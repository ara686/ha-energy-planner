"""Physical solar admission, using the same ledger as the SoC graph."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.energy_planner.ev_plan import (
    EVChargingPlanInput,
    EVChargingSlot,
    calculate_ev_charging_plan,
)
from custom_components.energy_planner.joint_plan import (
    JointLimits,
    JointWater,
    calculate_joint_plan,
)
from custom_components.energy_planner.managed_allocation import (
    SurplusSlot,
    allocate_managed_day,
)
from custom_components.energy_planner.models import (
    ForecastSlot,
    PlannerInput,
    TimeWindow,
)
from custom_components.energy_planner.planner import (
    SocGridBudget,
    calculate_soc_forecast,
)

from .test_managed_allocation import _electric_vehicle, _generic, _hot_water


def _data(soc=50, surplus=(2.3,), home=None):
    now = datetime(2026, 9, 14, 10, tzinfo=UTC)
    home = home or [0.7] * len(surplus)
    return PlannerInput(
        now=now,
        battery_soc=soc,
        battery_capacity_kwh=10,
        battery_min_soc=20,
        slots=[
            ForecastSlot(now + timedelta(hours=i), max(0, excess + home[i]), home[i])
            for i, excess in enumerate(surplus)
        ],
        nt_windows=[],
        charge_window=TimeWindow("00:00", "00:00"),
        grid_charging_enabled=False,
        interval_minutes=60,
        forecast_horizon_hours=len(surplus),
        grid_charge_efficiency=1,
        soc_reserve_percent=0,
    )


def _water(source="water", required=2.3, threshold=50, priority=100):
    return replace(
        _hot_water(source, required=required, flexible=0, power=2.3, priority=priority),
        solar_minimum_soc_percent=threshold,
    )


def _ev(source="ev", required=4, threshold=50, priority=100, maximum=11):
    return replace(
        _electric_vehicle(source, required=required, power=maximum, priority=priority),
        solar_minimum_soc_percent=threshold,
        minimum_solar_power_kw=1.38,
    )


def _allocate(data, loads):
    budget = SocGridBudget(
        data,
        managed_consumption_by_slot={},
        grid_charge_target_soc=None,
        nt_lock_soc=20,
    )
    result = allocate_managed_day(
        target_date=data.now.date(),
        interval_minutes=data.interval_minutes,
        surplus_complete=True,
        surplus_slots=[
            SurplusSlot(s.start, max(0, s.solar_kwh - s.consumption_kwh))
            for s in data.slots
        ],
        loads=loads,
        budget=budget,
    )
    energy = {}
    for schedule in (
        result.hot_water_energy_by_slot,
        result.electric_vehicle_energy_by_slot,
    ):
        for start, value in schedule.items():
            energy[start] = energy.get(start, 0) + value
    for (_, start), value in result.generic_energy_by_source_slot.items():
        energy[start] = energy.get(start, 0) + value
    points = calculate_soc_forecast(
        data, managed_consumption_by_slot=energy, nt_lock_soc=20
    ).points
    return result, points


@pytest.mark.parametrize("soc,expected", [(49.9999, 0), (50, 2.3), (50.0001, 2.3)])
def test_water_uses_exact_start_soc_not_rounded_end_soc(soc, expected):
    result, points = _allocate(_data(soc), [_water()])
    assert result.recommended_kwh == pytest.approx(expected)
    assert points[0].battery_start_kwh == pytest.approx(soc / 10)
    if expected == 0:
        assert result.loads[0].reason == "waiting_for_minimum_soc"


@pytest.mark.parametrize("excess,expected", [(2.2, 0), (2.3, 2.3), (2.4, 2.3)])
def test_water_requires_full_heater_above_household_demand(excess, expected):
    result, _ = _allocate(_data(surplus=(excess,)), [_water()])
    assert result.recommended_kwh == pytest.approx(expected)
    if expected == 0:
        assert result.loads[0].reason == "insufficient_solar_power"


def test_reaching_threshold_during_slot_only_permits_next_slot():
    data = _data(40, surplus=(2.3, 2.3))
    result, points = _allocate(data, [_water()])
    assert result.loads[0].timeline[0].start == data.now + timedelta(hours=1)
    assert points[0].battery_start_kwh == 4
    assert points[1].battery_start_kwh == pytest.approx(6.3)


def test_solar_pauses_after_soc_drop_then_resumes_after_recharge():
    data = _data(60, surplus=(2.3, -2, 2.3, 2.3), home=[0.7, 2, 0.7, 0.7])
    result, points = _allocate(data, [_water(required=4.6)])
    assert [window.start for window in result.loads[0].timeline] == [
        data.now,
        data.now + timedelta(hours=3),
    ]
    assert points[2].battery_start_kwh == 4
    assert points[3].battery_start_kwh == pytest.approx(6.3)


def test_earlier_generic_draw_preserves_already_accepted_later_soc_gate():
    data = _data(40, surplus=(1.2, 2.3))
    result, points = _allocate(data, [_water(), _generic("pool", expected=1)])
    loads = {load.source_id: load for load in result.loads}
    assert loads["water"].recommended_kwh == pytest.approx(2.3)
    assert loads["pool"].recommended_kwh == pytest.approx(0.2, abs=1e-5)
    assert points[1].battery_start_kwh >= 5 - 1e-9


def test_different_load_thresholds_and_fixed_peak_concurrency():
    data = _data(55, surplus=(4.6,))
    result, _ = _allocate(data, [_water(threshold=60), _ev(threshold=50)])
    assert result.loads[0].recommended_kwh == 0
    assert result.loads[1].recommended_kwh == 4

    result, _ = _allocate(data, [_water(required=0.3), _ev(required=1.5)])
    assert result.recommended_kwh == pytest.approx(1.8)
    water = result.loads[0].timeline[0]
    assert (water.end - water.start).total_seconds() / 3600 == pytest.approx(0.3 / 2.3)
    assert (
        sum(
            window.energy_kwh / ((window.end - window.start).total_seconds() / 3600)
            for load in result.loads
            for window in load.timeline
        )
        <= 4.6 + 1e-9
    )


def test_small_water_request_still_reserves_full_instantaneous_heater_power():
    result, _ = _allocate(
        _data(surplus=(3,)), [_water(required=0.3), _ev(required=0.3)]
    )
    assert result.loads[0].recommended_kwh == pytest.approx(0.3)
    assert result.loads[1].recommended_kwh == 0


@pytest.mark.parametrize(
    "excess,required,maximum,expected,duration",
    [
        (1.37, 4, 11, 0, None),
        (1.38, 4, 11, 1.38, 1),
        (2.4, 4, 11, 2.4, 1),
        (5, 4, 2, 2, 1),
        (1.38, 0.2, 11, 0.2, 0.2 / 1.38),
    ],
)
def test_ev_solar_minimum_modulation_and_short_completion(
    excess, required, maximum, expected, duration
):
    result, _ = _allocate(
        _data(surplus=(excess,)), [_ev(required=required, maximum=maximum)]
    )
    load = result.loads[0]
    assert load.recommended_kwh == pytest.approx(expected)
    if duration is not None:
        window = load.timeline[0]
        assert (window.end - window.start).total_seconds() / 3600 == pytest.approx(
            duration
        )


@pytest.mark.parametrize(
    "excess,expected", [(4, {"a": 2, "b": 2}), (2, {"a": 2, "b": 0})]
)
def test_equal_priority_shares_only_when_both_ev_minima_are_feasible(excess, expected):
    result, _ = _allocate(_data(surplus=(excess,)), [_ev("b"), _ev("a")])
    assert {load.source_id: load.recommended_kwh for load in result.loads} == expected


def test_fixed_heaters_use_source_id_if_proportional_split_is_impossible():
    result, _ = _allocate(_data(surplus=(3,)), [_water("b"), _water("a")])
    assert {load.source_id: load.recommended_kwh for load in result.loads} == {
        "b": 0,
        "a": pytest.approx(2.3),
    }
    assert result.loads[0].reason == "insufficient_solar_power"


def test_zero_soc_threshold_keeps_future_battery_reserve():
    data = _data(20, surplus=(2.3, -2), home=[0.7, 2])
    result, points = _allocate(data, [_water(threshold=0)])
    # Only 0.3 kWh could be removed safely; a 2.3-kWh request cannot run for
    # the whole interval at the heater's fixed power, so it is postponed.
    assert result.recommended_kwh == 0
    assert points[-1].battery_kwh >= 2


@pytest.mark.parametrize(
    "soc,excess,expected",
    [(49.9999, 2.3, 0), (50, 2.2, 0), (50, 2.3, 2.3), (50.0001, 2.4, 2.3)],
)
def test_joint_water_same_admission_as_compatibility(soc, excess, expected):
    d = _data(soc, surplus=(excess, 0), home=[0.7, 0])
    heat_capacity = 0.001163 * 200
    result = calculate_joint_plan(
        d,
        water=[
            JointWater(
                "water",
                40,
                200,
                2.3,
                minimum=40 + 2.3 / heat_capacity,
                normal=40 + 2.3 / heat_capacity,
                maximum=40 + 2.3 / heat_capacity,
                deadline=time(12),
                loss_kw=0,
                daily_draw_kwh=0,
            )
        ],
    )
    assert result.water["water"]["planned_electrical_kwh"] == pytest.approx(expected)
    assert all(p["grid_charge_ac_kwh"] == 0 for p in result.points)
    for action in result.water["water"]["timeline"]:
        assert action["power_kw"] == pytest.approx(2.3)


@pytest.mark.parametrize(
    "excess,required,expected",
    [(1.37, 4, 0), (1.38, 4, 1.38), (2.4, 4, 2.4), (1.38, 0.2, 0.2)],
)
def test_joint_ev_uses_technical_minimum_and_can_finish_early(
    excess, required, expected
):
    d = _data(surplus=(excess, 0), home=[0.7, 0])
    vehicle = EVChargingPlanInput(
        "ev",
        1,
        required,
        11,
        departure_time=time(12),
        currently_home=True,
        connected=True,
        allow_home_battery=False,
    )
    result = calculate_joint_plan(d, vehicles=[vehicle])
    assert result.vehicles["ev"]["planned_kwh"] == pytest.approx(expected)
    for action in result.vehicles["ev"]["timeline"]:
        assert action["power_kw"] >= 1.38 - 1e-9
        assert action["power_kw"] <= excess + 1e-6


@pytest.mark.parametrize(
    "soc,excess,required,expected",
    [(49.9999, 2.3, 4, 0), (50, 1.37, 4, 0), (50, 1.38, 4, 1.38), (50, 1.38, 0.2, 0.2)],
)
def test_deadline_ev_start_gate_and_minimum_power(soc, excess, required, expected):
    now = _data().now
    vehicle = EVChargingPlanInput(
        "ev",
        1,
        required,
        11,
        departure_time=time(11),
        currently_home=True,
        connected=True,
        allow_home_battery=False,
        minimum_solar_power_kw=1.38,
    )
    result = calculate_ev_charging_plan(
        vehicle,
        now=now,
        slots=[EVChargingSlot(now, excess, 10, battery_start_kwh=soc / 10)],
        interval_minutes=60,
        battery_capacity_kwh=10,
        safe_discharge_soc=20,
    )
    assert result.solar_kwh == pytest.approx(expected)
    if expected:
        window = result.timeline[0]
        assert (
            window.energy_kwh / ((window.end - window.start).total_seconds() / 3600)
            >= 1.38 - 1e-9
        )


def test_joint_replay_keeps_later_solar_threshold_after_earlier_ev_battery_draw():
    d = _data(60, surplus=(0, 2.3, 4, 0), home=[0, 0.7, 0.7, 0])
    vehicle = EVChargingPlanInput(
        "ev",
        1,
        5,
        6,
        departure_time=time(11),
        return_time=time(12),
        currently_home=True,
        connected=True,
    )
    tank = JointWater(
        "water",
        40,
        200,
        2.3,
        minimum=45,
        normal=45,
        maximum=45,
        deadline=time(14),
        loss_kw=0,
        daily_draw_kwh=0,
    )
    result = calculate_joint_plan(d, water=[tank], vehicles=[vehicle])
    for point in result.points:
        if point["managed_by_source"].get("water", 0) > 0:
            assert point["battery_start_kwh"] >= 5 - 1e-9
    assert result.water["water"]["planned_electrical_kwh"] == pytest.approx(1.163)


@pytest.mark.parametrize(
    "excess,expected", [(4, {"a": 2, "b": 2}), (2, {"a": 2, "b": 0})]
)
def test_joint_equal_priority_ev_shares_only_feasible_minima(excess, expected):
    d = _data(surplus=(excess, 0), home=[0.7, 0])
    vehicles = [
        EVChargingPlanInput(
            source,
            1,
            4,
            11,
            departure_time=time(12),
            currently_home=True,
            connected=True,
            allow_home_battery=False,
        )
        for source in ("b", "a")
    ]
    result = calculate_joint_plan(d, vehicles=vehicles)
    assert {
        source: plan["planned_kwh"] for source, plan in result.vehicles.items()
    } == expected


@pytest.mark.parametrize(
    "excess,expected", [(4.6, {"a": 2.3, "b": 2.3}), (3, {"a": 2.3, "b": 0})]
)
def test_joint_water_proportional_sharing_keeps_fixed_heater_power(excess, expected):
    d = _data(surplus=(excess, 0), home=[0.7, 0])
    target = 40 + 4.6 / (0.001163 * 200)
    tanks = [
        JointWater(
            source,
            40,
            200,
            2.3,
            minimum=target,
            normal=target,
            maximum=target,
            deadline=time(12),
            loss_kw=0,
            daily_draw_kwh=0,
        )
        for source in ("b", "a")
    ]
    result = calculate_joint_plan(d, water=tanks)
    assert {
        source: plan["planned_electrical_kwh"] for source, plan in result.water.items()
    } == pytest.approx(expected)
    assert all(
        action["power_kw"] == pytest.approx(2.3)
        for plan in result.water.values()
        for action in plan["timeline"]
    )


def test_incomplete_joint_interval_withholds_solar_loads():
    d = _data(surplus=(4, 0), home=[0.7, 0])
    d = replace(d, slots=[replace(slot, solar_coverage=0.5) for slot in d.slots])
    result = calculate_joint_plan(
        d,
        water=[
            JointWater(
                "water",
                40,
                200,
                2.3,
                minimum=45,
                normal=45,
                maximum=45,
                deadline=time(12),
            )
        ],
    )
    assert result.water["water"]["planned_electrical_kwh"] == 0
    assert "incomplete_solar_forecast" in result.water["water"]["solar_block_reasons"]


def test_joint_short_heater_cannot_exceed_phase_limit():
    d = _data(surplus=(4, 0), home=[0.7, 0])
    tank = JointWater(
        "water",
        40,
        200,
        2.3,
        minimum=40.1,
        normal=40.1,
        maximum=40.1,
        deadline=time(12),
    )
    result = calculate_joint_plan(
        d, water=[tank], limits=JointLimits(phase_limit_kw=2.9, phases=1)
    )
    assert result.water["water"]["planned_electrical_kwh"] == 0


def test_deadline_permission_window_cannot_start_before_fine_soc_gate():
    d = replace(_data(49, surplus=(0.115, 0.115, 0.115, 0.115)), interval_minutes=5)
    d = replace(
        d,
        slots=[
            ForecastSlot(d.now + timedelta(minutes=5 * i), 0.115, 0) for i in range(4)
        ],
    )
    vehicle = replace(_ev(required=0.23), solar_action_window_minutes=10)
    result, points = _allocate(d, [vehicle])
    assert result.electric_vehicle_energy_by_slot == {
        d.now + timedelta(minutes=10): pytest.approx(0.115),
        d.now + timedelta(minutes=15): pytest.approx(0.115),
    }
    assert points[0].battery_start_kwh == 4.9
    assert points[1].battery_start_kwh > 5
    assert result.loads[0].timeline[0].start == d.now + timedelta(minutes=10)


def test_deadline_permission_window_respects_lowest_fine_solar_power():
    d = replace(_data(50, surplus=(0.115, 0.11, 0.15, 0.2)), interval_minutes=5)
    d = replace(
        d,
        slots=[
            ForecastSlot(d.now + timedelta(minutes=5 * i), power, 0)
            for i, power in enumerate((0.115, 0.11, 0.15, 0.2))
        ],
    )
    result, _ = _allocate(d, [replace(_ev(required=1), solar_action_window_minutes=10)])
    assert result.electric_vehicle_energy_by_slot == {
        d.now + timedelta(minutes=10): pytest.approx(0.15),
        d.now + timedelta(minutes=15): pytest.approx(0.15),
    }


def test_deadline_multi_ev_reserves_peak_for_a_short_final_request():
    from custom_components.energy_planner.ev_plan import calculate_ev_charging_plans

    now = _data().now
    vehicles = [
        EVChargingPlanInput(
            source,
            priority,
            request,
            11,
            departure_time=time(11),
            currently_home=True,
            connected=True,
            allow_home_battery=False,
            minimum_solar_power_kw=1.38,
        )
        for source, priority, request in (("first", 1, 0.2), ("second", 2, 4))
    ]
    result = calculate_ev_charging_plans(
        vehicles,
        now=now,
        slots=[EVChargingSlot(now, 2, 5, battery_start_kwh=5)],
        interval_minutes=60,
        battery_capacity_kwh=10,
        safe_discharge_soc=20,
    )
    assert result["first"].solar_kwh == pytest.approx(0.2)
    assert result["second"].solar_kwh == 0


def test_deadline_battery_draw_keeps_its_own_later_solar_gate():
    now = datetime(2026, 9, 14, 6, tzinfo=UTC)
    slots = [
        EVChargingSlot(
            now + timedelta(hours=i), 2 if i >= 2 else 0, 5, battery_start_kwh=5
        )
        for i in range(6)
    ]
    vehicle = EVChargingPlanInput(
        "ev",
        1,
        3,
        2,
        departure_time=time(9),
        return_time=time(11),
        currently_home=True,
        connected=True,
        minimum_solar_power_kw=1.38,
    )
    result = calculate_ev_charging_plan(
        vehicle,
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=10,
        safe_discharge_soc=20,
    )
    assert result.solar_kwh == 2
    assert result.home_battery_kwh == 0


def test_deadline_battery_draw_after_solar_session_retains_existing_rules():
    now = datetime(2026, 9, 14, 6, tzinfo=UTC)
    slots = [
        EVChargingSlot(
            now + timedelta(hours=i),
            2 if i == 2 or i >= 4 else 0,
            5,
            battery_start_kwh=5,
        )
        for i in range(6)
    ]
    vehicle = EVChargingPlanInput(
        "ev",
        1,
        3,
        2,
        departure_time=time(10),
        return_time=time(11),
        currently_home=True,
        connected=True,
        minimum_solar_power_kw=1.38,
    )
    result = calculate_ev_charging_plan(
        vehicle,
        now=now,
        slots=slots,
        interval_minutes=60,
        battery_capacity_kwh=10,
        safe_discharge_soc=20,
    )
    assert result.solar_kwh == 2
    assert result.home_battery_kwh == 1
    assert result.timeline[-1].start == now + timedelta(hours=3)
