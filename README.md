# ha-energy-planner

English | [Česky](README.cs.md)

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
already existing Home Assistant source entities and maintains its own internal
hourly consumption history; you do not need to create Utility Meter helpers.

The setup and reconfigure forms filter entity pickers by expected domain and
device class where Home Assistant exposes that metadata. Submit validation then
enforces the exact unit and state class requirements. For example, battery
capacity must be a positive `kWh` entity, while house and managed consumption
inputs are cumulative energy sensors in `kWh`.

After setup, use **Settings > Devices & services > Energy Planner > Reconfigure**
to change input entities without deleting and adding the integration again.

### Input entities

These values are selected in the setup UI. The `Key` column is the stored
configuration key used in diagnostics and debug output.

| Setup field | Key | Required | Expected input | Notes and examples |
|-------------|-----|----------|----------------|--------------------|
| Battery state of charge | `battery_soc_entity` | Required | Numeric battery SoC sensor in `%`. | Use the SoC entity from your PV/battery inverter integration, for example Victron, GoodWe, Solax, Huawei or SolarEdge. |
| Battery capacity | `battery_capacity_entity` | Required | Numeric battery capacity sensor in `kWh`. | Use an inverter/BMS entity if it exists. If capacity is fixed and not exposed by the inverter, create a Home Assistant helper with the configured capacity value. |
| Battery minimum state of charge | `battery_min_soc_entity` | Required | Numeric minimum/reserve SoC sensor in `%`. | Use the minimum SoC entity from the inverter/BMS. If your system only has a fixed reserve value, create a Home Assistant helper for that value. |
| Home energy source | `home_energy_entity` | Required | Cumulative whole-home energy sensor in `kWh`. | Use a total/total-increasing energy sensor for house consumption. Energy Planner builds the hourly history internally from this source. |
| Managed energy sources | `managed_energy_entities` | Optional | Zero, one or more cumulative energy sensors in `kWh`. | Select intentionally controlled loads, for example EV charging, boiler heating or water heating. These values are summed and subtracted from home consumption per hour. |
| Solcast forecast for today | `solcast_today_entity` | Optional | Solcast forecast sensor from Home Assistant. | Example: `sensor.solcast_pv_forecast_forecast_today`. Energy Planner reads Home Assistant data only and does not call Solcast directly. |
| Solcast forecast for tomorrow | `solcast_tomorrow_entity` | Optional | Solcast forecast sensor from Home Assistant. | Example: `sensor.solcast_pv_forecast_forecast_tomorrow`. If the today entity uses the standard Solcast naming pattern, Energy Planner can auto-detect this sibling entity. |
| Additional Solcast forecast days | `solcast_additional_entities` | Optional | One or more Solcast forecast sensors from Home Assistant. | Examples: `sensor.solcast_pv_forecast_forecast_day_3`, `sensor.solcast_pv_forecast_forecast_day_4`. Standard `forecast_day_3` through `forecast_day_7` siblings can be auto-detected when they exist. |
| Price or tariff | `price_entity` | Optional | Numeric price/tariff sensor or tariff state entity. | Reserved for tariff-aware planning and diagnostics. The current v1 planner does not control devices from this input. |

### Consumption energy sources

Energy Planner needs cumulative energy values, not instantaneous power values.
For the home source, select a sensor that represents total house consumption in
`kWh`. Good sources are grid/import plus PV self-consumption totals from your
energy meter or inverter, depending on what your installation exposes.

For `Managed energy sources`, select only loads that are intentionally
controlled outside the baseline house profile, for example EV charging, boiler
heating, water heating or another managed load. Managed consumption must already
be part of the home consumption total; Energy Planner subtracts it per hour to
learn the uncontrollable baseline. Do not use a net-after-managed house sensor,
otherwise managed consumption would be subtracted twice.

