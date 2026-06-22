"""Combat capabilities: C24 Garcia Jimenez (Storm +2 rounds), M17 Arrada
(Storm/Sally +3 Missile Hits at -2 Enemy Armor)."""
from __future__ import annotations

from almoravid.battle import BattleSide, _resolve_step, _storm_setup
from almoravid.scenarios import load_scenario


def test_c24_garcia_jimenez_storm_two_extra_rounds() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    # Put a Christian Conquerable City with 1 Siege marker; Alvar (a C24-
    # eligible captain) is the active storming attacker holding C24.
    loc_id = next(lid for lid, loc in s.locales.items()
                  if loc.base_type == "city" and loc.territory in s.taifas)
    s.locales[loc_id].siege_yellow = 1
    s.lords["alvar_fanez"].capabilities.append("C24")
    s.meta.active_lord_id = "alvar_fanez"
    atk = BattleSide(side="christian", role="attacker",
                     lord_ids=["alvar_fanez"], forces={"knights": 3})
    s.lords["al_mundir"].cylinder = s.lords["al_mundir"].cylinder.__class__(
        kind="locale", locale_id=loc_id)
    deff = BattleSide(side="muslim", role="defender",
                      lord_ids=["al_mundir"], forces={"men_at_arms": 2})
    _ss, max_rounds = _storm_setup(s, atk, deff)
    assert max_rounds == 1 + 2          # base siege(1) + C24 two extra

    # Without C24: base only.
    s.lords["alvar_fanez"].capabilities.remove("C24")
    _ss2, mr2 = _storm_setup(s, atk, deff)
    assert mr2 == 1


def test_m17_arrada_adds_three_missile_hits_at_storm() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    al = s.lords["al_mundir"]
    al.capabilities.append("M17")            # this_lord Arrada
    # Muslim attacker missile step in a Storm; no base missile units, so
    # all hits come from Arrada (3).
    atk = BattleSide(side="muslim", role="attacker", lord_ids=["al_mundir"],
                     forces={"knights": 2})
    deff = BattleSide(side="christian", role="defender", lord_ids=["alfonso"],
                      forces={"men_at_arms": 6})
    res = _resolve_step(s, "1.b", "attacker", "missile", None, atk, deff,
                        context="storm")
    assert res.rounded_hits == 3             # 0 base + 3 Arrada
    assert sum(res.losses.values()) >= 1     # hits applied (at -2 armor)


def test_m17_no_arrada_in_field_battle() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=2)
    s.lords["al_mundir"].capabilities.append("M17")
    atk = BattleSide(side="muslim", role="attacker", lord_ids=["al_mundir"],
                     forces={"knights": 2})
    deff = BattleSide(side="christian", role="defender", lord_ids=["alfonso"],
                      forces={"men_at_arms": 6})
    # context="battle" and no sally flag => Arrada must NOT fire.
    res = _resolve_step(s, "1.b", "attacker", "missile", None, atk, deff,
                        context="battle")
    assert res.rounded_hits == 0
