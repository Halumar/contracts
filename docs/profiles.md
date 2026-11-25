# Profiles

Contract of the profile model for the hub, the admin UI and the apps. Executable reference: [`tools/profiles_ref.py`](../tools/profiles_ref.py) (materialize,
resolve, expiry). Test vectors: `fixtures/profiles/resolve` and `fixtures/profiles/expiry`.

## Model in one paragraph

Every device has exactly **one profile**. Profiles are created freely by the admin (at most 50): empty,
from a **suggestion** (copied; an update of the hub never changes an existing profile or device) or
from a device. A profile holds one value per **rule** of the catalog (`data/profile-rules.json`) and,
per rule, the checkbox **“Fixed”** (`fixed`: no device adjustment possible) or “Adjustable per device”,
and for comfort rules the value **“User's choice”** (`user_choice`: the person at the device decides,
the profile value is the starting value). A **device adjustment** (`device-override.json`) changes one
rule that is not fixed on one device, permanently or **until a time** (`expires_at`). Over everything lie
**three boundaries**: the **guest access** of the device (set when pairing, expires), the profile switch
**parental controls** (`child_protection`: every action is checked – by the hub where it is reachable,
otherwise, when the device holds a key, through the integration action `<ns>.control`) and **Hub only**
(the effective rule `control_path` is `hub`: the device holds no Home Assistant key unless remote access
gives it a read-only one, and features that need a key are off). Boundaries only ever restrict. The hub resolves everything; the apps
receive only effective values with their source.

## Rule catalog

