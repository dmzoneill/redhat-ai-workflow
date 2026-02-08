"""Tests for knowledge_tools module.

Tests the helper functions and async tool implementations in
tool_modules/aa_workflow/src/knowledge_tools.py.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from tool_modules.aa_workflow.src import knowledge_tools as kt

# ==================== Fixtures ====================


@pytest.fixture
def temp_knowledge_dir(tmp_path):
    """Create a temporary knowledge directory structure."""
    knowledge_dir = tmp_path / "knowledge" / "personas"
    knowledge_dir.mkdir(parents=True)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    with (
        patch.object(kt, "KNOWLEDGE_DIR", knowledge_dir),
        patch.object(kt, "MEMORY_DIR", tmp_path),
    ):
        yield knowledge_dir


@pytest.fixture
def sample_knowledge():
    """Return a sample knowledge dict."""
    return {
        "metadata": {
            "project": "test-project",
            "persona": "developer",
            "last_updated": "2025-01-01T00:00:00",
            "last_scanned": "2025-01-01T00:00:00",
            "confidence": 0.5,
        },
        "architecture": {
            "overview": "A test project",
            "key_modules": [
                {"path": "src/", "purpose": "Source code", "notes": "Main code"}
            ],
            "data_flow": "A -> B -> C",
            "dependencies": ["flask", "pytest", "pyyaml"],
        },
        "patterns": {
            "coding": [{"pattern": "Python project", "location": "pyproject.toml"}],
            "testing": [{"pattern": "pytest", "example": "pytest tests/"}],
            "deployment": [{"pattern": "Docker", "notes": "Dockerfile present"}],
        },
        "gotchas": [{"issue": "Port conflict", "solution": "Use port 8080"}],
        "learned_from_tasks": [
            {"date": "2025-01-01", "task": "AAP-100", "learning": "Use async calls"}
        ],
    }


@pytest.fixture
def saved_knowledge(temp_knowledge_dir, sample_knowledge):
    """Save sample knowledge and return the path."""
    persona_dir = temp_knowledge_dir / "developer"
    persona_dir.mkdir(parents=True, exist_ok=True)
    knowledge_path = persona_dir / "test-project.yaml"
    with open(knowledge_path, "w") as f:
        yaml.dump(sample_knowledge, f, default_flow_style=False)
    return knowledge_path


# ==================== Helper Function Tests ====================


class TestGetKnowledgePath:
    """Tests for _get_knowledge_path."""

    def test_returns_correct_path(self, temp_knowledge_dir):
        path = kt._get_knowledge_path("developer", "my-project")
        assert path == temp_knowledge_dir / "developer" / "my-project.yaml"

    def test_different_persona(self, temp_knowledge_dir):
        path = kt._get_knowledge_path("devops", "backend")
        assert "devops" in str(path)
        assert path.name == "backend.yaml"


class TestEnsureKnowledgeDir:
    """Tests for _ensure_knowledge_dir."""

    def test_creates_directory(self, temp_knowledge_dir):
        persona_dir = kt._ensure_knowledge_dir("new-persona")
        assert persona_dir.exists()
        assert persona_dir.is_dir()

    def test_idempotent(self, temp_knowledge_dir):
        kt._ensure_knowledge_dir("dev")
        kt._ensure_knowledge_dir("dev")
        assert (temp_knowledge_dir / "dev").exists()


class TestLoadKnowledge:
    """Tests for _load_knowledge."""

    def test_returns_none_when_not_found(self, temp_knowledge_dir):
        result = kt._load_knowledge("developer", "nonexistent")
        assert result is None

    def test_loads_existing_knowledge(self, saved_knowledge):
        result = kt._load_knowledge("developer", "test-project")
        assert result is not None
        assert result["metadata"]["project"] == "test-project"

    def test_handles_corrupt_file(self, temp_knowledge_dir):
        persona_dir = temp_knowledge_dir / "developer"
        persona_dir.mkdir(parents=True, exist_ok=True)
        bad_file = persona_dir / "bad.yaml"
        bad_file.write_text(": : invalid\n\t::")
        result = kt._load_knowledge("developer", "bad")
        # Should return None or empty dict on YAML error
        assert result is None or result == {}

    def test_returns_empty_dict_for_empty_file(self, temp_knowledge_dir):
        persona_dir = temp_knowledge_dir / "developer"
        persona_dir.mkdir(parents=True, exist_ok=True)
        empty_file = persona_dir / "empty.yaml"
        empty_file.touch()
        result = kt._load_knowledge("developer", "empty")
        # Empty YAML returns None from safe_load, falls to {}
        assert result == {} or result is None


class TestSaveKnowledge:
    """Tests for _save_knowledge."""

    def test_saves_new_knowledge(self, temp_knowledge_dir):
        knowledge = {"metadata": {"confidence": 0.5}, "gotchas": []}
        result = kt._save_knowledge("developer", "new-proj", knowledge)
        assert result is True
        path = temp_knowledge_dir / "developer" / "new-proj.yaml"
        assert path.exists()

    def test_updates_metadata(self, temp_knowledge_dir):
        knowledge = {"metadata": {}}
        kt._save_knowledge("developer", "proj", knowledge)
        path = temp_knowledge_dir / "developer" / "proj.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["metadata"]["project"] == "proj"
        assert data["metadata"]["persona"] == "developer"
        assert "last_updated" in data["metadata"]

    def test_save_creates_persona_dir(self, temp_knowledge_dir):
        knowledge = {"metadata": {}}
        kt._save_knowledge("brand-new-persona", "proj", knowledge)
        assert (temp_knowledge_dir / "brand-new-persona").exists()


class TestCheckForSignificantChanges:
    """Tests for _check_for_significant_changes."""

    def test_new_knowledge(self):
        notifications = kt._check_for_significant_changes(
            None, {"metadata": {}}, "proj", "dev"
        )
        assert len(notifications) == 1
        assert "New knowledge" in notifications[0]

    def test_confidence_milestone(self):
        old = {"metadata": {"confidence": 0.6}, "learned_from_tasks": [], "gotchas": []}
        new = {
            "metadata": {"confidence": 0.75},
            "learned_from_tasks": [],
            "gotchas": [],
        }
        notifications = kt._check_for_significant_changes(old, new, "proj", "dev")
        assert any("confidence" in n.lower() for n in notifications)

    def test_no_confidence_milestone_below(self):
        old = {"metadata": {"confidence": 0.3}, "learned_from_tasks": [], "gotchas": []}
        new = {"metadata": {"confidence": 0.5}, "learned_from_tasks": [], "gotchas": []}
        notifications = kt._check_for_significant_changes(old, new, "proj", "dev")
        assert not any("confidence" in n.lower() for n in notifications)

    def test_learning_count_milestone(self):
        old = {"metadata": {}, "learned_from_tasks": [{"x": 1}] * 4, "gotchas": []}
        new = {"metadata": {}, "learned_from_tasks": [{"x": 1}] * 5, "gotchas": []}
        notifications = kt._check_for_significant_changes(old, new, "proj", "dev")
        assert any("learnings" in n.lower() for n in notifications)

    def test_gotcha_added(self):
        old = {"metadata": {}, "learned_from_tasks": [], "gotchas": []}
        new = {"metadata": {}, "learned_from_tasks": [], "gotchas": [{"issue": "x"}]}
        notifications = kt._check_for_significant_changes(old, new, "proj", "dev")
        assert any("gotcha" in n.lower() for n in notifications)

    def test_no_notifications_when_unchanged(self):
        data = {
            "metadata": {"confidence": 0.5},
            "learned_from_tasks": [],
            "gotchas": [],
        }
        notifications = kt._check_for_significant_changes(data, data, "proj", "dev")
        assert notifications == []


class TestDetectProjectFromPath:
    """Tests for _detect_project_from_path."""

    def test_returns_none_when_no_config(self):
        with patch.object(kt, "load_config", return_value=None):
            result = kt._detect_project_from_path()
            assert result is None

    def test_returns_none_when_no_match(self):
        config = {"repositories": {"proj-a": {"path": "/nonexistent/path"}}}
        with patch.object(kt, "load_config", return_value=config):
            result = kt._detect_project_from_path(path="/some/other/path")
            assert result is None

    def test_matches_project_path(self, tmp_path):
        config = {"repositories": {"my-proj": {"path": str(tmp_path)}}}
        with patch.object(kt, "load_config", return_value=config):
            result = kt._detect_project_from_path(path=tmp_path / "subdir")
            assert result == "my-proj"

    def test_returns_none_on_cwd_error(self):
        config = {"repositories": {}}
        with (
            patch.object(kt, "load_config", return_value=config),
            patch("pathlib.Path.cwd", side_effect=OSError("no cwd")),
        ):
            result = kt._detect_project_from_path()
            assert result is None


class TestGetCurrentPersona:
    """Tests for _get_current_persona."""

    def test_returns_persona_from_loader(self):
        mock_loader = MagicMock()
        mock_loader.current_persona = "devops"
        with patch("server.persona_loader.get_loader", return_value=mock_loader):
            result = kt._get_current_persona()
            assert result == "devops"

    def test_returns_none_on_import_error(self):
        with patch.dict("sys.modules", {"server.persona_loader": None}):
            result = kt._get_current_persona()
            assert result is None

    def test_returns_none_when_no_loader(self):
        with patch("server.persona_loader.get_loader", return_value=None):
            result = kt._get_current_persona()
            assert result is None


class TestScanProjectStructure:
    """Tests for _scan_project_structure."""

    def test_scans_existing_project(self, tmp_path):
        # Create a mock project structure
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []")
        (tmp_path / "README.md").write_text("# My Project\n\nA test project.")
        (tmp_path / "Dockerfile").write_text("FROM python:3.11")

        result = kt._scan_project_structure(tmp_path)
        assert "pyproject.toml" in result["config_files"]
        assert "Dockerfile" in result["config_files"]
        assert "README.md" == result["readme"]
        assert "src" in result["directories"]
        assert "tests" in result["directories"]

    def test_nonexistent_path(self):
        result = kt._scan_project_structure(Path("/nonexistent/path"))
        assert result["files"] == []
        assert result["directories"] == []

    def test_parses_package_json(self, tmp_path):
        import json

        pkg = {"dependencies": {"react": "^18.0.0", "express": "^4.0.0"}}
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        result = kt._scan_project_structure(tmp_path)
        assert "package.json" in result["config_files"]
        assert "react" in result["dependencies"]
        assert "express" in result["dependencies"]

    def test_parses_pyproject_toml(self, tmp_path):
        toml_content = """
