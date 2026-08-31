---
name: conversion-reconcile
description: Reconcile a platform's conversion export against the CRM and name the likely cause of the gap. Use when GA4, Google Ads, Meta or a tag manager reports a different number of conversions from the CRM or the finance system, when a dashboard is not trusted, or when a team is arguing about attribution windows. Joins the two exports, measures the shape of the disagreement, and returns ranked causes with the evidence that fired each one. Needs no API access.
---

# conversion-reconcile

## Agent workflow

This is an executable comparison. When two usable exports are available, run the bundled
reconciler instead of debating attribution in the abstract.

1. Identify which file is the marketing/analytics platform export and which is the CRM or
   finance source of truth. Inspect filenames and headers first; ask only when the roles are
   genuinely ambiguous.
2. Confirm both files contain row-level conversions and a shared identifier. Aggregated
   daily totals cannot support the join this skill makes. Read
   [references/input-guide.md](references/input-guide.md) when the user needs an export recipe.
3. Resolve `scripts/reconcile.py` relative to this `SKILL.md` and run it with an available
   Python 3 interpreter. In Claude Code, `${CLAUDE_SKILL_DIR}` is this skill directory;
   in other hosts use the skill path supplied by the host. Quote every path. Let key
   auto-detection run first; pass `--key NAME` when the shared field has another name.
4. Interpret exit codes exactly: `0` means no material divergence shape was diagnosed, `1`
   means one or more evidence-backed diagnoses were produced, and `2` means the inputs could
   not support a trustworthy comparison. On `2`, relay the corrective message and stop.
5. Report the join quality and ratio before the ranked causes. Lead with the top cause's
   evidence and next check, but retain credible secondary causes. Never turn a heuristic
   confidence weight into a calibrated probability.

Do not modify either export, imply that attribution was modelled, or claim the tracking is
correct merely because no known divergence shape fired.

## When to use this

- "The platform says 400 conversions, the CRM says 260."
- "Sales don't trust the marketing dashboard."
- "Our cost per acquisition looks too good."
- Before presenting any number to a board, an investor or a budget owner.
- After a tracking migration, a consent tool rollout, or a move to server-side tagging.

Configuration audits cannot answer these. The container can be entirely valid — correct
tags, no orphans, clean naming — while the numbers coming out of it are wrong. That failure
only becomes visible when two systems are put side by side.

## How to run it

```bash
python skills/conversion-reconcile/scripts/reconcile.py \
    --platform ga4_conversions.csv \
    --crm crm_deals.csv \
    [--key transaction_id] [--json]
```

**What each file needs.** A shared identifier is the only hard requirement: a transaction
id, order id, lead id, deal id or click id present on both sides. The column is
auto-detected; pass `--key` when the shared column uses an unusual name or the guess is
wrong. If the two exports use different headers for the same identifier, rename those
headers to one shared name in copies of the exports first.

Everything else is optional and each one buys another detector:

| Column | What it unlocks |
|---|---|
| a date on both sides | timezone and attribution-window mismatch, step changes |
| `page_path` or `landing_page` | a trigger firing on pages it should not |
| `event_name` or `conversion_action` | one event double-counted while the rest are fine |
| `source` / `medium` / `campaign` | excess concentrated on paid traffic |

## What it looks for

Each detector matches a *shape*, not a number, and every one reports the evidence that
fired it:

| Cause | Signature |
|---|---|
| `join_key_mismatch` | Both sides are mostly strangers. Ranked first when it fires, because every other diagnosis is noise until the join works. |
| `duplicate_events` | The same id appears more than once on the platform side, usually exactly twice. |
| `trigger_matching_too_broadly` | The excess piles onto one page path or one event, while everything else reconciles. |
| `timezone_or_window_mismatch` | Totals agree, days do not, and shifting one side by a day collapses the disagreement. |
| `step_change_on_a_date` | The ratio was stable, then changed, and never went back. |
| `duplicate_stream_or_container` | Everything is inflated by the same round multiple, evenly, across unrelated dimensions. |
| `platform_undercount` | The CRM has conversions the platform never saw. |

## Reading the output

Diagnoses are ranked by **how well the divergence fits that shape** — not by how likely the
fix is to work, and not by severity. The confidence number is a goodness of fit.

**Read the evidence line before acting on the label.** Every diagnosis states the counts
and shares that produced it, so it can be checked against the data rather than believed.

More than one can be true at once, and often is: a duplicated event will also produce a
flat 2x ratio, so both appear, most specific first.

Silence is a real answer. When nothing fits, the tool says the two exports do not disagree
in any way it can name — which is deliberately not the same claim as "your tracking is
correct."

## What to tell the user afterwards

1. **Fix the join first** if `join_key_mismatch` fired. Nothing else is readable until it
   is gone.
2. **Take the top diagnosis to the place the evidence points**, not to the whole stack. If
   the excess is on one path, open that one tag.
3. **Re-run after the fix.** The ratio moving toward 1.0 is the only proof the change
   worked, and it is cheap to check because the tool needs nothing but two fresh exports.
4. **Historical data usually cannot be repaired** in the platform. Say so plainly rather
   than implying a backfill is coming; where a warehouse export exists, the correction can
   be applied at query time instead.

## What it will not do

- It does not connect to anything. Two CSVs, locally.
- It does not model attribution. It compares what two systems recorded about the same
  identified conversions, which is a different and more answerable question.
- It cannot see a conversion neither system recorded.
- It will not attribute a cause without evidence. Where the shape is ambiguous it returns
  several candidates rather than picking one, and where nothing fits it returns none.

## Fixtures and tests

```bash
python tools/make_fixtures.py          # regenerate (seeded, deterministic)
python tests/test_conversion_reconcile.py
```

Four synthetic scenarios ship with the repo: one clean, one with duplicated events, one
with a trigger firing on a single path, one with a one-day timezone offset. The test
asserts each gets the **right** top diagnosis and that the three faulty ones get three
**different** ones — a detector that always answered "duplicate events" would pass a
single-scenario test and be worthless.
