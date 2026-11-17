# AI Island — Build Phases

How AI Island gets built: six phases plus a short Phase 1.5, run by the two-manager system in this repo (Codex plans each phase alongside Claude; Claude builds it with its coder, tester and debugger). Setup comes first (see AI Island — Setup). Companion to the Design Document, Gameplay and Architecture docs; if a conflict ever turns up, fix the older statement.

`phases.md` in the repo root turns each checklist below into a phase spec with numbered acceptance criteria. That file is what the managers plan from; this one keeps the full checklists and the reasoning behind them.

## Overview

| Phase | Builds | Spends money? |
| --- | --- | --- |
| Setup (by hand) | Accounts, keys, installs, this repo, docs, assets | No |
| 1 Skeleton and the island | Project skeleton, basic storage, the island with no players, a map viewer | No |
| 1.5 Colour and time-true movement | The map in colour (Kenney colour sheet, Tiny Creatures animals), movement and daylight that follow the clock | No |
| 2 Bodies, villagers, actions and senses | The whole game, played by rule-based and scripted players | No |
| 3 Observer screen, run control and exports | The full observer screen, pause, autosave, crash recovery, CSV export, watched with rule-based players | No |
| 4 Minds and AI connections | AI players (router, tiers including the hooked tier, memory, values, reflection), choice points, spend cap, tested with the fake adapter | No |
| 5 Judge, measurement, calibration and pilot tools | Judge, summaries, the remaining measures, the calibration command, pilot profile, analysis report, launch check | Only the first paid steps Tim runs afterwards: calibration, a judge check, an optional test week and the pilot |
| 6 Tuning and launch | Config tuned from the pilot; launch check passing | The real run, which Tim starts |

No agent ever makes a real AI call. Each paid step is a command Tim runs himself, with a `--max-dollars` limit. Everything free is built first, so Tim can watch the whole game with rule-based players after Phase 3 and decide whether it's worth paying for the AIs before any money is spent.

## How every phase runs

1. Tim runs `.\scripts\start-phase.ps1 -Phase N` in the repo folder. Two tabs open: Claude and Codex.
2. Each manager writes its own plan for the phase from `phases.md`, `Overview.md` and these docs, without seeing the other's. Codex's researcher proposes ideas (it can search the web); its reviewer checks them against the code.
3. Claude asks Codex questions about its plan on Telegram (if set up), merges the two plans into `handoffs/phase-N.md` and lists every open question in `Questions.md`.
4. Tim reads the short "For Tim" summary and replies `go` (or asks for changes).
5. Claude runs up to four rounds: the coder builds, the tester writes and runs tests from the acceptance criteria, the debugger finds the cause of any failure, the coder fixes it. Claude commits after each step and tags `phase-N-start` and `phase-N-done`.
6. If the session stops, `.\scripts\start-phase.ps1 -Phase N -Continue` picks it up from the handoff file.
7. Tim does the review under "Done when". Between phases, `/review` in the Claude tab checks finished phases against the docs.

Every phase keeps the earlier phases working: their tests keep passing, and the determinism test (same seed, same event log) runs at the end of every phase.

## Decisions this plan rests on

These close the questions the other docs left open.

**When players decide**

- Every action has a duration in game minutes, set in config. Work and rest actions take an amount or an end point (gather 20 wood, rest until morning), so one decision covers a stretch of time.
- A player is asked for a decision only when:
  1. its current action finishes,
  2. someone speaks to it,
  3. something interrupts it: it's attacked or hurt, another player or a wild dog comes into sight, a storm starts, it notices a loss (stolen goods, a missing villager), or its feeling band changes,
  4. or 2 game hours pass awake without a decision (a fast-tier check, so nobody stands still for long).
- Urgent body needs are handled by the reflex tier in code, with no model call.
- The router then picks the tier for that decision: reflex for urgent body needs, the main model for big choices (with its Noticer and Advisor when unhooked, alone with a few recent memories when hooked), and the fast tier for everything else. Most ticks need no AI call at all, which keeps cost in line with the budget estimate of about 20 slow decisions per player per game day.

