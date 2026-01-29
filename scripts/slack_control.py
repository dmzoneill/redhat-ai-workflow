#!/usr/bin/env python3
"""
Slack Daemon Control CLI

Command-line tool for controlling the Slack daemon via D-Bus.

Usage:
    slack_control.py status           - Get daemon status
    slack_control.py pending          - List pending approvals
    slack_control.py approve <id>     - Approve a message
    slack_control.py approve-all      - Approve all pending
    slack_control.py reject <id>      - Reject a message
    slack_control.py history [--limit N] [--channel C] [--user U]
    slack_control.py send <channel> <message>
    slack_control.py reload           - Reload config
    slack_control.py stop             - Stop the daemon
    slack_control.py start            - Start daemon in background
    slack_control.py watch            - Watch for new messages (live)
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

if TYPE_CHECKING:
    from slack_dbus import SlackAgentClient

# Colors for terminal output
COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
}


def print_header(title: str):
    """Print a section header."""
    print(f"\n{COLORS['cyan']}{COLORS['bold']}{'━' * 60}{COLORS['reset']}")
    print(f"{COLORS['cyan']}{COLORS['bold']}{title}{COLORS['reset']}")
    print(f"{COLORS['cyan']}{'━' * 60}{COLORS['reset']}")


def print_success(msg: str):
    print(f"{COLORS['green']}✅ {msg}{COLORS['reset']}")


def print_error(msg: str):
    print(f"{COLORS['red']}❌ {msg}{COLORS['reset']}")


def print_warning(msg: str):
    print(f"{COLORS['yellow']}⚠️  {msg}{COLORS['reset']}")


def format_timestamp(ts: float) -> str:
    """Format a timestamp for display."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def format_message(msg: dict, verbose: bool = False) -> str:
    """Format a message for display."""
    status_colors = {
        "pending": COLORS["yellow"],
        "approved": COLORS["green"],
        "rejected": COLORS["red"],
        "sent": COLORS["green"],
        "skipped": COLORS["dim"],
    }

    status = msg.get("status", "unknown")
    status_color = status_colors.get(status, COLORS["reset"])

    output = f"""
{COLORS['bold']}ID:{COLORS['reset']} {msg.get('id', 'N/A')[:20]}...
{COLORS['bold']}Channel:{COLORS['reset']} #{msg.get('channel_name', 'unknown')}
{COLORS['bold']}From:{COLORS['reset']} {msg.get('user_name', 'unknown')} ({msg.get('classification', 'unknown')})
{COLORS['bold']}Intent:{COLORS['reset']} {msg.get('intent', 'unknown')}
{COLORS['bold']}Status:{COLORS['reset']} {status_color}{status}{COLORS['reset']}
{COLORS['bold']}Text:{COLORS['reset']} {msg.get('text', '')[:100]}{'...' if len(msg.get('text', '')) > 100 else ''}
"""

    if verbose and msg.get("response"):
        output += f"{COLORS['bold']}Response:{COLORS['reset']} {msg.get('response', '')[:200]}...\n"

    return output


async def cmd_status(client: SlackAgentClient, args):
    """Get daemon status."""
    status = await client.get_status()

    print_header("Slack Daemon Status")

    running = status.get("running", False)
    if running:
        print_success("Daemon is running")
    else:
        print_error("Daemon is not running")
        return

    uptime = status.get("uptime", 0)
    hours, remainder = divmod(int(uptime), 3600)
    minutes, seconds = divmod(remainder, 60)

    print(
        f"""
{COLORS['bold']}Uptime:{COLORS['reset']} {hours:02d}:{minutes:02d}:{seconds:02d}
{COLORS['bold']}Messages Processed:{COLORS['reset']} {status.get('messages_processed', 0)}
{COLORS['bold']}Messages Responded:{COLORS['reset']} {status.get('messages_responded', 0)}
{COLORS['bold']}Pending Approvals:{COLORS['reset']} {status.get('pending_approvals', 0)}
"""
    )


async def cmd_pending(client: SlackAgentClient, args):
    """List pending approval messages."""
    pending = await client.get_pending()

    print_header(f"Pending Approvals ({len(pending)})")

    if not pending:
        print_warning("No messages pending approval")
        return

    for msg in pending:
        print(format_message(msg, verbose=args.verbose))
        print(f"{COLORS['dim']}{'─' * 40}{COLORS['reset']}")

    print(
        f"""
{COLORS['bold']}To approve:{COLORS['reset']} slack_control.py approve <id>
{COLORS['bold']}To approve all:{COLORS['reset']} slack_control.py approve-all
{COLORS['bold']}To reject:{COLORS['reset']} slack_control.py reject <id>
"""
    )


