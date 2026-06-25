"""
hermes.py — MiMo LLM fallback extractor for incomplete POS documents.

When pos_parser.py regex extraction leaves essential fields missing
(i.e. _extraction_complete == False), Hermes submits the full POS text to
MiMo LLM and asks it to fill the gaps.

Architecture:
  pos_parser.py handles clean, well-structured patterns (the common cases).
  hermes.py (MiMo) handles everything pos_parser.py could not extract —
  edge cases, exotic formats, Islamic finance labels, 3-party docs, etc.
  MiMo supports 256 k context so the complete document is always sent
  without truncation.

Essential fields targeted:
  bank               The mortgagee / plaintiff (bank or government agency)
  borrower           The registered owner / defendant / assignor
  reserve_price_rm   Minimum bid (float, RM)
  deposit_required_rm  Deposit payable at auction (float, RM; usually 10% of reserve)
  disbursement_days  Days allowed to pay the balance (int; typically 90 or 120)
  encumbrances       Charges / liens on title (str; "Tiada" / "Nil" = none)
  location           Full postal address of the property (str)
  tenure             "freehold" | "leasehold"

Usage:
  from hermes import HermesAgent
  agent = HermesAgent()
  if agent.available and not pos_fields.get("_extraction_complete"):
      pos_fields = agent.enrich_pos(raw_text, pos_fields)
      # pos_fields["_hermes_mode"] tells you what happened

Environment variable overrides:
  MIMO_API_KEY    override the built-in API key
  MIMO_BASE_URL   override the built-in base URL
  MIMO_MODEL      override the default model (default: mimo-v2.5-pro)
  HERMES_MODEL    legacy alias for MIMO_MODEL
"""

import json
import os
import re
from typing import Any, Dict, List, Tuple

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

try:
    from pos_parser import ESSENTIAL_FIELDS      # when run from scraper/
except ImportError:
    from scraper.pos_parser import ESSENTIAL_FIELDS  # when run from project root

# ── MiMo credentials ─────────────────────────────────────────────────────────
# Override via environment variables; do not commit credentials to shared repos.

_MIMO_KEY      = os.environ.get("MIMO_API_KEY",  "tp-sgckfety1agxyyxu9ypqheyln1o09rrnca8r4lhz94xx9p47")
_MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
_MIMO_MODEL    = os.environ.get("MIMO_MODEL",    "mimo-v2.5-pro")

# ── Soft document size cap (flags, does not truncate) ─────────────────────────
# ~200 k tokens @ ~4 chars/token for MiMo's 256 k context window.
MAX_SAFE_CHARS = 800_000


# ── Field-presence helpers ─────────────────────────────────────────────────────

# Fields where numeric zero is semantically invalid (price/days are never 0).
# Only these fields trigger the zero-as-missing rule, keeping future fields safe.
_ZERO_IS_MISSING_FIELDS = {"reserve_price_rm", "deposit_required_rm", "disbursement_days"}


def _is_missing(field: str, value: Any) -> bool:
    """Return True when value is absent, None, empty-string, or numeric zero.

    Zero is treated as missing only for fields in _ZERO_IS_MISSING_FIELDS so
    that future numeric fields where zero may be valid (e.g. floor_number)
    are unaffected by this rule.
    """
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if field in _ZERO_IS_MISSING_FIELDS and isinstance(value, (int, float)) and value == 0:
        return True
    return False


def _parse_rm(raw: Any) -> float:
    """Parse a Ringgit amount from various model output formats.

    Handles: 350000.0, "350,000", "RM 350,000.00", "RM350,000", "350,000.00 RM"
    """
    s = str(raw).strip()
    s = re.sub(r"(?i)\bRM\b", "", s).strip()   # remove RM prefix/suffix
    s = re.sub(r"[,\s]", "", s)                # remove thousand separators
    s = re.sub(r"[^\d.]", "", s)               # keep only digits and decimal point
    return float(s)


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    """Robustly extract the first valid JSON object from a model response.

    Handles plain JSON, markdown-fenced JSON, prose + JSON, and commentary
    after the JSON block. Uses json.JSONDecoder.raw_decode so that nested
    braces inside string values are handled correctly.
    """
    # Strip markdown code fences
    clean = re.sub(r"```(?:json)?\s*|\s*```", "", text).strip()

    # Fast path: the entire stripped response is valid JSON
    try:
        obj = json.loads(clean)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Walk the string looking for the first parseable JSON object.
    # raw_decode handles nested braces inside string values correctly.
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(clean):
        idx = clean.find("{", pos)
        if idx == -1:
            break
        try:
            obj, _ = decoder.raw_decode(clean, idx)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        pos = idx + 1

    return {}


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a Malaysian legal document parser specialising in Proclamation of Sale \
(POS / Perisytiharan Jualan) documents used in property auction proceedings.

Documents are bilingual (Malay + English). Key term mappings:
  bank / plaintiff  = mortgagee:  PLAINTIF (court order) or
                                  Pemegang Serahhak/Pembiaya (Malay LACA) or
                                  Assignee/Bank (English LACA)
  borrower          = mortgagor:  DEFENDAN (court) or Penyerah Hak / Assignor/Borrower (LACA)
  reserve price     = harga rizab / Reserve Price (minimum auction bid)
  deposit           = wang pendahuluan / deposit (usually 10% of reserve price,
                      payable on auction day)
  disbursement_days = tempoh pembayaran baki / days to pay balance
                      (commonly 90 or 120 days from auction date)
  encumbrances      = bebanan (charges/liens on title; "Tiada" or "Nil" = none)
  location          = full postal address of the property
  tenure            = Hakmilik Kekal → freehold; Hakmilik Pajakan → leasehold

