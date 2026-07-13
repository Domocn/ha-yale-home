"""Config flow — reuses the core `yale` integration's token, no login needed."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yalexs.api_async import ApiAsync
from yalexs.const import Brand

from .const import (
    DOMAIN, API_BASE_URL, API_KEY, HEADER_API_KEY, HEADER_ACCESS_TOKEN,
    ENDPOINT_PINS, CONF_HOUSE_ID, CONF_LOCK_ID, CONF_LOCK_NAME,
    CONF_DELIVERY_PIN, CONF_DELIVERY_PIN_USER_ID,
    CONF_DEVICE_TYPE, DEVICE_TYPE_PARCEL, DEVICE_TYPE_DOOR, device_labels,
)


def _device_type_selector() -> selector.SelectSelector:
    """Dropdown for how the lock is used — parcel box or a regular door."""
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=[
            selector.SelectOptionDict(
                value=DEVICE_TYPE_PARCEL,
                label="Parcel box / locker (courier deliveries)",
            ),
            selector.SelectOptionDict(
                value=DEVICE_TYPE_DOOR,
                label="Door (Airbnb / home guest access)",
            ),
        ],
        mode=selector.SelectSelectorMode.DROPDOWN,
    ))


def _title(device_type: str, name: str) -> str:
    noun = device_labels(device_type).noun
    return f"Yale {noun} ({name})" if name else f"Yale {noun}"


def _token(hass):
    for e in hass.config_entries.async_entries("yale"):
        t = e.data.get("token", {}).get("access_token")
        if t:
            return t
    return None


async def _delivery_pin(session, token, lock_id):
    """Best-effort: find an 'always' code to use as the delivery PIN (raw fetch —
    yalexs' Pin parser needs a firstName these codes lack)."""
    headers = {HEADER_API_KEY: API_KEY, HEADER_ACCESS_TOKEN: token}
    async with session.get(f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
                           headers=headers, timeout=30) as resp:
        resp.raise_for_status()
        data = await resp.json()
    items = data if isinstance(data, list) else (data.get("pins") or data.get("loaded") or [])
    for d in items:
        if isinstance(d, dict) and d.get("accessType") == "always" and d.get("pin"):
            return str(d["pin"]), d.get("userID") or d.get("UserID")
    return None, None


class YaleParcelConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        token = _token(self.hass)
        if not token:
            return self.async_show_form(
                step_id="user", data_schema=vol.Schema({}), errors={"base": "no_core"})
        self._token = token
        self._session = async_get_clientsession(self.hass)
        self._api = ApiAsync(self._session, brand=Brand.YALE_GLOBAL)
        return await self.async_step_select_lock()

    async def async_step_select_lock(self, user_input=None):
        errors = {}
        try:
            locks = await self._api.async_get_operable_locks(self._token)
        except Exception:  # noqa: BLE001
            locks, errors["base"] = [], "cannot_connect"

        if user_input is not None:
            lid = user_input[CONF_LOCK_ID]
            device_type = user_input.get(CONF_DEVICE_TYPE, DEVICE_TYPE_PARCEL)
            labels = device_labels(device_type)
            ld = next((l for l in locks if l.device_id == lid), None)
            hid = ld.house_id if ld else user_input.get(CONF_HOUSE_ID, "")
            name = ld.device_name if ld else labels.noun
            try:
                dp, du = await _delivery_pin(self._session, self._token, lid)
            except Exception:  # noqa: BLE001
                dp, du = None, None
            await self.async_set_unique_id(lid)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(device_type, name),
                data={CONF_HOUSE_ID: hid, CONF_LOCK_ID: lid, CONF_LOCK_NAME: name,
                      CONF_DEVICE_TYPE: device_type,
                      CONF_DELIVERY_PIN: dp, CONF_DELIVERY_PIN_USER_ID: du})

        choices = {l.device_id: (l.device_name or l.device_id) for l in locks}
        schema = (
            vol.Schema({
                vol.Required(CONF_LOCK_ID): vol.In(choices),
                vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_PARCEL): _device_type_selector(),
            })
            if choices else
            vol.Schema({
                vol.Required(CONF_LOCK_ID): str,
                vol.Required(CONF_HOUSE_ID): str,
                vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_PARCEL): _device_type_selector(),
            })
        )
        return self.async_show_form(step_id="select_lock", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        """Let the user change how an existing lock is used (parcel box vs door)."""
        entry = self._get_reconfigure_entry()
        current = entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_PARCEL)
        if user_input is not None:
            new_type = user_input[CONF_DEVICE_TYPE]
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_DEVICE_TYPE: new_type},
                title=_title(new_type, entry.data.get(CONF_LOCK_NAME, "")),
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigured")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_TYPE, default=current): _device_type_selector(),
            }),
        )
