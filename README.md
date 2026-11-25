<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/brand/halumar-wordmark-on-dark.svg">
    <img src="docs/assets/brand/halumar-wordmark-color.svg" width="280" alt="Halumar">
  </picture>
  <br>contracts
</h1>

Halumar gives every device in a home its own, limited view of Home Assistant: a wall panel, a guest's
phone, a child's tablet, a TV or a watch each see and control only what an admin allows. This
repository is the shared contract of all Halumar parts: the rule catalog, the protocol between hub,
integration and apps, and the test material every part is checked against. It contains no running
software; the [hub](https://github.com/Halumar/hub) and the
[integration](https://github.com/Halumar/integration) implement it.

[Overview](docs/overview.md) · [Glossary](docs/glossary.md) · [All docs](docs/README.md) ·
[Security](SECURITY.md) · [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md)

## Who this is for

- **You want to understand how Halumar's rules work.** Read the [overview](docs/overview.md): it
  follows one device from its profile to the moment it switches a light, with a worked example from a
  real test vector. The [glossary](docs/glossary.md) explains every term, and
  [profiles.md](docs/profiles.md) lists every rule.
- **You want to build a client or check an implementation.** Use the schemas, the OpenAPI and
  AsyncAPI documents, the reference resolver and the shared test vectors described below. Generated
  models exist for Python, TypeScript, Swift and Kotlin.

## Status

The current version is **1.0.0** (see [VERSION](VERSION)), the first public release of the contract,
for hub and integration 2026.12.0. The hub, the integration and the apps move to a new contract version
together.

## How the parts fit together

```text
                 ┌──────────────────── contracts (this repository) ───────────────────┐
                 │ rule catalog · schemas · OpenAPI · AsyncAPI · vectors · codegen    │
                 └───────────┬─────────────────────┬─────────────────────┬────────────┘
                   generated models          generated models      generated models
                             ▼                     ▼                     ▼
   ┌──────────────┐  WebSocket /api/ws   ┌──────────────┐  REST + WS  ┌───────────────────────────┐
   │     Apps     │◀────────────────────▶│     Hub      │◀───────────▶│ Integration (in Home      │
   │ phones,      │  client_config,      │ (HA app)     │  rule       │ Assistant): one HA user   │
   │ tablets, TV, │  resolved rules      │ profiles,    │  snapshots, │ per device, <ns>.control  │
   │ watches      │                      │ resolver     │  events     │                           │
   └──────┬───────┘                      └──────────────┘             └─────────────┬─────────────┘
          │        Home Assistant WebSocket / REST with the device's own user       │
          └───────────────────────────────▶ Home Assistant ◀────────────────────────┘
```

The contract covers the Halumar apps for iPhone, iPad, Apple TV, Apple Watch, Android phone and tablet
(also as a wall panel) and Android TV (catalog platforms `ios`, `ipados`, `tvos`, `watchos`, `android`,
`android_tablet`, `android_tv`). The protocol also provides for Wear OS watches (`wearos`) and a web app (`web`);
apps for them are planned and do not exist yet. The Apple apps (iPhone, iPad, Apple TV, Apple Watch) are
in beta and available through [TestFlight](https://testflight.apple.com/join/fHX7YT8v); the Android apps
(phone, tablet and wall panel, Android TV) are not available yet. Not every rule applies to every platform; [profiles.md](docs/profiles.md#rule-catalog) names the platforms of each rule.

## How the rules work, in short

Every device has exactly one **profile**. A profile holds one value per **rule** of the catalog
([`data/profile-rules.json`](data/profile-rules.json)). The admin can change a rule that is not
**fixed** for one device with a **device adjustment**, permanently or until a time. Three **boundaries**,
guest access, parental controls and Hub only, lie over everything and only restrict. The hub **resolves** all of
this into one value per rule, with its source and reason, and sends the result to the app and a rule
snapshot to the integration. Each resolved rule says who **enforces** it: Home Assistant itself (`ha`,
`ha_control`), the hub (`hub`) or only the app (`app`). Full walk-through: [docs/overview.md](docs/overview.md).

## What is in this repository

| Path | Content |
|---|---|
| [`data/`](data) | Contract data shared by every part: the rule catalog (`profile-rules.json`), the profile suggestions, quick access levels, tile settings and icons, the control allowlist of `<ns>.control`, the event taxonomy, the family manager catalog, access requests, room climate. Each file has a schema in `schemas/data/`. |
| [`schemas/`](schemas) | JSON Schema 2020-12: every WebSocket message (`ws/client`, `ws/server`, `ws/command`, `ws/broadcast`, `ws/heartbeat`, `ws/integration`), shared types (`common/`), REST bodies (`rest/`), the integration API (`integration/`), Bonjour and deep links, mirrored Home Assistant entities (`sensors/`), crypto and profile vectors, the client configuration. |
| [`openapi/hub.openapi.json`](openapi/hub.openapi.json) | REST API of the hub (OpenAPI 3.1), a snapshot of the hub code with per-operation security (`x-auth`: `public`, `client`, `admin`, `ingress`, `integration`). |
| [`openapi/ha-compliance-view.openapi.json`](openapi/ha-compliance-view.openapi.json) | The compliance endpoint the integration adds to Home Assistant. |
| [`asyncapi/hub-ws.asyncapi.yaml`](asyncapi/hub-ws.asyncapi.yaml) | The hub WebSocket `/api/ws` (AsyncAPI 3.0): handshake, heartbeat, close codes, limits, every message and the audience of each broadcast. |
| [`fixtures/`](fixtures) | Golden examples at `fixtures/<schema path>/<case>.json`, validated against `schemas/<schema path>.json`; cases named `invalid-*` must fail. Test vectors live here too: `fixtures/profiles/resolve` and `expiry` (resolver), `access-hours`, `family-check`, `fixtures/crypto` (known-answer vectors), `fixtures/network`, `fixtures/climate`. |
| [`tools/profiles_ref.py`](tools/profiles_ref.py) | Reference resolver of the profile model (pure functions, standard library). Other references: `access_ref.py`, `family_ref.py`, `home_networks_ref.py`, `room_climate_ref.py`. |
| [`tools/validate.py`](tools/validate.py) | Validates schemas, fixtures, OpenAPI, AsyncAPI and the namespace, and runs every vector through the references. |
| [`tools/codegen/`](tools/codegen) | Model generator for Python (pydantic v2), TypeScript (types), Swift (Codable) and Kotlin (kotlinx.serialization), with the checked-in output in `tools/codegen/snapshots/`. See its [README](tools/codegen/README.md). |
| [`namespace.json`](namespace.json) | Every value that depends on the technical namespace `halumar` (written `<ns>` in the docs). |
| [`brand.json`](brand.json), [`tools/brand/`](tools/brand) | The display brand and the brand lint. |
| [`docs/`](docs/README.md) | The documents that explain how the pieces fit together. |

## Using the contract in a client

1. **Pin a tag.** Every contract version is tagged `v<version>` (for example `v1.0.0`). The hub
   and the integration keep the tag in `.github/contracts-ref`; their CI checks out that tag and fails
   when the OpenAPI snapshot or the copied data, schema and fixture files differ. Changing the pin is a reviewed commit in the
   consumer.
2. **Generate models** and check them in. The generator needs only Python 3.11 or later:

   ```sh
   python3 tools/codegen/generate.py --lang python --out <dir>          # pydantic v2 models
   python3 tools/codegen/generate.py --lang ts     --out <dir>          # TypeScript types
   python3 tools/codegen/generate.py --lang swift  --out <dir>          # Codable structs
   python3 tools/codegen/generate.py --lang kotlin --out <dir>          # kotlinx.serialization
   python3 tools/codegen/generate.py --lang swift  --out <dir> --check  # exit 1 if out of date
   ```

   The models decode tolerantly (unknown fields, enum values and message types do not break a client)
   and validate strictly on request.
3. **Decode tolerantly.** Servers may add fields, message types and enum values without a new protocol
   version. Clients ignore what they do not know.
4. **Test against the vectors.** Run every `fixtures/profiles/resolve/*.json` through your resolver (or,
   for an app, feed the expected rules into your UI tests); [profiles.md](docs/profiles.md#using-the-vectors)
   says how. To see what the reference returns for one vector:

   ```sh
   python3 tools/profiles_ref.py fixtures/profiles/resolve/control-path-guest-boundary.json
   ```

## Versions, tags and releases

- **Contract version.** SemVer in [`VERSION`](VERSION), independent of the calendar versions of the hub
  and the integration. An additive change (below) is a new minor version. A breaking change needs a new
  major version; when an older app cannot handle it, `protocol_version` increases as well.
- **Protocol version.** A separate integer (`protocol_version`); contract 1.0.0 is protocol 1. It only
  increases for changes an older app cannot handle. A hub always supports at least the two previous
  protocol versions ([protocol.md](docs/protocol.md#protocol-version)).
- **Additive** means: a new optional field, a new message type or a new enum value. Clients decode
  tolerantly, so an additive change does not raise the protocol version. The changelog says when a
  version is not additive.
- **Namespace.** The technical namespace `halumar` (domain, Bonjour type, deep-link scheme, entity id
  prefixes) is frozen. Schemas mark dependent values with `x-namespace-key`; `tools/validate.py` checks
  that the literal appears only where `namespace.json` allows it.
- **Release workflow** ([`.github/workflows/release.yml`](.github/workflows/release.yml)). On every push
  to `main` (and manual runs on `main`): it reads `VERSION` and requires a `## [<version>]` section in
  `CHANGELOG.md`. It stops when the tag `v<version>` and its GitHub release both exist; when only the
  tag exists it creates the release, provided the tag points at the pushed commit. Otherwise it runs the
  full validate workflow, creates the annotated tag `v<version>` and a GitHub release with that
  changelog section. Versions with a suffix
  (such as `1.1.0-rc.1`) are marked as pre-releases. A release is made by raising `VERSION` together with a
  new changelog section.

| Contract | Protocol | Hub and integration |
|---|---|---|
| 1.0.0 | 1 | 2026.12.0 |

## Checking the contract from a clean checkout

You need Python 3.12 (the version CI uses; the generator alone runs on 3.11 or later) and, for the
AsyncAPI check, Node.js.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r tools/codegen/requirements.txt          # validator + pydantic

.venv/bin/python tools/validate.py                               # schemas, fixtures, OpenAPI, AsyncAPI, namespace, vectors
.venv/bin/python tools/profile_rules.py --check                  # catalog, suggestions, resolved-rules.json
npx --yes @asyncapi/cli@6.3.1 validate asyncapi/hub-ws.asyncapi.yaml

for lang in python ts swift kotlin; do                           # generated models are current
  out=$lang; [ "$lang" = ts ] && out=typescript
  python3 tools/codegen/generate.py --lang "$lang" --out "tools/codegen/snapshots/$out" --check
done

.venv/bin/python tools/codegen/tests/test_codegen.py -v          # round trips over all fixtures

python3 -m unittest discover -s tools/brand -p "test_*.py"       # brand tool tests
python3 tools/brand/brandlint.py .                               # brand lint
python3 tools/check_licenses.py                                  # LICENSE unchanged, NOTICE complete
python3 -m unittest discover -s tools/publiclint -p "test_*.py"  # public text lint tests
python3 tools/publiclint/publiclint.py .                         # public text lint
.venv/bin/python -m unittest discover -s tools -p "test_workflows.py"  # workflow checks
```

The codegen tests also run the TypeScript, Swift and Kotlin round trips when `npx` (or `TSC`), the
Swift toolchain, and Gradle with a JDK 21 are available; otherwise they skip those languages
(`CODEGEN_SKIP_TS=1`, `CODEGEN_SKIP_SWIFT=1`, `CODEGEN_SKIP_KOTLIN=1` skip them on purpose). CI
runs all of them. [CONTRIBUTING.md](CONTRIBUTING.md) lists every CI check.

The OpenAPI snapshot is generated from a checkout of the hub next to this one:

```sh
python3 tools/snapshot_openapi.py --app-dir ../hub/halumar/rootfs/opt/hub           # write
python3 tools/snapshot_openapi.py --app-dir ../hub/halumar/rootfs/opt/hub --check   # hub CI
```

## Security model in brief

The contract describes three places where rules are enforced, and says per rule which one applies:

- **Home Assistant** (`ha`, `ha_control`): every device has its own Home Assistant user. Remote access
  is that user's "local only" flag. With the checked control path the user is read-only and can switch
  only through the integration action `<ns>.control`, which checks the device's rules.
- **The hub** (`hub`): rights such as setting up devices, the family manager and the kids rules are
  checked by the hub on every request. A device on “Hub only” gets no Home Assistant key at all: it reads
  and switches only through the hub, which serves only what its profile allows.
- **The app** (`app`): display rules, such as which areas are shown or the wall panel settings, are
  followed by the app. Someone with their own Home Assistant access is not bound by
  them.

Limits that Home Assistant sets: a Home Assistant user can always read every entity, so hiding is never
enforced by Home Assistant, only by the app or, on “Hub only”, by the hub. With remote access a device on
“Hub only” holds a read-only key and can read every state in Home Assistant from anywhere. With the direct control path, what a device may operate is
also only an app rule. Details: [docs/enforcement.md](docs/enforcement.md). Known deviations of the
current hub from the contract are listed in [docs/protocol.md](docs/protocol.md#known-deviations).

## Related repositories

- [Halumar/hub](https://github.com/Halumar/hub): the Home Assistant app (add-on)
- [Halumar/integration](https://github.com/Halumar/integration): the Home Assistant custom integration

## Reporting problems

- Bugs and questions about the contract: open an issue in this repository. Problems with the running
  hub or integration belong in their repositories.
- Security problems: do not open a public issue. See [SECURITY.md](SECURITY.md).

## How this project is built

The code and documentation are written with AI coding assistants under the direction and review of the
maintainer. Every change ships with tests, and the checks above run in CI on every pull request.
Report problems as described above.

## License

Licensed under the [Apache License 2.0](LICENSE) (`Apache-2.0`), copyright 2026 xonatec
([NOTICE](NOTICE)). Code generated from the contract may be used in any application, including
proprietary ones.

## Trademarks

"Halumar" and the Halumar logo are trademarks of xonatec and are not covered by the license
([TRADEMARKS.md](TRADEMARKS.md)). Home Assistant is a trademark of the Open Home Foundation. Halumar
is an independent project and is not affiliated with or endorsed by Home Assistant or the Open Home
Foundation.
