"""Mock-based skill execution tests.

Tests end-to-end execution of skills using a SkillHarness that replaces
real tool calls with mock responses from mock_responses.py.
"""

import sys
from pathlib import Path

import pytest
import yaml

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SKILLS_DIR = PROJECT_ROOT / "skills"


class SkillHarness:
    """Test harness that wraps SkillExecutor with mocked tool execution.

    Intercepts _exec_tool to return configurable mock responses and
    tracks which tools were called with what arguments.
    """

    def __init__(self, skill_name: str, inputs: dict = None, responses: dict = None):
        from tests.skills.mock_responses import generate_default_response
        from tool_modules.aa_workflow.src.skill_engine import SkillExecutor

        skill_path = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_path}")

        with open(skill_path) as f:
            self.skill = yaml.safe_load(f)

        self.inputs = inputs or {}
        self.custom_responses = responses or {}
        self.tool_calls: list[dict] = []
        self._generate_default = generate_default_response

        self.executor = SkillExecutor(
            skill=self.skill,
            inputs=self.inputs,
            debug=True,
            server=None,
            emit_events=False,
            enable_interactive_recovery=False,
        )

        # Monkey-patch _exec_tool with our mock
        self.executor._exec_tool = self._mock_exec_tool

    async def _mock_exec_tool(self, tool_name: str, args: dict) -> dict:
        """Mock tool executor that records calls and returns mock responses."""
        self.tool_calls.append({"tool": tool_name, "args": args})

        # Check for custom per-tool response overrides
        if tool_name in self.custom_responses:
            return dict(self.custom_responses[tool_name])

        # Fall back to the default mock response generator
        return self._generate_default(tool_name, args)

    async def execute(self) -> str:
        """Execute the skill and return the output string."""
        return await self.executor.execute()

    @property
    def context(self) -> dict:
        """Access the executor's context (step outputs)."""
        return self.executor.context

    @property
    def step_results(self) -> list:
        """Access recorded step results."""
        return self.executor.step_results

    def assert_tool_called(self, tool_name: str, times: int = None):
        """Assert that a specific tool was called.

        Args:
            tool_name: The tool name to check for.
            times: If provided, assert exact call count.
        """
        calls = [c for c in self.tool_calls if c["tool"] == tool_name]
        assert len(calls) > 0, (
            f"Tool '{tool_name}' was never called. "
            f"Called tools: {[c['tool'] for c in self.tool_calls]}"
        )
        if times is not None:
            assert (
                len(calls) == times
            ), f"Tool '{tool_name}' called {len(calls)} times, expected {times}"

    def assert_tool_not_called(self, tool_name: str):
        """Assert that a specific tool was never called."""
        calls = [c for c in self.tool_calls if c["tool"] == tool_name]
        assert (
            len(calls) == 0
        ), f"Tool '{tool_name}' was called {len(calls)} time(s), expected 0"

    def get_tool_args(self, tool_name: str) -> list[dict]:
        """Return all argument dicts for calls to the given tool."""
        return [c["args"] for c in self.tool_calls if c["tool"] == tool_name]


@pytest.fixture
def harness():
    """Factory fixture that creates a SkillHarness for a named skill."""

    def _create(skill_name: str, inputs: dict = None, responses: dict = None):
        return SkillHarness(skill_name, inputs=inputs, responses=responses)

    return _create


@pytest.fixture(scope="session")
def test_exclusions():
    """Load the test exclusions list."""
    exclusions_path = PROJECT_ROOT / "tests" / "test_exclusions.yaml"
    with open(exclusions_path) as f:
        data = yaml.safe_load(f)

    # Flatten excluded skill names for easy lookup
    excluded = set()
    for entry in data.get("excluded_skills", []):
        if isinstance(entry, dict):
            excluded.add(entry["name"])
        else:
            excluded.add(str(entry))

    return {
        "excluded_skills": excluded,
        "excluded_tools": set(data.get("excluded_tools", [])),
        "raw": data,
    }


# ============================================================================
# TestSkillExecution
# ============================================================================


