"""Yale Parcel Box integration for Home Assistant."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YaleApiClient
from .const import (
    DOMAIN,
    SCAN_INTERVAL,
    CONF_ACCESS_TOKEN,
    CONF_HOUSE_ID,
    CONF_LOCK_ID,
    CONF_DELIVERY_PIN,
    CONF_DELIVERY_PIN_USER_ID,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LOCK, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Yale Parcel Box from a config entry."""
    session = async_get_clientsession(hass)
    client = YaleApiClient(session, entry.data[CONF_ACCESS_TOKEN])

    # Verify connection
    try:
        user = await client.async_get_user()
        _LOGGER.info(
            "Connected to Yale API as %s %s (ID: %s)",
            user.get("FirstName", ""),
            user.get("LastName", ""),
            user.get("UserID", ""),
        )
    except Exception as err:
        _LOGGER.error("Failed to connect to Yale API: %s", err)
        return False

    coordinator = YaleDataUpdateCoordinator(
        hass,
        client=client,
        house_id=entry.data[CONF_HOUSE_ID],
        lock_id=entry.data[CONF_LOCK_ID],
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    async def async_enable_delivery_mode(call: ServiceCall) -> None:
        """Enable delivery mode."""
        client = hass.data[DOMAIN][entry.entry_id]["client"]
        lock_id = entry.data[CONF_LOCK_ID]
        pin = entry.data[CONF_DELIVERY_PIN]
        user_id = entry.data[CONF_DELIVERY_PIN_USER_ID]

        await client.async_wake_lock(lock_id)
        await asyncio.sleep(5)
        await client.async_enable_delivery_pin(lock_id, pin, user_id)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    async def async_disable_delivery_mode(call: ServiceCall) -> None:
        """Disable delivery mode."""
        client = hass.data[DOMAIN][entry.entry_id]["client"]
        lock_id = entry.data[CONF_LOCK_ID]
        pin = entry.data[CONF_DELIVERY_PIN]
        user_id = entry.data[CONF_DELIVERY_PIN_USER_ID]

        await client.async_wake_lock(lock_id)
        await asyncio.sleep(5)
        await client.async_disable_delivery_pin(lock_id, pin, user_id)
        await asyncio.sleep(3)
        await coordinator.async_refresh()

    async def async_create_temp_pin(call: ServiceCall) -> None:
        """Create a temporary PIN for delivery."""
        client = hass.data[DOMAIN][entry.entry_id]["client"]
        lock_id = entry.data[CONF_LOCK_ID]
        pin = call.data.get("pin", "")
        user_id = call.data.get("user_id", entry.data[CONF_DELIVERY_PIN_USER_ID])
        start_time = call.data.get("start_time", "")
        end_time = call.data.get("end_time", "")

        await client.async_wake_lock(lock_id)
        await asyncio.sleep(5)
        result = await client.async_create_temporary_pin(
            lock_id, pin, user_id, start_time, end_time
        )
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


class YaleDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to poll Yale API for activity and lock state."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: YaleApiClient,
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
        self.client = client
        self.house_id = house_id
        self.lock_id = lock_id

    async def _async_update_data(self) -> dict:
        """Fetch data from Yale API."""
        try:
            activities = await self.client.async_get_activities(self.house_id, limit=5)
            pins = await self.client.async_get_pins(self.lock_id)
            locks = await self.client.async_get_locks()

            lock_data = locks.get(self.lock_id, {})

            # Determine lock state from activities
            lock_state = "locked"
            last_activity = activities[0] if activities else None
            if last_activity:
                action = last_activity.get("action", "")
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
