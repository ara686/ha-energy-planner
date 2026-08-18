# Detailed Configuration

Energy Planner is configured only through the Home Assistant UI. YAML setup is
not supported.

Use **Settings > Devices & services > Energy Planner > Reconfigure** to change
the shared input entities. Add, edit or remove each managed load from the
integration entry's **Managed loads** section. Reconfiguration keeps the stored
Energy Planner history.

## Setup Inputs

The `Key` column is the internal configuration key visible in diagnostics.

| Setup field | Key | Required | Expected input | Notes and examples |
|-------------|-----|----------|----------------|--------------------|
| Battery state of charge | `battery_soc_entity` | Required | Numeric battery SoC sensor in `%`. | Use the SoC entity from your PV/battery inverter integration, for example Victron, GoodWe, Solax, Huawei or SolarEdge. |
| Battery capacity | `battery_capacity_entity` | Required | Numeric battery capacity sensor in `kWh`. | Use an inverter/BMS entity if it exists. If capacity is fixed and not exposed by the inverter, create a Home Assistant helper with the configured capacity value. |
| Battery minimum state of charge | `battery_min_soc_entity` | Required | Numeric minimum/reserve SoC `sensor`, `number` or `input_number` entity in `%`. | Generic inverter `number` entities without the battery device class are supported, for example `number.inverter_battery_low_soc`. If your system only has a fixed reserve value, create a Home Assistant helper for that value. |
| Home energy source | `home_energy_entity` | Required | Cumulative whole-home energy sensor in a Home Assistant-supported energy unit, such as `Wh`, `kWh` or `MWh`. | Use a total/total-increasing energy sensor for house consumption. Energy Planner normalizes source values to `kWh` and builds the hourly history internally. |
| Solcast forecast for today | `solcast_today_entity` | Optional | Solcast forecast sensor from Home Assistant. | Example: `sensor.solcast_pv_forecast_forecast_today`. Energy Planner reads Home Assistant data only and does not call Solcast directly. |
| Solcast forecast for tomorrow | `solcast_tomorrow_entity` | Optional | Solcast forecast sensor from Home Assistant. | Example: `sensor.solcast_pv_forecast_forecast_tomorrow`. If the today entity uses the standard Solcast naming pattern, Energy Planner can auto-detect this sibling entity. |
| Additional Solcast forecast days | `solcast_additional_entities` | Optional | One or more Solcast forecast sensors from Home Assistant. | Examples: `sensor.solcast_pv_forecast_forecast_day_3`, `sensor.solcast_pv_forecast_forecast_day_4`. Standard `forecast_day_3` through `forecast_day_7` siblings can be auto-detected when they exist. |

## Consumption Energy Sources

Energy Planner needs cumulative energy values, not instantaneous power values.
For the home source, select a sensor that represents total house consumption in
`kWh`. Good sources are grid/import plus PV self-consumption totals from your
energy meter or inverter, depending on what your installation exposes.

Add managed loads as separate items under the integration entry after completing
the shared setup. Select only loads that are intentionally controlled outside
the baseline house profile. Managed consumption must already be part of the home
consumption total; Energy Planner subtracts it per hour to learn the
uncontrollable baseline. Do not use a net-after-managed house sensor, otherwise
managed consumption would be subtracted twice.

Each managed source is tracked separately as well as in the combined
`managed_kwh` total. This lets you see values such as EV charging today, water
heating in the last hour or a tracked total for one controlled load. The source
entities should have useful Home Assistant friendly names before you add the
integration, because those names are used when the per-source entities are first
created.

Every managed-load item first asks for these common fields:

| Field | Key | Required | Description |
|-------|-----|----------|-------------|
| Managed load type | `managed_load_type` | Required | `generic` uses history or an explicit request. `hot_water` uses the physical tank model. `electric_vehicle` uses a current battery-side request and future charging-power limit. Pool is intentionally not offered until it has a dedicated model. |
| Priority | `priority` | Required | Positive whole number, default `100`. Lower numbers are allocated first within an allocation phase. Loads with equal priority share shortages proportionally. |
| Cumulative energy meter | `managed_energy_entity` | Required | A `total` or `total_increasing` energy sensor in a supported energy unit such as `Wh`, `kWh` or `MWh`. Its values are normalized to `kWh`; hourly and daily deltas are used for history. |

The cumulative meter remains required for all types so managed consumption can
be removed from the house profile and exposed by the historical sensors.

### Generic managed load

| Field | Key | Required | Description |
|-------|-----|----------|-------------|
| Requested energy tomorrow | `requested_energy_entity` | Optional | A numeric sensor, number or input-number entity in `kWh`. A valid non-negative state replaces this load's historical demand estimate for tomorrow. |

