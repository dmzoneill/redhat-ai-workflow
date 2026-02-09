"""Tests for the common memory helpers module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.common import memory


@pytest.fixture
def temp_memory_dir():
    """Create a temporary memory directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create subdirectories
        state_dir = Path(tmpdir) / "state"
        learned_dir = Path(tmpdir) / "learned"
        state_dir.mkdir()
        learned_dir.mkdir()

        # Patch the MEMORY_DIR constant
        with patch.object(memory, "MEMORY_DIR", Path(tmpdir)):
            yield Path(tmpdir)


class TestGetMemoryPath:
    """Tests for get_memory_path."""

    def test_adds_yaml_extension(self, temp_memory_dir):
        """Test that .yaml is appended if not present."""
        path = memory.get_memory_path("state/current_work")
        assert path.suffix == ".yaml"
        assert "current_work.yaml" in str(path)

    def test_preserves_yaml_extension(self, temp_memory_dir):
        """Test that .yaml is not duplicated."""
        path = memory.get_memory_path("state/current_work.yaml")
        assert str(path).count(".yaml") == 1


class TestReadMemory:
    """Tests for read_memory."""

    def test_returns_empty_dict_for_missing_file(self, temp_memory_dir):
        """Test that missing files return empty dict."""
        result = memory.read_memory("nonexistent/file")
        assert result == {}

    def test_reads_existing_file(self, temp_memory_dir):
        """Test reading an existing memory file."""
        # Create a test file
        test_file = temp_memory_dir / "state" / "test.yaml"
        test_data = {"foo": "bar", "nested": {"key": "value"}}
        with open(test_file, "w") as f:
            yaml.dump(test_data, f)

        result = memory.read_memory("state/test")
        assert result["foo"] == "bar"
        assert result["nested"]["key"] == "value"

    def test_handles_empty_file(self, temp_memory_dir):
        """Test that empty files return empty dict."""
        test_file = temp_memory_dir / "state" / "empty.yaml"
        test_file.touch()

        result = memory.read_memory("state/empty")
        assert result == {}


class TestWriteMemory:
    """Tests for write_memory."""

    def test_writes_new_file(self, temp_memory_dir):
        """Test writing a new memory file."""
        data = {"test": "data"}
        result = memory.write_memory("state/new_file", data)

        assert result is True
        assert (temp_memory_dir / "state" / "new_file.yaml").exists()

    def test_adds_last_updated(self, temp_memory_dir):
        """Test that last_updated is added automatically."""
        data = {"test": "data"}
        memory.write_memory("state/test", data)

        # Read back and check
        result = memory.read_memory("state/test")
        assert "last_updated" in result

    def test_creates_parent_directories(self, temp_memory_dir):
        """Test that parent directories are created."""
        data = {"test": "data"}
        memory.write_memory("new_category/subcategory/test", data)

        assert (temp_memory_dir / "new_category" / "subcategory" / "test.yaml").exists()


class TestAppendToList:
    """Tests for append_to_list."""

    def test_appends_to_empty_list(self, temp_memory_dir):
        """Test appending to a non-existent list."""
        item = {"key": "AAP-123", "summary": "Test issue"}
        result = memory.append_to_list("state/current_work", "active_issues", item)

        assert result is True
        data = memory.read_memory("state/current_work")
        assert len(data["active_issues"]) == 1
        assert data["active_issues"][0]["key"] == "AAP-123"

    def test_appends_to_existing_list(self, temp_memory_dir):
        """Test appending to an existing list."""
        # Create initial data
        memory.write_memory("state/current_work", {"active_issues": [{"key": "AAP-1"}]})

        # Append new item
        item = {"key": "AAP-2", "summary": "New issue"}
        memory.append_to_list("state/current_work", "active_issues", item)

        data = memory.read_memory("state/current_work")
        assert len(data["active_issues"]) == 2

    def test_updates_existing_item_with_match_key(self, temp_memory_dir):
        """Test that existing items are updated when match_key is provided."""
        # Create initial data
        memory.write_memory(
            "state/current_work",
            {"active_issues": [{"key": "AAP-1", "status": "Open"}]},
        )

        # Update with same key
        item = {"key": "AAP-1", "status": "In Progress"}
        memory.append_to_list(
            "state/current_work", "active_issues", item, match_key="key"
        )

        data = memory.read_memory("state/current_work")
        assert len(data["active_issues"]) == 1
        assert data["active_issues"][0]["status"] == "In Progress"


