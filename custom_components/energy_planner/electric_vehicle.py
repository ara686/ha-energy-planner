"""Pure electric-vehicle charging demand model."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ElectricVehicleInput:
    """Current vehicle-side charging requirement."""

    battery_required_kwh: float
    charging_efficiency: float


@dataclass(frozen=True)
class ElectricVehicleDemand:
    """Vehicle demand normalized to charger input energy."""

    battery_required_kwh: float
    electrical_required_kwh: float
    electrical_remaining_kwh: float
    charging_efficiency: float

    @property
    def battery_remaining_kwh(self) -> float:
        """Return the battery-side equivalent of the remaining input energy."""
        return self.electrical_remaining_kwh * self.charging_efficiency

    def with_electrical_remaining(self, value: float) -> ElectricVehicleDemand:
        """Return a demand snapshot with a reduced carried requirement."""
        return replace(self, electrical_remaining_kwh=max(float(value), 0.0))


def calculate_electric_vehicle_demand(
    data: ElectricVehicleInput,
) -> ElectricVehicleDemand:
    """Convert battery-side required energy to charger input energy."""
    values = (data.battery_required_kwh, data.charging_efficiency)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Electric-vehicle inputs must be finite")
    if data.battery_required_kwh < 0:
        raise ValueError("Required battery energy must be non-negative")
    if not 0 < data.charging_efficiency <= 1:
        raise ValueError(
            "Charging efficiency must be greater than zero and at most one"
        )

    electrical_required = data.battery_required_kwh / data.charging_efficiency
    return ElectricVehicleDemand(
        battery_required_kwh=float(data.battery_required_kwh),
        electrical_required_kwh=electrical_required,
        electrical_remaining_kwh=electrical_required,
        charging_efficiency=float(data.charging_efficiency),
    )
