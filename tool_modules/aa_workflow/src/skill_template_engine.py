# pylint: disable=duplicate-code,cyclic-import
"""Skill template engine.

Rendering is implemented once on SkillTemplateMixin. This class keeps the
standalone constructor used by callers that are not a SkillExecutor.
"""

import logging
from typing import Any

from .skill_template_mixin import SkillTemplateMixin

logger = logging.getLogger(__name__)


class SkillTemplateEngine(SkillTemplateMixin):  # pylint: disable=too-few-public-methods
    """Jinja2 templating, condition evaluation, and link formatting.

    Args:
        context: The execution context dict (shared with SkillExecutor).
        config: The application config dict (from config.json).
        inputs: The skill inputs dict.
        debug_fn: Optional callable for debug logging.
    """

    def __init__(
        self,
        context: dict[str, Any],
        config: dict[str, Any],
        inputs: dict[str, Any],
        debug_fn=None,
    ):
        self.context = context
        self.config = config
        self.inputs = inputs
        self._debug_fn = debug_fn or (lambda msg: None)

    def _debug(self, msg: str):
        """Delegate debug logging to the provided function."""
        self._debug_fn(msg)
