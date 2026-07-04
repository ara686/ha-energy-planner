from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.energy_planner.ha_history import (
    async_get_recorder_energy_history,
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
