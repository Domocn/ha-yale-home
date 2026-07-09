# Yale Parcel Box - Home Assistant Integration

Custom integration for Yale/August smart locks used as parcel delivery boxes. Built on the reverse-engineered Yale API (`api.aaecosystem.com`).

## Features

- **Lock control** — lock/unlock via Yale cloud API (no Bluetooth required)
- **Activity monitoring** — see who unlocked, what credential they used, and when
- **Delivery mode** — enable/disable a delivery PIN for couriers with one click
- **Temporary PINs** — create one-time PINs for delivery drivers
- **Auto-refreshing token** — API token self-extends on every poll, never expires
- **Cloud polling** — 60-second activity polling via DataUpdateCoordinator

## Why This Exists

The official Yale integration works for basic lock control but doesn't expose:
- PIN code management (enable/disable/create)
- Activity log monitoring (who unlocked, what credential)
- Delivery mode workflows

This integration fills those gaps, specifically designed for parcel box use cases.

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domocn&repository=ha-yale-parcel&category=integration)

Or manually:
1. HACS → Integrations → ⋮ → Custom repositories
2. URL: `https://github.com/domocn/ha-yale-parcel`
3. Category: Integration

### Manual

Copy `custom_components/yale_parcel/` to your Home Assistant `custom_components/` directory.

## Setup

1. Settings → Devices & Services → Add Integration → **Yale Parcel Box**
2. Enter your Yale API access token (auto-filled if you have the Yale integration)
3. Select your house and lock
4. Done

## Entities Created

| Entity | Type | Description |
|---|---|---|
| `lock.yale_parcel_*` | Lock | Lock/unlock with operator attributes |
| `sensor.parcel_box_last_action` | Sensor | Last activity (Unlock, Lock, etc.) |
| `sensor.parcel_box_last_operator` | Sensor | Who performed the last action |
| `sensor.parcel_box_last_credential` | Sensor | Credential type used (pin/mobile/key) |
| `sensor.parcel_box_last_unlock_time` | Sensor | Timestamp of last unlock |
| `sensor.parcel_box_activity_summary` | Sensor | Human-readable: "Unlock by Becca Parcel (pin)" |

## Services

### `yale_parcel.enable_delivery_mode`
Wakes the lock and enables the delivery PIN for courier access.

### `yale_parcel.disable_delivery_mode`
Disables the delivery PIN to secure the parcel box.

### `yale_parcel.create_temp_pin`
Creates a temporary PIN for one-time delivery access.

| Parameter | Required | Description |
|---|---|---|
| `pin` | Yes | PIN code (4-8 digits) |
| `user_id` | No | User ID to associate with PIN |
| `start_time` | No | Access start (ISO format) |
| `end_time` | No | Access end (ISO format) |

## Example Automations

```yaml
# Enable delivery mode when you leave home
automation:
  - trigger: state
    entity_id: person.dom
    to: "not_home"
  - action: yale_parcel.enable_delivery_mode
    target:
      entity_id: lock.yale_parcel_parcel_box

# Record delivery and disable delivery mode
  - trigger: state
    entity_id: lock.yale_parcel_parcel_box
    to: "unlocked"
  - condition: template
    value_template: >
      {{ states('sensor.parcel_box_last_credential') == 'pin' }}
  - action: yale_parcel.disable_delivery_mode
    target:
      entity_id: lock.yale_parcel_parcel_box
```

## How It Works

This integration talks directly to the Yale cloud API at `api.aaecosystem.com`. It uses the same API that the Yale Home Android app uses, reverse-engineered from the APK.

- **Authentication**: Uses the OAuth token from your existing Yale integration
- **Lock control**: `PUT /remoteoperate/{lock_id}/{action}`
- **Activity log**: `GET /houses/{house_id}/activities`
- **PIN management**: `POST /locks/{lock_id}/pins` with command-based actions
- **Token refresh**: Every API response includes a fresh token in the `x-access-token` header

## License

MIT
