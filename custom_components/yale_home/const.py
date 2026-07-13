"""Constants for the Yale Home integration."""
from __future__ import annotations

from types import SimpleNamespace

DOMAIN = "yale_home"

# Yale Global backend (public brand). The API key the integration uses is NOT
# shipped in this repo — each user supplies their own Yale Home APK at setup,
# and the integration extracts the app key from its native library (see
# apk_extract.py). This keeps Yale's key out of the public code.
API_BASE_URL = "https://api.aaecosystem.com"
HEADER_API_KEY = "x-api-key"
HEADER_ACCESS_TOKEN = "x-access-token"
HEADER_STEP_TOKEN = "x-step-token"
HEADER_BRANDING = "x-branding"
BRAND_VALUE = "yale"
USER_AGENT = "YaleHome/2026.7.0 Android"
SMS_HASH = "ND83fRplcC3"

# Auth flow endpoints.
ENDPOINT_SIGNIN = "/v2/session/signin"
ENDPOINT_VALIDATE_EMAIL = "/v2/validate/email"

# Lock / house endpoints.
ENDPOINT_LOCK_INFO = "/locks/{lock_id}"
ENDPOINT_PINS = "/locks/{lock_id}/pins"
ENDPOINT_LOCK_OPERATE = "/remoteoperate/{lock_id}/{action}"
ENDPOINT_ACTIVITIES = "/houses/{house_id}/activities"
ENDPOINT_GUESTLIST = "/houses/{house_id}/guestlist"
ENDPOINT_CREDENTIALS = "/locks/{lock_id}/credentials"
ENDPOINT_GUEST_CREDENTIAL = "/locks/{lock_id}/users/{other_user_id}/credentials"
ENDPOINT_ADD_USER = "/locks/adduser/{lock_id}/{other_user_id}/{type}"
ENDPOINT_REMOVE_USER = "/locks/{lock_id}/users/{other_user_id}"

SCAN_INTERVAL = 60

# Config entry fields.
CONF_HOUSE_ID = "house_id"
CONF_LOCK_ID = "lock_id"
CONF_LOCK_NAME = "lock_name"
CONF_DELIVERY_PIN = "delivery_pin"
CONF_DELIVERY_PIN_USER_ID = "delivery_pin_user_id"
CONF_DEVICE_TYPE = "device_type"
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_INSTALL_ID = "install_id"
CONF_ACCESS_TOKEN = "access_token"
CONF_TOKEN_EXPIRY = "token_expiry"
CONF_API_KEY = "api_key"

DEVICE_TYPE_PARCEL = "parcel_box"
DEVICE_TYPE_DOOR = "door"

EVENT_ACTIVITY = "yale_home_activity"

# PIN command actions (POST /locks/{id}/pins).
ACTION_LOAD = "load"
ACTION_ENABLE = "enable"
ACTION_DISABLE = "disable"
ACTION_DELETE = "delete"
# Lock remote operate actions (PUT /remoteoperate/{id}/{action}).
ACTION_LOCK = "lock"
ACTION_UNLOCK = "unlock"
ACTION_UNLATCH = "unlatch"
ACTION_STATUS = "status"


def device_labels(device_type: str | None) -> SimpleNamespace:
    """Words that vary by how the lock is used.

    A Yale/August lock can be a parcel box (couriers drop deliveries) or a
    regular door (Airbnb / home guest access). Returns a SimpleNamespace with
    .noun (the thing), .code (the always-on PIN), .access (the enable/disable
    concept) and .actor (who uses the code).
    """
    if device_type == DEVICE_TYPE_DOOR:
        return SimpleNamespace(
            noun="Door Lock",
            code="guest PIN",
            access="guest access",
            actor="guest",
        )
    return SimpleNamespace(
        noun="Parcel Box",
        code="delivery PIN",
        access="delivery mode",
        actor="courier",
    )