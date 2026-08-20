"""Pure deadline-aware electric-vehicle charging plan."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time, timedelta
from typing import Literal

EVChargingMode = Literal[
    "off",
    "connect_vehicle",
    "wait_for_solar",
    "solar",
    "home_battery",
    "grid_low_tariff",
    "grid_high_tariff",
    "complete",
    "shortfall",
    "unavailable",
]
EV_CHARGING_MODES: tuple[EVChargingMode, ...] = (
    "off",
    "connect_vehicle",
    "wait_for_solar",
    "solar",
    "home_battery",
    "grid_low_tariff",
    "grid_high_tariff",
    "complete",
    "shortfall",
    "unavailable",
)


@dataclass(frozen=True)
class EVChargingSlot:
    """Forecast values used to plan one EV charging interval."""

    start: datetime
    unused_surplus_kwh: float
    battery_kwh: float
    solar_coverage: float = 1.0
    is_low_tariff: bool = False


@dataclass(frozen=True)
class EVChargingPlanInput:
    """One vehicle's deadline and live-availability inputs."""

    source_id: str
    priority: int
    required_input_kwh: float
    maximum_charging_power_kw: float
    workdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    departure_time: time = time(7)
    return_time: time = time(17)
    currently_home: bool | None = None
    connected: bool | None = None
    allow_high_tariff_grid: bool = False


@dataclass(frozen=True)
class EVChargingWindow:
    """One contiguous charging recommendation."""

    start: datetime
    end: datetime
    mode: EVChargingMode
    energy_kwh: float

    def as_dict(self) -> dict[str, object]:
        """Return a compact recorder-friendly representation."""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "mode": self.mode,
            "energy_kwh": _round(self.energy_kwh),
        }


@dataclass(frozen=True)
class EVChargingPlan:
    """Deadline-aware charging decision for one vehicle."""

    source_id: str
    mode: EVChargingMode
    reason: str
    departure: datetime | None
    return_at: datetime | None
    required_input_kwh: float
    action_window_minutes: int
    solar_kwh: float = 0.0
    home_battery_kwh: float = 0.0
    grid_low_tariff_kwh: float = 0.0
    grid_high_tariff_kwh: float = 0.0
    shortfall_kwh: float = 0.0
    solar_if_home_kwh: float = 0.0
    solar_if_home_covers_request: bool = False
    forecast_complete: bool = True
    next_action_start: datetime | None = None
    next_action_end: datetime | None = None
    timeline: tuple[EVChargingWindow, ...] = field(default_factory=tuple)

    @property
    def planned_kwh(self) -> float:
        """Return total charger-input energy assigned before departure."""
        return (
            self.solar_kwh
            + self.home_battery_kwh
            + self.grid_low_tariff_kwh
            + self.grid_high_tariff_kwh
        )

    def as_dict(self) -> dict[str, object]:
        """Return the public planner payload."""
        return {
            "source_entity_id": self.source_id,
            "mode": self.mode,
            "reason": self.reason,
            "departure": self.departure.isoformat() if self.departure else None,
            "return_at": self.return_at.isoformat() if self.return_at else None,
            "required_input_kwh": _round(self.required_input_kwh),
            "action_window_minutes": self.action_window_minutes,
            "planned_kwh": _round(self.planned_kwh),
            "solar_kwh": _round(self.solar_kwh),
            "home_battery_kwh": _round(self.home_battery_kwh),
            "grid_low_tariff_kwh": _round(self.grid_low_tariff_kwh),
            "grid_high_tariff_kwh": _round(self.grid_high_tariff_kwh),
            "shortfall_kwh": _round(self.shortfall_kwh),
            "solar_if_home_kwh": _round(self.solar_if_home_kwh),
            "solar_if_home_covers_request": self.solar_if_home_covers_request,
            "forecast_complete": self.forecast_complete,
            "next_action_start": (
                self.next_action_start.isoformat() if self.next_action_start else None
            ),
            "next_action_end": (
                self.next_action_end.isoformat() if self.next_action_end else None
            ),
            "timeline": [window.as_dict() for window in self.timeline],
        }


