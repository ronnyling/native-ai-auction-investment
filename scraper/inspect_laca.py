"""Inspect LACA/strata POS documents."""
from pypdf import PdfReader
from pathlib import Path
import re

CACHE = Path(__file__).parent / "pos_study_cache"

def show(path, max_chars=4000):
    reader = PdfReader(str(path))
    text = ""
    for page in reader.pages:
        text += (page.extract_text() or "") + "\n"
    tl = text.lower()
    print(f"\n{'='*70}")
    print(f"FILE: {path.name}  ({len(text)} chars)")
    print(text[:max_chars])
    print()
    for term in ["bilik", "bedroom", "keluasan", "built", "floor", "luas", "petak", "lantai", "tingkat", "bangunan"]:
        hits = [(m.start(), text[max(0,m.start()-30):m.end()+40]) for m in re.finditer(term, tl)]
        if hits:
            print(f"  [{term}] — {len(hits)} hits")
            for _, snip in hits[:3]:
                print(f"    {repr(snip.strip())}")

pdfs = sorted(CACHE.glob("*.pdf"))

# Specifically look for LACA ones: property 250662
laca = [p for p in pdfs if "250662" in p.name]
for p in laca[:2]:
    show(p)

# Also look at 251289 (showed fields=7, signed_sealed)
laca2 = [p for p in pdfs if "251289" in p.name]
for p in laca2[:1]:
    show(p)

# And a strata one if possible — look for ones with large strata petak info
# Try some from the scraped set that showed 9-10 fields
strata_candidates = [p for p in pdfs if any(x in p.name for x in ["262896", "249833"])]
for p in strata_candidates[:1]:
    show(p)
