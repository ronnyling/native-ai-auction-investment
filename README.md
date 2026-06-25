# Auction Investment Vault — Malaysia

Automated pipeline that scrapes Malaysian auction property listings (BidNow, e-Lelong, LelongTips), enriches them with market data and AI scoring, and writes structured Obsidian vault notes for investment due diligence.

---

## Architecture

```
native ai auction investment/
├── scraper/            ← Python pipeline (run this)
│   ├── main.py         ← 10-stage daily scraper orchestrator
│   ├── e2e_due_diligence.py  ← Interactive single-property analysis
│   ├── entry_cost.py   ← ROI engine (5 investment scenarios)
│   ├── bidnow.py       ← BidNow scraper
│   ├── elelong.py      ← e-Lelong scraper (court orders)
│   ├── lelongtips.py   ← LelongTips scraper
│   ├── market_research.py    ← iProperty PSF cache (7-day TTL)
│   ├── analyst_agent.py      ← GPT-4o-mini scoring + rule-based fallback
│   ├── dedup_merger.py ← Cross-source dedup + re-auction detection
│   ├── geocode.py      ← Nominatim geocoder
│   ├── md_writer.py    ← Vault note writer (Obsidian Markdown + YAML)
│   ├── audit.py        ← 156-scenario regression audit
│   └── vault_scan.py   ← Vault data quality scanner
└── vault/
    ├── Properties/     ← bn-*.md / el-*.md notes (1 per property)
    └── Daily Notes/    ← Daily run summaries
```

---

## Daily Run

```bash
# All 15 states, delta mode (skips known IDs)
python scraper/main.py

# Specific states only
SCRAPE_STATES="Kuala Lumpur,Selangor" python scraper/main.py

# Force market cache refresh
RUN_MARKET=1 python scraper/main.py
```

**Environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `VAULT_PATH` | `../vault/Properties` | Vault notes directory |
| `SCRAPE_STATES` | all 15 states | Comma-separated state filter |
| `MAX_PAGES` | unlimited | Hard page cap per state |
| `OPENAI_API_KEY` | — | GPT-4o-mini analyst (optional) |
| `RUN_MARKET` | `auto` | Set `1` to force market cache rebuild |
| `MARKET_CACHE_PATH` | `scraper/market_cache.json` | iProperty cache file |

---

## Single-Property Due Diligence

```bash
# Interactive — scrapes live, auto-selects best BMV property
python scraper/e2e_due_diligence.py --state "Kuala Lumpur"

# Options
--bn-pages 2        # BidNow pages to scrape (default: 3)
--el-pages 1        # e-Lelong pages (default: 1)
--reno light        # Reno level: light | medium | heavy
--auto              # Non-interactive (CI/test mode)
```

The e2e flow always fetches a fresh iProperty market cache (if not already built today) before computing rental yields — so rental benchmarks are never stale when evaluating a deal.

---

## Investment Scenarios (ROI Engine)

Every property is evaluated across 5 scenarios. Source: `scraper/entry_cost.py`.

All scenarios share the same entry cost base: stamp duty (Stamp Act 1949 / SRO 2023 tiered rates), conveyancing legal fees, loan stamp duty (0.5%), valuation fee, and 10% deposit.

### Scenario A — Flip (Sell at Current Market Value)

Exit at the bank-stated market value today. No future appreciation assumed — the discount is locked in at auction.

| Deduction | Basis |
|---|---|
| Seller's agent commission | 2.5% of market value |
| Disposal legal / admin | 0.5% of market value |
| RPGT | 30% on **taxable gain** (citizen, year 1) |

**Taxable gain** = gross gain − stamp duty paid − conveyancing fees paid (RPGT Act 1976 allowable deductions).

### Scenario B — Full Unit Rental (Hold 5 Years)

Single tenancy for the whole unit. Rent from iProperty market cache (district/state PSF median). Vacancy: 1 month/year. RPGT at 15% (year 5, citizen) on capital gain at exit.

### Scenario C — Room Rental, Existing Structure (Hold 5 Years)

Rent individual bedrooms to separate tenants (co-living). No structural changes. Room count derived from bedroom count in listing; falls back to sqft estimate when bedrooms not available (common for BidNow listings — check POS for actual bedroom count).

