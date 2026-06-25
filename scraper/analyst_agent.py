"""
analyst_agent.py — LLM-powered investment scoring for auction properties.

Uses OpenAI GPT-4o-mini to evaluate each high-priority property and output:
  agent_score          int 0-100
  agent_recommendation str "skip" | "investigate" | "shortlist" | "bid"
  agent_reasoning      str 1-2 sentences specific to this property

Runs only on properties where bmv_pct >= HIGH_PRIORITY_BMV or
auction_count >= HIGH_PRIORITY_ROUND (same threshold as market_research.py).

Environment variables:
  OPENAI_API_KEY   required — OpenAI API key
  ANALYST_MODEL    optional — model to use (default: gpt-4o-mini)
"""

import json
import os
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ── Constants ─────────────────────────────────────────────────────────────────

HIGH_PRIORITY_BMV   = 29
HIGH_PRIORITY_ROUND = 3
REQUEST_DELAY       = 0.3   # seconds between API calls (rate-limit safety)
DEFAULT_MODEL       = "gpt-4o-mini"

# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a Malaysian property investment analyst specialising in distressed \
bank auction properties from BidNow.my.

Evaluation criteria:
1. Price vs market value — BMV% (Below Market Value): 30%+ is strong, 20%+ is decent
2. Rental yield: 5%+ annual is attractive, 7%+ is excellent for Malaysia
3. Auction round: more rounds means a motivated seller but also flags possible issues \
   (access problems, disputes, illegal occupation, or unrealistic original pricing)
4. Legal entry type: LACA (Loans Against Courts Act) = simpler entry process; \
   court order = more paperwork and risk
5. Tenure & restrictions: freehold > leasehold; Bumi-lot restrictions limit exit options
6. Location: Klang Valley (KL/PJ/Selangor/Putrajaya) has highest liquidity; \
   East Malaysia / Kedah / Kelantan / Terengganu = lower demand and longer holding

Score 0-100 mapped to recommendation:
  0-30   → skip        (poor fundamentals or excessive risk)
  31-60  → investigate (interesting but needs more due diligence before committing)
  61-80  → shortlist   (strong candidate — proceed to site visit and POS review)
  81-100 → bid         (high conviction — act quickly)

Recommendation must be consistent with score range.

Exit strategy — recommend one of:
  flip       Sell within 12 months; suitable when BMV > 35% in high-liquidity area
             (RPGT 30% applies if sold within 3 years — factor this in)
  rent       Hold 1–5 years; suitable when gross yield ≥ 5.5%
  long_hold  Hold > 5 years; best for RPGT-exempt exit (>5yr for citizens) and
             long-term appreciation plays; suitable when yield < 5% but location strong
  skip       Fundamentals too weak for any strategy

Holding period — recommend one of:
  "< 1 year"   for flip
  "1-3 years"  short medium-term
  "3-5 years"  standard medium-term
  "5+ years"   long-term hold
  "N/A"        for skip

Key risks — list top 2-3 specific risks from:
  - High auction round (R3+): possible title dispute, illegal occupant, structural issue
  - Leasehold < 50yr remaining: affects mortgageability and resale
  - Bumi restriction: limits buyer pool
  - Court order type: more complex entry paperwork vs LACA
  - Remote / low-demand area: illiquidity, long holding expected
  - High iProperty competition: crowded retail market, harder to flip at premium
  - Negative cashflow: monthly instalment exceeds expected rent

Due diligence flags — urgent checks before bidding:
  - Site visit to verify physical condition and occupancy status
  - Order land search and bankruptcy search
  - Confirm reserve price vs independent valuation (check BMV claims)
  - Verify POS is current (listing ID in file path matches property ID)

Output ONLY valid JSON with exactly these keys:
  "score"              integer 0-100
  "recommendation"     one of: "skip" "investigate" "shortlist" "bid"
  "reasoning"          string, 1-2 sentences, specific facts from this property,
                       no generic investment advice
  "exit_strategy"      one of: "flip" "rent" "long_hold" "skip"
  "holding_period"     one of: "< 1 year" "1-3 years" "3-5 years" "5+ years" "N/A"
  "key_risks"          string, comma-separated, top 2-3 risks
  "due_diligence_flags" string, comma-separated, top 2-3 checks to do before bidding
