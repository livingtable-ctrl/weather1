---
source_file: "system_health.py"
type: "rationale"
community: "Module: frosty"
location: "L68"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_frosty
---

# Return unhealthy if any loaded Platt model has A <= 0 (signal inversion).

## Connections
- [[_check_platt_sanity()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_frosty