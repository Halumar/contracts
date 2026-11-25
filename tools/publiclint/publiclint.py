#!/usr/bin/env python3
"""publiclint – find ticket references, local paths, secrets and emoji in text meant for the public.

Rules
  PL001  ticket-style reference: an upper-case word, a hyphen and a number that is not a
         standard (SHA-256, ISO-8601, RFC and CVE numbers, …); the pattern is configurable
  PL006  local paths (/Users/<name>, macOS temporary folders, C:\\Users\\<name>)
  PL011  emoji in code
  PL013  secrets: private key blocks, GitHub/AWS/Google/Slack tokens, JWTs
  PL014  certificate fingerprints written as colon hex (16 bytes or more)
  PL015  e-mail addresses outside example/test domains and the project's own domains
         (host names of the URLs in brand.json)

More rules come from rule packs: TOML files in the format of the configuration below, given
with --pack FILE (repeatable) or in the environment variable PUBLICLINT_PACK (several paths
separated by the platform's path separator).

Usage
  publiclint.py [REPO] [--config FILE] [--pack FILE] [--format text|summary|json]
                [--rules PL001,PL006]

REPO defaults to the current directory. In a git checkout the files come from `git ls-files`;
anywhere else (an unpacked archive, for example) the folder is walked. The configuration is
`.public-lint.toml` in the repository root (or --config):

  exclude = ["docs/archive/**"]           # globs on the repo-relative path
  legit_id_prefixes = ["ABC"]              # prefixes that are standards, not tickets
  ticket_pattern = '...'                   # regex for PL001: group 1 prefix, group 2 number

  [[allow]]
  rule = "PL011"                 # rule id or "*"
  path = "tests/test_x.py"       # glob on the repo-relative path ("**/" prefix allowed)
  line = "regex"                 # optional: regex on the whole line
  match = "regex"                # optional: regex on the finding
  reason = "why this is fine"

  [[rule]]
  id = "XY001"                   # unique rule id
  name = "short-name"
  help = "what to write instead" # optional
  scope = "line"                 # line (default): every line of every text file
                                 # comment: comments in code files
                                 # filename: the file's base name
  pattern = "regex"
  ignore_case = false            # optional

A rule with scope "comment" may give a word list instead of a pattern: it reports a comment
line with at least `min_words` (default 3) of `words` and more of them than of `other_words`;
with one of `marker_chars` in the line, `min_words` - 1 are enough.

Exit code 1 if anything was found, 0 if clean, 2 on errors. Standard library only.
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
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brand"))
import srclex  # noqa: E402

CONFIG_NAME = ".public-lint.toml"
PACK_ENV = "PUBLICLINT_PACK"
MAX_BYTES = 1_500_000

BUILTIN_RULES = {
    "PL001": "ticket-reference",
    "PL006": "local-path",
    "PL011": "emoji",
    "PL013": "secret",
    "PL014": "fingerprint",
    "PL015": "email",
}

DEFAULT_EXCLUDE = [
    "**/package-lock.json", "package-lock.json", "**/*.min.js", "**/*.map",
    "**/rootfs/opt/hub/static/**", "**/docs_assets/**", "**/.coverage",
    "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.webp", "**/*.gif", "**/*.ico", "**/*.icns",
    "**/*.pdf", "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.otf", "**/*.car", "**/*.zip",
    "**/*.xcresult/**",
    # This tool spells the patterns it looks for.
    "tools/publiclint/**",
]

# Folders skipped when the repository is walked instead of listed with git.
WALK_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".gradle", ".build", "build", "DerivedData", ".idea", ".vscode",
}

# Prefixes of ticket-like tokens that are standards, not ticket references.
LEGIT_ID_PREFIXES = {
    "SHA", "AGPL", "GPL", "LGPL", "MPL", "BSD", "MIT", "PSF", "LICENSE", "APACHE", "UTF", "UCS",
    "ISO", "IEC", "ECMA", "AES", "RSA", "TLS", "SSL", "DTLS", "RFC", "CVE", "CWE", "X", "HTTP",
    "IPV", "CC", "CC-BY", "CC-BY-SA", "CC0", "ED", "CP", "WINDOWS", "ARM", "IEEE", "ITU", "LATIN",
    "KOI", "BASE", "CRC", "MD", "HS", "ES", "PS", "RS", "EC", "ECDSA", "AES-GCM", "CHACHA",
    "GHSA", "WCAG", "EN", "DIN", "BS", "ZLIB", "OFL", "UNLICENSE", "PYTHON", "NODE", "ES2015",
    "ARGON", "PBKDF", "HKDF", "HMAC-SHA", "TOTP", "OWASP", "MASVS-AUTH", "ASVS", "PEP",
    "SF", "M", "H", "W", "WPA", "IP", "TCP", "UDP", "TV", "HDMI", "USB", "BLAKE",
}
TICKET_PATTERN = r"(?<![\w./#-])([A-Z][0-9A-Z]*(?:-[0-9A-Z]+)*)-(\d+)[a-z]?(?![\w])"
P_CURVES = {"256", "384", "521"}

# Patterns are written so that this file does not match itself (character classes).
LOCAL_PATH_RE = re.compile(
    r"(?<![\w.~-])/User[s]/[A-Za-z0-9._-]+|(?<![\w.~-])/privat[e]/var/\S*|(?<![\w.~-])/var/folder[s]/\S*|"
    r"C:\\User[s]\\\w+")
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFF]|[\u2600-\u26FF]|"
    "[\u2700-\u2712\u2719-\u27BF]|[\u2B50\u2B55\u2B1B\u2B1C]|\uFE0F|\u200D(?=[\U0001F000-\U0001FAFF])")
SECRET_RE = re.compile(
    r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{35}\b|\bxox[abprs]-[A-Za-z0-9-]{10,}|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
FINGERPRINT_RE = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}:){15,}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
EMAIL_RE = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@((?:[A-Za-z0-9-]+\.)+([A-Za-z]{2,}))(?![\w-])")
BRAND_FILE = Path(__file__).resolve().parent.parent.parent / "brand.json"


def _brand_domains() -> list[str]:
    """Host names of the brand URLs (brand.json): the project's own e-mail domains."""
    try:
        urls = json.loads(BRAND_FILE.read_text(encoding="utf-8")).get("urls", {})
    except (OSError, ValueError):
        return []
    hosts = {re.sub(r"^https?://([^/]+).*$", r"\1", u).lower() for u in urls.values() if isinstance(u, str)}
    return sorted(h for h in hosts if h and h != "github.com")


