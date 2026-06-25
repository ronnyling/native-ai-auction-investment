"""Quick E2E test for elelong.py — SearchAuction-based discovery."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')
from elelong import ELelongScraper

# First run: no prev state → full scrape of KL + Selangor only (faster test)
s = ELelongScraper()
listings, search_state = s.scrape_listings(
    known_slugs=set(),
    prev_search_state={},
    states=["Kuala Lumpur", "Selangor"],
    max_listings=10,
)

print(f"\n{'='*60}")
print(f"  e-Lelong E2E Test — {len(listings)} listings scraped")
print(f"{'='*60}\n")

for i, l in enumerate(listings):
    print(f"[{i+1}] ID={l['listing_id']} date={l['auction_date']}")
    print(f"     addr   : {l['full_address'][:80]}")
    print(f"     state  : {l['state']} | city: {l['district']}")
    print(f"     type   : {l['property_type']} | tenure: {l['tenure']}")
    print(f"     reserve: RM {l['reserve_price']:,} | deposit: RM {l['deposit_amount']:,} ({l['deposit_pct']}%)")
    print(f"     bank   : {l['bank']}")
    print(f"     case#  : {l['case_number']}")
    print(f"     title# : {l['title_number']}")
    print(f"     sqft   : built_up={l['built_up_sqft']} land={l['land_area_sqft']}")
    print(f"     restrict: {l['restriction']}")
    if l.get('encumbrances'):
        print(f"     encumb : {l['encumbrances'][:120]}")
    if l.get('pos_url'):
        print(f"     pos    : {l['pos_url'][:80]}")
    print()

# Summary stats
states = {}
types = {}
for l in listings:
    states[l['state']] = states.get(l['state'], 0) + 1
    types[l['property_type']] = types.get(l['property_type'], 0) + 1

print(f"By state  : {dict(sorted(states.items(), key=lambda x:-x[1]))}")
print(f"By type   : {dict(sorted(types.items(), key=lambda x:-x[1]))}")

has_encumb = sum(1 for l in listings if l.get('encumbrances'))
has_pos    = sum(1 for l in listings if l.get('pos_url'))
print(f"Has encumbrances : {has_encumb}/{len(listings)}")
print(f"Has POS URL      : {has_pos}/{len(listings)}")

# Delta test: second run with same state → should skip all states
print(f"\n{'='*60}")
print("  Delta test: second run with same search_state")
print(f"{'='*60}")
listings2, state2 = s.scrape_listings(
    known_slugs=set(),
    prev_search_state=search_state,
    states=["Kuala Lumpur", "Selangor"],
    max_listings=10,
)
print(f"  Second run listings: {len(listings2)}  (expected 0 — all states unchanged)")
