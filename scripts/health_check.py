#!/usr/bin/env python3
"""
Unified Health Check for AI Workflow Services

Performs comprehensive health checks on all AI Workflow services:
- Slack Agent
- Cron Scheduler
- Meet Bot
- MCP Server (via process check)
- Ollama instances (via HTTP)

Usage:
    python scripts/health_check.py              # Check all services
    python scripts/health_check.py --json       # JSON output
    python scripts/health_check.py --service slack  # Check specific service
    python scripts/health_check.py --fix        # Attempt to fix unhealthy services
    python scripts/health_check.py --watch      # Continuous monitoring

Exit codes:
    0 - All services healthy
    1 - One or more services unhealthy
    2 - Error running health check
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common.dbus_base import DBUS_AVAILABLE, check_daemon_health, check_daemon_status  # noqa: E402

# Services to check
DBUS_SERVICES = ["slack", "cron", "meet"]

# Ollama instances
OLLAMA_INSTANCES = [
    {"name": "npu", "port": 11434},
    {"name": "igpu", "port": 11435},
    {"name": "nvidia", "port": 11436},
    {"name": "cpu", "port": 11437},
]

# Systemd service names
SYSTEMD_SERVICES = {
    "slack": "bot-slack.service",
    "cron": "bot-cron.service",
    "meet": "bot-meet.service",
    "sprint": "bot-sprint.service",
}


def check_ollama_instance(port: int, timeout: float = 2.0) -> dict:
    """Check if Ollama instance is available and responding."""
    try:
        req = urllib.request.Request(f"http://localhost:{port}/api/tags", method="GET")
        start = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as response:
            latency = (time.time() - start) * 1000
            if response.status == 200:
                return {
                    "healthy": True,
                    "latency_ms": round(latency, 1),
                    "message": f"Responding ({latency:.0f}ms)",
                }
        return {"healthy": False, "message": f"HTTP {response.status}"}
    except urllib.error.URLError as e:
        return {"healthy": False, "message": f"Connection failed: {e.reason}"}
    except Exception as e:
        return {"healthy": False, "message": str(e)}


def check_mcp_server() -> dict:
    """Check if MCP server is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*-m server"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        pids = [p for p in result.stdout.strip().split("\n") if p]
        if pids:
            return {
                "healthy": True,
                "pid": int(pids[0]),
                "message": f"Running (PID: {pids[0]})",
            }
        return {"healthy": False, "message": "Not running"}
    except Exception as e:
        return {"healthy": False, "message": str(e)}


async def check_service_health(service: str) -> dict:
    """Check health of a D-Bus service."""
    if not DBUS_AVAILABLE:
        return {
            "healthy": False,
            "message": "D-Bus not available",
            "checks": {"dbus_available": False},
        }

    try:
        # First check if it's running
        status = await check_daemon_status(service)
        if not status.get("running", False):
            return {
                "healthy": False,
                "message": "Not running",
                "checks": {"running": False},
            }

        # Then do full health check
        health = await check_daemon_health(service)
        return health
    except Exception as e:
        return {
            "healthy": False,
            "message": f"Health check failed: {e}",
            "checks": {"exception": False},
        }


async def check_all_services(verbose: bool = False) -> dict:
    """Check health of all services."""
    results = {
        "timestamp": datetime.now().isoformat(),
        "overall_healthy": True,
        "services": {},
        "ollama": {},
        "mcp": {},
    }

    # Check D-Bus services
    for service in DBUS_SERVICES:
        if verbose:
            print(f"Checking {service}...", end=" ", flush=True)

        health = await check_service_health(service)
        results["services"][service] = health

        if not health.get("healthy", False):
            results["overall_healthy"] = False

        if verbose:
            status = "✅" if health.get("healthy") else "❌"
            print(f"{status} {health.get('message', 'Unknown')}")

    # Check MCP server
    if verbose:
        print("Checking MCP server...", end=" ", flush=True)

    mcp_health = check_mcp_server()
    results["mcp"] = mcp_health

    # MCP not running is not necessarily unhealthy (might be in Cursor)
    if verbose:
        status = "✅" if mcp_health.get("healthy") else "⚠️"
        print(f"{status} {mcp_health.get('message', 'Unknown')}")

    # Check Ollama instances
    for instance in OLLAMA_INSTANCES:
        if verbose:
            print(f"Checking Ollama {instance['name']}...", end=" ", flush=True)

        health = check_ollama_instance(instance["port"])
        results["ollama"][instance["name"]] = health

        # Ollama not running is not critical
        if verbose:
            status = "✅" if health.get("healthy") else "⚠️"
            print(f"{status} {health.get('message', 'Unknown')}")

    return results


