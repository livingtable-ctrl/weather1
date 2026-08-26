r"""Positive control for tests/prod_data_guard.py.

A guard that silently stops working is worse than no guard: it turns "the
suite never writes production" from a fact into an assumption. Every one of
these tests attempts a real mutation against the real data/ directory and
asserts BOTH halves of the contract -- the operation raised, and nothing
appeared/disappeared on disk.

Each attempt is deliberate, so each consumes its own recorded violation via
_expect_blocked(); otherwise conftest's own assert_clean() hook would fail
these tests for the very behaviour they exist to prove.
"""

from __future__ import annotations

import importlib
import inspect
import os
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

import paths
import weather_markets
from tests import conftest, prod_data_guard
from tests.conftest import _PERIODIC_GATE_SENTINELS

#: Prefix on every artefact these probes could possibly create. Nothing in
#: production is named this way, so the sweep below can match on it safely.
_PROBE_PREFIX = "GUARD_PROBE_"


def _real_data_dir() -> Path:
    """The directory the guard is actually enforcing, not the one we hope."""
    assert prod_data_guard._data_prefixes, "guard is not installed"
    return Path(prod_data_guard._data_prefixes[0])


def _real_data_dir_unguarded() -> Path:
    """The real data/ dir, resolved WITHOUT consulting the guard.

    The sweep below has to work when the guard is uninstalled or broken,
    which is exactly when _real_data_dir()'s assertion would fire.
    """
    import safe_io

    return safe_io.project_root() / "data"


@pytest.fixture(autouse=True)
def _sweep_probe_residue():
    """Delete any GUARD_PROBE_* artefact a probe actually managed to create.

    Every test in this module attempts a real mutation of the real data/
    directory. While the guard works, none of them lands. But these are
    precisely the tests that run when the guard is BROKEN -- during
    mutation testing, or after a genuine regression -- and then the
    attempt succeeds for real.

    That is not hypothetical: during this file's own mutation battery,
    dropping "a" from prod_data_guard._WRITE_MODES let
    test_append_mode_is_blocked append twice to a real
    data/GUARD_PROBE_append.log. The test correctly went red, and the
    junk file was still left sitting in the operator's production data
    directory. A guard's own test suite must not be the thing that dirties
    what it is guarding.

    Cleanup deliberately goes through prod_data_guard's captured
    ORIGINALS: os.remove/shutil.rmtree are patched to refuse exactly the
    paths being cleaned up here, and the originals also work when the
    guard was never installed at all.
    """
    yield
    survivors = _sweep_probe_artefacts()
    assert not survivors, (
        f"could not remove probe artefact(s) from the REAL production data "
        f"directory: {survivors}. They must not be left there -- delete them "
        f"by hand. (A locked file, e.g. a concurrent cron scan or an AV "
        f"scanner holding a handle, is the usual cause.)"
    )


def _remove_tree_unguarded(path: str) -> None:
    """Recursively delete `path` using only UN-patched primitives.

    shutil.rmtree is not usable here even via prod_data_guard._o_rmtree:
    rmtree calls os.rmdir internally, and that lookup resolves to the
    PATCHED os.rmdir, so the original rmtree blocks itself on exactly the
    paths this sweep exists to clean. Walking it by hand with the captured
    originals is the only version that works while the guard is armed.
    """
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False):
            _remove_tree_unguarded(entry.path)
        else:
            prod_data_guard._o_remove(entry.path)
    prod_data_guard._o_rmdir(path)


def _sweep_probe_artefacts() -> list[str]:
    """Delete every GUARD_PROBE_* artefact; return any that survived."""
    data_dir = _real_data_dir_unguarded()
    try:
        entries = list(os.scandir(data_dir))
    except OSError:  # pragma: no cover -- data/ absent on a fresh clone
        return []
    survivors = []
    for entry in entries:
        if not entry.name.startswith(_PROBE_PREFIX):
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                _remove_tree_unguarded(entry.path)
            else:
                prod_data_guard._o_remove(entry.path)
        except OSError:  # pragma: no cover -- only on a locked file
            survivors.append(entry.path)
    return survivors


def _expect_blocked(fn, *, op_contains: str):
    """Run `fn`, assert it was blocked AND recorded, then consume the record.

    Asserting on prod_data_guard._violations matters as much as asserting
    the raise: assert_clean()'s whole job is to catch an attempt whose
    exception got swallowed by production code's `except Exception`, and it
    can only do that if _block() recorded before it raised.
    """
    # Consume only what THIS call produced. Clearing the whole list would
    # swallow anything an earlier fixture or probe had recorded, making the
    # probes weaker than they read.
    before = len(prod_data_guard._violations)
    with pytest.raises(prod_data_guard.ProdDataWriteError):
        fn()
    recorded = prod_data_guard._violations[before:]
    del prod_data_guard._violations[before:]
    assert recorded, "the attempt raised but was never recorded for assert_clean"
    assert op_contains in recorded[0][1], (
        f"expected an operation containing {op_contains!r}, got {recorded[0][1]!r}"
    )
    return recorded[0]


