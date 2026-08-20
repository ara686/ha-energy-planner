from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.energy_planner.allocation import ManagedLoadEstimate
from custom_components.energy_planner.electric_vehicle import (
    ElectricVehicleInput,
    calculate_electric_vehicle_demand,
)
from custom_components.energy_planner.hot_water import HotWaterDemand
from custom_components.energy_planner.managed_allocation import (
    ElectricVehicleAllocationInput,
    GenericAllocationInput,
    HotWaterAllocationInput,
    SurplusSlot,
    UnavailableAllocationInput,
    allocate_managed_day,
)


def test_allocation_runs_all_four_phases_in_order():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, 9)],
        loads=[
            _hot_water("boiler", required=2, flexible=3, power=20),
            _electric_vehicle("car", required=4, power=20),
            _generic("generic", expected=2),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert loads["boiler"].minimum_allocated_kwh == 2
    assert loads["car"].recommended_kwh == 4
    assert loads["generic"].recommended_kwh == 2
    assert loads["boiler"].recommended_kwh == 3


def test_ev_priority_and_equal_priority_shortage_are_proportional():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, 5)],
        loads=[
            _electric_vehicle("first", required=2, power=20, priority=1),
            _electric_vehicle("small", required=2, power=20, priority=2),
            _electric_vehicle("large", required=4, power=20, priority=2),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert loads["first"].recommended_kwh == 2
    assert loads["small"].recommended_kwh == pytest.approx(1)
    assert loads["large"].recommended_kwh == pytest.approx(2)


def test_ev_power_limit_and_shortfall_are_reported_in_both_energy_domains():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=30,
        surplus_complete=True,
        surplus_slots=[
            SurplusSlot(start, 10),
            SurplusSlot(start + timedelta(minutes=30), 10),
        ],
        loads=[_electric_vehicle("car", required=10, power=2, efficiency=0.8)],
    )

    load = result.loads[0].as_dict()
    assert load["recommended_kwh"] == 2
    assert load["electrical_shortfall_kwh"] == 8
    assert load["battery_shortfall_kwh"] == pytest.approx(6.4)
    assert load["battery_required_kwh"] == 8
    assert load["electrical_required_kwh"] == 10
    assert load["electrical_remaining_before_kwh"] == 10
    assert load["method"] == "ev_request"
    assert all(value <= 1 for value in result.electric_vehicle_energy_by_slot.values())


def test_allocation_runs_hot_water_minimum_generic_then_hot_water_flexible():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[
            SurplusSlot(start + timedelta(hours=index), 2) for index in range(4)
        ],
        loads=[
            _hot_water("boiler", required=2, flexible=4, power=2),
            _generic("pool", expected=3),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert loads["boiler"].minimum_allocated_kwh == 2
    assert loads["boiler"].recommended_kwh == 5
    assert loads["boiler"].minimum_shortfall_kwh == 0
    assert loads["pool"].recommended_kwh == 3
    assert result.recommended_kwh == 8
    assert result.unallocated_surplus_kwh == 0
    assert sum(result.hot_water_energy_by_slot.values()) == 5


def test_hot_water_power_limits_each_slot_across_minimum_and_flexible_phases():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=30,
        surplus_complete=True,
        surplus_slots=[
            SurplusSlot(start + timedelta(minutes=30 * index), 5) for index in range(2)
        ],
        loads=[_hot_water("boiler", required=1.5, flexible=5, power=2)],
    )

    load = result.loads[0]
    assert load.recommended_kwh == 2
    assert load.minimum_allocated_kwh == 1.5
    assert load.minimum_shortfall_kwh == 0
    assert all(value <= 1 for value in result.hot_water_energy_by_slot.values())


def test_timeline_is_separate_per_source_and_preserves_slot_gaps():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[
            SurplusSlot(start, 4),
            SurplusSlot(start + timedelta(hours=1), 4),
            SurplusSlot(start + timedelta(hours=3), 4),
        ],
        loads=[
            _hot_water("first", required=6, flexible=0, power=10),
            _hot_water("second", required=6, flexible=0, power=10),
        ],
    )

    loads = {load.source_id: load.as_dict() for load in result.loads}
    assert loads["first"]["timeline"] == [
        {
            "start": "2026-08-19T10:00:00",
            "end": "2026-08-19T12:00:00",
            "mode": "solar",
            "energy_kwh": 4,
        },
        {
            "start": "2026-08-19T13:00:00",
            "end": "2026-08-19T14:00:00",
            "mode": "solar",
            "energy_kwh": 2,
        },
    ]
    assert loads["second"]["timeline"] == loads["first"]["timeline"]
    assert sum(window["energy_kwh"] for window in loads["first"]["timeline"]) == 6


def test_timeline_merges_elapsed_slots_across_dst_fallback():
    timezone = ZoneInfo("Europe/Prague")
    first = datetime(2026, 10, 25, 2, 30, tzinfo=timezone, fold=0)
    repeated = (first.astimezone(UTC) + timedelta(hours=1)).astimezone(timezone)
    result = allocate_managed_day(
        target_date=first.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(first, 1), SurplusSlot(repeated, 1)],
        loads=[_electric_vehicle("car", required=2, power=2)],
    )

    assert result.loads[0].as_dict()["timeline"] == [
        {
            "start": "2026-10-25T00:30:00+00:00",
            "end": "2026-10-25T02:30:00+00:00",
            "mode": "solar",
            "energy_kwh": 2,
        }
    ]


