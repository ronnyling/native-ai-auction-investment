"""
dedup_merger.py — Cross-source identity resolution and re-auction detection.

Responsibilities:
1. Cross-reference BidNow listings with LelongTips listings
   - Match by postcode + fuzzy street name (rapidfuzz ≥ 85 score)
   - Supplement BidNow records with LLT auction_history when matched

2. Re-auction detection against existing vault records
   - Same address+postcode already in vault:
       → same auction_date  : price update only
       → new auction_date   : new auction round — append to auction_history,
                              increment auction_count, add "reauction" tag
   - Not in vault          : new property

3. Compute derived fields
   - days_to_auction  (from today)
   - original_reserve (first entry in auction_history)
   - total_price_drop (original_reserve - latest reserve_price)
   - region           (from state name)
"""

import re
from datetime import date, datetime
from typing import Dict, List, Optional, Set, Tuple

try:
    from rapidfuzz import fuzz
    FUZZY_AVAILABLE = True
except ImportError:
    FUZZY_AVAILABLE = False
    print("[dedup] WARNING: rapidfuzz not installed — fuzzy matching disabled, "
          "exact postcode+street match only")


# ── Region mapping ────────────────────────────────────────────────────────────

STATE_TO_REGION: Dict[str, str] = {
    "Kuala Lumpur": "Klang Valley",
    "Selangor": "Klang Valley",
    "Putrajaya": "Klang Valley",
    "Penang": "Northern",
    "Kedah": "Northern",
    "Perlis": "Northern",
    "Perak": "Northern",
    "Johor": "Southern",
    "Melaka": "Southern",
    "Negeri Sembilan": "Southern",
    "Pahang": "East Coast",
    "Terengganu": "East Coast",
    "Kelantan": "East Coast",
    "Sabah": "East Malaysia",
    "Sarawak": "East Malaysia",
}


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalise_street(address: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    s = address.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_postcode(address: str) -> str:
    """Extract 5-digit Malaysian postcode from an address string."""
    m = re.search(r"\b(\d{5})\b", address)
    return m.group(1) if m else ""


def _street_similarity(a: str, b: str) -> int:
    """Return fuzzy similarity score 0-100 between two normalised address strings."""
    if not FUZZY_AVAILABLE:
        # Fallback: simple token overlap
        ta = set(_normalise_street(a).split())
        tb = set(_normalise_street(b).split())
        if not ta or not tb:
            return 0
        overlap = len(ta & tb) / len(ta | tb)
        return int(overlap * 100)
    return fuzz.token_sort_ratio(
        _normalise_street(a), _normalise_street(b)
    )


# ── Cross-source matching ─────────────────────────────────────────────────────

def cross_reference(
    bidnow_listings: List[Dict],
    llt_listings: List[Dict],
    fuzzy_threshold: int = 85,
) -> List[Dict]:
    """
    Attempt to match each BidNow listing to a LelongTips listing.
    When matched, merge LLT auction_count and past_history into the BN record.

    Matching strategy (in priority order):
      1. Exact postcode + fuzzy street ≥ threshold
      2. No match → keep BidNow record as-is, llt_slug = None

    Returns the enriched BidNow listing list.
    """
    # Build LLT lookup keyed by postcode
    llt_by_postcode: Dict[str, List[Dict]] = {}
    for llt in llt_listings:
        pc = _extract_postcode(llt.get("address", ""))
        if pc:
            llt_by_postcode.setdefault(pc, []).append(llt)

    matched = 0
    for bn in bidnow_listings:
        pc = _extract_postcode(bn.get("full_address", ""))
        candidates = llt_by_postcode.get(pc, [])

        best_score = 0
        best_llt: Optional[Dict] = None
        for llt in candidates:
            score = _street_similarity(
                bn.get("full_address", ""), llt.get("address", "")
            )
            if score > best_score:
                best_score = score
                best_llt = llt

        if best_llt and best_score >= fuzzy_threshold:
            bn["llt_slug"] = best_llt.get("llt_slug", "")
            bn["llt_url"] = best_llt.get("llt_url", "")
            bn["llt_match_score"] = best_score
            # Merge LLT auction count if higher than BN's
            llt_count = best_llt.get("auction_count", 1)
            if llt_count > bn.get("auction_count", 1):
                bn["auction_count"] = llt_count
            # Carry over LLT past history for auction_history enrichment
            if best_llt.get("past_price") and best_llt.get("past_date"):
                bn.setdefault("llt_past_history", []).append({
                    "reserve_price": best_llt["past_price"],
                    "date_text": best_llt["past_date"],
                })
            matched += 1
        else:
            bn.setdefault("llt_slug", "")
            bn.setdefault("llt_url", "")
            bn.setdefault("llt_match_score", 0)

    print(f"  [merge] {matched}/{len(bidnow_listings)} BidNow listings matched to LelongTips")
    return bidnow_listings


# ── Re-auction detection ──────────────────────────────────────────────────────

def detect_reauction(
    listing: Dict,
    vault_index: Dict[str, Dict],
    fuzzy_threshold: int = 90,
) -> Tuple[str, Optional[Dict]]:
    """
    Determine whether a listing is new, an update, or a re-auction.

    Args:
        listing:     Merged BidNow+LLT dict
        vault_index: Dict keyed by "{postcode}:{normalised_street}" → existing vault record
                     Built by md_writer from existing Property notes.

    Returns:
        (action, existing_record)
        action one of: "create" | "update_price" | "new_round"
    """
    pc = _extract_postcode(listing.get("full_address", ""))
    street = _normalise_street(listing.get("full_address", ""))
    key = f"{pc}:{street}"

    # Exact key match
    if key in vault_index:
        existing = vault_index[key]
        ex_date = existing.get("auction_date", "")
        new_date = listing.get("auction_date", "")
        if ex_date == new_date:
            return "update_price", existing
        else:
            return "new_round", existing

    # Fuzzy match within same postcode
    pc_candidates = {k: v for k, v in vault_index.items() if k.startswith(f"{pc}:")}
    for vkey, existing in pc_candidates.items():
        ex_street = vkey.split(":", 1)[1] if ":" in vkey else ""
        score = _street_similarity(street, ex_street)
        if score >= fuzzy_threshold:
            ex_date = existing.get("auction_date", "")
            new_date = listing.get("auction_date", "")
            if ex_date == new_date:
                return "update_price", existing
            else:
                return "new_round", existing

    return "create", None


# ── Derived field computation ─────────────────────────────────────────────────

def compute_derived_fields(listing: Dict, existing: Optional[Dict] = None) -> Dict:
    """
    Compute days_to_auction, region, original_reserve, total_price_drop,
    auction_history (merged), and tags.

    existing: the current vault record (for re-auction cases).
    """
    today = date.today()

    # days_to_auction
    auction_date_str = listing.get("auction_date", "")
    days_to_auction = 0
    if auction_date_str:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                ad = datetime.strptime(auction_date_str, fmt).date()
                days_to_auction = (ad - today).days
                break
            except ValueError:
                continue
    listing["days_to_auction"] = max(days_to_auction, 0)

    # region
    listing["region"] = STATE_TO_REGION.get(listing.get("state", ""), "")

    # auction_history — start from existing vault record if available
    if existing:
        history = list(existing.get("auction_history", []))
        # Append the existing vault's last known auction if not already in history
        ex_entry = {
            "auction_date": existing.get("auction_date", ""),
            "reserve_price": existing.get("reserve_price", 0),
        }
        if ex_entry not in history and ex_entry["auction_date"]:
            history.append(ex_entry)
    else:
        history = list(listing.get("auction_history", []))

    # Append LLT past history entries if present
    for llt_entry in listing.pop("llt_past_history", []):
        # Convert "Nov 2024" style dates to approximate YYYY-MM-DD
        converted = _parse_month_year(llt_entry.get("date_text", ""))
        mapped = {
            "auction_date": converted,
            "reserve_price": llt_entry.get("reserve_price", 0),
        }
        if mapped not in history and converted:
            history.append(mapped)

    # Sort chronologically
    history.sort(key=lambda x: x.get("auction_date", ""))
    listing["auction_history"] = history

    # original_reserve = first entry price (or current if no history)
    if history:
        listing["original_reserve"] = history[0].get("reserve_price", listing.get("reserve_price", 0))
    else:
        listing["original_reserve"] = listing.get("reserve_price", 0)

    # total_price_drop
    listing["total_price_drop"] = max(
        listing["original_reserve"] - listing.get("reserve_price", 0), 0
    )

    # auction_count from history length (floor at 1)
    listing["auction_count"] = max(len(history), listing.get("auction_count", 1), 1)

    # tags
    tags = _build_tags(listing)
    listing["tags"] = tags

    return listing


def _parse_month_year(text: str) -> str:
    """Convert 'Nov 2024' → '2024-11-01'."""
    months = {
        "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
        "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
        "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
    }
    m = re.search(r"(\w{3})\s+(\d{4})", text)
    if m:
        month_num = months.get(m.group(1).capitalize(), "01")
        return f"{m.group(2)}-{month_num}-01"
    return ""


def _build_tags(listing: Dict) -> List[str]:
    tags: List[str] = []

    state = listing.get("state", "").lower().replace(" ", "-")
    if state:
        tags.append(state)

    district = listing.get("district", "").lower().replace(" ", "-")
    if district:
        tags.append(district)

    ptype = listing.get("property_type", "")
    if ptype:
        tags.append(ptype)

    if listing.get("auction_count", 1) > 1:
        tags.append("reauction")

    if listing.get("total_price_drop", 0) > 0:
        tags.append("price-dropped")

    if listing.get("bmv_percent", 0) >= 30:
        tags.append("high-bmv")

    if listing.get("auction_type", "") == "LACA":
        tags.append("laca")
    elif listing.get("auction_type", "") == "Non-LACA":
        tags.append("non-laca")

    tags.append("active")
    return list(dict.fromkeys(tags))  # preserve order, remove duplicates
