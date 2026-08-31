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
import sys
from collections import Counter


class LoadError(ValueError):
    """The file could not be read as data. Carries a message meant for a human."""


def _raise_field_limit() -> None:
    """csv refuses fields over 131,072 characters by default and raises rather than
    truncating. A single base64 blob or a long redirect URL in one cell is enough, and
    "field larger than field limit" is not a sentence anyone can act on. Walk the limit
    down from sys.maxsize because some platforms reject the largest value."""
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10


_raise_field_limit()

SEVERITY_ORDER = ["critical", "high", "medium"]

# Column names that carry a URL, in the exports people actually have. Ordered: exact
# matches are tried before substring matches, so "page_location" beats "location".
URL_COLUMN_HINTS = ("page_location", "page location", "page_path", "page path", "pagepath",
                    "url", "landing page", "landing_page", "page", "request", "request_uri",
                    "link", "location", "href", "param_value", "event_param_value", "value")


def use_utf8_stdout() -> None:
    """Make stdout safe for the report's own characters.

    The reports contain '·' and '└─'. When stdout is a pipe or a redirect, Python uses the
    locale encoding, which on a Windows console is cp1252 — so `python scan.py x.csv > out.txt`
    died with a UnicodeEncodeError and printed nothing at all. Every test in this repo set
    PYTHONIOENCODING, which is exactly why nobody noticed until a tool was run from another
    tool. Called from each CLI's main() rather than on import, because a library that
    reconfigures your streams when you import it is a library that surprises you.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass        # already wrapped, or not a real stream


def decode_bytes(raw: bytes) -> str:
    """Real exports arrive with a BOM, or from Excel in cp1252. Never raise on encoding."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_text(path: str) -> str:
    """Read a text export, refusing bytes that cannot support a trustworthy audit."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if not raw.strip():
        raise LoadError(f"{path} contains no data. Export at least one data row and try again.")

    # A renamed PNG used to decode as latin-1 and receive a reassuring clean result. NULs
    # also usually mean a binary file or UTF-16 export, neither of which these tools can
    # interpret safely. Fail closed rather than auditing an accidental byte soup.
    magic = ((b"\x89PNG\r\n\x1a\n", "PNG image"), (b"\xff\xd8\xff", "JPEG image"),
             (b"GIF87a", "GIF image"), (b"GIF89a", "GIF image"),
             (b"%PDF-", "PDF document"), (b"PK\x03\x04", "ZIP or XLSX file"))
    for signature, kind in magic:
        if raw.startswith(signature):
            raise LoadError(
                f"{path} is a {kind}, not a text export. Export CSV, TSV or JSON Lines.")
    if b"\x00" in raw:
        raise LoadError(
            f"{path} contains NUL bytes and appears binary or UTF-16. "
            "Export it as UTF-8 CSV, TSV or JSON Lines.")
    controls = sum(byte < 32 and byte not in (9, 10, 13) for byte in raw[:65536])
    if controls > max(4, len(raw[:65536]) // 100):
        raise LoadError(
            f"{path} contains binary control bytes. Export a plain-text CSV, TSV or JSON Lines file.")
    return decode_bytes(raw)


def _header_duplicates(fields: list[str]) -> list[str]:
    normalised = [f.strip().casefold() for f in fields]
    counts = Counter(normalised)
    return sorted({fields[i].strip() or "(empty)" for i, name in enumerate(normalised)
                   if counts[name] > 1})


def _looks_like_header(fields: list[str]) -> bool:
    normalised = {f.strip().casefold() for f in fields}
    return bool(normalised.intersection(URL_COLUMN_HINTS))


def _header_delimiter(lines: list[str]) -> str | None:
    """Recover a delimiter when Sniffer rejects a malformed table.

    Sniffer quite reasonably gives up on ragged rows. Falling all the way back to
    "one value per line" is not reasonable when the first row is plainly a delimited
    export header: it turns broken CSV into a clean scan. Only use this narrow fallback
    for a recognisable header so ordinary logs containing commas keep working as lines.
    """
    first = lines[0]
    for delimiter in (",", ";", "\t", "|"):
        try:
            fields = next(csv.reader([first], delimiter=delimiter, strict=True))
        except (csv.Error, StopIteration):
            continue
        if len(fields) > 1 and _looks_like_header(fields):
            return delimiter
    return None


def _parse_table(lines: list[str], dialect, path: str,
                 header_expected: bool) -> tuple[list[str], list[list[str]]]:
    """Parse and validate a rectangular delimited table before interpreting any values."""
    try:
        if isinstance(dialect, str) and len(dialect) == 1:
            parsed = list(csv.reader(lines, delimiter=dialect, strict=True))
        else:
            parsed = list(csv.reader(lines, dialect=dialect, strict=True))
    except csv.Error as e:
        raise LoadError(f"could not parse {path} as delimited text: {e}") from e
    if not parsed:
        raise LoadError(f"{path} contains no data rows.")

    fields = parsed[0]
    width = len(fields)
    for number, row in enumerate(parsed[1:], 2):
        if len(row) != width:
            raise LoadError(
                f"{path} row {number} has {len(row)} columns; the header has {width}. "
                "Repair or re-export the ragged row.")

    if header_expected or _looks_like_header(fields):
        duplicates = _header_duplicates(fields)
        if duplicates:
            raise LoadError(
                f"{path} has duplicate header(s): {', '.join(duplicates)}. "
                "Rename each column uniquely and re-export.")
        if len(parsed) == 1:
            raise LoadError(
                f"{path} contains a header but no data rows. Export at least one row and try again.")
    return fields, parsed[1:]


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
    text = _read_text(path)

    lines = [ln for ln in text.splitlines() if ln.strip()]

    if lines[0].lstrip().startswith("{"):
        out = []
        for number, ln in enumerate(text.splitlines(), 1):
            if not ln.strip():
                continue
            try:
                record = json.loads(ln)
            except json.JSONDecodeError as e:
                raise LoadError(
                    f"could not parse {path} as JSON Lines: line {number} is invalid ({e.msg}). "
                    "Repair or re-export the truncated record.") from e
            if not isinstance(record, dict):
                raise LoadError(
                    f"could not parse {path} as JSON Lines: line {number} is not an object.")
            out.extend(strings_in(record))
        if not out:
            raise LoadError(f"{path} contains JSON records but no text values to inspect.")
        return out, "JSON lines"

    sample = "\n".join(lines[:20])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        has_header = csv.Sniffer().has_header(sample)
    except csv.Error:
        dialect, has_header = _header_delimiter(lines), False

    if dialect:
        fields, raw_rows = _parse_table(lines, dialect, path, has_header)
        has_header = has_header or _looks_like_header(fields)
        if has_header:
            rows = [dict(zip(fields, row)) for row in raw_rows]
            if column and column not in fields:
                available = ", ".join(fields[:12])
                raise LoadError(
                    f"column '{column}' was not found in {path}. Available columns: {available}")
            picked = column or pick_column(fields)
            if picked:
                vals = [r.get(picked) or "" for r in rows]
                return [v for v in vals if v.strip()], f"column '{picked}'"
            vals = [v for r in rows for v in r.values() if v and v.strip()]
            return vals, "all columns (no URL column recognised)"

    return lines, "one value per line"


def load_rows(path: str) -> tuple[list[dict], list[str]]:
    """Return (rows as dicts, field names) for a delimited export.

    Where `load_values` flattens a file into strings, this keeps the columns, because
    anything that compares two systems needs to join on one field and group by another.
    """
    text = _read_text(path)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines[0].lstrip().startswith(("{", "[")):
        raise LoadError(
            f"{path} looks like JSON. This comparison needs a CSV or TSV export with a header row.")
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]), delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    raw_fields, raw_rows = _parse_table(lines, dialect, path, True)
    fields = [f.strip() for f in raw_fields if f]
    if not fields or len(fields) != len(raw_fields):
        raise LoadError(f"{path} has an empty column name. Name every column and re-export.")
    rows = [{field.strip(): value.strip() for field, value in zip(raw_fields, row)}
            for row in raw_rows]
    return rows, fields


def find_column(fields: list[str], candidates: tuple[str, ...]) -> str | None:
    """First field matching a candidate name, exact match before substring."""
    lowered = {f.lower(): f for f in fields}
    for c in candidates:
        if c in lowered:
            return lowered[c]
    for c in candidates:
        for low, original in lowered.items():
            if c in low:
                return original
    return None


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
