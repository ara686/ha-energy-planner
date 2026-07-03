# Architecture

## Modules

```text
custom_components/energy_planner/
  __init__.py
  manifest.json
  const.py
  config_flow.py
  coordinator.py
  diagnostics.py
  history.py
  models.py
  planner.py
  sensor.py
  services.yaml
  strings.json
  translations/
```

## Separation

### Pure planner layer

Files:
- `planner.py`
- `models.py`

Rules:
- no Home Assistant imports
- deterministic
- fully unit tested
- accepts explicit time input for tests

### Home Assistant layer

Files:
- `__init__.py`
- `config_flow.py`
- `coordinator.py`
- `sensor.py`
- `diagnostics.py`

Responsibilities:
- read entity states
- parse options
- manage coordinator updates
- expose sensors
- diagnostics
- services

### History layer

File:
- `history.py`

Responsibilities:
- maintain hourly kWh buckets
- persist to HA storage
- cleanup by retention
- provide base consumption model