**Room composition by bedroom count:**

| BR | Master | Middle | Small |
|---|---|---|---|
| 1 | 1 | 0 | 0 |
| 2 | 1 | 1 | 0 |
| 3 | 1 | 1 | 1 |
| 4 | 1 | 2 | 1 |
| 5 | 1 | 2 | 2 |

**KL / Klang Valley room rates (furnished + AC, mid-market, 2025–2026):**

| Room type | Min | Max | Midpoint |
|---|---|---|---|
| Master (ensuite) | RM 1,000 | RM 1,200 | RM 1,100 |
| Middle (shared WC) | RM 800 | RM 1,000 | RM 900 |
| Small (shared WC) | RM 700 | RM 850 | RM 775 |

*Source: iBilik.my, iProperty.com.my (KL/Selangor 2025–2026). Rates are a floor estimate — cross-check live listings at iBilik.my before projecting.*

### Scenario D — Partition Room Rental (Hold 5 Years)

Drywall conversion into more rooms. Highest gross yield; CAPEX required; management overhead is highest. CAPEX is added to total investment for correct ROI.

**Room count formula:** `rooms = min(floor(sqft × 0.75 / 180), cap)`

| Unit size | Max rooms |
|---|---|
| < 600 sqft | 3 |
| 600–800 sqft | 4 |
| 800–1,000 sqft | 5 |
| 1,000–1,200 sqft | 6 |
| > 1,200 sqft | 7 |

Ensuite rooms: 1 per 3 rooms (fire safety / habitability ratio).

**Partition room rates (KL / Klang Valley, 2025–2026):**

| Room type | Min | Max | Midpoint |
|---|---|---|---|
| Ensuite (with toilet) | RM 900 | RM 1,100 | RM 1,000 |
| Shared WC | RM 600 | RM 900 | RM 750 |

**CAPEX per room:**

| Item | Cost |
|---|---|
| Room without bathroom (drywall, door, AC socket, basic furniture) | RM 8,500 |
| Room with ensuite (above + plumbing, toilet, shower, tile) | RM 16,000 |
| Common setup (WiFi, common area) | RM 3,000 |

> Get quotes from ≥ 2 licensed contractors. Obtain JMB/MC approval and local authority permit before work begins. Illegal partitions risk enforcement.

### Scenario E — Capital Hold Only

Hold without renting. Worst cashflow (full mortgage + maintenance shortfall each month). Baseline comparison.

---

## Vault Note Format

Each property is stored as `vault/Properties/bn-XXXXXX.md` with YAML frontmatter:

```yaml
---
id: bn-263430
reserve_price: 243000.0
market_value: 694285.71
bmv_pct: 65
built_up_sqft: 988.0
state: Selangor
property_type: condo
tenure: freehold
auction_date: '2026-06-23'
auction_count: 1
auction_type: LACA
status: new          # new | interested | pass | bid
rating: 0
---
```

Update `status: interested` in Obsidian when marking a property for due diligence. The e2e flow reads `status` to prioritise analysis.

---

## Data Quality

Run the vault scanner to assess field coverage:

```bash
python scraper/vault_scan.py
```

As of June 2026 (3,661 properties):
- 60% have `market_value > 0` (needed for Scenario A)
- 59% have `built_up_sqft > 0` (needed for Scenario D)
- 34% have both (full ROI coverage)
- 8% are past auction date (stale — no auto-cleanup yet)

A scrape health check runs automatically after each `main.py` run and warns if > 60% of the current batch is missing `market_value` or `built_up_sqft` — indicating a BidNow DOM change.

---

## Audit

```bash
python scraper/audit.py              # full 156-scenario audit
python scraper/audit.py --skip-net  # unit tests only (no network)
python scraper/audit.py --cat 2,11  # specific categories
```

Current baseline: **155 PASS, 0 FAIL, 1 WARN** (156 scenarios across 11 categories).

---

## Requirements

```bash
pip install -r scraper/requirements.txt
```

Python 3.11+. Optional: `OPENAI_API_KEY` for GPT-4o-mini analyst scoring.
