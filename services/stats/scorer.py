import json
import logging

from server.paths import PERFORMANCE_DIR

logger = logging.getLogger(__name__)

COMPETENCY_DEFS: dict[str, dict] = {
    "technical_contribution": {
        "name": "Technical Contribution",
        "category": "Technical Excellence",
        "goal": "Deliver high-quality code through commits, merge requests, and bug fixes.",
        "description": (
            "Measures direct code contributions: commits, MRs merged, bugs fixed, "
            "and upstream patches. Each shipped change demonstrates hands-on engineering."
        ),
        "base_points": 2,
        "event_types": [
            "mr_merged",
            "issue_resolved",
            "commit",
            "pr_opened",
            "pr_merged",
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
        "category": "Technical Excellence",
        "goal": "Build and share technical knowledge through documentation and knowledge articles.",
        "description": (
            "Captures documentation work: READMEs, architecture docs, runbooks, "
            "knowledge-base articles, and technical blog posts."
        ),
        "base_points": 3,
        "event_types": [],
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
        ],
        "keywords": [
            "doc",
            "readme",
            "documentation",
            "wiki",
            "guide",
            "runbook",
            "adr",
        ],
    },
    "creativity_innovation": {
        "name": "Creativity & Innovation",
        "category": "Technical Excellence",
        "goal": "Drive innovation through prototypes, AI experiments, and creative solutions.",
        "description": (
            "Recognises work on proof-of-concepts, AI/ML experiments, novel tooling, "
            "and creative problem solving that goes beyond routine tasks."
        ),
        "base_points": 4,
        "event_types": [],
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
        ],
    },
    "continuous_improvement": {
        "name": "Continuous Improvement",
        "category": "Technical Excellence",
        "goal": "Improve engineering processes, CI/CD, automation, and code quality.",
        "description": (
            "Tracks process improvements: CI/CD pipeline enhancements, automation, "
            "refactoring for maintainability, linting, test coverage, and tooling upgrades."
        ),
        "base_points": 3,
        "event_types": [],
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
        "category": "Leadership & Influence",
        "goal": "Lead cross-team initiatives, architecture decisions, and design reviews.",
        "description": (
            "Recognises leadership actions: driving architecture decisions, leading "
            "design reviews, cross-team coordination, and setting technical direction."
        ),
        "base_points": 3,
        "event_types": [],
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
        ],
    },
    "collaboration": {
        "name": "Collaboration",
        "category": "Leadership & Influence",
        "goal": "Strengthen team collaboration through code reviews, pair programming, and feedback.",
        "description": (
            "Measures collaborative work: reviewing others' code, pair programming, "
            "providing constructive feedback, and contributing to team discussions."
        ),
        "base_points": 2,
        "event_types": ["review_given", "pr_reviewed"],
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
        "category": "Leadership & Influence",
        "goal": "Grow others through mentoring, onboarding, training, and knowledge sharing.",
        "description": (
            "Captures mentoring activities: onboarding new hires, running training "
            "sessions, knowledge-sharing talks, and supporting junior team members."
        ),
        "base_points": 3,
        "event_types": [],
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
        "category": "Leadership & Influence",
        "goal": "Represent the team through presentations, blog posts, and public speaking.",
        "description": (
            "Tracks public-facing activities: conference talks, team demos, blog posts, "
            "lightning talks, and any outward communication about the team's work."
        ),
        "base_points": 4,
        "event_types": [],
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
        ],
    },
    "portfolio_impact": {
        "name": "Portfolio Impact",
        "category": "Delivery & Impact",
        "goal": "Deliver cross-cutting impact through APIs, schemas, and service integrations.",
        "description": (
            "Measures work that spans multiple services or products: API design, "
            "schema changes, app-interface updates, and cross-service integrations."
        ),
        "base_points": 4,
        "event_types": [],
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
        "category": "Delivery & Impact",
        "goal": "Plan and break down work into well-defined, actionable tasks.",
        "description": (
            "Recognises planning work: creating Jira issues with clear acceptance "
            "criteria, sprint planning, roadmap contributions, and task breakdown."
        ),
        "base_points": 2,
        "event_types": ["issue_created", "issue_opened", "issue_closed"],
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
        ],
    },
    "end_to_end_delivery": {
        "name": "End-to-End Delivery",
        "category": "Delivery & Impact",
        "goal": "Ship features from development all the way to production.",
        "description": (
            "Tracks full delivery lifecycle: releasing to production, deploying "
            "and validating, customer-facing fixes, and closing delivery loops."
        ),
        "base_points": 3,
        "event_types": ["pr_merged"],
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
        ],
    },
    "opportunity_recognition": {
        "name": "Opportunity Recognition",
        "category": "Delivery & Impact",
        "goal": "Identify opportunities and contribute beyond assigned work, including open-source.",
        "description": (
            "Measures proactive contributions: open-source work on GitHub, identifying "
            "improvement opportunities, proposing new features, and self-directed initiatives."
        ),
        "base_points": 4,
        "event_types": [],
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
        ],
        "keywords": [
            "open-source",
            "github",
            "upstream",
            "community",
            "volunteer",
            "initiative",
            "opportunity",
        ],
    },
}

DEFAULT_GLOBALS = {
    "min_signals": 2,
    "daily_cap": 15,
    "target_per_competency": 100,
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
            for field in ("base_points", "phrases", "keywords", "event_types"):
                if field in uc:
                    base[field] = uc[field]
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


def map_competencies(title: str, source: str, event_type: str) -> dict[str, int]:
    """Map an event to competency points using configurable scoring.

    An event must accumulate at least min_signals distinct indicator
    matches against a competency before any points are awarded.

    Signal types counted (each distinct hit = 1 signal):
      - event_type match: 1 signal
      - each matching phrase: 1 signal per phrase
      - each matching keyword: 1 signal per keyword
      - source-level rule: 1 signal
    """
    defs, min_sig, _, _ = get_effective_defs()
    points: dict[str, int] = {}
    text = title.lower()

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

        if signals >= min_sig:
            points[comp_id] = defn["base_points"]

    if source == "github" and "opportunity_recognition" in defs:
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
        if extra_signals >= min_sig:
            points[comp_id] = max(
                points.get(comp_id, 0),
                defn["base_points"],
            )

    return points


def get_competency_meta(comp_id: str) -> dict:
    """Return competency goal, description, and category for display."""
    defn = COMPETENCY_DEFS.get(comp_id, {})
    return {
        "name": defn.get("name", comp_id.replace("_", " ").title()),
        "category": defn.get("category", "Other"),
        "goal": defn.get("goal", ""),
        "description": defn.get("description", ""),
    }


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
