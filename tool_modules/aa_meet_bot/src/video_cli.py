"""Command-line entry point for the research video generator."""

import asyncio
import atexit
import logging
import os
import signal
import sys
from pathlib import Path

from tool_modules.aa_meet_bot.src.pulse_defaults import default_source_metadata_args
from tool_modules.aa_meet_bot.src.video_config import VideoConfig
from tool_modules.aa_meet_bot.src.video_realtime import RealtimeVideoRenderer
from tool_modules.aa_meet_bot.src.video_research import (
    DEFAULT_ATTENDEES_FILE,
    ResearchVideoGenerator,
    generate_research_video,
    load_attendees_from_file,
)
from tool_modules.aa_meet_bot.src.virtual_devices import (
    cleanup_orphaned_meetbot_devices,
)

logger = logging.getLogger(__name__)


def _cli_cleanup_unset(*_args, **_kwargs):
    """Placeholder until the v4l2 cleanup helper is imported."""


def _cli_setup_unset(*_args, **_kwargs):
    """Placeholder until the v4l2 setup helper is imported."""
    raise RuntimeError("v4l2 helper is not loaded")


class _CliHooks:  # pylint: disable=too-few-public-methods
    """Set after the v4l2 helper import so signal handlers can reach it."""

    cleanup = _cli_cleanup_unset
    setup = _cli_setup_unset


def run_cli() -> None:
    """Run the video generator CLI. Used by ``python -m`` and direct execution."""

    logging.basicConfig(level=logging.INFO)

    # Import shared video device module
    # Add project root to path for imports
    _project_root = Path(__file__).parent.parent.parent.parent.parent
    sys.path.insert(0, str(_project_root))

    # Path insert above is required before this optional scripts import.
    from scripts.common.video_device import (  # pylint: disable=import-outside-toplevel,no-name-in-module
        cleanup_device,
        setup_v4l2_device,
    )

    _CliHooks.cleanup = cleanup_device
    _CliHooks.setup = setup_v4l2_device

    # Register cleanup handlers
    atexit.register(cleanup_device)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    asyncio.run(main())


def signal_handler(_signum, _frame):
    """Handle Ctrl+C gracefully."""
    print("\n\nShutting down...", file=sys.stderr)
    _CliHooks.cleanup()
    sys.exit(0)


def print_usage():
    "Print usage."
    print("Usage:")
    print("  python -m tool_modules.aa_meet_bot.src.video_generator --realtime")
    print(
        "  python -m tool_modules.aa_meet_bot.src.video_generator --realtime --audio SOURCE"
    )
    print(
        "  python -m tool_modules.aa_meet_bot.src.video_generator "
        "--realtime /dev/videoX  # Use specific device"
    )
    print("  python -m tool_modules.aa_meet_bot.src.video_generator --file output.mp4")
    print("  python -m tool_modules.aa_meet_bot.src.video_generator --cleanup")
    print("")
    print("Commands:")
    print("  --realtime      Stream to v4l2loopback device with hardcoded attendees")
    print("  --file          Generate video file")
    print(
        "  --cleanup       Clean up orphaned MeetBot audio/video devices and restore defaults"
    )
    print("")
    print("Options:")
    print("  --audio SOURCE  PulseAudio source for audio-reactive waveform")
    print("                  Use 'pactl list sources short' to find available sources")
    print("  --720p          Use 1280x720 resolution (default: 1920x1080)")
    print("  --nvidia        Use NVIDIA GPU instead of Intel iGPU")
    print(
        "  --flip          Flip video horizontally (for Google Meet mirror compensation)"
    )
    print("  --webrtc        Enable WebRTC streaming for preview (ws://localhost:8765)")
    print("")
    print("Production Mode:")
    print(
        "  In production, the video_daemon is controlled via D-Bus by the meet_daemon."
    )
    print("  The meet_daemon calls StartVideo/StopVideo/UpdateAttendees methods.")
    print("")
    print("WebRTC Preview:")
    print("  With --webrtc, frames are pushed to a WebRTC server on port 8765")
    print("  Connect from the Meetings tab Video Preview (select WebRTC mode)")
    print("")
    print(
        "The device is automatically created/configured. Press Ctrl+C to stop and release."
    )
    print("")
    print("Architecture:")
    print("  Full GPU pipeline: OpenGL (text/shapes) + OpenCL (color conversion)")
    print("  Target: ~1% CPU utilization at 1080p")


