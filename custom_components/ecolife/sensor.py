"""Sensor platform for EcoLife."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
)

try:
    from homeassistant.const import UnitOfDensity

    UG_PER_M3 = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
except ImportError:  # Home Assistant versions before UnitOfDensity
    from homeassistant.const import CONCENTRATION_MICROGRAMS_PER_CUBIC_METER as UG_PER_M3
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcolifeConfigEntry
from .api import Measurement, MeasurePoint
from .entity import EcolifeEntity

PARALLEL_UPDATES = 0


def _pressure_hpa(m: Measurement) -> float | None:
    # The API labels pressure "Pa" but reports values like 967.35, i.e. hPa.
    if m.value is None:
        return None
    return m.value / 100 if m.value > 2000 else m.value


@dataclass(frozen=True, kw_only=True)
class EcolifeMeasurementDescription(SensorEntityDescription):
    """Describes a sensor built from one entry of ``latest``."""

    value_fn: Callable[[Measurement], float | None] = lambda m: m.value


# Keys are EcoLife ``measureType`` values seen in the API.
MEASUREMENT_DESCRIPTIONS: dict[str, EcolifeMeasurementDescription] = {
    "PM25": EcolifeMeasurementDescription(
        key="PM25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=UG_PER_M3,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "PM10": EcolifeMeasurementDescription(
        key="PM10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=UG_PER_M3,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "TEMP": EcolifeMeasurementDescription(
        key="TEMP",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    "HUMIDITY": EcolifeMeasurementDescription(
        key="HUMIDITY",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "PRESSURE": EcolifeMeasurementDescription(
        key="PRESSURE",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_pressure_hpa,
    ),
    "VOC": EcolifeMeasurementDescription(
        key="VOC",
        translation_key="voc",
        # Unit reported as "chwc" (EcoLife-specific index), so no device class.
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "CONTAMINATION": EcolifeMeasurementDescription(
        key="CONTAMINATION",
        translation_key="contamination",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    "LIGHT": EcolifeMeasurementDescription(
        key="LIGHT",
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
}

_UNIT_MAP = {"ugm3": UG_PER_M3, "pc": PERCENTAGE, "C": "°C", "lux": LIGHT_LUX}


def _description_for(measure_type: str, unit: str | None) -> EcolifeMeasurementDescription:
    """Return a description; unknown measure types get a generic one."""
    if desc := MEASUREMENT_DESCRIPTIONS.get(measure_type):
        return desc
    return EcolifeMeasurementDescription(
        key=measure_type,
        name=measure_type.replace("_", " ").capitalize(),
        native_unit_of_measurement=_UNIT_MAP.get(unit or "", unit),
        state_class=SensorStateClass.MEASUREMENT,
    )


@dataclass(frozen=True, kw_only=True)
class EcolifePointDescription(SensorEntityDescription):
    """Describes a sensor built from measure point metadata."""

    value_fn: Callable[[MeasurePoint], str | datetime | None]


POINT_DESCRIPTIONS: tuple[EcolifePointDescription, ...] = (
    EcolifePointDescription(
        key="range",
        translation_key="air_quality_range",
        value_fn=lambda mp: mp.range,
    ),
    EcolifePointDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda mp: mp.last_update,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcolifeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensors for every measure point; add new ones as they appear."""
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def _add_new_entities() -> None:
        new: list[SensorEntity] = []
        for mp in (coordinator.data or {}).values():
            for measure_type, measurement in mp.measurements.items():
                if (mp.id, measure_type) in known:
                    continue
                known.add((mp.id, measure_type))
                new.append(
                    EcolifeMeasurementSensor(
                        coordinator, mp, _description_for(measure_type, measurement.unit)
                    )
                )
            for desc in POINT_DESCRIPTIONS:
                if (mp.id, desc.key) in known:
                    continue
                known.add((mp.id, desc.key))
                new.append(EcolifePointSensor(coordinator, mp, desc))
        if new:
            async_add_entities(new)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class EcolifeMeasurementSensor(EcolifeEntity, SensorEntity):
    """A measurement (PM2.5, temperature, ...) of a measure point."""

    entity_description: EcolifeMeasurementDescription

    @property
    def _measurement(self) -> Measurement | None:
        mp = self.measure_point
        return mp.measurements.get(self.entity_description.key) if mp else None

    @property
    def available(self) -> bool:
        """Unavailable if this measurement disappeared from ``latest``."""
        return super().available and self._measurement is not None

    @property
    def native_value(self) -> float | None:
        """Return the measured value."""
        m = self._measurement
        return self.entity_description.value_fn(m) if m else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the norm and %-of-norm the app shows."""
        m = self._measurement
        if m is None:
            return None
        return {"norm": m.norm, "percent_of_norm": m.value_percentage}


class EcolifePointSensor(EcolifeEntity, SensorEntity):
    """Metadata of a measure point (air quality range, last update)."""

    entity_description: EcolifePointDescription

    @property
    def native_value(self) -> str | datetime | None:
        """Return the value."""
        mp = self.measure_point
        return self.entity_description.value_fn(mp) if mp else None
