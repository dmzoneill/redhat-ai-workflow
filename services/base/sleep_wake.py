"""
Sleep/Wake Detection for AI Workflow Daemons

Provides consistent sleep/wake handling across all daemons:
- Detects system sleep via systemd-logind D-Bus signals
- Fallback detection via time gap monitoring
- Callback-based notification system
- Automatic timer/task recovery after wake

Usage:
    from services.base import SleepWakeMonitor

    async def on_wake():
        print("System woke up!")
        await refresh_my_data()

    monitor = SleepWakeMonitor(on_wake_callback=on_wake)
    await monitor.start()
    # ... daemon runs ...
    await monitor.stop()

Integration with DaemonDBusBase:
    The SleepWakeAwareDaemon mixin provides automatic integration:

    class MyDaemon(SleepWakeAwareDaemon, DaemonDBusBase):
        async def on_system_wake(self):
            # Called automatically after wake
            await self.refresh_data()
"""

import asyncio
import importlib
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _optional_dbus_error() -> tuple[type[Exception], ...]:
    """Return dbus_next's DBusError when installed, else an empty tuple."""
    try:
        return (importlib.import_module("dbus_next.errors").DBusError,)
    except ImportError:
        return ()


# Errors raised by daemon callbacks, D-Bus calls or timers that are logged
# and survived so one failure doesn't stop sleep/wake handling.
CALLBACK_ERRORS: tuple[type[Exception], ...] = (
    ArithmeticError,
    AttributeError,
    ImportError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    asyncio.TimeoutError,
    *_optional_dbus_error(),
)


async def _cancel_and_wait(task: asyncio.Task | None) -> None:
    """Cancel ``task`` and wait for it to finish.

    asyncio.wait() never raises the task's result, so the task's own
    CancelledError isn't swallowed here and a cancellation of the caller
    still propagates.
    """
    if task is None:
        return
    task.cancel()
    await asyncio.wait({task})


@dataclass
class _MonitorConfig:
    """Callbacks and timings for a SleepWakeMonitor."""

    on_wake: Callable[[], Awaitable[None]]
    on_sleep: Callable[[], Awaitable[None]] | None
    time_gap_threshold: float
    check_interval: float


