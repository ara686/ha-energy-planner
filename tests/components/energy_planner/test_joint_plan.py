from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

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
    normalized_joint_slots,
)
from custom_components.energy_planner.models import (
    ForecastSlot,
    PlannerInput,
    TimeWindow,
)


def data(*, hours=24, soc=20, home=0.0, solar=0):
    now = datetime(2026, 9, 14, tzinfo=UTC)
    return PlannerInput(
        now,
        soc,
        10,
        20,
        [ForecastSlot(now + timedelta(hours=i), solar, home) for i in range(hours)],
        [TimeWindow("00:00", "02:00")],
        TimeWindow("00:00", "02:00"),
        interval_minutes=60,
        grid_charge_max_kw=2,
        grid_charge_efficiency=1,
        soc_reserve_percent=0,
        forecast_horizon_hours=hours,
    )


def ev(**kwargs):
    return EVChargingPlanInput(
        "ev",
        1,
        kwargs.pop("required", 4),
        6,
        departure_time=time(2),
        return_time=time(17),
        currently_home=True,
        connected=True,
        **kwargs,
    )


def assert_balance(result, charge_eff=1, discharge_eff=1):
    for p in result.points:
        assert p["solar_kwh"] + p["grid_import_kwh"] + p[
            "battery_discharge_ac_kwh"
        ] == pytest.approx(
            p["consumption_kwh"]
            - p["unserved_kwh"]
            + p["battery_charge_ac_kwh"]
            + p["export_kwh"]
            + p["curtailed_kwh"]
        )
        assert p["battery_kwh"] == pytest.approx(
            p["battery_start_kwh"]
            + p["battery_charge_ac_kwh"] * charge_eff
            - p["battery_discharge_ac_kwh"] / discharge_eff
        )


def test_house_reserve_precedes_ev_and_reports_shortfall():
    d = data()
    generic = {d.now + timedelta(hours=2): {"appliance": 4}}
    result = calculate_joint_plan(
        d,
        generic=generic,
        vehicles=[ev()],
        limits=JointLimits(grid_import_kw=2, phases=1),
    )
    assert result.nt_targets[0]["target_soc"] == pytest.approx(60)
    assert result.vehicles["ev"]["shortfall_kwh"] == pytest.approx(4)
    assert result.summary["vt_grid_import_kwh"] == 0
    assert sum(p["managed_by_source"].get("appliance", 0) for p in result.points) == 4
    assert_balance(result)


def test_optional_water_never_increases_grid_purchase():
    d = data(soc=100, home=0.1)
    baseline = calculate_joint_plan(d)
    result = calculate_joint_plan(
        d, water=[JointWater("water", 40, 200, 2.3, gas_backup=True)]
    )
    assert (
        result.summary["grid_import_kwh"] <= baseline.summary["grid_import_kwh"] + 1e-6
    )
    assert result.water["water"]["planned_electrical_kwh"] <= 200 * 0.001163 * 5 + 1e-6
    assert_balance(result)


def test_solar_only_water_starts_from_direct_headroom_before_battery_is_full():
    d = replace(
        data(soc=20),
        grid_charging_enabled=False,
        nt_windows=[],
        slots=[
            ForecastSlot(
                data().now + timedelta(hours=index),
                3 if 8 <= index < 16 else 0,
                1 if 8 <= index < 16 else 0,
            )
            for index in range(24)
        ],
    )
    baseline = calculate_joint_plan(d)
    result = calculate_joint_plan(d, water=[JointWater("water", 40, 200, 2.3)])

    timeline = result.water["water"]["timeline"]
    assert timeline
    assert timeline[0]["start"] == (d.now + timedelta(hours=8)).isoformat()
    assert all(action["mode"] == "solar" for action in timeline)
    assert all(action["grid_kwh"] == 0 for action in timeline)
    first_managed = next(
        index
        for index, point in enumerate(result.points)
        if point["managed_by_source"].get("water", 0) > 0
    )
    assert baseline.points[first_managed]["soc_percent"] < 100
    assert (
        result.points[first_managed]["soc_percent"]
        < baseline.points[first_managed]["soc_percent"]
    )
    assert result.summary["grid_import_kwh"] <= baseline.summary["grid_import_kwh"]


