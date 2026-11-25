# Family manager

Contract of the right **family manager** for the hub, the integration,
the admin UI and the apps, on top of the [profile model](profiles.md). Executable reference of the
permission check: [`tools/family_ref.py`](../tools/family_ref.py), vectors
`fixtures/profiles/family-check`. Data: [`data/family.json`](../data/family.json).

## Model in one paragraph

A member device gets the right through the profile rule **`family_manager`** (group Access, off · on,
default off, Fixed checkbox, phones and tablets (`ios`, `ipados`, `android`, `android_tablet`), boundaries guest and parental controls → off, enforcement
`hub`), as profile value (e.g. a profile “Parents”) or as device adjustment (also temporary, “Grandma for
the weekend”). Which children it looks after is a **device property** set by the admin: `scope`
(`$defs/family_children_scope`: all = every device with parental controls, also ones paired later –
the default – or a list of child devices). A family manager changes the kids rules of its children
**in the app**, but every change is a **device adjustment of one child device** (several children share
one profile; the profile stays the admin's), only for the rules in `data/family.json` `manageable_rules`
and only where the child's profile does not fix the rule. It also starts short **releases**, answers
the children's **requests** (“Can I have more time?”), reads their **activity** and gets **child
notifications**. Everything is logged with the actor. Profiles, “Fixed”, devices, guests, notification
targets and the log of adults stay with the admin.

## What a family manager may change

| Rule | Allowed when | Notes |
|---|---|---|
| `kids_quiet_hours` | not fixed in the child's profile | bedtime windows |
| `kids_rate_limit` | not fixed | pauses |
| `kids_rate_limit_all` | not fixed | pause everything |
| `kids_volume_max` | not fixed | |
| `kids_color_lock` | not fixed | |
| `kids_requests` | not fixed | “Can I have more time?” on/off and the kinds (optional) |
| `kids_blocked_types` | not fixed | device types |
| `areas` | not fixed | only areas the family manager sees itself (like the area choice when a device is set up); `mode all` only when it sees all areas |

Never: `kids_exceptions` (always fixed), every other rule (rights, remote access, app settings, display…),
`child_protection`, the profile, “Fixed”. The starter suggestion *Child* leaves
bedtime, breaks and volume **not fixed**, so a family manager can adjust them right away; blocked device
types, colors and exceptions stay fixed. To let family managers change a rule the profile fixes, the
admin unticks “Fixed” (the admin UI offers this when granting the right; `rest/client-family.response.json` `children[].fixed_manageable`).

**Pro:** the rule has `pro: true` in the catalog. The app offers the family view only with Pro on the
family manager's device; the hub shows a hint and does not check it. The suggestion **Parents** (`parent`) is
Adult plus `family_manager` on and fixed (children: all, set on the device), `control_path` direct and
`setup_devices` for the kinds guest, child, panel, tv, house_sitter and babysitter.

Writes: `family_rule_set {client_ids[], rule, value, expires?|expires_at?, note?}` and
`family_rule_reset {client_ids[], rule}` → `family_result {op, results[{client_id, status, reason?}]}`.
Durations and limits are the ones of the profile model (`rule_expiry_preset`, `expiry_limits`). The
stored adjustment carries `origin = family_manager`, `created_by` (device name) and
`created_by_client_id` (`common/device-override.json`); `client_config.rules.<key>.set_by` names who set
it, so the child's app says “Set by Mum” instead of the admin.

**Conflicts:** one adjustment per device and rule, the **last writer wins** – also between a family
manager and the admin. Every write is logged with before/after and actor; all family managers of the
child get `family_child_updated`, the admin UI shows “Adjusted by Mum · 2 min ago”.

## Releases

`family_release {client_ids[], kind, entity_id?, preset}` (`$defs/family_release_kind`):

| kind | Effect until `until` | Needs (not fixed) |
|---|---|---|
| `bedtime` | bedtime does not apply (“1 hour longer now”) | `kids_quiet_hours` |
| `pause` | running pauses end now (per entity and the pause of everything), rate limit and pause everything do not apply | `kids_rate_limit` |
| `entity` | one entity despite blocked type and bedtime | `kids_blocked_types` if the type blocks it, `kids_quiet_hours` during bedtime |

Never released by a family manager: domains in `never_release_domains` (`lock`, `alarm_control_panel`)
and entities the admin blocked in `kids_exceptions`. Presets: `15m`, `30m`, `1h`, `2h`, `bedtime_end`
(maximum `release_max_minutes`). A new release of the same kind (and entity) replaces the running one;
`family_release_end` ends releases early (always allowed). Releases appear in `client_config.kids.releases`
(`common/family-release.json`) and in the rule snapshot of the integration (enforcement stream) so that
`<ns>.control` honors them. The admin's own release (`kids-override`, `override_until`) stays as it is.

A child's watch (kids rule `kids_watch`, protocol.md “A child's watch”) is no child of its own: family
managers see and release the phone, and every release, early access and the admin's release of the
phone apply to its watch as well (one kids state for both).

