#!/usr/bin/env python3
"""The malformed fixtures' exact bytes are part of their behavior contract."""
from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parent.parent
MAL = ROOT / "fixtures" / "malformed"

checks = [
    ("crlf is really CRLF",
     lambda: b"\r\n" in (MAL / "crlf.csv").read_bytes()
     and b"\n" not in (MAL / "crlf.csv").read_bytes().replace(b"\r\n", b"")),
    ("BOM is present",
     lambda: (MAL / "bom.csv").read_bytes().startswith(b"\xef\xbb\xbf")),
    ("cp1252 is not UTF-8",
     lambda: b"\xe9" in (MAL / "cp1252.csv").read_bytes()
     and b"\xc3\xa9" not in (MAL / "cp1252.csv").read_bytes()),
    ("no-trailing-newline really has none",
     lambda: not (MAL / "no_trailing_newline.csv").read_bytes().endswith((b"\n", b"\r"))),
    ("binary fixture has PNG signature",
     lambda: (MAL / "binary.csv").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")),
    ("NUL fixture contains a NUL",
     lambda: b"\x00" in (MAL / "nul_bytes.csv").read_bytes()),
    ("large field exceeds Python's old CSV limit",
     lambda: max(map(len, (MAL / "huge_field.csv").read_bytes().splitlines())) > 131_072),
]

failed = []
for name, check in checks:
    try:
        ok = check()
    except Exception as exc:  # noqa: BLE001 - a broken fixture should fail this test cleanly
        ok = False
        failed.append(f"{name}: {exc}")
    if not ok and not any(item.startswith(name + ":") for item in failed):
        failed.append(name)
    print(f"{'ok  ' if ok else 'FAIL'} {name}")

print(f"{len(checks) - len(failed)}/{len(checks)} byte invariants preserved"
      if not failed else f"FAILED: {', '.join(failed)}")
raise SystemExit(1 if failed else 0)
