---
source_file: "tests/test_paper_cross_process_lock.py"
type: "code"
community: "Community 4"
location: "L1"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Community_4
---

# test_paper_cross_process_lock.py

## Connections
- [[paper._DATA_LOCK]] - `calls` [EXTRACTED]
- [[paper._DATA_LOCK must serialise the ledger read-modify-write cycle across…]] - `rationale_for` [EXTRACTED]
- [[pytest_1]] - `imports` [EXTRACTED]
- [[subprocess]] - `imports` [EXTRACTED]
- [[sys]] - `imports` [EXTRACTED]
- [[test_p1_remaining.py]] - `semantically_similar_to` [INFERRED]
- [[test_second_process_blocks_until_first_releases()]] - `contains` [EXTRACTED]
- [[time]] - `imports` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Community_4