# Protocol notes

Rules that span several schemas. The schemas, the OpenAPI and AsyncAPI documents and the fixtures are
authoritative; this page explains how the pieces fit together. The flow of one Home Assistant user per
device is described in [per-device-users.md](per-device-users.md).

## Protocol version

One integer, `protocol_version`, covers the whole hub protocol (WebSocket, the REST calls of the apps,
Bonjour TXT, deep link). It starts at **1** and only increases for changes an older app cannot handle.
Additive changes (new optional fields, message types, enum values) do not increase it, because clients
decode tolerantly. The contract version (SemVer) and the protocol version are separate: contract 1.0.0
is protocol 1.

| Where | Fields |
|---|---|
| App to hub: `auth`, `pair` | `protocol_version`, `platform` (`ios`, `ipados`, `tvos`, `watchos`, `android`, `android_tablet`, `android_tv`, `wearos`, `web`), `app_version` (required); `app_build`, `device_model` (optional) |
| Hub to app: `auth_ok`, `pair_ok`, `upgrade_required`, `GET /api/health` | `protocol_version`, `min_protocol_version`, `min_app_version` (per platform) |
| Bonjour TXT | `pv`, `pv_min` (strings) |

**Platforms.** One value per device class, Apple and Android side by side: phone `ios` /
`android`, tablet `ipados` / `android_tablet` (also as a wall panel), TV `tvos` / `android_tv`
(Android TV and Google TV), watch `watchos` / `wearos`, plus `web` (the protocol provides for Wear OS watches
and a web app; apps for them are planned and do not exist yet). Every Android class gets the
profile rules, default profile and set-up kinds of its Apple counterpart (`data/profile-rules.json`
`platforms`, `data/profile-suggestions.json` `default_for`; `tools/profile_rules.py` checks the
pairs). The set of
platforms is fixed in protocol 1; a new platform is a protocol change, because rule platforms
and default profile slots depend on it. Apps decode unknown platform values tolerantly (device lists,
`onboard_info`) and show a generic device.

**Compatibility rule.** The hub serves every app protocol version from `min_protocol_version` up to
its own `protocol_version`, and `min_protocol_version ≤ max(1, protocol_version − 2)`: a hub always
supports at least the two previous protocol versions, so apps may lag up to two breaking hub releases
behind (App Review, delayed updates). An app that is newer than the hub speaks the hub's protocol as
long as it still supports it, otherwise it asks the user to update the hub. `min_app_version` is an
additional lower bound per platform for known faulty app builds and ships with the hub release.

**App too old.** A missing or too low `protocol_version`, or `app_version` below
`min_app_version[platform]`, is answered with `upgrade_required` (`reason`, readable `message`) and
close code **4426**. The pairing is kept and a PIN is not used up. The app does not reconnect in a
loop; it shows a localized update notice and tries again after an update or on request. Malformed
client info (unknown platform, invalid version) is answered with `pair_error` or `auth_error`.

**Admin view.** The hub stores the client info per device (`platform`, `app_version`, `app_build`,
`device_model`, `protocol_version`, `update_required`) and keeps an activity feed per device
(`GET /api/pairing/clients/{client_id}/activity`, ring buffer of 100, broadcast `device_activity`):
`paired`, `connected`, `disconnected`, `app_updated`, `upgrade_required`, `token_issued`,
`token_rotated`. Service calls of a device go directly to Home Assistant with the device's own user
and appear in the Home Assistant logbook, not in the hub.

## Error reasons

`auth_error` and `pair_error` always carry a machine-readable `reason`
(`common/defs.json#/$defs/auth_error_reason`, `#/$defs/pair_error_reason`); `message` is English text
for logs. Apps decide and localize only by `reason` and treat unknown values cautiously
(`auth_error`: keep the pairing and retry with backoff; `pair_error`: like `pin_invalid`). Only
`invalid_secret` means "this device is unknown to the hub, pair again"; a deleted device still gets
`client_removed`.

| Message | `reason` |
|---|---|
| `auth_error` | `invalid_secret`, `revoked`, `guest_expired`, `rate_limited`, `invalid_client_info` |
| `pair_error` | `invalid_request`, `invalid_client_info`, `pin_invalid`, `pin_expired`, `too_many_failures`, `rate_limited`, `already_authenticated`, `connection_expired`, `platform_not_allowed` |

## Profiles

Every device has exactly one **profile**. The hub resolves the rules of the profile, the device adjustments and the boundaries (guest access,
parental controls, Hub only) and sends the apps only the result: `client_config.access`, `client_config.profile`
and `client_config.rules` (one entry per rule with `value`, `source`, `reason`, `locked`, `fixed`,
`user_choice`, `expires_at`, `then`). The apps never resolve anything themselves. Catalog:
`data/profile-rules.json`; suggestions: `data/profile-suggestions.json`; semantics, resolver, admin API
and reason codes: [profiles.md](profiles.md); executable reference: `tools/profiles_ref.py`; shared test
vectors: `fixtures/profiles/resolve`, `fixtures/profiles/expiry`.

The profile model has the rule group “When away” (`remote_control`, applied by the apps on the external route), an
`enforcement` label per rule (`ha`/`hub` = enforced, `app` = applies in the app), the rule
`notification_level` (critical and safety notifications are never suppressed; no delivery promise) and an
optional remote PIN in the profile (`settings_pin_source`).

Access hours, an access switch per device and the kind babysitter: [access.md](access.md).

Every profile has a **kind** (`$defs/profile_kind`: guest, child, panel, tv, house_sitter, babysitter, person;
`client_config.profile.kind`) and the rule `setup_devices {enabled, kinds}` (“Set up new devices”, only for
kind person): see [setup.md](setup.md).

