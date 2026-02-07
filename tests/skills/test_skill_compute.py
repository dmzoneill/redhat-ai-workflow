"""Tests for skill compute blocks.

Tests the _exec_compute_internal method, AttrDict, and the safe_globals
sandbox that compute blocks run inside.
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


@pytest.fixture
def executor_factory():
    """Create a minimal SkillExecutor for compute block testing.

    Returns a callable that accepts optional skill dict and inputs,
    builds an executor with emit_events=False and no server.
    """
    from tool_modules.aa_workflow.src.skill_engine import SkillExecutor

    def _create(skill=None, inputs=None, context_overrides=None):
        if skill is None:
            skill = {"name": "compute_test", "steps": []}
        if inputs is None:
            inputs = {}

        executor = SkillExecutor(
            skill=skill,
            inputs=inputs,
            debug=True,
            server=None,
            emit_events=False,
            enable_interactive_recovery=False,
        )

        if context_overrides:
            executor.context.update(context_overrides)

        return executor

    return _create


# ============================================================================
# TestComputeBlocks
# ============================================================================


class TestComputeBlocks:
    """Tests for compute block execution via _exec_compute_internal."""

    def test_simple_compute_returns_result(self, executor_factory):
        """Basic compute block produces a result via the 'result' variable."""
        executor = executor_factory()
        code = 'result = "hello from compute"'
        output = executor._exec_compute_internal(code, "my_output")
        assert output == "hello from compute"

    def test_compute_with_named_output(self, executor_factory):
        """Compute block returns value via output_name variable."""
        executor = executor_factory()
        code = 'greeting = "hi there"'
        output = executor._exec_compute_internal(code, "greeting")
        assert output == "hi there"

    def test_compute_with_imports(self, executor_factory):
        """Compute blocks can use re, json, os, datetime from safe_globals."""
        executor = executor_factory()

        # Test re (provided in safe_globals)
        code = """
import re
match = re.search(r'(\\d+)', 'abc123def')
result = match.group(1)
"""
        output = executor._exec_compute_internal(code, "test_re")
        assert output == "123"

    def test_compute_with_json_import(self, executor_factory):
        """Compute blocks can import and use json."""
        executor = executor_factory()
        code = """
import json
data = json.dumps({"key": "value"})
result = json.loads(data)["key"]
"""
        output = executor._exec_compute_internal(code, "test_json")
        assert output == "value"

    def test_compute_with_os_access(self, executor_factory):
        """Compute blocks can access os module (from safe_globals)."""
        executor = executor_factory()
        code = """
result = os.path.basename("/foo/bar/baz.txt")
"""
        output = executor._exec_compute_internal(code, "test_os")
        assert output == "baz.txt"

    def test_compute_with_datetime(self, executor_factory):
        """Compute blocks can use datetime (from safe_globals)."""
        executor = executor_factory()
        code = """
dt = datetime(2026, 1, 15, 10, 30, 0)
result = dt.strftime("%Y-%m-%d")
"""
        output = executor._exec_compute_internal(code, "test_dt")
        assert output == "2026-01-15"

    def test_compute_with_path(self, executor_factory):
        """Compute blocks can use Path (from safe_globals)."""
        executor = executor_factory()
        code = """
p = Path("/home/user/project/src/main.py")
result = p.suffix
"""
        output = executor._exec_compute_internal(code, "test_path")
        assert output == ".py"

    def test_compute_with_context_variables(self, executor_factory):
        """Compute blocks access context from prior steps.

        Context variables from prior steps are injected into the compute
        namespace via local_vars = dict(self.context). They are directly
        accessible as variables, not through locals().
        """
        executor = executor_factory(
            inputs={"repo": "my-repo"},
            context_overrides={
                "branch_name": "feature-branch",
                "issue_key": "AAP-999",
            },
        )
        code = """
repo = inputs.get("repo", "unknown")
# Context variables are directly available in the namespace
result = f"{repo}/{branch_name}"
"""
        output = executor._exec_compute_internal(code, "test_ctx")
        assert output == "my-repo/feature-branch"

    def test_compute_error_returns_error_string(self, executor_factory):
        """Compute errors produce <compute error: ...> strings via _exec_compute."""
        executor = executor_factory()
        code = """
raise ValueError("intentional test error")
"""
        output = executor._exec_compute(code, "test_err")
        assert output.startswith("<compute error:")
        assert "intentional test error" in output

    def test_compute_name_error_returns_error(self, executor_factory):
        """Undefined variable in compute block produces error string."""
        executor = executor_factory()
        code = """
result = undefined_variable_xyz + 1
"""
        output = executor._exec_compute(code, "test_name_err")
        assert "<compute error:" in output

    def test_compute_none_result_when_no_output(self, executor_factory):
        """Compute block with no result/output_name variable returns None."""
        executor = executor_factory()
        code = """
x = 42  # Neither 'result' nor output_name is set
"""
        output = executor._exec_compute_internal(code, "nonexistent_var")
        assert output is None

    def test_compute_list_operations(self, executor_factory):
        """Compute blocks can use list operations from builtins."""
        executor = executor_factory()
        code = """
items = [3, 1, 4, 1, 5, 9]
result = sorted(set(items))
"""
        output = executor._exec_compute_internal(code, "test_list")
        assert output == [1, 3, 4, 5, 9]

    def test_compute_dict_comprehension(self, executor_factory):
        """Compute blocks support dict comprehensions."""
        executor = executor_factory()
        code = """
