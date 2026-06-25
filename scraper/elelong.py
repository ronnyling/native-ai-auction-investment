"""
elelong.py — e-Lelong (High Court of Malaya) scraper for the auction vault pipeline.

Discovery architecture (confirmed via browser inspection):
  - POST /BidderWeb/Home/SearchAuction → HTML fragment with listing cards
  - Each card has: <a href="/BidderWeb/Home/Detail/{id}" class="aIamInterested">
  - Pagination: <a id="aPageOf">of N</a>  → N pages × 20 per page
  - Filter: hiddenState (state code), hiddenPage (page number)
  - CSRF token from home page required in POST body

Delta strategy (per state):
  1. GET home page → obtain CSRF token + session cookies (once per run)
  2. POST SearchAuction page 1 → read total_pages + first-page IDs
  3. POST SearchAuction last page → read last-page IDs
  4. Compare (total_pages, first_ids, last_ids) against stored prev_search_state:
       MATCH   → state unchanged, skip paginating (zero wasted requests)
       MISMATCH → paginate ALL pages, collect full ID set for that state
  5. Fetch /Home/Detail/{id} for new IDs only (not in known_slugs)
  6. Return canonical listing dicts + updated search_state for persistence

Key characteristics:
  - Auction type: ALWAYS "Court Order" — e-Lelong is High Court of Malaya
  - IDs are NOT sequential; gaps exist (e.g. 89374 → 89523 on the same page)
    Sequential ID scanning will miss listings — SearchAuction is the only
    complete discovery method
  - Scraping per state for granular delta — only re-fetch states that changed
  - ~60 pages × 20 per page ≈ 1200 upcoming listings nationally (Jun 2026)
  - Rich embedded data: encumbrances, title number, register owner, case number
    (fields not available on BidNow/LelongTips)
"""

import json
import math
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL    = "https://elelong.kehakiman.gov.my"
INDEX_URL   = BASE_URL + "/BidderWeb/Home/Index"
SEARCH_URL  = BASE_URL + "/BidderWeb/Home/SearchAuction"
DETAIL_URL  = BASE_URL + "/BidderWeb/Home/Detail/{id}"
EFS_DOC_URL = (
    "https://efs.kehakiman.gov.my/EFSWeb/DocDownloader.aspx"
    "?DocumentID={doc_id}&Inline=true"
)

PAGE_SIZE       = 20
SEARCH_DELAY    = 0.6    # seconds between search-page requests (lighter)
DETAIL_DELAY    = 1.2    # seconds between detail-page requests (heavier)
REQUEST_TIMEOUT = 25

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-MY,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": INDEX_URL,
}

# State codes from home page filter dropdown (name="N" on each <a> in the list)
STATE_CODES: Dict[str, int] = {
    "Johor":           5,
    "Kedah":           6,
    "Kelantan":        7,
    "Melaka":          8,
    "Negeri Sembilan": 9,
    "Pahang":          10,
    "Perak":           12,
    "Perlis":          13,
    "Penang":          11,
    "Selangor":        16,
    "Terengganu":      17,
    "Kuala Lumpur":    2,
    "Putrajaya":       4,
}


