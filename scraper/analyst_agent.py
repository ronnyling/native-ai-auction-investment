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

Output ONLY valid JSON with exactly three keys:
  "score"          integer 0-100
  "recommendation" one of: "skip" "investigate" "shortlist" "bid"
  "reasoning"      string, 1-2 sentences, specific facts from this property, \
                   no generic investment advice
"""


def _build_prompt(listing: Dict) -> str:
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

    return "\n".join(lines)


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

    def analyze(self, listing: Dict) -> Optional[Dict]:
        """
        Analyze a single listing via OpenAI.
        Returns dict with agent_* fields, or None on failure.
        """
        if not self._available:
            return None

        prompt = _build_prompt(listing)

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                max_tokens=250,
                temperature=0.2,
            )
            raw  = resp.choices[0].message.content
            data = json.loads(raw)

            score = int(data.get("score", 0))
            rec   = str(data.get("recommendation", "investigate")).lower().strip()
            if rec not in {"skip", "investigate", "shortlist", "bid"}:
                rec = "investigate"

            return {
                "agent_score":          max(0, min(100, score)),
                "agent_recommendation": rec,
                "agent_reasoning":      str(data.get("reasoning", ""))[:500],
                "agent_run_date":       str(date.today()),
            }

        except Exception as exc:
            print(f"  [analyst] API error for {listing.get('listing_id')}: {exc}")
            return None

    def enrich_listings(self, listings: List[Dict]) -> Tuple[int, int]:
        """
        Score all high-priority listings. Adds agent_* fields in-place.
        Returns (enriched_count, skipped_count).
        """
        if not self._available:
            return 0, len(listings)

        enriched = 0
        skipped  = 0

        for listing in listings:
            if not self.is_high_priority(listing):
                skipped += 1
                continue

            result = self.analyze(listing)
            if result:
                listing.update(result)
                enriched += 1
            else:
                skipped += 1

            if enriched > 0 and enriched % 10 == 0:
                print(f"  [analyst] {enriched} scored so far...")

            time.sleep(REQUEST_DELAY)

        return enriched, skipped
