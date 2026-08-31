#!/usr/bin/env python3
"""Generate the conversion-reconcile fixtures: three scenarios, three different causes.

Nobody can publish their employer's conversion data, so a reconciliation tool that cannot
be demonstrated without it will not be tried. These are synthetic, deterministic (seeded),
and each one has exactly one thing wrong with it — which is also what makes them a real
test: a diagnostic that always guesses "duplicate events" would pass one scenario and fail
the other two.

    python tools/make_fixtures.py
"""
from __future__ import annotations

import csv
import pathlib
import random
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "conversion-reconcile"

START = date(2026, 7, 1)
DAYS = 28
PATHS = ["/checkout/success", "/demo/thank-you", "/trial/confirmed", "/contact/sent"]
SOURCES = [("google", "cpc"), ("linkedin", "paid-social"), ("(direct)", "(none)"),
           ("bing", "cpc"), ("newsletter", "email")]
EVENTS = ["purchase", "generate_lead"]

PLATFORM_FIELDS = ["date", "transaction_id", "event_name", "source", "medium", "page_path"]
CRM_FIELDS = ["created_date", "transaction_id", "stage", "source", "owner"]


def _base(rng: random.Random, n_per_day: int = 9):
    """The truth: what actually happened, before any measurement went wrong."""
    truth = []
    for d in range(DAYS):
        day = START + timedelta(days=d)
        for i in range(n_per_day + rng.randint(-2, 2)):
            source, medium = rng.choice(SOURCES)
            truth.append({
                "date": day.isoformat(),
                "transaction_id": f"T{d:02d}{i:03d}",
                "event_name": rng.choice(EVENTS) if rng.random() < 0.35 else "purchase",
                "source": source,
                "medium": medium,
                "page_path": rng.choice(PATHS),
            })
    return truth


def _crm_rows(truth, shift_days: int = 0):
    rows = []
    for t in truth:
        d = date.fromisoformat(t["date"]) + timedelta(days=shift_days)
        rows.append({"created_date": d.isoformat(), "transaction_id": t["transaction_id"],
                     "stage": "closed-won", "source": t["source"], "owner": "unassigned"})
    return rows


def scenario_duplicate_events(rng):
    """Pixel and server-side API both firing, with no deduplication: every id twice."""
    truth = _base(rng)
    platform = []
    for t in truth:
        platform.append(dict(t))
        platform.append(dict(t))          # the same transaction_id, reported twice
    return platform, _crm_rows(truth)


def scenario_broad_trigger(rng):
    """A trigger whose regex matches too broadly: one page path inflated, rest correct."""
    truth = _base(rng)
    platform = [dict(t) for t in truth]
    victim = PATHS[0]
    extra = 0
    for t in truth:
        if t["page_path"] != victim:
            continue
        for k in range(3):                # fires four times instead of once
            dupe = dict(t)
            dupe["transaction_id"] = f"{t['transaction_id']}-x{k}"
            platform.append(dupe)
            extra += 1
    assert extra, "fixture generated no inflation"
    return platform, _crm_rows(truth)


def scenario_timezone_offset(rng):
    """Platform in one timezone, CRM in another: same volume, every row a day apart."""
    truth = _base(rng)
    return [dict(t) for t in truth], _crm_rows(truth, shift_days=1)


def scenario_clean(rng):
    """Nothing wrong. A tool that cannot stay quiet gets uninstalled after one false alarm."""
    truth = _base(rng)
    return [dict(t) for t in truth], _crm_rows(truth)


SCENARIOS = {
    "clean": scenario_clean,
    "duplicate_events": scenario_duplicate_events,
    "broad_trigger": scenario_broad_trigger,
    "timezone_offset": scenario_timezone_offset,
}


def write(path: pathlib.Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    for name, build in SCENARIOS.items():
        rng = random.Random(f"martech-verify/{name}")   # seeded: same fixture every time
        platform, crm = build(rng)
        write(OUT / f"{name}_platform.csv", PLATFORM_FIELDS, platform)
        write(OUT / f"{name}_crm.csv", CRM_FIELDS, crm)
        print(f"{name:<18} platform {len(platform):>5} rows · crm {len(crm):>5} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
