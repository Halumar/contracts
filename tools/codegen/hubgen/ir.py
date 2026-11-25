"""JSON Schema 2020-12 -> intermediate representation (IR) shared by all emitters.

The generator supports exactly the subset of JSON Schema the contract uses. Every keyword it
does not understand is an error, so a new schema feature fails loudly instead of being dropped
silently from the generated models.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

ANNOTATIONS = {
    "$schema", "title", "description", "deprecated", "default", "examples", "$comment",
}
# Vendor extensions are annotations as well (x-audience, x-planned, ...).


class SchemaError(Exception):
    pass


# ── types ─────────────────────────────────────────────────────────────────────


@dataclass
class StrRule:
    """Constraints of a string value. ``alternatives``: value must satisfy at least one."""

    pattern: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    fmt: str | None = None
    enum: list[str] | None = None
    alternatives: list["StrRule"] | None = None


@dataclass
class Type:
    kind: str  # string | integer | number | boolean | boolish | json | object_map | array | enum | model
    nullable: bool = False
    # string
    str_rule: StrRule | None = None
    # integer / number
    minimum: float | None = None
    maximum: float | None = None
    # const (string, integer, boolean)
    const: object = None
    has_const: bool = False
    # array
    items: "Type | None" = None
    min_items: int | None = None
    max_items: int | None = None
    unique_items: bool = False
    # object_map (free-form JSON object)
    max_properties: int | None = None
    required_keys: list[str] | None = None
    # enum / model
    ref: str | None = None

    def with_nullable(self) -> "Type":
        t = Type(**{**self.__dict__})
        t.nullable = True
        return t


@dataclass
class Field:
    json_name: str
    type: Type
    required: bool
    description: str | None = None
    deprecated: bool = False
    ns_key: str | None = None  # namespace value key when the JSON key itself is namespaced
    sensitive: bool = False  # x-sensitive: never printed by generated repr/toString/mirror


@dataclass
class Rule:
    required: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    consts: dict[str, object] = field(default_factory=dict)  # property -> required constant value
    non_null: list[str] = field(default_factory=list)  # nullable properties that must hold a value
    pending: list = field(default_factory=list, repr=False, compare=False)


@dataclass
class Conditional:
    prop: str
    values: list
    then: Rule
    otherwise: Rule | None
    presence: bool = False  # 'if' also requires the property; otherwise absent = condition holds


@dataclass
class ModelDef:
    name: str
    location: str
    description: str | None
    fields: list[Field]
    # discriminator fields: JSON name -> constant (type, command)
    fixed: dict[str, str]
    additional: object  # True | False | Type (schema for extra values)
    dependent_required: dict[str, list[str]] = field(default_factory=dict)
    any_of_required: list[list[str]] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    conditionals: list[Conditional] = field(default_factory=list)
    max_properties: int | None = None
    deprecated: bool = False
    schema_path: str | None = None  # "ws/server/auth_ok" for root models


@dataclass
class EnumDef:
    name: str
    location: str
    values: list[str]
    description: str | None = None


@dataclass
class UnionMember:
    model: str
    type_value: str | None  # None for shape unions (no discriminator)
    command: str | None


@dataclass
class UnionDef:
    name: str
    schema_path: str
    description: str | None
    members: list[UnionMember]
    discriminated: bool = True


@dataclass
class IR:
    version: str
    input_hash: str
    namespace_current: str
    namespace_values: dict[str, str]  # key -> current value (sorted)
    models: dict[str, ModelDef]
    enums: dict[str, EnumDef]
    unions: dict[str, UnionDef]
    registry: dict[str, str]  # schema path (without .json) -> model or union name
    # data/<name>.json -> (file stem, model of schemas/data/<name>.json, canonical JSON text)
    data: list[tuple[str, str, str]] = field(default_factory=list)

    def ordered_models(self) -> list[ModelDef]:
        return [self.models[k] for k in sorted(self.models)]

    def ordered_enums(self) -> list[EnumDef]:
        return [self.enums[k] for k in sorted(self.enums)]

    def ordered_unions(self) -> list[UnionDef]:
        return [self.unions[k] for k in sorted(self.unions)]


# ── naming ────────────────────────────────────────────────────────────────────

DIR_PREFIX = {
    "ws/client": "Client",
    "ws/server": "Server",
    "ws/command": "Command",
    "ws/broadcast": "Broadcast",
    "ws/heartbeat": "Heartbeat",
    "ws": "",
    "common": "",
    "bonjour": "Bonjour",
    "deep-link": "DeepLink",
    "sensors": "Sensor",
    "integration": "Integration",
    "rest": "Rest",
    "crypto": "Crypto",
    "": "",
}


def pascal(s: str) -> str:
    parts = [p for p in re.split(r"[^0-9A-Za-z]+", s) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def model_name_for(schema_rel: str) -> str:
    """'ws/server/auth_ok.json' -> 'ServerAuthOk'."""
    stem = schema_rel.removesuffix(".json")
    directory, _, base = stem.rpartition("/")
    # unknown directories: PascalCase of the path without 'ws' (ws/integration -> Integration);
    # name collisions are reported by the builder
    prefix = DIR_PREFIX.get(directory, "".join(pascal(p) for p in directory.split("/") if p != "ws"))
    name = pascal(base)
    if prefix and (name.startswith(prefix) or name.endswith(prefix)):
        return name
    return prefix + name


# ── builder ───────────────────────────────────────────────────────────────────


def _sanitize(text: str | None, ns: str) -> str | None:
    if text is None:
        return None
    return re.sub(re.escape(ns), "<ns>", text, flags=re.IGNORECASE)


class Builder:
    def __init__(self, repo: Path):
        self.repo = repo
        self.schemas_dir = repo / "schemas"
        self.docs: dict[str, dict] = {}
        for p in sorted(self.schemas_dir.rglob("*.json")):
            r = p.relative_to(self.schemas_dir).as_posix()
            if r.startswith("meta/"):
                continue
            self.docs[r] = json.loads(p.read_text(encoding="utf-8"))
        ns = json.loads((repo / "namespace.json").read_text(encoding="utf-8"))
        self.ns_current: str = ns["current"]
        self.ns_values = {k: v["value"] for k, v in sorted(ns["values"].items())}
        self.models: dict[str, ModelDef] = {}
        self.enums: dict[str, EnumDef] = {}
        self.unions: dict[str, UnionDef] = {}
        self.by_location: dict[str, str] = {}
        self.in_progress: set[str] = set()

    # -- helpers ------------------------------------------------------------

    def resolve(self, file_rel: str, ref: str) -> tuple[str, str, object]:
        file_part, _, frag = ref.partition("#")
        if file_part:
            target = (Path(file_rel).parent / file_part).as_posix()
            target = _normpath(target)
        else:
            target = file_rel
        if target not in self.docs:
            raise SchemaError(f"{file_rel}: $ref target not loaded: {ref}")
        node = self.docs[target]
        for part in [p for p in frag.split("/") if p]:
            node = node[part.replace("~1", "/").replace("~0", "~")]
        return target, frag, node

    def location_name(self, file_rel: str, pointer: str) -> str:
        if file_rel == "common/defs.json":
            parts = [p for p in pointer.split("/") if p]
            if len(parts) != 2 or parts[0] != "$defs":
                raise SchemaError(f"unsupported nested location in defs.json: {pointer}")
            return pascal(parts[1])
        base = model_name_for(file_rel)
        segs = []
        parts = [p for p in pointer.split("/") if p]
        i = 0
        while i < len(parts):
            p = parts[i]
            if p == "properties" and i + 1 < len(parts):
                segs.append(pascal(parts[i + 1]))
                i += 2
                continue
            if p == "items":
                segs.append("Item")
            elif p in ("allOf", "anyOf") and i + 1 < len(parts):
                i += 2
                continue
            i += 1
        return base + "".join(segs)

    def check_keywords(self, node: dict, allowed: set[str], where: str) -> None:
        for k in node:
            if k in ANNOTATIONS or k.startswith("x-") or k in allowed:
                continue
            raise SchemaError(f"{where}: unsupported keyword '{k}'")

    # -- types --------------------------------------------------------------

    def conv(self, node, file_rel: str, pointer: str) -> Type:
        where = f"{file_rel}#{pointer}"
        if node is True or node == {}:
            return Type("json", nullable=True)
        if not isinstance(node, dict):
            raise SchemaError(f"{where}: unsupported schema {node!r}")
        if "$ref" in node:
            self.check_keywords(node, {"$ref"}, where)
            target, frag, tnode = self.resolve(file_rel, node["$ref"])
            if target == "common/defs.json" and frag == "/$defs/boolish":
                return Type("boolish")
            if frag == "":
                if isinstance(tnode, dict) and tnode.get("type") == "object":
                    return Type("model", ref=self.model_for(target, "", tnode))
                raise SchemaError(f"{where}: $ref to a non-object root {target}")
            return self.conv(tnode, target, frag)
        if "allOf" in node and "type" not in node and "properties" not in node:
            self.check_keywords(node, {"allOf"}, where)
            if len(node["allOf"]) != 1:
                raise SchemaError(f"{where}: allOf with several branches outside an object")
            return self.conv(node["allOf"][0], file_rel, f"{pointer}/allOf/0")
        if "anyOf" in node and "type" not in node:
            self.check_keywords(node, {"anyOf"}, where)
            branches = node["anyOf"]
            nulls = [b for b in branches if b == {"type": "null"}]
            others = [(i, b) for i, b in enumerate(branches) if b != {"type": "null"}]
            if len(others) == 1:
                t = self.conv(others[0][1], file_rel, f"{pointer}/anyOf/{others[0][0]}")
                return t.with_nullable() if nulls else t
            # string alternatives, e.g. client_id = uuid | enum[...]
            alts = []
            for i, b in others:
                if isinstance(b, dict) and "enum" in b and all(isinstance(v, str) for v in b["enum"]):
                    self.check_keywords(b, {"enum"}, f"{where}/anyOf/{i}")
                    alts.append(StrRule(enum=list(b["enum"])))
                    continue
                t = self.conv(b, file_rel, f"{pointer}/anyOf/{i}")
                if t.kind == "string" and not t.has_const and not t.nullable:
                    alts.append(t.str_rule or StrRule())
                else:
                    raise SchemaError(f"{where}: unsupported anyOf (only nullable or string alternatives)")
            t = Type("string", str_rule=StrRule(alternatives=alts))
            return t.with_nullable() if nulls else t
        if "enum" in node:
            self.check_keywords(node, {"enum", "type"}, where)
            values = node["enum"]
            nullable = None in values
            values = [v for v in values if v is not None]
            if all(isinstance(v, str) for v in values):
                name = self.location_name(file_rel, pointer)
                loc = f"{file_rel}#{pointer}"
                if loc in self.by_location:
                    name = self.by_location[loc]
                else:
                    if name in self.enums or name in self.models:
                        raise SchemaError(f"{where}: type name collision '{name}'")
                    self.enums[name] = EnumDef(name, loc, list(values), _sanitize(node.get("description"), self.ns_current))
                    self.by_location[loc] = name
                return Type("enum", ref=name, nullable=nullable)
            raise SchemaError(f"{where}: only string enums are supported (boolish is special-cased)")
        if "const" in node:
            self.check_keywords(node, {"const", "type"}, where)
            v = node["const"]
            kind = {bool: "boolean", int: "integer", str: "string"}.get(type(v))
            if kind is None:
                raise SchemaError(f"{where}: unsupported const {v!r}")
            return Type(kind, const=v, has_const=True)
        types = node.get("type")
        if types is None:
            self.check_keywords(node, set(), where)
            return Type("json", nullable=True)
        if isinstance(types, list):
            nullable = "null" in types
            rest = [t for t in types if t != "null"]
            if len(rest) != 1:
                raise SchemaError(f"{where}: unsupported type union {types}")
            tname = rest[0]
        else:
            nullable = False
            tname = types
        if tname == "string":
            self.check_keywords(node, {"type", "pattern", "minLength", "maxLength", "format"}, where)
            rule = StrRule(
                pattern=node.get("pattern"),
                min_length=node.get("minLength"),
                max_length=node.get("maxLength"),
                fmt=node.get("format"),
            )
            if rule.fmt not in (None, "date-time", "ipv4"):
                raise SchemaError(f"{where}: unsupported format {rule.fmt}")
            empty = rule == StrRule()
            return Type("string", nullable=nullable, str_rule=None if empty else rule)
        if tname in ("integer", "number"):
            self.check_keywords(node, {"type", "minimum", "maximum"}, where)
            return Type(tname, nullable=nullable, minimum=node.get("minimum"), maximum=node.get("maximum"))
        if tname == "boolean":
            self.check_keywords(node, {"type"}, where)
            return Type("boolean", nullable=nullable)
        if tname == "array":
            self.check_keywords(node, {"type", "items", "minItems", "maxItems", "uniqueItems"}, where)
            items = self.conv(node.get("items", True), file_rel, f"{pointer}/items")
            if node.get("uniqueItems") and items.kind not in ("string", "enum", "integer"):
                raise SchemaError(f"{where}: uniqueItems is supported for string, enum and integer items only")
            return Type("array", nullable=nullable, items=items, min_items=node.get("minItems"), max_items=node.get("maxItems"),
                        unique_items=bool(node.get("uniqueItems")))
        if tname == "object":
            props = node.get("properties") or {}
            if not props and node.get("additionalProperties", True) is not False and "allOf" not in node:
                self.check_keywords(node, {"type", "properties", "required", "additionalProperties", "maxProperties"}, where)
                return Type("object_map", nullable=nullable, max_properties=node.get("maxProperties"),
                            required_keys=list(node.get("required", [])) or None)
            t = Type("model", ref=self.model_for(file_rel, pointer, node))
            return t.with_nullable() if nullable else t
        raise SchemaError(f"{where}: unsupported type {tname}")

    # -- objects ------------------------------------------------------------

    def model_for(self, file_rel: str, pointer: str, node: dict, name: str | None = None) -> str:
        loc = f"{file_rel}#{pointer}"
        if loc in self.by_location:
            return self.by_location[loc]
        name = name or self.location_name(file_rel, pointer)
        if name in self.models or name in self.enums:
            raise SchemaError(f"{loc}: type name collision '{name}'")
        self.by_location[loc] = name
        self.in_progress.add(name)
        self.models[name] = self.build_model(name, file_rel, pointer, node)
        self.in_progress.discard(name)
        return name

    def build_model(self, name: str, file_rel: str, pointer: str, node: dict) -> ModelDef:
        where = f"{file_rel}#{pointer}"
        self.check_keywords(
            node,
            {"type", "properties", "required", "additionalProperties", "allOf", "anyOf", "not",
             "dependentRequired", "maxProperties", "unevaluatedProperties"},
            where,
        )
        fields: dict[str, Field] = {}
        required: set[str] = set()
        model = ModelDef(name, where, _sanitize(node.get("description"), self.ns_current), [], {}, True,
                         deprecated=bool(node.get("deprecated")))

        for i, branch in enumerate(node.get("allOf", [])):
            if "$ref" in branch:
                target, frag, tnode = self.resolve(file_rel, branch["$ref"])
                base_name = self.model_for(target, frag, tnode)
                base = self.models[base_name]
                for f in base.fields:
                    fields[f.json_name] = Field(**{**f.__dict__})
                    if f.required:
                        required.add(f.json_name)
                model.fixed.update(base.fixed)
                model.dependent_required.update(base.dependent_required)
                model.any_of_required += base.any_of_required
                model.forbidden += base.forbidden
                model.conditionals += base.conditionals
                model.additional = base.additional
            elif "if" in branch:
                model.conditionals.append(self.conditional(branch, file_rel, f"{pointer}/allOf/{i}"))
            else:
                raise SchemaError(f"{where}/allOf/{i}: only $ref and if/then[/else] are supported in allOf")

        own_required = set(node.get("required", []))
        for pname, pnode in (node.get("properties") or {}).items():
            ptr = f"{pointer}/properties/{pname}"
            t = self.conv(pnode, file_rel, ptr)
            is_req = pname in own_required or pname in required
            if pname in ("type", "command") and t.kind == "string" and t.has_const and is_req:
                model.fixed[pname] = t.const
                fields.pop(pname, None)
                continue
            ns_key = None
            if self.ns_current in pname:
                ns_key = next((k for k, v in self.ns_values.items() if v == pname), None)
                if ns_key is None:
                    raise SchemaError(f"{ptr}: namespaced property key without a namespace.json value")
            fields[pname] = Field(
                pname, t, is_req,
                _sanitize(pnode.get("description") if isinstance(pnode, dict) else None, self.ns_current),
                bool(isinstance(pnode, dict) and pnode.get("deprecated")),
                ns_key,
                bool(isinstance(pnode, dict) and pnode.get("x-sensitive")),
            )
        for r in own_required:
            if r in fields:
                fields[r].required = True
            elif r not in model.fixed:
                raise SchemaError(f"{where}: required property '{r}' is not declared")

        if isinstance(node.get("unevaluatedProperties"), bool):
            # models are flattened over allOf, so unevaluated == additional here
            model.additional = node["unevaluatedProperties"]
        elif "unevaluatedProperties" in node:
            raise SchemaError(f"{where}: unevaluatedProperties must be a boolean")
        if "additionalProperties" in node:
            ap = node["additionalProperties"]
            model.additional = ap if isinstance(ap, bool) else self.conv(ap, file_rel, f"{pointer}/additionalProperties")
        for b in node.get("anyOf", []):
            if set(b) != {"required"}:
                raise SchemaError(f"{where}: object-level anyOf supports only {{required: [...]}} branches")
            model.any_of_required.append(list(b["required"]))
        if "not" in node:
            n = node["not"]
            if set(n) != {"required"}:
                raise SchemaError(f"{where}: 'not' supports only {{required: [...]}}")
            model.forbidden += list(n["required"])
        model.dependent_required.update({k: list(v) for k, v in node.get("dependentRequired", {}).items()})
        model.max_properties = node.get("maxProperties")
        self.resolve_conditionals(model, fields)
        model.fields = list(fields.values())
        return model

    def conditional(self, branch: dict, file_rel: str, pointer: str) -> Conditional:
        where = f"{file_rel}#{pointer}"
        self.check_keywords(branch, {"if", "then", "else"}, where)
        cond = branch["if"]
        props = cond.get("properties", {})
        if not set(cond) <= {"properties", "required"} or len(props) != 1:
            raise SchemaError(f"{where}: 'if' supports a single property condition")
        prop, pnode = next(iter(props.items()))
        if cond.get("required", [prop]) != [prop]:
            raise SchemaError(f"{where}: 'if' may only require the condition property")
        if "const" in pnode:
            values = [pnode["const"]]
        elif "enum" in pnode:
            values = list(pnode["enum"])
        else:
            raise SchemaError(f"{where}: 'if' condition must be const or enum")

        def rule(n: dict | None, key: str) -> Rule | None:
            if n is None:
                return None
            w = f"{where}/{key}"
            self.check_keywords(n, {"required", "not", "properties"}, w)
            r = Rule(required=list(n.get("required", [])))
            if "not" in n:
                if set(n["not"]) != {"required"}:
                    raise SchemaError(f"{w}: 'not' supports only required")
                r.forbidden = list(n["not"]["required"])
            for p, sub in (n.get("properties") or {}).items():
                if isinstance(sub, dict) and "const" in sub and set(sub) - ANNOTATIONS <= {"const"}:
                    r.consts[p] = sub["const"]
                else:
                    r.pending.append((p, sub, file_rel, f"{pointer}/{key}/properties/{p}"))
            return r

        return Conditional(prop, values, rule(branch.get("then"), "then") or Rule(), rule(branch.get("else"), "else"),
                           presence="required" in cond)

    def resolve_conditionals(self, model: ModelDef, fields: dict[str, Field]) -> None:
        """'then: {properties: {p: <schema>}}' is supported when <schema> is the non-null form of p."""
        for c in model.conditionals:
            for r in (c.then, c.otherwise):
                if r is None:
                    continue
                for p, sub, file_rel, ptr in r.pending:
                    f = fields.get(p)
                    t = self.conv(sub, file_rel, ptr)
                    if f is None or not f.type.nullable or t.nullable or t != Type(**{**f.type.__dict__, "nullable": False}):
                        raise SchemaError(f"{file_rel}#{ptr}: conditional subschema must be const or the non-null form of the property")
                    r.non_null.append(p)
                r.pending = []

    # -- roots --------------------------------------------------------------

    def build(self) -> IR:
        registry: dict[str, str] = {}
        union_files = []
        for r, doc in self.docs.items():
            if r == "common/defs.json":
                continue
            if "anyOf" in doc and "type" not in doc and all(set(b) == {"$ref"} for b in doc["anyOf"]):
                union_files.append(r)
                continue
            if "anyOf" in doc and "type" not in doc:
                self.check_keywords(doc, {"anyOf"}, r)
                name = model_name_for(r)
                members = []
                for i, b in enumerate(doc["anyOf"]):
                    if not (isinstance(b, dict) and b.get("type") == "object" and b.get("required")):
                        raise SchemaError(f"{r}/anyOf/{i}: shape unions need inline objects with required fields")
                    mname = self.model_for(r, f"/anyOf/{i}", b, name + pascal(b["required"][0]))
                    members.append(UnionMember(mname, None, None))
                self.unions[name] = UnionDef(name, r.removesuffix(".json"), _sanitize(doc.get("description"), self.ns_current),
                                             members, discriminated=False)
                registry[r.removesuffix(".json")] = name
                continue
            if doc.get("type") != "object":
                raise SchemaError(f"{r}: root must be an object or a union of $refs")
            name = self.model_for(r, "", doc)
            self.models[name].schema_path = r.removesuffix(".json")
            registry[r.removesuffix(".json")] = name
        for r in union_files:
            doc = self.docs[r]
            name = model_name_for(r)
            members = []
            for b in doc["anyOf"]:
                target, _, tnode = self.resolve(r, b["$ref"])
                mname = self.model_for(target, "", tnode)
                m = self.models[mname]
                if "type" not in m.fixed:
                    raise SchemaError(f"{r}: member {target} has no constant 'type'")
                members.append(UnionMember(mname, m.fixed["type"], m.fixed.get("command")))
            self.unions[name] = UnionDef(name, r.removesuffix(".json"), _sanitize(doc.get("description"), self.ns_current), members)
            registry[r.removesuffix(".json")] = name
        h = hashlib.sha256()
        for p in sorted(self.schemas_dir.rglob("*.json")):
            h.update(p.relative_to(self.repo).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
        h.update((self.repo / "namespace.json").read_bytes())
        data: list[tuple[str, str, str]] = []
        data_dir = self.repo / "data"
        for p in sorted(data_dir.glob("*.json")) if data_dir.exists() else []:
            key = f"data/{p.stem}"
            if key not in registry:
                raise SchemaError(f"data/{p.name}: no schema at schemas/{key}.json")
            raw = p.read_bytes()
            h.update(p.relative_to(self.repo).as_posix().encode() + b"\0" + raw + b"\0")
            canonical = json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if self.ns_current.lower() in canonical.lower():
                raise SchemaError(f"data/{p.name}: contains the namespace literal")
            data.append((p.stem, registry[key], canonical))
        version = (self.repo / "VERSION").read_text().strip()
        return IR(version, h.hexdigest()[:16], self.ns_current, self.ns_values, self.models, self.enums,
                  self.unions, dict(sorted(registry.items())), data)


def _normpath(p: str) -> str:
    out: list[str] = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            out.pop()
        else:
            out.append(part)
    return "/".join(out)


def build_ir(repo: Path) -> IR:
    return Builder(repo).build()


# ── helpers for emitters ──────────────────────────────────────────────────────


def ordered_union_candidates(ir: IR, union: UnionDef) -> list[tuple[str, str | None, list[str]]]:
    """[(type, command, [models in decode order])], sorted by type/command.

    Several members can share a discriminator. They are tried in order of descending
    number of required fields, then by name, so the more specific shape wins.
    """
    if not union.discriminated:
        return [(None, None, sorted((m.model for m in union.members), key=lambda n: (-sum(f.required for f in ir.models[n].fields), n)))]
    groups: dict[tuple[str, str | None], list[str]] = {}
    for m in union.members:
        groups.setdefault((m.type_value, m.command), []).append(m.model)
    out = []
    for key in sorted(groups, key=lambda k: (k[0], k[1] or "")):
        models = sorted(set(groups[key]), key=lambda n: (-sum(f.required for f in ir.models[n].fields), n))
        out.append((key[0], key[1], models))
    return out


def regex_for(pattern: str, end_anchor: str) -> str:
    """JSON Schema patterns are ECMA-262: '$' only matches at the very end. Python, Java and ICU
    also match before a trailing newline, so a terminal '$' is replaced by the strict anchor."""
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        return pattern[:-1] + end_anchor
    return pattern


def ns_split(s: str, ir: IR) -> list[tuple[str, str]]:
    """Split a literal into ('lit', text) and ('ns', key) parts so that no emitter writes the
    namespace literal into a model file. Exact namespace values map to their constant."""
    for k, v in ir.namespace_values.items():
        if s == v:
            return [("ns", k)]
    if ir.namespace_current not in s:
        return [("lit", s)]
    parts: list[tuple[str, str]] = []
    chunks = s.split(ir.namespace_current)
    for i, c in enumerate(chunks):
        if c:
            parts.append(("lit", c))
        if i < len(chunks) - 1:
            parts.append(("ns", "current"))
    return parts
