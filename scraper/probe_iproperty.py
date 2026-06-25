import requests, re, json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36',
    'Accept-Language': 'en-MY,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
}

# Test 1: iProperty sale search
url = 'https://www.iproperty.com.my/sale/puchong/apartment-condo/'
r = requests.get(url, headers=headers, timeout=20)
print('=== iProperty sale page ===')
print('Status:', r.status_code)
print('Content-Length:', len(r.text))

# __NEXT_DATA__
pat = r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>'
m = re.search(pat, r.text, re.DOTALL)
if m:
    data = json.loads(m.group(1))
    print('__NEXT_DATA__ found, top-level keys:', list(data.keys()))
    # Dig into props.pageProps
    page_props = data.get('props', {}).get('pageProps', {})
    print('pageProps keys:', list(page_props.keys())[:20])
    # Find listing data
    txt = json.dumps(page_props)
    prices = re.findall(r'"price":\s*(\d+)', txt)[:10]
    print('Sample prices:', prices)
    psf_vals = re.findall(r'"pricePerSqft":\s*([\d.]+)', txt)[:10]
    print('Sample PSF values:', psf_vals)
    # Save snippet for inspection
    with open('iproperty_sample.json', 'w') as f:
        json.dump(page_props, f, indent=2)
    print('Saved pageProps to iproperty_sample.json')
else:
    print('No __NEXT_DATA__ found')
    # Look for other patterns
    for pat in ['initialData', 'listingData', '__APOLLO_STATE__', 'searchResults']:
        if pat in r.text:
            idx = r.text.find(pat)
            print(f'Found pattern: {pat} at index {idx}')
            print('Snippet:', r.text[idx:idx+200])
    # Save raw HTML for inspection
    with open('iproperty_raw.html', 'w', encoding='utf-8') as f:
        f.write(r.text[:50000])
    print('Saved first 50KB of HTML to iproperty_raw.html')

print()

# Test 2: iProperty rental search
url2 = 'https://www.iproperty.com.my/rent/puchong/apartment-condo/'
r2 = requests.get(url2, headers=headers, timeout=20)
print('=== iProperty rent page ===')
print('Status:', r2.status_code)
m2 = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r2.text, re.DOTALL)
if m2:
    data2 = json.loads(m2.group(1))
    pp2 = data2.get('props', {}).get('pageProps', {})
    txt2 = json.dumps(pp2)
    rents = re.findall(r'"price":\s*(\d+)', txt2)[:10]
    print('Sample rents:', rents)
    psf2 = re.findall(r'"pricePerSqft":\s*([\d.]+)', txt2)[:10]
    print('Sample rent PSF:', psf2)
else:
    print('No __NEXT_DATA__ in rent page')
