from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.energy_planner import planner as planner_module
from custom_components.energy_planner.models import (
    ForecastSlot,
    PlannerInput,
    SolarForecastPoint,
    TimeWindow,
)
from custom_components.energy_planner.planner import (
    calculate_plan,
    generate_forecast_slots,
)


def _slots(
    start: datetime,
    count: int,
    *,
    solar_kwh: float,
    consumption_kwh: float,
    step_minutes: int = 60,
) -> list[ForecastSlot]:
    return [
        ForecastSlot(
            start=start + timedelta(minutes=step_minutes * index),
            solar_kwh=solar_kwh,
            consumption_kwh=consumption_kwh,
        )
        for index in range(count)
    ]


def _input(
    *,
    now: datetime,
    slots: list[ForecastSlot],
    battery_soc: float = 80.0,
    battery_capacity_kwh: float = 20.0,
    battery_min_soc: float = 20.0,
    nt_windows: list[TimeWindow] | None = None,
    charge_window: TimeWindow | None = None,
    interval_minutes: int = 60,
    forecast_horizon_hours: int = 36,
) -> PlannerInput:
    return PlannerInput(
        now=now,
        battery_soc=battery_soc,
        battery_capacity_kwh=battery_capacity_kwh,
        battery_min_soc=battery_min_soc,
        slots=slots,
        nt_windows=nt_windows or [TimeWindow(start="22:00", end="04:00")],
        charge_window=charge_window or TimeWindow(start="22:00", end="04:00"),
        interval_minutes=interval_minutes,
        grid_charge_max_kw=10.0,
        grid_charge_efficiency=1.0,
        forecast_horizon_hours=forecast_horizon_hours,
    )


def test_empty_slots_return_insufficient_data():
    result = calculate_plan(
        _input(
            now=datetime(2026, 7, 3, 12, 0),
            slots=[],
        )
    )

    assert result.state == "insufficient_data"
    assert result.plan["target_soc"] == 80.0
    assert result.plan["soc_forecast"]["points"] == []
    assert "No forecast slots available." in result.warnings


def test_generate_forecast_slots_splits_solcast_periods():
    now = datetime(2026, 7, 3, 12, 0)

    slots = generate_forecast_slots(
        now=now,
        horizon_hours=1,
        interval_minutes=15,
        solar_forecast=[
            SolarForecastPoint(start=now, solar_kwh=2.0, period_minutes=60)
        ],
        consumption_kwh_per_hour=1.2,
    )

    assert len(slots) == 4
    assert [slot.solar_kwh for slot in slots] == [0.5, 0.5, 0.5, 0.5]
    assert [slot.consumption_kwh for slot in slots] == [0.3, 0.3, 0.3, 0.3]
    assert [slot.solar_coverage for slot in slots] == [1.0, 1.0, 1.0, 1.0]


def test_generate_forecast_slots_reports_missing_solar_coverage():
    now = datetime(2026, 7, 3, 12, 0)

    slots = generate_forecast_slots(
        now=now,
        horizon_hours=2,
        interval_minutes=60,
        solar_forecast=[SolarForecastPoint(start=now, solar_kwh=1.0)],
        consumption_kwh_per_hour=0,
    )

    assert [slot.solar_coverage for slot in slots] == [1.0, 0.0]


def test_generate_forecast_slots_aligns_start_to_next_interval():
    now = datetime(2026, 7, 3, 12, 2, 43)

    slots = generate_forecast_slots(
        now=now,
        horizon_hours=1,
        interval_minutes=5,
        solar_forecast=[],
        consumption_kwh_per_hour=0.6,
    )

    assert slots[0].start == datetime(2026, 7, 3, 12, 5)
    assert all(slot.start.second == 0 for slot in slots)


def test_generate_forecast_slots_accepts_consumption_profile():
    now = datetime(2026, 7, 3, 12, 0)

    slots = generate_forecast_slots(
        now=now,
        horizon_hours=2,
        interval_minutes=60,
        solar_forecast=[],
        consumption_kwh_per_hour=lambda slot_start: (
            1.0 if slot_start.hour == 12 else 2.0
        ),
    )

    assert [slot.consumption_kwh for slot in slots] == [1.0, 2.0]


