"""
parser.py — Calls the screp binary and transforms its JSON output
into clean Python dataclasses ready for the visualizer and embed builder.
"""

import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import SCREP_BINARY, SCREP_TIMEOUT, BUILD_ORDER_MAX_ACTIONS


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BuildOrderEntry:
    frame: int
    time_seconds: float
    name: str           # Unit / building / upgrade name


@dataclass
class PlayerStats:
    name: str
    race: str
    is_winner: bool
    apm: int
    eapm: int           # Effective APM (filters spam clicks)
    build_order: list[BuildOrderEntry] = field(default_factory=list)
    # Frame-by-frame snapshots for charts
    # List of (time_seconds, apm_value) tuples sampled at intervals
    apm_timeline: list[tuple[float, int]] = field(default_factory=list)


@dataclass
class ReplayData:
    map_name: str
    duration_seconds: float
    matchup: str            # e.g. "TvZ"
    players: list[PlayerStats] = field(default_factory=list)

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration_seconds), 60)
        return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FRAMES_PER_SECOND = 23.81   # BW runs at ~23.81 game frames per second (fastest)


def _frames_to_seconds(frames: int) -> float:
    return frames / FRAMES_PER_SECOND


def _race_name(raw: str) -> str:
    """Normalise screp race strings."""
    mapping = {"T": "Terran", "P": "Protoss", "Z": "Zerg"}
    return mapping.get(raw, raw or "Unknown")


def _build_order_from_cmds(commands: list[dict]) -> list[BuildOrderEntry]:
    """
    Extract build-order entries from a player's command list.
    We keep only 'Build', 'Train', 'Morph', 'Research', 'Upgrade' commands.
    """
    BUILD_CMD_TYPES = {
        "Build", "Train", "Morph", "Research", "Upgrade",
        "BuildingMorph", "UnitMorph",
    }
    entries: list[BuildOrderEntry] = []
    seen: set[str] = set()          # deduplicate consecutive identical entries

    for cmd in commands:
        cmd_type = cmd.get("Name", "")
        if cmd_type not in BUILD_CMD_TYPES:
            continue

        unit_name = (
            cmd.get("UnitType", {}).get("Name")
            or cmd.get("TechType", {}).get("Name")
            or cmd.get("UpgradeType", {}).get("Name")
            or "Unknown"
        )

        frame = cmd.get("Frame", 0)
        key = f"{unit_name}"

        if key in seen:
            continue
        seen.add(key)

        entries.append(BuildOrderEntry(
            frame=frame,
            time_seconds=_frames_to_seconds(frame),
            name=unit_name,
        ))

        if len(entries) >= BUILD_ORDER_MAX_ACTIONS:
            break

    return entries


def _apm_timeline_from_cmds(commands: list[dict], total_frames: int) -> list[tuple[float, int]]:
    """
    Build a list of (time_seconds, rolling_apm) samples by counting commands
    inside a sliding 1-minute window, sampled every 30 seconds of game time.
    """
    if not commands or total_frames == 0:
        return []

    SAMPLE_FRAMES = int(30 * FRAMES_PER_SECOND)    # sample every 30 s
    WINDOW_FRAMES = int(60 * FRAMES_PER_SECOND)    # 1-minute rolling window

    frames = sorted(cmd.get("Frame", 0) for cmd in commands)
    timeline: list[tuple[float, int]] = []

    sample = SAMPLE_FRAMES
    while sample <= total_frames + SAMPLE_FRAMES:
        window_start = max(0, sample - WINDOW_FRAMES)
        count = sum(1 for f in frames if window_start <= f <= sample)
        apm = int(count * (FRAMES_PER_SECOND * 60 / WINDOW_FRAMES))
        timeline.append((_frames_to_seconds(sample), apm))
        sample += SAMPLE_FRAMES

    return timeline


def _determine_winner(players_raw: list[dict]) -> Optional[int]:
    """Return 0-based index of the winner, or None if unknown."""
    for i, p in enumerate(players_raw):
        if p.get("Result") == "Win":
            return i
    return None


# ---------------------------------------------------------------------------
# Main parsing function
# ---------------------------------------------------------------------------

def _parse_screp_json(data: dict) -> ReplayData:
    """Transform screp's raw JSON dict into a ReplayData object."""

    header = data.get("Header", {})
    map_name: str = header.get("Map", "Unknown Map")
    total_frames: int = header.get("Frames", 0)
    duration_seconds = _frames_to_seconds(total_frames)

    players_raw: list[dict] = header.get("Players", [])
    winner_idx = _determine_winner(players_raw)

    # Commands are keyed by player ID
    commands_by_player: dict[int, list[dict]] = {}
    for cmd in data.get("Commands", []):
        pid = cmd.get("PlayerID", -1)
        commands_by_player.setdefault(pid, []).append(cmd)

    # Computed APM data from screp (per-player summary)
    computed = data.get("Computed", {})
    player_descs = computed.get("PlayerDescs", [])

    players: list[PlayerStats] = []
    races: list[str] = []

    for i, p in enumerate(players_raw):
        # Skip observer / non-human slots
        if p.get("Type") not in ("Human", "Computer"):
            continue

        race = _race_name(p.get("Race", ""))
        races.append(race[0] if race else "?")   # First letter for matchup string

        desc = player_descs[i] if i < len(player_descs) else {}
        apm = desc.get("APM", 0)
        eapm = desc.get("EAPM", 0)

        cmds = commands_by_player.get(p.get("ID", i), [])
        build_order = _build_order_from_cmds(cmds)
        apm_timeline = _apm_timeline_from_cmds(cmds, total_frames)

        players.append(PlayerStats(
            name=p.get("Name", f"Player {i + 1}"),
            race=race,
            is_winner=(winner_idx == i),
            apm=apm,
            eapm=eapm,
            build_order=build_order,
            apm_timeline=apm_timeline,
        ))

    matchup = "v".join(races) if len(races) == 2 else "?v?"

    return ReplayData(
        map_name=map_name,
        duration_seconds=duration_seconds,
        matchup=matchup,
        players=players,
    )


async def parse_replay(rep_path: Path) -> ReplayData:
    """
    Async entry-point: runs screp in a thread pool so we don't block the
    Discord event loop, then parses the JSON output.

    Raises:
        FileNotFoundError: if the screp binary is missing.
        ValueError: if screp returns an error or unparseable output.
    """
    if not SCREP_BINARY.exists():
        raise FileNotFoundError(
            f"screp binary not found at {SCREP_BINARY}. "
            "Download it from https://github.com/icza/screp/releases "
            "and place it next to bot.py."
        )

    # Ensure the binary is executable at runtime (needed on Railway/Linux)
    import sys, os, stat
    if sys.platform != "win32":
        current = os.stat(SCREP_BINARY).st_mode
        os.chmod(SCREP_BINARY, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run() -> dict:
        result = subprocess.run(
            [str(SCREP_BINARY), "-json", str(rep_path)],
            capture_output=True,
            text=True,
            timeout=SCREP_TIMEOUT,
        )
        if result.returncode != 0:
            raise ValueError(f"screp error: {result.stderr.strip()}")
        return json.loads(result.stdout)

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _run)
    return _parse_screp_json(raw)
