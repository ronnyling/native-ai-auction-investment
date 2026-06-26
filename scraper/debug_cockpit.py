"""Verify Cockpit bridge configuration."""
import json
from pathlib import Path

VAULT = Path(__file__).parent.parent / "vault"

tc = VAULT / ".obsidian" / "plugins" / "templater-obsidian" / "data.json"
config = json.loads(tc.read_text(encoding="utf-8"))

print("=== TEMPLATER CONFIG ===")
print(f"  data_version: {config.get('data_version')}")
print(f"  templates_folder: {config.get('templates_folder')}")
print(f"  startup_templates: {config.get('startup_templates')}")
print(f"  command_timeout: {config.get('command_timeout')}")
print(f"  templates_pairs:")
for name, cmd in config.get("templates_pairs", []):
    print(f"    {name} -> {cmd}")

st = VAULT / "_templates" / "_startup" / "cockpit-bootstrap.md"
st_text = st.read_text(encoding="utf-8")
print(f"\n=== STARTUP TEMPLATE ===")
print(f"  Content: {st_text.strip()}")

ps1 = Path(__file__).parent / "obsidian-cockpit.ps1"
print(f"\n=== COCKPIT PS1 ===")
print(f"  Exists: {ps1.exists()}")
ps1_text = ps1.read_text(encoding="utf-8")
for line in ps1_text.strip().split("\n"):
    print(f"  {line}")

main = Path(__file__).parent / "main.py"
print(f"\n=== MAIN.PY ===")
print(f"  Exists: {main.exists()}")

# Verify path resolution
vault_parent = VAULT.parent
ps1_from_vault = vault_parent / "scraper" / "obsidian-cockpit.ps1"
print(f"\n=== PATH RESOLUTION ===")
print(f"  Vault: {VAULT}")
print(f"  Vault parent: {vault_parent}")
print(f"  PS1 via ../scraper/: {ps1_from_vault}")
print(f"  PS1 via ../scraper/ exists: {ps1_from_vault.exists()}")
