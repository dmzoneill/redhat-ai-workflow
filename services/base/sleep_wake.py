#!/usr/bin/env python3
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
import logging
import time
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


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
        on_sleep_callback: Optional[Callable[[], Awaitable[None]]] = None,
        time_gap_threshold: float = 30.0,
        check_interval: float = 10.0,
    ):
        self._on_wake = on_wake_callback
        self._on_sleep = on_sleep_callback
        self._time_gap_threshold = time_gap_threshold
        self._check_interval = check_interval

        self._bus = None
        self._last_active_time = time.monotonic()
        self._time_gap_task: Optional[asyncio.Task] = None
        self._logind_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._wake_count = 0
        self._last_wake_time: Optional[float] = None

    @property
    def wake_count(self) -> int:
        """Number of times system has woken since monitor started."""
        return self._wake_count

    @property
    def last_wake_time(self) -> Optional[float]:
        """Timestamp of last wake event (monotonic time)."""
        return self._last_wake_time

    async def start(self):
        """Start monitoring for sleep/wake events."""
        if self._is_running:
            return

        self._is_running = True
        self._last_active_time = time.monotonic()

        # Method 1: Monitor time gaps (always works)
        self._time_gap_task = asyncio.create_task(
            self._monitor_time_gaps(), name="sleep_wake_time_gap_monitor"
        )

        # Method 2: Try to subscribe to logind PrepareForSleep signal
        try:
            await self._subscribe_logind()
            logger.info("Sleep/wake monitor started (logind + time gap)")
        except Exception as e:
            logger.debug(f"Could not subscribe to logind signals: {e}")
            logger.info("Sleep/wake monitor started (time gap only)")

    async def stop(self):
        """Stop monitoring."""
        self._is_running = False

        # Cancel time gap monitor
        if self._time_gap_task:
            self._time_gap_task.cancel()
            try:
                await self._time_gap_task
            except asyncio.CancelledError:
                pass
            self._time_gap_task = None

        # Cancel logind monitor
        if self._logind_task:
            self._logind_task.cancel()
            try:
                await self._logind_task
            except asyncio.CancelledError:
                pass
            self._logind_task = None

        # Disconnect D-Bus
        if self._bus:
            try:
                self._bus.disconnect()
            except Exception as exc:
                logger.debug("Suppressed error: %s", exc)
            self._bus = None

        logger.info("Sleep/wake monitor stopped")

    async def _monitor_time_gaps(self):
        """
        Detect sleep by monitoring for time gaps.

        If the time between checks is much larger than expected,
        the system likely slept.
        """
        while self._is_running:
            try:
                await asyncio.sleep(self._check_interval)

                now = time.monotonic()
                elapsed = now - self._last_active_time
                self._last_active_time = now

                # If elapsed time is much larger than expected, we probably slept
                if elapsed > self._time_gap_threshold:
                    logger.info(f"Detected wake from sleep (time gap: {elapsed:.1f}s)")
                    await self._handle_wake()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Sleep monitor error: {e}")
                await asyncio.sleep(self._check_interval)

    async def _subscribe_logind(self):
        """Subscribe to systemd-logind PrepareForSleep signal."""
        from dbus_next import BusType
        from dbus_next.aio import MessageBus

        self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

        # Subscribe to PrepareForSleep signal from logind
        introspection = await self._bus.introspect(
            "org.freedesktop.login1", "/org/freedesktop/login1"
        )

        proxy = self._bus.get_proxy_object(
            "org.freedesktop.login1", "/org/freedesktop/login1", introspection
        )

        manager = proxy.get_interface("org.freedesktop.login1.Manager")

        # Connect to PrepareForSleep signal
        manager.on_prepare_for_sleep(self._on_prepare_for_sleep)

        logger.debug("Subscribed to systemd-logind sleep/wake signals")

        # Keep the connection alive
        self._logind_task = asyncio.create_task(
            self._keep_logind_alive(), name="sleep_wake_logind_monitor"
        )

    async def _keep_logind_alive(self):
        """Keep the logind D-Bus connection alive."""
        try:
            while self._is_running:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            pass

    def _on_prepare_for_sleep(self, going_to_sleep: bool):
        """Handle PrepareForSleep signal from logind."""
        if going_to_sleep:
            logger.info("System preparing for sleep...")
            if self._on_sleep:
                asyncio.create_task(self._handle_sleep())
        else:
            logger.info("System waking from sleep (logind signal)")
            asyncio.create_task(self._handle_wake())

    async def _handle_sleep(self):
        """Handle system going to sleep."""
        if self._on_sleep:
            try:
                await self._on_sleep()
            except Exception as e:
                logger.error(f"Error in sleep callback: {e}")

    async def _handle_wake(self):
        """Handle system wake."""
        self._wake_count += 1
        self._last_wake_time = time.monotonic()
        self._last_active_time = time.monotonic()  # Reset time gap detection

        try:
            await self._on_wake()
        except Exception as e:
            logger.error(f"Error in wake callback: {e}")


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

    @abstractmethod
            async def on_system_sleep(self):
                # Optional: save state before sleep
                pass
    """

    _sleep_monitor: Optional[SleepWakeMonitor] = None

    @abstractmethod
    async def on_system_wake(self):
        """
        Called when system wakes from sleep.

        Override this to refresh data, reconnect services, etc.
        """
        pass

    async def on_system_sleep(self):  # noqa: B027
        """
        Called before system goes to sleep.

        Override this to save state, close connections, etc.
        Default implementation does nothing.
        """
        pass

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
        except Exception as e:
            logger.error(f"Error handling system wake: {e}")

    async def _handle_system_sleep(self):
        """Internal sleep handler that calls the user's on_system_sleep."""
        logger.info("Handling system sleep...")
        try:
            await self.on_system_sleep()
            logger.info("System sleep handling complete")
        except Exception as e:
            logger.error(f"Error handling system sleep: {e}")

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
        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._next_fire_time: Optional[float] = None

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
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self):
        """Run the timer loop."""
        while self._is_running:
            try:
                # Calculate time until next fire
                now = time.time()
                wait_time = max(0, self._next_fire_time - now)

                if wait_time > 0:
                    # Use short sleeps to detect wake quickly
                    sleep_chunk = min(wait_time, 5.0)
                    await asyncio.sleep(sleep_chunk)
                    continue

                # Time to fire
                try:
                    await self._callback()
                except Exception as e:
                    logger.error(f"Timer {self._name} callback error: {e}")

                # Schedule next fire
                self._next_fire_time = time.time() + self._interval

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Timer {self._name} error: {e}")
                await asyncio.sleep(1)

    def reschedule(self, delay: Optional[float] = None):
        """
        Reschedule the timer.

        Args:
            delay: Seconds until next fire. If None, uses the interval.
        """
        self._next_fire_time = time.time() + (
            delay if delay is not None else self._interval
        )


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
        self._interval = interval
        self._callback = callback
        self._name = name
        self._run_immediately = run_immediately
        self._max_jitter = max_jitter

        self._task: Optional[asyncio.Task] = None
        self._is_running = False
        self._last_run_time: Optional[float] = None
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
        self._task = asyncio.create_task(
            self._run(), name=f"robust_periodic_{self._name}"
        )

    async def stop(self):
        """Stop the periodic task."""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def trigger_now(self):
        """Trigger the callback immediately (outside normal schedule)."""
        try:
            await self._callback()
            self._last_run_time = time.time()
        except Exception as e:
            logger.error(f"Task {self._name} callback error: {e}")

    async def _run(self):
        """Run the periodic task loop."""
        import random

        # Run immediately if requested
        if self._run_immediately:
            await self.trigger_now()

        while self._is_running:
            try:
                # Calculate time since last run
                now = time.time()

                if self._last_run_time:
                    elapsed = now - self._last_run_time

                    # Check if we missed cycles (e.g., due to sleep)
                    if elapsed > self._interval * 1.5:
                        missed = int(elapsed / self._interval) - 1
                        if missed > 0:
                            self._missed_cycles += missed
                            logger.info(
                                f"Task {self._name}: missed {missed} cycles "
                                f"(elapsed: {elapsed:.1f}s, interval: {self._interval}s)"
                            )
                        # Fire immediately after detecting missed cycles
                        await self.trigger_now()
                        continue

                    # Normal wait
                    wait_time = max(0, self._interval - elapsed)
                else:
                    wait_time = self._interval

                # Add jitter if configured
                if self._max_jitter > 0:
                    wait_time += random.uniform(0, self._max_jitter)

                # Sleep in chunks to detect wake quickly
                while wait_time > 0 and self._is_running:
                    chunk = min(wait_time, 5.0)
                    await asyncio.sleep(chunk)
                    wait_time -= chunk

                    # Re-check elapsed time after each chunk
                    # This catches sleep during our wait
                    if self._last_run_time:
                        elapsed = time.time() - self._last_run_time
                        if elapsed > self._interval * 1.5:
                            break  # Exit wait loop to handle missed cycle

                if not self._is_running:
                    break

                # Fire the callback
                await self.trigger_now()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Task {self._name} error: {e}")
                await asyncio.sleep(1)
