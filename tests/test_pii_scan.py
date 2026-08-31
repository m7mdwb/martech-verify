#!/usr/bin/env python3
"""Offline tests for pii-scan. No network, no dependencies, no fixtures but our own.

    python tests/test_pii_scan.py

The fixture has known planted defects and the first test asserts we find exactly those and
nothing else. A scanner that finds one extra thing is a scanner people stop running.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "pii-scan" / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import scan  # noqa: E402

FIXTURE = ROOT / "fixtures" / "pii-scan" / "ga4_pages_sample.csv"

# Ground truth: (kind, parameter, severity, signal). Everything planted, nothing else.
EXPECTED = {
    ("email", "email", "critical", "value"),
    ("email", "u", "critical", "value"),            # base64-encoded
    ("phone", "phone", "critical", "value"),        # %2B... must survive as E.164
    ("credit_card", "(path)", "critical", "value"),
    ("iban", "iban", "critical", "value"),
    ("jwt", "token", "critical", "value"),
    ("dob", "dob", "critical", "name"),
    ("credit_card", "cc", "high", "value"),         # documented test card
    ("name", "fname", "high", "name"),
    ("name", "lname", "high", "name"),
    ("phone", "ref", "medium", "value"),            # digits only, uncorroborated
    ("email", "email", "medium", "name"),           # present but empty
}

# (url, expected kinds) — the individual behaviours worth pinning down.
CASES = [
    ("https://x.test/a?email=someone%40gmail.com", {"email"},
     "plain email in a query parameter"),
    ("https://x.test/a?email=qa%40example.com", set(),
     "example.com is documentation, not a customer — and the parameter NAME must not "
     "resurrect it after the value was deliberately cleared"),
    ("https://x.test/a?phone=%2B35799123456", {"phone"},
     "REGRESSION: parse before decode. unquote_plus turns '+' into a space and silently "
     "downgrades a verified E.164 number to an unverified name match"),
    ("https://x.test/orders/1234567890123?status=shipped", set(),
     "a 13-digit order id that fails Luhn is not a card"),
    ("https://x.test/pay?cc=4111111111111111", {"credit_card"},
     "documented test card still reports — the leak path is real either way"),
    ("https://x.test/r?u=bWFyaWEua2FsbGlzQGdtYWlsLmNvbQ==", {"email"},
     "base64 is not anonymisation"),
    ("https://x.test/signup?email=&plan=starter", {"email"},
     "an empty PII parameter is still a leak path"),
    ("https://x.test/pricing?utm_source=linkedin&utm_medium=paid", set(),
     "ordinary campaign tagging must be silent"),
    ("https://x.test/refund?iban=GB82WEST12345698765432", {"iban"},
     "IBAN with a correct mod-97 checksum"),
    ("https://x.test/refund?iban=GB82WEST12345698765433", set(),
     "one digit wrong: the checksum is the whole point of checking it"),
    ("https://x.test/checkout/success?order=A-10054", set(),
     "a clean checkout URL"),
    ("/contact?email=maria%40gmail.com", {"email"},
     "a bare path with no scheme still parses"),
]

UNIT = [
    ("luhn accepts a valid number", lambda: scan.luhn_ok("4539578763621486") is True),
    ("luhn rejects an invalid one", lambda: scan.luhn_ok("4539578763621487") is False),
    ("iban accepts the canonical example", lambda: scan.iban_ok("GB82WEST12345698765432") is True),
    ("iban rejects a corrupted one", lambda: scan.iban_ok("GB82WEST12345698765433") is False),
    ("iban rejects an ordinary product code", lambda: scan.iban_ok("SKU2024PRODUCTX") is False),
    ("base64 decoder returns the address",
     lambda: scan.maybe_base64("bWFyaWEua2FsbGlzQGdtYWlsLmNvbQ==") == "maria.kallis@gmail.com"),
    ("base64 decoder ignores ordinary words", lambda: scan.maybe_base64("newsletter") is None),
]


def main() -> int:
    fails = 0

    print("FIXTURE GROUND TRUTH")
    print("-" * 78)
    values, how = scan.load_values(str(FIXTURE))
    report = scan.build_report(values)
    got = {(r["kind"], r["parameter"], r["severity"], r["signal"]) for r in report["findings"]}
    missing, extra = EXPECTED - got, got - EXPECTED
    print(f"  read {len(values)} values via {how}; {len(got)} distinct findings")
    for m in sorted(missing):
        print(f"  FAIL missing  {m}")
        fails += 1
    for e in sorted(extra):
        print(f"  FAIL spurious {e}")
        fails += 1
    if not missing and not extra:
        print(f"  ok   all {len(EXPECTED)} planted defects found, nothing invented")

    print("\nBEHAVIOUR")
    print("-" * 78)
    for url, expected_kinds, why in CASES:
        kinds = {f.kind for f in scan.scan_entry(url)}
        ok = kinds == expected_kinds
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {sorted(kinds) or '[]'} {url[:52]}")
        if not ok:
            print(f"       wanted {sorted(expected_kinds) or '[]'} — {why}")

    print("\nUNITS")
    print("-" * 78)
    for label, fn in UNIT:
        try:
            ok = bool(fn())
        except Exception as e:  # noqa: BLE001
            ok, label = False, f"{label} (raised {type(e).__name__})"
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")

    print("\nREDACTION SAFETY")
    print("-" * 78)
    # The one failure this tool cannot survive: printing the personal data it found.
    secrets = ["maria.kallis@gmail.com", "+35799123456", "4539578763621486",
               "GB82WEST12345698765432", "Andreas", "Georgiou"]
    blob = scan.render(report, str(FIXTURE), how) + str(report)
    for s in secrets:
        leaked = s in blob
        fails += leaked
        print(f"  {'FAIL' if leaked else 'ok  '} never printed in full: {s[:24]}")

    total = len(EXPECTED) + len(CASES) + len(UNIT) + len(secrets)
    print("-" * 78)
    print(f"{total - fails}/{total} passed" if not fails else f"{fails} FAILED of {total}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
