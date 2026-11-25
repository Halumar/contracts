"""Tests for publiclint (python -m unittest discover -s tools/publiclint -p "test_*.py")."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publiclint as pl  # noqa: E402

# Trigger strings are assembled so that this file stays clean for other scanners.
TICKET = "ABC" + "-12"
HAS_GIT = shutil.which("git") is not None


def make_repo(tmp: str, files: dict[str, str], config: str | None = None, git: bool = True) -> Path:
    repo = Path(tmp)
    if git:
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    if config is not None:
        (repo / pl.CONFIG_NAME).write_text(config, encoding="utf-8")
    if git:
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def lint_files(files: dict[str, str], config: str | None = None, git: bool = HAS_GIT,
               packs: list[str] | None = None) -> list[pl.Finding]:
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as packdir:
        repo = make_repo(tmp, files, config, git)
        pack_files = []
        for i, text in enumerate(packs or []):
            pack_files.append(Path(packdir) / f"pack{i}.toml")
            pack_files[-1].write_text(text, encoding="utf-8")
        return pl.lint_repo(repo, pl.load_config(repo / pl.CONFIG_NAME, packs=pack_files))


PACK = """
[[rule]]
id = "XY001"
name = "codename"
help = "the feature name"
pattern = '\\bproject acme\\b'
ignore_case = true

[[rule]]
id = "XY002"
name = "french-comment"
scope = "comment"
words = ["le", "la", "les", "est", "pas", "pour", "avec"]
other_words = ["the", "is", "for", "with"]

[[rule]]
id = "XY003"
name = "draft-file"
scope = "filename"
pattern = '(?i)^draft[-_]'
"""


class Rules(unittest.TestCase):
    def rules(self, line: str) -> list[str]:
        return [r for r, _ in pl.scan_line(line, pl.Config())]

    def test_ticket_reference(self):
        self.assertEqual(self.rules(f"# see ({TICKET})"), ["PL001"])

    def test_standards_are_not_tickets(self):
        self.assertEqual(self.rules("SHA-256, ISO-8601, RFC-5737, CVE-2024-1234, P-256, UTF-8"), [])

    def test_versions_and_fields_are_fine(self):
        self.assertEqual(self.rules('"version": "1.1.0-rc.1", "panel_remote": true'), [])

    def test_local_path(self):
        self.assertEqual(self.rules("/" + "Users/someone/dev"), ["PL006"])
        self.assertEqual(self.rules("tools/validate.py"), [])

    def test_secret_and_fingerprint(self):
        self.assertEqual(self.rules("token gh" + "p_" + "a" * 36), ["PL013"])
        self.assertEqual(self.rules(":".join(["AB"] * 16)), ["PL014"])

    def test_email(self):
        self.assertEqual(self.rules("someone@" + "mail-provider.net"), ["PL015"])
        own = pl._brand_domains()
        self.assertTrue(own)
        self.assertEqual(self.rules(f"admin@example.com, x@{own[0]}"), [])

    def test_only_generic_rules_are_built_in(self):
        self.assertEqual(sorted(pl.BUILTIN_RULES), ["PL001", "PL006", "PL011", "PL013", "PL014", "PL015"])


class Repo(unittest.TestCase):
    def test_comment_and_allow_list(self):
        files = {
            "a.py": f"x = 1  # see {TICKET}\n",
            "b.py": "# Ünïcode " + "\U0001F600" + "\n",
        }
        self.assertEqual(sorted(f.rule for f in lint_files(files)), ["PL001", "PL011"])
        config = '[[allow]]\nrule = "PL011"\npath = "b.py"\nreason = "test string"\n'
        self.assertEqual([f.rule for f in lint_files(files, config)], ["PL001"])

    def test_allow_entry_needs_reason(self):
        with self.assertRaises(ValueError):
            lint_files({"a.py": "x = 1\n"}, '[[allow]]\nrule = "PL001"\npath = "a.py"\n')

    def test_tool_folder_is_excluded(self):
        self.assertEqual(lint_files({"tools/publiclint/x.py": f"# {TICKET}\n"}), [])

    def test_folder_without_git_is_walked(self):
        files = {"docs/a.md": f"see {TICKET}\n", ".venv/lib/x.py": f"# {TICKET}\n"}
        found = lint_files(files, git=False)
        self.assertEqual([(f.path, f.rule) for f in found], [("docs/a.md", "PL001")])

    def test_ticket_pattern_is_configurable(self):
        config = "ticket_pattern = '(?<![\\w-])(TASK)-(\\d+)'\n"
        task = "TASK" + "-7"
        found = lint_files({"a.md": f"{task} and {TICKET}\n"}, config)
        self.assertEqual([f.match for f in found], [task])


class Packs(unittest.TestCase):
    def test_pack_rules_by_scope(self):
        files = {
            "a.md": "Built for Project Acme.\n",
            "b.py": "x = 1  # le code est pour la maison avec les enfants\n",
            "tests/draft-login.py": "x = 2\n",
        }
        self.assertEqual(lint_files(files), [])
        found = lint_files(files, packs=[PACK])
        self.assertEqual(sorted((f.path, f.rule, f.name) for f in found), [
            ("a.md", "XY001", "codename"),
            ("b.py", "XY002", "french-comment"),
            ("tests/draft-login.py", "XY003", "draft-file"),
        ])

    def test_words_rule_ignores_english_comments(self):
        found = lint_files({"b.py": "# the value is used for the house with the children\n"}, packs=[PACK])
        self.assertEqual(found, [])

    def test_pack_from_environment(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as packdir:
            repo = make_repo(tmp, {"a.md": "Project Acme\n"}, git=HAS_GIT)
            pack = Path(packdir) / "private.toml"
            pack.write_text(PACK, encoding="utf-8")
            out = io.StringIO()
            with mock.patch.dict(os.environ, {pl.PACK_ENV: str(pack)}), redirect_stdout(out):
                rc = pl.main([str(repo), "--format", "summary"])
            self.assertEqual(rc, 1)
            self.assertIn("XY001 codename 1", out.getvalue())
            with mock.patch.dict(os.environ, {pl.PACK_ENV: ""}), redirect_stdout(io.StringIO()):
                self.assertEqual(pl.main([str(repo), "--format", "summary"]), 0)

    def test_pack_from_flag_and_rule_selection(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as packdir:
            repo = make_repo(tmp, {"a.md": f"Project Acme, {TICKET}\n"}, git=HAS_GIT)
            pack = Path(packdir) / "private.toml"
            pack.write_text(PACK, encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pl.main([str(repo), "--pack", str(pack), "--rules", "XY001"]), 1)
                self.assertEqual(pl.main([str(repo), "--rules", "PL006"]), 0)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(pl.main([str(repo), "--rules", "XY001"]), 2)
                self.assertEqual(pl.main([str(repo), "--pack", str(Path(packdir) / "missing.toml")]), 2)

    def test_pack_rule_ids_are_unique(self):
        dup = '[[rule]]\nid = "PL006"\nname = "again"\npattern = "x"\n'
        with self.assertRaises(ValueError):
            lint_files({"a.md": "x\n"}, packs=[dup])


if __name__ == "__main__":
    unittest.main()