**Season length**

- Seasons last **2 game weeks**, so a game year is 8 game weeks: spring weeks 1–2, summer 3–4, autumn 5–6, winter 7–8.
- The $100 budget buys about 6–8 game weeks, so the run reaches winter, which is where food stores, shelter and trust matter most. Home plots run short around week 2–3, in summer, so contest over the centre starts well before winter.
- Season length stays in world.toml. The calibration report (Tim runs it after Phase 5) confirms the run reaches winter with measured costs; if the budget turns out to allow far more weeks, Tim can lengthen seasons before launch.

**Starting numbers (X formula and villager loyalty)**

- Phase 2 proposes every number in balance.toml, each with a one-line reason, aimed at these targets with dummy players:
  - X mostly 60–79 in week 1
  - home resources running short around week 2–3
  - X dropping below 40 in winter for players without food stores
  - villagers leaving only after several days of hunger or hard work
- Proposed starting points: adaptation half-life 2 game days, villager loyalty starting at 70, villagers leave below 30.
- Phase 6 tunes them from the pilot.

**Paid steps are Tim's**

- The build system's agents can't be trusted to spend money unattended, and a pilot runs for hours. So every phase is built and tested with the fake adapter, and each paid step (calibration, judge check, one-week test, pilot, real run) is a command Tim runs after the phase, with a dollar limit. All of them come after Phase 5, except the real run after Phase 6. This is why the pilot tools (5) and Tuning and launch (6) are separate phases.

**Hooked players**

- A hooked player (X below 40 or high pain) still makes its big decisions with its own main model, at the same thinking setting, but with less help and less information: no Noticer, no Advisor, and only a few recent memories (the number is in balance.toml). Routine decisions go to the fast tier, hooked or not.
- Every slow and hooked decision becomes a choice point, and so does any fast-tier decision that harms someone, makes or breaks a promise, or goes against the player's own values by its own label. So hooked and unhooked choices are made by the same model and can be compared.

---

## Phase 1 — Skeleton and the island

**Goal:** the full code skeleton plus a living island with no players that runs for a game year, deterministically, with and without a window.

**Project skeleton**

- [ ] uv project (pyproject.toml, Python 3.13, pinned versions), with ruff and pytest configured
- [ ] The full folder layout from the Architecture doc, with empty packages for later phases
- [ ] Config loading: world.toml, balance.toml, models.toml, run.toml, each checked by a Pydantic model on load, so a typo fails at start, not mid-run
- [ ] Seeded random streams, one per subsystem (weather, animals, combat and so on), so adding a feature in a later phase doesn't shift every other random number
- [ ] main.py commands: `new`, `resume`, `headless --ticks N`, `view`
- [ ] Confirm every library installs on the Dell XPS, including pygame_gui with pygame-ce

**Storage (basic)**

- [ ] One SQLite database per run in `runs/<name>/run.db`, with **every table from the Architecture doc created now** (events, ai_calls, choice_points, judge_labels, chats, value_history, spend, snapshots), so later phases add rows, not migrations
- [ ] Append-only event log with typed event records
- [ ] Snapshot save and load of the full world state and random stream positions

**World**

