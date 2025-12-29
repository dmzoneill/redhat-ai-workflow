#!/usr/bin/env python3
"""
Extract Slack credentials and update config.json.

Gets the xoxc_token and d_cookie needed for the Slack bot.

Usage:
    python scripts/get_slack_creds.py              # Auto-extract both credentials
    python scripts/get_slack_creds.py --dry-run    # Show values without updating config
    python scripts/get_slack_creds.py --xoxc "..." # Manually provide xoxc_token

Requirements:
    pip install pycookiecheat

Both credentials are extracted directly from Chrome's storage:
- d_cookie: From Chrome's encrypted Cookies database
- xoxc_token: From Chrome's Local Storage (LevelDB)
"""

import argparse
import json
import subprocess
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


def get_xoxc_token_from_local_storage(profile: str = "") -> str | None:
    """
    Extract xoxc_token from Chrome's Local Storage.

    Chrome stores Local Storage in LevelDB format. We use `strings` to extract
    readable text and grep for xoxc tokens.
    """
    chrome_base = Path.home() / ".config" / "google-chrome"

    # Auto-detect profile if not specified
    profiles_to_try = [profile] if profile else ["Profile 1", "Default", "Profile 2", "Profile 3"]

    for prof in profiles_to_try:
        local_storage_dir = chrome_base / prof / "Local Storage" / "leveldb"
        if not local_storage_dir.exists():
            continue

        try:
            # Use strings + grep to extract xoxc tokens from LevelDB files
            # This is simpler than parsing LevelDB and works reliably
            result = subprocess.run(
                f'strings "{local_storage_dir}"/*.ldb 2>/dev/null | grep -oE "xoxc-[a-zA-Z0-9_-]{{50,}}"',
                shell=True,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0 and result.stdout.strip():
                # Get unique tokens, prefer the most recent (last in file)
                tokens = result.stdout.strip().split("\n")
                # Filter valid tokens (should be ~100+ chars)
                valid_tokens = [t for t in tokens if len(t) > 80]
                if valid_tokens:
                    # Return the last (most recent) token
                    token = valid_tokens[-1]
                    print(f"📁 Found xoxc_token in Chrome profile: {prof}")
                    return token

        except Exception as e:
            print(f"⚠️  Error reading Local Storage from {prof}: {e}")
            continue

    return None


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
  python scripts/get_slack_creds.py              # Auto-extract both credentials
  python scripts/get_slack_creds.py --dry-run    # Show what would be updated
  python scripts/get_slack_creds.py --xoxc "..." # Manually provide xoxc_token
        """,
    )
    parser.add_argument(
        "--profile",
        "-p",
        default="",
        help="Chrome profile name (e.g., 'Profile 1'). Auto-detected if not specified.",
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
        help="Manually provide xoxc_token value (overrides auto-detection)",
    )
    args = parser.parse_args()

    print("🔍 Extracting Slack credentials from Chrome...")
    print()

    # Step 1: Get d_cookie from Chrome's Cookies database
    d_cookie = get_d_cookie_from_chrome(args.profile)

    if not d_cookie:
        print("❌ Could not find d_cookie")
        print("   Make sure you're logged into Slack in Chrome")
        sys.exit(1)

    print(f"   d_cookie: {d_cookie[:40]}...")
    print()

    # Step 2: Get xoxc_token from Chrome's Local Storage or manual input
    xoxc_token = args.xoxc if args.xoxc else None

    if not xoxc_token:
        # Try to extract from Chrome's Local Storage
        xoxc_token = get_xoxc_token_from_local_storage(args.profile)

    if not xoxc_token:
        print("⚠️  Could not find xoxc_token in Local Storage")
        print("   This can happen if you haven't used Slack recently.")
        print()
        print("   Options:")
        print("   1. Open Slack in Chrome, do any action, then run this script again")
        print("   2. Provide manually: --xoxc 'xoxc-...'")
        print()
        # Still update d_cookie
        update_config(d_cookie, None, args.dry_run)
        return

    print(f"   xoxc_token: {xoxc_token[:40]}...")
    print()

    # Step 3: Update config.json
    update_config(d_cookie, xoxc_token, args.dry_run)


if __name__ == "__main__":
    main()
