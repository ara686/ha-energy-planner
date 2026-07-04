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
from homeassistant.helpers.entity import EntityCategory

try:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:
    from homeassistant.helpers.entity_platform import (
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_INTERVAL_MINUTES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from .coordinator import EnergyPlannerCoordinator
from .models import PlannerResult
from .options import merged_options, serialize_window, serialize_windows


@dataclass(frozen=True, kw_only=True)
class EnergyPlannerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PlannerResult], Any] | None = None
    entry_value_fn: Callable[[ConfigEntry], Any] | None = None
    attr_fn: Callable[[PlannerResult], dict[str, Any]] | None = None
    always_available: bool = False
    entity_registry_enabled_default: bool = True


def _option_value(key: str) -> Callable[[ConfigEntry], Any]:
    return lambda entry: merged_options(dict(entry.options))[key]


def _windows_option_value(entry: ConfigEntry) -> str:
    return serialize_windows(merged_options(dict(entry.options))[CONF_NT_WINDOWS])


def _window_option_value(key: str) -> Callable[[ConfigEntry], str]:
    return lambda entry: serialize_window(merged_options(dict(entry.options))[key])


def _history_status_value(result: PlannerResult) -> str:
    status = result.forecast.get("history_status")
    if not isinstance(status, dict):
        return "unknown"
    source = status.get("source", "unknown")
    usable = status.get("usable_bucket_count", 0)
    total = status.get("bucket_count", 0)
    return f"{source}: {usable}/{total} buckets"


def _history_status_attributes(result: PlannerResult) -> dict[str, Any]:
    status = result.forecast.get("history_status")
    return dict(status) if isinstance(status, dict) else {}


def _consumption_history_value(result: PlannerResult) -> float | None:
    history = result.forecast.get("consumption_history")
    if not isinstance(history, dict):
        return None
    points = history.get("points")
    if not isinstance(points, list) or not points:
        return None
    latest = points[-1]
    if not isinstance(latest, dict):
        return None
    value = latest.get("base_kwh")
    return value if isinstance(value, (int, float)) else None


def _consumption_history_attributes(result: PlannerResult) -> dict[str, Any]:
    history = result.forecast.get("consumption_history")
    return dict(history) if isinstance(history, dict) else {}


