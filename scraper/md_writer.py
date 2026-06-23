"""
md_writer.py — Write and update Obsidian property vault notes.

Rules (CRITICAL):
- New property  : create vault/Properties/bn-{id}.md from scratch
- Existing note : update ONLY frontmatter keys owned by the scraper
                  NEVER touch anything below the "## Notes" heading
- Scraper-owned frontmatter keys are listed in SCRAPER_OWNED_KEYS
- User-owned keys (status, rating, visited, action_needed, tags)
  are preserved exactly as found in the existing file

Also provides:
- build_vault_index(): scan all existing notes → dict keyed by postcode:street
- update_daily_note(): write/overwrite today's Daily Note with Dataview queries
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import yaml  # pyyaml

# Keys the scraper is allowed to write/overwrite
SCRAPER_OWNED_KEYS = {
    "id", "bidnow_id", "llt_slug", "llt_url",
    "address", "postcode", "city", "state", "region",
    "location",
    "property_type", "built_up_sqft", "land_area_sqft",
    "tenure", "restriction", "auction_type",
    "auction_date", "auction_time", "days_to_auction",
    "reserve_price", "market_value", "bmv_pct",
    "auction_count", "original_reserve", "total_price_drop",
    "bank", "lawyer", "auctioneer", "borrower",
    "deposit_pct", "deposit_amount",
    "pos_file_path", "pos_url",
    "auction_history",
    "scrape_date",
    "source_bn", "source_llt",
}

# Keys preserved from existing notes (user-owned)
USER_OWNED_KEYS = {
    "status", "rating", "visited", "action_needed", "tags",
    # POS analysis results (written by pos_analyzer.py, not scraper)
    "pos_analyzed", "pos_analysis_date",
    "legal_risk", "legal_issues", "encumbrances",
    "management_fees_monthly", "quit_rent_annual",
    "outstanding_fees_est", "deposit_terms",
    "title_type", "lease_remaining_years", "pos_confidence",
}

NOTES_BOUNDARY = "## Notes"
POS_SECTION_HEADER = "## POS Document"


class MDWriter:

    def __init__(self, vault_properties_dir: str):
        self.props_dir = Path(vault_properties_dir)
        self.props_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def write(self, listing: Dict, action: str) -> Path:
        """
        Write or update a property note.

        action: "create" | "update_price" | "new_round"
        Returns the path written.
        """
        note_path = self.props_dir / f"bn-{listing['listing_id']}.md"

        if action == "create" or not note_path.exists():
            content = self._render_new_note(listing)
            note_path.write_text(content, encoding="utf-8")
            return note_path

        # Existing note — patch frontmatter only
        existing_text = note_path.read_text(encoding="utf-8")
        updated = self._patch_frontmatter(existing_text, listing)
        note_path.write_text(updated, encoding="utf-8")
        return note_path

    def build_vault_index(self) -> Dict[str, Dict]:
        """
        Scan all existing Property notes and return a lookup dict:
            key: "{postcode}:{normalised_street}"
            value: dict of frontmatter fields
        """
        index: Dict[str, Dict] = {}
        for md_file in self.props_dir.glob("bn-*.md"):
            fm = self._read_frontmatter(md_file)
            if not fm:
                continue
            address = fm.get("address", "")
            postcode = str(fm.get("postcode", ""))
            street = _normalise_street(address)
            if postcode and street:
                key = f"{postcode}:{street}"
                index[key] = fm
        print(f"  [vault] index built: {len(index)} existing notes")
        return index

    def build_known_ids(self) -> set:
        """Return set of all BidNow listing IDs already in the vault."""
        ids = set()
        for md_file in self.props_dir.glob("bn-*.md"):
            fm = self._read_frontmatter(md_file)
            if fm and fm.get("bidnow_id"):
                ids.add(str(fm["bidnow_id"]))
        return ids

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_new_note(self, listing: Dict) -> str:
        fm = self._build_frontmatter(listing, existing_user_fields={})
        fm_str = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)

        pos_line = ""
        if listing.get("pos_url"):
            pos_line = f"\n{POS_SECTION_HEADER}\n[Download POS]({listing['pos_url']})\n"

        return (
            f"---\n{fm_str}---\n\n"
            f"{NOTES_BOUNDARY}\n"
            f"<!-- Your personal notes — scraper never touches below this line -->\n"
            f"{pos_line}"
        )

    def _build_frontmatter(
        self, listing: Dict, existing_user_fields: Dict
    ) -> Dict:
        """Build the full frontmatter dict (scraper keys + preserved user keys)."""
        lat = listing.get("lat")
        lng = listing.get("lng")
        location = [lat, lng] if lat is not None and lng is not None else []

        postcode_raw = _extract_postcode(listing.get("full_address", ""))
        try:
            postcode = int(postcode_raw) if postcode_raw else 0
        except ValueError:
            postcode = 0

        fm = {
            # Identity
            "id": f"bn-{listing['listing_id']}",
            "bidnow_id": int(listing["listing_id"]) if listing.get("listing_id") else 0,
            "llt_slug": listing.get("llt_slug", ""),
            "llt_url": listing.get("llt_url", ""),
            # Address
            "address": listing.get("full_address", ""),
            "postcode": postcode,
            "city": listing.get("district", ""),
            "state": listing.get("state", ""),
            "region": listing.get("region", ""),
            "location": location,
            # Property specs
            "property_type": listing.get("property_type", ""),
            "built_up_sqft": listing.get("built_up_sqft", 0),
            "land_area_sqft": listing.get("land_area_sqft", 0),
            "tenure": listing.get("tenure", ""),
            "restriction": listing.get("restriction", ""),
            "auction_type": listing.get("auction_type", ""),
            # Latest auction
            "auction_date": listing.get("auction_date", ""),
            "auction_time": listing.get("auction_time", ""),
            "days_to_auction": listing.get("days_to_auction", 0),
            "reserve_price": listing.get("reserve_price", 0),
            "market_value": listing.get("market_value", 0),
            "bmv_pct": listing.get("bmv_percent", 0),
            "auction_count": listing.get("auction_count", 1),
            "original_reserve": listing.get("original_reserve", listing.get("reserve_price", 0)),
            "total_price_drop": listing.get("total_price_drop", 0),
            # Parties
            "bank": listing.get("bank", ""),
            "lawyer": listing.get("lawyer", ""),
            "auctioneer": listing.get("auctioneer", ""),
            "borrower": listing.get("borrower", ""),
            "deposit_pct": listing.get("deposit_pct", 10),
            "deposit_amount": listing.get("deposit_amount", 0),
            # POS
            "pos_file_path": listing.get("pos_file_path", ""),
            "pos_url": listing.get("pos_url", ""),
            # History (YAML block)
            "auction_history": listing.get("auction_history", []),
            # Scrape metadata
            "scrape_date": str(date.today()),
            "source_bn": listing.get("url", ""),
            "source_llt": listing.get("llt_url", ""),
            # User-owned (defaults for new notes, preserved from existing)
            "status": existing_user_fields.get("status", "new"),
            "rating": existing_user_fields.get("rating", 0),
            "visited": existing_user_fields.get("visited", False),
            "action_needed": existing_user_fields.get("action_needed", ""),
            "tags": existing_user_fields.get("tags", listing.get("tags", [])),
        }
        return fm

    # ── Frontmatter patching ──────────────────────────────────────────────────

    def _patch_frontmatter(self, existing_text: str, listing: Dict) -> str:
        """
        Update only SCRAPER_OWNED_KEYS in existing note's frontmatter.
        Preserve user-owned keys and everything below ## Notes.
        """
        # Split on first frontmatter block
        fm_match = re.match(r"^---\n(.*?)\n---\n(.*)", existing_text, re.DOTALL)
        if not fm_match:
            # No frontmatter found — treat as new
            return self._render_new_note(listing)

        existing_fm_str = fm_match.group(1)
        body = fm_match.group(2)

        try:
            existing_fm = yaml.safe_load(existing_fm_str) or {}
        except yaml.YAMLError:
            existing_fm = {}

        # Preserve all user-owned fields from existing frontmatter
        user_fields = {k: v for k, v in existing_fm.items() if k in USER_OWNED_KEYS}

        # Build updated frontmatter with new scraper data + preserved user fields
        new_fm = self._build_frontmatter(listing, user_fields)
        new_fm_str = yaml.dump(
            new_fm, allow_unicode=True, default_flow_style=False, sort_keys=False
        )

        return f"---\n{new_fm_str}---\n{body}"

    # ── Read helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _read_frontmatter(md_file: Path) -> Optional[Dict]:
        try:
            text = md_file.read_text(encoding="utf-8")
            fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
            if fm_match:
                return yaml.safe_load(fm_match.group(1)) or {}
        except Exception:
            pass
        return None


# ── Daily Note writer ─────────────────────────────────────────────────────────

def write_daily_note(daily_notes_dir: str, templates_dir: str):
    """
    Create today's Daily Note if it doesn't exist yet.
    Copies the daily-note template (Templater will expand queries on open).
    """
    today = date.today().isoformat()
    note_path = Path(daily_notes_dir) / f"{today}.md"
    template_path = Path(templates_dir) / "daily-note.md"

    if note_path.exists():
        return  # Already created today

    if template_path.exists():
        content = template_path.read_text(encoding="utf-8")
        content = content.replace("{{date}}", today)
    else:
        content = _default_daily_note(today)

    Path(daily_notes_dir).mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    print(f"  [vault] daily note created: {note_path.name}")


def _default_daily_note(today: str) -> str:
    return f"""# {today} — Auction Daily

## Auction This Week
```dataview
TABLE reserve_price, bmv_pct, state, city, auction_date, status
FROM "Properties"
WHERE days_to_auction <= 7 AND status != "passed"
SORT auction_date ASC
```

## New Today
```dataview
TABLE reserve_price, bmv_pct, state, city, property_type, auction_date
FROM "Properties"
WHERE scrape_date = date(today)
SORT reserve_price ASC
```

## Re-auctions (price dropped)
```dataview
TABLE reserve_price, original_reserve, total_price_drop, auction_count, city, auction_date
FROM "Properties"
WHERE auction_count > 1 AND status != "passed"
SORT total_price_drop DESC
```

## My Shortlist
```dataview
TABLE reserve_price, bmv_pct, city, auction_date, action_needed, rating
FROM "Properties"
WHERE contains(list("shortlisted","visiting","bid"), status)
SORT auction_date ASC
```
"""


# ── Utility ───────────────────────────────────────────────────────────────────

def _normalise_street(address: str) -> str:
    s = address.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_postcode(address: str) -> str:
    m = re.search(r"\b(\d{5})\b", address)
    return m.group(1) if m else ""
