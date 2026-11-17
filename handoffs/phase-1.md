# Phase 1: Skeleton and the island
Status: Stage: Done | Round: 2/3 | Updated: 2026-11-01 19:59

## For Tim
This phase builds the foundation: the project setup, the settings files, the save
system (a database with every table the later phases need), and a living island with
no players yet. Plants grow, animals breed and wander, wild dogs roam, weather and
seasons change, and a whole game year can run fast with no window, giving the exact
same result every time with the same seed (the starting number for all the luck in
the game). You also get a simple map window to watch it.
The work is split between two coders working at the same time: one builds the
island and the save system, the other builds the map window and matches every
picture to a tile in the Kenney art pack. They meet at one agreed "snapshot of the
map" format, so neither has to wait long for the other.
From Codex I took: the two-coder split, a more careful database layout, saving the
game settings inside each save so a resumed game behaves the same, and stricter
checks on settings files. Nothing in this phase costs money.
You are approving this plan before any code is written.

## Plan
Goal: full code skeleton, config, storage with all eight tables, and a living player-less island that runs a full game year deterministically, headless or in a read-only map viewer. Cost $0.
Planning inputs: Claude Done; Codex Done
Coders: 2 - the island simulation/storage and the observer (assets mapping + pygame viewer) are structurally separate; they meet only at the frozen pygame-free `WorldFrame` and `AssetsConfig` shapes below, and the asset mapping is a large independent job.
Part A (coder-a): uv project and dependencies, package skeleton, all config models + world/balance/models/run TOML, named RNG streams, storage (schema v1, append-only, typed events, snapshots), clock + tick loop + simulation session, map generation + A*, weather, resources, plants, animals, wild dogs, `world/view.py` (WorldFrame + frame_from_world), CLI (new/resume/headless/view including screenshot mode, which calls Part B's Viewer).
Part A folders: src/ai_island/__init__.py, src/ai_island/config.py, src/ai_island/rng.py, src/ai_island/sim.py, src/ai_island/cli.py, src/ai_island/world/, src/ai_island/rules/, src/ai_island/minds/, src/ai_island/llm/, src/ai_island/measure/, src/ai_island/storage/, config/world.toml, config/balance.toml, config/models.toml, config/run.toml, main.py, pyproject.toml, uv.lock, .python-version
Part B (coder-b): config/assets.toml (every docs/gameplay.md asset-list item mapped to a Kenney tile or `code`, plus `missing`), observer/ package: sprite loader (cut, recolour black on white, binary alpha, code drawings), Viewer window (map, plants, animals, dogs, weather + night + snow/drought overlays, title clock, DPI-aware, integer scale, arrow-key scroll, PNG save).
Part B folders: src/ai_island/observer/, config/assets.toml
Contract:
- Order: coder-a does P1-A-01 (pyproject, `uv add` of every dependency, `uv sync`) and P1-A-02 (skeleton) first. coder-b starts with the asset mapping (no Python needed) and never runs `uv add`/`uv sync`/`uv lock`; it only uses `uv run` once pyproject.toml exists. coder-b never edits Part A files; a needed change to the shapes below is reported as Blocked.
- AssetsConfig (A writes the Pydantic model in config.py; B writes the values). TOML shape:
  `[sheet]` path (str, project-relative), tile_size=16, gap=1, columns=49, rows=22;
  `[items.<key>]` source = "kenney" | "code"; kenney items require col (int, 0..columns-1) and row (int, 0..rows-1) and may set `flip` (bool, default false); code items have no col/row;
  `[missing]` items = [list of keys drawn in code because Kenney lacks them] - every key in it must exist in items with source "code".
  Keys are lowercase snake_case. Validation errors name assets.toml and the key.
- run.toml `[view]` (A writes; B reads `config.run.view`): seconds_per_tick=0.36, speed=1.0, fps=30, max_scale=4 (int), scroll_tiles=4 (int), window_width=1280, window_height=800.
- `ai_island.world.view` (A, no pygame): frozen dataclasses
  `EntityView(id: int, kind: str, x: int, y: int)`;
  `LandmarkView(kind: str, x: int, y: int)` kind in quarry | lake_dock | great_tree;
  `WorldFrame(tick, year, season, week, day, hour, minute: int/str as named; season in spring|summer|autumn|winter; is_night: bool; weather: str in clear|rain|storm|drought; width: int; height: int; terrain: tuple[tuple[str, ...], ...] row-major [y][x]; plants, animals, dogs: tuple[EntityView, ...] sorted by id; landmarks: tuple[LandmarkView, ...])`;
  `frame_from_world(sim) -> WorldFrame`.
  Terrain keys: grass, sand, tree, stump, spring, lake, coast, farmland_empty, farmland_planted, farmland_growing, farmland_ready, farmland_failed, rocky, rocky_depleted, quarry, quarry_depleted.
  Plant kinds: berries, mushrooms, roots, herbs, healing_herbs, mild_poison, strong_poison. Animal kinds: rabbit, deer, boar, fish, bird, nest_eggs, goat, chicken. Dog kind: wild_dog.
  Every terrain key, plant kind, animal kind, `wild_dog`, and each landmark kind is also an items key in assets.toml. Season/weather/night visuals are B's code overlays (snow in winter, drought, rain, storm, night).
- `ai_island.observer` (B): `load_sprites(assets: AssetsConfig, root: Path) -> dict[str, pygame.Surface]` loads every item eagerly, each 16x16 using only black (0,0,0,255), white (255,255,255,255) and fully transparent pixels; raises on any bad entry. `Viewer(assets: AssetsConfig, view: ViewConfig, root: Path)` sets Windows DPI awareness before creating the window (skipped safely elsewhere or on failure) and loads sprites; `.pump() -> bool` (False on quit; handles arrow-key scroll); `.draw(frame: WorldFrame) -> None` (window title shows game clock, day and season); `.save_png(path: Path) -> None` (creates parent dir); `.close()`. Viewer never steps the world, draws random numbers or touches SQLite. No file under assets/urizen/ is ever referenced.
- Simulation (A, used by tests): `ai_island.config.load_config(config_dir: Path = Path("config")) -> GameConfig` (.world .balance .models .run .assets), `load_file(path, model)`, `ConfigError` (message names file and dotted key); models are strict (no coercion, bool is not int) with extra="forbid" at every level. `ai_island.rng.Streams(seed)`: `.get(name) -> random.Random` seeded from sha256 of a versioned `"v1:{seed}:{name}"`, `.state() -> dict` (JSON-safe), `Streams.from_state(d)`. `ai_island.storage.db.RunDB.create(path)/open(path)/memory()`, `.append_events(list[Event])`, `.events() -> list[Event]` ordered by id, `.save_snapshot(...)`, `.latest_snapshot()`, `.table_names()`; no method updates or deletes events. `ai_island.storage.events.Event` (Pydantic: tick, type, payload) as a discriminated union of typed payload models. `ai_island.sim.Simulation.new(config, seed)`, `.from_snapshot(...)`, `.run(ticks, pace_seconds=None)`, `.snapshot()`, `.world`, `.events`, `.clock`. `ai_island.world.pathfinding.astar(costs, start, goal) -> list[tuple[int, int]] | None` (costs[y][x] float or None = impassable; 4 neighbours in fixed order; cost of entering a tile; Manhattan x min cost heuristic). World mutation API for tests and Phase 2: `cut_tree(world, pos, tick)`, `take_stone(world, pos, n) -> int`, `plant_crop(world, pos, tick)`, `remove_plant(world, pos, tick)`, `remove_animals(world, kind, zone, tick)`, `water_output(world, pos) -> float`, `world.weather.flags` -> stops_outdoor_work, puts_out_campfires, water_multiplier.
- Storage schema v1 (A): as in managers/codex/plans/phase-1/plan.md "Storage schema v1" (events id/tick/type/payload_json with BEFORE UPDATE, BEFORE DELETE and duplicate-id BEFORE INSERT abort triggers; ai_calls, choice_points, judge_labels, chats, value_history, spend, snapshots with the listed columns, json_valid checks, foreign keys on). Snapshots hold last_event_id watermark, schema_version, config_json + config_hash, state_json (zlib-compressed canonical JSON allowed), rng_json, spend_usd. Snapshot creation never adds an event. Snapshots are taken at `new` (tick 0) and at the clean end of every persisted command; periodic autosave is Phase 3.
- CLI (A): `new <run> [--seed N]` refuses an existing run, creates runs/<run>/run.db, world and tick-0 snapshot. `headless --ticks N [--run R] [--seed N]`: without --run, in-memory DB, nothing written; with --run, creates the run if missing or restores and appends N ticks (an explicit --seed that conflicts with the saved seed is an error). `resume <run> [--ticks N]`: requires an existing run, restores the latest snapshot using the snapshot's pinned config_json (not edited config/), runs N ticks headless (default run.toml `resume_ticks` = 1440), saves. An event tail after the snapshot's watermark is an explicit "crash recovery not supported until Phase 3" error. headless/resume print the final game time on stdout as `Year Y, <Season>, week W, day D, HH:MM`. `view [--run R] [--seed N]`: live, paced at seconds_per_tick / speed, renders at fps, from the run's latest snapshot or a fresh seeded world; never writes to the DB. `view ... --ticks N --screenshot <png>`: runs N ticks unpaced in memory, draws one frame, saves the PNG, exits 0 (works with SDL_VIDEODRIVER=dummy). --seed overrides run.toml seed.
Work IDs: P1-A-01 uv project: pyproject (hatchling, src layout, requires-python ">=3.13,<3.14"), .python-version, `uv add` pygame-ce pygame_gui pydantic python-dotenv anthropic openai google-genai mistralai ollama, dev pytest ruff, ruff + pytest config (testpaths tests, marker slow); P1-A-02 package skeleton: world, rules, minds, llm, measure, storage (observer is B's), cli.py, main.py -> ai_island.cli.main; minds/llm/measure contain only a one-line-docstring __init__.py; rules/ has only what this phase needs (nothing beyond its __init__ if unused); P1-A-03 config models (incl. AssetsConfig) + world/balance/models/run TOML, strict, errors name file and key; models.toml only `[embedding] model = "nomic-embed-text"` and an empty roles table; P1-A-04 named RNG streams (hashlib), state round-trip, independent streams; P1-A-05 storage schema v1, append-only triggers, typed events, snapshot save/load with watermark and pinned config; P1-A-06 clock (day 1440 ticks, seasons of 14 days, year 80,640, day/night from world.toml) + tick loop (headless unpaced; live paced) + Simulation session; P1-A-07 map 80x80: home template generated once from the `map` stream and rotated into four corners (including its initial resources, plants and animals), buffer, centre (large forest, quarry, best farmland, lake), quarry/lake dock/great tree as walkable tiles, coast, unclaimed-land pool, guaranteed corridors; A* with config terrain costs; P1-A-08 weather: equal intervals dividing the season, independent draw from season odds at each interval and at every season boundary; flags (storm stops outdoor work; rain and storm put out campfires; drought lowers water); P1-A-09 resources: tree regrowth and per-forest-area over-cut threshold, finite stone, seasonal water reduced in drought, farmland soil states with crops ready within one season and no winter growth; P1-A-10 seven plant types with configured seasons and regrowth; P1-A-11 animals (seven kinds incl. spring-only nests with eggs): seasonal breeding with capacities, movement, flee from dogs, per-zone local extinction with recolonisation delay; P1-A-12 wild dog packs of 2-4 only in buffer and centre forests, movement activity higher at night and in winter (counters kept in state), slow breeding; P1-A-13 world/view.py WorldFrame + frame_from_world; P1-A-14 CLI new/resume/headless/view (+ screenshot mode) per the contract; P1-B-01 config/assets.toml: every docs/gameplay.md asset-list item (terrain incl. states, plants, animals, characters incl. 4 players and a bounded set of villager variants, state markers, structures incl. damaged variants, item icons incl. every basic/better tool, observer-screen concept icons) mapped to a Kenney (col,row) after viewing the sheet, or `code`; `missing` section; P1-B-02 sprite loader: crop at (col*17, row*17), recolour opaque pixels black, binary alpha, white background where drawn, code drawings as 16x16 two-colour shapes; P1-B-03 Viewer: map + entities + overlays (night, rain, storm, snow, drought) at whole-number scale, never stretched, arrow-key scroll, title clock/day/season, DPI awareness, save_png.
Acceptance criteria: AC-1 `uv sync` succeeds and `uv run python -c "import pygame, pygame_gui, pydantic, dotenv, anthropic, openai, google.genai, mistralai, ollama"` exits 0; `pygame.IS_CE` is true; AC-2 `uv run ruff check` and `uv run ruff format --check` report no errors; AC-3 packages ai_island.world/.rules/.minds/.llm/.measure/.observer/.storage import; no module under world/ or rules/ imports pygame, pygame_gui or any AI SDK (ast scan); AC-4 each config file loads into its Pydantic model; a copy with an unknown key or a wrong type fails at load naming the file and the key; AC-5 `uv run python main.py new t1 --seed 1` creates runs/t1/run.db with the tables events, ai_calls, choice_points, judge_labels, chats, value_history, spend, snapshots; AC-6 UPDATE or DELETE on events raises; the storage API offers no way to change or remove an event; AC-7 snapshot round trip: run T ticks, save, load in a fresh process, run M more; event log equals an uninterrupted T+M run with the same seed; AC-8 two headless full-year (80,640 ticks) runs with the same seed give identical event logs; a different seed gives a different log; AC-9 drawing extra numbers from one stream does not change any other stream's numbers; AC-10 a headless full game year finishes in under 5 minutes (time recorded); AC-11 tick 0 is day 1, spring, week 1; a day is 1440 ticks; season changes every 14 days (spring weeks 1-2, summer 3-4, autumn 5-6, winter 7-8); tick 80,640 is spring of year 2; day/night follow world.toml; AC-12 map 80x80; four home plots identical after rotation; each has forest, spring, farmland; centre has more trees, farmland and stone than any home plot; quarry, lake dock, great tree in the centre; every landmark and every other home reachable from every home by A*; unclaimed-land pool non-empty; AC-13 A* returns the lowest-cost path on a small hand-made grid with terrain costs, and None when unreachable; AC-14 over many simulated years each weather type's frequency per season is within a stated tolerance of world.toml odds; storms set stop-outdoor-work and put-out-campfires; drought lowers water output; AC-15 a cut tree regrows; an area cut below the over-cut threshold does not regrow; quarry stone never increases; spring and lake water lower in drought; a crop planted in spring reaches ready within one season; crops cannot grow in winter; AC-16 each of the seven plant types appears only in its configured seasons and regrows after removal; AC-17 animal populations grow in breeding seasons; a kind reduced to zero in an area stays absent there for at least the configured time; nests with eggs exist only in spring; AC-18 dogs start in packs of 2-4 only in buffer and centre forests; they move more at night and in winter than by day in summer; their population grows more slowly than rabbits'; AC-19 assets.toml has an entry for every docs/gameplay.md asset-list item (pack + tile index, or code), every tile index inside its sheet, missing items listed; AC-20 every loaded sprite is a 16x16 surface using only black, white and transparency; no code reads any file under assets/urizen/; AC-21 with SDL_VIDEODRIVER=dummy, `uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png` exits 0, loads every mapped sprite, writes a PNG; AC-22 `uv run python main.py headless --ticks 1440 --seed 1` exits 0 and prints the final game time; `uv run python main.py resume t1` continues from the latest snapshot.
Commands: install `uv sync`; build `uv run python -m compileall -q src main.py`; start `uv run python main.py headless --ticks 1440 --seed 1`; lint `uv run ruff check; uv run ruff format --check`; type-check none; tests `uv run pytest`; screenshot `$env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png`
Lessons applied: none (first phase)

Performance and determinism rules for Part A (from both plans): subsystems run on configured intervals in stable (due_tick, subsystem order, entity id) order, never per-entity A* per tick; only meaningful/aggregate events are logged (no per-step animal moves); events are inserted in batches; canonical JSON (sort_keys) for payloads and snapshots; no set/dict iteration from unordered sources, no `hash()`, no clock, no uuid; every counter, timer, next id and stream state lives in the snapshot. coder-a times `headless --ticks 80640` before reporting.

## Decisions
| # | Source | Suggestion | Decision | Reason |
|---|--------|------------|----------|--------|
| 1 | Claude / Codex | Coders: Claude 1, Codex 2 | Changed to 2 | The observer + asset mapping is a separate part once WorldFrame and AssetsConfig are frozen (both are in the Contract); B can start on the mapping before pyproject exists, and it keeps coder-a's very large scope manageable. |
| 2 | Codex | Idea 1: pygame-free deterministic step + exact JSON checkpoints (RNG, schedules, ids) | Adopted | Matches Overview Constraints and AC-7/8; same as Claude's plan. |
| 3 | Codex | Idea 2: explicit schema v1 for all eight tables, atomic snapshot boundaries | Adopted | More complete than Claude's column list (json_valid, FKs, nullable helper fields, details_json); replaces it. |
| 4 | Codex | Idea 3: sparse scheduled ecology with saved timers | Adopted | Needed for AC-10; same as Claude's interval approach. |
| 5 | Codex | Idea 4: rotate the complete home template (incl. resources/residents) and guarantee corridors | Adopted | Makes AC-12 exact; Claude's plan rotated terrain only. |
| 6 | Codex | Idea 5: resolve all packages on Windows now; eager sprite audit, binary alpha | Adopted | phases.md requires early install check (AC-1) and AC-20. |
| 7 | Codex | resume runs a live viewer until the user quits | Rejected | AC-22 must be checked by the tester without a person; resume is headless with `--ticks` (default run.toml resume_ticks). Watching is `view`. |
| 8 | Codex | `view --run` advances and persists the run | Rejected | phases.md calls view read-only and architecture.md says the observer never changes the database; view simulates in memory. Persisted live runs come in Phase 3. |
| 9 | Codex | Snapshot pins config_json; resume uses it (clarified P1-C-CDX-01) | Adopted | Keeps resumed runs identical to uninterrupted ones (AC-7); new runs use current config/. |
| 10 | Codex | Event tail after the snapshot watermark is an explicit error until Phase 3 | Adopted | Never rewrites history; crash replay is Phase 3 scope. |
| 11 | Codex | Periodic autosave every 360 ticks in Phase 1 | Changed | Snapshots at `new` and at the end of every persisted command only; autosave is a Phase 3 item (architecture "Which phase builds what") and would slow AC-10. The interval stays in run.toml. |
| 12 | Codex | Weather: equal intervals dividing the season, independent draws (clarified P1-C-CDX-02), rain and storm both put out campfires | Adopted | Matches gameplay.md "Fire" and Claude's P1-Q-CLA-05. |
| 13 | Codex | Strict config (no coercion, bool not int, nested extra=forbid) | Adopted | AC-4 wrong-type case. |
| 14 | Codex | A*: 4 neighbours, fixed order, cost of entering tile, Manhattan heuristic | Adopted | Deterministic and admissible (AC-13). |
| 15 | Codex | Duplicate-id insert guard on events | Adopted | Blocks INSERT OR REPLACE erasing history (AC-6). |
| 16 | Codex | `new` refuses an existing run; headless --run restores and appends; seed conflict is an error | Adopted | Clear, safe semantics. |
| 17 | Codex | UI/font concepts get code icons now; monogram and widgets stay Phase 3 | Adopted | phases.md Notes defer the font; AC-19 needs full coverage. |
| 18 | Codex | Compatibility: Kenney art is white on alpha; recolour to black, integer scale, scroll at scale 1 | Adopted | Matches Claude's finding; AC-20. |
| 19 | Codex | Tester detail: AC-14 100 years via the weather subsystem, tolerance 0.05, draw and tick-share; round trips in fresh processes with different PYTHONHASHSEED | Adopted | Goes into the Test Task. |
| 20 | Claude | Simulation API and world mutation API fixed in the Contract for tests and Phase 2 | Adopted | Lets the tester write AC-15/16/17 fixtures from the Plan. |
| 21 | Claude | Aggregate events only, batch inserts | Adopted | AC-10 and log size; Codex agreed (bounded batches). |
| 22 | Claude | headless without --run uses an in-memory DB | Adopted | Both plans agree. |
| 23 | Claude | config.py, rng.py, sim.py as top-level modules | Adopted | Codex used config.py + session.py; sim.py chosen, same role. |
Questions: see Questions.md, Phase 1 (9 resolved, 0 escalated)
Clarifications: 2 asked, 2 answered (see managers/claude/plans/phase-1/clarifications.md)

## Round 0
### Code Task A
Assigned: 2026-11-01 18:52 | Work IDs: P1-A-01 .. P1-A-14
Overview: Build the whole simulation side of Phase 1 as specified in the Plan (Part A scope, Contract, Work IDs, Performance and determinism rules). Do P1-A-01 and P1-A-02 first: coder-b is working in parallel and needs pyproject.toml, `uv sync` and the package to exist before it can run `uv run`. Write the AssetsConfig model and the run.toml `[view]` section exactly as in the Contract, because coder-b fills assets.toml against them and reads the view settings. The CLI `view` command imports `ai_island.observer.Viewer` (coder-b's); if it is not ready when you finish, report which view checks you could not run. Never edit src/ai_island/observer/ or config/assets.toml. Before reporting: ruff check + format check clean, `uv run python main.py headless --ticks 1440 --seed 1` works, and time `headless --ticks 80640` (must be well under 5 min).
Checklist:
- [ ] P1-A-01 uv project, all dependencies, ruff + pytest config
- [ ] P1-A-02 package skeleton, main.py
- [ ] P1-A-03 config models (incl. AssetsConfig, ViewConfig) + world/balance/models/run TOML
- [ ] P1-A-04 named RNG streams
- [ ] P1-A-05 storage schema v1, append-only, typed events, snapshots
- [ ] P1-A-06 clock, tick loop, Simulation
- [ ] P1-A-07 map generation + A*
- [ ] P1-A-08 weather + flags
- [ ] P1-A-09 resources (trees, stone, water, farmland/crops)
- [ ] P1-A-10 plants
- [ ] P1-A-11 animals
- [ ] P1-A-12 wild dogs
- [ ] P1-A-13 world/view.py WorldFrame + frame_from_world
- [ ] P1-A-14 CLI new/resume/headless/view (+ screenshot)
#### Report (coder-a fills this in)
Finished: 2026-11-01 19:10 | Status: Done
Checklist: [x] P1-A-01 [x] P1-A-02 [x] P1-A-03 [x] P1-A-04 [x] P1-A-05 [x] P1-A-06 [x] P1-A-07 [x] P1-A-08 [x] P1-A-09 [x] P1-A-10 [x] P1-A-11 [x] P1-A-12 [x] P1-A-13 [x] P1-A-14
Files: created .python-version, pyproject.toml, uv.lock, main.py, config/{world,balance,models,run}.toml, src/ai_island/{config,rng,sim,cli}.py, src/ai_island/storage/{db,events}.py, src/ai_island/world/{clock,pathfinding,state,mapgen,weather,resources,plants,animals,dogs,engine,view}.py | changed src/ai_island/__init__.py, the six package __init__.py files (minds/llm/measure/rules are docstring-only; rules/ has nothing else)
What to run: `uv sync`; `uv run python -m compileall -q src main.py`; `uv run ruff check; uv run ruff format --check` (clean); `uv run python main.py headless --ticks 1440 --seed 1` prints `Year 1, Spring, week 1, day 2, 00:00`; `uv run python main.py new t1 --seed 1`; `uv run python main.py resume t1 [--ticks N]`; `$env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png` (ran OK with coder-b's Viewer, exit 0, PNG written). Timing: a persisted full year (`headless --ticks 80640 --run y1 --seed 3`) took 0.56 s total incl. start-up (AC-10). Same seed with different PYTHONHASHSEED gave identical event logs; run split (3000 + 500 ticks across separate commands) equals an uninterrupted 3500-tick run (checked by comparing DB event rows).
Contract notes (for the tester):
- Clock: `Simulation.clock` is `ai_island.world.clock.Clock` (fields tick, year, season, season_index, week 1-8, day = day of YEAR 1-56, hour, minute, is_night; `.format()`). `Clock.at(tick, config.world.clock)`. Event ticks: work due at tick t runs when the sim reaches t (inclusive); `run(N)` from tick 0 processes everything due up to tick N.
- Config keys: world.toml (clock, map, home, centre, terrain.cost/impassable, weather.interval_ticks + weather.odds.<season>, plants.<kind>, animals.<kind>.{habitat,initial,capacity,breed_seasons,parent_kind,present_seasons}, dogs); balance.toml (extinction_delay_ticks, trees.{regrow_ticks,overcut_threshold}, stone, water.{spring_output,lake_output,multiplier.<weather>}, crops, plants.<kind>.regrow_ticks, animals.<kind>.{breed_interval,birth_chance,move_interval,move_chance,flees_dogs,flee_radius,recolonise_count}, dogs). `load_config` requires assets.toml; `load_sim_config(dir)` skips it. Snapshots pin world/balance/models/run (not assets).
- World API (all re-exported from `ai_island.world`): `generate_world(cfg, streams)`, `cut_tree(world,(x,y),tick)->bool`, `take_stone(world,(x,y),n)->int`, `plant_crop`, `harvest_crop`, `remove_plant(world,(x,y),tick)->bool`, `remove_animals(world,kind,zone,tick)->int` (removes ALL of kind in zone), `population(world,kind,zone=None)`, `water_output(world,(x,y))` (pos is a spring/lake tile or a tile next to one), `world.weather.current` / `.flags` (stops_outdoor_work = storm; puts_out_campfires = rain or storm; water_multiplier), `world.cost_grid()`, `astar(costs,(x,y),(x,y))` includes both ends. Positions are (x, y).
- Zones: `world.zones` = home_0..home_3, centre, buffer. `world.homes[i]` has x,y,size,rotation,anchor; home i is the template rotated clockwise i*90 degrees (so un-rotate with `ai_island.world.mapgen.rotate_cw(x,y,size,4-i)` or compare under any rotation). `world.landmarks` (quarry, lake_dock, great_tree), `world.stone` {(x,y): n}, `world.trees_alive`/`tree_initial` per zone, `world.animals[kind]` list of Animal(id,kind,x,y,zone), `world.plants` PlantSite(id,kind,x,y,present,regrow_due), `world.dogs` Dog(id,pack,x,y), `world.counters["dog_checks"|"dog_moves"][ "<season>_<day|night>" ]` (dogs per check / dogs that moved).
- Weather: draw at tick 0 and every `weather.interval_ticks` (720); `ai_island.world.weather.draw_weather(rng, odds)` and `update_weather(world, tick)` can be exercised directly. Tree regrowth checks over-cut at due time (alive/initial < threshold -> no regrow). Crops: planted -> growing -> ready -> failed -> empty; growth stages wait for the next non-winter season when due in winter.
- Simulation: `Simulation.new(config, seed)`, `.snapshot() -> Snapshot`, `Simulation.from_snapshot(snapshot, config=None)` (config=None uses the pinned config), `.events` = events emitted since this object was created/restored (the DB holds the full log), `.attach(db)`/`.save()` persist. `RunDB.create/open/memory`, `.append_events`, `.events()`, `.save_snapshot`, `.latest_snapshot()`, `.table_names()`. Events are `Event(tick, type, payload)`, payload dict or model, 15 typed payloads in `storage/events.py`.
- CLI messages go to stderr with exit code 2 for user errors (existing run on `new`, seed conflict, event tail after snapshot, missing run).
Next steps / blockers: none. No tests written (tester owns tests/). Dependencies added with uv add; `uv.lock` is created. Files written with ruff format applied by the post-write hook.

### Code Task B
Assigned: 2026-11-01 18:52 | Work IDs: P1-B-01 .. P1-B-03
Overview: Build the observer side of Phase 1 as specified in the Plan (Part B scope and the Contract: AssetsConfig TOML shape, run.toml [view], WorldFrame, observer API). Start with config/assets.toml: view assets/kenney_1bit/Tilesheet/monochrome-transparent.png (tile (col,row) at x=col*17, y=row*17) and map every docs/gameplay.md asset-list item, including every terrain key, plant, animal, wild_dog and landmark kind named in the Contract; mark items Kenney lacks as `code` and list them in `[missing]`. coder-a is building pyproject.toml, config.py and world/view.py in parallel: never run `uv add`, `uv sync` or `uv lock`, and never edit Part A files; once pyproject.toml exists use `uv run` only. If a Contract shape is missing something you need, report Blocked with the exact change rather than working around it. Use SDL_VIDEODRIVER=dummy for your own checks. Before reporting: ruff check + format check clean on observer/.
Checklist:
- [x] P1-B-01 config/assets.toml (all items, missing section)
- [x] P1-B-02 sprite loader (load_sprites)
- [x] P1-B-03 Viewer (pump, draw, save_png, close, DPI, scroll, overlays, title)
#### Report (coder-b fills this in)
Finished: 2026-11-01 19:00 | Status: Done
Checklist: [x] P1-B-01 [x] P1-B-02 [x] P1-B-03
Files: created config/assets.toml, src/ai_island/observer/{__init__,code_art,sprites,viewer}.py | changed none
What to run: `$env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png` (needs Part A's CLI and world/view.py). Lint: `uv run ruff check src/ai_island/observer; uv run ruff format --check src/ai_island/observer`.
Contract notes: config.py did not exist when I finished, so I verified against stand-in objects (tomllib + SimpleNamespace) with a fake 80x80 WorldFrame: 126 sprites loaded, all 16x16 and only black/white/transparent, PNG saved under the dummy driver. Attribute names I rely on, so AssetsConfig/ViewConfig must expose them: `assets.sheet.{path,tile_size,gap,columns,rows}`, `assets.items` (dict key -> object with `.source`, `.col`, `.row`, `.flip`), `view.{max_scale,scroll_tiles,window_width,window_height}`. WorldFrame attributes used: year, season, week, day, hour, minute, is_night, weather, width, height, terrain, plants, animals, dogs, landmarks. Season shown capitalised in the title: "AI Island - Year Y, Winter, week W, day D, HH:MM". `[missing]` lists every `code` item (code items = missing, exactly). Items the loader draws in code: mushrooms, strong_poison, rabbit, deer, nest_eggs, marker_sleeping, snow, drought, overlay_night/rain/storm, item_cooked_meat/spoiled_meat/mushrooms, tool_fishing_net, ui_pause, ui_paused_indicator, ui_font; every `damaged_<x>` is the base sprite plus a crack (base must be a kenney item). The Kenney sheet is a palette PNG with a colour key, so the loader blits it onto an alpha surface before cutting tiles. Viewer scale: largest whole scale up to max_scale at which the whole map fits the window, otherwise 1 with arrow-key scroll (80x80 at 1280x800 means scale 1 and vertical scroll). Esc also quits pump(). Tile picks are my best match by eye (Kenney has no rabbit, deer or mushroom; a few picks such as goat/chicken/boar are approximate). Item keys beyond the contract: claim_border_1..4, boundary_stake, villager_1..6, marker_*, tool_*, item_*, ui_*, damaged_*.
Next steps / blockers: Part A should confirm the AssetsConfig and ViewConfig field names above. Not run: the full CLI screenshot (depends on Part A).

### Test Task
Assigned: 2026-11-01 19:10 | Work IDs covered: P1-A-01 .. P1-A-14, P1-B-01 .. P1-B-03
Check: AC-1 .. AC-22 exactly as listed under "Acceptance criteria" in the Plan. Write tests in tests/acceptance/ from the Plan's Acceptance criteria and Contract (the coders' Contract notes give exact names). Specifics agreed at planning:
- AC-3: ast scan of every module under world/ and rules/ including `from x import` and aliased imports; forbidden: pygame, pygame_gui, anthropic, openai, google.genai/google, mistralai, ollama.
- AC-4: for each of the five TOML files, copy to a temp dir, add an unknown key and separately change a value's type (include bool where an int is expected); the error names the file and the key.
- AC-7: fresh processes (subprocess CLI: `headless --run R --ticks T` then `resume R --ticks M`) at off-cadence T near a day or season boundary, vs an uninterrupted T+M run; compare ordered (tick, type, payload_json) rows; also run with differing PYTHONHASHSEED.
- AC-8: full year twice with the same seed, once with a different seed; mark slow if needed but keep it in the default `uv run pytest` run.
- AC-10: time a persisted full-year headless run and record the seconds in the Report.
- AC-14: exercise the weather subsystem directly over at least 100 configured years; absolute tolerance 0.05 per weather type per season for draw frequency; zero-probability types must never occur; check the flags and the drought water drop.
- AC-15/16/17/18: build fixtures with the world mutation API (cut, take stone, plant, remove plants, remove animals) instead of relying on a player-less default world; compare dog movement per check (world.counters) night/winter vs summer day; compare dog vs rabbit growth proportionally.
- AC-19: build your own list of items from the docs/gameplay.md asset list and check each has an assets.toml entry; check indices in range and the missing section.
- AC-20: load every sprite with SDL_VIDEODRIVER=dummy; check size and pixel colours; grep src/ for "urizen".
- AC-21/22: subprocess the exact commands; AC-22 resume must exit by itself (`resume t1` uses the default resume_ticks).
- Also check: screenshot mode does not change the source run.db (event count and latest snapshot unchanged).
Commands: `uv sync`; `uv run pytest`; `uv run ruff check; uv run ruff format --check`; `$env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png`
#### Report (tester fills this in)
Finished: 2026-11-01 19:15 | Result: Pass (175 passed, 0 failed)
Checklist: [x] AC-1 (test_AC1_uv_sync_and_imports) [x] AC-2 (test_AC2_ruff_clean) [x] AC-3 (test_AC3_package_imports[*], test_AC3_no_pygame_or_ai_sdk_in_world_and_rules) [x] AC-4 (test_AC4_all_configs_load, _wrong_type_fails_naming_file_and_key[10 cases incl. bool-for-int], _unknown_top_level_key_fails[5], _unknown_nested_key_fails[5]) [x] AC-5 (test_AC5_new_creates_db_with_tables) [x] AC-6 (test_AC6_events_are_append_only, test_AC6_storage_api_has_no_event_mutation) [x] AC-7 (test_AC7_resume_equals_uninterrupted[2 cases, differing PYTHONHASHSEED, fresh processes]) [x] AC-8 (test_AC8_full_year_deterministic_and_seed_sensitive) [x] AC-9 (test_AC9_streams_are_independent, test_AC9_stream_state_round_trip) [x] AC-10 (test_AC10_full_year_under_five_minutes: 0.47 s persisted full year, also in logs/ac10_year_seconds.txt) [x] AC-11 (test_AC11_tick_zero, _day_length_and_seasons, _night_follows_config, _simulation_clock_advances) [x] AC-12 (test_AC12_*: size, rotation identity, forest/spring/farmland, centre richer, landmarks+A* reachability, unclaimed land) [x] AC-13 (test_AC13_*, incl. random grids vs Dijkstra) [x] AC-14 (test_AC14_weather_frequencies_over_100_years, _simulated_weather_obeys_odds_support, _flags_and_drought_water) [x] AC-15 (test_AC15_*) [x] AC-16 (test_AC16_plants_only_in_their_seasons, test_AC16_plant_regrows_after_removal[7 kinds]) [x] AC-17 (test_AC17_*) [x] AC-18 (test_AC18_*) [x] AC-19 (test_AC19_*, ~90 concept checks) [x] AC-20 (test_AC20_*) [x] AC-21 (test_AC21_view_screenshot, _view_does_not_write_to_run_db) [x] AC-22 (test_AC22_*)
Tests written: tests/acceptance/conftest.py, test_p1_setup_storage.py (AC1-6), test_p1_determinism_time.py (AC7-11), test_p1_world.py (AC12-18), test_p1_assets_cli.py (AC19-22)
Commands run: `uv run pytest -q 2>&1 | Tee-Object -FilePath logs/phase-1-r0-test.log`; `uv run ruff check; uv run ruff format tests` (tests are lint/format clean)
Failures: none in the final run.
Notes: (1) AC-12 "unclaimed-land pool non-empty": the contract names no pool accessor, so the test only checks that walkable land exists outside the 4 homes and centre. (2) AC-20 "no code reads assets/urizen": src/ai_island/observer/sprites.py:23-24 mentions "urizen" only inside a guard that raises ValueError if assets.toml's sheet.path contains it; I allowed that guard line and fail on any other use, so a literal grep for "urizen" in src/ will hit that one line (manager decides if acceptable). (3) AC-19 matches assets.toml keys by substring against my own list from docs/gameplay.md (key names are not fixed by the contract beyond terrain/plant/animal/landmark keys). (4) Config files have a UTF-8 BOM; the loader copes, tests read with utf-8-sig. (5) AC-7/8 compare events table rows via the CLI in separate processes. Tests create and delete runs/acc_* and recreate runs/t1 and logs/view.png.
Full log: logs/phase-1-r0-test.log
Next steps: none; ready for manager review.

## Round 1
### Debug Task
Assigned: 2026-11-01 19:16 | Failures: Verify (manager) - AC-12 "the unclaimed-land pool is non-empty" / P1-A-07 "the unclaimed-land pool". Command: Grep -i "unclaimed|claimable" over src/ -> no matches. The world has no explicit unclaimed-land pool (docs/design.md "The world" Layout: "A fixed pool of unclaimed land tiles. Claimed land is the main zero-sum prize"; docs/gameplay.md "Land and landmarks"). The R0 test test_AC12 (tests/acceptance/test_p1_world.py) only checks for walkable land outside homes and centre, because the Contract names no accessor (tester Report note 1). | Logs: logs/phase-1-r0-test.log
Find the root cause and owner(s), and give a fix plan that includes the accessor the tester should use (name, type, where it lives in world state and snapshot, size from config).
#### Report (debugger fills this in)
Finished: 2026-11-01 19:18

#### AC-12 unclaimed-land pool missing (AC-12, Work ID P1-A-07)
Owner: coder-a (it needs a short `### Contract change` from the manager first, which names the accessor below; after that the tester tightens test_AC12_unclaimed_land_pool_nonempty)
Root cause: P1-A-07 and AC-12 both require "the unclaimed-land pool", but the Contract gives it no shape (no name, type or config key), and neither plan defined it (in managers/, "unclaimed" appears only in the Claude plan's P1-A-07 line). coder-a never built it. `World.__init__` and `to_state`/`from_state` (src/ai_island/world/state.py:111-254) have no pool field, `generate_world` (src/ai_island/world/mapgen.py:331-419) never computes one, and `MapConfig` (src/ai_island/config.py:104) / world.toml have no land key. test_AC12_unclaimed_land_pool_nonempty (tests/acceptance/test_p1_world.py:120) passes only because it checks for any walkable land outside the homes and centre.
Evidence: Grep -i "unclaimed|claimable|pool" over src/ and config/ found no matches. Scratch script logs/debug/pool_count.py (generate_world for seeds 1-3) printed `has_pool_attr: False`. Land tiles that are not landmarks, per zone, the same for all 3 seeds: `{'buffer': 3804, 'centre': 642, 'home_0..3': 323 each}`. So a pool made of the buffer, or buffer + centre, is large and never empty.
Fix plan:
1. Manager: add a `### Contract change` (the docs do not say which zones count, so this is a spec decision):
   - Config: world.toml new table `[land]` with `pool_zones = ["buffer", "centre"]` (list of str). Add a `LandConfig(Strict)` with `pool_zones: list[str]` as `WorldConfig.land`. A validator rejects an empty list, duplicates and any value other than "buffer" or "centre" (home plots are the players' own land, never in the pool). The error names world.toml and `land.pool_zones`. Use `["buffer"]` instead if the centre is only for holding landmarks and is never claimed. The pool's size is then fixed by the config and the map: 3804 tiles for buffer only, 4446 for buffer + centre (seed 1).
   - Accessor: `World.unclaimed: list[tuple[int, int]]` holds the (x, y) tiles of the fixed pool, sorted row-major (by y, then x). A tile is in the pool when its zone is in `cfg.world.land.pool_zones`, its terrain at generation is not in `terrain.impassable`, and it is not a landmark tile. Also add a pure helper `unclaimed_pool(world) -> list[tuple[int, int]]`, re-exported from `ai_island.world`.
2. coder-a:
   - state.py: add `self.unclaimed: list[Pos] = []` to `World.__init__`.
   - `to_state`: save the pool under the key "unclaimed" as a row mask, for example `["0101...", ...]` with height rows of width chars, '1' meaning in the pool. It must be compact and canonical.
   - `from_state`: restore the pool from that saved mask. Do not recompute it, because in Phase 2 claims will remove tiles. Make sure the shape stays deterministic.
   - mapgen.py `generate_world`: compute the pool once, after `_ensure_corridors` and before the tree counts. It must draw no random numbers, so no stream changes and AC-7/8 event logs stay as they are.
   - Add the `[land]` table to world.toml and LandConfig to config.py.
   - Do not log a new event (the pool does not change in Phase 1).
   - Run ruff and the 1440-tick headless start.
3. Tester (after the fix) should rewrite test_AC12_unclaimed_land_pool_nonempty to check:
   - `len(world.unclaimed) > 0`;
   - every tile's `world.zone_at` is in `pool_zones`;
   - no tile is impassable or a landmark;
   - the list is sorted and has no duplicates;
   - the pool is unchanged after `sim.run(N)`;
   - it is equal after a `snapshot()` / `from_snapshot()` round trip;
   - AC-4 should also cover a bad `land.pool_zones` value.
Confidence: High that the pool is missing and that the cause is the unspecified Contract. Which zones count is a judgement call that the manager has to make.

Debug edits restored: yes (no source file was edited. The only new file is logs/debug/pool_count.py. git status shows only handoffs/phase-1.md)
Other risks noticed:
- tests/acceptance/test_p1_world.py:120 currently passes vacuously, so it hid this gap. Other "contract names no accessor" passes may do the same; the tester's notes 1 and 3 are the ones to check.
- A literal grep of src/ for "urizen" hits a guard line in src/ai_island/observer/sprites.py:23-24 (tester note 2). That guard does not read the file, but the manager should decide whether AC-20 wording allows it.

### Contract change (2026-11-01 19:18)
Unclaimed-land pool (AC-12, P1-A-07), adopting the debugger's R1 fix plan:
- world.toml gets `[land] pool_zones = ["buffer", "centre"]`, validated by `LandConfig` (strict, extra="forbid") at `WorldConfig.land`: non-empty, no duplicates, values only "buffer" or "centre"; errors name world.toml and `land.pool_zones`. Home plots are the players' starting land and are not in the pool; the centre is contested land, so it is in the pool (docs/design.md "The world": "A fixed pool of unclaimed land tiles"; "rich contested centre").
- Accessor: `World.unclaimed: list[tuple[int, int]]` of (x, y), sorted by y then x, no duplicates. A tile is in the pool if its zone is in pool_zones, its generated terrain is passable, and it is not a landmark tile. Helper `unclaimed_pool(world) -> list[tuple[int, int]]`, re-exported from `ai_island.world`.
- Computed once in `generate_world` (after corridors), draws no random numbers, emits no event. Saved in world state (key "unclaimed", compact row-mask form allowed) and restored from the save on load, never recomputed.
- Decision on the AC-20 note: the guard in observer/sprites.py that rejects a sheet path containing "urizen" reads no file, so it satisfies "no code reads any file under assets/urizen/". No change.
Part A folders and Part B folders are unchanged.

### Code Task A
Assigned: 2026-11-01 19:18 | Work IDs: P1-A-15-R1
Debug Report: Round 1 | Root cause and fix plan: see the debugger R1 Report above and the Contract change; build exactly what the Contract change specifies.
Checklist:
- [ ] P1-A-15-R1 unclaimed-land pool: LandConfig + world.toml [land], World.unclaimed + unclaimed_pool(), generation, snapshot save/restore; event logs for a given seed unchanged
#### Report (coder-a fills this in)
Finished: 2026-11-01 19:30 | Status: Done
Checklist: [x] P1-A-15-R1
Files: changed config/world.toml, src/ai_island/config.py, src/ai_island/world/state.py, src/ai_island/world/mapgen.py, src/ai_island/world/__init__.py
What to run: uv run ruff check; uv run ruff format --check; uv run python -m compileall -q src main.py; uv run python main.py headless --ticks 1440 --seed 1; uv run pytest (175 passed)
Contract notes: `[land] pool_zones = ["buffer","centre"]` -> `WorldConfig.land: LandConfig` (validator: non-empty, no duplicates, only buffer/centre; error text names `land.pool_zones`). `World.unclaimed: list[tuple[int,int]]` sorted y then x; `unclaimed_pool(world)` in ai_island.world (mapgen.py) computes it from zone, passability and landmarks. Computed once in generate_world after corridors, no RNG, no event. Saved as key "unclaimed" (row masks of '0'/'1') and restored from the mask in from_state, not recomputed.
Next steps / blockers: none. Tester can tighten test_AC12 and add the bad-pool_zones AC-4 case.

### Test Task
Assigned: 2026-11-01 19:20 | Work IDs covered: P1-A-01 .. P1-A-14, P1-A-15-R1, P1-B-01 .. P1-B-03
Check: AC-1 .. AC-22 exactly as listed under "Acceptance criteria" in the Plan. Re-run the full suite.
Test bug to fix (from the debugger R1 Report): test_AC12_unclaimed_land_pool_nonempty only checks for walkable land outside homes and centre. Rewrite it against the Round 1 Contract change: `unclaimed_pool(world)` / `World.unclaimed` is non-empty; every tile is in a zone listed in world.toml `land.pool_zones`, is passable and is not a landmark; sorted by (y, x) with no duplicates; unchanged after running ticks and after a snapshot save/load round trip. Add to AC-4: a world.toml copy with a bad `land.pool_zones` (empty list, duplicate, unknown zone) fails naming world.toml and `land.pool_zones`.
AC-20 decision: the guard in observer/sprites.py that rejects an "urizen" sheet path is allowed (it reads no file); keep the test as it is.
Commands: `uv sync`; `uv run pytest`; `uv run ruff check; uv run ruff format --check`; `$env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png`
#### Report (tester fills this in)
Finished: 2026-11-01 19:30 | Result: Pass
Checklist: [x] AC-1 .. [x] AC-22 all pass (AC-4: test_AC4_*, incl. new test_AC4_bad_land_pool_zones_fails; AC-12: test_AC12_*, incl. rewritten test_AC12_unclaimed_land_pool_nonempty)
Tests written: test_p1_world.py: test_AC12_unclaimed_land_pool_nonempty (rewritten: non-empty, zones in land.pool_zones, passable, not landmark, sorted by (y,x), no duplicates, equals unclaimed_pool), test_AC12_unclaimed_pool_unchanged_after_ticks, test_AC12_unclaimed_pool_survives_snapshot_round_trip; test_p1_setup_storage.py: test_AC4_bad_land_pool_zones_fails (empty, duplicate, unknown zone; names world.toml and land.pool_zones)
Commands run: uv run ruff format tests; uv run ruff check tests; uv run pytest 2>&1 | Tee-Object -FilePath logs/phase-1-r1-test.log
Failures: none (180 passed). The separate view --screenshot command was not run by hand; AC tests for it are in the suite.
Full log: logs/phase-1-r1-test.log
Next steps: none

## Summary
Phase 1 is done (2026-11-01 19:23). The island now exists and lives on its own: weather and seasons change, plants grow back, animals breed and wander, and wild dogs roam in packs. A whole game year runs in under a second with no window, and the same seed always gives exactly the same history. Every game is saved in its own database file, and a saved game can be continued later with `resume`. The map window works. Things to watch when you look at it yourself: the lake shows as a solid black block, and a few animal pictures (goat, chicken, boar) are the closest matches the art pack has. Nothing cost money.

Technical: Round 0 built Part A (P1-A-01..14: uv project, strict config with ConfigError naming file and key, hashlib named RNG streams, storage schema v1 with append-only + duplicate-id triggers, typed events, snapshots with watermark and pinned config, clock/tick loop/Simulation, rotated-home map + A*, weather, resources, plants, animals, dogs, WorldFrame, CLI) and Part B (P1-B-01..03: assets.toml with 126 items incl. a missing/code set, sprite loader recolouring to black on white with binary alpha, Viewer). Tester R0: 175 passed. Manager verify found the unclaimed-land pool missing (Contract had never defined it); Round 1 added a Contract change (world.toml [land] pool_zones, World.unclaimed, unclaimed_pool(), saved as a row mask) and P1-A-15-R1; the tester tightened AC-12 and added an AC-4 case. Final: 180 passed in ~14 s; ruff clean; build, start, resume and screenshot commands exit 0; full persisted year ~0.5 s (AC-10). AC evidence: tester R1 Report (test_AC<n>_* per criterion). AC-20 note: observer/sprites.py has a guard that rejects an urizen sheet path; it reads no file (accepted).
### Planning outcome
- Codex ideas: adopted 1, 2, 3, 4, 5; rejected none; taken against the reviewer's verdict: none (2, 3, 5 were Maybe, conditions met); adopted ideas that caused problems: none
- Codex compatibility: adopted all nine findings (schema v1, full checkpoints, controller-owned ticking, equal weather intervals, rotated full home state, UI concept icons, recolouring, Windows install check, strict config); rejected the persisting view/resume semantics (Decisions 7-8) and periodic autosave in Phase 1 (Decision 11); issues later found in areas it checked: none
- Claude: neither plan defined the unclaimed-land pool concretely (my plan named it only in a Work ID), which caused Round 1

## Round 2
### Plan note (2026-11-01 19:50)
Tim's review after Done (phases.md Phase 1 Notes, "Tim's review"): "It's too blurry, and nothing seems to be moving." Phase 1 is reopened for this round; no test failed, so there is no Debug Task: the manager read viewer.py and cli.py and found the causes directly.
- Blur: Tim's screen is 3200x2000 (likely 200% Windows scaling). The window is a fixed 1280x800 at scale 1 (16 px tiles), the grass tile is a dense dither that reads as grey noise at that size, and DPI awareness is only requested via ctypes after import pygame (SDL may still be scaled by Windows).
- Not moving: the live loop is correct but runs at speed 1 (0.36 s per game minute); animals move every 90-180 ticks, so on screen almost nothing changes. phases.md asks for pacing "scaled by a speed setting"; there is no way to change speed while watching.
Contract additions (both coders build to these):
- run.toml `[view]` (coder-a, ViewConfig strict): add `min_visible_tiles = 36` (int > 0), `max_speed = 512.0` (float >= speed), `window_margin = 80` (int >= 0, pixels left free for taskbar/title bar). `window_width`/`window_height` stay as the fallback size when the desktop size is unknown (dummy driver).
- Viewer (coder-b): before `pygame.init()` set `os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")` and call the ctypes awareness first; window size = desktop size from `pygame.display.get_desktop_sizes()[0]` minus window_margin on each axis (fallback to window_width/height when that is unavailable or under the dummy driver); scale = largest whole number <= max_scale at which at least min_visible_tiles tiles fit along the window's shorter side (minimum 1), arrow keys scroll when the map does not fit; still whole-number scaling only. New property `Viewer.speed: float` starting at `view.speed`; in `pump()` the + / = / keypad-plus keys double it and - / keypad-minus halve it, clamped to [view.speed / 8, view.max_speed]; the title shows the speed, e.g. `AI Island - Year 1, Spring, week 1, day 1, 06:00 - speed x16`.
- CLI live loop (coder-a): use `viewer.speed` each iteration instead of `view.speed` (seconds per tick = view.seconds_per_tick / viewer.speed); the catch-up cap must allow the max speed to keep up (ticks owed per frame at max_speed and fps).
- Assets (coder-b): grass must read as mostly white with sparse marks (Pokemon Red style): pick a lighter Kenney tile or make grass a `code` item (then also list it in `[missing]`). Terrain must stay readable at scale 2-3.
Part A folders and Part B folders are unchanged.

### Code Task A
Assigned: 2026-11-01 19:50 | Work IDs: P1-A-16-R2
Debug Report: none (Tim's review; see the Plan note above).
Checklist:
- [ ] P1-A-16-R2 ViewConfig + run.toml new keys (min_visible_tiles, max_speed, window_margin); CLI live loop uses viewer.speed with a catch-up cap that keeps up at max_speed
#### Report (coder-a fills this in)
Finished: 2026-11-01 20:05 | Status: Done
Checklist: [x] P1-A-16-R2
Files: changed config/run.toml, src/ai_island/config.py (ViewConfig + validator max_speed >= speed), src/ai_island/cli.py (live loop uses viewer.speed each iteration; catch-up cap = max(5000, max_speed/seconds_per_tick + 1), about 1422 ticks, so max speed keeps up)
What to run: uv run pytest; uv run python main.py view <run> (needs coder-b's Viewer.speed)
Contract notes: cli reads `viewer.speed` (float property) from coder-b's Viewer. Ruff and the full suite were clean (180 passed) at my last run; a transient F821 (os undefined) in observer/viewer.py was seen mid-edit by coder-b and had cleared by the final run.
Next steps / blockers: none

### Code Task B
Assigned: 2026-11-01 19:50 | Work IDs: P1-B-04-R2, P1-B-05-R2
Debug Report: none (Tim's review; see the Plan note above).
Checklist:
- [ ] P1-B-04-R2 Viewer: SDL DPI hint + ctypes before pygame.init, window sized from the desktop minus margin, scale from min_visible_tiles, Viewer.speed with +/- keys, speed in title. On this machine (real display, not dummy) briefly open the Viewer and report get_desktop_sizes()[0], the window size and the chosen scale (expected desktop 3200x2000 when DPI-aware).
- [ ] P1-B-05-R2 grass tile mostly white with sparse marks (lighter Kenney tile or code drawing + [missing])
#### Report (coder-b fills this in)
Finished: 2026-11-01 19:55 | Status: Done
Checklist: [x] P1-B-04-R2 [x] P1-B-05-R2
Files: changed src/ai_island/observer/viewer.py, src/ai_island/observer/code_art.py, config/assets.toml
What to run: uv run ruff check; uv run ruff format --check; uv run python -m compileall -q src main.py; uv run pytest (180 passed); $env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png (exit 0)
Contract notes: Real-display probe on this machine (SDL windows driver): get_desktop_sizes() = [(3200, 2000), (1920, 1080), (1920, 1080)], so [0] = 3200x2000 (DPI-aware as expected). Window = 3120x1920 (margin 80). Chosen scale = 3 (1920 // 48 = 40 tiles on the short side >= 36). Viewer.speed starts at view.speed; +/=/keypad-plus doubles, -/keypad-minus halves, clamped to [view.speed/8, view.max_speed]; title ends "- speed x<g-format>". Dummy driver falls back to window_width/height. Grass is now a code item (source = "code", listed in [missing]): white tile with two sparse 3-pixel tufts (6 black pixels). Viewer reads view.min_visible_tiles, max_speed, window_margin from coder-a's ViewConfig (present in config.py). Note for the manager: in the dummy screenshot the island looks hatched because rain was active at tick 600 (overlay_rain diagonal streaks on every tile), not because of grass; the rain overlay is dense at small scale and could be thinned later if Tim finds it noisy. Screenshot at dummy 1280x800 now uses scale 1 (36 tiles needs scale <= 2 at 800 px; 800//32 = 25 < 36), so the whole map no longer fits there and the view starts at the top-left.
Next steps / blockers: none

### Plan note (2026-11-01 19:54)
coder-b's probe shows the process was already DPI-aware (desktop 3200x2000), so the blur Tim saw came from the tiny scale-1 tiles plus noisy textures. coder-b also reports that the rain overlay draws diagonal streaks on every tile, which reads as hatching/fuzz. Added to this round: thin the weather overlays.

### Code Task B (addendum)
Assigned: 2026-11-01 19:54 | Work IDs: P1-B-06-R2
Checklist:
- [ ] P1-B-06-R2 rain and storm overlays sparse and readable at scale 2-3: streaks on only some tiles (a fixed position-based pattern, e.g. about one tile in four, no random numbers), storm a little denser than rain; night overlay must leave the map readable. Overlays stay 1-bit (black/transparent) on the 16x16 grid. Save a dummy-driver screenshot at a tick with rain (logs/view-rain.png) and say in the Report how the overlays look.
#### Report (coder-b fills this in; replace only the placeholder below)
Finished: 2026-11-01 20:10 | Status: Done
Checklist: [x] P1-B-06-R2
Files: changed src/ai_island/observer/code_art.py, src/ai_island/observer/viewer.py
What to run: uv run ruff check; uv run ruff format --check; uv run pytest (180 passed); $env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view-rain.png
Contract notes: none. Rain overlay: 3 diagonal 3-pixel streaks per tile, drawn only on tiles where (x*3 + y*5) % 4 == 0 (about 1 tile in 4). Storm: 6 streaks plus the bolt, on (x*3 + y*5) % 3 == 0 (about 1 in 3). Night overlay: dots now every 4th pixel in both directions (1 in 16, was 1 in 4). All 1-bit, no random numbers. Screenshot logs/view-rain.png (tick 600, rain): island reads clearly, trees and items distinct, rain is light scattered diagonal ticks, no hatching. I did not view a night or storm frame.

### Test Task
Assigned: 2026-11-01 19:56 | Work IDs covered: all Phase 1 Work IDs incl. P1-A-16-R2, P1-B-04-R2, P1-B-05-R2, P1-B-06-R2
Check: AC-1 .. AC-22 exactly as listed under "Acceptance criteria" in the Plan; re-run the full suite. Add checks for the Round 2 Plan note (SDL_VIDEODRIVER=dummy): run.toml [view] has min_visible_tiles, max_speed, window_margin and a wrong type or max_speed < speed fails naming run.toml and the key; Viewer.speed starts at view.speed, doubles on a posted + key event and halves on -, clamped to [view.speed/8, max_speed]; the title contains "speed x"; with the dummy driver the window falls back to window_width x window_height and the scale is a whole number >= 1; the grass sprite is mostly white (at most 16 black pixels); `grass` is listed in assets.toml [missing]. AC-20/21 still hold for all sprites.
Commands: `uv sync`; `uv run pytest`; `uv run ruff check; uv run ruff format --check`; `$env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png`
#### Report (tester fills this in)
Finished: 2026-11-01 20:08 | Result: Pass
Checklist: [x] AC-1..AC-22 (existing tests, all pass) [x] R2: run.toml new keys + bad type/range fail naming run.toml and key (test_AC4_run_toml_view_has_round2_keys, test_AC4_bad_view_value_fails_naming_file_and_key x6) [x] Viewer.speed start/double/halve/clamp (test_AC21_viewer_speed_*) [x] title "speed x" + dummy window fallback + scale int >= 1 (test_AC21_title_shows_speed_and_dummy_window_fallback) [x] grass <= 16 black px and in [missing] (test_AC20_grass_mostly_white_and_listed_missing); AC-20/21 sprite tests still pass
Tests written: tests/acceptance/test_p1_r2_viewer.py (12 tests)
Commands run: uv sync; uv run ruff format tests; uv run ruff check tests; uv run pytest 2>&1 | Tee-Object logs/phase-1-r2-test.log; $env:SDL_VIDEODRIVER='dummy'; uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png (exit 0); uv run ruff check; uv run ruff format --check (both clean)
Failures: none (192 passed). Note: the scale check reads the private Viewer._scale since the contract has no public accessor.
Full log: logs/phase-1-r2-test.log
Next steps: none

### Round 2 addendum (2026-11-01 19:59)
After the first Done, Tim found the map window blurry and still. Round 2 fixed both: the window now fills the screen with tiles drawn three times bigger, the grass is plain white with a few marks, rain and night are drawn lighter, and the + and - keys speed the island up (up to 512 times) or slow it down. The speed is shown in the window title.
Technical: no Debug Task (review feedback, not a failing test; causes read directly from viewer.py/cli.py). P1-A-16-R2 (ViewConfig min_visible_tiles/max_speed/window_margin; CLI live loop uses Viewer.speed, catch-up cap 5000), P1-B-04-R2 (SDL permonitorv2 hint, window = desktop minus margin, scale from min_visible_tiles -> 3 on Tim's 3200x2000 screen, Viewer.speed +/- keys), P1-B-05-R2 (grass as code art, listed in [missing]), P1-B-06-R2 (sparse rain/storm/night overlays). Process was already DPI-aware (desktop reported 3200x2000), so the blur was tiny scale + noisy textures. Tester R2: 192 passed. Verify: ruff clean, build and start OK, diff within Part folders/tests/handoffs/memory. The phase-1-done tag marks the first Done; the final state is tagged phase-1-done-r2.
- Claude (planning outcome addition): neither plan sized the viewer for Tim's 3200x2000 screen or gave a way to change speed while watching; "whole-number scaling" alone was not enough.
