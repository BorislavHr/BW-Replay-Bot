"""
visualizer.py — Generates chart images from ReplayData.

Returns file Paths so bot.py can attach them to Discord messages.
Caller is responsible for deleting temp files after sending.
"""

import asyncio
import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "DejaVu Sans"
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from config import CHART_DPI, PLAYER_COLORS, TEMP_DIR
from parser import ReplayData

log = logging.getLogger("sc-replay-bot")

# ---------------------------------------------------------------------------
# Shared style helpers
# ---------------------------------------------------------------------------

BG_COLOR     = "#0d1117"
GRID_COLOR   = "#21262d"
TEXT_COLOR   = "#e6edf3"
ACCENT_COLOR = "#30363d"


def _apply_base_style(ax: plt.Axes, title: str) -> None:
    ax.set_facecolor(BG_COLOR)
    ax.set_title(title, color=TEXT_COLOR, fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
    for spine in ax.spines.values():
        spine.set_edgecolor(ACCENT_COLOR)


def _minutes_formatter(x, _):
    m, s = divmod(int(x), 60)
    return f"{m}:{s:02d}"


def _save_fig(fig: plt.Figure, filename: str) -> Path:
    path = TEMP_DIR / filename
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# APM over time chart
# ---------------------------------------------------------------------------

def _chart_apm(replay: ReplayData, uid: str) -> Path | None:
    """Line chart: APM over game time for each player."""
    players_with_data = [p for p in replay.players if p.apm_timeline]
    if not players_with_data:
        return None

    fig, ax = plt.subplots(figsize=(9, 4))
    fig.patch.set_facecolor(BG_COLOR)

    for i, player in enumerate(players_with_data):
        color = PLAYER_COLORS[i % len(PLAYER_COLORS)]
        times = [t for t, _ in player.apm_timeline]
        apms  = [a for _, a in player.apm_timeline]
        label = f"{player.name} ({player.race[0]}) — avg {player.apm} APM"
        ax.plot(times, apms, color=color, linewidth=2, label=label)
        ax.fill_between(times, apms, alpha=0.08, color=color)

    _apply_base_style(ax, "APM Over Time")
    ax.set_xlabel("Game Time")
    ax.set_ylabel("APM")
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(_minutes_formatter))
    ax.xaxis.set_major_locator(ticker.MultipleLocator(120))
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.legend(facecolor=ACCENT_COLOR, edgecolor=GRID_COLOR,
              labelcolor=TEXT_COLOR, fontsize=9)

    fig.tight_layout()
    return _save_fig(fig, f"apm_{uid}.png")


# ---------------------------------------------------------------------------
# Public async entry-point
# ---------------------------------------------------------------------------

async def generate_charts(replay: ReplayData, uid: str) -> list[Path]:
    """Generate the APM chart. Runs in a thread pool to keep Discord loop free."""
    loop = asyncio.get_event_loop()
    apm_path = await loop.run_in_executor(None, _chart_apm, replay, uid)
    return [apm_path] if apm_path is not None else []
