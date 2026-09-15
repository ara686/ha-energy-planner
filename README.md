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

- Compare the planned battery path with passive and managed-load SoC forecasts.
- Decide whether the battery should be charged during a low-tariff period.
- Disable low-tariff windows entirely for installations without dual-rate
  electricity pricing.
- Disable grid-charging planning independently when the battery must not be
  charged from the grid.
- Decide whether battery discharge is currently still safe for the plan.
- Estimate unused PV surplus that can be used for flexible loads such as hot
  water, pool technology or EV charging.
- Recommend how direct PV above base house demand can be divided among typed
  managed loads before the battery is full, without increasing the planned grid
  draw. Generic loads use recent usage or a requested-energy entity; hot-water
  tanks use their current temperatures and physical parameters; electric
  vehicles use a current battery-energy request and charging-power limit.
- Build an optional deadline-aware EV plan from vehicle availability, departure
  time, PV surplus, safe home-battery energy and low/high tariff GRID slots.
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
- Battery minimum/reserve SoC entity in `%`; generic inverter `number` entities
  such as `number.inverter_battery_low_soc` are supported.
- Whole-home cumulative energy entity with a supported energy unit such as
  `kWh` or `MWh`; Energy Planner normalizes it to `kWh`.

Optional:

- Managed loads added after the shared setup as separate items. The available
  types are `generic`, `hot_water` and `electric_vehicle`; each still requires
  its own cumulative energy meter so its consumption can be removed from the
  house profile.
- A numeric requested-energy entity and optional nominal input power in `kW`
  for a `generic` load, or two temperature sensors and the tank parameters for
  a `hot_water` load. An
  `electric_vehicle` load needs the remaining battery-side energy and a fixed
  maximum charger power in `kW`; `sensor.enyaq_charge_kwh` is a typical
  template-sensor input for the energy request.
- A deadline-aware EV additionally needs a `device_tracker`, a cable-connected
  `binary_sensor`, workdays with departure/return times and an `input_boolean`
  that explicitly permits GRID charging outside low tariff.
- Optional live total, solar, home-battery and GRID power sensors let the plan
  report whether the EV is charging now and from which dominant source, without
  confusing that observed state with the advisory Wallbox recommendation.
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
- Generic history-based recommendations require at least three
  coverage-qualified completed days and use up to seven recent days. Hot-water
  and EV recommendations do not require consumption history. Their current
  model inputs and complete solar coverage must be available.

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
| `sensor.energy_planner_soc_forecast` | Planned SoC at the configured forecast horizon. It includes the planner's grid-charge target and preserves `lock_soc` during low tariff, so its attributes represent the expected controlled battery path in graphs. |
| `sensor.energy_planner_soc_forecast_passive` | Diagnostic passive SoC forecast without planned grid charging or the planner's low-tariff lock. It shows what the battery would do with only its configured physical minimum SoC. |
| `sensor.energy_planner_soc_forecast_with_managed_loads` | Planned SoC with managed loads started as soon as forecast PV covers both base house demand and their allocated energy. They may run while the battery is still charging, so this curve can be lower than the base curve and can converge again after later charging. Allocation never adds planned grid import, violates the minimum/`lock_soc` reserve, or creates evening/night windows without PV. |
| `sensor.energy_planner_soc_forecast_24h` | Planned SoC exactly 24 hours from the last calculation. |
| `binary_sensor.energy_planner_charge_now` | On when enabled grid-charging planning says charging is currently useful. |
| `binary_sensor.energy_planner_discharge_allowed` | On when the plan says battery discharge is still allowed. |
| `sensor.energy_planner_target_soc` | Target SoC used by the planner. |
| `sensor.energy_planner_charge_to_soc` | SoC level needed for planned grid charging. |
| `sensor.energy_planner_safe_discharge_soc` | Lowest SoC that should still preserve the plan. |
| `sensor.energy_planner_unused_surplus_today` | Estimated unused PV surplus for today from the passive forecast. |
| `sensor.energy_planner_unused_surplus_tomorrow` | Tomorrow's allocatable surplus. It has a value only when the complete local day and its solar input are covered. |
| `sensor.energy_planner_recommended_managed_energy_today` | Total energy recommended for all managed loads in the complete remaining slots today. Live EV and hot-water demand is combined with remaining history-based generic demand after subtracting energy already used today. It is unavailable when slot or solar coverage is incomplete. |
| `sensor.energy_planner_recommended_managed_energy_tomorrow` | Total energy recommended for all managed loads tomorrow. Its attributes include compact allocations for every complete future local day in the horizon. |
| `sensor.energy_planner_unallocated_surplus_tomorrow` | Complete tomorrow surplus remaining after all recommendations. |
| `sensor.energy_planner_managed_<source>_suggested_today` | Energy recommended today for one managed load. EV and hot-water loads use live model inputs; generic loads use their remaining history-based daily estimate. The `timeline` attribute contains only the solar slots actually allocated to that source. Typed allocations expose forecast completeness and compact per-source details. |
| `sensor.energy_planner_managed_<source>_suggested_tomorrow` | Recommended energy for one managed load. Hot-water attributes include the planned target temperature and its solar timeline; EV attributes include battery/electrical demand, shortfall and its solar timeline. |
| `sensor.energy_planner_managed_<source>_charging_mode` | Current advisory EV action such as `connect_vehicle`, `solar`, `home_battery`, `grid_low_tariff`, `shortfall` or `complete`. |
| `sensor.energy_planner_managed_<source>_recommended_wallbox_mode` | Optional enum containing the exact configured `input_select` option recommended now. Attributes expose the planner mode and the next wallbox option with its time window. |
| `sensor.energy_planner_managed_<source>_next_departure` | Next configured local departure used as the EV deadline. |
| `sensor.energy_planner_managed_<source>_planned_until_departure` | Charger-input energy planned before departure. Attributes contain the source split, shortfall, reason, next action, solar-if-home result and compact timeline. |
| `sensor.energy_planner_managed_<source>_today` | Energy used today by one managed load, for example EV charging or water heating. |
| `sensor.energy_planner_managed_<source>_tracked_total` | Energy Planner's tracked total for one managed load. |

