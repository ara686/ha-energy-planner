# ha-energy-planner

Home Assistant custom integration for PV, battery, tariff and EV planning.

> [!WARNING]
> Energy Planner is experimental software under active development. It is not recommended for production use. Install and use it at your own risk, and do not rely on it for safety-critical, life-critical, property protection, emergency, operational, financial, billing, regulatory, or compliance decisions.

The integration calculates energy planning outputs only. It does **not** control Victron, EV chargers, heaters or other devices in v1.
If you use its sensors in automations, you are responsible for validating the
automation behavior and all consequences of those automations.

## Installation

HACS custom repository:

1. Add `https://github.com/ara686/ha-energy-planner` as an Integration custom repository.
2. Install Energy Planner through HACS.
3. Restart Home Assistant.
4. Add the integration from Settings > Devices & services.

Manual installation:

1. Copy `custom_components/energy_planner` into your Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from the UI.

YAML setup is intentionally not supported in v1.

## Configuration

Energy Planner is configured only through the Home Assistant UI. It expects
already existing Home Assistant entities; it does not create helper sensors for
you in v1.

### Input entities

These values are selected in the setup UI. The `Key` column is the stored
configuration key used in diagnostics and debug output.

| Setup field | Key | Required | Expected input | Notes and examples |
|-------------|-----|----------|----------------|--------------------|
| Battery state of charge | `battery_soc_entity` | Required | Numeric battery SoC sensor in `%`. | Use the SoC entity from your PV/battery inverter integration, for example Victron, GoodWe, Solax, Huawei or SolarEdge. |
| Battery capacity | `battery_capacity_entity` | Required | Numeric battery capacity sensor in `kWh`. | Use an inverter/BMS entity if it exists. If capacity is fixed and not exposed by the inverter, create a Home Assistant helper with the configured capacity value. |
| Battery minimum state of charge | `battery_min_soc_entity` | Required | Numeric minimum/reserve SoC sensor in `%`. | Use the minimum SoC entity from the inverter/BMS. If your system only has a fixed reserve value, create a Home Assistant helper for that value. |
| Home hourly consumption history | `home_energy_hourly_entity` | Required | Hourly `utility_meter` sensor in `kWh`. | Create a Utility Meter helper with cycle `hourly` from the whole-home energy consumption sensor. This is the main historical house consumption input. |
| Managed hourly consumption history | `managed_energy_hourly_entity` | Optional | Hourly `utility_meter` sensor in `kWh`. | Create another hourly Utility Meter from intentionally controlled load energy, for example EV charging, boiler heating or water heating. This value is subtracted from home consumption per hour. |
| Solcast forecast for today | `solcast_today_entity` | Optional | Solcast forecast sensor from Home Assistant. | Example: `sensor.solcast_pv_forecast_forecast_today`. Energy Planner reads Home Assistant data only and does not call Solcast directly. |
| Solcast forecast for tomorrow | `solcast_tomorrow_entity` | Optional | Solcast forecast sensor from Home Assistant. | Example: `sensor.solcast_pv_forecast_forecast_tomorrow`. If the today entity uses the standard Solcast naming pattern, Energy Planner can auto-detect this sibling entity. |
| Additional Solcast forecast days | `solcast_additional_entities` | Optional | One or more Solcast forecast sensors from Home Assistant. | Examples: `sensor.solcast_pv_forecast_forecast_day_3`, `sensor.solcast_pv_forecast_forecast_day_4`. Standard `forecast_day_3` through `forecast_day_7` siblings can be auto-detected when they exist. |
| Price or tariff | `price_entity` | Optional | Numeric price/tariff sensor or tariff state entity. | Reserved for tariff-aware planning and diagnostics. The current v1 planner does not control devices from this input. |

### Preparing hourly consumption helpers

Energy Planner needs hourly energy totals, not instantaneous power values. For
the house and managed-load history inputs, create Home Assistant Utility Meter
helpers:

