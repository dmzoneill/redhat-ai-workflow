"""Knowledge Tools - Project-specific expertise loading and learning.

Provides tools for:
- knowledge_load: Load project knowledge for a persona
- knowledge_scan: AI scans project, generates initial knowledge
- knowledge_update: Update specific section of knowledge
- knowledge_query: Query specific knowledge sections
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from mcp.types import TextContent

from server.tool_registry import ToolRegistry
from server.utils import load_config

# Support both package import and direct loading
try:
    from .constants import MEMORY_DIR, PROJECT_DIR
except ImportError:
    TOOL_MODULES_DIR = Path(__file__).parent.parent.parent
    PROJECT_DIR = TOOL_MODULES_DIR.parent
    MEMORY_DIR = PROJECT_DIR / "memory"

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Knowledge directory structure
KNOWLEDGE_DIR = MEMORY_DIR / "knowledge" / "personas"

# Notification thresholds
SIGNIFICANT_LEARNING_COUNT = 5  # Notify after this many learnings
CONFIDENCE_MILESTONE = 0.7  # Notify when confidence reaches this level

# Default knowledge schema
DEFAULT_KNOWLEDGE_SCHEMA = {
    "metadata": {
        "project": "",
        "persona": "",
        "last_updated": "",
        "last_scanned": "",
        "confidence": 0.5,
    },
    "architecture": {
        "overview": "",
        "key_modules": [],
        "data_flow": "",
        "dependencies": [],
    },
    "patterns": {
        "coding": [],
        "testing": [],
        "deployment": [],
    },
    "gotchas": [],
    "learned_from_tasks": [],
}


# ==================== HELPER FUNCTIONS ====================


def _get_knowledge_path(persona: str, project: str) -> Path:
    """Get the path to a knowledge file."""
    return KNOWLEDGE_DIR / persona / f"{project}.yaml"


def _ensure_knowledge_dir(persona: str) -> Path:
    """Ensure the knowledge directory exists for a persona."""
    persona_dir = KNOWLEDGE_DIR / persona
    persona_dir.mkdir(parents=True, exist_ok=True)
    return persona_dir


def _load_knowledge(persona: str, project: str) -> dict | None:
    """Load knowledge from file, return None if not found."""
    knowledge_path = _get_knowledge_path(persona, project)
    if not knowledge_path.exists():
        return None

    try:
        with open(knowledge_path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning(f"Failed to load knowledge {knowledge_path}: {e}")
        return None


def _save_knowledge(persona: str, project: str, knowledge: dict) -> bool:
    """Save knowledge to file."""
    _ensure_knowledge_dir(persona)
    knowledge_path = _get_knowledge_path(persona, project)

    # Check for significant changes before saving
    old_knowledge = _load_knowledge(persona, project)
    notifications = _check_for_significant_changes(old_knowledge, knowledge, project, persona)

    try:
        # Update metadata
        knowledge.setdefault("metadata", {})
        knowledge["metadata"]["last_updated"] = datetime.now().isoformat()
        knowledge["metadata"]["project"] = project
        knowledge["metadata"]["persona"] = persona

        with open(knowledge_path, "w") as f:
            yaml.dump(knowledge, f, default_flow_style=False, sort_keys=False)

        # Log notifications
        for notification in notifications:
            logger.info(f"📚 Knowledge milestone: {notification}")

        return True
    except Exception as e:
        logger.error(f"Failed to save knowledge {knowledge_path}: {e}")
        return False


def _check_for_significant_changes(
    old_knowledge: dict | None,
    new_knowledge: dict,
    project: str,
    persona: str,
) -> list[str]:
    """Check for significant knowledge changes and return notification messages."""
    notifications = []

    if not old_knowledge:
        notifications.append(f"New knowledge created for {project}/{persona}")
        return notifications

    old_meta = old_knowledge.get("metadata", {})
    new_meta = new_knowledge.get("metadata", {})

    # Check confidence milestone
    old_confidence = old_meta.get("confidence", 0)
    new_confidence = new_meta.get("confidence", 0)

    if old_confidence < CONFIDENCE_MILESTONE <= new_confidence:
        notifications.append(f"🎉 Knowledge confidence reached {new_confidence:.0%} for {project}/{persona}!")

    # Check learning count milestones
    old_learnings = len(old_knowledge.get("learned_from_tasks", []))
    new_learnings = len(new_knowledge.get("learned_from_tasks", []))

    if new_learnings > old_learnings:
        # Check for milestone (every 5 learnings)
        if new_learnings // SIGNIFICANT_LEARNING_COUNT > old_learnings // SIGNIFICANT_LEARNING_COUNT:
            notifications.append(f"📈 {new_learnings} learnings recorded for {project}/{persona}")

    # Check gotchas count
    old_gotchas = len(old_knowledge.get("gotchas", []))
    new_gotchas = len(new_knowledge.get("gotchas", []))

    if new_gotchas > old_gotchas:
        notifications.append(f"⚠️ New gotcha added for {project}/{persona} (total: {new_gotchas})")

    return notifications


def _emit_knowledge_notification(message: str, project: str, persona: str) -> None:
    """Emit a knowledge notification (can be extended to Slack, etc.)."""
    try:
        # Log to session
        session_file = MEMORY_DIR / "sessions" / f"{datetime.now().strftime('%Y-%m-%d')}.yaml"
        if session_file.exists():
            with open(session_file) as f:
                session = yaml.safe_load(f) or {}
        else:
            session = {"date": datetime.now().strftime("%Y-%m-%d"), "entries": []}

        session.setdefault("entries", []).append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": f"Knowledge: {message}",
                "details": f"project={project}, persona={persona}",
            }
        )

        with open(session_file, "w") as f:
            yaml.dump(session, f, default_flow_style=False)

    except Exception as e:
        logger.warning(f"Failed to emit knowledge notification: {e}")


def _detect_project_from_path(path: str | Path | None = None) -> str | None:
    """Detect project from a path by matching against config.json repositories."""
    config = load_config()
    if not config:
        return None

    # Use provided path or try to get cwd
    if path:
        check_path = Path(path).resolve()
    else:
        try:
            check_path = Path.cwd().resolve()
        except Exception:
            return None

    repositories = config.get("repositories", {})
    for project_name, project_config in repositories.items():
        project_path = Path(project_config.get("path", "")).expanduser().resolve()
        # Check if check_path is the project path or a subdirectory
        try:
            check_path.relative_to(project_path)
            return project_name
        except ValueError:
            continue

    return None


def _get_current_persona() -> str | None:
    """Get the currently loaded persona from the persona loader."""
    try:
        from server.persona_loader import get_loader

        loader = get_loader()
        if loader:
            return loader.current_persona
    except Exception:
        pass
    return None


def _scan_project_structure(project_path: Path) -> dict:
    """Scan a project's structure and return key information."""
    result = {
        "files": [],
        "directories": [],
        "config_files": [],
        "test_files": [],
        "readme": None,
        "dependencies": [],
    }

    if not project_path.exists():
        return result

    # Key files to look for
    config_patterns = [
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "Makefile",
        ".gitlab-ci.yml",
        "Dockerfile",
        "docker-compose.yml",
    ]

    readme_patterns = ["README.md", "README.rst", "README.txt", "README"]

    # Scan top-level
    for item in project_path.iterdir():
        if item.is_file():
            if item.name in config_patterns:
                result["config_files"].append(item.name)
            if item.name.upper() in [p.upper() for p in readme_patterns]:
                result["readme"] = item.name
        elif item.is_dir() and not item.name.startswith("."):
            result["directories"].append(item.name)

    # Look for test directories
    test_dirs = ["tests", "test", "spec", "specs"]
    for test_dir in test_dirs:
        test_path = project_path / test_dir
        if test_path.exists():
            result["test_files"] = [f.name for f in test_path.glob("*.py")][:10]
            break

    # Parse dependencies from config files
    if "pyproject.toml" in result["config_files"]:
        try:
            import tomllib

            with open(project_path / "pyproject.toml", "rb") as f:
                pyproject = tomllib.load(f)
            deps = pyproject.get("project", {}).get("dependencies", [])
            result["dependencies"] = [d.split("[")[0].split(">=")[0].split("==")[0] for d in deps[:20]]
        except Exception:
            pass

    if "package.json" in result["config_files"]:
        try:
            with open(project_path / "package.json") as f:
                pkg = json.load(f)
            deps = list(pkg.get("dependencies", {}).keys())[:20]
            result["dependencies"] = deps
        except Exception:
            pass

    return result


