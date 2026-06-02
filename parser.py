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
class HotkeyStats:
    """Lightweight summary of a player's control-group usage."""
    # group number (0-9) -> label "Army" / "Production" / "Mixed" / "Unused"
    group_roles: dict[int, str] = field(default_factory=dict)
    # how many times the player double-tapped any hotkey to snap camera
    camera_snaps: int = 0
    # total hotkey selects (single taps that changed selection)
    total_selects: int = 0


@dataclass
class PlayerStats:
    name: str
    race: str
    is_winner: bool
    apm: int
    eapm: int
    build_order: list[BuildOrderEntry] = field(default_factory=list)
    apm_timeline: list[tuple[float, int]] = field(default_factory=list)
    hotkeys: HotkeyStats = field(default_factory=HotkeyStats)


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
    """Normalise screp race — handles string, short string, or dict."""
    if isinstance(raw, dict):
        # screp returns {"Name": "Zerg", "ShortName": "zerg", "Letter": 90}
        raw = raw.get("Name") or raw.get("ShortName", "")
    if not raw:
        return "Unknown"
    # Normalise to title case
    raw = str(raw).strip().title()
    mapping = {
        "T": "Terran", "Terran": "Terran",
        "P": "Protoss", "Protoss": "Protoss", "Toss": "Protoss",
        "Z": "Zerg",    "Zerg": "Zerg",
        "R": "Random",  "Random": "Random",
    }
    return mapping.get(raw, raw)


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
    # How many times we allow the same unit/building to appear in the build order.
    # Workers and basic combat units are capped low since they repeat constantly;
    # buildings and key tech units are shown every time they appear.
    WORKER_NAMES = {"Probe", "SCV", "Drone"}
    REPEAT_CAPS: dict[str, int] = {name: 2 for name in WORKER_NAMES}
    DEFAULT_CAP = 6   # anything not listed gets up to 6 entries

    entries: list[BuildOrderEntry] = []
    counts: dict[str, int] = {}

    for cmd in commands:
        if not isinstance(cmd, dict):
            continue

        cmd_type = _safe_get(cmd, "Type", "Name") or ""
        if cmd_type not in BUILD_CMD_TYPES:
            continue

        unit_name = (
            _safe_get(cmd, "Unit", "Name")
            or _safe_get(cmd, "UnitType", "Name")
            or _safe_get(cmd, "TechType", "Name")
            or _safe_get(cmd, "UpgradeType", "Name")
            or cmd.get("UnitName")
            or "Unknown"
        )
        if unit_name in ("None", "Unknown"):
            continue

        cap = REPEAT_CAPS.get(unit_name, DEFAULT_CAP)
        current = counts.get(unit_name, 0)
        if current >= cap:
            continue
        counts[unit_name] = current + 1

        frame = cmd.get("Frame", 0)
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



# Command-type classification for hotkey role detection
_PRODUCTION_ACTIONS = frozenset({
    "Train", "Build", "Research", "Upgrade",
    "Building Morph", "Unit Morph", "Morph",
})
_ARMY_ACTIONS = frozenset({
    "Right Click", "Targeted Order", "Stop", "Hold Position",
    "Attack", "Attack Move", "Use Magic", "Move",
})

# Double-tap (camera snap) threshold in frames (~500ms at 23.81 fps)
_DOUBLE_TAP_FRAMES = 12


def _analyze_hotkeys(commands: list) -> HotkeyStats:
    """
    Single-pass analysis of one player's commands.

    Tallies army vs production actions per control group by looking at the
    command issued immediately after each Hotkey-Select, and counts camera
    snaps (rapid double-taps of the same group).

    Only a small fixed-size HotkeyStats summary is returned — the raw command
    list is never copied or retained.
    """
    # group -> [army_tally, production_tally]
    tallies: dict[int, list[int]] = {g: [0, 0] for g in range(10)}

    last_selected_group: int | None = None   # set by a Hotkey-Select, consumed by next cmd
    last_select_frame: dict[int, int] = {}    # group -> frame of its previous select
    camera_snaps = 0
    total_selects = 0

    for cmd in commands:
        if not isinstance(cmd, dict):
            continue

        ctype = _safe_get(cmd, "Type", "Name") or ""

        if ctype == "Hotkey":
            hk_action = _safe_get(cmd, "HotkeyType", "Name") or ""
            group = cmd.get("Group", -1)
            frame = cmd.get("Frame", 0)

            if hk_action == "Select":
                total_selects += 1
                # Camera snap: same group selected again within the threshold
                prev = last_select_frame.get(group)
                if prev is not None and (frame - prev) <= _DOUBLE_TAP_FRAMES:
                    camera_snaps += 1
                last_select_frame[group] = frame
                # Arm the action-pair detector for the next command
                last_selected_group = group
            else:
                # Assign / Add — not a selection, clear the pending pair
                last_selected_group = None
            continue

        # If the previous command was a Hotkey-Select, this command reveals
        # what that group is used for.
        if last_selected_group is not None and 0 <= last_selected_group <= 9:
            if ctype in _PRODUCTION_ACTIONS:
                tallies[last_selected_group][1] += 1
            elif ctype in _ARMY_ACTIONS:
                tallies[last_selected_group][0] += 1
            # Consume the pairing regardless so we only judge the immediate next cmd
            last_selected_group = None

    # Resolve each group's role from its tallies
    group_roles: dict[int, str] = {}
    for group, (army, prod) in tallies.items():
        total = army + prod
        if total == 0:
            continue  # unused — omit from summary
        if army >= prod * 4:
            group_roles[group] = "Army"
        elif prod >= army * 4:
            group_roles[group] = "Production"
        else:
            group_roles[group] = "Mixed"

    return HotkeyStats(
        group_roles=group_roles,
        camera_snaps=camera_snaps,
        total_selects=total_selects,
    )


