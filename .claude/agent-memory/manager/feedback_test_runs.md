---
name: feedback-test-runs
description: Tim's rule for test runs: slow marks on long tests, quick "not slow" runs during rounds, full suite only before judging a round and before Done
metadata:
  type: feedback
---
The tester marks every full-year and week-long test `slow`. During a round, agents run `uv run pytest -m "not slow"` and rerun only the failed tests while fixing. Before a round is judged and before Done, run the full `uv run pytest` (in the background if it takes over 10 minutes) and record it as evidence.

**Why:** the full suite took 17 min in Phase 2; repeated full runs waste time and agent turns.
**How to apply:** put this in a Plan note at Round 0 of every phase and in every Test/Debug/Code Task; check the full-suite evidence before Pass and before Done.
