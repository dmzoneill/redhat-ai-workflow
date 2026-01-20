# Local Inference Implementation Plan

## Executive Summary

**Goal:** Reduce Claude API token usage by 85-90% using local NPU-powered tool pre-filtering, with a comprehensive dashboard for monitoring and tuning.

| Metric | Current | Target |
|--------|---------|--------|
| Tools per API call | 222 | 15-35 |
| Tokens per API call | ~29,000 | ~2,000-4,000 |
| Token reduction | - | 85-90% |
| Monthly cost (1000 calls) | $87 | $11 |
| NPU power consumption | - | 2-5W |

**Hardware:** Intel Core Ultra 7 268V with 4 Ollama instances (NPU, iGPU, NVIDIA, CPU)

---

## Part 1: Architecture

### 4-Layer Tool Filtering

```
User Message
      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: CORE TOOLS (Always included)                                      │
│                                                                             │
│  skills, session_start, memory_*                                            │
│  = ~5 tools, hardcoded, never filtered out                                  │
└─────────────────────────────────────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: PERSONA BASELINE (from config.json)                               │
│                                                                             │
│  Developer: + jira_read, gitlab_mr_read, gitlab_ci                          │
│  DevOps:    + k8s_read, alerts, ephemeral                                   │
│  Incident:  + alerts, k8s_read, logs, metrics                               │
│  Release:   + gitlab_mr_read, quay, konflux                                 │
│  = ~12-17 tools per persona, loaded at session start                        │
└─────────────────────────────────────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: SKILL TOOLS (dynamic from YAML)                                   │
│                                                                             │
│  When skill detected, parse YAML → extract tools                            │
│  test_mr_ephemeral: + bonfire_*, quay_*, kubectl_*                          │
│  review_pr: + gitlab_mr_diff, lint tools                                    │
│  = +5-15 tools, discovered at runtime, <10ms                                │
└─────────────────────────────────────────────────────────────────────────────┘
      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  LAYER 4: NPU CLASSIFIED (semantic understanding)                           │
│                                                                             │
│  When ambiguous OR skill has compute blocks                                 │
│  "debug billing job" → + k8s_read, logs, metrics                            │
│  = +5-10 tools, ~400ms, 2-5W                                                │
│                                                                             │
│  FALLBACK: If NPU unavailable → keyword_match or expanded_baseline          │
└─────────────────────────────────────────────────────────────────────────────┘
      ↓
   Final Tool List: 17-40 tools (vs 222)
```

### Fallback Strategy

When local inference is unavailable:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  INFERENCE AVAILABILITY CHECK                                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Try Primary Instance (NPU)                                              │
│     ├─ Available? → Use NPU for Layer 4 classification                     │
│     └─ Offline?   → Try fallback chain                                     │
│                                                                             │
│  2. Fallback Chain: iGPU → NVIDIA → CPU                                    │
│     ├─ Any available? → Use that instance                                  │
│     └─ All offline?   → GRACEFUL DEGRADATION                               │
│                                                                             │
│  3. Graceful Degradation (No Local Inference):                             │
│     ├─ Layers 1-3: Still work (baseline + skill discovery)                 │
│     ├─ Layer 4: Use fallback_strategy from config:                         │
│     │   • "keyword_match" - Regex/keyword matching (~25-35 tools)          │
│     │   • "expanded_baseline" - Add common categories (~30-40 tools)       │
│     │   • "all_tools" - Return all 222 tools (original behavior)           │
│     └─ Dashboard shows: ⚠️ "Inference degraded"                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 2: Configuration

### config.json Schema

```json
{
  "tool_filtering": {
    "enabled": true,

    "core_tools": {
      "description": "Always included, every request",
      "categories": ["skills", "session", "memory"]
    },

    "persona_baselines": {
      "developer": {
        "categories": ["jira_read", "gitlab_mr_read", "gitlab_ci"],
        "description": "Core developer tools - always available"
      },
      "devops": {
        "categories": ["k8s_read", "alerts", "ephemeral"],
        "description": "Core devops tools - always available"
      },
      "incident": {
        "categories": ["alerts", "k8s_read", "logs", "metrics"],
        "description": "Core incident response tools"
      },
      "release": {
        "categories": ["gitlab_mr_read", "gitlab_ci", "quay", "konflux"],
        "description": "Core release tools"
      }
    },

    "fallback_strategy": "keyword_match",

    "expanded_baseline": {
      "description": "Categories to add when NPU unavailable (if fallback_strategy=expanded_baseline)",
      "developer": ["k8s_read", "git_read", "git_write"],
      "devops": ["logs", "metrics", "quay"],
      "incident": ["jira_write", "gitlab_ci"],
      "release": ["jira_write", "git_write"]
    },

    "npu": {
      "enabled": true,
      "instance": "npu",
      "model": "qwen2.5:0.5b",
      "fallback_chain": ["igpu", "nvidia", "cpu"],
      "timeout_ms": 500,
      "max_categories": 3,
      "max_retries": 1
    },

    "cache": {
      "enabled": true,
      "ttl_seconds": 300,
      "max_size": 500
    }
  },

  "ollama": {
    "instances": {
      "npu": {
        "host": "http://localhost:11434",
        "default_model": "qwen2.5:0.5b",
        "power_watts": "2-5W"
      },
      "igpu": {
        "host": "http://localhost:11435",
        "default_model": "llama3.2:3b",
        "power_watts": "8-15W"
      },
      "nvidia": {
        "host": "http://localhost:11436",
        "default_model": "llama3:7b",
        "power_watts": "40-60W"
      },
      "cpu": {
        "host": "http://localhost:11437",
        "default_model": "qwen2.5:0.5b",
        "power_watts": "15-35W"
      }
    }
  }
}
```

