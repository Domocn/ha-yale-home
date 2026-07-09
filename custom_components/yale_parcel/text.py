"""An editable text per code — setting a new value rotates that PIN."""
from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import _wake_then
from .const import DOMAIN, CONF_LOCK_ID, ACTION_LOAD


async def async_setup_entry(hass, entry, async_add_entities):
    store = hass.data[DOMAIN][entry.entry_id]
    coordinator = store["coordinator"]
    lock_id = store["data"][CONF_LOCK_ID]
    known: set[str] = set()

    def _sync():
        new = []
        for pin in (coordinator.data or {}).get("pins", []):
            if pin.pin and pin.pin not in known:
                known.add(pin.pin)
                new.append(YaleCodeValue(coordinator, store, lock_id, pin.pin))
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

    def __init__(self, coordinator, store, lock_id, pin):
        super().__init__(coordinator)
        self._store = store
        self._lock_id = lock_id
        self._pin = pin  # current identity; updated after a rotate
        self._attr_unique_id = f"{lock_id}_code_{pin}"
        self._attr_device_info = DeviceInfo(identifiers={("yale", lock_id)})

    def _record(self):
        for p in (self.coordinator.data or {}).get("pins", []):
            if p.pin == self._pin:
                return p
        return None

    @property
    def name(self):
        p = self._record()
        owner = (p.owner if p else "") or "Code"
        return f"{owner} code"

    @property
    def native_value(self):
        p = self._record()
        return p.pin if p else self._pin

    @property
    def available(self):
        return self._record() is not None

    async def async_set_value(self, value: str) -> None:
        p = self._record()
        await _wake_then(self._store["session"], self._store["token"], self._lock_id,
                         action=ACTION_LOAD, pin=value,
                         user_id=p.user_id if p else None)
        self._pin = value
        await self.coordinator.async_request_refresh()