def _generate_initial_knowledge(project: str, persona: str, project_path: Path) -> dict:
    """Generate initial knowledge by scanning a project."""
    structure = _scan_project_structure(project_path)

    # Read README if available
    overview = ""
    if structure["readme"]:
        try:
            readme_path = project_path / structure["readme"]
            readme_content = readme_path.read_text()[:2000]  # First 2000 chars
            # Extract first paragraph as overview
            paragraphs = readme_content.split("\n\n")
            for p in paragraphs:
                if p.strip() and not p.startswith("#"):
                    overview = p.strip()[:500]
                    break
        except Exception:
            pass

    # Build key modules from directory structure
    key_modules = []
    important_dirs = ["src", "lib", "app", "api", "core", "services", "models", "utils"]
    for dir_name in structure["directories"]:
        if dir_name.lower() in important_dirs or dir_name in ["tests", "test"]:
            key_modules.append(
                {
                    "path": f"{dir_name}/",
                    "purpose": f"{dir_name.title()} module",
                    "notes": "Auto-detected from project structure",
                }
            )

    # Determine project type and patterns based on config files
    patterns = {"coding": [], "testing": [], "deployment": []}

    if "pyproject.toml" in structure["config_files"] or "setup.py" in structure["config_files"]:
        patterns["coding"].append({"pattern": "Python project", "location": "pyproject.toml"})
        if structure["test_files"]:
            patterns["testing"].append({"pattern": "pytest test suite", "example": "pytest tests/"})

    if "package.json" in structure["config_files"]:
        patterns["coding"].append({"pattern": "Node.js/JavaScript project", "location": "package.json"})

    if ".gitlab-ci.yml" in structure["config_files"]:
        patterns["deployment"].append({"pattern": "GitLab CI/CD", "notes": "Pipeline defined in .gitlab-ci.yml"})

    if "Dockerfile" in structure["config_files"]:
        patterns["deployment"].append({"pattern": "Docker containerization", "notes": "Dockerfile present"})

    # Build the knowledge structure
    knowledge = {
        "metadata": {
            "project": project,
            "persona": persona,
            "last_updated": datetime.now().isoformat(),
            "last_scanned": datetime.now().isoformat(),
            "confidence": 0.3,  # Low confidence for auto-generated
            "auto_generated": True,
        },
        "architecture": {
            "overview": overview or f"Project: {project}",
            "key_modules": key_modules,
            "data_flow": "",
            "dependencies": structure["dependencies"],
        },
        "patterns": patterns,
        "gotchas": [],
        "learned_from_tasks": [],
    }

    return knowledge


