"""FIX-C / C3 Marshal Group March + Shared Transport (rules 4.3.1/4.3.2)."""

from __future__ import annotations

import pytest

from almoravid.actions import IllegalAction, apply_action
from almoravid.state import Cylinder
from tests.test_march import _setup_alfonso_active


def test_marshal_leads_group_march() -> None:
    """Alfonso (Marshal) Marches from Sahagún to León bringing a
    co-located Lord; both move together."""
    s = _setup_alfonso_active()
    # Keep the group Unladen (drop assets) to cost one action.
    for lid in ("alfonso", "garcia_ordonez"):
        s.lords[lid].assets = {}
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road",
                     "group_lord_ids": ["garcia_ordonez"]})
    assert s.lords["alfonso"].cylinder.locale_id == "leon"
    assert s.lords["garcia_ordonez"].cylinder.locale_id == "leon"
    assert s.lords["garcia_ordonez"].moved_fought is True


def test_group_march_uses_shared_transport_for_laden() -> None:
    """Shared Transport (4.3.2): the group is Laden when COMBINED
    Provender exceeds COMBINED Transport, even if each Lord alone is
    Unladen."""
    s = _setup_alfonso_active()
    # Each Lord alone: 1 Prov, 0 Transport -> not >transport? 1>0 True...
    # Use 1 Prov + 1 Mule each alone (Unladen: 1<=1), but combined
    # 2 Prov + 2 Mules is still Unladen. Make combined Laden instead:
    s.lords["alfonso"].assets = {"prov": 1, "mule": 1}        # alone: 1<=1
    s.lords["garcia_ordonez"].assets = {"prov": 2, "mule": 1}  # alone: 2>1 Laden
    # Combined: prov 3 > transport (mules) 2 -> Laden group.
    before = s.meta.actions_remaining
    r = apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road",
                         "group_lord_ids": ["garcia_ordonez"]})
    assert r["laden"] is True
    assert r["cost"] == 2
    assert s.meta.actions_remaining == before - 2


def test_non_marshal_cannot_lead_group() -> None:
    s = _setup_alfonso_active()
    # Make a non-Marshal (alvar_fanez) the active Lord at Sahagún.
    s.lords["alvar_fanez"].cylinder = Cylinder(kind="locale",
                                               locale_id="sahagun")
    s.lords["alvar_fanez"].in_stronghold = False
    s.meta.active_lord_id = "alvar_fanez"
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road",
                         "group_lord_ids": ["garcia_ordonez"]})
    assert ei.value.code == "not_marshal"


def test_group_member_must_be_co_located() -> None:
    s = _setup_alfonso_active()
    s.lords["alfonso"].assets = {}
    # Move garcia away so he is not co-located with the Marshal.
    s.lords["garcia_ordonez"].cylinder = Cylinder(kind="locale",
                                                  locale_id="burgos")
    with pytest.raises(IllegalAction) as ei:
        apply_action(s, {"type": "cmd_march", "side": "christian",
                         "target_locale_id": "leon", "way_type": "road",
                         "group_lord_ids": ["garcia_ordonez"]})
    assert ei.value.code == "not_same_locale"
