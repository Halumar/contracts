# Documentation

The schemas, the OpenAPI and AsyncAPI documents, the data files and the fixtures are authoritative.
These pages explain how the pieces fit together. New here? Start with the [overview](overview.md) and
keep the [glossary](glossary.md) open.

## Start here

| Document | What it defines | Who needs it |
|---|---|---|
| [overview.md](overview.md) | The rule model end to end (device, profile, rules, boundaries, resolved rules, enforcement), with one worked example from a test vector | Everyone |
| [glossary.md](glossary.md) | The terms these documents use, with the file that defines each | Everyone |

## Rules and profiles

| Document | What it defines | Who needs it |
|---|---|---|
| [profiles.md](profiles.md) | The rule catalog, boundaries, resolution order, reason codes, temporary adjustments, suggestions, profile admin API, delivery to the apps | Anyone checking or implementing rules: hub, admin UI, app developers, reviewers |
| [enforcement.md](enforcement.md) | Control path, the integration action `<ns>.control` and its checks, the rule snapshot and its hash, events, devices on the hub path (Hub only and parental controls), the compliance status | Integration and app developers; anyone judging what is enforced where |
| [access.md](access.md) | Access hours, the access switch in Home Assistant, babysitter and house sitter, early access | Hub, integration and app developers |
| [family.md](family.md) | The family manager right: what it may change, releases, pause everything, children's requests | Hub and app developers |
| [setup.md](setup.md) | Profile kinds, the rule "Set up new devices", the QR and code flow, no escalation, guest invitations | Hub and app developers |
| [location.md](location.md) | The rules `location` and `location_required`, the action `<ns>.report_location`, the hub way for parental controls | Hub, integration and app developers |

## Protocol and devices

| Document | What it defines | Who needs it |
|---|---|---|
| [protocol.md](protocol.md) | Protocol version and compatibility, error reasons, area visibility, tile settings, remote access, home networks, quick access, kids mode, watches, known deviations | Client developers |
| [per-device-users.md](per-device-users.md) | One Home Assistant user per device: provisioning, token delivery and rotation, removal | Hub and integration developers |
| [panel.md](panel.md) | Wall panels and status sensors of every device in Home Assistant, panel commands | Hub, integration and app developers |
| [log.md](log.md) | The log tab of the hub and notifications at events | Hub and admin UI developers |
| [links.md](links.md) | Tag links (`/t/<tag_id>`) and open links (`/open/<view>`), the website paths the apps claim | App and website developers |
| [room-climate.md](room-climate.md) | Which entities give an area's room temperature and humidity | Hub and app developers |

## Tools

| Document | What it defines | Who needs it |
|---|---|---|
| [tools/codegen/README.md](../tools/codegen/README.md) | The model generator for Python, TypeScript, Swift and Kotlin and its decoding rules | Anyone consuming the generated models |
| [tools/brand/README.md](../tools/brand/README.md) | Brand definition and brand lint | Contributors |
| [tools/publiclint/README.md](../tools/publiclint/README.md) | The public text lint run in CI | Contributors |

## Release notes

[CHANGELOG.md](../CHANGELOG.md): the changelog of the contract.
