import sys, io, re, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import requests
from bs4 import BeautifulSoup

H = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36',
    'Accept-Language': 'en-MY,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8',
}
BASE = 'https://elelong.kehakiman.gov.my'

def get(url, t=25):
    try:
        r = requests.get(url, headers=H, timeout=t, allow_redirects=True)
        return r
    except Exception as e:
        print(f'  ERROR: {e}')
        return None

# ── Home page
print('=== HOME ===')
r = get(BASE + '/BidderWeb/Home/Index')
if r:
    soup = BeautifulSoup(r.text, 'html.parser')
    print(f'Status={r.status_code} Bytes={len(r.content)}')
    print('Title:', soup.title.string if soup.title else 'none')
    text = soup.get_text(' ', strip=True)
    print('Text:', text[:1000])
    links = [(a.get_text(strip=True)[:50], a['href']) for a in soup.find_all('a', href=True) if a.get_text(strip=True)]
    print('Links:')
    for l in links[:30]:
        print(' ', l)
    forms = soup.find_all('form')
    print(f'Forms: {len(forms)}')
    for f in forms[:5]:
        print(f'  action={f.get("action","")} method={f.get("method","")}')
    scripts_src = [s.get('src','') for s in soup.find_all('script', src=True)]
    print('Script srcs:', scripts_src[:8])
    inline = ' '.join(s.string or '' for s in soup.find_all('script') if s.string)
    apis = list(set(re.findall(r'(?:/api/|/BidderWeb/)[A-Za-z][^\s"\'<>]{3,50}', inline)))
    print('API hints:', apis[:15])

# ── Listing page candidates
import time
print()
for path in [
    '/BidderWeb/Auction/Index',
    '/BidderWeb/Auction/List',
    '/BidderWeb/Property/Index',
    '/BidderWeb/Property/List',
    '/BidderWeb/Home/AuctionList',
    '/BidderWeb/Auction/Search',
]:
    print(f'=== {path} ===')
    r2 = get(BASE + path, t=15)
    if r2:
        print(f'  Status={r2.status_code} Bytes={len(r2.content)} URL={r2.url}')
        if r2.status_code == 200:
            s2 = BeautifulSoup(r2.text, 'html.parser')
            print(f'  Text: {s2.get_text(" ", strip=True)[:300]}')
    else:
        print('  TIMEOUT/ERROR')
    time.sleep(1)

print('\n=== DONE ===')