EMAIL_OK_DOMAIN_RE = re.compile(
    r"(?:^|\.)(?:example\.(?:com|org|net)|example|test|invalid|localhost|local\.host|"
    r"users\.noreply\.github\.com" + "".join("|" + re.escape(d) for d in _brand_domains()) + r")$", re.I)
FILE_EXT_TLDS = {"png", "jpg", "jpeg", "webp", "gif", "svg", "pdf", "js", "mjs", "ts", "py", "json", "md",
                 "css", "html", "svelte", "swift", "kt", "txt", "yaml", "yml", "toml", "sh", "map", "ico"}
WORD_RE = re.compile(r"[^\W\d_]+(?:\.[^\W\d_]+)*\.?")
CODE_LANGS = {"python", "swift", "clike", "markup", "hash", "pbxproj"}
RULE_ID_RE = re.compile(r"^[A-Z]{2,}\d{3}$")
SCOPES = ("line", "comment", "filename")


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    name: str
    match: str
    text: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.rule} {self.name} {self.match!r}  | {self.text.strip()[:140]}"


@dataclass
class AllowEntry:
    rule: str = "*"
    path: str = "*"
    match: str | None = None
    line: str | None = None
    reason: str = ""

    def allows(self, f: Finding) -> bool:
        if self.rule not in ("*", f.rule) or not _glob(f.path, self.path):
            return False
        if self.match and not re.search(self.match, f.match):
            return False
        return not (self.line and not re.search(self.line, f.text))