class TestGuardIsArmed:
    def test_guard_is_installed_for_the_whole_session(self):
        assert prod_data_guard._installed is True

    def test_guard_watches_the_path_paths_py_actually_resolves(self):
        """The guard is worthless if it is enforcing a different directory
        than the one production constants resolve to.

        Deliberately asserted against safe_io.project_root() rather than
        against paths.<CONST>: the isolate_* fixtures now redirect most of
        those constants to tmp_path (which is the point), so reading them
        here would test the fixtures, not the guard's target directory.
        project_root() is the un-redirected source of truth paths.py
        itself is built from.
        """
        import safe_io

        real_data = safe_io.project_root() / "data"
        assert prod_data_guard._under_real_data(real_data)
        assert prod_data_guard._under_real_data(real_data / ".kill_switch")
        assert prod_data_guard._under_real_data(real_data / "predictions.db")
        assert prod_data_guard._under_real_data(
            real_data / "ensemble_cache" / "40.7_-73.9_2026-01-01_max.json"
        ), "a nested subdirectory of data/ must be guarded, not just the top level"

    def test_tmp_path_is_not_treated_as_production(self, tmp_path):
        """The redirect target every isolate_* fixture uses must stay legal,
        or the guard would fail the entire suite instead of protecting it."""
        assert not prod_data_guard._under_real_data(tmp_path / ".kill_switch")
        (tmp_path / "ordinary.json").write_text("{}")
        assert (tmp_path / "ordinary.json").read_text() == "{}"


class TestMutationsAreBlocked:
    def test_builtin_open_for_write_is_blocked(self):
        target = _real_data_dir() / "GUARD_PROBE_open.txt"

        def attempt():
            with open(target, "w") as fh:
                fh.write("should never reach disk")

        _expect_blocked(attempt, op_contains="open(mode=")
        assert not target.exists()

    def test_path_write_text_is_blocked(self):
        """Path.write_text routes through Path.open on this interpreter.

        The guard patches Path.open rather than write_text/write_bytes
        individually, which is only sound if CPython still delegates. This
        asserts that against the running interpreter instead of trusting
        the stdlib source.
        """
        target = _real_data_dir() / "GUARD_PROBE_write_text.json"
        record = _expect_blocked(
            lambda: target.write_text("{}"), op_contains="Path.open(mode="
        )
        assert not target.exists()
        assert "GUARD_PROBE_write_text.json" in record[2]

    def test_path_write_bytes_is_blocked(self):
        target = _real_data_dir() / "GUARD_PROBE_write_bytes.bin"
        _expect_blocked(
            lambda: target.write_bytes(b"\x00"), op_contains="Path.open(mode="
        )
        assert not target.exists()

    def test_append_mode_is_blocked(self):
        """The 467-fake-lines cron.log incident was an append, not a
        truncating write -- 'a' must count as a mutation."""
        target = _real_data_dir() / "GUARD_PROBE_append.log"

        def attempt():
            with open(target, "a") as fh:
                fh.write("fabricated line\n")

        _expect_blocked(attempt, op_contains="open(mode=")
        assert not target.exists()

    def test_path_touch_is_blocked(self):
        """alerts.py engages the kill switch with _KILL_SWITCH_PATH.touch()."""
        target = _real_data_dir() / "GUARD_PROBE_touch"
        _expect_blocked(target.touch, op_contains="Path.touch")
        assert not target.exists()

    def test_deleting_from_the_data_dir_is_blocked(self):
        """web_app's /api/resume DELETES the production kill switch.

        A delete leaves nothing behind to notice afterwards, which is why
        this vector matters more than any overwrite: a halt the operator
        set deliberately would simply be gone after a test run.

        The target deliberately does not exist, so this test cannot destroy
        anything even if the guard is completely broken. It still detects a
        broken guard, because both calls have a well-defined un-guarded
        outcome that is NOT ProdDataWriteError: unlink(missing_ok=True)
        would silently succeed, and os.remove would raise FileNotFoundError.
        Getting ProdDataWriteError instead proves interception happens
        before the filesystem is touched at all.
        """
        target = _real_data_dir() / "GUARD_PROBE_absent_victim.txt"
        assert not target.exists(), "probe name collided with a real file"
        _expect_blocked(
            lambda: target.unlink(missing_ok=True), op_contains="Path.unlink"
        )
        _expect_blocked(lambda: os.remove(target), op_contains="os.remove")

    def test_os_replace_into_data_dir_is_blocked(self, tmp_path):
        """safe_io.atomic_write_json lands its temp file with os.replace --
        the final step of nearly every persistent write in this codebase."""
        src = tmp_path / "staged.json"
        src.write_text('{"halted": true}')
        dst = _real_data_dir() / "GUARD_PROBE_replaced.json"
        _expect_blocked(lambda: os.replace(src, dst), op_contains="os.replace")
        assert not dst.exists()
        assert src.exists(), "a blocked replace must not consume its source"

    def test_shutil_copy_into_data_dir_is_blocked(self, tmp_path):
        src = tmp_path / "payload.json"
        src.write_text("{}")
        dst = _real_data_dir() / "GUARD_PROBE_copied.json"
        _expect_blocked(lambda: shutil.copy2(src, dst), op_contains="shutil.copy2")
        assert not dst.exists()

    def test_sqlite_connect_to_a_production_db_is_blocked(self):
        """cloud_backup._sqlite_source_is_empty() opens every *.db in
        DATA_DIR; a handle is a write capability regardless of intent."""
        _expect_blocked(
            lambda: sqlite3.connect(paths.DB_PATH), op_contains="sqlite3.connect"
        )

    def test_creating_a_subdirectory_of_data_is_allowed(self):
        """mkdir is deliberately unguarded -- see the module docstring.

        An earlier version blocked creating a NEW subdirectory while
        allowing an exist_ok re-assertion of an existing one. That passed
        locally only because data/archive_cache happened to exist, and
        failed ~90 tests on a fresh CI checkout, where backtest.py and
        ab_test.py mkdir their cache subdirs at module import. An empty
        directory holds no production data; what matters is that writes
        into it are still refused, which the next test asserts.
        """
        target = _real_data_dir() / f"{_PROBE_PREFIX}subdir"
        target.mkdir(exist_ok=True)
        assert target.is_dir()
        assert not prod_data_guard._violations
        # _sweep_probe_residue removes it (it rmtree's GUARD_PROBE_* dirs).

    def test_a_write_into_a_created_subdirectory_is_still_blocked(self):
        """The reason not guarding mkdir is safe: the directory is inert,
        the write is what carries data, and the write is refused."""
        target = _real_data_dir() / f"{_PROBE_PREFIX}subdir_write"
        target.mkdir(exist_ok=True)
        inner = target / "payload.json"
        _expect_blocked(lambda: inner.write_text("{}"), op_contains="Path.open(mode=")
        assert not inner.exists()

    def test_recreating_the_data_dir_itself_is_allowed(self):
        """paths.py does _DATA.mkdir(parents=True, exist_ok=True) at import,
        and several modules do <CONST>.parent.mkdir(exist_ok=True) before an
        atomic write."""
        _real_data_dir().mkdir(parents=True, exist_ok=True)
        assert not prod_data_guard._violations


