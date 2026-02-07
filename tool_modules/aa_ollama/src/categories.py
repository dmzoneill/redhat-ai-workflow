"""Tool category definitions for pre-filtering.

Each category groups related tools with:
- description: Human-readable description for NPU prompts
- keywords: Trigger words for fast regex matching
- tools: List of tool names in this category
- priority: 1-10, higher = more likely to be selected
"""

TOOL_CATEGORIES = {
    # === JIRA (High Priority for Developer) ===
    "jira_read": {
        "description": "View and search Jira issues",
        "keywords": [
            "issue",
            "ticket",
            "aap-",
            "jira",
            "story",
            "bug",
            "task",
            "sprint",
            "backlog",
        ],
        "tools": [
            "jira_view_issue",
            "jira_view_issue_json",
            "jira_search",
            "jira_list_issues",
            "jira_my_issues",
            "jira_list_blocked",
            "jira_get_issue",
        ],
        "priority": 9,
    },
    "jira_write": {
        "description": "Update Jira issues - status, comments, assignments",
        "keywords": [
            "update issue",
            "set status",
            "assign",
            "comment on",
            "transition",
            "move to",
        ],
        "tools": [
            "jira_set_status",
            "jira_add_comment",
            "jira_assign",
            "jira_set_priority",
            "jira_transition",
            "jira_set_story_points",
            "jira_set_epic",
            "jira_add_link",
        ],
        "priority": 6,
    },
    "jira_create": {
        "description": "Create new Jira issues",
        "keywords": [
            "create issue",
            "new story",
            "new bug",
            "file ticket",
            "create task",
        ],
        "tools": [
            "jira_create_issue",
            "jira_clone_issue",
        ],
        "priority": 5,
    },
    # === GITLAB MR (High Priority for Developer) ===
    "gitlab_mr_read": {
        "description": "View merge requests - details, diff, comments",
        "keywords": ["mr", "merge request", "!", "pull request", "pr", "review"],
        "tools": [
            "gitlab_mr_view",
            "gitlab_mr_list",
            "gitlab_list_mrs",
            "gitlab_mr_diff",
            "gitlab_mr_comments",
            "gitlab_mr_sha",
            "gitlab_commit_list",
            "gitlab_mr_approvers",
        ],
        "priority": 9,
    },
    "gitlab_mr_write": {
        "description": "Create and update merge requests",
        "keywords": ["create mr", "update mr", "approve", "comment", "close mr"],
        "tools": [
            "gitlab_mr_create",
            "gitlab_mr_update",
            "gitlab_mr_approve",
            "gitlab_mr_comment",
            "gitlab_mr_close",
        ],
        "priority": 6,
    },
    # === GITLAB CI (High Priority) ===
    "gitlab_ci": {
        "description": "CI/CD pipelines - status, logs, jobs",
        "keywords": ["pipeline", "ci", "build", "job", "failed", "passed", "running"],
        "tools": [
            "gitlab_ci_status",
            "gitlab_ci_view",
            "gitlab_ci_list",
            "gitlab_ci_trace",
            "gitlab_ci_lint",
        ],
        "priority": 8,
    },
    # === GIT ===
    "git_read": {
        "description": "View git status, log, diff",
        "keywords": [
            "git status",
            "git log",
            "git diff",
            "commit history",
            "blame",
            "show commit",
        ],
        "tools": [
            "git_status",
            "git_log",
            "git_diff",
            "git_show",
            "git_blame",
            "git_diff_tree",
            "git_rev_parse",
            "git_branch_list",
            "git_config_get",
        ],
        "priority": 7,
    },
    "git_write": {
        "description": "Git operations - commit, push, branch",
        "keywords": [
            "commit",
            "push",
            "branch",
            "checkout",
            "merge",
            "rebase",
            "stash",
            "pull",
        ],
        "tools": [
            "git_commit",
            "git_push",
            "git_pull",
            "git_branch_create",
            "git_checkout",
            "git_merge",
            "git_merge_abort",
            "git_rebase",
            "git_stash",
            "git_add",
            "git_fetch",
            "git_reset",
        ],
        "priority": 6,
    },
    # === KUBERNETES ===
    "k8s_read": {
        "description": "View Kubernetes resources - pods, logs, events",
        "keywords": [
            "pod",
            "container",
            "k8s",
            "kubernetes",
            "logs",
            "deployment",
            "namespace",
            "clowdapp",
        ],
        "tools": [
            "kubectl_get_pods",
            "kubectl_logs",
            "kubectl_describe",
            "kubectl_get_deployments",
            "kubectl_get_events",
            "kubectl_get",
            "kubectl_exec",
        ],
        "priority": 7,
    },
    "k8s_write": {
        "description": "Modify Kubernetes resources",
        "keywords": ["delete pod", "scale", "restart", "rollout"],
        "tools": [
            "kubectl_delete",
            "kubectl_scale",
            "kubectl_rollout",
            "kubectl_apply",
        ],
        "priority": 4,
    },
    # === EPHEMERAL ===
    "ephemeral": {
        "description": "Ephemeral environments - reserve, deploy, release",
        "keywords": [
            "ephemeral",
            "bonfire",
            "reserve",
            "namespace",
            "test mr",
            "spin up",
        ],
        "tools": [
            "bonfire_namespace_reserve",
            "bonfire_namespace_list",
            "bonfire_namespace_release",
            "bonfire_deploy",
            "bonfire_namespace_describe",
        ],
        "priority": 7,
    },
    # === QUAY ===
    "quay": {
        "description": "Container images - check, list tags",
        "keywords": ["image", "quay", "container", "tag", "sha", "digest", "manifest"],
        "tools": [
            "quay_check_image_exists",
            "quay_list_aa_tags",
            "quay_get_manifest",
            "quay_get_tag",
            "quay_get_vulnerabilities",
            "skopeo_get_digest",
        ],
        "priority": 6,
    },
    # === KONFLUX ===
    "konflux": {
        "description": "Konflux builds and pipelines",
        "keywords": ["konflux", "tekton", "pipelinerun", "build"],
        "tools": [
            "konflux_list_pipelines",
            "konflux_get_pipeline",
            "konflux_list_components",
        ],
        "priority": 6,
    },
    # === MONITORING ===
    "alerts": {
        "description": "Alerts - view firing alerts, silences",
        "keywords": [
            "alert",
            "firing",
            "critical",
            "warning",
            "silence",
            "alertmanager",
        ],
        "tools": [
            "alertmanager_list_alerts",
            "alertmanager_list_silences",
            "alertmanager_create_silence",
        ],
        "priority": 8,
    },
    "logs": {
        "description": "Log searching - Kibana, application logs",
        "keywords": ["logs", "kibana", "error", "exception", "trace", "search logs"],
        "tools": [
            "kibana_search_logs",
            "kibana_get_errors",
            "kibana_tail_logs",
        ],
        "priority": 7,
    },
    "metrics": {
        "description": "Prometheus metrics and queries",
        "keywords": ["metrics", "prometheus", "grafana", "cpu", "memory", "latency"],
        "tools": [
            "prometheus_query",
            "prometheus_range_query",
            "prometheus_alerts",
        ],
        "priority": 6,
    },
    # === WORKFLOW (Always available) ===
    "skills": {
        "description": "Workflow automation skills",
        "keywords": ["skill", "workflow", "automate", "run skill"],
        "tools": [
            "skill_run",
            "skill_list",
        ],
        "priority": 10,
    },
    "session": {
        "description": "Session management",
        "keywords": ["session", "start", "persona", "agent"],
        "tools": [
            "session_start",
            "persona_load",
            "persona_list",
        ],
        "priority": 10,
    },
    "memory": {
        "description": "Memory and state management",
        "keywords": ["memory", "remember", "state", "context"],
        "tools": [
            "memory_read",
            "memory_write",
            "memory_update",
            "memory_append",
            "memory_query",
            "memory_session_log",
            "memory_stats",
            "check_known_issues",
            "learn_tool_fix",
        ],
        "priority": 10,
    },
    # === UTILITIES ===
    "tools_meta": {
        "description": "Tool discovery and execution",
        "keywords": ["tool", "list tools", "exec", "debug"],
        "tools": [
            "tool_list",
            "tool_exec",
            "debug_tool",
        ],
        "priority": 5,
    },
    "auth": {
        "description": "Authentication - VPN, Kubernetes login",
        "keywords": ["vpn", "login", "auth", "kube login", "credentials"],
        "tools": [
            "vpn_connect",
            "kube_login",
        ],
        "priority": 5,
    },
    "lint": {
        "description": "Code linting and formatting",
        "keywords": ["lint", "format", "black", "flake8", "isort"],
        "tools": [
            "lint_python",
        ],
        "priority": 4,
    },
    # === OLLAMA (Local Inference) ===
    "ollama": {
        "description": "Local Ollama inference",
        "keywords": ["ollama", "npu", "local inference", "generate"],
        "tools": [
            "ollama_status",
            "ollama_generate",
            "ollama_classify",
            "ollama_test",
            "inference_available",
        ],
        "priority": 3,
    },
}

