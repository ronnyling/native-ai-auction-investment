"""
e2e_all_sources.py — Multi-source auction data E2E comparison test.

Tests all implemented data sources against a common scope (Kuala Lumpur)
and produces a side-by-side comparison of coverage, data richness, and
reliability. Blocked/infeasible sources are documented with reasons.

Scope for speed: KL only, 1 page or 5 listings max per source.
Run time target: < 3 minutes total.
"""

import io
import sys
import time
from datetime import date

# Force UTF-8 stdout so Unicode chars don't crash on Windows cp1252 terminals
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ─── Source imports ───────────────────────────────────────────────────────────

sys.path.insert(0, ".")
from bidnow import BidNowScraper
from lelongtips import LelongTipsScraper
from elelong import ELelongScraper
from propertyguru import PropertyGuruScraper
from iproperty import IPropertyScraper

# ─── Helpers ──────────────────────────────────────────────────────────────────


def field_coverage(listings: list, fields: list) -> dict:
    """Return % of listings where each field is non-empty/non-zero."""
    if not listings:
        return {f: "N/A" for f in fields}
    result = {}
    for f in fields:
        filled = sum(1 for l in listings if l.get(f) and l.get(f) not in (0, 0.0, ""))
        result[f] = f"{round(filled / len(listings) * 100)}%"
    return result


def price_range(listings: list, field: str = "reserve_price") -> str:
    vals = [l.get(field) for l in listings if l.get(field) and l.get(field) > 0]
    if not vals:
        return "no data"
    return f"RM {min(vals):,.0f} – RM {max(vals):,.0f}"


def state_dist(listings: list) -> str:
    from collections import Counter
    c = Counter(l.get("state", "unknown") for l in listings)
    return ", ".join(f"{s}:{n}" for s, n in c.most_common(3))


def ptype_dist(listings: list) -> str:
    from collections import Counter
    c = Counter(l.get("property_type", "unknown") for l in listings)
    top = c.most_common(3)
    return ", ".join(f"{t}:{n}" for t, n in top)


def timing_label(seconds: float) -> str:
    return f"{seconds:.1f}s"


# ─── Run per source ───────────────────────────────────────────────────────────


def run_bidnow(max_pages=1):
    print("\n" + "=" * 60)
    print("  Source 1: BidNow (Tier 1 — LACA, all of Malaysia)")
    print("=" * 60)
    t0 = time.time()
    try:
        scraper = BidNowScraper()
        listings = scraper.scrape_listings(
            filters={"state": "Kuala Lumpur"},
            max_pages=max_pages,
            known_ids=set(),
        )
        elapsed = time.time() - t0
        print(f"  Result: {len(listings)} listings in {timing_label(elapsed)}")
        return listings, elapsed, None
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  ERROR: {exc}")
        return [], elapsed, str(exc)


def run_lelongtips(max_pages=1):
    print("\n" + "=" * 60)
    print("  Source 2: LelongTips (Tier 1 — LACA + Court, all states)")
    print("=" * 60)
    t0 = time.time()
    try:
        scraper = LelongTipsScraper()
        listings = scraper.scrape_state(
            "Kuala Lumpur", max_pages=max_pages, upcoming_only=True
        )
        elapsed = time.time() - t0
        print(f"  Result: {len(listings)} listings in {timing_label(elapsed)}")
        return listings, elapsed, None
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  ERROR: {exc}")
        return [], elapsed, str(exc)


def run_elelong(max_listings=5):
    print("\n" + "=" * 60)
    print("  Source 3: e-Lelong (Tier 1 — Court Orders, Peninsular MY)")
    print("=" * 60)
    t0 = time.time()
    try:
        scraper = ELelongScraper()
        listings, search_state = scraper.scrape_listings(
            known_slugs=set(),
            prev_search_state={},
            states=["Kuala Lumpur"],
            max_listings=max_listings,
        )
        elapsed = time.time() - t0
        print(f"  Result: {len(listings)} listings in {timing_label(elapsed)}")
        print(f"  search_state keys: {list(search_state.keys())}")
        return listings, elapsed, None, search_state
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  ERROR: {exc}")
        return [], elapsed, str(exc), {}


