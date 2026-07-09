"""Config flow for Yale Parcel Box - reads token from core yale integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from yalexs.api_async import ApiAsync
from yalexs.const import Brand

from .const import (
    DOMAIN,
    CONF_HOUSE_ID,
    CONF_LOCK_ID,
    CONF_LOCK_NAME,
    CONF_DELIVERY_PIN,
    CONF_DELIVERY_PIN_USER_ID,
)


class YaleParcelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yale Parcel Box.

    Reads the OAuth token from the existing core yale integration.
    """

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step - auto-discovers token from core integration."""
        errors = {}

        # Get token from core yale integration
        access_token = None
        for entry in self.hass.config_entries.async_entries("yale"):
            token_data = entry.data.get("token", {})
            access_token = token_data.get("access_token")
            if access_token:
                break

        if not access_token:
            errors["base"] = "no_core_integration"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors=errors,
            )

        # Validate token and discover houses/locks
        session = async_get_clientsession(self.hass)
        api = ApiAsync(session, brand=Brand.YALE_GLOBAL)

        try:
            houses_resp = await api.async_get_houses(access_token)
            houses = await houses_resp.json()
            if not houses:
                errors["base"] = "no_houses"
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({}),
                    errors=errors,
                )

            self._token = access_token
            self._api = api
            self._session = session
            self._houses = houses

            if user_input is not None:
                return await self.async_step_select_lock(user_input)

            # Auto-advance if there's only one house
            return await self.async_step_select_lock()

        except Exception:
            errors["base"] = "cannot_connect"
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({}),
                errors=errors,
            )

    async def async_step_select_lock(self, user_input=None):
        """Select the lock to control."""
        errors = {}

        if user_input is not None:
            house_id = user_input[CONF_HOUSE_ID]
            lock_id = user_input[CONF_LOCK_ID]

            try:
                # Get locks for the selected house
                locks = await self._api.async_get_operable_locks(self._token)
                lock_data = None
                for lock in locks:
                    if lock.device_id == lock_id:
                        lock_data = lock
                        break

                # Get PINs to find a delivery PIN
                pins = await self._api.async_get_pins(self._token, lock_id)
                delivery_pin = None
                delivery_user_id = None
                for pin in pins:
                    if pin.access_type == "always":
                        delivery_pin = pin.pin
                        delivery_user_id = pin.user_id
                        break

                lock_name = lock_data.device_name if lock_data else user_input.get(CONF_LOCK_NAME, lock_id)

                return self.async_create_entry(
                    title=f"Yale Parcel Box ({lock_name})",
                    data={
                        CONF_HOUSE_ID: house_id,
                        CONF_LOCK_ID: lock_id,
                        CONF_LOCK_NAME: lock_name,
                        CONF_DELIVERY_PIN: delivery_pin,
                        CONF_DELIVERY_PIN_USER_ID: delivery_user_id,
                    },
                )
            except Exception:
                errors["base"] = "cannot_connect"

        # Build house choices
        house_choices = {}
        for house in self._houses:
            hid = house.get("HouseID", house.get("_id", ""))
            hname = house.get("HouseName", hid)
            house_choices[hid] = hname

        return self.async_show_form(
            step_id="select_lock",
            data_schema=vol.Schema({
                vol.Required(CONF_HOUSE_ID): vol.In(house_choices),
                vol.Required(CONF_LOCK_ID): str,
                vol.Optional(CONF_LOCK_NAME, default="Parcel Box"): str,
            }),
            errors=errors,
        )
