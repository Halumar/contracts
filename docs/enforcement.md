# Enforcement in Home Assistant

The profile rule **Home Assistant access** (`control_path`) decides how a device reaches Home Assistant:

- **Hub only** (`hub`): the device gets no Home Assistant key. It reads and switches only through the hub,
  which serves exactly what its profile allows ([§7](#7-devices-on-the-hub-path)). With remote access it gets
  a read-only key for use away from home.
- **Checked** (`checked`): the device has a read-only HA user and switches only through the integration
  action `<ns>.control`, which checks the device's rules. Hiding stays a display rule: Home Assistant always
  lets a user read every entity.
- **Direct** (`direct`): the device user has full rights; the rules apply in the app only.

Operating devices is enforced **in Home Assistant** on Hub only and Checked. Wording for product texts:
“Operating devices is enforced in Home Assistant; hiding applies in the app.” On Hub only without remote
access hiding is enforced too: the device has no other way to read.

| Part | File | Direction |
|---|---|---|
| Rule `control_path` (hub · checked · direct), boundaries guest and parental controls → at most checked, `hub_only` | `data/profile-rules.json`, `$defs/control_path_rule`; Home Assistant side `$defs/control_path` (checked · direct) | hub (resolver) |
| Hub path: `control`, `state_subscribe`, `history_get`, `forecast_get`, `camera_image_get`, `media_image_get`, `location_report`; REST `POST /api/client/control` | `schemas/ws/client/*`, `schemas/ws/server/*`, `schemas/rest/client-control.request.json` | app → hub |
| Action `<ns>.control` (fields, answer, reasons) | `schemas/integration/ha-control.{request,response}.json`, `$defs/control_denial_reason` | app/hub → HA |
| Allowlist of actions and data fields per domain, targets of scenes and scripts (`run_targets`) | `data/control-allowlist.json` (codegen `ContractData.controlAllowlist`) | all |
| Rule snapshot per device | `schemas/common/enforcement-snapshot.json`, `$defs/rules_hash` | hub → integration |
| Push `enforcement_rules` | `schemas/ws/integration/enforcement_rules.json` | hub → integration (WS) |
| `GET /api/integration/enforcement-rules`, `status.enforcement.rules_hashes` | `schemas/integration/enforcement-rules.response.json`, `status.response.json` | integration → hub (REST) |
| `POST /api/integration/kids-check` | `schemas/integration/kids-check.{request,response}.json` | integration → hub |
| `POST /api/integration/events` | `schemas/integration/events.{request,response}.json`, `schemas/common/enforcement-event.json` | integration → hub |
| Event taxonomy, HA events `<ns>_event`, `<ns>_alarm` | `data/events.json`, `schemas/integration/ha-event.event.json`, `ha-alarm.event.json` | integration → HA |
| Push `ha_event` (hub events fired in HA) | `schemas/ws/integration/ha_event.json` | hub → integration |
| Notifications at events | `schemas/rest/event-notifications*.json`, `openapi/hub.openapi.json` (tag `log`), `docs/log.md` | admin UI ↔ hub |
| Capability for the app | `client_config.ha_enforcement` | hub → app |

## 1. Control path

| Value | Key on the device | HA group of the device user | How the app reads and switches | Rules |
|---|---|---|---|---|
| `hub` | none; with remote access a read-only key | `system-read-only` (the hub holds its token) | through the hub (`state_subscribe`, `control`, …); with a key and the hub not reachable like `checked` | areas, access hours and location enforced by the hub (`enforcement` `hub`), operating again by HA |
| `checked` | read-only key | `system-read-only` (reads everything, direct actions → “Unauthorized”) | reads HA, switches only through `<ns>.control` | areas and “when away” enforced by HA (`enforcement` `ha_control`) |
| `direct` | full key | `system-users` | directly (`call_service`) | app only (`enforcement` `app`) |

- Profile rule with “Fixed” and device adjustments, also temporary. Catalog default `checked`;
  strictest `hub` (an expired guest has no key). Without a stored value, a profile with parental
  controls, a device with guest access and a profile of the kinds guest, babysitter or house sitter
  resolve to `hub` (fail closed); an unknown value counts as `hub`. Suggestions: Adult `checked`, Parents `direct`; Guest,
  Babysitter and House sitter `hub` and fixed; every kids suggestion `hub`; Wall panel and TV
  `checked`. Boundaries: guest access and parental controls cap at `checked` (never `direct`).
- **Home Assistant knows two paths.** The rule snapshot, `control_paths` and
  `client_config.ha_enforcement` carry `checked` or `direct` (`$defs/control_path`); a device on `hub` is
  `checked` there, so its user is read-only like every checked device (`profiles_ref.snapshot_control_path`).
- **Platforms that need a key.** The apps for Apple TV, Android TV and Apple Watch read and switch through
  Home Assistant (a watch has no hub socket; the value `wearos` of the planned Wear OS app is treated the same): on `tvos`, `android_tv`, `watchos` and `wearos` the
  value `hub` resolves to `checked` (source `boundary`, reason `platform_needs_key`). This is the one case
  where a boundary raises a value, and never to `direct`. An expired guest stays on `hub` there.
- Reference: `tools/profiles_ref.py` `ha_user_group()`, `holds_key()`, `ha_access()`; vectors
  `fixtures/profiles/resolve/control-path-*.json` and the matrix `fixtures/profiles/ha-access/matrix.json`.
- **No automatic fallback** to `direct` when the integration is down (§6).
- The integration keeps the group: a `user_updated` watcher sets it back at once; at start it
  restores what changed while it was not running. **Emergency exit:** saving the device user in the
  HA user settings while the integration is down makes it a full user; when the integration returns
  and the profile still says `checked`, it is set back (event `access_group_restored`, repair issue).
- The integration sets the group as soon as the device's snapshot arrives (no switch): checked →
  `system-read-only`, direct → `system-users`. A new device user starts in `system-users` and is
  set to read-only with its first snapshot. The hub pushes that snapshot **before** the app gets the
  token (`client_config.ha_token` stays null until then), so a device on `hub` or `checked` is read-only
  before it can sign in.
- **Changing the control path of an existing device** (profile, adjustment, end of a temporary
  adjustment): the hub pushes the snapshot right away and only then sends `client_config_updated`.
  `client_config.ha_enforcement.control_path` is the path of the snapshot the integration last
  received, not the profile's new value, so the app never switches directly while its user is still
  read-only and keeps switching directly while it still may. A push that did not arrive
  makes the next one complete.

## 2. The action `<ns>.control`

Every authenticated user may call it; only device users of the integration (by their snapshot),
admins and system calls get anything executed (others: `not_a_device`). Apps call it over the HA
WebSocket:

```json
{"type": "call_service", "domain": "<ns>", "service": "control", "return_response": true,
 "service_data": {"entity_id": "light.kitchen", "action": "turn_on", "data": {"brightness_pct": 40}}}
```

Fields (`ha-control.request.json`): `entity_id` **or** `entity_ids` (batch of one action, max 50),
`action` (action of the entity's own domain), `data` (no targets), `origin` (`app` |
`quick_access`), `check_only`, `grant` (hub only). Answer (`ha-control.response.json`): `route`,
`rules_hash`, `results[]` per entity (`ok`, `executed`, `reason`, `until`, `adjusted`).

Checks per entity, in this order, first failure wins:

1. **Allowlist** (`data/control-allowlist.json`): action allowed for the domain
   (`not_allowed_action`), every data key allowed and not in `forbidden_fields`
   (`not_allowed_field`: targets, `group_members`, `variables`, `snapshot_entities`, …), value
   type and range (`not_allowed_value`; strict JSON types: `"50"` is not a number, `true` is not 1).
2. Entity exists (`unknown_entity`). Entities of the integration itself (its own platform in the entity
   registry: wall panel controls, hub buttons and switches) are refused with `own_entity`
   (`own_entities: blocked` in the allowlist) – only admins and automations operate them, directly.
3. **Access** snapshot `access` not null: switch off, or `hours` and the integration's clock (in
   `time_zone`) outside every window → `blocked_access_closed` for every entity (`until` = next window start
   when the switch is on). See [access.md](access.md).
   **Snapshot** `entities.<id>`: missing → `blocked_area`. Level on the route: local →
   `local`; external or unknown → `remote` (without `remote_access`: `hidden`). `hidden` →
   `blocked_remote`; `view` → only actions marked `safe` (lock, arm), else `blocked_view_only`
   (local) or `blocked_remote` (external). `origin: quick_access` → quick level (on the external
   route capped by the remote level) must be `control`, else `blocked_quick_access`. Domains with
   `release_required` (scene, script, automation, remote) need `run: true` (`scene_not_released`).
4. **Group entities** (state attribute `entity_id` is a list, any domain except scene and script):
   every member must be of the same domain and pass step 3 (`blocked_group_member`).
   **Scenes and scripts** (allowlist `run_targets`: `scene.turn_on`, `script.turn_on`,
   `script.toggle`) switch other entities as the system, so besides their own release every
   **target** must be allowed for the device on its own, judged for the target's domain:
   - Targets: of a Home Assistant scene the entities of its configuration (state attribute
     `entity_id`, with the stored state of each); of a script its sequence (blueprint inputs filled
     in), resolved the way Home Assistant resolves it when the script runs: `entity_id: all` = every
     entity of the action's domain (of every domain for `homeassistant.*`), `none` = nothing;
     devices, areas, floors and labels through the registries (only entities of the action's domain
     for an action of an entity domain); registry ids; old style groups expanded; scripts called as
     actions (`script.<name>`); the entities of `scene.apply`/`scene.create`; device actions; entity
     ids named in other data fields; entities of conditions and waits. A group among the targets
     (state attribute `entity_id`) is judged with its members. Targets in
     `run_targets.read_only_domains` (sensors, people, zones …) are ignored, entities that do not
     exist are skipped.
   - Each target: domain in the allowlist, not an entity of the integration, in the snapshot
     `entities`, level on the route and quick level for `origin: quick_access` as in step 3 for an
     unsafe action (a scene target stored in the safe direction – lock `locked`, alarm `armed_*` –
     counts as safe), scenes and scripts among the targets need `run: true` and are checked the
     same way (`run_targets.max_depth` levels, deeper → refused; cycles end the walk).
   - Kids (snapshot `kids`): the target's entry and `blocked` (unless released), its bedtime (unless
     a parent release, a bedtime release or a release of the target or of the scene runs, or the
     stored state is `off`/`closed`), and for scenes the color lock (stored light state in a color
     mode or with color or effect attributes) and the volume cap (stored `volume_level` above it).
     Kids locks, alarms and garage doors (blocked device types) therefore never switch through a
     scene or script either. The scene counts once for the hub counter, its targets do not.
   - A failing target refuses the scene or script: with the target's own reason when it is
     `blocked_remote`, `blocked_quick_access` or `blocked_kids*` (`until` of the bedtime), else
     `blocked_group_member` (apps: “devices outside your rooms”).
   - **Targets not determinable.** A scene of another integration (no `entity_id`
     attribute), a script of another integration, and a script with a part that is only known when
     it runs – a template in an action name, its target or its data, a device, area, floor, label or
     registry id that does not exist, `entity_id: all` for an action of an integration (not an
     entity domain), a fired event, an action of an integration without any target (notifications,
     `persistent_notification`, `logbook` and `system_log` excepted). Resolved targets are judged as
     above; what cannot be resolved runs on the scene's or script's release, because the admin released
     it for the device.
     With parental controls it runs only while the family manager has released that scene or
     script (`kids.entities.<id>.release_until`), else `blocked_kids`. Automations and remotes:
     their release covers what they do.
   - **Scene hints** (admin API, `common/scene-hint.json`): the hub judges the same targets in advance
     for the admin UI, so the admin sees a refusal before a device runs into it. `scene_hints` in
     `GET`/`PATCH /api/profiles/{profile_id}` (the profile without a device), in the dry run of that
     `PATCH` (the draft) and in every answer with the effective rules of a device
     (`client-effective.response.json`: own area and adjustments included). Each hint names the
     released scene or script, its areas and the targets that would be refused with
     `$defs/scene_hint_reason` (`outside_areas`, `not_controllable`, `kids_blocked`, `remote`);
     `targets_unknown` marks a scene or script whose targets are not determinable for a device with
     parental controls. Only the static part: bedtime, releases of the family manager and stored
     scene states (color lock, volume cap, safe direction) are decided when it runs. At most 50
     hints; empty when Home Assistant is not reachable. The integration stays the authority.