## Pause everything

The per-entity rate limit (`kids_rate_limit`) counts each entity on its own. The kids rule **`kids_rate_limit_all`** (`$defs/kids_rate_limit_all`)
is a failsafe across all entities of the child device:

```json
{"enabled": true, "max_actions": 12, "max_entities": 4, "window_seconds": 60, "cooldown_seconds": 300}
```

- Within `window_seconds` the hub counts the child device's **successful** actions (all entities) and the
  **different entities** among them. The action that would make it more than `max_actions` actions or
  more than `max_entities` different entities is rejected and starts a pause of **everything** for
  `cooldown_seconds`. Rejected attempts do not count. Values: actions 1–200, entities 1–50, window
  10–3600 s, pause 30–86400 s.
- Both control paths alike: the hub path (WS `control`, `POST /api/client/control`) and
  `<ns>.control` of the integration, which asks the hub (`kids-check`) for every action of a device whose
  snapshot has `kids.rate_limit_all.enabled` (also entities without `rate_limit`). Counter and pause live
  in the hub (in memory, a hub restart ends a pause, like the other pauses).
- **Reason codes** while everything is paused (until = end of the pause):

  | Where | Field | Value |
  |---|---|---|
  | App (WS `rule_blocked`, 403 of `POST /api/client/control`) | `reason` | `paused_all`, `level` `profile`, `until`, `retry_after`, `limit {max_actions, max_entities, window_seconds}` |
  | Integration `kids-check` answer | `reason` | `paused_all` |
  | `<ns>.control` / log / `<ns>_event` | `reason` | `blocked_kids_paused_all` (kind `kids_pause` for each rejected attempt) |
  | Start of the pause (once per pause) | event kind | `kids_paused_all` (log activity, `<ns>_event`, notifications at events) with `entity_id`/`action` of the attempt that started it and `until`; the log entry adds `detail {trigger: actions\|entities, actions, entities, window_seconds}` |

- **Display:** `client_config.kids.paused_all_until` (child app: grey out everything, show the end time;
  the hub sends `client_config_updated` when the pause starts and when it ends early),
  `family_children[].status.paused_all_until` (family app) and `GET …/kids-status` `paused_all_until`
  (admin UI). The rule itself is in `client_config.rules.kids_rate_limit_all` (and in the family view
  `rules.kids_rate_limit_all` with `manageable`).
- **Ending it early:** a running release of kind `pause` (family manager, admin, or the answer Yes to
  “End pause” / `end_pause`), the admin's parental release (`kids-override`) and “End pause” in the
  admin UI (`DELETE …/kids-override?action=lift`) end the pause of everything together with the other
  pauses and suspend the limit while they run. The release kind `pause` still needs `kids_rate_limit` not
  fixed (one “break” switch for parents).
- **Family managers** may change the rule when it is not fixed (`manageable_rules`), like the breaks. The
  starter *Child* has it on and not fixed; the age suggestions fix it; *Teen* is looser
  (30 actions / 10 devices). The catalog default is **off**.
- **Parents are told only when the admin wants it:** `kids_paused_all` is a normal event of “Notifications
  at events” (`rest/event-notifications.json`, off unless the admin adds a rule with this kind and
  targets: HA `notify.*` and/or devices). The taxonomy limits it to **one message per child and rule
  every 15 minutes** (`data/events.json` `notify_min_interval_minutes`); further pauses within that time
  go out as one bundled message at its end. It is not part of the automatic child notifications of family
  managers (`notify_defaults`). The log entry and `<ns>_event` are always written.
- **Texts for children:** short and factual, no slang, e.g. DE “Pause – alles geht um 14:05
  wieder.”, EN “Break – everything works again at 14:05.”

## Requests of the children

0. **Optional per child:** the kids rule **`kids_requests`** (`$defs/kids_requests`
   `{enabled, categories}`, Fixed checkbox like every rule, catalog default on with all kinds;
   suggestions: Toddler off; Child, Child 6–9, Child 10–12, Teen on with all kinds) decides whether a
   child may ask at all and for what. Off = the app shows no request button and the hub refuses
   `kids_request` with `family_error {requests_disabled}`. Not fixed → family managers change it per
   child like the other manageable rules (`family_rule_set {rule: kids_requests}`).
   **How the app reads it:** the child app shows “Can I have more time?” only when
   `client_config.kids.requests.enabled` is true and offers exactly `kids.requests.categories`; the hub
   computes both from `rules.kids_requests.value` (enabled, categories) ∩ the house settings
   (`requests_enabled`, `categories`, `GET/PUT /api/settings/family`) and only when a family manager
   looks after the child. `rules.kids_requests` itself is for display (“Turned off by Mum”,
   `set_by`); the family app edits it in the child detail (`family_children[].rules.kids_requests`
   with `manageable`). `tools/validate.py` checks that `kids.requests` never offers more than the rule.
