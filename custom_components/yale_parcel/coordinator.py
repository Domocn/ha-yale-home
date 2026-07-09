"""Data coordinator — activities, PIN codes, and guest names.

Guest/credential management endpoints (guestlist, manageduser, credentials) are
403 for the borrowed OAuth token — Yale restricts those to the app's own login.
So code owner names come from the activity log (a courier is named the first
time its code is used, then remembered), and codes are managed via
/locks/{id}/pins (not blocked). PINs are fetched raw because yalexs' Pin parser
requires a `firstName` these codes don't have (KeyError otherwise).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE_URL, API_KEY, HEADER_ACCESS_TOKEN, HEADER_API_KEY, DOMAIN, SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


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

    def _headers(self) -> dict[str, str]:
        return {HEADER_API_KEY: API_KEY, HEADER_ACCESS_TOKEN: self.token}

    async def _get(self, path: str) -> Any:
        async with self.session.get(f"{API_BASE_URL}{path}", headers=self._headers()) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            activities = await self._get(f"/houses/{self.house_id}/activities?limit=15")
            pins_raw = await self._get(f"/locks/{self.lock_id}/pins")
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Yale poll failed: {err}") from err

        for activity in activities or []:
            for key in ("callingUser", "otherUser"):
                user = activity.get(key)
                if isinstance(user, dict):
                    uid = user.get("UserID") or user.get("userID")
                    if uid and _name(user):
                        self._names[uid] = _name(user)

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
