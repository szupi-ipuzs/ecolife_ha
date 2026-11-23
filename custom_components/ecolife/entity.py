"""Base entity for EcoLife."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import MeasurePoint
from .const import DOMAIN, MANUFACTURER
from .coordinator import EcolifeCoordinator


class EcolifeEntity(CoordinatorEntity[EcolifeCoordinator]):
    """Base entity bound to one measure point (one HA device)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EcolifeCoordinator,
        mp: MeasurePoint,
        description: EntityDescription,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._mp_id = mp.id
        self._attr_unique_id = f"{mp.id}_{description.key.lower()}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mp.id)},
            name=mp.name,
            manufacturer=MANUFACTURER,
            model="Observed measure point" if mp.observed else "Air quality sensor",
            serial_number=mp.uuids[0] if mp.uuids else None,
        )

    @property
    def measure_point(self) -> MeasurePoint | None:
        """Return the latest data for this measure point."""
        return (self.coordinator.data or {}).get(self._mp_id)

    @property
    def available(self) -> bool:
        """Entity is available while the account still reports the point."""
        return super().available and self.measure_point is not None