1. The child device (over the hub WebSocket; away with remote access over `<ns>/family`, below) sends `kids_request {category,
   entity_id?, note?}` – categories `stay_up`, `unlock_device`, `end_pause` (`data/family.json`
   `request_categories`). `client_config.kids.requests` tells the app whether asking is possible
   (`enabled`: requests on, and a family manager of this child or an admin target for
   `kids_release_requested` exists), the categories, the open request, the cooldown and
   **`recipients`** – who gets a request right now, `{name, role}` with role `family_manager` or
   `babysitter` (family managers first, then the active babysitters). The app names them
   (“Dad and Mum will get your question.”, plural by count). The hub sends `client_config_updated`
   to the child whenever the active babysitters change (access opens or closes, a babysitter comes
   home or leaves, a rename).
2. Limits: one open request per child device, `child_requests_per_hour` (default 6), after a No the same
   category waits `decline_cooldown_minutes` (default 15) → `family_error {request_limit|cooldown,
   retry_after}`.
3. Delivery: `family_request` to every connection of every family manager of the child (at home over
   the hub WebSocket, away through `family_relay` → integration → HA WebSocket subscription), the
   event `kids_release_requested` (HA event `<ns>_event`; HA notify targets chosen by the admin plus the
   `notify_targets` linked to the family managers; for `notify.mobile_app_*` with the actions of
   `notify_actions`), and the admin UI.
4. Answer: `family_answer {request_id, answer, preset?, message?}` (app), `POST
   /api/family/requests/{id}/answer` (admin) or a notification button (`POST
   /api/integration/family/notify-answer {token}`; token 16 random bytes, single-use, bound to request and
   action, hub stores only SHA-256). **First answer wins**; later ones get `family_error
   {already_answered, request}`. Yes is carried out as a release with the checks above (`can_approve`
   tells the app beforehand); a Yes that would loosen a fixed rule is refused and the request stays open
   for the admin.
5. Timeout: `request_timeout_minutes` (default 10) → `expired`. The child gets `kids_request_state` on
   every change and sees child-friendly texts (`child_texts`, `decline_messages`).

### Answer buttons of Home Assistant notifications

For every `notify.mobile_app_*` target the hub calls the notify service itself (Supervisor API) with
`data.tag = "<ns>-family-<request_id>"` and one action per `notify_actions` entry; the action identifier is
`<NS>_FAMILY_<token>` (`<NS>` = namespace in upper case, token = 22 characters base64url of 16 random
bytes, its own token per button). A tap fires the HA event `mobile_app_notification_action {action}`; the
hub receives it on its own HA WebSocket connection, looks the token up (SHA-256), and answers exactly like
`notify-answer` (actor = the family manager the target is linked to, route `ha_notification`). No
integration code is needed for this; `POST /api/integration/family/notify-answer` stays for integrations
that relay the event themselves. Once the request is answered, expired or withdrawn the hub sends
`message: clear_notification` with the same tag to the targets. Other notify services get the text without
buttons. Without HA targets a request only reaches open apps and the admin UI (no push of our own).

Admin UIs get the broadcast **`family_changed {client_ids, request_id?}`** (ADMIN audience, ids only) on
every change of requests, releases, scopes, family settings and family adjustments and reload
`GET /api/family`.

## Babysitters

