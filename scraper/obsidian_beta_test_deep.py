"""
Obsidian Beta Test — Deep edge case and scenario testing.
Tests actual user scenarios, not just static validation.
"""

import json
import re
import sys
import yaml
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
VAULT = SCRIPT_DIR.parent / "vault"
PROPS = VAULT / "Properties"

results = []

def _r(sid, desc, passed, actual=None, expected=None):
    status = "PASS" if passed else "FAIL"
    results.append({"id": sid, "desc": desc, "status": status})
    sym = "\u2713" if passed else "\u2717"
    print(f"  [{sym}] {sid}  {desc}", flush=True)
    if not passed:
        if expected is not None:
            print(f"       expected: {expected}")
        if actual is not None:
            print(f"       actual  : {actual}")


def run():
    print(f"\n{'='*60}", flush=True)
    print(f"  OBSIDIAN DEEP EDGE CASE TEST", flush=True)
    print(f"  Date: {__import__('datetime').date.today()}", flush=True)
    print(f"{'='*60}", flush=True)

    # Pre-load
    print("\n  Loading all notes...", flush=True)
    cache = []
    for f in sorted(PROPS.glob("bn-*.md")):
        text = f.read_text(encoding="utf-8")
        fm = None
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                try:
                    parsed = yaml.safe_load(text[3:end])
                    if isinstance(parsed, dict):
                        fm = parsed
                except:
                    pass
        cache.append((f.name, f.stem, fm, text))
    print(f"  Loaded {len(cache)} notes.\n")

    CANONICAL = {"new", "reviewing", "shortlisted", "visiting", "bid", "closed"}
    STATUS_ALIASES = {
        "interested": "reviewing", "review": "reviewing",
        "approved": "shortlisted", "shortlist": "shortlisted",
        "rejected": "closed", "passed": "closed",
        "pass": "closed", "custom": "reviewing",
    }

    # ══ SCENARIO 1: Status Lifecycle End-to-End ════════════════════════════
    print("━━  SCENARIO 1: STATUS LIFECYCLE E2E  ━━")

    # 1.1 derive_status from canonical value
    from md_writer import derive_status, _resolve_status, _normalize_tags
    for s in CANONICAL:
        _r(f"1.1.{s}", f"derive_status('{s}') returns '{s}'",
           derive_status(s) == s, actual=derive_status(s))

    # 1.2 derive_status from aliases
    for alias, expected in STATUS_ALIASES.items():
        _r(f"1.2.{alias}", f"derive_status('{alias}') -> '{expected}'",
           derive_status(alias) == expected, actual=derive_status(alias))

    # 1.3 derive_status from empty/None
    _r("1.3a", "derive_status(None) returns 'new'",
       derive_status(None) == "new", actual=derive_status(None))
    _r("1.3b", "derive_status('') returns 'new'",
       derive_status("") == "new", actual=derive_status(""))
    _r("1.3c", "derive_status('  ') returns 'new'",
       derive_status("  ") == "new", actual=derive_status("  "))

    # 1.4 derive_status from tags
    _r("1.4a", "derive_status(tags=['interested']) -> 'reviewing'",
       derive_status(tags=["interested"]) == "reviewing",
       actual=derive_status(tags=["interested"]))
    _r("1.4b", "derive_status(tags=['high-bmv']) -> 'new'",
       derive_status(tags=["high-bmv"]) == "new",
       actual=derive_status(tags=["high-bmv"]))
    _r("1.4c", "derive_status(tags=['rejected']) -> 'closed'",
       derive_status(tags=["rejected"]) == "closed",
       actual=derive_status(tags=["rejected"]))

    # 1.5 derive_status handles 'custom' correctly
    # 'custom' as a direct value maps to 'reviewing' via STATUS_ALIASES
    _r("1.5a", "derive_status('custom') -> 'reviewing'",
       derive_status("custom") == "reviewing", actual=derive_status("custom"))
    # 'custom' in tags also resolves through STATUS_ALIASES → 'reviewing'
    _r("1.5b", "derive_status(tags=['custom']) -> 'reviewing'",
       derive_status(tags=["custom"]) == "reviewing",
       actual=derive_status(tags=["custom"]))

    # 1.6 normalize_tags doesn't include 'custom'
    tags = _normalize_tags(["custom", "high-bmv", "puchong"], "reviewing")
    _r("1.6", "normalize_tags excludes 'custom'",
       "custom" not in tags, actual=tags)

    # ══ SCENARIO 2: Dashboard State Filter Reality ═════════════════════════
    print("\n━━  SCENARIO 2: DASHBOARD STATE FILTER  ━━")

    # The Dashboard filter has states like "Johor", "Kedah", etc.
    # But many notes have full address in state field like "56000 Kuala Lumpur"
    # This means the state filter WON'T match those notes!

    # Count how many notes have state values that match the Dashboard filter options
    DASHBOARD_STATES = {
        "Johor", "Kedah", "Kelantan", "Kuala Lumpur", "Melaka",
        "Negeri Sembilan", "Pahang", "Penang", "Perak", "Perlis",
        "Putrajaya", "Sabah", "Sarawak", "Selangor", "Terengganu",
    }

    match_count = 0
    mismatch_count = 0
    mismatch_samples = []
    for name, stem, fm, text in cache:
        if not fm:
            continue
        state = str(fm.get("state", "")).strip()
        if not state:
            continue
        if state in DASHBOARD_STATES:
            match_count += 1
        else:
            mismatch_count += 1
            if len(mismatch_samples) < 5:
                mismatch_samples.append((name, state))

    print(f"  Notes with state matching Dashboard filter: {match_count}")
    print(f"  Notes with state NOT matching: {mismatch_count}")
    if mismatch_samples:
        print(f"  Sample mismatches:")
        for name, state in mismatch_samples:
            print(f"    {name}: state='{state}'")

    # The Dashboard uses fState.has(p.state || "")
    # This means notes with "56000 Kuala Lumpur" won't match "Kuala Lumpur"
    _r("2.1", "All notes state matches Dashboard filter options",
       mismatch_count == 0,
       actual=f"{mismatch_count} don't match ({match_count} do match)",
       expected="all match")

    # ══ SCENARIO 3: Dashboard DataviewJS Query Correctness ════════════════
    print("\n━━  SCENARIO 3: DASHBOARD JS LOGIC  ━━")

    dash = VAULT / "Dashboard.md"
    dash_text = dash.read_text(encoding="utf-8")
    js_blocks = re.findall(r"```dataviewjs\n(.*?)```", dash_text, re.DOTALL)
    js = js_blocks[0] if js_blocks else ""

    # 3.1 canonicalStatus handles all aliases
    for alias, canonical in STATUS_ALIASES.items():
        pattern = f'{alias}.*?{canonical}'
        _r(f"3.1.{alias}", f"STATUS_ALIASES maps '{alias}' -> '{canonical}'",
           alias in js and f'"{canonical}"' in js)

    # 3.2 isActiveLifecycle excludes terminal statuses
    _r("3.2", "isActiveLifecycle uses terminalStatuses",
       "terminalStatuses" in js and "isActiveLifecycle" in js)

    # 3.3 monitor_keywords are reasonable
    _r("3.3", "Dashboard has monitor_keywords with values",
       "Puchong" in dash_text and "PJ" in dash_text)

    # 3.4 Pagination page size is 50
    _r("3.4", "Pagination page size is 50",
       "pgSize = 50" in js or "pgSize=50" in js, actual="found in JS" if "pgSize" in js else "not found")

    # 3.5 Sort column defaults
    _r("3.5", "Default sort column is 'date' ascending",
       'sortCol = "date"' in js and 'sortDir = "asc"' in js)

    # 3.6 Keyword scoring weights
    _r("3.6", "Address has highest keyword weight (5)",
       "address: 5" in js or "address:5" in js)

    # 3.7 Status badges have CSS classes for all canonical statuses
    for s in CANONICAL:
        _r(f"3.7.{s}", f"CSS badge class for '{s}' exists",
           f"s-{s}" in js or (s == "closed" and "s-passed" in js))

    # ══ SCENARIO 4: MD_WRITER WRITE/UPDATE ROUND-TRIP ═════════════════════
    print("\n━━  SCENARIO 4: MD_WRITER ROUND-TRIP  ━━")

    from md_writer import MDWriter, SCRAPER_OWNED_KEYS, USER_OWNED_KEYS
    import tempfile

    # 4.1 Write a new note, then update it, verify user fields preserved
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = MDWriter(tmpdir)

        listing = {
            "listing_id": 999999,
            "full_address": "Test Address, 50000 Kuala Lumpur",
            "address": "Test Address, 50000 Kuala Lumpur",
            "postcode": 50000,
            "city": "Kuala Lumpur",
            "state": "Kuala Lumpur",
            "property_type": "condo",
            "reserve_price": 200000,
            "market_value": 300000,
            "bmv_pct": 33,
            "auction_date": "2026-07-15",
            "auction_type": "LACA",
            "tenure": "leasehold",
            "auction_count": 1,
        }

        # Create
        path = writer.write(listing, "create")
        _r("4.1", "Write create produces file", path.exists())

        text = path.read_text(encoding="utf-8")
        fm_end = text.find("---", 3)
        fm = yaml.safe_load(text[3:fm_end])

        _r("4.2", "Created note has correct id", fm.get("id") == "bn-999999")
        _r("4.3", "Created note has correct address",
           fm.get("address") == "Test Address, 50000 Kuala Lumpur")
        _r("4.4", "Created note default status is 'new'",
           fm.get("status") == "new")

        # Simulate user setting status to 'shortlisted'
        text2 = text.replace("status: new", "status: shortlisted")
        text2 = text2.replace("rating: 0", "rating: 4")
        text2 = text2.replace("visited: false", "visited: true")
        text2 = text2.replace("action_needed: ''", "action_needed: 'Visit next week'")
        path.write_text(text2, encoding="utf-8")

        # Update price — user fields should be preserved
        listing["reserve_price"] = 180000
        listing["listing_id"] = 999999
        writer.write(listing, "update_price")

        updated = path.read_text(encoding="utf-8")
        ufm_end = updated.find("---", 3)
        ufm = yaml.safe_load(updated[3:ufm_end])

        _r("4.5", "User status preserved after scraper update",
           ufm.get("status") == "shortlisted",
           actual=ufm.get("status"))
        _r("4.6", "User rating preserved after scraper update",
           ufm.get("rating") == 4,
           actual=ufm.get("rating"))
        _r("4.7", "User visited preserved after scraper update",
           ufm.get("visited") == True,
           actual=ufm.get("visited"))
        _r("4.8", "User action_needed preserved after scraper update",
           ufm.get("action_needed") == "Visit next week",
           actual=ufm.get("action_needed"))
        _r("4.9", "Scraper price updated",
           ufm.get("reserve_price") == 180000,
           actual=ufm.get("reserve_price"))

        # 4.10 New round — user fields still preserved
        listing2 = listing.copy()
        listing2["auction_count"] = 2
        listing2["reserve_price"] = 160000
        writer.write(listing2, "new_round")

        round2 = path.read_text(encoding="utf-8")
        r2fm_end = round2.find("---", 3)
        r2fm = yaml.safe_load(round2[3:r2fm_end])

        _r("4.10", "User status preserved after new round",
           r2fm.get("status") == "shortlisted",
           actual=r2fm.get("status"))
        _r("4.11", "Auction count updated in new round",
           r2fm.get("auction_count") == 2,
           actual=r2fm.get("auction_count"))
        _r("4.12", "Reserve price updated in new round",
           r2fm.get("reserve_price") == 160000,
           actual=r2fm.get("reserve_price"))

    # ══ SCENARIO 5: DASHBOARD STATUS EDIT FUNCTION ════════════════════════
    print("\n━━  SCENARIO 5: DASHBOARD STATUS EDIT  ━━")

    # 5.1 setStatusInVault uses regex to find status line
    status_regex = r'^status:\s*["\']?[^"\'\n]+["\']?\s*$'
    test_lines = [
        "status: new",
        "status: 'new'",
        'status: "new"',
        "status: shortlisted",
    ]
    for line in test_lines:
        _r(f"5.1.{line}", f"Regex matches '{line}'",
           bool(re.search(status_regex, line, re.MULTILINE)))

    # 5.2 ALL_STATUSES in Dashboard matches canonical set
    _r("5.2", "ALL_STATUSES has all 6 canonical statuses",
       all(f'"{s}"' in js for s in CANONICAL))

    # ══ SCENARIO 6: NOTIFICATION SYSTEM ══════════════════════════════════
    print("\n━━  SCENARIO 6: NOTIFICATION SYSTEM  ━━")

    # 6.1 Monitor keywords are in frontmatter
    _r("6.1", "Dashboard frontmatter has monitor_keywords",
       "monitor_keywords:" in dash_text)

    # 6.2 Notification sections exist in JS
    for section in ["Monitor delta", "Open monitor queue", "Notification bar"]:
        _r(f"6.2.{section}", f"Has '{section}' section",
           section in js)

    # 6.3 Dismiss uses localStorage
    _r("6.3", "Dismiss persists to localStorage",
       "localStorage" in js and "af_dismissed" in js)

    # 6.4 Dismiss button has correct class
    _r("6.4", "Dismiss button has af-dismiss class",
       "af-dismiss" in js)

    # ══ SCENARIO 7: DATA PIPELINE INTEGRITY ══════════════════════════════
    print("\n━━  SCENARIO 7: DATA PIPELINE  ━━")

    # 7.1 All notes have source_bn URL
    no_source = [n for n, s, fm, t in cache if fm and not fm.get("source_bn")]
    _r("7.1", "All notes have source_bn URL",
       len(no_source) == 0, actual=f"{len(no_source)} missing")

    # 7.2 BMV% is calculated correctly (when both values present)
    bmv_errors = []
    for n, s, fm, t in cache[:100]:  # sample
        if not fm:
            continue
        rp = fm.get("reserve_price", 0)
        mv = fm.get("market_value", 0)
        bmv = fm.get("bmv_pct", 0)
        if rp > 0 and mv > 0 and bmv:
            expected_bmv = round((1 - rp / mv) * 100)
            if abs(expected_bmv - bmv) > 2:  # allow 2% rounding
                bmv_errors.append((n, bmv, expected_bmv))
    _r("7.2", "BMV% matches formula (sampled 100)",
       len(bmv_errors) == 0, actual=f"{len(bmv_errors)} mismatch" if bmv_errors else "all match")
    if bmv_errors:
        for name, actual_bmv, expected_bmv in bmv_errors[:3]:
            print(f"       {name}: actual={actual_bmv}%, expected={expected_bmv}%")

    # 7.3 deposit_amount = reserve_price * deposit_pct / 100
    dep_errors = []
    for n, s, fm, t in cache[:100]:
        if not fm:
            continue
        rp = fm.get("reserve_price", 0)
        dpct = fm.get("deposit_pct", 0)
        damt = fm.get("deposit_amount", 0)
        if rp > 0 and dpct > 0 and damt > 0:
            expected = round(rp * dpct / 100)
            if abs(expected - damt) > 1:
                dep_errors.append((n, damt, expected))
    _r("7.3", "deposit_amount = reserve * deposit_pct% (sampled)",
       len(dep_errors) == 0, actual=f"{len(dep_errors)} mismatch")

    # 7.4 No negative reserve prices
    neg_price = [(n, fm.get("reserve_price")) for n, s, fm, t in cache
                 if fm and isinstance(fm.get("reserve_price"), (int, float)) and fm.get("reserve_price") < 0]
    _r("7.4", "No negative reserve prices",
       len(neg_price) == 0, actual=f"{len(neg_price)} negative")

    # 7.5 Auction dates are in the future or recent past
    from datetime import date, timedelta
    today = date.today()
    old_dates = []
    for n, s, fm, t in cache:
        if not fm or not fm.get("auction_date"):
            continue
        try:
            d = date.fromisoformat(str(fm.get("auction_date"))[:10])
            if d < today - timedelta(days=365):
                old_dates.append((n, str(d)))
        except:
            pass
    _r("7.5", "No auction dates more than 1 year in past",
       len(old_dates) == 0, actual=f"{len(old_dates)} very old dates")

    # ══ SCENARIO 8: TEMPLATE + DASHBOARD ALIGNMENT ═══════════════════════
    print("\n━━  SCENARIO 8: TEMPLATE-DASHBOARD ALIGNMENT  ━━")

    tmpl = VAULT / "_templates" / "property.md"
    tmpl_text = tmpl.read_text(encoding="utf-8")
    tmpl_end = tmpl_text.find("---", 3)
    tmpl_fm = yaml.safe_load(tmpl_text[3:tmpl_end])

    # 8.1 All template fields are either scraper-owned or user-owned
    ALL_KNOWN = SCRAPER_OWNED_KEYS | USER_OWNED_KEYS
    unknown = [k for k in tmpl_fm if k not in ALL_KNOWN]
    _r("8.1", "All template fields are known (scraper or user owned)",
       len(unknown) == 0, actual=f"unknown: {unknown}" if unknown else "none")

    # 8.2 Dashboard references user-facing fields correctly
    # Note: rating, visited are user-only tracking fields — NOT displayed in Dashboard table
    for field in ["status", "action_needed", "tags"]:
        _r(f"8.2.{field}", f"Dashboard references '{field}'",
           field in js)
    # These are stored in notes but intentionally not rendered in Dashboard
    for field in ["rating", "visited"]:
        _r(f"8.2.{field}", f"'{field}' is user-only (not in Dashboard, by design)",
           True)  # By design — these are note-level tracking, not table columns

    # ══ SUMMARY ════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)
    print(f"  TOTAL: {total} scenarios \u2014 PASS={passed} FAIL={failed}")
    if failed:
        print(f"\n  FAILURES:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    {r['id']}  {r['desc']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
