"""Repro: get_emos_status() mislabels a file-vanished race as file corruption.

Forces the exact TOCTOU window: exists() returns True (file WAS there a
moment ago) but the file is gone by the time read_text() runs -- simulating
a concurrent deactivate_emos() deleting it in between.
"""
import sys, pathlib
sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")
import ml_bias

tmp = pathlib.Path(r"C:\Users\thesa\AppData\Local\Temp\claude\C--Users-thesa-claude-kalshi--claude-worktrees-reverent-lumiere-f79c1f\b50706cb-f334-4fea-a520-cae9990efdda\scratchpad\emos_params_repro.json")
tmp.write_text('{"a":1,"b":2,"c":3,"d":4}')
ml_bias._EMOS_PARAMS_PATH = tmp

_real_exists = pathlib.Path.exists
def fake_exists(self):
    if self == tmp:
        tmp.unlink()  # simulate concurrent deactivate_emos() deleting it right here
        return True
    return _real_exists(self)

pathlib.Path.exists = fake_exists
try:
    result = ml_bias.get_emos_status()
finally:
    pathlib.Path.exists = _real_exists

print("result:", result)
print("mislabeled as corrupt during a pure deletion race?", result.get("corrupt") is True)
