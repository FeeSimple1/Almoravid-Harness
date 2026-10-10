# Scenario F / seed 137 reproduction positions

These are unedited board/RNG snapshots from the independently replay-verified
playtest of `090f224444a281bae690641322448b83d427d68d`. Only the history was
omitted when the original evidence bundle was created. `actions.json` contains
the original next action for each numbered snapshot; deferred-saqalibah is the
legal side branch in which the owner had not yet used the free recruitment.

Some positions already contain the old engine's incorrect side-wide M15/M20
setup. These fixtures reproduce isolated failure paths; they are not migrated
saves and are not offered as valid new-game setups. Fresh-setup regressions in
`test_seed137_capability_regressions.py` exercise the corrected scope end to end.
