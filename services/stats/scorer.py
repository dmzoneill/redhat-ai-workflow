"""Competency scoring engine with configurable weights, level-specific thresholds, and signal mapping."""

import json
import logging
from pathlib import Path

import yaml

from server.paths import PERFORMANCE_DIR

logger = logging.getLogger(__name__)

COMPETENCIES_YAML = Path(__file__).parent / "competencies.yaml"

COMPETENCY_DEFS: dict[str, dict] = {
    "technical_contribution": {
        "name": "Technical Contribution",
        "category": "Technical Contribution",
        "goal": "Deliver high-quality code through commits, merge requests, and bug fixes.",
        "description": (
            "Measures direct code contributions: commits, MRs merged, bugs fixed, "
            "and upstream patches. Also recognises architecture oversight, code review "
            "meetings, and alert investigation as hands-on engineering."
        ),
        "base_points": 2,
        "event_types": [
            "mr_merged",
            "mr_opened",
            "issue_resolved",
            "commit",
            "pr_opened",
            "pr_merged",
            "debugging_outcome",
            "architecture_decision",
            "alert_investigated",
            "meeting_organized_architecture_review",
            "meeting_attended_architecture_review",
            "meeting_organized_code_review",
            "meeting_attended_code_review",
        ],
        "phrases": [
            "fix:",
            "feat:",
            "bug fix",
            "patch",
            "hotfix",
            "implement",
            "add feature",
            "code change",
            "pull request",
            "merge request",
            "commit",
            "resolved",
            "fixed",
            "closes #",
            "upstream",
        ],
        "keywords": ["fix", "feat", "patch", "implement", "code", "commit", "upstream"],
    },
    "technical_knowledge": {
        "name": "Technical Knowledge",
        "category": "Technical Contribution",
        "goal": "Build and share technical knowledge through documentation and knowledge articles.",
        "description": (
            "Captures documentation work: READMEs, architecture docs, runbooks, "
            "knowledge-base articles, and technical blog posts."
        ),
        "base_points": 3,
        "event_types": [
            "commit",
            "alert_investigated",
            "architecture_decision",
            "debugging_outcome",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
            "gdrive_sheet_created",
            "gdrive_sheet_contributed",
            "meeting_organized_architecture_review",
            "meeting_attended_architecture_review",
            "meeting_organized_training",
            "meeting_attended_training",
            "meeting_organized_incident_response",
            "meeting_attended_incident_response",
            "meeting_organized_code_review",
            "meeting_attended_code_review",
        ],
        "phrases": [
            "update readme",
            "add documentation",
            "write docs",
            "knowledge base",
            "architecture decision record",
            "adr",
            "runbook",
            "how-to guide",
            "onboarding doc",
            "technical blog",
            "wiki update",
            "docs(",
            "doc:",
            "update doc",
            "changelog",
            "release notes",
            "comment",
            "annotation",
            "type hint",
            "docstring",
            "swagger",
            "openapi spec",
            "config doc",
            "readme",
            "yaml",
            "schema doc",
        ],
        "keywords": [
            "doc",
            "readme",
            "documentation",
            "wiki",
            "guide",
            "runbook",
            "adr",
            "changelog",
            "annotation",
            "docstring",
            "swagger",
            "schema",
            "yaml",
            "config",
        ],
    },
    "creativity_innovation": {
        "name": "Creativity & Innovation",
        "category": "Technical Contribution",
        "goal": "Drive innovation through prototypes, AI experiments, and creative solutions.",
        "description": (
            "Recognises work on proof-of-concepts, AI/ML experiments, novel tooling, "
            "and creative problem solving that goes beyond routine tasks."
        ),
        "base_points": 4,
        "event_types": [
            "pr_opened",
            "commit",
            "architecture_decision",
            "process_improvement",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
            "gdrive_slides_created",
            "gdrive_slides_contributed",
            "meeting_organized_architecture_review",
            "meeting_attended_architecture_review",
        ],
        "phrases": [
            "proof of concept",
            "poc",
            "prototype",
            "experiment",
            "ai model",
            "machine learning",
            "llm",
            "generative",
            "novel approach",
            "innovative",
            "new tool",
            "spike",
            "research",
            "gpt",
            "claude",
            "langchain",
            "embedding",
            "vector search",
            "workflow",
            "automation",
            "bot",
            "mcp",
            "tool",
            "plugin",
            "extension",
            "openai",
            "openvino",
            "npu",
            "inference",
            "model",
            "neural",
            "data pipeline",
            "etl",
        ],
        "keywords": [
            "poc",
            "prototype",
            "innovation",
            "experiment",
            "ai",
            "ml",
            "llm",
            "generative",
            "novel",
            "spike",
            "research",
            "workflow",
            "automation",
            "bot",
            "plugin",
            "extension",
            "openvino",
            "npu",
            "inference",
            "neural",
            "etl",
        ],
    },
    "continuous_improvement": {
        "name": "Continuous Improvement",
        "category": "Leadership",
        "goal": "Improve engineering processes, CI/CD, automation, and code quality.",
        "description": (
            "Tracks process improvements: CI/CD pipeline enhancements, automation, "
            "refactoring for maintainability, linting, test coverage, and tooling upgrades."
        ),
        "base_points": 3,
        "event_types": [
            "alert_investigated",
            "debugging_outcome",
            "process_improvement",
            "meeting_organized_retrospective",
            "meeting_attended_retrospective",
            "meeting_organized_incident_response",
            "meeting_attended_incident_response",
        ],
        "phrases": [
            "ci/cd",
            "pipeline",
            "automate",
            "refactor",
            "tech debt",
            "improve test",
            "add test",
            "coverage",
            "lint",
            "code quality",
            "tooling",
            "developer experience",
            "dx",
            "build system",
            "dependency update",
            "upgrade",
            "migrate",
            "modernise",
            "modernize",
        ],
        "keywords": [
            "ci/cd",
            "pipeline",
            "automation",
            "tooling",
            "refactor",
            "lint",
            "coverage",
            "tech debt",
            "migrate",
            "upgrade",
        ],
    },
    "leadership": {
        "name": "Leadership",
        "category": "Leadership",
        "goal": "Lead cross-team initiatives, architecture decisions, and design reviews.",
        "description": (
            "Recognises leadership actions: driving architecture decisions, leading "
            "design reviews, cross-team coordination, and setting technical direction."
        ),
        "base_points": 3,
        "event_types": [
            "meeting_participated",
            "architecture_decision",
            "collaboration_activity",
            "leadership_activity",
            "meeting_organized_planning",
            "meeting_organized_sprint_planning",
            "meeting_organized_architecture_review",
            "meeting_organized_all_hands",
            "meeting_organized_one_on_one",
            "meeting_attended_planning",
            "meeting_attended_sprint_planning",
            "meeting_attended_architecture_review",
            "meeting_attended_all_hands",
            "meeting_attended_one_on_one",
        ],
        "phrases": [
            "cross-team",
            "lead",
            "architecture",
            "design review",
            "rfc",
            "tech lead",
            "decision",
            "strategy",
            "proposal",
            "cross-functional",
            "stakeholder",
            "roadmap owner",
            "initiative lead",
            "project lead",
            "facilitated",
            "drove",
            "coordinated",
            "mentored",
        ],
        "keywords": [
            "cross-team",
            "lead",
            "architecture",
            "design",
            "rfc",
            "strategy",
            "proposal",
            "stakeholder",
            "facilitated",
            "drove",
            "coordinated",
        ],
    },
    "collaboration": {
        "name": "Collaboration",
        "category": "Leadership",
        "goal": "Strengthen team collaboration through code reviews, pair programming, and feedback.",
        "description": (
            "Measures collaborative work: reviewing others' code, pair programming, "
            "providing constructive feedback, and contributing to team discussions."
        ),
        "base_points": 2,
        "event_types": [
            "review_given",
            "pr_reviewed",
            "mr_review_given",
            "meeting_participated",
            "collaboration_activity",
            "recognition_given",
            "meeting_attended_cross_team",
            "meeting_organized_cross_team",
            "meeting_attended_code_review",
        ],
        "phrases": [
            "review",
            "pair program",
            "feedback",
            "team discussion",
            "code review",
            "nit:",
            "lgtm",
            "approved",
            "requested changes",
            "collab",
            "pair on",
            "mob program",
        ],
        "keywords": ["review", "pair", "feedback", "collab", "lgtm", "approved"],
    },
    "mentorship": {
        "name": "Mentorship",
        "category": "Mentorship",
        "goal": "Grow others through mentoring, onboarding, training, and knowledge sharing.",
        "description": (
            "Captures mentoring activities: onboarding new hires, running training "
            "sessions, knowledge-sharing talks, and supporting junior team members."
        ),
        "base_points": 3,
        "event_types": [
            "mr_review_given",
            "recognition_given",
            "meeting_organized_training",
            "meeting_attended_training",
            "meeting_organized_one_on_one",
            "meeting_attended_one_on_one",
            "meeting_organized_interview",
            "meeting_attended_interview",
            "meeting_organized_onboarding",
            "meeting_attended_onboarding",
            "meeting_organized_code_review",
            "meeting_attended_code_review",
        ],
        "phrases": [
            "mentor",
            "onboard",
            "training",
            "newcomer",
            "knowledge share",
            "teach",
            "coach",
            "intern",
            "junior developer",
            "ramping up",
            "brown bag",
            "lunch and learn",
            "demo session",
        ],
        "keywords": [
            "mentor",
            "onboard",
            "training",
            "newcomer",
            "teach",
            "coach",
            "intern",
            "brown bag",
        ],
    },
    "speaking_publicity": {
        "name": "Speaking & Publicity",
        "category": "Technical Contribution",
        "goal": "Represent the team through presentations, blog posts, and public speaking.",
        "description": (
            "Tracks public-facing activities: conference talks, team demos, blog posts, "
            "lightning talks, and any outward communication about the team's work."
        ),
        "base_points": 4,
        "event_types": [
            "gdrive_slides_created",
            "gdrive_slides_contributed",
            "meeting_organized_presentation",
            "meeting_attended_presentation",
            "meeting_organized_sprint_review",
            "meeting_attended_sprint_review",
            "meeting_organized_all_hands",
        ],
        "phrases": [
            "presentation",
            "demo",
            "talk",
            "blog post",
            "conference",
            "lightning talk",
            "all-hands",
            "meetup",
            "webinar",
            "podcast",
            "published",
            "article",
            "show and tell",
            "sprint demo",
            "tech talk",
            "team update",
            "share findings",
            "knowledge session",
            "retrospective",
            "retro",
            "standup presentation",
            "quarterly review",
        ],
        "keywords": [
            "presentation",
            "demo",
            "talk",
            "blog",
            "conference",
            "meetup",
            "webinar",
            "published",
            "retro",
            "slides",
            "recording",
            "deck",
            "google slides",
        ],
    },
    "portfolio_impact": {
        "name": "Portfolio Impact",
        "category": "Leadership",
        "goal": "Deliver cross-cutting impact through APIs, schemas, and service integrations.",
        "description": (
            "Measures work that spans multiple services or products: API design, "
            "schema changes, app-interface updates, cross-service integrations, "
            "and cross-team architecture discussions."
        ),
        "base_points": 4,
        "event_types": [
            "architecture_decision",
            "mr_merged",
            "pr_merged",
            "meeting_organized_architecture_review",
            "meeting_attended_architecture_review",
            "meeting_organized_cross_team",
            "meeting_attended_cross_team",
            "meeting_organized_planning",
            "meeting_attended_planning",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
        ],
        "phrases": [
            "api",
            "schema",
            "interface",
            "app-interface",
            "integration",
            "cross-service",
            "microservice",
            "contract",
            "openapi",
            "graphql",
            "rest endpoint",
            "service mesh",
        ],
        "keywords": [
            "api",
            "schema",
            "interface",
            "app-interface",
            "integration",
            "openapi",
            "graphql",
            "endpoint",
        ],
    },
    "planning_execution": {
        "name": "Planning & Execution",
        "category": "Technical Contribution",
        "goal": "Plan and break down work into well-defined, actionable tasks.",
        "description": (
            "Recognises planning work: creating Jira issues with clear acceptance "
            "criteria, sprint planning, roadmap contributions, and task breakdown."
        ),
        "base_points": 2,
        "event_types": [
            "issue_created",
            "issue_opened",
            "issue_closed",
            "meeting_organized_sprint_planning",
            "meeting_attended_sprint_planning",
            "meeting_organized_planning",
            "meeting_attended_planning",
            "meeting_organized_standup",
            "session_documented",
            "gdrive_sheet_created",
            "gdrive_sheet_contributed",
        ],
        "phrases": [
            "planning",
            "roadmap",
            "sprint",
            "backlog",
            "acceptance criteria",
            "break down",
            "task breakdown",
            "epic",
            "story point",
            "estimate",
            "scope",
            "requirement",
            "specification",
            "issue",
            "task",
            "ticket",
            "jira",
            "created",
            "opened",
            "closed",
            "assigned",
            "priority",
            "milestone",
            "due date",
            "grooming",
            "refinement",
            "triage",
        ],
        "keywords": [
            "planning",
            "roadmap",
            "sprint",
            "backlog",
            "scope",
            "requirement",
            "specification",
            "estimate",
            "standup",
            "daily sync",
            "ceremony",
            "issue",
            "task",
            "ticket",
            "jira",
            "created",
            "opened",
            "closed",
            "triage",
            "grooming",
            "milestone",
            "tracker",
            "spreadsheet",
        ],
    },
    "end_to_end_delivery": {
        "name": "End-to-End Delivery",
        "category": "End-to-End Delivery",
        "goal": "Ship features from development all the way to production.",
        "description": (
            "Tracks full delivery lifecycle: releasing to production, deploying "
            "and validating, customer-facing fixes, closing delivery loops, and "
            "shepherding releases through reviews and incident response."
        ),
        "base_points": 3,
        "event_types": [
            "pr_merged",
            "mr_merged",
            "issue_resolved",
            "issue_closed",
            "meeting_organized_sprint_review",
            "meeting_attended_sprint_review",
            "meeting_organized_customer_meeting",
            "meeting_attended_customer_meeting",
            "meeting_organized_incident_response",
            "meeting_attended_incident_response",
            "session_documented",
        ],
        "phrases": [
            "release",
            "deploy",
            "production",
            "customer",
            "ship",
            "go live",
            "rollout",
            "stage",
            "promote",
            "delivered",
            "merged to main",
            "hotfix",
            "incident fix",
            "merge",
            "merged",
            "pipeline",
            "ci pass",
            "tested",
            "validated",
            "approved",
            "ready for merge",
            "konflux",
            "quay",
            "image",
            "container",
        ],
        "keywords": [
            "release",
            "deploy",
            "customer",
            "production",
            "ship",
            "rollout",
            "promote",
            "hotfix",
            "merge",
            "merged",
            "pipeline",
            "validated",
            "quay",
            "konflux",
            "container",
        ],
    },
    "opportunity_recognition": {
        "name": "Opportunity Recognition",
        "category": "Technical Contribution",
        "goal": "Identify opportunities and contribute beyond assigned work, including open-source.",
        "description": (
            "Measures proactive contributions: open-source work on GitHub, identifying "
            "improvement opportunities, proposing new features, self-directed initiatives, "
            "and driving cross-team discussions that surface new opportunities."
        ),
        "base_points": 4,
        "event_types": [
            "issue_opened",
            "issue_created",
            "pr_opened",
            "mr_opened",
            "process_improvement",
            "architecture_decision",
            "gdrive_doc_created",
            "meeting_organized_architecture_review",
            "meeting_organized_cross_team",
            "meeting_organized_planning",
        ],
        "phrases": [
            "open source",
            "github",
            "upstream contribution",
            "community",
            "volunteer",
            "self-directed",
            "initiative",
            "improvement opportunity",
            "proposed feature",
            "new idea",
            "side project",
            "contribution",
            "feature request",
            "enhancement",
            "improvement",
            "proactive",
            "self-initiated",
            "hackathon",
            "20% time",
            "personal project",
            "refactor",
            "tech debt",
            "cleanup",
            "automated",
            "streamlined",
            "cve fix",
        ],
        "keywords": [
            "open-source",
            "github",
            "upstream",
            "community",
            "volunteer",
            "initiative",
            "opportunity",
            "contribution",
            "enhancement",
            "improvement",
            "proactive",
            "hackathon",
            "refactor",
            "tech debt",
            "cleanup",
            "automated",
        ],
    },
    "customer_focus": {
        "name": "Customer Involvement & Focus",
        "category": "End-to-End Delivery",
        "goal": "Engage with customers and stakeholders to understand and deliver value.",
        "description": (
            "Tracks customer-facing work: stakeholder engagement, customer issue resolution, "
            "field escalations, customer demos, and product feedback incorporation."
        ),
        "base_points": 3,
        "event_types": [
            "issue_resolved",
            "issue_closed",
            "issue_opened",
            "alert_investigated",
            "customer_engagement",
            "meeting_organized_customer_meeting",
            "meeting_attended_customer_meeting",
        ],
        "phrases": [
            "customer",
            "stakeholder",
            "field escalation",
            "customer demo",
            "customer feedback",
            "user request",
            "customer issue",
            "support case",
            "account",
            "use case",
            "customer engagement",
            "sla",
            "customer-reported",
            "field issue",
            "production issue",
            "user-facing",
            "user experience",
            "ux",
            "end user",
            "tenant",
            "billing",
            "subscription",
        ],
        "keywords": [
            "customer",
            "stakeholder",
            "escalation",
            "account",
            "field",
            "user request",
            "sla",
            "tenant",
            "billing",
            "ux",
            "user-facing",
            "subscription",
        ],
    },
    "scope": {
        "name": "Scope",
        "category": "Technical Contribution",
        "goal": "Demonstrate breadth and depth of technical scope in contributions.",
        "description": (
            "Measures the scope of work: from task-level to subsystem-level design, "
            "cross-component integration, and architectural coordination."
        ),
        "base_points": 3,
        "event_types": [
            "mr_merged",
            "mr_opened",
            "pr_merged",
            "pr_opened",
            "issue_closed",
            "issue_created",
            "commit",
            "meeting_organized_all_hands",
            "meeting_attended_all_hands",
            "meeting_organized_cross_team",
            "meeting_attended_cross_team",
        ],
        "phrases": [
            "subsystem",
            "cross-component",
            "architectural",
            "system design",
            "platform",
            "full stack",
            "end-to-end",
            "multi-service",
            "infrastructure",
            "framework",
            "refactor",
            "migration",
            "database",
            "schema change",
            "config change",
            "multiple services",
            "across repos",
            "cluster",
            "namespace",
            "deployment",
            "service",
            "backend",
            "frontend",
        ],
        "keywords": [
            "subsystem",
            "platform",
            "architecture",
            "infrastructure",
            "framework",
            "system",
            "migration",
            "database",
            "cluster",
            "deployment",
            "namespace",
            "backend",
            "frontend",
            "service",
            "config",
        ],
    },
    "evidence_record": {
        "name": "Evidence & Record",
        "category": "Technical Contribution",
        "goal": "Build a consistent track record of delivery and contribution.",
        "description": (
            "Tracks delivery consistency: on-time task completion, scoping accuracy, "
            "decomposition of complex work, and sustained contribution over time."
        ),
        "base_points": 2,
        "event_types": [
            "issue_resolved",
            "issue_closed",
            "mr_merged",
            "pr_merged",
            "meeting_participated",
            "session_documented",
            "customer_engagement",
            "leadership_activity",
            "gdrive_doc_created",
            "gdrive_doc_contributed",
            "gdrive_sheet_created",
            "gdrive_sheet_contributed",
            "gdrive_slides_created",
            "gdrive_slides_contributed",
            "meeting_organized_standup",
            "meeting_organized_sprint_review",
            "meeting_organized_sprint_planning",
            "meeting_organized_retrospective",
            "meeting_organized_one_on_one",
            "meeting_organized_planning",
            "meeting_attended_standup",
            "meeting_attended_sprint_review",
            "meeting_attended_sprint_planning",
            "meeting_attended_retrospective",
            "meeting_attended_one_on_one",
            "meeting_attended_planning",
            "meeting_attended_general_meeting",
            "meeting_organized_general_meeting",
        ],
        "phrases": [
            "delivered",
            "completed",
            "shipped",
            "on time",
            "acceptance criteria met",
            "resolved",
            "closed",
            "done",
            "finished",
            "ready for release",
            "accomplished",
            "addressed feedback",
        ],
        "keywords": [
            "delivered",
            "completed",
            "shipped",
            "resolved",
            "closed",
            "done",
            "accomplished",
            "meeting",
            "attended",
            "organized",
        ],
    },
    "execution_as_mentee": {
        "name": "Execution as Mentee",
        "category": "Mentorship",
        "goal": "Grow through mentoring relationships and expand scope through guidance.",
        "description": (
            "Tracks growth as a mentee: seeking mentors, acting on feedback, "
            "expanding scope through guidance, and building professional networks."
        ),
        "base_points": 2,
        "event_types": ["pr_reviewed", "mr_review_received"],
        "phrases": [
            "learned from",
            "mentor session",
            "1:1",
            "feedback received",
            "growth area",
            "stretch assignment",
            "professional development",
            "career growth",
            "skill building",
            "review comment",
            "suggestion",
            "requested changes",
            "fix review",
            "address feedback",
            "follow-up",
            "iteration",
            "v2",
            "revision",
            "update per",
            "nit",
        ],
        "keywords": [
            "mentor",
            "feedback",
            "growth",
            "learning",
            "development",
            "1:1",
            "suggestion",
            "revision",
            "iteration",
            "follow-up",
            "nit",
        ],
    },
}

