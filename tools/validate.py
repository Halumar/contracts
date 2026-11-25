#!/usr/bin/env python3
"""Validate the contracts repo.

Checks (all must pass, exit code 1 otherwise):
  1. every file under schemas/ is a valid JSON Schema 2020-12 and all $refs resolve
  2. every fixture validates against its schema (fixtures/<schema path>/<case>.json);
     cases named invalid-*.json MUST fail; WebSocket fixtures also validate against
     the direction union (schemas/ws/client-message.json / server-message.json)
  3. coverage: every non-shared schema has at least one valid fixture
  4. semantic checks: deep link uri <-> params (pairing and onboarding QR), compliance,
     settings-PIN and onboarding-seal (HPKE, RFC 9180) known-answer vectors are recomputed (the
     watch-access-v1 case also against crypto/watch-access-plaintext.json)
  5. OpenAPI documents are valid OpenAPI 3.1 (openapi-spec-validator), external
     $refs exist, every operation carries x-auth and security
  6. AsyncAPI document: version 3.0.0, all $refs resolve, every WebSocket schema
     is used by a message, operations only reference channel messages; with
     --asyncapi-schema FILE additionally validated against the official
     AsyncAPI 3.0.0 JSON Schema (CI also runs the AsyncAPI CLI)
  7. namespace.json: schema-valid, x-namespace-key references exist, the current
     namespace literal appears only in files listed in literal_scope
  8. fixture hygiene: no JWTs, private keys or bearer headers in fixtures
  9. data files: data/<name>.json validates against schemas/data/<name>.json (counts as
     coverage) plus consistency checks (tile capabilities: every domain once, exactly one
     _other row, defaults allowed everywhere, run targets/sensor domains match the
     defs.json patterns; tile icons: unique mdi/sf names, known categories, every
     category used; quick access: every domain once, exactly one _other row, default <= max,
     critical domains never default to control, safe_direction only on critical domains; control allowlist:
     every domain once, unique actions and fields, no forbidden field allowed, ranges and list sizes consistent,
     safe actions only where quick access has a safe direction). The MDI/SF names themselves are checked by
     tools/check_tile_icons.py.
 10. rule snapshots: rules_hash recomputed from the canonical JSON, kids exactly with parental controls,
     kids entries only for listed entities; control_paths next to them names every snapshot device with
     its control_path (it may name more devices); client_config.ha_enforcement agrees with rules.control_path.
 11. family manager: data/family.json consistent with the catalog (manageable rules with the Fixed
     checkbox, categories/presets/notify defaults), every vector in fixtures/profiles/family-check against
     tools/family_ref.py; client_config.family exactly with rules.family_manager true, never on guests or child
     devices; kids.requests never offers more than rules.kids_requests; kids.paused_all_until only with
     rules.kids_rate_limit_all enabled.
 11a. early access: client_config.access.request exactly with rules.access_requests true; available only while
     closed by the schedule without an own open request; access-hours vectors with early against tools/access_ref.py.
 12. profile kinds: setup_devices.kinds and setup-grant kinds hold every $defs/profile_kind.
 13. watch limit: limit_to is the meet of watch and phone, never more than either at any moment.
 13. home networks: every vector in fixtures/network/home-networks against tools/home_networks_ref.py;
     home_networks in client_config, rule snapshots (the same list in every snapshot) and the pairing link hn
     are in normalized form (canonical, private ranges only, sorted, no overlaps, max 10).
 14. room climate: data/room-climate.json keywords in normalized form, unique groups; every vector in
     fixtures/climate/room-climate-vector against tools/room_climate_ref.py.

Usage: python tools/validate.py [--asyncapi-schema PATH] [-v]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import hmac
import json
import re
import sys
import urllib.parse
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO = Path(__file__).resolve().parent.parent
SCHEMAS = REPO / "schemas"
FIXTURES = REPO / "fixtures"
DATA = REPO / "data"
SHARED_PREFIXES = ("common/", "meta/", "ws/client-message.json", "ws/server-message.json")

errors: list[str] = []
infos: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def rel(p: Path) -> str:
    return p.relative_to(REPO).as_posix()


# ── schema loading ────────────────────────────────────────────────────────────


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        fail(f"{rel(path)}: invalid JSON ({exc})")
        return None


def with_id(doc: dict, path: Path) -> dict:
    doc = dict(doc)
    doc["$id"] = path.resolve().as_uri()
    return doc


def retrieve(uri: str) -> Resource:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        raise LookupError(f"only local refs are allowed: {uri}")
    path = Path(urllib.parse.unquote(parsed.path))
    return Resource.from_contents(with_id(json.loads(path.read_text()), path), default_specification=DRAFT202012)


REGISTRY = Registry(retrieve=retrieve)
_validators: dict[Path, Draft202012Validator] = {}


def validator_for(schema_path: Path) -> Draft202012Validator:
    if schema_path not in _validators:
        doc = with_id(json.loads(schema_path.read_text()), schema_path)
        _validators[schema_path] = Draft202012Validator(
            doc, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
        )
    return _validators[schema_path]


def iter_refs(node, path=()):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from iter_refs(v, path + (k,))
    elif isinstance(node, list):
        for item in node:
            yield from iter_refs(item, path)


def resolve_pointer(doc, pointer: str):
    node = doc
    for part in [p for p in pointer.split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def check_ref(base_file: Path, ref: str, cache: dict) -> str | None:
    file_part, _, frag = ref.partition("#")
    target = (base_file.parent / file_part).resolve() if file_part else base_file
    if not target.exists():
        return f"{rel(base_file)}: $ref target missing: {ref}"
    if frag:
        if target not in cache:
            text = target.read_text()
            cache[target] = yaml.safe_load(text) if target.suffix in (".yaml", ".yml") else json.loads(text)
        try:
            resolve_pointer(cache[target], frag)
        except (KeyError, IndexError, ValueError):
            return f"{rel(base_file)}: $ref fragment not found: {ref}"
    return None


def check_schemas() -> list[Path]:
    paths = sorted(SCHEMAS.rglob("*.json"))
    cache: dict = {}
    for p in paths:
        doc = load_json(p)
        if doc is None:
            continue
        try:
            Draft202012Validator.check_schema(doc)
        except Exception as exc:  # noqa: BLE001
            fail(f"{rel(p)}: not a valid JSON Schema 2020-12: {exc.message if hasattr(exc, 'message') else exc}")
        for ref in iter_refs(doc):
            if ref.startswith("#"):
                try:
                    resolve_pointer(doc, ref[1:])
                except (KeyError, IndexError, ValueError):
                    fail(f"{rel(p)}: local $ref not found: {ref}")
            else:
                err = check_ref(p, ref, cache)
                if err:
                    fail(err)
    infos.append(f"schemas: {len(paths)} files")
    return paths


# ── fixtures ──────────────────────────────────────────────────────────────────


def schema_for_fixture(fx: Path) -> Path:
    return SCHEMAS / (fx.parent.relative_to(FIXTURES).as_posix() + ".json")


def union_for(schema_path: Path) -> Path | None:
    r = schema_path.relative_to(SCHEMAS).as_posix()
    if r.startswith("ws/client/"):
        return SCHEMAS / "ws/client-message.json"
    if r.startswith(("ws/server/", "ws/command/", "ws/broadcast/", "ws/integration/")):
        return SCHEMAS / "ws/server-message.json"
    return None


def check_fixtures(schema_paths: list[Path], verbose: bool) -> None:
    covered: set[Path] = set()
    fixtures = sorted(FIXTURES.rglob("*.json"))
    n_valid = n_invalid = 0
    for fx in fixtures:
        schema_path = schema_for_fixture(fx)
        if not schema_path.exists():
            fail(f"{rel(fx)}: no schema at {rel(schema_path)}")
            continue
        data = load_json(fx)
        if data is None:
            continue
        schema_rel = schema_path.relative_to(SCHEMAS).as_posix()
        errs = sorted(validator_for(schema_path).iter_errors(data), key=lambda e: list(e.path))
        messages = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs]
        if not errs:
            messages += semantic_checks(schema_rel, data)
        expect_invalid = fx.name.startswith("invalid-")
        if expect_invalid:
            n_invalid += 1
            if not messages:
                fail(f"{rel(fx)}: expected to be INVALID against {rel(schema_path)} but validates")
            elif fx.name.startswith("invalid-semantic-") and errs:
                fail(f"{rel(fx)}: invalid-semantic-* must pass the schema and fail only the semantic check ({messages[0]})")
            elif verbose:
                infos.append(f"  ok (rejected as expected) {rel(fx)}: {messages[0]}")
            continue
        n_valid += 1
        for m in messages[:3]:
            fail(f"{rel(fx)}: {m}")
        if not messages:
            covered.add(schema_path)
        union = union_for(schema_path)
        if union is not None or schema_path.relative_to(SCHEMAS).as_posix().startswith("ws/heartbeat/"):
            unions = [union] if union else [SCHEMAS / "ws/client-message.json", SCHEMAS / "ws/server-message.json"]
            for u in unions:
                if not validator_for(u).is_valid(data):
                    fail(f"{rel(fx)}: does not validate against union {rel(u)}")
    covered |= check_data()
    for sp in schema_paths:
        r = sp.relative_to(SCHEMAS).as_posix()
        if r.startswith(SHARED_PREFIXES):
            continue
        if sp not in covered:
            fail(f"coverage: no valid fixture for schemas/{r}")
    infos.append(f"fixtures: {n_valid} valid, {n_invalid} expected-invalid")


def check_data() -> set[Path]:
    """Validate data/<name>.json against schemas/data/<name>.json (+ semantic checks)."""
    covered: set[Path] = set()
    for f in sorted(DATA.glob("*.json")) if DATA.exists() else []:
        schema_path = SCHEMAS / "data" / f.name
        if not schema_path.exists():
            fail(f"{rel(f)}: no schema at {rel(schema_path)}")
            continue
        data = load_json(f)
        if data is None:
            continue
        errs = sorted(validator_for(schema_path).iter_errors(data), key=lambda e: list(e.path))
        messages = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs]
        if not errs:
            messages += semantic_checks(f"data/{f.name}", data)
        for m in messages[:5]:
            fail(f"{rel(f)}: {m}")
        if not messages:
            covered.add(schema_path)
    infos.append(f"data: {len(covered)} file(s) valid")
    return covered


def _defs_pattern(name: str) -> re.Pattern:
    defs = json.loads((SCHEMAS / "common/defs.json").read_text())["$defs"]
    return re.compile(defs[name]["pattern"])


def tile_capability_checks(data) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    others = 0
    for i, row in enumerate(data["domains"]):
        for d in row["domains"]:
            if d == "_other":
                others += 1
            if d in seen:
                out.append(f"domains/{i}: domain {d} already in row {seen[d]}")
            seen[d] = i
        if data["defaults"]["variant"] not in row["variants"]:
            out.append(f"domains/{i}: default variant {data['defaults']['variant']} missing")
        for key in ("variants", "attributes", "tap_actions"):
            if len(set(row[key])) != len(row[key]):
                out.append(f"domains/{i}: duplicate value in {key}")
        extra = set(row["tap_actions"]) & set(data["always"]["tap_actions"])
        if extra:
            out.append(f"domains/{i}: {sorted(extra)} already in always.tap_actions")
        if row["confirm"] and not row["tap_actions"]:
            out.append(f"domains/{i}: confirm without toggle/run")
        if row["confirm_always"] and row["confirm"]:
            out.append(f"domains/{i}: confirm_always and confirm")
        if row["run_self"] and "run" not in row["tap_actions"]:
            out.append(f"domains/{i}: run_self without run")
    if others != 1:
        out.append(f"exactly one _other row expected, found {others}")
    d = data["defaults"]
    if d["tap_action"] not in data["always"]["tap_actions"] or d["hold_action"] not in data["always"]["hold_actions"]:
        out.append("defaults.tap_action/hold_action must be in always")
    if d["secondary"] not in data["always"]["secondary_sources"]:
        out.append("defaults.secondary must be in always.secondary_sources")
    run_pat = _defs_pattern("tile_run_target")
    for t in data["run_targets"]:
        if not run_pat.search(f"{t['domain']}.x") or not t["service"].startswith(t["domain"] + "."):
            out.append(f"run_targets: {t} does not match defs.json tile_run_target")
    if {t["domain"] for t in data["run_targets"]} != set(re.findall(r"[a-z_]+", run_pat.pattern.split(")")[0])):
        out.append("run_targets domains differ from defs.json tile_run_target")
    sec = json.loads((SCHEMAS / "common/defs.json").read_text())["$defs"]["tile_secondary"]["properties"]["entity_id"]["pattern"]
    for dom in data["secondary_entity_domains"]:
        if not re.search(sec, f"{dom}.x"):
            out.append(f"secondary_entity_domains: {dom} not allowed by tile_secondary.entity_id")
    return out


def tile_icon_checks(data) -> list[str]:
    out: list[str] = []
    cats = [c["id"] for c in data["categories"]]
    if len(set(cats)) != len(cats):
        out.append("duplicate category id")
    used = set()
    for key in ("mdi", "sf"):
        names = [i[key] for i in data["icons"]]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            out.append(f"duplicate {key} names: {dup}")
    icon_pat = _defs_pattern("tile_icon")
    for i, icon in enumerate(data["icons"]):
        used.add(icon["category"])
        if icon["category"] not in cats:
            out.append(f"icons/{i}: unknown category {icon['category']}")
        if not icon_pat.search("mdi:" + icon["mdi"]) or not icon_pat.search("sf:" + icon["sf"]):
            out.append(f"icons/{i}: name does not match defs.json tile_icon")
    if set(cats) - used:
        out.append(f"categories without icons: {sorted(set(cats) - used)}")
    return out


QUICK_ACCESS_ORDER = {"off": 0, "status": 1, "control": 2}


def quick_access_checks(data) -> list[str]:
    out: list[str] = []
    seen: dict[str, int] = {}
    others = 0
    for i, row in enumerate(data["domains"]):
        for d in row["domains"]:
            if d == "_other":
                others += 1
            if d in seen:
                out.append(f"domains/{i}: domain {d} already in row {seen[d]}")
            seen[d] = i
        if QUICK_ACCESS_ORDER[row["default"]] > QUICK_ACCESS_ORDER[row["max"]]:
            out.append(f"domains/{i}: default {row['default']} above max {row['max']}")
        critical = row["critical"] or row["critical_device_classes"]
        if row["critical"] and row["default"] == "control":
            out.append(f"domains/{i}: a critical domain must not default to control")
        if row["safe_direction"] is not None and not row["critical"]:
            out.append(f"domains/{i}: safe_direction only for critical domains")
        if critical and row["max"] != "control":
            out.append(f"domains/{i}: critical without control is meaningless")
    if others != 1:
        out.append(f"exactly one _other row expected, found {others}")
    return out


KIDS_RULE_FIELDS = {"blocked_types": "kids_blocked_types", "quiet_hours": "kids_quiet_hours", "rate_limit": "kids_rate_limit",
                    "color_lock": "kids_color_lock", "volume_max": "kids_volume_max"}


def control_allowlist_checks(data) -> list[str]:
    """The allowlist the integration action enforces."""
    out: list[str] = []
    forbidden = set(data["forbidden_fields"])
    seen: set[str] = set()
    qa = json.loads((DATA / "quick-access.json").read_text())
    safe_dir = {d: row["safe_direction"] for row in qa["domains"] for d in row["domains"]}
    for i, dom in enumerate(data["domains"]):
        name = dom["domain"]
        if name in seen:
            out.append(f"domains/{i}: domain {name} twice")
        seen.add(name)
        actions = [a["action"] for a in dom["actions"]]
        if len(set(actions)) != len(actions):
            out.append(f"domains/{i} ({name}): duplicate action")
        for a in dom["actions"]:
            where = f"{name}.{a['action']}"
            fields = [f["name"] for f in a["fields"]]
            if len(set(fields)) != len(fields):
                out.append(f"{where}: duplicate field")
            if forbidden & set(fields):
                out.append(f"{where}: forbidden field allowed: {sorted(forbidden & set(fields))}")
            if len(fields) > data["limits"]["max_data_fields"]:
                out.append(f"{where}: more fields than limits.max_data_fields")
            if a["safe"] and safe_dir.get(name) is None:
                out.append(f"{where}: safe only on domains with a safe_direction in data/quick-access.json")
            for f in a["fields"]:
                t = f["type"]
                if ("min" in f) and ("max" in f) and f["min"] > f["max"]:
                    out.append(f"{where}.{f['name']}: min above max")
                if t in ("integer", "number", "integer_list", "number_list") and ("min" not in f or "max" not in f):
                    out.append(f"{where}.{f['name']}: numbers need min and max")
                if t in ("string", "string_list") and "max_length" not in f:
                    out.append(f"{where}.{f['name']}: strings need max_length")
                if t.endswith("_list") and "max_items" not in f:
                    out.append(f"{where}.{f['name']}: lists need max_items")
                if (t == "enum") != ("values" in f):
                    out.append(f"{where}.{f['name']}: values exactly for enum fields")
    for d, direction in safe_dir.items():
        if direction is not None and d in seen:
            dom = next(x for x in data["domains"] if x["domain"] == d)
            if not any(a["safe"] for a in dom["actions"]):
                out.append(f"{d}: quick access names a safe direction but no action is safe")
    by_name = {dom["domain"]: dom for dom in data["domains"]}
    targets = data["run_targets"]
    run_domains = [t["domain"] for t in targets["domains"]]
    if len(set(run_domains)) != len(run_domains):
        out.append("run_targets.domains: domain twice")
    for t in targets["domains"]:
        dom = by_name.get(t["domain"])
        if dom is None or not dom["release_required"]:
            out.append(f"run_targets.domains: {t['domain']} is no allowlist domain with release_required")
            continue
        known = {a["action"] for a in dom["actions"]}
        for action in t["actions"]:
            if action not in known:
                out.append(f"run_targets.domains: {t['domain']}.{action} is not an allowed action")
    if overlap := sorted(set(targets["read_only_domains"]) & seen):
        out.append(f"run_targets.read_only_domains: allowlist domains can be switched: {overlap}")
    return out


def event_taxonomy_checks(data) -> list[str]:
    """data/events.json agrees with $defs event_kind, alarm_kind and enforcement_event_type."""
    out: list[str] = []
    defs = json.loads((SCHEMAS / "common/defs.json").read_text())["$defs"]
    kinds = [k["kind"] for k in data["kinds"]]
    if len(set(kinds)) != len(kinds):
        out.append("duplicate kind")
    if kinds != defs["event_kind"]["enum"]:
        out.append("kinds differ from defs.json event_kind (same order required)")
    alarms = [k["kind"] for k in data["kinds"] if k["alarm"]]
    if alarms != defs["alarm_kind"]["enum"]:
        out.append("alarm kinds differ from defs.json alarm_kind")
    if any(k["alarm"] and k["category"] != "alarms" for k in data["kinds"]):
        out.append("alarm kinds belong to the category alarms")
    if any(k["alarm"] and k.get("important") for k in data["kinds"]):
        out.append("important marks kinds besides the alarms (alarm entries are always important)")
    integ = [k["kind"] for k in data["kinds"] if k["source"] == "integration"] + ["rules_applied"]
    if integ != defs["enforcement_event_type"]["enum"]:
        out.append("kinds with source integration (+ rules_applied) differ from defs.json enforcement_event_type")
    return out


def snapshot_hash(snapshot: dict) -> str:
    """rules_hash of a rule snapshot ($defs/rules_hash)."""
    body = {k: v for k, v in snapshot.items() if k not in ("rules_hash", "issued_at")}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_checks(snapshots: list, where: str = "snapshots") -> list[str]:
    out: list[str] = []
    for i, snap in enumerate(snapshots):
        if snapshot_hash(snap) != snap["rules_hash"]:
            out.append(f"{where}/{i}: rules_hash does not match the canonical JSON ({snapshot_hash(snap)})")
        if (snap["kids"] is not None) != snap["child_protection"]:
            out.append(f"{where}/{i}: kids is an object exactly with child_protection")
        if snap["kids"] is not None:
            extra = set(snap["kids"]["entities"]) - set(snap["entities"])
            if extra:
                out.append(f"{where}/{i}: kids entries for entities that are not listed: {sorted(extra)}")
        if not snap["remote_access"] and any(e["remote"] != "hidden" for e in snap["entities"].values()):
            out.append(f"{where}/{i}: without remote access every remote level is hidden")
        acc = snap.get("access")
        if acc is not None and not acc["hours"] and acc["windows"]:
            out.append(f"{where}/{i}: access.windows only with access.hours")
        out += home_networks_ref().check_list(snap["home_networks"], f"{where}/{i}/home_networks")
    if len({json.dumps(s["home_networks"]) for s in snapshots}) > 1:
        out.append(f"{where}: home_networks differ between snapshots (one list per household)")
    return out


def control_paths_checks(snapshots: list, control_paths: dict, where: str = "control_paths") -> list[str]:
    """control_paths next to the snapshots: every snapshot device with the snapshot's control path; it may
    name more devices (snapshot not built, HA user being provisioned)."""
    out = []
    for s in snapshots:
        got = control_paths.get(s["client_id"])
        if got != s["control_path"]:
            out.append(f"{where}: {s['client_id']} must be named with its snapshot's control_path "
                       f"{s['control_path']!r}, not {got!r}")
    return out


def home_networks_ref():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import home_networks_ref as ref  # noqa: PLC0415

    return ref


def room_climate_ref():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import room_climate_ref as ref  # noqa: PLC0415

    return ref


def room_climate_data_checks(data) -> list[str]:
    """Keywords in normalized form, unique group ids, no keyword in two groups."""
    out: list[str] = []
    normalize = room_climate_ref().normalize
    ids = [g["id"] for g in data["exclude"]["groups"]]
    if len(ids) != len(set(ids)):
        out.append("exclude.groups: ids not unique")
    seen: dict[str, str] = {}
    for group in data["exclude"]["groups"]:
        for key in ("contains", "prefixes"):
            for word in group[key]:
                if normalize(word) != word:
                    out.append(f"exclude.groups.{group['id']}.{key}: {word!r} is not normalized")
                if word in seen:
                    out.append(f"exclude.groups: {word!r} in {seen[word]} and {group['id']}")
                seen[word] = group["id"]
    if "entity_category" in ids:
        out.append("exclude.groups: entity_category is the reason of exclude.entity_categories")
    return out


# Profile kinds whose devices are guest accesses (catalog profile_kinds with guest_access).
GUEST_KINDS = ("guest", "house_sitter", "babysitter")


def client_config_checks(data) -> list[str]:
    """The hard fields of client_config must agree with the effective rules (second line of defence)."""
    out: list[str] = []
    if "home_networks" in data:
        out += home_networks_ref().check_list(data["home_networks"], "home_networks")
    rules = data.get("rules") or {}
    profile = data.get("profile") or {}
    child = bool(profile.get("child_protection"))

    def value(key):
        return (rules.get(key) or {}).get("value")

    kids_away = (data.get("kids") or {}).get("away")
    # The control path and whether the device holds its own HA key (tools/profiles_ref.py holds_key).
    # Parental controls without the rule count as the hub path (fail closed); without the rule and
    # without parental controls nothing can be said.
    # A missing or unknown rule counts as hub (fail closed), except in the admin variant without a profile.
    path = value("control_path")
    if data.get("profile") is None:
        path = None
    elif path not in ("hub", "checked", "direct"):
        path = "hub"
    guest_like = (data.get("access") or {}).get("kind") == "guest" or profile.get("kind") in GUEST_KINDS
    if path == "direct" and (child or guest_like):
        out.append("guests and devices with parental controls are never on control_path direct")
    key = None if path is None else (path in ("checked", "direct") or value("remote_access") is True)
    if data.get("ha_token") is not None and data.get("ha_enforcement") is None:
        out.append("ha_token only together with ha_enforcement")
    hours_open = ((data.get("access") or {}).get("hours") or {}).get("open") is not False
    if key and hours_open and data.get("ha_token") is None and not data.get("token_error"):
        out.append("a device that holds a key with open access gets ha_token, or token_error says why not "
                   "(pending, decryption_failed)")
    if data.get("token_error") and (data.get("ha_token") is not None or not key or not hours_open):
        out.append("token_error only when the device holds a key, its access is open and ha_token is null")
    if key is False:
        for field in ("ha_token", "ha_instance_id", "ha_enforcement"):
            if data.get(field) is not None:
                out.append(f"{field} only when the device holds a key (control_path checked or direct, "
                           f"or hub with remote_access true)")
    if (path == "hub" or child) and data.get("ha_instance_id") is not None and data.get("ha_token") is None:
        out.append("hub path: ha_instance_id only together with the HA key")
    if data.get("ha_url") is not None and value("remote_access") is not True:
        out.append("ha_url only with rules.remote_access.value true")
    if ("kids" in data) != child:
        out.append("kids must be present exactly when profile.child_protection is true")
    elif child:
        if (kids_away == "ha") != key:
            out.append("kids.away is ha exactly when the device holds a key (control_path checked, or hub with "
                       "remote_access true)")
        mirror = data["kids"]["rules"]["profile"]
        for field, key in KIDS_RULE_FIELDS.items():
            if key in rules and mirror.get(field) != value(key):
                out.append(f"kids.rules.profile.{field} differs from rules.{key}.value")
    if data.get("settings_pin_hash") is not None and value("app_settings") != "pin":
        out.append("settings_pin_hash only when rules.app_settings.value is pin")
    if (data.get("settings_pin_hash") is None) != (data.get("settings_pin_source") is None):
        out.append("settings_pin_source is set exactly when a PIN hash is sent")
    access_req = (data.get("access") or {}).get("request")
    hours = (data.get("access") or {}).get("hours") or {}
    if (access_req is not None) != (value("access_requests") is True):
        out.append("access.request must be present exactly when rules.access_requests.value is true")
    if access_req is not None and access_req.get("available") and not (
        access_req.get("enabled")
        and hours.get("open") is False
        and hours.get("reason") == "schedule"
        and access_req.get("open") is None
    ):
        out.append("access.request.available only when enabled, closed by the schedule and no own open request")
    family = data.get("family")
    access_kind = (data.get("access") or {}).get("kind")
    if (family is not None) != (value("family_manager") is True):
        out.append("family must be present exactly when rules.family_manager.value is true")
    if family is not None and (child or access_kind == "guest"):
        out.append("family never on guests or devices with parental controls")
    if child and (data.get("kids") or {}).get("requests") is not None and access_kind == "guest":
        out.append("kids.requests only on member child devices")
    kreq = (data.get("kids") or {}).get("requests")
    if child and kreq is not None:
        rule = value("kids_requests") or {}
        if kreq.get("enabled") and not rule.get("enabled"):
            out.append("kids.requests.enabled only when rules.kids_requests.value.enabled is true")
        if set(kreq.get("categories") or []) - set(rule.get("categories") or []):
            out.append("kids.requests.categories must be within rules.kids_requests.value.categories")
    if child and (data.get("kids") or {}).get("paused_all_until") and not (value("kids_rate_limit_all") or {}).get("enabled"):
        out.append("kids.paused_all_until only when rules.kids_rate_limit_all.value.enabled is true")
    enf = data.get("ha_enforcement")
    if enf is not None and data.get("ha_token") is None:
        out.append("ha_enforcement only with an HA token")
    if enf is not None and path is not None and enf["control_path"] != ("checked" if path == "hub" else path):
        out.append("ha_enforcement.control_path must be checked for control_path hub, else equal to "
                   "rules.control_path.value")
    hours = (data.get("access") or {}).get("hours") or {}
    if hours.get("open") is False:
        if data.get("ha_token") is not None or data.get("ha_url") is not None:
            out.append("access.hours.open false: ha_token and ha_url must be null")
        if (data.get("quick_access") or {}).get("entities"):
            out.append("access.hours.open false: quick_access.entities must be empty")
    if "access_hours" in rules and bool((value("access_hours") or {}).get("enabled")) != bool(hours.get("schedule")):
        out.append("access.hours.schedule must follow rules.access_hours.value.enabled")
    sitter = data.get("babysitter")
    if sitter is not None:
        if profile.get("kind") != "babysitter" or value("babysitter_requests") is not True:
            out.append("babysitter only on devices of kind babysitter with rules.babysitter_requests true")
        if sitter.get("active") and hours.get("open") is False:
            out.append("babysitter.active only while access.hours.open")
        if "access_end" in (sitter.get("presets") or []) and not sitter.get("access_until"):
            out.append("babysitter.presets: access_end only with access_until")
    qa = data.get("quick_access") or {}
    level = value("quick_access")
    if level in (None, "off") and qa.get("enabled"):
        out.append("quick_access.enabled must be false when rules.quick_access is off or missing")
    if level in ("status", "control") and (not qa.get("enabled") or qa.get("max") != level):
        out.append("quick_access.enabled/max must follow rules.quick_access")
    return out


def profile_checks(schema_rel: str, data) -> list[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import profile_rules  # noqa: PLC0415
    import profiles_ref  # noqa: PLC0415

    catalog = profiles_ref.load_catalog(REPO)
    if schema_rel == "data/profile-rules.json":
        return profile_rules.check(REPO)
    if schema_rel in ("data/family.json", "profiles/family-check.json"):
        import family_ref  # noqa: PLC0415

        if schema_rel == "data/family.json":
            return family_ref.check_family_data(data, catalog)
        return family_ref.run_family_vector(data, family_ref.load_family(REPO))
    if schema_rel == "profiles/resolve.json":
        return profiles_ref.run_resolve_vector(data, catalog, profiles_ref.load_suggestions(REPO))
    if schema_rel == "profiles/expiry.json":
        return profiles_ref.run_expiry_vector(data)
    if schema_rel == "profiles/ha-access.json":
        return profiles_ref.run_ha_access_vector(data, catalog)
    if schema_rel == "profiles/no-escalation.json":
        return profiles_ref.run_order_vector(data, catalog)
    if schema_rel == "profiles/access-hours.json":
        import access_ref  # noqa: PLC0415

        return access_ref.run_access_vector(data)
    if schema_rel == "rest/profile.json":
        out = []
        for access, per in (data.get("hub_remote_pairing") or {}).items():
            for platform in ("tvos", "android_tv", "watchos", "wearos"):
                if per.get(platform):
                    out.append(f"hub_remote_pairing.{access}.{platform}: never true on a TV or a watch")
        missing = [r["key"] for r in catalog["rules"] if r["key"] not in data["rules"]]
        if missing:
            out.append(f"rules: an answer contains every catalog rule, missing {missing}")
        always = [r["key"] for r in catalog["rules"] if not r["fixed_checkbox"] and r["key"] not in data["fixed"]]
        if always:
            out.append(f"fixed: rules without checkbox are always fixed, missing {always}")
        return out
    return []


HUB_PICTURE_ID = re.compile(r"^[0-9a-f]{16}$")
PICTURE_DOMAINS = ("media_player", "camera")


def relayed_state_checks(entity_id: str, state, where: str) -> list[str]:
    """A state the hub relays ($defs/hub_picture_id): attributes stay a free object, but
    hub_picture_id has its form and a media player or camera carries no entity_picture."""
    attrs = (state or {}).get("attributes") if isinstance(state, dict) else None
    if not isinstance(attrs, dict):
        return []
    out = []
    marker = attrs.get("hub_picture_id")
    if marker is not None and not (isinstance(marker, str) and HUB_PICTURE_ID.match(marker)):
        out.append(f"{where}: attributes.hub_picture_id must be 16 lowercase hex characters")
    if str(entity_id).split(".", 1)[0] in PICTURE_DOMAINS and "entity_picture" in attrs:
        out.append(f"{where}: a relayed {entity_id} carries hub_picture_id, never entity_picture")
    return out


def semantic_checks(schema_rel: str, data) -> list[str]:
    """Checks JSON Schema cannot express. Returns error messages."""
    out: list[str] = []
    if schema_rel == "ws/server/entity_state.json" and isinstance(data, dict):
        return relayed_state_checks(data.get("entity_id", ""), data.get("state"), "state")
    if schema_rel == "common/area-entity.json" and isinstance(data, dict):
        return relayed_state_checks(data.get("entity_id", ""), data.get("state"), "state")
    if schema_rel in ("rest/client-effective.response.json", "rest/profile-preview.response.json",
                      "integration/extend.response.json") and \
            isinstance(data, dict):
        items = data.get("devices", []) if "devices" in data else [data]
        for i, d in enumerate(items):
            if d.get("hub_remote_now") is True and d.get("hub_remote_at") is not None:
                out.append(f"{i}: hub_remote_at is null while hub_remote_now is true")
        if data.get("platform") in ("tvos", "android_tv", "watchos", "wearos") and \
                (data.get("hub_remote_now") or data.get("hub_remote_at")):
            out.append("hub_remote_now/hub_remote_at never on a TV or a watch")
        if out:
            return out
    if schema_rel == "rest/paired-client.json" and isinstance(data, dict):
        # Unresolved rules: remote_allowed and control_path are null together.
        if (data.get("remote_allowed") is None) != ("control_path" in data and data["control_path"] is None):
            return ["remote_allowed and control_path are null together (rules not resolved), else both set"]
    if schema_rel == "data/quick-access.json":
        return quick_access_checks(data)
    if schema_rel == "data/control-allowlist.json":
        return control_allowlist_checks(data)
    if schema_rel == "data/events.json":
        return event_taxonomy_checks(data)
    if schema_rel == "ws/integration/enforcement_rules.json":
        return snapshot_checks(data["data"]["snapshots"], "data/snapshots") + control_paths_checks(
            data["data"]["snapshots"], data["data"]["control_paths"], "data/control_paths"
        )
    if schema_rel == "integration/enforcement-rules.response.json":
        return snapshot_checks(data["snapshots"]) + control_paths_checks(data["snapshots"], data["control_paths"])
    if schema_rel == "network/home-networks.json":
        return home_networks_ref().run_vector(data)
    if schema_rel == "data/room-climate.json":
        return room_climate_data_checks(data)
    if schema_rel == "climate/room-climate-vector.json":
        return room_climate_ref().run_vector(data, room_climate_ref().load_data(REPO))
    if schema_rel == "deep-link/pairing-link.json" and "hn" in data["params"]:
        out += home_networks_ref().check_list(data["params"]["hn"].split(","), "params/hn")
    if schema_rel == "integration/ha-control.request.json" and "entity_id" in data and "entity_ids" in data:
        return ["entity_id and entity_ids are mutually exclusive"]
    if schema_rel in ("integration/ha-event.event.json", "ws/integration/ha_event.json"):
        ev = data["data"] if schema_rel.startswith("ws/") else data
        cats = {k["kind"]: k["category"] for k in json.loads((DATA / "events.json").read_text())["kinds"]}
        if cats.get(ev["kind"]) != ev["category"]:
            return [f"category {ev['category']} does not belong to kind {ev['kind']} (data/events.json)"]
    if schema_rel in ("data/profile-rules.json", "profiles/resolve.json", "profiles/expiry.json", "rest/profile.json",
                      "data/family.json", "profiles/family-check.json", "profiles/access-hours.json",
                      "profiles/ha-access.json", "profiles/no-escalation.json"):
        return profile_checks(schema_rel, data)
    if schema_rel == "ws/client/onboard_lookup.json":
        qr = [k for k in ("session_id", "public_key", "hub_id") if k in data]
        if ("code" in data) == bool(qr) or (qr and len(qr) != 3):
            return ["either code alone or session_id, public_key and hub_id"]
    if schema_rel == "ws/server/watch_access.json" and (data["status"] == "ready") != ("sealed" in data):
        return ["watch_access: sealed exactly with status ready"]
    if schema_rel in ("ws/server/access_request_state.json", "ws/server/access_request_update.json"):
        req = data["request"]
        if (req["answer"] is not None) != (req["status"] in ("approved", "declined")):
            return ["access request: answer is set exactly for approved and declined"]
    if schema_rel == "client-config.json":
        return client_config_checks(data)
    if schema_rel == "ws/server/client_config.json":
        return client_config_checks(data["data"])
    if schema_rel in ("data/tile-capabilities.json",) or schema_rel.startswith("data/tile-capabilities"):
        return tile_capability_checks(data)
    if schema_rel in ("data/tile-icons.json",) or schema_rel.startswith("data/tile-icons"):
        return tile_icon_checks(data)
    if schema_rel == "deep-link/pairing-link.json":
        uri = data["uri"]
        parsed = urllib.parse.urlsplit(uri)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        params = {k: v[0] for k, v in query.items()}
        if params != data["params"]:
            out.append(f"uri query {params} != params {data['params']}")
        raw_url = parsed.query.split("&", 1)[0].removeprefix("url=")
        if raw_url != urllib.parse.quote(data["params"]["url"], safe=""):
            out.append("url parameter must be fully percent-encoded")
    elif schema_rel == "deep-link/onboard-link.json":
        base, _, fragment = data["uri"].partition("#")
        pairs = [part.split("=", 1) for part in fragment.split("&")]
        params = {k: urllib.parse.unquote(v) for k, v in pairs}
        if params != data["params"]:
            out.append(f"uri fragment {params} != params {data['params']}")
        if [k for k, _ in pairs] != [k for k in ("hub", "fp", "s", "k", "n") if k in params]:
            out.append("fragment parameters must be in the order hub, fp, s, k, n")
    elif schema_rel == "crypto/onboard-seal-vectors.json":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import hpke_base  # noqa: PLC0415 - needs cryptography, only for this check

        for c in data["cases"]:
            b = {k: bytes.fromhex(c[k]) for k in ("sk_r", "pk_r", "sk_e", "enc", "info", "aad", "pt", "ct")}
            if hpke_base.public_key(b["sk_r"]) != b["pk_r"]:
                out.append(f"case {c['name']}: pk_r does not belong to sk_r")
            enc, ct = hpke_base.seal(b["pk_r"], b["info"], b["aad"], b["pt"], sk_e=b["sk_e"])
            if enc != b["enc"] or ct != b["ct"]:
                out.append(f"case {c['name']}: enc/ct do not match the recomputed seal")
            elif hpke_base.open_(b["sk_r"], b["enc"], b["info"], b["aad"], b["ct"]) != b["pt"]:
                out.append(f"case {c['name']}: sk_r does not open ct")
            if c["name"] == "watch-access-v1":
                # The plaintext is a sealed watch access for the client id in aad.
                try:
                    plain = json.loads(b["pt"])
                except ValueError:
                    out.append("case watch-access-v1: pt is not JSON")
                    continue
                if b["info"] != b"hub/watch-access/v1":
                    out.append("case watch-access-v1: info must be hub/watch-access/v1")
                if not validator_for(SCHEMAS / "crypto/watch-access-plaintext.json").is_valid(plain):
                    out.append("case watch-access-v1: pt does not validate against crypto/watch-access-plaintext.json")
                elif plain["client_id"].encode() != b["aad"]:
                    out.append("case watch-access-v1: aad must be the client_id of the plaintext")
    elif schema_rel == "crypto/compliance-vectors.json":
        label = data["label"].encode()
        for i, c in enumerate(data["cases"]):
            d32 = hashlib.sha256(c["secret"].encode()).digest() if "secret" in c else bytes.fromhex(c["digest32"])
            k = hmac.new(d32, label, hashlib.sha256).digest()
            msg = f"v1|{c['client_id']}|{c['status']}|{c['ts']}".encode()
            sig = hmac.new(k, msg, hashlib.sha256).hexdigest()
            if k.hex() != c["k_sign"] or sig != c["sig"]:
                out.append(f"case {i}: k_sign/sig do not match the recomputed values")
    elif schema_rel == "crypto/settings-pin-vectors.json":
        for i, c in enumerate(data["cases"]):
            h = hashlib.pbkdf2_hmac("sha256", c["pin"].encode(), bytes.fromhex(c["salt"]), data["iterations"], data["dklen"]).hex()
            if h != c["hash"]:
                out.append(f"case {i}: hash does not match PBKDF2 recomputation")
    return out


# ── OpenAPI ───────────────────────────────────────────────────────────────────


def check_openapi() -> None:
    try:
        from openapi_spec_validator import validate as oas_validate
    except ImportError:
        fail("openapi-spec-validator not installed (pip install -r tools/requirements.txt)")
        return
    cache: dict = {}
    for p in sorted((REPO / "openapi").glob("*.json")):
        spec = load_json(p)
        if spec is None:
            continue
        try:
            oas_validate(spec, base_uri=p.resolve().as_uri())
        except Exception as exc:  # noqa: BLE001
            fail(f"{rel(p)}: invalid OpenAPI: {str(exc).splitlines()[0]}")
        for ref in iter_refs(spec):
            if not ref.startswith("#"):
                err = check_ref(p, ref, cache)
                if err:
                    fail(err)
        n_ops = 0
        for path, ops in spec.get("paths", {}).items():
            for method, op in ops.items():
                n_ops += 1
                if "x-auth" not in op or "security" not in op:
                    fail(f"{rel(p)}: {method.upper()} {path}: x-auth/security missing")
        infos.append(f"openapi: {rel(p)} ok ({n_ops} operations, {spec.get('x-todo-count', 0)} responses without a model)")


# ── AsyncAPI ──────────────────────────────────────────────────────────────────


def check_asyncapi(official_schema: Path | None) -> None:
    p = REPO / "asyncapi" / "hub-ws.asyncapi.yaml"
    try:
        doc = yaml.safe_load(p.read_text())
    except Exception as exc:  # noqa: BLE001
        fail(f"{rel(p)}: invalid YAML ({exc})")
        return
    if doc.get("asyncapi") != "3.0.0":
        fail(f"{rel(p)}: asyncapi must be 3.0.0")
    cache: dict = {}
    used_payloads: set[Path] = set()
    for ref in iter_refs(doc):
        if ref.startswith("#"):
            try:
                resolve_pointer(doc, ref[1:])
            except (KeyError, IndexError, ValueError):
                fail(f"{rel(p)}: local $ref not found: {ref}")
        else:
            err = check_ref(p, ref, cache)
            if err:
                fail(err)
            else:
                used_payloads.add((p.parent / ref.partition("#")[0]).resolve())
    for mid, msg in doc.get("components", {}).get("messages", {}).items():
        ref = (msg.get("payload") or {}).get("$ref", "")
        schema = (p.parent / ref.partition("#")[0]).resolve() if ref and not ref.startswith("#") else None
        for fx in msg.get("x-fixtures", []):
            fx_path = p.parent / fx
            if not fx_path.exists():
                fail(f"{rel(p)}: message {mid}: fixture missing {fx}")
                continue
            if schema is None or not schema.exists():
                continue
            # A listed fixture belongs to its message: it validates against the payload (invalid-* must not).
            errs = list(validator_for(schema).iter_errors(load_json(fx_path)))
            if fx_path.name.startswith("invalid-") != bool(errs):
                fail(f"{rel(p)}: message {mid}: fixture {fx} does not match its payload "
                     f"{rel(schema)}" + (f" ({errs[0].message[:120]})" if errs else " (expected to fail)"))
    channel_msgs = {f"#/channels/{c}/messages/{m}" for c, ch in doc.get("channels", {}).items() for m in ch.get("messages", {})}
    for oid, op in doc.get("operations", {}).items():
        for m in op.get("messages", []) + op.get("reply", {}).get("messages", []):
            if m.get("$ref") not in channel_msgs:
                fail(f"{rel(p)}: operation {oid} references {m.get('$ref')} which is not a channel message")
    for sp in sorted((SCHEMAS / "ws").rglob("*.json")):
        r = sp.relative_to(SCHEMAS).as_posix()
        if r in ("ws/client-message.json", "ws/server-message.json"):
            continue
        if sp.resolve() not in used_payloads:
            fail(f"{rel(p)}: schemas/{r} is not used by any message")
    if official_schema:
        meta = json.loads(official_schema.read_text())
        from jsonschema import Draft7Validator  # noqa: PLC0415

        v = Draft7Validator(meta)
        errs = sorted(v.iter_errors(doc), key=lambda e: list(e.path))
        for e in errs[:5]:
            fail(f"{rel(p)}: AsyncAPI 3.0.0 schema: {'/'.join(map(str, e.path))}: {e.message[:200]}")
        infos.append(f"asyncapi: validated against {official_schema.name}")
    n_msgs = len(doc.get("components", {}).get("messages", {}))
    infos.append(f"asyncapi: {rel(p)} ok ({n_msgs} messages, {len(doc.get('operations', {}))} operations)")


# ── namespace ─────────────────────────────────────────────────────────────────

TEXT_SUFFIXES = {".json", ".yaml", ".yml", ".md", ".py", ".txt", ""}
# Legal and community files name the brand (whose spelling equals the namespace), not the namespace.
LEGAL_FILES = ("LICENSE", "NOTICE", "CONTRIBUTING.md", "TRADEMARKS.md", "SECURITY.md", "CODE_OF_CONDUCT.md")


def check_namespace() -> None:
    ns_path = REPO / "namespace.json"
    ns = load_json(ns_path)
    if ns is None:
        return
    errs = list(validator_for(SCHEMAS / "meta/namespace.schema.json").iter_errors(ns))
    for e in errs:
        fail(f"namespace.json: {'/'.join(map(str, e.path))}: {e.message}")
    keys = set(ns.get("values", {}))
    for doc_path in list(SCHEMAS.rglob("*.json")):
        doc = json.loads(doc_path.read_text())
        for key in re.findall(r'"x-namespace-key":\s*"([^"]+)"', json.dumps(doc)):
            if key not in keys:
                fail(f"{rel(doc_path)}: x-namespace-key '{key}' not defined in namespace.json")
    current = ns["current"]
    pattern = re.compile(re.escape(current), re.IGNORECASE)
    scope = ns.get("literal_scope", [])
    hits = 0
    for f in REPO.rglob("*"):
        if not f.is_file() or ".git" in f.parts or "__pycache__" in f.parts or f.suffix not in TEXT_SUFFIXES or f.name in LEGAL_FILES:
            continue
        r = rel(f)
        if r.startswith(".github/") or r == "CHANGELOG.md":
            continue
        # generated from namespace.json; kept current by tools/codegen/generate.py --check
        if r.startswith("tools/codegen/snapshots/"):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            hits += 1
            if not any(fnmatch.fnmatch(r, g) or (g.endswith("/**/*.json") and r.startswith(g[: -len("**/*.json")]) and r.endswith(".json")) for g in scope):
                fail(f"namespace: '{current}' used in {r}, which is not in namespace.json literal_scope")
    infos.append(f"namespace: current={current}, {len(keys)} values, literal in {hits} files (all in literal_scope)")


# ── hygiene ───────────────────────────────────────────────────────────────────

SECRET_PATTERNS = [
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "JWT-like token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"), "bearer credential"),
]


def check_kind_bounds() -> None:
    """Lists of profile kinds hold every kind: a fixed maxItems below the number of
    $defs/profile_kind refused "all kinds" once a kind was added (babysitter)."""
    kinds = load_json(SCHEMAS / "common/defs.json")["$defs"]["profile_kind"]["enum"]
    value = load_json(SCHEMAS / "common/profile-rule-values.json")["properties"]["setup_devices"]["properties"]["kinds"]
    if "maxItems" in value and value["maxItems"] < len(kinds):
        fail(f"profile-rule-values setup_devices.kinds: maxItems {value['maxItems']} < {len(kinds)} profile kinds")
    grant = load_json(SCHEMAS / "common/setup-grant.json")["properties"]["kinds"]
    if grant.get("maxItems") != len(kinds):
        fail(f"setup-grant kinds: maxItems {grant.get('maxItems')} != {len(kinds)} profile kinds")
    infos.append(f"profile kinds: {len(kinds)}, setup_devices and setup-grant hold all")


def check_watch_limit() -> None:
    """A watch follows its phone (docs/protocol.md): the limited value is the meet of both rule by
    rule, never more than either side at any moment (random pairs over the merged timeline), and the
    rule classes the vectors cannot reach on a watch (kinds) hold their meet."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import profiles_ref  # noqa: PLC0415

    catalog = profiles_ref.load_catalog(REPO)
    for e in profiles_ref.limit_property(catalog, profiles_ref.load_suggestions(REPO), cases=250):
        fail(f"watch limit property: {e}")
    rule = next(r for r in catalog["rules"] if r["key"] == "setup_devices")
    a = {"enabled": True, "kinds": ["guest", "tv"]}
    b = {"enabled": True, "kinds": ["tv", "child"]}
    m = profiles_ref.meet(rule, a, b)
    if m != {"enabled": True, "kinds": ["tv"]} or not (profiles_ref.leq(rule, m, a) and profiles_ref.leq(rule, m, b)):
        fail(f"watch limit: meet of kinds {m}")
    if profiles_ref.meet(rule, a, {"enabled": False, "kinds": ["guest"]}) != {"enabled": False, "kinds": []}:
        fail("watch limit: kinds with one side off must be off")
    infos.append("watch limit: meet never more than the watch or its phone (random pairs with area tags, device classes and DST instants, merged timeline)")


def check_hygiene() -> None:
    for f in sorted(FIXTURES.rglob("*.json")):
        text = f.read_text()
        for pat, what in SECRET_PATTERNS:
            if pat.search(text):
                fail(f"{rel(f)}: looks like it contains a {what}; fixtures must be synthetic")
        for m in re.finditer(r'"ha_token":\s*"([^"]+)"', text):
            if "FAKE" not in m.group(1):
                fail(f"{rel(f)}: ha_token must be an obvious fake (contain FAKE)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asyncapi-schema", type=Path, help="official AsyncAPI 3.0.0 JSON Schema (bundled) for a full check")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    schema_paths = check_schemas()
    check_fixtures(schema_paths, args.verbose)
    check_openapi()
    check_asyncapi(args.asyncapi_schema)
    check_namespace()
    check_kind_bounds()
    check_watch_limit()
    check_hygiene()

    for i in infos:
        print(i)
    if errors:
        print(f"\n{len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
