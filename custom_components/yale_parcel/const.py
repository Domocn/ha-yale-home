"""Constants for Yale Parcel Box integration."""

DOMAIN = "yale_parcel"

# API Configuration
API_BASE_URL = "https://api.aaecosystem.com"
API_KEY = "d16a1029-d823-4b55-a4ce-a769a9b56f0e"

# Endpoints
ENDPOINT_HOUSES = "/users/houses/mine"
ENDPOINT_LOCKS = "/users/locks/mine"
ENDPOINT_ACTIVITIES = "/houses/{house_id}/activities"
ENDPOINT_PINS = "/locks/{lock_id}/pins"
ENDPOINT_LOCK_OPERATE = "/remoteoperate/{lock_id}/{action}"
ENDPOINT_USER = "/users/me"

# Headers
HEADER_API_KEY = "x-api-key"
HEADER_ACCESS_TOKEN = "x-access-token"

# Lock operations
LOCK_ACTION_LOCK = "lock"
LOCK_ACTION_UNLOCK = "unlock"

# PIN actions
PIN_ACTION_LOAD = "load"
PIN_ACTION_ENABLE = "enable"
PIN_ACTION_DISABLE = "disable"
PIN_ACTION_DELETE = "delete"

# Default scan interval
SCAN_INTERVAL = 60

# Config flow
CONF_ACCESS_TOKEN = "access_token"
CONF_HOUSE_ID = "house_id"
CONF_LOCK_ID = "lock_id"
CONF_LOCK_NAME = "lock_name"
CONF_DELIVERY_PIN = "delivery_pin"
CONF_DELIVERY_PIN_USER_ID = "delivery_pin_user_id"
