# Phases

The manager reads only the section for the phase being started. Each phase is built
from `docs/build-phases.md` (the original checklists) and the docs it points to; the
acceptance criteria below are what the tester checks. "Tim's review" items under Notes
are done by Tim after the phase is Done and are not tester criteria.

Rules for every phase:
- Every earlier phase's tests keep passing, and the determinism test (same seed, same
  event log) runs at the end of every phase.
- Code, config and their names follow `Overview.md` (folder layout, constraints).
- Packages that a later phase fills contain only an `__init__.py` with a one-line
  docstring naming their job. No stub functions, fake values or TODOs (Definition of
  Done item 6).
- No agent runs a command that makes a real AI call or spends money.

## Phase 1: Skeleton and the island

### Goal
The full code skeleton, config, storage with every table, and a living island with no
players that runs a full game year deterministically, headless or in a read-only map
viewer. Cost: $0.

### Requirements
- uv project in the repo root: `pyproject.toml` (Python 3.13, `requires-python =
  ">=3.13,<3.14"`, a build backend so `uv sync` installs the `ai_island` package from
  `src/`), `.python-version`, pinned versions in `uv.lock`; ruff and pytest configured
  in `pyproject.toml`.
- Install every runtime library the project will use now, so install problems show up
  early: pygame-ce, pygame_gui, pydantic, python-dotenv, anthropic, openai,
  google-genai, mistralai, ollama. Dev: pytest, ruff. The AI SDKs are not imported by
  any module until Phase 4.
- Package layout from `Overview.md`: `src/ai_island/` with `world/`, `rules/`,
  `minds/`, `llm/`, `measure/`, `observer/`, `storage/` and `cli.py`; `main.py` in the
  root calls `ai_island.cli`.
- Config: `config/world.toml`, `balance.toml`, `models.toml`, `run.toml` and
  `assets.toml`, each checked by a Pydantic model (`extra="forbid"`) on load.
  `models.toml` holds only its schema-valid structure and the embedding model name
  (`nomic-embed-text`) until Phase 4 fills in the nine roles; no invented model names.
- Seeded random streams, one per subsystem (weather, plants, animals, dogs, map,
  combat, and so on), derived from the run seed and the stream name with hashlib;
  stream positions are part of every snapshot.
- `main.py` commands: `new <run> [--seed N]`, `resume <run>`,
  `headless --ticks N [--run <run>] [--seed N]`, `view [--run <run>]`, plus
  `view --ticks N --screenshot <png>` that renders without user input and saves one
  frame (for tests and quick checks).
- Storage: one SQLite database per run at `runs/<run>/run.db` with all eight tables
  from `docs/architecture.md` created now: events, ai_calls, choice_points,
  judge_labels, chats, value_history, spend, snapshots. Columns for the later tables
  follow `docs/architecture.md` ("Everything is recorded") and the choice point record
  in `docs/design.md`. The events table rejects UPDATE and DELETE (SQLite triggers).
- Append-only event log of typed events (Pydantic models: tick, type, payload).
- Snapshot save and load of the full world state and every random stream's position.
- Tick loop: 1 tick = 1 game minute. Headless runs unpaced; live mode paces to 0.36 s
  per tick, scaled by a speed setting.
- Clock: days, day and night, 4 seasons of 2 game weeks each (from `world.toml`), so a
  game year is 8 game weeks = 80,640 ticks.
- Map generated from the seed, 80 x 80: one home plot (small forest, spring, farmland
  patch) designed once and rotated into the four corners; buffer land; the contested
  centre with a large forest, the quarry, the best farmland and the lake; the three
  landmarks (quarry, lake dock, great tree); coast; the unclaimed-land pool. See
  `docs/design.md` "The world" and `docs/gameplay.md` "Land and landmarks".
- A* pathfinding over the tile grid with terrain costs from config.
- Weather by season odds (clear, rain, storm, drought), exposed as flags later phases
  read: stops outdoor work, puts out campfires, cuts water.
- Resources: trees regrow slowly and can be over-cut; stone is finite (quarry and
  loose stone on rocky tiles); water is seasonal and drops in drought; farmland soil
  states (empty, planted, growing, ready, failed) with crop growth that fits inside a
  2-week season.
- Plants: berries, mushrooms, roots, herbs, healing herbs, mild poison, strong poison,
  each with seasons and regrowth.
- Animals: rabbits, deer, boar, fish, birds and nests, goats, chickens. Populations
  breed by season, move, flee (from dogs for now) and can die out locally.
- Wild dogs: packs of 2-4 in the buffer and centre forests, more active at night and
  in winter, slow breeding. In this phase they roam and breed; attacks come in Phase 2.
- `config/assets.toml` maps every item on the asset list in `docs/gameplay.md` to a
  tile in `assets/kenney_1bit/Tilesheet/monochrome-transparent.png` (16 x 16 tiles,
  1 px gap, 49 x 22 tiles), or marks it `code`. Items the Kenney pack doesn't have are
  listed in a `missing` section and drawn in code as simple 1-bit shapes on the 16 x 16
  grid. No other tile pack is used (ignore `assets/urizen/` if it exists).
- Asset loader in `observer/`: every Kenney tile cut from the sheet and drawn as black
  on a white background at whole-number scale, never stretched; code-drawn items use
  the same 16 x 16 grid and two colours.
- `main.py view`: read-only pygame-ce window showing the map, plants, animals, dogs,
  weather and night overlays, with the game clock, day and season in the title bar.
  DPI-aware on Windows, whole-number scaling, and the whole island reachable (fits
  or scrolls with the arrow keys). No tabs yet.

