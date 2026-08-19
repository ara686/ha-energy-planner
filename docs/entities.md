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
| `binary_sensor.energy_planner_charge_now` | `charge_now` | Standard | binary | On when enabled grid-charging planning finds current planner-start SoC below `charge_to_soc`. It remains off when grid-charging planning is disabled. |
| `binary_sensor.energy_planner_discharge_allowed` | `discharge_allowed` | Standard | binary | On when current planner-start SoC is above `safe_discharge_soc`. Use it to allow battery discharge without comparing SoC values in automations. |
| `sensor.energy_planner_lock_soc` | `lock_soc` | Standard | `%` | Minimum SoC the planner wants to protect for the low/high tariff planning window. |
| `sensor.energy_planner_charge_to_soc` | `charge_to_soc` | Standard | `%` | Optional grid-charge target SoC needed to cover the forecasted high-tariff deficit from the configured charging window. When grid-charging planning is disabled, it remains at planner-start SoC. |
| `sensor.energy_planner_target_soc` | `target_soc` | Standard | `%` | Final target SoC used by the planner; currently the higher value of `lock_soc` and `charge_to_soc`. |
| `sensor.energy_planner_safe_discharge_soc` | `safe_discharge_soc` | Standard | `%` | Lowest SoC the planner considers safe to discharge to while still preserving the future plan. |
| `sensor.energy_planner_free_capacity_soc` | `free_capacity_soc` | Standard | `%` | Current SoC above `safe_discharge_soc`, expressed as battery percentage. |
| `sensor.energy_planner_free_capacity` | `free_capacity_kwh` | Standard | `kWh` | Current energy above `safe_discharge_soc`, expressed as battery capacity. |
| `sensor.energy_planner_unused_surplus_today` | `unused_surplus_today_kwh` | Standard | `kWh` | Passive forecasted PV surplus for today that cannot be stored in the battery. |
| `sensor.energy_planner_unused_surplus_total` | `unused_surplus_total_kwh` | Standard | `kWh` | Passive forecasted PV surplus across the configured forecast horizon that cannot be stored in the battery. |
| `sensor.energy_planner_unused_surplus_tomorrow` | `unused_surplus_tomorrow_kwh` | Standard | `kWh` | Passive surplus for the complete next local calendar day. Unavailable if time-slot or solar coverage is incomplete; coverage percentages are attributes. |
| `sensor.energy_planner_recommended_managed_energy_today` | `managed_recommended_today_kwh` | Standard | `kWh` | Combined EV charger-input recommendation from the next complete planner slot to local midnight. Unavailable if this remaining period lacks complete slot or solar coverage; zero when no slot remains. Attribute `managed_allocation_by_day` is unrecorded and contains compact today and future allocations. |
| `sensor.energy_planner_expected_managed_demand_tomorrow` | `managed_expected_demand_tomorrow_kwh` | Standard | `kWh` | Combined generic historical/requested demand, hot-water minimum need and EV remainder after today's planned allocation, before tomorrow's surplus limiting. |
| `sensor.energy_planner_recommended_managed_energy_tomorrow` | `managed_recommended_tomorrow_kwh` | Standard | `kWh` | Combined managed-load recommendation after the four allocation phases. Attribute `managed_allocation_by_day` contains compact per-day and per-source values for today and complete future days. |
| `sensor.energy_planner_unallocated_surplus_tomorrow` | `unallocated_surplus_tomorrow_kwh` | Standard | `kWh` | Complete tomorrow surplus left after all managed-load recommendations. |
| `sensor.energy_planner_first_full_time` | `first_full_time` | Standard | timestamp | First passive forecasted time when the battery reaches full SoC. |
| `sensor.energy_planner_high_tariff_grid_import_at_target` | `vt_grid_import_kwh_at_target` | Standard | `kWh` | Forecasted high-tariff grid import remaining in the simulation when charging to `target_soc`. |
| `sensor.energy_planner_charged_total_at_target` | `charged_kwh_total_at_target` | Standard | `kWh` | Total grid energy the simulation charges into the battery to reach `target_soc`. |
| `sensor.energy_planner_soc_at_planner_start` | `soc_at_planner_start` | Diagnostic | `%` | Predicted SoC at the start of the planning window. |
| `sensor.energy_planner_soc_at_lock_start` | `soc_at_lock_start` | Diagnostic | `%` | Predicted SoC at the start of the lock/protection window. |
| `sensor.energy_planner_soc_forecast` | `soc_forecast` | Standard | `%` | State is passive predicted SoC at the configured forecast horizon. Attributes include `horizon_hours`, `source` and a recorder-safe future `points` array for graph cards. |
| `sensor.energy_planner_soc_forecast_with_managed_loads` | `soc_forecast_with_managed` | Standard | `%` | State is passive predicted SoC at the configured horizon with tomorrow's generic demand and actually allocated hot-water and EV slots added to consumption. Attributes include compact graph points, `managed_allocation_by_day` and scheduled-demand details. |
| `sensor.energy_planner_soc_forecast_24h` | `soc_forecast_24h` | Standard | `%` | Passive predicted SoC exactly 24 hours from the calculation time. Attribute `point` contains the full forecast point. |
| `sensor.energy_planner_solar_start` | `sun_start` | Diagnostic | timestamp | Start of the next usable solar production period detected from forecast slots. |
| `sensor.energy_planner_lock_start` | `lock_start` | Diagnostic | timestamp | Start of the period where the calculated lock SoC is relevant. |
| `sensor.energy_planner_updated` | `updated` | Diagnostic | timestamp | Time of the last successful coordinator calculation. |
| `sensor.energy_planner_history_status` | `history_status` | Diagnostic, disabled by default | text | Compact status for the consumption history source and coverage used by the planner. Full details are also available in integration diagnostics. |
| `sensor.energy_planner_consumption_history` | `consumption_history` | Diagnostic | `kWh` | Latest usable hourly base consumption bucket used by the planner. Attributes include compact hourly `points` with `home_kwh`, `managed_kwh`, `base_kwh` and `base_usable` values for graph cards. |

