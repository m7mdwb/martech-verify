#!/usr/bin/env python3
"""Every skill, against every way a real export is broken.

    python tests/test_malformed_input.py

Until this existed, the only inputs these tools had ever seen were the fixtures written
alongside them — files shaped exactly the way the parser expected. The first stranger to
try one of these will hand it a header-only export, a file Excel saved as cp1252, or a
JSON-lines dump with one truncated line, and a traceback at that moment is the end of the
relationship.

The contract asserted here is narrow and absolute:

  1. Never traceback. Ever. For any bytes.
  2. Exit 0, 1 or 2 and nothing else.
  3. If it gives up (exit 2), say something a human can act on.
  4. Clearly unreadable or ambiguous input MUST give up rather than report clean.

There is no correct answer for a PNG interpreted as a CSV, which is precisely why accepting
it and printing "No personal data found" is a failure. Valid-but-awkward text files must
still work; inputs that cannot support a trustworthy conclusion must fail closed.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAL = ROOT / "fixtures" / "malformed"
SKILLS = ROOT / "skills"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

CSV_LIKE = ["empty.csv", "whitespace_only.csv", "header_only.csv", "single_column.txt",
            "ragged_rows.csv", "duplicate_headers.csv", "bom.csv", "cp1252.csv",
            "semicolons.csv", "tabs.tsv", "broken_jsonl.jsonl", "binary.csv",
            "huge_field.csv", "no_trailing_newline.csv", "crlf.csv", "nul_bytes.csv"]

MUST_REJECT = {"empty.csv", "whitespace_only.csv", "header_only.csv", "ragged_rows.csv",
               "duplicate_headers.csv", "broken_jsonl.jsonl", "binary.csv", "nul_bytes.csv"}
MUST_ACCEPT = set(CSV_LIKE) - MUST_REJECT

MISSING = "does_not_exist.csv"


def run(args: list[str]) -> subprocess.CompletedProcess:
    # encoding is explicit: a tool fed a PNG may echo bytes the locale codec cannot
    # decode, and the harness crashing on the tool's output is not the tool's fault.
    return subprocess.run([sys.executable, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, cwd=str(ROOT))


def check(label: str, proc: subprocess.CompletedProcess) -> list[str]:
    """Return a list of contract violations, empty when the run behaved."""
    bad = []
    blob = (proc.stdout or "") + (proc.stderr or "")
    if "Traceback (most recent call last)" in blob:
        first = [ln for ln in blob.splitlines() if "Error" in ln or "error" in ln]
        bad.append(f"TRACEBACK — {first[-1][:80] if first else 'see output'}")
    if proc.returncode not in (0, 1, 2):
        bad.append(f"exit code {proc.returncode}")
    if proc.returncode == 2 and not (proc.stderr or "").strip():
        bad.append("gave up silently (exit 2 with nothing on stderr)")
    return bad


def check_input_decision(name: str, proc: subprocess.CompletedProcess) -> list[str]:
    """A malformed audit input must not be mistaken for a clean dataset."""
    if name in MUST_REJECT and proc.returncode != 2:
        return [f"unsafe acceptance — expected exit 2, got {proc.returncode}"]
    if name in MUST_ACCEPT and proc.returncode == 2:
        return ["valid edge-case input was rejected"]
    return []


def main() -> int:
    fails = 0
    checked = 0

    scan = str(SKILLS / "pii-scan" / "scripts" / "scan.py")
    lint = str(SKILLS / "utm-lint" / "scripts" / "lint.py")
    rec = str(SKILLS / "conversion-reconcile" / "scripts" / "reconcile.py")
    sim = str(SKILLS / "routing-simulate" / "scripts" / "simulate.py")

    print("SINGLE-FILE SKILLS AGAINST BROKEN INPUT")
    print("-" * 78)
    for name in CSV_LIKE:
        path = str(MAL / name)
        for tool, argv in (("pii-scan", [scan, path]), ("utm-lint", [lint, path])):
            checked += 1
            proc = run(argv)
            bad = check(f"{tool} {name}", proc) + check_input_decision(name, proc)
            fails += bool(bad)
            print(f"  {'ok  ' if not bad else 'FAIL'} {tool:<10} {name:<24} "
                  f"{'' if not bad else ' · '.join(bad)}")

    print("\nRECONCILE AGAINST BROKEN PAIRS")
    print("-" * 78)
    good = str(ROOT / "fixtures" / "conversion-reconcile" / "clean_platform.csv")
    for name in ["empty.csv", "header_only.csv", "binary.csv", "ragged_rows.csv",
                 "single_column.txt", "broken_jsonl.jsonl", "huge_field.csv"]:
        path = str(MAL / name)
        for label, argv in (
                ("broken platform", [rec, "--platform", path, "--crm", good]),
                ("broken crm", [rec, "--platform", good, "--crm", path])):
            checked += 1
            proc = run(argv)
            bad = check(label, proc)
            if proc.returncode != 2:
                bad.append(f"unsafe acceptance — expected exit 2, got {proc.returncode}")
            fails += bool(bad)
            print(f"  {'ok  ' if not bad else 'FAIL'} {label:<16} {name:<24} "
                  f"{'' if not bad else ' · '.join(bad)}")

    print("\nROUTING AGAINST BROKEN RULES AND LEADS")
    print("-" * 78)
    leads = str(ROOT / "fixtures" / "routing-simulate" / "leads_sample.csv")
    rules = str(ROOT / "fixtures" / "routing-simulate" / "routing_rules.json")
    cases = [("rules_invalid.json", leads), ("rules_is_a_list.json", leads),
             ("rules_bad_condition.json", leads), ("rules_empty.json", leads),
             ("rules_no_assign.json", leads)]
    for rules_name, leads_path in cases:
        checked += 1
        proc = run([sim, "--rules", str(MAL / rules_name), "--leads", leads_path])
        bad = check(rules_name, proc)
        if proc.returncode != 2:
            bad.append(f"expected exit 2 for invalid rules, got {proc.returncode}")
        fails += bool(bad)
        print(f"  {'ok  ' if not bad else 'FAIL'} rules      {rules_name:<24} "
              f"{'' if not bad else ' · '.join(bad)}")
    for leads_name in ["empty.csv", "binary.csv", "header_only.csv", "ragged_rows.csv"]:
        checked += 1
        proc = run([sim, "--rules", rules, "--leads", str(MAL / leads_name)])
        bad = check(leads_name, proc)
        if proc.returncode != 2:
            bad.append(f"unsafe acceptance — expected exit 2, got {proc.returncode}")
        fails += bool(bad)
        print(f"  {'ok  ' if not bad else 'FAIL'} leads      {leads_name:<24} "
              f"{'' if not bad else ' · '.join(bad)}")

    print("\nMISSING FILES AND DIRECTORIES")
    print("-" * 78)
    for label, argv in (("pii-scan", [scan, str(MAL / MISSING)]),
                        ("utm-lint", [lint, str(MAL / MISSING)]),
                        ("pii-scan dir", [scan, str(MAL)]),
                        ("reconcile", [rec, "--platform", str(MAL / MISSING), "--crm", good]),
                        ("routing", [sim, "--rules", str(MAL / MISSING), "--leads", leads])):
        checked += 1
        proc = run(argv)
        bad = check(label, proc)
        if proc.returncode != 2:
            bad.append(f"expected exit 2 for an unreadable file, got {proc.returncode}")
        fails += bool(bad)
        print(f"  {'ok  ' if not bad else 'FAIL'} {label:<14} {'':<24}"
              f"{'' if not bad else ' · '.join(bad)}")

    print("-" * 78)
    print(f"{checked - fails}/{checked} inputs handled"
          if not fails else f"{fails} of {checked} FAILED the never-crash contract")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
