from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CAPACITY_ENTITY,
    CONF_BATTERY_MIN_SOC_ENTITY,
    CONF_BATTERY_SOC_ENTITY,
    CONF_CHARGE_WINDOW,
    CONF_FORECAST_HORIZON_HOURS,
    CONF_GRID_CHARGE_EFFICIENCY,
    CONF_GRID_CHARGE_MAX_KW,
    CONF_HOME_ENERGY_HOURLY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_HOURLY_ENTITY,
    CONF_MIN_BASELINE_KWH_PER_HOUR,
    CONF_NT_WINDOWS,
    CONF_SOC_EPS_KWH,
    CONF_SOC_RESERVE_PERCENT,
    CONF_SOLCAST_TODAY_ENTITY,
    CONF_SOLCAST_TOMORROW_ENTITY,
    CONF_SUN_START_REQUIRED_MINUTES,
    DEFAULT_CHARGE_WINDOW,
    DEFAULT_FORECAST_HORIZON_HOURS,
    DEFAULT_GRID_CHARGE_EFFICIENCY,
    DEFAULT_GRID_CHARGE_MAX_KW,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
    DEFAULT_NT_WINDOWS,
    DEFAULT_SOC_EPS_KWH,
    DEFAULT_SOC_RESERVE_PERCENT,
    DEFAULT_SUN_START_REQUIRED_MINUTES,
    DOMAIN,
)
from .models import PlannerInput, PlannerResult, SolarForecastPoint, TimeWindow
from .planner import calculate_plan, generate_forecast_slots
from .sources import parse_float, parse_solcast_attributes

_LOGGER = logging.getLogger(__name__)


class EnergyPlannerCoordinator(DataUpdateCoordinator[PlannerResult]):
    """Coordinator for Energy Planner."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=_option(entry, CONF_INTERVAL_MINUTES, DEFAULT_INTERVAL_MINUTES)
            ),
        )

    async def _async_update_data(self) -> PlannerResult:
        """Fetch and calculate planner data."""
        result = build_planner_result(self.hass, self.entry)
        if result.warnings:
            _LOGGER.warning(
                "Energy Planner update completed with warnings: %s",
                result.warnings,
            )
        return result


def build_planner_result(hass: HomeAssistant, entry: ConfigEntry) -> PlannerResult:
    """Build a planner result from configured Home Assistant entities."""
    now = dt_util.utcnow()
    planner_input, warnings = _build_planner_input(hass, entry, now)
    if planner_input is None:
        return PlannerResult(
            state="insufficient_data",
            updated=now,
            warnings=warnings,
        )

    result = calculate_plan(planner_input)
    if warnings:
        result.warnings = warnings + result.warnings
        if result.state == "ok":
            result.state = "warning"
    return result


def _build_planner_input(
    hass: HomeAssistant,
    entry: ConfigEntry,
    now,
) -> tuple[PlannerInput | None, list[str]]:
    warnings: list[str] = []

    battery_soc = _required_float(hass, entry, CONF_BATTERY_SOC_ENTITY, warnings)
    battery_capacity = _required_float(
        hass, entry, CONF_BATTERY_CAPACITY_ENTITY, warnings
    )
    battery_min_soc = _required_float(
        hass, entry, CONF_BATTERY_MIN_SOC_ENTITY, warnings
    )
    home_energy_hourly = _required_float(
        hass, entry, CONF_HOME_ENERGY_HOURLY_ENTITY, warnings
    )

    if (
        battery_soc is None
        or battery_capacity is None
        or battery_min_soc is None
        or home_energy_hourly is None
    ):
        return None, warnings

    managed_energy_hourly = _optional_float(
        hass,
        entry,
        CONF_MANAGED_ENERGY_HOURLY_ENTITY,
        warnings,
    )
    base_consumption_kwh_per_hour = max(
        home_energy_hourly - (managed_energy_hourly or 0.0),
        _option(
            entry,
            CONF_MIN_BASELINE_KWH_PER_HOUR,
            DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
        ),
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
        consumption_kwh_per_hour=base_consumption_kwh_per_hour,
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


def _optional_float(
    hass: HomeAssistant,
    entry: ConfigEntry,
    key: str,
    warnings: list[str],
) -> float | None:
    entity_id = entry.data.get(key)
    if not entity_id:
        return None
    value = _entity_float(hass, entity_id)
    if value is None:
        warnings.append(f"Optional entity has no valid numeric state: {entity_id}.")
    return value


def _entity_float(hass: HomeAssistant, entity_id: str) -> float | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    return parse_float(state.state)


def _solcast_forecast(
    hass: HomeAssistant,
    entry: ConfigEntry,
    warnings: list[str],
) -> list[SolarForecastPoint]:
    points: list[SolarForecastPoint] = []
    configured = False
    for key in (CONF_SOLCAST_TODAY_ENTITY, CONF_SOLCAST_TOMORROW_ENTITY):
        entity_id = entry.data.get(key)
        if not entity_id:
            continue
        configured = True
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

    if not configured:
        warnings.append("No Solcast forecast entities are configured.")
    return sorted(points, key=lambda point: point.start)


def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
    return entry.options.get(key, default)


def _time_windows(values: list[dict[str, str]]) -> list[TimeWindow]:
    return [_time_window(value) for value in values]


def _time_window(value: dict[str, str]) -> TimeWindow:
    return TimeWindow(start=value["start"], end=value["end"])
