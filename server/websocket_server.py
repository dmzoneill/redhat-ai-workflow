"""WebSocket server for real-time skill execution updates.

This provides instant updates to the VS Code extension instead of file polling.
Events include:
- Skill lifecycle (started, completed, failed)
- Step progress (started, completed, failed)
- Auto-heal triggers
- Confirmation requests/responses
- Memory query events (started, completed, intent_classified)

The server runs on localhost:9876 by default.
"""

import asyncio
import json
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from server.timeouts import Timeouts

logger = logging.getLogger(__name__)

# Try to import websockets
try:
    import websockets
    from websockets.server import WebSocketServerProtocol, serve

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets package not installed - real-time updates disabled")


@dataclass
class SkillState:
    """Track state of a running skill."""

    skill_id: str
    skill_name: str
    total_steps: int
    current_step: int = 0
    status: str = "running"  # running, completed, failed
    started_at: datetime = field(default_factory=datetime.now)
    source: str = "chat"  # chat, cron, slack, manual, api


@dataclass
class PendingConfirmation:
    """Track a pending confirmation request."""

    id: str
    skill_id: str
    step_index: int
    prompt: str
    options: list[str]
    claude_suggestion: str
    timeout_seconds: int
    created_at: datetime
    future: asyncio.Future


# Maximum number of running skills to track (prevents memory leaks from orphaned skills)
MAX_RUNNING_SKILLS = 100
# Maximum age for a running skill before it's considered stale (1 hour)
MAX_SKILL_AGE_SECONDS = 3600