See [all created entities](docs/entities.md) for the complete list.

Managed allocation attributes keep the legacy passive-curtailment values
`available_surplus_kwh` and `unallocated_surplus_kwh`. The separate
`available_direct_solar_kwh`, `scheduled_managed_kwh`,
`unallocated_direct_solar_kwh` and `reserve_limited_kwh` values show the PV
headroom above base house demand, energy actually scheduled, headroom left, and
energy withheld to protect the later battery/grid plan. A generic load without
`nominal_power_kw` remains supported, but diagnostics warn that its per-slot
power cannot be verified.

## Dashboards

Start with these dashboard ideas:

- Future SoC chart from `sensor.energy_planner_soc_forecast`.
- Comparison chart using `sensor.energy_planner_soc_forecast` and
  `sensor.energy_planner_soc_forecast_with_managed_loads`, with aggregate
  planned managed power so surplus-only loads remain visible.
- 24 hour SoC gauge from `sensor.energy_planner_soc_forecast_24h`.
- Unused PV surplus chart.
- Home vs managed consumption history chart.
- Per-load managed consumption chart, for example EV charging and water heating
  in separate series.
- Read-only hot-water and EV plan cards with a human summary, exact time windows
  and a combined household overview.

Lovelace and ApexCharts examples live in [dashboard examples](docs/dashboard.md).
Screenshots can be added there later without making this README too long.

## Automation Ideas

Energy Planner does not operate devices directly, but it provides simple signals
for automations:

- Use `binary_sensor.energy_planner_charge_now` to allow grid charging.
- Use `binary_sensor.energy_planner_discharge_allowed` to allow battery
  discharge.
- Use each load's solar `timeline` to start it when direct PV is available;
  `unused_surplus_today` remains a passive curtailment diagnostic.
- Use each `managed_<source>_suggested_tomorrow` value as an input to your own
  next-day automation; Energy Planner still does not switch the device itself.
- Use each load's `managed_<source>_suggested_today` as its solar-only budget
  for the remaining complete planner slots today.
- Configure a deadline-aware EV's optional Wallbox mode selector and let an
  automation copy `managed_<source>_recommended_wallbox_mode` to it. Keep phase,
  current and overload protection in the Wallbox's own safety logic.
- Use per-load managed sensors to prioritize loads, for example heat water
  before allowing EV charging.

Example automations with placeholders are in
[automation examples](docs/automations.md). Always test automations manually in
your own Home Assistant before letting them control real devices.

Grid-charging planning can be disabled independently in the integration
options. When disabled, the planned grid-charging window is ignored,
`binary_sensor.energy_planner_charge_now` stays off and no grid charging is
included in plan-specific simulations.

## Manual Recalculation

Energy Planner recalculates automatically at the configured update interval,
which defaults to 60 minutes and acts as a forecast refresh and safety fallback.
For deadline-aware EV plans, it also schedules a one-time recalculation at every
planned mode start and end, so advisory transitions do not wait for the periodic
interval. A changed EV energy request, location, cable or GRID permission
triggers a recalculation after a 10-second debounce; battery SoC and cumulative
energy-source changes retain their 60-second debounce.

Deadline-aware EV actions use permission windows with a minimum resolution of
10 minutes while the underlying SoC forecast keeps its configured finer
resolution. If the configured planning interval is not compatible with 10
minutes, Energy Planner uses the smallest compatible interval, for example 15
minutes becomes a 30-minute EV action window. A window permits its advisory
mode; it does not require maximum charger power for the complete window. The
planned energy can therefore be lower than the window's maximum capacity, and a
request reaching zero ends the recommendation early after the input refresh.
The `planned_until_departure` attributes expose the effective resolution as
`action_window_minutes`.

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
- An unavailable hot-water temperature sensor withholds only that tank's
  recommendation. Energy Planner never falls back to consumption history for a
  `hot_water` load.
