"""Delivery Mode switch for Yale Parcel Box."""
from __future__ import annotations
import asyncio
import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LOCK_ID, CONF_DELIVERY_PIN, CONF_DELIVERY_PIN_USER_ID
from . import _wake, _pin_cmd

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DeliveryModeSwitch(
        coordinator=data["coordinator"],
        session=data["session"],
        access_token=data["access_token"],
        lock_id=entry.data[CONF_LOCK_ID],
        pin=entry.data[CONF_DELIVERY_PIN],
        user_id=entry.data[CONF_DELIVERY_PIN_USER_ID],
    )])


class DeliveryModeSwitch(SwitchEntity):
    """Switch to toggle delivery mode on/off."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:package-variant-closed"

    def __init__(self, coordinator, session, access_token, lock_id, pin, user_id):
        self._coordinator = coordinator
        self._session = session
        self._token = access_token
        self._lock_id = lock_id
        self._pin = pin
        self._user_id = user_id
        self._attr_name = "Delivery Mode"
        self._attr_unique_id = f"yale_parcel_{lock_id}_delivery_mode"

    @property
    def available(self):
        return self._coordinator.last_update_success

    @property
    def is_on(self):
        data = self._coordinator.data
        if not data: return False
        for p in data.get("pins", []):
            if p.pin == self._pin:
                return p.state == "loaded"
        return False

    async def async_turn_on(self, **kwargs):
        await _wake(self._session, self._token, self._lock_id)
        await asyncio.sleep(5)
        await _pin_cmd(self._session, self._token, self._lock_id,
                       "enable", self._pin, "always", self._user_id)
        await asyncio.sleep(3)
        await self._coordinator.async_refresh()

    async def async_turn_off(self, **kwargs):
        await _wake(self._session, self._token, self._lock_id)
        await asyncio.sleep(5)
        await _pin_cmd(self._session, self._token, self._lock_id,
                       "disable", self._pin, "always", self._user_id)
        await asyncio.sleep(3)
        await self._coordinator.async_refresh()

    async def async_added_to_hass(self):
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))

    @property
    def should_poll(self):
        return False