async def cmd_approve(client: SlackAgentClient, args):
    """Approve a pending message."""
    result = await client.approve(args.message_id)

    if result.get("success"):
        print_success(f"Approved and sent message {args.message_id[:20]}...")
    else:
        print_error(f"Failed to approve: {result.get('error', 'Unknown error')}")


async def cmd_approve_all(client: SlackAgentClient, args):
    """Approve all pending messages."""
    result = await client.approve_all()

    total = result.get("total", 0)
    approved = result.get("approved", 0)
    failed = result.get("failed", 0)

    print_header("Approve All Results")
    print(
        f"""
{COLORS['bold']}Total:{COLORS['reset']} {total}
{COLORS['green']}Approved:{COLORS['reset']} {approved}
{COLORS['red']}Failed:{COLORS['reset']} {failed}
"""
    )


async def cmd_reject(client: SlackAgentClient, args):
    """Reject a pending message."""
    result = await client.reject(args.message_id)

    if result.get("success"):
        print_success(f"Rejected message {args.message_id[:20]}...")
    else:
        print_error(f"Failed to reject: {result.get('error', 'Unknown error')}")


async def cmd_history(client: SlackAgentClient, args):
    """Get message history."""
    history = await client.get_history(
        limit=args.limit,
        channel_id=args.channel or "",
        user_id=args.user or "",
        status=args.status or "",
    )

    print_header(f"Message History ({len(history)} messages)")

    if not history:
        print_warning("No messages in history")
        return

    for msg in history:
        print(format_message(msg, verbose=args.verbose))
        print(f"{COLORS['dim']}{'─' * 40}{COLORS['reset']}")


async def cmd_send(client: SlackAgentClient, args):
    """Send a message to Slack channel or user."""
    target = args.target

    # Show what we're doing
    if target.startswith("U"):
        print(f"{COLORS['cyan']}Sending DM to user {target}...{COLORS['reset']}")
    elif target.startswith("@"):
        print(f"{COLORS['cyan']}Sending DM to {target}...{COLORS['reset']}")
    elif target.startswith("D"):
        print(f"{COLORS['cyan']}Sending to DM channel {target}...{COLORS['reset']}")
    else:
        print(f"{COLORS['cyan']}Sending to channel {target}...{COLORS['reset']}")

    result = await client.send_message(
        channel_id=target,  # The daemon will handle user IDs
        text=args.message,
        thread_ts=args.thread or "",
    )

    if result.get("success"):
        msg_type = result.get("type", "message")
        if msg_type == "dm":
            print_success(f"DM sent (ts: {result.get('ts', 'N/A')})")
        else:
            print_success(f"Message sent (ts: {result.get('ts', 'N/A')})")
    else:
        print_error(f"Failed to send: {result.get('error', 'Unknown error')}")


async def cmd_reload(client: SlackAgentClient, args):
    """Reload daemon configuration."""
    result = await client.reload_config()

    if result.get("success"):
        print_success("Configuration reloaded")
    else:
        print_error(f"Failed to reload: {result.get('error', 'Unknown error')}")


async def cmd_stop(client: SlackAgentClient, args):
    """Stop the daemon."""
    result = await client.shutdown()

    if result.get("success"):
        print_success("Shutdown initiated")
    else:
        print_error(f"Failed to shutdown: {result.get('error', 'Unknown error')}")


def cmd_start(args):
    """Start the daemon in background."""
    daemon_script = PROJECT_ROOT / "scripts" / "slack_daemon.py"
    log_file = Path.home() / ".config" / "aa-workflow" / "slack_daemon.log"
    pid_file = Path("/tmp/slack-daemon.pid")

    # Check if already running
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)  # Check if process exists
            print_warning(f"Daemon already running (PID: {pid})")
            return
        except (OSError, ValueError):
            pid_file.unlink(missing_ok=True)

    # Start daemon
    print(f"{COLORS['cyan']}Starting Slack daemon...{COLORS['reset']}")

    cmd = [
        "nohup",
        sys.executable,
        str(daemon_script),
        "--dbus",  # Enable D-Bus
    ]

    if args.verbose:
        cmd.append("--verbose")
    if args.llm:
        cmd.append("--llm")

    with open(log_file, "w") as log:
        process = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )

    pid_file.write_text(str(process.pid))

    # Wait a moment and check if it started
    time.sleep(2)

    try:
        os.kill(process.pid, 0)
        print_success(f"Daemon started (PID: {process.pid})")
        print(f"  Logs: {log_file}")
        print("  Stop: slack_control.py stop")
    except OSError:
        print_error("Daemon failed to start. Check logs:")
        print(f"  tail -f {log_file}")


