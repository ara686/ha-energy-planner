from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from math import ceil

from .models import (
    ForecastSlot,
    PlannerInput,
    PlannerResult,
    SocForecastPoint,
    SolarForecastPoint,
    TimeWindow,
)
from .periods import infer_period_minutes


def generate_forecast_slots(
    *,
    now: datetime,
    horizon_hours: int,
    interval_minutes: int,
    solar_forecast: list[SolarForecastPoint],
    consumption_kwh_per_hour: float | Callable[[datetime], float],
) -> list[ForecastSlot]:
    """Generate regular planner slots from normalized forecast inputs."""
    if interval_minutes <= 0 or horizon_hours <= 0:
        return []

    interval = timedelta(minutes=interval_minutes)
    horizon_end = now + timedelta(hours=horizon_hours)
    solar_periods = _solar_periods(solar_forecast, interval_minutes)

    slots: list[ForecastSlot] = []
    slot_start = _ceil_to_interval(now, interval_minutes)
    while slot_start < horizon_end:
        slot_solar_kwh, solar_coverage = _solar_for_slot(
            slot_start=slot_start,
            interval_minutes=interval_minutes,
            solar_periods=solar_periods,
        )
        slot_consumption_kwh_per_hour = (
            consumption_kwh_per_hour(slot_start)
            if callable(consumption_kwh_per_hour)
            else consumption_kwh_per_hour
        )
        slots.append(
            ForecastSlot(
                start=slot_start,
                solar_kwh=_round(slot_solar_kwh),
                consumption_kwh=_round(
                    max(0.0, slot_consumption_kwh_per_hour) * interval_minutes / 60
                ),
                solar_coverage=solar_coverage,
            )
        )
        slot_start = _add_elapsed_time(slot_start, interval)
    return slots


@dataclass(frozen=True)
class _Simulation:
    points: list[SocForecastPoint]
    vt_grid_import_kwh: float
    charged_kwh: float
    unused_surplus_kwh: float
    unused_surplus_today_kwh: float
    first_full_time: datetime | None

    @property
    def final_soc(self) -> float:
        if not self.points:
            return 0.0
        return self.points[-1].soc_percent