The two horizon forecast sensors use Home Assistant's `battery` device class.
The other SoC outputs are planning setpoints, limits or future helper values, so
they remain plain percentage sensors.

Forecast `soc_percent` values are rounded to whole integer percentages because
most PV and battery systems do not provide meaningful decimal SoC precision.

`soc_forecast`, `soc_forecast_24h`, `unused_surplus_today_kwh`,
`unused_surplus_total_kwh` and `first_full_time` are passive forecasts from the
current battery SoC, consumption history and PV forecast. They do not assume
Energy Planner automations have already charged the battery or prevented
discharge. Plan-specific simulations are exposed separately by
`vt_grid_import_kwh_at_target` and `charged_kwh_total_at_target`.

`soc_forecast_with_managed` starts from the same passive simulation. For
`generic` loads, it adds tomorrow's full historical or requested demand using
the historical hourly shape; a load without a usable shape is spread evenly.
For `hot_water`, it adds only energy actually allocated to surplus slots for
each complete future day. For `electric_vehicle`, it adds only actual allocated
solar slots today and on subsequent complete days while carrying the unmet
remainder. Its compact `points` include
`managed_consumption_kwh` where managed demand is scheduled.

## Managed Source Entities

For every configured `Managed energy source`, Energy Planner also creates a
small group of per-source entities. The final entity IDs depend on the selected
source entity name. For example, a source with friendly name `EV charging energy`
typically creates entity IDs like
`sensor.energy_planner_managed_ev_charging_energy_today`.

