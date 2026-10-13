"""Regressions for reserves carried from an elapsed evening into future nights."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_planner.coordinator import (
    _add_managed_soc_forecast,
    _managed_solar_budget,
)
from custom_components.energy_planner.models import (
    ForecastSlot,
    PlannerInput,
    TimeWindow,
)
from custom_components.energy_planner.planner import (
    calculate_plan,
    calculate_soc_forecast,
)


def night_input(
    *,
    battery_soc: float = 100,
    second_sun_hour: int = 8,
    now: datetime | None = None,
) -> PlannerInput:
    """Two nights that fit in the battery but cross the old 49% fixed lock."""
    now = now or datetime(2026, 10, 13, 17, tzinfo=ZoneInfo("Europe/Prague"))
    slots = []
    for index in range(48 * 12):
        start = (now.astimezone(UTC) + timedelta(minutes=5 * index)).astimezone(
            now.tzinfo
        )
        sun_hour = (
            second_sun_hour if start.date() >= now.date() + timedelta(days=2) else 8
        )
        solar = 3 if sun_hour <= start.hour < 17 else 0
        consumption = (
            1.2
            if 17 <= start.hour < 22
            else 1
            if start.hour >= 22 or start.hour < 4
            else 0.5
        )
        slots.append(ForecastSlot(start, solar / 12, consumption / 12))
    return PlannerInput(
        now=now,
        battery_soc=battery_soc,
        battery_capacity_kwh=20,
        battery_min_soc=20,
        slots=slots,
        nt_windows=[TimeWindow("17:00", "19:00"), TimeWindow("22:00", "04:00")],
        charge_window=TimeWindow("22:00", "04:00"),
        grid_charging_enabled=False,
        interval_minutes=5,
        forecast_horizon_hours=48,
    )


def test_both_nights_use_available_energy_below_initial_lock():
    data = night_input()
    result = calculate_plan(data)
    assert result.plan["lock_soc"] == 49
    planned = result.plan["soc_forecast_planned"]["points"]
    passive = result.plan["soc_forecast"]["points"]
    assert planned == passive
    assert sum(p["grid_import_kwh"] for p in planned) == 0
    for day in (14, 15):
        night = [
            p for p in planned if datetime.fromisoformat(p["timestamp"]).day == day
        ]
        assert min(p["soc_percent"] for p in night) == 30
    assert result.plan["charged_kwh_total_at_target"] == 0


def test_scarce_night_still_preserves_remaining_morning_demand():
    data = night_input(battery_soc=75)
    result = calculate_plan(data)
    points = result.plan["soc_forecast_planned"]["points"]
    assert sum(p["grid_import_kwh"] for p in points if p["is_nt"]) > 0
    assert sum(p["grid_import_kwh"] for p in points if not p["is_nt"]) == 0
    morning = next(p for p in points if p["timestamp"].startswith("2026-10-14T07:55"))
    assert morning["soc_percent"] == 21
    assert min(p["soc_percent"] for p in points) >= data.battery_min_soc


def test_active_grid_charge_target_does_not_cycle_released_reserve():
    data = replace(night_input(battery_soc=75), grid_charging_enabled=True)
    result = calculate_plan(data)
    # At 22:00 the battery has 9 kWh, so only 0.8 kWh is needed for 49%.
    assert result.plan["target_soc"] == 49
    assert result.plan["charged_kwh_total_at_target"] == pytest.approx(0.8)
    for point in result.plan["soc_forecast_planned"]["points"]:
        if point["is_charge_window"]:
            assert point["battery_kwh"] + 0.001 >= min(point["battery_start_kwh"], 9.8)
            if point["battery_start_kwh"] >= 9.8:
                assert point["grid_charge_kwh"] == 0


def test_second_night_uses_its_own_later_solar_start():
    data = night_input(battery_soc=75, second_sun_hour=12)
    points = calculate_plan(data).plan["soc_forecast_planned"]["points"]
    # First morning requires 2 kWh (31% reserve), second requires 4 (41%).
    for day, expected in ((14, 31), (15, 41)):
        point = next(
            p for p in points if p["timestamp"].startswith(f"2026-10-{day}T03:55")
        )
        assert point["soc_percent"] == expected
    assert sum(p["grid_import_kwh"] for p in points if not p["is_nt"]) == 0


@pytest.mark.parametrize("sun_hours", [(), (9,)])
def test_no_sustained_solar_preserves_remaining_known_deficit(sun_hours):
    data = night_input(battery_soc=75)
    data = replace(
        data,
        sun_start_required_minutes=120,
        slots=[
            replace(
                s,
                solar_kwh=0.05 if s.start.hour in sun_hours else 0,
                consumption_kwh=0.025,
            )
            for s in data.slots
        ],
    )
    result = calculate_plan(data)
    points = result.plan["soc_forecast_planned"]["points"]
    # A single sunny hour cannot end a two-hour solar-start requirement.
    assert sum(p["grid_import_kwh"] for p in points if p["is_nt"]) > 0
    assert sum(p["grid_import_kwh"] for p in points if not p["is_nt"]) == 0
    assert min(p["soc_percent"] for p in points) >= 20


@pytest.mark.parametrize("date", [(2026, 3, 28), (2026, 10, 24)])
def test_night_reserve_across_dst_matches_passive_when_energy_suffices(date):
    data = night_input(now=datetime(*date, 17, tzinfo=ZoneInfo("Europe/Prague")))
    result = calculate_plan(data)
    assert (
        result.plan["soc_forecast_planned"]["points"]
        == result.plan["soc_forecast"]["points"]
    )
    assert result.plan["vt_grid_import_kwh_at_target"] == 0


def test_managed_forecast_and_admission_use_same_dynamic_reserve(hass):
    data = night_input()
    result = calculate_plan(data)
    _add_managed_soc_forecast(
        planner_input=data, now=data.now, allocations=[], result=result
    )
    assert (
        result.plan["soc_forecast_with_managed"]["points"]
        == result.plan["soc_forecast_planned"]["points"]
    )
    budget = _managed_solar_budget(data, result)
    start = next(s.start for s in data.slots if s.start.hour == 2)
    accepted = budget.add(start, 5)
    # Only the ~1.8 kWh above the 21% morning reserve may be allocated.
    assert 1.7 < accepted < 1.9
    managed = calculate_soc_forecast(
        data, managed_consumption_by_slot={start: accepted}, dynamic_nt_reserve=True
    )
    assert sum(p.grid_import_kwh for p in managed.points) == 0
    assert min(p.soc_percent for p in managed.points) >= 20