5. **Kids** (snapshot `kids`): no entry or `blocked` → `blocked_kids`; bedtime unless a parent
   release runs or the action reduces (allowlist `reduces`, toggle of an entity that is on, mute)
   → `blocked_kids_bedtime` (`until`); color lock and a field of class `color` →
   `blocked_kids_color`; volume cap: `volume_set` above it is lowered (`adjusted`), `volume_up` at
   the cap → `blocked_kids_volume`, just below → `volume_set(cap)`. With `rate_limit` (and no
   release) the integration asks the hub (`kids-check`, 3 s); no answer → `kids_hub_unreachable`.
   With `kids.rate_limit_all.enabled` it asks for every entity of the device (pause of
   everything, counted in the hub); `paused_all` → `blocked_kids_paused_all` (`until`).
   **Releases of the family manager** are part of the snapshot and compared with the
   integration's own clock: `kids.bedtime_released_until` (bedtime does not apply),
   `kids.pause_released_until` (no rate limit, no `kids-check`), `kids.entities.<id>.release_until`
   (that entity: `blocked` and bedtime do not apply). A past time counts as no release; the hub sends
   a new snapshot when a release starts or ends.

Route = how HA itself judges `local_only`: Home Assistant Cloud or a public address = `external`, a local
address = `local`, no HTTP request (automation) = `unknown`, treated like `external`. The app does
not declare it (it would not be trustworthy).

