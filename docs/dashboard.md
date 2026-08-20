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
and `soc_percent`. The attribute payload is compacted for Home Assistant's
recorder, so the graph points may use a lower resolution than the internal
planner calculation.

## Future Unused PV Surplus With ApexCharts

Each forecast point also contains `unused_surplus_kwh`, which is the passive
forecast surplus energy for that graph interval. The example below converts the
interval energy to an equivalent power value in `kW`.

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
- `base_kwh`: `home_kwh - managed_kwh`, clamped to zero
- `base_usable`: whether the bucket is valid for the baseline consumption
  profile used by the forecast

Per-source managed consumption is exposed by the separate
`sensor.energy_planner_managed_<source>_history` entities.

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

## Human-Readable Managed-Load Plans

The cards below use only Home Assistant's built-in Markdown card. They are
read-only explanations of the plan; they do not control a water heater, vehicle
or charger. Replace every example entity ID with the actual ID shown under
**Settings > Devices & services > Energy Planner > Entities**.

All timestamps are converted to the Home Assistant local time zone. A
`timeline` item contains stable English fields: `start`, `end`, `mode` and
`energy_kwh`. Hot-water and solar-only EV allocations use the `solar` mode;
deadline-aware EV plans can additionally use `home_battery`,
`grid_low_tariff` and `grid_high_tariff`.

### Hot-Water Plan — Czech

```yaml
type: markdown
title: Plán ohřevu TUV
entity_id: sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow
content: |
  {% set entity = 'sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow' %}
  {% set available = states(entity) not in ['unknown', 'unavailable'] %}
  {% set complete = state_attr(entity, 'forecast_complete') == true %}
  {% set energy = states(entity) | float(0) %}
  {% set shortfall = state_attr(entity, 'minimum_shortfall_kwh') | float(0) %}
  {% set current = state_attr(entity, 'average_temperature') | float(0) %}
  {% set target = state_attr(entity, 'planned_target_temperature') | float(0) %}
  {% set maximum = state_attr(entity, 'maximum_temperature') | float(0) %}
  {% set capacity = state_attr(entity, 'maximum_capacity_kwh') | float(0) %}
  {% set surplus = state_attr(entity, 'available_surplus_kwh') | float(0) %}
  {% set timeline = state_attr(entity, 'timeline') or [] %}

  {% if not available or not complete %}
  ⚠️ **Spolehlivý plán zatím není k dispozici.** Zkontrolujte předpověď a vstupní teploty.
  {% elif shortfall > 0.01 %}
  ⚠️ Solární přebytek nestačí ani na minimální teplotu. Chybí přibližně **{{ shortfall | round(1) }} kWh**.
  {% elif energy <= 0.01 and capacity <= 0.01 %}
  ✅ Další ohřev není potřeba. Průměrná teplota je **{{ current | round(1) }} °C**.
  {% elif energy <= 0.01 %}
  Zítra není naplánovaný solární ohřev. Aktuální průměrná teplota je **{{ current | round(1) }} °C**.
  {% elif target >= maximum - 0.1 %}
  ☀️ Je k dispozici dost solárního přebytku. Zásobník se může ohřát na maximum **{{ maximum | round(1) }} °C**; plán počítá s **{{ energy | round(1) }} kWh** z dostupných {{ surplus | round(1) }} kWh.
  {% else %}
  ☀️ Solární přebytek pokryje částečný ohřev na přibližně **{{ target | round(1) }} °C**. Plánovaná energie je **{{ energy | round(1) }} kWh**.
  {% endif %}

  {% if timeline %}
  **Časový plán**
  {% for window in timeline %}
  - {{ (as_datetime(window['start']) | as_local).strftime('%H:%M') }}–{{ (as_datetime(window['end']) | as_local).strftime('%H:%M') }} · solární přebytek · {{ window['energy_kwh'] | round(1) }} kWh
  {% endfor %}
  {% endif %}
```

