"""
e2e_due_diligence.py — Full property auction due diligence flow.

Stages:
  1. SCRAPE         BidNow + e-Lelong (KL, limited pages)
  2. SELECT         Auto-pick best candidate (highest BMV% with known data)
  3. DETAILS        Print full property card + mark as prospected
  4. POS CHECK      Identify current vs historical POS documents
  5. MARKET         iProperty competition signal (same size + locale)
  6. ENTRY COST     Stamp duty, legal fees, loan, renovation estimate
  7. ANALYSIS       Exit strategy + holding ROI (LLM or rule-based fallback)

Usage:
  python e2e_due_diligence.py
  python e2e_due_diligence.py --state Selangor --pages 3
"""

import io
import sys
import time
import argparse
import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# UTF-8 output (Windows console compatibility)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from bidnow import BidNowScraper
from elelong import ELelongScraper
from iproperty import IPropertyScraper
from market_research import MarketResearcher
from pos_identifier import identify_current_pos, validate_property_pos_status
from analyst_agent import AnalystAgent, _score_rule_based
from entry_cost import (
    calculate_entry_cost, calculate_roi,
    calculate_flip_roi,
    calculate_full_unit_rental_roi,
    calculate_room_rental_roi,
    calculate_partition_roi,
    estimate_partition_rooms,
    APPRECIATION_PA,
)

# ── Constants ─────────────────────────────────────────────────────────────────

MARKET_CACHE_PATH = str(SCRIPT_DIR / "market_cache.json")
ELELONG_STATE_PATH = str(SCRIPT_DIR / "elelong_search_state.json")

# iProperty state slug mapping
STATE_SLUG: Dict[str, str] = {
    "Kuala Lumpur":      "kuala-lumpur",
    "Selangor":          "selangor",
    "Putrajaya":         "putrajaya",
    "Penang":            "penang",
    "Johor":             "johor",
    "Melaka":            "melaka",
    "Negeri Sembilan":   "negeri-sembilan",
    "Kedah":             "kedah",
    "Perak":             "perak",
    "Pahang":            "pahang",
    "Kelantan":          "kelantan",
    "Terengganu":        "terengganu",
    "Perlis":            "perlis",
    "Sabah":             "sabah",
    "Sarawak":           "sarawak",
}

# iProperty property category mapping (BidNow type → iProperty slug)
PROP_CATEGORY: Dict[str, str] = {
    "condominium":          "apartment-condo",
    "apartment":            "apartment-condo",
    "serviced apartment":   "apartment-condo",
    "flat":                 "apartment-condo",
    "terrace":              "terrace-link-house",
    "terrace house":        "terrace-link-house",
    "townhouse":            "terrace-link-house",
    "townhouse/link":       "terrace-link-house",
    "link house":           "terrace-link-house",
    "semi-d":               "semi-detached-house",
    "semi-detached":        "semi-detached-house",
    "semi detached":        "semi-detached-house",
    "bungalow":             "bungalow",
    "detached":             "bungalow",
}
DEFAULT_CATEGORY = "apartment-condo"

LANDED_TYPES = {
    "terrace-link-house", "semi-detached-house", "bungalow",
}

# Monthly maintenance estimate by property type (for net yield calc)
MAINTENANCE_EST: Dict[str, float] = {
    "condominium":        350.0,
    "condo":              350.0,
    "apartment":          200.0,
    "serviced apartment": 350.0,
    "flat":               150.0,
    "terrace":            150.0,
    "semi-d":             200.0,
    "bungalow":           300.0,
}
DEFAULT_MAINTENANCE = 250.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _w(label: str, value: str, width: int = 22):
    """Fixed-width label: value line."""
    return f"  {label:<{width}}: {value}"


def _rm(value) -> str:
    if value is None:
        return "N/A"
    return f"RM {float(value):,.0f}"


def _pct(value, suffix: str = "%") -> str:
    if value is None:
        return "N/A"
    return f"{float(value):.1f}{suffix}"


def _sep(char: str = "-", width: int = 70) -> str:
    return "  " + char * (width - 2)


