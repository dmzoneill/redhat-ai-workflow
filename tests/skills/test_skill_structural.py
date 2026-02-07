"""Structural validation tests for skill YAML files.

Wraps the validators from ``scripts/validate_skills.py`` as pytest tests so
that every skill file is individually checked.  Each test loads the skill YAML,
runs one validator, and asserts that no errors are returned.

The ``skill_file`` parameter is auto-parametrized by the ``conftest.py`` in
this directory via ``pytest_generate_tests``.
"""

from validate_skills import (
    load_skill,
    validate_compute_syntax,
    validate_inputs,
    validate_on_error,
    validate_steps_not_in_outputs,
    validate_structure,
    validate_tool_names,
    validate_unique_step_names,
)


class TestSkillStructuralValidation:
    """Validate structural correctness of every skill YAML file."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load(skill_file):
        """Load a skill file and fail fast on parse errors."""
        skill = load_skill(skill_file)
        assert skill is not None, f"Failed to load {skill_file.name}"
        assert (
            "_error" not in skill
        ), f"YAML parse error in {skill_file.name}: {skill.get('_error')}"
        return skill

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_valid_yaml_structure(self, skill_file):
        """Skill must be valid YAML with required top-level keys (name, steps)."""
        skill = self._load(skill_file)
        errors = validate_structure(skill)
        # Filter out warnings (they contain the word 'warning')
        real_errors = [e for e in errors if "warning" not in e.lower()]
        assert real_errors == [], f"{skill_file.name} structural errors: {real_errors}"

    def test_tool_names_resolve(self, skill_file, valid_tools):
        """Every tool name referenced in steps must exist in the tool registry."""
        if not valid_tools:
            import pytest

            pytest.skip("Tool manifest not available")
        skill = self._load(skill_file)
        errors = validate_tool_names(skill, valid_tools)
        assert errors == [], f"{skill_file.name} unknown tools: {errors}"

    def test_compute_syntax_valid(self, skill_file):
        """Compute blocks must be syntactically valid Python."""
        skill = self._load(skill_file)
        errors = validate_compute_syntax(skill)
        assert errors == [], f"{skill_file.name} compute syntax errors: {errors}"

    def test_no_tools_in_outputs(self, skill_file):
        """The outputs section must not contain tool or compute keys."""
        skill = self._load(skill_file)
        errors = validate_steps_not_in_outputs(skill)
        assert errors == [], f"{skill_file.name} has tool/compute in outputs: {errors}"

    def test_on_error_values_valid(self, skill_file):
        """on_error values must be one of: continue, auto_heal, abort, fail."""
        skill = self._load(skill_file)
        errors = validate_on_error(skill)
        assert errors == [], f"{skill_file.name} invalid on_error values: {errors}"

    def test_no_duplicate_step_names(self, skill_file):
        """Step names within a skill must be unique."""
        skill = self._load(skill_file)
        errors = validate_unique_step_names(skill)
        assert errors == [], f"{skill_file.name} duplicate step names: {errors}"

    def test_inputs_have_names(self, skill_file):
        """Every input definition must have a 'name' field."""
        skill = self._load(skill_file)
        errors = validate_inputs(skill)
        assert errors == [], f"{skill_file.name} input errors: {errors}"
