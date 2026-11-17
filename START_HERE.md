# Start here (Tim)

This folder is AI Island, built on your two-manager system. It's a fresh copy of
Main_AI_Developer with the game added; Main_AI_Developer itself is unchanged. It
replaces the older `AI_Playground\ai_island` folder, which you can delete.

## What's already done
- `Overview.md` and `phases.md`: the game and its six build phases, written from your
  AI Island docs, with checkable goals for every phase.
- `docs/`: your five AI Island docs. These are now the master copies.
- `CLAUDE.md`: your AI Island rules added next to the system's rules, and the project
  commands filled in.
- `assets/`: the art packs: Kenney 1-Bit (in colour), and `tiny_creatures/` for the animals, which you download yourself (docs/setup.md step 3.2).
- `.env`: an empty key file, protected so no AI agent can open it.

## What you do, one step at a time
0. This folder lives at `<project folder>`, outside OneDrive (OneDrive syncing can lock the
   game's save files mid-write). Open PowerShell there for every step below:

       cd <project folder>
1. Finish the setup in `docs/setup.md` (installs, the monogram font, `SETUP.md` steps
   2-4 for Codex and Telegram). API keys can wait until after Phase 5.
2. Save the first version. In PowerShell, in this folder:

       git init; git add -A; git commit -m "Setup: AI Island on the two-manager system"

3. Start Phase 1:

       .\scripts\start-phase.ps1 -Phase 1

   When Claude shows its summary, reply `go`.
4. After each phase, do the "Tim's review" steps listed under that phase in
   `phases.md`. Phases 1-5 cost nothing. After Phase 3 you can already watch the whole
   game in the observer window, played by simple rule-based players, and decide
   whether it's worth paying for the AIs. The first steps that spend real money come
   after Phase 5 (calibration and the pilot), and the real run after Phase 6. Only you
   run those, and each command has a dollar limit.

## Changes from your original plan
- The free parts come first: the island (1), the game rules (2), and the full
  observer screen with saving and exports (3), all watched with rule-based players.
  The AI minds come after (4), then the judge, calibration and pilot tools (5). Nothing
  costs money until after Phase 5.
- The old Phase 5 (pilot, tuning and launch) is now split: 5 builds the pilot tools,
  you run the pilot, and 6 tunes the world from what the pilot showed. The build
  agents never spend money themselves, and a pilot takes hours, so the build has to
  pause there for you.
- A stressed ("hooked") player still thinks with its own main model, just alone and
  with fewer memories, and every one of those choices is recorded.