@dataclass
class PackRule:
    """A rule from a rule pack or the repository configuration."""
    id: str
    name: str
    scope: str = "line"
    pattern: re.Pattern | None = None
    words: frozenset[str] = frozenset()
    other_words: frozenset[str] = frozenset()
    min_words: int = 3
    marker_chars: str = ""
    help: str = ""

    def search_line(self, text: str) -> list[str]:
        if self.pattern is not None:
            return [m.group(0) for m in self.pattern.finditer(text) if m.group(0)]
        return [text.strip()[:40]] if self._words_match(text) else []

    def _words_match(self, text: str) -> bool:
        words = [w.lower().strip(".") for w in WORD_RE.findall(text)]
        if len(words) < 3:
            return False
        hits = sum(1 for w in words if w in self.words)
        other = sum(1 for w in words if w in self.other_words)
        if hits >= self.min_words and hits > other:
            return True
        marked = bool(self.marker_chars) and any(c in text for c in self.marker_chars)
        return marked and hits >= self.min_words - 1 and hits >= other


@dataclass
class Config:
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    allow: list[AllowEntry] = field(default_factory=list)
    legit_prefixes: set[str] = field(default_factory=lambda: set(LEGIT_ID_PREFIXES))
    ticket_re: re.Pattern = field(default_factory=lambda: re.compile(TICKET_PATTERN))
    pack_rules: list[PackRule] = field(default_factory=list)
    rules: set[str] = field(default_factory=lambda: set(BUILTIN_RULES))

    @property
    def names(self) -> dict[str, str]:
        return {**BUILTIN_RULES, **{r.id: r.name for r in self.pack_rules}}


def _glob(path: str, pattern: str) -> bool:
    if pattern in ("*", "**") or fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


TOP_KEYS = {"exclude", "legit_id_prefixes", "ticket_pattern", "allow", "rule"}
ALLOW_KEYS = {"rule", "path", "match", "line", "reason", "repo"}
RULE_KEYS = {"id", "name", "help", "scope", "pattern", "ignore_case", "words", "other_words",
             "min_words", "marker_chars"}


def _parse_rule(path: Path, entry: dict) -> PackRule:
    unknown = set(entry) - RULE_KEYS
    if unknown:
        raise ValueError(f"{path}: unknown rule keys {sorted(unknown)}")
    rid, name = entry.get("id", ""), entry.get("name", "")
    if not RULE_ID_RE.match(rid) or not name:
        raise ValueError(f"{path}: every rule needs an id like XY001 and a name ({entry})")
    scope = entry.get("scope", "line")
    if scope not in SCOPES:
        raise ValueError(f"{path}: rule {rid}: scope must be one of {SCOPES}")
    rule = PackRule(id=rid, name=name, scope=scope, help=entry.get("help", ""))
    if "pattern" in entry:
        rule.pattern = re.compile(entry["pattern"], re.I if entry.get("ignore_case") else 0)
    elif "words" in entry and scope == "comment":
        rule.words = frozenset(w.lower() for w in entry["words"])
        rule.other_words = frozenset(w.lower() for w in entry.get("other_words", []))
        rule.min_words = int(entry.get("min_words", 3))
        rule.marker_chars = entry.get("marker_chars", "")
    else:
        raise ValueError(f"{path}: rule {rid} needs a pattern (or words, with scope comment)")
    return rule