[project]
dependencies = ["flask>=2.0", "requests==2.28", "pyyaml"]
"""
        (tmp_path / "pyproject.toml").write_text(toml_content)

        result = kt._scan_project_structure(tmp_path)
        assert "flask" in result["dependencies"]
        assert "requests" in result["dependencies"]

    def test_hidden_dirs_excluded(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "visible").mkdir()

        result = kt._scan_project_structure(tmp_path)
        assert ".git" not in result["directories"]
        assert "visible" in result["directories"]

    def test_test_files_detected(self, tmp_path):
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_api.py").touch()
        (tests_dir / "test_models.py").touch()

        result = kt._scan_project_structure(tmp_path)
        assert "test_api.py" in result["test_files"]


class TestGenerateInitialKnowledge:
    """Tests for _generate_initial_knowledge."""

    def test_generates_knowledge(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []")
        (tmp_path / "README.md").write_text("# Title\n\nProject overview paragraph.")

        result = kt._generate_initial_knowledge("my-proj", "developer", tmp_path)
        assert result["metadata"]["project"] == "my-proj"
        assert result["metadata"]["persona"] == "developer"
        assert result["metadata"]["confidence"] == 0.3
        assert result["metadata"]["auto_generated"] is True
        assert "overview" in result["architecture"]

    def test_generates_without_readme(self, tmp_path):
        result = kt._generate_initial_knowledge("proj", "dev", tmp_path)
        assert result["architecture"]["overview"] == "Project: proj"

    def test_detects_python_patterns(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_a.py").touch()

        result = kt._generate_initial_knowledge("proj", "dev", tmp_path)
        coding_patterns = [p["pattern"] for p in result["patterns"]["coding"]]
        assert "Python project" in coding_patterns

    def test_detects_deployment_patterns(self, tmp_path):
        (tmp_path / ".gitlab-ci.yml").write_text("stages: [build]")
        (tmp_path / "Dockerfile").write_text("FROM python:3.11")

        result = kt._generate_initial_knowledge("proj", "dev", tmp_path)
        deploy_patterns = [p["pattern"] for p in result["patterns"]["deployment"]]
        assert "GitLab CI/CD" in deploy_patterns
        assert "Docker containerization" in deploy_patterns

    def test_detects_key_modules(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "lib").mkdir()
        (tmp_path / "app").mkdir()

        result = kt._generate_initial_knowledge("proj", "dev", tmp_path)
        module_paths = [m["path"] for m in result["architecture"]["key_modules"]]
        assert "src/" in module_paths
        assert "lib/" in module_paths
        assert "app/" in module_paths


class TestFormatKnowledgeSummary:
    """Tests for _format_knowledge_summary."""

    def test_formats_full_knowledge(self, sample_knowledge):
        summary = kt._format_knowledge_summary(sample_knowledge)
        assert "test-project" in summary
        assert "developer" in summary
        assert "Architecture" in summary
        assert "Key Modules" in summary
        assert "Dependencies" in summary
        assert "Patterns" in summary
        assert "Gotchas" in summary
        assert "Learned from Tasks" in summary

    def test_formats_minimal_knowledge(self):
        knowledge = {
            "metadata": {"project": "proj", "persona": "dev", "confidence": 0},
            "architecture": {},
            "patterns": {},
            "gotchas": [],
            "learned_from_tasks": [],
        }
        summary = kt._format_knowledge_summary(knowledge)
        assert "proj" in summary
        # Should not include sections with no data
        assert "Gotchas" not in summary

    def test_confidence_emoji_high(self):
        knowledge = {
            "metadata": {"project": "p", "persona": "d", "confidence": 0.8},
            "architecture": {},
            "patterns": {},
            "gotchas": [],
            "learned_from_tasks": [],
        }
        summary = kt._format_knowledge_summary(knowledge)
        assert "80%" in summary

    def test_confidence_emoji_low(self):
        knowledge = {
            "metadata": {"project": "p", "persona": "d", "confidence": 0.2},
            "architecture": {},
            "patterns": {},
            "gotchas": [],
            "learned_from_tasks": [],
        }
        summary = kt._format_knowledge_summary(knowledge)
        assert "20%" in summary


# ==================== Async Tool Implementation Tests ====================


class TestKnowledgeLoadImpl:
    """Tests for _knowledge_load_impl."""

    @pytest.mark.asyncio
    async def test_load_existing_knowledge(self, saved_knowledge):
        result = await kt._knowledge_load_impl(
            project="test-project", persona="developer"
        )
        assert len(result) == 1
        assert "test-project" in result[0].text

    @pytest.mark.asyncio
    async def test_load_no_project_detected(self, temp_knowledge_dir):
        with patch.object(kt, "_detect_project_from_path", return_value=None):
            result = await kt._knowledge_load_impl(project="", persona="dev")
            assert "Could not detect" in result[0].text

    @pytest.mark.asyncio
    async def test_load_no_knowledge_no_scan(self, temp_knowledge_dir):
        result = await kt._knowledge_load_impl(
            project="nonexistent", persona="developer", auto_scan=False
        )
        assert "No knowledge found" in result[0].text

    @pytest.mark.asyncio
    async def test_load_auto_scan_no_config(self, temp_knowledge_dir):
        with patch.object(kt, "load_config", return_value={"repositories": {}}):
            result = await kt._knowledge_load_impl(
                project="unknown-proj", persona="developer", auto_scan=True
            )
            assert "not found in config" in result[0].text

    @pytest.mark.asyncio
    async def test_load_auto_scan_path_missing(self, temp_knowledge_dir):
        config = {"repositories": {"proj": {"path": "/nonexistent/path/xxx"}}}
        with patch.object(kt, "load_config", return_value=config):
            result = await kt._knowledge_load_impl(
                project="proj", persona="developer", auto_scan=True
            )
            assert "does not exist" in result[0].text

    @pytest.mark.asyncio
    async def test_load_auto_scan_generates_knowledge(
        self, temp_knowledge_dir, tmp_path
    ):
        proj_dir = tmp_path / "myproj"
        proj_dir.mkdir()
        (proj_dir / "README.md").write_text("# My Project\n\nOverview here.")

        config = {"repositories": {"myproj": {"path": str(proj_dir)}}}
        with patch.object(kt, "load_config", return_value=config):
            result = await kt._knowledge_load_impl(
                project="myproj", persona="developer", auto_scan=True
            )
            assert "Auto-scanned" in result[0].text

    @pytest.mark.asyncio
    async def test_load_auto_detect_persona(self, saved_knowledge, temp_knowledge_dir):
        with patch.object(kt, "_get_current_persona", return_value=None):
            result = await kt._knowledge_load_impl(project="test-project", persona="")
            assert len(result) == 1
            # Should default to "developer"
            assert "test-project" in result[0].text


class TestKnowledgeScanImpl:
    """Tests for _knowledge_scan_impl."""

    @pytest.mark.asyncio
    async def test_scan_no_project_detected(self, temp_knowledge_dir):
        with patch.object(kt, "_detect_project_from_path", return_value=None):
            result = await kt._knowledge_scan_impl(project="", persona="dev")
            assert "Could not detect" in result[0].text

    @pytest.mark.asyncio
    async def test_scan_project_not_in_config(self, temp_knowledge_dir):
        with patch.object(kt, "load_config", return_value={"repositories": {}}):
            result = await kt._knowledge_scan_impl(
                project="unknown", persona="developer"
            )
            assert "not found in config" in result[0].text

    @pytest.mark.asyncio
    async def test_scan_path_missing(self, temp_knowledge_dir):
        config = {"repositories": {"proj": {"path": "/nonexistent/xyz"}}}
        with patch.object(kt, "load_config", return_value=config):
            result = await kt._knowledge_scan_impl(project="proj", persona="developer")
            assert "does not exist" in result[0].text

    @pytest.mark.asyncio
    async def test_scan_force_overwrites(self, temp_knowledge_dir, tmp_path):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()

        # Create existing knowledge
        persona_dir = temp_knowledge_dir / "developer"
        persona_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "metadata": {"confidence": 0.8},
            "gotchas": [{"issue": "old gotcha"}],
            "learned_from_tasks": [{"learning": "old"}],
            "patterns": {"coding": [], "testing": [], "deployment": []},
        }
        with open(persona_dir / "proj.yaml", "w") as f:
            yaml.dump(existing, f)

        config = {"repositories": {"proj": {"path": str(proj_dir)}}}
        with patch.object(kt, "load_config", return_value=config):
            result = await kt._knowledge_scan_impl(
                project="proj", persona="developer", force=True
            )
            assert "Scanned and created" in result[0].text

    @pytest.mark.asyncio
    async def test_scan_merge_existing(self, temp_knowledge_dir, tmp_path):
        proj_dir = tmp_path / "proj"
        proj_dir.mkdir()
        (proj_dir / "pyproject.toml").write_text("[project]\ndependencies = []")

        persona_dir = temp_knowledge_dir / "developer"
        persona_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            "metadata": {"confidence": 0.4},
            "gotchas": [{"issue": "existing gotcha"}],
            "learned_from_tasks": [{"learning": "existing"}],
            "patterns": {
                "coding": [{"pattern": "Python project", "location": "pyproject.toml"}],
                "testing": [],
                "deployment": [],
            },
        }
        with open(persona_dir / "proj.yaml", "w") as f:
            yaml.dump(existing, f)

        config = {"repositories": {"proj": {"path": str(proj_dir)}}}
        with patch.object(kt, "load_config", return_value=config):
            result = await kt._knowledge_scan_impl(
                project="proj", persona="developer", force=False
            )
            assert "Rescanned and updated" in result[0].text

        # Verify merge preserved existing data
        with open(persona_dir / "proj.yaml") as f:
            data = yaml.safe_load(f)
        assert any("existing gotcha" == g.get("issue") for g in data["gotchas"])
        assert data["metadata"]["confidence"] == 0.5  # 0.4 + 0.1


class TestKnowledgeUpdateImpl:
    """Tests for _knowledge_update_impl."""

    @pytest.mark.asyncio
    async def test_update_no_knowledge(self, temp_knowledge_dir):
        result = await kt._knowledge_update_impl(
            project="nope", persona="dev", section="gotchas", content="test"
        )
        assert "No knowledge found" in result[0].text

    @pytest.mark.asyncio
    async def test_update_append_to_list(self, saved_knowledge):
        result = await kt._knowledge_update_impl(
            project="test-project",
            persona="developer",
            section="gotchas",
            content='{"issue": "New gotcha", "solution": "Fix it"}',
            append=True,
        )
        assert "Updated" in result[0].text

        loaded = kt._load_knowledge("developer", "test-project")
        assert len(loaded["gotchas"]) == 2

    @pytest.mark.asyncio
    async def test_update_replace(self, saved_knowledge):
        result = await kt._knowledge_update_impl(
            project="test-project",
            persona="developer",
            section="architecture.overview",
            content="New overview",
            append=False,
        )
        assert "Updated" in result[0].text

        loaded = kt._load_knowledge("developer", "test-project")
        assert loaded["architecture"]["overview"] == "New overview"

    @pytest.mark.asyncio
    async def test_update_nested_section(self, saved_knowledge):
        result = await kt._knowledge_update_impl(
            project="test-project",
            persona="developer",
            section="patterns.coding",
            content='[{"pattern": "New pattern"}]',
            append=True,
        )
        assert "Updated" in result[0].text

    @pytest.mark.asyncio
    async def test_update_creates_missing_sections(self, saved_knowledge):
        result = await kt._knowledge_update_impl(
            project="test-project",
            persona="developer",
            section="new_section.sub",
            content="value",
            append=False,
        )
        assert "Updated" in result[0].text

    @pytest.mark.asyncio
    async def test_update_increases_confidence(self, saved_knowledge):
        await kt._knowledge_update_impl(
            project="test-project",
            persona="developer",
            section="architecture.overview",
            content="Updated overview",
            append=False,
        )
        loaded = kt._load_knowledge("developer", "test-project")
        assert loaded["metadata"]["confidence"] == 0.55  # 0.5 + 0.05

    @pytest.mark.asyncio
    async def test_update_invalid_yaml_content(self, saved_knowledge):
        """Test that plain string content works even if not valid YAML."""
        result = await kt._knowledge_update_impl(
            project="test-project",
            persona="developer",
            section="architecture.overview",
            content="Just a plain string",
            append=False,
        )
        assert "Updated" in result[0].text


class TestKnowledgeQueryImpl:
    """Tests for _knowledge_query_impl."""

    @pytest.mark.asyncio
    async def test_query_no_project(self, temp_knowledge_dir):
        with patch.object(kt, "_detect_project_from_path", return_value=None):
            result = await kt._knowledge_query_impl(project="", persona="dev")
            assert "Could not detect" in result[0].text

    @pytest.mark.asyncio
    async def test_query_no_knowledge(self, temp_knowledge_dir):
        result = await kt._knowledge_query_impl(
            project="nonexistent", persona="developer"
        )
        assert "No knowledge found" in result[0].text

    @pytest.mark.asyncio
    async def test_query_full_knowledge(self, saved_knowledge):
        result = await kt._knowledge_query_impl(
            project="test-project", persona="developer", section=""
        )
        assert "test-project" in result[0].text

    @pytest.mark.asyncio
    async def test_query_specific_section_dict(self, saved_knowledge):
        result = await kt._knowledge_query_impl(
            project="test-project", persona="developer", section="architecture"
        )
        assert "yaml" in result[0].text.lower() or "overview" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_query_specific_section_string(self, saved_knowledge):
        result = await kt._knowledge_query_impl(
            project="test-project",
            persona="developer",
            section="architecture.overview",
        )
        assert "A test project" in result[0].text

    @pytest.mark.asyncio
    async def test_query_missing_section(self, saved_knowledge):
        result = await kt._knowledge_query_impl(
            project="test-project",
            persona="developer",
            section="nonexistent",
        )
        assert "not found" in result[0].text

    @pytest.mark.asyncio
    async def test_query_list_section(self, saved_knowledge):
        result = await kt._knowledge_query_impl(
            project="test-project",
            persona="developer",
            section="gotchas",
        )
        assert "yaml" in result[0].text.lower() or "Port conflict" in result[0].text


class TestKnowledgeLearnImpl:
    """Tests for _knowledge_learn_impl."""

    @pytest.mark.asyncio
    async def test_learn_no_project(self, temp_knowledge_dir):
        with patch.object(kt, "_detect_project_from_path", return_value=None):
            result = await kt._knowledge_learn_impl(
                learning="test", project="", persona=""
            )
            assert "Could not detect" in result[0].text

    @pytest.mark.asyncio
    async def test_learn_creates_knowledge(self, temp_knowledge_dir):
        result = await kt._knowledge_learn_impl(
            learning="Always use async",
            task="AAP-200",
            project="new-proj",
            persona="developer",
        )
        assert "Learning recorded" in result[0].text

        loaded = kt._load_knowledge("developer", "new-proj")
        assert loaded is not None
        assert len(loaded["learned_from_tasks"]) == 1

    @pytest.mark.asyncio
    async def test_learn_appends_to_existing(self, saved_knowledge):
        result = await kt._knowledge_learn_impl(
            learning="New insight",
            task="AAP-300",
            project="test-project",
            persona="developer",
        )
        assert "Learning recorded" in result[0].text

        loaded = kt._load_knowledge("developer", "test-project")
        assert len(loaded["learned_from_tasks"]) == 2

    @pytest.mark.asyncio
    async def test_learn_gotcha(self, saved_knowledge):
        result = await kt._knowledge_learn_impl(
            learning="Port 3000 conflicts with local dev",
            section="gotchas",
            project="test-project",
            persona="developer",
        )
        assert "Learning recorded" in result[0].text

        loaded = kt._load_knowledge("developer", "test-project")
        assert len(loaded["gotchas"]) == 2

    @pytest.mark.asyncio
    async def test_learn_pattern(self, saved_knowledge):
        result = await kt._knowledge_learn_impl(
            learning="Always use dataclasses",
            section="patterns.coding",
            project="test-project",
            persona="developer",
        )
        assert "Learning recorded" in result[0].text

    @pytest.mark.asyncio
    async def test_learn_custom_section(self, saved_knowledge):
        result = await kt._knowledge_learn_impl(
            learning="Custom value",
            section="custom_section",
            project="test-project",
            persona="developer",
        )
        assert "Learning recorded" in result[0].text

    @pytest.mark.asyncio
    async def test_learn_increases_confidence(self, saved_knowledge):
        await kt._knowledge_learn_impl(
            learning="Insight",
            project="test-project",
            persona="developer",
        )
        loaded = kt._load_knowledge("developer", "test-project")
        assert loaded["metadata"]["confidence"] == 0.52  # 0.5 + 0.02

    @pytest.mark.asyncio
    async def test_learn_without_task(self, saved_knowledge):
        result = await kt._knowledge_learn_impl(
            learning="Generic insight",
            project="test-project",
            persona="developer",
        )
        assert "N/A" in result[0].text

    @pytest.mark.asyncio
    async def test_learn_non_list_section(self, temp_knowledge_dir):
        """Test learning into a section that is not a list (replaces)."""
        # Create knowledge with a non-list section
        persona_dir = temp_knowledge_dir / "developer"
        persona_dir.mkdir(parents=True, exist_ok=True)
        knowledge = {
            "metadata": {"confidence": 0.5},
            "architecture": {"overview": "old overview"},
            "patterns": {"coding": [], "testing": [], "deployment": []},
            "gotchas": [],
            "learned_from_tasks": [],
            "custom_field": "old_value",
        }
        with open(persona_dir / "proj.yaml", "w") as f:
            yaml.dump(knowledge, f)

        result = await kt._knowledge_learn_impl(
            learning="new_value",
            section="custom_field",
            project="proj",
            persona="developer",
        )
        assert "Learning recorded" in result[0].text


class TestKnowledgeListImpl:
    """Tests for _knowledge_list_impl."""

    @pytest.mark.asyncio
    async def test_list_no_dir(self, temp_knowledge_dir):
        import shutil

        # Remove the knowledge dir
        shutil.rmtree(temp_knowledge_dir)
        result = await kt._knowledge_list_impl()
        assert "No knowledge files" in result[0].text

    @pytest.mark.asyncio
    async def test_list_with_knowledge(self, saved_knowledge, temp_knowledge_dir):
        result = await kt._knowledge_list_impl()
        assert "Developer" in result[0].text
        assert "test-project" in result[0].text

    @pytest.mark.asyncio
    async def test_list_empty_dir(self, temp_knowledge_dir):
        result = await kt._knowledge_list_impl()
        assert "No knowledge files" in result[0].text

    @pytest.mark.asyncio
    async def test_list_handles_corrupt_file(self, temp_knowledge_dir):
        persona_dir = temp_knowledge_dir / "developer"
        persona_dir.mkdir(parents=True, exist_ok=True)
        bad_file = persona_dir / "bad.yaml"
        bad_file.write_text(": invalid yaml :")

        result = await kt._knowledge_list_impl()
        # Should still work, just show the project name
        assert "bad" in result[0].text or "Developer" in result[0].text


class TestDetectProjectFromCtx:
    """Tests for _detect_project_from_ctx."""

    @pytest.mark.asyncio
    async def test_none_ctx_falls_back(self):
        with patch.object(kt, "_detect_project_from_path", return_value="fallback"):
            result = await kt._detect_project_from_ctx(None)
            assert result == "fallback"

    @pytest.mark.asyncio
    async def test_ctx_with_workspace(self):
        mock_ctx = MagicMock()
        mock_ws_mod = MagicMock()
        mock_ws_mod.get_workspace_project = AsyncMock(return_value="ws-project")
        with patch.dict("sys.modules", {"server.workspace_utils": mock_ws_mod}):
            result = await kt._detect_project_from_ctx(mock_ctx)
            assert result == "ws-project"

    @pytest.mark.asyncio
    async def test_ctx_falls_back_on_error(self):
        mock_ctx = MagicMock()
        mock_ws_mod = MagicMock()
        mock_ws_mod.get_workspace_project = AsyncMock(side_effect=Exception("fail"))
        with (
            patch.dict("sys.modules", {"server.workspace_utils": mock_ws_mod}),
            patch.object(kt, "_detect_project_from_path", return_value="path-project"),
        ):
            result = await kt._detect_project_from_ctx(mock_ctx)
            assert result == "path-project"


class TestGetPersonaFromCtx:
    """Tests for _get_persona_from_ctx."""

    @pytest.mark.asyncio
    async def test_none_ctx_returns_default(self):
        with patch.object(kt, "_get_current_persona", return_value=None):
            result = await kt._get_persona_from_ctx(None)
            assert result == "developer"

    @pytest.mark.asyncio
    async def test_none_ctx_returns_current(self):
        with patch.object(kt, "_get_current_persona", return_value="devops"):
            result = await kt._get_persona_from_ctx(None)
            assert result == "devops"

    @pytest.mark.asyncio
    async def test_ctx_with_workspace(self):
        mock_ctx = MagicMock()
        mock_ws_mod = MagicMock()
        mock_ws_mod.get_workspace_persona = AsyncMock(return_value="incident")
        with patch.dict("sys.modules", {"server.workspace_utils": mock_ws_mod}):
            result = await kt._get_persona_from_ctx(mock_ctx)
            assert result == "incident"

    @pytest.mark.asyncio
    async def test_ctx_falls_back_on_error(self):
        mock_ctx = MagicMock()
        mock_ws_mod = MagicMock()
        mock_ws_mod.get_workspace_persona = AsyncMock(side_effect=Exception("fail"))
        with (
            patch.dict("sys.modules", {"server.workspace_utils": mock_ws_mod}),
            patch.object(kt, "_get_current_persona", return_value="release"),
        ):
            result = await kt._get_persona_from_ctx(mock_ctx)
            assert result == "release"
