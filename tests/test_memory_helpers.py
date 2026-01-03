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
        memory.write_memory("state/current_work", {"active_issues": [{"key": "AAP-1", "status": "Open"}]})

        # Update with same key
        item = {"key": "AAP-1", "status": "In Progress"}
        memory.append_to_list("state/current_work", "active_issues", item, match_key="key")

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

        removed = memory.remove_from_list("state/current_work", "active_issues", "key", "AAP-2")

        assert removed == 1
        data = memory.read_memory("state/current_work")
        assert len(data["active_issues"]) == 2
        keys = [i["key"] for i in data["active_issues"]]
        assert "AAP-2" not in keys

    def test_returns_zero_for_no_match(self, temp_memory_dir):
        """Test that 0 is returned when no item matches."""
        memory.write_memory("state/current_work", {"active_issues": [{"key": "AAP-1"}]})

        removed = memory.remove_from_list("state/current_work", "active_issues", "key", "AAP-999")

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
        memory.write_memory("state/environments", {"environments": {"stage": {"status": "unknown"}}})

        memory.update_field("state/environments", "environments.stage.status", "healthy")

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
        result = memory.add_active_issue("AAP-123", "Test summary", branch="feature/test")

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
        result = memory.add_open_mr(123, "my/project", "Fix bug", pipeline_status="passed")

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

        datetime.fromisoformat(ts)
