# ⚠️ VENDORED COPY — do not edit. Edit lib/_shared.py and run python tools/sync_shared.py
"""Shared helpers for every skill in this repo.

⚠️ THIS FILE IS THE SOURCE OF TRUTH AND IS COPIED INTO EACH SKILL.

Skills have to work when someone drops a single folder into `.claude/skills/`, so no skill
may import from a path outside itself. The alternative to copying is either a package
install (which breaks "no dependencies") or a relative import up the tree (which breaks the
moment a folder is copied). So `tools/sync_shared.py` vendors this file into every skill's
`scripts/` directory, and `tests/test_shared_sync.py` fails if any copy has drifted.

Edit here, run `python tools/sync_shared.py`, commit the copies.
"""
from __future__ import annotations

import csv
import json

SEVERITY_ORDER = ["critical", "high", "medium"]

# Column names that carry a URL, in the exports people actually have. Ordered: exact
# matches are tried before substring matches, so "page_location" beats "location".
URL_COLUMN_HINTS = ("page_location", "page location", "page_path", "page path", "pagepath",
                    "url", "landing page", "landing_page", "page", "request", "request_uri",
                    "link", "location", "href", "param_value", "event_param_value", "value")


def decode_bytes(raw: bytes) -> str:
    """Real exports arrive with a BOM, or from Excel in cp1252. Never raise on encoding."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def pick_column(fields: list[str]) -> str | None:
    lowered = {f.strip().lower(): f for f in fields if f}
    for hint in URL_COLUMN_HINTS:
        for low, original in lowered.items():
            if low == hint:
                return original
    for hint in URL_COLUMN_HINTS:
        for low, original in lowered.items():
            if hint in low:
                return original
    return None


def strings_in(obj, depth: int = 0) -> list[str]:
    """Every string in a nested structure, for JSON-lines exports (BigQuery)."""
    if depth > 6:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in strings_in(v, depth + 1)]
    if isinstance(obj, list):
        return [s for v in obj for s in strings_in(v, depth + 1)]
    return []


def load_values(path: str, column: str | None = None) -> tuple[list[str], str]:
    """Return (values, how_we_read_it).

    Accepts CSV, TSV, JSON lines, server logs, or one value per line. The second element
    is shown to the user, because "which column did it actually read" is the first question
    anyone asks of a report they did not expect.
    """
    with open(path, "rb") as fh:
        text = decode_bytes(fh.read())
    if not text.strip():
        return [], "empty file"

    lines = [ln for ln in text.splitlines() if ln.strip()]

    if lines[0].lstrip().startswith("{"):
        out = []
        for ln in lines:
            try:
                out.extend(strings_in(json.loads(ln)))
            except json.JSONDecodeError:
                continue
        if out:
            return out, "JSON lines"

    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        dialect, has_header = None, False

    if dialect and has_header:
        rows = list(csv.DictReader(lines, dialect=dialect))
        if rows:
            fields = [f for f in (rows[0].keys() or []) if f]
            picked = column or pick_column(fields)
            if picked and picked in rows[0]:
                vals = [r.get(picked) or "" for r in rows]
                return [v for v in vals if v.strip()], f"column '{picked}'"
            vals = [v for r in rows for v in r.values() if v and v.strip()]
            return vals, "all columns (no URL column recognised)"

    return lines, "one value per line"


def redact(value: str, kind: str = "") -> str:
    """Mask a value for display. A tool that prints the personal data it just found is the
    bug it is looking for, so this is used on every value that reaches a report."""
    v = (value or "").strip()
    if not v:
        return "(empty)"
    if kind == "email" and "@" in v:
        local, _, domain = v.partition("@")
        dom, _, tld = domain.rpartition(".")
        return f"{local[:1]}***@{dom[:1]}***.{tld}"
    if len(v) <= 4:
        return v[:1] + "*" * (len(v) - 1)
    return f"{v[:2]}{'*' * min(len(v) - 4, 12)}{v[-2:]}"


def wrap(text: str, width: int) -> list[str]:
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out
