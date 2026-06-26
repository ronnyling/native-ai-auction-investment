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
│   ├── audit.py        ← ~204-scenario regression audit (13 categories)
│   ├── vault_scan.py   ← Vault data quality scanner
│   ├── pos_parser.py   ← POS (Proclamation of Sale) PDF field extractor
│   ├── pos_regression.py     ← 157-PDF regression suite for POS parser
│   ├── pos_bulk_download.py  ← Batch POS PDF downloader
│   ├── pos_identifier.py     ← Match listing IDs to POS PDFs
│   ├── hermes.py       ← AI field enrichment from POS text
│   └── pdf_extractor.py      ← Raw text extraction from PDFs
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

Windows `cmd` equivalent for the environment-variable examples:

```bat
REM Specific states only
set SCRAPE_STATES=Kuala Lumpur,Selangor && python scraper/main.py

REM Force market cache refresh
set RUN_MARKET=1 && python scraper/main.py
```

The plain `python ...` commands above are also copy-paste safe in `cmd` if Python is on `PATH`.

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
--el-pages 1        # e-Lelong pages (default: 1; set 0 to skip entirely)
--district Puchong  # Filter listings by district/city name (substring match)
--reno light        # Reno level: light | medium | heavy
--auto              # Non-interactive (CI/test mode)
```

Auto-selection logic: residential types are always preferred over commercial types (shops, offices, industrial). Within residential, higher BMV% is ranked first. Commercial listings are included in the scrape output but skipped in market comparison — iProperty PSF benchmarks are residential-only.

---

## POS Pipeline

The Proclamation of Sale (POS) is the legal document attached to each auction listing. It is the primary source of ground-truth field data: borrower identity, encumbrances, tenure, exact address, and precise reserve price.

**Extracted fields (8 essential):**

| Field | Description |
|---|---|
| `bank` | Plaintiff bank name |
| `borrower` | Named borrower(s) / assignor(s) |
| `reserve_price_rm` | Reserve price as stated in POS |
| `deposit_required_rm` | Deposit amount |
| `disbursement_days` | Days to settle balance |
| `encumbrances` | Nil / specific encumbrances listed |
| `location` | Full property address as per title |
| `tenure` | Freehold / Leasehold + expiry |

**Coverage (as of June 2026):** 121 / 157 PDFs = **77.1%** all-field extraction across the regression suite.

**Running the regression:**

```bash
python scraper/pos_regression.py   # runs against local PDF corpus
```

**Running the unit tests:**

```bash
python scraper/audit.py --cat 12   # 39 POS parser tests
```

**Known POS extraction gaps** (see [Known Gaps](#known-gaps)).

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
status: new          # new | reviewing | shortlisted | visiting | bid | closed (terminal)
rating: 0
---
```

Update `status` in Obsidian as the note moves through the lifecycle. The e2e flow reads `status` to prioritise analysis.

## Property Lifecycle

Canonical lifecycle:

`new` → `reviewing` → `shortlisted` → `visiting` → `bid` → `closed`

Terminal end state: `closed`

Legacy aliases: `interested` maps to `reviewing`, while `rejected`, `passed`, and `pass` map to `closed` during migration.

