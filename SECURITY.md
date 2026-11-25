# Security policy

## Reporting a vulnerability

Please do not report security problems in public issues, discussions or pull requests.

Use GitHub's private vulnerability reporting: **Report a vulnerability** on the
[Security tab](https://github.com/Halumar/contracts/security) of this repository. Please include:

- the affected contract version and the schema, message, rule or endpoint concerned,
- what an attacker could do, and from where (home network, a paired device, the internet),
- the steps to reproduce, ideally with a short proof of concept.

Never send real access tokens, passwords, pairing PINs, QR codes or backups. Replace them with
placeholders.

We confirm your report, keep you informed about the assessment and the fix, and agree with you on
when and how the issue is disclosed.

## Supported versions

Security fixes are released for the latest contract version only (currently `v1.0.0`).

## Scope

In scope:

- the contract itself: a schema, rule, resolution step or enforcement description that lets a device
  get more than its profile and boundaries allow, or that leaks data to a device that should not see it;
- the reference tools (`tools/*_ref.py`) and the known-answer vectors, where they disagree with the
  documented behavior;
- the code generator, where generated models decode or validate differently from the schemas.

Problems in the running hub, integration or apps are welcome here too; we forward them.

The documents say where a rule is only followed by the app (enforcement `app`) and that Home Assistant
lets every user read every entity. That a person with their own Home Assistant access can see or do
what such an app rule hides is the documented limit, not a vulnerability
([docs/enforcement.md](docs/enforcement.md)).

## Out of scope

Problems in Home Assistant itself or in other apps and integrations belong to their projects, for
example the [Home Assistant security policy](https://www.home-assistant.io/security/).
