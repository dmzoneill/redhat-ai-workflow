"""Tests for ConfigManager.

Tests thread safety, debouncing, file locking, and mtime-based cache invalidation.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfigManager:
    """Test ConfigManager functionality."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temporary config file for testing."""
        config_file = tmp_path / "config.json"
        initial_config = {
            "test_section": {"key1": "value1", "key2": 42},
            "schedules": {"enabled": True, "jobs": []},
        }
        config_file.write_text(json.dumps(initial_config, indent=2))
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        """Create a ConfigManager instance with temp config file."""
        # Import here to avoid circular imports
        from server.config_manager import ConfigManager

        # Reset singleton for testing
        ConfigManager._instance = None

        # Patch CONFIG_FILE to use temp file
        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            # Clean up
            ConfigManager._instance = None

    def test_get_section(self, config_manager):
        """Test getting an entire section."""
        section = config_manager.get("test_section")
        assert section is not None
        assert section["key1"] == "value1"
        assert section["key2"] == 42

    def test_get_key(self, config_manager):
        """Test getting a specific key from a section."""
        value = config_manager.get("test_section", "key1")
        assert value == "value1"

    def test_get_with_default(self, config_manager):
        """Test getting with default value."""
        value = config_manager.get("nonexistent", "key", default="default_value")
        assert value == "default_value"

    def test_get_all(self, config_manager):
        """Test getting entire config."""
        all_config = config_manager.get_all()
        assert "test_section" in all_config
        assert "schedules" in all_config

    def test_set_value(self, config_manager, temp_config):
        """Test setting a value."""
        config_manager.set("test_section", "new_key", "new_value", flush=True)

        # Verify in memory
        assert config_manager.get("test_section", "new_key") == "new_value"

        # Verify on disk
        disk_config = json.loads(temp_config.read_text())
        assert disk_config["test_section"]["new_key"] == "new_value"

    def test_set_creates_section(self, config_manager, temp_config):
        """Test that set creates a new section if needed."""
        config_manager.set("new_section", "key", "value", flush=True)

        assert config_manager.get("new_section", "key") == "value"

        disk_config = json.loads(temp_config.read_text())
        assert disk_config["new_section"]["key"] == "value"

    def test_update_section_merge(self, config_manager, temp_config):
        """Test updating a section with merge=True."""
        config_manager.update_section("test_section", {"key3": "value3"}, merge=True, flush=True)

        # Original keys should still exist
        assert config_manager.get("test_section", "key1") == "value1"
        # New key should be added
        assert config_manager.get("test_section", "key3") == "value3"

    def test_update_section_replace(self, config_manager, temp_config):
        """Test updating a section with merge=False."""
        config_manager.update_section("test_section", {"only_key": "only_value"}, merge=False, flush=True)

        # Original keys should be gone
        assert config_manager.get("test_section", "key1") is None
        # New key should exist
        assert config_manager.get("test_section", "only_key") == "only_value"

    def test_delete_key(self, config_manager, temp_config):
        """Test deleting a key."""
        result = config_manager.delete("test_section", "key1", flush=True)
        assert result is True
        assert config_manager.get("test_section", "key1") is None

    def test_delete_section(self, config_manager, temp_config):
        """Test deleting an entire section."""
        result = config_manager.delete("test_section", flush=True)
        assert result is True
        assert config_manager.has_section("test_section") is False

    def test_delete_nonexistent(self, config_manager):
        """Test deleting nonexistent key returns False."""
        result = config_manager.delete("nonexistent", "key")
        assert result is False

    def test_has_section(self, config_manager):
        """Test has_section method."""
        assert config_manager.has_section("test_section") is True
        assert config_manager.has_section("nonexistent") is False

    def test_sections(self, config_manager):
        """Test sections method."""
        sections = config_manager.sections()
        assert "test_section" in sections
        assert "schedules" in sections

    def test_is_dirty(self, config_manager):
        """Test is_dirty property."""
        assert config_manager.is_dirty is False

        config_manager.set("test_section", "key", "value")
        assert config_manager.is_dirty is True

        config_manager.flush()
        assert config_manager.is_dirty is False

    def test_reload(self, config_manager, temp_config):
        """Test reload method."""
        # Modify file externally
        new_config = {"external_section": {"external_key": "external_value"}}
        temp_config.write_text(json.dumps(new_config, indent=2))

        # Reload
        config_manager.reload()

        # Should see new content
        assert config_manager.has_section("external_section")
        assert config_manager.get("external_section", "external_key") == "external_value"

    def test_mtime_auto_reload(self, config_manager, temp_config):
        """Test automatic reload when file mtime changes."""
        # Wait a bit to ensure mtime difference
        time.sleep(0.1)

        # Modify file externally
        new_config = {"auto_reload_section": {"key": "value"}}
        temp_config.write_text(json.dumps(new_config, indent=2))

        # Access should trigger auto-reload
        assert config_manager.has_section("auto_reload_section")

    def test_debounce_batches_writes(self, config_manager, temp_config):
        """Test that debounce batches multiple writes."""
        # Make multiple rapid changes
        for i in range(5):
            config_manager.set("batch_section", f"key{i}", f"value{i}")

        # Should be dirty but not yet written
        assert config_manager.is_dirty is True

        # Wait for debounce timer (2 seconds + buffer)
        time.sleep(2.5)

        # Should now be written
        assert config_manager.is_dirty is False

        # Verify all values on disk
        disk_config = json.loads(temp_config.read_text())
        for i in range(5):
            assert disk_config["batch_section"][f"key{i}"] == f"value{i}"


