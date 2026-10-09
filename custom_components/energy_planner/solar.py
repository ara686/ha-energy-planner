"""Shared admission rules for forecast solar-powered managed loads."""

from math import isfinite


def valid_solar_minimum_soc(value: float | None) -> bool:
    """Validate a per-load battery threshold without silently weakening it."""
    return value is not None and isfinite(value) and 0 <= value <= 100


def solar_block_reason(
    *,
    soc_percent: float | None,
    minimum_soc_percent: float,
    available_power_kw: float,
    minimum_power_kw: float,
) -> str | None:
    """Require starting SoC and enough instantaneous surplus to run a load."""
    if minimum_soc_percent > 0 and (
        soc_percent is None or soc_percent + 1e-9 < minimum_soc_percent
    ):
        return "waiting_for_minimum_soc"
    if available_power_kw + 1e-9 < minimum_power_kw:
        return "insufficient_solar_power"
    return None