def calculate_plan(data: PlannerInput) -> PlannerResult:
    """Calculate energy planner result from plain Python input models."""
    warnings = _validate_input(data)
    if data.battery_capacity_kwh <= 0:
        return PlannerResult(
            state="error",
            updated=data.now,
            warnings=["Battery capacity must be greater than zero."],
        )

    if data.forecast_horizon_hours < 24:
        warnings.append("Forecast horizon must be at least 24 hours.")

    slots = _normalized_slots(data)
    if not slots:
        current_soc = _clamp(data.battery_soc, 0.0, 100.0)
        floor_soc = _clamp(data.battery_min_soc, 0.0, 100.0)
        return PlannerResult(
            state="insufficient_data",
            updated=data.now,
            plan=_empty_plan(data, current_soc, floor_soc),
            forecast={
                "horizon_hours": data.forecast_horizon_hours,
                "source": "ha_entities",
                "points": [],
            },
            warnings=warnings + ["No forecast slots available."],
        )

    current_soc = _clamp(data.battery_soc, 0.0, 100.0)
    floor_soc = _clamp(data.battery_min_soc, 0.0, 100.0)
    floor_kwh = _soc_to_kwh(floor_soc, data.battery_capacity_kwh)

    lock_start = _find_lock_start(data)
    horizon_end = data.now + timedelta(hours=max(data.forecast_horizon_hours, 24))
    sun_start = _find_sun_start(data, slots, start=lock_start, end=horizon_end)
    sun_start = sun_start or horizon_end
    planner_start = (
        data.now
        if _is_in_window(data.now, data.charge_window)
        else _next_window_start(data.now, data.charge_window)
    )
    deficit_until_sun = _vt_deficit_kwh(
        slots=slots,
        data=data,
        start=lock_start,
        end=sun_start,
    )
    lock_soc = _clamp(
        _round_soc_percent(floor_kwh + deficit_until_sun, data.battery_capacity_kwh)
        + data.soc_reserve_percent,
        floor_soc,
        100.0,
    )
    if lock_soc >= 95:
        lock_soc = 100.0

    soc_at_planner_start = _predict_soc_at(
        data=data,
        slots=slots,
        start=data.now,
        end=planner_start,
        initial_soc=current_soc,
        nt_lock_soc=floor_soc,
    )
    kwh_at_planner_start = _soc_to_kwh(
        soc_at_planner_start,
        data.battery_capacity_kwh,
    )
    soc_at_lock_start = _predict_soc_at(
        data=data,
        slots=slots,
        start=data.now,
        end=lock_start,
        initial_soc=current_soc,
        nt_lock_soc=floor_soc,
    )
    kwh_at_lock_start = _soc_to_kwh(soc_at_lock_start, data.battery_capacity_kwh)

    charge_to_soc = _calculate_charge_to_soc(
        data=data,
        slots=_slots_between(slots, planner_start, horizon_end),
        floor_soc=floor_soc,
        initial_soc=soc_at_planner_start,
        nt_lock_soc=lock_soc,
    )
    target_soc = max(lock_soc, charge_to_soc)
    safe_discharge_soc = _calculate_safe_discharge_soc(
        data=data,
        slots=slots,
        floor_soc=floor_soc,
        current_soc=current_soc,
        grid_charge_target_soc=target_soc,
        nt_lock_soc=lock_soc,
    )
    free_capacity_soc = max(0.0, current_soc - safe_discharge_soc)

    forecast_simulation = _simulate(
        data=data,
        slots=slots,
        initial_soc=current_soc,
        grid_charge_target_soc=None,
        nt_lock_soc=floor_soc,
    )
    planned_simulation = _simulate(
        data=data,
        slots=slots,
        initial_soc=current_soc,
        grid_charge_target_soc=target_soc,
        nt_lock_soc=lock_soc,
    )
    forecast_24h = _point_at_or_project_end(
        forecast_simulation.points,
        data.now + timedelta(hours=24),
        data.interval_minutes,
    )
    forecast_horizon = _point_at_or_project_end(
        forecast_simulation.points, horizon_end, data.interval_minutes
    ) or (forecast_simulation.points[-1] if forecast_simulation.points else None)

    state = "warning" if warnings else "ok"
    if not forecast_24h:
        state = "warning"
        warnings.append("Forecast data does not cover the required 24 hour horizon.")

    points = [point.as_dict() for point in forecast_simulation.points]
    soc_forecast_24h = forecast_24h.as_dict() if forecast_24h else None
    daily_surplus = _daily_surplus_forecasts(
        forecast_simulation.points,
        reference=data.now,
        interval_minutes=data.interval_minutes,
    )
    tomorrow_date = data.now.date() + timedelta(days=1)
    tomorrow_surplus = next(
        (item for item in daily_surplus if item["date"] == tomorrow_date.isoformat()),
        None,
    )
    tomorrow_complete = bool(tomorrow_surplus and tomorrow_surplus["complete"])

    return PlannerResult(
        state=state,
        updated=data.now,
        plan={
            "lock_soc": _round(lock_soc),
            "charge_to_soc": _round(charge_to_soc),
            "target_soc": _round(target_soc),
            "safe_discharge_soc": _round(safe_discharge_soc),
            "free_capacity_soc": _round(free_capacity_soc),
            "free_capacity_kwh": _round(
                _soc_to_kwh(free_capacity_soc, data.battery_capacity_kwh)
            ),
            "unused_surplus_kwh": _round(forecast_simulation.unused_surplus_today_kwh),
            "unused_surplus_kwh_total": _round(forecast_simulation.unused_surplus_kwh),
            "unused_surplus_by_day": daily_surplus,
            "unused_surplus_tomorrow_kwh": (
                tomorrow_surplus["unused_surplus_kwh"]
                if tomorrow_complete and tomorrow_surplus
                else None
            ),
            "unused_surplus_tomorrow_coverage_percent": (
                tomorrow_surplus["coverage_percent"] if tomorrow_surplus else 0
            ),
            "unused_surplus_tomorrow_solar_coverage_percent": (
                tomorrow_surplus["solar_coverage_percent"] if tomorrow_surplus else 0
            ),
            "first_full_time": _iso_or_none(forecast_simulation.first_full_time),
            "vt_grid_import_kwh_at_target": _round(
                planned_simulation.vt_grid_import_kwh
            ),
            "charged_kwh_total_at_target": _round(planned_simulation.charged_kwh),
            "soc_at_planner_start": _round(soc_at_planner_start),
            "kwh_at_planner_start": _round(kwh_at_planner_start),
            "planner_start": _iso_or_none(planner_start),
            "lock_start": _iso_or_none(lock_start),
            "sun_start": _iso_or_none(sun_start),
            "soc_at_lock_start": _round(soc_at_lock_start),
            "kwh_at_lock_start": _round(kwh_at_lock_start),
            "vt_peak_deficit_kwh_from_lock_start": _round(deficit_until_sun),
            "soc_forecast": {
                "horizon_hours": data.forecast_horizon_hours,
                "source": "ha_entities",
                "points": points,
            },
            "soc_forecast_24h": soc_forecast_24h,
            "soc_at_forecast_horizon": (
                forecast_horizon.soc_percent
                if forecast_horizon
                else _round_soc_percent(
                    _soc_to_kwh(current_soc, data.battery_capacity_kwh),
                    data.battery_capacity_kwh,
                )
            ),
        },
        forecast={
            "horizon_hours": data.forecast_horizon_hours,
            "source": "ha_entities",
            "points": points,
        },
        warnings=warnings,
        debug={
            "slot_count": len(slots),
            "floor_kwh": _round(floor_kwh),
            "deficit_until_sun_kwh": _round(deficit_until_sun),
        },
    )


