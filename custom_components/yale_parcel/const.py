"""Constants for Yale Parcel Box integration."""

from types import SimpleNamespace

DOMAIN = "yale_parcel"

# Yale Global backend (public brand constant from the yalexs library).
API_BASE_URL = "https://api.aaecosystem.com"
API_KEY = "d16a1029-d823-4b55-a4ce-a769a9b56f0e"
HEADER_API_KEY = "x-api-key"
HEADER_ACCESS_TOKEN = "x-access-token"

ENDPOINT_PINS = "/locks/{lock_id}/pins"
ENDPOINT_LOCK_OPERATE = "/remoteoperate/{lock_id}/{action}"
ENDPOINT_ACTIVITIES = "/houses/{house_id}/activities"
ENDPOINT_GUESTLIST = "/houses/{house_id}/guestlist"

SCAN_INTERVAL = 60

CONF_HOUSE_ID = "house_id"
CONF_LOCK_ID = "lock_id"
CONF_LOCK_NAME = "lock_name"
CONF_DELIVERY_PIN = "delivery_pin"
CONF_DELIVERY_PIN_USER_ID = "delivery_pin_user_id"

# How the lock is used. Behaviour is identical either way (the same PIN
# services cover a courier delivery and an Airbnb guest stay); only the
# human-facing language differs. See device_labels().
CONF_DEVICE_TYPE = "device_type"
DEVICE_TYPE_PARCEL = "parcel_box"
DEVICE_TYPE_DOOR = "door"


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

EVENT_ACTIVITY = "yale_parcel_activity"

ACTION_LOAD = "load"
ACTION_ENABLE = "enable"
ACTION_DISABLE = "disable"
ACTION_DELETE = "delete"
