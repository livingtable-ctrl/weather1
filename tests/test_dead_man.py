"""Dead man's switch: heartbeat staleness, and .env configurability.

batch-84 item 2 (backlog.txt "`py watchdog.py` NEVER CALLS load_dotenv, SO
ITS ntfy PUSH ALERT CANNOT BE CONFIGURED FROM .env") adds
TestWatchdogDotenvBootstrap below.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

import pytest


def test_heartbeat_stale_detection(tmp_path, monkeypatch):
    import watchdog

    monkeypatch.setattr(watchdog, "HEARTBEAT_PATH", tmp_path / "last_heartbeat.txt")

    # No file → stale
    assert watchdog.is_heartbeat_stale(max_age_hours=48) is True

    # Recent file → not stale
    heartbeat_file = tmp_path / "last_heartbeat.txt"
    heartbeat_file.write_text(datetime.now(UTC).isoformat())
    assert watchdog.is_heartbeat_stale(max_age_hours=48) is False

    # Old file → stale
    old_time = (datetime.now(UTC) - timedelta(hours=49)).isoformat()
    heartbeat_file.write_text(old_time)
    assert watchdog.is_heartbeat_stale(max_age_hours=48) is True


# ─────────────────────────────────────────────────────────────────────────────
# batch-84 item 2 -- backlog.txt "`py watchdog.py` NEVER CALLS load_dotenv,
# SO ITS ntfy PUSH ALERT CANNOT BE CONFIGURED FROM .env"
# ─────────────────────────────────────────────────────────────────────────────

# Every key any child .env below sets must appear here, or the child would
# read the operator's REAL value out of the inherited environment and pass
# for the wrong reason (the lesson batch-79's own _B79_SCRUBBED_ENV_KEYS
# comment records). Currently exactly NTFY_TOPIC (all five children) and
# B84_PROBE (one) -- opus review I-5 caught a third entry here that no child
# actually sets, which made the comment above read as a correspondence it
# did not have.
_B84_SCRUBBED_ENV_KEYS = frozenset({"NTFY_TOPIC", "B84_PROBE"})


class _FakeRequests:
    """Records the ntfy POST instead of making one.

    Used by the IN-PROCESS tests only. The child processes each build their
    own inline fake in their source string rather than sharing this one --
    unavoidable, since a child is a separate interpreter that receives its
    body as text and cannot import a class from this module's namespace.

    `status` drives raise_for_status so the HTTP-error branch is reachable:
    ntfy answering 4xx/5xx must not be logged as a delivered alert.
    """

    def __init__(self, status: int = 200) -> None:
        self.calls: list[tuple] = []
        self._status = status

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        status = self._status

        class _Resp:
            status_code = status

            def raise_for_status(self) -> None:
                if status >= 400:
                    raise RuntimeError(f"{status} Server Error")

        return _Resp()


class TestWatchdogDotenvBootstrap:
    """`py watchdog.py` must read .env the way main.py and web_app.py do.

    The module docstring tells the operator to "set NTFY_TOPIC in .env", and
    this is a real standalone entry point that never goes through main.py, so
    the one documented way to configure the dead man's switch did nothing.

    Every assertion here runs in a CHILD process, and has to: conftest.py
    imports main before any test runs, and main.py calls load_dotenv() at
    import, so by the time a test body executes this pytest process has
    already read the repo's real .env. Nothing in-process can distinguish
    "watchdog loaded it" from "something else already had".

    How the child's .env is controlled (verified by batch-79 against
    python-dotenv's find_dotenv, 2026-08-26): find_dotenv normally walks up
    from the CALLING frame's file, which for a real script would be this
    repo's own directory and its live .env. In a ``python -c`` child,
    __main__ has no __file__, dotenv's _is_interactive() check returns True,
    and the search starts from the working directory instead -- so running
    with cwd=tmp_path and a .env written there is fully hermetic.

    The value-carrying test is parametrized over two different topics,
    neither of them any default, so a pass cannot come from a constant.
    """

    @staticmethod
    def _child(
        tmp_path, env_body: str, body: str, extra_env: dict | None = None
    ) -> dict:
        """Run `body` in a child with `env_body` as its .env. Returns its JSON."""
        import json as _json
        import os as _os
        import subprocess
        import sys as _sys
        from pathlib import Path as _Path

        import watchdog as _wd

        (tmp_path / ".env").write_text(env_body, encoding="utf-8")
        repo = str(_Path(_wd.__file__).resolve().parent)

        # Step 21: redirect project_root() before paths.py is imported, so
        # the child's DATA_DIR (and paths.materialize_missing_seeds) can
        # never reach the real data/ directory. The child bypasses
        # conftest's prod_data_guard entirely, exactly like any other
        # standalone script. Computed ONCE, under tmp_path, so safe_io's
        # emergency-write fallbacks re-calling project_root() land in the
        # same place rather than a fresh mkdtemp each time.
        root = tmp_path / "root"
        root.mkdir(exist_ok=True)
        preamble = (
            "import json, os, pathlib, sys\n"
            f"sys.path.insert(0, {repo!r})\n"
            "import safe_io\n"
            f"_ROOT = pathlib.Path({str(root)!r})\n"
            "safe_io.project_root = lambda: _ROOT\n"
        )
        env = {k: v for k, v in _os.environ.items() if k not in _B84_SCRUBBED_ENV_KEYS}
        env["PYTHONIOENCODING"] = "utf-8"
        env.update(extra_env or {})
        proc = subprocess.run(
            [_sys.executable, "-c", preamble + body],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, (
            f"child exited {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
        return _json.loads(proc.stdout.strip().splitlines()[-1])

    @pytest.mark.parametrize("configured", ["b84-alpha-topic", "b84-beta-topic"])
    def test_a_topic_set_in_dotenv_reaches_the_actual_ntfy_post(
        self, tmp_path, configured
    ):
        """The user-visible fix, asserted at the push call itself.

        Not merely "load_dotenv was called" and not merely "os.environ has
        the value" -- the URL send_alert actually posts to is the thing the
        operator cares about, and it is built from os.getenv("NTFY_TOPIC")
        at call time.
        """
        out = self._child(
            tmp_path,
            f"NTFY_TOPIC={configured}\n",
            "import watchdog\n"
            "import types\n"
            "posted = {}\n"
            "fake = types.ModuleType('requests')\n"
            "def _post(url, **kw):\n"
            "    posted['url'] = url\n"
            "    posted['title'] = (kw.get('headers') or {}).get('Title')\n"
            "    class R:\n"
            "        def raise_for_status(self): pass\n"
            "    return R()\n"
            "fake.post = _post\n"
            "sys.modules['requests'] = fake\n"
            "watchdog.send_alert('bot has not run in 48+ hours')\n"
            "print(json.dumps({'url': posted.get('url'),"
            " 'title': posted.get('title')}))\n",
        )
        assert out["url"] == f"https://ntfy.sh/{configured}"
        # Positive control: this really is watchdog's own alert path, not
        # some other post that happened to fire.
        assert out["title"] == "Kalshi Bot Dead Man Switch"

    def test_a_blank_topic_in_dotenv_is_treated_as_unconfigured(self, tmp_path):
        """The third state this item newly made reachable (opus review M-1).

        Before .env was read, os.getenv("NTFY_TOPIC") could only be None or a
        deliberately-exported value. Now `NTFY_TOPIC=` -- exactly what you get
        by uncommenting .env.example's `# NTFY_TOPIC=my_kalshi_bot_alerts` and
        deleting the placeholder -- produces an empty string.

        send_alert's guard is `if not topic`, which handles that correctly.
        Mutating it to `if topic is None` left all eight tests green, and the
        resulting behaviour is a dead man's switch POSTing to the bare
        https://ntfy.sh/ root and then logging "alert sent" while nobody is
        notified. This is that mutation's test.
        """
        out = self._child(
            tmp_path,
            "NTFY_TOPIC=\nB84_PROBE=landed\n",
            "import types, watchdog\n"
            "posted = {}\n"
            "fake = types.ModuleType('requests')\n"
            "def _post(url, **kw):\n"
            "    posted['url'] = url\n"
            "    class R:\n"
            "        def raise_for_status(self): pass\n"
            "    return R()\n"
            "fake.post = _post\n"
            "sys.modules['requests'] = fake\n"
            "watchdog.send_alert('bot has not run in 48+ hours')\n"
            "print(json.dumps({'url': posted.get('url'),"
            " 'env': os.getenv('NTFY_TOPIC'), 'probe': os.getenv('B84_PROBE')}))\n",
        )
        assert out["url"] is None, "a blank topic must not be POSTed to"
        # POSITIVE CONTROLS for that absence, in two parts. The .env really
        # was read (a second key from the same file landed), and dotenv
        # really does turn `NTFY_TOPIC=` into "" rather than leaving it
        # unset -- which is what makes the empty-string state reachable at
        # all and the `not topic` guard load-bearing rather than defensive.
        assert out["probe"] == "landed"
        assert out["env"] == "", (
            "dotenv is supposed to produce an empty string for a bare "
            f"`NTFY_TOPIC=`, got {out['env']!r}"
        )

    def test_nothing_but_watchdog_puts_the_topic_in_the_environment(self, tmp_path):
        """Positive control for the test above, and the ordering proof.

        `before` must be None: the child's .env is not inherited, and no
        other import in the chain reads it. That is what makes the `after`
        assertion evidence that watchdog's own load_dotenv() did the work,
        rather than a value that was going to be there anyway.
        """
        out = self._child(
            tmp_path,
            "NTFY_TOPIC=b84-ordering-topic\n",
            "before = os.getenv('NTFY_TOPIC')\n"
            "import watchdog\n"
            "after = os.getenv('NTFY_TOPIC')\n"
            "print(json.dumps({'before': before, 'after': after}))\n",
        )
        assert out["before"] is None, (
            "the child inherited or otherwise already had NTFY_TOPIC, so this "
            "test could not tell watchdog's load_dotenv() apart from noise"
        )
        assert out["after"] == "b84-ordering-topic"

    def test_an_already_set_topic_wins_over_the_dotenv_file(self, tmp_path):
        """No override=True -- an explicitly-set variable must survive.

        cron.py imports this module lazily at runtime, from inside a
        long-lived process. load_dotenv(override=True) there would re-read
        the WHOLE .env mid-cycle and rewrite os.environ under every other
        module, so the non-overriding default is load-bearing rather than
        incidental.
        """
        out = self._child(
            tmp_path,
            "NTFY_TOPIC=from-dotenv\nB84_PROBE=landed\n",
            "import watchdog\n"
            "print(json.dumps({'topic': os.getenv('NTFY_TOPIC'),"
            " 'probe': os.getenv('B84_PROBE')}))\n",
            extra_env={"NTFY_TOPIC": "from-parent-env"},
        )
        assert out["topic"] == "from-parent-env"
        # POSITIVE CONTROL: the .env really was read -- a second variable
        # from the SAME file landed. Without this, an override=False that
        # had silently become "never read the file at all" would pass.
        assert out["probe"] == "landed"

    def test_watchdog_imports_no_env_binding_module_before_load_dotenv(self, tmp_path):
        """Completeness half: the call precedes every env-derived binding.

        batch-79 established that position, not presence, is what matters --
        utils.py binds ~50 constants with module-level float(os.getenv(...))
        and config.get_config() caches its singleton, both frozen for the
        life of the process. The assertion is the whole set of local modules
        rather than an allowlist of names, so a future module-scope `import
        utils` / `import config` / `import weather_markets` above
        load_dotenv() trips it without anyone having to remember to add the
        name here.

        `paths` (and the `safe_io` it pulls in) are the permitted entries:
        neither reads an env var, and watchdog genuinely needs
        LAST_HEARTBEAT_PATH.

        Not a guard on load_dotenv itself -- removing that call leaves this
        test green. The tests above protect the call; this one protects its
        sufficiency.
        """
        out = self._child(
            tmp_path,
            "NTFY_TOPIC=b84-scope-topic\n",
            "_repo = pathlib.Path(sys.path[0])\n"
            "_local = lambda: sorted(\n"
            "    m for m in sys.modules\n"
            "    if (_repo / (m.split('.')[0] + '.py')).exists()\n"
            ")\n"
            "import watchdog\n"
            "before = _local()\n"
            "import config\n"
            "import utils\n"
            "print(json.dumps({'before': before, 'after': _local()}))\n",
        )
        allowed = {"watchdog", "paths", "safe_io"}
        # opus review L-4: subset alone passes vacuously if `before` were
        # empty -- e.g. if the child's repo-root heuristic stopped matching
        # the module under test at all. Assert the subject is present first,
        # then keep the subset direction for its future-proofing (batch-79's
        # precedent asserts equality; subset is the safer direction here
        # because `paths` may legitimately grow an env-free dependency).
        assert "watchdog" in out["before"], out["before"]
        assert set(out["before"]) <= allowed, (
            f"watchdog pulled in an unexpected local module at import scope: "
            f"{sorted(set(out['before']) - allowed)}"
        )
        # Positive control: the probe can see local modules when they ARE
        # imported, so the subset assertion above is a real observation and
        # not a probe that never detects anything.
        assert {"config", "utils"} <= set(out["after"])

    def test_the_load_dotenv_call_precedes_the_first_local_import(self):
        """Pin the SOURCE ORDER, which no runtime assertion can observe today.

        opus review I-3: moving load_dotenv() below `from paths import ...`
        leaves all of the tests above green, because paths and safe_io read
        no env vars -- so the position is currently correct by luck of what
        watchdog happens to import rather than by anything under test. The
        set-difference test above catches a future env-binding module added
        at module scope; this catches the other half, the call itself
        sliding down past an import that is already there.

        Bound by position within the file, not by a bare grep: the comment
        block above the call names `load_dotenv` several times, so a
        containment check has to compare the CALL's offset.
        """
        from pathlib import Path

        import watchdog

        src = Path(watchdog.__file__).read_text(encoding="utf-8")
        call = src.index("\nload_dotenv()")
        first_local_import = src.index("\nfrom paths import")
        assert call < first_local_import, (
            "load_dotenv() must run before the first local import"
        )
        # Positive control: both anchors were actually found and are
        # distinct, so the comparison is over two real offsets rather than
        # two -1s or one repeated match.
        assert call >= 0 and first_local_import > call
        assert src.count("\nload_dotenv()") == 1


class TestSendAlertChannel:
    """send_alert's two branches, which the .env fix decides between."""

    def test_a_configured_topic_posts_to_ntfy(self, monkeypatch):
        import watchdog

        fake = _FakeRequests()
        monkeypatch.setitem(sys.modules, "requests", fake)
        monkeypatch.setenv("NTFY_TOPIC", "b84-inproc-topic")

        watchdog.send_alert("bot is down")

        assert len(fake.calls) == 1
        url, kwargs = fake.calls[0]
        assert url == "https://ntfy.sh/b84-inproc-topic"
        assert kwargs["data"] == b"bot is down"
        # opus review I-4: the request's own shape was unasserted, so
        # dropping either of these left the suite green. `urgent` is what
        # gets the alert past a phone's do-not-disturb -- the entire point of
        # a push channel for a dead man's switch -- and a missing timeout
        # would hang the alert on an unresponsive ntfy.sh indefinitely.
        assert kwargs["headers"]["Priority"] == "urgent"
        assert kwargs["headers"]["Tags"] == "warning"
        assert kwargs["timeout"] == 10

    def test_an_http_error_from_ntfy_is_not_logged_as_a_delivered_alert(
        self, monkeypatch, caplog
    ):
        """opus review I-4: deleting resp.raise_for_status() left every test
        green, and the result is the worst shape available here -- a dead
        man's switch writing "WATCHDOG alert sent to ntfy.sh/<topic>" for a
        push that ntfy answered 500 to.
        """
        import logging

        import watchdog

        fake = _FakeRequests(status=500)
        monkeypatch.setitem(sys.modules, "requests", fake)
        monkeypatch.setenv("NTFY_TOPIC", "b84-http-error")

        with caplog.at_level(logging.INFO, logger="watchdog"):
            watchdog.send_alert("bot is down")

        messages = [r.getMessage() for r in caplog.records]
        assert not any("alert sent to" in m for m in messages), messages
        # POSITIVE CONTROLS for that absence: the POST really was attempted
        # (so the success line had a chance to be written), and the failure
        # was recorded rather than swallowed silently.
        assert len(fake.calls) == 1
        assert any("failed to send alert" in m for m in messages), messages

    def test_a_successful_post_does_log_the_delivery(self, monkeypatch, caplog):
        """Paired control for the test above: the success line is reachable,
        so its absence there is about the 500 and not about the log level or
        the logger name."""
        import logging

        import watchdog

        fake = _FakeRequests(status=200)
        monkeypatch.setitem(sys.modules, "requests", fake)
        monkeypatch.setenv("NTFY_TOPIC", "b84-http-ok")

        with caplog.at_level(logging.INFO, logger="watchdog"):
            watchdog.send_alert("bot is down")

        messages = [r.getMessage() for r in caplog.records]
        assert any("alert sent to ntfy.sh/b84-http-ok" in m for m in messages), messages
        assert not any("failed to send alert" in m for m in messages), messages

    def test_no_topic_falls_back_to_the_log_and_posts_nothing(
        self, monkeypatch, caplog
    ):
        """The pre-fix behaviour for every alert, and still correct when the
        operator genuinely has not configured ntfy."""
        import logging

        import watchdog

        fake = _FakeRequests()
        monkeypatch.setitem(sys.modules, "requests", fake)
        monkeypatch.delenv("NTFY_TOPIC", raising=False)

        with caplog.at_level(logging.WARNING, logger="watchdog"):
            watchdog.send_alert("bot is down")

        assert fake.calls == [], "nothing may be posted without a configured topic"
        # POSITIVE CONTROL (step 28) for that empty list: the alert really
        # was processed -- it reached the fallback branch and named the very
        # variable this item made configurable -- rather than send_alert
        # having returned early or never been called at all.
        messages = [r.getMessage() for r in caplog.records]
        assert any("NTFY_TOPIC" in m and "bot is down" in m for m in messages), messages
