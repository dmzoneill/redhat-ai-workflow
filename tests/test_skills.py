"""Tests for skill YAML definitions."""

import pytest
import yaml


class TestSkillFiles:
    """Tests for skill YAML file structure."""

    def get_skill_files(self, skills_dir):
        """Get all skill YAML files."""
        return list(skills_dir.glob("*.yaml"))

    def test_skills_directory_exists(self, skills_dir):
        """Skills directory should exist."""
        assert skills_dir.exists()

    def test_skills_exist(self, skills_dir):
        """Should have at least one skill defined."""
        skills = self.get_skill_files(skills_dir)
        assert len(skills) > 0, "No skill files found"

    def test_all_skills_valid_yaml(self, skills_dir):
        """All skill files should be valid YAML."""
        for skill_file in self.get_skill_files(skills_dir):
            content = skill_file.read_text()
            try:
                data = yaml.safe_load(content)
                assert data is not None, f"{skill_file.name} is empty"
            except yaml.YAMLError as e:
                pytest.fail(f"{skill_file.name} has invalid YAML: {e}")

    def test_skills_have_required_fields(self, skills_dir):
        """Skills should have required fields: name, description, steps."""
        required = ["name", "description", "steps"]
        for skill_file in self.get_skill_files(skills_dir):
            content = skill_file.read_text()
            data = yaml.safe_load(content)
            for field in required:
                assert field in data, f"{skill_file.name} missing '{field}'"

    def test_skills_steps_not_empty(self, skills_dir):
        """Skills should have at least one step."""
        for skill_file in self.get_skill_files(skills_dir):
            content = skill_file.read_text()
            data = yaml.safe_load(content)
            steps = data.get("steps", [])
            assert len(steps) > 0, f"{skill_file.name} has no steps"

    def test_skill_steps_have_name_or_id(self, skills_dir):
        """Each step should have an id or name."""
        for skill_file in self.get_skill_files(skills_dir):
            content = skill_file.read_text()
            data = yaml.safe_load(content)
            for i, step in enumerate(data.get("steps", [])):
                has_identifier = "id" in step or "name" in step
                assert has_identifier, f"{skill_file.name} step {i} missing 'id' or 'name'"


class TestCoreSkills:
    """Tests for specific important skills."""

    def test_coffee_skill_exists(self, skills_dir):
        """The coffee skill should exist."""
        coffee = skills_dir / "coffee.yaml"
        assert coffee.exists(), "coffee.yaml not found"

    def test_start_work_skill_exists(self, skills_dir):
        """The start_work skill should exist."""
        start_work = skills_dir / "start_work.yaml"
        assert start_work.exists(), "start_work.yaml not found"

    def test_create_mr_skill_exists(self, skills_dir):
        """The create_mr skill should exist."""
        create_mr = skills_dir / "create_mr.yaml"
        assert create_mr.exists(), "create_mr.yaml not found"
