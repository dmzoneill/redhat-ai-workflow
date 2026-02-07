"""Tests for memory_schemas module - Pydantic models and validation."""

import logging

import pytest

from scripts.common.memory_schemas import (
    PYDANTIC_AVAILABLE,
    SCHEMAS,
    ActiveIssue,
    AuthPattern,
    BonfirePattern,
    CurrentWork,
    DiscoveredWork,
    Environments,
    EnvironmentStatus,
    EphemeralNamespace,
    ErrorPattern,
    FollowUp,
    JiraCLIPattern,
    OpenMR,
    Patterns,
    PatternUsageStats,
    PipelinePattern,
    ToolFix,
    ToolFixes,
    get_schema_template,
    validate_memory,
)


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestActiveIssue:
    """Tests for ActiveIssue model."""

    def test_valid_issue(self):
        """Should create valid ActiveIssue."""
        issue = ActiveIssue(
            key="AAP-12345",
            summary="Fix the bug",
            status="In Progress",
            branch="aap-12345-fix",
            repo="backend",
            started="2026-01-09T10:00:00",
        )
        assert issue.key == "AAP-12345"
        assert issue.summary == "Fix the bug"

    def test_invalid_key_raises(self):
        """Should raise for invalid key format."""
        with pytest.raises((ValueError, TypeError, KeyError)):
            ActiveIssue(
                key="invalid",
                summary="Test",
                status="In Progress",
                branch="test",
                repo="backend",
                started="2026-01-09T10:00:00",
            )

    def test_empty_key_raises(self):
        """Should raise for empty key."""
        with pytest.raises((ValueError, TypeError, KeyError)):
            ActiveIssue(
                key="",
                summary="Test",
                status="In Progress",
                branch="test",
                repo="backend",
                started="2026-01-09T10:00:00",
            )


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestOpenMR:
    """Tests for OpenMR model."""

    def test_valid_mr(self):
        """Should create valid OpenMR."""
        mr = OpenMR(
            id=1459,
            project="automation-analytics-backend",
            title="AAP-12345 - feat: example",
        )
        assert mr.id == 1459
        assert mr.project == "automation-analytics-backend"

    def test_optional_fields(self):
        """Should handle optional fields."""
        mr = OpenMR(
            id=1,
            project="test",
            title="test mr",
            pipeline_status="passed",
            needs_review=True,
        )
        assert mr.pipeline_status == "passed"
        assert mr.needs_review is True

    def test_defaults(self):
        """Should use defaults for optional fields."""
        mr = OpenMR(id=1, project="test", title="test mr")
        assert mr.pipeline_status is None
        assert mr.needs_review is None


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestDiscoveredWork:
    """Tests for DiscoveredWork model."""

    def test_valid_discovered_work(self):
        """Should create valid DiscoveredWork."""
        dw = DiscoveredWork(
            task="Fix linting errors",
            work_type="tech_debt",
            priority="high",
            source_skill="review_mr",
            source_issue="AAP-12345",
            created="2026-01-09T10:00:00",
        )
        assert dw.task == "Fix linting errors"
        assert dw.work_type == "tech_debt"
        assert dw.jira_synced is False

    def test_defaults(self):
        """Should use defaults for optional fields."""
        dw = DiscoveredWork(
            task="Test task",
            created="2026-01-09T10:00:00",
        )
        assert dw.work_type == "discovered_work"
        assert dw.priority == "medium"
        assert dw.source_skill is None
        assert dw.jira_key is None


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestFollowUp:
    """Tests for FollowUp model."""

    def test_valid_followup(self):
        """Should create valid FollowUp."""
        fu = FollowUp(task="Update docs", priority="high", issue_key="AAP-123")
        assert fu.task == "Update docs"
        assert fu.priority == "high"

    def test_optional_fields(self):
        """Should handle optional fields."""
        fu = FollowUp(task="Simple task")
        assert fu.priority is None
        assert fu.issue_key is None
        assert fu.work_type is None


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestCurrentWork:
    """Tests for CurrentWork model."""

    def test_valid_current_work(self):
        """Should create valid CurrentWork."""
        cw = CurrentWork(
            active_issue="AAP-12345",
            active_issues=[],
            open_mrs=[],
            follow_ups=[],
            discovered_work=[],
            last_updated="2026-01-09T14:00:00",
        )
        assert cw.active_issue == "AAP-12345"
        assert cw.last_updated == "2026-01-09T14:00:00"

    def test_invalid_timestamp_raises(self):
        """Should raise for invalid timestamp."""
        with pytest.raises((ValueError, TypeError, KeyError)):
            CurrentWork(
                last_updated="not-a-timestamp",
            )

    def test_z_suffix_timestamp(self):
        """Should accept UTC Z suffix timestamp."""
        cw = CurrentWork(
            last_updated="2026-01-09T14:00:00Z",
        )
        assert "2026-01-09" in cw.last_updated


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestEnvironmentModels:
    """Tests for environment-related models."""

    def test_environment_status(self):
        """Should create valid EnvironmentStatus."""
        es = EnvironmentStatus(
            status="healthy",
            last_checked="2026-01-09T14:00:00",
            issues=[],
        )
        assert es.status == "healthy"
        assert es.issues == []

    def test_ephemeral_namespace(self):
        """Should create valid EphemeralNamespace."""
        ns = EphemeralNamespace(
            name="ephemeral-abc123",
            deployed_at="2026-01-09T14:00:00",
            expires_at="2026-01-09T18:00:00",
            mr_id=1449,
        )
        assert ns.name == "ephemeral-abc123"
        assert ns.mr_id == 1449

    def test_environments(self):
        """Should create valid Environments."""
        env = Environments(
            environments={
                "stage": EnvironmentStatus(
                    status="healthy",
                    last_checked="2026-01-09T14:00:00",
                    issues=[],
                )
            },
            ephemeral_namespaces=[],
            last_checked="2026-01-09T14:00:00",
        )
        assert "stage" in env.environments
        assert env.environments["stage"].status == "healthy"


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestPatternModels:
    """Tests for pattern-related models."""

    def test_pattern_usage_stats(self):
        """Should create valid PatternUsageStats."""
        stats = PatternUsageStats(
            times_matched=10,
            times_fixed=8,
            success_rate=0.8,
            last_matched="2026-01-09T14:00:00",
        )
        assert stats.times_matched == 10
        assert stats.success_rate == 0.8

    def test_error_pattern(self):
        """Should create valid ErrorPattern."""
        ep = ErrorPattern(
            pattern="connection refused",
            meaning="Cannot connect to service",
            fix="Check if service is running",
            commands=["kubectl get pods"],
        )
        assert ep.pattern == "connection refused"
        assert len(ep.commands) == 1

    def test_auth_pattern(self):
        """Should create valid AuthPattern."""
        ap = AuthPattern(
            pattern="token expired",
            meaning="Kubernetes credentials expired",
            fix="Refresh credentials",
            commands=["kube_login(cluster='e')"],
        )
        assert ap.pattern == "token expired"

    def test_bonfire_pattern(self):
        """Should create valid BonfirePattern."""
        bp = BonfirePattern(
            pattern="manifest unknown",
            fix="Use full SHA",
            commands=["git_rev_parse"],
        )
        assert bp.pattern == "manifest unknown"

    def test_pipeline_pattern(self):
        """Should create valid PipelinePattern."""
        pp = PipelinePattern(
            pattern="lint failed",
            fix="Run linter locally",
            commands=["make lint"],
        )
        assert pp.pattern == "lint failed"

    def test_jira_cli_pattern(self):
        """Should create valid JiraCLIPattern."""
        jp = JiraCLIPattern(
            pattern="401 Unauthorized",
            description="Auth token expired",
            solution="Re-authenticate with Jira",
        )
        assert jp.pattern == "401 Unauthorized"

    def test_patterns_collection(self):
        """Should create valid Patterns collection."""
        p = Patterns(
            auth_patterns=[],
            error_patterns=[],
            bonfire_patterns=[],
            pipeline_patterns=[],
            jira_cli_patterns=[],
            last_updated="2026-01-09T14:00:00",
        )
        assert p.last_updated == "2026-01-09T14:00:00"

    def test_patterns_defaults(self):
        """Should use defaults for empty Patterns."""
        p = Patterns()
        assert p.auth_patterns == []
        assert p.error_patterns == []
        assert p.last_updated is None


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestToolFixModels:
    """Tests for ToolFix and ToolFixes models."""

    def test_tool_fix(self):
        """Should create valid ToolFix."""
        tf = ToolFix(
            tool_name="bonfire_deploy",
            error_pattern="manifest unknown",
            root_cause="Short SHA doesn't exist in Quay",
            fix_applied="Use full 40-char SHA",
            date_learned="2026-01-09",
            times_prevented=5,
        )
        assert tf.tool_name == "bonfire_deploy"
        assert tf.times_prevented == 5

    def test_tool_fix_defaults(self):
        """Should use default for times_prevented."""
        tf = ToolFix(
            tool_name="test",
            error_pattern="error",
            root_cause="cause",
            fix_applied="fix",
            date_learned="2026-01-09",
        )
        assert tf.times_prevented == 0

    def test_tool_fixes_collection(self):
        """Should create valid ToolFixes collection."""
        tfs = ToolFixes(
            tool_fixes=[
                ToolFix(
                    tool_name="test",
                    error_pattern="error",
                    root_cause="cause",
                    fix_applied="fix",
                    date_learned="2026-01-09",
                )
            ],
            common_mistakes={"mistake1": "fix1"},
        )
        assert len(tfs.tool_fixes) == 1
        assert tfs.common_mistakes["mistake1"] == "fix1"


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestSchemaRegistry:
    """Tests for the SCHEMAS registry."""

    def test_schemas_has_expected_keys(self):
        """Should have all expected schema keys."""
        assert "state/current_work" in SCHEMAS
        assert "state/environments" in SCHEMAS
        assert "learned/patterns" in SCHEMAS
        assert "learned/tool_fixes" in SCHEMAS

    def test_schemas_map_to_correct_types(self):
        """Should map to correct model types."""
        assert SCHEMAS["state/current_work"] is CurrentWork
        assert SCHEMAS["state/environments"] is Environments
        assert SCHEMAS["learned/patterns"] is Patterns
        assert SCHEMAS["learned/tool_fixes"] is ToolFixes


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestValidateMemory:
    """Tests for validate_memory function."""

    def test_valid_current_work(self):
        """Should validate correct current_work data."""
        data = {
            "active_issue": "AAP-12345",
            "active_issues": [],
            "open_mrs": [],
            "follow_ups": [],
            "discovered_work": [],
            "last_updated": "2026-01-09T14:00:00",
        }
        assert validate_memory("state/current_work", data) is True

    def test_invalid_current_work(self):
        """Should reject invalid current_work data."""
        data = {
            "last_updated": "not-a-timestamp",
        }
        assert validate_memory("state/current_work", data) is False

    def test_unknown_key_passes(self):
        """Should pass validation for unknown keys."""
        assert validate_memory("unknown/key", {"anything": "goes"}) is True

    def test_valid_environments(self):
        """Should validate correct environments data."""
        data = {
            "environments": {
                "stage": {
                    "status": "healthy",
                    "last_checked": "2026-01-09T14:00:00",
                    "issues": [],
                }
            },
            "ephemeral_namespaces": [],
            "last_checked": "2026-01-09T14:00:00",
        }
        assert validate_memory("state/environments", data) is True

    def test_valid_patterns(self):
        """Should validate correct patterns data."""
        data = {
            "auth_patterns": [],
            "error_patterns": [],
            "bonfire_patterns": [],
            "pipeline_patterns": [],
            "jira_cli_patterns": [],
        }
        assert validate_memory("learned/patterns", data) is True

    def test_valid_tool_fixes(self):
        """Should validate correct tool_fixes data."""
        data = {
            "tool_fixes": [],
            "common_mistakes": {},
        }
        assert validate_memory("learned/tool_fixes", data) is True

    def test_validation_logs_warning(self, caplog):
        """Should log warning on validation failure."""
        data = {"last_updated": "bad"}
        with caplog.at_level(logging.WARNING):
            result = validate_memory("state/current_work", data)
        assert result is False


@pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
class TestGetSchemaTemplate:
    """Tests for get_schema_template function."""

    def test_current_work_template(self):
        """Should generate YAML template for current_work."""
        template = get_schema_template("state/current_work")
        assert template is not None
        assert "AAP-12345" in template
        assert "active_issue" in template

    def test_environments_template(self):
        """Should generate YAML template for environments."""
        template = get_schema_template("state/environments")
        assert template is not None
        assert "stage" in template
        assert "healthy" in template

    def test_patterns_template(self):
        """Should generate YAML template for patterns."""
        template = get_schema_template("learned/patterns")
        assert template is not None
        assert "auth_patterns" in template
        assert "token expired" in template

    def test_tool_fixes_template(self):
        """Should generate YAML template for tool_fixes."""
        template = get_schema_template("learned/tool_fixes")
        assert template is not None
        assert "bonfire_deploy" in template

    def test_unknown_key_returns_none(self):
        """Should return None for unknown key."""
        template = get_schema_template("unknown/key")
        assert template is None

    def test_no_schema_returns_none(self):
        """Should return None when no schema exists."""
        template = get_schema_template("nonexistent/schema")
        assert template is None


class TestValidateMemoryPydanticUnavailable:
    """Tests for validate_memory when PYDANTIC_AVAILABLE is mocked False."""

    def test_returns_true_when_pydantic_unavailable(self):
        """Should return True when pydantic is not available (graceful degradation)."""
        import scripts.common.memory_schemas as mod

        original = mod.PYDANTIC_AVAILABLE
        try:
            mod.PYDANTIC_AVAILABLE = False
            result = validate_memory("state/current_work", {"anything": "goes"})
            assert result is True
        finally:
            mod.PYDANTIC_AVAILABLE = original


class TestGetSchemaTemplateEdgeCases:
    """Tests for get_schema_template edge cases."""

    @pytest.mark.skipif(not PYDANTIC_AVAILABLE, reason="Pydantic not installed")
    def test_template_exception_returns_none(self):
        """Should return None if template creation raises."""
        import scripts.common.memory_schemas as mod

        # Temporarily add a broken schema to trigger exception
        original_schemas = dict(mod.SCHEMAS)
        mod.SCHEMAS["test/broken"] = str  # str() will fail as a schema
        try:
            template = get_schema_template("test/broken")
            assert template is None
        finally:
            mod.SCHEMAS.clear()
            mod.SCHEMAS.update(original_schemas)
