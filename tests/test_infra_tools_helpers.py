"""Tests for infra_tools lock and diagnosis helpers."""

import asyncio

import pytest

from tool_modules.aa_workflow.src import infra_tools


def test_exclusive_lock_does_not_block_event_loop(tmp_path):
    """Waiting for a held file lock leaves the event loop free."""
    lock_path = tmp_path / "x.lock"
    lock = vars(infra_tools)["_exclusive_lock"]
    order = []

    async def second():
        async with lock(lock_path, "test"):
            order.append("second")

    async def scenario():
        async with lock(lock_path, "test"):
            waiter = asyncio.create_task(second())
            await asyncio.sleep(0.05)
            order.append("loop-free")
        await asyncio.wait_for(waiter, timeout=5)

    asyncio.run(scenario())
    assert order == ["loop-free", "second"]


@pytest.mark.parametrize(
    ("err", "expected"),
    [
        ("error: Unauthorized", "**Issue:** Token is invalid or expired"),
        ("403 Forbidden", "**Issue:** Token valid but lacks permissions"),
        ("dial tcp: connection refused", "**Issue:** Cannot reach cluster API"),
        ("x509: certificate signed by unknown authority", "**Issue:** TLS certificate error"),
        ("weird", "**Error:** weird"),
        ("", "**Error:** Unknown"),
    ],
)
def test_diagnose_kube_error(err, expected):
    """Connection test failures are explained by their error text."""
    assert vars(infra_tools)["_diagnose_kube_error"]("s", err, "")[0] == expected


def test_safe_state_path_allows_temp_and_home(tmp_path, monkeypatch):
    """Configured state paths under temp or home are accepted."""
    monkeypatch.setenv("HOME", str(tmp_path))
    safe = vars(infra_tools)["_safe_state_path"]
    assert safe(str(tmp_path / "state")) == (tmp_path / "state").resolve()
    assert safe("~/x.lock") == (tmp_path / "x.lock").resolve()


def test_safe_state_path_rejects_outside(tmp_path, monkeypatch):
    """Configured state paths elsewhere are rejected."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert vars(infra_tools)["_safe_state_path"]("/etc/passwd") is None
