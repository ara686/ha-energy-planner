# Energy Planner for Home Assistant

English | [Česky](README.cs.md)

Energy Planner helps Home Assistant users understand what will probably happen
with a home battery during the next day. It combines your recent house
consumption, optional managed loads and Solcast PV forecast data that already
exists in Home Assistant.

> [!WARNING]
> Energy Planner is experimental software under active development. It is not
> recommended for production use. Install and use it at your own risk, and do
> not rely on it for safety-critical, life-critical, property protection,
> emergency, operational, financial, billing, regulatory, or compliance
> decisions.

Energy Planner **does not control anything by itself**. It only creates sensors
and binary sensors that you can use in dashboards or in your own automations.

## What It Helps With

- See a future battery SoC forecast for the next 24 hours or longer.
- Decide whether the battery should be charged during a low-tariff period.
- Decide whether battery discharge is currently still safe for the plan.
- Estimate unused PV surplus that can be used for flexible loads such as hot
  water, pool technology or EV charging.
- Recommend how tomorrow's fully covered surplus can be divided among managed
  loads from their recent daily usage or an optional requested-energy entity.
- Keep managed loads out of the normal house consumption profile, so the planner
  learns the base household load more realistically.
- Track managed loads separately, so you can see how much energy went into EV
  charging, water heating or other controlled loads.

For example, with a Czech D25d tariff you can use the forecast to run flexible
loads from summer PV surplus, and in winter use the low-tariff window to bridge
the next high-tariff period.

## Installation

Home Assistant 2025.3 or newer is required.

### HACS

1. Add `https://github.com/ara686/ha-energy-planner` as an **Integration**
   custom repository in HACS.
2. Install **Energy Planner**.
3. Restart Home Assistant.
4. Add **Energy Planner** from **Settings > Devices & services**.

### Manual Installation

1. Copy `custom_components/energy_planner` into your Home Assistant
   `custom_components` directory.
2. Restart Home Assistant.
3. Add the integration from **Settings > Devices & services**.

YAML setup is not supported.

## What You Need Before Setup

Energy Planner is configured from the Home Assistant UI. You select existing HA
entities during setup.

Required:

- Battery SoC entity in `%`.
- Battery capacity entity in `kWh`.
- Battery minimum/reserve SoC entity in `%`.
- Whole-home cumulative energy entity in `kWh`.

Optional:

- One or more managed-load cumulative energy entities in `kWh`, such as EV
  charging, water heater, boiler or pool technology.
- An optional numeric `kWh` entity for each managed load with the energy you
  want to supply tomorrow. It overrides that load's historical estimate.
- Solcast PV forecast entities for today, tomorrow and additional days.

If your home consumption is only available as a power sensor, for example
`sensor.home_power` in `W`, create a Home Assistant **Integral** helper first and
use the resulting `kWh` energy sensor.

See [detailed configuration](docs/configuration.md) for the full input list,
accepted units and runtime options.

## First Results

Energy Planner builds an hourly consumption profile from Home Assistant history.

- If Home Assistant already has history for your selected energy sensors, useful
  values can appear immediately.
- On a fresh setup without history, expect the first reasonable results after
  about 24 hours.
- Results become more accurate after about 48 hours because the planner has seen
  repeated samples for the same hour of day.
- Managed-load recommendations require at least three coverage-qualified
  completed days. The normal estimate uses up to seven recent days.

Reconfigure keeps the stored history. If you change a source entity, check the
results for a while and only remove the integration if you intentionally want to
delete the stored planner history.

## Main Entities To Use

The exact entity IDs can differ if Home Assistant adds a suffix or if you rename
entities. Check them in **Settings > Devices & services > Energy Planner >
Entities**.

Most useful entities:

