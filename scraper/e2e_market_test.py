"""
e2e_market_test.py -- End-to-end test for the market research pipeline.

What it does:
  1. Builds market cache from iProperty (or loads existing cache)
  2. Scans vault for high-priority properties (bmv >= 29 OR auction_count >= 3)
  3. Injects market fields into matching listing dicts
  4. Re-writes those vault notes (frontmatter + summary block)
  5. Prints a report showing what was enriched

Run from: scraper/ directory
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from md_writer import MDWriter
from market_research import MarketResearcher

VAULT_PROPS = Path(__file__).parent.parent / "vault" / "Properties"
CACHE_PATH  = Path(__file__).parent / "market_cache.json"
MAX_TO_PROCESS = 50   # limit for test run

print("=" * 65)
print("  Market Research E2E Test")
print("=" * 65)

# ── Step 1: Build / load market cache ─────────────────────────────────────────
print("\n[Step 1] Loading / building market cache...")
researcher = MarketResearcher(str(CACHE_PATH))
cache = researcher._load_or_build_cache()
print(f"  Sale districts:  {len(cache.get('sale_district', {}))}")
print(f"  Sale states:     {len(cache.get('sale_state', {}))}")
print(f"  Rent districts:  {len(cache.get('rent_district', {}))}")
print(f"  Rent states:     {len(cache.get('rent_state', {}))}")

# ── Step 2: Scan vault for high-priority properties ────────────────────────────
print(f"\n[Step 2] Scanning vault for high-priority properties...")
writer = MDWriter(str(VAULT_PROPS))
high_priority = []

for md_file in sorted(VAULT_PROPS.glob("bn-*.md")):
    txt = md_file.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", txt, re.DOTALL)
    if not m:
        continue
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        continue
    bmv   = float(fm.get("bmv_pct", 0) or 0)
    count = int(fm.get("auction_count", 1) or 1)
    if bmv >= 29 or count >= 3:
        high_priority.append((md_file, fm))

print(f"  Found {len(high_priority)} high-priority properties")
print(f"  Processing first {min(MAX_TO_PROCESS, len(high_priority))} for this test run")

# ── Step 3: Enrich and re-write ────────────────────────────────────────────────
print(f"\n[Step 3] Enriching and writing notes...")
enriched_count  = 0
no_data_count   = 0
written_count   = 0
results = []

for md_file, fm in high_priority[:MAX_TO_PROCESS]:
    # Build a minimal listing dict from frontmatter
    listing = {
        "listing_id":    str(fm.get("bidnow_id", "")),
        "bmv_pct":       fm.get("bmv_pct", 0),
        "bmv_percent":   fm.get("bmv_pct", 0),
        "auction_count": fm.get("auction_count", 1),
        "state":         fm.get("state", ""),
        "city":          fm.get("city", ""),
        "built_up_sqft": fm.get("built_up_sqft", 0),
        "land_area_sqft":fm.get("land_area_sqft", 0),
        "reserve_price": fm.get("reserve_price", 0),
        # Pass through all existing fields so md_writer keeps them
        "full_address":  fm.get("address", ""),
        "property_type": fm.get("property_type", ""),
        "tenure":        fm.get("tenure", ""),
        "auction_type":  fm.get("auction_type", ""),
        "auction_date":  fm.get("auction_date", ""),
        "auction_time":  fm.get("auction_time", ""),
        "days_to_auction": fm.get("days_to_auction", 0),
        "market_value":  fm.get("market_value", 0),
        "original_reserve": fm.get("original_reserve", 0),
        "total_price_drop": fm.get("total_price_drop", 0),
        "bank":          fm.get("bank", ""),
        "lawyer":        fm.get("lawyer", ""),
        "auctioneer":    fm.get("auctioneer", ""),
        "borrower":      fm.get("borrower", ""),
        "deposit_pct":   fm.get("deposit_pct", 10),
        "deposit_amount":fm.get("deposit_amount", 0),
        "pos_file_path": fm.get("pos_file_path", ""),
        "pos_url":       fm.get("pos_url", ""),
        "llt_slug":      fm.get("llt_slug", ""),
        "llt_url":       fm.get("llt_url", ""),
        "url":           fm.get("source_bn", ""),
        "auction_history": fm.get("auction_history", []),
        "lat":           None, "lng": None,
        "district":      fm.get("city", ""),
        "region":        fm.get("region", ""),
        "restriction":   fm.get("restriction", ""),
        "tags":          fm.get("tags", []),
        # Preserve existing market fields if any
        "market_sale_psf":     fm.get("market_sale_psf"),
        "market_rent_psf":     fm.get("market_rent_psf"),
        "market_rent_est":     fm.get("market_rent_est"),
        "market_value_est":    fm.get("market_value_est"),
        "independent_bmv_pct": fm.get("independent_bmv_pct"),
        "est_rental_yield":    fm.get("est_rental_yield"),
        "market_comps_date":   fm.get("market_comps_date"),
        "market_comps_n":      fm.get("market_comps_n"),
        "market_source":       fm.get("market_source"),
        "market_area_match":   fm.get("market_area_match"),
    }

    state   = listing["state"]
    city    = listing["city"]
    sqft    = listing["built_up_sqft"] or listing["land_area_sqft"]
    reserve = listing["reserve_price"]

    mkt = researcher._lookup(cache, state, city, sqft, reserve)
    if mkt:
        listing.update(mkt)
        enriched_count += 1
        try:
            writer.write(listing, "update_price")
            written_count += 1
        except Exception as exc:
            print(f"  ERROR writing {md_file.name}: {exc}")
        results.append({
            "file":         md_file.name,
            "city":         city,
            "state":        state,
            "sqft":         sqft,
            "reserve":      reserve,
            "bmv_pct":      listing["bmv_pct"],
            "auction_count":listing["auction_count"],
            **mkt,
        })
    else:
        no_data_count += 1

# ── Step 4: Report ─────────────────────────────────────────────────────────────
print(f"\n  Enriched:  {enriched_count}")
print(f"  No data:   {no_data_count}")
print(f"  Written:   {written_count}")

print(f"\n[Step 4] Enrichment results (first 20):")
print(f"  {'File':15s} {'City':22s} {'Reserve':>12s} {'Market':>12s} {'Indep BMV':>10s} {'Yield':>7s} {'Rent/mo':>10s} {'Match':8s} n")
print("  " + "-" * 105)
for r in results[:20]:
    mv  = r.get("market_value_est")
    ibm = r.get("independent_bmv_pct")
    yld = r.get("est_rental_yield")
    rnt = r.get("market_rent_est")
    mc  = r.get("market_area_match", "?")
    n   = r.get("market_comps_n", 0)
    print(
        f"  {r['file']:15s} {(r['city'] or '—')[:21]:22s} "
        f"RM{r['reserve']:>9,.0f}  "
        f"RM{(mv or 0):>9,.0f}  "
        f"{(str(ibm)+'%' if ibm is not None else '—'):>10s}  "
        f"{(str(yld)+'%' if yld else '—'):>6s}  "
        f"{'RM '+str(rnt)+'/mo' if rnt else '—':>10s}  "
        f"{mc:8s} {n}"
    )

print(f"\n[Step 4] Properties with NO market data:")
no_data_samples = [(md_file.name, fm.get('city', ''), fm.get('state', ''))
                   for md_file, fm in high_priority[:MAX_TO_PROCESS]
                   if not any(r['file'] == md_file.name for r in results)][:10]
for name, city, state in no_data_samples:
    print(f"  {name:15s} {city[:25]:26s} {state}")

print(f"\n{'='*65}")
print(f"  E2E test complete. {written_count} notes updated in vault.")
print(f"  Open Dashboard.md in Obsidian to see market columns.")
print(f"  Enable 'Only enriched' checkbox to filter to enriched properties.")
print(f"{'='*65}\n")
