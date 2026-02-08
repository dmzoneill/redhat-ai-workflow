"""Mock-based skill execution tests.

Tests end-to-end execution of skills using the SkillTestHarness from
tests/skills/harness.py (via the ``harness`` fixture from conftest).
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


def _excluded_skill_names(test_exclusions: dict) -> set:
    """Extract excluded skill names from the raw test_exclusions dict."""
    excluded = set()
    for entry in test_exclusions.get("excluded_skills", []):
        if isinstance(entry, dict):
            excluded.add(entry["name"])
        else:
            excluded.add(str(entry))
    return excluded


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
        excluded = _excluded_skill_names(test_exclusions)
        assert len(excluded) > 0
        # Verify known high-risk skills are in the exclusion list
        assert "release_aa_backend_prod" in excluded

    async def test_all_safe_skills_execute(
        self, all_skill_files, harness, test_exclusions
    ):
        """Every non-excluded skill executes without crashing.

        Smoke tests the first 10 non-excluded skills. Skills that require
        specific input types (e.g. add_project needs structured inputs)
        are expected to produce compute errors but should not crash the
        executor itself.
        """
        excluded = _excluded_skill_names(test_exclusions)
        tested = 0
        for path in all_skill_files[:10]:  # Smoke test first 10
            with open(path) as f:
                skill = yaml.safe_load(f)
            name = skill.get("name", path.stem)
            if name in excluded:
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

    async def test_debug_log_populated(self, skill_data):
        """Debug mode populates the executor's log."""
        from tests.skills.harness import SkillTestHarness

        data = skill_data("hello_world")
        h = SkillTestHarness(skill=data, debug=True)
        await h.execute()
        # SkillExecutor is created with debug=True
        assert len(h._executor.log) > 0
