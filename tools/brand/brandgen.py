#!/usr/bin/env python3
"""brandgen – generate brand constants for all components from one brand.json.

The display name and everything else the user sees as "the brand" lives in
exactly one file, `brand.json` at the root of this repository. The technical
namespace (domain, Bonjour type, URL scheme) is not part of it. This generator
turns it into

  swift/Brand.swift          Swift constants for the apps
  swift/Brand.xcconfig       BRAND_DISPLAY_NAME, BRAND_SHORT_NAME for Info.plist/build settings
  python/brand.py            constants for the hub and the integration
  ts/brand.ts                constants for the admin UI
  ha/addon-config.yaml       snippet with name/description/panel_title for config.yaml
  ha/manifest.json           snippet with the integration manifest "name"

Only the Python standard library is used. Exit codes: 0 ok, 1 check failed /
validation error, 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_BRAND = HERE.parent.parent / "brand.json"
DEFAULT_SCHEMA = HERE / "brand.schema.json"
GENERATOR = "brandgen.py"

TARGETS = ("swift", "python", "ts", "ha")


# --------------------------------------------------------------------------
# Minimal JSON-Schema validator (subset used by brand.schema.json)
# --------------------------------------------------------------------------

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def _resolve(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(instance: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """Return a list of human readable errors (empty = valid)."""
    root = root or schema
    schema = _resolve(schema, root)
    errors: list[str] = []
    typ = schema.get("type")
    if typ:
        py = _TYPES[typ]
        ok = isinstance(instance, py) and not (typ in ("integer", "number") and isinstance(instance, bool))
        if not ok:
            return [f"{path}: expected {typ}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']} ({len(instance)})")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']}")
        if schema.get("format") == "uri" and not re.match(r"^https?://[^\s/$.?#][^\s]*$", instance):
            errors.append(f"{path}: {instance!r} is not an http(s) URI")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(instance):
                errors += validate(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required key {key!r}")
        for key, value in instance.items():
            if key in props:
                errors += validate(value, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown key {key!r}")
    return errors


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_brand(brand_path: Path, schema_path: Path = DEFAULT_SCHEMA) -> dict:
    raw = brand_path.read_text(encoding="utf-8")
    brand = json.loads(raw)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = validate(brand, schema)
    if errors:
        raise ValueError("brand.json invalid:\n  " + "\n  ".join(errors))
    for key in brand.get("placeholders", []):
        node: Any = brand
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                raise ValueError(f"placeholders: unknown key {key!r}")
            node = node[part]
    # Hash of the content without "$schema", so copies with another schema path generate identically.
    canonical = json.dumps({k: v for k, v in brand.items() if k != "$schema"}, sort_keys=True, ensure_ascii=False)
    brand["_source_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    return brand


def copyright_line(brand: dict) -> str:
    legal = brand["legal"]
    return f"© {legal['copyright_start_year']} {legal['copyright_holder']}"


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------

def _swift_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(p.capitalize() for p in rest)


def _header(brand: dict, comment: str) -> str:
    return (
        f"{comment} Generated by {GENERATOR} from contracts/brand.json (sha256 {brand['_source_sha256']}).\n"
        f"{comment} Do not edit by hand – change brand.json and regenerate.\n"
    )


def render_swift(brand: dict) -> str:
    c = brand["colors"]
    lines = [_header(brand, "//"), "import Foundation", "#if canImport(SwiftUI)", "import SwiftUI", "#endif", ""]
    lines += [
        "/// sRGB color from the brand palette (platform-neutral, Sendable).",
        "public struct BrandColor: Sendable, Hashable {",
        "    public let red: Double",
        "    public let green: Double",
        "    public let blue: Double",
        "    public let hex: String",
        "}",
        "",
        "/// Display brand. Never use these values as technical identifiers.",
        "public enum Brand {",
        f"    public static let name = {_swift_str(brand['name'])}",
        f"    public static let shortName = {_swift_str(brand['short_name'])}",
        f"    public static let tagline = {_swift_str(brand['tagline'])}",
        f"    public static let summary = {_swift_str(brand['description'])}",
        f"    public static let copyright = {_swift_str(copyright_line(brand))}",
        f"    public static let copyrightHolder = {_swift_str(brand['legal']['copyright_holder'])}",
        f"    public static let copyrightStartYear = {brand['legal']['copyright_start_year']}",
        "",
        "    public enum URLs {",
    ]
    for key in ("website", "support", "privacy", "source"):
        lines.append(f"        public static let {key} = URL(string: {_swift_str(brand['urls'][key])})!")
    lines += ["    }", "", "    public enum Colors {"]
    for key, value in c.items():
        if isinstance(value, list):
            items = ", ".join(_swift_color(v) for v in value)
            lines.append(f"        public static let {_camel(key)}: [BrandColor] = [{items}]")
        else:
            lines.append(f"        public static let {_camel(key)} = {_swift_color(value)}")
    lines += ["    }", "}", "", "#if canImport(SwiftUI)", "extension BrandColor {",
              "    public var color: Color { Color(.sRGB, red: red, green: green, blue: blue, opacity: 1) }",
              "}", "#endif", ""]
    return "\n".join(lines)


def _swift_color(hex_color: str) -> str:
    r, g, b = _hex_rgb(hex_color)
    return (f"BrandColor(red: {r / 255:.4f}, green: {g / 255:.4f}, blue: {b / 255:.4f}, "
            f"hex: {_swift_str(hex_color)})")


def render_xcconfig(brand: dict) -> str:
    # xcconfig treats "//" as a comment start, so URLs are deliberately not exported here.
    return (
        _header(brand, "//")
        + "// Include from the target's base configuration (Project > Info > Configurations).\n"
        + f"BRAND_DISPLAY_NAME = {brand['apple']['display_name']}\n"
        + f"BRAND_SHORT_NAME = {brand['short_name']}\n"
    )


def render_python(brand: dict) -> str:
    d = json.dumps
    colors = ",\n".join(
        f"    {d(k)}: {('(' + ', '.join(d(x) for x in v) + ')') if isinstance(v, list) else d(v)}"
        for k, v in brand["colors"].items()
    )
    return (
        '"""Display brand. Never use these values as technical identifiers."""\n\n'
        + _header(brand, "#")
        + "from __future__ import annotations\n\n"
        + "from typing import Final\n\n"
        + "# fmt: off\n"
        + f"BRAND_NAME: Final = {d(brand['name'], ensure_ascii=False)}\n"
        + f"BRAND_SHORT_NAME: Final = {d(brand['short_name'], ensure_ascii=False)}\n"
        + f"BRAND_TAGLINE: Final = {d(brand['tagline'], ensure_ascii=False)}\n"
        + f"BRAND_DESCRIPTION: Final = {d(brand['description'], ensure_ascii=False)}\n"
        + f"BRAND_ADDON_DESCRIPTION: Final = {d(brand['home_assistant']['addon_description'], ensure_ascii=False)}\n"
        + f"BRAND_PANEL_TITLE: Final = {d(brand['home_assistant']['panel_title'], ensure_ascii=False)}\n"
        + f"BRAND_INTEGRATION_NAME: Final = {d(brand['home_assistant']['integration_name'], ensure_ascii=False)}\n"
        + f"BRAND_WEBSITE_URL: Final = {d(brand['urls']['website'])}\n"
        + f"BRAND_SUPPORT_URL: Final = {d(brand['urls']['support'])}\n"
        + f"BRAND_PRIVACY_URL: Final = {d(brand['urls']['privacy'])}\n"
        + f"BRAND_SOURCE_URL: Final = {d(brand['urls']['source'])}\n"
        + f"BRAND_COPYRIGHT: Final = {d(copyright_line(brand), ensure_ascii=False)}\n"
        + "BRAND_COLORS: Final = {\n" + colors + ",\n}\n"
    )


def render_ts(brand: dict) -> str:
    obj = {
        "name": brand["name"],
        "shortName": brand["short_name"],
        "tagline": brand["tagline"],
        "description": brand["description"],
        "panelTitle": brand["home_assistant"]["panel_title"],
        "copyright": copyright_line(brand),
        "urls": brand["urls"],
        "colors": {_camel(k): v for k, v in brand["colors"].items()},
    }
    body = json.dumps(obj, indent=2, ensure_ascii=False)
    return (
        _header(brand, "//")
        + "/** Display brand. Never use these values as technical identifiers. */\n"
        + f"export const BRAND = {body} as const;\n\n"
        + "export type Brand = typeof BRAND;\n"
        + "export default BRAND;\n"
    )


def render_addon_yaml(brand: dict) -> str:
    ha = brand["home_assistant"]
    d = lambda v: json.dumps(v, ensure_ascii=False)  # JSON strings are valid YAML scalars
    return (
        _header(brand, "#")
        + "# Brand fields for the add-on config.yaml (applied with --patch-addon-config).\n"
        + f"name: {d(ha['addon_name'])}\n"
        + f"description: {d(ha['addon_description'])}\n"
        + f"panel_title: {d(ha['panel_title'])}\n"
    )


def render_manifest(brand: dict) -> str:
    return json.dumps({"name": brand["home_assistant"]["integration_name"]}, indent=2, ensure_ascii=False) + "\n"


def render_all(brand: dict, targets: tuple[str, ...] = TARGETS) -> dict[str, str]:
    out: dict[str, str] = {}
    if "swift" in targets:
        out["swift/Brand.swift"] = render_swift(brand)
        out["swift/Brand.xcconfig"] = render_xcconfig(brand)
    if "python" in targets:
        out["python/brand.py"] = render_python(brand)
    if "ts" in targets:
        out["ts/brand.ts"] = render_ts(brand)
    if "ha" in targets:
        out["ha/addon-config.yaml"] = render_addon_yaml(brand)
        out["ha/manifest.json"] = render_manifest(brand)
    return out


# --------------------------------------------------------------------------
# Patchers for HA files (config.yaml is patched line-wise to keep comments)
# --------------------------------------------------------------------------

def patch_addon_config(text: str, brand: dict) -> str:
    ha = brand["home_assistant"]
    values = {"name": ha["addon_name"], "description": ha["addon_description"], "panel_title": ha["panel_title"]}
    out = []
    for line in text.splitlines(keepends=True):
        m = re.match(r"^(name|description|panel_title):(\s*)(.*?)(\r?\n)?$", line)
        if m:
            out.append(f"{m.group(1)}: {json.dumps(values[m.group(1)], ensure_ascii=False)}{m.group(4) or ''}")
        else:
            out.append(line)
    return "".join(out)


def patch_manifest(text: str, brand: dict) -> str:
    data = json.loads(text)
    data["name"] = brand["home_assistant"]["integration_name"]
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--brand", type=Path, default=DEFAULT_BRAND, help="brand.json (default: the one of this repository)")
    p.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    p.add_argument("--out", type=Path, help="output directory")
    p.add_argument("--only", default=",".join(TARGETS), help=f"comma list of {TARGETS}")
    p.add_argument("--check", action="store_true", help="do not write; fail if --out is stale")
    p.add_argument("--strict", action="store_true", help="fail if placeholders are listed")
    p.add_argument("--patch-addon-config", type=Path, metavar="CONFIG_YAML")
    p.add_argument("--patch-manifest", type=Path, action="append", default=[], metavar="MANIFEST_JSON",
                   help="set \"name\" in an integration manifest.json or hacs.json (repeatable)")
    p.add_argument("--emit", action="append", default=[], metavar="OUTPUT=PATH",
                   help="write one output (e.g. python/brand.py) to PATH; repeatable, honours --check")
    args = p.parse_args(argv)

    try:
        brand = load_brand(args.brand, args.schema)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"brandgen: {exc}", file=sys.stderr)
        return 1
    for key in brand.get("placeholders", []):
        print(f"brandgen: warning: {key} is still a placeholder", file=sys.stderr)
    if args.strict and brand.get("placeholders"):
        return 1

    rc = 0
    targets = tuple(t.strip() for t in args.only.split(",") if t.strip())
    unknown = set(targets) - set(TARGETS)
    if unknown:
        p.error(f"unknown targets {sorted(unknown)}")
    if args.out:
        for rel, content in render_all(brand, targets).items():
            dest = args.out / rel
            if args.check:
                current = dest.read_text(encoding="utf-8") if dest.exists() else None
                if current != content:
                    print(f"brandgen: stale {dest}", file=sys.stderr)
                    rc = 1
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
                print(f"wrote {dest}")
    if args.emit:
        rendered = render_all(brand)
        for spec in args.emit:
            key, sep, dest = spec.partition("=")
            if not sep or key not in rendered:
                p.error(f"--emit expects OUTPUT=PATH with OUTPUT in {sorted(rendered)}: {spec!r}")
            dest_path = Path(dest)
            current = dest_path.read_text(encoding="utf-8") if dest_path.exists() else None
            if args.check:
                if current != rendered[key]:
                    print(f"brandgen: stale {dest_path}", file=sys.stderr)
                    rc = 1
            elif current != rendered[key]:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_text(rendered[key], encoding="utf-8")
                print(f"wrote {dest_path}")
    patches = [(args.patch_addon_config, patch_addon_config)] + [(m, patch_manifest) for m in args.patch_manifest]
    for path, fn in patches:
        if not path:
            continue
        old = path.read_text(encoding="utf-8")
        new = fn(old, brand)
        if args.check:
            if old != new:
                print(f"brandgen: stale {path}", file=sys.stderr)
                rc = 1
        elif old != new:
            path.write_text(new, encoding="utf-8")
            print(f"patched {path}")
    if not (args.out or args.emit or args.patch_addon_config or args.patch_manifest):
        print("brand.json valid")
    return rc


if __name__ == "__main__":
    sys.exit(main())
