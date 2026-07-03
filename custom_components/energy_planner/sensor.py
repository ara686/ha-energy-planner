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
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy
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
class EnergyPlannerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PlannerResult], Any]
    attr_fn: Callable[[PlannerResult], dict[str, Any]] | None = None
    always_available: bool = False


SENSOR_DESCRIPTIONS: tuple[EnergyPlannerSensorDescription, ...] = (
    EnergyPlannerSensorDescription(
        key="state",
        translation_key="state",
        icon="mdi:calculator-variant",
        value_fn=lambda result: result.state,
        attr_fn=lambda result: {
            "warnings": result.warnings,
            "slot_count": result.debug.get("slot_count"),
            "history_status": result.forecast.get("history_status", "unknown"),
        },
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key="lock_soc",
        translation_key="lock_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("lock_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="charge_to_soc",
        translation_key="charge_to_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("charge_to_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="target_soc",
        translation_key="target_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("target_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="safe_discharge_soc",
        translation_key="safe_discharge_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("safe_discharge_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="free_capacity_soc",
        translation_key="free_capacity_soc",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("free_capacity_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="free_capacity_kwh",
        translation_key="free_capacity_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("free_capacity_kwh"),
    ),
    EnergyPlannerSensorDescription(
        key="unused_surplus_today_kwh",
        translation_key="unused_surplus_today_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda result: result.plan.get("unused_surplus_kwh"),
    ),
    EnergyPlannerSensorDescription(
        key="unused_surplus_total_kwh",
        translation_key="unused_surplus_total_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda result: result.plan.get("unused_surplus_kwh_total"),
    ),
    EnergyPlannerSensorDescription(
        key="first_full_time",
        translation_key="first_full_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda result: _datetime_value(result.plan.get("first_full_time")),
    ),
    EnergyPlannerSensorDescription(
        key="vt_grid_import_kwh_at_target",
        translation_key="vt_grid_import_kwh_at_target",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda result: result.plan.get("vt_grid_import_kwh_at_target"),
    ),
    EnergyPlannerSensorDescription(
        key="charged_kwh_total_at_target",
        translation_key="charged_kwh_total_at_target",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda result: result.plan.get("charged_kwh_total_at_target"),
    ),
    EnergyPlannerSensorDescription(
        key="soc_at_planner_start",
        translation_key="soc_at_planner_start",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("soc_at_planner_start"),
    ),
    EnergyPlannerSensorDescription(
        key="soc_at_lock_start",
        translation_key="soc_at_lock_start",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("soc_at_lock_start"),
    ),
    EnergyPlannerSensorDescription(
        key="soc_forecast",
        translation_key="soc_forecast",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: result.plan.get("soc_at_forecast_horizon"),
        attr_fn=lambda result: result.plan.get("soc_forecast", {}),
    ),
    EnergyPlannerSensorDescription(
        key="soc_forecast_24h",
        translation_key="soc_forecast_24h",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda result: _forecast_24h_soc(result),
        attr_fn=lambda result: {"point": result.plan.get("soc_forecast_24h")},
    ),
    EnergyPlannerSensorDescription(
        key="sun_start",
        translation_key="sun_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda result: _datetime_value(result.plan.get("sun_start")),
    ),
    EnergyPlannerSensorDescription(
        key="lock_start",
        translation_key="lock_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda result: _datetime_value(result.plan.get("lock_start")),
    ),
    EnergyPlannerSensorDescription(
        key="updated",
        translation_key="updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda result: result.updated,
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key="history_status",
        translation_key="history_status",
        icon="mdi:history",
        value_fn=lambda result: result.forecast.get("history_status", "unknown"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Energy Planner sensors."""
    coordinator: EnergyPlannerCoordinator = entry.runtime_data
    async_add_entities(
        EnergyPlannerSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class EnergyPlannerSensor(CoordinatorEntity[EnergyPlannerCoordinator], SensorEntity):
    """Energy Planner output sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EnergyPlannerCoordinator,
        entry: ConfigEntry,
        description: EnergyPlannerSensorDescription,
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
        if result is None:
            return False
        if self.entity_description.always_available:
            return True
        return result.state in {"ok", "warning"}

    @property
    def native_value(self) -> Any:
        result = self.coordinator.data
        if result is None:
            return None
        return self.entity_description.value_fn(result)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.coordinator.data
        if result is None or self.entity_description.attr_fn is None:
            return None
        return self.entity_description.attr_fn(result)


def _datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _forecast_24h_soc(result: PlannerResult) -> float | None:
    point = result.plan.get("soc_forecast_24h")
    if not isinstance(point, dict):
        return None
    value = point.get("soc_percent")
    return value if isinstance(value, int | float) else None
