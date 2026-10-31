"""Shared Meet Bot runtime state (lazily created controllers, managers and tasks)."""

import asyncio
import importlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
from tool_modules.aa_meet_bot.src.meeting_scheduler import MeetingScheduler, init_scheduler
from tool_modules.aa_meet_bot.src.notes_bot import NotesBot
from tool_modules.aa_meet_bot.src.notes_database import MeetingNotesDB, init_notes_db
from tool_modules.aa_meet_bot.src.notes_session import NotesBotManager, get_bot_manager
from tool_modules.aa_meet_bot.src.virtual_devices import VirtualDeviceManager
from tool_modules.aa_meet_bot.src.wake_word import WakeWordManager

logger = logging.getLogger(__name__)

MAX_APPROVED_MEETINGS = 50


def _optional_playwright_errors() -> tuple[type[Exception], ...]:
    """Return Playwright's base error when Playwright is installed."""
    errors: list[type[Exception]] = []
    try:
        errors.append(importlib.import_module("playwright.async_api").Error)
    except ImportError:
        logger.debug("Playwright not installed; no browser errors to catch")
    return tuple(errors)


# Failures expected at the tool boundary: browser automation, audio/video
# devices, subprocesses, network calls and malformed data.
MEET_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    LookupError,
    AttributeError,
    ImportError,
    asyncio.TimeoutError,
    *_optional_playwright_errors(),
)


def local_now() -> datetime:
    """Current local wall-clock time as a naive datetime.

    Controllers and the notes database store naive local timestamps, so
    comparisons must stay naive.
    """
    return datetime.now(tz=timezone.utc).astimezone().replace(tzinfo=None)


@dataclass
class BotState:
    """Single-meeting bot state."""

    controller: GoogleMeetController | None = None
    device_manager: VirtualDeviceManager | None = None
    wake_word_manager: WakeWordManager | None = None
    approved_meetings: dict[str, dict] = field(default_factory=dict)  # meeting_id -> meeting info


@dataclass
class NotesState:
    """Notes bot state."""

    notes_bot: NotesBot | None = None  # Legacy single-bot mode
    bot_manager: NotesBotManager | None = None  # Multi-meeting mode
    scheduler: MeetingScheduler | None = None
    db: MeetingNotesDB | None = None


@dataclass
class CleanupState:
    """Background device-cleanup state."""

    startup_done: bool = False
    task: asyncio.Task | None = None


BOT = BotState()
NOTES = NotesState()
CLEANUP = CleanupState()


async def ensure_controller() -> GoogleMeetController:
    """Get or create the browser controller."""
    if BOT.controller is None:
        BOT.controller = GoogleMeetController()
        await BOT.controller.initialize()
    return BOT.controller


async def ensure_device_manager() -> VirtualDeviceManager:
    """Get or create the device manager."""
    if BOT.device_manager is None:
        BOT.device_manager = VirtualDeviceManager()
    return BOT.device_manager


async def ensure_wake_word_manager() -> WakeWordManager:
    """Get or create the wake word manager."""
    if BOT.wake_word_manager is None:
        BOT.wake_word_manager = WakeWordManager()
        await BOT.wake_word_manager.initialize()
    return BOT.wake_word_manager


async def ensure_notes_db() -> MeetingNotesDB:
    """Get or create the notes database."""
    if NOTES.db is None:
        NOTES.db = await init_notes_db()
    return NOTES.db


async def ensure_notes_bot() -> NotesBot:
    """Get or create the notes bot (legacy single-bot mode)."""
    if NOTES.notes_bot is None:
        bot = NotesBot()
        # Kept even if initialization fails, so callers can report its errors
        await bot.initialize()
        NOTES.notes_bot = bot
    return NOTES.notes_bot


async def ensure_bot_manager() -> NotesBotManager:
    """Get or create the bot manager for multi-meeting support."""
    if NOTES.bot_manager is None:
        NOTES.bot_manager = get_bot_manager()
    return NOTES.bot_manager


async def ensure_scheduler() -> MeetingScheduler:
    """Get or create the scheduler."""
    if NOTES.scheduler is None:
        NOTES.scheduler = await init_scheduler()
    return NOTES.scheduler


def active_controller_ids() -> set[str]:
    """Instance ids of the browser controllers used by active notes sessions."""
    manager = NOTES.bot_manager
    if manager is None:
        return set()
    ids = set()
    for session_id in manager.get_active_session_ids():
        bot = manager.get_bot(session_id)
        instance_id = bot.controller_instance_id() if bot else None
        if instance_id:
            ids.add(instance_id)
    return ids
