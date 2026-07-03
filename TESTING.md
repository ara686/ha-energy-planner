# Testing Requirements

## Planner tests

Cover:

- normal sunny day
- bad solar day
- full battery
- empty battery
- battery below minimum SoC
- NT across midnight
- multiple NT windows
- charge window across midnight
- no Solcast data
- no price entity
- managed load subtraction
- history correction
- partial current hour
- forecast horizon boundary
- SoC forecast for exactly 24 hours
- SoC forecast for a horizon longer than 24 hours
- SoC forecast uses Solcast data from HA entity attributes
- lock_soc calculation
- charge_to_soc binary search
- safe_discharge_soc
- unused surplus calculation

## Config flow tests

Cover:

- successful setup
- duplicate setup prevention
- invalid entity selection
- default options
- option update

## Coordinator tests

Cover:

- unavailable entities
- unknown states
- invalid numeric states
- malformed Solcast forecast attributes
- missing optional Solcast forecast entities
- recovery after invalid state
- update interval

## Sensor tests

Cover:

- all entities created
- units and device classes
- state mapping
- attributes
- SoC forecast attributes stay compact
- unavailable state

## History tests

Cover:

- storage load/save
- hourly aggregation
- retention cleanup
- restart persistence
- managed energy subtraction

## Diagnostics tests

Cover:

- redaction if needed
- config summary
- options summary
- history status
- last warnings

## Legacy Node-RED parity tests

Use local `nodered_export.json` only as a reference source.

Rules:
- keep `nodered_export.json` ignored and out of GitHub
- use only the active flow path that reaches Home Assistant outputs
- ignore backup, archive, dated and disconnected Node-RED branches
- do not copy raw Node-RED code into the integration
- create sanitized parity fixtures or assertions only from understood behavior