class ELelongScraper:
    """
    Scrapes upcoming court auction listings from e-Lelong (kehakiman.gov.my).

    Usage:
        scraper = ELelongScraper()
        listings, new_state = scraper.scrape_listings(
            known_slugs=existing_slug_set,
            prev_search_state=loaded_state_dict,
        )
        # persist new_state between runs for delta efficiency
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._csrf_token: str = ""

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape_listings(
        self,
        known_slugs: Set[str] = None,
        prev_search_state: Dict = None,
        states: List[str] = None,
        max_listings: int = 2000,
    ) -> Tuple[List[Dict], Dict]:
        """
        Scrape all upcoming listings from e-Lelong.

        Parameters
        ----------
        known_slugs        : set of "EL-{id}" slugs already in the vault
        prev_search_state  : dict returned by the previous run (delta check)
        states             : state names to scrape; default = all 13 states
        max_listings       : hard cap on total listings returned this run

        Returns
        -------
        (listings, new_search_state)
          listings          -- list of canonical listing dicts (new only)
          new_search_state  -- persist this and pass as prev_search_state next run
        """
        known_slugs       = known_slugs or set()
        prev_search_state = prev_search_state or {}
        target_states     = states or list(STATE_CODES.keys())
        today             = date.today().isoformat()

        # One home-page fetch per run: get CSRF token + seed session cookies
        self._csrf_token = self._fetch_csrf_token()
        if not self._csrf_token:
            print("  [e-Lelong] WARNING: no CSRF token — search may fail")

        new_search_state: Dict = {}
        all_new_ids: Set[int]  = set()

        for state_name in target_states:
            state_id = STATE_CODES.get(state_name)
            if state_id is None:
                continue

            new_ids, updated_state = self._check_and_collect_state(
                state_name, state_id,
                known_slugs,
                prev_search_state.get(state_name, {}),
            )
            new_search_state[state_name] = updated_state
            all_new_ids.update(new_ids)

            skipped = "SKIP (unchanged)" if not new_ids and updated_state == prev_search_state.get(state_name, {}) else f"{len(new_ids)} new IDs"
            print(
                f"  [e-Lelong] {state_name:20s}: "
                f"cnt {updated_state.get('total_count', 0):4d} "
                f"pg {updated_state.get('total_pages', 0):3d}, {skipped}"
            )

            time.sleep(SEARCH_DELAY)

        # Fetch detail pages for new IDs only
        listings: List[Dict] = []
        for detail_id in sorted(all_new_ids):
            if len(listings) >= max_listings:
                break
            r = self._get(DETAIL_URL.format(id=detail_id))
            if not r or r.status_code != 200:
                time.sleep(DETAIL_DELAY * 0.5)
                continue
            listing = self._parse_detail(r.text, detail_id)
            if listing and listing.get("auction_date", "") >= today:
                listings.append(listing)
            time.sleep(DETAIL_DELAY)

        print(f"  [e-Lelong] Total: {len(listings)} upcoming listings scraped")
        return listings, new_search_state

    # ── Delta check + ID collection (per state) ───────────────────────────────

    def _check_and_collect_state(
        self,
        state_name: str,
        state_id: int,
        known_slugs: Set[str],
        prev_state: Dict,
    ) -> Tuple[Set[int], Dict]:
        """
        Check if a state has changed since the last run.
        Only paginates in full when the delta check fails.

        SearchAuction returns JSON: {totalCount, auctions: [{RowId, ...}]}
        pageIndex is 0-based (page 1 = pageIndex 0).

        Returns (new_ids, updated_state_dict).
        """
        # Step 1: pageIndex 0 (page 1) → totalCount + first-page RowIds
        data1 = self._search_page(state_id, 0)
        if not data1:
            return set(), prev_state

        total_count = data1.get("totalCount", 0)
        total_pages = math.ceil(total_count / PAGE_SIZE) if total_count else 0
        page1_ids   = [a["RowId"] for a in data1.get("auctions") or [] if "RowId" in a]

        if not page1_ids:
            return set(), {"total_count": 0, "total_pages": 0, "first_ids": [], "last_ids": []}

        # Step 2: last page → last-page IDs (skip extra fetch if only 1 page)
        if total_pages > 1:
            time.sleep(SEARCH_DELAY)
            data_last = self._search_page(state_id, total_pages - 1)  # 0-based
            last_ids  = [a["RowId"] for a in (data_last or {}).get("auctions") or [] if "RowId" in a]
        else:
            last_ids = list(page1_ids)

        # Step 3: delta check — unchanged if count AND both bookmark sets match
        if (
            prev_state.get("total_count") == total_count
            and set(prev_state.get("first_ids", [])) == set(page1_ids)
            and set(prev_state.get("last_ids", []))  == set(last_ids)
        ):
            # Nothing changed for this state
            return set(), prev_state

        # Step 4: changed — paginate all remaining pages (0-based index)
        all_ids: Set[int] = set(page1_ids)
        all_ids.update(last_ids)

        for page_idx in range(1, total_pages - 1):  # already have idx 0 and total_pages-1
            time.sleep(SEARCH_DELAY)
            data_p = self._search_page(state_id, page_idx)
            if data_p:
                all_ids.update(
                    a["RowId"] for a in data_p.get("auctions") or [] if "RowId" in a
                )

        # Step 5: filter to only IDs not yet in the vault
        new_ids = {id_ for id_ in all_ids if f"EL-{id_}" not in known_slugs}

        updated_state = {
            "total_count": total_count,
            "total_pages": total_pages,
            "first_ids":   page1_ids,
            "last_ids":    last_ids,
            "scraped_at":  str(date.today()),
        }
        return new_ids, updated_state

    # ── Search API helpers ────────────────────────────────────────────────────

    def _fetch_csrf_token(self) -> str:
        """GET home page once to obtain the ASP.NET anti-forgery token."""
        r = self._get(INDEX_URL)
        if not r or r.status_code != 200:
            return ""
        m = re.search(
            r'name="__RequestVerificationToken"[^>]+value="([^"]+)"',
            r.text,
        )
        return m.group(1) if m else ""

    def _search_page(self, state_id: int, page_index: int) -> Optional[Dict[str, Any]]:
        """
        POST SearchAuction and return the parsed JSON dict, or None on failure.

        Parameter names from ecourt.elelong.bidder.index.home.js:
          state, priceRange, landUsed, restrictionInInterest, tenure,
          auctionDate, propertyAddress, pageIndex (0-based), pageSize

        Response JSON: {totalCount: int, auctions: [{RowId, AuctionDate,
          AuctionStatecode, Status, ReservedPrice, LandTitle, ImageFile,
          Properties: [{District, Tenure}]}, ...], errorCode, errorMessage}
        """
        payload = {
            "__RequestVerificationToken": self._csrf_token,
            "state":                str(state_id),
            "priceRange":           "0",
            "landUsed":             "0",
            "restrictionInInterest":"0",
            "tenure":               "0",
            "pageSize":             str(PAGE_SIZE),
            "pageIndex":            str(page_index),   # 0-based
            "propertyAddress":      "",
            "auctionDate":          "",
        }
        extra_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type":
                "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        try:
            r = self.session.post(
                SEARCH_URL,
                data=payload,
                headers={**self.session.headers, **extra_headers},
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    # _parse_card_ids and _parse_total_pages replaced by JSON parsing:
    # SearchAuction returns {totalCount, auctions:[{RowId,...}]}.
    # See _check_and_collect_state for usage.

    # ── Detail page parsing ───────────────────────────────────────────────────

    def _parse_detail(self, html: str, listing_id: int) -> Optional[Dict]:
        """Parse a /Home/Detail/{id} page and return a canonical listing dict."""
        soup = BeautifulSoup(html, "html.parser")

        # var properties = [...] JSON embedded in inline <script>
        prop: Dict = {}
        pm = re.search(
            r'var\s+properties\s*=\s*(\[.*?\]);\s*(?:\n|$)', html, re.DOTALL
        )
        if not pm:
            pm = re.search(r'var\s+properties\s*=\s*(\[.+?\]);', html, re.DOTALL)
        if pm:
            try:
                arr = json.loads(pm.group(1))
                if arr:
                    prop = arr[0]
            except json.JSONDecodeError:
                pass

        # Auction date from: var date = new Date(Date.parse("..."))
        dm = re.search(
            r'var\s+date\s*=\s*new\s+Date\s*\(\s*Date\.parse\s*\(\s*"([^"]+)"\s*\)\s*\)',
            html,
        )
        auction_date, auction_time = self._parse_auction_datetime(
            dm.group(1) if dm else ""
        )

        # Label-pair fields from the rendered HTML
        reserve_price = self._parse_price(self._label_value(soup, "Reserved Price (RM)"))
        case_number   = self._label_value(soup, "Case Number") or prop.get("CaseNumber", "")
        state_raw     = self._label_value(soup, "State")
        land_title    = self._label_value(soup, "Land Title") or ""
        deposit_raw   = self._label_value(soup, "Deposit (Refundable)")
        deposit_amt   = self._parse_price(deposit_raw) if deposit_raw else 0
        deposit_pct   = round(deposit_amt / reserve_price * 100) if reserve_price else 10

        # POS document from EFS system
        pos_url = ""
        posm = re.search(r'DocumentID=([a-f0-9\-]{36})&Inline=true', html)
        if posm:
            pos_url = EFS_DOC_URL.format(doc_id=posm.group(1))

        # Property fields from JSON embed
        built_up  = float(prop.get("BuiltUp")   or 0)
        land_area = float(prop.get("LandArea")  or 0)
        city      = prop.get("City") or prop.get("District") or prop.get("Mukim", "")

        days_to_auction = 0
        if auction_date:
            try:
                delta = datetime.strptime(auction_date, "%Y-%m-%d").date() - date.today()
                days_to_auction = delta.days
            except ValueError:
                pass

        return {
            # Identity
            "listing_id":  f"EL-{listing_id}",
            "elelong_id":  listing_id,
            "source":      "elelong",
            "url":         DETAIL_URL.format(id=listing_id),

            # Address
            "full_address": prop.get("PostalAddress", ""),
            "postcode":     prop.get("Postcode", ""),
            "district":     city,
            "state":        self._normalise_state(state_raw),

            # Property
            "property_type":  self._normalise_property_type(prop.get("PropertyType", "")),
            "built_up_sqft":  int(built_up),
            "land_area_sqft": int(land_area),
            "tenure":         (prop.get("Tenure") or "").lower(),
            "restriction":    prop.get("RestrictionInInterest", ""),
            "auction_type":   "Court Order",

            # Auction
            "auction_date":      auction_date,
            "auction_time":      auction_time,
            "days_to_auction":   days_to_auction,
            "reserve_price":     reserve_price,
            "market_value":      0,
            "bmv_percent":       0,
            "auction_count":     1,
            "original_reserve":  reserve_price,
            "total_price_drop":  0,

            # Parties
            "bank":           prop.get("BankName", ""),
            "lawyer":         "",
            "auctioneer":     "",
            "borrower":       prop.get("RegisterOwner", ""),
            "deposit_pct":    deposit_pct,
            "deposit_amount": deposit_amt,

            # POS
            "pos_url":       pos_url,
            "pos_file_path": "",

            # History
            "auction_history": [],

            # e-Lelong exclusive fields (not on BidNow)
            "case_number":    case_number,
            "title_number":   prop.get("TitleNumber", ""),
            "land_title_type":land_title,
            "encumbrances":   prop.get("Emcumbrances", ""),
            "building_name":  prop.get("BuildingName", ""),
            "unit_number":    prop.get("UnitNumber", ""),

            # Scrape meta
            "scrape_date": str(date.today()),
            "tags":        ["court-order"],
        }

    # ── HTML label helper ─────────────────────────────────────────────────────

    def _label_value(self, soup: BeautifulSoup, label_text: str) -> Optional[str]:
        """
        Find a <label> whose text contains label_text; return the next sibling
        label's text (the value cell in a two-column label layout).
        """
        for lbl in soup.find_all("label"):
            if label_text.lower() in lbl.get_text(strip=True).lower():
                parent = lbl.parent
                siblings = parent.find_all("label") if parent else []
                if len(siblings) >= 2:
                    val = siblings[-1].get_text(strip=True)
                    if val and val.lower() not in label_text.lower():
                        return val
        return None

    # ── Type/value parsers ────────────────────────────────────────────────────

    def _parse_auction_datetime(self, raw: str) -> Tuple[str, str]:
        """'Thu, 25 Jun 2026 09:00:00' → ('2026-06-25', '09:00')."""
        if not raw:
            return "", ""
        for fmt in [
            "%a, %d %b %Y %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d %b %Y %H:%M:%S",
        ]:
            try:
                dt = datetime.strptime(raw.strip(), fmt)
                return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
            except ValueError:
                continue
        return raw[:10] if len(raw) >= 10 else "", ""

    def _parse_price(self, text: Optional[str]) -> int:
        """'RM 279,000.00' → 279000."""
        if not text:
            return 0
        try:
            return int(float(re.sub(r"[^\d.]", "", text.replace(",", ""))))
        except (ValueError, TypeError):
            return 0

    def _normalise_state(self, raw: Optional[str]) -> str:
        if not raw:
            return ""
        state_map = {
            "wilayah persekutuan kuala lumpur": "Kuala Lumpur",
            "wilayah persekutuan putrajaya":    "Putrajaya",
            "wilayah persekutuan labuan":       "Labuan",
            "pulau pinang":                     "Penang",
            "johor":           "Johor",
            "kedah":           "Kedah",
            "kelantan":        "Kelantan",
            "melaka":          "Melaka",
            "negeri sembilan": "Negeri Sembilan",
            "pahang":          "Pahang",
            "perak":           "Perak",
            "perlis":          "Perlis",
            "selangor":        "Selangor",
            "terengganu":      "Terengganu",
            "sabah":           "Sabah",
            "sarawak":         "Sarawak",
        }
        return state_map.get(raw.strip().lower(), raw.strip())

    def _normalise_property_type(self, raw: str) -> str:
        if not raw:
            return "residential"
        r = raw.strip().lower()
        if r in ("apartment", "flat"):
            return r
        if r in ("condominium", "condo"):
            return "condominium"
        if r in ("soho", "serviced apartment", "serviced residence"):
            return "apartment"
        if "bungalow" in r:
            return "bungalow"
        if "semi" in r:
            return "semi_detached"
        if r in ("terrace", "townhouse", "link house"):
            return "terrace"
        if r in ("land", "agricultural", "agriculture", "vacant land"):
            return "land"
        if r in ("shop", "shophouse", "commercial", "office", "retail"):
            return "shop"
        if r in ("warehouse", "industrial", "factory"):
            return "warehouse"
        return "residential"

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _get(self, url: str) -> Optional[requests.Response]:
        try:
            return self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        except Exception:
            return None