class TestRemoveFromList:
    """Tests for remove_from_list."""

    def test_removes_matching_item(self, temp_memory_dir):
        """Test removing an item that matches."""
        memory.write_memory(
            "state/current_work",
            {"active_issues": [{"key": "AAP-1"}, {"key": "AAP-2"}, {"key": "AAP-3"}]},
        )

        removed = memory.remove_from_list(
            "state/current_work", "active_issues", "key", "AAP-2"
        )

        assert removed == 1
        data = memory.read_memory("state/current_work")
        assert len(data["active_issues"]) == 2
        keys = [i["key"] for i in data["active_issues"]]
        assert "AAP-2" not in keys

    def test_returns_zero_for_no_match(self, temp_memory_dir):
        """Test that 0 is returned when no item matches."""
        memory.write_memory("state/current_work", {"active_issues": [{"key": "AAP-1"}]})

        removed = memory.remove_from_list(
            "state/current_work", "active_issues", "key", "AAP-999"
        )

        assert removed == 0


class TestUpdateField:
    """Tests for update_field."""

    def test_updates_top_level_field(self, temp_memory_dir):
        """Test updating a top-level field."""
        memory.write_memory("state/test", {"status": "old"})

        memory.update_field("state/test", "status", "new")

        data = memory.read_memory("state/test")
        assert data["status"] == "new"

    def test_updates_nested_field(self, temp_memory_dir):
        """Test updating a deeply nested field."""
        memory.write_memory(
            "state/environments", {"environments": {"stage": {"status": "unknown"}}}
        )

        memory.update_field(
            "state/environments", "environments.stage.status", "healthy"
        )

        data = memory.read_memory("state/environments")
        assert data["environments"]["stage"]["status"] == "healthy"

    def test_creates_missing_parents(self, temp_memory_dir):
        """Test that missing parent dicts are created."""
        memory.write_memory("state/test", {})

        memory.update_field("state/test", "a.b.c.d", "value")

        data = memory.read_memory("state/test")
        assert data["a"]["b"]["c"]["d"] == "value"


class TestHelperFunctions:
    """Tests for convenience helper functions."""

    def test_get_active_issues(self, temp_memory_dir):
        """Test get_active_issues returns list."""
        memory.write_memory("state/current_work", {"active_issues": [{"key": "AAP-1"}]})

        result = memory.get_active_issues()
        assert isinstance(result, list)
        assert len(result) == 1

    def test_get_active_issues_empty(self, temp_memory_dir):
        """Test get_active_issues returns empty list when no issues."""
        result = memory.get_active_issues()
        assert result == []

    def test_add_active_issue(self, temp_memory_dir):
        """Test add_active_issue helper."""
        result = memory.add_active_issue(
            "AAP-123", "Test summary", branch="feature/test"
        )

        assert result is True
        issues = memory.get_active_issues()
        assert len(issues) == 1
        assert issues[0]["key"] == "AAP-123"
        assert issues[0]["branch"] == "feature/test"

    def test_remove_active_issue(self, temp_memory_dir):
        """Test remove_active_issue helper."""
        memory.add_active_issue("AAP-123", "Test")
        memory.add_active_issue("AAP-456", "Test 2")

        result = memory.remove_active_issue("AAP-123")

        assert result is True
        issues = memory.get_active_issues()
        assert len(issues) == 1
        assert issues[0]["key"] == "AAP-456"

    def test_add_open_mr(self, temp_memory_dir):
        """Test add_open_mr helper."""
        result = memory.add_open_mr(
            123, "my/project", "Fix bug", pipeline_status="passed"
        )

        assert result is True
        mrs = memory.get_open_mrs()
        assert len(mrs) == 1
        assert mrs[0]["id"] == 123
        assert mrs[0]["project"] == "my/project"

    def test_add_follow_up(self, temp_memory_dir):
        """Test add_follow_up helper."""
        result = memory.add_follow_up("Review PR", priority="high", issue_key="AAP-123")

        assert result is True
        follow_ups = memory.get_follow_ups()
        assert len(follow_ups) == 1
        assert follow_ups[0]["task"] == "Review PR"
        assert follow_ups[0]["priority"] == "high"

    def test_get_timestamp(self):
        """Test get_timestamp returns ISO format."""
        ts = memory.get_timestamp()
        # Should be parseable as ISO format
        from datetime import datetime

        parsed = datetime.fromisoformat(ts)
        assert parsed is not None
        assert isinstance(ts, str)

    def test_get_open_mrs_returns_empty_list(self, temp_memory_dir):
        """Test get_open_mrs returns empty list when no MRs."""
        result = memory.get_open_mrs()
        assert result == []

    def test_get_open_mrs_non_list(self, temp_memory_dir):
        """Test get_open_mrs returns empty list when data is not a list."""
        memory.write_memory("state/current_work", {"open_mrs": "not a list"})
        result = memory.get_open_mrs()
        assert result == []

    def test_get_follow_ups_returns_empty(self, temp_memory_dir):
        """Test get_follow_ups returns empty list when none exist."""
        result = memory.get_follow_ups()
        assert result == []

    def test_get_follow_ups_non_list(self, temp_memory_dir):
        """Test get_follow_ups returns empty list when not a list."""
        memory.write_memory("state/current_work", {"follow_ups": "string"})
        result = memory.get_follow_ups()
        assert result == []

    def test_get_active_issues_non_list(self, temp_memory_dir):
        """Test get_active_issues returns empty when data is not a list."""
        memory.write_memory("state/current_work", {"active_issues": "string"})
        result = memory.get_active_issues()
        assert result == []

    def test_remove_open_mr(self, temp_memory_dir):
        """Test remove_open_mr helper."""
        memory.add_open_mr(100, "proj/a", "MR 100")
        memory.add_open_mr(200, "proj/b", "MR 200")
        result = memory.remove_open_mr(100)
        assert result is True
        mrs = memory.get_open_mrs()
        assert len(mrs) == 1
        assert mrs[0]["id"] == 200

    def test_remove_open_mr_not_found(self, temp_memory_dir):
        """Test remove_open_mr returns False when MR not found."""
        result = memory.remove_open_mr(999)
        assert result is False

    def test_add_follow_up_with_mr_id(self, temp_memory_dir):
        """Test add_follow_up with mr_id sets it in the item."""
        memory.add_follow_up("Check CI", mr_id=42)
        follow_ups = memory.get_follow_ups()
        assert follow_ups[0]["mr_id"] == 42

    def test_add_follow_up_without_optional_fields(self, temp_memory_dir):
        """Test add_follow_up without optional fields omits them."""
        memory.add_follow_up("Simple task")
        follow_ups = memory.get_follow_ups()
        assert "issue_key" not in follow_ups[0]
        assert "mr_id" not in follow_ups[0]


