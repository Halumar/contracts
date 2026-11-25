#!/usr/bin/env python3
"""License gate of the contract (Apache-2.0).

* LICENSE is the unchanged Apache License 2.0 text (GitHub detects it as Apache-2.0).
* NOTICE names the copyright holder and the third-party material in the contract.

  python tools/check_licenses.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# sha256 of https://www.apache.org/licenses/LICENSE-2.0.txt
APACHE_2_0 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
NOTICE_MUST_NAME = ("Copyright 2026 xonatec", "RFC 9180", "IETF Trust")


def main() -> int:
    problems = []
    if hashlib.sha256((REPO / "LICENSE").read_bytes()).hexdigest() != APACHE_2_0:
        problems.append("LICENSE is not the unchanged Apache License 2.0 text")
    notice = (REPO / "NOTICE").read_text(encoding="utf-8")
    problems += [f"NOTICE does not name {s!r}" for s in NOTICE_MUST_NAME if s not in notice]
    for p in problems:
        print(f"  - {p}")
    print("licenses: ok" if not problems else f"licenses: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
