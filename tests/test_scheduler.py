"""Tests for tool_modules/aa_workflow/src/scheduler.py - Cron-based task scheduling."""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

# We need to mock heavy imports before importing the module
with (
    patch("server.config_manager.config") as _mock_cm,
    patch("server.state_manager.state") as _mock_sm,
):
    _mock_cm.get_all.return_value = {"schedules": {}}
    _mock_sm.is_service_enabled.return_value = False
    _mock_sm.is_job_enabled.return_value = True

    from tool_modules.aa_workflow.src.scheduler import (
        DEFAULT_RETRY_CONFIG,
        CronScheduler,
        JobExecutionLog,
        RetryConfig,
        SchedulerConfig,
        get_scheduler,
        init_scheduler,
        start_scheduler,
        stop_scheduler,
    )


# ==================== RetryConfig ====================


class TestRetryConfig:
    def test_defaults(self):
        rc = RetryConfig()
        assert rc.enabled is True
        assert rc.max_attempts == 2
        assert rc.backoff == "exponential"
        assert rc.initial_delay_seconds == 30
        assert rc.max_delay_seconds == 300
        assert "auth" in rc.retry_on

    def test_from_config_disabled(self):
        rc = RetryConfig.from_config({"retry": False})
        assert rc.enabled is False

    def test_from_config_default(self):
        rc = RetryConfig.from_config({})
        assert rc.enabled is True
        assert rc.max_attempts == 2

    def test_from_config_custom_dict(self):
        rc = RetryConfig.from_config(
            {"retry": {"max_attempts": 5, "backoff": "linear"}},
            DEFAULT_RETRY_CONFIG,
        )
        assert rc.max_attempts == 5
        assert rc.backoff == "linear"

    def test_from_config_with_default_config(self):
        defaults = {
            "max_attempts": 3,
            "backoff": "linear",
            "initial_delay_seconds": 10,
            "max_delay_seconds": 60,
            "retry_on": ["timeout"],
        }
        rc = RetryConfig.from_config({}, defaults)
        assert rc.max_attempts == 3
        assert rc.backoff == "linear"
        assert rc.retry_on == ["timeout"]

    def test_calculate_delay_exponential(self):
        rc = RetryConfig(
            backoff="exponential", initial_delay_seconds=10, max_delay_seconds=300
        )
        assert rc.calculate_delay(0) == 10  # 10 * 2^0
        assert rc.calculate_delay(1) == 20  # 10 * 2^1
        assert rc.calculate_delay(2) == 40  # 10 * 2^2
        assert rc.calculate_delay(3) == 80  # 10 * 2^3

    def test_calculate_delay_linear(self):
        rc = RetryConfig(
            backoff="linear", initial_delay_seconds=10, max_delay_seconds=300
        )
        assert rc.calculate_delay(0) == 10  # 10 * 1
        assert rc.calculate_delay(1) == 20  # 10 * 2
        assert rc.calculate_delay(2) == 30  # 10 * 3

    def test_calculate_delay_capped(self):
        rc = RetryConfig(
            backoff="exponential", initial_delay_seconds=100, max_delay_seconds=200
        )
        assert rc.calculate_delay(5) == 200  # Would be 3200, capped at 200

    def test_should_retry_enabled(self):
        rc = RetryConfig(enabled=True, max_attempts=3, retry_on=["auth", "network"])
        assert rc.should_retry("auth", 0) is True
        assert rc.should_retry("auth", 2) is True
        assert rc.should_retry("auth", 3) is False  # exceeded max
        assert rc.should_retry("timeout", 0) is False  # not in retry_on

    def test_should_retry_disabled(self):
        rc = RetryConfig(enabled=False)
        assert rc.should_retry("auth", 0) is False


# ==================== SchedulerConfig ====================


