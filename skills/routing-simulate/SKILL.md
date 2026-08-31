---
name: routing-simulate
description: Run lead routing rules against real leads to find dead rules, rules shadowed by a broader rule above them, leads that match nothing, and an unbalanced distribution across owners. Use when auditing lead assignment in LeanData, HubSpot, Salesforce or a custom router, before changing routing, after a territory change, or when a salesperson says they stopped receiving leads. Takes a JSON rules file and a CSV of leads, needs no API access.
---

# routing-simulate

## When to use this

- "Some leads aren't reaching anyone."
- "A rep says they stopped getting leads three weeks ago."
- Before a territory change, a headcount change, or a new segment — simulate first.
- Auditing routing you inherited, in LeanData, HubSpot, Salesforce assignment rules, or
  something someone built in a workflow tool.
- After anyone edits routing, because routing is the one system where a change is invisible
  until a person notices an absence.

Routing rules are written once, edited by four people over two years, and never tested. The
failures are all silent: nothing errors, leads simply go to the wrong place or nowhere.

## The rules format

JSON, and deliberately small. One condition string per rule: comparisons joined by `and`
and `or`, `and` binding tighter, no nesting and no parentheses. A routing language that
needs a manual does not get maintained, and a rule that cannot be written this way is one
nobody on the revenue team can read either.

```json
{
  "rules": [
    {"name": "Enterprise DACH",
     "when": "country in DE,AT,CH and employees >= 500",
     "assign": "ana"},
    {"name": "SMB inbound",
     "when": "employees < 50 or plan_interest = starter",
     "assign": "round_robin: sam, lee"}
  ],
  "default": "unassigned"
}
```

Operators: `=` `!=` `>` `>=` `<` `<=` `in` `not in` `contains` `is empty` `is not empty`.
Comparisons are numeric when both sides are numbers and case-insensitive text otherwise.
`assign` is an owner name, or `round_robin: a, b, c`.

**Transcribing rules from a real system is the work**, and it is worth doing by hand: the
act of writing them out in one file is usually where the first surprise turns up.

## How to run it

```bash
python skills/routing-simulate/scripts/simulate.py --rules routing.json --leads leads.csv [--json]
```

The leads CSV is any export with the fields the rules test — country, employee count,
source, plan, industry, whatever the routing actually uses. Real leads matter more than
many leads: a hundred rows of last month beats a synthetic thousand.

## What it finds

| Problem | Why it is silent in production |
|---|---|
| `unknown_field` | A rule tests a field no lead carries — `employes` for `employees`. It never matches and never errors. |
| `dead_rule` | A rule for a segment that does not exist in the data. Someone's plan for a market that never arrived. |
| `shadowed_rule` | The rule matches leads and wins none, because a broader rule above it takes them all. This is the expensive one and the hardest to see by reading the file. |
| `broader_rule_above` | A partial version of the same thing: a rule loses most of its matches to something above it that matches everything it matches and more. |
| `unrouted_leads` | Leads that match nothing and fall to the default. Reported with a sample, so you can see what they have in common. |
| `load_imbalance` | One owner receiving several times what the lightest receives. |

**A catch-all placed below the specific rules is correct design and is never reported**,
even though it loses most of its matches to the rules above it. That distinction is the
difference between a useful report and one that flags every well-ordered routing file.

## Reading the output

The distribution comes first, because "where do leads actually land" is the question people
have. Then every rule with how many leads it matched *in isolation* against how many it
actually *won* — the gap between those two numbers is where all the interesting failures
live.

Silence means every rule fires and every lead lands somewhere. That is a real result, and
it is worth re-running after any routing change to keep it.

## What to tell the user afterwards

1. **Unknown fields first.** They are typos, they are one-character fixes, and the rule has
   been doing nothing since the day it was written.
2. **Then shadowed rules.** Move the specific rule above the general one. Order is the
   entire semantics of a cascade and nothing in the file records the intended order.
3. **Then the unrouted leads.** Look at the sample: they usually share one attribute
   nobody wrote a rule for, and the fix is one rule rather than a redesign.
4. **Leave load balance last.** It is real but it is a tuning problem, and it moves on its
   own once the rules above are fixed.

## What it will not do

- It does not connect to any CRM or routing tool. You transcribe the rules; that is the
  point, and it is where half the findings come from.
- It does not model time — round-robin is simulated in file order, not against who was on
  holiday.
- It does not know your intent. A dead rule may be deliberate, for a market you are about
  to enter. It reports the fact and leaves the judgement to you.

## Fixtures and tests

```bash
python tests/test_routing_simulate.py
```

Two routing files over the same thirty leads: one with four planted faults and the repaired
version of it. The repaired one must be **completely silent** — a linter that still
complains after you have fixed everything it asked for is one nobody fixes anything for.
