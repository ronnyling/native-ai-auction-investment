import sys, io, re, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
    'Accept-Language': 'en-MY,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
    'Referer': 'https://elelong.kehakiman.gov.my/BidderWeb/Home/Index',
}
BASE = 'https://elelong.kehakiman.gov.my'

def get(url, t=25, extra=None):
    headers = dict(H)
    if extra:
        headers.update(extra)
    try:
        r = requests.get(url, headers=headers, timeout=t, allow_redirects=True)
        return r
    except Exception as e:
        print(f'  ERROR: {e}')
        return None

def post(url, data=None, t=25):
    try:
        r = requests.post(url, headers=H, data=data or {}, timeout=t, allow_redirects=True)
        return r
    except Exception as e:
        print(f'  ERROR: {e}')
        return None

# ── Step 1: Read the bidder JS bundle to find API endpoints
print('=== STEP 1: Scan JS bundle for API endpoints ===')
r = get(BASE + '/BidderWeb/bundles/ecourt/elelong/bidder', t=30)
if r and r.status_code == 200:
    js = r.text
    print(f'Bundle size: {len(js)} chars')
    # Find URL patterns
    urls = re.findall(r'["\'](/BidderWeb/[A-Za-z][^"\'<>\s]{3,80})["\']', js)
    urls = list(set(u for u in urls if not u.endswith('.js') and not u.endswith('.css')))
    print(f'URLs in bundle ({len(urls)}):')
    for u in sorted(urls)[:40]:
        print(f'  {u}')
    # Look for AJAX / $.ajax / fetch / axios patterns
    ajax_patterns = re.findall(r'url\s*[:=]\s*["\']([^"\']{5,80})["\']', js)
    print(f'AJAX url= patterns ({len(ajax_patterns)}):')
    for u in list(set(ajax_patterns))[:20]:
        print(f'  {u}')
    # Controller/action patterns
    controllers = re.findall(r'/BidderWeb/(\w+)/(\w+)', js)
    print(f'Controller/action pairs: {list(set(controllers))[:30]}')
else:
    print(f'  bundle fetch failed: {r.status_code if r else "no response"}')

time.sleep(2)

# ── Step 2: Probe likely auction list endpoints directly
print('\n=== STEP 2: Probe auction list endpoints ===')
endpoints = [
    '/BidderWeb/Home/GetAuctions',
    '/BidderWeb/Home/GetAllAuctions',
    '/BidderWeb/Home/AuctionData',
    '/BidderWeb/Home/LoadAuctions',
    '/BidderWeb/Home/SearchAuctions',
    '/BidderWeb/Home/GetProperties',
    '/BidderWeb/Auction/GetAuctions',
    '/BidderWeb/Auction/List',
    '/BidderWeb/Auction/Search',
    '/BidderWeb/Auction/GetAll',
    '/BidderWeb/Auction/GetList',
    '/BidderWeb/Property/GetProperties',
    '/BidderWeb/Property/Search',
    '/BidderWeb/Home/Index?state=Selangor',
]

for ep in endpoints:
    url = BASE + ep
    # Try GET first
    r = get(url, t=10)
    if r:
        ct = r.headers.get('Content-Type', '')
        print(f'  GET {ep}: status={r.status_code} ct={ct[:40]} bytes={len(r.content)}')
        if r.status_code == 200:
            if 'json' in ct:
                try:
                    d = r.json()
                    print(f'    JSON: {str(d)[:300]}')
                except:
                    print(f'    body: {r.text[:200]}')
            elif len(r.content) > 500:
                soup = BeautifulSoup(r.text, 'html.parser')
                print(f'    text: {soup.get_text(" ", strip=True)[:200]}')
    else:
        print(f'  GET {ep}: TIMEOUT/ERROR')
    time.sleep(0.8)

# ── Step 3: Try POST to common search endpoints
print('\n=== STEP 3: POST search ===')
post_endpoints = [
    '/BidderWeb/Home/GetAuctions',
    '/BidderWeb/Home/Index',
    '/BidderWeb/Auction/Search',
]
search_data = {
    'state': 'Selangor',
    'State': 'Selangor',
    'page': '1',
    'pageSize': '10',
    'landUsed': '',
    'tenure': '',
}
for ep in post_endpoints:
    r2 = post(BASE + ep, search_data, t=15)
    if r2:
        ct = r2.headers.get('Content-Type', '')
        print(f'  POST {ep}: status={r2.status_code} ct={ct[:40]} bytes={len(r2.content)}')
        if r2.status_code == 200 and len(r2.content) > 100:
            if 'json' in ct:
                try:
                    d = r2.json()
                    print(f'    JSON: {str(d)[:300]}')
                except:
                    print(f'    body: {r2.text[:200]}')
            else:
                soup = BeautifulSoup(r2.text, 'html.parser')
                print(f'    text: {soup.get_text(" ", strip=True)[:300]}')
    else:
        print(f'  POST {ep}: TIMEOUT/ERROR')
    time.sleep(1)

# ── Step 4: Look at the Layout JS for clues
print('\n=== STEP 4: Layout.js ===')
r = get(BASE + '/BidderWeb/Scripts/Shared/Layout.js', t=15)
if r and r.status_code == 200:
    print(r.text[:2000])
else:
    print(f'  status={r.status_code if r else "no resp"}')

print('\n=== DONE ===')