### Tool Category Definitions

```python
TOOL_CATEGORIES = {
    # === JIRA ===
    "jira_read": {
        "description": "View and search Jira issues",
        "keywords": ["issue", "ticket", "aap-", "jira", "story", "bug", "task"],
        "tools": ["jira_view_issue", "jira_search", "jira_list_issues",
                  "jira_my_issues", "jira_list_blocked"],
        "priority": 9,
    },
    "jira_write": {
        "description": "Update Jira issues - status, comments, assignments",
        "keywords": ["update issue", "set status", "assign", "comment on"],
        "tools": ["jira_set_status", "jira_add_comment", "jira_assign",
                  "jira_set_priority", "jira_transition"],
        "priority": 6,
    },
    "jira_create": {
        "description": "Create new Jira issues",
        "keywords": ["create issue", "new story", "new bug", "file ticket"],
        "tools": ["jira_create_issue", "jira_clone_issue"],
        "priority": 5,
    },

    # === GITLAB MR ===
    "gitlab_mr_read": {
        "description": "View merge requests - details, diff, comments",
        "keywords": ["mr", "merge request", "!", "pull request", "pr"],
        "tools": ["gitlab_mr_view", "gitlab_mr_list", "gitlab_mr_diff",
                  "gitlab_mr_comments", "gitlab_mr_sha", "gitlab_commit_list"],
        "priority": 9,
    },
    "gitlab_mr_write": {
        "description": "Create and update merge requests",
        "keywords": ["create mr", "update mr", "approve", "comment"],
        "tools": ["gitlab_mr_create", "gitlab_mr_update", "gitlab_mr_approve",
                  "gitlab_mr_comment", "gitlab_mr_close"],
        "priority": 6,
    },

    # === GITLAB CI ===
    "gitlab_ci": {
        "description": "CI/CD pipelines - status, logs, jobs",
        "keywords": ["pipeline", "ci", "build", "job", "failed", "passed"],
        "tools": ["gitlab_ci_status", "gitlab_ci_view", "gitlab_ci_list",
                  "gitlab_ci_trace", "gitlab_ci_lint"],
        "priority": 8,
    },

    # === GIT ===
    "git_read": {
        "description": "View git status, log, diff",
        "keywords": ["git status", "git log", "git diff", "commit history"],
        "tools": ["git_status", "git_log", "git_diff", "git_show", "git_blame"],
        "priority": 7,
    },
    "git_write": {
        "description": "Git operations - commit, push, branch",
        "keywords": ["commit", "push", "branch", "checkout", "merge", "rebase"],
        "tools": ["git_commit", "git_push", "git_pull", "git_branch_create",
                  "git_checkout", "git_merge", "git_rebase", "git_stash"],
        "priority": 6,
    },

    # === KUBERNETES ===
    "k8s_read": {
        "description": "View Kubernetes resources - pods, logs, events",
        "keywords": ["pod", "container", "k8s", "kubernetes", "logs", "deployment"],
        "tools": ["kubectl_get_pods", "kubectl_logs", "kubectl_describe",
                  "kubectl_get_deployments", "kubectl_get_events"],
        "priority": 7,
    },
    "k8s_write": {
        "description": "Modify Kubernetes resources",
        "keywords": ["delete pod", "scale", "restart"],
        "tools": ["kubectl_delete", "kubectl_scale", "kubectl_rollout"],
        "priority": 4,
    },

    # === EPHEMERAL ===
    "ephemeral": {
        "description": "Ephemeral environments - reserve, deploy, release",
        "keywords": ["ephemeral", "bonfire", "reserve", "namespace", "test mr"],
        "tools": ["bonfire_namespace_reserve", "bonfire_namespace_list",
                  "bonfire_namespace_release", "bonfire_deploy"],
        "priority": 7,
    },

    # === QUAY ===
    "quay": {
        "description": "Container images - check, list tags",
        "keywords": ["image", "quay", "container", "tag", "sha"],
        "tools": ["quay_check_image", "quay_list_tags", "quay_get_manifest"],
        "priority": 6,
    },

    # === MONITORING ===
    "alerts": {
        "description": "Alerts - view firing alerts, silences",
        "keywords": ["alert", "firing", "critical", "warning", "silence"],
        "tools": ["alertmanager_list_alerts", "alertmanager_list_silences"],
        "priority": 8,
    },
    "logs": {
        "description": "Log searching - Kibana, application logs",
        "keywords": ["logs", "kibana", "error", "exception", "trace"],
        "tools": ["kibana_search_logs", "kibana_get_errors"],
        "priority": 7,
    },
    "metrics": {
        "description": "Prometheus metrics and queries",
        "keywords": ["metrics", "prometheus", "grafana", "cpu", "memory"],
        "tools": ["prometheus_query", "prometheus_range_query"],
        "priority": 6,
    },

    # === SKILLS (Always available) ===
    "skills": {
        "description": "Workflow automation skills",
        "keywords": ["skill", "workflow", "automate"],
        "tools": ["skill_run", "skill_list"],
        "priority": 10,
    },
}
```