Execution: as the system with the caller's call as parent context (`Context(parent_id=…)`): HA's
entity permission check does not apply, the logbook names the device user. Admins and system calls
keep their own context. Rate limit per user: `limits.max_calls_per_minute` (`rate_limited`).
A single rejected entity raises `ServiceValidationError` (`translation_domain` `<ns>`,
`translation_key` = reason, placeholders `entity_id`, `until`); a batch reports per entity
(without `return_response` a partly rejected batch raises `control_partly_denied` after executing
the allowed ones). `check_only` executes nothing and never asks the hub.

## 3. Rule snapshot

`schemas/common/enforcement-snapshot.json`: `client_id`, `ha_user_id`, `control_path`,
`remote_access`, `child_protection`, `entities` (entity → `local`, `remote`, `quick`, `run`), `kids`
(time zone, parent release, releases of the family manager `bedtime_released_until` /
`pause_released_until`, per entity `blocked`, `quiet_hours`, `color_lock`, `volume_max`,
`rate_limit`, `release_until`; device-wide `rate_limit_all`), `location` (effective rule location for
`<ns>.report_location`, [location.md](location.md)), `issued_at`, `rules_hash`. The hub resolves everything (profile, adjustments,
boundaries, areas with own area, `remote_control` incl. safety entities, quick access, kids layers
with the strictest value over several areas).

