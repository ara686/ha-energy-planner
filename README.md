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

| Setup field | Required | Expected entity | How to prepare it |
|-------------|----------|-----------------|-------------------|
| Battery state of charge | Yes | Numeric battery SoC sensor in `%`. | Use the SoC entity from your PV/battery inverter integration, for example Victron, GoodWe, Solax, Huawei, SolarEdge or another FVE/PV system integration. |
| Battery capacity | Yes | Numeric battery capacity sensor in `kWh`. | Use an entity from the inverter/BMS if it exists. If the battery capacity is fixed and your system does not expose it, create a Home Assistant helper that provides the configured capacity value. |
| Battery minimum state of charge | Yes | Numeric minimum SoC sensor in `%`. | Use the minimum/reserve SoC entity from the inverter/BMS. If your system only has a fixed reserve value, create a Home Assistant helper for that value. |
| Home hourly consumption history | Yes | Hourly `utility_meter` sensor in `kWh`. | Create a Utility Meter helper with cycle `hourly` from the whole-home energy consumption sensor. This is the main historical house consumption input. |
| Managed hourly consumption history | No | Hourly `utility_meter` sensor in `kWh`. | Create another Utility Meter helper with cycle `hourly` from the controlled/managed load energy sensor. This value is subtracted from home consumption per hour. |
| Solcast forecast for today | No | Solcast forecast entity from Home Assistant. | Select the Solcast entity that contains today's PV forecast in its state or attributes, for example `sensor.solcast_pv_forecast_forecast_today`. Energy Planner reads Home Assistant data only and does not call Solcast directly. |
| Solcast forecast for tomorrow | No | Solcast forecast entity from Home Assistant. | Select the Solcast entity that contains tomorrow's PV forecast, for example `sensor.solcast_pv_forecast_forecast_tomorrow`. If the today entity uses the standard Solcast naming pattern, Energy Planner can auto-detect this sibling entity. |
| Additional Solcast forecast days | No | One or more Solcast forecast entities from Home Assistant. | Select longer-horizon daily forecast sensors, for example `sensor.solcast_pv_forecast_forecast_day_3` or `sensor.solcast_pv_forecast_forecast_day_4`. If the today entity uses the standard Solcast naming pattern, Energy Planner can auto-detect `forecast_tomorrow` and `forecast_day_3` through `forecast_day_7` when those entities exist. |
| Price or tariff | No | Numeric price/tariff sensor or tariff state entity. | Reserved for tariff-aware planning and diagnostics. The current v1 planner does not control devices from this input. |

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

## Main outputs

- `lock_soc`
- `charge_to_soc`
- `safe_discharge_soc`
- `free_capacity_kwh`
- `unused_surplus_kwh`
- compact forecast object

The forecast includes at least 24 hours and can use a longer configured horizon
when Home Assistant source data is available.

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
