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
  8. Market research enrichment (iProperty PSF — high-priority only)
  9. Analyst Agent (LLM investment scoring — high-priority only)
 10. Write today's Daily Note

Environment variables (set by GitHub Actions or locally):
  VAULT_PATH        path to vault/Properties (default: ../vault/Properties)
  GEOCACHE_PATH     path to geocache.json     (default: geocache.json)
  KNOWN_IDS_PATH    path to known_ids.json    (default: known_ids.json)
  SCRAPE_STATES     comma-separated list of states to scrape (default: all)
  MAX_PAGES         hard page cap per state (default: unlimited)
    LLM_PROVIDER      optional analyst provider override (mimo/openai)
    MIMO_API_KEY      MiMo API key for Analyst Agent (optional)
    MIMO_BASE_URL     MiMo API base URL (optional)
    MIMO_MODEL        MiMo model name (optional)
    OPENAI_API_KEY    OpenAI API key for Analyst Agent (optional)
  ANALYST_MODEL     model to use (default: gpt-4o-mini)
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
MARKET_CACHE_PATH = os.environ.get(
    "MARKET_CACHE_PATH",
    str(SCRIPT_DIR / "market_cache.json"),
)
# Set RUN_MARKET=1 to force-run market research stage (default: auto, skip if cache fresh)
RUN_MARKET = os.environ.get("RUN_MARKET", "auto").strip().lower()
ELELONG_STATE_PATH = os.environ.get(
    "ELELONG_STATE_PATH",
    str(SCRIPT_DIR / "elelong_search_state.json"),
)

# ── Imports (local modules) ───────────────────────────────────────────────────

from bidnow import BidNowScraper
from bidnow_filter_enums import BIDNOW_STATES
from elelong import ELelongScraper
from lelongtips import LelongTipsScraper
from dedup_merger import cross_reference, detect_reauction, compute_derived_fields
from geocode import Geocoder
from md_writer import MDWriter, write_daily_note
from market_research import MarketResearcher
from analyst_agent import AnalystAgent


# ── Scrape health check ───────────────────────────────────────────────────────

def _scrape_health_check(batch: List[Dict]) -> None:
    """
    Print a warning if critical ROI fields are missing in the current scrape batch.
    Detects BidNow DOM changes early: if >60% of a batch has market_value=0 or
    built_up_sqft=0, ROI calculations will be blank for most properties.
    """
    n = len(batch)
    if n == 0:
        return
    no_mv   = sum(1 for l in batch if not l.get("market_value"))
    no_sqft = sum(1 for l in batch if not l.get("built_up_sqft"))
    pct_mv   = no_mv   / n * 100
    pct_sqft = no_sqft / n * 100
    WARN_THRESHOLD = 60  # % missing before we raise the alarm
    issues: List[str] = []
    if pct_mv   > WARN_THRESHOLD:
        issues.append(f"market_value   missing in {no_mv}/{n} listings ({pct_mv:.0f}%)")
    if pct_sqft > WARN_THRESHOLD:
        issues.append(f"built_up_sqft  missing in {no_sqft}/{n} listings ({pct_sqft:.0f}%)")
    if issues:
        bar = "!" * 40
        print(f"\n  {bar}")
        print(f"  SCRAPE HEALTH WARNING")
        for issue in issues:
            print(f"  >> {issue}")
        print(f"  >> BidNow DOM may have changed — ROI fields will be blank for affected listings.")
        print(f"  >> Check bidnow.py field mappings before next production run.")
        print(f"  {bar}\n")
    else:
        mv_ok   = n - no_mv
        sqft_ok = n - no_sqft
        print(f"  [health] batch OK  mv: {mv_ok}/{n} ({100 - pct_mv:.0f}%)  "
              f"sqft: {sqft_ok}/{n} ({100 - pct_sqft:.0f}%)")


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


