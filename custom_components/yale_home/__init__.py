"""Yale Home — a standalone Home Assistant integration for Yale/August locks.

Authenticates directly to the Yale cloud with the same login the official Yale
Home app uses (email + password + one-time emailed code), obtaining an
owner-scope access token. That token grants everything the app can do: lock
control, PIN / entry-code management, and named-guest management. The API key
is NOT shipped in this repo — each user pastes their own Yale Home app API key
at setup (see the README for how to obtain it), keeping Yale's key out of the
public code.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_state_change_event

from .auth import YaleAppAuth, expiry_iso, parse_expiry_iso
from .const import (
    API_BASE_URL, BRAND_VALUE, HEADER_ACCESS_TOKEN, HEADER_API_KEY,
    HEADER_BRANDING, USER_AGENT,
    CONF_ACCESS_TOKEN, CONF_API_KEY, CONF_EMAIL, CONF_HOUSE_ID, CONF_INSTALL_ID,
    CONF_LOCK_ID, CONF_PASSWORD, CONF_TOKEN_EXPIRY, CONF_TRIGGER_ENTITY_ID,
    ENDPOINT_ACTIVITIES, ENDPOINT_ADD_USER, ENDPOINT_CREDENTIALS,
    ENDPOINT_GUESTLIST, ENDPOINT_GUEST_CREDENTIAL, ENDPOINT_GUEST_CREDENTIAL_READ,
    ENDPOINT_LOCK_INFO, ENDPOINT_LOCK_OPERATE, ENDPOINT_MANAGED_DEVICES,
    ENDPOINT_KEYPAD_INFO, ENDPOINT_CREATE_SCHEDULE_RULE,
    ENDPOINT_PINS, ENDPOINT_REMOVE_USER, ENDPOINT_UNITY_SETTINGS,
    EVENT_ACTIVITY,
    ACTION_DELETE, ACTION_DISABLE, ACTION_ENABLE, ACTION_LOAD,
    ACTION_LOCK, ACTION_UNLOCK, ACTION_UNLATCH,
)
from .coordinator import YaleHomeCoordinator

_LOGGER = logging.getLogger(__name__)

# The lock, battery and connectivity are the official core `yale` integration's
# job (it holds a live PubNub connection). yale_home does what it's uniquely good
# at: named entry codes, guest management, code expiry, and activity.
PLATFORMS = [Platform.SENSOR, Platform.SWITCH, Platform.TEXT]


def random_pin() -> str:
    return f"{secrets.randbelow(999999):06d}"


def _headers(api_key: str, token: str, *, json_body: bool = False) -> dict[str, str]:
    h = {HEADER_API_KEY: api_key, HEADER_BRANDING: BRAND_VALUE,
         HEADER_ACCESS_TOKEN: token, "User-Agent": USER_AGENT}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


async def _wake(session, api_key, token, lock_id):
    url = (f"{API_BASE_URL}"
           f"{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action='status')}"
           "?v=2.3.1&type=async&intent=wakeup")
    async with session.put(url, headers=_headers(api_key, token, json_body=True),
                           json={}, timeout=30) as resp:
        if resp.status >= 400:
            raise HomeAssistantError(f"Yale wake failed ({resp.status}): {(await resp.text())[:200]}")


async def _pin_cmd(session, api_key, token, lock_id, *, action, pin,
                   access_type="always", user_id=None, partner_user_id=None, access_times=None):
    url = f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}"
    cmd: dict = {"action": action, "pin": pin, "accessType": access_type}
    if user_id:
        cmd["userID"] = user_id
    elif partner_user_id:
        cmd["partnerUserID"] = partner_user_id
    if access_times:
        cmd["accessTimes"] = access_times
    async with session.post(url, headers=_headers(api_key, token, json_body=True),
                            json={"commands": [cmd]}, timeout=30) as resp:
        if resp.status >= 400:
            raise HomeAssistantError(f"Yale {action} pin failed ({resp.status}): {(await resp.text())[:200]}")


async def _remote_op(session, api_key, token, lock_id, action):
    url = (f"{API_BASE_URL}{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action=action)}?type=async")
    async with session.put(url, headers=_headers(api_key, token, json_body=True),
                           json={}, timeout=30) as resp:
        if resp.status >= 400:
            raise HomeAssistantError(f"Yale {action} failed ({resp.status}): {(await resp.text())[:200]}")


async def _wake_then(session, api_key, token, lock_id, **kwargs):
    for attempt in range(2):
        try:
            await _wake(session, api_key, token, lock_id)
            await asyncio.sleep(5)
            await _pin_cmd(session, api_key, token, lock_id, **kwargs)
            await asyncio.sleep(3)
            return
        except Exception as err:
            if attempt == 1:
                raise
            _LOGGER.debug("PIN command retry after: %s", err)
            await asyncio.sleep(3)


def _partner_id_for(name: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return f"yalehome_{slug or 'guest'}_{secrets.token_hex(3)}"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = dict(entry.data)
    session = async_get_clientsession(hass)
    auth = YaleAppAuth(session, api_key=data[CONF_API_KEY], install_id=data.get(CONF_INSTALL_ID))
    token, expiry = await auth.ensure_valid(
        data[CONF_EMAIL], data[CONF_PASSWORD],
        data.get(CONF_ACCESS_TOKEN), parse_expiry_iso(data.get(CONF_TOKEN_EXPIRY)),
    )
    if token != data.get(CONF_ACCESS_TOKEN) or expiry_iso(expiry) != data.get(CONF_TOKEN_EXPIRY):
        hass.config_entries.async_update_entry(
            entry, data={**data, CONF_ACCESS_TOKEN: token, CONF_TOKEN_EXPIRY: expiry_iso(expiry)})
    coordinator = YaleHomeCoordinator(
        hass, session, auth, email=data[CONF_EMAIL], password=data[CONF_PASSWORD],
        house_id=data[CONF_HOUSE_ID], lock_id=data[CONF_LOCK_ID], api_key=data[CONF_API_KEY],
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault("yale_home", {})[entry.entry_id] = {
        "coordinator": coordinator, "session": session, "auth": auth, "data": data,
    }
    _register_activity_events(hass, coordinator)
    _register_instant_trigger(hass, entry, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _register_services(hass, entry, coordinator)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data["yale_home"].pop(entry.entry_id, None)
    return unloaded


def _register_activity_events(hass: HomeAssistant, coordinator) -> None:
    seen: dict[str, str | None] = {"id": None}

    @callback
    def _fire() -> None:
        last = (coordinator.data or {}).get("last_activity")
        if not last:
            return
        aid = str(last.get("dateTime") or last.get("entryTime") or last)
        if aid == seen["id"]:
            return
        seen["id"] = aid
        hass.bus.async_fire(EVENT_ACTIVITY, {"activity": last})

    coordinator.async_add_listener(_fire)


def _register_instant_trigger(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    """Optional CONF_TRIGGER_ENTITY_ID: when a local-push lock entity for the
    SAME physical lock (e.g. a yalexs_ble or core yale entity) changes
    state, immediately request a coordinator refresh instead of waiting up
    to SCAN_INTERVAL seconds. Combines yalexs_ble's instant local BLE state
    push with this integration's cloud activity/PIN attribution."""
    trigger_entity_id = entry.data.get(CONF_TRIGGER_ENTITY_ID)
    if not trigger_entity_id:
        return

    @callback
    def _on_trigger_state_change(event) -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        async_track_state_change_event(hass, [trigger_entity_id], _on_trigger_state_change))