### Hot-Water Plan — English

```yaml
type: markdown
title: Hot-water plan
entity_id: sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow
content: |
  {% set entity = 'sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow' %}
  {% set available = states(entity) not in ['unknown', 'unavailable'] %}
  {% set complete = state_attr(entity, 'forecast_complete') == true %}
  {% set energy = states(entity) | float(0) %}
  {% set shortfall = state_attr(entity, 'minimum_shortfall_kwh') | float(0) %}
  {% set current = state_attr(entity, 'average_temperature') | float(0) %}
  {% set target = state_attr(entity, 'planned_target_temperature') | float(0) %}
  {% set maximum = state_attr(entity, 'maximum_temperature') | float(0) %}
  {% set capacity = state_attr(entity, 'maximum_capacity_kwh') | float(0) %}
  {% set surplus = state_attr(entity, 'available_surplus_kwh') | float(0) %}
  {% set timeline = state_attr(entity, 'timeline') or [] %}

  {% if not available or not complete %}
  ⚠️ **A reliable plan is not available yet.** Check the forecast and temperature inputs.
  {% elif shortfall > 0.01 %}
  ⚠️ The solar surplus cannot reach the minimum temperature. About **{{ shortfall | round(1) }} kWh** is missing.
  {% elif energy <= 0.01 and capacity <= 0.01 %}
  ✅ No additional heating is needed. The average temperature is **{{ current | round(1) }} °C**.
  {% elif energy <= 0.01 %}
  No solar water heating is scheduled tomorrow. The current average temperature is **{{ current | round(1) }} °C**.
  {% elif target >= maximum - 0.1 %}
  ☀️ Enough solar surplus is available to heat the tank to its **{{ maximum | round(1) }} °C** maximum. The plan uses **{{ energy | round(1) }} kWh** of {{ surplus | round(1) }} kWh available.
  {% else %}
  ☀️ The solar surplus supports partial heating to about **{{ target | round(1) }} °C** using **{{ energy | round(1) }} kWh**.
  {% endif %}

  {% if timeline %}
  **Timeline**
  {% for window in timeline %}
  - {{ (as_datetime(window['start']) | as_local).strftime('%H:%M') }}–{{ (as_datetime(window['end']) | as_local).strftime('%H:%M') }} · solar surplus · {{ window['energy_kwh'] | round(1) }} kWh
  {% endfor %}
  {% endif %}
```

### EV Plan — Czech

This card automatically prefers the deadline-aware plan. When that strategy is
not active, it shows the solar-only recommendations for today and tomorrow.