If you only have a power sensor, for example `sensor.home_power` in `W`, create
a Home Assistant Integral helper first to convert power to energy in `kWh`, then
select that new energy sensor in Energy Planner. In Home Assistant, create an
Integration (Riemann sum integral) helper from the power sensor, set the output
unit to `kWh`, and use the resulting cumulative energy sensor as
`home_energy_entity`. Do this only when you do not already have a suitable `kWh`
energy sensor. Do not integrate an entity that is already cumulative energy in
`kWh`. For loads that switch on and off and hold a stable power value, the
`left` integration method is usually the right choice.

Energy Planner builds hourly buckets internally from positive deltas of the
selected cumulative energy sensors. The first reading is only a baseline; useful
history starts once the source changes or once Home Assistant recorder history
is available. On a fresh setup without existing recorder history for the
selected sources, the first reasonable results usually appear after roughly 24
hours. The profile becomes noticeably more accurate after roughly 48 hours
because the planner has seen at least two samples for the same hour of day.

### Consumption history model

When Home Assistant history is available, Energy Planner reads the configured
number of history days for the home and managed energy sources, calculates
positive cumulative deltas, assigns those deltas to hourly buckets, subtracts
managed consumption from home consumption, and builds a per-hour-of-day
consumption profile. For example, the forecast for 11:00 uses the average of
previous 11:00 values, not the overall house average.

The hourly profile is increased by a built-in 5% history margin and then by the
configurable `history_correction_percent`. If no value exists for a target hour,
the planner uses `min_baseline_kwh_per_hour`. Energy Planner also stores its own
hourly history as a fallback when Home Assistant history is unavailable.

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

Runtime behavior is changed through the Options Flow: automatic recalculation
interval, consumption history days, planning interval, history correction,
baseline load, grid charge limits, NT windows, charge window and forecast
horizon.

Open Settings > Devices & services > Energy Planner > Configure to change these
values. The same values are also exposed as read-only diagnostic sensors, so you
can see and reference the exact active settings from Home Assistant states.
The entity IDs below are typical defaults; verify the actual IDs in Home
Assistant if your backend language, conflicts or manual renames changed them.

| UI field | Key | Diagnostic entity | Default | Accepted value | Description |
|----------|-----|-------------------|---------|----------------|-------------|
| Recalculation interval in minutes | `update_interval_minutes` | `sensor.energy_planner_recalculation_interval` | `60` | Positive number. | Automatic planner polling interval. A battery SoC state change also triggers an immediate recalculation, so the planner can react before the next periodic update. |
| Consumption history days | `history_learning_days` | `sensor.energy_planner_consumption_history_days` | `3` | Positive whole number. | Number of days of Home Assistant history used to build the hourly consumption profile. |
| Planning interval in minutes | `interval_minutes` | `sensor.energy_planner_planning_interval` | `5` | Positive number that divides 60 exactly. | Time step used for the planner simulation and forecast slots. Common values are `5`, `10`, `15`, `30` or `60`. |
| History correction percent | `history_correction_percent` | `sensor.energy_planner_history_correction` | `5.0` | Greater than `-100` and at most `500`. | Extra percentage applied after the hourly consumption profile is calculated. Use this to tune the learned consumption profile. |
| Minimum baseline consumption in kWh per hour | `min_baseline_kwh_per_hour` | `sensor.energy_planner_minimum_baseline_consumption` | `0.2` | `0` or higher. | Fallback hourly home consumption when the target hour has no usable history sample. |
| Maximum grid charging power in kW | `grid_charge_max_kw` | `sensor.energy_planner_maximum_grid_charging_power` | `5.5` | `0` or higher. | Maximum power the simulation may use when planning grid charging during the charge window. |
| Grid charging efficiency | `grid_charge_efficiency` | `sensor.energy_planner_grid_charging_efficiency` | `0.92` | Greater than `0` and at most `1`. | Battery charging efficiency used when converting grid energy into stored battery energy. |
| SoC reserve percent | `soc_reserve_percent` | `sensor.energy_planner_soc_reserve` | `1` | From `0` to `100`. | Extra SoC margin added to calculated lock/target values. |
| SoC tolerance in kWh | `soc_eps_kwh` | `sensor.energy_planner_soc_tolerance` | `0.02` | `0` or higher. | Small battery-energy tolerance used by the planner to avoid unstable decisions around exact thresholds. |
| Low-tariff windows | `nt_windows` | `sensor.energy_planner_low_tariff_windows` | `17:00-19:00,22:00-04:00` | One or more `HH:MM-HH:MM` windows separated by commas. | Windows where low/high tariff protection is evaluated. Windows may cross midnight. |
| Charging window | `charge_window` | `sensor.energy_planner_charging_window` | `22:00-04:00` | One `HH:MM-HH:MM` window. | Window where simulated grid charging may be planned. The window may cross midnight. |
| Minimum solar start duration in minutes | `sun_start_required_minutes` | `sensor.energy_planner_minimum_solar_start_duration` | `30` | Greater than `0`. | Minimum continuous forecasted solar period before the planner treats solar production as started. |
| Forecast horizon in hours | `forecast_horizon_hours` | `sensor.energy_planner_forecast_horizon` | `36` | At least `24`. | Future horizon used for SoC forecast and planning. Longer horizons require matching future Solcast data. |

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
| `sensor.energy_planner_history_status` | `history_status` | Diagnostic, disabled by default | text | Compact status for the consumption history source and coverage used by the planner. Full details are also available in integration diagnostics. |
| `sensor.energy_planner_consumption_history` | `consumption_history` | Diagnostic | `kWh` | Latest hourly base consumption bucket used by the planner. Attributes include compact hourly `points` with `home_kwh`, `managed_kwh` and `base_kwh` values for graph cards. |

