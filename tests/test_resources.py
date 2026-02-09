"""Tests for tool_modules.aa_workflow.src.resources module."""

from unittest.mock import MagicMock, patch

import yaml

from tool_modules.aa_workflow.src.resources import (
    _get_current_work,
    _get_environments,
    _get_patterns,
    _get_personas,
    _get_repositories,
    _get_runbooks,
    _get_service_quirks,
    _get_skills,
    register_resources,
)

# ---------------------------------------------------------------------------
# _get_current_work
# ---------------------------------------------------------------------------


class TestGetCurrentWork:
    async def test_returns_file_contents_when_exists(self, tmp_path):
        content = "active_issues:\n- AAP-123\n"
        work_file = tmp_path / "current_work.yaml"
        work_file.write_text(content)

        with patch(
            "tool_modules.aa_workflow.src.chat_context.get_project_work_state_path",
            return_value=work_file,
        ):
            result = await _get_current_work()
        assert result == content

    async def test_returns_default_when_file_missing(self, tmp_path):
        work_file = tmp_path / "nonexistent.yaml"

        with patch(
            "tool_modules.aa_workflow.src.chat_context.get_project_work_state_path",
            return_value=work_file,
        ):
            result = await _get_current_work()
        assert "No current work tracked" in result
        assert "active_issues: []" in result


# ---------------------------------------------------------------------------
# _get_patterns
# ---------------------------------------------------------------------------


class TestGetPatterns:
    async def test_returns_file_contents_when_exists(self, tmp_path):
        content = "patterns:\n- name: test\n"
        patterns_dir = tmp_path / "learned"
        patterns_dir.mkdir()
        patterns_file = patterns_dir / "patterns.yaml"
        patterns_file.write_text(content)

        with patch(
            "tool_modules.aa_workflow.src.resources.MEMORY_DIR",
            tmp_path,
        ):
            result = await _get_patterns()
        assert result == content

    async def test_returns_default_when_file_missing(self, tmp_path):
        with patch(
            "tool_modules.aa_workflow.src.resources.MEMORY_DIR",
            tmp_path,
        ):
            result = await _get_patterns()
        assert "No patterns recorded yet" in result


# ---------------------------------------------------------------------------
# _get_runbooks
# ---------------------------------------------------------------------------


class TestGetRunbooks:
    async def test_returns_file_contents_when_exists(self, tmp_path):
        content = "runbooks:\n  deploy: steps here\n"
        learned_dir = tmp_path / "learned"
        learned_dir.mkdir()
        runbooks_file = learned_dir / "runbooks.yaml"
        runbooks_file.write_text(content)

        with patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path):
            result = await _get_runbooks()
        assert result == content

    async def test_returns_default_when_file_missing(self, tmp_path):
        with patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path):
            result = await _get_runbooks()
        assert "No runbooks recorded yet" in result


# ---------------------------------------------------------------------------
# _get_service_quirks
# ---------------------------------------------------------------------------


class TestGetServiceQuirks:
    async def test_returns_file_contents_when_exists(self, tmp_path):
        content = "services:\n  api: quirky\n"
        learned_dir = tmp_path / "learned"
        learned_dir.mkdir()
        quirks_file = learned_dir / "service_quirks.yaml"
        quirks_file.write_text(content)

        with patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path):
            result = await _get_service_quirks()
        assert result == content

    async def test_returns_default_when_file_missing(self, tmp_path):
        with patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path):
            result = await _get_service_quirks()
        assert "No service quirks recorded yet" in result


# ---------------------------------------------------------------------------
# _get_environments
# ---------------------------------------------------------------------------


class TestGetEnvironments:
    async def test_returns_file_contents_when_exists(self, tmp_path):
        content = "environments:\n  stage:\n    status: healthy\n"
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        env_file = state_dir / "environments.yaml"
        env_file.write_text(content)

        with patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path):
            result = await _get_environments()
        assert result == content

    async def test_returns_default_when_file_missing(self, tmp_path):
        with patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path):
            result = await _get_environments()
        assert "No environment state" in result


# ---------------------------------------------------------------------------
# _get_personas
# ---------------------------------------------------------------------------


