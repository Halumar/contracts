"""Python emitter: pydantic v2 models (package ``hub_contracts`` by default)."""

from __future__ import annotations

import keyword
from pathlib import Path

from .common import doc_lines, header_lines, topo_models, upper_snake
from .ir import IR, ModelDef, StrRule, Type, UnionDef, ns_split, ordered_union_candidates, regex_for

Q3 = '"' * 3

RUNTIME = Path(__file__).parent / "runtime" / "python" / "_runtime.py"

# attributes of pydantic.BaseModel that a field must not shadow
_BASEMODEL_ATTRS = {
    "construct", "copy", "dict", "json", "parse_file", "parse_obj", "parse_raw", "schema", "schema_json",
    "update_forward_refs", "validate", "from_orm", "fields", "from_dict", "from_json", "to_dict", "to_json",
    "contract_errors",
}


def py_attr(json_name: str, ns_key: str | None) -> str:
    name = ns_key if ns_key else json_name
    if keyword.iskeyword(name) or name in _BASEMODEL_ATTRS or name.startswith(("model_", "_")):
        name += "_"
    return name


def py_str(s: str, ir: IR) -> str:
    """Python expression for a literal; namespace parts reference hub_contracts.namespace."""
    parts = ns_split(s, ir)
    exprs = []
    for kind, val in parts:
        exprs.append(f"_ns.{upper_snake(val)}" if kind == "ns" else repr(val))
    return " + ".join(exprs) if exprs else "''"


