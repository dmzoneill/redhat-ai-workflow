"""Competency Mapper - Maps work items to PSE competencies.

Uses keyword rules for clear mappings and AI fallback for ambiguous items.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default competencies config location
COMPETENCIES_FILE = Path.home() / ".config" / "aa-workflow" / "competencies.json"


class CompetencyMapper:
    """Maps work items to PSE competencies using rules and AI."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or COMPETENCIES_FILE
        self.config = self._load_config()
        self.competencies = self.config.get("competencies", {})
        self.meta_categories = self.config.get("meta_categories", {})

    def _load_config(self) -> dict:
        """Load competencies configuration."""
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load competencies config: {e}")
        return self._get_default_config()

    def _get_default_config(self) -> dict:
        """Return default competencies configuration."""
        return {
            "version": "1.0",
            "quarter_target_points": 100,
            "daily_cap_per_competency": 15,
            "competencies": {},
            "meta_categories": {},
        }

    def map_event(self, event: dict) -> dict[str, int]:
        """Map an event to competencies and calculate points.

        Args:
            event: Work event with source, type, and metadata

        Returns:
            Dict of competency_id -> points
        """
        points = {}
        source = event.get("source", "")
        event_type = event.get("type", "")
        title = event.get("title", "")
        labels = event.get("labels", [])
        metadata = event.get("metadata", {})

        # Check each competency's detection rules
        for comp_id, comp_config in self.competencies.items():
            comp_points = self._check_rules(
                comp_config, source, event_type, event, metadata
            )
            if comp_points > 0:
                points[comp_id] = comp_points
                continue

            # Fallback to keyword matching
            keyword_points = self._check_keywords(comp_config, title, labels)
            if keyword_points > 0:
                points[comp_id] = keyword_points

        return points

    def _check_rules(
        self,
        comp_config: dict,
        source: str,
        event_type: str,
        event: dict,
        metadata: dict,
    ) -> int:
        """Check detection rules for a competency."""
        rules = comp_config.get("detection_rules", [])
        total_points = 0
        multiplier = 1.0

        for rule in rules:
            if rule.get("source") != source:
                continue
            if rule.get("type") != event_type:
                continue

            # Check conditions
            conditions = rule.get("conditions", {})
            if not self._check_conditions(conditions, event, metadata):
                continue

            # Apply points or multiplier
            if "points" in rule:
                total_points += rule["points"]
            if "multiplier" in rule:
                multiplier *= rule["multiplier"]

        return int(total_points * multiplier)

    def _check_conditions(self, conditions: dict, event: dict, metadata: dict) -> bool:
        """Check if conditions are met."""
        if not conditions:
            return True

        for key, expected in conditions.items():
            actual = event.get(key) or metadata.get(key)

            if isinstance(expected, dict):
                # Range conditions
                if "lt" in expected and not (
                    actual is not None and actual < expected["lt"]
                ):
                    return False
                if "lte" in expected and not (
                    actual is not None and actual <= expected["lte"]
                ):
                    return False
                if "gt" in expected and not (
                    actual is not None and actual > expected["gt"]
                ):
                    return False
                if "gte" in expected and not (
                    actual is not None and actual >= expected["gte"]
                ):
                    return False
                if "not" in expected and actual == expected["not"]:
                    return False
            elif isinstance(expected, list):
                if actual not in expected:
                    return False
            elif expected == "self":
                # Special case for checking if user is self
                if actual != metadata.get("current_user"):
                    return False
            elif actual != expected:
                return False

        return True

    def _check_keywords(self, comp_config: dict, title: str, labels: list) -> int:
        """Check keyword matching for a competency."""
        keywords = comp_config.get("keywords", [])
        if not keywords:
            return 0

        text = f"{title} {' '.join(labels)}".lower()

        for keyword in keywords:
            if keyword.lower() in text:
                return 1  # Base point for keyword match

        return 0

    def get_competency_info(self, comp_id: str) -> dict | None:
        """Get information about a competency."""
        return self.competencies.get(comp_id)

    def get_all_competencies(self) -> list[dict]:
        """Get all competency definitions."""
        return [
            {"id": comp_id, **comp_config}
            for comp_id, comp_config in self.competencies.items()
        ]

    def get_meta_category(self, comp_id: str) -> str | None:
        """Get the meta-category for a competency."""
        for cat_id, cat_config in self.meta_categories.items():
            if comp_id in cat_config.get("competencies", []):
                return cat_id
        return None

    def get_meta_categories(self) -> dict:
        """Get all meta-categories."""
        return self.meta_categories


def map_work_item_to_competencies(
    item: dict,
    mapper: CompetencyMapper | None = None,
) -> dict[str, int]:
    """Convenience function to map a work item to competencies.

    Args:
        item: Work item dict with source, type, title, etc.
        mapper: Optional CompetencyMapper instance

    Returns:
        Dict of competency_id -> points
    """
    if mapper is None:
        mapper = CompetencyMapper()
    return mapper.map_event(item)


async def map_with_ai_fallback(
    item: dict,
    mapper: CompetencyMapper | None = None,
    llm_client: Any = None,
) -> dict[str, int]:
    """Map work item with AI fallback for ambiguous cases.

    Args:
        item: Work item dict
        mapper: Optional CompetencyMapper instance
        llm_client: Optional LLM client for AI analysis

    Returns:
        Dict of competency_id -> points
    """
    if mapper is None:
        mapper = CompetencyMapper()

    # First try rule-based mapping
    points = mapper.map_event(item)

    # If no matches and we have an LLM client, try AI
    if not points and llm_client:
        try:
            points = await _ai_classify(item, mapper, llm_client)
        except Exception as e:
            logger.warning(f"AI classification failed: {e}")

    return points


async def _ai_classify(
    item: dict,
    mapper: CompetencyMapper,
    llm_client: Any,
) -> dict[str, int]:
    """Use AI to classify a work item."""
    competencies = mapper.get_all_competencies()
    comp_descriptions = "\n".join(
        f"- {c['id']}: {c.get('name', '')} - {c.get('pse_goal', '')[:100]}"
        for c in competencies
    )

    prompt = f"""Classify this work item into PSE competencies.

Work Item:
- Title: {item.get('title', '')}
- Type: {item.get('type', '')}
- Source: {item.get('source', '')}
- Labels: {', '.join(item.get('labels', []))}

Available Competencies:
{comp_descriptions}

Return a JSON object with competency IDs as keys and points (1-5) as values.
Only include competencies that clearly apply. Example: {{"technical_contribution": 3, "collaboration": 2}}
"""

    try:
        response = await llm_client.complete(prompt)
        # Parse JSON from response
        match = re.search(r"\{[^}]+\}", response)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.error(f"AI classification error: {e}")

    return {}