class SkillWebSocketServer:
    """WebSocket server for real-time skill updates."""

    def __init__(self, host: str = "localhost", port: int = 9876):
        self.host = host
        self.port = port
        self.clients: set = set()  # WebSocketServerProtocol instances
        self.pending_confirmations: dict[str, PendingConfirmation] = {}
        self.running_skills: dict[str, SkillState] = {}
        self._server = None
        self._started = False
        # Locks for thread-safe access to shared state
        self._clients_lock = asyncio.Lock()
        self._confirmations_lock = asyncio.Lock()
        self._skills_lock = asyncio.Lock()

    async def start(self):
        """Start the WebSocket server."""
        if not WEBSOCKETS_AVAILABLE:
            logger.warning(
                "WebSocket server not started - websockets package not available"
            )
            return

        if self._started:
            return

        try:
            self._server = await serve(self._handler, self.host, self.port)
            self._started = True
            logger.info(f"WebSocket server started on ws://{self.host}:{self.port}")
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning(
                    f"WebSocket port {self.port} already in use - another instance running?"
                )
            else:
                logger.error(f"Failed to start WebSocket server: {e}")

    async def stop(self):
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._started = False
            logger.info("WebSocket server stopped")

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._started

    async def _handler(self, websocket: WebSocketServerProtocol):
        """Handle a WebSocket connection."""
        async with self._clients_lock:
            self.clients.add(websocket)
            client_count = len(self.clients)
        logger.info(f"WebSocket client connected ({client_count} total)")

        try:
            # Send connection confirmation with current state
            async with self._skills_lock:
                running_skills_data = [
                    {
                        "skill_id": s.skill_id,
                        "skill_name": s.skill_name,
                        "total_steps": s.total_steps,
                        "current_step": s.current_step,
                        "status": s.status,
                    }
                    for s in self.running_skills.values()
                ]
            async with self._confirmations_lock:
                pending_confirmations_data = [
                    {
                        "id": c.id,
                        "skill_id": c.skill_id,
                        "step_index": c.step_index,
                        "prompt": c.prompt,
                        "options": c.options,
                        "claude_suggestion": c.claude_suggestion,
                        "timeout_seconds": c.timeout_seconds,
                        "created_at": c.created_at.isoformat(),
                    }
                    for c in self.pending_confirmations.values()
                ]
            await websocket.send(
                json.dumps(
                    {
                        "type": "connected",
                        "running_skills": running_skills_data,
                        "pending_confirmations": pending_confirmations_data,
                    }
                )
            )

            async for message in websocket:
                await self._handle_message(websocket, message)

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            async with self._clients_lock:
                self.clients.discard(websocket)
                remaining = len(self.clients)
            logger.info(f"WebSocket client disconnected ({remaining} total)")

    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str):
        """Handle incoming message from client."""
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "confirmation_response":
                conf_id = data["id"]
                async with self._confirmations_lock:
                    confirmation = self.pending_confirmations.get(conf_id)
                if confirmation is not None:
                    if not confirmation.future.done():
                        confirmation.future.set_result(
                            {
                                "response": data["response"],
                                "remember": data.get("remember", "none"),
                            }
                        )
                    logger.info(f"Confirmation {conf_id} responded: {data['response']}")

            elif msg_type == "heartbeat":
                await websocket.send(json.dumps({"type": "heartbeat_ack"}))

            elif msg_type == "pause_timer":
                # Client paused the timer - we don't need to do anything server-side
                # The client handles the pause locally
                pass

            elif msg_type == "resume_timer":
                # Client resumed the timer
                pass

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON message: {e}")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")

    async def broadcast(self, event: dict):
        """Broadcast event to all connected clients."""
        async with self._clients_lock:
            if not self.clients:
                return
            # Copy clients to avoid holding lock during I/O
            clients_copy = list(self.clients)

        message = json.dumps(event, default=str)
        # Send to all clients, ignore failures
        results = await asyncio.gather(
            *[client.send(message) for client in clients_copy], return_exceptions=True
        )

        # Log any errors
        for _i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.debug(f"Failed to send to client: {result}")

    # ==================== Skill Lifecycle Events ====================

    async def _cleanup_stale_skills(self) -> int:
        """Remove stale skills that have been running too long.

        This prevents memory leaks from skills that never completed/failed.

        Returns:
            Number of skills removed
        """
        now = datetime.now()
        stale_ids = []

        async with self._skills_lock:
            for skill_id, skill in self.running_skills.items():
                age = (now - skill.started_at).total_seconds()
                if age > MAX_SKILL_AGE_SECONDS:
                    stale_ids.append(skill_id)

            for skill_id in stale_ids:
                del self.running_skills[skill_id]
                logger.warning(f"Removed stale skill {skill_id} (exceeded max age)")

            # Also enforce max count by removing oldest if over limit
            while len(self.running_skills) > MAX_RUNNING_SKILLS:
                oldest_id = min(
                    self.running_skills.keys(),
                    key=lambda k: self.running_skills[k].started_at,
                )
                del self.running_skills[oldest_id]
                logger.warning(f"Removed oldest skill {oldest_id} (exceeded max count)")
                stale_ids.append(oldest_id)

        return len(stale_ids)

    async def skill_started(
        self,
        skill_id: str,
        skill_name: str,
        total_steps: int,
        inputs: dict | None = None,
        source: str = "chat",
    ):
        """Notify that a skill has started."""
        # Cleanup stale skills before adding new one
        await self._cleanup_stale_skills()

        async with self._skills_lock:
            self.running_skills[skill_id] = SkillState(
                skill_id=skill_id,
                skill_name=skill_name,
                total_steps=total_steps,
                source=source,
            )

        await self.broadcast(
            {
                "type": "skill_started",
                "skill_id": skill_id,
                "skill_name": skill_name,
                "total_steps": total_steps,
                "inputs": inputs or {},
                "source": source,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Skill started: {skill_name} ({skill_id}) source={source}")

    async def skill_completed(
        self, skill_id: str, total_duration_ms: int | None = None
    ):
        """Notify that a skill has completed successfully."""
        async with self._skills_lock:
            if skill_id in self.running_skills:
                self.running_skills[skill_id].status = "completed"

        await self.broadcast(
            {
                "type": "skill_completed",
                "skill_id": skill_id,
                "total_duration_ms": total_duration_ms,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Skill completed: {skill_id}")

        # Remove from running skills after a delay
        asyncio.create_task(self._remove_skill_delayed(skill_id, delay=5.0))

    async def skill_failed(
        self, skill_id: str, error: str, total_duration_ms: int | None = None
    ):
        """Notify that a skill has failed."""
        async with self._skills_lock:
            if skill_id in self.running_skills:
                self.running_skills[skill_id].status = "failed"

        await self.broadcast(
            {
                "type": "skill_failed",
                "skill_id": skill_id,
                "error": error,
                "total_duration_ms": total_duration_ms,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Skill failed: {skill_id} - {error}")

        # Remove from running skills after a delay
        asyncio.create_task(self._remove_skill_delayed(skill_id, delay=10.0))

    async def _remove_skill_delayed(self, skill_id: str, delay: float):
        """Remove a skill from running_skills after a delay."""
        await asyncio.sleep(delay)
        async with self._skills_lock:
            self.running_skills.pop(skill_id, None)

    # ==================== Step Events ====================

    async def step_started(
        self, skill_id: str, step_index: int, step_name: str, description: str = ""
    ):
        """Notify that a step has started."""
        async with self._skills_lock:
            if skill_id in self.running_skills:
                self.running_skills[skill_id].current_step = step_index

        await self.broadcast(
            {
                "type": "step_started",
                "skill_id": skill_id,
                "step_index": step_index,
                "step_name": step_name,
                "description": description,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Step started: {skill_id} [{step_index}] {step_name}")

    async def step_completed(
        self, skill_id: str, step_index: int, step_name: str, duration_ms: int
    ):
        """Notify that a step has completed."""
        await self.broadcast(
            {
                "type": "step_completed",
                "skill_id": skill_id,
                "step_index": step_index,
                "step_name": step_name,
                "duration_ms": duration_ms,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(
            f"Step completed: {skill_id} [{step_index}] {step_name} ({duration_ms}ms)"
        )

    async def step_failed(
        self, skill_id: str, step_index: int, step_name: str, error: str
    ):
        """Notify that a step has failed."""
        await self.broadcast(
            {
                "type": "step_failed",
                "skill_id": skill_id,
                "step_index": step_index,
                "step_name": step_name,
                "error": error,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Step failed: {skill_id} [{step_index}] {step_name} - {error}")

    # ==================== Auto-Heal Events ====================

    async def auto_heal_triggered(
        self,
        skill_id: str,
        step_index: int,
        error_type: str,
        fix_action: str,
        error_snippet: str = "",
    ):
        """Notify that auto-heal has been triggered."""
        await self.broadcast(
            {
                "type": "auto_heal_triggered",
                "skill_id": skill_id,
                "step_index": step_index,
                "error_type": error_type,
                "fix_action": fix_action,
                "error_snippet": error_snippet[:200] if error_snippet else "",
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(
            f"Auto-heal triggered: {skill_id} [{step_index}] {error_type} -> {fix_action}"
        )

    async def auto_heal_completed(
        self, skill_id: str, step_index: int, fix_action: str, success: bool
    ):
        """Notify that auto-heal has completed."""
        await self.broadcast(
            {
                "type": "auto_heal_completed",
                "skill_id": skill_id,
                "step_index": step_index,
                "fix_action": fix_action,
                "success": success,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(
            f"Auto-heal completed: {skill_id} [{step_index}] {fix_action} success={success}"
        )

    # ==================== Confirmation System ====================

    async def request_confirmation(
        self,
        skill_id: str,
        step_index: int,
        prompt: str,
        options: list[str],
        claude_suggestion: str = "",
        timeout_seconds: int = 30,
    ) -> dict:
        """Request confirmation from user, wait for response.

        Returns:
            dict with 'response' and 'remember' keys
        """
        conf_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()

        confirmation = PendingConfirmation(
            id=conf_id,
            skill_id=skill_id,
            step_index=step_index,
            prompt=prompt,
            options=options,
            claude_suggestion=claude_suggestion,
            timeout_seconds=timeout_seconds,
            created_at=datetime.now(),
            future=loop.create_future(),
        )

        async with self._confirmations_lock:
            self.pending_confirmations[conf_id] = confirmation

        # Bring Cursor to front and play notification sound (non-blocking)
        await self._bring_cursor_to_front()
        await self._play_notification_sound()

        # Broadcast confirmation request
        await self.broadcast(
            {
                "type": "confirmation_required",
                "id": conf_id,
                "skill_id": skill_id,
                "step_index": step_index,
                "prompt": prompt,
                "options": options,
                "claude_suggestion": claude_suggestion,
                "timeout_seconds": timeout_seconds,
                "created_at": confirmation.created_at.isoformat(),
            }
        )

        logger.info(f"Confirmation requested: {conf_id} - {prompt[:50]}...")

        # Wait for response with timeout
        try:
            result = await asyncio.wait_for(
                confirmation.future, timeout=timeout_seconds
            )

            # Broadcast that confirmation was answered
            await self.broadcast(
                {
                    "type": "confirmation_answered",
                    "id": conf_id,
                    "response": result["response"],
                    "remember": result.get("remember", "none"),
                }
            )

            logger.info(f"Confirmation {conf_id} answered: {result['response']}")
            return result

        except asyncio.TimeoutError:
            # Broadcast expiration
            await self.broadcast(
                {
                    "type": "confirmation_expired",
                    "id": conf_id,
                }
            )

            logger.info(f"Confirmation {conf_id} expired - defaulting to let_claude")

            # Try Zenity fallback if no clients connected
            if not self.clients:
                zenity_result = await self._zenity_fallback(
                    prompt, options, claude_suggestion
                )
                if zenity_result:
                    return zenity_result

            return {"response": "let_claude", "remember": "none"}

        finally:
            async with self._confirmations_lock:
                self.pending_confirmations.pop(conf_id, None)

    def _bring_cursor_to_front_sync(self) -> None:
        """Raise Cursor window to front (blocking - run in thread)."""
        try:
            # Try wmctrl first (more reliable)
            result = subprocess.run(
                ["wmctrl", "-a", "Cursor"],
                check=False,
                capture_output=True,
                timeout=Timeouts.INSTANT,
            )
            if result.returncode == 0:
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        try:
            # Fallback to xdotool
            subprocess.run(
                ["xdotool", "search", "--name", "Cursor", "windowactivate"],
                check=False,
                capture_output=True,
                timeout=Timeouts.INSTANT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    async def _bring_cursor_to_front(self) -> None:
        """Raise Cursor window to front (non-blocking)."""
        await asyncio.to_thread(self._bring_cursor_to_front_sync)

    def _play_notification_sound_sync(self) -> None:
        """Play notification sound (blocking - run in thread)."""
        sound_files = [
            "/usr/share/sounds/freedesktop/stereo/message.oga",
            "/usr/share/sounds/freedesktop/stereo/complete.oga",
            "/usr/share/sounds/gnome/default/alerts/drip.ogg",
        ]

        for sound_file in sound_files:
            try:
                subprocess.run(
                    ["paplay", sound_file],
                    check=False,
                    capture_output=True,
                    timeout=Timeouts.INSTANT,
                )
                return
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

    async def _play_notification_sound(self) -> None:
        """Play notification sound (non-blocking)."""
        await asyncio.to_thread(self._play_notification_sound_sync)

    async def _zenity_fallback(
        self, prompt: str, options: list[str], claude_suggestion: str
    ) -> dict | None:
        """Fallback to Zenity dialog if no WebSocket clients connected."""
        try:
            # Build Zenity command
            text = prompt
            if claude_suggestion:
                text += f"\n\n💡 Suggestion: {claude_suggestion}"

            # Use zenity --question with custom buttons
            cmd = [
                "zenity",
                "--question",
                "--title=Skill Confirmation Required",
                f"--text={text}",
                "--width=400",
            ]

            # Add buttons (Zenity supports --ok-label and --cancel-label)
            if "retry_with_fix" in options:
                cmd.extend(["--ok-label=Retry with Fix"])
            if "abort" in options:
                cmd.extend(["--cancel-label=Abort"])

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            await asyncio.wait_for(process.wait(), timeout=Timeouts.PROCESS_WAIT)

            if process.returncode == 0:
                return {"response": "retry_with_fix", "remember": "none"}
            else:
                return {"response": "abort", "remember": "none"}

        except FileNotFoundError:
            logger.debug("Zenity not available for fallback")
            return None
        except asyncio.TimeoutExpired:
            logger.debug("Zenity dialog timed out")
            return None
        except Exception as e:
            logger.debug(f"Zenity fallback failed: {e}")
            return None

    # ==================== Memory Query Events ====================

    async def memory_query_started(
        self,
        query_id: str,
        query: str,
        sources: list[str],
    ):
        """Notify that a memory query has started."""
        await self.broadcast(
            {
                "type": "memory_query_started",
                "query_id": query_id,
                "query": query,
                "sources": sources,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Memory query started: {query_id} - {query[:50]}...")

    async def memory_query_completed(
        self,
        query_id: str,
        intent: dict,
        sources_queried: list[str],
        result_count: int,
        latency_ms: float,
    ):
        """Notify that a memory query has completed."""
        await self.broadcast(
            {
                "type": "memory_query_completed",
                "query_id": query_id,
                "intent": intent,
                "sources_queried": sources_queried,
                "result_count": result_count,
                "latency_ms": latency_ms,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(
            f"Memory query completed: {query_id} - {result_count} results in {latency_ms:.0f}ms"
        )

    async def intent_classified(
        self,
        query_id: str,
        query: str,
        intent: str,
        confidence: float,
        sources_suggested: list[str],
    ):
        """Notify that intent classification has completed."""
        await self.broadcast(
            {
                "type": "intent_classified",
                "query_id": query_id,
                "query": query,
                "intent": intent,
                "confidence": confidence,
                "sources_suggested": sources_suggested,
                "timestamp": datetime.now().isoformat(),
            }
        )
        logger.debug(f"Intent classified: {query_id} - {intent} ({confidence:.0%})")


# ==================== Global Instance ====================

_ws_server: Optional[SkillWebSocketServer] = None


def get_websocket_server() -> SkillWebSocketServer:
    """Get or create the global WebSocket server instance."""
    global _ws_server
    if _ws_server is None:
        _ws_server = SkillWebSocketServer()
    return _ws_server


async def start_websocket_server():
    """Start the global WebSocket server."""
    server = get_websocket_server()
    await server.start()
    return server


async def stop_websocket_server():
    """Stop the global WebSocket server."""
    global _ws_server
    if _ws_server:
        await _ws_server.stop()
        _ws_server = None
