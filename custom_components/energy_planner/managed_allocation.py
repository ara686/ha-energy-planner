"""Pure type-aware managed-load allocation over forecast surplus slots."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from .allocation import ManagedLoadEstimate
from .hot_water import HotWaterDemand

LoadType = Literal["generic", "hot_water"]
AllocationState = Literal["ok", "insufficient_data"]


@dataclass(frozen=True)
class SurplusSlot:
    """Unused solar energy available in one planner interval."""

    start: datetime
    available_kwh: float


@dataclass(frozen=True)
class GenericAllocationInput:
    """Generic history-based demand participating in managed allocation."""

    source_id: str
    priority: int
    estimate: ManagedLoadEstimate


@dataclass(frozen=True)
class HotWaterAllocationInput:
    """Hot-water thermal demand participating in managed allocation."""

    source_id: str
    priority: int
    heater_power_kw: float
    demand: HotWaterDemand


@dataclass(frozen=True)
class UnavailableAllocationInput:
    """Configured managed load whose model inputs are currently unavailable."""

    source_id: str
    load_type: LoadType
    priority: int
    reason: str


ManagedAllocationInput = (
    GenericAllocationInput | HotWaterAllocationInput | UnavailableAllocationInput
)


@dataclass
class ManagedLoadAllocation:
    """One load's result for one complete local day."""

    source_id: str
    load_type: LoadType
    priority: int
    method: str
    expected_demand_kwh: float
    recommended_kwh: float | None
    state: AllocationState = "ok"
    reason: str = ""
    minimum_required_kwh: float = 0.0
    flexible_capacity_kwh: float = 0.0
    minimum_allocated_kwh: float = 0.0
    minimum_shortfall_kwh: float | None = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "source_entity_id": self.source_id,
            "load_type": self.load_type,
            "priority": self.priority,
            "state": self.state,
            "method": self.method,
            "expected_demand_kwh": _round(self.expected_demand_kwh),
            "recommended_kwh": (
                _round(self.recommended_kwh)
                if self.recommended_kwh is not None
                else None
            ),
            "reason": self.reason,
        }
        if self.load_type == "hot_water":
            payload.update(
                {
                    "minimum_required_kwh": _round(self.minimum_required_kwh),
                    "flexible_capacity_kwh": _round(self.flexible_capacity_kwh),
                    "minimum_allocated_kwh": _round(self.minimum_allocated_kwh),
                    "minimum_shortfall_kwh": (
                        _round(self.minimum_shortfall_kwh)
                        if self.minimum_shortfall_kwh is not None
                        else None
                    ),
                    **self.details,
                }
            )
        else:
            payload.update(self.details)
        return payload


@dataclass
class ManagedDayAllocation:
    """Allocation and hot-water schedule for one local calendar day."""

    state: AllocationState
    target_date: date
    available_surplus_kwh: float | None
    expected_demand_kwh: float
    recommended_kwh: float | None
    unallocated_surplus_kwh: float | None
    loads: list[ManagedLoadAllocation]
    hot_water_energy_by_slot: dict[datetime, float] = field(default_factory=dict)
    hot_water_scheduled_by_source: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "target_date": self.target_date.isoformat(),
            "available_surplus_kwh": (
                _round(self.available_surplus_kwh)
                if self.available_surplus_kwh is not None
                else None
            ),
            "expected_demand_kwh": _round(self.expected_demand_kwh),
            "recommended_kwh": (
                _round(self.recommended_kwh)
                if self.recommended_kwh is not None
                else None
            ),
            "unallocated_surplus_kwh": (
                _round(self.unallocated_surplus_kwh)
                if self.unallocated_surplus_kwh is not None
                else None
            ),
            "loads": {
                load.source_id: load.as_dict()
                for load in sorted(self.loads, key=lambda item: item.source_id)
            },
            "warnings": self.warnings,
        }


