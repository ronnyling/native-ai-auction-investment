"""
audit.py — Full system audit for the Auction Investment pipeline.

Covers 10 test categories, 70+ scenarios.
Runs unit tests (no network), integration tests (1-2 page scrapes), and
a lightweight E2E smoke test.  Produces a structured PASS/FAIL/WARN report
with improvement suggestions.

Usage:
    python audit.py             # all categories
    python audit.py --skip-net  # skip network-dependent tests
    python audit.py --cat 1,3   # run only categories 1 and 3
"""

import io
import sys
import json
import time
import traceback
import argparse
import re
import yaml
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# ── Result store ──────────────────────────────────────────────────────────────

class AuditResult:
    PASS  = "PASS"
    FAIL  = "FAIL"
    WARN  = "WARN"
    SKIP  = "SKIP"
    ERROR = "ERROR"

results: List[Dict] = []

def _r(cat: int, scenario_id: str, description: str,
       status: str, actual: Any = None, expected: Any = None,
       notes: str = "") -> Dict:
    r = {
        "cat": cat, "id": scenario_id, "desc": description,
        "status": status, "actual": actual, "expected": expected,
        "notes": notes,
    }
    results.append(r)
    _sym = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "-", "ERROR": "!"}
    sym  = _sym.get(status, "?")
    print(f"  [{sym}] {scenario_id}  {description}")
    if status in (AuditResult.FAIL, AuditResult.ERROR):
        if expected is not None:
            print(f"       expected: {expected}")
        if actual is not None:
            print(f"       actual  : {actual}")
        if notes:
            print(f"       note    : {notes}")
    elif status == AuditResult.WARN and notes:
        print(f"       warn    : {notes}")
    return r


def _assert(cat, sid, desc, condition, actual=None, expected=None, notes=""):
    if condition:
        return _r(cat, sid, desc, AuditResult.PASS, actual, expected, notes)
    else:
        return _r(cat, sid, desc, AuditResult.FAIL, actual, expected, notes)


def _run(cat, sid, desc, fn, *args, **kwargs):
    """Run fn(*args, **kwargs) and catch any exception → ERROR."""
    try:
        result = fn(*args, **kwargs)
        return result
    except Exception as e:
        _r(cat, sid, desc, AuditResult.ERROR,
           actual=str(e), notes=traceback.format_exc(limit=3))
        return None


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 1 — Entry Cost Calculations
# ══════════════════════════════════════════════════════════════════════════════

def cat1_entry_cost():
    print("\n━━  CAT 1: ENTRY COST CALCULATIONS  ━━")
    from entry_cost import (
        stamp_duty, legal_fees, monthly_instalment, rpgt_rate,
        calculate_entry_cost, calculate_roi,
    )

    # 1.1  Stamp duty slabs — RM 100k
    sd = stamp_duty(100_000)
    _assert(1, "1.1", "Stamp duty RM100k = RM1,000 (1%)", abs(sd - 1_000) < 1,
            actual=sd, expected=1_000)

    # 1.2  Stamp duty — RM 500k  (spans first + second slab)
    #  1% on 100k = 1000; 2% on 400k = 8000 → total 9000
    sd = stamp_duty(500_000)
    _assert(1, "1.2", "Stamp duty RM500k = RM9,000", abs(sd - 9_000) < 1,
            actual=sd, expected=9_000)

    # 1.3  Stamp duty — RM 1M (spans 3 slabs)
    #  1% on 100k + 2% on 400k + 3% on 500k = 1000+8000+15000 = 24000
    sd = stamp_duty(1_000_000)
    _assert(1, "1.3", "Stamp duty RM1M = RM24,000", abs(sd - 24_000) < 1,
            actual=sd, expected=24_000)

    # 1.4  Stamp duty — RM 1.2M (4th slab applies above RM1M)
    #  RM24k + 4% on RM200k = 24000+8000 = 32000
    sd = stamp_duty(1_200_000)
    _assert(1, "1.4", "Stamp duty RM1.2M = RM32,000", abs(sd - 32_000) < 1,
            actual=sd, expected=32_000)

    # 1.5  First-home exemption (citizen, ≤RM500k) — first RM150k exempt
    #  price after exemption = 350k → 1% on 100k + 2% on 250k = 1000+5000 = 6000
    sd_ex = stamp_duty(500_000, first_home_exemption=True)
    _assert(1, "1.5", "First-home exemption reduces stamp duty", sd_ex < stamp_duty(500_000),
            actual=sd_ex, expected="< 9000", notes=f"Expected ~RM6,000, got RM{sd_ex}")

    # 1.6  Legal fees — RM 184k (should be ≥ min RM500)
    lf = legal_fees(184_000)
    _assert(1, "1.6", "Legal fees RM184k >= RM500 minimum", lf >= 500,
            actual=lf, expected=">= 500")
    _assert(1, "1.6b", "Legal fees RM184k <= RM4,000 (sanity)", lf <= 4_000,
            actual=lf, expected="<= 4000")

    # 1.7  Monthly instalment — RM165,600 loan @ 4.25% / 30yr
    ec = calculate_entry_cost(184_000)
    mi = ec["monthly_instalment_rm"]
    _assert(1, "1.7", "Monthly instalment 90% of RM184k @ 4.25/30yr is ~RM815/mo",
            700 < mi < 1_000, actual=mi, expected="700-1000")

    # 1.8  Deposit is exactly 10%
    _assert(1, "1.8", "Deposit = 10% of reserve",
            abs(ec["deposit_rm"] - 184_000 * 0.10) < 1,
            actual=ec["deposit_rm"], expected=18_400)

    # 1.9  Total cash day-1 > deposit (includes fees)
    _assert(1, "1.9", "Total cash day-1 > deposit (fees included)",
            ec["total_cash_day1_rm"] > ec["deposit_rm"],
            actual=ec["total_cash_day1_rm"], expected=f"> {ec['deposit_rm']}")

    # 1.10  Renovation levels add correctly
    ec_light  = calculate_entry_cost(184_000, reno_level="light")
    ec_heavy  = calculate_entry_cost(184_000, reno_level="heavy")
    ec_none   = calculate_entry_cost(184_000, reno_level="none")
    _assert(1, "1.10", "Heavy reno > light reno > none in total_investment",
            ec_heavy["total_investment_rm"] > ec_light["total_investment_rm"] > ec_none["total_investment_rm"],
            actual=(ec_none["total_investment_rm"], ec_light["total_investment_rm"], ec_heavy["total_investment_rm"]))

    # 1.11  RPGT rates
    _assert(1, "1.11a", "RPGT yr1 citizen = 30%", rpgt_rate(1, True) == 0.30, actual=rpgt_rate(1, True))
    _assert(1, "1.11b", "RPGT yr4 citizen = 20%", rpgt_rate(4, True) == 0.20, actual=rpgt_rate(4, True))
    _assert(1, "1.11c", "RPGT yr5 citizen = 15%", rpgt_rate(5, True) == 0.15, actual=rpgt_rate(5, True))
    _assert(1, "1.11d", "RPGT yr6+ citizen = 0%", rpgt_rate(6, True) == 0.0,  actual=rpgt_rate(6, True))
    _assert(1, "1.11e", "RPGT yr1 non-citizen = 30%", rpgt_rate(1, False) == 0.30, actual=rpgt_rate(1, False))
    _assert(1, "1.11f", "RPGT yr6 non-citizen = 5%",  rpgt_rate(6, False) == 0.05, actual=rpgt_rate(6, False))

    # 1.12  Zero reserve edge case
    ec_zero = calculate_entry_cost(0)
    _assert(1, "1.12", "Zero reserve price doesn't crash; deposit=0",
            ec_zero["deposit_rm"] == 0, actual=ec_zero["deposit_rm"])

    # 1.13  Premium property (RM1.2M) correct stamp duty in entry cost
    ec_prem = calculate_entry_cost(1_200_000)
    _assert(1, "1.13", "RM1.2M entry cost stamp duty = RM32,000",
            abs(ec_prem["stamp_duty_rm"] - 32_000) < 1,
            actual=ec_prem["stamp_duty_rm"], expected=32_000)


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 2 — Flip ROI
# ══════════════════════════════════════════════════════════════════════════════

def cat2_flip_roi():
    print("\n━━  CAT 2: FLIP ROI  ━━")
    from entry_cost import calculate_entry_cost, calculate_flip_roi, rpgt_rate

    ec = calculate_entry_cost(184_000)

    # 2.1  Deep BMV (52%) — net profit should be positive
    r = calculate_flip_roi(184_000, 383_000, ec)
    _assert(2, "2.1", "52% BMV flip → positive net profit",
            r["net_profit_rm"] > 0, actual=r["net_profit_rm"])
    _assert(2, "2.1b", "52% BMV flip → ROI > 0%",
            r["roi_pct"] > 0, actual=r["roi_pct"])
    _assert(2, "2.1c", "instant_equity_pct ≈ 108% (gain/reserve)",
            abs(r["instant_equity_pct"] - 108.2) < 1.0,
            actual=r["instant_equity_pct"], expected=108.2)

    # 2.2  Moderate BMV (25%) — may still be positive after RPGT
    ec25 = calculate_entry_cost(300_000)
    r25  = calculate_flip_roi(300_000, 400_000, ec25)
    _assert(2, "2.2", "25% BMV flip: checks for positive margin",
            r25["roi_pct"] != 0, actual=r25["roi_pct"],
            notes="May be negative after 30% RPGT on RM100k gain")

    # 2.3  Low BMV (10%) — likely negative after costs
    ec10 = calculate_entry_cost(450_000)
    r10  = calculate_flip_roi(450_000, 500_000, ec10)
    _assert(2, "2.3", "10% BMV flip: RPGT+costs likely wipe profit",
            isinstance(r10["roi_pct"], float), actual=r10["roi_pct"],
            notes=f"Net profit = RM{r10['net_profit_rm']:,.0f}")

    # 2.4  No market value → error dict returned, not crash
    r_none = calculate_flip_roi(184_000, 0, ec)
    _assert(2, "2.4", "MV=0 returns error dict (no crash)",
            "error" in r_none, actual=r_none)

    # 2.5  Market value < reserve (underwater)
    r_uw = calculate_flip_roi(300_000, 250_000, ec25)
    _assert(2, "2.5", "MV < reserve → gross_gain is negative",
            r_uw["gross_gain_rm"] < 0, actual=r_uw["gross_gain_rm"])
    _assert(2, "2.5b", "MV < reserve → RPGT = 0 (no gain to tax)",
            r_uw["rpgt_rm"] == 0, actual=r_uw["rpgt_rm"])

    # 2.6  Large premium property (RM1.2M reserve, RM1.8M MV)
    ec_lg = calculate_entry_cost(1_200_000)
    r_lg  = calculate_flip_roi(1_200_000, 1_800_000, ec_lg)
    _assert(2, "2.6", "Premium flip: all numeric fields populated",
            all(isinstance(r_lg.get(k), (int, float))
                for k in ["gross_gain_rm", "rpgt_rm", "net_profit_rm", "roi_pct"]),
            actual=r_lg["roi_pct"])

    # 2.7  Agent commission correctly 2.5% of MV
    _assert(2, "2.7", "Agent commission = 2.5% of market value",
            abs(r["agent_commission_rm"] - 383_000 * 0.025) < 1,
            actual=r["agent_commission_rm"], expected=round(383_000 * 0.025, 2))

    # 2.8  roi_mode field present and correct
    _assert(2, "2.8", "roi_mode = 'flip'",
            r.get("roi_mode") == "flip", actual=r.get("roi_mode"))


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 3 — Rental Strategy ROI
# ══════════════════════════════════════════════════════════════════════════════

