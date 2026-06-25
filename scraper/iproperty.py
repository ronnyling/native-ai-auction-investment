"""
iproperty.py — iProperty.com.my competition signal scraper.

Purpose: gauge how many similar properties are actively marketed in the
same locale as an auction target, using price + size as proxies.

Why NOT address matching:
  iProperty hides exact unit addresses on listing cards to protect agent
  exclusivity. Full addresses are only visible after a lead inquiry.
  Therefore address-based matching against auction records is unreliable.

Competition signal approach (price + size + locale):
  Given an auction property at RM X, Y sqft built-up (+ optional land sqft) in district Z:
    1. Search iProperty for state + property type (+ optional district).
    2. Filter results where built_up_sqft is within ±size_tolerance% of Y.
       For landed properties: ALSO filter where land_area_sqft is within
       ±size_tolerance% of the target land area (same lot size = same layout).
    3. Within the size-matched set, filter asking_price within ±price_tolerance% of X.
    4. Count of matching listings = competition density for that locale.
  A count >= 3 means retail buyers are actively looking at similar
  properties — expect higher bidding competition at auction.

URL patterns (confirmed accessible, SSR, no anti-bot):
  - /sale/{state-slug}/{type-slug}/              state-level area search
  - /sale/{state-slug}/{district-slug}/{type}/   district-level (more precise)
  - /property-for-sale?q=bank+auction            keyword search

Data source: embedded "listingData":{...} JSON objects, extracted via
json.JSONDecoder.raw_decode() — fast O(n) parse of 1-2MB HTML pages.
Note: each listing appears TWICE in SSR HTML (card + drawer panel).
Deduplicate by listing ID before returning.

Key output fields per listing:
  listing_id, asking_price, price_psf, built_up_sqft, land_area_sqft, title,
  full_address (partial/area name only), scrape_date
  (land_area_sqft populated for landed properties; 0 for condos/apartments)
"""

import json
import re
import time
from datetime import date
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.iproperty.com.my"
SEARCH_URL = BASE_URL + "/property-for-sale"
REQUEST_TIMEOUT = 30
PAGE_DELAY = 1.0
PAGE_SIZE = 24  # iProperty default