Only `sensor.energy_planner_soc_forecast` uses Home Assistant's `battery`
device class. The other SoC outputs are planning setpoints, limits or future
helper values, so they remain plain percentage sensors and are not exposed as
battery-level sensors.

The SoC forecast includes at least 24 hours and can use a longer configured
horizon when Home Assistant source data is available.
Forecast `soc_percent` values are rounded to whole integer percentages because
most PV and battery systems do not provide meaningful decimal SoC precision.

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

### Future unused PV surplus with ApexCharts

Each forecast point also contains `unused_surplus_kwh`, which is the surplus
energy for that planner slot. The example below converts slot energy to an
equivalent power value in `kW` by using the interval between forecast points. For
a 5 minute planner interval, this is equivalent to multiplying slot `kWh` by
`12`.

```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: hour
locale: cs
header:
  title: Forecast unused PV surplus
  show: true
  colorize_states: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_soc_forecast
    name: Unused surplus
    type: area
    opacity: 0.45
    stroke_width: 2
    unit: kW
    show:
      extremas: true
    data_generator: |
      const points = entity.attributes.points || [];
      const first = new Date(points[0]?.timestamp).getTime();
      const second = new Date(points[1]?.timestamp).getTime();
      const intervalHours =
        Number.isFinite(first) && Number.isFinite(second) && second > first
          ? (second - first) / 3600000
          : 1;

      return points
        .map((point) => {
          const timestamp = new Date(point.timestamp).getTime();
          if (!Number.isFinite(timestamp)) {
            return null;
          }
          const surplusKwh = Number(point.unused_surplus_kwh ?? 0);
          return [
            timestamp,
            Number.isFinite(surplusKwh) ? surplusKwh / intervalHours : 0,
          ];
        })
        .filter((point) => point !== null);
```

To show raw energy per planner slot instead, change `unit` to `kWh` and return
`surplusKwh` instead of `surplusKwh / intervalHours`.

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

### Consumption history with ApexCharts

The `sensor.energy_planner_consumption_history` state is the latest hourly base
consumption bucket in `kWh`. Its `points` attribute contains the hourly history
used by the planner. Each point contains:

