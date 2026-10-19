"""Public wrappers around NotesInteractiveMixin for the notes bot."""

from tool_modules.aa_meet_bot.src.notes_interactive import NotesInteractiveMixin
from tool_modules.aa_meet_bot.src.notes_state import NotesBotState

__all__ = ["InteractiveActions", "NotesBotState"]


class InteractiveActions(  # pylint: disable=too-few-public-methods
    NotesInteractiveMixin
):
    """Interactive notes-bot actions.

    The implementation lives on NotesInteractiveMixin. This class keeps the
    name existing callers import.
    """

    def __init__(self, bot) -> None:
        self._bot = bot
