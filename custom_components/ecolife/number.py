"""LED brightness controls for EcoLife devices (mirrors the app's settings screen)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EcolifeConfigEntry
from .api import DeviceSetting
from .entity import EcolifeEntity

# Commands go through the cloud one at a time.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class EcolifeNumberDescription(NumberEntityDescription):
    """Describes one of the app's sliders."""

    value_fn: Callable[[DeviceSetting], int]
    field: str  # keyword for EcolifeCoordinator.async_set_led


NUMBER_DESCRIPTIONS: tuple[EcolifeNumberDescription, ...] = (
    # "brightOptions" in the app: floor 0, ceil 100, step 10, shown as "%".
    EcolifeNumberDescription(
        key="led_brightness",
        translation_key="led_brightness",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=100,
        native_step=10,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.bright,
        field="bright",
    ),
    # "timeOptions" in the app: floor 0, ceil 24, shown as "H:00".
    EcolifeNumberDescription(
        key="led_start",
        translation_key="led_start",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=24,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.start,
        field="start",
    ),
    EcolifeNumberDescription(
        key="led_stop",
        translation_key="led_stop",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=24,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.HOURS,
        mode=NumberMode.SLIDER,
        value_fn=lambda s: s.stop,
        field="stop",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EcolifeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add LED controls for every device that has settings (owned devices)."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_entities() -> None:
        new: list[EcolifeLedNumber] = []
        for mp in (coordinator.data or {}).values():
            if mp.setting is None or mp.id in known:
                continue
            known.add(mp.id)
            new.extend(EcolifeLedNumber(coordinator, mp, d) for d in NUMBER_DESCRIPTIONS)
        if new:
            async_add_entities(new)

    _add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_entities))


class EcolifeLedNumber(EcolifeEntity, NumberEntity):
    """LED brightness or one end of its hour range."""

    entity_description: EcolifeNumberDescription

    @property
    def _setting(self) -> DeviceSetting | None:
        mp = self.measure_point
        return mp.setting if mp else None

    @property
    def available(self) -> bool:
        """Unavailable while the settings can't be read."""
        return super().available and self._setting is not None

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        setting = self._setting
        return self.entity_description.value_fn(setting) if setting else None

    async def async_set_native_value(self, value: float) -> None:
        """Send the new value to the device via the EcoLife cloud."""
        await self.coordinator.async_set_led(
            self._mp_id, **{self.entity_description.field: int(round(value))}
        )
