"""
visualizer.py — Generates chart images from ReplayData.

Returns file Paths so bot.py can attach them to Discord messages.
Caller is responsible for deleting temp files after sending.
"""

import asyncio
from pathlib import Path

import matplotlib
matplotlib.use("Agg")           # Non-interactive backend — safe for bots
matplotlib.rcParams["font.family"] = "DejaVu Sans"  # Skip font cache scan
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

from config import CHART_DPI, CHART_STYLE, PLAYER_COLORS, TEMP_DIR
from parser import ReplayData, PlayerStats


# ---------------------------------------------------------------------------
# Shared style helpers
# ---------------------------------------------------------------------------

BG_COLOR = "#0d1117"
GRID_COLOR = "#21262d"
TEXT_COLOR = "#e6edf3"
ACCENT_COLOR = "#30363d"


def _apply_base_style(ax: plt.Axes, title: str) -> None:
    """Apply consistent dark StarCraft-themed style to an axes object."""
    ax.set_facecolor(BG_COLOR)
    ax.set_title(title, color=TEXT_COLOR, fontsize=13, fontweight="bold", pad=12)
    ax.tick_params(colors=TEXT_COLOR, labelsize=9)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.grid(True, color=GRID_COLOR, linewidth=0.8, linestyle="--", alpha=0.7)
    for spine in ax.spines.values():
        spine.set_edgecolor(ACCENT_COLOR)


def _minutes_formatter(x, _):
    """Format x-axis tick labels as mm:ss."""
    m, s = divmod(int(x), 60)
    return f"{m}:{s:02d}"


def _save_fig(fig: plt.Figure, filename: str) -> Path:
    path = TEMP_DIR / filename
    fig.savefig(path, dpi=CHART_DPI, bbox_inches="tight", facecolor=BG_COLOR)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Combined APM + Supply chart (two stacked panels)
# ---------------------------------------------------------------------------

def _chart_apm(replay: ReplayData, uid: str) -> Path | None:
    """Two-panel chart: APM over time (top) + cumulative supply spent (bottom)."""
    players = replay.players
    has_apm     = any(p.apm_timeline for p in players)
    has_supply  = any(p.supply_timeline for p in players)

    if not has_apm and not has_supply:
        return None

    # Decide layout: 1 or 2 panels
    n_panels = (1 if has_apm else 0) + (1 if has_supply else 0)
    fig, axes = plt.subplots(n_panels, 1, figsize=(9, 4 * n_panels))
    fig.patch.set_facecolor(BG_COLOR)
    if n_panels == 1:
        axes = [axes]

    panel = 0

    # ── APM panel ──────────────────────────────────────────────────────────
    if has_apm:
        ax = axes[panel]; panel += 1
        for i, player in enumerate(players):
            if not player.apm_timeline:
                continue
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

    # ── Supply spent panel ─────────────────────────────────────────────────
    if has_supply:
        ax = axes[panel]; panel += 1
        for i, player in enumerate(players):
            if not player.supply_timeline:
                continue
            color = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            times   = [t for t, _ in player.supply_timeline]
            supply  = [s for _, s in player.supply_timeline]
            label = f"{player.name} ({player.race[0]})"
            ax.plot(times, supply, color=color, linewidth=2, label=label)
            ax.fill_between(times, supply, alpha=0.08, color=color)

        _apply_base_style(ax, "Cumulative Supply Spent")
        ax.set_xlabel("Game Time")
        ax.set_ylabel("Supply")
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(_minutes_formatter))
        ax.xaxis.set_major_locator(ticker.MultipleLocator(120))
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.legend(facecolor=ACCENT_COLOR, edgecolor=GRID_COLOR,
                  labelcolor=TEXT_COLOR, fontsize=9)

    fig.tight_layout(pad=2.0)
    return _save_fig(fig, f"apm_{uid}.png")


# ---------------------------------------------------------------------------
# Build order timeline chart
# ---------------------------------------------------------------------------

def _chart_build_order(replay: ReplayData, uid: str) -> Path | None:
    """Horizontal timeline of build-order actions per player."""
    players_with_bo = [p for p in replay.players if p.build_order]
    if not players_with_bo:
        return None

    n_players = len(players_with_bo)
    fig, axes = plt.subplots(
        n_players, 1,
        figsize=(10, 3 * n_players),
        sharex=False,
    )
    fig.patch.set_facecolor(BG_COLOR)

    if n_players == 1:
        axes = [axes]

    for ax, player, color in zip(axes, players_with_bo, PLAYER_COLORS):
        times = [e.time_seconds for e in player.build_order]
        names = [e.name for e in player.build_order]
        y_pos = [0] * len(times)

        ax.scatter(times, y_pos, color=color, s=120, zorder=3)

        for t, name in zip(times, names):
            ax.annotate(
                name,
                xy=(t, 0),
                xytext=(0, 18),
                textcoords="offset points",
                ha="center",
                fontsize=7.5,
                color=TEXT_COLOR,
                rotation=30,
                arrowprops=dict(arrowstyle="-", color=color, lw=0.8),
            )

        _apply_base_style(ax, f"{player.name} ({player.race}) — Build Order")
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(_minutes_formatter))
        ax.set_yticks([])
        ax.set_xlabel("Game Time")
        ax.set_xlim(left=-10)
        ax.set_ylim(-0.5, 1.0)
        ax.spines["left"].set_visible(False)

    fig.tight_layout(pad=2.0)
    return _save_fig(fig, f"bo_{uid}.png")


# ---------------------------------------------------------------------------
# Public async entry-point
# ---------------------------------------------------------------------------

async def generate_charts(replay: ReplayData, uid: str) -> list[Path]:
    """
    Generate the APM chart and return its path.
    Runs matplotlib in a thread pool so the Discord event loop stays free.
    """
    loop = asyncio.get_event_loop()
    apm_path = await loop.run_in_executor(None, _chart_apm, replay, uid)
    return [apm_path] if apm_path is not None else []
