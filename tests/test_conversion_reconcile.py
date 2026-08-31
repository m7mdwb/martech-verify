#!/usr/bin/env python3
"""Offline tests for conversion-reconcile.

    python tests/test_conversion_reconcile.py

The important assertion is not that each scenario produces a diagnosis. It is that each
produces a DIFFERENT one. A detector that always answered "duplicate events" would pass a
single-scenario test and be worthless, so every scenario is checked against the top-ranked
cause and the clean pair is checked for silence.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "conversion-reconcile" / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import reconcile  # noqa: E402

FIX = ROOT / "fixtures" / "conversion-reconcile"

# scenario -> (expected top cause, or None for "say nothing")
SCENARIOS = {
    "clean": None,
    "duplicate_events": "duplicate_events",
    "broad_trigger": "trigger_matching_too_broadly",
    "timezone_offset": "timezone_or_window_mismatch",
}


def report_for(scenario: str) -> dict:
    p_rows, p_fields = reconcile.load_rows(str(FIX / f"{scenario}_platform.csv"))
    c_rows, c_fields = reconcile.load_rows(str(FIX / f"{scenario}_crm.csv"))
    ctx = reconcile.build_context(p_rows, p_fields, c_rows, c_fields)
    return reconcile.build_report(ctx)


def main() -> int:
    fails = 0
    reports = {}

    print("SCENARIO DIAGNOSIS")
    print("-" * 78)
    for scenario, expected in SCENARIOS.items():
        if not (FIX / f"{scenario}_platform.csv").exists():
            print(f"  FAIL {scenario}: fixture missing — run python tools/make_fixtures.py")
            fails += 1
            continue
        report = report_for(scenario)
        reports[scenario] = report
        top = report["diagnoses"][0]["cause"] if report["diagnoses"] else None
        ok = top == expected
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {scenario:<18} ratio {report['ratio']:>5.2f}  "
              f"top: {top or '(silent)'}")
        if not ok:
            print(f"       expected {expected or '(silent)'}; "
                  f"all: {[d['cause'] for d in report['diagnoses']]}")

    print("\nDISCRIMINATION")
    print("-" * 78)
    # The whole point: three faults, three different answers. If two scenarios share a top
    # diagnosis the tool is pattern-matching on nothing.
    tops = [r["diagnoses"][0]["cause"] for s, r in reports.items()
            if SCENARIOS[s] and r["diagnoses"]]
    unique = len(set(tops)) == len(tops)
    fails += not unique
    print(f"  {'ok  ' if unique else 'FAIL'} {len(set(tops))} distinct top causes across "
          f"{len(tops)} faulty scenarios")

    print("\nEVIDENCE QUALITY")
    print("-" * 78)
    # Every diagnosis must carry checkable evidence and an action. A label with neither is
    # a guess wearing a lab coat.
    for scenario, report in reports.items():
        for d in report["diagnoses"]:
            has = len(d["evidence"]) > 40 and len(d["action"]) > 40 and any(
                ch.isdigit() for ch in d["evidence"])
            fails += not has
            print(f"  {'ok  ' if has else 'FAIL'} {scenario:<18} {d['cause']:<32} "
                  f"evidence carries numbers and an action")

    print("\nBEHAVIOUR")
    print("-" * 78)
    checks = [
        ("clean pair exits 0",
         lambda: run_cli("clean") == 0),
        ("faulty pair exits 1",
         lambda: run_cli("duplicate_events") == 1),
        ("clean pair produces no diagnoses",
         lambda: reports["clean"]["diagnoses"] == []),
        ("duplicate scenario joins every id",
         lambda: reports["duplicate_events"]["platform_only_ids"] == 0),
        ("broad trigger leaves unmatched platform ids",
         lambda: reports["broad_trigger"]["platform_only_ids"] > 100),
        ("timezone scenario has equal totals",
         lambda: reports["timezone_offset"]["ratio"] == 1.0),
        ("join key auto-detected as transaction_id",
         lambda: all(r["join_key"] == "transaction_id" for r in reports.values())),
    ]
    for label, fn in checks:
        try:
            ok = bool(fn())
        except Exception as e:  # noqa: BLE001
            ok, label = False, f"{label} (raised {type(e).__name__}: {e})"
        fails += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")

    total = len(SCENARIOS) + 1 + sum(len(r["diagnoses"]) for r in reports.values()) + len(checks)
    print("-" * 78)
    print(f"{total - fails}/{total} passed" if not fails else f"{fails} FAILED of {total}")
    return 1 if fails else 0


def run_cli(scenario: str) -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "skills" / "conversion-reconcile" / "scripts" / "reconcile.py"),
         "--platform", str(FIX / f"{scenario}_platform.csv"),
         "--crm", str(FIX / f"{scenario}_crm.csv")],
        capture_output=True, text=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
