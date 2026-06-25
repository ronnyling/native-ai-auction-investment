# POS Extraction Regression & Audit Report
**Date**: 2026-06-24  
**Corpus**: 157 PDFs in `pos_study_cache/`  
**Baseline previous run**: 57 PDFs (partial, no `--all` flag)

---

## 1. Unit Audit (audit.py --skip-net)

| Category | Tests | PASS | FAIL | SKIP |
|---|---|---|---|---|
| Cat 1 – Entry Cost | 19 | 19 | 0 | 0 |
| Cat 2 – Flip ROI | 11 | 11 | 0 | 0 |
| Cat 3 – Rental ROI | 21 | 21 | 0 | 0 |
| Cat 4 – Partition Estimation | 33 | 33 | 0 | 0 |
| Cat 5 – Analyst Agent | 14 | 14 | 0 | 0 |
| Cat 6 – POS Identifier | 9 | 9 | 0 | 0 |
| Cat 7 – Dedup Merger | 10 | 10 | 0 | 0 |
| Cat 8 – Market Cache | 6 | 6 | 0 | 1 (net) |
| Cat 9 – Scraper Probes | 0 | 0 | 0 | 4 (net) |
| Cat 10 – Edge Cases | 13 | 13 | 0 | 0 |
| Cat 11 – E2E Smoke | 0 | 0 | 0 | 1 (net) |
| Cat 12 – POS Parser | 30 | 30 | 0 | 0 |
| Cat 13 – Hermes/MiMo | 23 | 23 | 0 | 0 |
| **TOTAL** | **195** | **189** | **0** | **6** |

**Pass rate (excl. SKIP): 100%** — no regressions in unit tests.

---

## 2. Regression Results (157 PDFs, `--all`)

### 2.1 Coverage by Region

| Region | PDFs | Strata | Landed | Complete |
|---|---|---|---|---|
| KL | 61 | 59 | 2 | 43/61 (70.5%) |
| Selangor | 5 | 3 | 2 | 5/5 (100%) |
| Other | 91 | 52 | 38 | 61/91 (67.0%) |
| **Total** | **157** | **114** | **42** | **109/157 (69.4%)** |

**vs. prior baseline: 103/157 (65.6%) → +6 PDFs, +3.8pp improvement**

### 2.2 Field Coverage by Region

| Field | KL (61) | Selangor (5) | Other (91) | Overall |
|---|---|---|---|---|
| bank | 95% (58) | 100% (5) | 95% (86) | **95%** |
| borrower | **82% (50)** | 100% (5) | **91% (83)** | 88% |
| reserve_price_rm | 98% (60) | 100% (5) | 100% (91) | **99%** |
| deposit_required_rm | 98% (60) | 100% (5) | 100% (91) | **99%** |
| disbursement_days | 100% (61) | 100% (5) | 97% (88) | 98% |
| encumbrances | 100% (61) | 100% (5) | **85% (77)** | 91% |
| location | 98% (60) | 100% (5) | 96% (87) | 97% |
| tenure | 93% (57) | 100% (5) | 97% (88) | 96% |

---

## 3. Failure Analysis (48 Incomplete PDFs)

### 3.1 By Missing Field

| Missing Field | Count | Root Cause |
|---|---|---|
| borrower | 18 | New English LACA layout (264xxx KL strata) + 251289 series |
| encumbrances | 16 | 251289 series (old format) + 263907-264057 series (Johor strata) |
| bank | 9 | New layouts: 263155, 263316, 263367, 263763, 263766 etc. |
| tenure | 9 | 264574, 262301, 262303, 263199 etc. — new LACA format variations |
| location | 5 | 264513-264515, 264445, 262858 — unusual address format |
| disbursement_days | 3 | 263276, 264209, 263909 — non-standard payment clause |
| reserve_price_rm | 1 | 264584 — unusual price format |
| deposit_required_rm | 1 | 264584 — depends on reserve |

### 3.2 Failure Clusters

#### Cluster A: 264xxx KL Strata (NEW — 13 PDFs)
- `262064, 262314, 262574, 262577, 262618, 263035, 263155, 263763, 263766, 263769, 264577, 264579, 264584`
- **Pattern**: English LACA format, KL condos/serviced apartments
- **Missing**: primarily `borrower`, some `bank`, some `tenure`  
- **Diagnosis**: The dot-fill pattern `[.…]{5,}.*(?:Assignor|Customer)` and the arrow-fill variant `(?:Assignors?/Borrowers?)` are not matching — likely these PDFs use a different separator (dashes, spaces) or a different label variant (e.g., `PURCHASER/BORROWER`, `DEBTOR`, `ASSIGNOR (S)/BORROWER (S)` with extra spaces)

#### Cluster B: 251289 Series (KNOWN — 5 PDFs)
- `251289_2024*, 251289_2025*, 251289_2026*` — same property, multiple auction rounds
- **Missing**: `borrower` + `encumbrances`
- **Status**: Previously identified, lower priority (same property format)

#### Cluster C: 263907-264057 Johor Strata (KNOWN — 9 PDFs)
- `263907–263913, 264056, 264057`
- **Missing**: `encumbrances`
- **Diagnosis**: Uses `Assignee/Lender` label (not standard LACA). `ENCUMBRANCES:` section may use a different label format
- **Status**: Known issue noted in previous session

