"""Tests for scripts/common/slack_utils.py"""

from unittest.mock import patch

import pytest

from scripts.common.slack_utils import (
    build_alert_notification,
    build_mr_notification,
    build_team_mention,
)


class TestBuildTeamMention:
    def test_with_group_id_and_handle(self):
        result = build_team_mention(group_id="S12345", group_handle="my-team")
        assert result == "<!subteam^S12345|@my-team>"

    def test_without_group_id_falls_back_to_handle(self):
        result = build_team_mention(group_id="", group_handle="my-team")
        assert result == "@my-team"

    def test_none_group_id_uses_config(self):
        with (
            patch("scripts.common.slack_utils.get_team_group_id", return_value="SCFG"),
            patch(
                "scripts.common.slack_utils.get_team_group_handle",
                return_value="cfg-team",
            ),
        ):
            result = build_team_mention()
            assert result == "<!subteam^SCFG|@cfg-team>"

    def test_none_group_id_empty_config(self):
        with (
            patch("scripts.common.slack_utils.get_team_group_id", return_value=""),
            patch(
                "scripts.common.slack_utils.get_team_group_handle",
                return_value="fallback",
            ),
        ):
            result = build_team_mention()
            assert result == "@fallback"


class TestBuildMrNotification:
    @patch("scripts.common.slack_utils.get_jira_url", return_value="https://jira.test")
    @patch("scripts.common.slack_utils.get_team_group_id", return_value="")
    @patch("scripts.common.slack_utils.get_team_group_handle", return_value="team")
    def test_basic_notification(self, mock_handle, mock_gid, mock_jira):
        result = build_mr_notification(
            mr_url="https://gitlab/mr/1",
            mr_id=1,
            mr_title="Fix bug",
        )
        assert "@team" in result
        assert "Fix bug" in result
        assert "https://gitlab/mr/1" in result

    @patch("scripts.common.slack_utils.get_jira_url", return_value="https://jira.test")
    @patch("scripts.common.slack_utils.get_team_group_id", return_value="")
    @patch("scripts.common.slack_utils.get_team_group_handle", return_value="team")
    def test_with_issue_key(self, mock_handle, mock_gid, mock_jira):
        result = build_mr_notification(
            mr_url="https://gitlab/mr/2",
            mr_id=2,
            mr_title="Feature",
            issue_key="AAP-123",
        )
        assert "AAP-123" in result
        assert "https://jira.test/browse/AAP-123" in result

    @patch("scripts.common.slack_utils.get_jira_url", return_value="https://jira.test")
    @patch("scripts.common.slack_utils.get_team_group_id", return_value="")
    @patch("scripts.common.slack_utils.get_team_group_handle", return_value="team")
    def test_title_truncation(self, mock_handle, mock_gid, mock_jira):
        long_title = "A" * 100
        result = build_mr_notification(
            mr_url="https://gitlab/mr/3",
            mr_id=3,
            mr_title=long_title,
        )
        # Title should be truncated to 60 chars
        assert "A" * 60 in result
        assert "A" * 61 not in result

    def test_explicit_jira_url(self):
        result = build_mr_notification(
            mr_url="https://gitlab/mr/4",
            mr_id=4,
            mr_title="Test",
            issue_key="AAP-999",
            jira_url="https://custom-jira.example.com",
            team_group_id="",
            team_group_handle="myteam",
        )
        assert "https://custom-jira.example.com/browse/AAP-999" in result

    def test_custom_header(self):
        result = build_mr_notification(
            mr_url="https://gitlab/mr/5",
            mr_id=5,
            mr_title="Test",
            team_group_id="",
            team_group_handle="t",
            header="CUSTOM HEADER",
        )
        assert "CUSTOM HEADER" in result

    def test_with_group_id(self):
        result = build_mr_notification(
            mr_url="https://gitlab/mr/6",
            mr_id=6,
            mr_title="Test",
            team_group_id="S999",
            team_group_handle="grp",
        )
        assert "<!subteam^S999|@grp>" in result


class TestBuildAlertNotification:
    def test_critical_alert(self):
        result = build_alert_notification(
            alert_name="HighCPU",
            environment="prod",
            severity="critical",
            team_group_id="",
            team_group_handle="ops",
        )
        assert "HighCPU" in result
        assert "`prod`" in result
        assert "`critical`" in result

    def test_warning_alert(self):
        result = build_alert_notification(
            alert_name="DiskUsage",
            environment="stage",
            severity="warning",
            team_group_id="",
            team_group_handle="ops",
        )
        assert "DiskUsage" in result
        assert "`stage`" in result
        assert "`warning`" in result

    def test_info_alert(self):
        result = build_alert_notification(
            alert_name="Deploy",
            environment="stage",
            severity="info",
            team_group_id="",
            team_group_handle="ops",
        )
        assert "Deploy" in result

    def test_with_description(self):
        result = build_alert_notification(
            alert_name="Test",
            environment="stage",
            description="Disk usage at 90%",
            team_group_id="",
            team_group_handle="ops",
        )
        assert "Disk usage at 90%" in result

    def test_description_truncation(self):
        long_desc = "X" * 200
        result = build_alert_notification(
            alert_name="Test",
            environment="stage",
            description=long_desc,
            team_group_id="",
            team_group_handle="ops",
        )
        # Description truncated to 100
        assert "X" * 100 in result
        assert "X" * 101 not in result

    def test_no_description(self):
        result = build_alert_notification(
            alert_name="Test",
            environment="stage",
            description="",
            team_group_id="",
            team_group_handle="ops",
        )
        lines = result.strip().split("\n")
        # Should not have a description line
        assert not any("X" in line for line in lines)

    def test_team_mention_in_alert(self):
        result = build_alert_notification(
            alert_name="Test",
            environment="stage",
            team_group_id="SABC",
            team_group_handle="myteam",
        )
        assert "<!subteam^SABC|@myteam>" in result
