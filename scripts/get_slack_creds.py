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
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

# Find project root (where config.json lives)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"

# Add scripts/common to path for shared utilities - must be before imports
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "common"))

# Try pycookiecheat for Chrome cookie extraction
try:
    from pycookiecheat import chrome_cookies

    HAS_PYCOOKIECHEAT = True
except ImportError:
    HAS_PYCOOKIECHEAT = False


def get_slack_url() -> str:
    """Get Slack URL from config or default."""
    from config_loader import load_config

    config = load_config()
    host = config.get("slack", {}).get("auth", {}).get("host", "")
    if host:
        return f"https://{host}"
    return "https://slack.com"


def get_chrome_settings() -> tuple[Path, list[str]]:
    """Get Chrome user data dir and profiles from config."""
    from config_loader import load_config

    config = load_config()
    creds_config = config.get("slack", {}).get("credentials_extraction", {})

    # Chrome user data directory
    chrome_dir = creds_config.get("chrome_user_data_dir", "~/.config/google-chrome")
    chrome_base = Path(chrome_dir).expanduser()

    # Profiles to try (in order)
    profiles = creds_config.get("chrome_profiles", ["Profile 1", "Default", "Profile 2", "Profile 3"])

    return chrome_base, profiles


def get_d_cookie_from_chrome(profile: str = "") -> str | None:
    """Get the d cookie from Chrome's cookie storage."""
    if not HAS_PYCOOKIECHEAT:
        print("❌ Missing: pip install pycookiecheat")
        return None

    chrome_base, default_profiles = get_chrome_settings()
    slack_url = get_slack_url()

    # Auto-detect profile if not specified
    profiles_to_try = [profile] if profile else default_profiles

    for prof in profiles_to_try:
        cookie_file = chrome_base / prof / "Cookies"
        if not cookie_file.exists():
            continue

        try:
            result = chrome_cookies(slack_url, cookie_file=str(cookie_file))
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

    Chrome stores Local Storage in LevelDB format. We search files from
    newest to oldest to get the most recent token.
    """
    chrome_base, default_profiles = get_chrome_settings()

    # Auto-detect profile if not specified
    profiles_to_try = [profile] if profile else default_profiles

    for prof in profiles_to_try:
        local_storage_dir = chrome_base / prof / "Local Storage" / "leveldb"
        if not local_storage_dir.exists():
            continue

        try:
            # Get LevelDB files sorted by modification time (newest first)
            ldb_files = sorted(
                local_storage_dir.glob("*.ldb"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,  # Newest first
            )

            if not ldb_files:
                continue

            # Search each file from newest to oldest
            for ldb_file in ldb_files:
                result = subprocess.run(
                    ["strings", str(ldb_file)],
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    continue

                # Find xoxc tokens embedded in strings
                # Pattern: xoxc- followed by alphanumeric, hyphen, underscore (80+ chars total)
                pattern = r"xoxc-[a-zA-Z0-9_-]{77,}"
                matches = re.findall(pattern, result.stdout)

                if matches:
                    # Return the first (and likely only) valid token from newest file
                    token = matches[0]
                    print(f"📁 Found xoxc_token in Chrome profile: {prof}")
                    print(f"   (from {ldb_file.name}, modified {_format_mtime(ldb_file)})")
                    return token

        except Exception as e:
            print(f"⚠️  Error reading Local Storage from {prof}: {e}")
            continue

    return None


def _format_mtime(path: Path) -> str:
    """Format file modification time."""
    from datetime import datetime

    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def update_config(d_cookie: str | None, xoxc_token: str | None, dry_run: bool = False):
    """Update config.json with the new credentials.

    Uses ConfigManager for thread-safe, debounced writes with file locking.
    """
    # Import ConfigManager for thread-safe config access
    from server.config_manager import config as config_manager

    # Get current slack config
    slack_config = config_manager.get("slack", default={})
    if not isinstance(slack_config, dict):
        slack_config = {}

    auth_config = slack_config.get("auth", {})
    if not isinstance(auth_config, dict):
        auth_config = {}

    updated = False

    if d_cookie:
        if auth_config.get("d_cookie") != d_cookie:
            auth_config["d_cookie"] = d_cookie
            updated = True
            print("✅ Updated slack.auth.d_cookie in config.json")

    if xoxc_token:
        if auth_config.get("xoxc_token") != xoxc_token:
            auth_config["xoxc_token"] = xoxc_token
            updated = True
            print("✅ Updated slack.auth.xoxc_token in config.json")

    if updated:
        if dry_run:
            print("\n🔍 DRY RUN - would update config.json with:")
            print(f"   d_cookie: {d_cookie[:30] if d_cookie else 'None'}...")
            print(f"   xoxc_token: {xoxc_token[:30] if xoxc_token else 'None'}...")
        else:
            # Update the auth section within slack config
            slack_config["auth"] = auth_config
            config_manager.update_section("slack", slack_config, merge=True, flush=True)
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