---

## Part 3: Implementation Phases

### Phase 1: Create `aa_ollama` Tool Module (1-2 hours)

**Purpose:** Foundation for all local inference integration

#### Directory Structure

```
tool_modules/aa_ollama/
├── pyproject.toml
├── README.md
└── src/
    ├── __init__.py
    ├── tools_basic.py      # MCP tools for direct Ollama access
    ├── client.py           # Ollama HTTP client with fallback
    ├── instances.py        # Instance configuration (NPU/iGPU/NVIDIA/CPU)
    ├── tool_filter.py      # HybridToolFilter implementation
    ├── skill_discovery.py  # Dynamic skill YAML parsing
    ├── categories.py       # Tool category definitions
    ├── stats.py            # Statistics collection
    └── npu_helpers.py      # NPU-specific helper functions
```

#### Key Files

**`instances.py`**

```python
"""Ollama instance configuration."""

from dataclasses import dataclass
import os

@dataclass
class OllamaInstance:
    name: str
    host: str
    default_model: str
    power_watts: str
    best_for: list[str]

INSTANCES = {
    "npu": OllamaInstance(
        name="npu",
        host=os.getenv("OLLAMA_NPU_HOST", "http://localhost:11434"),
        default_model="qwen2.5:0.5b",
        power_watts="2-5W",
        best_for=["classification", "extraction", "simple_queries"]
    ),
    "igpu": OllamaInstance(
        name="igpu",
        host=os.getenv("OLLAMA_IGPU_HOST", "http://localhost:11435"),
        default_model="llama3.2:3b",
        power_watts="8-15W",
        best_for=["balanced_tasks", "medium_complexity"]
    ),
    "nvidia": OllamaInstance(
        name="nvidia",
        host=os.getenv("OLLAMA_NVIDIA_HOST", "http://localhost:11436"),
        default_model="llama3:7b",
        power_watts="40-60W",
        best_for=["complex_reasoning", "code_generation"]
    ),
    "cpu": OllamaInstance(
        name="cpu",
        host=os.getenv("OLLAMA_CPU_HOST", "http://localhost:11437"),
        default_model="qwen2.5:0.5b",
        power_watts="15-35W",
        best_for=["fallback", "testing"]
    ),
}

def get_instance(name: str = "npu") -> OllamaInstance:
    """Get instance by name, default to NPU."""
    return INSTANCES.get(name, INSTANCES["npu"])
```

**`client.py`**

```python
"""Ollama HTTP client with retry, timeout, and fallback handling."""

import requests
import logging
from typing import Optional
from .instances import get_instance, INSTANCES

logger = logging.getLogger(__name__)

class OllamaClient:
    """HTTP client for Ollama API with fallback support."""

    def __init__(self, instance: str = "npu", timeout: int = 30, fallback_chain: list[str] = None):
        self.instance = get_instance(instance)
        self.timeout = timeout
        self.fallback_chain = fallback_chain or []
        self._available: Optional[bool] = None

    @property
    def host(self) -> str:
        return self.instance.host

    @property
    def default_model(self) -> str:
        return self.instance.default_model

    def is_available(self, force_check: bool = False) -> bool:
        """Check if instance is online."""
        if self._available is not None and not force_check:
            return self._available
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=2)
            self._available = r.status_code == 200
        except:
            self._available = False
        return self._available

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        stream: bool = False,
        temperature: float = 0,
        max_tokens: int = 100,
    ) -> str:
        """Generate text completion."""
        model = model or self.default_model

        response = requests.post(
            f"{self.host}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            },
            timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["response"]

    def classify(
        self,
        text: str,
        categories: list[str],
        max_text_length: int = 200,
    ) -> Optional[str]:
        """Classify text into one of the categories."""
        prompt = f"""Classify into ONE of: {', '.join(categories)}

Text: {text[:max_text_length]}

Category:"""

        try:
            result = self.generate(prompt, max_tokens=20, temperature=0)
            result_lower = result.strip().lower()

            for cat in categories:
                if cat.lower() in result_lower:
                    return cat

            return categories[-1]  # Default fallback

        except Exception as e:
            logger.error(f"Classification failed: {e}")
            return None


def get_available_client(
    primary: str = "npu",
    fallback_chain: list[str] = None
) -> Optional[OllamaClient]:
    """Get first available client from primary + fallback chain."""
    fallback_chain = fallback_chain or ["igpu", "nvidia", "cpu"]
    instances_to_try = [primary] + [f for f in fallback_chain if f != primary]

    for instance_name in instances_to_try:
        try:
            client = OllamaClient(instance=instance_name, timeout=2)
            if client.is_available():
                logger.info(f"Using {instance_name} for inference")
                return client
            else:
                logger.warning(f"{instance_name} not available, trying next...")
        except Exception as e:
            logger.warning(f"Failed to connect to {instance_name}: {e}")

    logger.warning("No inference instances available")
    return None
```