class PythonEmitter:
    def __init__(self, ir: IR, package: str):
        self.ir = ir
        self.package = package
        self.regexes: dict[str, str] = {}  # expr -> const name

    # -- types -----------------------------------------------------------------

    def ann(self, t: Type) -> str:
        k = t.kind
        if k == "string":
            base = "StrictStr"
        elif k == "integer":
            base = "StrictInt"
        elif k == "number":
            base = "_rt.Number"
        elif k == "boolean":
            base = "StrictBool"
        elif k == "boolish":
            base = "_rt.Boolish"
        elif k == "json":
            return "Any"
        elif k == "object_map":
            base = "dict[str, Any]"
        elif k == "array":
            base = f"list[{self.ann(t.items)}]"
        elif k == "enum":
            base = f"{t.ref}Value"
        elif k == "model":
            base = t.ref
        else:
            raise ValueError(k)
        return f"{base} | None" if t.nullable else base

    def regex(self, pattern: str) -> str:
        expr = py_str(regex_for(pattern, r"\Z"), self.ir)
        if expr not in self.regexes:
            self.regexes[expr] = f"_RE_{len(self.regexes) + 1}"
        return self.regexes[expr]

    def str_rule_kwargs(self, r: StrRule) -> list[str]:
        kw = []
        if r.alternatives is not None:
            alts = []
            for a in r.alternatives:
                inner = ", ".join(f"{x.split('=', 1)[0]!r}: {x.split('=', 1)[1]}" for x in self.str_rule_kwargs(a))
                alts.append("{" + inner + "}")
            kw.append(f"alternatives=({', '.join(alts)},)")
            return kw
        if r.pattern is not None:
            kw.append(f"pattern={self.regex(r.pattern)}")
        if r.min_length is not None:
            kw.append(f"min_length={r.min_length}")
        if r.max_length is not None:
            kw.append(f"max_length={r.max_length}")
        if r.fmt is not None:
            kw.append(f"fmt={r.fmt!r}")
        if r.enum is not None:
            kw.append(f"enum=({', '.join(py_str(v, self.ir) for v in r.enum)},)")
        return kw

    def checks(self, t: Type, value: str, path: str, depth: int = 0) -> list[str]:
        """Statements (without indentation) checking ``value``; empty when nothing to check."""
        k = t.kind
        if k == "string":
            kw = self.str_rule_kwargs(t.str_rule) if t.str_rule else []
            if t.has_const:
                kw.append(f"const={py_str(t.const, self.ir)}")
            return [f"_rt.check_str(e, {path}, {value}, {', '.join(kw)})"] if kw else []
        if k in ("integer", "number"):
            kw = []
            if t.minimum is not None:
                kw.append(f"minimum={t.minimum!r}")
            if t.maximum is not None:
                kw.append(f"maximum={t.maximum!r}")
            if t.has_const:
                kw.append(f"const={t.const!r}")
            if k == "number":
                kw.append("finite=True")
            return [f"_rt.check_num(e, {path}, {value}, {', '.join(kw)})"] if kw else []
        if k == "boolean":
            return [f"_rt.check_bool(e, {path}, {value}, const={t.const!r})"] if t.has_const else []
        if k == "enum":
            return [f"_rt.check_enum(e, {path}, {value}, {t.ref})"]
        if k == "model":
            return [f"_rt.check_model(e, {path}, {value})"]
        if k == "object_map":
            kw = []
            if t.max_properties is not None:
                kw.append(f"max_properties={t.max_properties}")
            if t.required_keys:
                kw.append(f"required={tuple(t.required_keys)!r}")
            return [f"_rt.check_map(e, {path}, {value}, {', '.join(kw)})"] if kw else []
        if k == "array":
            out = []
            kw = []
            if t.min_items is not None:
                kw.append(f"min_items={t.min_items}")
            if t.max_items is not None:
                kw.append(f"max_items={t.max_items}")
            if t.unique_items:
                kw.append("unique=True")
            if kw:
                out.append(f"_rt.check_items(e, {path}, {value}, {', '.join(kw)})")
            iv, ii = f"x{depth}", f"i{depth}"
            inner = self.checks(t.items, iv, f'f"{{{path}}}/{{{ii}}}"', depth + 1)
            if inner:
                out.append(f"for {ii}, {iv} in enumerate({value} or ()):")
                out += ["    " + s for s in inner]
            return out
        return []

    # -- emit ------------------------------------------------------------------

    def model(self, m: ModelDef) -> list[str]:
        out = [f"class {m.name}(_rt.ContractModel):"]
        doc = doc_lines(m.description)
        if m.deprecated:
            doc.append("Deprecated in the contract.")
        if m.schema_path:
            doc.append(f"Schema: schemas/{m.schema_path}.json")
        if doc:
            out.append('    """' + doc[0] + ("" if len(doc) > 1 else '"""'))
            out += ["    " + d for d in doc[1:]]
            if len(doc) > 1:
                out.append('    """')
            out.append("")
        if m.fixed:
            out.append(f"    __fixed__: ClassVar[dict[str, str]] = {dict(sorted(m.fixed.items()))!r}")
        aliases = {f.json_name: py_attr(f.json_name, f.ns_key) for f in m.fields if py_attr(f.json_name, f.ns_key) != f.json_name}
        if aliases:
            items = ", ".join(f"{py_str(k, self.ir)}: {v!r}" for k, v in sorted(aliases.items()))
            out.append(f"    __aliases__: ClassVar[dict[str, str]] = {{{items}}}")
        if m.additional is False:
            out.append("    __closed__: ClassVar[bool] = True")
        for k, v in m.fixed.items():
            out.append(f"    {k}: Literal[{v!r}] = {v!r}")
        for f in m.fields:
            attr = py_attr(f.json_name, f.ns_key)
            ann = self.ann(f.type)
            if not f.required and not f.type.nullable:
                ann += " | None"
            args = []
            if attr != f.json_name:
                args.append(f"alias={py_str(f.json_name, self.ir)}")
            if f.description:
                args.append(f"description={f.description!r}")
            if f.deprecated:
                args.append("deprecated=True")
            if f.sensitive:
                args.append("repr=False")
            if f.required:
                default = f" = Field({', '.join(args)})" if args else ""
            else:
                default = f" = Field(None, {', '.join(args)})" if args else " = None"
            out.append(f"    {attr}: {ann}{default}")
        if not m.fixed and not m.fields:
            out.append("    pass")
        body = []
        for f in m.fields:
            attr = py_attr(f.json_name, f.ns_key)
            path = f'p + "/" + {py_str(f.json_name, self.ir)}' if f.ns_key else f'p + "/{f.json_name}"'
            body += self.checks(f.type, f"self.{attr}", path)
        okw = []
        if m.dependent_required:
            okw.append(f"dependent={dict(sorted(m.dependent_required.items()))!r}")
        if m.any_of_required:
            okw.append(f"any_of={m.any_of_required!r}")
        if m.forbidden:
            okw.append(f"forbidden={m.forbidden!r}")
        if m.conditionals:
            def rule(r):
                if r is None:
                    return None
                d = {"required": r.required, "forbidden": r.forbidden, "consts": r.consts, "non_null": r.non_null}
                return {k: v for k, v in d.items() if v}

            conds = [{"prop": c.prop, "values": c.values, "presence": c.presence, "then": rule(c.then), "else": rule(c.otherwise)}
                     for c in m.conditionals]
            okw.append(f"conditionals={conds!r}")
        if m.max_properties is not None:
            okw.append(f"max_properties={m.max_properties}")
        if isinstance(m.additional, Type):
            if m.additional.kind != "string" or m.additional.str_rule:
                raise ValueError(f"{m.name}: additionalProperties schema other than plain string")
            okw.append("extra_check=_rt.extra_str_check(e)")
        if okw or m.additional is False:
            body.append(f"self._check_object(p, e, {', '.join(okw)})" if okw else "self._check_object(p, e)")
        if body:
            out.append("")
            out.append("    def _check(self, p: str, e: list[str]) -> None:")
            out += ["        " + s for s in body]
        return out

    def enum(self, e) -> list[str]:
        out = [f"class {e.name}(StrEnum):"]
        for d in doc_lines(e.description)[:1]:
            out.append(f'    """{d}"""')
        for v in e.values:
            out.append(f"    {self.enum_member(v)} = {py_str(v, self.ir)}")
        out.append("")
        out.append("")
        out.append(f'{e.name}Value = Annotated[Union[{e.name}, StrictStr], Field(union_mode="left_to_right")]')
        out.append(f'"""{e.name} or an unknown future value (plain str)."""')
        return out

    @staticmethod
    def enum_member(v: str) -> str:
        n = upper_snake(v) or "EMPTY"
        if n[0].isdigit():
            n = "V_" + n
        return n

    def models_file(self) -> str:
        body: list[str] = []
        for e in self.ir.ordered_enums():
            body += ["", ""] + self.enum(e)
        for m in topo_models(self.ir):
            body += ["", ""] + self.model(m)
        head = ['"""' + header_lines(self.ir)[0], header_lines(self.ir)[1], '"""', ""]
        head += [
            "import re",
            "from enum import StrEnum",
            "from typing import Annotated, Any, ClassVar, Literal, Union",
            "",
            "from pydantic import Field, StrictBool, StrictInt, StrictStr",
            "",
            "from . import _runtime as _rt",
            "from . import namespace as _ns",
            "",
        ]
        for expr, name in self.regexes.items():
            head.append(f"{name} = re.compile({expr})")
        all_names = [e.name for e in self.ir.ordered_enums()] + [f"{e.name}Value" for e in self.ir.ordered_enums()]
        all_names += [m.name for m in self.ir.ordered_models()]
        tail = ["", "", "__all__ = ["] + [f"    {n!r}," for n in sorted(all_names)] + ["]", ""]
        return "\n".join(head + body + tail)

    def union(self, u: UnionDef) -> list[str]:
        members = sorted({m.model for m in u.members})
        out = [f"{u.name} = Union[{', '.join(members + (['UnknownMessage'] if u.discriminated else []))}]"]
        if u.description:
            out.append('"""' + " ".join(doc_lines(u.description)) + '"""')
        out += ["", ""]
        fn = "parse_" + _snake(u.name)
        out.append(f"def {fn}(data: Any) -> {u.name}:")
        out.append(f'    """Decodes a {u.name} (schemas/{u.schema_path}.json); raises pydantic.ValidationError on a known')
        out.append('    discriminator with an invalid shape."""')
        out.append("    if isinstance(data, (str, bytes)):")
        out.append("        data = json.loads(data)")
        cands = ordered_union_candidates(self.ir, u)
        if u.discriminated:
            out.append('    if not isinstance(data, dict) or not isinstance(data.get("type"), str):')
            out.append('        raise ValueError("message must be an object with a string \'type\'")')
            out.append('    key = (data["type"], data.get("command") if data["type"] == "command" else None)')
            out.append(f"    candidates = _{upper_snake(u.name)}_CANDIDATES.get(key)")
            out.append("    if candidates is None:")
            out.append("        return UnknownMessage(raw=data)")
        else:
            out.append(f"    candidates = _{upper_snake(u.name)}_CANDIDATES[(None, None)]")
        out.append("    error: Exception | None = None")
        out.append("    for cls in candidates:")
        out.append("        try:")
        out.append("            return cls.model_validate(data)")
        out.append("        except ValidationError as exc:")
        out.append("            error = error or exc")
        out.append("    assert error is not None")
        out.append("    raise error")
        out.append("")
        out.append("")
        table = [f"_{upper_snake(u.name)}_CANDIDATES: dict[tuple[str | None, str | None], tuple[type, ...]] = {{"]
        for tv, cmd, models in cands:
            table.append(f"    ({tv!r}, {cmd!r}): ({', '.join(models)},),")
        table.append("}")
        return table + ["", ""] + out

    def unions_file(self) -> str:
        names = sorted({m.model for u in self.ir.unions.values() for m in u.members})
        lines = ['"""' + header_lines(self.ir)[0], header_lines(self.ir)[1], '"""', ""]
        lines += [
            "from __future__ import annotations",
            "",
            "import json",
            "from dataclasses import dataclass",
            "from typing import Any, Union",
            "",
            "from pydantic import ValidationError",
            "",
            "from .models import (",
        ] + [f"    {n}," for n in names] + [")", "", ""]
        lines += [
            "@dataclass(frozen=True)",
            "class UnknownMessage:",
            '    """Message with a type (or command) this contract version does not know; kept verbatim."""',
            "",
            "    raw: dict[str, Any]",
            "",
            "    @property",
            "    def type(self) -> str:",
            '        return self.raw["type"]',
            "",
            "    def to_dict(self) -> dict[str, Any]:",
            "        return self.raw",
            "",
            "    def contract_errors(self) -> list[str]:",
            "        return []",
            "",
            "",
        ]
        for u in self.ir.ordered_unions():
            lines += self.union(u) + ["", ""]
        exports = ["UnknownMessage"] + [u.name for u in self.ir.ordered_unions()] + ["parse_" + _snake(u.name) for u in self.ir.ordered_unions()]
        lines += ["__all__ = ["] + [f"    {n!r}," for n in sorted(exports)] + ["]", ""]
        return "\n".join(lines)

    def namespace_file(self) -> str:
        lines = ['"""' + header_lines(self.ir)[0], header_lines(self.ir)[1], "",
                 "Technical namespace values (namespace.json, 'current'). The only generated file that",
                 'contains namespace literals; models reference these constants."""', ""]
        lines.append(f"CURRENT = {self.ir.namespace_current!r}")
        for k, v in self.ir.namespace_values.items():
            lines.append(f"{upper_snake(k)} = {v!r}")
        lines.append("")
        return "\n".join(lines)

    def registry_file(self) -> str:
        lines = ['"""' + header_lines(self.ir)[0], header_lines(self.ir)[1], "",
                 'Schema path (schemas/<path>.json without suffix) -> model class or union parser."""', ""]
        lines += ["from __future__ import annotations", "", "from typing import Any, Callable", "", "from . import models, unions", "", ""]
        lines.append("SCHEMA_TYPES: dict[str, Callable[[Any], Any]] = {")
        for path, name in self.ir.registry.items():
            if name in self.ir.models:
                lines.append(f"    {path!r}: models.{name}.model_validate,")
            else:
                lines.append(f"    {path!r}: unions.parse_{_snake(name)},")
        lines.append("}")
        lines += ["", "", "def parse(schema_path: str, data: Any) -> Any:",
                  '    """Decodes ``data`` as the type generated for ``schemas/<schema_path>.json``."""',
                  "    return SCHEMA_TYPES[schema_path](data)", ""]
        return "\n".join(lines)

    def init_file(self) -> str:
        lines = ['"""Contract models of the hub protocol.', "", header_lines(self.ir)[0], header_lines(self.ir)[1], '"""', ""]
        lines += [
            "from . import namespace",
            "from ._runtime import Boolish, ContractModel, as_bool",
            "from .models import *  # noqa: F403",
            "from .registry import SCHEMA_TYPES, parse",
            "from .unions import *  # noqa: F403",
            "",
            f'CONTRACT_VERSION = "{self.ir.version}"',
            f'CONTRACT_INPUT_HASH = "{self.ir.input_hash}"',
            "",
        ]
        return "\n".join(lines)

    def data_file(self) -> str:
        lines = [Q3 + header_lines(self.ir)[0], "", "Contract data files (data/*.json): canonical JSON text and a typed, cached loader.",
                 Q3, "", "from __future__ import annotations", "", "from functools import cache", ""]
        names = sorted({model for _, model, _ in self.ir.data})
        if names:
            lines += [f"from .models import {', '.join(names)}", ""]
        for stem, model, text in self.ir.data:
            const = upper_snake(stem)
            lines += ["", f"{const}_JSON = {text!r}", "", "", "@cache",
                      f"def {upper_snake(stem).lower()}() -> {model}:",
                      f"    {Q3}data/{stem}.json, parsed (cached).{Q3}",
                      f"    return {model}.from_json({const}_JSON)", ""]
        return "\n".join(lines).rstrip("\n") + "\n"

    def files(self) -> dict[str, str]:
        models = self.models_file()  # fills self.regexes
        p = self.package
        return {
            f"{p}/__init__.py": self.init_file(),
            f"{p}/data.py": self.data_file(),
            f"{p}/_runtime.py": "# " + header_lines(self.ir)[0] + "\n" + RUNTIME.read_text(encoding="utf-8"),
            f"{p}/models.py": models,
            f"{p}/namespace.py": self.namespace_file(),
            f"{p}/registry.py": self.registry_file(),
            f"{p}/unions.py": self.unions_file(),
        }


def _snake(name: str) -> str:
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def emit(ir: IR, package: str = "hub_contracts") -> dict[str, str]:
    return PythonEmitter(ir, package).files()