def _header(title: str, width: int = 70) -> str:
    pad = max(0, (width - len(title) - 4) // 2)
    return f"\n{'=' * width}\n  {'=' * pad} {title} {'=' * pad}\n{'=' * width}"


def _select_best(listings: List[Dict]) -> Optional[Dict]:
    """
    Select the most suitable property for due diligence:
    Priority: has reserve_price > 0, has bmv_pct > 0, highest BMV%.
    Secondary: has built_up_sqft (needed for competition signal).
    Tertiary: has pos_url (POS check possible).
    """
    candidates = [
        l for l in listings
        if (l.get("reserve_price") or 0) > 0
        and (l.get("bmv_pct") or l.get("bmv_percent") or 0) > 0
    ]
    if not candidates:
        candidates = [l for l in listings if (l.get("reserve_price") or 0) > 0]
    if not candidates:
        return listings[0] if listings else None

    # Sort: built_up_sqft > 0 preferred, then by bmv_pct descending
    candidates.sort(key=lambda l: (
        -1 if (l.get("built_up_sqft") or 0) > 0 else 0,
        -(float(l.get("bmv_pct") or l.get("bmv_percent") or 0)),
    ))
    return candidates[0]


def _clean_state(raw: str) -> str:
    """
    Strip leading 5-digit postcode from BidNow state strings.
    BidNow sometimes returns e.g. '56000 Kuala Lumpur' instead of 'Kuala Lumpur'.
    """
    import re as _re
    return _re.sub(r'^\d{5}\s+', '', (raw or '').strip())


def _get_category(listing: Dict) -> str:
    pt = (listing.get("property_type") or "").lower().strip()
    return PROP_CATEGORY.get(pt, DEFAULT_CATEGORY)


def _get_state_slug(listing: Dict) -> str:
    state = _clean_state(listing.get("state") or "")
    return STATE_SLUG.get(state, state.lower().replace(" ", "-"))


def _is_landed(category: str) -> bool:
    return category in LANDED_TYPES


# ── Stage functions ───────────────────────────────────────────────────────────

def stage_scrape(state: str, bn_pages: int, el_pages: int) -> List[Dict]:
    all_listings: List[Dict] = []

    # BidNow
    print(f"\n  BidNow.my — {state}, up to {bn_pages} page(s)...")
    t0 = time.time()
    try:
        bn = BidNowScraper()
        filters = {"state": state, "listing": "active", "sort": "new"}
        bn_listings = bn.scrape_listings(filters=filters, max_pages=bn_pages, known_ids=set())
        elapsed = time.time() - t0
        print(f"  => {len(bn_listings)} listings in {elapsed:.1f}s")
        all_listings.extend(bn_listings)
    except Exception as exc:
        print(f"  => BidNow ERROR: {exc}")

    # e-Lelong
    el_state_path = Path(ELELONG_STATE_PATH)
    prev_state = json.loads(el_state_path.read_text(encoding="utf-8")) \
                 if el_state_path.exists() else {}
    print(f"\n  e-Lelong — {state}, up to {el_pages} pages...")
    t0 = time.time()
    try:
        el = ELelongScraper()
        el_listings, new_state = el.scrape_listings(
            known_slugs=set(),
            prev_search_state=prev_state,
            states=[state],
            max_listings=el_pages * 20,
        )
        elapsed = time.time() - t0
        print(f"  => {len(el_listings)} listings in {elapsed:.1f}s")
        all_listings.extend(el_listings)
        el_state_path.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"  => e-Lelong ERROR: {exc}")

    return all_listings


def stage_details(listing: Dict):
    bmv  = listing.get("bmv_pct") or listing.get("bmv_percent") or 0
    rnd  = listing.get("auction_count", 1) or 1
    sqft = listing.get("built_up_sqft") or 0
    land = listing.get("land_area_sqft") or 0
    state_clean = _clean_state(listing.get("state") or "")
    print(_w("Listing ID",    str(listing.get("listing_id", "?"))))
    print(_w("Source",        str(listing.get("source", "?"))))
    print(_w("Address",       str(listing.get("full_address", "?"))[:80]))
    print(_w("Type",          str(listing.get("property_type", "?"))))
    print(_w("Tenure",        str(listing.get("tenure", "?"))))
    print(_w("State",         state_clean))
    print(_w("District",      str(listing.get("district") or listing.get("city", "?"))))
    print(_sep())
    print(_w("Reserve Price", _rm(listing.get("reserve_price"))))
    print(_w("Market Value",  _rm(listing.get("market_value"))))
    print(_w("BMV%",          _pct(bmv)))
    print(_w("Auction Date",  str(listing.get("auction_date", "?"))))
    print(_w("Auction Round", f"R{rnd}"))
    print(_w("Bank",          str(listing.get("bank", "?"))))
    print(_sep())
    size_str = f"{sqft:,.0f} sqft built-up" if sqft else "Unknown"
    if land:
        size_str += f" + {land:,.0f} sqft land"
    print(_w("Size",          size_str))
    print(_w("POS URL",       str(listing.get("pos_url") or "N/A")[:80]))
    if listing.get("case_number"):
        print(_w("Case No.",  str(listing.get("case_number", ""))))
    if listing.get("encumbrances"):
        print(_w("Encumbrances", str(listing.get("encumbrances", ""))[:60]))


