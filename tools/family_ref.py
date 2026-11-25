#!/usr/bin/env python3
"""Reference permission check of the family manager. Standard library only.

family_check(family, manager, child, op) answers one question: may this device do this to this child
device right now? It returns (allowed, reason) with reason a $defs/family_error_reason or None. The hub
ports it 1:1 and runs the vectors in fixtures/profiles/family-check (tools/validate.py does the same).

Not covered here (checked by the hub with other parts of the contract): value schemas
(profile-rule-values.json -> value_invalid), boundaries on the child device (resolver -> boundary),
limits and rate limits, request state (already_answered, request_not_found, cooldown).

  python tools/family_ref.py fixtures/profiles/family-check/<vector>.json
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# release kind -> rule that must not be fixed in the child's profile
RELEASE_RULE = {"bedtime": "kids_quiet_hours", "pause": "kids_rate_limit"}


def load_family(repo: Path = REPO) -> dict:
    return json.loads((repo / "data/family.json").read_text(encoding="utf-8"))


def _type_blocked(entity_id: str, device_class: str | None, blocked_types: list[str]) -> bool:
    domain = entity_id.split(".", 1)[0]
    return domain in blocked_types or (device_class is not None and f"{domain}:{device_class}" in blocked_types)


def babysitter_check(family: dict, sitter: dict, child: dict, op: dict) -> tuple[bool, str | None]:
    """A babysitter device only answers requests, with access, at home, within its presets."""
    if sitter.get("child_protection") or not sitter.get("access_open", True) or not sitter.get("at_home", True):
        return False, "not_permitted"
    if op["kind"] not in ("answer_yes", "answer_no"):
        return False, "not_permitted"
    if not child["child_protection"] or child["client_id"] == sitter["client_id"]:
        return False, "not_your_child"
    if op["kind"] == "answer_no":
        return True, None
    sb = family["babysitter"]
    if op["category"] not in sb["categories"]:
        return False, "not_permitted"
    preset = op.get("preset")
    if preset not in sb["presets"] or (preset == "access_end" and not sitter.get("access_until")):
        return False, "preset_not_allowed"
    cat = {c["id"]: c for c in family["request_categories"]}[op["category"]]
    fixed = set(child.get("fixed", []))
    if set(cat["requires_unfixed"]) & fixed:
        return False, "release_not_allowed"
    if cat["release_kind"] != "entity":
        return True, None
    entity_id = op["entity_id"]
    if entity_id.split(".", 1)[0] in family["never_release_domains"]:
        return False, "release_not_allowed"
    if entity_id in child.get("exception_blocked_entities", []):
        return False, "release_not_allowed"
    # never a blocked device type, fixed or not ("no blocked devices")
    if _type_blocked(entity_id, op.get("device_class"), child.get("blocked_types", [])):
        return False, "release_not_allowed"
    if child.get("quiet_now") and "kids_quiet_hours" in fixed:
        return False, "release_not_allowed"
    return True, None


def family_check(family: dict, manager: dict, child: dict, op: dict) -> tuple[bool, str | None]:
    if manager.get("babysitter"):
        return babysitter_check(family, manager, child, op)
    # 1. the acting device: a member without parental controls whose effective rule family_manager is on
    if manager["access"] != "member" or manager["child_protection"] or not manager["family_manager"]:
        return False, "not_permitted"
    # 2. the target: a child device (parental controls) inside the scope
    scope = manager["scope"]
    if not child["child_protection"] or child["client_id"] == manager["client_id"]:
        return False, "not_your_child"
    if not scope["all"] and child["client_id"] not in scope["client_ids"]:
        return False, "not_your_child"

    fixed = set(child.get("fixed", []))
    kind = op["kind"]
    if kind in ("release_end", "answer_no"):
        return True, None  # ending a release only ever makes it stricter

    if kind in ("rule_set", "rule_reset"):
        rule = op["rule"]
        if rule not in {m["rule"] for m in family["manageable_rules"]}:
            return False, "rule_not_manageable"
        if rule in fixed:
            return False, "rule_fixed"
        if kind == "rule_set" and rule == "areas":
            visible = manager.get("visible_area_ids")
            value = op.get("value") or {}
            if visible is not None:
                if value.get("mode") == "all" or value.get("tags"):
                    return False, "areas_not_allowed"
                if set(value.get("area_ids", [])) - set(visible):
                    return False, "areas_not_allowed"
        return True, None

    # release or a Yes to a request
    if kind == "answer_yes":
        cat = {c["id"]: c for c in family["request_categories"]}[op["category"]]
        release_kind = cat["release_kind"]
        if set(cat["requires_unfixed"]) & fixed:
            return False, "release_not_allowed"
    else:
        release_kind = op["release_kind"]
    if release_kind in RELEASE_RULE:
        return (False, "release_not_allowed") if RELEASE_RULE[release_kind] in fixed else (True, None)

    entity_id = op["entity_id"]
    if entity_id.split(".", 1)[0] in family["never_release_domains"]:
        return False, "release_not_allowed"
    if entity_id in child.get("exception_blocked_entities", []):
        return False, "release_not_allowed"
    if _type_blocked(entity_id, op.get("device_class"), child.get("blocked_types", [])) and "kids_blocked_types" in fixed:
        return False, "release_not_allowed"
    if child.get("quiet_now") and "kids_quiet_hours" in fixed:
        return False, "release_not_allowed"
    return True, None


def run_family_vector(vector: dict, family: dict | None = None) -> list[str]:
    family = family or load_family()
    errs = []
    for c in vector["cases"]:
        allowed, reason = family_check(family, c["manager"], c["child"], c["op"])
        exp = c["expected"]
        if allowed != exp["allowed"] or reason != exp["reason"]:
            errs.append(f"case {c['name']}: vector {exp['allowed']}/{exp['reason']}, reference {allowed}/{reason}")
    return errs


def check_family_data(family: dict, catalog: dict) -> list[str]:
    """Consistency of data/family.json with the rule catalog and $defs (called by tools/validate.py)."""
    out: list[str] = []
    rules = {r["key"]: r for r in catalog["rules"]}
    manageable = [m["rule"] for m in family["manageable_rules"]]
    for key in manageable:
        if key not in rules:
            out.append(f"manageable_rules: unknown rule {key}")
        elif not rules[key]["fixed_checkbox"]:
            out.append(f"manageable_rules: {key} has no Fixed checkbox (always fixed), a family manager could never change it")
    if len(set(manageable)) != len(manageable):
        out.append("manageable_rules: duplicate rule")
    for forbidden in ("family_manager", "setup_devices", "remote_access", "kids_exceptions"):
        if forbidden in manageable:
            out.append(f"manageable_rules: {forbidden} is an admin decision")
    presets = {p["id"] for p in family["release_presets"]}
    for c in family["request_categories"]:
        if set(c["requires_unfixed"]) - set(manageable):
            out.append(f"request_categories/{c['id']}: requires_unfixed outside manageable_rules")
        if c["default_preset"] not in c["presets"]:
            out.append(f"request_categories/{c['id']}: default_preset not in presets")
        if set(c["presets"]) - presets:
            out.append(f"request_categories/{c['id']}: unknown preset")
        if c["release_kind"] == "pause" and "bedtime_end" in c["presets"]:
            out.append(f"request_categories/{c['id']}: bedtime_end only for bedtime and entity releases")
    if "kids_rate_limit" in [c for cat in family["request_categories"] if cat["release_kind"] == "bedtime" for c in cat["requires_unfixed"]]:
        out.append("request_categories: bedtime must not depend on kids_rate_limit")
    kinds = [n["kind"] for n in family["notify_defaults"]]
    if len(set(kinds)) != len(kinds):
        out.append("notify_defaults: duplicate kind")
    events_file = REPO / "data/events.json"
    if events_file.exists():
        taxonomy = {k["kind"]: k for k in json.loads(events_file.read_text(encoding="utf-8"))["kinds"]}
        for kind in kinds:
            if kind not in taxonomy:
                out.append(f"notify_defaults: {kind} is not in data/events.json (event taxonomy)")
            elif taxonomy[kind]["category"] != "kids":
                out.append(f"notify_defaults: {kind} must be a kids event")
    req = next((n for n in family["notify_defaults"] if n["kind"] == "kids_release_requested"), None)
    if req is None or req["can_disable"] or not req["enabled"]:
        out.append("notify_defaults: kids_release_requested must be enabled and not switchable off")
    for a in family["notify_actions"]:
        if (a["answer"] == "yes") != (a["preset"] is not None):
            out.append(f"notify_actions/{a['id']}: yes needs a preset, no must not have one")
    sb = family["babysitter"]
    if set(sb["presets"]) - presets or not set(sb["presets"]) <= {"15m", "30m", "access_end"}:
        out.append("babysitter.presets: only 15m, 30m and access_end")
    if set(sb["categories"]) - {c["id"] for c in family["request_categories"]}:
        out.append("babysitter.categories: unknown category")
    if set(sb["answer_labels"]) != set(sb["presets"]) | {"no"}:
        out.append("babysitter.answer_labels: one label per preset and no")
    d = family["settings_defaults"]
    if set(d["categories"]) - {c["id"] for c in family["request_categories"]}:
        out.append("settings_defaults.categories: unknown category")
    for key, lim in family["limits"].items():
        if isinstance(lim, dict) and key in d and not lim["min"] <= d[key] <= lim["max"]:
            out.append(f"settings_defaults.{key} outside limits")
    return out


if __name__ == "__main__":
    import sys

    vec = json.loads(Path(sys.argv[1]).read_text())
    problems = run_family_vector(vec)
    print("\n".join(problems) or "ok")
    sys.exit(1 if problems else 0)