```yaml
type: markdown
title: Plán nabíjení EV
entity_id:
  - sensor.energy_planner_managed_ev_charging_energy_planned_until_departure
  - sensor.energy_planner_managed_ev_charging_energy_suggested_today
  - sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow
content: |
  {% set deadline = 'sensor.energy_planner_managed_ev_charging_energy_planned_until_departure' %}
  {% set today = 'sensor.energy_planner_managed_ev_charging_energy_suggested_today' %}
  {% set tomorrow = 'sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow' %}
  {% set deadline_plan = states(deadline) not in ['unknown', 'unavailable'] and state_attr(deadline, 'departure') != none %}

  {% if deadline_plan %}
    {% set planned = states(deadline) | float(0) %}
    {% set required = state_attr(deadline, 'required_input_kwh') | float(0) %}
    {% set solar = state_attr(deadline, 'solar_kwh') | float(0) %}
    {% set battery = state_attr(deadline, 'home_battery_kwh') | float(0) %}
    {% set nt = state_attr(deadline, 'grid_low_tariff_kwh') | float(0) %}
    {% set grid = state_attr(deadline, 'grid_high_tariff_kwh') | float(0) %}
    {% set shortfall = state_attr(deadline, 'shortfall_kwh') | float(0) %}
    {% set departure = as_datetime(state_attr(deadline, 'departure')) | as_local %}
    {% set timeline = state_attr(deadline, 'timeline') or [] %}
    {% if state_attr(deadline, 'forecast_complete') != true %}
  ⚠️ Předpověď nepokrývá celé období do návratu auta; plán může být neúplný.
    {% endif %}
    {% if required <= 0.01 %}
  ✅ Požadavek je splněný; před odjezdem v **{{ departure.strftime('%H:%M') }}** není potřeba další nabíjení.
    {% elif shortfall > 0.01 %}
  ⚠️ Do odjezdu v **{{ departure.strftime('%H:%M') }}** je naplánováno **{{ planned | round(1) }} kWh**, ale stále chybí **{{ shortfall | round(1) }} kWh**.
    {% else %}
  ✅ Do odjezdu v **{{ departure.strftime('%H:%M') }}** je naplánováno požadovaných **{{ planned | round(1) }} kWh**.
    {% endif %}
    {% if solar + 0.01 < required %}
  Přímý solární přebytek před odjezdem nestačí, proto plán kombinuje dostupné zdroje.
    {% endif %}
    {% if battery > 0.01 %}
  Z domácí baterie se využije **{{ battery | round(1) }} kWh**, protože planner očekává přebytek v době, kdy bude auto pryč, a baterie zůstane nad bezpečným SoC.
    {% endif %}

  **Rozpad energie:** FVE {{ solar | round(1) }} kWh · baterie {{ battery | round(1) }} kWh · NT {{ nt | round(1) }} kWh · síť mimo NT {{ grid | round(1) }} kWh

    {% if timeline %}
  **Časový plán**
    {% for window in timeline %}
      {% set mode = window['mode'] %}
      {% if mode == 'solar' %}{% set label = 'solární přebytek' %}
      {% elif mode == 'home_battery' %}{% set label = 'domácí baterie' %}
      {% elif mode == 'grid_low_tariff' %}{% set label = 'nízký tarif' %}
      {% else %}{% set label = 'síť mimo NT' %}{% endif %}
  - {{ (as_datetime(window['start']) | as_local).strftime('%d.%m. %H:%M') }}–{{ (as_datetime(window['end']) | as_local).strftime('%H:%M') }} · {{ label }} · {{ window['energy_kwh'] | round(1) }} kWh
    {% endfor %}
    {% endif %}
  {% else %}
    {% set today_ok = states(today) not in ['unknown', 'unavailable'] and state_attr(today, 'forecast_complete') == true %}
    {% set tomorrow_ok = states(tomorrow) not in ['unknown', 'unavailable'] and state_attr(tomorrow, 'forecast_complete') == true %}
    {% if not today_ok and not tomorrow_ok %}
  ⚠️ **Spolehlivý solární plán zatím není k dispozici.** Zkontrolujte předpověď a požadovanou energii EV.
    {% else %}
      {% if not today_ok or not tomorrow_ok %}⚠️ Předpověď nepokrývá oba dny úplně; nedostupný den není do doporučení započtený.{% endif %}
  Režim pouze ze soláru doporučuje dnes **{{ states(today) | float(0) | round(1) }} kWh** a zítra **{{ states(tomorrow) | float(0) | round(1) }} kWh**.
      {% set remaining = state_attr(tomorrow, 'electrical_shortfall_kwh') | float(0) %}
      {% if remaining > 0.01 %}⚠️ Po zítřejším plánu bude stále chybět přibližně **{{ remaining | round(1) }} kWh**.{% endif %}
      {% for entity in [today, tomorrow] %}
        {% for window in state_attr(entity, 'timeline') or [] %}
  - {{ (as_datetime(window['start']) | as_local).strftime('%d.%m. %H:%M') }}–{{ (as_datetime(window['end']) | as_local).strftime('%H:%M') }} · solární přebytek · {{ window['energy_kwh'] | round(1) }} kWh
        {% endfor %}
      {% endfor %}
    {% endif %}
  {% endif %}
```