### Acceptance criteria
- AC-1: `uv sync` succeeds, and `uv run python -c "import pygame, pygame_gui, pydantic, dotenv, anthropic, openai, google.genai, mistralai, ollama"` exits 0; `pygame.IS_CE` is true.
- AC-2: `uv run ruff check` and `uv run ruff format --check` report no errors.
- AC-3: The packages `ai_island.world`, `.rules`, `.minds`, `.llm`, `.measure`, `.observer`, `.storage` import; no module under `world/` or `rules/` imports pygame, pygame_gui or any AI SDK (checked by scanning imports with ast).
- AC-4: Each config file loads into its Pydantic model; a copy with an unknown key or a wrong type fails at load with an error naming the file and the key.
- AC-5: `uv run python main.py new t1 --seed 1` creates `runs/t1/run.db` containing the tables events, ai_calls, choice_points, judge_labels, chats, value_history, spend and snapshots.
- AC-6: An UPDATE or DELETE on the events table raises an error; the storage API offers no way to change or remove an event.
- AC-7: Snapshot round trip: run T ticks, save, load into a fresh process, run M more ticks; the event log equals that of an uninterrupted run of T + M ticks with the same seed.
- AC-8: Two headless runs of a full game year (80,640 ticks) with the same seed produce identical event logs; a different seed produces a different log.
- AC-9: Drawing extra numbers from one named stream does not change the numbers produced by any other stream.
- AC-10: A headless full game year finishes in under 5 minutes on Tim's laptop (the tester records the time).
- AC-11: Clock: tick 0 is day 1, spring, week 1; a day is 1440 ticks; the season changes every 14 game days (spring weeks 1-2, summer 3-4, autumn 5-6, winter 7-8); tick 80,640 is spring of year 2; day and night follow `world.toml`.
- AC-12: The map is 80 x 80; the four home plots are identical once each is rotated into the same orientation; each has a forest, a spring and farmland; the centre has more trees, farmland and stone than any home plot; the quarry, lake dock and great tree are in the centre; every landmark and every other home is reachable from every home by A*; the unclaimed-land pool is non-empty.
- AC-13: A* returns the lowest-cost path on a small hand-made grid with terrain costs, and no path when the goal is unreachable.
- AC-14: Over many simulated years, each weather type's frequency per season is within a stated tolerance of the odds in `world.toml`; storms set the stop-outdoor-work and put-out-campfires flags; drought lowers water output.
- AC-15: A cut tree regrows over time; an area cut below the over-cutting threshold in config does not regrow; quarry stone never increases; spring and lake water are lower in drought; a crop planted in spring reaches ready within one season; crops cannot grow in winter.
- AC-16: Each of the seven plant types appears only in its configured seasons and regrows after being removed.
- AC-17: Animal populations grow in their breeding seasons; an animal type reduced to zero in an area stays absent there for at least the configured time; bird nests with eggs exist only in spring.
- AC-18: Wild dogs start in packs of 2-4 only in buffer and centre forests; they move more at night and in winter than by day in summer; their population grows more slowly than rabbits'.
- AC-19: `config/assets.toml` has an entry for every item on the `docs/gameplay.md` asset list (pack and tile index, or `code`), every tile index is inside its sheet, and missing items are listed.
- AC-20: Every loaded sprite (Kenney tile or code drawing) is a 16 x 16 surface using only black, white and transparency, and no code reads any file under `assets/urizen/`.
- AC-21: With `SDL_VIDEODRIVER=dummy`, `uv run python main.py view --run t1 --ticks 600 --screenshot logs/view.png` exits 0, loads every mapped sprite without error and writes a PNG.
- AC-22: `uv run python main.py headless --ticks 1440 --seed 1` exits 0 and prints the final game time; `uv run python main.py resume t1` continues from the latest snapshot.

### Depends on
The manual setup in `docs/setup.md` (uv, Python 3.13, git, assets in `assets/`).

### Notes
- Tim's review: run `uv run python main.py view` and watch the island change through
  seasons and weather with every sprite in place, sharp at his display scaling.
- The monogram font is not needed until Phase 3.
- Phase 1.5 changes the look to colour and adds Tiny Creatures for the animals. The
  black-and-white rules above (the monochrome sheet, the black-on-white loader and
  AC-20) now hold only with `palette = "mono"`, and AC-18 is checked through Phase
  1.5 AC-4.
- No AI calls in this phase. Cost: $0.

## Phase 1.5: Colour and time-true movement

### Goal
The map viewer in colour, with animals from Tiny Creatures, and movement and light
that follow the game clock: every moving thing has a speed in game minutes per tile,
moves on its own schedule and is drawn sliding between tiles, and daylight changes
smoothly with the hour. Same seed, same event log. Cost: $0.

### Requirements
Read `docs/gameplay.md` (Asset list), `docs/design.md` (Look), `docs/architecture.md`
(Observer screen) and the Phase 1 handoff Summary. Why this phase exists: at speed x1
the clock moves every 0.36 s, but each animal kind is checked only every 90-180 game
minutes (32-65 real seconds), every animal of a kind jumps on the same tick, dog packs
jump together every 20 ticks, sprites snap from tile to tile, and night switches on
in one tick at 20:00.

Movement (`world/`, no pygame):
- New `world/movement.py`. Every moving kind (each animal kind, wild dogs) has in
  `balance.toml`, each with a one-line reason comment: `minutes_per_tile`,
  `flee_minutes_per_tile` (animals that flee), a wander bout length in tiles (min,
  max) and a rest between bouts in game minutes (min, max). These replace
  `move_interval` and `move_chance` for animals and dogs. Dogs' night and winter
  multipliers now shorten rest and minutes_per_tile instead of raising a move chance.
- Starting values to propose (with reasons, tuned so that at x1 an active animal
  moves about once a real second): rabbit 3, deer 3, boar 5, goat 6, chicken 6,
  birds 2, fish 8 minutes per tile; dogs 4 by day and 2-3 at night; bouts of 2-6
  tiles; rest 20-120 game minutes. Nests with eggs don't move.
- Each animal and dog keeps its own `next_move_tick` and, for the step in progress,
  `from_x`, `from_y`, `move_start_tick`, `move_end_tick`. First moves are staggered
  from the `animals` / `dogs` streams so no two individuals start in lockstep. All of
  it is saved in snapshots.
- One movement job runs every `movement_step_ticks` (balance.toml) and advances only
  the individuals that are due, in id order. The tile changes when a step ends.
  Habitat, zone and home-plot limits stay as in Phase 1. No per-step events are
  logged (as in Phase 1).
