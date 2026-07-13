"""Yale Home app-login authentication.

Replicates the official Yale Home app's login so this integration obtains an
owner-scope `x-access-token` (the same token the app uses), enabling named-guest
management and lock control — for any user, with just an email + password + one
emailed verification code.

Flow (all on https://api.aaecosystem.com):
  1. POST /v2/session/signin  {identifierType:"email", identifier, credential,
     installID, smsHashString}  -> {needVerify,...} + x-step-token header.
     Yale auto-emails a 6-digit code to the user's email (no captcha).
  2. POST /v2/validate/email   {code, identifier}  + x-step-token header
     -> HTTP 200 (marks this installID a trusted device).
  3. POST /v2/session/signin   (again, SAME installID + creds)
     -> needVerify:false + x-access-token header  (owner JWT).
  Refresh = repeat step 3 with the stored installID + creds (no code needed).
"""
from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from homeassistant.exceptions import HomeAssistantError

from .const import (
    API_BASE_URL, BRAND_VALUE, HEADER_ACCESS_TOKEN, HEADER_API_KEY,
    HEADER_BRANDING, HEADER_STEP_TOKEN, SMS_HASH, USER_AGENT,
    ENDPOINT_SIGNIN, ENDPOINT_VALIDATE_EMAIL,
)

_LOGGER = logging.getLogger(__name__)

# Refresh a little before the token actually expires.
_TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
# Fallback expiry if the JWT can't be decoded.
_TOKEN_DEFAULT_LIFETIME = timedelta(hours=24)


class YaleAuthError(HomeAssistantError):
    """Raised when a Yale auth call fails (carries status + body for the UI)."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Yale auth failed ({status}): {body[:200]}")


class YaleAppAuth:
    """Yale Home app-login client — signin / verify / token / refresh."""

    def __init__(self, session, api_key: str, install_id: str | None = None) -> None:
        self._session = session
        self._api_key = api_key
        self.install_id = install_id or str(uuid.uuid4())

    # --- low-level request -------------------------------------------------
    def _base_headers(self) -> dict[str, str]:
        return {
            HEADER_API_KEY: self._api_key,
            HEADER_BRANDING: BRAND_VALUE,
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

    async def _post(self, path: str, body: dict[str, Any],
                    *, step_token: str | None = None) -> tuple[int, dict, dict[str, str]]:
        headers = self._base_headers()
        if step_token:
            headers[HEADER_STEP_TOKEN] = step_token
        url = f"{API_BASE_URL}{path}"
        async with self._session.post(url, json=body, headers=headers, timeout=30) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise YaleAuthError(resp.status, text)
            try:
                data = await resp.json()
            except Exception:  # noqa: BLE001
                data = {}
            return resp.status, data, dict(resp.headers)

    # --- public API --------------------------------------------------------
    async def signin(self, email: str, password: str) -> SimpleNamespace:
        """Step 1/3: sign in. Returns (need_verify, verify_types, step_token).
        Yale emails a 6-digit code when need_verify is true."""
        body = {
            "identifierType": "email",
            "identifier": email,
            "credential": password,
            "installID": self.install_id,
            "smsHashString": SMS_HASH,
        }
        _, data, headers = await self._post(ENDPOINT_SIGNIN, body)
        verify_types = [v.get("type") for v in (data.get("verifyTypes") or [])]
        return SimpleNamespace(
            need_verify=bool(data.get("needVerify")),
            verify_types=verify_types,
            require_recaptcha=bool(data.get("requireReCaptcha")),
            step_token=headers.get(HEADER_STEP_TOKEN, ""),
        )

    async def verify_email(self, step_token: str, email: str, code: str) -> bool:
        """Step 2/3: submit the emailed code. Marks this installID trusted."""
        await self._post(ENDPOINT_VALIDATE_EMAIL, {"code": code, "identifier": email},
                         step_token=step_token)
        return True

    async def get_owner_token(self, email: str, password: str) -> tuple[str, datetime]:
        """Step 3/3 (and the refresh path): re-sign in with the now-trusted
        installID, returning (access_token, expiry)."""
        body = {
            "identifierType": "email",
            "identifier": email,
            "credential": password,
            "installID": self.install_id,
            "smsHashString": SMS_HASH,
        }
        _, data, headers = await self._post(ENDPOINT_SIGNIN, body)
        token = headers.get(HEADER_ACCESS_TOKEN, "")
        if not token:
            # If the device still needs verification, the token is withheld.
            raise YaleAuthError(401, "no access token — device not verified or wrong credentials")
        return token, _token_expiry(token)

    async def refresh(self, email: str, password: str) -> tuple[str, datetime]:
        """Refresh = re-signin with the stored, already-trusted installID."""
        return await self.get_owner_token(email, password)

    async def ensure_valid(self, email: str, password: str,
                           token: str | None, expiry: datetime | None) -> tuple[str, datetime]:
        """Return a valid (token, expiry), refreshing first if near expiry."""
        now = datetime.now(timezone.utc)
        if token and expiry and expiry - now > _TOKEN_REFRESH_MARGIN:
            return token, expiry
        return await self.refresh(email, password)


def _token_expiry(token: str) -> datetime:
    """Decode the JWT `exp` claim; fall back to now+24h."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)  # base64url pad
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = int(claims.get("exp", 0))
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Could not decode token expiry: %s", err)
    return datetime.now(timezone.utc) + _TOKEN_DEFAULT_LIFETIME


def parse_expiry_iso(value: str | None) -> datetime | None:
    """Parse a stored token-expiry ISO string back to a datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def expiry_iso(dt: datetime | None) -> str | None:
    """Serialize a token expiry for storage."""
    return dt.isoformat() if dt else None