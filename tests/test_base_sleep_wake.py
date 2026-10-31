"""Tests for services.base.sleep_wake."""

import asyncio
import time

import pytest

from services.base import sleep_wake


def _run(coro):
    return asyncio.run(coro)


def test_time_gap_triggers_wake(monkeypatch):
    """A monotonic jump bigger than the threshold calls the wake callback."""
    woke = []

    async def on_wake():
        woke.append(True)

    async def scenario():
        monitor = sleep_wake.SleepWakeMonitor(on_wake, time_gap_threshold=0.5, check_interval=0.01)

        async def no_logind():
            raise OSError("no system bus")

        monkeypatch.setattr(monitor, "_subscribe_logind", no_logind)
        await monitor.start()
        vars(monitor)["_last_active_time"] -= 10
        for _ in range(50):
            if woke:
                break
            await asyncio.sleep(0.01)
        await monitor.stop()
        return monitor

    monitor = _run(scenario())
    assert woke
    assert monitor.wake_count >= 1
    assert monitor.last_wake_time is not None
    assert not vars(monitor)["_tasks"]


def test_wake_callback_errors_are_contained():
    """A failing wake callback is logged and the count still increases."""

    async def on_wake():
        raise RuntimeError("boom")

    monitor = sleep_wake.SleepWakeMonitor(on_wake)
    _run(vars(sleep_wake.SleepWakeMonitor)["_handle_wake"](monitor))
    assert monitor.wake_count == 1


def test_logind_signal_tasks_are_held_until_done():
    """PrepareForSleep handlers run as tracked tasks."""
    events = []

    async def on_wake():
        events.append("wake")

    async def on_sleep():
        events.append("sleep")

    async def scenario():
        monitor = sleep_wake.SleepWakeMonitor(on_wake, on_sleep)
        handler = vars(sleep_wake.SleepWakeMonitor)["_on_prepare_for_sleep"]
        handler(monitor, True)
        handler(monitor, False)
        assert len(vars(monitor)["_tasks"]) == 2
        await asyncio.sleep(0.01)
        return monitor

    monitor = _run(scenario())
    assert events == ["sleep", "wake"]
    assert not vars(monitor)["_tasks"]


def test_stop_propagates_cancellation_of_caller():
    """Cancelling the coroutine awaiting stop() is not swallowed."""

    async def scenario():
        monitor = sleep_wake.SleepWakeMonitor(asyncio.sleep, check_interval=60)
        monitor_tasks = vars(monitor)["_tasks"]

        async def stubborn():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                await asyncio.sleep(60)

        task = asyncio.create_task(stubborn())
        monitor_tasks.add(task)
        stopper = asyncio.create_task(monitor.stop())
        await asyncio.sleep(0.01)
        stopper.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopper
        task.cancel()

    _run(scenario())


class _Daemon(sleep_wake.SleepWakeAwareDaemon):
    def __init__(self):
        self.calls = []

    async def on_system_wake(self):
        self.calls.append("wake")
        raise ValueError("refresh failed")


def test_aware_daemon_handlers():
    """The mixin calls the hooks and contains their errors."""
    daemon = _Daemon()
    _run(vars(sleep_wake.SleepWakeAwareDaemon)["_handle_system_wake"](daemon))
    _run(vars(sleep_wake.SleepWakeAwareDaemon)["_handle_system_sleep"](daemon))
    assert daemon.calls == ["wake"]
    assert daemon.wake_count == 0


def test_robust_timer_fires_and_stops():
    """The timer fires after its interval and stops cleanly."""
    fired = []

    async def callback():
        fired.append(True)
        raise OSError("ignored")

    async def scenario():
        timer = sleep_wake.RobustTimer(0.01, callback, name="t")
        await timer.start()
        await asyncio.sleep(0.1)
        await timer.stop()
        timer.reschedule(5)

    _run(scenario())
    assert fired


def test_periodic_task_counts_missed_cycles():
    """An overdue task records missed cycles and fires immediately."""
    runs = []

    async def callback():
        runs.append(True)

    async def scenario():
        task = sleep_wake.RobustPeriodicTask(1.0, callback, name="p")
        vars(task)["_last_run_time"] = time.time() - 10_000
        vars(task)["_is_running"] = True
        loop_task = asyncio.create_task(vars(sleep_wake.RobustPeriodicTask)["_run"](task))
        await asyncio.sleep(0.01)
        await task.stop()
        await sleep_wake.asyncio.wait({loop_task})
        loop_task.cancel()
        return task

    task = _run(scenario())
    assert runs
    assert task.missed_cycles == 9_999


def test_periodic_task_run_immediately_and_stop():
    """run_immediately fires once on start; stop ends the loop."""
    runs = []

    async def callback():
        runs.append(True)

    async def scenario():
        task = sleep_wake.RobustPeriodicTask(60, callback, name="p", run_immediately=True, max_jitter=0.5)
        await task.start()
        await asyncio.sleep(0.01)
        await task.stop()
        return task

    task = _run(scenario())
    assert runs == [True]
    assert task.missed_cycles == 0