#### Deliverables

- [ ] `aa_ollama` module structure created
- [ ] `OllamaClient` class with generate/classify methods
- [ ] Instance configuration with environment variable overrides
- [ ] Fallback chain support
- [ ] Basic MCP tools: `ollama_generate`, `ollama_classify`, `ollama_status`
- [ ] Unit tests for client

---

### Phase 2: Build Tool Registry (2-3 hours)

**Purpose:** Create a structured registry of all tools with category metadata

#### Key Components

```python
from dataclasses import dataclass, field

@dataclass
class ToolCategory:
    """A category of related tools."""
    name: str
    description: str
    keywords: list[str]
    tools: list[str]
    priority: int = 5  # 1-10, higher = more likely to be selected

@dataclass
class ToolRegistry:
    """Registry of all tools organized by category."""
    categories: dict[str, ToolCategory] = field(default_factory=dict)

    def get_tools_for_categories(self, category_names: list[str]) -> list[str]:
        """Get all tools for given categories."""
        tools = set()
        for name in category_names:
            if name in self.categories:
                tools.update(self.categories[name].tools)
        return list(tools)

    def keyword_match(self, text: str) -> list[str]:
        """Match text against category keywords."""
        text_lower = text.lower()
        matched = []
        for name, cat in self.categories.items():
            for keyword in cat.keywords:
                if keyword.lower() in text_lower:
                    matched.append(name)
                    break
        return matched

    def to_prompt_format(self) -> str:
        """Format categories for NPU prompt."""
        lines = []
        for name, cat in sorted(self.categories.items(), key=lambda x: -x[1].priority):
            lines.append(f"- {name}: {cat.description}")
        return "\n".join(lines)
```

#### Deliverables

- [ ] `ToolCategory` and `ToolRegistry` dataclasses
- [ ] Complete category definitions for all 222 tools
- [ ] `keyword_match()` method for fast matching
- [ ] `to_prompt_format()` for NPU classification
- [ ] JSON export for config.json integration

---

### Phase 3: Implement HybridToolFilter (3-4 hours)

**Purpose:** The core 4-layer filtering logic with fallback support

#### Skill Tool Discovery

```python
from pathlib import Path
import yaml
import logging

logger = logging.getLogger(__name__)

class SkillToolDiscovery:
    """Dynamically discover tools required by a skill from YAML."""

    def __init__(self, skills_dir: Path = Path("skills")):
        self.skills_dir = skills_dir
        self._cache: dict[str, set[str]] = {}

    def discover_tools(self, skill_name: str) -> set[str]:
        """Parse skill YAML and extract all tool references."""
        if skill_name in self._cache:
            return self._cache[skill_name]

        skill_path = self.skills_dir / f"{skill_name}.yaml"
        if not skill_path.exists():
            return set()

        with open(skill_path) as f:
            skill = yaml.safe_load(f)

        tools = set()
        for step in skill.get("steps", []):
            self._extract_tools_from_step(step, tools)

        self._cache[skill_name] = tools
        return tools

    def _extract_tools_from_step(self, step: dict, tools: set[str]) -> None:
        """Recursively extract tools from a step."""
        if "tool" in step:
            tools.add(step["tool"])
        if "tools" in step:
            tools.update(step["tools"])
        if "parallel" in step:
            for parallel_step in step["parallel"]:
                self._extract_tools_from_step(parallel_step, tools)
        for branch in ["then", "else"]:
            if branch in step:
                for sub_step in step[branch]:
                    self._extract_tools_from_step(sub_step, tools)
        if "compute" in step:
            tools.add("__has_compute_block__")
```

#### Skill Detection (Fast Regex)

```python
import re

SKILL_PATTERNS = {
    "test_mr_ephemeral": [
        re.compile(r"deploy.*mr|test.*mr|spin.*up.*mr", re.I),
        re.compile(r"ephemeral.*mr\s*\d+", re.I),
    ],
    "review_pr": [
        re.compile(r"review.*mr|review.*!\d+", re.I),
    ],
    "start_work": [
        re.compile(r"start.*work.*aap-\d+", re.I),
    ],
    "investigate_slack_alert": [
        re.compile(r"investigate.*alert|whats.*firing", re.I),
    ],
    "create_mr": [
        re.compile(r"create.*mr|open.*mr", re.I),
    ],
}

def detect_skill(message: str) -> str | None:
    """Fast skill detection using regex patterns."""
    for skill_name, patterns in SKILL_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(message):
                return skill_name
    return None
```

#### HybridToolFilter with Fallback