def test_gas_fills_only_comfort_minimum_and_is_not_electricity():
    result = calculate_joint_plan(
        data(), water=[JointWater("water", 30, 200, 2.3, gas_backup=True)]
    )
    assert result.water["water"]["gas_thermal_kwh"] == pytest.approx(2.326)
    assert result.water["water"]["planned_electrical_kwh"] == 0
    assert result.summary["grid_import_kwh"] == 0


def test_solar_grid_mix_in_joint_slot():
    d = data(solar=0.1)
    # Full battery cannot absorb solar, but may not feed the EV.
    d = replace(d, battery_soc=100)
    result = calculate_joint_plan(
        d,
        vehicles=[ev(required=5, allow_home_battery=False)],
        limits=JointLimits(grid_import_kw=6, phases=1),
    )
    assert result.vehicles["ev"]["shortfall_kwh"] < 1e-5
    assert result.vehicles["ev"]["planned_kwh"] == pytest.approx(5)
    assert_balance(result)


def test_minimum_ev_power_does_not_schedule_tiny_solar():
    d = data(soc=100, solar=0.1)
    d = replace(d, nt_windows=[])
    result = calculate_joint_plan(
        d, vehicles=[ev(allow_home_battery=False)], limits=JointLimits(phases=1)
    )
    assert result.vehicles["ev"]["planned_kwh"] == 0


def test_all_nt_windows_can_charge_house():
    d = data()
    d = replace(
        d, nt_windows=[TimeWindow("00:00", "02:00"), TimeWindow("17:00", "19:00")]
    )
    generic = {d.now + timedelta(hours=h): {"load": 4} for h in (3, 20)}
    result = calculate_joint_plan(d, generic=generic)
    assert len(result.nt_targets) == 2
    assert all(t["grid_charge_ac_kwh"] > 0 for t in result.nt_targets)
    assert result.summary["vt_grid_import_kwh"] == 0
    assert_balance(result)


def test_partial_interval_retains_energy_and_duration():
    d = data()
    d = replace(
        d,
        now=d.now + timedelta(minutes=30),
        slots=[replace(s, solar_kwh=2, consumption_kwh=1) for s in d.slots],
    )
    slots = normalized_joint_slots(d, {})
    assert slots[0].hours == 0.5
    assert slots[0].solar == 1
    assert slots[0].home == 0.5


@pytest.mark.parametrize("month,day", [(3, 29), (10, 25)])
def test_dst_exact_elapsed_horizon(month, day):
    zone = ZoneInfo("Europe/Prague")
    start = datetime(2026, month, day, tzinfo=zone)
    d = data()
    d = replace(
        d,
        now=start,
        slots=[
            ForecastSlot(
                (start.astimezone(UTC) + timedelta(hours=i)).astimezone(zone), 0, 0.1
            )
            for i in range(25)
        ],
    )
    result = calculate_joint_plan(d)
    assert len(result.points) == 24
    assert datetime.fromisoformat(result.points[-1]["end"]).astimezone(
        UTC
    ) - start.astimezone(UTC) == timedelta(hours=24)


def test_efficiency_once_and_export_limit():
    d = replace(data(soc=100, solar=3), grid_charge_efficiency=0.9)
    result = calculate_joint_plan(
        d, limits=JointLimits(export_kw=1, discharge_efficiency=0.8)
    )
    assert result.summary["curtailed_kwh"] > 0
    assert all(p["export_kwh"] <= 1 for p in result.points)
    assert_balance(result, 0.9, 0.8)


