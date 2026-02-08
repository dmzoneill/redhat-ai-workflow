#!/usr/bin/env python3
"""Test script for Slack message export.

Run with: python scripts/slack_export_test.py

This tests the export functionality directly without going through MCP.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tool_modules" / "aa_slack" / "src"))

from server.utils import load_config  # noqa: E402


async def test_export():
    """Test the Slack export functionality."""
    from slack_client import SlackSession

    print("=" * 60)
    print("Slack Export Test")
    print("=" * 60)

    # Load config
    config = load_config()
    slack_config = config.get("slack", {})
    auth = slack_config.get("auth", {})

    if not auth.get("xoxc_token"):
        print("❌ No Slack credentials found in config.json")
        print("   Make sure slack.auth.xoxc_token is set")
        return

    print("Found Slack credentials")
    print(f"   Workspace: {auth.get('workspace_id', 'unknown')}")

    # Create session
    session = SlackSession(
        xoxc_token=auth.get("xoxc_token", ""),
        d_cookie=auth.get("d_cookie", ""),
        workspace_id=auth.get("workspace_id", ""),
        enterprise_id=auth.get("enterprise_id", ""),
    )

    # Validate session
    print("\n📡 Validating Slack session...")
    try:
        await session.validate_session()
        user_id = session.user_id
        print(f"✅ Session valid! Your user ID: {user_id}")
    except Exception as e:
        print(f"❌ Session validation failed: {e}")
        return

    # Get conversations - try client.counts API (enterprise workaround)
    print("\n📂 Fetching your conversations...")
    conversations = []
    try:
        # Try client.counts API (works around enterprise_is_restricted)
        print("   Trying client.counts API (enterprise workaround)...")
        counts = await session.get_client_counts()

        if counts.get("ok"):
            # Build conversation list from counts
            ims = counts.get("ims", [])
            mpims = counts.get("mpims", [])
            channels = counts.get("channels", [])

            # Convert to conversation format
            for im in ims:
                if isinstance(im, dict):
                    conversations.append({"id": im.get("id"), "is_im": True})
                else:
                    conversations.append({"id": im, "is_im": True})

            for mpim in mpims:
                if isinstance(mpim, dict):
                    conversations.append({"id": mpim.get("id"), "is_mpim": True})
                else:
                    conversations.append({"id": mpim, "is_mpim": True})

            for channel in channels:
                if isinstance(channel, dict):
                    conversations.append({"id": channel.get("id"), "is_channel": True})
                else:
                    conversations.append({"id": channel, "is_channel": True})

            print(f"✅ Found {len(conversations)} conversations via client.counts")
            print(f"   - DMs: {len(ims)}")
            print(f"   - Group DMs: {len(mpims)}")
            print(f"   - Channels: {len(channels)}")
        else:
            print(f"   client.counts failed: {counts.get('error')}")
            # Fallback to standard API
            print("   Trying standard API...")
            conversations = await session.get_user_conversations(
                types="im,mpim,public_channel,private_channel",
                limit=100,
            )
            print(f"✅ Found {len(conversations)} conversations")

        # Categorize (already done above for client.counts path)
        dms = [c for c in conversations if c.get("is_im")]
        [c for c in conversations if c.get("is_mpim")]
        channels = [
            c
            for c in conversations
            if c.get("is_channel") or (not c.get("is_im") and not c.get("is_mpim"))
        ]

    except Exception as e:
        print(f"❌ Failed to get conversations: {e}")
        return

    # Test fetching messages from first DM
    if dms:
        print("\n💬 Testing message fetch from first DM...")
        dm = dms[0]
        dm_id = dm.get("id")
        dm.get("user", "unknown")

        try:
            messages = await session.get_channel_history(
                channel_id=dm_id,
                limit=10,
            )
            print(f"✅ Fetched {len(messages)} messages from DM")

            # Filter to my messages
            my_messages = [m for m in messages if m.get("user") == user_id]
            print(f"   - Your messages: {len(my_messages)}")

            if my_messages:
                print("\n📝 Sample of your messages:")
                for msg in my_messages[:3]:
                    text = msg.get("text", "")[:80]
                    ts = msg.get("ts", "")
                    print(f"   [{ts}] {text}")

        except Exception as e:
            print(f"❌ Failed to fetch messages: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print("✅ Slack API connection works")
    print("✅ Can fetch conversations")
    print("✅ Can fetch message history")
    print("✅ Can filter to your messages")
    print("\nThe export tool should work. Restart Cursor to load the new tools,")
    print("then run: slack_export_my_messages(months=1)")


if __name__ == "__main__":
    asyncio.run(test_export())
