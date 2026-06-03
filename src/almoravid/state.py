"""Game state model for the Almoravid harness.

This file defines the canonical state shape using Pydantic v2. It is
the Phase 0 scaffold: data classes only, no handlers, no rules logic,
no business methods. Later phases add mutators, legal_moves enumeration,
battle/storm resolution, etc.

Design decisions driven by the bug-pattern catalog in
FUTURE_PROJECTS_LESSONS.md:

- Pattern 4 (parallel Ways): `GameState.ways` is a list of `Way`
  objects each carrying an explicit `way_type`. Never key Ways by
  `(a, b)` alone.
- Pattern 5 (overlay markers): `Locale.base_type` is fixed at scenario
  setup; overlay state (Conquered, Jihad, Seat, Siege, Bypass) lives
  in separate fields. Phase 1 will add `effective_stronghold(locale)`
  helpers; raw `locale.base_type` reads outside those helpers are an
  audit smell.
- Pattern 6 (off-edge calendar): `Calendar` has explicit `off_left`,
  `off_right`, `off_left_service`, `off_right_service` lanes. Cylinder
  and Service marker off-edge lists are separate, per SMOKE-057.
- Pattern 11 (active-player desync): `Meta.active_player` is the
  single source of truth for whose turn it is. Future mutators must
  update it; tests should assert legal_moves never returns 0 while
  non-terminal.
- Pattern 14 (capability scope): each `CardInPlay` has an explicit
  `scope` field (`this_lord` vs `side_wide`); lookup helpers in
  Phase 4 will filter by scope.
- Pattern 3 (stale per-Lord flags): each per-Lord flag below carries a
  `# scope: ...` comment naming its expected reset boundary. Phase 1
  reset logic must honor these.
- Pattern 8 (lifecycle leaks): `Lord.cleanup_on_removal_fields` (class
  attribute below) enumerates the fields that MUST be cleared when a
  Lord is removed or Disbanded at limit.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

Side = Literal["christian", "muslim"]
StrongholdType = Literal["city", "fortress", "town", "castle", "region"]
TaifaStatus = Literal["independent", "parias", "reconquista", "kingdoms"]
UnitType = Literal[
    "knights",
    "sergeants",
    "african_horse",
    "light_horse",
    "men_at_arms",
    "african_foot",
    "militia",
    "serfs",
]
# Assets the rules track. `coin`/`loot`/`prov` are general; `cart`/`mule`
# are Transport types per the Lord reference.
AssetType = Literal["coin", "loot", "prov", "cart", "mule"]
WayType = Literal["road", "pass"]
Season = Literal["spring", "summer", "autumn", "winter"]
TurnType = Literal["levy", "campaign", "curias", "winter"]
CardScope = Literal["this_lord", "side_wide"]
RavagedState = Literal["none", "yellow", "green"]
CylinderKind = Literal["calendar", "locale", "mat", "set_aside", "removed"]
LevyStep = Literal["arts_of_war", "pay", "service_disband", "muster", "call_to_arms", "done"]
CampaignStep = Literal["plan", "activation", "end_card", "end_campaign", "done"]
PlanEntryKind = Literal["command", "pass"]


class StrictModel(BaseModel):
    """Base for all state models: forbid extras, validate on assignment."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Meta(StrictModel):
    """Top-level game-meta state.

    `active_player` is the single source of truth for whose turn it is
    (Pattern 11). Any mutator that ends a step / passes the baton must
    update it.
    """

    scenario_id: str
    scenario_letter: Literal["A", "B", "C", "D", "E", "F", "S"]
    seed: int = 0
    active_player: Side
    phase: Literal["setup", "levy", "campaign", "curias", "winter", "ended",
                   "battle"] = "setup"
    turn_index: int = 0
    # Battle of Sagrajas minigame: "attack" (Christians attack, historical)
    # or "defend" (Christians defend); None until the Christian chooses.
    sagrajas_role: str | None = None
    version: str = "0.2.0"

    # Levy sub-phase tracking (Pattern 1: state-set-but-unreachable —
    # each Levy step must be reachable via legal_moves; Pattern 11:
    # active_player above is the source of truth for whose turn it is).
    levy_step: LevyStep | None = None
    levy_step_completed_christian: bool = False
    levy_step_completed_muslim: bool = False
    first_levy_done: bool = False
    # Per-Levy: has this side completed its mandatory 3.1.2/3.1.3 AoW
    # draw (two cards) this Levy? Reset on entering the Levy.
    aow_draw_done: dict[Side, bool] = Field(default_factory=dict)

    # Seeded RNG counter. Advanced by every roll_d6 / shuffle call.
    rng_state: int = 0

    # Campaign sub-phase tracking (Phase 3a).
    campaign_step: CampaignStep | None = None
    plan_finalized_christian: bool = False
    plan_finalized_muslim: bool = False
    # The Lord whose Command card is currently revealed (Activation step).
    active_lord_id: str | None = None
    # Actions remaining on the active Lord's Command card.
    actions_remaining: int = 0
    # Index into the plan of the next card to reveal for each side.
    plan_index_christian: int = 0
    plan_index_muslim: int = 0

    # Phase 6d: per-Levy Muster ban list (cards M16 Galician Revolt /
    # M17 Leon y Castilla mark a Lord as un-Musterable for the rest of
    # the current Levy). Cleared in _advance_step_if_both_done at the
    # Levy->Campaign transition.
    muster_banned_this_levy_lord_ids: list[str] = Field(default_factory=list)
    # Phase 6h: Swollen River (C3/M3) — when the holding side's card
    # triggers, this stores the lord_id whose current Command card has
    # March blocked for its remainder. Cleared in _h_end_card.
    swollen_river_blocked_card_lord_id: str | None = None
    # Phase 7d: advanced Vassal Service rule (3.4.2) toggle. When True,
    # Mustered Vassals get their own Calendar Service markers and Lord
    # Service shifts cascade to them.
    advanced_vassal_service: bool = False
    # Ruined Land special rule (Scenarios E & F): Parias Coin (1.4.3) awards
    # Coin equal to Service LESS the number of Ravaged markers (either side)
    # in the Taifa.
    ruined_land: bool = False
    # Optional Hidden Mats fog-of-war (1.5.2). When True, redacted_view()
    # hides a side's Lord Forces/Assets/This-Lord Capabilities from the
    # opponent (except Lords engaged in Battle/Storm). Rules/legal moves
    # are unaffected — this only governs what an opponent's view exposes.
    hidden_mats: bool = False
    # 6.1 Bidding for Sides is a one-time setup option; once used it is
    # no longer offered (prevents re-bidding / setup loops).
    bidding_done: bool = False
    # FIX-A (Call to Arms, 3.5): per-Levy bookkeeping for the
    # call_to_arms step. Each side may take at most ONE Call-to-Arms
    # option ("do nothing OR one of the following", 3.5.1-.2); these
    # flags enforce that. cta_crusade_jihad_pending is set when the
    # Christians play Call for Crusade (3.5.1) — the Muslim player MAY
    # then add one Jihad marker (resolved as a separate optional action
    # during the Muslim 3.5.2 sub-turn). All three reset when the Levy
    # advances into the call_to_arms step (and at begin_levy).
    cta_option_used_christian: bool = False
    cta_option_used_muslim: bool = False
    cta_crusade_jihad_pending: bool = False
    # Hit-absorption policy per side (rule 4.4.2 ASSIGN HITS — the
    # owner chooses which unit absorbs each Hit). Per-combat strategic
    # choice supplied by the controlling LLM: "weakest_first" (sacrifice
    # least-protected to shield strong units) or "armored_first"
    # (armored units soak Hits to maximize cancels / minimize losses).
    # Default weakest_first (matches Nevsky). NOTE: the Storm Attacker
    # is RULE-FORCED to armored_first (4.5.2) regardless of this value.
    absorption_policy: dict[Side, str] = Field(
        default_factory=lambda: cast("dict[Side, str]",
                                     {"christian": "weakest_first",
                                      "muslim": "weakest_first"}))
    # Phase 6i: Surprise (C6) consumed on March into empty Enemy
    # Stronghold — payload tells the next cmd_storm to use Walls-1
    # and applies +2 Siege markers (already placed by the cmd_march
    # auto-trigger).
    surprise_storm_pending_locale_id: str | None = None
    # Phase 6k: Count of Barcelona faction — toggled by C13/M23
    # Berenguer Ramon events. Default is the Christian side (Sancho
    # or Eudes can buy the C13 capability units).
    count_of_barcelona_side: Side | None = "christian"


