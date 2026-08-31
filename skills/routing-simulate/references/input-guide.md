# Preparing a routing simulation

The simulator needs a JSON description of the ordered rules and a CSV containing real
recent leads. It reads both locally and never changes production routing.

## Leads CSV

Use one lead per row. Include every field referenced by a rule:

```csv
lead_id,country,employees,industry,source,plan_interest
L001,DE,1200,software,webinar,enterprise
L002,ES,25,retail,demo,starter
```

Field names are matched without regard to case. Values are compared as numbers when both
sides are numeric and as case-insensitive text otherwise.

## Rules JSON

```json
{
  "rules": [
    {
      "name": "Enterprise DACH",
      "when": "country in DE,AT,CH and employees >= 500",
      "assign": "ana"
    },
    {
      "name": "SMB inbound",
      "when": "employees < 50 or plan_interest = starter",
      "assign": "round_robin: sam, lee"
    }
  ],
  "default": "unassigned"
}
```

Rule order is significant: the first matching rule wins. Supported operators are `=`,
`!=`, `>`, `>=`, `<`, `<=`, `in`, `not in`, `contains`, `is empty`, and `is not empty`.
`and` binds tighter than `or`; nesting and parentheses are intentionally unsupported.

When transcribing from a CRM or routing product, work from a copy and record assumptions.
Vendor-specific behavior such as schedules, rep availability, capacity and territory
objects is outside this DSL unless represented explicitly in the lead fields and rules.
