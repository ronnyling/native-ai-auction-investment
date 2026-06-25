"""
pos_regression.py — Regression test for pos_parser against real POS PDFs.

Focus: KL / Selangor properties, especially stratified (condos/apartments).

Output: per-PDF field table, then a coverage summary split by:
  - Region  : KL | Selangor | Other
  - Type    : Strata | Landed | Unknown
  - Format  : Court-Malay | LACA-Malay | LACA-English | Unknown

Run:
    C:\\Python314\\python.exe scraper\\pos_regression.py [--all] [--verbose]

    --all      include all PDFs, not just KL/Selangor/strata
    --verbose  also print full text of PDFs with missing essential fields
"""

import argparse
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pos_parser import parse_pos_fields, ESSENTIAL_FIELDS

try:
    from pypdf import PdfReader
except ImportError:
    print("pypdf not installed.  pip install pypdf")
    sys.exit(1)

# ── Region / type detection ───────────────────────────────────────────────────

_KL_DISTRICTS = {
    "kuala lumpur", "chow kit", "bukit bintang", "brickfields", "kepong",
    "petaling", "ampang", "wangsa maju", "segambut", "sentul", "titiwangsa",
    "seputeh", "bangsar", "mont kiara", "sri hartamas", "cheras", "setapak",
    "gombak", "pandan", "keramat", "dutamas", "damansara", "duta",
    "w.p. kuala lumpur", "wp kuala lumpur", "wilayah persekutuan",
}
_SELANGOR_DISTRICTS = {
    "petaling jaya", "shah alam", "klang", "subang jaya", "puchong",
    "sepang", "hulu langat", "kuala langat", "sabak bernam", "kuala selangor",
    "rawang", "selayang", "batu caves", "ampang jaya", "kajang",
    "bangi", "nilai", "cyberjaya", "putrajaya", "dengkil",
    "petaling", "ulu klang", "cheras", "hulu selangor",
}
_STRATA_KEYWORDS = re.compile(
    r"kondominium|condominium|apartment|flat|residensi|serviced apartment"
    r"|perkhidmatan|pangsapuri|strata|soho|studio|suites?",
    re.I,
)
_KL_CASE    = re.compile(r"^(KL|WA)-", re.I)
_SEL_CASE   = re.compile(r"^(BA|MI)-", re.I)   # BA = Shah Alam High Court
_COURT_MALAY = re.compile(r"PLAINTIF|DEFENDAN", re.I)
_LACA_MALAY  = re.compile(r"PEMEGANG SERAHHAK|PENYERAH HAK|PEMBIAYA", re.I)
_LACA_EN     = re.compile(r"Assignee\s*/\s*Bank|Assignor\s*/\s*Borrower", re.I)


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


def detect_region(fields: dict, text: str) -> str:
    district = (fields.get("district") or "").lower()
    mukim    = (fields.get("mukim") or "").lower()
    case_no  = fields.get("case_no") or ""
    combined = district + " " + mukim

    if _KL_CASE.match(case_no):
        return "KL"
    if _SEL_CASE.match(case_no):
        return "Selangor"
    if any(k in combined for k in _KL_DISTRICTS):
        return "KL"
    if any(k in combined for k in _SELANGOR_DISTRICTS):
        return "Selangor"

    # Fallback: scan raw text for district names
    txt_lower = text[:3000].lower()
    if "kuala lumpur" in txt_lower or "w.p. kuala lumpur" in txt_lower:
        return "KL"
    if "selangor" in txt_lower:
        return "Selangor"
    return "Other"


def detect_type(fields: dict, text: str) -> str:
    if fields.get("strata_parcel_no") or fields.get("floor_no"):
        return "Strata"
    desc = (fields.get("property_description") or "").lower()
    if _STRATA_KEYWORDS.search(desc) or _STRATA_KEYWORDS.search(text[:4000]):
        return "Strata"
    if fields.get("land_area_sqft") and not fields.get("strata_parcel_no"):
        return "Landed"
    if fields.get("built_up_sqft"):
        return "Strata"   # built-up without land → likely strata
    return "Unknown"


def detect_format(text: str) -> str:
    if _LACA_EN.search(text[:2000]):
        return "LACA-English"
    if _LACA_MALAY.search(text[:2000]):
        return "LACA-Malay"
    if _COURT_MALAY.search(text[:2000]):
        return "Court-Malay"
    return "Unknown"


# ── Main regression loop ──────────────────────────────────────────────────────

