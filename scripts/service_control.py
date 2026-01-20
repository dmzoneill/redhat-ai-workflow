#!/usr/bin/env python3
"""
Service Control for AI Workflow Daemons

Unified control interface for all AI Workflow services via D-Bus.

Usage:
    python scripts/service_control.py status              # All services
    python scripts/service_control.py status cron         # Specific service
    python scripts/service_control.py stop slack          # Stop a service
    python scripts/service_control.py run-job hello_world # Run a cron job

Services:
    - slack: Slack Agent (com.aiworkflow.SlackAgent)
    - cron: Cron Scheduler (com.aiworkflow.CronScheduler)
    - meet: Meet Bot (com.aiworkflow.MeetBot)
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path - must be before local imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Local imports after path setup
from scripts.common.dbus_base import DBUS_AVAILABLE, check_daemon_status, get_client  # noqa: E402

SERVICES = ["slack", "cron", "meet"]


def format_uptime(seconds: float) -> str:
    """Format uptime in human-readable form."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds / 60:.0f}m"
    elif seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    else:
        return f"{seconds / 86400:.1f}d"


async def cmd_status(args):
    """Show status of services."""
    services = [args.service] if args.service else SERVICES

    print("=" * 60)
    print("AI Workflow Services Status")
    print("=" * 60)
    print()

    for service in services:
        status = await check_daemon_status(service)

        if status.get("running", False):
            uptime = format_uptime(status.get("uptime", 0))
            print(f"✅ {service.upper()}: Running ({uptime})")

            # Service-specific details
            if service == "cron":
                print(f"   Jobs: {status.get('job_count', 0)}")
                print(f"   Executed: {status.get('jobs_executed', 0)}")
                print(f"   Mode: {status.get('execution_mode', 'unknown')}")
            elif service == "meet":
                print(f"   Current: {status.get('current_meeting', 'None')}")
                print(f"   Upcoming: {status.get('upcoming_count', 0)}")
            elif service == "slack":
                print(f"   Messages: {status.get('messages_processed', 0)}")
                print(f"   Pending: {status.get('pending_approvals', 0)}")
        else:
            error = status.get("error", "Not running")
            print(f"❌ {service.upper()}: {error}")

        print()


async def cmd_stop(args):
    """Stop a service."""
    if not args.service:
        print("Error: service name required")
        return

    client = get_client(args.service)
    if await client.connect():
        result = await client.shutdown()
        await client.disconnect()
        if result.get("success"):
            print(f"✅ {args.service.upper()}: Shutdown initiated")
        else:
            print(f"❌ {args.service.upper()}: {result.get('error', 'Unknown error')}")
    else:
        print(f"❌ {args.service.upper()}: Not running or D-Bus not available")


async def cmd_run_job(args):
    """Run a cron job immediately."""
    if not args.job_name:
        print("Error: job name required")
        return

    client = get_client("cron")
    if await client.connect():
        result = await client.call_method("run_job", [args.job_name])
        await client.disconnect()
        if result.get("success"):
            print(f"✅ Job '{args.job_name}' started")
        else:
            print(f"❌ Failed: {result.get('error', 'Unknown error')}")
    else:
        print("❌ Cron scheduler not running")


async def cmd_list_jobs(args):
    """List cron jobs."""
    client = get_client("cron")
    if await client.connect():
        result = await client.call_method("list_jobs", [])
        await client.disconnect()

        jobs = result.get("jobs", [])
        if jobs:
            print("📋 Scheduled Jobs:")
            print()
            for job in jobs:
                print(f"   {job['name']}")
                print(f"      Next run: {job.get('next_run', 'Unknown')}")
                print()
        else:
            print("No jobs scheduled")
    else:
        print("❌ Cron scheduler not running")


async def cmd_list_meetings(args):
    """List upcoming meetings."""
    client = get_client("meet")
    if await client.connect():
        result = await client.call_method("list_meetings", [])
        await client.disconnect()

        meetings = result.get("meetings", [])
        if meetings:
            print("📅 Upcoming Meetings:")
            print()
            for meeting in meetings:
                status_icon = {
                    "scheduled": "📅",
                    "joining": "🔄",
                    "active": "🎥",
                    "completed": "✅",
                    "skipped": "⏭️",
                }.get(meeting.get("status"), "❓")
                print(f"   {status_icon} {meeting['title']}")
                print(f"      Start: {meeting['start']}")
                print(f"      Status: {meeting['status']}")
                print()
        else:
            print("No upcoming meetings")
    else:
        print("❌ Meet bot not running")


async def cmd_json(args):
    """Output raw JSON status for all services."""
    services = [args.service] if args.service else SERVICES
    result = {}

    for service in services:
        status = await check_daemon_status(service)
        result[service] = status

    print(json.dumps(result, indent=2, default=str))


async def main():
    parser = argparse.ArgumentParser(
        description="AI Workflow Service Control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # status command
    status_parser = subparsers.add_parser("status", help="Show service status")
    status_parser.add_argument("service", nargs="?", choices=SERVICES, help="Service name")

    # stop command
    stop_parser = subparsers.add_parser("stop", help="Stop a service")
    stop_parser.add_argument("service", choices=SERVICES, help="Service to stop")

    # run-job command
    run_job_parser = subparsers.add_parser("run-job", help="Run a cron job immediately")
    run_job_parser.add_argument("job_name", help="Job name to run")

    # list-jobs command
    subparsers.add_parser("list-jobs", help="List cron jobs")

    # list-meetings command
    subparsers.add_parser("list-meetings", help="List upcoming meetings")

    # json command
    json_parser = subparsers.add_parser("json", help="Output raw JSON status")
    json_parser.add_argument("service", nargs="?", choices=SERVICES, help="Service name")

    args = parser.parse_args()

    if not DBUS_AVAILABLE:
        print("Error: dbus-next not installed")
        print("Install with: pip install dbus-next")
        sys.exit(1)

    if not args.command:
        # Default to status
        args.command = "status"
        args.service = None

    commands = {
        "status": cmd_status,
        "stop": cmd_stop,
        "run-job": cmd_run_job,
        "list-jobs": cmd_list_jobs,
        "list-meetings": cmd_list_meetings,
        "json": cmd_json,
    }

    if args.command in commands:
        await commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
