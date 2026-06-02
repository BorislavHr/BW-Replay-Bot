"""
parser.py — Calls the screp binary and transforms its JSON output
into clean Python dataclasses ready for the visualizer and embed builder.
"""

import asyncio
import json
import logging
import os
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import SCREP_BINARY, SCREP_TIMEOUT, BUILD_ORDER_MAX_ACTIONS

log = logging.getLogger("sc-replay-bot")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BuildOrderEntry:
    frame: int
    time_seconds: float
    name: str


@dataclass
class PlayerStats:
    name: str
    race: str
    is_winner: bool
    apm: int
    eapm: int
    build_order: list[BuildOrderEntry] = field(default_factory=list)
    apm_timeline: list[tuple[float, int]] = field(default_factory=list)


@dataclass
class ChatMessage:
    time_seconds: float
    player_name: str
    message: str

    @property
    def time_str(self) -> str:
        m, s = divmod(int(self.time_seconds), 60)
        return f"{m}:{s:02d}"


@dataclass
class ReplayData:
    map_name: str
    duration_seconds: float
    matchup: str
    players: list[PlayerStats] = field(default_factory=list)
    chat_log: list[ChatMessage] = field(default_factory=list)

    @property
    def duration_str(self) -> str:
        m, s = divmod(int(self.duration_seconds), 60)
        return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FRAMES_PER_SECOND = 23.81


def _frames_to_seconds(frames: int) -> float:
    return frames / FRAMES_PER_SECOND


def _race_name(raw) -> str:
    """Normalise screp race — handles both short ('T') and full ('Terran') strings."""
    if isinstance(raw, dict):
        # Some screp versions return {"Name": "Terran", "ShortName": "T"}
        raw = raw.get("Name") or raw.get("ShortName", "")
    mapping = {
        "T": "Terran", "Terran": "Terran",
        "P": "Protoss", "Protoss": "Protoss",
        "Z": "Zerg",    "Zerg": "Zerg",
    }
    return mapping.get(raw, raw or "Unknown")


def _safe_get(obj, *keys, default=None):
    """Safely traverse nested dicts/lists without crashing on unexpected types."""
    for key in keys:
        if isinstance(obj, dict):
            obj = obj.get(key, default)
        else:
            return default
    return obj


def _build_order_from_cmds(commands: list) -> list[BuildOrderEntry]:
    BUILD_CMD_TYPES = {
        "Build", "Train", "Morph", "Research", "Upgrade",
        "BuildingMorph", "UnitMorph", "Infestation",
    }
    entries: list[BuildOrderEntry] = []
    seen: set[str] = set()

    for cmd in commands:
        if not isinstance(cmd, dict):
            continue

        cmd_type = _safe_get(cmd, "Type", "Name") or ""
        if cmd_type not in BUILD_CMD_TYPES:
            continue

        # screp nests the unit/tech name differently depending on command type
        unit_name = (
            _safe_get(cmd, "Unit", "Name")
            or _safe_get(cmd, "UnitType", "Name")
            or _safe_get(cmd, "TechType", "Name")
            or _safe_get(cmd, "UpgradeType", "Name")
            or cmd.get("UnitName")
            or "Unknown"
        )
        # Skip "None" units (non-build commands that slipped through)
        if unit_name in ("None", "Unknown"):
            continue

        frame = cmd.get("Frame", 0)
        if unit_name in seen:
            continue
        seen.add(unit_name)

        entries.append(BuildOrderEntry(
            frame=frame,
            time_seconds=_frames_to_seconds(frame),
            name=unit_name,
        ))

        if len(entries) >= BUILD_ORDER_MAX_ACTIONS:
            break

    return entries


