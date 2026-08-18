from __future__ import annotations

import logging
import math
import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .allocation import (
    ManagedLoadDemandInput,
    estimate_managed_load,
)
from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_GRID_CHARGING_ENABLED,
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_ADDITIONAL_ENTITIES,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    CONF_UPDATE_INTERVAL_MINUTES,
    DEFAULT_CHARGE_WINDOW,
    DEFAULT_DAILY_HISTORY_MIN_COVERAGE_RATIO,
    DEFAULT_FORECAST_HORIZON_HOURS,
    DEFAULT_GRID_CHARGE_EFFICIENCY,
    DEFAULT_GRID_CHARGE_MAX_KW,
    DEFAULT_GRID_CHARGING_ENABLED,
    DEFAULT_HISTORY_CORRECTION_PERCENT,
    DEFAULT_HISTORY_LEARNING_DAYS,
    DEFAULT_HISTORY_PROFILE_MARGIN_PERCENT,
    DEFAULT_HISTORY_RETENTION_DAYS,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MANAGED_HISTORY_LEARNING_DAYS,
    DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
    DEFAULT_NT_WINDOWS,
    DEFAULT_SOC_EPS_KWH,
    DEFAULT_SOC_RESERVE_PERCENT,
    DEFAULT_SUN_START_REQUIRED_MINUTES,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from .electric_vehicle import (
    ElectricVehicleInput,
    calculate_electric_vehicle_demand,
)
from .ha_history import (
    async_get_recorder_energy_history,
    async_get_recorder_energy_statistics,
)
from .history import EnergyHistory, EnergyHistoryStore
from .hot_water import HotWaterInput, calculate_hot_water_demand
from .managed_allocation import (
    ElectricVehicleAllocationInput,
    GenericAllocationInput,
    HotWaterAllocationInput,
    ManagedAllocationInput,
    ManagedDayAllocation,
    SurplusSlot,
    UnavailableAllocationInput,
    allocate_managed_day,
)
from .managed_forecast import build_managed_demand_schedule
from .managed_loads import managed_energy_entity_ids, managed_load_configs
from .models import PlannerInput, PlannerResult, SolarForecastPoint, TimeWindow
from .planner import calculate_plan, calculate_soc_forecast, generate_forecast_slots
from .sources import parse_float, parse_solcast_attributes
from .units import energy_value_to_kwh, is_supported_energy_unit

_LOGGER = logging.getLogger(__name__)
_MAX_CONSUMPTION_HISTORY_SENSOR_POINTS = 24 * 7
_MAX_MANAGED_SOURCE_HISTORY_SENSOR_POINTS = 24 * 7
_SOLCAST_DAILY_ENTITY_RE = re.compile(
    r"(?:^|_)(?:forecast_)?(today|tomorrow|day_[3-7])$"
)


