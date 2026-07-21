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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify

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
from .managed_loads import managed_load_configs
from .models import PlannerResult
from .options import merged_options, serialize_window, serialize_windows

_FORECAST_ATTRIBUTE_MIN_STEP_MINUTES = 15
_ENERGY_ATTRIBUTE_PRECISION = 1


@dataclass(frozen=True, kw_only=True)
class EnergyPlannerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PlannerResult], Any] | None = None
    entry_value_fn: Callable[[ConfigEntry], Any] | None = None
    attr_fn: Callable[[PlannerResult], dict[str, Any]] | None = None
    always_available: bool = False
    entity_registry_enabled_default: bool = True


@dataclass(frozen=True, kw_only=True)
class ManagedSourceSensorDescription(SensorEntityDescription):
    value_key: str = ""
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
    for latest in reversed(points):
        if not isinstance(latest, dict):
            continue
        if latest.get("base_usable", True) is False:
            continue
        value = latest.get("base_kwh")
        return value if isinstance(value, (int, float)) else None
    return None


def _consumption_history_attributes(result: PlannerResult) -> dict[str, Any]:
    history = result.forecast.get("consumption_history")
    if not isinstance(history, dict):
        return {}
    attributes = {key: value for key, value in history.items() if key != "points"}
    points = history.get("points")
    if isinstance(points, list):
        attributes["points"] = [
            _compact_consumption_history_point(point)
            for point in points
            if isinstance(point, dict)
        ]
        attributes["points_compacted"] = True
    return attributes


def _soc_forecast_attributes(result: PlannerResult) -> dict[str, Any]:
    forecast = result.plan.get("soc_forecast")
    if not isinstance(forecast, dict):
        return {}
    attributes = {key: value for key, value in forecast.items() if key != "points"}
    points = forecast.get("points")
    if isinstance(points, list):
        compact_points = _compact_forecast_points(points)
        attributes["source_point_count"] = len(points)
        attributes["point_count"] = len(compact_points)
        attributes["points_compacted"] = True
        attributes["points_downsampled"] = len(compact_points) != len(points)
        attributes["points_resolution_minutes"] = _points_resolution_minutes(
            compact_points
        )
        attributes["points"] = compact_points
    return attributes


def _compact_forecast_points(points: list[Any]) -> list[dict[str, Any]]:
    valid_points = [point for point in points if isinstance(point, dict)]
    if not valid_points:
        return []
    stride = _forecast_point_stride(valid_points)
    compact_points: list[dict[str, Any]] = []
    for index in range(0, len(valid_points), stride):
        chunk = valid_points[index : index + stride]
        point = chunk[-1]
        unused_surplus_kwh = sum(
            value
            for value in (item.get("unused_surplus_kwh") for item in chunk)
            if isinstance(value, (int, float))
        )
        compact_points.append(
            {
                "timestamp": point.get("timestamp"),
                "soc_percent": _int_or_none(point.get("soc_percent")),
                "unused_surplus_kwh": _round_energy(unused_surplus_kwh),
            }
        )
    return compact_points


def _compact_consumption_history_point(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": point.get("timestamp"),
        "home_kwh": _round_energy(point.get("home_kwh")),
        "managed_kwh": _round_energy(point.get("managed_kwh")),
        "base_kwh": _round_energy(point.get("base_kwh")),
        "base_usable": point.get("base_usable", True),
        "is_current_hour": point.get("is_current_hour", False),
    }


def _compact_managed_source_point(point: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": point.get("timestamp"),
        "managed_kwh": _round_energy(point.get("managed_kwh")),
        "is_current_hour": point.get("is_current_hour", False),
    }


