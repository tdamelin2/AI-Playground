# codex-reviewer memory

## Lessons
(none yet)

## Log
### P5 | codex-reviewer | 2026-11-04 15:46-2026-11-04 15:54 (8 min)
- Files given: 33 paths (folders counted once, restricted design sections).
- Verdicts: Keep 1, Maybe 4, Reject 0; Keep5 read-only diagnosis/raw launch gate; remaining ideas need explicit post-commit/replay, provenance/export, usage/schema/cap and backend contracts.
- Compatibility findings: 22 (High 11, Medium 11, Low 0).
- Top findings: complete-wire reservation must replace chars/4 before paid use; ai_call and spend commits have a crash gap; broker drops request.meta needed for durable summaries.
- Kept by Claude (from previous Summary's Planning outcome): unknown (previous Summary not assigned); manager context supplies Phase4 broad integration concerns, not treated as new instructions.
- Lesson candidate: cap review must inspect both reservation math and atomic persistence, and metadata proposals must be checked against the physical record writer rather than request DTO alone.

### P4 | codex-reviewer | 2026-11-04 10:59-2026-11-04 11:03 (4 min)
- Files given: 37 paths (folders counted once; phase-only design/gameplay sections plus actions).
- Verdicts: Keep 1, Maybe 4, Reject 0; Keep5 value projection; other ideas conditional on journal/pause, SDK/Google thinking, prefix/bootstrap and one-report/outcome contracts.
- Compatibility findings: 18 (High 10, Medium 8, Low 0).
- Top findings: detached recovery/empty tail misses durable replies beyond events; one report fan-out is essential because build_report consumes heard cursor; LiveRun must use pinned cap rather than current disk run config.
- Kept by Claude (from previous Summary's Planning outcome): manager supplied all fifteen P3.5 findings adopted, no later issues; guide became generated, all other ideas adopted.
- Lesson candidate: report-building and view/projection methods can mutate cursors, so inspect those side effects before reusing them for per-tick cognitive memory.

### P3.5 | codex-reviewer | 2026-11-03 11:06-2026-11-03 11:11 (5 min)
- Files given: 31 paths (folders counted once; section restrictions retained).
- Verdicts: Keep 3, Maybe 2, Reject 0; Maybe2 item-based gather progress and completion visibility; Maybe4 missing coordinates and snapshot/cadence contracts.
- Compatibility findings: 15 (High 5, Medium 9, Low 1).
- Top findings: gather yields items rather than one item per work unit and completed actions clear immediately; departure/damage events lack exact historical coordinates; snapshot relationship path is world.people.players list, not a mapping.
- Kept by Claude (from previous Summary's Planning outcome): P3 ideas2/3/5 adopted; idea1 verified replay adopted but per-minute marker rejected; idea4 semantic measures adopted but welfare daily; all15 findings adopted; no adopted idea caused reported problems, verified replay exposed controller/config-order divergence.
- Lesson candidate: broad observer features need stable plain-text compatibility plus separate rich rendering; frame/day and snapshot payload shape must be checked directly rather than inferred from UI labels.

### P3 | codex-reviewer | 2026-11-02 16:00-2026-11-02 16:05 (5 min)
- Files given: 29 paths (folders counted once).
- Verdicts: Keep 2, Maybe 3, Reject 0; Maybe1 complete-tick batching/performance, Maybe3 configured damage/no ruin mechanic, Maybe4 precise measurement semantics/event samples.
- Compatibility findings: 15 (High 6, Medium 8, Low 1).
- Top findings: finalize after every same-tick scheduler job and compare detached replay; chat projection has no deduplication identity; preserve snapshot3/config compatibility with event-only welfare samples.
- Kept by Claude (from previous Summary's Planning outcome): manager supplied all five P2 ideas and twelve compatibility findings adopted, no resulting problems; two parts needed due context limits.
- Lesson candidate: preserve standalone Viewer API and use a separate full-screen composition; per-tick durability must be checked against the existing persisted-year performance acceptance.

### P2 | codex-reviewer | 2026-11-02 11:10-2026-11-02 11:15 (5 min)
- Files given: 16 paths (folders counted once).
- Verdicts: Keep 4, Maybe 1, Reject 0; Maybe 5 requires measurement/action ambiguity decisions.
- Compatibility findings: 12 (High 7, Medium 5, Low 0).
- Top findings: minute coordinator must sit inside scheduled advance_to; human routes must not enter animal wander heap; snapshot all new actor/private/controller state without SQL migration.
- Kept by Claude (from previous Summary's Planning outcome): manager supplied all five Phase 1.5 ideas adopted, no resulting problems; suite about 5m25s.
- Lesson candidate: isolate earlier movement tests from new default human controllers while retaining populated-world determinism and performance checks.

### P1.5 | codex-reviewer | 2026-11-02 08:58-2026-11-02 09:00 (2 min)
- Files given: 16
- Verdicts: Keep 3, Maybe 2, Reject 0
- Compatibility findings: High 4, Medium 5, Low 1; resolve AC-2 populations<4 explicitly; distinguish sub_tick from segment progress; snapshot2 preserves destination/bout/deadlines/RNG without changing SQL schema1.
- Kept by Claude (from the previous Summary's Planning outcome): unknown (previous Summary not assigned).
- Lesson candidate: none; schema-specific legacy tests need explicit adaptation when an approved phase changes manifest structure.

### P1 | codex-reviewer | 2026-11-01 18:42-2026-11-01 18:44 (2 min)
- Files given: 8
- Verdicts: Keep 2, Maybe 3, Reject 0
- Compatibility findings: High 3, Medium 6, Low 0; freeze eight-table schema before coding; exact snapshot/RNG/scheduler/event boundary; controller owns ticking and persistence independently of observer.
- Kept by Claude (from the previous Summary's Planning outcome): unknown (first phase)
- Lesson candidate: none


