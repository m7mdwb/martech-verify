---
name: pii-scan
description: Find personal data leaking into analytics URLs, page paths and event parameters. Use when auditing GA4, Google Tag Manager, server logs or any tracking export for emails, phone numbers, card numbers, IBANs, tokens or names that should never have reached an analytics platform. Runs on a CSV or log file you already have, needs no API access, and never prints an unredacted value.
---

# pii-scan

## When to use this

Reach for it when someone asks any of these:

- "Are we sending PII to Google Analytics?"
- "We got a privacy complaint / a DPA question about our tracking."
- "We're about to switch on server-side tagging" — check what is already in the URLs first.
- "Audit our GA4 setup" — configuration audits do not read values, so they never find this.
- Before a migration, a new consent tool, or handing an analytics property to an agency.

## Why it matters

Google's terms prohibit sending personally identifiable information to Google Analytics,
and Google will delete a property's data over a violation. It rarely happens deliberately.
It happens because a form submits over GET, or a tag-manager variable captures the whole
field, or a confirmation page puts the customer's name in the path. Nobody checks, because
checking means reading thousands of URLs by hand.

## How to run it

```bash
python skills/pii-scan/scripts/scan.py <export> [--column NAME] [--json] [--fail-on critical|high|medium]
```

It accepts whatever the user actually has:

| Source | How to get it |
|---|---|
| GA4 | Reports > Engagement > Pages and screens, export to CSV. Or an Explore with page path and event parameters. |
| BigQuery (GA4 export) | Any query returning `page_location` or event parameter values, exported as CSV or JSON lines. |
| Server logs | The access log itself. The request column is picked up automatically. |
| Tag manager | A Preview-mode export, or any list of URLs. |
| Anything else | One URL per line in a text file. |

The column is auto-detected from the header. Pass `--column` when the file has an unusual
name for it, and `--json` when the output feeds something else.

## Reading the output

Every finding carries a signal marker, and the distinction matters:

- `!` **value verified** — the value itself is personal data. The email parses, the card
  passes Luhn, the IBAN checksum is correct. This is not a guess.
- `?` **parameter name only** — the parameter is called `email` or `fname`, and the value
  was not independently verifiable. Worth investigating, not worth an incident report.

Severities: `critical` is verified personal data or a credential. `high` is a strong name
signal or a documented test card. `medium` is an uncorroborated pattern, or a PII-named
parameter that is currently empty — which still means the plumbing exists and will carry a
real value the first time someone fills that field in.

## What to tell the user afterwards

Lead with the fix, not the count. The scanner prints remediation for each kind it found;
the ordering of those steps is the important part and it is always the same:

1. **Stop it at the source.** A form that submits over GET, a variable that captures too
   much, a redirect that carries a parameter through. Until that is fixed, everything else
   is cleanup.
2. **Then configure the platform.** GA4's Redact data setting for email and phone, and the
   URL query parameter exclusion list. Both are second lines of defence — they only catch
   what they recognise.
3. **Then decide about the data already collected.** Card numbers, IBANs and credentials
   are an incident, not a settings change: the value has also reached server logs, any CDN
   in front of them, and the browser history of the person who typed it.

## What it will not do

- It does not read your GA4 property. It reads a file. That is deliberate — the whole
  point is that it needs no access grant, no OAuth, and no vendor subscription.
- It does not print unredacted values, in the table, the locations, or the JSON.
- It does not claim a finding is confirmed when only the parameter name looked suspicious.
- It cannot tell you the scan is complete. It tells you what is in the export you supplied.
  A one-month export answers a one-month question.
- It does not recognise national identity number formats, because verifying them properly
  is country-specific and a guess here would produce false alarms about salaries, invoice
  numbers and order references.

## Tests

```bash
python tests/test_pii_scan.py
```

The fixture carries twelve planted defects and the test asserts the scanner finds exactly
those and invents nothing. It also asserts that no personal value from the fixture appears
in full anywhere in the report — that test failed on first run and caught the scanner
reprinting a card number that sat in a URL path.
