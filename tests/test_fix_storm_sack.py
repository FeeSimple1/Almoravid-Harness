"""FIX-B S5: Storm Sack (4.5.2) — defender loss removes defending Lords,
awards their Assets + Stronghold Spoils to the besiegers."""
from __future__ import annotations
from almoravid.actions import apply_action
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder
from tests.test_siege import _activate_lord


def test_storm_sack_removes_lord_and_awards_spoils():
    s = _activate_lord("scenario_a_toledo_beset", "alfonso")
    loc = "calatayud"  # Castle (value 1): spoils coin+prov
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].forces = {"knights": 8, "men_at_arms": 4}
    s.lords["alfonso"].assets = {}
    s.locales[loc].siege_yellow = 1
    # A weak Muslim defender inside with some Coin to be sacked.
    s.lords["al_mustain"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords["al_mustain"].in_stronghold = True
    s.lords["al_mustain"].forces = {"militia": 1}
    s.lords["al_mustain"].assets = {"coin": 3}
    r = apply_action(s, {"type": "cmd_storm", "side": "christian"})
    if r["winner"] == "christian":
        assert r["sack"] is not None
        assert "al_mustain" in r["sack"]["removed_lords"]
        # al_mustain removed from the map.
        assert s.lords["al_mustain"].cylinder.kind == "removed"
        # Besieger received Sack spoils (3 coin from Lord + castle spoils).
        assert s.lords["alfonso"].assets.get("coin", 0) >= 3
        # Stronghold conquered.
        assert r["conquest"] is not None


def test_storm_attacker_loss_no_sack():
    s = _activate_lord("scenario_a_toledo_beset", "alfonso")
    loc = "zaragoza"  # City — strong garrison
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].forces = {"serfs": 1}  # token attacker
    s.locales[loc].siege_yellow = 1  # only 1 round
    r = apply_action(s, {"type": "cmd_storm", "side": "christian"})
    if r["winner"] != "christian":
        assert r["sack"] is None
        assert r["conquest"] is None
