"""Serializable state for a notes-bot meeting session."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from tool_modules.aa_meet_bot.src.notes_database import TranscriptEntry


@dataclass
class NotesBotState:  # pylint: disable=too-many-instance-attributes
    """Current state of the notes bot.

    The disable is required because these fields are the public session record.
    Nesting them would change every caller that reads ``state.meeting_id``.
    """

    meeting_id: Optional[int] = None  # Database meeting ID
    meet_url: str = ""
    title: str = ""
    calendar_id: str = ""
    event_id: str = ""

    # Status
    status: str = "idle"  # idle, joining, capturing, leaving, error
    joined_at: Optional[datetime] = None

    # Transcript buffer (for batching writes)
    transcript_buffer: list[TranscriptEntry] = field(default_factory=list)
    buffer_flush_interval: float = 10.0  # Flush every 10 seconds
    last_flush: Optional[datetime] = None

    # Caption ID tracking for update-in-place
    caption_id_to_index: dict[int, int] = field(default_factory=dict)

    # Stats
    captions_captured: int = 0
    wake_word_triggers: int = 0
    errors: list[str] = field(default_factory=list)