class TestMovesOutOfDataAreBlocked:
    """A move is a DELETE of its source.

    The guard blocks Path.unlink/os.remove precisely because "a delete
    leaves nothing behind to notice afterwards". Renaming a production file
    away is the same outcome, and checking only the destination -- correct
    for a copy, whose source is read-only -- left it as the one uncovered
    delete shape.
    """

    @pytest.mark.parametrize("operation", ["os.replace", "os.rename", "shutil.move"])
    def test_moving_a_production_file_out_of_data_is_blocked(self, operation, tmp_path):
        src = _real_data_dir() / f"{_PROBE_PREFIX}move_src.json"
        dst = tmp_path / "escaped.json"
        mover = {
            "os.replace": os.replace,
            "os.rename": os.rename,
            "shutil.move": shutil.move,
        }[operation]
        _expect_blocked(lambda: mover(src, dst), op_contains="moved OUT of data/")
        assert not dst.exists(), "the guard let a production file escape data/"

    def test_pathlib_move_out_of_data_is_blocked(self, tmp_path):
        src = _real_data_dir() / f"{_PROBE_PREFIX}pathlib_move_src.json"
        _expect_blocked(
            lambda: src.move(tmp_path / "escaped.json"),
            op_contains="moved OUT of data/",
        )

    def test_copying_out_of_data_stays_legal(self, tmp_path):
        """Only moves are two-sided. A copy reads its source, so copying a
        production file out must NOT be blocked -- otherwise every fixture
        that seeds tmp_path from a real calibration file would fail."""
        source = paths.SEASONAL_WEIGHTS_PATH
        if not source.exists():
            pytest.skip("data/seasonal_weights.json not present in this clone")
        shutil.copy2(source, tmp_path / "copied.json")
        assert (tmp_path / "copied.json").exists()
        assert not prod_data_guard._violations


class TestCopytreeIsBlockedBeforeAnythingLands:
    def test_copytree_into_an_existing_data_subdir_is_blocked(self, tmp_path):
        """shutil.copytree binds copy_function=copy2 as a DEFAULT ARGUMENT
        at def time, so patching shutil.copy2 never reaches it. Without its
        own patch, dirs_exist_ok=True let the first file land on disk and
        only tripped later at copystat -> os.utime: detected, but not
        prevented. cloud_backup.py's snapshot call is the live call site."""
        source = tmp_path / "payload"
        source.mkdir()
        (source / "leaked.json").write_text("{}")
        destination = _real_data_dir() / f"{_PROBE_PREFIX}copytree_dst"
        _expect_blocked(
            lambda: shutil.copytree(source, destination, dirs_exist_ok=True),
            op_contains="shutil.copytree",
        )
        assert not (destination / "leaked.json").exists(), (
            "copytree wrote a file into production before the guard tripped"
        )
        assert not destination.exists()


class TestSqliteUriFormIsBlocked:
    def test_read_write_uri_is_blocked(self):
        """The URI form does not start with a drive letter, so an earlier
        draft classified it as RELATIVE, abspath()'d it against the cwd, and
        let it straight through -- while also making the mode=ro allowance
        dead code."""
        uri = f"file:{paths.DB_PATH.as_posix()}?mode=rwc"
        _expect_blocked(
            lambda: sqlite3.connect(uri, uri=True), op_contains="sqlite3.connect"
        )

    def test_bare_file_uri_without_query_is_blocked(self):
        uri = f"file:{paths.DB_PATH.as_posix()}"
        _expect_blocked(
            lambda: sqlite3.connect(uri, uri=True), op_contains="sqlite3.connect"
        )

    def test_read_only_uri_is_allowed(self):
        """migrate_backup.py opens production DBs read-only this way. That
        must keep working -- and now works by design rather than by the
        accident of the URI never being recognised at all."""
        if not paths.DB_PATH.exists():
            pytest.skip("data/predictions.db not present in this clone")
        uri = f"file:{paths.DB_PATH.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.close()
        assert not prod_data_guard._violations


