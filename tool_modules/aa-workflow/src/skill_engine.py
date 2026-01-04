"""Skill Execution Engine - Multi-step workflow execution.

Provides:
- skill_list: List available skills
- skill_run: Execute a skill
- SkillExecutor: Class that handles step-by-step execution
"""

import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Support both package import and direct loading
try:
    from .constants import SKILLS_DIR, TOOL_MODULES_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    SKILLS_DIR = PROJECT_DIR / "skills"

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Add project root to path for server utilities
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from server.utils import load_config

# Import known issues checker from debuggable module
try:
    from server.debuggable import _check_known_issues_sync, _format_known_issues
except ImportError:
    # Fallback if debuggable not available
    def _check_known_issues_sync(tool_name="", error_text=""):
        return []

    def _format_known_issues(matches):
        return ""


class SkillExecutor:
    """Full skill execution engine with debug support."""

    def __init__(
        self,
        skill: dict,
        inputs: dict,
        debug: bool = False,
        server: FastMCP = None,
        create_issue_fn=None,
    ):
        self.skill = skill
        self.inputs = inputs
        self.debug = debug
        self.server = server
        self.create_issue_fn = create_issue_fn
        # Load config.json config for compute blocks
        self.config = load_config()
        self.context = {
            "inputs": inputs,
            "config": self.config,
        }
        self.log: list[str] = []
        self.step_results: list[dict] = []
        self.start_time = None

    def _debug(self, msg: str):
        """Add debug message."""
        if self.debug:
            import time

            elapsed = f"[{time.time() - self.start_time:.2f}s]" if self.start_time else ""
            self.log.append(f"🔍 {elapsed} {msg}")

    def _check_error_patterns(self, error: str) -> str | None:
        """Check if error matches known patterns and return fix suggestion."""
        try:
            patterns_file = SKILLS_DIR.parent / "memory" / "learned" / "patterns.yaml"
            if not patterns_file.exists():
                return None

            with open(patterns_file) as f:
                patterns_data = yaml.safe_load(f) or {}

            error_patterns = patterns_data.get("error_patterns", [])
            error_lower = error.lower()

            for pattern in error_patterns:
                pattern_text = pattern.get("pattern", "").lower()
                if pattern_text and pattern_text in error_lower:
                    fix = pattern.get("fix", "")
                    meaning = pattern.get("meaning", "")
                    commands = pattern.get("commands", [])

                    suggestion = f"\n   💡 **Known pattern: {pattern.get('pattern')}**"
                    if meaning:
                        suggestion += f"\n   *{meaning}*"
                    if fix:
                        suggestion += f"\n   **Fix:** {fix}"
                    if commands:
                        suggestion += "\n   **Try:**"
                        for cmd in commands[:3]:
                            suggestion += f"\n   - `{cmd}`"
                    return suggestion

            return None
        except Exception as e:
            self._debug(f"Pattern lookup failed: {e}")
            return None

    def _template(self, text: str) -> str:
        """Resolve {{ variable }} templates in text."""
        import re

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

        result = re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace_var, str(text))
        return result

    def _template_dict(self, d: dict) -> dict:
        """Recursively template a dictionary."""
        result = {}
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
        """Safely evaluate a condition expression."""
        self._debug(f"Evaluating condition: {condition}")
        templated = self._template(condition)
        self._debug(f"  → Templated: {templated}")

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
            # Default to False on error - safer to skip than to run with invalid state
            return False

    def _exec_compute(self, code: str, output_name: str):
        """Execute a compute block (limited Python)."""
        self._debug(f"Executing compute block for '{output_name}'")

        local_vars = dict(self.context)
        local_vars["inputs"] = self.inputs
        local_vars["config"] = self.config

        import os
        import re
        from datetime import datetime, timedelta
        from pathlib import Path

        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            ZoneInfo = None

        PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
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
            parsers = None
            jira_utils = None
            load_skill_config = None
            get_timezone = None
            emit_event_sync = None
            memory_helpers = None
            config_loader = None
            lint_utils = None
            repo_utils = None
            slack_utils = None

        try:
            from google.oauth2.credentials import Credentials as GoogleCredentials
            from googleapiclient.discovery import build as google_build
        except ImportError:
            GoogleCredentials = None
            google_build = None

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
        }

        try:
            templated_code = self._template(code)
            self._debug(f"  → Code: {templated_code[:100]}...")

            # Merge globals and locals into single namespace to avoid
            # Python scoping issues with generator expressions/comprehensions
            # (they create their own scope and can't see separate locals)
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

            self._debug(f"  → Result: {str(result)[:100]}")
            return result

        except Exception as e:
            self._debug(f"  → Compute error: {e}")
            return f"<compute error: {e}>"

    async def _exec_tool(self, tool_name: str, args: dict) -> dict:
        """Execute a tool and return its result."""
        import time

        start = time.time()

        self._debug(f"Calling tool: {tool_name}")
        self._debug(f"  → Args: {json.dumps(args)[:200]}")

        module_prefixes = {
            "git_": "git",
            "jira_": "jira",
            "gitlab_": "gitlab",
            "slack_": "slack",
            "kubectl_": "k8s",
            "k8s_": "k8s",
            "prometheus_": "prometheus",
            "alertmanager_": "alertmanager",
            "kibana_": "kibana",
            "konflux_": "konflux",
            "tkn_": "konflux",
            "bonfire_": "bonfire",
            "quay_": "quay",
            "appinterface_": "appinterface",
            # Lint module tools (developer-specific)
            "lint_": "lint",
            "test_": "lint",
            "security_": "lint",
            "precommit_": "lint",
            # Dev-workflow module tools (developer-specific)
            "workflow_": "dev-workflow",
            # Core workflow module tools (always loaded)
            "memory_": "workflow",
            "persona_": "workflow",
            "skill_": "workflow",
            "session_": "workflow",
            "tool_": "workflow",
            "vpn_": "workflow",
            "kube_": "workflow",
            "debug_": "workflow",
        }

        module = None
        for prefix, mod in module_prefixes.items():
            if tool_name.startswith(prefix):
                module = mod
                break

        if not module:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        if module == "workflow" and self.server:
            try:
                result = await self.server.call_tool(tool_name, args)
                duration = time.time() - start
                self._debug(f"  → Completed in {duration:.2f}s")

                if isinstance(result, tuple):
                    result = result[0]
                if isinstance(result, list) and result:
                    text = result[0].text if hasattr(result[0], "text") else str(result[0])
                    return {"success": True, "result": text, "duration": duration}
                return {"success": True, "result": str(result), "duration": duration}
            except Exception as e:
                return {"success": False, "error": str(e)}

        tools_file = TOOL_MODULES_DIR / f"aa-{module}" / "src" / "tools.py"

        if not tools_file.exists():
            return {"success": False, "error": f"Module not found: {module}"}

        try:
            import importlib.util

            temp_server = FastMCP(f"skill-{module}")
            spec = importlib.util.spec_from_file_location(f"skill_{module}", tools_file)
            if spec is None or spec.loader is None:
                return {"success": False, "error": f"Could not load: {module}"}

            loaded_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded_module)

            if hasattr(loaded_module, "register_tools"):
                loaded_module.register_tools(temp_server)

            result = await temp_server.call_tool(tool_name, args)
            duration = time.time() - start

            self._debug(f"  → Completed in {duration:.2f}s")

            if isinstance(result, tuple):
                result = result[0]
            if isinstance(result, list) and result:
                text = result[0].text if hasattr(result[0], "text") else str(result[0])
                return {"success": True, "result": text, "duration": duration}

            return {"success": True, "result": str(result), "duration": duration}

        except Exception as e:
            error_msg = str(e)
            self._debug(f"  → Error: {error_msg}")

            # Check for known issues
            matches = _check_known_issues_sync(tool_name=tool_name, error_text=error_msg)
            known_text = _format_known_issues(matches)

            if known_text:
                error_msg = f"{error_msg}\n{known_text}"
                self._debug(f"  → Found {len(matches)} known issue(s)")

            return {"success": False, "error": error_msg}

    async def execute(self) -> str:
        """Execute all steps and return the result."""
        import time

        self.start_time = time.time()

        skill_name = self.skill.get("name", "unknown")
        self._debug(f"Starting skill: {skill_name}")
        self._debug(f"Inputs: {json.dumps(self.inputs)}")

        for inp in self.skill.get("inputs", []):
            name = inp["name"]
            if name not in self.inputs and "default" in inp:
                self.inputs[name] = inp["default"]
                self.context["inputs"] = self.inputs
                self._debug(f"Applied default: {name} = {inp['default']}")

        defaults = self.skill.get("defaults", {})
        self.context["defaults"] = defaults

        output_lines = [f"## 🚀 Executing Skill: {skill_name}\n"]
        output_lines.append(f"*{self.skill.get('description', '')}*\n")

        if self.debug:
            output_lines.append("### 📋 Inputs")
            for k, v in self.inputs.items():
                output_lines.append(f"- `{k}`: {v}")
            output_lines.append("")

        output_lines.append("### 📝 Execution Log\n")

        step_num = 0
        for step in self.skill.get("steps", []):
            step_num += 1
            step_name = step.get("name", f"step_{step_num}")

            if "condition" in step:
                if not self._eval_condition(step["condition"]):
                    self._debug(f"Skipping step '{step_name}' - condition false")
                    output_lines.append(f"⏭️ **Step {step_num}: {step_name}** - *skipped (condition false)*\n")
                    continue

            if "then" in step:
                self._debug("Processing 'then' block")
                for then_item in step["then"]:
                    if "return" in then_item:
                        ret = then_item["return"]
                        templated = self._template_dict(ret) if isinstance(ret, dict) else self._template(str(ret))
                        self._debug(f"Early return: {templated}")

                        total_time = time.time() - self.start_time
                        output_lines.append(f"✅ **Early Exit**\n{templated}\n")
                        output_lines.append(f"\n---\n⏱️ *Completed in {total_time:.2f}s*")

                        if self.debug and self.log:
                            output_lines.append("\n\n### 🔍 Debug Log\n```")
                            output_lines.extend(self.log)
                            output_lines.append("```")

                        return "\n".join(output_lines)
                continue

            if "tool" in step:
                tool = step["tool"]
                raw_args = step.get("args", {})
                args = self._template_dict(raw_args)

                output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
                output_lines.append(f"   *Tool: `{tool}`*")

                result = await self._exec_tool(tool, args)

                if result["success"]:
                    output_name = step.get("output", step_name)
                    self.context[output_name] = result["result"]

                    try:
                        if ":" in result["result"]:
                            parsed = {}
                            for line in result["result"].split("\n"):
                                if ":" in line and not line.strip().startswith("#"):
                                    key, _, val = line.partition(":")
                                    parsed[key.strip().lower().replace(" ", "_")] = val.strip()
                            if parsed:
                                self.context[f"{output_name}_parsed"] = parsed
                    except Exception:
                        pass

                    duration = result.get("duration", 0)
                    output_lines.append(f"   ✅ Success ({duration:.2f}s)")

                    result_preview = result["result"][:300]
                    if len(result["result"]) > 300:
                        result_preview += "..."
                    output_lines.append(f"   ```\n   {result_preview}\n   ```\n")

                    self.step_results.append({"step": step_name, "tool": tool, "success": True, "duration": duration})
                else:
                    output_lines.append(f"   ❌ Error: {result['error']}")

                    # Check for known error patterns
                    pattern_hint = self._check_error_patterns(result["error"])
                    if pattern_hint:
                        output_lines.append(pattern_hint)

                    if self.create_issue_fn:
                        skill_name = self.skill.get("name", "unknown")
                        context = f"Skill: {skill_name}, Step: {step_name}"

                        try:
                            issue_result = await self.create_issue_fn(
                                tool=tool,
                                error=result["error"],
                                context=context,
                                skill=skill_name,
                            )

                            if issue_result["success"]:
                                output_lines.append(f"\n   🐛 **Issue created:** {issue_result['issue_url']}")
                            elif issue_result["issue_url"]:
                                output_lines.append("\n   💡 **Report this error:**")
                                output_lines.append(f"   📝 [Create GitHub Issue]({issue_result['issue_url']})")
                        except Exception as e:
                            self._debug(f"Failed to create issue: {e}")

                    on_error = step.get("on_error", "fail")
                    if on_error == "continue":
                        output_lines.append("   *Continuing despite error (on_error: continue)*\n")
                        self.step_results.append(
                            {
                                "step": step_name,
                                "tool": tool,
                                "success": False,
                                "error": result["error"],
                            }
                        )
                    else:
                        output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
                        break

            elif "compute" in step:
                output_name = step.get("output", step_name)
                output_lines.append(f"🧮 **Step {step_num}: {step_name}** (compute)")

                result = self._exec_compute(step["compute"], output_name)
                self.context[output_name] = result

                output_lines.append(f"   → `{output_name}` = {str(result)[:100]}\n")

            elif "description" in step:
                output_lines.append(f"📝 **Step {step_num}: {step_name}** (manual)")
                output_lines.append(f"   {self._template(step['description'])}\n")

        if self.skill.get("outputs"):
            output_lines.append("\n### 📤 Outputs\n")
            for out in self.skill["outputs"]:
                out_name = out.get("name", "output")
                if "value" in out:
                    templated = self._template(out["value"])
                    output_lines.append(f"**{out_name}:**\n{templated}\n")
                elif "compute" in out:
                    result = self._exec_compute(out["compute"], out_name)
                    output_lines.append(f"**{out_name}:** {result}\n")

        total_time = time.time() - self.start_time
        success_count = sum(1 for r in self.step_results if r.get("success"))
        fail_count = sum(1 for r in self.step_results if not r.get("success"))

        output_lines.append(
            f"\n---\n⏱️ *Completed in {total_time:.2f}s* | " f"✅ {success_count} succeeded | ❌ {fail_count} failed"
        )

        if self.debug and self.log:
            output_lines.append("\n\n### 🔍 Debug Log\n```")
            output_lines.extend(self.log)
            output_lines.append("```")

        return "\n".join(output_lines)


