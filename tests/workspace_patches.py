"""Shared patches for workspace tests that must not touch Cursor's database or the disk."""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from server.workspace_state import WorkspaceRegistry


@contextmanager
def offline_registry(chat_info: tuple[str | None, str | None] = (None, None)) -> Iterator[None]:
    """No loaded tools, no saving to disk, and ``chat_info`` as Cursor's active chat."""
    with (
        patch("server.workspace_model.loaded_tool_names", return_value=set()),
        patch.object(WorkspaceRegistry, "save_to_disk"),
        patch("server.cursor_chat_db.get_cursor_chat_info_from_db", return_value=chat_info),
    ):
        yield
