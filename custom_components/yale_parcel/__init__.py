"""Yale Parcel Box — companion to the core `yale` integration.

Adds courier-code management (a switch + an editable value per code), delivery-
mode services, and activity sensors for a Yale/August lock used as a parcel box.
Reuses the core `yale` integration's OAuth token, read live from its config entry
so it never expires. Guest/credential *management* endpoints are 403 for this
token (Yale gates those to the app's own login), so codes are managed via
/locks/{id}/pins and owner names are learned from the activity log.
"""
from __future__ import annotations

import asyncio
import logging
import random

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from yalexs.api_async import ApiAsync
from yalexs.const import Brand

from .const import (
    DOMAIN,
    CONF_HOUSE_ID, CONF_LOCK_ID, CONF_LOCK_NAME,
    CONF_DELIVERY_PIN, CONF_DELIVERY_PIN_USER_ID,
    API_BASE_URL, API_KEY, HEADER_API_KEY, HEADER_ACCESS_TOKEN,
    ENDPOINT_PINS, ENDPOINT_LOCK_OPERATE,
    EVENT_ACTIVITY,
    ACTION_LOAD, ACTION_ENABLE, ACTION_DISABLE, ACTION_DELETE,
)
from .coordinator import YaleParcelCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.TEXT]


def random_pin() -> str:
    """A random 6-digit code (avoids 0000-style weak defaults)."""
    return f"{random.randint(1, 999999):06d}"


def _get_yale_token(hass: HomeAssistant) -> str | None:
    for entry in hass.config_entries.async_entries("yale"):
        token = entry.data.get("token", {}).get("access_token")
        if token:
            return token
    return None


def _headers(token: str, *, json: bool = False) -> dict[str, str]:
    h = {HEADER_API_KEY: API_KEY, HEADER_ACCESS_TOKEN: token}
    if json:
        h["Content-Type"] = "application/json"
    return h


async def _wake(session, token, lock_id):
    # Yale's gateway rejects a body-less PUT with 415 (Unsupported Media Type),
    # so send an empty JSON body — aiohttp then sets Content-Type: application/json.
    url = (f"{API_BASE_URL}"
           f"{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action='status')}"
           "?v=2.3.1&type=async&intent=wakeup")
    async with session.put(url, headers=_headers(token), json={}, timeout=30) as resp:
        resp.raise_for_status()


async def _pin_cmd(session, token, lock_id, *, action, pin,
                   access_type="always", user_id=None, access_times=None):
    url = f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}"
    cmd = {"action": action, "pin": pin, "accessType": access_type}
    if user_id:
        cmd["userID"] = user_id
    if access_times:
        cmd["accessTimes"] = access_times
    async with session.post(url, headers=_headers(token, json=True),
                            json={"commands": [cmd]}, timeout=30) as resp:
        resp.raise_for_status()


async def _wake_then(session, token, lock_id, **kwargs):
    """Wake the lock, wait, then send a PIN command — retry once (codes only
    stick while the lock is awake, and the first wake can miss)."""
    for attempt in range(2):
        try:
            await _wake(session, token, lock_id)
            await asyncio.sleep(5)
            await _pin_cmd(session, token, lock_id, **kwargs)
            await asyncio.sleep(3)
            return
        except Exception as err:  # noqa: BLE001
            if attempt == 1:
                raise
            _LOGGER.debug("PIN command retry after: %s", err)
            await asyncio.sleep(3)


async def _discover(session, token) -> dict | None:
    """Auto-find the operable lock + house and a usable delivery PIN."""
    api = ApiAsync(session, brand=Brand.YALE_GLOBAL)
    locks = await api.async_get_operable_locks(token)
    if not locks:
        return None
    lock = locks[0]
    lock_id = lock.device_id
    house_id = lock.house_id
    delivery_pin, delivery_uid = "", ""
    try:
        async with session.get(f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
                               headers=_headers(token), timeout=30) as resp:
            resp.raise_for_status()
            data = await resp.json()
        items = data if isinstance(data, list) else (data.get("pins") or data.get("loaded") or [])
        for d in items:
            if isinstance(d, dict) and d.get("accessType") == "always" and d.get("pin"):
                delivery_pin = str(d["pin"])
                delivery_uid = d.get("userID") or d.get("UserID") or ""
                break
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Delivery-pin discovery failed: %s", err)
    return {
        CONF_LOCK_ID: lock_id,
        CONF_HOUSE_ID: house_id,
        CONF_LOCK_NAME: getattr(lock, "device_name", "Parcel Box"),
        CONF_DELIVERY_PIN: delivery_pin,
        CONF_DELIVERY_PIN_USER_ID: delivery_uid,
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    token = _get_yale_token(hass)
    if not token:
        _LOGGER.error("No Yale token — set up the core `yale` integration first")
        return False

    session = async_get_clientsession(hass)

    data = dict(entry.data)
    if not data.get(CONF_LOCK_ID) or not data.get(CONF_HOUSE_ID):
        discovered = await _discover(session, token)
        if not discovered:
            _LOGGER.error("No operable Yale locks found for this account")
            return False
        data = {**discovered, **{k: v for k, v in data.items() if v}}
        hass.config_entries.async_update_entry(entry, data=data)

    coordinator = YaleParcelCoordinator(
        hass, session, token, data[CONF_HOUSE_ID], data[CONF_LOCK_ID],
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "session": session,
        "token": token,
        "data": data,
    }

    _register_activity_events(hass, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, session, token, data, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


def _register_activity_events(hass: HomeAssistant, coordinator) -> None:
    """Fire an HA event on each new activity so users can automate on deliveries."""
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


def _register_services(hass, session, token, data, coordinator) -> None:
    lock_id = data[CONF_LOCK_ID]

    async def _enable(call: ServiceCall):
        await _wake_then(session, token, lock_id, action=ACTION_ENABLE,
                         pin=data[CONF_DELIVERY_PIN],
                         user_id=data.get(CONF_DELIVERY_PIN_USER_ID))
        await coordinator.async_request_refresh()

    async def _disable(call: ServiceCall):
        await _wake_then(session, token, lock_id, action=ACTION_DISABLE,
                         pin=data[CONF_DELIVERY_PIN],
                         user_id=data.get(CONF_DELIVERY_PIN_USER_ID))
        await coordinator.async_request_refresh()

    async def _create_temp(call: ServiceCall):
        pin = call.data.get("pin") or random_pin()
        start, end = call.data.get("start_time"), call.data.get("end_time")
        times = f"DTSTART={start};DTEND={end}" if start and end else None
        await _wake_then(session, token, lock_id, action=ACTION_LOAD, pin=pin,
                         access_type="temporary", user_id=call.data.get("user_id"),
                         access_times=times)
        await coordinator.async_request_refresh()

    async def _rotate(call: ServiceCall):
        new = call.data.get("new_pin") or random_pin()
        await _wake_then(session, token, lock_id, action=ACTION_LOAD, pin=new,
                         user_id=call.data.get("user_id"))
        await coordinator.async_request_refresh()

    async def _delete(call: ServiceCall):
        await _wake_then(session, token, lock_id, action=ACTION_DELETE,
                         pin=call.data.get("pin"), user_id=call.data.get("user_id"))
        await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "enable_delivery_mode", _enable)
    hass.services.async_register(DOMAIN, "disable_delivery_mode", _disable)
    hass.services.async_register(DOMAIN, "create_temp_pin", _create_temp)
    hass.services.async_register(DOMAIN, "rotate_pin", _rotate)
    hass.services.async_register(DOMAIN, "delete_pin", _delete)