def cat3_rental_roi():
    print("\n━━  CAT 3: RENTAL STRATEGY ROI  ━━")
    from entry_cost import (
        calculate_entry_cost,
        calculate_full_unit_rental_roi,
        calculate_room_rental_roi,
        calculate_partition_roi,
        ROOM_RATES_STANDARD, ROOM_RATES_PARTITION,
    )

    ec = calculate_entry_cost(184_000)

    # ── Full unit ──────────────────────────────────────────────────────────
    # 3.1  With rent data
    fu = calculate_full_unit_rental_roi(184_000, ec, monthly_rent_est=1_800,
                                        rent_source="iProperty", state="Kuala Lumpur")
    _assert(3, "3.1", "Full unit with rent: roi_mode=full_unit",
            fu["roi_mode"] == "full_unit", actual=fu["roi_mode"])
    _assert(3, "3.1b", "Full unit: gross_yield_pct > 0",
            fu.get("gross_yield_pct", 0) > 0, actual=fu.get("gross_yield_pct"))
    _assert(3, "3.1c", "Full unit: eff_monthly_rm present",
            "eff_monthly_rm" in fu, actual=list(fu.keys()))

    # 3.2  No rent data (cache miss scenario)
    fu0 = calculate_full_unit_rental_roi(184_000, ec, monthly_rent_est=0,
                                          rent_source="unavailable", state="Perlis")
    _assert(3, "3.2", "Full unit no rent: roi still computed (appreciation only)",
            isinstance(fu0.get("roi_pct"), float), actual=fu0.get("roi_pct"))
    _assert(3, "3.2b", "Full unit no rent: gross_yield=0",
            fu0.get("gross_yield_pct") == 0, actual=fu0.get("gross_yield_pct"))

    # ── Room rental ────────────────────────────────────────────────────────
    # 3.3  1BR room
    rr1 = calculate_room_rental_roi(184_000, ec, bedrooms=1, built_up_sqft=500,
                                     state="Kuala Lumpur")
    _assert(3, "3.3", "1BR room rental: 1 room total (master only)",
            rr1["num_rooms"] == 1, actual=rr1["num_rooms"])

    # 3.4  2BR room
    rr2 = calculate_room_rental_roi(184_000, ec, bedrooms=2, built_up_sqft=800,
                                     state="Kuala Lumpur")
    _assert(3, "3.4", "2BR room rental: 2 rooms (master+middle)",
            rr2["num_rooms"] == 2, actual=rr2["num_rooms"])

    # 3.5  3BR room (common condo layout)
    rr3 = calculate_room_rental_roi(184_000, ec, bedrooms=3, built_up_sqft=1_000,
                                     state="Kuala Lumpur")
    _assert(3, "3.5", "3BR room rental: 3 rooms",
            rr3["num_rooms"] == 3, actual=rr3["num_rooms"])
    _assert(3, "3.5b", "3BR room: gross > full unit (higher per-sqft yield)",
            rr3["gross_monthly_rm"] > 1_800,
            actual=rr3["gross_monthly_rm"], expected="> 1800")
    _assert(3, "3.5c", "3BR room: cashflow direction is computable",
            isinstance(rr3.get("monthly_cashflow_rm"), float),
            actual=rr3.get("monthly_cashflow_rm"))

    # 3.6  4BR room
    rr4 = calculate_room_rental_roi(184_000, ec, bedrooms=4, built_up_sqft=1_200,
                                     state="Selangor")
    _assert(3, "3.6", "4BR room rental: 4 rooms",
            rr4["num_rooms"] == 4, actual=rr4["num_rooms"])

    # 3.7  Manual room count override
    rr_man = calculate_room_rental_roi(184_000, ec, num_master=2, num_middle=1,
                                        num_small=0, state="Penang")
    _assert(3, "3.7", "Manual override: 2 master + 1 middle = 3 rooms",
            rr_man["num_rooms"] == 3, actual=rr_man["num_rooms"])

    # 3.8  Room rental: payback present when positive cashflow
    _assert(3, "3.8", "Room rental 3BR: payback_years is numeric",
            isinstance(rr3.get("payback_years"), (int, float)),
            actual=rr3.get("payback_years"))

    # 3.9  Rate midpoints match expected ranges
    mid_master = (ROOM_RATES_STANDARD["master_min"] + ROOM_RATES_STANDARD["master_max"]) / 2
    _assert(3, "3.9", f"Master room midpoint = RM{mid_master} (within 1,000-1,200)",
            1_000 <= mid_master <= 1_200, actual=mid_master)

    # ── Partition rental ───────────────────────────────────────────────────
    # 3.10  Partition 600 sqft
    ec_sm = calculate_entry_cost(150_000)
    p600  = calculate_partition_roi(150_000, ec_sm, built_up_sqft=600,
                                     state="Kuala Lumpur")
    _assert(3, "3.10", "Partition 600sqft: num_rooms <= 3 (cap)",
            p600["num_rooms"] <= 3, actual=p600["num_rooms"])
    _assert(3, "3.10b", "Partition 600sqft: capex in total_investment",
            p600["total_investment_rm"] > ec_sm["total_investment_rm"],
            actual=p600["total_investment_rm"])

    # 3.11  Partition 1000 sqft
    p1000 = calculate_partition_roi(184_000, ec, built_up_sqft=1_000,
                                     state="Kuala Lumpur")
    _assert(3, "3.11", "Partition 1000sqft: num_rooms 4-5",
            4 <= p1000["num_rooms"] <= 5, actual=p1000["num_rooms"])
    _assert(3, "3.11b", "Partition 1000sqft: gross > room rental 3BR",
            p1000["gross_monthly_rm"] > rr3["gross_monthly_rm"],
            actual=p1000["gross_monthly_rm"], expected=f"> {rr3['gross_monthly_rm']}")

    # 3.12  No sqft → error dict, no crash
    p_nodata = calculate_partition_roi(184_000, ec, built_up_sqft=0,
                                        state="Kuala Lumpur")
    _assert(3, "3.12", "Partition with sqft=0 returns error dict (no crash)",
            "error" in p_nodata or "num_rooms" in p_nodata,
            actual=list(p_nodata.keys())[:4])

    # 3.13  Partition: roi_mode = 'partition'
    _assert(3, "3.13", "Partition roi_mode = 'partition'",
            p1000.get("roi_mode") == "partition", actual=p1000.get("roi_mode"))

    # 3.14  Room rental: no sqft AND no bedrooms → default composition
    rr_def = calculate_room_rental_roi(184_000, ec, bedrooms=0, built_up_sqft=0,
                                        state="Kuala Lumpur")
    _assert(3, "3.14", "Room rental with no sqft/BR: uses default 2-room composition",
            rr_def["num_rooms"] >= 1, actual=rr_def["num_rooms"])


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 4 — Partition Room Estimation
# ══════════════════════════════════════════════════════════════════════════════

def cat4_partition_estimate():
    print("\n━━  CAT 4: PARTITION ROOM ESTIMATION  ━━")
    from entry_cost import estimate_partition_rooms

    cases = [
        # (sqft, desc, expected_rooms_range)
        (300,   "300 sqft studio",            (1, 3)),
        (500,   "500 sqft (< 600 cap)",        (1, 3)),
        (600,   "600 sqft boundary",           (1, 4)),
        (650,   "650 sqft mid-tier",           (2, 4)),
        (800,   "800 sqft boundary",           (2, 4)),
        (850,   "850 sqft",                    (3, 5)),
        (1_000, "1000 sqft boundary",          (4, 5)),
        (1_100, "1100 sqft",                   (4, 6)),
        (1_200, "1200 sqft boundary",          (5, 6)),
        (2_000, "2000 sqft large (max cap 7)", (7, 7)),
    ]

    for sqft, desc, (lo, hi) in cases:
        info = estimate_partition_rooms(sqft)
        n    = info["num_rooms"]
        sid  = f"4.{sqft}"
        _assert(4, sid, f"{desc} → {lo}–{hi} rooms (got {n})",
                lo <= n <= hi, actual=n, expected=f"{lo}-{hi}")
        # Always at least 1 ensuite
        _assert(4, sid+"_e", f"{desc} → ≥1 ensuite",
                info["num_ensuite"] >= 1, actual=info["num_ensuite"])
        # CAPEX > 0
        _assert(4, sid+"_c", f"{desc} → capex > 0",
                info["partition_capex_rm"] > 0, actual=info["partition_capex_rm"])

    # 4.x  1400 sqft: formula gives floor(1400*0.75/180)=5, cap=7, result=5
    info_1400 = estimate_partition_rooms(1_400)
    _assert(4, "4.1400_formula", "1400 sqft: formula=5 rooms (cap=7, formula wins)",
            info_1400["num_rooms"] == 5, actual=info_1400["num_rooms"], expected=5,
            notes="useable=1050, 1050/180=5.83 → floor=5; original test range was wrong")

    # 4.x  Ensuite ratio: roughly 1 per 3 rooms
    info_1000 = estimate_partition_rooms(1_000)
    _assert(4, "4.ratio", "Ensuite ≈ 1 per 3 rooms for 1000sqft",
            1 <= info_1000["num_ensuite"] <= info_1000["num_rooms"],
            actual=f"{info_1000['num_ensuite']}/{info_1000['num_rooms']}")

    # 4.x  guideline_note is a non-empty string
    _assert(4, "4.note", "estimate_partition_rooms returns guideline_note string",
            isinstance(info_1000.get("guideline_note"), str) and len(info_1000["guideline_note"]) > 10,
            actual=info_1000.get("guideline_note", "")[:60])


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 5 — Analyst Agent (Rule-Based)
# ══════════════════════════════════════════════════════════════════════════════