class TestWindowsPathSpellings:
    def test_extended_length_prefix_is_recognised(self):
        r"""\\?\C:\... names the same file as C:\..., and the write lands
        for real if the predicate does not strip the prefix."""
        extended = "\\\\?\\" + str(_real_data_dir() / f"{_PROBE_PREFIX}extended.json")
        assert prod_data_guard._under_real_data(extended)
        _expect_blocked(lambda: open(extended, "w"), op_contains="open(mode=")

    def test_sibling_directory_is_not_treated_as_production(self):
        """`prefix + os.sep` earns this: a bare startswith would classify
        data_other/ as inside data/ and fail unrelated tests."""
        sibling = str(_real_data_dir()) + "_other"
        assert not prod_data_guard._under_real_data(sibling + os.sep + "x.json")


class TestPathlibCopyApis:
    """Path.copy/copy_into are NEW in 3.14 and on Windows use
    _winapi.CopyFile2, bypassing open() entirely -- exactly the "a new
    stdlib API silently reopens the hole" shape this module exists to
    prevent."""

    @pytest.mark.parametrize("method", ["copy", "copy_into"])
    def test_pathlib_copy_into_data_is_blocked(self, method, tmp_path):
        if not hasattr(Path, method):
            pytest.skip(f"Path.{method} not available on this interpreter")
        source = tmp_path / "payload.json"
        source.write_text("{}")
        if method == "copy":
            target = _real_data_dir() / f"{_PROBE_PREFIX}pathlib_copy.json"
            _expect_blocked(lambda: source.copy(target), op_contains="Path.copy")
            assert not target.exists()
        else:
            target_dir = _real_data_dir()
            _expect_blocked(
                lambda: source.copy_into(target_dir), op_contains="Path.copy_into"
            )
            assert not (target_dir / "payload.json").exists()


class TestSwallowedFailuresStillFailTheTest:
    def test_a_swallowed_block_is_still_recorded(self):
        """The reason assert_clean() exists.

        This codebase wraps nearly all persistence in `try: ... except
        Exception: log`. If the guard relied only on raising at the call
        site, such a test would go green having attempted a production
        write -- exactly the silent outcome the guard is meant to end.
        """
        target = _real_data_dir() / "GUARD_PROBE_swallowed.json"
        try:
            target.write_text('{"reason": "swallowed"}')
        except Exception:  # noqa: BLE001 -- mimics the production idiom
            pass
        recorded = list(prod_data_guard._violations)
        prod_data_guard._violations.clear()
        assert recorded, "a swallowed attempt left no record for assert_clean"
        assert not target.exists()

    def test_assert_clean_raises_on_a_recorded_violation(self):
        prod_data_guard._violations.append(
            ("some::nodeid", "open(mode='w')", r"C:\fake\data\x.json", "MainThread")
        )
        with pytest.raises(AssertionError, match="must not mutate"):
            prod_data_guard.assert_clean("the test body")
        assert not prod_data_guard._violations, (
            "assert_clean must consume what it reported, or every later "
            "phase in the session would fail with the same stale violation"
        )

    def test_assert_clean_is_silent_when_nothing_was_attempted(self):
        assert not prod_data_guard._violations
        prod_data_guard.assert_clean("the test body")


#: Every (module, attribute) pair conftest's isolate_* fixtures redirect
#: away from the real data/ directory. Kept here rather than in conftest so
#: that deleting a fixture fails a test instead of silently re-opening the
#: hole -- the guard would catch a resulting WRITE, but only from whichever
#: test happens to exercise that path, which is how these leaks stayed
#: hidden for months in the first place.
_ISOLATED_BINDINGS = [
    ("paths", "KILL_SWITCH_PATH"),
    ("cron", "KILL_SWITCH_PATH"),
    ("main", "KILL_SWITCH_PATH"),
    ("alerts", "_KILL_SWITCH_PATH"),
    ("trading_gates", "KILL_SWITCH_PATH"),
    ("web_app", "_KS_PATH"),
    ("paths", "WATCH_STATE_PATH"),
    ("main", "WATCH_STATE_PATH"),
    ("main", "_WATCH_STATE_PATH"),
    ("paths", "NOTIFY_COOLDOWN_STATE_PATH"),
    ("notify", "NOTIFY_COOLDOWN_STATE_PATH"),
    ("paths", "CRON_WEB_LOG_PATH"),
    ("web_app", "CRON_WEB_LOG_PATH"),
    ("cloud_backup", "DATA_DIR"),
    ("paths", "LOCK_PATH"),
    ("cron", "LOCK_PATH"),
    ("main", "LOCK_PATH"),
    ("web_app", "LOCK_PATH"),
    ("paths", "RUNNING_FLAG_PATH"),
    ("cron", "RUNNING_FLAG_PATH"),
    ("main", "RUNNING_FLAG_PATH"),
    ("web_app", "RUNNING_FLAG_PATH"),
    ("paths", "LAST_CALIBRATION_COUNT_PATH"),
    ("cron", "LAST_CALIBRATION_COUNT_PATH"),
    ("main", "LAST_CALIBRATION_COUNT_PATH"),
    ("web_app", "LAST_CALIBRATION_COUNT_PATH"),
    ("paths", "LEARNED_WEIGHTS_PATH"),
    ("weather_markets", "LEARNED_WEIGHTS_PATH"),
    ("paths", "FORECAST_SNAPSHOTS_DIR"),
    ("weather_markets", "FORECAST_SNAPSHOTS_DIR"),
    ("weather_markets", "ENSEMBLE_CACHE_DIR"),
    ("paths", "FEATURE_IMPORTANCE_LOG_PATH"),
    ("feature_importance", "_FEATURE_LOG_PATH"),
    ("paths", "CONFIG_HASH_PATH"),
    ("utils", "_CONFIG_HASH_PATH"),
    ("settlement_monitor", "_SETTLEMENT_LOCK_PATH"),
    ("climatology", "_SIGMA_CACHE_PATH"),
]

