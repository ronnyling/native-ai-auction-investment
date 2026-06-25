"""Validate enhanced pos_parser.py against real corpus PDFs."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from pos_parser import parse_pos_fields
from pypdf import PdfReader
from pathlib import Path

CACHE = Path(__file__).parent / "pos_study_cache"

def extract(path):
    reader = PdfReader(str(path))
    text = ""
    for page in reader.pages:
        text += (page.extract_text() or "") + "\n"
    return text

def show(path):
    text = extract(path)
    fields = parse_pos_fields(text)
    print(f"\n=== {path.name} ===")
    for k, v in sorted(fields.items()):
        print(f"  {k:25s}: {v}")
    if not fields:
        print("  (no fields extracted)")

pdfs = sorted(CACHE.glob("*.pdf"))

# Sample: 2 court-order Malay (landed)
for p in pdfs[6:8]:
    show(p)

# Sample: LACA Malay
laca_my = [p for p in pdfs if "250662" in p.name]
for p in laca_my[:1]:
    show(p)

# Sample: English LACA (bank assigns)
en_laca = [p for p in pdfs if "251289" in p.name or "249833" in p.name]
for p in en_laca[:2]:
    show(p)

# Sample from scraped set
for p in pdfs[35:38]:
    show(p)
