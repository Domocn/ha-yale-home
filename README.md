# Yale Home for Home Assistant

A Home Assistant integration for **Yale / August smart locks** — used as a home
door **or** a parcel box. It signs in to the Yale cloud the same way the official
Yale Home app does, so it can do everything the app can: lock control, entry‑code
(PIN) management, temporary codes, and — because it holds an owner‑scope session —
show the **name of the guest/courier each code belongs to**.

> Not affiliated with, endorsed by, or connected to Yale or ASSA ABLOY. For
> personal use with your own account and your own devices.

## Features

- **Named codes** — every entry code shows whose it is (Amazon, DPD, a named
  guest…), pulled from your own account's guest list.
- **A switch per code** — enable/disable any code at a glance.
- **An editable value per code** — type a new number to rotate a code.
- **Temporary codes** — create time‑limited PINs; see when each expires.
- **Lock control + activity** — lock/unlock, and sensors for the latest action,
  who did it, and code expiry.
- **Parcel box or door mode** — the same features, worded for couriers or for
  Airbnb / home guests (switchable any time from *Configure*).

## Requirements

- A Yale / August lock on a **Yale Home** account (tested on the MD‑04I).
- Your Yale Home **API key** (a UUID) — see below.

## Getting your API key

The integration needs the Yale Home app's API key: a single UUID that is the
same inside every copy of the app (it identifies "the Yale app" to the server —
it is **not** an account password and grants nothing on its own without your
login). The key is **not** shipped in this repository. Obtaining it from your own
copy of the app is left to the user; once you have the UUID you simply paste it
during setup.

## Installation (HACS — custom repository)

1. HACS → ⋮ (top right) → **Custom repositories**.
2. Repository: `https://github.com/Domocn/ha-yale-home` · Category: **Integration**.
3. Install **Yale Home**, then restart Home Assistant.
4. Settings → Devices & Services → **Add Integration** → **Yale Home**.

(Or copy `custom_components/yale_home/` into your `config/custom_components/`.)

## Setup

1. **Paste your API key** (the UUID above).
2. **Sign in** with the email + password you use in the Yale Home app. Your
   password is stored encrypted by Home Assistant and never leaves your instance.
3. **Enter the one‑time code** Yale emails you — this makes your Home Assistant a
   trusted device. One‑time only; it won't ask again unless you change your
   password.
4. **Pick the lock** and whether it's a parcel box or a door.

## Privacy

Everything account‑specific — email, password, the session token — stays inside
your Home Assistant, encrypted. Nothing is sent anywhere except Yale's own API,
and nothing sensitive is stored in this repository.

## License

MIT
