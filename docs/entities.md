# Entities

Energy Planner creates sensor and binary sensor entities only. It does not
create switches, numbers, selects or any device-control entities in v1.

Entity IDs below are the typical defaults for an integration instance named
`Energy Planner`. Home Assistant may add suffixes or use renamed entity IDs.
Check the actual IDs in **Settings > Devices & services > Energy Planner >
Entities**.

## Output Entities

| Typical entity ID | Output key | Category | Unit/type | Description |
|-------------------|------------|----------|-----------|-------------|
| `sensor.energy_planner_state` | `state` | Diagnostic | text | Planner state: `ok`, `warning` or `insufficient_data`. Attributes include warnings, slot count and compact history status. |
| `binary_sensor.energy_planner_charge_now` | `charge_now` | Standard | binary | On when current planner-start SoC is below `charge_to_soc`. Use it to start or allow grid charging without comparing SoC values in automations. |
| `binary_sensor.energy_planner_discharge_allowed` | `discharge_allowed` | Standard | binary | On when current planner-start SoC is above `safe_discharge_soc`. Use it to allow battery discharge without comparing SoC values in automations. |
| `sensor.energy_planner_lock_soc` | `lock_soc` | Standard | `%` | Minimum SoC the planner wants to protect for the low/high tariff planning window. |
| `sensor.energy_planner_charge_to_soc` | `charge_to_soc` | Standard | `%` | Optional grid-charge target SoC needed to cover the forecasted high-tariff deficit from the configured charge window. |
| `sensor.energy_planner_target_soc` | `target_soc` | Standard | `%` | Final target SoC used by the planner; currently the higher value of `lock_soc` and `charge_to_soc`. |
| `sensor.energy_planner_safe_discharge_soc` | `safe_discharge_soc` | Standard | `%` | Lowest SoC the planner considers safe to discharge to while still preserving the future plan. |
| `sensor.energy_planner_free_capacity_soc` | `free_capacity_soc` | Standard | `%` | Current SoC above `safe_discharge_soc`, expressed as battery percentage. |
| `sensor.energy_planner_free_capacity` | `free_capacity_kwh` | Standard | `kWh` | Current energy above `safe_discharge_soc`, expressed as battery capacity. |
| `sensor.energy_planner_unused_surplus_today` | `unused_surplus_today_kwh` | Standard | `kWh` | Passive forecasted PV surplus for today that cannot be stored in the battery. |
| `sensor.energy_planner_unused_surplus_total` | `unused_surplus_total_kwh` | Standard | `kWh` | Passive forecasted PV surplus across the configured forecast horizon that cannot be stored in the battery. |
| `sensor.energy_planner_first_full_time` | `first_full_time` | Standard | timestamp | First passive forecasted time when the battery reaches full SoC. |
| `sensor.energy_planner_high_tariff_grid_import_at_target` | `vt_grid_import_kwh_at_target` | Standard | `kWh` | Forecasted high-tariff grid import remaining in the simulation when charging to `target_soc`. |
| `sensor.energy_planner_charged_total_at_target` | `charged_kwh_total_at_target` | Standard | `kWh` | Total grid energy the simulation charges into the battery to reach `target_soc`. |
| `sensor.energy_planner_soc_at_planner_start` | `soc_at_planner_start` | Diagnostic | `%` | Predicted SoC at the start of the planning window. |
| `sensor.energy_planner_soc_at_lock_start` | `soc_at_lock_start` | Diagnostic | `%` | Predicted SoC at the start of the lock/protection window. |
| `sensor.energy_planner_soc_forecast` | `soc_forecast` | Standard | `%` | State is passive predicted SoC at the configured forecast horizon. Attributes include `horizon_hours`, `source` and the compact future `points` array for graph cards. |
| `sensor.energy_planner_soc_forecast_24h` | `soc_forecast_24h` | Standard | `%` | Passive predicted SoC exactly 24 hours from the calculation time. Attribute `point` contains the full forecast point. |
| `sensor.energy_planner_solar_start` | `sun_start` | Diagnostic | timestamp | Start of the next usable solar production period detected from forecast slots. |
| `sensor.energy_planner_lock_start` | `lock_start` | Diagnostic | timestamp | Start of the period where the calculated lock SoC is relevant. |
| `sensor.energy_planner_updated` | `updated` | Diagnostic | timestamp | Time of the last successful coordinator calculation. |
| `sensor.energy_planner_history_status` | `history_status` | Diagnostic, disabled by default | text | Compact status for the consumption history source and coverage used by the planner. Full details are also available in integration diagnostics. |
| `sensor.energy_planner_consumption_history` | `consumption_history` | Diagnostic | `kWh` | Latest usable hourly base consumption bucket used by the planner. Attributes include compact hourly `points` with `home_kwh`, `managed_kwh`, per-source `managed_sources`, `base_kwh` and `base_usable` values for graph cards. |

