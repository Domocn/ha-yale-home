# Yale Home v3.0.0 — release notes

## The problem this fixes
The old "Yale Parcel Box" integration could manage entry codes on your lock, but it couldn't do everything the Yale Home app does. The big missing piece: **it couldn't create named guests** (e.g. "John — Airbnb stay") or fully manage who has access, because Yale only allowed the official phone app to do those things. The old integration worked by borrowing a limited, read-mostly token from Home Assistant's built-in Yale connection, and Yale deliberately blocked that token from changing guests. So you still had to open the app for anything involving real people's access.

## The fix
This integration now **signs in to Yale the same way the official Yale Home app does** — with your email, your password, and a one-time 6-digit code that Yale emails you. After that one code, Yale treats Home Assistant as another trusted copy of your app. That gives Home Assistant the same permissions the app has, so it can now:

- **Create and manage named guests** — give someone a name and their own entry code, permanent or time-limited (e.g. a guest's checkout time), straight from Home Assistant. No app needed.
- **Lock and unlock** the lock (the lock entity is now provided by this integration).
- **Show every code's expiry in plain English** — "Expires Sat 12 Jul 11:00 (in 3 h)", "Permanent — no expiry", or "Expired 2 h ago".
- **Show battery and connection status** for the lock.
- Keep all the old features: a switch and an editable code box per entry code, activity sensors ("Unlocked with code (Amazon Delivery) by Dom"), and a "Next code expiry" sensor.

## Setting it up (plain steps)
1. Add the **Yale Home** integration in Home Assistant.
2. Enter the **email and password** you use in the Yale Home app.
3. Yale emails a **6-digit code** — enter it. (This is a one-time step, just like signing the app in on a new phone. Home Assistant then stays trusted.)
4. Pick your **lock**, and choose whether it's a **parcel box** (courier deliveries) or a **door** (Airbnb / home guest access). You can change this later from the integration's Configure button.

That's it — no phone app needed afterwards.

## A note on security
Home Assistant stores your Yale password encrypted at rest, the same way it stores other credentials. The one-time emailed code is only there to confirm Home Assistant is allowed into your account (Yale's standard "new device" check) — it is not stored, and you won't be asked for it again unless you change your password. If you ever want to revoke access, remove the integration from Home Assistant (and, if you like, sign out of all devices from the Yale app).

## If you used the old "Yale Parcel Box" integration
- Remove the old **Yale Parcel Box** integration (Settings → Devices & Services → Yale Parcel Box → Delete) before or after adding this one.
- This integration provides the lock itself, so you can also **remove Home Assistant's built-in Yale integration** if you'd rather have everything in one place. (If you keep both, you'll see two lock entries for the same physical lock — disable one.)
- If you have automations that called the old services, update the service names from `yale_parcel.…` to `yale_home.…`, and the event from `yale_parcel_activity` to `yale_home_activity`.

## What "parcel box" vs "door" mode does
It only changes the wording Home Assistant shows you — "delivery PIN / courier" for a parcel box, "guest PIN / guest" for a door — and the names of a couple of services. The lock behaves the same either way. It's there so the language matches how you actually use the lock, which is handy if a lock is used as a normal front door (e.g. for Airbnb guests) rather than a parcel drop box.