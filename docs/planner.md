# Planner

Pure planner core. No Home Assistant imports allowed.

The planner receives normalized input models from the Home Assistant coordinator.
It must not read Home Assistant state directly and must not call Solcast or device APIs.

The planner must simulate battery SoC for at least 24 hours and for the configured
`forecast_horizon_hours` when that horizon is longer. PV input comes from Solcast
forecast data already collected by Home Assistant. Load input comes from the
integration history model built from Home Assistant energy entities.

Solcast `pv_estimate` values are normalized by the Home Assistant source parser
from kW to kWh using the forecast period length. The pure planner only receives
PV energy per period.

The SoC forecast output is a compact time series. Each point contains:

- timestamp
- predicted SoC percent
- predicted battery kWh

The result must always include the +24 hour SoC point when enough input data is
available, even if the full forecast horizon is longer.