1. Go to Settings > Devices & services > Helpers.
2. Create helper > Utility Meter.
3. Select the source energy sensor in `kWh`.
4. Set the meter reset cycle to `hourly`.
5. Leave tariffs empty unless you specifically need separate tariff meters.
6. Save the helper and use the created sensor as the Energy Planner input.

For `Home hourly consumption history`, the source should represent total house
consumption. Good sources are grid/import plus PV self-consumption totals from
your energy meter or inverter, depending on what your installation exposes.

For `Managed hourly consumption history`, the source should represent only the
loads that are intentionally controlled outside the baseline house profile, for
example EV charging, boiler heating, water heating or another managed load. This
managed consumption must already be part of the home consumption total; Energy
Planner subtracts it per hour to learn the uncontrollable baseline. Do not use a
net-after-managed house sensor here, otherwise managed consumption would be
subtracted twice.

If you only have a power sensor in `W` or `kW`, create an Integration (Riemann
sum integral) helper first to convert power to energy in `kWh`, then create the
hourly Utility Meter from that energy sensor. For loads that switch on and off
and hold a stable power value, the `left` integration method is usually the
right choice.

The first Utility Meter cycle is incomplete until the next hourly reset. Energy
Planner works best after at least 3 days of Home Assistant history for both the
home and managed consumption helpers.

### Consumption history model

When Home Assistant history is available, Energy Planner reads the last 3 days
for the configured home and managed consumption sources, groups records by the
hour from `last_reset`, keeps the maximum value per hour, subtracts managed
consumption from home consumption, and builds a per-hour-of-day consumption
profile. For example, the forecast for 11:00 uses the average of previous 11:00
values, not the overall house average.

The hourly profile is increased by the Node-RED-compatible 5% margin and then by
the configurable `history_correction_percent`. If no value exists for a target
hour, the planner uses `min_baseline_kwh_per_hour`. Energy Planner also stores
its own hourly history as a fallback when Home Assistant history is unavailable.

### Solcast forecast inputs

Energy Planner consumes the detailed forecast attributes from Home Assistant
Solcast forecast sensors. In a standard Solcast PV Forecast setup, useful entity
IDs look like this:

- `sensor.solcast_pv_forecast_forecast_today`
- `sensor.solcast_pv_forecast_forecast_tomorrow`
- `sensor.solcast_pv_forecast_forecast_day_3`
- `sensor.solcast_pv_forecast_forecast_day_4`

Day 5 through day 7 can be used the same way if your Solcast integration exposes
and enables those entities.

If you configure only `sensor.solcast_pv_forecast_forecast_today`, Energy
Planner automatically looks for standard sibling entities named
`forecast_tomorrow` and `forecast_day_3` through `forecast_day_7`. This is only a
name-based convenience; it does not synthesize or extrapolate future solar data.
If your Solcast entities use different names, select tomorrow and additional
forecast days explicitly in the setup form.

For a 24 hour forecast, today and tomorrow are usually enough. For longer
horizons, or late in the evening when less of today remains, enable and select
at least `forecast_day_3`.

### Runtime options

Runtime behavior is changed through the Options Flow: planning interval, history
correction, baseline load, grid charge limits, NT windows, charge window and
forecast horizon.

## Output entities

Energy Planner creates sensor entities only. It does not create switches,
numbers, selects or any device-control entities in v1.

Entity IDs below are the typical defaults for an integration instance named
`Energy Planner`. Home Assistant may add suffixes or use renamed entity IDs if
there are conflicts or if you rename entities manually. Check the actual IDs in
Settings > Devices & services > Energy Planner > Entities.

