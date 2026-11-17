# debugger memory

## Lessons
- A passing acceptance test can be vacuous when the Contract names no accessor (tester notes "contract names no accessor"). Check tester Report notes for these first; root cause is usually Contract gap + missing code, owner coder-a after a manager Contract change.
- Run scratch scripts from repo root with `uv run python logs/debug/<x>.py`; `load_sim_config(Path("config"))` + `generate_world(cfg, Streams(seed))` builds a world without assets.
- Tests can be imported in scratch scripts (sys.path insert tests/acceptance; `import test_p2_actions as t`) to replay a failing test step by step.
- `headless --run X` silently RESUMES an existing run: always use a fresh run name (a leftover from a turn-limited earlier run doubled my run). Delete runs/<name> afterwards.
- Run DB events table: columns id, tick, type, payload_json. logs/debug/scr_events.py summarises started kinds/fails.
- Scripted mind (minds/scripted.py) marks pieces done on issue, not on outcome; social/harm action requests put structure ids in `structure=`, not `target=`.
- Turn budget is tight: give the quick failures from a glance first, write the Report by ~turn 25.
- Snapshot state_json layout: top {controllers, schema, seed, world}; players/villagers/promises live under world["people"]. logs/debug/p3_snap.py dumps keys. Test fixture runs (p3b_*) are deleted after tests, so make a fresh run to inspect.
- Verify a fix without editing source by monkeypatching the module function in a logs/debug script.
- Only claim a grep result in a Report after running that grep.
- From P5 on, AI runs with a DB also write judge ai_calls (role "judge", player_id None): old tests asserting DISTINCT role/player_id sets break past tick 1440 or with choice points (owner tester). ai_calls has no `purpose` column; judge_kind is in details_json.

- Live-provider failures must be diagnosed offline: scan provider_schema output for every REPLY_TYPES/JUDGE_SCHEMAS model x provider (logs/debug/p5r2_schema_scan.py), and build SDK errors with a dummy httpx.Response (p5r2_badrequest.py). Grep tool skips .venv: search SDK code with PowerShell Select-String.

- Live 400s: read ai_calls status/error_json/duration_ms in the run's calls.db (logs/debug/p5r3_dur.py). Long durations before a schema 400 = server-side grammar compile; provider limits are not in the SDKs, so prefer fixes that do not depend on remembered limits.

## Log

### P5 R3 | debugger | 2026-11-04 20:37–20:40 (3 min) | opus
- Given: live calibrate Anthropic 400 "Schema is too complex"
- Commands: logs/debug/p5r3_calls.py, p5r3_dur.py (calls.db); p5r3_metrics.py (props/optional/anyOf per schema x provider); Select-String in anthropic SDK
- Root causes: Anthropic SlowReply/FastReply with 19 non-required props (17 in ActionRequest) -> grammar compile timeout (120 s) then 400 (coder-a); recommend Anthropic prompt-described JSON, no output_config.format
- Methods: DB timings (120 s timeout + 58 s 400), schema metrics, SDK types check (format Optional)
- Potential issues: Google exclusiveMinimum + 19 nullable may be rejected next; 120 s timeout vs first compile
- Restored: yes (no source edits)

### P5 R2 | debugger | 2026-11-04 18:48–18:52 (4 min) | opus
- Given: live calibrate Anthropic 400 (additionalProperties object), unhandled SDK 4xx traceback
- Commands: logs/debug/p5r2_schema_scan.py; logs/debug/p5r2_badrequest.py; Select-String in anthropic/openai SDK lib
- Root causes: ActionRequest offer/want maps -> open additionalProperties in fast/slow schemas (coder-a); map_error returns None for 4xx, broker _send catches only Network/RateLimit, cli has no handler (coder-a, + manager C1 PauseReason note)
- Methods: recursive scan of provider_schema output; read SDK strict transformers; map_error on built SDK errors
- Potential issues: Anthropic union-count limit (19 anyOf in fast/slow); calibrate re-raises network/sleep pauses as tracebacks; in-flight paid replies lost when an exception escapes broker.run
- Restored: yes (no source edits)

### P5 R1 | debugger | 2026-11-04 18:06–18:09 (3 min) | opus
- Given: test_p4_run.py::test_AC23_default_new_runs_a_whole_game_week (roles include "judge")
- Commands: pytest -k AC23; main.py new dbg_p5r1s --ticks 700 / dbg_p5r1w (week); logs/debug/p5_judge_rows.py
- Root causes: outdated old-test asserts at lines 385-386 vs Contract C6 judge rows (tester)
- Methods: counted ai_calls by role/player_id and judge_kind in fresh runs
- Potential issues: other slow tests filtering ai_calls by role/player could break similarly
- Restored: yes (no source edits)

### P3 R1 | debugger | 2026-11-02 19:38–19:41 (3 min) | opus
- Given: AC-13 test_AC13_quiet_players_still_get_total_rows_in_a_dummy_run
- Commands: pytest -k that test; headless --run dbg_p3r1 --players dummy --ticks 800; logs/debug/p3_snap.py, p3_weekly_fix.py
- Root causes: measure/weekly.py _player_ids reads state/world "players", but they are at world["people"]["players"] (coder-a)
- Methods: dumped snapshot keys; monkeypatched _player_ids -> 36 rows, 4 players, 9 measures
- Potential issues: none (only other "players" reader, state.py:386, reads the right level)
- Restored: yes (no source edits)

### P2 R1 | debugger | 2026-11-02 14:25–14:32 (7 min) | opus
- Given: AC11 poach, AC3 comments, AC30 x2, p15 AC6 version tests
- Commands: logs/debug/poach.py; headless --players scripted (resumed leftover -> 100800 min); logs/debug/scr_events.py, q.py
- Root causes: poach test loyalty 10 < leave_below -> villager leaves first (tester); AC3 missing comments (coder-a); p15 version 2 literal (tester); AC30 script: visit pieces give up after 12 moves, structure id in target= for sabotage/repair, no pen/herb/stakes, one-shot steal/recruit/assign; stage 3 stalls at 5 villagers/80 food (coder-b, threshold Medium)
- Methods: replayed test in scratch script; event counts from run DB; read begin funcs in harm.py/tools.py/social.py
- Potential issues: captives leave low_loyalty with 0 hungry days; player_4 home food exhausted
- Restored: yes (no source edits)

### P1 R1 | debugger | 2026-11-01 19:16–19:18 (2 min) | opus
- Given: AC-12 / P1-A-07 unclaimed-land pool missing (manager verify finding)
- Commands: Grep unclaimed/pool over src, config, docs, managers; uv run python logs/debug/pool_count.py
- Root causes: no pool in World state/mapgen/config; Contract never defined it -> owner coder-a after manager Contract change (World.unclaimed sorted list, world.toml [land] pool_zones, mask in snapshot)
- Methods: read state.py/mapgen.py/config.py; counted eligible tiles per zone for seeds 1-3 (buffer 3804, centre 642)
- Potential issues: AC-12 test vacuous; "urizen" guard line in observer/sprites.py vs AC-20 grep wording
- Restored: yes (no source edits)
