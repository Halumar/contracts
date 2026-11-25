"""Kotlin emitter: kotlinx.serialization data classes for the Android apps."""

from __future__ import annotations

from pathlib import Path

from .common import camel, doc_lines, header_lines, topo_models, upper_snake
from .ir import IR, EnumDef, ModelDef, SchemaError, StrRule, Type, UnionDef, ns_split, ordered_union_candidates, regex_for
from .ir import pascal

Q3 = '"' * 3

RUNTIME = Path(__file__).parent / "runtime" / "kotlin" / "ContractRuntime.kt"

KOTLIN_HARD_KEYWORDS = {
    "as", "break", "class", "continue", "do", "else", "false", "for", "fun", "if", "in", "interface", "is", "null",
    "object", "package", "return", "super", "this", "throw", "true", "try", "typealias", "typeof", "val", "var",
    "when", "while",
}
NS_OBJ = "ProtocolNamespace"

# Enum cases are nested objects of the sealed class, so inside the class body a case named like a type shadows
# that type (`object String` turns every `String` in the class into the case). Cases named like a type of the
# default imports (kotlin.*, kotlin.collections.*) or like a name the generated class body uses get the suffix
# `Value` (as `Unknown` -> `UnknownValue`); backticks would not help, `String` and `` `String` `` are the same name.
KOTLIN_RESERVED_CASES = {
    # kotlin.*
    "Any", "Array", "Boolean", "BooleanArray", "Byte", "ByteArray", "Char", "CharArray", "CharSequence", "Comparable",
    "Deprecated", "Double", "DoubleArray", "Enum", "Error", "Exception", "Float", "FloatArray", "Function", "Int",
    "IntArray", "Lazy", "Long", "LongArray", "Nothing", "Number", "Pair", "Result", "Short", "ShortArray", "String",
    "Throwable", "Triple", "UByte", "UInt", "ULong", "UShort", "Unit",
    # kotlin.collections.*
    "ArrayList", "Collection", "HashMap", "HashSet", "Iterable", "Iterator", "LinkedHashMap", "LinkedHashSet", "List",
    "Map", "MutableCollection", "MutableIterable", "MutableList", "MutableMap", "MutableSet", "Sequence", "Set",
    # names in the generated enum body
    "Companion", "ContractEnum", "ContractEnumSerializer", "Serializer", "Unknown",
}


def ident(name: str) -> str:
    return f"`{name}`" if name in KOTLIN_HARD_KEYWORDS else name


def kdoc(line: str) -> str:
    """Text safe inside a /** */ block: Kotlin nests block comments, so '/*' opens one and '*/' closes the KDoc."""
    return line.replace("*/", "*&#47;").replace("/*", "/&#42;")


