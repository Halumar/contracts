"""TypeScript emitter: type declarations for the Admin UI (no runtime validation)."""

from __future__ import annotations

import json

from .common import doc_lines, header_lines, upper_snake
from .ir import IR, ModelDef, Type, UnionDef, ns_split


def ts_key(name: str, ir: IR, ns_key: str | None) -> str:
    if ns_key:
        return f"[ns.{upper_snake(ns_key)}]"
    return name if name.isidentifier() else json.dumps(name)


class TsEmitter:
    def __init__(self, ir: IR):
        self.ir = ir

    def ty(self, t: Type) -> str:
        k = t.kind
        if t.has_const:
            parts = ns_split(t.const, self.ir) if isinstance(t.const, str) else None
            if parts and parts[0][0] == "ns" and len(parts) == 1:
                base = f"typeof ns.{upper_snake(parts[0][1])}"
            elif parts and any(p[0] == "ns" for p in parts):
                base = "string"
            else:
                base = json.dumps(t.const)
        elif k == "string":
            base = "string"
        elif k in ("integer", "number"):
            base = "number"
        elif k == "boolean":
            base = "boolean"
        elif k == "boolish":
            base = "Boolish"
        elif k == "json":
            return "unknown"
        elif k == "object_map":
            base = "Record<string, unknown>"
        elif k == "array":
            inner = self.ty(t.items)
            base = f"({inner})[]" if " " in inner else f"{inner}[]"
        else:
            base = t.ref
        return f"{base} | null" if t.nullable else base

    @staticmethod
    def doc(text: str | None, indent: str, extra: list[str] | None = None) -> list[str]:
        lines = doc_lines(text, 92) + (extra or [])
        if not lines:
            return []
        lines = [line.replace("*/", "*\\/") for line in lines]
        if len(lines) == 1:
            return [f"{indent}/** {lines[0]} */"]
        return [f"{indent}/**"] + [f"{indent} * {line}" for line in lines] + [f"{indent} */"]

    def model(self, m: ModelDef) -> list[str]:
        extra = (["@deprecated"] if m.deprecated else []) + ([f"Schema: schemas/{m.schema_path}.json"] if m.schema_path else [])
        out = self.doc(m.description, "", extra)
        out.append(f"export interface {m.name} {{")
        for k in ("type", "command"):
            if k in m.fixed:
                out.append(f"  {k}: {json.dumps(m.fixed[k])};")
        for f in m.fields:
            out += self.doc(f.description, "  ", ["@deprecated"] if f.deprecated else None)
            key = ts_key(f.json_name, self.ir, f.ns_key)
            if f.json_name in m.forbidden:
                out.append(f"  {key}?: never;")
                continue
            out.append(f"  {key}{'' if f.required else '?'}: {self.ty(f.type)};")
        out.append("}")
        return out

    def union(self, u: UnionDef) -> list[str]:
        out = self.doc(u.description, "", [f"Schema: schemas/{u.schema_path}.json"])
        members = sorted({m.model for m in u.members})
        out.append(f"export type {u.name} =")
        out += [f"  | {m}" for m in members[:-1]] + [f"  | {members[-1]};"]
        return out

    def files(self) -> dict[str, str]:
        head = [f"// {line}" for line in header_lines(self.ir)] + [""]
        idx = head + [
            'import * as ns from "./namespace";',
            "",
            'export * as protocolNamespace from "./namespace";',
            "",
            f'export const CONTRACT_VERSION = "{self.ir.version}";',
            "",
            "/** SQLite boolean as delivered today: boolean or 0/1 (known deviation D4 of the contract). */",
            "export type Boolish = boolean | 0 | 1;",
            "",
        ]
        for e in self.ir.ordered_enums():
            idx += self.doc(e.description, "")
            idx.append(f"export type {e.name} = {' | '.join(json.dumps(v) for v in e.values)};")
            idx.append(f"export const {_const_name(e.name)}_VALUES: readonly {e.name}[] = [{', '.join(json.dumps(v) for v in e.values)}];")
            idx.append("")
        for m in self.ir.ordered_models():
            idx += self.model(m) + [""]
        for u in self.ir.ordered_unions():
            idx += self.union(u) + [""]
        idx.append("/** Schema path (schemas/<path>.json without suffix) -> generated type. */")
        idx.append("export interface SchemaTypes {")
        for p, name in self.ir.registry.items():
            idx.append(f"  {json.dumps(p)}: {name};")
        idx.append("}")
        idx.append("")
        nsf = head + [
            "// Technical namespace values (namespace.json, 'current'). The only generated file that",
            "// contains namespace literals; types reference these constants.",
            "",
            f'export const CURRENT = "{self.ir.namespace_current}";',
        ]
        for k, v in self.ir.namespace_values.items():
            nsf.append(f'export const {upper_snake(k)} = "{v}";')
        nsf.append("")
        data = head + [
            "// Contract data files (data/*.json) as typed constants.",
            "",
        ]
        if self.ir.data:
            data += [f'import type {{ {", ".join(sorted({m for _, m, _ in self.ir.data}))} }} from "./index";', ""]
        for stem, model, text in self.ir.data:
            data += [f"/** data/{stem}.json */", f"export const {_const_name(model)}: {model} = {text};", ""]
        return {"index.ts": "\n".join(idx), "namespace.ts": "\n".join(nsf), "data.ts": "\n".join(data)}


def _const_name(name: str) -> str:
    import re

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def emit(ir: IR) -> dict[str, str]:
    return TsEmitter(ir).files()
