#!/usr/bin/env python3
"""
Test GPT-SoVITS TTS integration.

Run from the project root:
    python tool_modules/aa_meet_bot/scripts/test_tts.py
"""

import asyncio
import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine


async def main():
    print("=" * 60)
    print("GPT-SoVITS TTS Test")
    print("=" * 60)

    engine = get_tts_engine()

    # Test phrases
    test_phrases = [
        "Hello, this is a test of the voice cloning system.",
        "The current sprint is going well. We're on track to complete all items.",
        "I'll update the Jira ticket with the latest status.",
    ]

    print("\nInitializing TTS engine...")
    success = await engine.initialize()

    if not success:
        print("❌ Failed to initialize TTS engine")
        print("\nMake sure GPT-SoVITS is installed at ~/src/GPT-SoVITS")
        print("And the dave model is trained in GPT_weights_v2Pro/")
        return

    print("✅ TTS engine initialized")

    for i, phrase in enumerate(test_phrases, 1):
        print(f'\n[{i}/{len(test_phrases)}] Synthesizing: "{phrase[:50]}..."')

        result = await engine.synthesize(phrase, f"test_{i}.wav")

        if result.success:
            print(f"✅ Generated: {result.audio_path}")
            print(f"   Duration: {result.duration_seconds:.2f}s")
            print(f"   Sample rate: {result.sample_rate} Hz")
        else:
            print(f"❌ Failed: {result.error}")

    print("\n" + "=" * 60)
    print("Test complete!")
    print(f"Output files in: {engine.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
