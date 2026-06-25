"""
pos_parser.py — Extract structured fields from Malaysian POS (Proclamation of Sale) PDF text.

Malaysian POS documents are bilingual (Malay / English). This module handles:
  - e-Lelong court-order format (court order, Malay language)
  - BidNow LACA bank-filed format (Malay, "Pemegang Serahhak/Pembiaya")
  - English LACA format ("Assignee/Bank", "Assignor/Borrower")

NOTE: In Malaysian auction law, "bank" and "plaintiff" refer to the same party —
the mortgagee/financier who filed the auction order. Both terms are captured under
the `bank` field (court POS says PLAINTIF; LACA says Assignee/Bank).

Corpus findings from 57 real POS documents:
  - 100% bilingual, 84% court_order, 9% laca
  - strata_parcel label exists in 100% but is empty for landed properties
  - built_up_sqft only found in strata POS (~5%); landed only has land_area
  - bedrooms/bathrooms: NOT present in POS (legal instrument, not property listing)
  - tenure: "Hakmilik Kekal"=freehold, "Hakmilik Pajakan"=leasehold
  - reserve price: always "harga rizab sebanyak RM X" (court) or "Reserve Price: RM X" (LACA)
  - bank (plaintiff): before "PLAINTIF" (court), "PEMEGANG SERAHHAK/PEMBIAYA" (Malay LACA),
                      "Assignee/Bank" (EN LACA)
  - borrower (defendant): "Pemilik Berdaftar" (court title block), before "DEFENDAN" (court),
                           before "PENYERAHHAK/PELANGGAN" (Malay LACA), before "Assignor/Borrower" (EN LACA)

Extractable fields (all optional — returns only what is found):
  bank                    str       mortgagee / plaintiff (same party, different label by format)
  borrower                str       registered owner / defendant
  reserve_price_rm        float     minimum bid price
  deposit_required_rm     float     deposit payable at auction (usually 10% of reserve)
  deposit_pct             int       deposit percentage (if stated as %)
  disbursement_days       int       days allowed to pay balance after auction
  encumbrances            str       charges / liens on title; "Tiada" = none
  location                str       full postal address of the property
  spa_date                str       date SPA between bank and borrower was signed
  auction_date            str       date of the auction
  auction_time            str       time of the auction
  auction_venue           str       venue / platform for the auction
  expenses_covered_by_bank str      costs borne by the bank/assignee
  expenses_not_covered    str       costs borne by the purchaser (stamp duty, legal fees, etc.)
  bedrooms                int       from property description (rare; POS usually omits)
  bathrooms               int       from property description (rare; POS usually omits)
  floor_no                int       strata only — "No. Tingkat"
  strata_parcel_no        str       strata only — "No. Petak"
  land_area_sqft          float     "Keluasan Tanah" in kaki persegi (landed)
  built_up_sqft           float     strata — "Keluasan Petak/Binaan/Lantai" or LACA floor area
  tenure                  str       "freehold" | "leasehold"
  lawyer_firm             str       "Firma Guaman"
  case_no                 str       court case reference e.g. "PA-38-143-01/2026"
  property_description    str       one-line description from POS
  district                str       from Mukim/Daerah/Negeri block
  mukim                   str

Completeness metadata (always present in return dict):
  _extraction_complete    bool      True when all ESSENTIAL_FIELDS are present
  _missing_essential      list[str] names of essential fields not yet extracted
"""

import re
from typing import Any, Dict, List, Optional

# ── Essential fields — Hermes is triggered when any of these are missing ──────

ESSENTIAL_FIELDS: List[str] = [
    "bank",               # mortgagee / plaintiff
    "borrower",           # registered owner / defendant
    "reserve_price_rm",   # minimum bid
    "deposit_required_rm",# upfront cash at auction
    "disbursement_days",  # days to pay balance
    "encumbrances",       # charges / liens on title
    "location",           # postal address
    "tenure",             # freehold | leasehold
]

# ── Month name constants for date patterns ────────────────────────────────────

_MALAY_MONTHS = (
    "Januari|Februari|Mac|April|Mei|Jun|Julai|Ogos|"
    "September|Oktober|November|Disember"
)
_EN_MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)

# ── Malay/English number words ────────────────────────────────────────────────

