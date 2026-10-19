"""
Google Meet Audio Routing.

Handles PulseAudio/PipeWire audio routing for the Meet bot:
- Virtual sink/source creation (legacy fallback)
- Audio module loading/unloading
- Audio stream routing (Chrome to virtual sink)
- Mute/unmute of meeting audio
- Default source restoration

Extracted from GoogleMeetController to separate audio concerns.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController
    from tool_modules.aa_meet_bot.src.virtual_devices import InstanceDevices

from tool_modules.aa_meet_bot.src.browser_controller import (
    _shared_GoogleMeetController__create_virtual_audio_sink,
    _shared_GoogleMeetController__get_chrome_sink_inputs,
    _shared_GoogleMeetController__move_sink_input,
    _shared_GoogleMeetController__move_user_browser_to_original_source,
    _shared_GoogleMeetController__remove_virtual_audio_sink,
    _shared_GoogleMeetController__restore_user_default_source,
    _shared_GoogleMeetController__route_browser_audio_to_sink,
    _shared_GoogleMeetController_get_monitor_source,
    _shared_GoogleMeetController_get_pipe_path,
    _shared_GoogleMeetController_is_audio_muted,
    _shared_GoogleMeetController_mute_audio,
    _shared_GoogleMeetController_unmute_audio,
)

logger = logging.getLogger(__name__)


class MeetAudio:
    """Handles PulseAudio/PipeWire audio routing for Google Meet.

    Uses composition: receives a reference to the GoogleMeetController
    to access browser PID, state, device manager, and instance ID.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller

    @property
    def _instance_id(self):
        return self._controller._instance_id

    @property
    def _audio_sink_name(self) -> Optional[str]:
        return self._controller._audio_sink_name

    @_audio_sink_name.setter
    def _audio_sink_name(self, value: Optional[str]):
        self._controller._audio_sink_name = value

    @property
    def _browser_pid(self) -> Optional[int]:
        return self._controller._browser_pid

    @property
    def _device_manager(self):
        return self._controller._device_manager

    @property
    def _devices(self) -> Optional["InstanceDevices"]:
        return self._controller._devices

    @property
    def state(self):
        "State."
        return self._controller.state

    async def create_virtual_audio_sink(self) -> bool:
        "Create virtual audio sink."
        return await _shared_GoogleMeetController__create_virtual_audio_sink(
            self, logger=logger
        )

    create_virtual_audio_sink.__doc__ = (
        _shared_GoogleMeetController__create_virtual_audio_sink.__doc__
    )

    async def remove_virtual_audio_sink(self) -> None:
        "Remove virtual audio sink."
        return await _shared_GoogleMeetController__remove_virtual_audio_sink(
            self, logger=logger
        )

    remove_virtual_audio_sink.__doc__ = (
        _shared_GoogleMeetController__remove_virtual_audio_sink.__doc__
    )

    def get_audio_sink_name(self) -> Optional[str]:
        """Get the name of the virtual audio sink for this instance.

        To listen to meeting audio:
            pactl set-default-source <sink_name>.monitor
            # Or use pavucontrol to route the monitor to your headphones
        """
        return self._audio_sink_name

    def get_audio_devices(self) -> Optional["InstanceDevices"]:
        """Get the per-instance audio devices for this controller.

        Returns:
            InstanceDevices with sink_name, source_name, pipe_path, etc.
            None if devices weren't created (legacy mode).
        """
        return self._devices

    def get_monitor_source(self) -> Optional[str]:
        "Get monitor source."
        return _shared_GoogleMeetController_get_monitor_source(self)

    get_monitor_source.__doc__ = _shared_GoogleMeetController_get_monitor_source.__doc__

    def get_pipe_path(self) -> Optional[Path]:
        "Get pipe path."
        return _shared_GoogleMeetController_get_pipe_path(self)

    get_pipe_path.__doc__ = _shared_GoogleMeetController_get_pipe_path.__doc__

    async def route_browser_audio_to_sink(self) -> None:
        "Route browser audio to sink."
        return await _shared_GoogleMeetController__route_browser_audio_to_sink(
            self, logger=logger
        )

    route_browser_audio_to_sink.__doc__ = (
        _shared_GoogleMeetController__route_browser_audio_to_sink.__doc__
    )

    def _move_sink_input(self, sink_input_id: str) -> bool:
        return _shared_GoogleMeetController__move_sink_input(
            self, sink_input_id, logger=logger
        )

    _move_sink_input.__doc__ = _shared_GoogleMeetController__move_sink_input.__doc__

    def _get_chrome_sink_inputs(self, only_our_browser: bool = True) -> list[str]:
        return _shared_GoogleMeetController__get_chrome_sink_inputs(
            self, only_our_browser, logger=logger
        )

    _get_chrome_sink_inputs.__doc__ = (
        _shared_GoogleMeetController__get_chrome_sink_inputs.__doc__
    )

    def unmute_audio(self) -> bool:
        "Unmute audio."
        return _shared_GoogleMeetController_unmute_audio(self, logger=logger)

    unmute_audio.__doc__ = _shared_GoogleMeetController_unmute_audio.__doc__

    def mute_audio(self) -> bool:
        "Mute audio."
        return _shared_GoogleMeetController_mute_audio(self, logger=logger)

    mute_audio.__doc__ = _shared_GoogleMeetController_mute_audio.__doc__

    def is_audio_muted(self) -> bool:
        "Is audio muted."
        return _shared_GoogleMeetController_is_audio_muted(self, logger=logger)

    is_audio_muted.__doc__ = _shared_GoogleMeetController_is_audio_muted.__doc__

    async def restore_user_default_source(self) -> None:
        "Restore user default source."
        return await _shared_GoogleMeetController__restore_user_default_source(
            self, logger=logger
        )

    restore_user_default_source.__doc__ = (
        _shared_GoogleMeetController__restore_user_default_source.__doc__
    )

    async def move_user_browser_to_original_source(self, target_source: str) -> None:
        "Move user browser to original source."
        return await _shared_GoogleMeetController__move_user_browser_to_original_source(
            self, target_source, logger=logger
        )

    move_user_browser_to_original_source.__doc__ = (
        _shared_GoogleMeetController__move_user_browser_to_original_source.__doc__
    )