class EnergyPlannerCoordinator(DataUpdateCoordinator[PlannerResult]):
    """Coordinator for Energy Planner."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.history = EnergyHistory()
        self._energy_source_units: dict[str, str] = {}
        self._history_store = EnergyHistoryStore(hass, entry.entry_id)
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=_coordinator_update_interval(entry),
        )

    def update_interval_from_options(self) -> None:
        """Apply the current automatic recalculation interval option."""
        self.update_interval = _coordinator_update_interval(self.entry)

    def record_energy_source_state(
        self,
        *,
        entity_id: str,
        source_type: str,
        state,
        previous_state=None,
    ) -> None:
        """Record a changed cumulative energy source state."""
        unit = (
            _state_energy_unit(state)
            or _state_energy_unit(previous_state)
            or self._energy_source_units.get(entity_id)
        )
        if unit is not None:
            self._energy_source_units[entity_id] = unit
        value = energy_value_to_kwh(
            state.state,
            unit,
        )
        if value is None:
            return
        _record_energy_value(
            self.history,
            dt_util.as_local(state.last_updated),
            entity_id=entity_id,
            source_type=source_type,
            value=value,
        )

    async def async_load_history(self) -> None:
        """Load stored consumption history before the first refresh."""
        self.history = await self._history_store.async_load()

    async def _async_update_data(self) -> PlannerResult:
        """Fetch and calculate planner data."""
        now = dt_util.now()
        source_warnings: list[str] = []
        _record_consumption_history(
            self.hass,
            self.entry,
            self.history,
            now,
            source_warnings,
            self._energy_source_units,
        )
        self.history.cleanup(
            now=now,
            retention_days=max(
                DEFAULT_HISTORY_RETENTION_DAYS, _history_days(self.entry)
            ),
        )
        planner_history = await _async_planner_history_from_ha(
            self.hass,
            self.entry,
            now=now,
            learning_days=max(
                _history_days(self.entry),
                DEFAULT_MANAGED_HISTORY_LEARNING_DAYS,
            )
            + 1,
            fallback_history=self.history,
            warnings=source_warnings,
        )
        result = build_planner_result(
            self.hass,
            self.entry,
            history=planner_history.history,
            now=now,
            source_warnings=source_warnings,
            history_source=planner_history.source,
        )
        await self._async_save_history_if_changed()
        if result.warnings:
            _LOGGER.warning(
                "Energy Planner update completed with warnings: %s",
                result.warnings,
            )
        return result

    async def _async_save_history_if_changed(self) -> None:
        """Persist internal history only when it changed."""
        if self.history.dirty:
            await self._history_store.async_save(self.history)


def build_planner_result(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    history: EnergyHistory | None = None,
    now=None,
    source_warnings: list[str] | None = None,
    history_source: str = "stored",
) -> PlannerResult:
    """Build a planner result from configured Home Assistant entities."""
    now = now or dt_util.now()
    history = history or EnergyHistory()
    history_days = _history_days(entry)
    history_status = history.status(now=now, learning_days=history_days)
    history_status["source"] = history_source
    consumption_history = _consumption_history_payload(
        history,
        now=now,
        learning_days=history_days,
        source=history_source,
        status=history_status,
    )
    managed_source_history = _managed_source_history_payload(
        history,
        now=now,
        learning_days=history_days,
        source=history_source,
        source_ids=managed_energy_entity_ids(entry),
    )
    planner_input, warnings = _build_planner_input(
        hass,
        entry,
        history,
        now,
        history_days=history_days,
    )
    warnings = [*(source_warnings or []), *warnings]
    if planner_input is None:
        return PlannerResult(
            state="insufficient_data",
            updated=now,
            warnings=warnings,
            forecast={
                "history_status": history_status,
                "consumption_history": consumption_history,
                "managed_source_history": managed_source_history,
            },
        )

    result = calculate_plan(planner_input)
    allocations = _add_managed_allocations(
        hass,
        entry,
        history=history,
        now=now,
        result=result,
        warnings=warnings,
    )
    _add_managed_soc_forecast(
        planner_input=planner_input,
        history=history,
        now=now,
        allocations=allocations,
        result=result,
    )
    result.forecast["history_status"] = history_status
    result.forecast["consumption_history"] = consumption_history
    result.forecast["managed_source_history"] = managed_source_history
    result.debug["history_status"] = history_status
    if warnings:
        result.warnings = warnings + result.warnings
        if result.state == "ok":
            result.state = "warning"
    return result


def _add_managed_allocations(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    history: EnergyHistory,
    now,
    result: PlannerResult,
    warnings: list[str],
) -> list[ManagedDayAllocation]:
    """Build typed managed-load allocations for every future forecast day."""
    load_inputs = _managed_allocation_inputs(
        hass,
        entry,
        history=history,
        now=now,
        warnings=warnings,
    )
    interval_minutes = _interval_minutes(entry)
    daily_summaries = {
        item.get("date"): item
        for item in result.plan.get("unused_surplus_by_day", [])
        if isinstance(item, dict) and isinstance(item.get("date"), str)
    }
    today = now.date()
    tomorrow = now.date() + timedelta(days=1)
    if tomorrow.isoformat() not in daily_summaries:
        tomorrow_surplus = result.plan.get("unused_surplus_tomorrow_kwh")
        tomorrow_complete = (
            result.plan.get("unused_surplus_tomorrow_coverage_percent") == 100
            and result.plan.get("unused_surplus_tomorrow_solar_coverage_percent") == 100
        )
        if isinstance(tomorrow_surplus, int | float):
            daily_summaries[tomorrow.isoformat()] = {
                "date": tomorrow.isoformat(),
                "complete": tomorrow_complete,
                "unused_surplus_kwh": float(tomorrow_surplus),
            }
    hot_water_inputs = [
        load
        for load in load_inputs
        if isinstance(load, HotWaterAllocationInput)
        or (
            isinstance(load, UnavailableAllocationInput)
            and load.load_type == "hot_water"
        )
    ]
    electric_vehicle_inputs = [
        load
        for load in load_inputs
        if isinstance(load, ElectricVehicleAllocationInput)
        or (
            isinstance(load, UnavailableAllocationInput)
            and load.load_type == "electric_vehicle"
        )
    ]
    generic_inputs = [
        load for load in load_inputs if isinstance(load, GenericAllocationInput)
    ]
    forecast = result.plan.get("soc_forecast")
    points = forecast.get("points", []) if isinstance(forecast, dict) else []
    allocations: list[ManagedDayAllocation] = []
    carried_ev_inputs = electric_vehicle_inputs

    if electric_vehicle_inputs:
        today_slots, today_complete = _remaining_today_surplus_slots(
            points,
            now=now,
            interval_minutes=interval_minutes,
        )
        today_allocation = allocate_managed_day(
            target_date=today,
            interval_minutes=interval_minutes,
            surplus_complete=today_complete,
            surplus_slots=today_slots,
            loads=electric_vehicle_inputs,
        )
        allocations.append(today_allocation)
        carried_ev_inputs = _carry_electric_vehicle_inputs(
            electric_vehicle_inputs,
            today_allocation,
        )
        result.plan["surplus_allocation_today"] = today_allocation.as_dict()
        result.plan["managed_recommended_today_kwh"] = (
            today_allocation.recommended_kwh if today_allocation.state == "ok" else None
        )
    else:
        result.plan["surplus_allocation_today"] = None
        result.plan["managed_recommended_today_kwh"] = 0.0

    additional_dates = (
        {
            parsed_date
            for raw_date in daily_summaries
            if (parsed_date := _parse_date(raw_date)) is not None
            and parsed_date > tomorrow
        }
        if hot_water_inputs or electric_vehicle_inputs
        else set()
    )
    future_dates = sorted(additional_dates | {tomorrow})
    for target_date in future_dates:
        summary = daily_summaries.get(target_date.isoformat(), {})
        complete = bool(summary.get("complete"))
        surplus_slots = _surplus_slots_for_date(
            points,
            target_date=target_date,
            reference=now,
        )
        if (
            complete
            and not surplus_slots
            and isinstance(summary.get("unused_surplus_kwh"), int | float)
        ):
            surplus_slots = [
                SurplusSlot(
                    datetime.combine(target_date, datetime.min.time()),
                    float(summary["unused_surplus_kwh"]),
                )
            ]
        day_inputs: list[ManagedAllocationInput] = [
            *hot_water_inputs,
            *carried_ev_inputs,
        ]
        if target_date == tomorrow:
            day_inputs.extend(generic_inputs)
        day_allocation = allocate_managed_day(
            target_date=target_date,
            interval_minutes=interval_minutes,
            surplus_complete=complete,
            surplus_slots=surplus_slots,
            loads=day_inputs,
        )
        allocations.append(day_allocation)
        carried_ev_inputs = _carry_electric_vehicle_inputs(
            carried_ev_inputs,
            day_allocation,
        )

    allocation_payload = [allocation.as_dict() for allocation in allocations]
    tomorrow_allocation = next(
        (
            allocation
            for allocation in allocations
            if allocation.target_date == tomorrow
        ),
        allocate_managed_day(
            target_date=tomorrow,
            interval_minutes=interval_minutes,
            surplus_complete=False,
            surplus_slots=[],
            loads=[*hot_water_inputs, *carried_ev_inputs, *generic_inputs],
        ),
    )
    result.plan["managed_allocation_by_day"] = allocation_payload
    result.plan["surplus_allocation"] = tomorrow_allocation.as_dict()
    result.plan["managed_expected_demand_tomorrow_kwh"] = (
        tomorrow_allocation.expected_demand_kwh
    )
    result.plan["managed_recommended_tomorrow_kwh"] = (
        tomorrow_allocation.recommended_kwh
    )
    result.plan["unallocated_surplus_tomorrow_kwh"] = (
        tomorrow_allocation.unallocated_surplus_kwh
    )
    return allocations


def _managed_allocation_inputs(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    history: EnergyHistory,
    now,
    warnings: list[str],
) -> list[ManagedAllocationInput]:
    """Build runtime inputs for every managed-load strategy."""
    learning_days = DEFAULT_MANAGED_HISTORY_LEARNING_DAYS
    load_inputs: list[ManagedAllocationInput] = []
    for load in managed_load_configs(entry):
        if load.is_hot_water:
            hot_water_input = _hot_water_allocation_input(hass, load, warnings)
            load_inputs.append(hot_water_input)
            continue
        if load.is_electric_vehicle:
            electric_vehicle_input = _electric_vehicle_allocation_input(
                hass, load, warnings
            )
            load_inputs.append(electric_vehicle_input)
            continue
        daily_usage = history.managed_source_daily_usage(
            load.source_entity_id,
            now=now,
            learning_days=learning_days,
            minimum_coverage_ratio=DEFAULT_DAILY_HISTORY_MIN_COVERAGE_RATIO,
        )
        requested_energy_kwh = None
        if load.requested_energy_entity_id:
            requested_energy_kwh = _entity_float(
                hass,
                load.requested_energy_entity_id,
            )
            if requested_energy_kwh is None or requested_energy_kwh < 0:
                warnings.append(
                    "Requested energy source has no valid non-negative state: "
                    f"{load.requested_energy_entity_id}. Using history instead."
                )
                requested_energy_kwh = None
        estimate = estimate_managed_load(
            ManagedLoadDemandInput(
                load.source_entity_id,
                [item.energy_kwh for item in daily_usage],
                requested_energy_kwh,
            )
        )
        load_inputs.append(
            GenericAllocationInput(
                source_id=load.source_entity_id,
                priority=load.priority,
                estimate=estimate,
            )
        )
    return load_inputs


_add_surplus_allocation = _add_managed_allocations


def _hot_water_allocation_input(
    hass: HomeAssistant,
    load,
    warnings: list[str],
) -> ManagedAllocationInput:
    """Build one hot-water input or an explicit unavailable result."""
    required_config = (
        load.top_temperature_entity_id,
        load.bottom_temperature_entity_id,
        load.minimum_temperature_c,
        load.tank_volume_liters,
        load.heater_power_kw,
    )
    if any(value is None for value in required_config):
        reason = "invalid_hot_water_configuration"
        warnings.append(
            f"Hot-water load has incomplete configuration: {load.source_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id, "hot_water", load.priority, reason
        )
    if not math.isfinite(load.heater_power_kw) or load.heater_power_kw <= 0:
        warnings.append(
            f"Hot-water load has invalid physical parameters: {load.source_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "hot_water",
            load.priority,
            "invalid_hot_water_parameters",
        )
    top_temperature = _temperature_entity_celsius(hass, load.top_temperature_entity_id)
    bottom_temperature = _temperature_entity_celsius(
        hass, load.bottom_temperature_entity_id
    )
    if top_temperature is None or bottom_temperature is None:
        invalid_entities = [
            entity_id
            for entity_id, value in (
                (load.top_temperature_entity_id, top_temperature),
                (load.bottom_temperature_entity_id, bottom_temperature),
            )
            if value is None
        ]
        warnings.append(
            "Hot-water temperature source has no valid state: "
            + ", ".join(invalid_entities)
            + "."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "hot_water",
            load.priority,
            "invalid_temperature_source",
        )
    try:
        demand = calculate_hot_water_demand(
            HotWaterInput(
                top_temperature_c=top_temperature,
                bottom_temperature_c=bottom_temperature,
                minimum_temperature_c=load.minimum_temperature_c,
                maximum_temperature_c=load.maximum_temperature_c,
                tank_volume_liters=load.tank_volume_liters,
                thermal_conversion_factor=load.thermal_conversion_factor,
            )
        )
    except ValueError:
        warnings.append(
            f"Hot-water load has invalid physical parameters: {load.source_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "hot_water",
            load.priority,
            "invalid_hot_water_parameters",
        )
    return HotWaterAllocationInput(
        source_id=load.source_entity_id,
        priority=load.priority,
        heater_power_kw=load.heater_power_kw,
        demand=demand,
    )


def _electric_vehicle_allocation_input(
    hass: HomeAssistant,
    load,
    warnings: list[str],
) -> ManagedAllocationInput:
    """Build one electric-vehicle input or an explicit unavailable result."""
    if load.required_energy_entity_id is None or load.maximum_charging_power_kw is None:
        warnings.append(
            "Electric-vehicle load has incomplete configuration: "
            f"{load.source_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "electric_vehicle",
            load.priority,
            "invalid_electric_vehicle_configuration",
        )

    required_state = hass.states.get(load.required_energy_entity_id)
    battery_required_kwh = energy_value_to_kwh(
        required_state.state if required_state else None,
        required_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if required_state
        else None,
    )
    if (
        battery_required_kwh is None
        or not math.isfinite(battery_required_kwh)
        or battery_required_kwh < 0
    ):
        warnings.append(
            "Electric-vehicle required-energy source has no valid non-negative "
            f"state: {load.required_energy_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "electric_vehicle",
            load.priority,
            "invalid_required_energy_source",
        )

    if (
        not math.isfinite(load.maximum_charging_power_kw)
        or load.maximum_charging_power_kw <= 0
    ):
        warnings.append(
            "Electric-vehicle load has no valid positive maximum charging power: "
            f"{load.source_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "electric_vehicle",
            load.priority,
            "invalid_maximum_charging_power",
        )

    try:
        demand = calculate_electric_vehicle_demand(
            ElectricVehicleInput(
                battery_required_kwh=battery_required_kwh,
                charging_efficiency=load.charging_efficiency,
            )
        )
    except ValueError:
        warnings.append(
            f"Electric-vehicle load has invalid parameters: {load.source_entity_id}."
        )
        return UnavailableAllocationInput(
            load.source_entity_id,
            "electric_vehicle",
            load.priority,
            "invalid_electric_vehicle_parameters",
        )
    return ElectricVehicleAllocationInput(
        source_id=load.source_entity_id,
        priority=load.priority,
        maximum_charging_power_kw=load.maximum_charging_power_kw,
        demand=demand,
    )


def _add_managed_soc_forecast(
    *,
    planner_input: PlannerInput,
    history: EnergyHistory,
    now,
    allocations: list[ManagedDayAllocation],
    result: PlannerResult,
) -> None:
    """Add a passive SoC forecast including expected managed demand."""
    energy_by_slot: dict[datetime, float] = {}
    scheduled_by_source: dict[str, float] = {}
    fallback_source_ids: set[str] = set()
    total_expected = 0.0
    tomorrow = now.date() + timedelta(days=1)
    for allocation in allocations:
        expected_by_source = {
            load.source_id: load.expected_demand_kwh
            for load in allocation.loads
            if load.load_type == "generic" and allocation.target_date == tomorrow
        }
        hourly_profiles = {
            source_id: history.managed_source_hourly_profile(
                source_id,
                now=now,
                learning_days=DEFAULT_MANAGED_HISTORY_LEARNING_DAYS,
                minimum_coverage_ratio=DEFAULT_DAILY_HISTORY_MIN_COVERAGE_RATIO,
            )
            for source_id in expected_by_source
        }
        generic_schedule = build_managed_demand_schedule(
            slots=planner_input.slots,
            target_date=allocation.target_date,
            reference=now,
            interval_minutes=planner_input.interval_minutes,
            expected_by_source=expected_by_source,
            hourly_profiles=hourly_profiles,
        )
        _merge_slot_energy(energy_by_slot, generic_schedule.energy_by_slot)
        _merge_source_energy(scheduled_by_source, generic_schedule.scheduled_by_source)
        fallback_source_ids.update(generic_schedule.fallback_source_ids)
        _merge_slot_energy(energy_by_slot, allocation.hot_water_energy_by_slot)
        _merge_source_energy(
            scheduled_by_source, allocation.hot_water_scheduled_by_source
        )
        _merge_slot_energy(
            energy_by_slot,
            allocation.electric_vehicle_energy_by_slot,
        )
        _merge_source_energy(
            scheduled_by_source,
            allocation.electric_vehicle_scheduled_by_source,
        )
        total_expected += (
            generic_schedule.expected_kwh
            + sum(allocation.hot_water_scheduled_by_source.values())
            + sum(allocation.electric_vehicle_scheduled_by_source.values())
        )

    forecast = calculate_soc_forecast(
        planner_input,
        managed_consumption_by_slot=energy_by_slot,
    )
    points = [point.as_dict() for point in forecast.points]
    result.plan["soc_forecast_with_managed"] = {
        "horizon_hours": planner_input.forecast_horizon_hours,
        "source": "ha_entities_and_managed_estimates",
        "target_date": tomorrow.isoformat(),
        "managed_expected_kwh": round(total_expected, 6),
        "managed_scheduled_kwh": round(sum(energy_by_slot.values()), 6),
        "managed_scheduled_by_source": {
            source_id: round(value, 6)
            for source_id, value in sorted(scheduled_by_source.items())
        },
        "fallback_source_ids": sorted(fallback_source_ids),
        "managed_allocation_by_day": [
            allocation.as_dict() for allocation in allocations
        ],
        "point_24h": (
            forecast.point_24h.as_dict() if forecast.point_24h is not None else None
        ),
        "points": points,
    }
    result.plan["soc_at_forecast_horizon_with_managed"] = (
        forecast.horizon_point.soc_percent
        if forecast.horizon_point is not None
        else result.plan.get("soc_at_forecast_horizon")
    )


def _merge_slot_energy(
    target: dict[datetime, float], source: dict[datetime, float]
) -> None:
    for slot_start, value in source.items():
        target[slot_start] = target.get(slot_start, 0.0) + value


def _merge_source_energy(target: dict[str, float], source: dict[str, float]) -> None:
    for source_id, value in source.items():
        target[source_id] = target.get(source_id, 0.0) + value


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _carry_electric_vehicle_inputs(
    inputs: list[ManagedAllocationInput],
    allocation: ManagedDayAllocation,
) -> list[ManagedAllocationInput]:
    """Carry only an EV load's unallocated electrical requirement forward."""
    results = {load.source_id: load for load in allocation.loads}
    carried: list[ManagedAllocationInput] = []
    for load in inputs:
        if not isinstance(load, ElectricVehicleAllocationInput):
            carried.append(load)
            continue
        result = results.get(load.source_id)
        allocated = (
            result.recommended_kwh
            if result is not None and result.recommended_kwh is not None
            else 0.0
        )
        remaining = max(load.demand.electrical_remaining_kwh - allocated, 0.0)
        carried.append(
            replace(
                load,
                demand=load.demand.with_electrical_remaining(remaining),
            )
        )
    return carried