def _validate_input(data: PlannerInput) -> list[str]:
    warnings: list[str] = []
    if data.interval_minutes <= 0:
        warnings.append("Interval minutes must be greater than zero.")
    if data.grid_charge_max_kw < 0:
        warnings.append("Grid charge power cannot be negative.")
    if not 0 <= data.grid_charge_efficiency <= 1:
        warnings.append("Grid charge efficiency must be between 0 and 1.")
    if data.battery_soc < data.battery_min_soc:
        warnings.append("Battery SoC is below configured minimum SoC.")
    return warnings


def _normalized_slots(data: PlannerInput) -> list[ForecastSlot]:
    horizon_end = data.now + timedelta(hours=max(data.forecast_horizon_hours, 24))
    return sorted(
        (
            ForecastSlot(
                start=slot.start,
                solar_kwh=max(0.0, slot.solar_kwh),
                consumption_kwh=max(0.0, slot.consumption_kwh),
                solar_coverage=_clamp(slot.solar_coverage, 0.0, 1.0),
            )
            for slot in data.slots
            if data.now <= slot.start < horizon_end
        ),
        key=lambda slot: slot.start,
    )


def _solar_periods(
    solar_forecast: list[SolarForecastPoint],
    default_period_minutes: int,
) -> list[tuple[datetime, datetime, float]]:
    sorted_points = sorted(solar_forecast, key=lambda point: point.start)
    starts = [point.start for point in sorted_points]
    periods: list[tuple[datetime, datetime, float]] = []
    for index, point in enumerate(sorted_points):
        period_minutes = infer_period_minutes(
            starts,
            index,
            explicit_period_minutes=point.period_minutes,
            default_period_minutes=default_period_minutes,
        )
        if period_minutes is None:
            continue
        periods.append(
            (
                point.start,
                _add_elapsed_time(point.start, timedelta(minutes=period_minutes)),
                max(0.0, point.solar_kwh),
            )
        )
    return periods


def _solar_for_slot(
    *,
    slot_start: datetime,
    interval_minutes: int,
    solar_periods: list[tuple[datetime, datetime, float]],
) -> tuple[float, float]:
    slot_end = _add_elapsed_time(slot_start, timedelta(minutes=interval_minutes))
    timeline_slot_start = _timeline_time(slot_start)
    timeline_slot_end = _timeline_time(slot_end)
    solar_kwh = 0.0
    covered_ranges: list[tuple[datetime, datetime]] = []
    for period_start, period_end, period_solar_kwh in solar_periods:
        timeline_period_start = _timeline_time(period_start)
        timeline_period_end = _timeline_time(period_end)
        overlap_start = max(timeline_slot_start, timeline_period_start)
        overlap_end = min(timeline_slot_end, timeline_period_end)
        if overlap_start >= overlap_end:
            continue
        period_seconds = (timeline_period_end - timeline_period_start).total_seconds()
        if period_seconds <= 0:
            continue
        overlap_ratio = (overlap_end - overlap_start).total_seconds() / period_seconds
        solar_kwh += period_solar_kwh * overlap_ratio
        covered_ranges.append((overlap_start, overlap_end))

    covered_seconds = 0.0
    current_start: datetime | None = None
    current_end: datetime | None = None
    for overlap_start, overlap_end in sorted(covered_ranges):
        if current_start is None:
            current_start, current_end = overlap_start, overlap_end
            continue
        assert current_end is not None
        if overlap_start <= current_end:
            current_end = max(current_end, overlap_end)
            continue
        covered_seconds += (current_end - current_start).total_seconds()
        current_start, current_end = overlap_start, overlap_end
    if current_start is not None and current_end is not None:
        covered_seconds += (current_end - current_start).total_seconds()

    slot_seconds = max(
        (timeline_slot_end - timeline_slot_start).total_seconds(),
        1.0,
    )
    return solar_kwh, _round(_clamp(covered_seconds / slot_seconds, 0.0, 1.0))


