# BW-Replay-Bot 🏭✨🦠

A Discord bot that automatically parses StarCraft: Brood War `.rep` replay files and posts rich embeds with player stats, build orders, APM charts, hotkey analysis, and in-game chat.

Just upload a `.rep` file in any channel — no commands needed.

---

## What It Shows

- 🗺️ Map name and game duration
- ⚔️ Matchup (e.g. ZvP)
- 👤 Player names, races, APM / eAPM, win/loss result
- 📋 Build order (first meaningful actions per player)
- 🎮 Hotkey control-group analysis (Army / Production / Mixed roles + camera snaps)
- 📊 APM-over-time chart
- 📈 Hotkey usage timeline chart
- 💬 In-game chat log with timestamps

---

## How Stats Are Calculated

This section explains every term the bot shows and exactly how it is derived from the replay data.

### APM — Actions Per Minute
The total number of game commands a player issued, divided by the game duration in minutes. Includes all actions: selecting units, issuing orders, setting hotkeys, casting spells, and building structures. A higher APM generally reflects faster mechanical play, but raw APM alone says nothing about decision quality.

### eAPM — Effective APM
A filtered version of APM that tries to exclude "spam" — repetitive or redundant actions that don't actually do anything meaningful (e.g. clicking the same unit repeatedly, or issuing move commands to units that are already moving there). eAPM is computed by screp's own algorithm. It is generally considered a more accurate measure of meaningful mechanical output than raw APM.

### Win / Loss
The bot determines the winner by scanning the replay's command stream for a **Leave Game** command. The player who sent that command is the loser; the other player is the winner. In most BW games the losing player quits before the game formally ends, making this a reliable signal. If screp provides a `Result` field directly (which it does in some replay formats), that is used first; Leave Game detection is the fallback.

### Build Order
The build order shows the first several significant actions each player took, in chronological order — buildings constructed, units trained, upgrades and research initiated. Workers (Probe, SCV, Drone) are shown up to twice to indicate economic intent without cluttering the list; all other units and buildings are shown up to six times. Each entry is timestamped to the nearest second using the game's frame count and the BW frame rate of **23.81 frames per second** (Fastest speed).

### APM Chart
A line chart sampled every 60 seconds showing each player's rolling APM across the game. Lets you see at a glance when players ramped up (early aggression, micro-intensive fights) or slowed down (macro phases, waiting for resources).

### Control Group Roles — Army / Production / Mixed
The bot analyses how each hotkey group (0–9) was used by examining **action pairs**: every time a player selects a group, the very next command they issue reveals what that group contains.

- If the next command is **Train, Build, Research, Upgrade, or Morph** → the group is used for **Production** (buildings/larvae).
- If the next command is **Stop, Hold Position, Attack, Attack Move, or Use Magic** — or a **Targeted Order** whose order is Attack — → the group is used for **Army** (mobile combat units).
- **Right Click is intentionally ignored.** It is ambiguous: for army units it means "move here," but for production buildings it means "set rally point." Counting it would mislabel rallied gateways or barracks as Army groups.

At the end of the replay, if one category dominates by a **4-to-1 ratio or more**, the group is labelled **Army** or **Production**. Otherwise it's **Mixed**. Groups that were never selected are omitted entirely.

### Camera Snaps
A **camera snap** is when a player double-taps a hotkey to jump their camera to that group's location — a standard BW technique for switching view between your army and your base. The bot detects this by looking for two **Select** commands on the **same group** issued within **12 frames of each other (~500 ms)**. The number shown is how many times the player did this across the whole game. High camera snaps generally indicate active multitasking between multiple locations.

### Hotkey Timeline Chart
A scatter-plot image showing every hotkey press across the game. The X axis is game time; the Y axis shows control groups 0–9. **Bright squares** are Assign/Add commands — the moments a player bound units to a group. **Small dots** are Select commands — the constant recalls as they tap through their groups. The density and rhythm of the dots give a visual sense of the player's multitasking patterns: which groups they rely on, when they set things up, and how consistently they cycle through their control groups.

---

## Prerequisites

