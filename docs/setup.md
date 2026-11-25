# Setting up devices

A member sets up every new device from a device that is already paired: a child's phone, an iPad or
Android tablet as a wall panel, an Apple TV or Android TV, a guest's phone or the phone of another person. The new device only shows a
QR code with a 6-digit code (or takes the PIN); it never asks what it is for. The device that sets it
up decides the kind and the profile. Guests can also be invited with a QR code they scan with their own
phone. The PIN of the admin UI stays the fallback for every device.

Schemas: `ws/client/onboard_*`, `ws/server/onboard_*`, `common/setup-grant.json`,
`ws/client/get_setup_grant.json`, `ws/client/get_set_up_devices.json`,
`ws/client/set_up_device_remove.json`, `ws/client/guest_invite_create.json`; AsyncAPI sections “Setting up a device from a paired device” and
“Guest invitations by members”; crypto vectors `fixtures/crypto/onboard-seal-vectors`.

## Profile kind

Every profile has a **kind** (`$defs/profile_kind`, `rest/profile.json` `kind`, `client_config.profile.kind`):

| Kind | Devices | Set up as | Platforms of a new device |
|---|---|---|---|
| `guest` | a guest | guest access with expiry | phone, tablet |
| `child` | a child (with or without parental controls) | member | phone, tablet |
| `panel` | wall panel | member | tablet |
| `tv` | Apple TV, Android TV | member | TV |
| `house_sitter` | house sitter, helper | guest access with expiry | phone, tablet |
| `babysitter` | babysitter ([access.md](access.md)) | guest access with expiry | phone, tablet |
| `person` | a member of the household | member | phone, tablet |

Display order, labels, icons and platforms: `data/profile-rules.json` `profile_kinds`. The kind changes no
rule. Kind `child` is independent of parental controls (a teen profile without parental controls is still
`child`). Suggestions carry their kind (`data/profile-suggestions.json`); a new empty profile is `person`
unless the admin chooses another kind. Watches have no kind of their own (see below).

## Rule “Set up new devices”

`setup_devices {enabled, kinds[]}` (group access, sensitive, enforced by the hub, checkbox “Fixed”):

- Only for profiles of kind `person` (catalog `profile_kinds: ["person"]`): on any other kind it resolves to
  `not_applicable` with reason `requires_profile_kind`.
- Boundaries guest and parental controls: always `{enabled: false, kinds: []}`. A rule without `order`
  (object value) is decided by an active boundary (cap = value).
- Phones and tablets only (they have a camera).
- Without it a device can set up nothing and invite nobody.
- Not fixed: the admin may give one device more or fewer kinds (device adjustment).
- Suggestion **Parents**: on with guest, child, panel, tv, house_sitter, babysitter. All others: off.

## Flow

1. **New device** (any app platform; web gets `platform_not_supported`): `onboard_start` over TLS
   (port 8100, pinned) → `onboard_session {session_id, hub_id, code, expires_in: 300, expires_at}`. It
   shows the QR code (`deep-link/onboard-link.json`) and under it the code in two groups of three
   (“428 913”), the remaining time, “Enter PIN” and “Other hub”. A watch has no hub connection of its
   own: its phone opens the session with the watch's key and confirms it itself.
2. **Setting-up device**, two ways to the same session:
   - **QR code**: compares `fp` of the QR code with its own pin (otherwise “Wrong hub”) and sends
     `onboard_lookup {session_id, public_key, hub_id}`.
   - **Code**: `onboard_lookup {code}`. It compares nothing itself: it trusts its own pinned connection,
     and the waiting device receives the sealed secret only over its own pinned TLS connection. This is
     the same trust as with the PIN. A code is used up by the first successful lookup.

   The hub answers `onboard_info {session_id, public_key, hub_id, client_name, platform, …, grant}` and
   tells the waiting device `onboard_claimed {by_name}` (“Setting up · from iPhone Dad”). Without the right:
   `not_permitted`; when no allowed kind fits the platform: `kind_not_allowed` (“This is an Apple TV”).
3. The app shows the allowed kinds (`grant.kinds`; one kind → no choice) and asks only the questions of
   that kind:

   | Kind | Questions | `onboard_confirm` fields |
   |---|---|---|
   | child | name, profile, areas, managers | `owner_label`, `client_name`, `profile_id`, `area_ids`/`all_areas`, `managers` (only with `grant.managers_choice`) |
   | panel | place, profile, start area, areas | `client_name`, `own_area_id`, `start_area` (with `start_area_choice`), `area_ids` |
   | tv | room; areas under “More” | `own_area_id`, `area_ids` |
   | guest, house_sitter, babysitter | name, profile, duration, remote, access hours | `owner_label`, `client_name`, `expires_at` (required, ≤ 90 days), `remote` (with `remote_choice`), `access_windows` (with `access_hours_choice`) |
   | person | name, profile | `owner_label`, `client_name` |

   Then a summary (“Child's iPhone · Child 6–9 · Rooms: Kids' room, Living room · managed by Mum, Dad”;
   “Hub checked”, the fingerprint only under “Details”) and `onboard_confirm`.