def _empty_plan(
    data: PlannerInput,
    current_soc: float,
    floor_soc: float,
) -> dict[str, object]:
    current_kwh = _soc_to_kwh(current_soc, data.battery_capacity_kwh)
    return {
        "lock_soc": _round(max(current_soc, floor_soc)),
        "charge_to_soc": _round(max(current_soc, floor_soc)),
        "target_soc": _round(max(current_soc, floor_soc)),
        "safe_discharge_soc": _round(floor_soc),
        "free_capacity_soc": _round(max(0.0, current_soc - floor_soc)),
        "free_capacity_kwh": _round(
            _soc_to_kwh(max(0.0, current_soc - floor_soc), data.battery_capacity_kwh)
        ),
        "unused_surplus_kwh": 0.0,
        "unused_surplus_kwh_total": 0.0,
        "unused_surplus_by_day": [],
        "unused_surplus_tomorrow_kwh": None,
        "unused_surplus_tomorrow_coverage_percent": 0,
        "unused_surplus_tomorrow_solar_coverage_percent": 0,
        "first_full_time": None,
        "vt_grid_import_kwh_at_target": 0.0,
        "charged_kwh_total_at_target": 0.0,
        "soc_at_planner_start": _round(current_soc),
        "kwh_at_planner_start": _round(current_kwh),
        "lock_start": None,
        "sun_start": None,
        "soc_at_lock_start": _round(current_soc),
        "kwh_at_lock_start": _round(current_kwh),
        "vt_peak_deficit_kwh_from_lock_start": 0.0,
        "soc_forecast": {
            "horizon_hours": data.forecast_horizon_hours,
            "source": "ha_entities",
            "points": [],
        },
        "soc_forecast_24h": None,
        "soc_at_forecast_horizon": _round_soc_percent(
            current_kwh,
            data.battery_capacity_kwh,
        ),
    }


