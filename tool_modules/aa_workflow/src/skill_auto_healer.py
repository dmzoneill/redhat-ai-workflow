# pylint: disable=duplicate-code,cyclic-import
"""Facade over SkillExecutor auto-heal methods.

The implementation lives on SkillHealMixin. This class delegates so callers
that hold a SkillAutoHealer still reach the executor methods tests patch.
"""


class SkillAutoHealer:
    """Delegates heal operations to the parent SkillExecutor."""

    def __init__(self, executor):
        self.executor = executor

    def find_matched_pattern(self, *args, **kwargs):
        """Delegate pattern lookup."""
        return self.executor.find_matched_pattern(*args, **kwargs)

    def determine_fix_type(self, *args, **kwargs):
        """Delegate fix-type selection."""
        return self.executor.determine_fix_type(*args, **kwargs)

    def detect_auto_heal_type(self, *args, **kwargs):
        """Delegate heal-type detection."""
        return self.executor.detect_auto_heal_type(*args, **kwargs)

    async def attempt_auto_heal(self, *args, **kwargs):
        """Delegate an auth or network heal attempt."""
        return await self.executor.attempt_auto_heal(*args, **kwargs)

    async def log_auto_heal_to_memory(self, *args, **kwargs):
        """Delegate memory logging for a heal attempt."""
        return await self.executor.log_auto_heal_to_memory(*args, **kwargs)

    def update_pattern_usage_stats(self, *args, **kwargs):
        """Delegate pattern usage statistics."""
        return self.executor.update_pattern_usage_stats(*args, **kwargs)

    async def try_auto_fix(self, *args, **kwargs):
        """Delegate a pattern-based auto fix."""
        return await self.executor.try_auto_fix(*args, **kwargs)

    async def apply_network_fix(self):
        """Delegate VPN remediation."""
        return await self.executor.apply_network_fix()

    async def apply_auth_fix(self, *args, **kwargs):
        """Delegate kube-login remediation."""
        return await self.executor.apply_auth_fix(*args, **kwargs)
