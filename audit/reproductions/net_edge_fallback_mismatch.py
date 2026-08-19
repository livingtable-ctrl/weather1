"""
Independent reproduction: does trade_cycle.py's placement-gate mirror
(added in commit c9b0fc02) actually agree with order_executor.py's real
_validate_trade_opportunity() net_edge check, for the specific case where
analysis["net_edge"] is None but analysis["edge"] (raw edge) is a real,
positive number?

This reproduces BOTH pieces of logic verbatim (byte-for-byte copied from
the current source, cited below) on the SAME synthetic analysis dict, and
prints whether they agree.

Source snippets copied from:
  trade_cycle.py L467-471 (net_edge None-safe fallback)
  trade_cycle.py L649-654 (placement gate net_edge<=0 check, from the
      commit c9b0fc02 diff: "if net_edge <= 0: clears_placement_gate = False")
  order_executor.py L2011-2015 (_validate_trade_opportunity's real net_edge
      check)
"""


def trade_cycle_net_edge_fallback(analysis: dict):
    """Verbatim copy of trade_cycle.py lines 467-471."""
    net_edge = analysis.get("net_edge")
    if net_edge is None:
        net_edge = analysis.get("edge")
    if net_edge is None:
        net_edge = 0.0
    return net_edge


def trade_cycle_clears_placement_gate(analysis: dict, side: str, MIN_EDGE: float):
    """Verbatim copy of trade_cycle.py's placement-gate logic added in
    c9b0fc02 (lines ~649-660 in current source)."""
    net_edge = trade_cycle_net_edge_fallback(analysis)
    raw_edge = analysis.get("edge")
    clears_placement_gate = True
    if net_edge <= 0:
        clears_placement_gate = False
    if raw_edge is not None:
        if side == "yes" and raw_edge <= 0:
            clears_placement_gate = False
        elif side == "no" and raw_edge >= 0:
            clears_placement_gate = False
        elif abs(raw_edge) < MIN_EDGE:
            clears_placement_gate = False
    return clears_placement_gate


def validate_edge_check(opp: dict, MIN_EDGE: float):
    """Verbatim copy of order_executor.py's _validate_trade_opportunity
    edge-check block, lines 2011-2024 (skipping the confidence-tier/AB-test
    and Kelly checks, which are unrelated to this specific fallback
    question)."""
    edge = opp.get("net_edge")
    if edge is None:
        edge = 0.0
    if edge <= 0:
        return False, f"edge={edge:.4f} <= 0"
    if opp.get("edge") is not None:
        raw_edge = opp["edge"]
        side = opp.get("recommended_side", "yes")
        if side == "yes" and raw_edge <= 0:
            return False, f"raw_edge={raw_edge:.4f} <= 0 for YES recommendation"
        if side == "no" and raw_edge >= 0:
            return False, f"raw_edge={raw_edge:.4f} >= 0 for NO recommendation"
        if abs(raw_edge) < MIN_EDGE:
            return False, f"raw_edge={raw_edge:.4f} below MIN_EDGE={MIN_EDGE:.4f}"
    return True, "edge checks passed"


# --- Reproduction: net_edge is None (absent from a real analyze_trade dict
# shape -- e.g. a code path that never populates it), but "edge" (raw edge)
# is a real, clearly-positive value that would itself clear MIN_EDGE.
MIN_EDGE = 0.07  # utils.py default

analysis = {
    "net_edge": None,
    "edge": 0.30,
    "recommended_side": "yes",
    "adjusted_edge": 0.30,  # so the tier-magnitude check upstream also passes
}

tc_gate = trade_cycle_clears_placement_gate(analysis, "yes", MIN_EDGE)
ok, reason = validate_edge_check(analysis, MIN_EDGE)

print(f"analysis = {analysis}")
print(f"trade_cycle.py placement-gate mirror: clears_placement_gate = {tc_gate}")
print(f"order_executor.py real validate(): ok={ok}, reason={reason!r}")
print()
if tc_gate and not ok:
    print("MISMATCH CONFIRMED: trade_cycle.py's mirror says this candidate clears "
          "the placement gate (eligible for STRONG/MED tier), but the real "
          "validate() gate would reject it outright.")
else:
    print("No mismatch in this scenario.")
