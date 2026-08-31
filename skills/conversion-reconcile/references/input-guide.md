# Preparing conversion reconciliation exports

Provide two row-level files for the same period: one from the marketing or analytics
platform and one from the CRM or finance system you treat as the source of truth.

## Hard requirement: a shared identifier

Every row must represent one conversion and both files must carry the same stable key, for
example `transaction_id`, `order_id`, `conversion_id`, `lead_id`, `deal_id`, `event_id`,
`gclid` or `email`.

```csv
# platform.csv
date,transaction_id,event_name,source,medium,page_path
2026-08-01,T1001,purchase,google,cpc,/checkout/success
```

```csv
# crm.csv
created_date,transaction_id,stage,source,owner
2026-08-01,T1001,closed-won,google,ana
```

If the same key has different header names in the two systems, make copies of the exports
and rename those headers to one shared name. Never alter the source files. Aggregated daily
or campaign totals cannot be joined and are not valid input for this skill.

## Optional columns that improve the diagnosis

- Date on both sides: day offsets and step changes.
- Page path, landing page or event name: excess concentrated on one trigger.
- Source, medium or campaign: disagreement concentrated in one channel.
- Owner or stage: retained for context even though it does not drive every detector.

Use the same date window and timezone where possible. The reconciler can diagnose some
offsets, but comparing different reporting periods creates a gap with no useful cause.