```python
class HybridToolFilter:
    """4-layer tool filtering with graceful degradation."""

    FALLBACK_STRATEGIES = ["keyword_match", "expanded_baseline", "all_tools"]

    FAST_PATTERNS = [
        (re.compile(r"MR\s*#?(\d+)|!(\d+)", re.I), ["gitlab_mr_read", "gitlab_ci"]),
        (re.compile(r"AAP-\d+", re.I), ["jira_read"]),
        (re.compile(r"\bpods?\b|\bcontainers?\b", re.I), ["k8s_read"]),
        (re.compile(r"ephemeral|bonfire", re.I), ["ephemeral"]),
        (re.compile(r"alert|firing", re.I), ["alerts"]),
    ]

    def __init__(self, config_path: Path = Path("config.json")):
        self.config = self._load_config(config_path)
        self.registry = load_registry()
        self.skill_discovery = SkillToolDiscovery()
        self.inference_client = self._init_inference_client()
        self.fallback_strategy = self.config.get("tool_filtering", {}).get(
            "fallback_strategy", "keyword_match"
        )
        self.stats = FilterStats()

    def _init_inference_client(self) -> Optional[OllamaClient]:
        """Initialize inference client with fallback chain."""
        npu_config = self.config.get("tool_filtering", {}).get("npu", {})
        if not npu_config.get("enabled", True):
            return None

        return get_available_client(
            primary=npu_config.get("instance", "npu"),
            fallback_chain=npu_config.get("fallback_chain", ["igpu", "nvidia", "cpu"])
        )

    def filter(
        self,
        message: str,
        persona: str = "developer",
        detected_skill: str | None = None,
    ) -> dict:
        """
        4-layer filtering with graceful degradation.

        Returns dict with:
            - tools: list of tool names
            - methods: list of methods used
            - inference_available: whether local inference was used
            - stats: filtering statistics
        """
        start_time = time.perf_counter()
        categories = set()
        explicit_tools = set()
        methods_used = []

        # === LAYER 1: Core Tools (always) ===
        core_cats = self.config.get("tool_filtering", {}).get("core_tools", {}).get("categories", ["skills"])
        categories.update(core_cats)
        methods_used.append("layer1_core")

        # === LAYER 2: Persona Baseline (from config.json) ===
        baseline = self._get_baseline_categories(persona)
        categories.update(baseline)
        methods_used.append("layer2_persona")

        # === LAYER 3: Skill Tool Discovery (dynamic from YAML) ===
        if not detected_skill:
            detected_skill = detect_skill(message)

        needs_npu = False
        if detected_skill:
            skill_tools = self.skill_discovery.discover_tools(detected_skill)
            if "__has_compute_block__" in skill_tools:
                skill_tools = skill_tools - {"__has_compute_block__"}
                needs_npu = True
            explicit_tools.update(skill_tools)
            methods_used.append("layer3_skill")

        # === Fast Path: Regex matching ===
        fast_matches = self._fast_match(message)
        if fast_matches:
            categories.update(fast_matches)
            methods_used.append("fast_path")

        # === LAYER 4: NPU Classification (with fallback) ===
        if needs_npu or (not detected_skill and not fast_matches):
            npu_categories, npu_method = self._classify_with_fallback(message, categories, persona)
            categories.update(npu_categories)
            methods_used.append(f"layer4_{npu_method}")

        # === Combine all tools ===
        category_tools = self.registry.get_tools_for_categories(list(categories))
        all_tools = list(set(category_tools) | explicit_tools)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        result = {
            "tools": all_tools,
            "tool_count": len(all_tools),
            "total_available": 222,
            "reduction_pct": round((1 - len(all_tools) / 222) * 100, 1),
            "methods": methods_used,
            "inference_available": self.inference_client is not None,
            "persona": persona,
            "skill_detected": detected_skill,
            "latency_ms": round(elapsed_ms, 1),
        }

        # Record stats
        self.stats.record(result)

        return result

    def _classify_with_fallback(
        self,
        message: str,
        already_included: set[str],
        persona: str,
    ) -> tuple[list[str], str]:
        """Classify with NPU, falling back gracefully if unavailable."""

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

        elif self.fallback_strategy == "expanded_baseline":
            expanded = self._get_expanded_baseline(persona)
            extra = [c for c in expanded if c not in already_included]
            return extra, "expanded_baseline"

        elif self.fallback_strategy == "all_tools":
            return list(TOOL_CATEGORIES.keys()), "all_tools"

        return [], "none"
```

#### Deliverables

- [ ] `SkillToolDiscovery` class with YAML parsing
- [ ] `detect_skill()` function with regex patterns
- [ ] `HybridToolFilter` class with 4-layer logic
- [ ] Fallback chain support
- [ ] Fast path regex patterns
- [ ] Result caching
- [ ] Statistics collection
- [ ] Unit tests

---

### Phase 4: Integrate into ClaudeAgent (1-2 hours)

**Purpose:** Wire up the filter to actual Claude API calls

```python
from tool_modules.aa_ollama.src.tool_filter import HybridToolFilter, detect_skill

class ClaudeAgent:
    def __init__(self, ...):
        ...
        self.tool_filter = HybridToolFilter()
        self.use_tool_filtering = True
        self.persona = "developer"

    async def process_message(self, message: str, ...) -> str:
        all_tools = self.tool_registry.list_tools()

        if self.use_tool_filtering:
            result = self.tool_filter.filter(
                message=message,
                persona=self.persona,
            )

            filtered_tools = [
                tool for tool in all_tools
                if tool["name"] in result["tools"]
            ]

            logger.info(
                f"Tool filtering: {len(all_tools)} → {len(filtered_tools)} tools "
                f"({result['reduction_pct']}% reduction, {result['latency_ms']}ms)"
            )
        else:
            filtered_tools = all_tools

        response = self.client.messages.create(
            model=self.model,
            tools=filtered_tools,
            messages=messages,
        )
```

