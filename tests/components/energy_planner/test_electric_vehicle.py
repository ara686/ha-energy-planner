from __future__ import annotations

import math

import pytest

from custom_components.energy_planner.electric_vehicle import (
    ElectricVehicleInput,
    calculate_electric_vehicle_demand,
)


def test_electric_vehicle_converts_battery_demand_through_efficiency():
    demand = calculate_electric_vehicle_demand(ElectricVehicleInput(18, 0.9))

    assert demand.battery_required_kwh == 18
    assert demand.electrical_required_kwh == 20
    assert demand.electrical_remaining_kwh == 20
    assert demand.battery_remaining_kwh == 18


def test_electric_vehicle_zero_demand_is_valid():
    demand = calculate_electric_vehicle_demand(ElectricVehicleInput(0, 0.8))

    assert demand.electrical_required_kwh == 0
    assert demand.battery_remaining_kwh == 0


@pytest.mark.parametrize(
    "data",
    [
        ElectricVehicleInput(-1, 0.9),
        ElectricVehicleInput(1, 0),
        ElectricVehicleInput(1, 1.01),
        ElectricVehicleInput(math.inf, 0.9),
        ElectricVehicleInput(1, math.nan),
    ],
)
def test_electric_vehicle_rejects_invalid_parameters(data):
    with pytest.raises(ValueError):
        calculate_electric_vehicle_demand(data)


def test_electric_vehicle_carries_only_remaining_electrical_demand():
    demand = calculate_electric_vehicle_demand(ElectricVehicleInput(9, 0.9))

    carried = demand.with_electrical_remaining(4)

    assert carried.battery_required_kwh == 9
    assert carried.electrical_required_kwh == 10
    assert carried.electrical_remaining_kwh == 4
    assert carried.battery_remaining_kwh == pytest.approx(3.6)
