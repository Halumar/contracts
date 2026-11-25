# tools/brand – brand generator and brand lint

Generates the brand files of every component from `brand.json` and checks that the brand and the
technical namespace are used only where they belong. Python ≥ 3.11, standard library only.

| File | Purpose |
|---|---|
| `brandgen.py` | validates `brand.json`; `--emit OUTPUT=PATH` writes one generated file (`python/brand.py`, `ts/brand.ts`, `swift/Brand.swift`, `swift/Brand.xcconfig`, …), `--patch-addon-config`, `--patch-manifest` (repeatable); `--check` fails on stale files |
| `brandlint.py` | BL001 forbidden name in text, BL002 brand literal outside brand/generated files, BL003 namespace literal outside the namespace constants, BL004 forbidden name in paths; repo config `.brandlint.toml` |
| `default.brandlint.toml` | base configuration merged with the repo's `.brandlint.toml` |
| `srclex.py` | small lexer (code / string / comment) used by brandlint |
| `test_brand.py` | tests of both tools: `python3 -m unittest discover -s tools/brand -p "test_*.py"` |

Consumers call both through their `scripts/brand-check.sh` with `CONTRACTS_DIR` pointing to a
checkout of this repository.

Forbidden names (BL001, BL004) are regular expressions in `forbidden_patterns`. The default list is
empty; a repository adds its own in `.brandlint.toml`, or a private configuration is passed with
`--config FILE`:

```toml
forbidden_patterns = ['(?i)acme']    # report "Acme", "ACME", "acme_client.py", …
forbidden_allowed = ["docs/notes/**"] # paths where the name may appear
```
