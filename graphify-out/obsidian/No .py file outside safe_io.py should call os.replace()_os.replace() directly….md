---
source_file: "tests/test_bare_os_replace_guard.py"
type: "rationale"
community: "Backtest Engine & Atomic Writes"
location: "L109"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Backtest_Engine__Atomic_Writes
---

# No *.py file outside safe_io.py should call os.replace()/_os.replace() directly…

## Connections
- [[test_no_new_bare_os_replace_sites()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Backtest_Engine__Atomic_Writes