class Cylinder(StrictModel):
    """Where a Lord's cylinder currently is.

    Validation that (kind, box, locale_id) are consistent is deferred
    to Phase 1. Phase 0 just records the shape.
    """

    kind: CylinderKind
    box: int | None = None  # for kind="calendar"; 0..17 with 0/17 as off-edge sentinels
    locale_id: str | None = None  # for kind="locale"


class ServiceMarker(StrictModel):
    """A Lord's Service marker position on the Calendar.

    Off-edge handling: `box` may be 0 (off-left-service) or 17 (off-
    right-service). Cylinder and Service off-edges are independent
    (Pattern 6 / SMOKE-057).
    """

    lord_id: str
    box: int  # 0 = off_left_service, 1..16 in track, 17 = off_right_service
    # Phase 7d: advanced Vassal Service (3.4.2). When set, this marker
    # belongs to the named Vassal of `lord_id` rather than the Lord
    # himself. Lord-own markers leave this None.
    vassal_id: str | None = None


class CalendarBox(StrictModel):
    """One box on the 16-box Calendar."""

    number: int  # 1..16
    season: Season
    turn_type: TurnType
    cylinder_lord_ids: list[str] = Field(default_factory=list)
    # Service markers are stored on `Calendar.service_markers` keyed by
    # lord_id; this list is only the cylinders sitting on this box.

    # Scenario decorations placed at this box (Levy marker, Scenario End,
    # Victory marker color, Curias marker, etc.). Phase 0 stores them as
    # opaque strings; phase 1 will type them.
    decorations: list[str] = Field(default_factory=list)