Without a valid request, the `generic` strategy estimates demand from historical
daily consumption. The requested-energy input can be filled by a helper or
template that already understands a device-specific condition. Energy Planner
does not control the device.

### Hot-water managed load

| Field | Key | Required | Description |
|-------|-----|----------|-------------|
| Top water temperature | `top_temperature_entity` | Required | Numeric Home Assistant temperature sensor near 80% of the upright tank height. Supported temperature units are converted to Celsius. |
| Bottom water temperature | `bottom_temperature_entity` | Required | A different numeric temperature sensor near 20% of the tank height. |
| Minimum average temperature | `minimum_temperature_c` | Required | Minimum target for the calculated average tank temperature in °C. Solar shortage can leave this target unmet. |
| Maximum average temperature | `maximum_temperature_c` | Required | Maximum flexible solar target in °C; default `70`. Must be greater than the minimum and remain within the safe limits of the installation. |
| Tank volume | `tank_volume_liters` | Required | Positive total water volume in liters. |
| Heater input power | `heater_power_kw` | Required | Positive electrical input power in kW. It caps allocation in every planner slot. |
| Thermal conversion factor | `thermal_conversion_factor` | Required | Positive delivered heat / consumed electricity ratio; default `1.0` for a resistive heater. A value above `1` can represent heat-pump COP. |

For the assumed upright cylindrical tank with sensors at 20% and 80%, symmetry
gives this model:

```text
average temperature = (top temperature + bottom temperature) / 2
thermal kWh = 0.001163 × tank volume liters × max(target - average, 0)
electrical kWh = thermal kWh / thermal conversion factor
```

The tank diameter is not required. The minimum and maximum both apply to the
average temperature, not to either individual sensor. The model currently does
not include water draw, standing losses, sensor delay or temperature transfer
between forecast days. Invalid or unavailable temperature input withholds this
load's recommendation; it never falls back to history.

### Electric-vehicle managed load

| Field | Key | Required | Description |
|-------|-----|----------|-------------|
| Remaining battery energy | `required_energy_entity` | Required | Current non-negative energy still storable in the vehicle battery. `sensor`, `number` and `input_number` entities with units convertible to `kWh` are supported. For example, use `sensor.enyaq_charge_kwh`. |
| Maximum charging input power | `maximum_charging_power_entity` | Required | Positive future charger-input limit from a `sensor`, `number` or `input_number` entity with units convertible to `kW`. It must not be an instantaneous zero-power reading from an idle charger. |
| Charging efficiency | `charging_efficiency` | Required | Battery energy divided by charger electrical input, greater than zero and at most `1`; default `0.90`. |

The request is converted to charger-input energy:

```text
electrical required kWh = battery required kWh / charging efficiency
```

A zero request is valid. The integration watches both EV input entities and
requests a debounced recalculation when either state changes. Invalid or
unavailable EV input withholds only this load's recommendation; an
`electric_vehicle` load never falls back to history. Energy Planner assumes the
vehicle can charge in every planned slot and does not model connection state,
departure time, driving or target-SoC changes.

If you only have a power sensor, for example `sensor.home_power` in `W`, create
a Home Assistant Integral helper first to convert power to energy in `kWh`, then
select that new energy sensor in Energy Planner. Do this only when you do not
already have a suitable `kWh` energy sensor. Do not integrate an entity that is
already cumulative energy in `kWh`.

For loads that switch on and off and hold a stable power value, the `left`
integration method is usually the right choice.

## History And First Results

Energy Planner builds hourly buckets internally from positive deltas of the
selected cumulative energy sensors. The first reading is only a baseline.

Useful history starts once the source changes or once Home Assistant recorder
history is available. On a fresh setup without existing recorder history for the
selected sources, the first reasonable results usually appear after roughly 24
hours. The profile becomes noticeably more accurate after roughly 48 hours
because the planner has seen at least two samples for the same hour of day.

## Solcast Forecast Inputs

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

For a 24 hour forecast, today and tomorrow are usually enough. For longer
horizons, or late in the evening when less of today remains, enable and select
at least `forecast_day_3`.

## Runtime Options

Open **Settings > Devices & services > Energy Planner > Configure** to change
runtime behavior.

