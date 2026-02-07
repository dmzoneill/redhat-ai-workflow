"""Template resolution tests for skill YAML files.

Verifies that Jinja2 templates in skill step args, output values, and
conditions can be rendered without errors.  Also tests ChainableUndefined
behaviour and the custom Jinja2 filters (jira_link, mr_link, length).

The ``skill_file`` parameter is auto-parametrized by the ``conftest.py`` in
this directory via ``pytest_generate_tests``.
"""

from validate_skills import load_skill


class TestSkillTemplates:
    """Test Jinja2 template resolution across all skills."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load(skill_file):
        skill = load_skill(skill_file)
        assert skill is not None, f"Failed to load {skill_file.name}"
        assert "_error" not in skill, skill.get("_error")
        return skill

    @staticmethod
    def _collect_template_strings(value):
        """Recursively collect strings containing ``{{ }}`` from a value."""
        templates = []
        if isinstance(value, str) and "{{" in value:
            templates.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                templates.extend(TestSkillTemplates._collect_template_strings(v))
        elif isinstance(value, list):
            for item in value:
                templates.extend(TestSkillTemplates._collect_template_strings(item))
        return templates

    # ------------------------------------------------------------------
    # Parametrized tests (one per skill file)
    # ------------------------------------------------------------------

    def test_all_arg_templates_resolve(self, skill_file, make_executor):
        """Every ``{{ }}`` expression in step args must render without Jinja2 error."""
        skill = self._load(skill_file)
        executor = make_executor(skill=skill)

        errors = []
        for step in skill.get("steps", []):
            args = step.get("args", {})
            step_name = step.get("name", "unnamed")
            for arg_key, arg_val in args.items():
                for tpl in self._collect_template_strings(arg_val):
                    try:
                        executor._template(tpl)
                    except Exception as exc:
                        errors.append(f"step '{step_name}' arg '{arg_key}': {exc}")

        assert (
            errors == []
        ), f"{skill_file.name} template errors in args:\n" + "\n".join(
            f"  - {e}" for e in errors
        )

    def test_output_templates_resolve(self, skill_file, make_executor):
        """Output value templates must render without Jinja2 error."""
        skill = self._load(skill_file)
        executor = make_executor(skill=skill)

        errors = []
        for output in skill.get("outputs", []):
            if not isinstance(output, dict):
                continue
            out_name = output.get("name", "unnamed")
            value = output.get("value", "")
            for tpl in self._collect_template_strings(value):
                try:
                    executor._template(tpl)
                except Exception as exc:
                    errors.append(f"output '{out_name}': {exc}")

        assert (
            errors == []
        ), f"{skill_file.name} template errors in outputs:\n" + "\n".join(
            f"  - {e}" for e in errors
        )

    def test_condition_templates_resolve(self, skill_file, make_executor):
        """Condition expressions must render without Jinja2 error.

        We only test that the template *renders* -- we do not assert the
        boolean result because the test context may not match runtime.
        """
        skill = self._load(skill_file)
        executor = make_executor(skill=skill)

        errors = []
        for step in skill.get("steps", []):
            condition = step.get("condition")
            if not condition or not isinstance(condition, str):
                continue
            step_name = step.get("name", "unnamed")
            try:
                # _eval_condition internally wraps in {{ }} and renders
                executor._eval_condition(condition)
            except Exception as exc:
                errors.append(f"step '{step_name}': {exc}")

        assert (
            errors == []
        ), f"{skill_file.name} condition render errors:\n" + "\n".join(
            f"  - {e}" for e in errors
        )

    # ------------------------------------------------------------------
    # Non-parametrized tests
    # ------------------------------------------------------------------

    def test_template_with_missing_vars_renders_empty(self, make_executor):
        """ChainableUndefined must render missing variables as empty string."""
        executor = make_executor(context={})

        result = executor._template("Hello {{ nonexistent_var }}")
        # ChainableUndefined renders undefined variables as empty string
        assert "nonexistent_var" not in result
        assert isinstance(result, str)

        # Chained attribute access should also render empty
        result_chained = executor._template("{{ foo.bar.baz }}")
        assert isinstance(result_chained, str)
        assert "foo" not in result_chained

    def test_custom_jinja_filters(self, make_executor):
        """The custom jira_link, mr_link, and length filters must work."""
        executor = make_executor(
            inputs={"slack_format": False},
            context={
                "inputs": {"slack_format": False},
                "config": {
                    "jira": {"url": "https://issues.redhat.com"},
                    "gitlab": {"url": "https://gitlab.cee.redhat.com"},
                },
                "test_text": "Fix AAP-12345 billing bug",
                "test_mr_text": "See !42 for details",
                "test_list": [1, 2, 3, 4, 5],
            },
        )

        # jira_link filter
        result = executor._template("{{ test_text | jira_link }}")
        assert "AAP-12345" in result
        assert "issues.redhat.com" in result

        # mr_link filter
        result = executor._template("{{ test_mr_text | mr_link }}")
        assert "42" in result
        assert "merge_requests" in result

        # length filter
        result = executor._template("{{ test_list | length }}")
        assert result.strip() == "5"
