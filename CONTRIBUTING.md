# Contributing to the Halumar contract

Thank you for helping to improve the interface contract of Halumar: the rule catalog, schemas,
fixtures, OpenAPI and AsyncAPI documents, reference tools and the code generator.

## License

The contract is licensed under the [Apache License 2.0](LICENSE) (`Apache-2.0`),
copyright 2026 xonatec (see [NOTICE](NOTICE)). By contributing, you agree that your
contribution is licensed under the same license (Apache-2.0 §5). Code generated from the
contract is used in the hub (AGPL-3.0), the integration (Apache-2.0) and the Halumar apps
(proprietary); Apache-2.0 allows all of them.

## Developer Certificate of Origin (DCO)

Every commit must be signed off. With the sign-off you confirm the
[Developer Certificate of Origin 1.1](https://developercertificate.org/): you wrote the
change or otherwise have the right to submit it under the project's license.

Add the sign-off with `git commit -s`. It appends a line with your name and e-mail:

```text
Signed-off-by: Your Name <you@example.com>
```

Use your real name. The [DCO app](https://github.com/apps/dco) checks every pull request;
a commit without a sign-off can be fixed with `git commit --amend -s` or
`git rebase --signoff main`.

## How to contribute

1. Protocol changes start here (contract first). Open an issue first and describe the
   change for the hub, the integration and the apps.
2. Fork the repository and create a branch from `main`.
3. Make the change. After a schema change, generate the models again for all four languages
   and commit the diffs:

   ```sh
   python3 tools/codegen/generate.py --lang python --out tools/codegen/snapshots/python
   python3 tools/codegen/generate.py --lang ts     --out tools/codegen/snapshots/typescript
   python3 tools/codegen/generate.py --lang swift  --out tools/codegen/snapshots/swift
   python3 tools/codegen/generate.py --lang kotlin --out tools/codegen/snapshots/kotlin
   ```

   After a change of `schemas/common/profile-rule-values.json`, run
   `python3 tools/profile_rules.py` (it writes `schemas/common/resolved-rules.json`).
4. Keep the checks green (below) and add an entry under `## [Unreleased]` in `CHANGELOG.md`.
5. Open a pull request against `main`.

## Setting up

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r tools/codegen/requirements.txt
```

`tools/codegen/requirements.txt` includes the validator dependencies (`tools/requirements.txt`) and
pydantic for the Python round trip. The generator, the reference tools, the brand tools, the license
check and the public text lint need only the Python standard library (3.11 or later).

## Checks CI runs

[`.github/workflows/validate.yml`](.github/workflows/validate.yml) runs on every pull request and on
pushes to `main`. Run the same commands locally (with `python` = `.venv/bin/python`):

| Check | Command |
|---|---|
| Brand definition, brand lint and their tests | `python -m unittest discover -s tools/brand -p "test_*.py"`, `python tools/brand/brandgen.py --brand brand.json` and `python tools/brand/brandlint.py .` |
| Public text lint and its tests | `python -m unittest discover -s tools/publiclint -p "test_*.py"` and `python tools/publiclint/publiclint.py .` |
| Workflows: GitHub-hosted runners, pinned actions, resolvable references | `python -m unittest discover -s tools -p "test_workflows.py"` |
| Schemas, fixtures, OpenAPI, AsyncAPI, namespace, vectors | `python tools/validate.py` (CI adds `--asyncapi-schema <official AsyncAPI 3.0.0 JSON Schema>`) |
| AsyncAPI with the official parser | `npx --yes @asyncapi/cli@6.3.1 validate asyncapi/hub-ws.asyncapi.yaml` |
| License files | `python tools/check_licenses.py` |
| No brand icons among the tile icons | `python tools/check_tile_icons.py --mdi-meta <@mdi/svg 7.4.47>/meta.json` |
| Generated models are current | `python tools/codegen/generate.py --lang <python\|ts\|swift\|kotlin> --out tools/codegen/snapshots/<python\|typescript\|swift\|kotlin> --check` |
| Round trips over all fixtures | `python tools/codegen/tests/test_codegen.py -v` (CI sets `CODEGEN_REQUIRE_ALL=1`, so TypeScript, Swift and Kotlin must not be skipped) |

`tools/validate.py` also runs `tools/profile_rules.py`'s consistency check; you can run it alone with
`python tools/profile_rules.py --check`.

The public text lint finds ticket references, local paths, secrets and emoji in comments, docs and
tests ([tools/publiclint/README.md](tools/publiclint/README.md); exceptions with a reason in
`.public-lint.toml`).

## Commit messages

- English, imperative mood, subject at most 72 characters ("Add access hours to the rule snapshot").
- Say what changes and why. No internal ticket ids, review labels or local paths.
- Do not describe how to exploit a security problem in a commit message; report it privately first
  ([SECURITY.md](SECURITY.md)).
- Sign off every commit (`git commit -s`, see above).

## Releases

A release is made by raising [`VERSION`](VERSION) together with a `## [<version>]` section in
`CHANGELOG.md`. When that reaches `main`, [`.github/workflows/release.yml`](.github/workflows/release.yml)
runs the validate workflow, tags `v<version>` and creates a GitHub release with the changelog section
(versions with a suffix such as `-rc.1` as pre-releases). A version that is already tagged and released is
skipped; a tag without a release gets its release when the tag points at the pushed commit.

### Third-party material

- Do not copy material from other specifications or projects without naming its origin and
  license in the pull request; add the required notice to `NOTICE`.
- `data/tile-icons.json` may only name icons, never contain artwork; brand and logo icons
  are not allowed.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Trademarks

The license does not cover the name and logo "Halumar". See [TRADEMARKS.md](TRADEMARKS.md).

## Security

Please do not report security problems in public issues. See [SECURITY.md](SECURITY.md).
