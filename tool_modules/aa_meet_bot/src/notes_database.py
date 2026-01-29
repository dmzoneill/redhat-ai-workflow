"""
Meeting Notes Database.

SQLite-based storage for meeting transcripts and notes.
Provides persistent storage for:
- Meeting metadata (title, calendar, participants, times)
- Full transcripts (speaker, text, timestamp)
- AI-generated summaries and action items

Database location: ~/.config/aa-workflow/meetings.db
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# Default database path - centralized in server.paths
try:
    from server.paths import MEETINGS_DB_FILE

    DEFAULT_DB_PATH = MEETINGS_DB_FILE
except ImportError:
    # Fallback for standalone usage
    DEFAULT_DB_PATH = Path.home() / ".config" / "aa-workflow" / "meetings.db"


@dataclass
class TranscriptEntry:
    """A single transcript entry."""

    speaker: str
    text: str
    timestamp: datetime
    id: Optional[int] = None
    meeting_id: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "meeting_id": self.meeting_id,
            "speaker": self.speaker,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class MeetingNote:
    """A meeting with its metadata and notes."""

    id: Optional[int] = None
    title: str = ""
    calendar_id: str = ""  # Which calendar this came from
    calendar_name: str = ""
    meet_url: str = ""
    event_id: str = ""  # Google Calendar event ID

    # Timing
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None

    # Participants
    organizer: str = ""
    attendees: list[str] = field(default_factory=list)

    # Content
    description: str = ""  # Event description
    transcript: list[TranscriptEntry] = field(default_factory=list)
    summary: str = ""  # AI-generated summary
    action_items: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    # Status
    status: str = "scheduled"  # scheduled, in_progress, completed, cancelled
    bot_mode: str = "notes"  # notes (just capture) or interactive (AI voice)

    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "calendar_id": self.calendar_id,
            "calendar_name": self.calendar_name,
            "meet_url": self.meet_url,
            "event_id": self.event_id,
            "scheduled_start": self.scheduled_start.isoformat() if self.scheduled_start else None,
            "scheduled_end": self.scheduled_end.isoformat() if self.scheduled_end else None,
            "actual_start": self.actual_start.isoformat() if self.actual_start else None,
            "actual_end": self.actual_end.isoformat() if self.actual_end else None,
            "organizer": self.organizer,
            "attendees": self.attendees,
            "description": self.description,
            "summary": self.summary,
            "action_items": self.action_items,
            "tags": self.tags,
            "status": self.status,
            "bot_mode": self.bot_mode,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "transcript_count": len(self.transcript),
        }


@dataclass
class MonitoredCalendar:
    """A calendar being monitored for meetings."""

    id: Optional[int] = None
    calendar_id: str = ""  # Google Calendar ID (email or calendar ID)
    name: str = ""
    description: str = ""
    color: str = ""
    is_primary: bool = False
    auto_join: bool = True  # Automatically join meetings from this calendar
    bot_mode: str = "notes"  # Default mode: notes or interactive
    enabled: bool = True
    added_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "calendar_id": self.calendar_id,
            "name": self.name,
            "description": self.description,
            "color": self.color,
            "is_primary": self.is_primary,
            "auto_join": self.auto_join,
            "bot_mode": self.bot_mode,
            "enabled": self.enabled,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }


class MeetingNotesDB:
    """
    SQLite database for meeting notes and transcripts.

    Thread-safe with async support via aiosqlite.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the database.

        Args:
            db_path: Path to SQLite database file. Defaults to ~/.config/aa-workflow/meetings.db
        """
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Connect to database and create tables."""
        async with self._lock:
            await self._connect_internal()

    async def _connect_internal(self) -> None:
        """Internal connect (caller must hold lock)."""
        if self._db is None:
            # Use timeout and WAL mode for better concurrency
            self._db = await aiosqlite.connect(self.db_path, timeout=30.0)
            self._db.row_factory = aiosqlite.Row
            # Enable WAL mode for better concurrent access
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA busy_timeout=30000")
            await self._create_tables()
            logger.info(f"Connected to meetings database: {self.db_path}")

    async def close(self) -> None:
        """Close database connection."""
        async with self._lock:
            if self._db:
                await self._db.close()
                self._db = None

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        if not self._db:
            return

        # Monitored calendars table
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS calendars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                calendar_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                color TEXT DEFAULT '',
                is_primary INTEGER DEFAULT 0,
                auto_join INTEGER DEFAULT 1,
                bot_mode TEXT DEFAULT 'notes',
                enabled INTEGER DEFAULT 1,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Meetings table
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                calendar_id TEXT,
                calendar_name TEXT,
                meet_url TEXT,
                event_id TEXT,
                scheduled_start TEXT,
                scheduled_end TEXT,
                actual_start TEXT,
                actual_end TEXT,
                organizer TEXT,
                attendees TEXT,
                description TEXT,
                summary TEXT,
                action_items TEXT,
                tags TEXT,
                status TEXT DEFAULT 'scheduled',
                bot_mode TEXT DEFAULT 'notes',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(event_id, calendar_id)
            )
        """
        )

        # Transcripts table
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER NOT NULL,
                speaker TEXT NOT NULL,
                text TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
            )
        """
        )

        # Create indexes
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_meetings_calendar ON meetings(calendar_id)
        """
        )
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status)
        """
        )
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_meetings_scheduled ON meetings(scheduled_start)
        """
        )
        await self._db.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transcripts_meeting ON transcripts(meeting_id)
        """
        )

        # Full-text search for transcripts
        await self._db.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
                speaker, text, content=transcripts, content_rowid=id
            )
        """
        )

        # Triggers to keep FTS in sync
        await self._db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS transcripts_ai AFTER INSERT ON transcripts BEGIN
                INSERT INTO transcripts_fts(rowid, speaker, text) VALUES (new.id, new.speaker, new.text);
            END
        """
        )
        await self._db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS transcripts_ad AFTER DELETE ON transcripts BEGIN
                INSERT INTO transcripts_fts(transcripts_fts, rowid, speaker, text) VALUES('delete', old.id, old.speaker, old.text);
            END
        """
        )
        await self._db.execute(
            """
            CREATE TRIGGER IF NOT EXISTS transcripts_au AFTER UPDATE ON transcripts BEGIN
                INSERT INTO transcripts_fts(transcripts_fts, rowid, speaker, text) VALUES('delete', old.id, old.speaker, old.text);
                INSERT INTO transcripts_fts(rowid, speaker, text) VALUES (new.id, new.speaker, new.text);
            END
        """
        )

        await self._db.commit()

    # ==================== Calendar Operations ====================

    async def add_calendar(self, calendar: MonitoredCalendar) -> int:
        """Add a calendar to monitor."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                raise RuntimeError("Database not connected")

            cursor = await self._db.execute(
                """
                INSERT OR REPLACE INTO calendars
                (calendar_id, name, description, color, is_primary, auto_join, bot_mode, enabled, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    calendar.calendar_id,
                    calendar.name,
                    calendar.description,
                    calendar.color,
                    1 if calendar.is_primary else 0,
                    1 if calendar.auto_join else 0,
                    calendar.bot_mode,
                    1 if calendar.enabled else 0,
                    datetime.now().isoformat(),
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_calendars(self, enabled_only: bool = True) -> list[MonitoredCalendar]:
        """Get all monitored calendars."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return []

            query = "SELECT * FROM calendars"
            if enabled_only:
                query += " WHERE enabled = 1"
            query += " ORDER BY is_primary DESC, name ASC"

            cursor = await self._db.execute(query)
            rows = await cursor.fetchall()

            return [
                MonitoredCalendar(
                    id=row["id"],
                    calendar_id=row["calendar_id"],
                    name=row["name"],
                    description=row["description"] or "",
                    color=row["color"] or "",
                    is_primary=bool(row["is_primary"]),
                    auto_join=bool(row["auto_join"]),
                    bot_mode=row["bot_mode"] or "notes",
                    enabled=bool(row["enabled"]),
                    added_at=datetime.fromisoformat(row["added_at"]) if row["added_at"] else None,
                )
                for row in rows
            ]

    async def remove_calendar(self, calendar_id: str) -> bool:
        """Remove a calendar from monitoring."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return False

            cursor = await self._db.execute("DELETE FROM calendars WHERE calendar_id = ?", (calendar_id,))
            await self._db.commit()
            return cursor.rowcount > 0

    async def update_calendar(self, calendar_id: str, **updates) -> bool:
        """Update calendar settings."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return False

            # Build update query
            set_parts = []
            values = []
            for key, value in updates.items():
                if key in ("auto_join", "enabled", "is_primary"):
                    set_parts.append(f"{key} = ?")
                    values.append(1 if value else 0)
                elif key in ("name", "description", "color", "bot_mode"):
                    set_parts.append(f"{key} = ?")
                    values.append(value)

            if not set_parts:
                return False

            values.append(calendar_id)
            query = f"UPDATE calendars SET {', '.join(set_parts)} WHERE calendar_id = ?"

            cursor = await self._db.execute(query, values)
            await self._db.commit()
            return cursor.rowcount > 0

    # ==================== Meeting Operations ====================

    async def create_meeting(self, meeting: MeetingNote) -> int:
        """Create a new meeting record or return existing one.

        If a meeting with the same event_id and calendar_id already exists,
        returns the existing meeting's ID instead of failing.
        """
        import uuid

        async with self._lock:
            await self._connect_internal()
            if not self._db:
                raise RuntimeError("Database not connected")

            now = datetime.now().isoformat()

            # Generate unique event_id for manual joins (when no calendar event)
            event_id = meeting.event_id
            calendar_id = meeting.calendar_id
            if not event_id:
                # Use UUID for manual joins to avoid unique constraint issues
                event_id = f"manual_{uuid.uuid4().hex[:12]}"
            if not calendar_id:
                calendar_id = "manual"

            # Check if meeting already exists
            cursor = await self._db.execute(
                "SELECT id FROM meetings WHERE event_id = ? AND calendar_id = ?", (event_id, calendar_id)
            )
            existing = await cursor.fetchone()
            if existing:
                # Meeting already exists - update status and return existing ID
                await self._db.execute(
                    "UPDATE meetings SET status = ?, actual_start = ?, updated_at = ? WHERE id = ?",
                    ("in_progress", now, now, existing[0]),
                )
                await self._db.commit()
                logger.info(f"Meeting already exists (id={existing[0]}), reusing record")
                return existing[0]

            cursor = await self._db.execute(
                """
                INSERT INTO meetings
                (title, calendar_id, calendar_name, meet_url, event_id,
                 scheduled_start, scheduled_end, actual_start, actual_end,
                 organizer, attendees, description, summary, action_items, tags,
                 status, bot_mode, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    meeting.title,
                    calendar_id,
                    meeting.calendar_name,
                    meeting.meet_url,
                    event_id,
                    meeting.scheduled_start.isoformat() if meeting.scheduled_start else None,
                    meeting.scheduled_end.isoformat() if meeting.scheduled_end else None,
                    meeting.actual_start.isoformat() if meeting.actual_start else None,
                    meeting.actual_end.isoformat() if meeting.actual_end else None,
                    meeting.organizer,
                    json.dumps(meeting.attendees),
                    meeting.description,
                    meeting.summary,
                    json.dumps(meeting.action_items),
                    json.dumps(meeting.tags),
                    meeting.status,
                    meeting.bot_mode,
                    now,
                    now,
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def get_meeting(self, meeting_id: int, include_transcript: bool = False) -> Optional[MeetingNote]:
        """Get a meeting by ID."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return None

            cursor = await self._db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
            row = await cursor.fetchone()

            if not row:
                return None

            meeting = self._row_to_meeting(row)

            if include_transcript:
                meeting.transcript = await self._get_transcript_internal(meeting_id)

            return meeting

    async def get_meeting_by_event(self, event_id: str, calendar_id: str) -> Optional[MeetingNote]:
        """Get a meeting by Google Calendar event ID."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return None

            cursor = await self._db.execute(
                "SELECT * FROM meetings WHERE event_id = ? AND calendar_id = ?", (event_id, calendar_id)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return self._row_to_meeting(row)

    async def list_meetings(
        self,
        calendar_id: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
    ) -> list[MeetingNote]:
        """List meetings with optional filters."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return []

            conditions = []
            params = []

            if calendar_id:
                conditions.append("calendar_id = ?")
                params.append(calendar_id)

            if status:
                conditions.append("status = ?")
                params.append(status)

            if since:
                conditions.append("scheduled_start >= ?")
                params.append(since.isoformat())

            if until:
                conditions.append("scheduled_start <= ?")
                params.append(until.isoformat())

            query = "SELECT * FROM meetings"
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY scheduled_start DESC LIMIT ?"
            params.append(limit)

            cursor = await self._db.execute(query, params)
            rows = await cursor.fetchall()

            return [self._row_to_meeting(row) for row in rows]

    async def get_recent_meetings(self, limit: int = 20, status: str = "completed") -> list[dict]:
        """Get recent meetings as simple dicts with transcript counts.

        This is optimized for UI display - returns lightweight dicts instead of full MeetingNote objects.
        """
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return []

            # Query meetings with transcript counts
            query = """
                SELECT
                    m.id, m.title, m.meet_url, m.event_id, m.calendar_id,
                    m.scheduled_start, m.scheduled_end, m.actual_start, m.actual_end,
                    m.organizer, m.status, m.bot_mode,
                    (SELECT COUNT(*) FROM transcripts WHERE meeting_id = m.id) as transcript_count
                FROM meetings m
                WHERE m.status = ?
                ORDER BY m.actual_end DESC, m.actual_start DESC
                LIMIT ?
            """

            cursor = await self._db.execute(query, [status, limit])
            rows = await cursor.fetchall()

            return [
                {
                    "id": row[0],
                    "title": row[1],
                    "meet_url": row[2],
                    "event_id": row[3],
                    "calendar_id": row[4],
                    "scheduled_start": row[5],
                    "scheduled_end": row[6],
                    "actual_start": row[7],
                    "actual_end": row[8],
                    "organizer": row[9],
                    "status": row[10],
                    "bot_mode": row[11],
                    "transcript_count": row[12],
                }
                for row in rows
            ]

    async def update_meeting(self, meeting_id: int, **updates) -> bool:
        """Update meeting fields."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return False

            # Build update query
            set_parts = ["updated_at = ?"]
            values = [datetime.now().isoformat()]

            for key, value in updates.items():
                if key in (
                    "title",
                    "meet_url",
                    "organizer",
                    "description",
                    "summary",
                    "status",
                    "bot_mode",
                    "calendar_name",
                ):
                    set_parts.append(f"{key} = ?")
                    values.append(value)
                elif key in ("scheduled_start", "scheduled_end", "actual_start", "actual_end"):
                    set_parts.append(f"{key} = ?")
                    values.append(value.isoformat() if isinstance(value, datetime) else value)
                elif key in ("attendees", "action_items", "tags"):
                    set_parts.append(f"{key} = ?")
                    values.append(json.dumps(value) if isinstance(value, list) else value)

            values.append(meeting_id)
            query = f"UPDATE meetings SET {', '.join(set_parts)} WHERE id = ?"

            cursor = await self._db.execute(query, values)
            await self._db.commit()
            return cursor.rowcount > 0

    async def delete_meeting(self, meeting_id: int) -> bool:
        """Delete a meeting and its transcript."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return False

            # Delete transcript first (cascade should handle this, but be explicit)
            await self._db.execute("DELETE FROM transcripts WHERE meeting_id = ?", (meeting_id,))

            cursor = await self._db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            await self._db.commit()
            return cursor.rowcount > 0

    def _row_to_meeting(self, row: aiosqlite.Row) -> MeetingNote:
        """Convert a database row to MeetingNote."""
        return MeetingNote(
            id=row["id"],
            title=row["title"],
            calendar_id=row["calendar_id"] or "",
            calendar_name=row["calendar_name"] or "",
            meet_url=row["meet_url"] or "",
            event_id=row["event_id"] or "",
            scheduled_start=datetime.fromisoformat(row["scheduled_start"]) if row["scheduled_start"] else None,
            scheduled_end=datetime.fromisoformat(row["scheduled_end"]) if row["scheduled_end"] else None,
            actual_start=datetime.fromisoformat(row["actual_start"]) if row["actual_start"] else None,
            actual_end=datetime.fromisoformat(row["actual_end"]) if row["actual_end"] else None,
            organizer=row["organizer"] or "",
            attendees=json.loads(row["attendees"]) if row["attendees"] else [],
            description=row["description"] or "",
            summary=row["summary"] or "",
            action_items=json.loads(row["action_items"]) if row["action_items"] else [],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            status=row["status"] or "scheduled",
            bot_mode=row["bot_mode"] or "notes",
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )

    # ==================== Transcript Operations ====================

    async def add_transcript_entry(self, meeting_id: int, entry: TranscriptEntry) -> int:
        """Add a transcript entry to a meeting."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                raise RuntimeError("Database not connected")

            cursor = await self._db.execute(
                """
                INSERT INTO transcripts (meeting_id, speaker, text, timestamp)
                VALUES (?, ?, ?, ?)
            """,
                (
                    meeting_id,
                    entry.speaker,
                    entry.text,
                    entry.timestamp.isoformat(),
                ),
            )
            await self._db.commit()
            return cursor.lastrowid or 0

    async def add_transcript_entries(self, meeting_id: int, entries: list[TranscriptEntry]) -> int:
        """Add multiple transcript entries efficiently."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                raise RuntimeError("Database not connected")

            await self._db.executemany(
                """
                INSERT INTO transcripts (meeting_id, speaker, text, timestamp)
                VALUES (?, ?, ?, ?)
            """,
                [(meeting_id, e.speaker, e.text, e.timestamp.isoformat()) for e in entries],
            )
            await self._db.commit()
            return len(entries)

    async def get_transcript(self, meeting_id: int) -> list[TranscriptEntry]:
        """Get full transcript for a meeting."""
        async with self._lock:
            await self._connect_internal()
            return await self._get_transcript_internal(meeting_id)

    async def get_transcript_entries(self, meeting_id: int, limit: int = 50) -> list[TranscriptEntry]:
        """Get recent transcript entries for a meeting (with limit)."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return []

            cursor = await self._db.execute(
                """
                SELECT * FROM transcripts
                WHERE meeting_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """,
                (meeting_id, limit),
            )
            rows = await cursor.fetchall()

            # Return in chronological order (oldest first)
            entries = [
                TranscriptEntry(
                    id=row["id"],
                    meeting_id=row["meeting_id"],
                    speaker=row["speaker"],
                    text=row["text"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                )
                for row in rows
            ]
            entries.reverse()
            return entries

    async def _get_transcript_internal(self, meeting_id: int) -> list[TranscriptEntry]:
        """Get transcript (caller must hold lock)."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            """
            SELECT * FROM transcripts WHERE meeting_id = ? ORDER BY timestamp ASC
        """,
            (meeting_id,),
        )
        rows = await cursor.fetchall()

        return [
            TranscriptEntry(
                id=row["id"],
                meeting_id=row["meeting_id"],
                speaker=row["speaker"],
                text=row["text"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

    async def search_transcripts(
        self,
        query: str,
        meeting_id: Optional[int] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Full-text search across transcripts.

        Returns list of matches with meeting info.
        """
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return []

            if meeting_id:
                # Search within a specific meeting
                sql = """
                    SELECT t.*, m.title as meeting_title, m.scheduled_start
                    FROM transcripts_fts fts
                    JOIN transcripts t ON fts.rowid = t.id
                    JOIN meetings m ON t.meeting_id = m.id
                    WHERE transcripts_fts MATCH ? AND t.meeting_id = ?
                    ORDER BY rank
                    LIMIT ?
                """
                params = (query, meeting_id, limit)
            else:
                # Search across all meetings
                sql = """
                    SELECT t.*, m.title as meeting_title, m.scheduled_start
                    FROM transcripts_fts fts
                    JOIN transcripts t ON fts.rowid = t.id
                    JOIN meetings m ON t.meeting_id = m.id
                    WHERE transcripts_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """
                params = (query, limit)

            cursor = await self._db.execute(sql, params)
            rows = await cursor.fetchall()

            return [
                {
                    "meeting_id": row["meeting_id"],
                    "meeting_title": row["meeting_title"],
                    "meeting_date": row["scheduled_start"],
                    "speaker": row["speaker"],
                    "text": row["text"],
                    "timestamp": row["timestamp"],
                }
                for row in rows
            ]

    # ==================== Statistics ====================

    async def get_stats(self) -> dict:
        """Get database statistics."""
        async with self._lock:
            await self._connect_internal()
            if not self._db:
                return {}

            stats = {}

            # Calendar count
            cursor = await self._db.execute("SELECT COUNT(*) FROM calendars WHERE enabled = 1")
            row = await cursor.fetchone()
            stats["calendars"] = row[0] if row else 0

            # Meeting counts by status
            cursor = await self._db.execute(
                """
                SELECT status, COUNT(*) FROM meetings GROUP BY status
            """
            )
            rows = await cursor.fetchall()
            stats["meetings"] = {row[0]: row[1] for row in rows}
            stats["meetings"]["total"] = sum(stats["meetings"].values())

            # Transcript count
            cursor = await self._db.execute("SELECT COUNT(*) FROM transcripts")
            row = await cursor.fetchone()
            stats["transcript_entries"] = row[0] if row else 0

            # Database size
            stats["db_size_kb"] = round(self.db_path.stat().st_size / 1024, 2) if self.db_path.exists() else 0

            return stats


# Global instance
_db: Optional[MeetingNotesDB] = None


def get_notes_db() -> MeetingNotesDB:
    """Get the global database instance."""
    global _db
    if _db is None:
        _db = MeetingNotesDB()
    return _db


async def init_notes_db() -> MeetingNotesDB:
    """Initialize and return the database."""
    db = get_notes_db()
    await db.connect()
    return db
