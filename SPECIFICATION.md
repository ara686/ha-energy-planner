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

Create a Home Assistant custom integration that replaces a Node-RED based energy prediction flow.

The integration calculates energy planning entities. It does not directly control any device in v1.

The integration must include a battery SoC prediction for at least the next 24 hours.
The prediction may cover a longer configurable horizon when enough Home Assistant data is available.

## Inputs

Default entity IDs:

```yaml
battery_soc_entity: sensor.cerbo_gx_victron_battery_soc
battery_capacity_entity: sensor.cerbo_gx_victron_installed_battery_capacity
battery_min_soc_entity: number.cerbo_gx_victron_battery_minimum_soc_limit

home_energy_hourly_entity: sensor.home_power_hourly_utility_meter
managed_energy_hourly_entity: sensor.managed_power_utility_meter_hourly

solcast_today_entity: sensor.solcast_pv_forecast_forecast_today
solcast_tomorrow_entity: sensor.solcast_pv_forecast_forecast_tomorrow

price_entity: sensor.final_current_fix_electricity_price_3
```

Assumptions:

- All input data is read from configured Home Assistant entities, states and attributes.
- The integration must not call Solcast, Victron, tariff provider or device APIs directly in v1.
- `home_energy_hourly_entity` is an hourly utility-meter-like history source in kWh.
- `managed_energy_hourly_entity` is an hourly utility-meter-like history source in kWh.
- The integration stores its own hourly consumption history from those entities and uses that history to predict future consumption.
- Solcast PV forecast data is read from the configured Solcast Home Assistant forecast entities.
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
- price entity

## Options

Use Options Flow.

Options:

```yaml
managed_power_entities: []
history_retention_days: 30
history_learning_days: 3
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
- use Energy Planner's internal history-derived baseline consumption as load input
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