def _format_knowledge_summary(knowledge: dict) -> str:
    """Format knowledge into a readable summary."""
    lines = []

    metadata = knowledge.get("metadata", {})
    lines.append(f"## 📚 Project Knowledge: {metadata.get('project', 'Unknown')}")
    lines.append(f"*Persona: {metadata.get('persona', 'Unknown')}*")
    lines.append(f"*Last updated: {metadata.get('last_updated', 'Never')}*")
    confidence = metadata.get("confidence", 0)
    confidence_emoji = "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"
    lines.append(f"*Confidence: {confidence_emoji} {confidence:.0%}*\n")

    # Architecture
    arch = knowledge.get("architecture", {})
    if arch.get("overview"):
        lines.append("### 🏗️ Architecture")
        lines.append(arch["overview"])
        lines.append("")

    if arch.get("key_modules"):
        lines.append("### 📁 Key Modules")
        for module in arch["key_modules"][:5]:
            lines.append(f"- **{module.get('path', '?')}**: {module.get('purpose', '')}")
        lines.append("")

    if arch.get("dependencies"):
        deps = arch["dependencies"][:10]
        lines.append(f"### 📦 Dependencies ({len(arch['dependencies'])} total)")
        lines.append(", ".join(f"`{d}`" for d in deps))
        lines.append("")

    # Patterns
    patterns = knowledge.get("patterns", {})
    pattern_count = sum(len(v) for v in patterns.values() if isinstance(v, list))
    if pattern_count > 0:
        lines.append(f"### 🔄 Patterns ({pattern_count} total)")
        for category, items in patterns.items():
            if items:
                lines.append(f"**{category.title()}:**")
                for item in items[:3]:
                    lines.append(f"- {item.get('pattern', str(item))}")
        lines.append("")

    # Gotchas
    gotchas = knowledge.get("gotchas", [])
    if gotchas:
        lines.append(f"### ⚠️ Gotchas ({len(gotchas)})")
        for gotcha in gotchas[:3]:
            lines.append(f"- **{gotcha.get('issue', '?')}**: {gotcha.get('solution', '')}")
        lines.append("")

    # Learned from tasks
    learned = knowledge.get("learned_from_tasks", [])
    if learned:
        lines.append(f"### 📝 Learned from Tasks ({len(learned)})")
        for item in learned[-3:]:  # Show most recent
            lines.append(f"- [{item.get('date', '?')}] {item.get('task', '?')}: {item.get('learning', '')[:100]}")
        lines.append("")

    return "\n".join(lines)