def calculate_ev_charging_plan(
    data: EVChargingPlanInput,
    *,
    now: datetime,
    slots: list[EVChargingSlot],
    interval_minutes: int,
    battery_capacity_kwh: float,
    safe_discharge_soc: float,
) -> EVChargingPlan:
    """Allocate EV demand across solar, shifted battery energy and grid."""
    if (
        interval_minutes <= 0
        or data.required_input_kwh < 0
        or data.maximum_charging_power_kw <= 0
        or battery_capacity_kwh <= 0
        or not data.workdays
    ):
        return _unavailable(data, "invalid_configuration", interval_minutes)

    departure = _next_departure(now, data)
    return_at = _combine_local(
        departure,
        data.return_time,
    )
    if _timeline_time(return_at) <= _timeline_time(departure):
        return_at = _add_elapsed_time(return_at, timedelta(days=1))
    required = max(float(data.required_input_kwh), 0.0)
    if required <= 1e-9:
        return EVChargingPlan(
            source_id=data.source_id,
            mode="complete",
            reason="request_complete",
            departure=departure,
            return_at=return_at,
            required_input_kwh=0.0,
            action_window_minutes=interval_minutes,
            solar_if_home_covers_request=True,
        )

    ordered = sorted(
        (
            slot
            for slot in slots
            if _timeline_time(slot.start) >= _timeline_time(now)
            and _timeline_time(slot.start) < _timeline_time(return_at)
        ),
        key=lambda slot: _timeline_time(slot.start),
    )
    before_departure = [
        slot
        for slot in ordered
        if _timeline_time(slot.start) < _timeline_time(departure)
    ]
    if not before_departure:
        return EVChargingPlan(
            source_id=data.source_id,
            mode="unavailable",
            reason="forecast_does_not_reach_departure",
            departure=departure,
            return_at=return_at,
            required_input_kwh=required,
            action_window_minutes=interval_minutes,
            shortfall_kwh=required,
            forecast_complete=False,
        )

    interval_hours = interval_minutes / 60
    slot_limit = data.maximum_charging_power_kw * interval_hours
    allocations: dict[datetime, tuple[EVChargingMode, float]] = {}
    capacity_used: dict[datetime, float] = {}
    remaining = required

    forecast_complete = _forecast_covers_window(
        ordered,
        start=now,
        end=return_at,
        interval_minutes=interval_minutes,
    )
    home_slots = [
        slot for slot in before_departure if _scheduled_home(slot.start, data)
    ]

    solar_kwh = _allocate_slots(
        slots=home_slots,
        desired_kwh=remaining,
        mode="solar",
        slot_limit_kwh=slot_limit,
        allocations=allocations,
        capacity_used=capacity_used,
        available_fn=lambda slot: (
            max(slot.unused_surplus_kwh, 0.0) if slot.solar_coverage >= 0.999 else 0.0
        ),
    )
    remaining -= solar_kwh

    away_slots = [
        slot
        for slot in ordered
        if _timeline_time(departure)
        <= _timeline_time(slot.start)
        < _timeline_time(return_at)
        and not _scheduled_home(slot.start, data)
    ]
    lost_surplus_kwh = (
        sum(max(slot.unused_surplus_kwh, 0.0) for slot in away_slots)
        if forecast_complete
        else 0.0
    )
    departure_battery = before_departure[-1].battery_kwh
    safe_battery_kwh = (
        battery_capacity_kwh * max(0.0, min(safe_discharge_soc, 100.0)) / 100
    )
    battery_available_kwh = max(departure_battery - safe_battery_kwh, 0.0)
    battery_target = min(remaining, lost_surplus_kwh, battery_available_kwh)
    low_tariff_slots = [slot for slot in home_slots if slot.is_low_tariff]
    grid_low_tariff_kwh = _allocate_slots(
        slots=list(reversed(low_tariff_slots)),
        desired_kwh=max(remaining - battery_target, 0.0),
        mode="grid_low_tariff",
        slot_limit_kwh=slot_limit,
        allocations=allocations,
        capacity_used=capacity_used,
        available_fn=lambda _slot: slot_limit,
    )
    home_battery_kwh = _allocate_slots(
        slots=_battery_slots_near_grid_window(home_slots, allocations),
        desired_kwh=min(battery_target, remaining - grid_low_tariff_kwh),
        mode="home_battery",
        slot_limit_kwh=slot_limit,
        allocations=allocations,
        capacity_used=capacity_used,
        available_fn=lambda _slot: slot_limit,
    )
    remaining -= grid_low_tariff_kwh + home_battery_kwh

    if remaining > 1e-9:
        additional_low_tariff_kwh = _allocate_slots(
            slots=list(reversed(low_tariff_slots)),
            desired_kwh=remaining,
            mode="grid_low_tariff",
            slot_limit_kwh=slot_limit,
            allocations=allocations,
            capacity_used=capacity_used,
            available_fn=lambda _slot: slot_limit,
        )
        grid_low_tariff_kwh += additional_low_tariff_kwh
        remaining -= additional_low_tariff_kwh

    grid_high_tariff_kwh = 0.0
    if data.allow_high_tariff_grid and remaining > 1e-9:
        high_tariff_slots = [slot for slot in home_slots if not slot.is_low_tariff]
        grid_high_tariff_kwh = _allocate_slots(
            slots=list(reversed(high_tariff_slots)),
            desired_kwh=remaining,
            mode="grid_high_tariff",
            slot_limit_kwh=slot_limit,
            allocations=allocations,
            capacity_used=capacity_used,
            available_fn=lambda _slot: slot_limit,
        )
        remaining -= grid_high_tariff_kwh

    solar_if_home_kwh = min(
        required,
        sum(
            min(max(slot.unused_surplus_kwh, 0.0), slot_limit)
            for slot in ordered
            if slot.solar_coverage >= 0.999
        ),
    )
    windows = _merge_windows(allocations, interval_minutes)
    mode, reason = _current_mode(
        data,
        now=now,
        windows=windows,
        shortfall_kwh=remaining,
    )
    next_window = next(
        (
            window
            for window in windows
            if _timeline_time(window.end) > _timeline_time(now)
        ),
        None,
    )
    return EVChargingPlan(
        source_id=data.source_id,
        mode=mode,
        reason=reason,
        departure=departure,
        return_at=return_at,
        required_input_kwh=required,
        action_window_minutes=interval_minutes,
        solar_kwh=solar_kwh,
        home_battery_kwh=home_battery_kwh,
        grid_low_tariff_kwh=grid_low_tariff_kwh,
        grid_high_tariff_kwh=grid_high_tariff_kwh,
        shortfall_kwh=max(remaining, 0.0),
        solar_if_home_kwh=solar_if_home_kwh,
        solar_if_home_covers_request=solar_if_home_kwh + 1e-9 >= required,
        forecast_complete=forecast_complete,
        next_action_start=next_window.start if next_window else None,
        next_action_end=next_window.end if next_window else None,
        timeline=tuple(windows),
    )


