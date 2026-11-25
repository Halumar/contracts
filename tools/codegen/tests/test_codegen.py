#!/usr/bin/env python3
"""Tests for tools/codegen (stdlib unittest).

  python tools/codegen/tests/test_codegen.py [-v] [-k pattern]

Needs pydantic>=2.10 and the validator dependencies (tools/codegen/requirements.txt).
Language round trips run when the toolchain is available, otherwise they are skipped with a reason:
  Swift   `swift` on PATH (macOS / Linux toolchain)                   CODEGEN_SKIP_SWIFT=1 to skip
  Kotlin  GRADLE (path to gradle or a gradlew) or gradle on PATH, JDK 21  CODEGEN_SKIP_KOTLIN=1 to skip
          (Gradle project tools/codegen/kotlin-check compiles snapshots/kotlin with -Werror, then runs the harness)
  TS      TSC (path to tsc) or npx on PATH                            CODEGEN_SKIP_TS=1 to skip
Set CODEGEN_REQUIRE_ALL=1 (CI) to turn skips into failures.

Build products go to a temporary directory, never into the repository.
"""

from __future__ import annotations

import importlib
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODEGEN = HERE.parent
REPO = CODEGEN.parent.parent
SNAPSHOTS = CODEGEN / "snapshots"
FIXTURES = REPO / "fixtures"
sys.path.insert(0, str(CODEGEN))
sys.path.insert(0, str(REPO / "tools"))

import generate  # noqa: E402


def gen(*args: str) -> int:
    with contextlib.redirect_stdout(io.StringIO()):
        return generate.main(list(args))


from hubgen.ir import IR, SchemaError, Type, build_ir  # noqa: E402

LANG_DIRS = {"python": "python", "ts": "typescript", "swift": "swift", "kotlin": "kotlin"}
NAMESPACE_FILES = {"hub_contracts/namespace.py", "namespace.ts", "Namespace.swift", "hubcontracts/Namespace.kt"}
REQUIRE_ALL = os.environ.get("CODEGEN_REQUIRE_ALL") == "1"
CLOSED_OBJECT_VALIDATORS = {"additionalProperties", "unevaluatedProperties"}


def skip_or_fail(reason: str):
    if REQUIRE_ALL:
        raise AssertionError(f"CODEGEN_REQUIRE_ALL=1 but {reason}")
    raise unittest.SkipTest(reason)


# ── fixture model ─────────────────────────────────────────────────────────────


