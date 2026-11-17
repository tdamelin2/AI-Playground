# Questions

The Claude manager writes this file. No other agent edits it. After the planning
gate, it copies every question from both plans here and resolves each one.

- **Resolved**: answered from the project files. The Basis column names the file and
  section that supports the answer.
- **Escalated**: nothing in the project files supports an answer. Tim decides at the
  approval gate. Escalated questions are written in plain language.

Question IDs look like `P<phase>-Q-<CLA|CDX>-<number>`.

<!-- Each phase adds a section like this, newest phase last:

## Phase N: <name>
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| PN-Q-CDX-01 | Codex | yes | ... | ... | Overview.md, Architecture | Resolved |
| PN-Q-CLA-01 | Claude | no | ... | Tim: ... | none found | Escalated |
-->

## Phase 1: Skeleton and the island
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P1-Q-CLA-01 | Claude, Codex (P1-Q-CDX-02 part) | no | Does `view` write events/snapshots to the run database? | No. It loads the latest snapshot or a fresh seeded world, simulates in memory, never writes. | phases.md Phase 1 Requirements ("read-only pygame-ce window"); docs/architecture.md "Observer screen" | Resolved |
| P1-Q-CLA-02 | Claude, Codex (P1-Q-CDX-02 part) | no | How many ticks does `resume <run>` run, so it terminates? | Optional `--ticks N`, default run.toml `resume_ticks` = 1440; headless. | phases.md AC-22 (must be checkable by the tester) | Resolved |
| P1-Q-CLA-03 | Claude | no | Where does `headless` without `--run` store its log? | In-memory database; nothing written to runs/. | phases.md AC-22; Overview.md Folder layout (runs/ is program output per run) | Resolved |
| P1-Q-CLA-04 | Claude | no | What does models.toml contain now? | `[embedding] model = "nomic-embed-text"` and an empty roles table; no model names. | phases.md Phase 1 Requirements, Config | Resolved |
| P1-Q-CLA-05 | Claude | no | Which weather types stop outdoor work / put out campfires? | Storm stops outdoor work and puts out campfires; rain puts out campfires; drought lowers water. | docs/gameplay.md "Fire"; docs/design.md "Weather and seasons" | Resolved |
| P1-Q-CLA-06 | Claude | no | Where do config models, RNG and the tick loop live? | src/ai_island/config.py, rng.py, sim.py (top-level, no pygame). | Overview.md Components (no config package listed); CLAUDE.md AI Island rules | Resolved |
| P1-Q-CDX-01 | Codex | no | Adopt schema v1 names/types/JSON extension fields as the permanent base? | Yes, as in the Plan Contract. | docs/architecture.md "Everything is recorded", "Saving"; docs/design.md choice point record | Resolved |
| P1-Q-CDX-02 | Codex | no | Persistent live view/resume, isolated screenshot preview, `new` refusing existing names? | `new` refuses existing runs and screenshot mode never writes (adopted); resume is headless with --ticks and view never persists (see P1-Q-CLA-01/02). | phases.md Phase 1 Requirements and AC-22; docs/architecture.md "Observer screen" | Resolved |
| P1-Q-CDX-03 | Codex | no | UI/font concepts get manifest icons now, monogram/widgets wait for Phase 3? | Yes. | phases.md Phase 1 Notes ("monogram font is not needed until Phase 3"), AC-19 | Resolved |