| Group | Rule | Key | Values (strict → loose) | Catalog default | Fixed checkbox | User's choice | Platforms | Class | Pro | Boundaries | Enforcement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Access | Remote access | `remote_access` | off · on | off | yes | – | Phone, Tablet, TV, Watch | critical |  | – | ha |
| Access | May always allow unencrypted | `connection_insecure_http` | off · on | off | yes | – | Phone, Tablet, TV | critical |  | G→off (boundary_guest); K→off (boundary_child_protection) | app |
| Access | Home Assistant access ([enforcement.md](enforcement.md#1-control-path)) | `control_path` | hub · checked · direct | checked | yes | – | Phone, Tablet, TV, Watch (TV and Watch: hub → checked, `platform_needs_key`) | critical |  | G→checked (boundary_guest); K→checked (boundary_child_protection) | ha (on the hub path: hub) |
| Access | Access hours ([access.md](access.md)) | `access_hours` | object `{enabled, windows[]}` | off | yes | – | Phone, Tablet, TV, Watch | sensitive |  | – | app (with checked path: ha_control; on the hub path: hub) |
| Access | Set up new devices ([setup.md](setup.md)) | `setup_devices` | object `{enabled, kinds[]}` | off, no kinds | yes | – | Phone, Tablet; only profiles of kind person (else `requires_profile_kind`) | sensitive |  | G→off (boundary_guest); K→off (boundary_child_protection) | hub |
| Access | Family manager ([family.md](family.md)) | `family_manager` | off · on | off | yes | – | Phone, Tablet | sensitive | Pro | G→off (boundary_guest); K→off (boundary_child_protection) | hub |
| Access | Answer children's requests ([access.md](access.md)) | `babysitter_requests` | off · on | off | yes | – | Phone, Tablet; only profiles of kind babysitter (else `requires_profile_kind`) | sensitive |  | K→off (boundary_child_protection) | hub |
| Access | Ask for early access ([access.md](access.md)) | `access_requests` | off · on (only has an effect with access hours) | off | yes | – | Phone, Tablet, TV | normal |  | – | hub |
| Access | Settings in the app | `app_settings` | hidden · pin · open | open | yes | – | Phone, Tablet, TV | critical |  | G→hidden (boundary_guest); K→pin (boundary_child_protection); pin needs remote PIN → hidden | app |
| Access | Biometrics instead of remote PIN | `app_settings_biometrics` | off · on | off | yes | – | Phone, Tablet | sensitive |  | G→off (boundary_guest); K→off (boundary_child_protection) | app |
| When away | Control when away | `remote_control` | object | default control; lock view, alarm_control_panel view, cover:garage view, cover:gate view | yes | – | Phone, Tablet, TV, Watch | critical |  | – | app |
| Areas & controls | Visible areas | `areas` | object | all | yes | – | Phone, Tablet, TV, Watch | sensitive |  | – | app (with checked path: ha_control; on the hub path: hub) |
| Areas & controls | Controls up to | `control_mode_max` | basic · advanced · full | full | yes | – | Phone, Tablet, TV, Watch | normal |  | – | app (a display rule, also on the hub path) |
| Areas & controls | Live camera image (also on the TV, picture-in-picture where possible) | `camera_live` | off · on | off | yes | – | Phone, Tablet, TV | sensitive |  | – | app |
| Kids rules | Blocked device types | `kids_blocked_types` | list | lock, alarm_control_panel, cover:garage, cover:gate, camera | yes (default: fixed) | – | Phone, Tablet, TV, Watch | critical | Pro | only with parental controls | hub |
| Kids rules | Bedtime | `kids_quiet_hours` | list | mon–fri 20:00–06:30; sat–sun 21:00–07:00 | yes (default: fixed) | – | Phone, Tablet, TV, Watch | sensitive | Pro | only with parental controls | hub |
| Kids rules | Rate limit | `kids_rate_limit` | object | 6/60 s, 300 s | yes (default: fixed) | – | Phone, Tablet, TV, Watch | sensitive | Pro | only with parental controls | hub |
| Kids rules | Pause everything ([family.md](family.md#pause-everything)) | `kids_rate_limit_all` | object `{enabled, max_actions, max_entities, window_seconds, cooldown_seconds}` | off (12 actions / 4 devices per 60 s, 300 s) – profiles without a value stay off | yes (default: fixed) | – | Phone, Tablet, TV, Watch | sensitive | Pro | only with parental controls | hub |
| Kids rules | Volume up to | `kids_volume_max` | integer | 40 | yes (default: fixed) | – | Phone, Tablet, TV, Watch | normal | Pro | only with parental controls | hub |
| Kids rules | Lock colors | `kids_color_lock` | boolean | off | yes (default: fixed) | – | Phone, Tablet, TV, Watch | normal | Pro | only with parental controls | hub |
| Kids rules | “Can I have more time?” ([family.md](family.md)) | `kids_requests` | off · on, with the kinds stay_up, unlock_device, end_pause | on, all kinds | yes (not fixed by default) | – | Phone, Tablet, TV, Watch | normal | Pro | only with parental controls | hub |
| Kids rules | Exceptions for areas and devices | `kids_exceptions` | list | [] | no, always fixed | – | Phone, Tablet, TV, Watch | sensitive | Pro | only with parental controls | hub |
| Kids rules | Allow a watch ([protocol.md](protocol.md#watches-access-through-the-phone)) | `kids_watch` | off · on | off | yes | – | Phone (`ios` only); only with remote access (else `requires_remote_access`) | sensitive | Pro | only with parental controls | hub |
| Features | Widgets, controls & Siri | `quick_access` | off · status · control | status | yes | – | Phone, Tablet, Watch | sensitive | Pro | G→off (boundary_guest); H→off unless `remote_access` is on (boundary_hub_only) | app |
| Features | Watch | `watch` | off · on | on | yes | – | Phone | sensitive | Pro | G→off (boundary_guest); K→off unless `kids_watch` is on (boundary_kids_watch); H→off unless `remote_access` is on (boundary_hub_only) | hub |
| Features | NFC and QR tags ([links.md](links.md)) | `scan_tags` | off · on | on | yes | – | Phone, Tablet | normal | Pro | G→off (boundary_guest) | hub (switching like a widget: quick access level, `<ns>.control`) |
| Features | Values in Home Assistant (every device, [panel.md](panel.md)) | `panel_sensors` | list (battery, charging, screen = screen state on panels / “app active” elsewhere, brightness, illuminance, battery_temperature – Android) | battery, charging, screen, brightness | yes | – | Phone, Tablet, TV (no watch: no own hub connection) | normal |  | – | hub |
| Home screen | Header with clock & weather | `header` | boolean | on | yes | yes | Phone, Tablet, TV | normal |  | – | app |
| Home screen | Home screen head ([below](#home-screen-head)) | `home_header` | object `{style, status_chips, greeting, weather}` | weather_mood, all on | yes | yes | Phone, Tablet (not in wall panel mode) | normal |  | – | app |
| Display | Card style | `card_style` | enum | calm | yes | yes | Phone, Tablet, TV | normal |  | – | app |
| Display | Appearance | `appearance` | enum | system | yes | yes | Phone, Tablet, TV | normal |  | – | app |
| Display | Search & filter | `search_filter` | boolean | on | yes | yes | Phone, Tablet | normal |  | – | app |
| Display | Columns per area | `columns` | integer | 2 | yes | yes | Phone, Tablet | normal |  | – | app |
| Display | Power button | `power_button` | object | off (light) | yes | yes | Phone, Tablet | normal |  | – | app |
| Display | Notifications | `notification_level` | none · important · all | all | yes | yes | Phone, Tablet, TV | normal |  | – | app |
| Display | Stacked notifications | `notification_stack` | enum | banner | yes | yes | Phone, Tablet, TV | normal |  | – | app |
| Wall panel | Wall panel mode | `kiosk` | off · on | off | yes | yes | Tablet, TV | normal | Pro | G→off (boundary_guest) | app |
| Wall panel | Start area | `panel_start` | object | overview | yes | yes | Tablet | normal |  | – | app |
| Wall panel | Back to start after | `panel_auto_home` | integer | 0 | yes | yes | Tablet, TV | normal |  | – | app |
| Wall panel | Dim after | `panel_dim` | integer | 0 | yes | yes | Tablet | normal |  | – | app |
| Wall panel | Screensaver after | `panel_screensaver` | integer | 0 | yes | yes | Tablet, TV | normal |  | – | app |
| Wall panel | Night mode | `panel_night` | object | off | yes | yes | Tablet | normal |  | – | app |
| Wall panel | Control from Home Assistant | `panel_remote` | off · on | on (off in every suggestion except Wall panel, TV, Kids' room panel) | yes | – | Tablet, TV | normal | Pro | G→off (boundary_guest) | hub |
| Wall panel | Wake from sensors | `panel_wake` | object `{entities, proximity}` (proximity sensor, Android) | no entities, proximity off | yes | – | Tablet, TV | normal | Pro | – | app |
| Wall panel | Brightness | `panel_brightness` | object | system | yes | yes | Tablet | normal | Pro | – | app |
| Wall panel | Announcements and chime ([panel.md](panel.md)) | `panel_announce` | object `{enabled, volume_max, respect_night}` | off, 80 %, night text only | yes | – | Tablet | normal | Pro | – | hub |
| Wall panel | Screen off | `panel_off_mode` | black · off | black | yes | – | Tablet (`ipados` only: always a black screen) | normal | Pro | – | app |
| Location | Share location with the hub ([location.md](location.md)) | `location` | off · foreground · background | off | yes | – | Phone; only profiles of kind person and child (else `requires_profile_kind`) | sensitive |  | G→off (boundary_guest) | app (with checked path: ha, `<ns>.report_location`; on the hub path: hub) |
| Location | Location required | `location_required` | off · on | off | yes | – | Phone; only profiles of kind person and child; only while `location` is not off (else `requires_location`) | normal |  | G→off (boundary_guest) | app |

Platforms: Phone = `ios`, `android`; Tablet = `ipados`, `android_tablet`; TV = `tvos`,
`android_tv`; Watch = `watchos`, `wearos`. Every rule applies to both platforms of a class
(`tools/profile_rules.py` checks it; a deliberate exception is listed there with its reason). The
catalog leaves out the Android platforms of these rules, so the admin UI shows them as not applicable
there: `notification_level`, `notification_stack`, `card_style` (phone, tablet, TV), `search_filter`,
`power_button` (phone, tablet), `panel_off_mode` and `columns` (tablet), `appearance` (TV), `kids_watch` (phone). Columns in
the table above name the Apple platforms for these. Default profiles follow the same pairs (iPad and
Android tablet both start as **Wall panel**, one switch away from a person's profile).

G = guest access, K = parental controls (`child_protection`), H = Hub only (boundary `hub_only`: the
effective `control_path` is `hub`). Values of objects and lists:
`schemas/common/profile-rule-values.json`. Column Pro: the app offers the rule only with Pro; the hub
shows a hint and does not check it. For the kids rules Pro means: the app on the child's device works
only with Pro, and without Pro it shows a notice and controls nothing. It never means that a rule is
dropped without Pro; an app that treated `pro` that way would leave a child without rules. The switch
parental controls itself has no `pro` field; the admin UI shows the Pro badge next to it because every
rule of the group kids is Pro. Hub only never needs Pro.

## When away

Rule `remote_control` (group “When away”, catalog default and suggestion Adult: locks, alarm panel,
garage and gate covers `view`, everything else `control`; guest suggestions additionally `view` for
`cover:door`, valves, sirens and automations; not applicable without remote access, as for the kids
suggestions). Value `{default, domains, entities}` with the levels `control` (operate),
`view` (show only – the safe direction of `data/quick-access.json` `safe_direction` stays allowed: lock
a lock, arm an alarm) and `hidden` (not shown). Precedence **entity > `domain:device_class` > domain >
default** (`tools/profiles_ref.py` `remote_level`). It has the checkbox “Fixed”, device adjustments and
temporary adjustments like every rule.

- **Only on the external route**: the app applies it while its Home Assistant link runs over the
  external URL (Home Assistant Cloud or `external_url`).
  At home (internal URL or the hub) it has no effect. Without effective remote access the
  rule is not applicable (`requires_remote_access`) – there is no external route.
- **Everywhere in the app family**: app, widgets/controls, Siri and the watch.
- **Combination – the strictest value wins**: quick access per entity on the external route =
  min(hub level of the entity in `client_config.quick_access.entities`, remote level mapped
  hidden→off, view→status, control→control) (`entity_access`). Kids rules are enforced by the hub on
  top; with parental controls and remote access the integration enforces them on the external route
  (`<ns>.control`, [enforcement.md](enforcement.md)).
- **Safety entities** (catalog `safety_entities`: `alarm_control_panel`, `binary_sensor` with
  device_class smoke, carbon_monoxide, moisture, gas) are at least `view` from away, never `hidden`.
- Enforcement `app`: shown as “Applies in Halumar”. Rules with `enforcement_with_checked_path` report
  that value on the checked control path ([Enforcement](#enforcement)).

## Enforcement

Every rule carries `enforcement` (`$defs/rule_enforcement`), and the effective rule repeats it for the
device: `ha` = Home Assistant enforces it (device user, e.g. remote access) → “Enforced”; `hub` = the hub
checks it on every request (rights, kids rules, setting up devices) → “Enforced”; `app` = the app follows
it → “Applies in {brand}” (someone with their own Home Assistant access is not bound by it). On the hub path
(the effective `control_path` is `hub`, with or without parental controls) the hub reads and switches for
the device, so `control_path`, `access_hours`, `areas` and `location` become `hub`
(`enforcement_with_hub_path`); a rule without that value reports its checked-path value, because the
device user is read-only in Home Assistant there too. `control_mode_max` stays `app`: it is a display rule,
not a permission. A child on Checked reports the checked-path values. Labels and help texts: catalog
`enforcement`.

The value `ha_control` means Home Assistant enforces **operating** (the device user is read-only and switches
only through the checked integration action `<ns>.control`; hiding stays in the app) → “Control enforced”.
With the effective rule `control_path = checked` the rules with `enforcement_with_checked_path`
report that value (`access_hours`, `remote_control`, `areas` → `ha_control`; `location` → `ha`); on the hub
path `enforcement_with_hub_path` wins. See [enforcement.md](enforcement.md).

## Important notifications are never hidden by a profile

Rule `notification_level` (`all`, `important` = priority ≥ `notifications.important_min_priority` (50),
`none`). Critical notifications (priority ≥ `critical_min_priority` (80)) and notifications about a
safety entity are never suppressed (`notification_shown`). **No delivery promise**: no push,
notifications appear while the app is open; the product is no alarm system. With parental
controls safety entities are always visible read-only (regardless of areas and blocked types; operating
the alarm stays blocked by the kids rules).

## Remote PIN in the profile

A profile may carry a remote PIN for “settings with remote PIN” (`remote_pin` write-only in
`profile-write.request.json`; answers only `has_remote_pin`, `remote_pin_fixed`). It applies to every
device of the profile. A device PIN wins, unless the profile PIN is fixed (`remote_pin_fixed`): then the
profile PIN applies, a device PIN is ignored and `PUT …/remote-pin` answers 422 `remote_pin.fixed`.
`app_settings = pin` is met when the profile or the device has a PIN (`remote_pin_source`). Stored only
as PBKDF2 hash + salt; never in log, audit, diff or preview. `client_config.settings_pin_source`
(`profile` | `device`) tells the app where the delivered hash comes from;
`client-effective.response.remote_pin_source` the admin UI.

## Boundaries

| Boundary | Where it comes from | Effect |
|---|---|---|
| `guest` | device property `access = guest`, set when pairing, never changed (a guest becomes a member only by pairing again); always with `expires_at` | caps `connection_insecure_http`, `setup_devices`, `family_manager`, `app_settings_biometrics`, `watch`, `scan_tags`, `kiosk`, `panel_remote` at off, `control_path` at checked (never direct; the guest suggestions fix hub), `app_settings` at hidden, `quick_access` at off, `location` and `location_required` at off. **Remote access is not capped**: a guest has it when the profile or an adjustment says so. After `expires_at`: every critical/sensitive rule at its `strictest` value (`access_expired`), the hub rejects the device (`auth_error guest_expired`). v1.0: never together with parental controls (422 `profile.guest_child_protection`). |
| `child_protection` | profile switch “Parental controls” | every action is checked: by the hub where it is reachable (WS `control`, `POST /api/client/control`); otherwise, when the device holds a key (`client_config.kids.away = ha`), through `<ns>.control` of the integration with a **read-only** HA key. `control_path` at most `checked` (`boundary_child_protection`); the kids suggestions start on `hub`, so the device has no key at home; Checked gives it a read-only key also at home. `watch` is off unless the kids rule `kids_watch` is on (`boundary_kids_watch`, the boundary carries `lifted_by: kids_watch`; a child's watch gets the phone's kids rules and is checked like the app away from home, see protocol.md “A child's watch”); `setup_devices`, `app_settings_biometrics` off and `app_settings` at most `pin` (`boundary_child_protection`); the kids rules apply and are enforced. Widgets follow `quick_access` and the boundary `hub_only`. Remote access is a normal profile rule (starter suggestions keep it off). The app on the child's device needs Pro. |
| `hub_only` | the effective rule `control_path` is `hub` (resolved first, catalog order), with or without parental controls | the device holds no Home Assistant key, so `quick_access` and `watch` are off (`boundary_hub_only`: widgets, Siri and shortcuts, controls, complications and a watch need the device's own key). The boundary carries `lifted_by: remote_access`: with remote access the device holds a read-only key and both follow the profile; a temporary remote access ends the lift with it (`expires_at`, `then`). |

A boundary of a rule without `order` (object value, `setup_devices`) always decides the rule (value =
cap). A boundary whose cap is the first value of `order` always decides the rule (source `boundary`, also when
the profile already has that value, so the UI shows the lock and the reason; `hub_only` on `quick_access`
and `watch`). A partial cap (parental
controls: settings at most `pin`) only applies when the value is looser. A boundary with `lifted_by`
(parental controls on `watch`, lifted by `kids_watch`; `hub_only` on `quick_access` and `watch`, lifted by
`remote_access`) does not apply while that boolean rule resolves to true on the device (it is resolved first, catalog order; a device adjustment of it
counts); the rule's own value then applies, so it never loosens beyond the profile or adjustment. When
that rule is on only through a temporary adjustment, the lifted rule carries the same `expires_at` and
as `then` the value once the boundary applies again (an offline app stops offering the watch in time).

**Platforms that need a key.** The apps for Apple TV, Android TV and Apple Watch cannot run without their
own Home Assistant key (a watch has no hub socket, the TV apps read and switch through Home Assistant); the
value `wearos` of the planned Wear OS app is treated the same. On `tvos`, `android_tv`, `watchos` and `wearos` the value `hub` of `control_path` therefore
resolves to `checked` (source `boundary`, reason `platform_needs_key`, also as `then` of a temporary
adjustment; `profiles_ref.KEY_PLATFORMS`). It is the one case where the resolver raises a value, and never
to `direct`. A watch limited to its phone gets the same mapping after `limit_to`. An expired guest keeps
`hub` (`access_expired`): it gets no key at all. The admin UI does not offer “Hub only” in profiles of
kind tv.

## Resolution (one rule, one device)

`resolve(platform, access, profile, overrides, device, now)` in `tools/profiles_ref.py`:

1. **Applicability**: platform not in `platforms` → `not_applicable`; kids rule without parental
   controls → `not_applicable` / `requires_child_protection`. Value `null`, never sent to the app.
2. **Base value**: profile value, else catalog default (`source default`, only for rules a profile does
   not contain yet after a hub update). Exception: without a stored `control_path` a profile with
   parental controls, a device with guest access and a profile of the kinds guest, babysitter or house
   sitter resolve to `hub`, not to the catalog default `checked` (fail closed: no key by default); members
   keep `checked`. An unknown stored value counts as `hub`. `user_choice` when the rule allows it and the profile lists it.
   A **comfort rule** (user's choice allowed) the stored profile does not hold yet is filled when the
   profile is read (`fill_missing`): value of the origin suggestion, else of the starter suggestion of
   the profile kind, else the catalog default, and user's choice as `default_user_choice` – so a new
   comfort rule is never locked on existing devices before the admin decides. It still resolves with
   `source default` and stays in `catalog_defaults` until the profile is saved.
3. **Own area**: `areas.own_area` adds the device's own area (missing → nothing, fail closed);
   `panel_start.mode = own_area` becomes `area` with that id (missing → `overview`); a kids exception
   targeting the own area becomes an area exception (missing → dropped).
4. **Boundaries** (guest, then parental controls, then Hub only), then **prerequisites** (`app_settings = pin` without
   remote PIN of the profile or the device → `hidden`, `prerequisite_missing`), then **guest expiry**.
5. **Device adjustment**: only when the rule is not fixed and the adjustment has not ended
   (`now < expires_at`); steps 3–4 apply to it as well (an adjustment never beats a boundary). A running
   temporary adjustment carries `expires_at` and `then` (the value of steps 2–4 without it), also when a
   boundary caps it and the capped value differs from that. A rule whose boundary reads an earlier rule
   (`lifted_by`, and `control_path` for `hub_only`) carries the earliest end of such a rule that changes
   its value, with the value from then on as `then`. A boundary entry whose `then` equals its value carries
   no end.

6. `remote_control` without effective remote access → `not_applicable` / `requires_remote_access`;
   `location_required` while `location` is off → `not_applicable` / `requires_location`;
   `kids_watch` without effective remote access → `not_applicable` / `requires_remote_access` (decided
   right after the rule, before `watch` reads it); with a temporary remote access `kids_watch` carries
   its `expires_at` (`then` null), and so does `watch`; `control_path` on a platform that needs a key:
   `hub` → `checked` (`platform_needs_key`, right after the rule, before `hub_only` is read);
   every entry gets `enforcement` from the effective `control_path` (hub path, checked path, else the
   catalog value).

`locked = not user_choice`; `fixed` = checkbox “Fixed”, rule without checkbox, or decided by a boundary.
Precedence in short: **catalog default → profile → device adjustment (possibly temporary) →
boundaries**. Properties the hub tests (Hypothesis): boundary values do not depend on profile or
adjustment; an additional boundary never loosens (the platform mapping of `control_path` aside); with “Fixed” the value ignores every adjustment; after
a guest expiry every critical/sensitive rule is at its strictest value; every key yields a valid value and
exactly one reason; the order of adjustments does not matter; a missing own area is never more open.

A watch is then limited to its phone: the meet of both per rule class (`watch_limit` in the catalog,
`limit_to`, protocol.md “Every watch follows its phone”); vectors with `input.limit` (the phone) and the
random-pair property of `tools/validate.py` check it.

## Reason codes

| Code | Source | Admin UI | Device |
|---|---|---|---|
| `catalog_default` | default | {brand} default | – |
| `profile` | profile | From profile ‹{profile}› | Set by {admin} |
| `user_choice` | profile/device | User's choice · starts with {value} | Your setting · suggested: {value} |
| `device` | device | Adjusted for this device · profile: {profile_value} | Set by {admin} for this device |
| `device_temporary` | device | Adjusted until {until} · then: {then} | Until {until} |
| `boundary_guest` | boundary | Not available for guest access | Not available on this device |
| `boundary_child_protection` | boundary | Because of parental controls | Not available on this device |
| `boundary_kids_watch` | boundary | With parental controls only with “Allow a watch” (kids rules) | Not available on this device |
| `boundary_hub_only` | boundary | Needs the device's own Home Assistant key: not possible with “Hub only” without remote access | Not available on this device |
| `platform_needs_key` | boundary | On {platform} the device always has its own read-only key (“Checked”) | Always so on this device type |
| `limited_by_phone` | boundary | Limited by its phone ‹{device}› | Limited by your phone |
| `prerequisite_missing` | prerequisite | Needs a remote PIN on this device · hidden until then | – |
| `not_applicable` | not_applicable | Does not apply to {platform} | – |
| `requires_remote_access` | not_applicable | Only with remote access | – |
| `requires_child_protection` | not_applicable | Only with parental controls | – |
| `requires_profile_kind` | not_applicable | Only for profiles of kind {kinds} | – |
| `requires_location` | not_applicable | Only when the location may be shared | – |
| `access_expired` | access_expired | Guest access expired – everything blocked | Your guest access has expired |

Placeholders: `{brand}` display name (`brand.json`), `{profile}`, `{admin}` (`profile.managed_by`),
`{value}`, `{profile_value}`, `{until}` (absolute and relative, e.g. “tomorrow, 07:00 · 9 h left”),
`{then}`, `{platform}`. Device texts for children are friendly (no red, no “permission denied”).
Clients show a neutral text for an unknown code.

## Temporary adjustments

Presets (`$defs/rule_expiry_preset`): `1h`, `today` (until the next local midnight), `tomorrow_morning`
(07:00 local of the next day; from 00:00 to 04:59 07:00 of the same day), `7d`; or an own `expires_at`
(“Date”). Local = Home Assistant's time zone; DST cases in `fixtures/profiles/expiry`. The end lies at
least 5 minutes and at most 365 days ahead (`expiry_limits`). At the end the hub deletes the adjustment
(audit `override_expired`, author = the hub), switches the HA user when `remote_access` changes
(`update_client_identity`) and sends `client_config_updated`; an offline app switches to `then` at
`expires_at` on its own. One adjustment per device and rule: permanent or temporary. The parent release
of the kids mode (`POST …/kids-override`, `rest/kids-override.request.json`) is a separate run-time
action: `minutes` (15/30/60/120 in the admin UI) or `until: "bedtime_end"` (“Until tomorrow morning”: end of
the current or next bedtime of the device from `kids_quiet_hours`, in the hub time zone; without
bedtime 07:00 local like `tomorrow_morning`).

## Suggestions

`data/profile-suggestions.json`, 14 suggestions; the five starters are created at the first start of the
hub; Adult, Guest, Wall panel and TV become the default profiles, Child is created but is no default.

| Suggestion | Group | Starter | Parental controls | Default for | Values that differ | Fixed | User's choice |
|---|---|---|---|---|---|---|---|
| Adult (`adult`, version 5, kind person) | people | ★ |  | ios, watchos, android, wearos | remote_access on; connection_insecure_http on (the switch is offered, it starts off); control_path checked (family members); remote_control default control; lock view, alarm_control_panel view, cover:garage view, cover:gate view; quick_access control; camera_live on; watch on; location background; panel_remote off; panel_sensors battery, charging, screen, brightness | kids_* | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack, kiosk, panel_start, panel_auto_home, panel_dim, panel_screensaver, panel_night |
| Parents (`parent`, version 6, kind person) | people |  |  | – | like Adult, but control_path direct (trusted, full rights); family_manager on; setup_devices on: guest, child, panel, tv, house_sitter, babysitter; panel_remote off; panel_sensors battery, charging, screen, brightness | family_manager, kids_* | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack, kiosk, panel_start, panel_auto_home, panel_dim, panel_screensaver, panel_night |
| Child (`child`, version 8, kind child) | kids | ★ | ✓ | – | control_path hub; control_mode_max advanced; app_settings pin; quick_access off; watch off; card_style color; kids_rate_limit_all on, 12 actions / 4 devices per 60 s, 300 s; panel_remote off; panel_sensors battery, charging, screen, brightness; location foreground; home_header compact without status capsules | app_settings, kids_blocked_types, kids_color_lock, kids_exceptions (bedtime, breaks, pause everything and volume not fixed: family managers adjust them) | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack, kiosk, panel_start, panel_auto_home, panel_dim, panel_screensaver, panel_night |
| Guest (`guest`, version 4, kind guest) | guests | ★ |  | guest | control_path hub; access_requests on; areas selected: own; control_mode_max basic; app_settings hidden; quick_access off; watch off; remote_control default control; lock view, alarm_control_panel view, cover:garage view, cover:gate view, cover:door view, valve view, siren view, automation view | control_path, kids_* | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack |
| Wall panel (`wall_panel`, kind panel) | shared | ★ |  | ipados, android_tablet | app_settings pin; quick_access off; watch off; camera_live on; appearance dark; kiosk on; panel_start own_area; panel_auto_home 5; panel_dim 2; panel_screensaver 10; panel_night sun 22:00–06:00 20 %; panel_remote on; panel_sensors battery, charging, screen, brightness, battery_temperature; panel_brightness system; panel_announce on, 80 %, night text only; panel_off_mode black (version 4) | app_settings, connection_insecure_http, kiosk, location, remote_access, setup_devices, kids_* | – |
| TV (`apple_tv`, kind tv) | shared | ★ |  | tvos, android_tv (every TV: Apple TV, Android TV and Google TV) | app_settings pin; appearance dark; header on; panel_screensaver 10; panel_remote on; panel_sensors screen; kiosk off and camera_live off, both not fixed (version 4) | app_settings, connection_insecure_http, location, remote_access, setup_devices, kids_* | card_style |
| Easy mode (`easy_mode`, kind person) | people |  |  | – | control_mode_max basic; search_filter off; card_style color; app_settings pin; quick_access status; panel_remote off; panel_sensors battery, charging, screen, brightness (version 2) | kids_* | appearance |
| Toddler (up to 5) (`toddler`, kind child) | kids |  | ✓ | – | control_path hub; areas selected: own; control_mode_max basic; app_settings hidden; card_style color; kids_blocked_types lock, alarm_control_panel, cover:garage, cover:gate, camera, climate; kids_quiet_hours mon–sun 19:00–07:00; kids_rate_limit 4/60 s, 600 s; kids_rate_limit_all on, 8 actions / 3 devices per 60 s, 600 s; kids_volume_max 30; kids_requests off; panel_remote off; panel_sensors battery, charging, screen, brightness; location foreground; home_header compact without status capsules (version 7) | app_settings, kids_* except kids_requests | – |
| Child 6–9 (`child_6_9`, kind child) | kids |  | ✓ | – | control_path hub; areas selected: own; control_mode_max basic; app_settings pin; card_style color; kids_quiet_hours mon–fri 19:30–06:30; sat–sun 20:30–07:00; kids_rate_limit_all on, 12 actions / 4 devices per 60 s, 300 s; kids_requests on; panel_remote off; panel_sensors battery, charging, screen, brightness; location foreground; home_header compact without status capsules (version 7) | app_settings, kids_* except kids_requests | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack, kiosk, panel_start, panel_auto_home, panel_dim, panel_screensaver, panel_night |
| Child 10–12 (`child_10_12`, kind child) | kids |  | ✓ | – | control_path hub; control_mode_max advanced; app_settings pin; kids_blocked_types lock, alarm_control_panel, camera; kids_quiet_hours mon–fri 20:30–06:30; sat–sun 21:30–07:30; kids_rate_limit 10/60 s, 120 s; kids_rate_limit_all on, 20 actions / 6 devices per 60 s, 300 s; kids_volume_max 60; kids_requests on; panel_remote off; panel_sensors battery, charging, screen, brightness; location foreground; home_header compact without status capsules (version 7) | app_settings, kids_* except kids_requests | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack, kiosk, panel_start, panel_auto_home, panel_dim, panel_screensaver, panel_night |
| Teen (13–17) (`teen`, kind child) | kids |  | ✓ | – | control_path hub; control_mode_max full; app_settings pin; kids_blocked_types alarm_control_panel, camera; kids_quiet_hours mon–fri 22:00–06:00; kids_rate_limit 20/60 s, 60 s; kids_rate_limit_all on, 30 actions / 10 devices per 60 s, 120 s; kids_volume_max 80; kids_requests on; panel_remote off; panel_sensors battery, charging, screen, brightness; location foreground; home_header compact without status capsules (version 7) | kids_* except kids_requests | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack, kiosk, panel_start, panel_auto_home, panel_dim, panel_screensaver, panel_night |
| Babysitter (`babysitter`, version 5, kind babysitter) | guests |  |  | – | remote_access off; control_path hub; access_hours every day 17:00–01:00; access_requests on; babysitter_requests on; areas selected: own + preselection (`area_patterns`: living spaces, kids' rooms); control_mode_max advanced; app_settings hidden; quick_access off; watch off | remote_access, control_path, kids_* | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack |
| House sitter & helper (`house_sitter`, version 5, kind house_sitter) | guests |  |  | – | areas selected: own + preselection (`area_patterns`: living room, kitchen, garden, entrance); access_hours every day 07:00–21:00; access_requests on; remote_access off (switched on, it gives the device a read-only key); control_path hub; remote_control default control; lock view, alarm_control_panel view, cover:garage view, cover:gate view, cover:door view, valve view, siren view, automation view; control_mode_max advanced; app_settings hidden; quick_access off; watch off | control_path, kids_* | card_style, appearance, header, home_header, search_filter, columns, power_button, notification_level, notification_stack |
| Kids' room panel (`kids_room_panel`, kind panel) | shared |  | ✓ | – | control_path hub; areas selected: own; control_mode_max basic; app_settings pin; card_style color; kiosk on; panel_start own_area; panel_auto_home 5; panel_dim 2; panel_night schedule 19:30–07:00 10 %; kids_quiet_hours mon–sun 19:30–07:00; kids_rate_limit_all on, 12 actions / 4 devices per 60 s, 300 s; panel_remote on; panel_sensors battery, charging; panel_announce off (50 %); panel_off_mode black (version 6) | app_settings, connection_insecure_http, kiosk, location, panel_announce, panel_sensors, remote_access, setup_devices, kids_* | – |

The rule `access_hours` and the access switch in Home Assistant decide when a device has access at all;
outside it stays paired and sees nothing ([access.md](access.md)). The kind `babysitter` (guest access like guest and
house_sitter) has the rule `babysitter_requests`; Babysitter and House sitter carry access hours and
preselect areas by name (`area_patterns`); Parents may set up babysitters.

Every suggestion has a `kind` (`$defs/profile_kind`); a profile copied from it gets that kind, an
empty profile is `person`, a profile created from a device keeps the kind of the device's profile. The
kind groups profiles for “Set up new devices” and changes no rule; only kind person can have
`setup_devices`. Wall panel, TV and Kids' room panel fix `setup_devices` (it does not apply to their
kind anyway).

Every suggestion for members carries `panel_sensors` battery, charging, screen, brightness (guest suggestions do not: guests never get sensors), so every device except watches and guests reports its values to Home Assistant; the hub limits the list to what the platform delivers (TVs only the screen). `panel_remote` is on only in Wall panel, TV and Kids' room panel and off in every other member suggestion; its catalog default is on, which applies to a profile without a stored value.

The kids suggestions (Child, Toddler, Child 6–9, Child 10–12, Teen, Kids' room panel) carry `kids_rate_limit_all` switched on; Child leaves it not fixed like the other breaks, the age suggestions fix it with their kids rules, Teen is looser. The catalog default is **off**.

## Home screen head

Rule `home_header` (group “Home screen”, together with `header`): how the head of the start screen
looks on phones and tablets while `header` is on. Value `{style, status_chips, greeting, weather}`,
all four required:

| Field | Values | Meaning |
|---|---|---|
| `style` | `weather_mood` · `compact` (`$defs/home_header_style`) | **Weather mood**: sky in one tone per weather and time of day, large temperature, hourly row. **Compact**: one line with greeting and weather, the areas start high up. An unknown style is shown as `weather_mood`. |
| `status_chips` | boolean | Status capsules lights / doors / climate below the weather, each opens the matching areas. |
| `greeting` | boolean | Greeting by time of day (“Good morning”). |
| `weather` | boolean | Weather in the head. Without weather, `weather_mood` keeps its sky in the tone of the time of day. |

- **Catalog default** `weather_mood` with capsules, greeting and weather on, **user's choice**
  (`default_user_choice`): the person sets the head on the device (Settings › Home screen); the
  profile value is the starting value.
- **Lock**: the admin turns off “User's choice” in the profile (or sets a device adjustment) – then
  `client_config.rules.home_header.locked` is `true` and the app shows the value without a setting.
  “Fixed” (`fixed`) additionally forbids device adjustments, as with every rule.
- **Kids suggestions** (Child, Toddler, Child 6–9, Child 10–12, Teen): `compact` without status
  capsules, greeting and weather on. A child does not need the house status (doors, climate of other
  rooms) on the start screen, and its own areas start higher up with larger tiles in reach. Toddler
  has no user's choice at all, so the head stays compact there.
- **Not applicable**: TVs (`tvos`, `android_tv`) have no `home_header`; they keep `header`. On
  tablets in wall panel mode (`kiosk` on, suggestions Wall panel and Kids' room panel) the app
  ignores the value and shows its panel head.
- With `header` off there is no head at all; `home_header` keeps its value for when it is switched on
  again. Important notices stay visible either way.
- A profile without a stored value: the hub fills it with the value of the
  profile's suggestion or kind (children: compact without capsules, everyone else: weather mood) as
  the **user's choice**, not locked (`source default`, `catalog_defaults`, see Resolution step 2).
  Locked is only what the admin locks.

Each suggestion has a `version`. A profile keeps its `origin {suggestion_id, version}`; when the
shipped version is higher the profile shows `suggestion_update` (“New version”).
`POST /api/profiles/{id}/apply-suggestion` takes it over only on request, with preview. Adding a
suggestion again creates another copy (“Child 6–9 (2)”); a deleted suggestion profile is never lost.

## Profiles, devices, house settings

- **Create**: `POST /api/profiles` (empty: catalog defaults, `default_fixed`, `default_user_choice`),
  `POST /api/profile-suggestions/{id}`, `POST /api/profiles/from-device` (effective profile values incl.
  adjustments, not boundary-clamped values; `assign` moves the device and drops its adjustments),
  `POST /api/profiles/{id}/duplicate`.
- **Change**: `PATCH /api/profiles/{id}` – `rules` merge per key, `fixed` and `user_choice` replace.
  Fixing a rule deletes its adjustments; an adjustment equal to the profile value is deleted.
  A change that takes a device's Home Assistant key away (`control_path` hub without remote access, also
  through the end of a temporary adjustment) rotates its HA token; switching parental controls on sets
  `control_path` to hub in the admin UI, visible in the preview.
- **Delete**: `DELETE /api/profiles/{id}?replacement=<id>`; without replacement while devices use it
  → 409 `profile_in_use`; a default profile or the last profile cannot be deleted (409
  `profile_is_default`, `last_profile`). Guest devices only get a replacement without parental controls.
- **Default profiles** (`GET/PUT /api/settings/profiles`): one per device type (`ios`, `ipados`, `tvos`,
  `watchos`, `android`, `android_tablet`, `android_tv`, `wearos`) and `guest`, plus
  `guest_default_hours`. The starters set Android like its Apple counterpart (phone and `wearos` →
  Adult, tablet → Wall panel, Android TV → TV, like the Apple TV); the admin can choose each slot separately. They
  apply wherever nobody picks a profile: PIN pairing without `profile_id` (by the platform that pairs),
  a watch set up by its phone, invitations by members without a chosen profile, pairing
  through the integration. Setting up a device from another device picks the profile.
- **Own area** (`PUT /api/pairing/clients/{id}/own-area`): one area or none per device.
- **Assign** (`PUT /api/pairing/clients/{id}/profile`, `discard_overrides`) and **bulk**
  (`POST /api/pairing/clients/bulk`: assign profile, set own area, set/remove adjustment).
- **Guest duration**: the hub is authoritative (`guest_access.max_hours` = 90 days per grant,
  extendable); the apps follow `access.expires_at` and have no own cap.
- **Preview**: every profile write accepts `?dry_run=true` (a write without a dry run refuses it: 422 `dry_run_not_supported`, nothing changed, protocol.md “Errors and 404”) and answers `profile-preview.response.json` (changed
  effective values per device, deleted adjustments, HA key and remote access consequences, loosened
  rules that need a confirmation with the catalog's `loosening_warning`).
- **Scene hints**: `GET`/`PATCH /api/profiles/{id}` (also its dry run) and the effective rules of a
  device carry `scene_hints` (`common/scene-hint.json`): released scenes and scripts whose targets the
  profile or device may not switch, with the reason per target. The admin UI shows them next to the
  areas rule and offers to add the missing area. Details: [enforcement.md](enforcement.md) §2 step 4.
- **Audit** (persistent, with `before`/`after`; `GET /api/profile-audit?client_id=&profile_id=&limit=`,
  `rest/profile-audit.response.json`, newest first): `profile_created`, `profile_updated`,
  `profile_deleted`, `profile_assigned`, `override_set`, `override_removed`, `override_expired`,
  `own_area_set`, `remote_pin_set`, `profile_remote_pin_set`, `default_profiles_changed`,
  `suggestion_added`, `suggestion_applied`, `guest_extended`, `migration_v9`
  (`$defs/profile_audit_action`). The remote PIN never appears in profile, audit or log.
- **Admin push**: every write sends the admin broadcast `profiles_changed {profile_ids, client_ids}`
  (also to the integration, as refresh trigger); the affected devices get `client_config_updated`.
- **Summary sentences** (“In short” of a device, the sentence on a profile card) are built by the
  admin UI from the effective values and the catalog labels in its own language; the hub sends none.

The admin UI renders the editor from `GET /api/profile-rules` (the catalog file the hub was built with).

Admin endpoints in detail: [`openapi/hub.openapi.json`](../openapi/hub.openapi.json), tag `profiles`
(snapshot of the hub, `tools/snapshot_openapi.py`).

## Delivery to the apps (`client_config`)

- `access` (`common/client-access.json`), `profile` (`common/client-profile.json`), `rules`
  (`common/resolved-rules.json`, typed per rule; only rules that apply to the device), `kids` (only with
  parental controls; `rules.profile` mirrors the `kids_*` values, `rules.areas/entities` the exceptions),
  `quick_access` (derived from `rules.quick_access`), `control_mode` (hub default clamped by
  `control_mode_max`), `settings_pin_hash/salt/source` (only with `app_settings = pin`; profile or device
  PIN), `config_hash`.
- Hard checks independent of the resolver (also in `tools/validate.py` for the fixtures): `ha_url` only
  with `remote_access` true; `ha_token`, `ha_instance_id` and `ha_enforcement` only when the device holds
  a key (`holds_key`: `control_path` checked or direct, or hub with `remote_access` true), otherwise null;
  on the hub path `ha_instance_id` only together with `ha_token`; `ha_enforcement.control_path` is
  `checked` for `hub`, otherwise the rule's value; with parental controls `kids.away = ha` exactly when the
  device holds a key (a `child_protection` without the rule counts as `hub`). Reference
  `profiles_ref.ha_access`, matrix `fixtures/profiles/ha-access/matrix.json`.
- App mapping: `app_settings` hidden/pin/open (`pin` = unlock with the remote PIN, `app_settings_biometrics` = biometric unlock (Face ID, Touch ID, Android fingerprint or face unlock) allowed); `areas` is applied by the
  hub (`get_areas`); `user_choice` = local value of the person wins, otherwise the hub value;
  `then`/`expires_at` = switch offline at that time; `access.kind = guest` → guest UI, `expires_at` from
  the hub; `profile.child_protection` → kids session (with `kids.away = ha` over Home Assistant when the hub
  is not reachable); `profile.child_protection` or `rules.control_path.value = hub` → hub path
  ([enforcement.md](enforcement.md#7-devices-on-the-hub-path)).

## Using the vectors

- Vectors may carry `entity_checks` (remote level and quick access per entity and route, safety flag),
  `notification_checks` and `expected_remote_pin_source`.
- **Hub**: run every `fixtures/profiles/resolve/*.json` through the hub resolver (profile from
  `from_suggestion` via the shipped suggestions, otherwise a bare profile: only the given rules, nothing
  fixed, no user's choice) and compare the listed rules field by field; same for `expiry`.
- **Home Assistant access**: `fixtures/profiles/ha-access/matrix.json` lists every combination of
  `control_path`, remote access, open or closed access, platform and, for watches, the phone's rule
  `watch`, with the key fields of `client_config` (`profiles_ref.ha_access`); resolve vectors may carry
  `expected_ha_access`; the `time-*` vectors show a temporary adjustment before, at and after its end;
  `fixtures/profiles/no-escalation` compares what a setting-up device may hand out with its own
  (`profiles_ref.key_looser` for `control_path`, `profiles_ref.looser` for the other ordered rules).
- **Apps**: drop rules with source `not_applicable` to get `client_config.rules`, feed them into the
  settings/managed-state UI and snapshot tests; `fixtures/client-config/*.json` are complete payloads
  (adult, adjustments, child on Hub only and on Checked, guest on Hub only with and without remote
  access, a person on Hub only with and without remote access, temporary adjustment, wall panel, Apple TV,
  watch, remote PIN).
