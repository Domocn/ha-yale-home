"""Lock platform for Yale Parcel Box."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LOCK_ID, CONF_LOCK_NAME

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Yale Parcel Box lock."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    client = hass.data[DOMAIN][entry.entry_id]["client"]

    async_add_entities([
        YaleParcelLock(
            coordinator=coordinator,
            client=client,
            lock_id=entry.data[CONF_LOCK_ID],
            name=entry.data.get(CONF_LOCK_NAME, "Parcel Box"),
        )
    ])


class YaleParcelLock(LockEntity):
    """Representation of a Yale Parcel Box lock."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, client, lock_id: str, name: str):
        """Initialize the lock."""
        self._coordinator = coordinator
        self._client = client
        self._lock_id = lock_id
        self._attr_name = name
        self._attr_unique_id = f"yale_parcel_{lock_id}"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._coordinator.last_update_success

    @property
    def is_locked(self) -> bool | None:
        """Return True if the lock is locked."""
        data = self._coordinator.data
        if data is None:
            return None
        return data.get("lock_state") == "locked"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        data = self._coordinator.data
        if data is None:
            return {}

        attrs = {}
        lock_data = data.get("lock_data", {})
        if lock_data:
            attrs["mac_address"] = lock_data.get("macAddress")
            attrs["house_name"] = lock_data.get("HouseName")

        last_activity = data.get("last_activity")
        if last_activity:
            calling_user = last_activity.get("callingUser", {})
            attrs["last_operator"] = f"{calling_user.get('FirstName', '')} {calling_user.get('LastName', '')}".strip()
            attrs["last_action"] = last_activity.get("action", "")
            info = last_activity.get("info", {})
            attrs["credential_type"] = info.get("credentialType", "")

        return attrs

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the lock."""
        await self._client.async_lock(self._lock_id)
        await self._coordinator.async_request_refresh()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the lock."""
        await self._client.async_unlock(self._lock_id)
        await self._coordinator.async_request_refresh()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def should_poll(self) -> bool:
        """No need to poll, coordinator handles it."""
        return False

    async def async_update(self) -> None:
        """Update the entity."""
        await self._coordinator.async_request_refresh()
