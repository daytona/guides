# Copyright 2026 Daytona Platforms Inc.
# SPDX-License-Identifier: Apache-2.0

"""Verification for the agent's task.

The agent's goal is to create solution.py so that `python tests.py` exits 0.
This pass/fail signal is exactly the kind of verifiable outcome a reward
function consumes in reinforcement fine-tuning.
"""

import sys

try:
    from solution import slugify
except ImportError:
    print("FAIL could not import slugify from solution.py")
    sys.exit(1)

CASES = [
    ("Hello, World!", "hello-world"),
    ("  multiple   spaces  ", "multiple-spaces"),
    ("Üñíçôdé Çafé", "unicode-cafe"),
    ("already-slugged", "already-slugged"),
    ("Dots.and_underscores", "dots-and-underscores"),
    ("--Trim--Hyphens--", "trim-hyphens"),
    ("", ""),
]


def main() -> None:
    failures = 0
    for text, expected in CASES:
        try:
            actual = slugify(text)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the run
            print(f"FAIL slugify({text!r}) raised {exc!r}")
            failures += 1
            continue
        if actual == expected:
            print(f"PASS slugify({text!r}) == {expected!r}")
        else:
            print(f"FAIL slugify({text!r}) == {actual!r}, expected {expected!r}")
            failures += 1

    if failures:
        print(f"{failures} test(s) failed")
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