def _apm_timeline_from_cmds(commands: list, total_frames: int) -> list[tuple[float, int]]:
    if not commands or total_frames == 0:
        return []

    SAMPLE_FRAMES = int(30 * FRAMES_PER_SECOND)
    WINDOW_FRAMES = int(60 * FRAMES_PER_SECOND)

    frames = sorted(
        cmd.get("Frame", 0)
        for cmd in commands
        if isinstance(cmd, dict)
    )
    timeline: list[tuple[float, int]] = []

    sample = SAMPLE_FRAMES
    while sample <= total_frames + SAMPLE_FRAMES:
        window_start = max(0, sample - WINDOW_FRAMES)
        count = sum(1 for f in frames if window_start <= f <= sample)
        apm = int(count * (FRAMES_PER_SECOND * 60 / WINDOW_FRAMES))
        timeline.append((_frames_to_seconds(sample), apm))
        sample += SAMPLE_FRAMES

    return timeline


def _determine_winner(players_raw: list) -> Optional[int]:
    for i, p in enumerate(players_raw):
        if not isinstance(p, dict):
            continue
        result = p.get("Result") or p.get("Win")
        if result in ("Win", True, 1):
            return i
    return None


# ---------------------------------------------------------------------------
# Main parsing function
# ---------------------------------------------------------------------------

def _parse_screp_json(data: dict) -> ReplayData:
    """Transform screp's raw JSON into a ReplayData object."""

    # Log top-level keys to help diagnose structure issues
    log.info(f"screp JSON top-level keys: {list(data.keys())}")

    header = data.get("Header", {})
    map_name: str = header.get("Map", "Unknown Map")
    total_frames: int = header.get("Frames", 0)
    duration_seconds = _frames_to_seconds(total_frames)

    players_raw: list = header.get("Players", [])
    winner_idx = _determine_winner(players_raw)

    # --- Commands section ---
    # screp's "Commands" value is a list of tuples:
    #   [(player_index, [cmd_dict, ...]), (player_index, [...]), ..., ("ParseErrCmds", None)]
    # Each tuple's first element is the player index (int), second is the command list.
    # Non-player entries like ("ParseErrCmds", None) are skipped.
    # Some versions also emit a flat list of dicts with "PlayerID" — we handle both.
    raw_cmds_raw = data.get("Commands", [])
    commands_by_player: dict[int, list[dict]] = {}
    flat_cmds: list[dict] = []

    if isinstance(raw_cmds_raw, list):
        for item in raw_cmds_raw:
            if isinstance(item, dict):
                # Flat format: each dict has a PlayerID field
                pid = item.get("PlayerID", item.get("Player", -1))
                commands_by_player.setdefault(pid, []).append(item)
                flat_cmds.append(item)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                # Tuple format: (player_index_or_key, [cmd_list])
                key, cmds = item
                if not isinstance(cmds, list):
                    continue  # e.g. ('ParseErrCmds', None)
                try:
                    pid = int(key)
                except (ValueError, TypeError):
                    continue  # skip non-integer keys like 'ParseErrCmds'
                valid = [c for c in cmds if isinstance(c, dict)]
                commands_by_player.setdefault(pid, []).extend(valid)
                flat_cmds.extend(valid)

    elif isinstance(raw_cmds_raw, dict):
        for key, cmds in raw_cmds_raw.items():
            try:
                pid = int(key)
            except (ValueError, TypeError):
                pid = -1
            if isinstance(cmds, list):
                valid = [c for c in cmds if isinstance(c, dict)]
                commands_by_player[pid] = valid
                flat_cmds.extend(valid)

    raw_cmds = flat_cmds  # flat list used for chat extraction below
    log.info(f"Commands by player keys: {list(commands_by_player.keys())}, total cmds: {len(flat_cmds)}")

    # Computed APM data
    computed = data.get("Computed", {})
    player_descs = computed.get("PlayerDescs", [])

    log.info(f"Players found: {len(players_raw)}, PlayerDescs: {len(player_descs)}, Commands players: {list(commands_by_player.keys())}")

    players: list[PlayerStats] = []
    races: list[str] = []

    for i, p in enumerate(players_raw):
        if not isinstance(p, dict):
            continue

        # Skip non-playing slots
        p_type = p.get("Type", {})
        if isinstance(p_type, dict):
            p_type = p_type.get("Name", "")
        log.info(f"Player {i}: name={p.get('Name')} type={p_type!r} race={p.get('Race')} ID={p.get('ID')}")
        # Accept Human, Computer, and empty/unknown types
        # Some screp versions use "Human", others use "h" or leave it blank
        if p_type and p_type not in ("Human", "Computer", "h", "computer", "human"):
            log.info(f"  -> Skipping player {i} with type {p_type!r}")
            continue

        race = _race_name(p.get("Race", ""))
        races.append(race[0] if race else "?")

        desc = player_descs[i] if i < len(player_descs) else {}
        apm  = desc.get("APM", 0)  if isinstance(desc, dict) else 0
        eapm = desc.get("EAPM", 0) if isinstance(desc, dict) else 0

        player_id = p.get("ID", i)
        cmds = commands_by_player.get(player_id) or commands_by_player.get(i, [])
        build_order  = _build_order_from_cmds(cmds)
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

    # --- Extract chat messages ---
    # Build a name lookup by player ID, slot ID, and index
    player_name_by_id: dict[int, str] = {}
    for i, p in enumerate(players_raw):
        if not isinstance(p, dict):
            continue
        name = p.get("Name", f"Player {i + 1}")
        pid = p.get("ID", i)
        slot = p.get("SlotID", p.get("Slot", i))
        player_name_by_id[pid] = name
        player_name_by_id[i] = name        # index fallback
        player_name_by_id[slot] = name     # slot fallback
        log.info(f"Chat name map: ID={pid} slot={slot} index={i} -> {name!r}")

    chat_log: list[ChatMessage] = []
    for cmd in (raw_cmds if isinstance(raw_cmds, list) else []):
        if not isinstance(cmd, dict):
            continue
        if _safe_get(cmd, "Type", "Name") != "Chat":
            continue
        frame = cmd.get("Frame", 0)
        message = cmd.get("Message", "").strip()
        if not message:
            continue
        # screp uses SenderSlotID for chat, not PlayerID
        sender_slot = cmd.get("SenderSlotID", cmd.get("PlayerID", -1))
        pname = player_name_by_id.get(sender_slot, f"Player {sender_slot}")
        chat_log.append(ChatMessage(
            time_seconds=_frames_to_seconds(frame),
            player_name=pname,
            message=message,
        ))

    return ReplayData(
        map_name=map_name,
        duration_seconds=duration_seconds,
        matchup=matchup,
        players=players,
        chat_log=chat_log,
    )


