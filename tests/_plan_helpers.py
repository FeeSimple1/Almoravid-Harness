"""Shared test helper: build a rules-legal Plan padding (1.9.2/4.1.1).

The test suite historically padded a side's Plan with 6-7 Pass cards to
create a "one Lord acts, the rest idle" Campaign. That violates the
five-Pass-cards-per-side limit (1.9.2). `legal_pad` pads a side's Plan
up to the season target the legal way: fill Pass cards up to 5 first
(so an "idle" side still passes for its first reveals), then add the
minimum Command cards needed from that side's Mustered Lords (respecting
each Lord's 3/4 card cap). Any Command cards the caller already added
stay on top, so the first Active Lord is unchanged.
"""

from __future__ import annotations

from almoravid.actions import apply_action
from almoravid.campaign import _is_marshal, _plan_target_size


def legal_pad(s, side: str):
    target = _plan_target_size(s)
    plan = s.decks.plan.setdefault(side, [])

    # 1) Pad with Pass cards up to the 5-card limit (or the target).
    while len(plan) < target and sum(1 for e in plan if e.kind == "pass") < 5:
        apply_action(s, {"type": "plan_add_card", "side": side,
                         "plan_kind": "pass"})

    # 2) Remainder: Command cards of Mustered Lords (3 each, 4 Marshal).
    def cap(lid: str) -> int:
        return 4 if _is_marshal(lid, side) else 3

    # Candidate order: Lords already in the plan first, then any other
    # Mustered Lord of this side.
    order: list[str] = []
    for e in plan:
        if e.kind == "command" and e.lord_id not in order:
            order.append(e.lord_id)
    for lid, l in s.lords.items():
        if (l.side == side and l.cylinder.kind == "locale"
                and lid not in order):
            order.append(lid)

    while len(plan) < target:
        for lid in order:
            used = sum(1 for e in plan
                       if e.kind == "command" and e.lord_id == lid)
            if used < cap(lid):
                apply_action(s, {"type": "plan_add_card", "side": side,
                                 "plan_kind": "command", "lord_id": lid})
                break
        else:
            raise RuntimeError(
                f"cannot legally fill {side} plan to {target} "
                f"(insufficient Mustered Lords)")
    return plan