#: The isolate_* fixtures this change owns. TestNoUnlistedRedirects scans
#: exactly these, so pre-existing fixtures (isolate_tracker_db,
#: isolate_paper_data, ...) are out of scope and their own bindings are not
#: required to appear in _ISOLATED_BINDINGS.
_OWNED_FIXTURES = [
    "isolate_kill_switch",
    "isolate_watch_state",
    "isolate_notify_cooldowns",
    "isolate_cron_web_log",
    "isolate_cloud_backup_source",
    "isolate_cron_lifecycle_sentinels",
    "isolate_learned_weight_artifacts",
    "isolate_feature_importance_log",
    "isolate_config_hash",
    "isolate_paths_py_bypassers",
]

#: The periodic-gate sentinels are DERIVED from conftest's own table rather
#: than re-listed here. Hand-copying 30 more rows would just create a second
#: place to forget: a constant added to isolate_periodic_gate_sentinels but
#: not here would be tested by nothing.
_ISOLATED_BINDINGS += [
    (module_name, const)
    for const, module_names in _PERIODIC_GATE_SENTINELS
    for module_name in ("paths", *module_names)
]


class TestIsolationFixturesStayWired:
    @pytest.mark.parametrize(
        "module_name, attr", _ISOLATED_BINDINGS, ids=lambda v: str(v)
    )
    def test_binding_no_longer_points_at_production(self, module_name, attr):
        """Each redirected constant must resolve outside the real data/ dir.

        This fails the moment somebody deletes or narrows one of conftest's
        isolate_* fixtures, naming the exact (module, attribute) that came
        loose -- rather than waiting for whichever unrelated test happens to
        write through it.
        """
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        assert not prod_data_guard._under_real_data(value), (
            f"{module_name}.{attr} still resolves into the real data/ dir "
            f"({value}) -- its isolate_* fixture in tests/conftest.py is "
            f"missing, disabled, or no longer covers this binding."
        )

    def test_no_redirect_is_missing_from_the_list(self):
        """The reverse direction: a setattr added to a fixture but never
        listed here would be tested by nothing, so a later narrowing of it
        would go unnoticed. Scans only the fixtures this change owns."""
        listed = {attr for _, attr in _ISOLATED_BINDINGS}
        # The cache-reset companions in isolate_learned_weight_artifacts are
        # in-memory state, not paths, so they are deliberately out of scope.
        not_a_path = {
            "_LEARNED_WEIGHTS",
            "_LEARNED_WEIGHTS_MTIME",
            "_LEARNED_WEIGHTS_TTL_WARNED",
        }
        unlisted = {}
        for fixture_name in _OWNED_FIXTURES:
            source = inspect.getsource(getattr(conftest, fixture_name))
            for attr in re.findall(r'monkeypatch\.setattr\(\s*\w+,\s*"(\w+)"', source):
                if attr in not_a_path or attr in listed:
                    continue
                unlisted.setdefault(fixture_name, []).append(attr)
        assert not unlisted, (
            f"redirect(s) performed by an isolate_* fixture but absent from "
            f"_ISOLATED_BINDINGS: {unlisted}. Add them, or nothing verifies "
            f"they still point away from production."
        )

    def test_owned_fixtures_all_exist(self):
        for fixture_name in _OWNED_FIXTURES:
            assert hasattr(conftest, fixture_name), (
                f"conftest.{fixture_name} is gone -- if the fixture was "
                f"renamed or deleted, update _OWNED_FIXTURES so the scan "
                f"above does not silently cover nothing."
            )

    def test_every_binding_names_a_real_attribute(self):
        """A typo in _ISOLATED_BINDINGS would make its row vacuously pass
        only if getattr raised -- so assert the attribute exists first."""
        for module_name, attr in _ISOLATED_BINDINGS:
            module = importlib.import_module(module_name)
            assert hasattr(module, attr), (
                f"{module_name}.{attr} does not exist -- the constant was "
                f"renamed or removed; update conftest's fixture and this list."
            )