# Core categories that are ALWAYS included
CORE_CATEGORIES = ["skills", "session", "memory"]

# Categories by priority tier
HIGH_PRIORITY_CATEGORIES = [
    cat
    for cat, info in TOOL_CATEGORIES.items()
    if info["priority"] >= 8  # type: ignore[operator]
]
MEDIUM_PRIORITY_CATEGORIES = [
    cat
    for cat, info in TOOL_CATEGORIES.items()
    if 5 <= info["priority"] < 8  # type: ignore[operator]
]
LOW_PRIORITY_CATEGORIES = [
    cat
    for cat, info in TOOL_CATEGORIES.items()
    if info["priority"] < 5  # type: ignore[operator]
]


def get_category_tools(category_name: str) -> list[str]:
    """Get tools for a specific category."""
    cat = TOOL_CATEGORIES.get(category_name)
    return list(cat["tools"]) if cat else []  # type: ignore[call-overload]


def get_all_tools() -> list[str]:
    """Get all tools from all categories."""
    tools: set[str] = set()
    for cat in TOOL_CATEGORIES.values():
        tools.update(cat["tools"])  # type: ignore[arg-type]
    return list(tools)


def get_category_for_tool(tool_name: str) -> str | None:
    """Find which category a tool belongs to."""
    for cat_name, cat_info in TOOL_CATEGORIES.items():
        if tool_name in cat_info["tools"]:  # type: ignore[operator]
            return cat_name
    return None


def format_categories_for_prompt(exclude: set[str] | None = None) -> str:
    """Format categories for NPU classification prompt."""
    exclude = exclude or set()
    lines = []
    for name, info in sorted(  # type: ignore[call-overload]
        TOOL_CATEGORIES.items(),
        key=lambda x: -int(x[1]["priority"]),
    ):
        if name not in exclude:
            lines.append(f"- {name}: {info['description']}")
    return "\n".join(lines)