def _remaining_today_surplus_slots(
    points: object,
    *,
    now: datetime,
    interval_minutes: int,
) -> tuple[list[SurplusSlot], bool]:
    """Return covered surplus slots from the next interval to local midnight."""
    if interval_minutes <= 0:
        return [], False
    start = _ceil_to_interval(now, interval_minutes)
    end = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=now.tzinfo)
    expected: list[datetime] = []
    cursor = start
    while _timeline_time(cursor) < _timeline_time(end):
        expected.append(cursor)
        cursor = _add_elapsed_time(cursor, timedelta(minutes=interval_minutes))
    if not expected:
        return [], True
    if not isinstance(points, list):
        return [], False

    point_by_start: dict[datetime, tuple[float, float]] = {}
    for point in points:
        if not isinstance(point, dict):
            continue
        timestamp = _datetime_from_value(point.get("timestamp"))
        surplus = point.get("unused_surplus_kwh")
        coverage = point.get("solar_coverage")
        if (
            timestamp is None
            or not isinstance(surplus, int | float)
            or not isinstance(coverage, int | float)
        ):
            continue
        point_by_start[_timeline_time(timestamp)] = (
            max(float(surplus), 0.0),
            float(coverage),
        )

    slots: list[SurplusSlot] = []
    for slot_start in expected:
        point = point_by_start.get(_timeline_time(slot_start))
        if point is None or point[1] < 0.999:
            return [], False
        slots.append(SurplusSlot(slot_start, point[0]))
    return slots, True


