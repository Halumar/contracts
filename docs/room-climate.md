# Room climate

Which entities give the room temperature and humidity of an area: the area card, the climate capsule of the
start screen, the wall panel, TV tiles, widgets and the watch all show the same value. The rule lives in
`data/room-climate.json`, the reference in `tools/room_climate_ref.py`, the shared vectors in
`fixtures/climate/room-climate-vector/` (hub and apps run them).

## Where the decision is made

| Who | Knows | Does |
|---|---|---|
| Hub | placements, live states, entity and device registry (entity category, device name and model, Home Assistant area of entity and device), the admin's choice | sends `room_climate` with every area (`get_areas`, `get_area`) |
| App | placements, live states (entity_id, names, `device_class`) | computes the value from `room_climate`; without it (an app without a hub, demo) applies the rule itself |

```json
"room_climate": {
  "temperature": { "source": "auto", "entity_ids": ["climate.kitchen", "sensor.kitchen_temperature"] },
  "humidity":    { "source": "admin", "entity_ids": ["sensor.kitchen_humidity"] }
}
```

## The rule (per measure)

1. **Admin's choice.** On the area page ("Room climate") the admin may pick one entity placed in the area
   that reports the measure, an excluded one too. `source admin`, exactly that entity. Without a value
   (unavailable) the area shows none; there is no fallback.
2. **Automatic** (`source auto`), over the visible placements in layout order:
   - Candidates: entities of `device_domains` (thermostats) that carry `device_attribute`
     (`current_temperature`, `current_humidity`), and sensors with the `device_class` of the measure (state
     attribute; the hub also reads the registry's `device_class`/`original_device_class`).
   - Left out: registry `entity_category` in `exclude.entity_categories` (hub), and every entity whose text
     matches an exclude group: fridge, freezer, cool box, pool, outdoor, boiler, water, processor/battery/disk.
     Text = entity_id, display name of the placement, `friendly_name`; the hub adds registry name, original
     name, device name (by user and original) and model.
   - In the room wins (hub): within each tier, if one candidate or its device is assigned to the Home
     Assistant area of the area (`ha_area_id`; the entity's own area before its device's), only those stay.
3. **Value** (apps, and the hub for the admin preview): `admin` = the entity's value. `auto` = the median of
   the thermostats with a value; if none has one, the median of the sensors with a value; else none. Median
   of an even count = mean of the middle two. A thermostat's value is its attribute whatever its mode (off
   still measures); a sensor's value is its numeric state.
4. **One sensor** (widgets, watch, anything that shows the state of one entity): among the candidate sensors
   (or the admin's sensor) the one closest to the room value, the earlier one on a tie; none when the room
   has no value or no sensor.

## Matching

Lower case; `ä→ae`, `ö→oe`, `ü→ue`, `ß→ss`; other diacritics dropped; every run of characters other than
`a-z0-9` becomes one space. A keyword of `contains` matches anywhere (German compounds such as
"Weinkühlschrank"), one of `prefixes` only at the start of a word ("Aussentemperatur", "pool_temp", but not
"Haussensor"). Keywords are stored normalized, with the spelling Home Assistant uses in entity ids
(`kuhlschrank`) next to the transcribed one (`kuehlschrank`). A change of the lists raises `version`.

## Admin API

`GET /api/areas/{area_id}/room-climate` answers per measure the admin's choice (`entity_id`, null =
automatic), the `pick` the apps get, the current `value` and `unit`, and every placed entity that reports the
measure (`options`: `tier`, `in_room`, `excluded` = group id or `entity_category`, `value`).
`PUT` with `{temperature_entity_id, humidity_entity_id}` (null = automatic) replaces the choice; any other
entity than an option is refused with 422 `room_climate_invalid`. Connected apps get the area again.
