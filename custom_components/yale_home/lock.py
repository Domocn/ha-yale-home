"""The lock entity — owned by this integration (replaces HA's built-in Yale lock)."""
from __future__ import annotations

from homeassistant.components.lock import LockEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import _remote_op
from .const import CONF_LOCK_NAME, DOMAIN, ACTION_LOCK, ACTION_UNLATCH, ACTION_UNLOCK


def _lock_status(coordinator) -> str:
    lock = (coordinator.data or {}).get("lock") or {}
    return str((lock.get("LockStatus") or {}).get("status") or "").lower()


async def async_setup_entry(hass, entry, async_add_entities):
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator = store["coordinator"]
    async_add_entities([YaleLockEntity(coordinator, entry.data[CONF_LOCK_NAME],
                                       entry.data["lock_id"])])


class YaleLockEntity(CoordinatorEntity, LockEntity):
    _attr_has_entity_name = True
    _attr_name = None  # the device name is the lock name; this entity is the device's lock
    _attr_icon = "mdi:lock"

    def __init__(self, coordinator, lock_name, lock_id):
        super().__init__(coordinator)
        self._lock_name = lock_name
        self._lock_id = lock_id
        self._attr_unique_id = f"{lock_id}_lock"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, lock_id)},
            name=lock_name,
            manufacturer="Yale",
            model=self._model(),
        )

    def _model(self) -> str | None:
        lock = (self.coordinator.data or {}).get("lock") or {}
        return lock.get("Type") or lock.get("SerialNumber")

    @property
    def is_locked(self) -> bool:
        return _lock_status(self.coordinator) == "locked"

    @property
    def is_locking(self) -> bool:
        return _lock_status(self.coordinator) == "locking"

    @property
    def is_unlocking(self) -> bool:
        return _lock_status(self.coordinator) == "unlocking"

    @property
    def extra_state_attributes(self):
        lock = (self.coordinator.data or {}).get("lock") or {}
        status = lock.get("LockStatus") or {}
        bridge = lock.get("Bridge") or {}
        bstatus = bridge.get("status") or {}
        return {
            "door_state": status.get("doorState"),
            "lock_status": status.get("status"),
            "battery": lock.get("battery"),
            "bridge_online": bstatus.get("current"),
            "serial_number": lock.get("SerialNumber"),
            "house_id": lock.get("HouseID"),
        }

    async def _operate(self, action: str) -> None:
        token = await self.coordinator.get_token()
        await _remote_op(self.coordinator.session, self.coordinator.api_key, token, self._lock_id, action)
        await self.coordinator.async_request_refresh()

    async def async_lock(self, **kwargs):
        await self._operate(ACTION_LOCK)

    async def async_unlock(self, **kwargs):
        await self._operate(ACTION_UNLOCK)

    async def async_open(self, **kwargs):
        await self._operate(ACTION_UNLATCH)