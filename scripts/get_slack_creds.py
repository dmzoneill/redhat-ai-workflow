#!/usr/bin/env python3
"""
Extract Slack credentials and update config.json.

Gets the xoxc_token and d_cookie needed for the Slack bot.

Usage:
    python scripts/get_slack_creds.py              # Get d_cookie, prompt for xoxc
    python scripts/get_slack_creds.py --capture    # Auto-capture both (opens browser)
    python scripts/get_slack_creds.py --dry-run    # Show values without updating config

Requirements:
    pip install pycookiecheat
    pip install playwright && playwright install chromium  # For --capture mode
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import unquote

# Find project root (where config.json lives)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

# Slack URL
SLACK_URL = "https://redhat.enterprise.slack.com"

# Try pycookiecheat for Chrome cookie extraction
try:
    from pycookiecheat import chrome_cookies

    HAS_PYCOOKIECHEAT = True
except ImportError:
    HAS_PYCOOKIECHEAT = False

# Try playwright for browser automation
try:
    from playwright.async_api import async_playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


def get_d_cookie_from_chrome(profile: str = "") -> str | None:
    """Get the d cookie from Chrome's cookie storage."""
    if not HAS_PYCOOKIECHEAT:
        print("❌ Missing: pip install pycookiecheat")
        return None

    chrome_base = Path.home() / ".config" / "google-chrome"

    # Auto-detect profile if not specified
    profiles_to_try = [profile] if profile else ["Profile 1", "Default", "Profile 2", "Profile 3"]

    for prof in profiles_to_try:
        cookie_file = chrome_base / prof / "Cookies"
        if not cookie_file.exists():
            continue

        try:
            result = chrome_cookies(SLACK_URL, cookie_file=str(cookie_file))
            if "d" in result:
                print(f"📁 Found d_cookie in Chrome profile: {prof}")
                return unquote(result["d"])
        except Exception as e:
            print(f"⚠️  Error reading {prof}: {e}")
            continue

    return None


def check_chrome_debugging_port() -> int | None:
    """Check if Chrome is running with remote debugging enabled."""
    import socket

    for port in [9222, 9223, 9224]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                result = s.connect_ex(("127.0.0.1", port))
                if result == 0:
                    return port
        except Exception:
            pass
    return None


async def capture_xoxc_token_playwright() -> str | None:
    """
    Capture xoxc_token by connecting to existing Chrome browser.

    Requires Chrome to be running with --remote-debugging-port=9222
    """
    if not HAS_PLAYWRIGHT:
        print("❌ Missing: pip install playwright && playwright install chromium")
        return None

    # Check if Chrome has debugging enabled
    debug_port = check_chrome_debugging_port()

    if not debug_port:
        print("❌ Chrome is not running with remote debugging enabled.")
        print()
        print("   To enable, restart Chrome with this flag:")
        print()
        print("   google-chrome --remote-debugging-port=9222")
        print()
        print("   Or add to your Chrome desktop shortcut/launcher.")
        print("   Then run this script again with --capture")
        return None

    print(f"🌐 Connecting to existing Chrome on port {debug_port}...")

    xoxc_token = None

    async with async_playwright() as p:
        try:
            # Connect to existing Chrome instance
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}")
            print("✅ Connected to Chrome")

            # Get existing contexts (browser windows)
            contexts = browser.contexts
            if not contexts:
                print("❌ No browser windows found")
                return None

            # Find a Slack tab or create one
            slack_page = None
            for context in contexts:
                for page in context.pages:
                    if "slack.com" in page.url:
                        slack_page = page
                        print(f"   Found Slack tab: {page.url[:50]}...")
                        break
                if slack_page:
                    break

            if not slack_page:
                # Open Slack in a new tab
                print("   Opening Slack in new tab...")
                slack_page = await contexts[0].new_page()
                await slack_page.goto(SLACK_URL, wait_until="networkidle")

            # Intercept requests to capture xoxc_token
            async def handle_request(request):
                nonlocal xoxc_token
                if xoxc_token:
                    return

                # Check POST requests to Slack API
                if request.method == "POST" and "slack.com/api" in request.url:
                    try:
                        post_data = request.post_data
                        if post_data and "token" in str(post_data):
                            # Try to parse as JSON
                            try:
                                data = json.loads(post_data)
                                if isinstance(data, dict) and str(data.get("token", "")).startswith("xoxc-"):
                                    xoxc_token = data["token"]
                                    print(f"✅ Captured xoxc_token: {xoxc_token[:30]}...")
                            except json.JSONDecodeError:
                                # Try form data
                                post_str = str(post_data)
                                if "token=xoxc-" in post_str:
                                    for part in post_str.split("&"):
                                        if part.startswith("token=xoxc-"):
                                            xoxc_token = unquote(part.split("=", 1)[1])
                                            print(f"✅ Captured xoxc_token: {xoxc_token[:30]}...")
                                            break
                    except Exception:
                        pass

            slack_page.on("request", handle_request)

            # Trigger some activity
            print("   Waiting for xoxc_token...")
            print("   👆 Click something in the Slack tab to trigger an API request")

            # Wait for token capture
            for _ in range(60):  # 60 second timeout
                if xoxc_token:
                    break
                await asyncio.sleep(1)

            if not xoxc_token:
                print("   ⏳ Timeout - no token captured")
                print("   Make sure you clicked in the Slack browser tab")

            # Don't close the browser - it's the user's existing session
            browser.close()

        except Exception as e:
            print(f"❌ Error connecting to Chrome: {e}")
            return None

    return xoxc_token


