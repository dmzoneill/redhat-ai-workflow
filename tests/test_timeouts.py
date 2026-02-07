"""Tests for server.timeouts module."""

import pytest

from server.timeouts import (
    DEFAULT_ENVIRONMENT,
    DURATION_MINUTES,
    VALID_ENVIRONMENTS,
    OutputLimits,
    Timeouts,
    parse_duration_to_minutes,
)


class TestTimeoutsConstants:
    """Tests for Timeouts class constants."""

    def test_instant_value(self):
        assert Timeouts.INSTANT == 2

    def test_quick_value(self):
        assert Timeouts.QUICK == 5

    def test_short_value(self):
        assert Timeouts.SHORT == 10

    def test_fast_value(self):
        assert Timeouts.FAST == 30

    def test_default_value(self):
        assert Timeouts.DEFAULT == 60

    def test_lint_value(self):
        assert Timeouts.LINT == 300

    def test_build_value(self):
        assert Timeouts.BUILD == 600

    def test_deploy_value(self):
        assert Timeouts.DEPLOY == 900

    def test_test_suite_value(self):
        assert Timeouts.TEST_SUITE == 1200

    def test_http_request_value(self):
        assert Timeouts.HTTP_REQUEST == 30

    def test_cluster_login_value(self):
        assert Timeouts.CLUSTER_LOGIN == 120

    def test_bonfire_reserve_value(self):
        assert Timeouts.BONFIRE_RESERVE == 660

    def test_bonfire_deploy_value(self):
        assert Timeouts.BONFIRE_DEPLOY == 960

    def test_bonfire_iqe_value(self):
        assert Timeouts.BONFIRE_IQE == 900

    def test_db_connect_value(self):
        assert Timeouts.DB_CONNECT == 10

    def test_db_query_value(self):
        assert Timeouts.DB_QUERY == 30

    def test_process_wait_value(self):
        assert Timeouts.PROCESS_WAIT == 60

    def test_all_values_are_positive(self):
        """Every timeout constant should be positive."""
        for attr in dir(Timeouts):
            if attr.isupper():
                val = getattr(Timeouts, attr)
                assert val > 0, f"Timeouts.{attr} must be positive, got {val}"


class TestOutputLimits:
    """Tests for OutputLimits class constants."""

    def test_short_value(self):
        assert OutputLimits.SHORT == 1000

    def test_medium_value(self):
        assert OutputLimits.MEDIUM == 2000

    def test_standard_value(self):
        assert OutputLimits.STANDARD == 5000

    def test_long_value(self):
        assert OutputLimits.LONG == 10000

    def test_full_value(self):
        assert OutputLimits.FULL == 15000

    def test_extended_value(self):
        assert OutputLimits.EXTENDED == 20000

    def test_ascending_order(self):
        """Limits should increase from SHORT to EXTENDED."""
        assert (
            OutputLimits.SHORT
            < OutputLimits.MEDIUM
            < OutputLimits.STANDARD
            < OutputLimits.LONG
            < OutputLimits.FULL
            < OutputLimits.EXTENDED
        )


class TestEnvironmentConstants:
    """Tests for environment type definitions."""

    def test_default_environment(self):
        assert DEFAULT_ENVIRONMENT == "stage"

    def test_valid_environments_has_stage(self):
        assert "stage" in VALID_ENVIRONMENTS

    def test_valid_environments_has_prod(self):
        assert "prod" in VALID_ENVIRONMENTS

    def test_valid_environments_has_ephemeral(self):
        assert "ephemeral" in VALID_ENVIRONMENTS

    def test_valid_environments_has_konflux(self):
        assert "konflux" in VALID_ENVIRONMENTS

    def test_valid_environments_count(self):
        assert len(VALID_ENVIRONMENTS) == 4

    def test_default_is_in_valid(self):
        assert DEFAULT_ENVIRONMENT in VALID_ENVIRONMENTS


class TestDurationMinutes:
    """Tests for DURATION_MINUTES mapping."""

    def test_seconds_conversion(self):
        assert DURATION_MINUTES["s"] == pytest.approx(1 / 60)

    def test_minutes_conversion(self):
        assert DURATION_MINUTES["m"] == 1

    def test_hours_conversion(self):
        assert DURATION_MINUTES["h"] == 60

    def test_days_conversion(self):
        assert DURATION_MINUTES["d"] == 1440

    def test_weeks_conversion(self):
        assert DURATION_MINUTES["w"] == 10080


class TestParseDurationToMinutes:
    """Tests for parse_duration_to_minutes function."""

    def test_empty_string_returns_default(self):
        assert parse_duration_to_minutes("") == 60

    def test_pure_digits_treated_as_minutes(self):
        assert parse_duration_to_minutes("45") == 45

    def test_minutes_suffix(self):
        assert parse_duration_to_minutes("30m") == 30

    def test_hours_suffix(self):
        assert parse_duration_to_minutes("2h") == 120

    def test_days_suffix(self):
        assert parse_duration_to_minutes("1d") == 1440

    def test_weeks_suffix(self):
        assert parse_duration_to_minutes("1w") == 10080

    def test_seconds_suffix(self):
        # 60 seconds = 1 minute
        assert parse_duration_to_minutes("60s") == 1

    def test_uppercase_suffix_treated_same(self):
        # unit is lowered
        assert parse_duration_to_minutes("2H") == 120

    def test_invalid_value_returns_default(self):
        assert parse_duration_to_minutes("abcm") == 60

    def test_unknown_unit_defaults_to_multiplier_1(self):
        # unknown unit 'x' uses multiplier 1 from dict.get(unit, 1)
        assert parse_duration_to_minutes("5x") == 5

    def test_zero_value(self):
        assert parse_duration_to_minutes("0m") == 0

    def test_large_value(self):
        assert parse_duration_to_minutes("100h") == 6000