class TestProbeResidueSweep:
    def test_every_probe_target_uses_the_swept_prefix(self):
        """A probe named outside _PROBE_PREFIX would survive the sweep.

        The sweep can only match on a name prefix, so a future probe
        pointed at some other filename inside the real data dir would leave
        a real file behind in production the moment the guard regressed.
        Enforced by scanning this file's own source, matching the
        structural-guard idiom used by test_paths_bypass_guard.py.

        (The scanned pattern is written so that this docstring cannot
        itself supply a match -- an earlier draft quoted an example
        filename inline and the scan duly flagged its own prose.)
        """
        src = Path(__file__).read_text(encoding="utf-8")
        targets = re.findall(r'_real_data_dir\(\)\s*/\s*"([^"]+)"', src)
        assert targets, "the scan found no probe targets -- pattern went stale"
        offenders = [t for t in targets if not t.startswith(_PROBE_PREFIX)]
        assert not offenders, (
            f"probe target(s) {offenders} do not start with {_PROBE_PREFIX!r}, "
            f"so _sweep_probe_residue cannot clean them up if the guard breaks"
        )

    def test_sweep_removes_a_real_file_it_finds(self):
        """Positive control for the sweep itself.

        Written through the un-patched original, exactly as a broken guard
        would have let a probe write it, then left for the autouse fixture
        to remove. The companion assertion is that no GUARD_PROBE_* file
        exists in production data/ after this module's suite finishes.
        """
        stray = _real_data_dir_unguarded() / f"{_PROBE_PREFIX}sweep_control.txt"
        with prod_data_guard._o_open(stray, "w") as handle:
            handle.write("left behind by a deliberately broken guard")
        assert stray.exists()
        # No cleanup here on purpose -- _sweep_probe_residue must do it.


class _DummyItem:
    """Minimal stand-in for a pytest Item: the hooks only read .nodeid."""

    nodeid = "tests/test_prod_data_guard.py::<hook-wiring-probe>"


_PHASE_HOOKS = [
    "pytest_collection_finish",
    "pytest_runtest_setup",
    "pytest_runtest_call",
    "pytest_runtest_teardown",
]


class TestConftestWiring:
    """Behavioural checks on the hooks, not a grep of conftest's source.

    An earlier draft asserted `conftest_src.count("assert_clean(") == 3`.
    That was brittle (adding the collection hook broke it) and, worse, weak:
    it would have passed if someone dropped @pytest.hookimpl(wrapper=True),
    or moved assert_clean above the yield, or replaced a hook body with a
    no-op. These drive the hook generators directly instead.
    """

    @pytest.mark.parametrize("hook_name", _PHASE_HOOKS)
    def test_hook_is_a_wrapper(self, hook_name):
        """Without wrapper=True these become ordinary hooks that run BEFORE
        the phase, so assert_clean would report the previous phase's state."""
        hook = getattr(conftest, hook_name)
        assert inspect.isgeneratorfunction(hook), (
            f"{hook_name} is not a generator -- it lost its `yield`"
        )
        assert hook.pytest_impl["wrapper"] is True, (
            f"{hook_name} lost @pytest.hookimpl(wrapper=True)"
        )

    @pytest.mark.parametrize("hook_name", _PHASE_HOOKS)
    def test_hook_reports_a_violation_recorded_during_its_phase(self, hook_name):
        """Drive the wrapper's generator protocol by hand: advance to the
        yield, inject a violation as if production code had swallowed the
        raise, then resume. The hook must fail the phase."""
        hook = getattr(conftest, hook_name)
        generator = (
            hook(_DummyItem())
            if hook_name != "pytest_runtest_teardown"
            else hook(_DummyItem(), None)
        )
        next(generator)  # run the hook body up to its yield
        prod_data_guard._violations.append(
            ("injected::nodeid", "open(mode='w')", r"C:\fake\data\x.json", "MainThread")
        )
        with pytest.raises(AssertionError, match="must not mutate"):
            generator.send(None)
        assert not prod_data_guard._violations

    @pytest.mark.parametrize("hook_name", _PHASE_HOOKS)
    def test_hook_still_reports_when_the_phase_itself_failed(self, hook_name):
        """The try/finally case. `wrapper=True` re-raises at the yield, so a
        bare `result = yield` would skip assert_clean entirely and the
        violation would be swept into _orphaned by the next test."""
        hook = getattr(conftest, hook_name)
        generator = (
            hook(_DummyItem())
            if hook_name != "pytest_runtest_teardown"
            else hook(_DummyItem(), None)
        )
        next(generator)
        prod_data_guard._violations.append(
            (
                "injected::nodeid",
                "Path.unlink",
                r"C:\fake\data\.kill_switch",
                "MainThread",
            )
        )
        with pytest.raises(AssertionError, match="must not mutate"):
            generator.throw(RuntimeError("unrelated phase failure"))
        assert not prod_data_guard._violations

    def test_unclaimed_violations_are_orphaned_not_discarded(self):
        """set_current_test must not silently drop a pending violation.

        An earlier draft cleared the list here. That is the silent-loss
        path: a fixture finalizer that deletes a production file inside
        try/except, followed by an unrelated finalizer failure, skips
        assert_clean -- and the next test's setup would erase the evidence.
        """
        orphaned_before = len(prod_data_guard.orphaned_violations())
        prod_data_guard._violations.append(
            ("stranded::nodeid", "Path.unlink", r"C:\fake\data\.cron_running", "T-1")
        )
        prod_data_guard.set_current_test("next::test")

        assert not prod_data_guard._violations, "pending list should be handed off"
        orphaned = prod_data_guard.orphaned_violations()
        assert len(orphaned) == orphaned_before + 1, (
            "the unclaimed violation was discarded instead of orphaned"
        )
        assert orphaned[-1][0] == "stranded::nodeid"
        # Remove only what this test added, so the session-end report stays true.
        del prod_data_guard._orphaned[orphaned_before:]

    def test_guard_is_installed_from_pytest_configure(self):
        source = inspect.getsource(conftest.pytest_configure)
        assert "prod_data_guard.install(" in source

    def test_conftest_does_not_uninstall_the_guard(self):
        """atexit flushers run after pytest_unconfigure. Uninstalling there
        is what let flush_member_values write real predictions.db rows."""
        assert not hasattr(conftest, "pytest_unconfigure"), (
            "conftest must not uninstall the guard -- atexit flushers run "
            "after unconfigure, unguarded. See pytest_sessionfinish."
        )