`rules_hash` = SHA-256 hex of the canonical JSON **without `rules_hash` and `issued_at`**: keys
sorted, separators `,` and `:`, UTF-8 without escaping (`json.dumps(…, sort_keys=True,
separators=(",", ":"), ensure_ascii=False)`). `tools/validate.py` recomputes it for every fixture.

The integration takes a snapshot only if it is valid, the hash matches and `ha_user_id` is the
device user **it created for `client_id`** (so the hub can never grant rights to another HA user).
It stores the snapshots in `.storage` and decides with them while the hub is unreachable.

Transport: push `enforcement_rules` (complete set right after `auth_ok`, then per change;
`complete: true` replaces the set, `removed` drops devices); backstop: the status poll carries
`enforcement.rules_hashes`, and when they differ the integration fetches
`GET /api/integration/enforcement-rules` once per distinct set of hashes. The integration reports
applied snapshots as events `rules_applied` (with `rules_hash` and `ha_group`).
Admins can apply snapshots by hand with the HA action `<ns>.apply_rules` (same checks).

### Control paths next to the snapshots

Both transports carry, next to `snapshots` and outside their versioned body, `control_paths`
(`$defs/enforcement_control_paths`): `client_id` → `checked` | `direct`, the
resolved control path (parental controls and guests give `checked`). It names every device whose snapshot
is in the same message, with the snapshot's value, and – in the REST answer and in the first message of a
push – also every active device with an HA user (or one being provisioned) for which the hub could not
build a snapshot. Such a device is not reported in `removed`: it keeps its HA user, and the hub logs the
failed build as an error.

