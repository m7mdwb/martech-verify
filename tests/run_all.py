#!/usr/bin/env python3
"""Run every test in this repo. No framework, no dependencies.

    python tests/run_all.py
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = sorted(p for p in (ROOT / "tests").glob("test_*.py"))

failed = []
for test in TESTS:
    r = subprocess.run([sys.executable, str(test)], capture_output=True, text=True)
    tail = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    summary = tail[-1] if tail else "(no output)"
    print(f"{'PASS' if r.returncode == 0 else 'FAIL'}  {test.name:<26} {summary}")
    if r.returncode:
        failed.append(test.name)
        print(r.stdout[-1500:])

print("-" * 70)
print(f"{len(TESTS) - len(failed)}/{len(TESTS)} test files passed"
      if not failed else f"FAILED: {', '.join(failed)}")
raise SystemExit(1 if failed else 0)
