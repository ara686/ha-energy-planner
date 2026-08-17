from __future__ import annotations

import pytest

from custom_components.energy_planner.hot_water import (
    HotWaterInput,
    calculate_hot_water_demand,
)


def test_hot_water_demand_uses_average_temperature_and_physical_energy():
    demand = calculate_hot_water_demand(
        HotWaterInput(
            top_temperature_c=50,
            bottom_temperature_c=30,
            minimum_temperature_c=45,
            maximum_temperature_c=70,
            tank_volume_liters=200,
            thermal_conversion_factor=1,
        )
    )

    assert demand.average_temperature_c == 40
    assert demand.minimum_required_kwh == pytest.approx(1.163)
    assert demand.maximum_capacity_kwh == pytest.approx(6.978)
    assert demand.flexible_capacity_kwh == pytest.approx(5.815)


@pytest.mark.parametrize(
    ("factor", "expected_minimum"),
    [(0.5, 2.326), (1, 1.163), (2, 0.5815)],
)
def test_hot_water_conversion_factor_converts_thermal_to_electrical_energy(
    factor,
    expected_minimum,
):
    demand = calculate_hot_water_demand(HotWaterInput(50, 30, 45, 70, 200, factor))

    assert demand.minimum_required_kwh == pytest.approx(expected_minimum)


def test_hot_water_has_no_capacity_when_average_is_above_maximum():
    demand = calculate_hot_water_demand(HotWaterInput(75, 71, 45, 70, 200, 1))

    assert demand.minimum_required_kwh == 0
    assert demand.flexible_capacity_kwh == 0
    assert demand.maximum_capacity_kwh == 0


@pytest.mark.parametrize(
    "input_data",
    [
        HotWaterInput(50, 30, 70, 70, 200, 1),
        HotWaterInput(50, 30, 45, 70, 0, 1),
        HotWaterInput(50, 30, 45, 70, 200, 0),
        HotWaterInput(float("nan"), 30, 45, 70, 200, 1),
        HotWaterInput(50, 30, 45, float("inf"), 200, 1),
    ],
)
def test_hot_water_rejects_invalid_physical_parameters(input_data):
    with pytest.raises(ValueError):
        calculate_hot_water_demand(input_data)
