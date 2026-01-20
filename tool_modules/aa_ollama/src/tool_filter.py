"""Hybrid tool filter with 4-layer architecture.

Implements the core filtering logic:
1. Core tools (always included)
2. Persona baseline (dynamically from persona YAML files)
3. Skill tools (dynamic from YAML)
4. NPU classification (with fallback)

This module is workspace-aware: cache keys include workspace_uri to ensure
different Cursor chats/workspaces have separate cache entries.
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import yaml

from .cache import FilterCache
from .categories import CORE_CATEGORIES, TOOL_CATEGORIES, format_categories_for_prompt
from .client import OllamaClient, get_available_client, warmup_model
from .context_enrichment import enrich_context
from .skill_discovery import SkillToolDiscovery, detect_skill
from .stats import get_stats, save_stats
from .tool_registry import load_registry

if TYPE_CHECKING:
    pass  # Context import removed - not currently used

logger = logging.getLogger(__name__)

# Project paths
PROJECT_DIR = Path(__file__).parents[4]  # tool_modules/aa_ollama/src -> project root
PERSONAS_DIR = PROJECT_DIR / "personas"

# Cache for loaded persona configs
_persona_cache: dict[str, dict] = {}


def _load_persona_config(persona_name: str) -> dict:
    """Load persona configuration from YAML file with caching.

    Args:
        persona_name: Name of the persona (e.g., "developer", "devops")

    Returns:
        Persona config dict with 'tools', 'skills', etc. or empty dict if not found
    """
    if persona_name in _persona_cache:
        return _persona_cache[persona_name]

    persona_file = PERSONAS_DIR / f"{persona_name}.yaml"
    if not persona_file.exists():
        logger.warning(f"Persona file not found: {persona_file}")
        return {}

    try:
        with open(persona_file) as f:
            config = yaml.safe_load(f) or {}
            _persona_cache[persona_name] = config
            return config
    except Exception as e:
        logger.error(f"Failed to load persona config {persona_name}: {e}")
        return {}


def _get_persona_tool_modules(persona_name: str) -> list[str]:
    """Get tool modules for a persona from its YAML file.

    Args:
        persona_name: Name of the persona

    Returns:
        List of tool module names (e.g., ["workflow", "git_basic", "jira_basic"])
    """
    config = _load_persona_config(persona_name)
    return config.get("tools", [])


def clear_persona_cache() -> None:
    """Clear the persona config cache (useful for testing or hot-reload)."""
    _persona_cache.clear()


class HybridToolFilter:
    """4-layer tool filtering with graceful degradation.

    Layers:
    1. Core tools - Always included (skills, session, memory)
    2. Persona baseline - Dynamically loaded from persona YAML files
    3. Skill tools - Dynamically discovered from YAML
    4. NPU classification - Semantic understanding with fallback

    Fallback strategies when NPU unavailable:
    - keyword_match: Regex/keyword matching
    - all_tools: Return all tools (original behavior)
    """

    FALLBACK_STRATEGIES = ["keyword_match", "all_tools"]

    # Fast patterns for common requests (bypass NPU)
    FAST_PATTERNS = [
        (re.compile(r"MR\s*#?(\d+)|!(\d+)", re.I), ["gitlab_mr_read", "gitlab_ci"]),
        (re.compile(r"AAP-\d+", re.I), ["jira_read"]),
        (re.compile(r"\bpods?\b|\bcontainers?\b", re.I), ["k8s_read"]),
        (re.compile(r"ephemeral|bonfire", re.I), ["ephemeral"]),
        (re.compile(r"alert|firing", re.I), ["alerts"]),
        (re.compile(r"pipeline|ci\s+status|build\s+status", re.I), ["gitlab_ci"]),
        (re.compile(r"\bcommit\b|\bpush\b|\bbranch\b", re.I), ["git_write"]),
        (re.compile(r"git\s+status|git\s+log|git\s+diff", re.I), ["git_read"]),
        (re.compile(r"logs?\b|kibana", re.I), ["logs"]),
        (re.compile(r"metrics?|prometheus|grafana", re.I), ["metrics"]),
        (re.compile(r"quay|image|digest", re.I), ["quay"]),
    ]

    # Persona detection patterns - keywords that suggest a specific persona
    # Order matters: first match wins
    PERSONA_PATTERNS = [
        # Incident persona - alerts, outages, production issues
        (re.compile(r"\balert|firing|outage|incident|pagerduty|on-?call|production\s+issue", re.I), "incident"),
        # DevOps persona - deployments, k8s, ephemeral, infrastructure
        (re.compile(r"\bdeploy|ephemeral|bonfire|namespace|pods?|k8s|kubernetes|cluster|stage|prod\b", re.I), "devops"),
        # Release persona - shipping, releases, konflux, quay
        (re.compile(r"\brelease|ship|konflux|quay|image\s+tag|promote|rollout", re.I), "release"),
        # Developer persona - default, code, PRs, reviews
        (re.compile(r"\bcode|review|pr\b|merge\s+request|lint|test|refactor", re.I), "developer"),
    ]

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the filter.

        Args:
            config_path: Path to config.json (defaults to project root)
        """
        if config_path is None:
            config_path = Path(__file__).parents[4] / "config.json"

        self.config = self._load_config(config_path)
        self.registry = load_registry()
        self.skill_discovery = SkillToolDiscovery()
        self.stats = get_stats()

        # Initialize cache
        cache_config = self.config.get("tool_filtering", {}).get("cache", {})
        self.cache = FilterCache(
            max_size=cache_config.get("max_size", 500),
            ttl_seconds=cache_config.get("ttl_seconds", 300),
        )
        self.cache_enabled = cache_config.get("enabled", True)

        # Initialize NPU client
        self.inference_client: Optional[OllamaClient] = None
        self._init_inference_client()

        # Fallback strategy
        self.fallback_strategy = self.config.get("tool_filtering", {}).get("fallback_strategy", "keyword_match")

    def _load_config(self, path: Path) -> dict:
        """Load config.json."""
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load config: {e}")
        return {}

    def _init_inference_client(self) -> None:
        """Initialize inference client with fallback chain."""
        npu_config = self.config.get("tool_filtering", {}).get("npu", {})
        if not npu_config.get("enabled", True):
            logger.info("NPU inference disabled in config")
            return

        self.inference_client = get_available_client(
            primary=npu_config.get("instance", "npu"),
            fallback_chain=npu_config.get("fallback_chain", ["igpu", "nvidia", "cpu"]),
        )

        if self.inference_client:
            logger.info(f"Inference client initialized: {self.inference_client.name}")
            # Warm up the model to avoid cold start latency
            if npu_config.get("warmup", True):
                warmup_model(self.inference_client.name)
        else:
            logger.warning("No inference instances available")

    def _get_baseline_categories(self, persona: str) -> list[str]:
        """Get baseline tool modules from persona YAML file.

        Dynamically loads the persona's tool modules from its YAML config,
        ensuring the filter always uses the same source of truth as persona_load().

        Args:
            persona: Persona name (e.g., "developer", "devops")

        Returns:
            List of tool module names (e.g., ["workflow", "git_basic", "jira_basic"])
        """
        modules = _get_persona_tool_modules(persona)
        if modules:
            logger.debug(f"Loaded {len(modules)} tool modules for persona '{persona}': {modules}")
        else:
            logger.warning(f"No tool modules found for persona '{persona}', using empty baseline")
        return modules

    def _detect_persona(self, message: str, default_persona: str = "developer") -> tuple[str, str]:
        """Auto-detect persona from message keywords.

        Args:
            message: User message
            default_persona: Fallback persona if no patterns match

        Returns:
            Tuple of (persona_name, detection_reason)
        """
        for pattern, persona in self.PERSONA_PATTERNS:
            match = pattern.search(message)
            if match:
                matched_text = match.group(0)
                return persona, f"keyword '{matched_text}'"

        return default_persona, "default"

    def _fast_match(self, message: str) -> list[str]:
        """Fast regex-based category matching.

        Args:
            message: User message

        Returns:
            List of matched category names
        """
        matched = set()
        for pattern, categories in self.FAST_PATTERNS:
            if pattern.search(message):
                matched.update(categories)
        return list(matched)

    def _is_ambiguous(self, message: str, fast_matches: list[str]) -> bool:
        """Check if message needs NPU classification.

        Args:
            message: User message
            fast_matches: Categories from fast matching

        Returns:
            True if NPU classification is needed
        """
        # If fast patterns matched, not ambiguous
        if fast_matches:
            return False

        # Short messages are often ambiguous
        words = message.split()
        if len(words) < 3:
            return True

        # Questions are often ambiguous
        if message.strip().endswith("?"):
            return True

        return True  # Default to NPU for complex messages

    def _npu_classify(
        self,
        message: str,
        already_included: set[str],
    ) -> list[str]:
        """Use NPU to classify additional categories needed.

        Args:
            message: User message
            already_included: Categories already included

        Returns:
            List of additional category names
        """
        if not self.inference_client or not self.inference_client.is_available():
            logger.warning("NPU not available for classification")
            return []

        # Build prompt excluding already-included categories
        available_categories = [cat for cat in TOOL_CATEGORIES.keys() if cat not in already_included]

        npu_config = self.config.get("tool_filtering", {}).get("npu", {})
        max_categories = npu_config.get("max_categories", 3)

        # Format categories for prompt
        categories_str = format_categories_for_prompt(already_included)

        prompt = f"""What additional tool categories are needed for this request?

Already included: {', '.join(already_included)}

Available categories:
{categories_str}

Request: "{message[:200]}"

Reply with 0-{max_categories} category names separated by commas, or NONE if no additional categories needed:"""

        try:
            start_time = time.perf_counter()
            result = self.inference_client.generate(
                prompt=prompt,
                temperature=0,
                max_tokens=50,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(f"NPU classification took {elapsed_ms:.0f}ms: {result}")

            # Parse response
            if "NONE" in result.upper():
                return []

            # Extract category names from response
            categories = []
            result_lower = result.lower()
            for cat in available_categories:
                if cat.lower() in result_lower or cat.lower().replace("_", " ") in result_lower:
                    categories.append(cat)
                    if len(categories) >= max_categories:
                        break

            return categories

        except Exception as e:
            logger.error(f"NPU classification failed: {e}")
            self.stats.record_npu_timeout()
            return []

    def _classify_with_fallback(
        self,
        message: str,
        already_included: set[str],
        persona: str,
    ) -> tuple[list[str], str]:
        """Classify with NPU, falling back gracefully if unavailable.

        Args:
            message: User message
            already_included: Categories already included
            persona: Active persona

        Returns:
            Tuple of (category list, method used)
        """
        # Try NPU/inference if available
        if self.inference_client and self.inference_client.is_available():
            try:
                categories = self._npu_classify(message, already_included)
                return categories, "npu"
            except Exception as e:
                logger.warning(f"NPU classification failed: {e}")

        # Fallback strategies
        if self.fallback_strategy == "keyword_match":
            categories = self.registry.keyword_match(message)
            categories = [c for c in categories if c not in already_included]
            return categories[:3], "keyword_fallback"

        elif self.fallback_strategy == "all_tools":
            return list(TOOL_CATEGORIES.keys()), "all_tools"

        return [], "none"

    def filter(
        self,
        message: str,
        persona: str = "developer",
        detected_skill: Optional[str] = None,
        auto_detect_persona: bool = True,
        workspace_uri: str = "default",
    ) -> dict:
        """4-layer filtering with graceful degradation.

        Args:
            message: User message to filter tools for
            persona: Active persona (developer, devops, incident, release)
                     Used as default if auto_detect_persona is True
            detected_skill: Pre-detected skill name (optional)
            auto_detect_persona: If True, detect persona from message keywords
            workspace_uri: Workspace URI for cache isolation

        Returns:
            Dict with:
                - tools: list of tool names
                - tool_count: number of tools
                - total_available: total tools available
                - reduction_pct: percentage reduction
                - methods: list of methods used
                - inference_available: whether local inference was used
                - persona: persona used
                - persona_auto_detected: whether persona was auto-detected
                - persona_detection_reason: why this persona was chosen
                - skill_detected: detected skill or None
                - latency_ms: filter latency
                - workspace_uri: workspace used for cache
        """
        start_time = time.perf_counter()

        # === Auto-detect persona from message ===
        persona_auto_detected = False
        persona_detection_reason = "passed_in"

        # If persona is empty/None, force auto-detection
        if not persona:
            persona = "developer"  # Default fallback
            auto_detect_persona = True

        if auto_detect_persona:
            detected_persona, detection_reason = self._detect_persona(message, persona)
            if detected_persona != persona:
                logger.info(f"Auto-detected persona: {detected_persona} (was {persona}) - {detection_reason}")
                persona = detected_persona
                persona_auto_detected = True
                persona_detection_reason = detection_reason
            elif detection_reason != "default":
                # Same persona but detected via keyword
                persona_auto_detected = True  # Mark as auto-detected even if same as default
                persona_detection_reason = detection_reason

        # Check cache first (after persona detection) - workspace-aware
        if self.cache_enabled:
            cached_tools = self.cache.get(message, persona, workspace_uri)
            if cached_tools is not None:
                self.stats.record_cache_hit()
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                return {
                    "tools": cached_tools,
                    "tool_count": len(cached_tools),
                    "total_available": len(TOOL_CATEGORIES),
                    "reduction_pct": round((1 - len(cached_tools) / 222) * 100, 1),
                    "methods": ["cache_hit"],
                    "inference_available": self.inference_client is not None,
                    "persona": persona,
                    "persona_auto_detected": persona_auto_detected,
                    "persona_detection_reason": persona_detection_reason,
                    "skill_detected": detected_skill,
                    "latency_ms": round(elapsed_ms, 1),
                    "message_preview": message[:50],
                    "workspace_uri": workspace_uri,
                }
            self.stats.record_cache_miss()

        categories = set()
        explicit_tools = set()
        methods_used = []

        # Track detailed context for each layer
        context_details = {
            "core": {"categories": [], "tools": []},
            "persona": {
                "name": persona,
                "auto_detected": persona_auto_detected,
                "detection_reason": persona_detection_reason,
                "categories": [],
                "tools": [],
            },
            "skill": {"name": None, "description": None, "tools": [], "inputs": [], "memory_ops": []},
            "fast_match": {"patterns": [], "categories": []},
            "npu": {"method": None, "categories": [], "tools": []},
        }

        # === LAYER 1: Core Tools (always) ===
        core_cats = self.config.get("tool_filtering", {}).get("core_tools", {}).get("categories", CORE_CATEGORIES)
        categories.update(core_cats)
        methods_used.append("layer1_core")
        context_details["core"]["categories"] = list(core_cats)
        context_details["core"]["tools"] = self.registry.get_tools_for_categories(list(core_cats))

        # === LAYER 2: Persona Baseline (from config.json) ===
        baseline = self._get_baseline_categories(persona)
        categories.update(baseline)
        methods_used.append("layer2_persona")
        context_details["persona"]["categories"] = baseline
        context_details["persona"]["tools"] = self.registry.get_tools_for_categories(baseline)

        # === LAYER 3: Skill Tool Discovery (dynamic from YAML) ===
        if not detected_skill:
            detected_skill = detect_skill(message)

        if detected_skill:
            skill_tools = self.skill_discovery.discover_tools(detected_skill)
            # Remove the compute block flag - we don't need NPU for tool filtering
            # when we already have the skill's explicit tools
            skill_tools = skill_tools - {"__has_compute_block__"}
            explicit_tools.update(skill_tools)
            methods_used.append("layer3_skill")

            # Get skill metadata for context
            skill_meta = self.skill_discovery.get_skill_metadata(detected_skill)
            context_details["skill"]["name"] = detected_skill
            context_details["skill"]["description"] = skill_meta.get("description", "")
            context_details["skill"]["tools"] = list(skill_tools)
            context_details["skill"]["inputs"] = skill_meta.get("inputs", [])
            context_details["skill"]["memory_ops"] = skill_meta.get("memory_ops", {"reads": [], "writes": []})

        # === Fast Path: Regex matching ===
        fast_matches = self._fast_match(message)
        if fast_matches:
            categories.update(fast_matches)
            methods_used.append("fast_path")
            context_details["fast_match"]["categories"] = fast_matches
            context_details["fast_match"]["tools"] = self.registry.get_tools_for_categories(fast_matches)

        # === LAYER 4: NPU Classification (with fallback) ===
        # Only use NPU if no skill detected AND message is ambiguous
        # This saves ~8 seconds when a skill is detected
        if not detected_skill and self._is_ambiguous(message, fast_matches):
            npu_categories, npu_method = self._classify_with_fallback(message, categories, persona)
            categories.update(npu_categories)
            methods_used.append(f"layer4_{npu_method}")
            context_details["npu"]["method"] = npu_method
            context_details["npu"]["categories"] = npu_categories
            context_details["npu"]["tools"] = self.registry.get_tools_for_categories(npu_categories)

        # === Combine all tools ===
        category_tools = self.registry.get_tools_for_categories(list(categories))
        all_tools = list(set(category_tools) | explicit_tools)

        # === Load context enrichment ===
        # Skip semantic search for speed - it adds 4+ seconds on first call
        # The tool list is already filtered; semantic search is for extra context
        enrichment = enrich_context(
            persona=persona,
            detected_skill=detected_skill,
            tool_names=all_tools,
            message=message,
            include_semantic_search=False,  # Disabled for speed
        )
        context_details["memory_state"] = enrichment["memory_state"]
        context_details["environment"] = enrichment["environment"]
        context_details["learned_patterns"] = enrichment["learned_patterns"]
        context_details["session_log"] = enrichment["session_log"]
        context_details["persona_prompt"] = enrichment["persona_prompt"]
        context_details["semantic_knowledge"] = enrichment.get("semantic_knowledge", [])

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Cache result (tools only, not full context) - workspace-aware
        if self.cache_enabled:
            self.cache.set(message, persona, all_tools, workspace_uri)

        result = {
            "tools": all_tools,
            "tool_count": len(all_tools),
            "total_available": 222,  # Approximate total
            "reduction_pct": round((1 - len(all_tools) / 222) * 100, 1),
            "methods": methods_used,
            "inference_available": self.inference_client is not None,
            "persona": persona,
            "persona_auto_detected": persona_auto_detected,
            "persona_detection_reason": persona_detection_reason,
            "skill_detected": detected_skill,
            "latency_ms": round(elapsed_ms, 1),
            "message_preview": message[:50],
            "context": context_details,  # Detailed breakdown for inspector
            "workspace_uri": workspace_uri,  # Workspace used for cache isolation
        }

        # Record stats and persist to disk
        self.stats.record(result)
        save_stats()

        logger.info(
            f"Tool filter: {len(all_tools)} tools ({result['reduction_pct']}% reduction) "
            f"in {elapsed_ms:.0f}ms via {', '.join(methods_used)}"
        )

        return result

    def clear_cache(self) -> int:
        """Clear the filter cache.

        Returns:
            Number of entries cleared
        """
        count = self.cache.clear()
        self.skill_discovery.clear_cache()
        return count

    def get_stats(self) -> dict:
        """Get filter statistics.

        Returns:
            Dict with filter and cache statistics
        """
        return {
            "filter": self.stats.to_dict(),
            "cache": self.cache.get_stats(),
            "inference_available": self.inference_client is not None,
            "inference_instance": self.inference_client.name if self.inference_client else None,
            "fallback_strategy": self.fallback_strategy,
        }


# ==================== Convenience Functions ====================

_filter_instance: Optional[HybridToolFilter] = None


def get_filter() -> HybridToolFilter:
    """Get or create the filter instance."""
    global _filter_instance
    if _filter_instance is None:
        _filter_instance = HybridToolFilter()
    return _filter_instance


def filter_tools(
    message: str,
    persona: str = "developer",
    detected_skill: Optional[str] = None,
) -> list[str]:
    """Convenience function for tool filtering.

    Args:
        message: User message
        persona: Active persona
        detected_skill: Pre-detected skill (optional)

    Returns:
        List of tool names
    """
    result = get_filter().filter(message, persona, detected_skill)
    return result["tools"]


def filter_tools_detailed(
    message: str,
    persona: str = "developer",
    detected_skill: Optional[str] = None,
    workspace_uri: str = "default",
) -> dict:
    """Convenience function for detailed tool filtering.

    Args:
        message: User message
        persona: Active persona
        detected_skill: Pre-detected skill (optional)
        workspace_uri: Workspace URI for cache isolation

    Returns:
        Full filter result dict
    """
    return get_filter().filter(message, persona, detected_skill, workspace_uri=workspace_uri)