def _simulate(
    data: PlannerInput,
    slots: list[ForecastSlot],
    initial_soc: float,
    grid_charge_target_soc: float | None,
    nt_lock_soc: float | None = None,
) -> _Simulation:
    capacity = data.battery_capacity_kwh
    floor_kwh = _soc_to_kwh(_clamp(data.battery_min_soc, 0.0, 100.0), capacity)
    nt_lock_soc_value = nt_lock_soc if nt_lock_soc is not None else data.battery_min_soc
    nt_lock_kwh = _soc_to_kwh(
        _clamp(nt_lock_soc_value, 0.0, 100.0),
        capacity,
    )
    target_kwh = (
        _soc_to_kwh(_clamp(grid_charge_target_soc, 0.0, 100.0), capacity)
        if grid_charge_target_soc is not None
        else None
    )
    battery_kwh = _soc_to_kwh(_clamp(initial_soc, 0.0, 100.0), capacity)
    interval_hours = data.interval_minutes / 60
    grid_charge_limit_kwh = (
        data.grid_charge_max_kw * interval_hours * data.grid_charge_efficiency
    )

    points: list[SocForecastPoint] = []
    vt_grid_import = 0.0
    charged_kwh = 0.0
    unused_surplus = 0.0
    unused_surplus_today = 0.0
    first_full_time: datetime | None = None

    for slot in slots:
        is_nt = _is_in_windows(slot.start, data.nt_windows)
        is_charge = _is_in_window(slot.start, data.charge_window)
        solar_kwh = max(0.0, slot.solar_kwh)
        consumption_kwh = max(0.0, slot.consumption_kwh)
        net_kwh = solar_kwh - consumption_kwh
        grid_import_kwh = 0.0
        grid_charge_kwh = 0.0
        slot_unused_surplus = 0.0

        if net_kwh >= 0:
            storable_kwh = min(net_kwh, capacity - battery_kwh)
            battery_kwh += storable_kwh
            slot_unused_surplus = net_kwh - storable_kwh
        elif is_nt:
            discharge_kwh = min(-net_kwh, max(0.0, battery_kwh - nt_lock_kwh))
            battery_kwh -= discharge_kwh
            grid_import_kwh += -net_kwh - discharge_kwh
        else:
            discharge_kwh = min(-net_kwh, max(0.0, battery_kwh - floor_kwh))
            battery_kwh -= discharge_kwh
            grid_import_kwh += -net_kwh - discharge_kwh
            vt_grid_import += grid_import_kwh

        if is_charge and target_kwh is not None and battery_kwh < target_kwh:
            grid_charge_kwh = min(
                grid_charge_limit_kwh,
                target_kwh - battery_kwh,
                capacity - battery_kwh,
            )
            battery_kwh += grid_charge_kwh
            charged_kwh += grid_charge_kwh

        if battery_kwh >= capacity and first_full_time is None:
            first_full_time = slot.start

        unused_surplus += slot_unused_surplus
        if _is_same_local_date(slot.start, data.now):
            unused_surplus_today += slot_unused_surplus
        points.append(
            SocForecastPoint(
                timestamp=slot.start,
                soc_percent=_round_soc_percent(battery_kwh, capacity),
                battery_kwh=_round(battery_kwh),
                solar_kwh=_round(solar_kwh),
                consumption_kwh=_round(consumption_kwh),
                grid_charge_kwh=_round(grid_charge_kwh),
                grid_import_kwh=_round(grid_import_kwh),
                unused_surplus_kwh=_round(slot_unused_surplus),
                solar_coverage=_round(slot.solar_coverage),
                is_nt=is_nt,
                is_charge_window=is_charge,
            )
        )

    return _Simulation(
        points=points,
        vt_grid_import_kwh=vt_grid_import,
        charged_kwh=charged_kwh,
        unused_surplus_kwh=unused_surplus,
        unused_surplus_today_kwh=unused_surplus_today,
        first_full_time=first_full_time,
    )


def _daily_surplus_forecasts(
    points: list[SocForecastPoint],
    *,
    reference: datetime,
    interval_minutes: int,
) -> list[dict[str, object]]:
    """Summarize surplus and forecast coverage by local calendar day."""
    if not points or interval_minutes <= 0:
        return []

    point_dates = {_local_date(point.timestamp, reference) for point in points}
    summaries: list[dict[str, object]] = []
    for target_date in sorted(point_dates):
        day_points = [
            point
            for point in points
            if _local_date(point.timestamp, reference) == target_date
        ]
        expected_minutes = _minutes_in_local_day(target_date, reference)
        covered_minutes = min(len(day_points) * interval_minutes, expected_minutes)
        solar_covered_minutes = min(
            sum(
                interval_minutes * _clamp(point.solar_coverage, 0.0, 1.0)
                for point in day_points
            ),
            expected_minutes,
        )
        coverage_ratio = covered_minutes / expected_minutes
        solar_coverage_ratio = solar_covered_minutes / expected_minutes
        summaries.append(
            {
                "date": target_date.isoformat(),
                "unused_surplus_kwh": _round(
                    sum(point.unused_surplus_kwh for point in day_points)
                ),
                "coverage_percent": round(coverage_ratio * 100),
                "solar_coverage_percent": round(solar_coverage_ratio * 100),
                "complete": (coverage_ratio >= 0.999 and solar_coverage_ratio >= 0.999),
            }
        )
    return summaries


def _local_date(timestamp: datetime, reference: datetime) -> date:
    if timestamp.tzinfo is not None and reference.tzinfo is not None:
        timestamp = timestamp.astimezone(reference.tzinfo)
    return timestamp.date()


def _minutes_in_local_day(target_date: date, reference: datetime) -> float:
    day_start = datetime.combine(target_date, time.min, tzinfo=reference.tzinfo)
    next_day = datetime.combine(
        target_date + timedelta(days=1),
        time.min,
        tzinfo=reference.tzinfo,
    )
    if reference.tzinfo is None:
        return 24 * 60
    return (next_day.astimezone(UTC) - day_start.astimezone(UTC)).total_seconds() / 60


