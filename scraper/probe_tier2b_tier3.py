"""
probe_tier2b_tier3.py — Targeted probe of accessible sources after tier 1/2A blocked.
"""
import io, sys, re, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Accept-Language": "en-MY,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

def get(url, timeout=20, extra_headers=None):
    h = dict(HEADERS)
    if extra_headers:
        h.update(extra_headers)
    try:
        r = requests.get(url, headers=h, timeout=timeout, allow_redirects=True)
        return r
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

def D():
    print("-" * 60)

def section(t):
    print(f"\n{'='*60}\n  {t}\n{'='*60}")

def show(r, name=""):
    if not r:
        return
    soup = BeautifulSoup(r.text, "html.parser")
    print(f"  [{name}] Status={r.status_code} | Bytes={len(r.content)} | URL={r.url}")
    # Find listing items
    for cls_pat in [r'property|listing|auction|card|item|result']:
        items = soup.find_all(class_=re.compile(cls_pat, re.I))
        if items:
            print(f"  Items (class~={cls_pat}): {len(items)}")
            break
    # Look for JSON API endpoints in script tags
    scripts = [s.string or '' for s in soup.find_all('script') if s.string]
    api_urls = []
    for s in scripts:
        api_urls += re.findall(r'(?:https?://[^\s"\'<>]+(?:api|json|listings?|properties|auction)[^\s"\'<>]*)', s)[:5]
    if api_urls:
        print(f"  API urls in JS: {list(set(api_urls))[:5]}")
    # Sample text
    text = soup.get_text(' ', strip=True)
    print(f"  Text: {text[:500]}")
    # Prices visible
    prices = re.findall(r'RM\s*[\d,]+', text)[:8]
    print(f"  Prices visible: {prices}")
    # PDFs
    pdfs = [a.get('href','') for a in soup.find_all('a', href=True) if '.pdf' in a.get('href','').lower()]
    print(f"  PDF links: {len(pdfs)} {pdfs[:3]}")


# ─────────────────────────────────────────────────────────────────────────────
# MAYBANK 2OWN — deep probe
# ─────────────────────────────────────────────────────────────────────────────
section("Maybank2Own — Deep Probe")

r = get("https://www.maybank2own.com/portal/")
show(r, "home")
time.sleep(2)

for url in [
    "https://www.maybank2own.com/portal/properties",
    "https://www.maybank2own.com/portal/listing",
    "https://www.maybank2own.com/portal/#/properties",
    "https://www.maybank2own.com/portal/api/properties?page=1",
    "https://www.maybank2own.com/portal/api/listings?page=1",
    "https://www.maybank2own.com/portal/api/property/list",
]:
    print(f"\n  Probing: {url}")
    r = get(url, timeout=15)
    if r:
        ct = r.headers.get('Content-Type','')
        print(f"  Status={r.status_code} CT={ct} Bytes={len(r.content)}")
        if 'json' in ct:
            try:
                d = r.json()
                print(f"  JSON keys: {list(d.keys())[:10] if isinstance(d,dict) else type(d)}")
                print(f"  JSON sample: {str(d)[:300]}")
            except:
                print(f"  Body: {r.text[:200]}")
        elif r.status_code == 200 and len(r.content) > 1000:
            soup = BeautifulSoup(r.text, 'html.parser')
            print(f"  Text: {soup.get_text(' ',strip=True)[:300]}")
    time.sleep(1)

# Check for SPA (React/Angular/Vue) - look at script src
r2 = get("https://www.maybank2own.com/portal/", timeout=15)
if r2:
    soup = BeautifulSoup(r2.text, 'html.parser')
    scripts = [s.get('src','') for s in soup.find_all('script', src=True)]
    print(f"\n  Script sources: {scripts[:10]}")
    # Look for API base URL hints
    inline = ' '.join([s.string or '' for s in soup.find_all('script') if s.string])
    api_hints = re.findall(r'(?:apiUrl|baseUrl|API_URL|endpoint)\s*[:=]\s*["\']([^"\']+)["\']', inline)
    print(f"  API hints: {api_hints[:5]}")

# ─────────────────────────────────────────────────────────────────────────────
# BANK PORTALS QUICK SCAN
# ─────────────────────────────────────────────────────────────────────────────
section("Bank Portals — Foreclosed / Auction Property Pages")

bank_targets = [
    ("CIMB", "https://www.cimb.com.my/en/personal/day-to-day-banking/properties/foreclosed-properties.html"),
    ("CIMB-2", "https://www.cimb.com.my/en/personal/day-to-day-banking/properties.html"),
    ("RHB", "https://www.rhbgroup.com/personal/loans-and-financing/auction-property/index.html"),
    ("RHB-2", "https://www.rhbgroup.com/personal/insurance-and-investment/auction-property/index.html"),
    ("PublicBank", "https://www.publicbank.com.my/content/dam/public-bank/personal/loans/auctioned-property/property-listing.pdf"),
    ("PublicBank-2", "https://www.publicbank.com.my/personal/loans/auctioned-properties"),
    ("AmBank", "https://www.ambankgroup.com/eng/Personal/Loans/Pages/AuctionedPropertiesListing.aspx"),
    ("HongLeong", "https://www.hlb.com.my/en/personal-banking/others/foreclosed-property.html"),
    ("BankIslam", "https://www.bankislam.com/personal/financing/auctioned-properties/"),
    ("BSN", "https://www.bsn.com.my/page/auction-properties"),
]

