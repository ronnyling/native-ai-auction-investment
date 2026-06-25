"""Inspect failing PDFs to diagnose parser bugs."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from pypdf import PdfReader

CACHE = Path(__file__).parent / "pos_study_cache"


def get_text(name):
    p = CACHE / name
    return "\n".join(pg.extract_text() or "" for pg in PdfReader(str(p)).pages)


# ── 1. KL strata - borrower missing (3-party LACA-English) ──────────────────
print("=" * 70)
print("262064  (3-party LACA-English: ASSIGNEE + BORROWER + ASSIGNOR)")
print("=" * 70)
t = get_text("262064_20260622_113028_72c69.pdf")
print(t[:1500])

# ── 2. KL strata - borrower missing (ASSIGNORS / CUSTOMERS) ─────────────────
print()
print("=" * 70)
print("263035  (ASSIGNORS / CUSTOMERS label)")
print("=" * 70)
t2 = get_text("263035_20260618_162728_ad9d9.pdf")
print(t2[:1500])

# ── 3. Johor strata - encumbrances missing ──────────────────────────────────
print()
print("=" * 70)
print("263907  (Johor strata - encumbrances missing)")
print("=" * 70)
t3 = get_text("263907_20260623_143054_b6760.pdf")
# show full doc structure (every line with content)
lines = t3.split("\n")
print(f"Total chars={len(t3)}, lines={len(lines)}")
for i, ln in enumerate(lines):
    if ln.strip():
        print(f"  L{i:3d}: {ln.strip()[:120]}")
