import sys, io, re, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

H = {'User-Agent': 'Mozilla/5.0 Chrome/125', 'Accept-Language': 'en-MY,en;q=0.9'}
r = requests.get('https://elelong.kehakiman.gov.my/BidderWeb/bundles/ecourt/elelong/bidder', headers=H, timeout=30)
js = r.text
print('Bundle size:', len(js))

# Look for AJAX-related keyword occurrences
keywords = ['ajax', 'fetch', 'XMLHttp', 'getJSON', 'Home/', 'Auction/', 'Property/',
            'GetAll', 'GetList', 'Search', 'GetData', 'LoadData', 'AjaxUrl', 'dataUrl',
            'listUrl', 'controller', 'action', 'url:', 'url =', 'dataTableUrl',
            'ecourt', 'elelong', 'BidderWeb', 'auction', 'property', 'listing']

print('\n--- Keyword grep in bundle ---')
for kw in keywords:
    positions = [m.start() for m in re.finditer(re.escape(kw), js, re.IGNORECASE)]
    if positions:
        print(f'\n  [{kw}] — {len(positions)} hits:')
        for pos in positions[:4]:
            snippet = js[max(0, pos-60):pos+120].replace('\n', ' ')
            print(f'    ...{snippet}...')

# All unique string literals containing slash
print('\n--- Slash-path string literals ---')
strings = re.findall(r'["\']/([\w/\-_]{5,80})["\']', js)
for s in sorted(set(strings))[:50]:
    print(f'  /{s}')

# Look at first 3000 chars and last 3000 chars for initialization code
print('\n--- First 2000 chars of bundle ---')
print(js[:2000])
print('\n--- Last 2000 chars of bundle ---')
print(js[-2000:])