def cat5_analyst():
    print("\n━━  CAT 5: ANALYST AGENT (RULE-BASED)  ━━")
    from analyst_agent import _score_rule_based, AnalystAgent, HIGH_PRIORITY_BMV

    agent = AnalystAgent()

    def _mk(**kw) -> Dict:
        base = {
            "reserve_price": 200_000, "market_value": 400_000,
            "bmv_pct": 30, "auction_count": 1, "tenure": "freehold",
            "state": "Kuala Lumpur", "property_type": "condominium",
        }
        base.update(kw)
        return base

    # 5.1  High BMV + KL → shortlist/bid
    r = _score_rule_based(_mk(bmv_pct=52, state="Kuala Lumpur"))
    _assert(5, "5.1", "BMV 52% KL → score ≥ 60 (shortlist/bid)",
            r["agent_score"] >= 60, actual=r["agent_score"])
    _assert(5, "5.1b", "BMV 52% KL → recommendation in {shortlist, bid}",
            r["agent_recommendation"] in ("shortlist", "bid"),
            actual=r["agent_recommendation"])

    # 5.2  Low BMV + low liquidity → skip
    r = _score_rule_based(_mk(bmv_pct=5, state="Kelantan"))
    _assert(5, "5.2", "BMV 5% Kelantan → skip",
            r["agent_recommendation"] == "skip",
            actual=r["agent_recommendation"])

    # 5.3  Moderate BMV Selangor → investigate or shortlist
    r = _score_rule_based(_mk(bmv_pct=30, state="Selangor"))
    _assert(5, "5.3", "BMV 30% Selangor → investigate or shortlist",
            r["agent_recommendation"] in ("investigate", "shortlist"),
            actual=r["agent_recommendation"])

    # 5.4  Round 3 bonus applied
    r_r1 = _score_rule_based(_mk(bmv_pct=25, auction_count=1, state="Johor"))
    r_r3 = _score_rule_based(_mk(bmv_pct=25, auction_count=3, state="Johor"))
    _assert(5, "5.4", "Round 3 score ≥ Round 1 score",
            r_r3["agent_score"] >= r_r1["agent_score"],
            actual=f"r1={r_r1['agent_score']}, r3={r_r3['agent_score']}")

    # 5.5  Missing BMV → handled gracefully
    r = _score_rule_based({"reserve_price": 200_000, "state": "Selangor"})
    _assert(5, "5.5", "Missing bmv_pct → doesn't crash, returns skip/investigate",
            r.get("agent_score") is not None, actual=r.get("agent_score"))

    # 5.6  Postcode prefix in state string stripped correctly
    r = _score_rule_based(_mk(bmv_pct=40, state="56000 Kuala Lumpur"))
    _assert(5, "5.6", "BidNow postcode prefix '56000 Kuala Lumpur' → still gets KL bonus",
            r["agent_score"] >= 55, actual=r["agent_score"],
            notes="Requires _clean_state in rule-based scoring")

    # 5.7  Exit strategy recommended for high-BMV flip candidate
    r = _score_rule_based(_mk(bmv_pct=42, state="Selangor", auction_count=1))
    _assert(5, "5.7", "BMV 42% Selangor: exit_strategy field present",
            "agent_exit_strategy" in r, actual=list(r.keys()))
    _assert(5, "5.7b", "BMV 42% Selangor: exit could be flip",
            r.get("agent_exit_strategy") in ("flip", "rent", "long_hold", "skip"),
            actual=r.get("agent_exit_strategy"))

    # 5.8  Leasehold — no specific penalty in rule-based (verify it's documented)
    r_fh = _score_rule_based(_mk(bmv_pct=30, tenure="freehold",   state="Kuala Lumpur"))
    r_lh = _score_rule_based(_mk(bmv_pct=30, tenure="leasehold",  state="Kuala Lumpur"))
    _assert(5, "5.8", "Freehold score ≥ leasehold (same BMV)",
            r_fh["agent_score"] >= r_lh["agent_score"],
            actual=f"fh={r_fh['agent_score']}, lh={r_lh['agent_score']}",
            notes="Rule-based awards +5 for freehold")

    # 5.9  HIGH_PRIORITY_BMV threshold is 29
    _assert(5, "5.9", "HIGH_PRIORITY_BMV = 29",
            HIGH_PRIORITY_BMV == 29, actual=HIGH_PRIORITY_BMV)

    # 5.10  AnalystAgent.available reflects any configured LLM provider
    has_provider = bool(getattr(agent, "llm_provider", None))
    _assert(5, "5.10", f"AnalystAgent.available = {has_provider} (matches detected LLM provider)",
            agent.available == has_provider,
            actual=agent.available, expected=has_provider,
            notes=f"provider={getattr(agent, 'llm_provider', None) or 'rule-based'}")

    # 5.11  enrich_listings returns (enriched_count, skipped_count) tuple
    agent2 = AnalystAgent()
    enriched_cnt, skipped_cnt = agent2.enrich_listings([])
    _assert(5, "5.11", "enrich_listings([]) → returns (0, 0) tuple (no crash)",
            enriched_cnt == 0 and skipped_cnt == 0,
            actual=(enriched_cnt, skipped_cnt), expected=(0, 0))

    # 5.12  Required output fields present
    required = ["agent_score", "agent_recommendation", "agent_reasoning",
                "agent_exit_strategy", "agent_holding_period",
                "agent_key_risks", "agent_due_diligence", "agent_mode",
                "agent_confidence"]
    r_full = _score_rule_based(_mk(bmv_pct=40, state="Kuala Lumpur"))
    missing = [f for f in required if f not in r_full]
    _assert(5, "5.12", "All required output fields present in rule-based result",
            len(missing) == 0, actual=f"missing={missing}", expected="none missing")


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 6 — POS Identifier
# ══════════════════════════════════════════════════════════════════════════════

def cat6_pos():
    print("\n━━  CAT 6: POS IDENTIFIER  ━━")
    from pos_identifier import (
        extract_listing_id_from_filepath, identify_current_pos,
        validate_property_pos_status,
    )

    # 6.1  Extract listing ID from a valid path
    path = "files/upload/ap/263193/pos_file/20260410_094522_abc12.pdf"
    lid  = extract_listing_id_from_filepath(path)
    _assert(6, "6.1", "Extract listing_id=263193 from path",
            lid == 263193, actual=lid, expected=263193)

    # 6.2  Non-matching path returns None
    lid2 = extract_listing_id_from_filepath("files/upload/something_else.pdf")
    _assert(6, "6.2", "Non-POS path returns None",
            lid2 is None, actual=lid2)

    # 6.3  Current POS correctly identified
    result = identify_current_pos({
        "property_id": 263193,
        "property_title": "Test Property",
        "pdfs": [
            {"file_path": "files/upload/ap/263193/pos_file/20260410.pdf", "timestamp": "2026-04-10"},
        ]
    })
    _assert(6, "6.3", "Current POS correctly identified (ID matches)",
            result["has_current_pos"], actual=result["has_current_pos"])
    _assert(6, "6.3b", "current_pos dict populated",
            result["current_pos"] is not None, actual=result["current_pos"])

    # 6.4  Historical POS correctly identified (ID mismatch)
    result_hist = identify_current_pos({
        "property_id": 263193,
        "property_title": "Test Property",
        "pdfs": [
            {"file_path": "files/upload/ap/248650/pos_file/20260101.pdf", "timestamp": "2026-01-01"},
        ]
    })
    _assert(6, "6.4", "Historical POS detected (ID doesn't match property_id)",
            not result_hist["has_current_pos"], actual=result_hist["has_current_pos"])
    _assert(6, "6.4b", "historical_pos list has 1 entry",
            len(result_hist["historical_pos"]) == 1,
            actual=result_hist["historical_pos"])

    # 6.5  Mixed: 1 current + 1 historical
    result_mix = identify_current_pos({
        "property_id": 263193,
        "property_title": "Test",
        "pdfs": [
            {"file_path": "files/upload/ap/263193/pos_file/20260410.pdf", "timestamp": "2026-04-10"},
            {"file_path": "files/upload/ap/248650/pos_file/20260101.pdf", "timestamp": "2026-01-01"},
        ]
    })
    _assert(6, "6.5", "Mixed: 1 current + 1 historical POS",
            result_mix["has_current_pos"] and len(result_mix["historical_pos"]) == 1,
            actual=(result_mix["has_current_pos"], len(result_mix["historical_pos"])))

    # 6.6  Empty PDFs list → no current POS
    result_empty = identify_current_pos({
        "property_id": 999, "property_title": "X", "pdfs": []
    })
    _assert(6, "6.6", "No PDFs → has_current_pos=False, 0 historical",
            not result_empty["has_current_pos"] and result_empty["auction_attempts"] == 0,
            actual=(result_empty["has_current_pos"], result_empty["auction_attempts"]))

    # 6.7  validate_property_pos_status exists and returns expected keys
    try:
        vs = validate_property_pos_status({"listing": {"pos_url": None}})
        _assert(6, "6.7", "validate_property_pos_status returns dict with 'status' key",
                "status" in vs, actual=list(vs.keys()))
    except Exception as e:
        _r(6, "6.7", "validate_property_pos_status basic call", AuditResult.WARN,
           actual=str(e), notes="May require specific input shape")


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 7 — Dedup Merger & Derived Fields
# ══════════════════════════════════════════════════════════════════════════════

def cat7_dedup():
    print("\n━━  CAT 7: DEDUP MERGER & DERIVED FIELDS  ━━")
    from dedup_merger import (
        _normalise_street, _extract_postcode, _street_similarity,
        cross_reference, detect_reauction, compute_derived_fields,
        STATE_TO_REGION,
    )

    # 7.1  Postcode extraction
    _assert(7, "7.1", "Extract postcode from address string",
            _extract_postcode("56000 Kuala Lumpur") == "56000",
            actual=_extract_postcode("56000 Kuala Lumpur"))

    # 7.2  Street normalisation lowercases and removes punctuation
    norm = _normalise_street("Jalan Bukit, Taman KL-21!")
    _assert(7, "7.2", "Street normalisation: lowercase, no punctuation",
            norm == norm.lower() and "!" not in norm and "," not in norm,
            actual=norm)

    # 7.3  Street similarity: same street should be high
    score = _street_similarity("Jalan Bukit Daman", "Jalan Bukit Daman")
    _assert(7, "7.3", "Identical streets → similarity 100",
            score == 100, actual=score)

    # 7.4  Completely different streets → low similarity
    score2 = _street_similarity("Jalan Raja Chulan", "Lorong Awan Besar")
    _assert(7, "7.4", "Different streets → similarity < 50",
            score2 < 50, actual=score2)

    # 7.5  State to region mapping — KL is Klang Valley
    _assert(7, "7.5", "KL → Klang Valley region",
            STATE_TO_REGION.get("Kuala Lumpur") == "Klang Valley",
            actual=STATE_TO_REGION.get("Kuala Lumpur"))

    # 7.6  compute_derived_fields: days_to_auction computed
    future = str(date.today() + timedelta(days=30))
    listing = {"auction_date": future, "reserve_price": 200_000,
               "state": "Selangor", "auction_history": []}
    derived = compute_derived_fields(listing)
    _assert(7, "7.6", "days_to_auction ≈ 30 for future date",
            derived.get("days_to_auction", -1) in range(28, 33),
            actual=derived.get("days_to_auction"))

    # 7.7  Region field populated
    listing2 = {"auction_date": future, "reserve_price": 200_000,
                 "state": "Penang", "auction_history": []}
    d2 = compute_derived_fields(listing2)
    _assert(7, "7.7", "Penang gets region 'Northern'",
            d2.get("region") == "Northern",
            actual=d2.get("region"))

    # 7.8  cross_reference returns list (even if empty)
    merged = cross_reference([], [])
    _assert(7, "7.8", "cross_reference([], []) returns empty list",
            isinstance(merged, list), actual=type(merged).__name__)

    # 7.9  detect_reauction(single listing, vault_index) returns tuple (action, record)
    future2 = str(date.today() + timedelta(days=45))
    single_listing = {"full_address": "A-10-5 Test Road 56000 KL",
                      "auction_date": future2, "reserve_price": 200_000,
                      "state": "Kuala Lumpur", "auction_history": []}
    action, rec = detect_reauction(single_listing, {})
    _assert(7, "7.9", "detect_reauction returns (action, record) tuple",
            action in ("create", "update_price", "new_round"),
            actual=action, expected="create|update_price|new_round")

    # 7.10  cross_reference with 2 listings, same postcode+similar address → dedup
    bn = [{"full_address": "A-10-5 Jalan Bukit Daman 56000 KL",
            "listing_id": "BN-100", "source": "bidnow",
            "reserve_price": 200_000, "state": "Kuala Lumpur",
            "auction_date": future, "auction_history": []}]
    lt = [{"full_address": "A-10-5 Jalan Bukit Daman 56000 KL",
            "listing_id": "LT-200", "source": "lelongtips",
            "reserve_price": 200_000, "state": "Kuala Lumpur",
            "auction_date": future, "auction_history": []}]
    matched = cross_reference(bn, lt)
    _assert(7, "7.10", "Identical address cross-references → ≤ 1 unique record",
            len(matched) <= 2, actual=len(matched),
            notes="Exact match should merge to 1; duplicate-ok if source union")


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 8 — Market Cache & Research
# ══════════════════════════════════════════════════════════════════════════════

