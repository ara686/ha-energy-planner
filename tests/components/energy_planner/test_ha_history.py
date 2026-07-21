from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.energy_planner.ha_history import (
    async_get_recorder_energy_history,
    async_get_recorder_energy_statistics,
)


async def test_recorder_history_uses_keyword_arguments(hass, monkeypatch):
    now = datetime(2026, 7, 3, 12, 0)
    captured: dict[str, object] = {}

    def get_significant_states(hass_arg, **kwargs):
        captured["hass"] = hass_arg
        captured["kwargs"] = kwargs
        return {
            "sensor.home_energy_total": [
                {
                    "state": "10",
                    "last_updated": (now - timedelta(hours=2)).isoformat(),
                },
                {
                    "state": "11.5",
                    "last_updated": (now - timedelta(hours=1)).isoformat(),
                },
            ]
        }

    class RecorderInstance:
        async def async_add_executor_job(self, target):
            return target()

    monkeypatch.setattr(
        "homeassistant.components.recorder.history.get_significant_states",
        get_significant_states,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance",
        lambda _hass: RecorderInstance(),
    )

    history = await async_get_recorder_energy_history(
        hass,
        home_entity_id="sensor.home_energy_total",
        managed_entity_ids=[],
        now=now,
        learning_days=3,
    )

    assert history is not None
    assert captured["hass"] is hass
    assert captured["kwargs"] == {
        "start_time": now - timedelta(days=3),
        "end_time": now,
        "entity_ids": ["sensor.home_energy_total"],
        "filters": None,
        "include_start_time_state": True,
        "significant_changes_only": False,
        "minimal_response": False,
        "no_attributes": False,
        "compressed_state_format": False,
    }


async def test_recorder_statistics_are_preferred_as_hourly_changes(
    hass,
    monkeypatch,
):
    now = datetime(2026, 7, 3, 12, 0)
    start_timestamp = (now - timedelta(hours=2)).timestamp()
    captured: dict[str, object] = {}

    def statistics_during_period(*args):
        captured["args"] = args
        return {
            "sensor.home_energy_total": [{"start": start_timestamp, "change": 1.5}],
            "sensor.ev_energy_total": [{"start": start_timestamp, "change": 0.5}],
        }

    class RecorderInstance:
        async def async_add_executor_job(self, target, *args):
            return target(*args)

    monkeypatch.setattr(
        "homeassistant.components.recorder.statistics.statistics_during_period",
        statistics_during_period,
    )
    monkeypatch.setattr(
        "homeassistant.helpers.recorder.get_instance",
        lambda _hass: RecorderInstance(),
    )

    history = await async_get_recorder_energy_statistics(
        hass,
        home_entity_id="sensor.home_energy_total",
        managed_entity_ids=["sensor.ev_energy_total"],
        now=now,
        learning_days=3,
    )

    assert history is not None
    args = captured["args"]
    assert args[0] is hass
    assert args[3] == {
        "sensor.home_energy_total",
        "sensor.ev_energy_total",
    }
    assert args[4] == "hour"
    assert args[6] == {"change"}
    bucket = next(iter(history.buckets.values()))
    assert bucket.home_kwh == 1.5
    assert bucket.managed_kwh == 0.5