Why: the integration cannot always take a device's rules – it ignores a snapshot it cannot read (a
snapshot `version` it does not know because the hub updated itself before the integration, a hash
that does not match, a foreign HA user), and the hub may fail to build one. Without this map, a device
whose last taken snapshot says `direct` would remain a full Home Assistant user although the hub
resolves `checked`. The map is kept minimal and stable across snapshot versions. When `control_paths` names a
device with anything but `direct` (an unknown value included) and no snapshot of it is taken from the
message (rejected, or none in it), the integration holds its user read-only (`system-read-only`, the same
hold as for unreadable rules without earlier ones) and keeps its earlier snapshot for the decisions of
`<ns>.control`. A device the map names `direct` without a taken snapshot keeps its earlier snapshot (and
its group). The map never loosens: `direct` does not lift a `checked` snapshot or a hold. A
taken snapshot decides. `tools/validate.py` checks that the map names every snapshot device
with its `control_path`; it may name more devices.

### Which hub

The integration status carries `hub.instance_id` (`$defs/hub_instance_id`, the Bonjour TXT `iid` and the
`hub_id` of onboarding; generated once and kept in the hub's data). The integration stores it in its
config entry on first sight. A status with another id is another hub (hub reinstalled, data lost, or
the entry now points at another host): the integration then removes no device, HA user or token (no
reconcile, no rules from it), raises a repair issue “This is a different hub” and waits. Only after the
admin confirms with the existing reconfigure or reauthenticate flow does it take the new id; from then
on it reconciles against the new hub as usual.

## 4. Kids counter

`POST /api/integration/kids-check {client_id, entity_id, action, grant?}` → `{allowed, reason,
until}`. The hub counts an allowed action. When the hub itself switches for a child device it
passes an opaque `grant` (single use, bound to device and entity, short lived) in
`<ns>.control`; the integration forwards it and the hub answers `allowed` without counting twice.
The hub calls `POST /api/services/<ns>/control?return_response` with the device's token and
`entity_ids` (one entity): a batch answers with the reason per entity instead of raising, also over
REST (a single `entity_id` over REST would only give the translated message with status 400).

**A child's watch shares its phone's kids state**. A watch whose phone
(`set_up_by`) has parental controls resolves with that phone's profile, adjustments, access hours and
kids override (protocol.md, Watches). `kids-check` for the watch's `client_id` counts on the **phone**:
one rate limit, one “pause everything”, one cooldown per entity, and every release or early access a
parent grants applies to both. Using phone and watch together never doubles a limit. The watch's
snapshot carries the phone's kids layers, `override_until` and releases.

## 5. Events

Taxonomy `data/events.json` (kind, category, source, alarm, labels). Every event is fired on the HA
event bus as `<ns>_event` (`ha-event.event.json`); alarm kinds additionally as `<ns>_alarm`
(`ha-alarm.event.json`), immediately and without thresholds, for owners' own automations. Kinds
with source `integration` are created by the integration (control, kids_control, denied,
kids_bedtime_attempt, kids_pause, access_group_restored, direct_access_attempt, integration_started,
integration_outage) and sent to the hub (`POST /api/integration/events`, batches of ≤ 100 every
10 s, ≤ 500 in memory while the hub is unreachable, oldest dropped and counted in `dropped`,
idempotent per `id`). Kinds with source `hub` arrive as push `ha_event` and are only fired.
Data minimization: ids, entity, action name, route, origin, reason, counts and times — never action
data, codes, IP addresses, tokens or names (the HA events add the device name and owner label).

- `direct_access_attempt` is **best effort**: Home Assistant has no event for a rejected action, so
  the integration may miss attempts.
- `integration_outage` is detected at the next start: the integration's last sign of life
  (heartbeat every 10 minutes, final write) compared with Home Assistant's last saved states; a gap
  over 30 minutes means HA ran without the integration (repair issue when checked devices exist).

Notifications at events (`rest/event-notifications.json`): rules with kinds, targets (HA
`notify.*` actions and/or paired devices), filters (devices, persons, profiles, areas, entities,
routes), threshold, bundling and quiet hours; `POST …/test` (also fired as `<ns>_event` with
`test: true`). Thresholds and targets are the hub's job; the HA events are always fired. Storage,
alarms and the admin API of the log tab: [log.md](log.md).

## 6. App: integration not responding (“Switching not possible right now”)

With `client_config.ha_enforcement.control_path = checked` the app switches only through
`<ns>.control` and never falls back to direct actions. The app itself uses the HA WebSocket;
widgets, controls, Siri/Shortcuts and the Watch relay use REST
`POST /api/services/<ns>/control?return_response` with `entity_ids` (one entity) and
`origin: quick_access`, so the answer carries the reason per entity (a single `entity_id` over REST
only gives HTTP 400 with the translated message). Never try a direct action over REST either:
Home Assistant answers a read-only user with 401 and counts it as a failed login (notification
“Login attempt failed”, IP ban when the owner enabled a threshold). It shows the status chip “Switching is not
possible right now – the Halumar integration is not responding” and keeps showing all states when:

1. HA answers a call with error code `not_found` / `translation_key` `service_not_found` for
   `<ns>.control` (the integration is not loaded: removed, disabled, failed to start), or
2. after (re)connecting, `get_services` (allowed for every user) has no `<ns>.control`, or
3. a call times out (10 s) while the HA connection itself is alive.

The chip disappears when `<ns>.control` exists again (check `get_services` on every reconnect and
at most every 60 s while the chip shows). Rejections with a reason (`translation_key` of
`$defs/control_denial_reason`) are not an outage: the app explains the reason per entity.
`rules_missing` means the hub has not delivered the device's rules yet (show “Rules are being
loaded”, retry after `client_config_updated`). `check_only` with one entity can serve as a cheap
health check. The integration's state entities are not a signal (they depend on the hub).
The admin sees the outage as an HA repair issue after the integration is back and as an
`integration_outage` alarm in the log tab.