def kt_lit(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def kt_str(s: str, ir: IR) -> str:
    parts = []
    for kind, val in ns_split(s, ir):
        parts.append(f"{NS_OBJ}.{upper_snake(val)}" if kind == "ns" else kt_lit(val))
    return " + ".join(parts) if parts else '""'


def enum_case(value: str, enum_name: str = "") -> str:
    n = pascal(value) or "Empty"
    if n[0].isdigit():
        n = "V" + n
    if n in KOTLIN_RESERVED_CASES or n == enum_name:
        return n + "Value"
    return n


class KotlinEmitter:
    def __init__(self, ir: IR, package: str):
        self.ir = ir
        self.package = package
        self.patterns: dict[str, str] = {}
        self.memberships: dict[str, list[str]] = {}
        for u in ir.ordered_unions():
            for m in u.members:
                lst = self.memberships.setdefault(m.model, [])
                if u.name not in lst:
                    lst.append(u.name)

    def ty(self, t: Type) -> str:
        k = t.kind
        base = {
            "string": "String", "integer": "StrictLong", "number": "StrictDouble", "boolean": "StrictBoolean", "boolish": "Boolish",
            "json": "JsonElement", "object_map": "JsonObject",
        }.get(k)
        if k == "array":
            base = f"List<{self.ty(t.items)}>"
        elif k in ("enum", "model"):
            base = t.ref
        if k == "json":
            return "JsonElement?"
        return base + "?" if t.nullable else base

    def prop(self, f) -> str:
        return ident(camel(f.ns_key or f.json_name))

    def prop_type(self, f) -> str:
        t = self.ty(f.type)
        if not f.required and not t.endswith("?"):
            t += "?"
        return t

    def pattern(self, p: str) -> str:
        expr = kt_str(regex_for(p, "\\z"), self.ir)
        if expr not in self.patterns:
            self.patterns[expr] = f"P{len(self.patterns) + 1}"
        return f"ContractPatterns.{self.patterns[expr]}"

    def str_rule(self, r: StrRule) -> str:
        args = []
        if r.pattern is not None:
            args.append(f"pattern = {self.pattern(r.pattern)}")
        if r.min_length is not None:
            args.append(f"minLength = {r.min_length}")
        if r.max_length is not None:
            args.append(f"maxLength = {r.max_length}")
        if r.fmt is not None:
            args.append(f'format = "{r.fmt}"')
        if r.enum is not None:
            args.append(f"oneOf = listOf({', '.join(kt_str(v, self.ir) for v in r.enum)})")
        return f"ContractCheck.StringRule({', '.join(args)})"

    def checks(self, t: Type, value: str, path: str, depth: int = 0, opt: bool = True) -> list[str]:
        k = t.kind
        if k == "string":
            args = []
            if t.str_rule and t.str_rule.alternatives is not None:
                args.append(f"alternatives = listOf({', '.join(self.str_rule(a) for a in t.str_rule.alternatives)})")
            elif t.str_rule:
                args.append(f"rule = {self.str_rule(t.str_rule)}")
            if t.has_const:
                args.append(f"const = {kt_str(t.const, self.ir)}")
            return [f"ContractCheck.string(v_, {path}, {value}, {', '.join(args)})"] if args else []
        if k == "integer":
            args = []
            if t.minimum is not None:
                args.append(f"minimum = {int(t.minimum)}L")
            if t.maximum is not None:
                args.append(f"maximum = {int(t.maximum)}L")
            if t.has_const:
                args.append(f"const = {int(t.const)}L")
            return [f"ContractCheck.long(v_, {path}, {value}, {', '.join(args)})"] if args else []
        if k == "number":
            args = [""]
            if t.minimum is not None:
                args.append(f"minimum = {float(t.minimum)!r}")
            if t.maximum is not None:
                args.append(f"maximum = {float(t.maximum)!r}")
            return [f"ContractCheck.double(v_, {path}, {value}{', '.join(args)})"]
        if k == "boolean":
            return [f"ContractCheck.bool(v_, {path}, {value}, const = {'true' if t.const else 'false'})"] if t.has_const else []
        if k in ("enum", "model"):
            return [f"ContractCheck.nested(v_, {path}, {value})"]
        if k == "object_map":
            args = []
            if t.max_properties is not None:
                args.append(f"maxProperties = {t.max_properties}")
            if t.required_keys:
                args.append(f"required = listOf({', '.join(kt_lit(x) for x in t.required_keys)})")
            return [f"ContractCheck.map(v_, {path}, {value}, {', '.join(args)})"] if args else []
        if k == "array":
            out = []
            args = []
            if t.min_items is not None:
                args.append(f"minItems = {t.min_items}")
            if t.max_items is not None:
                args.append(f"maxItems = {t.max_items}")
            if t.unique_items:
                args.append("unique = true")
            if args:
                out.append(f"ContractCheck.items(v_, {path}, {value}, {', '.join(args)})")
            if t.items.kind in ("enum", "model") and not t.items.nullable:
                out.append(f"ContractCheck.nested(v_, {path}, {value})")
                return out
            iv, ii = f"x{depth}_", f"i{depth}_"
            inner = self.checks(t.items, iv, f'{path} + "/" + {ii}', depth + 1, t.items.nullable)
            if inner:
                out.append(f"{value}{'?' if opt else ''}.forEachIndexed {{ {ii}, {iv} ->")
                out += ["    " + s for s in inner]
                out.append("}")
            return out
        return []

    def literal(self, v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return f"{v}L"
        return kt_str(v, self.ir)

    @staticmethod
    def doc(text: str | None, indent: str, extra: list[str] | None = None) -> list[str]:
        lines = [kdoc(line) for line in doc_lines(text) + (extra or [])]
        if not lines:
            return []
        return [f"{indent}/**"] + [f"{indent} * {line}" for line in lines] + [f"{indent} */"]

    def model(self, m: ModelDef) -> list[str]:
        extra = (["Deprecated in the contract."] if m.deprecated else []) + ([f"Schema: `schemas/{m.schema_path}.json`."] if m.schema_path else [])
        out = self.doc(m.description, "", extra)
        out.append("@Serializable")
        params = []
        for k in ("type", "command"):
            if k in m.fixed:
                params.append(f'    @EncodeDefault @SerialName("{k}") val {k}: String = {upper_snake(k)},')
        for f in m.fields:
            params += self.doc(f.description, "    ")
            key = f"{NS_OBJ}.{upper_snake(f.ns_key)}" if f.ns_key else kt_lit(f.json_name)
            pt = self.prop_type(f)
            default = " = null" if not f.required else ""
            params.append(f"    @SerialName({key}) val {self.prop(f)}: {pt}{default},")
        supers = ["ContractValue"] + self.memberships.get(m.name, [])
        if params:
            out.append(f"data class {m.name}(")
            out += params
            out.append(f") : {', '.join(supers)} {{")
        else:
            # no properties: a class without state (data classes need at least one property)
            out.append(f"class {m.name} : {', '.join(supers)} {{")
            out.append(f"    override fun equals(other: Any?): Boolean = other is {m.name}")
            out.append(f'    override fun hashCode(): Int = "{m.name}".hashCode()')
            out.append(f'    override fun toString(): String = "{m.name}()"')
        if m.fixed:
            out.append("    companion object {")
            for k in ("type", "command"):
                if k in m.fixed:
                    out.append(f"        const val {upper_snake(k)}: String = {kt_lit(m.fixed[k])}")
            out.append("    }")
            out.append("")
        if any(f.sensitive for f in m.fields):
            parts = [f'"{k}=" + {k}' for k in ("type", "command") if k in m.fixed]
            parts += [f'"{self.prop(f).strip("`")}=<redacted>"' if f.sensitive else f'"{self.prop(f).strip("`")}=" + {self.prop(f)}' for f in m.fields]
            out.append("    /** Without the values of sensitive fields (x-sensitive). */")
            out.append(f'    override fun toString(): String = "{m.name}(" + listOf({", ".join(parts)}).joinToString(", ") + ")"')
            out.append("")
        body = []
        for k in ("type", "command"):
            if k in m.fixed:
                body.append(f'ContractCheck.string(v_, path + "/{k}", {k}, const = {upper_snake(k)})')
        for f in m.fields:
            path = f'path + "/" + {kt_str(f.json_name, self.ir)}' if f.ns_key else f'path + "/{f.json_name}"'
            body += self.checks(f.type, self.prop(f), path, opt=self.prop_type(f).endswith("?"))
        if m.dependent_required or m.any_of_required or m.forbidden or m.conditionals:
            fields = {f.json_name: f for f in m.fields}
            body.append("val present_ = mutableSetOf<String>()")
            for f in m.fields:
                if self.prop_type(f).endswith("?"):
                    body.append(f"if ({self.prop(f)} != null) present_.add({kt_str(f.json_name, self.ir)})")
                else:
                    body.append(f"present_.add({kt_str(f.json_name, self.ir)})")

            def lst(x):
                return "listOf(" + ", ".join(kt_lit(y) for y in (x or [])) + ")"

            args = []
            if m.dependent_required:
                items = ", ".join(f"{kt_lit(k)} to {lst(v)}" for k, v in sorted(m.dependent_required.items()))
                args.append(f"dependentRequired = mapOf({items})")
            if m.any_of_required:
                args.append("anyOfRequired = listOf(" + ", ".join(lst(g) for g in m.any_of_required) + ")")
            if m.forbidden:
                args.append(f"forbidden = {lst(m.forbidden)}")
            if m.conditionals:
                conds = []
                for ci, c in enumerate(m.conditionals):
                    f = fields[c.prop]
                    vals = ", ".join(self.literal(x) for x in c.values)
                    rv = ".value" if f.type.kind == "enum" else ""
                    if self.prop_type(f).endswith("?"):
                        # JSON Schema: an 'if' on an absent property holds (vacuous truth) unless 'if' requires it
                        matched = f"{self.prop(f)}?.let {{ it{rv} in listOf({vals}) }} ?: {'false' if c.presence else 'true'}"
                    else:
                        matched = f"{self.prop(f)}{rv} in listOf({vals})"
                    body.append(f"val c{ci}_ = {matched}")
                    for flag, r in ((f"c{ci}_", c.then), (f"!c{ci}_", c.otherwise)):
                        for name, const in sorted((r.consts if r else {}).items()):
                            cf = fields[name]
                            t = Type(**{**cf.type.__dict__, "const": const, "has_const": True})
                            for stmt in self.checks(t, self.prop(cf), f'path + "/{name}"'):
                                body.append(f"if ({flag}) {stmt}")
                    o = c.otherwise
                    conds.append(
                        f"ContractCheck.Conditional(c{ci}_, {lst(c.then.required + c.then.non_null)}, {lst(c.then.forbidden)}, "
                        f"{lst((o.required + o.non_null) if o else None)}, {lst(o.forbidden if o else None)})"
                    )
                args.append("conditionals = listOf(" + ", ".join(conds) + ")")
            body.append(f"ContractCheck.obj(v_, path, present_, {', '.join(args)})")
        if body:
            out.append("    override fun validate(path: String): List<ContractViolation> {")
            out.append("        val v_ = mutableListOf<ContractViolation>()")
            out += ["        " + b for b in body]
            out.append("        return v_")
            out.append("    }")
        else:
            out.append("    override fun validate(path: String): List<ContractViolation> = emptyList()")
        out.append("}")
        return out

    def enum(self, e: EnumDef) -> list[str]:
        out = self.doc(e.description, "")
        cases = [(enum_case(v, e.name), v) for v in e.values]
        names = [c for c, _ in cases]
        if len(set(names)) != len(names):
            raise SchemaError(f"{e.name}: enum values map to the same Kotlin case: {sorted(n for n in names if names.count(n) > 1)}")
        out.append(f"@Serializable(with = {e.name}.Serializer::class)")
        out.append(f"sealed class {e.name}(override val value: String) : ContractEnum {{")
        for c, v in cases:
            out.append(f"    object {c} : {e.name}({kt_str(v, self.ir)})")
        out.append("")
        out.append("    /** A value this contract version does not know (kept for forward compatibility). */")
        out.append(f"    class Unknown(raw: String) : {e.name}(raw)")
        out.append("")
        out.append("    override val isKnown: Boolean get() = this !is Unknown")
        out.append(f"    override fun equals(other: Any?): Boolean = other is {e.name} && other.value == value")
        out.append("    override fun hashCode(): Int = value.hashCode()")
        out.append("    override fun toString(): String = value")
        out.append("")
        out.append("    companion object {")
        out.append(f"        val knownValues: List<{e.name}> by lazy {{ listOf({', '.join(c for c, _ in cases)}) }}")
        out.append("")
        out.append(f"        fun of(value: String): {e.name} = when (value) {{")
        for c, v in cases:
            out.append(f"            {kt_str(v, self.ir)} -> {c}")
        out.append("            else -> Unknown(value)")
        out.append("        }")
        out.append("    }")
        out.append("")
        out.append(f'    object Serializer : ContractEnumSerializer<{e.name}>("{self.package}.{e.name}", {{ of(it) }})')
        out.append("}")
        return out

    def union(self, u: UnionDef) -> list[str]:
        cands = ordered_union_candidates(self.ir, u)
        members = sorted({m.model for m in u.members})
        out = self.doc(u.description, "", [f"Schema: `schemas/{u.schema_path}.json`."])
        out.append(f"@Serializable(with = {u.name}Serializer::class)")
        out.append(f"sealed interface {u.name} : ContractValue")
        out.append("")
        out.append(f"object {u.name}Serializer : KSerializer<{u.name}> {{")
        out.append(f'    override val descriptor: SerialDescriptor = buildClassSerialDescriptor("{self.package}.{u.name}")')
        out.append("")
        out.append(f"    override fun deserialize(decoder: Decoder): {u.name} {{")
        out.append("        val (json, obj) = ContractUnions.obj(decoder)")
        if u.discriminated:
            out.append('        val type = ContractUnions.stringField(obj, "type") ?: throw SerializationException("message without a string \'type\'")')
            out.append('        val key = if (type == "command") type + "/" + (ContractUnions.stringField(obj, "command") ?: "") else type')
            out.append("        return when (key) {")
            for tv, cmd, models in cands:
                k = f"{tv}/{cmd}" if cmd else tv
                sers = ", ".join(f"{m}.serializer()" for m in models)
                if len(models) == 1:
                    out.append(f"            {kt_lit(k)} -> json.decodeFromJsonElement({models[0]}.serializer(), obj)")
                else:
                    out.append(f"            {kt_lit(k)} -> ContractUnions.firstOf<{u.name}>(json, obj, {sers})")
            out.append("            else -> UnknownMessage(obj)")
            out.append("        }")
        else:
            sers = ", ".join(f"{m}.serializer()" for m in cands[0][2])
            out.append(f"        return ContractUnions.firstOf<{u.name}>(json, obj, {sers})")
        out.append("    }")
        out.append("")
        out.append(f"    override fun serialize(encoder: Encoder, value: {u.name}) {{")
        out.append("        when (value) {")
        for m in members:
            out.append(f"            is {m} -> encoder.encodeSerializableValue({m}.serializer(), value)")
        if u.discriminated:
            out.append("            is UnknownMessage -> ContractUnions.encodeRaw(encoder, value.raw)")
        out.append("        }")
        out.append("    }")
        out.append("}")
        return out

    def header(self, imports: list[str], opt_in: bool = False) -> list[str]:
        out = [f"// {line}" for line in header_lines(self.ir)]
        if opt_in:
            out += ["@file:OptIn(ExperimentalSerializationApi::class)"]
        out += ["", f"package {self.package}", ""]
        out += [f"import {i}" for i in sorted(imports)]
        return out + [""]

    def files(self) -> dict[str, str]:
        body = []
        for e in self.ir.ordered_enums():
            body += self.enum(e) + [""]
        for m in topo_models(self.ir):
            body += self.model(m) + [""]
        pats = ["internal object ContractPatterns {"]
        pats += [f"    val {name} = Regex({expr})" for expr, name in self.patterns.items()]
        pats += ["}", ""]
        models = self.header([
            "kotlinx.serialization.EncodeDefault", "kotlinx.serialization.ExperimentalSerializationApi",
            "kotlinx.serialization.SerialName", "kotlinx.serialization.Serializable",
            "kotlinx.serialization.json.JsonElement", "kotlinx.serialization.json.JsonObject",
        ], opt_in=True) + pats + body
        unions = self.header([
            "kotlinx.serialization.KSerializer", "kotlinx.serialization.SerializationException",
            "kotlinx.serialization.Serializable", "kotlinx.serialization.descriptors.SerialDescriptor",
            "kotlinx.serialization.descriptors.buildClassSerialDescriptor", "kotlinx.serialization.encoding.Decoder",
            "kotlinx.serialization.encoding.Encoder",
        ])
        for u in self.ir.ordered_unions():
            unions += self.union(u) + [""]
        ns = self.header([])[:-1] + [
            "/** Technical namespace values (namespace.json, 'current'). The only generated file that contains",
            " *  namespace literals; models reference these constants. */",
            f"object {NS_OBJ} {{",
            f'    const val CURRENT: String = "{self.ir.namespace_current}"',
        ]
        for k, v in self.ir.namespace_values.items():
            ns.append(f'    const val {upper_snake(k)}: String = "{v}"')
        ns += ["}", ""]
        reg = self.header(["kotlinx.serialization.KSerializer"]) + [
            "/** Schema path (schemas/<path>.json without suffix) -> generated serializer. */",
            "object ContractSchemaRegistry {",
            f'    const val CONTRACT_VERSION: String = "{self.ir.version}"',
            f'    const val INPUT_HASH: String = "{self.ir.input_hash}"',
            "",
            "    val schemaPaths: List<String> = listOf(",
        ]
        reg += [f'        "{p}",' for p in self.ir.registry] + ["    )", ""]
        reg.append("    fun serializerFor(schemaPath: String): KSerializer<out ContractValue> = when (schemaPath) {")
        for p, name in self.ir.registry.items():
            ser = f"{name}.serializer()" if name in self.ir.models else f"{name}Serializer"
            reg.append(f'        "{p}" -> {ser}')
        reg.append('        else -> throw IllegalArgumentException("no generated type for schema \'" + schemaPath + "\'")')
        reg += ["    }", "}", ""]
        unknown_supers = ", ".join(u.name for u in self.ir.ordered_unions() if u.discriminated) or "ContractValue"
        runtime = RUNTIME.read_text(encoding="utf-8").replace("__PACKAGE__", self.package).replace("__UNKNOWN_SUPERTYPES__", unknown_supers)
        runtime = f"// {header_lines(self.ir)[0]}\n" + runtime
        d = self.package.replace(".", "/")
        data = self.header([]) + [
            f"/** {kdoc('Contract data files (data/*.json): canonical JSON text and a typed decoder.')} */",
            "object ContractData {",
        ]
        for stem, model, text in self.ir.data:
            name = camel(stem)
            literal = text.replace("$", "${'$'}")
            data += [
                f"    /** {kdoc(f'data/{stem}.json')} */",
                f'    val {upper_snake(stem)}_JSON: String = {Q3}{literal}{Q3}',
                "",
                f"    fun {name}(): {model} = ContractJson.decodeFromString({model}.serializer(), {upper_snake(stem)}_JSON)",
                "",
            ]
        if data[-1] == "":
            data.pop()
        data += ["}", ""]
        return {
            f"{d}/ContractData.kt": "\n".join(data),
            f"{d}/ContractRuntime.kt": runtime,
            f"{d}/Models.kt": "\n".join(models),
            f"{d}/Messages.kt": "\n".join(unions),
            f"{d}/Namespace.kt": "\n".join(ns),
            f"{d}/SchemaRegistry.kt": "\n".join(reg),
        }


def emit(ir: IR, package: str = "hubcontracts") -> dict[str, str]:
    return KotlinEmitter(ir, package).files()
