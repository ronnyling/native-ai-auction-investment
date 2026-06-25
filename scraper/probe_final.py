import requests, re, json, time, sys

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept-Language': 'en-MY,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
}

def extract_listings(html):
    listings, seen = [], set()
    for m in re.finditer(r'"listingData":\{', html):
        start = m.start() + len('"listingData":')
        depth, end = 0, start
        for i in range(start, min(start + 20000, len(html))):
            if html[i] == '{': depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0: end = i + 1; break
        try:
            obj = json.loads(html[start:end])
            lid = obj.get('id') or obj.get('externalId')
            if lid and lid not in seen:
                seen.add(lid)
                listings.append(obj)
        except Exception:
            pass
    return listings

def parse_psf(l):
    t = l.get('psfText', '') or ''
    m = re.search(r'[\d,]+\.?\d*', t.replace(',', ''))
    return float(m.group()) if m else None

def parse_price(l):
    p = l.get('price', {})
    v = p.get('value') if isinstance(p, dict) else p
    return v if v and v > 0 else None

def parse_sqft(l):
    return l.get('floorArea') or None

def get_area(l):
    ad = l.get('additionalData', {}) or {}
    district = (ad.get('districtText') or '').strip()
    region = (ad.get('regionText') or '').strip()
    return district, region

# Scrape 5 pages of sale and 5 pages of rent, collect all listings with district data
print("Scraping iProperty national listings (5 pages sale + 5 pages rent)...")
sale_listings, rent_listings = [], []

for page in range(1, 6):
    url = f'https://www.iproperty.com.my/property-for-sale?page={page}'
    r = requests.get(url, headers=headers, timeout=20)
    ls = extract_listings(r.text)
    sale_listings.extend(ls)
    sys.stdout.write(f"  Sale page {page}: {len(ls)} listings\n"); sys.stdout.flush()
    time.sleep(1.2)

for page in range(1, 6):
    url = f'https://www.iproperty.com.my/property-for-rent?page={page}'
    r = requests.get(url, headers=headers, timeout=20)
    ls = extract_listings(r.text)
    rent_listings.extend(ls)
    sys.stdout.write(f"  Rent page {page}: {len(ls)} listings\n"); sys.stdout.flush()
    time.sleep(1.2)

# Build district-level PSF map from sale
sale_by_district = {}
sale_by_state = {}
for l in sale_listings:
    psf = parse_psf(l)
    if not psf: continue
    district, region = get_area(l)
    if district:
        sale_by_district.setdefault(district.lower(), []).append(psf)
    if region:
        sale_by_state.setdefault(region.lower(), []).append(psf)

# Build district-level rent/sqft from rent listings
rent_by_district = {}
rent_by_state = {}
for l in rent_listings:
    price = parse_price(l)
    sqft = parse_sqft(l)
    if not price or not sqft or sqft < 100: continue
    rent_psf = price / sqft
    district, region = get_area(l)
    if district:
        rent_by_district.setdefault(district.lower(), []).append(rent_psf)
    if region:
        rent_by_state.setdefault(region.lower(), []).append(rent_psf)

def median(vals):
    v = sorted([x for x in vals if x > 0])
    if not v: return None
    mid = len(v) // 2
    return round(v[mid] if len(v) % 2 else (v[mid-1] + v[mid]) / 2, 2)

print(f"\nSale by district ({len(sale_by_district)} unique districts):")
for d, vals in sorted(sale_by_district.items(), key=lambda x: -len(x[1]))[:15]:
    print(f"  {d:30s} n={len(vals):3d}  median_psf=RM {median(vals):,.2f}")

print(f"\nSale by state ({len(sale_by_state)} unique states):")
for s, vals in sorted(sale_by_state.items(), key=lambda x: -len(x[1]))[:15]:
    print(f"  {s:30s} n={len(vals):3d}  median_psf=RM {median(vals):,.2f}")

print(f"\nRent by district ({len(rent_by_district)} unique districts):")
for d, vals in sorted(rent_by_district.items(), key=lambda x: -len(x[1]))[:15]:
    print(f"  {d:30s} n={len(vals):3d}  median_rent_psf=RM {median(vals):.3f}/sqft/mo")

print(f"\nRent by state ({len(rent_by_state)} unique states):")
for s, vals in sorted(rent_by_state.items(), key=lambda x: -len(x[1]))[:15]:
    print(f"  {s:30s} n={len(vals):3d}  median_rent_psf=RM {median(vals):.3f}/sqft/mo")

# Save the raw cache for inspection
cache = {
    'sale_district': {k: {'psf_vals': v, 'median_psf': median(v), 'n': len(v)} for k, v in sale_by_district.items()},
    'sale_state':    {k: {'psf_vals': v, 'median_psf': median(v), 'n': len(v)} for k, v in sale_by_state.items()},
    'rent_district': {k: {'rent_psf_vals': v, 'median_rent_psf': median(v), 'n': len(v)} for k, v in rent_by_district.items()},
    'rent_state':    {k: {'rent_psf_vals': v, 'median_rent_psf': median(v), 'n': len(v)} for k, v in rent_by_state.items()},
}
with open('market_cache_probe.json', 'w') as f:
    json.dump(cache, f, indent=2)
print(f"\nSaved to market_cache_probe.json")

# Test lookup for specific properties
print("\n=== Simulated lookup for sample properties ===")
test_props = [
    ('Selangor', 'Puchong', 'apartment', 850),
    ('Kuala Lumpur', 'KLCC', 'condo', 1000),
    ('Penang', 'Georgetown', 'apartment', 700),
    ('Johor', 'Johor Bahru', 'terrace', 1500),
]
for state, city, ptype, sqft in test_props:
    d_key = city.lower()
    s_key = state.lower()
    sale_psf = None
    rent_psf = None
    match_level = 'none'
    
    if d_key in sale_by_district and len(sale_by_district[d_key]) >= 2:
        sale_psf = median(sale_by_district[d_key])
        match_level = 'district'
    elif s_key in sale_by_state:
        sale_psf = median(sale_by_state[s_key])
        match_level = 'state'
    
    if d_key in rent_by_district and len(rent_by_district[d_key]) >= 2:
        rent_psf = median(rent_by_district[d_key])
    elif s_key in rent_by_state:
        rent_psf = median(rent_by_state[s_key])
    
    if sale_psf:
        market_val = sale_psf * sqft
        rent_est = (rent_psf or 0) * sqft
        print(f"\n  {state} · {city} ({ptype}, {sqft} sqft) [{match_level}]")
        print(f"    Sale PSF:      RM {sale_psf:,.2f}/sqft")
        print(f"    Market Value:  RM {market_val:,.0f}")
        print(f"    Rent PSF:      RM {rent_psf:.3f}/sqft/mo" if rent_psf else "    Rent PSF:     N/A")
        print(f"    Est. Rent:     RM {rent_est:,.0f}/mo" if rent_psf else "")
        if rent_psf:
            yield_pct = (rent_psf * 12 / sale_psf) * 100
            print(f"    Est. Yield:    {yield_pct:.1f}%")
    else:
        print(f"\n  {state} · {city}: no data found")