# ==================== TOOL IMPLEMENTATIONS ====================


async def _knowledge_load_impl(
    project: str = "",
    persona: str = "",
    auto_scan: bool = True,
) -> list[TextContent]:
    """
    Load project knowledge for a persona.

    If knowledge doesn't exist and auto_scan is True, will scan the project
    and generate initial knowledge.

    Args:
        project: Project name (from config.json). Auto-detected from cwd if empty.
        persona: Persona name. Uses current persona if empty.
        auto_scan: If True, auto-scan project when knowledge doesn't exist.

    Returns:
        Project knowledge formatted for context injection.
    """
    # Auto-detect project if not provided
    if not project:
        project = _detect_project_from_path()
        if not project:
            return [
                TextContent(
                    type="text",
                    text="❌ Could not detect project from current directory.\n\n"
                    "Provide project name explicitly: `knowledge_load(project='automation-analytics-backend')`",
                )
            ]

    # Auto-detect persona if not provided
    if not persona:
        persona = _get_current_persona() or "developer"

    # Try to load existing knowledge
    knowledge = _load_knowledge(persona, project)

    if knowledge:
        summary = _format_knowledge_summary(knowledge)
        return [TextContent(type="text", text=summary)]

    # Knowledge doesn't exist
    if not auto_scan:
        return [
            TextContent(
                type="text",
                text=f"❌ No knowledge found for project '{project}' with persona '{persona}'.\n\n"
                f"Run `knowledge_scan(project='{project}')` to generate initial knowledge.",
            )
        ]

    # Auto-scan: get project path from config
    config = load_config()
    project_config = config.get("repositories", {}).get(project)
    if not project_config:
        return [
            TextContent(
                type="text",
                text=f"❌ Project '{project}' not found in config.json.\n\n"
                f"Available projects: {', '.join(config.get('repositories', {}).keys())}",
            )
        ]

    project_path = Path(project_config.get("path", "")).expanduser()
    if not project_path.exists():
        return [
            TextContent(
                type="text",
                text=f"❌ Project path does not exist: {project_path}",
            )
        ]

    # Generate initial knowledge
    knowledge = _generate_initial_knowledge(project, persona, project_path)
    _save_knowledge(persona, project, knowledge)

    summary = _format_knowledge_summary(knowledge)
    return [
        TextContent(
            type="text",
            text=f"🔍 **Auto-scanned project and generated initial knowledge**\n\n{summary}\n\n"
            "*This is auto-generated knowledge with low confidence. "
            "It will improve as you work on tasks.*",
        )
    ]


