# Almoravid Harness

Python harness for GMT's *Almoravid: Reconquista and Crusade in Spain, 1085-1086*.

See [`BRIEF.md`](BRIEF.md) for the project specification and
[`FUTURE_PROJECTS_LESSONS.md`](FUTURE_PROJECTS_LESSONS.md) for the
bug-pattern catalog inherited from the Nevsky harness (architecture
and process lessons only — Nevsky rules content is out of scope).

## Sagrajas battle options

Choose `sagrajas` for the published Background Book minigame, or
`sagrajas_variant` for the user-authorized, unofficial
[GermanBrau1 variant](https://boardgamegeek.com/thread/3717102/battle-of-sagrajas-variant).
The latter starts with the Christians attacking, three Christian Lords,
15 cavalry units and 10 infantry units, no Christian missile capabilities,
and Cantador assigned to Alfonso. It uses the same Muslim setup and battle
engine. The author's suggested extra cavalry for a more balanced contest
is not included in this fixed base variant.

```python
from playtest_harness import Harness

h = Harness("sagrajas_variant", seed=13)
print(h.show())
h.apply({"type": "resolve_battle", "side": "christian"})
```

The same option is listed by `almoravid scenarios` and can be saved with:

```sh
almoravid new sagrajas_variant --seed 13 --output sagrajas-variant.json
almoravid view sagrajas-variant.json
```

This is an alternate setup, not official errata or a guarantee of a Muslim
win. Standard combat rules, existing tactical policies, and optional-rule
flags still apply. The original `sagrajas` attack/defend choices remain
available in that scenario.