class Calendar(StrictModel):
    """The 16-box Calendar plus off-edge lanes.

    Off-edge lanes are separate for cylinders vs Service markers
    (Pattern 6 / SMOKE-057). Do NOT merge.
    """

    boxes: list[CalendarBox]  # length 16, indices 0..15 correspond to boxes 1..16
    current_box: int = 1  # the box the Levy/Campaign marker is on

    off_left: list[str] = Field(default_factory=list)  # cylinder lord_ids
    off_right: list[str] = Field(default_factory=list)  # cylinder lord_ids

    # Service markers live here (not per-box) so off-edge lanes work uniformly.
    service_markers: list[ServiceMarker] = Field(default_factory=list)
    off_left_service: list[str] = Field(default_factory=list)  # lord_ids
    off_right_service: list[str] = Field(default_factory=list)  # lord_ids


class Vassal(StrictModel):
    """A Lord's Vassal. Pure data per the Lords reference."""

    id: str
    name: str
    forces: dict[UnitType, int] = Field(default_factory=dict)
    service_cost: int  # = Vassal Service Rating: 40-Days boxes ahead on
    # the Calendar at Muster / Disband (advanced rule 3.4.2). Despite the
    # name it is the Service Rating, not a Lordship cost (Muster always
    # costs one Levy action).
    ready: bool = True
    # Advanced Vassal Service (3.4.2): a Vassal Disbanded at its Service
    # limit goes Pennant-side-DOWN (Unready) — it cannot Muster until the
    # side flips Pennants up at the end of its Vassal Muster segment.
    pennant_down: bool = False