def _ceil_to_interval(timestamp: datetime, interval_minutes: int) -> datetime:
    """Align a timestamp to the same next slot boundary used by the planner."""
    clean = timestamp.replace(second=0, microsecond=0)
    minutes = clean.hour * 60 + clean.minute
    remainder = minutes % interval_minutes
    if remainder == 0 and timestamp.second == 0 and timestamp.microsecond == 0:
        return clean
    return clean + timedelta(minutes=interval_minutes - remainder)


def _add_elapsed_time(timestamp: datetime, delta: timedelta) -> datetime:
    """Advance an aware timestamp without losing a repeated DST hour."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp + delta
    return (timestamp.astimezone(UTC) + delta).astimezone(timestamp.tzinfo)


def _timeline_time(timestamp: datetime) -> datetime:
    """Return a comparable absolute timestamp while preserving naive inputs."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp
    return timestamp.astimezone(UTC)


def _surplus_slots_for_date(
    points: object,
    *,
    target_date: date,
    reference: datetime,
) -> list[SurplusSlot]:
    if not isinstance(points, list):
        return []
    slots: list[SurplusSlot] = []
    for point in points:
        if not isinstance(point, dict):
            continue
        timestamp = _datetime_from_value(point.get("timestamp"))
        surplus = point.get("unused_surplus_kwh")
        if (
            timestamp is None
            or not isinstance(surplus, int | float)
            or _local_date(timestamp, reference) != target_date
        ):
            continue
        slots.append(SurplusSlot(timestamp, max(float(surplus), 0.0)))
    return slots


