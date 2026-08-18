"""Pure managed-load forecast scheduling helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from .models import ForecastSlot


@dataclass(frozen=True)
class ManagedDemandSchedule:
    """Managed energy distributed into forecast slots."""

    energy_by_slot: dict[datetime, float]
    expected_kwh: float
    scheduled_kwh: float
    scheduled_by_source: dict[str, float]
    fallback_source_ids: list[str]


def build_managed_demand_schedule(
    *,
    slots: list[ForecastSlot],
    target_date: date,
    reference: datetime,
    interval_minutes: int,
    expected_by_source: Mapping[str, float],
    hourly_profiles: Mapping[str, Mapping[int, float]],
) -> ManagedDemandSchedule:
    """Distribute expected daily managed energy using historical hourly shape."""
    target_slots = [
        slot
        for slot in slots
        if _local_timestamp(slot.start, reference).date() == target_date
    ]
    day_hours = _day_slot_hours(
        target_date=target_date,
        reference=reference,
        interval_minutes=interval_minutes,
    )
    energy_by_slot: dict[datetime, float] = {}
    scheduled_by_source: dict[str, float] = {}
    fallback_source_ids: list[str] = []

    if not day_hours:
        return ManagedDemandSchedule(
            energy_by_slot={},
            expected_kwh=round(
                sum(max(float(value), 0.0) for value in expected_by_source.values()),
                6,
            ),
            scheduled_kwh=0.0,
            scheduled_by_source={source_id: 0.0 for source_id in expected_by_source},
            fallback_source_ids=sorted(
                source_id
                for source_id, value in expected_by_source.items()
                if float(value) > 0
            ),
        )

    for source_id, raw_expected_kwh in expected_by_source.items():
        expected_kwh = max(float(raw_expected_kwh), 0.0)
        if expected_kwh <= 0:
            scheduled_by_source[source_id] = 0.0
            continue

        profile = {
            hour: max(float(value), 0.0)
            for hour, value in hourly_profiles.get(source_id, {}).items()
            if 0 <= hour <= 23 and float(value) > 0
        }
        denominator = sum(profile.get(hour, 0.0) for hour in day_hours)
        if denominator <= 0:
            fallback_source_ids.append(source_id)
            denominator = float(len(day_hours))

        scheduled = 0.0
        for slot in target_slots:
            hour = _local_timestamp(slot.start, reference).hour
            weight = profile.get(hour, 0.0) if profile else 1.0
            slot_kwh = expected_kwh * weight / denominator
            if slot_kwh <= 0:
                continue
            slot_key = _timeline_time(slot.start)
            energy_by_slot[slot_key] = energy_by_slot.get(slot_key, 0.0) + slot_kwh
            scheduled += slot_kwh
        scheduled_by_source[source_id] = round(scheduled, 6)

    return ManagedDemandSchedule(
        energy_by_slot=energy_by_slot,
        expected_kwh=round(
            sum(max(float(value), 0.0) for value in expected_by_source.values()),
            6,
        ),
        scheduled_kwh=round(sum(energy_by_slot.values()), 6),
        scheduled_by_source=scheduled_by_source,
        fallback_source_ids=sorted(fallback_source_ids),
    )


def _day_slot_hours(
    *,
    target_date: date,
    reference: datetime,
    interval_minutes: int,
) -> list[int]:
    if interval_minutes <= 0:
        return []
    start = datetime.combine(target_date, time.min, tzinfo=reference.tzinfo)
    end = datetime.combine(
        target_date + timedelta(days=1),
        time.min,
        tzinfo=reference.tzinfo,
    )
    hours: list[int] = []
    cursor = start
    while _timeline_time(cursor) < _timeline_time(end):
        hours.append(cursor.hour)
        cursor = _add_elapsed_time(cursor, timedelta(minutes=interval_minutes))
    return hours


def _local_timestamp(timestamp: datetime, reference: datetime) -> datetime:
    if timestamp.tzinfo is not None and reference.tzinfo is not None:
        return timestamp.astimezone(reference.tzinfo)
    return timestamp


def _add_elapsed_time(timestamp: datetime, delta: timedelta) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp + delta
    return (timestamp.astimezone(UTC) + delta).astimezone(timestamp.tzinfo)


def _timeline_time(timestamp: datetime) -> datetime:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp
    return timestamp.astimezone(UTC)
