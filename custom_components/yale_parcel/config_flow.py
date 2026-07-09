"""Config flow — auto-discovers token from core yale integration."""
from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yalexs.api_async import ApiAsync
from yalexs.const import Brand
from .const import (DOMAIN, CONF_HOUSE_ID, CONF_LOCK_ID, CONF_LOCK_NAME,
                    CONF_DELIVERY_PIN, CONF_DELIVERY_PIN_USER_ID)


class YaleParcelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        token = None
        for e in self.hass.config_entries.async_entries("yale"):
            token = e.data.get("token", {}).get("access_token")
            if token: break

        if not token:
            errors["base"] = "no_core"
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}), errors=errors)

        session = async_get_clientsession(self.hass)
        api = ApiAsync(session, brand=Brand.YALE_GLOBAL)
        try:
            resp = await api.async_get_houses(token)
            houses = await resp.json()
            if not houses:
                errors["base"] = "no_houses"
                return self.async_show_form(step_id="user", data_schema=vol.Schema({}), errors=errors)
            self._token = token
            self._api = api
            self._houses = houses
            return await self.async_step_select_lock()
        except Exception:
            errors["base"] = "cannot_connect"
            return self.async_show_form(step_id="user", data_schema=vol.Schema({}), errors=errors)

    async def async_step_select_lock(self, user_input=None):
        errors = {}
        if user_input is not None:
            hid = user_input[CONF_HOUSE_ID]
            lid = user_input[CONF_LOCK_ID]
            try:
                locks = await self._api.async_get_operable_locks(self._token)
                ld = next((l for l in locks if l.device_id == lid), None)
                pins = await self._api.async_get_pins(self._token, lid)
                dp, du = None, None
                for p in pins:
                    if p.access_type == "always":
                        dp, du = p.pin, p.user_id
                        break
                name = ld.device_name if ld else user_input.get(CONF_LOCK_NAME, lid)
                return self.async_create_entry(
                    title=f"Yale Parcel Box ({name})",
                    data={CONF_HOUSE_ID: hid, CONF_LOCK_ID: lid, CONF_LOCK_NAME: name,
                          CONF_DELIVERY_PIN: dp, CONF_DELIVERY_PIN_USER_ID: du})
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(step_id="select_lock", data_schema=vol.Schema({
            vol.Required(CONF_HOUSE_ID): vol.In({h["HouseID"]: h.get("HouseName", h["HouseID"]) for h in self._houses}),
            vol.Required(CONF_LOCK_ID): str,
            vol.Optional(CONF_LOCK_NAME, default="Parcel Box"): str,
        }), errors=errors)
