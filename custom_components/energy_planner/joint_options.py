"""UI-configurable joint-planner policy and optional technical sources."""

from __future__ import annotations

from datetime import time
from math import isfinite
from typing import Any

DEFAULTS: dict[str, Any] = {
    "joint_planning_mode": "shadow",
    "joint_ev_phases": 3,
    "joint_solar_ev_phases": 1,
    "joint_maximum_ev_current": 16.0,
    "joint_voltage": 230.0,
    "joint_minimum_ev_current": 6.0,
    "joint_discharge_efficiency": 1.0,
    "joint_water_minimum": 40.0,
    "joint_water_normal": 45.0,
    "joint_water_maximum": 65.0,
    "joint_water_deadline": "17:00:00",
}
ENTITY_KEYS = (
    "joint_grid_import_limit_entity",
    "joint_battery_charge_limit_entity",
    "joint_battery_discharge_limit_entity",
    "joint_export_limit_entity",
    "joint_phase_limit_entity",
)
OPTIONAL_NUMBERS = ("joint_water_loss_kw", "joint_water_daily_draw_kwh")


def normalize_joint_options(values: dict[str, Any]) -> dict[str, Any]:
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    if result["joint_planning_mode"] not in {"shadow", "advisory"}:
        raise ValueError("Invalid joint planning mode")
    for key in DEFAULTS.keys() - {"joint_planning_mode", "joint_water_deadline"}:
        result[key] = float(result[key])
        if not isfinite(result[key]):
            raise ValueError("Joint options must be finite")
    if result["joint_ev_phases"] not in {1, 3} or result[
        "joint_solar_ev_phases"
    ] not in {1, 3}:
        raise ValueError("EV phases must be 1 or 3")
    result["joint_ev_phases"] = int(result["joint_ev_phases"])
    result["joint_solar_ev_phases"] = int(result["joint_solar_ev_phases"])
    if result["joint_maximum_ev_current"] < result["joint_minimum_ev_current"]:
        raise ValueError("Maximum EV current is below minimum")
    if not 0 < result["joint_discharge_efficiency"] <= 1:
        raise ValueError("Invalid discharge efficiency")
    if result["joint_voltage"] <= 0 or result["joint_minimum_ev_current"] < 6:
        raise ValueError("Invalid charging voltage or current")
    if (
        not 0
        < result["joint_water_minimum"]
        <= result["joint_water_normal"]
        <= result["joint_water_maximum"]
        <= 100
    ):
        raise ValueError("Invalid water targets")
    result["joint_water_deadline"] = time.fromisoformat(
        result["joint_water_deadline"]
    ).isoformat()
    for key in ENTITY_KEYS:
        if values.get(key):
            value = str(values[key])
            if not value.startswith(("sensor.", "number.", "input_number.")):
                raise ValueError("Invalid power-limit entity")
            result[key] = value
    for key in OPTIONAL_NUMBERS:
        if values.get(key) is not None:
            result[key] = float(values[key])
            if not isfinite(result[key]) or result[key] < 0:
                raise ValueError("Invalid thermal estimate")
    return result