def test_generate_forecast_slots_keeps_both_fall_back_hours():
    timezone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 10, 24, 0, 0, tzinfo=timezone)
    start_utc = now.astimezone(UTC)
    solar_forecast = [
        SolarForecastPoint(
            start=(start_utc + timedelta(hours=index)).astimezone(timezone),
            solar_kwh=2,
            period_minutes=60,
        )
        for index in range(49)
    ]

    slots = generate_forecast_slots(
        now=now,
        horizon_hours=48,
        interval_minutes=60,
        solar_forecast=solar_forecast,
        consumption_kwh_per_hour=0,
    )

    repeated_hours = [
        slot.start
        for slot in slots
        if slot.start.date().isoformat() == "2026-10-25" and slot.start.hour == 2
    ]
    assert len(slots) == 49
    assert len(repeated_hours) == 2
    assert {timestamp.utcoffset() for timestamp in repeated_hours} == {
        timedelta(hours=1),
        timedelta(hours=2),
    }
    assert all(slot.solar_kwh == 2 for slot in slots)
    assert all(slot.solar_coverage == 1 for slot in slots)


def test_soc_forecast_contains_24h_point_and_longer_horizon():
    now = datetime(2026, 7, 3, 0, 0)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(now, 36, solar_kwh=0.0, consumption_kwh=0.2),
            battery_soc=90.4,
            battery_capacity_kwh=13,
            forecast_horizon_hours=36,
        )
    )

    assert result.state == "ok"
    assert (
        result.plan["soc_forecast_24h"]["timestamp"]
        == (now + timedelta(hours=24)).isoformat()
    )
    assert len(result.plan["soc_forecast"]["points"]) == 36
    assert isinstance(result.plan["soc_forecast_24h"]["soc_percent"], int)
    assert isinstance(result.plan["soc_at_forecast_horizon"], int)
    assert all(
        isinstance(point["soc_percent"], int)
        for point in result.plan["soc_forecast"]["points"]
    )
    assert result.plan["soc_at_forecast_horizon"] < 90


def test_soc_forecast_uses_battery_in_nt_until_minimum_soc():
    now = datetime(2026, 7, 3, 23, 0)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(now, 24, solar_kwh=0.0, consumption_kwh=1.0),
            battery_soc=50,
            battery_capacity_kwh=10,
            charge_window=TimeWindow(start="10:00", end="11:00"),
            forecast_horizon_hours=24,
        )
    )

    first_point = result.plan["soc_forecast"]["points"][0]
    assert first_point["is_nt"] is True
    assert first_point["grid_import_kwh"] == 0.0
    assert first_point["battery_kwh"] == 4.0
    assert result.plan["target_soc"] == 100.0
    assert result.plan["vt_grid_import_kwh_at_target"] == 7.0
    assert result.plan["charged_kwh_total_at_target"] == 8.0


def test_equal_start_end_window_is_empty():
    now = datetime(2026, 7, 3, 22, 0)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(now, 2, solar_kwh=0.0, consumption_kwh=1.0),
            nt_windows=[TimeWindow(start="22:00", end="22:00")],
            charge_window=TimeWindow(start="23:00", end="23:30"),
            forecast_horizon_hours=24,
        )
    )

    assert result.plan["soc_forecast"]["points"][0]["is_nt"] is False


def test_window_start_normalizes_nonexistent_dst_time():
    timezone = ZoneInfo("Europe/Prague")
    timestamp = datetime(2026, 3, 29, 1, 30, tzinfo=timezone)

    assert planner_module._next_window_start(
        timestamp,
        TimeWindow(start="02:30", end="04:00"),
    ) == datetime(2026, 3, 29, 3, 30, tzinfo=timezone)


def test_lock_start_uses_current_nt_window_start_not_next_slot():
    now = datetime(2026, 7, 3, 23, 16, 58)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(
                datetime(2026, 7, 3, 23, 20),
                24,
                solar_kwh=0.0,
                consumption_kwh=0.2,
                step_minutes=5,
            ),
            nt_windows=[TimeWindow(start="22:00", end="04:00")],
            interval_minutes=5,
            forecast_horizon_hours=24,
        )
    )

    assert result.plan["lock_start"] == datetime(2026, 7, 3, 22, 0).isoformat()


def test_lock_start_uses_next_nt_window_start_when_outside_window():
    now = datetime(2026, 7, 3, 21, 16, 58)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(
                datetime(2026, 7, 3, 21, 20),
                24,
                solar_kwh=0.0,
                consumption_kwh=0.2,
                step_minutes=5,
            ),
            nt_windows=[TimeWindow(start="22:00", end="04:00")],
            interval_minutes=5,
            forecast_horizon_hours=24,
        )
    )

    assert result.plan["lock_start"] == datetime(2026, 7, 3, 22, 0).isoformat()


