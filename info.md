# Yale Parcel Box

Custom integration for Yale/August smart locks used as parcel delivery boxes.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domocn&repository=ha-yale-home&category=integration)

## Features

- **Lock control** via Yale cloud API (no Bluetooth)
- **Activity monitoring** — who unlocked, what credential, when
- **Delivery mode** — enable/disable delivery PIN with one click
- **Temporary PINs** for one-time courier access
- **Auto-refreshing token** — never expires

## Setup

1. Add integration → search "Yale Parcel Box"
2. Token auto-filled from existing Yale integration
3. Select house and lock
4. Done

{% if installed %}
## Services

- `yale_parcel.enable_delivery_mode`
- `yale_parcel.disable_delivery_mode`
- `yale_parcel.create_temp_pin`
{% endif %}