@pytest.mark.parametrize(
    ("available", "required", "flexible", "recommended", "target", "shortfall"),
    [
        (6, 2, 4, 6, 70, 0),
        (4, 2, 4, 4, 60, 0),
        (2, 4, 2, 2, 50, 2),
        (0, 0, 0, 0, 40, 0),
    ],
)
def test_hot_water_planned_target_temperature(
    available,
    required,
    flexible,
    recommended,
    target,
    shortfall,
):
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, available)],
        loads=[
            _hot_water(
                "boiler",
                required=required,
                flexible=flexible,
                power=20,
            )
        ],
    )

    load = result.loads[0].as_dict()
    assert load["recommended_kwh"] == recommended
    assert load["planned_target_temperature"] == target
    assert load["minimum_shortfall_kwh"] == shortfall


def test_lower_number_priority_is_allocated_first():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, 4)],
        loads=[
            _hot_water("first", required=4, flexible=0, power=10, priority=1),
            _hot_water("second", required=4, flexible=0, power=10, priority=2),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert loads["first"].recommended_kwh == 4
    assert loads["second"].recommended_kwh == 0
    assert loads["second"].minimum_shortfall_kwh == 4


def test_equal_priorities_share_shortage_proportionally():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, 3)],
        loads=[
            _hot_water("small", required=2, flexible=0, power=10),
            _hot_water("large", required=4, flexible=0, power=10),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert loads["small"].recommended_kwh == pytest.approx(1)
    assert loads["large"].recommended_kwh == pytest.approx(2)


def test_equal_priority_redistribution_respects_each_slot_power_cap():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, 6)],
        loads=[
            _hot_water("one_kw", required=10, flexible=0, power=1),
            _hot_water("four_kw", required=10, flexible=0, power=4),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert loads["one_kw"].recommended_kwh == 1
    assert loads["four_kw"].recommended_kwh == 4
    assert result.unallocated_surplus_kwh == 1


def test_incomplete_day_withholds_recommendations():
    target = date(2026, 8, 19)
    result = allocate_managed_day(
        target_date=target,
        interval_minutes=60,
        surplus_complete=False,
        surplus_slots=[],
        loads=[_hot_water("boiler", required=2, flexible=4, power=2)],
    )

    assert result.state == "insufficient_data"
    assert result.forecast_complete is False
    assert result.available_surplus_kwh is None
    assert result.recommended_kwh is None
    assert result.loads[0].recommended_kwh is None
    assert result.loads[0].minimum_shortfall_kwh is None
    assert result.loads[0].as_dict()["timeline"] == []


def test_valid_hot_water_load_with_no_deficit_recommends_zero():
    target = date(2026, 8, 19)
    result = allocate_managed_day(
        target_date=target,
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(datetime(2026, 8, 19, 10), 5)],
        loads=[_hot_water("boiler", required=0, flexible=0, power=2)],
    )

    assert result.state == "ok"
    assert result.recommended_kwh == 0
    assert result.loads[0].state == "ok"
    assert result.loads[0].recommended_kwh == 0


def test_unavailable_hot_water_load_does_not_block_generic_allocation():
    start = datetime(2026, 8, 19, 10)
    result = allocate_managed_day(
        target_date=start.date(),
        interval_minutes=60,
        surplus_complete=True,
        surplus_slots=[SurplusSlot(start, 3)],
        loads=[
            UnavailableAllocationInput(
                "boiler", "hot_water", 1, "invalid_temperature_source"
            ),
            _generic("generic", expected=2, priority=2),
        ],
    )

    loads = {load.source_id: load for load in result.loads}
    assert result.state == "ok"
    assert loads["boiler"].recommended_kwh is None
    assert loads["generic"].recommended_kwh == 2
    assert result.unallocated_surplus_kwh == 1


def _hot_water(
    source_id: str,
    *,
    required: float,
    flexible: float,
    power: float,
    priority: int = 100,
) -> HotWaterAllocationInput:
    return HotWaterAllocationInput(
        source_id=source_id,
        priority=priority,
        heater_power_kw=power,
        demand=HotWaterDemand(
            top_temperature_c=50,
            bottom_temperature_c=30,
            average_temperature_c=40,
            minimum_temperature_c=45,
            maximum_temperature_c=70,
            minimum_required_kwh=required,
            flexible_capacity_kwh=flexible,
            maximum_capacity_kwh=required + flexible,
        ),
    )


def _generic(
    source_id: str,
    *,
    expected: float,
    priority: int = 100,
) -> GenericAllocationInput:
    return GenericAllocationInput(
        source_id=source_id,
        priority=priority,
        estimate=ManagedLoadEstimate(
            source_id=source_id,
            method="history",
            expected_demand_kwh=expected,
            recommended_kwh=None,
            observed_days=7,
            active_days=7,
            active_probability=1,
            active_day_median_kwh=expected,
            confidence="high",
            reason="historical_daily_usage",
        ),
    )


def _electric_vehicle(
    source_id: str,
    *,
    required: float,
    power: float,
    priority: int = 100,
    efficiency: float = 1,
) -> ElectricVehicleAllocationInput:
    demand = calculate_electric_vehicle_demand(
        ElectricVehicleInput(
            battery_required_kwh=required * efficiency,
            charging_efficiency=efficiency,
        )
    )
    return ElectricVehicleAllocationInput(
        source_id=source_id,
        priority=priority,
        maximum_charging_power_kw=power,
        demand=demand,
    )