class IPropertyScraper:
    """
    Scrape iProperty for auction-related listings (market/competition signal).

    Approach: extract embedded "listingData" JSON objects from SSR HTML using
    json.JSONDecoder.raw_decode() for reliable, fast extraction from 1-2MB pages.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept-Language": "en-MY,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self._decoder = json.JSONDecoder()

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape_competition_signal(
        self,
        query: str = "bank auction",
        max_pages: int = 2,
    ) -> List[Dict]:
        """
        Scrape iProperty for a keyword and return standardised listing data.

        Args:
            query:      Keyword — "bank auction", "laca", or "foreclosure"
            max_pages:  Max pages (default 2 = ~48 unique listings)

        Returns:
            List of standardised listing dicts.
        """
        all_listings: List[Dict] = []
        seen_ids: set = set()

        for page in range(1, max_pages + 1):
            print(f"  [iProperty] '{query}' page {page}/{max_pages} ...")
            params = {"q": query}
            if page > 1:
                params["page"] = page

            try:
                resp = self.session.get(
                    SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
            except Exception as exc:
                print(f"  [iProperty] fetch error page {page}: {exc}")
                break

            listings = self._extract_listings(resp.text)
            if not listings:
                print(f"  [iProperty] no listings on page {page}, stopping")
                break

            new_count = 0
            for item in listings:
                lid = item.get("listing_id", "")
                if lid and lid not in seen_ids:
                    seen_ids.add(lid)
                    all_listings.append(item)
                    new_count += 1

            print(f"  [iProperty] page {page}: {len(listings)} blocks, {new_count} unique new")

            if page < max_pages:
                time.sleep(PAGE_DELAY)

        print(f"  [iProperty] total: {len(all_listings)} unique listings")
        return all_listings

    def scrape_area_listings(
        self,
        state_slug: str,
        property_category: str = "apartment-condo",
        district_slug: str = "",
        max_pages: int = 2,
    ) -> List[Dict]:
        """
        Scrape iProperty listings for a locale (state + optional district).

        This is the primary data-gathering method for competition signal.
        Addresses are partial (area name only) — do not attempt exact matching.

        Args:
            state_slug:         URL slug, e.g. "selangor", "kuala-lumpur"
            property_category:  URL slug, e.g. "apartment-condo", "terrace-house"
            district_slug:      Optional district, e.g. "subang-jaya", "cheras"
            max_pages:          Pages to scrape (default 2 = ~48 unique listings)

        Returns:
            List of listing dicts with asking_price, price_psf, built_up_sqft.
        """
        all_listings: List[Dict] = []
        seen_ids: set = set()

        for page in range(1, max_pages + 1):
            if district_slug:
                url = f"{BASE_URL}/sale/{state_slug}/{district_slug}/{property_category}/"
            else:
                url = f"{BASE_URL}/sale/{state_slug}/{property_category}/"
            params = {"page": page} if page > 1 else {}

            print(f"  [iProperty] area '{state_slug}/{district_slug or property_category}' page {page}/{max_pages}")
            try:
                resp = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
            except Exception as exc:
                print(f"  [iProperty] fetch error: {exc}")
                break

            listings = self._extract_listings(resp.text)
            if not listings:
                break

            for item in listings:
                lid = item.get("listing_id", "")
                if lid and lid not in seen_ids:
                    seen_ids.add(lid)
                    all_listings.append(item)

            if page < max_pages:
                time.sleep(PAGE_DELAY)

        print(f"  [iProperty] area total: {len(all_listings)} unique listings")
        return all_listings

    def get_competition_signal(
        self,
        target_price: float,
        target_sqft: float,
        state_slug: str,
        property_category: str = "apartment-condo",
        district_slug: str = "",
        price_tolerance_pct: float = 25.0,
        size_tolerance_pct: float = 10.0,
        max_pages: int = 2,
        target_land_sqft: float = 0.0,
    ) -> Dict:
        """
        Measure how many iProperty listings in the same locale are
        comparable to an auction target, as a proxy for retail-buyer
        competition.

        Matching strategy:
          - Size is the PRIMARY filter: properties of the same size share
            the same floor layout, making them directly interchangeable to
            a buyer. Different sizes imply different layouts and different
            buyer pools, so price comparison across sizes is misleading.
          - Price is the SECONDARY filter: within the matched size band,
            we narrow to listings whose asking price is within
            ±price_tolerance_pct of the auction reserve price.
          - If target_sqft is unknown (0): no comparables are returned and
            competition_level is set to "Unknown" — do not guess.

        Default tolerances:
          size_tolerance_pct = 10%  (tight — same layout assumption)
          price_tolerance_pct = 25% (looser — price varies by condition/floor)

        For LANDED properties (terrace, semi-D, bungalow):
          Pass target_land_sqft > 0 to also filter on land area.
          A different land lot size implies a different build configuration
          (e.g. 20x65 vs 20x80 intermediate terrace), so land area is used
          as an additional size constraint alongside built-up area.

        Full addresses are hidden by iProperty to protect agent exclusivity;
        locale precision is limited to state + optional district.

        Args:
            target_price:         Auction reserve price (RM)
            target_sqft:          Auction property built-up area (sqft).
                                  Pass 0 if unknown — returns "Unknown" signal.
            state_slug:           e.g. "selangor", "kuala-lumpur"
            property_category:    e.g. "apartment-condo", "terrace-link-house"
            district_slug:        Optional narrower locale, e.g. "subang-jaya"
            price_tolerance_pct:  ±% band for price matching (default 25)
            size_tolerance_pct:   ±% band for size matching (default 10)
            max_pages:            Pages to fetch for the area (default 2)
            target_land_sqft:     Land area (sqft) for landed properties (default 0).
                                  When > 0, also filters on land_area_sqft ±size_tolerance_pct.

        Returns:
            {
              "comparable_count":  int | None  — listings matching size+price band,
                                                 None if target_sqft unknown,
              "total_area_count":  int          — all listings scraped for locale,
              "size_matched_count": int | None  — listings matching size band only,
              "median_asking":     float        — median asking of comparables,
              "median_psf":        float        — median PSF of comparables,
              "price_range":       str          — "RM X - RM Y",
              "size_range":        str          — "X - Y sqft (land: A - B sqft)",
              "competition_level": str          — "Low"/"Medium"/"High"/"Unknown",
              "size_known":        bool         — False means signal is unreliable,
              "locale":            str          — human-readable locale label,
            }
        """
        locale_label = (
            district_slug.replace("-", " ").title()
            or state_slug.replace("-", " ").title()
        )
        locale_label += f" ({property_category.replace('-', ' ').title()})"

        # Size unknown — cannot make a reliable comparison
        if not target_sqft or target_sqft <= 0:
            print(f"  [iProperty] size unknown — skipping comparison for {locale_label}")
            return {
                "comparable_count":   None,
                "total_area_count":   0,
                "size_matched_count": None,
                "median_asking":      0.0,
                "median_psf":         0.0,
                "price_range":        "no data",
                "size_range":         "no data",
                "competition_level":  "Unknown",
                "size_known":         False,
                "locale":             locale_label,
            }

        listings = self.scrape_area_listings(
            state_slug, property_category, district_slug, max_pages
        )

        size_lo  = target_sqft * (1 - size_tolerance_pct  / 100)
        size_hi  = target_sqft * (1 + size_tolerance_pct  / 100)
        price_lo = target_price * (1 - price_tolerance_pct / 100)
        price_hi = target_price * (1 + price_tolerance_pct / 100)

        # Land area bounds (landed properties only)
        land_lo = target_land_sqft * (1 - size_tolerance_pct / 100) if target_land_sqft > 0 else None
        land_hi = target_land_sqft * (1 + size_tolerance_pct / 100) if target_land_sqft > 0 else None

        # Step 1: filter by size (primary) — listings without size data are excluded.
        # For landed properties, ALSO enforce land area band (same lot = same build config).
        def _size_match(l: Dict) -> bool:
            if not (l.get("built_up_sqft") and size_lo <= l["built_up_sqft"] <= size_hi):
                return False
            if land_lo is not None:
                land = l.get("land_area_sqft") or 0
                # Only apply land filter when the listing actually has land area data
                if land > 0 and not (land_lo <= land <= land_hi):
                    return False
            return True

        size_matched = [l for l in listings if _size_match(l)]

        # Step 2: filter by price within the size-matched set (secondary)
        comparables = [
            l for l in size_matched
            if l.get("asking_price") and price_lo <= l["asking_price"] <= price_hi
        ]

        count = len(comparables)
        prices  = sorted(l["asking_price"]   for l in comparables if l.get("asking_price"))
        psfs    = sorted(l["price_psf"]       for l in comparables if l.get("price_psf"))
        sizes   = sorted(l["built_up_sqft"]   for l in comparables if l.get("built_up_sqft"))
        lands   = sorted(l["land_area_sqft"]  for l in comparables if l.get("land_area_sqft"))

        def median(vals):
            if not vals:
                return 0.0
            mid = len(vals) // 2
            return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2

        if count <= 2:
            level = "Low"
        elif count <= 5:
            level = "Medium"
        else:
            level = "High"

        return {
            "comparable_count":   count,
            "total_area_count":   len(listings),
            "size_matched_count": len(size_matched),
            "median_asking":      median(prices),
            "median_psf":         median(psfs),
            "price_range":        f"RM {min(prices):,.0f} - RM {max(prices):,.0f}" if prices else "no data",
            "size_range":         (
                f"{min(sizes):,.0f} - {max(sizes):,.0f} sqft"
                + (f" (land: {min(lands):,.0f} - {max(lands):,.0f} sqft)" if lands else "")
            ) if sizes else "no data",
            "competition_level":  level,
            "size_known":         True,
            "locale":             locale_label,
        }

    # ── Internal: parse ───────────────────────────────────────────────────────

    def _extract_listings(self, html: str) -> List[Dict]:
        """Extract listingData objects from HTML using raw_decode (fast, O(n))."""
        listings = []
        decoder = self._decoder

        for m in re.finditer(r'"listingData"\s*:\s*\{', html):
            pos = m.end() - 1  # start of '{' character
            try:
                obj, _ = decoder.raw_decode(html, pos)
                listings.append(self._normalise(obj))
            except Exception:
                pass

        return listings

    def _normalise(self, item: Dict) -> Dict:
        """Map raw iProperty listingData dict to standardised output."""
        today = date.today().isoformat()

        lid = str(item.get("id") or item.get("externalId") or "")
        title = item.get("localizedTitle") or item.get("title") or ""

        # Build URL from profile URL slug or construct from id
        listing_url = item.get("listingUrl") or item.get("profileUrl") or ""
        if listing_url and not listing_url.startswith("http"):
            listing_url = BASE_URL + listing_url

        full_address = item.get("fullAddress") or item.get("address") or ""
        district = item.get("district") or ""
        state = item.get("stateRegion") or item.get("state") or item.get("region") or ""

        # Price
        price_raw = item.get("price") or {}
        if isinstance(price_raw, dict):
            asking_price = float(price_raw.get("value") or price_raw.get("amount") or 0)
        else:
            asking_price = float(price_raw or 0)

        psf_text = item.get("psfText") or ""
        price_psf: Optional[float] = None
        if psf_text:
            m = re.search(r"[\d,]+\.?\d*", psf_text.replace(",", ""))
            if m:
                price_psf = float(m.group())

        floor_area = float(item.get("floorArea") or 0)
        land_area  = float(item.get("landArea") or item.get("landSize") or 0)
        prop_type = item.get("subTypeText") or item.get("propertyType") or ""
        tenure = ""
        furnished = ""

        bedrooms = 0
        bathrooms = 0
        for feat_group in (item.get("listingFeatures") or []):
            if isinstance(feat_group, list):
                for feat in feat_group:
                    auto_id = feat.get("dataAutomationId", "")
                    if "bedroom" in auto_id:
                        try:
                            bedrooms = int(feat.get("text") or 0)
                        except ValueError:
                            pass
                    elif "bathroom" in auto_id:
                        try:
                            bathrooms = int(feat.get("text") or 0)
                        except ValueError:
                            pass

        return {
            "listing_id": f"IP-{lid}",
            "source": "iproperty",
            "url": listing_url,
            "title": title,
            "full_address": full_address,
            "state": state,
            "district": district,
            "property_type": prop_type,
            "built_up_sqft": floor_area,
            "land_area_sqft": land_area,
            "asking_price": asking_price,
            "price_psf": price_psf,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "tenure": tenure,
            "furnished": furnished,
            "scrape_date": today,
        }