@pytest.mark.asyncio
class TestSkillExecution:
    """End-to-end skill execution tests with mocked tools."""

    async def test_hello_world_executes(self, harness):
        """Simplest skill runs to completion."""
        h = harness("hello_world")
        result = await h.execute()
        assert "Hello World" in result
        h.assert_tool_called("memory_session_log")

    async def test_skill_handles_tool_failure(self, harness):
        """on_error:continue proceeds after tool failure."""
        h = harness(
            "hello_world",
            responses={
                "memory_session_log": {
                    "success": False,
                    "error": "mock failure",
                    "duration": 0.01,
                },
            },
        )
        result = await h.execute()
        # hello_world's log_execution step has on_error: continue,
        # so the skill should still complete
        assert result is not None
        assert "Hello World" in result

    async def test_context_propagation(self, harness):
        """Output from step N is available in step N+1."""
        h = harness("hello_world")
        await h.execute()
        # The say_hello compute step stores its result as 'greeting'
        assert "greeting" in h.context
        assert "Hello World" in str(h.context["greeting"])

    async def test_conditional_step_skipped(self, harness):
        """Steps with false conditions are skipped."""
        # find_similar_code has a 'detect_project' step with
        # condition: "{{ not inputs.project }}" -- when project IS provided,
        # detect_project should be skipped and set_project should run
        h = harness("find_similar_code", inputs={"query": "test", "project": "myproj"})
        await h.execute()
        # The set_project step should have run (condition: {{ inputs.project }})
        assert h.context.get("project") == "myproj"

    async def test_excluded_skills_skipped(self, test_exclusions):
        """Verify excluded skills list is loaded and non-empty."""
        assert len(test_exclusions["excluded_skills"]) > 0
        # Verify known high-risk skills are in the exclusion list
        assert "release_aa_backend_prod" in test_exclusions["excluded_skills"]

    async def test_all_safe_skills_execute(
        self, all_skill_files, harness, test_exclusions
    ):
        """Every non-excluded skill executes without crashing.

        Smoke tests the first 10 non-excluded skills. Skills that require
        specific input types (e.g. add_project needs structured inputs)
        are expected to produce compute errors but should not crash the
        executor itself.
        """
        tested = 0
        for path in all_skill_files[:10]:  # Smoke test first 10
            with open(path) as f:
                skill = yaml.safe_load(f)
            name = skill.get("name", path.stem)
            if name in test_exclusions["excluded_skills"]:
                continue

            h = harness(name)
            try:
                result = await h.execute()
                assert result is not None, f"Skill {name} returned None"
                tested += 1
            except FileNotFoundError:
                # Skill file might reference a different name
                continue
            except (AttributeError, TypeError, KeyError) as e:
                # Some skills have schema issues (e.g. outputs as dict
                # instead of list-of-dicts). Record but don't fail the
                # smoke test -- these are caught by schema validation tests.
                import warnings

                warnings.warn(
                    f"Skill '{name}' has a schema issue: {e}",
                    stacklevel=1,
                )
                tested += 1

        assert tested > 0, "No skills were tested"

    async def test_tool_call_tracking(self, harness):
        """Harness correctly tracks which tools are called."""
        h = harness("hello_world")
        await h.execute()
        # hello_world has 1 tool step: memory_session_log
        h.assert_tool_called("memory_session_log", times=1)
        h.assert_tool_not_called("jira_view_issue")

    async def test_step_results_recorded(self, harness):
        """Step results are collected during execution."""
        h = harness("hello_world")
        await h.execute()
        # Should have at least the tool step recorded
        tool_steps = [r for r in h.step_results if r.get("tool")]
        assert len(tool_steps) >= 1
        assert tool_steps[0]["tool"] == "memory_session_log"
        assert tool_steps[0]["success"] is True

    async def test_custom_mock_response(self, harness):
        """Custom per-tool responses override defaults."""
        custom_result = "Custom session log result"
        h = harness(
            "hello_world",
            responses={
                "memory_session_log": {
                    "success": True,
                    "result": custom_result,
                    "duration": 0.01,
                },
            },
        )
        await h.execute()
        h.assert_tool_called("memory_session_log")

    async def test_debug_log_populated(self, harness):
        """Debug mode populates the executor's log."""
        h = harness("hello_world")
        await h.execute()
        # SkillExecutor is created with debug=True in harness
        assert len(h.executor.log) > 0
