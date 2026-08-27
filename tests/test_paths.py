"""Tests for paths.py's first-run seed materialization (batch-79 item 2).

Five learned-calibration files used to be force-tracked inside the gitignored
``data/`` directory so a fresh clone had a starting point. The cost was that a
routine ``git restore .`` or ``git checkout -- data/`` reverted live, learned
calibration to the committed values -- silently, with nothing downstream
noticing. The fresh-clone copies now live in ``seeds/`` and are applied only
when ``data/`` does not already have the file.

Two properties matter and are tested separately:
  * seeds are applied on a fresh clone (otherwise untracking broke first run);
  * seeds NEVER overwrite an existing file (otherwise the fix would itself
    become a new way to lose calibration, on every single process start).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import paths

# Deliberately NOT paths.SEEDS_DIR. That resolves through
# safe_io.project_root(), which returns the MAIN CLONE even when running from
# a worktree -- so at runtime the seeds actually read are the main clone's,
# while the ones under review here are this checkout's. The two coincide in
# the main clone. TestImportTimeMaterialization covers the runtime path
# separately by redirecting project_root() in a child, so a typo in
# SEEDS_DIR's basename still fails a test.
_REPO_ROOT = Path(paths.__file__).resolve().parent


class TestMaterializeMissingSeeds:
    def test_copies_a_seed_whose_data_counterpart_is_absent(self, tmp_path):
        seeds, data = tmp_path / "seeds", tmp_path / "data"
        seeds.mkdir()
        data.mkdir()
        (seeds / "city_weights.json").write_text('{"NYC": {"ensemble": 0.5}}')

        copied = paths.materialize_missing_seeds(seeds_dir=seeds, data_dir=data)

        assert copied == ["city_weights.json"]
        assert json.loads((data / "city_weights.json").read_text()) == {
            "NYC": {"ensemble": 0.5}
        }

    def test_never_overwrites_an_existing_data_file(self, tmp_path):
        """The load-bearing one: an existing file always wins.

        If this ever regressed, every process start would silently replace
        learned calibration with the frozen seed -- strictly worse than the
        `git restore` bug this whole change exists to remove, because it
        would fire on a normal run rather than on an explicit git command.
        """
        seeds, data = tmp_path / "seeds", tmp_path / "data"
        seeds.mkdir()
        data.mkdir()
        (seeds / "temperature_scale.json").write_text('{"global": {"T": 1.0}}')
        learned = '{"global": {"T": 4.601267428939456, "n": 68}}'
        (data / "temperature_scale.json").write_text(learned)

        copied = paths.materialize_missing_seeds(seeds_dir=seeds, data_dir=data)

        assert copied == [], "an already-present file must not be reported copied"
        assert (data / "temperature_scale.json").read_text() == learned
        # Positive control: the same call in the same seeds dir DOES copy a
        # file that is genuinely absent, so the assertion above is not passing
        # because the function is inert or the seeds dir was misspelled.
        (seeds / "city_weights.json").write_text("{}")
        assert paths.materialize_missing_seeds(seeds_dir=seeds, data_dir=data) == [
            "city_weights.json"
        ]
        assert (data / "city_weights.json").exists()

    def test_copies_every_seed_that_is_missing(self, tmp_path):
        seeds, data = tmp_path / "seeds", tmp_path / "data"
        seeds.mkdir()
        data.mkdir()
        for name in paths._SEEDED_FILENAMES:
            (seeds / name).write_text("{}")

        copied = paths.materialize_missing_seeds(seeds_dir=seeds, data_dir=data)

        assert sorted(copied) == sorted(paths._SEEDED_FILENAMES)

    def test_absent_seeds_dir_is_a_silent_no_op(self, tmp_path):
        """A clone with no seeds/ must still import. All five loaders already
        treat a missing file as 'uncalibrated' and return {} or None, so doing
        nothing is an already-supported state, never a reason to fail."""
        data = tmp_path / "data"
        data.mkdir()

        assert paths.materialize_missing_seeds(tmp_path / "nope", data) == []
        assert list(data.iterdir()) == []

    def test_unwritable_data_dir_is_a_silent_no_op(self, tmp_path):
        """Same tolerance on the write side: a data dir that does not exist
        raises OSError per file, which is caught and skipped rather than
        propagating out of `import paths`."""
        seeds = tmp_path / "seeds"
        seeds.mkdir()
        (seeds / "city_weights.json").write_text("{}")

        assert paths.materialize_missing_seeds(seeds, tmp_path / "missing") == []


class TestSeedsShippedInThisRepo:
    def test_seeds_dir_holds_exactly_the_declared_filenames(self):
        shipped = {p.name for p in (_REPO_ROOT / "seeds").glob("*.json")}
        assert shipped == set(paths._SEEDED_FILENAMES)

    def test_every_shipped_seed_is_valid_json(self):
        for name in paths._SEEDED_FILENAMES:
            body = (_REPO_ROOT / "seeds" / name).read_text()
            assert isinstance(json.loads(body), dict), name

    def test_uniform_seed_weights_all_carry_the_uncalibrated_flag(self):
        """A 1/3-1/3-1/3 entry is _best_weights' placeholder, not a fit.

        weather_markets._blend_weights only falls through to the hardcoded
        days-out schedule when it sees "_uncalibrated"; an unflagged uniform
        entry is instead applied as a real calibrated result, suppressing that
        schedule. seeds/seasonal_weights.json's `summer` entry was exactly
        that -- _best_weights' brier-gate rejection path used to omit the flag
        (fixed by batch-37 item 5(a) on 2026-08-24, but commit fa183f65 had
        already frozen the pre-fix output into git, and that blob became this
        seed).
        """
        uniform = round(1 / 3, 10)
        scanned = 0
        # Scan EVERY shipped seed rather than a hardcoded pair. An earlier
        # version listed ("seasonal_weights.json", "city_weights.json"); the
        # second is literally `{}`, so that arm was entirely vacuous, and the
        # list omitted condition_weights.json even though _blend_weights'
        # tier 2 applies the same _uncalibrated semantics to it. Deriving the
        # set also means a seed added later (batch-82 plans to) is covered
        # without anyone remembering to extend this list.
        for name in paths._SEEDED_FILENAMES:
            data = json.loads((_REPO_ROOT / "seeds" / name).read_text())
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                weights = {
                    k: v
                    for k, v in entry.items()
                    if not k.startswith("_") and isinstance(v, int | float)
                }
                if len(weights) < 2:
                    continue  # not a weight vector
                # NOTE (batch-87): this guard does NOT exclude coefficient
                # fits, despite what an earlier version of this comment said.
                # metar's a/b/c/n is skipped for a different reason (it is
                # flat, so `entry` is not a dict and the outer isinstance
                # check drops it first), and analysis_calibration.json's
                # nested {a, b, n} entry has three numeric keys and IS
                # scanned here. Harmless -- a=1.0 is not 1/3, so the uniform
                # assertion never fires on it -- but it is scanned, not
                # excluded, and the count below includes it.
                scanned += 1
                if all(round(v, 10) == uniform for v in weights.values()):
                    assert entry.get("_uncalibrated") is True, (
                        f"{name}:{key} is uniform but unflagged -- _blend_weights "
                        f"will treat it as a real calibration and suppress the "
                        f"days-out schedule"
                    )
        # The scan reached real weight vectors rather than skipping everything
        # via the `continue`s above.
        assert scanned >= 4, f"only {scanned} weight vectors scanned"

    def test_seed_weight_entries_that_are_flagged_are_actually_uniform(self):
        """Positive control for the test above: the flag and the uniform shape
        travel together, so that test is scanning real entries rather than
        skipping every one of them via an `all()` over an empty dict."""
        data = json.loads((_REPO_ROOT / "seeds" / "seasonal_weights.json").read_text())
        flagged = [k for k, v in data.items() if v.get("_uncalibrated")]
        assert len(flagged) == 4, f"expected all four seasons flagged, got {flagged}"
        for key in flagged:
            weights = {k: v for k, v in data[key].items() if not k.startswith("_")}
            assert weights, f"{key} has no weights at all"
            assert all(round(v, 10) == round(1 / 3, 10) for v in weights.values()), (
                f"{key} is flagged _uncalibrated but is not uniform: {weights}"
            )

    def test_every_seeded_name_is_protected_from_cleanup_data_dir(self):
        """`main.cleanup_data_dir` unlinks any data/*.json older than 2 days
        unless it is in `_PERMANENT_DATA_FILES`. That invariant changed
        MEANING with the seeding change and is now safety-critical: before,
        cleanup deleting a calibration file meant "uncalibrated until the next
        fit"; now it means "silently restored to the frozen seed on the next
        import". metar_lockout_calibration.json's seed is real fitted
        coefficients that pass _load_metar_calibration's validity gates and
        would be applied to live pricing, so a name falling out of that set
        would be a silent calibration rollback.
        """
        import main

        missing = set(paths._SEEDED_FILENAMES) - set(main._PERMANENT_DATA_FILES)
        assert not missing, (
            f"{sorted(missing)} would be deleted by cleanup_data_dir and then "
            f"silently re-seeded from seeds/ on the next import"
        )
        # Positive control: the set is a real, populated collection of these
        # filenames -- not an empty or never-matching container that would
        # make the difference above trivially empty.
        assert "paper_trades.json" in main._PERMANENT_DATA_FILES
        assert set(paths._SEEDED_FILENAMES) < set(main._PERMANENT_DATA_FILES)

    def test_declared_filenames_match_the_path_constants_loaders_use(self):
        """Pins _SEEDED_FILENAMES against the constants the nine loaders
        actually open, so a rename in paths.py cannot leave seeds/ quietly
        seeding a filename nothing reads."""
        assert set(paths._SEEDED_FILENAMES) == {
            # batch-87: the final-stage calibration fitted on
            # analysis_attempts, read by ml_bias.apply_analysis_calibration.
            paths.ANALYSIS_CALIBRATION_PATH.name,
            paths.CITY_WEIGHTS_PATH.name,
            paths.CONDITION_WEIGHTS_PATH.name,
            paths.SEASONAL_WEIGHTS_PATH.name,
            paths.TEMPERATURE_SCALE_PATH.name,
            paths.METAR_CALIBRATION_PATH.name,
            # batch-82: the same-day halves of the three blend-weight tables.
            paths.CITY_WEIGHTS_SAMEDAY_PATH.name,
            paths.CONDITION_WEIGHTS_SAMEDAY_PATH.name,
            paths.SEASONAL_WEIGHTS_SAMEDAY_PATH.name,
        }

    def test_sameday_and_multiday_seed_names_are_distinct(self):
        """The two horizons must never resolve to the same file.

        A copy-paste slip in paths.py that pointed a _SAMEDAY_PATH at its
        multi-day sibling would make a same-day calibration run overwrite the
        multi-day fit -- precisely the contamination the split exists to
        prevent -- and every other seeds test would still pass, because the
        name would be a valid, declared, permanent, loader-backed one.
        """
        pairs = [
            (paths.CITY_WEIGHTS_PATH, paths.CITY_WEIGHTS_SAMEDAY_PATH),
            (paths.CONDITION_WEIGHTS_PATH, paths.CONDITION_WEIGHTS_SAMEDAY_PATH),
            (paths.SEASONAL_WEIGHTS_PATH, paths.SEASONAL_WEIGHTS_SAMEDAY_PATH),
        ]
        for multiday, sameday in pairs:
            assert multiday != sameday, multiday
        # And all six are distinct from each other, not merely pairwise.
        assert len({p.name for pair in pairs for p in pair}) == 6


def _seed_a_fresh_clone(tmp_path, *, with_seeds: bool) -> list[str]:
    """Import paths.py in a child whose project_root() is `tmp_path`.

    A child rather than importlib.reload(paths): reloading would rebind
    DATA_DIR for the rest of the pytest process and re-run materialization
    against the REAL data/ directory on the way back out. The child also
    bypasses conftest's prod_data_guard the same way any standalone script
    does, which is precisely why project_root() is redirected first.
    """
    if with_seeds:
        seeds = tmp_path / "seeds"
        seeds.mkdir()
        for name in paths._SEEDED_FILENAMES:
            (seeds / name).write_text('{"from_seed": true}')

    code = (
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {str(_REPO_ROOT)!r})\n"
        "import safe_io\n"
        f"_root = pathlib.Path({str(tmp_path)!r})\n"
        "safe_io.project_root = lambda: _root\n"
        "import paths\n"
        "print(json.dumps(sorted(p.name for p in paths.DATA_DIR.iterdir())))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, (
        f"child exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestImportTimeMaterialization:
    """`import paths` is what gives this complete coverage -- every entry
    point in the project reaches it at module scope, so no launch path can
    start up unseeded and none of the five loaders needed changing."""

    def test_a_fresh_clone_is_seeded_by_importing_paths(self, tmp_path):
        assert _seed_a_fresh_clone(tmp_path, with_seeds=True) == sorted(
            paths._SEEDED_FILENAMES
        )

    def test_a_clone_without_seeds_gets_an_empty_data_dir(self, tmp_path):
        """Positive control for the test above: the files land because seeds/
        supplied them, not because importing paths creates them from anywhere
        else -- and a seedless clone still imports cleanly."""
        assert _seed_a_fresh_clone(tmp_path, with_seeds=False) == []


class TestNothingUnderDataIsTracked:
    def test_git_tracks_no_file_under_data(self):
        """Regression pin for the untracking itself.

        Five files used to be force-added past .gitignore's `data/` rule, which
        is what made `git restore .` able to revert learned calibration. If
        anyone `git add -f`s under data/ again, this fails the build.
        """
        try:
            proc = subprocess.run(
                ["git", "ls-files", "data/"],
                cwd=str(_REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            pytest.skip(f"git unavailable: {exc}")
        if proc.returncode != 0:  # pragma: no cover
            pytest.skip(f"not a git checkout: {proc.stderr.strip()}")

        tracked = [line for line in proc.stdout.splitlines() if line.strip()]
        assert tracked == [], (
            "these files are tracked under the gitignored data/ directory, so "
            "`git restore .` can revert live calibration to a committed "
            f"snapshot: {tracked}. Ship first-run copies in seeds/ instead."
        )
        # Positive control: the same invocation DOES list files for a path
        # that is genuinely tracked, so an empty result above means "nothing
        # tracked under data/" rather than "git ls-files returned nothing".
        control = subprocess.run(
            ["git", "ls-files", "seeds/"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert [ln for ln in control.stdout.splitlines() if ln.strip()], (
            "git ls-files reported nothing for seeds/ either -- the assertion "
            "above proved nothing about data/"
        )