def test_legacy_ev_active_interval_is_not_discarded():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    slots = [
        EVChargingSlot(now + timedelta(minutes=10 * i), 0, 2, is_low_tariff=True)
        for i in range(30)
    ]
    vehicle = replace(ev(required=6, allow_home_battery=False), departure_time=time(13))
    result = calculate_ev_charging_plan(
        vehicle,
        now=now + timedelta(seconds=1),
        slots=slots,
        interval_minutes=10,
        battery_capacity_kwh=10,
        safe_discharge_soc=20,
    )
    assert result.planned_kwh == pytest.approx(6 - 6 / 3600)
    assert result.next_action_start == now + timedelta(seconds=1)
    assert result.timeline[-1].end == now + timedelta(hours=1)


def test_legacy_ev_solar_does_not_block_nt_top_up():
    now = datetime(2026, 9, 14, 12, tzinfo=UTC)
    slots = [
        EVChargingSlot(now + timedelta(minutes=10 * i), 0.1, 2, is_low_tariff=True)
        for i in range(30)
    ]
    result = calculate_ev_charging_plan(
        replace(ev(required=5, allow_home_battery=False), departure_time=time(13)),
        now=now,
        slots=slots,
        interval_minutes=10,
        battery_capacity_kwh=10,
        safe_discharge_soc=20,
    )
    assert result.solar_kwh == pytest.approx(0.6)
    assert result.grid_low_tariff_kwh == pytest.approx(4.4)
    assert result.shortfall_kwh == 0
    assert sum(w.energy_kwh for w in result.timeline) == pytest.approx(5)


def test_water_deficit_is_not_repeated_the_next_day():
    result = calculate_joint_plan(
        data(hours=48), water=[JointWater("water", 30, 200, 2.3, gas_backup=True)]
    )
    deadlines = result.water["water"]["deadlines"]
    assert len(deadlines) == 2
    assert deadlines[0]["gas_thermal_kwh"] == pytest.approx(2.326)
    assert deadlines[1]["gas_thermal_kwh"] == 0


def test_water_new_day_only_replenishes_estimated_losses():
    result = calculate_joint_plan(
        data(hours=48),
        water=[
            JointWater(
                "water", 40, 200, 2.3, gas_backup=True, loss_kw=0.05, daily_draw_kwh=0.6
            )
        ],
    )
    deadlines = result.water["water"]["deadlines"]
    assert deadlines[1]["gas_thermal_kwh"] == pytest.approx(24 * 0.05 + 0.6)


def test_small_ev_request_cannot_fake_minimum_current():
    d = replace(data(soc=100, solar=0.1), nt_windows=[])
    result = calculate_joint_plan(
        d,
        vehicles=[ev(required=0.1, allow_home_battery=False)],
        limits=JointLimits(phases=1),
    )
    assert result.vehicles["ev"]["planned_kwh"] == 0


def test_binary_decisions_use_current_soc_and_window():
    from custom_components.energy_planner.binary_sensor import (
        _charge_now,
        _discharge_allowed,
    )
    from custom_components.energy_planner.models import PlannerResult

    r = PlannerResult(
        "ok",
        datetime.now(UTC),
        plan={
            "current_soc": 60,
            "soc_at_planner_start": 20,
            "target_soc": 80,
            "safe_discharge_soc": 40,
            "current_charge_window": False,
        },
    )
    assert _charge_now(r) is False
    assert _discharge_allowed(r) is True


def test_history_partial_gap_is_filled_per_hour_without_double_counting():
    from custom_components.energy_planner.history import EnergyHistory

    hours = ["2026-09-13T00:00:00", "2026-09-13T01:00:00"]
    main = EnergyHistory.from_hourly_energy_changes(
        home_source_id="home",
        home_changes={h: 2 for h in hours},
        managed_changes_by_source={"pool": {hours[0]: 0.5}},
    )
    fallback = EnergyHistory.from_hourly_energy_changes(
        home_source_id="home",
        home_changes={h: 2 for h in hours},
        managed_changes_by_source={"pool": {h: 0.5 for h in hours}},
    )
    assert not main.buckets[hours[1]].base_usable
    main.merge_missing_managed_sources(fallback, ["pool"])
    main.merge_missing_managed_sources(fallback, ["pool"])
    assert [main.buckets[h].base_kwh for h in hours] == [1.5, 1.5]
    assert all(main.buckets[h].base_usable for h in hours)


