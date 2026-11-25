"""Checks of the GitHub Actions workflows (python -m unittest discover -s tools -p "test_workflows.py").

Every job runs on a GitHub-hosted runner, every needs and steps reference resolves, every action
from another repository is pinned by a full commit SHA, and the top-level permissions are set and
not write-all. Needs PyYAML (tools/requirements.txt).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
PUBLIC = REPO / ".github" / "public" / "workflows"
WORKFLOWS = PUBLIC if PUBLIC.is_dir() else REPO / ".github" / "workflows"

HOSTED_RE = re.compile(r"^(ubuntu|macos|windows)-[0-9a-z.-]+$")
PINNED_RE = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
STEPS_REF_RE = re.compile(r"\bsteps\.([A-Za-z_][\w-]*)")
NEEDS_REF_RE = re.compile(r"\bneeds\.([A-Za-z_][\w-]*)")


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 reads the key "on" as True.
    if True in data:
        data["on"] = data.pop(True)
    return data


def as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def strings(node):
    """Every string in a YAML node."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


class Workflows(unittest.TestCase):
    def setUp(self):
        self.files = sorted(WORKFLOWS.glob("*.y*ml"))
        self.assertTrue(self.files, f"no workflows in {WORKFLOWS}")

    def each_job(self):
        for path in self.files:
            wf = load(path)
            for name, job in wf.get("jobs", {}).items():
                yield path.name, wf, name, job

    def test_top_level_permissions(self):
        for path in self.files:
            wf = load(path)
            with self.subTest(workflow=path.name):
                self.assertIn("permissions", wf)
                self.assertNotEqual(wf["permissions"], "write-all")

    def test_hosted_runners(self):
        for wf_name, _, name, job in self.each_job():
            if "uses" in job:  # reusable workflow: runs where that workflow says
                continue
            with self.subTest(workflow=wf_name, job=name):
                runs_on = job.get("runs-on")
                self.assertIsInstance(runs_on, str, "runs-on must be one GitHub-hosted label")
                self.assertRegex(runs_on, HOSTED_RE)

    def test_needs_resolve(self):
        for wf_name, wf, name, job in self.each_job():
            needs = as_list(job.get("needs"))
            with self.subTest(workflow=wf_name, job=name):
                for need in needs:
                    self.assertIn(need, wf["jobs"], f"needs: {need}")
                for ref in NEEDS_REF_RE.findall(" ".join(strings({k: v for k, v in job.items() if k != "needs"}))):
                    self.assertIn(ref, needs, f"needs.{ref} without needs: {ref}")

    def test_step_references_resolve(self):
        for wf_name, _, name, job in self.each_job():
            ids = {s["id"] for s in job.get("steps", []) if "id" in s}
            with self.subTest(workflow=wf_name, job=name):
                for ref in STEPS_REF_RE.findall(" ".join(strings(job))):
                    self.assertIn(ref, ids, f"steps.{ref}")

    def test_actions_pinned_and_local_paths_exist(self):
        for wf_name, _, name, job in self.each_job():
            uses = [job["uses"]] if "uses" in job else [s["uses"] for s in job.get("steps", []) if "uses" in s]
            for use in uses:
                with self.subTest(workflow=wf_name, job=name, uses=use):
                    if use.startswith("./"):
                        target = REPO / use.split("@", 1)[0]
                        if target.suffix in (".yml", ".yaml"):
                            # Reusable workflow next to this one.
                            self.assertTrue((WORKFLOWS / target.name).is_file(), use)
                        else:
                            self.assertTrue((target / "action.yml").is_file() or (target / "action.yaml").is_file(), use)
                    elif not use.startswith("docker://"):
                        self.assertRegex(use, PINNED_RE)


if __name__ == "__main__":
    unittest.main()
