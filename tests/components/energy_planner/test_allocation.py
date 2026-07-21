from __future__ import annotations

from datetime import date

from custom_components.energy_planner.allocation import (
    ManagedLoadDemandInput,
    calculate_surplus_allocation,
)


def test_history_estimate_uses_active_probability_and_active_day_median():
    result = calculate_surplus_allocation(
        target_date=date(2026, 7, 22),
        available_surplus_kwh=10,
        surplus_complete=True,
        loads=[
            ManagedLoadDemandInput(
                source_id="sensor.water_heater_energy_total",
                daily_kwh=[0, 3, 0, 4, 3, 0, 5],
            )
        ],
    )

    load = result.loads[0]
    assert load.method == "history"
    assert load.observed_days == 7
    assert load.active_days == 4
    assert load.active_probability == 0.571
    assert load.active_day_median_kwh == 3.5
    assert load.expected_demand_kwh == 2.0
    assert load.recommended_kwh == 2.0
    assert result.unallocated_surplus_kwh == 8.0


def test_insufficient_surplus_is_distributed_proportionally():
    result = calculate_surplus_allocation(
        target_date=date(2026, 7, 22),
        available_surplus_kwh=3,
        surplus_complete=True,
        loads=[
            ManagedLoadDemandInput("sensor.boiler", [2, 2, 2]),
            ManagedLoadDemandInput("sensor.pool", [4, 4, 4]),
        ],
    )

    assert result.state == "ok"
    assert result.expected_demand_kwh == 6
    assert result.loads[0].recommended_kwh == 1
    assert result.loads[1].recommended_kwh == 2
    assert result.recommended_kwh == 3
    assert result.unallocated_surplus_kwh == 0


def test_requested_energy_overrides_history_for_one_load():
    result = calculate_surplus_allocation(
        target_date=date(2026, 7, 22),
        available_surplus_kwh=20,
        surplus_complete=True,
        loads=[
            ManagedLoadDemandInput(
                "sensor.ev",
                [2, 2, 2, 2, 2, 2, 2],
                requested_energy_kwh=9,
            )
        ],
    )

    load = result.loads[0]
    assert load.method == "requested"
    assert load.reason == "requested_energy"
    assert load.expected_demand_kwh == 9
    assert load.recommended_kwh == 9
    assert load.confidence == "high"


def test_incomplete_tomorrow_forecast_withholds_recommendation():
    result = calculate_surplus_allocation(
        target_date=date(2026, 7, 22),
        available_surplus_kwh=5,
        surplus_complete=False,
        loads=[ManagedLoadDemandInput("sensor.pool", [4, 4, 4])],
    )

    assert result.state == "insufficient_data"
    assert result.available_surplus_kwh is None
    assert result.expected_demand_kwh == 4
    assert result.recommended_kwh is None
    assert result.loads[0].recommended_kwh is None


def test_fewer_than_three_observed_days_do_not_create_history_demand():
    result = calculate_surplus_allocation(
        target_date=date(2026, 7, 22),
        available_surplus_kwh=5,
        surplus_complete=True,
        loads=[ManagedLoadDemandInput("sensor.pool", [4, 4])],
    )

    assert result.state == "insufficient_data"
    assert result.loads[0].method == "insufficient_data"
    assert result.loads[0].confidence == "insufficient"
    assert result.loads[0].recommended_kwh == 0