- [ ] Tick loop: 1 tick = 1 game minute. Headless runs as fast as possible; live mode paces to 0.36 seconds per tick, scaled by the speed setting
- [ ] Clock: days, day and night, 4 seasons of 2 game weeks each (from config)
- [ ] Map generated from the seed, 80 × 80: one home plot designed once and rotated into the four corners; buffer land; the contested centre with a large forest, the quarry, the best farmland and the lake; the three landmarks (quarry, lake dock, great tree); the unclaimed-land pool
- [ ] A* pathfinding with terrain costs
- [ ] Weather by season odds: rain, storms, drought. Effects are exposed as flags that later phases read (stops outdoor work, puts out campfires, cuts water)
- [ ] Resources: trees regrow slowly and can be over-cut; stone is finite; water is seasonal and drops in drought; farmland soil states, with crop growth that fits inside 2-week seasons
- [ ] Plants: berries, mushrooms, roots, herbs, healing herbs, the mild and the strong poison, each with seasons and regrowth
- [ ] Animals: rabbits, deer, boar, fish, birds and nests, goats, chickens. Populations breed by season, move, flee and can die out locally
- [ ] Wild dogs: packs of 2–4 in the buffer and centre forests, more active at night and in winter, slow breeding (attacks come in Phase 2)

**Assets and map viewer**

- [ ] Asset mapping file pointing every item on the Gameplay asset list to a Kenney tile, with missing items listed and drawn in code
- [ ] Loader: Kenney tiles cut from the sheet and drawn black on white at whole-number scale, never stretched; code drawings on the same 16 × 16 grid (Phase 1.5 switches to colour)
- [ ] `main.py view`: a read-only pygame-ce window showing the map, plants, animals, dogs, weather and night overlays, with the clock in the title bar, sharp under Windows display scaling. No tabs yet

**Tests**

- [ ] Same seed → identical event log over a full game year (run twice, compare)
- [ ] Map: plots identical after rotation, every landmark reachable, centre richer than the plots
- [ ] Seasons, weather odds, regrowth, over-cutting, local extinction, snapshot round trip

**Done when (Tim reviews)**

- A headless game year finishes in a few minutes, and the determinism test passes
- `main.py view` shows the island changing through seasons and weather, with every sprite in place
- **Cost:** $0

---

## Phase 1.5 — Colour and time-true movement

**Goal:** a short phase between 1 and 2. The map in colour, the animals drawn from Tiny Creatures, and movement and daylight that follow the game clock.

**Why:** at speed ×1 the clock moves every 0.36 s, but each animal kind was checked only every 90–180 game minutes, all animals of a kind jumped on the same tick, sprites snapped from tile to tile and night switched on at once.

**Movement**

- [ ] Every moving kind has a speed in game minutes per tile, wander bouts and rests (balance.toml, each with a reason)
- [ ] Each animal and dog moves on its own staggered timer; the step in progress is saved in snapshots
- [ ] One movement module that Phase 2 reuses for players and villagers
- [ ] The viewer draws moving sprites sliding between tiles, in whole pixels; frame pacing accounts for drawing time

**Colour**

- [ ] Kenney's colour sheet (same layout as the black-and-white one) for everything except the animals
- [ ] Tiny Creatures for every animal it has a good match for; anything neither pack has is drawn in code
- [ ] Ground colours per terrain, four player colours, colours for code drawings; a `mono` switch keeps the old look
- [ ] Daylight that fades through dawn and dusk; autumn colours, winter snow, drought-yellowed grass

**Tests**

- [ ] No lockstep jumps; speeds match config; dogs still busier at night and in winter
- [ ] Snapshot round trip mid-step, determinism, a full year under 5 minutes
- [ ] Every asset-list item mapped; colour and mono screenshots; light by hour; all Phase 1 tests

**Done when (Tim reviews)**

- At ×1, animals amble on their own timing and slide between tiles, and the light fades at dusk
- The animals are Tiny Creatures sprites, and `palette = "mono"` still shows the old look
- **Cost:** $0

---

## Phase 2 — Bodies, villagers, actions and senses

**Goal:** the complete game, played by rule-based and scripted players. Everything except the AI minds.

**Bodies and wellbeing**

- [ ] Needs: hunger, thirst, cold, rest; sickness (mild and strong poison, raw or spoiled meat); injury
- [ ] The X formula from the Design Document: a concave f per input, weights from balance.toml, adaptation B with a half-life
- [ ] Starting numbers proposed in balance.toml with a reason each, aimed at the targets under "Decisions this plan rests on"
- [ ] Feeling bands as words, speed and work multipliers per band, the hooked flag (X below 40 or high pain)
- [ ] Trust and anger scores toward every other player, fading over time
- [ ] Death and respawn: back home, carried items dropped, −10 X

