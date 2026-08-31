#!/usr/bin/env python3
"""Reconcile a platform's conversion export against the CRM, and name the likely cause.

The platform says 400 conversions. The CRM says 260. Everyone argues about attribution
windows for a week and nobody finds the bug. This joins the two exports, measures the SHAPE
of the disagreement, and matches that shape against a ranked list of named causes.

    python reconcile.py --platform ga4.csv --crm crm.csv
    python reconcile.py --platform ads.csv --crm hubspot.csv --key transaction_id --json

Exit codes: 0 no material divergence · 1 divergence diagnosed · 2 could not read input.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

# Vendored into this folder by tools/sync_shared.py so the skill works when copied alone.
from _shared import LoadError, find_column, load_rows, wrap, use_utf8_stdout  # noqa: E402

KEY_CANDIDATES = ("transaction_id", "order_id", "conversion_id", "lead_id", "deal_id",
                  "event_id", "id", "gclid", "email")
DATE_CANDIDATES = ("date", "created_date", "event_date", "created_at", "created", "day",
                   "timestamp", "close_date")
DIMENSIONS = ("page_path", "page_location", "landing_page", "event_name", "conversion_action",
              "source", "medium", "campaign", "channel", "utm_source", "utm_medium")

# How far apart two totals have to be before any of this is worth reading.
MATERIAL_RATIO = 0.05


def parse_date(value: str):
    v = (value or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


class Diagnosis:
    __slots__ = ("name", "confidence", "headline", "evidence", "action")

    def __init__(self, name, confidence, headline, evidence, action):
        self.name, self.confidence = name, confidence
        self.headline, self.evidence, self.action = headline, evidence, action

    def as_dict(self):
        return {"cause": self.name, "confidence": round(self.confidence, 2),
                "headline": self.headline, "evidence": self.evidence, "action": self.action}


# --------------------------------------------------------------------------------------
# Detectors. Each returns a Diagnosis or None, and every one of them states the evidence
# that fired it — a diagnosis a user cannot check is a guess wearing a lab coat.
# --------------------------------------------------------------------------------------

def detect_key_mismatch(ctx) -> Diagnosis | None:
    """Runs first and outranks everything, because if the join is wrong the rest is noise."""
    p_only, c_only = len(ctx["platform_only"]), len(ctx["crm_only"])
    if not (p_only and c_only):
        return None
    both_high = p_only / max(ctx["platform_ids"], 1) > 0.6 and \
        c_only / max(ctx["crm_ids"], 1) > 0.6
    if not both_high:
        return None
    return Diagnosis(
        "join_key_mismatch", 0.95,
        "The two exports barely join at all, so nothing below can be trusted yet.",
        f"{p_only} of {ctx['platform_ids']} platform ids and {c_only} of {ctx['crm_ids']} "
        f"CRM ids have no counterpart on the '{ctx['key']}' column. When a real measurement "
        f"gap exists, one side is usually a superset of the other rather than both sides "
        f"being strangers.",
        "Check the key before anything else: different prefixes, one side lower-cased, one "
        "side truncated, or the platform holding a click id where the CRM holds an order id. "
        "Re-run with --key once they share a field.")


def detect_duplicate_ids(ctx) -> Diagnosis | None:
    dupes = {k: n for k, n in ctx["platform_counts"].items() if n > 1}
    if not dupes:
        return None
    extra_rows = sum(n - 1 for n in dupes.values())
    share = extra_rows / max(ctx["platform_rows"], 1)
    if share < 0.05:
        return None
    multiplicities = Counter(dupes.values())
    common, common_n = multiplicities.most_common(1)[0]
    uniform = common_n / len(dupes) > 0.8
    conf = min(0.95, 0.55 + share)
    return Diagnosis(
        "duplicate_events", conf,
        "The same conversion is being counted more than once by the platform.",
        f"{len(dupes):,} ids appear more than once in the platform export, adding "
        f"{extra_rows:,} rows ({share:.0%} of the total). "
        + (f"Almost all of them appear exactly {common} times, which points at one "
           f"mechanism rather than scattered accidents." if uniform else
           "The multiplicity varies, so more than one thing is firing twice."),
        "Look for the browser pixel and the server-side API sending the same event without "
        "a shared event id, a tag with two triggers, or the tag placed both in the container "
        "and hard-coded on the page. Deduplication needs the SAME event id on both paths.")


def detect_concentrated_excess(ctx) -> Diagnosis | None:
    """Excess piled onto one dimension value is a specific broken tag, not a systemic one."""
    best = None
    for dim, values in ctx["excess_by_dimension"].items():
        total_excess = sum(values.values())
        if total_excess < 5:
            continue
        value, n = max(values.items(), key=lambda kv: kv[1])
        excess_share = n / total_excess
        baseline = ctx["matched_by_dimension"][dim].get(value, 0)
        baseline_share = baseline / max(sum(ctx["matched_by_dimension"][dim].values()), 1)
        if excess_share < 0.5 or excess_share - baseline_share < 0.25:
            continue
        conf = min(0.9, 0.45 + excess_share - baseline_share)
        if not best or conf > best[0]:
            best = (conf, dim, value, n, total_excess, excess_share, baseline_share)
    if not best:
        return None
    conf, dim, value, n, total, excess_share, baseline_share = best
    return Diagnosis(
        "trigger_matching_too_broadly", conf,
        f"The excess is not spread out. It is almost all on one value of '{dim}'.",
        f"{n:,} of {total:,} unmatched platform rows ({excess_share:.0%}) carry "
        f"{dim}='{value}', while that value accounts for only {baseline_share:.0%} of rows "
        f"that did match. A systemic problem inflates everything evenly; this does not.",
        f"Read the trigger behind the conversion tag on {dim}='{value}'. The usual cause is "
        f"a 'contains' or regex condition that matches more pages than intended — a path "
        f"regex without anchors is the classic. Fire the tag in preview mode on a page you "
        f"expect it NOT to fire on.")


def detect_date_offset(ctx) -> Diagnosis | None:
    p, c = ctx["platform_by_date"], ctx["crm_by_date"]
    if len(p) < 5 or len(c) < 5:
        return None

    def distance(shift: int) -> int:
        days = set(p) | {d + timedelta(days=shift) for d in c}
        return sum(abs(p.get(d, 0) - c.get(d - timedelta(days=shift), 0)) for d in days)

    base = distance(0)
    if base == 0:
        return None
    best_shift, best = min(((s, distance(s)) for s in (-1, 1)), key=lambda x: x[1])
    improvement = (base - best) / base
    if improvement < 0.4:
        return None
    direction = "ahead of" if best_shift == 1 else "behind"
    return Diagnosis(
        "timezone_or_window_mismatch", min(0.9, 0.5 + improvement / 2),
        "The totals are close; the days they are attributed to are not.",
        f"Shifting the CRM by {abs(best_shift)} day reduces the day-by-day disagreement by "
        f"{improvement:.0%} ({base:,} to {best:,}). The platform is reporting {direction} "
        f"the CRM.",
        "Compare the reporting timezone on the analytics property against the CRM's, and "
        "check whether one side stamps the conversion at click time and the other at close "
        "time. Until they agree, every daily comparison is wrong and every monthly one is "
        "right, which is why this survives so long.")


def detect_step_change(ctx) -> Diagnosis | None:
    days = sorted(set(ctx["platform_by_date"]) | set(ctx["crm_by_date"]))
    if len(days) < 10:
        return None
    ratios = []
    for d in days:
        c = ctx["crm_by_date"].get(d, 0)
        if c:
            ratios.append((d, ctx["platform_by_date"].get(d, 0) / c))
    if len(ratios) < 10:
        return None
    best = None
    for i in range(4, len(ratios) - 4):
        before = sum(r for _, r in ratios[:i]) / i
        after = sum(r for _, r in ratios[i:]) / (len(ratios) - i)
        gap = abs(after - before)
        if not best or gap > best[0]:
            best = (gap, ratios[i][0], before, after)
    gap, when, before, after = best
    if gap < 0.5:
        return None
    return Diagnosis(
        "step_change_on_a_date", min(0.85, 0.4 + gap / 4),
        f"Something changed on {when.isoformat()}, and the ratio never went back.",
        f"Platform-to-CRM ratio averaged {before:.2f} before {when.isoformat()} and "
        f"{after:.2f} after. A measurement problem that has always been there does not have "
        f"a start date.",
        "Line that date up against your release log, your tag manager's version history and "
        "any consent banner change. A tag published, a consent category changed, or a "
        "redirect added is the usual answer, and the version history will name who did it.")


def detect_flat_multiple(ctx) -> Diagnosis | None:
    ratio = ctx["ratio"]
    if ratio < 1.6:
        return None
    nearest = round(ratio)
    if nearest < 2 or abs(ratio - nearest) > 0.15:
        return None
    per_dim = []
    for dim, values in ctx["ratio_by_dimension"].items():
        per_dim.extend(values.values())
    if len(per_dim) < 3:
        return None
    spread = max(per_dim) - min(per_dim)
    if spread > 0.6:
        return None
    return Diagnosis(
        "duplicate_stream_or_container", min(0.85, 0.6 + (0.6 - spread)),
        f"Everything is inflated by almost exactly {nearest}x, evenly.",
        f"Overall ratio {ratio:.2f}, and the ratio holds across every dimension checked "
        f"(spread {spread:.2f}). Even inflation across unrelated dimensions is the signature "
        f"of counting the same thing twice at the source, not of a broken campaign.",
        "Look for a second measurement id on the page, the container included twice, or a "
        "tag deployed both through the tag manager and in the site template. View source and "
        "count the occurrences of the measurement id.")


def detect_undercount(ctx) -> Diagnosis | None:
    if ctx["ratio"] > 0.9 or not ctx["crm_only"]:
        return None
    missing = len(ctx["crm_only"])
    return Diagnosis(
        "platform_undercount", 0.6,
        "The CRM has conversions the platform never recorded.",
        f"{missing:,} CRM records ({missing / max(ctx['crm_ids'], 1):.0%}) have no platform "
        f"counterpart, and the platform total is {1 - ctx['ratio']:.0%} below the CRM's.",
        "In order of likelihood: consent gating blocking the tag for a share of visitors, ad "
        "blockers, the conversion page not carrying the tag on every route, or offline and "
        "assisted conversions that were never going to be visible client-side. Server-side "
        "measurement fixes the first two and nothing fixes the fourth.")


DETECTORS = (detect_key_mismatch, detect_duplicate_ids, detect_concentrated_excess,
             detect_date_offset, detect_step_change, detect_flat_multiple, detect_undercount)


# --------------------------------------------------------------------------------------

def build_context(p_rows, p_fields, c_rows, c_fields, key=None, verbose=True):
    key_p = key or find_column(p_fields, KEY_CANDIDATES)
    key_c = key or find_column(c_fields, KEY_CANDIDATES)
    if not key_p or not key_c:
        raise SystemExit("could not find a join key in both files — pass --key")

    date_p = find_column(p_fields, DATE_CANDIDATES)
    date_c = find_column(c_fields, DATE_CANDIDATES)

    p_counts = Counter(r[key_p] for r in p_rows if r.get(key_p))
    c_counts = Counter(r[key_c] for r in c_rows if r.get(key_c))
    matched = set(p_counts) & set(c_counts)
    platform_only = set(p_counts) - matched
    crm_only = set(c_counts) - matched

    dims = [d for d in DIMENSIONS if d in {f.lower() for f in p_fields}]
    dim_cols = {d: find_column(p_fields, (d,)) for d in dims}

    excess: dict[str, Counter] = defaultdict(Counter)
    matched_dim: dict[str, Counter] = defaultdict(Counter)
    for r in p_rows:
        bucket = excess if r.get(key_p) in platform_only else matched_dim
        for dim, col in dim_cols.items():
            if col and r.get(col):
                bucket[dim][r[col]] += 1

    # Per-dimension platform:CRM ratio, for values the CRM also carries.
    ratio_dim: dict[str, dict] = {}
    for dim, col in dim_cols.items():
        c_col = find_column(c_fields, (dim,))
        if not c_col:
            continue
        p_by = Counter(r[col] for r in p_rows if r.get(col))
        c_by = Counter(r[c_col] for r in c_rows if r.get(c_col))
        shared = {v: p_by[v] / c_by[v] for v in p_by if c_by.get(v, 0) >= 5}
        if shared:
            ratio_dim[dim] = shared

    p_by_date = Counter()
    c_by_date = Counter()
    if date_p:
        for r in p_rows:
            d = parse_date(r.get(date_p, ""))
            if d:
                p_by_date[d] += 1
    if date_c:
        for r in c_rows:
            d = parse_date(r.get(date_c, ""))
            if d:
                c_by_date[d] += 1

    return {
        "key": key_p, "key_crm": key_c,
        "platform_rows": len(p_rows), "crm_rows": len(c_rows),
        "platform_ids": len(p_counts), "crm_ids": len(c_counts),
        "platform_counts": p_counts, "crm_counts": c_counts,
        "matched": matched, "platform_only": platform_only, "crm_only": crm_only,
        "ratio": len(p_rows) / len(c_rows) if c_rows else 0.0,
        "excess_by_dimension": excess, "matched_by_dimension": matched_dim,
        "ratio_by_dimension": ratio_dim,
        "platform_by_date": p_by_date, "crm_by_date": c_by_date,
        "dimensions": list(dim_cols),
    }


def build_report(ctx) -> dict:
    diagnoses = [d for d in (fn(ctx) for fn in DETECTORS) if d]
    diagnoses.sort(key=lambda d: -d.confidence)
    material = abs(ctx["ratio"] - 1) > MATERIAL_RATIO or bool(diagnoses)
    return {
        "join_key": ctx["key"],
        "platform_rows": ctx["platform_rows"], "crm_rows": ctx["crm_rows"],
        "ratio": round(ctx["ratio"], 3),
        "matched_ids": len(ctx["matched"]),
        "platform_only_ids": len(ctx["platform_only"]),
        "crm_only_ids": len(ctx["crm_only"]),
        "material": material,
        "diagnoses": [d.as_dict() for d in diagnoses],
    }


def render(report: dict, platform: str, crm: str) -> str:
    L = [f"conversion-reconcile · {os.path.basename(platform)} vs {os.path.basename(crm)}",
         "=" * 78, ""]
    delta = report["ratio"] - 1
    L.append(f"  platform {report['platform_rows']:>7,} rows")
    L.append(f"  crm      {report['crm_rows']:>7,} rows"
             f"   ratio {report['ratio']:.2f}  ({delta:+.0%})")
    L.append(f"  joined on '{report['join_key']}': {report['matched_ids']:,} matched · "
             f"{report['platform_only_ids']:,} platform-only · "
             f"{report['crm_only_ids']:,} crm-only")
    L.append("")

    if not report["diagnoses"]:
        L.append("  The two sides agree within tolerance, and no known divergence shape fits.")
        L.append("  That is not the same as 'the tracking is correct' — it means these two")
        L.append("  exports do not disagree in any way this tool can name.")
        return "\n".join(L)

    L.append("  RANKED CAUSES")
    L.append("  " + "-" * 74)
    for i, d in enumerate(report["diagnoses"], 1):
        L.append(f"  {i}. {d['cause']}   (confidence {d['confidence']:.2f})")
        for line in wrap(d["headline"], 70):
            L.append(f"     {line}")
        L.append("")
        for line in wrap("Evidence: " + d["evidence"], 70):
            L.append(f"       {line}")
        L.append("")
        for line in wrap("What to do: " + d["action"], 70):
            L.append(f"       {line}")
        L.append("")
    L.append("  Confidence is how well the divergence fits this shape, not how likely the")
    L.append("  fix is to work. Read the evidence line before acting on the label.")
    return "\n".join(L)


def main(argv=None) -> int:
    use_utf8_stdout()
    p = argparse.ArgumentParser(
        description="Reconcile a platform conversion export against the CRM.")
    p.add_argument("--platform", required=True, help="the platform's export (GA4, Ads, Meta)")
    p.add_argument("--crm", required=True, help="the CRM export — the side you believe")
    p.add_argument("--key", help="join column present in both (default: auto-detect)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    try:
        p_rows, p_fields = load_rows(args.platform)
        c_rows, c_fields = load_rows(args.crm)
    except (OSError, LoadError) as e:
        print(f"could not read input: {e}", file=sys.stderr)
        return 2
    if not p_rows or not c_rows:
        print("one of the exports has no rows", file=sys.stderr)
        return 2

    ctx = build_context(p_rows, p_fields, c_rows, c_fields, args.key)
    report = build_report(ctx)
    print(json.dumps(report, indent=2) if args.json else render(report, args.platform, args.crm))
    return 1 if report["diagnoses"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
