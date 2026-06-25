import requests, re, json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept-Language': 'en-MY,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
}

def extract_listing_data(html):
    """Extract all listingData JSON objects from iProperty HTML."""
    # iProperty embeds data as: "listingData":{...} inside a larger JS object
    listings = []
    for m in re.finditer(r'"listingData":\{', html):
        start = m.start() + len('"listingData":')
        depth = 0
        end = start
        for i in range(start, min(start + 20000, len(html))):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            obj = json.loads(html[start:end])
            listings.append(obj)
        except Exception:
            pass
    return listings

def get_median_price(listings, field='price'):
    vals = [l.get(field) for l in listings if isinstance(l.get(field), (int, float)) and l.get(field, 0) > 0]
    if not vals:
        return None
    vals.sort()
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid-1] + vals[mid]) / 2

# ── Sale page ─────────────────────────────────────────────────────────────────
url = 'https://www.iproperty.com.my/sale/puchong/apartment-condo/'
r = requests.get(url, headers=headers, timeout=20)
print('=== Sale page status:', r.status_code, '===')

listings = extract_listing_data(r.text)
print(f'Found {len(listings)} listingData blocks')

if listings:
    sample = listings[0]
    print('Sample listing keys:', list(sample.keys())[:30])
    print('Sample price:', sample.get('price'))
    print('Sample sqft:', sample.get('buildUpSize') or sample.get('builtUpSize') or sample.get('floorSize'))
    print('Sample PSF:', sample.get('pricePerSqft') or sample.get('psf'))
    print('Sample title:', sample.get('title') or sample.get('name'))
    print('Sample location:', sample.get('location') or sample.get('area') or sample.get('district'))
    # Save one full listing for inspection
    with open('iproperty_listing_sample.json', 'w') as f:
        json.dump(sample, f, indent=2)
    print('Saved sample to iproperty_listing_sample.json')

    prices = [l.get('price', 0) for l in listings if l.get('price')]
    print(f'\nPrices found: {prices[:10]}')
    median_p = get_median_price(listings, 'price')
    print(f'Median sale price (Puchong apts): RM {median_p:,.0f}' if median_p else 'No median')

    # Check PSF field name
    for key in ['pricePerSqft', 'psf', 'pricePersqft', 'price_per_sqft']:
        vals = [l.get(key) for l in listings if l.get(key)]
        if vals:
            print(f'PSF field "{key}": sample values {vals[:5]}')

# Also check if there's a summary stats block (avg, median from iProperty itself)
# Look for "averagePrice", "medianPrice" etc in raw HTML
for pattern in [r'"medianPrice":\s*([\d.]+)', r'"averagePrice":\s*([\d.]+)', r'"averagePsf":\s*([\d.]+)']:
    found = re.findall(pattern, r.text)[:5]
    if found:
        print(f'Pattern {pattern}: {found}')

# ── Rental page ───────────────────────────────────────────────────────────────
print('\n=== Rent page ===')
url2 = 'https://www.iproperty.com.my/rent/puchong/apartment-condo/'
r2 = requests.get(url2, headers=headers, timeout=20)
print('Status:', r2.status_code)

listings2 = extract_listing_data(r2.text)
print(f'Found {len(listings2)} listingData blocks')
if listings2:
    rents = [l.get('price', 0) for l in listings2 if l.get('price')]
    print(f'Rent prices: {rents[:10]}')
    median_r = get_median_price(listings2, 'price')
    print(f'Median rent (Puchong apts): RM {median_r:,.0f}' if median_r else 'No median')
    sqft_key = next((k for k in ['buildUpSize','builtUpSize','floorSize','size'] if listings2[0].get(k)), None)
    print(f'Sqft key: {sqft_key}')
    if sqft_key:
        sqfts = [l.get(sqft_key, 0) for l in listings2 if l.get(sqft_key)]
        print(f'Sqft samples: {sqfts[:5]}')

# ── Test postcode-based search ─────────────────────────────────────────────────
print('\n=== Postcode search test ===')
# Try searching by postcode directly (more accurate for our use case)
url3 = 'https://www.iproperty.com.my/sale/?q=47100'
r3 = requests.get(url3, headers=headers, timeout=20)
print('Status:', r3.status_code, 'Length:', len(r3.text))
l3 = extract_listing_data(r3.text)
print(f'Listings found for postcode 47100: {len(l3)}')
if l3:
    print('Sample:', {k: l3[0].get(k) for k in ['price','title','area','district']})