class CardInPlay(StrictModel):
    """An Arts of War card currently in play.

    `scope` enforces the this_lord vs side_wide distinction
    (Pattern 14 / SMOKE-016). Helpers in Phase 4 must filter on this.
    """

    card_id: str
    scope: CardScope
    owner_side: Side
    owner_lord_id: str | None = None  # required iff scope == "this_lord"


class PlanEntry(StrictModel):
    """One card in a side's Campaign Plan stack (rule 4.1).

    kind="command" with a lord_id activates that Lord for command_rating
    actions on reveal. kind="pass" advances the plan without activating
    anyone.
    """

    kind: PlanEntryKind
    lord_id: str | None = None  # required iff kind == "command"


class Lord(StrictModel):
    """A Lord (Christian or Muslim).

    Per-flag scope conventions (Pattern 3 / SMOKE-001, 035, 036, 037, 095):
        moved_fought:            scope = per-Levy
        just_arrived_this_levy:  scope = per-Levy (reset on Levy->Campaign->Levy)
        lordship_used:           scope = per-card (Muster segment)
        in_stronghold:           scope = lifecycle (cleared on move / re-Muster)
        routed_units:            scope = per-engagement (cleared on aftermath)
        first_march_used_this_card: scope = per-card
        raiders_used_this_card:  scope = per-card

    Lifecycle cleanup contract (Pattern 8 / SMOKE-033, 038, 087, 088, 095):
    `Lord.cleanup_on_removal_fields` lists every field that MUST be
    cleared when this Lord is permanently removed OR Disbanded at limit.
    Removal handlers added in later phases must consult this list.
    """

    id: str
    name: str
    side: Side
    is_taifa: bool = False  # one of the 6 Muslim Taifa Lords (Pattern 5/14-adjacent)
    home_taifa: str | None = None  # taifa_id if Muslim Taifa Lord
    seats: list[str] = Field(default_factory=list)  # locale_ids of printed pennants

    fealty: int | None = None  # None = Call to Arms only (no Fealty roll)
    service_rating: int  # Service-ahead boxes at Muster/Disband
    lordship_rating: int
    command_rating: int

    cylinder: Cylinder

    # Mat contents (Phase 0: simple dicts; refined in Phase 1).
    forces: dict[UnitType, int] = Field(default_factory=dict)
    assets: dict[AssetType, int] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)  # this_lord-scope card_ids
    vassals: list[Vassal] = Field(default_factory=list)

    # Stronghold occupancy (Pattern 5): NOT derived from base_type; tracked
    # explicitly so overlay-aware effective_stronghold() helpers in Phase 1
    # can answer "is this Lord inside walls" correctly.
    in_stronghold: bool = False

    # Per-card / per-Levy / per-engagement flags. See docstring above.
    moved_fought: bool = False
    just_arrived_this_levy: bool = False
    lordship_used: int = 0
    first_march_used_this_card: bool = False
    raiders_used_this_card: bool = False
    routed_units: dict[UnitType, int] = Field(default_factory=dict)
    # Phase 6i: Crusader marker count placed by C11 Indulgences /
    # C12 Song of Roland. Each marker is a transient resource with
    # 2 Knights "attached" (modeled by adding 2 Knights to forces
    # on placement). Removed when the marker is consumed.
    crusader_markers: int = 0
    # Phase 7c: Lieutenant stacking (rule 4.1.3). When True this Lord
    # is a Lower Lord stacked on `lieutenant_of` (an Upper Lord at the
    # same Locale). Set/cleared by the Lieutenant designation action.
    is_lieutenant: bool = False
    lieutenant_of: str | None = None

    # Lifecycle cleanup contract (Pattern 8). Class-level, not a field.
    cleanup_on_removal_fields: ClassVar[tuple[str, ...]] = (
        "forces",
        "assets",
        "capabilities",
        "vassals",
        "in_stronghold",
        "moved_fought",
        "just_arrived_this_levy",
        "lordship_used",
        "first_march_used_this_card",
        "raiders_used_this_card",
        "routed_units",
        "crusader_markers",
        "is_lieutenant",
        "lieutenant_of",
    )