- Python 3.12+
- The `screp` binary (Go-based BW replay parser by [icza](https://github.com/icza/screp))
- A Discord bot token

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/BorislavHr/BW-Replay-Bot.git
cd BW-Replay-Bot
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Download the screp binary

`screp` parses the `.rep` files. Download it from:
**https://github.com/icza/screp/releases**

| OS | File to download | Rename to |
|----|-----------------|-----------| 
| Windows | `screp_windows_amd64.exe` | `screp.exe` |
| Linux | `screp_linux_amd64` | `screp` |
| macOS | `screp_darwin_amd64` | `screp` |

Place the renamed binary in the project root folder.

**Windows** — test it works:
```cmd
screp.exe -help
```

**Linux/macOS** — make it executable first:
```bash
chmod +x screp
./screp -help
```

### 4. Create a Discord bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → name it
3. Go to **Bot** → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable **Message Content Intent** ✅
5. Copy the **Token**
6. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot permissions: `Send Messages`, `Read Message History`, `Attach Files`, `Embed Links`
7. Open the generated URL to invite the bot to your server

### 5. Set your token

**Windows:**
```cmd
set DISCORD_TOKEN=your-token-here
python bot.py
```

**Linux/macOS:**
```bash
export DISCORD_TOKEN=your-token-here
python bot.py
```

You should see:
```
Logged in as YourBot#1234 (id=...)
Listening for .rep file uploads…
```

---

## Deploying to Railway (free 24/7 hosting)

Railway gives $5 of free credit/month — more than enough for a Discord bot.

### Steps

1. Push your repo to GitHub
2. Go to https://railway.app → **New Project → Deploy from GitHub repo**
3. Select your repo
4. Go to the **Variables** tab and add:
   ```
   DISCORD_TOKEN=your-token-here
   ```
5. Railway auto-deploys on every `git push`

### Required files for Railway

**`Procfile`**
```
worker: bash build.sh && python bot.py
```

**`runtime.txt`**
```
python-3.12.9
```

**`build.sh`**
```bash
#!/bin/bash
chmod +x screp
```

> ⚠️ Railway runs **Linux** — use the `screp_linux_amd64` binary renamed to `screp` (no `.exe`).
> The `config.py` auto-detects the OS so no code changes are needed.

---

## Project Structure

```
BW-Replay-Bot/
├── bot.py              # Discord bot — event handling and orchestration
├── parser.py           # Calls screp, parses JSON → Python dataclasses
├── visualizer.py       # Generates APM chart and hotkey timeline with matplotlib
├── embed_builder.py    # Builds the Discord embed(s)
├── config.py           # All settings (token, paths, colours, limits)
├── requirements.txt    # Python dependencies
├── Procfile            # Railway process definition
├── runtime.txt         # Python version pin for Railway
├── build.sh            # Makes screp executable on Railway
├── screp / screp.exe   # ← place the binary here
└── temp/               # Auto-created; holds temp files during processing
```

---

## Running 24/7 on Windows (without Railway)

Use **NSSM** to run the bot as a Windows Service:

1. Download from https://nssm.cc/download
2. Open a terminal as Administrator:
```cmd
nssm install BW-Replay-Bot
```
3. In the GUI:
   - **Path**: your `python.exe` (e.g. `C:\Python312\python.exe`)
   - **Startup directory**: your project folder
   - **Arguments**: `bot.py`
   - **Environment**: `DISCORD_TOKEN=your-token-here`
4. Click **Install service**, then:
```cmd
nssm start BW-Replay-Bot
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `screp binary not found` | Download screp and place it in the project root |
| `Could not parse replay` | File may be corrupt or from an unsupported version |
| Bot doesn't respond to uploads | Check **Message Content Intent** is enabled in Discord dev portal |
| Charts are blank / missing | Run `pip install matplotlib` |
| Railway crash on startup | Check the binary is `screp` (not `screp.exe`) and `build.sh` exists |
| Double reply in Discord | Make sure you're on the latest version of `bot.py` |
| PyNaCl / davey warnings in logs | Harmless — voice libraries discord.py optionally uses; the bot never uses voice |