4. **Hub**: checks everything again (below), creates the device (access `guest` with `expires_at` for
   guest, house_sitter and babysitter, else `member`), assigns the profile, stores the choices as device adjustments
   (`areas`, `panel_start`, `remote_access` until the access ends), sets the own area and the owner
   label, adds a new child with parental controls to the chosen family managers, records
   `set_up_by {client_id, name, method: onboard}`, provisions its own HA user (a device on Hub only without
   remote access never gets its key), sends the waiting device `onboard_ok` (HPKE-sealed secret)
   and the setting-up device `onboard_confirm_ok {kind, profile, owner_label, area_names, expires_at,
   remote_allowed}`. The app on the new device starts according to its rules (kids view, wall panel,
   TV kiosk).

A validation error (`kind_not_allowed`, `profile_not_allowed`, `areas_not_allowed`, `expiry_not_allowed`,
`managers_not_allowed`, `access_hours_not_allowed`) keeps the session open and counts as a failed attempt of the setting-up device.

**Type first.** `get_setup_grant {platform}` returns the same grant before scanning, so the app can
start with “What are you setting up?”; after the scan it compares the platform (“Wrong device”).

## Platform of the profile

When a device pairs with a PIN or is set up from another device, the hub checks the platform the device
reports against the profile it is to get:

- a profile of a guest kind (guest, babysitter, house sitter) or with parental controls only on the
  platforms of its kind (`data/profile-rules.json` `profile_kinds`);
- on a TV or a watch (`tvos`, `android_tv`, `watchos`, `wearos`, which always hold a key) not a profile that
  gives no key on a phone (Hub only without remote access), unless the profile's kind is meant for that
  platform (a TV profile on a TV).

Otherwise the device is refused: `pair_error {platform_not_allowed}` when pairing with a PIN,
`onboard_error {profile_not_allowed}` when it is set up from another device. Apps treat a reason they do not
know like `pin_invalid` (pairing) or `session_not_found` (setting up).

The check applies when the device is added. An admin may later assign the device to another profile or
change its profile; the resolver then decides what the device gets on its platform. A TV or a watch on a
profile whose Home Assistant access is Hub only resolves to Checked (`platform_needs_key`), and the admin
page shows that.

## No escalation

The hub offers a profile in `grant.kinds[].profiles` only if a device with it (on the platform of the new
device, with the access of its kind, without adjustments) has no more rights than the setting-up device:

- every rule with security `critical` or `sensitive` outside the groups kids and location, along its
  `order` (e.g. no `control_path` direct, no `family_manager`, no `remote_access`, no `quick_access`
  control, no `app_settings` open the setting-up device does not have itself). `control_path` is compared
  by the key the new device will hold on its platform (after hub → checked on a TV or watch): none <
  read-only < full (`profiles_ref.key_looser`). A device on Hub only with remote access holds a read-only
  key and may hand out what resolves to checked (an Apple TV, an Android TV, its own watch), never direct;
  a device on Hub only without remote access hands out nothing that holds a key (vectors
  `fixtures/profiles/no-escalation`);
- `setup_devices`: enabled only if its own is enabled, `kinds` a subset of its own;
- `access_hours`: if the setting-up device has access hours, the new device has access hours too
  and they open at no time its own are closed (minutes of the week); chosen `access_windows` outside its
  own hours → `access_hours_not_allowed` (also for invitations);
- `remote_control` (When away): per default, domain and entity at most its own level;
- `areas`: a profile that fixes the areas may show only areas the setting-up device sees; otherwise the
  area choice is a subset of `grant.areas` (never empty, “All areas” only with `grant.all_areas`).

A rule that does not apply to the setting-up device's platform is not compared. Remote access chosen for
a guest (`remote: true`) needs the setting-up device's own remote access. Profiles that fail are left out,
kinds without profiles are left out. The admin is not bound by this.

## Family managers

A new child with parental controls is always managed by every family manager with “all children”. A
setting-up device with the right `family_manager` additionally chooses managers with a selected list
(`grant.managers`, itself preselected, may deselect itself); the child is added to their lists.
Without that right it cannot choose (`managers_not_allowed`).

## Guests by invitation

`guest_invite_create {profile_id?, owner_label?, expires_at?, remote?}` needs `guest` in
`setup_devices.kinds`. The choice comes from `get_setup_grant {purpose: invite}` (kind guest only; areas of
the profile, never more than the member sees). Default profile: the default guest profile if offered,
else the first. Without `expires_at` the access lasts `guest_access.default_hours` from pairing. The guest
scans the pairing QR code with its own phone and gets exactly what `guest_invite.grant` shows. Later
changes to a guest are the admin's.

