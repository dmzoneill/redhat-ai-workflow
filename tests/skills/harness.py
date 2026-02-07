"""SkillTestHarness - wrapper around SkillExecutor for deterministic testing.

The harness injects mock tool responses so that skills can be executed
end-to-end without hitting any real services.  It also exposes helper
methods and rich assertion helpers that make writing skill tests concise.

Usage::

    harness = SkillTestHarness(skill_data, inputs={"issue_key": "AAP-1"})
    result = await harness.execute()

    harness.assert_tool_called("jira_view_issue")
    harness.assert_tool_called_with("git_checkout", {"branch": "AAP-1-fix"})
    harness.assert_all_steps_passed()
"""

from __future__ import annotations

import asyncio
import copy
from typing import Any
from unittest.mock import AsyncMock, patch

from tests.skills.mock_responses import generate_default_response

# Import the real executor - path matches the project layout
from tool_modules.aa_workflow.src.skill_engine import SkillExecutor


class SkillTestHarness:
    """Test wrapper around :class:`SkillExecutor`.

    Key capabilities:

    * Intercepts every ``_exec_tool`` call, records it, and returns a mock
      response drawn from (in priority order):
        1. Per-test overrides passed via *tool_responses*.
        2. The shared YAML fixture (``fixtures/tool_responses.yaml``).
        3. The programmatic defaults in :mod:`mock_responses`.
    * Provides ``resolve_template`` / ``eval_condition`` / ``exec_compute``
      for unit-testing individual template expressions without running the
      full skill.
    * Offers assertion helpers (``assert_tool_called``, ``assert_context_has``,
      etc.) that produce clear failure messages.
    """

    def __init__(
        self,
        skill: dict,
        inputs: dict | None = None,
        tool_responses: dict[str, dict] | None = None,
        debug: bool = False,
    ):
        self._skill = copy.deepcopy(skill)
        self._inputs = dict(inputs or {})
        self._tool_responses = dict(tool_responses or {})
        self._debug = debug

        # Build the real executor (with events / interactive recovery off)
        self._executor = SkillExecutor(
            skill=self._skill,
            inputs=self._inputs,
            debug=debug,
            server=None,
            create_issue_fn=None,
            ask_question_fn=None,
            enable_interactive_recovery=False,
            emit_events=False,
            workspace_uri="test",
        )

        # Tool call tracking: list of (tool_name, args_dict) tuples
        self._tool_calls: list[tuple[str, dict]] = []

        # Monkey-patch _exec_tool on the executor instance
        original_exec_tool = self._executor._exec_tool

        async def _mock_exec_tool(tool_name: str, args: dict) -> dict:
            self._tool_calls.append((tool_name, dict(args)))

            # 1. Per-test override
            if tool_name in self._tool_responses:
                resp = self._tool_responses[tool_name]
                # Allow callables for dynamic responses
                if callable(resp):
                    resp = resp(tool_name, args)
                result = dict(resp)
            else:
                # 2. Programmatic default (includes SPECIFIC_TOOLS + prefix)
                result = generate_default_response(tool_name, args)

            # Store result in context under the step's output name
            # The real executor does this in execute(), so we replicate it
            # for tools that the executor would have stored.
            self._executor.context[tool_name] = result.get("result", "")

            return result

        self._executor._exec_tool = _mock_exec_tool  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self) -> str:
        """Run the full skill through the executor and return its output."""
        return await self._executor.execute()

    # ------------------------------------------------------------------
    # Low-level helpers (test individual engine primitives)
    # ------------------------------------------------------------------

    def resolve_template(self, text: str) -> str:
        """Resolve ``{{ var }}`` templates using the current executor context."""
        return self._executor._template(text)

    def eval_condition(self, condition: str) -> bool:
        """Evaluate a condition expression against the current context."""
        return self._executor._eval_condition(condition)

    def exec_compute(self, code: str, output_name: str = "result") -> Any:
        """Execute a compute block and return its result.

        The result is also stored in ``self.context[output_name]``.
        """
        result = self._executor._exec_compute(code, output_name)
        self._executor.context[output_name] = result
        return result

    def set_context(self, key: str, value: Any) -> None:
        """Inject a value into the executor context (available to templates)."""
        self._executor.context[key] = value

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def context(self) -> dict:
        """The executor's live context dictionary."""
        return self._executor.context

    @property
    def step_results(self) -> list[dict]:
        """List of step result dicts recorded by the executor."""
        return self._executor.step_results

    @property
    def tool_calls(self) -> list[tuple[str, dict]]:
        """All recorded ``(tool_name, args)`` pairs, in call order."""
        return list(self._tool_calls)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_tool_calls_for(self, name: str) -> list[dict]:
        """Return a list of args dicts for every call to *name*."""
        return [args for tool_name, args in self._tool_calls if tool_name == name]

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def assert_tool_called(self, name: str, *, times: int | None = None) -> None:
        """Assert that *name* was called.  Optionally check exact call count."""
        calls = self.get_tool_calls_for(name)
        if not calls:
            called_tools = sorted({t for t, _ in self._tool_calls})
            raise AssertionError(f"Tool '{name}' was never called.\n" f"Tools that WERE called: {called_tools}")
        if times is not None and len(calls) != times:
            raise AssertionError(f"Tool '{name}' was called {len(calls)} time(s), expected {times}.")

    def assert_tool_not_called(self, name: str) -> None:
        """Assert that *name* was **not** called."""
        calls = self.get_tool_calls_for(name)
        if calls:
            raise AssertionError(
                f"Tool '{name}' was called {len(calls)} time(s) but should not have been.\n"
                f"Args of first call: {calls[0]}"
            )

    def assert_tool_called_with(self, name: str, expected_args: dict) -> None:
        """Assert *name* was called at least once with args that are a superset of *expected_args*."""
        calls = self.get_tool_calls_for(name)
        if not calls:
            called_tools = sorted({t for t, _ in self._tool_calls})
            raise AssertionError(f"Tool '{name}' was never called.\n" f"Tools that WERE called: {called_tools}")
        for call_args in calls:
            if all(call_args.get(k) == v for k, v in expected_args.items()):
                return  # match found
        raise AssertionError(
            f"Tool '{name}' was called {len(calls)} time(s) but none matched "
            f"expected args {expected_args}.\n"
            f"Actual calls: {calls}"
        )

    def assert_context_has(self, key: str, value: Any = None) -> None:
        """Assert *key* exists in context; optionally check its value."""
        ctx = self._executor.context
        if key not in ctx:
            raise AssertionError(f"Context key '{key}' not found.\n" f"Available keys: {sorted(ctx.keys())}")
        if value is not None and ctx[key] != value:
            raise AssertionError(f"Context['{key}'] = {ctx[key]!r}, expected {value!r}")

    def assert_all_steps_passed(self) -> None:
        """Assert that every executed step succeeded (no errors)."""
        for i, sr in enumerate(self._executor.step_results):
            if not sr.get("success", True):
                raise AssertionError(f"Step {i} ('{sr.get('name', '?')}') failed: {sr.get('error', 'unknown')}")

    def assert_step_failed(self, step_name: str) -> None:
        """Assert that a step with *step_name* recorded a failure."""
        for sr in self._executor.step_results:
            if sr.get("name") == step_name:
                if sr.get("success", True):
                    raise AssertionError(f"Step '{step_name}' was expected to fail but succeeded.")
                return
        # Step not found at all - list available step names
        available = [sr.get("name", "?") for sr in self._executor.step_results]
        raise AssertionError(f"Step '{step_name}' not found in results.\n" f"Available steps: {available}")
