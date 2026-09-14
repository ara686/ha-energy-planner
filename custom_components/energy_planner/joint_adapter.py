"""HA input adapter for the pure joint planner and its shadow comparison."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time, timedelta
from typing import Any

from .ev_plan import EVChargingPlanInput
from .joint_options import normalize_joint_options
from .joint_plan import JointLimits, JointWater, calculate_joint_plan, instant
from .managed_allocation import ElectricVehicleAllocationInput, HotWaterAllocationInput
from .managed_loads import managed_load_configs
from .models import PlannerInput, PlannerResult
from .planner import generate_forecast_slots


def add_joint_plan(
    hass,
    entry,
    *,
    history,
    now: datetime,
    planner_input: PlannerInput,
    allocations,
    result: PlannerResult,
) -> None:
    """Read the same state snapshot as the compatibility planner."""
    from .coordinator import (
        _binary_state_value,
        _electric_vehicle_allocation_input,
        _hot_water_allocation_input,
        _power_entity_kw,
        _presence_state_value,
        _solcast_forecast,
    )

    options = normalize_joint_options(dict(entry.options))
    warnings: list[str] = []
    profile = history.hourly_base_consumption_profile(
        now=now,
        learning_days=int(entry.options.get("history_learning_days", 3)),
        margin_percent=0,
        include_current_hour=False,
    )
    baseline = float(entry.options.get("min_baseline_kwh_per_hour", 0.2))
    # Generate an overlapping first interval, then clip it with exact elapsed time.
    interval = planner_input.interval_minutes
    start = now.replace(
        minute=now.minute - now.minute % interval, second=0, microsecond=0
    )
    slots = generate_forecast_slots(
        now=start,
        horizon_hours=planner_input.forecast_horizon_hours + 1,
        interval_minutes=interval,
        solar_forecast=_solcast_forecast(hass, entry, warnings),
        consumption_kwh_per_hour=lambda t: max(baseline, profile.get(t.hour, baseline)),
    )
    data = replace(planner_input, slots=slots)
    generic: dict[datetime, dict[str, float]] = {}
    for allocation in allocations:
        for (
            source_id,
            timestamp,
        ), energy in allocation.generic_energy_by_source_slot.items():
            generic.setdefault(timestamp, {})[source_id] = energy
    if not profile:
        warnings.append("unverified_house_consumption_profile")
    vehicles = []
    tanks = []
    unavailable: dict[str, dict[str, Any]] = {}
    for load in managed_load_configs(entry):
        if load.is_electric_vehicle:
            allocation_input = _electric_vehicle_allocation_input(hass, load, warnings)
            if not isinstance(allocation_input, ElectricVehicleAllocationInput):
                unavailable[load.source_entity_id] = {
                    "mode": "unavailable",
                    "recommended_mode": "unavailable",
                    "reason": "invalid_required_energy_source",
                    "shortfall_kwh": None,
                }
                continue
            connected = _binary_state_value(
                hass.states.get(load.ev_connected_entity_id or "")
            )
            present = (
                True
                if connected is True
                else _presence_state_value(
                    hass.states.get(load.ev_presence_entity_id or "")
                )
            )
            vehicles.append(
                EVChargingPlanInput(
                    source_id=load.source_entity_id,
                    priority=load.priority,
                    required_input_kwh=allocation_input.demand.electrical_remaining_kwh,
                    maximum_charging_power_kw=load.maximum_charging_power_kw or 0,
                    workdays=load.ev_workdays,
                    departure_time=load.ev_departure_time,
                    return_time=load.ev_return_time,
                    currently_home=present,
                    connected=connected,
                    allow_home_battery=load.ev_allow_home_battery,
                    allow_high_tariff_grid=_binary_state_value(
                        hass.states.get(load.ev_grid_outside_nt_entity_id or "")
                    )
                    is True,
                )
            )
        elif load.is_hot_water:
            allocation_input = _hot_water_allocation_input(hass, load, warnings)
            if not isinstance(allocation_input, HotWaterAllocationInput):
                warnings.append(f"invalid_water_source:{load.source_entity_id}")
                continue
            tanks.append(
                JointWater(
                    source_id=load.source_entity_id,
                    priority=load.priority,
                    temperature=allocation_input.demand.average_temperature_c,
                    volume_liters=load.tank_volume_liters or 0,
                    heater_kw=load.heater_power_kw or 0,
                    efficiency=load.thermal_conversion_factor or 1,
                    minimum=options["joint_water_minimum"],
                    normal=options["joint_water_normal"],
                    maximum=options["joint_water_maximum"],
                    deadline=time.fromisoformat(options["joint_water_deadline"]),
                    gas_backup=load.hot_water_alternative_source == "gas",
                    loss_kw=options.get("joint_water_loss_kw"),
                    daily_draw_kwh=options.get("joint_water_daily_draw_kwh"),
                )
            )

    def limit(key: str) -> float | None:
        entity_id = options.get(key)
        value = _power_entity_kw(hass, entity_id) if entity_id else None
        if entity_id and (value is None or value < 0):
            warnings.append(f"invalid_limit_source:{entity_id}")
            return None
        return value

    limits = JointLimits(
        grid_import_kw=limit("joint_grid_import_limit_entity"),
        battery_charge_kw=limit("joint_battery_charge_limit_entity"),
        battery_discharge_kw=limit("joint_battery_discharge_limit_entity"),
        export_kw=limit("joint_export_limit_entity"),
        phase_limit_kw=limit("joint_phase_limit_entity"),
        discharge_efficiency=options["joint_discharge_efficiency"],
        phases=options["joint_ev_phases"],
        solar_phases=options["joint_solar_ev_phases"],
        maximum_ev_current=options["joint_maximum_ev_current"],
        voltage=options["joint_voltage"],
        minimum_ev_current=options["joint_minimum_ev_current"],
    )
    try:
        joint = calculate_joint_plan(
            data, limits=limits, generic=generic, vehicles=vehicles, water=tanks
        )
    except ValueError as err:
        result.debug["joint_plan"] = {
            "summary": {"state": "insufficient_data"},
            "warnings": [str(err)],
        }
        result.plan["joint_summary"] = {"state": "insufficient_data"}
        if options["joint_planning_mode"] == "advisory":
            result.state = "insufficient_data"
        return
    joint.warnings.extend(warnings)
    joint.vehicles.update(unavailable)
    for source, payload in joint.vehicles.items():
        observed = result.plan.get("ev_charging_plans", {}).get(source, {})
        for key in ("observed_mode", "is_charging", "current_charging_power_kw"):
            payload[key] = observed.get(key)
        if payload.get("observed_mode"):
            payload["mode"] = payload["observed_mode"]
    joint.summary["state"] = "warning" if joint.warnings else joint.summary["state"]
    invalid_limits = any(w.startswith("invalid_limit_source:") for w in warnings)
    if invalid_limits:
        joint.summary["state"] = "insufficient_data"
        joint.summary["target_soc"] = None
    comparison = {
        key: {"compatibility": result.plan.get(key), "joint": joint.summary.get(key)}
        for key in ("target_soc", "lock_soc", "safe_discharge_soc")
    }
    result.debug["joint_plan"] = joint.as_dict()
    result.debug["joint_comparison"] = {
        "same_state_snapshot": True,
        "consumption_policy": "expected_without_margin",
        "values": comparison,
    }
    result.plan["joint_summary"] = joint.summary
    result.plan["joint_planning_mode"] = options["joint_planning_mode"]
    if options["joint_planning_mode"] == "shadow":
        return
    if invalid_limits:
        result.state = "insufficient_data"
        return
    # Preserve IDs, but switch all dependent public values together.
    result.plan.update(
        {
            key: joint.summary[key]
            for key in (
                "target_soc",
                "lock_soc",
                "safe_discharge_soc",
                "current_soc",
                "current_charge_window",
                "charge_now",
                "valid_until",
            )
            if key in joint.summary
        }
    )
    if not joint.points:
        result.state = "insufficient_data"
        return
    result.warnings.extend(joint.warnings)
    result.state = "warning" if result.warnings else "ok"
    result.plan["charge_to_soc"] = joint.summary["current_charge_target_soc"]
    result.plan["ev_charging_plans"] = joint.vehicles
    result.plan["vt_grid_import_kwh_at_target"] = joint.summary["vt_grid_import_kwh"]
    result.plan["charged_kwh_total_at_target"] = sum(
        p["grid_charge_ac_kwh"] * data.grid_charge_efficiency for p in joint.points
    )
    result.plan["free_capacity_soc"] = max(
        0, data.battery_soc - joint.summary["safe_discharge_soc"]
    )
    result.plan["free_capacity_kwh"] = (
        result.plan["free_capacity_soc"] * data.battery_capacity_kwh / 100
    )
    public_points = [
        {
            **p,
            "managed_consumption_kwh": sum(p["managed_by_source"].values()),
            "grid_charge_kwh": p["grid_charge_ac_kwh"] * data.grid_charge_efficiency,
            "solar_coverage": 1.0
            if "incomplete_solar_forecast" not in joint.warnings
            else 0.0,
            "is_charge_window": p["is_nt"] and data.grid_charging_enabled,
        }
        for p in joint.points
    ]
    for key in ("soc_forecast", "soc_forecast_planned", "soc_forecast_with_managed"):
        result.plan[key] = {
            "source": "joint_plan",
            "points": public_points,
            "horizon_hours": data.forecast_horizon_hours,
        }
    for key in (
        "soc_at_forecast_horizon",
        "soc_at_forecast_horizon_planned",
        "soc_at_forecast_horizon_with_managed",
    ):
        result.plan[key] = joint.summary["soc_at_horizon"]
    at_24 = next(
        (
            p
            for p in public_points
            if instant(datetime.fromisoformat(p["timestamp"]))
            >= instant(now) + timedelta(hours=24)
        ),
        None,
    )
    result.plan["soc_forecast_24h"] = at_24
    result.plan["soc_forecast_planned_24h"] = at_24
    result.forecast["points"] = public_points
    _publish_managed_results(result, joint, managed_load_configs(entry), now)


def _publish_managed_results(result, joint, configured_loads, now):
    """Expose only allocations from the final ledger in advisory mode."""
    days = sorted({datetime.fromisoformat(p["start"]).date() for p in joint.points})
    payloads = []
    daily_surplus = []
    for day in days:
        points = [
            p for p in joint.points if datetime.fromisoformat(p["start"]).date() == day
        ]
        sources = {}
        for load in configured_loads:
            source = load.source_entity_id
            energy = sum(p["managed_by_source"].get(source, 0.0) for p in points)
            ev = joint.vehicles.get(source)
            tank = joint.water.get(source)
            info = ev or tank or {}
            timeline = [
                a
                for a in info.get("timeline", [])
                if datetime.fromisoformat(a["start"]).date() == day
            ]
            sources[source] = {
                "source_entity_id": source,
                "load_type": load.load_type,
                "priority": load.priority,
                "state": "insufficient_data"
                if ev and ev["mode"] == "unavailable"
                else "ok",
                "method": "joint_plan",
                "expected_demand_kwh": energy,
                "recommended_kwh": None
                if ev and ev["mode"] == "unavailable"
                else energy,
                "reason": info.get("reason", "joint_plan"),
                "timeline": timeline,
            }
            if ev:
                sources[source].update(
                    {
                        "electrical_shortfall_kwh": ev.get("shortfall_kwh"),
                        "battery_shortfall_kwh": None
                        if ev.get("shortfall_kwh") is None
                        else ev["shortfall_kwh"] * load.charging_efficiency,
                        "charging_efficiency": load.charging_efficiency,
                    }
                )
            if tank:
                deadline = next(
                    (
                        d
                        for d in tank["deadlines"]
                        if datetime.fromisoformat(d["deadline"]).date() == day
                    ),
                    None,
                )
                sources[source].update(
                    {
                        "minimum_temperature": tank["minimum_temperature"],
                        "maximum_temperature": tank["maximum_temperature"],
                        "minimum_required_kwh": deadline["minimum_required_kwh"]
                        if deadline
                        else None,
                        "minimum_shortfall_kwh": deadline["minimum_shortfall_kwh"]
                        if deadline
                        else None,
                        "alternative_source": load.hot_water_alternative_source,
                        "alternative_heating_recommended": bool(
                            deadline and deadline["gas_thermal_kwh"] > 0
                        ),
                        "planned_target_temperature": tank["temperature_forecast"][-1][
                            "temperature_if_actions_executed"
                        ],
                    }
                )
        surplus = sum(p["unused_surplus_kwh"] for p in points)
        total = sum(p["consumption_kwh"] - p["home_kwh"] for p in points)
        payloads.append(
            {
                "state": "ok",
                "forecast_complete": "incomplete_solar_forecast" not in joint.warnings,
                "target_date": day.isoformat(),
                "available_surplus_kwh": surplus,
                "expected_demand_kwh": total,
                "recommended_kwh": total,
                "unallocated_surplus_kwh": surplus,
                "loads": sources,
                "warnings": joint.warnings,
            }
        )
        daily_surplus.append({"date": day.isoformat(), "unused_surplus_kwh": surplus})
    result.plan["managed_allocation_by_day"] = payloads
    result.plan["unused_surplus_by_day"] = daily_surplus
    result.plan["unused_surplus_kwh_total"] = sum(
        p["unused_surplus_kwh"] for p in joint.points
    )
    for day, suffix in (
        (now.date(), "today"),
        (now.date() + timedelta(days=1), "tomorrow"),
    ):
        allocation = next(
            (p for p in payloads if p["target_date"] == day.isoformat()), None
        )
        result.plan[
            "surplus_allocation_today" if suffix == "today" else "surplus_allocation"
        ] = allocation
        result.plan[f"managed_recommended_{suffix}_kwh"] = (
            allocation["recommended_kwh"] if allocation else None
        )
        result.plan[f"unused_surplus_{suffix}_kwh"] = (
            allocation["unallocated_surplus_kwh"] if allocation else None
        )
        if suffix == "today":
            result.plan["unused_surplus_kwh"] = (
                allocation["unallocated_surplus_kwh"] if allocation else None
            )
        else:
            result.plan["managed_expected_demand_tomorrow_kwh"] = (
                allocation["expected_demand_kwh"] if allocation else None
            )
            result.plan["unallocated_surplus_tomorrow_kwh"] = (
                allocation["unallocated_surplus_kwh"] if allocation else None
            )
