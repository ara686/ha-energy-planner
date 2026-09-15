"""House-first energy scheduling, with one AC/DC ledger and no HA dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from math import inf, isfinite
from typing import Any

from .ev_plan import EVChargingPlanInput, _next_departure, _scheduled_home
from .models import PlannerInput

EPS = 1e-7


def instant(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value


def elapsed(value: datetime, delta: timedelta) -> datetime:
    result = instant(value) + delta
    return result.astimezone(value.tzinfo) if value.tzinfo else result


def in_nt(value: datetime, data: PlannerInput) -> bool:
    minute = value.hour * 60 + value.minute
    for window in data.nt_windows:
        start, end = (int(t[:2]) * 60 + int(t[3:]) for t in (window.start, window.end))
        if start <= minute < end if start < end else minute >= start or minute < end:
            return True
    return False


@dataclass(frozen=True)
class JointLimits:
    """AC powers in kW; battery SoC and capacity are on the DC side."""

    grid_import_kw: float | None = None
    battery_charge_kw: float | None = None
    battery_discharge_kw: float | None = None
    export_kw: float | None = None
    discharge_efficiency: float = 1.0
    phase_limit_kw: float | None = None
    phases: int = 3
    solar_phases: int = 1
    maximum_ev_current: float = 16.0
    voltage: float = 230.0
    minimum_ev_current: float = 6.0


@dataclass(frozen=True)
class JointWater:
    source_id: str
    temperature: float
    volume_liters: float
    heater_kw: float
    efficiency: float = 1.0
    minimum: float = 40.0
    normal: float = 45.0
    maximum: float = 65.0
    deadline: time = time(17)
    gas_backup: bool = False
    loss_kw: float | None = None
    daily_draw_kwh: float | None = None
    priority: int = 1


@dataclass(frozen=True)
class JointSlot:
    start: datetime
    end: datetime
    solar: float
    home: float
    generic: dict[str, float] = field(default_factory=dict)

    @property
    def hours(self) -> float:
        return (instant(self.end) - instant(self.start)).total_seconds() / 3600


@dataclass
class JointResult:
    summary: dict[str, Any]
    points: list[dict[str, Any]]
    nt_targets: list[dict[str, Any]]
    vehicles: dict[str, dict[str, Any]]
    water: dict[str, dict[str, Any]]
    warnings: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "points": self.points,
            "nt_targets": self.nt_targets,
            "vehicles": self.vehicles,
            "water": self.water,
            "warnings": self.warnings,
        }


def normalized_joint_slots(
    data: PlannerInput,
    generic: dict[datetime, dict[str, float]],
    boundaries: tuple[time, ...] = (),
) -> list[JointSlot]:
    """Clip both boundaries; retain the remaining energy of an active slot."""
    end = elapsed(data.now, timedelta(hours=data.forecast_horizon_hours))
    ordered = sorted(data.slots, key=lambda s: instant(s.start))
    lookup = {instant(k): v for k, v in generic.items()}
    result = []
    for index, slot in enumerate(ordered):
        original_end = elapsed(slot.start, timedelta(minutes=data.interval_minutes))
        if index + 1 < len(ordered):
            original_end = min(original_end, ordered[index + 1].start, key=instant)
        start = max(slot.start, data.now, key=instant)
        stop = min(original_end, end, key=instant)
        if instant(stop) <= instant(start):
            continue
        cuts = {instant(start): start, instant(stop): stop}
        clocks = [
            *boundaries,
            *(time.fromisoformat(v) for w in data.nt_windows for v in (w.start, w.end)),
        ]
        for day in {start.date(), stop.date()}:
            for clock in clocks:
                for fold in (0, 1):
                    candidate = datetime.combine(
                        day, clock, tzinfo=start.tzinfo
                    ).replace(fold=fold)
                    if instant(start) < instant(candidate) < instant(stop):
                        cuts[instant(candidate)] = candidate
        edges = [cuts[k] for k in sorted(cuts)]
        for left, right in zip(edges, edges[1:], strict=False):
            ratio = (instant(right) - instant(left)).total_seconds() / (
                instant(original_end) - instant(slot.start)
            ).total_seconds()
            values = {
                k: max(0.0, v) * ratio
                for k, v in lookup.get(instant(slot.start), {}).items()
            }
            result.append(
                JointSlot(
                    left,
                    right,
                    max(0.0, slot.solar_kwh) * ratio,
                    max(0.0, slot.consumption_kwh) * ratio,
                    values,
                )
            )
    return result


def _limit(value: float | None) -> float:
    return inf if value is None else max(0.0, value)


def _reserve(
    data: PlannerInput, slots: list[JointSlot], limits: JointLimits
) -> list[float]:
    """Backward reachable reserve. NT grid power is shared with house demand."""
    floor = data.battery_capacity_kwh * data.battery_min_soc / 100
    margin = data.battery_capacity_kwh * data.soc_reserve_percent / 100
    reserve = [floor] * (len(slots) + 1)
    for i in range(len(slots) - 1, -1, -1):
        s = slots[i]
        net = s.home + sum(s.generic.values()) - s.solar
        needed = reserve[i + 1]
        if net < 0:
            needed -= (
                min(-net, _limit(limits.battery_charge_kw) * s.hours)
                * data.grid_charge_efficiency
            )
        elif not in_nt(s.start, data):
            needed += net / limits.discharge_efficiency
            needed = max(needed, floor + margin)
        if in_nt(s.start, data) and data.grid_charging_enabled:
            charge = min(
                data.grid_charge_max_kw * s.hours,
                _limit(limits.battery_charge_kw) * s.hours,
                max(0.0, _limit(limits.grid_import_kw) * s.hours - max(0.0, net)),
            )
            needed -= charge * data.grid_charge_efficiency
        elif in_nt(s.start, data):
            # Direct NT supply is still possible with battery charging disabled.
            needed += (
                max(0.0, net - _limit(limits.grid_import_kw) * s.hours)
                / limits.discharge_efficiency
            )
        reserve[i] = max(floor, needed)
    return reserve


def _simulate(
    data: PlannerInput,
    slots: list[JointSlot],
    limits: JointLimits,
    reserve: list[float],
    loads: list[dict[str, float]],
    grid_for_loads: list[float],
    fixed_charge: list[float] | None = None,
) -> list[dict[str, Any]]:
    capacity = data.battery_capacity_kwh
    floor = capacity * data.battery_min_soc / 100
    battery = capacity * data.battery_soc / 100
    points = []
    for i, s in enumerate(slots):
        before = battery
        demand = s.home + sum(s.generic.values()) + sum(loads[i].values())
        net = s.solar - demand
        charge_ac = discharge_ac = grid = unserved = 0.0
        nt = in_nt(s.start, data)
        charge_limit = _limit(limits.battery_charge_kw) * s.hours
        grid_limit = _limit(limits.grid_import_kw) * s.hours
        if net >= 0:
            charge_ac = min(
                net,
                charge_limit,
                max(0.0, capacity - battery) / data.grid_charge_efficiency,
            )
            battery += charge_ac * data.grid_charge_efficiency
            unused = net - charge_ac
        else:
            unused = 0.0
            explicit_grid = min(grid_for_loads[i], -net, grid_limit)
            deficit = -net - explicit_grid
            protected = min(capacity, max(floor, reserve[i + 1])) if nt else floor
            discharge_ac = min(
                deficit,
                max(0.0, battery - protected) * limits.discharge_efficiency,
                _limit(limits.battery_discharge_kw) * s.hours,
            )
            battery -= discharge_ac / limits.discharge_efficiency
            grid = min(grid_limit, explicit_grid + deficit - discharge_ac)
            unserved = max(0.0, explicit_grid + deficit - discharge_ac - grid)
        grid_charge_ac = 0.0
        if nt and data.grid_charging_enabled:
            desired = (
                max(0.0, reserve[i + 1] - battery) / data.grid_charge_efficiency
                if fixed_charge is None
                else fixed_charge[i]
            )
            grid_charge_ac = min(
                desired,
                max(0.0, grid_limit - grid),
                data.grid_charge_max_kw * s.hours,
                max(0.0, charge_limit - charge_ac),
                max(0.0, capacity - battery) / data.grid_charge_efficiency,
            )
            battery += grid_charge_ac * data.grid_charge_efficiency
        export = min(unused, _limit(limits.export_kw) * s.hours)
        points.append(
            {
                "start": s.start.isoformat(),
                "end": s.end.isoformat(),
                "timestamp": s.end.isoformat(),
                "is_nt": nt,
                "solar_kwh": s.solar,
                "home_kwh": s.home,
                "managed_by_source": {**s.generic, **loads[i]},
                "consumption_kwh": demand,
                "battery_start_kwh": before,
                "battery_kwh": battery,
                "soc_percent": battery / capacity * 100,
                "reserve_kwh": min(capacity, reserve[i + 1]),
                "battery_charge_ac_kwh": charge_ac + grid_charge_ac,
                "battery_discharge_ac_kwh": discharge_ac,
                "grid_charge_ac_kwh": grid_charge_ac,
                "grid_import_kwh": grid + grid_charge_ac,
                "unused_surplus_kwh": unused,
                "export_kwh": export,
                "curtailed_kwh": unused - export,
                "unserved_kwh": unserved,
                "unreachable_reserve_kwh": max(0.0, reserve[i + 1] - capacity),
            }
        )
    return points


def calculate_joint_plan(
    data: PlannerInput,
    *,
    limits: JointLimits | None = None,
    generic: dict[datetime, dict[str, float]] | None = None,
    vehicles: Sequence[EVChargingPlanInput] = (),
    water: Sequence[JointWater] = (),
) -> JointResult:
    """Schedule discretionary loads only after reserving the house's NT budget.

    Each candidate is replayed against the same house charging schedule. An
    optional load cannot buy additional battery energy or steal a future reserve.
    """
    limits = limits or JointLimits()
    for key in (
        "grid_import_kw",
        "battery_charge_kw",
        "battery_discharge_kw",
        "export_kw",
        "phase_limit_kw",
    ):
        value = getattr(limits, key)
        if value is not None and (not isfinite(value) or value < 0):
            raise ValueError("Invalid joint power limit")
    required = (
        data.battery_capacity_kwh,
        data.battery_soc,
        data.battery_min_soc,
        data.grid_charge_efficiency,
        limits.discharge_efficiency,
    )
    if (
        not all(isfinite(v) for v in required)
        or data.battery_capacity_kwh <= 0
        or not 0 < data.grid_charge_efficiency <= 1
        or not 0 < limits.discharge_efficiency <= 1
    ):
        raise ValueError("Invalid joint battery parameters")
    slots = normalized_joint_slots(
        data,
        generic or {},
        tuple([v.departure_time for v in vehicles] + [t.deadline for t in water]),
    )
    warnings = [
        f"unverified_{key}"
        for key in (
            "grid_import_kw",
            "battery_charge_kw",
            "battery_discharge_kw",
            "export_kw",
            "phase_limit_kw",
        )
        if getattr(limits, key) is None
    ]
    warnings.append("phase_load_distribution_unverified")
    if any(s.solar_coverage < 0.999 for s in data.slots):
        warnings.append("incomplete_solar_forecast")
    if not slots:
        return JointResult(
            {"state": "insufficient_data"}, [], [], {}, {}, ["no_forecast_slots"]
        )
    reserve = _reserve(data, slots, limits)
    loads: list[dict[str, float]] = [{} for _ in slots]
    grid_loads = [0.0] * len(slots)
    baseline = _simulate(data, slots, limits, reserve, loads, grid_loads)
    fixed_charge = [p["grid_charge_ac_kwh"] for p in baseline]
    points = baseline
    actions: dict[str, list[dict[str, Any]]] = {}
    water_by_source = {tank.source_id: tank for tank in water}

    def allocate(
        source: str,
        indices: list[int],
        demand: float,
        power: float,
        allow_grid: bool = False,
        solar_only: bool = False,
        minimum_power: float = 0.0,
    ) -> float:
        nonlocal points
        remaining = max(0.0, demand)
        for i in indices:
            if remaining <= EPS:
                break
            s = slots[i]
            existing = loads[i].get(source, 0.0)
            direct_solar = max(0.0, s.solar - points[i]["consumption_kwh"])
            cap = min(power * s.hours - existing, remaining)
            if limits.phase_limit_kw is not None:
                # Phase distribution is an estimate, not a verified circuit model.
                cap = min(
                    cap,
                    max(
                        0.0,
                        limits.phase_limit_kw * limits.phases * s.hours
                        - points[i]["consumption_kwh"],
                    ),
                )
            if solar_only:
                cap = min(cap, direct_solar)
            elif not allow_grid:
                slack = max(
                    0.0,
                    points[i]["battery_kwh"]
                    - max(
                        data.battery_capacity_kwh * data.battery_min_soc / 100,
                        reserve[i + 1],
                    ),
                )
                cap = min(
                    cap,
                    points[i]["unused_surplus_kwh"]
                    + slack * limits.discharge_efficiency,
                )
            if cap <= EPS:
                continue
            old_grid = grid_loads[i]

            def trial(
                value: float,
                *,
                i=i,
                existing=existing,
                old_grid=old_grid,
                previous_points=points,
            ) -> tuple[bool, list[dict[str, Any]]]:
                loads[i][source] = existing + value
                added_grid = (
                    max(0.0, value - previous_points[i]["unused_surplus_kwh"])
                    if allow_grid
                    else 0.0
                )
                grid_loads[i] = old_grid + added_grid
                candidate = _simulate(
                    data, slots, limits, reserve, loads, grid_loads, fixed_charge
                )
                valid = all(
                    p["grid_import_kwh"]
                    <= previous["grid_import_kwh"] + (added_grid if j == i else 0) + EPS
                    and p["unserved_kwh"] <= previous["unserved_kwh"] + EPS
                    and p["battery_kwh"] + EPS
                    >= min(previous["battery_kwh"], reserve[j + 1])
                    for j, (p, previous) in enumerate(
                        zip(candidate, previous_points, strict=True)
                    )
                )
                tank = water_by_source.get(source)
                if tank is not None:
                    temperature = tank.temperature
                    for j, slot in enumerate(slots):
                        thermal = loads[j].get(source, 0.0) * tank.efficiency
                        thermal -= (
                            (tank.loss_kw or 0) + (tank.daily_draw_kwh or 0) / 24
                        ) * slot.hours
                        temperature += thermal / (0.001163 * tank.volume_liters)
                        if (
                            tank.gas_backup
                            and slot.end.timetz().replace(tzinfo=None) == tank.deadline
                        ):
                            temperature = max(temperature, tank.minimum)
                        if temperature > max(tank.temperature, tank.maximum) + EPS:
                            valid = False
                            break
                return valid, candidate

            valid, candidate = trial(cap)
            if not valid:
                low, high = 0.0, cap
                for _ in range(18):
                    mid = (low + high) / 2
                    if trial(mid)[0]:
                        low = mid
                    else:
                        high = mid
                cap = low
                valid, candidate = trial(cap)
            # Require enough instantaneous supply to sustain 6 A; a final small
            # request may finish early rather than run below the minimum current.
            supply = cap / s.hours
            final_short = remaining < minimum_power * s.hours and cap + EPS >= remaining
            if final_short:
                minimum_energy = minimum_power * s.hours
                supports_minimum = (
                    minimum_power <= power
                    and (not solar_only or direct_solar + EPS >= minimum_energy)
                    and trial(minimum_energy)[0]
                )
                valid, candidate = trial(cap)
                final_short = supports_minimum
            if (
                not valid
                or cap < 1e-5
                or (supply + EPS < minimum_power and not final_short)
            ):
                if existing:
                    loads[i][source] = existing
                else:
                    loads[i].pop(source, None)
                grid_loads[i] = old_grid
                continue
            grid_added = max(
                0.0, candidate[i]["grid_import_kwh"] - points[i]["grid_import_kwh"]
            )
            actual_power = max(minimum_power, min(power, cap / s.hours))
            stop = elapsed(s.start, timedelta(hours=cap / actual_power))
            solar_energy = cap if solar_only else min(cap, direct_solar)
            mode = (
                "grid_low_tariff"
                if grid_added > EPS and in_nt(s.start, data)
                else "grid_high_tariff"
                if grid_added > EPS
                else "solar"
                if solar_only
                else "home_battery"
            )
            actions.setdefault(source, []).append(
                {
                    "start": s.start.isoformat(),
                    "end": stop.isoformat(),
                    "mode": mode,
                    "energy_kwh": cap,
                    "grid_kwh": grid_added,
                    "solar_kwh": solar_energy,
                    "home_battery_kwh": max(
                        0.0,
                        cap - grid_added - solar_energy,
                    ),
                    "power_kw": actual_power,
                }
            )
            points = candidate
            remaining -= cap
        return max(0.0, remaining)

    water_results = {}
    sorted_water = sorted(water, key=lambda w: (w.priority, w.source_id))
    for tank in sorted_water:
        if (
            not all(
                isfinite(v)
                for v in (
                    tank.temperature,
                    tank.volume_liters,
                    tank.heater_kw,
                    tank.efficiency,
                )
            )
            or tank.volume_liters <= 0
            or tank.heater_kw <= 0
            or tank.efficiency <= 0
        ):
            raise ValueError("Invalid water parameters")
        heat_capacity = 0.001163 * tank.volume_liters
        first_day = data.now.date()
        deadlines = []
        day = first_day
        gas_so_far = 0.0
        while True:
            deadline = datetime.combine(day, tank.deadline, tzinfo=data.now.tzinfo)
            if instant(deadline) > instant(slots[-1].end):
                break
            day += timedelta(days=1)
            if instant(deadline) <= instant(data.now):
                continue
            hours = (instant(deadline) - instant(data.now)).total_seconds() / 3600
            losses = (tank.loss_kw or 0.0) * hours + (
                tank.daily_draw_kwh or 0.0
            ) * hours / 24
            assigned_before = sum(
                loads[i].get(tank.source_id, 0)
                for i, slot in enumerate(slots)
                if instant(slot.end) <= instant(deadline)
            )
            deficit = (
                max(
                    0.0,
                    heat_capacity * (tank.minimum - tank.temperature)
                    + losses
                    - assigned_before * tank.efficiency
                    - gas_so_far,
                )
                / tank.efficiency
            )
            indices = [
                i
                for i, slot in enumerate(slots)
                if instant(slot.end) <= instant(deadline)
            ]
            missing = allocate(
                tank.source_id,
                indices,
                deficit,
                tank.heater_kw,
                solar_only=True,
            )
            gas = missing * tank.efficiency if tank.gas_backup else 0.0
            gas_so_far += gas
            deadlines.append(
                {
                    "deadline": deadline.isoformat(),
                    "minimum_required_kwh": deficit,
                    "minimum_shortfall_kwh": missing,
                    "gas_thermal_kwh": gas,
                    "estimated_losses_kwh": losses,
                }
            )
        first = (
            deadlines[0]
            if deadlines
            else {
                "deadline": None,
                "minimum_required_kwh": 0.0,
                "minimum_shortfall_kwh": None,
                "gas_thermal_kwh": 0.0,
                "estimated_losses_kwh": 0.0,
            }
        )
        water_results[tank.source_id] = {
            **first,
            "deadlines": deadlines,
            "minimum_temperature": tank.minimum,
            "normal_temperature": tank.normal,
            "maximum_temperature": tank.maximum,
            "gas_thermal_kwh": gas_so_far,
            "alternative_heating_recommended": tank.gas_backup
            and first["gas_thermal_kwh"] > EPS,
            "future_losses_estimated_kwh": first["estimated_losses_kwh"],
            "future_demand_complete": tank.loss_kw is not None
            and tank.daily_draw_kwh is not None,
        }
        if tank.loss_kw is None or tank.daily_draw_kwh is None:
            warnings.append(f"unverified_thermal_forecast:{tank.source_id}")

    vehicle_results = {}
    for vehicle in sorted(vehicles, key=lambda v: (v.priority, v.source_id)):
        departure = _next_departure(data.now, vehicle)
        indices = [
            i
            for i, s in enumerate(slots)
            if instant(s.end) <= instant(departure)
            and _scheduled_home(s.start, vehicle)
        ]
        remaining = vehicle.required_input_kwh
        minimum = limits.minimum_ev_current * limits.voltage * limits.phases / 1000
        maximum = min(
            vehicle.maximum_charging_power_kw,
            limits.maximum_ev_current * limits.voltage * limits.phases / 1000,
        )
        solar_maximum = min(
            vehicle.maximum_charging_power_kw,
            limits.maximum_ev_current * limits.voltage * limits.solar_phases / 1000,
        )
        solar_minimum = (
            limits.minimum_ev_current * limits.voltage * limits.solar_phases / 1000
        )
        if vehicle.currently_home is None or vehicle.connected is None:
            indices = []
        remaining = allocate(
            vehicle.source_id,
            indices,
            remaining,
            solar_maximum,
            solar_only=True,
            minimum_power=solar_minimum,
        )
        if vehicle.allow_home_battery:
            remaining = allocate(
                vehicle.source_id,
                list(reversed(indices)),
                remaining,
                maximum,
                minimum_power=minimum,
            )
        remaining = allocate(
            vehicle.source_id,
            [i for i in reversed(indices) if in_nt(slots[i].start, data)],
            remaining,
            maximum,
            allow_grid=True,
            minimum_power=minimum,
        )
        if vehicle.allow_high_tariff_grid:
            remaining = allocate(
                vehicle.source_id,
                [i for i in reversed(indices) if not in_nt(slots[i].start, data)],
                remaining,
                maximum,
                allow_grid=True,
                minimum_power=minimum,
            )
        timeline = sorted(actions.get(vehicle.source_id, []), key=lambda a: a["start"])
        active = next(
            (
                a
                for a in timeline
                if instant(datetime.fromisoformat(a["end"])) > instant(data.now)
            ),
            None,
        )
        mode = (
            active["mode"]
            if active
            and instant(datetime.fromisoformat(active["start"])) <= instant(data.now)
            else "wait_for_charging"
            if active
            else "shortfall"
            if remaining > EPS
            else "complete"
        )
        if vehicle.currently_home is None or vehicle.connected is None:
            mode = "unavailable"
        elif not vehicle.currently_home:
            mode = "off"
        elif not vehicle.connected:
            mode = "connect_vehicle"
        vehicle_results[vehicle.source_id] = {
            "mode": mode,
            "recommended_mode": mode,
            "reason": "house_reserve_or_power_limit"
            if remaining > EPS
            else "joint_plan",
            "departure": departure.isoformat(),
            "required_input_kwh": vehicle.required_input_kwh,
            "planned_kwh": vehicle.required_input_kwh - remaining,
            "shortfall_kwh": remaining,
            "timeline": timeline,
            "next_action_start": active["start"] if active else None,
            "next_action_end": active["end"] if active else None,
            "next_action_mode": active["mode"] if active else None,
        }

    for tank in sorted_water:
        initial = 0.001163 * tank.volume_liters * tank.temperature
        assigned = sum(load.get(tank.source_id, 0.0) for load in loads)
        for target in (tank.normal, tank.maximum):
            desired = (
                max(
                    0.0,
                    0.001163 * tank.volume_liters * target
                    - initial
                    - assigned * tank.efficiency,
                )
                / tank.efficiency
            )
            missing = allocate(
                tank.source_id,
                list(range(len(slots))),
                desired,
                tank.heater_kw,
                solar_only=True,
            )
            assigned += desired - missing
        water_results[tank.source_id]["planned_electrical_kwh"] = assigned
        water_results[tank.source_id]["timeline"] = actions.get(tank.source_id, [])

    targets = []
    for i, s in enumerate(slots):
        if in_nt(s.start, data) and (i == 0 or not in_nt(slots[i - 1].start, data)):
            end = i
            while end + 1 < len(slots) and in_nt(slots[end + 1].start, data):
                end += 1
            targets.append(
                {
                    "start": s.start.isoformat(),
                    "end": slots[end].end.isoformat(),
                    "target_soc": min(
                        100.0, reserve[end + 1] / data.battery_capacity_kwh * 100
                    ),
                    "grid_charge_ac_kwh": sum(
                        p["grid_charge_ac_kwh"] for p in points[i : end + 1]
                    ),
                    "shortfall_kwh": max(
                        0.0, reserve[end + 1] - points[end]["battery_kwh"]
                    ),
                }
            )
    # One actionable command per source/interval, including mixed PV + grid.
    for source, entries in actions.items():
        merged = {}
        for action in entries:
            key = action["start"]
            if key not in merged:
                merged[key] = dict(action)
            else:
                item = merged[key]
                item["energy_kwh"] += action["energy_kwh"]
                item["grid_kwh"] += action["grid_kwh"]
                item["solar_kwh"] += action["solar_kwh"]
                item["home_battery_kwh"] += action["home_battery_kwh"]
                if action["mode"].startswith("grid"):
                    item["mode"] = action["mode"]
                item["end"] = max(item["end"], action["end"])
            item = merged[key]
            hours = (
                instant(datetime.fromisoformat(item["end"]))
                - instant(datetime.fromisoformat(key))
            ).total_seconds() / 3600
            item["power_kw"] = item["energy_kwh"] / hours
        timeline = sorted(
            merged.values(), key=lambda a: instant(datetime.fromisoformat(a["start"]))
        )
        if source in vehicle_results:
            value = vehicle_results[source]
            value["timeline"] = timeline
            active = next(
                (
                    a
                    for a in timeline
                    if instant(datetime.fromisoformat(a["end"])) > instant(data.now)
                ),
                None,
            )
            if active:
                value.update(
                    next_action_start=active["start"],
                    next_action_end=active["end"],
                    next_action_mode=active["mode"],
                )
                if value["mode"] not in {"off", "connect_vehicle", "unavailable"}:
                    mode = (
                        active["mode"]
                        if instant(datetime.fromisoformat(active["start"]))
                        <= instant(data.now)
                        else "wait_for_solar"
                        if active["mode"] == "solar"
                        else "wait_for_charging"
                    )
                    value["mode"] = value["recommended_mode"] = mode
            value["solar_kwh"] = sum(a["solar_kwh"] for a in timeline)
            value["home_battery_kwh"] = sum(a["home_battery_kwh"] for a in timeline)
            for tariff in ("low", "high"):
                value[f"grid_{tariff}_tariff_kwh"] = sum(
                    a["grid_kwh"]
                    for a in timeline
                    if a["mode"] == f"grid_{tariff}_tariff"
                )
            value["action_window_minutes"] = data.interval_minutes
        if source in water_results:
            water_results[source]["timeline"] = timeline
    for tank in sorted_water:
        temperature = tank.temperature
        trace = []
        due = list(water_results[tank.source_id]["deadlines"])
        for i, slot in enumerate(slots):
            thermal = loads[i].get(tank.source_id, 0.0) * tank.efficiency
            thermal -= (
                (tank.loss_kw or 0.0) + (tank.daily_draw_kwh or 0.0) / 24
            ) * slot.hours
            temperature += thermal / (0.001163 * tank.volume_liters)
            while due and instant(
                datetime.fromisoformat(due[0]["deadline"])
            ) <= instant(slot.end):
                deadline = due.pop(0)
                missing = (
                    max(0.0, tank.minimum - temperature) * 0.001163 * tank.volume_liters
                )
                deadline["minimum_shortfall_kwh"] = missing / tank.efficiency
                deadline["gas_thermal_kwh"] = missing if tank.gas_backup else 0.0
                temperature += deadline["gas_thermal_kwh"] / (
                    0.001163 * tank.volume_liters
                )
            trace.append(
                {
                    "timestamp": slot.end.isoformat(),
                    "temperature_if_actions_executed": temperature,
                }
            )
        water_results[tank.source_id]["temperature_forecast"] = trace
        deadlines = water_results[tank.source_id]["deadlines"]
        water_results[tank.source_id]["gas_thermal_kwh"] = sum(
            d["gas_thermal_kwh"] for d in deadlines
        )
        if deadlines:
            water_results[tank.source_id]["minimum_shortfall_kwh"] = deadlines[0][
                "minimum_shortfall_kwh"
            ]
            water_results[tank.source_id]["alternative_heating_recommended"] = (
                deadlines[0]["gas_thermal_kwh"] > EPS
            )
    first = targets[0] if targets else None
    total_grid = sum(p["grid_import_kwh"] for p in points)
    if any(
        p["unserved_kwh"] > EPS or p["unreachable_reserve_kwh"] > EPS for p in points
    ):
        warnings.append("house_power_or_capacity_shortfall")
    summary = {
        "state": "warning" if warnings else "ok",
        "valid_from": slots[0].start.isoformat(),
        "valid_until": slots[0].end.isoformat(),
        "current_soc": data.battery_soc,
        "current_charge_window": in_nt(data.now, data),
        "charge_now": points[0]["grid_charge_ac_kwh"] > EPS,
        "current_charge_target_soc": points[0]["soc_percent"]
        if points[0]["grid_charge_ac_kwh"] > EPS
        else data.battery_soc,
        "target_soc": first["target_soc"] if first else data.battery_min_soc,
        "lock_soc": min(100.0, reserve[0] / data.battery_capacity_kwh * 100),
        "safe_discharge_soc": min(100.0, reserve[0] / data.battery_capacity_kwh * 100),
        "grid_import_kwh": total_grid,
        "vt_grid_import_kwh": sum(
            p["grid_import_kwh"] for p in points if not p["is_nt"]
        ),
        "nt_grid_import_kwh": sum(p["grid_import_kwh"] for p in points if p["is_nt"]),
        "export_kwh": sum(p["export_kwh"] for p in points),
        "curtailed_kwh": sum(p["curtailed_kwh"] for p in points),
        "unserved_kwh": sum(p["unserved_kwh"] for p in points),
        "soc_at_horizon": points[-1]["soc_percent"],
        "technical_limits_verified": not any(
            w.startswith("unverified_") or w.startswith("phase_") for w in warnings
        ),
    }
    return JointResult(
        summary, points, targets, vehicle_results, water_results, warnings
    )
