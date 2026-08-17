"""Pure hot-water thermal demand model."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

WATER_HEAT_CAPACITY_KWH_PER_LITER_K = 0.001163


@dataclass(frozen=True)
class HotWaterInput:
    """Current hot-water tank state and fixed installation parameters."""

    top_temperature_c: float
    bottom_temperature_c: float
    minimum_temperature_c: float
    maximum_temperature_c: float
    tank_volume_liters: float
    thermal_conversion_factor: float


@dataclass(frozen=True)
class HotWaterDemand:
    """Electrical energy targets calculated from the tank state."""

    top_temperature_c: float
    bottom_temperature_c: float
    average_temperature_c: float
    minimum_temperature_c: float
    maximum_temperature_c: float
    minimum_required_kwh: float
    flexible_capacity_kwh: float
    maximum_capacity_kwh: float

    def as_dict(self) -> dict[str, Any]:
        """Return a compact serializable representation."""
        return {
            "top_temperature": round(self.top_temperature_c, 3),
            "bottom_temperature": round(self.bottom_temperature_c, 3),
            "average_temperature": round(self.average_temperature_c, 3),
            "minimum_temperature": round(self.minimum_temperature_c, 3),
            "maximum_temperature": round(self.maximum_temperature_c, 3),
            "minimum_required_kwh": round(self.minimum_required_kwh, 6),
            "flexible_capacity_kwh": round(self.flexible_capacity_kwh, 6),
            "maximum_capacity_kwh": round(self.maximum_capacity_kwh, 6),
        }


def calculate_hot_water_demand(data: HotWaterInput) -> HotWaterDemand:
    """Calculate electrical energy needed to reach average tank targets."""
    values = (
        data.top_temperature_c,
        data.bottom_temperature_c,
        data.minimum_temperature_c,
        data.maximum_temperature_c,
        data.tank_volume_liters,
        data.thermal_conversion_factor,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Hot-water model inputs must be finite")
    if data.tank_volume_liters <= 0:
        raise ValueError("Tank volume must be greater than zero")
    if data.thermal_conversion_factor <= 0:
        raise ValueError("Thermal conversion factor must be greater than zero")
    if data.minimum_temperature_c >= data.maximum_temperature_c:
        raise ValueError("Minimum temperature must be below maximum temperature")

    average_temperature = (data.top_temperature_c + data.bottom_temperature_c) / 2
    minimum_required = _electrical_energy_to_target(
        current_temperature_c=average_temperature,
        target_temperature_c=data.minimum_temperature_c,
        tank_volume_liters=data.tank_volume_liters,
        thermal_conversion_factor=data.thermal_conversion_factor,
    )
    maximum_capacity = _electrical_energy_to_target(
        current_temperature_c=average_temperature,
        target_temperature_c=data.maximum_temperature_c,
        tank_volume_liters=data.tank_volume_liters,
        thermal_conversion_factor=data.thermal_conversion_factor,
    )
    return HotWaterDemand(
        top_temperature_c=data.top_temperature_c,
        bottom_temperature_c=data.bottom_temperature_c,
        average_temperature_c=average_temperature,
        minimum_temperature_c=data.minimum_temperature_c,
        maximum_temperature_c=data.maximum_temperature_c,
        minimum_required_kwh=minimum_required,
        flexible_capacity_kwh=max(maximum_capacity - minimum_required, 0.0),
        maximum_capacity_kwh=maximum_capacity,
    )


def _electrical_energy_to_target(
    *,
    current_temperature_c: float,
    target_temperature_c: float,
    tank_volume_liters: float,
    thermal_conversion_factor: float,
) -> float:
    thermal_kwh = (
        WATER_HEAT_CAPACITY_KWH_PER_LITER_K
        * tank_volume_liters
        * max(target_temperature_c - current_temperature_c, 0.0)
    )
    return thermal_kwh / thermal_conversion_factor