async def _knowledge_scan_impl(
    project: str = "",
    persona: str = "",
    force: bool = False,
) -> list[TextContent]:
    """
    Scan a project and generate/update knowledge.

    Args:
        project: Project name (from config.json). Auto-detected from cwd if empty.
        persona: Persona name. Uses current persona if empty.
        force: If True, overwrite existing knowledge. Otherwise merge.

    Returns:
        Summary of scanned knowledge.
    """
    # Auto-detect project if not provided
    if not project:
        project = _detect_project_from_path()
        if not project:
            return [
                TextContent(
                    type="text",
                    text="❌ Could not detect project from current directory.\n\n"
                    "Provide project name explicitly: `knowledge_scan(project='automation-analytics-backend')`",
                )
            ]

    # Auto-detect persona if not provided
    if not persona:
        persona = _get_current_persona() or "developer"

    # Get project path from config
    config = load_config()
    project_config = config.get("repositories", {}).get(project)
    if not project_config:
        return [
            TextContent(
                type="text",
                text=f"❌ Project '{project}' not found in config.json.\n\n"
                f"Available projects: {', '.join(config.get('repositories', {}).keys())}",
            )
        ]

    project_path = Path(project_config.get("path", "")).expanduser()
    if not project_path.exists():
        return [
            TextContent(
                type="text",
                text=f"❌ Project path does not exist: {project_path}",
            )
        ]

    # Load existing knowledge if not forcing
    existing = None if force else _load_knowledge(persona, project)

    # Generate new knowledge
    new_knowledge = _generate_initial_knowledge(project, persona, project_path)

    if existing and not force:
        # Merge: keep existing learned items, update structure
        new_knowledge["gotchas"] = existing.get("gotchas", [])
        new_knowledge["learned_from_tasks"] = existing.get("learned_from_tasks", [])

        # Merge patterns (keep existing, add new)
        for category in ["coding", "testing", "deployment"]:
            existing_patterns = existing.get("patterns", {}).get(category, [])
            new_patterns = new_knowledge.get("patterns", {}).get(category, [])
            # Deduplicate by pattern text
            existing_texts = {p.get("pattern", "") for p in existing_patterns}
            merged = existing_patterns + [p for p in new_patterns if p.get("pattern", "") not in existing_texts]
            new_knowledge["patterns"][category] = merged

        # Increase confidence if we had existing knowledge
        new_knowledge["metadata"]["confidence"] = min(existing.get("metadata", {}).get("confidence", 0.3) + 0.1, 1.0)

    _save_knowledge(persona, project, new_knowledge)

    summary = _format_knowledge_summary(new_knowledge)
    action = "Rescanned and updated" if existing else "Scanned and created"
    return [
        TextContent(
            type="text",
            text=f"✅ **{action} knowledge for {project} ({persona})**\n\n{summary}",
        )
    ]