def merge_file(cfg: Config, path: Path) -> None:
    """Merge a configuration file or rule pack into cfg."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    unknown_top = set(data) - TOP_KEYS
    if unknown_top:
        raise ValueError(f"{path}: unknown keys {sorted(unknown_top)}")
    cfg.exclude.extend(data.get("exclude", []))
    cfg.legit_prefixes.update(data.get("legit_id_prefixes", []))
    if "ticket_pattern" in data:
        cfg.ticket_re = re.compile(data["ticket_pattern"])
    for entry in data.get("allow", []):
        unknown = set(entry) - ALLOW_KEYS
        if unknown:
            raise ValueError(f"{path}: unknown allow keys {sorted(unknown)}")
        if not entry.get("reason"):
            raise ValueError(f"{path}: every allow entry needs a reason ({entry})")
        entry = {k: v for k, v in entry.items() if k != "repo"}
        cfg.allow.append(AllowEntry(**entry))
    for entry in data.get("rule", []):
        rule = _parse_rule(path, entry)
        if rule.id in cfg.names:
            raise ValueError(f"{path}: rule id {rule.id} is already defined")
        cfg.pack_rules.append(rule)
        cfg.rules.add(rule.id)


def pack_paths(cli: list[Path] | None = None) -> list[Path]:
    """Rule packs from --pack and from the environment variable PUBLICLINT_PACK."""
    env = [Path(p) for p in os.environ.get(PACK_ENV, "").split(os.pathsep) if p.strip()]
    return env + list(cli or [])


def load_config(path: Path | None, rules: set[str] | None = None, packs: list[Path] | None = None) -> Config:
    cfg = Config()
    if path is not None and path.exists():
        merge_file(cfg, path)
    for pack in packs or []:
        if not pack.is_file():
            raise ValueError(f"rule pack not found: {pack}")
        merge_file(cfg, pack)
    if rules:
        unknown = rules - set(cfg.names)
        if unknown:
            raise ValueError(f"unknown rules: {sorted(unknown)}")
        cfg.rules = rules
    return cfg


def _ids(line: str, cfg: Config) -> list[str]:
    out = []
    for m in cfg.ticket_re.finditer(line):
        prefix, num = m.group(1), m.group(2)
        if prefix in cfg.legit_prefixes or prefix.split("-")[0] in cfg.legit_prefixes:
            continue
        if prefix == "P" and num in P_CURVES:
            continue
        segs = prefix.split("-")
        # UUIDs, hex constants and version-like tokens
        if any(len(s) >= 4 and re.fullmatch(r"[0-9A-F]+", s) and any(c.isdigit() for c in s) for s in segs) \
                or len(num) >= 5:
            continue
        out.append(m.group(0))
    return out


def scan_line(line: str, cfg: Config) -> list[tuple[str, str]]:
    r = cfg.rules
    hits: list[tuple[str, str]] = []
    if "PL001" in r:
        hits += [("PL001", m) for m in _ids(line, cfg)]
    if "PL006" in r:
        hits += [("PL006", m.group(0)) for m in LOCAL_PATH_RE.finditer(line)]
    for rule in cfg.pack_rules:
        if rule.scope == "line" and rule.id in r:
            hits += [(rule.id, m) for m in rule.search_line(line)]
    if "PL013" in r:
        hits += [("PL013", m.group(0)[:24]) for m in SECRET_RE.finditer(line)]
    if "PL014" in r:
        hits += [("PL014", m.group(0)[:24]) for m in FINGERPRINT_RE.finditer(line)]
    if "PL015" in r and "@" in line:
        hits += [("PL015", m.group(0)) for m in EMAIL_RE.finditer(line)
                 if m.group(2).lower() not in FILE_EXT_TLDS and not EMAIL_OK_DOMAIN_RE.search(m.group(1))]
    return hits


def scan_text(path: str, text: str, cfg: Config) -> list[tuple[int, str, str, str]]:
    lines = text.split("\n")
    out = [(no, rule, match, line) for no, line in enumerate(lines, 1) for rule, match in scan_line(line, cfg)]
    lang = srclex.language_for(path)
    is_code = lang in CODE_LANGS and not path.endswith((".md", ".txt"))
    if is_code and "PL011" in cfg.rules:
        out += [(no, "PL011", m.group(0), line) for no, line in enumerate(lines, 1) for m in EMOJI_RE.finditer(line)]
    comment_rules = [rule for rule in cfg.pack_rules if rule.scope == "comment" and rule.id in cfg.rules]
    if is_code and lang != "pbxproj" and comment_rules:
        for rule in comment_rules:
            seen: set[int] = set()
            for seg in srclex.segments(text, lang):
                if seg.kind != srclex.COMMENT:
                    continue
                first = text.count("\n", 0, seg.start) + 1
                for k, part in enumerate(text[seg.start:seg.end].split("\n")):
                    no = first + k
                    if no in seen:
                        continue
                    for match in rule.search_line(part):
                        seen.add(no)
                        out.append((no, rule.id, match, lines[no - 1] if no <= len(lines) else part))
    name = PurePosixPath(path).name
    for rule in cfg.pack_rules:
        if rule.scope == "filename" and rule.id in cfg.rules and rule.search_line(name):
            out.append((0, rule.id, name, path))
    return out


def _git_files(repo: Path) -> list[str] | None:
    """Tracked files of a git checkout, or None when REPO is not one (or git is missing)."""
    if not (repo / ".git").exists():
        return None
    try:
        res = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p.decode(errors="replace") for p in res.stdout.split(b"\0") if p]


def _walked_files(repo: Path) -> list[str]:
    files: list[str] = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in WALK_SKIP_DIRS)
        rel_root = os.path.relpath(root, repo)
        prefix = "" if rel_root == "." else rel_root.replace(os.sep, "/") + "/"
        files += [prefix + n for n in sorted(names)]
    return files


def tracked_files(repo: Path) -> list[str]:
    files = _git_files(repo)
    return files if files is not None else _walked_files(repo)


def lint_repo(repo: Path, cfg: Config) -> list[Finding]:
    findings: list[Finding] = []
    names = cfg.names
    for path in tracked_files(repo):
        if any(_glob(path, g) for g in cfg.exclude):
            continue
        fp = repo / path
        if fp.is_symlink() or not fp.is_file():
            continue
        data = fp.read_bytes()
        if b"\0" in data[:8192] or len(data) > MAX_BYTES:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for no, rule, match, line in scan_text(path, text, cfg):
            f = Finding(path, no, rule, names[rule], match, line)
            if not any(a.allows(f) for a in cfg.allow):
                findings.append(f)
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", nargs="?", type=Path, default=Path("."))
    ap.add_argument("--config", type=Path, help=f"configuration (default: REPO/{CONFIG_NAME})")
    ap.add_argument("--pack", type=Path, action="append", default=[],
                    help=f"additional rule pack (repeatable; also ${PACK_ENV})")
    ap.add_argument("--rules", help="comma-separated rule ids (default: all)")
    ap.add_argument("--format", choices=("text", "summary", "json"), default="text")
    args = ap.parse_args(argv)
    rules = set(args.rules.split(",")) if args.rules else None
    try:
        cfg = load_config(args.config or args.repo / CONFIG_NAME, rules, pack_paths(args.pack))
        findings = lint_repo(args.repo, cfg)
    except (ValueError, OSError, re.error, tomllib.TOMLDecodeError) as exc:
        print(f"publiclint: {exc}", file=sys.stderr)
        return 2
    if args.format == "json":
        json.dump([asdict(f) for f in findings], sys.stdout, indent=2, ensure_ascii=False)
        print()
    else:
        by_rule = Counter((f.rule, f.name) for f in findings)
        print(f"publiclint: {len(findings)} finding(s)"
              + ("  [" + "  ".join(f"{k} {n} {v}" for (k, n), v in sorted(by_rule.items())) + "]" if by_rule else ""))
        if args.format == "text":
            for f in findings:
                print("  " + f.format())
            if findings:
                print("See tools/publiclint/README.md of the contract: describe the reason in plain words "
                      "or add a justified entry to .public-lint.toml.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
