"""Overlay-aware lookups for Locale / Lord / Stronghold state.

Per BRIEF and FUTURE_PROJECTS_LESSONS.md Pattern 5:

  Any code that needs to know 'what is the effective stronghold here?'
  or 'is this Lord besieged?' or 'is this Locale friendly to side X?'
  MUST go through this module. Raw reads of `locale.base_type` or
  similar are an audit smell because future capability cards may
  override the base value.

  Almoravid 1085-1086 currently has no Stronghold-type overlays
  (nothing converts a Town to a Castle, etc.), but the helper API
  stays uniform with the L&C series convention so future cards plug
  in without revisiting every call site.
"""

from __future__ import annotations

from almoravid.state import GameState, Side, StrongholdType


def effective_stronghold_type(state: GameState, locale_id: str) -> StrongholdType:
    """Return the effective Stronghold type at a Locale (Pattern 5).

    Almoravid currently has no overlay cards that change Stronghold
    type; this returns the static base_type. The function exists so
    callers don't read `locale.base_type` directly — when a future
    card grants a type override, only this function needs updating.
    """
    return state.locales[locale_id].base_type


def effective_stronghold_value(state: GameState, locale_id: str) -> int:
    """Return the VP value of a Stronghold at this Locale (rule 1.3.1).

    Castle/Town = 1, Fortress = 2, City = 3. Returns 0 for Region
    (no Stronghold).
    """
    t = effective_stronghold_type(state, locale_id)
    return {"city": 3, "fortress": 2, "town": 1, "castle": 1, "region": 0}[t]


def has_gardens(state: GameState, locale_id: str) -> bool:
    """Gardens are at Cities and Fortresses only (rule 4.7.1).

    Static reads check `locale.has_gardens` which was set from the Map
    reference at scenario load; this wrapper exists for symmetry with
    the other overlay-aware lookups.
    """
    return state.locales[locale_id].has_gardens


# ---------------------------------------------------------------------------
# Friendliness — rule 1.3.1
# ---------------------------------------------------------------------------


def is_friendly_locale(state: GameState, locale_id: str, side: Side) -> bool:
    """Is `locale_id` Friendly to `side` per rule 1.3.1?

    Locale or Stronghold override (highest priority):
      - A Conquered or Seat marker is Friendly to that side.
      - A Jihad marker is Friendly to Muslims.

    Otherwise per Territory:
      - Reconquista Taifa or Kingdom -> Christian.
      - Parias Taifa -> Neutral (not Friendly to either).
      - Independent Taifa -> Muslim.

    Phase 3c implementation is the "no card overlays" baseline; future
    capabilities can extend this without changing call sites.
    """
    loc = state.locales[locale_id]

    # Locale-override checks first (rule 1.3.1 §locale_or_stronghold).
    if loc.seat_marker_lord_ids:
        # Seat marker friendly to its owner Lord's side. Pick the first
        # (in Almoravid a Locale has at most one side's Seat markers at
        # a time per the rules; multi-Lord Seats at Burgos/Algeciras
        # both belong to the same side).
        owner_lid = loc.seat_marker_lord_ids[0]
        owner = state.lords.get(owner_lid)
        if owner is not None:
            return owner.side == side
    if loc.conquered_markers:
        # Conquered markers belong to the side that placed them. Phase 1b
        # records all Conquered as a single count; the placing side is
        # encoded contextually (Christian places on Muslim territory by
        # default; Muslim Conquered = Kingdoms-territory Muslim conquest).
        # Phase 4 will split if the rules require — Q-NNN candidate.
        territory_taifa = state.taifas.get(loc.territory)
        if territory_taifa is not None and territory_taifa.side == "muslim":
            return side == "christian"
        return side == "muslim"  # Conquered on Christian Kingdom
    if loc.jihad_markers:
        return side == "muslim"

    # Otherwise per Territory.
    if loc.territory in ("leon", "aragon"):
        return side == "christian"  # Christian Kingdom
    taifa = state.taifas.get(loc.territory)
    if taifa is None:
        return False
    if taifa.status == "reconquista":
        return side == "christian"
    if taifa.status == "parias":
        return False  # Neutral
    if taifa.status == "independent":
        return side == "muslim"
    if taifa.status == "kingdoms":
        return side == "christian"  # Castile-style absorbed Christian kingdom
    return False


# ---------------------------------------------------------------------------
# Besieged state — rule 4.3.5 / 4.5
# ---------------------------------------------------------------------------


def is_besieged(state: GameState, lord_id: str) -> bool:
    """Is `lord_id` currently Besieged?

    A Lord is Besieged if:
      - His cylinder is at a Locale (kind='locale'), AND
      - He is inside the Stronghold there (in_stronghold=True), AND
      - There is an enemy Siege marker at that Locale (siege_yellow
        for a Muslim Besieged Lord, siege_green for Christian).

    Note: a Lord without a Siege marker on him may be Bypassed, which
    is a separate state. Bypass on the Locale flips the side flag.
    """
    lord = state.lords.get(lord_id)
    if lord is None or lord.cylinder.kind != "locale":
        return False
    if not lord.in_stronghold:
        return False
    loc = state.locales[lord.cylinder.locale_id]
    if lord.side == "muslim":
        return loc.siege_yellow > 0  # Christian-placed Siege
    return loc.siege_green > 0  # Muslim-placed Siege on a Christian-held Locale


def is_bypassed(state: GameState, lord_id: str) -> bool:
    """Is `lord_id` currently Bypassed? (4.3.5 / 4.5)

    Bypass is a side-attached locale marker indicating the besieger
    has chosen to bypass rather than commit to Siege. The Lord inside
    the Stronghold is Bypassed (cannot leave Stronghold but takes no
    Storm risk).
    """
    lord = state.lords.get(lord_id)
    if lord is None or lord.cylinder.kind != "locale":
        return False
    if not lord.in_stronghold:
        return False
    loc = state.locales[lord.cylinder.locale_id]
    if lord.side == "muslim":
        return loc.bypass_yellow
    return loc.bypass_green
