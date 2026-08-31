#!/usr/bin/env python3
"""Lint a real corpus of tagged URLs against the way analytics platforms actually read them.

Every marketing skill collection ships UTM *advice*. None of them will look at the four
thousand tagged URLs you already have and tell you which ones broke the taxonomy, which
ones will split one campaign into three rows, and which ones land in Unassigned.

    python lint.py urls.csv
    python lint.py urls.csv --json
    python lint.py urls.csv --site shop.example.com --fail-on high

Exit codes: 0 clean · 1 findings at or above --fail-on · 2 could not read input.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, urlsplit

# Vendored into this folder by tools/sync_shared.py so the skill works when copied alone.
from _shared import LoadError, SEVERITY_ORDER, load_values, redact, wrap, use_utf8_stdout  # noqa: E402

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
            "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic")
CLICK_IDS = ("gclid", "gbraid", "wbraid", "dclid", "fbclid", "msclkid", "ttclid", "li_fat_id")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# GA4's default channel group only recognises certain utm_medium values. Anything else is
# not "a custom channel" — it is Unassigned, and the spend attached to it disappears from
# every channel report. These mirror the platform's own definitions.
RECOGNISED_MEDIUM = [
    (re.compile(r"^(.*cp.*|ppc|retargeting|paid.*)$"), "Paid Search / Paid Other"),
    (re.compile(r"^(display|banner|expandable|interstitial|cpm)$"), "Display"),
    (re.compile(r"^(email|e-mail|e_mail|e mail)$"), "Email"),
    (re.compile(r"^(social|social-network|social-media|sm|social network|social media)$"),
     "Organic Social"),
    (re.compile(r"^affiliate$"), "Affiliates"),
    (re.compile(r"^referral$"), "Referral"),
    (re.compile(r"^organic$"), "Organic Search"),
    (re.compile(r"^(audio|video|sms|push|mobile|notification)$"), "Audio / Video / SMS / Push"),
]
# The near-misses seen most often, and what they were meant to be.
MEDIUM_SUGGESTIONS = {
    "paid social": "paid-social", "paidsocial": "paid-social", "social paid": "paid-social",
    "ppc ": "ppc", "cost per click": "cpc", "pay per click": "cpc", "adwords": "cpc",
    "google ads": "cpc", "newsletter": "email", "mail": "email", "emails": "email",
    "facebook": "paid-social", "linkedin": "paid-social", "instagram": "paid-social",
    "organic social": "social", "socialmedia": "social", "banner ad": "display",
}

RULES = {
    "pii_in_utm": ("critical",
                   "An email address is sitting in a campaign parameter. Email tools do "
                   "this when a merge field is dropped into utm_content. It is a privacy "
                   "problem before it is a tagging one — run pii-scan on the same corpus."),
    "case_drift": ("high",
                   "The same value appears in different cases. Analytics platforms are "
                   "case-sensitive here, so one campaign becomes several rows and every "
                   "total is wrong. Lower-case everything at the source."),
    "near_duplicate": ("high",
                       "Values that a human reads as identical and a report does not: "
                       "underscores against hyphens against spaces. Pick one and enforce it."),
    "unmapped_medium": ("high",
                        "This utm_medium does not match any default channel definition, so "
                        "the traffic lands in Unassigned and vanishes from channel reports."),
    "missing_required": ("high",
                         "A campaign is named but its source or medium is missing, so the "
                         "visits cannot be grouped with the rest of the campaign."),
    "whitespace": ("high",
                   "A leading, trailing or embedded space. It survives into the report as a "
                   "separate value that looks identical to the correct one."),
    "duplicate_param": ("high",
                        "The same parameter appears twice in one URL. Which one wins depends "
                        "on the platform, which means the answer is unreliable."),
    "self_referral": ("high",
                      "A link on your own site is tagged with your own domain as the source. "
                      "That restarts the session and reassigns the conversion away from "
                      "whatever actually brought the visitor."),
    "autotagging_conflict": ("medium",
                             "A Google click id and manual utm tags on the same URL. With "
                             "auto-tagging on, the click id wins and your manual tags are "
                             "ignored — so the taxonomy you think you have is not the one "
                             "in the reports."),
    "source_equals_medium": ("medium",
                             "utm_source and utm_medium hold the same value, which usually "
                             "means one of them was filled in by mistake."),
    "empty_param": ("medium",
                    "The parameter is present but empty, which is not the same as absent: "
                    "it can still create a blank dimension value in reporting."),
}


class Issue:
    __slots__ = ("rule", "param", "value", "suggestion", "example")

    def __init__(self, rule, param, value, suggestion="", example=""):
        self.rule, self.param = rule, param
        self.value, self.suggestion, self.example = value, suggestion, example

    def key(self):
        return (self.rule, self.param, self.value, self.suggestion)


def normalise(value: str) -> str:
    """Collapse everything a report would treat as different but a human would not."""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def classify_medium(medium: str) -> str | None:
    m = medium.strip().lower()
    for pattern, channel in RECOGNISED_MEDIUM:
        if pattern.match(m):
            return channel
    return None


def parse(url: str) -> tuple[dict, list[tuple[str, str]], str]:
    """Return (utm dict, raw pairs, host). Raw pairs are kept so duplicates survive."""
    parts = urlsplit(url if "://" in url else "//host" + url if url.startswith("/") else url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    utm = {k.lower(): v for k, v in pairs if k.lower() in UTM_KEYS or k.lower() in CLICK_IDS}
    return utm, pairs, (parts.netloc or "").lower().removeprefix("www.")


def lint_url(url: str, site: str | None) -> list[Issue]:
    utm, pairs, host = parse(url)
    out: list[Issue] = []
    if not any(k.startswith("utm_") for k in utm):
        return out

    seen = Counter(k.lower() for k, _ in pairs)
    for key, count in seen.items():
        if count > 1 and key in UTM_KEYS:
            out.append(Issue("duplicate_param", key, f"appears {count}x", example=url))

    for key in UTM_KEYS:
        if key not in utm:
            continue
        value = utm[key]
        if not value.strip():
            out.append(Issue("empty_param", key, "(empty)", example=url))
            continue
        if value != value.strip() or " " in value:
            out.append(Issue("whitespace", key, value,
                             re.sub(r"\s+", "-", value.strip()).lower(), url))
        for m in EMAIL_RE.finditer(value):
            out.append(Issue("pii_in_utm", key, redact(m.group(0), "email"),
                             "remove the merge field from the tagged link", url))

    if utm.get("utm_campaign") and not (utm.get("utm_source") and utm.get("utm_medium")):
        # Short label on purpose: "utm_source and utm_medium" is wider than the column and
        # the finding is what got truncated, which is the one thing that must stay readable.
        missing = " + ".join(k.replace("utm_", "") for k in ("utm_source", "utm_medium")
                             if not utm.get(k))
        out.append(Issue("missing_required", missing, utm["utm_campaign"], example=url))

    medium = utm.get("utm_medium", "").strip()
    if medium and classify_medium(medium) is None:
        low = medium.lower()
        suggestion = MEDIUM_SUGGESTIONS.get(low, "")
        if not suggestion:
            # A medium containing "cp" is already recognised, so anything left that mentions
            # paid, ads or social almost always meant one of these three.
            for needle, fix in (("social", "paid-social"), ("mail", "email"),
                                ("ad", "cpc"), ("banner", "display")):
                if needle in low:
                    suggestion = fix
                    break
        out.append(Issue("unmapped_medium", "utm_medium", medium, suggestion, url))

    if utm.get("utm_source") and utm.get("utm_source") == utm.get("utm_medium"):
        out.append(Issue("source_equals_medium", "utm_source", utm["utm_source"], example=url))

    own = (site or "").lower().removeprefix("www.")
    source = utm.get("utm_source", "").lower()
    if source and (source == own or (host and source == host)):
        out.append(Issue("self_referral", "utm_source", utm["utm_source"],
                         "remove the tags from internal links", url))

    if any(c in utm for c in CLICK_IDS if c in ("gclid", "gbraid", "wbraid", "dclid")) \
            and utm.get("utm_source"):
        out.append(Issue("autotagging_conflict", "utm_source", utm["utm_source"],
                         "drop the manual tags on Google Ads links", url))
    return out


def corpus_issues(values: list[str]) -> list[Issue]:
    """Checks that only exist across the whole corpus: one campaign, three spellings."""
    raw_by_param: dict[str, Counter] = defaultdict(Counter)
    for url in values:
        utm, _, _ = parse(url)
        for key in ("utm_source", "utm_medium", "utm_campaign", "utm_content"):
            v = utm.get(key, "").strip()
            if v:
                raw_by_param[key][v] += 1

    out: list[Issue] = []
    for param, counts in raw_by_param.items():
        clusters: dict[str, Counter] = defaultdict(Counter)
        for value, n in counts.items():
            clusters[normalise(value)][value] += n
        for norm, variants in clusters.items():
            if len(variants) < 2 or not norm:
                continue
            canonical = variants.most_common(1)[0][0]
            only_case = len({v.lower() for v in variants}) == 1
            rule = "case_drift" if only_case else "near_duplicate"
            for value, n in variants.most_common():
                if value == canonical:
                    continue
                out.append(Issue(rule, param, value, canonical.lower(),
                                 f"{n} URL(s) — canonical form used {variants[canonical]}x"))
    return out


def build_report(values: list[str], site: str | None) -> dict:
    tagged = [v for v in values if "utm_" in v.lower()]
    grouped: dict[tuple, dict] = {}
    for url in values:
        for issue in lint_url(url, site):
            g = grouped.setdefault(issue.key(), {"issue": issue, "count": 0})
            g["count"] += 1
    for issue in corpus_issues(values):
        g = grouped.setdefault(issue.key(), {"issue": issue, "count": 0})
        g["count"] += 1

    rows, severities = [], Counter()
    for g in grouped.values():
        i, severity = g["issue"], RULES[g["issue"].rule][0]
        severities[severity] += g["count"]
        rows.append({"rule": i.rule, "severity": severity, "parameter": i.param,
                     "value": i.value, "suggestion": i.suggestion, "count": g["count"],
                     "example": i.example[:110]})
    rows.sort(key=lambda r: (SEVERITY_ORDER.index(r["severity"]), -r["count"], r["rule"]))

    rules_hit = {r["rule"] for r in rows}
    return {"scanned": len(values), "tagged": len(tagged), "findings": rows,
            "by_severity": dict(severities),
            "explanations": {r: RULES[r][1] for r in rules_hit}}


def render(report: dict, source: str, how: str) -> str:
    L = [f"utm-lint · {report['tagged']:,} tagged URLs of {report['scanned']:,} read from "
         f"{os.path.basename(source)} ({how})", "=" * 78]
    if not report["findings"]:
        L += ["", "  No tagging problems found in this corpus.", ""]
        return "\n".join(L)

    counts = report["by_severity"]
    L.append("  " + " · ".join(f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts.get(s)))
    L.append("")
    L.append(f"  {'severity':<9} {'rule':<21} {'parameter':<22} {'value':<21} {'n':>4}")
    L.append(f"  {'-'*9} {'-'*21} {'-'*22} {'-'*21} {'-'*4}")
    for r in report["findings"]:
        L.append(f"  {r['severity']:<9} {r['rule']:<21} {r['parameter'][:22]:<22} "
                 f"{r['value'][:21]:<21} {r['count']:>4}")
        if r["suggestion"]:
            L.append(f"  {'':<9} {'':<21} └─ should be: {r['suggestion'][:48]}")
    L.append("")
    L.append("  Why each of these matters")
    L.append("  " + "-" * 40)
    for rule, text in report["explanations"].items():
        L.append(f"    {rule}:")
        for line in wrap(text, 70):
            L.append(f"      {line}")
    return "\n".join(L)


def main(argv=None) -> int:
    use_utf8_stdout()
    p = argparse.ArgumentParser(description="Lint tagged URLs against how analytics reads them.")
    p.add_argument("input", help="CSV, TSV, JSON lines, or one URL per line")
    p.add_argument("--column", help="column to read (default: auto-detect)")
    p.add_argument("--site", help="your own domain, to catch internally tagged links")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fail-on", choices=SEVERITY_ORDER, default="high")
    args = p.parse_args(argv)

    try:
        values, how = load_values(args.input, args.column)
    except (OSError, LoadError) as e:
        print(f"could not read {args.input}: {e}", file=sys.stderr)
        return 2

    report = build_report(values, args.site)
    print(json.dumps(report, indent=2) if args.json else render(report, args.input, how))
    threshold = SEVERITY_ORDER.index(args.fail_on)
    return 1 if any(SEVERITY_ORDER.index(r["severity"]) <= threshold
                    for r in report["findings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
