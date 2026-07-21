from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Any, Literal

AllocationConfidence = Literal["insufficient", "low", "medium", "high"]
AllocationMethod = Literal["history", "requested", "insufficient_data"]
AllocationState = Literal["ok", "insufficient_data"]

ACTIVE_DAY_MIN_KWH = 0.05
MINIMUM_HISTORY_DAYS = 3


@dataclass(frozen=True)
class ManagedLoadDemandInput:
    source_id: str
    daily_kwh: list[float]
    requested_energy_kwh: float | None = None


@dataclass(frozen=True)
class ManagedLoadEstimate:
    source_id: str
    method: AllocationMethod
    expected_demand_kwh: float
    recommended_kwh: float | None
    observed_days: int
    active_days: int
    active_probability: float
    active_day_median_kwh: float
    confidence: AllocationConfidence
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_entity_id": self.source_id,
            "method": self.method,
            "expected_demand_kwh": self.expected_demand_kwh,
            "recommended_kwh": self.recommended_kwh,
            "observed_days": self.observed_days,
            "active_days": self.active_days,
            "active_probability": self.active_probability,
            "active_day_median_kwh": self.active_day_median_kwh,
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class SurplusAllocationResult:
    state: AllocationState
    target_date: date
    available_surplus_kwh: float | None
    expected_demand_kwh: float
    recommended_kwh: float | None
    unallocated_surplus_kwh: float | None
    loads: list[ManagedLoadEstimate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "target_date": self.target_date.isoformat(),
            "available_surplus_kwh": self.available_surplus_kwh,
            "expected_demand_kwh": self.expected_demand_kwh,
            "recommended_kwh": self.recommended_kwh,
            "unallocated_surplus_kwh": self.unallocated_surplus_kwh,
            "loads": {
                load.source_id: load.as_dict()
                for load in sorted(self.loads, key=lambda item: item.source_id)
            },
            "warnings": self.warnings,
        }


def calculate_surplus_allocation(
    *,
    target_date: date,
    available_surplus_kwh: float | None,
    surplus_complete: bool,
    loads: list[ManagedLoadDemandInput],
) -> SurplusAllocationResult:
    """Allocate forecast surplus across generic managed-load demand estimates."""
    estimates = [_estimate_load(load) for load in loads]
    total_expected = _round_energy(
        sum(estimate.expected_demand_kwh for estimate in estimates)
    )
    warnings: list[str] = []

    if available_surplus_kwh is None or not surplus_complete:
        warnings.append("Tomorrow surplus forecast is not fully covered.")
        return SurplusAllocationResult(
            state="insufficient_data",
            target_date=target_date,
            available_surplus_kwh=None,
            expected_demand_kwh=total_expected,
            recommended_kwh=None,
            unallocated_surplus_kwh=None,
            loads=estimates,
            warnings=warnings,
        )

    surplus = max(available_surplus_kwh, 0.0)
    if not loads:
        warnings.append("No managed loads are configured.")
    if total_expected <= 0:
        warnings.append("Managed-load history has no usable demand estimate.")

    allocation_factor = (
        min(1.0, surplus / total_expected) if total_expected > 0 else 0.0
    )
    allocated_estimates = [
        ManagedLoadEstimate(
            source_id=estimate.source_id,
            method=estimate.method,
            expected_demand_kwh=estimate.expected_demand_kwh,
            recommended_kwh=_round_energy(
                estimate.expected_demand_kwh * allocation_factor
            ),
            observed_days=estimate.observed_days,
            active_days=estimate.active_days,
            active_probability=estimate.active_probability,
            active_day_median_kwh=estimate.active_day_median_kwh,
            confidence=estimate.confidence,
            reason=estimate.reason,
        )
        for estimate in estimates
    ]
    recommended = _round_energy(
        sum(estimate.recommended_kwh or 0.0 for estimate in allocated_estimates)
    )
    return SurplusAllocationResult(
        state="ok" if total_expected > 0 else "insufficient_data",
        target_date=target_date,
        available_surplus_kwh=_round_energy(surplus),
        expected_demand_kwh=total_expected,
        recommended_kwh=recommended,
        unallocated_surplus_kwh=_round_energy(max(surplus - recommended, 0.0)),
        loads=allocated_estimates,
        warnings=warnings,
    )


def _estimate_load(load: ManagedLoadDemandInput) -> ManagedLoadEstimate:
    values = [max(float(value), 0.0) for value in load.daily_kwh]
    observed_days = len(values)
    active_values = [value for value in values if value >= ACTIVE_DAY_MIN_KWH]
    active_days = len(active_values)
    active_probability = active_days / observed_days if observed_days else 0.0
    active_median = median(active_values) if active_values else 0.0

    if load.requested_energy_kwh is not None:
        expected = max(load.requested_energy_kwh, 0.0)
        return ManagedLoadEstimate(
            source_id=load.source_id,
            method="requested",
            expected_demand_kwh=_round_energy(expected),
            recommended_kwh=None,
            observed_days=observed_days,
            active_days=active_days,
            active_probability=_round_probability(active_probability),
            active_day_median_kwh=_round_energy(active_median),
            confidence="high",
            reason="requested_energy",
        )

    if observed_days < MINIMUM_HISTORY_DAYS:
        return ManagedLoadEstimate(
            source_id=load.source_id,
            method="insufficient_data",
            expected_demand_kwh=0.0,
            recommended_kwh=None,
            observed_days=observed_days,
            active_days=active_days,
            active_probability=_round_probability(active_probability),
            active_day_median_kwh=_round_energy(active_median),
            confidence="insufficient",
            reason="insufficient_history",
        )

    expected = active_probability * active_median
    return ManagedLoadEstimate(
        source_id=load.source_id,
        method="history",
        expected_demand_kwh=_round_energy(expected),
        recommended_kwh=None,
        observed_days=observed_days,
        active_days=active_days,
        active_probability=_round_probability(active_probability),
        active_day_median_kwh=_round_energy(active_median),
        confidence=_history_confidence(values, active_values, active_probability),
        reason="historical_daily_usage" if active_values else "no_historical_usage",
    )


def _history_confidence(
    values: list[float],
    active_values: list[float],
    active_probability: float,
) -> AllocationConfidence:
    observed_days = len(values)
    if observed_days < MINIMUM_HISTORY_DAYS:
        return "insufficient"
    if not active_values:
        return "low"

    active_median = median(active_values)
    relative_mad = (
        median(abs(value - active_median) for value in active_values) / active_median
        if active_median > 0
        else 1.0
    )
    if observed_days >= 7 and active_probability >= 0.7 and relative_mad <= 0.25:
        return "high"
    if observed_days >= 5 and active_probability >= 0.4:
        return "medium"
    return "low"


def _round_energy(value: float) -> float:
    return round(value, 3)


def _round_probability(value: float) -> float:
    return round(value, 3)
