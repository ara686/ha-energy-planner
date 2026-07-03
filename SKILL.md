# SKILL.md

## Domain knowledge

This integration models a home energy system with:

- PV production forecast, primarily from Solcast.
- Home consumption history in kWh/hour.
- Managed loads that can be excluded from base consumption:
  - DHW heating
  - pool pump
  - pool heating
  - air conditioning
- Battery SoC and capacity.
- Low tariff / high tariff windows.
- Optional grid battery charging window.
- EV free capacity planning.

## Core concepts

### Managed power

Managed loads are loads intentionally controlled by automations. They should not pollute the baseline house consumption model.

Base consumption:

```text
base_home_kwh = max(home_kwh - managed_kwh, 0)
```

### NT/VT

NT means low tariff. In NT the planner prefers using grid for household load and preserving battery for VT.

VT means high tariff. In VT the planner assumes the battery should cover the house load down to physical battery minimum.

### lock_soc

Battery SoC that should be protected in NT so the house can survive the next VT period until PV starts covering load.

### charge_to_soc

Target SoC for optional grid charging inside the configured charge window.

### safe_discharge_soc

Lowest current SoC that can be allowed while still avoiding VT grid import according to the model.

### unused_surplus_kwh

PV energy that cannot be stored because the battery reaches 100%.