- An unavailable EV energy request or an invalid maximum charger power
  withholds only that vehicle's recommendation. An `electric_vehicle` load
  never falls back to consumption history. `solar_only` never plans grid
  charging; `deadline_aware` reports GRID only as an advisory decision.
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

### Alternative energy sources when solar is insufficient

In the integration's **Configure / Options** form, select each EV under
**EVs that must not use the home battery** (`ev_home_battery_disabled_sources`)
and each tank with gas backup under **Hot-water tanks with gas backup**
(`hot_water_gas_sources`). Both lists default to empty, preserving existing behavior.
For EV charging from solar and low tariff only, also select `deadline_aware`
with departure, presence and cable inputs in the EV configuration, and leave
permission for grid outside NT disabled. The home battery remains available to
supply the house; this option prevents allocating it to EV charging.

The EV plan assigns actual solar surplus first, then missing energy to NT windows
before departure. `wait_for_charging` means a future non-solar charging window;
`next_action_mode`, `next_action_start` and `next_action_end` identify it.
`wait_for_solar` applies only to a future solar window. Insufficient charging
capacity is still reported as a shortfall. Observed charging remains separate
from the recommendation, even when it uses a disallowed source.

For gas-backed water heating, `alternative_source: gas` and
`alternative_heating_recommended: true` indicate that planned solar cannot reach
the minimum temperature. Gas does not top up the optional maximum target.
`minimum_shortfall_kwh` remains an **electrical-equivalent deficit**, not gas
consumption. Gas is not added to electrical demand or forecast tank temperature;
the existing controller decides when to heat. With incomplete forecasts the
recommendation is `null`, not a confirmed gas requirement. No devices are controlled.

## Joint energy plan: shadow comparison

The joint planner reserves the house battery's energy for high-tariff periods
before allocating energy to hot water and EV charging. It considers **all NT
windows**, retains the seasonal minimum SoC, and reports an EV shortfall when
available NT power cannot meet both the house reserve and the departure request.
It uses the expected consumption profile without the compatibility planner's
percentage margins; the configured SoC reserve remains in place.

The default `joint_planning_mode: shadow` keeps the existing recommendation
entities on the compatibility calculation. New diagnostic sensors **Joint target
SoC** and **Joint forecast grid import**, plus `joint_plan` and `joint_comparison`
in downloaded diagnostics, expose the candidate plan. Both calculations read one
snapshot of HA states and history. Diagnostics identify the consumption-policy
difference; actual operation under another controller is not a replay of either
candidate. Computation runs in an executor; boundaries trigger a new calculation.

The Options Flow can explicitly select `advisory` to publish joint recommendations
through the existing entity IDs. This switches battery forecasts and managed-load
recommendations together. It does not operate devices. `charge_now` refers to the
current scheduled interval, `charge_to_soc` to its immediate target, and
`target_soc` to the next NT window's required exit target. The full per-window
schedule and recommendation validity are in diagnostics. Keep existing device
protections and manual overrides in the external controller.

Joint-planner options include:

- Separate solar and other EV phase counts (defaults 1 and 3), nominal phase
  voltage (230 V), and current range (6–16 A). Match these to the external
  wallbox modes. The planner limits power and merges mixed-source charging into
  one command per interval; the controller handles switching and anti-cycling.
- Optional **power entities in W or kW** for shared grid import, battery charge
  and discharge on the AC side, export, and per-phase load limits. Use the
  installation's actual limits. An AC input-current setting in A or a BMS DC
  current limit cannot be entered as a power entity without a correct conversion.
  The export limit is read, never changed. Battery charging and discharging
  efficiencies are applied once, at the AC/DC boundary.
- Water targets of 40 °C minimum by 17:00, 45 °C normal, and 65 °C maximum,
  using the average of both configured tank sensors. Optional heating cannot
  increase grid purchases or consume the house reserve. With gas backup selected,
  gas is recommended only for the remaining comfort deficit. Its quantity is
  **thermal energy**, not metered gas consumption, and is excluded from the
  electrical ledger. The temperature forecast assumes recommended actions occur.
- Optional tank heat loss in kW and daily water draw in thermal kWh. These are
  estimates; absent values are explicitly marked unverified. The current deficit
  is carried through the horizon, not copied into every future day. Water policy
  and EV electrical settings currently apply to all respective configured loads.

Unknown technical limits and missing thermal data are visible in diagnostics.
Phase loading currently uses an equal-distribution estimate; **the forecast is
not verification of each phase's physical capacity**. Invalid configured limit
entities make joint recommendations unavailable in advisory mode. Missing managed
meter readings are not treated as measured zero consumption; partial gaps are
filled per hour from available stored observations. These limitations must be
resolved or covered by the external controller before relying on automatic control.

The Enyaq request-helper correction preserves its entity ID: valid percentages
produce `max(0, (target - current) * capacity / 100)`, rounded after multiplication;
invalid percentages make the helper unavailable. Charger efficiency belongs to
the planner, not to this battery-energy request. See
[HA template availability](https://www.home-assistant.io/integrations/template/#common-device-configuration-options).
