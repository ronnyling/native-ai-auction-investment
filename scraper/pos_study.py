"""
pos_study.py — Collect, extract, and analyse real POS PDFs from BidNow.

Stages:
  1. COLLECT  — Harvest POS PDF URLs from BidNow property detail pages
  2. DOWNLOAD — Download each PDF to a local cache directory
  3. ANALYSE  — Extract text and catalogue field presence / pattern variants
  4. REPORT   — Print findings summary + write pos_study_findings.json

Usage:
  python scraper/pos_study.py             # full run (all stages)
  python scraper/pos_study.py --collect   # stage 1 only
  python scraper/pos_study.py --analyse   # skip download, analyse cached PDFs

The script is idempotent — already-downloaded PDFs are skipped.
"""

import argparse
import json
import os
import re
import sys
import time
import random
from collections import Counter, defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Paths ─────────────────────────────────────────────────────────────────────

_HERE     = Path(__file__).parent
_ROOT     = _HERE.parent
_VAULT    = _ROOT / "vault" / "Properties"
_CACHE    = _HERE / "pos_study_cache"
_FINDINGS = _HERE / "pos_study_findings.json"
_URL_LIST = _HERE / "pos_study_urls.json"

# Penang JSON from goal_6_prop that already has 35 PDF URLs
_PENANG_JSON = Path(r"c:\Users\r.a.ling\OneDrive - Avanade\Documents\work\Native AI\goal_6_prop\bidnow_penang_pos_pdfs_complete_urls.json")

TARGET_PDF_COUNT = 120   # minimum target

# ── HTTP helpers ──────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ms;q=0.8",
}

