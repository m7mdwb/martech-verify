# martech-verify — design

## The gap this exists to fill

About 150 marketing skills are published for Claude across the three largest public
collections. Two things are true of nearly all of them:

1. **The free ones give advice; the ones that touch real data need a vendor account.**
   Schema references, naming conventions, checklists, templates. The moment a skill
   reads your actual numbers it wants an API key, an OAuth grant, or a subscription.
2. **Every audit stays inside one platform's own configuration.** A GTM audit reads the
   GTM container. A GA4 audit reads GA4 settings. Nothing crosses a system boundary.

The second one matters more than it sounds, because the expensive failures in marketing
measurement are invisible from inside a single platform's config:

- A tag-manager trigger whose regex matches too broadly. The container is *valid* —
  correct tags, no orphans, clean naming. It just fires three to four times more often
  than it should, and the top of the funnel looks healthier than it is for months.
- A phone system reporting 331 call rows against 114 real calls. Same class of bug, and
  no amount of reading the phone system's own settings finds it.
- A cost-per-qualified-lead definition that silently under-counts. The platform is doing
  exactly what it was told; the instruction was wrong.

None of those are configuration errors. They are disagreements between what a system
reports and what actually happened, and you only find them by putting two systems'
numbers next to each other.

## What this repo is

Verification skills for marketing and revenue operations that

- **run on exports, not API keys** — a CSV you already have, not a vendor grant,
- **cross system boundaries** where the interesting failures live,
- **have zero runtime dependencies** — Python standard library only, and
- **never print raw personal data**, including in their own reports.

Not: another campaign builder, another copywriter, another single-platform audit.

## The four skills

Shipped in this order. Smallest first, so the repo is never a half-finished shell, and
hardest last, so the design has time to settle.

### 1. `pii-scan` — personal data leaking into analytics

**Problem.** Sending personal data to Google Analytics violates its terms and Google will
delete a property's data over it. It happens by accident constantly: a form that submits
over GET so the email lands in the query string, a page path carrying a customer name, a
tag-manager variable that captures a whole form field. Nobody audits for it, because
checking means reading thousands of URLs.

**In:** any export containing URLs, page paths or event parameters — GA4 exploration
export, BigQuery export, a server access log, or a plain list of URLs.

**Out:** every leak found, grouped by parameter and by kind, with counts, redacted
samples, a severity, and the specific remediation for that kind.

**Refuses to:** print an unredacted value, guess at national ID formats it cannot verify,
or claim a finding is confirmed when only the parameter *name* looked suspicious.

### 2. `utm-lint` — campaign tagging that drifted

**Problem.** Every collection ships UTM *advice*. None of them will look at the 4,000
tagged URLs you actually have and tell you which ones broke the taxonomy.

**In:** a URL corpus plus an optional taxonomy definition.

**Out:** casing inconsistencies, near-duplicate campaign names, unknown sources, missing
required parameters, parameters that will collapse into each other in reporting, and a
corrected URL for each.

### 3. `conversion-reconcile` — the flagship

**Problem.** The platform says 400 conversions. The CRM says 260. Everyone argues about
attribution windows and nobody finds the bug.

**In:** a platform export and a CRM export, plus the join key.

**Out:** the divergence, and — the actual work — the *shape* of that divergence matched
against a ranked list of named causes:

| Shape | Likely cause |
|---|---|
| flat ~2.0x across everything | duplicate stream, or a second container on the page |
| inflated on one path only | a trigger matching too broadly |
| ~2x on one event only | pixel and server-side API firing without deduplication |
| step change on one date | consent gating changed, or a tag shipped |
| consistent one-day offset | timezone or attribution-window mismatch |
| platform above CRM on paid only | bot or invalid traffic |

### 4. `routing-simulate` — lead routing before it costs you a quarter

**Problem.** Routing rules are written once, edited by four people, and never tested. Dead
ends and overlapping conditions are found by a salesperson noticing they got nothing.

**In:** a rules file and a CSV of leads.

**Out:** where each lead lands, which rules never fire, which leads match nothing, which
rules overlap, and the distribution across owners.

**Hardest of the four**, because the rules format is the whole problem: expressive enough
to be worth using, simple enough to need no manual.

## Shared spine

**Revised once, at the second skill.** The plan said `lib/` would be imported. It cannot be:
a skill has to work when someone copies one folder into `.claude/skills/`, and an import
reaching outside that folder breaks the moment they do. Installing a package would break
"no dependencies". So `lib/_shared.py` is the source of truth and `tools/sync_shared.py`
vendors a copy into each skill's `scripts/` directory, with `tests/test_shared_sync.py`
failing if any copy drifts. Duplication in the repo, in exchange for folders that work
alone, with a test making the trade safe.

`lib/` carries what all four need, built once:

- **loader** — read real-world CSV, TSV, JSON-lines and plain lists without falling over
  on encoding, BOMs, or a column named something unexpected.
- **fixtures generator** — synthetic datasets with planted defects, so every skill is
  demonstrable and testable without anyone's real data.
- **report** — one output shape: a readable terminal table, and `--json` for machines.

## Conventions

- Python 3.9+, standard library only. No install step.
- Every skill exits non-zero when it finds something, so it can run in CI.
- Every skill ships a fixture with known planted defects, and a test that asserts it finds
  exactly those.
- No skill ever transmits data anywhere. Everything runs locally on a file you point at.
