# manager memory

## Lessons
- Every AC noun that names a world concept (e.g. "unclaimed-land pool") needs a concrete accessor (name, type, config key, snapshot key) in the Contract; otherwise the coder skips it and the tester tests a proxy. Scan the AC list for such nouns before approval. (P1)
- Two coders worked well for "simulation vs observer" once the shared data shapes (frame dataclass, config TOML shape, view API) were frozen in the Contract and coder-b started on work needing no Python. (P1)
- Tim's laptop is 3200x2000 (high DPI): any window must size from the desktop and pick a scale by tiles visible, never a fixed small window at scale 1; any live view needs a speed control or real-time pace looks frozen. Look at the screenshot critically before calling a viewer done. (P1)
- Tester reports that say "contract names no accessor, tested a proxy" are a real gap signal: check them at verify. (P1)
- A Contract with exact pure accessors plus worked example values (slide_position numbers, formula for rates, version message) gave a zero-fix-round phase. Keep doing it. (P1.5)
- Statistical/time-based ACs (rates over a week, full years) make the suite slow (14 s -> 5.4 min in P1.5). In the Test Task, ask the tester to mark long tests `slow` and keep the default run short. (P1.5)
- Check for stray files in the root after coders run (a shell redirection slip left empty .py files). The ownership check catches them. (P1.5)
- Telegram tools accept half phases (3.5) since Tim's fix before P3.5: use the real phase number in tg_ask qids (P3.5-C-CDX-01) and tg_close. Before the fix, half phases could not ask questions and closed the wrong id. (P1.5, fixed P3.5)
- Agents have hard turn limits (coders 60, tester/debugger 40). For a big phase (~15 Work IDs per coder) every agent hit them in R0. Delegate in slices (2-5 Work IDs per call), and always say "write the Report by turn ~45 (coders) / ~30 (tester, debugger)" and "run long commands with a timeout, not in the background". (P2)
- A scripted "uses every action and finishes all stages" player is a large job in its own right: give it its own Work IDs and a pass after the engine runs, not one line. (P2)
- Never write a Plan note time by hand: take it from Get-Date. An Edit that fails because the file changed means the note is missing, so re-check before telling an agent to read it. (P2)

- Slicing worked in P3: coders in 3 slices each, tester in 2 parts (ACs 1-9, then 10-16 + full suite in background); no turn-limit resends. Keep it. (P3)
- Verified replay (compare regenerated tail to stored events) catches hidden state gaps (controller sub-state, dict order); demand it whenever saves/restores change. (P3)
- Tim's test-run rule: see [feedback_test_runs.md](feedback_test_runs.md) (slow marks; "not slow" during rounds; full suite before judging and Done). (P3)

- Look at coder screenshots before testing and send a small polish Work ID then (P3.5 B-10: tiny graphs, cut guide box); cheaper than a fix round. Running the full suite myself in the background after the tester's quick run saved tester turns. (P3.5)

- With threads, freezing "apply in player order" is not enough: anything that emits events (generators fed replies) must also advance in a fixed order. Write that into the Contract when a phase adds concurrency. (P4)
- Look at screenshots after every UI follow-up too: P4's "readable rows" fix changed only the plain-text path, not the drawn rich-text path. (P4)
- Telegram can be down at clarify time; ask fewer, decide from research.md, and mark the rows "Telegram unavailable". (P4)
- When a phase adds a new kind of row to every run (judge calls), list in the Test Task the old tests that count rows, roles or players over a whole table, slow ones included: P5's only fix round was an old slow test asserting the role set of ai_calls. (P5)
- Before the first paid phase, ask whether the money path is truly bounded and atomic (reservation bound, call+spend in one transaction, no silent fake fallback); Codex's review found all three gaps I missed. (P5)
- Before any phase that sends live AI calls, make the Contract demand an offline scan of every schema per provider (closed objects, no maps, union limits) and a clean path for every SDK 4xx. Tim's first live call hit both (P5 R2).
- Never run the full suite while the tester runs its suite: timing tests (P3 fps) flake under load. Rerun a timing-only failure alone before sending the debugger. (P5 R2)
- Vendor limits that cannot be verified offline (schema complexity) need a config-switchable fallback and a cheap preflight that reports every provider at once, not a cleverer schema each round: R2's fix traded one Anthropic limit for another. (P5 R3)
- Any bound that provider_schema drops for a provider (maxItems, min/max) must be stated in the prompt or normalised before validation, or real models break it (P5 R5: 5-6 value ids). Practice runs overwrite Tim's real reports (runs/*/report.md): never run a dry run right after his paid run without copying the report first. (P5 R5)
- For any provider setting ladder, read the installed SDK's allowed values first (Literal types) and include every step; P5 stopped at "high" while anthropic xhigh/max and openai xhigh existed, costing Tim two paid runs. Check durations/tok-s in calls.db to tell "not thinking" from "not counted". (P5 R7)