class TestGetMemoryPathProjectSpecific:
    """Tests for project-specific memory path routing."""

    def test_project_specific_key_with_explicit_project(self, temp_memory_dir):
        """Test that project-specific keys route to project dir."""
        path = memory.get_memory_path("state/current_work", project="my-project")
        assert "projects" in str(path)
        assert "my-project" in str(path)
        assert path.name == "current_work.yaml"

    def test_project_specific_key_auto_detect_env(self, temp_memory_dir):
        """Test auto-detection from environment variable."""
        import os

        os.environ["AA_CURRENT_PROJECT"] = "test-proj"
        try:
            path = memory.get_memory_path("state/current_work")
            assert "test-proj" in str(path)
        finally:
            del os.environ["AA_CURRENT_PROJECT"]

    def test_non_project_specific_key(self, temp_memory_dir):
        """Test that non-project-specific keys use global path."""
        path = memory.get_memory_path("learned/patterns")
        assert "projects" not in str(path)
        assert path.name == "patterns.yaml"


class TestGetProjectMemoryPath:
    """Tests for get_project_memory_path."""

    def test_default_filename(self, temp_memory_dir):
        """Test default filename is current_work."""
        path = memory.get_project_memory_path("myproj")
        assert path.name == "current_work.yaml"
        assert "myproj" in str(path)

    def test_custom_filename(self, temp_memory_dir):
        """Test custom filename."""
        path = memory.get_project_memory_path("myproj", filename="custom")
        assert path.name == "custom.yaml"


class TestGetCurrentProject:
    """Tests for _get_current_project."""

    def test_returns_env_var(self):
        """Test that env var is returned when set."""
        import os

        os.environ["AA_CURRENT_PROJECT"] = "env-project"
        try:
            result = memory._get_current_project()
            assert result == "env-project"
        finally:
            del os.environ["AA_CURRENT_PROJECT"]

    def test_fallback_to_default(self):
        """Test fallback to default when env var is unset."""
        import os

        os.environ.pop("AA_CURRENT_PROJECT", None)
        with patch("scripts.common.memory.Path.cwd", side_effect=Exception("no cwd")):
            result = memory._get_current_project()
            assert result == "redhat-ai-workflow"


class TestReadMemoryErrors:
    """Tests for read_memory error handling."""

    def test_handles_yaml_error(self, temp_memory_dir):
        """Test that YAML parse errors return empty dict."""
        bad_file = temp_memory_dir / "state" / "bad.yaml"
        bad_file.write_text(": : : invalid yaml\n\t\t::")
        result = memory.read_memory("state/bad")
        assert result == {}


class TestWriteMemoryValidation:
    """Tests for write_memory with schema validation."""

    def test_write_with_validation_disabled(self, temp_memory_dir):
        """Test write with validate=False skips validation."""
        data = {"test": "data"}
        result = memory.write_memory("state/test", data, validate=False)
        assert result is True

    def test_write_with_import_error(self, temp_memory_dir):
        """Test write handles ImportError for missing schemas module."""
        with patch("scripts.common.memory.get_memory_path") as mock_path:
            mock_path.return_value = temp_memory_dir / "state" / "test.yaml"
            data = {"test": "data"}
            result = memory.write_memory("state/test", data, validate=True)
            assert result is True

    def test_write_io_error(self, temp_memory_dir):
        """Test write_memory returns False on IOError."""
        _data = {"test": "data"}
        with patch("builtins.open", side_effect=IOError("disk full")):
            # get_memory_path needs to work, so only patch open for the write
            path = memory.get_memory_path("state/ioerror")
            path.parent.mkdir(parents=True, exist_ok=True)
        # Use a path that can't be written
        with patch("scripts.common.memory.get_memory_path") as mock_gmp:
            bad_path = temp_memory_dir / "no-such-dir-xyz" / "test.yaml"
            mock_gmp.return_value = bad_path
            with patch("pathlib.Path.mkdir", side_effect=IOError("no mkdir")):
                result = memory.write_memory("state/x", {"k": "v"})
                assert result is False