#### Deliverables

- [ ] `ClaudeAgent` modified to use tool filtering
- [ ] Persona passed through from session
- [ ] Metrics tracking for filter effectiveness
- [ ] Toggle to enable/disable filtering
- [ ] Logging for debugging

---

### Phase 5: Statistics & Caching (1-2 hours)

**Purpose:** Optimize performance and track effectiveness

#### Statistics Collection

```python
@dataclass
class FilterStats:
    """Track filter effectiveness."""
    total_requests: int = 0
    by_persona: dict = field(default_factory=dict)
    latency_histogram: dict = field(default_factory=lambda: {
        "<10ms": 0, "10-100ms": 0, "100-500ms": 0, ">500ms": 0
    })
    cache_hits: int = 0
    cache_misses: int = 0
    npu_calls: int = 0
    npu_timeouts: int = 0
    recent_history: list = field(default_factory=list)

    def record(self, result: dict) -> None:
        """Record a filter result."""
        self.total_requests += 1

        # Update persona stats
        persona = result["persona"]
        if persona not in self.by_persona:
            self.by_persona[persona] = {
                "requests": 0, "tools": [],
                "tier1_only": 0, "tier2_skill": 0, "tier3_npu": 0
            }
        self.by_persona[persona]["requests"] += 1
        self.by_persona[persona]["tools"].append(result["tool_count"])

        # Update latency histogram
        latency = result["latency_ms"]
        if latency < 10:
            self.latency_histogram["<10ms"] += 1
        elif latency < 100:
            self.latency_histogram["10-100ms"] += 1
        elif latency < 500:
            self.latency_histogram["100-500ms"] += 1
        else:
            self.latency_histogram[">500ms"] += 1

        # Add to recent history (keep last 20)
        self.recent_history.append({
            "timestamp": datetime.now().isoformat(),
            **result
        })
        self.recent_history = self.recent_history[-20:]

    def to_dict(self) -> dict:
        """Export stats for dashboard."""
        return {
            "total_requests": self.total_requests,
            "by_persona": {
                name: {
                    "requests": stats["requests"],
                    "tools_min": min(stats["tools"]) if stats["tools"] else 0,
                    "tools_max": max(stats["tools"]) if stats["tools"] else 0,
                    "tools_mean": sum(stats["tools"]) / len(stats["tools"]) if stats["tools"] else 0,
                }
                for name, stats in self.by_persona.items()
            },
            "latency": self.latency_histogram,
            "cache_hit_rate": self.cache_hits / (self.cache_hits + self.cache_misses) if (self.cache_hits + self.cache_misses) > 0 else 0,
            "recent_history": self.recent_history,
        }
```

#### Cache Implementation

```python
@dataclass
class CacheEntry:
    tools: list[str]
    created_at: datetime
    hits: int = 0

class FilterCache:
    """LRU cache with TTL for tool filter results."""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl = timedelta(seconds=ttl_seconds)
        self._cache: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[list[str]]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if datetime.now() - entry.created_at > self.ttl:
            del self._cache[key]
            return None
        entry.hits += 1
        return entry.tools

    def set(self, key: str, tools: list[str]) -> None:
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
            del self._cache[oldest_key]
        self._cache[key] = CacheEntry(tools=tools, created_at=datetime.now())
```

#### Deliverables

- [ ] `FilterStats` class for tracking effectiveness
- [ ] `FilterCache` with LRU eviction and TTL
- [ ] Stats file persistence (`~/.config/aa-workflow/inference_stats.json`)
- [ ] Metrics export for dashboard

---

### Phase 6: Inference Dashboard (4-6 hours)

**Purpose:** Command Center tab for monitoring, testing, and tuning

#### Tab Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📊 Overview │ 🤖 Personas │ ⚡ Skills │ 🔧 Tools │ 🧠 Memory │ 🕐 Cron │   │
│  🔌 Services │ 🧪 Inference  ← NEW TAB                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Dashboard Sections

**1. Ollama Instance Status**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🖥️ Ollama Instances                                          [Refresh ↻]  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  🟢 NPU      │  │  🟢 iGPU     │  │  🟡 NVIDIA   │  │  ⚫ CPU      │    │
│  │  :11434     │  │  :11435     │  │  :11436     │  │  :11437     │    │
│  │  qwen2.5:0.5b│  │  llama3.2:3b│  │  llama3:7b  │  │  (offline)  │    │
│  │  2-5W ~400ms│  │  8-15W ~800ms│  │  40W ~300ms │  │  --         │    │
│  │  [Test] [⚙]│  │  [Test] [⚙]│  │  [Test] [⚙]│  │  [Start]    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

