"""
Obsidian Vault Beta Test v2 — Comprehensive validation of all vault components.
Usage: python scraper/obsidian_beta_test_v2.py
"""

import json
import re
import yaml
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
VAULT = SCRIPT_DIR.parent / "vault"
PROPS = VAULT / "Properties"

results = []

def _r(sid, desc, passed, actual=None, expected=None):
    status = "PASS" if passed else "FAIL"
    results.append({"id": sid, "desc": desc, "status": status})
    sym = "\u2713" if passed else "\u2717"
    print(f"  [{sym}] {sid}  {desc}")
    if not passed:
        if expected is not None:
            print(f"       expected: {expected}")
        if actual is not None:
            print(f"       actual  : {actual}")

def run():
    notes = sorted(PROPS.glob("bn-*.md"))
    print(f"\n{'='*60}")
    print(f"  OBSIDIAN VAULT BETA TEST")
    print(f"  Date: {__import__('datetime').date.today()}")
    print(f"  Notes: {len(notes)}")
    print(f"{'='*60}")

    CANONICAL = {"new", "reviewing", "shortlisted", "visiting", "bid", "closed"}
    LEGACY = {"interested", "review", "approved", "shortlist", "rejected", "passed", "pass", "custom"}
    REQUIRED = ["id", "bidnow_id", "address", "postcode", "city", "state", "property_type", "reserve_price", "status"]

    # Pre-load all frontmatter
    print("\n  Loading all frontmatter...")
    cache = []
    for f in notes:
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

    # ══ CAT 1: FRONTMATTER INTEGRITY ════════════════════════════════════════
    print("━━  CAT 1: FRONTMATTER INTEGRITY  ━━")

    bad_fm = [n for n, s, fm, t in cache if fm is None]
    _r("1.1", "All notes have valid YAML frontmatter",
       len(bad_fm) == 0, actual=f"{len(bad_fm)} bad", expected="0")

    missing = {}
    for n, s, fm, t in cache:
        if not fm: continue
        for r in REQUIRED:
            if r not in fm:
                missing.setdefault(r, []).append(n)
    _r("1.2", "All required fields present",
       len(missing) == 0, actual={k: len(v) for k, v in missing.items()} if missing else "all present")

    id_mismatch = [(n, s) for n, s, fm, t in cache if fm and str(fm.get("id", "")) != s]
    _r("1.3", "id matches filename",
       len(id_mismatch) == 0, actual=f"{len(id_mismatch)} mismatch")

    bad_bid = [(n, fm.get("bidnow_id")) for n, s, fm, t in cache
               if fm and (not isinstance(fm.get("bidnow_id", 0), (int, float)) or fm.get("bidnow_id", 0) <= 0)]
    _r("1.4", "bidnow_id is positive number",
       len(bad_bid) == 0, actual=f"{len(bad_bid)} bad")

    bad_price = [(n, fm.get("reserve_price")) for n, s, fm, t in cache
                 if fm and (not isinstance(fm.get("reserve_price", 0), (int, float)) or fm.get("reserve_price", 0) < 0)]
    _r("1.5", "reserve_price >= 0",
       len(bad_price) == 0, actual=f"{len(bad_price)} bad")

    empty_state = [n for n, s, fm, t in cache if fm and not str(fm.get("state", "")).strip()]
    _r("1.6", "state field is non-empty",
       len(empty_state) == 0, actual=f"{len(empty_state)} empty")

    # ══ CAT 2: STATUS LIFECYCLE ═════════════════════════════════════════════
    print("\n━━  CAT 2: STATUS LIFECYCLE  ━━")

    bad_status = [(n, str(fm.get("status", ""))) for n, s, fm, t in cache
                  if fm and str(fm.get("status", "")).strip().lower() not in CANONICAL
                  and str(fm.get("status", "")).strip()]
    _r("2.1", "All statuses are canonical",
       len(bad_status) == 0, actual=f"{len(bad_status)} non-canonical")

    legacy = [(n, str(fm.get("status", ""))) for n, s, fm, t in cache
              if fm and str(fm.get("status", "")).strip().lower() in LEGACY]
    _r("2.2", "No legacy status aliases",
       len(legacy) == 0, actual=f"{len(legacy)} legacy")

    custom_tags = [n for n, s, fm, t in cache
                   if fm and "custom" in [str(x).lower() for x in (fm.get("tags", []) or [])]]
    _r("2.3", "No 'custom' tag",
       len(custom_tags) == 0, actual=f"{len(custom_tags)} have custom")

    status_counts = Counter(str(fm.get("status", "")).strip().lower() for n, s, fm, t in cache if fm)
    print(f"  [i] 2.4  Status distribution: {dict(status_counts)}")

    bad_tag_type = [(n, type(fm.get("tags")).__name__) for n, s, fm, t in cache
                    if fm and fm.get("tags") is not None and not isinstance(fm.get("tags"), list)]
    _r("2.5", "Tags field is list type",
       len(bad_tag_type) == 0, actual=f"{len(bad_tag_type)} wrong type")

    # ══ CAT 3: DASHBOARD INTEGRITY ═════════════════════════════════════════
    print("\n━━  CAT 3: DASHBOARD INTEGRITY  ━━")

    dash = VAULT / "Dashboard.md"
    dash_text = dash.read_text(encoding="utf-8")

    _r("3.1", "Dashboard.md exists", dash.exists())
    _r("3.2", "Has monitor_keywords in frontmatter", "monitor_keywords" in dash_text)
    _r("3.3", "Has terminal_statuses in frontmatter", "terminal_statuses" in dash_text)

    js_blocks = re.findall(r"```dataviewjs\n(.*?)```", dash_text, re.DOTALL)
    _r("3.4", "Has dataviewjs code block", len(js_blocks) >= 1, actual=f"{len(js_blocks)} blocks")

    js = js_blocks[0] if js_blocks else ""
    if js:
        opens, closes = js.count("{"), js.count("}")
        _r("3.5", "Braces balanced", opens == closes, actual=f"{opens} vs {closes}")

        p_open, p_close = js.count("("), js.count(")")
        _r("3.6", "Parens balanced", p_open == p_close, actual=f"{p_open} vs {p_close}")

        for fn in ["canonicalStatus", "statusLabel", "keywordScore", "attachStatusEdit",
                    "appendPagination", "doDismiss", "isMonitorHit", "isActiveLifecycle",
                    "auctionDays", "noteText", "render"]:
            _r(f"3.7.{fn}", f"Has {fn} function", fn in js)

        _r("3.8", "Has STATUS_ALIASES map", "STATUS_ALIASES" in js)
        _r("3.9", "Has column resize (col-rz)", "col-rz" in js)
        _r("3.10", "Terminal statuses include 'closed'", "closed" in dash_text)
        _r("3.11", "Has render() call", "render()" in js)
        _r("3.12", "Resets page on filter change", "filterSig" in js and "pg = 1" in js)
        _r("3.13", "Has localStorage for dismiss", "localStorage" in js)

        for s in sorted(CANONICAL):
            _r(f"3.14.{s}", f"Status '{s}' in filter options", f'"{s}"' in js)

    # ══ CAT 4: COCKPIT BRIDGE ══════════════════════════════════════════════
    print("\n━━  CAT 4: COCKPIT BRIDGE  ━━")

    ps1 = SCRIPT_DIR / "obsidian-cockpit.ps1"
    _r("4.1", "obsidian-cockpit.ps1 exists", ps1.exists())
    if ps1.exists():
        ps1_text = ps1.read_text(encoding="utf-8")
        _r("4.2", "cockpit.ps1 references main.py", "main.py" in ps1_text)

    tc = VAULT / ".obsidian" / "plugins" / "templater-obsidian" / "data.json"
    _r("4.3", "Templater config exists", tc.exists())
    if tc.exists():
        tc_text = tc.read_text(encoding="utf-8")
        _r("4.4", "Config references cockpit_run", "cockpit_run" in tc_text)

    st = VAULT / "_templates" / "_startup" / "cockpit-bootstrap.md"
    _r("4.5", "Startup bootstrap template exists", st.exists())
    if st.exists():
        st_text = st.read_text(encoding="utf-8")
        _r("4.6", "Bootstrap calls tp.user.cockpit_run()", "tp.user.cockpit_run" in st_text)

    # Templater uses templates_pairs in data.json, not a user_functions folder
    if tc.exists():
        import json
        tc_config = json.loads(tc.read_text(encoding="utf-8"))
        pairs = dict(tc_config.get("templates_pairs", []))
        _r("4.7", "Templater has cockpit_run user function", "cockpit_run" in pairs)
    else:
        _r("4.7", "Templater has cockpit_run user function", False)

    # ══ CAT 5: MD_WRITER CONSISTENCY ═══════════════════════════════════════
    print("\n━━  CAT 5: MD_WRITER CONSISTENCY  ━━")

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
        "agent_run_date", "agent_mode", "agent_confidence",
    }
    USER_KEYS = {"status", "rating", "visited", "action_needed", "tags"}

    overlap = SCRAPER_KEYS & USER_KEYS
    _r("5.1", "Scraper/user keys don't overlap", len(overlap) == 0,
       actual=f"overlap: {overlap}" if overlap else "none")

    tmpl = VAULT / "_templates" / "property.md"
    if tmpl.exists():
        tmpl_text = tmpl.read_text(encoding="utf-8")
        tmpl_end = tmpl_text.find("---", 3)
        try:
            tmpl_fm = yaml.safe_load(tmpl_text[3:tmpl_end])
            missing_tmpl = [r for r in REQUIRED if r not in tmpl_fm]
            _r("5.2", "Template has all required fields", len(missing_tmpl) == 0,
               actual=f"missing: {missing_tmpl}" if missing_tmpl else "all present")
            _r("5.3", "Template default status is 'new'",
               str(tmpl_fm.get("status", "")).strip().lower() == "new",
               actual=tmpl_fm.get("status"))
        except:
            _r("5.2", "Template has valid YAML", False)

    empty_body = sum(1 for n, s, fm, t in cache[:30]
                     if fm and (end := t.find("---", 3)) != -1 and len(t[end+3:].strip()) < 5)
    _r("5.4", f"Sample notes have body content", empty_body == 0,
       actual=f"{empty_body} empty out of 30")

    # ══ CAT 6: EDGE CASES & DATA QUALITY ═══════════════════════════════════
    print("\n━━  CAT 6: EDGE CASES & DATA QUALITY  ━━")

    all_ids = [fm.get("id", "") for n, s, fm, t in cache if fm]
    dupes = [(x, c) for x, c in Counter(all_ids).items() if c > 1]
    _r("6.1", "No duplicate listing IDs", len(dupes) == 0,
       actual=f"{len(dupes)} duplicates" if dupes else "none")

    bad_dates = [(n, str(fm.get("auction_date", ""))) for n, s, fm, t in cache
                 if fm and str(fm.get("auction_date", ""))
                 and not re.match(r"^\d{4}-\d{2}-\d{2}", str(fm.get("auction_date", "")))]
    _r("6.2", "auction_date in YYYY-MM-DD format", len(bad_dates) == 0,
       actual=f"{len(bad_dates)} bad")

    bad_loc = [n for n, s, fm, t in cache[:100]
               if fm and fm.get("location")
               and (not isinstance(fm.get("location"), list) or len(fm.get("location")) != 2)]
    _r("6.3", "location is [lat, lng] array (sampled)", len(bad_loc) == 0,
       actual=f"{len(bad_loc)} bad")

    bad_type = [(n, fm.get("property_type")) for n, s, fm, t in cache
                if fm and str(fm.get("property_type", ""))
                and str(fm.get("property_type", "")) != str(fm.get("property_type", "")).lower()]
    _r("6.4", "property_type is lowercase", len(bad_type) == 0,
       actual=f"{len(bad_type)} not lowercase")

    dn = VAULT / "_templates" / "daily-note.md"
    _r("6.5", "Daily note template exists", dn.exists())

    cp = VAULT / ".obsidian" / "community-plugins.json"
    if cp.exists():
        plugins = json.loads(cp.read_text(encoding="utf-8"))
        _r("6.6a", "Dataview plugin enabled", "dataview" in plugins, actual=plugins)
        _r("6.6b", "Templater plugin enabled", "templater-obsidian" in plugins)

    no_scrape = [n for n, s, fm, t in cache if fm and not fm.get("scrape_date")]
    _r("6.7", "All notes have scrape_date", len(no_scrape) == 0,
       actual=f"{len(no_scrape)} missing")

    bad_bmv = [(n, fm.get("bmv_pct")) for n, s, fm, t in cache
               if fm and isinstance(fm.get("bmv_pct"), (int, float))
               and (fm.get("bmv_pct") < -100 or fm.get("bmv_pct") > 200)]
    _r("6.8", "bmv_pct in reasonable range", len(bad_bmv) == 0,
       actual=f"{len(bad_bmv)} out of range")

    # ══ CAT 7: CROSS-FILE CONSISTENCY ══════════════════════════════════════
    print("\n━━  CAT 7: CROSS-FILE CONSISTENCY  ━━")

    md_path = SCRIPT_DIR / "md_writer.py"
    if md_path.exists():
        md_text = md_path.read_text(encoding="utf-8")
        md_aliases_block = re.search(r"STATUS_ALIASES\s*=\s*\{(.*?)\}", md_text, re.DOTALL)
        if md_aliases_block:
            for alias in ["interested", "rejected", "passed", "pass", "custom"]:
                in_md = f'"{alias}"' in md_aliases_block.group(0)
                # Dashboard uses unquoted JS keys (e.g. interested: "reviewing")
                in_dash = bool(re.search(rf'{alias}\s*:', js)) if js else False
                _r(f"7.1.{alias}", f"Alias '{alias}' in both md_writer+Dashboard",
                   in_md and in_dash)

        md_canonical = re.search(r"CANONICAL_STATUSES\s*=\s*\{(.*?)\}", md_text, re.DOTALL)
        if md_canonical:
            for s in sorted(CANONICAL):
                _r(f"7.2.{s}", f"Canonical '{s}' in md_writer",
                   f'"{s}"' in md_canonical.group(0))

    if tmpl.exists():
        tmpl_text = tmpl.read_text(encoding="utf-8")
        has_all_statuses = all(s in tmpl_text for s in CANONICAL)
        _r("7.3", "Template comment lists all canonical statuses", has_all_statuses)

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