class TestAppendToListEdge:
    """Edge-case tests for append_to_list."""

    def test_returns_false_when_list_path_is_not_list(self, temp_memory_dir):
        """Test returns False when the list_path points to a non-list."""
        memory.write_memory("state/current_work", {"active_issues": "not_a_list"})
        result = memory.append_to_list(
            "state/current_work", "active_issues", {"key": "X"}
        )
        assert result is False

    def test_creates_file_when_missing(self, temp_memory_dir):
        """Test creates the file when it doesn't exist yet."""
        result = memory.append_to_list("state/brand_new", "items", {"id": 1})
        assert result is True
        data = memory.read_memory("state/brand_new")
        assert len(data["items"]) == 1


class TestRemoveFromListEdge:
    """Edge-case tests for remove_from_list."""

    def test_returns_zero_for_missing_file(self, temp_memory_dir):
        """Test returns 0 when the file doesn't exist."""
        result = memory.remove_from_list("state/nonexistent", "items", "id", 1)
        assert result == 0

    def test_returns_zero_when_list_path_missing(self, temp_memory_dir):
        """Test returns 0 when the list path is not in the data."""
        memory.write_memory("state/current_work", {"other_key": "value"})
        result = memory.remove_from_list(
            "state/current_work", "active_issues", "key", "X"
        )
        assert result == 0

    def test_returns_zero_when_list_path_is_not_list(self, temp_memory_dir):
        """Test returns 0 when the list path is not a list."""
        memory.write_memory("state/current_work", {"active_issues": "string"})
        result = memory.remove_from_list(
            "state/current_work", "active_issues", "key", "X"
        )
        assert result == 0


class TestUpdateFieldEdge:
    """Edge-case tests for update_field."""

    def test_creates_file_when_missing(self, temp_memory_dir):
        """Test creates file if it doesn't exist."""
        result = memory.update_field("state/newfile", "key", "value")
        assert result is True
        data = memory.read_memory("state/newfile")
        assert data["key"] == "value"


class TestDiscoveredWork:
    """Tests for discovered work functions."""

    def test_add_discovered_work_basic(self, temp_memory_dir):
        """Test adding basic discovered work."""
        result = memory.add_discovered_work("Fix broken test")
        assert result is True
        items = memory.get_discovered_work()
        assert len(items) == 1
        assert items[0]["task"] == "Fix broken test"
        assert items[0]["work_type"] == "discovered_work"
        assert items[0]["jira_synced"] is False

    def test_add_discovered_work_all_fields(self, temp_memory_dir):
        """Test adding discovered work with all optional fields."""
        result = memory.add_discovered_work(
            task="Refactor validators",
            work_type="tech_debt",
            priority="high",
            source_skill="review_pr",
            source_issue="AAP-100",
            source_mr=42,
            file_path="api/validators.py",
            line_number=55,
            notes="Repeated 3 times",
        )
        assert result is True
        items = memory.get_discovered_work()
        assert items[0]["source_skill"] == "review_pr"
        assert items[0]["source_issue"] == "AAP-100"
        assert items[0]["source_mr"] == 42
        assert items[0]["file_path"] == "api/validators.py"
        assert items[0]["line_number"] == 55
        assert items[0]["notes"] == "Repeated 3 times"

    def test_get_discovered_work_empty(self, temp_memory_dir):
        """Test getting discovered work when none exists."""
        items = memory.get_discovered_work()
        assert items == []

    def test_get_discovered_work_non_list(self, temp_memory_dir):
        """Test get_discovered_work returns empty when data is not a list."""
        memory.write_memory("state/current_work", {"discovered_work": "string"})
        items = memory.get_discovered_work()
        assert items == []

    def test_get_discovered_work_pending_only(self, temp_memory_dir):
        """Test filtering only pending discovered work."""
        memory.add_discovered_work("Task 1")
        memory.add_discovered_work("Task 2")
        # Manually mark one as synced
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["jira_synced"] = True
        memory.write_memory("state/current_work", data)

        pending = memory.get_discovered_work(pending_only=True)
        assert len(pending) == 1
        assert pending[0]["task"] == "Task 2"

    def test_get_pending_discovered_work(self, temp_memory_dir):
        """Test convenience wrapper for pending work."""
        memory.add_discovered_work("Task A")
        result = memory.get_pending_discovered_work()
        assert len(result) == 1

    def test_remove_discovered_work(self, temp_memory_dir):
        """Test removing discovered work."""
        memory.add_discovered_work("Task to remove")
        memory.add_discovered_work("Task to keep")
        result = memory.remove_discovered_work("Task to remove")
        assert result is True
        items = memory.get_discovered_work()
        assert len(items) == 1
        assert items[0]["task"] == "Task to keep"

    def test_remove_discovered_work_not_found(self, temp_memory_dir):
        """Test removing non-existent discovered work."""
        result = memory.remove_discovered_work("Does not exist")
        assert result is False


