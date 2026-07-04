from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

try:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:
    from homeassistant.helpers.entity_platform import (
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EnergyPlannerCoordinator
from .models import PlannerResult


@dataclass(frozen=True, kw_only=True)
class EnergyPlannerBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[PlannerResult], bool | None]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, int | float) else None


def _charge_now(result: PlannerResult) -> bool | None:
    current_soc = _number(result.plan.get("soc_at_planner_start"))
    charge_to_soc = _number(result.plan.get("charge_to_soc"))
    if current_soc is None or charge_to_soc is None:
        return None
    return current_soc < charge_to_soc


def _discharge_allowed(result: PlannerResult) -> bool | None:
    current_soc = _number(result.plan.get("soc_at_planner_start"))
    safe_discharge_soc = _number(result.plan.get("safe_discharge_soc"))
    if current_soc is None or safe_discharge_soc is None:
        return None
    return current_soc > safe_discharge_soc


BINARY_SENSOR_DESCRIPTIONS: tuple[EnergyPlannerBinarySensorDescription, ...] = (
    EnergyPlannerBinarySensorDescription(
        key="charge_now",
        translation_key="charge_now",
        icon="mdi:battery-charging-high",
        value_fn=_charge_now,
    ),
    EnergyPlannerBinarySensorDescription(
        key="discharge_allowed",
        translation_key="discharge_allowed",
        icon="mdi:battery-arrow-down-outline",
        value_fn=_discharge_allowed,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Energy Planner binary sensors."""
    coordinator: EnergyPlannerCoordinator = entry.runtime_data
    async_add_entities(
        EnergyPlannerBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )


class EnergyPlannerBinarySensor(
    CoordinatorEntity[EnergyPlannerCoordinator],
    BinarySensorEntity,
):
    """Energy Planner plan-state binary sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EnergyPlannerCoordinator,
        entry: ConfigEntry,
        description: EnergyPlannerBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }

    @property
    def available(self) -> bool:
        result = self.coordinator.data
        return (
            super().available
            and result is not None
            and result.state in {"ok", "warning"}
            and self.entity_description.value_fn(result) is not None
        )

    @property
    def is_on(self) -> bool | None:
        result = self.coordinator.data
        if result is None:
            return None
        return self.entity_description.value_fn(result)