| Typical entity ID | Output key | Category | Unit/type | Description |
|-------------------|------------|----------|-----------|-------------|
| `sensor.energy_planner_state` | `state` | Diagnostic | text | Planner state: `ok`, `warning` or `insufficient_data`. Attributes include warnings, slot count and compact history status. |
| `sensor.energy_planner_lock_soc` | `lock_soc` | Standard | `%` | Minimum SoC the planner wants to protect for the low/high tariff planning window. |
| `sensor.energy_planner_charge_to_soc` | `charge_to_soc` | Standard | `%` | Optional grid-charge target SoC needed to cover the forecasted high-tariff deficit from the configured charge window. |
| `sensor.energy_planner_target_soc` | `target_soc` | Standard | `%` | Final target SoC used by the planner; currently the higher value of `lock_soc` and `charge_to_soc`. |
| `sensor.energy_planner_safe_discharge_soc` | `safe_discharge_soc` | Standard | `%` | Lowest SoC the planner considers safe to discharge to while still preserving the future plan. |
| `sensor.energy_planner_free_capacity_soc` | `free_capacity_soc` | Standard | `%` | Current SoC above `safe_discharge_soc`, expressed as battery percentage. |
| `sensor.energy_planner_free_capacity` | `free_capacity_kwh` | Standard | `kWh` | Current energy above `safe_discharge_soc`, expressed as battery capacity. |
| `sensor.energy_planner_unused_surplus_today` | `unused_surplus_today_kwh` | Standard | `kWh` | Forecasted PV surplus for today that cannot be stored or used by the simulated plan. |
| `sensor.energy_planner_unused_surplus_total` | `unused_surplus_total_kwh` | Standard | `kWh` | Forecasted PV surplus across the configured forecast horizon that cannot be stored or used by the simulated plan. |
| `sensor.energy_planner_first_full_time` | `first_full_time` | Standard | timestamp | First forecasted time when the battery reaches full SoC. |
| `sensor.energy_planner_high_tariff_grid_import_at_target` | `vt_grid_import_kwh_at_target` | Standard | `kWh` | Forecasted high-tariff grid import remaining in the simulation when charging to `target_soc`. |
| `sensor.energy_planner_charged_total_at_target` | `charged_kwh_total_at_target` | Standard | `kWh` | Total grid energy the simulation charges into the battery to reach `target_soc`. |
| `sensor.energy_planner_soc_at_planner_start` | `soc_at_planner_start` | Diagnostic | `%` | Predicted SoC at the start of the planning window. |
| `sensor.energy_planner_soc_at_lock_start` | `soc_at_lock_start` | Diagnostic | `%` | Predicted SoC at the start of the lock/protection window. |
| `sensor.energy_planner_soc_forecast` | `soc_forecast` | Standard | `%` | State is predicted SoC at the configured forecast horizon. Attributes include `horizon_hours`, `source` and the compact future `points` array for graph cards. |
| `sensor.energy_planner_soc_forecast_24h` | `soc_forecast_24h` | Standard | `%` | Predicted SoC exactly 24 hours from the calculation time. Attribute `point` contains the full forecast point. |
| `sensor.energy_planner_solar_start` | `sun_start` | Diagnostic | timestamp | Start of the next usable solar production period detected from forecast slots. |
| `sensor.energy_planner_lock_start` | `lock_start` | Diagnostic | timestamp | Start of the period where the calculated lock SoC is relevant. |
| `sensor.energy_planner_updated` | `updated` | Diagnostic | timestamp | Time of the last successful coordinator calculation. |
| `sensor.energy_planner_history_status` | `history_status` | Diagnostic | text | Compact status for the consumption history source and coverage used by the planner. |

The SoC forecast includes at least 24 hours and can use a longer configured
horizon when Home Assistant source data is available.

## Dashboard examples

Entity IDs can differ if Home Assistant already had conflicting names. Check the
actual entity IDs in Settings > Devices & services > Energy Planner > Entities
and adjust the examples as needed.

### Future SoC forecast with ApexCharts

The full future SoC curve is exposed on the `soc_forecast` sensor as a compact
`points` attribute. The sensor state itself is only the SoC at the configured
forecast horizon.

Install `apexcharts-card` through HACS, then add a manual card like this:

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: hour
locale: cs
header:
  title: Forecast SoC
  show: true
  show_states: true
  colorize_states: true
now:
  show: true
  label: Now
yaxis:
  - min: 0
    max: 100
    decimals: 0
