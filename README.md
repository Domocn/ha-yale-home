# Yale Parcel Box / Door Lock — Home Assistant integration

Turn a Yale/August smart lock into a **managed parcel box** *or* a **guest-access
door** in Home Assistant — handy for receiving deliveries, and equally handy for
Airbnb hosts or homeowners who want per-guest PIN codes on a front door.

This is a **companion** to the built-in [`yale`](https://www.home-assistant.io/integrations/yale/)
integration — not a replacement. It reuses the token from your existing Yale
integration (no extra login) and adds the code-management and activity features
core Yale doesn't expose. Your normal `lock.*` entity keeps working as-is.

## What you get

Attached to your existing Yale lock device:

- **A switch per entry code** — turn any courier/guest code on or off at a glance.
- **An editable value per code** — type a new number to rotate that code.
- **Expiry shown, in plain words** — each code's switch and edit box carry a
  `type` (Permanent / Temporary) and an `expiry` attribute: *"Expires Sat 12 Jul
  11:00 (in 3 h)"*, *"Permanent — no expiry"*, or *"Expired 2 h ago"*. A
  **Next code expiry** timestamp sensor on the device shows the soonest-expiring
  guest code, so checkout times are visible at a glance.
- **A Last pin command sensor** — shows whether the last enable/create/rotate/
  delete succeeded, and if not, Yale's actual error message (instead of an
  opaque failure).
- **Activity sensors** — last action, who did it, which code was affected, a
  human-readable summary (e.g. *"Unlocked with code (Amazon Delivery) by Dom"*),
  a code count, and the last activity timestamp.
- **Services** — `enable_delivery_mode`, `disable_delivery_mode`,
  `create_temp_pin` (time-limited, auto-expires), `rotate_pin`, `delete_pin`.
- **An event** — `yale_parcel_activity` fires on every new activity, so you can
  automate on deliveries (chime, notify, snap a camera still…).

### Temporary / guest codes (Airbnb check-in)

`create_temp_pin` makes a code that auto-expires at the end time — ideal for a
courier window or a guest's stay. Yale requires every code to belong to a user;
since creating *named* guests is app-only, the service invents a `partnerUserID`
for you, so a standalone guest code works without touching the Yale app. Pass
an optional `name` to label it locally. Times are iCal compact UTC, e.g.
`start_time: 20260711T110000Z`, `end_time: 20260713T110000Z` (checkout 11:00).
Yale needs the lock awake, so the first call after the lock has been idle can
take ~10 s.

## Requirements

- The core **Yale** integration set up and working (this borrows its token).
- A Yale/August lock (tested on the **MD-04I** parcel lock).

## Installation

### HACS
[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domocn&repository=ha-yale-parcel&category=integration)

Or: HACS → ⋮ → Custom repositories → `https://github.com/Domocn/ha-yale-parcel` → Integration.

### Manual
Copy `custom_components/yale_parcel/` into your HA `config/custom_components/`, then restart.

## Setup

Settings → Devices & Services → **Add Integration** → **Yale Parcel Box & Door Lock**.
It finds your lock automatically from the Yale integration and picks it from a
list — no IDs or tokens to paste. You'll also pick **Used as**:

- **Parcel box / locker** — for courier deliveries.
- **Door** — for Airbnb / home guest access on a regular door.

This only changes the wording shown in the integration title and service
descriptions; the PIN services behave identically either way. Change it later
from the integration's **Configure** button.

> Door users: the services keep their slugs (`enable_delivery_mode`, …) so
> existing automations don't break — think "delivery mode" = "guest access" for
> a door. `create_temp_pin` is the one you want for a guest's stay code.

## Example automation

```yaml
# Announce a delivery when a courier code is used
automation:
  - alias: Parcel delivered
    trigger:
      - platform: event
        event_type: yale_parcel_activity
    condition:
      - condition: template
        value_template: "{{ 'code' in trigger.event.data.activity.action | lower }}"
    action:
      - service: notify.mobile_app
        data:
          message: >
            📦 {{ states('sensor.parcel_box_activity_summary') }}
```

## How it works & known limits

Talks to the Yale cloud (`api.aaecosystem.com`) using the OAuth token from the
core Yale integration.

- **Code management** (`POST /locks/{id}/pins`) — enable / disable / rotate /
  delete / temporary codes. Works fully.
- **Activity + names** (`GET /houses/{id}/activities`) — a code's owner name is
  learned the **first time that code is used** (Yale only returns names in the
  activity log), then remembered. Newly-created codes show as *"Code (NNNN)"*
  until first use.
- **Creating brand-new named guests is app-only.** Yale returns `403` on the
  guest-management endpoints for this token, so new courier profiles must be
  added in the Yale Home app. Everything on an existing code is controllable here.

## License

MIT
