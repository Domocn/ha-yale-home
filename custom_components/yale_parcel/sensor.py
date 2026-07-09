"""Sensor platform for Yale Parcel Box activity monitoring."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LOCK_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Yale Parcel Box sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    lock_id = entry.data[CONF_LOCK_ID]

    entities = [
        YaleParcelActivitySensor(coordinator, lock_id, "last_action", "Last Action"),
        YaleParcelActivitySensor(coordinator, lock_id, "last_operator", "Last Operator"),
        YaleParcelActivitySensor(coordinator, lock_id, "credential_type", "Last Credential"),
        YaleParcelActivitySensor(coordinator, lock_id, "last_unlock_time", "Last Unlock Time"),
        YaleParcelActivitySensor(coordinator, lock_id, "activity_summary", "Activity Summary"),
    ]
    async_add_entities(entities)


class YaleParcelActivitySensor(SensorEntity):
    """Sensor showing Yale Parcel Box activity data."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, lock_id: str, sensor_type: str, name: str):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._lock_id = lock_id
        self._sensor_type = sensor_type
        self._attr_name = f"Parcel Box {name}"
        self._attr_unique_id = f"yale_parcel_{lock_id}_{sensor_type}"

        if sensor_type == "last_unlock_time":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._coordinator.last_update_success

    @property
    def native_value(self) -> str | datetime | None:
        """Return the state of the sensor."""
        data = self._coordinator.data
        if data is None:
            return None

        activities = data.get("activities", [])
        last = activities[0] if activities else None

        if self._sensor_type == "last_action":
            if last:
                return last.get("action", "unknown").title()
            return "unknown"

        elif self._sensor_type == "last_operator":
            if last:
                user = last.get("callingUser", {})
                return f"{user.get('FirstName', '')} {user.get('LastName', '')}".strip()
            return "unknown"

        elif self._sensor_type == "credential_type":
            if last:
                info = last.get("info", {})
                return info.get("credentialType", "unknown")
            return "unknown"

        elif self._sensor_type == "last_unlock_time":
            for activity in (activities or []):
                if activity.get("action") == "unlock":
                    ts = activity.get("dateTime")
                    if ts:
                        return datetime.fromtimestamp(ts / 1000)
            return None

        elif self._sensor_type == "activity_summary":
            if last:
                action = last.get("action", "unknown").title()
                user = last.get("callingUser", {})
                who = f"{user.get('FirstName', '')} {user.get('LastName', '')}".strip()
                info = last.get("info", {})
                cred = info.get("credentialType", "unknown")
                return f"{action} by {who} ({cred})"
            return "No recent activity"

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        data = self._coordinator.data
        if data is None:
            return {}

        if self._sensor_type == "last_action":
            last = data.get("last_activity")
            if last:
                return {
                    "action": last.get("action"),
                    "date_time": last.get("dateTime"),
                    "calling_user": last.get("callingUser"),
                    "other_user": last.get("otherUser"),
                    "info": last.get("info"),
                }

        return {}

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def should_poll(self) -> bool:
        """No need to poll, coordinator handles it."""
        return False
