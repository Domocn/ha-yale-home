# Yale Parcel Box — Home Assistant integration

Turn a Yale/August smart lock into a **managed parcel box** in Home Assistant.

This is a **companion** to the built-in [`yale`](https://www.home-assistant.io/integrations/yale/)
integration — not a replacement. It reuses the token from your existing Yale
integration (no extra login) and adds the code-management and activity features
core Yale doesn't expose. Your normal `lock.*` entity keeps working as-is.

## What you get

Attached to your existing Yale lock device:

- **A switch per entry code** — turn any courier/guest code on or off at a glance.
- **An editable value per code** — type a new number to rotate that code.
- **Activity sensors** — last action, who did it, which code was affected, a
  human-readable summary (e.g. *"Unlocked with code (Amazon Delivery) by Dom"*),
  a code count, and the last activity timestamp.
- **Services** — `enable_delivery_mode`, `disable_delivery_mode`,
  `create_temp_pin` (time-limited), `rotate_pin`, `delete_pin`.
- **An event** — `yale_parcel_activity` fires on every new activity, so you can
  automate on deliveries (chime, notify, snap a camera still…).

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

Settings → Devices & Services → **Add Integration** → **Yale Parcel Box**.
It finds your lock automatically from the Yale integration and picks it from a
list — no IDs or tokens to paste.

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
