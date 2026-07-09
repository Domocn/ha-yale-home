"""Yale API client for Parcel Box integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from .const import (
    API_BASE_URL,
    API_KEY,
    HEADER_API_KEY,
    HEADER_ACCESS_TOKEN,
    ENDPOINT_HOUSES,
    ENDPOINT_LOCKS,
    ENDPOINT_ACTIVITIES,
    ENDPOINT_PINS,
    ENDPOINT_LOCK_OPERATE,
    ENDPOINT_USER,
    LOCK_ACTION_LOCK,
    LOCK_ACTION_UNLOCK,
    PIN_ACTION_ENABLE,
    PIN_ACTION_DISABLE,
    PIN_ACTION_LOAD,
    PIN_ACTION_DELETE,
)

_LOGGER = logging.getLogger(__name__)


class YaleApiClient:
    """API client for Yale/August aaecosystem.com."""

    def __init__(self, session, access_token: str):
        """Initialize the client."""
        self._session = session
        self._access_token = access_token
        self._headers = {
            HEADER_API_KEY: API_KEY,
            HEADER_ACCESS_TOKEN: access_token,
        }

    @property
    def access_token(self) -> str:
        """Return current access token."""
        return self._access_token

    def _update_token_from_response(self, resp) -> None:
        """Extract refreshed token from response headers."""
        new_token = resp.headers.get(HEADER_ACCESS_TOKEN)
        if new_token:
            self._access_token = new_token
            self._headers[HEADER_ACCESS_TOKEN] = new_token

    async def async_get_houses(self) -> list[dict]:
        """Get list of houses."""
        resp = await self._session.get(
            f"{API_BASE_URL}{ENDPOINT_HOUSES}",
            headers=self._headers,
        )
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_get_locks(self) -> dict:
        """Get list of locks."""
        resp = await self._session.get(
            f"{API_BASE_URL}{ENDPOINT_LOCKS}",
            headers=self._headers,
        )
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_get_user(self) -> dict:
        """Get current user info."""
        resp = await self._session.get(
            f"{API_BASE_URL}{ENDPOINT_USER}",
            headers=self._headers,
        )
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_get_activities(self, house_id: str, limit: int = 5) -> list[dict]:
        """Get house activity log."""
        url = f"{API_BASE_URL}{ENDPOINT_ACTIVITIES.format(house_id=house_id)}?limit={limit}"
        resp = await self._session.get(url, headers=self._headers)
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_get_pins(self, lock_id: str) -> dict:
        """Get PINs for a lock."""
        resp = await self._session.get(
            f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
            headers=self._headers,
        )
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_operate_lock(self, lock_id: str, action: str) -> dict:
        """Lock or unlock."""
        url = f"{API_BASE_URL}{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action=action)}"
        resp = await self._session.put(url, headers=self._headers)
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_lock(self, lock_id: str) -> dict:
        """Lock the lock."""
        return await self.async_operate_lock(lock_id, LOCK_ACTION_LOCK)

    async def async_unlock(self, lock_id: str) -> dict:
        """Unlock the lock."""
        return await self.async_operate_lock(lock_id, LOCK_ACTION_UNLOCK)

    async def async_wake_lock(self, lock_id: str) -> None:
        """Wake the lock for PIN operations."""
        url = f"{API_BASE_URL}{ENDPOINT_LOCK_OPERATE.format(lock_id=lock_id, action='status')}?v=2.3.1&type=async&intent=wakeup"
        resp = await self._session.put(url, headers=self._headers)
        self._update_token_from_response(resp)

    async def async_manage_pin(
        self,
        lock_id: str,
        action: str,
        pin: str,
        access_type: str = "always",
        user_id: str | None = None,
        access_times: str | None = None,
    ) -> dict:
        """Manage a PIN (enable, disable, load, delete)."""
        command = {
            "action": action,
            "pin": pin,
            "accessType": access_type,
        }
        if user_id:
            command["userID"] = user_id
        if access_times:
            command["accessTimes"] = access_times

        payload = {"commands": [command]}
        resp = await self._session.post(
            f"{API_BASE_URL}{ENDPOINT_PINS.format(lock_id=lock_id)}",
            headers={**self._headers, "Content-Type": "application/json"},
            json=payload,
        )
        self._update_token_from_response(resp)
        resp.raise_for_status()
        return await resp.json()

    async def async_enable_delivery_pin(
        self, lock_id: str, pin: str, user_id: str
    ) -> dict:
        """Enable the delivery PIN."""
        return await self.async_manage_pin(
            lock_id, PIN_ACTION_ENABLE, pin, "always", user_id
        )

    async def async_disable_delivery_pin(
        self, lock_id: str, pin: str, user_id: str
    ) -> dict:
        """Disable the delivery PIN."""
        return await self.async_manage_pin(
            lock_id, PIN_ACTION_DISABLE, pin, "always", user_id
        )

    async def async_create_temporary_pin(
        self,
        lock_id: str,
        pin: str,
        user_id: str,
        start_time: str,
        end_time: str,
    ) -> dict:
        """Create a temporary PIN."""
        access_times = f"DTSTART={start_time};DTEND={end_time}"
        return await self.async_manage_pin(
            lock_id,
            PIN_ACTION_LOAD,
            pin,
            "temporary",
            user_id,
            access_times,
        )