## Log
### P5 R8 | manager | 2026-11-05 08:53-09:00 (7 min) | opus
- Rounds ran: 8 (save Tim's chosen settings after calibrate $2.43: claude xhigh 288 / max 5886; gpt xhigh 1034, gemini/grok medium ~1000)
- Coders: coder-a P5-A-20-R8 config only (Report relayed by me: it said it had no handoff edit access)
- Tester: 1 test made text-independent, 1 new; subset 161 passed; no long run (Tim)
- Note: calibrate's chooser optimises the all-four ratio and so picked gpt high when claude cannot match; a chooser that matches the matchable models first would have picked gpt xhigh
### P5 R7 | manager | 2026-11-04 23:24-23:35 (11 min) | opus
- Rounds ran: 7 (reopened: claude refused thinking type enabled; adaptive never thinks at medium/high)
- What I did: duration/tok-s check proved no thinking; SDK literals showed unused effort steps (anthropic xhigh/max, openai xhigh); config-only fix
- Coders: coder-a P5-A-19-R7 (ladders, max_rounds 6)
- Tester: R5/R6 tests moved to explicit force configs; subset 135 passed; no long run (Tim)
- Lesson: before adding a new mechanism, read the installed SDK's allowed values; the ladder stopped at "high" while xhigh/max existed (cost Tim two paid runs)
### P5 R6 | manager | 2026-11-04 22:51-23:12 (21 min) | opus
- Rounds ran: 6 (reopened after Tim's calibrate, $1.06: claude adaptive never thinks; gemini low = 0 misreported)
- What I did: diagnosed from calls.db + installed SDK types; Contract: ladder force table (anthropic enabled/1024), overshoot rule, provider_error never stops the search, max_rounds 5; coder-a then coder-b in sequence (accessor named in A's Report)
- Coders: coder-a P5-A-18-R6; coder-b P5-B-16-R6, P5-B-17-R6 (label order)
- Tester: test_p5_r6_force.py 16; 212/2 then my subset 39 passed; no long run (Tim)
### P5 R5 | manager | 2026-11-04 22:16-22:38 (22 min) | opus
- Rounds ran: 5 (reopened after Tim's first finished calibrate, $0.76)
- What I did: diagnosed from calls.db myself (maxItems not sent to openai/xai -> 5-6 value ids; claude adaptive medium thought 0 tokens -> search stopped); Tim asked for no long test; short subset only
- Coders: coder-a P5-A-16-R5 (cut lists), P5-A-17-R5 (no change); coder-b P5-B-15-R5 (zero median climbs ladder)
- Tester: test_p5_r5_calibrate.py 12 tests, subset 194 passed
- Lesson candidates: bounds dropped from a provider schema must be stated in the prompt or normalised; my dry-run calibrate overwrote Tim's real report.md (copy reports before practice runs)
### P5 R3-R4 | manager | 2026-11-04 20:37-21:53 (76 min) | opus
- Rounds ran: 3, 4 (re-plan; same approach, one config fault)
- What I did: debug task on "Schema is too complex"; Tim chose prompt mode for Anthropic; Contract change 20:43 (per-provider output_mode, Google guard, calibrate Form check); follow-up fix line; R4 re-plan for the output_mode table bug
- Coders: coder-a P5-A-12..14-R3, P5-A-15-R4; coder-b P5-B-13-R3, P5-B-14-R3
- Tester: R3 test_p5_r3_prompt_mode.py (50) + 4 old files updated, 1 fail; R4 pass, not-slow 1073; my full run 1117 passed
- Debugger: R3 Anthropic grammar compile on 19 optional properties; Google exclusiveMinimum risk
- Detail: see handoffs/phase-5.md#summary-rounds-3-4

### P5 R2 | manager | 2026-11-04 18:47-20:26 (99 min) | opus
- Rounds ran: 2 (reopened after Done: Tim's live calibrate got Anthropic 400)
- What I did: Plan note with Tim's error, debug task, Contract change 18:52 (map wire form, Anthropic optional fields, provider_error pause); verify full suite 1065/1 fps flake (concurrent load), rerun alone passed
- Coders: coder-a P5-A-09..11-R2; coder-b P5-B-12-R2
- Tester: test_p5_r2_strict.py 102 cases; not-slow 1022 passed
- Debugger: R2 open map schemas (offer/want); non-429 4xx escaped as raw SDK errors
- Detail: see handoffs/phase-5.md#summary-round-2

### P5 | manager | 2026-11-04 15:40-18:40 (180 min) | opus
- Rounds ran: 0-1
- Planning: coders 2 (Codex 2); Codex Done; adopted 35 of 43 decision rows (ideas 1-5, 3 and 4 with changes); Telegram ok, 2 asked, 1 answered (the pause-on-judge-failure answer was rejected: failed labels continue)
- What I did: merged a C1-C10 contract (config, spend safety, live runtime, profiles, judge schemas/packet/service, minds samples, CLI, tools, observer); screenshot review gave polish B-11 (judge_summary row kind); ran the full suite myself twice
- Coders: coder-a P5-A-01..08 in 3 slices (spend safety, live runtime, judge, samples); coder-b P5-B-01..10 in 4 slices + B-11 (CLI, measures, analyze, tuning, launch-check, judge-check, calibrate, observer, guide)
- Tester: R0 2 parts, 5 new files (97 tests) + conftest offline guard, 4 old tests updated; quick 920 passed; full 963/1 failed; R1 test_p4_run judge-row filter; full 964 passed (18:19)
- Debugger: R1 outdated expectation in test_p4_run check_run (judge rows), owner tester
- Detail: see handoffs/phase-5.md#summary

### P4 | manager | 2026-11-04 10:50-13:21 (151 min) | opus
- Rounds ran: 0 only
- Planning: coders 2 (both plans 2); Codex Done; adopted 33 of 38 suggestions (ideas 1,2,3,5 adopted, 4 changed; rejected pending-intent journal, delayed effect upgrades, ai_budget_blocked event); Telegram down, 3 questions decided; Tim kept gemini-3.8-flash
- What I did: merged a C0-C9 contract (types, money examples, broker rules, turn/sim, storage, minds with value/memory/mistake examples, CLI); Plan notes 11:26, 11:39, 11:52; screenshot review caught wait_hook wiring and raw-JSON choice rows; ran full suite myself
- Coders: coder-a P4-A-01..06 in 3 slices + cause_kind follow-up (broker rounds in pipeline order for determinism); coder-b P4-B-01..06 in 3 slices + 2 follow-ups (live.wait_hook, choice rows in words)
- Tester: 2 parts, 5 new test files, 3 old tests updated; quick 826 passed; full suite 867 passed (27:52)
- Debugger: not needed
- Detail: see handoffs/phase-4.md#summary

### P3.5 | manager | 2026-11-03 10:59-12:46 (107 min) | opus
- Rounds ran: 0 only
- Planning: coders 2 (both plans 2); Codex Done; adopted 33 of 38 suggestions (ideas 1-4 adopted, 5 changed: generated guide; rejected A-owned observer read model, no villager night sleep, B owning CLI/guide)
- What I did: merged a frozen frame/layout/selection/inspector/series contract; Plan notes for links on the time stamp and the B-10 polish after looking at screenshots; ran the full suite myself
- Coders: coder-a P3.5-A-01..06 in 3 slices (frame fields, config tables, history who/x/y, series, CLI, guide generator); coder-b P3.5-B-01..10 in 3 slices + polish (camera, layout, keys, prefs, bubbles, chats, inspector, flashes, graphs, minimap)
- Tester: R0 155 new tests in 2 parts; quick 683 passed; full suite 715 passed (13:50)
- Debugger: not needed
- Detail: see handoffs/phase-3.5.md#summary

### P3 | manager | 2026-11-02 15:53-20:12 (259 min) | opus
- Rounds ran: 0-1
- Planning: coders 2 (both plans 2); Codex Done; adopted 33 of 38 suggestions (ideas 2, 3, 5 adopted; 1, 4 changed: no per-minute marker/welfare events; rejected own snapshot v4)
- What I did: merged a frozen Controls/Observer/RunDB/frame/measures contract; Plan notes for Observer kwargs and minds/ ownership to coder-a (scripted dummy state); checked night/day screenshots
- Coders: coder-a P3-A-01..10 in 3 slices (+ scripted state fix, canonical config order), P3-A-08-R1 (_player_ids path); coder-b P3-B-01..05 in 3 slices + night check (no change)
- Tester: R0 72 new tests, 600 passed / 1 failed (26:41); R1 601 passed (25:51); slow markers added
- Debugger: R1 weekly._player_ids read state.world.players instead of state.world.people.players
- Detail: see handoffs/phase-3.md#summary

### P2 | manager | 2026-11-02 10:58-15:24 (266 min) | opus
- Rounds ran: 0-1 (R0 had two in-round passes per coder after turn-limit resends)
- Planning: coders 2 (Codex proposed 1); Codex Done; adopted 31 of 35 outside suggestions (5/5 ideas; changed sanitized-world, landmark tile, belief literalism; rejected Manhattan distance, first-finisher bonus)
- What I did: merged plans into a frozen engine/perception contract; resent coder-a, coder-b, tester and debugger after turn limits; Plan notes for coder-b bug fix, coder-a balance pass, coder-b scripted pass; relaxed AC-30 to 8 game weeks
- Coders: coder-a P2-A-01..15 (engine, balance pass), P2-A-02-R1 (39 reason comments); coder-b P2-B-01..09 (senses, tasks, minds, report, viewer), P2-B-07-R1/P2-B-09-R1 (scripted rewrite, border frames)
- Tester: R0 501 passed / 7 failed; R1 529 passed (17 min)
- Debugger: R1 poach test loyalty below leave_below; missing reason comments; outdated snapshot-version tests; scripted script bugs (target vs structure, visits, no pen/herb/stakes, too little recruiting)
- Detail: see handoffs/phase-2.md#summary

### P1.5 | manager | 2026-11-02 08:48-09:54 (66 min) | opus
- Rounds ran: 0 only
- Planning: coders 2 (both plans 2); Codex Done; adopted 22 of 25 outside suggestions (5/5 ideas; changed light location and dusk timing, rejected resting-animal dog checks)
- What I did: merged plans with frozen AssetsConfig/movement/WorldFrame/observer accessor contract; resent coder-b to finish screenshots after A-08; coder-a removed 3 stray root files
- Coders: coder-a P1.5-A-01..08 (movement.py, config models, snapshot v2, daylight, WorldFrame; full year ~10-18 s); coder-b P1.5-B-01..05 (Tiny Creatures picks, colour/mono loader, viewer slide/light/cache, CLI pacing)
- Tester: R0 328 passed (hit its turn limit after writing the Report; no memory entry); Phase 1 tests updated to new shapes
- Debugger: not needed
- Detail: see handoffs/phase-1.5.md#summary

### P1 | manager | 2026-11-01 18:35-19:59 (84 min) | opus
- Rounds ran: 0-2 (R2 reopened after Done for Tim's review: blurry, nothing moving)
- Planning: coders 2 (Claude proposed 1, Codex 2; took 2); Codex Done; adopted 18 of 20 outside suggestions (5/5 ideas, rejected persisting view/resume, changed autosave to Phase 3)
- What I did: merged plans, froze WorldFrame/AssetsConfig/view API contract; verify found the unclaimed-land pool missing -> Contract change in R1
- Coders: coder-a P1-A-01..14 (R0), P1-A-15-R1 (pool); coder-b P1-B-01..03 (assets.toml 126 items, loader, Viewer)
- Tester: R0 175 passed; R1 180 passed (AC-12 pool test rewritten, AC-4 pool_zones case)
- Debugger: R1 root cause = Contract never defined the pool; owner coder-a after manager Contract change
- Detail: see handoffs/phase-1.md#summary