class TestGetPersonas:
    async def test_returns_personas_from_yaml_files(self, tmp_path):
        persona_data = {
            "name": "devops",
            "description": "DevOps persona",
            "tools": ["kubectl", "helm"],
            "skills": ["deploy"],
        }
        persona_file = tmp_path / "devops.yaml"
        persona_file.write_text(yaml.dump(persona_data))

        with patch("tool_modules.aa_workflow.src.resources.PERSONAS_DIR", tmp_path):
            result = await _get_personas()

        parsed = yaml.safe_load(result)
        assert "personas" in parsed
        assert len(parsed["personas"]) == 1
        assert parsed["personas"][0]["name"] == "devops"
        assert parsed["personas"][0]["description"] == "DevOps persona"
        assert "kubectl" in parsed["personas"][0]["tools"]

    async def test_returns_empty_when_dir_missing(self, tmp_path):
        missing_dir = tmp_path / "nonexistent"
        with patch("tool_modules.aa_workflow.src.resources.PERSONAS_DIR", missing_dir):
            result = await _get_personas()
        parsed = yaml.safe_load(result)
        assert parsed["personas"] == []

    async def test_skips_invalid_yaml_files(self, tmp_path):
        # Write invalid YAML
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml:: [")

        with patch("tool_modules.aa_workflow.src.resources.PERSONAS_DIR", tmp_path):
            result = await _get_personas()
        parsed = yaml.safe_load(result)
        # Bad files are skipped
        assert parsed["personas"] == []

    async def test_uses_stem_when_name_missing(self, tmp_path):
        persona_data = {"description": "A test"}
        persona_file = tmp_path / "myagent.yaml"
        persona_file.write_text(yaml.dump(persona_data))

        with patch("tool_modules.aa_workflow.src.resources.PERSONAS_DIR", tmp_path):
            result = await _get_personas()
        parsed = yaml.safe_load(result)
        assert parsed["personas"][0]["name"] == "myagent"


# ---------------------------------------------------------------------------
# _get_skills
# ---------------------------------------------------------------------------


class TestGetSkills:
    async def test_returns_skills_from_yaml_files(self, tmp_path):
        skill_data = {
            "name": "deploy",
            "description": "Deploy application",
            "inputs": [{"name": "env"}, {"name": "branch"}],
        }
        skill_file = tmp_path / "deploy.yaml"
        skill_file.write_text(yaml.dump(skill_data))

        with patch("tool_modules.aa_workflow.src.resources.SKILLS_DIR", tmp_path):
            result = await _get_skills()

        parsed = yaml.safe_load(result)
        assert "skills" in parsed
        assert len(parsed["skills"]) == 1
        assert parsed["skills"][0]["name"] == "deploy"
        assert "env" in parsed["skills"][0]["inputs"]
        assert "branch" in parsed["skills"][0]["inputs"]

    async def test_returns_empty_when_dir_missing(self, tmp_path):
        missing_dir = tmp_path / "nonexistent"
        with patch("tool_modules.aa_workflow.src.resources.SKILLS_DIR", missing_dir):
            result = await _get_skills()
        parsed = yaml.safe_load(result)
        assert parsed["skills"] == []

    async def test_skips_invalid_yaml(self, tmp_path):
        bad_file = tmp_path / "broken.yaml"
        bad_file.write_text("{{bad yaml!")

        with patch("tool_modules.aa_workflow.src.resources.SKILLS_DIR", tmp_path):
            result = await _get_skills()
        parsed = yaml.safe_load(result)
        assert parsed["skills"] == []

    async def test_uses_stem_when_name_missing(self, tmp_path):
        skill_data = {"description": "A skill", "inputs": []}
        skill_file = tmp_path / "mystep.yaml"
        skill_file.write_text(yaml.dump(skill_data))

        with patch("tool_modules.aa_workflow.src.resources.SKILLS_DIR", tmp_path):
            result = await _get_skills()
        parsed = yaml.safe_load(result)
        assert parsed["skills"][0]["name"] == "mystep"

    async def test_handles_skill_with_no_inputs(self, tmp_path):
        skill_data = {"name": "simple", "description": "No inputs"}
        skill_file = tmp_path / "simple.yaml"
        skill_file.write_text(yaml.dump(skill_data))

        with patch("tool_modules.aa_workflow.src.resources.SKILLS_DIR", tmp_path):
            result = await _get_skills()
        parsed = yaml.safe_load(result)
        assert parsed["skills"][0]["inputs"] == []


# ---------------------------------------------------------------------------
# _get_repositories
# ---------------------------------------------------------------------------


class TestGetRepositories:
    def test_returns_repositories_from_config(self):
        config = {
            "repositories": {
                "backend": {"path": "/home/user/backend"},
                "frontend": {"path": "/home/user/frontend"},
            }
        }
        load_fn = MagicMock(return_value=config)
        result = _get_repositories(load_fn)
        parsed = yaml.safe_load(result)
        assert "repositories" in parsed
        assert "backend" in parsed["repositories"]
        assert "frontend" in parsed["repositories"]

    def test_returns_empty_when_no_repositories(self):
        load_fn = MagicMock(return_value={})
        result = _get_repositories(load_fn)
        parsed = yaml.safe_load(result)
        assert parsed["repositories"] == {}

    def test_calls_load_config_fn(self):
        load_fn = MagicMock(return_value={"repositories": {}})
        result = _get_repositories(load_fn)
        load_fn.assert_called_once()
        assert result is not None


# ---------------------------------------------------------------------------
# register_resources
# ---------------------------------------------------------------------------


class TestRegisterResources:
    def test_returns_8(self):
        server = MagicMock()
        # server.resource should be a decorator factory
        server.resource = MagicMock(return_value=lambda fn: fn)
        load_fn = MagicMock(return_value={})
        count = register_resources(server, load_fn)
        assert count == 8

    def test_registers_all_resource_uris(self):
        server = MagicMock()
        registered_uris = []

        def capture_uri(uri):
            registered_uris.append(uri)
            return lambda fn: fn

        server.resource = capture_uri
        load_fn = MagicMock(return_value={})
        register_resources(server, load_fn)

        expected_uris = [
            "memory://state/current_work",
            "memory://learned/patterns",
            "memory://learned/runbooks",
            "memory://learned/service_quirks",
            "memory://state/environments",
            "config://personas",
            "config://skills",
            "config://repositories",
        ]
        assert sorted(registered_uris) == sorted(expected_uris)

    async def test_registered_functions_are_callable(self, tmp_path):
        """Ensure the registered decorator-wrapped functions call the underlying helpers."""
        server = MagicMock()
        registered_fns = {}

        def capture_decorator(uri):
            def decorator(fn):
                registered_fns[uri] = fn
                return fn

            return decorator

        server.resource = capture_decorator
        load_fn = MagicMock(return_value={"repositories": {"test": {"path": "/tmp"}}})
        register_resources(server, load_fn)

        # Test all async resources by calling them
        with (
            patch(
                "tool_modules.aa_workflow.src.chat_context.get_project_work_state_path",
                return_value=tmp_path / "nonexistent.yaml",
            ),
            patch("tool_modules.aa_workflow.src.resources.MEMORY_DIR", tmp_path),
            patch(
                "tool_modules.aa_workflow.src.resources.PERSONAS_DIR", tmp_path / "none"
            ),
            patch(
                "tool_modules.aa_workflow.src.resources.SKILLS_DIR", tmp_path / "none"
            ),
        ):
            result = await registered_fns["memory://state/current_work"]()
            assert "No current work" in result

            result = await registered_fns["memory://learned/patterns"]()
            assert "No patterns" in result

            result = await registered_fns["memory://learned/runbooks"]()
            assert "No runbooks" in result

            result = await registered_fns["memory://learned/service_quirks"]()
            assert "No service quirks" in result

            result = await registered_fns["memory://state/environments"]()
            assert "No environment" in result

            result = await registered_fns["config://personas"]()
            assert "personas" in result

            result = await registered_fns["config://skills"]()
            assert "skills" in result

            result = await registered_fns["config://repositories"]()
            assert "test" in result
