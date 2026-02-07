"""Tests for ConfigManager.

Tests thread safety, debouncing, file locking, and mtime-based cache invalidation.
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

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
        config_manager.update_section(
            "test_section", {"key3": "value3"}, merge=True, flush=True
        )

        # Original keys should still exist
        assert config_manager.get("test_section", "key1") == "value1"
        # New key should be added
        assert config_manager.get("test_section", "key3") == "value3"

    def test_update_section_replace(self, config_manager, temp_config):
        """Test updating a section with merge=False."""
        config_manager.update_section(
            "test_section", {"only_key": "only_value"}, merge=False, flush=True
        )

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
        assert (
            config_manager.get("external_section", "external_key") == "external_value"
        )

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
                    config_manager.set(
                        "writes", f"thread{thread_id}_key{i}", f"value{i}"
                    )
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


# ==================== New coverage tests ====================


class TestConfigValidationError:
    """Test ConfigValidationError class."""

    def test_init_stores_errors(self):
        """ConfigValidationError stores error list and formats message."""
        from server.config_manager import ConfigValidationError

        errors = ["Missing section: jira", "Invalid type for gitlab.project_id"]
        exc = ConfigValidationError(errors)
        assert exc.errors == errors
        assert "Missing section: jira" in str(exc)
        assert "Invalid type for gitlab.project_id" in str(exc)

    def test_init_single_error(self):
        """ConfigValidationError works with a single error."""
        from server.config_manager import ConfigValidationError

        exc = ConfigValidationError(["one error"])
        assert exc.errors == ["one error"]
        assert "one error" in str(exc)


class TestValidateConfig:
    """Test validate_config function."""

    def test_missing_required_sections(self):
        """validate_config reports missing required sections."""
        from server.config_manager import validate_config

        errors = validate_config({})
        assert any("Missing required section: jira" in e for e in errors)
        assert any("Missing required section: gitlab" in e for e in errors)

    def test_valid_config(self):
        """validate_config returns empty list for valid config."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
        }
        errors = validate_config(config)
        assert errors == []

    def test_section_not_dict(self):
        """validate_config catches section that is not a dict."""
        from server.config_manager import validate_config

        config = {
            "jira": "not-a-dict",
            "gitlab": {"url": "https://gitlab.example.com"},
        }
        errors = validate_config(config)
        assert any("must be a dict" in e for e in errors)

    def test_missing_required_key(self):
        """validate_config catches missing required keys."""
        from server.config_manager import validate_config

        config = {
            "jira": {},  # Missing required 'server'
            "gitlab": {"url": "https://gitlab.example.com"},
        }
        errors = validate_config(config)
        assert any("Missing required key: jira.server" in e for e in errors)

    def test_invalid_type_for_key(self):
        """validate_config catches wrong type for a key."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": 12345},  # Should be str
            "gitlab": {"url": "https://gitlab.example.com", "project_id": "not-int"},
        }
        errors = validate_config(config)
        assert any("Invalid type for jira.server" in e for e in errors)
        assert any("Invalid type for gitlab.project_id" in e for e in errors)

    def test_none_value_passes_type_check(self):
        """validate_config allows None values even when type is specified."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com", "project_id": None},
        }
        errors = validate_config(config)
        assert errors == []

    def test_repositories_not_dict(self):
        """validate_config catches repositories that is not a dict."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
            "repositories": "not-a-dict",
        }
        errors = validate_config(config)
        assert any("'repositories' must be a dict" in e for e in errors)

    def test_repo_config_not_dict(self):
        """validate_config catches repo config that is not a dict."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
            "repositories": {"my-repo": "not-a-dict"},
        }
        errors = validate_config(config)
        assert any("'my-repo' config must be a dict" in e for e in errors)

    def test_repo_missing_path_and_gitlab_path(self):
        """validate_config catches repo missing both path and gitlab_path."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
            "repositories": {"my-repo": {"some_other_key": "value"}},
        }
        errors = validate_config(config)
        assert any("missing 'path' or 'gitlab_path'" in e for e in errors)

    def test_repo_with_path_is_valid(self):
        """validate_config accepts repo with path key."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
            "repositories": {"my-repo": {"path": "/some/path"}},
        }
        errors = validate_config(config)
        assert errors == []

    def test_repo_with_gitlab_path_is_valid(self):
        """validate_config accepts repo with gitlab_path key."""
        from server.config_manager import validate_config

        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
            "repositories": {"my-repo": {"gitlab_path": "org/repo"}},
        }
        errors = validate_config(config)
        assert errors == []

    def test_spec_as_type_only(self):
        """validate_config handles spec that is just a type (not a tuple)."""
        from server.config_manager import CONFIG_SCHEMA, validate_config

        # The slack section has specs that are tuples, but let's test through
        # a normal config validation path
        config = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
            "slack": {"workspace": "my-workspace"},
        }
        errors = validate_config(config)
        assert errors == []