def test_observed_zero_is_distinct_from_missing():
    from custom_components.energy_planner.history import EnergyHistory

    h = "2026-09-13T00:00:00"
    zero = EnergyHistory.from_hourly_energy_changes(
        home_source_id="home",
        home_changes={h: 0},
        managed_changes_by_source={"pool": {h: 0}},
    )
    missing = EnergyHistory.from_hourly_energy_changes(
        home_source_id="home",
        home_changes={h: 0},
        managed_changes_by_source={"pool": {}},
    )
    assert zero.buckets[h].base_usable
    assert not missing.buckets[h].base_usable


def test_remaining_profile_fallback_preserves_energy():
    from custom_components.energy_planner.managed_forecast import (
        build_managed_demand_schedule,
    )

    d = data()
    result = build_managed_demand_schedule(
        slots=d.slots[12:14],
        target_date=d.now.date(),
        reference=d.now,
        interval_minutes=60,
        expected_by_source={"pool": 2},
        hourly_profiles={"pool": {8: 1}},
        normalize_to_available_slots=True,
    )
    assert sum(result.energy_by_slot.values()) == pytest.approx(2)


def test_24h_point_is_end_of_24th_interval():
    from custom_components.energy_planner.planner import calculate_plan

    d = data(hours=48, soc=100, home=1)
    d = replace(
        d,
        battery_capacity_kwh=100,
        battery_min_soc=0,
        grid_charging_enabled=False,
        nt_windows=[],
    )
    result = calculate_plan(d)
    assert result.plan["soc_forecast_24h"]["soc_percent"] == 76


def test_mixed_ev_commands_are_merged_and_sources_sum_to_plan():
    d = data(soc=100, solar=2)
    result = calculate_joint_plan(
        d,
        vehicles=[ev(required=9, allow_home_battery=False)],
        limits=JointLimits(grid_import_kw=11, phases=3),
    )
    vehicle = result.vehicles["ev"]
    actions = vehicle["timeline"]
    assert len({a["start"] for a in actions}) == len(actions)
    assert sum(
        a["solar_kwh"] + a["home_battery_kwh"] + a["grid_kwh"] for a in actions
    ) == pytest.approx(vehicle["planned_kwh"])
    assert vehicle["next_action_mode"] == actions[0]["mode"]


def test_water_after_gas_does_not_exceed_maximum():
    d = data(hours=48, soc=20)
    d = replace(
        d,
        slots=[
            replace(s, solar_kwh=10 if i >= 18 else 0) for i, s in enumerate(d.slots)
        ],
    )
    result = calculate_joint_plan(
        d, water=[JointWater("water", 30, 200, 2.3, gas_backup=True)]
    )
    trace = result.water["water"]["temperature_forecast"]
    assert max(p["temperature_if_actions_executed"] for p in trace) <= 65.001
    assert_balance(result)


def test_nt_boundary_inside_a_slot_is_split():
    d = replace(data(), nt_windows=[TimeWindow("00:00", "00:15")])
    result = calculate_joint_plan(d, generic={d.now + timedelta(hours=2): {"load": 2}})
    assert result.points[0]["end"].endswith("00:15:00+00:00")
    assert result.points[0]["grid_charge_ac_kwh"] <= 0.5
    assert not result.points[1]["is_nt"]


def test_charging_command_matches_first_interval_not_future_target():
    result = calculate_joint_plan(
        data(), generic={data().now + timedelta(hours=2): {"load": 1}}
    )
    assert result.summary["target_soc"] > 20
    assert result.summary["charge_now"] is False
    assert result.summary["current_charge_target_soc"] == 20
