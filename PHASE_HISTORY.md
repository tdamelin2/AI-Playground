# Phase history

How AI Island was built, phase by phase. This file takes the place of the original git history, which isn't included in this public copy. Everything below comes from that history (54 commits, 1–5 November 2026), the phase records in `handoffs/` and the specs in `phases.md`. Times are local time (Israel) as git recorded them.

Each phase ran the same way (see "How it was built" in the README): two AI planning managers wrote plans separately, one merged plan was approved by me, then AI coder, tester and debugger agents worked in rounds until every acceptance criterion had a passing test. "Round 0" is the first build; later rounds are fixes.

## Summary

| Phase | What it added | Acceptance criteria | Plan → done | Rounds |
|---|---|---|---|---|
| Setup | Project created on the two-manager build system | – | 1 Nov | – |
| 1 | Skeleton and the island | 22 | 1 Nov, 18:52 → 19:23 (+ a second round to 20:00) | 0–2 |
| 1.5 | Colour and time-true movement | 19 | 2 Nov, 09:12 → 09:54 | 0 |
| 2 | Bodies, villagers, actions and senses | 32 | 2 Nov, 12:14 → 15:23 | 0–1 |
| 3 | Observer screen, run control and exports | 16 | 2 Nov, 18:06 → 20:11 | 0–1 |
| 3.5 | Observer comfort and the player guide | 16 | 3 Nov, 11:20 → 12:47 | 0 |
| 4 | Minds and AI connections | 24 | 4 Nov, 11:19 → 13:20 | 0 |
| 5 | Judge, measurement, calibration and pilot tools | 11 | 4 Nov, 16:04 → 18:39, then 7 more rounds to 5 Nov, 08:59 | 0–8 |
| 6 | Tuning and launch | 5 | Not started | – |

Phases 1–4 were built and tested without any real AI calls (tests use a fake AI). The first money was spent after Phase 5, on calibration runs I started myself.

## Setup — 1 November

Commit `a2f7826`. Copied my two-manager build system into a new project and added the AI Island specs (`docs/`), the phase list (`phases.md`), project rules for the agents (`CLAUDE.md`, `AGENTS.md`), safety hooks that block agents from reading the API key file, and the Kenney art pack.

## Phase 1 — Skeleton and the island (1 November)

The island exists and runs on its own: weather and seasons change, plants grow back, animals breed and wander, and wild dogs roam in packs. A whole game year runs headless (no window) in under a second, and the same seed always gives exactly the same event history. Each game is saved in its own database and can be resumed. A read-only map viewer shows the island.

- Round 1 fixed the unclaimed-land pool, which neither plan had defined concretely.
- Round 2 reopened the phase after my review: the viewer was blurry on my high-resolution screen and nothing seemed to move. The fix made the window DPI-aware, scaled tiles to whole numbers, lightened the grass tile and added a speed control.

## Phase 1.5 — Colour and time-true movement (2 November)

A short phase I added between 1 and 2 after watching the island. The map switched to the Kenney colour sheet, animals use the Tiny Creatures pack, and every animal and wild dog moves on its own timer and glides between tiles instead of jumping in lockstep. Daylight fades at dusk and dawn. Done in one round with no fixes.

Before it, commits `e50a070` and `cd83032` updated the docs for colour and Tiny Creatures and fixed the phase launcher so it accepts half-step phase numbers.

## Phase 2 — Bodies, villagers, actions and senses (2 November)

The whole game runs without any AI, played by rule-based and scripted players. Players get hungry, thirsty, cold and tired, can get sick or hurt, and can die and come back at home. Each has a hidden wellbeing score they only feel as words. Each starts with 3 villagers who work, grow loyal or fed up, and can leave. All 39 actions take game time, and players only learn about the world through their senses.

- Round 0 was long: every agent hit its turn limit and was restarted. The scripted test scenario needed two extra passes, and balance was tuned so neglected villagers leave before they die.
- Round 1 fixed the remaining test failures.
- Afterwards (`81ee189`) I raised the agents' step limits and added a rule that every plan must include worked examples for each number and name it tests.

