import re, sys
import yaml
from pathlib import Path

vault = Path('../vault/Properties')
files = list(vault.glob('bn-*.md'))
sys.stdout.write(f"Total files: {len(files)}\n")
sys.stdout.flush()

cities = {}
processed = 0
for f in files[:200]:
    txt = f.read_text(encoding='utf-8')
    m = re.match(r'^---\n(.*?)\n---', txt, re.DOTALL)
    if not m:
        continue
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        continue
    processed += 1
    bmv = float(fm.get('bmv_pct', 0) or 0)
    cnt = int(fm.get('auction_count', 1) or 1)
    if bmv >= 29 or cnt >= 3:
        city = str(fm.get('city', '') or '').strip()
        ptype = str(fm.get('property_type', '') or '').strip()
        if city:
            key = f"{city}|{ptype}"
            cities[key] = cities.get(key, 0) + 1

sys.stdout.write(f"Processed: {processed}, High-priority groups: {len(cities)}\n")
top = sorted(cities.items(), key=lambda x: -x[1])[:20]
for k, n in top:
    sys.stdout.write(f"  {k:50s} {n}\n")
sys.stdout.flush()
