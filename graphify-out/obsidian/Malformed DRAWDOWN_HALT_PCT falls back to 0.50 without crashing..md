---
source_file: "tests/test_debug_fixes.py"
type: "rationale"
community: "Module: tests"
location: "L163"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Module_tests
---

# Malformed DRAWDOWN_HALT_PCT falls back to 0.50 without crashing.

## Connections
- [[.test_bad_drawdown_env_var_uses_default()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Module_tests