| Entity | What it means |
|--------|---------------|
| `sensor.energy_planner_soc_forecast` | Passive forecasted SoC at the configured forecast horizon. It uses current SoC, consumption history and PV forecast, without assuming Energy Planner automations have already charged or locked the battery. Its attributes contain the future forecast points for graphs. |
| `sensor.energy_planner_soc_forecast_24h` | Passive forecasted SoC exactly 24 hours from the last calculation. |
| `binary_sensor.energy_planner_charge_now` | On when the plan says charging is currently useful. |
| `binary_sensor.energy_planner_discharge_allowed` | On when the plan says battery discharge is still allowed. |
| `sensor.energy_planner_target_soc` | Target SoC used by the planner. |
| `sensor.energy_planner_charge_to_soc` | SoC level needed for planned grid charging. |
| `sensor.energy_planner_safe_discharge_soc` | Lowest SoC that should still preserve the plan. |
| `sensor.energy_planner_unused_surplus_today` | Estimated unused PV surplus for today from the passive forecast. |
| `sensor.energy_planner_unused_surplus_tomorrow` | Tomorrow's allocatable surplus. It has a value only when the complete local day and its solar input are covered. |
| `sensor.energy_planner_recommended_managed_energy_tomorrow` | Total energy recommended for all managed loads tomorrow. |
| `sensor.energy_planner_unallocated_surplus_tomorrow` | Complete tomorrow surplus remaining after all recommendations. |
| `sensor.energy_planner_managed_<source>_suggested_tomorrow` | Recommended energy for one managed load, with method, confidence and historical inputs in attributes. |
| `sensor.energy_planner_managed_<source>_today` | Energy used today by one managed load, for example EV charging or water heating. |
| `sensor.energy_planner_managed_<source>_tracked_total` | Energy Planner's tracked total for one managed load. |

See [all created entities](docs/entities.md) for the complete list.

## Dashboards

Start with these dashboard ideas:

- Future SoC chart from `sensor.energy_planner_soc_forecast`.
- 24 hour SoC gauge from `sensor.energy_planner_soc_forecast_24h`.
- Unused PV surplus chart.
- Home vs managed consumption history chart.
- Per-load managed consumption chart, for example EV charging and water heating
  in separate series.

Lovelace and ApexCharts examples live in [dashboard examples](docs/dashboard.md).
Screenshots can be added there later without making this README too long.

## Automation Ideas

Energy Planner does not operate devices directly, but it provides simple signals
for automations:

- Use `binary_sensor.energy_planner_charge_now` to allow grid charging.
- Use `binary_sensor.energy_planner_discharge_allowed` to allow battery
  discharge.
- Use `sensor.energy_planner_unused_surplus_today` to start flexible loads when
  there is enough predicted PV surplus.
- Use each `managed_<source>_suggested_tomorrow` value as an input to your own
  next-day automation; Energy Planner still does not switch the device itself.
- Use per-load managed sensors to prioritize loads, for example heat water
  before allowing EV charging.

Example automations with placeholders are in
[automation examples](docs/automations.md). Always test automations manually in
your own Home Assistant before letting them control real devices.

## Manual Recalculation

Energy Planner recalculates automatically. It also reacts to battery SoC changes.

You can force a recalculation from **Developer Tools > Services**:

```text
energy_planner.recalculate
```

## Troubleshooting

- `insufficient_data` usually means a required source entity is missing,
  unavailable or not numeric.
- If the home source is in `W`, convert it to `kWh` with an Integral helper.
- `warning` usually means a configured optional source, such as a selected
  Solcast entity, is missing or has no usable forecast data.
- If forecast graphs are empty, check that
  `sensor.energy_planner_soc_forecast` has a `points` attribute in
  **Developer Tools > States**.
- If values look strange after the first setup, wait until the planner has at
  least 24 to 48 hours of history.

Use diagnostics from the integration page to inspect configured entities, active
options, warnings and the last planner output.

## Removal

To remove Energy Planner:

1. Open **Settings > Devices & services > Energy Planner**.
2. Delete the integration entry.
3. Remove Energy Planner from HACS if it was installed through HACS.
4. Restart Home Assistant if Home Assistant asks for a restart.

Deleting the integration entry removes Energy Planner's stored internal history.
It does not remove your original source entities, helpers, dashboards or
automations.

## More Documentation

- [Detailed configuration](docs/configuration.md)
- [All created entities](docs/entities.md)
- [Dashboard examples](docs/dashboard.md)
- [Automation examples](docs/automations.md)
- [How the history model works](docs/history.md)
- [Planner details](docs/planner.md)