class TestAtexitFlushersAreAllDrained:
    def test_every_atexit_registered_buffer_is_drained_at_session_end(self):
        """conftest._ATEXIT_FLUSH_BUFFERS must cover every atexit flusher.

        A hand-maintained list of two already failed once: _member_values_
        pending was added later with its own atexit.register and went
        undrained, writing fabricated rows into the real data/predictions.db
        on every run. This reads weather_markets' source so the NEXT
        flusher added cannot repeat it.
        """
        source = inspect.getsource(weather_markets)
        registered = set(re.findall(r"atexit\.register\((\w+)\)", source))
        assert registered, "no atexit.register calls found -- pattern went stale"

        drained = set(conftest._ATEXIT_FLUSH_BUFFERS)
        missing = set()
        for flusher_name in sorted(registered):
            flusher_src = inspect.getsource(getattr(weather_markets, flusher_name))
            buffers = set(re.findall(r"\b(_\w*pending\w*)\b", flusher_src))
            if not buffers & drained:
                missing.add((flusher_name, tuple(sorted(buffers))))
        assert not missing, (
            f"atexit flusher(s) whose buffer conftest never drains: {missing}. "
            f"Their contents flush to the REAL data/ dir at interpreter exit, "
            f"after every isolate_* redirect has been reverted. Add the buffer "
            f"to conftest._ATEXIT_FLUSH_BUFFERS."
        )

    def test_every_registered_flusher_is_unregistered_at_session_end(self):
        """conftest._ATEXIT_FLUSHERS must name every atexit.register target.

        Draining the buffers is a race on its own: anything repopulating one
        between pytest_sessionfinish and true interpreter shutdown still
        flushes to the un-redirected production path. Unregistering the
        flushers removes the race, but only for the ones actually listed.
        """
        source = inspect.getsource(weather_markets)
        registered = set(re.findall(r"atexit\.register\((\w+)\)", source))
        assert registered, "no atexit.register calls found -- pattern went stale"
        missing = registered - set(conftest._ATEXIT_FLUSHERS)
        assert not missing, (
            f"atexit flusher(s) conftest never unregisters: {sorted(missing)}. "
            f"Add them to conftest._ATEXIT_FLUSHERS."
        )

    def test_declared_flushers_all_exist_and_are_callable(self):
        for flusher_name in conftest._ATEXIT_FLUSHERS:
            flusher = getattr(weather_markets, flusher_name, None)
            assert callable(flusher), (
                f"weather_markets.{flusher_name} is missing or not callable -- "
                f"atexit.unregister would silently no-op on it."
            )

    def test_declared_buffers_all_exist(self):
        for buffer_name in conftest._ATEXIT_FLUSH_BUFFERS:
            assert hasattr(weather_markets, buffer_name), (
                f"weather_markets.{buffer_name} does not exist -- it was "
                f"renamed or removed; update conftest._ATEXIT_FLUSH_BUFFERS."
            )


class TestReadsAreAllowedButCounted:
    def test_reading_a_live_production_file_is_allowed_and_recorded(self):
        """The five data/*.json calibration files are legitimate reads today.
        They stay legal, but must show up in the summary so the list can be
        tightened deliberately rather than by accident.

        They were force-tracked in git until batch-79 untracked them; the
        fresh-clone copies now live in seeds/ and paths.py materializes them
        on first import, so they are still present on a CI checkout and this
        test still exercises a real read. The skip below remains the honest
        guard for a clone where that has not happened."""
        if not paths.SEASONAL_WEIGHTS_PATH.exists():
            pytest.skip("data/seasonal_weights.json not present in this clone")
        content = paths.SEASONAL_WEIGHTS_PATH.read_text()
        assert content, "read returned nothing -- the guard broke the read path"
        assert not prod_data_guard._violations, "a read was treated as a mutation"
        assert str(paths.SEASONAL_WEIGHTS_PATH) in prod_data_guard._reads

    def test_read_summary_names_the_files_that_were_read(self):
        prod_data_guard._reads.setdefault(r"C:\fake\data\example.json", set()).add(
            "some::nodeid"
        )
        lines = prod_data_guard.read_summary_lines()
        assert any("example.json" in line for line in lines)
        del prod_data_guard._reads[r"C:\fake\data\example.json"]


# ── dir_fd resolution (CI-only false positive, fixed 2026-08-26) ─────────────


