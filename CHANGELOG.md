# Changelog

All notable changes to the contract are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the contract uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] – 2026-11-26

First public release of contract 1.0.0 (protocol version 1), for hub and integration 2026.12.0.
Earlier development versions were not published.

### Protocol

- REST API of the hub (OpenAPI 3.1) with security per operation, and the hub WebSocket (AsyncAPI 3.0)
  with handshake, heartbeat, close codes, limits and broadcast audiences.
- JSON Schemas for every WebSocket message, the client configuration, the Bonjour TXT record, pairing and
  onboarding links, mirrored Home Assistant entities and the integration API.
- A protocol version with a compatibility rule: a hub supports at least the two previous protocol
  versions; apps that are too old get `upgrade_required`.
- Machine-readable error reasons for authentication, pairing, setting up devices and guest invitations.
- Golden fixtures, including expected-invalid cases, and known-answer vectors for the compliance
  signature, the settings PIN and the onboarding seal.
- Stable notification ids, also for broadcasts, so a retried or handed-over notification is never
  delivered twice.

### Profiles and rules

- One profile per device with a shared rule catalog; suggestions that are copied, never changed by an
  update; per rule "fixed" or adjustable per device, also until a given time.
- Three boundaries, guest access, parental controls and Hub only, that only restrict.
- Resolved rules with value, source, reason and enforcement for every device; a reference resolver and
  shared test vectors.
- Access hours and an access switch in Home Assistant; babysitter and house sitter profiles; early
  access on request.
- Setting up a new device from a paired device with a QR code or a code, without handing on more rights
  than the setting-up device has; guest invitations.
- The family manager right for parents: kids rules per child, releases, children's requests.
- Parental controls are a Pro feature of the app on the child's device: every kids rule carries `pro`.
  Without Pro the child's device shows a notice and controls nothing; a rule is never dropped.

### Enforcement in Home Assistant

- One Home Assistant user per paired device, created and removed by the integration.
- Remote access as a profile rule, enforced through the device user's "local only" flag.
- The rule "Home Assistant access" (`control_path`) with three values: Hub only, Checked, Direct.
  On Hub only the device gets no Home Assistant key; it reads and switches only through the hub,
  which serves only what its profile allows, including camera still images and media artwork. With
  remote access it gets a read-only key, with which it can read every state in Home Assistant.
  Guests, babysitters, house sitters, children and the Kids' room panel start on Hub only;
  Adult, Wall panel and TV on Checked; Parents on Direct. Apple TV,
  Android TV and watches never run without a key.
- The checked control path: a read-only device user that switches only through the integration action
  `<ns>.control`, which checks the device's rules with a rule snapshot from the hub, also while the hub
  is unreachable.
- Event taxonomy, Home Assistant events `<ns>_event` and `<ns>_alarm`, and notifications at events.

### Devices

- Rule platforms for iPhone, iPad, Apple TV, Apple Watch, Android phone, Android tablet (also as a wall
  panel) and Android TV. The protocol also provides for Wear OS watches (`wearos`) and a web app
  (`web`); apps for them are planned and do not exist yet.
- Wall panels and status sensors of every device in Home Assistant; tag links and open links.
- Setting up a device from a paired phone or tablet, with the client secret sealed by HPKE; devices sign
  themselves off when they are reset (`client_leave`), and the hub removes them and their Home Assistant
  user at once.
- Per-entity tile settings and contract data for allowed settings and curated icons.

### Tools

- Model generator for Python, TypeScript, Swift and Kotlin with tolerant decoding and strict validation.
- Validator for schemas, fixtures, OpenAPI, AsyncAPI and the namespace; brand definition and brand lint;
  public text lint with optional rule packs.