Your task: extract ONLY the fields listed below. Return valid JSON. \
Use null for any field you cannot confidently extract. \
Do NOT include extra fields. Do NOT add commentary.

Required JSON schema:
{
  "bank":                "Name of bank/plaintiff (string or null)",
  "borrower":            "Name of borrower/defendant (string or null)",
  "reserve_price_rm":    0.0,
  "deposit_required_rm": 0.0,
  "disbursement_days":   0,
  "encumbrances":        "Description or Nil/Tiada (string or null)",
  "location":            "Full postal address (string or null)",
  "tenure":              "freehold or leasehold (string or null)"
}"""


# ── Standalone completeness helper ───────────────────────────────────────────

def check_pos_completeness(fields: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Return (is_complete, missing_fields) for a parse_pos_fields() result.

    A field counts as missing when its value is absent, None, empty-string,
    or numeric zero — not merely when the key is absent. This means a parser
    that sets 'bank': None is treated the same as one that omits the key.
    """
    missing = [f for f in ESSENTIAL_FIELDS if _is_missing(f, fields.get(f))]
    return len(missing) == 0, missing


# ── HermesAgent ───────────────────────────────────────────────────────────────

class HermesAgent:
    """
    LLM-powered fallback for incomplete POS field extraction.

    Instantiate once and reuse:
        agent = HermesAgent()
        if agent.available:
            enriched = agent.enrich_pos(raw_text, partial_fields)

    `_hermes_mode` key in the returned dict:
        "skipped_complete" — nothing was missing; MiMo did not run
        "llm"              — LLM extraction ran (fields may have been added)
        "unavailable"      — openai package not installed
        "error"            — LLM call failed; partial_fields returned unchanged
    """

    def __init__(self, model: str | None = None, client=None):
        """
        Args:
            model:  Override model name (else checks MIMO_MODEL / HERMES_MODEL env vars).
            client: Inject a pre-built OpenAI-compatible client. Bypasses package and
                    credential checks — pass a MagicMock to test without openai installed.
        """
        self.model = (
            model
            or os.environ.get("MIMO_MODEL")
            or os.environ.get("HERMES_MODEL")
            or "mimo-v2.5-pro"
        )
        if client is not None:
            # Dependency injection — skip all package / credential validation.
            self._client = client
            self.available = True
            return
        self._client = None
        if not _OPENAI_AVAILABLE:
            self.available = False
            return
        if not _MIMO_KEY:
            self.available = False
            return
        self._client = OpenAI(
            api_key=_MIMO_KEY,
            base_url=_MIMO_BASE_URL,
        )
        self.available = True

    # ── Public API ────────────────────────────────────────────────────────────

    def enrich_pos(
        self,
        raw_text: str,
        partial_fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Fill missing essential fields using LLM, then update completeness metadata.

        Args:
            raw_text:       Full POS text (from PDF extraction)
            partial_fields: Dict returned by parse_pos_fields()

        Returns:
            The same dict, mutated in-place with any newly extracted fields and
            updated _extraction_complete / _missing_essential / _hermes_mode.
        """
        if not self.available:
            partial_fields["_hermes_mode"] = "unavailable"
            return partial_fields

        is_complete, missing = check_pos_completeness(partial_fields)
        if is_complete:
            partial_fields["_hermes_mode"] = "skipped_complete"
            return partial_fields

        already_extracted = {
            k: v for k, v in partial_fields.items()
            if not k.startswith("_")
        }
        # Send the full document — MiMo supports 256 k context, no truncation needed.
        clean_text = raw_text.strip()
        if len(clean_text) > MAX_SAFE_CHARS:
            partial_fields["_hermes_warning"] = "very_large_document"
        user_msg = (
            f"Fields NOT yet extracted (need these): {missing}\n\n"
            f"Already extracted (do NOT re-extract): {json.dumps(already_extracted)}\n\n"
            f"FULL POS TEXT:\n{clean_text}"
        )

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.0,
            )
            raw_response = resp.choices[0].message.content or "{}"
            llm_fields: Dict[str, Any] = _extract_json_from_text(raw_response)
        except Exception as exc:
            partial_fields["_hermes_mode"] = "error"
            partial_fields["_hermes_error"] = str(exc)
            return partial_fields

        # Merge: only fill fields whose current value is missing or empty.
        # Checking the *value* (not just key presence) is critical: pos_parser.py
        # may set  bank=None  when it finds the key but cannot extract a value;
        # that key would be silently skipped by a naive `if field in partial_fields`.
        for field in ESSENTIAL_FIELDS:
            if not _is_missing(field, partial_fields.get(field)):
                continue                                       # already have a meaningful value
            val = llm_fields.get(field)
            if val in (None, "", 0, 0.0):
                continue                                       # LLM couldn't find it either
            # Type coercion
            try:
                if field == "reserve_price_rm":
                    val = _parse_rm(val)
                elif field == "deposit_required_rm":
                    val = _parse_rm(val)
                elif field == "disbursement_days":
                    val = int(float(str(val)))
                elif field == "tenure":
                    val = str(val).lower().strip()
                    if val not in ("freehold", "leasehold"):
                        continue
                else:
                    val = str(val).strip()
                    if not val:
                        continue
            except (ValueError, TypeError):
                continue
            partial_fields[field] = val

        # Re-check completeness after enrichment
        is_now_complete, still_missing = check_pos_completeness(partial_fields)
        partial_fields["_extraction_complete"] = is_now_complete
        partial_fields["_missing_essential"]   = still_missing
        partial_fields["_hermes_mode"]         = "llm"
        return partial_fields
