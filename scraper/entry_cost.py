"""
entry_cost.py — Malaysian property auction entry cost and ROI calculator.

Covers the full cash outlay for a bank or court auction purchase:
  1. Auction deposit (10% on hammer day, non-refundable if balance unpaid)
  2. Balance (90% within 90–120 days — typically bank-financed)
  3. Stamp duty on Memorandum of Transfer (MOT) — progressive rates
  4. Stamp duty on loan agreement — 0.5% of loan principal
  5. Legal / conveyancing fees — Solicitors Remuneration Order 2023 scale
  6. Bank processing / admin fee
  7. Valuation fee (mandatory for bank financing)
  8. Miscellaneous (title search, land search, registration, disbursements)
  9. Optional renovation (light / moderate / heavy)

Holding strategy metrics:
  - Monthly mortgage instalment (reducing-balance annuity)
  - Gross and net rental yield
  - Cash-on-cash return
  - Simple ROI at requested holding period (capital gain + rent – RPGT)
  - Monthly cashflow (rent – mortgage – maintenance)

Reference:
  Stamp Act 1949 Third Schedule (as amended)
  Solicitors Remuneration Order 2023
  Real Property Gains Tax Act 1976 (citizens: RPGT-free after 5 years)
"""

from typing import Dict

# ── Stamp duty (MOT) — Stamp Act 1949, Third Schedule ────────────────────────
# First-home exemption: Malaysian citizens buying first home ≤RM500k are exempt
# on the first RM150k of the instrument of transfer.
_STAMP_DUTY_SLABS = [
    (100_000,  0.01),   # 1%  on first RM100k
    (400_000,  0.02),   # 2%  on RM100k – RM500k
    (500_000,  0.03),   # 3%  on RM500k – RM1M
]
_STAMP_DUTY_MARGINAL = 0.04   # 4% on amount above RM1M

# ── Legal / conveyancing fees — Solicitors Remuneration Order 2023 ────────────
_LEGAL_FEE_SLABS = [
    (500_000,    0.010),   # 1%   on first RM500k  (min RM500)
    (500_000,    0.008),   # 0.8% on next RM500k
    (2_000_000,  0.007),   # 0.7% on next RM2M
    (2_000_000,  0.006),   # 0.6% on next RM2M
]
_LEGAL_FEE_MARGINAL = 0.005   # 0.5% above RM5M
_LEGAL_FEE_MIN      = 500.0

# ── Loan parameters ───────────────────────────────────────────────────────────
DEFAULT_LOAN_RATE   = 4.25   # % per annum (OPR-based, Jan 2026 estimate)
DEFAULT_LOAN_TENURE = 30     # years
LOAN_STAMP_DUTY_PCT = 0.005  # 0.5% on loan principal (Stamp Act — charge doc)
BANK_PROCESSING_FEE = 750.0  # bank admin fee (one-off)

# ── Other upfront costs ───────────────────────────────────────────────────────
MISC_DISBURSEMENTS  = 1_500.0   # searches, registration, courier, certified copies
VALUATION_FEE_LOW   = 1_500.0   # ≤RM700k property
VALUATION_FEE_HIGH  = 4_000.0   # > RM700k property

_RENO_COSTS: Dict[str, float] = {
    "none":     0.0,
    "light":    15_000.0,    # repaint, patch, basic fittings — habitable fast
    "moderate": 40_000.0,    # full refurb: kitchen, bathrooms, flooring
    "heavy":    90_000.0,    # major: structural repair + full fit-out
}

# ── Capital appreciation assumptions (conservative, pa) ──────────────────────
APPRECIATION_PA: Dict[str, float] = {
    "Kuala Lumpur":      3.5,
    "Selangor":          3.0,
    "Putrajaya":         3.0,
    "Penang":            3.5,
    "Johor":             2.5,
    "Melaka":            2.0,
    "Negeri Sembilan":   2.0,
    "Kedah":             1.5,
    "Perak":             1.5,
    "Pahang":            1.5,
    "Kelantan":          1.5,
    "Terengganu":        1.5,
    "Perlis":            1.0,
    "Sabah":             2.0,
    "Sarawak":           2.0,
}
DEFAULT_APPRECIATION = 2.5   # % pa fallback for unknown state

# ── RPGT (Real Property Gains Tax) — citizens ─────────────────────────────────
# Disposal within ≤3 yr → 30%, yr 4 → 20%, yr 5 → 15%, > 5 yr → 0%
_RPGT_CITIZEN = [(3, 0.30), (4, 0.20), (5, 0.15)]


# ── Helper functions ──────────────────────────────────────────────────────────

def stamp_duty(price: float, first_home_exemption: bool = False) -> float:
    """
    Stamp duty on the Memorandum of Transfer (MOT).
    first_home_exemption: for Malaysian citizen buying first home ≤RM500k —
    the first RM150k is exempt.
    """
    if first_home_exemption and price <= 500_000:
        price = max(0.0, price - 150_000)

    tax = 0.0
    remaining = price
    for slab, rate in _STAMP_DUTY_SLABS:
        if remaining <= 0:
            break
        chunk = min(remaining, slab)
        tax += chunk * rate
        remaining -= chunk
    if remaining > 0:
        tax += remaining * _STAMP_DUTY_MARGINAL
    return round(tax, 2)


