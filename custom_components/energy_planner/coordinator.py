from __future__ import annotations

import logging
import re
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
    CONF_HISTORY_CORRECTION_PERCENT,
    CONF_HISTORY_LEARNING_DAYS,
    CONF_HOME_ENERGY_ENTITY,
    CONF_INTERVAL_MINUTES,
    CONF_MANAGED_ENERGY_ENTITIES,
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
    DEFAULT_FORECAST_HORIZON_HOURS,
    DEFAULT_GRID_CHARGE_EFFICIENCY,
    DEFAULT_GRID_CHARGE_MAX_KW,
    DEFAULT_HISTORY_CORRECTION_PERCENT,
    DEFAULT_HISTORY_LEARNING_DAYS,
    DEFAULT_HISTORY_PROFILE_MARGIN_PERCENT,
    DEFAULT_HISTORY_RETENTION_DAYS,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MIN_BASELINE_KWH_PER_HOUR,
    DEFAULT_NT_WINDOWS,
    DEFAULT_SOC_EPS_KWH,
    DEFAULT_SOC_RESERVE_PERCENT,
    DEFAULT_SUN_START_REQUIRED_MINUTES,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from .ha_history import async_get_recorder_energy_history
from .history import EnergyHistory, EnergyHistoryStore
from .models import PlannerInput, PlannerResult, SolarForecastPoint, TimeWindow
from .planner import calculate_plan, generate_forecast_slots
from .sources import parse_float, parse_solcast_attributes

_LOGGER = logging.getLogger(__name__)
_MAX_CONSUMPTION_HISTORY_SENSOR_POINTS = 24 * 7
_SOLCAST_DAILY_ENTITY_RE = re.compile(
    r"(?:^|_)(?:forecast_)?(today|tomorrow|day_[3-7])$"
)


class EnergyPlannerCoordinator(DataUpdateCoordinator[PlannerResult]):
    """Coordinator for Energy Planner."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.history = EnergyHistory()
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
    ) -> None:
        """Record a changed cumulative energy source state."""
        value = parse_float(state.state)
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
            learning_days=_history_days(self.entry),
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
            },
        )

    result = calculate_plan(planner_input)
    result.forecast["history_status"] = history_status
    result.forecast["consumption_history"] = consumption_history
    result.debug["history_status"] = history_status
    if warnings:
        result.warnings = warnings + result.warnings
        if result.state == "ok":
            result.state = "warning"
    return result


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


def _record_consumption_history(
    hass: HomeAssistant,
    entry: ConfigEntry,
    history: EnergyHistory,
    now,
    warnings: list[str],
) -> None:
    home_entity_id = entry.data.get(CONF_HOME_ENERGY_ENTITY)
    if home_entity_id:
        home_value = _entity_float(hass, home_entity_id)
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

    for managed_entity_id in _managed_energy_entity_ids(entry):
        managed_value = _entity_float(hass, managed_entity_id)
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

    history = await async_get_recorder_energy_history(
        hass,
        home_entity_id=home_entity_id,
        managed_entity_ids=_managed_energy_entity_ids(entry),
        now=now,
        learning_days=learning_days,
    )
    if history is None:
        warnings.append(
            "Home Assistant recorder history is not available; "
            "using stored Energy Planner history."
        )
        return _PlannerHistory(fallback_history, "stored")
    return _PlannerHistory(history, "ha_history")


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
    configured = bool(
        entry.data.get(CONF_SOLCAST_TODAY_ENTITY)
        or entry.data.get(CONF_SOLCAST_TOMORROW_ENTITY)
        or entry.data.get(CONF_SOLCAST_ADDITIONAL_ENTITIES)
    )
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

    if not configured:
        warnings.append("No Solcast forecast entities are configured.")
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


def _managed_energy_entity_ids(entry: ConfigEntry) -> list[str]:
    raw_entity_ids = entry.data.get(CONF_MANAGED_ENERGY_ENTITIES) or []
    if isinstance(raw_entity_ids, str):
        return [raw_entity_ids] if raw_entity_ids else []
    return [
        entity_id
        for entity_id in raw_entity_ids
        if isinstance(entity_id, str) and entity_id
    ]


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