def _add_elapsed_time(timestamp: datetime, delta: timedelta) -> datetime:
    """Advance an aware timestamp without skipping or duplicating DST time."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp + delta
    return (timestamp.astimezone(UTC) + delta).astimezone(timestamp.tzinfo)


def _timeline_time(timestamp: datetime) -> datetime:
    """Return a comparable absolute timestamp while preserving naive inputs."""
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp
    return timestamp.astimezone(UTC)


def _calculate_charge_to_soc(
    data: PlannerInput,
    slots: list[ForecastSlot],
    floor_soc: float,
    initial_soc: float,
    nt_lock_soc: float,
) -> float:
    low = max(floor_soc, nt_lock_soc)
    no_charge = _simulate(
        data,
        slots,
        initial_soc,
        grid_charge_target_soc=low,
        nt_lock_soc=nt_lock_soc,
    )
    if no_charge.vt_grid_import_kwh <= data.soc_eps_kwh:
        return low

    full_charge = _simulate(
        data,
        slots,
        initial_soc,
        grid_charge_target_soc=100.0,
        nt_lock_soc=nt_lock_soc,
    )
    if full_charge.vt_grid_import_kwh > data.soc_eps_kwh:
        return 100.0

    high = 100.0
    for _ in range(12):
        mid = (low + high) / 2
        simulation = _simulate(
            data,
            slots,
            initial_soc,
            grid_charge_target_soc=mid,
            nt_lock_soc=nt_lock_soc,
        )
        if simulation.vt_grid_import_kwh <= data.soc_eps_kwh:
            high = mid
        else:
            low = mid
    target = _clamp(high + data.soc_reserve_percent, floor_soc, 100.0)
    return 100.0 if target >= 95 else _round(target)


def _calculate_safe_discharge_soc(
    data: PlannerInput,
    slots: list[ForecastSlot],
    floor_soc: float,
    current_soc: float,
    grid_charge_target_soc: float,
    nt_lock_soc: float,
) -> float:
    floor_simulation = _simulate(
        data,
        slots,
        floor_soc,
        grid_charge_target_soc=grid_charge_target_soc,
        nt_lock_soc=nt_lock_soc,
    )
    if floor_simulation.vt_grid_import_kwh <= data.soc_eps_kwh:
        return floor_soc

    low = floor_soc
    high = current_soc
    best = current_soc
    for _ in range(12):
        mid = (low + high) / 2
        simulation = _simulate(
            data,
            slots,
            mid,
            grid_charge_target_soc=grid_charge_target_soc,
            nt_lock_soc=nt_lock_soc,
        )
        if simulation.vt_grid_import_kwh <= data.soc_eps_kwh:
            best = mid
            high = mid
        else:
            low = mid
    return _round(_clamp(best, floor_soc, current_soc))


def _vt_deficit_kwh(
    slots: list[ForecastSlot],
    data: PlannerInput,
    start: datetime,
    end: datetime,
) -> float:
    deficit = 0.0
    peak = 0.0
    for slot in slots:
        if start <= slot.start < end and not _is_in_windows(
            slot.start, data.nt_windows
        ):
            deficit = max(0.0, deficit + slot.consumption_kwh - slot.solar_kwh)
            peak = max(peak, deficit)
    return peak


def _find_sun_start(
    data: PlannerInput,
    slots: list[ForecastSlot],
    start: datetime,
    end: datetime,
) -> datetime | None:
    required_slots = max(
        1, ceil(data.sun_start_required_minutes / data.interval_minutes)
    )
    streak = 0
    streak_start: datetime | None = None
    for slot in slots:
        if slot.start < start or slot.start >= end:
            continue
        if slot.solar_kwh >= slot.consumption_kwh and slot.solar_kwh > 0:
            streak += 1
            streak_start = streak_start or slot.start
            if streak >= required_slots:
                return streak_start
        else:
            streak = 0
            streak_start = None
    return None


def _find_lock_start(data: PlannerInput) -> datetime:
    active_starts = [
        _current_window_start(data.now, window)
        for window in data.nt_windows
        if _is_in_window(data.now, window)
    ]
    if active_starts:
        return max(active_starts)
    if data.nt_windows:
        return min(_next_window_start(data.now, window) for window in data.nt_windows)
    return data.now


def _current_window_start(timestamp: datetime, window: TimeWindow) -> datetime:
    start_minutes = _minutes_since_midnight(window.start)
    end_minutes = _minutes_since_midnight(window.end)
    current_minutes = timestamp.hour * 60 + timestamp.minute
    candidate = _window_start_on_date(timestamp, start_minutes)

    if start_minutes == end_minutes:
        if current_minutes < start_minutes:
            candidate -= timedelta(days=1)
        return candidate

    if start_minutes > end_minutes and current_minutes < end_minutes:
        candidate -= timedelta(days=1)
    return candidate


def _next_window_start(timestamp: datetime, window: TimeWindow) -> datetime:
    start_minutes = _minutes_since_midnight(window.start)
    candidate = _window_start_on_date(timestamp, start_minutes)
    if candidate <= timestamp:
        candidate += timedelta(days=1)
    return candidate


def _window_start_on_date(timestamp: datetime, start_minutes: int) -> datetime:
    candidate = datetime.combine(
        timestamp.date(),
        time(start_minutes // 60, start_minutes % 60),
        tzinfo=timestamp.tzinfo,
    )
    return _normalize_existing_local_time(candidate)


def _normalize_existing_local_time(candidate: datetime) -> datetime:
    if candidate.tzinfo is None:
        return candidate
    return candidate.astimezone(UTC).astimezone(candidate.tzinfo)


def _predict_soc_at(
    *,
    data: PlannerInput,
    slots: list[ForecastSlot],
    start: datetime,
    end: datetime,
    initial_soc: float,
    nt_lock_soc: float,
) -> float:
    if end <= start:
        return initial_soc
    simulation = _simulate(
        data=data,
        slots=_slots_between(slots, start, end),
        initial_soc=initial_soc,
        grid_charge_target_soc=None,
        nt_lock_soc=nt_lock_soc,
    )
    if not simulation.points:
        return initial_soc
    return _round_soc_percent(
        simulation.points[-1].battery_kwh,
        data.battery_capacity_kwh,
    )


def _slots_between(
    slots: list[ForecastSlot],
    start: datetime,
    end: datetime,
) -> list[ForecastSlot]:
    return [slot for slot in slots if start <= slot.start < end]


def _point_at_or_after(
    points: list[SocForecastPoint],
    timestamp: datetime,
) -> SocForecastPoint | None:
    for point in points:
        if point.timestamp >= timestamp:
            return point
    return None


def _point_at_or_project_end(
    points: list[SocForecastPoint],
    timestamp: datetime,
    interval_minutes: int,
) -> SocForecastPoint | None:
    point = _point_at_or_after(points, timestamp)
    if point:
        return point
    if not points:
        return None
    last = points[-1]
    if last.timestamp + timedelta(minutes=interval_minutes) >= timestamp:
        return replace(last, timestamp=timestamp)
    return None


def _is_in_windows(timestamp: datetime, windows: list[TimeWindow]) -> bool:
    return any(_is_in_window(timestamp, window) for window in windows)


def _is_in_window(timestamp: datetime, window: TimeWindow) -> bool:
    start = _minutes_since_midnight(window.start)
    end = _minutes_since_midnight(window.end)
    current = timestamp.hour * 60 + timestamp.minute
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _is_same_local_date(timestamp: datetime, reference: datetime) -> bool:
    if timestamp.tzinfo is not None and reference.tzinfo is not None:
        timestamp = timestamp.astimezone(reference.tzinfo)
    return timestamp.date() == reference.date()


def _minutes_since_midnight(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def _ceil_to_interval(timestamp: datetime, interval_minutes: int) -> datetime:
    clean = timestamp.replace(second=0, microsecond=0)
    minutes = clean.hour * 60 + clean.minute
    remainder = minutes % interval_minutes
    if remainder == 0 and timestamp.second == 0 and timestamp.microsecond == 0:
        return clean
    return clean + timedelta(minutes=interval_minutes - remainder)


def _soc_to_kwh(soc: float, capacity_kwh: float) -> float:
    return _clamp(soc, 0.0, 100.0) / 100 * capacity_kwh


def _kwh_to_soc(kwh: float, capacity_kwh: float) -> float:
    if capacity_kwh <= 0:
        return 0.0
    return _clamp(kwh / capacity_kwh * 100, 0.0, 100.0)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _round(value: float) -> float:
    return round(value, 3)


def _round_soc_percent(kwh: float, capacity_kwh: float) -> int:
    return int(_kwh_to_soc(kwh, capacity_kwh) + 0.5)


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
