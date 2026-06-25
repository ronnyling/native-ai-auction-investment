"""
pos_bulk_download.py — Download up to TARGET new POS PDFs from BidNow.

Strategy:
  1. Scrape BidNow listing pages (KL + Selangor strata first, then landed,
     then other states) to collect listing IDs cheaply.
  2. pos_file_path is NOT in listing page data (var aps) — it is only on the
     detail page (var ap).  For each new ID, call scrape_detail() to get the
     POS URL, then download.
  3. Stop once TARGET new PDFs are downloaded.
  4. Print a download summary.

Usage:
  python scraper/pos_bulk_download.py [--target 100] [--max-pages 5]
"""

import argparse
import re
import sys
import time
import random
from collections import Counter
from pathlib import Path

_HERE  = Path(__file__).parent
_CACHE = _HERE / "pos_study_cache"
sys.path.insert(0, str(_HERE))

from bidnow import BidNowScraper

# ── Config ─────────────────────────────────────────────────────────────────────

DEFAULT_TARGET = 100

# Scrape order: (state, property_type or None).
# Strata (KL/Selangor) first to fill the known coverage gap.
SCRAPE_PLAN = [
    ("Kuala Lumpur",    "Condominium / SOHO House / Apartment"),
    ("Kuala Lumpur",    "Flat House"),
    ("Kuala Lumpur",    "Service Suite"),
    ("Selangor",        "Condominium / SOHO House / Apartment"),
    ("Selangor",        "Flat House"),
    ("Selangor",        "Service Suite"),
    ("Kuala Lumpur",    "Link House / Townhouse / Terrace House"),
    ("Kuala Lumpur",    "Bungalow / Villa House / Semi-D House"),
    ("Selangor",        "Link House / Townhouse / Terrace House"),
    ("Selangor",        "Bungalow / Villa House / Semi-D House"),
    ("Johor",           "Condominium / SOHO House / Apartment"),
    ("Johor",           "Link House / Townhouse / Terrace House"),
    ("Negeri Sembilan", None),
    ("Perak",           None),
    ("Kedah",           None),
    ("Melaka",          None),
    ("Pahang",          None),
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cached_ids(cache: Path) -> set:
    ids = set()
    for f in cache.glob("*.pdf"):
        m = re.match(r"^(\d+)_", f.name)
        if m:
            ids.add(m.group(1))
    return ids


def _safe_filename(listing_id: str, url: str) -> str:
    tail = url.split("/")[-1].split("?")[0]
    tail = re.sub(r"[^\w.-]", "_", tail)
    if not tail.endswith(".pdf"):
        tail += ".pdf"
    return f"{listing_id}_{tail}"


def _download_pdf(url: str, dest: Path, session) -> bool:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.content
        if len(data) < 500:
            return False
        dest.write_bytes(data)
        return True
    except Exception as exc:
        print(f"    [FAIL] {url}: {exc}", flush=True)
        return False


# ── Main ───────────────────────────────────────────────────────────────────────

def run(target: int = DEFAULT_TARGET, max_pages_per_query: int = 5):
    _CACHE.mkdir(exist_ok=True)
    scraper = BidNowScraper()

    cached_ids = _cached_ids(_CACHE)
    print(f"[init] {len(cached_ids)} listing IDs already in cache", flush=True)

    # ── Phase 1: Collect listing IDs ──────────────────────────────────────────
    # pos_file_path is NOT in listing page data (var aps); only in detail page.
    # We collect IDs here cheaply (1 request per 12 listings), then detail-scrape.
    listing_pool = []     # (listing_id, state, is_strata)
    seen_ids = set(cached_ids)

    print(f"\n[phase-1] Collecting listing IDs from BidNow...", flush=True)
    for state, prop_type in SCRAPE_PLAN:
        if len(listing_pool) >= target * 4:
            break  # enough candidates for ample headroom

        filters = {"state": state, "listing": "active", "sort": "new"}
        if prop_type:
            filters["property_type"] = prop_type

        label = f"{state} / {prop_type or 'all'}"
        print(f"  [{label}]", flush=True)
        listings = scraper.scrape_listings(filters=filters, max_pages=max_pages_per_query)

        added = 0
        for lst in listings:
            lid = lst.get("listing_id", "")
            if not lid or lid in seen_ids:
                continue
            seen_ids.add(lid)
            is_strata = lst.get("property_type", "") in ("condo", "apartment")
            listing_pool.append((lid, state, is_strata))
            added += 1
        print(f"    -> {added} new IDs  (pool: {len(listing_pool)})", flush=True)
        time.sleep(1.0)

    print(f"\n[phase-1] {len(listing_pool)} candidate IDs collected", flush=True)
    # Strata first
    listing_pool.sort(key=lambda x: (0 if x[2] else 1, x[1]))

    # ── Phase 2: Detail-scrape for POS URL, then download ─────────────────────
    print(f"\n[phase-2] Detail-scraping for POS URLs + downloading...", flush=True)
    downloaded = 0
    no_pos     = 0
    failed     = 0
    region_ctr = Counter()

    for lid, state, is_strata in listing_pool:
        if downloaded >= target:
            break

        detail = scraper.scrape_detail(lid)
        if not detail:
            no_pos += 1
            time.sleep(0.5)
            continue

        pos_url = detail.get("pos_url", "")
        if not pos_url:
            no_pos += 1
            time.sleep(0.5)
            continue

        dest = _CACHE / _safe_filename(lid, pos_url)
        if dest.exists() and dest.stat().st_size > 500:
            # Already cached (possibly under a slightly different name)
            downloaded += 1
            region_ctr[state] += 1
            time.sleep(0.3)
            continue

        ok = _download_pdf(pos_url, dest, scraper.session)
        if ok:
            downloaded += 1
            region_ctr[state] += 1
            tag = "strata" if is_strata else "landed"
            size_kb = dest.stat().st_size // 1024
            print(f"  [{downloaded:3d}/{target}] {lid} ({state}, {tag})  {dest.name}  {size_kb}KB", flush=True)
        else:
            failed += 1
        # Polite delay (detail page already fetched above; this covers download)
        time.sleep(0.8 + random.random() * 0.5)

    print(f"\n[done] Downloaded={downloaded}  No-POS={no_pos}  Failed={failed}", flush=True)
    total_cached = len(list(_CACHE.glob("*.pdf")))
    print(f"[done] Total PDFs in cache: {total_cached}", flush=True)
    print(f"\n[region breakdown]:", flush=True)
    for st, cnt in region_ctr.most_common():
        print(f"  {st}: {cnt}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=DEFAULT_TARGET,
                    help=f"Number of new PDFs to download (default {DEFAULT_TARGET})")
    ap.add_argument("--max-pages", type=int, default=5,
                    help="Max BidNow pages per query (default 5)")
    args = ap.parse_args()
    run(target=args.target, max_pages_per_query=args.max_pages)