def calculate_ev_charging_plans(
    vehicles: list[EVChargingPlanInput],
    *,
    now: datetime,
    slots: list[EVChargingSlot],
    interval_minutes: int,
    battery_capacity_kwh: float,
    safe_discharge_soc: float,
) -> dict[str, EVChargingPlan]:
    """Plan multiple vehicles in priority order against shared energy."""
    available_slots = list(slots)
    plans: dict[str, EVChargingPlan] = {}
    for vehicle in sorted(vehicles, key=lambda item: (item.priority, item.source_id)):
        plan = calculate_ev_charging_plan(
            vehicle,
            now=now,
            slots=available_slots,
            interval_minutes=interval_minutes,
            battery_capacity_kwh=battery_capacity_kwh,
            safe_discharge_soc=safe_discharge_soc,
        )
        plans[vehicle.source_id] = plan
        available_slots = _reserve_shared_energy(available_slots, plan)
    return plans


def _allocate_slots(
    *,
    slots: list[EVChargingSlot],
    desired_kwh: float,
    mode: EVChargingMode,
    slot_limit_kwh: float,
    allocations: dict[datetime, tuple[EVChargingMode, float]],
    capacity_used: dict[datetime, float],
    available_fn: Callable[[EVChargingSlot], float],
) -> float:
    remaining = max(desired_kwh, 0.0)
    allocated = 0.0
    for slot in slots:
        if remaining <= 1e-9:
            break
        used = capacity_used.get(slot.start, 0.0)
        capacity = max(slot_limit_kwh - used, 0.0)
        value = min(remaining, capacity, max(float(available_fn(slot)), 0.0))
        if value <= 1e-9:
            continue
        existing = allocations.get(slot.start)
        if existing is not None and existing[0] != mode:
            continue
        allocations[slot.start] = (mode, (existing[1] if existing else 0.0) + value)
        capacity_used[slot.start] = used + value
        allocated += value
        remaining -= value
    return allocated


