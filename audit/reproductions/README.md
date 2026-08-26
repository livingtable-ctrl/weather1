# `audit/reproductions/`

One-off scripts that reproduce a bug, or verify a fix, outside the test suite.

## The rule

Every script here starts with `isolate()`, above every repo import, and is run
as a module from the repo root:

```python
from audit.reproductions._isolate import isolate

isolate()

import cron  # everything below is bound to a sandbox data/
```

```bash
python -m audit.reproductions.<script_name>
```

## Why

Two guards protect the test suite — `3cca1e8e` default-denies outbound network
for every test, and `27949ffa` blocks any test write to the real `data/`. Both
hook pytest. **A script run directly loads neither**, so it inherits the real
`project_root()`, the real `data/`, and unrestricted network. The guards
therefore cover the test runner — the least dangerous caller — and nothing
else.

This is not hypothetical:

- On 2026-08-26, four commands were run against the real `data/predictions.db`
  from an ordinary shell. One of them, `py main.py validate`, **applied schema
  migrations v77 and v78 to the production database** purely as a side effect
  of being run.
- Earlier, a `MagicMock` repr was persisted into `data/miami_index_state.json`
  as a stored `config_version`. The next real cron cycle read it back and fired
  a red "Miami settlement methodology may have changed" operator alert — and
  overwrote the baseline the guard diffs against. Three separate sessions could
  not attribute it, because nothing outside pytest records who writes `data/`.

Importing a production module is enough on its own. `import main` pulls in
`paths.py`, which resolves `DATA_DIR` at import time and then calls
`materialize_missing_seeds()`. Measured with the guard armed against the real
directory, a bare `import main` from a plain script attempts:

```
open(mode='wb')  <repo>/data/.city_weights.json.seed-<pid>.tmp
Path.unlink      <repo>/data/.city_weights.json.seed-<pid>.tmp
```

No script body required. That is the whole vector.

## The two modes

`isolate()` redirects `safe_io.project_root()` to a fresh temp directory, so
every `paths.py` constant resolves inside it, and arms the production-data
guard in **BLOCK** mode against the *real* `data/` so anything still reaching
it raises at the call site.

`isolate(allow_real_data=True)` is the deliberate override for a script whose
purpose *is* to read or repair live state. It redirects nothing and arms the
guard in **AUDIT** mode instead: every real mutation is printed with the script
and pid that made it.

The override has to exist. Writing `data/` from outside pytest is **correct**
for the ~70 `main.py` operator subcommands — `repair-metar-lockout-rows`,
`backfill-attempt-outcomes` and `backfill-ensemble-var` all did so
deliberately during that same session. A guard built on "no out-of-pytest
write to `data/`" would break the maintenance tooling it exists to protect.
The defect is narrower: code touching the real data dir with nobody able to
say which code. AUDIT mode buys that attribution.

## What `isolate()` does not do

It does not block network. The default-deny guard is a pytest fixture in
`tests/conftest.py`, not a reusable module, so there is nothing to arm here
without extracting it first. A script that must not reach the network still
has to mock its own callers.

## Calling it too late

`isolate()` raises if `paths` or `safe_io` is already imported. `paths.py`
computes every constant from `project_root()` at import time, so a redirect
after that point cannot reach them — and a silent no-op there is exactly the
failure this harness exists to prevent.

## Older scripts

Most scripts here predate this convention and still open with

```python
sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")
```

That worktree no longer exists, so the line is inert — those scripts work only
because they are run from the repo root, and they are unisolated when they do.
They are migrated opportunistically rather than in bulk, because whether a
given one needs `allow_real_data=True` is a per-script judgement. See
`backlog.txt`, "audit/reproductions/ SCRIPTS RUN OUTSIDE PYTEST".
`repro_target_date_due.py` is the migrated worked example.