def _datetime_from_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _local_date(timestamp: datetime, reference: datetime) -> date:
    if timestamp.tzinfo is not None and reference.tzinfo is not None:
        timestamp = timestamp.astimezone(reference.tzinfo)
    return timestamp.date()


def _temperature_entity_celsius(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    if state.attributes.get("device_class") != SensorDeviceClass.TEMPERATURE:
        return None
    value = parse_float(state.state)
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    if value is None or unit is None:
        return None
    try:
        return float(
            TemperatureConverter.convert(
                value,
                str(unit),
                UnitOfTemperature.CELSIUS,
            )
        )
    except (TypeError, ValueError):
        return None


def _consumption_history_payload(
    history: EnergyHistory,
    *,
    now,
    learning_days: int,
    source: str,
    status: dict[str, Any],
) -> dict[str, Any]:
    points, truncated = history.hourly_points(
        now=now,
        learning_days=learning_days,
        point_limit=_MAX_CONSUMPTION_HISTORY_SENSOR_POINTS,
    )
    return {
        "source": source,
        "learning_days": learning_days,
        "bucket_count": status["bucket_count"],
        "usable_bucket_count": status["usable_bucket_count"],
        "point_count": len(points),
        "point_limit": _MAX_CONSUMPTION_HISTORY_SENSOR_POINTS,
        "truncated": truncated,
        "points": points,
    }


def _managed_source_history_payload(
    history: EnergyHistory,
    *,
    now,
    learning_days: int,
    source: str,
    source_ids: list[str],
) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for source_id in source_ids:
        points, truncated = history.managed_source_hourly_points(
            source_id,
            now=now,
            learning_days=learning_days,
            point_limit=_MAX_MANAGED_SOURCE_HISTORY_SENSOR_POINTS,
        )
        latest_kwh = points[-1]["managed_kwh"] if points else 0.0
        payload[source_id] = {
            "history_source": source,
            "source_entity_id": source_id,
            "learning_days": learning_days,
            "today_kwh": round(
                history.managed_source_today_kwh(source_id, now=now),
                6,
            ),
            "current_hour_kwh": round(
                history.managed_source_current_hour_kwh(source_id, now=now),
                6,
            ),
            "last_hour_kwh": round(
                history.managed_source_last_hour_kwh(source_id, now=now),
                6,
            ),
            "latest_kwh": latest_kwh,
            "point_count": len(points),
            "point_limit": _MAX_MANAGED_SOURCE_HISTORY_SENSOR_POINTS,
            "truncated": truncated,
            "points": points,
        }
    return payload


def _build_planner_input(
    hass: HomeAssistant,
    entry: ConfigEntry,
    history: EnergyHistory,
    now,
    history_days: int,
) -> tuple[PlannerInput | None, list[str]]:
    warnings: list[str] = []

    battery_soc = _required_float(hass, entry, CONF_BATTERY_SOC_ENTITY, warnings)
    battery_capacity = _required_float(
        hass, entry, CONF_BATTERY_CAPACITY_ENTITY, warnings
    )
    battery_min_soc = _required_float(
        hass, entry, CONF_BATTERY_MIN_SOC_ENTITY, warnings
    )
    if not entry.data.get(CONF_HOME_ENERGY_ENTITY):
        warnings.append(
            "Required history source entity is not configured: "
            f"{CONF_HOME_ENERGY_ENTITY}."
        )
        return None, warnings

    if battery_soc is None or battery_capacity is None or battery_min_soc is None:
        return None, warnings

    min_baseline_kwh_per_hour = _option(
        entry,
        CONF_MIN_BASELINE_KWH_PER_HOUR,
        DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
    )
    history_correction_percent = _option(
        entry,
        CONF_HISTORY_CORRECTION_PERCENT,
        DEFAULT_HISTORY_CORRECTION_PERCENT,
    )
    hourly_profile = history.hourly_base_consumption_profile(
        now=now,
        learning_days=history_days,
        margin_percent=DEFAULT_HISTORY_PROFILE_MARGIN_PERCENT,
        include_current_hour=False,
    )
    if not history.status(
        now=now,
        learning_days=history_days,
    )["has_completed_bucket"]:
        warnings.append(
            "Consumption history has no completed hourly bucket yet; "
            "using minimum baseline until history is collected."
        )
    elif not hourly_profile:
        warnings.append(
            "Consumption history has no usable hourly profile; using minimum baseline."
        )

    interval_minutes = _option(entry, CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES)
    horizon_hours = _option(
        entry,
        CONF_FORECAST_HORIZON_HOURS,
        DEFAULT_FORECAST_HORIZON_HOURS,
    )
    solar_forecast = _solcast_forecast(hass, entry, warnings)
    slots = generate_forecast_slots(
        now=now,
        horizon_hours=max(24, horizon_hours),
        interval_minutes=interval_minutes,
        solar_forecast=solar_forecast,
        consumption_kwh_per_hour=lambda slot_start: _consumption_from_hourly_profile(
            hourly_profile=hourly_profile,
            target=slot_start,
            min_baseline_kwh_per_hour=min_baseline_kwh_per_hour,
            history_correction_percent=history_correction_percent,
        ),
    )

    return (
        PlannerInput(
            now=now,
            battery_soc=battery_soc,
            battery_capacity_kwh=battery_capacity,
            battery_min_soc=battery_min_soc,
            slots=slots,
            nt_windows=_time_windows(
                _option(entry, CONF_NT_WINDOWS, DEFAULT_NT_WINDOWS)
            ),
            charge_window=_time_window(
                _option(entry, CONF_CHARGE_WINDOW, DEFAULT_CHARGE_WINDOW)
            ),
            grid_charging_enabled=_option(
                entry,
                CONF_GRID_CHARGING_ENABLED,
                DEFAULT_GRID_CHARGING_ENABLED,
            ),
            interval_minutes=interval_minutes,
            grid_charge_max_kw=_option(
                entry,
                CONF_GRID_CHARGE_MAX_KW,
                DEFAULT_GRID_CHARGE_MAX_KW,
            ),
            grid_charge_efficiency=_option(
                entry,
                CONF_GRID_CHARGE_EFFICIENCY,
                DEFAULT_GRID_CHARGE_EFFICIENCY,
            ),
            soc_reserve_percent=_option(
                entry,
                CONF_SOC_RESERVE_PERCENT,
                DEFAULT_SOC_RESERVE_PERCENT,
            ),
            soc_eps_kwh=_option(entry, CONF_SOC_EPS_KWH, DEFAULT_SOC_EPS_KWH),
            sun_start_required_minutes=_option(
                entry,
                CONF_SUN_START_REQUIRED_MINUTES,
                DEFAULT_SUN_START_REQUIRED_MINUTES,
            ),
            forecast_horizon_hours=horizon_hours,
        ),
        warnings,
    )


def _required_float(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    warnings: list[str],
) -> float | None:
    entity_id = entry.data.get(key)
    if not entity_id:
        warnings.append(f"Required entity is not configured: {key}.")
        return None
    value = _entity_float(hass, entity_id)
    if value is None:
        warnings.append(f"Required entity has no valid numeric state: {entity_id}.")
    return value


def _entity_float(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return parse_float(state.state)


def _state_energy_unit(state) -> str | None:
    if state is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    return unit if is_supported_energy_unit(unit) else None


def _energy_entity_kwh(
    hass: HomeAssistant,
    entity_id: str,
    known_units: dict[str, str],
) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    unit = _state_energy_unit(state) or known_units.get(entity_id)
    if unit is not None:
        known_units[entity_id] = unit
    return energy_value_to_kwh(
        state.state,
        unit,
    )


def _record_consumption_history(
    hass: HomeAssistant,
    entry: ConfigEntry,
    history: EnergyHistory,
    now,
    warnings: list[str],
    known_units: dict[str, str],
) -> None:
    home_entity_id = entry.data.get(CONF_HOME_ENERGY_ENTITY)
    if home_entity_id:
        home_value = _energy_entity_kwh(hass, home_entity_id, known_units)
        if home_value is None:
            warnings.append(
                f"Home energy source has no valid numeric state: {home_entity_id}."
            )
        else:
            _record_energy_value(
                history,
                now,
                entity_id=home_entity_id,
                source_type="home",
                value=home_value,
            )

    for managed_entity_id in managed_energy_entity_ids(entry):
        managed_value = _energy_entity_kwh(hass, managed_entity_id, known_units)
        if managed_value is None:
            warnings.append(
                "Managed energy source has no valid numeric state: "
                f"{managed_entity_id}."
            )
        else:
            _record_energy_value(
                history,
                now,
                entity_id=managed_entity_id,
                source_type="managed",
                value=managed_value,
            )


class _PlannerHistory:
    def __init__(self, history: EnergyHistory, source: str) -> None:
        self.history = history
        self.source = source


def _record_energy_value(
    history: EnergyHistory,
    timestamp,
    *,
    entity_id: str,
    source_type: str,
    value: float,
) -> None:
    history.record_cumulative_energy_source(
        timestamp,
        source_type=source_type,
        source_id=f"{source_type}:{entity_id}",
        value=value,
    )


async def _async_planner_history_from_ha(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    now,
    learning_days: int,
    fallback_history: EnergyHistory,
    warnings: list[str],
) -> _PlannerHistory:
    home_entity_id = entry.data.get(CONF_HOME_ENERGY_ENTITY)
    if not home_entity_id:
        return _PlannerHistory(fallback_history, "stored")

    managed_entity_ids = managed_energy_entity_ids(entry)
    history = await async_get_recorder_energy_statistics(
        hass,
        home_entity_id=home_entity_id,
        managed_entity_ids=managed_entity_ids,
        now=now,
        learning_days=learning_days,
    )
    source = "ha_statistics"
    if history is None:
        history = await async_get_recorder_energy_history(
            hass,
            home_entity_id=home_entity_id,
            managed_entity_ids=managed_entity_ids,
            now=now,
            learning_days=learning_days,
        )
        source = "ha_history"
    if history is None:
        warnings.append(
            "Home Assistant recorder history is not available; "
            "using stored Energy Planner history."
        )
        return _PlannerHistory(fallback_history, "stored")
    history.merge_current_hour(fallback_history, now=now)
    history.merge_missing_managed_sources(fallback_history, managed_entity_ids)
    return _PlannerHistory(history, source)


def _consumption_from_hourly_profile(
    *,
    hourly_profile: dict[int, float],
    target,
    min_baseline_kwh_per_hour: float,
    history_correction_percent: float,
) -> float:
    value = hourly_profile.get(target.hour, 0.0)
    value *= 1 + history_correction_percent / 100
    return max(value, min_baseline_kwh_per_hour)


def _solcast_forecast(
    hass: HomeAssistant,
    entry: ConfigEntry,
    warnings: list[str],
) -> list[SolarForecastPoint]:
    points: list[SolarForecastPoint] = []
    for entity_id in _solcast_entity_ids(hass, entry):
        state = hass.states.get(entity_id)
        if state is None:
            warnings.append(f"Optional Solcast entity is missing: {entity_id}.")
            continue
        parsed = parse_solcast_attributes(state.attributes)
        if not parsed:
            warnings.append(
                f"Optional Solcast entity has no usable forecast data: {entity_id}."
            )
        points.extend(parsed)

    return sorted(points, key=lambda point: point.start)


def _solcast_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> list[str]:
    entity_ids: list[str] = []
    configured_daily_slots: set[str] = set()

    def add(entity_id: Any) -> None:
        if isinstance(entity_id, str) and entity_id and entity_id not in entity_ids:
            entity_ids.append(entity_id)
            if daily_slot := _solcast_daily_slot(entity_id):
                configured_daily_slots.add(daily_slot)

    today_entity_id = entry.data.get(CONF_SOLCAST_TODAY_ENTITY)
    add(today_entity_id)
    add(entry.data.get(CONF_SOLCAST_TOMORROW_ENTITY))
    additional_entity_ids = entry.data.get(CONF_SOLCAST_ADDITIONAL_ENTITIES) or []
    if isinstance(additional_entity_ids, str):
        add(additional_entity_ids)
    else:
        for entity_id in additional_entity_ids:
            add(entity_id)

    for entity_id in _standard_solcast_daily_entities(
        hass,
        today_entity_id,
        configured_daily_slots,
    ):
        add(entity_id)

    return entity_ids


def _standard_solcast_daily_entities(
    hass: HomeAssistant,
    today_entity_id: Any,
    excluded_slots: set[str],
) -> list[str]:
    if not isinstance(today_entity_id, str) or not today_entity_id:
        return []
    if not today_entity_id.endswith("_forecast_today"):
        return []

    prefix = today_entity_id.removesuffix("_forecast_today")
    candidates = {
        "tomorrow": f"{prefix}_forecast_tomorrow",
        **{f"day_{day}": f"{prefix}_forecast_day_{day}" for day in range(3, 8)},
    }
    return [
        entity_id
        for slot, entity_id in candidates.items()
        if slot not in excluded_slots and hass.states.get(entity_id)
    ]


def _solcast_daily_slot(entity_id: str) -> str | None:
    match = _SOLCAST_DAILY_ENTITY_RE.search(entity_id)
    return match.group(1) if match else None


def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
    return entry.options.get(key, default)


def _history_days(entry: ConfigEntry) -> int:
    return int(
        _option(entry, CONF_HISTORY_LEARNING_DAYS, DEFAULT_HISTORY_LEARNING_DAYS)
    )


def _interval_minutes(entry: ConfigEntry) -> int:
    return int(_option(entry, CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES))


def _coordinator_update_interval(entry: ConfigEntry) -> timedelta:
    return timedelta(
        minutes=_option(
            entry,
            CONF_UPDATE_INTERVAL_MINUTES,
            DEFAULT_UPDATE_INTERVAL_MINUTES,
        )
    )


def _time_windows(values: list[dict[str, str]]) -> list[TimeWindow]:
    return [_time_window(value) for value in values]


def _time_window(value: dict[str, str]) -> TimeWindow:
    return TimeWindow(start=value["start"], end=value["end"])
