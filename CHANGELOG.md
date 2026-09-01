# Changelog

## v0.3.0 — 2026-09-01

- Connect `$martech-audit` findings to MarTech Change Guard through a compact change brief.
- Define the shared diagnose → plan → approve → verify safety loop.
- Coordinate marketplace versions so installing from either repository exposes both tools.
- Add the real-output connected walkthrough and MP4 recording.
- Standardize the human-facing product name as MarTech Verify.

## v0.2.0 — 2026-09-01

The agent-ready release. MarTech Verify is now installable as a Codex or Claude Code bundle
and has one plain-language front door for marketers who do not know which check to run.

### Added

- `martech-audit`, an umbrella skill that classifies supplied exports, runs the smallest
  useful set of specialist checks, and reports **Fix now**, **Investigate**, and **Coverage**.
- Codex plugin metadata and per-skill UI metadata.
- A Claude Code plugin manifest and GitHub-hosted marketplace.
- Marketer-oriented input guides with minimal export examples for every specialist.
- Package-layout tests that keep both distribution formats and all five skills in sync.
- A generated README animation derived from all four tools' real fixture output.

### Improved

- All specialist skills now instruct the host agent to run their deterministic tool,
  interpret exit codes safely, preserve evidence boundaries, and avoid changing source data.
- The README now leads with installation, usable prompts, required exports, and the privacy
  model instead of assuming command-line knowledge.
- Routing field names are evaluated case-insensitively, consistent with validation.
- GitHub Actions now uses the current Node 24-based official actions.

### Security

- UTM JSON output now redacts emails inside URL examples, including percent-encoded email
  addresses. A regression test covers the raw and encoded forms.
- Untrustworthy inputs continue to fail closed with exit code `2`; the adversarial suite
  covers 60 malformed or hostile files across all four tools.

### Compatibility and boundaries

- Python 3.9 or newer; runtime tools use only the standard library.
- No connectors, API keys, telemetry, background service, or production-system writes.
- Inputs are local exports and conclusions are limited to the supplied files and period.
- This release does not claim compliance certification or warehouse-scale processing.