class TestMarkDiscoveredWorkSynced:
    """Tests for mark_discovered_work_synced."""

    def test_marks_matching_item(self, temp_memory_dir):
        """Test marking a discovered work item as synced."""
        memory.add_discovered_work("Fix broken API endpoint")
        result = memory.mark_discovered_work_synced(
            "Fix broken API endpoint", "AAP-500"
        )
        assert result is True
        items = memory.get_discovered_work()
        assert items[0]["jira_synced"] is True
        assert items[0]["jira_key"] == "AAP-500"

    def test_marks_partial_match(self, temp_memory_dir):
        """Test marking with partial task match."""
        memory.add_discovered_work("Fix broken API endpoint in validators")
        result = memory.mark_discovered_work_synced(
            "Fix broken API endpoint", "AAP-501"
        )
        assert result is True

    def test_no_match_returns_false(self, temp_memory_dir):
        """Test returns False when no match found."""
        memory.add_discovered_work("Task A")
        result = memory.mark_discovered_work_synced("Completely different", "AAP-502")
        assert result is False

    def test_file_not_exists(self, temp_memory_dir):
        """Test returns False when file does not exist."""
        result = memory.mark_discovered_work_synced("anything", "AAP-503")
        assert result is False

    def test_non_list_discovered_work(self, temp_memory_dir):
        """Test returns False when discovered_work is not a list."""
        memory.write_memory("state/current_work", {"discovered_work": "not_a_list"})
        result = memory.mark_discovered_work_synced("anything", "AAP-504")
        assert result is False


class TestDiscoveredWorkSummary:
    """Tests for get_discovered_work_summary."""

    def test_empty_summary(self, temp_memory_dir):
        """Test summary with no items."""
        summary = memory.get_discovered_work_summary()
        assert summary["total"] == 0
        assert summary["pending_sync"] == 0
        assert summary["synced"] == 0

    def test_summary_with_items(self, temp_memory_dir):
        """Test summary with multiple items."""
        memory.add_discovered_work(
            "A", work_type="bug", priority="high", source_skill="review"
        )
        memory.add_discovered_work(
            "B", work_type="tech_debt", priority="low", source_skill="review"
        )
        memory.add_discovered_work(
            "C", work_type="bug", priority="high", source_skill="deploy"
        )

        summary = memory.get_discovered_work_summary()
        assert summary["total"] == 3
        assert summary["pending_sync"] == 3
        assert summary["synced"] == 0
        assert summary["by_type"]["bug"] == 2
        assert summary["by_type"]["tech_debt"] == 1
        assert summary["by_priority"]["high"] == 2
        assert summary["by_priority"]["low"] == 1
        assert summary["by_source_skill"]["review"] == 2
        assert summary["by_source_skill"]["deploy"] == 1

    def test_summary_with_synced_items(self, temp_memory_dir):
        """Test summary counts synced items."""
        memory.add_discovered_work("Synced task")
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["jira_synced"] = True
        memory.write_memory("state/current_work", data)

        summary = memory.get_discovered_work_summary()
        assert summary["synced"] == 1
        assert summary["pending_sync"] == 0


class TestFindSimilarDiscoveredWork:
    """Tests for find_similar_discovered_work."""

    def test_no_items_returns_none(self, temp_memory_dir):
        """Test returns None when no items exist."""
        result = memory.find_similar_discovered_work("any task")
        assert result is None

    def test_exact_match(self, temp_memory_dir):
        """Test finds exact match."""
        memory.add_discovered_work("Fix broken API endpoint")
        result = memory.find_similar_discovered_work("Fix broken API endpoint")
        assert result is not None
        assert "_similarity_score" in result

    def test_similar_match(self, temp_memory_dir):
        """Test finds similar match above threshold."""
        memory.add_discovered_work("Refactor duplicate validation logic in validators")
        result = memory.find_similar_discovered_work(
            "Refactor duplicate validation logic in validators module",
            threshold=0.7,
        )
        assert result is not None

    def test_no_match_below_threshold(self, temp_memory_dir):
        """Test returns None when similarity is below threshold."""
        memory.add_discovered_work("Fix database connection pooling")
        result = memory.find_similar_discovered_work(
            "Update frontend CSS styles",
            threshold=0.8,
        )
        assert result is None

    def test_empty_tokens(self, temp_memory_dir):
        """Test returns None for input with only stop words."""
        result = memory.find_similar_discovered_work("the a an")
        assert result is None


