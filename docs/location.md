# Location

Halumar asks for the location actively (after pairing and later when needed).
Apps never call `device_tracker.see` or any other Home Assistant action for the location and never use
`mobile_app`. Same on iOS and Android. There are two ways, depending on whether the device holds a Home
Assistant key:

| Device | Way | Where |
|---|---|---|
| Off the hub path (Home Assistant access checked or direct, without parental controls) | integration action **`<ns>.report_location`** | at home; away only with effective `remote_access` (otherwise the device user is `local_only` and Home Assistant refuses it from outside) |
| On the hub path (Hub only, or parental controls) | hub: **`location_report`** (WS) / `POST /api/client/location`; with a key and the hub not reachable `<ns>.report_location` | at home through the hub (it is reachable only in the home network) |

Why not `device_tracker.see`: a device with the control path “checked” is read-only in Home
Assistant. A direct `device_tracker.see` is refused with 401 and counts as a failed login towards the IP
ban. `<ns>.report_location` is callable by every authenticated user, like `<ns>.control`, and
decides itself. A device on Hub only without remote access has no key at all.

## Profile rules

| Rule | Key | Values | Who | Default |
|---|---|---|---|---|
| Share location with the hub | `location` | `off` · `foreground` · `background` | profiles of kind `person` and `child` (`profile_kinds`); phone platforms `ios`, `android` | `off` |
| Location required | `location_required` | `false` · `true` | same; only while `location` is not `off` | `false` |

- Both rules have the checkbox “Fixed” and device adjustments like every rule.
- Every other kind (`guest`, `babysitter`, `house_sitter`, `panel`, `tv`) resolves to `not_applicable` /
  `requires_profile_kind`: these devices are never asked. A person profile on a guest access is capped at
  `off` (`boundary_guest`).
- `location_required` while `location` is `off` (profile, adjustment or boundary) resolves to
  `not_applicable` / `requires_location`.
- `location` is the upper limit. The person decides in the operating system; the app never shares more
  than the rule allows. `foreground` = only while the app is in use; `background` = also when the app is
  closed (“Always”).
- Enforcement: `app` (control path direct: the device user could call Home Assistant itself); `ha` with
  the control path checked (read-only user, only `<ns>.report_location`); `hub` on Hub only.
- The rule snapshot of every device (`enforcement-snapshot.json`) carries `location` (effective value,
  `off` when the rule does not apply). Both ways check against it.
- Suggestions (data/profile-suggestions.json): Adult and Parents `background`, not required; every child
  suggestion (Child, Toddler, Child 6–9, Child 10–12, Teen) `foreground`, not required (presence
  while the app is in use; tracking a child in the background is an explicit decision of the parents, who
  raise it per profile or device). All other suggestions do not have the rule.

## What the app does

1. **After pairing** (rule `location` not `off`): a short Halumar explanation, then the system dialog
   for “While using”. “Always” only as a second step and only when the rule is `background`.
2. **Later when needed**: from the settings or a notice. Never more than the rule allows.
3. **Notice**: `location_required` true and nothing shared → a **lasting notice on the home screen**
   until the location is shared. Otherwise (only allowed) a calm row in settings/status and a one-time
   notice.
4. **Status**: `client_status.location_shared` (`none` · `foreground` · `background`) after `auth_ok`
   and on every change (permission changed in the system, rule changed); `none` also when the rule is
   `off`. Away from home the status travels with each report (`location_shared` field).
5. **Reports**: with a key `<ns>.report_location` over the Home Assistant connection in use (WebSocket
   `call_service` or REST `POST /api/services/<ns>/report_location?return_response`); on the hub
   path `location_report` over the hub socket, without a socket `POST /api/client/location` (at
   home only; away the fix is dropped, not queued). `background: true` for every fix taken while the app
   is not in the foreground. When the rule goes to `off` the app stops at once.

## Fields (both ways)

```json
{"latitude": 47.3769, "longitude": 8.5417, "accuracy": 12.0, "altitude": 408.0,
 "vertical_accuracy": 4.0, "speed": 0.0, "course": 90.0, "battery_level": 80,
 "background": false, "ts": "2026-11-21T18:00:00Z", "location_shared": "background"}
```

