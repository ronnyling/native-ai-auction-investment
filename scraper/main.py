"""
main.py — Daily scraper pipeline orchestrator.

Stages (run in order):
  1. Load vault index + known BidNow IDs from existing vault notes
  2. BidNow scrape (all 15 states, delta mode)
  3. LelongTips scrape (all 16 states, delta mode)
  4. Cross-reference BidNow ↔ LelongTips (fuzzy address match)
  5. Re-auction detection against vault index
  6. Geocode (Nominatim + postcode centroid fallback)
  7. Write / update vault notes
  8. Write today's Daily Note
  9. Print run summary

Environment variables (set by GitHub Actions or locally):
  VAULT_PATH        path to vault/Properties (default: ../vault/Properties)
  GEOCACHE_PATH     path to geocache.json     (default: geocache.json)
  KNOWN_IDS_PATH    path to known_ids.json    (default: known_ids.json)
  SCRAPE_STATES     comma-separated list of states to scrape (default: all)
  MAX_PAGES         hard page cap per state (default: unlimited)
"""

import json
import os
import sys
import traceback
from datetime import date
from pathlib import Path
from typing import Dict, List

# ── Resolve paths ─────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
VAULT_PATH = os.environ.get(
    "VAULT_PATH",
    str(SCRIPT_DIR.parent / "vault" / "Properties"),
)
DAILY_NOTES_PATH = os.environ.get(
    "DAILY_NOTES_PATH",
    str(SCRIPT_DIR.parent / "vault" / "Daily Notes"),
)
TEMPLATES_PATH = os.environ.get(
    "TEMPLATES_PATH",
    str(SCRIPT_DIR.parent / "vault" / "_templates"),
)
GEOCACHE_PATH = os.environ.get(
    "GEOCACHE_PATH",
    str(SCRIPT_DIR / "geocache.json"),
)
KNOWN_IDS_PATH = os.environ.get(
    "KNOWN_IDS_PATH",
    str(SCRIPT_DIR / "known_ids.json"),
)
_max_pages_raw = os.environ.get("MAX_PAGES", "").strip()
MAX_PAGES = int(_max_pages_raw) if _max_pages_raw else None
SCRAPE_STATES = os.environ.get("SCRAPE_STATES", "")

# ── Imports (local modules) ───────────────────────────────────────────────────

from bidnow import BidNowScraper
from bidnow_filter_enums import BIDNOW_STATES
from lelongtips import LelongTipsScraper
from dedup_merger import cross_reference, detect_reauction, compute_derived_fields
from geocode import Geocoder
from md_writer import MDWriter, write_daily_note


# ── Known IDs helpers ─────────────────────────────────────────────────────────

