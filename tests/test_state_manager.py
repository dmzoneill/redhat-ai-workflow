"""Tests for StateManager singleton."""

import json
import threading
import time

import pytest


class TestStateManager:
    """Tests for StateManager functionality."""

    @pytest.fixture(autouse=True)
    def setup_temp_state(self, tmp_path):
        """Set up a temporary state file for each test."""
        self.state_file = tmp_path / "state.json"

        # Patch the STATE_FILE constant
        import server.state_manager as sm_module

        self.original_state_file = sm_module.STATE_FILE
        sm_module.STATE_FILE = self.state_file

        # Reset singleton for each test
        sm_module.StateManager._instance = None

        yield

        # Restore original
        sm_module.STATE_FILE = self.original_state_file
        sm_module.StateManager._instance = None

    def test_singleton_pattern(self):
        """Test that StateManager is a singleton."""
        from server.state_manager import StateManager

        manager1 = StateManager()
        manager2 = StateManager()

        assert manager1 is manager2

    def test_default_state_when_file_missing(self):
        """Test that default state is used when file doesn't exist."""
        from server.state_manager import StateManager

        manager = StateManager()

        # Should have default services
        assert manager.get("services") is not None
        assert "scheduler" in manager.get("services")
        assert "sprint_bot" in manager.get("services")

    def test_load_existing_state(self):
        """Test loading state from existing file."""
        # Create state file
        state_data = {
            "version": 1,
            "services": {
                "scheduler": {"enabled": True},
                "sprint_bot": {"enabled": False},
            },
            "jobs": {
                "test_job": {"enabled": True},
            },
        }
        self.state_file.write_text(json.dumps(state_data))

        from server.state_manager import StateManager

        manager = StateManager()

        assert manager.is_service_enabled("scheduler") is True
        assert manager.is_service_enabled("sprint_bot") is False
        assert manager.is_job_enabled("test_job") is True

    def test_get_section(self):
        """Test getting entire section."""
        from server.state_manager import StateManager

        manager = StateManager()

        services = manager.get("services")
        assert isinstance(services, dict)
        assert "scheduler" in services

    def test_get_key(self):
        """Test getting specific key from section."""
        from server.state_manager import StateManager

        manager = StateManager()

        scheduler = manager.get("services", "scheduler", {})
        assert isinstance(scheduler, dict)

    def test_get_default(self):
        """Test default value when key doesn't exist."""
        from server.state_manager import StateManager

        manager = StateManager()

        result = manager.get("nonexistent", "key", "default_value")
        assert result == "default_value"

    def test_set_value(self):
        """Test setting a value."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set("services", "test_service", {"enabled": True}, flush=True)

        # Verify it was set
        assert manager.get("services", "test_service") == {"enabled": True}

        # Verify it was written to disk
        with open(self.state_file) as f:
            data = json.load(f)
        assert data["services"]["test_service"]["enabled"] is True

    def test_is_service_enabled(self):
        """Test is_service_enabled convenience method."""
        from server.state_manager import StateManager

        manager = StateManager()

        # Default should be False
        assert manager.is_service_enabled("scheduler") is False

        # Set to True
        manager.set_service_enabled("scheduler", True, flush=True)
        assert manager.is_service_enabled("scheduler") is True

    def test_set_service_enabled(self):
        """Test set_service_enabled convenience method."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set_service_enabled("scheduler", True, flush=True)

        # Verify via get
        scheduler = manager.get("services", "scheduler")
        assert scheduler["enabled"] is True

    def test_is_job_enabled_default_true(self):
        """Test that jobs default to enabled if not explicitly set."""
        from server.state_manager import StateManager

        manager = StateManager()

        # Job not in state should default to True
        assert manager.is_job_enabled("nonexistent_job") is True

    def test_set_job_enabled(self):
        """Test set_job_enabled convenience method."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set_job_enabled("test_job", False, flush=True)
        assert manager.is_job_enabled("test_job") is False

        manager.set_job_enabled("test_job", True, flush=True)
        assert manager.is_job_enabled("test_job") is True

    def test_get_all_job_states(self):
        """Test getting all job states."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set_job_enabled("job1", True)
        manager.set_job_enabled("job2", False)
        manager.flush()

        states = manager.get_all_job_states()
        assert states["job1"] is True
        assert states["job2"] is False

    def test_delete_key(self):
        """Test deleting a key."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set("services", "temp_service", {"enabled": True}, flush=True)
        assert manager.get("services", "temp_service") is not None

        manager.delete("services", "temp_service", flush=True)
        assert manager.get("services", "temp_service") is None

    def test_delete_section(self):
        """Test deleting entire section."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set("temp_section", "key", "value", flush=True)
        assert manager.has_section("temp_section")

        manager.delete("temp_section", flush=True)
        assert not manager.has_section("temp_section")

    def test_reload(self):
        """Test reloading state from disk."""
        from server.state_manager import StateManager

        manager = StateManager()

        # Set a value
        manager.set_service_enabled("scheduler", True, flush=True)

        # Modify file directly
        with open(self.state_file) as f:
            data = json.load(f)
        data["services"]["scheduler"]["enabled"] = False
        with open(self.state_file, "w") as f:
            json.dump(data, f)

        # Reload
        manager.reload()

        # Should reflect file change
        assert manager.is_service_enabled("scheduler") is False

    def test_flush(self):
        """Test explicit flush."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set("services", "scheduler", {"enabled": True})
        # Don't flush yet - file might not be updated due to debounce

        manager.flush()

        # Now file should be updated
        with open(self.state_file) as f:
            data = json.load(f)
        assert data["services"]["scheduler"]["enabled"] is True

    def test_is_dirty(self):
        """Test dirty flag."""
        from server.state_manager import StateManager

        manager = StateManager()

        # Initially not dirty (just loaded)
        manager.flush()  # Ensure clean
        assert not manager.is_dirty

        # After set, should be dirty
        manager.set("services", "scheduler", {"enabled": True})
        assert manager.is_dirty

        # After flush, not dirty
        manager.flush()
        assert not manager.is_dirty

    def test_sections(self):
        """Test getting list of sections."""
        from server.state_manager import StateManager

        manager = StateManager()

        sections = manager.sections()
        assert "services" in sections
        assert "jobs" in sections

    def test_update_section_merge(self):
        """Test updating section with merge."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set("services", "existing", {"enabled": True}, flush=True)

        # Merge new data
        manager.update_section(
            "services", {"new_service": {"enabled": False}}, merge=True, flush=True
        )

        # Both should exist
        assert manager.get("services", "existing") is not None
        assert manager.get("services", "new_service") is not None

    def test_update_section_replace(self):
        """Test updating section without merge (replace)."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set("services", "existing", {"enabled": True}, flush=True)

        # Replace entire section
        manager.update_section(
            "services", {"new_service": {"enabled": False}}, merge=False, flush=True
        )

        # Only new should exist
        assert manager.get("services", "existing") is None
        assert manager.get("services", "new_service") is not None

    def test_meeting_overrides(self):
        """Test meeting override convenience methods."""
        from server.state_manager import StateManager

        manager = StateManager()

        # Initially empty
        assert manager.get_meeting_overrides() == {}
        assert manager.get_meeting_override("abc-defg-hij") is None

        # Set an override
        manager.set_meeting_override("abc-defg-hij", "skip")

        # Verify it was set
        assert manager.get_meeting_override("abc-defg-hij") == "skip"
        overrides = manager.get_meeting_overrides()
        assert "abc-defg-hij" in overrides
        assert overrides["abc-defg-hij"]["status"] == "skip"
        assert "timestamp" in overrides["abc-defg-hij"]

        # Clear the override
        result = manager.clear_meeting_override("abc-defg-hij")
        assert result is True
        assert manager.get_meeting_override("abc-defg-hij") is None

        # Clear non-existent returns False
        result = manager.clear_meeting_override("xyz-wxyz-xyz")
        assert result is False


class TestStateManagerThreadSafety:
    """Tests for StateManager thread safety."""

    @pytest.fixture(autouse=True)
    def setup_temp_state(self, tmp_path):
        """Set up a temporary state file for each test."""
        self.state_file = tmp_path / "state.json"

        import server.state_manager as sm_module

        self.original_state_file = sm_module.STATE_FILE
        sm_module.STATE_FILE = self.state_file
        sm_module.StateManager._instance = None

        yield

        sm_module.STATE_FILE = self.original_state_file
        sm_module.StateManager._instance = None

    def test_concurrent_writes(self):
        """Test that concurrent writes don't corrupt state."""
        from server.state_manager import StateManager

        manager = StateManager()

        errors = []

        def writer(thread_id):
            try:
                for i in range(10):
                    manager.set("jobs", f"thread{thread_id}_job{i}", {"enabled": True})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        manager.flush()

        assert len(errors) == 0

        # Verify all writes succeeded
        jobs = manager.get("jobs")
        assert len(jobs) == 50  # 5 threads * 10 jobs each

    def test_concurrent_reads_writes(self):
        """Test concurrent reads and writes."""
        from server.state_manager import StateManager

        manager = StateManager()

        manager.set_service_enabled("scheduler", True, flush=True)

        errors = []
        read_results = []

        def reader():
            try:
                for _ in range(20):
                    result = manager.is_service_enabled("scheduler")
                    read_results.append(result)
                    # Yield to other thread to promote interleaving
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(20):
                    manager.set_service_enabled("scheduler", i % 2 == 0)
                    # Yield to other thread to promote interleaving
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        reader_thread = threading.Thread(target=reader)
        writer_thread = threading.Thread(target=writer)

        reader_thread.start()
        writer_thread.start()

        reader_thread.join()
        writer_thread.join()

        assert len(errors) == 0
        # All reads should have returned boolean values
        assert all(isinstance(r, bool) for r in read_results)