def _determine_winner(players_raw: list, flat_cmds: list = None) -> Optional[int]:
    # First try: use the Result field screp may provide
    for i, p in enumerate(players_raw):
        if not isinstance(p, dict):
            continue
        result = p.get("Result") or p.get("Win")
        if isinstance(result, dict):
            result = result.get("Name") or result.get("ID")
        if result in ("Win", "win", True, 1):
            return i

    # Second try: the player who sent "Leave Game" lost; the other one won
    if flat_cmds:
        leave_pids = set()
        for cmd in flat_cmds:
            if not isinstance(cmd, dict):
                continue
            cmd_name = cmd.get("Type", {})
            if isinstance(cmd_name, dict):
                cmd_name = cmd_name.get("Name", "")
            if cmd_name == "Leave Game":
                leave_pids.add(cmd.get("PlayerID", -1))

        human_pids = [
            p.get("ID", i)
            for i, p in enumerate(players_raw)
            if isinstance(p, dict)
            and (p.get("Type", {}).get("Name") if isinstance(p.get("Type"), dict) else p.get("Type", "")) in ("Human", "")
        ]

        winners = [pid for pid in human_pids if pid not in leave_pids]
        if len(winners) == 1:
            # Map player ID back to index
            for i, p in enumerate(players_raw):
                if isinstance(p, dict) and p.get("ID", i) == winners[0]:
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

    # --- Commands section ---
    # screp returns Commands as a dict: {"Cmds": [list of all cmds], "ParseErrCmds": None}
    # Each cmd dict has a "PlayerID" field (0 or 1).
    raw_cmds_raw = data.get("Commands", {})
    commands_by_player: dict[int, list[dict]] = {}
    flat_cmds: list[dict] = []

    # Extract the flat command list from the "Cmds" key
    if isinstance(raw_cmds_raw, dict):
        cmd_list = raw_cmds_raw.get("Cmds", []) or []
    elif isinstance(raw_cmds_raw, list):
        cmd_list = raw_cmds_raw
    else:
        cmd_list = []

    for item in cmd_list:
        if not isinstance(item, dict):
            continue
        pid = item.get("PlayerID", item.get("Player", -1))
        commands_by_player.setdefault(pid, []).append(item)
        flat_cmds.append(item)

    raw_cmds = flat_cmds  # flat list used for chat extraction below
    log.info(f"Commands by player keys: {list(commands_by_player.keys())}, total cmds: {len(flat_cmds)}")

    winner_idx = _determine_winner(players_raw, flat_cmds)

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
        log.info(f"Player {i}: name={p.get('Name')} type={p_type!r} race={p.get('Race')} ID={p.get('ID')} SlotID={p.get('SlotID')} TeamID={p.get('TeamID')}")
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
        hotkeys      = _analyze_hotkeys(cmds)

        players.append(PlayerStats(
            name=p.get("Name", f"Player {i + 1}"),
            race=race,
            is_winner=(winner_idx == i),
            apm=apm,
            eapm=eapm,
            build_order=build_order,
            apm_timeline=apm_timeline,
            hotkeys=hotkeys,
        ))

    matchup = "v".join(races) if len(races) == 2 else "?v?"

    # --- Extract chat messages ---
    # SenderSlotID in chat commands maps to the player's SlotID field.
    # We build the lookup using SlotID as the primary key only.
    player_name_by_slot: dict[int, str] = {}
    for i, p in enumerate(players_raw):
        if not isinstance(p, dict):
            continue
        name = p.get("Name", f"Player {i + 1}")
        pid  = p.get("ID", i)
        slot = p.get("SlotID", p.get("Slot", None))
        # Primary: map by SlotID (what SenderSlotID refers to)
        if slot is not None:
            player_name_by_slot[slot] = name
        # Fallback: map by player ID and index in case SlotID is absent
        player_name_by_slot.setdefault(pid, name)
        player_name_by_slot.setdefault(i, name)
        log.info(f"Chat slot map: index={i} ID={pid} SlotID={slot} -> {name!r}")

    chat_log: list[ChatMessage] = []
    for cmd in (raw_cmds if isinstance(raw_cmds, list) else []):
        if not isinstance(cmd, dict):
            continue
        if _safe_get(cmd, "Type", "Name") != "Chat":
            continue
        frame   = cmd.get("Frame", 0)
        message = cmd.get("Message", "").strip()
        if not message:
            continue
        sender = cmd.get("SenderSlotID", cmd.get("PlayerID", -1))
        pname  = player_name_by_slot.get(sender, f"Player {sender}")
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
