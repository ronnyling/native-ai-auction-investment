"""
Migration: Fix postcode-prefixed state values in vault property notes.
e.g. "56000 Kuala Lumpur" → "Kuala Lumpur"

Usage: python scraper/migrate_fix_state.py [--dry-run]
"""

import re
import sys
import yaml
from pathlib import Path

VAULT = Path(__file__).parent.parent / "vault" / "Properties"
DRY_RUN = "--dry-run" in sys.argv


def run():
    notes = sorted(VAULT.glob("bn-*.md"))
    fixed = 0
    skipped = 0
    errors = []

    for f in notes:
        text = f.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("---", 3)
        if end == -1:
            continue

        fm_text = text[3:end]
        try:
            fm = yaml.safe_load(fm_text)
        except Exception:
            errors.append(f.name)
            continue

        if not isinstance(fm, dict):
            continue

        state = str(fm.get("state", "")).strip()
        if not re.match(r"^\d{5}\s", state):
            skipped += 1
            continue

        # Strip leading postcode
        new_state = re.sub(r"^\d{5}\s*", "", state).strip()
        if not new_state:
            errors.append(f"{f.name}: state became empty after strip ('{state}')")
            continue

        # Replace in the raw text to preserve formatting
        # Match: state: '56000 Kuala Lumpur'  or  state: "56000 Kuala Lumpur"  or  state: 56000 Kuala Lumpur
        old_line = re.search(r"^state:\s+.*$", fm_text, re.MULTILINE)
        if old_line:
            old_str = old_line.group(0)
            # Preserve quoting style
            if old_str.startswith("state: '"):
                new_str = f"state: '{new_state}'"
            elif old_str.startswith('state: "'):
                new_str = f'state: "{new_state}"'
            else:
                new_str = f"state: {new_state}"

            new_text = text[:3 + old_line.start()] + new_str + text[3 + old_line.end():]

            if not DRY_RUN:
                f.write_text(new_text, encoding="utf-8")

            print(f"  {'[DRY] ' if DRY_RUN else ''}FIXED {f.name}: '{state}' → '{new_state}'")
            fixed += 1
        else:
            errors.append(f"{f.name}: could not find state line in frontmatter")

    print(f"\n{'='*50}")
    print(f"  Migration {'(DRY RUN) ' if DRY_RUN else ''}Complete")
    print(f"  Fixed:   {fixed}")
    print(f"  Skipped: {skipped} (already clean)")
    print(f"  Errors:  {len(errors)}")
    if errors:
        for e in errors[:10]:
            print(f"    {e}")
    print(f"{'='*50}")


if __name__ == "__main__":
    run()
