"""
visualizer.py — Generates chart images and minimap from ReplayData.

Returns file Paths so bot.py can attach them to Discord messages.
Caller is responsible for deleting temp files after sending.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["font.family"] = "DejaVu Sans"
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from PIL import Image, ImageDraw, ImageFont

from config import CHART_DPI, PLAYER_COLORS, SCREP_BINARY, TEMP_DIR
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
# Minimap with spawn location overlay
# ---------------------------------------------------------------------------

# Match PLAYER_COLORS from config — blue for player 1, red for player 2
SPAWN_COLORS = ["#4fc3f7", "#ef5350"]


def _generate_minimap(replay: ReplayData, rep_path: Path, uid: str) -> Path | None:
    """
    1. Call screp -map to extract the raw minimap PNG from the replay file.
    2. Upscale it to ~512px on the longer side.
    3. Draw a coloured circle + player name at each spawn location.
    4. Return the composited PNG path.
    """
    raw_map_path = TEMP_DIR / f"minimap_raw_{uid}.png"
    out_path     = TEMP_DIR / f"minimap_{uid}.png"

    # ── Step 1: extract raw minimap ─────────────────────────────────────────
    try:
        os.chmod(SCREP_BINARY, 0o755)
    except Exception:
        pass

    # Log screp version so we can diagnose flag issues
    try:
        ver = subprocess.run([str(SCREP_BINARY), "-version"],
                             capture_output=True, timeout=5)
        log.info(f"screp version: {(ver.stdout or ver.stderr)[:80].decode(errors='replace').strip()}")
    except Exception:
        pass

    try:
        result = subprocess.run(
            [str(SCREP_BINARY), "-map", str(rep_path), str(raw_map_path)],
            capture_output=True,
            timeout=30,
        )
        log.info(f"screp -map exit={result.returncode} stderr={result.stderr[:200]}")
        if not raw_map_path.exists():
            log.warning(f"screp -map produced no file. stderr: {result.stderr[:300]}")
            return None
    except Exception as e:
        log.warning(f"screp -map failed: {e}")
        return None

    # ── Step 2: open and upscale ─────────────────────────────────────────────
    try:
        img = Image.open(raw_map_path).convert("RGBA")
    except Exception as e:
        log.warning(f"Could not open raw minimap: {e}")
        raw_map_path.unlink(missing_ok=True)
        return None

    orig_w, orig_h = img.size
    map_w = replay.map_width  or orig_w
    map_h = replay.map_height or orig_h
    log.info(f"Raw minimap: {orig_w}x{orig_h}px  map tiles: {map_w}x{map_h}")

    TARGET = 512
    scale  = TARGET / max(map_w, map_h)
    new_w  = max(1, int(map_w * scale))
    new_h  = max(1, int(map_h * scale))
    img    = img.resize((new_w, new_h), Image.NEAREST)
    draw   = ImageDraw.Draw(img)

    # ── Step 3: load font ────────────────────────────────────────────────────
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 14)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    # ── Step 4: draw spawn markers ───────────────────────────────────────────
    for i, player in enumerate(replay.players):
        sx, sy = player.spawn_x, player.spawn_y
        if sx == 0 and sy == 0:
            log.info(f"Player {player.name} has no spawn location — skipping marker")
            continue

        color = SPAWN_COLORS[i % len(SPAWN_COLORS)]

        # Convert tile coords to pixel coords in the upscaled image
        # screp gives StartLocation in tiles; the raw minimap is 1px per tile
        px = int(sx * scale)
        py = int(sy * scale)
        px = max(12, min(new_w - 12, px))
        py = max(12, min(new_h - 12, py))

        log.info(f"Drawing spawn for {player.name} at tile ({sx},{sy}) → px ({px},{py})")

        r = 10
        # White outline for contrast on any background
        draw.ellipse([px - r - 2, py - r - 2, px + r + 2, py + r + 2],
                     fill="white", outline="white")
        # Coloured fill
        draw.ellipse([px - r, py - r, px + r, py + r],
                     fill=color, outline=color)

        # Name label with black drop-shadow for legibility
        label  = player.name
        tx, ty = px + r + 4, py - 8
        draw.text((tx + 1, ty + 1), label, fill="black", font=font)
        draw.text((tx,     ty),     label, fill="white", font=font)

    # ── Step 5: save and clean up ────────────────────────────────────────────
    try:
        img.convert("RGB").save(out_path, "PNG")
        raw_map_path.unlink(missing_ok=True)
        log.info(f"Minimap saved: {out_path}")
        return out_path
    except Exception as e:
        log.warning(f"Could not save composited minimap: {e}")
        raw_map_path.unlink(missing_ok=True)
        return None


# ---------------------------------------------------------------------------
# Public async entry-points
# ---------------------------------------------------------------------------

async def generate_charts(replay: ReplayData, uid: str) -> list[Path]:
    """Generate the APM chart. Runs in a thread pool to keep Discord loop free."""
    loop = asyncio.get_event_loop()
    apm_path = await loop.run_in_executor(None, _chart_apm, replay, uid)
    return [apm_path] if apm_path is not None else []


async def generate_minimap(replay: ReplayData, rep_path: Path, uid: str) -> Path | None:
    """Generate the minimap with spawn overlays. Runs in a thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _generate_minimap, replay, rep_path, uid)