_WORD_TO_INT: Dict[str, int] = {
    # Malay
    "satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "lapan": 8, "sembilan": 9, "sepuluh": 10,
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _to_int(s: str) -> Optional[int]:
    """Convert a digit string or Malay/English word to int; None on failure."""
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    return _WORD_TO_INT.get(s)


def _sqft(value_str: str, unit_str: str) -> float:
    """Return sqft, converting from sqm if needed."""
    val = float(value_str.replace(",", ""))
    u = unit_str.lower()
    if any(x in u for x in ("meter", "sqm", "m.p", "sq.mt", "sq.m", "m2")):
        return round(val * 10.7639, 1)
    return val


def _clean_name(raw: str) -> str:
    """Strip IC/company number suffixes from a person or company name."""
    raw = re.sub(r"\s*\(No\.\s*(?:Kad|IC|K/P|Syarikat|Pendaftaran)[^)]*\)\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*\(No\.\s*K/P[^)]*\)\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*\((?:I/C|IC|NRIC|MyKad)\s*(?:No\.?)?\s*[^)]+\)\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*\([A-Z0-9/-]{6,}\)\s*", "", raw)   # bare registration numbers
    return raw.strip()


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_pos_fields(text: str) -> Dict[str, Any]:
    """
    Parse structured property fields from a POS PDF text string.

    Returns a dict containing only the fields that could be extracted (no None
    values — callers can use `.get("bedrooms")` safely). An empty dict means
    the text did not yield any extractable fields.
    """
    out: Dict[str, Any] = {}
    if not text:
        return out

    # ── Bedrooms ──────────────────────────────────────────────────────────────
    # NOTE: POS documents (court/LACA) rarely state bedroom counts.
    # These patterns fire only when the description paragraph explicitly lists rooms.
    m = re.search(r"(?:comprising|consisting of)\s+(\w+)\s+bedrooms?", text, re.I)
    if m:
        v = _to_int(m.group(1))
        if v:
            out["bedrooms"] = v
    if "bedrooms" not in out:
        m = re.search(r"(\w+)\s*(?:\(\d+\))?\s*bilik\s*tidur", text, re.I)
        if m:
            v = _to_int(m.group(1))
            if v:
                out["bedrooms"] = v
    if "bedrooms" not in out:
        m = re.search(r"\b(\d)\s*BR\b", text)
        if m:
            out["bedrooms"] = int(m.group(1))

    # ── Bathrooms ─────────────────────────────────────────────────────────────
    m = re.search(r"(\w+)\s*(?:\(\d+\))?\s*(?:bathroom|bilik\s*(?:mandi|air))", text, re.I)
    if m:
        v = _to_int(m.group(1))
        if v:
            out["bathrooms"] = v

    # ── Strata floor + parcel (court combined block) ──────────────────────────
    # Court format: "No. Petak/No. Tingkat/No. Bangunan : P-03-01 / 3 / TowerA"
    m = re.search(
        r"No\.\s*Petak\s*/\s*No\.\s*Tingkat\s*/\s*No\.\s*Bangunan\s*[:/]?\s*"
        r"([A-Z0-9][-A-Z0-9]*)\s*/\s*(\d+)\s*/\s*(\S*)",
        text, re.I,
    )
    if m:
        out["strata_parcel_no"] = m.group(1).strip()
        out["floor_no"] = int(m.group(2))
    else:
        # LACA comma-sep: "No. Petak 26, No. Tingkat 2, No. Bangunan M1"
        m = re.search(
            r"No\.\s*Petak\s+(\d+)[,\s]+No\.\s*Tingkat\s+(\w+)[,\s]+No\.\s*Bangunan\s+(\w+)",
            text, re.I,
        )
        if m:
            out["strata_parcel_no"] = m.group(1).strip()
            floor_raw = m.group(2).strip()
            if floor_raw.isdigit():
                out["floor_no"] = int(floor_raw)
        else:
            # Standalone "No. Tingkat : 15"
            m = re.search(r"No\.\s*Tingkat\s*[:/]\s*(\d+)", text, re.I)
            if m:
                out["floor_no"] = int(m.group(1))
            # Standalone strata parcel
            m = re.search(r"No\.\s*Petak\s*[:/]\s*([A-Z0-9][-A-Z0-9]{2,})", text, re.I)
            if m:
                out["strata_parcel_no"] = m.group(1).strip()

    # ── Land area sqft ────────────────────────────────────────────────────────
    # Court format: "Keluasan Tanah : 1292.0000 kaki persegi"
    # LACA Malay:   "KELUASAN TANAH : 1,754 m.p"
    if "land_area_sqft" not in out:
        m = re.search(
            r"Keluasan\s*Tanah\s*[:/]\s*([\d,]+(?:\.\d+)?)\s*(kaki\s*persegi|meter\s*persegi|m\.p|sqft|sqm)",
            text, re.I,
        )
        if m:
            out["land_area_sqft"] = _sqft(m.group(1), m.group(2))

    # LACA English: "LANDAREA/FLOOR AREA : 143 sq.mt (1539 sq.ft)"
    # When the field says 'FLOOR AREA' it is built-up (strata), NOT land area — skip for land_area
    # Only use pure 'LAND AREA :' (without FLOOR AREA) for land_area_sqft
    if "land_area_sqft" not in out:
        m = re.search(
            r"(?:LANDAREA|LAND\s*AREA)\s*[:/]\s*"
            r"(?!.*FLOOR\s*AREA)"
            r"([\ d,]+(?:\.\d+)?)\s*(sq\.mt|sq\.m|sqm|meter|m2)"
            r"(?:\s*\(([\d,]+(?:\.\d+)?)\s*sq\.ft\))?",
            text, re.I,
        )
        if m:
            if m.group(3):
                out["land_area_sqft"] = float(m.group(3).replace(",", ""))
            else:
                out["land_area_sqft"] = _sqft(m.group(1), m.group(2))

    # LACA English: "Area: Approximately 1432 square feet / 133 square metres"
    if "land_area_sqft" not in out:
        m = re.search(
            r"(?:Keluasan|Area)\s*[:/]?\s*(?:Lebih\s*kurang|Approximately)?\s*"
            r"([\d,]+(?:\.\d+)?)\s*(kaki\s*persegi|square\s*feet|sq\.ft)",
            text, re.I,
        )
        if m:
            out["land_area_sqft"] = float(m.group(1).replace(",", ""))

    # ── Built-up sqft (strata only) ───────────────────────────────────────────
    # Court strata: "Keluasan Petak : 850 kaki persegi"
    # LACA Malay:   "Anggaran Keluasan Lantai : 57 meter persegi"
    # LACA English: "LANDAREA/FLOOR AREA : 143 sq.mt (1539 sq.ft)"
    m = re.search(
        r"(?:Anggaran\s*)?Keluasan\s*(?:Petak|Binaan|Lantai)\s*[:/]?\s*"
        r"([\d,]+(?:\.\d+)?)\s*(kaki\s*persegi|meter\s*persegi|m\.p|sqft|sqm)",
        text, re.I,
    )
    if m:
        out["built_up_sqft"] = _sqft(m.group(1), m.group(2))

    if "built_up_sqft" not in out:
        # English LACA: "LANDAREA/FLOOR AREA : 143 sq.mt (1539 sq.ft)"
        m = re.search(
            r"(?:LANDAREA|LAND\s*AREA)\s*/?\s*FLOOR\s*AREA\s*[:/]\s*"
            r"([\d,]+(?:\.\d+)?)\s*(sq\.mt|sq\.m|sqm|meter|m2)"
            r"(?:\s*\(([\d,]+(?:\.\d+)?)\s*sq\.ft\))?",
            text, re.I,
        )
        if m:
            if m.group(3):
                out["built_up_sqft"] = float(m.group(3).replace(",", ""))
            else:
                out["built_up_sqft"] = _sqft(m.group(1), m.group(2))

    # ── Tenure ────────────────────────────────────────────────────────────────
    # Court Malay: "Pegangan : Hakmilik Kekal" / "Pegangan : Hakmilik Pajakan"
    # LACA English: "TENURE : Freehold" / "Tenure: Leasehold"
    # NOTE: bare "Pajakan" appears as legal boilerplate in ALL court docs; don't use it alone.
    peg = re.search(r"Pegangan\s*[:/]\s*(\w[\w\s]*)", text, re.I)
    ten = re.search(r"\bTENURE\s*[:/]\s*(\w+)", text, re.I)
    pegval = peg.group(1).strip().lower() if peg else ""
    tenval = ten.group(1).strip().lower() if ten else ""

    if "kekal" in pegval or "freehold" in pegval or tenval == "freehold":
        out["tenure"] = "freehold"
    elif "pajakan" in pegval or "leasehold" in pegval or tenval == "leasehold":
        out["tenure"] = "leasehold"

    # ── Bank (plaintiff / mortgagee) ──────────────────────────────────────────
    # Court: bank name may span multiple lines before ". . . PLAINTIF"
    # e.g. "AIA BHD. (dahulunya dikenali sebagai...\n...\n. . .  PLAINTIF"
    # e.g. "HONG LEONG ISLAMIC BANK BERHAD (No. Syarikat : 200501009144 (686191-\nW))\n . . .  PLAINTIF"
    m = re.search(
        r"([\w &()[\].,'-]+(?:Bank|Berhad|Bhd|Finance|Credit|Mortgage|Pembiayaan|Lembaga|Perbendaharaan|AIA|Takaful|Insurance|Assurance)[^\n]*)"
        r"(?:\n[^\n]*){0,4}\n\s*[.\s]*PLAINTIF",
        text, re.I,
    )
    if m:
        out["bank"] = m.group(1).strip()

    if "bank" not in out:
        # Malay LACA: entity before "PEMEGANG SERAHHAK" or "PIHAK PEMEGANG SERAHHAK"
        # Two-branch lookahead: stop before PIHAK when "PIHAK PEMEGANG" follows,
        # or before PEMEGANG when plain "PEMEGANG SERAHHAK" follows.
        # Uses ^ + MULTILINE + horizontal-whitespace-only to avoid cross-line matches.
        m = re.search(
            r"^([\w &().,'-]+(?:Bank|Berhad|Bhd|Finance|Credit|Mortgage|Pembiayaan|Lembaga|Perbendaharaan|Kredit|Tabung|Kerajaan|Insurance|Assurance|AIA|Takaful)[^\n]*?)(?=[ \t]+PIHAK[ \t]*PEMEGANG|[ \t]*PEMEGANG[ \t]*SERAHHAK)",
            text, re.I | re.MULTILINE,
        )
        if m:
            out["bank"] = m.group(1).strip()

    if "bank" not in out:
        # English LACA: "CIMB Bank Berhad (197201001799) .......  Assignee/Bank"
        # or:           "ALLIANCE BANK MALAYSIA BERHAD (88103-W) àASSIGNEE/BANK"
        # Iterate all occurrences — boilerplate uses "Assignee/Bank" too, so we need the
        # one whose line contains a bank-like keyword.
        for m in re.finditer(r"^([^\n]+?)(?:Assignee|ASSIGNEE)\s*/\s*(?:Bank|BANK)", text, re.I | re.MULTILINE):
            line_before = m.group(1)
            # Strip trailing fill chars: rstrip spaces first, then strip non-ASCII-word trailing chars
            # (handles both ASCII dots and Unicode arrows like \u00e0 which is \w in Python 3)
            stripped = re.sub(r"[^A-Za-z0-9()]+$", "", line_before.rstrip()).strip()
            candidate = _clean_name(stripped)
            if candidate and re.search(r"Bank|Berhad|Bhd|Finance|Credit|Mortgage|Pembiayaan|Lembaga|Tabung", candidate, re.I):
                out["bank"] = candidate
                break

    # ── Borrower (defendant / registered owner) ───────────────────────────────
    # Priority 1: "Pemilik Berdaftar" in court title block
    m = re.search(r"Pemilik\s*Berdaftar\s*[:/]?\s*(.+?)(?:\n|Syarat|$)", text, re.I)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"\s*\(Si\s*(?:Bankrap|Mati)[^\n]*", "", raw, flags=re.I).strip()
        name = _clean_name(raw.split("\n")[0])
        if name:
            out["borrower"] = name

    if "borrower" not in out:
        # Court: "NAME (No. Kad ...)\n. . . DEFENDAN"
        m = re.search(
            r"([^\n]+(?:\(No\.\s*(?:Kad|K/P|IC)|No\.\s*K/P)[^\n]*)\s*\n[.\s]*DEFENDAN",
            text, re.I,
        )
        if m:
            name = _clean_name(m.group(1))
            if name:
                out["borrower"] = name

    if "borrower" not in out:
        # Malay LACA: "1) NAME (NO. K/P ...) PIHAK-PIHAK PENYERAH HAK/ PELANGGAN"
        # Note: text has 'PENYERAH HAK' (with space) not 'PENYERAHHAK'
        m = re.search(
            r"\d[).]\s+([A-Z][A-Z\s'/-]{5,60})\s*(?:\([^)]{5,40}\))?\s+PIHAK-PIHAK PENYERAH",
            text, re.I,
        )
        if not m:
            # Fallback: any line before PENYERAHHAK / PENYERAH HAK / PELANGGAN
            m = re.search(
                r"([^\n]{5,80})\s*\n?\s*(?:PIHAK-PIHAK\s*)?PENYERAH\s*(?:HAK\s*)?/?\s*PELANGGAN",
                text, re.I,
            )
        if m:
            name = _clean_name(m.group(1))
            if name:
                out["borrower"] = name

    if "borrower" not in out:
        # English LACA: "Osman Bin Mohamed (NRIC ...) .............. Assignor(s)/Borrower(s)"
        # Use MULTILINE to match same-line name + dot fill + Assignor or Customer
        # Include '/' in name chars to handle A/L, A/P prefixes.
        m = re.search(
            r"^([ \t]*[\w][\w \t'/-]{4,60}?)[ \t]*(?:\([^)]+\))?[ \t]*[.…]{3,}[.\t ]*(?:Assignor|Customer)",
            text, re.I | re.MULTILINE,
        )
        if m:
            name = _clean_name(m.group(1).strip())
            if name:
                out["borrower"] = name
        else:
            # Fallback: "Name (IC) àASSIGNOR(S)/BORROWER(S)" (spaces/arrows, optional plural S)
            m = re.search(
                r"^([^\n]+?)(?:Assignors?|ASSIGNORS?)(?:\(S\))?\s*/\s*(?:Borrowers?|BORROWERS?)(?:\(S\))?",
                text, re.I | re.MULTILINE
            )
            if m:
                line_before = m.group(1)
                stripped = re.sub(r"[^A-Za-z0-9()]+$", "", line_before.rstrip()).strip()
                name = _clean_name(stripped)
                # Reject if it looks like boilerplate
                if name and len(name) > 5 and not re.search(r"\b(?:the|of|in|and|shall|with)\b", name, re.I):
                    out["borrower"] = name

    if "borrower" not in out:
        # English LACA variant: name on its own line, label "…………Assignors/Customers" on the NEXT line
        # e.g. 264579: "YAHAYA BIN MAT (NRIC)\n               …………Assignor/Customer"
        # e.g. 264577: "MUHAMAD AL ARIF (NRIC)\nNADIA SAFIRAH (NRIC)\n   …………Assignors/Customers"
        m = re.search(
            r"^([ \t]*[A-Z][\w \t'/-]{4,60}?)[ \t]*(?:\([^)]+\))?[ \t]*$\n(?:[^\n]*\n)?[ \t]*[\.…]{3,}[. \t]*(?:Assignors?|Customers?)",
            text, re.MULTILINE,
        )
        if m:
            name = _clean_name(m.group(1).strip())
            if name:
                out["borrower"] = name

    if "borrower" not in out:
        # English LACA variant: "NAME (ID) BORROWER/CUSTOMER/ASSIGNOR(S)" — label at end of line
        # e.g. 262064: "SYED AHMAD BIN OMAR ALSAGOFF (PASSPORT NO. S8223886G) BORROWER"
        # e.g. 262618: "FARIZAH BINTE BORHAN (NRIC NO. S8411201A) CUSTOMER"
        # e.g. 262314: "(2) TAN SIM HONG (NRIC NO. 641211-06-5411)  CUSTOMER(S)"
        # e.g. 263035: "GURDEV SINGH A/L BALWANT SINGH (NRIC)   ASSIGNORS / CUSTOMERS"
        # e.g. 263046: "CRISTY RAJ A/L SELVARAJA (NRIC NO. 960407-08-6239) ASSIGNOR"
        # e.g. 263769: "2) WAN MOHAMAD NOR ARIFF ... CUSTOMER(S)" — N) prefix (no opening paren)
        # Name must end with alphanumeric to prevent "ASSIGNORS /" from being captured as name
        m = re.search(
            r"^(?:\(?\d+\)?[ \t]+)?([ \t]*[A-Z][\w \t'/-]{4,60}?[A-Za-z0-9])[ \t]*(?:\([^)]+\))?[ \t]+"
            r"(?:ASSIGNORS?\s*/\s*(?:BORROWERS?|CUSTOMERS?)|BORROWERS?|CUSTOMERS?(?:\([Ss]\))?|ASSIGNORS?)\s*$",
            text, re.MULTILINE,
        )
        if m:
            name = _clean_name(m.group(1).strip())
            # Reject if name is itself a label keyword (prevents false ASSIGNORS match)
            if name and not re.fullmatch(r"(?:ASSIGNORS?|BORROWERS?|CUSTOMERS?)", name, re.I):
                out["borrower"] = name

    if "borrower" not in out:
        # English LACA variant: "(N) NAME (NRIC)\n(N) NAME2 (NRIC)\nASSIGNORS / BORROWERS"
        # The label is on its own standalone line below numbered-name lines
        # e.g. 262577: "(1) LIM SUNG MING (NRIC)\n(2) TAN MAY LIAN (NRIC)\nASSIGNORS / BORROWERS"
        m = re.search(
            r"^\(?\d+\)?\s+([ \t]*[A-Z][\w \t'/-]{4,60}?)[ \t]*(?:\([^)]+\))?[ \t]*$\n"
            r"(?:[^\n]*\n)?[ \t]*ASSIGNORS?\s*/\s*(?:BORROWERS?|CUSTOMERS?)\s*$",
            text, re.MULTILINE,
        )
        if m:
            name = _clean_name(m.group(1).strip())
            if name:
                out["borrower"] = name

    # ── Law firm ─────────────────────────────────────────────────────────────
    m = re.search(r"Firma\s*Guaman\s*[:/]?\s*(.+?)(?:\n|Alamat|$)", text, re.I)
    if m:
        out["lawyer_firm"] = m.group(1).strip()
    if "lawyer_firm" not in out:
        m = re.search(r"Peguam\s*Cara\s*(?:Plaintif|Pihak)?[:/]?\s*(.+?)(?:\n|Alamat|$)", text, re.I)
        if m:
            out["lawyer_firm"] = m.group(1).strip()

    # ── Court case number ─────────────────────────────────────────────────────
    # e.g. "PA-38-143-01/2026" — only in court-order POS, not LACA
    m = re.search(r"\b([A-Z]{1,5}-\d{2,3}-\d+-\d+/\d{4})\b", text)
    if m:
        out["case_no"] = m.group(1)

    # ── Reserve price ─────────────────────────────────────────────────────────
    # Court Malay: "harga rizab sebanyak RM 470,000.00" or "Harga Rizab : RM 470,000"
    m = re.search(r"harga\s*rizab\s*[:/]?\s*(?:sebanyak\s+)?RM\s*([\d,]+(?:\.\d{2})?)", text, re.I)
    if m:
        out["reserve_price_rm"] = float(m.group(1).replace(",", ""))

    if "reserve_price_rm" not in out:
        # English LACA: "Reserve Price: RM460,000.00" or "reserve price of RM 470,000.00"
        m = re.search(
            r"[Rr]eserve\s*[Pp]rice\s*[:/]?\s*(?:of\s+)?RM\s*([\d,]+(?:\.\d{2})?)",
            text, re.I,
        )
        if m:
            out["reserve_price_rm"] = float(m.group(1).replace(",", ""))

    # ── Property description ──────────────────────────────────────────────────
    # Court Malay: "Hartanah tersebut adalah <desc> yang beralamat..."
    m = re.search(
        r"Hartanah\s*tersebut\s*adalah\s+(.+?)(?=yang\s+(?:beralamat|terletak)|\n)",
        text, re.I,
    )
    if m:
        out["property_description"] = m.group(1).strip()

    if "property_description" not in out:
        # English LACA: "The subject property is ..."
        m = re.search(
            r"[Tt]he\s+subject\s+property\s+is\s+(?:an?\s+)?(.+?)(?=(?:[,.]?\s*bearing\s+postal)|(?:\n))",
            text, re.I,
        )
        if m:
            out["property_description"] = m.group(1).strip()

    if "property_description" not in out:
        m = re.search(
            r"[Tt]he\s+said\s+property\s+is\s+(.+?)(?=(?:situated|located)|\n)",
            text, re.I,
        )
        if m:
            out["property_description"] = m.group(1).strip()

    # ── Mukim / District ─────────────────────────────────────────────────────
    # Court Malay: "Mukim / Daerah / Negeri : MUKIM 06 / DAERAH ... / Pulau Pinang"
    m = re.search(
        r"Mukim\s*/\s*Daerah\s*/\s*Negeri\s*[:/]?\s*([^/\n]+)\s*/\s*([^/\n]+)\s*/\s*([^\n]+)",
        text, re.I,
    )
    if m:
        out["mukim"]    = m.group(1).strip()
        out["district"] = m.group(2).strip()

    if "district" not in out:
        # English LACA uppercase: "MUKIM : 6  DISTRICT : Seberang Perai Utara"
        m = re.search(r"\bDISTRICT\s*[:/]\s*([^\n,]+)", text, re.I)
        if m:
            out["district"] = m.group(1).strip()
        m2 = re.search(r"\bMUKIM\s*[:/]\s*([^\n,]+)", text, re.I)
        if m2:
            raw_mukim = m2.group(1).strip()
            # Avoid capturing "Mukim / Daerah" already handled above
            if "/" not in raw_mukim:
                out.setdefault("mukim", raw_mukim)

    # ── SPA date ──────────────────────────────────────────────────────────────
    # Court Malay: "Perjanjian Jual Beli bertarikh 01.01.2020"
    # LACA English: "Sale and Purchase Agreement dated 1 January 2020"
    _date_pat = (
        rf"(\d{{1,2}}\s+(?:{_MALAY_MONTHS}|{_EN_MONTHS})\s+\d{{4}}"
        r"|\d{1,2}[/.-]\d{1,2}[/.-]\d{4})"
    )
    m = re.search(
        rf"(?:Perjanjian\s*(?:Jual\s*Beli\s*)?bertarikh|"
        rf"(?:Sale\s+and\s+Purchase\s+Agreement|SPA)\s+dated)\s+{_date_pat}",
        text, re.I,
    )
    if m:
        out["spa_date"] = (m.group(1) or m.group(2) or "").strip()

    # ── Encumbrances ──────────────────────────────────────────────────────────
    # Court Malay: "Bebanan : Tiada" or "Bebanan : Lain-Lain : DIGADAIKAN ..."
    # LACA English: "ENCUMBRANCES : NIL" or section listing charges
    # Stop before Kawasan Rizab / Kaveat / LOKASI to prevent spillover
    _ENCUMB_STOP = r"(?:\n|Syarat|Kawasan\s+Rizab|Kaveat|LOKASI\s+DAN|Harga\s+Rizab|HARGA\s+RIZAB|$)"
    m = re.search(r"Bebanan\s*[:/]\s*(.+?)" + _ENCUMB_STOP, text, re.I)
    if m:
        out["encumbrances"] = m.group(1).strip()
    if "encumbrances" not in out:
        m = re.search(r"ENCUMBRANCE[S]?\s*[:/]\s*(.+?)(?:\n|$)", text, re.I)
        if m:
            out["encumbrances"] = m.group(1).strip()

    # ── Deposit required ──────────────────────────────────────────────────────
    # Court Malay: "Wang Pendahuluan/Deposit sebanyak RM X" or "RM X (10% daripada harga rizab)"
    # LACA English: "Deposit: RM X" or computed from "10% of the Reserve Price"
    m = re.search(
        r"(?:[Ww]ang\s+[Pp]endahuluan|[Dd]eposit)\s*(?:[/\\]\s*\w+\s*)?[:/]?\s*"
        r"(?:sebanyak\s+)?RM\s*([\d,]+(?:\.\d{1,2})?)",
        text, re.I,
    )
    if m:
        out["deposit_required_rm"] = float(m.group(1).replace(",", ""))
    if "deposit_required_rm" not in out:
        # Explicit RM amount after "Deposit:" label
        m = re.search(r"[Dd]eposit\s*[:/]\s*RM\s*([\d,]+(?:\.\d{1,2})?)", text, re.I)
        if m:
            out["deposit_required_rm"] = float(m.group(1).replace(",", ""))
    if "deposit_required_rm" not in out:
        # Derive from stated percentage: "10% of Reserve Price" or "10% daripada Harga Rizab"
        m = re.search(
            r"(\d+)\s*%\s*(?:of\s+(?:the\s+)?[Rr]eserve\s+[Pp]rice|"
            r"daripada\s+[Hh]arga\s+[Rr]izab)",
            text, re.I,
        )
        if m and "reserve_price_rm" in out:
            pct = int(m.group(1))
            out["deposit_required_rm"] = round(out["reserve_price_rm"] * pct / 100, 2)
            out["deposit_pct"] = pct

    # ── Disbursement days (days allowed to pay the balance) ───────────────────
    # Court Malay: "dalam tempoh SEMBILAN PULUH (90) hari bekerja"
    # LACA English: "shall be paid within ninety (90) days"
    # Strategy: look for digits in parentheses near hari/days in balance-payment sentence.
    m = re.search(
        r"(?:baki[^.]*?|balance[^.]*?)"
        r"(?:hendaklah\s+dibayar|to\s+be\s+paid|shall\s+be\s+paid)[^.]*?"
        r"(?:dalam\s+tempoh|within)\s+"
        r"(?:(?:\w+\s+){0,4})\(?\s*(\d+)\s*\)?\s*(?:hari|days?)",
        text, re.I | re.DOTALL,
    )
    if m:
        out["disbursement_days"] = int(m.group(1))
    if "disbursement_days" not in out:
        # Broader fallback: any standalone "within X days from" or "dalam tempoh X hari"
        m = re.search(
            r"(?:within\s+(?:\w+\s+)?\(??(\d+)\)??\s+(?:business\s+)?days?\s+from"
            r"|dalam\s+tempoh\s+(?:\w+\s+){0,4}\(?(\d+)\)?\s+hari)",
            text, re.I,
        )
        if m:
            val = int(m.group(1) or m.group(2))
            if val >= 30:   # reject admin deadlines (3 days, 7 days etc.)
                out["disbursement_days"] = val
    # Sanity-check: disbursement must be between 30 and 365 days
    if out.get("disbursement_days") is not None:
        if not (30 <= out["disbursement_days"] <= 365):
            del out["disbursement_days"]

    # ── Location / postal address ─────────────────────────────────────────────
    # Court Malay: "beralamat pos di No. X, Jalan Y, ..."
    # LACA English: "bearing the postal address of No. X, ..." / "known as No. X, ..."
    m = re.search(
        r"(?:beralamat\s+(?:pos\s+)?(?:di|pada)\s+)(No\.?\s*[\w/-]+[^\n]{10,100})",
        text, re.I,
    )
    if m:
        out["location"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".,")
    if "location" not in out:
        m = re.search(
            r"(?:bearing\s+the\s+postal\s+address\s+of|"
            r"known\s+as|situated\s+at|located\s+at)\s+"
            r"(No\.?\s*[\w/-]+[^\n]{10,100})",
            text, re.I,
        )
        if m:
            out["location"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(".,")
    if "location" not in out:
        # Fallback: any line that looks like a postal address (has postcode + "Jalan"/"Taman")
        m = re.search(
            r"((?:No\.?\s*[\d\w/-]+,?\s+)?(?:Jalan|Taman|Lorong|Persiaran|Lebuh)[^\n,]{5,60}"
            r"[^\n]*\b\d{5}\b[^\n]*)",
            text, re.I,
        )
        if m:
            out["location"] = re.sub(r"\s+", " ", m.group(1)).strip()

    # ── Auction date ──────────────────────────────────────────────────────────
    # Court Malay: "pada hari Isnin, 15 Jun 2026" or "tarikh lelongan: 15/06/2026"
    # LACA English: "on Monday, 15 June 2026 at 10.00 am"
    m = re.search(
        rf"(?:pada\s+hari\s+\w+[,\s]+|on\s+(?:\w+,\s+)?|"
        rf"(?:auction|lelongan)\s+(?:on\s+|pada\s+|tarikh\s*[:/]\s*))"
        rf"(?:{_date_pat})",
        text, re.I | re.MULTILINE,
    )
    if m:
        out["auction_date"] = (m.group(1) or m.group(2) or "").strip()

    # ── Auction time ──────────────────────────────────────────────────────────
    m = re.search(
        r"(?:pukul|at)\s+(\d{1,2}[:.]\d{2}\s*(?:pagi|tengahari|petang|malam|am|pm)?)",
        text, re.I,
    )
    if m:
        out["auction_time"] = m.group(1).strip()

    # ── Auction venue ─────────────────────────────────────────────────────────
    m = re.search(
        r"(?:di\s+|at\s+(?:the\s+)?)"
        r"((?:Mahkamah|Bangunan|Kompleks|Wisma|Court|e-lelong|BidNow|"
        r"bilik\s+lelongan|Aras|Level)[^\n,]{4,80})",
        text, re.I,
    )
    if m:
        out["auction_venue"] = re.sub(r"\s+", " ", m.group(1)).strip()

    # ── Expenses covered by bank (Assignee/Bank bears these costs) ────────────
    # LACA English: "The Assignee/Bank shall bear / pay ..."
    # LACA Malay: "Pemegang Serahhak/Pembiaya akan menanggung..."
    m = re.search(
        r"(?:[Tt]he\s+Assignee[/\\]Bank|Pemegang\s+Serahhak[/\\]Pembiaya)\s*"
        r"(?:shall\s+(?:be\s+responsible\s+for\s+)?(?:bear|pay)|akan\s+menanggung)\s*"
        r"(.+?)(?:\n\n|[Tt]he\s+[Pp]urchaser|CONDITION|\Z)",
        text, re.I | re.DOTALL,
    )
    if m:
        snippet = re.sub(r"\s+", " ", m.group(1).strip())[:300]
        if len(snippet) > 10:
            out["expenses_covered_by_bank"] = snippet

    # ── Expenses not covered (Purchaser must pay these) ───────────────────────
    # LACA English: "The Purchaser shall bear / pay [stamp duty, legal fees, ...]"
    m = re.search(
        r"[Tt]he\s+[Pp]urchaser\s+shall\s+(?:bear|pay|be\s+responsible\s+for)\s*"
        r"(.+?)(?:\n\n|\Z)",
        text, re.I | re.DOTALL,
    )
    if m:
        snippet = re.sub(r"\s+", " ", m.group(1).strip())[:300]
        if len(snippet) > 10:
            out["expenses_not_covered"] = snippet

    # ── Completeness check ────────────────────────────────────────────────────
    # Callers and Hermes use these metadata keys to decide whether LLM fallback
    # is needed. Leading underscore marks them as metadata, not content.
    _missing = [f for f in ESSENTIAL_FIELDS if not out.get(f)]
    out["_extraction_complete"] = len(_missing) == 0
    out["_missing_essential"]   = _missing

    return out