| Typical entity pattern | Category | Unit/type | Description |
|------------------------|----------|-----------|-------------|
| `sensor.energy_planner_managed_<source>_suggested_today` | Standard | `kWh` | Recommended charger electrical input for an `electric_vehicle` today. Unavailable for non-EV loads and when remaining-today solar coverage is incomplete. |
| `sensor.energy_planner_managed_<source>_suggested_tomorrow` | Standard | `kWh` | Recommended energy for this load tomorrow. Common attributes include type, priority, state, method, expected demand and reason. Generic loads add history/request details; hot-water loads add thermal-model values; EV loads add request, power, efficiency and shortfalls. |
| `sensor.energy_planner_managed_<source>_charging_mode` | Standard | enum | Current deadline-aware EV instruction: `off`, `connect_vehicle`, `wait_for_solar`, `solar`, `home_battery`, `grid_low_tariff`, `grid_high_tariff`, `complete`, `shortfall` or `unavailable`. |
| `sensor.energy_planner_managed_<source>_next_departure` | Standard | timestamp | Next local workday departure used as the charging deadline. |
| `sensor.energy_planner_managed_<source>_planned_until_departure` | Standard | `kWh` | Charger-input energy assigned before departure. Attributes contain the source split, shortfall, next action, reason, return time, solar-if-home counterfactual and compact timeline. |
| `sensor.energy_planner_managed_<source>_today` | Standard | `kWh` | Energy used by this managed load today. Uses `device_class: energy` and `state_class: total_increasing`. |
| `sensor.energy_planner_managed_<source>_current_hour` | Standard | `kWh` | Energy used by this managed load in the current hour bucket. Useful for live dashboards and automation conditions. |
| `sensor.energy_planner_managed_<source>_last_hour` | Standard | `kWh` | Energy used by this managed load in the previous completed hour bucket. Useful for hourly charts and decisions that should not use an incomplete current hour. |
| `sensor.energy_planner_managed_<source>_tracked_total` | Standard | `kWh` | Monotonic total tracked by Energy Planner from positive deltas observed after setup. Uses `device_class: energy` and `state_class: total_increasing`. |
| `sensor.energy_planner_managed_<source>_history` | Diagnostic, disabled by default | `kWh` | Detail entity for graph cards. Its `points` attribute contains hourly `managed_kwh` values for this one source. Enable it only when you want per-source history graphs. |

Each per-source entity includes these attributes:

- `source_entity_id`: original managed source entity selected in setup.
- `source_name`: source friendly name used when the entity was created.
- `history_source`: whether hourly values came from Home Assistant long-term
  statistics, raw recorder history or Energy Planner's stored fallback history.
- `today_kwh`, `current_hour_kwh`, `last_hour_kwh`: compact summary values.
- `point_count`, `point_limit`, `truncated`: history payload status.
- `tracked_total_kwh`: Energy Planner's monotonic tracked total for the source.

The `history` entity additionally exposes a `points` attribute with compact
hourly data. Other per-source entities intentionally do not expose `points`, so
regular state history stays compact.

The suggested-tomorrow entity has allocation attributes instead of hourly
history attributes. For `generic`, `method` is `history`, `requested` or
`insufficient_data`; `confidence` describes the historical estimate and is not
a guarantee about PV production or device behavior. For `hot_water`, `method`
is `thermal_model` and the attributes include `average_temperature`,
`minimum_required_kwh`, `flexible_capacity_kwh`, `minimum_shortfall_kwh` and
`recommended_kwh`. An unavailable temperature sensor makes only this suggested
entity unavailable; historical per-source sensors remain available.

The suggested-today entity is available only for `electric_vehicle`. Its
`method` is `ev_request`; attributes include `battery_required_kwh`,
`electrical_required_kwh`, `electrical_remaining_before_kwh`,
`electrical_shortfall_kwh`, `battery_shortfall_kwh`, `charging_efficiency`,
`maximum_charging_power_kw` and `recommended_kwh`. Recommended values are
charger input, while `battery_*` values are on the vehicle-battery side. Invalid
EV inputs make only that EV recommendation unavailable and never trigger a
history fallback.

The three deadline-aware entities use stable unique IDs. The
`planned_until_departure` attributes include `solar_kwh`, `home_battery_kwh`,
`grid_low_tariff_kwh`, `grid_high_tariff_kwh`, `shortfall_kwh`,
`solar_if_home_kwh`, `solar_if_home_covers_request`, `forecast_complete`,
`reason`, `next_action_start`, `next_action_end` and `timeline`. The timeline is
marked unrecorded so the future plan is not written into regular recorder
history.

The multi-day allocation payload is deliberately compact and marked as
unrecorded together with forecast `points`, so these larger prediction
attributes are not written into Home Assistant's recorder history.

The main `sensor.energy_planner_consumption_history` entity shows total home,
total managed and calculated base consumption. It does not include per-source
managed breakdown in each point; use the per-source `history` entities for that.
