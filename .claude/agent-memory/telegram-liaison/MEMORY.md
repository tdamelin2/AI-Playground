# telegram-liaison memory

## Lessons
- tg_check can fail once on a transient network error; one retry worked.

- Half-step phases work since Tim's connector fix before P3.5: pass the real number (3.5) to tg_close and use it in qids (P3.5-C-CDX-01). Never round it down.

- Implementation-mechanism questions (how a guard/lock works) can get "Not in our plan"; Codex plans state contracts, not mechanisms.

- Cost-allocation/estimate-formula questions also get "Not in our plan" (P3, P5).

## Log

### P5 | telegram-liaison | 15:59-16:02 (3 min) | sonnet
- Asked: 2 to codex | Follow-ups: 0
- Answered: 1 (+1 "Not in our plan": P5-C-CDX-02) | No answer: none
- Telegram problems: none

### P4 | telegram-liaison | 11:13-11:15 (2 min) | sonnet
- Asked: 0 of 3 (Telegram down) | Follow-ups: 0
- Answered: 0 | No answer: P4-C-CDX-01, -02, -03 (not asked)
- Telegram problems: tg_check failed twice (network error); tg_close still accepted phase 4

### P3.5 | telegram-liaison | 11:15-11:17 (2 min) | sonnet
- Asked: 0 (close only) | Follow-ups: 0
- Answered: 0 | No answer: none
- Telegram problems: first tg_check network error, retry succeeded; tg_close accepted 3.5

### P3 | telegram-liaison | 16:14-16:17 (3 min) | sonnet
- Asked: 2 to codex | Follow-ups: 0
- Answered: 1 (+1 "Not in our plan": P3-C-CDX-02) | No answer: none
- Telegram problems: none

### P2 | telegram-liaison | 11:24-11:26 (2 min) | sonnet
- Asked: 0 (close only) | Follow-ups: 0
- Answered: 0 | No answer: none
- Telegram problems: none

### P1.5 | telegram-liaison | 09:09-09:11 (2 min) | sonnet
- Asked: 0 (close only) | Follow-ups: 0
- Answered: 0 | No answer: none
- Telegram problems: tg_close rejected phase 1.5; closed with phase 1

### P1 | telegram-liaison | 18:48-18:52 (4 min) | sonnet
- Asked: 2 to codex | Follow-ups: 0
- Answered: 2 | No answer: none
- Telegram problems: first tg_check network error, retry succeeded
