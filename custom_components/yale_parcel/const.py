"""Constants for Yale Parcel Box integration."""

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

EVENT_ACTIVITY = "yale_parcel_activity"

ACTION_LOAD = "load"
ACTION_ENABLE = "enable"
ACTION_DISABLE = "disable"
ACTION_DELETE = "delete"