class SleepWakeMonitor:
    """
    Monitor system sleep/wake events.

    Uses two detection methods:
    1. systemd-logind D-Bus signals (primary, immediate)
    2. Time gap monitoring (fallback, works without D-Bus)

    Args:
        on_wake_callback: Async function to call when system wakes
        on_sleep_callback: Optional async function to call before sleep
        time_gap_threshold: Seconds of gap to consider as sleep (default: 30)
        check_interval: How often to check for time gaps (default: 10s)
    """

    def __init__(
        self,
        on_wake_callback: Callable[[], Awaitable[None]],
        on_sleep_callback: Callable[[], Awaitable[None]] | None = None,
        time_gap_threshold: float = 30.0,
        check_interval: float = 10.0,
    ):
        self._config = _MonitorConfig(on_wake_callback, on_sleep_callback, time_gap_threshold, check_interval)
        self._bus = None
        self._last_active_time = time.monotonic()
        # Monitor tasks plus signal-handler tasks; held so they aren't
        # garbage-collected mid-run, and cancelled together on stop().
        self._tasks: set[asyncio.Task] = set()
        self._is_running = False
        self._wake_count = 0
        self._last_wake_time: float | None = None

    @property
    def wake_count(self) -> int:
        """Number of times system has woken since monitor started."""
        return self._wake_count

    @property
    def last_wake_time(self) -> float | None:
        """Timestamp of last wake event (monotonic time)."""
        return self._last_wake_time

    def _spawn(self, coro, name: str | None = None) -> asyncio.Task:
        """Create a task and keep a reference until it finishes."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def start(self):
        """Start monitoring for sleep/wake events."""
        if self._is_running:
            return

        self._is_running = True
        self._last_active_time = time.monotonic()

        # Method 1: Monitor time gaps (always works)
        self._spawn(self._monitor_time_gaps(), name="sleep_wake_time_gap_monitor")

        # Method 2: Try to subscribe to logind PrepareForSleep signal
        try:
            await self._subscribe_logind()
            logger.info("Sleep/wake monitor started (logind + time gap)")
        except CALLBACK_ERRORS as e:
            logger.debug("Could not subscribe to logind signals: %s", e)
            logger.info("Sleep/wake monitor started (time gap only)")

    async def stop(self):
        """Stop monitoring."""
        self._is_running = False

        # Cancel the time gap monitor, logind keep-alive and any pending handlers
        for task in list(self._tasks):
            await _cancel_and_wait(task)
        self._tasks.clear()

        # Disconnect D-Bus
        if self._bus:
            try:
                self._bus.disconnect()
            except CALLBACK_ERRORS as exc:
                logger.debug("Suppressed error: %s", exc)
            self._bus = None

        logger.info("Sleep/wake monitor stopped")

    async def _monitor_time_gaps(self):
        """
        Detect sleep by monitoring for time gaps.

        If the time between checks is much larger than expected,
        the system likely slept. Cancellation propagates to the caller.
        """
        while self._is_running:
            try:
                await asyncio.sleep(self._config.check_interval)

                now = time.monotonic()
                elapsed = now - self._last_active_time
                self._last_active_time = now

                # If elapsed time is much larger than expected, we probably slept
                if elapsed > self._config.time_gap_threshold:
                    logger.info("Detected wake from sleep (time gap: %.1fs)", elapsed)
                    await self._handle_wake()

            except CALLBACK_ERRORS as e:
                logger.warning("Sleep monitor error: %s", e)
                await asyncio.sleep(self._config.check_interval)

    async def _subscribe_logind(self):
        """Subscribe to systemd-logind PrepareForSleep signal."""
        dbus_next = importlib.import_module("dbus_next")
        message_bus = importlib.import_module("dbus_next.aio").MessageBus

        self._bus = await message_bus(bus_type=dbus_next.BusType.SYSTEM).connect()

        # Subscribe to PrepareForSleep signal from logind
        introspection = await self._bus.introspect("org.freedesktop.login1", "/org/freedesktop/login1")

        proxy = self._bus.get_proxy_object("org.freedesktop.login1", "/org/freedesktop/login1", introspection)

        manager = proxy.get_interface("org.freedesktop.login1.Manager")

        # Connect to PrepareForSleep signal
        manager.on_prepare_for_sleep(self._on_prepare_for_sleep)

        logger.debug("Subscribed to systemd-logind sleep/wake signals")

        # Keep the connection alive
        self._spawn(self._keep_logind_alive(), name="sleep_wake_logind_monitor")

    async def _keep_logind_alive(self):
        """Keep the logind D-Bus connection alive until stopped or cancelled."""
        while self._is_running:
            await asyncio.sleep(60)

    def _on_prepare_for_sleep(self, going_to_sleep: bool):
        """Handle PrepareForSleep signal from logind."""
        if going_to_sleep:
            logger.info("System preparing for sleep...")
            if self._config.on_sleep:
                self._spawn(self._handle_sleep())
        else:
            logger.info("System waking from sleep (logind signal)")
            self._spawn(self._handle_wake())

    async def _handle_sleep(self):
        """Handle system going to sleep."""
        if self._config.on_sleep:
            try:
                await self._config.on_sleep()
            except CALLBACK_ERRORS as e:
                logger.error("Error in sleep callback: %s", e)

    async def _handle_wake(self):
        """Handle system wake."""
        self._wake_count += 1
        self._last_wake_time = time.monotonic()
        self._last_active_time = time.monotonic()  # Reset time gap detection

        try:
            await self._config.on_wake()
        except CALLBACK_ERRORS as e:
            logger.error("Error in wake callback: %s", e)


class SleepWakeAwareDaemon(ABC):
    """
    Mixin class for daemons that need sleep/wake awareness.

    Add this as a parent class to your daemon to get automatic
    sleep/wake handling.

    Usage:
        class MyDaemon(SleepWakeAwareDaemon, DaemonDBusBase):
            async def on_system_wake(self):
                # Refresh your data here
                await self.refresh_calendars()

            async def on_system_sleep(self):
                # Optional: save state before sleep
                pass
    """

    _sleep_monitor: SleepWakeMonitor | None = None

    @abstractmethod
    async def on_system_wake(self):
        """
        Called when system wakes from sleep.

        Override this to refresh data, reconnect services, etc.
        """

    async def on_system_sleep(self):
        """
        Called before system goes to sleep.

        Override this to save state, close connections, etc.
        Default implementation does nothing.
        """

    async def start_sleep_monitor(self):
        """Start the sleep/wake monitor."""
        self._sleep_monitor = SleepWakeMonitor(
            on_wake_callback=self._handle_system_wake,
            on_sleep_callback=self._handle_system_sleep,
        )
        await self._sleep_monitor.start()

    async def stop_sleep_monitor(self):
        """Stop the sleep/wake monitor."""
        if self._sleep_monitor:
            await self._sleep_monitor.stop()
            self._sleep_monitor = None

    async def _handle_system_wake(self):
        """Internal wake handler that calls the user's on_system_wake."""
        logger.info("Handling system wake...")
        try:
            await self.on_system_wake()
            logger.info("System wake handling complete")
        except CALLBACK_ERRORS as e:
            logger.error("Error handling system wake: %s", e)

    async def _handle_system_sleep(self):
        """Internal sleep handler that calls the user's on_system_sleep."""
        logger.info("Handling system sleep...")
        try:
            await self.on_system_sleep()
            logger.info("System sleep handling complete")
        except CALLBACK_ERRORS as e:
            logger.error("Error handling system sleep: %s", e)

    @property
    def wake_count(self) -> int:
        """Number of times system has woken since daemon started."""
        if self._sleep_monitor:
            return self._sleep_monitor.wake_count
        return 0


