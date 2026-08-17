---
type: community
cohesion: 0.14
members: 21
---

# Community 151

**Cohesion:** 0.14 - loosely connected
**Members:** 21 nodes

## Members
- [[dot-_patch_paths()]] - code - tests/test_hmac_bias.py
- [[dot-test_compare_digest_used_not_equality()]] - code - tests/test_hmac_bias.py
- [[dot-test_missing_hmac_sidecar_returns_empty()]] - code - tests/test_hmac_bias.py
- [[dot-test_no_pkl_returns_empty()]] - code - tests/test_hmac_bias.py
- [[dot-test_no_secret_set_returns_empty()]] - code - tests/test_hmac_bias.py
- [[dot-test_tampered_pkl_returns_empty()]] - code - tests/test_hmac_bias.py
- [[dot-test_train_writes_hmac_sidecar()]] - code - tests/test_hmac_bias.py
- [[dot-test_valid_hmac_loads_models()]] - code - tests/test_hmac_bias.py
- [[dot-test_wrong_secret_returns_empty()]] - code - tests/test_hmac_bias.py
- [[HMAC mismatch (tampered pkl) → refuse to load, return {}.]] - rationale - tests/test_hmac_bias.py
- [[HMAC signed with different secret → mismatch → return {}.]] - rationale - tests/test_hmac_bias.py
- [[MODEL_HMAC_SECRET not set → skip loading entirely (RCE risk).]] - rationale - tests/test_hmac_bias.py
- [[Path_6]] - code
- [[TestHmacVerification]] - code - tests/test_hmac_bias.py
- [[Valid pkl + matching HMAC sidecar → models loaded successfully.]] - rationale - tests/test_hmac_bias.py
- [[Write a valid pkl + sidecar and return the raw bytes.]] - rationale - tests/test_hmac_bias.py
- [[_load_models must use hmac.compare_digest, not == for timing safety.]] - rationale - tests/test_hmac_bias.py
- [[_write_valid_pkl()]] - code - tests/test_hmac_bias.py
- [[pkl does not exist → return {} without error.]] - rationale - tests/test_hmac_bias.py
- [[pkl exists but no .hmac sidecar → refuse to load, return {}.]] - rationale - tests/test_hmac_bias.py
- [[train_bias_model must write the .hmac sidecar alongside the pkl.]] - rationale - tests/test_hmac_bias.py

## Live Query (requires Dataview plugin)

```dataview
TABLE source_file, type FROM #community/Community_151
SORT file.name ASC
```

## Connections to other communities
- 2 edges to [[_COMMUNITY_Community 41]]

## Top bridge nodes
- [[TestHmacVerification]] - degree 10, connects to 1 community
- [[_write_valid_pkl()]] - degree 7, connects to 1 community