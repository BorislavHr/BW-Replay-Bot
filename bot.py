"""
bot.py — StarCraft Brood War replay bot entry-point.

Listens for .rep file uploads in any channel the bot can read,
parses them with screp, generates charts, and posts a rich embed.
"""

import asyncio
import logging
import uuid
from pathlib import Path

import discord
from discord.ext import commands

from config import DISCORD_TOKEN, TEMP_DIR
from embed_builder import build_embed
from parser import parse_replay
# visualizer is imported lazily in _handle_replay to avoid startup memory spike

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sc-replay-bot")


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True          # Required to read attachment filenames

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    log.info(f"Logged in as {bot.user} (id={bot.user.id})")
    log.info("Listening for .rep file uploads…")


@bot.event
async def on_message(message: discord.Message):
    # Ignore the bot's own messages
    if message.author.bot:
        return

    # Check for .rep attachments
    rep_attachments = [
        att for att in message.attachments
        if att.filename.lower().endswith(".rep")
    ]

    if not rep_attachments:
        await bot.process_commands(message)     # Still handle !commands
        return

    # Process all .rep files in the message (usually just one)
    for attachment in rep_attachments:
        await _handle_replay(message, attachment)

    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Core replay handling
# ---------------------------------------------------------------------------

async def _handle_replay(message: discord.Message, attachment: discord.Attachment) -> None:
    """Download, parse, visualize, and post the replay analysis."""

    uid = uuid.uuid4().hex[:8]
    rep_path = TEMP_DIR / f"{uid}_{attachment.filename}"
    chart_paths: list[Path] = []

    async with message.channel.typing():
        try:
            # 1. Download the replay file
            log.info(f"Downloading {attachment.filename} from {message.author}")
            await attachment.save(rep_path)

            # 2. Parse with screp
            log.info(f"Parsing {rep_path.name}…")
            replay = await parse_replay(rep_path)
            log.info(
                f"Parsed: {replay.matchup} on {replay.map_name} "
                f"({replay.duration_str})"
            )

            # 3. Generate charts + minimap (lazy import to avoid startup memory spike)
            log.info("Generating charts…")
            from visualizer import generate_charts, generate_minimap
            chart_paths = await generate_charts(replay, uid)
            log.info(f"Generated {len(chart_paths)} chart(s)")

            log.info("Generating minimap…")
            minimap_path = await generate_minimap(replay, rep_path, uid)
            if minimap_path:
                log.info(f"Minimap generated: {minimap_path.name}")
            else:
                log.info("No minimap generated")

            # 4. Build embed + send
            embed, files = build_embed(replay, chart_paths, minimap_path)

            await message.reply(
                embed=embed,
                files=files,
                mention_author=False,
            )

        except FileNotFoundError as exc:
            log.error(f"screp binary missing: {exc}")
            await message.reply(
                "⚠️ **Setup error:** The `screp` binary was not found. "
                "Please ask the bot admin to install it.",
                mention_author=False,
            )

        except ValueError as exc:
            log.error(f"Parsing failed: {exc}")
            await message.reply(
                f"❌ **Could not parse replay:** {exc}\n"
                "Make sure the file is a valid Brood War `.rep` replay.",
                mention_author=False,
            )

        except discord.HTTPException as exc:
            log.error(f"Discord error sending response: {exc}")

        except Exception as exc:
            log.exception(f"Unexpected error processing {attachment.filename}: {exc}")
            await message.reply(
                "💥 An unexpected error occurred while processing the replay. "
                "Check the bot logs for details.",
                mention_author=False,
            )

        finally:
            # Clean up temp files regardless of success/failure
            extra = [minimap_path] if "minimap_path" in dir() and minimap_path else []
            _cleanup([rep_path] + chart_paths + extra)


def _cleanup(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            log.warning(f"Could not delete temp file {path}: {exc}")


# ---------------------------------------------------------------------------
# Optional slash / prefix commands
# ---------------------------------------------------------------------------

@bot.command(name="help_replay", aliases=["replayhelp"])
async def help_replay(ctx: commands.Context):
    """Show usage instructions."""
    embed = discord.Embed(
        title="📘 StarCraft Replay Bot — Help",
        description=(
            "Just **upload a `.rep` file** in any channel and I'll automatically "
            "analyse it and post the results!\n\n"
            "**What I show:**\n"
            "• Map name & game duration\n"
            "• Player names, races, APM / eAPM\n"
            "• Win/loss result\n"
            "• Build order timeline\n"
            "• APM-over-time chart\n"
        ),
        colour=discord.Colour.blurple(),
    )
    embed.set_footer(text="Powered by screp • StarCraft: Brood War")
    await ctx.send(embed=embed)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if DISCORD_TOKEN == "YOUR_TOKEN_HERE":
        log.error(
            "No Discord token set! "
            "Set the DISCORD_TOKEN environment variable or edit config.py."
        )
        raise SystemExit(1)

    bot.run(DISCORD_TOKEN, log_handler=None)   # We manage our own logger
