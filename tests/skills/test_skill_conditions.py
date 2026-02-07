"""Condition evaluation tests for the SkillExecutor.

Validates that ``_eval_condition`` correctly handles truthy/falsy values,
negation, dict methods, compound expressions, undefined variables, Jinja2
filters, and Python operators.

Also includes a smoke test that extracts every ``condition:`` string from
every skill YAML file and verifies it can be parsed without errors.
"""

import re

import pytest
import yaml
from validate_skills import load_skill


class TestConditionEvaluation:
    """Test SkillExecutor._eval_condition with various expression types."""

    # ------------------------------------------------------------------
    # Basic truthiness
    # ------------------------------------------------------------------

    def test_simple_truthy_condition(self, make_executor):
        """A truthy context variable should evaluate to True."""
        executor = make_executor(context={"some_var": "non-empty"})
        assert executor._eval_condition("some_var") is True

    def test_simple_falsy_condition(self, make_executor):
        """An empty string should evaluate to False."""
        executor = make_executor(context={"some_var": ""})
        assert executor._eval_condition("some_var") is False

    # ------------------------------------------------------------------
    # Negation
    # ------------------------------------------------------------------

    def test_negation_condition(self, make_executor):
        """``not`` should invert a truthy value."""
        executor = make_executor(context={"flag": True})
        assert executor._eval_condition("not flag") is False

    def test_negation_of_false(self, make_executor):
        """``not`` on a falsy value should return True."""
        executor = make_executor(context={"flag": False})
        assert executor._eval_condition("not flag") is True

    # ------------------------------------------------------------------
    # Dict .get() access
    # ------------------------------------------------------------------

    def test_dict_get_in_condition(self, make_executor):
        """Accessing a dict value via ``.get()`` should work."""
        executor = make_executor(context={"data": {"status": "active"}})
        assert executor._eval_condition("data.get('status')") is True

    def test_dict_get_missing_key(self, make_executor):
        """``.get()`` on a missing key should return the default (falsy)."""
        executor = make_executor(context={"data": {}})
        assert executor._eval_condition("data.get('missing', '')") is False

    # ------------------------------------------------------------------
    # Compound expressions
    # ------------------------------------------------------------------

    def test_complex_and_condition(self, make_executor):
        """Multi-part ``and`` expression should be True only if all parts are truthy."""
        executor = make_executor(
            context={
                "has_branch": True,
                "has_issue": True,
                "is_ready": True,
            }
        )
        assert executor._eval_condition("has_branch and has_issue and is_ready") is True

    def test_complex_and_one_false(self, make_executor):
        """``and`` should short-circuit to False if any part is falsy."""
        executor = make_executor(
            context={
                "has_branch": True,
                "has_issue": False,
                "is_ready": True,
            }
        )
        assert executor._eval_condition("has_branch and has_issue and is_ready") is False

    # ------------------------------------------------------------------
    # Undefined variables
    # ------------------------------------------------------------------

    def test_missing_var_defaults_to_false(self, make_executor):
        """An undefined variable should evaluate to False (not raise)."""
        executor = make_executor(context={})
        result = executor._eval_condition("totally_undefined_var")
        assert result is False

    # ------------------------------------------------------------------
    # Jinja2 filters
    # ------------------------------------------------------------------

    def test_jinja_filter_in_condition(self, make_executor):
        """The ``|length`` filter should work inside conditions."""
        executor = make_executor(context={"items": [1, 2, 3]})
        assert executor._eval_condition("items|length > 0") is True

    def test_jinja_length_zero(self, make_executor):
        """``|length`` on an empty list should allow comparison to 0."""
        executor = make_executor(context={"items": []})
        assert executor._eval_condition("items|length > 0") is False

    # ------------------------------------------------------------------
    # Python ``in`` operator
    # ------------------------------------------------------------------

    def test_in_operator_condition(self, make_executor):
        """Python ``in`` operator should work for membership tests."""
        executor = make_executor(context={"status": "merged"})
        assert executor._eval_condition("status in ['merged', 'closed']") is True

    def test_in_operator_not_found(self, make_executor):
        """``in`` should return False when value is not in the list."""
        executor = make_executor(context={"status": "open"})
        assert executor._eval_condition("status in ['merged', 'closed']") is False

    # ------------------------------------------------------------------
    # Smoke test: all real conditions from every skill
    # ------------------------------------------------------------------

    def test_all_real_conditions_parse(self, all_skill_files, make_executor):
        """Every condition string in every skill file must parse without error.

        This is a smoke test -- we only verify that the condition can be
        evaluated by the Jinja2 engine without raising an exception.  The
        boolean result is irrelevant since we use a synthetic context.
        """
        errors = []

        for skill_path in all_skill_files:
            skill = load_skill(skill_path)
            if skill is None or "_error" in skill:
                continue

            executor = make_executor(skill=skill)

            for step in skill.get("steps", []):
                condition = step.get("condition")
                if not condition or not isinstance(condition, str):
                    continue

                step_name = step.get("name", "unnamed")
                try:
                    executor._eval_condition(condition)
                except Exception as exc:
                    errors.append(f"{skill_path.stem}:{step_name}: {exc}")

        assert errors == [], f"{len(errors)} condition(s) failed to parse:\n" + "\n".join(f"  - {e}" for e in errors)