Use `closed` for notes that are finished. Active alerts and monitor queues should only show notes that have not yet reached `closed`.

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
python scraper/audit.py              # full ~204-scenario audit
python scraper/audit.py --skip-net  # unit tests only (no network)
python scraper/audit.py --cat 2,11  # specific categories
```

Current baseline: **~204 PASS, 0 FAIL** (204 scenarios across 13 categories).

Category 12 (POS Parser): 39/39 PASS.

---

## Beta Tester Guide

Beta Mode Objective: simulate real user decision-making, not internal validation.

Execution Rule:
- Run scenarios sequentially.
- Stop immediately on the first failure.
- Fix the root cause before continuing.
- Rerun the same scenario after a fix before widening scope.

What to capture on every run:
- Command used.
- State, district, page counts, and whether e-Lelong was skipped.
- Selected listing ID, property type, and district/city.
- Final user outcome: `SHORTLIST`, `REVIEW`, `REJECT`, or `CONFIDENT SHORTLIST`.
- Key risks, assumption warnings, and whether the explanation is clear.

### Flow To Follow

1. Scraping - confirm the batch is not empty and the district filter matches the target area.
2. Property Selection - confirm residential listings are preferred over commercial when both exist.
3. Property Details - confirm reserve price, market value, tenure, and location print correctly.
4. POS Check - confirm POS status, POS URL, and extracted fields appear when available.
5. Market Comparison - confirm residential benchmarks are used; commercial should show `N/A`.
6. Entry Cost Estimate - confirm exit price compounds from market value when present, not reserve price.
7. Investment Analysis - confirm the final recommendation matches the score and the key risks are explicit.
8. Explanation Check - confirm a human can understand why the property was chosen and which assumptions were used.

### Suggested Beta Scenarios

| # | Scenario | What it proves | Expected user outcome |
|---|---|---|---|
| 1 | Puchong residential happy path | District filter, residential selection, and full report flow work end to end | `SHORTLIST` or `REVIEW` |
| 2 | District ambiguity check | District filtering is token-based and does not collapse to the full state | `REVIEW` if the match is fuzzy |
| 3 | Commercial guardrail | Commercial listings do not outrank residential ones | `REJECT` for commercial-only candidates |
| 4 | Missing-data fallback | Sparse listings still produce a usable report without crashing | `REVIEW` |
| 5 | High-volume stress run | The pipeline stays responsive with a wider scrape batch | `REVIEW` or better if stable |
| 6 | Misleading ROI detection | Inflated market-value assumptions trigger a visible warning | `REVIEW` or `REJECT` |
| 7 | Repeatability check | The same inputs produce the same selection and recommendation | `CONFIDENT SHORTLIST` if stable |
| 8 | Explanation clarity check | The report explains selection, ROI, and assumptions clearly | `CONFIDENT SHORTLIST` or `REVIEW` |

### Pass Criteria

- No hangs or silent stalls.
- No commercial listing is treated as better residential stock when residential options exist.
- High market value vs reserve triggers a visible high-risk assumption warning.
- Repeated runs stay stable unless the live source data changes.
- The final report explains the recommendation, the ROI basis, and the main risks.

### Reporting Guidance

When logging a beta issue, include:
- The exact command used.
- The selected listing ID and a short description.
- The expected outcome versus the actual outcome.
- The stage where the issue appeared.
- Whether the issue is a crash, a wrong recommendation, or an explanation gap.

### Obsidian Monitor

Use the dashboard note as the user-facing monitoring layer. Keep the scraper state-based; use Obsidian for keyword monitoring and lifecycle review.

Put watch terms in the Dashboard frontmatter under `monitor_keywords`, and set the terminal state list under `terminal_statuses`.

What it shows:
1. Delta matches - notes scraped today that match any monitor keyword.
2. Open monitor queue - notes that match any monitor keyword but have not yet reached the terminal state.
3. Notification bar - notes near auction that are still active, so you can see what needs attention before the deadline.

Keyword matching is against the note's visible property text and metadata, including address, city, state, postcode, bank, auctioneer, property type, status, action_needed, tags, and file name.

Suggested workflow:
1. Search the district or city first, for example `Puchong`, `PJ`, or `Shah Alam`.
2. Narrow by note fields in the YAML frontmatter, such as `status: reviewing`, `tenure: leasehold`, or `auction_type: LACA`.
3. Add investment filters when needed, such as `bmv_pct`, `reserve_price`, or `market_value`.
4. Open the matching note and review the property summary, risks, and report text.

Fast checks:
- Use the global search pane in Obsidian to scan the whole vault.
- Search for `status: reviewing` to see active notes.
- Combine a location term with a field term to narrow results quickly, for example `Puchong` + `status: reviewing`.

## Templater Cockpit Bridge

The vault includes an Obsidian-native startup hook through Templater. The startup template at `vault/_templates/_startup/cockpit-bootstrap.md` calls the `cockpit_run` system-command function, which in turn runs `scraper/obsidian-cockpit.ps1`.

One-time setup inside Obsidian:
1. Enable `Enable startup templates` in Templater.
2. Enable `Enable user system command functions` in Templater.

After that, opening Obsidian can trigger the Cockpit pipeline without a manual tag or a separate launcher.

---

## Known Gaps

Distinguishes between **not yet implemented** (fixable) and **structurally hard** (pattern variance in source documents).

| Field | Gap | Type |
|---|---|---|
| `encumbrances` | Johor LACA deeds encode encumbrances differently from Peninsular court-order format; not yet handled | Not yet built |
| `bank` | Some PDFs list the bank inline with the address block instead of in a named section; regex misses these | Structurally hard (pattern variance) |
| `location` | Multi-lot properties (e.g. "Lot 1234 and Lot 5678") only capture the first lot | Not yet built |
| `tenure` | Some PDFs omit leasehold expiry year; tenure extracted as "Leasehold" without expiry date | Structurally hard (data absent in source) |
| `borrower` | PDFs with no heading label (bare name blocks) — parser cannot distinguish borrower from address | Structurally hard |
| e-Lelong | Hangs on high-volume state scrapes (Selangor: 1,255 results) — set `--el-pages 0` to skip | Not yet built (pagination throttle needed) |
| iProperty market cache | Returns `None` for areas not covered by iProperty listings (rural / low-density districts) | Structurally hard (no data source) |

---

## Pending Work

| Item | What's needed | Priority |
|---|---|---|
| POS encumbrance — Johor LACA | Map Johor LACA deed format to `encumbrances` field | P2 |
| POS multi-lot location | Capture all lot numbers when multiple lots are described | P2 |
| e-Lelong pagination throttle | Add rate limiting + page cap to prevent hangs on high-volume states | P2 |
| Bedroom count from POS | Parse bedroom count out of POS description; currently falls back to sqft estimate | P2 |
| Analyst agent (LLM) | OpenAI GPT-4o-mini path present but disabled without API key; rule-based fallback always active | P3 |
| Vault stale-note cleanup | Properties past auction date are flagged but not auto-archived | P3 |
| Full-text POS search | Index all POS PDFs for keyword search (occupancy issues, access disputes) | P3 |

---

## Requirements

```bash
pip install -r scraper/requirements.txt
```

Python 3.14. Optional: `OPENAI_API_KEY` for GPT-4o-mini analyst scoring.
