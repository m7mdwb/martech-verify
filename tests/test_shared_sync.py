#!/usr/bin/env python3
"""The vendored copies of lib/_shared.py must match the source.

Skills are copied into .claude/skills/ as single folders, so each one carries its own copy
of the shared helpers. That is a deliberate trade — droppable folders in exchange for
duplication — and this test is the thing that makes the trade safe. Without it the copies
drift within a month and two skills quietly disagree about how to read a CSV.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

result = subprocess.run([sys.executable, str(ROOT / "tools" / "sync_shared.py"), "--check"],
                        capture_output=True, text=True)
print(result.stdout.strip() or result.stderr.strip())
if result.returncode:
    print("\nrun: python tools/sync_shared.py")
raise SystemExit(result.returncode)
