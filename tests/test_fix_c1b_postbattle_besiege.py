"""FIX-C / C1b: Besiege-or-Bypass after a Battle-loss Withdraw (4.3.5).

When the losing Enemy Withdraws into the Stronghold at the Battle Locale
and the winning Active side has Lord(s) outside it (Unbesieged/
Unbypassed), the Active side must immediately choose Besiege or Bypass.
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, PendingDecision


def _stand_battle(seed):
    s = load_scenario("scenario_a_toledo_beset", seed=seed)
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="zaragoza")
    s.lords["alvar_fanez"].in_stronghold = False
    s.lords["alvar_fanez"].forces = {"knights": 12}     # strong attacker
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale",
                                              locale_id="zaragoza")
    s.lords["al_mustain"].in_stronghold = False
    s.lords["al_mustain"].forces = {"men_at_arms": 8}   # armored, survives
    s.meta.active_lord_id = "alvar_fanez"
    s.meta.actions_remaining = 2
    s.locales["zaragoza"].siege_yellow = 0
    s.locales["zaragoza"].bypass_yellow = False
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": "zaragoza", "from_locale_id": "calatayud",
                 "via_way_type": "road", "active_lord_id": "alvar_fanez",
                 "active_side": "christian", "defender_lord_ids": ["al_mustain"]})
    s.meta.active_player = "muslim"
    apply_action(s, {"type": "respond_stand_battle", "side": "muslim"})
    return s


def test_post_battle_withdraw_triggers_besiege_or_bypass() -> None:
    s = _stand_battle(seed=0)
    assert s.lords["al_mustain"].in_stronghold is True   # loser withdrew
    assert s.pending is not None
    assert s.pending.kind == "besiege_or_bypass"
    assert s.pending.waiting_on == "christian"


def test_post_battle_besiege_choice_places_marker() -> None:
    s = _stand_battle(seed=0)
    apply_action(s, {"type": "respond_besiege", "side": "christian"})
    assert s.locales["zaragoza"].siege_yellow == 1
    assert s.pending is None
    from almoravid.effective import is_besieged
    assert is_besieged(s, "al_mustain") is True
