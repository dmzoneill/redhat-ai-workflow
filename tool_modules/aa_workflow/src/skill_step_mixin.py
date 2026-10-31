# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""

import asyncio
import logging
import re
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


# Strong references to fire-and-forget tasks so they are not garbage-collected mid-run
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _spawn_background(coro: Coroutine[Any, Any, Any]) -> None:
    """Start a fire-and-forget task and keep a reference until it finishes."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class SkillStepMixin:  # pylint: disable=too-few-public-methods
    """SkillExecutor behavior split out of skill_engine."""

    # Declared for mixins that read sibling state.
    _attempt_auto_heal: Any
    _check_error_patterns: Any
    _debug: Any
    _detect_auto_heal_type: Any
    _exec_compute: Any
    _exec_tool: Any
    _learn_from_error: Any
    _log_auto_heal_to_memory: Any
    _template: Any
    _template_dict: Any
    context: Any
    create_issue_fn: Any
    debug: Any
    event_emitter: Any
    log: Any
    skill: Any
    skill_id: Any
    start_time: Any
    step_results: Any
    ws_server: Any

    async def _handle_tool_error(  # pylint: disable=too-many-branches,too-many-locals,too-many-statements
        self,
        tool: str,
        step: dict,
        step_name: str,
        error_msg: str,
        output_lines: list[str],
    ) -> bool:
        """Handle tool execution error.

        Returns:
            True if processing should continue, False if skill should stop
        """
        output_lines.append(f"   ❌ Error: {error_msg}")

        # Check for known error patterns
        pattern_hint = self._check_error_patterns(error_msg)
        if pattern_hint:
            output_lines.append(pattern_hint)

        on_error = step.get("on_error", "fail")

        # Handle auto_heal mode - try to fix and retry before giving up
        if on_error == "auto_heal":
            heal_type, cluster = self._detect_auto_heal_type(error_msg)

            if heal_type:
                output_lines.append(f"   🩹 Detected {heal_type} error, attempting auto-heal...")

                # Emit auto-heal triggered event (WebSocket)
                if self.ws_server and self.ws_server.is_running:
                    # Get current step index from event_emitter or calculate it
                    step_idx = self.event_emitter.current_step_index if self.event_emitter else 0
                    _spawn_background(
                        self.ws_server.auto_heal_triggered(
                            skill_id=self.skill_id,
                            step_index=step_idx,
                            error_type=heal_type,
                            fix_action=(f"kube_login({cluster})" if heal_type == "auth" else "vpn_connect()"),
                            error_snippet=error_msg[:200],
                        )
                    )

                # Emit toast notification for auto-heal triggered
                try:
                    # pylint: disable-next=import-outside-toplevel
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_auto_heal_triggered,
                    )

                    fix_action = f"kube_login({cluster})" if heal_type == "auth" else "vpn_connect()"
                    notify_auto_heal_triggered(step_name, heal_type, fix_action)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.debug("Suppressed error: %s", exc, exc_info=True)

                retry_result = await self._attempt_auto_heal(heal_type, cluster, tool, step, output_lines)

                if retry_result and retry_result.get("success"):
                    # Auto-heal worked! Store result and continue
                    output_lines.append("   ✅ Auto-heal successful!")
                    output_name = step.get("output", step_name)
                    self.context[output_name] = retry_result["result"]
                    self._parse_and_store_tool_result(retry_result["result"], output_name)

                    # Log success to memory
                    await self._log_auto_heal_to_memory(tool, heal_type, error_msg[:100], success=True)

                    # Emit auto-heal completed event (WebSocket)
                    if self.ws_server and self.ws_server.is_running:
                        step_idx = self.event_emitter.current_step_index if self.event_emitter else 0
                        _spawn_background(
                            self.ws_server.auto_heal_completed(
                                skill_id=self.skill_id,
                                step_index=step_idx,
                                fix_action=heal_type,
                                success=True,
                            )
                        )

                    # Emit toast notification for auto-heal success
                    try:
                        # pylint: disable-next=import-outside-toplevel
                        from tool_modules.aa_workflow.src.notification_emitter import (
                            notify_auto_heal_succeeded,
                        )

                        notify_auto_heal_succeeded(step_name, heal_type)
                    except Exception as exc:  # pylint: disable=broad-exception-caught
                        logger.debug("Suppressed error: %s", exc, exc_info=True)

                    self.step_results.append(
                        {
                            "step": step_name,
                            "tool": tool,
                            "success": True,
                            "auto_healed": True,
                            "heal_type": heal_type,
                        }
                    )
                    return True
                # Auto-heal failed, log and continue
                output_lines.append("   ⚠️ Auto-heal failed, continuing anyway...")
                await self._log_auto_heal_to_memory(tool, heal_type, error_msg[:100], success=False)

                # Emit auto-heal completed (failed) event (WebSocket)
                if self.ws_server and self.ws_server.is_running:
                    step_idx = self.event_emitter.current_step_index if self.event_emitter else 0
                    _spawn_background(
                        self.ws_server.auto_heal_completed(
                            skill_id=self.skill_id,
                            step_index=step_idx,
                            fix_action=heal_type,
                            success=False,
                        )
                    )

                # Emit toast notification for auto-heal failure
                try:
                    # pylint: disable-next=import-outside-toplevel
                    from tool_modules.aa_workflow.src.notification_emitter import (
                        notify_auto_heal_failed,
                    )

                    notify_auto_heal_failed(step_name, error_msg[:100])
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    logger.debug("Suppressed error: %s", exc, exc_info=True)
            else:
                output_lines.append("   ℹ️ Error not auto-healable, continuing...")

            # Fall through to continue behavior
            output_lines.append("   *Continuing despite error (on_error: auto_heal)*\n")

            # Set output variable to None so downstream compute steps don't crash
            # with NameError when referencing this step's output
            output_name = step.get("output", step_name)
            if output_name not in self.context:
                self.context[output_name] = None

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {k: self._template(str(v)) for k, v in args_data.items()}

            await self._learn_from_error(tool_name=tool, params=tool_params, error_msg=error_msg)

            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": error_msg,
                    "auto_heal_attempted": heal_type is not None,
                }
            )
            return True

        if self.create_issue_fn:
            skill_name = self.skill.get("name", "unknown")
            context = f"Skill: {skill_name}, Step: {step_name}"

            try:
                issue_result = await self.create_issue_fn(
                    tool=tool,
                    error=error_msg,
                    context=context,
                    skill=skill_name,
                )

                if issue_result["success"]:
                    output_lines.append(f"\n   🐛 **Issue created:** {issue_result['issue_url']}")
                elif issue_result["issue_url"]:
                    output_lines.append("\n   💡 **Report this error:**")
                    output_lines.append(f"   📝 [Create GitHub Issue]({issue_result['issue_url']})")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.debug("Failed to create issue", exc_info=True)
                self._debug(f"Failed to create issue: {e}")

        if on_error == "continue":
            output_lines.append("   *Continuing despite error (on_error: continue)*\n")

            # Set output variable to None so downstream compute steps don't crash
            # with NameError when referencing this step's output
            output_name = step.get("output", step_name)
            if output_name not in self.context:
                self.context[output_name] = None

            # Log to Python logger for journalctl visibility
            skill_name = self.skill.get("name", "unknown")
            logger.warning(
                "Skill '%s' step '%s' failed with on_error=continue: tool=%s, error=%s",
                skill_name,
                step_name,
                tool,
                error_msg[:200],
            )

            # Layer 5: Learn from this error
            tool_params = {}
            if "args" in step:
                args_data = step["args"]
                if isinstance(args_data, dict):
                    tool_params = {k: self._template(str(v)) for k, v in args_data.items()}

            await self._learn_from_error(tool_name=tool, params=tool_params, error_msg=error_msg)

            # Emit toast notification for continue-mode failures (helps visibility)
            try:
                # pylint: disable-next=import-outside-toplevel
                from tool_modules.aa_workflow.src.notification_emitter import (
                    notify_step_failed,
                )

                notify_step_failed(skill_name, step_name, error_msg[:150])
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("Suppressed error: %s", exc, exc_info=True)

            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": error_msg,
                }
            )
            return True
        return False

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
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("Suppressed error: %s", exc, exc_info=True)

    def _detect_soft_failure(self, result_text: str) -> tuple[bool, str | None]:
        """Detect if a successful tool result actually contains an error (soft failure).

        Many tools return success=True but include error messages in the result text.
        This method detects those cases so auto-heal can be triggered.

        Returns:
            (is_soft_failure, error_message) - True if result contains error patterns
        """
        if not result_text:
            return False, None

        result_lower = result_text.lower()

        # Patterns that indicate a soft failure (tool returned success but result is an error)
        soft_failure_patterns = [
            # Explicit failure markers
            ("❌ failed", "Tool returned failure marker"),
            ("❌ error", "Tool returned error marker"),
            # Network/DNS errors
            ("no such host", "DNS resolution failed - VPN may be disconnected"),
            ("dial tcp", "TCP connection failed - network issue"),
            ("connection refused", "Connection refused - service may be down"),
            ("no route to host", "No route to host - VPN may be disconnected"),
            ("network unreachable", "Network unreachable - VPN may be disconnected"),
            # Auth errors
            ("unauthorized", "Authentication failed - token may be expired"),
            ("forbidden", "Access forbidden - permissions issue"),
            ("401", "HTTP 401 - authentication required"),
            ("403", "HTTP 403 - access forbidden"),
            ("token expired", "Token expired - need to re-authenticate"),
            # Cluster errors
            (
                "the server has asked for the client to provide credentials",
                "Kubernetes auth required",
            ),
            ("error from server", "Kubernetes API error"),
            # Bonfire/ephemeral errors
            ("traceback (most recent call last)", "Python exception in tool"),
        ]

        for pattern, error_desc in soft_failure_patterns:
            if pattern in result_lower:
                # Extract a snippet around the error for context
                idx = result_lower.find(pattern)
                start = max(0, idx - 50)
                end = min(len(result_text), idx + len(pattern) + 100)
                snippet = result_text[start:end].strip()
                return True, f"{error_desc}: ...{snippet}..."

        return False, None

    def _validate_tool_args(
        self,
        tool: str,  # pylint: disable=unused-argument
        raw_args: dict,
        args: dict,
        step_name: str,  # pylint: disable=unused-argument
    ) -> str | None:
        """Validate tool arguments after template rendering.

        Returns:
            Error message if validation fails, None if valid.
        """
        # Check for empty required arguments that came from templates
        # Skip validation for args that use 'default' or 'or' in the template (these are optional)
        for key, raw_value in raw_args.items():
            if isinstance(raw_value, str) and "{{" in raw_value:
                # pylint: disable-next=line-too-long
                # Skip if template has a default/fallback (e.g., "{{ x | default('') }}" or "{{ x or '' }}")
                if "default(" in raw_value or " or " in raw_value:
                    continue
                rendered_value = args.get(key, "")
                if rendered_value == "" or rendered_value is None:
                    # Extract variable name from template for better error message
                    var_match = re.search(r"\{\{\s*([^\s}][^}]*)\}\}", raw_value)
                    var_name = var_match.group(1).strip() if var_match else raw_value
                    return (
                        f"Required argument '{key}' is empty. "
                        f"Template '{raw_value}' rendered to empty string. "
                        f"Check if '{var_name}' is defined in a previous step."
                    )
        return None

    async def _process_tool_step(  # pylint: disable=too-many-locals
        self, step: dict, step_num: int, step_name: str, output_lines: list[str]
    ) -> bool:
        """Process a 'tool' step and append results to output_lines.

        Returns:
            True if processing should continue, False if skill should stop
        """
        tool = step["tool"]
        raw_args = step.get("args", {})
        args = self._template_dict(raw_args)

        # Validate that template rendering produced valid arguments
        validation_error = self._validate_tool_args(tool, raw_args, args, step_name)
        if validation_error:
            self._debug(f"Argument validation failed for {tool}: {validation_error}")
            output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
            output_lines.append(f"   *Tool: `{tool}`*")
            output_lines.append(f"   ❌ {validation_error}")

            # Check on_error handling
            on_error = step.get("on_error", "fail")
            if on_error == "continue":
                output_lines.append("   ⏭️ Continuing (on_error: continue)")
                return True

            # Record step failure
            self.step_results.append(
                {
                    "step": step_name,
                    "tool": tool,
                    "success": False,
                    "error": validation_error,
                }
            )
            return False

        output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
        output_lines.append(f"   *Tool: `{tool}`*")

        result = await self._exec_tool(tool, args)

        if result["success"]:
            output_name = step.get("output", step_name)
            result_text = result["result"]

            # Check for soft failures - tool returned success but result contains error
            is_soft_failure, soft_error = self._detect_soft_failure(result_text)

            if is_soft_failure and step.get("on_error") == "auto_heal":
                # Treat as error and trigger auto-heal
                output_lines.append(f"   ⚠️ Soft failure detected: {(soft_error or '')[:100]}")
                self._debug(f"Soft failure in {tool}: {soft_error}")

                # Store result anyway (some steps may need it even if failed)
                self.context[output_name] = result_text
                self._parse_and_store_tool_result(result_text, output_name)

                # Trigger auto-heal flow
                should_continue = await self._handle_tool_error(
                    tool,
                    step,
                    step_name,
                    soft_error or "Soft failure detected",
                    output_lines,
                )
                if not should_continue:
                    output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
                return should_continue

            # Normal success path
            self.context[output_name] = result_text
            self._parse_and_store_tool_result(result_text, output_name)

            duration = result.get("duration", 0)
            output_lines.append(f"   ✅ Success ({duration:.2f}s)")

            result_preview = result_text[:300]
            if len(result_text) > 300:
                result_preview += "..."
            output_lines.append(f"   ```\n   {result_preview}\n   ```\n")

            self.step_results.append({"step": step_name, "tool": tool, "success": True, "duration": duration})
            return True

        # Handle error - error message can be in 'error' key or 'result' key
        error_msg = result.get("error") or result.get("result", "Unknown error")
        should_continue = await self._handle_tool_error(tool, step, step_name, error_msg, output_lines)
        if not should_continue:
            output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
        return should_continue

    def _format_skill_outputs(self, output_lines: list[str]):
        """Format and append skill outputs section."""
        if not self.skill.get("outputs"):
            return

        output_lines.append("\n### 📤 Outputs\n")
        for out in self.skill["outputs"]:
            out_name = out.get("name", "output")
            if "value" in out:
                val = out["value"]
                output_value: Any
                if isinstance(val, str):
                    output_value = self._template(val)
                elif isinstance(val, (dict, list)):
                    output_value = (
                        self._template_dict(val)
                        if isinstance(val, dict)
                        else [self._template(i) if isinstance(i, str) else i for i in val]
                    )
                else:
                    output_value = val

                self.context[out_name] = output_value
                output_lines.append(f"**{out_name}:**\n{output_value}\n")
            elif "compute" in out:
                result = self._exec_compute(out["compute"], out_name)
                output_lines.append(f"**{out_name}:** {result}\n")

    def _process_then_block(self, step: dict, output_lines: list[str]) -> str | None:
        """Process a 'then' block with early return.

        Returns:
            Final output string if early return, None to continue execution
        """
        import time  # pylint: disable=import-outside-toplevel

        self._debug("Processing 'then' block")
        for then_item in step["then"]:
            if "return" in then_item:
                ret = then_item["return"]
                templated = self._template_dict(ret) if isinstance(ret, dict) else self._template(str(ret))
                self._debug(f"Early return: {templated}")

                total_time = time.time() - (self.start_time or 0.0)
                output_lines.append(f"✅ **Early Exit**\n{templated}\n")
                output_lines.append(f"\n---\n⏱️ *Completed in {total_time:.2f}s*")

                if self.debug and self.log:
                    output_lines.append("\n\n### 🔍 Debug Log\n```")
                    output_lines.extend(self.log)
                    output_lines.append("```")

                return "\n".join(output_lines)
        return None