class Locale(StrictModel):
    """A map location.

    `base_type` is fixed at scenario setup. Overlay state (Conquered,
    Jihad, Seat, Siege, Bypass, Ravaged) lives in separate fields and
    is queried via Phase 1 `effective_*` helpers (Pattern 5 / SMOKE-040,
    054, 065, 066, 073-077).
    """

    id: str
    name: str
    territory: str  # taifa_id for Muslim Taifas, or "leon"/"aragon" for Christian
    base_type: StrongholdType
    has_gardens: bool = False  # Y at Cities and Fortresses per Map reference
    has_port: bool = False
    is_reconquista_target: bool = False  # printed Y/N on map

    # Overlay markers (counts where applicable; lists where multiple).
    conquered_markers: int = 0  # 1 VP each (Christian on Muslim, or Muslim on Christian)
    jihad_markers: int = 0  # 1/2 VP each
    # PLACED Seat MARKERS only (Rodrigo, Yusuf/Sir double-Seat, Cathedrals
    # — 1.8 / 1.9.1 / 3.5.1-.2). Per 1.3.1 a Stronghold with a Seat MARKER
    # is Friendly to that Lord's side. Printed home-Seat pennants do NOT
    # confer Friendliness and live in `printed_seat_lord_ids` instead.
    seat_marker_lord_ids: list[str] = Field(default_factory=list)
    # PRINTED Seat pennants (1.3.1 SEATS): affect Reconquista (1.4.1),
    # Call Upon an Emir (3.5.2), Muster (3.4.1), Supply (4.6.1), Tax
    # (4.7.3) — but NOT Locale Friendliness.
    printed_seat_lord_ids: list[str] = Field(default_factory=list)
    siege_yellow: int = 0  # Christian-placed Siege progress markers
    siege_green: int = 0  # Muslim-placed Siege progress markers
    bypass_yellow: bool = False
    bypass_green: bool = False
    ravaged: RavagedState = "none"


class Taifa(StrictModel):
    """One of the 7 Muslim Taifas.

    Christian "Kingdoms" (León, Aragón) are NOT Taifas and live in their
    own structure (or implicitly as a territory string on Locales).
    """

    id: str
    name: str
    locale_ids: list[str] = Field(default_factory=list)
    status: TaifaStatus = "independent"
    # Sevilla has 3 status boxes per Map reference; status changes place
    # 3 markers. `status_marker_count` tracks how many are placed.
    status_marker_count: int = 0


class Way(StrictModel):
    """A connection between two Locales.

    Stored as a list on GameState, NOT a dict keyed by (a, b)
    (Pattern 4 / SMOKE-047, 067-069). Each Way carries its `way_type`
    so parallel Ways are distinguishable.
    """

    a: str  # locale_id
    b: str  # locale_id
    way_type: WayType


class Decks(StrictModel):
    """Arts of War deck state.

    `capabilities_in_play` holds side-wide-scope cards (Pattern 14).
    This-lord-scope cards live on `Lord.capabilities`.

    `this_levy_events` and `this_campaign_events` are the persistence
    buckets for hold-events drawn this turn (cleared at the relevant
    window boundary per Pattern 13).
    """

    draw: list[str] = Field(default_factory=list)
    discard: list[str] = Field(default_factory=list)
    held: dict[Side, list[str]] = Field(default_factory=dict)
    capabilities_in_play: list[CardInPlay] = Field(default_factory=list)
    # Christian/Muslim board-edge Capability cards available for Levy.
    board_edge: dict[Side, list[str]] = Field(default_factory=dict)
    # Cards removed from the game permanently (never recycled into the
    # draw deck). E.g. C18 Milites: "discard removes the card from the
    # game ... removes Event #C18 Runaway Slaves with it" (AoW ref).
    removed_from_game: list[str] = Field(default_factory=list)

    # Per-Levy / per-Campaign event persistence buckets (Pattern 13).
    # Cleared at the end of their respective windows.
    this_levy_events: dict[Side, list[str]] = Field(default_factory=dict)
    this_campaign_events: dict[Side, list[str]] = Field(default_factory=dict)

    # Cards just drawn but not yet implemented (3.1 Arts of War step).
    pending_draw: dict[Side, list[str]] = Field(default_factory=dict)

    # Campaign Plan stacks (rule 4.1). One per side; revealed in order
    # during Activation. Pattern 13: cleared at end-of-Campaign.
    plan: dict[Side, list[PlanEntry]] = Field(default_factory=dict)


