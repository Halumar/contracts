"""srclex – tiny, dependency-free source segmenter.

Splits a file into contiguous segments of kind "code", "string" or "comment"
so that codemod rules and lint checks can tell an identifier from a string
literal or a comment. It is deliberately approximate: it only has to be good
enough for the Halumar repos (Python, Swift, JS/TS/Svelte,
YAML/shell, JSON, Markdown, plist/XML).

    segments(text, lang) -> list[Segment]   # covers text completely, in order
    language_for(path)   -> lang string
"""
from __future__ import annotations

import io
import tokenize
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import PurePosixPath

CODE, STRING, COMMENT = "code", "string", "comment"


@dataclass(frozen=True)
class Segment:
    kind: str
    start: int
    end: int


_EXT = {
    ".py": "python", ".pyi": "python",
    ".swift": "swift",
    ".js": "clike", ".mjs": "clike", ".cjs": "clike", ".ts": "clike", ".mts": "clike",
    ".css": "clike", ".scss": "clike",
    ".svelte": "markup", ".html": "markup", ".htm": "markup", ".xml": "markup", ".plist": "markup",
    ".xcscheme": "markup", ".xcworkspacedata": "markup", ".entitlements": "markup", ".svg": "markup",
    ".yaml": "hash", ".yml": "hash", ".toml": "hash", ".sh": "hash", ".cfg": "hash", ".ini": "hash",
    ".conf": "hash", ".txt": "hash", ".env": "hash",
    ".json": "json",
    ".pbxproj": "pbxproj", ".xcconfig": "clike", ".strings": "clike",
}
_NAMES = {"Dockerfile": "hash", "Makefile": "hash", "run": "hash", "finish": "hash", ".gitignore": "hash"}


def language_for(path: str) -> str:
    p = PurePosixPath(path)
    if p.name in _NAMES:
        return _NAMES[p.name]
    return _EXT.get(p.suffix.lower(), "plain")


def segments(text: str, lang: str) -> list[Segment]:
    fn = {
        "python": _python, "swift": _swift, "clike": _clike, "pbxproj": _clike,
        "hash": _hash, "markup": _markup, "json": _json,
    }.get(lang)
    if fn is None:
        return [Segment(CODE, 0, len(text))] if text else []
    try:
        spans = fn(text)
    except Exception:  # tokenizer failure: treat as one code segment
        spans = []
    return _fill(spans, len(text))


def kind_at(segs: list[Segment], offset: int) -> str:
    starts = [s.start for s in segs]
    i = bisect_right(starts, offset) - 1
    if i < 0:
        return CODE
    return segs[i].kind


def _fill(spans: list[tuple[str, int, int]], n: int) -> list[Segment]:
    out: list[Segment] = []
    pos = 0
    for kind, s, e in sorted(spans, key=lambda x: x[1]):
        if s < pos:
            continue
        if s > pos:
            out.append(Segment(CODE, pos, s))
        out.append(Segment(kind, s, e))
        pos = e
    if pos < n:
        out.append(Segment(CODE, pos, n))
    return out


# ---------------------------------------------------------------- Python

def _python(text: str) -> list[tuple[str, int, int]]:
    line_starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            line_starts.append(i + 1)

    def off(pos: tuple[int, int]) -> int:
        return line_starts[pos[0] - 1] + pos[1]

    toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    spans: list[tuple[str, int, int]] = []
    skip = {tokenize.NL, tokenize.COMMENT}
    fstart = getattr(tokenize, "FSTRING_START", None)
    fend = getattr(tokenize, "FSTRING_END", None)
    tstart = getattr(tokenize, "TSTRING_START", None)
    tend = getattr(tokenize, "TSTRING_END", None)
    depth = 0
    fs_begin = None
    prev_sig = None
    for idx, tok in enumerate(toks):
        if tok.type == tokenize.COMMENT:
            spans.append((COMMENT, off(tok.start), off(tok.end)))
            continue
        if tok.type in (fstart, tstart) and tok.type is not None:
            if depth == 0:
                fs_begin = off(tok.start)
            depth += 1
            continue
        if tok.type in (fend, tend) and tok.type is not None:
            depth -= 1
            if depth == 0 and fs_begin is not None:
                spans.append((STRING, fs_begin, off(tok.end)))
                fs_begin = None
                prev_sig = tok
            continue
        if depth:
            continue
        if tok.type == tokenize.STRING:
            nxt = next((t for t in toks[idx + 1:] if t.type not in skip), None)
            is_doc = (prev_sig is None or prev_sig.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                                                             tokenize.ENCODING)) and \
                (nxt is None or nxt.type in (tokenize.NEWLINE, tokenize.ENDMARKER))
            spans.append((COMMENT if is_doc else STRING, off(tok.start), off(tok.end)))
        if tok.type not in skip:
            prev_sig = tok
    return spans