def allocate_managed_day(
    *,
    target_date: date,
    interval_minutes: int,
    surplus_complete: bool,
    surplus_slots: list[SurplusSlot],
    loads: list[ManagedAllocationInput],
) -> ManagedDayAllocation:
    """Allocate one complete day's surplus in three ordered phases."""
    results = {load.source_id: _initial_result(load) for load in loads}
    expected = sum(item.expected_demand_kwh for item in results.values())
    if not surplus_complete:
        for result in results.values():
            result.recommended_kwh = None
            result.minimum_shortfall_kwh = None
            result.state = "insufficient_data"
        return ManagedDayAllocation(
            state="insufficient_data",
            target_date=target_date,
            available_surplus_kwh=None,
            expected_demand_kwh=expected,
            recommended_kwh=None,
            unallocated_surplus_kwh=None,
            loads=list(results.values()),
            warnings=["Managed-load surplus forecast is not fully covered."],
        )

    slot_pool = {
        _timeline_time(slot.start): max(float(slot.available_kwh), 0.0)
        for slot in surplus_slots
    }
    initial_surplus = sum(slot_pool.values())
    power_used: dict[tuple[str, datetime], float] = {}
    hot_schedule: dict[datetime, float] = {}
    hot_by_source: dict[str, float] = {}

    hot_loads = [load for load in loads if isinstance(load, HotWaterAllocationInput)]
    generic_loads = [load for load in loads if isinstance(load, GenericAllocationInput)]
    _allocate_phase(
        items=[
            _PhaseItem(
                source_id=load.source_id,
                priority=load.priority,
                desired_kwh=load.demand.minimum_required_kwh,
                heater_power_kw=load.heater_power_kw,
                is_hot_water=True,
            )
            for load in hot_loads
        ],
        interval_minutes=interval_minutes,
        slot_pool=slot_pool,
        results=results,
        power_used=power_used,
        hot_schedule=hot_schedule,
        hot_by_source=hot_by_source,
        minimum_phase=True,
    )
    _allocate_phase(
        items=[
            _PhaseItem(
                source_id=load.source_id,
                priority=load.priority,
                desired_kwh=load.estimate.expected_demand_kwh,
            )
            for load in generic_loads
        ],
        interval_minutes=interval_minutes,
        slot_pool=slot_pool,
        results=results,
        power_used=power_used,
        hot_schedule=hot_schedule,
        hot_by_source=hot_by_source,
    )
    _allocate_phase(
        items=[
            _PhaseItem(
                source_id=load.source_id,
                priority=load.priority,
                desired_kwh=load.demand.flexible_capacity_kwh,
                heater_power_kw=load.heater_power_kw,
                is_hot_water=True,
            )
            for load in hot_loads
        ],
        interval_minutes=interval_minutes,
        slot_pool=slot_pool,
        results=results,
        power_used=power_used,
        hot_schedule=hot_schedule,
        hot_by_source=hot_by_source,
    )

    for result in results.values():
        if result.recommended_kwh is None:
            continue
        result.minimum_shortfall_kwh = max(
            result.minimum_required_kwh - result.minimum_allocated_kwh,
            0.0,
        )
    recommended = sum(result.recommended_kwh or 0.0 for result in results.values())
    unallocated = sum(slot_pool.values())
    usable_loads = [result for result in results.values() if result.state == "ok"]
    warnings = []
    if not loads:
        warnings.append("No managed loads are configured.")
    if loads and not usable_loads:
        warnings.append("Managed loads have no usable demand estimate.")
    return ManagedDayAllocation(
        state="ok" if usable_loads else "insufficient_data",
        target_date=target_date,
        available_surplus_kwh=initial_surplus,
        expected_demand_kwh=expected,
        recommended_kwh=recommended,
        unallocated_surplus_kwh=unallocated,
        loads=list(results.values()),
        hot_water_energy_by_slot={
            start: value for start, value in hot_schedule.items() if value > 0
        },
        hot_water_scheduled_by_source={
            source_id: _round(value) for source_id, value in hot_by_source.items()
        },
        warnings=warnings,
    )


@dataclass
class _PhaseItem:
    source_id: str
    priority: int
    desired_kwh: float
    heater_power_kw: float | None = None
    is_hot_water: bool = False
    allocated_kwh: float = 0.0

    @property
    def remaining_kwh(self) -> float:
        return max(self.desired_kwh - self.allocated_kwh, 0.0)


