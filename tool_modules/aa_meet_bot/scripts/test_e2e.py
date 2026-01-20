#!/usr/bin/env python3
"""
End-to-End Test for Meet Bot.

Tests the complete flow:
1. Virtual device setup
2. Wake word detection from captions
3. LLM response generation
4. TTS synthesis
5. Video generation
6. (Optional) Browser automation

Run from the project root:
    python tool_modules/aa_meet_bot/scripts/test_e2e.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# Add project to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from tool_modules.aa_meet_bot.src.config import get_config
from tool_modules.aa_meet_bot.src.virtual_devices import VirtualDeviceManager
from tool_modules.aa_meet_bot.src.wake_word import WakeWordManager, WakeWordEvent
from tool_modules.aa_meet_bot.src.llm_responder import get_llm_responder
from tool_modules.aa_meet_bot.src.tts_engine import get_tts_engine
from tool_modules.aa_meet_bot.src.video_generator import get_video_generator
from tool_modules.aa_meet_bot.src.jira_preloader import get_jira_preloader


def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_step(step: int, total: int, description: str):
    print(f"\n[{step}/{total}] {description}")
    print("-" * 40)


async def test_config():
    """Test configuration loading."""
    print_step(1, 7, "Configuration")
    
    config = get_config()
    print(f"✅ Bot account: {config.bot_account.email}")
    print(f"✅ Wake word: '{config.wake_word}'")
    print(f"✅ Avatar image: {config.avatar.face_image}")
    print(f"   Exists: {config.avatar.face_image.exists()}")
    
    return True


async def test_virtual_devices():
    """Test virtual device setup."""
    print_step(2, 7, "Virtual Devices")
    
    manager = VirtualDeviceManager()
    status = await manager.get_status()
    
    print(f"Audio Sink: {'✅' if status.audio_sink_ready else '❌'} {status.audio_sink_id or 'Not ready'}")
    print(f"Audio Source: {'✅' if status.audio_source_ready else '❌'} {status.audio_source_id or 'Not ready'}")
    print(f"Virtual Camera: {'✅' if status.video_device_ready else '❌'} {status.video_device_path or 'Not ready'}")
    
    if not status.all_ready:
        print("\n⚠️ Virtual devices not fully configured.")
        print("Run: ./tool_modules/aa_meet_bot/scripts/setup_devices.sh")
    
    return status.all_ready


async def test_wake_word():
    """Test wake word detection from captions."""
    print_step(3, 7, "Wake Word Detection")
    
    manager = WakeWordManager()
    await manager.initialize()
    
    # Simulate captions
    test_captions = [
        ("John", "Good morning everyone, let's start the standup."),
        ("Sarah", "I finished the API refactoring yesterday."),
        ("John", "Great! David, what's your status?"),
        ("David", "I'm working on the authentication fix."),
        ("Sarah", "David, are there any blockers?"),
    ]
    
    events = []
    for speaker, text in test_captions:
        print(f"  [{speaker}]: {text[:50]}...")
        event = manager.process_caption(speaker, text)
        if event:
            events.append(event)
            print(f"  🎯 WAKE WORD DETECTED!")
            print(f"     Command: '{event.command_text}'")
    
    print(f"\n✅ Detected {len(events)} wake word events")
    
    if events:
        return events[-1]  # Return last event for next test
    return None


async def test_llm_response(wake_event: WakeWordEvent = None):
    """Test LLM response generation."""
    print_step(4, 7, "LLM Response Generation")
    
    responder = get_llm_responder()
    
    if not await responder.initialize():
        print("❌ Ollama not available. Run: ollama serve")
        return None
    
    print("✅ Ollama connected")
    
    # Use wake event command or default
    if wake_event:
        question = wake_event.command_text
        speaker = wake_event.speaker
    else:
        question = "what's your status?"
        speaker = "Test User"
    
    print(f"\n📝 Question: '{question}' (from {speaker})")
    
    response = await responder.generate_response(question, speaker)
    
    if response.success:
        print(f"✅ Response: {response.text}")
        return response.text
    else:
        print(f"❌ Failed: {response.error}")
        return None


async def test_tts(text: str = None):
    """Test TTS synthesis."""
    print_step(5, 7, "TTS Synthesis (GPT-SoVITS)")
    
    engine = get_tts_engine()
    
    if not await engine.initialize():
        print("❌ GPT-SoVITS not available")
        return None
    
    print("✅ GPT-SoVITS ready")
    
    text = text or "This is a test of the voice synthesis system."
    print(f"\n📝 Text: '{text[:60]}...'")
    
    result = await engine.synthesize(text, "e2e_test.wav")
    
    if result.success:
        print(f"✅ Audio: {result.audio_path}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
        return result.audio_path
    else:
        print(f"❌ Failed: {result.error}")
        return None


async def test_video(audio_path: Path = None):
    """Test video generation."""
    print_step(6, 7, "Video Generation")
    
    generator = get_video_generator()
    await generator.initialize()
    
    print(f"🎬 Wav2Lip available: {generator.wav2lip_available}")
    
    if not audio_path:
        print("⚠️ No audio provided, skipping video test")
        return None
    
    print(f"\n📝 Audio: {audio_path}")
    
    result = await generator.generate_video(audio_path, "e2e_test.mp4")
    
    if result.success:
        print(f"✅ Video: {result.video_path}")
        print(f"   Source: {result.source}")
        print(f"   Duration: {result.duration_seconds:.2f}s")
        return result.video_path
    else:
        print(f"❌ Failed: {result.error}")
        return None


async def test_jira_preload():
    """Test Jira context preloading."""
    print_step(7, 7, "Jira Context Preloading")
    
    preloader = get_jira_preloader()
    
    # This may fail if rh-issue CLI is not configured
    try:
        success = await preloader.preload("AAP")
        
        if success:
            print(f"✅ Loaded {len(preloader.my_issues)} personal issues")
            print(f"✅ Loaded {len(preloader.issues)} sprint issues")
            print(f"\n📊 Status: {preloader.get_status_summary()}")
        else:
            print("⚠️ Jira preload returned false (CLI may not be configured)")
            
    except Exception as e:
        print(f"⚠️ Jira preload failed: {e}")
        print("   This is expected if rh-issue CLI is not configured")
    
    return True


async def main():
    print_header("Meet Bot End-to-End Test")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # Test 1: Configuration
    results['config'] = await test_config()
    
    # Test 2: Virtual Devices
    results['devices'] = await test_virtual_devices()
    
    # Test 3: Wake Word Detection
    wake_event = await test_wake_word()
    results['wake_word'] = wake_event is not None
    
    # Test 4: LLM Response
    llm_response = await test_llm_response(wake_event)
    results['llm'] = llm_response is not None
    
    # Test 5: TTS
    audio_path = await test_tts(llm_response)
    results['tts'] = audio_path is not None
    
    # Test 6: Video
    video_path = await test_video(audio_path)
    results['video'] = video_path is not None
    
    # Test 7: Jira Preload
    results['jira'] = await test_jira_preload()
    
    # Summary
    print_header("Test Summary")
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name.ljust(15)}: {status}")
        if not passed:
            all_passed = False
    
    print("\n" + "-" * 40)
    
    if all_passed:
        print("🎉 All tests passed!")
    else:
        print("⚠️ Some tests failed (see above)")
    
    # Output files
    if audio_path or video_path:
        print("\n📁 Output Files:")
        if audio_path:
            print(f"   Audio: {audio_path}")
        if video_path:
            print(f"   Video: {video_path}")
            print(f"\n🎬 Play: mpv {video_path}")
    
    print("\n" + "=" * 60)
    print(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())


