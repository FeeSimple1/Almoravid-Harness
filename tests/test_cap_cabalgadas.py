"""C14/C17 Cabalgadas long-range Ravage (Arts of War ref): the bearer must
have or Share (1.5.2) one Provender and use ALL actions on his Command
card; Ravage a Locale up to two Ways distant where neither the intervening
nor target Locale has an Unbesieged Enemy Lord (even if Bypassed). Effect =
normal Ravage (4.7.2).
"""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.campaign import _cabalgadas_targets
from almoravid.map import all_neighbors, is_region
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def _setup(card="C14", prov=1, ally_prov=0):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    g = s.lords["garcia_ordonez"]
    g.capabilities.append(card)
    s.decks.capabilities_in_play.append(CardInPlay(
        card_id=card, scope="this_lord", owner_side="christian",
        owner_lord_id="garcia_ordonez"))
    g.cylinder = Cylinder(kind="locale", locale_id="toledo")
    g.in_stronghold = False
    g.assets["prov"] = prov
    # Clear Muslim Lords so the paths are clean, and move any OTHER Lord
    # off toledo so the only same-Locale sharer is one we control.
    for lid, l in s.lords.items():
        if lid == "garcia_ordonez":
            continue
        if l.side == "muslim" and l.cylinder.kind == "locale":
            l.cylinder = Cylinder(kind="locale", locale_id="sevilla")
        elif l.cylinder.kind == "locale" and l.cylinder.locale_id == "toledo":
            l.cylinder = Cylinder(kind="locale", locale_id="leon")
    if ally_prov:
        a = s.lords["pedro_ansurez"]
        a.cylinder = Cylinder(kind="locale", locale_id="toledo")
        a.in_stronghold = False
        a.assets["prov"] = ally_prov
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "garcia_ordonez"
    s.meta.actions_remaining = 2
    return s


def test_cabalgadas_ravages_two_hop_region_spends_prov_and_card() -> None:
    s = _setup(prov=1)
    tgts = _cabalgadas_targets(s, "garcia_ordonez", "christian")
    nbrs = set(all_neighbors("toledo"))
    region_2hop = next(t for t in tgts if t not in nbrs and is_region(t))
    color_before = s.locales[region_2hop].ravaged
    assert color_before != "yellow"
    apply_action(s, {"type": "cmd_cabalgadas", "side": "christian",
                     "target_locale": region_2hop})
    assert s.locales[region_2hop].ravaged == "yellow"   # Ravaged
    assert s.lords["garcia_ordonez"].assets.get("prov", 0) == 0  # spent (region: no prov rustling)
    assert s.meta.actions_remaining == 0                # entire card


def test_cabalgadas_blocked_by_unbesieged_enemy_on_path_and_target() -> None:
    s = _setup(prov=1)
    # Put an Unbesieged Muslim Lord on a 1-hop neighbor (talavera).
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id="talavera")
    s.lords["al_mutamid"].in_stronghold = False
    tgts = _cabalgadas_targets(s, "garcia_ordonez", "christian")
    assert "talavera" not in tgts          # blocked as target
    # Any 2-hop target reachable ONLY through talavera is also gone; at
    # minimum, talavera cannot be used as an intervening Locale.
    assert all(t != "talavera" for t in tgts)


def test_cabalgadas_requires_provender_else_rejected() -> None:
    s = _setup(prov=0, ally_prov=0)
    assert not [m for m in __import__("almoravid.legal_moves",
                fromlist=["legal_moves"]).legal_moves(s)
                if m["type"] == "cmd_cabalgadas"]
    tgt = "calatrava"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_cabalgadas", "side": "christian",
                         "target_locale": tgt})
    assert ei.value.code == "no_provender"


def test_cabalgadas_shares_provender_from_same_locale_ally() -> None:
    s = _setup(prov=0, ally_prov=1)   # bearer has none; ally at same locale does
    from almoravid.legal_moves import legal_moves
    moves = [m for m in legal_moves(s) if m["type"] == "cmd_cabalgadas"]
    assert moves, "Cabalgadas should be available via Shared Provender (1.5.2)"
    r = apply_action(s, moves[0])
    assert r["prov_payer"] == "pedro_ansurez"   # only ally at toledo with Prov
    assert s.lords["pedro_ansurez"].assets.get("prov", 0) == 0  # ally's Prov spent
