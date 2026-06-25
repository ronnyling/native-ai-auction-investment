"""vault_scan.py — Quick data-quality scan of vault/Properties."""
import re
from pathlib import Path
from datetime import date

VAULT = Path(__file__).parent.parent / "vault" / "Properties"
today = str(date.today())

total = hasMV = hasSqft = pastDue = hasBoth = 0
best = []

for f in VAULT.glob("*.md"):
    total += 1
    c = f.read_text(encoding="utf-8", errors="ignore")
    mv_m  = re.search(r"market_value: ([0-9.]+)", c)
    sq_m  = re.search(r"built_up_sqft: ([0-9.]+)", c)
    ad_m  = re.search(r"auction_date: '([0-9-]+)'", c)
    mv    = float(mv_m.group(1)) if mv_m else 0.0
    sq    = float(sq_m.group(1)) if sq_m else 0.0
    ad    = ad_m.group(1) if ad_m else "9999-01-01"
    if mv > 0:   hasMV   += 1
    if sq > 0:   hasSqft += 1
    if ad < today: pastDue += 1
    if mv > 100_000 and sq > 500:
        hasBoth += 1
        state_m = re.search(r"state: (.+)", c)
        bmv_m   = re.search(r"bmv_pct: ([0-9]+)", c)
        rp_m    = re.search(r"reserve_price: ([0-9.]+)", c)
        state   = state_m.group(1).strip() if state_m else ""
        bmv     = int(bmv_m.group(1)) if bmv_m else 0
        rp      = float(rp_m.group(1)) if rp_m else 0
        if bmv > 20:
            best.append((bmv, f.name, mv, sq, rp, state))

best.sort(reverse=True)

print(f"\nVAULT DATA QUALITY")
print(f"  Total files  : {total}")
print(f"  Has MV > 0   : {hasMV:4d}  ({hasMV/total*100:5.1f}%)")
print(f"  Has sqft > 0 : {hasSqft:4d}  ({hasSqft/total*100:5.1f}%)")
print(f"  Has both     : {hasBoth:4d}  ({hasBoth/total*100:5.1f}%)")
print(f"  Past due     : {pastDue:4d}  ({pastDue/total*100:5.1f}%)")
print(f"\nTop 5 BMV% candidates (KL + mv>100k + sqft>500):")
for bmv, fn, mv, sq, rp, st in best[:5]:
    print(f"  {fn}  BMV={bmv}%  MV=RM{mv:,.0f}  RP=RM{rp:,.0f}  sqft={sq:.0f}  {st}")