def legal_fees(price: float) -> float:
    """Solicitor conveyancing fee on purchase price (SRO 2023 scale)."""
    fee = 0.0
    remaining = price
    for slab, rate in _LEGAL_FEE_SLABS:
        if remaining <= 0:
            break
        chunk = min(remaining, slab)
        fee += chunk * rate
        remaining -= chunk
    if remaining > 0:
        fee += remaining * _LEGAL_FEE_MARGINAL
    return round(max(fee, _LEGAL_FEE_MIN), 2)


def monthly_instalment(principal: float, annual_rate: float, years: int) -> float:
    """Monthly mortgage instalment (reducing-balance annuity formula)."""
    if principal <= 0:
        return 0.0
    r = annual_rate / 100 / 12
    n = years * 12
    if r == 0:
        return round(principal / n, 2)
    return round(principal * r * (1 + r) ** n / ((1 + r) ** n - 1), 2)


def rpgt_rate(holding_years: int, is_citizen: bool = True) -> float:
    """
    RPGT rate on capital gain for Malaysian citizen residential property.
    > 5 years: exempt for citizens.
    """
    if not is_citizen:
        return 0.30 if holding_years <= 5 else 0.05
    for yrs, rate in _RPGT_CITIZEN:
        if holding_years <= yrs:
            return rate
    return 0.0  # > 5 years: RPGT-exempt


# ── Main calculators ──────────────────────────────────────────────────────────

def calculate_entry_cost(
    reserve_price: float,
    loan_pct: float = 90.0,
    annual_loan_rate: float = DEFAULT_LOAN_RATE,
    loan_tenure_years: int = DEFAULT_LOAN_TENURE,
    reno_level: str = "light",
    first_home_exemption: bool = False,
    include_valuation: bool = True,
) -> Dict:
    """
    Compute total cash entry cost and financing summary.

    Returns a flat dict:
      reserve_price_rm       auction reserve
      deposit_rm             10% paid on hammer day
      balance_rm             90% paid within 90-120 days
      loan_amount_rm         balance × loan_pct%
      stamp_duty_rm          MOT stamp duty
      loan_stamp_duty_rm     0.5% on loan principal
      legal_fees_rm          conveyancing fee
      bank_processing_rm     bank admin fee
      valuation_fee_rm       bank valuation
      misc_rm                searches + registration + courier
      reno_rm                renovation estimate
      monthly_instalment_rm  monthly mortgage payment
      total_cash_day1_rm     deposit + all fees (deposit, stamp, legal, bank, val, misc)
      total_investment_rm    total_cash_day1 + reno
    """
    deposit  = round(reserve_price * 0.10, 2)
    balance  = round(reserve_price * 0.90, 2)
    loan_amt = round(balance * loan_pct / 100.0, 2)

    sd       = stamp_duty(reserve_price, first_home_exemption)
    loan_sd  = round(loan_amt * LOAN_STAMP_DUTY_PCT, 2)
    lf       = legal_fees(reserve_price)
    val_fee  = (VALUATION_FEE_LOW if reserve_price < 700_000 else VALUATION_FEE_HIGH) \
               if include_valuation else 0.0
    reno     = _RENO_COSTS.get(reno_level.lower(), 0.0)
    monthly  = monthly_instalment(loan_amt, annual_loan_rate, loan_tenure_years)

    # Day-1 cash: deposit + all one-off fees (balance paid by bank)
    cash_day1 = deposit + sd + loan_sd + lf + BANK_PROCESSING_FEE + MISC_DISBURSEMENTS + val_fee
    total_inv = cash_day1 + reno

    return {
        "reserve_price_rm":      reserve_price,
        "deposit_rm":            deposit,
        "balance_rm":            balance,
        "loan_amount_rm":        loan_amt,
        "loan_pct":              loan_pct,
        "stamp_duty_rm":         sd,
        "loan_stamp_duty_rm":    loan_sd,
        "legal_fees_rm":         lf,
        "bank_processing_rm":    BANK_PROCESSING_FEE,
        "valuation_fee_rm":      val_fee,
        "misc_rm":               MISC_DISBURSEMENTS,
        "reno_rm":               reno,
        "reno_level":            reno_level,
        "monthly_instalment_rm": monthly,
        "total_cash_day1_rm":    round(cash_day1, 2),
        "total_investment_rm":   round(total_inv, 2),
    }


