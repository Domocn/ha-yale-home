"""An editable text per code — setting a new value rotates that PIN.

The entity name mirrors the matching switch ("Owner (pin) ✏️") so that on the
auto-generated device page — where controls sort alphabetically — each code's
edit box lands directly next to its on/off switch instead of clumping into a
separate block.
"""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import _wake_then
from .const import DOMAIN, CONF_LOCK_ID, ACTION_LOAD
from .coordinator import format_expiry


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    lock_id = entry.data[CONF_LOCK_ID]
    known: set[str] = set()

    def _sync():
        new = []
        for pin in (coordinator.data or {}).get("pins", []):
            if pin.pin and pin.pin not in known:
                known.add(pin.pin)
                new.append(YaleCodeValue(coordinator, lock_id, pin.pin))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class YaleCodeValue(CoordinatorEntity, TextEntity):
    _attr_has_entity_name = True
    _attr_mode = TextMode.TEXT
    _attr_native_min = 4
    _attr_native_max = 8
    _attr_pattern = r"\d{4,8}"
    _attr_icon = "mdi:form-textbox-password"

    def __init__(self, coordinator, lock_id, pin):
        super().__init__(coordinator)
        self._lock_id = lock_id
        self._pin = pin
        self._attr_unique_id = f"{lock_id}_code_{pin}"
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
        pin = p.pin if p else self._pin
        return f"{owner} ({pin}) ✏️"

    @property
    def native_value(self):
        p = self._record()
        return p.pin if p else self._pin

    @property
    def available(self):
        return self._record() is not None

    @property
    def extra_state_attributes(self):
        p = self._record()
        if not p:
            return {}
        attrs = {
            "type": "Temporary" if getattr(p, "is_temporary", False) else "Permanent",
            "expiry": format_expiry(getattr(p, "expires_at", None)),
        }
        if getattr(p, "expires_at", None):
            attrs["expires_at"] = dt_util.as_local(p.expires_at).isoformat()
        if getattr(p, "valid_from", None):
            attrs["valid_from"] = dt_util.as_local(p.valid_from).isoformat()
        return attrs

    async def async_set_value(self, value: str) -> None:
        p = self._record()
        token = await self.coordinator.get_token()
        await _wake_then(self.coordinator.session, self.coordinator.api_key, token, self._lock_id,
                         action=ACTION_LOAD, pin=value,
                         user_id=p.user_id if p else None)
        self._pin = value
        await self.coordinator.async_request_refresh()