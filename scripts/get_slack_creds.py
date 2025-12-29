#!/usr/bin/env python3
"""
Extract Slack credentials from browser cookies.

Gets the xoxc_token and d_cookie needed for the Slack bot.

Usage:
    python scripts/get_slack_creds.py
    python scripts/get_slack_creds.py --profile "Profile 1"
    python scripts/get_slack_creds.py --browser firefox

Requirements:
    pip install pycookiecheat browser-cookie3
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import unquote

# Try pycookiecheat first (best for Chrome)
try:
    from pycookiecheat import chrome_cookies

    HAS_PYCOOKIECHEAT = True
except ImportError:
    HAS_PYCOOKIECHEAT = False

# Fallback to browser-cookie3
try:
    import browser_cookie3

    HAS_BROWSER_COOKIE3 = True
except ImportError:
    HAS_BROWSER_COOKIE3 = False


def get_chrome_cookies_pycookiecheat(profile: str = "") -> dict:
    """Get Slack cookies from Chrome using pycookiecheat."""
    cookies = {"d": None, "xoxc": None}

    if not HAS_PYCOOKIECHEAT:
        return cookies

    chrome_base = Path.home() / ".config" / "google-chrome"

    # Auto-detect profile if not specified
    profiles_to_try = [profile] if profile else ["Profile 1", "Default", "Profile 2", "Profile 3"]

    for prof in profiles_to_try:
        cookie_file = chrome_base / prof / "Cookies"
        if not cookie_file.exists():
            continue

        try:
            result = chrome_cookies(
                "https://redhat.enterprise.slack.com",
                cookie_file=str(cookie_file),
            )

            if "d" in result:
                # URL-decode the cookie value
                cookies["d"] = unquote(result["d"])
                print(f"📁 Found cookies in Chrome profile: {prof}")
                return cookies
        except Exception as e:
            print(f"⚠️  Error reading {prof}: {e}")
            continue

    return cookies


def get_firefox_cookies() -> dict:
    """Get Slack cookies from Firefox."""
    cookies = {"d": None, "xoxc": None}

    if not HAS_BROWSER_COOKIE3:
        print("❌ Missing: pip install browser-cookie3")
        return cookies

    try:
        cj = browser_cookie3.firefox(domain_name=".slack.com")
        for cookie in cj:
            if cookie.name == "d":
                cookies["d"] = cookie.value
            if cookie.name == "xoxc":
                cookies["xoxc"] = cookie.value
    except Exception as e:
        print(f"⚠️  Firefox error: {e}")

    return cookies


def get_slack_cookies(browser: str = "chrome", profile: str = "") -> dict:
    """Extract Slack cookies from browser."""
    if browser == "chrome":
        return get_chrome_cookies_pycookiecheat(profile)
    elif browser == "firefox":
        return get_firefox_cookies()
    else:
        print(f"❌ Unsupported browser: {browser}")
        return {"d": None, "xoxc": None}


def main():
    parser = argparse.ArgumentParser(description="Extract Slack credentials from browser")
    parser.add_argument(
        "--browser",
        "-b",
        choices=["chrome", "firefox"],
        default="chrome",
        help="Browser to extract from (default: chrome)",
    )
    parser.add_argument(
        "--profile",
        "-p",
        default="",
        help="Chrome profile name (e.g., 'Profile 1'). Auto-detected if not specified.",
    )
    parser.add_argument(
        "--json",
        "-j",
        action="store_true",
        help="Output as JSON",
    )
    args = parser.parse_args()

    # Check dependencies
    if args.browser == "chrome" and not HAS_PYCOOKIECHEAT:
        print("❌ Missing dependency for Chrome: pip install pycookiecheat")
        sys.exit(1)
    if args.browser == "firefox" and not HAS_BROWSER_COOKIE3:
        print("❌ Missing dependency for Firefox: pip install browser-cookie3")
        sys.exit(1)

    print(f"🔍 Extracting Slack cookies from {args.browser}...")
    cookies = get_slack_cookies(args.browser, args.profile)

    if args.json:
        import json

        print(json.dumps(cookies, indent=2))
        return

    print()
    if cookies["d"]:
        d_val = cookies["d"]
        print(f"✅ d_cookie found ({len(d_val)} chars)")
        print(f"   Preview: {d_val[:30]}...")
        print()
        print("=" * 60)
        print("FULL d_cookie VALUE (copy this):")
        print("=" * 60)
        print(d_val)
        print("=" * 60)
    else:
        print("❌ d_cookie not found")
        print("   Make sure you're logged into Slack in your browser")
        print("   Try: python scripts/get_slack_creds.py --profile 'Profile 1'")

    print()
    if cookies["xoxc"]:
        print(f"✅ xoxc_token found: {cookies['xoxc'][:30]}...")
    else:
        print("ℹ️  xoxc_token not in cookies - get it via browser console:")
        print()
        print("   1. Open Slack in browser, press F12 for DevTools")
        print("   2. Go to Console tab, paste this and press Enter:")
        print()
        print("   (function() {")
        print("       const s = XMLHttpRequest.prototype.send;")
        print("       XMLHttpRequest.prototype.send = function(b) {")
        print("           if (b && typeof b === 'string') {")
        print("               try {")
        print("                   const p = JSON.parse(b);")
        print("                   if (p.token?.startsWith('xoxc-')) {")
        print("                       console.log('xoxc_token:', p.token);")
        print("                       XMLHttpRequest.prototype.send = s;")
        print("                   }")
        print("               } catch(e) {}")
        print("           }")
        print("           return s.apply(this, arguments);")
        print("       };")
        print("       console.log('Click anything in Slack...');")
        print("   })();")
        print()
        print("   3. Click anywhere in Slack to trigger the capture")

    print()
    print("📋 Add both values to ~/.config/aa-workflow/slack-creds.json:")
    print('   {"d_cookie": "<value>", "xoxc_token": "<value>"}')


if __name__ == "__main__":
    main()