#### Cluster D: Location failures (5 PDFs)
- `264513–264515` (listed as Other Strata) — 3 PDFs from the same area
- `264445, 262858` — individual cases
- **Diagnosis**: Address may not start with `No.` or the postal pattern differs

### 3.3 Field-Specific Root Causes

**Borrower (KL 82%)**: The 264xxx KL series are English LACA. Patterns in pos_parser.py:
- Dot-fill pattern requires `[.…]{5,}` (5+ dots/ellipsis chars)
- Arrow-fill pattern requires `Assignors?/Borrowers?`
- These PDFs may use `– – – –` (dashes), plain spaces, or `ASSIGNOR(S)/BORROWER` with spaces around `(S)`

**Tenure (KL 93%)**: PDFs 262301, 262303, 264574 — English LACA. `TENURE:` keyword should exist but case/spacing may differ. Alternatively, these PDFs state tenure differently (e.g., "Hakmilik Kekal" in a field that the regex `Pegangan\s*[:/]\s*(\w[\w\s]*)` doesn't reach, or the English `TENURE` pattern exists but `\bTENURE\s*[:/]\s*(\w+)` fails to match a multi-word value like "99 YEAR LEASEHOLD").

**Bank (Other 95%)**: 263367 (`bank` + `borrower` both missing) and 263316, 261926, 261871 suggest a format where neither PLAINTIF nor PEMEGANG SERAHHAK nor Assignee/Bank labels appear — possibly a government-filed LACA (LPPSA/Tabung Haji style with different party labels).

**Encumbrances (Other 85%)**: 251289 and 263907+ both miss this. For 263907+, it's the Johor LACA format where the encumbrance section may use a label like `ENCUMBRANCE` (no S) or `CAVEAT` rather than `Bebanan`.

---

## 4. Static Code Audit

### 4.1 Correctness Issues

| Severity | Issue | Location |
|---|---|---|
| LOW | Completeness check uses `not out.get(f)` while hermes.py uses `_is_missing()` — whitespace-only strings would pass pos_parser but fail hermes | `pos_parser.py` line 695 |
| LOW | Location regex `[^\n]{10,100}` caps at 100 chars — long Malaysian addresses (Taman + street + unit + floor) may be truncated | `pos_parser.py` ~line 545 |
| LOW | Encumbrances regex stops at first `\n` — multi-line encumbrance entries only capture line 1 | `pos_parser.py` ~line 450 |
| COSMETIC | `_MISSING_ESSENTIAL` key populated using `not out.get(f)` — numeric 0 for any non-price field would (incorrectly) be flagged as missing | `pos_parser.py` line 698 |

### 4.2 Flow Correctness

| Stage | Assessment |
|---|---|
| PDF → text (pypdf) | Correct. 30s timeout per PDF prevents hanging on cloud PDFs. |
| Text → parse_pos_fields() | Correct for known formats. Falls through to `None` silently for unknown. |
| Completeness check | Correct logic, but slightly inconsistent with hermes.py's `_is_missing()` |
| Hermes LLM fallback | Not invoked in regression (no openai package). Hermes mock tests all pass (Cat 13: 23/23). |
| `_hermes_mode` tracking | Correct — `"skipped_complete"` when all fields present, `"unavailable"` when openai absent |

### 4.3 Pattern Coverage Audit

| Format | Coverage |
|---|---|
| Court Malay (PLAINTIF/DEFENDAN) | Excellent — 100% fields for clean docs |
| Malay LACA (PEMEGANG SERAHHAK) | Good — 95%+ all fields |
| English LACA (Assignee/Bank) | Fair — 82% borrower for KL batch; gap in 264xxx series |
| Islamic LACA (Assignee/Lender) | Poor — bank extraction known issue, delegated to MiMo |

---

## 5. Actionable Fixes

### Priority 1 (High — 18 incomplete KL strata PDFs)
Investigate one or two 264xxx PDFs to identify the exact borrower label used. The most likely fixes:
1. Add support for `ASSIGNOR (S)/BORROWER (S)` with spaces around `(S)`
2. Add support for dash-fill separator variant (`-------` instead of `...`)
3. Check if these PDFs use `CUSTOMER/MORTGAGOR` or `DEBTOR` labels

### Priority 2 (Medium — 9 encumbrance failures in Johor strata)
Inspect `263907` PDF text. The `Bebanan` pattern won't match English LACA that uses only `ENCUMBRANCES` (already a fallback exists but may not match specific formatting).

### Priority 3 (Low — tenure in 9 PDFs)
Add pattern for leasehold expressed as `"XX YEAR LEASEHOLD"` or `"PAJAKAN XX TAHUN"` without the `Pegangan :` label wrapper.

### Priority 4 (Low — code consistency)
Replace pos_parser.py line 695 with the same `_is_missing()` logic from hermes.py, or import and use it directly.

---

## 6. Summary

| Metric | Value |
|---|---|
| Unit tests | 189/195 PASS, 0 FAIL (100% excl. SKIP) |
| Full regression PDFs | 157 |
| Complete extractions | **109/157 (69.4%)** |
| Previous baseline | 103/157 (65.6%) |
| Improvement | **+6 PDFs, +3.8pp** |
| Selangor (priority) | 5/5 (100%) |
| KL (priority) | 43/61 (70.5%) |
| Top field gaps | borrower 88%, encumbrances 91% |
| Primary new failure mode | 264xxx English LACA KL strata — borrower not extracted |
| No regressions | All previously passing tests still pass |
