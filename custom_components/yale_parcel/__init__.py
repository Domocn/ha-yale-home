"""Yale Parcel Box integration - extends the core yale integration with
PIN management, activity monitoring, and delivery mode.

Uses the yalexs library (already installed as a dependency of the core
yale integration) for authentication and data access. Adds PIN management
via direct API calls since yalexs doesn't expose those endpoints yet.
"""
from __future__ import annotations

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
    DOMAIN,
    SCAN_INTERVAL,
    CONF_HOUSE_ID,
    CONF_LOCK_ID,
    CONF_LOCK_NAME,
    CONF_DELIVERY_PIN,
    CONF_DELIVERY_PIN_USER_ID,
    API_BASE_URL,
    API_KEY,
    HEADER_API_KEY,
    HEADER_ACCESS_TOKEN,
    ENDPOINT_PINS,
    ENDPOINT_LOCK_OPERATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LOCK, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yale Parcel Box from a config entry."""
    session = async_get_clientsession(hass)

    # Get the access token from the core yale integration
    access_token = await _get_yale_token(hass)
    if not access_token:
        _LOGGER.error("Could not get Yale access token from core integration")
        return False

    # Create yalexs API client for standard operations
    api = ApiAsync(session, brand=Brand.YALE_GLOBAL)

    # Verify connection
    try:
        user = await api.async_get_user(access_token)
        _LOGGER.info(
            "Connected to Yale API as %s %s",
            user.get("FirstName", ""),
            user.get("LastName", ""),
        )
    except Exception as err:
        _LOGGER.error("Failed to connect to Yale API: %s", err)
        return False

    coordinator = YaleDataUpdateCoordinator(
        hass,
        api=api,
        session=session,
        access_token=access_token,
        house_id=entry.data[CONF_HOUSE_ID],
        lock_id=entry.data[CONF_LOCK_ID],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "session": session,
        "access_token": access_token,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def async_enable_delivery_mode(call: ServiceCall) -> None:
        """Enable delivery mode."""
        data = hass.data[DOMAIN][entry.entry_id]
        lock_id = entry.data[CONF_LOCK_ID]
        pin = entry.data[CONF_DELIVERY_PIN]
        user_id = entry.data[CONF_DELIVERY_PIN_USER_ID]
        token = data["access_token"]

        await _wake_lock(session, token, lock_id)
        await asyncio.sleep(5)
        await _manage_pin(session, token, lock_id, "enable", pin, "always", user_id)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    async def async_disable_delivery_mode(call: ServiceCall) -> None:
        """Disable delivery mode."""
        data = hass.data[DOMAIN][entry.entry_id]
        lock_id = entry.data[CONF_LOCK_ID]
        pin = entry.data[CONF_DELIVERY_PIN]
        user_id = entry.data[CONF_DELIVERY_PIN_USER_ID]
        token = data["access_token"]

        await _wake_lock(session, token, lock_id)
        await asyncio.sleep(5)
        await _manage_pin(session, token, lock_id, "disable", pin, "always", user_id)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    async def async_create_temp_pin(call: ServiceCall) -> None:
        """Create a temporary PIN."""
        data = hass.data[DOMAIN][entry.entry_id]
        lock_id = entry.data[CONF_LOCK_ID]
        pin = call.data.get("pin", "")
        user_id = call.data.get("user_id", entry.data[CONF_DELIVERY_PIN_USER_ID])
        start_time = call.data.get("start_time", "")
        end_time = call.data.get("end_time", "")
        token = data["access_token"]

        access_times = f"DTSTART={start_time};DTEND={end_time}" if start_time and end_time else None
        await _wake_lock(session, token, lock_id)
        await asyncio.sleep(5)
        await _manage_pin(session, token, lock_id, "load", pin, "temporary", user_id, access_times)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    hass.services.async_register(DOMAIN, "enable_delivery_mode", async_enable_delivery_mode)
    hass.services.async_register(DOMAIN, "disable_delivery_mode", async_disable_delivery_mode)
    hass.services.async_register(DOMAIN, "create_temp_pin", async_create_temp_pin)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _get_yale_token(hass: HomeAssistant) -> str | None:
    """Get the access token from the core yale integration's config entry."""
    for entry in hass.config_entries.async_entries("yale"):
        token_data = entry.data.get("token", {})
        return token_data.get("access_token")
    return None


async def _wake_lock(session, access_token: str, lock_id: str) -> None:
    """Wake the lock via direct API call (not in yalexs library)."""
    url = f"{API_BASE_URL}{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action='status')}?v=2.3.1&type=async&intent=wakeup"
    headers = {
        HEADER_API_KEY: API_KEY,
        HEADER_ACCESS_TOKEN: access_token,
    }
    async with session.put(url, headers=headers) as resp:
        resp.raise_for_status()


async def _manage_pin(
    session,
    access_token: str,
    lock_id: str,
    action: str,
    pin: str,
    access_type: str = "always",
    user_id: str | None = None,
    access_times: str | None = None,
) -> dict:
    """Manage a PIN via direct API call (not in yalexs library)."""
    command = {
        "action": action,
        "pin": pin,
        "accessType": access_type,
    }
    if user_id:
        command["userID"] = user_id
    if access_times:
        command["accessTimes"] = access_times

    payload = {"commands": [command]}
    headers = {
        HEADER_API_KEY: API_KEY,
        HEADER_ACCESS_TOKEN: access_token,
        "Content-Type": "application/json",
    }
    url = f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}"
    async with session.post(url, headers=headers, json=payload) as resp:
        resp.raise_for_status()
        return await resp.json()


class YaleDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to poll Yale API for activity and lock state."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: ApiAsync,
        session,
        access_token: str,
        house_id: str,
        lock_id: str,
    ):
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self.session = session
        self.access_token = access_token
        self.house_id = house_id
        self.lock_id = lock_id

    async def _async_update_data(self) -> dict:
        """Fetch data from Yale API using yalexs library."""
        try:
            # Use yalexs for standard operations
            activities = await self.api.async_get_house_activities(
                self.access_token, self.house_id, limit=5
            )
            pins = await self.api.async_get_pins(self.access_token, self.lock_id)
            locks = await self.api.async_get_operable_locks(self.access_token)

            # Find our lock
            lock_data = None
            for lock in locks:
                if lock.device_id == self.lock_id:
                    lock_data = lock
                    break

            # Determine lock state
            lock_state = "locked"
            last_activity = activities[0] if activities else None
            if last_activity:
                action = last_activity.action
                if action == "unlock":
                    lock_state = "unlocked"
                elif action == "lock":
                    lock_state = "locked"

            return {
                "activities": activities,
                "pins": pins,
                "lock_data": lock_data,
                "lock_state": lock_state,
                "last_activity": last_activity,
            }
        except Exception as err:
            raise UpdateFailed(f"Error fetching Yale data: {err}") from err
