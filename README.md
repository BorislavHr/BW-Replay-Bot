# BW-Replay-Bot 🏭✨🦠

A Discord bot that automatically parses StarCraft: Brood War `.rep` replay files and posts rich embeds with player stats, build orders, APM charts, and in-game chat.

Just upload a `.rep` file in any channel — no commands needed.

---

## What It Shows

- 🗺️ Map name and game duration
- ⚔️ Matchup (e.g. ZvP)
- 👤 Player names, races, APM / eAPM, win/loss result
- 📋 Build order timeline (first 12 key actions per player)
- 📊 APM-over-time chart (PNG attached to embed)
- 💬 In-game chat log with timestamps

---

## Prerequisites

- Python 3.12+
- The `screp` binary (Go-based BW replay parser)
- A Discord bot token

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/BW-Replay-Bot.git
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

Make sure these are in your repo:

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
├── visualizer.py       # Generates APM chart with matplotlib
├── embed_builder.py    # Builds the Discord embed
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