**2. Configuration**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⚙️ Inference Configuration                                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│  Primary Engine:  [NPU (qwen2.5:0.5b) ▼]    Fallback: NPU → iGPU → NVIDIA  │
│                                                                             │
│  ☑ Enable Tool Pre-filtering    ☑ Enable NPU (Layer 4)    ☑ Enable Cache  │
│                                                                             │
│  Max Categories: [3 ▼]  Timeout: [500ms ▼]  Cache TTL: [300s ▼]            │
│                                                                             │
│  Fallback Strategy: [keyword_match ▼]              [Save to config.json]   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**3. Persona Statistics**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📊 Persona Tool Statistics                              [Export CSV]       │
├─────────────────────────────────────────────────────────────────────────────┤
│  │ Persona    │ Requests │ Min │ Max │ Mean │ Median │ P95 │               │
│  ├────────────┼──────────┼─────┼─────┼──────┼────────┼─────┤               │
│  │ developer  │    847   │  17 │  42 │ 24.3 │   22   │  35 │               │
│  │ devops     │    234   │  19 │  38 │ 26.1 │   25   │  33 │               │
│                                                                             │
│  Total: 1,160 requests │ Avg Reduction: 87.2% │ Token Savings: ~$94        │
└─────────────────────────────────────────────────────────────────────────────┘
```

**4. Recent History**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  📜 Recent Inference History                              [Clear] [Export]  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─ 12:34:56 ───────────────────────────────────────────────────────────┐  │
│  │ "deploy MR 1459 to ephemeral" │ developer │ skill: test_mr_ephemeral │  │
│  │ Layer 1: 5 │ Layer 2: +12 │ Layer 3: +6 │ Layer 4: SKIPPED          │  │
│  │ Final: 23 tools (89.6% reduction) │ 8ms                              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

**5. Performance Metrics**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  ⏱️ Performance Metrics                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  Latency Distribution:                                                      │
│  <10ms  ████████████████████████████████████████  68%                      │
│  10-100ms  ████████  12%                                                    │
│  100-500ms  ████████████  18%                                               │
│  >500ms  ██  2%                                                             │
│                                                                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │ Avg: 47ms  │  │ P50: 8ms   │  │ P95: 412ms │  │ Cache: 34% │            │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘            │
└─────────────────────────────────────────────────────────────────────────────┘
```

**6. Inference Inspector**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  🧪 Inference Inspector                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  Test Message: [deploy MR 1459 to ephemeral                              ] │
│  Persona: [developer ▼]    Skill: [Auto-detect ▼]                          │
│                                                                             │
│  [🔍 Run Inference]  [📋 Copy Result]  [💾 Save Test Case]                 │
│                                                                             │
│  Result: ✅ 23 tools in 8ms (89.6% reduction)                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │ Layer 1 (Core): skills → 5 tools                                    │   │
│  │ Layer 2 (Persona): jira_read, gitlab_mr_read, gitlab_ci → +12 tools │   │
│  │ Layer 3 (Skill): test_mr_ephemeral → +6 tools                       │   │
│  │ Layer 4 (NPU): SKIPPED (skill detected)                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Quick Tests: [hello] [MR 1459] [AAP-12345] [deploy MR] [debug error]      │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### New MCP Tools for Dashboard

```python
def inference_stats() -> dict:
    """Get current inference statistics."""

def ollama_status() -> dict:
    """Get status of all Ollama instances."""

def inference_test(message: str, persona: str = "developer") -> dict:
    """Run a test inference and return detailed results."""

def inference_config_update(key: str, value: Any) -> dict:
    """Update inference configuration in config.json."""
```

#### Data Storage

- `~/.config/aa-workflow/inference_stats.json` - Statistics and history
- `~/.config/aa-workflow/ollama_status.json` - Instance health

#### Deliverables

- [ ] Add "Inference" tab to Command Center
- [ ] Ollama instance status cards with health polling
- [ ] Configuration section with config.json updates
- [ ] Persona statistics table
- [ ] Recent history with expandable entries
- [ ] Performance metrics charts
- [ ] Inference inspector/tester
- [ ] Quick test presets
- [ ] Export functionality

---

### Phase 7: Testing & Tuning (2-3 hours)

**Purpose:** Validate and optimize

#### Test Cases

```python
class TestLayerFiltering:
    def test_layer1_core_always_included(self):
        result = filter_tools("hello", persona="developer")
        assert "skill_run" in result["tools"]

    def test_layer2_persona_baseline(self):
        result = filter_tools("hello", persona="developer")
        assert "jira_view_issue" in result["tools"]
        assert "gitlab_mr_view" in result["tools"]

    def test_layer3_skill_discovery(self):
        result = filter_tools("deploy MR 1459 to ephemeral", persona="developer")
        assert "bonfire_deploy" in result["tools"]

    def test_layer4_npu_classification(self):
        result = filter_tools("help debug this error", persona="developer")
        assert len(result["tools"]) > 20  # More than baseline

    def test_fallback_when_npu_offline(self):
        # Simulate NPU offline
        result = filter_tools("help debug this error", persona="developer")
        assert "layer4_keyword_fallback" in result["methods"] or "layer4_npu" in result["methods"]

class TestToolReduction:
    def test_significant_reduction(self):
        result = filter_tools("check MR 1459", persona="developer")
        assert result["reduction_pct"] > 80

    def test_baseline_reasonable_size(self):
        result = filter_tools("hello", persona="developer")
        assert 15 <= result["tool_count"] <= 25
```

