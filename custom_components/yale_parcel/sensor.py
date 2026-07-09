"""Activity sensors derived from the Yale activity log.

Names come from the activity payload (callingUser = who acted, otherUser = the
code/person affected), since the guest-list endpoint is 403 for this token.
"""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_LOCK_ID

_ACTION_LABELS = {
    "lock": "Locked",
    "unlock": "Unlocked",
    "onetouchlock": "Locked",
    "remotelock": "Locked remotely",
    "remoteunlock": "Unlocked remotely",
    "pinunlock": "Unlocked with code",
    "loadpin": "Added code",
    "load_pin": "Added code",
    "deletepin": "Removed code",
    "delete_pin": "Removed code",
    "removedpin": "Removed code",
    "removepin": "Removed code",
    "enablepin": "Enabled code",
    "disablepin": "Disabled code",
    "associatedbridgeonline": "Bridge online",
    "associatedbridgeoffline": "Bridge offline",
    "doorclosed": "Door closed",
    "dooropen": "Door opened",
}


def _name(user) -> str:
    if not isinstance(user, dict):
        return ""
    first = user.get("FirstName") or user.get("firstName") or ""
    last = user.get("LastName") or user.get("lastName") or ""
    return f"{first} {last}".strip()


def _pretty_action(action: str) -> str:
    return _ACTION_LABELS.get(action.lower(), action.replace("_", " ").capitalize())


async def async_setup_entry(hass, entry, async_add_entities):
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator = store["coordinator"]
    lock_id = store["data"][CONF_LOCK_ID]
    async_add_entities([
        YaleActivitySensor(coordinator, lock_id, "Last action", "mdi:gesture-tap",
                           lambda a, c: _pretty_action(a.get("action", ""))),
        YaleActivitySensor(coordinator, lock_id, "Last operator", "mdi:account",
                           lambda a, c: _name(a.get("callingUser")) or "—"),
        YaleActivitySensor(coordinator, lock_id, "Last code affected", "mdi:dialpad",
                           lambda a, c: _name(a.get("otherUser")) or "—"),
        YaleActivitySensor(coordinator, lock_id, "Activity summary", "mdi:history",
                           _summary),
        YaleActivitySensor(coordinator, lock_id, "Codes", "mdi:counter",
                           lambda a, c: len((c.data or {}).get("pins", []))),
        YaleTimeSensor(coordinator, lock_id),
    ])


def _summary(activity: dict, coordinator) -> str:
    action = _pretty_action(activity.get("action", ""))
    actor = _name(activity.get("callingUser"))
    affected = _name(activity.get("otherUser"))
    if affected:
        action = f"{action} ({affected})"
    return f"{action} by {actor}".strip() if actor else action


class YaleActivitySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, lock_id, label, icon, extractor):
        super().__init__(coordinator)
        self._extractor = extractor
        self._attr_name = label
        self._attr_icon = icon
        self._attr_unique_id = f"{lock_id}_{label.lower().replace(' ', '_')}"
        self._attr_device_info = DeviceInfo(identifiers={("yale", lock_id)})

    @property
    def native_value(self):
        last = (self.coordinator.data or {}).get("last_activity")
        try:
            if self._attr_name == "Codes":
                return self._extractor({}, self.coordinator)
            if not last:
                return None
            return self._extractor(last, self.coordinator)
        except Exception:  # noqa: BLE001
            return None


class YaleTimeSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Last activity time"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, lock_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{lock_id}_last_activity_time"
        self._attr_device_info = DeviceInfo(identifiers={("yale", lock_id)})

    @property
    def native_value(self):
        last = (self.coordinator.data or {}).get("last_activity")
        if not isinstance(last, dict):
            return None
        raw = last.get("dateTime") or last.get("entryTime")
        if raw is None:
            return None
        try:
            # Yale activity timestamps are epoch milliseconds.
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (TypeError, ValueError):
            return None
