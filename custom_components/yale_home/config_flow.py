"""Config flow — Yale Home (APK key extraction + app-login + lock selection).

Security-transparent: each step tells the user what's happening and why.
Step 1: supply the Yale Home APK — the integration extracts the app's API key
from its own native library (the key never ships in this repo's code).
Step 2: sign in with email + password (stored encrypted by HA).
Step 3: enter the one-time emailed code (HA becomes a trusted device).
Step 4: pick the lock + whether it's a parcel box or a door.
"""
from __future__ import annotations

import logging
import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from yalexs.api_async import ApiAsync
from yalexs.const import Brand

_LOGGER = logging.getLogger(__name__)

from .auth import YaleAppAuth, YaleAuthError, expiry_iso

_KEY_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
from .const import (
    API_BASE_URL, BRAND_VALUE, HEADER_ACCESS_TOKEN, HEADER_API_KEY,
    HEADER_BRANDING, USER_AGENT,
    CONF_ACCESS_TOKEN, CONF_API_KEY, CONF_DEVICE_TYPE, CONF_EMAIL, CONF_HOUSE_ID,
    CONF_INSTALL_ID, CONF_LOCK_ID, CONF_LOCK_NAME, CONF_PASSWORD,
    CONF_TOKEN_EXPIRY, CONF_DELIVERY_PIN, CONF_DELIVERY_PIN_USER_ID,
    DEVICE_TYPE_PARCEL, ENDPOINT_PINS, device_labels,
)


def _device_type_selector() -> selector.SelectSelector:
    return selector.SelectSelector(selector.SelectSelectorConfig(
        options=[
            selector.SelectOptionDict(value=DEVICE_TYPE_PARCEL,
                                       label="Parcel box / locker (courier deliveries)"),
            selector.SelectOptionDict(value="door",
                                       label="Door (Airbnb / home guest access)"),
        ],
        mode=selector.SelectSelectorMode.DROPDOWN,
    ))


def _title(device_type: str, name: str) -> str:
    noun = device_labels(device_type).noun
    return f"Yale {noun} ({name})" if name else f"Yale {noun}"


class YaleHomeConfigFlow(config_entries.ConfigFlow, domain="yale_home"):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Step 1: paste your Yale Home API key (a UUID)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get(CONF_API_KEY) or "").strip()
            if _KEY_RE.fullmatch(key):
                self._api_key = key
                return await self.async_step_credentials()
            errors["base"] = "bad_key"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
        )

    async def async_step_credentials(self, user_input=None):
        """Step 2: email + password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)
            auth = YaleAppAuth(session, api_key=self._api_key)
            try:
                result = await auth.signin(email, password)
            except YaleAuthError as err:
                errors["base"] = "invalid_auth" if err.status in (400, 401, 403, 409) else "cannot_connect"
            else:
                self._email = email
                self._password = password
                self._install_id = auth.install_id
                self._auth = auth
                if result.need_verify and "email" in (result.verify_types or []):
                    self._step_token = result.step_token
                    return await self.async_step_code()
                if result.need_verify:
                    errors["base"] = "no_email_verify"
                else:
                    try:
                        self._token, self._expiry = await auth.get_owner_token(email, password)
                    except YaleAuthError as err:
                        errors["base"] = "invalid_auth" if err.status in (400, 401, 403, 409) else "cannot_connect"
                    else:
                        return await self.async_step_select_lock()
        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)),
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            }),
            errors=errors,
        )

    async def async_step_code(self, user_input=None):
        """Step 3: one-time emailed verification code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._auth.verify_email(self._step_token, self._email, user_input["code"])
                self._token, self._expiry = await self._auth.get_owner_token(self._email, self._password)
            except YaleAuthError:
                errors["base"] = "invalid_code"
            else:
                return await self.async_step_select_lock()
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({
                vol.Required("code"): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT, pattern=r"\d{6}")),
            }),
            errors=errors,
            description_placeholders={"email": self._email},
        )

    async def async_step_select_lock(self, user_input=None):
        """Step 4: pick the lock + parcel/door mode."""
        errors: dict[str, str] = {}
        session = async_get_clientsession(self.hass)
        api = ApiAsync(session, brand=Brand.YALE_GLOBAL)
        try:
            locks = await api.async_get_operable_locks(self._token)
        except Exception:
            locks, errors["base"] = [], "cannot_connect"

        if user_input is not None:
            lid = user_input[CONF_LOCK_ID]
            device_type = user_input.get(CONF_DEVICE_TYPE, DEVICE_TYPE_PARCEL)
            ld = next((l for l in locks if l.device_id == lid), None)
            hid = ld.house_id if ld else user_input.get(CONF_HOUSE_ID, "")
            name = ld.device_name if ld else "Yale Lock"
            dp, du = await self._delivery_pin(session, self._api_key, self._token, lid)
            await self.async_set_unique_id(lid)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title(device_type, name),
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_INSTALL_ID: self._install_id,
                    CONF_ACCESS_TOKEN: self._token,
                    CONF_TOKEN_EXPIRY: expiry_iso(self._expiry),
                    CONF_HOUSE_ID: hid,
                    CONF_LOCK_ID: lid,
                    CONF_LOCK_NAME: name,
                    CONF_DEVICE_TYPE: device_type,
                    CONF_DELIVERY_PIN: dp,
                    CONF_DELIVERY_PIN_USER_ID: du,
                },
            )

        choices = {l.device_id: (l.device_name or l.device_id) for l in locks}
        schema = (
            vol.Schema({
                vol.Required(CONF_LOCK_ID): vol.In(choices),
                vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_PARCEL): _device_type_selector(),
            }) if choices else vol.Schema({
                vol.Required(CONF_LOCK_ID): str,
                vol.Required(CONF_HOUSE_ID): str,
                vol.Required(CONF_DEVICE_TYPE, default=DEVICE_TYPE_PARCEL): _device_type_selector(),
            })
        )
        return self.async_show_form(step_id="select_lock", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        current = entry.data.get(CONF_DEVICE_TYPE, DEVICE_TYPE_PARCEL)
        if user_input is not None:
            new_type = user_input[CONF_DEVICE_TYPE]
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_DEVICE_TYPE: new_type},
                title=_title(new_type, entry.data.get(CONF_LOCK_NAME, "")),
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigured")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_DEVICE_TYPE, default=current): _device_type_selector()}),
        )

    async def _delivery_pin(self, session, api_key, token, lock_id):
        headers = {HEADER_API_KEY: api_key, HEADER_BRANDING: BRAND_VALUE,
                   HEADER_ACCESS_TOKEN: token, "User-Agent": USER_AGENT}
        try:
            async with session.get(f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
                                   headers=headers, timeout=30) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception:
            return None, None
        items = data if isinstance(data, list) else (data.get("pins") or data.get("loaded") or [])
        for d in items:
            if isinstance(d, dict) and d.get("accessType") == "always" and d.get("pin"):
                return str(d["pin"]), d.get("userID") or d.get("UserID")
        return None, None