#### Benchmark Script

```python
#!/usr/bin/env python3
"""Benchmark tool filtering performance."""

MESSAGES = [
    ("hello", "layer1+2"),
    ("check MR 1459", "fast_path"),
    ("deploy MR 1459 to ephemeral", "layer3_skill"),
    ("help debug this error", "layer4_npu"),
]

def benchmark():
    filter = HybridToolFilter()

    for msg, expected in MESSAGES:
        filter.clear_cache()
        result = filter.filter(msg, persona="developer")
        print(f"{result['latency_ms']:6.1f}ms | {result['tool_count']:2d} tools | {msg[:40]}")
```

#### Deliverables

- [ ] Comprehensive test suite for all 4 layers
- [ ] Fallback strategy tests
- [ ] Benchmark script
- [ ] Performance baseline metrics
- [ ] Tuning documentation

---

## Part 4: Timeline Summary

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: aa_ollama module | 1-2 hours | None |
| Phase 2: Tool registry | 2-3 hours | Phase 1 |
| Phase 3: HybridToolFilter | 3-4 hours | Phase 1, 2 |
| Phase 4: ClaudeAgent integration | 1-2 hours | Phase 3 |
| Phase 5: Statistics & caching | 1-2 hours | Phase 3 |
| Phase 6: Inference Dashboard | 4-6 hours | Phase 5 |
| Phase 7: Testing & tuning | 2-3 hours | All phases |

**Total: 14-22 hours**

---

## Part 5: Success Metrics

| Metric | Target |
|--------|--------|
| Tool reduction | >85% (222 → <35 tools) |
| Token savings | >85% (~29K → <4K tokens) |
| Layer 1+2 only (no NPU) | ~70% of requests |
| Layer 3 (skill discovery) | ~15% of requests |
| Layer 4 (NPU needed) | ~15% of requests |
| Cache hit rate | >30% of requests |
| Filter latency (Layer 1-3) | <10ms |
| Filter latency (Layer 4) | <500ms |
| NPU power | 2-5W during classification |
| Fallback success rate | 100% (graceful degradation) |

---

## Part 6: Example Flows

### Flow 1: Simple Greeting (Layer 1+2 only)

```
Message: "hello"
Persona: developer

Layer 1 (Core): skills, session, memory → 5 tools
Layer 2 (Persona): jira_read, gitlab_mr_read, gitlab_ci → +12 tools
Layer 3 (Skill): No skill detected → SKIPPED
Layer 4 (NPU): Not needed → SKIPPED

Final: 17 tools (92% reduction) | 2ms
```

### Flow 2: MR Reference (Fast Path)

```
Message: "check MR 1459"
Persona: developer

Layer 1 (Core): 5 tools
Layer 2 (Persona): +12 tools
Fast Path: "MR 1459" → gitlab_mr_read, gitlab_ci (already included)
Layer 3-4: SKIPPED

Final: 17 tools (92% reduction) | 3ms
```

### Flow 3: Skill Execution (Layer 3)

```
Message: "deploy MR 1459 to ephemeral"
Persona: developer

Layer 1 (Core): 5 tools
Layer 2 (Persona): +12 tools
Layer 3 (Skill): test_mr_ephemeral detected
  → gitlab_mr_sha, quay_check_image, bonfire_deploy, kubectl_get_pods → +6 tools
Layer 4 (NPU): SKIPPED (skill detected)

Final: 23 tools (89% reduction) | 8ms
```

### Flow 4: Ambiguous Request (Layer 4 NPU)

```
Message: "why is the API so slow today"
Persona: developer

Layer 1 (Core): 5 tools
Layer 2 (Persona): +12 tools
Layer 3 (Skill): No skill detected
Layer 4 (NPU): Classifies → k8s_read, logs, metrics → +12 tools

Final: 29 tools (87% reduction) | 412ms
```

### Flow 5: NPU Offline (Fallback)

```
Message: "why is the API so slow today"
Persona: developer
NPU Status: OFFLINE

Layer 1 (Core): 5 tools
Layer 2 (Persona): +12 tools
Layer 3 (Skill): No skill detected
Layer 4 (Fallback): keyword_match → "slow" → metrics, "API" → k8s_read → +8 tools

Final: 25 tools (89% reduction) | 5ms
Dashboard shows: ⚠️ "Inference degraded - using keyword fallback"
```

---

## Part 7: Cost/Benefit Summary

### Token Savings

| Scenario | Tools | Tokens | Cost/call |
|----------|-------|--------|-----------|
| No filtering | 222 | ~29,000 | $0.087 |
| With filtering | ~25 | ~3,500 | $0.011 |
| **Savings** | - | 88% | **$0.076** |

### Monthly Impact (1000 calls)

- Before: $87/month
- After: $11/month
- **Savings: $76/month**

### Power Cost

- NPU classification: 0.001 Wh per call
- 1000 calls: 1 Wh total
- Cost: ~$0.00015/month (negligible)
