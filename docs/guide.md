# AI Island guide

This file is written by the program (`uv run python main.py guide`). Do not edit it by hand: your changes would be overwritten.

## What this is

AI Island is a small island with four players and their villagers. You watch it in a window. This guide says which commands start things, which keys and buttons the window understands, and what every picture means.

## Commands

Type these in a terminal (PowerShell) opened in the project folder. Copy the example line, and change the run name `p35` to your own name if you like.

### `new`

Creates a new game (a run) with a name you choose. Nothing is played yet, except with --ai-seats or --profile: then the AI seats are played by AI, the game runs for --ticks minutes and is saved. --max-dollars is then needed: it is the most the run may ever spend. --cheap gives the AI players the smaller helper model for every decision. Without --backend live the AI is the practice kind (pretend, no cost). --profile pilot is the short cheap trial (three game weeks) and --profile launch is the real run; profiles use the real AI by default, which costs money, so starting them is Tim only: the program shows how much it may spend and waits for you to type yes. Practice example: uv run python main.py new t4 --ai-seats 1 --cheap --max-dollars 1

Options: `run` (needed), `--seed` (optional), `--players` (optional), `--ai-seats` (optional), `--cheap` (optional), `--profile` (optional), `--backend` (optional), `--max-dollars` (optional), `--ticks` (optional).

```
uv run python main.py new p35 --players scripted
```

### `headless`

Plays the game with no window, as fast as the computer can. Good for quick tests.

Options: `--ticks` (needed), `--run` (optional), `--seed` (optional), `--players` (optional).

```
uv run python main.py headless --ticks 1440 --seed 1
```

### `resume`

Continues a saved game with no window, from where it stopped. A game with real AI asks you to type yes first (it shows how much it may spend). A pilot stops by itself at its planned end.

Options: `run` (needed), `--ticks` (optional), `--players` (optional).

```
uv run python main.py resume p35 --ticks 1440
```

### `report`

Prints a balance report of a saved game: how food, health and the like went.

Options: `--run` (needed).

```
uv run python main.py report --run p35
```

### `measures`

Prints the weekly numbers of a saved game (one line per week).

Options: `--run` (needed).

```
uv run python main.py measures --run p35
```

### `export`

Writes every table of a saved game as spreadsheet (CSV) files you can open in Excel.

Options: `--run` (needed), `--out` (optional).

```
uv run python main.py export --run p35
```

### `watch`

Opens the window and shows a saved game while it plays. The game saves as it goes.

Options: `--run` (needed).

```
uv run python main.py watch --run p35
```

### `view`

Shows a quick preview of the island in a window. Nothing is saved. With a picture file name it saves one picture and closes.

Options: `--run` (optional), `--seed` (optional), `--ticks` (optional), `--screenshot` (optional).

```
uv run python main.py view --run p35 --ticks 60 --screenshot runs/p35/preview.png
```

### `decisions`

Prints every decision an AI player made, one block each: when, what it saw, the options it weighed, what it chose and which of its values that served or hurt. Add --player to see one player only.

Options: `--run` (needed), `--player` (optional).

```
uv run python main.py decisions --run t4 --player 1
```

### `analyze`

Reads a finished or paused AI game and writes a report (analysis.md) and CSV files in the run's folder: deaths, wellbeing, food, decisions per day, failures, cost per game week, value changes, the judge's summaries, and suggested setting changes. It changes nothing and costs nothing.

Options: `--run` (needed).

```
uv run python main.py analyze --run t4
```

### `launch-check`

A last safety check before the real run: no unsaved changes in the config folder, a spending limit and a seed are set. Prints PASS or FAIL for each. Changes nothing.

```
uv run python main.py launch-check
```

### `judge-check`

Tim only (spends real money). Sends a few sample choices to the judge AI and shows what it says and what each answer cost. --max-dollars is needed; the check stops before any call that could pass it. Add --dry-run to try it with pretend AI and no cost.

Options: `--max-dollars` (optional), `--dry-run` (optional).

```
uv run python main.py judge-check --max-dollars 1 --dry-run
```

### `calibrate`

