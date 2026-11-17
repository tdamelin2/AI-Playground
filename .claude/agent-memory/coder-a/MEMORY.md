# coder-a memory

## Lessons
- PowerShell 5.1 `Set-Content -Encoding utf8` writes a BOM and `a,b+c` array literals bind wrong: write TOML/code with the Write tool; the loader reads `utf-8-sig` anyway.
- A hook runs ruff format after each Write; run `uv run ruff check` after multi-file edits.
- Scheduler-heap simulation (jump to next due tick) makes a full game year take under 1 s; keep per-tick work out of the loop.

- PowerShell .NET File calls ignore the shell cwd: use absolute paths; multi-line Python in -Replace strings breaks on triple quotes, use the Edit tool.
- A per-tick movement job makes a full year take ~10 s (not <1 s); still fine for the 5 min limit.

- Never put "\n" inside Python code written via PowerShell/Edit strings; and cached derived grids (A* costs) must not outlive terrain changes or restore diverges. Wire the run loop early so the other coder can test.
- Phase 2 is large: write the Report by about turn 45; verify restore by diffing two snapshots after N ticks.

- Pytest "not slow" full run can exceed 3 min and gets auto-backgrounded; run targeted `-k` subsets for quick checks. The guard hook blocks writes outside Part folders (even scratchpad); use `python -` with a here-string for scratch checks. pytest has no --timeout option here.

- Async generator pipelines that emit events must be advanced in a fixed order (rounds, player order), never by completion order; test determinism with a recovery diff, not just two identical runs.

- Every non-comment key line in config/balance.toml needs a trailing `# reason` comment (test_AC3), including new tables.

- A per-player pydantic check the broker cannot know (value ids) goes in a same-named subclass from create_model (copy __doc__ so the provider schema is identical).

## Log

### P5 R3 | coder-a | 20:44-21:05 (21 min) | sonnet
- Work IDs: P5-A-12..14-R3 | Status: Done
- Files: changed config.py, config/models.toml, llm/{adapters,schema_transform,prices}.py
- Approach: RoleConfig.output_mode filled by validator (role > [llm.output_mode] > provider default); prompt mode in all adapters + extract_json; Google exclusive-bound guard.
- Issues: 5 old tests assert the previous Anthropic request shape; left for tester.

### P5 R2 | coder-a | 19:00-19:25 (25 min) | sonnet
- Work IDs: P5-A-09..11-R2 | Status: Done
- Files: changed llm/{schema_transform,broker,adapters,errors,types}.py, minds/{schemas,prompts}.py, storage/run_control.py
- Approach: generic map wire list + from_wire in broker._judge; Anthropic optional = non-required; ProviderRequestError -> request_error row + provider_error pause.
- Issues: a regex edit swallowed a field line; check diffs after regex rewrites. Full not-slow suite takes 9 min.

### P5 R0 slice 3 | coder-a | 17:25-17:55 (30 min) | sonnet
- Work IDs: P5-A-08 | Status: Done
- Files: created minds/samples.py | changed minds/ai.py, storage/{records,db}.py

### P5 R0 slices 1-2 | coder-a | 16:05-17:20 | sonnet
- Work IDs: P5-A-01..07 | Status: Done
- Files: judge.py, judge_schemas.py, config, llm/*, storage/*; judge calls appear in every fake AI run with a db.

### Earlier phases (P1-P4) | coder-a | sonnet
- Engine, observer, LLM broker/adapters built; details in git history and handoffs/phase-N.md.
