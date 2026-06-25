"""Quick inspector — show PDF text from first few cached files."""
from pypdf import PdfReader
from pathlib import Path
import re

CACHE = Path(__file__).parent / "pos_study_cache"

def show(path, max_chars=3000):
    reader = PdfReader(str(path))
    text = ""
    for page in reader.pages:
        text += (page.extract_text() or "") + "\n"
    tl = text.lower()
    print(f"\n{'='*70}")
    print(f"FILE: {path.name}  ({len(text)} chars)")
    print(text[:max_chars])
    print()
    for term in ["bilik", "bedroom", "keluasan", "built", "floor", "luas", "petak", "lantai"]:
        hits = [(m.start(), text[max(0,m.start()-25):m.end()+35]) for m in re.finditer(term, tl)]
        if hits:
            print(f"  [{term}] — {len(hits)} hits")
            for _, snip in hits[:2]:
                print(f"    {repr(snip.strip())}")

pdfs = sorted(CACHE.glob("*.pdf"))
# Show a court-order one and a LACA one
for p in pdfs[:2]:
    show(p)
# Also show one from the scraped set (later ones)
for p in pdfs[35:37]:
    show(p)
