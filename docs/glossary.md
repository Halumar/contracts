# Glossary

Terms used across these documents, with the file that defines them. The German UI label is given in
parentheses where it helps. `<ns>` is the technical namespace `halumar`.

## Parts

**Hub.** The Home Assistant app (add-on). It pairs devices, holds profiles and rules, resolves them and
checks the rules marked `hub`. It stays on the home network.

**Integration.** The Home Assistant custom integration. It creates one Home Assistant user per
device, sets that user's group and "local only" flag, provides the action `<ns>.control` and decides
with the rule snapshots it received from the hub ([enforcement.md](enforcement.md)).

**App.** A Halumar app on a device. Platforms (`$defs/platform` in the protocol, `platforms` in the
catalog): `ios` (iPhone), `ipados` (iPad), `tvos` (Apple TV), `watchos` (Apple Watch), `android`
(Android phone), `android_tablet` (Android tablet, also as a wall panel), `android_tv` (Android TV
and Google TV). The protocol also provides for Wear OS watches (`wearos`, like `watchos`) and a web app
(`web`); apps for them are planned and do not exist yet. `web` has no profile rules and no default profile. Phone, tablet, TV and watch in the docs mean both platforms of that class.

**Admin UI.** The editor of the hub, opened from the Home Assistant sidebar.

## Devices and profiles

**Device (client).** A paired app installation. It has a platform, an access kind, exactly one
profile, optionally an own area and device adjustments.

**Access kind.** `member` or `guest` (`$defs/device_access`). Set when the device is paired, never
changed. A guest always has an expiry (`expires_at`).

**Pairing.** Connecting a new device to the hub with a PIN from the admin UI or through the
integration ([protocol.md](protocol.md)).

**Setting up a device** (onboarding). Adding a new device from a device that is already paired, with a
QR code or a 6-digit code ([setup.md](setup.md)). The setting-up device chooses the kind and the
profile.

**Set up by.** The device that set up another one (`set_up_by`). The admin sees its id; the new device
sees only its name and method.

**Profile.** A named set of rule values. Every device has exactly one; a hub holds at most 50
(`limits.max_profiles`). Created empty, from a suggestion or from a device ([profiles.md](profiles.md)).

**Profile kind.** One of `person`, `child`, `panel`, `tv`, `guest`, `house_sitter`, `babysitter`
(`$defs/profile_kind`, catalog `profile_kinds`). The kind groups profiles for setting up devices and
changes no rule by itself. `guest`, `house_sitter` and `babysitter` devices are set up with guest
access. `child` does not imply parental controls.

**Set-up kinds.** The profile kinds a device may set up, `setup_devices.kinds` of the rule "Set up new
devices". Only profiles of kind `person` can have this rule ([setup.md](setup.md)).

**Suggestion** (Vorschlag). A ready-made profile in `data/profile-suggestions.json` (14 of them). Adding
one copies it; an update of the hub never changes an existing profile. Each has a `version`; a newer
shipped version shows "new version of the suggestion" and is taken over only on request.

**Starter.** The five suggestions created at the first start of the hub (Adult, Child, Guest, Wall
panel, TV). Adult, Guest, Wall panel and TV become the default profiles; Child is created but
is no default.

**Default profile.** The profile a new device gets when nobody picks one: one slot per platform
(`ios`, `ipados`, `tvos`, `watchos`, `android`, `android_tablet`, `android_tv`, `wearos`) and one
for `guest`.

**Own area.** One area per device (for example the room of a wall panel). Rules can refer to it
(`areas.own_area`, `panel_start` mode `own_area`); a missing own area never opens more.

## Rules

**Rule catalog.** `data/profile-rules.json` (`catalog_version` 10, 49 rules). Each rule has a key, a
group, a type, a default, values from strict to loose (`order`), platforms, a security class,
boundaries, enforcement and labels in German and English.

**Rule.** One entry of the catalog, for example `remote_access` or `kids_quiet_hours`.

**Rule group.** The section of the editor: Access, When away, Areas & controls, Kids rules,
Features, Home screen, Display, Wall panel, Location (catalog `groups`).

**Security class.** `critical`, `sensitive` or `normal` (`$defs/rule_security`). Decides what falls to
the strictest value when a guest's access expires and what a setting-up device may hand on.

**Fixed** (Fest). A checkbox per rule in a profile: no device adjustment possible. A rule decided by a
boundary is fixed as well. `kids_exceptions` is always fixed.

**User's choice** (Am Gerät wählbar). For comfort rules (`user_choice_allowed`): the person at the
device decides; the profile value is the starting value. `locked` is true when the value is not the
user's choice.