for name, url in bank_targets:
    print(f"\n  {name}: {url}")
    r = get(url, timeout=15)
    if not r:
        print("  TIMEOUT")
        continue
    print(f"  Status={r.status_code} | Bytes={len(r.content)} | CT={r.headers.get('Content-Type','')[:40]}")
    if r.status_code == 200:
        if 'pdf' in r.headers.get('Content-Type','').lower():
            print(f"  -> PDF response ({len(r.content)} bytes) — not directly parseable")
            continue
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(' ', strip=True)
        prices = re.findall(r'RM\s*[\d,]+', text)
        pdfs = [a.get('href','') for a in soup.find_all('a',href=True) if '.pdf' in a.get('href','').lower()]
        tables = soup.find_all('table')
        print(f"  Prices: {prices[:5]} | PDFs: {len(pdfs)} | Tables: {len(tables)}")
        print(f"  Text: {text[:300]}")
    time.sleep(1.5)


# ─────────────────────────────────────────────────────────────────────────────
# PROPERTYGURU — auction / foreclosure listings
# ─────────────────────────────────────────────────────────────────────────────
section("PropertyGuru — Auction Signal Probe")

pg_urls = [
    "https://www.propertyguru.com.my/property-for-sale?freetext=bank+auction&listing_type=sale",
    "https://www.propertyguru.com.my/property-for-sale?freetext=laca&listing_type=sale",
    "https://www.propertyguru.com.my/property-for-sale?freetext=foreclosure&listing_type=sale",
    "https://www.propertyguru.com.my/malaysia-property-for-sale/foreclosure",
]

for url in pg_urls:
    print(f"\n  URL: {url}")
    r = get(url, timeout=20, extra_headers={
        "Referer": "https://www.propertyguru.com.my/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    if not r:
        print("  TIMEOUT")
        continue
    print(f"  Status={r.status_code} | Bytes={len(r.content)}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(' ', strip=True)
        # Count listing cards
        for pat in ['listing-card', 'ListingCard', 'property-card', 'listing']:
            items = soup.find_all(class_=re.compile(pat, re.I))
            if items:
                print(f"  Cards (class~={pat}): {len(items)}")
                break
        # Check for __NEXT_DATA__ or window data
        nd = soup.find('script', id='__NEXT_DATA__')
        if nd:
            try:
                nd_json = json.loads(nd.string)
                print(f"  __NEXT_DATA__ keys: {list(nd_json.keys())[:5]}")
                # Drill into listings
                props = nd_json.get('props',{}).get('pageProps',{})
                print(f"  pageProps keys: {list(props.keys())[:10]}")
                listings = props.get('listings', props.get('data', props.get('properties',[])))
                if listings and isinstance(listings, list):
                    print(f"  Listings in __NEXT_DATA__: {len(listings)}")
                    print(f"  First listing keys: {list(listings[0].keys())[:15] if listings else '—'}")
            except Exception as ex:
                print(f"  __NEXT_DATA__ parse error: {ex}")
        prices = re.findall(r'RM\s*[\d,]+', text)[:8]
        print(f"  Prices: {prices}")
        print(f"  Text: {text[:400]}")
    time.sleep(2)

# ─────────────────────────────────────────────────────────────────────────────
# IPROPERTY — dedicated auction section probe
# ─────────────────────────────────────────────────────────────────────────────
section("iProperty — Auction / Foreclosure Listings Probe")

ip_urls = [
    "https://www.iproperty.com.my/auction-property-for-sale/",
    "https://www.iproperty.com.my/property-for-sale?q=bank+auction",
    "https://www.iproperty.com.my/property-for-sale?q=laca",
]

for url in ip_urls:
    print(f"\n  URL: {url}")
    r = get(url, timeout=20)
    if not r:
        print("  TIMEOUT")
        continue
    print(f"  Status={r.status_code} | Bytes={len(r.content)}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(' ', strip=True)
        listings_m = re.search(r'"listingData"\s*:\s*(\{.*?\}),\s*"', r.text, re.DOTALL)
        all_ld = re.findall(r'"listingData"\s*:\s*\{[^}]{20,}', r.text)
        print(f"  listingData embeds: {len(all_ld)}")
        prices = re.findall(r'RM\s*[\d,]+', text)[:6]
        print(f"  Prices: {prices}")
        print(f"  Text: {text[:300]}")
    time.sleep(2)

print("\n\n=== PROBE COMPLETE ===")
