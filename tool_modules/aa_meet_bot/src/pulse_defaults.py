# pylint: disable=duplicate-code
"""Shared PipeWire commands used by Meet audio routing and the video CLI."""


def default_source_metadata_args(source_name: str) -> list[str]:
    """Argv for pw-metadata to set the default audio source."""
    return [
        "pw-metadata",
        "-n",
        "default",
        "0",
        "default.audio.source",
        '{"name":"%s"}' % source_name,
    ]
