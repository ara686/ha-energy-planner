# Dashboard Examples

These examples assume default entity IDs. If Home Assistant created localized,
renamed or suffixed entities, adjust the IDs.

Screenshots can be added here later, for example:

- overview dashboard with SoC forecast and target values
- unused PV surplus chart
- home vs managed consumption history
- per-source managed load chart, for example EV charging vs water heating
- simple mobile dashboard tile set

## Future SoC Forecast With ApexCharts

Install `apexcharts-card` through HACS, then add a manual card:

<img width="513" height="362" alt="image" src="https://github.com/user-attachments/assets/7f141e6a-2667-46bd-a696-6f74fcbf405e" />


```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: hour
locale: en
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
    name: Forecast SoC
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

The important part is `entity.attributes.points`. Each point uses `timestamp`
and `soc_percent`.

## Future Unused PV Surplus With ApexCharts

Each forecast point also contains `unused_surplus_kwh`, which is the passive
forecast surplus energy for that planner slot. The example below converts slot
energy to an equivalent power value in `kW`.

<img width="518" height="374" alt="image" src="https://github.com/user-attachments/assets/8eea7ce6-5777-481b-a942-4c4f68c3df96" />


```yaml
type: custom:apexcharts-card
graph_span: 24h
span:
  start: hour
locale: en
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

## Single 24 Hour SoC Value

```yaml
type: gauge
entity: sensor.energy_planner_soc_forecast_24h
name: SoC in 24 hours
min: 0
max: 100
severity:
  green: 50
  yellow: 25
  red: 0
```

## Consumption History With ApexCharts

The `sensor.energy_planner_consumption_history` state is the latest hourly base
consumption bucket in `kWh`. Its `points` attribute contains the hourly history
used by the planner:

- `home_kwh`: whole-home consumption in the hour
- `managed_kwh`: intentionally managed consumption in the hour
- `managed_sources`: intentionally managed consumption split by configured
  source entity
- `base_kwh`: `home_kwh - managed_kwh`, clamped to zero

<img width="511" height="376" alt="image" src="https://github.com/user-attachments/assets/5623fb02-e79d-414b-880b-3766257bacc1" />


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

## Per-Source Managed Load History With ApexCharts

Energy Planner creates one disabled-by-default history entity for every
configured managed source. Enable the relevant entities in **Settings > Devices
& services > Energy Planner > Entities** before using this card.

The example below assumes Home Assistant created these entity IDs:

- `sensor.energy_planner_managed_ev_charging_energy_history`
- `sensor.energy_planner_managed_water_heater_energy_history`

Adjust them to match your actual entity IDs.

```yaml
type: custom:apexcharts-card
graph_span: 3d
span:
  end: hour
locale: en
header:
  title: Managed load history
  show: true
yaxis:
  - min: 0
    decimals: 2
series:
  - entity: sensor.energy_planner_managed_ev_charging_energy_history
    name: EV charging
    type: column
    unit: kWh
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.managed_kwh ?? 0),
      ]);
  - entity: sensor.energy_planner_managed_water_heater_energy_history
    name: Water heating
    type: column
    unit: kWh
    data_generator: |
      const points = entity.attributes.points || [];
      return points.map((point) => [
        new Date(point.timestamp).getTime(),
        Number(point.managed_kwh ?? 0),
      ]);
```

For simple cards and automation conditions, use the enabled summary entities
instead, for example:

- `sensor.energy_planner_managed_ev_charging_energy_today`
- `sensor.energy_planner_managed_ev_charging_energy_current_hour`
- `sensor.energy_planner_managed_ev_charging_energy_last_hour`
- `sensor.energy_planner_managed_ev_charging_energy_tracked_total`

## Home And Managed Power History With ApexCharts

This chart converts hourly energy buckets to average power. For hourly buckets,
`kWh / 1 h` is the average `kW`.

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