- `home_kwh`: whole-home consumption in the hour.
- `managed_kwh`: intentionally managed consumption in the hour.
- `base_kwh`: `home_kwh - managed_kwh`, clamped to zero.

The sensor exposes the newest 168 hourly points at most. If the configured
history window is longer, the `truncated` attribute is `true`.

```yaml
type: custom:apexcharts-card
graph_span: 3d
span:
  end: hour
locale: en
header:
  title: Consumption history
  show: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_consumption_history
    name: Home
    type: column
    unit: kWh
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.home_kwh ?? 0),
      ]);
  - entity: sensor.energy_planner_consumption_history
    name: Managed
    type: column
    unit: kWh
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.managed_kwh ?? 0),
      ]);
  - entity: sensor.energy_planner_consumption_history
    name: Base
    type: line
    unit: kWh
    stroke_width: 2
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.base_kwh ?? 0),
      ]);
```

### Home and managed power history with ApexCharts

If you want to compare whole-home consumption with managed consumption in one
power chart, use the same `points` attribute and convert each hourly energy
bucket to average power. For hourly buckets, `kWh / 1 h` is the average `kW`.

```yaml
type: custom:apexcharts-card
graph_span: 3d
span:
  end: hour
locale: en
header:
  title: Home vs managed power history
  show: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_consumption_history
    name: Home power
    type: column
    unit: kW
    data_generator: |
      const points = entity.attributes.points || [];

      const intervalHours = (index) => {
        const current = new Date(points[index]?.timestamp).getTime();
        const next = new Date(points[index + 1]?.timestamp).getTime();
        const previous = new Date(points[index - 1]?.timestamp).getTime();
        if (Number.isFinite(current) && Number.isFinite(next) && next > current) {
          return (next - current) / 3600000;
        }
        if (Number.isFinite(previous) && Number.isFinite(current) && current > previous) {
          return (current - previous) / 3600000;
        }
        return 1;
      };

      return points.map((point, index) => {
        const timestamp = new Date(point.timestamp).getTime();
        const hours = intervalHours(index);
        return [
          timestamp,
          Number(point.home_kwh ?? 0) / hours,
        ];
      });
  - entity: sensor.energy_planner_consumption_history
    name: Managed power
    type: column
    unit: kW
    data_generator: |
      const points = entity.attributes.points || [];

      const intervalHours = (index) => {
        const current = new Date(points[index]?.timestamp).getTime();
        const next = new Date(points[index + 1]?.timestamp).getTime();
        const previous = new Date(points[index - 1]?.timestamp).getTime();
        if (Number.isFinite(current) && Number.isFinite(next) && next > current) {
          return (next - current) / 3600000;
        }
        if (Number.isFinite(previous) && Number.isFinite(current) && current > previous) {
          return (current - previous) / 3600000;
        }
        return 1;
      };

      return points.map((point, index) => {
        const timestamp = new Date(point.timestamp).getTime();
        const hours = intervalHours(index);
        return [
          timestamp,
          Number(point.managed_kwh ?? 0) / hours,
        ];
      });
```

## Services

- `energy_planner.recalculate` refreshes planner data for loaded entries.
- `energy_planner.export_debug` writes compact debug data to the log and fires an
  `energy_planner_debug_exported` event.

The services do not control devices.

## Troubleshooting

- `insufficient_data` means a required source entity is missing, unavailable or
  not numeric.
- `error` with `Battery capacity must be greater than zero` means the configured
  `battery_capacity_entity` is not a positive battery capacity in `kWh`. Do not
  use current or installed-capacity-in-`Ah` entities; use a `kWh` capacity entity
  or a Home Assistant helper with the fixed battery capacity.
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

See `SPECIFICATION.md` and `CODEX_IMPLEMENTATION_PROMPT.md`.

## Disclaimer

This software is provided as-is, without warranty, and without a support
guarantee. See `DISCLAIMER.md` for project risk and support limitations.
