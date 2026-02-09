#!/usr/bin/env python3
"""Run Slack message export directly.

Run with: python scripts/run_slack_export.py [months]

Example: python scripts/run_slack_export.py 1
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "tool_modules" / "aa_slack" / "src"))

from server.utils import load_config  # noqa: E402

MEMORY_DIR = PROJECT_ROOT / "memory"
STYLE_DIR = MEMORY_DIR / "style"


async def run_export(months: int = 1):
    """Run the Slack message export."""
    from slack_client import SlackSession

    print("=" * 60)
    print(f"Slack Message Export - {months} month(s)")
    print("=" * 60)

    # Ensure style directory exists
    STYLE_DIR.mkdir(parents=True, exist_ok=True)

    # Load config
    config = load_config()
    slack_config = config.get("slack", {})
    auth = slack_config.get("auth", {})

    if not auth.get("xoxc_token"):
        print("❌ No Slack credentials found in config.json")
        return

    # Create session
    session = SlackSession(
        xoxc_token=auth.get("xoxc_token", ""),
        d_cookie=auth.get("d_cookie", ""),
        workspace_id=auth.get("workspace_id", ""),
        enterprise_id=auth.get("enterprise_id", ""),
    )

    # Validate session
    print("📡 Validating session...")
    await session.validate_session()
    my_user_id = session.user_id
    print(f"✅ User ID: {my_user_id}")

    # Calculate time range
    now = datetime.now()
    oldest_date = now - timedelta(days=months * 30)
    print(
        f"📅 Date range: {oldest_date.strftime('%Y-%m-%d')} to {now.strftime('%Y-%m-%d')}"
    )

    # Get conversations - try multiple methods for enterprise restrictions
    print("\n📂 Fetching conversations...")
    conversations = []

    # Try users.conversations first
    try:
        conversations = await session.get_user_conversations(
            types="im,mpim,public_channel,private_channel",
            limit=500,
        )
        print(f"✅ Found {len(conversations)} conversations via users.conversations")
    except Exception as e:
        if "enterprise_is_restricted" in str(e):
            print("   ⚠️ Enterprise restricted, trying client.counts API...")
            # Use client.counts as fallback
            counts = await session.get_client_counts()
            if counts.get("ok"):
                # Build conversation list from counts
                for im in counts.get("ims", []):
                    conversations.append(
                        {
                            "id": im.get("id", im) if isinstance(im, dict) else im,
                            "is_im": True,
                            "name": im.get("id", im) if isinstance(im, dict) else im,
                        }
                    )
                for mpim in counts.get("mpims", []):
                    conversations.append(
                        {
                            "id": (
                                mpim.get("id", mpim) if isinstance(mpim, dict) else mpim
                            ),
                            "is_mpim": True,
                            "name": (
                                mpim.get("id", mpim) if isinstance(mpim, dict) else mpim
                            ),
                        }
                    )
                for channel in counts.get("channels", []):
                    conversations.append(
                        {
                            "id": (
                                channel.get("id", channel)
                                if isinstance(channel, dict)
                                else channel
                            ),
                            "is_im": False,
                            "is_mpim": False,
                            "name": (
                                channel.get("id", channel)
                                if isinstance(channel, dict)
                                else channel
                            ),
                        }
                    )
                print(f"✅ Found {len(conversations)} conversations via client.counts")
            else:
                print(f"❌ client.counts also failed: {counts.get('error')}")
                return
        else:
            print(f"❌ Failed to get conversations: {e}")
            return

    if not conversations:
        print("❌ No conversations found")
        return

    # Output files
    output_file = STYLE_DIR / "slack_corpus.jsonl"
    context_file = STYLE_DIR / "slack_corpus_context.jsonl"

    total_messages = 0
    my_messages = 0
    channels_done = 0

    print(f"\n📝 Exporting to: {output_file}")
    print("-" * 60)

    try:
        f_out = open(output_file, "w", encoding="utf-8")
        try:
            f_ctx = open(context_file, "w", encoding="utf-8")
        except OSError:
            f_out.close()
            raise
    except OSError as e:
        print(f"❌ Failed to open output files: {e}")
        return

    try:
        for conv in conversations:
            channel_id = conv.get("id", "")
            channel_name = conv.get("name", conv.get("user", channel_id[:8]))

            # Determine channel type
            if conv.get("is_im"):
                channel_type = "dm"
            elif conv.get("is_mpim"):
                channel_type = "group_dm"
            elif conv.get("is_private"):
                channel_type = "private_channel"
            else:
                channel_type = "public_channel"

            try:
                # Fetch ALL messages with pagination (no date filter for full history)
                all_messages = []
                latest_ts = None  # Start from now, go backwards

                while True:
                    # Fetch batch - NO oldest filter to get full history
                    batch = await session.get_channel_history(
                        channel_id=channel_id,
                        limit=100,
                        latest=latest_ts,
                    )

                    if not batch:
                        break

                    all_messages.extend(batch)

                    # Check if we got fewer than limit (no more messages)
                    if len(batch) < 100:
                        break

                    # Get oldest message timestamp for next batch
                    latest_ts = batch[-1].get("ts")
                    if not latest_ts:
                        break

                    # Rate limit between pagination calls
                    await asyncio.sleep(0.2)

                channel_mine = 0

                for msg in all_messages:
                    msg_user = msg.get("user", "")
                    msg_text = msg.get("text", "")
                    msg_ts = msg.get("ts", "")
                    thread_ts = msg.get("thread_ts", "")

                    total_messages += 1

                    if msg_user == my_user_id and msg_text:
                        my_messages += 1
                        channel_mine += 1

                        record = {
                            "text": msg_text,
                            "ts": msg_ts,
                            "channel_type": channel_type,
                            "channel_id": channel_id,
                            "is_thread_reply": bool(thread_ts and thread_ts != msg_ts),
                            "reply_to": None,
                            "reactions": msg.get("reactions", []),
                            "has_attachments": bool(
                                msg.get("files") or msg.get("attachments")
                            ),
                        }
                        f_out.write(json.dumps(record) + "\n")

                    elif msg_text:
                        # Context message
                        ctx_record = {
                            "user": msg_user,
                            "text": msg_text[:500],
                            "ts": msg_ts,
                            "channel_id": channel_id,
                        }
                        f_ctx.write(json.dumps(ctx_record) + "\n")

                channels_done += 1
                if channel_mine > 0:
                    print(
                        f"  [{channels_done}/{len(conversations)}] "
                        f"{channel_type}: {channel_name} - "
                        f"{channel_mine} messages"
                    )

                # Rate limit
                await asyncio.sleep(0.3)

            except Exception as e:
                print(f"  ⚠️ Error on {channel_name}: {e}")
                channels_done += 1
    finally:
        f_out.close()
        f_ctx.close()

    # Write metadata
    metadata = {
        "export_date": datetime.now().isoformat(),
        "months_exported": months,
        "total_messages_scanned": total_messages,
        "my_messages_exported": my_messages,
        "channels_processed": channels_done,
        "user_id": my_user_id,
    }

    metadata_file = STYLE_DIR / "export_metadata.json"
    try:
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except OSError as e:
        print(f"⚠️ Failed to write metadata: {e}")

    print("-" * 60)
    print("\n✅ Export complete!")
    print(f"   Your messages: {my_messages:,}")
    print(f"   Total scanned: {total_messages:,}")
    print(f"   Channels: {channels_done}")
    print("\n📁 Files:")
    print(f"   - {output_file}")
    print(f"   - {context_file}")
    print(f"   - {metadata_file}")


if __name__ == "__main__":
    months = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    asyncio.run(run_export(months))