def run_propertyguru(max_pages=1):
    print("\n" + "=" * 60)
    print("  Source 4: PropertyGuru (Tier 3 — Market/competition signal)")
    print("=" * 60)
    t0 = time.time()
    try:
        scraper = PropertyGuruScraper()
        listings = scraper.scrape_competition_signal(
            query="bank auction", max_pages=max_pages
        )
        elapsed = time.time() - t0
        print(f"  Result: {len(listings)} listings in {timing_label(elapsed)}")
        return listings, elapsed, None
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  ERROR: {exc}")
        return [], elapsed, str(exc)


def run_iproperty(max_pages=1):
    print("\n" + "=" * 60)
    print("  Source 5: iProperty (Tier 3 — Market/competition signal)")
    print("=" * 60)
    t0 = time.time()
    try:
        scraper = IPropertyScraper()
        listings = scraper.scrape_competition_signal(
            query="bank auction", max_pages=max_pages
        )
        elapsed = time.time() - t0
        print(f"  Result: {len(listings)} listings in {timing_label(elapsed)}")
        return listings, elapsed, None
    except Exception as exc:
        elapsed = time.time() - t0
        print(f"  ERROR: {exc}")
        return [], elapsed, str(exc)


# ─── Blocked sources summary ──────────────────────────────────────────────────

BLOCKED_SOURCES = [
    {
        "name": "Maybank2Own",
        "url": "https://www.maybank2own.com/portal/",
        "type": "LACA (HouzKEY)",
        "block_reason": "PerimeterX bot protection on all API endpoints — HTTP 200 returns 'Pardon Our Interruption' anti-bot page for non-browser requests. Requires Selenium + real browser fingerprinting.",
        "workaround": "Selenium + undetected-chromedriver. Low priority — HouzKEY is a rent-to-own product, not traditional LACA auction.",
    },
    {
        "name": "CIMB Foreclosed Properties",
        "url": "https://www.cimb.com.my/en/personal/day-to-day-banking/properties/foreclosed-properties.html",
        "type": "LACA (bank-owned)",
        "block_reason": "Connection timeout on all probes. Likely Cloudflare or heavy WAF. CIMB Malaysia blocks headless HTTP clients.",
        "workaround": "Selenium required. Data volume unknown.",
    },
    {
        "name": "RHB Auction Property",
        "url": "https://www.rhbgroup.com/personal/loans-and-financing/auction-property/",
        "type": "LACA (bank-owned)",
        "block_reason": "URL changed — returns 'Page Unavailable'. New URL path not identified.",
        "workaround": "Find updated URL via browser. May redirect to a third-party auctioneer (BidNow/LelongTips).",
    },
    {
        "name": "Public Bank Auctioned Properties",
        "url": "https://www.publicbank.com.my/personal/loans/auctioned-properties",
        "type": "LACA (bank-owned)",
        "block_reason": "SSL certificate hostname mismatch + connection timeout. Certificate not valid for 'www.publicbank.com.my'.",
        "workaround": "SSL verification bypass (verify=False) or Selenium. Risk: may expose empty/small dataset.",
    },
    {
        "name": "AmBank Auctioned Properties",
        "url": "https://www.ambankgroup.com/eng/Personal/Loans/Pages/AuctionedPropertiesListing.aspx",
        "type": "LACA (bank-owned)",
        "block_reason": "Connection timeout on all probes.",
        "workaround": "Selenium required.",
    },
    {
        "name": "Hong Leong Bank Foreclosed Property",
        "url": "https://www.hlb.com.my/en/personal-banking/others/foreclosed-property.html",
        "type": "LACA (bank-owned)",
        "block_reason": "Connection timeout on all probes.",
        "workaround": "Selenium required.",
    },
    {
        "name": "Bank Islam Auctioned Properties",
        "url": "https://www.bankislam.com/personal/financing/auctioned-properties/",
        "type": "LACA (bank-owned)",
        "block_reason": "Connection timeout on all probes.",
        "workaround": "Selenium required.",
    },
    {
        "name": "BSN Auction Properties",
        "url": "https://www.bsn.com.my/page/auction-properties",
        "type": "LACA (bank-owned)",
        "block_reason": "HTTP 200 but Angular SPA — listings load via client-side JS. HTML contains only 3 PDF links (no structured data).",
        "workaround": "Selenium or inspect XHR to find BSN API endpoint.",
    },
]


# ─── Print comparison report ──────────────────────────────────────────────────

