#!/usr/bin/env python3
"""Keep the Codex and Claude distribution surfaces installable and in sync."""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILLS = {
    "martech-audit": ("Marketing Data Audit", "Choose and run the right verification checks"),
    "pii-scan": ("PII Leakage Scanner", "Find personal data leaking into analytics"),
    "utm-lint": ("UTM Hygiene Check", "Find broken campaign tags in real URLs"),
    "conversion-reconcile": (
        "Conversion Gap Investigator",
        "Explain platform-to-CRM conversion gaps",
    ),
    "routing-simulate": ("Lead Routing Auditor", "Simulate rules against real lead exports"),
}
SPECIALIST_SCRIPTS = {
    "pii-scan": "scan.py",
    "utm-lint": "lint.py",
    "conversion-reconcile": "reconcile.py",
    "routing-simulate": "simulate.py",
}
VERSION = "0.2.0"


def read_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def yaml_value(text: str, key: str) -> str:
    match = re.search(rf'^\s*{re.escape(key)}:\s*"([^"]*)"\s*$', text, re.MULTILINE)
    return match.group(1) if match else ""


def main() -> int:
    checks: list[tuple[str, bool]] = []

    codex = read_json(".codex-plugin/plugin.json")
    claude = read_json(".claude-plugin/plugin.json")
    marketplace = read_json(".claude-plugin/marketplace.json")
    listing = marketplace.get("plugins", [{}])[0]

    checks.extend([
        ("Codex manifest names the bundle", codex.get("name") == "martech-verify"),
        ("Claude manifest names the bundle", claude.get("name") == "martech-verify"),
        ("plugin versions stay in sync",
         {codex.get("version"), claude.get("version"), listing.get("version")} == {VERSION}),
        ("Codex exposes the skills directory", codex.get("skills") == "./skills/"),
        ("Claude marketplace installs this repository", listing.get("source") == "."),
        ("Claude marketplace entry names the plugin", listing.get("name") == "martech-verify"),
    ])

    for name, (display_name, short_description) in SKILLS.items():
        folder = ROOT / "skills" / name
        skill_text = (folder / "SKILL.md").read_text(encoding="utf-8")
        metadata_text = (folder / "agents" / "openai.yaml").read_text(encoding="utf-8")
        checks.extend([
            (f"{name} has matching frontmatter", f"name: {name}" in skill_text),
            (f"{name} has the expected display name",
             yaml_value(metadata_text, "display_name") == display_name),
            (f"{name} has a concise description",
             yaml_value(metadata_text, "short_description") == short_description
             and 25 <= len(short_description) <= 64),
            (f"{name} default prompt explicitly invokes the skill",
             f"${name}" in yaml_value(metadata_text, "default_prompt")),
            (f"{name} metadata contains no placeholders", "TODO" not in metadata_text),
        ])

    for name, script in SPECIALIST_SCRIPTS.items():
        folder = ROOT / "skills" / name
        checks.extend([
            (f"{name} keeps its executable", (folder / "scripts" / script).is_file()),
            (f"{name} explains its required export", (folder / "references" / "input-guide.md").is_file()),
        ])

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checks.extend([
        ("README presents the umbrella skill", "$martech-audit" in readme),
        ("README documents the Claude marketplace install",
         "claude plugin marketplace add m7mdwb/martech-verify" in readme),
    ])

    failed = [label for label, ok in checks if not ok]
    for label, ok in checks:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    print("-" * 78)
    print(f"{len(checks) - len(failed)}/{len(checks)} passed"
          if not failed else f"{len(failed)} FAILED of {len(checks)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
