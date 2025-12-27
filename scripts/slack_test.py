#!/usr/bin/env python3
"""Quick Slack smoke test - send a message to yourself."""

import asyncio
import json
import sys
from pathlib import Path

# Add the slack module to path
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp-servers/aa-slack/src"))

from slack_client import SlackSession


def load_config() -> dict:
    """Load config.json."""
    config_path = Path(__file__).parent.parent / "config.json"
    if not config_path.exists():
        print(f"❌ Config not found: {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return json.load(f)


async def main():
    config = load_config()
    slack_config = config.get("slack", {})
    auth = slack_config.get("auth", {})

    # Check required config
    xoxc_token = auth.get("xoxc_token", "")
    d_cookie = auth.get("d_cookie", "")
    workspace_id = auth.get("workspace_id", "")
    self_user_id = slack_config.get("listener", {}).get("self_user_id", "")

    if not xoxc_token or not d_cookie:
        print("❌ Missing xoxc_token or d_cookie in config.json")
        sys.exit(1)

    if not self_user_id:
        print("❌ Missing self_user_id in config.json")
        sys.exit(1)

    print("🔧 Creating Slack session...")
    print(f"   Workspace: {workspace_id}")
    print(f"   User ID: {self_user_id}")
    print(f"   Token: {xoxc_token[:20]}...")
    print()

    session = SlackSession(
        xoxc_token=xoxc_token,
        d_cookie=d_cookie,
        workspace_id=workspace_id,
    )

    try:
        # Test 1: Validate session
        print("📋 Test 1: Validating session...")
        is_valid = await session.validate_session()
        if is_valid:
            print("   ✅ Session is valid!")
        else:
            print("   ❌ Session is invalid - check your tokens")
            sys.exit(1)
        print()

        # Test 2: Get user info
        print("📋 Test 2: Getting your user info...")
        try:
            user_info = await session.get_user_info(self_user_id)
            if user_info.get("ok"):
                user = user_info.get("user", {})
                print(f"   ✅ Found user: {user.get('real_name', 'Unknown')}")
                print(f"      Username: @{user.get('name', 'unknown')}")
                print(f"      Email: {user.get('profile', {}).get('email', 'N/A')}")
            else:
                print(f"   ⚠️  API returned: {user_info.get('error', 'no error field')}")
                print(f"      (This is OK - we can still send messages)")
        except Exception as e:
            print(f"   ⚠️  Exception: {e}")
            print(f"      (This is OK - we can still try sending messages)")
        print()

        # Test 3: Open DM and send message to self
        print("📋 Test 3: Opening DM channel to yourself...")
        try:
            dm_channel = await session.open_dm(self_user_id)
            print(f"   ✅ DM channel opened: {dm_channel}")
        except Exception as e:
            print(f"   ❌ Failed to open DM: {e}")
            return

        print("📋 Test 4: Sending test message...")
        message = "🤖 *Smoke Test* - Your AI Workflow Slack integration is working! 🎉"
        result = await session.send_message(
            channel_id=dm_channel,
            text=message,
            typing_delay=False,  # Skip delay for test
        )

        if result.get("ok"):
            print("   ✅ Message sent successfully!")
            print(f"      Channel: {result.get('channel')}")
            print(f"      Timestamp: {result.get('ts')}")
            print()
            print("📱 Check your Slack - you should see a DM from yourself!")
        else:
            print(f"   ❌ Failed to send: {result.get('error', 'Unknown error')}")
            if result.get("error") == "invalid_auth":
                print("      → Your tokens may have expired. Get fresh ones from browser.")
            elif result.get("error") == "channel_not_found":
                print("      → Could not open DM. Try sending to a channel instead.")

    finally:
        await session.close()


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Slack Smoke Test")
    print("=" * 60)
    print()
    asyncio.run(main())