## Set up by me

`get_set_up_devices` → `set_up_devices`: the active devices and guests whose `set_up_by` is this device
(newest first) with kind, profile, expiry and connection state. `set_up_device_remove {client_id}` removes
one like the admin's “Remove” (disconnect, delete, HA user removed) → `set_up_device_removed`, otherwise
`onboard_error {device_not_found}`. Every active member device may list and remove what it set up, also
after its right was removed. The admin sees `set_up_by` on every device (`rest/paired-client.json`) and
may change everything. The device itself gets only `client_config.access.set_up_by {name, method}`:
never the `client_id` of the device that set it up, so a child cannot learn
the id of its family manager's device.

## Limits and security

- Sessions: 5 minutes, single use, in memory only (a hub restart ends them); one per connection; per
  source IP 3 open and 20 starts per 10 minutes, 20 open in total.
- Codes: 6 digits from a CSPRNG, unique among the open sessions. Wrong codes: 5 per setting-up device and
  20 on the hub per 10 minutes (`too_many_attempts`); only devices with `setup_devices` may try codes at all.
- QR path: a lookup or confirm with another public key or hub id ends the session (`session_invalidated`).
- Failures of the setting-up device (wrong session, invalid choice): 10 per 10 minutes (`rate_limited`).
- The QR code and the code contain no secret; the secret is HPKE-sealed to the waiting device's key.

## Log and notifications

- Log entry and event `device_set_up` (`data/events.json`, category devices): device, kind, profile,
  `set_up_by`, method; text “Child's iPhone set up by Dad as Child 6–9”. It can be selected under
  “Notifications at events” (HA `notify.*` and/or Halumar devices) and fires `<ns>_event`.
- Activity: new device `paired {method: onboard, confirmed_by}` or `{method: invite, invited_by}`;
  setting-up device `device_added` or `guest_invited` with `kind` and `profile_name`.
- Admin: running sessions `GET /api/pairing/onboarding` (with `claimed_by`, never id, code or key),
  `DELETE …/{id}`, broadcasts `onboarding_started` / `onboarding_claimed` / `onboarding_ended`.

## Watches

A phone sets up its own watch: the waiting watch gets the watch's default profile (`grant.own_watch`,
one kind with that one profile), never stronger than the phone. It needs `setup_devices` enabled (any
kind) and the rule `watch`.

The phone opens the session with the watch's key and confirms it itself. The watch's connection is not
authenticated: the hub sends `onboard_ok` and closes it, and the phone gets the watch's Home Assistant
access only sealed to the watch's key (`watch_access_get` → `watch_access`, also pushed after every
change, e.g. a token rotation). The phone can therefore neither read the watch's secret nor its HA
token. The watch signs itself off with `POST /api/client/leave`; its phone may remove it like every
device it set up (`set_up_device_remove`). Details: [protocol.md](protocol.md#watches-access-through-the-phone).

### A child's watch

A device with parental controls never confirms a setup (`setup_devices` off). It may still add its own
watch when its effective rule `watch` is on (kids rule `kids_watch`, needs remote access), and only
with an adult's confirmation, the same confirmation a child's own device needs:

1. The child's phone opens the watch's session with the watch's key (as above) and sends
   `onboard_lookup {session_id, public_key, hub_id}` on its own socket. The hub **binds the session to
   that phone** and answers `onboard_info` with `grant.own_watch: true`, `grant.child_watch {role:
   child, phone_name}` and no kinds. The phone shows the session's code (and the QR code) and asks an
   adult; its own `onboard_confirm` is `not_permitted`. Without the rule its lookup is `not_permitted`.
2. An adult's device with `setup_devices` enabled with kind **child** (not the child's phone) looks the
   session up with the code or the QR code. The grant has `own_watch: false`, `child_watch {role: adult,
   phone_name}` and exactly kind child with the phone's profile (if it passes “No escalation” on
   `watchos`; no area choice, no managers, no expiry). Confirming it is the approval.
3. The hub checks again that the phone still has parental controls and its effective `watch` on, creates
   the watch with `set_up_by` = the **child's phone** (it carries the watch's access) and
   `confirmed_by` = the adult (activity `paired`, log `device_set_up`), and from then on the watch follows
   the phone (protocol.md “A child's watch”). The waiting session gets `onboard_ok` (on the child's
   phone), the adult `onboard_confirm_ok`. `onboard_decline` by the adult ends it (`declined`).

After pairing a watch keeps following its phone: it never has more than the phone has now
(protocol.md “Every watch follows its phone”, reason `limited_by_phone`).

A session bound to a child's phone is never an adult's own watch; another child's phone cannot bind it
again (`not_permitted`).
