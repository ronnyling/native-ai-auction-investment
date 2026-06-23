"""
lelongtips.py — LelongTips.com.my scraper (supplementary source).

Provides:
  - Auction count badge text (e.g. "4th Auction") visible on listing cards
  - Past auction price history shown on detail pages (free, no login)
  - Cross-reference data (address, date, price) to supplement BidNow records

LelongTips search URL (confirmed working):
    https://www.lelongtips.com.my/search/?state={STATE}&upcoming=1&sort=latest&page={N}

Listing card URL pattern:
    https://www.lelongtips.com.my/property/{BASE64_ID}/{slug}

Detail page exposes (free):
    - Full address, auction price, date, area sqft, tenure, title type
    - Auction count badge (e.g. "4th Auction")
    - Past auction price + month/year (e.g. "RM315,000 (Nov 2024)")

Detail page requires premium:
    - Unit number, plaintiff, solicitor, auctioneer, POS PDF

Delta strategy: sort by 'latest', stop paginating when all slugs on a page
are already in known_llt_slugs.
"""

import re
import time
from typing import Dict, List, Optional, Set
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

# LelongTips uses state names matching these exact URL values
LLT_STATES = [
    "Johor",
    "Kedah",
    "Kelantan",
    "Kuala Lumpur",
    "Labuan",
    "Melaka",
    "Negeri Sembilan",
    "Pahang",
    "Penang",
    "Perak",
    "Perlis",
    "Putrajaya",
    "Sabah",
    "Sarawak",
    "Selangor",
    "Terengganu",
]

BASE_URL = "https://www.lelongtips.com.my"
SEARCH_URL = BASE_URL + "/search/"
REQUEST_TIMEOUT = 30
PAGE_DELAY = 1.0  # seconds between requests — be a polite scraper


