"""Meeting leave, close, and stale-session cleanup for NotesBot."""

import asyncio
import logging
from datetime import datetime

from tool_modules.aa_meet_bot.src.audio_capture import PulseAudioCapture
from tool_modules.aa_meet_bot.src.dynamic_fields import DynamicFields
from tool_modules.aa_meet_bot.src.notes_state import NotesBotState
from tool_modules.aa_workflow.src.notification_emitter import notify_meeting_left

logger = logging.getLogger(__name__)


class NotesLifecycleMixin(DynamicFields):  # pylint: disable=too-few-public-methods
    """Private cleanup paths for NotesBot.

    ``too-few-public-methods`` is disabled because leave_meeting and close are
    the public API and the rest of this mixin is cleanup helpers. leave_meeting
    and close are public; this disable is unnecessary if those two count.
    """

    async def _finish_stale_cleanup(self, cleanup_errors) -> None:
        """Continue a cleanup sequence."""
        # 6. Update meeting record as ended
        if self.db and self.state.meeting_id:
            try:
                await self.db.update_meeting(
                    self.state.meeting_id,
                    status="completed",
                    actual_end=datetime.now().astimezone(),
                )
                logger.info("CLEANUP: Meeting %s marked as completed", self.state.meeting_id)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("CLEANUP: Failed to update meeting record: %s", e)

        # 7. Close the browser controller - this cleans up per-instance audio devices
        # restore_browser_audio=True because the meeting died unexpectedly
        if self._controller:
            logger.info("CLEANUP: Closing browser controller...")
            try:
                await asyncio.wait_for(self._controller.close(restore_browser_audio=True), timeout=10.0)
                logger.info("CLEANUP: Browser controller closed")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout closing controller, force killing...")
                try:
                    await self._controller.force_kill()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("CLEANUP: Error closing controller: %s", e)
                cleanup_errors.append(f"Controller close error: {e}")
            finally:
                self.__dict__["_controller"] = None

        # 8. FINAL: Clean up ANY remaining orphaned devices system-wide
        # This is the safety net that catches anything we missed
        cleanup_result = await self._run_orphan_cleanup("CLEANUP")
        if cleanup_result.get("errors"):
            cleanup_errors.extend(cleanup_result["errors"])

        # 9. Reset state
        self.state.status = "idle"
        self.state.meeting_id = None
        self.state.meet_url = ""
        self.state.title = ""
        self.state.caption_id_to_index.clear()
        self.state.transcript_buffer.clear()

        # Log summary
        logger.info("=" * 60)
        if cleanup_errors:
            logger.warning("CLEANUP: Completed with %s errors:", len(cleanup_errors))
            for err in cleanup_errors:
                logger.warning("  - %s", err)
        else:
            logger.info("CLEANUP: Completed successfully - all resources released")
        logger.info("CLEANUP: Ready for new meeting")
        logger.info("=" * 60)

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-branches,too-many-statements
    async def _cleanup_stale_meeting(
        self,
    ) -> None:
        """Clean up state from a meeting where the browser was closed unexpectedly.

        This is called when:
        - Browser window is closed by user
        - Browser crashes
        - Meeting ends unexpectedly
        - Health monitor detects browser is unresponsive

        CRITICAL: This must clean up ALL resources to prevent orphaned:
        - PulseAudio modules (sinks/sources)
        - Named pipes
        - parec processes
        - Video devices
        - Background tasks
        """
        logger.info("=" * 60)
        logger.info("CLEANUP: Starting stale meeting cleanup...")
        logger.info("=" * 60)

        # Track what we're cleaning up
        cleanup_errors = []

        # 1. FIRST: Stop NPU STT pipeline - this kills the parec process
        # This MUST happen before closing the controller to ensure the parec
        # process is killed while we still have the PID reference
        if self._npu_stt_pipeline:
            logger.info("CLEANUP: Stopping NPU STT pipeline...")
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
                logger.info("CLEANUP: NPU STT pipeline stopped successfully")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout stopping NPU STT pipeline")
                cleanup_errors.append("NPU STT timeout")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("CLEANUP: Error stopping NPU STT: %s", e)
                cleanup_errors.append(f"NPU STT error: {e}")
            finally:
                self.__dict__["_npu_stt_pipeline"] = None

        # 2. Kill any remaining audio capture processes from this session
        try:
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info("CLEANUP: Force-killed %s orphaned audio capture processes", killed)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("CLEANUP: Error killing audio captures: %s", e)
            cleanup_errors.append(f"Audio capture kill error: {e}")

        # 3. Cancel all background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
            ("wake_word_check_task", getattr(self, "_wake_word_check_task", None)),
            ("participant_poll_task", getattr(self, "_participant_poll_task", None)),
        ]

        for _task_name, task in tasks_to_cancel:
            if task and not task.done():
                logger.info("CLEANUP: Cancelling %s...", _task_name)
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception as e:  # pylint: disable=broad-exception-caught
                    cleanup_errors.append(f"{_task_name} cancel error: {e}")

        # Clear task references
        self.__dict__["_flush_task"] = None
        self.__dict__["_screenshot_task"] = None
        self.__dict__["_browser_monitor_task"] = None
        if hasattr(self, "_wake_word_check_task"):
            self.__dict__["_wake_word_check_task"] = None
        if hasattr(self, "_participant_poll_task"):
            self.__dict__["_participant_poll_task"] = None

        # 4. Stop video daemon integration
        if self._video_daemon_active:
            logger.info("CLEANUP: Stopping video daemon integration...")
            try:
                await asyncio.wait_for(self._stop_video_integration(), timeout=5.0)
                logger.info("CLEANUP: Video daemon stopped")
            except asyncio.TimeoutError:
                logger.warning("CLEANUP: Timeout stopping video daemon")
                cleanup_errors.append("Video daemon timeout")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("CLEANUP: Error stopping video integration: %s", e)
                cleanup_errors.append(f"Video daemon error: {e}")

        # 5. Flush any remaining transcript buffer
        try:
            await self._flush_buffer()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("CLEANUP: Failed to flush buffer: %s", e)

        await self._finish_stale_cleanup(cleanup_errors)

    async def _finish_leave(self) -> dict:
        """Continue a cleanup sequence."""
        # 6. Leave the meeting (browser automation)
        if self._controller:
            logger.info("LEAVE: Leaving meeting via browser...")
            try:
                await asyncio.wait_for(self._controller.leave_meeting(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout leaving meeting")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("LEAVE: Error leaving meeting: %s", e)

        # 7. Build result before cleanup
        result = {
            "meeting_id": self.state.meeting_id,
            "title": self.state.title,
            "duration_minutes": 0,
            "captions_captured": self.state.captions_captured,
        }

        if self.db and self.state.meeting_id:
            now = datetime.now().astimezone()

            # Calculate duration
            if self.state.joined_at:
                duration = now - self.state.joined_at
                result["duration_minutes"] = round(duration.total_seconds() / 60, 1)

            # Update meeting status
            try:
                await self.db.update_meeting(
                    self.state.meeting_id,
                    status="completed",
                    actual_end=now,
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("LEAVE: Failed to update meeting record: %s", e)

        # 8. Close browser controller (this cleans up per-instance devices)
        # restore_browser_audio=False for normal exit (user's Chrome wasn't affected)
        if self._controller:
            logger.info("LEAVE: Closing browser controller...")
            try:
                await asyncio.wait_for(self._controller.close(restore_browser_audio=False), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout closing controller")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("LEAVE: Error closing controller: %s", e)
            finally:
                self.__dict__["_controller"] = None

        # 9. Emit toast notification
        try:
            notify_meeting_left(
                result.get("title", "Meeting"),
                result.get("duration_minutes", 0),
                result.get("captions_captured", 0),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        # 10. FINAL: Clean up any orphaned devices (safety net)
        await self._run_orphan_cleanup("POST-LEAVE")

        # 11. Reset state
        self.__dict__["state"] = NotesBotState()

        logger.info("=" * 60)
        logger.info("LEAVE: Meeting ended. Captured %s captions.", result["captions_captured"])
        logger.info("=" * 60)

        return result

    # Live flow kept together after the duplicate copy was removed.
    # pylint: disable-next=too-many-branches
    async def leave_meeting(self, generate_summary: bool = True) -> dict:
        """
        Leave the meeting and finalize notes.

        This is the NORMAL exit path (user requested leave).
        For unexpected exits (browser closed), see _cleanup_stale_meeting().

        Args:
            generate_summary: Whether to generate an AI summary (future feature)

        Returns:
            Meeting summary dict
        """
        del generate_summary  # reserved for a future summary step
        if self.state.status != "capturing":
            return {"error": "Not in a meeting"}

        logger.info("=" * 60)
        logger.info("LEAVE: Starting graceful meeting exit...")
        logger.info("=" * 60)

        self.state.status = "leaving"

        # 1. FIRST: Stop NPU STT pipeline - this kills the parec process
        # Must happen before closing controller to ensure clean shutdown
        if self._npu_stt_pipeline:
            logger.info("LEAVE: Stopping NPU STT pipeline...")
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
                logger.info("LEAVE: NPU STT pipeline stopped")
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout stopping NPU STT pipeline")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("LEAVE: Error stopping NPU STT: %s", e)
            finally:
                self.__dict__["_npu_stt_pipeline"] = None

        # 2. Kill any remaining audio capture processes
        try:
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info("LEAVE: Killed %s audio capture processes", killed)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("LEAVE: Error killing audio captures: %s", e)

        # 3. Cancel background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
            ("participant_poll_task", getattr(self, "_participant_poll_task", None)),
        ]

        for _task_name, task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self.__dict__["_flush_task"] = None
        self.__dict__["_screenshot_task"] = None
        self.__dict__["_browser_monitor_task"] = None
        if hasattr(self, "_participant_poll_task"):
            self.__dict__["_participant_poll_task"] = None

        # 4. Stop video daemon integration
        if self._video_daemon_active:
            logger.info("LEAVE: Stopping video daemon...")
            try:
                await asyncio.wait_for(self._stop_video_integration(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("LEAVE: Timeout stopping video daemon")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("LEAVE: Error stopping video daemon: %s", e)

        # 5. Final buffer flush
        try:
            await self._flush_buffer()
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("LEAVE: Failed to flush buffer: %s", e)

        return await self._finish_leave()

    async def _close_meeting_and_browser(self) -> None:
        """Continue a cleanup sequence."""
        # 4. Leave meeting if in one (this also flushes buffer)
        if self.state.status == "capturing":
            logger.info("CLOSE: Leaving active meeting...")
            try:
                await asyncio.wait_for(self.leave_meeting(), timeout=15.0)
            except asyncio.TimeoutError:
                logger.warning("CLOSE: Timeout leaving meeting, forcing cleanup...")
                await self._cleanup_stale_meeting()
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("CLOSE: Error leaving meeting: %s", e)
                await self._cleanup_stale_meeting()

        # 5. Close browser controller if still open
        if self._controller:
            logger.info("CLOSE: Closing browser controller...")
            try:
                await asyncio.wait_for(self._controller.close(restore_browser_audio=True), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("CLOSE: Timeout closing controller, force killing...")
                try:
                    await self._controller.force_kill()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("CLOSE: Error closing browser controller: %s", e)
            finally:
                self.__dict__["_controller"] = None

        # 6. FINAL: Clean up any remaining orphaned devices system-wide
        await self._run_orphan_cleanup("SHUTDOWN")

        # Note: Don't close the database here - it may be shared
        # The caller (scheduler/manager) is responsible for database cleanup

        logger.info("=" * 60)
        logger.info("CLOSE: Notes bot shutdown complete")
        logger.info("=" * 60)

    async def close(self) -> None:
        """Clean up all resources.

        This is the final cleanup method called when the bot is being destroyed.
        It ensures ALL resources are released, including:
        - Background tasks
        - NPU STT pipeline (and its parec processes)
        - Browser controller (and its audio devices)
        - Any orphaned devices system-wide
        """
        logger.info("=" * 60)
        logger.info("CLOSE: Shutting down notes bot...")
        logger.info("=" * 60)

        # 1. Stop NPU STT pipeline FIRST (kills parec processes)
        if self._npu_stt_pipeline:
            logger.info("CLOSE: Stopping NPU STT pipeline...")
            try:
                await asyncio.wait_for(self._npu_stt_pipeline.stop(), timeout=5.0)
            except (  # pylint: disable=broad-exception-caught
                asyncio.TimeoutError,
                Exception,
            ) as e:
                logger.warning("CLOSE: Error stopping NPU STT: %s", e)
            finally:
                self.__dict__["_npu_stt_pipeline"] = None

        # 2. Kill any remaining audio capture processes
        try:
            killed = await PulseAudioCapture.kill_all_captures()
            if killed > 0:
                logger.info("CLOSE: Killed %s orphaned audio capture processes", killed)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("CLOSE: Error killing audio captures: %s", e)

        # 3. Cancel all background tasks
        tasks_to_cancel = [
            ("flush_task", self._flush_task),
            ("screenshot_task", getattr(self, "_screenshot_task", None)),
            ("browser_monitor_task", getattr(self, "_browser_monitor_task", None)),
            ("wake_word_check_task", getattr(self, "_wake_word_check_task", None)),
            ("participant_poll_task", getattr(self, "_participant_poll_task", None)),
        ]

        for _task_name, task in tasks_to_cancel:
            if task and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self.__dict__["_flush_task"] = None
        self.__dict__["_screenshot_task"] = None

        await self._close_meeting_and_browser()