# ---------------------------------------------------------------------------
# Public async entry-point
# ---------------------------------------------------------------------------

async def parse_replay(rep_path: Path) -> ReplayData:
    if not SCREP_BINARY.exists():
        raise FileNotFoundError(
            f"screp binary not found at {SCREP_BINARY}. "
            "Download it from https://github.com/icza/screp/releases "
            "and place it next to bot.py."
        )

    # Ensure executable at runtime (Railway/Linux)
    if sys.platform != "win32":
        current = os.stat(SCREP_BINARY).st_mode
        os.chmod(SCREP_BINARY, current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run() -> dict:
        result = subprocess.run(
            [str(SCREP_BINARY), "-cmds", "-computed", str(rep_path)],
            capture_output=True,
            text=True,
            timeout=SCREP_TIMEOUT,
        )
        if result.returncode != 0:
            raise ValueError(f"screp error: {result.stderr.strip()}")

        raw = json.loads(result.stdout)

        # Debug: log a sample of the raw structure to help diagnose issues
        if "Commands" in raw:
            cmds = raw["Commands"]
            sample = cmds[:2] if isinstance(cmds, list) else list(cmds.items())[:2]
            log.info(f"Commands type: {type(cmds).__name__}, sample: {sample}")

        return raw

    loop = asyncio.get_event_loop()
    raw = await loop.run_in_executor(None, _run)
    return _parse_screp_json(raw)
