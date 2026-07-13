# Yale Home

Home Assistant integration for **Yale / August smart locks** — used as a home
door or a parcel box. It signs in like the official Yale Home app to get an
owner‑scope session, so it can manage entry codes **and show whose each code is**.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domocn&repository=ha-yale-home&category=integration)

## Features

- **Named codes** — every entry code shows whose it is (Amazon, DPD, a named
  guest…), pulled from your account's guest list
- **A switch + editable value per code** — enable/disable, or type a new number to rotate
- **Temporary codes** with expiry tracking
- **Lock control + activity** sensors — last action, who did it, when
- **Parcel box or door mode** — the same features, worded for couriers or home guests

## Setup

1. Add integration → **Yale Home**
2. Paste your Yale Home API key (a UUID)
3. Sign in with your Yale email + password, then the one‑time code Yale emails you
4. Pick your lock and parcel‑box / door mode

{% if installed %}
## Services

- `yale_home.create_temp_pin` / `rotate_pin` / `delete_pin`
- `yale_home.enable_delivery_mode` / `disable_delivery_mode`
- `yale_home.create_named_guest` / `remove_guest` / `list_guests`
{% endif %}