SENSOR_DESCRIPTIONS: tuple[EnergyPlannerSensorDescription, ...] = (
    EnergyPlannerSensorDescription(
        key="state",
        translation_key="state",
        icon="mdi:calculator-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
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
        value_fn=lambda result: result.plan.get("lock_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="charge_to_soc",
        translation_key="charge_to_soc",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda result: result.plan.get("charge_to_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="target_soc",
        translation_key="target_soc",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda result: result.plan.get("target_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="safe_discharge_soc",
        translation_key="safe_discharge_soc",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda result: result.plan.get("safe_discharge_soc"),
    ),
    EnergyPlannerSensorDescription(
        key="free_capacity_soc",
        translation_key="free_capacity_soc",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
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
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda result: result.plan.get("soc_at_planner_start"),
    ),
    EnergyPlannerSensorDescription(
        key="soc_at_lock_start",
        translation_key="soc_at_lock_start",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda result: result.plan.get("soc_at_lock_start"),
    ),
    EnergyPlannerSensorDescription(
        key="soc_forecast",
        translation_key="soc_forecast",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        value_fn=lambda result: result.plan.get("soc_at_forecast_horizon"),
        attr_fn=lambda result: result.plan.get("soc_forecast", {}),
    ),
    EnergyPlannerSensorDescription(
        key="soc_forecast_24h",
        translation_key="soc_forecast_24h",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda result: _forecast_24h_soc(result),
        attr_fn=lambda result: {"point": result.plan.get("soc_forecast_24h")},
    ),
    EnergyPlannerSensorDescription(
        key="sun_start",
        translation_key="sun_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda result: _datetime_value(result.plan.get("sun_start")),
    ),
    EnergyPlannerSensorDescription(
        key="lock_start",
        translation_key="lock_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda result: _datetime_value(result.plan.get("lock_start")),
    ),
    EnergyPlannerSensorDescription(
        key="updated",
        translation_key="updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda result: result.updated,
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key="history_status",
        translation_key="history_status",
        icon="mdi:history",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_history_status_value,
        attr_fn=lambda result: _history_status_attributes(result),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key="consumption_history",
        translation_key="consumption_history",
        icon="mdi:chart-bar",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=_consumption_history_value,
        attr_fn=_consumption_history_attributes,
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_UPDATE_INTERVAL_MINUTES,
        translation_key=CONF_UPDATE_INTERVAL_MINUTES,
        icon="mdi:timer-refresh-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="min",
        entry_value_fn=_option_value(CONF_UPDATE_INTERVAL_MINUTES),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_HISTORY_LEARNING_DAYS,
        translation_key=CONF_HISTORY_LEARNING_DAYS,
        icon="mdi:calendar-range",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="d",
        entry_value_fn=_option_value(CONF_HISTORY_LEARNING_DAYS),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_INTERVAL_MINUTES,
        translation_key=CONF_INTERVAL_MINUTES,
        icon="mdi:timeline-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="min",
        entry_value_fn=_option_value(CONF_INTERVAL_MINUTES),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_HISTORY_CORRECTION_PERCENT,
        translation_key=CONF_HISTORY_CORRECTION_PERCENT,
        icon="mdi:percent-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        entry_value_fn=_option_value(CONF_HISTORY_CORRECTION_PERCENT),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_MIN_BASELINE_KWH_PER_HOUR,
        translation_key=CONF_MIN_BASELINE_KWH_PER_HOUR,
        icon="mdi:home-lightning-bolt-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="kWh/h",
        entry_value_fn=_option_value(CONF_MIN_BASELINE_KWH_PER_HOUR),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_GRID_CHARGE_MAX_KW,
        translation_key=CONF_GRID_CHARGE_MAX_KW,
        icon="mdi:transmission-tower-import",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="kW",
        entry_value_fn=_option_value(CONF_GRID_CHARGE_MAX_KW),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_GRID_CHARGE_EFFICIENCY,
        translation_key=CONF_GRID_CHARGE_EFFICIENCY,
        icon="mdi:battery-charging-high",
        entity_category=EntityCategory.DIAGNOSTIC,
        entry_value_fn=_option_value(CONF_GRID_CHARGE_EFFICIENCY),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_SOC_RESERVE_PERCENT,
        translation_key=CONF_SOC_RESERVE_PERCENT,
        icon="mdi:battery-heart-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        entry_value_fn=_option_value(CONF_SOC_RESERVE_PERCENT),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_SOC_EPS_KWH,
        translation_key=CONF_SOC_EPS_KWH,
        icon="mdi:plus-minus-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        entry_value_fn=_option_value(CONF_SOC_EPS_KWH),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_NT_WINDOWS,
        translation_key=CONF_NT_WINDOWS,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entry_value_fn=_windows_option_value,
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_CHARGE_WINDOW,
        translation_key=CONF_CHARGE_WINDOW,
        icon="mdi:battery-clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entry_value_fn=_window_option_value(CONF_CHARGE_WINDOW),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_SUN_START_REQUIRED_MINUTES,
        translation_key=CONF_SUN_START_REQUIRED_MINUTES,
        icon="mdi:weather-sunny-clock",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="min",
        entry_value_fn=_option_value(CONF_SUN_START_REQUIRED_MINUTES),
        always_available=True,
    ),
    EnergyPlannerSensorDescription(
        key=CONF_FORECAST_HORIZON_HOURS,
        translation_key=CONF_FORECAST_HORIZON_HOURS,
        icon="mdi:telescope",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement="h",
        entry_value_fn=_option_value(CONF_FORECAST_HORIZON_HOURS),
        always_available=True,
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
        self._entry = entry
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
        }

    @property
    def available(self) -> bool:
        if self.entity_description.entry_value_fn is not None:
            return True
        result = self.coordinator.data
        if result is None:
            return False
        if self.entity_description.always_available:
            return True
        return result.state in {"ok", "warning"}

    @property
    def native_value(self) -> Any:
        if self.entity_description.entry_value_fn is not None:
            return self.entity_description.entry_value_fn(self._entry)
        result = self.coordinator.data
        if result is None:
            return None
        if self.entity_description.value_fn is None:
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


def _forecast_24h_soc(result: PlannerResult) -> int | None:
    point = result.plan.get("soc_forecast_24h")
    if not isinstance(point, dict):
        return None
    value = point.get("soc_percent")
    return value if isinstance(value, int) else None