def restart_service(service: str) -> bool:
    """Attempt to restart a systemd service."""
    unit = SYSTEMD_SERVICES.get(service)
    if not unit:
        print(f"Unknown service: {service}")
        return False

    try:
        # First try to stop
        subprocess.run(
            ["systemctl", "--user", "stop", unit],
            capture_output=True,
            timeout=10,
        )
        time.sleep(1)

        # Then start
        result = subprocess.run(
            ["systemctl", "--user", "start", unit],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Failed to restart {service}: {e}")
        return False


async def fix_unhealthy_services(results: dict, verbose: bool = False) -> dict:
    """Attempt to fix unhealthy services."""
    fixed = []
    failed = []

    for service, health in results.get("services", {}).items():
        if not health.get("healthy", False):
            if verbose:
                print(f"Attempting to restart {service}...")

            if restart_service(service):
                # Wait for service to start
                await asyncio.sleep(5)

                # Re-check health
                new_health = await check_service_health(service)
                if new_health.get("healthy", False):
                    fixed.append(service)
                    if verbose:
                        print(f"  ✅ {service} recovered")
                else:
                    failed.append(service)
                    if verbose:
                        print(f"  ❌ {service} still unhealthy: {new_health.get('message')}")
            else:
                failed.append(service)
                if verbose:
                    print(f"  ❌ Failed to restart {service}")

    return {"fixed": fixed, "failed": failed}


async def watch_services(interval: int = 30, verbose: bool = True):
    """Continuously monitor service health."""
    print(f"Watching services every {interval}s (Ctrl+C to stop)")
    print()

    try:
        while True:
            timestamp = datetime.now().strftime("%H:%M:%S")
            results = await check_all_services(verbose=False)

            # Build status line
            statuses = []
            for service in DBUS_SERVICES:
                health = results["services"].get(service, {})
                status = "✅" if health.get("healthy") else "❌"
                statuses.append(f"{service}:{status}")

            # Ollama count
            ollama_healthy = sum(1 for h in results["ollama"].values() if h.get("healthy"))
            statuses.append(f"ollama:{ollama_healthy}/4")

            overall = "✅" if results["overall_healthy"] else "❌"
            print(f"[{timestamp}] {overall} {' | '.join(statuses)}")

            # If unhealthy, show details
            if not results["overall_healthy"] and verbose:
                for service, health in results["services"].items():
                    if not health.get("healthy"):
                        print(f"  └─ {service}: {health.get('message', 'Unknown')}")

            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped watching")


def print_results(results: dict, json_output: bool = False):
    """Print health check results."""
    if json_output:
        print(json.dumps(results, indent=2, default=str))
        return

    print()
    print("=" * 60)
    print("AI Workflow Health Check")
    print(f"Time: {results['timestamp']}")
    print("=" * 60)
    print()

    # D-Bus services
    print("Services:")
    for service, health in results.get("services", {}).items():
        status = "✅" if health.get("healthy") else "❌"
        message = health.get("message", "Unknown")
        print(f"  {status} {service.upper()}: {message}")

        # Show failed checks
        if not health.get("healthy") and health.get("checks"):
            failed = [k for k, v in health["checks"].items() if not v]
            if failed:
                print(f"      Failed: {', '.join(failed)}")

    print()

    # MCP server
    print("MCP Server:")
    mcp = results.get("mcp", {})
    status = "✅" if mcp.get("healthy") else "⚠️"
    print(f"  {status} {mcp.get('message', 'Unknown')}")

    print()

    # Ollama
    print("Ollama Instances:")
    for name, health in results.get("ollama", {}).items():
        status = "✅" if health.get("healthy") else "⚠️"
        print(f"  {status} {name}: {health.get('message', 'Unknown')}")

    print()

    # Overall
    overall = "✅ All services healthy" if results["overall_healthy"] else "❌ Some services unhealthy"
    print(f"Overall: {overall}")
    print()


async def main():
    parser = argparse.ArgumentParser(
        description="AI Workflow Health Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--service",
        choices=DBUS_SERVICES + ["mcp", "ollama"],
        help="Check specific service only",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to fix unhealthy services",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuous monitoring mode",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Watch interval in seconds (default: 30)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    try:
        if args.watch:
            await watch_services(interval=args.interval, verbose=args.verbose)
            return 0

        if args.service:
            # Check specific service
            if args.service in DBUS_SERVICES:
                health = await check_service_health(args.service)
                if args.json:
                    print(json.dumps(health, indent=2, default=str))
                else:
                    status = "✅" if health.get("healthy") else "❌"
                    print(f"{status} {args.service.upper()}: {health.get('message')}")
                    if health.get("checks"):
                        for check, passed in health["checks"].items():
                            check_status = "✓" if passed else "✗"
                            print(f"  {check_status} {check}")
                return 0 if health.get("healthy") else 1
            elif args.service == "mcp":
                health = check_mcp_server()
                if args.json:
                    print(json.dumps(health, indent=2))
                else:
                    status = "✅" if health.get("healthy") else "❌"
                    print(f"{status} MCP: {health.get('message')}")
                return 0 if health.get("healthy") else 1
            elif args.service == "ollama":
                results = {}
                for inst in OLLAMA_INSTANCES:
                    results[inst["name"]] = check_ollama_instance(inst["port"])
                if args.json:
                    print(json.dumps(results, indent=2))
                else:
                    for name, health in results.items():
                        status = "✅" if health.get("healthy") else "⚠️"
                        print(f"{status} {name}: {health.get('message')}")
                return 0

        # Check all services
        results = await check_all_services(verbose=args.verbose)

        if args.fix and not results["overall_healthy"]:
            print("\nAttempting to fix unhealthy services...")
            fix_results = await fix_unhealthy_services(results, verbose=True)

            # Re-check after fixes
            results = await check_all_services(verbose=False)
            results["fix_results"] = fix_results

        print_results(results, json_output=args.json)

        return 0 if results["overall_healthy"] else 1

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print(f"Error: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