Tim only (spends real money). Measures what a decision costs on each AI model, matches how hard the four main models think, and estimates the cost of a game week and of the pilot. --max-dollars is needed; it stops before any call that could pass it. Add --dry-run for a practice estimate with pretend AI and no cost. --apply saves a good real result in the models file.

Options: `--max-dollars` (optional), `--dry-run` (optional), `--apply` (optional).

```
uv run python main.py calibrate --max-dollars 1 --dry-run
```

### `guide`

Rewrites this guide file from the program's own lists.

Options: `--out` (optional).

```
uv run python main.py guide
```

## Keys, buttons and mouse

Everything the window reacts to. Press `H` in the window to see the same list.

### Keys

| Name | What it does |
|---|---|
| `P` | pause or resume the game |
| `+` | faster (also = and keypad +) |
| `-` | slower (also keypad -) |
| `Left` | scroll the map left |
| `Right` | scroll the map right |
| `Up` | scroll the map up |
| `Down` | scroll the map down |
| `Tab` | hide or show the side panel |
| `B` | bubbles: all, players only, off |
| `M` | mini-map on or off |
| `J` | jump to the latest event |
| `H` | show or hide this key help |
| `F11` | full screen on or off |
| `F12` | save a screenshot |
| `Esc` | quit |

### Buttons

| Name | What it does |
|---|---|
| `Pause/Resume` | pause or resume the game |
| `-` | slower |
| `+` | faster |
| `Chats` | show the Chats tab |
| `Choice points` | show the Choice points tab |
| `World history` | show the World history tab |
| `Players` | show the Players tab |
| `Spend` | show the Spend tab |
| `Older` | older page of the list |
| `Newer` | newer page of the list |
| `Panel` | hide or show the side panel |
| `Display size` | choose the window size |
| `UI scale` | choose the text and button scale |
| `Village guide` | fold or unfold the village guide on the Chats tab |
| `Chat filter` | choose which chats to show |

### Mouse

| Name | What it does |
|---|---|
| `Left click person on map` | select that person (the map follows them) |
| `Right click map` | clear the selection |
| `Click empty map` | clear the selection |
| `Click chat/choice/history row` | select the person named in the row |
| `Click mini-map` | move the view there |
| `Mouse wheel` | scroll the text |
| `Drag window edge` | resize the window |

## Pictures

Every picture comes from one of two sheets, named by column and row (`kenney 3,4` is column 3, row 4 of the Kenney sheet; `tiny_creatures` is the animal sheet). Some are drawn by the program itself. Nothing is shown in the window that is not listed here.

### Terrain

The ground, water and land markers.

| Name | Picture from |
|---|---|
| `grass` | drawn by the program |
| `sand` | kenney 1,0 |
| `tree` | kenney 0,1 |
| `stump` | kenney 18,6 |
| `spring` | kenney 12,4 |
| `lake` | kenney 8,5 |
| `coast` | kenney 9,4 |
| `farmland_empty` | kenney 16,0 |
| `farmland_planted` | kenney 13,6 |
| `farmland_growing` | kenney 14,6 |
| `farmland_ready` | kenney 15,6 |
| `farmland_failed` | kenney 12,6 |
| `rocky` | kenney 3,0 |
| `rocky_depleted` | kenney 2,0 |
| `quarry` | kenney 1,11 |
| `quarry_depleted` | kenney 2,11 |
| `claim_border_1` | kenney 13,1 |
| `claim_border_2` | kenney 14,1 |
| `claim_border_3` | kenney 15,1 |
| `claim_border_4` | kenney 16,1 |
| `boundary_stake` | kenney 0,7 |
| `snow` | drawn by the program |
| `drought` | drawn by the program |
| `overlay_night` | drawn by the program |
| `overlay_rain` | drawn by the program |
| `overlay_storm` | drawn by the program |

### Plants

Things that grow and can be picked.

| Name | Picture from |
|---|---|
| `berries` | kenney 20,5 |
| `mushrooms` | drawn by the program |
| `roots` | kenney 34,20 |
| `herbs` | kenney 0,2 |
| `healing_herbs` | kenney 33,20 |
| `mild_poison` | kenney 2,2 |
| `strong_poison` | drawn by the program |

