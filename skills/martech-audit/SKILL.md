---
name: martech-audit
description: Route local marketing and revenue exports to the right evidence-based checks for PII leakage, broken UTM tagging, conversion gaps, or lead-routing defects. Use when someone says "audit my marketing data," provides unfamiliar exports, or is unsure which martech-verify skill applies. Prefer the named specialist when the request is already specific.
---

# martech-audit

Use this as the front door to the martech-verify bundle. It chooses and runs the existing
specialist audits; it is not a fifth detector and must not invent checks of its own.

## Workflow

1. Inventory only the files the user supplied or explicitly placed in scope. Do not search
   unrelated directories, upload files, or paste raw records into the conversation.
2. Use filenames, extensions and headers to classify the inputs. Avoid reading or printing
   data rows merely to decide which audit applies.
3. Select the smallest useful set of specialists:

   | Input or question | Specialist |
   |---|---|
   | URLs, page locations, event values, logs, privacy concern | `pii-scan` |
   | Tagged/final URLs, campaign taxonomy, Unassigned traffic | `utm-lint` |
   | Platform conversions plus CRM/finance conversions | `conversion-reconcile` |
   | Ordered routing rules plus real leads | `routing-simulate` |

   A broad audit of a URL export may warrant both `pii-scan` and `utm-lint`. Two conversion
   exports may also contain URLs worth scanning, but do not expand a narrow request without
   explaining why the extra read-only check is relevant.
4. Resolve the selected sibling skill directory from the installed bundle, read that
   skill's `SKILL.md`, and follow its agent workflow. In a normal bundle installation the
   sibling skills sit beside this directory under `skills/`. If they are absent because
   this folder was copied alone, tell the user to install the full martech-verify bundle.
5. Respect each tool's exit codes. Exit `2` is unusable input, not a clean result. Relay the
   corrective message and do not continue drawing conclusions from that file.
6. Combine completed results into three plain-language sections:
   - **Fix now:** verified privacy exposure, broken attribution, or leads going nowhere.
   - **Investigate:** evidence-backed but ambiguous diagnoses and name-only signals.
   - **Coverage:** which files, periods and checks ran, plus what the audit could not see.

## Hand off a proposed fix

When the user wants to change CRM or marketing records in response to a finding, keep the
audit read-only. Produce a compact change brief containing the finding, supporting counts,
target record scope, intended fields, invariants that must remain true, and the report file
that contains the evidence. If `$martech-change-guard` is installed, offer to hand that
brief and report to it. Invoke the guard only when the user asks to plan the fix.

The handoff is evidence, not authorization. MarTech Change Guard still requires matching
current and proposed exports, applies its own policy, and keeps any live write outside the
guard. When creating its plan, pass the audit report with `--evidence` so the changeset binds
the exact upstream evidence by SHA-256.

Never modify source exports or production systems. Do not call the result a compliance
certification, a complete tracking audit, or proof that systems are correct. The conclusion
is limited to the supplied files and the deterministic checks that actually ran.

## If no usable files are present

Ask one focused question: which outcome matters now—privacy leakage, campaign tagging,
conversion disagreement, or lead routing? Then request only the file or pair of files the
chosen specialist requires. Do not make the user learn all four tools before they can begin.