def register_skill_tools(server: "FastMCP", create_issue_fn=None) -> int:
    """Register skill tools with the MCP server."""
    tool_count = 0

    @server.tool()
    async def skill_list() -> list[TextContent]:
        """
        List all available skills (reusable workflows).

        Skills are multi-step workflows that combine MCP tools with logic.
        Use skill_run() to execute a skill.

        Returns:
            List of available skills with descriptions.
        """
        skills = []
        if SKILLS_DIR.exists():
            for f in SKILLS_DIR.glob("*.yaml"):
                if f.name == "README.md":
                    continue
                try:
                    with open(f) as fp:
                        data = yaml.safe_load(fp)
                    skills.append(
                        {
                            "name": data.get("name", f.stem),
                            "description": data.get("description", "No description"),
                            "inputs": [i["name"] for i in data.get("inputs", [])],
                        }
                    )
                except Exception as e:
                    skills.append({"name": f.stem, "description": f"Error loading: {e}", "inputs": []})

        if not skills:
            return [TextContent(type="text", text="No skills found. Create .yaml files in skills/ directory.")]

        lines = ["## Available Skills\n"]
        for s in skills:
            inputs = ", ".join(s["inputs"]) if s["inputs"] else "none"
            lines.append(f"### {s['name']}")
            lines.append(f"{s['description']}")
            lines.append(f"**Inputs:** {inputs}\n")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def skill_run(
        skill_name: str, inputs: str = "{}", execute: bool = True, debug: bool = False
    ) -> list[TextContent]:
        """
        Execute a skill (multi-step workflow).

        Skills chain multiple MCP tools together with logic and conditions.

        Args:
            skill_name: Name of the skill (e.g., "start_work", "investigate_alert")
            inputs: JSON object with input parameters
            execute: If True (default), run the tools. If False, just show the plan.
            debug: If True, show detailed execution trace with timing.

        Returns:
            Execution results or plan preview.
        """
        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            available = [f.stem for f in SKILLS_DIR.glob("*.yaml")] if SKILLS_DIR.exists() else []
            return [
                TextContent(
                    type="text",
                    text=f"❌ Skill not found: {skill_name}\n\n" f"Available: {', '.join(available) or 'none'}",
                )
            ]

        try:
            with open(skill_file) as f:
                skill = yaml.safe_load(f)

            try:
                input_data = json.loads(inputs) if inputs else {}
            except json.JSONDecodeError:
                return [TextContent(type="text", text=f"❌ Invalid inputs JSON: {inputs}")]

            missing = []
            for inp in skill.get("inputs", []):
                if inp.get("required", False) and inp["name"] not in input_data:
                    if "default" not in inp:
                        missing.append(inp["name"])

            if missing:
                lines = [f"❌ Missing required inputs: {', '.join(missing)}\n"]
                lines.append("### Required Inputs\n")
                for inp in skill.get("inputs", []):
                    req = "**required**" if inp.get("required") else "optional"
                    default = f" (default: {inp['default']})" if "default" in inp else ""
                    lines.append(f"- `{inp['name']}` ({inp.get('type', 'string')}) - {req}{default}")
                    if inp.get("description"):
                        lines.append(f"  {inp['description']}")
                return [TextContent(type="text", text="\n".join(lines))]

            if not execute:
                lines = [f"## 📋 Skill Plan: {skill.get('name', skill_name)}\n"]
                lines.append(f"*{skill.get('description', '')}*\n")
                lines.append("### Inputs")
                for k, v in input_data.items():
                    lines.append(f"- `{k}`: {v}")
                lines.append("\n### Steps to Execute\n")

                step_num = 0
                for step in skill.get("steps", []):
                    step_num += 1
                    name = step.get("name", f"step_{step_num}")

                    if "tool" in step:
                        lines.append(f"{step_num}. **{name}** → `{step['tool']}`")
                        if step.get("condition"):
                            lines.append(f"   *Condition: {step['condition']}*")
                    elif "compute" in step:
                        lines.append(f"{step_num}. **{name}** → compute")
                    elif "description" in step:
                        lines.append(f"{step_num}. **{name}** → manual step")

                lines.append("\n*Run with `execute=True` to execute this plan*")
                return [TextContent(type="text", text="\n".join(lines))]

            executor = SkillExecutor(skill, input_data, debug=debug, server=server, create_issue_fn=create_issue_fn)
            result = await executor.execute()

            return [TextContent(type="text", text=result)]

        except Exception as e:
            import traceback

            if debug:
                return [TextContent(type="text", text=f"❌ Error: {e}\n\n```\n{traceback.format_exc()}\n```")]
            return [TextContent(type="text", text=f"❌ Error loading skill: {e}")]

    tool_count += 1

    return tool_count
