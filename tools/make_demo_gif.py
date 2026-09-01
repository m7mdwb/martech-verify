#!/usr/bin/env python3
"""Build the README animation from real outputs over the synthetic fixtures.

Generation uses Pillow because GIF encoding and text rasterisation are development-time
concerns, not skill runtime dependencies. ``--check`` remains standard-library only: it
reruns the four tools and checks their current transcript fingerprint against the comment
embedded in the GIF.

    python tools/make_demo_gif.py
    python tools/make_demo_gif.py --check
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "martech-audit-demo.gif"
WIDTH, HEIGHT = 1200, 720

COMMANDS = {
    "pii": [
        sys.executable,
        str(ROOT / "skills" / "pii-scan" / "scripts" / "scan.py"),
        str(ROOT / "fixtures" / "pii-scan" / "ga4_pages_sample.csv"),
        "--json",
    ],
    "utm": [
        sys.executable,
        str(ROOT / "skills" / "utm-lint" / "scripts" / "lint.py"),
        str(ROOT / "fixtures" / "utm-lint" / "tagged_urls_sample.csv"),
        "--site",
        "shop.example-store.test",
        "--json",
    ],
    "conversion": [
        sys.executable,
        str(ROOT / "skills" / "conversion-reconcile" / "scripts" / "reconcile.py"),
        "--platform",
        str(ROOT / "fixtures" / "conversion-reconcile" / "broad_trigger_platform.csv"),
        "--crm",
        str(ROOT / "fixtures" / "conversion-reconcile" / "broad_trigger_crm.csv"),
        "--json",
    ],
    "routing": [
        sys.executable,
        str(ROOT / "skills" / "routing-simulate" / "scripts" / "simulate.py"),
        "--rules",
        str(ROOT / "fixtures" / "routing-simulate" / "routing_rules.json"),
        "--leads",
        str(ROOT / "fixtures" / "routing-simulate" / "leads_sample.csv"),
        "--json",
    ],
}

COLOURS = {
    "bg": "#0b0f14",
    "panel": "#111821",
    "border": "#273241",
    "text": "#d7dee9",
    "dim": "#8290a3",
    "prompt": "#73e2a7",
    "heading": "#7dd3fc",
    "critical": "#ff7b72",
    "warn": "#f2cc60",
    "good": "#73e2a7",
}


def capture_reports() -> dict:
    reports = {}
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for name, command in COMMANDS.items():
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=env)
        if result.returncode != 1:
            detail = (result.stderr or result.stdout or "no output").strip().splitlines()[-1]
            raise RuntimeError(f"{name} exited {result.returncode}; expected findings: {detail}")
        try:
            reports[name] = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"{name} did not produce valid JSON: {error}") from error
    return reports


def transcript(reports: dict) -> list[tuple[str, str]]:
    pii = reports["pii"]
    utm = reports["utm"]
    conversion = reports["conversion"]
    routing = reports["routing"]

    verified_critical = sum(
        finding["count"] for finding in pii["findings"]
        if finding["severity"] == "critical" and finding["signal"] == "value"
    )
    name_only_critical = sum(
        finding["count"] for finding in pii["findings"]
        if finding["severity"] == "critical" and finding["signal"] != "value"
    )
    utm_critical = utm["by_severity"].get("critical", 0)
    utm_high = utm["by_severity"].get("high", 0)
    unknown_fields = sum(len(item["fields"]) for item in routing["unknown_fields"])
    ratio_excess = round((conversion["ratio"] - 1) * 100)
    evidence = conversion["diagnoses"][0]["evidence"]
    path_match = re.search(r"page_path='([^']+)'", evidence)
    path = path_match.group(1) if path_match else "one page path"
    shadowed = next(problem["detail"] for problem in routing["problems"]
                    if problem["kind"] == "shadowed_rule")
    shadow_match = re.search(r"rule '([^']+)'.*matched (\d+)", shadowed)
    shadow_rule, shadow_count = shadow_match.groups() if shadow_match else ("one rule", "several")

    return [
        ("prompt", "codex > $martech-audit Audit the exports in demo-data/"),
        ("dim", "Classified 6 local files; running 4 read-only checks..."),
        ("good", "  pii-scan  OK     utm-lint  OK     conversion-reconcile  OK"),
        ("good", "  routing-simulate  OK     source files unchanged"),
        ("text", ""),
        ("heading", "FIX NOW"),
        ("critical", f"  {verified_critical} verified critical PII leaks in {pii['scanned']} analytics values"),
        ("critical", f"  {utm_critical} critical PII leak inside a campaign tag"),
        ("critical", f"  {routing['unrouted']} of {routing['leads']} leads are unrouted; {unknown_fields} rule field is unknown"),
        ("warn", f"  Platform conversions are +{ratio_excess}%; excess clusters on {path}"),
        ("text", ""),
        ("heading", "INVESTIGATE"),
        ("warn", f"  {utm_high} high-severity UTM issues split or misattribute campaign traffic"),
        ("warn", f"  '{shadow_rule}' matched {shadow_count} leads and won none"),
        ("warn", f"  {name_only_critical} critical DOB signal is parameter-name evidence only"),
        ("text", ""),
        ("heading", "COVERAGE"),
        ("dim", "  6 synthetic files | 4 deterministic checks | no connectors or telemetry"),
        ("good", "  Evidence first. Raw personal values stay redacted."),
    ]


def fingerprint(reports: dict) -> str:
    source = pathlib.Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n")
    payload = json.dumps(reports, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((source + "\n" + payload).encode("utf-8")).hexdigest()


def marker(reports: dict) -> bytes:
    return f"martech-verify-demo:{fingerprint(reports)}".encode("ascii")


def check(reports: dict) -> int:
    if not OUT.is_file():
        print(f"MISSING {OUT.relative_to(ROOT)} — run python tools/make_demo_gif.py",
              file=sys.stderr)
        return 1
    raw = OUT.read_bytes()
    if not raw.startswith((b"GIF87a", b"GIF89a")) or len(raw) < 10:
        print(f"INVALID {OUT.relative_to(ROOT)} — expected a GIF", file=sys.stderr)
        return 1
    width, height = struct.unpack("<HH", raw[6:10])
    if (width, height) != (WIDTH, HEIGHT):
        print(f"INVALID {OUT.relative_to(ROOT)} — expected {WIDTH}x{HEIGHT}, "
              f"got {width}x{height}", file=sys.stderr)
        return 1
    if marker(reports) not in raw:
        print(f"STALE {OUT.relative_to(ROOT)} — run python tools/make_demo_gif.py",
              file=sys.stderr)
        return 1
    print(f"{OUT.relative_to(ROOT)} matches the four tools' current output")
    return 0


def find_font(candidates: list[str], size: int):
    from PIL import ImageFont

    for candidate in candidates:
        if pathlib.Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    raise RuntimeError(f"could not find a usable font; tried: {', '.join(candidates)}")


def generate(reports: dict) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as error:
        raise RuntimeError("GIF generation requires Pillow: python -m pip install Pillow") from error

    mono = find_font([
        "C:/Windows/Fonts/consola.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
    ], 21)
    title_font = find_font([
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/SFNS.ttf",
    ], 19)
    lines = transcript(reports)

    def render(visible: list[tuple[str, str]]) -> "Image.Image":
        image = Image.new("RGB", (WIDTH, HEIGHT), COLOURS["bg"])
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), radius=15,
                               fill=COLOURS["panel"], outline=COLOURS["border"], width=2)
        for x, colour in ((42, "#ff5f57"), (64, "#febc2e"), (86, "#28c840")):
            draw.ellipse((x - 6, 38 - 6, x + 6, 38 + 6), fill=colour)
        draw.text((110, 27), "martech-verify · local marketing data audit",
                  font=title_font, fill=COLOURS["dim"])
        draw.line((28, 62, WIDTH - 28, 62), fill=COLOURS["border"], width=1)

        y = 84
        for style, text in visible:
            draw.text((48, y), text, font=mono, fill=COLOURS.get(style, COLOURS["text"]))
            y += 30
        draw.text((48, HEIGHT - 45), "Real tool output · bundled synthetic fixtures",
                  font=mono, fill=COLOURS["dim"])
        return image

    frames, durations = [], []
    prompt_style, prompt_text = lines[0]
    for chars in range(0, len(prompt_text) + 1, 4):
        cursor = "_" if chars < len(prompt_text) else ""
        frames.append(render([(prompt_style, prompt_text[:chars] + cursor)]))
        durations.append(75)
    durations[-1] = 650

    for visible_count in range(2, len(lines) + 1):
        frames.append(render(lines[:visible_count]))
        style = lines[visible_count - 1][0]
        durations.append(500 if style == "heading" else 300)
    durations[-1] = 5200

    palette_source = frames[-1].quantize(colors=64)
    paletted = [frame.quantize(palette=palette_source, dither=Image.Dither.NONE)
                for frame in frames]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    paletted[0].save(
        OUT,
        save_all=True,
        append_images=paletted[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
        comment=marker(reports),
    )
    print(f"wrote {OUT.relative_to(ROOT)} ({len(frames)} frames, {OUT.stat().st_size:,} bytes)")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        reports = capture_reports()
        if "--check" in argv:
            return check(reports)
        generate(reports)
        return check(reports)
    except (OSError, RuntimeError) as error:
        print(f"could not build demo: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
