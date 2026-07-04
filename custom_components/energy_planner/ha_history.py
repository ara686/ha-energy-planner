from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .history import CumulativeEnergySample, EnergyHistory
from .sources import parse_float


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
            recorder_history.get_significant_states,
            hass,
            start,
            now,
            entity_ids,
            None,
            True,
            False,
            False,
            False,
            False,
        )
    except (KeyError, RuntimeError, ValueError):
        return None

    home_samples = _samples_from_states(states_by_entity.get(home_entity_id, []))
    managed_samples_by_source = {
        entity_id: _samples_from_states(states_by_entity.get(entity_id, []))
        for entity_id in managed_entity_ids
    }
    if not home_samples:
        return None
    history = EnergyHistory.from_cumulative_energy_samples(
        home_samples=home_samples,
        managed_samples_by_source=managed_samples_by_source,
    )
    return history if history.buckets else None


def _samples_from_states(
    states: list[State | dict[str, Any]],
) -> list[CumulativeEnergySample]:
    samples: list[CumulativeEnergySample] = []
    for state in states:
        value = parse_float(_state_value(state))
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
