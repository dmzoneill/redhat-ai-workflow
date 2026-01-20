#!/usr/bin/env python3
"""
Test the full Meet Bot pipeline: LLM → TTS → Video.

Run from the project root:
    python tool_modules/aa_meet_bot/scripts/test_pipeline.py
"""

import asyncio
import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from tool_modules.aa_meet_bot.src.llm_responder import get_llm_responder
from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine
from tool_modules.aa_meet_bot.src.video_generator import get_video_generator


async def test_llm():
    """Test LLM response generation."""
    print("\n" + "=" * 60)
    print("Testing LLM Response")
    print("=" * 60)
    
    responder = get_llm_responder()
    
    if not await responder.initialize():
        print("❌ Ollama not available. Run: ollama serve")
        return None
    
    print("✅ Ollama connected")
    
    # Test questions
    questions = [
        "What's the status of the current sprint?",
        "Are there any blockers?",
        "What are you working on?",
    ]
    
    for q in questions:
        print(f"\n📝 Question: {q}")
        response = await responder.generate_response(q, "Test User")
        
        if response.success:
            print(f"💬 Response: {response.text}")
        else:
            print(f"❌ Failed: {response.error}")
    
    return response.text if response.success else None


async def test_tts(text: str):
    """Test TTS synthesis."""
    print("\n" + "=" * 60)
    print("Testing TTS (GPT-SoVITS)")
    print("=" * 60)
    
    engine = get_tts_engine()
    
    if not await engine.initialize():
        print("❌ GPT-SoVITS not available")
        return None
    
    print("✅ GPT-SoVITS ready")
    print(f"📝 Text: {text}")
    
    result = await engine.synthesize(text, "pipeline_test.wav")
    
    if result.success:
        print(f"✅ Audio: {result.audio_path}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
        return result.audio_path
    else:
        print(f"❌ Failed: {result.error}")
        return None


async def test_video(audio_path: Path):
    """Test video generation."""
    print("\n" + "=" * 60)
    print("Testing Video Generation")
    print("=" * 60)
    
    generator = get_video_generator()
    await generator.initialize()
    
    print(f"📝 Audio: {audio_path}")
    print(f"🎬 Wav2Lip available: {generator.wav2lip_available}")
    
    result = await generator.generate_video(audio_path, "pipeline_test.mp4")
    
    if result.success:
        print(f"✅ Video: {result.video_path}")
        print(f"   Source: {result.source}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
        return result.video_path
    else:
        print(f"❌ Failed: {result.error}")
        return None


async def main():
    print("=" * 60)
    print("Meet Bot Full Pipeline Test")
    print("=" * 60)
    
    # Step 1: LLM
    response_text = await test_llm()
    
    if not response_text:
        response_text = "This is a test response for the pipeline."
        print(f"\n⚠️ Using fallback text: {response_text}")
    
    # Step 2: TTS
    audio_path = await test_tts(response_text)
    
    if not audio_path:
        print("\n❌ Pipeline stopped: TTS failed")
        return
    
    # Step 3: Video
    video_path = await test_video(audio_path)
    
    # Summary
    print("\n" + "=" * 60)
    print("Pipeline Test Complete!")
    print("=" * 60)
    print(f"Response: {response_text}")
    print(f"Audio: {audio_path}")
    print(f"Video: {video_path or 'Not generated'}")
    
    if video_path:
        print(f"\n🎬 Play video: mpv {video_path}")
    elif audio_path:
        print(f"\n🔊 Play audio: aplay {audio_path}")


if __name__ == "__main__":
    asyncio.run(main())


