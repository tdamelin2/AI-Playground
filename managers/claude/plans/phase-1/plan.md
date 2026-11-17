# Phase 1: Skeleton and the island | Claude plan
Status: Done | Started: 2026-11-01 18:35 | Finished: 2026-11-01 18:37
Helpers: Claude: 1 coder - greenfield phase; the viewer reads world internals directly, so a world/observer split would need a large, still-moving contract and coder-b could not run anything until coder-a's pyproject and world exist

## Summary
Greenfield. One coder builds in dependency order: uv project and deps -> package skeleton -> config models + TOML -> named RNG streams -> storage (8 tables, append-only trigger, typed events, JSON snapshots) -> clock/tick loop -> map gen + A* -> weather -> resources/plants/animals/dogs -> CLI (new/resume/headless) -> assets.toml + loader + read-only viewer with screenshot mode.
Key design rules: the world is a plain-data `WorldState` (dataclasses/dicts, JSON-serialisable) advanced by `step(world, rngs, events)`; subsystems update on configured intervals (not every tick) so a full year (80,640 ticks) stays well under 5 minutes; only aggregate/meaningful events are logged (no per-animal-step events) to keep the log small; snapshots are zlib-compressed canonical JSON (sort_keys) including every stream's `getstate()`; event payloads are canonical JSON so logs compare byte-for-byte.

## Proposed split
Coders: 1 - see Helpers line
Part A: whole phase | Folders: src/, config/, main.py, pyproject.toml, uv.lock, .python-version
Contract: none (one coder). Internal interfaces the tester relies on (fixed now so tests can be written from the Plan):
- `ai_island.config.load_config(config_dir: Path = Path("config")) -> GameConfig` (fields `.world .balance .models .run .assets`); `load_file(path: Path, model) -> model`; errors raise `ai_island.config.ConfigError` whose message contains the file name and the dotted key.
- `ai_island.rng.Streams(seed: int)`: `.get(name: str) -> random.Random` (seeded from `int.from_bytes(hashlib.sha256(f"{seed}:{name}".encode()).digest()[:8])`); `.state() -> dict` (JSON-safe), `Streams.from_state(dict)`.
- `ai_island.storage.db.RunDB.create(path: Path)` / `RunDB.open(path)` / `RunDB.memory()`; `.append_events(list[Event])`, `.events() -> list[Event]` (ordered by seq), `.save_snapshot(tick: int, state: dict)`, `.latest_snapshot() -> tuple[int, dict] | None`, `.table_names()`. No update/delete method for events. Triggers `events_no_update` / `events_no_delete` RAISE(ABORT).
- `ai_island.storage.events.Event` (Pydantic: `tick: int`, `type: str`, `payload: dict`), typed subclasses per event type.
- `ai_island.sim.Simulation`: `Simulation.new(config, seed)`, `Simulation.from_snapshot(config, state)`, `.run(ticks, pace_seconds: float | None = None)`, `.snapshot() -> dict`, `.world`, `.events` (list emitted so far), `.clock` (tick -> day, season, week, year, is_night).
- `ai_island.world.pathfinding.astar(grid_costs, start, goal) -> list[tuple[int,int]] | None` where `grid_costs[y][x]` is a float cost or None (impassable).
- World query/mutation API (used by Phase 2 actions and by tests): `cut_tree(world, pos)`, `take_stone(world, pos, n) -> int`, `plant_crop(world, pos, tick)`, `remove_plant(world, pos, tick)`, `remove_animals(world, kind, area, tick)`, `water_output(world, source_pos) -> float`, weather flags `world.weather.flags -> {stops_outdoor_work, puts_out_campfires, water_multiplier}`.
- CLI: `new <run> [--seed N]`, `resume <run> [--ticks N]`, `headless --ticks N [--run <run>] [--seed N]`, `view [--run <run>] [--seed N] [--ticks N --screenshot <png>]`. headless/resume print the final game time as `Year Y, <Season>, week W, day D, HH:MM` on stdout.
Work IDs: P1-A-01 uv project: pyproject (hatchling, src layout, requires-python ">=3.13,<3.14"), .python-version 3.13, `uv add` all runtime + dev deps, ruff + pytest config (testpaths=tests, marker `slow`); P1-A-02 package skeleton: all subpackages; later-phase packages (minds, llm, measure) contain only a one-line-docstring `__init__.py`; main.py -> ai_island.cli.main; P1-A-03 config: 5 TOML files + Pydantic models (extra="forbid", strict types), ConfigError naming file and key; models.toml = embedding model `nomic-embed-text` + empty roles table only; P1-A-04 named RNG streams via hashlib, state round-trip; P1-A-05 storage: schema for all 8 tables (columns below), append-only triggers, typed events, snapshot save/load (zlib JSON); P1-A-06 clock + tick loop (headless unpaced, live 0.36 s/tick / speed), season/day/night from world.toml; P1-A-07 map generation 80x80 (home plot template rotated into 4 corners, buffer, centre with forest/quarry/best farmland/lake, 3 landmarks, coast, unclaimed pool) + A* with config terrain costs; P1-A-08 weather by season odds + flags; P1-A-09 resources: trees regrow/over-cutting per forest area, finite stone, seasonal water with drought, farmland soil states + crop growth; P1-A-10 seven plant types with seasons + regrowth; P1-A-11 animals (7 kinds incl. nests) breed/move/flee from dogs/local extinction with recolonisation delay; P1-A-12 wild dog packs 2-4 in buffer+centre forests, night/winter activity, slow breeding; P1-A-13 CLI new/resume/headless with snapshot at end of every command and seed precedence (--seed > run.toml); P1-A-14 config/assets.toml covering every asset-list item (Kenney col/row index or `code`) + `missing` list; P1-A-15 observer asset loader (cut sheet, recolour to black on white, integer scale, code drawings 16x16 two colours); P1-A-16 read-only view window (map, plants, animals, dogs, weather + night overlays, clock/day/season in title, DPI-aware, integer scale, arrow-key scroll) + `--ticks N --screenshot` headless-renderable mode.

