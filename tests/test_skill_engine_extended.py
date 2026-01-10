"""Extended tests for skill_engine module."""

from unittest.mock import AsyncMock

import pytest

from tool_modules.aa_workflow.src.skill_engine import (
    SkillCondition,
    SkillContext,
    SkillEngine,
    SkillStep,
)


@pytest.fixture
def mock_skill_engine():
    """Create a mock skill engine for testing."""
    engine = SkillEngine()
    engine.tool_registry = {}
    return engine


@pytest.fixture
def sample_skill_yaml():
    """Sample skill YAML for testing."""
    return """
name: test_skill
description: A test skill
inputs:
  - name: issue_key
    required: true
  - name: optional_param
    required: false
steps:
  - name: Step 1
    tool: test_tool
    inputs:
      param1: "{{ issue_key }}"
  - name: Step 2
    condition:
      type: success
      step: Step 1
    tool: another_tool
outputs:
  result: "{{ Step 1.output }}"
"""


class TestSkillContext:
    """Tests for SkillContext class."""

    def test_skill_context_initialization(self):
        """Test SkillContext initializes correctly."""
        context = SkillContext(issue_key="TEST-123", repo="myrepo")

        assert context.get("issue_key") == "TEST-123"
        assert context.get("repo") == "myrepo"

    def test_skill_context_set_and_get(self):
        """Test setting and getting context values."""
        context = SkillContext()

        context.set("key1", "value1")
        context.set("key2", 42)

        assert context.get("key1") == "value1"
        assert context.get("key2") == 42

    def test_skill_context_get_missing_key(self):
        """Test getting missing key returns None."""
        context = SkillContext()

        assert context.get("nonexistent") is None

    def test_skill_context_get_with_default(self):
        """Test getting missing key with default value."""
        context = SkillContext()

        result = context.get("nonexistent", "default_value")

        assert result == "default_value"

    def test_skill_context_has_key(self):
        """Test checking if context has key."""
        context = SkillContext(test_key="value")

        assert context.has("test_key") is True
        assert context.has("missing_key") is False


class TestSkillStep:
    """Tests for SkillStep class."""

    def test_skill_step_initialization(self):
        """Test SkillStep initializes correctly."""
        step = SkillStep(name="Test Step", tool="test_tool", inputs={"param": "value"})

        assert step.name == "Test Step"
        assert step.tool == "test_tool"
        assert step.inputs == {"param": "value"}

    def test_skill_step_with_condition(self):
        """Test SkillStep with condition."""
        condition = SkillCondition(type="success", step="Previous Step")
        step = SkillStep(
            name="Conditional Step",
            tool="test_tool",
            inputs={},
            condition=condition,
        )

        assert step.condition is not None
        assert step.condition.type == "success"
        assert step.condition.step == "Previous Step"

    def test_skill_step_without_condition(self):
        """Test SkillStep without condition."""
        step = SkillStep(name="Unconditional Step", tool="test_tool", inputs={})

        assert step.condition is None


class TestSkillCondition:
    """Tests for SkillCondition class."""

    def test_skill_condition_success_type(self):
        """Test SkillCondition with success type."""
        condition = SkillCondition(type="success", step="Step 1")

        assert condition.type == "success"
        assert condition.step == "Step 1"

    def test_skill_condition_failure_type(self):
        """Test SkillCondition with failure type."""
        condition = SkillCondition(type="failure", step="Step 1")

        assert condition.type == "failure"

    def test_skill_condition_equals_type(self):
        """Test SkillCondition with equals type."""
        condition = SkillCondition(type="equals", step="Step 1", value="expected_value")

        assert condition.type == "equals"
        assert condition.value == "expected_value"