**Villagers**

- [ ] 3 per player at start, a wanderer pool, an island cap of 50, no births
- [ ] Needs, health, loyalty (fed, safe, not overworked) and bonds with every player, separate from loyalty
- [ ] Jobs (gather, farm, guard, build, tend animals) and work levels (light, normal, hard)
- [ ] Leaving, joining another player, wandering off, death, and grief scaled by bond
- [ ] Short scripted lines, and gossip only about players and only about what they saw or heard

**Actions (the full Gameplay list)**

- [ ] Every action has a duration in game minutes from config, and work and rest actions take an amount or an end point
- [ ] Interrupt events (spoken to, attacked or hurt, a player or dog comes into sight, a storm starts, a loss noticed, a feeling band changes) are raised by the rules, ready for Phase 4's decision triggers
- [ ] Body: eat, drink, rest. Work: move, gather, farm, fish, hunt (odds by tool and animal, boar injuries), build, store, craft, make fire, cook, tame
- [ ] Tools: basic and better recipes, half speed by hand, pickaxe required at the quarry, wear, repair, dropping, stealing and trading
- [ ] Fire: campfire and hearth, 6 hours of fuel, cooking, warmth, light, scaring dogs, put out by rain (campfires only)
- [ ] Buildings: house, field, storehouse, workshop, pen, granary, bridge, monument, shrine; storm damage and repair
- [ ] Care: use herb, assign villager. Social: talk, trade (barter, both sides agree), gift, promise (recorded, so keeping or breaking it can be checked), ally, recruit, teach (a knowledge-book entry at lower confidence for the listener; lies use the same action)
- [ ] Protect: guard. Harm: steal, sabotage, attack, chase off or claim land with boundary stakes, pull stakes, capture or poach villagers
- [ ] Belief: pray, ceremony, shrine, offering. Logged, with no mechanical effect
- [ ] Wild dogs now attack lone villagers, penned animals and unarmed players
- [ ] Simultaneous resolution: clashes settled by the seeded generator, player order rotated every tick

**Tasks, land and landmarks**

- [ ] Five stages, hidden per player, with unlocks and rewards (stage 1 gives a set of basic tools)
- [ ] The cooperative bonus for joint projects and the dominance bonus for holding a landmark for a week
- [ ] Land claims with border patterns, and the landmark-holding rule

**Senses and talk (the Discoverer)**

- [ ] Sight about 7 tiles (less at night and in storms), hearing about 5, body feelings as words, memory of place that can go out of date
- [ ] Sense reports as short text from varied templates
- [ ] Witness records: a victim learns who did it only if it saw or heard it, or someone tells it
- [ ] Chat phase: talk only to someone in sight, overheard within hearing range
- [ ] Knowledge book data model (entries with confidence), used by teach now and by the minds in Phase 4

**Test players**

- [ ] Four rule-based dummy players that only follow their needs
- [ ] Scripted players that use every action at least once

**Tests**

- [ ] Every action on a small example map, every sense range, X calculations, interrupt events, villager loyalty edge cases
- [ ] The determinism test now includes players

**Done when (Tim reviews)**

- Dummy players survive, run short of home resources around game week 2–3, and struggle in winter (weeks 7–8)
- Scripted players trade, steal, claim land, fight dogs and finish all five task stages
- The map viewer shows players and villagers moving (with the Phase 1.5 movement module), each in its player's colour
- **Cost:** $0

---

## Phase 3 — Observer screen, run control and exports

**Goal:** the full observer window and run control before any AI exists. Tim watches four rule-based players in every tab, pauses, closes and restarts, and exports the logs, so he sees what the game gives him before paying for anything.

**Observer screen (observer/)**