## Phase 1.5: Colour and time-true movement
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P1.5-Q-CLA-01 | Claude, Codex (P1.5-Q-CDX-01) | yes | AC-2 cannot hold for a kind with fewer than 4 individuals; what is allowed? | Start cap per kind per tick: floor(N/4) for N >= 4, one start for N = 1-3; the AC-2 test states the denominator. | phases.md Phase 1.5 AC-2 ("no lockstep jumps") and Requirements (staggered first moves) | Resolved |
| P1.5-Q-CLA-02 | Claude | no | Does "snapshot schema version goes up by one" also bump the DB user_version? | No: SNAPSHOT_VERSION = 2 in sim.py; DB schema stays 1. | Overview.md Constraints (later phases add rows, not migrations); phases.md Phase 1.5 Movement | Resolved |
| P1.5-Q-CLA-03 | Claude | no | Where do dawn and dusk sit relative to night_start/night_end? | Dusk ends at night_start, dawn starts at night_end; fully dark exactly when is_night is true. | phases.md Phase 1.5 Colour ("is_night and every world rule that uses it stay exactly as they are"), AC-14 | Resolved |
| P1.5-Q-CLA-04 | Claude | no | Mono mode: smooth light layer or Phase 1 night dots? | The light layer in both modes; overlay_night stays mapped. | phases.md Phase 1.5 AC-16 (both palette modes) | Resolved |
| P1.5-Q-CLA-05 | Claude, Codex (P1.5-Q-CDX-04) | no | `new t1` refuses an existing run, but Tim's review says to run it again. | Tim reviews with a fresh run name; nothing is deleted. The tester uses its own fixture. | src/ai_island/cli.py `_cmd_new`; phases.md Phase 1.5 Notes | Resolved |
| P1.5-Q-CLA-06 | Claude | no | How does nest_eggs fit "every moving kind has the keys" with strict config? | `moves = false` and no movement keys; `moves = true` requires all of them. | phases.md Phase 1.5 Requirements ("Nests with eggs don't move"), AC-1 | Resolved |
| P1.5-Q-CDX-02 | Codex | yes | Is AC-8's 0 / 0.5 / 1 journey progress while live sub_tick is a fraction of one tick? | Yes: slide_position uses tick + sub_tick against move_start/move_end; AC-8 is tested with a one-tick step, plus multi-tick progress. | phases.md Phase 1.5 AC-5, AC-8, Viewer timing | Resolved |
| P1.5-Q-CDX-03 | Codex | no | May movement_step_ticks be restricted to 1? | Yes, validated = 1 with an error naming balance.toml and the key. | phases.md Phase 1.5 AC-5 (end at exactly T + M) | Resolved |

## Phase 2: Bodies, villagers, actions and senses
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P2-Q-CLA-01 | Claude, Codex (P2-Q-CDX-02) | yes | AC-19 says belief actions change nothing, but "build a shrine" creates a structure. | build_shrine = belief-tagged build of a shrine (materials + structure only); pray/ceremony change only time and the log; offering removes only the offered item; none affects X, needs, weather, animals or other players. | docs/design.md Religion ("no mechanical effect"); docs/gameplay.md Actions (Belief row); phases.md AC-16, AC-19 | Resolved |
| P2-Q-CLA-02 | Claude | no | AC-6 "X is 10 lower" vs respawn fixing the fatal need. | Respawn sets respawn_* body values, then B so X_after = max(0, X_before - 10). | docs/design.md Wellbeing X ("lose 10 points of X") | Resolved |
| P2-Q-CLA-03 | Claude, Codex (P2-Q-CDX-01) | yes | How are AC-29's "home food runs short", "players without food stores", "several days" and the acceptance run defined? | Seed 1, default config, 80,640 ticks, dummy controllers. Food short = first day the home zone's obtainable food < household daily need (target days 8-21). No stores = home store + storehouse/granary food at the start of week 7 < one household-day. Several days = >= 3 game days of hunger or hard work. | phases.md Phase 2 AC-29 and Notes | Resolved |
| P2-Q-CLA-04 | Claude | no | Merged into P2-Q-CLA-03 (no-store cohort). | See P2-Q-CLA-03. | phases.md AC-29 | Resolved |
| P2-Q-CLA-05 | Claude | no | Player and villager names: where and which? | world.toml `[agents] player_names` (4 neutral first names) and `villager_names` (>= 50); changeable before the real run. | docs/design.md Identity ("neutral human name") | Resolved |
| P2-Q-CLA-06 | Claude | no | Is "finishing a task first" a dominance bonus now? | No; only the landmark dominance bonus. | phases.md Phase 2 Requirements (Tasks) and AC-22 | Resolved |
| P2-Q-CLA-07 | Claude | no | Do villagers' job outputs go into the leader's stores? | Yes, into home_store (or a storehouse); the report's food_stored flag decides who "has stores". | docs/design.md Villagers ("adds labour"); phases.md AC-29 | Resolved |
| P2-Q-CDX-03 | Codex | yes | Landmark "held for a week": uninterrupted or most of the week? | Fixed game-week windows; > 50% of the week's minutes exclusive to one player (it or its villagers with loyalty >= 30) within landmark_radius 2; one bonus per landmark per week. | docs/gameplay.md Land and landmarks ("most of a game week"); phases.md AC-22, AC-23 | Resolved |
| P2-Q-CDX-04 | Codex | no | Can an addressed listener in sight but out of hearing receive talk? | No: the target must be in sight and hearing; otherwise it fails for that target. Anyone in hearing receives the words. | phases.md AC-27 | Resolved |
| P2-Q-CDX-05 | Codex | no | Freeze the five stage quantities/rewards and the pool-exhausted fallback? | Yes, values in the Plan Contract in balance.toml; a reward that needs an exhausted pool is recorded as pending, never spawned. | docs/design.md Tasks and rewards; phases.md AC-7 (no births) | Resolved |
| P2-Q-CDX-06 | Codex | no | Keep old saves or bump the snapshot to 3? | Bump to 3, DB schema stays 1, refuse older saves with the existing message. | src/ai_island/sim.py SNAPSHOT_VERSION; Questions P1.5-Q-CLA-02 | Resolved |
| P2-Q-CDX-01 | Codex | yes | Merged into P2-Q-CLA-03. | See P2-Q-CLA-03. | phases.md AC-29 | Resolved |

