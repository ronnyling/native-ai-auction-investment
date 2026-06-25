"""
probe_all_sources.py — Structural probe for all candidate auction property sources.
Run this to understand what each source offers before building scrapers.
"""
import json
import re
import time
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-MY,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

DELAY = 2.0

def get(url, timeout=25):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        return r
    except Exception as e:
        return None

def divider(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def check_json_embed(text):
    """Return snippets of any JSON data embeds in page HTML/scripts."""
    patterns = [
        r'var\s+\w+\s*=\s*(\{.*?\});',
        r'window\.__(?:INITIAL|NEXT|DATA)__\s*=\s*(\{)',
        r'"listings?":\s*\[',
        r'"properties?":\s*\[',
        r'"auctions?":\s*\[',
        r'"data":\s*\[',
        r'"items?":\s*\[',
    ]
    found = []
    for p in patterns:
        m = re.search(p, text, re.DOTALL | re.IGNORECASE)
        if m:
            found.append(p + " → " + text[m.start():m.start()+150].replace('\n',' '))
    return found

def count_listing_cards(soup):
    """Try to count listing cards by common class patterns."""
    total = 0
    matched_class = ""
    for pat in [r'listing|property-card|auction-item|result-item|item-card|prop-item', r'card']:
        items = soup.find_all(class_=re.compile(pat, re.I))
        if items:
            total = len(items)
            matched_class = pat
            break
    return total, matched_class

def extract_sample_data(soup, n=3):
    """Try to extract address, price, date from first few visible items."""
    samples = []
    # Look for price patterns
    prices = re.findall(r'RM\s*[\d,]+', soup.get_text())[:n*2]
    # Look for date patterns
    dates = re.findall(r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}', soup.get_text())[:n]
    return prices[:n*2], dates[:n]


# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: AuctionGuru
# ─────────────────────────────────────────────────────────────────────────────
divider("TIER 1 — AuctionGuru.com.my")

for ag_url in [
    "https://www.auctionguru.com.my/listing/",
    "https://www.auctionguru.com.my/listing/?state=Selangor",
    "https://www.auctionguru.com.my/listing/?state=Kuala+Lumpur&page=1",
]:
    print(f"\n  URL: {ag_url}")
    r = get(ag_url, timeout=20)
    if not r:
        print("  TIMEOUT / CONNECTION REFUSED")
        continue
    print(f"  Status: {r.status_code} | Bytes: {len(r.content)} | Final URL: {r.url}")
    if r.status_code != 200:
        print(f"  Body snippet: {r.text[:300]}")
        time.sleep(DELAY)
        continue
    soup = BeautifulSoup(r.text, "html.parser")
    cards, cls = count_listing_cards(soup)
    print(f"  Listing cards: {cards} (class pattern: {cls})")
    embeds = check_json_embed(r.text)
    print(f"  JSON embeds: {len(embeds)}")
    for e in embeds[:3]:
        print(f"    {e[:200]}")
    prices, dates = extract_sample_data(soup)
    print(f"  Sample prices: {prices[:6]}")
    print(f"  Sample dates:  {dates[:4]}")
    # Check for POS/PDF links
    pdf_links = [a['href'] for a in soup.find_all('a', href=True) if '.pdf' in a['href'].lower()]
    print(f"  PDF links: {pdf_links[:3]}")
    # Check for detail page pattern
    detail_links = [a['href'] for a in soup.find_all('a', href=True) if '/listing/' in a['href'] or '/property/' in a['href']]
    print(f"  Detail link sample: {detail_links[:3]}")
    print(f"  Text sample: {soup.get_text(' ', strip=True)[:400]}")
    time.sleep(DELAY)

# Probe a detail page if we found links
print("\n  Probing AuctionGuru detail page...")
r = get("https://www.auctionguru.com.my/listing/?state=Selangor", timeout=20)
if r and r.status_code == 200:
    soup = BeautifulSoup(r.text, "html.parser")
    links = [a['href'] for a in soup.find_all('a', href=True)
             if re.search(r'/listing/\d+|/property/\d+', a.get('href',''))]
    if links:
        detail_url = urljoin("https://www.auctionguru.com.my", links[0])
        print(f"  Detail URL: {detail_url}")
        time.sleep(DELAY)
        rd = get(detail_url, timeout=20)
        if rd and rd.status_code == 200:
            ds = BeautifulSoup(rd.text, "html.parser")
            print(f"  Detail page text:\n{ds.get_text(' ', strip=True)[:800]}")


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2A: e-Lelong (Government Court Auctions)
# ─────────────────────────────────────────────────────────────────────────────
divider("TIER 2A — e-Lelong (elelong.gov.my) — Government Court Auctions")

for el_url in [
    "https://elelong.gov.my",
    "https://elelong.gov.my/public/auctionList",
    "https://elelong.gov.my/public/properties",
    "https://www.elelong.gov.my",
]:
    print(f"\n  URL: {el_url}")
    r = get(el_url, timeout=20)
    if not r:
        print("  TIMEOUT / NO RESPONSE")
        continue
    print(f"  Status: {r.status_code} | Bytes: {len(r.content)} | Final URL: {r.url}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        print(f"  Text: {soup.get_text(' ', strip=True)[:400]}")
        embeds = check_json_embed(r.text)
        if embeds:
            for e in embeds[:2]:
                print(f"    embed: {e[:200]}")
        forms = soup.find_all('form')
        print(f"  Forms: {len(forms)}")
        apis = re.findall(r'https?://[^\s"\']+api[^\s"\']*', r.text)[:5]
        print(f"  API URLs found: {apis}")
    time.sleep(DELAY)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2B: Maybank2Own (most structured bank portal)
# ─────────────────────────────────────────────────────────────────────────────
divider("TIER 2B — Maybank2Own (maybank2own.com)")

for mb_url in [
    "https://www.maybank2own.com",
    "https://www.maybank2own.com/property-listing",
    "https://www.maybank2own.com/api/properties",
    "https://www.maybank2own.com/listing",
]:
    print(f"\n  URL: {mb_url}")
    r = get(mb_url, timeout=20)
    if not r:
        print("  TIMEOUT")
        continue
    print(f"  Status: {r.status_code} | Bytes: {len(r.content)} | Final URL: {r.url}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        print(f"  Text: {soup.get_text(' ', strip=True)[:400]}")
        embeds = check_json_embed(r.text)
        for e in embeds[:2]:
            print(f"    embed: {e[:200]}")
        # API probes
        api_hints = re.findall(r'(?:fetch|axios|get|post)\s*\(["\']([^"\']+)["\']', r.text)[:5]
        print(f"  API calls in JS: {api_hints}")
    time.sleep(DELAY)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2C: Other bank portals (quick scan)
# ─────────────────────────────────────────────────────────────────────────────
divider("TIER 2C — Bank Portals Quick Scan")

bank_urls = [
    ("CIMB",    "https://www.cimb.com.my/en/personal/day-to-day-banking/properties/foreclosed-properties.html"),
    ("RHB",     "https://www.rhbgroup.com/personal/insurance-and-investment/auction-property/index.html"),
    ("RHB-2",   "https://www.rhbgroup.com/personal/loans-and-financing/auction-property/index.html"),
    ("PublicBk","https://www.publicbank.com.my/personal/loans/auctioned-properties"),
    ("AmBank",  "https://www.ambankgroup.com/eng/Personal/Loans/Pages/AuctionedPropertiesListing.aspx"),
]

for name, url in bank_urls:
    print(f"\n  {name}: {url}")
    r = get(url, timeout=15)
    if not r:
        print("  TIMEOUT")
        continue
    print(f"  Status: {r.status_code} | Bytes: {len(r.content)} | Final URL: {r.url}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(' ', strip=True)
        prices = re.findall(r'RM\s*[\d,]+', text)[:5]
        pdf_count = len(re.findall(r'\.pdf', r.text, re.I))
        print(f"  Prices: {prices} | PDF links: {pdf_count} | Text: {text[:300]}")
    time.sleep(1.5)


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: PropertyGuru (Auction / Foreclosure listings)
# ─────────────────────────────────────────────────────────────────────────────
divider("TIER 3 — PropertyGuru (advertised auction / foreclosure)")

for pg_url in [
    "https://www.propertyguru.com.my/property-for-sale?freetext=auction",
    "https://www.propertyguru.com.my/foreclosure-property-for-sale",
    "https://www.propertyguru.com.my/auction-property-for-sale",
    "https://www.propertyguru.com.my/property-for-sale?property_type_code[]=APT&freetext=bank+auction",
]:
    print(f"\n  URL: {pg_url}")
    r = get(pg_url, timeout=20)
    if not r:
        print("  TIMEOUT")
        continue
    print(f"  Status: {r.status_code} | Bytes: {len(r.content)} | Final URL: {r.url}")
    if r.status_code == 200:
        soup = BeautifulSoup(r.text, "html.parser")
        cards, cls = count_listing_cards(soup)
        print(f"  Cards: {cards} (cls: {cls})")
        embeds = check_json_embed(r.text)
        for e in embeds[:3]:
            print(f"    embed: {e[:200]}")
        prices, dates = extract_sample_data(soup)
        print(f"  Prices: {prices[:6]} | Dates: {dates[:3]}")
        print(f"  Text: {soup.get_text(' ', strip=True)[:300]}")
        # Check for structured data
        ld = soup.find_all('script', type='application/ld+json')
        print(f"  LD+JSON blocks: {len(ld)}")
    time.sleep(DELAY)

print("\n\n=== PROBE COMPLETE ===")