def _get(url: str, timeout: int = 20, as_bytes: bool = False):
    """GET with simple error handling. Returns content or None."""
    try:
        import urllib.request
        import urllib.parse
        # URL-encode literal spaces in the path only (don't touch query or scheme)
        if " " in url:
            parts = url.split("?", 1)
            parts[0] = parts[0].replace(" ", "%20")
            url = "?".join(parts)
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read() if as_bytes else resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_js_var(html: str, var_name: str) -> Optional[Dict]:
    """
    Extract a named JS variable embedded as `var <name> = {...};` in BidNow HTML.
    Same logic as bidnow.py — POS data is NOT in href attributes but in this var.
    """
    needle = f"var {var_name} = {{"
    start = html.find(needle)
    if start == -1:
        return None
    json_start = start + len(f"var {var_name} = ")
    depth = 0
    json_end = 0
    for i in range(json_start, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                json_end = i + 1
                break
    if not json_end:
        return None
    try:
        return json.loads(html[json_start:json_end])
    except json.JSONDecodeError:
        return None


# ── Stage 1: Collect POS PDF URLs ─────────────────────────────────────────────

def _urls_from_penang_json() -> List[Dict]:
    """Load the 35 Penang PDF URLs we already have in goal_6_prop."""
    if not _PENANG_JSON.exists():
        print(f"  [warn] Penang JSON not found: {_PENANG_JSON}")
        return []
    data = json.loads(_PENANG_JSON.read_text(encoding="utf-8"))
    results = []
    for p in data.get("properties", []):
        prop_id = str(p.get("property_id", ""))
        for pdf in p.get("pdfs", []):
            url = pdf.get("full_url", "")
            if url and "pos_file" in url:
                results.append({"bn_id": prop_id, "url": url, "source": "penang_json"})
    print(f"  [penang_json] {len(results)} PDF URLs")
    return results


_BIDNOW_BASE = "https://www.bidnow.my"


def _build_pos_url(pos_file_path: str) -> str:
    """Convert a relative BidNow pos_file_path to a full HTTPS URL."""
    if not pos_file_path:
        return ""
    cleaned = pos_file_path.replace("\\/", "/").lstrip("/")
    # URL-encode spaces in the filename component only
    cleaned = cleaned.replace(" ", "%20")
    return f"{_BIDNOW_BASE}/{cleaned}"


def _scrape_property_page(bn_id: str) -> List[str]:
    """
    Scrape BidNow property detail page, extract `var ap = {...}` embedded JSON,
    and return POS PDF URL(s). BidNow embeds the data as inline JS — not in href
    attributes — so raw HTML href-pattern scraping always returns nothing.
    """
    url = f"{_BIDNOW_BASE}/auction-property/x/{bn_id}"
    html = _get(url)
    if not html:
        return []

    ap = _extract_js_var(html, "ap")
    if not ap:
        return []

    # pos_file_path may be a single path OR absent
    pos_path = ap.get("pos_file_path", "") or ""
    if pos_path:
        full = _build_pos_url(pos_path)
        if full:
            return [full]

    # Also check pos_files array if present (some listings have multiple)
    results = []
    for pf in ap.get("pos_files", []):
        path = pf.get("file_path", "") or pf.get("full_url", "")
        if path:
            results.append(_build_pos_url(path) if not path.startswith("http") else path)

    return results


def _load_vault_ids(limit: int = 300) -> List[str]:
    """Read BidNow IDs from vault filenames — NO file content read, so it's fast."""
    ids = []
    if not _VAULT.exists():
        return ids
    for f in sorted(_VAULT.glob("bn-*.md")):
        m = re.match(r"bn-(\d+)\.md", f.name)
        if m:
            ids.append(m.group(1))
    random.seed(42)
    random.shuffle(ids)
    return ids[:limit]


def collect_urls(existing: List[Dict]) -> List[Dict]:
    """Fill up to TARGET_PDF_COUNT PDF URLs by scraping BidNow property pages."""
    existing_set = {e["url"] for e in existing}
    results = list(existing)

    needed = TARGET_PDF_COUNT - len(results)
    if needed <= 0:
        print(f"  Already have {len(results)} URLs — skipping scrape")
        return results

    vault_ids = _load_vault_ids(limit=400)
    print(f"  Scraping up to {len(vault_ids)} BidNow property pages for {needed} more PDFs...")

    found_extra = 0
    for i, bn_id in enumerate(vault_ids):
        if len(results) >= TARGET_PDF_COUNT:
            break
        pdfs = _scrape_property_page(bn_id)
        new = [u for u in pdfs if u not in existing_set]
        for u in new:
            results.append({"bn_id": bn_id, "url": u, "source": "scraped"})
            existing_set.add(u)
            found_extra += 1
        status = f"OK({len(new)})" if new else "none"
        print(f"  [{i+1}/{len(vault_ids)}] bn-{bn_id}: {status}  total={len(results)}")
        time.sleep(1.2 + random.random() * 0.8)   # 1.2–2.0 s between requests

    print(f"  Collected {len(results)} PDF URLs total ({found_extra} scraped)")
    return results


# ── Stage 2: Download PDFs ────────────────────────────────────────────────────

def download_pdfs(url_list: List[Dict]) -> List[Path]:
    """Download PDFs to _CACHE, skip if already present. Returns local paths."""
    _CACHE.mkdir(exist_ok=True)
    paths = []
    for i, item in enumerate(url_list):
        url = item["url"]
        fname = re.sub(r"[^\w.-]", "_", url.split("/")[-1].split("?")[0])
        if not fname.endswith(".pdf"):
            fname += ".pdf"
        dest = _CACHE / f"{item['bn_id']}_{fname}"
        if dest.exists() and dest.stat().st_size > 1000:
            paths.append(dest)
            continue
        data = _get(url, timeout=25, as_bytes=True)
        if data and len(data) > 500:
            dest.write_bytes(data)
            paths.append(dest)
            print(f"  [{i+1}/{len(url_list)}] Downloaded {dest.name} ({len(data)//1024} KB)")
        else:
            print(f"  [{i+1}/{len(url_list)}] FAILED  {url}")
        time.sleep(0.5 + random.random() * 0.5)
    print(f"  {len(paths)} PDFs ready in cache")
    return paths


# ── Stage 3: Extract text from PDFs ──────────────────────────────────────────

def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF file. Returns empty string on failure."""
    try:
        try:
            from pypdf import PdfReader
        except ImportError:
            from PyPDF2 import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pass
        return "\n".join(pages)
    except Exception as e:
        return ""


# ── Stage 4: Analyse POS texts ───────────────────────────────────────────────

# All fields we try to detect and the patterns we look for
_FIELD_PATTERNS: Dict[str, List[str]] = {
    "bedrooms": [
        r"bilik\s*tidur",
        r"bedroom",
        r"bilik\s*tidur\s*utama",
        r"\d\+\d\s*bilik\s*tidur",       # e.g. "3+1 bilik tidur"
    ],
    "bathrooms": [
        r"bilik\s*(?:mandi|air)",
        r"bathroom",
        r"lavatory",
        r"washroom",
    ],
    "built_up_sqft": [
        r"keluasan\s*petak",
        r"keluasan\s*binaan",
        r"keluasan\s*lantai",
        r"built.?up\s*area",
        r"floor\s*area",
    ],
    "land_area": [
        r"keluasan\s*tanah",
        r"land\s*area",
    ],
    "tenure_freehold": [
        r"hakmilik\s*kekal",
        r"freehold",
    ],
    "tenure_leasehold": [
        r"pajakan",
        r"leasehold",
    ],
    "strata_parcel": [
        r"no\.\s*petak",
        r"no\.\s*tingkat",
        r"strata\s*title",
    ],
    "mukim_district": [
        r"mukim\s*/\s*daerah",
        r"mukim\s*[:/]",
        r"district\s*[:/]",
    ],
    "bank_plaintif": [
        r"plaintif",
        r"plaintiff",
        r"peminjam",
    ],
    "borrower_defendan": [
        r"defendan",
        r"defendant",
        r"pemilik\s*berdaftar",
    ],
    "case_no": [
        r"\b[A-Z]{1,5}-\d{2,3}-\d+-\d+/\d{4}\b",
    ],
    "reserve_price": [
        r"harga\s*rizab",
        r"reserve\s*price",
        r"harga\s*jualan",
    ],
    "lawyer_firm": [
        r"firma\s*guaman",
        r"peguam\s*cara",
        r"solicitor",
    ],
    "auction_date": [
        r"tarikh\s*lelongan",
        r"date\s*of\s*auction",
        r"tarikh\s*jualan",
    ],
}

# Variant spellings / typos seen in real POS documents
_TYPO_VARIANTS: Dict[str, List[str]] = {
    "bilik tidur": [
        r"bilik tidur",
        r"bilik tiduer",    # typo
        r"bilik\s+tidur",
        r"biliktidur",
        r"bilik  tidur",    # double space
        r"bilit tidur",     # 't' → 'k'
    ],
    "keluasan": [
        r"keluasan",
        r"kelusaan",        # transposition typo
        r"keluesaan",
    ],
    "plaintif": [
        r"plaintif",
        r"plaintiff",
        r"plaintff",        # missing 'i'
        r"plainitf",        # transposition
    ],
    "hakmilik": [
        r"hakmilik",
        r"hak milik",
        r"hak-milik",
    ],
    "pajakan": [
        r"pajakan",
        r"perjanjian pajakan",
    ],
    "pemilik berdaftar": [
        r"pemilik berdaftar",
        r"pemilik\s+berdaftar",
        r"pemilk berdaftar",   # missing 'i'
    ],
}

# Auctioneer / format fingerprints
_FORMAT_FINGERPRINTS: Dict[str, List[str]] = {
    "elelong_court":   ["DALAM MAHKAMAH", "e-Lelong", "Notis Lelongan Awam", "court order"],
    "bidnow_laca":     ["LACA", "Lembaga Akreditasi", "BidNow", "auction-property"],
    "hartanah_seksyen": ["SEKSYEN", "seksyen", "Hartanah Seksyen"],
    "signed_sealed":   ["meterai diri", "sealed", "tandatangan"],
    "jual_beli":       ["surat perjanjian jual beli", "perjanjian jual"],
    "english_only":    ["Proclamation of Sale", "The Assignee", "The Assignor"],
    "bilingual":       ["Perisytiharan Jualan", "Proclamation of Sale"],
}

# ── Number-word extraction helpers ────────────────────────────────────────────

_WORD_TO_INT = {
    "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "lapan": 8, "sembilan": 9, "sepuluh": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _to_int(s: str) -> Optional[int]:
    s = s.strip().lower()
    return int(s) if s.isdigit() else _WORD_TO_INT.get(s)


def _analyse_one(text: str, path: Path) -> Dict[str, Any]:
    """Return per-document analysis dict."""
    tl = text.lower()
    rec: Dict[str, Any] = {
        "file": path.name,
        "chars": len(text),
        "pages_guess": text.count("\f") + 1,
        "fields_found": [],
        "field_hits": {},           # field_name → [matched snippets]
        "typo_hits": {},            # typo_key → [raw match]
        "format_type": [],
        "bedroom_raw": None,
        "bathroom_raw": None,
        "reserve_raw": None,
        "tenure_raw": None,
        "case_no_raw": None,
        "district_raw": None,
        "built_up_raw": None,
        "land_area_raw": None,
        "bank_raw": None,
    }

    # Detect format type
    for fmt_name, signals in _FORMAT_FINGERPRINTS.items():
        for sig in signals:
            if re.search(sig, text, re.I):
                if fmt_name not in rec["format_type"]:
                    rec["format_type"].append(fmt_name)
                break

    # Field presence
    for field, pats in _FIELD_PATTERNS.items():
        hits = []
        for pat in pats:
            for m in re.finditer(pat, tl):
                snippet = text[max(0, m.start()-30):m.end()+30].strip()
                hits.append(snippet)
        if hits:
            rec["fields_found"].append(field)
            rec["field_hits"][field] = hits[:3]   # keep up to 3 examples

    # Typo variants
    for key, variants in _TYPO_VARIANTS.items():
        for variant in variants:
            for m in re.finditer(variant, tl):
                if key not in rec["typo_hits"]:
                    rec["typo_hits"][key] = []
                snippet = text[max(0, m.start()-10):m.end()+10].strip()
                rec["typo_hits"][key].append(snippet)

    # Extract specific raw values for deeper analysis
    # Bedrooms
    for pat in [
        r"(\w+)\s*(?:\(\d+\))?\s*bilik\s*tidur",
        r"(?:comprising|consisting of)\s+(\w+)\s+bedrooms?",
        r"(\d\+\d)\s*bilik\s*tidur",   # "3+1 bilik tidur"
        r"\b(\d)\s*bilik\s*tidur",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            rec["bedroom_raw"] = m.group(0).strip()
            break

    # Bathrooms
    for pat in [
        r"(\w+)\s*(?:\(\d+\))?\s*(?:bilik\s*(?:mandi|air)|bathroom)",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            rec["bathroom_raw"] = m.group(0).strip()
            break

    # Reserve price
    for pat in [
        r"harga\s*rizab\s+(?:sebanyak\s+)?RM\s*[\d,]+(?:\.\d{2})?",
        r"reserve\s*price\s+(?:of\s+)?RM\s*[\d,]+(?:\.\d{2})?",
        r"RM\s*[\d,]+(?:\.\d{2})?\s*(?:being|iaitu)\s+(?:the\s+)?reserve",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            rec["reserve_raw"] = m.group(0).strip()
            break

    # Tenure
    m = re.search(r"(Hakmilik\s*Kekal|Freehold|Pajakan\s*\d+\s*[Tt]ahun|Leasehold\s*(?:for\s+)?\d+\s*[Yy]ears?)", text)
    if m:
        rec["tenure_raw"] = m.group(0).strip()

    # Case number
    m = re.search(r"\b([A-Z]{1,5}-\d{2,3}-\d+-\d+/\d{4})\b", text)
    if m:
        rec["case_no_raw"] = m.group(1)

    # District
    m = re.search(r"Mukim\s*/\s*Daerah\s*/\s*Negeri\s*[:/]?\s*([^/\n]+)\s*/\s*([^/\n]+)\s*/\s*([^\n]+)", text, re.I)
    if m:
        rec["district_raw"] = f"{m.group(1).strip()} / {m.group(2).strip()} / {m.group(3).strip()}"

    # Built-up
    m = re.search(
        r"Keluasan\s*(?:Petak|Binaan|Lantai)\s*[:/]?\s*([\d,]+(?:\.\d+)?)\s*(kaki\s*persegi|meter\s*persegi|sqft|sqm)",
        text, re.I,
    )
    if m:
        rec["built_up_raw"] = m.group(0).strip()

    # Land area
    m = re.search(
        r"Keluasan\s*Tanah\s*[:/]?\s*([\d,]+(?:\.\d+)?)\s*(kaki\s*persegi|meter\s*persegi|sqft|sqm)",
        text, re.I,
    )
    if m:
        rec["land_area_raw"] = m.group(0).strip()

    # Bank
    for pat in [
        r"([\w &().,'-]+(?:Bank|Berhad|Bhd|Finance|Credit|Mortgage)[^\n]*)\s*\n[.\s]*PLAINTIF",
        r"Pembekal\s*Kredit[:/]?\s*(.+?)(?:\n|$)",
        r"([\w &().,'-]+(?:Bank|Berhad)[^\n]{0,60})\n",
    ]:
        m = re.search(pat, text, re.I)
        if m:
            raw = m.group(1).strip()
            if len(raw) > 3:
                rec["bank_raw"] = raw
                break

    return rec


def analyse_corpus(paths: List[Path]) -> List[Dict]:
    results = []
    failed = 0
    for i, path in enumerate(paths):
        text = _extract_pdf_text(path)
        if len(text) < 100:
            print(f"  [{i+1}/{len(paths)}] SKIP (empty) {path.name}")
            failed += 1
            continue
        rec = _analyse_one(text, path)
        results.append(rec)
        n_fields = len(rec["fields_found"])
        print(f"  [{i+1}/{len(paths)}] {path.name[:50]}  fields={n_fields}  fmt={rec['format_type']}")
    print(f"  Analysed {len(results)} POS (failed to extract: {failed})")
    return results


# ── Stage 5: Build findings summary ──────────────────────────────────────────

def build_findings(records: List[Dict]) -> Dict[str, Any]:
    n = len(records)
    if n == 0:
        return {"error": "no records"}

    # Field coverage
    field_count = Counter()
    for r in records:
        for f in r["fields_found"]:
            field_count[f] += 1

    # Format distribution
    fmt_count = Counter()
    for r in records:
        for fmt in r["format_type"]:
            fmt_count[fmt] += 1

    # Bedroom raw pattern catalogue
    bedroom_raws = Counter(r["bedroom_raw"] for r in records if r["bedroom_raw"])
    bathroom_raws = Counter(r["bathroom_raw"] for r in records if r["bathroom_raw"])
    reserve_raws = Counter(r["reserve_raw"] for r in records if r["reserve_raw"])
    tenure_raws = Counter(r["tenure_raw"] for r in records if r["tenure_raw"])
    case_patterns = Counter()
    for r in records:
        if r["case_no_raw"]:
            prefix = r["case_no_raw"].split("-")[0]
            case_patterns[prefix] += 1

    # Typo catalogue
    typo_all = defaultdict(Counter)
    for r in records:
        for key, hits in r["typo_hits"].items():
            for h in hits:
                # normalise whitespace for counting
                typo_all[key][re.sub(r"\s+", " ", h.strip().lower())] += 1

    # Missing field analysis (docs where field is absent)
    all_fields = list(_FIELD_PATTERNS.keys())
    missing_pct = {
        f: round(100 * (1 - field_count.get(f, 0) / n), 1)
        for f in all_fields
    }

    # Built-up / land area co-occurrence
    has_buildup  = sum(1 for r in records if r["built_up_raw"])
    has_landarea = sum(1 for r in records if r["land_area_raw"])
    has_bank     = sum(1 for r in records if r["bank_raw"])
    has_bedroom  = sum(1 for r in records if r["bedroom_raw"])

    # Sample snippets for rare fields
    snippets = defaultdict(list)
    for r in records:
        for field, hits in r["field_hits"].items():
            if len(snippets[field]) < 5:
                snippets[field].extend(hits[:2])

    return {
        "corpus_size": n,
        "field_coverage_pct": {f: round(100 * cnt / n, 1) for f, cnt in field_count.most_common()},
        "missing_pct": missing_pct,
        "format_distribution": dict(fmt_count.most_common()),
        "bedroom_patterns": dict(bedroom_raws.most_common(20)),
        "bathroom_patterns": dict(bathroom_raws.most_common(20)),
        "reserve_price_patterns": dict(reserve_raws.most_common(20)),
        "tenure_patterns": dict(tenure_raws.most_common(20)),
        "case_no_prefixes": dict(case_patterns.most_common(20)),
        "typo_catalogue": {k: dict(v.most_common(10)) for k, v in typo_all.items()},
        "cooccurrence": {
            "has_built_up": f"{has_buildup}/{n} ({round(100*has_buildup/n)}%)",
            "has_land_area": f"{has_landarea}/{n} ({round(100*has_landarea/n)}%)",
            "has_bank": f"{has_bank}/{n} ({round(100*has_bank/n)}%)",
            "has_bedroom": f"{has_bedroom}/{n} ({round(100*has_bedroom/n)}%)",
        },
        "field_snippets": dict(snippets),
    }


def print_report(findings: Dict):
    print()
    print("=" * 70)
    print(f"  POS CORPUS ANALYSIS — {findings['corpus_size']} documents")
    print("=" * 70)

    print("\n── Field Coverage (% of POS that contain each field) ──")
    for field, pct in sorted(findings["field_coverage_pct"].items(), key=lambda x: -x[1]):
        bar = "█" * int(pct / 5)
        print(f"  {field:<25} {pct:>5.1f}%  {bar}")

    print("\n── Format Distribution ──")
    for fmt, cnt in findings["format_distribution"].items():
        print(f"  {fmt:<30} {cnt}")

    print("\n── Bedroom Pattern Variants (top 15) ──")
    for pat, cnt in list(findings["bedroom_patterns"].items())[:15]:
        print(f"  [{cnt:>3}] {pat}")

    print("\n── Tenure Pattern Variants ──")
    for pat, cnt in findings["tenure_patterns"].items():
        print(f"  [{cnt:>3}] {pat}")

    print("\n── Reserve Price Pattern Variants (top 10) ──")
    for pat, cnt in list(findings["reserve_price_patterns"].items())[:10]:
        print(f"  [{cnt:>3}] {pat}")

    print("\n── Typo / Variant Catalogue ──")
    for key, variants in findings["typo_catalogue"].items():
        if any(cnt > 0 for cnt in variants.values()):
            print(f"  {key}:")
            for variant, cnt in variants.items():
                if cnt > 0:
                    print(f"    [{cnt:>3}] '{variant}'")

    print("\n── Co-occurrence ──")
    for k, v in findings["cooccurrence"].items():
        print(f"  {k:<30} {v}")

    print("\n── Case Number Prefixes (court code / state) ──")
    for prefix, cnt in findings["case_no_prefixes"].items():
        print(f"  {prefix:<10} {cnt}")

    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="POS corpus study tool")
    parser.add_argument("--collect-only", action="store_true", help="Stage 1 only")
    parser.add_argument("--analyse-only", action="store_true", help="Skip stages 1-2, use cached PDFs")
    parser.add_argument("--no-download",  action="store_true", help="Skip download stage")
    args = parser.parse_args()

    # ── Stage 1: Collect URLs ──────────────────────────────────────────────
    print("\n[Stage 1] Collecting POS PDF URLs...")
    seed_urls = _urls_from_penang_json()
    if not args.analyse_only:
        all_urls = collect_urls(seed_urls)
        _URL_LIST.write_text(json.dumps(all_urls, indent=2), encoding="utf-8")
        print(f"  Saved {len(all_urls)} URLs to {_URL_LIST.name}")
    else:
        if _URL_LIST.exists():
            all_urls = json.loads(_URL_LIST.read_text(encoding="utf-8"))
            print(f"  Loaded {len(all_urls)} URLs from {_URL_LIST.name}")
        else:
            all_urls = seed_urls

    if args.collect_only:
        return

    # ── Stage 2: Download ──────────────────────────────────────────────────
    if not args.analyse_only and not args.no_download:
        print(f"\n[Stage 2] Downloading {len(all_urls)} PDFs...")
        pdf_paths = download_pdfs(all_urls)
    else:
        _CACHE.mkdir(exist_ok=True)
        pdf_paths = list(_CACHE.glob("*.pdf"))
        print(f"\n[Stage 2] Using {len(pdf_paths)} cached PDFs (skipped download)")

    if not pdf_paths:
        print("  No PDFs available — aborting.")
        sys.exit(1)

    # ── Stage 3+4: Extract and analyse ────────────────────────────────────
    print(f"\n[Stage 3] Extracting text and analysing {len(pdf_paths)} PDFs...")
    records = analyse_corpus(pdf_paths)

    if not records:
        print("  No usable POS texts extracted.")
        sys.exit(1)

    # ── Stage 5: Report ────────────────────────────────────────────────────
    print(f"\n[Stage 4] Building findings from {len(records)} records...")
    findings = build_findings(records)
    _FINDINGS.write_text(json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Findings saved to {_FINDINGS.name}")

    print_report(findings)


if __name__ == "__main__":
    main()
