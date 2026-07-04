# Energy Planner Specification

## Integration domain

```text
energy_planner
```

## Repository name

```text
ha-energy-planner
```

## Purpose

Create a Home Assistant custom integration that calculates battery and energy
planning outputs from Home Assistant entities.

The integration calculates energy planning entities. It does not directly control any device in v1.

The integration must include a battery SoC prediction for at least the next 24 hours.
The prediction may cover a longer configurable horizon when enough Home Assistant data is available.

## Inputs

Default entity IDs:

```yaml
battery_soc_entity: sensor.cerbo_gx_victron_battery_soc
battery_capacity_entity: sensor.cerbo_gx_victron_installed_battery_capacity
battery_min_soc_entity: number.cerbo_gx_victron_battery_minimum_soc_limit

home_energy_entity: sensor.home_energy_total
managed_energy_entities:
  - sensor.ev_energy_total
  - sensor.water_heater_energy_total

solcast_today_entity: sensor.solcast_pv_forecast_forecast_today
solcast_tomorrow_entity: sensor.solcast_pv_forecast_forecast_tomorrow
solcast_additional_entities:
  - sensor.solcast_pv_forecast_forecast_day_3
  - sensor.solcast_pv_forecast_forecast_day_4
```

Assumptions:

- All input data is read from configured Home Assistant entities, states and attributes.
- The integration must not call Solcast, Victron, tariff provider or device APIs directly in v1.
- `home_energy_entity` is a cumulative whole-home energy source in kWh.
- `managed_energy_entities` is an optional list of cumulative managed-load energy sources in kWh.
- The consumption model reads the configured number of Home Assistant history days for those energy sources when available.
- History records are converted to positive cumulative deltas and assigned to the hour of the newer reading.
- Managed energy deltas from all managed sources are summed per hour.
- Managed consumption is subtracted from home consumption per hour before the hourly profile is calculated.
- Future consumption uses the average for the same hour of day. A forecast slot at 11:00 uses historical 11:00 values, not a global average.
- The hourly profile includes a built-in 5% history margin and then applies `history_correction_percent`.
- If Home Assistant history is unavailable, the integration uses its own stored hourly history as a fallback.
- Solcast PV forecast data is read from the configured Solcast Home Assistant forecast entities.
- When the configured Solcast today entity uses the standard `_forecast_today` suffix, the integration may auto-detect existing standard sibling entities for tomorrow and day 3 through day 7.
- Auto-detection only discovers existing Home Assistant entities; it must not synthesize, extrapolate or call Solcast for missing future days.
- Battery capacity is kWh.
- Battery SoC is percent.
- Integration should build and maintain its own internal history.

## Configuration

Use Config Flow.

Required:
- planner instance name
- battery SoC entity
- battery capacity entity
- battery minimum SoC entity
- home hourly consumption history source entity

Optional:
- managed hourly consumption history source entity
- Solcast today entity
- Solcast tomorrow entity
- additional Solcast forecast day entities
- price entity

## Options

Use Options Flow.

Options:

```yaml
history_retention_days: 30
history_learning_days: 3
update_interval_minutes: 60
interval_minutes: 5
history_correction_percent: 5
min_baseline_kwh_per_hour: 0.2
grid_charge_max_kw: 5.5
grid_charge_efficiency: 0.92
soc_reserve_percent: 1
soc_eps_kwh: 0.02
nt_windows:
  - start: "17:00"
    end: "19:00"
  - start: "22:00"
    end: "04:00"
charge_window:
  start: "22:00"
  end: "04:00"
sun_start_required_minutes: 30
forecast_horizon_hours: 36
enable_grid_charge_planning: true
enable_surplus_calculation: true
enable_ev_free_capacity_calculation: true
forecast_detail_level: compact
```

Validate:
- `update_interval_minutes` must be greater than 0.
- `history_learning_days` must be greater than 0.
- `interval_minutes` must divide 60.
- `forecast_horizon_hours` must be at least 24.
- windows must be valid HH:MM.
- numeric values must be inside safe ranges.

## SoC forecast

The planner must simulate battery SoC over the forecast horizon.

Requirements:
- include at least the next 24 hours
- support a longer configurable horizon through `forecast_horizon_hours`
- use Solcast forecast data from Home Assistant entities as PV input
- use the hourly history profile as load input
- use current battery SoC, capacity and minimum SoC from Home Assistant entities
- respect NT/VT windows, grid charge window and physical battery floor
- expose a compact time series with timestamp, predicted SoC percent and predicted battery kWh
- include the predicted SoC at +24 hours even when the configured horizon is longer
- produce warnings instead of crashing when optional forecast data is missing
- return `insufficient_data` when required HA input entities are missing or invalid

## Output sensors

Create:

```yaml
sensor.energy_planner_state
sensor.energy_planner_lock_soc
sensor.energy_planner_charge_to_soc
sensor.energy_planner_target_soc
sensor.energy_planner_safe_discharge_soc
sensor.energy_planner_free_capacity_soc
sensor.energy_planner_free_capacity_kwh
sensor.energy_planner_unused_surplus_today_kwh
sensor.energy_planner_unused_surplus_total_kwh
sensor.energy_planner_first_full_time
sensor.energy_planner_vt_grid_import_kwh_at_target
sensor.energy_planner_charged_kwh_total_at_target
sensor.energy_planner_soc_at_planner_start
sensor.energy_planner_soc_at_lock_start
sensor.energy_planner_soc_forecast
sensor.energy_planner_soc_forecast_24h
sensor.energy_planner_sun_start
sensor.energy_planner_lock_start
sensor.energy_planner_updated
sensor.energy_planner_history_status
sensor.energy_planner_recalculation_interval
sensor.energy_planner_consumption_history_days
sensor.energy_planner_planning_interval
sensor.energy_planner_history_correction
sensor.energy_planner_minimum_baseline_consumption
sensor.energy_planner_maximum_grid_charging_power
sensor.energy_planner_grid_charging_efficiency
sensor.energy_planner_soc_reserve
sensor.energy_planner_soc_tolerance
sensor.energy_planner_low_tariff_windows
sensor.energy_planner_charging_window
sensor.energy_planner_minimum_solar_start_duration
sensor.energy_planner_forecast_horizon
```

Main state sensor:

```yaml
sensor.energy_planner_state:
  state: ok | warning | error | insufficient_data
  attributes:
    warnings: []
    slot_count: 0
    history_status: unknown
```

Large plan, forecast and debug payloads belong in diagnostics, the
`energy_planner.export_debug` service event or dedicated forecast sensors, not in
regular state attributes.

SoC forecast sensors:

```yaml
sensor.energy_planner_soc_forecast:
  state: predicted SoC at the configured forecast horizon
  attributes:
    horizon_hours: 36
    source: ha_entities
    points: []

sensor.energy_planner_soc_forecast_24h:
  state: predicted SoC at now + 24 hours
  attributes:
    source: ha_entities
    point: {}
```

## Services

```yaml
energy_planner.recalculate
energy_planner.export_debug
```

No control services in v1.

## Internal history

Use Home Assistant storage helpers.

Requirements:
- hourly buckets
- retention cleanup
- restart persistence
- managed energy subtraction
- history availability status
- no required dependency on recorder internals