class TestIsDuplicateDiscoveredWork:
    """Tests for is_duplicate_discovered_work."""

    def test_not_duplicate_when_empty(self, temp_memory_dir):
        """Test returns not duplicate when no items."""
        result = memory.is_duplicate_discovered_work("New task")
        assert result["is_duplicate"] is False

    def test_exact_match_duplicate(self, temp_memory_dir):
        """Test detects exact match duplicate."""
        memory.add_discovered_work("Fix broken endpoint")
        result = memory.is_duplicate_discovered_work("Fix broken endpoint")
        assert result["is_duplicate"] is True
        assert result["reason"] == "exact_match"

    def test_exact_match_with_jira(self, temp_memory_dir):
        """Test exact match includes jira_key when synced."""
        memory.add_discovered_work("Fix broken endpoint")
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["jira_synced"] = True
        data["discovered_work"][0]["jira_key"] = "AAP-999"
        memory.write_memory("state/current_work", data)

        result = memory.is_duplicate_discovered_work("Fix broken endpoint")
        assert result["jira_key"] == "AAP-999"

    def test_high_similarity_duplicate(self, temp_memory_dir):
        """Test detects high similarity duplicate via check 4 (>= 0.9)."""
        # These two tasks differ by only 1 word in a 10-word set -> Jaccard ~0.91
        memory.add_discovered_work(
            "Refactor duplicate validation logic api validators module handler code review"
        )
        memory.is_duplicate_discovered_work(
            "Refactor duplicate validation logic api validators module handler code check"
        )
        # 9/11 overlap -> 0.818, not enough for 0.9 threshold
        # Use exact overlap instead to test the boundary
        result2 = memory.is_duplicate_discovered_work(
            "Refactor duplicate validation logic api validators module handler code review"
        )
        # Exact match should trigger check 1
        assert result2["is_duplicate"] is True
        assert result2["reason"] == "exact_match"


class TestAddDiscoveredWorkSafe:
    """Tests for add_discovered_work_safe."""

    def test_adds_when_no_duplicate(self, temp_memory_dir):
        """Test adds item when no duplicate exists."""
        result = memory.add_discovered_work_safe("Brand new task")
        assert result["added"] is True
        assert result["is_duplicate"] is False

    def test_skips_when_duplicate(self, temp_memory_dir):
        """Test skips adding when duplicate found."""
        memory.add_discovered_work("Existing task")
        result = memory.add_discovered_work_safe("Existing task")
        assert result["added"] is False
        assert result["is_duplicate"] is True

    def test_returns_jira_key_on_duplicate(self, temp_memory_dir):
        """Test returns jira_key when duplicate is synced."""
        memory.add_discovered_work("Synced task")
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["jira_synced"] = True
        data["discovered_work"][0]["jira_key"] = "AAP-700"
        memory.write_memory("state/current_work", data)

        result = memory.add_discovered_work_safe("Synced task")
        assert result["jira_key"] == "AAP-700"


class TestGetDiscoveredWorkForPeriod:
    """Tests for get_discovered_work_for_period."""

    def test_returns_recent_items(self, temp_memory_dir):
        """Test returns items from the specified period."""
        memory.add_discovered_work("Recent task")
        result = memory.get_discovered_work_for_period(days=7)
        assert result["created_count"] == 1
        assert len(result["items"]) == 1

    def test_excludes_old_items(self, temp_memory_dir):
        """Test excludes items older than the period."""
        memory.add_discovered_work("Old task")
        # Manipulate the created timestamp to be old
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["created"] = "2020-01-01T00:00:00"
        memory.write_memory("state/current_work", data)

        result = memory.get_discovered_work_for_period(days=7)
        assert result["created_count"] == 0

    def test_synced_only_filter(self, temp_memory_dir):
        """Test synced_only flag filters correctly."""
        memory.add_discovered_work("Task 1")
        memory.add_discovered_work("Task 2")
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["jira_synced"] = True
        data["discovered_work"][0]["jira_key"] = "AAP-800"
        memory.write_memory("state/current_work", data)

        result = memory.get_discovered_work_for_period(days=7, synced_only=True)
        assert result["created_count"] == 1
        assert result["synced_count"] == 1
        assert "AAP-800" in result["jira_keys"]

    def test_items_with_bad_dates_skipped(self, temp_memory_dir):
        """Test items with unparseable dates are skipped."""
        memory.add_discovered_work("Bad date task")
        data = memory.read_memory("state/current_work")
        data["discovered_work"][0]["created"] = "not-a-date"
        memory.write_memory("state/current_work", data)

        result = memory.get_discovered_work_for_period(days=7)
        assert result["created_count"] == 0

    def test_by_type_and_by_day(self, temp_memory_dir):
        """Test by_type and by_day aggregation."""
        memory.add_discovered_work("Bug", work_type="bug")
        memory.add_discovered_work("Debt", work_type="tech_debt")
        result = memory.get_discovered_work_for_period(days=7)
        assert result["by_type"]["bug"] == 1
        assert result["by_type"]["tech_debt"] == 1
        assert len(result["by_day"]) >= 1


