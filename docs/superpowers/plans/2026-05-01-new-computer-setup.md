# New Computer Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the Kalshi weather trading project fully running on a new Windows machine so development can resume exactly where it left off.

**Architecture:** Two-phase setup. Phase A is manual file transfers that must happen before Claude Code can help (skills folder + private key + data folder). Phase B is fully automated by Claude — clone, install deps, configure env, verify. Ends with a single prompt to resume the feature roadmap.

**Tech Stack:** Python 3.12+, Git, Claude Code (already installed), pip, existing `requirements.txt`

> **Legend:** 🧑 = you must do this manually | 🤖 = paste into Claude Code and it does it

---

## Phase A — Manual transfers (do these FIRST, before opening Claude Code)

These cannot be automated because Claude Code needs the skills folder to exist before it can use skills, and the private key is a secret that must never be typed into a chat.

---

### Task A.1: Copy skills folder from old computer

**Files:**
- Source (old computer): `C:\Users\thesa\.claude\skills\`
- Destination (new computer): `C:\Users\<yourname>\.claude\skills\`

- [ ] 🧑 **Step 1: On the OLD computer — zip the skills folder**

Open File Explorer, navigate to:
```
C:\Users\thesa\.claude\
```
Right-click the `skills` folder → Send to → Compressed (zipped) folder.
Save the zip as `claude-skills.zip` on a USB drive or upload to Google Drive.

- [ ] 🧑 **Step 2: On the NEW computer — restore the skills folder**

Copy `claude-skills.zip` to the new machine.
Extract it so the result is:
```
C:\Users\<yourname>\.claude\skills\
```
Where `<yourname>` is your Windows username on the new machine.

- [ ] 🧑 **Step 3: Verify the skills are present**

Open File Explorer and confirm this folder exists and is not empty:
```
C:\Users\<yourname>\.claude\skills\superpowers-writing-plans\
```
If you can see `SKILL.md` inside it, the transfer worked.

---

### Task A.2: Copy the Kalshi private key

**Files:**
- Source (old computer): `kalshi_private_key.pem` (wherever it lives — check your old `.env` file's `KALSHI_PRIVATE_KEY_PATH` value)
- Destination (new computer): same relative path (e.g. inside the project folder)

- [ ] 🧑 **Step 1: Find the .pem file on the old computer**

Open the project folder on the old computer and check the `.env` file:
```
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem
```
The path is relative to the project root, so the file is at:
```
C:\Users\thesa\claude kalshi\kalshi_private_key.pem
```

- [ ] 🧑 **Step 2: Transfer it to the new computer**

Copy it via USB drive or another secure method. Do NOT email it or upload it to any cloud service — it is a private key.

Set it aside for now. You will place it in the project folder in Task B.3.

---

### Task A.3: Copy the data folder from old computer

This contains your prediction history, paper trading P&L, and calibration weights.
It is **not in git** — without it you lose all Brier score history and paper trade records.

**Files:**
- Source (old computer): `C:\Users\thesa\claude kalshi\data\`
- Destination (new computer): `C:\Users\<yourname>\claude kalshi\data\`

> Note: the project folder won't exist on the new machine yet (that happens in Task B.1).
> Transfer the data folder now and paste it in after the clone completes.

- [ ] 🧑 **Step 1: On the OLD computer — zip the data folder**

Navigate to `C:\Users\thesa\claude kalshi\`, right-click the `data` folder →
Send to → Compressed (zipped) folder. Save as `kalshi-data.zip` on a USB drive
or Google Drive.

- [ ] 🧑 **Step 2: Set it aside — you will place it after cloning in Task B.1**

After Task B.1 clones the repo, extract `kalshi-data.zip` so the result is:
```
C:\Users\<yourname>\claude kalshi\data\
```

- [ ] 🧑 **Step 3: Verify the key files are present**

Confirm these exist after extraction:
```
C:\Users\<yourname>\claude kalshi\data\predictions.db
C:\Users\<yourname>\claude kalshi\data\paper_trades.json
```

---

## Phase B — Automated setup (paste into Claude Code)

Once Phase A is complete, open Claude Code on the new machine (just `claude` in any terminal) and paste each task's prompt as instructed.

---

### Task B.1: Check prerequisites, then clone and install

- [ ] 🤖 **Step 1: Paste this prompt into Claude Code**

```
Do these steps in order, stop and report any errors before continuing:

1. Check Python and Git are installed:
   python --version
   git --version
   If either command fails, stop immediately and tell me — I need to 
   install the missing tool before continuing.

