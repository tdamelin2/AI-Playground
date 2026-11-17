# coder-b memory

## Lessons
- Hooks block writing outside Part folders, even the scratchpad. Put throwaway check scripts inside your own folder and delete them afterwards.
- Kenney monochrome-transparent.png is a palette PNG with a colour key: get_at() reports alpha 255 everywhere. Blit it onto a SRCALPHA surface before reading pixels.
- A formatter hook rewrites files after Write; Read before editing text it may have reflowed.
- Scratch scripts and screenshots can go in the session scratchpad dir via PowerShell (it is writable).
- Dummy driver window is 1280x800 (scale 1); pass a model_copy of ViewConfig with a big window to see scale 3.
- Large phases hit the turn limit: write big files in one Write each and put the Report in early (by turn ~45).

- Harness: Simulation.new(load_config(Path("config")), 1, "scripted") + sim.run(days*1440) in-process is ~1 s per game day and lets you print world state; world.events keeps every event (a controller can scan it by index).
- Gather/harm/recruit actions walk to their target themselves (Plan goal/reach); do not issue approach moves. Failed begins emit no action_started.

- pygame_gui wheel scrolling reads the real mouse: call pygame.mouse.set_pos in synthetic tests. Post UI_BUTTON_PRESSED or real mouse down/up for buttons.

- Write tool is blocked for the scratchpad; use PowerShell Set-Content there. Assemble big files from parts kept inside observer/ and delete them.

- pygame_gui `<a>` links ignore `<font color>` (link colour is per text box); put links on a neutral part of the row (time stamp) and colour names separately.

- Never splice a file with PowerShell array slicing from Select-String line numbers (a null index duplicated a whole file); use Edit. Never Write MEMORY.md as a placeholder; Edit it.

## Log

### P5 R6 | coder-b | 2026-11-04 22:58-23:20 (~22 min) | sonnet
- Work IDs: P5-B-16-R6 | Status: Done
- Files: changed measure/calibrate.py
- Approach: force table as a move at the top step (label "k=v, ..."), blocked list for refused/overshoot steps, provider_error caught per search step; apply deletes extra thinking keys.
- Issues: PS splice duplicated the file (repaired); R5 warning-text test now stale (tester).

### P5 R3 | coder-b | 2026-11-04 20:50-21:05 (~15 min) | sonnet
- Work IDs: P5-B-13-R3 | Status: Done
- Files: changed measure/calibrate.py
- Approach: _form_check sends one spec per (provider, model) via runner.execute one at a time, catches provider_error only; checked with a DryRunAdapter subclass raising ProviderRequestError.

### P5 R2 | coder-b | 2026-11-04 19:35-19:50 (~15 min) | sonnet
- Work IDs: P5-B-12-R2 | Status: Done
- Files: changed cli.py, measure/calibrate.py, measure/judge_check.py
- Approach: stop_text helper for every RunPaused reason; stop_reason/stop_detail on both result types; LLMError catch after the known tuple in main.

### P5 R0 slice 3b | coder-b | 2026-11-04 17:55-18:40 (~45 min) | sonnet
- Work IDs: P5-B-06, B-07, B-08, B-10 | Status: Done
- Files: created measure/judge_check.py, calibrate.py | changed cli.py, guide.py, docs/guide.md
- Approach: both tools drive CallBroker + SpendLedger(max_dollars) on a calls.db; dry run = FakeAdapter(bill=True) subclass.
- Issues: broker.run raises RunPaused and drops the chunk's results; the classifier blocked a piped non-dry calibrate test.

### P5 R0 slice 3a | coder-b | 2026-11-04 16:40-16:55 (~15 min) | sonnet
- Work IDs: P5-B-09 | Status: Done
- Files: created observer/judgeview.py | changed observer.py, measure/weekly.py

### P5 R0 slice 2 | coder-b | 2026-11-04 16:23-17:10 (~45 min) | sonnet
- Work IDs: P5-B-04, B-01 | Status: Done
- Files: created measure/tuning.py | changed cli.py, measure/analyze.py

### P5 R0 slice 1 | coder-b | 2026-11-04 16:05-16:12 (7 min) | sonnet
- Work IDs: P5-B-05, B-02, B-03 | Status: Done
- Files: created measure/launch_check.py, analyze.py | changed measure/weekly.py

### P4 R0 slices 1-3 | coder-b | 2026-11-04 | sonnet
- Work IDs: P4-B-01..06 | Status: Done
- Files: minds/settings, schemas, values, memory, prompts, ai, router, reflex, choice, outcomes, events, runtime; measure/decisions.py; observer/cli changes.

### P3.5 R0 slices 1-3 | coder-b | 2026-11-03 | sonnet
- Work IDs: P3.5-B-01..09 | Status: Done
- Files: observer camera/layout/keys/prefs/window/bubbles/chats/inspector/flashes/graphs/minimap.

### P3 R0 | coder-b | 2026-11-02 | sonnet
- Work IDs: P3-B-01..05 | Status: Partial then Done
- Files: observer/observer.py (Observer subclasses Viewer).

### P2 R0-R1 | coder-b | 2026-11-02 | sonnet
- Work IDs: P2-B-01..09 | Status: Done
- Files: rules/senses/*, rules/tasks.py, minds/dummy.py, scripted.py, measure/report.py, viewer.

### P1.5 / P1 | coder-b | 2026-11-01..02 | sonnet
- Work IDs: P1-B-01..06, P1.5-B-01..05 | Status: Done
- Lessons: colour key PNG; ruff format after Set-Content -Encoding utf8.