class PendingDecision(StrictModel):
    """A response/choice owed by some side before play can continue.

    Phase 0 scaffold. Phase 2+ will populate `kind` with action-specific
    discriminators (battle strike select, siege response, event target
    pick, etc.) and may turn this into a discriminated union.

    Pattern 11 (active-player desync): when `pending` is set, the side
    in `waiting_on` must equal `Meta.active_player`. Tests should
    assert this invariant.
    """

    kind: str
    waiting_on: Side
    payload: dict[str, Any] = Field(default_factory=dict)


class HistoryEntry(StrictModel):
    """One action recorded in the game history log."""

    turn_index: int
    actor: Side | Literal["system"]
    action: str
    args: dict[str, object] = Field(default_factory=dict)
    summary: str = ""


class Score(StrictModel):
    """Victory point totals, separated by side and source.

    Detail breakdown (Conquered, Jihad, Taifa-status, etc.) added in
    Phase 1 when scoring is wired up.
    """

    christian: float = 0.0
    muslim: float = 0.0

    # Phase 7b: end-of-game verdict (rule 5.1/5.2/5.3). Populated by
    # campaign.compute_victory when the scenario ends. `winner` is
    # 'christian', 'muslim', or 'draw'; *_final are the recomputed
    # board VP totals; reason explains the trigger.
    winner: str | None = None
    christian_final: float | None = None
    muslim_final: float | None = None
    victory_reason: str | None = None


class GameState(StrictModel):
    """The full game state.

    Invariants future phases must enforce (and tests must check):

    1. Pattern 11: `pending.waiting_on == meta.active_player` whenever
       `pending` is not None.
    2. Pattern 6: any cylinder/Service marker not on the 16-box track
       must live in exactly one of the off-edge lanes.
    3. Pattern 14: every `CardInPlay` with `scope == "this_lord"` must
       have its `card_id` in exactly one `Lord.capabilities` list.
    4. Pattern 8: removed Lords have all `cleanup_on_removal_fields`
       fields cleared.
    """

    meta: Meta
    calendar: Calendar
    lords: dict[str, Lord] = Field(default_factory=dict)
    locales: dict[str, Locale] = Field(default_factory=dict)
    taifas: dict[str, Taifa] = Field(default_factory=dict)
    ways: list[Way] = Field(default_factory=list)
    decks: Decks = Field(default_factory=Decks)
    pending: PendingDecision | None = None
    # Phase 7g: the Muslim Taifas box (rule 4.1.4 Dinars, 1.4.2). Holds
    # Coin deposited by Taifa Lords and any VP banked there (e.g. C25
    # De Vivar Reconciliation). taifas_box_coin counts toward C10
    # Devaluation totals; taifas_box_vp is added to Muslim VP at end.
    taifas_box_coin: int = 0
    taifas_box_vp: float = 0.0
    # Cathedral Seat markers (C16 Cathedrals capability, Alfonso). Each
    # locale_id here holds one of Alfonso's <=2 Cathedral Seats: it acts
    # as a Christian Seat AND is worth +1 Christian VP (5.1).
    cathedral_seat_locales: list[str] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list)
    score: Score = Field(default_factory=Score)