**Home Assistant key of a device.** Every paired device has its own HA user with one token. The
admin API and the integration status show `ha_token_status` (`pending` = the integration has not created
the user and delivered its token yet, `active` = user and token are stored on the hub) and `has_ha_token`
(= the device holds a key that Home Assistant still accepts: a delivered key, or a withdrawn key whose
replacement the integration has not confirmed yet; false when it holds none). The paired client also
carries `control_path`, the effective Home Assistant access after the platform mapping; `null` means the
hub could not resolve the device's rules (the cause is in the hub's log). `remote_allowed` is then `null`
too: access, remote access and key level are unknown, and `has_ha_token` only says whether a token exists
at all. The integration status keeps `remote_allowed` a boolean and carries `false` for such a device (its
HA user stays `local_only`). The rule `control_path` decides
whether the device holds a key (`holds_key`): on `checked` and `direct` always, on `hub` (“Hub only”) only
the read-only key of its device user with effective remote access
([enforcement.md §7](enforcement.md#7-devices-on-the-hub-path)); without it `has_ha_token` is false and
the hub keeps the token for its own calls on the hub path. Whenever a device stops holding a key the hub
rotates the token, so a key the app held before stops working as soon as the integration has removed it
(until then it keeps working, and the hub keeps trying; log entry `ha_key_withdrawn`, docs/log.md).

The rule `control_path` adds enforcement in Home Assistant: devices with the checked path
have a read-only HA user and switch only through the integration action `<ns>.control` (rule snapshot per
device from the hub, allowlist `data/control-allowlist.json`, client_config `ha_enforcement`). There are also
the event taxonomy `data/events.json`, the HA events `<ns>_event`/`<ns>_alarm` and the integration event
log. Details, transport and the app's “integration not responding” state: [enforcement.md](enforcement.md).

## Area visibility (tags)

The visible areas are the profile rule `areas` (`all`, or `selected` with area ids, tags and
the device's own area). The hub derives the device's tags from the effective rule (`all` → `["*"]`,
`selected` → its tags plus one pin `area:<id>` per area) and keeps using them internally and towards the
integration (`status.response`, `POST /api/integration/clients/{id}/tags` and `guest_tags` write a device
adjustment of `areas`). The tag semantics (`common/defs.json#/$defs/client_tags`) decide which areas a
device sees (`get_areas`, `get_area`):

| Device | Tags | Sees |
|---|---|---|
| Member | `[]` | all active areas |
| Member | `["upstairs", …]` | active areas with one of these tags |
| Guest | `[]` | **no** area (fail closed) |
| Guest | `["*"]` | all active areas (explicit choice) |
| Guest | `["guest", …]` | active areas with one of these tags |

`"*"` is reserved: as an area tag (`$defs/area_tags`) and as a tag in the rule `areas` the hub answers
422. User interfaces never show `"*"` as a tag,
but as "All areas". The filter is a convenience in the apps, not a security boundary in Home Assistant:
the device's Home Assistant user can read states directly.

## Tile settings

Every entity placement (`area_entities` row) carries `tile` (`schemas/common/tile-settings.json`):
`icon`, `variant`, `secondary`, `tap_action`, `hold_action`, `confirm`, `accent`, `hidden_on`. The
display name stays `display_name` (1 to 100 characters, no control characters, empty means the Home
Assistant name). Everything is optional; `{}` is the default. What is allowed per domain is defined
only in `data/tile-capabilities.json` (row of the domain, otherwise `_other`); the hub rejects
anything else with 422 `tile.<reason>`. Writing: `PUT /api/areas/{area_id}/entities/{entity_id}`
(`schemas/rest/area-entity-update.request.json`; `tile` replaces the whole object, `tile: null`
resets it, admin only). Afterwards `entity_updated` with `changed` goes to admin sessions, the
integration and every app that may read the area.

- The hub always delivers `tile` to every device; an app may show the default tile instead (guests
  always do).
- A script or scene as tap action is the admin's decision: the `run` target does not have to be
  visible to the device. The hub only checks that it exists in Home Assistant and belongs to an
  allowed domain (`run_targets`); service data is never accepted.
- Not available when the app runs without a hub.
- `hidden_on` hides a tile on `phone`, `tablet` or `tv` (every platform of that class); the app filters.

Fallbacks in the app: `tile` missing or `{}` gives the default card; an
unknown enum value or a value not allowed for the domain falls back to the default of that field; a
variant that does not fit the size (`slider` narrower than 2, `large` at 1×1) becomes `compact`; a
missing `sf:` symbol falls back to `icon_svg`, then to the domain symbol; an `mdi:` icon with a pair in
`tile-icons.json` and an OS at or above `sf_min_os` uses the SF Symbol; a `run` target that is missing
from the Home Assistant states or `unavailable` falls back to `default`; a missing `secondary`
attribute drops the line; `hidden_on` with the device's own form factor hides the tile (a section
without visible tiles is dropped). The accent color applies only in the active state; the state is
always visible as text.

## Setting up a device from a paired device

Every new device can be set up from a device that is already paired: it shows a one-time QR
code with a 6-digit code instead of entering the PIN, and the setting-up device (iPhone, iPad, Android
phone or tablet with the rule `setup_devices`) decides **what** it becomes: kind (child, wall panel, TV,
guest, house sitter, babysitter, person) and profile. **The PIN stays the fallback: pairing always works without
another device.** The contract is platform-neutral, also across vendors. `onboard_start` accepts every app
platform (`ios`, `ipados`, `tvos`, `android`, `android_tablet`, `android_tv`; a watch (`watchos`,
`wearos`) through its phone, which opens the session with the watch's public key, confirms it on its own
connection and passes the sealed secret on to the watch, see [Watches](#watches-access-through-the-phone)); only `web` gets
`onboard_error {platform_not_supported}`. Flow, questions per kind, escalation check, family managers,
limits and “Set up by me”: [setup.md](setup.md). Short form (AsyncAPI section “Setting up a device from a paired device”):

1. Waiting device: ephemeral X25519 key pair, `onboard_start {public_key, client_name, <client info>}`
   over TLS only (port 8100, pinned to the Bonjour fingerprint), otherwise `onboard_error {tls_required}`.
   Answer: `onboard_session {session_id, hub_id, code, expires_in: 300, expires_at}`. The connection stays
   open until the session ends.
2. It shows the QR code (`deep-link/onboard-link.json`):
   `https://<website>/pair-tv#hub=<iid>&fp=<32 hex>&s=<session_id>&k=<public_key>[&n=<name>]`
   (development: `halumar://pair-tv#…`; one path for all waiting devices) and under it the code
   (“428 913”). Neither contains a secret. The fingerprint is not shown; it is checked automatically.
3. Setting-up device: QR code → compares `fp` with its own pin (otherwise aborts) and sends
   `onboard_lookup {session_id, public_key, hub_id}`; code → `onboard_lookup {code}` (it trusts its own
   pinned connection; the waiting device gets the secret only over its own pinned TLS connection, as with
   the PIN). Answer `onboard_info` with `grant` (`common/setup-grant.json`); the waiting device gets
   `onboard_claimed`. The app asks the questions of the chosen kind and sends `onboard_confirm` (kind,
   profile_id and the answers) or `onboard_decline`.
4. Hub: checks the permission, kind, profile (never stronger than the setting-up device), areas, expiry
   and managers; a validation error keeps the session open. It creates the device with the profile and
   the choices as device adjustments, records `set_up_by`, provisions its own HA user (`provision_client`),
   sends the waiting device `onboard_ok` with the client secret sealed by HPKE (RFC 9180 Base,
   X25519/HKDF-SHA256/ChaCha20-Poly1305, `info = hub/onboard/v1`, `aad = session_id`; vectors in
   `fixtures/crypto/onboard-seal-vectors`), which authenticates the connection, and the setting-up device
   `onboard_confirm_ok`. From here on it continues as after `pair_ok`.

**Area pins.** The client tag `area:<area_id>` matches exactly that area, regardless of its tags. A
device with pins sees the pinned areas plus the areas matching its other tags. A pin of a deleted area
matches nothing (fail closed, never "all"). The prefix `area:` is reserved as an area tag (422). Apps
and the admin UI show the area name instead of the pin.

**Permission.** The profile rule `setup_devices {enabled, kinds}` (only profiles of kind person,
never guests or devices with parental controls), read from `client_config.rules.setup_devices`. Setting up
a watch additionally needs the rule `watch` of the phone. There is no additional confirmation in the
admin UI. A child's phone may set up its watch only with an adult's confirmation (setup.md “A child's
watch”).

**Security.** One-time, 5 minutes. A key or hub mismatch in lookup or confirm discards the session
(`session_invalidated`). Wrong codes are limited per setting-up device and on the hub
(`too_many_attempts`). Limits are in `x-limits` `onboard_*`. Admins see running sessions without their ID
or code (`GET /api/pairing/onboarding`, `DELETE …/{id}`, broadcasts `onboarding_started`,
`onboarding_ended`). Errors: `onboard_error.reason` (`$defs/onboard_error_reason`); treat unknown values
like `session_not_found`. Activity: `paired` with `method: onboard` and `confirmed_by`, `device_added` on
the setting-up device; audit entry `onboarding_confirmed`; log entry and event `device_set_up`.

## Guest invitations by members

Inviting guests needs the kind `guest` in the profile rule `setup_devices` (in the profile or as a
device adjustment, never for guests or devices with parental controls). The app reads it from
`client_config.rules.setup_devices` and only then shows "Invite guest". Flow (AsyncAPI section “Guest invitations by members”):

1. Member: `get_setup_grant {purpose: invite}` lists the guest profiles it may give (never more than its
   own rights) and whether remote access can be chosen. `guest_invite_create {profile_id?, owner_label?,
   expires_at?, remote?}` returns
   `guest_invite {invite_id, pin, deep_link, url, expires_in: 300, expires_at, grant}`. The invitation
   is its **own guest PIN** (one-time, 5 minutes) next to the single admin PIN; a new invitation from
   the same device replaces its open one (`guest_invite_ended {replaced}`). `deep_link` is the normal
   pairing link (`deep-link/pairing-link.json`, with `fp` when a certificate exists); the app shows it
   as a large QR code, with the PIN and the remaining time.
2. Guest: pairs with the normal `pair` (QR code with the camera or PIN in the app) and gets exactly what
   `grant` shows: the chosen guest profile (its areas), the chosen end (at most 90 days; without a choice
   the default guest duration from pairing) and remote access. A guest profile without any area rejects
   invitations (`no_guest_areas`).
3. Member: receives `guest_invite_ended {result}` on all connections: `paired` with `client_id` and
   `client_name`, otherwise `expired`, `cancelled`, `revoked`, `replaced` or `invalidated`.

**What the member may do:** invite; withdraw their **own** open invitation (`guest_invite_cancel`); see
and remove the guests in “Set up by me” (`get_set_up_devices`, `set_up_device_remove`). Everything else
about the guest (areas, extending the access, permissions) stays with the admin.

**Security.** Permission per device, never for guests. At most one open invitation per device, 10
invitations per hour per device and 20 open invitations in total (`x-limits` `guest_invite*`,
otherwise `rate_limited`). Wrong PINs count like those for the admin PIN (budget per source IP; a PIN
is invalidated after repeated failures from several source addresses). Removing the permission or
deleting the device ends its open invitation (`revoked`). Admins see open invitations without the PIN
(`GET /api/pairing/guest-invites`, `DELETE …/{id}`, broadcasts `guest_invite_opened`,
`guest_invite_closed`) and `set_up_by` on the guest. Activity: guest
`paired {method: invite, invited_by}`, member `guest_invited`; audit entries `guest_invite_created`,
`guest_invite_cancelled`, `guest_invite_paired`. Errors: `guest_invite_error.reason`
(`$defs/guest_invite_error_reason`); treat unknown values like `not_permitted`.

## Remote access

Remote access is the profile rule `remote_access` (profile value, device adjustment, possibly
temporary; guests too when their profile allows it; with parental controls too). On Hub only it gives the
device a read-only key for use away from home: with it the device can read every state in Home Assistant from
anywhere, including what its profile hides, and switches only through `<ns>.control`, see
[enforcement.md §7](enforcement.md#7-devices-on-the-hub-path). The hub sends the effective value to the integration
as `remote_allowed` (HA user `local_only`) and uses Home Assistant's own remote access (Home Assistant
Cloud or a reverse proxy). The hub stays on the home network. When a temporary adjustment ends, the hub
switches the HA user back (`update_client_identity`) and sends `client_config_updated`.

- **External address.** The integration reports what Home Assistant itself returns (`get_url` without
  internal URLs: `external_url`, otherwise the Home Assistant Cloud address, otherwise `null`) to
  `POST /api/integration/ha-url` (`schemas/integration/ha-url.{request,response,error}.json`) at start
  and on every change. The hub only accepts Home Assistant's own `external_url` or a Home Assistant
  Cloud address (otherwise 422 `url_not_allowed`). A URL entered in the hub
  (`PUT /api/settings/ha-urls`) takes precedence over the reported one (`ha_url_detected`).
- **Who gets it.** `client_config.ha_url` is set only for devices with remote access, otherwise
  `null`, and the app then deletes a stored external URL. `sensor.<ns>_config.ha_url` is always `null`
  (every Home Assistant user can read the sensor). Switching remote access and URL changes send
  `client_config_updated`.
- **Token.** Granting remote access keeps the token; revoking it rotates the token
  ([per-device-users.md](per-device-users.md) §5.2). An admin rotation of a device with remote access
  that is away waits for its next hub connection, at most 72 hours (`rotate-token` 202 `pending`). If
  the token changed after the last hub contact, the compliance channel reports a signed
  `need_token_update` (see [Compliance status](#compliance-status)).

### Compliance status

The iPhone and iPad app polls the compliance view ([enforcement.md](enforcement.md#8-compliance-status-away-from-home))
while its Home Assistant sign-in fails outside the home network; the Android apps do not poll it. The
app acts only on a status whose signature it verified:

- `need_token_update`: the app stops connecting to Home Assistant, shows the state and asks again every
  30 minutes. It gets the new token from the hub on the home network.
- `deleted`: the app stops connecting to Home Assistant and shows the state. It keeps its pairing data;
  it resets only when the hub answers `client_removed` over its own authenticated connection.
- `compliant` or `unknown` (also a missing or invalid signature): the app lifts its own restriction and
  connects again; Home Assistant decides whether the token works.

## Home networks

Built in, every component treats loopback, link-local, RFC 1918 (10/8, 172.16/12, 192.168/16) and
fc00::/7 as the home network. The admin can add further networks (admin UI Settings > Network,
`GET/PUT /api/settings/home-networks`, `schemas/rest/home-networks.json`), default empty, max 10:
CIDR plus optional name, only inside 10/8, 172.16/12, 192.168/16, 100.64/10 and fc00::/7 (public →
422 `home_network_public`). The hub normalizes (host bits cleared, networks inside another merged,
sorted) with the same rules as `tools/home_networks_ref.py` (vectors `fixtures/network/home-networks`).
Templates: Tailscale = `100.64.0.0/10` (+ optionally `fd7a:115c:a1e0::/48`), with the hint that mobile
networks use 100.64.x.x too (carrier-grade NAT); WireGuard and ZeroTier have no fixed range.

- **App** (`client_config.home_networks`): a host inside them counts as local: a pairing QR code or link
  naming it is accepted (the hub adds `hn` to the pairing link), a self-signed Home Assistant
  certificate of it may be pinned on first use while the home network is verified, and it counts as
  an internal route. The token rules for unencrypted connections stay: plain `http://`/`ws://` still needs the verified
  home network.
- **Integration** (`home_networks` in every rule snapshot, part of `rules_hash`): `<ns>.control` puts a
  caller from these networks on the local route (also for "When away"). Home Assistant's own
  `local_only` of a device user is not widened: a device without remote access is still refused by
  Home Assistant itself from 100.64.0.0/10.
- **Hub**: audit entry `home_networks_set`, then `client_config_updated` to every connected app and new
  snapshots for the integration.

## Quick access (widgets, controls, Siri)

"Quick access" (`quick_access`) is everything a device operates or shows outside the app: widgets
(Home Screen, Lock Screen, StandBy, CarPlay), controls (Control Center, Lock Screen,
Action button, Apple Watch through the iPhone) and Siri/Shortcuts; on Android home screen
widgets, quick settings tiles and device controls, with the same levels and the same
`<ns>.control` path. The name `widget` stays reserved for the area widgets (clock/text).

- **Level per entity** (`$defs/quick_access_level`): `off` (nowhere), `status` (state visible, a tap
  opens the app), `control` (operate without opening the app). The level belongs to the entity, not
  to a placement. Default and maximum per domain are defined only in `data/quick-access.json` (row of
  the domain, otherwise `_other`); non-critical devices can be operated by default.
- **Critical** are lock, alarm panel, valve, siren, automation and covers with `device_class`
  garage/gate/door: by default at most `status`; `control` only with `critical_ack` (otherwise 422
  `quick_access.critical_ack_required`). Widgets operate locks and alarm panels only in the safe
  direction (`safe_direction`: lock, arm without `code_arm_required`); unlocking and disarming always
  open the app with a confirmation. Garage doors and gates are status only in widgets and need an
  unlocked phone as a control. Camera, person and device tracker are always `off`.
- **Admin API:** `GET /api/quick-access`, `PUT /api/quick-access/{entity_id}`
  (`schemas/rest/quick-access.{request,response}.json`; `level: null` resets to the default). Per device
  through the profile rule `quick_access` (`off`, `status`, `control`).
- **Resolved per device:** `client_config.quick_access` (`enabled`, `max`, `sensor`, `entities` with
  the effective levels, `critical`) = min(entity level, domain maximum, device maximum), only for
  entities the device may read (areas/tags, `is_visible`). Guests always get `enabled: false`, and so does
  a device on Hub only without remote access (boundary `hub_only`: widgets need the device's own key).
  Changes
  send `client_config_updated`.
- **Check sensor** (`schemas/sensors/client-quick-access-sensor.json`,
  `sensor.<ns>_client_<slug>_<uid8>_quick_access`): the same content, readable with the device's Home
  Assistant token. Widgets and controls read it before every action and only perform what it allows; a
  missing sensor means "not allowed". A withdrawn release therefore applies at the next tap, even when
  the app is not running; a blocked device loses Home Assistant access at once (401).
- Not available when the app runs without a hub. The rule `quick_access` is marked Pro; only the app checks Pro.

## Hub path

A device is on the **hub path** when its profile has parental controls or its effective rule `control_path`
is `hub` (“Hub only”). It reads and switches through the hub wherever the hub is reachable; on Hub only
without remote access that is the only way (no Home Assistant key, `ha_token`, `ha_instance_id`,
`ha_enforcement` and `ha_url` `null`). Apps: `usesHubPath = profile.child_protection or
rules.control_path.value == hub` on a phone or tablet (a watch and a TV are never on the hub path, they
always use their key), `holdsKey = ha_enforcement != null or token_error != null` while access is open
(`token_error`: the key exists but is not usable yet; [enforcement.md §7](enforcement.md#7-devices-on-the-hub-path),
“Key in client_config”).
Details and the table of who reads what where: [enforcement.md §7](enforcement.md#7-devices-on-the-hub-path).

- **Switching:** `control` (WebSocket) or `POST /api/client/control` (bearer = device secret). Answers:
  `control_ok` (`adjusted` at the volume cap), `rule_blocked` (`reason`, `level`, `until`, `retry_after`,
  `limit`), `control_error` (`reason`). The hub checks access, scope and, with parental controls, the kids
  rules, then calls `<ns>.control` as the device's own HA user (logbook), which checks again.
- **Live states:** `state_subscribe` → a snapshot of every visible state, then `entity_state`. States are
  sanitized like `get_area`: no `access_token`, no GPS of people and trackers, and an `entity_picture`
  that carries a token is replaced by `attributes.hub_picture_id` (`$defs/hub_picture_id`): 16 hex
  characters, an HMAC with a secret of the hub over the picture link without its token. It is there exactly
  when Home Assistant has a picture, changes with a media player's artwork (a camera's stays the same), is
  no URL, gives no way to the link, the token or the image, and differs between hubs. The app asks
  `media_image_get` (or `camera_image_get`) when the marker appears or changes, and nothing without it.
- **Reading without a key:** `history_get {request_id, entity_id, hours}` (1–168) →
  `history {states: [{state, last_changed}], truncated}` for the sensor charts (recorder, significant
  changes, oldest first, at most 1000 points, evenly thinned out beyond) and `forecast_get {request_id,
  entity_id, forecast_type}` (`weather.*`; `daily`, `hourly`, `twice_daily`) → `forecast {forecast: [...]}`
  (`weather.get_forecasts`, at most 240 entries). Same visibility as `state_subscribe`; failures are
  `control_error` with the same `request_id`. `state_subscribe` also relays `sun.sun` when a weather entity
  is visible (day/night symbol, read only).
- **Still images:** `camera_image_get {request_id, entity_id, width?}` → `camera_image {request_id,
  entity_id, content_type, data_b64}` and `media_image_get` → `media_image` (artwork of a media player).
  The hub reads the image with its own access to Home Assistant, only for an entity in the device's
  scope, at most 2 MiB (JPEG, PNG, WebP or GIF, content type normalized: lower case, no parameters,
  `image/jpg` and `image/pjpeg` → `image/jpeg`); it follows no redirect and keeps no copy.
  - Order of the checks: a malformed request or a `request_id` of this device's still open request →
    `invalid_request`; not on the hub path → `not_hub_controlled`; access closed, an unknown entity, an
    entity of another domain or outside the scope → `not_visible`, the same answer each time and before
    Home Assistant is contacted or a kids rule is read; a request for the entity still open or a limit
    reached → `rate_limited` with `retry_after`; with parental controls a blocked device type
    (`kids_blocked_types`) → `rule_blocked {reason blocked}`; then Home Assistant (`ha_error`,
    `ha_unavailable`).
  - Limits per device (AsyncAPI x-limits `hub_image_*`): one open request and at most one per second per
    entity, at most 4 open requests, 20 images and 16 MiB per 10 s. These are maxima: a hub may enforce
    lower shares, for example of a hub-wide limit of open reads, and answer `rate_limited` earlier; clients
    honor `rate_limited` with `retry_after` at any time. A wall of 8 camera tiles refreshed
    every 5 s needs 16 images per 10 s, typically a few MiB; the budget keeps one device from flooding
    the hub or Home Assistant. A message with an image is at most 2 800 000 bytes; apps accept WebSocket
    messages of that size.
  - `width` (64–3840 px) is a best-effort hint. The hub passes `width` and `height = ceil(width·9/16)` to
    Home Assistant's camera proxy, which scales only JPEG images (with its libjpeg-turbo), only down and
    by the smallest of the factors 7/8 … 1/8 that keeps at least that size, so an image may come up to
    about twice as wide, and other formats come unscaled. The hub does not scale itself (it ships no image
    library). `media_image_get` has no hint: the media player proxy does not scale.
  - The device never gets a Home Assistant camera token, a signed image URL or any other URL, and live
    video is not part of the hub path. The app asks again while the tile or the detail view is visible;
    without an image it shows the domain icon.
- **Limits** per device: a new `state_subscribe` at most every 10 s, `history_get` and `forecast_get`
  together at most 10 per 10 s; beyond that `control_error {rate_limited, retry_after}` (AsyncAPI x-limits
  `hub_*`).
- Devices off the hub path get `control_error {not_hub_controlled}` and use Home Assistant with their own
  key.
- **Availability:** the hub path needs the hub; without the hub and without a key nothing can be read or
  controlled (fail closed).

## Kids mode

Kids mode is the profile switch **parental controls** (`client_config.profile.child_protection`).
Its rules are the profile rules `kids_*` (catalog group `kids`); the hub delivers them twice:
with source and reason in `client_config.rules`, and in the enforcement shape of
`common/kids-rules.json` in `client_config.kids` (`rules.profile` = the `kids_*` values,
`rules.areas`/`rules.entities` = the exceptions `kids_exceptions` with the own area resolved).

- **Rules** (`common/kids-rules.json`) on the levels profile → area → entity; a missing field inherits
  the more general level, `null` for `rate_limit`/`volume_max` turns it off. Building blocks: `blocked`,
  `blocked_types` (domain or `domain:device_class`, profile and area only), `quiet_hours` (windows per
  weekday, across midnight = start day, Home Assistant time zone, only reducing actions allowed),
  `rate_limit` (per entity and device, with a cooldown), `color_lock`, `volume_max`. An entity in several
  visible areas: every rejection wins.
- **Enforced by the hub and the integration:** a child device is on the hub path (above) and controls
  through the hub wherever it is reachable. Its Home Assistant access is “Hub only” by default and at most
  “Checked”. It holds a read-only key when it is on Checked or has effective remote access
  (`kids.away = ha`, `<ns>.control` with the kids rules of the snapshot,
  [enforcement.md §7](enforcement.md#7-devices-on-the-hub-path)); otherwise `ha_token` and `ha_url` are
  `null` (`kids.away = none`).
- **Admin:** the profile API of [profiles.md](profiles.md) (`/api/profiles`, assignment, adjustments),
  `POST /api/profiles/{id}/check` (rule test), `POST/DELETE …/kids-override` (release, lift pauses),
  `GET …/kids-status`. Switching parental controls on sets Home Assistant access to Hub only in the
  admin UI (a visible change); when a device stops holding a key the hub withdraws its token (rotation).
  A guest device never gets such a profile (422 `profile.guest_child_protection`). Remote access stays a
  normal profile rule that can be adjusted per device. Activity `rule_blocked` (throttled),
  `profile_changed`, `kids_override`.
- **Pro:** parental controls are a Halumar Pro feature, checked by the app on the child's device (the 8
  kids rules besides `kids_watch` carry `pro` like `kids_watch`). Without Pro the child's device shows a
  notice and controls nothing on every platform; the hub and the integration enforce the rules either way.
  No app treats a `pro` flag as “drop the rule”.
- **Apps** localize only by `reason` (child-friendly, countdown from `until`), hide blocked tiles and
  areas, and cap sliders by `rules`; the rules in `client_config` are for display only, the hub
  decides.

## Family manager

Details in [family.md](family.md). A member device with the effective
profile rule `family_manager` manages the kids rules of the child devices in its scope (device property
set by the admin) as device adjustments of each child device, starts releases, answers the children's
requests (`kids_request` → `family_request`, first answer wins) and reads their activity – at home over
the hub WebSocket, away through Home Assistant and the integration relay (`<ns>/family`,
`POST /api/integration/family`, `family_relay`). The hub checks every message (reference
`tools/family_ref.py`).

## Wall panel as a Home Assistant device

Details in [panel.md](panel.md). Apps report `battery_level`,
`battery_state`, `low_power` (independently of location) and `client_status.panel` (screen state,
backlight, capabilities). The hub decides which entities the integration creates (`clients[].panel_ha` in
`GET /api/integration/status`) and forwards commands from Home Assistant (`POST
/api/integration/clients/{id}/panel`) or the admin UI as WebSocket command `panel_command`; the app answers
`panel_command_ok` / `panel_command_error` with the same `id` within 5 s. Only Home Assistant admins and
automations operate panel entities; `<ns>.control` refuses entities of the integration itself
(`own_entity`).

Every app with a hub connection sends `client_status.panel`, also outside the wall
panel mode (`panel_mode` false: `screen` active/off = app in front or not, brightness only in front); every
device except watches and guests gets sensors in Home Assistant by its rule `panel_sensors`, control entities
only wall panels and TVs with `panel_remote`.

## Notifications while the hub is unreachable

Home Assistant keeps running when the hub stops (update, crash, stopped app). The integration then
delivers notifications itself and hands them to the hub afterwards; the hub stays the source of truth.

- **When.** `display_notification`, `clear_notifications` and `ack_notifications` fall back only when
  the hub does not answer: connection error, timeout or HTTP 502/503/504. Any other answer (4xx, 500)
  is the hub's and is reported to the caller.
- **Stable ids.** The integration chooses the UUID of every notification to one device and sends it as
  `notification_id` with `POST /api/integration/notify`; the same id again returns the existing
  notification (`duplicate: true`, not pushed again), an id of another device is 409.
- **Stable ids for broadcasts.** With `client_id: "all"` the `notification_id` is a broadcast id. The
  id of each device's notification is derived from it: UUIDv5 with the broadcast id as namespace and
  the device's `client_id` (lowercase text) as name (RFC 9562; Python
  `uuid.uuid5(uuid.UUID(broadcast_id), client_id)`; example: broadcast
  `6f1c2a4e-8b3d-4c5e-9f70-1a2b3c4d5e6f`, device `3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b` →
  `e58ba18c-8fa7-5d79-87b1-4e45eb94b7b9`). The hub creates the derived id for every active device
  except watches (below);
  a device that already has it counts in `duplicates` and is neither created nor pushed again. In the
  fallback the integration writes the same derived ids for each active device of its last status
  snapshot except watches, so a broadcast whose request timed out although the hub processed it is
  handed over as duplicates instead of a second notification.
- **Watches.** The fallback treats watches like the hub (`platform` and `set_up_by` of the status
  snapshot): `all` leaves them out, and a notification for a watch goes into the sensor of the phone
  that set it up, with the `notification_id` sent to the hub, so its handover is a duplicate, not a
  second copy. Without that phone the action fails and nothing is stored.
- **Sensor.** In the fallback the integration writes the device's notification sensor in the usual
  shape (`schemas/sensors/client-notifications-sensor.json`, same item shape) and lists the ids
  it has not handed over in `pending_handover`. The hub's own sensor update keeps those items (younger
  than 72 h, not in its database) until the handover, so the apps, which take the sensor as the
  removal authority, never lose a card.
- **Acknowledgement, clear.** `ack_notifications` during the outage marks the items as `delivered` in
  the sensor; queued ones are handed over as `delivered`, earlier hub notifications get a queued
  `POST /api/integration/notifications/ack`. `clear_notifications` empties the sensor at once and is
  sent to the hub later.
- **Handover.** Once the hub answers (next status poll), the integration hands the queue over in
  order: notifications with `POST /api/integration/notifications/handover`
  (`schemas/integration/notifications-handover.{request,response}.json`, 1–50 per call; `created`,
  `duplicates`, `skipped` with a reason), clears and acknowledgements through their usual endpoints.
  A new change never overtakes the queue. Limits as on the hub: at most 50 queued notifications per
  device, nothing older than 72 hours.

## Signing off a device (client_leave)

A device that resets itself or removes this home signs itself off first, so no paired device
and no HA user stay behind:

- The app sends `client_leave {client_id}` on its authenticated socket (members, child devices and
  guests; `client_id` must be its own, otherwise `error` and nothing changes) and waits for
  `client_leave_ok`, at most a few seconds. Then it wipes its data.
- The hub removes the device at once, like an admin deletion whose HA user goes immediately, but
  without a tombstone (the device has wiped itself): the pairing row goes, the integration removes the
  device's HA user (`deprovision_client`), open guest invitations of the device end, other live
  connections of the device close with 4001, admin sessions get `client_kicked {reason: left}` and the
  audit log records `client_left` ("signed off by the device"). It answers `client_leave_ok` and closes
  with 1000.
- Without a hub connection (offline, hub stopped, an app without a hub) nothing is sent: the app resets
  locally and the admin deletes the device.
- A device without a hub socket (the watch) signs off over REST: `POST /api/client/leave {client_id}`
  with `Authorization: Bearer <its client secret>` (`rest/client-leave.request.json`), directly over the
  pinned TLS port or through its phone, which forwards exactly this request to its own pinned hub. Same
  effect as `client_leave`; answers 200 `client_leave_ok`, 401 for an unknown or removed secret, 422 when
  `client_id` is not the device of the secret. The secret passes the phone only in this request, when it
  stops being valid. When the watch cannot be reached, its phone removes it with `set_up_device_remove`
  (it set the watch up).

## Watches: access through the phone

A watch (`watchos`, `wearos`) has no hub socket. Its phone carries
everything, but never sees the watch's Home Assistant token and keeps the watch working after
a token rotation:

1. **Pairing.** The watch makes an X25519 key and keeps it (watch keychain, this device only). Its phone
   opens the onboarding session with that public key and confirms it itself (the watch's default
   profile, rule `watch`; a child's phone cannot confirm: an adult does, see “A child's watch” below). The hub stores the public key for the watch, sends `onboard_ok` (secret sealed
   to the key, `hub/onboard/v1`) and **closes the connection with 1000 without authenticating it**: the
   phone never reads the watch's `client_config`. `client_config.ha_token` of a watch is null on the wire
   in any case.
2. **Access.** The phone that set the watch up asks `watch_access_get {client_id}` on its own socket. Answer
   `watch_access {client_id, status, sealed?}`:
   - `ready`: `sealed` = HPKE base mode to the watch's key (suite of the onboarding, `info =
     hub/watch-access/v1`, `aad = client_id`), plaintext `{client_id, issued_at, config}` with the watch's
     whole `client_config` (`crypto/watch-access-plaintext.json`, vector `watch-access-v1`);
   - `pending`: the watch holds a key that is not usable yet: not issued, or held back until the
     integration has the watch's rules, or being replaced (`client_config.token_error`); a push follows;
   - `gone`: no such watch of this phone (deleted, locked, set up by another device): the watch forgets
     its access.
3. **Changes.** Whenever the watch's access changes (first or rotated HA token, profile, rules, remote
   access, access hours) the hub pushes `watch_access` to every connection of that phone. The phone
   passes it on unchanged (WatchConnectivity on Apple). The watch keeps the newest `issued_at` and keeps
   its stored token when `config.ha_token` is null (outside its access hours).
4. **After a rotation** the old token stops working; when Home Assistant answers 401 the watch asks its
   phone for `watch_access` once more and continues with the new token. Only `gone`, or a 401 with the
   newest token, removes it. A rotation of a watch with remote access waits for the **phone** to be
   connected (the phone's connection counts for its watches) and is released when it connects.
5. **Signing off.** The watch signs off with `POST /api/client/leave` (above); the phone's “Remove
   watch” asks the watch to do that and otherwise removes it with `set_up_device_remove`.
6. **Notifications.** A watch has no notification view of its own and gets no notification stored for
   it. A notification for a watch (`POST /api/notifications`, `POST /api/integration/notify`, an item of
   the handover) goes to the phone that set it up: the notification's `client_id` is the phone's and the
   answer names it, `forwarded_to {client_id, name}`; a `notification_id` is checked against the phone.
   The phone's system shows the notification on the watch (notification forwarding). Without that phone
   (deleted, inactive or being deleted) the call is 422 and nothing is stored; a handover item is skipped
   as `client_not_found`. `client_id: "all"` leaves watches out (they show their phone's), and watches
   are no targets of notifications at events (`GET /api/log/notify-targets` leaves them out, a rule
   naming one is 422 `notifications.device_unknown`).

### A child's watch

A watch whose phone (`set_up_by`) has parental controls is a child device itself. The admin allows it per
profile or device with the kids rule **`kids_watch`** (“Allow a watch”, default off, `ios` only, needs
remote access); parental controls cap the phone's rule `watch` at off unless `kids_watch` is on
(`boundary_kids_watch`). Guests never get a watch; adults have the rule `watch`.

- **Rules.** While its phone has parental controls the watch resolves with the **phone's** profile,
  device adjustments, access, access hours, own area and kids override on its own platform (`watchos`):
  the same kids rules, areas and blocked types, `control_path` checked (a watch always holds a key:
  `platform_needs_key` when the phone is on Hub only), `quick_access` by the rules (never more than the
  phone's), `client_config.profile` is the phone's profile and
  `child_protection` true. Its own stored profile applies again only when the phone no longer has
  parental controls.
- **One kids state.** Counters, “pause everything”, cooldowns, releases of a family manager, early access
  and the kids override are the phone's (enforcement.md §4): a child cannot double a limit by using both,
  pausing everything pauses both, a release applies to both. The watch's `client_config.kids` (and its
  rule snapshot) carries the phone's `paused_all_until` and releases.
- **Key.** The watch switches only through `<ns>.control` (checked, kids rules of the snapshot plus
  `kids-check`); its read-only key is in its sealed `client_config` exactly when the phone's would be
  (`kids_watch` needs remote access, so the watch's HA user is never `local_only` while it is allowed;
  closed access hours hold the key back as for every device). Requests (“Can I have more time?”) stay on the
  phone; the watch shows the state and points to the phone.
- **Pairing needs an adult.** See setup.md “A child's watch”: the child's phone binds the session, an
  adult's device with `setup_devices` (kind child) confirms it with the code.
- **Lifecycle.** When a phone comes under parental controls (assignment, profile switch, adjustment) and
  its effective `watch` stays on (`kids_watch`), its watch is re-scoped at once: new `watch_access` with
  the child config, new rule snapshot (read-only user), and its old token is rotated. When the phone's
  effective `watch` is off under parental controls – on becoming a child without `kids_watch`, or later
  when `kids_watch` or remote access is switched off – the hub removes the watch like
  `set_up_device_remove` (HA user removed, `watch_access` `gone` with `reason` `kids_watch_off`,
  `remote_access_off` or `parental_controls` to the phone, which tells its user; the admin's preview lists
  it beforehand in `watches_removed`). When the phone leaves parental controls the watch stays, follows
  its phone (below) and gets a new token. Removing the phone removes its watch.
- **A phone on Hub only.** A watch needs its own key, and a phone on Hub only without remote access holds
  none: its rule `watch` resolves to off (boundary `hub_only`). When that happens to a phone without
  parental controls that carries a watch, the hub removes the watch the same way (`watch_access` `gone`
  with `reason` `hub_only`, `watches_removed` in the preview). The watch holds its key only while its
  phone's effective `watch` is on (`profiles_ref.ha_access` with the phone's rules). **The hub must evaluate
  again at every `expires_at`**: when a temporary remote access or a temporary checked of the phone ends,
  the phone's `watch` carries that end (`expires_at`, `then` false) and the hub removes the watch and
  withdraws its key at that time, as on a write. With remote access the phone holds a
  read-only key and may carry a watch; the watch's `control_path` is then `checked`.

### Every watch follows its phone

A watch never has more than the phone that carries it, also after pairing: for every rule of the
No-escalation check of setup.md (security critical or sensitive outside kids and location) and the areas,
the hub resolves the watch to the **meet** of its own and its phone's current effective value – never a
replacement, so it never gets anything its own profile does not give (`profiles_ref.limit_to`: source
`boundary`, reason `limited_by_phone` only when the meet is stricter than its own somewhere at runtime;
otherwise the watch's own entry stays). Each rule has a class in the
catalog (`watch_limit`, checked by `tools/profile_rules.py`; an unclassified rule is refused):

| Rule | Class |
|---|---|
| `remote_access` | ordered |
| `connection_insecure_http` | ordered |
| `control_path` | ordered |
| `access_hours` | schedule |
| `setup_devices` | kinds |
| `family_manager` | ordered |
| `babysitter_requests` | ordered |
| `app_settings` | ordered |
| `app_settings_biometrics` | ordered |
| `remote_control` | remote_levels |
| `control_mode_max` | ordered (a normal rule, but the app enforces it: a watch never shows more advanced controls than its phone) |
| `areas` | areas |
| `camera_live` | ordered |
| `quick_access` | ordered |
| `watch` | ordered |

- **ordered**: the stricter value along `order`. `control_path`: a watch cannot be on `hub` (it needs its own
  key), so a meet of `hub` becomes `checked` (`platform_needs_key`); the watch then never has more than
  `checked`, and whether it may exist at all is decided by the phone's rule `watch`.
- **areas**: “all areas” on one side gives the other side. The hub knows the areas' tags: the watch gets
  the areas both sides reach (pinned ids, tags matched against the areas), pinned by id. Without the tags
  (the reference resolver without `input.area_tags`): the common ids and common tags only. The own area is
  already an id; an empty result is no areas, never all.
- **schedule** (`access_hours`): only the minutes both are open (off = always open; both in the hub's time
  zone; overnight windows run into the next day). One side always open or both the same windows: exactly
  the other side's windows. Otherwise written back as one window per run of at most a day, equal times on
  several days in one entry; beyond 14 entries the rest stays closed. Spring forward: a local time that
  does not exist that night means as much later, so an edge inside the gap moves on one side only. The
  hub checks the result on the real instants of each spring-forward night of its zone and closes only the
  minutes where it would be open while a side is closed (an end inside the gap moves to the gap's start;
  a run cut by the other side's later-moved start loses just those minutes). Typical case still trimmed:
  both sides end on that night, one inside the gap and the other within as long after it (Zurich: watch
  Sat 22:00–02:45, phone 22:00–03:15 → 22:00–02:00 on Saturdays). While the hub's zone is not known the
  clock jumps of every IANA zone are assumed (fail closed).
- **remote_levels** (`remote_control`): the lower level for the default and for every domain and
  `domain:device_class` key either side names, each side's level being what it gives such an entity at
  runtime (entity > domain:device_class > domain > default). An entity key one side names: the hub passes
  its states as `entity_classes` (entity id → device class or null); the entity gets the lower of both
  sides' runtime levels for its real class. Only an entity without a known state gets the lower of both
  sides' **lowest** level it can have (every class key of its domain, the domain, the default). Keys that
  change nothing (a class key equal to its domain, a domain key equal to the default, an entity key equal
  to what it gets without it) are left out.
- **kinds** (`setup_devices`): enabled only when both are, the common kinds only.
- Not limited (`none`): `access_requests`, `kids_blocked_types`, `kids_quiet_hours`, `kids_rate_limit`, `kids_rate_limit_all`, `kids_volume_max`, `kids_color_lock`, `kids_requests`, `kids_exceptions`, `kids_watch`, `scan_tags`, `card_style`, `appearance`, `header`, `home_header`, `search_filter`, `columns`, `power_button`, `notification_level`, `notification_stack`, `kiosk`, `panel_start`, `panel_auto_home`, `panel_dim`, `panel_screensaver`, `panel_night`, `panel_remote`, `panel_sensors`, `panel_wake`, `panel_brightness`, `panel_announce`, `panel_off_mode`, `location`, `location_required`.

Over time the limited value is never more than either side at any moment: with an end on either side
the entry carries the earliest `expires_at`, and `then` is the meet of every later state (after the first
end, after both). What one `expires_at`/`then` cannot carry is a loosening after the second end; the hub
sends it when that adjustment ends. A watch whose phone row or profile cannot be read resolves with
every limited rule at its strictest value (no remote access, checked path, nothing released). The watch's own profile and
adjustments stay stored and apply again by themselves. Its rule snapshot, HA user (`local_only`, read-only
for the checked path), token and `watch_access` follow like any rule change. An adult's watch is removed only
when its phone's effective `watch` turns off through Hub only (reason `hub_only`, above), also when a
temporary adjustment ends; other rule changes of the phone never remove it.

## Errors and 404

Errors use FastAPI's `{"detail": ...}`. Every operation that answers 404 for an unknown resource
(area, section, entity placement, widget, device, profile …) lists the 404 in
`openapi/hub.openapi.json` (`#/components/responses/NotFound`); `detail` names what was not found
(for example `Area not found`, `Client not found`, `Section not found in area`). Mostly the resource
is in the path; a few operations answer 404 for a single id in the body (`client_id` of a
notification, a section of another area in `POST …/entities`, the target section of a move). Ids
that are checked as a list (sections in `PUT …/layout`) answer 422.

Dry runs: a write that offers one takes `dry_run` as a query parameter (profile writes, adjustments,
assignment, own area) or a body field (bulk change, guest extension) and changes nothing. Every other
write that receives `dry_run` true, as a query parameter or a top-level body field, answers 422 with
`{"detail": {"code": "dry_run_not_supported", "message": …}}` and changes nothing.

## Known deviations

Places where the current hub differs from what the protocol would ideally define. They are marked in the files
(`x-known-deviation`, `x-unused`, `x-todo`, `deprecated`), and schema descriptions refer to them by
the labels below.

| # | Deviation | Marked in |
|---|---|---|
| D1 | `icon_svg` in notifications is sent but not decoded by the apps | `schemas/common/notification-item.json` |
| D2 | Diverging defaults (`grid_cols`, `dense_section_placement`, `control_mode`) | `schemas/common/area.json`, `client-config.json` |
| D3 | Apps decode `tls_port` strictly as an integer; a string drops the whole `client_config` (the hub sends an integer) | fixture `client-config/invalid-tls-port-as-string.json` |
| D4 | SQLite booleans arrive as `0`/`1` over WebSocket (`is_active`, `dense_section_placement`, `is_visible`, `is_collapsed`), as `true`/`false` in sensors and status | `schemas/common/defs.json#/$defs/boolish` |
| D5 | WebSocket and REST area payloads contain server file paths (`*_path`), only for admin sessions and the admin REST API, never for apps | `schemas/common/area.json` (`deprecated`) |
| D6 | Mixed timestamps: `isoformat()` with offset, section `created_at` in SQLite format without zone | `schemas/common/defs.json#/$defs/timestamp` |
| D7 | Binary frames and JSON values that are not objects close the connection | AsyncAPI description |
| D8 | Same `type`, two shapes: `guest_extended` (targeted and broadcast), `notification_created` (admin and integration) | `schemas/ws/server-message.json` |
| D9 | A repeated `auth` returns `auth_ok` without `client_id`; messages before sign-in are answered with `auth_required` instead of `error` | `schemas/ws/server/auth_ok.json`, AsyncAPI |
| D10 | 43 REST responses without a model; the body of `POST /api/integration/start-pairing` is missing from the FastAPI OpenAPI | OpenAPI `x-todo`, `schemas/integration/start-pairing.request.json` |
| D11 | `PUT /api/settings/app-url` sends no `client_config_updated` and does not check the URL | OpenAPI `x-known-deviation` |
