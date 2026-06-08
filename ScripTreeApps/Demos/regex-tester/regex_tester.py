#!/usr/bin/env python3
"""
regex_tester.py — demo backing script for the v0.8.0a48 'regex' widget.

Reads two positional args (pattern, sample) from the ScripTree
form, runs ``re.finditer`` on the sample with the pattern, and
prints a tidy match report so the user can verify the pattern
behaves as expected on real input.

The pattern's inline-flag prefix (``(?i)``, ``(?im)`` etc., set
via the helper dialog's flag checkboxes) is honoured natively by
``re`` — no flag-stripping needed here.
"""
from __future__ import annotations

import re
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "usage: regex_tester.py <pattern> <sample>",
            file=sys.stderr,
        )
        return 2
    pattern, sample = argv[1], argv[2]

    try:
        rx = re.compile(pattern)
    except re.error as exc:
        print(f"regex did not compile: {exc}", file=sys.stderr)
        return 1

    matches = list(rx.finditer(sample))
    print(f"Pattern: {pattern}")
    print(f"Sample : {len(sample):,} chars, "
          f"{sample.count(chr(10)) + 1} line(s)")
    print(f"Matches: {len(matches)}")
    print("-" * 60)
    if not matches:
        print("(no matches)")
        return 0
    for i, m in enumerate(matches, start=1):
        text = m.group(0)
        start, end = m.start(), m.end()
        print(f"#{i:>3}  span {start}-{end:<5}  {text!r}")
        # Numbered captures.
        for g in range(1, (rx.groups or 0) + 1):
            try:
                cap = m.group(g)
            except IndexError:
                cap = None
            if cap is not None:
                print(f"        group {g}: {cap!r}")
        # Named captures.
        if m.groupdict():
            for name, val in m.groupdict().items():
                if val is not None:
                    print(f"        <{name}>: {val!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