class TestDirFdRelativePaths:
    """shutil.rmtree uses the fd-based _rmtree_safe_fd walk wherever the
    platform supports it, calling os.rmdir(entry.name, dir_fd=topfd) with a
    BARE entry name. _norm()'s abspath() resolved that against the process
    cwd -- the repo root under CI -- so tearing down any tmpdir containing a
    subdirectory named "data" was blocked as if it were the production data/.

    tests/test_calibration.py's TestCalibrateCLI creates exactly that layout,
    and its teardown_method failed on Linux CI while passing on Windows (which
    has no os.supports_dir_fd entries, so rmtree takes the path-based walk).
    """

    def test_bare_relative_name_is_not_judged_against_cwd(self, monkeypatch):
        from tests import prod_data_guard as g

        real = os.path.normcase(os.path.normpath(os.path.abspath("data")))
        monkeypatch.setattr(g, "_data_prefixes", (real,))

        # Positive control: without a dir_fd the bare name IS read as the
        # production dir. This is the exact misjudgement being fixed, so if it
        # ever stops being true the test below proves nothing.
        assert g._under_real_data("data") is True

        # With a dir_fd naming some other directory, it must resolve there.
        monkeypatch.setattr(
            g.os, "readlink", lambda p: os.path.join("/tmp", "pytest-99")
        )
        resolved = g._resolve_at("data", 7)
        assert resolved is not None
        assert g._under_real_data(resolved) is False

    def test_a_dir_fd_pointing_at_real_data_is_still_blocked(self, monkeypatch):
        """The fix must not become a bypass: an fd that really does name the
        production dir still resolves there and still trips."""
        from tests import prod_data_guard as g

        real = os.path.normcase(os.path.normpath(os.path.abspath("data")))
        monkeypatch.setattr(g, "_data_prefixes", (real,))
        monkeypatch.setattr(g.os, "readlink", lambda p: os.path.abspath("data"))

        resolved = g._resolve_at("kill_switch.json", 7)
        assert g._under_real_data(resolved) is True

    def test_unresolvable_fd_declines_to_judge(self, monkeypatch):
        """No /proc (macOS) or a stale fd -> None, meaning "cannot judge".
        Guessing is what produced the false positive, and no production code
        in this repo passes dir_fd at all."""
        from tests import prod_data_guard as g

        def _boom(_p):
            raise OSError("no /proc")

        monkeypatch.setattr(g.os, "readlink", _boom)
        assert g._resolve_at("data", 7) is None

    def test_absolute_path_ignores_dir_fd(self, monkeypatch):
        """The OS ignores dir_fd for an absolute path, so the guard must too
        -- and must not consult readlink at all."""
        from tests import prod_data_guard as g

        def _boom(_p):
            raise AssertionError("readlink must not be called for an abs path")

        monkeypatch.setattr(g.os, "readlink", _boom)
        assert g._resolve_at(os.path.abspath("data"), 7) == os.path.abspath("data")

    def test_no_dir_fd_is_passed_through_unchanged(self):
        from tests import prod_data_guard as g

        assert g._resolve_at("data", None) == "data"

    @pytest.mark.skipif(
        os.rmdir not in os.supports_dir_fd,
        reason="platform has no dir_fd support, so rmtree never takes the fd walk",
    )
    def test_rmtree_of_a_tmpdir_containing_data_is_not_blocked(self, tmp_path):
        """The end-to-end reproduction, on the platform CI actually runs.
        Skipped on Windows, which is precisely why this went unnoticed."""
        import shutil

        victim = tmp_path / "scratch"
        (victim / "data").mkdir(parents=True)
        (victim / "data" / "seasonal_weights.json").write_text("{}")

        shutil.rmtree(victim)
        assert not victim.exists()

    def test_target_guard_actually_consults_dir_fd(self, monkeypatch):
        """Pins the WIRING, not just the helper.

        Mutation-testing caught this gap: reverting _target_guard to
        `_under_real_data(path)` -- i.e. reintroducing the exact CI failure --
        left every other test in this class green, because they exercise
        _resolve_at directly and the end-to-end rmtree case is skipped on
        Windows. Calling the wrapper with a stubbed `original` reproduces the
        fd path on any platform, with no os.supports_dir_fd needed.
        """
        from tests import prod_data_guard as g

        real = os.path.normcase(os.path.normpath(os.path.abspath("data")))
        monkeypatch.setattr(g, "_data_prefixes", (real,))
        monkeypatch.setattr(
            g.os, "readlink", lambda p: os.path.join("/tmp", "pytest-99")
        )

        called = []
        guarded = g._target_guard(lambda *a, **kw: called.append((a, kw)), "os.rmdir")

        # The bare name resolves under the fd's directory, not the cwd.
        guarded("data", dir_fd=7)
        assert called == [(("data",), {"dir_fd": 7})]

        # Positive control: the same bare name with NO dir_fd is still judged
        # against the cwd and still blocked, so the pass above is the fd
        # resolution working rather than the guard being disabled outright.
        with pytest.raises(BaseException) as exc:
            guarded("data")
        assert "data" in str(exc.value)
        assert len(called) == 1
        # _block() also appends to the session ledger, which assert_clean
        # turns into a teardown failure. This one was deliberate, so drop it.
        g._violations.clear()

    def test_move_guard_actually_consults_the_dir_fds(self, monkeypatch):
        """Same wiring check for os.rename/os.replace, which take
        src_dir_fd/dst_dir_fd and had the identical latent false positive."""
        from tests import prod_data_guard as g

        real = os.path.normcase(os.path.normpath(os.path.abspath("data")))
        monkeypatch.setattr(g, "_data_prefixes", (real,))
        monkeypatch.setattr(
            g.os, "readlink", lambda p: os.path.join("/tmp", "pytest-99")
        )

        called = []
        guarded = g._move_guard(
            lambda *a, **kw: called.append((a, kw)), "os.rename -> "
        )

        guarded("data", "data", src_dir_fd=7, dst_dir_fd=8)
        assert len(called) == 1

        with pytest.raises(BaseException):
            guarded("data", "data")
        assert len(called) == 1
        g._violations.clear()  # deliberate block, see the test above
