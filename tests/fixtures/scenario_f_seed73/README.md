# Scenario F / seed 73 regression positions

Source: the independent Scenario F playtest of main commit
`c4468413f486fa7361ade8467ee90f352ebcc323`, dated October 10, 2026.
These are exact saved board/RNG/turn positions from that playtest with only
`history` removed to keep the fixtures small. No board or rules fields have
been altered.

- `before-winter.json`: the siege line, before action 726 (`end_campaign`).
- `withdrawal-before-winter.json`: the full-length line, before action 725.
- `bishop-levy-placement-before.json`: Bishoprics just acquired during Muster.
- `spring-levy-actions.json`: original full-length-line actions 725–744,
  reaching the Muslim Muster segment after Winter/Spring Muster.

The nine assertions in `test_scenario_f_saved_positions.py` fail on the
source commit and pass with the Scenario F fixes. The original complete
playtest evidence preserves the unabridged histories and full game traces.