def stage_pos_check(listing: Dict) -> Dict:
    lid_raw  = listing.get("listing_id", "")
    pos_url  = listing.get("pos_url", "") or ""
    source   = listing.get("source", "")

    if source == "elelong":
        # e-Lelong: POS is a direct EFS document link (already current)
        if pos_url and "efs.kehakiman.gov.my" in pos_url:
            return {
                "status":     "valid",
                "message":    "e-Lelong POS is a live EFS court document link",
                "pos_url":    pos_url,
                "source":     "elelong",
            }
        return {
            "status":   "missing",
            "message":  "No POS URL found in e-Lelong listing",
            "source":   "elelong",
        }

    # BidNow: use pos_identifier path-based check
    try:
        prop_id_str = str(lid_raw).replace("BN-", "").replace("EL-", "")
        prop_id = int(prop_id_str) if prop_id_str.isdigit() else 0
    except Exception:
        prop_id = 0

    if not pos_url:
        return {"status": "missing", "message": "No POS URL on this listing"}

    # Derive file_path from URL (path after domain)
    from urllib.parse import urlparse
    path_part = urlparse(pos_url).path
    property_data = {
        "property_id": prop_id,
        "property_title": listing.get("full_address", ""),
        "pdfs": [{"file_path": path_part, "timestamp": ""}],
    }
    result = validate_property_pos_status(property_data)

    # ── POS text extraction + field parsing ───────────────────────────────────
    from pdf_extractor import extract_text
    from pos_parser import parse_pos_fields
    try:
        raw = extract_text(url=pos_url)
        if raw.get("extracted_text"):
            pos_fields = parse_pos_fields(raw["extracted_text"])
            if pos_fields:
                result["pos_fields"] = pos_fields
                result["pos_pages"]  = raw.get("page_count", 0)

                # ── Hermes fallback: LLM fills fields regex couldn't extract ──
                if not pos_fields.get("_extraction_complete"):
                    try:
                        from hermes import HermesAgent
                        _hermes = HermesAgent()
                        if _hermes.available:
                            pos_fields = _hermes.enrich_pos(
                                raw["extracted_text"], pos_fields
                            )
                            result["pos_fields"] = pos_fields
                    except Exception as _he:
                        result["pos_hermes_error"] = str(_he)
    except Exception as exc:
        result["pos_parse_error"] = str(exc)

    return result


def stage_market(listing: Dict) -> Tuple[Dict, Dict]:
    """
    Returns (competition_signal, market_research_dict).
    competition_signal: iProperty comparable count + level
    market_research: PSF benchmark from market_cache
    """
    category  = _get_category(listing)
    state_slug = _get_state_slug(listing)
    reserve   = float(listing.get("reserve_price") or 0)
    sqft      = float(listing.get("built_up_sqft") or 0)
    land_sqft = float(listing.get("land_area_sqft") or 0)

    # iProperty competition signal
    t0 = time.time()
    competition = {}
    try:
        ip = IPropertyScraper()
        competition = ip.get_competition_signal(
            target_price=reserve,
            target_sqft=sqft,
            target_land_sqft=land_sqft if _is_landed(category) else 0.0,
            state_slug=state_slug,
            property_category=category,
            price_tolerance_pct=25.0,
            size_tolerance_pct=10.0,
            max_pages=2,
        )
    except Exception as exc:
        competition = {"competition_level": "Error", "error": str(exc)}
    competition["_elapsed"] = round(time.time() - t0, 1)

    # Market research (PSF benchmark from iProperty — always fresh for due diligence)
    mkt = {}
    try:
        researcher = MarketResearcher(MARKET_CACHE_PATH)
        # Force a fresh fetch when cache is not from today so the user never
        # evaluates a deal against stale rent/PSF benchmarks.
        _cache_fresh = False
        if researcher.cache_path.exists():
            try:
                import json as _json
                _raw = _json.loads(researcher.cache_path.read_text(encoding="utf-8"))
                from datetime import date as _date
                _cache_fresh = _raw.get("built_at", "")[:10] == _date.today().isoformat()
            except Exception:
                pass
        if not _cache_fresh:
            researcher.force_refresh()
        researcher.enrich_listings([listing])
        mkt = {k: v for k, v in listing.items() if k.startswith("market_")
               or k in {"independent_bmv_pct", "est_rental_yield", "market_rent_est"}}
    except Exception as exc:
        mkt = {"error": str(exc)}

    return competition, mkt


def stage_entry_cost(listing: Dict, reno_level: str = "light") -> Tuple[Dict, Dict, Dict, Dict, Dict, Dict]:
    """
    Returns (entry_cost, flip_roi, full_unit_roi, room_rental_roi, partition_roi, hold_roi).

    Rental scenario logic:
      flip_roi        — sell at current market value today (no appreciation est.)
      full_unit_roi   — rent whole unit as single tenancy (iProperty market rate)
      room_rental_roi — rent individual bedrooms, existing structure (co-living)
      partition_roi   — drywall conversion into more rooms (highest gross yield)
      hold_roi        — capital appreciation only, no rental income
    """
    reserve   = float(listing.get("reserve_price") or 0)
    state     = _clean_state(listing.get("state") or "")
    pt        = (listing.get("property_type") or "").lower()
    maint     = MAINTENANCE_EST.get(pt, DEFAULT_MAINTENANCE)
    sqft      = float(listing.get("built_up_sqft") or 0)
    bedrooms  = int(listing.get("bedrooms") or listing.get("num_bedrooms") or 0)

    # Full-unit rent: prefer market_rent_est (iProperty cache)
    rent_est    = float(listing.get("market_rent_est") or 0)
    rent_source = "iProperty" if rent_est > 0 else "unavailable"

    # Current market value for flip
    mkt_val = float(
        listing.get("market_value") or
        listing.get("market_value_est") or
        0
    )

    ec           = calculate_entry_cost(reserve, reno_level=reno_level)
    flip_roi     = calculate_flip_roi(reserve, mkt_val, ec)
    full_unit    = calculate_full_unit_rental_roi(
        reserve, ec,
        monthly_rent_est=rent_est,
        rent_source=rent_source,
        state=state,
        holding_years=5,
        maintenance_monthly=maint,
    )
    room_rental  = calculate_room_rental_roi(
        reserve, ec,
        bedrooms=bedrooms,
        built_up_sqft=sqft,
        state=state,
        holding_years=5,
    ) if sqft > 0 or bedrooms > 0 else {"roi_mode": "room_rental", "error": "sqft/bedroom data unavailable"}
    partition    = calculate_partition_roi(
        reserve, ec,
        built_up_sqft=sqft,
        state=state,
        holding_years=5,
    ) if sqft > 0 else {"roi_mode": "partition", "error": "built_up_sqft not available"}
    hold_roi     = calculate_roi(
        reserve, ec,
        monthly_rent_est=0.0,
        state=state,
        holding_years=5,
        maintenance_monthly=maint,
    )
    return ec, flip_roi, full_unit, room_rental, partition, hold_roi


