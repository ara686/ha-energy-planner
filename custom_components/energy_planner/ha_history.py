from __future__ import annotations

from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, UnitOfEnergy
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .history import CumulativeEnergySample, EnergyHistory
from .sources import parse_float
from .units import energy_value_to_kwh

_KWH_STATISTICS_UNITS = {
    EnergyConverter.UNIT_CLASS: UnitOfEnergy.KILO_WATT_HOUR,
}


async def async_get_recorder_energy_history(
    hass: HomeAssistant,
    *,
    home_entity_id: str,
    managed_entity_ids: list[str],
    now: datetime,
    learning_days: int,
) -> EnergyHistory | None:
    """Fetch cumulative energy source history from HA recorder."""
    try:
        from homeassistant.components.recorder import history as recorder_history
        from homeassistant.helpers.recorder import get_instance
    except ImportError:
        return None

    entity_ids = [home_entity_id, *managed_entity_ids]

    start = now - timedelta(days=max(1, learning_days))
    try:
        states_by_entity = await get_instance(hass).async_add_executor_job(
            partial(
                recorder_history.get_significant_states,
                hass,
                start_time=start,
                end_time=now,
                entity_ids=entity_ids,
                filters=None,
                include_start_time_state=True,
                significant_changes_only=False,
                minimal_response=False,
                no_attributes=False,
                compressed_state_format=False,
            )
        )
    except (KeyError, RuntimeError, ValueError):
        return None

    home_samples = _samples_from_states(
        states_by_entity.get(home_entity_id, []),
        default_unit=_entity_unit(hass, home_entity_id),
    )
    managed_samples_by_source = {
        entity_id: _samples_from_states(
            states_by_entity.get(entity_id, []),
            default_unit=_entity_unit(hass, entity_id),
        )
        for entity_id in managed_entity_ids
    }
    if not home_samples:
        return None
    history = EnergyHistory.from_cumulative_energy_samples(
        home_samples=home_samples,
        managed_samples_by_source=managed_samples_by_source,
        home_source_id=home_entity_id,
    )
    return history if history.buckets else None


async def async_get_recorder_energy_statistics(
    hass: HomeAssistant,
    *,
    home_entity_id: str,
    managed_entity_ids: list[str],
    now: datetime,
    learning_days: int,
) -> EnergyHistory | None:
    """Fetch hourly energy changes from Home Assistant long-term statistics."""
    try:
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )
        from homeassistant.helpers.recorder import get_instance
    except ImportError:
        return None

    entity_ids = {home_entity_id, *managed_entity_ids}
    start = dt_util.as_utc(now - timedelta(days=max(1, learning_days)))
    end = dt_util.as_utc(now)
    try:
        rows_by_entity = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            start,
            end,
            entity_ids,
            "hour",
            _KWH_STATISTICS_UNITS,
            {"change"},
        )
    except (KeyError, RuntimeError, TypeError, ValueError):
        return None

    home_changes = _hourly_changes_from_statistics(
        rows_by_entity.get(home_entity_id, [])
    )
    if not home_changes:
        return None
    history = EnergyHistory.from_hourly_energy_changes(
        home_source_id=home_entity_id,
        home_changes=home_changes,
        managed_changes_by_source={
            entity_id: _hourly_changes_from_statistics(
                rows_by_entity.get(entity_id, [])
            )
            for entity_id in managed_entity_ids
        },
    )
    return history if history.buckets else None


def _hourly_changes_from_statistics(rows: list[dict[str, Any]]) -> dict[str, float]:
    changes: dict[str, float] = {}
    for row in rows:
        start = row.get("start")
        value = parse_float(row.get("change"))
        if value is None or value < 0 or not isinstance(start, int | float):
            continue
        timestamp = dt_util.as_local(dt_util.utc_from_timestamp(start))
        key = timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
        changes[key] = value
    return changes


def _samples_from_states(
    states: list[State | dict[str, Any]],
    *,
    default_unit: str | None,
) -> list[CumulativeEnergySample]:
    samples: list[CumulativeEnergySample] = []
    for state in states:
        value = energy_value_to_kwh(
            _state_value(state),
            _state_unit(state) or default_unit,
        )
        timestamp = _state_timestamp(state)
        if value is None or timestamp is None:
            continue
        samples.append(
            CumulativeEnergySample(
                timestamp=dt_util.as_local(timestamp),
                value=value,
            )
        )
    return samples


def _state_value(state: State | dict[str, Any]) -> Any:
    if isinstance(state, State):
        return state.state
    return state.get("state")


def _state_unit(state: State | dict[str, Any]) -> str | None:
    attributes = (
        state.attributes if isinstance(state, State) else state.get("attributes")
    )
    if not isinstance(attributes, dict):
        return None
    unit = attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    return unit if isinstance(unit, str) else None


def _entity_unit(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    if state is None:
        return None
    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
    return unit if isinstance(unit, str) else None


def _state_timestamp(state: State | dict[str, Any]) -> datetime | None:
    if isinstance(state, State):
        return state.last_updated
    return _parse_datetime(
        state.get("last_updated")
        or state.get("last_changed")
        or state.get("last_reported")
    )


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
