"""Data coordinator — activities, PIN codes, and guest names.

Guest/credential management endpoints (guestlist, manageduser, credentials) are
403 for the borrowed OAuth token — Yale restricts those to the app's own login.
So code owner names come from the activity log (a courier is named the first
time its code is used) and are then **persisted** so they stick across restarts.
PINs are fetched raw because yalexs' Pin parser requires a `firstName` these
codes don't have (KeyError otherwise).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE_URL, API_KEY, HEADER_ACCESS_TOKEN, HEADER_API_KEY, DOMAIN, SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Activity page sizes to try, largest first. Yale caps the limit and 403s an
# over-large request, so we step down until one is accepted and remember it.
# A deeper page names more couriers (each is named only when their code is used).
_ACTIVITY_LIMITS = [100, 50, 25, 15]


def _name(user: dict[str, Any]) -> str:
    first = user.get("FirstName") or user.get("firstName") or ""
    last = user.get("LastName") or user.get("lastName") or ""
    return f"{first} {last}".strip()


class YaleParcelCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls activity + PINs for one lock/house."""

    def __init__(self, hass: HomeAssistant, session, token: str, house_id: str, lock_id: str) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=SCAN_INTERVAL))
        self.session = session
        self.token = token
        self.house_id = house_id
        self.lock_id = lock_id
        self._names: dict[str, str] = {}
        self._store: Store = Store(hass, 1, f"{DOMAIN}_names_{lock_id}")
        self._loaded = False
        self._act_limit = 0  # 0 = probe; otherwise the last accepted page size

    def _headers(self) -> dict[str, str]:
        return {HEADER_API_KEY: API_KEY, HEADER_ACCESS_TOKEN: self.token}

    async def _get(self, path: str) -> Any:
        async with self.session.get(f"{API_BASE_URL}{path}", headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _load_names(self) -> None:
        if self._loaded:
            return
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._names.update({k: v for k, v in stored.items() if v})
        self._loaded = True

    async def _get_activities(self) -> Any:
        """Fetch the deepest activity page the API will accept (remembering it)."""
        tries = [self._act_limit] if self._act_limit else _ACTIVITY_LIMITS
        last_err: Exception | None = None
        for lim in tries:
            try:
                data = await self._get(f"/houses/{self.house_id}/activities?limit={lim}")
                self._act_limit = lim
                return data
            except Exception as err:  # noqa: BLE001 — step down to a smaller page
                last_err = err
                self._act_limit = 0
        raise last_err  # type: ignore[misc]

    async def _async_update_data(self) -> dict[str, Any]:
        await self._load_names()
        try:
            activities = await self._get_activities()
            pins_raw = await self._get(f"/locks/{self.lock_id}/pins")
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Yale poll failed: {err}") from err

        learned = False
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
            pins_raw.get("pins") or pins_raw.get("loaded") or []
        )
        pins = []
        for d in items:
            if not isinstance(d, dict):
                continue
            uid = d.get("userID") or d.get("UserID")
            pins.append(SimpleNamespace(
                pin=str(d.get("pin", "")), state=d.get("state"), user_id=uid,
                access_type=d.get("accessType"), slot=d.get("slot"),
                owner=self._names.get(uid, ""), raw=d,
            ))

        return {
            "activities": activities,
            "pins": pins,
            "users": dict(self._names),
            "last_activity": activities[0] if activities else None,
        }