def load_known_ids() -> set:
    p = Path(KNOWN_IDS_PATH)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_known_ids(ids: set):
    p = Path(KNOWN_IDS_PATH)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, indent=2)


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run():
    today = date.today().isoformat()
    print(f"\n{'='*60}")
    print(f"  Auction Vault Scraper — {today}")
    print(f"{'='*60}\n")

    # Determine states to scrape
    states_to_scrape = (
        [s.strip() for s in SCRAPE_STATES.split(",") if s.strip()]
        if SCRAPE_STATES
        else BIDNOW_STATES
    )
    print(f"  States: {', '.join(states_to_scrape)}")
    print(f"  Vault:  {VAULT_PATH}")

    # ── Stage 1: Load vault index ─────────────────────────────────────────────
    print("\n[Stage 1] Loading vault index...")
    writer = MDWriter(VAULT_PATH)
    vault_index = writer.build_vault_index()
    vault_known_ids = writer.build_known_ids()
    scraper_known_ids = load_known_ids()
    known_ids = vault_known_ids | scraper_known_ids
    print(f"  {len(known_ids)} known BidNow IDs")

    # ── Stage 2: BidNow scrape ────────────────────────────────────────────────
    print("\n[Stage 2] BidNow scrape (all states, delta mode)...")
    bn_scraper = BidNowScraper()
    all_bn_listings: List[Dict] = []

    for state in states_to_scrape:
        filters = {"state": state, "listing": "active", "sort": "new"}
        listings = bn_scraper.scrape_listings(
            filters=filters,
            max_pages=MAX_PAGES,
            known_ids=known_ids,
        )
        all_bn_listings.extend(listings)

    print(f"\n  BidNow total: {len(all_bn_listings)} listings fetched")

    # ── Stage 3: LelongTips scrape ────────────────────────────────────────────
    print("\n[Stage 3] LelongTips scrape (all states, delta mode)...")
    llt_scraper = LelongTipsScraper()
    all_llt_listings: List[Dict] = []

    # Build known LLT slugs from vault index
    known_llt_slugs = {
        v.get("llt_slug", "") for v in vault_index.values() if v.get("llt_slug")
    }

    for state in states_to_scrape:
        listings = llt_scraper.scrape_state(
            state,
            known_slugs=known_llt_slugs,
            upcoming_only=True,
            max_pages=MAX_PAGES,
        )
        all_llt_listings.extend(listings)

    print(f"\n  LelongTips total: {len(all_llt_listings)} listings fetched")

    # ── Stage 4: Cross-reference ──────────────────────────────────────────────
    print("\n[Stage 4] Cross-referencing BidNow ↔ LelongTips...")
    merged_listings = cross_reference(all_bn_listings, all_llt_listings)

    # ── Stage 5: Re-auction detection ─────────────────────────────────────────
    print("\n[Stage 5] Re-auction detection against vault...")
    actions: Dict[str, int] = {"create": 0, "update_price": 0, "new_round": 0}
    enriched: List[tuple] = []  # (action, listing, existing)

    for listing in merged_listings:
        action, existing = detect_reauction(listing, vault_index)
        listing = compute_derived_fields(listing, existing)
        actions[action] += 1
        enriched.append((action, listing, existing))

    print(
        f"  {actions['create']} new | "
        f"{actions['update_price']} price updates | "
        f"{actions['new_round']} new auction rounds"
    )

    # ── Stage 6: Geocode ──────────────────────────────────────────────────────
    print("\n[Stage 6] Geocoding...")
    geocoder = Geocoder(GEOCACHE_PATH)
    listings_to_geocode = [l for _, l, _ in enriched]
    geocoder.geocode_listings(listings_to_geocode)

    # ── Stage 7: Write vault notes ────────────────────────────────────────────
    print("\n[Stage 7] Writing vault notes...")
    written = 0
    errors = 0
    new_ids: set = set()

    for action, listing, _ in enriched:
        try:
            writer.write(listing, action)
            new_ids.add(str(listing["listing_id"]))
            written += 1
        except Exception as exc:
            print(f"  [write] ERROR for {listing.get('listing_id')}: {exc}")
            traceback.print_exc()
            errors += 1

    # Persist updated known IDs
    all_known = known_ids | new_ids
    save_known_ids(all_known)
    print(f"  {written} notes written, {errors} errors")

    # ── Stage 8: Daily Note ───────────────────────────────────────────────────
    print("\n[Stage 8] Writing daily note...")
    try:
        write_daily_note(DAILY_NOTES_PATH, TEMPLATES_PATH)
    except Exception as exc:
        print(f"  [daily note] ERROR: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Run complete — {today}")
    print(f"  BidNow fetched   : {len(all_bn_listings)}")
    print(f"  LLT fetched      : {len(all_llt_listings)}")
    print(f"  LLT matched      : {sum(1 for l in merged_listings if l.get('llt_slug'))}")
    print(f"  New properties   : {actions['create']}")
    print(f"  Price updates    : {actions['update_price']}")
    print(f"  New rounds       : {actions['new_round']}")
    print(f"  Notes written    : {written}")
    print(f"  Total vault size : {len(all_known)} known IDs")
    print(f"{'='*60}\n")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
