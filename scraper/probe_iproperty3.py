import requests, re, json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept-Language': 'en-MY,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
}

def extract_listings(html):
    listings = []
    for m in re.finditer(r'"listingData":\{', html):
        start = m.start() + len('"listingData":')
        depth = 0
        end = start
        for i in range(start, min(start + 20000, len(html))):
            if html[i] == '{': depth += 1
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

def parse_psf(listing):
    """Extract PSF from psfText field e.g. 'RM 1,361.39 psf'"""
    psf_text = listing.get('psfText', '') or ''
    m = re.search(r'[\d,]+\.?\d*', psf_text.replace(',', ''))
    return float(m.group()) if m else None

def parse_price(listing):
    p = listing.get('price', {})
    if isinstance(p, dict):
        return p.get('value') or 0
    return p or 0

def parse_sqft(listing):
    return listing.get('floorArea') or 0

def median(vals):
    v = [x for x in vals if x and x > 0]
    if not v: return None
    v.sort()
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid-1] + v[mid]) / 2

# Test URL patterns for state-level search
test_cases = [
    ('Selangor', 'apartment', 'https://www.iproperty.com.my/sale/selangor/apartment-condo/'),
    ('Selangor rent', 'apartment', 'https://www.iproperty.com.my/rent/selangor/apartment-condo/'),
    ('Selangor', 'terrace', 'https://www.iproperty.com.my/sale/selangor/terrace-house/'),
    ('KL', 'apartment', 'https://www.iproperty.com.my/sale/kuala-lumpur/apartment-condo/'),
]

for label, ptype, url in test_cases:
    r = requests.get(url, headers=headers, timeout=20)
    listings = extract_listings(r.text)
    prices = [parse_price(l) for l in listings]
    psfs = [parse_psf(l) for l in listings]
    sqfts = [parse_sqft(l) for l in listings]
    
    # Deduplicate (iProperty embeds each listing twice)
    ids_seen = set()
    unique_listings = []
    for l in listings:
        lid = l.get('id') or l.get('externalId')
        if lid not in ids_seen:
            ids_seen.add(lid)
            unique_listings.append(l)
    
    psfs_clean = [parse_psf(l) for l in unique_listings]
    prices_clean = [parse_price(l) for l in unique_listings]
    
    print(f"\n{label} [{ptype}] - {url}")
    print(f"  Total blocks: {len(listings)} -> Unique: {len(unique_listings)}")
    print(f"  Prices (unique): {prices_clean[:8]}")
    print(f"  PSFs (unique):   {[p for p in psfs_clean if p][:8]}")
    print(f"  Median price: RM {median(prices_clean):,.0f}" if median(prices_clean) else "  No median price")
    print(f"  Median PSF:   RM {median(psfs_clean):,.2f}" if median(psfs_clean) else "  No median PSF")
