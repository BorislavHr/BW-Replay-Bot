import os
import sys
from pathlib import Path

# --- Discord ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")

# --- Paths ---
BASE_DIR = Path(__file__).parent
_screp_name = "screp.exe" if sys.platform == "win32" else "screp"
SCREP_BINARY = BASE_DIR / _screp_name      # Path to the screp binary
TEMP_DIR = BASE_DIR / "temp"               # Temp dir for downloaded replays + charts
TEMP_DIR.mkdir(exist_ok=True)

# --- Replay parsing ---
SCREP_TIMEOUT = 15                         # Seconds before screp subprocess times out

# --- Chart settings ---
CHART_DPI = 120
CHART_STYLE = "dark_background"            # matplotlib style
PLAYER_COLORS = ["#00BFFF", "#FF4500"]     # Blue for P1, Orange for P2

# --- Build order ---
BUILD_ORDER_MAX_ACTIONS = 12               # How many build-order actions to show per player

# --- Races ---
RACE_EMOJI = {
    "Terran": "🏭",
    "Protoss": "✨",
    "Zerg": "🦠",
    "Unknown": "❓",
}
