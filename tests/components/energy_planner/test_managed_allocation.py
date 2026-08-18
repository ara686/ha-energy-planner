from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from custom_components.energy_planner.allocation import ManagedLoadEstimate
from custom_components.energy_planner.hot_water import HotWaterDemand
from custom_components.energy_planner.managed_allocation import (
    GenericAllocationInput,
    HotWaterAllocationInput,
    SurplusSlot,
    UnavailableAllocationInput,
    allocate_managed_day,
)


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
    assert result.available_surplus_kwh is None
    assert result.recommended_kwh is None
    assert result.loads[0].recommended_kwh is None
    assert result.loads[0].minimum_shortfall_kwh is None


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
