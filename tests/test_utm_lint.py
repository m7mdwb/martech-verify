#!/usr/bin/env python3
"""Offline tests for utm-lint. No network, no dependencies.

    python tests/test_utm_lint.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "utm-lint" / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import lint  # noqa: E402

FIXTURE = ROOT / "fixtures" / "utm-lint" / "tagged_urls_sample.csv"
SITE = "shop.example-store.test"

# Ground truth: (rule, parameter, value). Everything planted, nothing invented.
EXPECTED = {
    ("pii_in_utm", "utm_content", "m***@g***.com"),
    ("case_drift", "utm_source", "LinkedIn"),
    ("near_duplicate", "utm_campaign", "q3_demand"),
    ("duplicate_param", "utm_source", "appears 2x"),
    ("missing_required", "source + medium", "content-push"),
    ("self_referral", "utm_source", "shop.example-store.test"),
    ("unmapped_medium", "utm_medium", "newsletter"),
    ("unmapped_medium", "utm_medium", "internal"),
    ("whitespace", "utm_medium", "Paid Social"),
    ("whitespace", "utm_campaign", " spring-webinar"),
    ("source_equals_medium", "utm_source", "email"),
    ("source_equals_medium", "utm_source", "newsletter"),
    ("autotagging_conflict", "utm_source", "google"),
    ("empty_param", "utm_campaign", "(empty)"),
}

CASES = [
    ("https://x.test/p?utm_source=bing&utm_medium=cpc&utm_campaign=competitor", set(),
     "correct tagging must be silent, or nobody runs the linter twice"),
    ("https://x.test/p?utm_source=reddit&utm_medium=social&utm_campaign=launch", set(),
     "'social' is a recognised medium"),
    ("https://x.test/about", set(), "an untagged URL is not a finding"),
    ("https://x.test/p?utm_source=x&utm_medium=newsletter&utm_campaign=c",
     {"unmapped_medium"},
     "'newsletter' feels like a medium and is not one — it lands in Unassigned"),
    ("https://x.test/p?utm_source=x&utm_medium=paid-social&utm_campaign=c", set(),
     "'paid-social' matches the paid pattern and is fine"),
    ("https://x.test/p?utm_source=x&utm_medium=CPC&utm_campaign=c", set(),
     "medium matching is case-insensitive, so uppercase CPC is still Paid Search"),
    ("https://x.test/p?utm_source=google&utm_medium=cpc&utm_campaign=b&gclid=abc123",
     {"autotagging_conflict"},
     "a Google click id beside manual tags: the click id wins and the tags are ignored"),
    ("https://x.test/p?utm_source=x&utm_medium=cpc&utm_campaign=%20lead%20space",
     {"whitespace"}, "a leading space survives into the report as a separate value"),
]

UNITS = [
    ("normalise collapses delimiters",
     lambda: lint.normalise("Summer_Sale") == lint.normalise("summer-sale") == "summersale"),
    ("cpc is recognised", lambda: lint.classify_medium("cpc") is not None),
    ("paid-social is recognised", lambda: lint.classify_medium("paid-social") is not None),
    ("email is recognised", lambda: lint.classify_medium("e-mail") is not None),
    ("newsletter is not", lambda: lint.classify_medium("newsletter") is None),
    ("internal is not", lambda: lint.classify_medium("internal") is None),
    ("duplicate keys survive parsing",
     lambda: len(lint.parse("https://x.test/?utm_source=a&utm_source=b")[1]) == 2),
    ("encoded emails are redacted in URL examples",
     lambda: "m***@g***.com" in lint.safe_example(
         "https://x.test/?utm_content=maria.kallis%40gmail.com")),
]


def main() -> int:
    fails = 0

    print("FIXTURE GROUND TRUTH")
    print("-" * 78)
    values, how = lint.load_values(str(FIXTURE))
    report = lint.build_report(values, SITE)
    got = {(r["rule"], r["parameter"], r["value"]) for r in report["findings"]}
    missing, extra = EXPECTED - got, got - EXPECTED
    print(f"  read {len(values)} values via {how}; {report['tagged']} tagged; "
          f"{len(got)} distinct findings")
    for m in sorted(missing):
        print(f"  FAIL missing  {m}")
        fails += 1
    for e in sorted(extra):
        print(f"  FAIL spurious {e}")
        fails += 1
    if not missing and not extra:
        print(f"  ok   all {len(EXPECTED)} planted problems found, nothing invented")

    print("\nBEHAVIOUR")
    print("-" * 78)
    for url, expected_rules, why in CASES:
        rules = {i.rule for i in lint.lint_url(url, "x.test")}
        ok = rules == expected_rules
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {sorted(rules) or '[]'} {url[:50]}")
        if not ok:
            print(f"       wanted {sorted(expected_rules) or '[]'} — {why}")

    print("\nUNITS")
    print("-" * 78)
    for label, fn in UNITS:
        try:
            ok = bool(fn())
        except Exception as e:  # noqa: BLE001
            ok, label = False, f"{label} (raised {type(e).__name__})"
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")

    print("\nREDACTION SAFETY")
    print("-" * 78)
    # utm parameters are not usually personal data, but when one is, the same rule applies
    # as everywhere else in this repo: never reprint what you just flagged.
    blob = lint.render(report, str(FIXTURE), how) + json.dumps(report)
    leaked = any(value in blob for value in (
        "maria.kallis@gmail.com",
        "maria.kallis%40gmail.com",
        "maria.kallis%2540gmail.com",
    ))
    fails += leaked
    print(f"  {'FAIL' if leaked else 'ok  '} the email found in utm_content is never printed in full")

    total = len(EXPECTED) + len(CASES) + len(UNITS) + 1
    print("-" * 78)
    print(f"{total - fails}/{total} passed" if not fails else f"{fails} FAILED of {total}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
