# Contributing

Martech Verify accepts focused fixes and detectors that strengthen its core promise:
evidence-based verification over local marketing and revenue exports, without connectors,
accounts or production-system access.

## Before opening a pull request

- Use an issue for behavior changes and new detectors. Small documentation corrections can
  go directly to a pull request.
- Reproduce bugs with the smallest synthetic input possible. Never submit customer data,
  production URLs, credentials or real personal information.
- Preserve the runtime baseline: Python 3.9+, standard library only.
- Keep every specialist installable as a standalone folder. It must not import from outside
  its own skill directory.

## What makes a detector belong here

A proposed detector should meet all of these tests:

1. It reads an export someone can already obtain without granting this project access.
2. It verifies data or behavior instead of returning generic marketing advice.
3. It has a narrow, explainable contract and evidence a human can independently inspect.
4. False positives are controlled and suspected evidence is not presented as verified.
5. Synthetic fixtures can prove both the faulty and clean cases deterministically.
6. It does not require a connector, API key, subscription, service or agent framework.

An additional prompt-only skill, dashboard, warehouse engine or vendor-specific connector
is unlikely to fit this repository even when it would be useful elsewhere.

## Development workflow

Run the complete suite from the repository root:

```bash
python tests/run_all.py
python tools/sync_shared.py --check
python tools/make_terminal_svg.py --check
python tools/make_demo_gif.py --check
```

When editing `lib/_shared.py`, run `python tools/sync_shared.py` to refresh the standalone
copies before testing. `tools/make_fixtures.py` must reproduce the committed conversion
fixtures without a diff.

Every command-line tool follows the same exit-code contract:

- `0`: the supplied input produced no reportable findings;
- `1`: findings were produced;
- `2`: the input could not support a trustworthy result.

Exit `2` must never be converted into a clean verdict. Errors must be actionable and no
input bytes may cause a traceback. Any value identified as sensitive must remain redacted
in text, JSON, examples, locations and error messages.

## Pull requests

Explain the user-visible problem, the evidence behind the change, and the limits of what
the change proves. Add or update a planted fixture and regression test for behavior changes.
Keep generated assets synchronized, and call out any deliberate non-goal affected by the
proposal.
