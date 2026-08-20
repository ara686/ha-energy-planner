from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_planner.ev_plan import (
    EVChargingPlanInput,
    EVChargingSlot,
    calculate_ev_charging_plan,
    calculate_ev_charging_plans,
)


def _slots(
    start: datetime,
    *,
    count: int,
    surplus_by_hour: dict[int, float] | None = None,
    battery_kwh: float = 10.0,
    low_tariff_hours: set[int] | None = None,
    coverage: float = 1.0,
) -> list[EVChargingSlot]:
    surplus_by_hour = surplus_by_hour or {}
    low_tariff_hours = low_tariff_hours or set()
    return [
        EVChargingSlot(
            start=start + timedelta(hours=index),
            unused_surplus_kwh=surplus_by_hour.get(index, 0.0),
            battery_kwh=battery_kwh,
            solar_coverage=coverage,
            is_low_tariff=index in low_tariff_hours,
        )
        for index in range(count)
    ]


def _vehicle(**overrides) -> EVChargingPlanInput:
    values = {
        "source_id": "sensor.ev_energy",
        "priority": 1,
        "required_input_kwh": 6.0,
        "maximum_charging_power_kw": 3.0,
        "currently_home": True,
        "connected": True,
    }
    values.update(overrides)
    return EVChargingPlanInput(**values)


def test_ev_plan_uses_solar_only_while_vehicle_is_scheduled_home() -> None:
    now = datetime(2026, 8, 17, 6, tzinfo=UTC)
    slots = _slots(
        now,
        count=11,
        surplus_by_hour={0: 2.0, 4: 5.0},
        battery_kwh=6.0,
    )

    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=4.0),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.solar_kwh == 2
    assert plan.home_battery_kwh == 0
    assert plan.shortfall_kwh == 2
    assert plan.solar_if_home_kwh == 4
    assert plan.solar_if_home_covers_request is True


def test_ev_plan_shifts_only_safe_battery_energy_replaced_by_lost_solar() -> None:
    now = datetime(2026, 8, 17, 5, tzinfo=UTC)
    slots = _slots(
        now,
        count=12,
        surplus_by_hour={4: 2.0, 5: 2.0},
        battery_kwh=10.0,
    )

    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=5.0),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.home_battery_kwh == 4
    assert plan.shortfall_kwh == 1


def test_ev_plan_never_shifts_battery_with_incomplete_forecast() -> None:
    now = datetime(2026, 8, 17, 5, tzinfo=UTC)
    slots = _slots(
        now,
        count=12,
        surplus_by_hour={4: 5.0},
        battery_kwh=10.0,
        coverage=0.8,
    )

    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=3.0),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.forecast_complete is False
    assert plan.home_battery_kwh == 0


def test_ev_plan_marks_a_gap_between_action_windows_incomplete() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    slots = [
        EVChargingSlot(
            start=now + timedelta(minutes=10 * index),
            unused_surplus_kwh=0,
            battery_kwh=10,
        )
        for index in range(102)
        if index != 6
    ]

    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=1),
        now=now,
        slots=slots,
        interval_minutes=10,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.forecast_complete is False


def test_ev_plan_uses_low_tariff_then_explicitly_allowed_high_tariff_grid() -> None:
    now = datetime(2026, 8, 17, 3, tzinfo=UTC)
    slots = _slots(now, count=14, battery_kwh=6.0, low_tariff_hours={0})

    disallowed = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=6.0, allow_high_tariff_grid=False),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )
    allowed = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=6.0, allow_high_tariff_grid=True),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert disallowed.grid_low_tariff_kwh == 3
    assert disallowed.shortfall_kwh == 3
    assert allowed.grid_low_tariff_kwh == 3
    assert allowed.grid_high_tariff_kwh == 3
    assert allowed.shortfall_kwh == 0


def test_ev_plan_places_battery_next_to_low_tariff_grid_session() -> None:
    now = datetime(2026, 8, 17, tzinfo=UTC)
    slots = [
        EVChargingSlot(
            start=now + timedelta(minutes=10 * index),
            unused_surplus_kwh=1 if index == 48 else 0,
            battery_kwh=10,
            is_low_tariff=6 <= index < 18,
        )
        for index in range(102)
    ]

    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=4.0),
        now=now,
        slots=slots,
        interval_minutes=10,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.home_battery_kwh == 1
    assert plan.grid_low_tariff_kwh == 3
    assert plan.shortfall_kwh == 0
    timeline = [(window.start, window.end, window.mode) for window in plan.timeline]
    assert timeline == [
        (
            datetime(2026, 8, 17, 1, 40, tzinfo=UTC),
            datetime(2026, 8, 17, 2, tzinfo=UTC),
            "home_battery",
        ),
        (
            datetime(2026, 8, 17, 2, tzinfo=UTC),
            datetime(2026, 8, 17, 3, tzinfo=UTC),
            "grid_low_tariff",
        ),
    ]


def test_ev_plan_live_availability_overrides_schedule() -> None:
    now = datetime(2026, 8, 17, 5, tzinfo=UTC)
    slots = _slots(now, count=12, surplus_by_hour={0: 3.0})

    away = calculate_ev_charging_plan(
        _vehicle(currently_home=False),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )
    disconnected = calculate_ev_charging_plan(
        _vehicle(connected=False),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert away.mode == "off"
    assert away.reason == "vehicle_away"
    assert disconnected.mode == "connect_vehicle"


def test_ev_plan_weekend_and_dst_find_next_local_workday_departure() -> None:
    timezone = ZoneInfo("Europe/Prague")
    now = datetime(2026, 10, 25, 1, tzinfo=timezone)
    slots: list[EVChargingSlot] = []
    cursor = now.astimezone(UTC)
    for _index in range(33):
        local = cursor.astimezone(timezone)
        slots.append(EVChargingSlot(local, 0.0, 6.0))
        cursor += timedelta(hours=1)

    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=1.0),
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.departure == datetime(2026, 10, 26, 7, tzinfo=timezone)


def test_multiple_evs_reserve_shared_solar_by_priority() -> None:
    now = datetime(2026, 8, 17, 6, tzinfo=UTC)
    slots = _slots(now, count=11, surplus_by_hour={0: 3.0}, battery_kwh=6.0)

    plans = calculate_ev_charging_plans(
        [
            _vehicle(source_id="sensor.second", priority=2, required_input_kwh=3),
            _vehicle(source_id="sensor.first", priority=1, required_input_kwh=3),
        ],
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plans["sensor.first"].solar_kwh == 3
    assert plans["sensor.second"].solar_kwh == 0
    assert plans["sensor.second"].shortfall_kwh == 3


@pytest.mark.parametrize("required", [0.0, -1.0])
def test_ev_plan_complete_or_invalid_request(required: float) -> None:
    now = datetime(2026, 8, 17, 5, tzinfo=UTC)
    plan = calculate_ev_charging_plan(
        _vehicle(required_input_kwh=required),
        now=now,
        slots=_slots(now, count=12),
        interval_minutes=60,
        battery_capacity_kwh=20,
        safe_discharge_soc=30,
    )

    assert plan.mode == ("complete" if required == 0 else "unavailable")