def _allocate_phase(
    *,
    items: list[_PhaseItem],
    interval_minutes: int,
    slot_pool: dict[datetime, float],
    results: dict[str, ManagedLoadAllocation],
    power_used: dict[tuple[str, datetime], float],
    hot_schedule: dict[datetime, float],
    hot_by_source: dict[str, float],
    minimum_phase: bool = False,
) -> None:
    for priority in sorted({item.priority for item in items}):
        group = [item for item in items if item.priority == priority]
        for slot_start in sorted(slot_pool):
            available = slot_pool[slot_start]
            if available <= 1e-12:
                continue
            capacities: dict[str, float] = {}
            weights: dict[str, float] = {}
            items_by_source = {item.source_id: item for item in group}
            for item in group:
                remaining = item.remaining_kwh
                if remaining <= 1e-12:
                    continue
                capacity = remaining
                if item.heater_power_kw is not None:
                    slot_limit = max(item.heater_power_kw, 0.0) * interval_minutes / 60
                    already_used = power_used.get((item.source_id, slot_start), 0.0)
                    capacity = min(capacity, max(slot_limit - already_used, 0.0))
                if capacity <= 1e-12:
                    continue
                capacities[item.source_id] = capacity
                weights[item.source_id] = remaining
            allocations = _proportional_capped_allocations(
                available=available,
                capacities=capacities,
                weights=weights,
            )
            for source_id, value in allocations.items():
                item = items_by_source[source_id]
                item.allocated_kwh += value
                result = results[source_id]
                result.recommended_kwh = (result.recommended_kwh or 0.0) + value
                if minimum_phase:
                    result.minimum_allocated_kwh += value
                if item.is_hot_water:
                    power_used[(source_id, slot_start)] = (
                        power_used.get((source_id, slot_start), 0.0) + value
                    )
                    hot_schedule[slot_start] = hot_schedule.get(slot_start, 0.0) + value
                    hot_by_source[source_id] = hot_by_source.get(source_id, 0.0) + value
                slot_pool[slot_start] -= value


def _proportional_capped_allocations(
    *,
    available: float,
    capacities: dict[str, float],
    weights: dict[str, float],
) -> dict[str, float]:
    remaining_available = max(available, 0.0)
    remaining = dict(capacities)
    allocated = {source_id: 0.0 for source_id in capacities}
    while remaining_available > 1e-12 and remaining:
        total_weight = sum(weights[source_id] for source_id in remaining)
        if total_weight <= 0:
            break
        distributed = 0.0
        saturated: list[str] = []
        for source_id, capacity in remaining.items():
            share = remaining_available * weights[source_id] / total_weight
            value = min(share, capacity)
            allocated[source_id] += value
            distributed += value
            remaining[source_id] = capacity - value
            if remaining[source_id] <= 1e-12:
                saturated.append(source_id)
        remaining_available -= distributed
        for source_id in saturated:
            remaining.pop(source_id, None)
        if distributed <= 1e-12 or not saturated:
            break
    return {source_id: value for source_id, value in allocated.items() if value > 0}


def _initial_result(load: ManagedAllocationInput) -> ManagedLoadAllocation:
    if isinstance(load, GenericAllocationInput):
        estimate = load.estimate
        return ManagedLoadAllocation(
            source_id=load.source_id,
            load_type="generic",
            priority=load.priority,
            method=estimate.method,
            expected_demand_kwh=estimate.expected_demand_kwh,
            recommended_kwh=0.0,
            state=(
                "ok" if estimate.method != "insufficient_data" else "insufficient_data"
            ),
            reason=estimate.reason,
            details={
                "observed_days": estimate.observed_days,
                "active_days": estimate.active_days,
                "active_probability": estimate.active_probability,
                "active_day_median_kwh": estimate.active_day_median_kwh,
                "confidence": estimate.confidence,
            },
        )
    if isinstance(load, HotWaterAllocationInput):
        return ManagedLoadAllocation(
            source_id=load.source_id,
            load_type="hot_water",
            priority=load.priority,
            method="thermal_model",
            expected_demand_kwh=load.demand.minimum_required_kwh,
            recommended_kwh=0.0,
            reason="current_temperatures",
            minimum_required_kwh=load.demand.minimum_required_kwh,
            flexible_capacity_kwh=load.demand.flexible_capacity_kwh,
            details=load.demand.as_dict(),
        )
    return ManagedLoadAllocation(
        source_id=load.source_id,
        load_type=load.load_type,
        priority=load.priority,
        method="insufficient_data",
        expected_demand_kwh=0.0,
        recommended_kwh=None,
        state="insufficient_data",
        reason=load.reason,
        minimum_shortfall_kwh=None,
    )


def _round(value: float) -> float:
    return round(float(value), 6)


def _timeline_time(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp
    return timestamp.astimezone(UTC)