def _battery_slots_near_grid_window(
    slots: list[EVChargingSlot],
    allocations: dict[datetime, tuple[EVChargingMode, float]],
) -> list[EVChargingSlot]:
    """Prefer battery slots adjoining the planned low-tariff grid session."""
    grid_starts = sorted(
        (
            start
            for start, (mode, _energy) in allocations.items()
            if mode == "grid_low_tariff"
        ),
        key=_timeline_time,
    )
    if not grid_starts:
        return list(reversed(slots))

    first_grid_start = grid_starts[0]
    last_grid_start = grid_starts[-1]
    free_slots = [slot for slot in slots if slot.start not in allocations]
    before = sorted(
        (
            slot
            for slot in free_slots
            if _timeline_time(slot.start) < _timeline_time(first_grid_start)
        ),
        key=lambda slot: _timeline_time(slot.start),
        reverse=True,
    )
    after = sorted(
        (
            slot
            for slot in free_slots
            if _timeline_time(slot.start) > _timeline_time(last_grid_start)
        ),
        key=lambda slot: _timeline_time(slot.start),
    )
    between = sorted(
        (
            slot
            for slot in free_slots
            if _timeline_time(first_grid_start)
            < _timeline_time(slot.start)
            < _timeline_time(last_grid_start)
        ),
        key=lambda slot: _timeline_time(slot.start),
        reverse=True,
    )
    return [*before, *after, *between]


def _merge_windows(
    allocations: dict[datetime, tuple[EVChargingMode, float]],
    interval_minutes: int,
) -> list[EVChargingWindow]:
    windows: list[EVChargingWindow] = []
    delta = timedelta(minutes=interval_minutes)
    for start in sorted(allocations, key=_timeline_time):
        mode, energy = allocations[start]
        end = _add_elapsed_time(start, delta)
        if (
            windows
            and windows[-1].mode == mode
            and _timeline_time(windows[-1].end) == _timeline_time(start)
        ):
            previous = windows[-1]
            windows[-1] = EVChargingWindow(
                previous.start,
                end,
                mode,
                previous.energy_kwh + energy,
            )
        else:
            windows.append(EVChargingWindow(start, end, mode, energy))
    return windows


def _forecast_covers_window(
    slots: list[EVChargingSlot],
    *,
    start: datetime,
    end: datetime,
    interval_minutes: int,
) -> bool:
    """Return whether every interval through the vehicle's return is covered."""
    if not slots or any(slot.solar_coverage < 0.999 for slot in slots):
        return False
    delta = timedelta(minutes=interval_minutes)
    cursor = slots[0].start
    if _timeline_time(cursor) - _timeline_time(start) > delta:
        return False
    for slot in slots:
        difference = _timeline_time(slot.start) - _timeline_time(cursor)
        if abs(difference.total_seconds()) > 1:
            return False
        cursor = _add_elapsed_time(cursor, delta)
    return _timeline_time(cursor) >= _timeline_time(end)


