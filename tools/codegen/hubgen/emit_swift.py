"""Swift emitter: Codable/Sendable structs for the Apple apps (iOS 17 / tvOS 17 / macOS 14)."""

from __future__ import annotations

from pathlib import Path

from .common import camel, doc_lines, header_lines, topo_models
from .ir import IR, EnumDef, ModelDef, StrRule, Type, UnionDef, ns_split, ordered_union_candidates, regex_for

RUNTIME = Path(__file__).parent / "runtime" / "swift" / "ContractRuntime.swift"

SWIFT_KEYWORDS = {
    "associatedtype", "class", "deinit", "enum", "extension", "fileprivate", "func", "import", "init", "inout",
    "internal", "let", "open", "operator", "private", "precedencegroup", "protocol", "public", "rethrows", "static",
    "struct", "subscript", "typealias", "var", "break", "case", "catch", "continue", "default", "defer", "do",
    "else", "fallthrough", "for", "guard", "if", "in", "repeat", "return", "throw", "switch", "where", "while",
    "Any", "as", "await", "false", "is", "nil", "self", "Self", "super", "throws", "true", "try", "Type",
}
NS_TYPE = "ProtocolNamespace"


def ident(name: str) -> str:
    return f"`{name}`" if name in SWIFT_KEYWORDS else name


def raw(s: str) -> str:
    if '"#' in s:
        raise ValueError(f"cannot emit raw string {s!r}")
    return f'#"{s}"#' if "\\" in s or '"' in s else f'"{s}"'


def sw_str(s: str, ir: IR) -> str:
    parts = []
    for kind, val in ns_split(s, ir):
        parts.append(f"{NS_TYPE}.{camel(val)}" if kind == "ns" else raw(val))
    return " + ".join(parts) if parts else '""'


def enum_case(value: str) -> str:
    c = camel(value) or "empty"
    if c == "none":
        return "noneValue"
    if c == "unknown":
        return "unknownValue"
    return c


