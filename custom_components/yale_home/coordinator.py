"""Data coordinator — lock state, activities, PIN codes, guests, and learned names.

Guest/credential *management* endpoints are owner-scope (the app-login token
unlocks them). Code owner names are still learned from the activity log the
first time a code is used and cached, so names persist across restarts.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .auth import expiry_iso
from .const import (
    API_BASE_URL, BRAND_VALUE, HEADER_ACCESS_TOKEN, HEADER_API_KEY,
    HEADER_BRANDING, USER_AGENT,
    CONF_EMAIL, CONF_HOUSE_ID, CONF_LOCK_ID, CONF_PASSWORD,
    ENDPOINT_ACTIVITIES, ENDPOINT_GUESTLIST, ENDPOINT_LOCK_INFO, ENDPOINT_PINS,
    SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_ACTIVITY_LIMITS = [100, 50, 25, 15]


def _name(user: dict[str, Any]) -> str:
    first = user.get("FirstName") or user.get("firstName") or ""
    last = user.get("LastName") or user.get("lastName") or ""
    return f"{first} {last}".strip()


def _guest_names(guests: Any) -> dict[str, str]:
    """userID -> full name from a /guestlist response.

    The owner-scope guest list is the one source that names EVERY code up front,
    including ones a courier has never used. Yale returns it either as a map
    keyed by userID (HouseGuestList) or, on some tenants, a flat list — handle
    both, and tolerate a `{guestList: {...}}` / `{users: [...]}` wrapper.
    """
    if isinstance(guests, dict):
        for wrapper in ("guestList", "guests", "users", "loaded"):
            if isinstance(guests.get(wrapper), (dict, list)):
                guests = guests[wrapper]
                break
    out: dict[str, str] = {}
    if isinstance(guests, dict):
        for uid, info in guests.items():
            if isinstance(info, dict) and uid and _name(info):
                out[str(uid)] = _name(info)
    elif isinstance(guests, list):
        for info in guests:
            if isinstance(info, dict):
                uid = info.get("UserID") or info.get("userID") or info.get("userId")
                if uid and _name(info):
                    out[str(uid)] = _name(info)
    return out


def _parse_yale_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if f > 1e12:
            f /= 1000.0
        return dt_util.utc_from_timestamp(f)
    s = str(value)
    parsed = dt_util.parse_datetime(s)
    if parsed is None:
        try:
            return _parse_yale_time(float(s))
        except (ValueError, TypeError):
            return None
    return parsed


def _pin_schedule(d: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    vf = _parse_yale_time(d.get("accessStartTime"))
    ex = _parse_yale_time(d.get("accessEndTime"))
    at = d.get("accessTimes")
    if isinstance(at, str) and (vf is None or ex is None):
        m_start = re.search(r"DTSTART=([^;]+)", at)
        m_end = re.search(r"DTEND=([^;\s]+)", at)
        if m_start and vf is None:
            vf = _parse_yale_time(m_start.group(1))
        if m_end and ex is None:
            ex = _parse_yale_time(m_end.group(1))
    return vf, ex


def _humanize(td: timedelta) -> str:
    mins = int(td.total_seconds() // 60)
    if mins < 1:
        return "less than a min"
    if mins < 60:
        return f"{mins} min"
    hours = mins // 60
    if hours < 24:
        rem = mins % 60
        return f"{hours} h" + (f" {rem} min" if rem else "")
    days = hours // 24
    return f"{days} day" + ("s" if days != 1 else "")


def format_expiry(expires_at: datetime | None, now: datetime | None = None) -> str:
    if expires_at is None:
        return "Permanent — no expiry"
    if now is None:
        now = dt_util.now()
    delta = expires_at - now
    if delta.total_seconds() <= 0:
        return f"Expired {_humanize(now - expires_at)} ago"
    local = dt_util.as_local(expires_at)
    return f"Expires {local:%a %d %b %H:%M} (in {_humanize(delta)})"


class YaleHomeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls lock state, activities, PINs and guests for one lock/house."""

    def __init__(self, hass: HomeAssistant, session, auth,
                 email: str, password: str, house_id: str, lock_id: str,
                 api_key: str) -> None:
        super().__init__(hass, _LOGGER, name="yale_home",
                         update_interval=timedelta(seconds=SCAN_INTERVAL))
        self.session = session
        self.auth = auth
        self._api_key = api_key
        self._email = email
        self._password = password
        self._data = {CONF_EMAIL: email, CONF_PASSWORD: password,
                      CONF_HOUSE_ID: house_id, CONF_LOCK_ID: lock_id}
        self.house_id = house_id
        self.lock_id = lock_id
        self._names: dict[str, str] = {}
        self._store = Store(hass, 1, f"yale_home_names_{lock_id}")
        self._loaded = False
        self._act_limit = 0
        self._token: str | None = None
        self._token_expiry: datetime | None = None
        self.last_pin_error: str | None = None
        self.last_pin_ok: str | None = None
        self.last_pin_at: datetime | None = None

    @property
    def api_key(self) -> str:
        """The per-user API key (extracted from the user's own APK at setup)."""
        return self._api_key

    # --- token -------------------------------------------------------------
    async def get_token(self) -> str:
        """Return a valid owner token, refreshing first if near expiry."""
        token, expiry = await self.auth.ensure_valid(
            self._email, self._password, self._token, self._token_expiry)
        self._token, self._token_expiry = token, expiry
        return token

    def record_pin(self, ok: str | None, error: str | None) -> None:
        self.last_pin_ok = ok
        self.last_pin_error = error
        self.last_pin_at = dt_util.now()

    # --- HTTP --------------------------------------------------------------
    def _headers(self, token: str) -> dict[str, str]:
        return {HEADER_API_KEY: self._api_key, HEADER_BRANDING: BRAND_VALUE,
                HEADER_ACCESS_TOKEN: token, "User-Agent": USER_AGENT}

    async def _get(self, path: str, *, retry_on_401: bool = True) -> Any:
        token = await self.get_token()
        url = f"{API_BASE_URL}{path}"
        async with self.session.get(url, headers=self._headers(token), timeout=30) as resp:
            if resp.status == 401 and retry_on_401:
                # Token expired mid-session — force a refresh and retry once.
                self._token = None
                return await self._get(path, retry_on_401=False)
            if resp.status >= 400:
                raise UpdateFailed(f"Yale GET {path} failed ({resp.status})")
            return await resp.json()

    async def _load_names(self) -> None:
        if self._loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._names.update({k: v for k, v in stored.items() if v})
        self._loaded = True

    async def _get_activities(self) -> Any:
        tries = [self._act_limit] if self._act_limit else _ACTIVITY_LIMITS
        last_err: Exception | None = None
        for lim in tries:
            try:
                data = await self._get(f"{ENDPOINT_ACTIVITIES.format(house_id=self.house_id)}?limit={lim}")
                self._act_limit = lim
                return data
            except Exception as err:  # noqa: BLE001
                last_err = err
                self._act_limit = 0
        raise last_err  # type: ignore[misc]

    async def _async_update_data(self) -> dict[str, Any]:
        await self._load_names()
        try:
            lock = await self._get(ENDPOINT_LOCK_INFO.format(lock_id=self.lock_id))
            activities = await self._get_activities()
            pins_raw = await self._get(ENDPOINT_PINS.format(lock_id=self.lock_id))
            try:
                guests = await self._get(
                    ENDPOINT_GUESTLIST.format(house_id=self.house_id) + "?mergeDuplicates=true")
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Guest list unavailable: %s", err)
                guests = None
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Yale poll failed: {err}") from err

        learned = False
        # Guest list (owner-scope) names EVERY code up front — even ones a
        # courier has never used — so codes stop showing as a generic "Code".
        for uid, nm in _guest_names(guests).items():
            if self._names.get(uid) != nm:
                self._names[uid] = nm
                learned = True
        # Activity log fills in / corrects a name the first time a code is used.
        for activity in activities or []:
            for key in ("callingUser", "otherUser"):
                user = activity.get(key)
                if isinstance(user, dict):
                    uid = user.get("UserID") or user.get("userID")
                    nm = _name(user)
                    if uid and nm and self._names.get(uid) != nm:
                        self._names[uid] = nm
                        learned = True
        if learned:
            await self._store.async_save(self._names)

        items = pins_raw if isinstance(pins_raw, list) else (
            pins_raw.get("pins") or pins_raw.get("loaded") or [])
        pins = []
        for d in items:
            if not isinstance(d, dict):
                continue
            uid = d.get("userID") or d.get("UserID")
            valid_from, expires_at = _pin_schedule(d)
            pins.append(SimpleNamespace(
                pin=str(d.get("pin", "")), state=d.get("state"), user_id=uid,
                access_type=d.get("accessType"), slot=d.get("slot"),
                owner=self._names.get(uid, ""), raw=d,
                valid_from=valid_from, expires_at=expires_at,
                access_times=d.get("accessTimes"),
                is_temporary=bool(d.get("accessType") == "temporary" or expires_at),
            ))

        return {
            "lock": lock,
            "activities": activities,
            "pins": pins,
            "users": dict(self._names),
            "guests": guests,
            "last_activity": activities[0] if activities else None,
        }