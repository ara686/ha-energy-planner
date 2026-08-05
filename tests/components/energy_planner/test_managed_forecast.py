from __future__ import annotations

from datetime import date, datetime, timedelta

from custom_components.energy_planner.managed_forecast import (
    build_managed_demand_schedule,
)
from custom_components.energy_planner.models import ForecastSlot


def _slots(start: datetime, count: int) -> list[ForecastSlot]:
    return [
        ForecastSlot(
            start=start + timedelta(hours=index),
            solar_kwh=0,
            consumption_kwh=0,
        )
        for index in range(count)
    ]


def test_managed_demand_uses_hourly_profiles_and_uniform_fallback():
    target_date = date(2026, 7, 22)
    start = datetime(2026, 7, 22, 0, 0)

    schedule = build_managed_demand_schedule(
        slots=_slots(start, 24),
        target_date=target_date,
        reference=start,
        interval_minutes=60,
        expected_by_source={"boiler": 6, "ev": 24},
        hourly_profiles={"boiler": {12: 2, 13: 1}},
    )

    assert schedule.expected_kwh == 30
    assert schedule.scheduled_kwh == 30
    assert schedule.scheduled_by_source == {"boiler": 6, "ev": 24}
    assert schedule.fallback_source_ids == ["ev"]
    assert schedule.energy_by_slot[start + timedelta(hours=12)] == 5
    assert schedule.energy_by_slot[start + timedelta(hours=13)] == 3
    assert schedule.energy_by_slot[start] == 1


def test_managed_demand_does_not_compress_full_day_into_partial_horizon():
    target_date = date(2026, 7, 22)
    start = datetime(2026, 7, 22, 0, 0)

    schedule = build_managed_demand_schedule(
        slots=_slots(start, 12),
        target_date=target_date,
        reference=start,
        interval_minutes=60,
        expected_by_source={"ev": 24},
        hourly_profiles={},
    )

    assert schedule.expected_kwh == 24
    assert schedule.scheduled_kwh == 12
    assert schedule.scheduled_by_source == {"ev": 12}


def test_managed_demand_handles_invalid_interval_without_dividing_by_zero():
    target_date = date(2026, 7, 22)
    start = datetime(2026, 7, 22, 0, 0)

    schedule = build_managed_demand_schedule(
        slots=_slots(start, 1),
        target_date=target_date,
        reference=start,
        interval_minutes=0,
        expected_by_source={"ev": 8},
        hourly_profiles={},
    )

    assert schedule.expected_kwh == 8
    assert schedule.scheduled_kwh == 0
    assert schedule.energy_by_slot == {}
    assert schedule.fallback_source_ids == ["ev"]
