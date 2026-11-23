"""Run structural WCAG 2.2 AA checks against the LibraryTO source.

This is a source-level regression check, not a substitute for testing the
running application with real browsers, zoom, keyboard and screen readers.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def luminance(hex_color: str) -> float:
    value = hex_color.lstrip("#")
    channels = [int(value[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(first: str, second: str) -> float:
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def theme_tokens(css: str, selector: str) -> dict[str, str]:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    if not match:
        raise AssertionError(f"Missing theme token block: {selector}")
    tokens = dict(re.findall(r"(--[a-z-]+)\s*:\s*(#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?)", match.group(1)))
    return {key: ("#" + "".join(character * 2 for character in value[1:]) if len(value) == 4 else value) for key, value in tokens.items()}


def main() -> int:
    template = (ROOT / "templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/css/app.css").read_text(encoding="utf-8")
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    enhancement = (ROOT / "static/js/graph-enhancements.js").read_text(encoding="utf-8")

    checks: list[tuple[str, bool]] = []
    checks.append(("Document language is declared", bool(re.search(r'<html[^>]+lang="en"', template))))
    checks.append(("Viewport metadata is present", 'name="viewport"' in template))
    checks.append(("Skip link and main landmark are present", 'class="skip-link"' in template and '<main id="main"' in template))
    checks.append(("Primary navigation has an accessible name", 'aria-label="Primary navigation"' in template and 'aria-label="Main"' in template))
    checks.append(("Dynamic tabs expose tab semantics", 'role="tablist"' in js and 'role="tab"' in js and 'role="tabpanel"' in js and 'aria-selected' in js))
    checks.append(("Tabs support arrow, Home and End keyboard navigation", all(key in js for key in ("ArrowRight", "ArrowLeft", "Home", "End"))))
    checks.append(("Keyboard focus styles are defined", ":focus-visible" in css and "outline:3px solid var(--focus)" in css))
    checks.append(("Reduced-motion preference is respected", "prefers-reduced-motion:reduce" in css))
    checks.append(("Main interactive controls meet 44px minimum target height", all(token in css for token in ("min-height:44px"))))
    checks.append(("Charts have programmatic labels", 'role="img" aria-label="Interactive chart:' in js))
    checks.append(("Question forms and search inputs have labels", all(token in js for token in ('for="overview-question"', 'for="branch-question"', 'for="compare-search"'))))
    checks.append(("Branch Explorer and activity-intensity tables expose captions and header scopes", '<caption class="visually-hidden">' in enhancement and 'scope="col"' in enhancement and 'scope="row"' in enhancement))
    checks.append(("Loading and error updates have status semantics", 'role="status"' in enhancement and 'role="alert"' in enhancement))

    light = theme_tokens(css, ":root")
    dark = theme_tokens(css, ":root[data-theme=dark]")
    contrast_pairs = (
        ("Light normal text", light["--text"], light["--page"]),
        ("Light muted text", light["--muted"], light["--page"]),
        ("Light links", light["--accent"], light["--surface"]),
        ("Light button text", light["--button-text"], light["--accent"]),
        ("Light focus indicator", light["--focus"], light["--surface"]),
        ("Dark normal text", dark["--text"], dark["--page"]),
        ("Dark muted text", dark["--muted"], dark["--page"]),
        ("Dark links", dark["--accent"], dark["--surface"]),
        ("Dark button text", dark["--button-text"], dark["--accent"]),
        ("Dark focus indicator", dark["--focus"], dark["--surface"]),
    )
    print("LibraryTO source-level accessibility validation")
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {label}")
    for label, foreground, background in contrast_pairs:
        ratio = contrast(foreground, background)
        passed = ratio >= 4.5
        print(f"{'PASS' if passed else 'FAIL'}  {label}: {ratio:.2f}:1")
        checks.append((label, passed))

    failed = [label for label, passed in checks if not passed]
    if failed:
        print("\nAccessibility source checks failed:")
        for label in failed:
            print(f"- {label}")
        return 1
    print("\nAll source-level checks passed. Manual WCAG 2.2 AA testing is still required; see ACCESSIBILITY_VALIDATION.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
