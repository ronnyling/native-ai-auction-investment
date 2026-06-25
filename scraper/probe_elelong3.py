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
    'X-Requested-With': 'XMLHttpRequest',
}
BASE = 'https://elelong.kehakiman.gov.my'

def get(url, t=25, extra=None, xhr=False):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
        'Accept-Language': 'en-MY,en;q=0.9',
        'Referer': 'https://elelong.kehakiman.gov.my/BidderWeb/Home/Index',
    }
    if xhr:
        headers['X-Requested-With'] = 'XMLHttpRequest'
        headers['Accept'] = 'application/json, text/javascript, */*; q=0.01'
    if extra:
        headers.update(extra)
    try:
        r = requests.get(url, headers=headers, timeout=t, allow_redirects=True)
        return r
    except Exception as e:
        print(f'  ERROR: {e}')
        return None

def post_xhr(url, data=None, t=25):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
        'Accept-Language': 'en-MY,en;q=0.9',
        'Referer': 'https://elelong.kehakiman.gov.my/BidderWeb/Home/Index',
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    try:
        r = requests.post(url, headers=headers, data=data or {}, timeout=t, allow_redirects=True)
        return r
    except Exception as e:
        print(f'  ERROR: {e}')
        return None

# ── Step 1: Parse the home page HTML structure thoroughly
print('=== STEP 1: Deep-parse home page HTML ===')
r = get(BASE + '/BidderWeb/Home/Index')
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, 'html.parser')
    print(f'Status={r.status_code} Bytes={len(r.content)}')
    
    # Find ALL tables
    tables = soup.find_all('table')
    print(f'Tables: {len(tables)}')
    for i, t in enumerate(tables):
        rows = t.find_all('tr')
        print(f'  Table {i}: {len(rows)} rows')
        for row in rows[:5]:
            cells = [td.get_text(strip=True) for td in row.find_all(['td','th'])]
            if cells:
                print(f'    {cells}')
    
    # Find ALL divs with data
    divs_with_id = [(d.get('id',''), d.get('class',''), d.get_text(strip=True)[:80]) for d in soup.find_all('div') if d.get('id') or (d.get('class') and any('result' in c.lower() or 'listing' in c.lower() or 'auction' in c.lower() or 'item' in c.lower() or 'row' in ' '.join(d.get('class',[])).lower() for c in (d.get('class') or [])))]
    print(f'Relevant divs: {len(divs_with_id)}')
    for d in divs_with_id[:20]:
        print(f'  id={d[0]} class={d[1]} text={d[2]}')
    
    # Find data embedded in script tags
    scripts = soup.find_all('script')
    for i, s in enumerate(scripts):
        if s.string and len(s.string) > 50 and 'WhereAmI' not in s.string and 'SharedLayout' not in s.string:
            print(f'  Inline script {i} ({len(s.string)} chars):')
            print(f'    {s.string[:600]}')
    
    # Save full HTML for manual inspection
    with open('elelong_home.html', 'w', encoding='utf-8') as f:
        f.write(r.text)
    print('  Full HTML saved to elelong_home.html')

time.sleep(2)

# ── Step 2: Try XHR requests that DataTables / jQuery might use
print('\n=== STEP 2: XHR / DataTables endpoint probes ===')
# Common DataTables server-side URL patterns
dt_endpoints = [
    '/BidderWeb/Home/GetAuctionData',
    '/BidderWeb/Home/AuctionListData',
    '/BidderWeb/Home/IndexData',
    '/BidderWeb/Home/GetListings',
    '/BidderWeb/Home/GetData',
    '/BidderWeb/Home/GetAuctionList',
    '/BidderWeb/Home/AuctionJson',
    '/BidderWeb/Home/DataTable',
    '/BidderWeb/Home/AjaxList',
    '/BidderWeb/api/auctions',
    '/api/auctions',
    '/api/listings',
    '/BidderWeb/Home/TableData',
    '/BidderWeb/Home/AllAuctions',
]
for ep in dt_endpoints:
    r2 = get(BASE + ep, t=10, xhr=True)
    if r2:
        ct = r2.headers.get('Content-Type', '')
        print(f'  GET(xhr) {ep}: status={r2.status_code} ct={ct[:50]} bytes={len(r2.content)}')
        if r2.status_code == 200 and len(r2.content) > 100:
            if 'json' in ct:
                print(f'    JSON: {r2.text[:400]}')
            else:
                soup2 = BeautifulSoup(r2.text, 'html.parser')
                t2 = soup2.get_text(' ', strip=True)
                if t2:
                    print(f'    text: {t2[:300]}')
    else:
        print(f'  GET(xhr) {ep}: NO RESPONSE')
    time.sleep(0.5)

# ── Step 3: Try state-filtered pages and look for embedded data
print('\n=== STEP 3: State-filtered pages parse ===')
for state_param in ['Selangor', 'WP+Kuala+Lumpur', 'Johor']:
    url = f'{BASE}/BidderWeb/Home/Index?state={state_param}'
    r3 = get(url, t=20)
    if r3 and r3.status_code == 200:
        soup3 = BeautifulSoup(r3.text, 'html.parser')
        text = soup3.get_text(' ', strip=True)
        print(f'  state={state_param}: bytes={len(r3.content)}')
        # Look for prices / property data
        prices = re.findall(r'RM\s*[\d,]+', text)
        dates = re.findall(r'\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}', text)
        addresses = re.findall(r'(?:Lot|No\.|Jalan|Persiaran|Taman)[^\n,]{5,60}', text)[:5]
        print(f'    prices={prices[:5]} dates={dates[:5]} addresses={addresses[:3]}')
        # Find rows/items more aggressively
        items = soup3.find_all(class_=re.compile(r'row|item|card|list|auction|prop', re.I))
        print(f'    div items found: {len(items)}')
        for it in items[:5]:
            t_i = it.get_text(' ', strip=True)
            if len(t_i) > 20:
                print(f'      {t_i[:150]}')
    time.sleep(2)

# ── Step 4: Check XHR with POST and DataTables draw parameter
print('\n=== STEP 4: POST with DataTables params ===')
dt_params = {
    'draw': '1',
    'start': '0',
    'length': '10',
    'state': '',
    'landUsed': '',
    'tenure': '',
    'auctionDateFrom': '',
    'auctionDateTo': '',
    'propertyAddress': '',
    'reservedPriceRange': '',
    'restrictionInInterest': '',
}
for ep in ['/BidderWeb/Home/Index', '/BidderWeb/Home/GetAuctions', '/BidderWeb/Home/AuctionList']:
    r4 = post_xhr(BASE + ep, dt_params, t=15)
    if r4:
        ct = r4.headers.get('Content-Type', '')
        print(f'  POST {ep}: status={r4.status_code} ct={ct[:50]} bytes={len(r4.content)}')
        if r4.status_code == 200 and len(r4.content) > 100:
            if 'json' in ct:
                print(f'    JSON: {r4.text[:400]}')
            else:
                soup4 = BeautifulSoup(r4.text, 'html.parser')
                print(f'    text: {soup4.get_text(" ",strip=True)[:300]}')
    else:
        print(f'  POST {ep}: NO RESPONSE')
    time.sleep(1)

print('\n=== DONE ===')