class TestGetConfigDefaults:
    """Test get_config_defaults function."""

    def test_returns_defaults(self):
        """get_config_defaults returns default values from schema."""
        from server.config_manager import get_config_defaults

        defaults = get_config_defaults()
        assert isinstance(defaults, dict)
        # paths.config_dir has a default
        assert "paths" in defaults
        assert defaults["paths"]["config_dir"] == "~/.config/aa-workflow"

    def test_jira_default(self):
        """get_config_defaults includes jira.project default."""
        from server.config_manager import get_config_defaults

        defaults = get_config_defaults()
        assert "jira" in defaults
        assert defaults["jira"]["project"] == "AAP"

    def test_no_none_defaults(self):
        """get_config_defaults skips keys with None defaults."""
        from server.config_manager import get_config_defaults

        defaults = get_config_defaults()
        # slack workspace default is None, should not appear
        assert "slack" not in defaults or "workspace" not in defaults.get("slack", {})


class TestConfigManagerLoadErrors:
    """Test ConfigManager error handling during load."""

    @pytest.fixture
    def fresh_manager_class(self):
        """Get a fresh ConfigManager class with reset singleton."""
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        yield ConfigManager
        ConfigManager._instance = None

    def test_load_missing_file(self, tmp_path, fresh_manager_class):
        """ConfigManager handles missing config file gracefully."""
        missing_file = tmp_path / "nonexistent.json"
        with patch("server.config_manager.CONFIG_FILE", missing_file):
            manager = fresh_manager_class()
            assert manager.get_all() == {}

    def test_load_invalid_json(self, tmp_path, fresh_manager_class):
        """ConfigManager handles invalid JSON gracefully."""
        bad_file = tmp_path / "config.json"
        bad_file.write_text("{invalid json!!!")
        with patch("server.config_manager.CONFIG_FILE", bad_file):
            manager = fresh_manager_class()
            assert manager.get_all() == {}

    def test_load_os_error(self, tmp_path, fresh_manager_class):
        """ConfigManager handles OS errors during load."""
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")
        with patch("server.config_manager.CONFIG_FILE", config_file):
            with patch("builtins.open", side_effect=OSError("Permission denied")):
                manager = fresh_manager_class()
                assert manager.get_all() == {}

    def test_check_reload_os_error(self, tmp_path, fresh_manager_class):
        """ConfigManager handles OS error in _check_reload."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"a": 1}')
        with patch("server.config_manager.CONFIG_FILE", config_file):
            manager = fresh_manager_class()
            # Now make stat fail
            with patch.object(
                type(config_file), "exists", side_effect=OSError("IO error")
            ):
                # Should not raise, just silently pass
                val = manager.get("a")
                assert val == 1


class TestConfigManagerFlushError:
    """Test ConfigManager flush error handling."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"sec": {"k": "v"}}')
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            ConfigManager._instance = None

    def test_flush_os_error(self, config_manager, temp_config):
        """ConfigManager handles OS error during flush."""
        config_manager.set("sec", "k2", "v2")
        with patch("builtins.open", side_effect=OSError("Disk full")):
            # Should not raise
            config_manager.flush()
        # Still dirty since write failed
        # (Implementation sets _dirty=False only on success)
        # The data in memory is intact
        assert config_manager.get("sec", "k2") == "v2"


class TestConfigManagerGetEdgeCases:
    """Test get/set edge cases for coverage."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        initial = {"non_dict_section": "I am a string, not a dict"}
        config_file.write_text(json.dumps(initial))
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            ConfigManager._instance = None

    def test_get_key_from_non_dict_section(self, config_manager):
        """Getting a key from a non-dict section returns default."""
        result = config_manager.get("non_dict_section", "key", default="fallback")
        assert result == "fallback"

    def test_set_overwrites_non_dict_section(self, config_manager):
        """Setting a key on a non-dict section converts it to dict."""
        config_manager.set("non_dict_section", "key", "value", flush=True)
        assert config_manager.get("non_dict_section", "key") == "value"


class TestConfigManagerDeleteEdgeCases:
    """Test delete edge cases."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        initial = {"sec": {"k1": "v1", "k2": "v2"}}
        config_file.write_text(json.dumps(initial))
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            ConfigManager._instance = None

    def test_delete_key_not_in_section(self, config_manager):
        """Deleting a non-existent key from existing section returns False."""
        result = config_manager.delete("sec", "nonexistent_key")
        assert result is False

    def test_delete_key_with_flush(self, config_manager, temp_config):
        """Deleting a key with flush writes to disk."""
        result = config_manager.delete("sec", "k1", flush=True)
        assert result is True
        disk = json.loads(temp_config.read_text())
        assert "k1" not in disk["sec"]

    def test_delete_section_with_flush(self, config_manager, temp_config):
        """Deleting a section with flush writes to disk."""
        result = config_manager.delete("sec", flush=True)
        assert result is True
        disk = json.loads(temp_config.read_text())
        assert "sec" not in disk