- [ ] pygame_gui tabs: Chats (with who was in earshot), Choice points (both labels; empty until Phase 4), World history, Players (feeling, X, hooked flag, values when a player has them, trust and anger grid), Spend ($0.00 until real AI calls)
- [ ] Top bar: clock, day and season, pause and resume button, speed control, spend warning, autosave indicator
- [ ] Map additions: land borders, state markers (sick, injured, sleeping, grave), buildings and their damaged versions
- [ ] 30 frames per second, separate from ticks, and read-only except for pause, resume and speed

**Run control (storage/)**

- [ ] Pause (button or P): the world stops after the current tick and a snapshot is saved
- [ ] Autosave every 6 game hours; resume across days with the same log and spend counter
- [ ] Crash recovery: load the last autosave and replay, so the log matches an uninterrupted run (Phase 4 makes it reuse stored AI replies)
- [ ] Keep Windows awake while a run is active

**Measurement without AI (measure/)**

- [ ] Per game week: promises made vs. kept, help vs. harm actions and toward whom, villager welfare (deaths, departures, average loyalty), belief actions
- [ ] CSV export of every table, ready for R

**Tests**

- [ ] Every tab and top bar element with a dummy video driver; the observer changes nothing but pause, resume and speed
- [ ] Pause, resume and crash recovery give the same result as an uninterrupted run

**Done when (Tim reviews)**

- Tim watches a rule-based run in the full observer, pauses and resumes, closes it mid-run and restarts without losing anything, and opens the CSV exports
- **Cost:** $0

---

## Phase 4 — Minds and AI connections

**Goal:** the AI players' minds and the connections to every company, built and tested with the fake adapter only.

**AI connections (llm/)**

