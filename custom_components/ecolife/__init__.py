"""The EcoLife air quality integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EcolifeApi
from .const import CONF_HIDDEN_DEVICES, DOMAIN, STATIC_URL

STATIC_REGISTERED_KEY = f"{DOMAIN}_static_registered"
from .coordinator import EcolifeCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type EcolifeConfigEntry = ConfigEntry[EcolifeCoordinator]


def _locale(hass: HomeAssistant) -> str:
    return (hass.config.language or "en").split("-")[0]


async def _async_register_static_images(hass: HomeAssistant) -> None:
    """Serve images/ (device picture) once per HA run."""
    if hass.data.get(STATIC_REGISTERED_KEY) or hass.http is None:
        return
    hass.data[STATIC_REGISTERED_KEY] = True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(Path(__file__).parent / "images"), True)]
    )


async def async_setup_entry(hass: HomeAssistant, entry: EcolifeConfigEntry) -> bool:
    """Set up an EcoLife hub (one EcoLife account)."""
    await _async_register_static_images(hass)
    api = EcolifeApi(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        locale=_locale(hass),
    )
    coordinator = EcolifeCoordinator(hass, entry, api)
    # Runs _async_setup (login) and then the first userSearch.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EcolifeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: EcolifeConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Hide a device in Home Assistant when the user deletes it.

    This deliberately does NOT call the EcoLife ``removeDevice`` endpoint: the
    device stays registered on the server and in the mobile app. Its id is
    remembered as hidden, so polling skips it until the user picks
    "Refresh device list" in the hub's options.
    """
    ids = {ident for domain, ident in device_entry.identifiers if domain == DOMAIN}
    if ids:
        hidden = set(entry.data.get(CONF_HIDDEN_DEVICES, [])) | ids
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_HIDDEN_DEVICES: sorted(hidden)}
        )
    return True
