# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""

import logging
import sys

from tool_modules.common import PROJECT_ROOT

from .skill_support import (
    AttrDict,
)

logger = logging.getLogger(__name__)


class SkillComputeMixin:  # pylint: disable=too-few-public-methods
    """SkillExecutor behavior split out of skill_engine."""

    # pylint: disable-next=too-many-branches,too-many-locals,too-many-statements
    def _exec_compute_internal(self, code: str, output_name: str):
        """Internal compute execution without error recovery (used by recovery itself)."""
        # This is the actual compute logic extracted from _exec_compute
        # to avoid infinite recursion during auto-fix retries
        local_vars = dict(self.context)
        # Wrap inputs in AttrDict to allow attribute-style access (inputs.repo vs inputs["repo"])
        local_vars["inputs"] = AttrDict(self.inputs)
        local_vars["config"] = self.config

        import os  # pylint: disable=import-outside-toplevel
        import re  # pylint: disable=import-outside-toplevel
        from datetime import (  # pylint: disable=import-outside-toplevel
            datetime,
            timedelta,
        )
        from pathlib import Path  # pylint: disable=import-outside-toplevel

        try:
            from zoneinfo import ZoneInfo  # pylint: disable=import-outside-toplevel
        except ImportError:
            ZoneInfo = None  # type: ignore[misc,assignment]

        # Use module-level PROJECT_ROOT
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        try:
            from scripts.common import (  # pylint: disable=import-outside-toplevel
                config_loader,
                jira_utils,
                lint_utils,
            )

            # isort: off
            from scripts.common import (  # pylint: disable=import-outside-toplevel
                memory as memory_helpers,
            )

            # isort: on
            from scripts.common import (  # pylint: disable=import-outside-toplevel
                parsers,
                repo_utils,
                slack_utils,
            )
            from scripts.common.config_loader import (  # pylint: disable=import-outside-toplevel
                get_timezone,
            )

            # isort: off
            from scripts.common.config_loader import (  # pylint: disable=import-outside-toplevel
                load_config as load_skill_config,
            )

            # isort: on
            from scripts.skill_hooks import (  # pylint: disable=import-outside-toplevel
                emit_event_sync,
            )
        except ImportError:
            parsers = None  # type: ignore[assignment]
            jira_utils = None  # type: ignore[assignment]
            load_skill_config = None  # type: ignore[assignment]
            get_timezone = None  # type: ignore[assignment]
            emit_event_sync = None  # type: ignore[assignment]
            memory_helpers = None  # type: ignore[assignment]
            config_loader = None  # type: ignore[assignment]
            lint_utils = None  # type: ignore[assignment]
            repo_utils = None  # type: ignore[assignment]
            slack_utils = None  # type: ignore[assignment]

        try:
            # isort: off
            from google.oauth2.credentials import (  # pylint: disable=import-outside-toplevel
                Credentials as GoogleCredentials,
            )
            from googleapiclient.discovery import (  # pylint: disable=import-outside-toplevel
                build as google_build,
            )

            # isort: on
        except ImportError:
            GoogleCredentials = None  # type: ignore[misc,assignment]
            google_build = None

        # Create the nested skill runner for compute blocks
        run_skill = self._create_nested_skill_runner()

        safe_globals = {
            "__builtins__": {
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "bool": bool,
                "tuple": tuple,
                "set": set,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "sorted": sorted,
                "min": min,
                "max": max,
                "sum": sum,
                "any": any,
                "all": all,
                "isinstance": isinstance,
                "type": type,
                "hasattr": hasattr,
                "getattr": getattr,
                "repr": repr,
                "print": print,
                "dir": dir,
                "vars": vars,
                "Exception": Exception,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "KeyError": KeyError,
                "AttributeError": AttributeError,
                "IndexError": IndexError,
                "ImportError": ImportError,
                "True": True,
                "False": False,
                "None": None,
                "open": open,
                "__import__": __import__,
            },
            "re": re,
            "os": os,
            "Path": Path,
            "datetime": datetime,
            "timedelta": timedelta,
            "ZoneInfo": ZoneInfo,
            "parsers": parsers,
            "jira_utils": jira_utils,
            "memory": memory_helpers,
            "emit_event": emit_event_sync,
            "load_config": load_skill_config,
            "get_timezone": get_timezone,
            "GoogleCredentials": GoogleCredentials,
            "google_build": google_build,
            # New shared utilities
            "config_loader": config_loader,
            "lint_utils": lint_utils,
            "repo_utils": repo_utils,
            "slack_utils": slack_utils,
            # Nested skill runner - allows compute blocks to run other skills
            "run_skill": run_skill,
        }

        templated_code = self._template(code)
        namespace = {**safe_globals, **local_vars}
        exec(templated_code, namespace)  # pylint: disable=exec-used

        if output_name in namespace:
            result = namespace[output_name]
        elif "result" in namespace:
            result = namespace["result"]
        elif "return" in templated_code:
            for line in reversed(templated_code.split("\n")):
                if line.strip().startswith("return "):
                    expr = line.strip()[7:]
                    result = eval(expr, namespace)  # pylint: disable=eval-used
                    break
            else:
                result = None
        else:
            result = None

        # Update context with any new variables defined in the code
        for key in namespace:
            if key not in safe_globals and not key.startswith("_"):
                local_vars[key] = namespace[key]

        return result

    def _exec_compute(self, code: str, output_name: str):
        """Execute a compute block (limited Python) with error recovery."""
        self._debug(f"Executing compute block for '{output_name}'")

        try:
            result = self._exec_compute_internal(code, output_name)
            self._debug(f"  → Result: {str(result)[:100]}")
            return result

        except Exception as e:  # pylint: disable=broad-exception-caught
            self._debug(f"  → Compute error: {e}")

            # Try interactive recovery if enabled
            if self.enable_interactive_recovery and self.ask_question_fn:
                recovery_result = self._try_interactive_recovery(
                    code, str(e), output_name
                )
                if recovery_result is not None:
                    return recovery_result

            return f"<compute error: {e}>"