def calculate_roi(
    reserve_price: float,
    entry_cost: Dict,
    monthly_rent_est: float = 0.0,
    state: str = "",
    holding_years: int = 3,
    is_citizen: bool = True,
    vacancy_months_per_year: float = 1.0,
    maintenance_monthly: float = 300.0,
) -> Dict:
    """
    Estimate ROI for a given holding period (sell at end of period).

    Assumptions:
      - Property appreciates at conservative state-specific % pa.
      - Rent is collected throughout; vacancy & maintenance deducted.
      - RPGT applied on capital gain at disposal (citizens: free > 5yr).
      - Entry cost (total_investment_rm) is the investor's total cash in.

    Returns:
      appreciation_rate_pct   % pa assumed for this state
      exit_price_est_rm       estimated resale price at end of holding period
      capital_gain_rm         gross capital gain
      rpgt_rm                 RPGT payable on gain
      net_capital_gain_rm     capital gain after RPGT
      total_rent_rm           cumulative net rent (less vacancy + maintenance)
      total_return_rm         net_capital_gain + total_rent
      total_investment_rm     total cash invested (day-1 + reno)
      roi_pct                 total_return / total_cash_day1 × 100
      gross_yield_pct         annual gross rent / reserve_price × 100
      net_yield_pct           annual net rent / reserve_price × 100
      monthly_cashflow_rm     monthly net rent minus mortgage payment
    """
    appn_rate  = APPRECIATION_PA.get(state, DEFAULT_APPRECIATION) / 100
    exit_price = round(reserve_price * (1 + appn_rate) ** holding_years)

    cap_gain   = exit_price - reserve_price
    tax        = round(cap_gain * rpgt_rate(holding_years, is_citizen), 2)
    net_gain   = round(cap_gain - tax, 2)

    # Annual rent: gross minus vacancy and maintenance
    eff_monthly = monthly_rent_est * (1 - vacancy_months_per_year / 12) - maintenance_monthly
    total_rent  = round(eff_monthly * 12 * holding_years, 2)

    cash_day1  = entry_cost["total_cash_day1_rm"]
    total_inv  = entry_cost["total_investment_rm"]
    total_ret  = net_gain + total_rent
    roi_pct    = round(total_ret / cash_day1 * 100, 1) if cash_day1 else 0.0

    gross_yield = round(monthly_rent_est * 12 / reserve_price * 100, 2) if reserve_price else 0.0
    net_yield   = round(eff_monthly * 12 / reserve_price * 100, 2) if reserve_price else 0.0
    monthly_cf  = round(eff_monthly - entry_cost["monthly_instalment_rm"], 2)

    return {
        "holding_years":          holding_years,
        "appreciation_rate_pct":  APPRECIATION_PA.get(state, DEFAULT_APPRECIATION),
        "exit_price_est_rm":      exit_price,
        "capital_gain_rm":        round(cap_gain, 2),
        "rpgt_rm":                tax,
        "net_capital_gain_rm":    net_gain,
        "total_rent_rm":          total_rent,
        "total_return_rm":        round(total_ret, 2),
        "total_investment_rm":    total_inv,
        "roi_pct":                roi_pct,
        "gross_yield_pct":        gross_yield,
        "net_yield_pct":          net_yield,
        "monthly_cashflow_rm":    monthly_cf,
    }


# ── Disposal cost constants ───────────────────────────────────────────────────
AGENT_COMMISSION_PCT = 2.5   # seller's agent commission on disposal (typical in MY)
DISPOSAL_LEGAL_PCT   = 0.50  # legal/admin on disposal side (rough estimate)


