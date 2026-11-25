#!/usr/bin/env python3
"""brandlint – keep the brand out of the code.

Rules
  BL001  forbidden name (configurable: forbidden_patterns) outside forbidden_allowed
  BL002  brand literal "Halumar" outside brand/generated files
  BL003  namespace literal "halumar" outside the namespace constants files
  BL004  forbidden name (configurable: forbidden_patterns) in a file or folder path

Usage
  brandlint.py [REPO ...] [--config FILE] [--format text|summary|json] [--max N]

Each REPO is scanned with its own `.brandlint.toml` (merged onto
default.brandlint.toml). Git repos are listed with `git ls-files`, other
folders are walked. Read-only. Exit code 1 if anything was found, 0 if clean,
2 on usage/config errors.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import srclex  # noqa: E402

DEFAULT_CONFIG = HERE / "default.brandlint.toml"
LIST_KEYS = ("forbidden_patterns", "exclude", "forbidden_allowed", "brand_allowed", "namespace_allowed",
             "allow_line_patterns")


@dataclass
class Finding:
    repo: str
    path: str
    line: int
    col: int
    rule: str
    match: str
    text: str

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: {self.rule} {self.match!r}  | {self.text.strip()[:140]}"


def load_config(repo: Path, explicit: Path | None = None) -> dict:
    with open(DEFAULT_CONFIG, "rb") as fh:
        cfg = tomllib.load(fh)
    override = explicit or (repo / ".brandlint.toml")
    if override and override.exists():
        with open(override, "rb") as fh:
            extra = tomllib.load(fh)
        replace = extra.pop("replace_lists", False)
        for key, value in extra.items():
            if key in LIST_KEYS and not replace:
                cfg[key] = list(cfg.get(key, [])) + list(value)
            else:
                cfg[key] = value
    return cfg


def glob_match(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatchcase(path, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatchcase(path, pat[3:]):
            return True
    return False


def list_files(repo: Path, cfg: dict) -> list[str]:
    files: list[str] = []
    if (repo / ".git").exists():
        res = subprocess.run(["git", "-C", str(repo), "ls-files", "-co", "--exclude-standard", "-z"],
                             capture_output=True, check=True)
        files = [f for f in res.stdout.decode().split("\0") if f]
    else:
        for root, dirs, names in os.walk(repo):
            rel_root = os.path.relpath(root, repo)
            rel_root = "" if rel_root == "." else rel_root.replace(os.sep, "/") + "/"
            dirs[:] = [d for d in dirs if not glob_match(rel_root + d + "/x", cfg["exclude"])]
            files += [rel_root + n for n in names]
    return sorted(f for f in files if not glob_match(f, cfg["exclude"]) and (repo / f).is_file())


def _line_col(text: str, offset: int, line_starts: list[int]) -> tuple[int, int]:
    import bisect
    i = bisect.bisect_right(line_starts, offset) - 1
    return i + 1, offset - line_starts[i] + 1


def lint_text(rel: str, text: str, cfg: dict, repo_name: str = "") -> list[Finding]:
    forbidden_ok = glob_match(rel, cfg["forbidden_allowed"])
    brand_ok = glob_match(rel, cfg["brand_allowed"])
    ns_ok = glob_match(rel, cfg["namespace_allowed"])
    if forbidden_ok and brand_ok and ns_ok:
        return []
    segs = srclex.segments(text, srclex.language_for(rel))
    line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
    lines = text.split("\n")
    pragma = cfg.get("inline_pragma") or None
    allow_lines = [re.compile(p) for p in cfg.get("allow_line_patterns", [])]
    out: list[Finding] = []

    def add(rule: str, m: re.Match, allow_in_comment: bool) -> None:
        ln, col = _line_col(text, m.start(), line_starts)
        line = lines[ln - 1]
        if pragma and pragma in line:
            return
        if any(p.search(line) for p in allow_lines):
            return
        if allow_in_comment and srclex.kind_at(segs, m.start()) == srclex.COMMENT:
            return
        out.append(Finding(repo_name, rel, ln, col, rule, m.group(0), line))

    if not forbidden_ok:
        for pat in cfg["forbidden_patterns"]:
            for m in re.finditer(pat, text):
                add("BL001", m, cfg.get("allow_forbidden_in_comments", False))
    brand = cfg["brand_name"]
    ns = cfg["namespace"]
    if not (brand_ok and ns_ok):
        for m in re.finditer(re.escape(ns), text, re.IGNORECASE):
            if m.group(0) == brand:
                if not brand_ok:
                    add("BL002", m, cfg.get("allow_brand_in_comments", True))
            elif not ns_ok:
                add("BL003", m, cfg.get("allow_namespace_in_comments", True))
    # de-duplicate overlapping patterns on the same spot
    seen: set[tuple] = set()
    uniq = []
    for f in sorted(out, key=lambda f: (f.line, f.col, f.rule)):
        key = (f.line, f.col, f.rule)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def lint_repo(repo: Path, cfg: dict) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    files = list_files(repo, cfg)
    name = repo.name
    for rel in files:
        if cfg.get("check_paths", True) and not glob_match(rel, cfg["forbidden_allowed"]):
            for pat in cfg["forbidden_patterns"]:
                m = re.search(pat, rel)
                if m:
                    findings.append(Finding(name, rel, 0, 0, "BL004", m.group(0), rel))
                    break
        try:
            raw = (repo / rel).read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        text = raw.decode("utf-8", errors="replace")
        findings += lint_text(rel, text, cfg, name)
    return findings, len(files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Brand lint")
    ap.add_argument("repos", nargs="*", type=Path, default=[Path(".")])
    ap.add_argument("--config", type=Path, help="config file instead of <repo>/.brandlint.toml")
    ap.add_argument("--format", choices=("text", "summary", "json"), default="text")
    ap.add_argument("--max", type=int, default=0, help="print at most N findings per repo (text)")
    args = ap.parse_args(argv)

    total = 0
    report = []
    for repo in args.repos:
        if not repo.is_dir():
            print(f"brandlint: not a directory: {repo}", file=sys.stderr)
            return 2
        try:
            cfg = load_config(repo, args.config)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            print(f"brandlint: config error: {exc}", file=sys.stderr)
            return 2
        findings, nfiles = lint_repo(repo, cfg)
        total += len(findings)
        by_rule = Counter(f.rule for f in findings)
        by_file = Counter(f.path for f in findings)
        report.append({"repo": str(repo), "files_scanned": nfiles, "findings": len(findings),
                       "by_rule": dict(sorted(by_rule.items())), "files_with_findings": len(by_file),
                       "items": [asdict(f) for f in findings]})
        if args.format == "text":
            shown = findings[: args.max] if args.max else findings
            for f in shown:
                print(f"{repo.name}/{f.format()}" if len(args.repos) > 1 else f.format())
            if args.max and len(findings) > args.max:
                print(f"… {len(findings) - args.max} more")
        elif args.format == "summary":
            rules = " ".join(f"{k}={v}" for k, v in sorted(by_rule.items())) or "clean"
            print(f"{repo.name}: {len(findings)} findings in {len(by_file)} of {nfiles} files ({rules})")
    if args.format == "json":
        for r in report:
            r.pop("items") if os.environ.get("BRANDLINT_JSON_BRIEF") else None
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