result = {k: v for k, v in [("a", 1), ("b", 2)]}
"""
        output = executor._exec_compute_internal(code, "test_dict")
        assert output == {"a": 1, "b": 2}

    def test_real_compute_from_hello_world(self, executor_factory):
        """Test actual compute block from hello_world skill."""
        skill_path = SKILLS_DIR / "hello_world.yaml"
        with open(skill_path) as f:
            skill = yaml.safe_load(f)

        # Find the compute step
        compute_step = None
        for step in skill.get("steps", []):
            if "compute" in step:
                compute_step = step
                break

        assert compute_step is not None, "hello_world should have a compute step"

        executor = executor_factory(skill=skill)
        output = executor._exec_compute_internal(
            compute_step["compute"],
            compute_step.get("output", compute_step["name"]),
        )

        assert output is not None
        assert "Hello World" in str(output)


# ============================================================================
# TestAttrDict
# ============================================================================


class TestAttrDict:
    """Tests for the AttrDict class used in compute blocks."""

    def test_dot_access(self):
        """AttrDict allows inputs.foo instead of inputs['foo']."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"foo": "bar", "count": 42})
        assert ad.foo == "bar"
        assert ad.count == 42

    def test_bracket_access(self):
        """AttrDict still supports bracket access."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"key": "value"})
        assert ad["key"] == "value"

    def test_get_method(self):
        """AttrDict supports .get() with defaults."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"foo": "bar"})
        assert ad.get("foo") == "bar"
        assert ad.get("missing", "default") == "default"
        assert ad.get("missing") is None

    def test_nested_dict_not_auto_wrapped(self):
        """Nested dicts are plain dicts, not AttrDict (by design)."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"nested": {"x": 1}})
        assert ad.nested == {"x": 1}
        assert ad.nested["x"] == 1

    def test_missing_attribute_raises(self):
        """Accessing missing attribute raises AttributeError."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"foo": "bar"})
        with pytest.raises(AttributeError, match="no attribute 'missing'"):
            _ = ad.missing

    def test_setattr(self):
        """AttrDict supports attribute assignment."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({})
        ad.new_key = "new_value"
        assert ad["new_key"] == "new_value"
        assert ad.new_key == "new_value"

    def test_delattr(self):
        """AttrDict supports attribute deletion."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"temp": "delete_me"})
        del ad.temp
        assert "temp" not in ad

    def test_delattr_missing_raises(self):
        """Deleting missing attribute raises AttributeError."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({})
        with pytest.raises(AttributeError):
            del ad.nonexistent

    def test_iteration(self):
        """AttrDict supports standard dict iteration."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"a": 1, "b": 2, "c": 3})
        assert set(ad.keys()) == {"a", "b", "c"}
        assert sorted(ad.values()) == [1, 2, 3]

    def test_in_operator(self):
        """AttrDict supports 'in' membership test."""
        from tool_modules.aa_workflow.src.skill_engine import AttrDict

        ad = AttrDict({"exists": True})
        assert "exists" in ad
        assert "missing" not in ad


# ============================================================================
# TestTemplating
# ============================================================================


class TestTemplating:
    """Tests for the _template method used in compute and tool args."""

    def test_simple_variable_substitution(self, executor_factory):
        """Templates resolve simple {{ variable }} references."""
        executor = executor_factory(context_overrides={"greeting": "hello"})
        result = executor._template("{{ greeting }} world")
        assert result == "hello world"

    def test_no_template_passthrough(self, executor_factory):
        """Strings without {{ }} pass through unchanged."""
        executor = executor_factory()
        result = executor._template("plain text")
        assert result == "plain text"

    def test_nested_variable(self, executor_factory):
        """Templates resolve {{ obj.attr }} style references."""
        executor = executor_factory(
            inputs={"issue_key": "AAP-123"},
        )
        result = executor._template("Issue: {{ inputs.issue_key }}")
        assert result == "Issue: AAP-123"

    def test_template_with_filter(self, executor_factory):
        """Templates support Jinja2 filters like | default."""
        executor = executor_factory()
        result = executor._template("{{ missing_var | default('fallback') }}")
        assert result == "fallback"


# ============================================================================
# TestConditionEvaluation
# ============================================================================


class TestConditionEvaluation:
    """Tests for the _eval_condition method."""

    def test_true_condition(self, executor_factory):
        """Truthy condition evaluates to True."""
        executor = executor_factory(context_overrides={"flag": True})
        assert executor._eval_condition("flag") is True

    def test_false_condition(self, executor_factory):
        """Falsy condition evaluates to False."""
        executor = executor_factory(context_overrides={"flag": False})
        assert executor._eval_condition("flag") is False

    def test_not_condition(self, executor_factory):
        """Negation works in conditions."""
        executor = executor_factory(inputs={"project": ""})
        assert executor._eval_condition("not inputs.project") is True

    def test_undefined_defaults_false(self, executor_factory):
        """Undefined variables in conditions default to False."""
        executor = executor_factory()
        # ChainableUndefined renders to empty string -> False
        assert executor._eval_condition("nonexistent_var") is False

    def test_comparison_condition(self, executor_factory):
        """Comparison operators work in conditions."""
        executor = executor_factory(context_overrides={"count": 5})
        assert executor._eval_condition("count > 3") is True
        assert executor._eval_condition("count > 10") is False