def test_lock_start_uses_previous_day_start_after_midnight_in_crossing_window():
    now = datetime(2026, 7, 4, 2, 16, 58)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(
                datetime(2026, 7, 4, 2, 20),
                24,
                solar_kwh=0.0,
                consumption_kwh=0.2,
                step_minutes=5,
            ),
            nt_windows=[TimeWindow(start="22:00", end="04:00")],
            interval_minutes=5,
            forecast_horizon_hours=24,
        )
    )

    assert result.plan["lock_start"] == datetime(2026, 7, 3, 22, 0).isoformat()


def test_charge_to_soc_covers_future_vt_deficit_from_charge_window():
    now = datetime(2026, 7, 3, 22, 0)
    slots = [
        ForecastSlot(start=now, solar_kwh=0.0, consumption_kwh=0.0),
        ForecastSlot(
            start=now + timedelta(hours=1), solar_kwh=0.0, consumption_kwh=0.0
        ),
        ForecastSlot(
            start=now + timedelta(hours=6), solar_kwh=0.0, consumption_kwh=2.0
        ),
        ForecastSlot(
            start=now + timedelta(hours=7), solar_kwh=0.0, consumption_kwh=2.0
        ),
    ]

    result = calculate_plan(
        _input(
            now=now,
            slots=slots,
            battery_soc=20,
            battery_capacity_kwh=10,
            battery_min_soc=20,
            forecast_horizon_hours=24,
        )
    )

    assert result.state == "warning"
    assert result.plan["charge_to_soc"] >= 59.8
    assert result.plan["target_soc"] >= 60.0
    assert result.plan["vt_grid_import_kwh_at_target"] == 0.0
    assert result.plan["charged_kwh_total_at_target"] > 0.0


def test_unused_surplus_is_recorded_when_battery_is_full():
    now = datetime(2026, 7, 3, 12, 0)
    result = calculate_plan(
        _input(
            now=now,
            slots=_slots(now, 24, solar_kwh=5.0, consumption_kwh=0.0),
            battery_soc=90,
            battery_capacity_kwh=10,
            forecast_horizon_hours=24,
        )
    )

    assert result.plan["first_full_time"] == now.isoformat()
    assert result.plan["unused_surplus_kwh_total"] > 0.0
    assert (
        0.0
        < result.plan["unused_surplus_kwh"]
        < result.plan["unused_surplus_kwh_total"]
    )
    assert result.plan["soc_at_forecast_horizon"] == 100.0


def test_tomorrow_surplus_requires_a_complete_calendar_day_forecast():
    now = datetime(2026, 7, 3, 0, 0, tzinfo=ZoneInfo("Europe/Prague"))
    slots = _slots(now, 48, solar_kwh=2, consumption_kwh=0)

    complete = calculate_plan(
        _input(
            now=now,
            slots=slots,
            battery_soc=100,
            forecast_horizon_hours=48,
        )
    )

    assert complete.plan["unused_surplus_tomorrow_kwh"] == 48
    assert complete.plan["unused_surplus_tomorrow_coverage_percent"] == 100
    assert complete.plan["unused_surplus_tomorrow_solar_coverage_percent"] == 100

    incomplete_slots = list(slots)
    incomplete_slots[24] = ForecastSlot(
        start=incomplete_slots[24].start,
        solar_kwh=2,
        consumption_kwh=0,
        solar_coverage=0,
    )
    incomplete = calculate_plan(
        _input(
            now=now,
            slots=incomplete_slots,
            battery_soc=100,
            forecast_horizon_hours=48,
        )
    )

    assert incomplete.plan["unused_surplus_tomorrow_kwh"] is None
    assert incomplete.plan["unused_surplus_tomorrow_coverage_percent"] == 100
    assert incomplete.plan["unused_surplus_tomorrow_solar_coverage_percent"] == 96


def test_tomorrow_surplus_covers_a_25_hour_dst_day():
    timezone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 10, 24, 0, 0, tzinfo=timezone)
    start_utc = now.astimezone(UTC)
    slots = [
        ForecastSlot(
            start=(start_utc + timedelta(hours=index)).astimezone(timezone),
            solar_kwh=2,
            consumption_kwh=0,
        )
        for index in range(49)
    ]

    result = calculate_plan(
        _input(
            now=now,
            slots=slots,
            battery_soc=100,
            forecast_horizon_hours=48,
        )
    )

    assert result.plan["unused_surplus_tomorrow_kwh"] == 50
    assert result.plan["unused_surplus_tomorrow_coverage_percent"] == 100


def test_battery_capacity_must_be_positive():
    result = calculate_plan(
        _input(
            now=datetime(2026, 7, 3, 12, 0),
            slots=[],
            battery_capacity_kwh=0,
        )
    )

    assert result.state == "error"
    assert result.warnings == ["Battery capacity must be greater than zero."]
