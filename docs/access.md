# Access hours, house sitter and babysitter

Some devices should only have access at certain times: a babysitter in the evening, a house sitter while
the family is away, a cleaner on Tuesday mornings. Halumar has two controls for this and both must allow
access:

1. the profile rule **access hours** (`access_hours`) – weekly windows like the bedtime
   editor, with “Fixed”, per device adjustable, also temporarily (“stays until 03:00 tonight”);
2. an **access switch** per device in Home Assistant, `switch.<ns>_<name>_access` (name “Access”), for the
   owner's own schedules and automations (calendar, presence, alarm armed …).

**Access = schedule allows it (when access hours are enabled) AND the switch is on (when the device has
one).** Outside, the device stays paired but sees nothing: no areas, no states, no control, no quick
access; it shows only “Access again from Mon 18:00” (or “No access right now” while the switch is off).

Schemas: `$defs/access_hours`, `$defs/access_window`, `$defs/access_now`, `$defs/enforcement_access`,
`common/client-access.json` `hours`, `common/client-babysitter.json`, `rest/paired-client.json`
`access_now`, `rest/access-switch.request.json`, `integration/access-switch.{request,response}.json`,
`integration/status.response.json` `clients[].access`. Reference `tools/access_ref.py`, vectors
`fixtures/profiles/access-hours`; babysitter permission vectors `fixtures/profiles/family-check/babysitter.json`.

## Rule “Access hours”

`access_hours {enabled, windows[]}` (group access, sensitive, “Fixed” checkbox, every platform, every
profile kind, no boundary). Windows have the form of a bedtime window (`days`, `start`, `end` in Home
Assistant's time zone; `end <= start` crosses midnight and belongs to the start day; `start == end` = 24
hours). Windows that touch or overlap are one access (`until` follows them). `enabled` with no window =
no access at all (the strictest value). Catalog default: off. Suggestions: **Babysitter** every day
17:00–01:00, **House sitter** every day 07:00–21:00, both not fixed.

Enforcement (`enforcement`): on Hub only (the suggestions for guests, house sitters and babysitters, and
children) the hub refuses every read and control outside the windows (`hub`) and Home Assistant refuses
every control again; with the control path checked Home Assistant refuses every control outside the
windows (`ha_control`); with the direct path the hub withholds everything (`app`). In every case the hub renews the
device's Home Assistant key when access closes (below), so a key the app kept stops working as soon as the integration has removed it (until then it keeps working, and the hub keeps trying).

## Access hours when setting up or inviting

The device that sets up a guest, house sitter or babysitter (or any other kind) may choose its access
hours: every profile entry of the grant (`common/setup-grant.json`) has `access_hours` (the profile value,
preset of the question) and `access_hours_choice` (true = the profile does not fix the rule). The app
sends `access_windows` (1–14 windows, `$defs/access_windows`, checked like the rule editor) in
`onboard_confirm` or `guest_invite_create`; the hub stores `{enabled: true, windows}` as a permanent
device adjustment of `access_hours` (nothing when equal to the profile value; for an invitation when the
guest pairs). Without `access_hours_choice` the field is refused with `access_hours_not_allowed` (the
session stays open like other validation errors) – never silently ignored. Leaving the field out keeps
the profile value; “any time” cannot be chosen this way when the profile sets hours. `onboard_confirm_ok`
and `guest_invite.grant` repeat the effective `access_hours`.

## Access switch

- A device has a switch when its effective `access_hours` is enabled **or** its profile is of kind
  `guest`, `house_sitter` or `babysitter`. Default on; the hub stores the state (survives restarts). A
  device that loses its switch (profile change) counts as on.
- The integration creates `switch.<ns>_<name>_access` (translation key `access`, name “Access”;
  attributes `open`, `reason`, `until`, `opens_at`) for every client whose status has `access.switch`
  not null. Turning it calls `POST /api/integration/access-switch {client_id, on, user}`.
- **Only Home Assistant admins and automations** operate it: the switch refuses calls of non-admin users
  (`Unauthorized`); `<ns>.control` refuses it as `own_entity`. The admin UI switches it with
  `PUT /api/pairing/clients/{id}/access-switch {on}`.
- If the hub is unreachable the switch reports an error and changes nothing.

## What the hub does while access is closed

