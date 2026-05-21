"""FIX-A L8/L11: Levy Transport (3.4.3) + the 3.4 Friendly+Unbesieged
gate on Lordship-spending Levy actions."""
from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.effective import is_friendly_locale
from almoravid.legal_moves import legal_moves
from almoravid.scenarios import load_scenario
from tests._plan_helpers import step_levy


def _to_muster(s, side="christian"):
    from tests.test_real_levy import _drive_to_levy_step
    _drive_to_levy_step(s, "muster")
    while s.meta.active_player != side:
        step_levy(s)
    return s


def _friendly_unbesieged_lord(s, side):
    for lid, l in s.lords.items():
        if (l.side == side and l.cylinder.kind == "locale"
                and is_friendly_locale(s, l.cylinder.locale_id, side)
                and l.lordship_rating > 0):
            return lid
    return None


def test_levy_transport_adds_cart():
    s = load_scenario("scenario_a_toledo_beset")
    _to_muster(s, "christian")
    lid = _friendly_unbesieged_lord(s, "christian")
    assert lid is not None
    carts0 = s.lords[lid].assets.get("cart", 0)
    used0 = s.lords[lid].lordship_used
    r = apply_action(s, {"type": "levy_transport", "side": "christian",
                         "lord_id": lid, "transport": "cart"})
    assert s.lords[lid].assets["cart"] == carts0 + 1
    assert s.lords[lid].lordship_used == used0 + 1
    assert r["transport"] == "cart"


def test_levy_transport_returns_lost_serf():
    s = load_scenario("scenario_a_toledo_beset")
    _to_muster(s, "christian")
    # Find a Lord that starts with Serfs.
    from almoravid.static_data import load_lords
    statics = load_lords()["lords"]
    lid = None
    for cand, l in s.lords.items():
        if (l.side == "christian" and l.cylinder.kind == "locale"
                and is_friendly_locale(s, l.cylinder.locale_id, "christian")
                and statics[cand]["forces"].get("serfs", 0) > 0
                and l.lordship_rating > 0):
            lid = cand
            break
    if lid is None:
        pytest.skip("no Christian Lord with Serfs at a Friendly Locale")
    # Simulate a lost Serf.
    start = statics[lid]["forces"]["serfs"]
    s.lords[lid].forces["serfs"] = start - 1
    apply_action(s, {"type": "levy_transport", "side": "christian",
                     "lord_id": lid, "transport": "mule"})
    assert s.lords[lid].forces["serfs"] == start  # one returned


def test_levy_transport_rejected_at_enemy_locale():
    """3.4 gate: a besieging Lord at an Enemy Locale cannot Levy."""
    s = load_scenario("scenario_a_toledo_beset")
    _to_muster(s, "christian")
    # alvar_fanez is at Toledo (Enemy) in this scenario.
    enemy_lid = next((lid for lid, l in s.lords.items()
                      if l.side == "christian" and l.cylinder.kind == "locale"
                      and not is_friendly_locale(s, l.cylinder.locale_id,
                                                 "christian")), None)
    if enemy_lid is None:
        pytest.skip("no Christian Lord at an Enemy Locale in this scenario")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "levy_transport", "side": "christian",
                         "lord_id": enemy_lid, "transport": "cart"})
    assert ei.value.code in ("not_friendly_locale", "besieged")


def test_enumerator_offers_transport_and_excludes_enemy_locale_lords():
    s = load_scenario("scenario_a_toledo_beset")
    _to_muster(s, "christian")
    moves = legal_moves(s)
    tr = [m for m in moves if m["type"] == "levy_transport"]
    assert tr, "expected Levy Transport options"
    # No transport move offered for a Lord at an Enemy Locale.
    enemy_lids = {lid for lid, l in s.lords.items()
                  if l.side == "christian" and l.cylinder.kind == "locale"
                  and not is_friendly_locale(s, l.cylinder.locale_id,
                                             "christian")}
    assert not any(m["lord_id"] in enemy_lids for m in tr)
