"""
embed_builder.py — Builds discord.Embed objects from ReplayData.

Kept separate from bot.py so the logic is easy to test and tweak
without touching the Discord event handling.
"""

from pathlib import Path

import discord

from config import RACE_EMOJI, PLAYER_COLORS
from parser import ReplayData, PlayerStats


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _hex_to_int(hex_color: str) -> int:
    """Convert '#RRGGBB' → integer for discord.Colour."""
    return int(hex_color.lstrip("#"), 16)


def _matchup_color(matchup: str) -> discord.Colour:
    """Pick embed accent colour based on matchup."""
    colors = {
        "TvT": 0x607D8B,
        "PvP": 0x9C27B0,
        "ZvZ": 0x4CAF50,
        "TvP": 0x2196F3, "PvT": 0x2196F3,
        "TvZ": 0xFF5722, "ZvT": 0xFF5722,
        "PvZ": 0xFFEB3B, "ZvP": 0xFFEB3B,
    }
    return discord.Colour(colors.get(matchup, 0x00BFFF))


# ---------------------------------------------------------------------------
# Result badge
# ---------------------------------------------------------------------------

def _result_badge(player: PlayerStats) -> str:
    if player.is_winner:
        return "🏆 **WIN**"
    return "💀 **LOSS**"


# ---------------------------------------------------------------------------
# Build order text
# ---------------------------------------------------------------------------

def _hotkey_text(player: PlayerStats) -> str:
    """Format the control-group usage summary, one group per line."""
    hk = player.hotkeys
    if not hk.group_roles and hk.camera_snaps == 0:
        return "*No hotkey data*"

    role_emoji = {"Army": "⚔️", "Production": "🏭", "Mixed": "🔀"}
    lines = [
        f"`{g}` {role_emoji.get(role, '•')} {role}"
        for g, role in sorted(hk.group_roles.items())
    ]
    if lines:
        lines.append("")   # blank spacer line before the snap count
    lines.append(f"📷 Camera snaps: **{hk.camera_snaps}**")
    return "\n".join(lines)


def _build_order_text(player: PlayerStats) -> str:
    if not player.build_order:
        return "*No build order data*"
    lines = [
        f"`{int(e.time_seconds // 60):02d}:{int(e.time_seconds % 60):02d}` {e.name}"
        for e in player.build_order
    ]
    # Discord field value limit is 1024 chars — fit as many lines as possible
    MAX_CHARS = 1016
    text = ""
    for line in lines:
        candidate = text + line + "\n"
        if len(candidate) > MAX_CHARS:
            text += "…"
            break
        text = candidate
    return text.rstrip()


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------

def build_embed(replay: ReplayData, chart_paths: list[Path]) -> tuple[discord.Embed, list[discord.File]]:
    """
    Returns:
        embed  — the rich Discord embed
        files  — list of discord.File objects (charts) to attach
    """
    embed = discord.Embed(
        title=f"📺  Replay Analysis — {replay.matchup}",
        colour=_matchup_color(replay.matchup),
    )

    # ── Header row ──────────────────────────────────────────────────────────
    embed.add_field(name="🗺️  Map", value=replay.map_name, inline=True)
    embed.add_field(name="⏱️  Duration", value=replay.duration_str, inline=True)
    embed.add_field(name="⚔️  Matchup", value=replay.matchup, inline=True)

    embed.add_field(name="\u200b", value="", inline=False)   # spacer

    # ── Per-player fields ────────────────────────────────────────────────────
    for i, player in enumerate(replay.players):
        race_emoji = RACE_EMOJI.get(player.race, "❓")
        color_dot = "🔵" if i == 0 else "🔴"

        # Stats block
        stats = (
            f"{_result_badge(player)}\n"
            f"Race: {race_emoji} {player.race}\n"
            f"APM: **{player.apm}** (eAPM: {player.eapm})"
        )
        embed.add_field(
            name=f"{color_dot}  {player.name}",
            value=stats,
            inline=True,
        )

    embed.add_field(name="\u200b", value="", inline=False)   # spacer

    # ── Build orders ─────────────────────────────────────────────────────────
    for i, player in enumerate(replay.players):
        race_emoji = RACE_EMOJI.get(player.race, "❓")
        embed.add_field(
            name=f"{race_emoji}  {player.name} — Build Order",
            value=_build_order_text(player),
            inline=True,
        )

    embed.add_field(name="\u200b", value="", inline=False)   # spacer

    # ── Hotkey / control-group usage ─────────────────────────────────────────
    for i, player in enumerate(replay.players):
        race_emoji = RACE_EMOJI.get(player.race, "❓")
        embed.add_field(
            name=f"{race_emoji}  {player.name} — Hotkeys",
            value=_hotkey_text(player),
            inline=True,
        )

    # ── Chat log ─────────────────────────────────────────────────────────────
    if replay.chat_log:
        lines = [
            f"`{msg.time_str}` **{msg.player_name}:** {msg.message}"
            for msg in replay.chat_log
        ]
        # Discord field value limit is 1024 chars — truncate if needed
        chat_text = "\n".join(lines)
        if len(chat_text) > 1020:
            chat_text = chat_text[:1020] + "\n…"
        embed.add_field(name="💬  In-Game Chat", value=chat_text, inline=False)
    else:
        embed.add_field(name="💬  In-Game Chat", value="*No messages*", inline=False)

    # ── Attach charts ─────────────────────────────────────────────────────────
    files: list[discord.File] = []

    if chart_paths:
        first = chart_paths[0]
        files.append(discord.File(first, filename=first.name))
        embed.set_image(url=f"attachment://{first.name}")

        for path in chart_paths[1:]:
            files.append(discord.File(path, filename=path.name))

    embed.set_footer(text="Powered by screp • StarCraft: Brood War Replay Bot")

    return embed, files
