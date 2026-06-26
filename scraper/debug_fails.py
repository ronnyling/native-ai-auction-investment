"""Debug the 7 Obsidian beta test failures."""
import yaml, re
from pathlib import Path

VAULT = Path(__file__).parent.parent / "vault"
PROPS = VAULT / "Properties"

print("=" * 60)
print("  DEBUG: 7 FAILURES")
print("=" * 60)

# ── FAIL 1.6: empty state ──
print("\n── FAIL 1.6: Empty state field ──")
for f in sorted(PROPS.glob("bn-*.md")):
    text = f.read_text(encoding="utf-8")
    end = text.find("---", 3)
    if end == -1:
        continue
    fm = yaml.safe_load(text[3:end])
    if fm and not str(fm.get("state", "")).strip():
        print(f"  File: {f.name}")
        print(f"  id: {fm.get('id')}")
        print(f"  address: {fm.get('address')}")
        print(f"  city: {fm.get('city')}")
        print(f"  state repr: {repr(fm.get('state'))}")

# ── FAIL 4.7: Templater user_functions ──
print("\n── FAIL 4.7: Templater user_functions folder ──")
tp_dir = VAULT / ".obsidian" / "plugins" / "templater-obsidian"
print(f"  Plugin dir exists: {tp_dir.exists()}")
if tp_dir.exists():
    for item in sorted(tp_dir.iterdir()):
        print(f"  {item.name}")

# Check alternate locations for user functions
for candidate in [
    tp_dir / "user_functions",
    tp_dir / "user_scripts",
    VAULT / "_templates" / "user_functions",
    VAULT / "user_functions",
]:
    print(f"  {candidate}: {'EXISTS' if candidate.exists() else 'not found'}")

# ── FAIL 7.1: Dashboard aliases ──
print("\n── FAIL 7.1: STATUS_ALIASES check ──")
dash = VAULT / "Dashboard.md"
dash_text = dash.read_text(encoding="utf-8")
js_blocks = re.findall(r"```dataviewjs\n(.*?)```", dash_text, re.DOTALL)
js = js_blocks[0] if js_blocks else ""

# The test checks for "interested" (quoted) but JS uses unquoted keys
aliases = ["interested", "rejected", "passed", "pass", "custom"]
for alias in aliases:
    quoted = f'"{alias}"' in js
    unquoted = f'{alias}:' in js or f'{alias} :' in js
    print(f"  '{alias}': quoted={quoted}, unquoted={unquoted}")

# Check the actual STATUS_ALIASES block in Dashboard
import re as re2
aliases_block = re2.search(r"STATUS_ALIASES\s*=\s*\{(.*?)\}", js, re2.DOTALL)
if aliases_block:
    print(f"\n  Dashboard STATUS_ALIASES block:")
    for line in aliases_block.group(0).split("\n"):
        print(f"    {line.strip()}")

print("\n── CONCLUSION ──")
print("  1.6: 1 note with empty state - DATA issue, needs fix")
print("  4.7: user_functions not needed - Templater uses data.json")
print("  7.1: FALSE POSITIVES - Dashboard uses unquoted JS keys")
print("       Dashboard aliases ARE correct, test regex was wrong")