async def _knowledge_update_impl(
    project: str,
    persona: str,
    section: str,
    content: str,
    append: bool = True,
) -> list[TextContent]:
    """
    Update a specific section of project knowledge.

    Args:
        project: Project name
        persona: Persona name
        section: Section to update (e.g., "gotchas", "patterns.coding", "architecture.overview")
        content: Content to add (YAML string for complex data, plain string for simple)
        append: If True, append to lists. If False, replace.

    Returns:
        Confirmation of update.
    """
    knowledge = _load_knowledge(persona, project)
    if not knowledge:
        return [
            TextContent(
                type="text",
                text=f"❌ No knowledge found for {project}/{persona}.\n\n"
                f"Run `knowledge_scan(project='{project}', persona='{persona}')` first.",
            )
        ]

    try:
        # Parse content
        try:
            parsed_content = yaml.safe_load(content)
        except yaml.YAMLError:
            parsed_content = content

        # Navigate to section
        parts = section.split(".")
        target = knowledge
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        final_key = parts[-1]

        # Update based on type and append flag
        if append and isinstance(target.get(final_key), list):
            if isinstance(parsed_content, list):
                target[final_key].extend(parsed_content)
            else:
                target[final_key].append(parsed_content)
        else:
            target[final_key] = parsed_content

        # Increase confidence slightly on manual updates
        knowledge["metadata"]["confidence"] = min(knowledge.get("metadata", {}).get("confidence", 0.5) + 0.05, 1.0)

        _save_knowledge(persona, project, knowledge)

        return [
            TextContent(
                type="text",
                text=f"✅ Updated knowledge: {project}/{persona} → {section}\n\n"
                f"*Confidence: {knowledge['metadata']['confidence']:.0%}*",
            )
        ]

    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error updating knowledge: {e}")]


async def _knowledge_query_impl(
    project: str = "",
    persona: str = "",
    section: str = "",
) -> list[TextContent]:
    """
    Query specific knowledge sections.

    Args:
        project: Project name. Auto-detected if empty.
        persona: Persona name. Uses current if empty.
        section: Dot-separated path to query (e.g., "architecture.key_modules", "gotchas")
                 Empty returns full knowledge.

    Returns:
        Requested knowledge section.
    """
    # Auto-detect
    if not project:
        project = _detect_project_from_path()
        if not project:
            return [
                TextContent(
                    type="text",
                    text="❌ Could not detect project. Provide project name explicitly.",
                )
            ]

    if not persona:
        persona = _get_current_persona() or "developer"

    knowledge = _load_knowledge(persona, project)
    if not knowledge:
        return [
            TextContent(
                type="text",
                text=f"❌ No knowledge found for {project}/{persona}.",
            )
        ]

    if not section:
        # Return full knowledge
        summary = _format_knowledge_summary(knowledge)
        return [TextContent(type="text", text=summary)]

    # Navigate to section
    try:
        parts = section.split(".")
        result = knowledge
        for part in parts:
            result = result[part]

        # Format result
        if isinstance(result, (dict, list)):
            formatted = yaml.dump(result, default_flow_style=False)
            return [
                TextContent(
                    type="text",
                    text=f"## Knowledge: {project}/{persona} → {section}\n\n```yaml\n{formatted}```",
                )
            ]
        else:
            return [
                TextContent(
                    type="text",
                    text=f"## Knowledge: {project}/{persona} → {section}\n\n{result}",
                )
            ]

    except KeyError:
        return [
            TextContent(
                type="text",
                text=f"❌ Section not found: {section}\n\n"
                f"Available sections: metadata, architecture, patterns, gotchas, learned_from_tasks",
            )
        ]