### EV Plan — English

```yaml
type: markdown
title: EV charging plan
entity_id:
  - sensor.energy_planner_managed_ev_charging_energy_planned_until_departure
  - sensor.energy_planner_managed_ev_charging_energy_suggested_today
  - sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow
content: |
  {% set deadline = 'sensor.energy_planner_managed_ev_charging_energy_planned_until_departure' %}
  {% set today = 'sensor.energy_planner_managed_ev_charging_energy_suggested_today' %}
  {% set tomorrow = 'sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow' %}
  {% set deadline_plan = states(deadline) not in ['unknown', 'unavailable'] and state_attr(deadline, 'departure') != none %}

  {% if deadline_plan %}
    {% set planned = states(deadline) | float(0) %}
    {% set required = state_attr(deadline, 'required_input_kwh') | float(0) %}
    {% set solar = state_attr(deadline, 'solar_kwh') | float(0) %}
    {% set battery = state_attr(deadline, 'home_battery_kwh') | float(0) %}
    {% set nt = state_attr(deadline, 'grid_low_tariff_kwh') | float(0) %}
    {% set grid = state_attr(deadline, 'grid_high_tariff_kwh') | float(0) %}
    {% set shortfall = state_attr(deadline, 'shortfall_kwh') | float(0) %}
    {% set departure = as_datetime(state_attr(deadline, 'departure')) | as_local %}
    {% set timeline = state_attr(deadline, 'timeline') or [] %}
    {% if state_attr(deadline, 'forecast_complete') != true %}
  ⚠️ The forecast does not cover the complete period through the vehicle's return; this plan may be incomplete.
    {% endif %}
    {% if required <= 0.01 %}
  ✅ The request is complete; no charging is needed before the **{{ departure.strftime('%H:%M') }}** departure.
    {% elif shortfall > 0.01 %}
  ⚠️ **{{ planned | round(1) }} kWh** is planned before the **{{ departure.strftime('%H:%M') }}** departure, but **{{ shortfall | round(1) }} kWh** is still missing.
    {% else %}
  ✅ The requested **{{ planned | round(1) }} kWh** is planned before the **{{ departure.strftime('%H:%M') }}** departure.
    {% endif %}
    {% if solar + 0.01 < required %}
  Direct solar surplus before departure is insufficient, so the plan combines available sources.
    {% endif %}
    {% if battery > 0.01 %}
  **{{ battery | round(1) }} kWh** comes from the home battery because the planner expects otherwise-unused surplus while the car is away and keeps the battery above safe SoC.
    {% endif %}

  **Energy split:** solar {{ solar | round(1) }} kWh · battery {{ battery | round(1) }} kWh · low tariff {{ nt | round(1) }} kWh · other grid {{ grid | round(1) }} kWh

    {% if timeline %}
  **Timeline**
    {% for window in timeline %}
      {% set mode = window['mode'] %}
      {% if mode == 'solar' %}{% set label = 'solar surplus' %}
      {% elif mode == 'home_battery' %}{% set label = 'home battery' %}
      {% elif mode == 'grid_low_tariff' %}{% set label = 'low tariff' %}
      {% else %}{% set label = 'grid outside low tariff' %}{% endif %}
  - {{ (as_datetime(window['start']) | as_local).strftime('%d %b %H:%M') }}–{{ (as_datetime(window['end']) | as_local).strftime('%H:%M') }} · {{ label }} · {{ window['energy_kwh'] | round(1) }} kWh
    {% endfor %}
    {% endif %}
  {% else %}
    {% set today_ok = states(today) not in ['unknown', 'unavailable'] and state_attr(today, 'forecast_complete') == true %}
    {% set tomorrow_ok = states(tomorrow) not in ['unknown', 'unavailable'] and state_attr(tomorrow, 'forecast_complete') == true %}
    {% if not today_ok and not tomorrow_ok %}
  ⚠️ **A reliable solar plan is not available yet.** Check the forecast and requested EV energy.
    {% else %}
      {% if not today_ok or not tomorrow_ok %}⚠️ The forecast does not fully cover both days; the unavailable day is omitted from the recommendation.{% endif %}
  Solar-only mode recommends **{{ states(today) | float(0) | round(1) }} kWh** today and **{{ states(tomorrow) | float(0) | round(1) }} kWh** tomorrow.
      {% set remaining = state_attr(tomorrow, 'electrical_shortfall_kwh') | float(0) %}
      {% if remaining > 0.01 %}⚠️ About **{{ remaining | round(1) }} kWh** will remain after tomorrow's plan.{% endif %}
      {% for entity in [today, tomorrow] %}
        {% for window in state_attr(entity, 'timeline') or [] %}
  - {{ (as_datetime(window['start']) | as_local).strftime('%d %b %H:%M') }}–{{ (as_datetime(window['end']) | as_local).strftime('%H:%M') }} · solar surplus · {{ window['energy_kwh'] | round(1) }} kWh
        {% endfor %}
      {% endfor %}
    {% endif %}
  {% endif %}
```