async def cmd_watch(client: SlackAgentClient, args):
    """Watch for new messages in real-time."""
    print_header("Watching for Messages (Ctrl+C to stop)")

    last_count = 0

    try:
        while True:
            try:
                status = await client.get_status()
                pending = await client.get_pending()

                current_count = len(pending)
                if current_count > last_count:
                    # New pending messages
                    n = current_count - last_count
                    new_messages = pending[-n:]
                    for msg in new_messages:
                        print(f"\n{COLORS['yellow']}🔔 NEW MESSAGE{COLORS['reset']}")
                        print(format_message(msg))

                last_count = current_count

                # Update status line
                print(
                    f"\r{COLORS['dim']}[{datetime.now().strftime('%H:%M:%S')}] "
                    f"Processed: {status.get('messages_processed', 0)} | "
                    f"Pending: {current_count}{COLORS['reset']}",
                    end="",
                    flush=True,
                )

            except Exception as e:
                print(f"\r{COLORS['red']}Connection lost: {e}{COLORS['reset']}")
                print("Attempting to reconnect...")
                await asyncio.sleep(5)
                await client.connect()

            await asyncio.sleep(2)

    except KeyboardInterrupt:
        print(f"\n\n{COLORS['cyan']}Stopped watching{COLORS['reset']}")


async def main_async(args, cmd_func):
    """Run async command."""
    from slack_dbus import SlackAgentClient

    client = SlackAgentClient()

    if not await client.connect():
        return 1

    try:
        await cmd_func(client, args)
        return 0
    finally:
        await client.disconnect()


def main():
    from slack_dbus import DBUS_AVAILABLE

    parser = argparse.ArgumentParser(
        description="Slack Daemon Control CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # status
    subparsers.add_parser("status", help="Get daemon status")

    # pending
    pending_parser = subparsers.add_parser("pending", help="List pending approvals")
    pending_parser.add_argument("-v", "--verbose", action="store_true")

    # approve
    approve_parser = subparsers.add_parser("approve", help="Approve a message")
    approve_parser.add_argument("message_id", help="Message ID to approve")

    # approve-all
    subparsers.add_parser("approve-all", help="Approve all pending messages")

    # reject
    reject_parser = subparsers.add_parser("reject", help="Reject a message")
    reject_parser.add_argument("message_id", help="Message ID to reject")

    # history
    history_parser = subparsers.add_parser("history", help="Get message history")
    history_parser.add_argument("-n", "--limit", type=int, default=50)
    history_parser.add_argument("-c", "--channel", help="Filter by channel ID")
    history_parser.add_argument("-u", "--user", help="Filter by user ID")
    history_parser.add_argument("-s", "--status", help="Filter by status")
    history_parser.add_argument("-v", "--verbose", action="store_true")

    # send
    send_parser = subparsers.add_parser(
        "send",
        help="Send a message to channel or user",
        description="Send to channel (C123), DM channel (D123), user (U123), or @username",
    )
    send_parser.add_argument(
        "target",
        help="Target: Channel (C123), User ID (U123), or @username",
    )
    send_parser.add_argument("message", help="Message text")
    send_parser.add_argument("-t", "--thread", help="Thread timestamp")

    # reload
    subparsers.add_parser("reload", help="Reload configuration")

    # stop
    subparsers.add_parser("stop", help="Stop the daemon")

    # start
    start_parser = subparsers.add_parser("start", help="Start daemon in background")
    start_parser.add_argument("-v", "--verbose", action="store_true")
    start_parser.add_argument("--llm", action="store_true", help="Enable LLM")

    # watch
    subparsers.add_parser("watch", help="Watch for new messages")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if not DBUS_AVAILABLE and args.command not in ["start"]:
        print_error("dbus-next not installed. Install with: pip install dbus-next")
        return 1

    # Commands that don't need D-Bus connection
    if args.command == "start":
        cmd_start(args)
        return 0

    # Async commands
    cmd_map = {
        "status": cmd_status,
        "pending": cmd_pending,
        "approve": cmd_approve,
        "approve-all": cmd_approve_all,
        "reject": cmd_reject,
        "history": cmd_history,
        "send": cmd_send,
        "reload": cmd_reload,
        "stop": cmd_stop,
        "watch": cmd_watch,
    }

    if args.command in cmd_map:
        return asyncio.run(main_async(args, cmd_map[args.command]))

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
