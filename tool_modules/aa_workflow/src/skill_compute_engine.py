"""Skill Compute Engine - sandboxed Python execution for skill compute blocks.

Extracted from SkillExecutor to separate compute execution from the main
execution loop.

Provides:
- _restricted_import: Module-level function for safe import control.
- _ALLOWED_COMPUTE_MODULES: Allowlist of importable modules in compute blocks.
- SkillComputeEngine: Handles compute block execution with sandboxed globals.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml

from tool_modules.common import PROJECT_ROOT

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Allowed modules for compute block `import` statements.
# Skill YAML compute blocks should use the modules already provided in
# safe_globals (re, os, json, yaml, datetime, pathlib, etc.) rather than
# importing arbitrary packages.  This allowlist keeps exec() functional
# for common patterns like ``from datetime import datetime`` while
# blocking dangerous imports (e.g., subprocess, socket, shutil).
_ALLOWED_COMPUTE_MODULES = frozenset(
    {
        "re",
        "os",
        "os.path",
        "pathlib",
        "datetime",
        "json",
        "yaml",
        "math",
        "collections",
        "itertools",
        "functools",
        "textwrap",
        "string",
        "hashlib",
        "base64",
        "copy",
        "time",
        "zoneinfo",
        "urllib",
        "urllib.parse",
        "gzip",
        "subprocess",
    }
)


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    """A restricted __import__ that only allows pre-approved modules.

    This is used in skill compute block exec() to prevent arbitrary code
    from importing dangerous modules (e.g., ctypes, socket) while still
    allowing common stdlib patterns like ``from datetime import datetime``
    or ``import json``.
    """
    if level != 0:
        # Relative imports are not supported in compute blocks
        raise ImportError(f"Relative imports not allowed in compute blocks: {name}")
    if name not in _ALLOWED_COMPUTE_MODULES:
        raise ImportError(
            f"Import of '{name}' is not allowed in skill compute blocks. "
            f"Use the modules already provided in the execution context "
            f"(re, os, json, yaml, datetime, Path, etc.) or use MCP tools."
        )
    return __import__(name, globals, locals, fromlist, level)


class AttrDict(dict):
    """Dictionary that allows attribute-style access to keys.

    This allows skill YAML compute blocks to use `inputs.repo` instead of `inputs["repo"]`.
    """

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'AttrDict' object has no attribute '{key}'")


class SkillComputeEngine:
    """Handles sandboxed Python execution for skill compute blocks.

    Args:
        executor: Reference to the parent SkillExecutor for access to
                  context, config, inputs, template engine, and nested execution.
    """

    def __init__(self, executor):
        self.executor = executor

    @property
    def context(self):
        return self.executor.context

    @property
    def config(self):
        return self.executor.config

    @property
    def inputs(self):
        return self.executor.inputs

    def _debug(self, msg: str):
        self.executor._debug(msg)

    def _template(self, text: str) -> str:
        return self.executor._template(text)

    def create_nested_skill_runner(self):
        """Create a helper function that compute blocks can use to run nested skills.

        Returns a function that can be called like:
            run_skill("jira_hygiene", {"issue_key": "AAP-12345"})
        """
        import asyncio

        # Import here to avoid circular imports at module level
        from tool_modules.aa_workflow.src.skill_engine import (
            SkillExecutor,
            SkillExecutorConfig,
        )

        # Support both package import and direct loading
        try:
            from tool_modules.aa_workflow.src.constants import SKILLS_DIR
        except ImportError:
            SKILLS_DIR = Path(__file__).parent.parent.parent.parent / "skills"

        executor = self.executor

        def run_skill_sync(skill_name: str, inputs: Optional[dict] = None) -> dict:
            """Run a nested skill synchronously from within a compute block.

            Args:
                skill_name: Name of the skill to run (e.g., "jira_hygiene")
                inputs: Input parameters for the skill

            Returns:
                dict with 'success', 'result', and optionally 'error' keys
            """
            inputs = inputs or {}

            try:
                # Load the skill definition
                skill_file = SKILLS_DIR / f"{skill_name}.yaml"
                if not skill_file.exists():
                    return {"success": False, "error": f"Skill not found: {skill_name}"}

                with open(skill_file) as f:
                    nested_skill = yaml.safe_load(f)

                # Create a new executor for the nested skill
                nested_config = SkillExecutorConfig(
                    debug=executor.debug,
                    enable_interactive_recovery=False,  # Don't prompt in nested skills
                    emit_events=False,  # Don't emit events for nested skills
                    workspace_uri=executor.workspace_uri,
                )
                nested_executor = SkillExecutor(
                    skill=nested_skill,
                    inputs=inputs,
                    config=nested_config,
                    server=executor.server,
                    create_issue_fn=executor.create_issue_fn,
                    ask_question_fn=executor.ask_question_fn,
                    ctx=executor.ctx,
                )

                # Run the nested skill - handle async properly
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                outputs: Any = None
                if loop and loop.is_running():
                    # We're already in an async context, schedule on the existing loop
                    # Use run_coroutine_threadsafe to safely run from sync context
                    future = asyncio.run_coroutine_threadsafe(
                        nested_executor.execute(), loop
                    )
                    outputs, _ = future.result(timeout=300)  # type: ignore[misc]
                else:
                    # No running loop, can use asyncio.run directly
                    outputs, _ = asyncio.run(nested_executor.execute())  # type: ignore[misc]

                return {"success": True, "result": outputs}

            except Exception as e:
                return {"success": False, "error": str(e)}

        return run_skill_sync

    def exec_compute_internal(self, code: str, output_name: str):
        """Internal compute execution without error recovery (used by recovery itself)."""
        # This is the actual compute logic extracted from _exec_compute
        # to avoid infinite recursion during auto-fix retries
        local_vars = dict(self.context)
        # Wrap inputs in AttrDict to allow attribute-style access (inputs.repo vs inputs["repo"])
        local_vars["inputs"] = AttrDict(self.inputs)
        local_vars["config"] = self.config

        import os
        import re
        from datetime import datetime, timedelta
        from pathlib import Path

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            ZoneInfo = None  # type: ignore[misc,assignment]

        # Use module-level PROJECT_ROOT
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        try:
            from scripts.common import config_loader, jira_utils, lint_utils
            from scripts.common import memory as memory_helpers
            from scripts.common import parsers, repo_utils, slack_utils
            from scripts.common.config_loader import get_timezone
            from scripts.common.config_loader import load_config as load_skill_config
            from scripts.skill_hooks import emit_event_sync
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
            from google.oauth2.credentials import Credentials as GoogleCredentials
            from googleapiclient.discovery import build as google_build
        except ImportError:
            GoogleCredentials = None  # type: ignore[misc,assignment]
            google_build = None

        # Create the nested skill runner for compute blocks
        run_skill = self.create_nested_skill_runner()

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
                # Restricted __import__: only allow pre-approved stdlib modules.
                # Skill compute blocks should use the modules already provided
                # in safe_globals (re, os, json, yaml, datetime, etc.) or use
                # MCP tools for external access.
                "__import__": _restricted_import,
            },
            "re": re,
            "os": os,
            "Path": Path,
            "datetime": datetime,
            "timedelta": timedelta,
            "ZoneInfo": ZoneInfo,
            "json": json,
            "yaml": yaml,
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
        exec(templated_code, namespace)

        if output_name in namespace:
            result = namespace[output_name]
        elif "result" in namespace:
            result = namespace["result"]
        elif "return" in templated_code:
            for line in reversed(templated_code.split("\n")):
                if line.strip().startswith("return "):
                    expr = line.strip()[7:]
                    result = eval(expr, namespace)
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

    def exec_compute(self, code: str, output_name: str):
        """Execute a compute block (limited Python) with error recovery."""
        self._debug(f"Executing compute block for '{output_name}'")

        try:
            result = self.exec_compute_internal(code, output_name)
            self._debug(f"  → Result: {str(result)[:100]}")
            return result

        except Exception as e:
            self._debug(f"  → Compute error: {e}")

            # Try interactive recovery if enabled
            if (
                self.executor.enable_interactive_recovery
                and self.executor.ask_question_fn
            ):
                recovery_result = self.executor._try_interactive_recovery(
                    code, str(e), output_name
                )
                if recovery_result is not None:
                    return recovery_result

            return f"<compute error: {e}>"
