"""Yale Home — a standalone Home Assistant integration for Yale/August locks.

Authenticates directly to the Yale cloud with the same login the official Yale
Home app uses (email + password + one-time emailed code), obtaining an
owner-scope access token. That token grants everything the app can do: lock
control, PIN / entry-code management, and named-guest management. The API key
is NOT shipped in this repo — each user pastes their own Yale Home app API key
at setup (see the README for how to obtain it), keeping Yale's key out of the
public code.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .auth import YaleAppAuth, expiry_iso, parse_expiry_iso
from .const import (
    API_BASE_URL, BRAND_VALUE, HEADER_ACCESS_TOKEN, HEADER_API_KEY,
    HEADER_BRANDING, USER_AGENT,
    CONF_ACCESS_TOKEN, CONF_API_KEY, CONF_EMAIL, CONF_HOUSE_ID, CONF_INSTALL_ID,
    CONF_LOCK_ID, CONF_PASSWORD, CONF_TOKEN_EXPIRY,
    ENDPOINT_ACTIVITIES, ENDPOINT_ADD_USER, ENDPOINT_CREDENTIALS,
    ENDPOINT_GUESTLIST, ENDPOINT_GUEST_CREDENTIAL, ENDPOINT_LOCK_OPERATE,
    ENDPOINT_PINS, ENDPOINT_REMOVE_USER,
    EVENT_ACTIVITY,
    ACTION_DELETE, ACTION_DISABLE, ACTION_ENABLE, ACTION_LOAD,
    ACTION_LOCK, ACTION_UNLOCK, ACTION_UNLATCH,
)
from .coordinator import YaleHomeCoordinator

_LOGGER = logging.getLogger(__name__)

# The lock, battery and connectivity are the official core `yale` integration's
# job (it holds a live PubNub connection). yale_home does what it's uniquely good
# at: named entry codes, guest management, code expiry, and activity.
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.TEXT]


def random_pin() -> str:
    return f"{secrets.randbelow(999999):06d}"


def _headers(api_key: str, token: str, *, json_body: bool = False) -> dict[str, str]:
    h = {HEADER_API_KEY: api_key, HEADER_BRANDING: BRAND_VALUE,
         HEADER_ACCESS_TOKEN: token, "User-Agent": USER_AGENT}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


async def _wake(session, api_key, token, lock_id):
    url = (f"{API_BASE_URL}"
           f"{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action='status')}"
           "?v=2.3.1&type=async&intent=wakeup")
    async with session.put(url, headers=_headers(api_key, token, json_body=True),
                           json={}, timeout=30) as resp:
        if resp.status >= 400:
            raise HomeAssistantError(f"Yale wake failed ({resp.status}): {(await resp.text())[:200]}")


async def _pin_cmd(session, api_key, token, lock_id, *, action, pin,
                   access_type="always", user_id=None, partner_user_id=None, access_times=None):
    url = f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}"
    cmd: dict = {"action": action, "pin": pin, "accessType": access_type}
    if user_id:
        cmd["userID"] = user_id
    elif partner_user_id:
        cmd["partnerUserID"] = partner_user_id
    if access_times:
        cmd["accessTimes"] = access_times
    async with session.post(url, headers=_headers(api_key, token, json_body=True),
                            json={"commands": [cmd]}, timeout=30) as resp:
        if resp.status >= 400:
            raise HomeAssistantError(f"Yale {action} pin failed ({resp.status}): {(await resp.text())[:200]}")


async def _remote_op(session, api_key, token, lock_id, action):
    url = (f"{API_BASE_URL}{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action=action)}?type=async")
    async with session.put(url, headers=_headers(api_key, token, json_body=True),
                           json={}, timeout=30) as resp:
        if resp.status >= 400:
            raise HomeAssistantError(f"Yale {action} failed ({resp.status}): {(await resp.text())[:200]}")


async def _wake_then(session, api_key, token, lock_id, **kwargs):
    for attempt in range(2):
        try:
            await _wake(session, api_key, token, lock_id)
            await asyncio.sleep(5)
            await _pin_cmd(session, api_key, token, lock_id, **kwargs)
            await asyncio.sleep(3)
            return
        except Exception as err:
            if attempt == 1:
                raise
            _LOGGER.debug("PIN command retry after: %s", err)
            await asyncio.sleep(3)


def _partner_id_for(name: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return f"yalehome_{slug or 'guest'}_{secrets.token_hex(3)}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = dict(entry.data)
    session = async_get_clientsession(hass)
    auth = YaleAppAuth(session, api_key=data[CONF_API_KEY], install_id=data.get(CONF_INSTALL_ID))
    token, expiry = await auth.ensure_valid(
        data[CONF_EMAIL], data[CONF_PASSWORD],
        data.get(CONF_ACCESS_TOKEN), parse_expiry_iso(data.get(CONF_TOKEN_EXPIRY)),
    )
    if token != data.get(CONF_ACCESS_TOKEN) or expiry_iso(expiry) != data.get(CONF_TOKEN_EXPIRY):
        hass.config_entries.async_update_entry(
            entry, data={**data, CONF_ACCESS_TOKEN: token, CONF_TOKEN_EXPIRY: expiry_iso(expiry)})
    coordinator = YaleHomeCoordinator(
        hass, session, auth, email=data[CONF_EMAIL], password=data[CONF_PASSWORD],
        house_id=data[CONF_HOUSE_ID], lock_id=data[CONF_LOCK_ID], api_key=data[CONF_API_KEY],
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault("yale_home", {})[entry.entry_id] = {
        "coordinator": coordinator, "session": session, "auth": auth, "data": data,
    }
    _register_activity_events(hass, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, entry, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data["yale_home"].pop(entry.entry_id, None)
    return unloaded


def _register_activity_events(hass: HomeAssistant, coordinator) -> None:
    seen: dict[str, str | None] = {"id": None}

    @callback
    def _fire() -> None:
        last = (coordinator.data or {}).get("last_activity")
        if not last:
            return
        aid = str(last.get("dateTime") or last.get("entryTime") or last)
        if aid == seen["id"]:
            return
        seen["id"] = aid
        hass.bus.async_fire(EVENT_ACTIVITY, {"activity": last})

    coordinator.async_add_listener(_fire)


def _register_services(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    lock_id = coordinator.lock_id
    api_key = coordinator.api_key
    delivery_pin = coordinator._data.get("delivery_pin")
    delivery_uid = coordinator._data.get("delivery_pin_user_id")

    async def _get_tok():
        return await coordinator.get_token()

    async def _run(label, coro):
        try:
            await coro
            coordinator.record_pin(label, None)
        except Exception as err:
            coordinator.record_pin(None, str(err))
            raise
        finally:
            await coordinator.async_request_refresh()

    async def _enable(call):
        tok = await _get_tok()
        await _run("Enable access PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id,
                              action=ACTION_ENABLE, pin=delivery_pin, user_id=delivery_uid))

    async def _disable(call):
        tok = await _get_tok()
        await _run("Disable access PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id,
                              action=ACTION_DISABLE, pin=delivery_pin, user_id=delivery_uid))

    async def _create_temp(call):
        tok = await _get_tok()
        pin = call.data.get("pin") or random_pin()
        start, end = call.data.get("start_time"), call.data.get("end_time")
        times = f"DTSTART={start};DTEND={end}" if start and end else None
        user_id = call.data.get("user_id")
        partner = None if user_id else _partner_id_for(call.data.get("name"))
        await _run("Create temporary PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id, action=ACTION_LOAD,
                              pin=pin, access_type="temporary", user_id=user_id,
                              partner_user_id=partner, access_times=times))

    async def _rotate(call):
        tok = await _get_tok()
        await _run("Rotate PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id, action=ACTION_LOAD,
                              pin=call.data.get("new_pin") or random_pin(),
                              user_id=call.data.get("user_id")))

    async def _delete(call):
        tok = await _get_tok()
        await _run("Delete PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id, action=ACTION_DELETE,
                              pin=call.data.get("pin"), user_id=call.data.get("user_id")))

    async def _create_named_guest(call):
        tok = await _get_tok()
        first, last = call.data.get("first_name") or "", call.data.get("last_name") or ""
        pin = call.data.get("pin") or random_pin()
        at = call.data.get("access_type") or "always"
        start, end = call.data.get("start_time"), call.data.get("end_time")
        times = f"DTSTART={start};DTEND={end}" if (start and end and at == "temporary") else None
        other = call.data.get("other_user_id") or _partner_id_for(f"{first} {last}".strip() or None)
        body = {"firstName": first, "lastName": last, "credentialType": "pin",
                "pin": pin, "accessType": at}
        if times:
            body["accessTimes"] = times
        await _wake(coordinator.session, api_key, tok, lock_id)
        await asyncio.sleep(5)
        url = f"{API_BASE_URL}{ENDPOINT_GUEST_CREDENTIAL.format(lock_id=lock_id, other_user_id=other)}"
        async with coordinator.session.post(url, headers=_headers(api_key, tok, json_body=True),
                                            json=body, timeout=30) as resp:
            if resp.status >= 400:
                raise HomeAssistantError(f"Create guest failed ({resp.status}): {(await resp.text())[:200]}")
        coordinator.record_pin("Create named guest", None)
        await coordinator.async_request_refresh()

    async def _list_guests(call):
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_GUESTLIST.format(house_id=coordinator.house_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            text = await resp.text()
        _LOGGER.info("Yale guest list: %s", text[:500])
        hass.bus.async_fire("yale_home_guestlist", {"raw": text[:4000]})

    async def _remove_guest(call):
        tok = await _get_tok()
        other = call.data["other_user_id"]
        url = f"{API_BASE_URL}{ENDPOINT_REMOVE_USER.format(lock_id=lock_id, other_user_id=other)}"
        async with coordinator.session.delete(url, headers=_headers(api_key, tok), timeout=30) as resp:
            if resp.status >= 400:
                raise HomeAssistantError(f"Remove guest failed ({resp.status}): {(await resp.text())[:200]}")
        await coordinator.async_request_refresh()

    hass.services.async_register("yale_home", "enable_delivery_mode", _enable)
    hass.services.async_register("yale_home", "disable_delivery_mode", _disable)
    hass.services.async_register("yale_home", "create_temp_pin", _create_temp)
    hass.services.async_register("yale_home", "rotate_pin", _rotate)
    hass.services.async_register("yale_home", "delete_pin", _delete)
    hass.services.async_register("yale_home", "create_named_guest", _create_named_guest)
    hass.services.async_register("yale_home", "list_guests", _list_guests)
    hass.services.async_register("yale_home", "remove_guest", _remove_guest)