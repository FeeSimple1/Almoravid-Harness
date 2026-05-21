"""Relief Sally per-Lord lane Losses (4.4.1): a lane with multiple Lords
commits Losses to the Lords that actually took them, not proportionally
split across the lane."""

from __future__ import annotations

from almoravid.battle import resolve_relief_sally
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder


def test_sallyer_lane_losses_attributed_per_lord() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    # Two Sallying Lords: A = Knights only, B = Serfs only. Serfs are
    # weakest -> absorbed first, so all early Losses fall on B; A's
    # Knights stay intact (per-Lord, not proportional).
    a, b = "alfonso", "alvar_fanez"
    for lid in (a, b):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
    s.lords[a].forces = {"knights": 3}
    s.lords[b].forces = {"serfs": 4}
    # One besieger (Muslim) defending in the field, modest force.
    d = "al_mustain"
    s.lords[d].cylinder = Cylinder(kind="locale", locale_id="zamora")
    s.lords[d].in_stronghold = False
    s.lords[d].forces = {"men_at_arms": 1}
    s.locales["zamora"].siege_green = 1   # 1-round Storm cap (besieger Muslim)
    result, lanes = resolve_relief_sally(
        s, [], [a, b], [d], besieger_side="muslim", locale_id="zamora",
        max_rounds=1)
    # A's Knights are untouched (Serfs absorbed the besieger's Hits).
    assert s.lords[a].forces.get("knights", 0) == 3
    # B (Serfs) bore any Losses; sum is consistent with starting count.
    surv = s.lords[b].forces.get("serfs", 0)
    routed = s.lords[b].routed_units.get("serfs", 0)
    assert surv + routed == 4
    # A took no Routs.
    assert not s.lords[a].routed_units


def test_disjoint_lanes_only_their_targets_take_losses() -> None:
    """Marchers hit Front Defenders; Sallyers hit Reserve Defenders —
    each Defender Lord's Losses are tracked on that Lord alone."""
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    m, sal = "alfonso", "alvar_fanez"
    for lid in (m, sal):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
    s.lords[m].forces = {"knights": 12}    # marcher: wipes Front Defender
    s.lords[sal].forces = {"serfs": 1}     # negligible sallyer
    df, dr = "al_mustain", "abu_bakr"
    for lid in (df, dr):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id="zamora")
        s.lords[lid].in_stronghold = False
    s.lords[df].forces = {"serfs": 1}      # Front Defender (faces marcher)
    s.lords[dr].forces = {"men_at_arms": 6}  # Reserve Defender (faces sallyer)
    s.locales["zamora"].siege_green = 1
    result, lanes = resolve_relief_sally(
        s, [m], [sal], [df, dr], besieger_side="muslim",
        locale_id="zamora", max_rounds=1)
    # Front Defender (df) cleared by the strong marcher.
    assert s.lords[df].forces.get("serfs", 0) == 0
    # Reserve Defender (dr) only faced the 1 negligible Sallyer Serf, so
    # is essentially intact (>=5 of 6 Men-at-Arms).
    assert s.lords[dr].forces.get("men_at_arms", 0) >= 5