async def _knowledge_learn_impl(
    learning: str,
    task: str = "",
    section: str = "learned_from_tasks",
    project: str = "",
    persona: str = "",
) -> list[TextContent]:
    """
    Record a learning from completing a task.

    This is the primary way knowledge grows over time. Call this after
    completing tasks, fixing bugs, or discovering patterns.

    Args:
        learning: What was learned (the insight)
        task: Task/issue that led to this learning (e.g., "AAP-12345")
        section: Where to store (default: learned_from_tasks, can be "gotchas", "patterns.coding", etc.)
        project: Project name. Auto-detected if empty.
        persona: Persona name. Uses current if empty.

    Returns:
        Confirmation of learning recorded.
    """
    # Auto-detect
    if not project:
        project = _detect_project_from_path()
        if not project:
            return [
                TextContent(
                    type="text",
                    text="❌ Could not detect project. Provide project name explicitly.",
                )
            ]

    if not persona:
        persona = _get_current_persona() or "developer"

    # Load or create knowledge
    knowledge = _load_knowledge(persona, project)
    if not knowledge:
        # Create minimal knowledge structure
        knowledge = dict(DEFAULT_KNOWLEDGE_SCHEMA)
        knowledge["metadata"]["project"] = project
        knowledge["metadata"]["persona"] = persona

    # Build the learning entry
    if section == "learned_from_tasks":
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "task": task or "manual",
            "learning": learning,
        }
    elif section == "gotchas":
        entry = {
            "issue": learning,
            "reason": "",
            "solution": "",
        }
    elif section.startswith("patterns."):
        entry = {
            "pattern": learning,
            "example": "",
            "location": "",
        }
    else:
        entry = learning

    # Navigate and append
    parts = section.split(".")
    target = knowledge
    for part in parts[:-1]:
        if part not in target:
            target[part] = {}
        target = target[part]

    final_key = parts[-1]
    if final_key not in target:
        target[final_key] = []

    if isinstance(target[final_key], list):
        target[final_key].append(entry)
    else:
        target[final_key] = entry

    # Increase confidence
    knowledge["metadata"]["confidence"] = min(knowledge.get("metadata", {}).get("confidence", 0.5) + 0.02, 1.0)

    _save_knowledge(persona, project, knowledge)

    return [
        TextContent(
            type="text",
            text=f"✅ **Learning recorded!**\n\n"
            f"**Project:** {project}\n"
            f"**Persona:** {persona}\n"
            f"**Section:** {section}\n"
            f"**Task:** {task or 'N/A'}\n"
            f"**Learning:** {learning[:200]}{'...' if len(learning) > 200 else ''}\n\n"
            f"*Knowledge confidence: {knowledge['metadata']['confidence']:.0%}*",
        )
    ]


async def _knowledge_list_impl() -> list[TextContent]:
    """
    List all available knowledge files.

    Returns:
        List of knowledge files organized by persona and project.
    """
    if not KNOWLEDGE_DIR.exists():
        return [
            TextContent(
                type="text",
                text="📚 **No knowledge files yet.**\n\n"
                "Knowledge will be auto-generated when you start working on projects.\n"
                "Or run `knowledge_scan(project='...')` to generate manually.",
            )
        ]

    lines = ["## 📚 Available Knowledge\n"]

    for persona_dir in sorted(KNOWLEDGE_DIR.iterdir()):
        if not persona_dir.is_dir():
            continue

        persona = persona_dir.name
        knowledge_files = list(persona_dir.glob("*.yaml"))

        if knowledge_files:
            lines.append(f"### 🎭 {persona.title()}")
            for kf in sorted(knowledge_files):
                project = kf.stem
                # Load to get confidence
                try:
                    with open(kf) as f:
                        data = yaml.safe_load(f) or {}
                    confidence = data.get("metadata", {}).get("confidence", 0)
                    confidence_emoji = "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"
                    last_updated = data.get("metadata", {}).get("last_updated", "?")[:10]
                    lines.append(f"- **{project}** {confidence_emoji} {confidence:.0%} (updated: {last_updated})")
                except Exception:
                    lines.append(f"- **{project}** ❓")
            lines.append("")

    if len(lines) == 1:
        lines.append("*No knowledge files found.*")

    return [TextContent(type="text", text="\n".join(lines))]


# ==================== TOOL REGISTRATION ====================