class RobustTimer:
    """
    A timer that survives system sleep.

    Regular asyncio.sleep() doesn't account for sleep time - if you
    sleep for 60 seconds and the system sleeps for 8 hours, you'll
    wake up 8 hours late.

    RobustTimer uses wall clock time to ensure callbacks fire at the
    right time even after system sleep.

    Usage:
        timer = RobustTimer(interval=60, callback=my_callback)
        await timer.start()
        # ... later ...
        await timer.stop()
    """

    def __init__(
        self,
        interval: float,
        callback: Callable[[], Awaitable[None]],
        name: str = "timer",
    ):
        self._interval = interval
        self._callback = callback
        self._name = name
        self._task: asyncio.Task | None = None
        self._is_running = False
        self._next_fire_time: float | None = None

    async def start(self):
        """Start the timer."""
        if self._is_running:
            return

        self._is_running = True
        self._next_fire_time = time.time() + self._interval
        self._task = asyncio.create_task(self._run(), name=f"robust_timer_{self._name}")

    async def stop(self):
        """Stop the timer."""
        self._is_running = False
        await _cancel_and_wait(self._task)
        self._task = None

    async def _run(self):
        """Run the timer loop; cancellation propagates to the caller."""
        while self._is_running:
            try:
                # Calculate time until next fire
                wait_time = max(0.0, (self._next_fire_time or 0.0) - time.time())

                if wait_time > 0:
                    # Use short sleeps to detect wake quickly
                    await asyncio.sleep(min(wait_time, 5.0))
                    continue

                # Time to fire
                try:
                    await self._callback()
                except CALLBACK_ERRORS as e:
                    logger.error("Timer %s callback error: %s", self._name, e)

                # Schedule next fire
                self._next_fire_time = time.time() + self._interval

            except CALLBACK_ERRORS as e:
                logger.error("Timer %s error: %s", self._name, e)
                await asyncio.sleep(1)

    def reschedule(self, delay: float | None = None):
        """
        Reschedule the timer.

        Args:
            delay: Seconds until next fire. If None, uses the interval.
        """
        self._next_fire_time = time.time() + (delay if delay is not None else self._interval)


