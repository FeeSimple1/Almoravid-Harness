"""Provender capacity on March (rule 1.7.2): a Lord/group must discard
Provender beyond 2 x (Carts + Mules) to March."""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.state import Cylinder
from tests.test_march import _setup_alfonso_active


def test_excess_provender_discarded_on_march() -> None:
    s = _setup_alfonso_active()
    # 1 Mule (capacity 2), 5 Provender -> discard 3, keep 2.
    s.lords["alfonso"].assets = {"mule": 1, "prov": 5}
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road"})
    assert s.lords["alfonso"].assets.get("prov", 0) == 2
    assert s.lords["alfonso"].cylinder.locale_id == "leon"


def test_no_transport_discards_all_provender() -> None:
    s = _setup_alfonso_active()
    s.lords["alfonso"].assets = {"prov": 3}   # 0 Transport -> capacity 0
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road"})
    assert s.lords["alfonso"].assets.get("prov", 0) == 0


def test_within_capacity_keeps_all_provender() -> None:
    s = _setup_alfonso_active()
    s.lords["alfonso"].assets = {"cart": 1, "mule": 1, "prov": 4}  # cap 4
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road"})
    assert s.lords["alfonso"].assets.get("prov", 0) == 4


def test_group_shares_transport_capacity() -> None:
    """Shared Transport (1.5.2/4.3.2): the group's combined Transport
    sets the combined Provender capacity."""
    s = _setup_alfonso_active()
    s.lords["alfonso"].assets = {"mule": 2, "prov": 3}        # cap 4 alone
    s.lords["garcia_ordonez"].assets = {"prov": 4}            # 0 transport alone
    # Combined: transport 2 -> capacity 4; total prov 7 -> discard 3.
    apply_action(s, {"type": "cmd_march", "side": "christian",
                     "target_locale_id": "leon", "way_type": "road",
                     "group_lord_ids": ["garcia_ordonez"]})
    total = (s.lords["alfonso"].assets.get("prov", 0)
             + s.lords["garcia_ordonez"].assets.get("prov", 0))
    assert total == 4