def _forecast_point_stride(points: list[dict[str, Any]]) -> int:
    interval_minutes = _points_resolution_minutes(points)
    if interval_minutes is None or interval_minutes <= 0:
        return 1
    return max(1, -(-_FORECAST_ATTRIBUTE_MIN_STEP_MINUTES // interval_minutes))


def _points_resolution_minutes(points: list[dict[str, Any]]) -> int | None:
    if len(points) < 2:
        return None
    first = _timestamp_value(points[0].get("timestamp"))
    second = _timestamp_value(points[1].get("timestamp"))
    if first is None or second is None or second <= first:
        return None
    return max(1, round((second - first).total_seconds() / 60))


def _timestamp_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _round_energy(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(value, _ENERGY_ATTRIBUTE_PRECISION)


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, int) else None


def _managed_source_history(result: PlannerResult, source_id: str) -> dict[str, Any]:
    history = result.forecast.get("managed_source_history")
    if not isinstance(history, dict):
        return {}
    payload = history.get(source_id)
    return dict(payload) if isinstance(payload, dict) else {}


def _managed_source_value(
    result: PlannerResult,
    source_id: str,
    value_key: str,
) -> float | None:
    value = _managed_source_history(result, source_id).get(value_key)
    return round(value, 6) if isinstance(value, (int, float)) else None


def _managed_source_history_attributes(
    result: PlannerResult,
    source_id: str,
) -> dict[str, Any]:
    return _managed_source_history(result, source_id)


def _managed_source_allocation(
    result: PlannerResult,
    source_id: str,
) -> dict[str, Any]:
    allocation = result.plan.get("surplus_allocation")
    if not isinstance(allocation, dict):
        return {}
    loads = allocation.get("loads")
    if not isinstance(loads, dict):
        return {}
    payload = loads.get(source_id)
    return dict(payload) if isinstance(payload, dict) else {}


def _tomorrow_surplus_attributes(result: PlannerResult) -> dict[str, Any]:
    return {
        "forecast_coverage_percent": result.plan.get(
            "unused_surplus_tomorrow_coverage_percent"
        ),
        "solar_coverage_percent": result.plan.get(
            "unused_surplus_tomorrow_solar_coverage_percent"
        ),
    }


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
        value_fn=lambda result: result.plan.get("unused_surplus_kwh"),
    ),
    EnergyPlannerSensorDescription(
        key="unused_surplus_total_kwh",
        translation_key="unused_surplus_total_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda result: result.plan.get("unused_surplus_kwh_total"),
    ),
    EnergyPlannerSensorDescription(
        key="unused_surplus_tomorrow_kwh",
        translation_key="unused_surplus_tomorrow_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda result: result.plan.get("unused_surplus_tomorrow_kwh"),
        attr_fn=_tomorrow_surplus_attributes,
    ),
    EnergyPlannerSensorDescription(
        key="managed_expected_demand_tomorrow_kwh",
        translation_key="managed_expected_demand_tomorrow_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda result: result.plan.get("managed_expected_demand_tomorrow_kwh"),
    ),
    EnergyPlannerSensorDescription(
        key="managed_recommended_tomorrow_kwh",
        translation_key="managed_recommended_tomorrow_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda result: result.plan.get("managed_recommended_tomorrow_kwh"),
    ),
    EnergyPlannerSensorDescription(
        key="unallocated_surplus_tomorrow_kwh",
        translation_key="unallocated_surplus_tomorrow_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda result: result.plan.get("unallocated_surplus_tomorrow_kwh"),
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
        value_fn=lambda result: result.plan.get("vt_grid_import_kwh_at_target"),
    ),
    EnergyPlannerSensorDescription(
        key="charged_kwh_total_at_target",
        translation_key="charged_kwh_total_at_target",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
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
        attr_fn=_soc_forecast_attributes,
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


MANAGED_SOURCE_SENSOR_DESCRIPTIONS: tuple[ManagedSourceSensorDescription, ...] = (
    ManagedSourceSensorDescription(
        key="suggested_tomorrow",
        value_key="recommended_kwh",
        translation_key="managed_source_suggested_tomorrow",
        icon="mdi:chart-donut-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
    ),
    ManagedSourceSensorDescription(
        key="today",
        value_key="today_kwh",
        translation_key="managed_source_today",
        icon="mdi:calendar-today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    ManagedSourceSensorDescription(
        key="current_hour",
        value_key="current_hour_kwh",
        translation_key="managed_source_current_hour",
        icon="mdi:clock-start",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=3,
    ),
    ManagedSourceSensorDescription(
        key="last_hour",
        value_key="last_hour_kwh",
        translation_key="managed_source_last_hour",
        icon="mdi:clock-check-outline",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=3,
    ),
    ManagedSourceSensorDescription(
        key="tracked_total",
        value_key="tracked_total_kwh",
        translation_key="managed_source_tracked_total",
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=3,
    ),
    ManagedSourceSensorDescription(
        key="history",
        value_key="latest_kwh",
        translation_key="managed_source_history",
        icon="mdi:chart-timeline-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        suggested_display_precision=3,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Energy Planner sensors."""
    coordinator: EnergyPlannerCoordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        EnergyPlannerSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    ]
    async_add_entities(entities)
    for load in managed_load_configs(entry):
        source_name = _source_display_name(hass, load.source_entity_id)
        source_entities = [
            EnergyPlannerManagedSourceSensor(
                coordinator,
                entry,
                source_entity_id=load.source_entity_id,
                source_name=source_name,
                subentry_id=load.subentry_id,
                description=description,
            )
            for description in MANAGED_SOURCE_SENSOR_DESCRIPTIONS
        ]
        async_add_entities(
            source_entities,
            config_subentry_id=load.subentry_id,
        )


class EnergyPlannerSensor(CoordinatorEntity[EnergyPlannerCoordinator], SensorEntity):
    """Energy Planner output sensor."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"points"})

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


class EnergyPlannerManagedSourceSensor(
    CoordinatorEntity[EnergyPlannerCoordinator],
    SensorEntity,
):
    """Energy Planner per-managed-source history sensor."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"points"})

    def __init__(
        self,
        coordinator: EnergyPlannerCoordinator,
        entry: ConfigEntry,
        *,
        source_entity_id: str,
        source_name: str,
        subentry_id: str | None,
        description: ManagedSourceSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self._source_entity_id = source_entity_id
        self._source_name = source_name
        self.entity_description = description
        self._attr_unique_id = (
            f"{entry.entry_id}_managed_{slugify(source_entity_id)}_{description.key}"
        )
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_translation_placeholders = {"source": source_name}
        load_identifier = subentry_id or slugify(source_entity_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_managed_load_{load_identifier}")},
            name=source_name,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    @property
    def native_value(self) -> float | None:
        if self.entity_description.key == "tracked_total":
            return round(
                self.coordinator.history.managed_source_tracked_total_kwh(
                    self._source_entity_id
                ),
                6,
            )
        result = self.coordinator.data
        if result is None:
            return None
        if self.entity_description.key == "suggested_tomorrow":
            value = _managed_source_allocation(
                result,
                self._source_entity_id,
            ).get(self.entity_description.value_key)
            return round(value, 6) if isinstance(value, (int, float)) else None
        return _managed_source_value(
            result,
            self._source_entity_id,
            self.entity_description.value_key,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes: dict[str, Any] = {
            "source_entity_id": self._source_entity_id,
            "source_name": self._source_name,
        }
        result = self.coordinator.data
        if result is None:
            return attributes

        if self.entity_description.key == "suggested_tomorrow":
            attributes.update(
                _managed_source_allocation(result, self._source_entity_id)
            )
            return attributes

        history = _managed_source_history_attributes(result, self._source_entity_id)
        attributes.update(
            {key: value for key, value in history.items() if key not in {"points"}}
        )
        attributes["tracked_total_kwh"] = round(
            self.coordinator.history.managed_source_tracked_total_kwh(
                self._source_entity_id
            ),
            6,
        )
        if self.entity_description.key == "history" and "points" in history:
            attributes["points"] = [
                _compact_managed_source_point(point)
                for point in history["points"]
                if isinstance(point, dict)
            ]
            attributes["points_compacted"] = True
        return attributes


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


def _source_display_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    friendly_name = state.attributes.get("friendly_name") if state else None
    if isinstance(friendly_name, str) and friendly_name:
        return friendly_name
    return entity_id.split(".", 1)[-1].replace("_", " ").title()
