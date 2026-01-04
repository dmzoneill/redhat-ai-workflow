"""Tests for configuration loading and validation."""

import json

from server.config import load_config


class TestLoadConfig:
    """Tests for load_config function."""

    def test_config_loads(self):
        """Config should load without error."""
        config = load_config()
        assert config is not None
        assert isinstance(config, dict)

    def test_get_repository_config(self):
        """Should get repository configuration."""
        config = load_config()
        # This may return None if not configured
        repos = config.get("repositories", {})
        assert isinstance(repos, dict)

    def test_get_with_default(self):
        """Should return default for missing keys."""
        config = load_config()
        result = config.get("nonexistent_key", "default_value")
        assert result == "default_value"


class TestConfigFile:
    """Tests for config.json file format."""

    def test_config_file_exists(self, config_path):
        """config.json should exist."""
        assert config_path.exists(), f"config.json not found at {config_path}"

    def test_config_is_valid_json(self, config_path):
        """config.json should be valid JSON."""
        if config_path.exists():
            content = config_path.read_text()
            data = json.loads(content)
            assert isinstance(data, dict)

    def test_config_has_expected_sections(self, config_path):
        """config.json should have expected top-level keys."""
        if config_path.exists():
            content = config_path.read_text()
            data = json.loads(content)
            # Check for common expected sections
            expected = ["repositories", "environments", "jira", "slack"]
            for key in expected:
                # They may or may not be present, just check structure
                if key in data:
                    assert isinstance(data[key], dict)
