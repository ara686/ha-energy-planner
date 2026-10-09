"""Parity against full-horizon reference trials and deterministic work bounds."""

from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from random import Random
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_planner import joint_plan, planner
from custom_components.energy_planner.coordinator import (
    _reserve_safe_direct_solar_slots,
)
from custom_components.energy_planner.ev_plan import EVChargingPlanInput
from custom_components.energy_planner.joint_plan import JointLimits, JointWater
from custom_components.energy_planner.managed_allocation import SurplusSlot
from custom_components.energy_planner.models import (
    ForecastSlot,
    PlannerInput,
    TimeWindow,
)


class FullForecastBudget:
    """Reference search: render every full forecast, as before optimization."""

    def __init__(self, data, *, managed_consumption_by_slot, **kwargs):
        self.data = data
        self.kwargs = kwargs
        self.schedule = dict(managed_consumption_by_slot)
        self.baseline = planner.calculate_soc_forecast(data, **kwargs).points

    def add(self, start, upper):
        def valid(value):
            schedule = {**self.schedule, start: self.schedule.get(start, 0) + value}
            points = planner.calculate_soc_forecast(
                self.data, managed_consumption_by_slot=schedule, **self.kwargs
            ).points
            return all(
                p.grid_import_kwh <= b.grid_import_kwh + 1e-6
                and p.grid_charge_kwh <= b.grid_charge_kwh + 1e-6
                for p, b in zip(points, self.baseline, strict=True)
            )

        safe = upper
        if not valid(upper):
            low, high = 0.0, upper
            for _ in range(18):
                middle = (low + high) / 2
                if valid(middle):
                    low = middle
                else:
                    high = middle
            safe = low
        if safe > 1e-6:
            self.schedule[start] = self.schedule.get(start, 0) + safe
        return safe


def full_joint_simulator(simulate):
    """Use a complete replay and the original post-simulation validity checks."""

    def full(*args, replay=None, **kwargs):
        candidate = simulate(*args, **kwargs)
        if replay is None or candidate is None:
            return candidate
        reserve = args[3]
        for j, (point, previous) in enumerate(
            zip(candidate, replay.previous, strict=True)
        ):
            if not (
                point["grid_import_kwh"]
                <= previous["grid_import_kwh"]
                + (replay.added_grid if j == replay.index else 0)
                + joint_plan.EPS
                and point["unserved_kwh"] <= previous["unserved_kwh"] + joint_plan.EPS
                and point["battery_kwh"] + joint_plan.EPS
                >= min(previous["battery_kwh"], reserve[j + 1])
            ):
                return None
        return candidate

    return full


def sample_data(seed, *, count=96):
    rng = Random(seed)
    now = datetime(2026, 10, 25, tzinfo=ZoneInfo("Europe/Prague"))
    return PlannerInput(
        now=now,
        battery_soc=rng.choice([10, 40, 100]),
        battery_capacity_kwh=10,
        battery_min_soc=20,
        slots=[
            ForecastSlot(
                (now.astimezone(UTC) + timedelta(minutes=5 * i)).astimezone(now.tzinfo),
                rng.uniform(0, 0.7) if i % 12 < 8 else 0,
                rng.uniform(0, 0.3),
                managed_consumption_kwh=0.01 if seed % 3 else 0,
            )
            for i in range(count)
        ],
        nt_windows=[TimeWindow("22:00", "03:00"), TimeWindow("06:00", "07:00")],
        charge_window=TimeWindow("22:00", "03:00"),
        interval_minutes=5,
        forecast_horizon_hours=48,
        grid_charge_max_kw=2,
        grid_charge_efficiency=0.92,
        grid_charging_enabled=bool(seed % 2),
    )


@pytest.mark.parametrize("seed", range(8))
def test_reserve_budget_matches_full_forecasts(seed):
    data = sample_data(seed)
    existing = (
        {data.slots[3].start: 0.01, data.slots[70].start: 0.1} if seed % 2 else {}
    )
    kwargs = dict(
        managed_consumption_by_slot=existing,
        grid_charge_target_soc=60 if seed % 3 else None,
        nt_lock_soc=40,
    )
    expected = FullForecastBudget(data, **kwargs)
    actual = planner.SocGridBudget(data, **kwargs)
    # Include reverse additions, repeated timestamps and dates outside the horizon.
    starts = [s.start for s in data.slots[::7]]
    if seed % 2:
        starts.reverse()
    starts += starts[:2] + [data.now - timedelta(days=1)]
    for start in starts:
        assert actual.add(start, 0.4) == expected.add(start, 0.4)


