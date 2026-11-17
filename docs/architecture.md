# AI Island — Architecture

Last updated: Nov 1, 2026 (repo copy: folder layout and phase plan adapted to the two-manager build system)

How the code is organized and how a run works, from one tick of the world to saving and resuming. Companion to the Design Document (what the game is), Gameplay (the detailed rules), Build Phases (the build plan) and Setup. All these files agree; if a conflict ever turns up, fix the older statement rather than working around it.

## Decisions this rests on

| Area | Decision |
| --- | --- |
| Computer | Tim's Dell XPS: Intel Core Ultra X7 358H, 32 GB RAM, Intel Arc B390 graphics, 64-bit Windows |
| Main models | Mid-tier Claude, GPT, Gemini and Grok, thinking set to medium and calibrated (a command Tim runs after Phase 5) so all four think roughly the same amount |
| Hooked players | Their big decisions are still made by their own main model, at the same thinking setting, but alone: no Noticer, no Advisor and only a few recent memories |
| Helpers (Noticer, Advisor, fast tier) | Each player's helpers use its own company's cheap cloud model |
| Judge | A Mistral model in the cloud, blind to which company is behind each player |
| Local models | Ollama runs one small embedding model for memory search, nothing else |
| Observer screen | pygame-ce, with pygame_gui for the scrolling text tabs |
| Pausing | Pause at any moment; a reply already in progress finishes first; autosave every 6 game hours |
| Run | One open-ended run, continued across days until Tim ends it or the $100 cap is reached |
| Seasons | 2 game weeks each, so a game year is 8 game weeks and winter falls in weeks 7–8 |
| When players decide | Only when an action ends, someone speaks to them, something interrupts them, or 2 game hours pass awake without a decision |
| Build | Six phases with the two-manager system (Claude Code builds, Codex plans alongside), following `phases.md`, after the manual Setup. Everything free comes first (island, game rules, full observer and saving, Phases 1–3); the AI minds come after (Phases 4–5); no money is spent before the end of Phase 5 |

## The core idea: a turn-based world with a window on top

The program works like a board game played in turns, not like an action game.

- The world advances in **ticks**. One tick is one game minute.
- During a tick, the world updates, every player perceives, players that need a decision make one, actions resolve and everything is logged. Most ticks need no AI call, because actions last many minutes.
- **Any AI call stops the clock.** The world simply waits for the reply, so a slow model or a slow internet connection never changes what happens.
- The pygame window only **shows** the current state. It never drives timing. The same world can run with no window at all, for tests.
- Every random event (weather, hunting odds, combat) comes from a numbered **seed**, so a run can be reproduced and debugged.

At full speed, one tick takes about 0.36 seconds of running time, so a game day is about 8.6 minutes and a game week is about one hour. Time spent waiting for AI replies or paused is not counted. Headless runs with rule-based players skip the pacing and run as fast as the computer allows.

```
            ┌──────────────────────────── one tick ────────────────────────────┐
            │                                                                   │
 world/ ──▶ 1. Update world ──▶ 2. Senses (Discoverer) ──▶ 3. Who decides?      │
            │                                              Router picks tier    │
            │                     ┌─────────────────────────┤                   │
            │                     ▼                         ▼                   │
            │              Reflex / fast tier        Main model (clock stops)   │
            │              (code + cheap helper)     slow: helpers, then main   │
            │                                        hooked: main alone         │
            │                     └────────────┬────────────┘                   │
            │                                  ▼                                │
            │           4. Validate replies ──▶ 5. Resolve actions together     │
            │                                  ▼                                │
            │                    6. Chat phase ──▶ 7. Log events to SQLite      │
            └───────────────────────────────────────────────────────────────────┘
                     │                                         │
                     ▼                                         ▼
            observer/ draws the map                 measure/ sends choice points
            and tabs (30 frames/s)                  to the judge
```

## The tick, step by step