### Household Overview — Czech

```yaml
type: markdown
title: Energetický plán domácnosti
entity_id:
  - sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow
  - sensor.energy_planner_managed_ev_charging_energy_planned_until_departure
  - sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow
content: |
  {% set boiler = 'sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow' %}
  {% set ev = 'sensor.energy_planner_managed_ev_charging_energy_planned_until_departure' %}
  {% set ev_solar = 'sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow' %}
  - <ha-icon icon="mdi:water-boiler"></ha-icon> **TUV:** {% if states(boiler) in ['unknown', 'unavailable'] %}plán není dostupný{% else %}{{ states(boiler) | float(0) | round(1) }} kWh, cíl {{ state_attr(boiler, 'planned_target_temperature') | float(0) | round(1) }} °C{% endif %}
  - <ha-icon icon="mdi:car-electric"></ha-icon> **EV:** {% if states(ev) not in ['unknown', 'unavailable'] %}{{ states(ev) | float(0) | round(1) }} kWh do odjezdu{% elif states(ev_solar) not in ['unknown', 'unavailable'] %}{{ states(ev_solar) | float(0) | round(1) }} kWh ze zítřejšího přebytku{% else %}plán není dostupný{% endif %}

  Podrobné důvody a časová okna jsou v samostatných kartách TUV a EV.
```

### Household Overview — English

```yaml
type: markdown
title: Household energy plan
entity_id:
  - sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow
  - sensor.energy_planner_managed_ev_charging_energy_planned_until_departure
  - sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow
content: |
  {% set boiler = 'sensor.energy_planner_managed_water_heater_energy_suggested_tomorrow' %}
  {% set ev = 'sensor.energy_planner_managed_ev_charging_energy_planned_until_departure' %}
  {% set ev_solar = 'sensor.energy_planner_managed_ev_charging_energy_suggested_tomorrow' %}
  - <ha-icon icon="mdi:water-boiler"></ha-icon> **Hot water:** {% if states(boiler) in ['unknown', 'unavailable'] %}plan unavailable{% else %}{{ states(boiler) | float(0) | round(1) }} kWh, target {{ state_attr(boiler, 'planned_target_temperature') | float(0) | round(1) }} °C{% endif %}
  - <ha-icon icon="mdi:car-electric"></ha-icon> **EV:** {% if states(ev) not in ['unknown', 'unavailable'] %}{{ states(ev) | float(0) | round(1) }} kWh before departure{% elif states(ev_solar) not in ['unknown', 'unavailable'] %}{{ states(ev_solar) | float(0) | round(1) }} kWh from tomorrow's surplus{% else %}plan unavailable{% endif %}

  See the separate hot-water and EV cards for reasons and exact windows.
```
