"""Diagnostics support for EcoLife."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import EcolifeConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "token",
    "userId",
    "location",
    "uuids",
    "uuid",
    "title",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EcolifeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "measure_points": [
            async_redact_data(
                {
                    **mp.raw,
                    "observed": mp.observed,
                    "setting": asdict(mp.setting) if mp.setting else None,
                },
                TO_REDACT,
            )
            for mp in (coordinator.data or {}).values()
        ],
    }
