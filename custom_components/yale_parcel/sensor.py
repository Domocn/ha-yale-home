"""Activity sensors for Yale Parcel Box."""
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

SENSOR_TYPES = [
    ("last_action", "Last Action", None),
    ("last_operator", "Last Operator", None),
    ("credential_type", "Last Credential", None),
    ("last_unlock_time", "Last Unlock Time", SensorDeviceClass.TIMESTAMP),
    ("activity_summary", "Activity Summary", None),
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    lock_id = entry.data[CONF_LOCK_ID]
    async_add_entities([
        YaleActivitySensor(coordinator, lock_id, st, name, dc)
        for st, name, dc in SENSOR_TYPES
    ])


class YaleActivitySensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, lock_id, sensor_type, name, device_class):
        self._coordinator = coordinator
        self._sensor_type = sensor_type
        self._attr_name = f"Parcel Box {name}"
        self._attr_unique_id = f"yale_parcel_{lock_id}_{sensor_type}"
        self._attr_device_class = device_class

    @property
    def available(self):
        return self._coordinator.last_update_success

    @property
    def native_value(self):
        data = self._coordinator.data
        if not data: return None
        activities = data.get("activities", [])
        last = activities[0] if activities else None

        if self._sensor_type == "last_action":
            return last.action.title() if last and last.action else "unknown"
        elif self._sensor_type == "last_operator":
            return (last.operated_by or "unknown") if last else "unknown"
        elif self._sensor_type == "credential_type":
            return (getattr(last, "credential_type", None) or "unknown") if last else "unknown"
        elif self._sensor_type == "last_unlock_time":
            for a in (activities or []):
                if a.action == "unlock" and a.activity_start_time:
                    return datetime.fromtimestamp(a.activity_start_time / 1000)
            return None
        elif self._sensor_type == "activity_summary":
            if last:
                a = (last.action or "unknown").title()
                w = last.operated_by or "unknown"
                c = getattr(last, "credential_type", None) or "unknown"
                return f"{a} by {w} ({c})"
            return "No recent activity"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._sensor_type != "last_action": return {}
        data = self._coordinator.data
        if not data: return {}
        last = data.get("last_activity")
        if not last: return {}
        return {
            "action": last.action,
            "activity_start_time": last.activity_start_time,
            "operated_by": last.operated_by,
            "was_pushed": last.was_pushed,
            "device_id": last.device_id,
        }

    async def async_added_to_hass(self):
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def should_poll(self):
        return False