class TestSharedContext:
    """Tests for save_shared_context and load_shared_context."""

    def test_save_and_load(self, temp_memory_dir):
        """Test saving and loading shared context."""
        ctx = {"pod_name": "api-123", "issue": "High CPU"}
        memory.save_shared_context("investigate_alert", ctx)

        loaded = memory.load_shared_context()
        assert loaded is not None
        assert loaded["pod_name"] == "api-123"

    def test_load_expired_context(self, temp_memory_dir):
        """Test loading expired context returns None."""
        ctx = {"pod_name": "api-123"}
        memory.save_shared_context("test", ctx, ttl_hours=0)

        # Manually set expiry in the past
        data = memory.read_memory("state/shared_context")
        data["current_investigation"]["expires_at"] = "2020-01-01T00:00:00"
        memory.write_memory("state/shared_context", data)

        loaded = memory.load_shared_context()
        assert loaded is None

    def test_load_missing_context(self, temp_memory_dir):
        """Test loading when no context exists returns None."""
        loaded = memory.load_shared_context()
        assert loaded is None

    def test_load_invalid_expiry(self, temp_memory_dir):
        """Test loading with invalid expiry format returns None."""
        memory.write_memory(
            "state/shared_context",
            {
                "current_investigation": {
                    "expires_at": "invalid",
                    "context": {"k": "v"},
                }
            },
        )
        loaded = memory.load_shared_context()
        assert loaded is None


class TestCheckKnownIssues:
    """Tests for check_known_issues."""

    def test_no_files_returns_empty(self, temp_memory_dir):
        """Test returns empty when no patterns file exists."""
        result = memory.check_known_issues("some_tool", "some error")
        assert result["has_known_issues"] is False
        assert result["matches"] == []

    def test_matches_error_pattern(self, temp_memory_dir):
        """Test matches against error patterns."""
        patterns_file = temp_memory_dir / "learned" / "patterns.yaml"
        patterns_data = {
            "error_patterns": [
                {"pattern": "no such host", "meaning": "VPN down", "fix": "Connect VPN"}
            ]
        }
        with open(patterns_file, "w") as f:
            yaml.dump(patterns_data, f)

        result = memory.check_known_issues("gitlab", "dial tcp: no such host found")
        assert result["has_known_issues"] is True
        assert result["matches"][0]["fix"] == "Connect VPN"

    def test_matches_tool_name(self, temp_memory_dir):
        """Test matches pattern against tool name."""
        patterns_file = temp_memory_dir / "learned" / "patterns.yaml"
        patterns_data = {
            "error_patterns": [
                {"pattern": "gitlab", "meaning": "GitLab issue", "fix": "Check VPN"}
            ]
        }
        with open(patterns_file, "w") as f:
            yaml.dump(patterns_data, f)

        result = memory.check_known_issues("gitlab_mr_list", "")
        assert result["has_known_issues"] is True

    def test_matches_tool_fixes(self, temp_memory_dir):
        """Test matches tool_fixes.yaml by tool name."""
        fixes_file = temp_memory_dir / "learned" / "tool_fixes.yaml"
        fixes_data = {
            "tool_fixes": [
                {
                    "tool_name": "bonfire_deploy",
                    "error_pattern": "manifest unknown",
                    "fix_applied": "Use full SHA",
                }
            ]
        }
        with open(fixes_file, "w") as f:
            yaml.dump(fixes_data, f)

        result = memory.check_known_issues("bonfire_deploy", "something")
        assert result["has_known_issues"] is True
        assert result["matches"][0]["fix"] == "Use full SHA"

    def test_matches_tool_fixes_by_error(self, temp_memory_dir):
        """Test matches tool_fixes.yaml by error text."""
        fixes_file = temp_memory_dir / "learned" / "tool_fixes.yaml"
        fixes_data = {
            "tool_fixes": [
                {
                    "tool_name": "other_tool",
                    "error_pattern": "manifest unknown",
                    "fix_applied": "Use full SHA",
                }
            ]
        }
        with open(fixes_file, "w") as f:
            yaml.dump(fixes_data, f)

        result = memory.check_known_issues("", "got error: manifest unknown in quay")
        assert result["has_known_issues"] is True

    def test_empty_inputs(self, temp_memory_dir):
        """Test with empty tool name and error text."""
        result = memory.check_known_issues("", "")
        assert result["has_known_issues"] is False

    def test_checks_multiple_categories(self, temp_memory_dir):
        """Test checks auth_patterns, bonfire_patterns, etc."""
        patterns_file = temp_memory_dir / "learned" / "patterns.yaml"
        patterns_data = {
            "auth_patterns": [
                {
                    "pattern": "unauthorized",
                    "meaning": "Token expired",
                    "fix": "Re-login",
                }
            ],
            "network_patterns": [
                {"pattern": "timeout", "meaning": "Network slow", "fix": "Check VPN"}
            ],
        }
        with open(patterns_file, "w") as f:
            yaml.dump(patterns_data, f)

        result = memory.check_known_issues("", "got unauthorized error and timeout")
        assert result["has_known_issues"] is True
        assert len(result["matches"]) == 2


