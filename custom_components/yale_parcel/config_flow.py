"""Config flow for Yale Parcel Box integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    API_BASE_URL,
    API_KEY,
    HEADER_API_KEY,
    HEADER_ACCESS_TOKEN,
    ENDPOINT_HOUSES,
    ENDPOINT_LOCKS,
    ENDPOINT_PINS,
    CONF_ACCESS_TOKEN,
    CONF_HOUSE_ID,
    CONF_LOCK_ID,
    CONF_LOCK_NAME,
    CONF_DELIVERY_PIN,
    CONF_DELIVERY_PIN_USER_ID,
)


class YaleParcelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Yale Parcel Box."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate the access token by fetching houses
            token = user_input[CONF_ACCESS_TOKEN]
            session = async_get_clientsession(self.hass)

            headers = {
                HEADER_API_KEY: API_KEY,
                HEADER_ACCESS_TOKEN: token,
            }

            try:
                resp = await session.get(
                    f"{API_BASE_URL}{ENDPOINT_HOUSES}",
                    headers=headers,
                )
                if resp.status == 200:
                    houses = await resp.json()
                    if houses:
                        # Store token and houses for next step
                        self._token = token
                        self._houses = houses
                        return await self.async_step_select_lock()
                else:
                    errors["base"] = "invalid_token"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_ACCESS_TOKEN): str,
            }),
            errors=errors,
        )

    async def async_step_select_lock(self, user_input=None):
        """Select the lock to control."""
        errors = {}

        if user_input is not None:
            house_id = user_input[CONF_HOUSE_ID]
            lock_id = user_input[CONF_LOCK_ID]

            # Fetch PINs to find delivery PIN
            session = async_get_clientsession(self.hass)
            headers = {
                HEADER_API_KEY: API_KEY,
                HEADER_ACCESS_TOKEN: self._token,
            }

            try:
                resp = await session.get(
                    f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
                    headers=headers,
                )
                if resp.status == 200:
                    pins_data = await resp.json()
                    pins = pins_data.get("loaded", [])

                    # Find a PIN suitable for delivery
                    delivery_pin = None
                    delivery_user_id = None
                    for pin in pins:
                        if pin.get("accessType") == "always":
                            delivery_pin = pin.get("pin")
                            delivery_user_id = pin.get("userID")
                            break

                    return self.async_create_entry(
                        title=f"Yale Parcel Box ({user_input.get(CONF_LOCK_NAME, lock_id)})",
                        data={
                            CONF_ACCESS_TOKEN: self._token,
                            CONF_HOUSE_ID: house_id,
                            CONF_LOCK_ID: lock_id,
                            CONF_LOCK_NAME: user_input.get(CONF_LOCK_NAME, lock_id),
                            CONF_DELIVERY_PIN: delivery_pin,
                            CONF_DELIVERY_PIN_USER_ID: delivery_user_id,
                        },
                    )
            except Exception:
                errors["base"] = "cannot_connect"

        # Build house/lock selection
        houses = self._houses
        lock_choices = {}
        for house in houses:
            house_id = house["HouseID"]
            house_name = house.get("HouseName", house_id)
            # We need to fetch locks for each house
            # For now, use the known lock
            lock_choices[f"{house_id}/C0DDB145F77449A89DBF547D138E366D"] = f"{house_name} - Parcel Box"

        return self.async_show_form(
            step_id="select_lock",
            data_schema=vol.Schema({
                vol.Required(CONF_HOUSE_ID): vol.In(
                    {h["HouseID"]: h.get("HouseName", h["HouseID"]) for h in houses}
                ),
                vol.Required(CONF_LOCK_ID): str,
                vol.Optional(CONF_LOCK_NAME, default="Parcel Box"): str,
            }),
            errors=errors,
        )
