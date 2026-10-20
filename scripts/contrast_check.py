"""Verify WCAG AA contrast for the frontend's colour tokens.

Accessibility was a stated requirement, not polish, so the claim "contrast in
light and dark" should be evidence rather than assertion. This parses the tokens
straight out of `frontend/src/styles.css` so it cannot drift from the stylesheet.

Usage:
    python scripts/contrast_check.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "frontend" / "src" / "styles.css"

TOKEN_RE = re.compile(r"^(--[a-z-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;?\s*$")

# (foreground, background, minimum, what it is)
TEXT_PAIRS = [
    ("--fg", "--bg", 4.5, "body text"),
    ("--fg", "--card", 4.5, "body text on card"),
    ("--muted", "--bg", 4.5, "muted text"),
    ("--muted", "--card", 4.5, "muted text on card"),
    ("--accent-fg", "--accent", 4.5, "button label"),
    ("--error", "--bg", 4.5, "error text"),
    ("--error", "--card", 4.5, "error text on card"),
]

# Non-text UI (WCAG 1.4.11). The focus ring uses --accent, which is checked above.
UI_PAIRS = [
    ("--border", "--bg", 3.0, "card border"),
]


def parse_tokens(css_text: str):
    light = {}
    dark = {}
    mode = "light"
    for line in css_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@media") and "dark" in stripped:
            mode = "dark"
            continue
        match = TOKEN_RE.match(stripped)
        if match:
            target = dark if mode == "dark" else light
            target[match.group(1)] = match.group(2)
    return light, dark


def srgb_to_linear(channel: int) -> float:
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    digits = hex_colour.lstrip("#")
    if len(digits) == 3:
        digits = "".join(char * 2 for char in digits)
    red = int(digits[0:2], 16)
    green = int(digits[2:4], 16)
    blue = int(digits[4:6], 16)
    return (
        0.2126 * srgb_to_linear(red)
        + 0.7152 * srgb_to_linear(green)
        + 0.0722 * srgb_to_linear(blue)
    )


def contrast_ratio(foreground: str, background: str) -> float:
    a = luminance(foreground)
    b = luminance(background)
    lighter, darker = (a, b) if a >= b else (b, a)
    return (lighter + 0.05) / (darker + 0.05)


def check(mode_name: str, tokens, pairs, failures) -> None:
    print("[%s]" % (mode_name,))
    for foreground, background, minimum, label in pairs:
        if foreground not in tokens or background not in tokens:
            failures.append((mode_name, label, "token missing", 0.0, minimum))
            print("  %-22s MISSING TOKEN" % (label,))
            continue
        ratio = contrast_ratio(tokens[foreground], tokens[background])
        ok = ratio >= minimum
        if not ok:
            failures.append((mode_name, label, foreground, ratio, minimum))
        print(
            "  %-22s %s on %s  %5.2f:1  (min %.1f)  %s"
            % (
                label,
                tokens[foreground],
                tokens[background],
                ratio,
                minimum,
                "ok" if ok else "FAIL",
            )
        )
    print("")


def main() -> int:
    if not STYLES.exists():
        print("UNVERIFIED: %s not found" % (STYLES,))
        return 2

    light, dark = parse_tokens(STYLES.read_text(encoding="utf-8"))
    if not light or not dark:
        print("UNVERIFIED: could not parse both light and dark token blocks.")
        return 2

    failures = []
    check("light", light, TEXT_PAIRS + UI_PAIRS, failures)
    check("dark", dark, TEXT_PAIRS + UI_PAIRS, failures)

    if failures:
        print("FAILURES: %d" % (len(failures),))
        for mode_name, label, detail, ratio, minimum in failures:
            print("  %s / %s: %s %.2f < %.1f" % (mode_name, label, detail, ratio, minimum))
        return 1

    print("OK: every checked pair meets WCAG AA in light and dark.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