class SwiftEmitter:
    def __init__(self, ir: IR):
        self.ir = ir

    def ty(self, t: Type) -> str:
        k = t.kind
        base = {
            "string": "String", "integer": "Int", "number": "Double", "boolean": "Bool", "boolish": "Boolish",
            "json": "JSONValue", "object_map": "[String: JSONValue]",
        }.get(k)
        if k == "array":
            base = f"[{self.ty(t.items)}]"
        elif k in ("enum", "model"):
            base = t.ref
        if k == "json":
            return "JSONValue?"
        return base + "?" if t.nullable else base

    def prop_type(self, f) -> str:
        t = self.ty(f.type)
        if not f.required and not t.endswith("?"):
            t += "?"
        return t

    def key(self, f) -> str:
        return f"ContractCodingKey({NS_TYPE}.{camel(f.ns_key)})" if f.ns_key else raw(f.json_name)

    def prop(self, f) -> str:
        return ident(camel(f.ns_key or f.json_name))

    # -- validation ------------------------------------------------------------

    def literal(self, v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        return sw_str(v, self.ir)

    def str_rule(self, r: StrRule) -> str:
        args = []
        if r.pattern is not None:
            args.append(f"pattern: {sw_str(regex_for(r.pattern, chr(92) + 'z'), self.ir)}")
        if r.min_length is not None:
            args.append(f"minLength: {r.min_length}")
        if r.max_length is not None:
            args.append(f"maxLength: {r.max_length}")
        if r.fmt is not None:
            args.append(f'format: "{r.fmt}"')
        if r.enum is not None:
            args.append(f"oneOf: [{', '.join(sw_str(v, self.ir) for v in r.enum)}]")
        return f".init({', '.join(args)})"

    def checks(self, t: Type, value: str, path: str, depth: int = 0, opt: bool = True) -> list[str]:
        k = t.kind
        if k == "string":
            args = []
            if t.str_rule and t.str_rule.alternatives is not None:
                args.append(f"alternatives: [{', '.join(self.str_rule(a) for a in t.str_rule.alternatives)}]")
            elif t.str_rule:
                args.append(self.str_rule(t.str_rule))
            if t.has_const:
                args.append(f"const: {sw_str(t.const, self.ir)}")
            return [f"ContractCheck.string(&v_, {path}, {value}, {', '.join(args)})"] if args else []
        if k in ("integer", "number"):
            args = []
            fmt = (lambda x: str(int(x))) if k == "integer" else (lambda x: repr(float(x)))
            if t.minimum is not None:
                args.append(f"minimum: {fmt(t.minimum)}")
            if t.maximum is not None:
                args.append(f"maximum: {fmt(t.maximum)}")
            if t.has_const:
                args.append(f"const: {fmt(t.const)}")
            out = [f"ContractCheck.finite(&v_, {path}, {value})"] if k == "number" else []
            return out + ([f"ContractCheck.number(&v_, {path}, {value}, {', '.join(args)})"] if args else [])
        if k == "boolean":
            return [f"ContractCheck.bool(&v_, {path}, {value}, const: {'true' if t.const else 'false'})"] if t.has_const else []
        if k in ("enum", "model"):
            return [f"ContractCheck.nested(&v_, {path}, {value})"]
        if k == "object_map":
            args = []
            if t.max_properties is not None:
                args.append(f"maxProperties: {t.max_properties}")
            if t.required_keys:
                args.append(f"required: [{', '.join(raw(x) for x in t.required_keys)}]")
            return [f"ContractCheck.map(&v_, {path}, {value}, {', '.join(args)})"] if args else []
        if k == "array":
            out = []
            args = []
            if t.min_items is not None:
                args.append(f"minItems: {t.min_items}")
            if t.max_items is not None:
                args.append(f"maxItems: {t.max_items}")
            if t.unique_items:
                args.append("unique: true")
            if args:
                out.append(f"ContractCheck.items(&v_, {path}, {value}, {', '.join(args)})")
            if t.items.kind in ("enum", "model") and not t.items.nullable:
                out.append(f"ContractCheck.nested(&v_, {path}, {value})")
                return out
            iv, ii = f"x{depth}_", f"i{depth}_"
            inner = self.checks(t.items, iv, f'"\\({path})/\\({ii})"', depth + 1, t.items.nullable)
            if inner:
                seq = f"({value} ?? [])" if opt else value
                out.append(f"for ({ii}, {iv}) in {seq}.enumerated() {{")
                out += ["    " + s for s in inner]
                out.append("}")
            return out
        return []

    # -- emit ------------------------------------------------------------------

    @staticmethod
    def docs(text: str | None, indent: str, extra: list[str] | None = None) -> list[str]:
        lines = doc_lines(text) + (extra or [])
        return [f"{indent}/// {line}" for line in lines]

    def model(self, m: ModelDef) -> list[str]:
        extra = ["Deprecated in the contract."] if m.deprecated else []
        if m.schema_path:
            extra.append(f"Schema: `schemas/{m.schema_path}.json`.")
        out = self.docs(m.description, "", extra)
        sensitive = any(f.sensitive for f in m.fields)
        out.append(f"public struct {m.name}: ContractValue{', CustomReflectable' if sensitive else ''} {{")
        for k in ("type", "command"):
            if k in m.fixed:
                out.append(f"    public static let {k} = {raw(m.fixed[k])}")
        for f in m.fields:
            out += self.docs(f.description, "    ")
            out.append(f"    public var {self.prop(f)}: {self.prop_type(f)}")
        # memberwise init
        params = []
        for f in m.fields:
            pt = self.prop_type(f)
            default = " = nil" if pt.endswith("?") and not f.required else ""
            params.append(f"{self.prop(f)}: {pt}{default}")
        out.append("")
        if params:
            out.append("    public init(")
            out += [f"        {p}," for p in params[:-1]] + [f"        {params[-1]}"]
            out.append("    ) {")
            for f in m.fields:
                p = self.prop(f)
                out.append(f"        self.{p} = {p}")
            out.append("    }")
        else:
            out.append("    public init() {}")
        # decoding
        out.append("")
        out.append("    public init(from decoder: any Decoder) throws {")
        if m.fields or m.fixed:
            out.append("        let c = try decoder.container(keyedBy: ContractCodingKey.self)")
        else:
            out.append("        _ = try decoder.container(keyedBy: ContractCodingKey.self)")
        for k in ("type", "command"):
            if k in m.fixed:
                out.append(f'        try c.expectConstant(Self.{k}, forKey: "{k}")')
        for f in m.fields:
            p, key = self.prop(f), self.key(f)
            st = self.ty(f.type)
            if f.required and not st.endswith("?"):
                out.append(f"        {p} = try c.decode({st}.self, forKey: {key})")
            elif f.required:
                out.append(f"        {p} = try c.decode({st}.self, forKey: {key})")
            else:
                out.append(f"        {p} = try c.decodeIfPresent({st.rstrip('?')}.self, forKey: {key})")
        out.append("    }")
        out.append("")
        out.append("    public func encode(to encoder: any Encoder) throws {")
        if m.fields or m.fixed:
            out.append("        var c = encoder.container(keyedBy: ContractCodingKey.self)")
        else:
            out.append("        _ = encoder.container(keyedBy: ContractCodingKey.self)")
        for k in ("type", "command"):
            if k in m.fixed:
                out.append(f'        try c.encode(Self.{k}, forKey: "{k}")')
        for f in m.fields:
            p, key = self.prop(f), self.key(f)
            if f.required:
                out.append(f"        try c.encode({p}, forKey: {key})")
            else:
                out.append(f"        try c.encodeIfPresent({p}, forKey: {key})")
        out.append("    }")
        # validation
        body = []
        for f in m.fields:
            path = f'path + "/" + {sw_str(f.json_name, self.ir)}' if f.ns_key else f'path + "/{f.json_name}"'
            body += self.checks(f.type, self.prop(f), path, opt=self.prop_type(f).endswith("?"))
        if m.dependent_required or m.any_of_required or m.forbidden or m.conditionals:
            fields = {f.json_name: f for f in m.fields}
            body.append("var present_ = Set<String>()")
            for f in m.fields:
                if self.prop_type(f).endswith("?"):
                    body.append(f'if {self.prop(f)} != nil {{ present_.insert({sw_str(f.json_name, self.ir)}) }}')
                else:
                    body.append(f"present_.insert({sw_str(f.json_name, self.ir)})")
            args = []
            if m.dependent_required:
                items = ", ".join(f'"{k}": [{", ".join(chr(34) + x + chr(34) for x in v)}]' for k, v in sorted(m.dependent_required.items()))
                args.append(f"dependentRequired: [{items}]")
            if m.any_of_required:
                args.append("anyOfRequired: [" + ", ".join("[" + ", ".join(f'"{x}"' for x in g) + "]" for g in m.any_of_required) + "]")
            if m.forbidden:
                args.append("forbidden: [" + ", ".join(f'"{x}"' for x in m.forbidden) + "]")
            if m.conditionals:
                conds = []
                for ci, c in enumerate(m.conditionals):
                    f = fields[c.prop]
                    vals = ", ".join(self.literal(x) for x in c.values)
                    raw_value = ".rawValue" if f.type.kind == "enum" else ""
                    if self.prop_type(f).endswith("?"):
                        # JSON Schema: an 'if' on an absent property holds (vacuous truth) unless 'if' requires it
                        matched = f"{self.prop(f)}.map {{ [{vals}].contains($0{raw_value}) }} ?? {'false' if c.presence else 'true'}"
                    else:
                        matched = f"[{vals}].contains({self.prop(f)}{raw_value})"
                    body.append(f"let c{ci}_ = {matched}")
                    for flag, r in ((f"c{ci}_", c.then), (f"!c{ci}_", c.otherwise)):
                        for name, const in sorted((r.consts if r else {}).items()):
                            cf = fields[name]
                            t = Type(**{**cf.type.__dict__, "const": const, "has_const": True})
                            for stmt in self.checks(t, self.prop(cf), f'path + "/{name}"'):
                                body.append(f"if {flag} {{ {stmt} }}")

                    def lst(x):
                        return "[" + ", ".join(f'"{y}"' for y in (x or [])) + "]"

                    o = c.otherwise
                    conds.append(
                        f"(matched: c{ci}_, thenRequired: {lst(c.then.required + c.then.non_null)}, thenForbidden: {lst(c.then.forbidden)}, "
                        f"elseRequired: {lst((o.required + o.non_null) if o else None)}, "
                        f"elseForbidden: {lst(o.forbidden if o else None)})"
                    )
                args.append("conditionals: [" + ", ".join(conds) + "]")
            body.append(f"ContractCheck.object(&v_, path, present: present_, {', '.join(args)})")
        out.append("")
        if sensitive:
            out.append("    /// Debug output without the values of sensitive fields (`x-sensitive`).")
            out.append("    public var customMirror: Mirror {")
            kids = ", ".join(f'"{self.prop(f).strip("`")}": ' + ('"<redacted>"' if f.sensitive else f"{self.prop(f)} as Any") for f in m.fields)
            out.append(f"        Mirror(self, children: [{kids}], displayStyle: .struct)")
            out.append("    }")
            out.append("")
        out.append("    public func validate(at path: String) -> [ContractViolation] {")
        if body:
            out.append("        var v_: [ContractViolation] = []")
            out += ["        " + b for b in body]
            out.append("        return v_")
        else:
            out.append("        []")
        out.append("    }")
        out.append("}")
        return out

    def enum(self, e: EnumDef) -> list[str]:
        out = self.docs(e.description, "")
        cases = [(enum_case(v), v) for v in e.values]
        out.append(f"public enum {e.name}: ContractEnum {{")
        for c, v in cases:
            out.append(f"    case {ident(c)}")
        out.append("    /// A value this contract version does not know (kept for forward compatibility).")
        out.append("    case unknown(String)")
        out.append("")
        out.append(f"    public static let knownCases: [{e.name}] = [{', '.join('.' + c for c, _ in cases)}]")
        out.append("")
        out.append("    public init(rawValue: String) {")
        out.append("        switch rawValue {")
        for c, v in cases:
            out.append(f"        case {sw_str(v, self.ir)}: self = .{c}")
        out.append("        default: self = .unknown(rawValue)")
        out.append("        }")
        out.append("    }")
        out.append("")
        out.append("    public var rawValue: String {")
        out.append("        switch self {")
        for c, v in cases:
            out.append(f"        case .{c}: {sw_str(v, self.ir)}")
        out.append("        case .unknown(let value): value")
        out.append("        }")
        out.append("    }")
        out.append("")
        out.append("    public var isKnown: Bool {")
        out.append("        if case .unknown = self { return false }")
        out.append("        return true")
        out.append("    }")
        out.append("")
        out.append("    public init(from decoder: any Decoder) throws {")
        out.append("        self.init(rawValue: try decoder.singleValueContainer().decode(String.self))")
        out.append("    }")
        out.append("")
        out.append("    public func encode(to encoder: any Encoder) throws {")
        out.append("        var c = encoder.singleValueContainer()")
        out.append("        try c.encode(rawValue)")
        out.append("    }")
        out.append("")
        out.append("    public static func == (lhs: Self, rhs: Self) -> Bool { lhs.rawValue == rhs.rawValue }")
        out.append("    public func hash(into hasher: inout Hasher) { hasher.combine(rawValue) }")
        out.append("}")
        return out

    def union(self, u: UnionDef) -> list[str]:
        cands = ordered_union_candidates(self.ir, u)
        members = sorted({m.model for m in u.members})
        out = self.docs(u.description, "", [f"Schema: `schemas/{u.schema_path}.json`."])
        # Discriminated unions (all WebSocket messages) are indirect and decode every member in its own
        # function: a single init with ~140 inline payload temporaries exceeded the 512 KB stack of a
        # test thread in debug builds (SIGBUS seen on 19.11.2026).
        out.append(f"public {'indirect ' if u.discriminated else ''}enum {u.name}: ContractValue {{")
        for m in members:
            out.append(f"    case {ident(camel(m))}({m})")
        if u.discriminated:
            out.append("    /// A message type (or command) this contract version does not know; kept verbatim.")
            out.append("    case unknown(JSONValue)")
        out.append("")
        out.append("    public init(from decoder: any Decoder) throws {")
        if u.discriminated:
            out.append("        let c = try decoder.container(keyedBy: ContractCodingKey.self)")
            out.append('        let type = try c.decode(String.self, forKey: "type")')
            out.append('        let command = type == "command" ? try c.decodeIfPresent(String.self, forKey: "command") : nil')
            out.append("        switch (type, command) {")
            for tv, cmd, models in cands:
                cmd_s = f'"{cmd}"' if cmd else "nil"
                out.append(f'        case ("{tv}", {cmd_s}):')
                out += ["            " + line for line in self.try_chain_boxed(models)]
            out.append("        default:")
            out.append("            self = .unknown(try JSONValue(from: decoder))")
            out.append("        }")
        else:
            out += ["        " + line for line in self.try_chain(cands[0][2])]
        out.append("    }")
        out.append("")
        if u.discriminated:
            for m in members:
                out.append(f"    @inline(never) private static func decode{m}(_ decoder: any Decoder) throws -> Self {{")
                out.append(f"        .{ident(camel(m))}(try {m}(from: decoder))")
                out.append("    }")
            out.append("")
        out.append("    public func encode(to encoder: any Encoder) throws {")
        out.append("        switch self {")
        for m in members:
            out.append(f"        case .{ident(camel(m))}(let value): try value.encode(to: encoder)")
        if u.discriminated:
            out.append("        case .unknown(let value): try value.encode(to: encoder)")
        out.append("        }")
        out.append("    }")
        out.append("")
        out.append("    /// The decoded payload.")
        out.append("    public var value: any ContractValue {")
        out.append("        switch self {")
        for m in members:
            out.append(f"        case .{ident(camel(m))}(let value): value")
        if u.discriminated:
            out.append("        case .unknown(let value): value")
        out.append("        }")
        out.append("    }")
        out.append("")
        out.append("    public func validate(at path: String) -> [ContractViolation] { value.validate(at: path) }")
        out.append("}")
        return out

    def try_chain_boxed(self, models: list[str]) -> list[str]:
        if len(models) == 1:
            return [f"self = try Self.decode{models[0]}(decoder)"]
        out = []
        for m in models[:-1]:
            out.append(f"if let value = try? Self.decode{m}(decoder) {{")
            out.append("    self = value")
            out.append("    return")
            out.append("}")
        out.append(f"self = try Self.decode{models[-1]}(decoder)")
        return out

    def try_chain(self, models: list[str]) -> list[str]:
        if len(models) == 1:
            return [f"self = .{ident(camel(models[0]))}(try {models[0]}(from: decoder))"]
        out = []
        for m in models[:-1]:
            out.append(f"if let value = try? {m}(from: decoder) {{")
            out.append(f"    self = .{ident(camel(m))}(value)")
            out.append("    return")
            out.append("}")
        out.append(f"self = .{ident(camel(models[-1]))}(try {models[-1]}(from: decoder))")
        return out

    def header(self) -> list[str]:
        return [f"// {line}" for line in header_lines(self.ir)] + ["", "import Foundation", ""]

    def files(self) -> dict[str, str]:
        models = self.header()
        for e in self.ir.ordered_enums():
            models += self.enum(e) + [""]
        for m in topo_models(self.ir):
            models += self.model(m) + [""]
        unions = self.header()
        for u in self.ir.ordered_unions():
            unions += self.union(u) + [""]
        ns = self.header()[:-2] + [
            "/// Technical namespace values (`namespace.json`, `current`). The only generated file that contains",
            "/// namespace literals; models reference these constants.",
            f"public enum {NS_TYPE} {{",
            f'    public static let current = "{self.ir.namespace_current}"',
        ]
        for k, v in self.ir.namespace_values.items():
            ns.append(f'    public static let {camel(k)} = "{v}"')
        ns += ["}", ""]
        reg = self.header() + [
            "/// Schema path (`schemas/<path>.json` without suffix) -> generated type.",
            "public enum ContractSchemaRegistry {",
            f'    public static let contractVersion = "{self.ir.version}"',
            f'    public static let inputHash = "{self.ir.input_hash}"',
            "",
            "    public static let schemaPaths: [String] = [",
        ]
        reg += [f'        "{p}",' for p in self.ir.registry] + ["    ]", ""]
        reg += [
            "    public static func decode(_ schemaPath: String, from data: Data, using decoder: JSONDecoder = JSONDecoder()) throws -> any ContractValue {",
            "        switch schemaPath {",
        ]
        for p, name in self.ir.registry.items():
            reg.append(f'        case "{p}": return try decoder.decode({name}.self, from: data)')
        reg += [
            '        default: throw ContractDecodingError("no generated type for schema \'\\(schemaPath)\'")',
            "        }",
            "    }",
            "}",
            "",
        ]
        runtime = [f"// {header_lines(self.ir)[0]}", ""] + RUNTIME.read_text(encoding="utf-8").splitlines() + [""]
        data = self.header() + [
            "/// Contract data files (`data/*.json`): canonical JSON text and a typed decoder.",
            "public enum ContractData {",
        ]
        for stem, model, text in self.ir.data:
            name = camel(stem)
            # raw string delimiter: one more '#' than any '"#…' run in the text (e.g. colors "#2E7D32")
            hashes = "#"
            while f'"{hashes}' in text:
                hashes += "#"
            data += [
                f"    /// `data/{stem}.json`",
                f'    public static let {name}JSON = {hashes}"{text}"{hashes}',
                "",
                f"    public static func {name}(using decoder: JSONDecoder = JSONDecoder()) throws -> {model} {{",
                f"        try decoder.decode({model}.self, from: Data({name}JSON.utf8))",
                "    }",
                "",
            ]
        if data[-1] == "":
            data.pop()
        data += ["}", ""]
        return {
            "ContractData.swift": "\n".join(data),
            "ContractRuntime.swift": "\n".join(runtime),
            "ContractModels.swift": "\n".join(models),
            "ContractMessages.swift": "\n".join(unions),
            "Namespace.swift": "\n".join(ns),
            "ContractSchemaRegistry.swift": "\n".join(reg),
        }


def emit(ir: IR) -> dict[str, str]:
    return SwiftEmitter(ir).files()
