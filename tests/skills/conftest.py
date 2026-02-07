"""Pytest fixtures for skill testing.

Provides:
- Automatic parametrization of ``skill_file`` across all 126+ skill YAMLs.
- Factory fixtures to load skill data, create mock executors, and create
  :class:`SkillTestHarness` instances.
- A ``sample_context`` fixture with plausible default values.
- A ``test_exclusions`` fixture loaded from ``tests/test_exclusions.yaml``.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

# Ensure project root and scripts are on sys.path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from tests.skills.harness import SkillTestHarness
from tests.skills.mock_responses import generate_default_response

# Directories
SKILLS_DIR = PROJECT_ROOT / "skills"
PERF_DIR = SKILLS_DIR / "performance"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXCLUSIONS_PATH = PROJECT_ROOT / "tests" / "test_exclusions.yaml"


# ---------------------------------------------------------------------------
# Auto-parametrize helpers
# ---------------------------------------------------------------------------


def _collect_skill_files() -> list[Path]:
    """Collect all skill YAML files from skills/ and all subdirectories."""
    files = sorted(SKILLS_DIR.rglob("*.yaml"))
    return files


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``skill_file`` across every discovered skill YAML.

    Any test function that declares a ``skill_file`` parameter will be
    automatically expanded to one test case per skill file.  The test ID
    is the skill file stem (e.g. ``start_work``, ``deploy_to_ephemeral``).
    """
    if "skill_file" in metafunc.fixturenames:
        files = _collect_skill_files()
        ids = [f.stem for f in files]
        metafunc.parametrize("skill_file", files, ids=ids)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def all_skill_files() -> list[Path]:
    """Return a list of all skill YAML file paths (session-scoped)."""
    return _collect_skill_files()


@pytest.fixture(scope="session")
def valid_tools():
    """Return the set of known tool names (cached for the session)."""
    from validate_skills import get_all_valid_tools

    return get_all_valid_tools()


@pytest.fixture(scope="session")
def test_exclusions() -> dict:
    """Load ``tests/test_exclusions.yaml`` (session-scoped).

    Returns an empty dict if the file does not exist.
    """
    if not EXCLUSIONS_PATH.exists():
        return {}
    with open(EXCLUSIONS_PATH) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Factory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def skill_data():
    """Factory fixture: load a skill YAML by name and return its dict.

    Usage::

        def test_something(skill_data):
            data = skill_data("start_work")
            assert data["name"] == "start_work"
    """

    def _load(name: str) -> dict:
        # Try direct file first, then search subdirectories
        path = SKILLS_DIR / f"{name}.yaml"
        if not path.exists():
            matches = list(SKILLS_DIR.rglob(f"{name}.yaml"))
            if not matches:
                raise FileNotFoundError(f"Skill '{name}' not found under {SKILLS_DIR}")
            path = matches[0]
        with open(path) as f:
            return yaml.safe_load(f)

    return _load


@pytest.fixture
def mock_tool_responses() -> dict[str, dict]:
    """Load default tool responses from ``fixtures/tool_responses.yaml``.

    Returns a dict mapping tool names to response dicts.  Tests can
    override individual entries by updating the returned dict before
    passing it to a harness or executor fixture.
    """
    yaml_path = FIXTURES_DIR / "tool_responses.yaml"
    if not yaml_path.exists():
        return {}
    with open(yaml_path) as f:
        data = yaml.safe_load(f) or {}
    return data


@pytest.fixture
def skill_executor(mock_tool_responses):
    """Factory fixture: create a mock-ready :class:`SkillExecutor`.

    The executor's ``_exec_tool`` is patched to return mock responses.

    Usage::

        def test_something(skill_executor, skill_data):
            data = skill_data("hello_world")
            executor = skill_executor(data, inputs={})
            result = asyncio.run(executor.execute())
    """
    from tool_modules.aa_workflow.src.skill_engine import SkillExecutor

    def _create(
        skill: dict,
        inputs: dict | None = None,
        responses: dict[str, dict] | None = None,
    ) -> SkillExecutor:
        merged = {**mock_tool_responses}
        if responses:
            merged.update(responses)

        executor = SkillExecutor(
            skill=copy.deepcopy(skill),
            inputs=dict(inputs or {}),
            debug=False,
            server=None,
            create_issue_fn=None,
            ask_question_fn=None,
            enable_interactive_recovery=False,
            emit_events=False,
            workspace_uri="test",
        )

        # Patch _exec_tool
        async def _mock_exec_tool(tool_name: str, args: dict) -> dict:
            if tool_name in merged:
                return dict(merged[tool_name])
            return generate_default_response(tool_name, args)

        executor._exec_tool = _mock_exec_tool  # type: ignore[assignment]
        return executor

    return _create