async def ensure_default_source_not_meetbot():
    """Ensure the system default audio source isn't a MeetBot device."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl",
            "get-default-source",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        current_default = stdout.decode().strip()

        if "meet_bot" in current_default.lower():
            print(
                f"WARNING: Default audio source is a MeetBot device: {current_default}",
                file=sys.stderr,
            )
            print("Restoring to physical microphone...", file=sys.stderr)

            # Find a physical microphone
            proc = await asyncio.create_subprocess_exec(
                "pactl",
                "list",
                "sources",
                "short",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            physical_mic = None
            for line in stdout.decode().strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    source_name = parts[1]
                    # Look for physical microphones (not monitors, not meetbot)
                    if (
                        "meet_bot" not in source_name.lower()
                        and ".monitor" not in source_name
                        and (
                            "alsa" in source_name.lower()
                            or "input" in source_name.lower()
                        )
                    ):
                        physical_mic = source_name
                        break

            if physical_mic:
                # Restore via pw-metadata (persistent)
                await asyncio.create_subprocess_exec(
                    *default_source_metadata_args(physical_mic),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                # Also via pactl (immediate)
                await asyncio.create_subprocess_exec(
                    "pactl",
                    "set-default-source",
                    physical_mic,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                print(f"Restored default source to: {physical_mic}", file=sys.stderr)
            else:
                print(
                    "WARNING: Could not find a physical microphone to restore to",
                    file=sys.stderr,
                )
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Error checking default source: %s", e)


async def _cli_cleanup() -> None:
    """Remove orphaned MeetBot devices."""
    print("Cleaning up orphaned MeetBot devices...", file=sys.stderr)
    try:
        results = await cleanup_orphaned_meetbot_devices()

        if results["removed_modules"]:
            print(
                f"Removed audio modules: {results['removed_modules']}",
                file=sys.stderr,
            )
        if results["removed_pipes"]:
            print(
                f"Removed pipes: {results['removed_pipes']}",
                file=sys.stderr,
            )
        if results["removed_video_devices"]:
            print(
                f"Removed video devices: {results['removed_video_devices']}",
                file=sys.stderr,
            )
        if results["errors"]:
            print(f"Errors: {results['errors']}", file=sys.stderr)

        total = (
            len(results["removed_modules"])
            + len(results["removed_pipes"])
            + len(results.get("removed_video_devices", []))
        )
        if total == 0:
            print("No orphaned devices found.", file=sys.stderr)
        else:
            print(f"Cleanup complete: {total} items removed.", file=sys.stderr)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"Cleanup error: {e}", file=sys.stderr)


async def _cli_stream() -> None:
    """Stream a research video to a v4l2 device."""
    video_device = sys.argv[2]
    attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
    if not attendees:
        print(
            f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
            file=sys.stderr,
        )
        return
    print(
        f"Streaming to {video_device} with {len(attendees)} attendees...",
        file=sys.stderr,
    )
    print("Using pre-rendered overlays (faster)", file=sys.stderr)
    print("Press Ctrl+C to stop", file=sys.stderr)
    generator = ResearchVideoGenerator()
    await generator.stream_to_device(attendees, video_device, loop=True)


# Live flow kept together after the duplicate copy was removed.
# pylint: disable-next=too-many-branches,too-many-statements
async def _cli_realtime() -> None:
    """Render a realtime overlay to a v4l2 device."""
    # Device can be specified or auto-created

    # Check for explicit device path
    video_device = None
    for arg in sys.argv[2:]:
        if arg.startswith("/dev/video"):
            video_device = arg
            break

    # Check for --audio option
    audio_source = None
    if "--audio" in sys.argv:
        audio_idx = sys.argv.index("--audio")
        if audio_idx + 1 < len(sys.argv):
            audio_source = sys.argv[audio_idx + 1]

    # Check for resolution option (1080p is now default)
    use_720p = "--720p" in sys.argv

    # Check for --flip option (horizontal mirror for Google Meet)
    use_flip = "--flip" in sys.argv

    # Determine resolution
    if use_720p:
        width, height = 1280, 720
    else:
        width, height = 1920, 1080

    # Auto-setup device if not specified
    if video_device is None:
        video_device = _CliHooks.setup(width, height)
    else:
        # Still configure the specified device
        print(f"Using specified device: {video_device}", file=sys.stderr)
        _CliHooks.setup(width, height)  # This will configure it

    # Check for GPU options
    use_nvidia = "--nvidia" in sys.argv

    # Create config (1080p default)
    if use_720p:
        config = VideoConfig.hd_720p()
        print("Using 720p resolution (1280x720)", file=sys.stderr)
    else:
        config = VideoConfig()  # Default is now 1080p
        print("Using 1080p resolution (1920x1080)", file=sys.stderr)

    # Set GPU preference
    config.prefer_intel_gpu = not use_nvidia
    gpu_name = "NVIDIA" if use_nvidia else "Intel iGPU"
    print(f"Using full GPU pipeline on {gpu_name}", file=sys.stderr)

    # Set flip mode
    if use_flip:
        os.environ["FLIP"] = "1"
        print("Horizontal flip ENABLED (for Google Meet)", file=sys.stderr)

    attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
    if not attendees:
        print(
            f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
            file=sys.stderr,
        )
        return
    print(
        f"Real-time streaming to {video_device} with {len(attendees)} attendees...",
        file=sys.stderr,
    )
    if audio_source:
        print(f"Audio-reactive waveform from: {audio_source}", file=sys.stderr)
    else:
        print("Using simulated waveform (no audio source)", file=sys.stderr)
    print("Press Ctrl+C to stop", file=sys.stderr)

    # Check for WebRTC streaming option
    use_webrtc = "--webrtc" in sys.argv
    if use_webrtc:
        print("WebRTC preview enabled on ws://localhost:8765", file=sys.stderr)

    renderer = RealtimeVideoRenderer(
        config=config, audio_source=audio_source, enable_webrtc=use_webrtc
    )
    try:
        await renderer.stream_realtime(attendees, video_device, loop=True)
    finally:
        await renderer.stop_async()


async def _cli_file() -> None:
    """Write a research video file."""
    # Generate to file
    output_path = sys.argv[2] if len(sys.argv) > 2 else "research_video.mp4"
    attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
    if not attendees:
        print(
            f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
            file=sys.stderr,
        )
        return
    generator = ResearchVideoGenerator()
    path = await generator.generate_video_file(attendees, Path(output_path))
    print(f"Generated: {path}", file=sys.stderr)


async def _cli_stdout() -> None:
    """Stream a research video to stdout."""
    # Stream to stdout as matroska (pipe-friendly format)
    attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
    if not attendees:
        print(
            f"No attendees found in {DEFAULT_ATTENDEES_FILE}",
            file=sys.stderr,
        )
        return
    print(
        f"Streaming {len(attendees)} attendees to stdout...",
        file=sys.stderr,
    )
    print("Pipe to: ffplay -f matroska -", file=sys.stderr)
    generator = ResearchVideoGenerator()
    await generator.stream_to_stdout(attendees)


async def _cli_named() -> None:
    """Generate a video from names passed on the command line."""
    # Generate file with provided names
    names = sys.argv[1:]
    path = await generate_research_video(names, Path("test_research.mp4"))
    print(f"Generated: {path}")


async def _cli_default() -> None:
    """Generate a video from the default attendee file."""
    attendees = load_attendees_from_file(DEFAULT_ATTENDEES_FILE)
    if attendees:
        print(f"Loaded {len(attendees)} attendees from {DEFAULT_ATTENDEES_FILE}")
        generator = ResearchVideoGenerator()
        path = await generator.generate_video_file(attendees, Path("test_research.mp4"))
        print(f"Generated: {path}")
        return
    names = ["John Smith", "Jane Doe", "Bob Wilson"]
    path = await generate_research_video(names, Path("test_research.mp4"))
    print(f"Generated: {path}")


async def main() -> None:
    """Dispatch the video generator command line."""
    await ensure_default_source_not_meetbot()
    if len(sys.argv) <= 1:
        await _cli_default()
        return
    command = sys.argv[1]
    if command == "--cleanup":
        await _cli_cleanup()
    elif command == "--stream" and len(sys.argv) > 2:
        await _cli_stream()
    elif command == "--realtime":
        await _cli_realtime()
    elif command == "--file":
        await _cli_file()
    elif command == "--stdout":
        await _cli_stdout()
    elif command in {"--help", "-h"}:
        print_usage()
    else:
        await _cli_named()
