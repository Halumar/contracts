# publiclint

Finds ticket references, local paths, secrets and emoji in text meant for the public. It runs in
the CI of the contract (`validate.yml`), the hub (`ci.yml`) and the integration (`validate.yml`);
hub and integration use the copy in the pinned contract.

```sh
python3 tools/publiclint/publiclint.py .                   # all findings, exit code 1 if any
python3 tools/publiclint/publiclint.py ../hub --format summary
python3 -m unittest discover -s tools/publiclint -p "test_*.py"
```

Python 3.11 or later, standard library only (plus `tools/brand/srclex.py` for comments). In a git
checkout the tool lints the tracked files; in a folder without git, such as an unpacked archive,
it walks the folder and skips `.git`, virtual environments, `node_modules` and build folders.

## Rules

| Rule | Finds | Write instead |
|---|---|---|
| PL001 | ticket-style references: an upper-case word, a hyphen and a number; standards such as `SHA-256`, `ISO-8601` and RFC or CVE numbers are fine | what the change does or why, in one sentence |
| PL006 | local paths (`/Users/<name>`, macOS temporary folders, `C:\Users\<name>`) | a relative path |
| PL011 | emoji in code | plain text |
| PL013 | secrets (private keys, tokens, JWTs) | – (rotate the secret) |
| PL014 | certificate fingerprints in colon hex | a made-up or shortened value |
| PL015 | e-mail addresses outside `example.*`, `.test`, `.invalid` and the project's domains | an example address |

Versions (`1.0.0`, `1.1.0-rc.1`), protocol values and field names are never findings.

## Configuration

`.public-lint.toml` in the repository root (or `--config FILE`). Keep it short; every exception
needs a reason:

```toml
[[allow]]
rule = "PL011"
path = "tests/test_crypto.py"
line = "Ünïcode"
reason = "Unicode round-trip test string, not decoration."
```

Keys of an `[[allow]]` entry: `rule` (id or `*`), `path` (glob, `**/` prefix allowed), optional
`line` and `match` (regular expressions on the line and on the finding), `reason`. Top level:

- `exclude = [globs]`: files that are never read;
- `legit_id_prefixes = ["ABC"]`: a standard that looks like a ticket reference;
- `ticket_pattern = '…'`: replaces the regular expression of PL001 (group 1 is the prefix, group 2
  the number).

## Rule packs

A project can add its own rules without putting them into this repository. A rule pack is a TOML
file in the same format as `.public-lint.toml`, with `[[rule]]` tables. Pass it with
`--pack FILE` (repeatable) or set `PUBLICLINT_PACK` to one or more paths (separated by `:` on
Linux and macOS, `;` on Windows):

```toml
[[rule]]
id = "XY001"                  # unique id: two or more capitals and three digits
name = "codename"
help = "the feature name"     # optional
pattern = '\bproject acme\b'
ignore_case = true            # optional

[[rule]]
id = "XY002"
name = "draft-file"
scope = "filename"            # line (default), comment or filename
pattern = '(?i)^draft[-_]'
```

- `line` rules check every line of every text file.
- `comment` rules check only comments in code files. Instead of a `pattern` they may give
  `words` and `other_words`: a comment line is reported when at least `min_words` (default 3) of
  its words are in `words` and they outnumber those in `other_words`. With one of `marker_chars`
  in the line, `min_words` − 1 words are enough.
- `filename` rules check the base name of every file.

`--rules` selects rule ids, built-in or from a pack.