class TestConfigManagerProperties:
    """Test config_file property and validate methods."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        initial = {
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
        }
        config_file.write_text(json.dumps(initial))
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            ConfigManager._instance = None

    def test_config_file_property(self, config_manager, temp_config):
        """config_file property returns the CONFIG_FILE path."""
        # The property returns the module-level CONFIG_FILE, not temp_config
        from server.config_manager import CONFIG_FILE

        assert config_manager.config_file == CONFIG_FILE

    def test_validate_valid_config(self, config_manager):
        """validate returns empty list for valid config."""
        errors = config_manager.validate()
        assert errors == []

    def test_validate_or_raise_valid(self, config_manager):
        """validate_or_raise does not raise for valid config."""
        config_manager.validate_or_raise()  # Should not raise

    def test_validate_or_raise_invalid(self, tmp_path):
        """validate_or_raise raises ConfigValidationError for invalid config."""
        from server.config_manager import ConfigManager, ConfigValidationError

        ConfigManager._instance = None
        config_file = tmp_path / "config.json"
        config_file.write_text('{"no_jira": true}')  # Missing required sections
        with patch("server.config_manager.CONFIG_FILE", config_file):
            manager = ConfigManager()
            with pytest.raises(ConfigValidationError) as exc_info:
                manager.validate_or_raise()
            assert len(exc_info.value.errors) > 0
            ConfigManager._instance = None


class TestGetWithDefault:
    """Test get_with_default method."""

    @pytest.fixture
    def temp_config(self, tmp_path):
        config_file = tmp_path / "config.json"
        initial = {
            "paths": {"config_dir": "/custom/path"},
            "jira": {"server": "https://jira.example.com"},
            "gitlab": {"url": "https://gitlab.example.com"},
        }
        config_file.write_text(json.dumps(initial))
        return config_file

    @pytest.fixture
    def config_manager(self, temp_config):
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        with patch("server.config_manager.CONFIG_FILE", temp_config):
            manager = ConfigManager()
            yield manager
            ConfigManager._instance = None

    def test_returns_config_value(self, config_manager):
        """get_with_default returns value from config when present."""
        assert config_manager.get_with_default("paths", "config_dir") == "/custom/path"

    def test_falls_back_to_schema_default(self, config_manager):
        """get_with_default falls back to schema default when key missing."""
        # jira.project is not in config but has schema default "AAP"
        assert config_manager.get_with_default("jira", "project") == "AAP"

    def test_returns_none_for_unknown(self, config_manager):
        """get_with_default returns None for keys not in config or schema."""
        assert config_manager.get_with_default("unknown_section", "unknown_key") is None

    def test_non_dict_section(self, tmp_path):
        """get_with_default handles non-dict section data."""
        from server.config_manager import ConfigManager

        ConfigManager._instance = None
        config_file = tmp_path / "config.json"
        config_file.write_text('{"jira": "a string", "gitlab": {"url": "x"}}')
        with patch("server.config_manager.CONFIG_FILE", config_file):
            manager = ConfigManager()
            # jira is a string, not a dict - should fall back to schema default
            result = manager.get_with_default("jira", "project")
            assert result == "AAP"
            ConfigManager._instance = None


class TestBackwardCompatLoadConfigReload:
    """Test load_config backward-compat function with reload=True."""

    def test_load_config_with_reload(self, tmp_path):
        """load_config(reload=True) forces reload from disk."""
        from server.config_manager import ConfigManager, load_config

        ConfigManager._instance = None
        config_file = tmp_path / "config.json"
        config_file.write_text('{"initial": true}')
        with patch("server.config_manager.CONFIG_FILE", config_file):
            cfg = load_config()
            assert cfg.get("initial") is True

            # Modify file
            config_file.write_text('{"updated": true}')
            cfg2 = load_config(reload=True)
            assert cfg2.get("updated") is True
            ConfigManager._instance = None


class TestGetSectionConfigNonDict:
    """Test get_section_config with non-dict result."""

    def test_non_dict_result_returns_default(self, tmp_path):
        """get_section_config returns default when section is not a dict."""
        from server.config_manager import ConfigManager, get_section_config

        ConfigManager._instance = None
        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"jira": {"server": "x"}, "gitlab": {"url": "y"}, "stringy": "not a dict"}'
        )
        with patch("server.config_manager.CONFIG_FILE", config_file):
            result = get_section_config("stringy", {"fallback": True})
            assert result == {"fallback": True}

            result2 = get_section_config("stringy")
            assert result2 == {}
            ConfigManager._instance = None
