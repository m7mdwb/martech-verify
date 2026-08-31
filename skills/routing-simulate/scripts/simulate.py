#!/usr/bin/env python3
"""Run your lead routing rules against real leads before a salesperson finds the hole.

Routing rules are written once, edited by four people over two years, and never tested.
Dead rules, rules shadowed by a broader rule above them, and leads that match nothing are
discovered when somebody notices they stopped getting leads — usually a quarter late.

    python simulate.py --rules routing.json --leads leads.csv
    python simulate.py --rules routing.json --leads leads.csv --json

Exit codes: 0 no problems · 1 problems found · 2 could not read input.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

# Vendored into this folder by tools/sync_shared.py so the skill works when copied alone.
from _shared import LoadError, load_rows, wrap, use_utf8_stdout  # noqa: E402

# --------------------------------------------------------------------------------------
# The rules format
#
# Deliberately small. A routing DSL that needs a manual does not get maintained, and the
# rules people actually write are "this field, this comparison, this value", joined by and
# and or. So: OR of ANDs, no nesting, no parentheses. If a rule cannot be expressed here it
# is a rule nobody on the revenue team can read either.
#
#   {"rules": [
#       {"name": "DACH enterprise",
#        "when": "country in DE,AT,CH and employees >= 500",
#        "assign": "ana"},
#       {"name": "SMB",
#        "when": "employees < 50 or plan = starter",
#        "assign": "round_robin: sam, lee"}
#   ], "default": "unassigned"}
# --------------------------------------------------------------------------------------

OPERATORS = ("not in", "in", "contains", ">=", "<=", "!=", ">", "<", "=",
             "is not empty", "is empty")


class RuleError(ValueError):
    pass


def parse_condition(text: str):
    """One 'field op value' clause into (field, op, value)."""
    t = " ".join(text.split())
    low = t.lower()
    for op in ("is not empty", "is empty"):
        if low.endswith(op):
            return t[: -len(op)].strip(), op, ""
    for op in OPERATORS:
        if op in ("is empty", "is not empty"):
            continue
        idx = low.find(f" {op} ")
        if idx != -1:
            return t[:idx].strip(), op, t[idx + len(op) + 2:].strip()
    raise RuleError(f"could not read condition: {text!r}. "
                    f"Expected 'field op value' using one of: {', '.join(OPERATORS)}")


def parse_when(when: str):
    """'a and b or c' -> [[a, b], [c]]. AND binds tighter than OR, as everyone expects."""
    groups = []
    for disjunct in when.split(" or "):
        clauses = [parse_condition(c) for c in disjunct.split(" and ") if c.strip()]
        if clauses:
            groups.append(clauses)
    if not groups:
        raise RuleError(f"empty condition: {when!r}")
    return groups


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def evaluate(clause, lead: dict) -> bool:
    field, op, expected = clause
    actual = (lead.get(field) or "").strip()

    if op == "is empty":
        return actual == ""
    if op == "is not empty":
        return actual != ""
    if op in ("in", "not in"):
        options = {o.strip().lower() for o in expected.split(",") if o.strip()}
        hit = actual.lower() in options
        return hit if op == "in" else not hit
    if op == "contains":
        return expected.lower() in actual.lower()

    a, b = _num(actual), _num(expected)
    if a is not None and b is not None:
        return {"=": a == b, "!=": a != b, ">": a > b, ">=": a >= b,
                "<": a < b, "<=": a <= b}[op]
    if op in (">", ">=", "<", "<="):
        return False        # a non-numeric value never satisfies a numeric comparison
    return {"=": actual.lower() == expected.lower(),
            "!=": actual.lower() != expected.lower()}[op]


def matches(groups, lead: dict) -> bool:
    return any(all(evaluate(c, lead) for c in group) for group in groups)


def fields_used(groups) -> set:
    return {field for group in groups for field, _, _ in group}


# --------------------------------------------------------------------------------------

def simulate(rules_doc: dict, leads: list[dict], lead_fields: list[str]) -> dict:
    # People write the rules array on its own, without the wrapper. Say what is wrong
    # rather than dying on .get() — it is one of the two most likely first-run mistakes.
    if isinstance(rules_doc, list):
        raise RuleError(
            "the rules file is a bare list. Wrap it: {\"rules\": [ ... ], "
            "\"default\": \"unassigned\"}")
    if not isinstance(rules_doc, dict):
        raise RuleError("the rules file must be a JSON object with a 'rules' array")
    rules = rules_doc.get("rules") or []
    if not isinstance(rules, list) or any(not isinstance(r, dict) for r in rules):
        raise RuleError("'rules' must be an array of objects, each with 'when' and 'assign'")
    default_owner = rules_doc.get("default", "unassigned")
    if not rules:
        raise RuleError("the rules file contains no rules")

    compiled = []
    for i, rule in enumerate(rules):
        if "when" not in rule or "assign" not in rule:
            raise RuleError(f"rule {i + 1} needs both 'when' and 'assign'")
        compiled.append({
            "name": rule.get("name") or f"rule {i + 1}",
            "groups": parse_when(rule["when"]),
            "assign": rule["assign"],
            "when": rule["when"],
        })

    # A field a rule tests but no lead carries is a typo that silently disables the rule.
    known = {f.lower() for f in lead_fields}
    unknown_fields = []
    for rule in compiled:
        missing = sorted(f for f in fields_used(rule["groups"]) if f.lower() not in known)
        if missing:
            unknown_fields.append({"rule": rule["name"], "fields": missing})

    rr_state: dict[str, int] = defaultdict(int)
    assignments = Counter()
    won = Counter()
    isolated = Counter()
    unrouted = []
    stolen_by: dict[str, Counter] = defaultdict(Counter)
    match_sets: dict[str, set] = defaultdict(set)

    for lead_index, lead in enumerate(leads):
        winner = None
        for rule in compiled:
            if not matches(rule["groups"], lead):
                continue
            isolated[rule["name"]] += 1
            match_sets[rule["name"]].add(lead_index)
            if winner is None:
                winner = rule
            else:
                # This rule would have taken the lead if the winner were not above it.
                stolen_by[rule["name"]][winner["name"]] += 1
        if winner is None:
            assignments[default_owner] += 1
            unrouted.append(lead)
            continue
        won[winner["name"]] += 1
        target = winner["assign"]
        if isinstance(target, str) and target.lower().startswith("round_robin:"):
            pool = [p.strip() for p in target.split(":", 1)[1].split(",") if p.strip()]
            owner = pool[rr_state[winner["name"]] % len(pool)] if pool else default_owner
            rr_state[winner["name"]] += 1
        else:
            owner = target
        assignments[owner] += 1

    rule_stats = []
    for rule in compiled:
        name = rule["name"]
        rule_stats.append({
            "rule": name, "when": rule["when"], "assign": rule["assign"],
            "matched": isolated[name], "won": won[name],
            "shadowed_by": dict(stolen_by[name].most_common(3)),
            # A rule above that matches everything this one matches, and more, is an
            # ordering bug. A rule above that is NARROWER is an ordinary cascade and must
            # not be reported, or every correctly-placed catch-all becomes a finding.
            "broader_above": sorted(
                other for other in stolen_by[name]
                if match_sets[other] > match_sets[name]),
        })

    return {
        "leads": len(leads),
        "rules": len(compiled),
        "default": default_owner,
        "assignments": dict(assignments.most_common()),
        "rule_stats": rule_stats,
        "unknown_fields": unknown_fields,
        "unrouted": len(unrouted),
        "unrouted_sample": [{k: v for k, v in lead.items() if v}
                            for lead in unrouted[:5]],
    }


def problems(report: dict) -> list[dict]:
    out = []
    explained = set()
    for u in report["unknown_fields"]:
        explained.add(u["rule"])
        out.append({"kind": "unknown_field", "severity": "critical",
                    "detail": f"rule '{u['rule']}' tests "
                              f"{', '.join(repr(f) for f in u['fields'])}, which no lead "
                              f"carries — the rule can never match anything"})
    for s in report["rule_stats"]:
        if s["rule"] in explained:
            continue        # the unknown field above is already the reason it is dead
        if s["matched"] == 0:
            out.append({"kind": "dead_rule", "severity": "high",
                        "detail": f"rule '{s['rule']}' matched no lead at all"})
        elif s["won"] == 0:
            takers = ", ".join(f"'{k}'" for k in s["shadowed_by"]) or "an earlier rule"
            out.append({"kind": "shadowed_rule", "severity": "high",
                        "detail": f"rule '{s['rule']}' matched {s['matched']} lead(s) and "
                                  f"won none — {takers} sits above it and takes them all"})
        elif s["broader_above"]:
            lost = sum(n for k, n in s["shadowed_by"].items() if k in s["broader_above"])
            takers = ", ".join(f"'{k}'" for k in s["broader_above"])
            out.append({"kind": "broader_rule_above", "severity": "medium",
                        "detail": f"rule '{s['rule']}' loses {lost} of {s['matched']} "
                                  f"matches to {takers}, which sits above it and matches "
                                  f"everything this rule matches and more. A catch-all "
                                  f"belongs below the specific rules, not above them"})
    if report["unrouted"]:
        share = report["unrouted"] / max(report["leads"], 1)
        out.append({"kind": "unrouted_leads",
                    "severity": "high" if share > 0.1 else "medium",
                    "detail": f"{report['unrouted']} lead(s) ({share:.0%}) matched no rule "
                              f"and fell to '{report['default']}'"})
    owners = report["assignments"]
    routed = {k: v for k, v in owners.items() if k != report["default"]}
    if len(routed) > 1:
        top, low = max(routed.values()), min(routed.values())
        if low and top / low > 3:
            name = max(routed, key=routed.get)
            out.append({"kind": "load_imbalance", "severity": "medium",
                        "detail": f"'{name}' receives {top} leads while the lightest owner "
                                  f"receives {low} — a {top / low:.0f}x spread"})
    order = {"critical": 0, "high": 1, "medium": 2}
    out.sort(key=lambda p: order[p["severity"]])
    return out


def render(report: dict, found: list[dict], rules_path: str, leads_path: str) -> str:
    L = [f"routing-simulate · {os.path.basename(rules_path)} against "
         f"{os.path.basename(leads_path)}", "=" * 78, ""]
    L.append(f"  {report['leads']:,} leads through {report['rules']} rules")
    L.append("")
    L.append("  WHERE THEY LAND")
    L.append("  " + "-" * 40)
    for owner, n in report["assignments"].items():
        bar = "█" * max(1, round(28 * n / max(report["assignments"].values())))
        flag = "  ← nothing matched" if owner == report["default"] else ""
        L.append(f"    {owner[:18]:<18} {n:>5}  {bar}{flag}")
    L.append("")
    L.append("  RULES")
    L.append("  " + "-" * 40)
    L.append(f"    {'rule':<26} {'matched':>8} {'won':>6}")
    for s in report["rule_stats"]:
        note = ""
        if s["matched"] == 0:
            note = "  never matches"
        elif s["won"] == 0:
            note = "  shadowed"
        L.append(f"    {s['rule'][:26]:<26} {s['matched']:>8} {s['won']:>6}{note}")
    L.append("")

    if not found:
        L.append("  No routing problems found: every rule fires, every lead lands somewhere.")
        return "\n".join(L)

    L.append("  PROBLEMS")
    L.append("  " + "-" * 40)
    for p in found:
        L.append(f"    [{p['severity']}] {p['kind']}")
        for line in wrap(p["detail"], 68):
            L.append(f"      {line}")
        L.append("")
    if report["unrouted_sample"]:
        L.append("  LEADS THAT MATCHED NOTHING (first few)")
        L.append("  " + "-" * 40)
        for lead in report["unrouted_sample"]:
            L.append("    " + " · ".join(f"{k}={v}" for k, v in list(lead.items())[:5]))
    return "\n".join(L)


def main(argv=None) -> int:
    use_utf8_stdout()
    p = argparse.ArgumentParser(description="Simulate lead routing rules against real leads.")
    p.add_argument("--rules", required=True, help="routing rules as JSON")
    p.add_argument("--leads", required=True, help="leads export as CSV")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        with open(args.rules, encoding="utf-8-sig") as fh:
            rules_doc = json.load(fh)
        leads, fields = load_rows(args.leads)
    except (OSError, LoadError, json.JSONDecodeError) as e:
        print(f"could not read input: {e}", file=sys.stderr)
        return 2
    if not leads:
        print("the leads file has no rows", file=sys.stderr)
        return 2

    try:
        report = simulate(rules_doc, leads, fields)
    except RuleError as e:
        print(f"rules problem: {e}", file=sys.stderr)
        return 2

    found = problems(report)
    if args.json:
        print(json.dumps({**report, "problems": found}, indent=2))
    else:
        print(render(report, found, args.rules, args.leads))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
