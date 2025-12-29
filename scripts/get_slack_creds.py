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


async def capture_xoxc_token_playwright() -> str | None:
    """
    Open browser and capture xoxc_token from Slack API requests.

    Uses Chrome's user data directory so you're already logged in.
    """
    if not HAS_PLAYWRIGHT:
        print("❌ Missing: pip install playwright && playwright install chromium")
        return None

    print("🌐 Opening browser to capture xoxc_token...")
    print("   (Slack should load with your existing login)")

    xoxc_token = None

    async with async_playwright() as p:
        # Launch with persistent context (uses Chrome profile)
        chrome_user_data = Path.home() / ".config" / "google-chrome"

        # Find the profile with Slack cookies
        profile_dir = None
        for prof in ["Profile 1", "Default", "Profile 2"]:
            if (chrome_user_data / prof / "Cookies").exists():
                profile_dir = prof
                break

        if not profile_dir:
            print("❌ No Chrome profile found")
            return None

        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(chrome_user_data),
            channel="chrome",
            headless=False,
            args=[f"--profile-directory={profile_dir}"],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        # Intercept requests to capture xoxc_token
        async def handle_request(request):
            nonlocal xoxc_token
            if xoxc_token:
                return

            # Check POST requests to Slack API
            if request.method == "POST" and "slack.com/api" in request.url:
                try:
                    post_data = request.post_data
                    if post_data and "token" in post_data:
                        # Try to parse as JSON
                        try:
                            data = json.loads(post_data)
                            if isinstance(data, dict) and data.get("token", "").startswith("xoxc-"):
                                xoxc_token = data["token"]
                                print(f"✅ Captured xoxc_token: {xoxc_token[:30]}...")
                        except json.JSONDecodeError:
                            # Try form data
                            if "token=xoxc-" in post_data:
                                for part in post_data.split("&"):
                                    if part.startswith("token=xoxc-"):
                                        xoxc_token = unquote(part.split("=", 1)[1])
                                        print(f"✅ Captured xoxc_token: {xoxc_token[:30]}...")
                                        break
                except Exception:
                    pass

        page.on("request", handle_request)

        # Navigate to Slack
        print(f"   Navigating to {SLACK_URL}...")
        await page.goto(SLACK_URL, wait_until="networkidle")

        # Wait for token capture or timeout
        print("   Waiting for xoxc_token (interact with Slack if needed)...")
        for _ in range(30):  # 30 second timeout
            if xoxc_token:
                break
            await asyncio.sleep(1)

        if not xoxc_token:
            print("   ⏳ No token captured yet. Click around in Slack...")
            for _ in range(30):  # Another 30 seconds
                if xoxc_token:
                    break
                await asyncio.sleep(1)

        await context.close()

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
