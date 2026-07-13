"""A switch per PIN code — on = enabled, off = disabled."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import _wake_then
from .const import DOMAIN, CONF_LOCK_ID, ACTION_ENABLE, ACTION_DISABLE
from .coordinator import format_expiry

_ON_STATES = {"enabled", "loaded", "active", "1", "true", "on"}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    lock_id = entry.data[CONF_LOCK_ID]
    known: set[str] = set()

    def _sync():
        new = []
        for pin in (coordinator.data or {}).get("pins", []):
            if pin.pin and pin.pin not in known:
                known.add(pin.pin)
                new.append(YalePinSwitch(coordinator, lock_id, pin.pin))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class YalePinSwitch(CoordinatorEntity, SwitchEntity):
    _attr_has_entity_name = True
    _attr_icon = "mdi:dialpad"

    def __init__(self, coordinator, lock_id, pin):
        super().__init__(coordinator)
        self._lock_id = lock_id
        self._pin = pin
        self._attr_unique_id = f"{lock_id}_pin_{pin}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, lock_id)})

    def _record(self):
        for p in (self.coordinator.data or {}).get("pins", []):
            if p.pin == self._pin:
                return p
        return None

    @property
    def name(self):
        p = self._record()
        owner = (p.owner if p else "") or "Code"
        return f"{owner} ({self._pin})"

    @property
    def is_on(self):
        p = self._record()
        return bool(p and str(p.state).lower() in _ON_STATES)

    @property
    def available(self):
        return self._record() is not None

    @property
    def extra_state_attributes(self):
        p = self._record()
        if not p:
            return {}
        attrs = {
            "owner": p.owner, "access_type": p.access_type,
            "user_id": p.user_id, "state": p.state,
            "type": "Temporary" if getattr(p, "is_temporary", False) else "Permanent",
            "expiry": format_expiry(getattr(p, "expires_at", None)),
        }
        if getattr(p, "expires_at", None):
            attrs["expires_at"] = dt_util.as_local(p.expires_at).isoformat()
        if getattr(p, "valid_from", None):
            attrs["valid_from"] = dt_util.as_local(p.valid_from).isoformat()
        return attrs

    async def _operate(self, action):
        p = self._record()
        token = await self.coordinator.get_token()
        await _wake_then(self.coordinator.session, self.coordinator.api_key, token, self._lock_id,
                         action=action, pin=self._pin,
                         user_id=p.user_id if p else None)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs):
        await self._operate(ACTION_ENABLE)

    async def async_turn_off(self, **kwargs):
        await self._operate(ACTION_DISABLE)