class TestSchedulerConfig:
    def test_init_from_data(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch("tool_modules.aa_workflow.src.scheduler_config.config_manager"):
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True

                config_data = {
                    "schedules": {
                        "timezone": "US/Eastern",
                        "jobs": [
                            {"name": "job1", "cron": "0 8 * * *", "skill": "s1"},
                            {"name": "job2", "trigger": "poll", "skill": "s2"},
                        ],
                        "poll_sources": {"gitlab": {}},
                        "execution_mode": "direct",
                        "default_retry": {"max_attempts": 5},
                    }
                }
                sc = SchedulerConfig(config_data)
                assert sc.timezone == "US/Eastern"
                assert len(sc.jobs) == 2
                assert sc.execution_mode == "direct"
                assert sc.default_retry["max_attempts"] == 5

    def test_get_cron_jobs(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch("tool_modules.aa_workflow.src.scheduler_config.config_manager"):
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True

                config_data = {
                    "schedules": {
                        "jobs": [
                            {"name": "cron1", "cron": "0 * * * *", "skill": "s1"},
                            {"name": "poll1", "trigger": "poll", "skill": "s2"},
                            {"name": "cron2", "cron": "30 8 * * 1-5", "skill": "s3"},
                        ]
                    }
                }
                sc = SchedulerConfig(config_data)
                cron_jobs = sc.get_cron_jobs()
                assert len(cron_jobs) == 2
                assert cron_jobs[0]["name"] == "cron1"

    def test_get_poll_jobs(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch("tool_modules.aa_workflow.src.scheduler_config.config_manager"):
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True

                config_data = {
                    "schedules": {
                        "jobs": [
                            {"name": "cron1", "cron": "0 * * * *", "skill": "s1"},
                            {"name": "poll1", "trigger": "poll", "skill": "s2"},
                        ]
                    }
                }
                sc = SchedulerConfig(config_data)
                poll_jobs = sc.get_poll_jobs()
                assert len(poll_jobs) == 1
                assert poll_jobs[0]["name"] == "poll1"

    def test_get_retry_config(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch("tool_modules.aa_workflow.src.scheduler_config.config_manager"):
                mock_sm.is_service_enabled.return_value = True
                config_data = {"schedules": {"default_retry": {"max_attempts": 4}}}
                sc = SchedulerConfig(config_data)
                rc = sc.get_retry_config({"retry": {"max_attempts": 1}})
                assert rc.max_attempts == 1

    def test_init_defaults(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = False
                mock_cm.get_all.return_value = {}
                sc = SchedulerConfig()
                assert sc.timezone == "UTC"
                assert sc.jobs == []
                assert sc.execution_mode == "claude_cli"

    def test_disabled_job_filtered(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch("tool_modules.aa_workflow.src.scheduler_config.config_manager"):
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.side_effect = lambda name: name != "disabled_job"

                config_data = {
                    "schedules": {
                        "jobs": [
                            {"name": "enabled_job", "cron": "0 * * * *", "skill": "s1"},
                            {
                                "name": "disabled_job",
                                "cron": "0 * * * *",
                                "skill": "s2",
                            },
                        ]
                    }
                }
                sc = SchedulerConfig(config_data)
                cron_jobs = sc.get_cron_jobs()
                assert len(cron_jobs) == 1
                assert cron_jobs[0]["name"] == "enabled_job"


# ==================== JobExecutionLog ====================


class TestJobExecutionLog:
    def test_init_no_file(self, tmp_path):
        with patch.object(JobExecutionLog, "HISTORY_FILE", tmp_path / "history.json"):
            log = JobExecutionLog()
            assert log.entries == []

    def test_load_from_file(self, tmp_path):
        history_file = tmp_path / "history.json"
        history_file.write_text(
            json.dumps(
                {
                    "executions": [
                        {"job_name": "j1", "success": True},
                        {"job_name": "j2", "success": False},
                    ]
                }
            )
        )
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            assert len(log.entries) == 2

    def test_load_bad_file(self, tmp_path):
        history_file = tmp_path / "history.json"
        history_file.write_text("bad json")
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            assert log.entries == []

    def test_log_execution(self, tmp_path):
        history_file = tmp_path / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            log.log_execution(
                job_name="test_job",
                skill="test_skill",
                success=True,
                duration_ms=500,
                output_preview="output here",
                session_name="session1",
            )
            assert len(log.entries) == 1
            assert log.entries[0]["job_name"] == "test_job"
            assert log.entries[0]["success"] is True
            assert history_file.exists()

    def test_log_execution_with_retry_info(self, tmp_path):
        history_file = tmp_path / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            log.log_execution(
                job_name="j1",
                skill="s1",
                success=False,
                duration_ms=1000,
                error="timeout",
                retry_info={
                    "attempts": 3,
                    "retried": True,
                    "failure_type": "network",
                    "remediation_applied": "vpn_connect",
                    "remediation_success": True,
                },
            )
            entry = log.entries[0]
            assert entry["retry"]["attempts"] == 3
            assert entry["retry"]["retried"] is True
            assert entry["retry"]["failure_type"] == "network"

    def test_log_execution_truncates_output(self, tmp_path):
        history_file = tmp_path / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            long_output = "x" * 1000
            log.log_execution("j", "s", True, 100, output_preview=long_output)
            assert len(log.entries[0]["output_preview"]) == 500

    def test_max_entries_trimming(self, tmp_path):
        history_file = tmp_path / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog(max_entries=5)
            for i in range(10):
                log.log_execution(f"job{i}", "s", True, 100)
            assert len(log.entries) == 5
            assert log.entries[0]["job_name"] == "job5"

    def test_get_recent(self, tmp_path):
        history_file = tmp_path / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            for i in range(5):
                log.log_execution(f"job{i}", "s", True, 100)
            recent = log.get_recent(3)
            assert len(recent) == 3
            assert recent[-1]["job_name"] == "job4"

    def test_get_for_job(self, tmp_path):
        history_file = tmp_path / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            log.log_execution("job_a", "s", True, 100)
            log.log_execution("job_b", "s", True, 100)
            log.log_execution("job_a", "s", False, 200)
            results = log.get_for_job("job_a")
            assert len(results) == 2
            assert all(e["job_name"] == "job_a" for e in results)

    def test_save_file_error(self, tmp_path):
        """Save errors should be caught, not raised."""
        history_file = tmp_path / "readonly" / "history.json"
        with patch.object(JobExecutionLog, "HISTORY_FILE", history_file):
            log = JobExecutionLog()
            # Make parent read-only to force write error
            with patch("builtins.open", side_effect=PermissionError("denied")):
                log.log_execution("j", "s", True, 100)
            # Should not raise
            assert len(log.entries) == 1


# ==================== CronScheduler ====================


class TestCronScheduler:
    def _make_scheduler(self, enabled=False, jobs=None):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = enabled
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": jobs or [],
                        "timezone": "UTC",
                    }
                }
                return CronScheduler()

    def test_init(self):
        sched = self._make_scheduler()
        assert sched._running is False
        assert sched.scheduler is None

    def test_parse_cron_valid(self):
        sched = self._make_scheduler()
        trigger = sched._parse_cron_to_trigger("0 8 * * 1-5")
        assert trigger is not None

    def test_parse_cron_invalid(self):
        sched = self._make_scheduler()
        with pytest.raises(ValueError, match="Invalid cron expression"):
            sched._parse_cron_to_trigger("bad cron")

    def test_parse_cron_too_few_fields(self):
        sched = self._make_scheduler()
        with pytest.raises(ValueError):
            sched._parse_cron_to_trigger("0 8 *")

    # ---------- _detect_failure_type ----------

    def test_detect_failure_type_empty(self):
        sched = self._make_scheduler()
        assert sched._detect_failure_type("") == "unknown"

    def test_detect_failure_type_auth(self):
        sched = self._make_scheduler()
        assert sched._detect_failure_type("Error: Unauthorized 401") == "auth"
        assert sched._detect_failure_type("token expired") == "auth"
        assert sched._detect_failure_type("403 Forbidden") == "auth"
        assert sched._detect_failure_type("authentication required") == "auth"
        assert sched._detect_failure_type("Permission denied") == "auth"
        assert sched._detect_failure_type("credentials invalid") == "auth"

    def test_detect_failure_type_network(self):
        sched = self._make_scheduler()
        assert sched._detect_failure_type("no route to host") == "network"
        assert sched._detect_failure_type("connection refused") == "network"
        assert sched._detect_failure_type("timeout error") == "network"
        assert sched._detect_failure_type("dial tcp failed") == "network"
        assert sched._detect_failure_type("connection reset by peer") == "network"
        assert sched._detect_failure_type("cannot connect") == "network"
        assert sched._detect_failure_type("HTTPSConnectionPool") == "network"

    def test_detect_failure_type_timeout(self):
        sched = self._make_scheduler()
        assert sched._detect_failure_type("request timed out") == "timeout"
        assert sched._detect_failure_type("deadline exceeded") == "timeout"
        assert sched._detect_failure_type("context deadline exceeded") == "timeout"

    def test_detect_failure_type_unknown(self):
        sched = self._make_scheduler()
        assert sched._detect_failure_type("some random error") == "unknown"

    # ---------- _apply_remediation ----------

    @pytest.mark.asyncio
    async def test_apply_remediation_auth(self):
        sched = self._make_scheduler()
        sched._run_kube_login = AsyncMock(return_value=True)
        remedy, success = await sched._apply_remediation("auth", "job1")
        assert remedy == "kube_login"
        assert success is True

    @pytest.mark.asyncio
    async def test_apply_remediation_network(self):
        sched = self._make_scheduler()
        sched._run_vpn_connect = AsyncMock(return_value=True)
        remedy, success = await sched._apply_remediation("network", "job1")
        assert remedy == "vpn_connect"
        assert success is True

    @pytest.mark.asyncio
    async def test_apply_remediation_timeout(self):
        sched = self._make_scheduler()
        remedy, success = await sched._apply_remediation("timeout", "job1")
        assert remedy is None
        assert success is True

    @pytest.mark.asyncio
    async def test_apply_remediation_unknown(self):
        sched = self._make_scheduler()
        remedy, success = await sched._apply_remediation("unknown", "job1")
        assert remedy is None
        assert success is False

    # ---------- _log_to_file ----------

    def test_log_to_file(self, tmp_path):
        sched = self._make_scheduler()
        tmp_path / "scheduler.log"
        with patch("pathlib.Path.home", return_value=tmp_path):
            sched._log_to_file("test message")
        # Verify log file was created
        actual_log = tmp_path / ".config" / "aa-workflow" / "scheduler.log"
        assert actual_log.exists()
        assert "test message" in actual_log.read_text()

    def test_log_to_file_error_silent(self):
        sched = self._make_scheduler()
        with patch("builtins.open", side_effect=PermissionError):
            sched._log_to_file("test")  # Should not raise

    # ---------- _cleanup_skill_execution_state ----------

    def test_cleanup_skill_state(self, tmp_path):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()

        exec_file = tmp_path / "skill_execution.json"
        state = {
            "skillName": "my_skill",
            "status": "running",
            "workspaceUri": "default",
            "currentStepIndex": 1,
        }
        exec_file.write_text(json.dumps(state))

        with patch("pathlib.Path.home", return_value=tmp_path):
            # Adjust the path to match what the code expects
            config_dir = tmp_path / ".config" / "aa-workflow"
            config_dir.mkdir(parents=True)
            actual_file = config_dir / "skill_execution.json"
            actual_file.write_text(json.dumps(state))

            sched._cleanup_skill_execution_state("my_skill", "Timed out")

            updated = json.loads(actual_file.read_text())
            assert updated["status"] == "failed"
            assert "endTime" in updated

    def test_cleanup_skill_state_different_skill(self, tmp_path):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()

        config_dir = tmp_path / ".config" / "aa-workflow"
        config_dir.mkdir(parents=True)
        exec_file = config_dir / "skill_execution.json"
        state = {"skillName": "other_skill", "status": "running"}
        exec_file.write_text(json.dumps(state))

        with patch("pathlib.Path.home", return_value=tmp_path):
            sched._cleanup_skill_execution_state("my_skill", "err")

        # Should not modify since different skill
        assert json.loads(exec_file.read_text())["status"] == "running"

    def test_cleanup_skill_state_already_failed(self, tmp_path):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()

        config_dir = tmp_path / ".config" / "aa-workflow"
        config_dir.mkdir(parents=True)
        exec_file = config_dir / "skill_execution.json"
        state = {"skillName": "my_skill", "status": "completed"}
        exec_file.write_text(json.dumps(state))

        with patch("pathlib.Path.home", return_value=tmp_path):
            sched._cleanup_skill_execution_state("my_skill", "err")

        assert json.loads(exec_file.read_text())["status"] == "completed"

    def test_cleanup_skill_state_no_file(self, tmp_path):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()
        with patch("pathlib.Path.home", return_value=tmp_path):
            sched._cleanup_skill_execution_state("my_skill", "err")  # should not raise

    # ---------- start / stop ----------

    @pytest.mark.asyncio
    async def test_start_disabled(self):
        sched = self._make_scheduler(enabled=False)
        with patch.object(sched, "_create_scheduler") as mock_create:
            mock_ap = MagicMock()
            mock_create.return_value = mock_ap
            with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
                mock_cf.exists.return_value = False
                await sched.start()
        assert sched._running is True
        mock_ap.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_enabled_with_jobs(self):
        sched = self._make_scheduler(
            enabled=True,
            jobs=[{"name": "j1", "cron": "0 * * * *", "skill": "s1"}],
        )
        with patch.object(sched, "_create_scheduler") as mock_create:
            mock_ap = MagicMock()
            mock_create.return_value = mock_ap
            with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
                mock_cf.exists.return_value = False
                await sched.start()
        assert sched._running is True

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        sched = self._make_scheduler()
        sched._running = True
        await sched.start()
        # Should return without creating scheduler
        assert sched.scheduler is None

    @pytest.mark.asyncio
    async def test_start_no_cron_jobs(self):
        sched = self._make_scheduler(enabled=True)
        with patch.object(sched, "_create_scheduler") as mock_create:
            mock_ap = MagicMock()
            mock_create.return_value = mock_ap
            with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
                mock_cf.exists.return_value = False
                await sched.start(add_cron_jobs=False)
        assert sched._running is True

    @pytest.mark.asyncio
    async def test_stop(self):
        sched = self._make_scheduler()
        sched._running = True
        sched.scheduler = MagicMock()
        await sched.stop()
        assert sched._running is False
        sched.scheduler.shutdown.assert_called_once_with(wait=True)

    @pytest.mark.asyncio
    async def test_stop_not_running(self):
        sched = self._make_scheduler()
        await sched.stop()  # Should not raise

    # ---------- _add_cron_job ----------

    def test_add_cron_job_no_scheduler(self):
        sched = self._make_scheduler()
        sched.scheduler = None
        sched._add_cron_job({"name": "j", "skill": "s", "cron": "0 * * * *"})
        # No error should occur

    def test_add_cron_job_missing_skill(self):
        sched = self._make_scheduler()
        sched.scheduler = MagicMock()
        sched._add_cron_job({"name": "j", "cron": "0 * * * *"})
        sched.scheduler.add_job.assert_not_called()

    def test_add_cron_job_missing_cron(self):
        sched = self._make_scheduler()
        sched.scheduler = MagicMock()
        sched._add_cron_job({"name": "j", "skill": "s"})
        sched.scheduler.add_job.assert_not_called()

    def test_add_cron_job_success(self):
        sched = self._make_scheduler()
        sched.scheduler = MagicMock()
        sched._add_cron_job(
            {
                "name": "morning",
                "skill": "check_health",
                "cron": "0 8 * * *",
                "inputs": {"target": "stage"},
                "notify": ["slack"],
                "persona": "devops",
                "timeout_seconds": 1200,
            }
        )
        sched.scheduler.add_job.assert_called_once()

    def test_add_cron_job_bad_cron(self):
        sched = self._make_scheduler()
        sched.scheduler = MagicMock()
        sched._add_cron_job({"name": "bad", "skill": "s", "cron": "not valid"})
        # Should log error but not raise

    # ---------- reload_config ----------

    def test_reload_config(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [{"name": "new_job", "cron": "0 * * * *", "skill": "s"}]
                    }
                }

                sched = CronScheduler()
                mock_job1 = MagicMock()
                mock_job1.id = "old_job"
                mock_job2 = MagicMock()
                mock_job2.id = "_config_watcher"
                sched.scheduler = MagicMock()
                sched.scheduler.get_jobs.return_value = [mock_job1, mock_job2]

                sched.reload_config()

                sched.scheduler.remove_job.assert_called_once_with("old_job")

    def test_reload_config_no_scheduler(self):
        sched = self._make_scheduler()
        sched.scheduler = None
        sched.reload_config()  # Should not raise

    # ---------- check_config_changed ----------

    def test_check_config_changed_no_file(self):
        sched = self._make_scheduler()
        with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
            mock_cf.exists.return_value = False
            assert sched.check_config_changed() is False

    def test_check_config_changed_first_call(self):
        sched = self._make_scheduler()
        sched._config_mtime = None
        with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
            mock_cf.exists.return_value = True
            mock_cf.stat.return_value = MagicMock(st_mtime=100.0)
            assert sched.check_config_changed() is False
            assert sched._config_mtime == 100.0

    def test_check_config_changed_modified(self):
        sched = self._make_scheduler()
        sched._config_mtime = 100.0
        with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
            mock_cf.exists.return_value = True
            mock_cf.stat.return_value = MagicMock(st_mtime=200.0)
            assert sched.check_config_changed() is True

    def test_check_config_changed_not_modified(self):
        sched = self._make_scheduler()
        sched._config_mtime = 100.0
        with patch("tool_modules.aa_workflow.src.scheduler.CONFIG_FILE") as mock_cf:
            mock_cf.exists.return_value = True
            mock_cf.stat.return_value = MagicMock(st_mtime=100.0)
            assert sched.check_config_changed() is False

    # ---------- _check_config_and_reload ----------

    @pytest.mark.asyncio
    async def test_check_config_no_change(self):
        sched = self._make_scheduler()
        sched.check_config_changed = MagicMock(return_value=False)
        await sched._check_config_and_reload()
        # Nothing should happen

    @pytest.mark.asyncio
    async def test_check_config_disabled(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = False
                mock_cm.get_all.return_value = {"schedules": {}}

                sched = CronScheduler()
                sched._running = True
                sched.check_config_changed = MagicMock(return_value=True)
                sched.config.enabled = True  # was enabled
                sched.scheduler = MagicMock()

                mock_job = MagicMock()
                mock_job.id = "some_job"
                sched.scheduler.get_jobs.return_value = [mock_job]

                with patch(
                    "tool_modules.aa_workflow.src.scheduler.CONFIG_FILE"
                ) as mock_cf:
                    mock_cf.exists.return_value = True
                    mock_cf.stat.return_value = MagicMock(st_mtime=999.0)
                    await sched._check_config_and_reload()

    @pytest.mark.asyncio
    async def test_check_config_enabled(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {"schedules": {"jobs": []}}

                sched = CronScheduler()
                sched.check_config_changed = MagicMock(return_value=True)
                sched.config.enabled = False  # was disabled

                sched.scheduler = MagicMock()
                sched.scheduler.get_jobs.return_value = []

                with patch(
                    "tool_modules.aa_workflow.src.scheduler.CONFIG_FILE"
                ) as mock_cf:
                    mock_cf.exists.return_value = True
                    mock_cf.stat.return_value = MagicMock(st_mtime=999.0)
                    await sched._check_config_and_reload()

    # ---------- run_job_now ----------

    @pytest.mark.asyncio
    async def test_run_job_now_not_found(self):
        sched = self._make_scheduler()
        result = await sched.run_job_now("nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_run_job_now_success(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [{"name": "job1", "skill": "s1", "cron": "0 * * * *"}]
                    }
                }
                sched = CronScheduler()
                sched._execute_job = AsyncMock()
                result = await sched.run_job_now("job1")
                assert result["success"] is True

    @pytest.mark.asyncio
    async def test_run_job_now_error(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [{"name": "job1", "skill": "s1", "cron": "0 * * * *"}]
                    }
                }
                sched = CronScheduler()
                sched._execute_job = AsyncMock(side_effect=RuntimeError("boom"))
                result = await sched.run_job_now("job1")
                assert result["success"] is False

    # ---------- get_job_info ----------

    def test_get_job_info_no_scheduler(self):
        sched = self._make_scheduler()
        assert sched.get_job_info("j1") is None

    def test_get_job_info_not_found(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {"schedules": {"jobs": []}}
                sched = CronScheduler()
                sched.scheduler = MagicMock()
                sched.scheduler.get_job.return_value = None
                assert sched.get_job_info("j1") is None

    def test_get_job_info_found(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [
                            {
                                "name": "j1",
                                "skill": "s1",
                                "cron": "0 * * * *",
                                "notify": ["slack"],
                            }
                        ]
                    }
                }
                sched = CronScheduler()
                sched.scheduler = MagicMock()
                mock_job = MagicMock()
                mock_job.next_run_time = datetime(2025, 1, 1, 8, 0)
                sched.scheduler.get_job.return_value = mock_job

                info = sched.get_job_info("j1")
                assert info["name"] == "j1"
                assert info["skill"] == "s1"
                assert info["next_run"] is not None
                assert info["notify"] == ["slack"]
                assert "retry" in info

    def test_get_job_info_no_config_match(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_cm.get_all.return_value = {"schedules": {"jobs": []}}
                sched = CronScheduler()
                sched.scheduler = MagicMock()
                mock_job = MagicMock()
                mock_job.next_run_time = None
                sched.scheduler.get_job.return_value = mock_job

                info = sched.get_job_info("j1")
                assert info["skill"] == "unknown"
                assert info["next_run"] is None

    # ---------- get_all_jobs ----------

    def test_get_all_jobs(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [
                            {"name": "cron1", "cron": "0 8 * * *", "skill": "s1"},
                            {
                                "name": "poll1",
                                "trigger": "poll",
                                "skill": "s2",
                                "poll_interval": "2h",
                                "condition": "new_issue",
                            },
                        ]
                    }
                }
                sched = CronScheduler()
                jobs = sched.get_all_jobs()
                assert len(jobs) == 2
                assert jobs[0]["type"] == "cron"
                assert jobs[0]["next_run"] is not None
                assert jobs[1]["type"] == "poll"
                assert jobs[1]["poll_interval"] == "2h"

    def test_get_all_jobs_bad_cron(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [{"name": "bad", "cron": "invalid", "skill": "s"}]
                    }
                }
                sched = CronScheduler()
                jobs = sched.get_all_jobs()
                assert jobs[0]["next_run"] is None

    # ---------- get_status ----------

    def test_get_status(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_sm.is_job_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {
                        "jobs": [
                            {"name": "c1", "cron": "0 * * * *", "skill": "s1"},
                            {"name": "p1", "trigger": "poll", "skill": "s2"},
                        ]
                    }
                }
                sched = CronScheduler()
                sched._running = True
                status = sched.get_status()
                assert status["enabled"] is True
                assert status["running"] is True
                assert status["total_jobs"] == 2
                assert status["cron_jobs"] == 1
                assert status["poll_jobs"] == 1

    # ---------- is_running ----------

    def test_is_running(self):
        sched = self._make_scheduler()
        assert sched.is_running is False
        sched._running = True
        assert sched.is_running is True

    # ---------- _execute_job ----------

    @pytest.mark.asyncio
    async def test_execute_job_direct_success(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {"execution_mode": "direct"}
                }

                sched = CronScheduler()
                sched._run_skill = AsyncMock(return_value="done")
                sched.execution_log = MagicMock()

                with patch(
                    "tool_modules.aa_workflow.src.scheduler.notify_cron_job_started",
                    create=True,
                ):
                    with patch(
                        "tool_modules.aa_workflow.src.scheduler.notify_cron_job_completed",
                        create=True,
                    ):
                        await sched._execute_job("j1", "s1", {}, [])

                sched._run_skill.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_job_direct_failure_no_retry(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {"execution_mode": "direct"}
                }

                sched = CronScheduler()
                sched._run_skill = AsyncMock(side_effect=RuntimeError("broken"))
                sched.execution_log = MagicMock()

                rc = RetryConfig(enabled=False)
                await sched._execute_job("j1", "s1", {}, [], retry_config=rc)

                sched.execution_log.log_execution.assert_called_once()
                call_kwargs = sched.execution_log.log_execution.call_args[1]
                assert call_kwargs["success"] is False

    @pytest.mark.asyncio
    async def test_execute_job_with_notifications(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                mock_sm.is_service_enabled.return_value = True
                mock_cm.get_all.return_value = {
                    "schedules": {"execution_mode": "direct"}
                }

                callback = AsyncMock()
                sched = CronScheduler(notification_callback=callback)
                sched._run_skill = AsyncMock(return_value="done")
                sched.execution_log = MagicMock()

                await sched._execute_job("j1", "s1", {}, ["slack"])

                callback.assert_called_once()

    # ---------- _send_notifications ----------

    @pytest.mark.asyncio
    async def test_send_notifications_no_callback(self):
        sched = self._make_scheduler()
        sched.notification_callback = None
        await sched._send_notifications("j", "s", True, "out", None, ["slack"])
        # Should not raise

    @pytest.mark.asyncio
    async def test_send_notifications_callback_error(self):
        sched = self._make_scheduler()
        sched.notification_callback = AsyncMock(side_effect=RuntimeError("fail"))
        await sched._send_notifications("j", "s", True, "out", None, ["slack"])
        # Should not raise

    # ---------- _run_kube_login ----------

    @pytest.mark.asyncio
    async def test_run_kube_login_success(self):
        sched = self._make_scheduler()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"Logged in", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", return_value=(b"Logged in", b"")):
                mock_proc.communicate = AsyncMock(return_value=(b"Logged in", b""))
                result = await sched._run_kube_login("stage")

        assert result is True

    @pytest.mark.asyncio
    async def test_run_kube_login_not_found(self):
        sched = self._make_scheduler()
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await sched._run_kube_login()
        assert result is False

    @pytest.mark.asyncio
    async def test_run_kube_login_generic_error(self):
        sched = self._make_scheduler()
        with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("fail")):
            result = await sched._run_kube_login()
        assert result is False

    # ---------- _run_vpn_connect ----------

    @pytest.mark.asyncio
    async def test_run_vpn_connect_no_script(self):
        sched = self._make_scheduler()
        with patch("os.path.exists", return_value=False):
            result = await sched._run_vpn_connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_run_vpn_connect_not_found(self):
        sched = self._make_scheduler()
        with patch("os.path.exists", return_value=True):
            with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
                result = await sched._run_vpn_connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_run_vpn_connect_generic_error(self):
        sched = self._make_scheduler()
        with patch("os.path.exists", return_value=True):
            with patch(
                "asyncio.create_subprocess_exec", side_effect=RuntimeError("fail")
            ):
                result = await sched._run_vpn_connect()
        assert result is False

    # ---------- _run_with_claude_cli ----------

    @pytest.mark.asyncio
    async def test_run_with_claude_cli_success(self):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", return_value=(b"output text", b"")):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", mock_open()):
                        success, output, error = await sched._run_with_claude_cli(
                            "j1", "s1", {}, "session1"
                        )
        assert success is True
        assert error is None

    @pytest.mark.asyncio
    async def test_run_with_claude_cli_timeout(self):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()
        sched._cleanup_skill_execution_state = MagicMock()

        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                success, output, error = await sched._run_with_claude_cli(
                    "j1", "s1", {}, "session1", timeout_seconds=10
                )

        assert success is False
        assert "timed out" in error

    @pytest.mark.asyncio
    async def test_run_with_claude_cli_not_found(self):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()
        sched._cleanup_skill_execution_state = MagicMock()

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            success, output, error = await sched._run_with_claude_cli(
                "j1", "s1", {}, "session1"
            )

        assert success is False
        assert "not found" in error.lower()

    @pytest.mark.asyncio
    async def test_run_with_claude_cli_nonzero_exit(self):
        sched = self._make_scheduler()
        sched._log_to_file = MagicMock()

        mock_proc = MagicMock()
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", return_value=(b"", b"error output")):
                with patch("pathlib.Path.mkdir"):
                    with patch("builtins.open", mock_open()):
                        success, output, error = await sched._run_with_claude_cli(
                            "j1", "s1", {}, "session1"
                        )

        assert success is False
        assert "error output" in error


# ==================== Module-level functions ====================


class TestModuleFunctions:
    def test_get_scheduler_none(self):
        with patch("tool_modules.aa_workflow.src.scheduler._scheduler", None):
            assert get_scheduler() is None

    def test_get_scheduler_exists(self):
        mock_sched_instance = MagicMock()
        with patch(
            "tool_modules.aa_workflow.src.scheduler._scheduler", mock_sched_instance
        ):
            assert get_scheduler() is mock_sched_instance

    def test_init_scheduler_new(self):
        with patch(
            "tool_modules.aa_workflow.src.scheduler_config.state_manager"
        ) as mock_sm:
            with patch(
                "tool_modules.aa_workflow.src.scheduler_config.config_manager"
            ) as mock_cm:
                with patch("tool_modules.aa_workflow.src.scheduler._scheduler", None):
                    mock_sm.is_service_enabled.return_value = False
                    mock_cm.get_all.return_value = {"schedules": {}}

                    import tool_modules.aa_workflow.src.scheduler as smod

                    smod._scheduler = None

                    sched = init_scheduler()
                    assert sched is not None
                    smod._scheduler = None  # cleanup

    def test_init_scheduler_already_exists(self):
        with patch("tool_modules.aa_workflow.src.scheduler_config.state_manager"):
            with patch("tool_modules.aa_workflow.src.scheduler_config.config_manager"):
                import tool_modules.aa_workflow.src.scheduler as smod

                existing = MagicMock()
                smod._scheduler = existing

                result = init_scheduler()
                assert result is existing
                smod._scheduler = None  # cleanup

    @pytest.mark.asyncio
    async def test_start_scheduler_no_instance(self):
        import tool_modules.aa_workflow.src.scheduler as smod

        smod._scheduler = None
        await start_scheduler()  # Should not raise

    @pytest.mark.asyncio
    async def test_start_scheduler_with_instance(self):
        import tool_modules.aa_workflow.src.scheduler as smod

        mock_sched = MagicMock()
        mock_sched.start = AsyncMock()
        smod._scheduler = mock_sched
        await start_scheduler(add_cron_jobs=False)
        mock_sched.start.assert_called_once_with(add_cron_jobs=False)
        smod._scheduler = None

    @pytest.mark.asyncio
    async def test_stop_scheduler_no_instance(self):
        import tool_modules.aa_workflow.src.scheduler as smod

        smod._scheduler = None
        await stop_scheduler()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_scheduler_with_instance(self):
        import tool_modules.aa_workflow.src.scheduler as smod

        mock_sched = MagicMock()
        mock_sched.stop = AsyncMock()
        smod._scheduler = mock_sched
        await stop_scheduler()
        mock_sched.stop.assert_called_once()
        smod._scheduler = None
