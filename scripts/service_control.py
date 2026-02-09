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
    - slack: Slack Bot (com.aiworkflow.BotSlack)
    - cron: Cron Bot (com.aiworkflow.BotCron)
    - meet: Meet Bot (com.aiworkflow.BotMeet)
    - sprint: Sprint Bot (com.aiworkflow.BotSprint)
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
from scripts.common.dbus_base import (  # noqa: E402
    DBUS_AVAILABLE,
    check_daemon_health,
    check_daemon_status,
    get_client,
)

SERVICES = ["slack", "cron", "meet", "sprint"]


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
            elif service == "sprint":
                print(f"   Issues: {status.get('total_issues', 0)}")
                print(f"   Processed: {status.get('issues_processed', 0)}")
                print(
                    f"   Working Hours: {'Yes' if status.get('within_working_hours') else 'No'}"
                )
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


async def cmd_health(args):
    """Perform health checks on services."""
    services = [args.service] if args.service else SERVICES

    print("=" * 60)
    print("AI Workflow Services Health Check")
    print("=" * 60)
    print()

    all_healthy = True
    for service in services:
        health = await check_daemon_health(service)

        if health.get("healthy", False):
            print(f"✅ {service.upper()}: {health.get('message', 'Healthy')}")
        else:
            all_healthy = False
            print(f"❌ {service.upper()}: {health.get('message', 'Unhealthy')}")

            # Show failed checks
            checks = health.get("checks", {})
            failed = [k for k, v in checks.items() if not v]
            if failed:
                print(f"   Failed checks: {', '.join(failed)}")

        # Show additional health info
        if args.verbose:
            checks = health.get("checks", {})
            for check, passed in checks.items():
                status = "✓" if passed else "✗"
                print(f"   {status} {check}")

        print()

    # Summary
    if all_healthy:
        print("✅ All services healthy")
    else:
        print("❌ Some services unhealthy")
        if not args.no_fix:
            print("\nTip: Run with --fix to attempt automatic recovery")


async def cmd_fix(args):
    """Attempt to fix unhealthy services."""
    import subprocess
    import time

    services = [args.service] if args.service else SERVICES

    print("Checking services and attempting fixes...")
    print()

    systemd_units = {
        "slack": "bot-slack.service",
        "cron": "bot-cron.service",
        "meet": "bot-meet.service",
        "sprint": "bot-sprint.service",
    }

    for service in services:
        health = await check_daemon_health(service)

        if health.get("healthy", False):
            print(f"✅ {service.upper()}: Already healthy")
            continue

        print(f"❌ {service.upper()}: Unhealthy - {health.get('message')}")
        print("   Attempting restart...")

        unit = systemd_units.get(service)
        if not unit:
            print(f"   ⚠️  No systemd unit configured for {service}")
            continue

        try:
            # Restart the service
            subprocess.run(
                ["systemctl", "--user", "restart", unit],
                capture_output=True,
                timeout=30,
            )

            # Wait for service to start
            time.sleep(5)

            # Re-check health
            new_health = await check_daemon_health(service)
            if new_health.get("healthy", False):
                print(f"   ✅ {service.upper()}: Recovered!")
            else:
                print(
                    f"   ❌ {service.upper()}: Still unhealthy - {new_health.get('message')}"
                )
        except subprocess.TimeoutExpired:
            print("   ⚠️  Restart timed out")
        except Exception as e:
            print(f"   ⚠️  Restart failed: {e}")

        print()


async def main():
    parser = argparse.ArgumentParser(
        description="AI Workflow Service Control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # status command
    status_parser = subparsers.add_parser("status", help="Show service status")
    status_parser.add_argument(
        "service", nargs="?", choices=SERVICES, help="Service name"
    )

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
    json_parser.add_argument(
        "service", nargs="?", choices=SERVICES, help="Service name"
    )

    # health command
    health_parser = subparsers.add_parser("health", help="Perform health checks")
    health_parser.add_argument(
        "service", nargs="?", choices=SERVICES, help="Service name"
    )
    health_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Show all checks"
    )
    health_parser.add_argument(
        "--no-fix", action="store_true", help="Don't show fix tip"
    )

    # fix command
    fix_parser = subparsers.add_parser("fix", help="Attempt to fix unhealthy services")
    fix_parser.add_argument("service", nargs="?", choices=SERVICES, help="Service name")

    args = parser.parse_args()

    if not DBUS_AVAILABLE:
        print("Error: dbus-next not installed")
        print("Install with: uv add dbus-next")
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
        "health": cmd_health,
        "fix": cmd_fix,
    }

    if args.command in commands:
        await commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