### Animals

Wild and kept animals.

| Name | Picture from |
|---|---|
| `rabbit` | tiny_creatures 7,17 |
| `deer` | tiny_creatures 2,16 |
| `boar` | tiny_creatures 0,16 |
| `fish` | tiny_creatures 4,6 |
| `bird` | tiny_creatures 4,13 |
| `nest_eggs` | drawn by the program |
| `goat` | tiny_creatures 2,15 |
| `chicken` | tiny_creatures 0,15 |
| `wild_dog` | tiny_creatures 3,2 |

### People

The four players and the villagers (each villager looks like one of six).

| Name | Picture from |
|---|---|
| `player_1` | kenney 25,0 |
| `player_2` | kenney 26,1 |
| `player_3` | kenney 24,4 |
| `player_4` | kenney 28,1 |
| `villager_1` | kenney 25,2 |
| `villager_2` | kenney 26,2 |
| `villager_3` | kenney 24,3 |
| `villager_4` | kenney 25,3 |
| `villager_5` | kenney 26,3 |
| `villager_6` | kenney 27,3 |

### State markers

Small signs drawn on a person.

| Name | Picture from |
|---|---|
| `marker_sick` | kenney 38,14 |
| `marker_injured` | kenney 41,10 |
| `marker_sleeping` | drawn by the program |
| `marker_grave` | kenney 43,21 |

### Buildings and structures

Things people build.

| Name | Picture from |
|---|---|
| `house` | kenney 0,20 |
| `hearth` | kenney 14,10 |
| `field` | kenney 17,0 |
| `storehouse` | kenney 8,14 |
| `workshop` | kenney 10,14 |
| `pen` | kenney 1,3 |
| `campfire` | kenney 15,10 |
| `shrine` | kenney 21,11 |
| `offering_spot` | kenney 23,11 |
| `granary` | kenney 12,14 |
| `bridge` | kenney 7,5 |
| `monument` | kenney 44,21 |
| `great_tree` | kenney 4,2 |
| `lake_dock` | kenney 3,10 |

### Damaged and unfinished buildings

A damaged building shows a crack drawn over it. A building still being built looks like the normal sprite faded, with a progress bar.

| Building | Normal picture | Damaged picture | While being built |
|---|---|---|---|
| `house` | kenney 0,20 | drawn by the program | normal sprite faded with a progress bar |
| `hearth` | kenney 14,10 | drawn by the program | normal sprite faded with a progress bar |
| `field` | kenney 17,0 | drawn by the program | normal sprite faded with a progress bar |
| `storehouse` | kenney 8,14 | drawn by the program | normal sprite faded with a progress bar |
| `workshop` | kenney 10,14 | drawn by the program | normal sprite faded with a progress bar |
| `pen` | kenney 1,3 | drawn by the program | normal sprite faded with a progress bar |
| `campfire` | kenney 15,10 | drawn by the program | normal sprite faded with a progress bar |
| `shrine` | kenney 21,11 | drawn by the program | normal sprite faded with a progress bar |
| `offering_spot` | kenney 23,11 | drawn by the program | normal sprite faded with a progress bar |
| `granary` | kenney 12,14 | drawn by the program | normal sprite faded with a progress bar |
| `bridge` | kenney 7,5 | drawn by the program | normal sprite faded with a progress bar |
| `monument` | kenney 44,21 | drawn by the program | normal sprite faded with a progress bar |
| `great_tree` | kenney 4,2 | drawn by the program | normal sprite faded with a progress bar |
| `lake_dock` | kenney 3,10 | drawn by the program | normal sprite faded with a progress bar |

### Items

Things people carry.

| Name | Picture from |
|---|---|
| `item_wood` | kenney 26,11 |
| `item_stone` | kenney 5,2 |
| `item_water` | kenney 28,11 |
| `item_raw_meat` | kenney 33,16 |
| `item_cooked_meat` | drawn by the program |
| `item_spoiled_meat` | drawn by the program |
| `item_fish` | kenney 33,17 |
| `item_eggs` | kenney 34,17 |
| `item_milk` | kenney 33,13 |
| `item_berries` | kenney 20,5 |
| `item_mushrooms` | drawn by the program |
| `item_roots` | kenney 34,20 |
| `item_herbs` | kenney 0,2 |
| `item_crops` | kenney 34,18 |
| `item_offering` | kenney 41,4 |

