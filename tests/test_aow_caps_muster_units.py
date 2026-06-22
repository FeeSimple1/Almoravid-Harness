"""Muster-units capabilities: C13/M23 Count of Barcelona, C18 Milites,
M15 Saqalibah, M20 Al-Rum, C22 Bishoprics."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def _act(s, lord_id, side):
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = side
    s.meta.active_lord_id = lord_id
    s.meta.actions_remaining = 2


def _deploy(s, card, side):
    s.decks.capabilities_in_play.append(
        CardInPlay(card_id=card, scope="side_wide", owner_side=side))


def test_c13_count_of_barcelona_musters_units_for_2_coin() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _deploy(s, "C13", "christian")
    s.meta.count_of_barcelona_side = "christian"
    sancho = s.lords["sancho"]
    sancho.cylinder = Cylinder(kind="locale", locale_id="leon")
    sancho.assets = {"coin": 3}
    k0 = sancho.forces.get("knights", 0)
    _act(s, "sancho", "christian")
    assert any(m["type"] == "cap_count_barcelona" for m in legal_moves(s))
    apply_action(s, {"type": "cap_count_barcelona", "side": "christian"})
    assert sancho.forces.get("knights", 0) == k0 + 2
    assert sancho.forces.get("men_at_arms", 0) >= 2
    assert sancho.assets["coin"] == 1            # paid 2
    # once only
    assert not any(m["type"] == "cap_count_barcelona" for m in legal_moves(s))


def test_m23_count_blocked_when_count_on_christian_side() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _deploy(s, "M23", "muslim")
    s.meta.count_of_barcelona_side = "christian"   # not with Muslims
    al = s.lords["al_mustain"]
    al.cylinder = Cylinder(kind="locale", locale_id="zaragoza")
    al.assets = {"coin": 3}
    _act(s, "al_mustain", "muslim")
    assert not any(m["type"] == "cap_count_barcelona" for m in legal_moves(s))


def test_m15_saqalibah_musters_two_maa_free() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _deploy(s, "M15", "muslim")
    al = s.lords["al_mundir"]
    al.cylinder = Cylinder(kind="locale", locale_id="valencia")
    m0 = al.forces.get("men_at_arms", 0)
    _act(s, "al_mundir", "muslim")
    assert any(m["type"] == "cap_saqalibah" for m in legal_moves(s))
    apply_action(s, {"type": "cap_saqalibah", "side": "muslim"})
    assert al.forces.get("men_at_arms", 0) == m0 + 2
    assert not any(m["type"] == "cap_saqalibah" for m in legal_moves(s))


def test_m20_al_rum_pays_taifa_box_coin_for_two_knights() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _deploy(s, "M20", "muslim")
    al = s.lords["al_mundir"]
    # Move to an isolated Locale so no co-located Sharing; only the box pays.
    al.cylinder = Cylinder(kind="locale", locale_id="huesca")
    for L in s.lords.values():
        if L.side == "muslim" and L.id != "al_mundir":
            L.cylinder = Cylinder(kind="calendar", box=1)
    al.assets = {}                       # no own coin -> use Taifas box
    s.taifas_box_coin = 2
    k0 = al.forces.get("knights", 0)
    _act(s, "al_mundir", "muslim")
    apply_action(s, {"type": "cap_al_rum", "side": "muslim"})
    assert al.forces.get("knights", 0) == k0 + 2
    assert s.taifas_box_coin == 1


def test_c18_milites_takes_up_to_three_units_for_one_asset() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _deploy(s, "C18", "christian")
    al = s.lords["alvar_fanez"]
    al.cylinder = Cylinder(kind="locale", locale_id="leon")
    al.assets = {"prov": 1}
    lh0 = al.forces.get("light_horse", 0)
    _act(s, "alvar_fanez", "christian")
    apply_action(s, {"type": "cap_milites", "side": "christian",
                     "units": {"light_horse": 3}})
    assert al.forces.get("light_horse", 0) == lh0 + 3
    assert al.assets.get("prov", 0) == 0
    # pool decremented; same Lord can't take again
    assert not any(m["type"] == "cap_milites" and m.get("side") == "christian"
                   and s.meta.active_lord_id == "alvar_fanez"
                   for m in legal_moves(s))


def test_c22_bishoprics_adds_ready_bishop_vassal() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    _deploy(s, "C22", "christian")
    al = s.lords["alvar_fanez"]
    al.cylinder = Cylinder(kind="locale", locale_id="leon")
    nv0 = len(al.vassals)
    _act(s, "alvar_fanez", "christian")
    apply_action(s, {"type": "cap_bishoprics", "side": "christian",
                     "target_lord_id": "alvar_fanez"})
    assert len(al.vassals) == nv0 + 1
    bishop = al.vassals[-1]
    assert bishop.ready and bishop.forces.get("knights", 0) == 1
    # Sancho is ineligible
    assert not any(m.get("target_lord_id") == "sancho"
                   for m in legal_moves(s) if m["type"] == "cap_bishoprics")