## 7. Devices on the hub path

A device is **on the hub path** when its profile has parental controls or its effective `control_path`
is `hub`. It reads and switches through the hub wherever the hub is reachable. The hub is never exposed
to the internet, so a device without a key works only at home. A watch is never on the hub path (it has
no hub socket).

| Profile | Key on the device | `client_config` |
|---|---|---|
| Hub only, no remote access | none | `ha_token`, `ha_instance_id`, `ha_enforcement`, `ha_url` null |
| Hub only with remote access | read-only key | `ha_token` (while access is open), `ha_url`, `ha_instance_id`, `ha_enforcement.control_path` `checked` |
| Checked (children may choose it) | read-only key | as for every checked device |

`holds_key` (`tools/profiles_ref.py`): `control_path` is `checked` or `direct`, or `hub` with effective
`remote_access`. For a device with parental controls `client_config.kids.away = ha` exactly when it holds a
key; `kids.control` stays `hub`.

**With remote access a device on Hub only holds a read-only key.** With that key it can read every state
in Home Assistant from anywhere, including the areas and devices its profile hides. It can still switch
only what its profile allows (`<ns>.control`, its HA user is read-only). The admin UI says so where remote
access is switched on for such a device. The admin API tells it which devices that concerns: `hub_remote_now`
(Hub only with remote access right after the change) and `hub_remote_at` (the earliest end of a device
adjustment or of the guest access after which it becomes so) on every device of a preview
(`profile-preview.response.json`; a device the change leaves unchanged is listed only when the change
alters its pair, both computed before and after the change at the same moment, with `changes: []`,
`overrides_removed: []`, `ha_key` and `remote_access` `unchanged` and not counted in `affected_count`) and in
the effective rules of
a device (`client-effective.response.json`) and of a guest extension (`extend.response.json`, also its
dry run), and `hub_remote_pairing` (per access and platform: a device
paired with this profile now) in `profile.json`. A TV or a watch never sets them. There is no relay through the integration.

