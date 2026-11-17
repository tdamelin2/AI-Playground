# Project overview

## Goal
AI Island is a Python simulation that drops four AI players (Claude, GPT, Gemini and
Grok, each believing it is a person) onto a small, resource-limited colour pixel-art
island, and records how their values form, collide and change under scarcity. It is
for Tim, who watches the run through a pygame observer window and analyses the logs in
R. The core question: when breaking a value raises a player's wellbeing (X), does it
keep the value or drop it?

The full specification lives in `docs/` and is the source of truth for every phase:
- `docs/design.md`: what the game is (world, players, mind, values, X, measurement)
- `docs/gameplay.md`: detailed rules (tools, fire, dogs, every action, triggers, land, assets)
- `docs/architecture.md`: code structure, the tick, storage, AI calls, config files
- `docs/build-phases.md`: the original phase checklists that `phases.md` turns into
  acceptance criteria
- `docs/setup.md`: the one-time manual setup Tim does

Planners read `docs/architecture.md` in full at every phase start, and the sections of
the other docs that the phase in `phases.md` points to.

## Tech stack
- Python 3.13, managed by uv (`uv add` for packages, `uv run` for every command,
  never pip). Pinned versions in `uv.lock`.
- pygame-ce and pygame_gui for the observer window (never plain pygame).
- Pydantic v2 for config checking and every AI reply schema.
- SQLite (Python's built-in sqlite3) for the event log, AI call records and saves.
- Config in TOML files read with the built-in tomllib.
- AI SDKs (from Phase 4): anthropic, openai (also for xAI's OpenAI-compatible API),
  google-genai, mistralai, and ollama for local embeddings.
- pytest for tests, ruff for lint and formatting. No type-checker.
- Art: Kenney 1-Bit Pack in colour (CC0) plus Tiny Creatures (CC0) for the animals, and simple code drawings for anything neither has; monogram pixel font.

## Architecture
A turn-based world with a window on top (details: `docs/architecture.md`).
- The world advances in ticks; 1 tick = 1 game minute. Each tick: update the world,
  build sense reports (the Discoverer, plain code), decide who needs a decision and
  which tier (reflex code / fast cheap model / main model: slow with its helpers, or
  hooked, alone with fewer memories), ask the AIs (the
  clock stops while waiting), validate replies, resolve all actions simultaneously,
  run the chat phase, log everything.
- Players decide only when an action finishes, someone speaks to them, an interrupt
  happens, or 2 game hours pass awake without a decision.
- Every random number comes from the run seed through named random streams, so the
  same seed gives the same event log.
- The pygame observer only reads the world and the database (plus pause, resume and
  speed). The same world runs headless for tests.
- One SQLite database per run (`runs/<name>/run.db`) holds the append-only event log,
  AI calls, choice points, judge labels, chats, value history, spend and snapshots.

Components (all under `src/ai_island/`):
| Package | Job | Never does |
|---|---|---|
| `world/` | Island state and its update each tick: map, clock, seasons, weather, resources, plants, animals, wild dogs, villagers | import pygame, call an AI |
| `rules/` | Actions (effects, durations), interrupts, tasks and rewards, tools, fire, land and landmarks, needs and the X formula, the Discoverer, chat | import pygame, call an AI |
| `minds/` | Decision triggers, router, reflex/fast/slow tiers, prompts, memory, values, knowledge book, weekly reflection, rule-based and scripted test players | import pygame |
| `llm/` | One interface for every model; one adapter per company, Ollama embeddings, the fake adapter, prices and spend | |
| `measure/` | Choice point records, judge, summaries, per-week measures, CSV export, pilot analysis | |
| `observer/` | The pygame window: map viewer, tabs, top bar, controls, asset loader | change world state (except pause, resume, speed) |
| `storage/` | SQLite schema, event log, snapshots, autosave, crash recovery, run control | |
| `cli.py` | The command-line commands that `main.py` exposes | |

## Folder layout
```
src/ai_island/      the Python package (subpackages above), installed by `uv sync`
main.py             thin entry point: `uv run python main.py <command>`
config/             world.toml, balance.toml, models.toml, run.toml, assets.toml
                    (every tunable number lives here, never in code)
pyproject.toml      project, dependencies, ruff and pytest settings
uv.lock, .python-version
tests/              all automated tests (the tester owns this folder)
assets/             art packs and font, stored unchanged (read-only for agents)
docs/               the specification (see Goal)
runs/               one folder per run: run.db, logs, exports (created by the program,
                    never committed)
.env                API keys (never read, printed or committed)
```
Part folders for coders are normally: `src/`, `config/`, `main.py`, `pyproject.toml`,
`uv.lock`, `.python-version`. A phase may add a single file under `docs/` when it must
record a decision there (say which file in the Plan). `assets/`, `.env` and `runs/` are
never Part folders. The project's own code never uses the root `scripts/` folder (it
belongs to the two-manager system); helper commands live in `src/ai_island/` and are
run through `main.py`.

Tests import the package as `ai_island.<subpackage>`. Tests that open a window set
`SDL_VIDEODRIVER=dummy` so they run without a screen.

## Constraints
- Runs on Tim's Dell XPS: 64-bit Windows, Intel Core Ultra X7 358H, 32 GB RAM, Intel
  Arc B390 integrated graphics. Use pathlib for every path. The window must stay sharp
  under Windows display scaling (DPI-aware, whole-number pixel scaling).
- `world/` and `rules/` never import pygame and never call an AI.
- Every tunable number lives in `config/*.toml`, checked by a Pydantic model on load
  (unknown keys and wrong types fail at start with the file and key named).
- Determinism: all randomness comes from the run seed through named streams, one per
  subsystem, derived with a stable hash (hashlib), never Python's salted `hash()`, and
  never from wall-clock time or unordered set iteration. Same seed = same event log.
- The event log is append-only. Every database table from `docs/architecture.md`
  exists from Phase 1, so later phases add rows, not migrations.
- Snapshots and saved state are JSON (compression allowed), not pickle, so saves stay
  readable after code changes.
- No real AI calls (and no spending) unless the current phase says so. Tests use the
  fake adapter and mocked SDK clients, with no network and no keys. Any command that
  spends money needs an explicit `--max-dollars` limit and is run by Tim, never by an
  agent.
- Never read, print or log `.env` or any API key. The program loads keys at runtime
  with python-dotenv; agents don't open the file.
- Players see only their human names and never anything that reveals AI, models,
  companies, a game, an experiment or an observer. The judge never sees model or
  company names.
- No Chinese-developed models in any role.
- Budget: $100 for the whole open-ended run, enforced by the spend cap.
- Version 1 is silent (no audio) and has no free-form "improvise" action, no villager
  births, no currency.

## Out of scope
- Multiplayer, networking, or running on any machine other than Tim's laptop.
- Audio, hand-drawn art, animation frames (sprites only flip left/right).
- Running local language models for decisions (Ollama is used only for embeddings).
- Automatic model switching on outages (the run pauses instead).
- A web interface or cloud deployment.
