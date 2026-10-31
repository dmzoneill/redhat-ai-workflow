# pylint: disable=duplicate-code,cyclic-import
"""Split from skill_engine.py so the public module stays importable."""

import asyncio
import json
import logging
import time
from collections.abc import Coroutine
from datetime import datetime
from typing import Any

from .skill_support import (
    _get_agent_stats_module,
)

logger = logging.getLogger(__name__)


# Strong references to fire-and-forget tasks so they are not garbage-collected mid-run
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _spawn_background(coro: Coroutine[Any, Any, Any]) -> None:
    """Start a fire-and-forget task and keep a reference until it finishes."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


class SkillRunMixin:  # pylint: disable=too-few-public-methods
    """SkillExecutor behavior split out of skill_engine."""

    # Declared for mixins that read sibling state.
    _debug: Any
    _eval_condition: Any
    _exec_compute: Any
    _format_skill_outputs: Any
    _process_then_block: Any
    _process_tool_step: Any
    _template: Any
    context: Any
    debug: Any
    event_emitter: Any
    inputs: Any
    log: Any
    skill: Any
    skill_id: Any
    source: Any
    start_time: float | None
    step_results: Any
    ws_server: Any

    # pylint: disable-next=too-many-branches,too-many-locals,too-many-statements
    async def execute(self) -> str:
        """Execute all steps and return the result."""

        self.start_time = time.time()

        skill_name = self.skill.get("name", "unknown")
        total_steps = len(self.skill.get("steps", []))
        self._debug(f"Starting skill: {skill_name}")
        self._debug(f"Inputs: {json.dumps(self.inputs)}")

        # Emit skill start event (file-based)
        if self.event_emitter:
            self.event_emitter.skill_start()

        # Emit skill start event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            _spawn_background(
                self.ws_server.skill_started(
                    skill_id=self.skill_id,
                    skill_name=skill_name,
                    total_steps=total_steps,
                    inputs=self.inputs,
                    source=self.source,
                )
            )

        self._apply_input_defaults()

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
            step_index = step_num  # 0-based index for events
            step_num += 1
            step_name = step.get("name", f"step_{step_num}")
            step_start_time = time.time()

            if "condition" in step and not self._eval_condition(step["condition"]):
                self._debug(f"Skipping step '{step_name}' - condition false")
                output_lines.append(f"⏭️ **Step {step_num}: {step_name}** - *skipped (condition false)*\n")
                # Emit step skipped event
                if self.event_emitter:
                    self.event_emitter.step_skipped(step_index, "condition false")
                continue

            # Emit step start event (file-based)
            if self.event_emitter:
                self.event_emitter.step_start(step_index)

            # Emit step start event (WebSocket)
            if self.ws_server and self.ws_server.is_running:
                description = step.get("description", "")
                _spawn_background(
                    self.ws_server.step_started(
                        skill_id=self.skill_id,
                        step_index=step_index,
                        step_name=step_name,
                        description=description[:200] if description else "",
                    )
                )

            if "then" in step:
                early_return = self._process_then_block(step, output_lines)
                if early_return is not None:
                    # Emit skill complete (early return)
                    if self.event_emitter:
                        total_time = time.time() - (self.start_time or 0.0)
                        self.event_emitter.skill_complete(True, int(total_time * 1000))
                    return str(early_return)
                continue

            step_success = True
            step_error = None

            if "tool" in step:
                # Check for memory operations
                tool_name = step.get("tool", "")
                if self.event_emitter:
                    self._emit_memory_events_for_tool(step_index, tool_name, step.get("args", {}))

                should_continue = await self._process_tool_step(step, step_num, step_name, output_lines)

                # Check step result
                if self.step_results:
                    last_result = self.step_results[-1]
                    step_success = last_result.get("success", True)
                    if not step_success:
                        step_error = last_result.get("error", "Unknown error")

                if not should_continue:
                    # Emit step failed event
                    if self.event_emitter:
                        duration_ms = int((time.time() - step_start_time) * 1000)
                        self.event_emitter.step_failed(step_index, duration_ms, step_error or "Step failed")
                    break

            elif "compute" in step:
                step_success, step_error = self._run_compute_step(step, step_num, step_name, output_lines)

            elif "description" in step:
                output_lines.append(f"📝 **Step {step_num}: {step_name}** (manual)")
                output_lines.append(f"   {self._template(step['description'])}\n")

            self._emit_step_finished(step_index, step_name, step_start_time, step_success, step_error)

        self._format_skill_outputs(output_lines)

        total_time = time.time() - (self.start_time or 0.0)
        success_count = sum(1 for r in self.step_results if r.get("success"))
        fail_count = sum(1 for r in self.step_results if not r.get("success"))

        output_lines.append(
            # pylint: disable-next=line-too-long
            f"\n---\n⏱️ *Completed in {total_time:.2f}s* | ✅ {success_count} succeeded | ❌ {fail_count} failed"
        )

        self._emit_skill_finished(total_time, fail_count)

        # Track skill execution in agent stats
        try:
            agent_stats = _get_agent_stats_module()
            overall_success = fail_count == 0
            agent_stats.record_skill_execution(
                skill_name=skill_name,
                success=overall_success,
                duration_ms=int(total_time * 1000),
                steps_completed=success_count,
                total_steps=len(self.skill.get("steps", [])),
            )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("Failed to record skill stats", exc_info=True)
            self._debug(f"Failed to record skill stats: {e}")

        # Extract and save learnings from successful skill execution
        if fail_count == 0:
            await self._extract_and_save_learnings(output_lines)

        if self.debug and self.log:
            output_lines.append("\n\n### 🔍 Debug Log\n```")
            output_lines.extend(self.log)
            output_lines.append("```")

        return "\n".join(output_lines)

    def _apply_input_defaults(self) -> None:
        """Fill missing inputs from their declared defaults (templated)."""
        for inp in self.skill.get("inputs", []):
            name = inp["name"]
            if name not in self.inputs and "default" in inp:
                # Template the default value to resolve variables like {{ today }}
                default_val = inp["default"]
                if isinstance(default_val, str) and "{{" in default_val:
                    default_val = self._template(default_val)
                self.inputs[name] = default_val
                self.context["inputs"] = self.inputs
                self._debug(f"Applied default: {name} = {default_val}")

    def _run_compute_step(
        self, step: dict, step_num: int, step_name: str, output_lines: list[str]
    ) -> tuple[bool, str | None]:
        """Run a compute step and record its result; return (success, error)."""
        step_success = True
        step_error: str | None = None
        output_name = step.get("output", step_name)
        output_lines.append(f"🧮 **Step {step_num}: {step_name}** (compute)")

        try:
            result = self._exec_compute(step["compute"], output_name)

            # Check if compute returned an error string
            if isinstance(result, str) and result.startswith("<compute error:"):
                step_success = False
                step_error = result
                output_lines.append(f"   ❌ {result}\n")
                self._debug(f"Compute step '{step_name}' failed: {result}")

                # Store error result in context so dependent steps can check
                self.context[output_name] = None
                self.context[f"{output_name}_error"] = result

                # Record step failure
                self.step_results.append(
                    {
                        "step": step_name,
                        "compute": True,
                        "success": False,
                        "error": result,
                    }
                )
            else:
                self.context[output_name] = result
                output_lines.append(f"   → `{output_name}` = {str(result)[:100]}\n")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("❌ Error", exc_info=True)
            step_success = False
            step_error = str(e)
            output_lines.append(f"   ❌ Error: {e}\n")
        return step_success, step_error

    def _emit_step_finished(
        self, step_index: int, step_name: str, step_start_time: float, step_success: bool, step_error: str | None
    ) -> None:
        """Emit step complete/failed events (file-based and WebSocket)."""
        # Emit step complete/failed event (file-based)
        if self.event_emitter:
            duration_ms = int((time.time() - step_start_time) * 1000)
            if step_success:
                self.event_emitter.step_complete(step_index, duration_ms)
            else:
                self.event_emitter.step_failed(step_index, duration_ms, step_error or "Unknown error")

        # Emit step complete/failed event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            duration_ms = int((time.time() - step_start_time) * 1000)
            if step_success:
                _spawn_background(
                    self.ws_server.step_completed(
                        skill_id=self.skill_id,
                        step_index=step_index,
                        step_name=step_name,
                        duration_ms=duration_ms,
                    )
                )
            else:
                _spawn_background(
                    self.ws_server.step_failed(
                        skill_id=self.skill_id,
                        step_index=step_index,
                        step_name=step_name,
                        error=step_error or "Unknown error",
                    )
                )

    def _emit_skill_finished(self, total_time: float, fail_count: int) -> None:
        """Emit skill complete/failed events (file-based and WebSocket)."""
        # Emit skill complete event (file-based)
        if self.event_emitter:
            overall_success = fail_count == 0
            self.event_emitter.skill_complete(overall_success, int(total_time * 1000))
            # Clear the global emitter
            try:
                from .skill_execution_events import (  # pylint: disable=import-outside-toplevel
                    set_emitter,
                )

                set_emitter(None)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                logger.debug("Suppressed error: %s", exc, exc_info=True)

        # Emit skill complete event (WebSocket)
        if self.ws_server and self.ws_server.is_running:
            overall_success = fail_count == 0
            if overall_success:
                _spawn_background(
                    self.ws_server.skill_completed(
                        skill_id=self.skill_id,
                        total_duration_ms=int(total_time * 1000),
                    )
                )
            else:
                # Get last error from step_results
                last_error = "Skill failed"
                for r in reversed(self.step_results):
                    if not r.get("success") and r.get("error"):
                        last_error = r["error"]
                        break
                _spawn_background(
                    self.ws_server.skill_failed(
                        skill_id=self.skill_id,
                        error=last_error,
                        total_duration_ms=int(total_time * 1000),
                    )
                )

    def _emit_memory_events_for_tool(self, step_index: int, tool_name: str, args: dict) -> None:
        """Emit memory read/write events based on tool being called."""
        if not self.event_emitter:
            return

        # Memory read tools
        memory_read_tools = [
            "memory_read",
            "memory_query",
            "check_known_issues",
            "memory_stats",
        ]
        if any(t in tool_name for t in memory_read_tools):
            key = args.get("key", tool_name)
            self.event_emitter.memory_read(step_index, key)

        # Memory write tools
        memory_write_tools = [
            "memory_write",
            "memory_update",
            "memory_append",
            "memory_session_log",
            "learn_tool_fix",
        ]
        if any(t in tool_name for t in memory_write_tools):
            key = args.get("key", tool_name)
            self.event_emitter.memory_write(step_index, key)

        # Semantic search tools
        semantic_search_tools = [
            "code_search",
            "knowledge_query",
            "semantic_search",
            "vector_search",
        ]
        if any(t in tool_name for t in semantic_search_tools):
            query = args.get("query", args.get("section", tool_name))
            self.event_emitter.semantic_search(step_index, query)

    async def _extract_and_save_learnings(  # pylint: disable=too-many-locals
        self, output_lines: list[str]
    ) -> None:  # pylint: disable=too-many-locals
        """Extract learnings from successful skill execution and save to knowledge.

        This is called after a skill completes successfully. It analyzes the
        execution context and results to extract potential learnings.
        """
        skill_name = self.skill.get("name", "unknown")

        # Skip skills that don't produce learnable outcomes
        non_learning_skills = [
            "memory_view",
            "memory_cleanup",
            "coffee",
            "beer",
            "standup_summary",
            "weekly_summary",
        ]
        if skill_name in non_learning_skills:
            return

        # Try to detect project and persona
        try:
            from .knowledge_tools import (  # pylint: disable=import-outside-toplevel
                _detect_project_from_path,
                _get_current_persona,
                _load_knowledge,
                _save_knowledge,
            )

            project = _detect_project_from_path()
            if not project:
                self._debug("No project detected, skipping learning extraction")
                return

            persona = _get_current_persona() or "developer"

            # Load existing knowledge
            knowledge = _load_knowledge(persona, project)
            if not knowledge:
                self._debug(f"No knowledge file for {project}/{persona}, skipping")
                return

            # Extract learning based on skill type
            task = self.inputs.get("issue_key", skill_name)

            # Map skill -> (input_key, template)
            _learning_templates = {
                "start_work": ("issue_key", "Started work on {}"),
                "create_mr": ("issue_key", "Created MR for {}"),
                "review_pr": ("mr_id", "Reviewed MR !{}"),
                "review_all_prs": ("mr_id", "Reviewed MR !{}"),
                "test_mr_ephemeral": (
                    "mr_id",
                    "Tested MR !{} in ephemeral environment",
                ),
                "investigate_alert": ("alert_name", "Investigated alert: {}"),
                "close_issue": ("issue_key", "Closed issue {}"),
            }

            learning = None
            if skill_name in _learning_templates:
                input_key, template = _learning_templates[skill_name]
                value = self.inputs.get(input_key, "")
                if value:
                    learning = template.format(value)

            # Save learning if we extracted one
            if learning:
                # Ensure learned_from_tasks exists
                if "learned_from_tasks" not in knowledge:
                    knowledge["learned_from_tasks"] = []

                # Add the learning
                knowledge["learned_from_tasks"].append(
                    {
                        "date": datetime.now().astimezone().strftime("%Y-%m-%d"),
                        "task": task,
                        "learning": learning,
                        "skill": skill_name,
                    }
                )

                # Limit to last 50 learnings
                knowledge["learned_from_tasks"] = knowledge["learned_from_tasks"][-50:]

                # Slightly increase confidence
                current_confidence = knowledge.get("metadata", {}).get("confidence", 0.5)
                knowledge["metadata"]["confidence"] = min(current_confidence + 0.01, 1.0)

                # Save
                _save_knowledge(persona, project, knowledge)
                self._debug(f"Saved learning: {learning}")

                # Add note to output
                output_lines.append(f"\n📚 *Learning recorded: {learning}*")

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.debug("Failed to extract/save learnings", exc_info=True)
            self._debug(f"Failed to extract/save learnings: {e}")
