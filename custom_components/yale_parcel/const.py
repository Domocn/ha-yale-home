"""Constants for Yale Parcel Box integration."""

DOMAIN = "yale_parcel"

# API endpoints for PIN management (not yet in yalexs library)
API_BASE_URL = "https://api.aaecosystem.com"
API_KEY = "d16a1029-d823-4b55-a4ce-a769a9b56f0e"
HEADER_API_KEY = "x-api-key"
HEADER_ACCESS_TOKEN = "x-access-token"
ENDPOINT_PINS = "/locks/{lock_id}/pins"
ENDPOINT_LOCK_OPERATE = "/remoteoperate/{lock_id}/{action}"

# Polling interval
SCAN_INTERVAL = 60

# Config flow keys
CONF_HOUSE_ID = "house_id"
CONF_LOCK_ID = "lock_id"
CONF_LOCK_NAME = "lock_name"
CONF_DELIVERY_PIN = "delivery_pin"
CONF_DELIVERY_PIN_USER_ID = "delivery_pin_user_id"