def stage_analysis(listing: Dict, entry_cost: Dict, competition: Dict) -> Dict:
    analyst = AnalystAgent()
    if analyst.available:
        result = analyst.analyze(listing, entry_cost=entry_cost, competition=competition)
        if result:
            return result
    return _score_rule_based(listing)


# ── Report printer ────────────────────────────────────────────────────────────

def print_report(
    listing: Dict,
    pos_result: Dict,
    competition: Dict,
    mkt: Dict,
    entry_cost: Dict,
    flip_roi: Dict,
    full_unit: Dict,
    room_rental: Dict,
    partition: Dict,
    hold_roi: Dict,
    analysis: Dict,
):
    today = date.today().isoformat()
    print(_header(f"AUCTION PROPERTY DUE DILIGENCE  —  {today}"))

    # ── 3/7 Details (already printed inline, recap key numbers) ──
    print("\n[RECAP] Key Metrics")
    print(_sep())
    reserve = listing.get("reserve_price") or 0
    bmv     = listing.get("bmv_pct") or listing.get("bmv_percent") or 0
    mv      = listing.get("market_value") or 0
    print(_w("Reserve",       _rm(reserve)))
    print(_w("Market Value",  _rm(mv) if mv else "N/A (e-Lelong, no BidNow MV)"))
    print(_w("BMV%",          _pct(bmv) if bmv else "N/A"))
    print(_w("Auction Round", f"R{listing.get('auction_count', 1) or 1}"))
    print(_w("Auction Date",  str(listing.get("auction_date", "?"))))

    # ── 4/7 POS ──────────────────────────────────────────────────────────────
    print("\n[4/7] POS CHECK")
    print(_sep())
    status = pos_result.get("status", "unknown")
    icon   = {"valid": "OK", "expired": "EXPIRED", "missing": "MISSING"}.get(status, "?")
    print(f"  Status : [{icon}] {pos_result.get('message', '')}")
    if pos_result.get("pos_url"):
        print(f"  URL    : {pos_result['pos_url'][:80]}")
    hist = pos_result.get("previous_attempts", 0)
    if hist:
        print(f"  Previous auction rounds (historical POS): {hist}")
    if status == "missing":
        print(f"  Note   : Check BidNow listing page directly for POS download link.")
        print(f"           Some listings only upload POS close to auction date.")

    # POS-extracted fields (if PDF was parsed)
    pos_fields = pos_result.get("pos_fields", {})
    if pos_fields:
        print(f"  ── POS Extracted Fields ──")
        _pf = pos_fields
        if _pf.get("property_description"):
            print(_w("  Description", _pf["property_description"][:70], 24))
        if _pf.get("bedrooms"):
            br = f"{_pf['bedrooms']}BR"
            if _pf.get("bathrooms"):
                br += f" / {_pf['bathrooms']}BA"
            if _pf.get("floor_no"):
                br += f" / Floor {_pf['floor_no']}"
            print(_w("  Rooms", br, 24))
        if _pf.get("built_up_sqft"):
            print(_w("  Built-up (POS)", f"{_pf['built_up_sqft']:,.0f} sqft", 24))
        if _pf.get("land_area_sqft"):
            print(_w("  Land Area", f"{_pf['land_area_sqft']:,.0f} sqft", 24))
        if _pf.get("tenure"):
            print(_w("  Tenure (POS)", _pf["tenure"].capitalize(), 24))
        if _pf.get("bank"):
            print(_w("  Bank (POS)", _pf["bank"][:60], 24))
        if _pf.get("borrower"):
            print(_w("  Borrower", _pf["borrower"][:60], 24))
        if _pf.get("lawyer_firm"):
            print(_w("  Law Firm", _pf["lawyer_firm"][:60], 24))
        if _pf.get("case_no"):
            print(_w("  Case No.", _pf["case_no"], 24))
        if _pf.get("reserve_price_rm"):
            rp_pos = _pf["reserve_price_rm"]
            rp_lst = float(pos_result.get("reserve_price", listing.get("reserve_price") or 0) or 0)
            flag = "  *** MISMATCH ***" if rp_lst and abs(rp_pos - rp_lst) > 1 else ""
            print(_w("  Reserve (POS)", f"{_rm(rp_pos)}{flag}", 24))


    # ── 5/7 Market Comparison ─────────────────────────────────────────────────
    print("\n[5/7] MARKET COMPARISON")
    print(_sep())
    reserve_rpt = listing.get("reserve_price") or 0
    sqft_rpt    = listing.get("built_up_sqft") or 0
    print("  iProperty Competition Signal:")
    print(_w("  Locale",       str(competition.get("locale", "N/A")), 24))
    if reserve_rpt and sqft_rpt:
        print(_w("  Search bands",
                 f"price {_rm(reserve_rpt*0.75)}-{_rm(reserve_rpt*1.25)}  "
                 f"| size {sqft_rpt*0.9:,.0f}-{sqft_rpt*1.1:,.0f} sqft", 24))
    print(_w("  Level",        str(competition.get("competition_level", "?")), 24))
    print(_w("  Comparables",  str(competition.get("comparable_count", "N/A")), 24))
    print(_w("  Size-matched", str(competition.get("size_matched_count", "N/A")), 24))
    print(_w("  Total area",   str(competition.get("total_area_count", 0)), 24))
    med_a = competition.get("median_asking")
    print(_w("  Median asking", _rm(med_a) if med_a else "N/A", 24))
    print(_w("  Price range",  str(competition.get("price_range", "no data")), 24))
    print(_w("  Size range",   str(competition.get("size_range", "no data")), 24))
    lvl = competition.get("competition_level", "")
    n_cmp = competition.get("comparable_count") or 0
    if lvl == "Low":
        print(f"  => Low competition: few buyers at this price/size band.")
    elif lvl == "High":
        print(f"  => High competition: crowded retail market — harder to flip at premium.")
    elif n_cmp == 0 and sqft_rpt and lvl not in ("Unknown", "Error"):
        print(f"  => 0 comparables: reserve price is below all iProperty listings in this area — confirms discount.") 

    if mkt:
        print("\n  Area PSF Benchmark (iProperty national sample):")
        if mkt.get("market_sale_psf"):
            print(_w("  Sale PSF",     f"RM {mkt['market_sale_psf']:.2f}/sqft", 24))
        if mkt.get("market_rent_psf"):
            print(_w("  Rent PSF",     f"RM {mkt['market_rent_psf']:.4f}/sqft/mo", 24))
        if mkt.get("market_value_est"):
            print(_w("  Market Est",   _rm(mkt["market_value_est"]), 24))
        if mkt.get("independent_bmv_pct") is not None:
            print(_w("  Indep. BMV%",  _pct(mkt["independent_bmv_pct"]), 24))
        if mkt.get("est_rental_yield") is not None:
            print(_w("  Est. Yield",   _pct(mkt["est_rental_yield"]), 24))
        if mkt.get("market_rent_est"):
            print(_w("  Est. Rent",    f"RM {mkt['market_rent_est']:,}/mo", 24))
        if mkt.get("market_area_match"):
            print(_w("  Match level",  str(mkt["market_area_match"]), 24))
    else:
        print("  No PSF benchmark available for this area.")

    # ── 6/7 Entry Cost ────────────────────────────────────────────────────────
    print("\n[6/7] ENTRY COST ESTIMATE")
    print(_sep())
    print(_w("Reserve price",     _rm(entry_cost["reserve_price_rm"])))
    print(_w("Deposit (10%)",     _rm(entry_cost["deposit_rm"])))
    print(_w("Balance (90%)",     _rm(entry_cost["balance_rm"])))
    print(_w("Loan @ 90%",        _rm(entry_cost["loan_amount_rm"])))
    print(_sep("."))
    print(_w("Stamp duty (MOT)",  _rm(entry_cost["stamp_duty_rm"])))
    print(_w("Loan stamp duty",   _rm(entry_cost["loan_stamp_duty_rm"])))
    print(_w("Legal fees",        _rm(entry_cost["legal_fees_rm"])))
    print(_w("Valuation fee",     _rm(entry_cost["valuation_fee_rm"])))
    print(_w("Bank processing",   _rm(entry_cost["bank_processing_rm"])))
    print(_w("Misc / searches",   _rm(entry_cost["misc_rm"])))
    print(_w("Renovation (light)",_rm(entry_cost["reno_rm"])))
    print(_sep("."))
    print(_w("TOTAL CASH DAY-1",  _rm(entry_cost["total_cash_day1_rm"])))
    print(_w("TOTAL INVESTMENT",  _rm(entry_cost["total_investment_rm"])))
    print(_w("Monthly instalment",f"{_rm(entry_cost['monthly_instalment_rm'])}/mo"))
    print(f"\n  Note: Total cash day-1 = deposit + all fees (paid upfront).")
    print(f"  Loan balance (RM {entry_cost['loan_amount_rm']:,.0f}) financed by bank.")

    # ── Scenario A: FLIP ─────────────────────────────────────────────────────
    print("\n  [SCENARIO A — FLIP]  Sell at current market value (no future estimate)")
    print("  " + "-" * 62)
    if flip_roi.get("error"):
        print(f"  Not available: {flip_roi['error']}")
    else:
        mv_used = flip_roi["current_market_value_rm"]
        print(_w("  Market value used",  _rm(mv_used), 28))
        print(_w("  Gross gain",         _rm(flip_roi["gross_gain_rm"]), 28))
        print(_w("  Instant equity",     _pct(flip_roi["instant_equity_pct"]) + "  (gain / reserve)", 28))
        print(_w("  Agent commission",   _rm(flip_roi["agent_commission_rm"]) + f"  (2.5%)", 28))
        print(_w("  Disposal legal",     _rm(flip_roi["disposal_legal_rm"]), 28))
        print(_w("  RPGT",               _rm(flip_roi["rpgt_rm"]) + f"  ({flip_roi['rpgt_rate_pct']:.0f}% — sold < 3yr)", 28))
        print(_w("  Net proceeds",       _rm(flip_roi["net_proceeds_rm"]), 28))
        print(_w("  Net profit",         _rm(flip_roi["net_profit_rm"]), 28))
        print(_w("  FLIP ROI",           _pct(flip_roi["roi_pct"]) + "  (on total cash day-1)", 28))
        verdict = "POSITIVE — property is undervalued at auction reserve." if flip_roi["net_profit_rm"] > 0 else "NEGATIVE after RPGT + disposal costs."
        print(f"  => Flip margin is {verdict}")
        print(f"  NOTE: Market value from BidNow — verify with independent valuation before bidding.")

    state_disp = _clean_state(listing.get("state") or "")

    # ── Scenario B: FULL UNIT RENTAL ─────────────────────────────────────────
    print(f"\n  [SCENARIO B — FULL UNIT RENTAL, 5YR HOLD]")
    print("  " + "-" * 62)
    rent_src     = full_unit.get("rent_source", "unavailable")
    rent_monthly = full_unit.get("monthly_rent_est_rm", 0)
    if rent_monthly > 0:
        print(_w("  Monthly rent",       f"RM {rent_monthly:,.0f}/mo  (source: {rent_src})", 28))
        print(_w("  Eff. monthly rent",  f"RM {full_unit.get('eff_monthly_rm', 0):,.0f}/mo  (vacancy+maint deducted)", 28))
        cf = full_unit.get("monthly_cashflow_rm", 0)
        print(_w("  Monthly cashflow",   f"RM {abs(cf):,.0f}/mo {'surplus' if cf >= 0 else 'shortfall'}", 28))
        print(_w("  Gross yield",        _pct(full_unit.get("gross_yield_pct")) + " pa", 28))
        print(_w("  Net yield",          _pct(full_unit.get("net_yield_pct")) + " pa", 28))
        if full_unit.get("payback_years"):
            print(_w("  Payback",        f"{full_unit['payback_years']} yrs (rent covers total investment)", 28))
    else:
        print(f"  Rental estimate unavailable — market cache may not cover this area.")
        print(f"  Check iProperty.com.my/property-for-rent for {state_disp} rental benchmarks.")
    print(_w("  Appreciation",       f"{full_unit.get('appreciation_rate_pct', 2.5)}% pa ({state_disp})", 28))
    print(_w("  Exit price (yr 5)",  _rm(full_unit.get("exit_price_est_rm")), 28))
    print(_w("  Net cap gain",       _rm(full_unit.get("net_capital_gain_rm")), 28))
    print(_w("  FULL UNIT ROI (5yr)",_pct(full_unit.get("roi_pct")) + "  (on total cash day-1)", 28))
    print(f"  Note: Single tenancy — simplest management, lowest gross yield per sqft.")

    # ── Scenario C: ROOM RENTAL ───────────────────────────────────────────────
    print(f"\n  [SCENARIO C — ROOM RENTAL, 5YR HOLD]  Existing structure, co-living")
    print("  " + "-" * 62)
    if room_rental.get("error"):
        print(f"  Not available: {room_rental['error']}")
    else:
        print(_w("  Total rooms",        str(room_rental.get("num_rooms", "?")), 28))
        for rb in room_rental.get("room_breakdown", []):
            print(_w(f"    {rb['type'].title()} ×{rb['count']}",
                     f"RM {rb['rate_rm']:,.0f}/mo each = RM {rb['monthly_rm']:,.0f}/mo (post-vacancy)", 28))
        print(_w("  Gross monthly",      f"RM {room_rental.get('gross_monthly_rm', 0):,.0f}/mo", 28))
        print(_w("  Landlord OPEX",      f"RM {room_rental.get('opex_monthly_rm', 0):,.0f}/mo  (util+WiFi+cleaning+mgmt)", 28))
        print(_w("  Eff. monthly",       f"RM {room_rental.get('eff_monthly_rm', 0):,.0f}/mo", 28))
        cf = room_rental.get("monthly_cashflow_rm", 0)
        print(_w("  Monthly cashflow",   f"RM {abs(cf):,.0f}/mo {'surplus' if cf >= 0 else 'shortfall'}", 28))
        print(_w("  Gross yield",        _pct(room_rental.get("gross_yield_pct")) + " pa", 28))
        print(_w("  Net yield",          _pct(room_rental.get("net_yield_pct")) + " pa", 28))
        if room_rental.get("payback_years"):
            print(_w("  Payback",        f"{room_rental['payback_years']} yrs", 28))
        print(_w("  ROOM ROI (5yr)",     _pct(room_rental.get("roi_pct")) + "  (on total cash day-1)", 28))
        print(f"  Rates: master RM1,000-1,200 / middle RM800-1,000 / small RM700-850")
        print(f"  Cross-check: iBilik.my (room-for-rent listings in this area)")

    # ── Scenario D: PARTITION RENTAL ─────────────────────────────────────────
    print(f"\n  [SCENARIO D — PARTITION RENTAL, 5YR HOLD]  Drywall conversion, co-living")
    print("  " + "-" * 62)
    if partition.get("error"):
        print(f"  Not available: {partition['error']}")
    else:
        rd = partition.get("room_detail") or {}
        sqft = listing.get("built_up_sqft") or 0
        print(_w("  Unit size",          f"{sqft} sqft built-up", 28))
        print(_w("  Useable sqft",       f"{rd.get('useable_sqft', '?')} sqft (25% deducted for common areas)", 28))
        print(_w("  Partition rooms",    str(partition.get("num_rooms", "?")), 28))
        print(_w("    En-suite",         f"{partition.get('num_ensuite', 0)} rooms (with attached toilet)", 28))
        print(_w("    Shared-WC",        f"{partition.get('num_shared', 0)} rooms ({rd.get('shared_toilets', '?')} shared toilet bloc(s))", 28))
        print(_w("  Conversion CAPEX",   _rm(partition.get("partition_capex_rm")), 28))
        print(_w("  Total investment",   _rm(partition.get("total_investment_rm")) + "  (entry + partition)", 28))
        for rb in partition.get("room_breakdown", []):
            t = "En-suite" if rb["type"] == "ensuite" else "Shared-WC"
            print(_w(f"    {t} ×{rb['count']}",
                     f"RM {rb['rate_rm']:,.0f}/mo each = RM {rb['monthly_rm']:,.0f}/mo (post-vacancy)", 28))
        print(_w("  Gross monthly",      f"RM {partition.get('gross_monthly_rm', 0):,.0f}/mo", 28))
        print(_w("  Landlord OPEX",      f"RM {partition.get('opex_monthly_rm', 0):,.0f}/mo  (util+WiFi+cleaning+mgmt)", 28))
        print(_w("  Eff. monthly",       f"RM {partition.get('eff_monthly_rm', 0):,.0f}/mo", 28))
        cf = partition.get("monthly_cashflow_rm", 0)
        print(_w("  Monthly cashflow",   f"RM {abs(cf):,.0f}/mo {'surplus' if cf >= 0 else 'shortfall'}", 28))
        print(_w("  Gross yield",        _pct(partition.get("gross_yield_pct")) + " pa", 28))
        print(_w("  Net yield",          _pct(partition.get("net_yield_pct")) + " pa", 28))
        if partition.get("payback_years"):
            print(_w("  Payback",        f"{partition['payback_years']} yrs (incl. CAPEX in investment base)", 28))
        print(_w("  PARTITION ROI (5yr)",_pct(partition.get("roi_pct")) + "  (on cash day-1 + CAPEX)", 28))
        print(f"  Rates: ensuite RM900-1,100 / shared-WC RM600-900")
        print(f"  IMPORTANT: Local authority permit required for structural works.")
        print(f"  Cross-check: iBilik.my (bilik sewa / partition listings in this area)")

    # ── Scenario E: CAPITAL HOLD ─────────────────────────────────────────────
    print(f"\n  [SCENARIO E — CAPITAL HOLD 5YR]  No rental income")
    print("  " + "-" * 62)
    print(_w("  Appreciation",       f"{hold_roi.get('appreciation_rate_pct', 2.5)}% pa ({state_disp})", 28))
    print(_w("  Exit price (yr 5)",  _rm(hold_roi.get("exit_price_est_rm")), 28))
    print(_w("  Net cap gain",       _rm(hold_roi.get("net_capital_gain_rm")), 28))
    print(_w("  Monthly cashflow",   f"RM {abs(hold_roi.get('monthly_cashflow_rm', 0)):,.0f}/mo shortfall (instalment only)", 28))
    print(_w("  HOLD ROI (5yr)",     _pct(hold_roi.get("roi_pct")) + "  (on total cash day-1)", 28))

    # ── 7/7 Analysis ──────────────────────────────────────────────────────────
    mode = analysis.get("agent_mode", "unknown")
    mode_label = "LLM (GPT)" if mode == "llm" else "Rule-based (no API key)"
    print(f"\n[7/7] INVESTMENT ANALYSIS  [{mode_label}]")
    print(_sep())
    score = analysis.get("agent_score", 0)
    rec   = (analysis.get("agent_recommendation") or "").upper()
    bar   = "#" * (score // 5) + "-" * (20 - score // 5)
    print(f"  Score          : {score}/100  [{bar}]")
    print(f"  Recommendation : {rec}")
    print(f"  Exit Strategy  : {analysis.get('agent_exit_strategy', 'N/A').upper()}")
    print(f"  Holding Period : {analysis.get('agent_holding_period', 'N/A')}")
    print(f"\n  Reasoning:")
    print(f"    {analysis.get('agent_reasoning', 'N/A')}")
    print(f"\n  Key Risks:")
    for risk in (analysis.get("agent_key_risks") or "").split(","):
        r = risk.strip()
        if r:
            print(f"    - {r}")
    print(f"\n  Due Diligence Checklist:")
    for chk in (analysis.get("agent_due_diligence") or "").split(","):
        c = chk.strip()
        if c:
            print(f"    [ ] {c}")

    # ── Footer ────────────────────────────────────────────────────────────────
    print(_header("END OF REPORT"))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Property auction due diligence E2E")
    parser.add_argument("--state",    default="Kuala Lumpur", help="State to scrape")
    parser.add_argument("--bn-pages", type=int, default=2, help="BidNow pages to fetch")
    parser.add_argument("--el-pages", type=int, default=2, help="e-Lelong pages to fetch")
    parser.add_argument("--reno",     default="light",
                        choices=["none", "light", "moderate", "heavy"],
                        help="Renovation level for cost estimate")
    parser.add_argument("--auto",     action="store_true",
                        help="Auto-select top BMV listing without interactive prompt")
    args = parser.parse_args()

    print(_header(f"AUCTION PROPERTY DUE DILIGENCE  —  {date.today()}"))
    print(f"\n  State : {args.state}  |  BidNow pages: {args.bn_pages}"
          f"  |  e-Lelong pages: {args.el_pages}")
    total_start = time.time()

    # ── Stage 1: Scrape ───────────────────────────────────────────────────────
    print("\n[1/7] SCRAPING")
    print(_sep())
    listings = stage_scrape(args.state, args.bn_pages, args.el_pages)
    print(f"\n  Total listings scraped: {len(listings)}")
    if not listings:
        print("  ERROR: No listings scraped — cannot continue.")
        return 1

    # ── Stage 2: Select ───────────────────────────────────────────────────────
    print("\n[2/7] PROPERTY SELECTION")
    print(_sep())
    selected = _select_best(listings)
    if not selected:
        print("  ERROR: Could not select a candidate.")
        return 1
    bmv_sel = selected.get("bmv_pct") or selected.get("bmv_percent") or 0
    print(f"  Selected: [{selected.get('listing_id')}]  {(selected.get('full_address') or '')[:70]}")
    print(f"  BMV: {bmv_sel}%  |  Reserve: {_rm(selected.get('reserve_price'))}"
          f"  |  Type: {selected.get('property_type', '?')}"
          f"  |  Size: {selected.get('built_up_sqft') or '?'} sqft built-up")
    print(f"  Source: {selected.get('source', '?')}  |  Round: R{selected.get('auction_count', 1) or 1}")
    print(f"\n  *** Property marked as PROSPECTED ***")

    # ── Stage 3: Details ──────────────────────────────────────────────────────
    print("\n[3/7] PROPERTY DETAILS")
    print(_sep())
    stage_details(selected)

    # ── Stage 4: POS ─────────────────────────────────────────────────────────
    print("\n[4/7] POS CHECK")
    print(_sep())
    pos_result = stage_pos_check(selected)

    # Propagate POS-extracted fields into selected before entry cost / analysis.
    # Fields extracted from POS override gaps in the listing (never overwrite
    # non-zero existing values).
    pos_fields = pos_result.get("pos_fields", {})
    if pos_fields:
        _POS_FIELD_MAP = {
            "bedrooms":       "bedrooms",
            "bathrooms":      "bathrooms",
            "floor_no":       "floor_no",
            "built_up_sqft":  "built_up_sqft",
            "tenure":         "tenure",
            "bank":           "bank",
            "borrower":       "borrower",
            "lawyer_firm":    "lawyer",
            "district":       "district",
        }
        for pos_key, listing_key in _POS_FIELD_MAP.items():
            if pos_key in pos_fields and not selected.get(listing_key):
                selected[listing_key] = pos_fields[pos_key]
        if pos_fields.get("bedrooms"):
            print(f"  POS extracted: bedrooms={pos_fields['bedrooms']}"
                  + (f"  bathrooms={pos_fields['bathrooms']}" if pos_fields.get("bathrooms") else "")
                  + (f"  floor={pos_fields['floor_no']}" if pos_fields.get("floor_no") else ""))

    # ── Stage 5: Market ───────────────────────────────────────────────────────
    print("\n[5/7] MARKET COMPARISON  (iProperty + area PSF benchmark)")
    print(_sep())
    competition, mkt = stage_market(selected)
    # Copy enriched market fields back into selected for analyst prompt
    selected.update({k: v for k, v in mkt.items() if k not in selected})

    # ── Stage 6: Entry Cost ───────────────────────────────────────────────────
    print("\n[6/7] ENTRY COST ESTIMATE")
    print(_sep())
    entry_cost, flip_roi, full_unit, room_rental, partition, hold_roi = stage_entry_cost(selected, reno_level=args.reno)

    # ── Stage 7: Analysis ─────────────────────────────────────────────────────
    print("\n[7/7] INVESTMENT ANALYSIS")
    print(_sep())
    print("  Running analyst (LLM if API key set, rule-based fallback)...")
    analysis = stage_analysis(selected, entry_cost, competition)
    mode = "GPT" if analysis.get("agent_mode") == "llm" else "rule-based"
    print(f"  Done ({mode})")

    # ── Full report ───────────────────────────────────────────────────────────
    print_report(selected, pos_result, competition, mkt, entry_cost, flip_roi, full_unit, room_rental, partition, hold_roi, analysis)

    elapsed = time.time() - total_start
    print(f"\n  Total elapsed: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