Only `sensor.energy_planner_soc_forecast` uses Home Assistant's `battery`
device class. The other SoC outputs are planning setpoints, limits or future
helper values, so they remain plain percentage sensors.

Forecast `soc_percent` values are rounded to whole integer percentages because
most PV and battery systems do not provide meaningful decimal SoC precision.

`soc_forecast`, `soc_forecast_24h`, `unused_surplus_today_kwh`,
`unused_surplus_total_kwh` and `first_full_time` are passive forecasts from the
current battery SoC, consumption history and PV forecast. They do not assume
Energy Planner automations have already charged the battery or prevented
discharge. Plan-specific simulations are exposed separately by
`vt_grid_import_kwh_at_target` and `charged_kwh_total_at_target`.

## Managed Source Entities

For every configured `Managed energy source`, Energy Planner also creates a
small group of per-source entities. The final entity IDs depend on the selected
source entity name. For example, a source with friendly name `EV charging energy`
typically creates entity IDs like
`sensor.energy_planner_managed_ev_charging_energy_today`.

| Typical entity pattern | Category | Unit/type | Description |
|------------------------|----------|-----------|-------------|
| `sensor.energy_planner_managed_<source>_today` | Standard | `kWh` | Energy used by this managed load today. Uses Home Assistant long-term statistics with `device_class: energy` and `state_class: total_increasing`. |
| `sensor.energy_planner_managed_<source>_current_hour` | Standard | `kWh` | Energy used by this managed load in the current hour bucket. Useful for live dashboards and automation conditions. |
| `sensor.energy_planner_managed_<source>_last_hour` | Standard | `kWh` | Energy used by this managed load in the previous completed hour bucket. Useful for hourly charts and decisions that should not use an incomplete current hour. |
| `sensor.energy_planner_managed_<source>_tracked_total` | Standard | `kWh` | Monotonic total tracked by Energy Planner from positive deltas observed after setup. Uses `device_class: energy` and `state_class: total_increasing`. |
| `sensor.energy_planner_managed_<source>_history` | Diagnostic, disabled by default | `kWh` | Detail entity for graph cards. Its `points` attribute contains hourly `managed_kwh` values for this one source. Enable it only when you want per-source history graphs. |

Each per-source entity includes these attributes:

- `source_entity_id`: original managed source entity selected in setup.
- `source_name`: source friendly name used when the entity was created.
- `history_source`: whether the hourly values came from Home Assistant recorder
  history or Energy Planner's stored fallback history.
- `today_kwh`, `current_hour_kwh`, `last_hour_kwh`: compact summary values.
- `point_count`, `point_limit`, `truncated`: history payload status.
- `tracked_total_kwh`: Energy Planner's monotonic tracked total for the source.

The `history` entity additionally exposes a `points` attribute with compact
hourly data. Other per-source entities intentionally do not expose `points`, so
regular state history stays compact.
