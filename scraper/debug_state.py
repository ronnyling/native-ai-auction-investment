"""Analyze state field mismatch pattern."""
import yaml, re, sys
from pathlib import Path
from collections import Counter

vault = Path(__file__).parent.parent / "vault" / "Properties"

# Pre-load all
cache = []
for f in sorted(vault.glob("bn-*.md")):
    text = f.read_text(encoding="utf-8")
    end = text.find("---", 3)
    if end == -1:
        continue
    fm = yaml.safe_load(text[3:end])
    if isinstance(fm, dict):
        cache.append((f.name, fm))

# Count postcode-prefixed states
postcode_state = []
clean_state = []
for name, fm in cache:
    state = str(fm.get("state", "")).strip()
    if re.match(r"^\d{5}\s", state):
        postcode_state.append((name, state, fm.get("address", ""), fm.get("postcode"), fm.get("city")))
    elif state:
        clean_state.append(state)

lines = []
lines.append(f"Total notes: {len(cache)}")
lines.append(f"Postcode-prefixed state: {len(postcode_state)}")
lines.append(f"Clean state: {len(clean_state)}")

# Show unique postcode-state patterns
patterns = Counter(s for _, s, _, _, _ in postcode_state)
lines.append(f"\nUnique postcode-state patterns (top 15):")
for pat, cnt in patterns.most_common(15):
    lines.append(f"  '{pat}': {cnt}")

# Sample
lines.append(f"\nSample mismatches:")
for name, state, addr, pc, city in postcode_state[:5]:
    lines.append(f"  {name}:")
    lines.append(f"    address: {addr[:80]}")
    lines.append(f"    state:   '{state}'")
    lines.append(f"    postcode: {pc}")
    lines.append(f"    city:    '{city}'")

# What state can we extract from the address?
lines.append(f"\n--- Can we extract state from address? ---")
STATE_MAP = {
    "kuala lumpur": "Kuala Lumpur", "selangor": "Selangor", "penang": "Penang",
    "johor": "Johor", "perak": "Perak", "kedah": "Kedah", "melaka": "Melaka",
    "negeri sembilan": "Negeri Sembilan", "pahang": "Pahang", "kelantan": "Kelantan",
    "terengganu": "Terengganu", "sabah": "Sabah", "sarawak": "Sarawak",
    "putrajaya": "Putrajaya", "perlis": "Perlis", "labuan": "Labuan",
}
fixable = 0
for name, state, addr, pc, city in postcode_state:
    addr_lower = addr.lower()
    for key, val in STATE_MAP.items():
        if key in addr_lower:
            fixable += 1
            break
lines.append(f"Fixable from address: {fixable}/{len(postcode_state)}")

out = "\n".join(lines)
print(out)
(Path(__file__).parent / "state_debug_output.txt").write_text(out, encoding="utf-8")
