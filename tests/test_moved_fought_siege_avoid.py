"""Moved/Fought marking for Siege (4.5.1) and Avoid Battle (4.3.4),
plus Bypass-marking when Avoiding into an Enemy Stronghold (4.3.4)."""
from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.map import neighbors_via
from almoravid.scenarios import load_scenario
from almoravid.effective import is_friendly_locale
from almoravid.state import Cylinder, PendingDecision


def test_siege_marks_all_lords_there_moved_fought() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=3)
    # Put Alfonso (besieger) and a Muslim defender (inside) at an enemy
    # Stronghold so a Siege command runs and marks BOTH Fought (4.5.1).
    loc_id = next(lid for lid, l in s.locales.items()
                  if l.base_type != "region"
                  and not is_friendly_locale(s, lid, "christian"))
    al = s.lords["alfonso"]
    al.cylinder = Cylinder(kind="locale", locale_id=loc_id)
    al.in_stronghold = False
    al.moved_fought = False
    defn = next(l for l in s.lords.values() if l.side == "muslim")
    defn.cylinder = Cylinder(kind="locale", locale_id=loc_id)
    defn.in_stronghold = True
    defn.moved_fought = False
    s.meta.active_player = "christian"
    s.meta.active_lord_id = "alfonso"
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.actions_remaining = 3
    r = apply_action(s, {"type": "cmd_siege", "side": "christian",
                         "surrender": False})
    assert "alfonso" in r["fought_marked"]
    assert defn.id in r["fought_marked"]
    assert al.moved_fought is True
    assert defn.moved_fought is True


def _avoid_setup(s, target_from="cordoba", loc="sevilla"):
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {}
    s.lords["al_mutamid"].forces = {"sergeants": 1}
    s.lords["al_mutamid"].moved_fought = False
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc)
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": loc, "from_locale_id": target_from,
                 "via_way_type": "road", "active_lord_id": "alfonso",
                 "active_side": "christian",
                 "defender_lord_ids": ["al_mutamid"]})
    s.meta.active_player = "muslim"


def test_avoid_battle_marks_moved_fought() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    _avoid_setup(s)
    target = [n for n in neighbors_via("sevilla", "road")
              if n != "cordoba"][0]
    apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                     "target_locale_id": target, "way_type": "road"})
    assert s.lords["al_mutamid"].moved_fought is True


def test_avoid_into_enemy_stronghold_marks_bypassing() -> None:
    """A Christian defender Avoiding into a Muslim-territory (Enemy)
    Stronghold is marked Bypassing it (4.3.4 / 4.3.5)."""
    s = load_scenario("scenario_a_toledo_beset", seed=7)
    # Christian defender (alfonso) at sevilla; Muslim attacker (yusuf)
    # Approaches from cordoba; alfonso Avoids to an Enemy (Muslim) road
    # neighbour that holds a Stronghold and is unbesieged/unbypassed.
    alf = s.lords["alfonso"]
    alf.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    alf.in_stronghold = False
    alf.assets = {}
    alf.forces = {"sergeants": 1}
    yus = s.lords["yusuf"]
    yus.cylinder = Cylinder(kind="locale", locale_id="sevilla")
    yus.in_stronghold = False
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="christian",
        payload={"locale_id": "sevilla", "from_locale_id": "cordoba",
                 "via_way_type": "road", "active_lord_id": "yusuf",
                 "active_side": "muslim",
                 "defender_lord_ids": ["alfonso"]})
    s.meta.active_player = "christian"
    target = None
    for n in neighbors_via("sevilla", "road"):
        if n == "cordoba":
            continue
        loc = s.locales[n]
        if loc.base_type == "region":
            loc.base_type = "town"   # force a Stronghold for the test
        if (not is_friendly_locale(s, n, "christian")
                and loc.siege_yellow == 0 and not loc.bypass_yellow):
            target = n
            break
    assert target is not None, "no enemy-Stronghold road neighbour of sevilla"
    apply_action(s, {"type": "respond_avoid_battle", "side": "christian",
                     "target_locale_id": target, "way_type": "road"})
    assert s.locales[target].bypass_yellow is True