## Phase 3 — Observer screen, run control and exports (2 November)

The full watching screen: a top bar with clock, season, pause/resume, speed and autosave; the map with buildings and land borders; and tabs for chats, choice points, world history, players and spending. Games can be paused, closed and resumed without losing anything, crash recovery replays from the last autosave, and every table exports to CSV. One small fix round.

A "verified replay" check, proposed by the Codex planner, caught two real problems during this phase: a difference in config key order and scripted-player state that wasn't being saved.

## Phase 3.5 — Observer comfort and the player guide (3 November)

Another phase I added after watching Phase 3. Activity bubbles over people, a coloured village guide and chat filters, a hideable side panel, and a resizable window with full screen and text scaling. Clicking a name or a person makes the map follow them and opens an Inspector with their needs, health, belongings and mood, plus graphs of wellbeing, trust and anger. Thefts, attacks, deaths and land claims flash on the map. It also added a mini-map, a key list, a screenshot key and a generated plain-language guide (`docs/guide.md`). Before it, commit `ffb928a` fixed the Telegram connector so it accepts half-step phase numbers. Done in one round with no fixes.

## Phase 4 — Minds and AI connections (4 November)

The island gets AI players. Each has a ranked list of 14 values, a memory, and three ways of deciding: instant reflexes for urgent needs, a cheap helper model for routine things, and its main model for big choices. A stressed ("hooked") player decides alone with fewer memories. Every big choice is recorded with the options it weighed. Connections to Anthropic, OpenAI, Google, xAI and Mistral, a spending counter with a hard cap, and model research for all nine AI roles. Built and tested with the fake AI only; nothing was spent. Done in one round with no fixes.

## Phase 5 — Judge, measurement, calibration and pilot tools (4–5 November)

A neutral Mistral judge labels important choices, writes daily summaries and weekly player profiles, and flags deaths, betrayals and new beliefs. It never sees which company is behind a player. New weekly measures compare what players say they value with what the judge sees them do. Commands for the paid steps: `calibrate`, `judge-check`, the pilot and its analysis, and a launch check. Done after one fix round (18:39), with nothing spent.

I then ran the first paid step, `calibrate`, which measures each model's cost and how much it "thinks". Each run surfaced a problem, which reopened the phase:

| Round | What my calibration run showed | Fix |
|---|---|---|
| 2 | Anthropic rejected the reply format before any charge | Closed the reply schemas so strict modes accept them |
| 3 | Anthropic: "Schema is too complex" | Simpler schemas for that provider |
| 4 | A config setting was never applied (re-plan) | Fixed the config default |
| 5 | Finished ($0.76), but some replies broke list-length limits and one main model reported no thinking | The prompt now states the limit (at most 4 values); calibration handles a model that doesn't think |
| 6 | Finished ($1.06); thinking amounts still didn't match across models | Added a forced-thinking step for Anthropic |
| 7 | Finished ($1.17); Anthropic refused the forced setting for its model | Added higher effort levels ("xhigh", "max") for Claude and GPT instead |
| 8 | Finished ($2.43); measured thinking at every setting | Saved the settings I chose: Claude and GPT main models at "xhigh", Gemini and Grok at "medium" |

The calibration runs that finished cost about $5.43 in total. The last commit, `35d09e9` (5 November, 08:59), is "phase 5: done (round 8)".

## After Phase 5 (not in git)

- I ran a 3-game-week pilot with all four AI players: 11,528 AI calls, about $11.10 against a $2.77 estimate. The run's output stays on my laptop (run folders are never committed).
- The whole system ran end to end, but a review of the logs found game bugs that blocked most actions: item names in prompts didn't match what the eat and gather actions accept, players couldn't target anyone by name (so talk, trade and every action aimed at a person failed), and spoken words never reached the listener. The pilot therefore says nothing yet about how the AIs behave.
- Fixing those bugs and a second pilot are planned and not started. Phase 6 (tuning and the real run) is not started.
