"""
propertyguru.py — PropertyGuru competition/market signal scraper.

Purpose: identify whether auction properties are also publicly listed
on PropertyGuru (bank auction / LACA keyword searches), which indicates
higher public visibility = more competition from retail bidders.

Search URLs (confirmed accessible, no auth, no anti-bot blocking):
  - https://www.propertyguru.com.my/property-for-sale?freetext=bank+auction
  - https://www.propertyguru.com.my/property-for-sale?freetext=laca

Data source: __NEXT_DATA__ JSON embedded in HTML (Next.js SSR).
No rate limiting observed; polite 1s delay between pages is sufficient.

Output per listing:
  listing_id, source, url, title, full_address, state, district,
  property_type, built_up_sqft, asking_price, price_psf,
  bedrooms, bathrooms, tenure, furnished, scrape_date
"""

import json
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.propertyguru.com.my"
SEARCH_URL = BASE_URL + "/property-for-sale"
REQUEST_TIMEOUT = 30
PAGE_DELAY = 1.0
PAGE_SIZE = 20  # PropertyGuru returns ~20 listings per page


class PropertyGuruScraper:
    """
    Scrape PropertyGuru for auction-related listings (competition signal).

    These are NOT auction listings — they are conventional for-sale listings
    that mention "bank auction" or "LACA" in their description. Their
    presence and price provides a market rate reference and competition
    signal for the same/nearby properties going to auction.
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

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape_competition_signal(
        self,
        query: str = "bank auction",
        max_pages: int = 3,
    ) -> List[Dict]:
        """
        Scrape PropertyGuru for a query keyword and return listing data.

        Args:
            query:      Search keyword — "bank auction", "laca", or "foreclosure"
            max_pages:  Max pages to scrape (default 3 = ~60 listings)

        Returns:
            List of standardised listing dicts.
        """
        all_listings: List[Dict] = []
        seen_ids: set = set()

        for page in range(1, max_pages + 1):
            print(f"  [PropertyGuru] '{query}' page {page}/{max_pages} ...")
            params = {
                "freetext": query,
                "listing_type": "sale",
            }
            if page > 1:
                params["page"] = page

            try:
                resp = self.session.get(
                    SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
            except Exception as exc:
                print(f"  [PropertyGuru] fetch error page {page}: {exc}")
                break

            listings = self._extract_listings(resp.text)
            if not listings:
                print(f"  [PropertyGuru] no listings on page {page}, stopping")
                break

            new_count = 0
            for item in listings:
                lid = item.get("listing_id", "")
                if lid and lid not in seen_ids:
                    seen_ids.add(lid)
                    all_listings.append(item)
                    new_count += 1

            print(f"  [PropertyGuru] page {page}: {len(listings)} listings, {new_count} new")

            if len(listings) < PAGE_SIZE:
                break  # last page

            if page < max_pages:
                time.sleep(PAGE_DELAY)

        print(f"  [PropertyGuru] total: {len(all_listings)} unique listings")
        return all_listings

    # ── Internal: parse ───────────────────────────────────────────────────────

    def _extract_listings(self, html: str) -> List[Dict]:
        """Extract listings from __NEXT_DATA__ JSON or BeautifulSoup fallback."""
        soup = BeautifulSoup(html, "html.parser")

        # Primary: __NEXT_DATA__ script tag (Next.js SSR)
        nd_tag = soup.find("script", id="__NEXT_DATA__")
        if nd_tag and nd_tag.string:
            try:
                nd = json.loads(nd_tag.string)
                listings = self._parse_next_data(nd)
                if listings:
                    return listings
                # Debug: show what pageData actually contains
                pd = nd.get("props", {}).get("pageProps", {}).get("pageData", {})
                print(f"  [PropertyGuru] pageData keys: {list(pd.keys())[:10]}")
            except Exception as exc:
                print(f"  [PropertyGuru] __NEXT_DATA__ parse error: {exc}")
        elif not nd_tag:
            print("  [PropertyGuru] __NEXT_DATA__ script tag not found")
        else:
            print("  [PropertyGuru] __NEXT_DATA__ tag has no string content")

        # Fallback: look for window.__INITIAL_STATE__ or similar embedded JSON
        for script in soup.find_all("script"):
            text = script.string or ""
            if "listingId" in text and "askingPrice" in text:
                try:
                    m = re.search(r"\{.*\"listingId\".*\}", text[:10000])
                    if m:
                        obj = json.loads(m.group())
                        return [self._normalise(obj)]
                except Exception:
                    pass

        return []

    def _parse_next_data(self, nd: Dict) -> List[Dict]:
        """Navigate __NEXT_DATA__ JSON to find listings list."""
        page_props = nd.get("props", {}).get("pageProps", {})
        page_data = page_props.get("pageData", {})

        # Try direct list keys first
        for key in ("listings", "searchResults", "items", "properties", "results"):
            val = page_data.get(key)
            if isinstance(val, list) and val:
                return [self._normalise(item) for item in val]

        # pageData.data is typically a dict — recurse into it
        data_obj = page_data.get("data")
        if isinstance(data_obj, dict):
            # Direct list keys
            for key in ("listings", "searchResults", "items", "properties", "results"):
                val = data_obj.get(key)
                if isinstance(val, list) and val:
                    print(f"  [PropertyGuru] found listings at pageData.data.{key}: {len(val)}")
                    return [self._normalise(item) for item in val]
            # listingsData is a dict with a listings list inside
            listings_data = data_obj.get("listingsData")
            if isinstance(listings_data, dict):
                for key in ("listings", "items", "data", "results", "searchResults"):
                    val = listings_data.get(key)
                    if isinstance(val, list) and val:
                        print(f"  [PropertyGuru] found listings at pageData.data.listingsData.{key}: {len(val)}")
                        return [self._normalise(item) for item in val]
                # listingsData itself might be what we want
                print(f"  [PropertyGuru] pageData.data.listingsData keys: {list(listings_data.keys())[:15]}")
            elif isinstance(listings_data, list) and listings_data:
                print(f"  [PropertyGuru] found listings at pageData.data.listingsData (list): {len(listings_data)}")
                # Each item is a wrapper: {'listingData': {...}, 'metadata': {...}, ...}
                # Unwrap to the inner listingData if present
                unwrapped = []
                for item in listings_data:
                    if not isinstance(item, dict):
                        continue
                    inner = item.get("listingData") or item
                    unwrapped.append(inner)
                return [self._normalise(item) for item in unwrapped]
            # Print data keys for debugging
            print(f"  [PropertyGuru] pageData.data keys: {list(data_obj.keys())[:15]}")

        # Try pgBasePageLayoutData (PropertyGuru layout key observed)
        for layout_key in ("pgBasePageLayoutData", "ippBasePageLayoutData"):
            layout = page_data.get(layout_key, {})
            if isinstance(layout, dict):
                for key in ("listings", "searchResults", "items", "properties"):
                    val = layout.get(key)
                    if isinstance(val, list) and val:
                        print(f"  [PropertyGuru] found listings at pageData.{layout_key}.{key}: {len(val)}")
                        return [self._normalise(item) for item in val]

        # Breadth-first search one level deeper across all pageData values
        for outer_key, outer_val in page_data.items():
            if not isinstance(outer_val, dict):
                continue
            for inner_key, inner_val in outer_val.items():
                if isinstance(inner_val, list) and inner_val and isinstance(inner_val[0], dict):
                    first = inner_val[0]
                    # Heuristic: a listing has id/price/address
                    if any(k in first for k in ("id", "listingId")) and any(
                        k in first for k in ("price", "askingPrice", "listingPrice")
                    ):
                        print(f"  [PropertyGuru] found listings via heuristic at pageData.{outer_key}.{inner_key}: {len(inner_val)}")
                        return [self._normalise(item) for item in inner_val]

        return []

    def _normalise(self, item: Dict) -> Dict:
        """Map raw PropertyGuru listing dict to standardised output format."""
        today = date.today().isoformat()

        lid = str(item.get("id") or item.get("listingId") or "")
        title = item.get("localizedTitle") or item.get("title") or item.get("name") or ""
        url = item.get("url") or item.get("listingUrl") or item.get("seoUrl") or ""
        if url and not url.startswith("http"):
            url = BASE_URL + url

        # Address
        full_address = (
            item.get("address")
            or item.get("fullAddress")
            or item.get("streetName")
            or ""
        )
        district = item.get("districtName") or item.get("district") or ""
        state = item.get("state") or item.get("region") or item.get("stateName") or ""

        # Price
        price_raw = item.get("price") or item.get("listingPrice") or item.get("askingPrice") or {}
        if isinstance(price_raw, dict):
            asking_price = float(price_raw.get("value") or price_raw.get("amount") or 0)
        else:
            asking_price = float(price_raw or 0)

        psf_text = item.get("psfText") or item.get("pricePerSqft") or ""
        price_psf: Optional[float] = None
        if psf_text:
            m = re.search(r"[\d,]+\.?\d*", psf_text.replace(",", ""))
            if m:
                price_psf = float(m.group())

        # Property details
        floor_area = float(item.get("floorArea") or item.get("builtUpSize") or 0)
        prop_type = (
            item.get("propertyType")
            or item.get("category")
            or item.get("subTypeText")
            or item.get("type")
            or ""
        )
        tenure = item.get("tenure") or ""
        furnished = item.get("furnishedStatus") or ""

        features = item.get("listingFeatures") or []
        bedrooms = 0
        bathrooms = 0
        for feat_group in features:
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
            "listing_id": f"PG-{lid}",
            "source": "propertyguru",
            "url": url,
            "title": title,
            "full_address": full_address,
            "state": state,
            "district": district,
            "property_type": prop_type,
            "built_up_sqft": floor_area,
            "asking_price": asking_price,
            "price_psf": price_psf,
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "tenure": tenure,
            "furnished": furnished,
            "scrape_date": today,
        }