## Phase 3: Observer screen, run control and exports
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P3-Q-CLA-01 | Claude, Codex (P3-Q-CDX-03) | yes | Which command opens a live run in the full observer? | `main.py watch --run <run>` on an existing run (made with `new`); `view` stays a read-only preview; `resume` stays bounded headless. | phases.md Phase 3 Requirements ("the Plan names the command"); Questions P1-Q-CLA-01/02 | Resolved |
| P3-Q-CLA-02 | Claude, Codex (P3-Q-CDX-02) | yes | What counts as a help action, and how are promises, loyalty and weeks counted? | Helped event once per action at its first successful effect for someone else (gift, use_herb on another, teach, build/build_shrine/repair on another player's structure); promises counted in the week they happen; loyalty = mean of daily player_day.villager_loyalty; game_week = max(0, tick-1)//week_ticks+1; zero rows, null means. | docs/design.md Measures tracked over time; docs/gameplay.md Actions | Resolved |
| P3-Q-CLA-03 | Claude | no | Does autosave apply to headless and resume too? | Yes, every persisted run, at exact multiples of autosave_interval. | docs/architecture.md Saving ("Autosave takes a snapshot every 6 game hours") | Resolved |
| P3-Q-CLA-04 | Claude | no | How is crash recovery tested without a real crash? | Hidden `--crash-after-tick N` (flush, os._exit(3)), plus a real killed subprocess in the tests. | phases.md AC-11 | Resolved |
| P3-Q-CLA-05 | Claude | no | Where are the spend cap and warning? | run.toml `spend_cap_usd = 100.0`, `spend_warning_share = 0.8`; total = SUM(spend.cost_usd). | Overview.md Constraints (Budget); docs/architecture.md ("Spend reaches 80% of the cap") | Resolved |
| P3-Q-CLA-06 | Claude, Codex (P3-Q-CDX-05) | no | How are building sites and damaged buildings drawn? | Complete: `<kind>`, or `damaged_<kind>` when Structure.damaged(damaged_share); in progress: faded base sprite plus progress bar; destroyed: gone. | phases.md AC-8; config/balance.toml buildings.damaged_share | Resolved |
| P3-Q-CLA-07 | Claude | no | Average villager loyalty per week: from what? | Merged into P3-Q-CLA-02 (daily player_day.villager_loyalty). | docs/design.md Measures (villager welfare) | Resolved |
| P3-Q-CDX-01 | Codex | yes | Does AC-11's crash point mean the last committed whole tick, with uncommitted work rerun? | Yes: recovery restores the latest snapshot and replays to the last stored event's tick with full verification; uncommitted work is rerun deterministically. No per-minute marker (see Decisions 2). | docs/architecture.md Saving, pausing and resuming; src/ai_island/sim.py run (flushes after whole ticks) | Resolved |
| P3-Q-CDX-04 | Codex | no | Keep grave markers for every death, even after a player respawns? | Yes, from died and villager_died events, indefinitely; observer only. | phases.md Phase 3 Map additions ("grave"); src/ai_island/rules/body.py respawn | Resolved |
| P3-Q-CDX-03 | Codex | no | Merged into P3-Q-CLA-01. | See P3-Q-CLA-01. | phases.md Phase 3 Requirements | Resolved |
| P3-Q-CDX-05 | Codex | no | Merged into P3-Q-CLA-06. | See P3-Q-CLA-06. | phases.md AC-8 | Resolved |
| P3-Q-CDX-02 | Codex | yes | Merged into P3-Q-CLA-02. | See P3-Q-CLA-02. | docs/design.md Measures | Resolved |

## Phase 3.5: Observer comfort and the player guide
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P3.5-Q-CLA-01 | Claude | yes | May the frame carry needs, health, items, tools, loyalty and bond for the Inspector? | Yes, as defaulted AgentView fields; no snapshot/DB/event change. | phases.md 3.5 Inspector ("built from ... frame and database"), Frame data ("No snapshot, database or event changes") | Resolved |
| P3.5-Q-CLA-02 | Claude, Codex (P3.5-Q-CDX-02) | yes | Where do flashes for events without a tile (villager departure, building damage) go? | Building damage: the tile of its structure_built event; departure: the villager's position in the current frame; neither -> no marker, J still selects. No snapshot approximation. | src/ai_island/storage/events.py VillagerLeft/StructureDamaged; phases.md 3.5 Frame data | Resolved |
| P3.5-Q-CLA-03 | Claude | no | Screenshot name `d3` with `w2`: day of week or of year? | Day of week: (day-1) % 7 + 1. | src/ai_island/world/clock.py (day = day of year); phases.md AC-13 example | Resolved |
| P3.5-Q-CLA-04 | Claude | no | What does Esc do with the help overlay open? | Still quits; H closes the overlay. | phases.md 3.5 ("Esc keeps its Phase 3 meaning") | Resolved |
| P3.5-Q-CLA-05 | Claude | no | Hand-written or generated guide? | Generated by `main.py guide` from argparse, KEY_TABLE and assets.toml; committed; a test checks equality. | phases.md AC-14 | Resolved |
| P3.5-Q-CLA-06 | Claude | no | When is a villager "sleeping"? | At night (villagers stop work and go home then). | src/ai_island/world/villagers.py think(); phases.md 3.5 Frame data ("idle or sleeping") | Resolved |
| P3.5-Q-CLA-07 | Claude | no | Do pause/close snapshots count as graph points? | No: only ticks on the autosave cadence, largest id per tick, no tick 0 (Codex's reading adopted). | phases.md 3.5 Graphs ("one point per autosave"); config/run.toml autosave_interval | Resolved |
| P3.5-Q-CDX-01 | Codex | yes | Must a completed action stay visible at progress 1, and how is unbounded progress read? | No retained state: progress is checked up to the last working frame (or a detached ActiveAction fixture); the engine clears a finished action as in Phase 2. want/got, minutes, route or current-unit fractions as in the Contract. | src/ai_island/rules/actions/core.py finish_action; phases.md 3.5 ("no world rule changes") | Resolved |
| P3.5-Q-CDX-03 | Codex | yes | May the effective UI scale fall below the chosen one on a small window? | Yes: lowered until the panel fits half the width and the bar an eighth of the height; the choice is kept in prefs and the menu shows the effective scale. | phases.md AC-6 ("fit the window without overlap") | Resolved |
| P3.5-Q-CDX-04 | Codex | no | Where does F12 save without a named run? | Nowhere: a top-bar note asks for a named run. | phases.md 3.5 ("in runs/<run>/screenshots/") | Resolved |
| P3.5-Q-CDX-05 | Codex | no | Village colours/filters: current or historic membership? | Current membership from the frame's village_guide (chats carry no village stamp). | src/ai_island/storage/db.py ChatRow; phases.md 3.5 chat filters | Resolved |
| P3.5-Q-CDX-02 | Codex | yes | Merged into P3.5-Q-CLA-02. | See P3.5-Q-CLA-02. | storage/events.py | Resolved |

## Phase 4: Minds and AI connections
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P4-Q-CLA-01 | Claude, Codex (P4-Q-CDX-01) | yes | AC-3 "layer 1 byte-identical across every call": the guide has the player's name, and day-0 ranking comes before the action list. | Layer 1 is fixed per player and prompt family (player / noticer / advisor) for every call after a separate day-0 ranking bootstrap call; both reply formats live in layer 1. | docs/gameplay.md Opening guide ("only the names change") and Day 0 order; docs/architecture.md Prompt order | Resolved |
| P4-Q-CLA-02 | Claude | yes | Which cap does --max-dollars set? | min(--max-dollars, run.toml spend_cap_usd), pinned in the run's config; LiveRun and the broker use the pinned value; warning at spend_warning_share of it. | phases.md Phase 4 Requirements (spend cap from run.toml; --max-dollars required) | Resolved |
| P4-Q-CLA-03 | Claude, Codex (P4-Q-CDX-03) | yes | Does AC-23's `new` run a game week, and how is the fake adapter chosen? | AI `new` runs ai.new_ticks = 10080 by default (`--ticks` overrides, 0 = create only); no-AI `new` stays create-only; run.toml [ai] backend = "fake" is the only backend in Phase 4. | phases.md AC-23 (literal); CLAUDE.md (no real AI calls by agents) | Resolved |
| P4-Q-CLA-04 | Claude | no | Is thirst an urgent need for the reflex tier? | Yes, level 3 like hunger, cold and fatigue (config [mind] urgent_levels). | docs/design.md Router rules (urgent body need); docs/gameplay.md When players decide | Resolved |
| P4-Q-CLA-05 | Claude, Codex (P4-Q-CDX-04 router part) | yes | What counts as "involves another player" / "surprise" before choosing, and is small talk an exception? | main_interrupts (attacked, hurt, loss_noticed, storm_started, player_in_sight), spoken_to from a player, or a pending offer/promise from a player -> main; a lone 2-hour check and everything else -> fast; fast reply needs_more_thought escalates; small talk the player starts itself is fast; no text-marker classifier. | docs/design.md Router rules 2 and 3 | Resolved |
| P4-Q-CLA-06 | Claude, Codex (P4-Q-CDX-04 mistake part) | yes | How is "worse than expected" measured, and when? | expected_delta = chosen feel_now (slow/hooked) or expected_feel (fast) x 1.0; X change from decision to the action's end or 120 ticks; mistake when expected - actual > 5. | docs/design.md Learning from mistakes; phases.md AC-16 ("configured margin") | Resolved |
| P4-Q-CLA-07 | Claude | no | Where do embeddings live? | runs/<run>/embeddings.sqlite cache keyed by model+text; snapshots keep text only; tests use FakeEmbedder. | Overview.md Constraints (JSON snapshots; tables fixed since Phase 1) | Resolved |
| P4-Q-CLA-08 | Claude | no | Fake adapter cost? | $0 in runs (Tim's review shows $0.00); FakeAdapter(bill=True) only in AC-6/AC-7 tests. | phases.md Phase 4 Notes | Resolved |
| P4-Q-CLA-09 | Claude (from P4-C-CDX-01, Telegram down) | no | Codex picked gemini-3.8-flash (a "Flash" model, cheaper than the others' mains) as Gemini's main model. Is that the "mid-tier" Gemini you want? | Tim: use gemini-3.8-flash for now. | docs/design.md The players ("mid tier"); Codex research.md registry (no Pro option listed) | Resolved |
| P4-Q-CLA-10 | Claude (from P4-C-CDX-03, Telegram down) | no | The xAI helper (grok-4.20-0309-non-reasoning) costs far more than the other helpers. Keep it? | Keep: it is the researched non-reasoning xAI model; helpers are a small share of spend; models.toml can change before the paid steps. | docs/design.md Model rules (helpers from the player's own company); docs/architecture.md Budget (helpers ~$1/week) | Resolved |
| P4-Q-CDX-01 | Codex | yes | Merged into P4-Q-CLA-01. | See P4-Q-CLA-01. | docs/gameplay.md | Resolved |
| P4-Q-CDX-02 | Codex | yes | Is gemini-3.5-flash-lite thinking_level=minimal acceptable as "no extended thinking"? | Yes, as a recorded exception: no current Google cheap model with thinking fully off was found; thought tokens are logged per call. | docs/architecture.md Thinking ("helpers don't use extended thinking"); Codex research.md Questions | Resolved |
| P4-Q-CDX-03 | Codex | yes | Merged into P4-Q-CLA-03. | See P4-Q-CLA-03. | phases.md AC-23 | Resolved |
| P4-Q-CDX-04 | Codex | yes | Mistake timing, small-talk exception, initial idle, invented value priority. | Router and mistakes: see P4-Q-CLA-05/06. Initial idle = one bootstrap "finished" decision. Invented priority = positive raw starting weight added before the floor-lock rescale. | docs/design.md Values system; src/ai_island/rules/turn.py | Resolved |
| P4-Q-CDX-05 | Codex | no | May an unresolved in-flight call pause recovery instead of resending? | No pending-intent rows: replies are stored the moment they arrive and always reused; only a call in flight during a hard crash can be sent again. | docs/architecture.md Saving ("reusing the stored AI replies"); Decisions 8 | Resolved |

## Phase 5: Judge, measurement, calibration and pilot tools
| ID | From | Blocking | Question | Resolution | Basis | Status |
|----|------|----------|----------|------------|-------|--------|
| P5-Q-CLA-01 | Claude, Codex (P5-Q-CDX-04) | yes | Which commands use real AI by default? | Profiles (pilot, launch), calibrate and judge-check are live by default; ordinary `new --ai-seats` stays practice (fake) unless `--backend live`; `--backend fake` / `--dry-run` force the fake adapter; every live path needs a typed "yes"; tests set AI_ISLAND_OFFLINE=1. | phases.md Phase 5 Notes (Tim's exact commands); CLAUDE.md "No real AI calls" | Resolved |
| P5-Q-CLA-02 | Claude | yes | Where are daily summaries, profiles and flags stored, given the fixed tables? | Summaries and profiles are the judge's ai_calls rows (details carry kind, period, subject); flags are derived on read from events and labels; labels in judge_labels. No new tables or events. | Overview.md Constraints (tables fixed since Phase 1); Decisions 3 | Resolved |
| P5-Q-CLA-03 | Claude | no | Unhooked "against" share: slow only, or slow + fast? | Slow only; fast is excluded (different model). | docs/design.md Measures ("both made by the same main model") | Resolved |
| P5-Q-CLA-04 | Claude | no | Anthropic reports no thinking tokens. | Read usage.output_tokens_details.thinking_tokens (present in the installed SDK); absent -> None, reported as unavailable, never treated as a match. | Codex plan compatibility (anthropic types/usage.py); Decisions 15 | Resolved |
| P5-Q-CLA-05 | Claude | no | Decisions per game day for the cost model? | Per player per day: 14 slow, 6 hooked, 20 fast, 2 flagged fast; in models.toml [calibration]. | docs/architecture.md Budget (about 20 main decisions a day); Decisions 30 | Resolved |
| P5-Q-CLA-06 | Claude, Codex (P5-Q-CDX-02) | yes | Tuning targets and proposal rules? | The C9 catalogue: food short days 8-21 (min 21 days), week-1 median X 60-80 (paired food/achievement weights), loyalty 40-80, checks 0-8 per player-day, main decisions 0-20 per player-day (trigger removal only with interrupt evidence); in balance.toml [analysis]. | handoffs/phase-2.md AC-29 targets; docs/architecture.md Budget; docs/design.md Open questions (loyalty start 70, leave below 30) | Resolved |
| P5-Q-CLA-07 | Claude | no | Live run while Ollama is not running? | Refuse before any call with one plain sentence naming `ollama pull nomic-embed-text`. | docs/setup.md 2.8 | Resolved |
| P5-Q-CLA-08 | Claude | no | `calibrate --dry-run --apply`? | Refused (exit 2): pretend numbers never go into models.toml. | phases.md Requirements (--apply writes measured settings) | Resolved |
| P5-Q-CDX-01 | Codex | yes | What is "roughly matched" thinking, and what if no match is possible? | max/min of the per-model median thinking tokens <= 1.25, up to 3 search rounds, same setting for slow and hooked; missing or zero counts -> unmatched, no apply. | docs/architecture.md Thinking (calibration adjusts until roughly the same); Decisions 29 | Resolved |
| P5-Q-CDX-02 | Codex | yes | Merged into P5-Q-CLA-06. | See P5-Q-CLA-06. | handoffs/phase-2.md | Resolved |
| P5-Q-CDX-03 | Codex | yes | Value changes "linked to events": perceived memory items or events.id? | The player's memory items (id, tick, kind, text) stored at reflection time; never joined to events.id. | handoffs/phase-4.md Summary (cause ids are memory items); Decisions 18 | Resolved |
| P5-Q-CDX-04 | Codex | no | Merged into P5-Q-CLA-01. | See P5-Q-CLA-01. | phases.md Phase 5 Notes | Resolved |
| P5-Q-CDX-05 | Codex | no | Can labels be revised when an outcome later becomes a mistake? | Yes: an appended full revision; the latest label counts in measures. | docs/design.md Judge (flagged choice points include mistakes); Decisions 5 | Resolved |
