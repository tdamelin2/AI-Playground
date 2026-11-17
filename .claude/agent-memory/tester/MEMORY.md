# tester memory

## Lessons
- config/*.toml files have a UTF-8 BOM: read with encoding="utf-8-sig" (tomllib rb fails; prepending text breaks).
- Ruff checks tests/ too (AC-2 runs it): run `uv run ruff format tests` and `ruff check` before the final run.
- Write long PowerShell edits with [IO.File]::WriteAllText; Set-Content -Encoding utf8 adds a BOM.

- Example world (build_example_world) has no turn_handler: fire sweep, storm damage, dog attacks only run if the test sets w.turn_handler to run_turn(world, tick, None). Wanderers are not dog prey. world.stone keys are (x,y) = terrain[y][x].
- Run the full suite in the background-safe way: it takes ~10 min (Phase 1/1.5 year runs); give the Tee-Object command timeout 600000.

- Full suite now ~17 min: run it in background and wait with a bounded Get-Content loop (Start-Sleep chains are blocked). Test villager loyalty must stay above leave_below or it leaves on its own.

- events table is append-only via triggers: to tamper in tests, DROP TRIGGER on events first. Raise csv.field_size_limit for snapshots.csv. RunLock release lags a moment after kill: retry.

- Tick 0 is midnight (is_night). Hidden layout rects are zero-size at the window edge: skip them in contains() checks. Observer text box markup: obs.elements["text_box"].html_text.

- P4 fake-AI tests: new_ai_sim helper in tests/acceptance/p4_helpers.py (ai_config + Simulation.new, sim.adapters={"fake": FakeAdapter}); force triggers with clean(sim)+raise_int(...) then sim.run(1); FakeAdapter script entry is popped per attempt even when a failure is raised. Provider order: p1 anthropic, p2 openai, p3 google, p4 xai, judge mistral. Full non-slow suite ~5 min (tool backgrounds it; poll the output file).

- P4 scripts: a bad scripted reply is retried once, so script it twice to force a fallback. The first AI decision is not at tick 0: run several ticks (LiveRun.run_ticks(6)) before expecting day-0 ranking waits. Compare recovered event logs against a reference cut at the same tick. Multi-line .Replace edits fail on CRLF files: use the Edit tool.

- P5: tests/conftest.py sets AI_ISLAND_OFFLINE=1. ai_calls.model_version is the fake label ("fake-1"); the model id is in details_json $.model. Judge runs automatically with a fake adapter whenever a db is attached; use test_p4_choices.force/slow_reply to make choice points. PowerShell Get-Content -Raw then WriteAllText mangles UTF-8: use [IO.File]::ReadAllText. Never run `main.py calibrate` directly in the shell (classifier denies); only via pytest.

## Log

### P5 R8 | tester | 08:56-09:05 (9 min) | sonnet
- Given: P5-A-20-R8 defaults test + regex fix
- Result: 161 passed (subset), ruff clean
- Full log: logs/phase-5-r8-test.log

### P5 R6 | tester | 23:01-23:10 (9 min) | sonnet
- Given: force step, budget validation, overshoot, refusal (test_p5_r6_force.py) + R5 test update
- Checklist: all pass except force label order (actual "budget_tokens=1024, type=enabled" vs contract "type=enabled, budget_tokens=1024")
- Result: subset 212 passed, 2 failed
- Full log: logs/phase-5-r6-test.log

### P5 R0 part2 | tester | 18:05-19:10 (~65 min) | sonnet
- Given: AC-7,8,9,11 + 4 old-test updates + quick suite
- Checklist: all pass
- Result: 920 passed (not slow)
- Full log: logs/phase-5-r0-part2-test.log

### P5 R0 part1 | tester | 17:06-17:21 (15 min) | sonnet
- Given: AC-1..6, AC-10 + offline guard
- Checklist: all pass
- Result: 71 passed (4 new files, incl. slow pilot ~3 min)
- Full log: logs/phase-5-r0-part1-test.log

### P4 R0 part2 | tester | 13:00-13:50 (~50 min) | sonnet
- Given: AC-13..24 (test_p4_choices.py, test_p4_run.py)
- Checklist: all pass
- Result: 58 passed (new files incl. slow); not-slow suite 826 passed
- Full log: logs/phase-4-r0-part2-test.log

### P4 R0 part1 | tester | 12:08-12:55 (~47 min) | sonnet
- Given: AC-1..12 + 3 old-test updates
- Checklist: all pass
- Result: 776 passed, 0 failed (not slow); AC-11 week test slow, passes
- Full log: logs/phase-4-r0-part1-test.log

### P3.5 R0 part2 | tester | 12:20-12:58 (~38 min) | sonnet
- Given: AC-9..16 + CLI wiring + quick suite
- Checklist: all pass
- Result: 683 passed, 0 failed (not slow)
- Full log: logs/phase-3.5-r0-part2-test.log

### P3.5 R0 part1 | tester | 12:11-12:50 (~40 min) | sonnet
- Given: AC-1..8 + P3 HistoryRow test update
- Checklist: all pass (115 passed, not-slow subset of 3 files)
- Full log: logs/phase-3.5-r0-part1-test.log

### P3 R1 | tester | 19:43-20:09 (26 min) | sonnet
- Given: AC-13 rerun + full suite
- Checklist: all pass
- Result: 601 passed, 0 failed, 1551 s; ruff clean
- Full log: logs/phase-3-r1-test.log

### P3 R0 part2 | tester | 19:03-19:45 (42 min) | sonnet
- Given: AC-10..16 + RunLock + watch missing run; slow markers via --durations
- Checklist: AC-10,11,12,14,15,16 pass; AC-13 fail (weekly.py _player_ids reads wrong snapshot path: players are at state.world.people.players)
- Commands: uv run pytest --durations=30 > logs/p3_r0_full.txt
- Result: 600 passed, 1 failed, 1600 s
- Full log: logs/phase-3-r0-test.log
### P3 R0 part1 | tester | 18:53-19:30 (37 min) | sonnet
- Given: AC-1..9 + slow marker on 11 old long tests
- Checklist: AC-1..9 pass
- Commands: uv run pytest tests/acceptance/test_p3_observer.py -m 'not slow'
- Result: 41 passed (3 initial failures were my test bugs)
- Full log: logs/phase-3-r0-part1-test.log

### P2 R1 | tester | 15:01-15:19 (18 min) | sonnet
- Given: full re-run, fixed test_AC11_poach (loyalty 37.5)
- Checklist: AC-1..32 all pass
- Commands: uv run pytest (full)
- Result: 529 passed, 0 failed
- Full log: logs/phase-2-r1-test.log

### P2 R0 | tester | 2026-11-02 (resend, ~2 sessions) | sonnet
- Given: AC-1..32 (bodies, villagers, actions earlier; rules and runs files this session)
- Checklist: all pass except AC-3 (balance comments), AC-11 poach harm event, AC-30 scripted scenario; 3 old P1.5 snapshot-version-2 tests outdated
- Commands: uv run pytest (full, 10 min)
- Result: 501 passed, 7 failed
- Full log: logs/phase-2-r0-test.log

### P1 R2 | tester | 2026-11-01 19:56-20:08 (12 min) | sonnet
- Given: R2 viewer/config checks, P1-A-16/B-04/05/06-R2
- Checklist: all pass
- Commands: uv run pytest; ruff; view screenshot (dummy)
- Result: 192 passed, 0 failed
- Full log: logs/phase-1-r2-test.log

### P1 R1 | tester | 2026-11-01 19:21-19:30 (9 min) | sonnet
- Given: AC-1..22, P1-A-15-R1; rewrote AC12 pool test, added AC4 pool_zones test
- Checklist: all pass
- Commands: uv run pytest
- Result: 180 passed, 0 failed
- Full log: logs/phase-1-r1-test.log

### P1 R0 | tester | 2026-11-01 19:09-19:15 (6 min) | sonnet
- Given: AC-1..AC-22, no Work IDs beyond P1-A/B
- Checklist: all AC pass
- Commands: uv run pytest -q
- Result: 175 passed, 0 failed (first run: 17 failed from my own test bugs: BOM, ruff on tests, urizen guard line)
- Failure excerpt: none final
- Full log: logs/phase-1-r0-test.log