def run(show_all: bool = False, verbose: bool = False):
    cache = Path(__file__).parent / "pos_study_cache"
    pdfs  = sorted(cache.glob("*.pdf"))

    if not pdfs:
        print(f"No PDFs found in {cache}")
        return

    rows = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"  [{i:3d}/{len(pdfs)}] {pdf.name}", file=sys.stderr, flush=True)
        try:
            result  = [None]
            error   = [None]
            def _worker(p=pdf):
                try:    result[0] = extract_text(p)
                except Exception as e: error[0] = e
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            t.join(timeout=30)
            if t.is_alive():
                raise RuntimeError(f"pypdf timeout (>30s) skipping {pdf.name}")
            if error[0]:
                raise error[0]
            text   = result[0]
            fields = parse_pos_fields(text)
        except Exception as exc:
            rows.append({
                "name": pdf.name, "region": "?", "type": "?", "format": "?",
                "complete": False, "missing": list(ESSENTIAL_FIELDS),
                "fields": {}, "text": "", "error": str(exc),
            })
            continue

        region  = detect_region(fields, text)
        ptype   = detect_type(fields, text)
        fmt     = detect_format(text)
        complete = fields.get("_extraction_complete", False)
        missing  = fields.get("_missing_essential", [])

        rows.append({
            "name": pdf.name, "region": region, "type": ptype, "format": fmt,
            "complete": complete, "missing": missing,
            "fields": fields, "text": text, "error": None,
        })

    # ── filter ────────────────────────────────────────────────────────────────
    focus = [r for r in rows
             if show_all or r["region"] in ("KL", "Selangor") or r["type"] == "Strata"]

    print("=" * 80)
    print(f"  POS REGRESSION  -  KL / Selangor / Strata")
    print(f"  Total cached: {len(rows)}  |  In focus: {len(focus)}")
    print("=" * 80)

    for r in focus:
        status = "COMPLETE" if r["complete"] else f"INCOMPLETE ({', '.join(r['missing'])})"
        print(f"\n" + "-"*80)
        print(f"  {r['name']}")
        print(f"  Region: {r['region']}  Type: {r['type']}  Format: {r['format']}")
        print(f"  Status: {status}")
        if r["error"]:
            print(f"  ERROR : {r['error']}")
            continue
        f = r["fields"]
        interesting = [
            ("bank",               f.get("bank")),
            ("borrower",           f.get("borrower")),
            ("case_no",            f.get("case_no")),
            ("district",           f.get("district")),
            ("reserve_price_rm",   f.get("reserve_price_rm")),
            ("deposit_required_rm",f.get("deposit_required_rm")),
            ("disbursement_days",  f.get("disbursement_days")),
            ("encumbrances",       f.get("encumbrances")),
            ("location",           f.get("location")),
            ("tenure",             f.get("tenure")),
            ("strata_parcel_no",   f.get("strata_parcel_no")),
            ("floor_no",           f.get("floor_no")),
            ("built_up_sqft",      f.get("built_up_sqft")),
            ("bedrooms",           f.get("bedrooms")),
            ("bathrooms",          f.get("bathrooms")),
        ]
        for key, val in interesting:
            if val is not None:
                marker = ""
            else:
                marker = "  ← MISSING" if key in ESSENTIAL_FIELDS else ""
            print(f"    {key:<22s}: {val}{marker}")

        if verbose and not r["complete"]:
            print(f"\n  [RAW TEXT SNIPPET for {r['name']}]")
            print("  " + "\n  ".join(r["text"][:2500].splitlines()))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n" + "="*80)
    print("  SUMMARY")
    print("="*80)

    for region in ("KL", "Selangor", "Other"):
        subset = [r for r in rows if r["region"] == region]
        if not subset:
            continue
        complete   = sum(1 for r in subset if r["complete"])
        strata_cnt = sum(1 for r in subset if r["type"] == "Strata")
        landed_cnt = sum(1 for r in subset if r["type"] == "Landed")
        print(f"\n  {region} ({len(subset)} PDFs):"
              f"  Strata={strata_cnt}  Landed={landed_cnt}"
              f"  Complete={complete}/{len(subset)}")

        # Per-field hit rate
        for field in ESSENTIAL_FIELDS:
            hits = sum(1 for r in subset if r["fields"].get(field))
            pct  = round(hits / len(subset) * 100)
            bar  = "█" * (pct // 10) + "░" * (10 - pct // 10)
            print(f"    {field:<22s} {bar} {pct:3d}%  ({hits}/{len(subset)})")

    # Incomplete PDFs list
    incomplete = [r for r in rows if not r["complete"]]
    if incomplete:
        print(f"\n  INCOMPLETE PDFs ({len(incomplete)}):")
        for r in incomplete:
            print(f"    {r['region']:8s} {r['type']:8s}  {r['name']}")
            print(f"    missing: {r['missing']}")
    else:
        print("\n  All PDFs: 100% complete extraction!")

    print(f"\n" + "="*80)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all",     action="store_true", help="Show all PDFs not just KL/Selangor/strata")
    ap.add_argument("--verbose", action="store_true", help="Print raw text of incomplete PDFs")
    args = ap.parse_args()
    run(show_all=args.all, verbose=args.verbose)
