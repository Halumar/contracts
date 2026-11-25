"""Tests for brandlint and brandgen (python -m unittest discover -s tools/brand -p "test_*.py")."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brandgen  # noqa: E402
import brandlint  # noqa: E402

REPO = HERE.parent.parent


def lint(files: dict[str, str], config: str | None = None) -> list[brandlint.Finding]:
    """Lint a folder without git (walked), with an optional .brandlint.toml."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8")
        if config is not None:
            (repo / ".brandlint.toml").write_text(config, encoding="utf-8")
        findings, _ = brandlint.lint_repo(repo, brandlint.load_config(repo))
        return findings


class ForbiddenNames(unittest.TestCase):
    def test_default_has_no_forbidden_names(self):
        cfg = brandlint.load_config(Path("/nonexistent"))
        self.assertEqual(cfg["forbidden_patterns"], [])
        self.assertEqual(lint({"acme_client.py": "name = 'Acme Home'\n"}), [])

    def test_configured_pattern_in_text_and_path(self):
        config = "forbidden_patterns = ['(?i)acme']\n"
        found = lint({"src/acme_client.py": "title = 'Acme Home'\n", "ok.py": "x = 1\n"}, config)
        self.assertEqual(sorted((f.rule, f.path) for f in found),
                         [("BL001", "src/acme_client.py"), ("BL004", "src/acme_client.py")])

    def test_configured_pattern_allowed_path(self):
        config = "forbidden_patterns = ['(?i)acme']\nforbidden_allowed = ['docs/**']\n"
        self.assertEqual(lint({"docs/history.md": "Acme\n"}, config), [])

    def test_brand_and_namespace_literals(self):
        found = lint({"app.py": "a = 'Halumar'\nb = 'halumar'\n"})
        self.assertEqual(sorted(f.rule for f in found), ["BL002", "BL003"])


class GeneratedHeaders(unittest.TestCase):
    def test_generated_files_carry_the_display_brand_note(self):
        brand = brandgen.load_brand(REPO / "brand.json")
        note = "Display brand. Never use these values as technical identifiers."
        rendered = brandgen.render_all(brand)
        for key in ("swift/Brand.swift", "python/brand.py", "ts/brand.ts"):
            self.assertIn(note, rendered[key], key)

    def test_brand_json_has_no_placeholders(self):
        brand = brandgen.load_brand(REPO / "brand.json")
        self.assertFalse(brand.get("placeholders"))


if __name__ == "__main__":
    unittest.main()
