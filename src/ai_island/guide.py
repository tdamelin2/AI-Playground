"""Builds the plain-language guide (docs/guide.md) from the program's own tables.

The guide is generated, so it cannot drift: ``uv run python main.py guide`` rewrites it.
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any

from ai_island.observer.keys import KEY_TABLE
from ai_island.world.view import ACTIVITY_KINDS

# What each command does, in plain words, and one copyable example.
_COMMANDS: dict[str, tuple[str, str]] = {
    "new": (
        "Creates a new game (a run) with a name you choose. Nothing is played yet, except with "
        "--ai-seats or --profile: then the AI seats are played by AI, the game runs for --ticks "
        "minutes and is saved. --max-dollars is then needed: it is the most the run may ever "
        "spend. --cheap gives the AI players the smaller helper model for every decision. "
        "Without --backend live the AI is the practice kind (pretend, no cost). "
        "--profile pilot is the short cheap trial (three game weeks) and --profile launch is "
        "the real run; profiles use the real AI by default, which costs money, so starting "
        "them is Tim only: the program shows how much it may spend and waits for you to type "
        "yes. Practice example: "
        "uv run python main.py new t4 --ai-seats 1 --cheap --max-dollars 1",
        "uv run python main.py new p35 --players scripted",
    ),
    "analyze": (
        "Reads a finished or paused AI game and writes a report (analysis.md) and CSV files in "
        "the run's folder: deaths, wellbeing, food, decisions per day, failures, cost per game "
        "week, value changes, the judge's summaries, and suggested setting changes. It changes "
        "nothing and costs nothing.",
        "uv run python main.py analyze --run t4",
    ),
    "launch-check": (
        "A last safety check before the real run: no unsaved changes in the config folder, a "
        "spending limit and a seed are set. Prints PASS or FAIL for each. Changes nothing.",
        "uv run python main.py launch-check",
    ),
    "judge-check": (
        "Tim only (spends real money). Sends a few sample choices to the judge AI and shows "
        "what it says and what each answer cost. --max-dollars is needed; the check stops before "
        "any call that could pass it. Add --dry-run to try it with pretend AI and no cost.",
        "uv run python main.py judge-check --max-dollars 1 --dry-run",
    ),
    "calibrate": (
        "Tim only (spends real money). Measures what a decision costs on each AI model, matches "
        "how hard the four main models think, and estimates the cost of a game week and of the "
        "pilot. --max-dollars is needed; it stops before any call that could pass it. Add "
        "--dry-run for a practice estimate with pretend AI and no cost. --apply saves a good "
        "real result in the models file.",
        "uv run python main.py calibrate --max-dollars 1 --dry-run",
    ),
    "decisions": (
        "Prints every decision an AI player made, one block each: when, what it saw, "
        "the options it weighed, what it chose and which of its values that served or hurt. "
        "Add --player to see one player only.",
        "uv run python main.py decisions --run t4 --player 1",
    ),
    "headless": (
        "Plays the game with no window, as fast as the computer can. Good for quick tests.",
        "uv run python main.py headless --ticks 1440 --seed 1",
    ),
    "resume": (
        "Continues a saved game with no window, from where it stopped. A game with real AI asks "
        "you to type yes first (it shows how much it may spend). A pilot stops by itself at its "
        "planned end.",
        "uv run python main.py resume p35 --ticks 1440",
    ),
    "report": (
        "Prints a balance report of a saved game: how food, health and the like went.",
        "uv run python main.py report --run p35",
    ),
    "measures": (
        "Prints the weekly numbers of a saved game (one line per week).",
        "uv run python main.py measures --run p35",
    ),
    "export": (
        "Writes every table of a saved game as spreadsheet (CSV) files you can open in Excel.",
        "uv run python main.py export --run p35",
    ),
    "watch": (
        "Opens the window and shows a saved game while it plays. The game saves as it goes.",
        "uv run python main.py watch --run p35",
    ),
    "view": (
        "Shows a quick preview of the island in a window. Nothing is saved. "
        "With a picture file name it saves one picture and closes.",
        "uv run python main.py view --run p35 --ticks 60 --screenshot runs/p35/preview.png",
    ),
    "guide": (
        "Rewrites this guide file from the program's own lists.",
        "uv run python main.py guide",
    ),
}

_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Terrain",
        "The ground, water and land markers.",
        (
            "grass",
            "sand",
            "tree",
            "stump",
            "spring",
            "lake",
            "coast",
            "farmland_empty",
            "farmland_planted",
            "farmland_growing",
            "farmland_ready",
            "farmland_failed",
            "rocky",
            "rocky_depleted",
            "quarry",
            "quarry_depleted",
            "claim_border_1",
            "claim_border_2",
            "claim_border_3",
            "claim_border_4",
            "boundary_stake",
            "snow",
            "drought",
            "overlay_night",
            "overlay_rain",
            "overlay_storm",
        ),
    ),
    (
        "Plants",
        "Things that grow and can be picked.",
        (
            "berries",
            "mushrooms",
            "roots",
            "herbs",
            "healing_herbs",
            "mild_poison",
            "strong_poison",
        ),
    ),
    (
        "Animals",
        "Wild and kept animals.",
        (
            "rabbit",
            "deer",
            "boar",
            "fish",
            "bird",
            "nest_eggs",
            "goat",
            "chicken",
            "wild_dog",
        ),
    ),
    (
        "People",
        "The four players and the villagers (each villager looks like one of six).",
        (
            "player_1",
            "player_2",
            "player_3",
            "player_4",
            "villager_1",
            "villager_2",
            "villager_3",
            "villager_4",
            "villager_5",
            "villager_6",
        ),
    ),
    (
        "State markers",
        "Small signs drawn on a person.",
        ("marker_sick", "marker_injured", "marker_sleeping", "marker_grave"),
    ),
    (
        "Buildings and structures",
        "Things people build.",
        (
            "house",
            "hearth",
            "field",
            "storehouse",
            "workshop",
            "pen",
            "campfire",
            "shrine",
            "offering_spot",
            "granary",
            "bridge",
            "monument",
            "great_tree",
            "lake_dock",
        ),
    ),
)


def _source(entry: dict[str, Any]) -> str:
    src = str(entry.get("source", "code"))
    if src == "code":
        text = "drawn by the program"
    else:
        text = f"{src} {entry.get('col')},{entry.get('row')}"
    if entry.get("flip"):
        text += f", flipped ({entry['flip']})"
    return text


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(cell.replace("|", "/") for cell in row) + " |")
    return lines


def _items_group(items: dict[str, dict[str, Any]], names: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [(f"`{n}`", _source(items[n])) for n in names if n in items]


def _subcommands(parser: argparse.ArgumentParser) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            helps = {a.dest: (a.help or "") for a in action._choices_actions}
            for name in action.choices:
                found.append((name, helps.get(name, "")))
    return found


def _options(parser: argparse.ArgumentParser, name: str) -> list[str]:
    sub = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            sub = action.choices[name]
    out: list[str] = []
    if sub is None:
        return out
    for a in sub._actions:
        if a.help == argparse.SUPPRESS or isinstance(a, argparse._HelpAction):
            continue
        if a.option_strings:
            out.append(f"`{a.option_strings[0]}` ({'needed' if a.required else 'optional'})")
        else:
            out.append(f"`{a.dest}` (needed)")
    return out


def render_guide(root: Path) -> str:
    from ai_island.cli import build_parser

    with (Path(root) / "config" / "assets.toml").open("rb") as fh:
        assets = tomllib.load(fh)
    items: dict[str, dict[str, Any]] = assets["items"]
    icons: dict[str, str] = assets.get("activity_icons", {})
    words: dict[str, str] = assets.get("activity_words", {})

    out: list[str] = [
        "# AI Island guide",
        "",
        "This file is written by the program (`uv run python main.py guide`). "
        "Do not edit it by hand: your changes would be overwritten.",
        "",
        "## What this is",
        "",
        "AI Island is a small island with four players and their villagers. "
        "You watch it in a window. This guide says which commands start things, "
        "which keys and buttons the window understands, and what every picture means.",
        "",
        "## Commands",
        "",
        "Type these in a terminal (PowerShell) opened in the project folder. "
        "Copy the example line, and change the run name `p35` to your own name if you like.",
        "",
    ]
    parser = build_parser()
    for name, help_text in _subcommands(parser):
        what, example = _COMMANDS.get(name, (help_text, f"uv run python main.py {name}"))
        out += [f"### `{name}`", "", what, ""]
        opts = _options(parser, name)
        if opts:
            out += ["Options: " + ", ".join(opts) + ".", ""]
        out += ["```", example, "```", ""]

    out += [
        "## Keys, buttons and mouse",
        "",
        "Everything the window reacts to. Press `H` in the window to see the same list.",
        "",
    ]
    for kind, title in (("key", "Keys"), ("button", "Buttons"), ("mouse", "Mouse")):
        out += [f"### {title}", ""]
        out += _table(
            ("Name", "What it does"),
            [(f"`{b.name}`", b.action) for b in KEY_TABLE if b.kind == kind],
        )
        out.append("")

    out += [
        "## Pictures",
        "",
        "Every picture comes from one of two sheets, named by column and row "
        "(`kenney 3,4` is column 3, row 4 of the Kenney sheet; `tiny_creatures` is the "
        "animal sheet). Some are drawn by the program itself. "
        "Nothing is shown in the window that is not listed here.",
        "",
    ]
    listed: set[str] = set()
    for title, intro, names in _GROUPS:
        out += [f"### {title}", "", intro, ""]
        out += _table(("Name", "Picture from"), _items_group(items, names))
        out.append("")
        listed.update(names)

    damaged = [k[len("damaged_") :] for k in items if k.startswith("damaged_")]
    out += [
        "### Damaged and unfinished buildings",
        "",
        "A damaged building shows a crack drawn over it. A building still being built "
        "looks like the normal sprite faded, with a progress bar.",
        "",
    ]
    out += _table(
        ("Building", "Normal picture", "Damaged picture", "While being built"),
        [
            (
                f"`{k}`",
                _source(items[k]) if k in items else "n/a",
                _source(items[f"damaged_{k}"]),
                "normal sprite faded with a progress bar",
            )
            for k in damaged
        ],
    )
    out.append("")
    listed.update(f"damaged_{k}" for k in damaged)

    item_names = tuple(k for k in items if k.startswith("item_"))
    tool_names = tuple(k for k in items if k.startswith("tool_"))
    ui_names = tuple(k for k in items if k.startswith("ui_"))
    for title, intro, names in (
        ("Items", "Things people carry.", item_names),
        ("Tools", "Basic and better tools.", tool_names),
        ("Interface", "Pictures used by the window itself.", ui_names),
    ):
        out += [f"### {title}", "", intro, ""]
        out += _table(("Name", "Picture from"), _items_group(items, names))
        out.append("")
        listed.update(names)

    rest = tuple(k for k in items if k not in listed)
    if rest:
        out += ["### Other", ""]
        out += _table(("Name", "Picture from"), _items_group(items, rest))
        out.append("")

    out += [
        "## What people are doing (bubbles)",
        "",
        "A small bubble over each person shows what they are doing now. "
        "It is a picture, or a word when no picture fits. Press `B` to switch bubbles.",
        "",
    ]
    rows = []
    for kind in ACTIVITY_KINDS:
        icon = icons.get(kind, "word")
        if icon == "word":
            shown = f'the word "{words.get(kind, kind)}"'
        else:
            shown = f"picture `{icon}` ({_source(items[icon]) if icon in items else 'n/a'})"
        rows.append((f"`{kind}`", shown))
    out += _table(("Activity", "Shown as"), rows)
    out.append("")
    return "\n".join(out)
