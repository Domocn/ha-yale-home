"""Activity and code-expiry sensors for a Yale parcel box.

The lock, battery and connectivity live on the core `yale` integration; this
module is only the parcel-box extras: activity, code count, and expiry.
"""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import (SensorDeviceClass, SensorEntity,
                                             StateType)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_LOCK_ID
from .coordinator import format_expiry


_ACTION_LABELS = {
    "lock": "Locked", "unlock": "Unlocked", "onetouchlock": "Locked",
    "remotelock": "Locked remotely", "remoteunlock": "Unlocked remotely",
    "pinunlock": "Unlocked with code", "loadpin": "Added code",
    "load_pin": "Added code", "deletepin": "Removed code", "delete_pin": "Removed code",
    "removedpin": "Removed code", "removepin": "Removed code",
    "enablepin": "Enabled code", "disablepin": "Disabled code",
    "associatedbridgeonline": "Bridge online", "associatedbridgeoffline": "Bridge offline",
    "doorclosed": "Door closed", "dooropen": "Door opened",
}


def _pretty_action(action: str) -> str:
    return _ACTION_LABELS.get(action.lower(), action.replace("_", " ").capitalize())


def _name(user) -> str:
    if not isinstance(user, dict):
        return ""
    first = user.get("FirstName") or user.get("firstName") or ""
    last = user.get("LastName") or user.get("lastName") or ""
    return f"{first} {last}".strip()


async def async_setup_entry(hass, entry, async_add_entities):
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator = store["coordinator"]
    lock_id = entry.data[CONF_LOCK_ID]
    async_add_entities([
        YaleActivitySensor(coordinator, lock_id, "Last action", "mdi:gesture-tap",
                           lambda a, c: _pretty_action(a.get("action", ""))),
        YaleActivitySensor(coordinator, lock_id, "Last operator", "mdi:account",
                           lambda a, c: _name(a.get("callingUser")) or "—"),
        YaleActivitySensor(coordinator, lock_id, "Last code affected", "mdi:dialpad",
                           lambda a, c: _name(a.get("otherUser")) or "—"),
        YaleActivitySensor(coordinator, lock_id, "Activity summary", "mdi:history", _summary),
        YaleActivitySensor(coordinator, lock_id, "Codes", "mdi:counter",
                           lambda a, c: len((c.data or {}).get("pins", []))),
        YaleTimeSensor(coordinator, lock_id),
        YaleNextExpirySensor(coordinator, lock_id),
        YalePinCommandSensor(coordinator, lock_id),
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
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, lock_id)})

    @property
    def native_value(self) -> StateType:
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
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, lock_id)})

    @property
    def native_value(self):
        last = (self.coordinator.data or {}).get("last_activity")
        if not isinstance(last, dict):
            return None
        raw = last.get("dateTime") or last.get("entryTime")
        if raw is None:
            return None
        try:
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (TypeError, ValueError):
            return None


class YaleNextExpirySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Next code expiry"
    _attr_icon = "mdi:timer-alert-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, lock_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{lock_id}_next_code_expiry"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, lock_id)})

    def _next(self):
        now = dt_util.now()
        upcoming = []
        for p in (self.coordinator.data or {}).get("pins", []):
            ex = getattr(p, "expires_at", None)
            if ex and ex > now:
                upcoming.append((ex, p))
        if not upcoming:
            return None
        upcoming.sort(key=lambda x: x[0])
        return upcoming[0]

    @property
    def native_value(self):
        nxt = self._next()
        return nxt[0] if nxt else None

    @property
    def extra_state_attributes(self):
        nxt = self._next()
        if not nxt:
            pins = (self.coordinator.data or {}).get("pins")
            return {"status": "No expiring codes" if pins else "—"}
        ex, p = nxt
        return {"code": p.pin, "owner": p.owner or "—", "expiry": format_expiry(ex)}


class YalePinCommandSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Last pin command"
    _attr_icon = "mdi:clipboard-list-outline"

    def __init__(self, coordinator, lock_id):
        super().__init__(coordinator)
        self._attr_unique_id = f"{lock_id}_last_pin_command"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, lock_id)})

    @property
    def native_value(self):
        if self.coordinator.last_pin_error:
            return "Error"
        if self.coordinator.last_pin_ok:
            return "OK"
        return "—"

    @property
    def extra_state_attributes(self):
        return {
            "action": self.coordinator.last_pin_ok or self.coordinator.last_pin_error or "—",
            "result": "Error" if self.coordinator.last_pin_error else ("OK" if self.coordinator.last_pin_ok else "—"),
            "at": dt_util.as_local(self.coordinator.last_pin_at).isoformat() if self.coordinator.last_pin_at else None,
        }


# Battery + connectivity intentionally live on the core `yale` integration.