| UI field | Key | Diagnostic entity | Default | Accepted value | Description |
|----------|-----|-------------------|---------|----------------|-------------|
| Recalculation interval in minutes | `update_interval_minutes` | `sensor.energy_planner_recalculation_interval` | `60` | Positive number. | Automatic planner polling interval. Battery SoC changes also trigger a debounced recalculation before the next periodic update. |
| Consumption history days | `history_learning_days` | `sensor.energy_planner_consumption_history_days` | `3` | Positive whole number. | Number of days of Home Assistant history used to build the hourly consumption profile. |
| Planning interval in minutes | `interval_minutes` | `sensor.energy_planner_planning_interval` | `5` | Positive number that divides 60 exactly. | Time step used for the planner simulation and forecast slots. Common values are `5`, `10`, `15`, `30` or `60`. |
| History correction percent | `history_correction_percent` | `sensor.energy_planner_history_correction` | `5.0` | Greater than `-100` and at most `500`. | Extra percentage applied after the hourly consumption profile is calculated. |
| Minimum baseline consumption in kWh per hour | `min_baseline_kwh_per_hour` | `sensor.energy_planner_minimum_baseline_consumption` | `0.2` | `0` or higher. | Fallback hourly home consumption when the target hour has no usable history sample. |
| Enable grid-charging planning | `grid_charging_enabled` | — | Enabled | Boolean switch. | Disable this independently when the installation must not plan battery charging from the grid. Energy Planner never controls the charger directly. |
| Maximum grid charging power in kW | `grid_charge_max_kw` | `sensor.energy_planner_maximum_grid_charging_power` | `5.5` | `0` or higher. | Maximum power the simulation may use when planning grid charging during the charge window. |
| Grid charging efficiency | `grid_charge_efficiency` | `sensor.energy_planner_grid_charging_efficiency` | `0.92` | Greater than `0` and at most `1`. | Battery charging efficiency used when converting grid energy into stored battery energy. |
| SoC reserve percent | `soc_reserve_percent` | `sensor.energy_planner_soc_reserve` | `1` | From `0` to `100`. | Extra SoC margin added to calculated lock/target values. |
| SoC tolerance in kWh | `soc_eps_kwh` | `sensor.energy_planner_soc_tolerance` | `0.02` | `0` or higher. | Small battery-energy tolerance used by the planner to avoid unstable decisions around exact thresholds. |
| Low-tariff windows | `nt_windows` | `sensor.energy_planner_low_tariff_windows` | `17:00-19:00,22:00-04:00` | Enable switch plus two optional start/end time selector pairs in the UI. | Disable the switch for installations without dual-rate pricing; no slot is then treated as low tariff. Enabled windows may cross midnight and their start and end must differ. |
| Planned grid-charging window | `charge_window` | `sensor.energy_planner_charging_window` | `22:00-04:00` | Two optional start/end time selectors in the UI. | Used only when grid-charging planning is enabled. The window may cross midnight and start/end must then differ. When disabled, invalid or empty window values are ignored and the diagnostic sensor reports `disabled`. |
| Minimum solar start duration in minutes | `sun_start_required_minutes` | `sensor.energy_planner_minimum_solar_start_duration` | `30` | Greater than `0`. | Minimum continuous forecasted solar period before the planner treats solar production as started. |
| Forecast horizon in hours | `forecast_horizon_hours` | `sensor.energy_planner_forecast_horizon` | `48` | At least `24`. | The 48-hour default leaves room for a complete next local day. A shorter horizon can make tomorrow's recommendation unavailable. Longer horizons require matching future Solcast data. |

## Managed-load Allocation

For each `generic` load without a valid requested-energy value, Energy Planner
uses up to seven completed local calendar days with at least 75% hourly source
coverage. A recorded zero is a real zero-use day; missing hours are not treated
as zero. At least three qualified days are required.

```text
active probability = active days / observed days
active-day energy = median of days with at least 0.05 kWh
expected demand = active probability × active-day energy
```

Allocation runs directly over passive-forecast `unused_surplus_kwh` slots in
four phases:

1. `hot_water` electrical energy needed to reach the configured minimum.
2. `electric_vehicle` charger-input energy.
3. Historical or explicitly requested `generic` energy.
4. Flexible `hot_water` capacity from the minimum to the maximum.

Within each phase, lower priorities run first and equal priorities share a
shortage proportionally. Hot-water allocation is limited by remaining demand,
remaining surplus and `heater_power_kw × slot duration`. The configured minimum
is a solar target, not a guarantee; `minimum_shortfall_kwh` reports any unmet
part. EV allocation uses the equivalent
`maximum_charging_power_kw × slot duration` limit and reports electrical and
battery-side shortfalls.

EV is first allocated from the next complete planner boundary through today's
local midnight. If that whole remaining period is not covered, today's EV
recommendation is unavailable and the complete request carries to tomorrow; if
no slot remains, today's recommendation is zero. Tomorrow includes every load
type. Later complete days repeat the current hot-water deficit, carry only the
unmet EV remainder and do not repeat generic demand. Each day's solar surplus
and allocation remains separate. The model neither carries simulated tank
temperature nor changes the EV input entity; its next state corrects the plan at
the following recalculation. Only solar surplus is recommended—grid charging is
not part of managed-load allocation.