| | Hub reachable | Hub not reachable, with a key | Without a key |
|---|---|---|---|
| States, history, forecast | hub (`state_subscribe`, `history_get`, `forecast_get`) | Home Assistant (WebSocket, internal URL or `ha_url`) | hub only |
| Camera still images, media artwork | hub (`camera_image_get`, `media_image_get`) | Home Assistant | hub only |
| Switching | hub `control` (the hub checks, then calls `<ns>.control` with the device's token) | `<ns>.control` from the app, no `grant` | hub only |
| Requests of children (“Can I have more time?”) | hub WebSocket | HA WebSocket `<ns>/family` (`kids_request`, `kids_request_cancel`; pushes `kids_request_state` via `<ns>/family/subscribe`) | hub only |
| Location | hub (`location_report`) | `<ns>.report_location` | hub only |
| Widgets, Siri and shortcuts, controls, complications, a watch | with a key as for a checked device (`quick_access`, `watch`), without one off | as for a checked device | off (boundary `hub_only`) |

- **What the hub checks on the hub path.** For every request: the device is paired, active and not a
  watch, and on the hub path (else `control_error {not_hub_controlled}`); its access is open (hours,
  switch, guest expiry: `rule_blocked {access_closed}` for `control`, nothing visible for reads); the
  entity is in its scope: placed visibly in one of its active areas or the `run` target of such a tile
  (else `not_visible`; areas only linked by a notification are readable, not switchable). With parental
  controls also the kids rules, counters, pauses and releases (a `grant` goes with the call; nothing
  else gets one). Then it calls `<ns>.control` with the device's own token; the integration checks the
  allowlist, the area scope, `run` releases, group members and the targets of scenes and scripts, access
  hours on its own clock and its rate limit again. Integration down: `ha_unavailable` or `not_ready`,
  never a fallback. Reads (`state_subscribe`, `history_get`, `forecast_get`, the images) have the same
  scope; the hub limits them per device (x-limits `hub_*` in the AsyncAPI document, `control_error
  {rate_limited}`). Images are read with the hub's own access, at most 2 MiB each, after the scope check:
  access closed, an unknown entity, another domain or an entity outside the scope all answer `not_visible`
  before Home Assistant is contacted or a kids rule is read (protocol.md, Hub path). A key-less device never
  gets a Home Assistant camera token, a signed image URL or any other URL.
- **Not on the hub path:** `remote_control` (the hub is reachable only at home, the route is local);
  `quick_access` (no widgets on the hub path); `control_mode_max` is a display rule of the app, not a
  permission.
- **Keys.** The device's HA user and token always exist; the hub keeps the token encrypted. The user
  stays in `system-read-only`; `local_only` follows `remote_allowed`, so even a leaked key is refused from
  outside without remote access. The hub rotates the token (`ha_key_withdrawn`) whenever the device stops
  holding a key: `control_path` becomes `hub` (profile, adjustment, the end of a temporary checked or
  direct), remote access ends on Hub only (rule, adjustment, its end). When a guest's access ends the hub
  removes the device instead, and the integration removes its Home Assistant user and token
  (`deprovision_client`, reason `guest_expired`). It also rotates the token
  when the access closes (access.md). The old key stops working as soon as the integration has removed
  it; until then it keeps working, and the hub keeps trying. Gaining a key hands out the token the hub already holds, no rotation.
  The rule snapshot carries `control_path` `checked`, `remote_access` and the remote levels like for every
  device.
- **Quick access and the watch** follow the rules: the boundary `hub_only` caps `quick_access` at off and
  `watch` at off while the device holds no key; remote access lifts it. When a temporary remote access or a
  temporary checked or direct ends, both carry that `expires_at` and their value from then on as `then`; a
  temporary checked or direct that a boundary caps ends the same way. A watch holds its key only while its
  phone's effective `watch` is on (`profiles_ref.ha_access` with the phone's rules). **The hub evaluates
  every device again at each `expires_at`**, not only on writes: when a phone's `watch` turns off it removes
  the watch and withdraws its key (`watch_removed_reason`), and it withdraws the key of every device that
  stops holding one. The guest boundary and the Pro features stay as they are.
