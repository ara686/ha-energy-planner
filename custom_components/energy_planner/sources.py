from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import SolarForecastPoint
from .periods import infer_period_minutes

UNAVAILABLE_STATES = {"", "unknown", "unavailable", "none", "null"}


def parse_float(value: Any) -> float | None:
    """Parse a Home Assistant state-like value into a float."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in UNAVAILABLE_STATES:
        return None
    try:
        return float(normalized.replace(",", "."))
    except ValueError:
        return None


def parse_solcast_attributes(
    attributes: Mapping[str, Any] | None,
) -> list[SolarForecastPoint]:
    """Parse Solcast forecast attributes exposed by Home Assistant."""
    if not attributes:
        return []

    entries = _forecast_entries(attributes)
    raw_points: list[_RawSolarForecastPoint] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        start = _parse_datetime(
            entry.get("period_start")
            or entry.get("periodStart")
            or entry.get("datetime")
            or entry.get("start")
            or entry.get("time")
        )
        solar_value = _parse_solar_value(entry)
        if start is None or solar_value is None:
            continue
        raw_points.append(
            _RawSolarForecastPoint(
                start=start,
                value=max(0.0, solar_value.value),
                unit=solar_value.unit,
                period_minutes=_parse_period_minutes(entry),
            ),
        )

    sorted_points = sorted(raw_points, key=lambda item: item.start)
    points: list[SolarForecastPoint] = []
    for index, point in enumerate(sorted_points):
        period_minutes = _period_minutes(sorted_points, index)
        points.append(
            SolarForecastPoint(
                start=point.start,
                solar_kwh=_solar_value_to_kwh(point, period_minutes=period_minutes),
                period_minutes=period_minutes,
            )
        )
    return points


@dataclass(frozen=True)
class _SolarValue:
    value: float
    unit: str


@dataclass(frozen=True)
class _RawSolarForecastPoint:
    start: datetime
    value: float
    unit: str
    period_minutes: int | None


def _forecast_entries(attributes: Mapping[str, Any]) -> list[Any]:
    for key in (
        "detailedForecast",
        "detailed_forecast",
        "forecast",
        "forecasts",
    ):
        value = attributes.get(key)
        if isinstance(value, list):
            return value
    return []


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _parse_solar_value(entry: Mapping[str, Any]) -> _SolarValue | None:
    for key in (
        "solar_kwh",
        "kwh",
        "energy",
    ):
        value = parse_float(entry.get(key))
        if value is not None:
            return _SolarValue(value=value, unit="kwh")

    wh_value = parse_float(entry.get("wh") or entry.get("pv_estimate_wh"))
    if wh_value is not None:
        return _SolarValue(value=wh_value / 1000, unit="kwh")

    for key in (
        "pv_estimate",
        "pvEstimate",
        "estimate",
    ):
        value = parse_float(entry.get(key))
        if value is not None:
            return _SolarValue(value=value, unit="kw")
    return None


def _period_minutes(points: list[_RawSolarForecastPoint], index: int) -> int | None:
    point = points[index]
    return infer_period_minutes(
        [item.start for item in points],
        index,
        explicit_period_minutes=point.period_minutes,
    )


def _solar_value_to_kwh(
    point: _RawSolarForecastPoint,
    period_minutes: int | None,
) -> float:
    if point.unit == "kwh":
        return point.value
    return point.value * (period_minutes or 30) / 60


def _parse_period_minutes(entry: Mapping[str, Any]) -> int | None:
    value = parse_float(
        entry.get("period_minutes")
        or entry.get("periodMinutes")
        or entry.get("duration_minutes")
        or entry.get("durationMinutes")
    )
    if value is None or value <= 0:
        return None
    return int(value)