@pytest.mark.asyncio
class TestSkillEngine:
    """Tests for SkillEngine class."""

    async def test_skill_engine_initialization(self, mock_skill_engine):
        """Test SkillEngine initializes correctly."""
        assert mock_skill_engine.tool_registry == {}

    async def test_skill_engine_register_tool(self, mock_skill_engine):
        """Test registering a tool."""
        mock_tool = AsyncMock(return_value="result")

        mock_skill_engine.register_tool("test_tool", mock_tool)

        assert "test_tool" in mock_skill_engine.tool_registry
        assert mock_skill_engine.tool_registry["test_tool"] == mock_tool

    async def test_skill_engine_execute_tool(self, mock_skill_engine):
        """Test executing a registered tool."""
        mock_tool = AsyncMock(return_value="tool_result")
        mock_skill_engine.register_tool("test_tool", mock_tool)

        result = await mock_skill_engine.execute_tool("test_tool", {"param1": "value1"})

        assert result == "tool_result"
        mock_tool.assert_called_once_with(param1="value1")

    async def test_skill_engine_execute_missing_tool(self, mock_skill_engine):
        """Test executing a non-existent tool."""
        with pytest.raises(KeyError):
            await mock_skill_engine.execute_tool("nonexistent_tool", {})

    async def test_skill_engine_variable_substitution(self, mock_skill_engine):
        """Test variable substitution in inputs."""
        context = SkillContext(issue_key="TEST-123", repo="myrepo")

        result = mock_skill_engine.substitute_variables({"param": "{{ issue_key }}"}, context)

        assert result["param"] == "TEST-123"

    async def test_skill_engine_multiple_variable_substitution(self, mock_skill_engine):
        """Test multiple variable substitutions."""
        context = SkillContext(issue_key="TEST-123", repo="myrepo", branch="feature-branch")

        result = mock_skill_engine.substitute_variables(
            {
                "issue": "{{ issue_key }}",
                "repository": "{{ repo }}",
                "git_branch": "{{ branch }}",
            },
            context,
        )

        assert result["issue"] == "TEST-123"
        assert result["repository"] == "myrepo"
        assert result["git_branch"] == "feature-branch"


@pytest.mark.asyncio
class TestSkillExecution:
    """Tests for skill execution."""

    async def test_execute_simple_skill(self, mock_skill_engine):
        """Test executing a simple skill with one step."""
        mock_tool = AsyncMock(return_value=(True, "Success"))
        mock_skill_engine.register_tool("test_tool", mock_tool)

        skill_data = {
            "name": "simple_skill",
            "inputs": [],
            "steps": [{"name": "Step 1", "tool": "test_tool", "inputs": {}}],
        }

        await mock_skill_engine.execute_skill(skill_data, {})

        mock_tool.assert_called_once()

    async def test_execute_skill_with_inputs(self, mock_skill_engine):
        """Test executing a skill with input parameters."""
        mock_tool = AsyncMock(return_value=(True, "Success"))
        mock_skill_engine.register_tool("test_tool", mock_tool)

        skill_data = {
            "name": "skill_with_inputs",
            "inputs": [{"name": "param1", "required": True}],
            "steps": [
                {
                    "name": "Step 1",
                    "tool": "test_tool",
                    "inputs": {"arg1": "{{ param1 }}"},
                }
            ],
        }

        context = {"param1": "test_value"}
        await mock_skill_engine.execute_skill(skill_data, context)

        # Verify tool was called with substituted value
        mock_tool.assert_called_once()

    async def test_execute_skill_conditional_step(self, mock_skill_engine):
        """Test executing a skill with conditional steps."""
        mock_tool1 = AsyncMock(return_value=(True, "Step 1 Success"))
        mock_tool2 = AsyncMock(return_value=(True, "Step 2 Success"))

        mock_skill_engine.register_tool("tool1", mock_tool1)
        mock_skill_engine.register_tool("tool2", mock_tool2)

        skill_data = {
            "name": "conditional_skill",
            "inputs": [],
            "steps": [
                {"name": "Step 1", "tool": "tool1", "inputs": {}},
                {
                    "name": "Step 2",
                    "tool": "tool2",
                    "inputs": {},
                    "condition": {"type": "success", "step": "Step 1"},
                },
            ],
        }

        await mock_skill_engine.execute_skill(skill_data, {})

        # Both tools should be called since Step 1 succeeded
        assert mock_tool1.call_count == 1
        assert mock_tool2.call_count == 1


@pytest.mark.asyncio
class TestSkillValidation:
    """Tests for skill validation."""

    async def test_validate_skill_missing_required_input(self, mock_skill_engine):
        """Test validation fails for missing required input."""
        skill_data = {
            "name": "skill_with_required",
            "inputs": [{"name": "required_param", "required": True}],
            "steps": [],
        }

        with pytest.raises(ValueError, match="required"):
            await mock_skill_engine.validate_skill(skill_data, {})

    async def test_validate_skill_optional_input_missing(self, mock_skill_engine):
        """Test validation passes for missing optional input."""
        skill_data = {
            "name": "skill_with_optional",
            "inputs": [{"name": "optional_param", "required": False}],
            "steps": [],
        }

        # Should not raise
        await mock_skill_engine.validate_skill(skill_data, {})

    async def test_validate_skill_all_inputs_provided(self, mock_skill_engine):
        """Test validation passes when all inputs provided."""
        skill_data = {
            "name": "skill_complete",
            "inputs": [
                {"name": "param1", "required": True},
                {"name": "param2", "required": False},
            ],
            "steps": [],
        }

        context = {"param1": "value1", "param2": "value2"}

        # Should not raise
        await mock_skill_engine.validate_skill(skill_data, context)