DEFAULT_GLOBALS = {
    "min_signals": 2,
    "daily_cap": 15,
    "target_per_competency": 50,
    "engineering_level": "sse",
    "scope_multipliers": {
        "commit": 1,
        "doc": 2,
        "meeting": 1,
        "story": 2,
        "epic": 4,
        "anstrat": 7,
        "strategy": 10,
    },
    "strategy_alignment": {
        "enabled": True,
        "bonus_multiplier": 1.5,
        "enrich_classification": True,
        "min_text_overlap_words": 3,
    },
    "npu_settings": {
        "enabled": False,
        "device": "CPU",
        "confidence_threshold": 0.35,
        "bonus_signals": 2,
    },
    "session_integration": {
        "enabled": True,
        "noise_skip_patterns": [
            "hello_world",
            "vector_reindex",
            "vector reindex",
        ],
        "noise_skip_types": ["session"],
        "min_details_length": 10,
    },
    "max_competencies_per_event": 4,
    "max_classification_length": 200,
    "gaps_threshold_pct": 25,
    "highlights_max_count": 10,
    "backfill_parallel_peers": 4,
    "source_daily_caps": {
        "github": 30,
        "gitlab": 30,
        "git": 20,
        "meeting": 20,
        "jira": 25,
        "gdrive": 15,
        "session": 15,
    },
    "peer_comparable": {
        "work_github_orgs": [
            "ansible",
            "RedHatInsights",
            "aap-ci",
            "aap-cpaas",
        ],
        "work_gitlab_groups": [
            "automation-analytics",
            "aap-cpaas",
        ],
        "work_project_repos": [
            "automation-analytics-backend",
            "pdf-generator",
            "app-interface",
            "konflux-release-data",
            "dataproduct-config",
            "aws-ingestion",
        ],
        "max_meetings_per_day": 3,
        "min_peer_events": 30,
        "min_peer_active_days": 15,
        "blacklisted_peers": [],
        "max_daily_comparable_total": 20,
    },
}