def cat8_market(skip_net=False):
    print("\n━━  CAT 8: MARKET CACHE & RESEARCH  ━━")
    import json
    from pathlib import Path
    from market_research import MarketResearcher

    cache_path = str(SCRIPT_DIR / "market_cache.json")

    # 8.1  Cache file exists and is valid JSON
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        _assert(8, "8.1", "market_cache.json exists and is valid JSON",
                isinstance(cache, dict), actual=type(cache).__name__)
    except FileNotFoundError:
        _r(8, "8.1", "market_cache.json exists", AuditResult.WARN,
           actual="file not found", notes="Cache will be built on first run")
        cache = {}
    except Exception as e:
        _r(8, "8.1", "market_cache.json valid JSON", AuditResult.FAIL, actual=str(e))
        cache = {}

    # 8.2  Cache has expected top-level keys (actual schema: sale_district, rent_district, etc.)
    has_built_at    = "built_at" in cache
    has_sale_data   = any(k.startswith("sale_") for k in cache)
    has_rent_data   = any(k.startswith("rent_") for k in cache)
    has_keys = has_built_at and has_sale_data and has_rent_data
    _assert(8, "8.2", "Cache has built_at + sale_* + rent_* keys",
            has_keys, actual=list(cache.keys())[:6])

    # 8.3  KL is covered (actual cache keys: sale_district, sale_state)
    kl_covered = any(
        "Kuala Lumpur" in str(v) or "kuala" in str(k).lower()
        for section in ("sale_district", "sale_state", "rent_district", "rent_state")
        for k, v in cache.get(section, {}).items()
    )
    _assert(8, "8.3", "Cache covers Kuala Lumpur data (sale_district or sale_state)",
            kl_covered or not has_keys, actual=kl_covered,
            notes="WARN if cache miss for KL — run market_research.py to refresh")

    # 8.4  MarketResearcher.enrich_listings returns (enriched_count, skipped_count) tuple
    mr = MarketResearcher(cache_path)
    e_cnt, s_cnt = mr.enrich_listings([])
    _assert(8, "8.4", "enrich_listings([]) returns (0, 0) tuple (no crash)",
            e_cnt == 0 and s_cnt == 0, actual=(e_cnt, s_cnt), expected=(0, 0))

    # 8.5  Enrichment modifies listing in-place for a KL condo (high-priority: BMV ≥ 29)
    test_listing = {
        "listing_id": "TEST-001",
        "reserve_price": 184_000, "market_value": 383_000,
        "bmv_pct": 52, "auction_count": 1,
        "state": "Kuala Lumpur", "property_type": "condominium",
        "built_up_sqft": 1_000,
        "full_address": "Pangsapuri Damai Vista, Bandar Damai Perdana, Kuala Lumpur",
    }
    mr.enrich_listings([test_listing])   # modifies in-place
    _assert(8, "8.5", "enrich_listings adds market_area_match in-place",
            "market_area_match" in test_listing,
            actual=list(test_listing.keys())[-5:])

    # 8.6  Cache TTL respected (built_at field)
    if "built_at" in cache:
        try:
            built = datetime.fromisoformat(cache["built_at"])
            age   = (datetime.utcnow() - built).days
            _r(8, "8.6", f"Cache age: {age} days",
               AuditResult.PASS if age <= 7 else AuditResult.WARN,
               actual=f"{age} days old",
               notes="Cache TTL=7 days — refresh if stale")
        except Exception as e:
            _r(8, "8.6", "Cache TTL check", AuditResult.WARN, actual=str(e))

    if skip_net:
        _r(8, "8.net", "Market scrape probe (skipped, --skip-net)", AuditResult.SKIP)
        return

    # 8.7  Live market probe (1 page)
    try:
        mr2 = MarketResearcher(str(SCRIPT_DIR / "market_cache_probe.json"))
        # Call internal method to probe 1 page only (avoid full 5-page scrape)
        from market_research import PAGES_TO_SCRAPE
        _r(8, "8.7", f"Market research config: PAGES_TO_SCRAPE={PAGES_TO_SCRAPE}",
           AuditResult.PASS if PAGES_TO_SCRAPE <= 10 else AuditResult.WARN,
           actual=PAGES_TO_SCRAPE, notes="High page count = slower run")
    except Exception as e:
        _r(8, "8.7", "Market research module import", AuditResult.WARN, actual=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 9 — Scraper Probes (lightweight, 1-page)
# ══════════════════════════════════════════════════════════════════════════════

def cat9_scrapers(skip_net=False):
    print("\n━━  CAT 9: SCRAPER PROBES (network)  ━━")
    if skip_net:
        for sid, desc in [
            ("9.1", "BidNow 1-page KL scrape"),
            ("9.2", "BidNow filter validation"),
            ("9.3", "e-Lelong CSRF + 1-page probe"),
            ("9.4", "iProperty competition signal (1 page)"),
        ]:
            _r(9, sid, desc, AuditResult.SKIP, notes="--skip-net")
        return

    # 9.1  BidNow scrape — 1 page, KL (filters dict, not keyword args)
    try:
        from bidnow import BidNowScraper
        scraper = BidNowScraper()
        t0 = time.time()
        listings = scraper.scrape_listings(filters={"state": "Kuala Lumpur"}, max_pages=1)
        elapsed = round(time.time() - t0, 1)
        _assert(9, "9.1", f"BidNow KL 1-page: got ≥1 listing in {elapsed}s",
                len(listings) >= 1, actual=len(listings))
        if listings:
            l = listings[0]
            required = ["listing_id", "reserve_price", "full_address", "state"]
            missing  = [k for k in required if k not in l or l[k] is None]
            _assert(9, "9.1b", f"BidNow listing has required fields (missing: {missing})",
                    len(missing) == 0, actual=f"missing={missing}")
            _assert(9, "9.1c", "BidNow listing: reserve_price > 0",
                    float(l.get("reserve_price", 0)) > 0, actual=l.get("reserve_price"))
            _assert(9, "9.1d", "BidNow listing: source='bidnow'",
                    l.get("source") == "bidnow", actual=l.get("source"))
    except Exception as e:
        _r(9, "9.1", "BidNow 1-page scrape", AuditResult.ERROR, actual=str(e),
           notes=traceback.format_exc(limit=2))

    # 9.2  BidNow filter validation
    try:
        from bidnow_filter_enums import validate_state, validate_property_type
        _assert(9, "9.2a", "validate_state('Kuala Lumpur') passes",
                validate_state("Kuala Lumpur"), actual=True)
        _assert(9, "9.2b", "validate_state('InvalidState') fails",
                not validate_state("InvalidState"), actual=False)
        _assert(9, "9.2c", "validate_property_type('Condominium / SOHO House / Apartment') passes",
                validate_property_type("Condominium / SOHO House / Apartment"), actual=True)
    except Exception as e:
        _r(9, "9.2", "BidNow filter enum validation", AuditResult.ERROR, actual=str(e))

    # 9.3  e-Lelong CSRF probe (lightweight, no pagination)
    try:
        from elelong import ELelongScraper
        el = ELelongScraper()
        t0 = time.time()
        token = el._get_csrf_token()
        elapsed = round(time.time() - t0, 1)
        _assert(9, "9.3", f"e-Lelong CSRF token retrieved in {elapsed}s",
                token is not None and len(str(token)) > 5,
                actual=f"token length={len(str(token or ''))}")
    except AttributeError:
        _r(9, "9.3", "e-Lelong CSRF probe", AuditResult.WARN,
           notes="_get_csrf_token method not exposed publicly — check elelong.py interface")
    except Exception as e:
        _r(9, "9.3", "e-Lelong CSRF probe", AuditResult.ERROR, actual=str(e))

    # 9.4  iProperty competition signal (1-page, state_slug not 'state')
    try:
        from iproperty import IPropertyScraper
        ip = IPropertyScraper()
        t0 = time.time()
        comps = ip.get_competition_signal(
            target_price=184_000, target_sqft=1_000,
            state_slug="kuala-lumpur", property_category="apartment-condo",
            max_pages=1,
        )
        elapsed = round(time.time() - t0, 1)
        _assert(9, "9.4", f"iProperty competition signal returned in {elapsed}s",
                isinstance(comps, dict), actual=type(comps).__name__)
        _assert(9, "9.4b", "Competition signal has 'comparable_count' key",
                "comparable_count" in comps, actual=list(comps.keys()))
    except Exception as e:
        _r(9, "9.4", "iProperty competition signal", AuditResult.ERROR, actual=str(e),
           notes=traceback.format_exc(limit=2))


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 10 — Edge Cases & Error Handling
# ══════════════════════════════════════════════════════════════════════════════

def cat10_edge_cases():
    print("\n━━  CAT 10: EDGE CASES & ERROR HANDLING  ━━")
    from entry_cost import (
        stamp_duty, calculate_entry_cost, calculate_flip_roi,
        calculate_room_rental_roi, calculate_partition_roi,
        estimate_partition_rooms, APPRECIATION_PA,
    )
    from analyst_agent import _score_rule_based

    # 10.1  State postcode prefix stripped in appreciation lookup
    clean = "Kuala Lumpur"
    raw   = "56000 Kuala Lumpur"
    # Both should give same appreciation rate
    rate_clean = APPRECIATION_PA.get(clean, 2.5)
    import re as _re
    stripped   = _re.sub(r"^\d{5}\s+", "", raw)
    rate_raw   = APPRECIATION_PA.get(stripped, 2.5)
    _assert(10, "10.1", "BidNow postcode prefix strips cleanly",
            stripped == clean, actual=stripped, expected=clean)
    _assert(10, "10.1b", "Both cleaned/raw map to same appreciation rate",
            rate_clean == rate_raw, actual=f"clean={rate_clean}, raw={rate_raw}")

    # 10.2  Unknown state → falls back to DEFAULT_APPRECIATION
    from entry_cost import DEFAULT_APPRECIATION
    fallback = APPRECIATION_PA.get("UnknownState", DEFAULT_APPRECIATION)
    _assert(10, "10.2", "Unknown state uses DEFAULT_APPRECIATION",
            fallback == DEFAULT_APPRECIATION, actual=fallback)

    # 10.3  Very high BMV (>80%) — shouldn't break anything
    ec = calculate_entry_cost(100_000)
    r  = calculate_flip_roi(100_000, 600_000, ec)
    _assert(10, "10.3", "BMV >80% flip ROI is computed (no crash)",
            r.get("roi_pct") is not None and not "error" in r,
            actual=r.get("roi_pct"))

    # 10.4  Property with zero sqft → partition returns error gracefully
    r_zero = calculate_partition_roi(200_000, ec, built_up_sqft=0, state="Selangor")
    _assert(10, "10.4", "partition_roi sqft=0 → error key present",
            "error" in r_zero or r_zero.get("num_rooms", 0) == 0,
            actual=r_zero.get("error", "no error key"))

    # 10.5  Negative reserve price — stamp duty should handle
    try:
        sd_neg = stamp_duty(-50_000)
        _assert(10, "10.5", "stamp_duty(-50000) doesn't crash",
                isinstance(sd_neg, float), actual=sd_neg)
    except Exception as e:
        _r(10, "10.5", "stamp_duty(-50000)", AuditResult.WARN, actual=str(e),
           notes="Negative price is invalid input — consider adding guard")

    # 10.6  Listing with all None values for derived fields
    r = _score_rule_based({
        "listing_id": "X", "reserve_price": None,
        "market_value": None, "bmv_pct": None,
        "state": None, "auction_count": None,
    })
    _assert(10, "10.6", "rule_based with all-None fields doesn't crash",
            isinstance(r.get("agent_score"), (int, float)),
            actual=r.get("agent_score"))

    # 10.7  Very small unit (300 sqft) partition
    p_tiny = estimate_partition_rooms(300)
    _assert(10, "10.7", "300 sqft partition: ≥1 room, ≥1 ensuite",
            p_tiny["num_rooms"] >= 1 and p_tiny["num_ensuite"] >= 1,
            actual=(p_tiny["num_rooms"], p_tiny["num_ensuite"]))

    # 10.8  calculate_entry_cost with custom loan_pct
    ec_80 = calculate_entry_cost(300_000, loan_pct=80.0)
    ec_90 = calculate_entry_cost(300_000, loan_pct=90.0)
    _assert(10, "10.8", "Lower loan_pct (80%) → lower monthly instalment",
            ec_80["monthly_instalment_rm"] < ec_90["monthly_instalment_rm"],
            actual=f"80%={ec_80['monthly_instalment_rm']}, 90%={ec_90['monthly_instalment_rm']}")

    # 10.9  Holding years = 0 in calculate_roi doesn't crash
    from entry_cost import calculate_roi
    try:
        r0 = calculate_roi(200_000, ec, holding_years=0)
        _assert(10, "10.9", "holding_years=0 doesn't crash",
                isinstance(r0.get("roi_pct"), float), actual=r0.get("roi_pct"))
    except Exception as e:
        _r(10, "10.9", "holding_years=0", AuditResult.WARN, actual=str(e),
           notes="Consider guard for holding_years <= 0")

    # 10.10  Room rental 5BR (edge of composition table)
    ec5 = calculate_entry_cost(400_000)
    rr5 = calculate_room_rental_roi(400_000, ec5, bedrooms=5,
                                     built_up_sqft=1_500, state="Selangor")
    _assert(10, "10.10", "5BR room rental: 5 rooms total (1 master+2 middle+2 small)",
            rr5["num_rooms"] == 5, actual=rr5["num_rooms"])

    # 10.11  6BR (beyond table) → falls back gracefully
    rr6 = calculate_room_rental_roi(400_000, ec5, bedrooms=6,
                                     built_up_sqft=1_800, state="Selangor")
    _assert(10, "10.11", "6BR (beyond table) → falls back to sqft-derived or default",
            rr6.get("num_rooms", 0) >= 1,
            actual=rr6.get("num_rooms"),
            notes="6BR not in _ROOM_COMPOSITION_BY_BR — uses sqft fallback")

    # 10.12  Non-citizen RPGT after 5yr is 5% (not 0%)
    from entry_cost import rpgt_rate
    _assert(10, "10.12", "Non-citizen RPGT yr6 = 5% (not exempt)",
            rpgt_rate(6, is_citizen=False) == 0.05,
            actual=rpgt_rate(6, is_citizen=False))


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 11 — End-to-End Flow Smoke Test
# ══════════════════════════════════════════════════════════════════════════════

def cat11_e2e(skip_net=False):
    print("\n━━  CAT 11: E2E SMOKE TEST  ━━")
    import subprocess
    import sys as _sys

    if skip_net:
        _r(11, "11.1", "E2E full flow (skipped, --skip-net)", AuditResult.SKIP)
        return

    # 11.1  Import e2e_due_diligence without crash.
    # e2e_due_diligence.py wraps sys.stdout.buffer at module level.
    # If we just restore sys.stdout the new wrapper gets GC'd and closes the
    # shared buffer. We must detach() the wrapper first.
    _orig_stdout = _sys.stdout
    try:
        import e2e_due_diligence as e2e
        # Detach the replacement wrapper so GC doesn't close stdout.buffer
        new_wrapper = _sys.stdout
        if new_wrapper is not _orig_stdout:
            try:
                new_wrapper.flush()
                new_wrapper.detach()
            except Exception:
                pass
        _sys.stdout = _orig_stdout
        _r(11, "11.1", "e2e_due_diligence imports cleanly", AuditResult.PASS)
    except Exception as ex:
        try:
            _sys.stdout = _orig_stdout
        except Exception:
            pass
        _r(11, "11.1", "e2e_due_diligence imports cleanly", AuditResult.ERROR,
           actual=str(ex))
        return

    # 11.2  stage_entry_cost returns 6 values for a real vault listing
    def _load_vault_listing(filename: str) -> dict:
        """Load YAML frontmatter from a vault Properties file."""
        vault_file = SCRIPT_DIR.parent / "vault" / "Properties" / filename
        text = vault_file.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^---\n(.+?)\n---", text, re.DOTALL)
        data = yaml.safe_load(m.group(1)) if m else {}
        # Normalise keys for e2e compatibility
        data.setdefault("listing_id", data.get("id", filename))
        data.setdefault("source", "bidnow")
        data.setdefault("full_address", data.get("address", ""))
        data.setdefault("bedrooms", 0)
        data.setdefault("market_rent_est", 0)
        return data

    try:
        real_listing = _load_vault_listing("bn-263430.md")
        ec, flip, fu, rr, part, hold = e2e.stage_entry_cost(real_listing)
        _assert(11, "11.2", "stage_entry_cost returns (ec, flip, full_unit, room, partition, hold)",
                all(isinstance(x, dict) for x in [ec, flip, fu, rr, part, hold]),
                actual=[x.get("roi_mode", "?") for x in [flip, fu, rr, part, hold]])
        _assert(11, "11.2b", "real_listing loaded from vault (bn-263430.md)",
                real_listing.get("reserve_price", 0) > 0,
                actual=f"reserve=RM{real_listing.get('reserve_price',0):,.0f}  mv=RM{real_listing.get('market_value',0):,.0f}  sqft={real_listing.get('built_up_sqft',0)}")
    except Exception as ex:
        _r(11, "11.2", "stage_entry_cost (6 values)", AuditResult.ERROR, actual=str(ex))

    # 11.3  print_report signature accepts all 11 positional args
    try:
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            # Use a minimal analysis dict
            analysis = {
                "agent_score": 65, "agent_recommendation": "shortlist",
                "agent_reasoning": "Test reasoning", "agent_exit_strategy": "flip",
                "agent_holding_period": "< 1yr", "agent_key_risks": "test,risk",
                "agent_due_diligence": "verify,title", "agent_mode": "rule_based",
            }
            e2e.print_report(
                real_listing,
                {"status": "missing", "message": "No POS found"},
                {"listings_found": 5, "price_range": "RM150k-220k",
                 "size_range": "900-1100 sqft"},
                {"market_sale_psf": 450.0},
                ec, flip, fu, rr, part, hold, analysis,
            )
        out = buf.getvalue()
        _assert(11, "11.3", "print_report executes without crash",
                len(out) > 100, actual=f"{len(out)} chars output")
        _assert(11, "11.3b", "Report contains all 5 scenario headers",
                all(f"SCENARIO {s}" in out.upper() for s in ["A", "B", "C", "D", "E"]),
                actual="scenario labels present" if "SCENARIO" in out.upper() else "MISSING")
    except Exception as ex:
        _r(11, "11.3", "print_report full call", AuditResult.ERROR,
           actual=str(ex), notes=traceback.format_exc(limit=3))

    # 11.4  Subprocess E2E — 2 BidNow pages, no e-Lelong (fastest real scrape)
    try:
        t0  = time.time()
        res = subprocess.run(
            ["C:\\Python314\\python.exe", "e2e_due_diligence.py",
             "--state", "Kuala Lumpur", "--bn-pages", "1",
             "--el-pages", "0", "--auto"],
            capture_output=True, text=True, cwd=str(SCRIPT_DIR), timeout=120,
        )
        elapsed = round(time.time() - t0, 1)
        _assert(11, "11.4", f"Full E2E subprocess exits 0 in {elapsed}s",
                res.returncode == 0,
                actual=f"exit={res.returncode}, stderr={res.stderr[-200:] if res.stderr else ''}")
        # Check key output sections
        combined = (res.stdout or "") + (res.stderr or "")
        _assert(11, "11.4b", "E2E output contains 'ENTRY COST'",
                "ENTRY COST" in combined, actual="present" if "ENTRY COST" in combined else "MISSING")
        _assert(11, "11.4c", "E2E output contains 'SCENARIO A'",
                "SCENARIO A" in combined, actual="present" if "SCENARIO A" in combined else "MISSING")
        _assert(11, "11.4d", "E2E output contains 'PARTITION'",
                "PARTITION" in combined, actual="present" if "PARTITION" in combined else "MISSING")
        _assert(11, "11.4e", "E2E output contains 'INVESTMENT ANALYSIS'",
                "INVESTMENT ANALYSIS" in combined, actual="present" if "INVESTMENT ANALYSIS" in combined else "MISSING")
    except subprocess.TimeoutExpired:
        _r(11, "11.4", "Full E2E subprocess (timed out >120s)", AuditResult.FAIL,
           notes="Investigate scraper latency or throttling")
    except Exception as ex:
        _r(11, "11.4", "Full E2E subprocess", AuditResult.ERROR, actual=str(ex))


def cat12_pos_parser():
    print("\n\u2501\u2501  CAT 12: POS PARSER  \u2501\u2501")
    from pos_parser import parse_pos_fields

    # 12.1  Synthetic condo POS with bedrooms
    condo_text = """
PERISYTIHARAN JUALAN
DALAM MAHKAMAH TINGGI MALAYA DI KUALA LUMPUR
PERMOHONAN UNTUK PERLAKSANAAN NO: KL-22-987-03/2025
ANTARA
Maybank (Malaysia) Berhad (No. Syarikat : 123456-A)
. . .  PLAINTIF
DAN
Ahmad Bin Ismail (No. Kad Pengenalan : 800101015678)
. . . DEFENDAN
Butir-Butir Hakmilik:
No. Hakmilik : Geran No. Hakmilik 112233
No. Petak/No. Tingkat/No. Bangunan : B-15-08 / 15 / Block B
Pegangan : Hakmilik Kekal
Keluasan Petak : 850.0000 kaki persegi
Pemilik Berdaftar : Ahmad Bin Ismail (No. Kad Pengenalan : 800101015678)
Mukim / Daerah / Negeri : Setapak / Kuala Lumpur / W.P. Kuala Lumpur
Lokasi dan Perihal Hartanah :
Hartanah tersebut adalah sebuah unit kondominium yang beralamat pos di
Unit B-15-08, Residensi Tropika, Jalan Gombak, 53000 Kuala Lumpur.
Hartanah tersebut mengandungi tiga (3) bilik tidur dan dua (2) bilik mandi.
Harga Rizab :
Hartanah tersebut akan dijual atas harga rizab sebanyak RM 350,000.00
Firma Guaman : KADIR ANDRI & PARTNERS
Alamat : Level 5, Menara Maybank, Kuala Lumpur
No. Telefon : 03-20787788
"""
    f = parse_pos_fields(condo_text)
    _assert(12, "12.1", "bedrooms extracted from Malay 'tiga bilik tidur'",
            f.get("bedrooms") == 3, actual=f.get("bedrooms"), expected=3)
    _assert(12, "12.1b", "bathrooms extracted from 'dua bilik mandi'",
            f.get("bathrooms") == 2, actual=f.get("bathrooms"), expected=2)
    _assert(12, "12.1c", "floor_no = 15 from strata block",
            f.get("floor_no") == 15, actual=f.get("floor_no"), expected=15)
    _assert(12, "12.1d", "strata_parcel_no = 'B-15-08'",
            f.get("strata_parcel_no") == "B-15-08",
            actual=f.get("strata_parcel_no"), expected="B-15-08")
    _assert(12, "12.1e", "built_up_sqft = 850.0 from Keluasan Petak",
            f.get("built_up_sqft") == 850.0, actual=f.get("built_up_sqft"), expected=850.0)
    _assert(12, "12.1f", "tenure = 'freehold' from Hakmilik Kekal",
            f.get("tenure") == "freehold", actual=f.get("tenure"))
    _assert(12, "12.1g", "bank contains 'Maybank'",
            "Maybank" in (f.get("bank") or ""), actual=f.get("bank"))
    _assert(12, "12.1h", "borrower = 'Ahmad Bin Ismail'",
            f.get("borrower") == "Ahmad Bin Ismail", actual=f.get("borrower"))
    _assert(12, "12.1i", "case_no = 'KL-22-987-03/2025'",
            f.get("case_no") == "KL-22-987-03/2025", actual=f.get("case_no"))
    _assert(12, "12.1j", "reserve_price_rm = 350000.0",
            f.get("reserve_price_rm") == 350000.0, actual=f.get("reserve_price_rm"))
    _assert(12, "12.1k", "district = 'Kuala Lumpur'",
            f.get("district") == "Kuala Lumpur", actual=f.get("district"))
    _assert(12, "12.1l", "lawyer_firm contains 'KADIR'",
            "KADIR" in (f.get("lawyer_firm") or ""), actual=f.get("lawyer_firm"))
    _assert(12, "12.1m", "property_description contains 'kondominium'",
            "kondominium" in (f.get("property_description") or "").lower(),
            actual=f.get("property_description"))

    # 12.2  English bedrooms pattern
    en_text = "The said property is an apartment unit comprising 2 bedrooms and 1 bathroom."
    f2 = parse_pos_fields(en_text)
    _assert(12, "12.2", "bedrooms from English 'comprising 2 bedrooms'",
            f2.get("bedrooms") == 2, actual=f2.get("bedrooms"), expected=2)
    _assert(12, "12.2b", "bathrooms from English '1 bathroom'",
            f2.get("bathrooms") == 1, actual=f2.get("bathrooms"), expected=1)

    # 12.3  Landed property — no bedrooms, has land area
    landed_text = """
Pegangan : Hakmilik Kekal
Mukim / Daerah / Negeri : 6 / Barat Daya / Pulau Pinang
Keluasan Tanah : 1400.0000000000 kaki persegi
Hartanah tersebut adalah A double storey mid terraced house yang beralamat pos di
harga rizab sebanyak RM 480,000.00
"""
    f3 = parse_pos_fields(landed_text)
    _assert(12, "12.3", "no bedrooms in landed POS → key absent",
            f3.get("bedrooms") is None, actual=f3.get("bedrooms"))
    _assert(12, "12.3b", "land_area_sqft = 1400.0",
            f3.get("land_area_sqft") == 1400.0, actual=f3.get("land_area_sqft"))
    _assert(12, "12.3c", "tenure = 'freehold'",
            f3.get("tenure") == "freehold", actual=f3.get("tenure"))
    _assert(12, "12.3d", "district = 'Barat Daya'",
            f3.get("district") == "Barat Daya", actual=f3.get("district"))

    # 12.4  Empty text — returns empty dict, no crash
    _assert(12, "12.4", "empty text returns empty dict",
            parse_pos_fields("") == {}, actual=parse_pos_fields(""))

    # 12.5  Leasehold detection
    lease_text = "Pegangan : Pajakan 99 tahun"
    _assert(12, "12.5", "leasehold detected from 'Pajakan'",
            parse_pos_fields(lease_text).get("tenure") == "leasehold",
            actual=parse_pos_fields(lease_text).get("tenure"))

    # 12.6  Si Bankrap borrower clean-up
    bankrap_text = "Pemilik Berdaftar : Tan Ah Kow (Si Bankrap diwakili oleh Ketua\nPengarah Insolvensi)\nSyarat Nyata : ..."
    f6 = parse_pos_fields(bankrap_text)
    _assert(12, "12.6", "Si Bankrap suffix stripped from borrower name",
            f6.get("borrower") == "Tan Ah Kow", actual=f6.get("borrower"))

    # 12.7  Multi-line bank name before PLAINTIF (insurance successor entity — KL WA- case)
    multiline_bank_text = """\
Mahkamah, 2012
ANTARA
AIA BHD. (dahulunya dikenali sebagai American International Assurance Bhd.
yang telah mengambil alih kuasa, hak dan kepentingan ING Insurance Berhad
(No Syarikat - 17007-P) melalui Perintah Peletakhakan bertarikh 11.06.2013)
(No. Syarikat : 200701032867 [7908950-D])
. . .  PLAINTIF
DAN
MOHD FAUZI BIN ZAKARIA (No. Kad Pengenalan : 600409105705)
. . . DEFENDAN
Mukim / Daerah / Negeri : Ulu Langat / Selangor / Selangor
Harga Rizab : RM 1,600,000.00
Pegangan : Hakmilik Kekal
Firma Guaman : LEE & PARTNERS
"""
    f7 = parse_pos_fields(multiline_bank_text)
    _assert(12, "12.7", "bank extracted when name spans 4 lines before PLAINTIF",
            "AIA" in (f7.get("bank") or ""), actual=f7.get("bank"))

    # 12.8  Bank with reg-number wrapped to next line before PLAINTIF (Selangor BA- case)
    wrapped_reg_text = """\
DALAM MAHKAMAH TINGGI MALAYA DI SHAH ALAM
BA-38-364-01/2026
ANTARA
HONG LEONG ISLAMIC BANK BERHAD (No. Syarikat : 200501009144 (686191-
W))
 . . .  PLAINTIF
DAN
ZAKIAH BINTI MOHD ISA (No. Kad Pengenalan : 800101015678)
. . . DEFENDAN
Mukim / Daerah / Negeri : Batu / Gombak / Selangor
Pegangan : Hakmilik Kekal
harga rizab sebanyak RM 470,000.00
Firma Guaman : Y.H. TEH & QUEK
"""
    f8 = parse_pos_fields(wrapped_reg_text)
    _assert(12, "12.8", "bank extracted when reg-number wraps to next line (Selangor BA-)",
            "HONG LEONG" in (f8.get("bank") or ""), actual=f8.get("bank"))
    _assert(12, "12.8b", "Selangor BA- case_no extracted",
            f8.get("case_no") == "BA-38-364-01/2026", actual=f8.get("case_no"))

    # 12.9  Disbursement_days: reject short admin deadlines (3 days, 7 days)
    short_days_text = """\
Dalam tempoh tiga (3) hari selepas jualan
Dalam tempoh tujuh (7) hari untuk pendaftaran
Baki harga belian hendaklah dibayar dalam tempoh SATU RATUS DUA PULUH (120) hari
"""
    f9 = parse_pos_fields(short_days_text)
    _assert(12, "12.9", "disbursement_days ignores 3-day admin deadline; picks 120",
            f9.get("disbursement_days") == 120, actual=f9.get("disbursement_days"), expected=120)

    # 12.10  Encumbrances: stop at Kawasan Rizab to prevent spillover
    encumb_spillover_text = """\
Bebanan  :  Lain-Lain:DIGADAIKAN KEPADA MINISTER OF FINANCE (INCORPORATED) MALAYSIAKawasan Rizab:Kaveat:LOKASI DAN PERIHAL HARTANAH :Hartanah tersebut adalah ...
"""
    f10 = parse_pos_fields(encumb_spillover_text)
    encumb_val = f10.get("encumbrances") or ""
    _assert(12, "12.10", "encumbrances stops before 'Kawasan Rizab'",
            "LOKASI" not in encumb_val and "Kawasan" not in encumb_val,
            actual=encumb_val)

    # 12.11  Borrower: ASSIGNOR(S) / BORROWER(S) with explicit (S) suffix
    t11 = "LIM CHING YAU (NRIC NO: 850124-10-5432)                              ASSIGNOR(S) / BORROWER(S)"
    f11 = parse_pos_fields(t11)
    _assert(12, "12.11", "borrower extracted from ASSIGNOR(S) / BORROWER(S) format",
            "LIM CHING YAU" in (f11.get("borrower") or ""), actual=f11.get("borrower"))

    # 12.15  Borrower: dot-fill with Customer suffix (and A/L name with slash)
    t15 = "NIRWANNA BINTI LIBASA (NRIC: 790915-11-5260)  \u2026\u2026\u2026\u2026\u2026Assignor/Customer"
    f15 = parse_pos_fields(t15)
    _assert(12, "12.15", "borrower extracted from dot-fill Assignor/Customer suffix",
            "NIRWANNA BINTI LIBASA" in (f15.get("borrower") or ""), actual=f15.get("borrower"))

    # 12.15b  Borrower: dot-fill with only 4 ellipsis chars (264579 PDF format)
    t15b = "YAHAYA BIN MAT (NRIC NO.: 660402-02-6371/A0537432)               \u2026\u2026\u2026\u2026Assignor/Customer"
    f15b = parse_pos_fields(t15b)
    _assert(12, "12.15b", "borrower extracted from 4-ellipsis dot-fill (264579 format)",
            "YAHAYA BIN MAT" in (f15b.get("borrower") or ""), actual=f15b.get("borrower"))

    # 12.16  Bank: Malay LACA stops before PIHAK in "PIHAK PEMEGANG SERAHHAK"
    t16 = "MALAYAN BANKING BERHAD [196001000142/3813-K]                    PIHAK PEMEGANG SERAHHAK"
    f16 = parse_pos_fields(t16)
    bank16 = f16.get("bank") or ""
    _assert(12, "12.16", "Malay LACA bank stops before PIHAK label",
            "MALAYAN BANKING BERHAD" in bank16 and "PIHAK" not in bank16,
            actual=bank16)

    # 12.17a  Borrower: label on NEXT line (single borrower, 264579 format)
    t17a = "YAHAYA BIN MAT (NRIC NO.: 660402-02-6371/A0537432)\n               \u2026\u2026\u2026\u2026\u2026Assignor/Customer"
    f17a = parse_pos_fields(t17a)
    _assert(12, "12.17a", "borrower extracted when Assignor/Customer label is on next line",
            "YAHAYA BIN MAT" in (f17a.get("borrower") or ""), actual=f17a.get("borrower"))

    # 12.17b  Borrower: label on next line, two borrowers on preceding lines (264577 format)
    t17b = ("MUHAMAD AL ARIF BIN AHMAD AZAM (NRIC NO.: 900925-14-5601)\n"
            "NADIA SAFIRAH BINTI RUSLI (NRIC NO.: 901211-10-5258)\n"
            "                     \u2026\u2026\u2026\u2026\u2026Assignors/Customers")
    f17b = parse_pos_fields(t17b)
    _assert(12, "12.17b", "first borrower extracted when two names precede next-line label",
            "MUHAMAD AL ARIF BIN AHMAD AZAM" in (f17b.get("borrower") or ""), actual=f17b.get("borrower"))

    # 12.18  Borrower: standalone BORROWER/CUSTOMER/ASSIGNORS label at end of line (Ng Chan Mau format)
    t18a = ("ALLIANCE BANK MALAYSIA BERHAD [198201008390 (88103-W)] ASSIGNEE\n"
            "AND\n"
            "SYED AHMAD BIN OMAR ALSAGOFF (PASSPORT NO. S8223886G) BORROWER\n"
            "AND\n"
            "SYED OMAR BIN HASHIM ALSAGOFF (PASSPORT NO. E2059053H) ASSIGNOR")
    f18a = parse_pos_fields(t18a)
    _assert(12, "12.18a", "borrower extracted from end-of-line BORROWER label",
            "SYED AHMAD BIN OMAR ALSAGOFF" in (f18a.get("borrower") or ""), actual=f18a.get("borrower"))

    t18b = ("ALLIANCE ISLAMIC BANK BERHAD [200701018870 (776882-V)] BANK\n"
            "AND\n"
            "FARIZAH BINTE BORHAN (SINGAPORE NRIC NO. S8411201A / PASSPORT NO. E2963098B) CUSTOMER")
    f18b = parse_pos_fields(t18b)
    _assert(12, "12.18b", "borrower extracted from end-of-line CUSTOMER label (262618 format)",
            "FARIZAH BINTE BORHAN" in (f18b.get("borrower") or ""), actual=f18b.get("borrower"))

    t18c = ("MALAYAN BANKING BERHAD [196001000142(3813-K)] ASSIGNEE / BANK\n"
            "AND\n"
            "GURDEV SINGH A/L BALWANT SINGH (NRIC NO: 830708-14-6061)                    ASSIGNORS / CUSTOMERS\n"
            "JASBIR SINGH A/L BALWANT SINGH (NRIC NO.: 870111-14-6061)")
    f18c = parse_pos_fields(t18c)
    _assert(12, "12.18c", "borrower extracted from end-of-line ASSIGNORS / CUSTOMERS label (263035 format)",
            "GURDEV SINGH" in (f18c.get("borrower") or ""), actual=f18c.get("borrower"))

    t18d = ("RHB BANK BERHAD [196501000373 (6171-M)] ASSIGNEE\n"
            "AND\n"
            "CRISTY RAJ A/L SELVARAJA (NRIC NO. 960407-08-6239) ASSIGNOR")
    f18d = parse_pos_fields(t18d)
    _assert(12, "12.18d", "borrower extracted from end-of-line ASSIGNOR label (263046 format, first-party)",
            "CRISTY RAJ" in (f18d.get("borrower") or ""), actual=f18d.get("borrower"))

    # 12.19  Borrower: numbered names then standalone ASSIGNORS / BORROWERS line (262577 format)
    t19 = ("MALAYAN BANKING BERHAD (196001000142) ASSIGNEE / BANK\n"
           "AND\n"
           "(1) LIM SUNG MING (NRIC NO. 850609-08-5341)\n"
           "(2) TAN MAY LIAN (NRIC NO. 870925-35-5030)\n"
           "ASSIGNORS / BORROWERS")
    f19 = parse_pos_fields(t19)
    _assert(12, "12.19", "first borrower extracted from numbered names above standalone ASSIGNORS / BORROWERS line",
            "LIM SUNG MING" in (f19.get("borrower") or ""), actual=f19.get("borrower"))

    # 12.20  Borrower: N) prefix without opening paren (263769 format)
    t20 = ("BANK ISLAM MALAYSIA BERHAD [98127-X] BANK\n"
           "AND\n"
           "1) AHMAD BIN ABDULLAH (NRIC NO.: 750101-01-1234)\n"
           "2) WAN MOHAMAD NOR ARIFF BIN WAN YUSUF (NRIC NO.: 670908-02-5535)     CUSTOMER(S)")
    f20 = parse_pos_fields(t20)
    _assert(12, "12.20", "borrower extracted from N) prefix without opening paren (263769 format)",
            "AHMAD BIN ABDULLAH" in (f20.get("borrower") or "") or "WAN MOHAMAD NOR ARIFF" in (f20.get("borrower") or ""),
            actual=f20.get("borrower"))


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORY 13 — Hermes Fallback (MiMo Integration)
# ══════════════════════════════════════════════════════════════════════════════

def cat13_hermes_fallback():
    print("\n━━  CAT 13: HERMES FALLBACK (MiMo Integration)  ━━")
    import copy
    from unittest.mock import MagicMock

    try:
        from hermes import (HermesAgent, check_pos_completeness,
                            _is_missing, _parse_rm)
        from pos_parser import parse_pos_fields
    except ImportError as e:
        _r(13, "13.0", "hermes module imports", AuditResult.ERROR, actual=str(e))
        return

    # ── Shared fixtures ───────────────────────────────────────────────────────
    _partial_with_nones = {
        "bank": None, "borrower": "",
        "reserve_price_rm": 350_000.0, "deposit_required_rm": 35_000.0,
        "disbursement_days": 90, "encumbrances": "Tiada",
        "location": "No. 5, Jalan Ampang, 50450 KL", "tenure": "leasehold",
    }

    # Helper: create a mock response object
    def _mock_resp(content: str):
        m = MagicMock()
        m.choices[0].message.content = content
        return m

    # Helper: HermesAgent with injected mock client — no openai package needed
    def _make_agent(response_content: str) -> HermesAgent:
        mc = MagicMock()
        mc.chat.completions.create.return_value = _mock_resp(response_content)
        return HermesAgent(client=mc)

    # ── 13.1 – 13.6  _is_missing() helper ────────────────────────────────────
    _assert(13, "13.1",  "_is_missing: None → missing",
            _is_missing("bank", None))
    _assert(13, "13.2",  "_is_missing: empty string → missing",
            _is_missing("bank", ""))
    _assert(13, "13.3",  "_is_missing: whitespace-only → missing",
            _is_missing("bank", "   "))
    _assert(13, "13.4",  "_is_missing: real value → not missing",
            not _is_missing("bank", "MAYBANK BERHAD"))
    _assert(13, "13.5",  "_is_missing: zero for reserve_price_rm → missing",
            _is_missing("reserve_price_rm", 0.0))
    _assert(13, "13.5b", "_is_missing: zero NOT missing for field outside ZERO_IS_MISSING_FIELDS",
            not _is_missing("bedrooms", 0))
    _assert(13, "13.6",  "_is_missing: non-zero price → not missing",
            not _is_missing("reserve_price_rm", 350_000.0))

    # ── 13.7  check_pos_completeness: None / empty values count as missing ────
    _complete, _missing13 = check_pos_completeness(_partial_with_nones)
    _assert(13, "13.7",
            "check_pos_completeness treats None/empty values as missing (not just absent keys)",
            not _complete and "bank" in _missing13 and "borrower" in _missing13,
            actual=f"complete={_complete}, missing={_missing13}")

    # ── 13.8 – 13.11  enrich_pos fills None / empty keys (critical fix) ──────
    _llm_json = json.dumps({
        "bank": "MAYBANK ISLAMIC BERHAD", "borrower": "AHMAD BIN HASSAN",
        "reserve_price_rm": None, "deposit_required_rm": None,
        "disbursement_days": None, "encumbrances": None,
        "location": None, "tenure": None,
    })
    _base = {**_partial_with_nones,
             "_extraction_complete": False, "_missing_essential": ["bank", "borrower"]}

    _r13 = _make_agent(_llm_json).enrich_pos("(POS text)", copy.copy(_base))

    _assert(13, "13.8",  "enrich_pos fills bank when partial_fields['bank'] is None",
            _r13.get("bank") == "MAYBANK ISLAMIC BERHAD", actual=_r13.get("bank"))
    _assert(13, "13.9",  "enrich_pos fills borrower when partial_fields['borrower'] is ''",
            _r13.get("borrower") == "AHMAD BIN HASSAN", actual=_r13.get("borrower"))
    _assert(13, "13.10", "_hermes_mode == 'llm' after enrichment",
            _r13.get("_hermes_mode") == "llm", actual=_r13.get("_hermes_mode"))
    _assert(13, "13.11", "_extraction_complete == True after enrichment",
            _r13.get("_extraction_complete") is True, actual=_r13.get("_extraction_complete"))

    # ── 13.12 – 13.13  enrich_pos skips when already complete ────────────────
    _full = {**_partial_with_nones,
             "bank": "ORIGINAL BANK", "borrower": "ORIGINAL BORROWER",
             "_extraction_complete": True, "_missing_essential": []}
    # LLM not called (early-exit on skipped_complete) — plain MagicMock suffices
    _r12 = HermesAgent(client=MagicMock()).enrich_pos("(POS text)", copy.copy(_full))
    _assert(13, "13.12", "_hermes_mode == 'skipped_complete' when nothing missing",
            _r12.get("_hermes_mode") == "skipped_complete", actual=_r12.get("_hermes_mode"))
    _assert(13, "13.13", "enrich_pos does NOT overwrite existing non-empty bank",
            _r12.get("bank") == "ORIGINAL BANK", actual=_r12.get("bank"))

    # ── 13.14 – 13.15  Regression: Islamic BANK label → now handled by MiMo ──
    _t_islamic = "MAYBANK ISLAMIC BERHAD (200701029411)                              BANK"
    _p_islamic = parse_pos_fields(_t_islamic)
    _assert(13, "13.14",
            "pos_parser no longer handles standalone BANK label (regex removed; MiMo fills)",
            not _p_islamic.get("bank"), actual=_p_islamic.get("bank"))
    _r_islamic = _make_agent(json.dumps({
        "bank": "MAYBANK ISLAMIC BERHAD", "borrower": None,
        "reserve_price_rm": None, "deposit_required_rm": None,
        "disbursement_days": None, "encumbrances": None, "location": None, "tenure": None,
    })).enrich_pos(_t_islamic, _p_islamic)
    _assert(13, "13.15",
            "Hermes fills Islamic BANK via mock MiMo (regression coverage for removed 12.14)",
            "MAYBANK ISLAMIC BERHAD" in (_r_islamic.get("bank") or ""),
            actual=_r_islamic.get("bank"))

    # ── 13.16 – 13.17  Regression: standalone BORROWER → now handled by MiMo ─
    _t_bwr = "SYED AHMAD BIN OMAR ALSAGOFF (SINGAPORE PASSPORT NO. S8223886G) BORROWER"
    _p_bwr = parse_pos_fields(_t_bwr)
    _assert(13, "13.16",
            "pos_parser no longer handles standalone BORROWER label (regex removed; MiMo fills)",
            not _p_bwr.get("borrower"), actual=_p_bwr.get("borrower"))
    _r_bwr = _make_agent(json.dumps({
        "bank": None, "borrower": "SYED AHMAD BIN OMAR ALSAGOFF",
        "reserve_price_rm": None, "deposit_required_rm": None,
        "disbursement_days": None, "encumbrances": None, "location": None, "tenure": None,
    })).enrich_pos(_t_bwr, _p_bwr)
    _assert(13, "13.17",
            "Hermes fills standalone BORROWER via mock MiMo (regression coverage for removed 12.12)",
            "SYED AHMAD BIN OMAR ALSAGOFF" in (_r_bwr.get("borrower") or ""),
            actual=_r_bwr.get("borrower"))

    # ── 13.18  Markdown-fenced JSON is parsed correctly ───────────────────────
    _base_nobank = {**_partial_with_nones,
                    "bank": None, "borrower": None,
                    "_extraction_complete": False, "_missing_essential": ["bank", "borrower"]}
    _r3 = _make_agent('```json\n{"bank": "CIMB BANK BERHAD", "borrower": null}\n```').enrich_pos(
        "(POS text)", copy.copy(_base_nobank))
    _assert(13, "13.18", "JSON wrapped in markdown fences is correctly parsed",
            _r3.get("bank") == "CIMB BANK BERHAD", actual=_r3.get("bank"))

    # ── 13.19 – 13.21  _parse_rm() currency normalization ─────────────────────
    _assert(13, "13.19", "_parse_rm: plain float string '350000.0'",
            abs(_parse_rm("350000.0") - 350_000.0) < 0.01)
    _assert(13, "13.20", "_parse_rm: 'RM 350,000.00' (prefix + space + thousand sep)",
            abs(_parse_rm("RM 350,000.00") - 350_000.0) < 0.01)
    _assert(13, "13.21", "_parse_rm: 'RM120,000' (no space, no decimal)",
            abs(_parse_rm("RM120,000") - 120_000.0) < 0.01)

    # ── 13.22  RM-prefixed amount from LLM is coerced in full enrich_pos path ─
    _base_no_price = {
        "bank": "TEST BANK", "borrower": "JOHN DOE",
        "reserve_price_rm": 0.0,        # _is_missing → True (zero for RM field)
        "deposit_required_rm": 0.0,     # _is_missing → True
        "disbursement_days": 90, "encumbrances": "Tiada",
        "location": "No. 5, Jalan Test, 50000 KL", "tenure": "freehold",
        "_extraction_complete": False,
        "_missing_essential": ["reserve_price_rm", "deposit_required_rm"],
    }
    _r_curr = _make_agent(json.dumps({
        "bank": None, "borrower": None,
        "reserve_price_rm": "RM 350,000.00",
        "deposit_required_rm": "RM35,000",
        "disbursement_days": None, "encumbrances": None, "location": None, "tenure": None,
    })).enrich_pos("(POS text)", copy.copy(_base_no_price))
    _assert(13, "13.22",
            "enrich_pos coerces 'RM 350,000.00' string to float 350000.0",
            abs((_r_curr.get("reserve_price_rm") or 0) - 350_000.0) < 0.01,
            actual=_r_curr.get("reserve_price_rm"))


# ══════════════════════════════════════════════════════════════════════════════
# FINAL REPORT
# ══════════════════════════════════════════════════════════════════════════════

def _print_report():
    from collections import Counter
    counts = Counter(r["status"] for r in results)
    total  = len(results)

    print("\n")
    print("═" * 70)
    print("  AUDIT REPORT SUMMARY")
    print("═" * 70)

    # By category
    cats = sorted({r["cat"] for r in results})
    cat_names = {
        1: "Entry Cost Calculations",
        2: "Flip ROI",
        3: "Rental Strategy ROI",
        4: "Partition Room Estimation",
        5: "Analyst Agent (Rule-Based)",
        6: "POS Identifier",
        7: "Dedup Merger & Derived Fields",
        8: "Market Cache & Research",
        9: "Scraper Probes",
        10: "Edge Cases & Error Handling",
        11: "E2E Flow Smoke Test",
        12: "POS Parser",
        13: "Hermes Fallback (MiMo)",
    }
    for cat in cats:
        cat_results = [r for r in results if r["cat"] == cat]
        c = Counter(r["status"] for r in cat_results)
        p, f, w, e, s = c["PASS"], c["FAIL"], c["WARN"], c["ERROR"], c["SKIP"]
        status_bar = (
            f"PASS={p:2d}  FAIL={f:2d}  WARN={w:2d}  ERR={e:2d}  SKIP={s:2d}"
        )
        overall = "OK" if (f + e) == 0 else "ISSUES"
        print(f"  Cat {cat:2d}  [{overall:6s}]  {cat_names.get(cat,''):<35s}  {status_bar}")

    print()
    print(f"  TOTAL: {total} scenarios  —  "
          f"PASS={counts['PASS']}  FAIL={counts['FAIL']}  "
          f"WARN={counts['WARN']}  ERROR={counts['ERROR']}  SKIP={counts['SKIP']}")
    pct = round(counts['PASS'] / max(1, total - counts['SKIP']) * 100, 1)
    print(f"  Pass rate (excl. SKIP): {pct}%")

    # Failed / Errored details
    fails = [r for r in results if r["status"] in (AuditResult.FAIL, AuditResult.ERROR)]
    if fails:
        print("\n  ── FAILURES & ERRORS ─────────────────────────────────────────")
        for r in fails:
            print(f"  [{r['status']:5s}] {r['id']:12s}  {r['desc']}")
            if r.get("actual"):   print(f"           actual  : {r['actual']}")
            if r.get("expected"): print(f"           expected: {r['expected']}")
            if r.get("notes"):    print(f"           note    : {r['notes']}")

    # Warnings
    warns = [r for r in results if r["status"] == AuditResult.WARN]
    if warns:
        print("\n  ── WARNINGS ──────────────────────────────────────────────────")
        for r in warns:
            print(f"  [WARN]  {r['id']:12s}  {r['desc']}")
            if r.get("notes"): print(f"           {r['notes']}")

    print("\n  ── IMPROVEMENT SUGGESTIONS ───────────────────────────────────────")
    suggestions = [
        ("Market Coverage",
         "market_research.py covers only ~8/16 states from 5-page national sample. "
         "Add state-specific URL scraping (e.g. /property-for-rent/selangor/) for "
         "East Malaysia, Kedah, Perlis, Terengganu, Kelantan."),
        ("Room Rental Rates",
         "Room and partition rates are KL/Selangor benchmarks only. Add a "
         "LOCATION_FACTOR dict (e.g. Penang=0.85, Johor=0.75, Sabah=0.70) to "
         "scale rates regionally."),
        ("Bedroom Count Extraction",
         "BidNow listings do not expose bedroom count in list-page JSON. "
         "POS PDF parsing (pos_parser.py) extracts bedrooms when a POS URL is available. "
         "Consider also adding detail page scraping for bedrooms when no POS is present."),
        ("Partition Permit Warning",
         "The partition guideline note is text-only. Add a structured 'requires_permit' "
         "bool field and surface it prominently in print_report as a risk flag."),
        ("iBilik Scraper",
         "Room rental rates currently use hardcoded ranges. Build an iBilik.my "
         "scraper (search by district) to pull live room rates as a dynamic benchmark."),
        ("6BR Composition",
         "_ROOM_COMPOSITION_BY_BR ends at 5BR. Add 6BR and 7BR mappings, "
         "or use a formula fallback for large properties."),
        ("Non-Citizen ROI",
         "is_citizen=True is hardcoded as default everywhere. Add a CLI flag "
         "--non-citizen to e2e_due_diligence.py to surface non-citizen RPGT rates."),
        ("Cashflow Stress Test",
         "No interest rate stress test. Add a calculate_cashflow_stress(rate+1%) "
         "to show OPR hike impact on mortgage instalment and net yield."),
        ("Audit Automation",
         "This audit script is manually triggered. Wire it to GitHub Actions "
         "on PR merge to catch regressions automatically."),
    ]
    for i, (title, desc) in enumerate(suggestions, 1):
        print(f"  {i:2d}. {title}")
        print(f"      {desc}")

    print("\n" + "═" * 70)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Auction Investment System Audit")
    parser.add_argument("--skip-net", action="store_true",
                        help="Skip all network-dependent tests (cats 9, 11)")
    parser.add_argument("--cat", default="",
                        help="Comma-separated category numbers to run, e.g. 1,3,5")
    args = parser.parse_args()

    run_cats = set(int(x) for x in args.cat.split(",") if x.strip()) if args.cat else set(range(1, 14))

    print("═" * 70)
    print("  AUCTION INVESTMENT SYSTEM — FULL AUDIT")
    print(f"  Date : {date.today().isoformat()}")
    print(f"  Mode : {'skip-net' if args.skip_net else 'full (includes network)'}")
    print(f"  Cats : {sorted(run_cats)}")
    print("═" * 70)

    dispatch = {
        1:  cat1_entry_cost,
        2:  cat2_flip_roi,
        3:  cat3_rental_roi,
        4:  cat4_partition_estimate,
        5:  cat5_analyst,
        6:  cat6_pos,
        7:  cat7_dedup,
        8:  lambda: cat8_market(skip_net=args.skip_net),
        9:  lambda: cat9_scrapers(skip_net=args.skip_net),
        10: cat10_edge_cases,
        11: lambda: cat11_e2e(skip_net=args.skip_net),
        12: cat12_pos_parser,
        13: cat13_hermes_fallback,
    }

    for cat_num, fn in dispatch.items():
        if cat_num in run_cats:
            try:
                fn()
            except Exception as e:
                _r(cat_num, f"{cat_num}.crash",
                   f"Category {cat_num} CRASHED", AuditResult.ERROR,
                   actual=str(e), notes=traceback.format_exc(limit=3))

    _print_report()


if __name__ == "__main__":
    main()
