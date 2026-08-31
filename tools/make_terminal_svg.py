#!/usr/bin/env python3
"""Render a skill's real output as an SVG terminal card for the README.

A screenshot would be a binary blob that silently stops matching the tool the first time
the output changes. This runs the tool, captures what it actually printed, and draws that
— so `python tools/make_terminal_svg.py --check` in CI fails when the image and the code
disagree, exactly like the fixture check.

    python tools/make_terminal_svg.py
    python tools/make_terminal_svg.py --check
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "pii-scan.svg"

COMMAND = [sys.executable,
           str(ROOT / "skills" / "pii-scan" / "scripts" / "scan.py"),
           str(ROOT / "fixtures" / "pii-scan" / "ga4_pages_sample.csv")]
MAX_LINES = 26

BG, FG, DIM = "#11141a", "#d7dce3", "#7b8492"
COLOURS = {"critical": "#ff6b6b", "high": "#ffa94d", "medium": "#ffd43b",
           "!": "#ff8787", "?": "#868e96"}
CHAR_W, LINE_H, PAD = 7.6, 17.5, 20


def escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def colour_for(line: str) -> str:
    stripped = line.strip()
    for key, value in COLOURS.items():
        if stripped.startswith(key):
            return value
    if stripped.startswith(("severity", "---", "===")) or "└─" in line:
        return DIM
    return FG


def render(lines: list[str]) -> str:
    width = PAD * 2 + int(max((len(l) for l in lines), default=60) * CHAR_W)
    height = PAD * 2 + int(len(lines) * LINE_H) + 26
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="ui-monospace,SFMono-Regular,'
        f'Menlo,Consolas,monospace" font-size="12.5">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        # the three window dots, so it reads as a terminal at a glance
        f'<circle cx="{PAD}" cy="18" r="5" fill="#ff5f57"/>',
        f'<circle cx="{PAD + 18}" cy="18" r="5" fill="#febc2e"/>',
        f'<circle cx="{PAD + 36}" cy="18" r="5" fill="#28c840"/>',
    ]
    for i, line in enumerate(lines):
        y = PAD + 26 + i * LINE_H
        parts.append(f'<text x="{PAD}" y="{y}" fill="{colour_for(line)}" '
                     f'xml:space="preserve">{escape(line)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(COMMAND, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    lines = [l.rstrip() for l in proc.stdout.splitlines()][:MAX_LINES]
    if not lines:
        print("the command produced no output", file=sys.stderr)
        return 2
    lines.append("")
    lines.append("  ... full report continues with locations and remediation")
    svg = render(lines)

    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != svg:
            print(f"STALE {OUT.relative_to(ROOT)} — run python tools/make_terminal_svg.py",
                  file=sys.stderr)
            return 1
        print("docs/pii-scan.svg matches the tool's current output")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