SCORING_CONFIG_FILE = PERFORMANCE_DIR / "scoring_config.json"


def load_scoring_config() -> dict:
    """Load user overrides from scoring_config.json."""
    try:
        if SCORING_CONFIG_FILE.exists():
            with open(SCORING_CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load scoring config: {e}")
    return {}


def save_scoring_config(config: dict) -> None:
    """Write user overrides to scoring_config.json."""
    SCORING_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(SCORING_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def get_merged_config() -> dict:
    """Return full config: defaults merged with user overrides."""
    user = load_scoring_config()
    merged_globals = {**DEFAULT_GLOBALS}
    for k in DEFAULT_GLOBALS:
        if k in user:
            if isinstance(DEFAULT_GLOBALS[k], dict) and isinstance(user[k], dict):
                merged_globals[k] = {**DEFAULT_GLOBALS[k], **user[k]}
            else:
                merged_globals[k] = user[k]

    merged_comps: dict[str, dict] = {}
    user_comps = user.get("competencies", {})
    for comp_id, defn in COMPETENCY_DEFS.items():
        base = {
            "base_points": defn["base_points"],
            "phrases": list(defn.get("phrases", [])),
            "keywords": list(defn.get("keywords", [])),
            "event_types": list(defn.get("event_types", [])),
        }
        if comp_id in user_comps:
            uc = user_comps[comp_id]
            if "base_points" in uc:
                base["base_points"] = uc["base_points"]
            for list_field in ("phrases", "keywords", "event_types"):
                if list_field in uc:
                    merged = list(dict.fromkeys(uc[list_field] + base[list_field]))
                    base[list_field] = merged
        merged_comps[comp_id] = base

    return {**merged_globals, "competencies": merged_comps}


def get_effective_defs() -> tuple[dict[str, dict], int, int, int]:
    """Return (effective_competency_defs, min_signals, daily_cap, target).

    Merges user overrides onto COMPETENCY_DEFS for the scoring engine.
    """
    cfg = get_merged_config()
    effective: dict[str, dict] = {}
    for comp_id, defn in COMPETENCY_DEFS.items():
        eff = dict(defn)
        comp_cfg = cfg.get("competencies", {}).get(comp_id, {})
        for field in ("base_points", "phrases", "keywords", "event_types"):
            if field in comp_cfg:
                eff[field] = comp_cfg[field]
        effective[comp_id] = eff
    return (
        effective,
        cfg.get("min_signals", DEFAULT_GLOBALS["min_signals"]),
        cfg.get("daily_cap", DEFAULT_GLOBALS["daily_cap"]),
        cfg.get("target_per_competency", DEFAULT_GLOBALS["target_per_competency"]),
    )


def get_scope_multipliers() -> dict[str, int]:
    """Return the scope multiplier mapping from config."""
    cfg = get_merged_config()
    return cfg.get("scope_multipliers", DEFAULT_GLOBALS["scope_multipliers"])


def get_strategy_alignment_config() -> dict:
    """Return strategy alignment configuration."""
    cfg = get_merged_config()
    return cfg.get("strategy_alignment", DEFAULT_GLOBALS["strategy_alignment"])


def get_npu_settings() -> dict:
    """Return NPU classification settings."""
    cfg = get_merged_config()
    return cfg.get("npu_settings", DEFAULT_GLOBALS["npu_settings"])


def get_peer_comparable_config() -> dict:
    """Return peer-comparable filtering configuration."""
    cfg = get_merged_config()
    return cfg.get("peer_comparable", DEFAULT_GLOBALS["peer_comparable"])


def get_source_daily_caps() -> dict[str, int]:
    """Return per-source daily point caps."""
    cfg = get_merged_config()
    return cfg.get("source_daily_caps", DEFAULT_GLOBALS["source_daily_caps"])


def get_session_integration_config() -> dict:
    """Return session integration settings."""
    cfg = get_merged_config()
    return cfg.get("session_integration", DEFAULT_GLOBALS["session_integration"])


def get_level_weights(level: str | None = None) -> dict:
    """Return level weight configuration for a specific engineering level.

    Loads from competencies.yaml level_weights section. Returns empty dict
    if level not found.
    """
    if not level:
        cfg = get_merged_config()
        level = cfg.get("engineering_level", "sse")
    data = _load_competencies_yaml()
    all_weights = data.get("level_weights", {})
    return all_weights.get(level, {})


def map_competencies(
    classification_text: str,
    source: str,
    event_type: str,
    scope: str = "story",
    role: str = "assignee",
    *,
    effective_defs: dict[str, dict] | None = None,
    min_signals: int | None = None,
    level: str | None = None,
    strategy_aligned: bool = False,
    npu_classifier: object | None = None,
    contribution_type: str | None = None,
    is_cross_team: bool = False,
    review_decision: str | None = None,
) -> dict[str, int]:
    """Map an event to competency points using the full scoring formula.

    Formula: base_points * scope_mult * role_weight * pillar_weight * strategy_bonus

    Signal types counted (each distinct hit = 1 signal):
      - event_type match: 1 signal
      - each matching phrase: 1 signal per phrase
      - each matching keyword: 1 signal per keyword
      - source-level rule: 1 signal
      - NPU bonus signals (if classifier provided)
      - contribution_type bonus (fork/upstream/cross-org)
      - cross-team Jira bonus
      - review_decision bonus (CHANGES_REQUESTED = mentorship)
    """
    points, _ = map_competencies_with_signals(
        classification_text,
        source,
        event_type,
        scope=scope,
        role=role,
        effective_defs=effective_defs,
        min_signals=min_signals,
        level=level,
        strategy_aligned=strategy_aligned,
        npu_classifier=npu_classifier,
        contribution_type=contribution_type,
        is_cross_team=is_cross_team,
        review_decision=review_decision,
    )
    return points


def map_competencies_with_signals(  # noqa: C901
    classification_text: str,
    source: str,
    event_type: str,
    scope: str = "story",
    role: str = "assignee",
    *,
    effective_defs: dict[str, dict] | None = None,
    min_signals: int | None = None,
    level: str | None = None,
    strategy_aligned: bool = False,
    npu_classifier: object | None = None,
    contribution_type: str | None = None,
    is_cross_team: bool = False,
    review_decision: str | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    """Like map_competencies but also returns raw signal counts per competency.

    Returns (points, signal_counts) where signal_counts[comp_id] is the raw
    signal count *before* the min_signals threshold check.  Persisting
    signal_counts in daily files allows fast re-thresholding when only
    min_signals changes without re-running text matching.
    """
    if effective_defs is not None and min_signals is not None:
        defs, min_sig = effective_defs, min_signals
    else:
        defs, min_sig, _, _ = get_effective_defs()

    cfg = get_merged_config()
    if not level:
        level = cfg.get("engineering_level", "sse")

    scope_multipliers = cfg.get(
        "scope_multipliers", DEFAULT_GLOBALS["scope_multipliers"]
    )
    scope_mult = scope_multipliers.get(scope, 1)

    lw = get_level_weights(level)
    user_cfg = load_scoring_config()
    user_lw = user_cfg.get("level_weight_overrides", {}).get(level, {})
    if user_lw.get("role_weights"):
        merged_rw = dict(lw.get("role_weights", {}))
        for s, roles in user_lw["role_weights"].items():
            if isinstance(roles, dict):
                merged_rw[s] = {**merged_rw.get(s, {}), **roles}
        role_weights_table = merged_rw
    else:
        role_weights_table = lw.get("role_weights", {})
    if user_lw.get("pillar_weights"):
        pillar_weights = {**lw.get("pillar_weights", {}), **user_lw["pillar_weights"]}
    else:
        pillar_weights = lw.get("pillar_weights", {})

    strategy_cfg = cfg.get("strategy_alignment", DEFAULT_GLOBALS["strategy_alignment"])
    strategy_bonus = 1.0
    if strategy_aligned and strategy_cfg.get("enabled", True):
        strategy_bonus = strategy_cfg.get("bonus_multiplier", 1.5)

    npu_bonus: dict[str, int] = {}
    if npu_classifier is not None and hasattr(npu_classifier, "get_bonus_signals"):
        try:
            npu_bonus = npu_classifier.get_bonus_signals(classification_text)
        except Exception as e:
            logger.warning("NPU classifier get_bonus_signals failed: %s", e)

    max_class_len = cfg.get(
        "max_classification_length",
        DEFAULT_GLOBALS["max_classification_length"],
    )
    max_comps = cfg.get(
        "max_competencies_per_event",
        DEFAULT_GLOBALS["max_competencies_per_event"],
    )

    points: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    text = classification_text.lower()[:max_class_len]

    _contrib_bonus_comps: set[str] = set()
    if contribution_type in ("upstream", "fork"):
        _contrib_bonus_comps.update(("opportunity_recognition", "scope"))
    if contribution_type == "cross-org":
        _contrib_bonus_comps.update(("scope", "collaboration"))
    _cross_team_bonus_comps: set[str] = set()
    if is_cross_team:
        _cross_team_bonus_comps.update(("scope", "collaboration", "leadership"))
    _review_decision_bonus: dict[str, set[str]] = {}
    if review_decision:
        rd = review_decision.upper()
        if rd == "CHANGES_REQUESTED":
            _review_decision_bonus = {"mentorship": {rd}, "collaboration": {rd}}
        elif rd == "APPROVED":
            _review_decision_bonus = {"collaboration": {rd}}

    for comp_id, defn in defs.items():
        signals = 0

        if event_type in defn.get("event_types", []):
            signals += 1

        for phrase in defn.get("phrases", []):
            if phrase in text:
                signals += 1

        for kw in defn.get("keywords", []):
            if kw in text:
                signals += 1

        signals += npu_bonus.get(comp_id, 0)

        if comp_id in _contrib_bonus_comps:
            signals += 1
        if comp_id in _cross_team_bonus_comps:
            signals += 1
        if comp_id in _review_decision_bonus:
            signals += 1

        signal_counts[comp_id] = signals

        if signals >= min_sig:
            base = defn["base_points"]
            scope_role_weights = role_weights_table.get(scope, {})
            role_weight = scope_role_weights.get(role, 1.0)
            category = defn.get("category", "")
            pillar_weight = pillar_weights.get(category, 1.0)
            final = round(
                base * scope_mult * role_weight * pillar_weight * strategy_bonus
            )
            points[comp_id] = max(final, 1)

    if source in ("github", "gitlab") and "opportunity_recognition" in defs:
        comp_id = "opportunity_recognition"
        defn = defs[comp_id]
        extra_signals = 1
        if event_type in defn.get("event_types", []):
            extra_signals += 1
        for phrase in defn.get("phrases", []):
            if phrase in text:
                extra_signals += 1
        for kw in defn.get("keywords", []):
            if kw in text:
                extra_signals += 1
        extra_signals += npu_bonus.get(comp_id, 0)
        if comp_id in _contrib_bonus_comps:
            extra_signals += 1
        signal_counts[comp_id] = max(signal_counts.get(comp_id, 0), extra_signals)
        if extra_signals >= min_sig:
            base = defn["base_points"]
            scope_role_weights = role_weights_table.get(scope, {})
            role_weight = scope_role_weights.get(role, 1.0)
            category = defn.get("category", "")
            pillar_weight = pillar_weights.get(category, 1.0)
            final = round(
                base * scope_mult * role_weight * pillar_weight * strategy_bonus
            )
            points[comp_id] = max(
                points.get(comp_id, 0),
                max(final, 1),
            )

    if max_comps and len(points) > max_comps:
        top = sorted(points.items(), key=lambda kv: kv[1], reverse=True)[:max_comps]
        points = dict(top)

    return points, signal_counts


_competencies_yaml_cache: dict | None = None


def _load_competencies_yaml() -> dict:
    """Load and cache the engineering competencies YAML."""
    global _competencies_yaml_cache
    if _competencies_yaml_cache is not None:
        return _competencies_yaml_cache
    try:
        if COMPETENCIES_YAML.exists():
            with open(COMPETENCIES_YAML, encoding="utf-8") as f:
                _competencies_yaml_cache = yaml.safe_load(f) or {}
        else:
            _competencies_yaml_cache = {}
    except Exception as e:
        logger.warning(f"Failed to load competencies YAML: {e}")
        _competencies_yaml_cache = {}
    return _competencies_yaml_cache


def get_engineering_levels() -> list[dict]:
    """Return the list of engineering levels from the competencies YAML."""
    data = _load_competencies_yaml()
    return data.get("engineering_levels", [])


_SCORING_TO_YAML_ALIASES = {
    "technical_contribution": "business_impact",
    "leadership": "work_impact",
    "mentorship": "growth_impact",
    "end_to_end_delivery": "product_delivery_lifecycle",
}


def get_level_description(comp_id: str, level: str) -> dict:
    """Return title and description for a competency at a specific level."""
    data = _load_competencies_yaml()
    comps = data.get("competencies", {})
    comp_data = comps.get(comp_id, {})
    if not comp_data and comp_id in _SCORING_TO_YAML_ALIASES:
        comp_data = comps.get(_SCORING_TO_YAML_ALIASES[comp_id], {})
    levels = comp_data.get("levels", {})
    return levels.get(level, {"title": "", "description": ""})


def get_competency_meta(comp_id: str, level: str | None = None) -> dict:
    """Return competency goal, description, and category for display.

    If level is provided, includes level-specific title and description
    from the engineering competencies YAML.
    """
    defn = COMPETENCY_DEFS.get(comp_id, {})
    meta = {
        "name": defn.get("name", comp_id.replace("_", " ").title()),
        "category": defn.get("category", "Other"),
        "goal": defn.get("goal", ""),
        "description": defn.get("description", ""),
    }
    if level:
        level_data = get_level_description(comp_id, level)
        if level_data.get("title"):
            meta["level_title"] = level_data["title"]
        if level_data.get("description"):
            meta["level_description"] = level_data["description"]
    return meta


def get_gap_suggestions(comp_id: str) -> list[str]:
    """Return actionable suggestions for improving a competency gap."""
    suggestions_map = {
        "technical_contribution": [
            "Submit more code reviews and merge requests",
            "Fix bugs or resolve Jira issues",
            "Contribute commits to upstream projects",
        ],
        "technical_knowledge": [
            "Write documentation or READMEs",
            "Create internal knowledge-base articles",
            "Document architecture decisions",
        ],
        "creativity_innovation": [
            "Run a proof-of-concept or prototype",
            "Experiment with new tools or AI features",
            "Propose innovative solutions in design reviews",
        ],
        "continuous_improvement": [
            "Improve CI/CD pipelines or automation",
            "Refactor legacy code for maintainability",
            "Introduce new tooling to the team",
        ],
        "leadership": [
            "Lead a cross-team initiative or design review",
            "Drive architecture decisions",
            "Mentor through code reviews with detailed feedback",
        ],
        "collaboration": [
            "Review more team members' code",
            "Pair-program on complex features",
            "Provide constructive feedback in reviews",
        ],
        "mentorship": [
            "Onboard a new team member",
            "Run a training session or knowledge share",
            "Create onboarding documentation",
        ],
        "speaking_publicity": [
            "Present at a team demo or all-hands",
            "Write a blog post about your work",
            "Give a lightning talk on a technical topic",
        ],
        "portfolio_impact": [
            "Work on customer-facing API changes",
            "Contribute to app-interface or schema changes",
            "Improve cross-service integration",
        ],
        "planning_execution": [
            "Create or refine Jira issues with clear acceptance criteria",
            "Run a sprint planning or roadmap session",
            "Break down large features into actionable tasks",
        ],
        "end_to_end_delivery": [
            "Ship a feature to production",
            "Deploy and validate a release",
            "Close the loop on a customer-reported issue",
        ],
        "opportunity_recognition": [
            "Contribute to open-source projects on GitHub",
            "Identify and document improvement opportunities",
            "Propose new features based on user feedback",
        ],
    }
    return suggestions_map.get(comp_id, ["Look for activities in this area"])
