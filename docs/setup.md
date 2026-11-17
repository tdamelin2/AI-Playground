# AI Island — Setup

Everything Tim does by hand before Phase 1, step by step. No game code is written here.

- **Time:** about 1.5–2 hours the first time (most of it is creating accounts and waiting for installs).
- **Money:** nothing for Phases 1–5. The five API accounts only need credit before the first paid steps, after Phase 5. You also need the Claude subscription you use for Claude Code, and a ChatGPT account for Codex.
- **What you end up with:** every tool installed and checked, the project in `<project folder>` with its first saved version (commit), and the safety checks passed. Then you start Phase 1.

Do the parts in order. Each step says what it's for, what to type and what you should see.

---

## Part 0 — How to follow this guide

**Open PowerShell:** press the Windows key, type `PowerShell`, and click **Windows PowerShell** (not "as administrator"). The prompt starts with `PS C:\Users\<you>>`.

**Running a command:** copy the grey box, right-click in the PowerShell window to paste, press Enter.

**The "new window" rule:** after installing a program, close PowerShell and open a new window before using it. Otherwise Windows won't find the new program ("is not recognized as the name of a cmdlet").

**Going to the project folder:** most steps start with

```powershell
cd <project folder>
```

**One-time script permission.** Windows blocks scripts like the phase launcher by default. Allow scripts you made or copied yourself, for your user only:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Answer `Y` if asked. Check: `Get-ExecutionPolicy -Scope CurrentUser` prints `RemoteSigned`.

---

## Part 1 — Put the project in its place

**Why:** the project must live outside OneDrive. OneDrive syncing can lock the game's save database in the middle of a write, and it also slows git down. The project is at `<project folder>`, which is outside OneDrive and has no spaces in its path.

- [x] **1.1 The folder is in place** at `<project folder>`. Nothing to move. Don't keep a second working copy inside OneDrive.

- [ ] **1.2 Check it.** `cd <project folder>; Get-ChildItem` lists `Overview.md`, `phases.md`, `docs`, `assets`, `scripts` and the rest.

- [x] **1.3 Art packs.** The Kenney pack is included. You add Tiny Creatures (the animals) yourself in step 3.2. The unused Urizen tileset was left out of this folder, so there's nothing to remove.

- [ ] **1.4 Show hidden folders (helps later).** In File Explorer: **View → Show → Hidden items**. The project has hidden folders (`.claude`, `.agents`, `.codex`) that must stay with it.

---

## Part 2 — Install the tools

For each tool: run the install, open a new PowerShell window, run the check. If the check already works before you install, the tool is there; skip to the next one.

| Tool | What it's for |
| --- | --- |
| Git | Saves versions of the project, so any phase can be undone |
| Windows Terminal | Lets the launcher open the Claude and Codex tabs side by side |
| Node.js | Runs Codex and the Telegram connector |
| uv | Installs Python and every library the game uses, at fixed versions |
| Python 3.13 | The language the game is written in |
| Claude Code | The Claude manager and its coders, tester and debugger |
| Codex CLI | The second manager, which plans each phase alongside Claude |
| Ollama | Runs the small local model the players use to search their memories |

- [ ] **2.1 Git for Windows**

  ```powershell
  winget install --id Git.Git -e
  ```

  (Or download from git-scm.com/downloads/win and click through the installer with the default choices.)
  New window, then check: `git --version` prints `git version 2.…`.

  Tell git who you are (used to label saved versions):

  ```powershell
  git config --global user.name "Tim"
  git config --global user.email "you@example.com"
  ```

- [ ] **2.2 Windows Terminal** — usually already part of Windows 11. Check: `wt --version` (a small window with the version may open). If it's missing, install **Windows Terminal** from the Microsoft Store.

- [ ] **2.3 Node.js (LTS)**

  ```powershell
  winget install --id OpenJS.NodeJS.LTS -e
  ```

  New window, then check: `node --version` prints `v18` or higher (the Telegram connector needs 18+).

