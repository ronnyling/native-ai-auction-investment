"""
market_research.py — Area-level market data for auction property enrichment.

Strategy:
  - Scrape iProperty.com.my national sale + rent listing pages (paginated)
  - Each embedded listing carries its own district/state metadata
  - Group scraped listings by (district, state) to build PSF benchmarks
  - Cache results in market_cache.json with 7-day TTL
  - Enrich high-priority auction properties: bmv_pct >= 29 OR auction_count >= 3

Computed fields added to each qualifying listing dict:
  market_sale_psf      float  RM/sqft median sale price in matched area
  market_rent_psf      float  RM/sqft/month median rental in matched area
  market_rent_est      int    estimated monthly rent  = market_rent_psf × sqft
  market_value_est     int    independent market value = market_sale_psf × sqft
  independent_bmv_pct  int    ((market_value_est − reserve_price) / market_value_est) × 100
  est_rental_yield     float  (market_rent_psf × 12 / market_sale_psf) × 100
  market_comps_date    str    ISO date cache was built
  market_comps_n       int    number of comps used for the lookup
  market_source        str    "iproperty"
  market_area_match    str    "district" | "state" | "none"

Known limitations (to evaluate during testing):
  - iProperty featured listings are biased toward KL/Selangor premium properties
  - Only 8 of 16 states covered in 5-page national sample
  - PSF is type-agnostic (no apartment vs terrace split) due to URL filter ineffectiveness
  - District matching relies on substring fuzzy match against vault city field
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

IPROPERTY_SALE_BASE = "https://www.iproperty.com.my/property-for-sale"
IPROPERTY_RENT_BASE = "https://www.iproperty.com.my/property-for-rent"
PAGES_TO_SCRAPE = 5          # ~24 unique listings per page → ~120 total
CACHE_TTL_DAYS  = 7
MIN_COMPS_DISTRICT = 2       # minimum comps to trust district-level data
REQUEST_DELAY   = 1.3        # seconds between requests (polite crawling)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-MY,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# Criteria for high-priority (eligible for market enrichment)
HIGH_PRIORITY_BMV   = 29   # bmv_pct >= this
HIGH_PRIORITY_ROUND = 3    # auction_count >= this


# ── MarketResearcher class ────────────────────────────────────────────────────

class MarketResearcher:
    """
    Scrapes iProperty for area-level sale PSF and rent PSF,
    then enriches high-priority auction property listings with market data.
    """

    def __init__(self, cache_path: str):
        self.cache_path = Path(cache_path)
        self._cache: Optional[Dict] = None  # loaded lazily

    # ── Public API ────────────────────────────────────────────────────────────

    def enrich_listings(self, listings: List[Dict]) -> Tuple[int, int]:
        """
        Add market_* fields to each high-priority listing in-place.
        Returns (enriched_count, skipped_count).
        """
        cache = self._load_or_build_cache()
        enriched, skipped = 0, 0

        for listing in listings:
            if not self._is_high_priority(listing):
                skipped += 1
                continue

            state   = (listing.get("state") or "").strip()
            city    = (listing.get("city") or "").strip()
            sqft    = listing.get("built_up_sqft") or listing.get("land_area_sqft") or 0
            reserve = listing.get("reserve_price") or 0

            mkt = self._lookup(cache, state, city, sqft, reserve)
            if mkt:
                listing.update(mkt)
                enriched += 1
            else:
                skipped += 1

        return enriched, skipped

    def force_refresh(self):
        """Delete the cache and rebuild from iProperty."""
        if self.cache_path.exists():
            self.cache_path.unlink()
        self._cache = None
        self._load_or_build_cache()

    # ── Cache management ──────────────────────────────────────────────────────

    def _load_or_build_cache(self) -> Dict:
        if self._cache:
            return self._cache

        if self.cache_path.exists():
            try:
                with open(self.cache_path, encoding="utf-8") as f:
                    raw = json.load(f)
                built_at = datetime.fromisoformat(raw.get("built_at", "2000-01-01"))
                if datetime.now() - built_at < timedelta(days=CACHE_TTL_DAYS):
                    print(f"  [market] Cache loaded from {self.cache_path.name} "
                          f"(built {built_at.date()})")
                    self._cache = raw
                    return self._cache
                else:
                    print(f"  [market] Cache stale ({built_at.date()}) — rebuilding...")
            except Exception as e:
                print(f"  [market] Cache load error: {e} — rebuilding...")

        self._cache = self._build_cache()
        return self._cache

    def _build_cache(self) -> Dict:
        """Scrape iProperty and build district/state PSF lookup tables.
        Sale and rent scraping runs in parallel."""
        if not REQUESTS_AVAILABLE:
            print("  [market] requests not available — skipping market research")
            return self._empty_cache()

        print(f"  [market] Building market cache from iProperty "
              f"({PAGES_TO_SCRAPE} pages sale + {PAGES_TO_SCRAPE} pages rent)...")

        def _scrape_sale() -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
            session = requests.Session()
            session.headers.update(HEADERS)
            by_district: Dict[str, List[float]] = {}
            by_state: Dict[str, List[float]] = {}
            for page in range(1, PAGES_TO_SCRAPE + 1):
                url = f"{IPROPERTY_SALE_BASE}?page={page}"
                listings = self._fetch_page(session, url)
                for l in listings:
                    psf = self._parse_psf(l)
                    if not psf:
                        continue
                    district, state = self._get_area(l)
                    if district:
                        by_district.setdefault(district, []).append(psf)
                    if state:
                        by_state.setdefault(state, []).append(psf)
                print(f"    Sale page {page}/{PAGES_TO_SCRAPE}: "
                      f"{len(listings)} listings")
                time.sleep(REQUEST_DELAY)
            return by_district, by_state

        def _scrape_rent() -> Tuple[Dict[str, List[float]], Dict[str, List[float]]]:
            session = requests.Session()
            session.headers.update(HEADERS)
            by_district: Dict[str, List[float]] = {}
            by_state: Dict[str, List[float]] = {}
            for page in range(1, PAGES_TO_SCRAPE + 1):
                url = f"{IPROPERTY_RENT_BASE}?page={page}"
                listings = self._fetch_page(session, url)
                for l in listings:
                    price = self._parse_price(l)
                    sqft  = self._parse_sqft(l)
                    if not price or not sqft or sqft < 100:
                        continue
                    rent_psf = price / sqft
                    district, state = self._get_area(l)
                    if district:
                        by_district.setdefault(district, []).append(rent_psf)
                    if state:
                        by_state.setdefault(state, []).append(rent_psf)
                print(f"    Rent page {page}/{PAGES_TO_SCRAPE}: "
                      f"{len(listings)} listings")
                time.sleep(REQUEST_DELAY)
            return by_district, by_state

        # Run sale + rent in parallel
        with ThreadPoolExecutor(max_workers=2) as pool:
            sale_future = pool.submit(_scrape_sale)
            rent_future = pool.submit(_scrape_rent)
            sale_by_district, sale_by_state = sale_future.result()
            rent_by_district, rent_by_state = rent_future.result()

        # ── Build medians ──────────────────────────────────────────────────────
        cache = {
            "built_at": datetime.now().isoformat(),
            "sale_district": {
                k: {"median_psf": _median(v), "n": len(v)}
                for k, v in sale_by_district.items()
            },
            "sale_state": {
                k: {"median_psf": _median(v), "n": len(v)}
                for k, v in sale_by_state.items()
            },
            "rent_district": {
                k: {"median_rent_psf": _median(v), "n": len(v)}
                for k, v in rent_by_district.items()
            },
            "rent_state": {
                k: {"median_rent_psf": _median(v), "n": len(v)}
                for k, v in rent_by_state.items()
            },
        }

        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)

        n_districts = len(sale_by_district)
        n_states    = len(sale_by_state)
        total_comps = sum(len(v) for v in sale_by_district.values())
        print(f"  [market] Cache built: {n_districts} districts, "
              f"{n_states} states, {total_comps} sale comps")
        return cache

    @staticmethod
    def _empty_cache() -> Dict:
        return {
            "built_at": datetime.now().isoformat(),
            "sale_district": {}, "sale_state": {},
            "rent_district": {}, "rent_state": {},
        }

    # ── Lookup ────────────────────────────────────────────────────────────────

    def _lookup(
        self,
        cache: Dict,
        state: str,
        city: str,
        sqft: float,
        reserve: float,
    ) -> Optional[Dict]:
        """Return market fields dict or None if no data found."""
        today_str = str(date.today())
        sale_district = cache.get("sale_district", {})
        sale_state    = cache.get("sale_state", {})
        rent_district = cache.get("rent_district", {})
        rent_state    = cache.get("rent_state", {})

        # Normalise city for lookup
        city_clean = _clean_city_for_lookup(city)
        state_key  = state.lower().strip()

        # ── Sale PSF ──────────────────────────────────────────────────────────
        sale_psf, sale_n, match_level = None, 0, "none"

        # Try district match (exact then substring)
        district_key = _fuzzy_district_match(city_clean, sale_district)
        if district_key and sale_district[district_key]["n"] >= MIN_COMPS_DISTRICT:
            sale_psf    = sale_district[district_key]["median_psf"]
            sale_n      = sale_district[district_key]["n"]
            match_level = "district"

        # Fall back to state
        if not sale_psf and state_key in sale_state:
            sale_psf    = sale_state[state_key]["median_psf"]
            sale_n      = sale_state[state_key]["n"]
            match_level = "state"

        if not sale_psf:
            return None  # No market data available for this area

        # ── Rent PSF ──────────────────────────────────────────────────────────
        rent_psf = None
        district_key_rent = _fuzzy_district_match(city_clean, rent_district)
        if district_key_rent and rent_district[district_key_rent]["n"] >= MIN_COMPS_DISTRICT:
            rent_psf = rent_district[district_key_rent]["median_rent_psf"]
        elif state_key in rent_state:
            rent_psf = rent_state[state_key]["median_rent_psf"]

        # ── Derived fields ────────────────────────────────────────────────────
        market_value_est = round(sale_psf * sqft) if sqft else None
        market_rent_est  = round(rent_psf * sqft) if (rent_psf and sqft) else None

        independent_bmv = None
        if market_value_est and market_value_est > 0 and reserve > 0:
            independent_bmv = round(
                (market_value_est - reserve) / market_value_est * 100
            )

        est_yield = None
        if rent_psf and sale_psf and sale_psf > 0:
            est_yield = round(rent_psf * 12 / sale_psf * 100, 1)

        return {
            "market_sale_psf":     round(sale_psf, 2),
            "market_rent_psf":     round(rent_psf, 3) if rent_psf else None,
            "market_rent_est":     market_rent_est,
            "market_value_est":    market_value_est,
            "independent_bmv_pct": independent_bmv,
            "est_rental_yield":    est_yield,
            "market_comps_date":   today_str,
            "market_comps_n":      sale_n,
            "market_source":       "iproperty",
            "market_area_match":   match_level,
        }

    # ── iProperty scraping ────────────────────────────────────────────────────

    @staticmethod
    def _fetch_page(session: "requests.Session", url: str) -> List[Dict]:
        """Fetch one iProperty page and return unique listing dicts."""
        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            print(f"    [market] fetch error {url}: {exc}")
            return []
        return MarketResearcher._extract_listings(r.text)

    @staticmethod
    def _extract_listings(html: str) -> List[Dict]:
        """Extract all unique `listingData` JSON objects from iProperty HTML."""
        listings: List[Dict] = []
        seen: set = set()
        for m in re.finditer(r'"listingData":\{', html):
            start = m.start() + len('"listingData":')
            depth, end = 0, start
            for i in range(start, min(start + 25_000, len(html))):
                if html[i] == "{":
                    depth += 1
                elif html[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            try:
                obj = json.loads(html[start:end])
                lid = obj.get("id") or obj.get("externalId")
                if lid and lid not in seen:
                    seen.add(lid)
                    listings.append(obj)
            except Exception:
                pass
        return listings

    @staticmethod
    def _parse_psf(listing: Dict) -> Optional[float]:
        """Extract PSF from psfText e.g. 'RM 1,361.39 psf' → 1361.39"""
        t = listing.get("psfText", "") or ""
        m = re.search(r"[\d,]+\.?\d*", t.replace(",", ""))
        return float(m.group()) if m else None

    @staticmethod
    def _parse_price(listing: Dict) -> Optional[float]:
        p = listing.get("price", {})
        v = p.get("value") if isinstance(p, dict) else p
        return float(v) if v and float(v) > 0 else None

    @staticmethod
    def _parse_sqft(listing: Dict) -> Optional[float]:
        v = listing.get("floorArea")
        return float(v) if v and float(v) > 0 else None

    @staticmethod
    def _get_area(listing: Dict) -> Tuple[str, str]:
        """Return (district_lower, state_lower) from additionalData."""
        ad = listing.get("additionalData", {}) or {}
        district = (ad.get("districtText") or "").strip().lower()
        state    = (ad.get("regionText") or "").strip().lower()
        return district, state

    @staticmethod
    def _is_high_priority(listing: Dict) -> bool:
        bmv   = float(listing.get("bmv_pct") or listing.get("bmv_percent") or 0)
        count = int(listing.get("auction_count") or 1)
        return bmv >= HIGH_PRIORITY_BMV or count >= HIGH_PRIORITY_ROUND


# ── Utility functions ─────────────────────────────────────────────────────────

def _median(vals: List[float]) -> Optional[float]:
    v = sorted(x for x in vals if x and x > 0)
    if not v:
        return None
    mid = len(v) // 2
    return round(v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2, 2)


def _clean_city_for_lookup(city: str) -> str:
    """
    Normalise vault city field for district lookup.
    e.g. '40100 Shah Alam' → 'shah alam'
         'Jalan Perak'     → 'jalan perak'
    """
    # Strip leading postcode
    city = re.sub(r"^\d{5}\s*", "", city).strip()
    return city.lower()


def _fuzzy_district_match(city_key: str, lookup: Dict) -> Optional[str]:
    """
    Try to match `city_key` against keys in `lookup` dict.
    1. Exact match
    2. City key is substring of district key  (e.g. 'puchong' in 'puchong perdana')
    3. District key is substring of city key
    """
    if not city_key:
        return None

    # Exact
    if city_key in lookup:
        return city_key

    # Substring both directions
    for key in lookup:
        if city_key in key or key in city_key:
            return key

    return None
