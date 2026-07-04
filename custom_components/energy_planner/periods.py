from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime


def infer_period_minutes(
    starts: Sequence[datetime],
    index: int,
    *,
    explicit_period_minutes: int | None = None,
    default_period_minutes: int | None = None,
) -> int | None:
    """Infer a positive period length from neighboring timestamps."""
    if explicit_period_minutes and explicit_period_minutes > 0:
        return explicit_period_minutes

    if index + 1 < len(starts):
        minutes = _delta_minutes(starts[index], starts[index + 1])
        if minutes is not None:
            return minutes

    if index > 0:
        minutes = _delta_minutes(starts[index - 1], starts[index])
        if minutes is not None:
            return minutes

    if default_period_minutes and default_period_minutes > 0:
        return default_period_minutes
    return None


def _delta_minutes(start: datetime, end: datetime) -> int | None:
    minutes = int((end - start).total_seconds() // 60)
    return minutes if minutes > 0 else None
