#!/usr/bin/env python3
"""Copy lib/_shared.py into every skill's scripts/ directory.

Skills must work when someone drops one folder into `.claude/skills/`, so they cannot
import from outside themselves. Vendoring is the price of that, and this script plus
tests/test_shared_sync.py is what stops the copies drifting.

    python tools/sync_shared.py            # write the copies
    python tools/sync_shared.py --check    # exit 1 if any copy is stale
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "lib" / "_shared.py"
BANNER = ("# ⚠️ VENDORED COPY — do not edit. Edit lib/_shared.py and run "
          "python tools/sync_shared.py\n")


def targets() -> list[pathlib.Path]:
    """Every skill that has a scripts/ directory — not every skill that already has a copy.

    Globbing for existing _shared.py files looked equivalent and was not: a brand-new skill
    has no copy yet, so it was silently skipped and only failed at import time.
    """
    return sorted(p / "scripts" / "_shared.py"
                  for p in (ROOT / "skills").iterdir() if (p / "scripts").is_dir())


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    if not SOURCE.exists():
        print(f"missing source: {SOURCE}", file=sys.stderr)
        return 2

    wanted = BANNER + SOURCE.read_text(encoding="utf-8")
    stale = []
    for target in targets():
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == wanted:
            continue
        stale.append(target)
        if not check:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(wanted, encoding="utf-8", newline="\n")

    rel = [str(p.relative_to(ROOT)).replace("\\", "/") for p in stale]
    if check:
        for r in rel:
            print(f"STALE {r}")
        print("all vendored copies match lib/_shared.py" if not stale
              else f"{len(stale)} stale copy/copies — run python tools/sync_shared.py")
        return 1 if stale else 0

    for r in rel:
        print(f"wrote {r}")
    print("up to date" if not stale else f"synced {len(stale)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
