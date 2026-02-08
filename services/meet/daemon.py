#!/usr/bin/env python3
"""
Google Meet Bot Daemon

A standalone service that monitors calendars and auto-joins meetings.
Designed to run as a systemd user service.

Features:
- Calendar polling for upcoming meetings
- Automatic meeting join with configurable buffer
- Note-taking during meetings
- D-Bus IPC for external control
- Graceful shutdown handling
- Systemd watchdog support

Usage:
    python -m services.meet                # Run daemon
    python -m services.meet --status       # Check if running
    python -m services.meet --stop         # Stop running daemon
    python -m services.meet --list         # List upcoming meetings
    python -m services.meet --dbus         # Enable D-Bus IPC

Systemd:
    systemctl --user start bot-meet
    systemctl --user status bot-meet
    systemctl --user stop bot-meet

D-Bus:
    Service: com.aiworkflow.BotMeet
    Path: /com/aiworkflow/BotMeet
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

# Import centralized paths - meet daemon owns its own state file
from server.paths import MEET_STATE_FILE
from services.base.daemon import BaseDaemon
from services.base.dbus import DaemonDBusBase
from services.base.sleep_wake import SleepWakeAwareDaemon

logger = logging.getLogger(__name__)

# Suppress noisy Google API cache warning
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)


class MeetDaemon(SleepWakeAwareDaemon, DaemonDBusBase, BaseDaemon):
    """Main Google Meet bot daemon with D-Bus support."""

    # BaseDaemon configuration
    name = "meet"
    description = "Google Meet Bot Daemon"

    # D-Bus configuration
    service_name = "com.aiworkflow.BotMeet"
    object_path = "/com/aiworkflow/BotMeet"
    interface_name = "com.aiworkflow.BotMeet"

    def __init__(self, verbose: bool = False, enable_dbus: bool = False):
        BaseDaemon.__init__(self, verbose=verbose, enable_dbus=enable_dbus)
        DaemonDBusBase.__init__(self)
        SleepWakeAwareDaemon.__init__(self)
        self._scheduler = None
        self._meetings_joined = 0
        self._meetings_completed = 0
        self._state_writer_task = None

        # Register custom D-Bus method handlers
        self.register_handler("list_meetings", self._handle_list_meetings)
        self.register_handler("skip_meeting", self._handle_skip_meeting)
        self.register_handler("approve_meeting", self._handle_approve_meeting)
        self.register_handler("unapprove_meeting", self._handle_unapprove_meeting)
        self.register_handler("force_join", self._handle_force_join)
        self.register_handler("join_meeting", self._handle_join_meeting)
        self.register_handler("leave_meeting", self._handle_leave_meeting)
        self.register_handler("list_calendars", self._handle_list_calendars)
        self.register_handler("set_meeting_mode", self._handle_set_meeting_mode)
        self.register_handler("get_captions", self._handle_get_captions)
        self.register_handler("get_participants", self._handle_get_participants)
        self.register_handler("get_meeting_history", self._handle_get_meeting_history)
        self.register_handler("mute_audio", self._handle_mute_audio)
        self.register_handler("unmute_audio", self._handle_unmute_audio)
        self.register_handler("get_audio_state", self._handle_get_audio_state)
        self.register_handler("write_state", self._handle_write_state)
        self.register_handler("get_state", self._handle_get_state)  # Full state for UI

    # ==================== D-Bus Interface Methods ====================

    async def get_service_stats(self) -> dict:
        """Return meet-specific statistics."""
        stats = {
            "meetings_joined": self._meetings_joined,
            "meetings_completed": self._meetings_completed,
        }

        if self._scheduler:
            scheduler_status = await self._scheduler.get_status()
            stats["current_meeting"] = scheduler_status.get("current_meeting")
            stats["upcoming_count"] = scheduler_status.get("upcoming_count", 0)
            stats["completed_today"] = scheduler_status.get("completed_today", 0)
            stats["last_poll"] = scheduler_status.get("last_poll")

        return stats

    async def get_service_status(self) -> dict:
        """Return detailed service status."""
        base = self.get_base_stats()
        service = await self.get_service_stats()

        # Add upcoming meetings and current meetings
        if self._scheduler:
            scheduler_status = await self._scheduler.get_status()
            service["upcoming_meetings"] = scheduler_status.get("upcoming_meetings", [])
            service["current_meetings"] = scheduler_status.get("current_meetings", [])
            service["errors"] = scheduler_status.get("errors", [])

        return {**base, **service}

    async def health_check(self) -> dict:
        """
        Perform a comprehensive health check on the meet daemon.

        Checks:
        - Service is running
        - Scheduler is initialized
        - Calendar API is accessible
        - No excessive errors
        """
        import time as time_mod

        self._last_health_check = time_mod.time()

        checks = {
            "running": self.is_running,
            "scheduler_initialized": self._scheduler is not None,
        }

        # Check scheduler health
        if self._scheduler:
            try:
                scheduler_status = await self._scheduler.get_status()
                checks["scheduler_polling"] = (
                    scheduler_status.get("last_poll") is not None
                )

                # Check if we've had recent polls (within last 5 minutes)
                last_poll = scheduler_status.get("last_poll")
                if last_poll:
                    try:
                        from datetime import datetime

                        poll_time = datetime.fromisoformat(
                            last_poll.replace("Z", "+00:00")
                        )
                        poll_age = (
                            datetime.now(poll_time.tzinfo) - poll_time
                        ).total_seconds()
                        checks["recent_poll"] = poll_age < 300  # Within 5 minutes
                    except Exception as e:
                        logger.debug(
                            f"Suppressed error in health_check (poll time parse): {e}"
                        )
                        checks["recent_poll"] = False
                else:
                    checks["recent_poll"] = False

                # Check for excessive errors
                errors = scheduler_status.get("errors", [])
                checks["no_excessive_errors"] = len(errors) < 10
            except Exception as e:
                logger.warning(f"Health check scheduler status failed: {e}")
                checks["scheduler_polling"] = False
                checks["recent_poll"] = False
                checks["no_excessive_errors"] = True
        else:
            checks["scheduler_polling"] = False
            checks["recent_poll"] = False
            checks["no_excessive_errors"] = True

        # Overall health - only check core requirements
        # Note: We don't require uptime_ok or recent_poll for health
        # Those are informational, not critical for watchdog
        core_checks = ["running", "scheduler_initialized"]
        healthy = all(checks.get(k, False) for k in core_checks)

        # Build message
        if healthy:
            message = "Meet daemon is healthy"
        else:
            failed = [k for k, v in checks.items() if not v]
            message = f"Unhealthy: {', '.join(failed)}"

        return {
            "healthy": healthy,
            "checks": checks,
            "message": message,
            "timestamp": self._last_health_check,
            "meetings_joined": self._meetings_joined,
            "meetings_completed": self._meetings_completed,
        }

    async def _handle_list_meetings(self) -> dict:
        """Handle D-Bus request to list upcoming meetings."""
        if not self._scheduler:
            return {"meetings": []}

        status = await self._scheduler.get_status()
        return {"meetings": status.get("upcoming_meetings", [])}

    async def _handle_skip_meeting(self, event_id: str) -> dict:
        """Handle D-Bus request to skip a meeting."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.skip_meeting(event_id)
        return {"success": success, "event_id": event_id}

    async def _handle_approve_meeting(self, event_id: str, mode: str = "notes") -> dict:
        """Handle D-Bus request to pre-approve a meeting for auto-join."""
        logger.info(
            f"D-Bus: approve_meeting request - event_id={event_id}, mode={mode}"
        )
        if not self._scheduler:
            logger.error("D-Bus: approve_meeting failed - scheduler not running")
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.approve_meeting(event_id, mode)
        logger.info(f"D-Bus: approve_meeting result - success={success}")
        return {"success": success, "event_id": event_id, "mode": mode}

    async def _handle_unapprove_meeting(self, event_id: str) -> dict:
        """Handle D-Bus request to un-approve a meeting (change to skipped)."""
        logger.info(f"D-Bus: unapprove_meeting request - event_id={event_id}")
        if not self._scheduler:
            logger.error("D-Bus: unapprove_meeting failed - scheduler not running")
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.unapprove_meeting(event_id)
        logger.info(f"D-Bus: unapprove_meeting result - success={success}")
        return {"success": success, "event_id": event_id}

    async def _handle_set_meeting_mode(self, event_id: str, mode: str) -> dict:
        """Handle D-Bus request to set meeting mode (notes or interactive)."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.set_meeting_mode(event_id, mode)
        return {"success": success, "event_id": event_id, "mode": mode}

    async def _handle_force_join(self, event_id: str) -> dict:
        """Handle D-Bus request to force join a meeting."""
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not running"}

        success = await self._scheduler.force_join(event_id)
        return {"success": success, "event_id": event_id}

    async def _handle_join_meeting(
        self,
        meet_url: str,
        title: str = "Manual Join",
        mode: str = "notes",
        video_enabled: bool = False,
    ) -> dict:
        """Handle D-Bus request to join a meeting by URL (quick join).

        This returns immediately with status="joining" and spawns the actual
        join operation in the background. The UI should poll GetStatus to
        see when the meeting appears in currentMeetings.

        Args:
            meet_url: Google Meet URL
            title: Meeting title for display
            mode: "notes" or "interactive"
            video_enabled: If True, show full AI video overlay. If False, show black screen.
        """
        logger.info(
            f"D-Bus: join_meeting request - URL: {meet_url}, title: {title}, "
            f"mode: {mode}, video_enabled: {video_enabled}"
        )
        if not self._scheduler:
            logger.error("D-Bus: join_meeting failed - scheduler not running")
            return {"success": False, "error": "Scheduler not running"}

        # Spawn the join operation in the background so we can return immediately
        async def _do_join():
            try:
                success = await self._scheduler.join_meeting_url(
                    meet_url, title, mode, video_enabled=video_enabled
                )
                logger.info(f"D-Bus: join_meeting completed - success: {success}")
            except Exception as e:
                logger.error(f"D-Bus: join_meeting failed - {e}")

        # Start the background task
        asyncio.create_task(_do_join())

        # Return immediately - the UI should poll GetStatus to see the meeting
        return {
            "success": True,
            "status": "joining",
            "message": "Join operation started. Check status for progress.",
            "meet_url": meet_url,
            "title": title,
            "mode": mode,
            "video_enabled": video_enabled,
        }

    async def _handle_leave_meeting(self, session_id: str = "") -> dict:
        """Handle D-Bus request to leave the current meeting."""
        logger.info(f"D-Bus: leave_meeting request (session_id={session_id})")

        if not self._scheduler or not self._scheduler.notes_bot:
            return {"success": False, "error": "No active meeting"}

        try:
            result = await self._scheduler.notes_bot.leave_meeting()
            logger.info("D-Bus: leave_meeting completed - success: True")
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"D-Bus: leave_meeting failed - {e}")
            return {"success": False, "error": str(e)}

    async def _handle_list_calendars(self) -> dict:
        """Handle D-Bus request to list monitored calendars."""
        if not self._scheduler:
            return {"calendars": []}

        calendars = await self._scheduler.list_calendars()
        return {
            "calendars": [
                {
                    "calendar_id": c.calendar_id,
                    "name": c.name,
                    "enabled": c.enabled,
                    "auto_join": c.auto_join,
                    "bot_mode": c.bot_mode,
                }
                for c in calendars
            ]
        }

    async def _handle_get_captions(self, limit: int = 50) -> dict:
        """Handle D-Bus request to get recent captions from active meeting."""
        if not self._scheduler or not self._scheduler.notes_bot:
            return {"captions": [], "count": 0}

        bot = self._scheduler.notes_bot
        captions = []

        # Get captions from the transcript buffer (not yet flushed to DB)
        if bot.state and bot.state.transcript_buffer:
            for entry in bot.state.transcript_buffer[-limit:]:
                captions.append(
                    {
                        "speaker": entry.speaker,
                        "text": entry.text,
                        "timestamp": (
                            entry.timestamp.isoformat() if entry.timestamp else None
                        ),
                    }
                )

        # Also get recent captions from DB if we have a meeting ID
        if bot.db and bot.state and bot.state.meeting_id:
            try:
                db_entries = await bot.db.get_transcript_entries(
                    bot.state.meeting_id, limit=limit
                )
                # Prepend DB entries (older) before buffer entries (newer)
                db_captions = [
                    {
                        "speaker": e.speaker,
                        "text": e.text,
                        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                    }
                    for e in db_entries
                ]
                # Combine: DB entries first, then buffer (avoid duplicates by timestamp)
                seen_timestamps = {c["timestamp"] for c in captions}
                for c in db_captions:
                    if c["timestamp"] not in seen_timestamps:
                        captions.insert(0, c)
            except Exception as e:
                logger.warning(f"Failed to get DB captions: {e}")

        # Sort by timestamp and limit
        captions.sort(key=lambda x: x.get("timestamp") or "")
        captions = captions[-limit:]

        return {
            "captions": captions,
            "count": len(captions),
            "meeting_id": bot.state.meeting_id if bot.state else None,
            "meeting_title": bot.state.title if bot.state else None,
            "total_captured": bot.state.captions_captured if bot.state else 0,
        }

    async def _handle_get_participants(self) -> dict:
        """Handle D-Bus request to get current meeting participants."""
        if not self._scheduler or not self._scheduler.notes_bot:
            return {"participants": [], "count": 0}

        bot = self._scheduler.notes_bot
        participants = []

        # Get participants from browser controller if available
        if bot._controller and bot._controller.state:
            participants = bot._controller.state.participants or []

        return {
            "participants": participants,
            "count": len(participants),
        }

    async def _handle_get_meeting_history(self, limit: int = 20) -> dict:
        """Handle D-Bus request to get meeting history from database."""
        if not self._scheduler or not self._scheduler.notes_bot:
            return {"meetings": [], "count": 0}

        bot = self._scheduler.notes_bot
        meetings = []

        try:
            if bot.db:
                # Query completed meetings from database
                rows = await bot.db.get_recent_meetings(limit=limit)
                for row in rows:
                    meetings.append(
                        {
                            "id": row.get("id"),
                            "title": row.get("title", "Untitled"),
                            "date": row.get(
                                "actual_start", row.get("scheduled_start", "")
                            ),
                            "duration": self._calculate_duration(
                                row.get("actual_start"), row.get("actual_end")
                            ),
                            "transcriptCount": row.get("transcript_count", 0),
                            "status": row.get("status", "completed"),
                            "botMode": row.get("bot_mode", "notes"),
                            "meetUrl": row.get("meet_url", ""),
                            "organizer": row.get("organizer", ""),
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to get meeting history: {e}")

        return {
            "meetings": meetings,
            "count": len(meetings),
        }

    def _calculate_duration(self, start: str, end: str) -> float:
        """Calculate duration in minutes between two ISO timestamps."""
        if not start or not end:
            return 0.0
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            return (end_dt - start_dt).total_seconds() / 60.0
        except Exception:
            return 0.0

    async def _handle_mute_audio(self, session_id: str = "") -> dict:
        """Handle D-Bus request to mute meeting audio (route to null sink)."""
        logger.info(f"D-Bus: mute_audio request (session_id={session_id})")

        if not self._scheduler or not self._scheduler.notes_bot:
            return {"success": False, "error": "No active meeting"}

        bot = self._scheduler.notes_bot
        if not bot._controller:
            return {"success": False, "error": "No browser controller"}

        try:
            success = bot._controller.mute_audio()
            return {"success": success, "muted": success}
        except Exception as e:
            logger.error(f"Failed to mute audio: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_unmute_audio(self, session_id: str = "") -> dict:
        """Handle D-Bus request to unmute meeting audio (route to default output)."""
        logger.info(f"D-Bus: unmute_audio request (session_id={session_id})")

        if not self._scheduler or not self._scheduler.notes_bot:
            return {"success": False, "error": "No active meeting"}

        bot = self._scheduler.notes_bot
        if not bot._controller:
            return {"success": False, "error": "No browser controller"}

        try:
            success = bot._controller.unmute_audio()
            return {"success": success, "muted": not success}
        except Exception as e:
            logger.error(f"Failed to unmute audio: {e}")
            return {"success": False, "error": str(e)}

    async def _handle_get_audio_state(self, session_id: str = "") -> dict:
        """Handle D-Bus request to get current audio mute state."""
        if not self._scheduler or not self._scheduler.notes_bot:
            return {"muted": True, "has_meeting": False}

        bot = self._scheduler.notes_bot
        if not bot._controller:
            return {"muted": True, "has_meeting": False}

        try:
            is_muted = bot._controller.is_audio_muted()
            return {"muted": is_muted, "has_meeting": True}
        except Exception as e:
            logger.debug(f"Failed to get audio state: {e}")
            return {"muted": True, "has_meeting": True, "error": str(e)}

    async def _handle_write_state(self) -> dict:
        """Write state to file immediately (for UI refresh requests)."""
        try:
            await self._write_state()
            return {"success": True, "file": str(MEET_STATE_FILE)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _build_state_dict(self, status: dict, calendars: list) -> dict:
        """Build the meet state dictionary from scheduler status and calendars.

        This is the single source of truth for meet state structure,
        used by both _handle_get_state() and _write_state().

        Args:
            status: Result from scheduler.get_status()
            calendars: Result from scheduler.list_calendars()

        Returns:
            Meet state dictionary with upcoming/current meetings, calendars, and countdown.
        """
        meet_state = {
            "schedulerRunning": self.is_running,
            "upcomingMeetings": [
                {
                    "id": m.get("event_id", ""),
                    "title": m.get("title", "Untitled"),
                    "url": m.get("meet_url", ""),
                    "startTime": m.get("start", ""),
                    "endTime": m.get("end", ""),
                    "organizer": m.get("organizer", ""),
                    "status": m.get("status", "scheduled"),
                    "botMode": m.get("bot_mode", "notes"),
                    "calendarName": m.get("calendar_name", ""),
                }
                for m in status.get("upcoming_meetings", [])
            ],
            "currentMeetings": [
                {
                    "id": m.get("event_id", ""),
                    "sessionId": m.get("event_id", ""),
                    "title": m.get("title", "Untitled"),
                    "url": m.get("meet_url", ""),
                    "startTime": m.get("start", ""),
                    "endTime": m.get("end", ""),
                    "organizer": m.get("organizer", ""),
                    "status": "joined",
                    "botMode": m.get("bot_mode", "notes"),
                    "screenshotPath": m.get("screenshot_path"),
                    "screenshotUpdated": m.get("screenshot_updated"),
                }
                for m in status.get("current_meetings", [])
            ],
            "monitoredCalendars": [
                {"id": c.calendar_id, "name": c.name, "enabled": c.enabled}
                for c in calendars
            ],
            "lastPoll": status.get("last_poll"),
            "updated_at": datetime.now().isoformat(),
        }

        # Calculate countdown to next meeting
        upcoming = meet_state["upcomingMeetings"]
        if upcoming:
            next_meeting = None
            for m in upcoming:
                if m.get("status") in ("scheduled", "approved", "joining"):
                    next_meeting = m
                    break

            if next_meeting:
                meet_state["nextMeeting"] = next_meeting
                try:
                    start_str = next_meeting.get("startTime", "")
                    if start_str:
                        start_time = datetime.fromisoformat(
                            start_str.replace("Z", "+00:00")
                        )
                        now = (
                            datetime.now(start_time.tzinfo)
                            if start_time.tzinfo
                            else datetime.now()
                        )
                        delta = start_time - now
                        total_seconds = int(delta.total_seconds())
                        meet_state["countdownSeconds"] = max(0, total_seconds)

                        if total_seconds <= 0:
                            meet_state["countdown"] = "Starting now"
                        elif total_seconds < 60:
                            meet_state["countdown"] = f"{total_seconds}s"
                        elif total_seconds < 3600:
                            meet_state["countdown"] = f"{total_seconds // 60}m"
                        elif total_seconds < 86400:
                            hours = total_seconds // 3600
                            minutes = (total_seconds % 3600) // 60
                            meet_state["countdown"] = f"{hours}h {minutes}m"
                        else:
                            days = total_seconds // 86400
                            hours = (total_seconds % 86400) // 3600
                            meet_state["countdown"] = f"{days}d {hours}h"
                except Exception as e:
                    logger.debug(
                        f"Suppressed error in _get_meet_state (countdown): {e}"
                    )

        return meet_state

    async def _handle_get_state(self, **kwargs) -> dict:
        """Get full meet state for UI.

        Returns the complete meeting state including upcoming meetings,
        current meetings, calendars, and status. This is the primary
        method for UI to read meet state via D-Bus.
        """
        if not self._scheduler:
            return {"success": False, "error": "Scheduler not initialized"}

        try:
            status = await self._scheduler.get_status()
            calendars = await self._scheduler.list_calendars()
            meet_state = await self._build_state_dict(status, calendars)

            return {"success": True, "state": meet_state}

        except Exception as e:
            logger.error(f"Failed to get meet state: {e}")
            return {"success": False, "error": str(e)}

    # ==================== Sleep/Wake Handling ====================

    async def on_system_wake(self):
        """Handle system wake from sleep (SleepWakeAwareDaemon interface).

        This refreshes all state to ensure the daemon is responsive after sleep.
        """
        print("\n🌅 System wake detected - refreshing...")

        try:
            # 1. Re-poll calendars to get fresh meeting data
            if self._scheduler:
                logger.info("Re-polling calendars after wake...")
                await self._scheduler._poll_calendars()

                status = await self._scheduler.get_status()
                logger.info(
                    f"After wake: {status.get('upcoming_count', 0)} upcoming meetings"
                )
                print(
                    f"   📅 Refreshed: {status.get('upcoming_count', 0)} upcoming meetings"
                )

            # 2. Check if we were in a meeting that may have ended during sleep
            if self._scheduler and self._scheduler.notes_bot:
                bot = self._scheduler.notes_bot
                if bot._controller and bot._controller.is_browser_closed():
                    logger.info("Browser was closed during sleep, cleaning up...")
                    await bot._cleanup_stale_meeting()
                    print("   🧹 Cleaned up stale meeting state")

            print("   ✅ Wake handling complete\n")

        except Exception as e:
            logger.error(f"Error handling system wake: {e}")
            print(f"   ⚠️  Wake handling error: {e}\n")

    # ==================== Daemon Lifecycle ====================

    # ==================== Lifecycle ====================

    async def startup(self):
        """Initialize daemon resources."""
        await super().startup()

        from tool_modules.aa_meet_bot.src.meeting_scheduler import init_scheduler

        print("=" * 60)
        print("🎥 Google Meet Bot Daemon")
        print("=" * 60)

        # Start D-Bus if enabled
        if self.enable_dbus:
            if await self.start_dbus():
                print(f"✅ D-Bus IPC enabled ({self.service_name})")
            else:
                print("⚠️  D-Bus not available")

        # Initialize scheduler
        try:
            self._scheduler = await init_scheduler()
            print("✅ Meeting scheduler initialized")
        except Exception as e:
            print(f"❌ Failed to initialize scheduler: {e}")
            logger.error(f"Initialization error: {e}")
            raise

        # List monitored calendars
        calendars = await self._scheduler.list_calendars()
        print(f"   Monitored calendars: {len(calendars)}")
        for cal in calendars:
            status = "✅" if cal.enabled else "❌"
            print(f"      {status} {cal.name} ({cal.calendar_id})")

        if not calendars:
            print()
            print("⚠️  No calendars configured!")
            print("   Add calendars using the meet_bot tools:")
            print("   meet_add_calendar(calendar_id='your@email.com')")
            print()

        print()
        print("Starting scheduler...")

        # Start the scheduler (does initial poll before starting background loop)
        await self._scheduler.start()
        self.is_running = True

        print("✅ Scheduler started")
        print()

        # Show status (meetings are already loaded from initial poll)
        status = await self._scheduler.get_status()
        print(f"📅 Upcoming meetings: {status['upcoming_count']}")
        for meeting in status.get("upcoming_meetings", [])[:5]:
            print(f"   - {meeting['title']} at {meeting['start']}")

        # Start sleep/wake monitor (from SleepWakeAwareDaemon mixin)
        await self.start_sleep_monitor()
        print("✅ Sleep/wake monitor started")

        # Start state writer task (writes meet_state.json periodically)
        self._state_writer_task = asyncio.create_task(self._state_writer_loop())
        print("✅ State writer started")

        logger.info("Meet daemon ready")

        print()
        print("-" * 60)
        print("Daemon running. Press Ctrl+C to stop.")
        print("Logs: journalctl --user -u bot-meet -f")
        if self.enable_dbus:
            print(f"D-Bus: {self.service_name}")
        print("-" * 60)

    async def run_daemon(self):
        """Main daemon loop - wait for shutdown."""
        await self._shutdown_event.wait()

    async def _state_writer_loop(self):
        """Periodically write meet state to meet_state.json.

        Each service owns its own state file. The VS Code extension reads
        all state files on refresh. No shared file = no race conditions.
        """
        while not self._shutdown_event.is_set():
            try:
                await self._write_state()
                await asyncio.sleep(10)  # Write every 10 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"State writer error: {e}")
                await asyncio.sleep(10)

    async def _write_state(self):
        """Write current meet state to meet_state.json."""
        import json
        import tempfile

        if not self._scheduler:
            return

        try:
            status = await self._scheduler.get_status()
            calendars = await self._scheduler.list_calendars()
            meet_state = await self._build_state_dict(status, calendars)

            # Write atomically
            MEET_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temp_fd, temp_path = tempfile.mkstemp(
                suffix=".tmp", prefix="meet_state_", dir=MEET_STATE_FILE.parent
            )
            try:
                with os.fdopen(temp_fd, "w") as f:
                    json.dump(meet_state, f, indent=2, default=str)
                Path(temp_path).replace(MEET_STATE_FILE)
            except Exception:
                try:
                    Path(temp_path).unlink()
                except OSError:
                    pass
                raise

        except Exception as e:
            logger.debug(f"Failed to write meet state: {e}")

    async def shutdown(self):
        """Clean up daemon resources."""
        logger.info("Meet daemon shutting down...")

        print()
        print("Stopping daemon...")

        # Stop state writer task
        if self._state_writer_task and not self._state_writer_task.done():
            self._state_writer_task.cancel()
            try:
                await self._state_writer_task
            except asyncio.CancelledError:
                pass

        # Stop sleep monitor (from SleepWakeAwareDaemon mixin)
        try:
            await asyncio.wait_for(self.stop_sleep_monitor(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Sleep monitor stop timed out")

        print("Stopping scheduler...")

        if self._scheduler:
            try:
                # Give scheduler 30 seconds to stop gracefully
                await asyncio.wait_for(self._scheduler.stop(), timeout=30.0)
            except asyncio.TimeoutError:
                logger.warning("Scheduler stop timed out, forcing shutdown...")
                print("⚠️  Scheduler stop timed out")

        # Stop D-Bus
        if self.enable_dbus:
            try:
                await asyncio.wait_for(self.stop_dbus(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("D-Bus stop timed out")

        self.is_running = False
        await super().shutdown()
        print("✅ Meet Bot Daemon stopped")


async def list_meetings():
    """List upcoming meetings without starting the daemon."""
    from tool_modules.aa_meet_bot.src.meeting_scheduler import init_scheduler

    print("📅 Upcoming Meetings")
    print("=" * 60)

    try:
        scheduler = await init_scheduler()

        # Trigger a poll
        await scheduler._poll_calendars()

        status = await scheduler.get_status()

        if not status.get("upcoming_meetings"):
            print("No upcoming meetings with Google Meet links found.")
            return

        for meeting in status["upcoming_meetings"]:
            status_icon = {
                "scheduled": "📅",
                "joining": "🔄",
                "active": "🎥",
                "completed": "✅",
                "skipped": "⏭️",
            }.get(meeting["status"], "❓")

            print(f"{status_icon} {meeting['title']}")
            print(f"   Start: {meeting['start']}")
            print(f"   End: {meeting['end']}")
            print(f"   Status: {meeting['status']}")
            print(f"   Mode: {meeting['bot_mode']}")
            print()

    except Exception as e:
        print(f"❌ Error: {e}")
        logger.error(f"Failed to list meetings: {e}")


if __name__ == "__main__":
    MeetDaemon.main()
