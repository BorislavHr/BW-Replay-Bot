# StarCraft BW Replay Bot 🏭✨🦠

A Discord bot that automatically parses Brood War `.rep` replay files and posts
rich embeds with player stats, build orders, and charts.

---

## Quick Start

### 1. Clone / download this project

```bash
git clone <your-repo-url>
cd BW-Replay-Bot
```

### 2. Install Python dependencies

Requires **Python 3.11+**.

```bash
pip install -r requirements.txt
```

### 3. Download the `screp` binary

`screp` is a Go tool that does the heavy lifting of parsing BW replay files.

1. Go to https://github.com/icza/screp/releases
2. Download `screp_windows_amd64.exe`
3. Place it in the project root and rename it to `screp.exe`

Test it works by opening a terminal in the project folder:
```cmd
screp.exe -help
```

### 4. Create a Discord bot

1. Go to https://discord.com/developers/applications
2. Click **New Application** → give it a name
3. Go to **Bot** → click **Add Bot**
4. Enable **Message Content Intent** (under Privileged Gateway Intents)
5. Copy the **Token**
6. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Read Message History`, `Attach Files`, `Embed Links`
7. Open the generated URL to invite the bot to your server

### 5. Set your token

Either set an environment variable (Windows):
```cmd
set DISCORD_TOKEN=your-token-here
```

Or edit `config.py` directly (not recommended for production):
```python
DISCORD_TOKEN = "your-token-here"
```

### 6. Run the bot

```bash
python bot.py
```

---

## Usage

Just **upload any `.rep` file** in a channel the bot can see.
The bot will automatically:
1. Download the replay
2. Parse it with `screp`
3. Generate APM and build-order charts
4. Post a rich embed with all the stats

No commands needed!

You can also type `!help_replay` to see the help embed.

---

## Project Structure

```
BW-Replay-Bot/
├── bot.py              # Discord bot — events & message handling
├── parser.py           # screp subprocess call + JSON → dataclasses
├── visualizer.py       # matplotlib chart generation
├── embed_builder.py    # discord.Embed construction
├── config.py           # Settings (token, paths, colours, …)
├── requirements.txt
├── screp.exe           # ← place the binary here (Windows)
└── temp/               # Auto-created; holds temp files during processing
```

---

## Keeping the Bot Running (Windows)

To keep the bot alive in the background on Windows, use **NSSM** (Non-Sucking Service Manager)
to run it as a Windows Service:

1. Download NSSM from https://nssm.cc/download
2. Open a terminal as Administrator and run:
```cmd
nssm install BW-Replay-Bot
```
3. In the GUI that opens:
   - **Path**: point to your `python.exe` (e.g. `C:\Python311\python.exe`)
   - **Startup directory**: your project folder
   - **Arguments**: `bot.py`
   - Under **Environment**: add `DISCORD_TOKEN=your-token-here`
4. Click **Install service**, then:
```cmd
nssm start BW-Replay-Bot
```

For a simpler option during development, just keep a terminal open running `python bot.py`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `screp binary not found` | Download `screp.exe` and place it in the project root |
| `Could not parse replay` | File may be corrupt or from a different game version |
| Bot doesn't respond | Check Message Content Intent is enabled in Discord dev portal |
| Charts are blank | Ensure matplotlib is installed: `pip install matplotlib` |
