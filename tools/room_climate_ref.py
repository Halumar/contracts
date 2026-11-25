#!/usr/bin/env python3
"""Reference of the room climate of an area (data/room-climate.json, docs/room-climate.md).
Standard library only.

hub_pick(vector)   what the hub sends as area.room_climate: per measure the admin's entity, else
                   the candidates of the rule (thermostats, then sensors; excluded ones out; in each
                   tier the ones assigned to the room's Home Assistant area win, when there are any).
local_pick(vector) what an app uses without room_climate (older hub, direct mode, demo): the same
                   rule with what an app knows (entity_id, names, device_class, no registry).
value(pick, ...)   the room value from the live states: the admin's entity, else the median of the
                   thermostats with a value, else the median of the sensors with a value.
primary_sensor()   for consumers that show one sensor's state (widgets, watch): the candidate sensor
                   whose value is closest to the room value.

Hub and apps port it and run the vectors in fixtures/climate/room-climate-vector (tools/validate.py too).

  python tools/room_climate_ref.py fixtures/climate/room-climate-vector/<vector>.json
"""

from __future__ import annotations

import json
import math
import sys
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MEASURES = ("temperature", "humidity")
UNKNOWN_STATES = ("unavailable", "unknown", "", None)


def load_data(repo: Path = REPO) -> dict:
    return json.loads((repo / "data" / "room-climate.json").read_text(encoding="utf-8"))


# ── text ────────────────────────────────────────────────────────────────────

_FOLD = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def normalize(text: str) -> str:
    """Lower case, umlauts transcribed, other diacritics dropped, other characters -> one space."""
    out = "".join(_FOLD.get(c, c) for c in text.lower())
    out = "".join(c for c in unicodedata.normalize("NFKD", out) if not unicodedata.combining(c))
    words: list[str] = []
    word = ""
    for c in out:
        if "a" <= c <= "z" or "0" <= c <= "9":
            word += c
        elif word:
            words.append(word)
            word = ""
    if word:
        words.append(word)
    return " ".join(words)


def excluded_group(texts: list[str | None], data: dict) -> str | None:
    """Id of the first exclude group one of the texts matches, else None."""
    normalized = [normalize(t) for t in texts if t]
    for group in data["exclude"]["groups"]:
        for text in normalized:
            padded = " " + text
            if any(k in text for k in group["contains"]):
                return group["id"]
            if any(" " + k in padded for k in group["prefixes"]):
                return group["id"]
    return None


# ── entities ────────────────────────────────────────────────────────────────


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _attributes(entity: dict) -> dict:
    state = entity.get("state") or {}
    return state.get("attributes") or {}


def device_class(entity: dict, *, registry: bool) -> str | None:
    value = _attributes(entity).get("device_class")
    if value is None and registry:
        reg = entity.get("registry") or {}
        value = reg.get("device_class") or reg.get("original_device_class")
    return value if isinstance(value, str) else None


def tier(entity: dict, measure: dict, *, registry: bool) -> str | None:
    """device (thermostat reporting the attribute), sensor (of the device class) or None."""
    domain = _domain(entity["entity_id"])
    if domain in measure["device_domains"]:
        return "device" if measure["device_attribute"] in _attributes(entity) else None
    if domain == "sensor" and device_class(entity, registry=registry) == measure["sensor_device_class"]:
        return "sensor"
    return None


def texts(entity: dict, *, registry: bool) -> list[str | None]:
    out = [entity["entity_id"], entity.get("display_name"), _attributes(entity).get("friendly_name")]
    if registry:
        reg = entity.get("registry") or {}
        out += [reg.get("name"), reg.get("original_name")]
        device = reg.get("device") or {}
        out += [device.get("name_by_user"), device.get("name"), device.get("model")]
    return out


def excluded(entity: dict, data: dict, *, registry: bool) -> str | None:
    if registry:
        category = (entity.get("registry") or {}).get("entity_category")
        if category in data["exclude"]["entity_categories"]:
            return "entity_category"
    return excluded_group(texts(entity, registry=registry), data)


def in_room(entity: dict, ha_area_id: str | None) -> bool:
    """The entity, or (without an own area) its device, is in the area's Home Assistant area."""
    if not ha_area_id:
        return False
    reg = entity.get("registry") or {}
    area = reg.get("area_id") or (reg.get("device") or {}).get("area_id")
    return area == ha_area_id


def _placed(entities: list[dict], *, visible_only: bool) -> list[dict]:
    seen: set[str] = set()
    out = []
    for e in entities:
        if visible_only and not e.get("visible", True):
            continue
        if e["entity_id"] in seen:
            continue
        seen.add(e["entity_id"])
        out.append(e)
    return out


def _auto(entities: list[dict], measure: dict, data: dict, ha_area_id: str | None, *, registry: bool) -> list[str]:
    tiers: dict[str, list[tuple[dict, bool]]] = {"device": [], "sensor": []}
    for e in _placed(entities, visible_only=True):
        t = tier(e, measure, registry=registry)
        if t is None or excluded(e, data, registry=registry):
            continue
        tiers[t].append((e, registry and in_room(e, ha_area_id)))
    keep: set[str] = set()
    for members in tiers.values():
        room = [e for e, inside in members if inside]
        keep.update(e["entity_id"] for e in (room or [e for e, _ in members]))
    return [e["entity_id"] for e in _placed(entities, visible_only=True) if e["entity_id"] in keep]