**Device adjustment** (device override). A change of one rule that is not fixed, for one device,
permanent or until a time (`schemas/common/device-override.json`). One adjustment per device and
rule.

**Temporary adjustment.** A device adjustment with `expires_at`, chosen with a preset (`1h`, `today`,
`tomorrow_morning`, `7d`) or a date; between 5 minutes and 365 days ahead. While it runs, the
resolved rule carries `then`, the value after it ends.

**Boundary** (Grenze). One of three restrictions over all profile values (`$defs/rule_boundary`):
**guest access**, **parental controls** and **Hub only**. A boundary only restricts, and no adjustment
beats it. The one exception is `platform_needs_key`: on a TV or a watch Hub only becomes Checked.

**Guest access** (Gastzugang). The boundary of a device with access kind `guest`. It switches off,
among others, setting up devices, the watch, wall panel mode and quick access, hides the app
settings and caps Home Assistant access at Checked. It does not cap remote access. When the access
expires, the hub rejects the device.

**Parental controls** (Kindersicherung, `child_protection`). A profile switch and the second
boundary. Every action of such a device is checked: by the hub where it is reachable, otherwise,
when the device holds a key, through `<ns>.control` of the integration. Home Assistant access is at
most Checked (children start on Hub only); the watch is off unless the kids rule `kids_watch` is on;
the kids rules apply. The app on the child's device needs Halumar Pro.

**Hub only** (Nur über den Hub, boundary `hub_only`). The boundary of a device whose effective
`control_path` is `hub`. While the device holds no Home Assistant key (no remote access) it caps
`quick_access` and `watch` at off (reason `boundary_hub_only`); remote access lifts it.

