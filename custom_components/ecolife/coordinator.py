"""Data update coordinator for EcoLife."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EcolifeApi, EcolifeAuthError, EcolifeError, MeasurePoint
from .const import (
    CONF_HIDDEN_DEVICES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
)

if TYPE_CHECKING:
    from . import EcolifeConfigEntry


class EcolifeCoordinator(DataUpdateCoordinator[dict[str, MeasurePoint]]):
    """Logs in once, then polls ``MeasurePoint/userSearch`` periodically."""

    config_entry: EcolifeConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: EcolifeConfigEntry, api: EcolifeApi
    ) -> None:
        """Initialise the coordinator."""
        interval = int(
            entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.api = api

    async def _async_setup(self) -> None:
        """Log in when the hub is set up (entry creation or HA start)."""
        try:
            await self.api.async_login()
        except EcolifeAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except EcolifeError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

    async def _async_update_data(self) -> dict[str, MeasurePoint]:
        try:
            points = await self.api.async_get_measure_points()
        except EcolifeAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except EcolifeError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        hidden = set(self.config_entry.data.get(CONF_HIDDEN_DEVICES, []))
        return {mp_id: mp for mp_id, mp in points.items() if mp_id not in hidden}
