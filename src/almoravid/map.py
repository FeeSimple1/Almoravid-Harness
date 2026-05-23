"""Locale classifier helpers — the way-class profile of each Locale.

Used by future Phase 5 code (March, Supply, Forage, Ravage, Tax) to
reason about how a Locale connects to its neighbors and which Transport
types can use those connections.

The Almoravid map has two Way types per the Map reference v13:
  - 'road': open-country routes (72 total)
  - 'pass': mountain / border crossings (37 total). Carts cannot
    traverse Passes (rule 4.3.2 Laden). Mules can.

Almoravid 1085-1086 has no parallel-Way locale-pairs (Pattern 4 audit
test confirms it). The classifier API stays uniform with the rest of
the L&C series so future map revisions don't require call-site changes.
"""

from __future__ import annotations

from functools import lru_cache

from almoravid.static_data import load_locales, load_ways


@lru_cache(maxsize=1)
def way_classes_per_locale() -> dict[str, frozenset[str]]:
    """Map locale_id -> frozenset of way_types incident on it."""
    classes: dict[str, set[str]] = {}
    for w in load_ways()["ways"]:
        classes.setdefault(w["a"], set()).add(w["way_type"])
        classes.setdefault(w["b"], set()).add(w["way_type"])
    # Ensure every locale has an entry (even isolated ones — there shouldn't
    # be any but the map could change).
    for lid in load_locales()["locales"]:
        classes.setdefault(lid, set())
    return {lid: frozenset(types) for lid, types in classes.items()}


def has_road(locale_id: str) -> bool:
    """Locale has at least one Road-type Way incident on it."""
    return "road" in way_classes_per_locale().get(locale_id, frozenset())


def has_pass(locale_id: str) -> bool:
    """Locale has at least one Pass-type Way incident on it."""
    return "pass" in way_classes_per_locale().get(locale_id, frozenset())


def is_port(locale_id: str) -> bool:
    """Locale has a Port (Map reference v13 PORT column).

    Ports are not currently a Way type in Almoravid (no Ship transport
    in 1085-1086 the way Nevsky had Cogs / Lodya), but the flag exists
    on Locales because Map Part 1 lists them and future variants may
    care.
    """
    loc = load_locales()["locales"].get(locale_id)
    return bool(loc and loc.get("port"))


def only_accessible_via_pass(locale_id: str) -> bool:
    """Locale connects to the rest of the map ONLY via Passes.

    Relevant to 4.3.2 Laden: a Cart laden with Provender cannot cross a
    Pass. Lords needing to bring Cart-borne Provender into such a
    Locale must offload at the boundary.
    """
    classes = way_classes_per_locale().get(locale_id, frozenset())
    return classes == frozenset({"pass"})


def is_road_isolated(locale_id: str) -> bool:
    """Locale has no Road Ways at all. Almoravid currently has none such."""
    return not has_road(locale_id)


def neighbors_via(locale_id: str, way_type: str) -> list[str]:
    """List of locale_ids reachable from `locale_id` via the named way_type."""
    out: list[str] = []
    for w in load_ways()["ways"]:
        if w["way_type"] != way_type:
            continue
        if w["a"] == locale_id:
            out.append(w["b"])
        elif w["b"] == locale_id:
            out.append(w["a"])
    return out


def christian_kingdom_locales() -> list[str]:
    """Locale ids in León or Aragón (Christian Kingdoms)."""
    return [
        lid for lid, l in load_locales()["locales"].items()
        if l["territory"] in ("leon", "aragon")
    ]


def taifa_locales(taifa_id: str) -> list[str]:
    """Locale ids belonging to the named Taifa."""
    return [
        lid for lid, l in load_locales()["locales"].items()
        if l["territory"] == taifa_id
    ]


def is_region(locale_id: str) -> bool:
    """True if the Locale is a Region (no Stronghold)."""
    loc = load_locales()["locales"].get(locale_id)
    return bool(loc and loc.get("base_type") == "region")


def hop_distances(origin: str) -> dict[str, int]:
    """BFS shortest-path distances (in number of adjacent-space hops, any
    Way type) from `origin` to every reachable Locale, including origin=0.
    Used for "closer than any Christian" tests (e.g. M9 Emir al-Muslimin:
    "Closer means by the shortest chain of adjacent spaces away")."""
    from collections import deque
    dist: dict[str, int] = {origin: 0}
    q = deque([origin])
    while q:
        cur = q.popleft()
        for nbr in all_neighbors(cur):
            if nbr not in dist:
                dist[nbr] = dist[cur] + 1
                q.append(nbr)
    return dist


def all_neighbors(locale_id: str) -> list[str]:
    """All Locales adjacent to `locale_id` via ANY Way type.

    Used by Call to Arms (3.5.2 Invite the Almoravids) to find the
    nearest Port when Algeciras is unavailable. Deduplicated.
    """
    out: list[str] = []
    seen: set[str] = set()
    for w in load_ways()["ways"]:
        other = None
        if w["a"] == locale_id:
            other = w["b"]
        elif w["b"] == locale_id:
            other = w["a"]
        if other is not None and other not in seen:
            seen.add(other)
            out.append(other)
    return out


def nearest_ports(origin: str) -> list[tuple[str, int]]:
    """Breadth-first list of (port_locale_id, hop_distance) sorted by
    increasing hop distance from `origin`, over ALL Way types.

    `origin` itself is included at distance 0 if it is a Port. Used by
    3.5.2 Invite the Almoravids ("nearest Port that is Friendly and
    free of Siege") — the caller filters by Friendly/Siege and picks
    the first survivor. Ties at equal distance preserve insertion
    (BFS) order; the caller resolves any remaining ambiguity.
    """
    from collections import deque
    locales = load_locales()["locales"]
    result: list[tuple[str, int]] = []
    seen = {origin}
    dq: deque[tuple[str, int]] = deque([(origin, 0)])
    while dq:
        node, dist = dq.popleft()
        loc = locales.get(node)
        if loc and loc.get("port"):
            result.append((node, dist))
        for nb in all_neighbors(node):
            if nb not in seen:
                seen.add(nb)
                dq.append((nb, dist + 1))
    return result