def _reserve_shared_energy(
    slots: list[EVChargingSlot],
    plan: EVChargingPlan,
) -> list[EVChargingSlot]:
    """Reserve solar and shifted battery energy for lower-priority EVs."""
    reserved_solar: dict[datetime, float] = {}
    for window in plan.timeline:
        if window.mode != "solar":
            continue
        matching = [
            slot
            for slot in slots
            if _timeline_time(window.start)
            <= _timeline_time(slot.start)
            < _timeline_time(window.end)
        ]
        remaining = window.energy_kwh
        for slot in matching:
            value = min(remaining, max(slot.unused_surplus_kwh, 0.0))
            reserved_solar[slot.start] = value
            remaining -= value

    shifted_surplus_remaining = plan.home_battery_kwh
    reserved: list[EVChargingSlot] = []
    for slot in slots:
        surplus = max(
            slot.unused_surplus_kwh - reserved_solar.get(slot.start, 0.0),
            0.0,
        )
        if (
            shifted_surplus_remaining > 1e-9
            and plan.departure is not None
            and plan.return_at is not None
            and _timeline_time(plan.departure)
            <= _timeline_time(slot.start)
            < _timeline_time(plan.return_at)
        ):
            shifted = min(surplus, shifted_surplus_remaining)
            surplus -= shifted
            shifted_surplus_remaining -= shifted
        reserved.append(
            replace(
                slot,
                unused_surplus_kwh=surplus,
                battery_kwh=max(slot.battery_kwh - plan.home_battery_kwh, 0.0),
            )
        )
    return reserved


def _current_mode(
    data: EVChargingPlanInput,
    *,
    now: datetime,
    windows: list[EVChargingWindow],
    shortfall_kwh: float,
) -> tuple[EVChargingMode, str]:
    if data.currently_home is None or data.connected is None:
        return "unavailable", "live_availability_unavailable"
    if data.currently_home is False:
        return "off", "vehicle_away"
    if data.connected is False:
        return "connect_vehicle", "vehicle_home_but_disconnected"
    current_or_next = next(
        (
            window
            for window in windows
            if _timeline_time(window.end) > _timeline_time(now)
        ),
        None,
    )
    if current_or_next is None:
        if shortfall_kwh > 1e-9:
            return "shortfall", "deadline_shortfall"
        return "complete", "request_complete"
    if _timeline_time(current_or_next.start) <= _timeline_time(now):
        return current_or_next.mode, f"charging_from_{current_or_next.mode}"
    if shortfall_kwh > 1e-9 and not windows:
        return "shortfall", "deadline_shortfall"
    return "wait_for_solar", f"next_action_{current_or_next.mode}"


def _next_departure(now: datetime, data: EVChargingPlanInput) -> datetime:
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        if day.weekday() not in data.workdays:
            continue
        candidate = datetime.combine(day, data.departure_time, tzinfo=now.tzinfo)
        if _timeline_time(candidate) > _timeline_time(now):
            return candidate
    raise ValueError("No departure found in the next eight days")


def _scheduled_home(timestamp: datetime, data: EVChargingPlanInput) -> bool:
    if timestamp.weekday() not in data.workdays:
        return True
    local_time = timestamp.timetz().replace(tzinfo=None)
    return local_time < data.departure_time or local_time >= data.return_time


def _combine_local(reference: datetime, value: time) -> datetime:
    return datetime.combine(reference.date(), value, tzinfo=reference.tzinfo)


def _add_elapsed_time(timestamp: datetime, delta: timedelta) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp + delta
    return (timestamp.astimezone(UTC) + delta).astimezone(timestamp.tzinfo)


def _timeline_time(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp
    return timestamp.astimezone(UTC)


def _unavailable(
    data: EVChargingPlanInput,
    reason: str,
    interval_minutes: int,
) -> EVChargingPlan:
    return EVChargingPlan(
        source_id=data.source_id,
        mode="unavailable",
        reason=reason,
        departure=None,
        return_at=None,
        required_input_kwh=max(data.required_input_kwh, 0.0),
        action_window_minutes=max(interval_minutes, 0),
        shortfall_kwh=max(data.required_input_kwh, 0.0),
        forecast_complete=False,
    )


def _round(value: float) -> float:
    return round(float(value), 6)
