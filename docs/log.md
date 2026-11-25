# Log tab

The log builds on the event taxonomy (`data/events.json`, `POST /api/integration/events`,
`<ns>_event`/`<ns>_alarm`). The admin endpoints
are in the OpenAPI snapshot `openapi/hub.openapi.json` (tag `log`), the admin broadcasts
`log_entry`/`log_read` in the AsyncAPI.

## 1. Storage and retention

- One table in the hub (`event_log`), three categories: `activity` (who switched what),
  `change` (profile audit, pairing, removal, guests, parent releases, integration starts),
  `alarm` (rejections from a threshold, direct access attempts, integration outages).
- Retention **7, 30 (default) or 90 days** (`rest/log-settings.json`), nightly clean-up from 03:00
  in Home Assistant's time zone; entries older than the retention are never returned, also
  before the clean-up ran. Stored across restarts and updates.
- Names (device, owner label, profile) are stored with the entry; while the device/profile
  exists the current name is shown (`device_exists`, `profile_exists`).
- **Hidden people** (`hidden_owners`, owner labels): their **activity** is not stored at all
  (also not notified); changes and alarms stay.
- Data minimization: never action data (values, codes), IP addresses, PINs or tokens.

## 2. Sources

| Source | Category | Kinds |
|---|---|---|
| Profile audit (every `profile_audit_action`) | change | the action; `event_kind` `profile_changed` for `profile_assigned`/`profile_updated`, `adjustment_expired` for `override_expired` |
| Pairing | change | `device_paired` / `guest_paired` |
| Delete, kick, leave, revoke, guest expiry | change | `device_removed` (`device_revoked` with `event_kind` `device_removed`), `guest_expired`; the hub removes the device and has the integration remove its Home Assistant user and token (`deprovision_client`, reason `guest_expired` at guest expiry) |
| Guest invitation (admin PIN or member device) | change | `guest_invited` |
| Access of a device opens or closes ([access.md](access.md)): window start/end, access switch | change | `access_opened` / `access_closed` (`detail.reason` schedule/switch, `detail.until` or `detail.opens_at`, `detail.by` admin/ha) |
| Early access ([access.md](access.md#early-access)): a device outside its access hours asks, a recipient or the admin answers, nobody answers, the admin ends it | activity/change | `access_requested` (activity, `detail.request_id`/`note`/`recipients`), `access_request_answered` (change, actor = who answered with route, `action` yes/no, `until`, `detail.duration`/`message`), `access_request_expired`, `access_request_cancelled` (activity), `access_early_ended` (change, admin); `access_opened`/`access_closed` with `detail.early` |
| Device or guest set up by a member device ([setup.md](setup.md)) | change | `device_set_up` (`actor` = setting-up device, `detail.kind`, `detail.method` onboard/invite, `detail.set_up_by`; “Child's iPhone set up by Dad as Child 6–9”), next to `device_paired`/`guest_paired` |
| A device stops holding a Home Assistant key (Home Assistant access set to Hub only, remote access ends on Hub only) | change | `ha_key_withdrawn`, written once the integration has accepted the replacement: the token the app held no longer works, the hub keeps the new one for the hub path |
| Parent release / lift pause | change | `kids_release`, `kids_pause_lifted` |
| Hub: pause of everything of a child device starts (both control paths) | activity | `kids_paused_all` (once per pause, `until`, `detail.trigger`/`actions`/`entities`/`window_seconds`); rejected attempts during it `kids_pause` with reason `blocked_kids_paused_all` |
| Hub path (the hub calls `<ns>.control` with the device's token; with parental controls also a grant) | activity | with parental controls `kids_control`, otherwise `control`; rejections by the hub or by the integration `kids_bedtime_attempt`, `kids_pause`, else `denied` (reason as `control_denial_reason`); `source hub`, `control_path hub` – one entry per call |
| HA `call_service` event of a device user (control path **direct**) | activity | `control`, `source: ha`, `control_path: direct` – mapped by `context.user_id` = the device's HA user; calls of `<ns>.*`, devices on the hub path and checked devices are skipped |
| `POST /api/integration/events` | activity/alarm/change | as the taxonomy; one intake (repeated ids dropped while the hub runs), the log stores new events as a sink, idempotent across restarts (`uid int:<id>`); `rules_applied` accepted, not stored; activity of devices on the hub path is not stored twice (the hub records its own calls, see below; for a device without parental controls the report of a call the hub made itself is dropped) |
| Hub: integration push session down ≥ 1 min | alarm | `integration_outage` with `detail.live`, `until` when it is back |
| Hub: expiring guests (24 h) and temporary adjustments (1 h) | change | `guest_expiring`, `adjustment_expiring` |

**Alarm from rejections**: a single rejection is activity ("not carried out");
from `alarm_threshold` (default **3 in 10 minutes per device**) the hub adds one alarm `denied`
with `count`, `since`, `detail.derived`, `detail.window_minutes`, `detail.entities`. At most one
such alarm per device and window.

## 3. Admin API

`GET /api/log` (filters category, range `today`/`7d`, client_id, owner, profile_id, area_id,
kind, q, unread, important; paging `before_id` + `limit`), `GET /api/log/export` (same filters, no paging,
max 20 000; the admin UI builds the CSV: `;`, UTF-8 with BOM, optional without people's names),
`GET /api/log/summary` (unread alarms, counts, facets, retention, hidden people, integration
connected, namespace), `POST /api/log/read` (`{ids}` or `{all: true}` → `{marked}`),
`GET/PUT /api/log/settings`, `GET /api/log/notify-targets` (HA `notify.*` actions without
`notify.send_message`; **every paired device** except watches (they show their phone's
notifications, [protocol.md](protocol.md#watches-access-through-the-phone)), also children –
shown in the app while the device is at home, through the hub channel – and guests until their
access ends; `kind`
member|child|guest, `expires_at`), `GET/PUT /api/settings/event-notifications` and
`POST /api/settings/event-notifications/test`. A device that is deleted or whose guest access ends is
removed from all rules (targets and filters); a rule left without target is switched off; a target
that is gone is skipped (`device_gone`).

**Important**: an entry is important when its category is `alarm` or its `event_kind`
or `kind` is marked `important` in `data/events.json` (devices paired or set up, guests paired,
expiring or expired, profile changes, family changes, children's requests and their answers).
Every entry carries `important`; `important=true` filters on the same rule, so the overview card
"Recent important" needs one request and never loses an entry behind other changes.

Admin broadcasts (WebSocket, audience ADMIN): `log_entry` (data = entry of `common/log-entry.json`)
and `log_read` (`{ids, all}`). The integration push session never gets them (entries carry names,
and they are no reason to re-poll the status).

## 4. Notifications at events (`rest/event-notifications.json`)

Details of the rules:

- `retention_days` only **7, 30, 90**; the same value as `log-settings.retention_days`.
- `quiet_default {start, end}`: global quiet hours of the UI; rules copy them into `quiet_hours`.
- Optional rule fields `lead_minutes` (expiring kinds: notify this long before the end; null =
  guests 1440, adjustments 60) and `delay_minutes` (`integration_outage` detected by the hub: notify
  after this long; null = 5). With `integration_outage` **and** `integration_started` in one rule,
  "back again" is only sent after a reported outage.
- PUT: the hub does **not** check notify targets against Home Assistant (HA may be down);
  `422 notifications.no_target` only for enabled rules; `422 notifications.device_unknown` for
  devices that are not paired, watches and expired guests; children and guests are allowed;
  `422 notifications.duplicate_id`.
- Thresholds count per device (`client_id`) within the rule; the rejection threshold of the log
  (alarm `denied`) is `rest/log-settings.json` `alarm_threshold`.

**Send test** (`POST …/test`, `rest/event-notifications-test.request.json`): a stored rule
(`rule_id`) or an unsaved draft (`rule`, the edit panel tests before saving). The hub sends a test
message to every target and answers per target (`rest/event-notifications-test.response.json`:
`handed_over` | `failed` | `shown` | `waiting_for_app`, `error`). It also pushes the first kind of
the rule as `ws/integration/ha_event` with **`test: true`**; the integration fires a test of **any**
kind (also kinds with source `integration`) as `<ns>_event` with `test: true` (alarm kinds also as
`<ns>_alarm` with `test: true`), so owners can try their automations and filter tests out. Answer
`ha_event`: `handed_over` or `integration_not_connected`.

Taxonomy: the hub also emits `adjustment_expiring`, `guest_expiring` and records its own live
detection of `integration_outage` (push session of the integration gone ≥ 1 minute) in the log; the
HA event of an outage stays the integration's (source `integration`, fired after its restart).

## 5. Notifications (hub)

The hub sends through its own Home Assistant connection (`notify.<service>` with title = brand,
message without values) and as device notifications of the hub (shown while the app is open, no
push). Per rule: threshold per device, quiet hours (alarm kinds are collected and sent at the end,
others dropped), bundling (one summary after `bundle_minutes`). Kinds with
`notify_min_interval_minutes` in the taxonomy (`kids_paused_all`, 15) go out at most once per
device and rule in that time; later ones are bundled and sent when it ends. Thresholds, bundles and quiet-hour
queues live in memory (a restart forgets a half-full window; the log keeps everything); expiring
and outage notifications are marked persistently so they are never sent twice. The entry records
where it was notified (`detail.sent`). "Handed over" means Home Assistant accepted the call; no
delivery promise (Halumar is not an alarm system).