**Hub path.** How a device on Hub only or with parental controls reads and switches: through the hub
(`state_subscribe`, `history_get`, `forecast_get`, `camera_image_get`, `media_image_get`, `control`),
which serves only what the profile allows ([enforcement.md](enforcement.md#7-devices-on-the-hub-path)).

**Kids mode.** The app's session on a device with parental controls ([protocol.md](protocol.md#kids-mode)).

**Kids rules** (Kinderregeln). The rules of the group `kids` (`kids_blocked_types`,
`kids_quiet_hours`, `kids_rate_limit`, `kids_rate_limit_all`, `kids_volume_max`, `kids_color_lock`,
`kids_requests`, `kids_exceptions`, `kids_watch`). They apply only with parental controls (catalog
`requires_child_protection`); without it they resolve to `not_applicable` with reason
`requires_child_protection`. The hub enforces them.

**Bedtime** (`kids_quiet_hours`). Weekly windows in which a child device may only reduce (switch off,
lower, mute).

**Family manager** (Familienverwaltung). A member device with the rule `family_manager`. It changes
the kids rules of its children as device adjustments of each child device, starts releases and answers
requests ([family.md](family.md)).

**Release** (Freigabe). A time-limited approval that lifts kids rules: the parent release of the admin
(`kids-override`) or a release of a family manager. The protocol names it release (`family_release`,
`release_until`); the apps show it as an approval.

**Request** ("Darf ich noch?"). A child asks for more time, an unlock or the end of a pause (rule
`kids_requests`). The first answer wins.

**Babysitter.** A profile kind with guest access. With the rule `babysitter_requests` its device
can answer the children's requests while its access is open and it is at home ([access.md](access.md)).

## Access and connection

**Remote access** (`remote_access`). Whether a device may use Home Assistant from outside the home
network. Enforced by Home Assistant through the device user's "local only" flag. Guests have it when
their profile says so; with parental controls it is a normal rule too. On Hub only it gives the
device a read-only key, with which it can read every state in Home Assistant
([enforcement.md](enforcement.md#7-devices-on-the-hub-path)).

**When away** (`remote_control`). The rule that sets per domain, device class or entity what a device
may do on the external route: `control`, `view` (only the safe direction, for example lock) or
`hidden`. Not applicable without remote access.

**Route.** How a call reaches Home Assistant: `local`, `external` (Home Assistant Cloud or a public
address) or `unknown`, treated like external (`$defs/control_route`). The integration decides the
route the way Home Assistant does; the app does not declare it.

**Home networks.** Address ranges that count as local: built-in private ranges plus up to 10 ranges
the admin adds ([protocol.md](protocol.md#home-networks)).

**Access hours** (Zugangszeiten, `access_hours`). Weekly windows in which a device has access at all.
Outside, the device stays paired but sees and controls nothing ([access.md](access.md)).

**Access switch** (Zugang, `switch.<ns>_<name>_access`). A switch per device in Home Assistant, for the owner's own automations.
Access needs both: the schedule allows it and the switch is on.

**Early access.** A time-limited opening of a device's access after it asked and someone said yes
(rule `access_requests`).

**Remote PIN.** A PIN set by the admin for a profile or a device. With `app_settings = pin` the app
settings open only with it. Stored only as a hash.

## Enforcement

**Enforcement.** Who makes a rule hold, per resolved rule (`$defs/rule_enforcement`):
`ha` (Home Assistant itself, shown as "Enforced"), `hub` (the hub checks every request, "Enforced"),
`ha_control` (operating is enforced in Home Assistant, hiding only in the app, "Control enforced"),
`app` (the app follows it, "Applies in Halumar"; someone with their own Home Assistant access is not
bound by it).

**Control path** (Zugang zu Home Assistant, `control_path`). Whether a device holds a Home Assistant
key and how it switches: `hub`, `checked` or `direct`. Home Assistant itself knows only `checked` and
`direct` (`$defs/control_path`); `hub` is `checked` there.

**Hub only** (Nur über den Hub, `hub`). The device gets no Home Assistant key (with remote access a
read-only one) and reads and switches through the hub. Rules with `enforcement_with_hub_path`
(`control_path`, `access_hours`, `areas`, `location`) then report `hub`. Guests, babysitters, house sitters,
children and the Kids' room panel start on it; Adult, Wall panel and TV start on Checked, Parents on
Direct.

**Checked path** (Geprüft). The device's Home Assistant user is in the read-only group and can switch
only through `<ns>.control`; it can read every state. Guests and devices with parental controls use at
most this path. Rules with `enforcement_with_checked_path` (`access_hours`, `remote_control`, `areas`,
`location`) then report a stronger enforcement.

**Direct path** (Direkt). The device's Home Assistant user is a normal user and switches directly; the
rules about what to show and operate are then enforced by the app only.

**`<ns>.control`.** The integration action through which checked devices switch. It checks the
allowlist, the entity, access, the device's snapshot, groups, scene and script targets and the kids
rules, in that order, and answers a reason per entity ([enforcement.md](enforcement.md#2-the-action-nscontrol)).

**Allowlist.** `data/control-allowlist.json`: which actions and data fields `<ns>.control` accepts per
domain.

**Rule snapshot.** The resolved rules of one device in the form the integration needs
(`schemas/common/enforcement-snapshot.json`), with a `rules_hash`. Pushed by the hub, stored by the
integration, used while the hub is unreachable.

**Resolved rules** (effective rules). The result of resolution for one device: per rule `value`,
`source`, `reason`, `locked`, `fixed`, `user_choice`, `expires_at`, `then`, `enforcement`
(`schemas/common/effective-rule.json`). The apps get those that apply in `client_config.rules`.

**Source and reason.** Where a resolved value comes from (`$defs/rule_source`: `default`, `profile`,
`device`, `boundary`, `prerequisite`, `not_applicable`, `access_expired`) and the text code shown for it
(`$defs/rule_reason`, table in [profiles.md](profiles.md#reason-codes)).

**Not applicable.** A rule that does not apply to a device (platform, profile kind, missing parental
controls, no remote access, location off). Its value is `null` and it is not sent to the app.

## Features

**Quick access** (`quick_access`). Everything a device operates or shows outside the app: widgets,
controls, Siri and Shortcuts, and on Android home screen widgets, quick settings tiles and device
controls. Levels per entity: `off`, `status`, `control` ([protocol.md](protocol.md#quick-access-widgets-controls-siri)).
Platforms of the rule: iPhone, iPad, Apple Watch, Android phone and Android tablet; the catalog also lists `wearos` for the planned Wear OS app.

**Safety entities.** Alarm panels and smoke, carbon monoxide, moisture and gas sensors (catalog
`safety_entities`). They are at least visible from away, and their critical notifications are never
hidden by a profile.

**Wall panel mode** (`kiosk`). A tablet or TV that shows a fixed start view. Rule platforms: iPad,
Apple TV, Android tablet, Android TV ([panel.md](panel.md)).

**Pro.** A flag on rules of the catalog (`pro`). The app offers a rule marked `pro` only with Pro; the
hub shows a hint and does not check it. For the kids rules it means the app on the child's device works
only with Pro and without Pro controls nothing; it never means a rule is dropped.

## Versions

**Contract version.** The SemVer version of this repository (`VERSION`), tagged `v<version>`.

**Protocol version.** One integer (`protocol_version`) for the whole hub protocol. Contract 1.0.0 is
protocol 1. It increases only for changes an older app cannot handle ([protocol.md](protocol.md#protocol-version)).

**Catalog version.** `catalog_version` in `data/profile-rules.json` and
`data/profile-suggestions.json`. It changes with the rule catalog.

**Additive change.** A new optional field, message type or enum value. Clients decode tolerantly, so it
does not raise the protocol version.