class LelongTipsScraper:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape_all_states(
        self,
        known_slugs: Set[str] = None,
        upcoming_only: bool = True,
    ) -> List[Dict]:
        """Scrape all LLT states and return combined listing list."""
        results: List[Dict] = []
        known_slugs = known_slugs or set()
        for state in LLT_STATES:
            print(f"\n[LLT] Scraping state: {state}")
            listings = self.scrape_state(
                state, known_slugs=known_slugs, upcoming_only=upcoming_only
            )
            results.extend(listings)
            print(f"  [LLT] {state}: {len(listings)} listings")
        return results

    def scrape_state(
        self,
        state: str,
        known_slugs: Set[str] = None,
        upcoming_only: bool = True,
        max_pages: int = None,
    ) -> List[Dict]:
        """
        Scrape one state's listing pages.

        Delta mode: stops when an entire page consists only of known slugs.
        """
        known_slugs = known_slugs or set()
        all_listings: List[Dict] = []
        seen_slugs: Set[str] = set()
        page = 1

        while True:
            if max_pages and page > max_pages:
                break

            print(f"  [LLT] {state} page {page}...")
            params = {"state": state, "sort": "latest", "page": page}
            if upcoming_only:
                params["upcoming"] = 1

            try:
                resp = self.session.get(
                    SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT
                )
                resp.raise_for_status()
            except Exception as exc:
                print(f"  [LLT] fetch error on {state} page {page}: {exc}")
                break

            cards = self._parse_listing_cards(resp.text)
            if not cards:
                print(f"  [LLT] no cards on page {page}, stopping")
                break

            all_known = True
            new_count = 0
            for card in cards:
                slug = card.get("llt_slug", "")
                if not slug or slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                if slug not in known_slugs:
                    all_known = False
                    new_count += 1
                all_listings.append(card)

            print(f"  [LLT] page {page}: {len(cards)} cards, {new_count} new")

            if all_known and known_slugs:
                print(f"  [LLT] all slugs known on page {page} — stopping early")
                break

            page += 1
            time.sleep(PAGE_DELAY)

        return all_listings

    def scrape_detail(self, llt_url: str) -> Optional[Dict]:
        """
        Scrape a LelongTips property detail page.
        Returns past_auction_history list and available specs.
        """
        try:
            resp = self.session.get(llt_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return self._parse_detail_page(resp.text, llt_url)
        except Exception as exc:
            print(f"  [LLT] detail scrape error {llt_url}: {exc}")
            return None

    # ── HTML parsing — listing card ───────────────────────────────────────────

    def _parse_listing_cards(self, html: str) -> List[Dict]:
        """Parse all listing cards from a search results page."""
        soup = BeautifulSoup(html, "html.parser")
        listings: List[Dict] = []

        # LelongTips renders cards as <a> tags linking to /property/{id}/{slug}
        # Each card contains: title, address, price, date, area, tenure, auction count
        for link in soup.select("a[href*='/property/']"):
            href = link.get("href", "")
            if not href or "/property/" not in href:
                continue

            # Extract BASE64 id and slug from URL
            # Pattern: /property/{base64id}/{slug}
            match = re.search(r"/property/([^/]+)/([^/?]+)", href)
            if not match:
                continue

            llt_id = match.group(1)
            slug = match.group(2)
            full_url = BASE_URL + href if href.startswith("/") else href

            # Skip duplicates (same card appears multiple times in HTML)
            if not llt_id:
                continue

            # Extract visible text from the card element
            card_text = link.get_text(separator=" ", strip=True)

            # --- Address: try CSS class selectors first, fall back to heuristic ---
            address = ""
            # LLT uses various class names for address text
            for sel in ["p.location", "span.location", ".property-address",
                        ".address", "h5", "address"]:
                addr_tag = link.select_one(sel)
                if addr_tag:
                    address = addr_tag.get_text(strip=True)
                    break
            # Fallback: first line that looks like a Malaysian address
            # (contains a number and a comma, or contains "Jalan"/"Taman"/"No.")
            if not address:
                for line in card_text.split("  "):
                    line = line.strip()
                    if line and re.search(
                        r"(Jalan|Taman|Lorong|No\.|Jln|Tmn|Blok|Block|Lot|Apartment|Condominium|,\s*\d{5})",
                        line, re.IGNORECASE
                    ):
                        address = line
                        break

            # --- Price: look for RM pattern ---
            price = 0.0
            price_match = re.search(r"RM\s*([\d,]+(?:\.\d+)?)", card_text)
            if price_match:
                price = float(price_match.group(1).replace(",", ""))

            # --- Auction date ---
            auction_date = ""
            date_match = re.search(
                r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})",
                card_text,
                re.IGNORECASE,
            )
            if date_match:
                auction_date = date_match.group(1)

            # --- Auction count (e.g. "4th Auction", "2nd Auction") ---
            auction_count_text = ""
            ac_match = re.search(
                r"(\d+(?:st|nd|rd|th)\s+Auction)", card_text, re.IGNORECASE
            )
            if ac_match:
                auction_count_text = ac_match.group(1)

            # Parse numeric count from badge text
            ac_num = 1
            ac_num_match = re.search(r"(\d+)", auction_count_text)
            if ac_num_match:
                ac_num = int(ac_num_match.group(1))

            # --- Sqft ---
            sqft = 0.0
            sqft_match = re.search(r"([\d,]+)\s*sq\.?ft", card_text, re.IGNORECASE)
            if sqft_match:
                sqft = float(sqft_match.group(1).replace(",", ""))

            # --- Tenure ---
            tenure = ""
            if "Freehold" in card_text or " FH" in card_text:
                tenure = "freehold"
            elif "Leasehold" in card_text or " LH" in card_text:
                tenure = "leasehold"

            # --- Title type ---
            title_type = ""
            if "LACA" in card_text:
                title_type = "LACA"
            elif "e-Lelong" in card_text:
                title_type = "e-Lelong"
            elif "Title" in card_text:
                title_type = "Title"

            # --- BMV discount % ---
            discount_pct = 0
            disc_match = re.search(r"-(\d+)%", card_text)
            if disc_match:
                discount_pct = int(disc_match.group(1))

            # --- Past auction price (shown on card if re-auction) ---
            past_price = 0.0
            past_date = ""
            past_match = re.search(
                r"RM\s*([\d,]+(?:\.\d+)?)\s*\(([^)]+)\)", card_text
            )
            if past_match:
                # First RM match is current price; a second would be past
                all_prices = re.findall(r"RM\s*([\d,]+(?:\.\d+)?)", card_text)
                if len(all_prices) >= 2:
                    past_price = float(all_prices[-1].replace(",", ""))
                    past_date = past_match.group(2)

            listings.append({
                "llt_id": llt_id,
                "llt_slug": slug,
                "llt_url": full_url,
                "address": address,
                "reserve_price": price,
                "auction_date_text": auction_date,
                "auction_count": ac_num,
                "auction_count_text": auction_count_text,
                "sqft": sqft,
                "tenure": tenure,
                "title_type": title_type,
                "discount_pct": discount_pct,
                "past_price": past_price,
                "past_date": past_date,
                "source": "lelongtips",
            })

        # Deduplicate by llt_id within this page
        seen = set()
        unique = []
        for item in listings:
            if item["llt_id"] not in seen:
                seen.add(item["llt_id"])
                unique.append(item)
        return unique

    # ── HTML parsing — detail page ────────────────────────────────────────────

    def _parse_detail_page(self, html: str, url: str) -> Dict:
        """
        Parse a LelongTips property detail page.
        Extracts past auction history rows (price + date pairs).
        """
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        # Past auction prices (shown in detail page as: "RM315,000 (Nov 2024)")
        past_history = []
        for m in re.finditer(
            r"RM\s*([\d,]+(?:\.\d+)?)\s*\((\w{3}\s+\d{4})\)", text
        ):
            past_history.append({
                "reserve_price": float(m.group(1).replace(",", "")),
                "date_text": m.group(2),
            })

        # Current price (first RM occurrence)
        current_price = 0.0
        price_match = re.search(r"RM\s*([\d,]+(?:\.\d+)?)", text)
        if price_match:
            current_price = float(price_match.group(1).replace(",", ""))

        return {
            "llt_url": url,
            "current_price": current_price,
            "past_auction_history": past_history,
        }
