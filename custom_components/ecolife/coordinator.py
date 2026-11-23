"""Data update coordinator for EcoLife."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DeviceSetting, EcolifeApi, EcolifeAuthError, EcolifeError, MeasurePoint
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
        points = {mp_id: mp for mp_id, mp in points.items() if mp_id not in hidden}
        await self._async_attach_settings(points)
        return points

    async def _async_attach_settings(self, points: dict[str, MeasurePoint]) -> None:
        """Join LED settings (keyed by hardware uuid) onto measure points.

        A failure here only makes the brightness controls unavailable; the
        sensor readings are still delivered.
        """
        try:
            settings = await self.api.async_get_device_settings()
        except EcolifeAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except EcolifeError as err:
            LOGGER.warning("Could not read EcoLife device settings: %s", err)
            return
        for mp in points.values():
            mp.setting = next((settings[u] for u in mp.uuids if u in settings), None)

    async def async_set_led(
        self,
        mp_id: str,
        *,
        bright: int | None = None,
        start: int | None = None,
        stop: int | None = None,
    ) -> None:
        """Send a brightness command; unchanged fields keep their current value."""
        mp = (self.data or {}).get(mp_id)
        if mp is None or mp.setting is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_led_settings"
            )
        current = mp.setting
        new = DeviceSetting(
            uuid=current.uuid,
            name=current.name,
            bright=current.bright if bright is None else bright,
            start=current.start if start is None else start,
            stop=current.stop if stop is None else stop,
        )
        # start > stop is allowed: the LED is lit from start, across midnight,
        # until stop (e.g. 22 -> 6 for nights). The cloud accepts and stores it.
        try:
            await self.api.async_send_bright_command(
                new.uuid, new.bright, new.start, new.stop, str(self.hass.config.time_zone)
            )
        except EcolifeAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except EcolifeError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        mp.setting = new
        self.async_update_listeners()
