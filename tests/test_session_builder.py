"""Tests for server/session_builder.py - Super Prompt Context Assembly."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
import yaml

from server.session_builder import SessionBuilder, build_auto_context, estimate_tokens

# ==================== estimate_tokens ====================


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # "hello" is 5 chars -> 5 // 4 = 1
        assert estimate_tokens("hello") == 1

    def test_longer_string(self):
        text = "a" * 100
        assert estimate_tokens(text) == 25

    def test_exact_multiple(self):
        text = "a" * 8
        assert estimate_tokens(text) == 2


# ==================== SessionBuilder.__init__ ====================


class TestSessionBuilderInit:
    @patch("server.session_builder.CONFIG_FILE")
    def test_init_no_config(self, mock_config_file):
        mock_config_file.exists.return_value = False
        sb = SessionBuilder()
        assert sb.context_sections == {}
        assert sb.token_counts == {}
        assert sb.config == {}

    @patch("server.session_builder.CONFIG_FILE")
    def test_init_with_valid_config(self, mock_config_file):
        mock_config_file.exists.return_value = True
        mock_config_file.read_text.return_value = '{"key": "val"}'
        sb = SessionBuilder()
        assert sb.config == {"key": "val"}

    @patch("server.session_builder.CONFIG_FILE")
    def test_init_with_bad_json(self, mock_config_file):
        mock_config_file.exists.return_value = True
        mock_config_file.read_text.return_value = "not-json"
        sb = SessionBuilder()
        assert sb.config == {}

    @patch("server.session_builder.CONFIG_FILE")
    def test_init_with_io_error(self, mock_config_file):
        mock_config_file.exists.return_value = True
        mock_config_file.read_text.side_effect = IOError("boom")
        sb = SessionBuilder()
        assert sb.config == {}


# ==================== add_persona ====================


class TestAddPersona:
    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.PERSONAS_DIR")
    def test_persona_not_found(self, mock_pdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        persona_file = MagicMock()
        persona_file.exists.return_value = False
        mock_pdir.__truediv__ = MagicMock(return_value=persona_file)
        assert sb.add_persona("missing") is False

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.PERSONAS_DIR")
    def test_persona_success(self, mock_pdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        persona_data = {
            "name": "Dev",
            "description": "A developer persona",
            "system_prompt": "You are a dev",
            "tools": ["git", "pytest"],
        }
        persona_file = MagicMock()
        persona_file.exists.return_value = True
        persona_file.read_text.return_value = yaml.dump(persona_data)
        mock_pdir.__truediv__ = MagicMock(return_value=persona_file)

        assert sb.add_persona("developer") is True
        assert "persona" in sb.context_sections
        assert "Dev" in sb.context_sections["persona"]
        assert "A developer persona" in sb.context_sections["persona"]
        assert "You are a dev" in sb.context_sections["persona"]
        assert "git" in sb.context_sections["persona"]
        assert sb.token_counts["persona"] > 0

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.PERSONAS_DIR")
    def test_persona_minimal(self, mock_pdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        persona_data = {"name": "Minimal"}
        persona_file = MagicMock()
        persona_file.exists.return_value = True
        persona_file.read_text.return_value = yaml.dump(persona_data)
        mock_pdir.__truediv__ = MagicMock(return_value=persona_file)

        assert sb.add_persona("minimal") is True
        assert "Minimal" in sb.context_sections["persona"]

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.PERSONAS_DIR")
    def test_persona_bad_yaml(self, mock_pdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        persona_file = MagicMock()
        persona_file.exists.return_value = True
        persona_file.read_text.side_effect = IOError("disk error")
        mock_pdir.__truediv__ = MagicMock(return_value=persona_file)

        assert sb.add_persona("broken") is False


# ==================== add_skill ====================


class TestAddSkill:
    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.SKILLS_DIR")
    def test_skill_not_found(self, mock_sdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        skill_file = MagicMock()
        skill_file.exists.return_value = False
        mock_sdir.__truediv__ = MagicMock(return_value=skill_file)
        assert sb.add_skill("missing") is False

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.SKILLS_DIR")
    def test_skill_success(self, mock_sdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        skill_data = {
            "name": "Start Work",
            "description": "Begin work on an issue",
            "inputs": [
                {
                    "name": "issue_key",
                    "required": True,
                    "description": "Jira issue key",
                },
                {"name": "branch", "description": "Branch name"},
            ],
            "steps": [
                {"name": "Fetch issue", "tool": "jira_get"},
                {"name": "Create branch"},
            ],
        }
        skill_file = MagicMock()
        skill_file.exists.return_value = True
        skill_file.read_text.return_value = yaml.dump(skill_data)
        mock_sdir.__truediv__ = MagicMock(return_value=skill_file)

        assert sb.add_skill("start_work") is True
        section = sb.context_sections["skills"]
        assert "Start Work" in section
        assert "Begin work on an issue" in section
        assert "issue_key" in section
        assert "(required)" in section
        assert "Fetch issue" in section
        assert "jira_get" in section

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.SKILLS_DIR")
    def test_multiple_skills_appended(self, mock_sdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()

        # First skill
        skill1 = {"name": "Skill1"}
        skill2 = {"name": "Skill2"}
        file1 = MagicMock()
        file1.exists.return_value = True
        file1.read_text.return_value = yaml.dump(skill1)
        file2 = MagicMock()
        file2.exists.return_value = True
        file2.read_text.return_value = yaml.dump(skill2)

        mock_sdir.__truediv__ = MagicMock(side_effect=[file1, file2])

        sb.add_skill("s1")
        sb.add_skill("s2")
        assert "Skill1" in sb.context_sections["skills"]
        assert "Skill2" in sb.context_sections["skills"]

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.SKILLS_DIR")
    def test_skill_bad_yaml(self, mock_sdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        skill_file = MagicMock()
        skill_file.exists.return_value = True
        skill_file.read_text.side_effect = IOError("boom")
        mock_sdir.__truediv__ = MagicMock(return_value=skill_file)
        assert sb.add_skill("broken") is False


# ==================== add_memory ====================


class TestAddMemory:
    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.MEMORY_DIR")
    def test_memory_yaml(self, mock_mdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()

        yaml_file = MagicMock()
        yaml_file.exists.return_value = True
        yaml_file.read_text.return_value = yaml.dump({"active_issues": ["AAP-123"]})

        json_file = MagicMock()
        json_file.exists.return_value = False

        def truediv_side_effect(name):
            if name.endswith(".yaml"):
                return yaml_file
            return json_file

        mock_mdir.__truediv__ = MagicMock(side_effect=truediv_side_effect)

        assert sb.add_memory("state/current_work") is True
        assert "memory" in sb.context_sections
        assert "state/current_work" in sb.context_sections["memory"]

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.MEMORY_DIR")
    def test_memory_json(self, mock_mdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()

        yaml_file = MagicMock()
        yaml_file.exists.return_value = False

        json_file = MagicMock()
        json_file.exists.return_value = True
        json_file.read_text.return_value = json.dumps({"key": "val"})

        def truediv_side_effect(name):
            if name.endswith(".yaml"):
                return yaml_file
            return json_file

        mock_mdir.__truediv__ = MagicMock(side_effect=truediv_side_effect)

        assert sb.add_memory("state/work") is True
        assert "memory" in sb.context_sections

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.MEMORY_DIR")
    def test_memory_not_found(self, mock_mdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()

        missing = MagicMock()
        missing.exists.return_value = False
        mock_mdir.__truediv__ = MagicMock(return_value=missing)

        assert sb.add_memory("nonexistent") is False

    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.MEMORY_DIR")
    def test_memory_multiple_appended(self, mock_mdir, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()

        # Each add_memory call tries .yaml first, then .json
        # We want both to succeed via .yaml
        f1 = MagicMock()
        f1.exists.return_value = True
        f1.read_text.return_value = yaml.dump({"a": 1})

        f2 = MagicMock()
        f2.exists.return_value = True
        f2.read_text.return_value = yaml.dump({"b": 2})

        # Call sequence: first.yaml, second.yaml
        mock_mdir.__truediv__ = MagicMock(side_effect=[f1, f2])

        sb.add_memory("first")
        sb.add_memory("second")
        assert sb.context_sections["memory"].count("## Memory:") == 2


# ==================== add_jira_issue ====================


class TestAddJiraIssue:
    @patch("server.session_builder.CONFIG_FILE")
    def test_jira_placeholder(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        assert sb.add_jira_issue("AAP-12345") is True
        assert "AAP-12345" in sb.context_sections["jira"]
        assert "will be fetched" in sb.context_sections["jira"]

    @patch("server.session_builder.CONFIG_FILE")
    def test_jira_with_data(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        data = {
            "summary": "Fix bug",
            "description": "Details here",
            "status": "In Progress",
            "priority": "High",
            "assignee": "alice",
        }
        assert sb.add_jira_issue("AAP-99", issue_data=data) is True
        section = sb.context_sections["jira"]
        assert "Fix bug" in section
        assert "Details here" in section
        assert "In Progress" in section
        assert "High" in section
        assert "alice" in section

    @patch("server.session_builder.CONFIG_FILE")
    def test_jira_minimal_data(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        data = {"summary": "Minimal"}
        assert sb.add_jira_issue("AAP-1", issue_data=data) is True
        section = sb.context_sections["jira"]
        assert "Minimal" in section


# ==================== add_slack_results ====================


class TestAddSlackResults:
    @patch("server.session_builder.CONFIG_FILE")
    def test_no_results(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        assert sb.add_slack_results("billing", []) is True
        assert "No matching messages" in sb.context_sections["slack"]

    @patch("server.session_builder.CONFIG_FILE")
    def test_with_results(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        results = [
            {
                "user": "alice",
                "channel": "general",
                "timestamp": "10am",
                "text": "hello",
            },
            {"user": "bob", "channel": "dev", "timestamp": "11am", "text": "world"},
        ]
        assert sb.add_slack_results("search query", results) is True
        section = sb.context_sections["slack"]
        assert "alice" in section
        assert "hello" in section
        assert "bob" in section

    @patch("server.session_builder.CONFIG_FILE")
    def test_limits_to_10(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        results = [{"user": f"u{i}", "text": f"msg{i}"} for i in range(15)]
        sb.add_slack_results("q", results)
        # Only first 10 should appear
        assert "u9" in sb.context_sections["slack"]
        assert "u10" not in sb.context_sections["slack"]


# ==================== add_code_results ====================


class TestAddCodeResults:
    @patch("server.session_builder.CONFIG_FILE")
    def test_no_results(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        assert sb.add_code_results("billing", []) is True
        assert "No matching code" in sb.context_sections["code"]

    @patch("server.session_builder.CONFIG_FILE")
    def test_with_results(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        results = [
            {
                "file": "billing.py",
                "line": 42,
                "snippet": "def calc():",
                "relevance": 0.95,
            },
        ]
        assert sb.add_code_results("billing calc", results) is True
        section = sb.context_sections["code"]
        assert "billing.py" in section
        assert "line 42" in section
        assert "def calc():" in section
        assert "0.95" in section

    @patch("server.session_builder.CONFIG_FILE")
    def test_limits_to_5(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        results = [{"file": f"f{i}.py"} for i in range(10)]
        sb.add_code_results("q", results)
        assert "f4.py" in sb.context_sections["code"]
        assert "f5.py" not in sb.context_sections["code"]


# ==================== add_meeting_context ====================


class TestAddMeetingContext:
    @patch("server.session_builder.CONFIG_FILE")
    def test_meeting(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        assert (
            sb.add_meeting_context(
                "standup-2024", ["discussed billing", "assigned AAP-123"]
            )
            is True
        )
        section = sb.context_sections["meeting"]
        assert "standup-2024" in section
        assert "discussed billing" in section
        assert "assigned AAP-123" in section


# ==================== add_custom_context ====================


class TestAddCustomContext:
    @patch("server.session_builder.CONFIG_FILE")
    def test_custom_context(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        assert sb.add_custom_context("My Notes", "some content here") is True
        assert "my_notes" in sb.context_sections
        assert "My Notes" in sb.context_sections["my_notes"]
        assert "some content here" in sb.context_sections["my_notes"]


# ==================== build ====================


class TestBuild:
    @patch("server.session_builder.CONFIG_FILE")
    def test_build_empty(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        prompt = sb.build()
        assert "# Session Context" in prompt
        assert "Generated:" in prompt

    @patch("server.session_builder.CONFIG_FILE")
    def test_build_ordering(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.context_sections["code"] = "## Code content\n"
        sb.context_sections["persona"] = "## Persona content\n"
        sb.context_sections["jira"] = "## Jira content\n"

        prompt = sb.build()
        # persona should come before jira, jira before code
        persona_idx = prompt.index("Persona content")
        jira_idx = prompt.index("Jira content")
        code_idx = prompt.index("Code content")
        assert persona_idx < jira_idx < code_idx

    @patch("server.session_builder.CONFIG_FILE")
    def test_build_includes_custom_sections(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.context_sections["custom_stuff"] = "## Custom stuff\n"
        prompt = sb.build()
        assert "Custom stuff" in prompt


# ==================== get_token_summary ====================


class TestGetTokenSummary:
    @patch("server.session_builder.CONFIG_FILE")
    def test_token_summary_empty(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        summary = sb.get_token_summary()
        assert summary["total"] == 0
        assert summary["warning"] is False
        assert summary["danger"] is False

    @patch("server.session_builder.CONFIG_FILE")
    def test_token_summary_with_counts(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.token_counts["persona"] = 1000
        sb.token_counts["jira"] = 2000
        summary = sb.get_token_summary()
        assert summary["total"] == 3000
        assert summary["sections"] == {"persona": 1000, "jira": 2000}

    @patch("server.session_builder.CONFIG_FILE")
    def test_token_summary_warning(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.token_counts["big"] = 60000
        summary = sb.get_token_summary()
        assert summary["warning"] is True
        assert summary["danger"] is False

    @patch("server.session_builder.CONFIG_FILE")
    def test_token_summary_danger(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.token_counts["huge"] = 150000
        summary = sb.get_token_summary()
        assert summary["warning"] is True
        assert summary["danger"] is True


# ==================== preview ====================


class TestPreview:
    @patch("server.session_builder.CONFIG_FILE")
    def test_preview(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.context_sections["jira"] = "## Jira\n"
        sb.token_counts["jira"] = 10
        p = sb.preview()
        assert "prompt" in p
        assert "tokens" in p
        assert "sections" in p
        assert "jira" in p["sections"]


# ==================== export_template ====================


class TestExportTemplate:
    @patch("server.session_builder.CONFIG_FILE")
    def test_export(self, mock_cfg):
        mock_cfg.exists.return_value = False
        sb = SessionBuilder()
        sb.context_sections["jira"] = "x"
        sb.token_counts["jira"] = 10
        t = sb.export_template("my-template", "A test template")
        assert t["name"] == "my-template"
        assert t["description"] == "A test template"
        assert "created_at" in t
        assert t["sections"] == ["jira"]
        assert t["token_estimate"] == 10


# ==================== build_auto_context ====================


class TestBuildAutoContext:
    @patch("server.session_builder.CONFIG_FILE")
    @patch("server.session_builder.MEMORY_DIR")
    def test_auto_context(self, mock_mdir, mock_cfg):
        mock_cfg.exists.return_value = False
        # Memory files don't exist
        missing = MagicMock()
        missing.exists.return_value = False
        mock_mdir.__truediv__ = MagicMock(return_value=missing)

        builder = build_auto_context("AAP-999")
        assert "jira" in builder.context_sections
        assert "AAP-999" in builder.context_sections["jira"]
        assert "slack" in builder.context_sections
        assert "code" in builder.context_sections