def test_reserve_allocation_matches_full_search(monkeypatch):
    data = sample_data(5)
    kwargs = dict(
        planner_input=data,
        result=planner.calculate_plan(data),
        candidate_slots=[
            SurplusSlot(s.start, max(0, s.solar_kwh - s.consumption_kwh))
            for s in data.slots
        ],
        existing_managed_energy_by_slot={},
        maximum_energy_kwh=10,
        maximum_power_kw=3,
    )
    actual = _reserve_safe_direct_solar_slots(**kwargs)
    monkeypatch.setattr(
        "custom_components.energy_planner.coordinator.SocGridBudget", FullForecastBudget
    )
    assert actual == _reserve_safe_direct_solar_slots(**kwargs)


def test_reserve_trial_reuses_prepared_inputs_and_skips_unchanged_prefix():
    data = sample_data(0, count=576)
    data = replace(
        data, slots=[replace(s, solar_kwh=1, consumption_kwh=0) for s in data.slots]
    )
    with patch.object(
        planner, "_normalized_slots", wraps=planner._normalized_slots
    ) as normalize:
        budget = planner.SocGridBudget(
            data,
            managed_consumption_by_slot={},
            grid_charge_target_soc=None,
            nt_lock_soc=20,
        )
        step = planner._BatteryModel.step
        with patch.object(
            planner._BatteryModel, "step", autospec=True, side_effect=step
        ) as steps:
            assert budget.add(data.slots[-1].start, 0.1) == 0.1
            assert steps.call_count == 1
        assert normalize.call_count == 1


@pytest.mark.parametrize("seed", range(8))
def test_joint_plan_matches_full_replay(seed, monkeypatch):
    data = sample_data(seed)
    water = [
        JointWater(
            "water",
            35 if seed % 2 else 64,
            100,
            3,
            gas_backup=bool(seed % 2),
            deadline=time(6),
            loss_kw=0.08,
            daily_draw_kwh=4,
        )
    ]
    vehicles = [
        EVChargingPlanInput(
            "ev",
            1,
            4,
            7,
            departure_time=time(7),
            currently_home=True,
            connected=True,
            allow_home_battery=bool(seed % 2),
        )
    ]
    kwargs = dict(
        water=water,
        vehicles=vehicles,
        limits=JointLimits(
            grid_import_kw=3,
            battery_charge_kw=2,
            battery_discharge_kw=2,
            export_kw=1,
            discharge_efficiency=0.9,
            phases=1,
            phase_limit_kw=4,
        ),
    )
    actual = joint_plan.calculate_joint_plan(data, **kwargs).as_dict()
    monkeypatch.setattr(
        joint_plan, "_simulate", full_joint_simulator(joint_plan._simulate)
    )
    assert actual == joint_plan.calculate_joint_plan(data, **kwargs).as_dict()


def test_joint_trial_reuses_unchanged_prefix_and_converged_suffix():
    data = sample_data(0, count=576)
    data = replace(
        data,
        battery_soc=100,
        slots=[replace(s, solar_kwh=1, consumption_kwh=0) for s in data.slots],
    )
    slots = joint_plan.normalized_joint_slots(data, {})
    limits = JointLimits()
    reserve = joint_plan._reserve(data, slots, limits)
    loads = [{} for _ in slots]
    grid = [0.0] * len(slots)
    baseline = joint_plan._simulate(data, slots, limits, reserve, loads, grid)
    loads[200]["water"] = 0.1
    candidate = joint_plan._simulate(
        data,
        slots,
        limits,
        reserve,
        loads,
        grid,
        [p["grid_charge_ac_kwh"] for p in baseline],
        replay=joint_plan._Replay(baseline, 200, 0),
    )
    assert candidate[200]["managed_by_source"] == {"water": 0.1}
    assert all(candidate[i] is baseline[i] for i in range(576) if i != 200)


def test_reserve_budget_preserves_duplicate_slot_behavior():
    data = sample_data(0)
    data = replace(data, slots=[data.slots[0], *data.slots])
    kwargs = dict(
        managed_consumption_by_slot={}, grid_charge_target_soc=60, nt_lock_soc=40
    )
    actual = planner.SocGridBudget(data, **kwargs)
    expected = FullForecastBudget(data, **kwargs)
    for start in [data.slots[0].start, data.slots[1].start, data.slots[-1].start]:
        assert actual.add(start, 0.2) == expected.add(start, 0.2)
