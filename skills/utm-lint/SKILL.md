---
name: utm-lint
description: Lint a real corpus of tagged URLs against the way analytics platforms actually read them. Use when campaign reporting looks fragmented, when traffic is landing in Unassigned, before rolling out a UTM taxonomy, or when auditing an account someone else tagged. Finds case drift, near-duplicate campaign names, mediums that no channel grouping recognises, self-referrals, auto-tagging conflicts and personal data in campaign parameters. Runs on a CSV of URLs, needs no API access.
---

# utm-lint

## Agent workflow

This is an executable audit, not a taxonomy-writing exercise. When a usable URL export is
available, run the bundled linter instead of responding with generic UTM advice.

1. Identify the export containing full destination or landing-page URLs. If none is
   available, ask for that one file and explain that CSV, JSON Lines, a log, or one URL per
   line all work.
2. Resolve `scripts/lint.py` relative to this `SKILL.md` and run it with an available
   Python 3 interpreter. In Claude Code, `${CLAUDE_SKILL_DIR}` is this skill directory;
   in other hosts use the skill path supplied by the host. Quote every path.
3. Pass `--site DOMAIN` when the user's own domain is known. If it is not known, do not
   block the rest of the audit; state that self-referrals were not evaluated. Let column
   auto-detection run before adding `--column NAME`.
4. Interpret exit codes exactly: `0` means no configured rule fired on the supplied URLs,
   `1` means findings were produced, and `2` means the input could not support a trustworthy
   audit. On `2`, relay the actionable error and never describe the file as clean.
5. Group the result into privacy/attribution risks, taxonomy fragmentation, and mechanical
   cleanup. Preserve the tool's `should be:` values and distinguish facts found in the file
   from recommendations.

Never rewrite the user's source export or claim that historical analytics data was fixed.
If the user needs help preparing an export, read [references/input-guide.md](references/input-guide.md).

## When to use this

- "Why is one campaign showing up as three rows?"
- "Why is so much of our traffic in Unassigned?"
- "We're rolling out a new UTM convention" — measure the drift before writing the rules.
- Inheriting an account: this is the fastest read on how disciplined the previous team was.
- After an email send, a paid launch, or any hand-off to an agency.

Every marketing skill collection publishes UTM *advice* — naming conventions, a builder, a
taxonomy template. None of them will look at the URLs you already have.

## How to run it

```bash
python skills/utm-lint/scripts/lint.py <export> [--site yourdomain.com] [--column NAME] [--json] [--fail-on critical|high|medium]
```

Pass `--site` whenever you can. It is what turns "someone tagged a link with our own
domain" from invisible into a finding, and internal tagging is the single most expensive
mistake in this list because it reassigns conversions away from the channel that earned
them.

Where to get the corpus: GA4 Reports > Acquisition > Traffic acquisition with page location,
a BigQuery query over `page_location`, a server access log, your email platform's link
export, or the ad platforms' final URLs.

## The checks, and why each one costs money

| Rule | What it costs you |
|---|---|
| `case_drift` | `LinkedIn` and `linkedin` are two rows. Every campaign total is understated. |
| `near_duplicate` | `q3-demand`, `q3_demand`, `Q3 Demand` — one campaign, three lines, no total. |
| `unmapped_medium` | A medium no channel definition recognises lands in **Unassigned**, so the spend disappears from every channel report. `newsletter` is the classic: it feels like a medium and is not one. |
| `missing_required` | A campaign with no source or medium cannot be grouped with the rest of itself. |
| `whitespace` | A leading space produces a value that looks identical in the report and is not. |
| `duplicate_param` | The same parameter twice: which one wins is platform-dependent, so the answer is unreliable. |
| `self_referral` | Your own domain as `utm_source` on an internal link restarts the session and steals the conversion from the channel that actually earned it. |
| `autotagging_conflict` | A `gclid` beside manual tags. With auto-tagging on the click id wins, so the taxonomy in your reports is not the one you designed. |
| `source_equals_medium` | Usually one field filled in by mistake. |
| `empty_param` | Present-but-empty is not the same as absent; it can create a blank dimension value. |
| `pii_in_utm` | An email address in `utm_content`, which email tools produce when a merge field ends up in the link. A privacy problem before it is a tagging one. |

## Reading the output

Findings are grouped and counted, and anything fixable carries a `should be:` line with the
corrected value. For `case_drift` and `near_duplicate` the suggestion is the **most common
form already in your data**, lower-cased — the taxonomy you actually have rather than one
invented for you.

Nothing correct is reported. Clean tagging produces silence, which is the property that
makes a linter worth running more than once.

## What to tell the user afterwards

Fix in this order, because later steps are wasted without earlier ones:

1. **Stop the source of new bad tags.** A link builder, a template, an agency brief. Drift
   comes from people typing links by hand.
2. **Decide the canonical value for each cluster** the linter found, and apply it going
   forward. History cannot be rewritten in the platform — but if warehouse or BigQuery data
   is available, a mapping table applied at query time recovers the historical totals.
3. **Turn off manual tagging on Google Ads links** if auto-tagging is on, rather than
   maintaining both.
4. **Remove the tags from internal links** entirely. Internal campaign tagging should be
   replaced by a separate internal-promotion parameter that does not reset attribution.

## What it will not do

- It does not fix your URLs. It tells you what each should be and leaves the edit to you.
- It does not know your taxonomy. It infers the canonical form from what is most common in
  your own corpus rather than imposing a convention.
- It does not read your analytics account. It reads a file, on purpose.
- Channel classification mirrors the standard default channel definitions. A property with
  custom channel groups may legitimately use mediums flagged here as unmapped.

## Tests

```bash
python tests/test_utm_lint.py
```

Fourteen planted problems in the fixture; the test asserts exactly those are found and
nothing else, that correctly tagged URLs stay silent, and that the email planted in
`utm_content` is never printed in full.
