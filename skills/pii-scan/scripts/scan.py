#!/usr/bin/env python3
"""Find personal data that has leaked into analytics URLs, paths and event parameters.

Reads an export you already have — GA4, BigQuery, a server log, or a plain list of URLs —
and reports every value that looks like personal data, where it came from, and how to stop
it. Standard library only. Nothing is transmitted anywhere.

    python scan.py export.csv
    python scan.py urls.txt --json
    python scan.py export.csv --column page_location --fail-on high

Exit codes: 0 nothing found · 1 findings at or above --fail-on · 2 could not read input.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, unquote, unquote_plus, urlsplit

# --------------------------------------------------------------------------------------
# What counts as personal data
#
# Two independent signals, and the tool is careful to say which one fired:
#   VALUE signals  - the value itself is verifiably personal (an address that parses as an
#                    email, digits that pass Luhn, an IBAN whose checksum is right).
#   NAME signals   - the parameter is called "email" or "phone". Suggestive, not proof.
# A name signal alone is never reported as confirmed. That distinction is the difference
# between a report someone acts on and a report someone stops reading.
# --------------------------------------------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone numbers are the easiest thing in this file to get wrong: order ids, timestamps and
# product codes are all digit runs. Only two shapes are trusted — an explicit E.164 number,
# or a classic separated format. Everything else needs a parameter name to corroborate it.
E164_RE = re.compile(r"\+\d{7,15}(?!\d)")
SEPARATED_PHONE_RE = re.compile(r"(?<!\d)(?:\(\d{2,4}\)[\s.\-]?\d{3,4}[\s.\-]?\d{3,4}"
                                r"|\d{3,4}[\s.\-]\d{3,4}[\s.\-]\d{3,4})(?!\d)")
CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
IBAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}[A-Z0-9]{11,30}(?![A-Z0-9])")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]*)?")
DOB_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])(?!\d)")
BASE64_RE = re.compile(r"^[A-Za-z0-9+/=_\-]{12,}$")

# Parameter names that carry personal data often enough to be worth reporting on their own.
NAME_FAMILIES = {
    "email": ("email", "e_mail", "emailaddress", "email_address", "mail", "usermail",
              "customer_email", "contact_email", "em"),
    "phone": ("phone", "telephone", "tel", "mobile", "msisdn", "phone_number",
              "phonenumber", "contact_number", "whatsapp"),
    "name": ("name", "fname", "lname", "firstname", "first_name", "lastname", "last_name",
             "fullname", "full_name", "customer_name", "contact_name", "surname"),
    "address": ("address", "address1", "address_1", "addr", "street", "street_address",
                "zip", "zipcode", "postcode", "postal_code", "city_address"),
    "dob": ("dob", "birthdate", "birth_date", "birthday", "date_of_birth"),
    "government_id": ("ssn", "nino", "nin", "national_id", "passport", "tax_id", "vat_id",
                      "id_number", "personal_code"),
    "credential": ("password", "passwd", "pwd", "token", "auth", "access_token",
                   "api_key", "apikey", "secret", "session", "sid", "otp"),
}

# Values that look personal but are not, and would otherwise make the report untrustworthy.
BENIGN_VALUES = {"", "-", "n/a", "na", "null", "none", "undefined", "(not set)", "0",
                 "false", "true", "test", "example"}
BENIGN_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "test.com",
                        "domain.com", "email.com", "yourdomain.com", "sentry.io")
# Publicly documented test card numbers. Still a finding — a real form posted them — but
# not a customer's card, and saying so keeps the severity honest.
TEST_CARDS = {"4111111111111111", "4242424242424242", "5555555555554444",
              "378282246310005", "6011111111111117", "5105105105105100"}

SEVERITY_ORDER = ["critical", "high", "medium"]

REMEDIATION = {
    "email": "Stop the value reaching the tag. If the form submits over GET, switch it to "
             "POST. If a tag-manager variable captures the field, drop the variable. Then "
             "turn on GA4 Admin > Data Streams > Redact data for email, and add the "
             "parameter to the URL query parameter exclusion list.",
    "phone": "Same order as email: fix the form first, then GA4 Admin > Data Streams > "
             "Redact data has a phone toggle. Redaction only covers what it recognises, so "
             "it is a second line of defence rather than the fix.",
    "credit_card": "Treat as an incident, not a config change. A card number in a URL has "
                   "been written to analytics, to your server logs, to any CDN in front of "
                   "them, and to the browser history of the person who typed it. Fix the "
                   "form, then ask for deletion on every system that received it.",
    "iban": "As with card numbers: fix the source, then pursue deletion. IBANs are personal "
            "data under GDPR and there is no analytics setting that redacts them.",
    "jwt": "A session or auth token in a URL is a takeover risk before it is a privacy one. "
           "Rotate the signing key if the token is still valid, and move the token to a "
           "header or cookie.",
    "credential": "A credential in a URL should be rotated on the assumption it is already "
                  "compromised, then moved out of the query string entirely.",
    "name": "Names are personal data even without an email attached. Remove the parameter "
            "from the URL and pass it in the page's own data layer only if a tag genuinely "
            "needs it, which is rare.",
    "address": "Postal data belongs in your CRM, not in a page path. Move it out of the URL "
               "and exclude the parameter in GA4.",
    "dob": "A date of birth in a URL is special-category-adjacent and has no analytics use. "
           "Remove it at the source.",
    "government_id": "Highest-severity personal data. Remove at the source and treat any "
                     "historical collection as a reportable incident under your DPA process.",
}


# --------------------------------------------------------------------------------------
# Reading whatever the user actually has
# --------------------------------------------------------------------------------------

URL_COLUMN_HINTS = ("page_location", "page location", "page_path", "page path", "pagepath",
                    "url", "landing page", "landing_page", "page", "request", "request_uri",
                    "link", "location", "href", "param_value", "event_param_value", "value")


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def load_values(path: str, column: str | None = None) -> tuple[list[str], str]:
    """Return (values, how_we_read_it). Accepts CSV/TSV, JSON lines, or one value per line."""
    with open(path, "rb") as fh:
        text = _decode(fh.read())
    if not text.strip():
        return [], "empty file"

    lines = [ln for ln in text.splitlines() if ln.strip()]

    # JSON lines, as BigQuery exports them.
    if lines[0].lstrip().startswith("{"):
        out = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                continue
            out.extend(_strings_in(obj))
        if out:
            return out, "JSON lines"

    # Delimited, if the header looks like a header.
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
            picked = column or _pick_column(fields)
            if picked and picked in rows[0]:
                vals = [r.get(picked) or "" for r in rows]
                return [v for v in vals if v.strip()], f"column '{picked}'"
            # No obvious URL column: scan every cell rather than give up.
            vals = [v for r in rows for v in r.values() if v and v.strip()]
            return vals, "all columns (no URL column recognised)"

    return lines, "one value per line"


def _pick_column(fields: list[str]) -> str | None:
    lowered = {f.strip().lower(): f for f in fields}
    for hint in URL_COLUMN_HINTS:
        for low, original in lowered.items():
            if low == hint:
                return original
    for hint in URL_COLUMN_HINTS:
        for low, original in lowered.items():
            if hint in low:
                return original
    return None


def _strings_in(obj, depth: int = 0) -> list[str]:
    if depth > 6:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for v in obj.values() for s in _strings_in(v, depth + 1)]
    if isinstance(obj, list):
        return [s for v in obj for s in _strings_in(v, depth + 1)]
    return []


# --------------------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------------------

def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def iban_ok(candidate: str) -> bool:
    """Real mod-97 check. Without it every uppercase product code is a false positive."""
    s = candidate.upper()
    if len(s) < 15 or len(s) > 34:
        return False
    rearranged = s[4:] + s[:4]
    numeric = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        elif "A" <= ch <= "Z":
            numeric += str(ord(ch) - 55)
        else:
            return False
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def maybe_base64(value: str) -> str | None:
    """Decode base64 that hides an email. Encoding is not anonymisation and the pattern is
    common: a 'user' parameter that is just the address in base64."""
    v = value.strip()
    if len(v) < 12 or len(v) > 512 or not BASE64_RE.match(v):
        return None
    padded = v.replace("-", "+").replace("_", "/")
    padded += "=" * (-len(padded) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
    except (binascii.Error, ValueError):
        return None
    try:
        text = decoded.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(1 for c in text if 32 <= ord(c) < 127)
    return text if text and printable / len(text) > 0.9 else None


def redact(value: str, kind: str) -> str:
    """A tool that leaks personal data into its own report is the bug it is looking for."""
    v = value.strip()
    if not v:
        return "(empty)"
    if kind == "email" and "@" in v:
        local, _, domain = v.partition("@")
        dom, _, tld = domain.rpartition(".")
        return f"{local[:1]}***@{dom[:1]}***.{tld}"
    if len(v) <= 4:
        return v[:1] + "*" * (len(v) - 1)
    return f"{v[:2]}{'*' * min(len(v) - 4, 12)}{v[-2:]}"


def safe_location(text: str) -> str:
    """Redact a path before it is ever shown as a location.

    Paths carry personal data too — /receipt/4539578763621486/print is a real shape — and
    the "where it is coming from" section would otherwise reprint in full the exact value
    it just flagged. Caught by this repo's own redaction test, which is the whole argument
    for having one: a scanner that leaks in its own report is the bug it is looking for.
    """
    def _card(m):
        digits = re.sub(r"[ \-]", "", m.group(0))
        return redact(digits, "card") if len(digits) >= 13 and luhn_ok(digits) else m.group(0)

    out = EMAIL_RE.sub(lambda m: redact(m.group(0), "email"), text)
    out = JWT_RE.sub(lambda m: redact(m.group(0), "jwt"), out)
    out = E164_RE.sub(lambda m: redact(m.group(0), "phone"), out)
    out = IBAN_RE.sub(
        lambda m: redact(m.group(0), "iban") if iban_ok(m.group(0)) else m.group(0), out)
    return CARD_CANDIDATE_RE.sub(_card, out)


class Finding:
    __slots__ = ("kind", "severity", "signal", "param", "sample", "location", "note")

    def __init__(self, kind, severity, signal, param, sample, location, note=""):
        self.kind = kind
        self.severity = severity
        self.signal = signal        # "value" (verified) or "name" (parameter name only)
        self.param = param
        self.sample = sample
        self.location = location
        self.note = note

    def key(self):
        return (self.kind, self.param, self.signal, self.severity)

    def as_dict(self):
        return {"kind": self.kind, "severity": self.severity, "signal": self.signal,
                "parameter": self.param, "redacted_sample": self.sample,
                "location": self.location, "note": self.note}


def _name_family(param: str) -> str | None:
    p = param.strip().lower().lstrip("_")
    for family, names in NAME_FAMILIES.items():
        if p in names:
            return family
    return None


def scan_value(value: str, param: str, location: str, depth: int = 0) -> list[Finding]:
    """Findings for one parameter value. Recurses once through base64."""
    out: list[Finding] = []
    benign_value_seen = False
    v = (value or "").strip()
    if v.lower() in BENIGN_VALUES:
        # An empty PII-named parameter is still worth one medium: the plumbing exists and
        # will carry a real value the moment someone fills the field in.
        fam = _name_family(param)
        if fam and depth == 0:
            out.append(Finding(fam, "medium", "name", param, "(empty)", location,
                               "parameter present but empty — the leak path exists"))
        return out

    for m in EMAIL_RE.finditer(v):
        addr = m.group(0)
        if addr.lower().endswith(BENIGN_EMAIL_DOMAINS):
            # Deliberately excluded, so the parameter name must not resurrect it below.
            # Reporting example.com as a leak is how an audit tool loses its reader.
            benign_value_seen = True
            continue
        out.append(Finding("email", "critical", "value", param, redact(addr, "email"),
                           location))

    for m in E164_RE.finditer(v):
        out.append(Finding("phone", "critical", "value", param,
                           redact(m.group(0), "phone"), location))
    if not out or all(f.kind != "phone" for f in out):
        for m in SEPARATED_PHONE_RE.finditer(v):
            corroborated = _name_family(param) == "phone"
            out.append(Finding("phone", "critical" if corroborated else "medium", "value",
                               param, redact(m.group(0), "phone"), location,
                               "" if corroborated else
                               "digit pattern only — could be an order or reference number"))

    for m in CARD_CANDIDATE_RE.finditer(v):
        digits = re.sub(r"[ \-]", "", m.group(0))
        if len(digits) < 13 or not luhn_ok(digits):
            continue
        is_test = digits in TEST_CARDS
        out.append(Finding("credit_card", "high" if is_test else "critical", "value", param,
                           redact(digits, "card"), location,
                           "publicly documented test card — still a live leak path"
                           if is_test else ""))

    for m in IBAN_RE.finditer(v):
        if iban_ok(m.group(0)):
            out.append(Finding("iban", "critical", "value", param,
                               redact(m.group(0), "iban"), location))

    for m in JWT_RE.finditer(v):
        out.append(Finding("jwt", "critical", "value", param, redact(m.group(0), "jwt"),
                           location, "session or auth token in a URL"))

    # The parameter name is the weakest signal, so it only speaks when nothing stronger
    # already has. If any value in this parameter was verified — or was examined and
    # deliberately cleared — the name adds nothing but a duplicate row.
    fam = _name_family(param)
    if fam and not out and not benign_value_seen:
        severity = "critical" if fam in ("credential", "government_id") else "high"
        note = "parameter name indicates personal data; value not independently verified"
        if fam == "dob" and DOB_RE.search(v):
            severity, note = "critical", "date of birth"
        out.append(Finding(fam, severity, "name", param, redact(v, fam), location, note))

    if depth == 0:
        decoded = maybe_base64(v)
        if decoded and decoded != v:
            for f in scan_value(decoded, param, location, depth + 1):
                f.note = (f.note + " " if f.note else "") + "(found base64-encoded)"
                f.severity = "critical" if f.signal == "value" else f.severity
                out.append(f)
    return out


def scan_entry(entry: str) -> list[Finding]:
    """Findings for one URL, path or raw value."""
    raw = (entry or "").strip()
    if not raw:
        return []

    # ⚠️ Parse BEFORE decoding, never after. `parse_qsl` reads form encoding, where "+"
    # means a space — so unquoting the whole URL first turns "%2B35799123456" into
    # " 35799123456" and a verified E.164 phone number silently degrades into an
    # unverified guess. Found by reading the scanner's own output against a fixture whose
    # answer was known.
    parts = urlsplit(raw if "://" in raw else ("//host" + raw if raw.startswith("/") else raw))
    location = safe_location((parts.path or raw)[:80])

    findings: list[Finding] = []
    pairs = parse_qsl(parts.query, keep_blank_values=True) if parts.query else []
    for key, val in pairs:
        findings.extend(scan_value(val, key, location))
        # Redirect chains double-encode. Only rescan when decoding actually changed
        # something, so ordinary values are not scanned twice — and use unquote, NOT
        # unquote_plus: parse_qsl has already applied form decoding, and applying it twice
        # eats the "+" of an E.164 number and downgrades a verified phone to a guess.
        again = unquote(val)
        if again != val:
            findings.extend(scan_value(again, key, location))
    if parts.query and not pairs:
        findings.extend(scan_value(unquote_plus(parts.query), "(query)", location))

    # The path and fragment carry personal data too: /order/confirm/name@example.co is a
    # real shape. unquote, not unquote_plus — a "+" in a path is a literal plus.
    for chunk, label in ((parts.path, "(path)"), (parts.fragment, "(fragment)")):
        if chunk:
            findings.extend(scan_value(unquote(chunk), label, location))

    # A bare value with no URL structure at all (an event-parameter export column).
    if not parts.query and not parts.path and not parts.fragment:
        findings.extend(scan_value(raw, "(value)", location))
    return findings


# --------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------

def build_report(values: list[str]) -> dict:
    grouped: dict[tuple, dict] = {}
    severities = Counter()
    kinds = Counter()
    locations: dict[tuple, Counter] = defaultdict(Counter)

    for entry in values:
        for f in scan_entry(entry):
            k = f.key()
            g = grouped.setdefault(k, {"finding": f, "count": 0})
            g["count"] += 1
            locations[k][f.location] += 1

    rows = []
    for k, g in grouped.items():
        f, count = g["finding"], g["count"]
        severities[f.severity] += count
        kinds[f.kind] += count
        rows.append({**f.as_dict(), "count": count,
                     "top_locations": [loc for loc, _ in locations[k].most_common(3)]})

    rows.sort(key=lambda r: (SEVERITY_ORDER.index(r["severity"]), -r["count"]))
    return {"scanned": len(values), "findings": rows,
            "by_severity": dict(severities), "by_kind": dict(kinds),
            "remediation": {kind: REMEDIATION[kind] for kind in kinds if kind in REMEDIATION}}


def render(report: dict, source: str, how: str) -> str:
    L = []
    L.append(f"pii-scan · {report['scanned']:,} values read from {os.path.basename(source)} ({how})")
    L.append("=" * 78)
    if not report["findings"]:
        L.append("")
        L.append("  No personal data found.")
        L.append("")
        L.append("  Worth knowing what that does and does not mean: this reads the export you")
        L.append("  gave it. If the export covers one month, the answer covers one month.")
        return "\n".join(L)

    counts = report["by_severity"]
    summary = " · ".join(f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts.get(s))
    L.append(f"  {sum(counts.values()):,} affected values — {summary}")
    L.append("")
    L.append(f"  {'severity':<9} {'kind':<15} {'parameter':<22} {'count':>7}  example")
    L.append(f"  {'-'*9} {'-'*15} {'-'*22} {'-'*7}  {'-'*24}")
    for r in report["findings"]:
        mark = "!" if r["signal"] == "value" else "?"
        L.append(f"  {r['severity']:<9} {r['kind']:<15} {r['parameter'][:22]:<22} "
                 f"{r['count']:>7}  {mark} {r['redacted_sample'][:24]}")
        if r["note"]:
            L.append(f"  {'':<9} {'':<15} └─ {r['note'][:60]}")
    L.append("")
    L.append("  ! the value itself was verified   ? the parameter name says so, the value was not verified")
    L.append("")
    L.append("  Where it is coming from")
    L.append("  " + "-" * 40)
    for r in report["findings"][:6]:
        for loc in r["top_locations"][:2]:
            L.append(f"    {r['kind']:<15} {loc}")
    L.append("")
    L.append("  What to do")
    L.append("  " + "-" * 40)
    for kind, text in report["remediation"].items():
        L.append(f"    {kind}:")
        for line in _wrap(text, 70):
            L.append(f"      {line}")
    return "\n".join(L)


def _wrap(text: str, width: int) -> list[str]:
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Find personal data leaking into analytics URLs and event parameters.")
    p.add_argument("input", help="CSV, TSV, JSON lines, server log, or one URL per line")
    p.add_argument("--column", help="column to read (default: auto-detect)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--fail-on", choices=SEVERITY_ORDER, default="high",
                   help="exit non-zero at this severity or above (default: high)")
    args = p.parse_args(argv)

    try:
        values, how = load_values(args.input, args.column)
    except OSError as e:
        print(f"could not read {args.input}: {e}", file=sys.stderr)
        return 2

    report = build_report(values)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render(report, args.input, how))

    threshold = SEVERITY_ORDER.index(args.fail_on)
    hit = any(SEVERITY_ORDER.index(r["severity"]) <= threshold for r in report["findings"])
    return 1 if hit else 0


if __name__ == "__main__":
    raise SystemExit(main())