def print_comparison(results: dict):
    today = date.today().isoformat()

    print("\n\n" + "=" * 72)
    print(f"  MULTI-SOURCE AUCTION DATA — E2E COMPARISON REPORT ({today})")
    print("=" * 72)

    # ── Section 1: Coverage ──
    print("\n--- 1. Coverage & Availability ---")
    header = f"{'Source':<20} {'Type':<20} {'Listings':<10} {'Scope':<22} {'Time':<8} {'Status'}"
    print(header)
    print("-" * 95)

    for src, data in results.items():
        listings = data["listings"]
        elapsed = data["elapsed"]
        error = data["error"]
        source_type = data["type"]
        scope = data["scope"]
        status = "ERROR: " + error[:30] if error else "OK"
        print(f"{src:<20} {source_type:<20} {len(listings):<10} {scope:<22} {timing_label(elapsed):<8} {status}")

    # ── Section 2: Data richness ──
    print("\n--- 2. Data Richness per Source ---")

    AUCTION_FIELDS = ["reserve_price", "pos_url", "auction_date", "bank", "tenure", "built_up_sqft", "market_value", "bmv_percent"]
    MARKET_FIELDS  = ["asking_price", "price_psf", "full_address", "state", "property_type", "built_up_sqft"]

    for src, data in results.items():
        listings = data["listings"]
        if not listings:
            print(f"\n  {src}: No listings to analyse")
            continue

        is_market = data.get("is_market_signal", False)
        fields = MARKET_FIELDS if is_market else AUCTION_FIELDS
        cov = field_coverage(listings, fields)
        price_field = "asking_price" if is_market else "reserve_price"

        print(f"\n  {src} ({len(listings)} listings):")
        print(f"    Field coverage:  {', '.join(f'{k}={v}' for k, v in cov.items())}")
        if src == "LelongTips" and all(v == "0%" for v in cov.values()):
            print(f"    NOTE: Card scraper returns slugs/URLs only. Reserve price/date/bank")
            print(f"          populated by scrape_detail() per-listing (separate request).")
        print(f"    Price range:     {price_range(listings, price_field)}")
        print(f"    States:          {state_dist(listings)}")
        print(f"    Property types:  {ptype_dist(listings)}")

        # Sample listing
        sample = listings[0]
        print(f"    Sample listing:")
        addr = sample.get("full_address") or sample.get("title") or "N/A"
        print(f"      address:       {addr[:60]}")
        price_val = sample.get(price_field, 0)
        print(f"      {price_field}: RM {price_val:,.0f}" if price_val else f"      {price_field}: N/A")
        unique_fields = [f for f in ("pos_url", "case_number", "bank", "auction_type", "bmv_percent", "auction_count", "price_psf") if sample.get(f)]
        if unique_fields:
            print(f"      unique fields: {', '.join(unique_fields)}")

    # ── Section 3: Pros/cons ──
    print("\n--- 3. Pros & Cons per Source ---\n")

    PROS_CONS = {
        "BidNow": {
            "pros": [
                "Most complete LACA dataset for Malaysia — primary source for banks",
                "Structured JSON API with state/type filters — very reliable",
                "BMV% pre-calculated by the platform — no independent market valuation needed",
                "Includes lawyer, auctioneer, deposit amount, POS file URL",
                "Covers all 16 states including East Malaysia (Sabah, Sarawak)",
                "Delta mode works cleanly via known_ids stop condition",
            ],
            "cons": [
                "LACA auctions only — court orders from e-Lelong not included",
                "BMV% accuracy depends on BidNow's own valuation — not independently verified",
                "API undocumented — subject to breaking changes without notice",
                "No case number or title registration details",
            ],
        },
        "LelongTips": {
            "pros": [
                "Covers LACA + some court order auctions — broader than BidNow alone",
                "Unique: past auction price history visible (free tier) — shows how many rounds",
                "Auction count badge ('4th Auction') is a key competition signal",
                "Covers Sabah, Sarawak, Labuan + Peninsular — broadest geographic coverage",
                "No authentication required for public data",
            ],
            "cons": [
                "Not a primary source — aggregates from various auctioneers, may lag BidNow",
                "Detailed data (POS PDF, plaintiff, solicitor) requires paid subscription",
                "Scraping HTML cards is fragile compared to JSON API",
                "Overlap with BidNow is high — many same properties, not additive",
                "Smaller total inventory than BidNow for most states",
            ],
        },
        "e-Lelong": {
            "pros": [
                "ONLY source for High Court of Malaya court order auctions",
                "Official government platform — data is authoritative",
                "POS PDF directly accessible (no subscription) via EFS document system",
                "Case number + title number + encumbrances field unique to this source",
                "SearchAuction JSON API is stable (official government endpoint)",
                "Per-state delta checking minimises redundant requests",
            ],
            "cons": [
                "Peninsular Malaysia + WP only (High Court of Malaya jurisdiction only)",
                "No BMV% — market value must be sourced independently (iProperty/PropertyGuru)",
                "IDs are non-sequential with large gaps — sequential scanning impossible",
                "Detail page requires separate HTTP request per listing",
                "CSRF token required — adds one warmup GET per session",
            ],
        },
        "PropertyGuru": {
            "pros": [
                "Largest Malaysian property portal — highest market coverage",
                "Price PSF data enables rough market valuation without external tools",
                "New listings daily — real-time market signal",
                "No authentication, no bot protection observed",
                "__NEXT_DATA__ JSON embedded in HTML — reliable extraction",
            ],
            "cons": [
                "NOT an auction source — competition/market signal only",
                "'bank auction' keyword search may include false positives (agent marketing language)",
                "No auction date, reserve price, or POS data",
                "Listing prices are asking prices — actual market value differs",
                "Pagination required for full coverage (60+ listings per search)",
            ],
        },
        "iProperty": {
            "pros": [
                "Largest alternative portal — broad coverage of for-sale listings in all states",
                "Price PSF prominently shown — useful for market value derivation",
                "get_competition_signal() returns comparable count for price+size+locale match",
                "No authentication required; no bot protection observed",
                "Area-level search by state+district+type gives precise locale context",
                "raw_decode extraction is fast (O(n) through 1-2MB HTML)",
            ],
            "cons": [
                "NOT an auction source — competition/market signal only",
                "Full unit address hidden by iProperty to protect agent exclusivity",
                "  -> Match by size +-10% (same layout) then price +-25% within locale",
                "  -> If built_up_sqft unknown: competition_level = 'Unknown', signal skipped",
                "state/district fields sparse in listingData — locale from URL context",
                "Each listing appears twice in SSR HTML — must deduplicate by ID",
            ],
        },
    }

    for src, pc in PROS_CONS.items():
        print(f"  {src}")
        print(f"    PROS:")
        for p in pc["pros"]:
            print(f"      + {p}")
        print(f"    CONS:")
        for c in pc["cons"]:
            print(f"      - {c}")
        print()

    # ── Section 4: Blocked sources ──
    print("--- 4. Blocked / Infeasible Sources ---\n")
    for src in BLOCKED_SOURCES:
        print(f"  {src['name']} ({src['type']})")
        print(f"    URL:     {src['url']}")
        print(f"    Blocked: {src['block_reason']}")
        print(f"    Fix:     {src['workaround']}")
        print()

    # ── Section 5: Recommended pipeline ──
    print("--- 5. Recommended Multi-Source Pipeline ---\n")
    print("""  Priority  Source         Role                    Update Cadence
  --------  -------------  ----------------------  --------------
  P1        BidNow         Primary LACA discovery  Daily (delta)
  P2        e-Lelong       Court order discovery   Daily (delta)
  P3        LelongTips     Auction history/round#  Weekly (cross-ref)
  P4        iProperty      Area price benchmarks   Weekly (on demand)
  P5        PropertyGuru   Competition signal      Weekly (on demand)
  DEFERRED  Bank portals   Direct bank inventory   Needs Selenium

  Integration point: all P1-P3 listings flow into dedup_merger → geocode →
  md_writer → Analyst Agent (Stage 9) scoring.
  P4/P5 feeds into market_research.py for market_value derivation when
  BidNow BMV% is missing (e.g. all e-Lelong listings).
""")

    print("=" * 72)
    print("  END OF REPORT")
    print("=" * 72)


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    overall_t0 = time.time()

    print("\n" + "=" * 72)
    print("  MULTI-SOURCE E2E TEST — Scope: Kuala Lumpur, max 5 listings each")
    print("=" * 72)

    # ── Run all sources ──
    bn_listings, bn_t, bn_err = run_bidnow(max_pages=1)
    llt_listings, llt_t, llt_err = run_lelongtips(max_pages=1)
    el_listings, el_t, el_err, el_state = run_elelong(max_listings=5)
    pg_listings, pg_t, pg_err = run_propertyguru(max_pages=1)
    ip_listings, ip_t, ip_err = run_iproperty(max_pages=1)

    total_elapsed = time.time() - overall_t0
    print(f"\n  All sources scraped in {total_elapsed:.1f}s total")

    # ── Aggregate results ──
    results = {
        "BidNow": {
            "listings": bn_listings,
            "elapsed": bn_t,
            "error": bn_err,
            "type": "LACA (court + bank)",
            "scope": "All Malaysia",
            "is_market_signal": False,
        },
        "LelongTips": {
            "listings": llt_listings,
            "elapsed": llt_t,
            "error": llt_err,
            "type": "LACA + Court (mixed)",
            "scope": "All 16 states",
            "is_market_signal": False,
        },
        "e-Lelong": {
            "listings": el_listings,
            "elapsed": el_t,
            "error": el_err,
            "type": "Court Orders",
            "scope": "Peninsular MY + WP",
            "is_market_signal": False,
        },
        "PropertyGuru": {
            "listings": pg_listings,
            "elapsed": pg_t,
            "error": pg_err,
            "type": "Market signal",
            "scope": "All Malaysia",
            "is_market_signal": True,
        },
        "iProperty": {
            "listings": ip_listings,
            "elapsed": ip_t,
            "error": ip_err,
            "type": "Market signal",
            "scope": "All Malaysia",
            "is_market_signal": True,
        },
    }

    # ── Print report ──
    print_comparison(results)

    # ── iProperty competition signal demo ──
    # Use first e-Lelong listing (if any) as a sample auction property to probe
    print("\n" + "=" * 72)
    print("  iProperty Competition Signal Demo")
    print("=" * 72)
    sample = el_listings[0] if el_listings else None
    if sample:
        price  = sample.get("reserve_price", 0)
        sqft   = sample.get("built_up_sqft", 0)
        ptype  = sample.get("property_type", "")
        addr   = (sample.get("full_address") or "")[:60]
        # Map e-Lelong property type to iProperty category slug
        cat_map = {
            "condominium": "apartment-condo",
            "apartment":   "apartment-condo",
            "condo":       "apartment-condo",
            "terrace":     "terrace-link-house",
            "semi-d":      "semi-detached-house",
            "bungalow":    "bungalow",
        }
        cat = cat_map.get(ptype.lower(), "apartment-condo")
        print(f"\n  Sample auction property: {addr}")
        print(f"  Reserve price: RM {price:,.0f} | Size: {sqft} sqft | Type: {ptype}")
        if sqft:
            print(f"  iProperty query: state=kuala-lumpur, category={cat}, size+-10%, price+-25%")
        else:
            print(f"  iProperty query: state=kuala-lumpur, category={cat}, size=UNKNOWN")
        t0 = time.time()
        scraper = IPropertyScraper()
        signal = scraper.get_competition_signal(
            target_price=price,
            target_sqft=sqft,
            state_slug="kuala-lumpur",
            property_category=cat,
            district_slug="",
            price_tolerance_pct=25.0,
            size_tolerance_pct=10.0,
            max_pages=1,
        )
        elapsed = time.time() - t0
        print(f"\n  Competition Signal Result ({elapsed:.1f}s):")
        print(f"    Locale:            {signal['locale']}")
        print(f"    Total listings:    {signal['total_area_count']} scraped from iProperty")
        if signal["size_known"]:
            print(f"    Size-matched:      {signal['size_matched_count']} within +-10% of {sqft:.0f} sqft")
            print(f"    Comparable count:  {signal['comparable_count']} also within +-25% of reserve price")
            print(f"    Median asking:     RM {signal['median_asking']:,.0f}" if signal['median_asking'] else "    Median asking:     N/A")
            print(f"    Median PSF:        RM {signal['median_psf']:,.2f}" if signal['median_psf'] else "    Median PSF:        N/A")
            print(f"    Price range:       {signal['price_range']}")
            print(f"    Size range:        {signal['size_range']}")
        else:
            print(f"    Size unknown — competition signal unreliable, skipped comparison")
        print(f"    Competition level: {signal['competition_level']}")
        level_note = {
            "Low":     "(<= 2 comparables) -- fewer retail buyers, less bidding pressure",
            "Medium":  "(3-5 comparables) -- moderate competition, some retail interest",
            "High":    "(> 5 comparables) -- strong retail market, expect active bidding",
            "Unknown": "(size not provided) -- cannot assess without matching layout/size",
        }
        print(f"    Interpretation:    {level_note.get(signal['competition_level'], '')}")
    else:
        print("  (no e-Lelong listings available for demo)")

    print("=" * 72)
