"""Constants for the EcoLife integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "ecolife"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "EcoLife"

# custom_components/ecolife/images is served here (device picture).
STATIC_URL: Final = f"/{DOMAIN}_static"
DEVICE_PICTURE: Final = f"{STATIC_URL}/device.png"

CONF_SCAN_INTERVAL: Final = "scan_interval"
# Measure point ids ("uuid" in the app's API) the user removed from HA.
# They are only hidden locally; nothing is ever deleted on the EcoLife server.
CONF_HIDDEN_DEVICES: Final = "hidden_devices"
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600