| Field | Type | Meaning |
|---|---|---|
| `latitude`, `longitude` | number, required | WGS 84 degrees |
| `accuracy` | number 0–100 000, required | horizontal accuracy in m |
| `altitude` | number or null | m above sea level |
| `vertical_accuracy` | number ≥ 0 or null | m |
| `speed` | number ≥ 0 or null | m/s |
| `course` | number 0–360 or null | degrees |
| `battery_level` | integer 0–100 or null | stored like `client_status.battery_level` |
| `background` | boolean, required | fix taken while the app was not in the foreground |
| `ts` | timestamp, required | time of the fix (UTC) |
| `location_shared` | `none` · `foreground` · `background` or null | what the app shares now (optional) |

Checks, the same on both ways (`$defs/location_report_reason`):

| Reason | Hub (REST status) | Action | When |
|---|---|---|---|
| `invalid_request` | 422 | (schema error of the action) | a field is missing or out of range |
| `not_hub_controlled` | 403 | – | the device holds a Home Assistant key: use `<ns>.report_location` |
| `location_stale` | 422 | ✓ | `ts` older than 15 min or more than 5 min in the future |
| `location_not_allowed` | 403 | ✓ | effective `location` is `off` or not applicable (kind, platform, guest, expired guest access) |
| `location_background_not_allowed` | 403 | ✓ | `background: true` while the rule is `foreground` |
| `rate_limited` | 429 | ✓ | less than 5 s after the last accepted report of the device; hub: `retry_after` (REST header `Retry-After`) |
| `not_a_device` | – | ✓ | caller is no device user of the integration |
| `rules_missing` | – | ✓ | no rule snapshot for the device yet |

Answers never contain coordinates. `applied: false` = the fix did not reach Home Assistant: it is older
than the last one of the device and was ignored, or (hub way only) no integration took it because none is
connected; then the hub does not count it as the newest fix, so the same fix is new again later.

## `<ns>.report_location` (integration action)

Fields `schemas/integration/ha-report-location.request.json`, answer `ha-report-location.response.json`
(`{applied}`, `return_response` true). Refusals raise `ServiceValidationError` (translation_domain
`<ns>`, translation_key = reason). The integration:

1. resolves the caller (`context.user_id`) to its device and rule snapshot (`not_a_device`,
   `rules_missing`);
2. checks `location` of the snapshot, the age of `ts` and the rate limit;
3. updates the device's `device_tracker` (no HA entity check, the integration writes its own entity);
4. sends the hub only metadata: `POST /api/integration/location-status {client_id, background, ts,
   location_shared, battery_level}` (best effort, never coordinates).

## Hub way (`location_report`, devices on the hub path)

- WS `location_report` → `location_report_ok {applied}` / `location_report_error {reason,
  retry_after?}`. REST twin `POST /api/client/location` with `Authorization: Bearer <device secret>`
  (like `/api/client/control`; 401 for an unknown, revoked or deleted device), body without `type`.
- The hub checks the effective rule at the moment of the report (resolver incl. adjustments, boundaries
  and guest expiry) and the rate limit, hands the fix to the integration (`client_location` on the
  integration push session) and **keeps no position** (no database, no memory, no backup). The
  integration checks the rule of its snapshot again.
- Away from home the hub is not reachable; reports resume at home.

## Status in the hub

- `location_shared` and `location_at` (time of the last accepted fix) per device, in memory: from
  `client_status.location_shared`, from hub reports and from the action's metadata
  (`location-status`). A background fix proves at least `background`, a foreground fix at least
  `foreground`.
- Admin UI: `paired-client.location_rule` / `location_required` (effective rules), `location_shared` /
  `location_at` and the broadcast `client_status_updated`.
- Log: only metadata (device, way, accepted or reason, background) – never coordinates.

## Integration

- `device_tracker` per device (existing entity, source GPS): position, `gps_accuracy`, attributes
  `altitude`, `vertical_accuracy`, `speed`, `course`, `client_id`, `battery_level`. Restores its last
  fix after a Home Assistant restart.
- Snapshot `location` becomes `off` → the tracker forgets the fix (state unknown).

## Admin UI

- Profile editor: group “Location” with “Share location with the hub” (off / while using / also in the
  background) and “Location required”, each with “Fixed”. For kinds other than person and child the
  group shows “Only for profiles of kind …”.
- Device page: “Location: shared in the background / only while in use / not shared”, with
  “(required)” when `location_required` is true and nothing is shared; “unknown” while the device has
  not reported since the hub started.