def _register_services(hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
    lock_id = coordinator.lock_id
    api_key = coordinator.api_key
    delivery_pin = coordinator._data.get("delivery_pin")
    delivery_uid = coordinator._data.get("delivery_pin_user_id")

    async def _get_tok():
        return await coordinator.get_token()

    async def _run(label, coro):
        try:
            await coro
            coordinator.record_pin(label, None)
        except Exception as err:
            coordinator.record_pin(None, str(err))
            raise
        finally:
            await coordinator.async_request_refresh()

    async def _enable(call):
        tok = await _get_tok()
        await _run("Enable access PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id,
                              action=ACTION_ENABLE, pin=delivery_pin, user_id=delivery_uid))

    async def _disable(call):
        tok = await _get_tok()
        await _run("Disable access PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id,
                              action=ACTION_DISABLE, pin=delivery_pin, user_id=delivery_uid))

    async def _create_temp(call):
        tok = await _get_tok()
        pin = call.data.get("pin") or random_pin()
        start, end = call.data.get("start_time"), call.data.get("end_time")
        times = f"DTSTART={start};DTEND={end}" if start and end else None
        user_id = call.data.get("user_id")
        partner = None if user_id else _partner_id_for(call.data.get("name"))
        await _run("Create temporary PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id, action=ACTION_LOAD,
                              pin=pin, access_type="temporary", user_id=user_id,
                              partner_user_id=partner, access_times=times))

    async def _rotate(call):
        tok = await _get_tok()
        await _run("Rotate PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id, action=ACTION_LOAD,
                              pin=call.data.get("new_pin") or random_pin(),
                              user_id=call.data.get("user_id")))

    async def _delete(call):
        tok = await _get_tok()
        await _run("Delete PIN",
                   _wake_then(coordinator.session, api_key, tok, lock_id, action=ACTION_DELETE,
                              pin=call.data.get("pin"), user_id=call.data.get("user_id")))

    async def _create_named_guest(call):
        tok = await _get_tok()
        first, last = call.data.get("first_name") or "", call.data.get("last_name") or ""
        pin = call.data.get("pin") or random_pin()
        at = call.data.get("access_type") or "always"
        start, end = call.data.get("start_time"), call.data.get("end_time")
        times = f"DTSTART={start};DTEND={end}" if (start and end and at == "temporary") else None
        other = call.data.get("other_user_id") or _partner_id_for(f"{first} {last}".strip() or None)
        body = {"firstName": first, "lastName": last, "credentialType": "pin",
                "pin": pin, "accessType": at}
        if times:
            body["accessTimes"] = times
        await _wake(coordinator.session, api_key, tok, lock_id)
        await asyncio.sleep(5)
        url = f"{API_BASE_URL}{ENDPOINT_GUEST_CREDENTIAL.format(lock_id=lock_id, other_user_id=other)}"
        async with coordinator.session.post(url, headers=_headers(api_key, tok, json_body=True),
                                            json=body, timeout=30) as resp:
            if resp.status >= 400:
                raise HomeAssistantError(f"Create guest failed ({resp.status}): {(await resp.text())[:200]}")
        coordinator.record_pin("Create named guest", None)
        await coordinator.async_request_refresh()

    async def _list_guests(call):
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_GUESTLIST.format(house_id=coordinator.house_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            text = await resp.text()
        _LOGGER.info("Yale guest list: %s", text[:500])
        hass.bus.async_fire("yale_home_guestlist", {"raw": text[:4000]})

    async def _remove_guest(call):
        tok = await _get_tok()
        other = call.data["other_user_id"]
        url = f"{API_BASE_URL}{ENDPOINT_REMOVE_USER.format(lock_id=lock_id, other_user_id=other)}"
        async with coordinator.session.delete(url, headers=_headers(api_key, tok), timeout=30) as resp:
            if resp.status >= 400:
                raise HomeAssistantError(f"Remove guest failed ({resp.status}): {(await resp.text())[:200]}")
        await coordinator.async_request_refresh()

    async def _dump_unity_settings(call):
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_UNITY_SETTINGS.format(lock_id=lock_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            text = await resp.text()
            status = resp.status
        _LOGGER.info("Yale unity settings (%s): %s", status, text[:1000])
        hass.bus.async_fire("yale_home_unity_settings", {"status": status, "raw": text[:4000]})

    async def _set_delivery_box_mode(call):
        """Diagnostic write: GET the settings, merge in isDeliveryBoxModeEnabled,
        PUT the full object back, then GET again to confirm what actually
        stuck. Unverified endpoint/verb — fires its own event either way so
        you can see the raw before/after/error without guessing."""
        enabled = bool(call.data.get("enabled", True))
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_UNITY_SETTINGS.format(lock_id=lock_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            before_status = resp.status
            before_text = await resp.text()
        import json as _json
        try:
            current = _json.loads(before_text)
        except ValueError:
            current = None
        result = {"before_status": before_status, "before_raw": before_text[:2000]}
        if not isinstance(current, dict):
            result["error"] = "GET settings did not return a JSON object"
            hass.bus.async_fire("yale_home_set_delivery_box_mode", result)
            return
        merged = {**current, "isDeliveryBoxModeEnabled": enabled}
        async with coordinator.session.put(url, headers=_headers(api_key, tok, json_body=True),
                                           json=merged, timeout=30) as resp:
            result["put_status"] = resp.status
            result["put_raw"] = (await resp.text())[:2000]
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            result["after_status"] = resp.status
            result["after_raw"] = (await resp.text())[:2000]
        _LOGGER.info("Yale set_delivery_box_mode result: %s", result)
        hass.bus.async_fire("yale_home_set_delivery_box_mode", result)

    async def _test_signin(call):
        """Diagnostic: call the raw signin endpoint directly (bypassing the
        cached/working token) and report exactly what Yale says, so you can
        tell a bad API key apart from a bad password from the error text."""
        stored = hass.data.get("yale_home", {}).get(entry.entry_id, {})
        auth = stored.get("auth")
        data = stored.get("data", {})
        email, password = data.get(CONF_EMAIL), data.get(CONF_PASSWORD)
        if not (auth and email and password):
            hass.bus.async_fire("yale_home_test_signin", {
                "error": "No stored auth/email/password found for this entry."})
            return
        result = {"api_key_used": f"{auth._api_key[:8]}...{auth._api_key[-4:]}"
                                  if len(auth._api_key) > 12 else "<short>",
                  "install_id": auth.install_id}
        try:
            signin = await auth.signin(email, password)
            result["need_verify"] = signin.need_verify
            result["verify_types"] = signin.verify_types
            result["require_recaptcha"] = signin.require_recaptcha
            result["got_access_token_directly"] = bool(signin.access_token)
            result["outcome"] = "SUCCESS - credentials and API key both accepted"
        except Exception as err:  # noqa: BLE001
            status = getattr(err, "status", None)
            body = getattr(err, "body", str(err))
            result["error_status"] = status
            result["error_body"] = str(body)[:500]
            if status == 401:
                result["outcome"] = "401 - likely wrong password OR revoked/rotated API key"
            elif status == 403:
                result["outcome"] = "403 - API key rejected (wrong/invalid key)"
            elif status == 429:
                result["outcome"] = "429 - rate limited, try again later"
            else:
                result["outcome"] = f"Unexpected status {status} - see error_body"
        _LOGGER.info("Yale test_signin result: %s", result)
        hass.bus.async_fire("yale_home_test_signin", result)

    hass.services.async_register("yale_home", "test_signin", _test_signin)
    async def _dump_pubnub_fields(call):
        """Diagnostic: GET /locks/{id} and fire every field whose name
        mentions channel/pubsub/pubnub. Yale's app model (Lock.getChannel())
        reads entity.pubsubChannel/pubsubProtocol/pubsubURL directly from
        this response - confirming whether (and what) real-time channel
        info is actually present for this lock."""
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_LOCK_INFO.format(lock_id=lock_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            status = resp.status
            try:
                data = await resp.json()
            except Exception:  # noqa: BLE001
                data = {}
        matches = {k: v for k, v in (data or {}).items()
                  if isinstance(k, str) and any(s in k.lower() for s in ("pubsub", "pubnub", "channel"))}
        result = {"status": status, "matches": matches, "all_keys": sorted(data) if isinstance(data, dict) else []}
        _LOGGER.info("Yale pubnub-field dump: %s", result)
        hass.bus.async_fire("yale_home_pubnub_fields", result)

    async def _dump_credentials(call):
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_CREDENTIALS.format(lock_id=lock_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            status, text = resp.status, await resp.text()
        _LOGGER.info("Yale credentials dump (%s): %s", status, text[:1000])
        hass.bus.async_fire("yale_home_credentials", {"status": status, "raw": text[:4000]})

    async def _subscribe_pubnub(call):
        """Diagnostic: open a short-lived PubNub subscription and fire an
        event for every message received. Takes pub_key/sub_key/channel from
        the service call - never hardcoded here, since these are Yale's own
        app-wide PubNub credentials (cracked from the APK, not meant to be
        committed to a public repo any more than the API key was)."""
        from pubnub.pnconfiguration import PNConfiguration
        from pubnub.pubnub_asyncio import PubNubAsyncio
        from pubnub.callbacks import SubscribeCallback

        pub_key = call.data["pub_key"]
        sub_key = call.data["sub_key"]
        channel = call.data["channel"]
        duration = call.data.get("duration", 30)

        pnconfig = PNConfiguration()
        pnconfig.publish_key = pub_key
        pnconfig.subscribe_key = sub_key
        pnconfig.uuid = f"yale_home_diag_{secrets.token_hex(4)}"
        pubnub_client = PubNubAsyncio(pnconfig)

        class _Listener(SubscribeCallback):
            def message(self, pubnub_instance, message):
                _LOGGER.info("Yale PubNub message on %s: %s", channel, message.message)
                hass.bus.async_fire("yale_home_pubnub_message", {
                    "channel": channel, "message": message.message})

            def status(self, pubnub_instance, status):
                pass

        listener = _Listener()
        pubnub_client.add_listener(listener)
        pubnub_client.subscribe().channels(channel).execute()
        hass.bus.async_fire("yale_home_pubnub_subscribed", {"channel": channel, "duration": duration})
        try:
            await asyncio.sleep(duration)
        finally:
            pubnub_client.unsubscribe().channels(channel).execute()
            await pubnub_client.stop()
            hass.bus.async_fire("yale_home_pubnub_unsubscribed", {"channel": channel})

    async def _dump_guest_credential(call):
        """Diagnostic: GET /locks/{id}/users/{otherUserID}/credential (singular -
        the read-single-credential endpoint, verified from the decompiled
        Retrofit interface, distinct from the plural one used elsewhere)."""
        other_user_id = call.data["other_user_id"]
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_GUEST_CREDENTIAL_READ.format(lock_id=lock_id, other_user_id=other_user_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            status, text = resp.status, await resp.text()
        _LOGGER.info("Yale guest credential dump (%s): %s", status, text[:1000])
        hass.bus.async_fire("yale_home_guest_credential", {"status": status, "raw": text[:4000]})

    async def _dump_managed_devices(call):
        """Diagnostic: GET /houses/{houseId}/manageduser/{userId} - 403'd on
        the weaker HA-Cloud-borrowed token in earlier testing; retest with
        the owner token this integration logs in with. user_id defaults to
        'me' if not supplied - adjust if Yale expects a real user ID."""
        user_id = call.data.get("user_id", "me")
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_MANAGED_DEVICES.format(house_id=coordinator.house_id, user_id=user_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            status, text = resp.status, await resp.text()
        _LOGGER.info("Yale managed devices dump (%s): %s", status, text[:1000])
        hass.bus.async_fire("yale_home_managed_devices", {"status": status, "raw": text[:4000]})

    async def _dump_keypad_info(call):
        """Diagnostic: GET /keypads/{keypadId}."""
        keypad_id = call.data["keypad_id"]
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_KEYPAD_INFO.format(keypad_id=keypad_id)}"
        async with coordinator.session.get(url, headers=_headers(api_key, tok), timeout=30) as resp:
            status, text = resp.status, await resp.text()
        _LOGGER.info("Yale keypad info (%s): %s", status, text[:1000])
        hass.bus.async_fire("yale_home_keypad_info", {"status": status, "raw": text[:4000]})

    async def _create_schedule_rule(call):
        """EXPERIMENTAL: POST rules/rulewithuser/{lockID}/{userID}. The real
        Rule model uses Joda DateTime + a biweekly RecurrenceRule with
        custom Gson adapters we haven't observed serializing live, so this
        body shape is a best-effort guess from decompiled property names -
        NOT confirmed working. Pass raw_body to override entirely if this
        guess is wrong; fires the real error either way so you can correct
        it from evidence rather than more guessing."""
        other_user_id = call.data["other_user_id"]
        tok = await _get_tok()
        url = f"{API_BASE_URL}{ENDPOINT_CREATE_SCHEDULE_RULE.format(lock_id=lock_id, user_id=other_user_id)}"
        if "raw_body" in call.data:
            body = call.data["raw_body"]
        else:
            start = call.data["start_time"]
            end = call.data["end_time"]
            days = call.data.get("recurrence_days")  # e.g. [0,1,2,3,4] Mon-Fri
            body = {
                "type": "recurring" if days else "one_time",
                "startDateTime": start,
                "endDateTime": end,
                "credentialAccessType": call.data.get("access_type", "always"),
            }
            if days:
                body["recurrenceDays"] = days
        async with coordinator.session.post(url, headers=_headers(api_key, tok, json_body=True),
                                            json=body, timeout=30) as resp:
            status, text = resp.status, await resp.text()
        _LOGGER.info("Yale create_schedule_rule (%s): %s", status, text[:1000])
        hass.bus.async_fire("yale_home_create_schedule_rule", {
            "status": status, "raw": text[:4000], "sent_body": body})

    hass.services.async_register("yale_home", "dump_keypad_info", _dump_keypad_info)
    hass.services.async_register("yale_home", "create_schedule_rule", _create_schedule_rule)
    hass.services.async_register("yale_home", "dump_guest_credential", _dump_guest_credential)
    hass.services.async_register("yale_home", "dump_managed_devices", _dump_managed_devices)
    hass.services.async_register("yale_home", "dump_credentials", _dump_credentials)
    hass.services.async_register("yale_home", "subscribe_pubnub", _subscribe_pubnub)
    hass.services.async_register("yale_home", "dump_pubnub_fields", _dump_pubnub_fields)
    hass.services.async_register("yale_home", "dump_unity_settings", _dump_unity_settings)
    hass.services.async_register("yale_home", "set_delivery_box_mode", _set_delivery_box_mode)
    hass.services.async_register("yale_home", "enable_delivery_mode", _enable)
    hass.services.async_register("yale_home", "disable_delivery_mode", _disable)
    hass.services.async_register("yale_home", "create_temp_pin", _create_temp)
    hass.services.async_register("yale_home", "rotate_pin", _rotate)
    hass.services.async_register("yale_home", "delete_pin", _delete)
    hass.services.async_register("yale_home", "create_named_guest", _create_named_guest)
    hass.services.async_register("yale_home", "list_guests", _list_guests)
    hass.services.async_register("yale_home", "remove_guest", _remove_guest)