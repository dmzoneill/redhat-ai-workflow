"""Tests for scripts/common/paths.py"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.common.paths import (
    CONFIG_DIR,
    MEMORY_DIR,
    PERSONAS_DIR,
    PROJECT_ROOT,
    SCRIPTS_DIR,
    SERVER_DIR,
    SERVICES_DIR,
    SKILLS_DIR,
    TOOL_MODULES_DIR,
    get_config_file,
    get_state_file,
    setup_path,
)


class TestProjectRoot:
    def test_project_root_is_absolute(self):
        assert PROJECT_ROOT.is_absolute()

    def test_project_root_is_resolved(self):
        # resolve() returns a path without ".." components
        assert ".." not in str(PROJECT_ROOT)

    def test_project_root_exists(self):
        assert PROJECT_ROOT.exists()


class TestDirectoryConstants:
    def test_scripts_dir(self):
        assert SCRIPTS_DIR == PROJECT_ROOT / "scripts"

    def test_server_dir(self):
        assert SERVER_DIR == PROJECT_ROOT / "server"

    def test_services_dir(self):
        assert SERVICES_DIR == PROJECT_ROOT / "services"

    def test_tool_modules_dir(self):
        assert TOOL_MODULES_DIR == PROJECT_ROOT / "tool_modules"

    def test_memory_dir(self):
        assert MEMORY_DIR == PROJECT_ROOT / "memory"

    def test_skills_dir(self):
        assert SKILLS_DIR == PROJECT_ROOT / "skills"

    def test_personas_dir(self):
        assert PERSONAS_DIR == PROJECT_ROOT / "personas"

    def test_config_dir(self):
        assert CONFIG_DIR == Path.home() / ".config" / "aa-workflow"


class TestSetupPath:
    def test_setup_path_adds_project_root(self):
        project_root_str = str(PROJECT_ROOT)
        # setup_path is called on import, so it's already in sys.path
        assert project_root_str in sys.path

    def test_setup_path_no_duplicates(self):
        project_root_str = str(PROJECT_ROOT)
        # Call setup_path again -- it should not add a duplicate
        original_count = sys.path.count(project_root_str)
        setup_path()
        assert sys.path.count(project_root_str) == original_count

    def test_setup_path_inserts_at_front_when_missing(self):
        project_root_str = str(PROJECT_ROOT)
        # Temporarily remove it, call setup_path, verify it's at index 0
        original_path = sys.path.copy()
        sys.path = [p for p in sys.path if p != project_root_str]
        try:
            setup_path()
            assert sys.path[0] == project_root_str
        finally:
            sys.path = original_path


class TestGetConfigFile:
    def test_returns_config_json_path(self):
        result = get_config_file()
        assert result == CONFIG_DIR / "config.json"
        assert result.name == "config.json"

    def test_returns_path_object(self):
        assert isinstance(get_config_file(), Path)


class TestGetStateFile:
    def test_returns_state_json_path(self):
        result = get_state_file()
        assert result == CONFIG_DIR / "state.json"
        assert result.name == "state.json"

    def test_returns_path_object(self):
        assert isinstance(get_state_file(), Path)