@pytest.fixture
def harness(mock_tool_responses):
    """Factory fixture: create a :class:`SkillTestHarness`.

    Usage::

        async def test_start_work(harness, skill_data):
            h = harness("start_work", inputs={"issue_key": "AAP-1"})
            await h.execute()
            h.assert_tool_called("jira_view_issue")
    """

    # Cache loaded skill data to avoid repeated YAML parsing
    _cache: dict[str, dict] = {}

    def _create(
        skill_name: str,
        inputs: dict | None = None,
        responses: dict[str, dict] | None = None,
    ) -> SkillTestHarness:
        if skill_name not in _cache:
            path = SKILLS_DIR / f"{skill_name}.yaml"
            if not path.exists():
                matches = list(SKILLS_DIR.rglob(f"{skill_name}.yaml"))
                if not matches:
                    raise FileNotFoundError(f"Skill '{skill_name}' not found under {SKILLS_DIR}")
                path = matches[0]
            with open(path) as f:
                _cache[skill_name] = yaml.safe_load(f)

        merged = {**mock_tool_responses}
        if responses:
            merged.update(responses)

        return SkillTestHarness(
            skill=_cache[skill_name],
            inputs=inputs,
            tool_responses=merged,
            debug=False,
        )

    return _create


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_context() -> dict[str, Any]:
    """Provide plausible values for common template variables.

    This context mimics what a real SkillExecutor would have after
    several steps have executed.
    """
    return {
        "inputs": {
            "issue_key": "AAP-12345",
            "repo": "/home/user/src/automation-analytics-backend",
            "repo_name": "automation-analytics-backend",
            "slack_format": False,
            "days_back": 1,
        },
        "config": {
            "jira": {"url": "https://issues.redhat.com"},
            "gitlab": {"url": "https://gitlab.cee.redhat.com"},
            "user": {
                "username": "testuser",
                "full_name": "Test User",
                "email": "testuser@redhat.com",
            },
            "repositories": {
                "automation-analytics-backend": {
                    "path": "/home/user/src/automation-analytics-backend",
                    "gitlab": "automation-analytics/automation-analytics-backend",
                    "jira_project": "AAP",
                },
            },
        },
        "workspace_uri": "default",
        "today": "2026-01-15",
        # Common step outputs that skills reference
        "resolved_repo": "/home/user/src/automation-analytics-backend",
        "branch_check": {"exists": True, "current": "AAP-12345-fix-billing"},
        "issue": {
            "key": "AAP-12345",
            "summary": "Fix billing calculation",
            "status": "In Progress",
            "type": "Bug",
            "assignee": "testuser",
        },
        "mr_info": {
            "id": 42,
            "iid": 42,
            "title": "AAP-12345 Fix billing calculation",
            "state": "opened",
            "branch": "AAP-12345-fix-billing",
        },
        "cfg": {
            "default_branch": "main",
            "jira_project": "AAP",
            "gitlab": "automation-analytics/automation-analytics-backend",
        },
        "ctx": {
            "greeting": "Good morning",
            "today": "2026-01-15",
            "day_name": "Wednesday",
            "time": "09:30",
            "config": {
                "user": {
                    "username": "testuser",
                    "full_name": "Test User",
                },
            },
        },
        # Additional common context variables
        "issue_key": "AAP-12345",
        "issue_summary": "Improve billing calculation accuracy",
        "issue_status": "In Progress",
        "issue_type": "Story",
        "issue_priority": "High",
        "issue_assignee": "testuser@redhat.com",
        "sprint": "Sprint 42",
        "branch": "AAP-12345-billing-calc",
        "repo": "automation-analytics-backend",
        "default_branch": "main",
        "mr_iid": "789",
        "mr_title": "feat(billing): improve vCPU calculation",
        "pipeline_status": "passed",
        "project": "automation-analytics-backend",
        "project_path": "/home/testuser/src/automation-analytics-backend",
        "gitlab_project": "automation-analytics/automation-analytics-backend",
        "jira_project": "AAP",
        "namespace": "tower-analytics-stage",
        "environment": "stage",
        "cluster": "stage",
        "ephemeral_namespace": "ephemeral-abc123",
        "persona": "developer",
        "session_id": "test-session-001",
        "user": "testuser",
        "email": "testuser@redhat.com",
        "team_channel": "#team-analytics",
        "alert_channel": "#alerts-analytics",
    }


@pytest.fixture()
def make_executor(sample_context):
    """Factory fixture that creates a minimal SkillExecutor.

    Returns a callable ``make_executor(skill=None, inputs=None, context=None)``
    that builds a SkillExecutor suitable for unit-testing ``_template`` and
    ``_eval_condition`` without side-effects.
    """
    from tool_modules.aa_workflow.src.skill_engine import SkillExecutor

    def _factory(skill=None, inputs=None, context=None):
        if skill is None:
            skill = {"name": "test_skill", "steps": []}
        if inputs is None:
            inputs = sample_context.get("inputs", {})

        executor = SkillExecutor(
            skill=skill,
            inputs=inputs,
            debug=True,
            server=None,
            emit_events=False,
        )
        # Override context with test data so templates resolve predictably
        if context is not None:
            executor.context.update(context)
        else:
            executor.context.update(sample_context)
        return executor

    return _factory
