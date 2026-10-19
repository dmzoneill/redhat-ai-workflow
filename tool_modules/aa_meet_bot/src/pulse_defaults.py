"""Shared PipeWire and PulseAudio commands for Meet audio routing."""

import asyncio


def pw_metadata_args(key: str, source_name: str) -> list[str]:
    """Argv for pw-metadata to set a default PipeWire audio property."""
    return [
        "pw-metadata",
        "-n",
        "default",
        "0",
        key,
        '{"name":"%s"}' % source_name,
    ]


def default_source_metadata_args(source_name: str) -> list[str]:
    """Argv for pw-metadata to set default.audio.source."""
    return pw_metadata_args("default.audio.source", source_name)


def configured_source_metadata_args(source_name: str) -> list[str]:
    """Argv for pw-metadata to set default.configured.audio.source."""
    return pw_metadata_args("default.configured.audio.source", source_name)


async def read_pactl_sources_short() -> str:
    """Return stdout from ``pactl list sources short``."""
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        "list",
        "sources",
        "short",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()
