# Automation Examples

Energy Planner does not control devices directly. These examples show how to use
its entities as inputs for your own automations.

Replace all placeholder entities such as `switch.your_inverter_grid_charge` with
real entities from your Home Assistant installation. Test every automation
manually before using it with real equipment.

## Allow Grid Charging When The Plan Requests It

```yaml
alias: Energy Planner - allow grid charging
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.energy_planner_charge_now
    to: "on"
conditions:
  - condition: state
    entity_id: binary_sensor.energy_planner_charge_now
    state: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.your_inverter_grid_charge
```

Optional companion automation to turn charging off when the planner no longer
requests it:

```yaml
alias: Energy Planner - stop grid charging
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.energy_planner_charge_now
    to: "off"
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.your_inverter_grid_charge
```

## Allow Battery Discharge Only When The Plan Allows It

This example uses an `input_boolean` as an intermediate helper. Your inverter
automation can then use this helper as a condition.

```yaml
alias: Energy Planner - mirror discharge permission
mode: restart
triggers:
  - trigger: state
    entity_id: binary_sensor.energy_planner_discharge_allowed
actions:
  - choose:
      - conditions:
          - condition: state
            entity_id: binary_sensor.energy_planner_discharge_allowed
            state: "on"
        sequence:
          - action: input_boolean.turn_on
            target:
              entity_id: input_boolean.battery_discharge_allowed
    default:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.battery_discharge_allowed
```

## Start A Flexible Load From Predicted PV Surplus

This example starts a water heater when the forecasted unused PV surplus for
today is above a threshold. Tune the threshold for your own device.

```yaml
alias: Energy Planner - use PV surplus for water heater
mode: single
triggers:
  - trigger: numeric_state
    entity_id: sensor.energy_planner_unused_surplus_today
    above: 2.5
conditions:
  - condition: state
    entity_id: binary_sensor.energy_planner_discharge_allowed
    state: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.your_water_heater
```

## Prioritize Water Heating Before EV Charging

This example allows EV charging from PV surplus only after the water heater has
already consumed at least a minimum amount today. Replace the managed entity IDs
with the IDs created in your Home Assistant.

```yaml
alias: Energy Planner - allow EV after water heating
mode: single
triggers:
  - trigger: numeric_state
    entity_id: sensor.energy_planner_unused_surplus_today
    above: 5
conditions:
  - condition: numeric_state
    entity_id: sensor.energy_planner_managed_water_heater_energy_today
    above: 2
  - condition: numeric_state
    entity_id: sensor.energy_planner_managed_ev_charging_energy_today
    below: 20
  - condition: state
    entity_id: binary_sensor.energy_planner_discharge_allowed
    state: "on"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.your_ev_charger_enable
```

The same pattern can be used for pool technology, boilers or other controlled
loads. Use `*_last_hour` when an automation should react only to a completed
hour, not the still-changing current hour.

## Send A Notification When The 24h Forecast Is Low

```yaml
alias: Energy Planner - low 24h SoC notification
mode: single
triggers:
  - trigger: numeric_state
    entity_id: sensor.energy_planner_soc_forecast_24h
    below: 25
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: Battery forecast is low
      message: >
        Energy Planner expects the battery to be below 25% in 24 hours.
```

## Force A Recalculation Before A Larger Decision

```yaml
alias: Energy Planner - recalculate before evening decisions
mode: single
triggers:
  - trigger: time
    at: "21:45:00"
actions:
  - action: energy_planner.recalculate
```