def hub_pick(vector: dict, data: dict) -> dict:
    out = {}
    admin = vector.get("admin") or {}
    for name in MEASURES:
        chosen = admin.get(name)
        if chosen:
            out[name] = {"source": "admin", "entity_ids": [chosen]}
        else:
            ids = _auto(vector["entities"], data["measures"][name], data, vector.get("ha_area_id"), registry=True)
            out[name] = {"source": "auto", "entity_ids": ids}
    return out


def local_pick(vector: dict, data: dict) -> dict:
    return {
        name: {"source": "auto", "entity_ids": _auto(vector["entities"], data["measures"][name], data, None, registry=False)}
        for name in MEASURES
    }


def options(vector: dict, data: dict, name: str) -> list[dict]:
    """Admin UI: every placed entity that reports the measure, with why it does not count."""
    measure = data["measures"][name]
    out = []
    for e in _placed(vector["entities"], visible_only=False):
        t = tier(e, measure, registry=True)
        if t is None:
            continue
        out.append({
            "entity_id": e["entity_id"],
            "tier": t,
            "in_room": in_room(e, vector.get("ha_area_id")),
            "excluded": excluded(e, data, registry=True),
            "value": read(e, measure),
        })
    return out


# ── values ──────────────────────────────────────────────────────────────────


def _number(raw) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def read(entity: dict | None, measure: dict) -> float | None:
    """Value of one entity: the attribute of a thermostat, else the numeric state."""
    if not entity or not entity.get("state"):
        return None
    state = entity["state"]
    if state.get("state") in UNKNOWN_STATES:
        return None
    if _domain(entity["entity_id"]) in measure["device_domains"]:
        return _number((state.get("attributes") or {}).get(measure["device_attribute"]))
    return _number(state.get("state"))


def median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _tier_values(pick: dict, by_id: dict[str, dict], measure: dict) -> list[tuple[str, float]]:
    """(entity_id, value) of the tier the value comes from."""
    ids = pick["entity_ids"]
    if pick["source"] == "admin":
        v = read(by_id.get(ids[0]) if ids else None, measure)
        return [(ids[0], v)] if v is not None else []
    for devices in (True, False):
        found = [
            (i, v)
            for i in ids
            if (_domain(i) in measure["device_domains"]) == devices
            and (v := read(by_id.get(i), measure)) is not None
        ]
        if found:
            return found
    return []


def value(pick: dict, entities: list[dict], measure: dict) -> float | None:
    by_id = {e["entity_id"]: e for e in entities}
    return median([v for _, v in _tier_values(pick, by_id, measure)])


def primary_sensor(pick: dict, entities: list[dict], measure: dict) -> str | None:
    """The candidate sensor closest to the room value (ties: the earlier one)."""
    by_id = {e["entity_id"]: e for e in entities}
    room = value(pick, entities, measure)
    sensors = [
        (i, v) for i in pick["entity_ids"]
        if _domain(i) == "sensor" and (v := read(by_id.get(i), measure)) is not None
    ]
    if room is None or not sensors:
        return None
    return min(sensors, key=lambda s: abs(s[1] - room))[0]


# ── vectors ─────────────────────────────────────────────────────────────────


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 4)


def run_vector(vector: dict, data: dict | None = None) -> list[str]:
    data = data or load_data()
    out: list[str] = []
    name = vector["name"]
    expect = vector["expect"]
    hub = hub_pick(vector, data)
    if hub != expect["room_climate"]:
        out.append(f"{name}: room_climate {hub}, expected {expect['room_climate']}")
    local = local_pick(vector, data)
    for m in MEASURES:
        measure = data["measures"][m]
        got = _round(value(expect["room_climate"][m], vector["entities"], measure))
        if got != _round(expect["value"][m]):
            out.append(f"{name}: {m} value {got}, expected {expect['value'][m]}")
        got_local = _round(value(local[m], vector["entities"], measure))
        if got_local != _round(expect["local"][m]):
            out.append(f"{name}: {m} local value {got_local}, expected {expect['local'][m]}")
        primary = primary_sensor(expect["room_climate"][m], vector["entities"], measure)
        if primary != expect["primary_sensor"][m]:
            out.append(f"{name}: {m} primary_sensor {primary}, expected {expect['primary_sensor'][m]}")
    for m, opts in (expect.get("options") or {}).items():
        got_opts = [{k: o[k] for k in ("entity_id", "tier", "in_room", "excluded")} for o in options(vector, data, m)]
        if got_opts != opts:
            out.append(f"{name}: {m} options {got_opts}, expected {opts}")
    return out


if __name__ == "__main__":
    errors: list[str] = []
    for arg in sys.argv[1:]:
        errors += run_vector(json.loads(Path(arg).read_text(encoding="utf-8")))
    print("\n".join(errors) or "ok")
    sys.exit(1 if errors else 0)
