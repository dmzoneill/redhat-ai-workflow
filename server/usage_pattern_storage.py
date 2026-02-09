"""
Usage Pattern Storage - Layer 5 of Auto-Heal System.

This module handles storage and retrieval of usage patterns.

Part of Layer 5: Usage Pattern Learning
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class UsagePatternStorage:
    """Handle storage and retrieval of usage patterns."""

    def __init__(self, patterns_file: Optional[Path] = None):
        """Initialize storage.

        Args:
            patterns_file: Path to usage_patterns.yaml file.
                          If None, uses default location.
        """
        if patterns_file is None:
            # Default location
            project_root = Path(__file__).parent.parent
            patterns_file = project_root / "memory" / "learned" / "usage_patterns.yaml"

        self.patterns_file = patterns_file
        self.patterns_file.parent.mkdir(parents=True, exist_ok=True)

        # Ensure file exists
        if not self.patterns_file.exists():
            self._initialize_file()

    def _initialize_file(self):
        """Initialize usage_patterns.yaml with schema."""
        initial_data = {
            "usage_patterns": [],
            "stats": {
                "total_usage_patterns": 0,
                "high_confidence": 0,
                "medium_confidence": 0,
                "low_confidence": 0,
                "by_category": {
                    "INCORRECT_PARAMETER": 0,
                    "PARAMETER_FORMAT": 0,
                    "MISSING_PREREQUISITE": 0,
                    "WORKFLOW_SEQUENCE": 0,
                    "WRONG_TOOL_SELECTION": 0,
                },
                "prevention_success_rate": 0.0,
                "last_updated": None,
            },
        }

        with open(self.patterns_file, "w", encoding="utf-8") as f:
            yaml.dump(initial_data, f, default_flow_style=False, sort_keys=False)

        logger.info(f"Initialized usage patterns file: {self.patterns_file}")

    def load(self) -> dict:
        """Load all patterns from storage."""
        try:
            with open(self.patterns_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if not data:
                    logger.warning("Usage patterns file is empty, reinitializing")
                    self._initialize_file()
                    return self.load()
                return data
        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error loading usage patterns: {e}")
            return {"usage_patterns": [], "stats": {}}

    def save(self, data: dict):
        """Save patterns to storage.

        Args:
            data: Full patterns data structure to save
        """
        try:
            # Update stats before saving
            data = self._update_stats(data)

            # Update last_updated timestamp
            if "stats" not in data:
                data["stats"] = {}
            data["stats"]["last_updated"] = datetime.now().isoformat()

            with open(self.patterns_file, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)

            logger.debug(f"Saved usage patterns to {self.patterns_file}")

        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error saving usage patterns: {e}")

    def add_pattern(self, pattern: dict) -> bool:
        """Add a new pattern to storage.

        Args:
            pattern: Pattern dict to add

        Returns:
            True if added successfully
        """
        try:
            data = self.load()

            # Check if pattern ID already exists
            existing_ids = {p["id"] for p in data.get("usage_patterns", [])}
            if pattern["id"] in existing_ids:
                logger.warning(
                    f"Pattern ID {pattern['id']} already exists, skipping add"
                )
                return False

            # Add pattern
            if "usage_patterns" not in data:
                data["usage_patterns"] = []
            data["usage_patterns"].append(pattern)

            # Save
            self.save(data)
            logger.info(f"Added new usage pattern: {pattern['id']}")
            return True

        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error adding pattern: {e}")
            return False

    def update_pattern(self, pattern_id: str, updates: dict) -> bool:
        """Update an existing pattern.

        Args:
            pattern_id: ID of pattern to update
            updates: Dict of fields to update

        Returns:
            True if updated successfully
        """
        try:
            data = self.load()

            # Find pattern
            patterns = data.get("usage_patterns", [])
            for i, pattern in enumerate(patterns):
                if pattern["id"] == pattern_id:
                    # Update fields
                    for key, value in updates.items():
                        pattern[key] = value

                    # Update last_seen
                    pattern["last_seen"] = datetime.now().isoformat()

                    # Save
                    data["usage_patterns"][i] = pattern
                    self.save(data)
                    logger.info(f"Updated usage pattern: {pattern_id}")
                    return True

            logger.warning(f"Pattern ID {pattern_id} not found")
            return False

        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error updating pattern: {e}")
            return False

    def get_pattern(self, pattern_id: str) -> Optional[dict]:
        """Get a specific pattern by ID.

        Args:
            pattern_id: ID of pattern to retrieve

        Returns:
            Pattern dict or None if not found
        """
        data = self.load()
        patterns = data.get("usage_patterns", [])

        for pattern in patterns:
            if pattern["id"] == pattern_id:
                return pattern

        return None

    def get_patterns_for_tool(
        self, tool_name: str, min_confidence: float = 0.0
    ) -> list[dict]:
        """Get all patterns for a specific tool.

        Args:
            tool_name: Name of tool to get patterns for
            min_confidence: Minimum confidence threshold

        Returns:
            List of patterns for the tool
        """
        data = self.load()
        patterns = data.get("usage_patterns", [])

        return [
            p
            for p in patterns
            if p.get("tool") == tool_name and p.get("confidence", 0.0) >= min_confidence
        ]

    def get_high_confidence_patterns(self, min_confidence: float = 0.85) -> list[dict]:
        """Get all high-confidence patterns.

        Args:
            min_confidence: Minimum confidence threshold (default: 0.85)

        Returns:
            List of high-confidence patterns
        """
        data = self.load()
        patterns = data.get("usage_patterns", [])

        return [p for p in patterns if p.get("confidence", 0.0) >= min_confidence]

    def delete_pattern(self, pattern_id: str) -> bool:
        """Delete a pattern.

        Args:
            pattern_id: ID of pattern to delete

        Returns:
            True if deleted successfully
        """
        try:
            data = self.load()
            patterns = data.get("usage_patterns", [])

            # Filter out the pattern
            new_patterns = [p for p in patterns if p["id"] != pattern_id]

            if len(new_patterns) == len(patterns):
                logger.warning(f"Pattern ID {pattern_id} not found")
                return False

            data["usage_patterns"] = new_patterns
            self.save(data)
            logger.info(f"Deleted usage pattern: {pattern_id}")
            return True

        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error deleting pattern: {e}")
            return False

    def _update_stats(self, data: dict) -> dict:
        """Update statistics based on current patterns."""
        patterns = data.get("usage_patterns", [])

        if "stats" not in data:
            data["stats"] = {}

        # Total patterns
        data["stats"]["total_usage_patterns"] = len(patterns)

        # By confidence level
        high_conf = sum(1 for p in patterns if p.get("confidence", 0.0) >= 0.85)
        medium_conf = sum(
            1 for p in patterns if 0.70 <= p.get("confidence", 0.0) < 0.85
        )
        low_conf = sum(1 for p in patterns if p.get("confidence", 0.0) < 0.70)

        data["stats"]["high_confidence"] = high_conf
        data["stats"]["medium_confidence"] = medium_conf
        data["stats"]["low_confidence"] = low_conf

        # By category
        if "by_category" not in data["stats"]:
            data["stats"]["by_category"] = {}

        categories = [
            "INCORRECT_PARAMETER",
            "PARAMETER_FORMAT",
            "MISSING_PREREQUISITE",
            "WORKFLOW_SEQUENCE",
            "WRONG_TOOL_SELECTION",
        ]

        for category in categories:
            count = sum(1 for p in patterns if p.get("error_category") == category)
            data["stats"]["by_category"][category] = count

        # Prevention success rate
        total_obs = sum(p.get("observations", 0) for p in patterns)
        total_success = sum(p.get("success_after_prevention", 0) for p in patterns)

        if total_obs > 0:
            data["stats"]["prevention_success_rate"] = round(
                total_success / total_obs, 3
            )
        else:
            data["stats"]["prevention_success_rate"] = 0.0

        return data

    def prune_old_patterns(
        self, max_age_days: int = 90, min_confidence: float = 0.70
    ) -> int:
        """Remove old low-confidence patterns.

        Args:
            max_age_days: Maximum age in days for low-confidence patterns
            min_confidence: Confidence threshold for pruning

        Returns:
            Number of patterns pruned
        """
        try:
            data = self.load()
            patterns = data.get("usage_patterns", [])

            now = datetime.now()
            pruned = 0

            new_patterns = []
            for pattern in patterns:
                # Keep high-confidence patterns
                if pattern.get("confidence", 0.0) >= min_confidence:
                    new_patterns.append(pattern)
                    continue

                # Check age
                last_seen = datetime.fromisoformat(
                    pattern.get("last_seen", now.isoformat())
                )
                age_days = (now - last_seen).days

                if age_days < max_age_days:
                    new_patterns.append(pattern)
                else:
                    pruned += 1
                    logger.info(
                        f"Pruned old pattern: {pattern['id']} "
                        f"(age: {age_days}d, conf: {pattern.get('confidence', 0.0):.2f})"
                    )

            if pruned > 0:
                data["usage_patterns"] = new_patterns
                self.save(data)

            return pruned

        except (OSError, yaml.YAMLError, ValueError, KeyError, TypeError) as e:
            logger.error(f"Error pruning patterns: {e}")
            return 0
