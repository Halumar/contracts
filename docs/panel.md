# Wall panel as a Home Assistant device

Contract of the wall panel as a Home Assistant device, for Apple and Android tablets and TVs. Status
sensors exist on every device ([Sensors on every device](#sensors-on-every-device)); some actions and
values are reserved; the apps do not offer them yet ([Reserved actions and values](#reserved-actions-and-values)).
Rules marked Pro in the catalog are offered by the app only with Pro.
REST: `openapi/hub.openapi.json` (tags `clients` and `integration`, generated from the hub).

## Model in one paragraph

A wall panel (an iPad or Android tablet in wall panel mode) or a TV (Apple TV, Android TV) gets entities **on the existing
client device** of the integration – no second device, never a `mobile_app` registration. The app reports
its panel status with `client_status` (battery independently of location), the hub keeps only the last value
and decides which entities exist (`panel_ha` in `GET /api/integration/status`). Home Assistant controls the
panel through those entities (`number`, `select`, `button`): integration → `POST /api/integration/clients/{id}/panel`
→ hub checks → WebSocket `panel_command` → app answers `panel_command_ok` / `panel_command_error` within 5 s.
**Only Home Assistant administrators and automations operate panel entities**; device users never, and
`<ns>.control` refuses every entity of the integration itself (`own_entity`). Waking from HA sensors and
brightness from an HA illuminance sensor are profile rules the app applies locally (no automation needed).
**No camera** – neither camera wake nor a stream.

## Status: app → hub

`client_status` (any subset, also together with the other fields):

| Field | Type | Notes |
|---|---|---|
| `battery_level` | int −1…100 | sent independently of the location rule (wall panel profiles have location off) |
| `battery_state` | `charging` · `full` · `unplugged` · `unknown` | `$defs/battery_state`; Apple TV `unknown` |
| `low_power` | bool | low power mode / battery saver |
| `panel` | [`common/panel-status.json`](../schemas/common/panel-status.json) or `null` | By every app with a hub connection; `panel_mode` says whether the wall panel / kiosk is shown; `null` = no status right now |

`panel` fields: `screen` (`active` · `dimmed` · `screensaver` · `night` · `off`; TVs (Apple TV, Android TV) only `active`/`screensaver`/`off`;
outside the panel mode only `active` = app in front and `off` = app left the foreground), `panel_mode` (bool),
`brightness` (actual backlight 0–1, `null` on Apple TV), `brightness_mode` (`auto` · `manual`), `actions`
(capabilities: the `panel_command` actions this app supports), Android only: `illuminance` (lx), `light_sensor`,
`lock` (`none` · `pinning` · `lock_task`, reserved).

When to send: on every change (debounced ~1 s, brightness 500 ms), on every battery level or
battery state change of the system, after every executed panel command, and as heartbeat every 300 s. When the app goes to
the background it sends `screen: off` if it still can. No touch timestamp (presence data).

The hub merges `panel` into the last value (fields not sent stay; kept in memory only – after a hub restart the app resends it on reconnect, so `panel` is `null` for a few seconds), validates enums and ranges and drops invalid
fields silently, and broadcasts `client_status_updated` (admin UIs and the integration re-poll).

## Commands: Home Assistant → app

```
HA entity (number/select/button) or the integration's own call
  → integration checks the caller: HA admin or no user (automation/script); else Unauthorized
  → POST /api/integration/clients/{id}/panel {action, level?, mode?, actor}
  → hub checks (below), sends {"type":"command","command":"panel_command","id":…, "action":…, "level"?, "mode"?}
  → app executes, answers panel_command_ok {id, panel} or panel_command_error {id, code}
  → hub answers 200 {success, client_id, action, panel} or 4xx/504 {detail:{code,message}}
  → integration: state from panel; error → translated HomeAssistantError (never silent)
```

| Action | Meaning | iPad | Apple TV | Android |
|---|---|---|---|---|
| `wake` | like a touch: leave dimmed/screensaver/night | ✓ | ✓ | ✓ |
| `screensaver` | screensaver now | ✓ | ✓ | ✓ |
| `home` | back to the start area (`panel_start`) | ✓ | ✓ | ✓ |
| `reload` | reload areas and states | ✓ | ✓ | ✓ |
| `set_brightness` | `level` 0.05–1, switches to manual until the next phase change | ✓ | – | ✓ |
| `set_brightness_mode` | `mode` `auto` / `manual` | ✓ | – | ✓ |
| `screen_off` | black screen or real off by lock level (reserved) | – | – | – |
| `announce` | `text` (1–300), `volume` 0–100 (capped by `panel_announce.volume_max`), `chime` (default on); rule `panel_announce` (reserved) | – | – | – |
| `show_camera` | `entity_id` (a camera the device may see): open the camera view; live only with `camera_live`; picture-in-picture only by the user (reserved) | – | – | – |

Reserved actions: the apps do not offer them yet.

Hub checks, in this order (error code → HTTP status): unknown device `not_found` (404) · `deactivated` (422) ·
guest `guest` (422) · not a panel `not_a_panel` (422; phone, watch, tablet with rule `kiosk` off) · rule
`panel_remote` off `remote_off` (422) · action not offered for the platform or not in the reported `actions`
`unsupported` (422) · `level`/`mode` missing `invalid` (422) · no live WebSocket `not_connected` (422) ·
no answer in 5 s `timeout` (504). After `unsupported`: `announce` with rule
`panel_announce.enabled` off `announce_off` (422), `show_camera` with a camera outside the device's areas or
no camera `not_visible` (422); `text`/`entity_id` missing `invalid`. App codes (422): `unsupported`, `not_in_panel_mode`, `not_pro` (the app
offers the rule only with Pro), `invalid`, `failed`.

The admin UI uses `POST /api/pairing/clients/{id}/panel` (test buttons, actor `admin_ui`) with the same checks and
answers, and reads the panel card from `GET /api/pairing/clients/{id}/panel`
([`rest/client-panel.response.json`](../schemas/rest/client-panel.response.json)).

## Profile rules (group “Wall panel”)

| Rule | Value | Default | Platforms | Enforced by | Notes |
|---|---|---|---|---|---|
| `panel_remote` | bool | on (off in every suggestion except Wall panel, TV and Kids' room panel) | ipados, tvos, android_tablet, android_tv | hub | “Control from Home Assistant”; boundary guest → off; off = no control entities, every command `remote_off`; Pro |
| `panel_sensors` | list of `battery`, `charging`, `screen`, `brightness`, `illuminance`, `battery_temperature` | battery, charging, screen, brightness | **ios**, ipados, tvos, **android**, android_tablet, android_tv (group “Features”) | hub | which values appear as entities in HA; `screen` = screen state on panels, “app active” elsewhere; TVs (Apple TV, Android TV) only `screen`; `illuminance` only Android with light sensor; no watch |
| `panel_wake` | `{entities: [...]}` (≤ 10: `binary_sensor`, `person`, `device_tracker`, `input_boolean`, `event`) | `[]` | ipados, tvos, android_tablet, android_tv | app | the app subscribes with `state_subscribe` and treats `on` / `home` / a new event like a touch; Pro |
| `panel_brightness` | `{mode: system·fixed·lux·device_lux·schedule, level, lux_entity, min, max, lux_max, curve, schedule}` | `system` | ipados, android_tablet | app | lux: HA illuminance entity (iPad has no light sensor API); log curve, hysteresis ±10 %, ≤ 1 step per 10 s; `panel_night` stays the upper limit; user choice allowed; Pro |
| `panel_announce` | `{enabled, volume_max 0–100, respect_night}` | off, 80, on | ipados, android_tablet | hub | Pro: off = `announce_off`; the hub and the app cap the volume; `respect_night` = text without sound during night mode |
| `panel_off_mode` | `black` · `off` | `black` | ipados | app | the iPad always shows a black screen, also with `off`; Pro |

Android counterparts: `android_tablet` like `ipados`, `android_tv` like `tvos`. Android-only commands and values (`screen_off`, `illuminance`, `lock`, `device_lux`) exist only as reported capabilities: the hub offers an action only when the platform has it and the app lists it in `panel.actions`. No camera rule. Dimming lowers the **real backlight** (the system
brightness plus a light overlay, restored when the app is not active).

Suggestions: `panel_remote` off and `panel_sensors` battery, charging, screen, brightness in every
member suggestion except Wall panel (`panel_remote` on, `panel_sensors` battery/charging/screen/brightness,
`panel_brightness` system), Apple TV (`panel_remote` on, `panel_sensors` screen) and Kids' room panel
(`panel_remote` on, `panel_sensors` battery/charging, fixed – no screen state from a child's room). The
catalog default of `panel_remote` is on.

## Which entities exist (`panel_ha`)

The hub computes `clients[].panel_ha` in `GET /api/integration/status`: `null` for guests, deactivated
devices and platforms without a status (watches, `watchos` and `wearos`: the rule `panel_sensors` does not apply),
otherwise `{sensors, controls}` (also for phones and for tablets without wall panel mode):

- `sensors` = `panel_sensors` ∩ platform (`$defs/panel_ha_sensor`). On a **panel** (tablet with `kiosk` on,
  TV) the rule value `screen` stays `screen`; on **every other device** it becomes `app` (“app active”).
  `tvos`/`android_tv`: only `screen`; `illuminance` only when the app reported `light_sensor: true`.
- `controls` = only panels: empty with `panel_remote` off; else tablets (iPad, Android tablet) all of
  `brightness`, `brightness_mode`, `wake`, `screensaver`, `home`, `reload`; TVs (Apple TV, Android TV)
  `wake`, `screensaver`, `home`, `reload`. Phones and
  tablets without wall panel mode never get controls.

Entities on the existing client device (entity ids from the fixed English object name, never from the
translated name; slug rules like the other entities: no `__`, no `_` at the ends):

| Key | Entity | Id (example device “Kitchen”) | Notes |
|---|---|---|---|
| `battery` | `sensor` battery % | `sensor.halumar_kitchen_battery` | existing sensor; only with `battery` in `sensors` (not without `panel_ha`: guests, watches); keeps the last reported level while disconnected |
| `charging` | `binary_sensor` battery_charging | `binary_sensor.halumar_kitchen_charging` | on for `charging` and `full`; attribute `battery_state`, `low_power`; unavailable while disconnected |
| `screen` | `sensor` enum | `sensor.halumar_kitchen_panel_screen` | panels only: `active/dimmed/screensaver/night/off`; `off` while disconnected; attribute `panel_mode` |
| `app` | `binary_sensor` “App active” | `binary_sensor.halumar_kitchen_app_active` | Every device that is no panel: on = app in front (`screen` not `off`); unavailable while disconnected |
| `brightness` | `sensor` % | `sensor.halumar_kitchen_panel_brightness` | actual backlight (“Screen brightness”); phones/tablets outside the panel only while the app is in front (else unknown); unavailable while disconnected |
| `illuminance` | `sensor` lx | `sensor.halumar_kitchen_panel_illuminance` | Android; unavailable while disconnected |
| `battery_temperature` | `sensor` °C (device_class temperature) | `sensor.halumar_kitchen_battery_temperature` | Android phones and tablets; attribute `battery_health`; unavailable while disconnected |
| control `brightness` | `number` 5–100 % | `number.halumar_kitchen_panel_brightness` | `set_brightness` |
| control `brightness_mode` | `select` auto/manual | `select.halumar_kitchen_panel_brightness_mode` | `set_brightness_mode` |
| controls `wake`, `screensaver`, `home`, `reload` | `button` | `button.halumar_kitchen_panel_wake`, `…_panel_screensaver`, `…_panel_home`, `…_panel_reload` | |

Control entities are unavailable while the panel is not connected; pressing then raises
`panel_not_connected`. Entities that leave `panel_ha` are removed from the entity registry.

## Sensors on every device

The sensors are not limited to wall panels: every device except watches and guests
reports its status, and the integration creates the entities its rule `panel_sensors` allows (catalog
default battery, charging, screen, brightness, set explicitly in every member suggestion). Control from
Home Assistant: only wall panels and TVs, only with `panel_remote` (on in Wall panel, TV and Kids'
room panel).

What each platform delivers, and when (apps never keep running in the background just to report; the
values arrive while the app has its hub connection, after every reconnect and with the 300 s heartbeat):

| Platform | Battery / charging | Screen / app active | Brightness |
|---|---|---|---|
| iPhone, iPad without wall panel mode | always while connected, on every change (battery notifications of the system, level at most once a minute) | `app`: on while the app is in front; `off` is sent when the app leaves the foreground (if iOS still lets it), afterwards unavailable once the connection ends | only while the app is in front; `null` in the background (iOS lets no app read it there) |
| iPad in wall panel mode | as above | `screen` with dimmed / screensaver / night | actual backlight incl. dimming |
| Apple TV | – (no battery, `battery_state: unknown`) | `screen`: in kiosk active/screensaver, without kiosk active while the app is in front, `off` when tvOS sends it to the background | – |
| Apple Watch | – | – | – (a watch has no hub connection; the rule does not apply) |
| Android phone / tablet / TV | like the Apple counterpart | like the Apple counterpart | like the Apple counterpart; tablets also `illuminance` |

Outside the panel mode the app reports `panel_mode: false`; it answers `panel_command` there with
`not_in_panel_mode` (a TV without kiosk: commands are offered but answered like that).

## Who may operate panel entities

- **Home Assistant administrators and automations** (context without a user): yes.
- **Every other user** – device users of the control path “Direct” in `system-users` included – gets
  `Unauthorized` from the entity itself (the integration checks `context.user_id`, like the pairing buttons).
- Devices with the control path “Checked” are read-only in HA anyway; **`<ns>.control` refuses every entity of
  the integration's own platform** with reason `own_entity`
  ([`data/control-allowlist.json`](../data/control-allowlist.json) `own_entities: blocked`), so a child panel with
  all areas cannot dim, wake or reload other panels, and cannot press hub buttons either.
- Guests never get panel entities.

## Log

Every command is an event of the taxonomy ([`data/events.json`](../data/events.json)), category activity, source
hub: **`panel_command`** (executed) and **`panel_command_rejected`** (rejected by the hub or the app, or
timed out), with device, action, error code and actor – no values (brightness level), like every log entry (`ha_admin` + HA user name, `automation`,
`admin_ui`). Both go to the log tab and as `<ns>_event` to Home Assistant; neither is an alarm.

## Battery protection blueprint

No automation engine in Halumar. The integration ships the blueprint
`blueprints/automation/<ns>/panel_battery_protection.yaml` (“Wall panel battery protection”): input battery
sensor of the panel and a switch (smart plug), lower/upper limit (default 20/80 %); the plug switches on at or
below the lower and off at or above the upper limit (hysteresis by design). The admin UI points to it on the
panel card.

## TV

Apple TV and Android TV: status (`screen` `active`/`screensaver`) and `wake`, `screensaver`, `home`, `reload`.
An app cannot switch on the TV set (HDMI-CEC is the system's job; the help points to the TV integrations of
Home Assistant, such as `apple_tv`).

## Reserved actions and values

Defined in the protocol; the apps do not offer them yet. The hub validates and forwards everything below; apps answer what they do not
support with `unsupported` and simply do not list it in `panel.actions`.

- **Status** (`panel`, [`common/panel-status.json`](../schemas/common/panel-status.json)): capabilities
  `pip` (picture-in-picture available), `proximity_sensor`, `device_admin`, `device_owner`,
  `background_connection` (foreground service keeps the hub connection), `nfc` (reader present and on),
  `charge_limit_detected` (the device limits charging itself; the battery protection blueprint is then not
  needed); `lock` adds `device_admin` (`$defs/panel_lock`); Android values `battery_temperature` (°C) and
  `battery_health` (`$defs/battery_health`). The admin UI shows the capabilities as “active / missing”.
- **Commands**: `announce` and `show_camera` (table above), only when listed in `panel.actions`. The
  integration offers them as admin actions `<ns>.panel_announce` and `<ns>.panel_show_camera` (HA admins and
  automations only); the announcement text is never logged.
- **Rules**: `panel_announce` and `panel_off_mode`, `panel_wake.proximity` (boolean, missing = false;
  the proximity value never becomes a Home Assistant sensor), `panel_sensors` value `battery_temperature`,
  `camera_live` also on `tvos`/`android_tv`. Suggestions: **Wall panel**
  `panel_announce` on (80 %, night text only), `panel_off_mode` black, `panel_sensors` plus
  `battery_temperature`; **Apple TV** `kiosk` off and `camera_live` off, both **not fixed** (the
  admin switches them per device); **Kids' room panel** `panel_announce` off and **fixed**,
  `panel_off_mode` black.
- **Default profile**: the Android tablet slot points to **Wall panel**, like the iPad slot; another
  profile can be chosen while setting the device up.
- **Links** for tags and for opening a camera or area: [links.md](links.md).

No camera wake and no stream to Home Assistant: `show_camera` only opens the camera view of
Home Assistant's own camera entity on the device.

