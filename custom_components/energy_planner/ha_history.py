from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

from .history import EnergyHistory, HourlyCumulativeSample
from .sources import parse_float


async def async_get_recorder_energy_history(
    hass: HomeAssistant,
    *,
    home_entity_id: str,
    managed_entity_id: str | None,
    now: datetime,
    learning_days: int,
) -> EnergyHistory | None:
    """Fetch Node-RED-compatible hourly energy history from HA recorder."""
    try:
        from homeassistant.components.recorder import history as recorder_history
        from homeassistant.helpers.recorder import get_instance
    except ImportError:
        return None

    entity_ids = [home_entity_id]
    if managed_entity_id:
        entity_ids.append(managed_entity_id)

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
    managed_samples = (
        _samples_from_states(states_by_entity.get(managed_entity_id, []))
        if managed_entity_id
        else []
    )
    if not home_samples:
        return None
    history = EnergyHistory.from_cumulative_history_samples(
        home_samples=home_samples,
        managed_samples=managed_samples,
    )
    return history if history.buckets else None


def _samples_from_states(
    states: list[State | dict[str, Any]],
) -> list[HourlyCumulativeSample]:
    samples: list[HourlyCumulativeSample] = []
    for state in states:
        value = parse_float(_state_value(state))
        reset_time = _state_reset_time(state)
        if value is None or reset_time is None:
            continue
        samples.append(
            HourlyCumulativeSample(
                reset_time=dt_util.as_local(reset_time),
                value=value,
            )
        )
    return samples


def _state_value(state: State | dict[str, Any]) -> Any:
    if isinstance(state, State):
        return state.state
    return state.get("state")


def _state_reset_time(state: State | dict[str, Any]) -> datetime | None:
    if isinstance(state, State):
        reset_time = _parse_datetime(state.attributes.get("last_reset"))
        return reset_time or state.last_updated

    attributes = state.get("attributes")
    if isinstance(attributes, dict):
        reset_time = _parse_datetime(attributes.get("last_reset"))
        if reset_time:
            return reset_time
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
