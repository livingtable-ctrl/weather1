"""/api/run_cron must be able to spawn `cron --sameday-only`.

The same-day scan skips the multi-day analysis pool and forecast prewarm, so
it is cheap enough to run at the local hours where the METAR lock-in is
possible. It is NOT a different capability -- a full scan fires the lock-in
identically -- and nothing scheduled it before. This is the dashboard's route
to it.

The assertions are on the ARGV the endpoint actually builds, not on the
response body alone: a handler that returns {"sameday_only": true} while
spawning a full scan would satisfy the body and be exactly wrong.

KNOWN, ACCEPTED: _make_app() reads the real data/.cb_state.json (the
prod-data-guard reports it). It is a read, not a write, and it is the same
exposure tests/test_p0_16_cron_endpoint.py's identical _make_app() already
has -- isolating it means giving web_app._build_app a circuit-breaker fixture,
which belongs with that harness rather than bolted onto this file. Recorded
here rather than left for the next reader to rediscover in guard output.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest


def _make_app():
    import web_app

    with patch("main.KALSHI_ENV", "demo"):
        app = web_app._build_app(client=MagicMock())
    app.config["TESTING"] = True
    return app


def _auth_headers(password: str = "secret") -> dict:
    encoded = base64.b64encode(f"user:{password}".encode()).decode()
    return {"Authorization": f"Basic {encoded}", "X-Requested-With": "XMLHttpRequest"}


def _spawn(body=None, as_json=True):
    """POST to /api/run_cron and return (response, argv-actually-spawned)."""
    app = _make_app()
    with app.test_client() as c:
        with (
            patch("utils.DASHBOARD_PASSWORD", "secret"),
            patch("cron._is_cron_running", return_value=False),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock(pid=4242)
            # Reset the module-level spawn rate limiter so these tests do not
            # 429 each other depending on execution order.
            import web_app  # noqa: F401

            for rule in app.url_map.iter_rules():
                if str(rule) == "/api/run_cron":
                    view = app.view_functions[rule.endpoint]
                    view._last_spawn = 0.0  # type: ignore[attr-defined]
                    break
            kwargs = {"headers": _auth_headers()}
            if body is not None:
                if as_json:
                    kwargs["json"] = body
                else:
                    kwargs["data"] = body
            resp = c.post("/api/run_cron", **kwargs)
            argv = mock_popen.call_args[0][0] if mock_popen.call_args else None
    return resp, argv


class TestSamedayFlagReachesTheSubprocess:
    def test_sameday_true_appends_the_flag(self):
        resp, argv = _spawn({"sameday_only": True})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert argv is not None, "subprocess.Popen was never called"
        assert argv[-1] == "--sameday-only", argv
        assert "cron" in argv
        assert resp.get_json().get("sameday_only") is True

    def test_sameday_false_runs_a_full_scan(self):
        resp, argv = _spawn({"sameday_only": False})
        assert resp.status_code == 200
        # Negative, with its positive control immediately below: the flag is
        # absent, AND the command really is the cron scan (so this is not
        # passing because nothing was spawned or a different command ran).
        assert "--sameday-only" not in argv, argv
        assert argv[-1] == "cron", argv
        assert resp.get_json().get("sameday_only") is False


class TestBackwardCompatibility:
    def test_no_body_at_all_is_a_full_scan(self):
        """The legacy /signals button posts with no body and no Content-Type.

        get_json() without silent=True raises 415 on that, which would turn
        an existing working button into a hard error.
        """
        resp, argv = _spawn(None)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert "--sameday-only" not in argv, argv
        assert argv[-1] == "cron", argv

    def test_malformed_body_is_a_full_scan_not_a_500(self):
        resp, argv = _spawn("this is not json", as_json=False)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert "--sameday-only" not in argv, argv

    @pytest.mark.parametrize(
        "raw",
        ["[1,2]", '"hello"', "123", "true", "[]", "null", "{}"],
        ids=["list", "string", "number", "bool", "empty-list", "null", "empty-obj"],
    )
    def test_non_object_json_body_is_a_full_scan_not_a_500(self, raw):
        """silent=True suppresses PARSE failures, not SHAPE ones.

        A syntactically valid body whose top level is not an object is
        returned as-is and is truthy, so `or {}` kept it and `.get` raised
        AttributeError -> 500. Found by opus review against the live app:
        list/string/number/bool all 500'd, while [] and null survived on
        falsiness alone -- which is why the earlier "malformed body" test
        passed while this whole class was broken.
        """
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("cron._is_cron_running", return_value=False),
                patch("subprocess.Popen") as mock_popen,
            ):
                mock_popen.return_value = MagicMock(pid=4242)
                for rule in app.url_map.iter_rules():
                    if str(rule) == "/api/run_cron":
                        app.view_functions[rule.endpoint]._last_spawn = 0.0
                        break
                resp = c.post(
                    "/api/run_cron",
                    headers={**_auth_headers(), "Content-Type": "application/json"},
                    data=raw,
                )
                argv = mock_popen.call_args[0][0] if mock_popen.call_args else None
        assert resp.status_code == 200, resp.get_data(as_text=True)
        # Positive control: a scan really was spawned, so the flag's absence
        # below is about the body shape and not about an early return.
        assert argv is not None and argv[-1] == "cron", argv

    def test_body_cannot_smuggle_extra_arguments(self):
        """No part of the request reaches argv, and a non-boolean does not
        opt in at all.

        `is True` rather than bool(): the response echoes which scan the
        caller got, and bool() made {"sameday_only": "false"} a SAME-DAY scan
        whose echo said "true".
        """
        resp, argv = _spawn({"sameday_only": "; rm -rf /"})
        assert resp.status_code == 200
        assert not any("rm -rf" in str(a) for a in argv), argv
        # A non-boolean is a FULL scan, and the echo says so.
        assert "--sameday-only" not in argv, argv
        assert resp.get_json().get("sameday_only") is False

    def test_string_false_is_not_a_sameday_scan(self):
        resp, argv = _spawn({"sameday_only": "false"})
        assert "--sameday-only" not in argv, argv
        assert resp.get_json().get("sameday_only") is False

    def test_flag_is_appended_exactly_once(self):
        _resp, argv = _spawn({"sameday_only": True})
        assert argv.count("--sameday-only") == 1, argv


class TestGuardsStillApply:
    def test_sameday_request_still_blocked_by_the_running_lock(self):
        """The two modes share one lock file and one log; a same-day request
        must not bypass the concurrency guard the full scan obeys."""
        app = _make_app()
        with app.test_client() as c:
            with (
                patch("utils.DASHBOARD_PASSWORD", "secret"),
                patch("cron._is_cron_running", return_value=True),
                patch("subprocess.Popen") as mock_popen,
            ):
                resp = c.post(
                    "/api/run_cron",
                    headers=_auth_headers(),
                    json={"sameday_only": True},
                )
        assert resp.status_code == 409
        # Positive control for the negative above: nothing was spawned.
        assert mock_popen.call_count == 0