"""


def _build_prompt(listing: Dict, entry_cost: Dict = None, competition: Dict = None) -> str:
    r        = listing.get("reserve_price", 0) or 0
    mv       = listing.get("market_value", 0) or 0
    bmv      = listing.get("bmv_pct", 0) or listing.get("bmv_percent", 0) or 0
    ind_bmv  = listing.get("independent_bmv_pct")
    mkt_est  = listing.get("market_value_est")
    mkt_psf  = listing.get("market_sale_psf")
    yld      = listing.get("est_rental_yield")
    rent_est = listing.get("market_rent_est")
    rnd      = listing.get("auction_count", 1) or 1
    orig_r   = listing.get("original_reserve", r) or r
    drop     = listing.get("total_price_drop", 0) or 0
    days     = listing.get("days_to_auction", "?")
    n_comps  = listing.get("market_comps_n", 0) or 0
    match    = listing.get("market_area_match", "none")
    city     = listing.get("district", listing.get("city", "?"))

    lines = [
        f"Property: {listing.get('property_type', 'Unknown')} in {city}, {listing.get('state', '?')}",
        f"Tenure: {listing.get('tenure', '?')} | Auction type: {listing.get('auction_type', '?')}",
        f"Reserve: RM {r:,} | BidNow market value: RM {mv:,} | BidNow BMV: {bmv}%",
    ]

    if ind_bmv is not None and mkt_est:
        lines.append(
            f"Independent market est: RM {mkt_est:,} @ RM {mkt_psf:.2f}/sqft "
            f"({match} match, {n_comps} comps) | Independent BMV: {ind_bmv}%"
        )
    else:
        lines.append("Independent market data: not available (area not covered by iProperty sample)")

    if yld is not None and rent_est:
        lines.append(f"Est. rental yield: {yld}% | Est. rent: RM {rent_est:,}/mo")
    else:
        lines.append("Rental yield: not available")

    drop_str = f" | Total price drop: {drop}%" if drop else ""
    lines.append(f"Auction round: {rnd} | Original reserve: RM {orig_r:,}{drop_str}")
    lines.append(f"Bank: {listing.get('bank', '?')} | Days to auction: {days}")

    if entry_cost:
        cash_d1 = entry_cost.get("total_cash_day1_rm", 0)
        total_i = entry_cost.get("total_investment_rm", 0)
        monthly = entry_cost.get("monthly_instalment_rm", 0)
        lines.append(
            f"Entry cost: deposit RM {entry_cost.get('deposit_rm',0):,.0f} | "
            f"Total cash day-1 RM {cash_d1:,.0f} | "
            f"Total investment RM {total_i:,.0f} | "
            f"Monthly instalment RM {monthly:,.0f}"
        )

    if competition:
        lvl   = competition.get("competition_level", "Unknown")
        n_cmp = competition.get("comparable_count") or 0
        n_tot = competition.get("total_area_count", 0)
        med_a = competition.get("median_asking", 0)
        lines.append(
            f"iProperty competition: {lvl} | {n_cmp} comparables of {n_tot} area listings"
            + (f" | Median asking RM {med_a:,.0f}" if med_a else "")
        )

    if r > 0 and mv > 0:
        ratio = mv / r
        if ratio > 2.5:
            lines.append(
                "Plausibility check: High-risk assumption - market value appears unusually high "
                f"relative to reserve ({ratio:.1f}x)."
            )

    return "\n".join(lines)


def _high_risk_assumption_flag(listing: Dict) -> Optional[str]:
    reserve = float(listing.get("reserve_price") or 0)
    market_value = float(listing.get("market_value") or listing.get("market_value_est") or 0)
    if reserve > 0 and market_value > 0:
        ratio = market_value / reserve
        if ratio > 2.5:
            return (
                "High-risk assumption - market value appears unusually high relative to reserve "
                f"({ratio:.1f}x)"
            )
    return None


def _append_guardrail_risk(existing: str, listing: Dict) -> str:
    guardrail = _high_risk_assumption_flag(listing)
    if not guardrail:
        return existing
    if guardrail in existing:
        return existing
    return f"{existing}, {guardrail}" if existing else guardrail


# ── Rule-based fallback (no OpenAI API key) ───────────────────────────────────

def _score_rule_based(listing: Dict) -> Dict:
    """
    Simple deterministic scoring used when OpenAI is unavailable.
    Not a substitute for LLM analysis — flags only the most obvious signals.
    """
    bmv      = float(listing.get("bmv_pct") or listing.get("bmv_percent") or 0)
    rnd      = int(listing.get("auction_count", 1) or 1)
    yld      = float(listing.get("est_rental_yield") or 0)
    import re as _re
    state    = _re.sub(r'^\d{5}\s+', '', (listing.get("state") or "").strip())
    tenure   = (listing.get("tenure") or "").lower()

    # BMV-tiered base score (not linear-capped — very high BMV deserves shortlist territory)
    if bmv >= 40:
        base_score = 55   # very strong discount, shortlist territory
    elif bmv >= 30:
        base_score = 40   # good discount
    elif bmv >= 20:
        base_score = 25   # modest discount
    else:
        base_score = max(0, bmv * 1.0)

    score  = base_score
    score += min(20, max(0, (yld - 3.0) * 5.0)) if yld else 0    # yield above 3%
    score += 10 if state in {"Kuala Lumpur", "Selangor", "Putrajaya"} else 0
    score += 5 if "freehold" in tenure else 0
    # High round: motivated seller but flag risk
    if rnd >= 3:
        score += 5

    score = int(max(0, min(100, score)))

    if score >= 81:
        rec = "bid"
    elif score >= 61:
        rec = "shortlist"
    elif score >= 31:
        rec = "investigate"
    else:
        rec = "skip"

    # Exit strategy — only recommend flip for shortlist/bid level conviction
    if rec == "skip":
        exit_strat, hold_period = "skip", "N/A"
    elif rec in ("shortlist", "bid") and bmv >= 35 and state in {"Kuala Lumpur", "Selangor", "Putrajaya", "Penang"}:
        exit_strat, hold_period = "flip", "< 1 year"
    elif yld >= 5.5:
        exit_strat, hold_period = "rent", "3-5 years"
    else:
        exit_strat, hold_period = "long_hold", "5+ years"

    risks = []
    if float(listing.get("market_value") or listing.get("market_value_est") or 0) > 0 or yld > 0:
        risks.append("Market value and rental yield are source estimates — verify independently")
    if rnd >= 3:
        risks.append(f"Round {rnd} — possible title or occupancy issue")
    if "leasehold" in tenure:
        risks.append("Leasehold — check years remaining and mortgageability")
    if bmv <= 10:
        risks.append("Low discount — limited margin of safety")
    high_risk_assumption = _high_risk_assumption_flag(listing)
    if high_risk_assumption:
        risks.append(high_risk_assumption)
    if not risks:
        risks.append("Verify physical condition and occupancy before bidding")

    dd_flags = [
        "Site visit + occupancy check",
        "Land search + bankruptcy search",
        "Confirm POS is current",
    ]

    return {
        "agent_score":            score,
        "agent_recommendation":   rec,
        "agent_reasoning":        f"Rule-based estimate: BMV {bmv}%, yield {yld}%, round {rnd}.",
        "agent_exit_strategy":    exit_strat,
        "agent_holding_period":   hold_period,
        "agent_key_risks":        ", ".join(risks[:3]),
        "agent_due_diligence":    ", ".join(dd_flags[:3]),
        "agent_run_date":         str(date.today()),
        "agent_mode":             "rule_based",
    }


# ── Main class ────────────────────────────────────────────────────────────────

class AnalystAgent:

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model   = os.environ.get("ANALYST_MODEL", DEFAULT_MODEL)
        self._client = None
        self._available = False

        if not OPENAI_AVAILABLE:
            print("  [analyst] openai package not installed — skipping agent stage")
            return
        if not self.api_key:
            print("  [analyst] OPENAI_API_KEY not set — skipping agent stage")
            return

        try:
            self._client = OpenAI(api_key=self.api_key)
            self._available = True
        except Exception as exc:
            print(f"  [analyst] OpenAI init failed: {exc}")

    @property
    def available(self) -> bool:
        return self._available

    def is_high_priority(self, listing: Dict) -> bool:
        bmv = listing.get("bmv_pct") or listing.get("bmv_percent") or 0
        rnd = listing.get("auction_count", 1) or 1
        return float(bmv) >= HIGH_PRIORITY_BMV or int(rnd) >= HIGH_PRIORITY_ROUND

    def analyze(
        self,
        listing: Dict,
        entry_cost: Dict = None,
        competition: Dict = None,
    ) -> Optional[Dict]:
        """
        Analyze a single listing via OpenAI.
        Optionally accepts pre-computed entry_cost and competition dicts
        to enrich the prompt with due-diligence context.
        Returns dict with agent_* fields, or None on failure.
        """
        if not self._available:
            return None

        prompt = _build_prompt(listing, entry_cost=entry_cost, competition=competition)

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=400,
                temperature=0.2,
            )
            raw  = resp.choices[0].message.content
            data = json.loads(raw)

            score = int(data.get("score", 0))
            rec   = str(data.get("recommendation", "investigate")).lower().strip()
            if rec not in {"skip", "investigate", "shortlist", "bid"}:
                rec = "investigate"

            exit_s = str(data.get("exit_strategy", "long_hold")).lower().strip()
            if exit_s not in {"flip", "rent", "long_hold", "skip"}:
                exit_s = "long_hold"

            return {
                "agent_score":            max(0, min(100, score)),
                "agent_recommendation":   rec,
                "agent_reasoning":        str(data.get("reasoning", ""))[:500],
                "agent_exit_strategy":    exit_s,
                "agent_holding_period":   str(data.get("holding_period", ""))[:30],
                "agent_key_risks":        _append_guardrail_risk(str(data.get("key_risks", ""))[:300], listing),
                "agent_due_diligence":    str(data.get("due_diligence_flags", ""))[:300],
                "agent_run_date":         str(date.today()),
                "agent_mode":             "llm",
            }

        except Exception as exc:
            print(f"  [analyst] API error for {listing.get('listing_id')}: {exc}")
            return None

    def enrich_listings(self, listings: List[Dict]) -> Tuple[int, int]:
        """
        Score all high-priority listings. Adds agent_* fields in-place.
        Falls back to rule-based scoring when OpenAI is unavailable.
        Returns (enriched_count, skipped_count).
        """
        enriched = 0
        skipped  = 0

        for listing in listings:
            if not self.is_high_priority(listing):
                skipped += 1
                continue

            if self._available:
                result = self.analyze(listing)
            else:
                result = _score_rule_based(listing)

            if result:
                listing.update(result)
                enriched += 1
            else:
                skipped += 1

            if enriched > 0 and enriched % 10 == 0:
                print(f"  [analyst] {enriched} scored so far...")

            if self._available:
                time.sleep(REQUEST_DELAY)

        return enriched, skipped
