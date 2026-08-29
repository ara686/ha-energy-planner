"""Pure wallbox mode recommendation helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WallboxModeOptions:
    """Configured external wallbox selector options."""

    solar: str
    home_battery: str
    grid: str
    off: str

    @property
    def values(self) -> tuple[str, ...]:
        """Return distinct configured options in stable order."""
        return tuple(
            dict.fromkeys((self.solar, self.home_battery, self.grid, self.off))
        )


def recommended_wallbox_mode(
    planner_mode: object,
    options: WallboxModeOptions,
) -> str:
    """Map one planner mode to the configured advisory wallbox option."""
    if planner_mode == "solar":
        return options.solar
    if planner_mode == "home_battery":
        return options.home_battery
    if planner_mode in {"grid_low_tariff", "grid_high_tariff"}:
        return options.grid
    return options.off


def wallbox_charging_source(
    option: object,
    options: WallboxModeOptions,
) -> str | None:
    """Map a current external wallbox option back to its energy source."""
    if option == options.solar:
        return "solar"
    if option == options.home_battery:
        return "home_battery"
    if option == options.grid:
        return "grid"
    return None