Storage columns (P1-A-05), from docs/architecture.md "Everything is recorded" and the docs/design.md choice point record:
- events(seq INTEGER PRIMARY KEY, tick INTEGER NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL /*canonical JSON*/)
- ai_calls(id PK, tick, player, role, company, model, model_version, prompt, reply, thinking_tokens, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, duration_ms, status, error)
- choice_points(id PK, tick, player, situation, x_value, feeling, tier, thought, noticer_read, advisor_said, advisor_followed, action, self_label_values, self_label_direction, outcome, insight, ai_call_id)
- judge_labels(id PK, choice_point_id, tick, label_kind /*full|short*/, served_values, violated_values, direction, summary, ai_call_id)
- chats(id PK, tick, speaker, listeners /*JSON*/, in_earshot /*JSON*/, location /*JSON*/, text)
- value_history(id PK, tick, player, value_name, weight, invented INTEGER, cause_event_seqs /*JSON*/)
- spend(id PK, tick, ai_call_id, company, role, cost_usd, cumulative_usd)
- snapshots(id PK, tick, format_version, state BLOB /*zlib canonical JSON*/)

## Findings
- No code exists yet; CLAUDE.md project commands are already filled in and match this plan.
- uv 0.11.8 is installed. `assets/urizen/` does not exist (AC-20 still requires that no code references it).
- Kenney sheet `assets/kenney_1bit/Tilesheet/monochrome-transparent.png` = 49x22 tiles, 16 px, 1 px gap => tile (c,r) at x=c*17, y=r*17; sheet 832x373. The monochrome tiles are a light colour on transparency, so the loader must recolour every opaque pixel to pure black and composite on white (AC-20: only black, white, transparent). The coder maps tiles by viewing the sheet image (Read tool shows PNGs).
- Performance (AC-10, 80,640 ticks < 5 min => < 3.7 ms/tick): per-tick work must be O(1)-ish. Config-driven intervals: weather draw every `weather_interval_ticks` (e.g. 360), plants/trees/crops/water daily or hourly, animal + dog movement every `move_interval_ticks` with dog activity multiplier. Events buffered and inserted with executemany, one commit per command/snapshot. Movement uses cheap random-neighbour steps, never A* per animal per tick.
- Determinism traps: never iterate sets/dicts built from unordered sources; sort entity ids; no `hash()`, no time; snapshot must not emit an event (AC-7 compares logs of split vs. uninterrupted runs), and the tick loop state must be fully in the snapshot (including counters such as next entity id and dog movement counters).
- AC-7 needs "load into a fresh process": CLI `headless --run r --ticks T` then `resume r --ticks M` is exactly that; the event log in the run db then equals a single `headless --ticks T+M`.
- AC-12 reachability: water is impassable; spring, lake and quarry targets are reached by an adjacent walkable tile; landmarks (quarry tile, lake dock, great tree base) are walkable tiles. Home plot template generated once from the `map` stream, then rotated 90/180/270 into the other corners, so `rot90^k(plot_k) == plot_0` exactly.
- AC-15 over-cutting: each forest is a connected "forest area"; if its standing-tree fraction falls below `overcut_threshold`, no tree in it regrows.
- AC-17 local extinction: island divided into fixed zones (size in world.toml); a kind at zero in a zone cannot reappear there for `recolonise_days`.
- AC-18 measurability: dog packs keep movement counters per (day/night, season) in state so tests can compare.