2. Clone the repo:
   git clone https://github.com/livingtable-ctrl/weather1.git "C:\Users\<yourname>\claude kalshi"

3. Change into the project folder:
   cd "C:\Users\<yourname>\claude kalshi"

4. Install Python dependencies:
   pip install -r requirements.txt

5. Confirm pip install succeeded by running:
   python -c "import requests, scipy, flask, pytest; print('dependencies OK')"

Report the output of every step.
```

Replace `<yourname>` with your actual Windows username before pasting.

- [ ] 🧑 **Step 2: If Python or Git is missing, install them first**

- Python 3.12+: https://python.org/downloads — tick "Add Python to PATH" during install
- Git: https://git-scm.com/downloads — all defaults are fine

Then re-run the prompt above.

- [ ] 🧑 **Step 3: Confirm Claude reports "dependencies OK"**

If any package fails to install, Claude will tell you what went wrong and fix it.

---

### Task B.2: Create and configure the .env file

- [ ] 🤖 **Step 1: Paste this prompt into Claude Code**

```
In the project folder "C:\Users\<yourname>\claude kalshi":

1. Copy .env.example to .env
2. Open .env and tell me every line that contains a placeholder 
   (anything with "your-", "your_", or that is blank but has a comment 
   saying it's required)
3. Do NOT fill in any values — just list them so I know what I need to provide
```

- [ ] 🧑 **Step 2: Fill in the secret values yourself**

Claude will list the fields. Open `.env` in Notepad and fill in:
- `KALSHI_KEY_ID` — from kalshi.com → Account → API Keys
- `KALSHI_PRIVATE_KEY_PATH` — set to `./kalshi_private_key.pem`
- Any other values you had configured (Discord webhook, email, etc.)

Save and close `.env`.

---

### Task B.3: Place the private key file

- [ ] 🧑 **Step 1: Copy the .pem file into the project folder**

Take the `kalshi_private_key.pem` file you transferred in Task A.2 and place it at:
```
C:\Users\<yourname>\claude kalshi\kalshi_private_key.pem
```
This matches the default `KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem` in `.env`.

---

### Task B.4: Verify the full setup works

- [ ] 🤖 **Step 1: Paste this prompt into Claude Code**

```
In the project folder "C:\Users\<yourname>\claude kalshi", run these checks:

1. python main.py --help
   Expected: prints the command list with no errors

2. python -m pytest tests/ -q --tb=no -q
   Expected: should show passed/failed counts — note the numbers

3. python -c "
   from pathlib import Path
   import os
   from dotenv import load_dotenv
   load_dotenv()
   key_id = os.getenv('KALSHI_KEY_ID', '')
   pem = Path(os.getenv('KALSHI_PRIVATE_KEY_PATH', ''))
   print('KEY_ID set:', bool(key_id and 'your' not in key_id))
   print('PEM exists:', pem.exists())
   "
   Expected: both lines say True

Report all three outputs.
```

- [ ] 🧑 **Step 2: Review the outputs**

| Check | Expected |
|---|---|
| `main.py --help` | Command list printed, no ImportError |
| pytest | ~1079 passed, 0 errors (some skipped is fine) |
| KEY_ID set | `True` |
| PEM exists | `True` |

If anything shows `False` or an error, fix it before moving on.

---

## Phase C — Resume development

Everything is set up. Now open Claude Code **inside the project folder**:

```bash
cd "C:\Users\<yourname>\claude kalshi"
claude
```

Then paste this exact prompt:

---

```
Continue implementing the feature roadmap starting with Phase 1.

The plan is at: docs/superpowers/plans/2026-05-01-feature-roadmap.md

Phase 1 is "Full Ensemble CDF Integration" — fetching all 51 ECMWF IFS04 
ensemble members from Open-Meteo and wiring them into the blend pipeline 
as an empirical CDF source.

Start with Task 1.1 Step 1: write the failing tests for get_ensemble_members 
in tests/test_gaussian_prob.py, then proceed through the plan task by task.
```

---

## Self-review checklist

**Spec coverage:**
- [x] Skills folder copy — Task A.1
- [x] Private key transfer — Task A.2
- [x] Data folder (predictions.db, paper trades) — Task A.3
- [x] Repo clone — Task B.1
- [x] Python deps — Task B.1
- [x] .env setup — Task B.2
- [x] .pem placement — Task B.3
- [x] Full verification — Task B.4
- [x] Exact resume prompt — Phase C

**Manual vs automated clearly marked:** Every step labelled 🧑 or 🤖.

**No placeholders:** All commands are complete. `<yourname>` is the only variable and is called out explicitly every time it appears.