- [ ] One interface for every role, with an adapter each for Anthropic, OpenAI, Google, xAI (openai SDK at xAI's endpoint) and Mistral, plus Ollama embeddings and the fake adapter
- [ ] Pydantic schemas for the player reply types (action, self-label, weekly reflection, invented value), sent through each company's structured-output mode; every action reply, fast tier included, carries a short self-label
- [ ] Three-layer prompts for caching (fixed, slow-changing, per call), with Anthropic's cache markers
- [ ] Retry rules: format error → 1 retry, then rest. Refusal → no retry, rest, logged. Network error or rate limit → 3 retries, then auto-pause
- [ ] Every call recorded: prompt, reply, model version, tokens (thinking, input, output, cached), cost and time taken
- [ ] Spend counter using prices from models.toml; spend cap with a warning at 80% and an auto-pause before any call that would pass it; any run with an AI seat needs `--max-dollars`
- [ ] Calls for different players run at the same time, and the clock waits for all of them

**Minds (minds/)**

- [ ] Decision triggers as decided above: action finished, spoken to, an interrupt event, or 2 game hours awake without a decision
- [ ] Router with the three rules; reflex tier (code); fast tier (rules plus the cheap model, hooked or not); slow tier for unhooked main-model decisions (Noticer → Advisor → main model, full memory search); hooked tier for hooked main-model decisions (the same main model at the same thinking setting, alone, with only a few recent memories)
- [ ] Opening guide and day-0 order from the Gameplay doc, with players' human names and no hints about models
- [ ] Day-0 value ranking: all 14 values, weights summing to 100, core values 10–25%, background values at least 1%, checked and repaired by code
- [ ] Slow and hooked decisions follow the 4-step weighing and end with a self-label; acting against one's own values is logged, never blocked
- [ ] Memory: identity, value table, relationships, knowledge book, memory stream picked by recency, importance and relevance (embeddings), rolling summary
- [ ] The Advisor reads the main model's past decisions
- [ ] Mistake flags when an outcome was clearly worse than expected
- [ ] Weekly reflection: at most ±10 per value, rescaling with a 1% floor, the core recomputed, at most one invented value checked by code, the rolling summary rewritten

**Choice points and run control with AI**

- [ ] Choice point records with every field from the Design Document, including the tier: every slow and hooked decision, plus any fast-tier decision that harms someone, makes or breaks a promise, or self-labels as against its values
- [ ] Pause lets a reply in progress finish first; crash recovery reuses stored AI replies, so no call is paid for twice; a call that fails because the laptop slept pauses the run
- [ ] The observer shows value tables, choice points with self-labels and tier, and live spend

**Model choice**

- [ ] Research current models and prices for all nine roles (four main models, four helpers, the Mistral judge; no Chinese-developed models). Confirm structured outputs, caching and the thinking setting for each, and pick a Grok model that accepts the thinking setting. (Codex's researcher does this: it has web search.) Results go into models.toml

**Tests**

- [ ] Schema tests with good and bad replies for every type; decision triggers; router rules, including that a hooked decision calls only the main model with the short memory; choice point creation per tier; value constraints and rescaling; invented-value rejection cases; spend cap; a full game week with the fake adapter

**Done when (Tim reviews)**

- A fake-adapter run can be watched in the observer, and `main.py decisions` prints a player's decisions in plain text
- **Cost:** $0

---

## Phase 5 — Judge, measurement, calibration and pilot tools

**Goal:** everything left before money is spent. After this phase Tim makes the first paid runs himself: calibration, a judge check, an optional one-week test and the pilot.

**Judge and measurement (measure/)**

- [ ] Mistral judge, blind (human names only) and neutral: full labels for flagged choice points, short ones for routine ones, labelled live and shown in the observer
- [ ] Daily world summary, weekly player profiles, flags for betrayals, deaths and new beliefs
- [ ] The remaining measures from the Design Document per game week: stated vs. revealed values, hooked vs. unhooked "against" shares, following the Advisor, superstition events and invented beliefs, value weights linked to their causes
- [ ] Judge check command (`main.py judge-check --max-dollars N`) for a few real judge calls

**Calibration**

- [ ] Calibration command (`main.py calibrate --max-dollars N`): the same sample slow and hooked decisions on all four main models; compare thinking tokens and adjust the settings until they roughly match
- [ ] It measures the cost per slow decision, per hooked decision and per game week, and `--apply` fills in models.toml
- [ ] Calibration report: chosen versions, thinking settings, measured cost per game week, game weeks per $100, confirmation that the run reaches winter (week 7), and estimates for a one-seat test week and for the pilot

**Pilot and launch tools**

- [ ] Pilot profile: all four seats on their own companies' cheap models for 2–3 game weeks, with a `--max-dollars` limit
- [ ] Analysis command for the pilot's logs: deaths, X over time, when resources run short, decisions per player per game day by trigger and by tier, refusals, schema failures, cost per game week
- [ ] Tuning proposals with evidence (scarcity, X weights, villager loyalty, decision triggers, slow-thinking triggers), written into the analysis report
- [ ] Launch check: config frozen and committed, spend cap set, seed recorded
- [ ] Launch profile with the four main models

**Done when (Tim reviews)**

- The tools pass their tests with the fake adapter
- Then Tim runs, one at a time: the calibration (and approves the report), a few judge calls, optionally one AI player for a game week, and the pilot with its analysis
- **Cost:** the first real money: calibration (about $5), judge check (cents), the optional test week and the pilot (the calibration report estimates both), each run by Tim's commands with a dollar limit

---

## Phase 6 — Tuning and launch

**Goal:** a tuned world and the real run started.

- [ ] Tuning proposals from the pilot → Tim approves → config changes, each with its evidence
- [ ] Balance targets re-checked with dummy players
- [ ] Model versions, thinking settings and measured costs (from the calibration and the pilot) written into the Design Document
- [ ] Launch check passes: config frozen and committed, spend cap set, seed recorded
- [ ] Tim starts the real run with the four main models

**Done when:** the pilot finished under budget with no crashes, the launch check passes, and the real run is running.
**Cost:** the run itself.