| Where | Effect |
|---|---|
| Connection | `auth` succeeds (the device stays paired); `auth_ok` as usual |
| `client_config` | `access.hours.open = false` with `reason` and `opens_at`; `ha_token`, `ha_url`, `ha_enforcement` null; `quick_access.entities` empty; `family` and `babysitter.active` off |
| Areas and states | `get_areas` → `[]`, `get_area`/`subscribe`/`state_subscribe` → not visible, no state pushes |
| Control (hub path) | `rule_blocked {reason: access_closed, until: opens_at}` |
| Family, setting up, invitations | `family_error {not_permitted}`, `onboard_error {not_permitted}`, `guest_invite_error {not_permitted}` |
| Early access | `access_request` / `access_request_cancel` accepted over the hub WebSocket (rule `access_requests`, below) |
| Panel status | still accepted (the device's own values) |
| Snapshot | `access {switch, hours, windows, time_zone}`; `<ns>.control` → `blocked_access_closed` for every entity |
| Home Assistant key | when access closes the hub rotates the device user's token of every device that holds a key (also with parental controls): the key the app held stops working as soon as the integration has removed it (until then it keeps working, and the hub keeps trying), so after that an altered app can neither read nor switch in Home Assistant outside the access; the hub keeps the new token and hands it out in `client_config` when access opens. A device on Hub only without remote access holds no key; the hub path gives it nothing while access is closed |

`client_config.access.time_zone` is the hub's IANA zone (Home Assistant's
`time_zone`, UTC when unknown) for every device. The windows are in this zone, so the app computes every
edge it needs itself (the next start after `until`, the end of a window a child device opens by itself)
in it and never in the device's own zone; a phone travelling in another zone shows the same times as the
hub. Shared vectors: `fixtures/profiles/access-hours` (`device-zone-differs` with `device_time_zone`).

The hub sends `client_config_updated` at every change (window start/end, switch, profile or adjustment)
and pushes the snapshot when the switch or the rule changes. The integration evaluates the windows with
its own clock, so access hours keep working without the hub. The app switches by itself at
`until`/`opens_at` even without a push.

`access_now` (`client_config.access.hours`, `paired-client.access_now`, integration status):

| Field | Meaning |
|---|---|
| `open` | schedule allows it and switch on |
| `reason` | closed: `switch` (wins) or `schedule`; open: null |
| `until` | open: end of the running window (null = no time limit) |
| `opens_at` | closed by schedule: next window start within 8 days; null while the switch is off |
| `schedule` | access hours enabled |
| `switch` | switch state, null = no switch |

Admin device page: “Access now: open until 23:30” / “closed until Mon 18:00” / “closed – switch off”.

## Log and notifications

Events `access_opened` and `access_closed` (category devices, source hub, `data/events.json`): one log
entry per change with `detail {reason: schedule|switch, until|opens_at, by: admin|ha}`; selectable in
“Notifications at events” and fired as `<ns>_event` (`access_reason`, `until`). A change of the
switch by the admin UI or Home Assistant is also an audit entry (`access_switch_set`).

## Profile kind babysitter and suggestions

The kind **`babysitter`** (`$defs/profile_kind`, catalog `profile_kinds`: phone and tablet, guest access
with expiry like guest and house_sitter). It can be chosen in `setup_devices.kinds`; the suggestion
**Parents** includes it.

- **Babysitter** (kind babysitter): only at home (`remote_access` off, fixed), Home Assistant access
  Hub only (fixed: no key on the device), areas selected (own area + preselection by `area_patterns`: living spaces and kids'
  rooms), access hours 17:00–01:00, `babysitter_requests` on, no rights (guest boundary: no guests, no
  setting up, no settings, no widgets).
- **House sitter & helper** (kind house_sitter): Home Assistant access Hub only (fixed), remote access off
  (not fixed: switched on, it gives the device a read-only key with which it can read every state in Home
  Assistant), selected areas (own area + preselection: living room, kitchen, garden, entrance), access hours
  07:00–21:00, from away door, garage, gate, lock and alarm view only.

`area_patterns` (suggestions only): when the admin adds the suggestion, the hub preselects the active
areas whose name has a word starting with one of the prefixes (“Wohnzimmer”, “Kinderzimmer oben”,
“Kitchen”) into `areas.area_ids`; the admin checks the choice. The profile keeps concrete areas.

## Babysitter answers the children's requests