def load_config() -> dict:
    """Load existing config.json."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def save_config(config: dict):
    """Save config.json with proper formatting."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def update_config(d_cookie: str | None, xoxc_token: str | None, dry_run: bool = False):
    """Update config.json with the new credentials."""
    config = load_config()

    # Ensure slack section exists
    if "slack" not in config:
        config["slack"] = {}

    updated = False

    if d_cookie:
        if config["slack"].get("d_cookie") != d_cookie:
            config["slack"]["d_cookie"] = d_cookie
            updated = True
            print("✅ Updated d_cookie in config.json")

    if xoxc_token:
        if config["slack"].get("xoxc_token") != xoxc_token:
            config["slack"]["xoxc_token"] = xoxc_token
            updated = True
            print("✅ Updated xoxc_token in config.json")

    if updated:
        if dry_run:
            print("\n🔍 DRY RUN - would update config.json with:")
            print(f"   d_cookie: {d_cookie[:30] if d_cookie else 'None'}...")
            print(f"   xoxc_token: {xoxc_token[:30] if xoxc_token else 'None'}...")
        else:
            save_config(config)
            print(f"\n💾 Saved to {CONFIG_FILE}")
    else:
        print("\n✓ Config already up to date")


def main():
    parser = argparse.ArgumentParser(
        description="Extract Slack credentials and update config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/get_slack_creds.py              # Get d_cookie from Chrome
  python scripts/get_slack_creds.py --capture    # Auto-capture both (opens browser)
  python scripts/get_slack_creds.py --dry-run    # Show what would be updated
        """,
    )
    parser.add_argument(
        "--profile",
        "-p",
        default="",
        help="Chrome profile name (e.g., 'Profile 1'). Auto-detected if not specified.",
    )
    parser.add_argument(
        "--capture",
        "-c",
        action="store_true",
        help="Open browser to auto-capture xoxc_token",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show values without updating config.json",
    )
    parser.add_argument(
        "--xoxc",
        "-x",
        default="",
        help="Manually provide xoxc_token value",
    )
    args = parser.parse_args()

    print("🔍 Extracting Slack credentials...")
    print()

    # Step 1: Get d_cookie from Chrome
    d_cookie = get_d_cookie_from_chrome(args.profile)

    if not d_cookie:
        print("❌ Could not find d_cookie")
        print("   Make sure you're logged into Slack in Chrome")
        sys.exit(1)

    print(f"   d_cookie: {d_cookie[:40]}...")
    print()

    # Step 2: Get xoxc_token
    xoxc_token = args.xoxc if args.xoxc else None

    if args.capture and not xoxc_token:
        # Auto-capture using browser
        xoxc_token = asyncio.run(capture_xoxc_token_playwright())
    elif not xoxc_token:
        # Check if we already have one in config
        config = load_config()
        existing = config.get("slack", {}).get("xoxc_token", "")
        if existing:
            print(f"ℹ️  Using existing xoxc_token from config: {existing[:30]}...")
            xoxc_token = existing
        else:
            print("ℹ️  No xoxc_token provided. Options:")
            print("   1. Run with --capture to auto-capture")
            print("   2. Run with --xoxc 'xoxc-...' to provide manually")
            print()
            # Still update d_cookie
            update_config(d_cookie, None, args.dry_run)
            return

    # Step 3: Update config.json
    update_config(d_cookie, xoxc_token, args.dry_run)


if __name__ == "__main__":
    main()
