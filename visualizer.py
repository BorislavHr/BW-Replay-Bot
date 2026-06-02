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
from parser import ReplayData, FRAMES_PER_SECOND

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

# ---------------------------------------------------------------------------
# Hotkey usage timeline
# ---------------------------------------------------------------------------

def _chart_hotkeys(replay: ReplayData, uid: str) -> Path | None:
    """
    Two-panel timeline (one per player): control groups 0-9 on the Y axis,
    game time on the X axis. Each hotkey press is a marker — bright square
    for an assign (setting the group), smaller dot for a select (recall).
    """
    players_with_hk = [p for p in replay.players if p.hotkey_events]
    if not players_with_hk:
        return None

    n = len(players_with_hk)
    fig, axes = plt.subplots(n, 1, figsize=(11, 3.2 * n))
    fig.patch.set_facecolor(BG_COLOR)
    if n == 1:
        axes = [axes]

    for ax, player, base_color in zip(axes, players_with_hk, PLAYER_COLORS):
        assign_frames, assign_groups = [], []
        select_frames, select_groups = [], []
        for ev in player.hotkey_events:
            t = ev.frame / FRAMES_PER_SECOND
            if ev.is_assign:
                assign_frames.append(t)
                assign_groups.append(ev.group)
            else:
                select_frames.append(t)
                select_groups.append(ev.group)

        # Selects: small semi-transparent dots (the constant tapping)
        ax.scatter(select_frames, select_groups, s=14, c=base_color,
                   alpha=0.45, marker="o", linewidths=0, zorder=2)
        # Assigns: bright bold squares (the moments a group is (re)bound)
        ax.scatter(assign_frames, assign_groups, s=70, c=base_color,
                   alpha=1.0, marker="s", linewidths=0, zorder=3)

        title = (f"{player.name} ({player.race[0]}) — "
                 f"Hotkey Timeline  •  {player.hotkeys.camera_snaps} camera snaps")
        _apply_base_style(ax, title)
        ax.set_xlabel("Game Time")
        ax.set_yticks(range(10))
        ax.set_yticklabels([str(g) for g in range(10)])
        ax.set_ylabel("Control Group")
        ax.set_ylim(-0.5, 9.5)
        ax.invert_yaxis()   # group 0 at bottom, 1 near top — reads like the keyboard
        ax.set_xlim(left=0)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(_minutes_formatter))
        ax.xaxis.set_major_locator(ticker.MultipleLocator(120))

    fig.tight_layout(pad=1.5)
    return _save_fig(fig, f"hotkeys_{uid}.png")


async def generate_charts(replay: ReplayData, uid: str) -> list[Path]:
    """Generate the APM chart + hotkey timeline. Runs in a thread pool."""
    loop = asyncio.get_event_loop()
    apm_path = await loop.run_in_executor(None, _chart_apm, replay, uid)
    hk_path  = await loop.run_in_executor(None, _chart_hotkeys, replay, uid)
    return [p for p in (apm_path, hk_path) if p is not None]