- The module is written so Phase 2 can move players and villagers with it (walk
  minutes per tile x terrain cost from `world.toml`; "Moving takes a destination and
  lasts the walk", `docs/gameplay.md`).
- Snapshot schema version goes up by one. Restoring an older snapshot fails with a
  message naming both versions (old runs are recreated, not migrated).

Viewer timing (`world/view.py`, `observer/`, `cli.py`):
- `WorldFrame` carries, for every moving entity, from and to tile and
  move_start / move_end tick. The live loop passes the viewer a `sub_tick` fraction
  (0-1, from the time owed to the next tick). The viewer draws each moving sprite
  between its two tiles at that progress, snapped to whole sprite pixels (multiples
  of the scale), so it stays sharp. This is drawing only and never changes the world.
- Frame pacing subtracts the time spent drawing (target `fps` from `run.toml`). The
  terrain layer is cached and redrawn only when terrain, season, weather or scale
  changes. The title shows the measured frames per second next to the speed.

Colour and assets (`config/assets.toml`, `observer/`):
- `assets.toml` lists two sheets: `[sheets.kenney]` =
  `assets/kenney_1bit/Tilesheet/colored-transparent.png` (same 16 x 16 tiles, 1 px
  gap, 49 x 22 layout and the same col/row for every item as the black-and-white
  sheet; checked: every mapped tile's shape matches) and `[sheets.tiny_creatures]`
  for the Tiny Creatures pack in `assets/tiny_creatures/` (the coder opens the
  download, finds its sheet or sprite files and records path, tile size, gap and
  layout; if it ships separate PNGs, each item names its file instead of col/row).
  Each item says `source = "kenney" | "tiny_creatures" | "code"`.
- Tiny Creatures is used for every animal on the asset list it has a good match for,
  chosen by eye with a short comment per pick: at least rabbit, deer, boar, goat,
  chicken, birds, fish and wild dog are checked against it. Nest with eggs and every
  other item stay with Kenney or code. Items neither pack has stay `code` and in
  `[missing]`.
- `palette = "color" | "mono"` in `assets.toml` (default `color`). Colour mode keeps
  each sprite's own colours (Kenney's 8-colour palette, Tiny Creatures' own colours).
  Mono mode is the Phase 1 look: every sprite black on white, Tiny Creatures included.
- `[colors]` in `assets.toml` (hex, checked by the Pydantic model): background
  (`#472d3c`, from Kenney's `colored.png`), a ground colour for every terrain kind
  drawn under its tile, one colour per player 1-4 (Phase 2 uses them for the player
  sprite, its villagers and its land border), and an ink colour for every code-drawn
  item. Code drawings use only Kenney palette colours.
- Light follows the clock: a smooth daylight curve from the `world.toml` night hours
  plus new `dawn_minutes` and `dusk_minutes` keys, drawn as one full-screen tinted
  layer (not one blit per tile). Rain and storm darken it. `is_night` and every world
  rule that uses it (dogs) stay exactly as they are.
- Seasons in colour: autumn trees and bushes use the orange and yellow palette
  entries, winter keeps snow, drought yellows the grass ground.
- Docs: none to change; Tim updated `docs/gameplay.md`, `docs/design.md`,
  `docs/setup.md`, `docs/build-phases.md` and `docs/architecture.md` before the phase.

### Acceptance criteria
- AC-1: Every moving kind has minutes_per_tile, bout and rest keys with reason comments in `balance.toml`; a missing, zero or negative value fails at load naming the file and key.
- AC-2: Over one game day, no single tick starts a step for more than 25% of any kind's individuals (no lockstep jumps).
- AC-3: Over a game week, each kind's average tiles per game hour matches what its minutes_per_tile, bout and rest values give, within a stated tolerance; a fleeing animal steps faster than a wandering one.
- AC-4: Dogs move more tiles per game hour at night and in winter than on summer days (the Phase 1 AC-18 property still holds).
- AC-5: A step that starts at tick T with minutes_per_tile M ends at T + M; the entity's tile changes only when the step ends; animals stay in their habitat and zone, and dogs stay out of home plots.
- AC-6: Snapshot round trip in the middle of a step gives the same event log as an uninterrupted run (the Phase 1 AC-7 test); an older-version snapshot is refused with a message naming both versions.
- AC-7: Same seed gives identical full-year event logs, a different seed a different one; a headless full game year still finishes in under 5 minutes (time recorded).
- AC-8: `WorldFrame` gives from, to, start and end for every moving entity; with sub_tick 0, 0.5 and 1 the viewer places the sprite at the start tile, at the whole-pixel midpoint and at the end tile.
- AC-9: `assets.toml` has an entry for every `docs/gameplay.md` asset-list item with source `kenney`, `tiny_creatures` or `code`; every Kenney index is inside its sheet; every Tiny Creatures entry points to an existing file and tile; every `code` item is in `[missing]`.
- AC-10: Rabbit, deer, boar, goat, chicken, birds, fish and wild dog each either use a Tiny Creatures sprite or have a comment saying why not.
- AC-11: In colour mode the Kenney sheet is `colored-transparent.png`, and each mapped Kenney tile's opaque shape equals its shape in `monochrome-transparent.png`.
- AC-12: Every loaded sprite is 16 x 16; in colour mode Kenney tiles and code drawings use only the 8 Kenney palette colours and transparency; in mono mode every sprite uses only black, white and transparency (Phase 1 AC-20, now checked in mono mode).
- AC-13: `[colors]` has a ground colour for every terrain kind, four different player colours and an ink colour for every `[missing]` item; a bad hex value fails at load naming the key.
- AC-14: The light layer is clear at 12:00, darkest between the end of dusk and the start of dawn, and changes steadily through dawn and dusk; `is_night_at()` gives the same results as in Phase 1.
- AC-15: Autumn tree tiles use the autumn colours, winter shows snow, and drought changes the grass ground colour.
- AC-16: With `SDL_VIDEODRIVER=dummy`, `main.py view --run t1 --ticks 600 --screenshot logs/view.png` exits 0 in both palette modes and loads every sprite; screenshots at 12:00 and 22:00 differ in mean brightness by a stated margin.
- AC-17: No code reads any file under `assets/urizen/`, and `git diff --name-only phase-1.5-start -- assets/` is empty.
- AC-18: The `world/` and `rules/` import scan still passes (`movement.py` imports no pygame).
- AC-19: All Phase 1 tests pass (AC-18 through this phase's AC-4, AC-20 through AC-12 in mono mode), and ruff reports no errors.

### Depends on
Phase 1. Tim has unzipped Tiny Creatures into `assets/tiny_creatures/` and committed
it (`docs/setup.md` step 3.2).

### Notes
- Tim's review: run `uv run python main.py new t1 --seed 1` again first (old saves
  can't be loaded after this phase), then `uv run python main.py view --run t1`. At
  speed x1 animals should amble on their own timing and slide between tiles, the
  light should fade at dusk and return at dawn, and the animals should be the Tiny
  Creatures sprites. Then set `palette = "mono"` in `config/assets.toml` to see the
  old black-and-white look, and set it back.
- No AI calls in this phase. Cost: $0.

## Phase 2: Bodies, villagers, actions and senses

### Goal
The complete game played by rule-based and scripted players: everything except the
AI minds. Cost: $0.

### Requirements
Read `docs/design.md` (Wellbeing X; Villagers, senses, chat and harm; Learning from
mistakes) and all of `docs/gameplay.md`.
- Bodies: needs (hunger, thirst, cold, rest), sickness (mild and strong poison, raw
  or spoiled meat), injury.
- The X formula from `docs/design.md`: a concave f per input, weights from
  `balance.toml`, adaptation B with a half-life.
- Every number in `balance.toml` proposed with a one-line reason comment, aimed at
  these targets with dummy players: X mostly 60-79 in week 1; home resources running
  short around weeks 2-3; X below 40 in winter for players without food stores;
  villagers leaving only after several days of hunger or hard work. Starting points:
  adaptation half-life 2 game days, villager loyalty starting at 70, leaving below 30.
- Feeling bands as words (the table in `docs/design.md`), speed and work multipliers
  per band, the hooked flag (X below 40 or high pain).
- Trust and anger toward every other player, fading over time.
- Death and respawn: back home, carried items dropped where the player died, -10 X.
- Villagers: 3 per player at start, a wanderer pool, an island cap of 50, no births;
  needs, health, loyalty (fed, safe, not overworked) and a bond with every player,
  separate from loyalty; jobs (gather, farm, guard, build, tend animals) and work
  levels (light, normal, hard); leaving, joining another player, wandering off,
  death, grief scaled by bond; short scripted lines; gossip only about players and
  only about what they saw or heard.
- Every action in the `docs/gameplay.md` list, each with a duration in game minutes
  from `balance.toml` (changed by tools, X and weather); work and rest actions take
  an amount or an end point; moving takes a destination; an interrupted action keeps
  the progress made so far.
- Interrupt events raised by the rules, ready for Phase 4's decision triggers: spoken
  to, attacked or hurt, a player or dog comes into sight, a storm starts, a loss
  noticed, a feeling band changes.
- Tools (basic and better recipes, half speed by hand, pickaxe required at the
  quarry, wear, repair at half price, dropping, stealing, trading), fire (campfire and
  hearth, 6 hours of fuel, cooking, warmth, light, scaring dogs, rain puts out
  campfires only), buildings (house, field, storehouse, workshop, pen, granary,
  bridge, monument, shrine; storm damage and repair), care, social (talk, barter
  trade with both sides agreeing, gift, promise recorded so keeping or breaking it can
  be checked, ally, recruit, teach), protect (guard), harm (steal, sabotage, attack,
  chase off, claim land with boundary stakes, pull stakes, capture or poach
  villagers), belief (pray, ceremony, shrine, offering: logged, no mechanical effect).
- Wild dogs now attack lone villagers, penned animals and unarmed players.
- Simultaneous resolution: clashes settled by the seeded generator; player order
  rotates every tick.
- Tasks: five stages, hidden per player, with unlocks and rewards (stage 1 gives a
  set of basic tools); the cooperative bonus for joint projects; the dominance bonus
  for holding a landmark for a week; land claims with border patterns; the
  landmark-holding rule.
- Senses (the Discoverer): sight about 7 tiles (less at night and in storms), hearing
  about 5, body feelings as words, memory of place that can go out of date; sense
  reports as short text from varied templates; witness records; the chat phase (talk
  only to someone in sight, overheard within hearing range); the knowledge book data
  model (entries with confidence).
- Test players in `minds/`: four rule-based dummy players that only follow their
  needs, and scripted players that use every action at least once.
- `main.py report --run <run>` prints the balance metrics used in AC-29.
- The map viewer shows players and villagers. They walk with the Phase 1.5 movement
  module (walk minutes per tile x terrain cost) and are drawn in their player's colour
  from `assets.toml` `[colors]`, as are land borders.

### Acceptance criteria
- AC-1: Hunger and thirst rise at the configured rates and fall when eating and drinking; cold rises at night and in winter outside shelter without fire; rest restores; mild poison, strong poison, raw meat and spoiled meat cause their configured sickness; strong poison can kill a villager or a player.
- AC-2: X = sum of w_i * f_i(c_i) + B with weights from `balance.toml`; every f_i is concave (equal steps give shrinking gains); B halves after the configured half-life with no new events; X stays within 0-100.
- AC-3: Every value in `balance.toml` has a one-line reason comment; the half-life is 2 game days, villager loyalty starts at 70 and villagers leave below 30.
- AC-4: Feeling words, speed and work multipliers match the `docs/design.md` table for each X band; a player is hooked exactly when X is below 40 or pain is at or above the configured threshold.
- AC-5: Every player holds trust and anger toward every other player, and both fade toward neutral at the configured rate.
- AC-6: A player who dies respawns at home, its carried items lie on the tile where it died, and its X is 10 lower.
- AC-7: Each player starts with 3 villagers, the island never holds more than 50, and no villager is ever born.
- AC-8: Loyalty rises when a villager is fed, safe and not overworked and falls otherwise; below the leave threshold it leaves for another player or wanders off; bond and loyalty change independently; a villager's death lowers its leader's X more the higher their bond.
- AC-9: Hard work gives more output than normal work and lowers loyalty and health; light work gives less output.
- AC-10: Villagers gossip only about players, and only about events they saw or heard; a villager that witnessed nothing has nothing to tell.
- AC-11: Every action on the `docs/gameplay.md` list runs on a small example map, takes its configured duration, and changes the world as the rules say (one test per action).
- AC-12: Work and rest actions accept an amount or an end point; an interrupted action keeps the progress already made.
- AC-13: Each interrupt (spoken to, attacked or hurt, a player or dog comes into sight, a storm starts, a loss noticed, a feeling band changes) produces an interrupt event for the affected player.
- AC-14: Gathering by hand works at half speed; quarrying without a pickaxe fails while loose stone can be picked up by hand; basic tools can be crafted anywhere and better tools only at a workshop; tools wear and break; repair costs half the price; tools can be dropped, stolen and traded and are lost on death.
- AC-15: A fire burns for 6 game hours of fuel; cooking turns raw meat into cooked meat; raw meat spoils after about 1 game day; fire reduces cold and extends night sight; dogs keep away from fire; rain and storms put out campfires but not hearths.
- AC-16: All nine building types can be built; storms damage buildings and repair restores them.
- AC-17: A trade changes nothing unless both sides agree; a promise is recorded and later produces a kept or broken event; teach adds an entry at lower confidence to the listener's knowledge book, and a false entry can be taught the same way.
- AC-18: Steal, sabotage, attack (pain and dropped items), chase off, claim land with stakes, pull stakes, capture and poach each work on the example map.
- AC-19: Belief actions are logged and change nothing else in the world.
- AC-20: Wild dogs attack lone villagers, penned animals and unarmed players, and are scared off by fire, spears and groups of 3 or more.
- AC-21: When two players take the last fish in the same tick, exactly one gets it, decided by the seeded generator; the player order rotates every tick.
- AC-22: Each player has five hidden task stages; finishing stage 1 gives basic tools; a joint project gives each contributor more than the solo reward; holding a landmark for a game week gives the dominance bonus.
- AC-23: Claimed land shows the owner's border pattern; a landmark counts as held only when one player (or its loyal villagers) is the only one present for most of a game week.
- AC-24: Sight is about 7 tiles and shorter at night and in storms; hearing is about 5 tiles; remembered tiles can differ from the real map after a change out of sight.
- AC-25: Sense reports use at least 3 templates per event kind and are the same for the same seed.
- AC-26: A victim learns who harmed it only if it saw or heard it, or was told.
- AC-27: A player can talk only to someone in sight; everyone within hearing range receives the words and nobody else does.
- AC-28: Knowledge book entries carry a confidence between 0 and 1.
- AC-29: A full game year with four dummy players: week-1 median X is 60-79; each home plot's food first runs short in week 2 or 3; players without food stores have mean X below 40 in winter (weeks 7-8); no villager leaves before several game days of hunger or hard work (`main.py report` shows these).
- AC-30: In a scripted scenario, every action is used at least once, and scripted players trade, steal, claim land, fight dogs and finish all five task stages.
- AC-31: The determinism test passes with players and villagers, and all Phase 1 tests still pass.
- AC-32: `main.py view --screenshot` works on a run with players and villagers.

### Depends on
Phase 1.5.

### Notes
- Tim's review: dummy players run short of home resources around game weeks 2-3 and
  struggle in winter; scripted players do everything; the viewer shows players and
  villagers moving.
- No AI calls in this phase. Cost: $0.

## Phase 3: Observer screen, run control and exports

### Goal
The full observer window and run control, before any AI exists: a run of rule-based
players that Tim can watch in every tab, pause, resume, close and restart without
losing anything, and export to CSV. This is where Tim first sees what the game gives
him. Cost: $0.

### Requirements
Plan Contract (also with one coder): for every name and number an acceptance
criterion checks, the Contract gives the exact accessor (function, field, command or
config key) and at least one worked example (input and expected result, for example
`slide_position(start=(3,4), end=(4,4), progress=0.5) -> (3.5, 4)`), so coders and
the tester build and check the same thing and nothing is guessed.

Read `docs/design.md` (Measurement and the observer screen; Tech, hardware and
budget) and `docs/architecture.md` (Saving, pausing and resuming; Observer screen).
- Observer (pygame_gui) with the five tabs from `docs/design.md`, filled from the
  world and the database:
  - Chats: every line spoken by players and villagers, with who was in earshot.
  - Choice points: the rows of the `choice_points` table with the self-label and
    judge label columns. Rule-based players make none; Phase 4 fills it.
  - World history: a timeline of major events (deaths, villager departures and
    deaths, thefts, attacks, land claims, finished and damaged buildings, storms,
    droughts, season changes).
  - Players: feeling words, X, the hooked flag, the trust and anger grid, and the
    value table when a player has one (rule-based players have none, and the tab says
    so).
  - Spend: dollars used from the `spend` table and the cap from `run.toml`
    (rule-based runs show $0.00).
  Top bar: clock, day and season, pause and resume button, speed control, spend
  warning, autosave indicator. The monogram font from `assets/fonts/monogram/`.
- Map additions: land borders, state markers (sick, injured, sleeping, grave),
  buildings and their damaged versions.
- 30 frames per second, separate from ticks; read-only except pause, resume and speed.
- A live run opens in the full observer (the Plan names the command); `main.py view
  --screenshot` keeps working and now includes the tabs.
- Pause (button or P): the world stops after the current tick and a snapshot is
  saved. Autosave every 6 game hours; resume across days with the same event log and
  spend counter.
- Crash recovery: load the last autosave, then replay to the point of the crash so the
  event log matches an uninterrupted run. Build it so Phase 4 can make the replay
  reuse stored AI replies.
- Keep Windows awake while a run is active, and release the request on pause or exit.
- The measures from `docs/design.md` "Measures tracked over time" that need no AI,
  computed per game week: promises made vs. kept (per player and partner), help vs.
  harm actions and toward whom, villager welfare (deaths, departures, average
  loyalty), and belief actions. The rest come in Phases 4 and 5.
- `main.py export --run <run>`: CSV export of every table, ready for R.

### Acceptance criteria
- AC-1: With `SDL_VIDEODRIVER=dummy`, the observer opens with the five tabs and every top bar element, using the monogram font.
- AC-2: The observer draws at about 30 frames per second independent of tick speed, and its code calls no world-changing function except pause, resume and speed.
- AC-3: In a run with four rule-based players, the Chats tab shows every line in the `chats` table with the list of who was in earshot.
- AC-4: The World history tab lists the major event kinds above in time order, matching the event log.
- AC-5: The Players tab shows each player's feeling words, X, hooked flag and trust and anger grid; a player without a value table is shown as having none.
- AC-6: The Choice points tab shows rows inserted directly into `choice_points` with their self-label and judge label columns, and is empty for a rule-based run.
- AC-7: The Spend tab shows the dollars in the `spend` table and the cap from `run.toml`; a rule-based run shows $0.00.
- AC-8: The map draws land borders, the four state markers, every building and the damaged versions.
- AC-9: P and the button both pause and resume; pausing stops the world after the current tick and saves a snapshot.
- AC-10: An autosave is written every 6 game hours; resuming after the program is closed continues with the same event log and spend counter.
- AC-11: Pause-and-resume and crash recovery (process killed mid-run, then restarted) give the same event log as an uninterrupted run with the same seed.
- AC-12: While a run is active, the program asks Windows not to sleep, and releases the request on pause or exit.
- AC-13: Each no-AI measure listed above has a per-week value computed from a scripted-player run.
- AC-14: `main.py export --run <run>` writes one UTF-8 CSV with a header row per table, and each re-imports with the same row count.
- AC-15: `main.py view --screenshot` works on a run with players and villagers and shows the tabs.
- AC-16: All Phase 1 and 2 tests still pass, including determinism.

### Depends on
Phase 2.

### Notes
- Tim's review: watch a run of four rule-based players in the observer for a while
  (chats, world history, players tab, map); pause and resume; close the program
  mid-run and restart it; open the CSVs from `main.py export` in R. This is the
  moment to decide whether the game is worth paying for the AIs.
- Needs `assets/fonts/monogram/` (see `docs/setup.md`).
- No AI calls in this phase. Cost: $0.

## Phase 3.5: Observer comfort and the player guide

### Goal
The observer becomes easy to follow: activity bubbles, a village guide, a hideable
panel, a window that fits any screen and can be resized in game, click-to-find from
the tabs and the map with an inspector for any player or villager, event flashes,
chat filters, wellbeing and trust graphs, a mini-map, a key-help overlay, a screenshot
key, and a plain-language guide to every command and sprite. Drawing and reading
only: no world rule changes. Cost: $0.

### Requirements
Plan Contract (also with one coder): for every name and number an acceptance
criterion checks, the Contract gives the exact accessor (function, field, command,
key or config key) and at least one worked example (input and expected result), so
coders and the tester build and check the same thing and nothing is guessed.

Read `docs/design.md` (Measurement and the observer screen), `docs/architecture.md`
(Observer screen), `docs/gameplay.md` (Asset list) and the Phase 3 handoff Summary.

Frame data (`world/view.py`, no pygame):
- `AgentView` gains `activity` (the current action kind; for a villager without an
  action, its job; else `idle` or `sleeping`), `activity_target` (item, structure
  kind or person name, or empty) and `activity_progress` (0-1). Villager views also
  carry `job` and `work_level`.
- `WorldFrame.village_guide`: for each player its id, name, colour index and the ids
  and names of its villagers, plus the wanderers. Built from the world each frame.
- No snapshot, database or event changes.

Activity bubbles (`observer/`, `config/assets.toml`):
- A small bubble above each player and villager showing its activity as an icon. A
  new `[activity_icons]` table in `assets.toml` maps every activity kind to an item
  icon key (from the existing asset list) or to `word`; a `word` entry shows a short
  word instead ("Praying", "Guarding"). Every activity kind has an entry (checked on
  load).
- Whole-pixel drawing; bubbles never cover the top bar, the panel or the mini-map.
- B cycles bubbles: all, players only, off.

Village guide and chat filters (Chats tab):
- At the top of the Chats tab, a collapsible guide: each village in its player's
  colour with its villagers' names, then the wanderers. Names in chat lines are drawn
  in their village's colour.
- A filter above the list: all, one village, one person (speaker or target), or only
  lines the selected person heard. Paging works on the filtered rows.

Hideable panel and window size:
- A button and the Tab key hide or show the right-hand panel; the map takes the freed
  width.
- The window opens fitting the usable desktop (taskbar and title bar included), is
  DPI-aware on Windows and resizable by dragging. F11 toggles full screen.
- A Display menu in the top bar: size presets (fit screen, 1280x800, 1600x1000,
  1920x1080, full screen) and UI scale 1-3. Every layout keeps whole-number map
  scaling and fits the top bar, map, panel and mini-map without overlap.
- The choice is saved in `runs/observer_prefs.json` (never in `config/`, so the
  Phase 5 launch check is not affected) and used the next time any run is watched.
  The defaults stay in `run.toml`.

Selecting, click to find and the inspector:
- Clicking a chat line selects its speaker; a Choice points row selects its player; a
  World history row selects the player or villager it names. Clicking a player or
  villager on the map selects it. The map centres on the selected one, draws a ring
  in its colour and follows it. A right-click or a click on empty map clears the
  selection. Esc keeps its Phase 3 meaning.
- An Inspector in the panel for the selected one: name, village, activity and
  progress, needs (hunger, thirst, cold, rest), health, sickness, pain; for players,
  feeling words, X, hooked flag, carried items and tools, and the graphs below; for
  villagers, job, work level, loyalty and bond with its leader. Updated live;
  read-only.
- The Inspector is built from a list of sections, each a function from frame and
  database to rows, so Phase 4 can add "Values" and "Last choice point" sections
  without changing the layout code.

Event flashes:
- When a death, villager death or departure, theft, attack, land claim or building
  damage is logged, a short marker flashes on its tile for a few real seconds (length
  in `run.toml`). J jumps the map to the most recent one and selects who was
  involved.

Graphs:
- In the Players tab and the Inspector: a small line chart per player of X over time
  (from `player_day.x_hourly` events), and trust and anger toward each other player
  (from the stored snapshots, one point per autosave). Drawn with pygame, no extra
  library. Read from the database only. No sixth tab.

Mini-map:
- A small whole-island map in a corner of the map area: terrain colours, claimed
  land, one dot per player and villager in its colour, and a frame for the visible
  area. Clicking it moves the view there. M toggles it.

Key help and screenshots:
- H shows an overlay with every key, button and mouse action, from the same key table
  the guide uses.
- F12 saves the current window as a PNG in `runs/<run>/screenshots/`, named with the
  run and game time (for example `p35_y1_w2_d3_14-05.png`), and shows "Saved" in the
  top bar.

Guide (`docs/guide.md`; the Plan lists this file in Part folders):
- A plain-language guide for Tim: every `main.py` command with a copyable example and
  what it does; every observer key, button and mouse action; a table of every
  building and structure (with its damaged and in-progress look) and the sprite it
  uses from `assets.toml` (pack and tile, or `code`); animals, plants, state markers
  and activity bubbles the same way.

### Acceptance criteria
- AC-1: `AgentView` carries activity, activity_target and activity_progress for every player and villager; a player gathering wood shows `gather` / `wood` with progress rising from 0 to 1 over the action.
- AC-2: `WorldFrame.village_guide` lists every player's villagers and the wanderers, matching the world; after a villager leaves or is poached, the next frame shows it in its new place.
- AC-3: `[activity_icons]` has an entry for every activity kind (a missing one fails at load naming the file and key); with `SDL_VIDEODRIVER=dummy` each visible player and villager gets one bubble, showing the mapped icon or, for `word` entries, the word; B cycles all / players / off; no bubble overlaps the top bar, panel or mini-map rect.
- AC-4: The Chats tab starts with the village guide and chat names use their village colour; each filter (village, person, heard by the selected person) shows exactly the matching `chats` rows.
- AC-5: Tab and the hide button hide and show the panel; with it hidden, the map rect spans the full width.
- AC-6: At 1280x720, 1600x1000, 1920x1080 and 3200x2000, and after a resize event, the top bar, map, panel and mini-map fit the window without overlap and the map scale is a whole number; F11 toggles full screen.
- AC-7: A Display menu choice changes the layout at once, writes `runs/observer_prefs.json`, and a new observer reads it back; nothing under `config/` changes.
- AC-8: Clicking a chat line, a choice point row (inserted directly into `choice_points`), a world history row and a map sprite each select the right player or villager, centre the map on it and draw the ring; right-click clears it; Esc behaves as in Phase 3.
- AC-9: The Inspector shows every listed field for a selected player and a selected villager, matching the world at that tick; a test adds an extra section through the section list and it appears without layout code changes.
- AC-10: A logged theft, attack, death and land claim each flash a marker on their tile; J centres on the latest and selects who was involved.
- AC-11: The X graph for a player matches its `player_day.x_hourly` values, and the trust and anger lines match the values in the stored snapshots.
- AC-12: The mini-map shows every player and villager dot in its colour and the visible-area frame; a click on it moves the view there; M hides it.
- AC-13: H shows the key-help overlay listing every key and button the observer handles (checked against the observer's key table); F12 writes a PNG with the run and game time in its name under `runs/<run>/screenshots/`.
- AC-14: `docs/guide.md` lists every subcommand of `main.py` (checked by a test against the argparse parser), every key in the observer's key table, and every building and structure kind in `assets.toml` with its sprite source.
- AC-15: The observer still calls no world-changing function except pause, resume and speed; a watched run's event log equals a headless run with the same seed.
- AC-16: All earlier tests pass, including determinism (the Phase 3 five-tab test still holds), and ruff reports no errors.

### Depends on
Phase 3. The Telegram connector accepts half-phase numbers (Tim's fix before this
phase).

### Notes
- Tim's review: `uv run python main.py new p35 --players scripted`, then
  `uv run python main.py watch --run p35`. Watch the bubbles, open the village guide,
  filter the chats, hide the panel, try the Display menu and F11, click chat lines,
  people and the mini-map, open a player's graphs, press J, H and F12, and read
  `docs/guide.md`.
- No AI calls in this phase. Cost: $0.

## Phase 4: Minds and AI connections

### Goal
The AI players' minds and the connections to every company, built and tested with
the fake adapter only. Cost: $0, and no paid steps for Tim after this phase.

### Requirements
Plan Contract (also with one coder): for every name and number an acceptance
criterion checks, the Contract gives the exact accessor (function, field, command or
config key) and at least one worked example (input and expected result, for example
`slide_position(start=(3,4), end=(4,4), progress=0.5) -> (3.5, 4)`), so coders and
the tester build and check the same thing and nothing is guessed.

Read `docs/design.md` (The players, The mind, Values system, Learning from mistakes,
Measurement and the observer screen), `docs/gameplay.md` (Opening guide, When players
decide, Reply validation) and `docs/architecture.md` (AI calls, Memory, Saving,
pausing and resuming).
- `llm/`: one interface for every role, an adapter each for Anthropic, OpenAI,
  Google, xAI (openai SDK at xAI's endpoint) and Mistral, plus Ollama embeddings and
  the fake adapter. API keys loaded at runtime from `.env` with python-dotenv.
- Pydantic schemas for the player reply types (action, self-label, weekly reflection,
  invented value), sent through each company's structured-output mode. Every action
  reply, fast tier included, carries a short self-label (values served and violated,
  toward or against).
- Three-layer prompts for caching (fixed, slow-changing, per call), with Anthropic's
  cache markers.
- Retry rules: format error, 1 retry, then rest. Refusal, no retry, rest, logged.
  Network error or rate limit, 3 retries with growing waits, then auto-pause.
- Every call recorded in `ai_calls`: prompt, reply, model version, tokens (thinking,
  input, output, cached), cost and time taken; a spend counter using prices from
  `models.toml`.
- Spend cap from `run.toml`: warning at 80%, auto-pause before any call that would
  pass it. `main.py new` with any AI seat refuses to start without `--max-dollars`.
- Calls for different players run at the same time, and the clock waits for all.
- `minds/`: the four decision triggers; the router with the three rules in
  `docs/design.md`; reflex tier (code); fast tier (rules plus the cheap model, hooked
  or not); slow tier for unhooked main-model decisions (Noticer, Advisor, then the
  main model, with the full memory search); hooked tier for hooked main-model
  decisions (the same main model at the same thinking setting, with no Noticer or
  Advisor call and only the most recent memories, up to the hooked memory size in
  `balance.toml`).
- The opening guide and day-0 order from `docs/gameplay.md`, with human names and no
  hints about models.
- Day-0 value ranking: all 14 values, weights summing to 100, core values 10-25%,
  background at least 1%, checked and repaired by code.
- Slow and hooked decisions follow the 4-step weighing in `docs/design.md` and end
  with a self-label; acting against one's own values is logged, never blocked.
- Memory: identity, value table, relationships, knowledge book, memory stream picked
  by recency, importance and relevance (embeddings), rolling summary. The Advisor
  reads the main model's past decisions. Mistake flags when an outcome was clearly
  worse than expected.
- Weekly reflection: at most +/-10 per value, rescaling with a 1% floor, the core
  recomputed, at most one invented value checked by code, the rolling summary
  rewritten, `value_history` rows written.
- Choice points: every slow and hooked decision, and every fast-tier decision that
  harms someone, makes or breaks a promise, or self-labels as against its own values,
  becomes a `choice_points` record with every field in `docs/design.md`, including
  the tier. Noticer and Advisor fields are empty when they didn't run; the judge label
  is filled in Phase 5.
- Run control with AI: pausing while a reply is in progress lets it finish and apply
  first; crash recovery reuses stored AI replies, so no call is paid for twice; a call
  that fails because the laptop slept pauses the run.
- The observer shows the AI data: value tables in the Players tab, choice points with
  their self-labels and tier, and live spend.
- `models.toml` filled for all nine roles (four main models, four helpers, the
  Mistral judge) with versions, prices, structured-output, caching and thinking
  settings, each with its source URL in a comment. No Chinese-developed models; the
  Grok model must accept the thinking setting. Model research comes from the Codex
  researcher (it has web search; the Claude agents don't).
- `main.py new <run> --ai-seats 1 --cheap --max-dollars <N>`: one AI player on its
  company's cheap model, the other three rule-based.
- `main.py decisions --run <run> [--player N]`: prints a player's decisions in plain
  text (tier, situation, options, choice, trade-off, self-label).

### Acceptance criteria
- AC-1: Each company adapter turns the common request into that SDK's call with structured output, and turns the SDK's response into the common reply object (tested with mocked SDK clients, no network, no keys).
- AC-2: Each reply type has good and bad example replies; good ones validate and bad ones are rejected; an action reply without a self-label is rejected.
- AC-3: Prompts are built in three layers; layer 1 is byte-identical across every call in a run; Anthropic requests carry cache markers after layers 1 and 2.
- AC-4: A format error is retried once and then the player rests with the failure logged; a refusal is not retried, the player rests and the refusal is logged; a network error or rate limit is retried 3 times with growing waits and then the run pauses.
- AC-5: Every call writes one `ai_calls` row with prompt, reply, model version, thinking, input, output and cached tokens, cost and duration.
- AC-6: The spend counter equals a hand calculation from the `models.toml` prices for a set of recorded calls.
- AC-7: Spend at 80% of the cap shows a warning; a call that would pass the cap is not sent and the run pauses; `main.py new` with an AI seat and no `--max-dollars` refuses to start.
- AC-8: Calls for different players run concurrently, and no tick advances until all have returned (fake adapter with delays).
- AC-9: A player is asked for a decision only on the four triggers; with no trigger it continues its action; awake for 2 game hours without a decision triggers a fast-tier check.
- AC-10: The router follows the three rules in `docs/design.md`: urgent body needs go to the reflex tier with no model call; routine decisions go to the fast tier whether hooked or not; a main-model decision by an unhooked player calls the Noticer, the Advisor and then the main model; the same decision by a hooked player calls only the main model, at the same thinking setting, with no more memories than the hooked memory size and no memory search.
- AC-11: The opening guide matches `docs/gameplay.md` with the names filled in; across a fake-adapter game week, no player prompt contains the words AI, model, Claude, GPT, Gemini, Grok, Anthropic, OpenAI, Google, xAI, Mistral, game, experiment or observer.
- AC-12: A day-0 ranking with 14 values summing to 100, 5 core values at 10-25% and background values at 1% or more is accepted; invalid rankings are repaired by code and the repair is logged.
- AC-13: A slow or hooked decision lists 2-4 options with values served and violated, X estimates, the choice, the trade-off and a self-label; a choice against the player's own top values is logged as a value violation and still carried out.
- AC-14: Memory retrieval ranks by recency, importance and relevance (fake embedder); the rolling summary is kept and rewritten weekly.
- AC-15: The Advisor's prompt includes the main model's recent decisions.
- AC-16: An outcome worse than expected by the configured margin is flagged as a mistake and the weekly reflection prompt includes it.
- AC-17: Weekly reflection: requested changes beyond +/-10 are clipped; weights are rescaled to sum to 100 with a 1% floor; the core is the top 5 after rescaling; at most one invented value per week; invented values that grant abilities, mention the real world, AI or the game, or duplicate an existing value are rejected; `value_history` gets a row per value.
- AC-18: In a fake-adapter run, every slow and hooked decision has a `choice_points` record with every field in the `docs/design.md` table and its tier; a fast-tier steal, a fast-tier promise and a fast-tier action self-labelled "against" each produce one; a routine fast-tier gather produces none; hooked records have empty Noticer and Advisor fields.
- AC-19: Pausing while a reply is in progress lets it finish and apply, then saves a snapshot; crash recovery with AI players gives the same event log as an uninterrupted run and makes no AI call twice (fake adapter call count); a failed call caused by sleep pauses the run.
- AC-20: With `SDL_VIDEODRIVER=dummy`, a fake-adapter run shows value tables in the Players tab, choice points with self-labels and tier, and the spend so far.
- AC-21: A full game week with four fake-adapter AI players completes, and running it twice with the same seed and the same fake replies gives identical event logs.
- AC-22: `models.toml` loads with all nine roles filled, each with a source URL, and contains no Chinese-developed model.
- AC-23: `main.py new t4 --ai-seats 1 --cheap --max-dollars 1` runs a game week with the fake adapter in seat 1 and rule-based players in seats 2-4; `main.py decisions --run t4 --player 1` prints its decisions.
- AC-24: All Phase 1-3 tests still pass, including determinism.

### Depends on
Phase 3. API keys in `.env` are not needed for this phase.

### Notes
- Tim's review: a short fake-adapter run watched in the observer (values, choice
  points with their tier, spend at $0.00) and `main.py decisions` read in plain text.
  The fake adapter's replies are canned, so this checks the plumbing, not how real AIs
  behave.
- No real AI calls in this phase. Cost: $0.

## Phase 5: Judge, measurement, calibration and pilot tools

### Goal
Everything left before money is spent: the blind judge and its summaries, the
remaining measures, the calibration command, and the pilot and launch tools, all
tested with the fake adapter. After this phase Tim makes the first paid runs himself.
Cost for the agents: $0.

### Requirements
Plan Contract (also with one coder): for every name and number an acceptance
criterion checks, the Contract gives the exact accessor (function, field, command or
config key) and at least one worked example (input and expected result, for example
`slide_position(start=(3,4), end=(4,4), progress=0.5) -> (3.5, 4)`), so coders and
the tester build and check the same thing and nothing is guessed.

Read `docs/design.md` (Measurement and the observer screen; Tech, hardware and
budget) and `docs/architecture.md` (AI calls; Budget).
- Mistral judge, blind (human names only) and told to stay neutral, with a Pydantic
  judge-label schema: full labels for flagged choice points (harm, promises, value
  conflicts, mistakes), short ones for routine ones, labelled as they happen and shown
  in the observer's Choice points tab.
- Daily world summary, weekly player profiles, flags for betrayals, deaths and new
  beliefs.
- The remaining measures in `docs/design.md` "Measures tracked over time", computed
  per game week: stated vs. revealed values (from the judge's labels), the share of
  hooked and of unhooked choices that go "against", how often each player follows its
  Advisor (unhooked slow decisions only), superstition events and invented beliefs,
  and value weights per week linked to the events that caused each change.
- `main.py judge-check --max-dollars <N>`: a few real judge calls on sample choice
  points, for Tim to run.
- `main.py calibrate --max-dollars <N> [--dry-run] [--apply]`: runs the same sample
  slow and hooked decisions on all four main models, compares thinking tokens,
  adjusts the settings until they roughly match, measures cost per slow decision and
  per game week, and writes `runs/calibration/report.md`. The report also estimates
  the cost of one cheap seat for a game week and of the pilot. `--dry-run` uses the
  fake adapter. `--apply` writes the measured settings and costs into
  `config/models.toml`.
- A pilot profile (`main.py new <run> --profile pilot --max-dollars <N>`): all four
  seats on their own companies' cheap models for 2-3 game weeks.
- `main.py analyze --run <run>`: a report (`runs/<run>/analysis.md` plus CSVs) with
  deaths, X over time, when resources ran short, decisions per player per game day
  split by trigger (action finished, spoken to, interrupt, 2-hour check) and by tier,
  refusals, schema failures and cost per game week.
- Tuning proposals in the same report: each compares a measured value with its target
  (scarcity, X weights, villager loyalty, decision triggers, slow-thinking triggers)
  and proposes a config change with the evidence.
- `main.py launch-check`: passes only when `config/` has no uncommitted changes, the
  spend cap is set, and the seed is recorded in `run.toml`; prints each check.
- A launch profile (`--profile launch`) with the four main models.

### Acceptance criteria
- AC-1: No judge prompt contains a model or company name (scan of every judge prompt in a fake-adapter run); flagged choice points get the full label and routine ones the short label; each choice point is labelled before the next game hour ends, and the label shows in the Choice points tab.
- AC-2: A fake-adapter run of 2 game days produces 2 daily summaries, and a game week produces one profile per player; betrayals, deaths and new beliefs are flagged.
- AC-3: Each measure in the `docs/design.md` list (including the Phase 3 ones) has a per-week value computed from a fake-adapter run; the hooked and unhooked "against" shares are computed separately.
- AC-4: `main.py judge-check` and `main.py calibrate` without `--max-dollars` refuse to start, and both stop before any call that would pass the limit (tested with the fake adapter).
- AC-5: `main.py calibrate --dry-run --max-dollars 1` runs with the fake adapter and writes a report with: chosen versions, thinking settings, thinking tokens per model, cost per slow decision, cost per hooked decision, cost per game week, game weeks per $100, whether the run reaches week 7, and the estimated cost of one cheap seat for a game week and of the pilot.
- AC-6: `--profile pilot` sets all four seats to their companies' cheap models and a run length of 2-3 game weeks, refuses to start without `--max-dollars`, and a fake-adapter run with it completes.
- AC-7: `main.py analyze` on a fake-adapter run writes a report with every metric listed above, each with a number, including decisions per player per game day by trigger and by tier.
- AC-8: Every tuning proposal names the config key, the current value, the proposed value and the measured evidence; no proposal is made when a metric is on target.
- AC-9: `main.py launch-check` fails with uncommitted changes in `config/`, a missing spend cap or a missing seed, and passes when all three are in order.
- AC-10: `--profile launch` selects the four main models from `models.toml`.
- AC-11: All earlier tests still pass, including determinism.

### Depends on
Phase 4.

### Notes
- Tim's review: the first steps that spend money, all run by Tim, never by an agent,
  one at a time:
  0. If not done yet, create the five API accounts and keys with spend limits
     (`docs/setup.md` Part 4).
  1. `uv run python main.py calibrate --max-dollars 5`, then read
     `runs/calibration/report.md`.
  2. If it looks right: `uv run python main.py calibrate --max-dollars 5 --apply`,
     then `git add -A; git commit -m "calibration results"`.
  3. A few real judge calls: `uv run python main.py judge-check --max-dollars 0.10`.
  4. Optional, one AI player for a game week:
     `uv run python main.py new week-test --ai-seats 1 --cheap --max-dollars <N>`
     (N = the report's cheap-seat estimate, rounded up), then
     `uv run python main.py decisions --run week-test --player 1`.
  5. The pilot: `uv run python main.py new pilot --profile pilot --max-dollars <N>`
     (N = the report's pilot estimate, rounded up), let it run, then
     `uv run python main.py analyze --run pilot`. Commit nothing from `runs/`.
- In the pilot analysis, check decisions per game day by trigger: if being spoken to
  or seeing another player drives most of the cost, Phase 6 can tune the triggers.

## Phase 6: Tuning and launch

### Goal
A tuned world, frozen config and a passing launch check, ready for Tim to start the
real run.

### Requirements
Plan Contract (also with one coder): for every name and number an acceptance
criterion checks, the Contract gives the exact accessor (function, field, command or
config key) and at least one worked example (input and expected result, for example
`slide_position(start=(3,4), end=(4,4), progress=0.5) -> (3.5, 4)`), so coders and
the tester build and check the same thing and nothing is guessed.

- Read `runs/calibration/report.md`, `runs/pilot/analysis.md` and the pilot database.
- Turn the tuning proposals into config changes, each with its evidence, presented to
  Tim at the approval gate (he approves each change).
- Re-check the balance targets from Phase 2 with dummy players after the changes.
- Update `docs/design.md` open questions with the model versions, thinking settings
  and measured cost per game week (from the calibration and the pilot), and the tuned
  starting numbers (the Plan names `docs/design.md` in a Part folders line).
- Leave the config ready to freeze: `main.py launch-check` passes after the manager's
  phase commit.

### Acceptance criteria
- AC-1: Every config change matches an approved proposal and has a one-line reason comment with its evidence.
- AC-2: The Phase 2 balance metrics still hit their targets with dummy players after the changes, or the miss is explained in the Summary.
- AC-3: `docs/design.md` open questions hold the measured model versions, thinking settings and cost per game week, with the files they came from.
- AC-4: `main.py launch-check` passes on the committed tree.
- AC-5: All tests pass, including determinism.

### Depends on
Phase 5, Tim's calibration results committed, and a finished pilot run in
`runs/pilot/`.

### Notes
- Tim starts the real run himself after this phase: `main.py new <run> --profile
  launch --max-dollars <N>`, with N equal to the spend cap in `run.toml` (the $100
  budget). The Plan's For Tim section gives the exact command.
