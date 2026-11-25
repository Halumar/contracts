#!/usr/bin/env python3
"""Check data/tile-icons.json against the real icon sets.

  python tools/check_tile_icons.py [--mdi-paths <hub repo>/<add-on dir>/rootfs/opt/hub/data/mdi_paths.py]
                                   [--mdi-js <frontend>/node_modules/@mdi/js/mdi.js]
                                   [--mdi-meta <frontend>/node_modules/@mdi/svg/meta.json]
                                   [--sf-availability /System/Library/CoreServices/CoreGlyphs.bundle/Contents/Resources/name_availability.plist]

* MDI: every ``mdi`` name exists in the hub's MDI table (``mdi_paths.py``, the same names the
  hub resolves to ``icon_svg``) and/or in ``@mdi/js`` (``mdiFloorLamp`` -> ``floor-lamp``).
* MDI brands: no ``mdi`` name is a brand/logo icon or deprecated (``@mdi/svg`` meta.json, tag
  "Brand / Logo"; the Pictogrammers Free License does not cover these icons, see LICENSE).
* SF Symbols (macOS only, needs ``plutil``): every ``sf`` name exists, is not a restricted
  symbol (``symbol_restrictions.strings``, Apple product symbols) and ``sf_min_os`` is the later
  of the iOS and tvOS release that introduced it.

The SF part cannot run in Linux CI; run it on a Mac whenever the icon set changes. Exit 1 on
any finding, 0 otherwise; sources that are not given or not found are skipped with a note.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BRAND_TAG = "Brand / Logo"
CORE_GLYPHS = Path("/System/Library/CoreServices/CoreGlyphs.bundle/Contents/Resources")


def plist_json(path: Path):
    out = subprocess.run(["plutil", "-convert", "json", "-o", "-", str(path)], check=True, capture_output=True)
    return json.loads(out.stdout)


def mdi_names_from_hub(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "MDI_PATHS":
            return {k.value for k in node.value.keys}
    raise SystemExit(f"{path}: MDI_PATHS not found")


def mdi_names_from_js(path: Path) -> set[str]:
    names = set()
    for m in re.finditer(r"export var mdi([A-Za-z0-9]+)\s*=", path.read_text(encoding="utf-8")):
        names.add(re.sub(r"(?<!^)(?=[A-Z])", "-", m.group(1)).lower())
    return names


def version(v: str) -> tuple[int, int]:
    parts = [int(p) for p in v.split(".")] + [0]
    return parts[0], parts[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mdi-paths", type=Path)
    ap.add_argument("--mdi-js", type=Path)
    ap.add_argument("--mdi-meta", type=Path)
    ap.add_argument("--sf-availability", type=Path, default=CORE_GLYPHS / "name_availability.plist")
    args = ap.parse_args()

    icons = json.loads((REPO / "data/tile-icons.json").read_text(encoding="utf-8"))["icons"]
    problems: list[str] = []

    for label, path, loader in (("hub MDI table", args.mdi_paths, mdi_names_from_hub), ("@mdi/js", args.mdi_js, mdi_names_from_js)):
        if not path:
            continue
        names = loader(path)
        missing = [i["mdi"] for i in icons if i["mdi"] not in names]
        problems += [f"mdi:{n} not in {label}" for n in missing]
        print(f"{label}: {len(icons) - len(missing)}/{len(icons)} found")

    if args.mdi_meta:
        meta = {i["name"]: i for i in json.loads(args.mdi_meta.read_text(encoding="utf-8"))}
        for i in icons:
            m = meta.get(i["mdi"])
            if m is None:
                problems.append(f"mdi:{i['mdi']} not in @mdi/svg meta.json")
            elif BRAND_TAG in m.get("tags", []) or m.get("deprecated"):
                problems.append(f"mdi:{i['mdi']} is a brand/logo or deprecated icon")
        print(f"MDI brand icons: {len(icons)} checked against {args.mdi_meta}")

    if args.sf_availability.exists():
        avail = plist_json(args.sf_availability)
        restricted = plist_json(args.sf_availability.parent / "symbol_restrictions.strings")
        symbols, releases = avail["symbols"], avail["year_to_release"]
        for i in icons:
            sf = i["sf"]
            if sf not in symbols:
                problems.append(f"sf:{sf} does not exist")
                continue
            if sf in restricted:
                problems.append(f"sf:{sf} is a restricted symbol")
            rel = releases[symbols[sf]]
            want = max(version(rel["iOS"]), version(rel["tvOS"]))
            if version(i["sf_min_os"]) != want:
                problems.append(f"sf:{sf} sf_min_os {i['sf_min_os']} != {want[0]}.{want[1]}")
        print(f"SF Symbols: {len(icons)} checked against {args.sf_availability}")
    else:
        print("SF Symbols: skipped (no CoreGlyphs availability list, macOS only)")

    for p in problems:
        print(f"  - {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