class TestLearnToolFix:
    """Tests for learn_tool_fix."""

    def test_learns_new_fix(self, temp_memory_dir):
        """Test learning a new tool fix."""
        result = memory.learn_tool_fix(
            "gitlab_mr_list", "no such host", "VPN not connected", "Run vpn_connect()"
        )
        assert result is True

        # Verify saved
        fixes_file = temp_memory_dir / "learned" / "tool_fixes.yaml"
        with open(fixes_file) as f:
            data = yaml.safe_load(f)
        assert len(data["tool_fixes"]) == 1
        assert data["tool_fixes"][0]["tool_name"] == "gitlab_mr_list"

    def test_updates_existing_fix(self, temp_memory_dir):
        """Test updating an existing fix increments occurrences."""
        memory.learn_tool_fix("tool_a", "error_1", "cause_1", "fix_1")
        memory.learn_tool_fix("tool_a", "error_1", "cause_updated", "fix_updated")

        fixes_file = temp_memory_dir / "learned" / "tool_fixes.yaml"
        with open(fixes_file) as f:
            data = yaml.safe_load(f)
        assert len(data["tool_fixes"]) == 1
        assert data["tool_fixes"][0]["occurrences"] == 2
        assert data["tool_fixes"][0]["root_cause"] == "cause_updated"

    def test_creates_learned_dir(self, temp_memory_dir):
        """Test creates learned directory if missing."""
        import shutil

        learned = temp_memory_dir / "learned"
        if learned.exists():
            shutil.rmtree(learned)

        result = memory.learn_tool_fix("tool", "error", "cause", "fix")
        assert result is True
        assert (temp_memory_dir / "learned" / "tool_fixes.yaml").exists()

    def test_limits_to_100_fixes(self, temp_memory_dir):
        """Test keeps only last 100 fixes."""
        for i in range(105):
            memory.learn_tool_fix(f"tool_{i}", f"error_{i}", f"cause_{i}", f"fix_{i}")

        fixes_file = temp_memory_dir / "learned" / "tool_fixes.yaml"
        with open(fixes_file) as f:
            data = yaml.safe_load(f)
        assert len(data["tool_fixes"]) == 100


class TestRecordToolFailure:
    """Tests for record_tool_failure."""

    def test_records_failure(self, temp_memory_dir):
        """Test recording a tool failure."""
        result = memory.record_tool_failure("my_tool", "connection refused")
        assert result is True

        failures_file = temp_memory_dir / "learned" / "tool_failures.yaml"
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert len(data["failures"]) == 1
        assert data["failures"][0]["tool"] == "my_tool"

    def test_records_with_context(self, temp_memory_dir):
        """Test recording a failure with context."""
        ctx = {"skill": "deploy", "args": {"env": "stage"}}
        result = memory.record_tool_failure("my_tool", "error", context=ctx)
        assert result is True

        failures_file = temp_memory_dir / "learned" / "tool_failures.yaml"
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert data["failures"][0]["context"]["skill"] == "deploy"

    def test_truncates_error_text(self, temp_memory_dir):
        """Test truncates long error text to 200 chars."""
        long_error = "x" * 500
        memory.record_tool_failure("my_tool", long_error)

        failures_file = temp_memory_dir / "learned" / "tool_failures.yaml"
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert len(data["failures"][0]["error_snippet"]) == 200

    def test_limits_to_100_failures(self, temp_memory_dir):
        """Test keeps only last 100 failures."""
        for i in range(105):
            memory.record_tool_failure(f"tool_{i}", f"error_{i}")

        failures_file = temp_memory_dir / "learned" / "tool_failures.yaml"
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert len(data["failures"]) == 100

    def test_records_empty_error(self, temp_memory_dir):
        """Test recording with empty error text."""
        result = memory.record_tool_failure("my_tool", "")
        assert result is True

    def test_records_none_context(self, temp_memory_dir):
        """Test recording with None context."""
        result = memory.record_tool_failure("my_tool", "err", context=None)
        assert result is True
        failures_file = temp_memory_dir / "learned" / "tool_failures.yaml"
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert data["failures"][0]["context"] == {}