### Tools

Basic and better tools.

| Name | Picture from |
|---|---|
| `tool_axe_basic` | kenney 41,7 |
| `tool_axe_better` | kenney 42,8 |
| `tool_pickaxe_basic` | kenney 43,5 |
| `tool_pickaxe_better` | kenney 36,5 |
| `tool_hoe_basic` | kenney 35,2 |
| `tool_hoe_better` | kenney 36,2 |
| `tool_fishing_rod` | kenney 32,4 |
| `tool_fishing_net` | drawn by the program |
| `tool_spear_basic` | kenney 32,3 |
| `tool_spear_better` | kenney 36,3 |
| `tool_water_skin` | kenney 47,3 |
| `tool_bucket` | kenney 46,3 |

### Interface

Pictures used by the window itself.

| Name | Picture from |
|---|---|
| `ui_map` | kenney 32,15 |
| `ui_clock` | kenney 39,12 |
| `ui_season` | kenney 27,11 |
| `ui_pause` | drawn by the program |
| `ui_resume` | kenney 29,20 |
| `ui_speed` | kenney 34,21 |
| `ui_tab_chats` | kenney 35,15 |
| `ui_tab_choice_points` | kenney 37,13 |
| `ui_tab_world_history` | kenney 33,15 |
| `ui_tab_players` | kenney 43,16 |
| `ui_tab_spend` | kenney 35,16 |
| `ui_spend_warning` | kenney 35,21 |
| `ui_paused_indicator` | drawn by the program |
| `ui_autosave_indicator` | kenney 42,16 |
| `ui_font` | drawn by the program |

## What people are doing (bubbles)

A small bubble over each person shows what they are doing now. It is a picture, or a word when no picture fits. Press `B` to switch bubbles.

| Activity | Shown as |
|---|---|
| `ally` | the word "Alliance" |
| `assign_villager` | the word "Assigning" |
| `attack` | the word "Attacking" |
| `build` | the word "Building" |
| `build_shrine` | picture `shrine` (kenney 21,11) |
| `capture` | the word "Capturing" |
| `ceremony` | the word "Ceremony" |
| `chase_off` | the word "Chasing" |
| `claim_land` | picture `boundary_stake` (kenney 0,7) |
| `cook` | picture `item_cooked_meat` (drawn by the program) |
| `craft` | picture `tool_axe_basic` (kenney 41,7) |
| `drink` | picture `item_water` (kenney 28,11) |
| `drop` | the word "Dropping" |
| `eat` | picture `item_cooked_meat` (drawn by the program) |
| `farm` | picture `tool_hoe_basic` (kenney 35,2) |
| `fish` | picture `tool_fishing_rod` (kenney 32,4) |
| `gather` | picture `item_wood` (kenney 26,11) |
| `gift` | the word "Gifting" |
| `guard` | the word "Guarding" |
| `hunt` | picture `tool_spear_basic` (kenney 32,3) |
| `idle` | the word "Idle" |
| `make_fire` | picture `campfire` (kenney 15,10) |
| `move` | the word "Walking" |
| `offering` | picture `item_offering` (kenney 41,4) |
| `pick_up` | the word "Picking up" |
| `poach` | the word "Poaching" |
| `pray` | the word "Praying" |
| `promise` | the word "Promising" |
| `pull_stakes` | the word "Pulling" |
| `recruit` | the word "Recruiting" |
| `repair` | the word "Repairing" |
| `rest` | the word "Resting" |
| `sabotage` | the word "Sabotage" |
| `sleeping` | the word "Sleeping" |
| `steal` | the word "Stealing" |
| `store` | picture `storehouse` (kenney 8,14) |
| `talk` | the word "Talking" |
| `tame` | the word "Taming" |
| `teach` | the word "Teaching" |
| `tend_animals` | the word "Tending" |
| `trade` | the word "Trading" |
| `use_herb` | picture `item_herbs` (kenney 0,2) |