- [ ] **2.4 uv**

  ```powershell
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  (Alternative: `winget install --id=astral-sh.uv -e`.)
  New window, then check: `uv --version` prints `uv 0.…`.

- [ ] **2.5 Python 3.13 (through uv)**

  ```powershell
  uv python install 3.13
  ```

  Check: `uv run --python 3.13 python --version` prints `Python 3.13.…`.
  Don't install Python from python.org or the Microsoft Store as well; uv manages it.

- [ ] **2.6 Claude Code**

  ```powershell
  irm https://claude.ai/install.ps1 | iex
  ```

  (Alternative: `winget install Anthropic.ClaudeCode`, but that version doesn't update itself.)
  The installer shows no progress while it downloads; wait for the prompt to come back. New window, then check: `claude --version` prints a version, and `claude doctor` shows no errors.
  Sign in: run `claude`, follow the browser prompt, then type `/exit`. Claude Code needs a paid Claude plan (Pro, Max, Team or Enterprise) or a Console account.

- [ ] **2.7 Codex CLI**

  ```powershell
  npm install -g @openai/codex
  ```

  Use exactly `@openai/codex`; a package called just `codex` is something else. New window, then check: `codex --version`. You sign in during Part 5.

- [ ] **2.8 Ollama and the embedding model**

  1. Download **OllamaSetup.exe** from ollama.com/download and run it. It doesn't need administrator rights, and afterwards it runs in the background with a llama icon in the system tray.
  2. New window, then check: `ollama --version`.
  3. Download the embedding model (small, about 270 MB):

     ```powershell
     ollama pull nomic-embed-text
     ```

  4. Check: `ollama list` shows `nomic-embed-text`.

  Ollama doesn't use the Intel Arc graphics chip on Windows yet, which is fine: this model runs well on the processor. If `ollama` commands later say they can't connect, open **Ollama** from the Start menu to start it again.

- [ ] **2.9 DB Browser for SQLite (optional)** — download from sqlitebrowser.org to look inside a run's database (`runs\<name>\run.db`) by hand. Only open a database while the game isn't running.

---

## Part 3 — Fonts and art

- [x] **Kenney 1-Bit Pack** is already in `assets\kenney_1bit\` (unchanged, with its `License.txt`). The game uses its colour version for everything except the animals; anything neither pack has is drawn in code.
- [ ] **3.1 monogram font** (by datagoblin, free, CC0). The observer screen uses it from Phase 3.
  1. Open datagoblin.itch.io/monogram and click **Download Now**. It's "name your own price": you can choose to pay nothing and go straight to the downloads.
  2. Download **monogram.zip**.
  3. Unzip it into `<project folder>\assets\fonts\monogram\`, so that `monogram.ttf` sits directly in that folder (next to the `README.txt` that's already there). Keep the license file if the zip has one.
  4. Check: `Test-Path <project folder>\assets\fonts\monogram\monogram.ttf` prints `True`.
- [ ] **3.2 Tiny Creatures** (by Clint Bellanger, free, CC0). The animals on the map come from it. Do this before starting Phase 1.5.
  1. Open clintbellanger.itch.io/tiny-creatures and click **Download Now**. It's "name your own price": you can choose to pay nothing and go straight to the downloads.
  2. Download **tiny-creatures.zip**.
  3. Unzip it into `<project folder>\assets\tiny_creatures\`. The folder is already there, empty except for a small `.gitkeep` file that lets git keep the empty folder; leave that file alone. If the zip puts everything inside one extra folder, that's fine. Don't rename or edit anything from the pack.
  4. Check: `(Get-ChildItem <project folder>\assets\tiny_creatures -Recurse -Filter *.png).Count` prints a number above 0.
  5. Save it, so the phase can start from a clean folder: `git add -A; git commit -m "add Tiny Creatures"`.

---

## Part 4 — API accounts, keys and spend limits

**When:** you can do this now, or any time before the paid steps after Phase 5. Phases 1–5 don't use any key, so you can wait until you've watched the game in the observer (after Phase 3) and decided it's worth paying for.

**Why five companies:** each player's whole mind comes from one company (Claude, GPT, Gemini, Grok), and the judge is Mistral so it can't favour its own maker's player.

**Two safety nets:** the game has its own $100 cap. On top of it, set a limit at each company so a bug can never spend more. Prefer prepaid credit with automatic top-up **off**: when the credit runs out, calls simply stop.

**Rules for keys:**
- Name every key `ai-island`, so you can find and revoke it later.
- A key is shown only once. Paste it straight into `.env` (step 4.6). Never into a chat, a doc, or a screenshot.
- If a key ever leaks, delete it on the company's site and make a new one.

- [ ] **4.1 Anthropic (Player 1)** — platform.claude.com
  1. Sign up (this is separate from your Claude subscription) and add a payment method and a small credit under **Billing**.
  2. Set a monthly limit: click your organization name (bottom left) → **Organization settings** → **Billing** → **Spend limits** → set about $30. Add a notification at about $24.
  3. Create the key on the **API keys** page, named `ai-island`.

- [ ] **4.2 OpenAI (Player 2)** — platform.openai.com
  1. Sign up, add prepaid credit under **Settings → Billing**, and leave auto recharge off.
  2. Create a project named `ai-island`. In the project's **Limits**, use **Set budget** for about $30 a month, with alert emails at 80% and 95%.
  3. In the project's **API keys**, click **Create new secret key**, named `ai-island`.

- [ ] **4.3 Google Gemini (Player 3)** — aistudio.google.com
  1. Sign in with your Google account and click **Get API key** to create a key (it creates a project for it).
  2. Paid use needs a billing account: in AI Studio go to **Projects** (aistudio.google.com/projects) and link a billing profile to the key's project.
  3. Set a cap: open the **Spend** tab (aistudio.google.com/spend), find **Monthly spend cap** for that project and enter about $30. It takes about 10 minutes to start working.

- [ ] **4.4 xAI (Player 4)** — console.x.ai
  1. Sign up and load prepaid credit under **Billing**. Leave auto top-up off. Without credit, every request is refused, which is the safe default.
  2. If offered, set a monthly cap with the 80% warning.
  3. Create the key on the **API Keys** page, named `ai-island`.

- [ ] **4.5 Mistral (judge)** — console.mistral.ai
  1. Sign up. The free tier is enough to start; for the real run, add prepaid credit so the judge never stops mid-run.
  2. Set a limit: admin.mistral.ai → **Subscriptions → Billing**, with an organization monthly limit of about $10 (the judge is cheap).
  3. Create the key under **API keys**, named `ai-island`.

- [ ] **4.6 Paste the keys into `.env`.** In PowerShell:

  ```powershell
  cd <project folder>
  notepad .env
  ```

  Paste each key right after its `=`, with no spaces or quotes:

  ```
  ANTHROPIC_API_KEY=sk-ant-...
  OPENAI_API_KEY=sk-...
  GEMINI_API_KEY=...
  XAI_API_KEY=xai-...
  MISTRAL_API_KEY=...
  ```

  Save and close Notepad. The game reads this file when it runs. The AI agents are blocked from opening it, and git never saves it.

---

## Part 5 — Set up the two managers

These are steps 2–4 of `SETUP.md`, done in this folder.

- [ ] **5.1 Trust the folder in Codex.**

  ```powershell
  cd <project folder>
  codex
  ```

  Sign in with your ChatGPT account when asked, then answer **yes** to trusting the folder. Type `/status` and check the permissions line says `codex-planner`. Type `/exit`.

- [ ] **5.2 Approve the Telegram connector in Claude (if you'll use Telegram).** Run `claude` in the folder. If it asks whether to use the `telegram` server from `.mcp.json`, approve it. Type `/exit`.

- [ ] **5.3 Safety test: the planning gate.**

  ```powershell
  $j = @{ tool_name = 'Write'; tool_input = @{ file_path = "$PWD\handoffs\phase-99.md" }; cwd = "$PWD" } | ConvertTo-Json -Depth 5
  $j | powershell -NoProfile -ExecutionPolicy Bypass -File .claude\hooks\guard-paths.ps1 -Agent manager; "exit code: $LASTEXITCODE"
  ```

  Expected: a message about the planning gate, then `exit code: 2`.

- [ ] **5.4 Safety test: the key file is protected.**

  ```powershell
  $j = @{ agent_type = 'coder-a'; tool_input = @{ command = 'Get-Content .env' } } | ConvertTo-Json -Depth 5
  $j | powershell -NoProfile -ExecutionPolicy Bypass -File .claude\hooks\block-dangerous.ps1; "exit code: $LASTEXITCODE"
  ```

  Expected: `block-dangerous: reading the .env file or the API keys is not allowed.`, then `exit code: 2`.

- [ ] **5.5 Safety test: Codex can't write files.** Run `codex` and type
  `create a file called test.txt in the project folder with the word hello`.
  Expected: the write fails or Codex asks permission. Answer no, then `/exit`.

- [ ] **5.6 Telegram (optional).** Follow `SETUP.md` step 4 (bot-to-bot setting, the three `setx` lines, then `node scripts\telegram\telegram-mcp.mjs --selftest`). If you skip it, phases still run; Claude just doesn't ask Codex questions about its plan.

---

## Part 6 — Save the first version

- [ ] **6.1 Make the folder a git repository and save:**

  ```powershell
  cd <project folder>
  git init
  git add -A
  git commit -m "Setup: AI Island on the two-manager system"
  ```

- [ ] **6.2 Check the keys weren't saved:** `git ls-files .env` prints nothing, and `git status` says `nothing to commit, working tree clean`.

If `git status` later shows files you didn't expect before starting a phase, the launcher stops and tells you; save them with `git add -A; git commit -m "before phase N"`.

---

## Part 7 — Final check

Open a **new** PowerShell window and run:

```powershell
cd <project folder>
git --version; wt --version; node --version; uv --version
uv run --python 3.13 python --version
claude --version; codex --version
ollama list
Test-Path assets\fonts\monogram\monogram.ttf
git log --oneline
```

## Done when

- [ ] Every command above prints a version (or a list) instead of "is not recognized"
- [ ] `ollama list` shows `nomic-embed-text`
- [ ] `Test-Path …monogram.ttf` prints `True` (needed from Phase 3)
- [ ] `git log --oneline` shows the setup commit, and `.env` is not tracked
- [ ] Safety tests 5.3 and 5.4 gave `exit code: 2`; Codex refused to write in 5.5
- [ ] All five keys are in `.env` with spend limits set (needed only from the paid steps after Phase 5; this can wait)

Then start Phase 1:

```powershell
cd <project folder>
.\scripts\start-phase.ps1 -Phase 1
```

Two tabs open. Leave the Codex tab open until it says you can close it. When Claude shows its summary, reply `go`.

---

## If something goes wrong

| What you see | What to do |
| --- | --- |
| `… is not recognized as the name of a cmdlet` | Open a new PowerShell window. If it still fails, run that tool's install step again |
| `running scripts is disabled on this system` | Run the script-permission command in Part 0 |
| `'irm' is not recognized` | You're in CMD, not PowerShell. Open Windows PowerShell |
| The launcher says "this folder has no saved version" | Do Part 6 |
| The launcher says "there are unsaved changes" | `git add -A; git commit -m "before phase N"`, then start again |
| `ollama` says it can't connect | Start **Ollama** from the Start menu |
| Codex `/status` doesn't show `codex-planner` | The folder isn't trusted yet: run `codex` in `<project folder>` and answer yes |
| A key stops working | Check the company's billing page: the credit may be used up or the monthly limit reached |
| A key may have leaked | Delete it on the company's site, make a new one, paste it into `.env` |

## Sources

- Claude Code install: code.claude.com/docs/en/setup
- uv on Windows: pydevtools.com/handbook/how-to/how-to-install-uv-on-windows
- Ollama on Windows: docs.ollama.com/windows
- monogram font: datagoblin.itch.io/monogram
- Claude Console spend limits: xray.tech/post/how-to-set-spend-limits-in-claude-console
- OpenAI keys and project budgets: support.cmts.jhu.edu (Guide to Managing API Keys and Usage Limits on platform.openai.com)
- Gemini spend caps: blog.google (Giving you more transparency and control over your Gemini API costs, March 2026)
- xAI keys and billing: apidog.com/blog/grok-api-key
- Mistral usage limits: docs.mistral.ai/admin/billing-usage/usage-limits