- **Integration:** `<ns>.control` has no special case for the hub path: the hub's call without a `grant` (route local) and a call
  of the app away from home go through every check of §2; for children `<ns>.control` asks the hub with
  `kids-check` for pauses and the pause of everything (the hub's own call counts once through its grant).
  Hub unreachable → `kids_hub_unreachable` for those devices only when the snapshot needs a counter.
  `<ns>/family` relays `kids_request` / `kids_request_cancel` of a child device; the hub refuses them
  (`family_error not_permitted`) when the device holds no key.
- **App:** `usesHubPath = not a watch or TV and (profile.child_protection or rules.control_path.value
  == hub)` (a `child_protection` without the rule counts as the hub path; a watch and a TV always use their
  key); `holdsKey = ha_enforcement != null or token_error != null` while access is open (for children also
  `kids.away = ha`), see “Key in client_config” below. While the hub is connected the app reads and switches through it; when
  the hub is not reachable and the device holds a key it reads from Home Assistant and switches through
  `<ns>.control` (`entity_ids`, one entity), with the texts of the refusals (`blocked_kids*` → same notices
  as `rule_blocked`, `blocked_remote` → “not from away”, `kids_hub_unreachable` → “not possible right
  now”). Never a direct action. Without a key and without the hub it shows that the hub is not reachable.
  The parental-controls UX (kids notices, requests, family) follows `child_protection`, never the hub path.
- **Key in client_config.** While access is open a device holds a Home Assistant key exactly when `ha_enforcement != null` or `token_error != null` (`holdsKey`; for children `kids.away = ha` says the same). With `ha_enforcement` set the key is usable: `ha_token` carries it (a watch gets it sealed). With `token_error` set the device holds a key that is not usable right now (`ha_token`, `ha_enforcement` null): `pending` = the token has not arrived from the integration yet or the hub holds it back until the integration has the device's rule snapshot; `decryption_failed` = the stored token cannot be read and the hub asks for a new one. Then the app is not on the hub path because of it (only its rule `control_path` hub or parental controls put it there), keeps its stored Home Assistant address, deletes any Home Assistant token it stored before (for every value: the hub sends the usable token again with `client_config_updated`, and a kept one may already be rotated or belong to a user whose group is not yet the one of its profile), uses none, shows that the connection to Home Assistant is being set up and waits for `client_config_updated`. A device on Hub only with remote access stays on the hub path meanwhile: at home it reads and switches through the hub as usual, only the way away waits. With access closed nothing of this is sent and the device holds no usable key.
- **Parental controls need Halumar Pro** in the app on the child's device. Without Pro the child's device
  shows a notice and controls nothing; the hub and the integration enforce the rules either way. Hub only
  itself never needs Pro.
- **Availability.** While the hub restarts or updates, a device on the hub path without a key can neither
  read nor switch. If the integration is down, reading through the hub works and switching answers
  `ha_unavailable`.
- **A child's watch** (`kids_watch`) has no hub socket, so it always switches like a child device away
  from home: `<ns>.control` with its own read-only key (its `control_path` is `checked`, `platform_needs_key`
  when the phone is on Hub only), checked here with the phone's kids rules and the shared counter (§4).
  That is why `kids_watch` needs effective remote access (`requires_remote_access` otherwise), also on
  Checked: a watch is used away from home, and its HA user follows the same `remote_allowed` as the phone's.

## 8. Compliance status away from home

A device that can no longer sign in to Home Assistant asks the integration's compliance view why
(`openapi/ha-compliance-view.openapi.json`). The view needs no token, holds no key and is limited to
one request per second per address (429 `rate_limited`).

- The integration returns a status only when the hub's blob for that client id is `need_token_update` or
  `deleted` and carries `ts` and `sig`; it returns `{v: 1, status, ts, sig}` from that blob. The hub
  signs these two statuses with HMAC over `v1|client_id|status|ts` (`fixtures/crypto/compliance-vectors`).
- Every other case gets the same neutral body `{v: 1, status: "unknown", ts: <now>}`: an unknown client
  id, `compliant`, a missing, unsigned or malformed blob, the view switched off, the integration not
  loaded.
- The app checks the signature, not the age of `ts`. A recorded answer can therefore only repeat a
  restricting status of the same device; it cannot apply to another device or loosen anything. What the
  app does on each status: [protocol.md](protocol.md#compliance-status).
