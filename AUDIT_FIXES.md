# October 2026 audit corrections

This change addresses the 27 findings from the review of commit `ff0c642`.
Rule and card citations live alongside the affected implementation and tests.

| Findings | Correction | Regression coverage |
| --- | --- | --- |
| 01–02 | Battle and Sally resolve, commit, and recover casualties per Lord even when the sides have different numbers of Lords. | `test_audit_combat_regressions.py` |
| 03, 07 | Ordinary, Call to Arms, and event Muster share complete Forces, Assets, available Vassals, Service, and arrival initialization. Permanently removed Vassals remain removed. | `test_audit_levy_regressions.py`, `test_audit_event_lifecycle.py` |
| 04–05 | Drawing a Hold stores it for later play; scenario Holds and newly drawn Holds use the same handlers and menus. Legacy holding buckets remain readable. Combat consumes its own played cards. | `test_audit_hold_lifecycle.py` |
| 06 | Berenguer Ramon requires payment and installs a correctly scoped Count capability with ownership and contingent tracking. Ordinary capability Levy remains usable. | `test_audit_event_lifecycle.py`, `test_aow_caps_muster_units.py` |
| 08 | Event Lordship bonuses are temporary modifiers rather than mutations of printed Lordship. | `test_audit_event_lifecycle.py` |
| 09 | Baggage Parapet payment protects both Service and remaining Spoils. | `test_audit_combat_regressions.py` |
| 10 | Serfs removed by Hits never recover through Losses rolls. | `test_audit_combat_regressions.py` |
| 11 | Walls and Siegeworks cancel different Hit types separately. | `test_audit_combat_regressions.py` |
| 12 | Ordinary synchronous and interactive Battles continue to a rules-defined conclusion. Storm retains its printed round limit. | `test_audit_combat_regressions.py` |
| 13–17 | Camels capacity, blocked Supply sources, special March groups and arrival decisions, and source-free Dawud Supply agree between menus and execution. | `test_audit_march_supply.py` |
| 18 | A Lord newly Mustered during the Muster segment cannot spend Lordship during that segment. | `test_audit_levy_regressions.py` |
| 19 | Permanently removed capabilities cannot return through Levy. | `test_audit_levy_regressions.py` |
| 20 | Employment payments are aggregated by payer before validation. | `test_audit_levy_regressions.py` |
| 21 | Uphold Dynasties validates the requested Jihad target before moving cylinders or awarding VP. | `test_audit_levy_regressions.py` |
| 22–23 | Freebooter uses normal at-Service-limit Disband and allows the printed allegiance change when Rodrigo already occupies the Calendar. | `test_audit_event_lifecycle.py` |
| 24 | Bernard de Sedirac installs the compulsory Cathedrals capability. | `test_audit_event_lifecycle.py` |
| 25–26 | Interactive combat reveals Mats; unused enemy Plans and private card histories stay hidden independently of the Hidden Mats option. | `test_audit_player_views.py` |
| 27 | The Jativa trace recognizes Python 3.12 comprehension inlining; CI covers Python 3.11 and 3.12. | `test_bgbook_jativa_storm.py` |

The stress-test invariant now accepts Calendar box 0, as specified by rule
2.2.3 and the existing state model. This corrects the check rather than
changing legal Calendar placement.

Final integration review also corrected card source bookkeeping: recycling
and capability acquisition remove the card from its previous draw/discard
location. Regression checks cover both capability scopes and first-Levy
deployment.

`ACTIONS.md` documents the added `play_event` interface. Player-facing
`redacted_view` protects private cards; administrative code can still inspect
the complete engine state with `GameState.model_dump()`.
