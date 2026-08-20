"""Independent re-derivation (Pass 8 verification) of the METAR settlement
force-close gate reachability claim.

Formula reproduced from ml_bias.apply_metar_calibration's exact docstring:
    sigmoid(a*ln(s) - b*ln(1-s) + c)
with params (a, a, c) as fit_metar_calibration always returns (Platt-
equivalent), cited coefficients a=b=0.2262, c=0.4001 (from settlement_monitor.py's
_calibrate_metar_settlement_confidence docstring, commit d320142d).

Raw confidence domain reproduced from metar._dynamic_lock_in_confidence's
hard round(min(0.97, max(0.72, conf)), 3) bound -> [0.72, 0.97].

settlement_monitor.py's _calibrate_metar_settlement_confidence conversion:
    raw_p_yes = confidence if outcome == "yes" else (1.0 - confidence)
    new_p_yes = apply_metar_calibration(raw_p_yes, metar_cal)
    new_confidence = new_p_yes if outcome == "yes" else (1.0 - new_p_yes)
"""
import math


def sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def apply_metar_calibration(raw_prob, params):
    a, b, c = params
    eps = 1e-6
    s = min(max(raw_prob, eps), 1 - eps)
    return sigmoid(a * math.log(s) - b * math.log(1 - s) + c)


a = b = 0.2262
c = 0.4001
params = (a, b, c)

N = 100_000
max_yes = -1.0
argmax_yes = None
max_no = -1.0
argmax_no = None

for i in range(N + 1):
    raw = 0.72 + (0.97 - 0.72) * i / N

    # YES-lock direction: confidence == raw is already P(YES)
    raw_p_yes = raw
    new_p_yes = apply_metar_calibration(raw_p_yes, params)
    new_confidence_yes = new_p_yes
    if new_confidence_yes > max_yes:
        max_yes = new_confidence_yes
        argmax_yes = raw

    # NO-lock direction: confidence == raw means P(NO)=raw -> P(YES)=1-raw
    raw_p_yes_for_no = 1.0 - raw
    new_p_yes_for_no = apply_metar_calibration(raw_p_yes_for_no, params)
    new_confidence_no = 1.0 - new_p_yes_for_no
    if new_confidence_no > max_no:
        max_no = new_confidence_no
        argmax_no = raw

print(f"max calibrated YES-lock confidence = {max_yes:.4f} at raw={argmax_yes:.4f}")
print(f"max calibrated NO-lock confidence  = {max_no:.4f} at raw={argmax_no:.4f}")
print(f"global max = {max(max_yes, max_no):.4f}")
print("gate threshold = 0.80")
print(f"gate reachable? {max(max_yes, max_no) >= 0.80}")