def calculate_flip_roi(
    reserve_price: float,
    current_market_value: float,
    entry_cost: Dict,
    agent_commission_pct: float = AGENT_COMMISSION_PCT,
    is_citizen: bool = True,
) -> Dict:
    """
    Flip ROI — buy at auction, sell at CURRENT market value.

    No future price estimation required: the discount is locked in at purchase.
    The exit price is today's market value, not a speculated appreciation target.

    Disposal costs deducted:
      - Seller's agent commission (default 2.5%)
      - Disposal legal / admin (default 0.5%)
      - RPGT at 30% on TAXABLE gain (citizen, sold within 3 years)

    RPGT Act 1976 — allowable deductions applied before tax:
      Taxable gain = gross gain − stamp_duty_rm − legal_fees_rm
      This correctly reduces the RPGT liability vs taxing the raw gross gain.

    Returns:
      current_market_value_rm   market value used as exit price
      gross_gain_rm             market_value - reserve_price
      agent_commission_rm       disposal agent fee
      disposal_legal_rm         disposal legal / admin
      rpgt_rm                   RPGT payable (conservative — on gross gain)
      rpgt_rate_pct             rate applied (30% for < 3yr hold)
      net_proceeds_rm           what you actually pocket from the sale
      net_profit_rm             net_proceeds - total_investment
      total_investment_rm       all cash in (day-1 + reno)
      roi_pct                   net_profit / total_cash_day1 × 100
      instant_equity_pct        gross_gain / reserve_price × 100
    """
    if current_market_value <= 0:
        return {"roi_mode": "flip", "roi_pct": 0.0, "error": "market value not available"}

    agent_fee     = round(current_market_value * agent_commission_pct / 100, 2)
    disposal_lf   = round(current_market_value * DISPOSAL_LEGAL_PCT   / 100, 2)

    gross_gain    = current_market_value - reserve_price

    # RPGT Act 1976: allowable deductions reduce the taxable gain.
    # Deduct stamp duty and conveyancing legal fees paid at purchase.
    allowable_ded = round(
        entry_cost.get("stamp_duty_rm", 0) + entry_cost.get("legal_fees_rm", 0), 2
    )
    taxable_gain  = max(0.0, gross_gain - allowable_ded)
    tax           = round(taxable_gain * rpgt_rate(1, is_citizen), 2)

    net_proceeds  = current_market_value - agent_fee - disposal_lf - tax
    total_inv     = entry_cost["total_investment_rm"]
    cash_day1     = entry_cost["total_cash_day1_rm"]

    net_profit    = net_proceeds - total_inv
    roi_pct       = round(net_profit / cash_day1 * 100, 1) if cash_day1 else 0.0
    instant_eq    = round(gross_gain / reserve_price * 100, 1) if reserve_price else 0.0

    return {
        "roi_mode":                   "flip",
        "current_market_value_rm":    current_market_value,
        "gross_gain_rm":              round(gross_gain, 2),
        "agent_commission_rm":        agent_fee,
        "disposal_legal_rm":          disposal_lf,
        "rpgt_allowable_deductions_rm": allowable_ded,
        "rpgt_taxable_gain_rm":       round(taxable_gain, 2),
        "rpgt_rm":                    tax,
        "rpgt_rate_pct":              rpgt_rate(1, is_citizen) * 100,
        "net_proceeds_rm":            round(net_proceeds, 2),
        "net_profit_rm":              round(net_profit, 2),
        "total_investment_rm":        total_inv,
        "total_cash_day1_rm":         cash_day1,
        "roi_pct":                    roi_pct,
        "instant_equity_pct":         instant_eq,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# RENTAL STRATEGY CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
#
# Three strategies supported:
#   1. FULL UNIT  — single tenancy for whole unit (simplest, lowest gross yield)
#   2. ROOM       — rent individual bedrooms of existing layout (no structural
#                   changes; higher gross yield, more management overhead)
#   3. PARTITION  — convert unit into more rooms using drywall (highest gross
#                   yield; CAPEX required; requires local authority permit for
#                   structural works)
#
# References (KL/Klang Valley mid-market, furnished, 2025-2026):
#   iBilik.my — room rental listings (Kuala Lumpur)
#   iProperty.com.my — full unit rental benchmarks
#
# ── Room rental rate ranges ───────────────────────────────────────────────────
# Existing structural rooms (permanent walls, proper bedrooms, furnished+AC)
ROOM_RATES_STANDARD = {
    "master_min": 1_000,  "master_max": 1_200,  # en-suite toilet, largest room
    "middle_min":   800,  "middle_max": 1_000,  # no toilet, medium-sized room
    "small_min":    700,  "small_max":    850,  # no toilet, smallest room
}

# Partition rooms — drywall conversion (furnished+AC, slightly lower premium)
# Rates ~10-20% below standard rooms due to perceived lower build quality.
ROOM_RATES_PARTITION = {
    "master_min":   900,  "master_max": 1_100,  # with toilet add-on
    "middle_min":   700,  "middle_max":   900,  # no toilet
    "small_min":    600,  "small_max":    750,  # no toilet, smallest partition
}

# ── Partition room setup costs ────────────────────────────────────────────────
# CAPEX to convert an existing open/bedroom space into partition rooms.
# Includes: drywall partition, door, lighting, electrical socket, AC socket,
#           basic bed+wardrobe furniture.
PARTITION_COST_ROOM_BASIC    = 8_500   # per room, no bathroom (RM)
PARTITION_COST_ROOM_ENSUITE  = 16_000  # per room, with attached toilet+shower (RM)
PARTITION_COST_UNIT_COMMON   = 3_000   # one-off: WiFi router, common area tidy-up

# ── Partition room count guidelines ──────────────────────────────────────────
# There is NO national Malaysian law setting a hard cap on partition rooms.
# Local authority (DBKL, MBPJ, MPAJ, MBSA) bylaws may require a renovation
# permit for structural works; enforcement varies.
#
# Industry rule-of-thumb used by Malaysian landlords:
#   ~1 room per 180 sqft of net useable area (after deducting common areas)
#   Minimum habitable room size: 80 sqft
#   Shared bathroom ratio: ≤3 non-ensuite rooms per 1 shared bathroom
#   Fire safety (BOMBA): all rooms must have a window for natural ventilation
#
# Practical caps by total built-up size (incl. common area):
_PARTITION_SQFT_PER_ROOM   = 180    # net sqft allocated per room (conservative)
_PARTITION_COMMON_AREA_PCT = 0.25   # 25% deducted for living rm, kitchen, corridor
_PARTITION_MIN_ROOM_SQFT   = 80     # minimum habitable room size

_PARTITION_ROOM_CAPS = [
    (600,       3),   # < 600 sqft  → max 3 partition rooms
    (800,       4),   # 600–800     → max 4
    (1_000,     5),   # 800–1000    → max 5
    (1_200,     6),   # 1000–1200   → max 6
    (float("inf"), 7),# > 1200      → max 7 (practical residential condo limit)
]

# ── Room rental operating costs (monthly, per unit) ──────────────────────────
# Expenses the landlord bears when renting by room.
ROOM_RENTAL_UTILITIES_PER_ROOM = 100  # electricity + water pro-rata (RM/room/mo)
ROOM_RENTAL_WIFI                = 120  # shared unit WiFi (RM/month)
ROOM_RENTAL_COMMON_CLEANING     = 200  # common area cleaning + minor repairs (RM/mo)
ROOM_RENTAL_MGMT_PREMIUM        = 150  # extra mgmt overhead vs full unit (RM/mo)

# Vacancy allowance for room strategies (lower than full unit — rooms fill faster)
ROOM_VACANCY_MONTHS_PER_YEAR   = 0.5   # 0.5 months idle per room per year (~4%)


def _room_midpoint(lo: int, hi: int) -> float:
    """Return the midpoint of a rental rate range for conservative projection."""
    return float((lo + hi) / 2)


# ── Room composition defaults from bedroom count ─────────────────────────────
# Mapping: bedrooms → (num_master, num_middle, num_small)
_ROOM_COMPOSITION_BY_BR = {
    1: (1, 0, 0),   # 1BR: 1 master
    2: (1, 1, 0),   # 2BR: 1 master + 1 middle
    3: (1, 1, 1),   # 3BR: 1 master + 1 middle + 1 small
    4: (1, 2, 1),   # 4BR: 1 master + 2 middle + 1 small
    5: (1, 2, 2),   # 5BR: 1 master + 2 middle + 2 small
}


def estimate_partition_rooms(built_up_sqft: float) -> Dict:
    """
    Estimate how many partition rooms can fit in a unit of given size.

    Applies the Malaysian landlord rule-of-thumb:
      net useable = built_up × 0.75 (25% for common areas)
      rooms       = floor(net_useable / 180 sqft), capped by unit size
      en-suite    = 1 per every 3 rooms (fire safety / habitability)
      shared WC   = ceiling(non-ensuite rooms / 3)

    Returns:
      useable_sqft          net sqft after common area deduction
      num_rooms             total partition rooms
      num_ensuite           rooms with attached toilet
      num_shared            rooms using shared toilet
      shared_toilets        number of shared toilet blocks needed
      sqft_per_room         average sqft per room
      partition_capex_rm    estimated total conversion CAPEX
      guideline_note        advisory text
    """
    useable = built_up_sqft * (1 - _PARTITION_COMMON_AREA_PCT)
    formula = max(1, int(useable / _PARTITION_SQFT_PER_ROOM))
    cap     = next(c for sz, c in _PARTITION_ROOM_CAPS if built_up_sqft <= sz)
    num_rooms   = min(formula, cap)
    num_ensuite = max(1, num_rooms // 3)
    num_shared  = num_rooms - num_ensuite
    shared_wc   = max(1, -(-num_shared // 3))   # ceiling division
    capex       = (
        num_ensuite * PARTITION_COST_ROOM_ENSUITE
        + num_shared * PARTITION_COST_ROOM_BASIC
        + PARTITION_COST_UNIT_COMMON
    )
    return {
        "useable_sqft":       round(useable),
        "num_rooms":          num_rooms,
        "num_ensuite":        num_ensuite,
        "num_shared":         num_shared,
        "shared_toilets":     shared_wc,
        "sqft_per_room":      round(useable / num_rooms),
        "partition_capex_rm": capex,
        "guideline_note": (
            f"{num_rooms} rooms ({num_ensuite} en-suite, {num_shared} shared-WC) "
            f"from {built_up_sqft:.0f} sqft built-up. "
            f"No national law caps room count; local authority permit required "
            f"for structural works (DBKL/MBPJ). Min 80 sqft per room, 1 window "
            f"per room (BOMBA), ≤3 shared-WC rooms per toilet block."
        ),
    }


def calculate_full_unit_rental_roi(
    reserve_price: float,
    entry_cost: Dict,
    monthly_rent_est: float,
    rent_source: str = "iProperty",
    state: str = "",
    holding_years: int = 5,
    is_citizen: bool = True,
    vacancy_months_per_year: float = 1.0,
    maintenance_monthly: float = 300.0,
) -> Dict:
    """
    Strategy 1 — FULL UNIT rental.

    Rent the entire unit to a single tenant. Simplest management; lowest gross
    income per sqft. Monthly rent from iProperty/market_research.py cache.

    Vacancy default: 1 month/year (~8.3%) — single vacancy event per tenancy.
    Management overhead: property maintenance only (strata fee, minor repairs).

    Returns same fields as calculate_roi() plus:
      roi_mode              = "full_unit"
      rent_strategy         = "full_unit"
      rent_source           label of rental data source
      monthly_rent_est_rm   gross monthly rent used
      eff_monthly_rm        net monthly after vacancy + maintenance
      payback_years         years for rent to cover total_investment
    """
    result = calculate_roi(
        reserve_price=reserve_price,
        entry_cost=entry_cost,
        monthly_rent_est=monthly_rent_est,
        state=state,
        holding_years=holding_years,
        is_citizen=is_citizen,
        vacancy_months_per_year=vacancy_months_per_year,
        maintenance_monthly=maintenance_monthly,
    )
    eff_monthly = monthly_rent_est * (1 - vacancy_months_per_year / 12) - maintenance_monthly
    total_inv   = entry_cost["total_investment_rm"]
    payback     = round(total_inv / (eff_monthly * 12), 1) if eff_monthly > 0 else None
    result.update({
        "roi_mode":            "full_unit",
        "rent_strategy":       "full_unit",
        "rent_source":         rent_source,
        "monthly_rent_est_rm": monthly_rent_est,
        "eff_monthly_rm":      round(eff_monthly, 2),
        "payback_years":       payback,
        "room_breakdown":      [],
    })
    return result


def calculate_room_rental_roi(
    reserve_price: float,
    entry_cost: Dict,
    bedrooms: int = 0,
    built_up_sqft: float = 0.0,
    state: str = "",
    holding_years: int = 5,
    is_citizen: bool = True,
    # Manual room count overrides (0 = auto-derive)
    num_master: int = 0,
    num_middle: int = 0,
    num_small:  int = 0,
    use_midpoint: bool = True,
) -> Dict:
    """
    Strategy 2 — ROOM rental (existing structure, no partition works).

    Rent individual bedrooms of the unit's existing layout. No structural
    changes; bedrooms are rented separately to different tenants (co-living).

    Room composition auto-derived from bedroom count; override with num_* params.

    Rate basis: ROOM_RATES_STANDARD midpoints (furnished, AC, KL/Selangor).
    Vacancy: 0.5 months/room/year (rooms fill faster than whole units).
    Operating costs: utilities + WiFi + common cleaning + mgmt premium deducted.

    Returns:
      roi_mode              = "room_rental"
      rent_strategy         = "room_rental"
      num_rooms             total rooms rented
      room_breakdown        list of {type, count, rate_rm, monthly_rm}
      gross_monthly_rm      total gross monthly rent across all rooms
      opex_monthly_rm       monthly landlord operating costs
      eff_monthly_rm        gross − opex (before mortgage)
      monthly_cashflow_rm   eff_monthly − mortgage instalment
      gross_yield_pct       gross annual / reserve_price × 100
      net_yield_pct         eff_annual / reserve_price × 100
      payback_years         years for net rent to cover total_investment
      roi_pct               (net_cap_gain + total_net_rent) / cash_day1 × 100
      + all fields from calculate_roi()
    """
    # ── Derive room composition ───────────────────────────────────────────────
    if num_master or num_middle or num_small:
        nm, nmd, ns = num_master, num_middle, num_small
    elif bedrooms in _ROOM_COMPOSITION_BY_BR:
        nm, nmd, ns = _ROOM_COMPOSITION_BY_BR[bedrooms]
    elif built_up_sqft > 0:
        br_est = max(1, int(built_up_sqft / 400))
        nm, nmd, ns = _ROOM_COMPOSITION_BY_BR.get(br_est, (1, 1, 0))
    else:
        nm, nmd, ns = 1, 1, 0   # conservative default

    num_rooms = nm + nmd + ns

    # ── Monthly rent per room type ────────────────────────────────────────────
    r = ROOM_RATES_STANDARD
    if use_midpoint:
        rate_master = _room_midpoint(r["master_min"], r["master_max"])
        rate_middle = _room_midpoint(r["middle_min"], r["middle_max"])
        rate_small  = _room_midpoint(r["small_min"],  r["small_max"])
    else:
        rate_master = r["master_min"]
        rate_middle = r["middle_min"]
        rate_small  = r["small_min"]

    # Vacancy: 0.5 months/year per room
    vac_factor = 1 - ROOM_VACANCY_MONTHS_PER_YEAR / 12
    gross_master = nm  * rate_master * vac_factor
    gross_middle = nmd * rate_middle * vac_factor
    gross_small  = ns  * rate_small  * vac_factor
    gross_monthly = gross_master + gross_middle + gross_small

    # ── Operating costs (landlord-side) ──────────────────────────────────────
    opex_monthly = (
        num_rooms * ROOM_RENTAL_UTILITIES_PER_ROOM
        + ROOM_RENTAL_WIFI
        + ROOM_RENTAL_COMMON_CLEANING
        + ROOM_RENTAL_MGMT_PREMIUM
    )

    eff_monthly  = gross_monthly - opex_monthly
    monthly_cf   = round(eff_monthly - entry_cost["monthly_instalment_rm"], 2)

    # ── Yields ───────────────────────────────────────────────────────────────
    ann_gross   = gross_monthly * 12
    ann_eff     = eff_monthly   * 12
    gross_yield = round(ann_gross / reserve_price * 100, 2) if reserve_price else 0.0
    net_yield   = round(ann_eff  / reserve_price * 100, 2) if reserve_price else 0.0

    # ── Capital appreciation + ROI ────────────────────────────────────────────
    appn  = APPRECIATION_PA.get(state, DEFAULT_APPRECIATION) / 100
    exit_ = round(reserve_price * (1 + appn) ** holding_years)
    cap_g = exit_ - reserve_price
    tax   = round(max(0.0, cap_g) * rpgt_rate(holding_years, is_citizen), 2)
    net_g = round(cap_g - tax, 2)

    total_rent = round(eff_monthly * 12 * holding_years, 2)
    cash_day1  = entry_cost["total_cash_day1_rm"]
    total_inv  = entry_cost["total_investment_rm"]
    roi_pct    = round((net_g + total_rent) / cash_day1 * 100, 1) if cash_day1 else 0.0

    payback = round(total_inv / (eff_monthly * 12), 1) if eff_monthly > 0 else None

    breakdown = []
    if nm:  breakdown.append({"type": "master", "count": nm,  "rate_rm": rate_master, "monthly_rm": round(nm  * rate_master * vac_factor, 0)})
    if nmd: breakdown.append({"type": "middle", "count": nmd, "rate_rm": rate_middle, "monthly_rm": round(nmd * rate_middle * vac_factor, 0)})
    if ns:  breakdown.append({"type": "small",  "count": ns,  "rate_rm": rate_small,  "monthly_rm": round(ns  * rate_small  * vac_factor, 0)})

    return {
        "roi_mode":              "room_rental",
        "rent_strategy":         "room_rental",
        "num_rooms":             num_rooms,
        "room_breakdown":        breakdown,
        "gross_monthly_rm":      round(gross_monthly, 2),
        "opex_monthly_rm":       round(opex_monthly, 2),
        "eff_monthly_rm":        round(eff_monthly, 2),
        "monthly_cashflow_rm":   monthly_cf,
        "gross_yield_pct":       gross_yield,
        "net_yield_pct":         net_yield,
        "payback_years":         payback,
        "holding_years":         holding_years,
        "appreciation_rate_pct": APPRECIATION_PA.get(state, DEFAULT_APPRECIATION),
        "exit_price_est_rm":     exit_,
        "capital_gain_rm":       round(cap_g, 2),
        "rpgt_rm":               tax,
        "net_capital_gain_rm":   net_g,
        "total_rent_rm":         total_rent,
        "total_investment_rm":   total_inv,
        "total_cash_day1_rm":    cash_day1,
        "roi_pct":               roi_pct,
    }


def calculate_partition_roi(
    reserve_price: float,
    entry_cost: Dict,
    built_up_sqft: float,
    state: str = "",
    holding_years: int = 5,
    is_citizen: bool = True,
    # Override room count (0 = auto from estimate_partition_rooms)
    num_ensuite_override: int = 0,
    num_shared_override:  int = 0,
    use_midpoint: bool = True,
) -> Dict:
    """
    Strategy 3 — PARTITION room rental.

    Convert the unit into more rooms using drywall partitions (co-living model).
    CAPEX (partition setup cost) is ADDED to entry_cost total_investment for ROI.

    Room count auto-estimated from built_up_sqft via estimate_partition_rooms().
    Override with num_ensuite_override + num_shared_override if known.

    Rate basis: ROOM_RATES_PARTITION midpoints (slightly below standard rooms).
    Vacancy: 0.5 months/room/year (same as room rental — faster to fill).

    Returns same fields as calculate_room_rental_roi() plus:
      roi_mode              = "partition"
      rent_strategy         = "partition"
      partition_capex_rm    total CAPEX for room conversion
      total_investment_rm   entry_cost.total_investment + partition_capex
      guideline_note        advisory text on room count method + permit note
      room_detail           dict from estimate_partition_rooms()
    """
    if not built_up_sqft or built_up_sqft <= 0:
        return {"roi_mode": "partition", "error": "built_up_sqft not available"}
    room_info = estimate_partition_rooms(built_up_sqft)

    ne = num_ensuite_override if num_ensuite_override else room_info["num_ensuite"]
    ns = num_shared_override  if num_shared_override  else room_info["num_shared"]
    # Recalculate capex with overrides
    capex = (
        ne * PARTITION_COST_ROOM_ENSUITE
        + ns * PARTITION_COST_ROOM_BASIC
        + PARTITION_COST_UNIT_COMMON
    )

    num_rooms = ne + ns

    r = ROOM_RATES_PARTITION
    if use_midpoint:
        rate_ensuite = _room_midpoint(r["master_min"], r["master_max"])
        rate_shared  = _room_midpoint(r["middle_min"], r["middle_max"])
    else:
        rate_ensuite = r["master_min"]
        rate_shared  = r["middle_min"]

    vac_factor   = 1 - ROOM_VACANCY_MONTHS_PER_YEAR / 12
    gross_monthly = (
        ne * rate_ensuite * vac_factor
        + ns * rate_shared  * vac_factor
    )

    # Operating costs — partition setup has more tenants so slightly higher
    opex_monthly = (
        num_rooms * ROOM_RENTAL_UTILITIES_PER_ROOM
        + ROOM_RENTAL_WIFI
        + ROOM_RENTAL_COMMON_CLEANING
        + ROOM_RENTAL_MGMT_PREMIUM
    )

    eff_monthly = gross_monthly - opex_monthly
    # CAPEX added to investment basis
    total_inv_aug = entry_cost["total_investment_rm"] + capex
    cash_day1     = entry_cost["total_cash_day1_rm"]
    monthly_cf    = round(eff_monthly - entry_cost["monthly_instalment_rm"], 2)

    gross_yield  = round(gross_monthly * 12 / reserve_price * 100, 2) if reserve_price else 0.0
    net_yield    = round(eff_monthly   * 12 / reserve_price * 100, 2) if reserve_price else 0.0

    appn  = APPRECIATION_PA.get(state, DEFAULT_APPRECIATION) / 100
    exit_ = round(reserve_price * (1 + appn) ** holding_years)
    cap_g = exit_ - reserve_price
    tax   = round(max(0.0, cap_g) * rpgt_rate(holding_years, is_citizen), 2)
    net_g = round(cap_g - tax, 2)

    total_rent = round(eff_monthly * 12 * holding_years, 2)
    roi_pct    = round((net_g + total_rent) / (cash_day1 + capex) * 100, 1) if (cash_day1 + capex) else 0.0

    payback = round(total_inv_aug / (eff_monthly * 12), 1) if eff_monthly > 0 else None

    breakdown = []
    if ne: breakdown.append({"type": "ensuite",  "count": ne, "rate_rm": rate_ensuite, "monthly_rm": round(ne * rate_ensuite * vac_factor, 0)})
    if ns: breakdown.append({"type": "shared_wc","count": ns, "rate_rm": rate_shared,  "monthly_rm": round(ns * rate_shared  * vac_factor, 0)})

    return {
        "roi_mode":              "partition",
        "rent_strategy":         "partition",
        "num_rooms":             num_rooms,
        "num_ensuite":           ne,
        "num_shared":            ns,
        "room_breakdown":        breakdown,
        "partition_capex_rm":    capex,
        "gross_monthly_rm":      round(gross_monthly, 2),
        "opex_monthly_rm":       round(opex_monthly, 2),
        "eff_monthly_rm":        round(eff_monthly, 2),
        "monthly_cashflow_rm":   monthly_cf,
        "gross_yield_pct":       gross_yield,
        "net_yield_pct":         net_yield,
        "payback_years":         payback,
        "holding_years":         holding_years,
        "appreciation_rate_pct": APPRECIATION_PA.get(state, DEFAULT_APPRECIATION),
        "exit_price_est_rm":     exit_,
        "capital_gain_rm":       round(cap_g, 2),
        "rpgt_rm":               tax,
        "net_capital_gain_rm":   net_g,
        "total_rent_rm":         total_rent,
        "total_investment_rm":   total_inv_aug,
        "total_cash_day1_rm":    cash_day1,
        "roi_pct":               roi_pct,
        "room_detail":           room_info,
        "guideline_note":        room_info["guideline_note"],
    }


# ── Legacy wrapper — kept for back-compat (used by e2e_due_diligence.py) ──────
def calculate_rental_roi(
    reserve_price: float,
    entry_cost: Dict,
    monthly_rent_est: float,
    rent_source: str = "iProperty",
    state: str = "",
    holding_years: int = 5,
    is_citizen: bool = True,
    vacancy_months_per_year: float = 1.0,
    maintenance_monthly: float = 300.0,
) -> Dict:
    """
    Rental ROI — hold for rental income, then sell at appreciated value.

    Uses ACTUAL rental market data (from iProperty or iBilik) instead of
    guessing. If monthly_rent_est == 0, still computes metrics but flags
    that the rental source is unavailable.

    rental_source: label of where rent data came from (e.g. "iProperty",
                   "iBilik", "manual"). Cross-check with iBilik.my for
                   room/unit rental rates in the same area.

    Returns all fields from calculate_roi() plus:
      rent_source           where the rental estimate came from
      monthly_rent_est_rm   the monthly rent used
      payback_years         how many years of net rent to cover total_investment
    """
    result = calculate_roi(
        reserve_price=reserve_price,
        entry_cost=entry_cost,
        monthly_rent_est=monthly_rent_est,
        state=state,
        holding_years=holding_years,
        is_citizen=is_citizen,
        vacancy_months_per_year=vacancy_months_per_year,
        maintenance_monthly=maintenance_monthly,
    )

    eff_monthly = monthly_rent_est * (1 - vacancy_months_per_year / 12) - maintenance_monthly
    total_inv   = entry_cost["total_investment_rm"]
    payback     = None
    if eff_monthly > 0:
        payback = round(total_inv / (eff_monthly * 12), 1)

    result.update({
        "roi_mode":              "rental",
        "rent_source":           rent_source,
        "monthly_rent_est_rm":   monthly_rent_est,
        "eff_monthly_rm":        round(eff_monthly, 2),
        "payback_years":         payback,
    })
    return result
