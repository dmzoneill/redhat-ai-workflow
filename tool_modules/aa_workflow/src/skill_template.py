"""Template and compute engine for skill execution."""

from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import yaml

from tool_modules.common import PROJECT_ROOT

from .constants import SKILLS_DIR

if TYPE_CHECKING:
    pass


def _get_attr_dict():
    """Import AttrDict lazily to avoid circular import with skill_engine."""
    from .skill_engine import AttrDict

    return AttrDict


class TemplateEngineMixin:
    """Mixin providing template rendering and compute block execution."""

    def _linkify_jira_keys(self, text):
        """Convert Jira keys to clickable links (Slack or Markdown format)."""
        if not text:
            return text

        is_slack = self.inputs.get("slack_format", False)
        jira_url = self.config.get("jira", {}).get("url", "https://issues.redhat.com")

        pattern = re.compile(r"\b([A-Z]+-\d+)(-[\w-]+)?\b")

        def replace(match):
            key = match.group(1)
            suffix = match.group(2) or ""
            if is_slack:
                return f"<{jira_url}/browse/{key}|{key}{suffix}>"
            return f"[{key}{suffix}]({jira_url}/browse/{key})"

        return pattern.sub(replace, str(text))

    def _linkify_mr_ids(self, text):
        """Convert MR IDs to clickable links (Slack or Markdown format)."""
        if not text:
            return text

        is_slack = self.inputs.get("slack_format", False)
        gitlab_url = self.config.get("gitlab", {}).get(
            "url", "https://gitlab.cee.redhat.com"
        )
        project = "automation-analytics/automation-analytics-backend"

        pattern = re.compile(r"!(\d+)")

        def replace(match):
            mr_id = match.group(1)
            url = f"{gitlab_url}/{project}/-/merge_requests/{mr_id}"
            if is_slack:
                return f"<{url}|!{mr_id}>"
            return f"[!{mr_id}]({url})"

        return pattern.sub(replace, str(text))

    def _create_jinja_filters(self):
        """Create Jinja2 custom filters for template rendering."""
        return {
            "jira_link": self._linkify_jira_keys,
            "mr_link": self._linkify_mr_ids,
            "length": len,
        }

    def _template_with_regex_fallback(self, text: str) -> str:
        """Template replacement using regex (fallback when Jinja2 unavailable)."""

        def replace_var(match):
            var_path = match.group(1).strip()
            try:
                value = self.context
                parts = var_path.split(".")

                for part in parts:
                    array_match = re.match(r"^(\w+)\[(\d+)\]$", part)
                    if array_match:
                        var_name, index = array_match.groups()
                        index = int(index)
                        if isinstance(value, dict):
                            value = value.get(var_name)
                        elif hasattr(value, var_name):
                            value = getattr(value, var_name)
                        else:
                            return match.group(0)
                        if isinstance(value, (list, tuple)) and index < len(value):
                            value = value[index]
                        else:
                            return match.group(0)
                    elif isinstance(value, dict):
                        value = value.get(part, match.group(0))
                        if value == match.group(0):
                            return value
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        return match.group(0)
                return str(value) if value is not None else ""
            except Exception:
                return match.group(0)

        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace_var, str(text))

    def _template(self, text: str) -> str:
        """Resolve {{ variable }} templates in text using Jinja2 if available.

        Uses ChainableUndefined to allow attribute access on undefined variables
        (returns empty string) while still catching completely missing variables
        in debug mode.
        """
        if not isinstance(text, str) or "{{" not in text:
            return text

        try:
            from jinja2 import ChainableUndefined, Environment

            # autoescape=False to preserve Slack link format <url|text>
            # Skills don't generate HTML, they generate plain text and Slack markdown
            # ChainableUndefined allows {{ foo.bar.baz }} to return "" if foo is undefined
            # but still allows chained attribute access without errors
            env = Environment(autoescape=False, undefined=ChainableUndefined)
            env.filters.update(self._create_jinja_filters())

            template = env.from_string(text)
            rendered = template.render(**self.context)

            # Warn if template rendered to empty when it had variables
            # This helps catch cases where context variables are missing
            if rendered == "" and "{{" in text:
                self._debug(f"WARNING: Template rendered to empty string: {text[:100]}")

            return rendered
        except ImportError:
            return self._template_with_regex_fallback(text)
        except Exception as e:
            self._debug(f"Template error: {e}")
            return text

    def _template_dict(self, d: dict) -> dict:
        """Recursively template a dictionary."""
        result: dict = {}
        for k, v in d.items():
            if isinstance(v, str):
                result[k] = self._template(v)
            elif isinstance(v, dict):
                result[k] = self._template_dict(v)
            elif isinstance(v, list):
                result[k] = [self._template(i) if isinstance(i, str) else i for i in v]
            else:
                result[k] = v
        return result

    def _eval_condition(self, condition: str) -> bool:
        """Safely evaluate a condition expression using Jinja2 if available."""
        self._debug(f"Evaluating condition: {condition}")

        try:
            from jinja2 import Environment

            # autoescape=False - conditions don't need HTML escaping
            env = Environment(autoescape=False)
            # Wrap condition in {{ }} if not already there for Jinja evaluation
            if "{{" not in condition:
                expr = "{{ " + condition + " }}"
            else:
                expr = condition

            result_str = env.from_string(expr).render(**self.context).strip()
            self._debug(f"  → Rendered condition: '{condition}' = '{result_str}'")
            # If it's a boolean-like string, convert it
            if result_str.lower() in ("true", "1", "yes"):
                return True
            if result_str.lower() in ("false", "0", "no", "", "none"):
                return False
            # Otherwise check if it's non-empty
            return bool(result_str)
        except ImportError:
            # Fallback to eval
            templated = self._template(condition)
            self._debug(f"  → Templated (fallback): {templated}")

            safe_context = {
                "len": len,
                "any": any,
                "all": all,
                "isinstance": isinstance,
                "type": type,
                "hasattr": hasattr,
                "dir": dir,
                "str": str,
                "int": int,
                "float": float,
                "list": list,
                "dict": dict,
                "bool": bool,
                "True": True,
                "False": False,
                "None": None,
                **self.context,
            }

            try:
                result = eval(templated, {"__builtins__": {}}, safe_context)
                self._debug(f"  → Result: {result}")
                return bool(result)
            except Exception as e:
                self._debug(f"  → Error: {e}, defaulting to False")
                return False
        except Exception as e:
            self._debug(f"  → Jinja eval error: {e}, defaulting to False")
            return False

    def _create_nested_skill_runner(self):
        """Create a helper function that compute blocks can use to run nested skills.

        Returns a function that can be called like:
            run_skill("jira_hygiene", {"issue_key": "AAP-12345"})
        """
        import asyncio

        # Late import to avoid circular import - SkillExecutor is in skill_engine
        from .skill_engine import SkillExecutor

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

                with open(skill_file, encoding="utf-8") as f:
                    nested_skill = yaml.safe_load(f)

                # Create a new executor for the nested skill
                nested_executor = SkillExecutor(
                    skill=nested_skill,
                    inputs=inputs,
                    debug=self.debug,
                    server=self.server,
                    create_issue_fn=self.create_issue_fn,
                    ask_question_fn=self.ask_question_fn,
                    enable_interactive_recovery=False,  # Don't prompt in nested skills
                    emit_events=False,  # Don't emit events for nested skills
                    workspace_uri=self.workspace_uri,
                    ctx=self.ctx,
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

    def _exec_compute_internal(self, code: str, output_name: str):
        """Internal compute execution without error recovery (used by recovery itself)."""
        AttrDict = _get_attr_dict()

        local_vars = dict(self.context)
        # Wrap inputs in AttrDict to allow attribute-style access (inputs.repo vs inputs["repo"])
        local_vars["inputs"] = AttrDict(self.inputs)
        local_vars["config"] = self.config

        import os

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

    def _exec_compute(self, code: str, output_name: str):
        """Execute a compute block (limited Python) with error recovery."""
        self._debug(f"Executing compute block for '{output_name}'")

        try:
            result = self._exec_compute_internal(code, output_name)
            self._debug(f"  → Result: {str(result)[:100]}")
            return result

        except Exception as e:
            self._debug(f"  → Compute error: {e}")

            # Try interactive recovery if enabled
            if self.enable_interactive_recovery and self.ask_question_fn:
                recovery_result = self._try_interactive_recovery(
                    code, str(e), output_name
                )
                if recovery_result is not None:
                    return recovery_result

            return f"<compute error: {e}>"

    def _parse_and_store_tool_result(self, result_text: str, output_name: str):
        """Parse key:value output from tool result and store in context."""
        try:
            if ":" in result_text:
                parsed = {}
                for line in result_text.split("\n"):
                    if ":" in line and not line.strip().startswith("#"):
                        key, _, val = line.partition(":")
                        parsed[key.strip().lower().replace(" ", "_")] = val.strip()
                if parsed:
                    self.context[f"{output_name}_parsed"] = parsed
        except Exception as exc:
            import logging

            logging.getLogger(__name__).debug("Suppressed error: %s", exc)
