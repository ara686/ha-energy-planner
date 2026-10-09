"""House-first energy scheduling, with one AC/DC ledger and no HA dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from functools import cached_property
from math import inf, isfinite
from typing import Any

from .const import DEFAULT_SOLAR_MINIMUM_SOC_PERCENT
from .ev_plan import EVChargingPlanInput, _next_departure, _scheduled_home
from .managed_allocation import _proportional_capped_allocations
from .models import PlannerInput
from .solar import solar_block_reason, valid_solar_minimum_soc

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
    solar_minimum_soc_percent: float = DEFAULT_SOLAR_MINIMUM_SOC_PERCENT


@dataclass(frozen=True)
class JointSlot:
    start: datetime
    end: datetime
    solar: float
    home: float
    generic: dict[str, float] = field(default_factory=dict)
    solar_coverage: float = 1.0

    @cached_property
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
                    slot.solar_coverage,
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


@dataclass(frozen=True)
class _PreparedSlot:
    nt: bool
    charge_limit: float
    discharge_limit: float
    grid_limit: float
    grid_charge_limit: float
    export_limit: float
    home: float
    attributes: dict[str, Any]


def _prepare_simulation(
    data: PlannerInput,
    slots: list[JointSlot],
    limits: JointLimits,
    reserve: list[float],
) -> list[_PreparedSlot]:
    return [
        _PreparedSlot(
            in_nt(s.start, data),
            _limit(limits.battery_charge_kw) * s.hours,
            _limit(limits.battery_discharge_kw) * s.hours,
            _limit(limits.grid_import_kw) * s.hours,
            data.grid_charge_max_kw * s.hours,
            _limit(limits.export_kw) * s.hours,
            s.home + sum(s.generic.values()),
            {
                "start": s.start.isoformat(),
                "end": s.end.isoformat(),
                "timestamp": s.end.isoformat(),
                "is_nt": in_nt(s.start, data),
                "solar_kwh": s.solar,
                "home_kwh": s.home,
                "reserve_kwh": min(data.battery_capacity_kwh, reserve[i + 1]),
                "unreachable_reserve_kwh": max(
                    0.0, reserve[i + 1] - data.battery_capacity_kwh
                ),
            },
        )
        for i, s in enumerate(slots)
    ]


@dataclass(frozen=True)
class _Replay:
    previous: list[dict[str, Any]]
    index: int
    added_grid: float


def _simulate(
    data: PlannerInput,
    slots: list[JointSlot],
    limits: JointLimits,
    reserve: list[float],
    loads: list[dict[str, float]],
    grid_for_loads: list[float],
    fixed_charge: list[float] | None = None,
    *,
    prepared: list[_PreparedSlot] | None = None,
    replay: _Replay | None = None,
    minimum_start_kwh: list[float] | None = None,
) -> list[dict[str, Any]] | None:
    capacity = data.battery_capacity_kwh
    floor = capacity * data.battery_min_soc / 100
    battery = capacity * data.battery_soc / 100
    prepared = (
        prepared
        if prepared is not None
        else _prepare_simulation(data, slots, limits, reserve)
    )
    start = replay.index if replay is not None else 0
    points = replay.previous[:start] if replay is not None else []
    if start:
        battery = points[-1]["battery_kwh"]
    for i in range(start, len(slots)):
        s = slots[i]
        cached = prepared[i]
        before = battery
        if minimum_start_kwh is not None and before + 1e-9 < minimum_start_kwh[i]:
            return None
        demand = cached.home + sum(loads[i].values())
        net = s.solar - demand
        charge_ac = discharge_ac = grid = unserved = 0.0
        nt = cached.nt
        charge_limit = cached.charge_limit
        grid_limit = cached.grid_limit
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
                cached.discharge_limit,
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
                cached.grid_charge_limit,
                max(0.0, charge_limit - charge_ac),
                max(0.0, capacity - battery) / data.grid_charge_efficiency,
            )
            battery += grid_charge_ac * data.grid_charge_efficiency
        if replay is not None:
            previous = replay.previous[i]
            if (
                grid + grid_charge_ac
                > previous["grid_import_kwh"]
                + (replay.added_grid if i == start else 0)
                + EPS
                or unserved > previous["unserved_kwh"] + EPS
                or battery + EPS < min(previous["battery_kwh"], reserve[i + 1])
            ):
                return None
        export = min(unused, cached.export_limit)
        points.append(
            {
                **cached.attributes,
                "managed_by_source": {**s.generic, **loads[i]},
                "consumption_kwh": demand,
                "battery_start_kwh": before,
                "battery_kwh": battery,
                "soc_percent": battery / capacity * 100,
                "battery_charge_ac_kwh": charge_ac + grid_charge_ac,
                "battery_discharge_ac_kwh": discharge_ac,
                "grid_charge_ac_kwh": grid_charge_ac,
                "grid_import_kwh": grid + grid_charge_ac,
                "unused_surplus_kwh": unused,
                "export_kwh": export,
                "curtailed_kwh": unused - export,
                "unserved_kwh": unserved,
            }
        )
        if replay is not None and battery == replay.previous[i]["battery_kwh"]:
            # All later inputs are unchanged, including the fixed house charge.
            points.extend(replay.previous[i + 1 :])
            break
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
    if any(
        not valid_solar_minimum_soc(load.solar_minimum_soc_percent)
        for load in (*water, *vehicles)
    ):
        raise ValueError("Invalid solar minimum SoC")
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
    prepared = _prepare_simulation(data, slots, limits, reserve)
    baseline = _simulate(
        data, slots, limits, reserve, loads, grid_loads, prepared=prepared
    )
    assert baseline is not None
    fixed_charge = [p["grid_charge_ac_kwh"] for p in baseline]
    points = baseline
    actions: dict[str, list[dict[str, Any]]] = {}
    water_by_source = {tank.source_id: tank for tank in water}
    solar_thresholds = {
        load.source_id: load.solar_minimum_soc_percent for load in (*water, *vehicles)
    }
    minimum_start_kwh = [0.0] * len(slots)
    peak_by_slot: list[dict[str, float]] = [{} for _ in slots]
    blocked: dict[str, set[str]] = {}

    def allocate(
        source: str,
        indices: list[int],
        demand: float,
        power: float,
        allow_grid: bool = False,
        solar_only: bool = False,
        minimum_power: float = 0.0,
        minimum_addition_kwh: float | None = None,
    ) -> float:
        nonlocal points
        remaining = max(0.0, demand)
        for i in indices:
            if remaining <= EPS:
                break
            s = slots[i]
            existing = loads[i].get(source, 0.0)
            direct_solar = max(0.0, s.solar - points[i]["consumption_kwh"])
            own_peak = peak_by_slot[i].get(source, 0.0)
            solar_power = max(
                0.0,
                (s.solar - prepared[i].home) / s.hours
                - sum(peak_by_slot[i].values())
                + own_peak,
            )
            if solar_only:
                if s.solar_coverage < 0.999:
                    blocked.setdefault(source, set()).add("incomplete_solar_forecast")
                    continue
                reason = solar_block_reason(
                    soc_percent=points[i]["battery_start_kwh"]
                    / data.battery_capacity_kwh
                    * 100,
                    minimum_soc_percent=solar_thresholds[source],
                    available_power_kw=min(power, solar_power),
                    minimum_power_kw=minimum_power,
                )
                if reason:
                    blocked.setdefault(source, set()).add(reason)
                    continue
            cap = min(power * s.hours - existing, remaining)
            if limits.phase_limit_kw is not None:
                # Phase distribution is an estimate, not a verified circuit model.
                phase_power = max(
                    0.0,
                    limits.phase_limit_kw * limits.phases
                    - prepared[i].home / s.hours
                    - sum(peak_by_slot[i].values())
                    + own_peak,
                )
                if minimum_power > phase_power + EPS:
                    if solar_only:
                        blocked.setdefault(source, set()).add(
                            "insufficient_solar_power"
                        )
                    continue
                cap = min(cap, max(0.0, phase_power * s.hours - existing))
            if solar_only:
                cap = min(cap, max(0.0, solar_power * s.hours - existing))
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
            old_minimum = minimum_start_kwh[i]
            if solar_only:
                minimum_start_kwh[i] = max(
                    old_minimum,
                    solar_thresholds[source] * data.battery_capacity_kwh / 100,
                )

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
                    data,
                    slots,
                    limits,
                    reserve,
                    loads,
                    grid_loads,
                    fixed_charge,
                    prepared=prepared,
                    replay=_Replay(previous_points, i, added_grid),
                    minimum_start_kwh=minimum_start_kwh,
                )
                if candidate is None:
                    return False, previous_points
                valid = True
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
            minimum_addition = (
                minimum_addition_kwh
                if minimum_addition_kwh is not None
                else min(remaining, max(0.0, minimum_power * s.hours - existing))
            )
            if not valid or cap < 1e-5 or cap + EPS < minimum_addition:
                if existing:
                    loads[i][source] = existing
                else:
                    loads[i].pop(source, None)
                grid_loads[i] = old_grid
                minimum_start_kwh[i] = old_minimum
                continue
            grid_added = max(
                0.0, candidate[i]["grid_import_kwh"] - points[i]["grid_import_kwh"]
            )
            actual_power = max(
                own_peak, minimum_power, min(power, (existing + cap) / s.hours)
            )
            peak_by_slot[i][source] = actual_power
            stop = elapsed(s.start, timedelta(hours=(existing + cap) / actual_power))
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

    def solar_group(
        requests: list[tuple[str, int, list[int], float, float, float]],
    ) -> dict[str, float]:
        """Share a phase's headroom only between physically feasible loads."""
        remaining = {source: demand for source, _, _, demand, _, _ in requests}
        for priority in sorted({request[1] for request in requests}):
            group = [request for request in requests if request[1] == priority]
            for i, slot in enumerate(slots):
                available = max(0.0, slot.solar - points[i]["consumption_kwh"])
                peak = max(
                    0.0,
                    (slot.solar - prepared[i].home) / slot.hours
                    - sum(peak_by_slot[i].values()),
                )
                caps, weights, minima, powers = {}, {}, {}, {}
                for source, _, indices, _, power, minimum in group:
                    if i not in indices or remaining[source] <= EPS:
                        continue
                    if slot.solar_coverage < 0.999:
                        blocked.setdefault(source, set()).add(
                            "incomplete_solar_forecast"
                        )
                        continue
                    own = peak_by_slot[i].get(source, 0.0)
                    reason = solar_block_reason(
                        soc_percent=points[i]["battery_start_kwh"]
                        / data.battery_capacity_kwh
                        * 100,
                        minimum_soc_percent=solar_thresholds[source],
                        available_power_kw=min(power, peak + own),
                        minimum_power_kw=minimum,
                    )
                    if reason:
                        blocked.setdefault(source, set()).add(reason)
                        continue
                    existing = loads[i].get(source, 0.0)
                    caps[source] = min(
                        remaining[source], max(0.0, power * slot.hours - existing)
                    )
                    weights[source] = remaining[source]
                    minima[source] = min(
                        remaining[source], max(0.0, minimum * slot.hours - existing)
                    )
                    powers[source] = (power, minimum, own, existing)

                values = _proportional_capped_allocations(
                    available=available, capacities=caps, weights=weights
                )

                def required_peak(
                    source: str, value: float, *, powers=powers, slot=slot
                ) -> float:
                    _, minimum, own, existing = powers[source]
                    return max(own, minimum, (existing + value) / slot.hours)

                if (
                    any(
                        value + EPS < minima[source] for source, value in values.items()
                    )
                    or sum(
                        required_peak(source, value) - powers[source][2]
                        for source, value in values.items()
                    )
                    > peak + EPS
                ):
                    values = {}
                    energy_left, power_left = available, peak
                    for source in sorted(caps):
                        _, _, own, existing = powers[source]
                        value = min(
                            caps[source],
                            energy_left,
                            max(0.0, (power_left + own) * slot.hours - existing),
                        )
                        if value <= EPS or value + EPS < minima[source]:
                            continue
                        extra_peak = required_peak(source, value) - own
                        if extra_peak > power_left + EPS:
                            continue
                        values[source] = value
                        energy_left -= value
                        power_left -= extra_peak
                for source, value in values.items():
                    power, minimum, _, _ = powers[source]
                    missing = allocate(
                        source,
                        [i],
                        value,
                        power,
                        solar_only=True,
                        minimum_power=minimum,
                        minimum_addition_kwh=minima[source],
                    )
                    remaining[source] -= value - missing
                for source, _, indices, _, power, minimum in group:
                    if i not in indices or remaining[source] <= EPS:
                        continue
                    own = peak_by_slot[i].get(source, 0.0)
                    actual_headroom = max(
                        0.0,
                        (slot.solar - prepared[i].home) / slot.hours
                        - sum(peak_by_slot[i].values())
                        + own,
                    )
                    if min(power, actual_headroom) + EPS < minimum:
                        blocked.setdefault(source, set()).add(
                            "insufficient_solar_power"
                        )
        return remaining

    water_results = {}
    sorted_water = sorted(water, key=lambda w: (w.priority, w.source_id))
    deadlines_by_source: dict[str, list[dict[str, Any]]] = {
        tank.source_id: [] for tank in sorted_water
    }
    gas_by_source = {tank.source_id: 0.0 for tank in sorted_water}
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
    for priority in sorted({tank.priority for tank in sorted_water}):
        day = data.now.date()
        while day <= slots[-1].end.date():
            requests = []
            pending = {}
            for tank in sorted_water:
                if tank.priority != priority:
                    continue
                deadline = datetime.combine(day, tank.deadline, tzinfo=data.now.tzinfo)
                if not instant(data.now) < instant(deadline) <= instant(slots[-1].end):
                    continue
                hours = (instant(deadline) - instant(data.now)).total_seconds() / 3600
                losses = ((tank.loss_kw or 0) + (tank.daily_draw_kwh or 0) / 24) * hours
                indices = [
                    i
                    for i, slot in enumerate(slots)
                    if instant(slot.end) <= instant(deadline)
                ]
                assigned = sum(loads[i].get(tank.source_id, 0.0) for i in indices)
                deficit = (
                    max(
                        0.0,
                        0.001163
                        * tank.volume_liters
                        * (tank.minimum - tank.temperature)
                        + losses
                        - assigned * tank.efficiency
                        - gas_by_source[tank.source_id],
                    )
                    / tank.efficiency
                )
                requests.append(
                    (
                        tank.source_id,
                        priority,
                        indices,
                        deficit,
                        tank.heater_kw,
                        tank.heater_kw,
                    )
                )
                pending[tank.source_id] = (tank, deadline, losses, deficit)
            missing_by_source = solar_group(requests)
            for source, (tank, deadline, losses, deficit) in pending.items():
                missing = missing_by_source[source]
                gas = missing * tank.efficiency if tank.gas_backup else 0.0
                gas_by_source[source] += gas
                deadlines_by_source[source].append(
                    {
                        "deadline": deadline.isoformat(),
                        "minimum_required_kwh": deficit,
                        "minimum_shortfall_kwh": missing,
                        "gas_thermal_kwh": gas,
                        "estimated_losses_kwh": losses,
                    }
                )
            day += timedelta(days=1)
    for tank in sorted_water:
        deadlines = deadlines_by_source[tank.source_id]
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
            "gas_thermal_kwh": gas_by_source[tank.source_id],
            "alternative_heating_recommended": tank.gas_backup
            and first["gas_thermal_kwh"] > EPS,
            "future_losses_estimated_kwh": first["estimated_losses_kwh"],
            "future_demand_complete": tank.loss_kw is not None
            and tank.daily_draw_kwh is not None,
        }
        if tank.loss_kw is None or tank.daily_draw_kwh is None:
            warnings.append(f"unverified_thermal_forecast:{tank.source_id}")

    vehicle_results = {}
    vehicle_context = {}
    solar_requests = []
    for vehicle in sorted(vehicles, key=lambda v: (v.priority, v.source_id)):
        departure = (
            slots[-1].end if vehicle.solar_only else _next_departure(data.now, vehicle)
        )
        indices = [
            i
            for i, slot in enumerate(slots)
            if instant(slot.end) <= instant(departure)
            and (vehicle.solar_only or _scheduled_home(slot.start, vehicle))
        ]
        if vehicle.currently_home is None or vehicle.connected is None:
            indices = []
        minimum = limits.minimum_ev_current * limits.voltage * limits.phases / 1000
        maximum = min(
            vehicle.maximum_charging_power_kw,
            limits.maximum_ev_current * limits.voltage * limits.phases / 1000,
        )
        solar_maximum = min(
            vehicle.maximum_charging_power_kw,
            limits.maximum_ev_current * limits.voltage * limits.solar_phases / 1000,
        )
        solar_minimum = max(
            vehicle.minimum_solar_power_kw,
            limits.minimum_ev_current * limits.voltage * limits.solar_phases / 1000,
        )
        solar_requests.append(
            (
                vehicle.source_id,
                vehicle.priority,
                indices,
                vehicle.required_input_kwh,
                solar_maximum,
                solar_minimum,
            )
        )
        vehicle_context[vehicle.source_id] = (departure, indices, minimum, maximum)
    solar_remaining = {}
    completed_priorities = set()
    for vehicle in sorted(vehicles, key=lambda v: (v.priority, v.source_id)):
        if vehicle.priority not in completed_priorities:
            solar_remaining.update(
                solar_group(
                    [
                        request
                        for request in solar_requests
                        if request[1] == vehicle.priority
                    ]
                )
            )
            completed_priorities.add(vehicle.priority)
        departure, indices, minimum, maximum = vehicle_context[vehicle.source_id]
        remaining = solar_remaining[vehicle.source_id]
        if vehicle.allow_home_battery and not vehicle.solar_only:
            remaining = allocate(
                vehicle.source_id,
                list(reversed(indices)),
                remaining,
                maximum,
                minimum_power=minimum,
            )
        remaining = allocate(
            vehicle.source_id,
            []
            if vehicle.solar_only
            else [i for i in reversed(indices) if in_nt(slots[i].start, data)],
            remaining,
            maximum,
            allow_grid=True,
            minimum_power=minimum,
        )
        if vehicle.allow_high_tariff_grid and not vehicle.solar_only:
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

    for target_attribute in ("normal", "maximum"):
        requests = []
        for tank in sorted_water:
            assigned = sum(load.get(tank.source_id, 0.0) for load in loads)
            desired = (
                max(
                    0.0,
                    0.001163
                    * tank.volume_liters
                    * (getattr(tank, target_attribute) - tank.temperature)
                    - assigned * tank.efficiency,
                )
                / tank.efficiency
            )
            requests.append(
                (
                    tank.source_id,
                    tank.priority,
                    list(range(len(slots))),
                    desired,
                    tank.heater_kw,
                    tank.heater_kw,
                )
            )
        solar_group(requests)
    for tank in sorted_water:
        water_results[tank.source_id]["planned_electrical_kwh"] = sum(
            load.get(tank.source_id, 0.0) for load in loads
        )
        water_results[tank.source_id]["timeline"] = actions.get(tank.source_id, [])

    for source, value in {**water_results, **vehicle_results}.items():
        value["solar_minimum_soc_percent"] = solar_thresholds[source]
        if blocked.get(source):
            value["solar_block_reasons"] = sorted(blocked[source])
            if (
                source in vehicle_results
                and value.get("mode")
                in {
                    "shortfall",
                    "wait_for_solar",
                }
            ) or (
                source in water_results
                and value.get("planned_electrical_kwh", 0) <= EPS
            ):
                value["reason"] = (
                    "waiting_for_minimum_soc"
                    if "waiting_for_minimum_soc" in blocked[source]
                    else "insufficient_solar_power"
                )

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