def register_tools(server: "FastMCP") -> int:
    """Register knowledge tools with the MCP server."""
    registry = ToolRegistry(server)

    @registry.tool()
    async def knowledge_load(
        project: str = "",
        persona: str = "",
        auto_scan: bool = True,
    ) -> list[TextContent]:
        """
        Load project knowledge for a persona into context.

        Loads project-specific expertise including architecture, patterns,
        gotchas, and learnings. If knowledge doesn't exist and auto_scan
        is True, will scan the project and generate initial knowledge.

        Args:
            project: Project name (from config.json). Auto-detected from cwd if empty.
            persona: Persona name. Uses current persona if empty.
            auto_scan: If True, auto-scan project when knowledge doesn't exist.

        Returns:
            Project knowledge formatted for context injection.
        """
        return await _knowledge_load_impl(project, persona, auto_scan)

    @registry.tool()
    async def knowledge_scan(
        project: str = "",
        persona: str = "",
        force: bool = False,
    ) -> list[TextContent]:
        """
        Scan a project and generate/update knowledge.

        Analyzes project structure, config files, dependencies, and README
        to build initial knowledge. Merges with existing knowledge unless
        force=True.

        Args:
            project: Project name (from config.json). Auto-detected from cwd if empty.
            persona: Persona name. Uses current persona if empty.
            force: If True, overwrite existing knowledge. Otherwise merge.

        Returns:
            Summary of scanned knowledge.
        """
        return await _knowledge_scan_impl(project, persona, force)

    @registry.tool()
    async def knowledge_update(
        project: str,
        persona: str,
        section: str,
        content: str,
        append: bool = True,
    ) -> list[TextContent]:
        """
        Update a specific section of project knowledge.

        Use this to manually add or update knowledge sections like
        architecture details, patterns, or gotchas.

        Args:
            project: Project name
            persona: Persona name
            section: Section to update (e.g., "gotchas", "patterns.coding", "architecture.overview")
            content: Content to add (YAML string for complex data, plain string for simple)
            append: If True, append to lists. If False, replace.

        Returns:
            Confirmation of update.
        """
        return await _knowledge_update_impl(project, persona, section, content, append)

    @registry.tool()
    async def knowledge_query(
        project: str = "",
        persona: str = "",
        section: str = "",
    ) -> list[TextContent]:
        """
        Query specific knowledge sections.

        Retrieve specific parts of project knowledge without loading
        the full context.

        Args:
            project: Project name. Auto-detected if empty.
            persona: Persona name. Uses current if empty.
            section: Dot-separated path to query (e.g., "architecture.key_modules", "gotchas")
                     Empty returns full knowledge summary.

        Returns:
            Requested knowledge section.
        """
        return await _knowledge_query_impl(project, persona, section)

    @registry.tool()
    async def knowledge_learn(
        learning: str,
        task: str = "",
        section: str = "learned_from_tasks",
        project: str = "",
        persona: str = "",
    ) -> list[TextContent]:
        """
        Record a learning from completing a task.

        This is the primary way knowledge grows over time. Call this after
        completing tasks, fixing bugs, or discovering patterns.

        Args:
            learning: What was learned (the insight)
            task: Task/issue that led to this learning (e.g., "AAP-12345")
            section: Where to store (default: learned_from_tasks, can be "gotchas", "patterns.coding", etc.)
            project: Project name. Auto-detected if empty.
            persona: Persona name. Uses current if empty.

        Returns:
            Confirmation of learning recorded.
        """
        return await _knowledge_learn_impl(learning, task, section, project, persona)

    @registry.tool()
    async def knowledge_list() -> list[TextContent]:
        """
        List all available knowledge files.

        Shows all knowledge organized by persona and project, with
        confidence levels and last update dates.

        Returns:
            List of knowledge files organized by persona and project.
        """
        return await _knowledge_list_impl()

    return registry.count
