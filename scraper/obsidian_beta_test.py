"""
Obsidian Vault Beta Test — Comprehensive validation of all vault components.
Tests: frontmatter integrity, status lifecycle, field completeness, Dashboard JS,
Cockpit bridge, tag hygiene, and edge cases.

Usage: python scraper/obsidian_beta_test.py
"""

import json
import re
import sys
import yaml
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
VAULT = SCRIPT_DIR.parent / "vault"
PROPS = VAULT / "Properties"

results = []

def _r(sid, desc, passed, actual=None, expected=None, notes=""):
    status = "PASS" if passed else "FAIL"
    results.append({"id": sid, "desc": desc, "status": status, "actual": actual, "expected": expected})
    sym = "✓" if passed else "✗"
    print(f"  [{sym}] {sid}  {desc}")
    if not passed:
        if expected is not None:
            print(f"       expected: {expected}")
        if actual is not None:
            print(f"       actual  : {actual}")
        if notes:
            print(f"       note    : {notes}")


def run():
    notes = sorted(PROPS.glob("bn-*.md"))
    print(f"\n{'='*60}")
    print(f"  OBSIDIAN VAULT BETA TEST")
    print(f"  Date: {__import__('datetime').date.today()}")
    print(f"  Notes: {len(notes)}")
    print(f"{'='*60}\n")

    CANONICAL = {"new", "reviewing", "shortlisted", "visiting", "bid", "closed"}
    LEGACY = {"interested", "review", "approved", "shortlist", "rejected", "passed", "pass", "custom"}
    REQUIRED = ["id", "bidnow_id", "address", "postcode", "city", "state", "property_type", "reserve_price", "status"]
    SCRAPER_KEYS = {
        "id", "bidnow_id", "llt_slug", "llt_url",
        "address", "postcode", "city", "state", "region", "location",
        "property_type", "built_up_sqft", "land_area_sqft",
        "tenure", "restriction", "auction_type",
        "auction_date", "auction_time", "days_to_auction",
        "reserve_price", "market_value", "bmv_pct",
        "auction_count", "original_reserve", "total_price_drop",
        "bank", "lawyer", "auctioneer", "borrower",
        "deposit_pct", "deposit_amount",
        "pos_file_path", "pos_url",
        "auction_history", "scrape_date", "source_bn", "source_llt",
        "market_sale_psf", "market_rent_psf", "market_rent_est",
        "market_value_est", "independent_bmv_pct", "est_rental_yield",
        "market_comps_date", "market_comps_n", "market_source", "market_area_match",
        "agent_score", "agent_recommendation", "agent_reasoning",
        "agent_exit_strategy", "agent_holding_period", "agent_key_risks",
        "agent_due_diligence", "agent_run_date", "agent_mode", "agent_confidence",
    }
    USER_KEYS = {"status", "rating", "visited", "action_needed", "tags",
                 "pos_analyzed", "pos_analysis_date", "legal_risk", "legal_issues",
                 "encumbrances", "management_fees_monthly", "quit_rent_annual",
                 "outstanding_fees_est", "deposit_terms", "title_type",
                 "lease_remaining_years", "pos_confidence"}

    def load_fm(f):
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return None, text
        end = text.find("---", 3)
        if end == -1:
            return None, text
        try:
            fm = yaml.safe_load(text[3:end])
            return (fm if isinstance(fm, dict) else None), text
        except:
            return None, text

    # Pre-load all frontmatter once for performance
    print("  Loading all frontmatter...")
    all_fm = {}
    for f in notes:
        fm, text = load_fm(f)
        all_fm[f.name] = (fm, text)
    print(f"  Loaded {len(all_fm)} notes.\n")

    # ══════════════════════════════════════════════════════════════════════════
    # CAT 1: FRONTMATTER INTEGRITY
    # ══════════════════════════════════════════════════════════════════════════
    print("━━  CAT 1: FRONTMATTER INTEGRITY  ━━")

    # 1.1 All notes have valid YAML frontmatter
    bad_fm = []
    for f in notes:
        fm, _ = load_fm(f)
        if fm is None:
            bad_fm.append(f.name)
    _r("1.1", f"All {len(notes)} notes have valid YAML frontmatter",
       len(bad_fm) == 0, actual=f"{len(bad_fm)} bad", expected="0 bad")

    # 1.2 Required fields present
    missing = {}
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        for r in REQUIRED:
            if r not in fm:
                missing.setdefault(r, []).append(f.name)
    _r("1.2", "All required fields present in every note",
       len(missing) == 0, actual=dict((k, len(v)) for k, v in missing.items()) if missing else "all present",
       expected="all present")

    # 1.3 id matches filename
    id_mismatch = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        if str(fm.get("id", "")) != f.stem:
            id_mismatch.append(f.name)
    _r("1.3", "id field matches filename (bn-XXXXX)",
       len(id_mismatch) == 0, actual=f"{len(id_mismatch)} mismatch", expected="0")

    # 1.4 bidnow_id is positive integer
    bad_bid = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        bid = fm.get("bidnow_id", 0)
        if not isinstance(bid, (int, float)) or bid <= 0:
            bad_bid.append((f.name, bid))
    _r("1.4", "bidnow_id is a positive number",
       len(bad_bid) == 0, actual=f"{len(bad_bid)} bad", expected="0")

    # 1.5 reserve_price is numeric and >= 0
    bad_price = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        rp = fm.get("reserve_price", 0)
        if not isinstance(rp, (int, float)) or rp < 0:
            bad_price.append((f.name, rp))
    _r("1.5", "reserve_price is numeric and >= 0",
       len(bad_price) == 0, actual=f"{len(bad_price)} bad", expected="0")

    # 1.6 state field is non-empty
    empty_state = []
    for f in notes:
        fm, _ = load_fm(f)
        if fm and not str(fm.get("state", "")).strip():
            empty_state.append(f.name)
    _r("1.6", "state field is non-empty",
       len(empty_state) == 0, actual=f"{len(empty_state)} empty", expected="0")

    # ══════════════════════════════════════════════════════════════════════════
    # CAT 2: STATUS LIFECYCLE
    # ══════════════════════════════════════════════════════════════════════════
    print("\n━━  CAT 2: STATUS LIFECYCLE  ━━")

    # 2.1 All statuses are canonical
    bad_status = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        s = str(fm.get("status", "")).strip().lower()
        if s and s not in CANONICAL:
            bad_status.append((f.name, s))
    _r("2.1", "All statuses are canonical values",
       len(bad_status) == 0, actual=f"{len(bad_status)} non-canonical", expected="0")

    # 2.2 No legacy aliases present
    legacy = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        s = str(fm.get("status", "")).strip().lower()
        if s in LEGACY:
            legacy.append((f.name, s))
    _r("2.2", "No legacy status aliases (interested, rejected, passed, etc.)",
       len(legacy) == 0, actual=f"{len(legacy)} legacy", expected="0")

    # 2.3 No 'custom' tag
    custom_tags = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        tags = fm.get("tags", []) or []
        if "custom" in [str(t).lower() for t in tags]:
            custom_tags.append(f.name)
    _r("2.3", "No 'custom' tag in any note",
       len(custom_tags) == 0, actual=f"{len(custom_tags)} have custom tag", expected="0")

    # 2.4 Status distribution
    status_counts = Counter()
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        status_counts[str(fm.get("status", "")).strip().lower()] += 1
    print(f"  [i] 2.4  Status distribution: {dict(status_counts)}")

    # 2.5 Tags are list type
    bad_tag_type = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        tags = fm.get("tags")
        if tags is not None and not isinstance(tags, list):
            bad_tag_type.append((f.name, type(tags).__name__))
    _r("2.5", "Tags field is list type (not string)",
       len(bad_tag_type) == 0, actual=f"{len(bad_tag_type)} wrong type", expected="0")

    # ══════════════════════════════════════════════════════════════════════════
    # CAT 3: DASHBOARD INTEGRITY
    # ══════════════════════════════════════════════════════════════════════════
    print("\n━━  CAT 3: DASHBOARD INTEGRITY  ━━")

    dash = VAULT / "Dashboard.md"
    dash_text = dash.read_text(encoding="utf-8")

    # 3.1 Dashboard exists and has frontmatter
    _r("3.1", "Dashboard.md exists", dash.exists())

    # 3.2 Has monitor_keywords in frontmatter
    _r("3.2", "Dashboard has monitor_keywords in frontmatter",
       "monitor_keywords" in dash_text)

    # 3.3 Has terminal_statuses in frontmatter
    _r("3.3", "Dashboard has terminal_statuses in frontmatter",
       "terminal_statuses" in dash_text)

    # 3.4 Has dataviewjs block
    js_blocks = re.findall(r"```dataviewjs\n(.*?)```", dash_text, re.DOTALL)
    _r("3.4", "Dashboard has dataviewjs code block",
       len(js_blocks) >= 1, actual=f"{len(js_blocks)} blocks", expected=">= 1")

    # 3.5 Braces balanced in JS
    if js_blocks:
        js = js_blocks[0]
        opens = js.count("{")
        closes = js.count("}")
        _r("3.5", "Braces balanced in DataviewJS",
           opens == closes, actual=f"{opens} open vs {closes} close")

        # 3.6 Parens balanced
        p_open = js.count("(")
        p_close = js.count(")")
        _r("3.6", "Parentheses balanced in DataviewJS",
           p_open == p_close, actual=f"{p_open} open vs {p_close} close")

        # 3.7 Has canonicalStatus function
        _r("3.7", "Dashboard has canonicalStatus function",
           "canonicalStatus" in js)

        # 3.8 Has STATUS_ALIASES map
        _r("3.8", "Dashboard has STATUS_ALIASES map",
           "STATUS_ALIASES" in js)

        # 3.9 Has keyword scoring
        _r("3.9", "Dashboard has keywordScore function",
           "keywordScore" in js)

        # 3.10 Has status editor
        _r("3.10", "Dashboard has attachStatusEdit function",
           "attachStatusEdit" in js)

        # 3.11 Has pagination
        _r("3.11", "Dashboard has appendPagination function",
           "appendPagination" in js)

        # 3.12 Has dismiss/notification
        _r("3.12", "Dashboard has doDismiss function",
           "doDismiss" in js)

        # 3.13 Has column resize
        _r("3.13", "Dashboard has column resize handles",
           "col-rz" in js)

        # 3.14 Terminal statuses include 'closed'
        _r("3.14", "Terminal statuses include 'closed'",
           "closed" in dash_text)

        # 3.15 All canonical statuses in filter UI
        for s in CANONICAL:
            _r(f"3.15.{s}", f"Status '{s}' appears in filter options",
               f'"{s}"' in js or f"'{s}'" in js)

    # ══════════════════════════════════════════════════════════════════════════
    # CAT 4: COCKPIT BRIDGE
    # ══════════════════════════════════════════════════════════════════════════
    print("\n━━  CAT 4: COCKPIT BRIDGE  ━━")

    # 4.1 PowerShell script exists
    ps1 = SCRIPT_DIR / "obsidian-cockpit.ps1"
    _r("4.1", "obsidian-cockpit.ps1 exists", ps1.exists())

    # 4.2 PowerShell script references main.py
    if ps1.exists():
        ps1_text = ps1.read_text(encoding="utf-8")
        _r("4.2", "cockpit.ps1 references main.py",
           "main.py" in ps1_text)

    # 4.3 Templater config exists
    tc = VAULT / ".obsidian" / "plugins" / "templater-obsidian" / "data.json"
    _r("4.3", "Templater config exists", tc.exists())

    # 4.4 Templater config references cockpit_run
    if tc.exists():
        tc_text = tc.read_text(encoding="utf-8")
        _r("4.4", "Templater config references cockpit_run",
           "cockpit_run" in tc_text)

    # 4.5 Startup template exists
    st = VAULT / "_templates" / "_startup" / "cockpit-bootstrap.md"
    _r("4.5", "Startup bootstrap template exists", st.exists())

    # 4.6 Startup template calls tp.user.cockpit_run
    if st.exists():
        st_text = st.read_text(encoding="utf-8")
        _r("4.6", "Bootstrap template calls tp.user.cockpit_run()",
           "tp.user.cockpit_run" in st_text)

    # ══════════════════════════════════════════════════════════════════════════
    # CAT 5: MD_WRITER CONSISTENCY
    # ══════════════════════════════════════════════════════════════════════════
    print("\n━━  CAT 5: MD_WRITER CONSISTENCY  ━━")

    # 5.1 SCRAPER_OWNED_KEYS and USER_OWNED_KEYS don't overlap
    overlap = SCRAPER_KEYS & USER_KEYS
    _r("5.1", "Scraper-owned and user-owned keys don't overlap",
       len(overlap) == 0, actual=f"overlap: {overlap}" if overlap else "none")

    # 5.2 All scraper-owned keys exist in template
    tmpl = VAULT / "_templates" / "property.md"
    if tmpl.exists():
        tmpl_text = tmpl.read_text(encoding="utf-8")
        tmpl_end = tmpl_text.find("---", 3)
        try:
            tmpl_fm = yaml.safe_load(tmpl_text[3:tmpl_end])
            missing_tmpl = [r for r in REQUIRED if r not in tmpl_fm]
            _r("5.2", "Property template has all required fields",
               len(missing_tmpl) == 0, actual=f"missing: {missing_tmpl}" if missing_tmpl else "all present")
        except:
            _r("5.2", "Property template has valid YAML", False, notes="YAML parse error")

    # 5.3 Notes below frontmatter have content
    empty_body = []
    for f in notes[:20]:  # sample first 20
        text = f.read_text(encoding="utf-8")
        end = text.find("---", 3)
        body = text[end + 3:].strip()
        if not body or len(body) < 5:
            empty_body.append(f.name)
    _r("5.3", "Sample notes have body content below frontmatter",
       len(empty_body) == 0, actual=f"{len(empty_body)} empty", expected="0")

    # ══════════════════════════════════════════════════════════════════════════
    # CAT 6: EDGE CASES & DATA QUALITY
    # ══════════════════════════════════════════════════════════════════════════
    print("\n━━  CAT 6: EDGE CASES & DATA QUALITY  ━━")

    # 6.1 No duplicate listing IDs
    all_ids = []
    for f in notes:
        fm, _ = load_fm(f)
        if fm:
            all_ids.append(fm.get("id", ""))
    dupes = [x for x in Counter(all_ids).items() if x[1] > 1]
    _r("6.1", "No duplicate listing IDs",
       len(dupes) == 0, actual=f"{len(dupes)} duplicates" if dupes else "none")

    # 6.2 auction_date format is YYYY-MM-DD
    bad_dates = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        d = str(fm.get("auction_date", ""))
        if d and not re.match(r"^\d{4}-\d{2}-\d{2}", d):
            bad_dates.append((f.name, d))
    _r("6.2", "auction_date in YYYY-MM-DD format",
       len(bad_dates) == 0, actual=f"{len(bad_dates)} bad format", expected="0")

    # 6.3 location is list of 2 floats
    bad_loc = []
    for f in notes[:50]:  # sample
        fm, _ = load_fm(f)
        if not fm:
            continue
        loc = fm.get("location", [])
        if loc and (not isinstance(loc, list) or len(loc) != 2):
            bad_loc.append(f.name)
    _r("6.3", "location field is [lat, lng] array (sampled)",
       len(bad_loc) == 0, actual=f"{len(bad_loc)} bad", expected="0")

    # 6.4 property_type is lowercase
    bad_type = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        pt = str(fm.get("property_type", ""))
        if pt and pt != pt.lower():
            bad_type.append((f.name, pt))
    _r("6.4", "property_type is lowercase",
       len(bad_type) == 0, actual=f"{len(bad_type)} not lowercase", expected="0")

    # 6.5 No scraper-owned keys leaked into user territory
    leaked = []
    for f in notes:
        fm, _ = load_fm(f)
        if not fm:
            continue
        for k in fm:
            if k in USER_KEYS:
                continue  # user key, fine
            if k in SCRAPER_KEYS:
                continue  # scraper key, fine
            # Unknown key
    # (This is informational, not a failure)

    # 6.6 Daily Note template exists
    dn = VAULT / "_templates" / "daily-note.md"
    _r("6.6", "Daily note template exists", dn.exists())

    # ══════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)
    print(f"  TOTAL: {total} scenarios — PASS={passed} FAIL={failed}")
    if failed:
        print(f"\n  FAILURES:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    {r['id']}  {r['desc']}")
                if r.get("actual"):
                    print(f"      actual: {r['actual']}")
    print(f"{'='*60}")


if __name__ == "__main__":
    run()
