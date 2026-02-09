#!/usr/bin/env python3
"""Full test of Slack message export - runs a small export.

Run with: python scripts/test_slack_export_full.py

This does an actual export of 1 month of DMs only to verify the pipeline.
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

STYLE_DIR = PROJECT_ROOT / "memory" / "style"


async def run_export():
    """Run a small export test."""
    from slack_client import SlackSession

    print("=" * 60)
    print("Slack Export Full Test (1 month, DMs only)")
    print("=" * 60)

    # Load config
    config = load_config()
    slack_config = config.get("slack", {})
    auth = slack_config.get("auth", {})

    if not auth.get("xoxc_token"):
        print("❌ No Slack credentials found")
        return

    # Create session
    session = SlackSession(
        xoxc_token=auth.get("xoxc_token", ""),
        d_cookie=auth.get("d_cookie", ""),
        workspace_id=auth.get("workspace_id", ""),
        enterprise_id=auth.get("enterprise_id", ""),
    )

    # Validate
    print("\n📡 Validating session...")
    await session.validate_session()
    my_user_id = session.user_id
    print(f"✅ User ID: {my_user_id}")

    # Get conversations via client.counts
    print("\n📂 Fetching conversations...")
    counts = await session.get_client_counts()

    if not counts.get("ok"):
        print(f"❌ Failed: {counts.get('error')}")
        return

    # Only DMs for this test
    conversations = []
    for im in counts.get("ims", []):
        if isinstance(im, dict):
            conversations.append({"id": im.get("id"), "is_im": True})
        else:
            conversations.append({"id": im, "is_im": True})

    print(f"✅ Found {len(conversations)} DMs")

    # Time range - 1 month
    now = datetime.now()
    oldest_date = now - timedelta(days=30)
    oldest_ts = str(oldest_date.timestamp())

    # Output files
    STYLE_DIR.mkdir(parents=True, exist_ok=True)
    output_file = STYLE_DIR / "slack_corpus.jsonl"
    context_file = STYLE_DIR / "slack_corpus_context.jsonl"

    print(f"\n📝 Exporting to: {output_file}")

    total_messages = 0
    my_messages = 0

    with (
        open(output_file, "w", encoding="utf-8") as f_out,
        open(context_file, "w", encoding="utf-8") as f_ctx,
    ):
        for i, conv in enumerate(conversations[:10]):  # Limit to 10 DMs for test
            channel_id = conv.get("id", "")
            print(f"   [{i+1}/10] Processing {channel_id}...", end=" ")

            try:
                messages = await session.get_channel_history(
                    channel_id=channel_id,
                    limit=100,
                    oldest=oldest_ts,
                )

                channel_total = len(messages)
                channel_mine = 0

                for msg in messages:
                    msg_user = msg.get("user", "")
                    msg_text = msg.get("text", "")
                    msg_ts = msg.get("ts", "")

                    if msg_user == my_user_id and msg_text:
                        channel_mine += 1
                        my_messages += 1

                        record = {
                            "text": msg_text,
                            "ts": msg_ts,
                            "channel_type": "dm",
                            "channel_id": channel_id,
                            "is_thread_reply": False,
                            "reply_to": None,
                            "reactions": msg.get("reactions", []),
                            "has_attachments": bool(
                                msg.get("files") or msg.get("attachments")
                            ),
                        }
                        f_out.write(json.dumps(record) + "\n")

                    elif msg_text:
                        ctx_record = {
                            "user": msg_user,
                            "text": msg_text[:500],
                            "ts": msg_ts,
                            "channel_id": channel_id,
                        }
                        f_ctx.write(json.dumps(ctx_record) + "\n")

                total_messages += channel_total
                print(f"{channel_total} msgs, {channel_mine} mine")

                await asyncio.sleep(0.3)  # Rate limit

            except Exception as e:
                print(f"error: {e}")

    # Write metadata
    metadata = {
        "export_date": datetime.now().isoformat(),
        "months_exported": 1,
        "total_messages_scanned": total_messages,
        "my_messages_exported": my_messages,
        "channels_processed": min(10, len(conversations)),
        "user_id": my_user_id,
        "test_run": True,
    }

    metadata_file = STYLE_DIR / "export_metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\n" + "=" * 60)
    print("Export Complete!")
    print("=" * 60)
    print(f"✅ Total messages scanned: {total_messages}")
    print(f"✅ Your messages exported: {my_messages}")
    print(f"✅ Corpus file: {output_file}")
    print(f"✅ Metadata: {metadata_file}")

    # Show sample
    if my_messages > 0:
        print("\n📝 Sample of exported messages:")
        with open(output_file, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 3:
                    break
                msg = json.loads(line)
                text = msg.get("text", "")[:60]
                print(f'   {i+1}. "{text}..."')


if __name__ == "__main__":
    asyncio.run(run_export())