@dataclass
class _PeriodicSchedule:
    """Timing options for a RobustPeriodicTask."""

    interval: float
    run_immediately: bool
    max_jitter: float


class RobustPeriodicTask:
    """
    A periodic task that handles sleep gracefully.

    Unlike a simple loop with asyncio.sleep(), this:
    - Fires immediately after wake if a cycle was missed
    - Tracks missed cycles
    - Provides jitter to avoid thundering herd

    Usage:
        task = RobustPeriodicTask(
            interval=300,  # 5 minutes
            callback=poll_calendars,
            name="calendar_poll",
            run_immediately=True,
        )
        await task.start()
    """

    def __init__(
        self,
        interval: float,
        callback: Callable[[], Awaitable[None]],
        name: str = "task",
        run_immediately: bool = False,
        max_jitter: float = 0,
    ):
        self._schedule = _PeriodicSchedule(interval, run_immediately, max_jitter)
        self._callback = callback
        self._name = name

        self._task: asyncio.Task | None = None
        self._is_running = False
        self._last_run_time: float | None = None
        self._missed_cycles = 0

    @property
    def missed_cycles(self) -> int:
        """Number of cycles missed (e.g., due to sleep)."""
        return self._missed_cycles

    async def start(self):
        """Start the periodic task."""
        if self._is_running:
            return

        self._is_running = True
        self._task = asyncio.create_task(self._run(), name=f"robust_periodic_{self._name}")

    async def stop(self):
        """Stop the periodic task."""
        self._is_running = False
        await _cancel_and_wait(self._task)
        self._task = None

    async def trigger_now(self):
        """Trigger the callback immediately (outside normal schedule)."""
        try:
            await self._callback()
            self._last_run_time = time.time()
        except CALLBACK_ERRORS as e:
            logger.error("Task %s callback error: %s", self._name, e)

    def _overdue(self) -> bool:
        """Whether more than 1.5 intervals have passed since the last run."""
        if not self._last_run_time:
            return False
        return time.time() - self._last_run_time > self._schedule.interval * 1.5

    def _record_missed_cycles(self) -> None:
        """Count and log the cycles missed since the last run."""
        elapsed = time.time() - (self._last_run_time or 0.0)
        missed = int(elapsed / self._schedule.interval) - 1
        if missed > 0:
            self._missed_cycles += missed
            logger.info(
                "Task %s: missed %s cycles (elapsed: %.1fs, interval: %ss)",
                self._name,
                missed,
                elapsed,
                self._schedule.interval,
            )

    def _next_wait(self) -> float:
        """Seconds to wait before the next run, including any jitter."""
        if self._last_run_time:
            wait_time = max(0.0, self._schedule.interval - (time.time() - self._last_run_time))
        else:
            wait_time = self._schedule.interval
        if self._schedule.max_jitter > 0:
            wait_time += random.uniform(0, self._schedule.max_jitter)
        return wait_time

    async def _wait(self, wait_time: float) -> None:
        """Sleep in 5s chunks, stopping early if stopped or a cycle is missed."""
        while wait_time > 0 and self._is_running:
            chunk = min(wait_time, 5.0)
            await asyncio.sleep(chunk)
            wait_time -= chunk
            # Re-check after each chunk; this catches sleep during our wait
            if self._overdue():
                return

    async def _run(self):
        """Run the periodic task loop; cancellation propagates to the caller."""
        # Run immediately if requested
        if self._schedule.run_immediately:
            await self.trigger_now()

        while self._is_running:
            try:
                # Fire immediately after detecting missed cycles (e.g., due to sleep)
                if self._overdue():
                    self._record_missed_cycles()
                    await self.trigger_now()
                    continue

                await self._wait(self._next_wait())
                if not self._is_running:
                    break

                # Fire the callback
                await self.trigger_now()

            except CALLBACK_ERRORS as e:
                logger.error("Task %s error: %s", self._name, e)
                await asyncio.sleep(1)
