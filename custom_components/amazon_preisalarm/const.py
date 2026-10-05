"""Constants for the Amazon Preisalarm integration."""

from __future__ import annotations

DOMAIN = "amazon_preisalarm"

SUBENTRY_TYPE_PRODUCT = "product"

CONF_SCAN_INTERVAL = "scan_interval"
CONF_URL = "url"
CONF_NAME = "name"
CONF_TARGET_PRICE = "target_price"
CONF_ASIN = "asin"
CONF_AMAZON_DOMAIN = "amazon_domain"
CONF_INITIAL_PRICE = "initial_price"
CONF_ADDED_AT = "added_at"

DEFAULT_SCAN_INTERVAL = 60  # minutes
MIN_SCAN_INTERVAL = 15  # minutes
MAX_SCAN_INTERVAL = 1440  # minutes

# Pause between two product requests within one update cycle (seconds).
REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 5.0

EVENT_PRICE_CHANGED = f"{DOMAIN}_price_changed"

STORAGE_VERSION = 1