Rule **`babysitter_requests`** (“Answer children's requests”, group access, sensitive, “Fixed”, phone
and tablet, only profiles of kind `babysitter` – else `requires_profile_kind`; parental controls → off).
**Why a profile rule and not a house setting:** the admin decides per babysitter (grandma yes, a new
babysitter no), can fix it, adjust it per device and temporarily, and every change is audited like every
right. The house setting `requests_enabled` (family settings) still switches requests off
for everyone.

- **Who gets a request:** every family manager of the child **and** every babysitter device
  with the rule that is *active*: access open (switch and hours), connected to the hub WebSocket (= at
  home; never through the integration relay or HA notifications). `client_config.babysitter {active,
  presets, access_until}` tells the app. The child sees it in `client_config.kids.requests.recipients`
  (`role: babysitter`, only while active); every change of the active babysitters reaches the
  connected children as `client_config_updated` (docs/family.md).
- **First answer wins**. A babysitter sends `family_answer` with `no` or `yes` and a preset
  of `data/family.json` `babysitter.presets`: `15m`, `30m`, `access_end` (“until the end of babysitting”
  = `access_until`, the end of its running window; not offered without a known end). Anything else →
  `family_error {preset_not_allowed}`. The release never lasts beyond `access_until`.
- **Limits:** no `family_rule_set/reset`, no own `family_release`/`family_release_end`, no children's
  overview, activity, log or rules (`not_permitted`); `family_get_requests` returns only open requests.
  `unlock_device` only for an entity that no blocked device type, exception, lock or alarm panel blocks;
  a fixed rule in the child's profile is never released (`release_not_allowed`, the request stays open
  for the parents). Reference `tools/family_ref.py` `babysitter_check`.
- **Parents see every answer** with its author (`answer.by.kind = babysitter`, `family_request` to every
  family manager, event `kids_request_answered`, family activity) and can end the release
  (`family_release_end`, admin UI).
- When the babysitter's access closes, the hub ends the releases it gave that are still running.

## Early access

On “Access again from …” a device can ask for access now: **“Ask for early access”**. Schemas: rule `access_requests` (`profile-rule-values.json`), `common/access-request.json`,
`common/access-request-config.json` (`client_config.access.request`), `$defs/access_early`
(`access_now.early`, `enforcement_access.early_until`), WS `access_request`, `access_request_cancel`,
`access_requests_get`, `access_request_answer` → `access_request_state`, `access_request_update`,
`access_requests`, `access_request_error`, broadcast `access_requests_changed`, REST
`rest/access-requests.response.json`, `rest/access-request-answer.request.json`. Catalog (durations, short
answers, notification buttons, texts, limits): `data/access-requests.json`. Its texts are the source for every
client: iOS, Android and the admin UI show the same words (DE/EN). Reference: `tools/access_ref.py`,
vector `fixtures/profiles/access-hours/early-access.json`.

### Rule

`access_requests` (“Ask for early access”, group access, boolean, “Fixed” checkbox, phone, tablet and TV
– on a TV the request is sent with the remote, without a message –, every profile kind, enforcement `hub`). Catalog default off; suggestions **Guest**, **House sitter**
and **Babysitter** on, not fixed. It takes effect only while the device has access hours
(`access_hours` enabled): children see the screen only when their profile has access hours (by default
they have bedtime instead). `client_config.access.request` is present exactly while the rule is on:

| Field | Meaning |
|---|---|
| `enabled` | rule on and access hours enabled |
| `available` | the device can ask now: enabled, closed by the schedule (`hours.reason = schedule`), no own open request, limits not reached, someone can answer |
| `open` | own open request (also after an app restart) |
| `next_allowed_at` | hourly limit or cooldown after a No |
| `recipients` | `[{name, role}]` – who gets the request now, for “Mum and Dad will get your request.” |

The app shows the button only with `available`. While the access switch is off (`reason = switch`) the
device cannot ask: a request never overrides Home Assistant's switch (`switch_off`).

### Who gets the request

1. the device that set it up (`set_up_by`, role `set_up_by`), if still paired and active;
2. every person device (member, kind `person`, no parental controls) whose effective `setup_devices` is on
   and holds the kind of the requesting device (role `setup`);
3. for a **babysitter** additionally every family manager (effective `family_manager`, role
   `family_manager`).