1. **Update the world.** Weather, plant growth, animal movement and breeding, fires burning down, villagers' needs and jobs, spoilage, tool wear, and progress on every action in progress.
2. **Build sense reports.** The Discoverer (plain code) works out what each player can see (about 7 tiles), hear (about 5 tiles) and feel, and turns it into short text. Players only ever learn about the world through this step.
3. **Decide who needs a decision, and how.** Every action lasts a set number of game minutes, and work and rest actions take an amount or an end point (gather 20 wood, rest until morning). A player is asked for a decision only when:
   - its current action finishes,
   - someone speaks to it,
   - an interrupt happens: it's attacked or hurt, another player or a wild dog comes into sight, a storm starts, it notices a loss, or its feeling band changes,
   - or 2 game hours pass while it's awake without a decision (a fast-tier check).

   Everyone else carries on with its current action. For each player that decides, the router applies the three router rules from the Design Document: reflex (code), fast (rules plus the player's cheap helper model), or the main model. A main-model decision uses the slow tier when the player is unhooked (Noticer, Advisor, then the main model, with the full memory search) and the hooked tier when it is hooked (the main model alone, with only a few recent memories).
4. **Ask the AIs.** Calls for different players run at the same time to save waiting, and the clock stays stopped until all of them return. Every reply is checked against its schema.
5. **Resolve actions together.** All actions in a tick count as simultaneous. When two clash (both take the last fish), the seeded random generator decides, and the order of players is rotated every tick so nobody always goes first.
6. **Chat phase.** Players and villagers who can see each other may speak. Anyone within hearing range receives the words in their next sense report. Being spoken to triggers a decision for the listener.
7. **Log everything.** Each change is written to the event log. Each slow or hooked decision becomes a choice point record for the judge, and so does any fast-tier decision that harms someone, makes or breaks a promise, or goes against the player's own values by its own label.

The weekly reflection runs at the end of each game week, after the last tick of the week.

## Folder layout

The repo root also holds the two-manager build system (`.claude/`, `.agents/`, `.codex/`, `managers/`, `handoffs/`, `reviews/`, `logs/`, `scripts/`, `Overview.md`, `phases.md`, `Questions.md`). The game itself:

```
src/ai_island/      the game's Python package, installed by `uv sync`
  world/            map generation, clock, seasons, weather, resources, plants,
                    animals, wild dogs, villagers                  (no pygame, no AI)
  rules/            action list and their effects and durations, interrupt events,
                    tasks and rewards, tools, fire, land and landmarks, the X
                    formula, the Discoverer (senses)               (no pygame, no AI)
  minds/            decision triggers, router, reflex and fast tiers, slow tier,
                    prompts, memory, values, knowledge book, weekly reflection,
                    rule-based and scripted test players
  llm/              one adapter per company (Anthropic, OpenAI, Google, xAI,
                    Mistral) plus Ollama embeddings and the fake adapter; prices
                    and spend tracking
  measure/          choice point records, judge, daily and weekly summaries,
                    per-week measures, CSV export, pilot analysis
  observer/         the pygame window: map, tabs, pause button, asset loader
  storage/          SQLite database, snapshots, autosave, crash recovery
  cli.py            the commands main.py exposes
main.py             starts a run, resumes a run, runs headless, opens the map viewer,
                    and the other commands (calibrate, export, analyze, launch-check)
config/             every tunable number, in plain text files (plus assets.toml)
tests/              automatic checks
assets/             art packs and font, unchanged
docs/               this specification
runs/               one folder per run: database, logs, saves, reports (not committed)
```

Rule for the folders: **world/** and **rules/** never import pygame or call an AI. That keeps the island testable on its own and lets Phases 1–3 be built, watched and checked without any AI at all.

## What each part does

| Part | Job | Talks to |
| --- | --- | --- |
| world/ | Holds the island's state and updates it each tick | rules/, storage/ |
| rules/ | Decides what an action does, how long it lasts, what interrupts it and what each player perceives | world/, minds/ |
| minds/ | Decides when a player must choose, then turns its sense report into an action using the right tier | rules/, llm/, storage/ |
| llm/ | Sends prompts to the right company, checks replies, counts cost | minds/, measure/ |
| measure/ | Builds choice points, asks the judge, writes summaries and exports | llm/, storage/ |
| storage/ | Saves events, snapshots and spend; restores a run | everything |
| observer/ | Draws the island and the tabs; pause, resume and speed controls | reads world/ and storage/ |

## The map

- **Generated by code from the seed**, not drawn by hand. One home plot is designed, then rotated into the other three corners, so the four plots are exactly identical.
- 80 × 80 tiles, with buffer land, the contested centre, the three landmarks and the pool of unclaimed land as described in the Design Document and Gameplay.
- Walking routes use A* pathfinding over the tile grid.

## AI calls (llm/)

**One interface for every model.** The rest of the code asks for "this player's main model" or "this player's Advisor" and gets back a checked Pydantic object, plus the tokens and dollars it cost. Only llm/ knows about companies.

| Company | Roles | Library |
| --- | --- | --- |
| Anthropic | Player 1 main and helpers | Official anthropic SDK |
| OpenAI | Player 2 main and helpers | Official openai SDK |
| Google | Player 3 main and helpers | Official google-genai SDK |
| xAI | Player 4 main and helpers | openai SDK pointed at xAI's OpenAI-compatible API |
| Mistral | Judge | Official mistralai SDK |
| Ollama (local) | Embeddings for memory search | ollama Python library |

**Reliable replies.** Every reply type (action, choice-point label, weekly reflection, invented value, judge label) has a Pydantic schema. Each company's native structured-output mode is used, and Pydantic still checks every reply before anything happens in the world.

**Prompt order, for caching.** Each prompt is built in three layers, from least to most changing:

1. Fixed for the whole run: the opening guide, value library, action list and reply format.
2. Changes slowly: identity, current value weights, relationship scores, knowledge book summary.
3. Changes every call: this tick's sense report and the question.

Repeated beginnings are cached and billed at a large discount. Anthropic needs explicit cache markers; the other companies cache matching beginnings automatically or with a setting. Phase 4 confirms each one.

**Thinking.** Main models think at medium. Each company names and measures this differently, so models.toml holds the exact setting per model, and the calibration (after Phase 5) adjusts them until the four use roughly the same number of thinking tokens. Hooked decisions use the same setting as slow ones. Helpers and the judge don't use extended thinking.

**When something goes wrong**

| Problem | What happens |
| --- | --- |
| Network error or rate limit | Retry up to 3 times with growing waits; if it still fails, the run pauses automatically and the observer shows why |
| Reply doesn't match the schema | Retry once; if still invalid, the player rests that turn and the failure is logged as data |
| Model refuses or breaks character | No retry; the player rests that turn and the refusal is logged as data |
| Spend reaches 80% of the cap | Warning in the observer |
| Spend would pass the cap | The run pauses before the call is sent |

Pausing on a lasting outage, instead of switching to a different model, keeps every decision coming from the right company.

**Everything is recorded.** For every call: the full prompt, the full reply, the model version, thinking tokens, input and output tokens, cache hits, cost and time taken.

## Memory (minds/)

Each player has:

- **Identity:** name, villagers, home, and who it has become (updated in weekly reflection).
- **Value table:** all 14 values with weights, plus any invented values.
- **Relationship scores:** trust and anger toward every other player, and bonds with villagers.
- **Knowledge book:** discoveries with confidence levels.
- **Memory stream:** every event the player perceived, each with a time and an importance score. Before a slow decision, the most useful memories are picked by how recent, how important and how relevant they are. Relevance comes from the local embedding model, which runs on the processor. Before a hooked decision there is no search: the player gets only its few most recent memories (the number is in balance.toml).
- **Rolling summary:** a short running account of the player's life, rewritten in each weekly reflection, so prompts stay short however long the run gets.

## Saving, pausing and resuming (storage/)

- **One SQLite database per run**, in runs/<run name>/run.db. Main tables: events, ai_calls, choice_points, judge_labels, chats, value_history, spend, snapshots. All of them are created in Phase 1, so later phases add rows rather than migrations.
- **The event log is append-only.** Nothing is ever overwritten, so the full history is always there for the judge, the observer and analysis in R.
- **Snapshots** hold the complete state: the world, every player's memory, the random generators' positions and the spend counter. They are stored as JSON (compression allowed), not pickle, so saves stay readable after code changes.
- **Autosave** takes a snapshot every 6 game hours (about 2 minutes of running time).
- **Pause** (button or the P key): if a reply is on its way, it finishes and its action is applied; then the world stops and a snapshot is saved. Nothing is paid for twice and no decision is lost.
- **Resume** loads the latest snapshot and carries on with the same log and the same spend counter, across days.
- **After a crash**, the program loads the last autosave and replays the logged events after it, reusing the stored AI replies, so no call is paid for twice.
- **Sleep:** while a run is active, the program asks Windows not to sleep. If the laptop sleeps anyway, the next AI call fails, the run pauses itself, and nothing is lost.

## Observer screen (observer/)

- pygame-ce window. Left: the island map with players, villagers, animals and weather. Right: tabs for Chats, Choice points, World history, Players and Spend, built with pygame_gui so text can scroll.
- Top bar: game clock, day and season, pause/resume button, speed control, spend warning, autosave indicator.
- Drawn at 30 frames per second, separately from ticks. The observer reads the world and the database and never changes them, except for pause, resume and speed.
- A read-only map viewer (map only, no tabs) comes first, in Phase 1, so the island can be checked by eye from the start. The tabs and controls come in Phase 3, watching rule-based players, before any AI is built. Phase 4 adds the AI players' values, choice points and spend; Phase 5 adds the judge's labels.
- Colour pixel art (Kenney colour tiles, Tiny Creatures animals, each player in its own colour), with a `mono` switch for the original black-and-white look. Moving things slide between tiles at their real speed, and the light follows the clock through dawn and dusk (Phase 1.5). This is drawing only: the world still moves in whole tiles and whole ticks.
- Headless mode (no window) for tests and long unattended stretches.

## Configuration (config/)

All numbers live in plain text files, so tuning after the pilot never needs code changes.

| File | Holds |
| --- | --- |
| world.toml | Map size, season length (2 game weeks), resource amounts and regrowth, animal and dog numbers |
| balance.toml | X formula weights, curves and half-life, hooked threshold and hooked memory size, villager loyalty rules, task rewards, action durations, decision-trigger settings (such as the 2-hour check) |
| models.toml | Model versions for all nine roles, prices, thinking settings |
| run.toml | Seed, run name, spend cap, autosave interval |
| assets.toml | Which pack tile (or code drawing) shows each item on the asset list |
| .env (repo root) | API keys (never shared or committed) |

## Testing (tests/)

- **A fake AI adapter** returns pre-written replies. Every phase is built and tested with it; the build itself spends nothing. Tim runs every paid step after Phase 5: the calibration, a few judge calls, an optional one-week test and the pilot.
- **Same seed, same island:** a game year with rule-based players must produce an identical event log on two runs.
- **Rule tests:** every action, its duration and interrupts, every sense range and X calculation is checked on small example situations.
- **Schema tests:** good and bad example replies for every reply type.
- **Save tests:** pause, resume and crash recovery must give the same result as an uninterrupted run.

## Tools

| Tool | Use |
| --- | --- |
| Python 3.13 | The language |
| uv | Installs Python and every library at pinned versions with one command |
| pygame-ce, pygame_gui | Window and tabs |
| pydantic | Reply schemas, config checking |
| anthropic, openai, google-genai, mistralai, ollama | AI connections |
| python-dotenv | Loads the API keys from .env at runtime |
| pytest | Automatic tests |
| ruff | Keeps code tidy and catches simple mistakes |
| git | Version history, so any phase can be undone |
| Claude Code and Codex CLI | The two-manager build system: Codex plans each phase alongside Claude, Claude builds it |

All file paths are built with Python's pathlib, so the code works on Windows without changes. Phase 1 confirms that every library installs on the Dell XPS, including pygame_gui with pygame-ce, and that the map window stays sharp under Windows display scaling.

## Which phase builds what

Phase specs and acceptance criteria are in `phases.md`; the original checklists are in the Build Phases doc.

| Phase | Builds |
| --- | --- |
| Setup (by hand) | Accounts and keys, installs, the repo (this copy of the build system), docs, assets |
| 1 Skeleton and the island | Project skeleton, config/, storage/ (basic, all tables), world/, map viewer, headless main.py |
| 1.5 Colour and time-true movement | world/movement.py (speed per kind, own timers, saved mid-step), the viewer in colour with Tiny Creatures animals, sliding sprites and clock-driven light |
| 2 Bodies, villagers, actions and senses | rules/ (needs, X, every action with durations and interrupts, tasks, land, Discoverer, chat), villagers in world/, rule-based and scripted players |
| 3 Observer screen, run control and exports | The full observer/ with every tab, pause, autosave, crash recovery, the measures that need no AI, CSV export; all watched with rule-based players |
| 4 Minds and AI connections | minds/ (router, fast, slow and hooked tiers, memory, values, reflection), llm/, model choice, choice points with self-labels, spend counter and cap, crash recovery reusing stored replies |
| 5 Judge, measurement, calibration and pilot tools | The judge and summaries, the remaining measures, the calibration command, pilot profile, analysis report, launch check; Tim then runs the first paid steps (calibration, pilot) |
| 6 Tuning and launch | Tuning config/ from the pilot, results into the Design Document; Tim starts the open-ended run |

## Budget

Costs are counted per **game week**, because thinking time and pauses make real time meaningless for cost.

| Item | Estimate |
| --- | --- |
| One slow decision, medium thinking, with caching | about $0.01–0.03 |
| Slow calls per game week (4 players × about 20 a day) | about 560 |
| Helpers, judge and weekly reflections | small, about $1 a week |
| Total per game week | about $12–17 |
| Game weeks for $100 | about 6–8 |

The calibration and the pilot (after Phase 5) replace these with measured figures. Players decide only on the triggers above, which is what keeps slow calls near 20 per player per game day. With 2-week seasons, winter falls in game weeks 7–8, so the affordable run reaches it.

## Sources

- [Concordia: generative agent-based modeling (Google DeepMind)](https://arxiv.org/abs/2312.03664v1): the world-runner and component ideas this design borrows
- [pygame-ce on PyPI](https://pypi.org/pypi/pygame-ce): versions and supported Python releases, including Windows builds
- [Claude structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Gemini API structured outputs with JSON Schema](https://blog.google/technology/developers/gemini-api-structured-outputs/)
- [Grok structured outputs and automatic caching](https://docs.apiyi.com/en/api-capabilities/grok/chat)
- [Ollama on Windows: Intel Arc support status](https://vucense.com/dev-corner/ollama-on-windows-2026-install-guide/)
- [LLM API prices, October 2026](https://hireagentic.dev/blog/llm-api-pricing-comparison)