def load_elelong_state() -> dict:
    p = Path(ELELONG_STATE_PATH)
    if p.exists():
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_elelong_state(state: dict):
    p = Path(ELELONG_STATE_PATH)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


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
    vault_index, vault_known_ids = writer.build_vault_index_and_ids()  # single pass
    scraper_known_ids = load_known_ids()
    known_ids = vault_known_ids | scraper_known_ids
    print(f"  {len(known_ids)} known BidNow IDs")

    # Build known e-Lelong slugs from vault (EL-* prefix notes)
    known_el_slugs = {
        vid for vid in vault_index if str(vid).startswith("EL-")
    } | {
        vid for vid in vault_index.values()
        if isinstance(vid, str) and str(vid).startswith("EL-")
    }
    el_prev_state = load_elelong_state()

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

    # ── Stage 2b: e-Lelong scrape (court order, delta) ───────────────────────
    print("\n[Stage 2b] e-Lelong scrape (court orders, delta mode)...")
    all_el_listings: List[Dict] = []
    el_new_state: dict = {}
    try:
        el_scraper = ELelongScraper()
        el_states = (
            [s for s in states_to_scrape if s in ELelongScraper.__module__ or True]
        )
        # Map BidNow state names to e-Lelong — use the same list (they match)
        el_states_to_scrape = [
            s for s in states_to_scrape
            if s in {"Kuala Lumpur", "Selangor", "Putrajaya", "Johor", "Kedah",
                     "Kelantan", "Melaka", "Negeri Sembilan", "Pahang",
                     "Penang", "Perak", "Perlis", "Terengganu"}
        ] or None  # None = all e-Lelong states
        all_el_listings, el_new_state = el_scraper.scrape_listings(
            known_slugs=known_el_slugs,
            prev_search_state=el_prev_state,
            states=el_states_to_scrape,
            max_listings=2000,
        )
        save_elelong_state(el_new_state)
        print(f"  e-Lelong total: {len(all_el_listings)} new court-order listings")
    except Exception as exc:
        print(f"  [e-Lelong] Stage error: {exc}")
        import traceback; traceback.print_exc()

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
    merged_listings = cross_reference(all_bn_listings, all_llt_listings)    # Append e-Lelong listings directly (no LLT cross-ref — different source)
    merged_listings.extend(all_el_listings)
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

    # ── Scrape health check ───────────────────────────────────────────────────
    all_scraped = all_bn_listings + all_el_listings + all_llt_listings
    _scrape_health_check(all_scraped)

    # ── Stage 8: Market Research (high-priority only) ────────────────────────
    print("\n[Stage 8] Market research enrichment...")
    market_enriched = 0
    market_skipped  = 0
    try:
        researcher = MarketResearcher(MARKET_CACHE_PATH)
        if RUN_MARKET == "1":
            print("  Force-refreshing market cache (RUN_MARKET=1)...")
            researcher.force_refresh()

        # Collect enriched listings (those with market data) and re-write their notes
        enrichable = [l for _, l, _ in enriched]
        m_enriched, m_skipped = researcher.enrich_listings(enrichable)

        # Batch coverage check: if > 30% of enrichable listings got no market data,
        # the cache may be stale or incomplete — force a full rebuild and re-enrich.
        no_data = sum(1 for l in enrichable if not l.get("market_rent_est"))
        coverage_pct = (len(enrichable) - no_data) / len(enrichable) * 100 if enrichable else 100
        print(f"  Market coverage: {coverage_pct:.0f}% ({len(enrichable) - no_data}/{len(enrichable)} enriched)")
        if enrichable and no_data / len(enrichable) > 0.30:
            print(f"  [market] >30% without data — rebuilding full cache...")
            researcher.force_refresh()
            m_enriched, m_skipped = researcher.enrich_listings(enrichable)
            print(f"  [market] Post-rebuild: {m_enriched} enriched, {m_skipped} skipped")
        market_enriched = m_enriched
        market_skipped  = m_skipped
        print(f"  {m_enriched} high-priority properties enriched with market data")
        print(f"  {m_skipped} properties skipped (low priority or no area match)")

        # Re-write notes that received market data
        mkt_written = 0
        for listing in enrichable:
            if listing.get("market_sale_psf"):
                try:
                    writer.write(listing, "update_price")  # update-only, preserves Notes
                    mkt_written += 1
                except Exception as exc:
                    print(f"  [market write] ERROR {listing.get('listing_id')}: {exc}")
        print(f"  {mkt_written} notes updated with market data")
    except Exception as exc:
        print(f"  [market] Stage error: {exc}")
        import traceback; traceback.print_exc()

    # ── Stage 9: Analyst Agent ───────────────────────────────────────────
    print("\n[Stage 9] Analyst Agent (LLM investment scoring)...")
    agent_enriched = 0
    agent_skipped  = 0
    try:
        analyst = AnalystAgent()
        # Always run enrich_listings — it falls back to rule-based scoring when
        # no LLM provider is configured, so vault notes are always scored.
        agent_enriched, agent_skipped = analyst.enrich_listings(enrichable)
        provider_label = {"mimo": "MiMo", "openai": "OpenAI"}.get(analyst.llm_provider, "LLM")
        mode = provider_label if analyst.available else "rule-based fallback"
        print(f"  {agent_enriched} properties scored ({mode})")
        print(f"  {agent_skipped} properties skipped (below priority threshold)")

        # Re-write notes that received agent recommendations
        agent_written = 0
        for listing in enrichable:
            if listing.get("agent_recommendation"):
                try:
                    writer.write(listing, "update_price")
                    agent_written += 1
                except Exception as exc:
                    print(f"  [agent write] ERROR {listing.get('listing_id')}: {exc}")
        print(f"  {agent_written} notes updated with agent recommendation")
    except Exception as exc:
        print(f"  [analyst] Stage error: {exc}")
        import traceback; traceback.print_exc()

    # ── Stage 10: Daily Note ─────────────────────────────────────────
    print("\n[Stage 10] Writing daily note...")
    try:
        write_daily_note(DAILY_NOTES_PATH, TEMPLATES_PATH)
    except Exception as exc:
        print(f"  [daily note] ERROR: {exc}")

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Run complete — {today}")
    print(f"  BidNow fetched   : {len(all_bn_listings)}")
    print(f"  e-Lelong fetched : {len(all_el_listings)}")
    print(f"  LLT fetched      : {len(all_llt_listings)}")
    print(f"  LLT matched      : {sum(1 for l in merged_listings if l.get('llt_slug'))}")
    print(f"  New properties   : {actions['create']}")
    print(f"  Price updates    : {actions['update_price']}")
    print(f"  New rounds       : {actions['new_round']}")
    print(f"  Notes written    : {written}")
    print(f"  Market enriched  : {market_enriched}")
    print(f"  Agent scored     : {agent_enriched}")
    print(f"  Total vault size : {len(all_known)} known IDs")
    print(f"  e-Lelong new     : {len(all_el_listings)}")
    print(f"{'='*60}\n")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