A device of kind `babysitter` with the rule `babysitter_requests` also receives the children's requests
while its access is open and it is connected to the hub (at home); it answers with `family_answer`
(`no`, or `yes` with `15m`, `30m` or `access_end` = end of its access window) and nothing else. Details,
limits and the reason for a profile rule instead of a house setting: [access.md](access.md#babysitter-answers-the-childrens-requests).
Reference: `tools/family_ref.py` `babysitter_check`, vectors `fixtures/profiles/family-check/babysitter.json`.

## Activity and notifications

`family_get_activity {client_id?, kinds?, since?, limit?, cursor?}` → `family_activity {items, summary,
next_cursor}`: read view of the log, children in scope only, `activity_days` back (default 7) and
never longer than the log retention. Items (`common/family-activity-item.json`) contain no IP addresses,
no action data and nothing about adults.

Automatic child notifications (`notify_defaults`): every family manager device gets
`kids_release_requested` (always), `kids_request_answered`, `kids_bedtime_attempt`, `kids_pause`,
`family_change` (on) and `kids_control` (off) for its children – in the app while it is open, and on the
HA notify targets the admin linked to it. `family_notify_set` switches the switchable ones. Event
kinds of the event taxonomy (`data/events.json`, category kids, source hub): `kids_release_requested`,
`kids_request_answered`, `kids_request_expired`, `family_change` (rule change or release by a family
manager). The hub feeds them into the log tab (activity) and the notifications at events like every hub
event, and hands them to the integration (`ha_event` → `<ns>_event`).

## Away from home

The hub is only reachable at home. Away, the app sends the same family messages through Home Assistant:
HA WebSocket command `<ns>/family` `{message}` → the integration maps `connection.user` to the Halumar
device whose HA user it is (refuses everybody else), calls `POST /api/integration/family {client_id,
message}` and returns the hub's messages; `<ns>/family/subscribe` receives the pushes the hub sends with
`family_relay`. Needs effective remote access on the family manager device (`client_config.family.remote
= away`); otherwise `home_only`. The hub decides everything; the integration only relays and rate-limits
per HA user.

**Child devices away:** a child device that holds a Home Assistant key (`client_config.kids.away
= ha`: Checked, or Hub only with remote access) sends `kids_request` and `kids_request_cancel` the same way (`<ns>/family`) and gets
`kids_request_state` as answer and, while it is not connected to the hub, as push over
`<ns>/family/subscribe` (`family_relay` with the child's id). For a device without a key the hub answers
`family_error {not_permitted}` (such a device cannot reach Home Assistant anyway).

**Early access:** the same command and subscription carry the early access messages of recipient
devices away from home (`access_requests_get`, `access_request_answer`; pushes `access_request_update`,
`access_requests`, `access_request_error`, docs/access.md#early-access). A device asking for early access
is closed and holds no valid HA key, so `access_request` through the relay gets `access_request_error
{home_only}`.

Forms (schemas): command `schemas/integration/ha-ws-family.command.json`
(`{id, type: "<ns>/family", message}`), HA answer `{id, type: result, success: true, result}` with
`result` = `ha-ws-family.result.json` = the body of `POST /api/integration/family` (`messages[]`, 1–10
hub messages, unchanged; hub away → `[family_error {reason: hub_unreachable}]`); subscription
`ha-ws-family-subscribe.command.json` (`{id, type: "<ns>/family/subscribe"}`, result `null`), then one
HA event message `{id, type: event, event}` per push with `event` = `ha-ws-family.event.json` = the hub
push itself (e.g. `family_request`), not wrapped. Command names: `namespace.json`
`ha_ws_family_command`, `ha_ws_family_subscribe_command`.

## Checks of the hub (fail closed)

Every family message: authenticated paired device · access member · no parental controls · effective
`family_manager` now · target is a child device in scope · rule manageable and not fixed · no boundary
decides it on the child device · value valid (`profile-rule-values.json`) · areas within own areas ·
release allowed (`family_check`) · limits (`family_writes_per_manager` 30 / 10 min, reads 60/min, answers
60/h). Losing the right (rule off, adjustment expired, profile changed) takes effect at once; running
releases and adjustments it set stay until they end (they are rules of the child, not of the manager).

## Messages and endpoints

| Direction | Message / endpoint | Schema |
|---|---|---|
| app → hub | `family_get_children`, `family_rule_set`, `family_rule_reset`, `family_release`, `family_release_end`, `family_get_requests`, `family_answer`, `family_get_activity`, `family_notify_set` | `ws/client/family_*.json` |
| child → hub | `kids_request`, `kids_request_cancel` | `ws/client/kids_request*.json` |
| hub → app | `family_children`, `family_child_updated`, `family_result`, `family_requests`, `family_request`, `family_activity`, `family_notify`, `family_error`, `kids_request_state` | `ws/server/*.json` |
| hub → integration | `family_relay` | `ws/integration/family_relay.json` |
| admin | `GET/PUT /api/pairing/clients/{id}/family`, `GET /api/family`, `GET/PUT /api/settings/family`, `POST /api/family/requests/{id}/answer` | `openapi/hub.openapi.json` (tag `family`) |
| integration | `POST /api/integration/family`, `POST /api/integration/family/notify-answer` | same |
| client_config | `family` (manager), `kids.requests`, `kids.releases` (child), `rules.*.set_by` | `common/client-family.json`, `common/client-kids-requests.json`, `common/family-release.json` |

Audit kinds: `family_scope_set`, `family_rule_set`, `family_rule_reset`, `family_release`,
`family_release_end`, `kids_request`, `kids_request_answered`, `kids_request_expired`,
`family_settings_changed`, each with actor (`common/family-actor.json`) and route.