# ---------------------------------------------------------------- Swift

def _swift(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    n = len(text)
    i = 0

    def scan_string(i: int) -> int:
        """i points at the first '#' or '"' of a literal; returns end offset."""
        hashes = 0
        while i < n and text[i] == "#":
            hashes += 1
            i += 1
        multi = text.startswith('"""', i)
        i += 3 if multi else 1
        close = ('"""' if multi else '"') + "#" * hashes
        esc = "\\" + "#" * hashes
        while i < n:
            if text.startswith(esc, i):
                j = i + len(esc)
                if j < n and text[j] == "(":
                    i = scan_interp(j + 1)
                    continue
                i = j + 1
                continue
            if text.startswith(close, i):
                return i + len(close)
            if not multi and text[i] == "\n":
                return i
            i += 1
        return n

    def scan_interp(i: int) -> int:
        depth = 1
        while i < n and depth:
            ch = text[i]
            if ch == '"' or (ch == "#" and _raw_start(i)):
                i = scan_string(i)
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        return i

    def _raw_start(i: int) -> bool:
        j = i
        while j < n and text[j] == "#":
            j += 1
        return j < n and text[j] == '"'

    while i < n:
        if text.startswith("//", i):
            e = text.find("\n", i)
            e = n if e < 0 else e
            spans.append((COMMENT, i, e))
            i = e
        elif text.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            spans.append((COMMENT, i, j))
            i = j
        elif text[i] == '"' or (text[i] == "#" and _raw_start(i)):
            e = scan_string(i)
            spans.append((STRING, i, e))
            i = e
        else:
            i += 1
    return spans


# ---------------------------------------------------------------- C-like (JS/TS/CSS/xcconfig/pbxproj)

def _clike(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    n = len(text)
    i = 0
    while i < n:
        if text.startswith("//", i) and (i == 0 or text[i - 1] != ":"):
            e = text.find("\n", i)
            e = n if e < 0 else e
            spans.append((COMMENT, i, e))
            i = e
        elif text.startswith("/*", i):
            e = text.find("*/", i + 2)
            e = n if e < 0 else e + 2
            spans.append((COMMENT, i, e))
            i = e
        elif text[i] in "'\"`":
            q = text[i]
            j = i + 1
            while j < n and text[j] != q:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "\n" and q != "`":
                    break
                j += 1
            e = min(j + 1, n)
            spans.append((STRING, i, e))
            i = e
        else:
            i += 1
    return spans


# ---------------------------------------------------------------- '#' comment languages (YAML, shell, TOML)

def _hash(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        q = None
        j = 0
        while j < len(line):
            ch = line[j]
            if q:
                if ch == "\\" and q == '"':
                    j += 1
                elif ch == q:
                    spans.append((STRING, pos + qs, pos + j + 1))
                    q = None
            elif ch in "'\"" and (j == 0 or not line[j - 1].isalnum()):
                q, qs = ch, j
            elif ch == "#" and (j == 0 or line[j - 1] in " \t"):
                end = len(line.rstrip("\r\n"))
                spans.append((COMMENT, pos + j, pos + end))
                break
            j += 1
        pos += len(line)
    return spans


# ---------------------------------------------------------------- markup (HTML/XML/Svelte/plist)

def _markup(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    i = 0
    while True:
        s = text.find("<!--", i)
        if s < 0:
            break
        e = text.find("-->", s + 4)
        e = len(text) if e < 0 else e + 3
        spans.append((COMMENT, s, e))
        i = e
    return spans


# ---------------------------------------------------------------- JSON

def _json(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    n, i = len(text), 0
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\":
                    j += 1
                j += 1
            spans.append((STRING, i, min(j + 1, n)))
            i = j + 1
        else:
            i += 1
    return spans


__all__ = ["Segment", "segments", "language_for", "kind_at", "CODE", "STRING", "COMMENT"]
