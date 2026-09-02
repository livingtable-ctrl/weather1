"""cmd_menu's Same-day entry must actually run a same-day scan.

The menu dispatches on the STRIPPED label, so the option tuple and the
`elif name_stripped == ...` branch are two halves of one contract living ~200
lines apart. Renaming either silently turns the menu entry into a no-op that
falls through to the unknown-choice path -- nothing else in the suite would
notice, because every other menu test drives a different option.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, patch

import pytest

MENU_KEY = "D"
MENU_LABEL = "Same-day"


def _top_options() -> list[tuple[str, str, str]]:
    """Extract cmd_menu's option table from source.

    Read from source rather than by calling cmd_menu(), which loops on stdin
    and touches the paper ledger; the table is a literal, so this is exact.
    """
    import inspect

    import main

    src = inspect.getsource(main.cmd_menu)
    block = re.search(r"top_options = \[(.*?)\n    \]", src, re.S)
    assert block, "cmd_menu no longer has a `top_options = [...]` literal"
    return re.findall(
        r'\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)', block.group(1)
    )


class TestMenuEntry:
    def test_sameday_option_is_present_with_a_unique_key(self):
        opts = _top_options()
        keys = [k.lower() for k, _lbl, _d in opts]
        assert MENU_KEY.lower() in keys, f"no {MENU_KEY!r} shortcut in cmd_menu: {keys}"
        # A duplicate key would make key_map silently resolve to whichever
        # entry came last, sending the operator to the wrong command.
        assert len(keys) == len(set(keys)), f"duplicate menu shortcut: {keys}"

        labels = [lbl.strip() for _k, lbl, _d in opts]
        assert MENU_LABEL in labels, f"no {MENU_LABEL!r} label: {labels}"

    def test_label_width_matches_its_siblings(self):
        """Labels are space-padded to a fixed width for column alignment."""
        opts = _top_options()
        widths = {len(lbl) for _k, lbl, _d in opts}
        assert len(widths) == 1, f"menu labels are no longer uniform width: {widths}"

    def test_dispatch_branch_exists_for_the_stripped_label(self):
        """The half that actually runs. Guards the rename-one-side failure."""
        import inspect

        import main

        src = inspect.getsource(main.cmd_menu)
        assert f'name_stripped == "{MENU_LABEL}"' in src, (
            f"cmd_menu has a {MENU_LABEL!r} option but no dispatch branch for it"
        )


class TestDispatchRunsASamedayScan:
    @pytest.mark.parametrize(
        "label,expect_sameday",
        [("Same-day", True), ("Cron", False)],
    )
    def test_branch_passes_the_right_sameday_flag(self, label, expect_sameday):
        """Drive cmd_menu once with a scripted choice and assert what
        cmd_cron actually received.

        Cron is included as the control: without it this would pass just as
        happily against an implementation that hardcoded sameday_only=True for
        BOTH menu entries.
        """
        import main

        opts = _top_options()
        index = next(
            str(i) for i, (_k, lbl, _d) in enumerate(opts, 1) if lbl.strip() == label
        )
        answers = iter([index, "q"])

        calls: list[dict] = []

        def _fake_cron(client, **kwargs):
            calls.append(kwargs)

        with (
            patch.object(main, "cmd_cron", _fake_cron),
            patch("builtins.input", lambda *_a, **_kw: next(answers)),
            # patch("paper.get_balance"), NOT patch.object(main, "paper_balance",
            # create=True): cmd_menu does `from paper import get_balance as
            # paper_balance` as a FUNCTION-LOCAL import, so the name is never an
            # attribute of `main` and create=True silently manufactured one that
            # nothing read. Patching the source module fails loudly if the
            # import ever moves, and actually keeps the banner off the real
            # paper ledger.
            patch("paper.get_balance", return_value=0.0),
        ):
            try:
                main.cmd_menu(MagicMock())
            except (StopIteration, SystemExit):
                pass

        assert calls, f"{label} branch never reached cmd_cron"
        assert calls[0].get("sameday_only", False) is expect_sameday, (
            f"{label} called cmd_cron with {calls[0]!r}"
        )
