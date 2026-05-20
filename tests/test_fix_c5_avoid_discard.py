"""FIX-C / C5 Avoid-Battle discard-to-Unladen + Spoils (rule 4.3.4)."""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.map import neighbors_via
from almoravid.scenarios import load_scenario
from almoravid.state import Cylinder, PendingDecision


def _avoid_setup(s, defender_assets):
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale",
                                              locale_id="sevilla")
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = dict(defender_assets)
    s.lords["al_mutamid"].forces = {"sergeants": 1}
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": "sevilla", "from_locale_id": "cordoba",
                 "via_way_type": "road", "active_lord_id": "alfonso",
                 "active_side": "christian",
                 "defender_lord_ids": ["al_mutamid"]})
    s.meta.active_player = "muslim"


def test_avoid_discards_all_loot_as_spoils() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Loot + Provender within transport: Loot must still be discarded.
    _avoid_setup(s, {"loot": 2, "prov": 1, "mule": 1})
    target = [n for n in neighbors_via("sevilla", "road")
              if n != "cordoba"][0]
    r = apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                         "target_locale_id": target, "way_type": "road"})
    assert r["discarded_as_spoils"].get("loot") == 2
    assert s.lords["al_mutamid"].assets.get("loot", 0) == 0
    assert s.lords["al_mutamid"].assets.get("prov", 0) == 1   # kept (<=transport)
    assert s.lords["alfonso"].assets.get("loot", 0) == 2


def test_avoid_over_pass_only_mules_carry_provender() -> None:
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Find a Locale with a Pass neighbor + a distinct road neighbor for
    # the Approach origin.
    loc_id = pass_target = from_road = None
    for lid in s.locales:
        pn = neighbors_via(lid, "pass")
        rn = neighbors_via(lid, "road")
        if pn and rn and set(rn) - set(pn):
            loc_id, pass_target = lid, pn[0]
            from_road = next(n for n in rn if n != pass_target)
            break
    assert loc_id is not None, "no Locale with a Pass neighbor on this map"
    s.lords["al_mutamid"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.lords["al_mutamid"].in_stronghold = False
    s.lords["al_mutamid"].assets = {"prov": 2, "cart": 1, "mule": 1}
    s.lords["al_mutamid"].forces = {"sergeants": 1}
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id=loc_id)
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": loc_id, "from_locale_id": from_road,
                 "via_way_type": "road", "active_lord_id": "alfonso",
                 "active_side": "christian",
                 "defender_lord_ids": ["al_mutamid"]})
    s.meta.active_player = "muslim"
    r = apply_action(s, {"type": "respond_avoid_battle", "side": "muslim",
                         "target_locale_id": pass_target, "way_type": "pass"})
    # max_prov over Pass = mules (1) -> discard 1.
    assert r["discarded_as_spoils"].get("prov") == 1
    assert s.lords["al_mutamid"].assets.get("prov", 0) == 1


def test_avoid_shared_transport_group_capacity() -> None:
    """E7/1.5.2: avoiding Lords Share Transport — the GROUP's combined
    Carts+Mules set the combined Provender capacity (Road)."""
    from almoravid.actions import apply_action as _aa
    s = load_scenario("scenario_a_toledo_beset", seed=11)
    # Two Muslim defenders avoiding together from sevilla.
    d1, d2 = "al_mutamid", "abu_bakr"
    for d in (d1, d2):
        s.lords[d].cylinder = Cylinder(kind="locale", locale_id="sevilla")
        s.lords[d].in_stronghold = False
        s.lords[d].forces = {"sergeants": 1}
    s.lords[d1].assets = {"prov": 3, "mule": 1}   # alone: 3>1 laden
    s.lords[d2].assets = {"prov": 0, "mule": 1}   # contributes transport
    # Combined: transport 2, prov 3 -> discard 1 (keep 2).
    s.lords["alfonso"].cylinder = Cylinder(kind="locale", locale_id="sevilla")
    s.lords["alfonso"].in_stronghold = False
    s.lords["alfonso"].assets = {}
    s.pending = PendingDecision(
        kind="march_arrival_response", waiting_on="muslim",
        payload={"locale_id": "sevilla", "from_locale_id": "cordoba",
                 "via_way_type": "road", "active_lord_id": "alfonso",
                 "active_side": "christian", "defender_lord_ids": [d1, d2]})
    s.meta.active_player = "muslim"
    target = next(n for n in neighbors_via("sevilla", "road")
                  if n != "cordoba")
    r = _aa(s, {"type": "respond_avoid_battle", "side": "muslim",
                "target_locale_id": target, "way_type": "road"})
    assert r["discarded_as_spoils"].get("prov") == 1   # 3 - capacity(2)
    total_prov = (s.lords[d1].assets.get("prov", 0)
                  + s.lords[d2].assets.get("prov", 0))
    assert total_prov == 2