## Risks
- Asset mapping is large and visual; wrong tile indices are the most likely AC-19/20 failure. Mitigation: indices stored as (col,row), validated in range on load; every item has an entry or `code`.
- Year-long run time (AC-10) and determinism (AC-8) failures. Mitigation: interval-based updates, aggregate events, canonical JSON, sorted iteration; coder runs `headless --ticks 80640` and times it before reporting.
- pygame window under dummy driver: DPI call (`ctypes.windll.shcore.SetProcessDpiAwareness`) must be wrapped and skipped when not on Windows or when it fails; screenshot mode must not wait for events.
- Ruff format of generated code: coder runs `uv run ruff format` and `ruff check` before reporting.

## Questions
| ID | Blocking | Question | Suggested answer |
|----|----------|----------|------------------|
| P1-Q-CLA-01 | no | Does `view` write events/snapshots to the run database? | No. It loads the latest snapshot (or a fresh world from the seed), simulates in memory and never writes; architecture.md "Observer screen" says the observer never changes the world or database. Live runs that write come in Phase 3. |
| P1-Q-CLA-02 | no | How many ticks does `resume <run>` run, so that it terminates? | Add optional `--ticks N`; default `resume_ticks` in run.toml (1440). phases.md AC-22 only requires it to continue from the latest snapshot. |
| P1-Q-CLA-03 | no | Where does `headless` without `--run` store its log? | In an in-memory database; nothing written to runs/. With `--run`, it creates/uses runs/<run>/run.db. |
| P1-Q-CLA-04 | no | What does models.toml contain now? | `[embedding] model = "nomic-embed-text"` and an empty `[roles]` table whose schema accepts role entries later; no model names (phases.md Phase 1 Config). |
| P1-Q-CLA-05 | no | Which weather types stop outdoor work and put out campfires? | Storm: stops outdoor work + puts out campfires; rain: puts out campfires only; drought: water multiplier < 1 (gameplay.md "Fire", design.md "Weather"). |
| P1-Q-CLA-06 | no | Where do config models and the RNG live, since Overview lists no config package? | `src/ai_island/config.py` and `src/ai_island/rng.py` as top-level modules (no pygame), plus `src/ai_island/sim.py` for the tick loop. |

## Helper notes
none (no helpers)
