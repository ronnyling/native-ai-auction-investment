import requests, re, json, time

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
    m = re.search(r'[\d,.]+', t.replace(',', ''))
    return float(m.group()) if m else None

def parse_price(l):
    p = l.get('price', {})
    v = p.get('value') if isinstance(p, dict) else p
    return v if v and v > 0 else None

def parse_sqft(l):
    return l.get('floorArea') or None

def median(vals):
    v = sorted([x for x in vals if x and x > 0])
    if not v: return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid-1] + v[mid]) / 2

print("=== Test 1: iProperty pagination (does page 2 differ?) ===")
for pg in [1, 2, 3]:
    url = f'https://www.iproperty.com.my/sale/selangor/apartment-condo/?page={pg}'
    r = requests.get(url, headers=headers, timeout=20)
    ls = extract_listings(r.text)
    prices = [parse_price(l) for l in ls]
    ids = [l.get('id') for l in ls]
    print(f"  Page {pg}: {len(ls)} unique listings, IDs: {ids[:5]}, Prices: {prices[:5]}")
    time.sleep(1)

print()
print("=== Test 2: EdgeProp area stats ===")
# EdgeProp has dedicated market stats pages
edgeprop_urls = [
    ('Puchong', 'https://www.edgeprop.my/area/47100'),
    ('Shah Alam', 'https://www.edgeprop.my/area/40150'),
    ('Selangor overview', 'https://www.edgeprop.my/area/selangor'),
]
for label, url in edgeprop_urls:
    try:
        r = requests.get(url, headers=headers, timeout=20)
        print(f"  {label}: status={r.status_code}, len={len(r.text)}")
        # Look for PSF/price data patterns
        for pat in [r'"medianPsf":\s*([\d.]+)', r'"medianPrice":\s*([\d.]+)',
                    r'median.*?RM\s*([\d,]+)', r'RM\s*([\d,]+)\s*(?:psf|per sqft)']:
            found = re.findall(pat, r.text, re.IGNORECASE)[:3]
            if found: print(f"    Pattern '{pat}': {found}")
        # Check for embedded JSON
        for jskey in ['__NEXT_DATA__', 'window.__data', 'initialData', 'areaData']:
            if jskey in r.text:
                idx = r.text.index(jskey)
                print(f"    JS key: {jskey} at {idx}")
    except Exception as e:
        print(f"  {label}: ERROR {e}")
    time.sleep(1)

print()
print("=== Test 3: PropertyGuru area-level market stats ===")
pg_urls = [
    ('PG Puchong apt sale', 'https://www.propertyguru.com.my/property-for-sale?freetext=Puchong&property_type=N&property_type_code=APT'),
    ('PG Selangor', 'https://www.propertyguru.com.my/property-for-sale?market=residential&region_code=selangor'),
]
for label, url in pg_urls:
    try:
        r = requests.get(url, headers=headers, timeout=20)
        print(f"  {label}: status={r.status_code}, len={len(r.text)}")
        # Check for Next.js data
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            pp = data.get('props', {}).get('pageProps', {})
            txt = json.dumps(pp)
            prices = re.findall(r'"price":\s*(\d{4,})', txt)[:5]
            print(f"    __NEXT_DATA__ found; sample prices: {prices}")
        else:
            print(f"    No __NEXT_DATA__")
            for pat in ['listingData', 'propertyData', 'searchResults']:
                if pat in r.text: print(f"    Found: {pat}")
    except Exception as e:
        print(f"  {label}: ERROR {e}")
    time.sleep(1)
