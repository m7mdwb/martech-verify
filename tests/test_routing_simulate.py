#!/usr/bin/env python3
"""Offline tests for routing-simulate.

    python tests/test_routing_simulate.py

Two fixtures on the same leads: a routing file with four planted faults, and the repaired
version of it. The repaired one must be completely silent — a linter that still complains
after you have fixed everything it asked for is one nobody fixes anything for.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "routing-simulate" / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import simulate as sim  # noqa: E402

FIX = ROOT / "fixtures" / "routing-simulate"
LEADS = FIX / "leads_sample.csv"

# What the broken routing file is supposed to reveal.
EXPECTED_PROBLEMS = {
    ("unknown_field", "High intent trial"),      # 'employes' — a typo, silently disabling
    ("shadowed_rule", "France mid-market"),      # a broader rule sits above it
    ("dead_rule", "Japan"),                      # a segment that does not exist
    ("unrouted_leads", ""),                      # no rule covers the rest of the world
    ("load_imbalance", ""),
}

LEAD = {"country": "DE", "employees": "500", "plan_interest": "starter", "note": ""}

CONDITIONS = [
    ("country = DE", True, "string equality is case-insensitive"),
    ("Country = de", True, "CSV field names are also case-insensitive"),
    ("country = de", True, ""),
    ("country != FR", True, ""),
    ("country in DE,AT,CH", True, "membership list"),
    ("country not in FR,ES", True, ""),
    ("employees >= 500", True, "numeric comparison on a string column"),
    ("employees > 500", False, ""),
    ("employees < 50", False, ""),
    ("plan_interest contains star", True, "substring"),
    ("note is empty", True, "an empty field is a routable fact"),
    ("country is not empty", True, ""),
    ("country = FR and employees >= 500", False, "and requires both"),
    ("country = FR or employees >= 500", True, "or requires either"),
    ("country = FR and employees < 10 or plan_interest = starter", True,
     "and binds tighter than or"),
    ("industry = software", False, "a field the lead does not carry never matches"),
]


def run(rules_file: pathlib.Path):
    doc = json.loads(rules_file.read_text(encoding="utf-8"))
    leads, fields = sim.load_rows(str(LEADS))
    report = sim.simulate(doc, leads, fields)
    return report, sim.problems(report)


def main() -> int:
    fails = 0

    print("BROKEN RULES")
    print("-" * 78)
    report, found = run(FIX / "routing_rules.json")
    got = set()
    for p in found:
        # The subject of a finding is the rule named FIRST in it. A shadowed_rule detail
        # names two rules — the victim and the one above it — and scanning in file order
        # picked whichever happened to appear earlier in the rules file.
        named = [(p["detail"].index(f"'{s['rule']}'"), s["rule"])
                 for s in report["rule_stats"] if f"'{s['rule']}'" in p["detail"]]
        rule = min(named)[1] if named else ""
        got.add((p["kind"], rule))
    for expected in sorted(EXPECTED_PROBLEMS):
        ok = expected in got
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {expected[0]:<18} {expected[1]}")
    extra = got - EXPECTED_PROBLEMS
    for e in sorted(extra):
        print(f"  FAIL unexpected problem {e}")
        fails += 1

    print("\n  once a rule is explained by an unknown field it is not also reported dead")
    dead_high_intent = any(p["kind"] == "dead_rule" and "High intent" in p["detail"]
                           for p in found)
    fails += dead_high_intent
    print(f"  {'FAIL' if dead_high_intent else 'ok  '} 'High intent trial' appears once, "
          f"not twice")

    print("\nREPAIRED RULES")
    print("-" * 78)
    fixed_report, fixed_found = run(FIX / "routing_rules_fixed.json")
    silent = not fixed_found
    fails += not silent
    print(f"  {'ok  ' if silent else 'FAIL'} the repaired routing produces no problems")
    if not silent:
        for p in fixed_found:
            print(f"       still reported: {p['kind']} — {p['detail'][:90]}")
    no_unrouted = fixed_report["unrouted"] == 0
    fails += not no_unrouted
    print(f"  {'ok  ' if no_unrouted else 'FAIL'} every lead lands with an owner")

    # The false positive this design exists to avoid: a catch-all BELOW specific rules is
    # correct cascade design and must never be reported, even though it loses most of its
    # matches to the rules above it.
    catchall = next(s for s in fixed_report["rule_stats"] if s["rule"] == "Europe catch-all")
    quiet_catchall = catchall["matched"] > catchall["won"] and not catchall["broader_above"]
    fails += not quiet_catchall
    print(f"  {'ok  ' if quiet_catchall else 'FAIL'} a catch-all below specific rules loses "
          f"{catchall['matched'] - catchall['won']} matches and is not a finding")

    print("\nCONDITION LANGUAGE")
    print("-" * 78)
    for text, expected, why in CONDITIONS:
        try:
            got_value = sim.matches(sim.parse_when(text), LEAD)
            ok = got_value == expected
        except Exception as e:  # noqa: BLE001
            ok, got_value = False, f"raised {type(e).__name__}"
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {str(got_value):<5} {text}")
        if not ok and why:
            print(f"       {why}")

    print("\nERRORS ARE READABLE")
    print("-" * 78)
    checks = [
        ("an unparseable condition names the problem",
         lambda: _raises(sim.parse_when, "country DE")),
        ("a rules file with no rules is rejected",
         lambda: _raises(sim.simulate, {"rules": []}, [], [])),
        ("a rule missing 'assign' is rejected",
         lambda: _raises(sim.simulate, {"rules": [{"when": "country = DE"}]}, [], [])),
    ]
    for label, fn in checks:
        ok = bool(fn())
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")

    total = len(EXPECTED_PROBLEMS) + 4 + len(CONDITIONS) + len(checks)
    print("-" * 78)
    print(f"{total - fails}/{total} passed" if not fails else f"{fails} FAILED of {total}")
    return 1 if fails else 0


def _raises(fn, *args) -> bool:
    try:
        fn(*args)
    except sim.RuleError:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


if __name__ == "__main__":
    raise SystemExit(main())