A recipient needs access itself (open now) and is never the requesting device. Every name appears once
(owner label, else device name; set_up_by first, then by name; at most 10). `available` is also true
without recipients when the admin has a notification rule for `access_requested` (only the admin can
answer then; `recipients` empty, the app says “Nobody can answer right now” only when `available` is
false). Recipients get `access_request_update` on every connection (away through `family_relay`, like the
family manager), read open requests with `access_requests_get` and answer with `access_request_answer`; the
admin answers in the admin UI. HA notifications: the event `access_requested` goes to the targets the
admin chose (“Notifications at events”), and the hub sends every recipient's linked HA notify targets
(`PUT /api/pairing/clients/{id}/family notify_targets`) the request with buttons for `notify.mobile_app_*`
(`notify_actions`: “Yes, 1 hour”, “Yes, until the start” while offered, “No”; action id
`<NS>_ACCESS_<token>`, tag `<ns>-access-<request_id>`, one single-use token per button, only its SHA-256
stored, cleared when the request closes) – the same mechanism as the children's requests (docs/family.md).

### Asking, limits, expiry

- `access_request {note?}` only over the **hub WebSocket** (at home). A closed device holds no valid Home
  Assistant key (the hub rotates it when access closes), so it cannot ask away from home; the
  integration relay answers `access_request_error {home_only}` and the app says “Only possible at home”.
- Checks: rule on, access hours enabled, closed by the schedule (`not_closed`, `switch_off`), one open
  request per device (`request_limit`), `requests_per_hour` (3), after a No `decline_cooldown_minutes` (10)
  (`cooldown`, `retry_after`), at most `messages_per_device_per_minute` (20) messages (`rate_limited`),
  someone to answer (`no_recipients`). Note at most 80 characters, plain text.
- A request expires after `request_timeout_minutes` (10) → `expired`. It is `cancelled` when the device
  withdraws it (`access_request_cancel`), when its access opens by itself (window start) or it is removed
  or loses the rule.

### Answers

`access_request_answer {request_id, answer, duration?, message?}` (recipient device), `POST
/api/access-requests/{id}/answer` (admin) or a notification button. **The first answer wins**; later ones
get `access_request_error {already_answered, request}`.

- **Yes** with a duration of `request.durations`: `until_window_start` (until the start of the next regular
  window; only while that start is known and at most `until_window_start_max_hours` = 24 h ahead), `1h`,
  `3h`, `today` (until midnight in Home Assistant's time zone). The hub stores an **early access**
  (`$defs/access_early {until, by, request_id, duration, at}`) – a temporary adjustment of the device's
  access hours for that time, without changing its rule or its permanent adjustments. While it runs the
  device is open (if the switch allows it): `access_now.open = true`, `until` = the end of the early access
  or of a window that starts before it ends, `early` names who opened it. A device whose key the hub
  withdrew when access closed gets its key back at once (`client_config_updated` → `ha_token`). The
  integration gets `early_until` in the rule snapshot and lets `<ns>.control` through until then with its
  own clock. At `until` the hub deletes it and the device closes again like at a window end (log
  `access_closed`, key withdrawn).
- **No** with an optional short answer (`not_now`, `not_today`, `later`, `call_me`); the device waits
  `decline_cooldown_minutes` before it asks again.
- Every recipient gets the answer (`access_request_update`, `can_answer` false), the device
  `access_request_state` and `client_config_updated`. Admin UIs get `access_requests_changed`.
- The admin can end an early access before its end: `DELETE /api/pairing/clients/{id}/early-access`.

### Log and events

| Kind | Category | Detail |
|---|---|---|
| `access_requested` (event, devices, important) | activity | `request_id`, `note`, recipients count |
| `access_request_answered` (event, devices, important) | change | `action` yes/no, `until`, `duration`, `message`, actor = who answered (`by` with route home/away/ha_notification/admin_ui) |
| `access_request_expired` (event, devices) | activity | `request_id` |
| `access_request_cancelled` | activity | `request_id` |
| `access_opened` / `access_closed` | change | as above; `detail.early {until, by}` when an early access opened it |
| `access_early_ended` | change | the admin ended an early access (actor admin) |

The three events are selectable in “Notifications at events” and fired as `<ns>_event` (`action`
yes|no, `until`). The admin device page shows “Access open until 19:00 (early, by Dad)”.
