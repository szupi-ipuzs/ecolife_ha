"""Constants for the EcoLife integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "ecolife"
LOGGER = logging.getLogger(__package__)

MANUFACTURER: Final = "EcoLife"

CONF_SCAN_INTERVAL: Final = "scan_interval"
# Measure point ids (HA device identifiers) the user removed from HA.
# They are only hidden locally; nothing is ever deleted on the EcoLife server.
CONF_HIDDEN_DEVICES: Final = "hidden_devices"
DEFAULT_SCAN_INTERVAL: Final = 60  # seconds
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600
