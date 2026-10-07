"""Compare a deterministic 48-hour workload with a locally available Git revision.

Run with: uv run --extra ha --extra dev python scripts/benchmark_planner.py
The baseline revision is executed as Python code; use only trusted revisions.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median
from time import perf_counter
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def baseline_module(name: str, revision: str) -> ModuleType:
    """Read an existing local revision without changing the working tree."""
    filename = f"custom_components/energy_planner/{name}.py"
    source = subprocess.check_output(
        ["git", "show", f"{revision}:{filename}"], cwd=ROOT, text=True
    )
    module_name = f"custom_components.energy_planner._benchmark_{name}"
    module = ModuleType(module_name)
    module.__package__ = "custom_components.energy_planner"
    sys.modules[module_name] = module
    exec(compile(source, filename, "exec"), module.__dict__)
    return module


def main() -> None:
    from custom_components.energy_planner.coordinator import (
        _reserve_safe_direct_solar_slots,
    )
    from custom_components.energy_planner.joint_plan import (
        JointLimits,
        JointWater,
        calculate_joint_plan,
    )
    from custom_components.energy_planner.managed_allocation import SurplusSlot
    from custom_components.energy_planner.models import (
        ForecastSlot,
        PlannerInput,
        TimeWindow,
    )
    from custom_components.energy_planner.planner import calculate_plan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="v0.1.33")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    old_planner = baseline_module("planner", args.baseline)
    old_coordinator = baseline_module("coordinator", args.baseline)
    old_joint = baseline_module("joint_plan", args.baseline)
    old_coordinator.calculate_soc_forecast = old_planner.calculate_soc_forecast
    now = datetime(2026, 10, 7, tzinfo=UTC)
    data = PlannerInput(
        now,
        40,
        24,
        15,
        [
            ForecastSlot(
                now + timedelta(minutes=5 * i),
                max(0, math.sin(math.pi * ((i % 288) / 12 - 6) / 12)) * 0.65,
                0.065,
            )
            for i in range(576)
        ],
        [TimeWindow("00:00", "06:00"), TimeWindow("16:00", "17:00")],
        TimeWindow("00:00", "06:00"),
        interval_minutes=5,
        forecast_horizon_hours=48,
    )
    water = [JointWater("tank", 35, 300, 3, loss_kw=0.08, daily_draw_kwh=6)]
    limits = JointLimits(
        grid_import_kw=8, battery_charge_kw=5, battery_discharge_kw=5, export_kw=5
    )
    reserve_kwargs = dict(
        planner_input=data,
        result=calculate_plan(data),
        candidate_slots=[
            SurplusSlot(s.start, max(0, s.solar_kwh - s.consumption_kwh))
            for s in data.slots
        ],
        existing_managed_energy_by_slot={},
        maximum_energy_kwh=30,
        maximum_power_kw=3,
    )
    cases = {
        "solar_reserve": (
            lambda: old_coordinator._reserve_safe_direct_solar_slots(**reserve_kwargs),
            lambda: _reserve_safe_direct_solar_slots(**reserve_kwargs),
        ),
        "joint_water_plan": (
            lambda: old_joint.calculate_joint_plan(
                data, water=water, limits=limits
            ).as_dict(),
            lambda: calculate_joint_plan(data, water=water, limits=limits).as_dict(),
        ),
    }
    report = {"baseline": args.baseline, "slots": 576, "repetitions": args.repeat}
    for name, (before, after) in cases.items():
        timings = [[], []]
        for _ in range(args.repeat):
            results = []
            for index, function in enumerate((before, after)):
                start = perf_counter()
                results.append(function())
                timings[index].append(perf_counter() - start)
            if results[0] != results[1]:
                raise AssertionError(f"Planner output changed: {name}")
        original, optimized = (median(values) for values in timings)
        report[name] = {
            "baseline_seconds": round(original, 6),
            "optimized_seconds": round(optimized, 6),
            "speedup": round(original / optimized, 2),
            "identical_results": True,
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