def json_equal(a, b) -> bool:
    """Semantic JSON equality that, unlike ==, keeps true and 1 apart."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def project(ir: IR, t: Type, v):
    """What a typed client (Swift, Kotlin) re-encodes: unknown keys dropped, optional nulls omitted."""
    if v is None:
        return None
    if t.kind == "model":
        m = ir.models[t.ref]
        out = {k: v[k] for k in m.fixed if k in v}
        for f in m.fields:
            if f.json_name not in v:
                continue
            val = v[f.json_name]
            if val is None and not f.required:
                continue
            out[f.json_name] = project(ir, f.type, val)
        return out
    if t.kind == "array":
        return [project(ir, t.items, x) for x in v]
    return v


def union_for(schema_path: str) -> str | None:
    if schema_path.startswith("ws/client/"):
        return "ws/client-message"
    if schema_path.startswith(("ws/server/", "ws/command/", "ws/broadcast/", "ws/heartbeat/")):
        return "ws/server-message"
    return None


class Fixtures:
    ir: IR | None = None

    @classmethod
    def get_ir(cls) -> IR:
        if cls.ir is None:
            cls.ir = build_ir(REPO)
        return cls.ir

    @staticmethod
    def all() -> list[tuple[str, str, bool]]:
        """[(fixture path relative to repo, schema path, expect_invalid)] without crypto vectors' semantics.

        invalid-semantic-* fixtures satisfy the schema and fail only a check of tools/validate.py
        (e.g. resolver vectors, client_config consistency): for the models they are valid."""
        out = []
        for fx in sorted(FIXTURES.rglob("*.json")):
            schema = fx.parent.relative_to(FIXTURES).as_posix()
            out.append((fx.relative_to(REPO).as_posix(), schema,
                        fx.name.startswith("invalid-") and not fx.name.startswith("invalid-semantic-")))
        return out

    @classmethod
    def expected(cls, schema: str, data):
        ir = cls.get_ir()
        name = ir.registry[schema]
        if name in ir.models:
            return project(ir, Type("model", ref=name), data)
        union = ir.unions[name]
        # shape union: the projection of the first member that the data satisfies structurally
        for m in union.members:
            req = [f.json_name for f in ir.models[m.model].fields if f.required]
            if all(k in data for k in req):
                return project(ir, Type("model", ref=m.model), data)
        raise AssertionError(f"no member of {name} fits")

    @classmethod
    def manifest(cls) -> list[dict]:
        ir = cls.get_ir()
        out = []
        for fx, schema, _ in cls.all():
            entry = {"fixture": fx, "schema": schema, "union": union_for(schema)}
            out.append(entry)
        assert all(e["schema"] in ir.registry for e in out)
        return out


# Home Assistant attributes of relayed states are a free JSON object: every attribute survives a
# decode (a typed container would drop all but its own keys and empty every tile on the hub path).
FREE_ATTRIBUTES_FIXTURE = "fixtures/ws/server/entity_state/media-player-picture.json"
FREE_ATTRIBUTE_TYPES = {
    "python": ("attributes: dict[str, Any] | None = None",),
    "typescript": ("attributes?: Record<string, unknown>;",),
    "swift": ("public var attributes: [String: JSONValue]?",),
    "kotlin": ('@SerialName("attributes") val attributes: JsonObject? = null,',),
}
FREE_ATTRIBUTE_MODELS = {
    "python": ("class AreaEntityState(", "class ServerEntityStateState("),
    "typescript": ("export interface AreaEntityState ", "export interface ServerEntityStateState "),
    "swift": ("public struct AreaEntityState:", "public struct ServerEntityStateState:"),
    "kotlin": ("data class AreaEntityState(", "data class ServerEntityStateState("),
}


def check_free_attributes(self: unittest.TestCase, output_of, lang: str) -> None:
    """A decoded and re-encoded relayed state keeps attributes the schema does not name."""
    out = output_of(FREE_ATTRIBUTES_FIXTURE)
    attrs = ((out or {}).get("state") or {}).get("attributes") or {}
    self.assertEqual(attrs.get("media_title"), "Abendlied", f"{lang}: attributes lost media_title: {attrs}")
    self.assertEqual(attrs.get("hub_picture_id"), "3fa1c09be27d4a65", f"{lang}: attributes lost hub_picture_id")


def schema_validator(schema: str):
    import validate as contracts_validate  # tools/validate.py

    return contracts_validate.validator_for(REPO / "schemas" / f"{schema}.json")


def leaf_validators(errors) -> set[str]:
    """Validators that failed, looking through anyOf/oneOf into the branches that are not a
    plain type mismatch (a nullable closed object fails as anyOf, its cause is the closed object)."""
    out: set[str] = set()
    for e in errors:
        if e.validator in ("anyOf", "oneOf") and e.context:
            branch = [c for c in e.context if c.validator != "type"]
            out |= leaf_validators(branch) if branch else {e.validator}
        else:
            out.add(e.validator)
    return out


class LanguageResults:
    """Shared checks for the result files written by the Swift and Kotlin harnesses."""

    def check_results(self: unittest.TestCase, results: dict, lang: str) -> None:
        ir = Fixtures.get_ir()
        check_free_attributes(self, lambda fx: results[fx]["output"], lang)
        self.assertEqual(set(results), {fx for fx, _, _ in Fixtures.all()}, f"{lang}: result set incomplete")
        for fx, schema, invalid in Fixtures.all():
            r = results[fx]
            with self.subTest(lang=lang, fixture=fx):
                if invalid:
                    if r["decoded"] and not r["violations"]:
                        # typed clients drop unknown keys while decoding, so they cannot see
                        # additionalProperties/unevaluatedProperties: false (README "Grenzen")
                        data = json.loads((REPO / fx).read_text())
                        kinds = leaf_validators(schema_validator(schema).iter_errors(data))
                        self.assertTrue(kinds and kinds <= CLOSED_OBJECT_VALIDATORS, f"{lang}: invalid fixture accepted: {fx}")
                    continue
                self.assertTrue(r["decoded"], f"{lang}: {fx}: {r.get('error')}")
                self.assertEqual(r["violations"], [], f"{lang}: {fx}")
                data = json.loads((REPO / fx).read_text())
                expected = Fixtures.expected(schema, data)
                self.assertTrue(json_equal(r["output"], expected), f"{lang}: {fx}\n got {r['output']}\nwant {expected}")
                errs = [e.message for e in schema_validator(schema).iter_errors(r["output"])]
                self.assertEqual(errs, [], f"{lang}: re-encoded {fx} violates the schema")
                if union_for(schema):
                    self.assertIsNone(r.get("unionError"), f"{lang}: {fx}: {r.get('unionError')}")
                    self.assertEqual(r["unionMember"], ir.registry[schema], f"{lang}: union picked the wrong member for {fx}")
                    self.assertTrue(json_equal(r["unionOutput"], expected), f"{lang}: union round trip of {fx}")


# ── generator ─────────────────────────────────────────────────────────────────


class GeneratorTests(unittest.TestCase):
    def test_deterministic(self):
        for lang in generate.LANGS:
            with self.subTest(lang=lang):
                self.assertEqual(generate.generate(lang, None), generate.generate(lang, None))

    def test_snapshots_up_to_date(self):
        for lang, d in LANG_DIRS.items():
            with self.subTest(lang=lang):
                rc = gen("--lang", lang, "--out", str(SNAPSHOTS / d), "--check")
                self.assertEqual(rc, 0, f"snapshot {d} stale: python tools/codegen/generate.py --lang {lang} --out tools/codegen/snapshots/{d}")

    def test_check_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(gen("--lang", "ts", "--out", str(out)), 0)
            self.assertEqual(gen("--lang", "ts", "--out", str(out), "--check"), 0)
            f = next(out.rglob("*.ts"))
            f.write_text(f.read_text() + "\n// edited\n")
            self.assertEqual(gen("--lang", "ts", "--out", str(out), "--check"), 1)
            (out / "obsolete.ts").write_text("// " + generate.MARKER + "\n")
            gen("--lang", "ts", "--out", str(out))
            self.assertFalse((out / "obsolete.ts").exists(), "obsolete generated file not removed")
            self.assertEqual(gen("--lang", "ts", "--out", str(out), "--check"), 0)

    def test_relayed_state_attributes_are_free(self):
        files = {"python": "python/hub_contracts/models.py", "typescript": "typescript/index.ts",
                 "swift": "swift/ContractModels.swift", "kotlin": "kotlin/hubcontracts/Models.kt"}
        for lang, rel in files.items():
            text = (SNAPSHOTS / rel).read_text()
            for start in FREE_ATTRIBUTE_MODELS[lang]:
                with self.subTest(lang=lang, model=start):
                    i = text.index(start)
                    nxt = {"python": "\nclass ", "typescript": "\nexport ", "swift": "\npublic struct ",
                           "kotlin": "\ndata class "}[lang]
                    end = text.find(nxt, i + len(start))
                    block = text[i:end if end > 0 else len(text)]
                    self.assertTrue(any(t in block for t in FREE_ATTRIBUTE_TYPES[lang]),
                                    f"{lang}: {start} attributes is no longer a free object")

    def test_namespace_literal_only_in_namespace_files(self):
        current = Fixtures.get_ir().namespace_current.lower()
        for lang in generate.LANGS:
            for rel, content in generate.generate(lang, None).items():
                with self.subTest(file=rel):
                    if rel in NAMESPACE_FILES:
                        self.assertIn(current, content)
                    else:
                        self.assertNotIn(current, content.lower(), f"{rel} contains the namespace literal")

    def test_unsupported_keyword_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "schemas", root / "schemas")
            shutil.copy(REPO / "namespace.json", root / "namespace.json")
            shutil.copy(REPO / "VERSION", root / "VERSION")
            (root / "schemas/rest/probe.json").write_text(json.dumps({
                "type": "object", "properties": {"x": {"oneOf": [{"type": "string"}, {"type": "integer"}]}},
            }))
            with self.assertRaises(SchemaError):
                build_ir(root)

    def test_kotlin_comments_do_not_nest(self):
        """Kotlin nests block comments: '/*' inside a KDoc opens a comment that swallows the rest of the file."""
        for rel, content in generate.generate("kotlin", None).items():
            depth = 0
            for no, line in enumerate(content.split("\n"), 1):
                if depth == 0 and line.lstrip().startswith("/**"):
                    body = line.lstrip()[3:]
                    depth = 1
                elif depth:
                    body = line
                else:
                    continue
                with self.subTest(file=rel, line=no):
                    end = body.find("*/")
                    self.assertNotIn("/*", body if end < 0 else body[:end], line)
                if end >= 0:
                    depth = 0

    def test_kotlin_enum_cases_do_not_shadow_types(self):
        from hubgen import emit_kotlin
        from hubgen.ir import EnumDef

        self.assertEqual(emit_kotlin.enum_case("string"), "StringValue")
        self.assertEqual(emit_kotlin.enum_case("list"), "ListValue")
        self.assertEqual(emit_kotlin.enum_case("unknown"), "UnknownValue")
        self.assertEqual(emit_kotlin.enum_case("integer"), "Integer")
        self.assertEqual(emit_kotlin.enum_case("mode", "Mode"), "ModeValue")
        self.assertEqual(emit_kotlin.kdoc("schemas/ws/server/* and */"), "schemas/ws/server/&#42; and *&#47;")
        for e in Fixtures.get_ir().ordered_enums():
            for v in e.values:
                with self.subTest(enum=e.name, value=v):
                    self.assertNotIn(emit_kotlin.enum_case(v, e.name), emit_kotlin.KOTLIN_RESERVED_CASES | {e.name})
        emitter = emit_kotlin.KotlinEmitter(Fixtures.get_ir(), "hubcontracts")
        with self.assertRaises(SchemaError):
            emitter.enum(EnumDef(name="Probe", location="probe", values=["string", "string_value"]))

    def test_every_fixture_schema_has_a_type(self):
        ir = Fixtures.get_ir()
        for _, schema, _ in Fixtures.all():
            self.assertIn(schema, ir.registry)


# ── Python ────────────────────────────────────────────────────────────────────


class PythonRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import pydantic  # noqa: F401
        except ImportError:
            skip_or_fail("pydantic is not installed")
        cls.tmp = tempfile.TemporaryDirectory()
        gen("--lang", "python", "--out", cls.tmp.name)
        sys.path.insert(0, cls.tmp.name)
        for mod in [m for m in sys.modules if m == "hub_contracts" or m.startswith("hub_contracts.")]:
            del sys.modules[mod]
        cls.hc = importlib.import_module("hub_contracts")

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(cls.tmp.name)
        cls.tmp.cleanup()

    def test_fixtures(self):
        from pydantic import ValidationError

        ir = Fixtures.get_ir()
        for fx, schema, invalid in Fixtures.all():
            data = json.loads((REPO / fx).read_text())
            with self.subTest(fixture=fx):
                try:
                    value = self.hc.parse(schema, data)
                except (ValidationError, ValueError) as exc:
                    self.assertTrue(invalid, f"{fx}: {exc}")
                    continue
                errors = value.contract_errors()
                if invalid:
                    self.assertTrue(errors, f"invalid fixture accepted: {fx}")
                    continue
                self.assertEqual(errors, [], fx)
                if fx == FREE_ATTRIBUTES_FIXTURE:
                    check_free_attributes(self, lambda _fx: value.to_dict(), "python")
                self.assertTrue(json_equal(value.to_dict(), data), f"{fx}\n got {value.to_dict()}\nwant {data}")
                self.assertEqual([e.message for e in schema_validator(schema).iter_errors(value.to_dict())], [])
                union = union_for(schema)
                if union:
                    msg = self.hc.parse(union, data)
                    self.assertEqual(type(msg).__name__, ir.registry[schema], f"union picked the wrong member for {fx}")
                    self.assertTrue(json_equal(msg.to_dict(), data))

    def test_data_constants(self):
        data_mod = importlib.import_module("hub_contracts.data")
        for f in sorted((REPO / "data").glob("*.json")):
            with self.subTest(data=f.name):
                const = f.stem.replace("-", "_")
                raw = json.loads(f.read_text())
                self.assertTrue(json_equal(json.loads(getattr(data_mod, const.upper() + "_JSON")), raw))
                value = getattr(data_mod, const)()
                self.assertEqual(value.contract_errors(), [])
                self.assertTrue(json_equal(value.to_dict(), raw))

    def test_unique_items(self):
        req = self.hc.parse("rest/area-entity-update.request", {"tile": {"hidden_on": ["tv", "tv"]}})
        self.assertTrue(any("unique" in e for e in req.contract_errors()))

    def test_tolerance(self):
        hc = self.hc
        m = hc.parse_server_message({"type": "future_thing", "x": 1})
        self.assertIsInstance(m, hc.UnknownMessage)
        self.assertEqual(m.to_dict(), {"type": "future_thing", "x": 1})
        self.assertIsInstance(hc.parse_server_message({"type": "command", "command": "teleport"}), hc.UnknownMessage)
        cmd = hc.CommandShowEntity.model_validate({"type": "command", "command": "show_entity", "entity_id": "light.a", "control_mode": "turbo"})
        self.assertEqual(cmd.control_mode, "turbo")
        self.assertEqual(len(cmd.contract_errors()), 1)
        known = hc.CommandShowEntity.model_validate({"type": "command", "command": "show_entity", "entity_id": "light.a", "control_mode": "full"})
        self.assertIs(known.control_mode, hc.ControlMode.FULL)
        err = hc.ServerError.model_validate({"type": "error", "message": "m", "later": True})
        self.assertEqual(err.to_dict(), {"type": "error", "message": "m", "later": True})

    def test_strict_types(self):
        from pydantic import ValidationError

        for bad in ({"type": "client_status", "battery_level": "80"}, {"type": "client_status", "battery_level": 80.5},
                    {"type": "client_status", "battery_level": True}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.hc.ClientStatus.model_validate(bad)

    def test_built_messages_carry_discriminators(self):
        hc = self.hc
        self.assertEqual(hc.ClientGetAreas().to_dict(), {"type": "get_areas"})
        self.assertEqual(hc.CommandRefresh().to_dict(), {"type": "command", "command": "refresh"})
        pv = {"protocol_version": 1, "min_protocol_version": 1, "min_app_version": hc.MinAppVersion(ios="2026.12.0")}
        auth = hc.ServerAuthOk(client_id="integration", **pv)
        self.assertEqual(auth.to_dict(), {"type": "auth_ok", "client_id": "integration", "protocol_version": 1,
                                          "min_protocol_version": 1, "min_app_version": {"ios": "2026.12.0"}})
        self.assertEqual(auth.contract_errors(), [])
        self.assertTrue(hc.ServerAuthOk(**pv).contract_errors(), "anyOf(client_id|message) must be enforced")

    def test_trailing_newline_does_not_match_anchored_pattern(self):
        p = self.hc.ClientPair.model_validate({"type": "pair", "pin": "1234-5678\n", "client_name": "x",
                                         "protocol_version": 1, "platform": "ios", "app_version": "2026.12.0"})
        self.assertEqual(len(p.contract_errors()), 1)

    def test_sensitive_fields_not_in_repr(self):
        ok = self.hc.ServerPairOk(client_id="c", client_name="n", secret="ab" * 32, protocol_version=1,
                                  min_protocol_version=1, min_app_version=self.hc.MinAppVersion())
        self.assertNotIn("abab", repr(ok))
        self.assertNotIn("abab", str(ok))

    def test_namespaced_key(self):
        hc = self.hc
        key = hc.namespace.AREA_SWITCH_ID_ATTRIBUTE
        a = hc.SensorAreaSwitchAttributes.model_validate({key: "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b"})
        self.assertEqual(a.area_switch_id_attribute, "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b")
        self.assertEqual(a.to_dict(), {key: "3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b"})


# ── Swift ─────────────────────────────────────────────────────────────────────


class SwiftRoundTrip(unittest.TestCase, LanguageResults):
    def test_swift(self):
        if os.environ.get("CODEGEN_SKIP_SWIFT") == "1":
            raise unittest.SkipTest("CODEGEN_SKIP_SWIFT=1")
        swift = shutil.which("swift")
        if not swift:
            skip_or_fail("swift toolchain not found")
        with tempfile.TemporaryDirectory(prefix="codegen-swift-") as tmp:
            pkg = Path(tmp) / "pkg"
            shutil.copytree(HERE / "swift", pkg)
            gen("--lang", "swift", "--out", str(pkg / "Sources" / "HubModels"))
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps(Fixtures.manifest()))
            out = Path(tmp) / "results.json"
            env = {**os.environ, "ROUNDTRIP_MANIFEST": str(manifest), "ROUNDTRIP_OUT": str(out), "CONTRACTS_ROOT": str(REPO)}
            proc = subprocess.run(
                [swift, "test", "--package-path", str(pkg), "--scratch-path", str(Path(tmp) / "build")],
                env=env, capture_output=True, text=True, timeout=1800,
            )
            if proc.returncode != 0:
                self.fail(f"swift test failed:\n{proc.stdout[-6000:]}\n{proc.stderr[-4000:]}")
            self.check_results(json.loads(out.read_text()), "swift")


# ── Kotlin ────────────────────────────────────────────────────────────────────


class KotlinRoundTrip(unittest.TestCase, LanguageResults):
    def test_kotlin(self):
        """Compiles the checked-in Kotlin snapshot (equal to the generator output, see test_snapshots_up_to_date)
        with the Kotlin Gradle plugin and the versions of the Android consumer, then runs the harness."""
        if os.environ.get("CODEGEN_SKIP_KOTLIN") == "1":
            raise unittest.SkipTest("CODEGEN_SKIP_KOTLIN=1")
        gradle = os.environ.get("GRADLE") or shutil.which("gradle")
        if not gradle:
            skip_or_fail("gradle not available (set GRADLE or put gradle on PATH)")
        with tempfile.TemporaryDirectory(prefix="codegen-kotlin-") as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps(Fixtures.manifest()))
            out = Path(tmp) / "results.json"
            proc = subprocess.run(
                [gradle, "-p", str(CODEGEN / "kotlin-check"), "--console=plain", "--warning-mode=fail", "--no-problems-report",
                 "--project-cache-dir", str(Path(tmp) / "gradle-project"),
                 f"-PbuildRoot={Path(tmp) / 'build'}", f"-Pkotlin.project.persistent.dir={Path(tmp) / 'kotlin'}",
                 f"-PgeneratedDir={SNAPSHOTS / 'kotlin'}", f"-PcontractsRoot={REPO}",
                 f"-Pmanifest={manifest}", f"-Presults={out}", "roundTrip"],
                capture_output=True, text=True, timeout=1800,
            )
            if proc.returncode != 0:
                self.fail(f"gradle roundTrip failed:\n{proc.stdout[-8000:]}\n{proc.stderr[-6000:]}")
            self.check_results(json.loads(out.read_text()), "kotlin")


# ── TypeScript ────────────────────────────────────────────────────────────────


class TypeScriptCheck(unittest.TestCase):
    def test_typecheck(self):
        if os.environ.get("CODEGEN_SKIP_TS") == "1":
            raise unittest.SkipTest("CODEGEN_SKIP_TS=1")
        tsc = os.environ.get("TSC")
        cmd = [tsc] if tsc else None
        if cmd is None and shutil.which("npx"):
            cmd = [shutil.which("npx"), "--yes", "-p", "typescript@5.9.3", "tsc"]
        if cmd is None:
            skip_or_fail("tsc / npx not available")
        ir = Fixtures.get_ir()
        with tempfile.TemporaryDirectory(prefix="codegen-ts-") as tmp:
            out = Path(tmp)
            gen("--lang", "ts", "--out", str(out))
            lines = ['import type * as C from "./index";', ""]
            for i, (fx, schema, invalid) in enumerate(Fixtures.all()):
                if invalid:
                    continue
                name = ir.registry[schema]
                lines.append(f"// {fx}")
                literal = json.dumps(Fixtures.expected(schema, json.loads((REPO / fx).read_text())), ensure_ascii=False)
                lines.append(f"export const f{i}: C.{name} = {literal};")
                if union_for(schema):
                    union = "ClientMessage" if union_for(schema) == "ws/client-message" else "ServerMessage"
                    lines.append(f"export const u{i}: C.{union} = f{i};")
            # type errors the TS types must catch
            lines += [
                "// @ts-expect-error tls_port must be a number (known deviation D3)",
                'export const bad1: C.ClientConfig["tls_port"] = "8100";',
                "// @ts-expect-error status is not allowed in display_notification",
                'export const bad2: C.CommandDisplayNotification["status"] = "pending";',
                "// relayed state attributes stay a free object (media_title survives)",
                'export const freeAttrs: C.ServerEntityStateState["attributes"] = {media_title: "Abendlied", hub_picture_id: "3fa1c09be27d4a65"};',
                'export const freeAttrTitle: unknown = freeAttrs?.["media_title"];',
                "// @ts-expect-error unknown guest_url_mode",
                'export const bad3: C.IntegrationStartPairingRequest["guest_url_mode"] = "remote";',
            ]
            (out / "fixtures.check.ts").write_text("\n".join(lines) + "\n")
            proc = subprocess.run(
                cmd + ["--noEmit", "--strict", "--exactOptionalPropertyTypes", "--target", "es2022", "--module", "es2022",
                       "--moduleResolution", "bundler", "--resolveJsonModule", str(out / "index.ts"), str(out / "fixtures.check.ts")],
                capture_output=True, text=True, timeout=600, cwd=tmp,
            )
            if proc.returncode != 0:
                self.fail(f"tsc failed:\n{proc.stdout[-6000:]}\n{proc.stderr[-2000:]}")


if __name__ == "__main__":
    unittest.main()
