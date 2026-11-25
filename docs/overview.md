# How the rules work, end to end

This page follows one device from pairing to the moment it switches a light. It names the files that
define each step, so you can read further where you need to. Terms are explained in the
[glossary](glossary.md).

## The parts

| Part | What it does with the rules |
|---|---|
| **Hub** (Home Assistant app) | Holds the profiles and device adjustments, resolves the rules for every device, checks the rules it enforces itself, sends each app its resolved rules and sends the integration a rule snapshot per device. A device on “Hub only” reads and switches through the hub and gets no Home Assistant key. |
| **Integration** (Home Assistant custom integration) | Creates one Home Assistant user per device, keeps that user read-only when the device is on “Hub only” or “Checked”, and checks every call of the action `<ns>.control` against the device's rule snapshot. |
| **Apps** (iPhone, iPad, Apple TV, Apple Watch; Android phone, Android tablet incl. wall panel, Android TV) | Receive only resolved values with their source and reason. They show and apply them; they never resolve rules themselves. |
| **This repository** | Defines the rule catalog, the value schemas, the reference resolver and the shared test vectors that all three parts are tested against. |

`<ns>` stands for the technical namespace `halumar` ([`namespace.json`](../namespace.json)).

## Step by step

```text
device ──has──▶ profile ──holds──▶ one value per rule (catalog)
                                       │
                 device adjustments ───┤  (only rules that are not fixed)
                                       ▼
                 boundaries: guest access, parental controls, Hub only  (only restrict)
                                       ▼
                 resolved rules: value + source + reason + enforcement
                     │                      │                       │
                     ▼                      ▼                       ▼
                   app                     hub                  integration
             (client_config.rules)   (checks hub rules)   (rule snapshot, <ns>.control)
```

1. **Device.** Every paired device has a platform (`ios`, `ipados`, `tvos`, `watchos`, `android`,
   `android_tablet`, `android_tv`; `wearos` and `web` are provided for in the protocol, apps for them are planned and do not exist yet) and an
   access kind: `member`, or `guest` with an expiry
   (`$defs/device_access`). The access kind is set when the device is paired and never changes.
2. **Profile.** Every device has exactly one profile. A profile holds one value per rule of the
   catalog, plus per rule the checkbox "fixed" and, for comfort rules, "user's choice". It has a kind
   (`person`, `child`, `panel`, `tv`, `guest`, `house_sitter`, `babysitter`) and the switch
   **parental controls**. Profiles start empty, as a copy of a suggestion
   ([`data/profile-suggestions.json`](../data/profile-suggestions.json)) or as a copy of a device.
3. **Rules.** The catalog [`data/profile-rules.json`](../data/profile-rules.json) lists every rule
   with its values from strict to loose (`order`), its default, the platforms it applies to, its
   security class, its boundaries and how it is enforced. Value shapes are in
   [`schemas/common/profile-rule-values.json`](../schemas/common/profile-rule-values.json).
4. **Device adjustments.** The admin can change a rule that is not fixed for one device, permanently
   or until a time ([`schemas/common/device-override.json`](../schemas/common/device-override.json)).
5. **Boundaries.** Three boundaries lie over everything: **guest access** (from the device's access
   kind), **parental controls** (from the profile switch) and **Hub only** (while the device holds no
   Home Assistant key). They only restrict, and an adjustment never beats them. After a guest's access expires, every critical and sensitive rule falls to its
   strictest value.
6. **Resolved rules.** The hub resolves every rule for the device: applicability (platform, profile
   kind, parental controls), base value, own area, boundaries, prerequisites, guest expiry, device
   adjustment. The result per rule is `value`, `source`, `reason`, `locked`, `fixed`, `user_choice`,
   `expires_at`, `then` and `enforcement`
   ([`schemas/common/effective-rule.json`](../schemas/common/effective-rule.json),
   [`schemas/common/resolved-rules.json`](../schemas/common/resolved-rules.json)). The executable
   reference is [`tools/profiles_ref.py`](../tools/profiles_ref.py); the full order is in
   [profiles.md](profiles.md#resolution-one-rule-one-device).
7. **Enforcement.** Every resolved rule says who enforces it:
   - `hub`: the hub checks it on every request (for example setting up devices, kids rules);
   - `ha`: Home Assistant itself enforces it through the device's own Home Assistant user (for
     example remote access, through the user's "local only" flag);
   - `ha_control`: the device's Home Assistant user is read-only and can switch only through the
     integration action `<ns>.control`, which checks the rule; hiding still applies only in the app;
   - `app`: the app follows it. Someone with their own Home Assistant access is not bound by it.

   The app gets the resolved rules in `client_config.rules`. The integration gets a rule snapshot
   per device ([`schemas/common/enforcement-snapshot.json`](../schemas/common/enforcement-snapshot.json))
   and decides with it even while the hub is unreachable. Details: [enforcement.md](enforcement.md).

## A worked example

The vector [`fixtures/profiles/resolve/control-path-guest-boundary.json`](../fixtures/profiles/resolve/control-path-guest-boundary.json)
shows a boundary winning over both the profile and a device adjustment.

**Input.** A guest iPhone (`platform: ios`, `access.kind: guest`, expiring 2026-11-27). Its profile
is a copy of the suggestion **Adult**, whose Home Assistant access (`control_path`) is `checked`. The
admin also set a device adjustment `control_path = direct`.

**What the resolver does with three of the rules:**

| Rule | Profile says | Adjustment | Boundary | Resolved value | Source / reason | Enforcement |
|---|---|---|---|---|---|---|
| `control_path` | `checked` | `direct` | guest → at most `checked` | `checked` | `boundary` / `boundary_guest`, fixed | `ha` |
| `remote_control` | locks, alarm panels, garage doors and gates `view`, everything else `control` | – | none | the profile value | `profile` / `profile` | `ha_control` |
| `remote_access` | on | – | none (guests are not capped) | on | `profile` / `profile` | `ha` |

The vector lists the first two rules; running the reference shows the third:

```sh
python3 tools/profiles_ref.py fixtures/profiles/resolve/control-path-guest-boundary.json
```

The vector also expects `expected_ha_user_group: read_only` (`ha_user_group()` in the reference).

**What each part does with it:**

- **Hub.** Sends the app `client_config.rules` with these values and reasons. The admin UI shows the
  control path as locked with "Not available for guest access". The hub pushes the rule snapshot to
  the integration before the app gets its Home Assistant key.
- **Integration.** Puts the device's Home Assistant user into the read-only group. When the app calls
  `<ns>.control` from away (external route), the integration looks up the entity's remote level in
  the snapshot: a light switches, a lock only in the safe direction (lock, not unlock). Any direct
  action call of the device is refused by Home Assistant itself.
- **App.** Switches only through `<ns>.control` (`client_config.ha_enforcement.control_path` is
  `checked`), shows the guest UI and hides what `remote_control` hides from away. Hiding is an app
  rule: Home Assistant lets every user read every entity.

## Where to go next

- The full catalog, boundaries, resolution and reason codes: [profiles.md](profiles.md)
- Enforcement in Home Assistant, `<ns>.control` and the rule snapshot: [enforcement.md](enforcement.md)
- Access hours and the access switch: [access.md](access.md)
- Setting up devices from another device: [setup.md](setup.md)
- Parental controls managed by family members: [family.md](family.md)
- All documents: [docs/README.md](README.md)
