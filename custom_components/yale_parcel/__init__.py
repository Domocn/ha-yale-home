"""Yale Parcel Box — adds activity monitoring, PIN management & delivery
mode on top of the core yale integration. No duplicate lock entity."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from yalexs.api_async import ApiAsync
from yalexs.const import Brand

from .const import (
    DOMAIN, SCAN_INTERVAL,
    CONF_HOUSE_ID, CONF_LOCK_ID, CONF_DELIVERY_PIN, CONF_DELIVERY_PIN_USER_ID,
    API_BASE_URL, API_KEY, HEADER_API_KEY, HEADER_ACCESS_TOKEN,
    ENDPOINT_PINS, ENDPOINT_LOCK_OPERATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yale Parcel Box from a config entry."""
    session = async_get_clientsession(hass)
    access_token = _get_yale_token(hass)
    if not access_token:
        _LOGGER.error("No Yale token found — set up the core yale integration first")
        return False

    api = ApiAsync(session, brand=Brand.YALE_GLOBAL)

    try:
        user = await api.async_get_user(access_token)
        _LOGGER.info("Connected to Yale as %s %s", user.get("FirstName",""), user.get("LastName",""))
    except Exception as err:
        _LOGGER.error("Yale API connection failed: %s", err)
        return False

    coordinator = YaleCoordinator(hass, api, session, access_token,
                                   entry.data[CONF_HOUSE_ID], entry.data[CONF_LOCK_ID])
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api, "session": session,
        "access_token": access_token, "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # ── Services ──────────────────────────────────────────────
    lock_id = entry.data[CONF_LOCK_ID]
    pin = entry.data[CONF_DELIVERY_PIN]
    user_id = entry.data[CONF_DELIVERY_PIN_USER_ID]

    async def _enable(call: ServiceCall):
        await _wake(session, access_token, lock_id)
        await asyncio.sleep(5)
        await _pin_cmd(session, access_token, lock_id, "enable", pin, "always", user_id)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    async def _disable(call: ServiceCall):
        await _wake(session, access_token, lock_id)
        await asyncio.sleep(5)
        await _pin_cmd(session, access_token, lock_id, "disable", pin, "always", user_id)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    async def _temp_pin(call: ServiceCall):
        p = call.data.get("pin", "")
        uid = call.data.get("user_id", user_id)
        st = call.data.get("start_time", "")
        et = call.data.get("end_time", "")
        at = f"DTSTART={st};DTEND={et}" if st and et else None
        await _wake(session, access_token, lock_id)
        await asyncio.sleep(5)
        await _pin_cmd(session, access_token, lock_id, "load", p, "temporary", uid, at)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, "enable_delivery_mode", _enable)
    hass.services.async_register(DOMAIN, "disable_delivery_mode", _disable)
    hass.services.async_register(DOMAIN, "create_temp_pin", _temp_pin)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _get_yale_token(hass: HomeAssistant) -> str | None:
    for e in hass.config_entries.async_entries("yale"):
        return e.data.get("token", {}).get("access_token")
    return None


async def _wake(session, token, lock_id):
    url = f"{API_BASE_URL}{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action='status')}?v=2.3.1&type=async&intent=wakeup"
    async with session.put(url, headers={HEADER_API_KEY: API_KEY, HEADER_ACCESS_TOKEN: token}) as r:
        r.raise_for_status()


async def _pin_cmd(session, token, lock_id, action, pin, access_type, user_id=None, access_times=None):
    cmd = {"action": action, "pin": pin, "accessType": access_type}
    if user_id: cmd["userID"] = user_id
    if access_times: cmd["accessTimes"] = access_times
    h = {HEADER_API_KEY: API_KEY, HEADER_ACCESS_TOKEN: token, "Content-Type": "application/json"}
    async with session.post(f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
                            headers=h, json={"commands": [cmd]}) as r:
        r.raise_for_status()
        return await r.json()


class YaleCoordinator(DataUpdateCoordinator):
    """Polls Yale API for activities and PINs."""

    def __init__(self, hass, api, session, access_token, house_id, lock_id):
        super().__init__(hass, _LOGGER, name=DOMAIN,
                         update_interval=timedelta(seconds=SCAN_INTERVAL))
        self.api = api
        self.session = session
        self.access_token = access_token
        self.house_id = house_id
        self.lock_id = lock_id

    async def _async_update_data(self):
        try:
            activities = await self.api.async_get_house_activities(self.access_token, self.house_id, limit=5)
            pins = await self.api.async_get_pins(self.access_token, self.lock_id)
            return {"activities": activities, "pins": pins,
                    "last_activity": activities[0] if activities else None}
        except Exception as err:
            raise UpdateFailed(f"Yale poll failed: {err}") from err
