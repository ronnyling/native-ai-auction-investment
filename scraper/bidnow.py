"""
bidnow.py — BidNow.my scraper for the auction vault pipeline.

Ported from goal_6_prop/orchestrator/utilities/bidnow_scraper.py.
Strips Telegram/agent imports; exposes BidNowScraper for use by main.py.

BidNow embeds full listing data in a JavaScript variable:
    var aps = {"current_page":1, "data":[...], "last_page":7, "total":81}
No login required for: address, price, bank, lawyer, auctioneer, POS file path,
BMV%, sqft, tenure, auction type, deposit — all in the public page HTML.
"""

import json
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlencode

import requests

from bidnow_filter_enums import (
    BIDNOW_STATES,
    validate_state,
    validate_property_type,
    validate_auction_type,
    validate_listing_status,
    validate_sort_option,
)


class BidNowScraper:
    BASE_URL = "https://www.bidnow.my"
    LISTINGS_PAGE = "https://www.bidnow.my/properties/auction"
    REQUEST_TIMEOUT = 30

    TENURE_MAP = {1: "freehold", 2: "leasehold"}

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        })

    # ── URL builder ──────────────────────────────────────────────────────────

    def _build_listing_url(self, page: int = 1, filters: Dict = None) -> str:
        filters = filters or {}
        params = {}

        if filters.get("state") and validate_state(filters["state"]):
            params["state"] = filters["state"]

        if filters.get("property_type") and validate_property_type(filters["property_type"]):
            params["property_type"] = filters["property_type"]

        if filters.get("price_min") is not None:
            params["price_min"] = int(filters["price_min"])

        if filters.get("price_max") is not None:
            params["price_max"] = int(filters["price_max"])

        if filters.get("listing") and validate_listing_status(filters["listing"]):
            params["listing"] = filters["listing"]

        if filters.get("sort") and validate_sort_option(filters["sort"]):
            params["sort"] = filters["sort"]

        if filters.get("auction_type") and validate_auction_type(filters["auction_type"]):
            params["auction_type"] = filters["auction_type"]

        if filters.get("auction_date"):
            params["auction_date"] = filters["auction_date"]

        if filters.get("built_up_min") is not None:
            params["built_up_min"] = filters["built_up_min"]

        if filters.get("built_up_max") is not None:
            params["built_up_max"] = filters["built_up_max"]

        if filters.get("plaintiff_assignee"):
            params["plaintiff_assignee"] = filters["plaintiff_assignee"]

        if page > 1:
            params["page"] = page

        if params:
            return f"{self.LISTINGS_PAGE}?{urlencode(params, safe='/')}"
        return self.LISTINGS_PAGE

    # ── Main listing scrape ───────────────────────────────────────────────────

    def scrape_listings(
        self,
        filters: Dict = None,
        max_pages: int = None,
        known_ids: set = None,
    ) -> List[Dict]:
        """
        Scrape BidNow listings for a given state/filter set.

        Args:
            filters:    dict with keys like {"state": "Selangor", "listing": "active"}
            max_pages:  hard cap on pages scraped (None = scrape all)
            known_ids:  set of bidnow listing IDs already in the vault.
                        Scraping stops early when all IDs on a page are known
                        (delta mode — only pull genuinely new/updated listings).

        Returns:
            List of standardised listing dicts.
        """
        all_listings: List[Dict] = []
        filters = filters or {}
        known_ids = known_ids or set()
        seen_this_run: set = set()
        total_pages = max_pages or 1

        page = 1
        while page <= total_pages:
            print(f"  [BidNow] page {page}/{total_pages} ...")
            url = self._build_listing_url(page, filters)

            try:
                resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
                resp.raise_for_status()
                resp.encoding = "utf-8"
            except Exception as exc:
                print(f"  [BidNow] fetch error on page {page}: {exc}")
                break

            page_listings, pagination = self._extract_from_js(resp.text)

            if page == 1 and pagination.get("last_page"):
                discovered_total = pagination["last_page"]
                if max_pages is None:
                    total_pages = discovered_total
                else:
                    total_pages = min(max_pages, discovered_total)
                print(
                    f"  [BidNow] {pagination.get('total', '?')} total results "
                    f"across {discovered_total} pages"
                )

            if not page_listings:
                print(f"  [BidNow] no listings on page {page}, stopping")
                break

            new_count = 0
            all_known = True
            for listing in page_listings:
                lid = listing.get("listing_id", "")
                if not lid or lid in seen_this_run:
                    continue
                seen_this_run.add(lid)
                if lid not in known_ids:
                    all_known = False
                all_listings.append(listing)
                new_count += 1

            print(
                f"  [BidNow] page {page}: {new_count} listings "
                f"({sum(1 for l in all_listings if l['listing_id'] not in known_ids)} new total)"
            )

            # Delta stop: all IDs on this page already known → nothing newer to find
            if all_known and known_ids:
                print(f"  [BidNow] all IDs on page {page} already known — stopping early")
                break

            page += 1

        return all_listings

    def scrape_all_states(
        self,
        known_ids: set = None,
        listing_status: str = "active",
    ) -> List[Dict]:
        """Scrape all 15 BidNow states and return combined listing list."""
        results: List[Dict] = []
        known_ids = known_ids or set()
        for state in BIDNOW_STATES:
            print(f"\n[BidNow] Scraping state: {state}")
            filters = {"state": state, "listing": listing_status, "sort": "new"}
            listings = self.scrape_listings(filters=filters, known_ids=known_ids)
            results.extend(listings)
            print(f"  [BidNow] {state}: {len(listings)} listings")
        return results

    # ── JS extraction ─────────────────────────────────────────────────────────

    def _extract_from_js(self, html: str) -> Tuple[List[Dict], Dict]:
        """Extract listings from the embedded `var aps = {...}` JS variable."""
        listings: List[Dict] = []
        pagination: Dict = {}

        start = html.find("var aps = {")
        if start == -1:
            print("  [BidNow] 'var aps' not found in HTML")
            return [], {}

        json_start = start + len("var aps = ")
        depth = 0
        json_end = 0
        for i in range(json_start, len(html)):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break

        if not json_end:
            print("  [BidNow] could not find closing brace for 'var aps'")
            return [], {}

        try:
            data = json.loads(html[json_start:json_end])
        except json.JSONDecodeError as exc:
            print(f"  [BidNow] JSON parse error: {exc}")
            return [], {}

        pagination = {
            "total": data.get("total", 0),
            "last_page": data.get("last_page", 1),
            "per_page": data.get("per_page", 12),
            "from": data.get("from"),
            "to": data.get("to"),
            "current_page": data.get("current_page", 1),
        }

        for item in data.get("data", []):
            listing = self._convert_listing(item)
            if listing:
                listings.append(listing)

        return listings, pagination

    # ── Listing conversion ────────────────────────────────────────────────────

    def _convert_listing(self, item: Dict) -> Optional[Dict]:
        """Convert a raw BidNow `data` array item to a standardised dict."""
        try:
            prop = item.get("property", item)

            listing_id = str(item.get("id", ""))
            reserve_price = float(item.get("reserved_price", 0) or 0)
            bmv_percent = int(item.get("bmv_percent", 0) or 0)

            # Derive market value from BMV%
            # bmv_percent=34 means property is 34% below market value
            market_value = 0.0
            if bmv_percent > 0 and reserve_price > 0:
                market_value = round(reserve_price / (1 - bmv_percent / 100.0), 2)

            auction_type = (item.get("auction_type") or {}).get("name", "")
            listing_type = (item.get("listing_type") or {}).get("name", "")
            tenure_id = prop.get("ap_tenure_id")
            tenure = self.TENURE_MAP.get(tenure_id, "unknown")

            full_address = prop.get("full_address", "") or ""
            state, district = self._parse_location(full_address)

            bank = (item.get("plaintiff_assignee") or {}).get("name", "")
            lawyer = (item.get("ap_lawyer") or {}).get("name", "")
            auctioneer = (item.get("ap_auctioneer") or {}).get("name", "")
            borrower = item.get("defendant_assignor", "")

            built_up = float(item.get("built_up_size") or prop.get("built_up_size") or 0)
            land_area = float(item.get("land_area_size") or prop.get("land_area_size") or 0)
            restriction = (item.get("ap_restriction") or {}).get("name", "")

            deposit_pct = float(item.get("deposit_percent") or 10)
            deposit_amount = float(item.get("deposit_amount") or 0)

            pos_file_path = item.get("pos_file_path", "") or ""
            pos_url = self.get_pos_url(listing_id, pos_file_path) if pos_file_path else ""

            raw_type = prop.get("description", "") or ""

            return {
                "listing_id": listing_id,
                "reference_number": item.get("reference_number", ""),
                "title": prop.get("title", ""),
                "full_address": full_address,
                "state": state,
                "district": district,
                "property_type": self._normalise_type(raw_type),
                "property_type_raw": raw_type,
                "tenure": tenure,
                "restriction": restriction,
                "built_up_sqft": built_up,
                "land_area_sqft": land_area,
                "reserve_price": reserve_price,
                "market_value": market_value,
                "bmv_percent": bmv_percent,
                "auction_date": item.get("auction_date", ""),
                "auction_time": item.get("auction_time", ""),
                "auction_type": auction_type,
                "listing_type": listing_type,
                "bank": bank,
                "lawyer": lawyer,
                "auctioneer": auctioneer,
                "borrower": borrower,
                "deposit_pct": deposit_pct,
                "deposit_amount": deposit_amount,
                "average_market_rental": item.get("average_market_rental"),
                "pos_file_path": pos_file_path,
                "pos_url": pos_url,
                "source": "bidnow",
                "url": f"{self.BASE_URL}/auction-property/x/{listing_id}",
            }
        except Exception as exc:
            print(f"  [BidNow] convert error: {exc}")
            return None

    # ── Detail page (for re-auction history) ─────────────────────────────────

    def scrape_detail(self, listing_id: str) -> Optional[Dict]:
        """
        Scrape the detail page for a single listing.
        Returns full auction_history array (prior auction rounds).
        Used by dedup_merger to populate auction_history on re-auctions.
        """
        try:
            url = f"{self.BASE_URL}/auction-property/x/{listing_id}"
            resp = self.session.get(url, timeout=self.REQUEST_TIMEOUT)
            resp.raise_for_status()
            html = resp.text

            ap_data = self._extract_js_var(html, "ap") or {}
            property_data = self._extract_js_var(html, "property") or {}

            # Build full auction history from property.aps array
            auction_history = []
            for prev in property_data.get("aps", []):
                auction_history.append({
                    "auction_date": prev.get("auction_date", ""),
                    "reserve_price": float(prev.get("reserved_price", 0) or 0),
                    "bmv_percent": int(prev.get("bmv_percent", 0) or 0),
                })
            auction_history.sort(key=lambda x: x["auction_date"])

            pos_file_path = ap_data.get("pos_file_path", "") or ""

            return {
                "listing_id": str(ap_data.get("id", listing_id)),
                "property_id": str(ap_data.get("property_id", "")),
                "auction_history": auction_history,
                "auction_count": len(auction_history),
                "bank": (ap_data.get("plaintiff_assignee") or {}).get("name", ""),
                "lawyer": (ap_data.get("ap_lawyer") or {}).get("name", ""),
                "auctioneer": (ap_data.get("ap_auctioneer") or {}).get("name", ""),
                "borrower": ap_data.get("defendant_assignor", ""),
                "deposit_pct": float(ap_data.get("deposit_percent") or 10),
                "deposit_amount": float(ap_data.get("deposit_amount") or 0),
                "pos_file_path": pos_file_path,
                "pos_url": self.get_pos_url(listing_id, pos_file_path),
                "market_value": float(
                    property_data.get("market_value") or 0
                ),
            }
        except Exception as exc:
            print(f"  [BidNow] detail scrape error for {listing_id}: {exc}")
            return None

    def _extract_js_var(self, html: str, var_name: str) -> Optional[Dict]:
        """Extract a named JS variable like `var ap = {...}` or `var property = {...}`."""
        needle = f"var {var_name} = {{"
        start = html.find(needle)
        if start == -1:
            return None
        json_start = start + len(f"var {var_name} = ")
        depth = 0
        json_end = 0
        for i in range(json_start, len(html)):
            if html[i] == "{":
                depth += 1
            elif html[i] == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break
        if not json_end:
            return None
        try:
            return json.loads(html[json_start:json_end])
        except json.JSONDecodeError:
            return None

    # ── POS URL ───────────────────────────────────────────────────────────────

    def get_pos_url(self, listing_id: str, pos_file_path: str) -> str:
        if not pos_file_path:
            return ""
        cleaned = pos_file_path.replace("\\/", "/")
        return urljoin(self.BASE_URL + "/", cleaned)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_location(address: str) -> Tuple[str, str]:
        """
        Extract (state, district) from a BidNow full_address.
        Format: "..., <postcode>, <district>, <state>"
        """
        if not address:
            return "", ""
        parts = [p.strip() for p in address.split(",")]
        if len(parts) >= 2:
            state = parts[-1]
            district = parts[-2]
            if district.isdigit():
                district = parts[-3] if len(parts) >= 4 else ""
            return state, district
        return "", ""

    @staticmethod
    def _normalise_type(raw: str) -> str:
        if not raw:
            return "residential"
        r = raw.lower()
        if any(w in r for w in ("terrace", "link house", "townhouse", "town house")):
            return "terrace"
        if "semi-d" in r or "semi detach" in r:
            return "semi-d"
        if any(w in r for w in ("bungalow", "detach", "villa")):
            return "bungalow"
        if any(w in r for w in ("condominium", "soho")):
            return "condo"
        if "service suite" in r or "service apartment" in r:
            return "condo"
        if "apartment" in r or "flat" in r:
            return "apartment"
        if any(w in r for w in ("shop", "office", "retail")):
            return "shop"
        if any(w in r for w in ("warehouse", "factory")):
            return "warehouse"
        if "land" in r:
            return "land"
        return "residential"