class TestConfigManagerThreadSafety:
    """Test ConfigManager thread safety."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temporary config file for testing."""
        config_file = tmp_path / "config.json"
        initial_config = {"counter": {"value": 0}}
        config_file.write_text(json.dumps(initial_config, indent=2))
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        """Create a ConfigManager instance with temp config file."""
        from server.config_manager import ConfigManager

        ConfigManager._instance = None

        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            ConfigManager._instance = None

    def test_concurrent_reads(self, config_manager):
        """Test concurrent reads don't cause issues."""
        results = []
        errors = []

        def reader():
            try:
                for _ in range(100):
                    value = config_manager.get("counter", "value")
                    results.append(value)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 1000

    def test_concurrent_writes(self, config_manager, temp_config):
        """Test concurrent writes don't corrupt data."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(10):
                    config_manager.set("writes", f"thread{thread_id}_key{i}", f"value{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Flush and verify
        config_manager.flush()

        assert len(errors) == 0

        # Verify all writes succeeded
        writes_section = config_manager.get("writes")
        assert writes_section is not None
        # Should have 50 keys (5 threads * 10 keys each)
        assert len(writes_section) == 50


class TestConfigManagerBackwardCompatibility:
    """Test backward compatibility functions."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        """Create a temporary config file for testing."""
        config_file = tmp_path / "config.json"
        initial_config = {"compat_section": {"key": "value"}}
        config_file.write_text(json.dumps(initial_config, indent=2))
        return config_file

    def test_load_config_function(self, temp_config):
        """Test load_config backward compatibility function."""
        from server.config_manager import ConfigManager, load_config

        ConfigManager._instance = None

        with patch("server.config_manager.CONFIG_FILE", temp_config):
            config = load_config()
            assert "compat_section" in config
            assert config["compat_section"]["key"] == "value"
            ConfigManager._instance = None

    def test_get_section_config_function(self, temp_config):
        """Test get_section_config backward compatibility function."""
        from server.config_manager import ConfigManager, get_section_config

        ConfigManager._instance = None

        with patch("server.config_manager.CONFIG_FILE", temp_config):
            section = get_section_config("compat_section")
            assert section["key"] == "value"

            # Test default
            missing = get_section_config("missing", {"default": True})
            assert missing["default"] is True
            ConfigManager._instance = None
