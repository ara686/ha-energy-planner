# History

Energy Planner keeps its own storage-backed hourly consumption history.

The configured home consumption source is expected to be an hourly
utility-meter-like entity whose state is cumulative kWh for the current hour. On
each planner refresh the integration stores only the delta since the previous
reading in the same hour. When the utility meter resets for a new hour, a new
history bucket is started.

The optional managed consumption source is handled the same way and is subtracted
from home consumption before the baseline profile is used for future SoC
prediction.

The planner does not require Home Assistant recorder internals and does not
backfill old recorder data in v1. A fresh install starts with the configured
minimum baseline until at least one completed hourly bucket has been collected.
