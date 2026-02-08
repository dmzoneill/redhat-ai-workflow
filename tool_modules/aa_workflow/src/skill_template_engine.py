"""Skill Template Engine - Jinja2 templating, condition evaluation, and link formatting.

Extracted from SkillExecutor to separate template rendering concerns from
execution logic.

Provides:
- SkillTemplateEngine: Handles {{ variable }} resolution, condition evaluation,
  Jinja2 filters, and link formatting (Jira keys, MR IDs).
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class SkillTemplateEngine:
    """Handles Jinja2 templating, condition evaluation, and link formatting.

    Delegates to Jinja2 when available, with a regex-based fallback.

    Args:
        context: The execution context dict (shared with SkillExecutor).
        config: The application config dict (from config.json).
        inputs: The skill inputs dict.
        debug_fn: Optional callable for debug logging (e.g., SkillExecutor._debug).
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

    def _linkify_mr_ids(self, text, project=None):
        """Convert MR IDs to clickable links (Slack or Markdown format).

        Args:
            text: Text containing MR IDs like !42
            project: GitLab project path (e.g. "org/repo"). If not provided,
                     looks up the first repository's gitlab path from config.
        """
        if not text:
            return text

        is_slack = self.inputs.get("slack_format", False)
        gitlab_url = self.config.get("gitlab", {}).get(
            "url", "https://gitlab.cee.redhat.com"
        )
        if project is None:
            # Resolve from config: use the first repository's gitlab path
            repos = self.config.get("repositories", {})
            if repos:
                first_repo = next(iter(repos.values()), {})
                project = first_repo.get("gitlab", "")
            if not project:
                project = "unknown/project"

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
            except Exception as e:
                logger.debug(f"Suppressed error in template variable resolution: {e}")
                return match.group(0)

        return re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace_var, str(text))

    def template(self, text: str) -> str:
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

    def template_dict(self, d: dict) -> dict:
        """Recursively template a dictionary."""
        result: dict = {}
        for k, v in d.items():
            if isinstance(v, str):
                result[k] = self.template(v)
            elif isinstance(v, dict):
                result[k] = self.template_dict(v)
            elif isinstance(v, list):
                result[k] = [self.template(i) if isinstance(i, str) else i for i in v]
            else:
                result[k] = v
        return result

    def eval_condition(self, condition: str) -> bool:
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
            templated = self.template(condition)
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
