"""C8 Hueste capability effect (Arts of War ref C8): a Lord with Hueste
counts as a Marshal for Group March (4.3.1) to/from any Taifa Locale (not
Kingdom->Kingdom); he may not take Alfonso (the Marshal) in the group; he
cannot use it while himself a Lower Lord.
"""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.map import neighbors_via
from almoravid.scenarios import load_scenario
from almoravid.state import CardInPlay, Cylinder


def _setup(here="toledo", give_hueste=True, leader="garcia_ordonez",
           members=("pedro_ansurez",)):
    s = load_scenario("scenario_a_toledo_beset", seed=1)
    if give_hueste:
        s.lords[leader].capabilities.append("C8")
        s.decks.capabilities_in_play.append(CardInPlay(
            card_id="C8", scope="this_lord", owner_side="christian",
            owner_lord_id=leader))
    for lid in (leader, *members):
        s.lords[lid].cylinder = Cylinder(kind="locale", locale_id=here)
        s.lords[lid].in_stronghold = False
    s.meta.phase = "campaign"
    s.meta.campaign_step = "activation"
    s.meta.active_player = "christian"
    s.meta.active_lord_id = leader
    s.meta.actions_remaining = 2
    return s


def test_hueste_bearer_leads_group_march_to_taifa_locale() -> None:
    s = _setup()                      # toledo is a Taifa Locale
    tgt = neighbors_via("toledo", "road")[0]
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": tgt, "way_type": "road",
                     "group_lord_ids": ["pedro_ansurez"]})
    assert s.lords["garcia_ordonez"].cylinder.locale_id == tgt
    assert s.lords["pedro_ansurez"].cylinder.locale_id == tgt


def test_hueste_may_not_take_alfonso() -> None:
    s = _setup(members=("alfonso",))
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": neighbors_via("toledo", "road")[0],
                         "way_type": "road", "group_lord_ids": ["alfonso"]})
    assert ei.value.code == "hueste_no_alfonso"


def test_non_hueste_non_marshal_cannot_lead_group() -> None:
    s = _setup(give_hueste=False)
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": neighbors_via("toledo", "road")[0],
                         "way_type": "road", "group_lord_ids": ["pedro_ansurez"]})
    assert ei.value.code == "not_marshal"


def test_hueste_does_not_apply_kingdom_to_kingdom() -> None:
    # Both endpoints in a Christian Kingdom -> Hueste does not grant Marshal.
    s = _setup(here="leon")
    # find a road neighbor of leon that is also a Kingdom locale
    from almoravid.map import christian_kingdom_locales
    kingdom = set(christian_kingdom_locales())
    tgt = next((n for n in neighbors_via("leon", "road") if n in kingdom), None)
    assert tgt is not None, "expected a Kingdom road-neighbor of leon"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": tgt, "way_type": "road",
                         "group_lord_ids": ["pedro_ansurez"]})
    assert ei.value.code == "not_marshal"
