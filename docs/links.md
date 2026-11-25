# Links on tags and from Home Assistant

Two URL formats are fixed because they leave the system for good:
the **tag link** stays on printed NFC and QR tags, the **open link** in users' automations and blueprints.
Both use the brand website (`brand.json` `urls.website`,
production `https://halumar.com`). The tag link uses the app scheme only for development; the open link
also has an **official app form** `<scheme>://open/…`, see below. The TV apps also support the open link and show
cameras, with picture-in-picture where the platform allows it. The rule `scan_tags` is marked Pro: the app offers tags only with Pro.

| Link | Production | Development | Schema |
|---|---|---|---|
| Tag | `https://<website>/t/<tag_id>` | `<scheme>://t/<tag_id>` | [`deep-link/tag-link.json`](../schemas/deep-link/tag-link.json) |
| Open a view | `https://<website>/open/camera/<entity_id>` · `https://<website>/open/area/<area_id>` (preferred) | `<scheme>://open/…` – also official | [`deep-link/open-link.json`](../schemas/deep-link/open-link.json) |

No query string, no fragment, no other paths. Unknown views under `/open/` open the start screen (never an
action).

## Tag link

- `tag_id` = 22 characters base64url (128 random bits, `$defs/tag_id`). **No secret**: anyone who reads the
  tag only learns the id. What the tag does is stored in the **hub** the tag is registered in (table
  `scan_tags`, admin REST `GET/POST /api/scan-tags`, `PUT/DELETE /api/scan-tags/{tag_id}`,
  [`common/scan-tag.json`](../schemas/common/scan-tag.json)). The hub draws new ids; an already written tag
  can be registered in another hub with its id (`tag_id` in the POST body). At most 100 tags per hub.
- Action (`$defs/tag_action`): `show` (open an entity or an area – read), `toggle`, `turn_on`, `turn_off`
  (switch an entity), `run` (scene, script, button).
- Flow: the app reads the URL (Android: NDEF URI record or QR → App Link; iPhone: background tag reading or
  QR → universal link) → WebSocket `tag_resolve {tag_id, via}` → `tag_result {result, tag?}`
  (`ok`, `unknown_tag`, `tags_off`, `not_visible`, `rate_limited`). With `ok` the app runs the action
  **like a widget**: `control_origin` `quick_access`, so the quick access level of the entity, the profile
  (`areas`, `remote_control`, kids rules) and, on the checked path, `<ns>.control` apply. The hub itself
  executes nothing.
- Hub checks for `tag_resolve`: rule `scan_tags` (off, not applicable or guest → `tags_off`), target inside
  the device's areas (`not_visible`), 10 per minute per device (`rate_limited`). Pro is checked only by
  the app.
- Several homes: the app asks the hub of the active home first; on `unknown_tag` the next home it knows.
- Log: event `tag_scanned` (activity, `tag_id`, `tag_name`, `result`), in Home Assistant as `<ns>_event`
  and additionally as **`<ns>_tag_scanned`**
  ([`integration/ha-tag-scanned.event.json`](../schemas/integration/ha-tag-scanned.event.json)) for own
  automations, fired by the integration on the hub's `ha_event`. The app never calls `fire_event`.
- Away from home (no hub): the app does nothing with a tag; it may show the name it knows from an earlier
  scan.

## Open link

- `camera/<entity_id>`: a `camera.*` entity (`$defs/camera_entity_id`). Shows the camera view, live only
  with the rule `camera_live`, else still images. Picture-in-picture only when the user starts it
  or as the platform allows.
- `area/<area_id>`: a hub area UUID, or a Home Assistant area id (`[a-z0-9_]{1,64}`, first hub area with that
  `ha_area_id`).
- Two official forms: `https://<website>/open/…` is preferred (works on every device with verified
  universal links / App Links); the app form `halumar://open/…` is allowed as well and behaves exactly the
  same. Use it where the https form does not reach the app, e.g. Google TV via `androidtv_remote`
  (`remote.turn_on activity:`) before the App Links are verified, or Apple TV through `media_player.play_media`.
- A link **only opens a view**. It never switches, confirms or starts anything. The device's profile decides
  what it may see; a hidden or unknown camera/area opens the start screen without naming it.
- Typical use: an HA notification with `url`/`clickAction` `https://halumar.com/open/camera/camera.doorbell`.
  On a TV nobody taps a notification: Home Assistant brings the app to the front with the link (Apple TV:
  `media_player.play_media` with `media_content_type: url`; Google TV: `remote.turn_on` with `activity:` of
  `androidtv_remote`; blueprints “Doorbell → camera on the Apple TV / on the TV (Google TV)” in the
  integration), or uses the panel command `show_camera` (below) when the app is already connected.

## Panel commands for the same purpose

`panel_command` reserves two actions (docs/panel.md):

- `show_camera {entity_id}`: wall panels and TVs open the camera view; the hub checks that the camera
  is inside the device's areas (`not_visible`).
- `announce {text, volume?, chime?}`: wall panels speak/show the text with an optional chime;
  rule `panel_announce` (`enabled`, `volume_max`, `respect_night`).

Both are offered only when the app lists them in `panel.actions`. Only Home Assistant admins and automations
trigger them (integration actions `<ns>.panel_announce`, `<ns>.panel_show_camera`).

## Website paths

The apps claim `https://halumar.com/t/*` and `/open/*` as universal links / App Links.

Without the app the website answers these paths with a short page (tag: "Open with the Halumar app"; open
link: same), never with data.