series:
  - entity: sensor.energy_planner_soc_forecast
    name: Predikce SoC
    type: area
    opacity: 0.35
    stroke_width: 2
    unit: "%"
    show:
      in_header: raw
      extremas: true
    data_generator: |
      const points = entity.attributes.points || [];
      return points
        .filter((point) => point.timestamp && point.soc_percent !== undefined)
        .map((point) => {
          return [new Date(point.timestamp).getTime(), Number(point.soc_percent)];
        });
```

The important part is `entity.attributes.points`. Each point uses
`timestamp` and `soc_percent`; do not use `entity.points`, `time` or `SoC`.

This example intentionally shows the next 24 hours. Increase `graph_span` to
match a longer configured forecast horizon if you also provide longer Solcast
forecast inputs.

If the card is empty:

- Confirm that `sensor.energy_planner_soc_forecast` has a `points` attribute in
  Developer Tools > States.
- Replace the entity ID if Home Assistant created a localized or suffixed name.
- Run the `energy_planner.recalculate` service and refresh the dashboard.
- Clear the browser cache after installing or updating `apexcharts-card`.

### Single 24 hour SoC value

For a simple dashboard value, use the dedicated 24 hour sensor:

```yaml
type: gauge
entity: sensor.energy_planner_soc_forecast_24h
name: SoC za 24 hodin
min: 0
max: 100
severity:
  green: 50
  yellow: 25
  red: 0
```

This sensor is a normal numeric entity, so built-in `tile`, `gauge`,
`history-graph` and `statistics-graph` cards can display its state history.
That history shows how the predicted 24 hour SoC changes over time; it is not
the full future forecast curve. Use the ApexCharts attribute example above for
the complete future curve.

## Services

- `energy_planner.recalculate` refreshes planner data for loaded entries.
- `energy_planner.export_debug` writes compact debug data to the log and fires an
  `energy_planner_debug_exported` event.

The services do not control devices.

## Troubleshooting

- `insufficient_data` means a required source entity is missing, unavailable or
  not numeric.
- `warning` usually means optional data, such as Solcast forecast, is missing or
  malformed.
- Use diagnostics from the integration page to inspect configured entities, last
  planner state, warnings and plan summary.
- Keep debug payloads out of regular state attributes; use diagnostics or
  `energy_planner.export_debug`.

## Development Validation

```bash
uv run --extra ha --extra dev ruff check .
uv run --extra ha --extra dev ruff format --check .
uv run --extra ha --extra dev pytest -q
```

Release candidates must also pass Hassfest and the HACS Action in GitHub Actions.

## Migration from Node-RED

This integration replaces the active `Energy Prediction 2` Node-RED flow with a
tested Home Assistant integration.

Only the active Node-RED calculation path is used as a parity reference. Backup,
dated archive and disconnected Node-RED nodes are ignored.

The local `nodered_export.json` file is intentionally ignored by Git and must not
be published. Parity tests use sanitized fixtures derived from understood active
flow behavior, not raw Node-RED code.

Important migration notes:

- v1 exposes planner sensors only and does not control devices.
- `lock_soc` preserves the battery reserve for NT/VT planning.
- `charge_to_soc` is the optional grid-charge target for the configured charge window.
- `free_capacity_kwh` means safely dischargeable energy above `safe_discharge_soc`.
- The legacy flow adds 1 percentage point to the configured battery minimum SoC before using it as its effective floor; parity fixtures model that explicitly.
- Consumption prediction follows the active flow's hourly profile: last 3 days of HA history, grouped by `last_reset`, managed consumption subtracted per hour, plus the 5% history margin.
- The pure planner may expose cleaner timestamp formatting and compact forecast attributes while preserving the core planning outputs.

See `SPECIFICATION.md` and `CODEX_IMPLEMENTATION_PROMPT.md`.

## Disclaimer

This software is provided as-is, without warranty, and without a support
guarantee. See `DISCLAIMER.md` for project risk and support limitations.
