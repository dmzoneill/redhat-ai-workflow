"""
Common memory helpers for skills.

These functions provide a consistent interface for reading and writing
to memory files, reducing code duplication across skills.

Memory directory structure:
  ~/src/redhat-ai-workflow/memory/
  ├── state/
  │   ├── projects/           - Project-specific state
  │   │   └── <project>/
  │   │       └── current_work.yaml  - Active issues, MRs, follow-ups
  │   └── environments.yaml  - Stage/prod health, namespaces
  ├── learned/
  │   ├── patterns.yaml      - Error patterns for debugging
  │   ├── runbooks.yaml      - Operational procedures
  │   ├── teammate_preferences.yaml
  │   └── service_quirks.yaml
  └── logs/
      └── YYYY-MM-DD.yaml    - Session logs

Project-specific state:
  Work state (current_work) is stored per-project to avoid mixing
  issues/MRs from different codebases. Use get_project_memory_path()
  for project-specific files.
"""

import fcntl
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Memory directory - relative to project root (memory.py is in scripts/common/)
MEMORY_DIR = Path(__file__).parent.parent.parent / "memory"

# Keys that are project-specific (stored per-project)
PROJECT_SPECIFIC_KEYS = {"state/current_work"}

logger = logging.getLogger(__name__)


def _get_current_project() -> str:
    """Get the current project from environment or default.

    Skills should set AA_CURRENT_PROJECT env var when running.
    Falls back to detecting from cwd or using default.
    """
    # Check environment variable first (set by skill runner)
    project = os.environ.get("AA_CURRENT_PROJECT")
    if project:
        return project

    # Try to detect from cwd using ConfigManager
    try:
        from server.config_manager import config as config_manager

        cwd = Path.cwd().resolve()
        repositories = config_manager.get("repositories", default={})
        for project_name, project_config in repositories.items():
            project_path = Path(project_config.get("path", "")).expanduser().resolve()
            try:
                cwd.relative_to(project_path)
                return project_name
            except ValueError:
                continue
    except Exception as e:
        logger.debug(f"Error detecting project from cwd: {e}")

    # Default to redhat-ai-workflow
    return "redhat-ai-workflow"


def get_memory_path(key: str, project: Optional[str] = None) -> Path:
    """
    Get the full path to a memory file.

    For project-specific keys (like state/current_work), routes to the
    project's directory under memory/state/projects/<project>/.

    Args:
        key: Memory key like "state/current_work" or "learned/patterns"
        project: Project name for project-specific keys. Auto-detected if None.

    Returns:
        Full path to the memory file (with .yaml extension)
    """
    # Normalize key
    key_normalized = key.replace(".yaml", "") if key.endswith(".yaml") else key

    # Check if this is a project-specific key
    if key_normalized in PROJECT_SPECIFIC_KEYS:
        if project is None:
            project = _get_current_project()
        # Route to project-specific path
        # state/current_work -> state/projects/<project>/current_work.yaml
        parts = key_normalized.split("/")
        if len(parts) == 2:
            return MEMORY_DIR / parts[0] / "projects" / project / f"{parts[1]}.yaml"

    # Global path
    if not key.endswith(".yaml"):
        key = f"{key}.yaml"
    return MEMORY_DIR / key


def get_project_memory_path(project: str, filename: str = "current_work") -> Path:
    """
    Get the path to a project-specific memory file.

    Args:
        project: Project name (e.g., "automation-analytics-backend")
        filename: File name without extension (default: "current_work")

    Returns:
        Full path to the project's memory file
    """
    return MEMORY_DIR / "state" / "projects" / project / f"{filename}.yaml"


def read_memory(key: str) -> Dict[str, Any]:
    """
    Read a memory file.

    Args:
        key: Memory key like "state/current_work"

    Returns:
        Dict containing the memory file contents, or empty dict if not found
    """
    path = get_memory_path(key)
    if path.exists():
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except (yaml.YAMLError, IOError):
            return {}
    return {}


def write_memory(key: str, data: Dict[str, Any], validate: bool = True) -> bool:
    """
    Write a memory file with optional schema validation.

    Args:
        key: Memory key like "state/current_work"
        data: Dict to write
        validate: Whether to validate against schema (default: True)

    Returns:
        True if successful, False otherwise
    """
    path = get_memory_path(key)

    # Validate against schema before writing (if requested)
    if validate:
        try:
            from scripts.common.memory_schemas import validate_memory

            # Normalize key (remove .yaml extension for schema lookup)
            schema_key = key.replace(".yaml", "")

            if not validate_memory(schema_key, data):
                logger.warning(f"Schema validation failed for {key} - writing anyway")
                # Still write, but log the validation failure
        except ImportError:
            # Schema validation not available, skip
            pass
        except Exception as e:
            logger.debug(f"Schema validation error: {e}")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data["last_updated"] = datetime.now().isoformat()
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
        return True
    except (IOError, yaml.YAMLError):
        return False


def append_to_list(
    key: str, list_path: str, item: Dict[str, Any], match_key: Optional[str] = None
) -> bool:
    """
    Atomically append an item to a list in a memory file with file locking.

    If match_key is provided and an item with the same key exists, it will be updated.

    Args:
        key: Memory file key (e.g., "state/current_work")
        list_path: Path to the list within the file (e.g., "active_issues")
        item: Dict to append
        match_key: Key to check for existing items (e.g., "key" for issues, "id" for MRs)

    Returns:
        True if successful, False otherwise
    """
    path = get_memory_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic read-modify-write with exclusive lock
    try:
        with open(path, "r+" if path.exists() else "w+") as f:
            # Acquire exclusive lock (blocks until available)
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                # Read current data
                f.seek(0)
                content = f.read()
                data = yaml.safe_load(content) if content else {}

                if list_path not in data:
                    data[list_path] = []

                if not isinstance(data[list_path], list):
                    return False

                # Check for existing item if match_key provided
                if match_key and item.get(match_key):
                    for i, existing in enumerate(data[list_path]):
                        if existing.get(match_key) == item.get(match_key):
                            data[list_path][i] = item
                            # Write back
                            data["last_updated"] = datetime.now().isoformat()
                            f.seek(0)
                            f.truncate()
                            yaml.dump(
                                data, f, default_flow_style=False, sort_keys=False
                            )
                            return True

                # Append new item
                data[list_path].append(item)
                data["last_updated"] = datetime.now().isoformat()

                # Write back
                f.seek(0)
                f.truncate()
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                return True

            finally:
                # Release lock
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        print(f"Error in append_to_list: {e}")
        return False


def remove_from_list(key: str, list_path: str, match_key: str, match_value: Any) -> int:
    """
    Atomically remove items from a list in a memory file with file locking.

    Args:
        key: Memory file key (e.g., "state/current_work")
        list_path: Path to the list within the file (e.g., "active_issues")
        match_key: Key to match on (e.g., "key")
        match_value: Value to match

    Returns:
        Number of items removed
    """
    path = get_memory_path(key)

    if not path.exists():
        return 0

    try:
        with open(path, "r+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                f.seek(0)
                content = f.read()
                data = yaml.safe_load(content) if content else {}

                if list_path not in data or not isinstance(data[list_path], list):
                    return 0

                original_len = len(data[list_path])
                data[list_path] = [
                    item
                    for item in data[list_path]
                    if str(item.get(match_key, "")) != str(match_value)
                ]

                removed = original_len - len(data[list_path])
                if removed > 0:
                    data["last_updated"] = datetime.now().isoformat()
                    f.seek(0)
                    f.truncate()
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)

                return removed

            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        print(f"Error in remove_from_list: {e}")
        return 0


def update_field(key: str, field_path: str, value: Any) -> bool:
    """
    Atomically update a specific field in a memory file with file locking.

    Args:
        key: Memory file key (e.g., "state/environments")
        field_path: Dot-separated path (e.g., "environments.stage.status")
        value: New value

    Returns:
        True if successful, False otherwise
    """
    path = get_memory_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path, "r+" if path.exists() else "w+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                f.seek(0)
                content = f.read()
                data = yaml.safe_load(content) if content else {}

                parts = field_path.split(".")

                # Navigate to parent
                obj = data
                for part in parts[:-1]:
                    if part not in obj:
                        obj[part] = {}
                    obj = obj[part]

                obj[parts[-1]] = value
                data["last_updated"] = datetime.now().isoformat()

                # Write back
                f.seek(0)
                f.truncate()
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
                return True

            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        print(f"Error in update_field: {e}")
        return False


def get_timestamp() -> str:
    """
    Get current timestamp in ISO format.

    Returns:
        ISO format timestamp string
    """
    return datetime.now().isoformat()


def get_active_issues() -> List[Dict[str, Any]]:
    """
    Get list of active issues from memory.

    Returns:
        List of active issue dicts
    """
    data = read_memory("state/current_work")
    result = data.get("active_issues", [])
    return result if isinstance(result, list) else []


def get_open_mrs() -> List[Dict[str, Any]]:
    """
    Get list of open MRs from memory.

    Returns:
        List of open MR dicts
    """
    data = read_memory("state/current_work")
    result = data.get("open_mrs", [])
    return result if isinstance(result, list) else []


def get_follow_ups() -> List[Dict[str, Any]]:
    """
    Get list of follow-up tasks from memory.

    Returns:
        List of follow-up dicts
    """
    data = read_memory("state/current_work")
    result = data.get("follow_ups", [])
    return result if isinstance(result, list) else []


def add_active_issue(
    issue_key: str,
    summary: str,
    status: str = "In Progress",
    branch: str = "",
    repo: str = "",
    notes: str = "",
) -> bool:
    """
    Add an issue to active_issues.

    Args:
        issue_key: Jira issue key (e.g., "AAP-12345")
        summary: Issue summary
        status: Current status
        branch: Working branch name
        repo: Repository path
        notes: Additional notes

    Returns:
        True if successful
    """
    return append_to_list(
        "state/current_work",
        "active_issues",
        {
            "key": issue_key,
            "summary": summary,
            "status": status,
            "branch": branch,
            "repo": repo,
            "started": get_timestamp(),
            "notes": notes,
        },
        match_key="key",
    )


def add_open_mr(
    mr_id: int,
    project: str,
    title: str,
    url: str = "",
    pipeline_status: str = "pending",
    needs_review: bool = True,
) -> bool:
    """
    Add an MR to open_mrs.

    Args:
        mr_id: GitLab MR IID
        project: GitLab project path
        title: MR title
        url: MR web URL
        pipeline_status: Pipeline status
        needs_review: Whether MR needs review

    Returns:
        True if successful
    """
    return append_to_list(
        "state/current_work",
        "open_mrs",
        {
            "id": mr_id,
            "project": project,
            "title": title,
            "url": url,
            "pipeline_status": pipeline_status,
            "needs_review": needs_review,
            "created": get_timestamp(),
        },
        match_key="id",
    )


def add_follow_up(
    task: str, priority: str = "normal", issue_key: str = "", mr_id: int = 0
) -> bool:
    """
    Add a follow-up task (legacy - prefer add_discovered_work for new items).

    Args:
        task: Task description
        priority: Priority (low, normal, medium, high)
        issue_key: Related Jira issue key
        mr_id: Related MR ID

    Returns:
        True if successful
    """
    item: Dict[str, Any] = {
        "task": task,
        "priority": priority,
        "created": get_timestamp(),
    }
    if issue_key:
        item["issue_key"] = issue_key
    if mr_id:
        item["mr_id"] = mr_id

    return append_to_list("state/current_work", "follow_ups", item)


# =============================================================================
# DISCOVERED WORK FUNCTIONS - Track work found during other tasks
# =============================================================================


def add_discovered_work(
    task: str,
    work_type: str = "discovered_work",
    priority: str = "medium",
    source_skill: str = "",
    source_issue: str = "",
    source_mr: int = 0,
    file_path: str = "",
    line_number: int = 0,
    notes: str = "",
) -> bool:
    """
    Add discovered work item found during skill execution.

    Use this when a skill discovers work that needs to be done but isn't
    part of the current task. These items can later be synced to Jira.

    Args:
        task: Description of the work needed
        work_type: Type of work:
            - "discovered_work" (default) - general discovered item
            - "tech_debt" - technical debt to address
            - "bug" - bug found during other work
            - "improvement" - enhancement opportunity
            - "missing_test" - test coverage gap
            - "missing_docs" - documentation gap
            - "security" - security concern
        priority: Priority level (low, medium, high, critical)
        source_skill: Name of skill that discovered this (e.g., "review_pr")
        source_issue: Jira issue being worked on when discovered
        source_mr: MR ID being reviewed when discovered
        file_path: File where issue was found
        line_number: Line number if applicable
        notes: Additional context

    Returns:
        True if successfully added

    Example:
        # In review_pr skill when finding tech debt:
        add_discovered_work(
            task="Refactor duplicate validation logic in api/validators.py",
            work_type="tech_debt",
            priority="medium",
            source_skill="review_pr",
            source_mr=1459,
            file_path="api/validators.py",
            notes="Same validation repeated in 3 places"
        )
    """
    item: Dict[str, Any] = {
        "task": task,
        "work_type": work_type,
        "priority": priority,
        "created": get_timestamp(),
        "jira_synced": False,
        "jira_key": None,
    }

    if source_skill:
        item["source_skill"] = source_skill
    if source_issue:
        item["source_issue"] = source_issue
    if source_mr:
        item["source_mr"] = source_mr
    if file_path:
        item["file_path"] = file_path
    if line_number:
        item["line_number"] = line_number
    if notes:
        item["notes"] = notes

    return append_to_list("state/current_work", "discovered_work", item)


def get_discovered_work(pending_only: bool = False) -> List[Dict[str, Any]]:
    """
    Get list of discovered work items.

    Args:
        pending_only: If True, only return items not yet synced to Jira

    Returns:
        List of discovered work dicts
    """
    data = read_memory("state/current_work")
    items = data.get("discovered_work", [])

    if not isinstance(items, list):
        return []

    if pending_only:
        return [item for item in items if not item.get("jira_synced", False)]

    return items


def get_pending_discovered_work() -> List[Dict[str, Any]]:
    """
    Get discovered work items not yet synced to Jira.

    Convenience wrapper for get_discovered_work(pending_only=True).

    Returns:
        List of pending discovered work dicts
    """
    return get_discovered_work(pending_only=True)


def mark_discovered_work_synced(task: str, jira_key: str) -> bool:
    """
    Mark a discovered work item as synced to Jira.

    Args:
        task: Task description to match (or partial match)
        jira_key: The created Jira issue key

    Returns:
        True if item was found and updated
    """
    path = get_memory_path("state/current_work")

    if not path.exists():
        return False

    try:
        with open(path, "r+") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                f.seek(0)
                content = f.read()
                data = yaml.safe_load(content) if content else {}

                items = data.get("discovered_work", [])
                if not isinstance(items, list):
                    return False

                # Find and update matching item
                updated = False
                for item in items:
                    if task in item.get("task", "") or item.get("task", "") in task:
                        item["jira_synced"] = True
                        item["jira_key"] = jira_key
                        item["synced_at"] = get_timestamp()
                        updated = True
                        break

                if updated:
                    data["last_updated"] = get_timestamp()
                    f.seek(0)
                    f.truncate()
                    yaml.dump(data, f, default_flow_style=False, sort_keys=False)

                return updated

            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        logger.warning(f"Error marking discovered work synced: {e}")
        return False


def remove_discovered_work(task: str) -> bool:
    """
    Remove a discovered work item.

    Args:
        task: Task description to match

    Returns:
        True if item was removed
    """
    return remove_from_list("state/current_work", "discovered_work", "task", task) > 0


def get_discovered_work_summary() -> Dict[str, Any]:
    """
    Get summary statistics of discovered work.

    Returns:
        Dict with counts by type, priority, and sync status
    """
    items = get_discovered_work()

    summary: Dict[str, Any] = {
        "total": len(items),
        "pending_sync": 0,
        "synced": 0,
        "by_type": {},
        "by_priority": {},
        "by_source_skill": {},
    }

    for item in items:
        # Sync status
        if item.get("jira_synced"):
            summary["synced"] += 1
        else:
            summary["pending_sync"] += 1

        # By type
        work_type = item.get("work_type", "discovered_work")
        summary["by_type"][work_type] = summary["by_type"].get(work_type, 0) + 1

        # By priority
        priority = item.get("priority", "medium")
        summary["by_priority"][priority] = summary["by_priority"].get(priority, 0) + 1

        # By source skill
        source = item.get("source_skill", "unknown")
        summary["by_source_skill"][source] = (
            summary["by_source_skill"].get(source, 0) + 1
        )

    return summary


def find_similar_discovered_work(
    task: str, threshold: float = 0.8
) -> Optional[Dict[str, Any]]:
    """
    Find existing discovered work that is similar to the given task.

    Uses word overlap similarity to find potential duplicates.
    Returns the most similar item if similarity >= threshold.

    Args:
        task: Task description to match
        threshold: Minimum similarity score (0.0-1.0, default 0.8 = 80%)

    Returns:
        Most similar discovered work item, or None if no match >= threshold
    """
    items = get_discovered_work()
    if not items:
        return None

    # Normalize and tokenize the input task
    def tokenize(text: str) -> set:
        """Convert text to lowercase word tokens."""
        import re

        words = re.findall(r"\b\w+\b", text.lower())
        # Remove common stop words
        stop_words = {
            "the",
            "a",
            "an",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "and",
            "or",
            "is",
            "are",
            "was",
            "were",
        }
        return {w for w in words if w not in stop_words and len(w) > 2}

    task_tokens = tokenize(task)
    if not task_tokens:
        return None

    best_match = None
    best_score = 0.0

    for item in items:
        item_task = item.get("task", "")
        item_tokens = tokenize(item_task)

        if not item_tokens:
            continue

        # Jaccard similarity: intersection / union
        intersection = len(task_tokens & item_tokens)
        union = len(task_tokens | item_tokens)
        similarity = intersection / union if union > 0 else 0.0

        if similarity >= threshold and similarity > best_score:
            best_score = similarity
            best_match = item.copy()
            best_match["_similarity_score"] = similarity

    return best_match


def is_duplicate_discovered_work(
    task: str, work_type: str = "", source_mr: int = 0
) -> Dict[str, Any]:
    """
    Check if a discovered work item is a duplicate of an existing one.

    Checks for:
    1. Exact task match (already exists)
    2. Same task from same MR (duplicate detection during same review)
    3. High similarity match (potential duplicate)
    4. Already synced to Jira (should not create again)

    Args:
        task: Task description
        work_type: Type of work (for stricter matching)
        source_mr: Source MR ID (same MR = likely duplicate)

    Returns:
        Dict with:
            - is_duplicate: bool
            - reason: str (why it's a duplicate)
            - existing_item: dict (the matching item, if any)
            - jira_key: str (if already synced to Jira)
    """
    items = get_discovered_work()

    result: Dict[str, Any] = {
        "is_duplicate": False,
        "reason": None,
        "existing_item": None,
        "jira_key": None,
    }

    task_lower = task.lower().strip()

    for item in items:
        item_task = item.get("task", "").lower().strip()

        # Check 1: Exact match
        if task_lower == item_task:
            result["is_duplicate"] = True
            result["reason"] = "exact_match"
            result["existing_item"] = item
            if item.get("jira_synced"):
                result["jira_key"] = item.get("jira_key")
            return result

        # Check 2: Same MR and similar task
        if source_mr and item.get("source_mr") == source_mr:
            # Same MR - check for high similarity
            similar = find_similar_discovered_work(task, threshold=0.7)
            if similar and similar.get("source_mr") == source_mr:
                result["is_duplicate"] = True
                result["reason"] = "same_mr_similar_task"
                result["existing_item"] = item
                if item.get("jira_synced"):
                    result["jira_key"] = item.get("jira_key")
                return result

        # Check 3: Already synced with similar task
        if item.get("jira_synced"):
            similar = find_similar_discovered_work(task, threshold=0.85)
            if similar and similar.get("jira_synced"):
                result["is_duplicate"] = True
                result["reason"] = "already_synced_similar"
                result["existing_item"] = similar
                result["jira_key"] = similar.get("jira_key")
                return result

    # Check 4: High similarity match (even if not synced)
    similar = find_similar_discovered_work(task, threshold=0.9)
    if similar:
        result["is_duplicate"] = True
        result["reason"] = "high_similarity"
        result["existing_item"] = similar
        if similar.get("jira_synced"):
            result["jira_key"] = similar.get("jira_key")
        return result

    return result


def add_discovered_work_safe(
    task: str,
    work_type: str = "discovered_work",
    priority: str = "medium",
    source_skill: str = "",
    source_issue: str = "",
    source_mr: int = 0,
    file_path: str = "",
    line_number: int = 0,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Safely add discovered work with deduplication.

    This is the preferred method for adding discovered work as it:
    1. Checks for duplicates before adding
    2. Returns info about existing items if duplicate
    3. Can be used to decide whether to add notes to existing Jira

    Args:
        (same as add_discovered_work)

    Returns:
        Dict with:
            - added: bool (True if new item was added)
            - is_duplicate: bool
            - reason: str (if duplicate)
            - existing_item: dict (if duplicate)
            - jira_key: str (if already synced)

    Example:
        result = add_discovered_work_safe(
            task="Missing API documentation",
            work_type="missing_docs",
            source_skill="review_pr",
            source_mr=1459
        )

        if result["is_duplicate"]:
            if result["jira_key"]:
                # Add note to existing Jira issue instead
                jira_add_comment(result["jira_key"], "Also found in MR !1459")
            else:
                print(f"Duplicate of: {result['existing_item']['task']}")
        else:
            print("New item added")
    """
    # Check for duplicates first
    dup_check = is_duplicate_discovered_work(task, work_type, source_mr)

    if dup_check["is_duplicate"]:
        return {
            "added": False,
            "is_duplicate": True,
            "reason": dup_check["reason"],
            "existing_item": dup_check["existing_item"],
            "jira_key": dup_check.get("jira_key"),
        }

    # Not a duplicate - add it
    success = add_discovered_work(
        task=task,
        work_type=work_type,
        priority=priority,
        source_skill=source_skill,
        source_issue=source_issue,
        source_mr=source_mr,
        file_path=file_path,
        line_number=line_number,
        notes=notes,
    )

    return {
        "added": success,
        "is_duplicate": False,
        "reason": None,
        "existing_item": None,
        "jira_key": None,
    }


def get_discovered_work_for_period(
    days: int = 7,
    synced_only: bool = False,
) -> Dict[str, Any]:
    """
    Get discovered work items from a specific time period.

    Useful for daily/weekly summaries.

    Args:
        days: Number of days to look back (default: 7)
        synced_only: If True, only return items that were synced to Jira

    Returns:
        Dict with:
            - items: List of items in the period
            - created_count: Number of items discovered in period
            - synced_count: Number synced to Jira in period
            - by_type: Counts by work type
            - by_day: Counts by day
            - jira_keys: List of created Jira keys
    """
    from datetime import datetime, timedelta

    items = get_discovered_work()
    cutoff = datetime.now() - timedelta(days=days)

    period_items = []
    synced_in_period = []
    by_type: Dict[str, int] = {}
    by_day: Dict[str, int] = {}
    jira_keys: List[str] = []

    for item in items:
        # Check created date
        created_str = item.get("created", "")
        try:
            created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            created = created.replace(tzinfo=None)  # Make naive for comparison
        except (ValueError, AttributeError):
            continue

        if created < cutoff:
            continue

        # Item is in period
        if synced_only and not item.get("jira_synced"):
            continue

        period_items.append(item)

        # Track by type
        work_type = item.get("work_type", "discovered_work")
        by_type[work_type] = by_type.get(work_type, 0) + 1

        # Track by day
        day_str = created.strftime("%Y-%m-%d")
        by_day[day_str] = by_day.get(day_str, 0) + 1

        # Track synced items
        if item.get("jira_synced"):
            synced_in_period.append(item)
            if item.get("jira_key"):
                jira_keys.append(item["jira_key"])

    return {
        "items": period_items,
        "created_count": len(period_items),
        "synced_count": len(synced_in_period),
        "by_type": by_type,
        "by_day": by_day,
        "jira_keys": jira_keys,
        "period_days": days,
    }


def remove_active_issue(issue_key: str) -> bool:
    """
    Remove an issue from active_issues.

    Args:
        issue_key: Jira issue key to remove

    Returns:
        True if removed
    """
    return remove_from_list("state/current_work", "active_issues", "key", issue_key) > 0


def remove_open_mr(mr_id: int) -> bool:
    """
    Remove an MR from open_mrs.

    Args:
        mr_id: MR ID to remove

    Returns:
        True if removed
    """
    return remove_from_list("state/current_work", "open_mrs", "id", mr_id) > 0


def save_shared_context(
    skill_name: str, context: Dict[str, Any], ttl_hours: int = 1
) -> bool:
    """
    Save context for sharing between skills with expiry.

    This allows one skill to save important discoveries for other skills to use
    without re-discovering the same information.

    Args:
        skill_name: Name of the skill saving the context
        context: Dict of context data to share
        ttl_hours: Time-to-live in hours (default: 1)

    Returns:
        True if successful

    Example:
        # In investigate_alert skill:
        save_shared_context("investigate_alert", {
            "environment": "stage",
            "pod_name": "tower-analytics-api-123",
            "issue": "High CPU",
        })

        # In debug_prod skill:
        ctx = load_shared_context()
        if ctx and ctx.get("pod_name"):
            # Use the pod name from investigation
            pod = ctx["pod_name"]
    """
    from datetime import timedelta

    now = datetime.now()
    expires = now + timedelta(hours=ttl_hours)

    data = read_memory("state/shared_context")
    data["current_investigation"] = {
        "started_by": skill_name,
        "started_at": now.isoformat(),
        "context": context,
        "expires_at": expires.isoformat(),
    }

    return write_memory("state/shared_context", data)


def load_shared_context() -> Optional[Dict[str, Any]]:
    """
    Load shared context if not expired.

    Returns:
        Dict of shared context, or None if expired/not found
    """
    data = read_memory("state/shared_context")
    investigation = data.get("current_investigation", {})

    if not investigation or not investigation.get("expires_at"):
        return None

    # Check expiry
    try:
        expires_at = datetime.fromisoformat(
            investigation["expires_at"].replace("Z", "+00:00")
        )
        if datetime.now().replace(tzinfo=None) > expires_at.replace(tzinfo=None):
            # Expired
            return None
    except (ValueError, KeyError):
        return None

    context: Optional[Dict[str, Any]] = investigation.get("context")
    return context


# =============================================================================
# LEARNING FUNCTIONS - Check known issues and learn from fixes
# =============================================================================


def check_known_issues(tool_name: str = "", error_text: str = "") -> Dict[str, Any]:
    """
    Check memory for known issues matching this tool/error.

    This is the synchronous version for use in skill compute blocks.
    It searches patterns.yaml and tool_fixes.yaml for matching patterns.

    Args:
        tool_name: Name of the tool that failed (e.g., "gitlab_mr_list")
        error_text: Error message text to match against patterns

    Returns:
        Dict with:
            - matches: List of matching patterns with fix suggestions
            - has_known_issues: Boolean indicating if any matches found

    Example:
        issues = memory.check_known_issues("gitlab_mr_list", "no such host")
        if issues.get("has_known_issues"):
            for match in issues.get("matches", []):
                print(f"Known fix: {match.get('fix')}")
    """
    matches = []
    error_lower = error_text.lower() if error_text else ""
    tool_lower = tool_name.lower() if tool_name else ""

    try:
        # Check patterns.yaml
        patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
        if patterns_file.exists():
            with open(patterns_file) as f:
                patterns = yaml.safe_load(f) or {}

            # Check all pattern categories
            for category in [
                "error_patterns",
                "auth_patterns",
                "bonfire_patterns",
                "pipeline_patterns",
                "network_patterns",
            ]:
                for pattern in patterns.get(category, []):
                    pattern_text = pattern.get("pattern", "").lower()
                    if pattern_text and (
                        pattern_text in error_lower or pattern_text in tool_lower
                    ):
                        matches.append(
                            {
                                "source": category,
                                "pattern": pattern.get("pattern"),
                                "meaning": pattern.get("meaning", ""),
                                "fix": pattern.get("fix", ""),
                                "commands": pattern.get("commands", []),
                            }
                        )

        # Check tool_fixes.yaml
        fixes_file = MEMORY_DIR / "learned" / "tool_fixes.yaml"
        if fixes_file.exists():
            with open(fixes_file) as f:
                fixes = yaml.safe_load(f) or {}

            for fix in fixes.get("tool_fixes", []):
                if tool_name and fix.get("tool_name", "").lower() == tool_lower:
                    matches.append(
                        {
                            "source": "tool_fixes",
                            "tool_name": fix.get("tool_name"),
                            "pattern": fix.get("error_pattern", ""),
                            "fix": fix.get("fix_applied", ""),
                        }
                    )
                elif error_text:
                    fix_pattern = fix.get("error_pattern", "").lower()
                    if fix_pattern and fix_pattern in error_lower:
                        matches.append(
                            {
                                "source": "tool_fixes",
                                "tool_name": fix.get("tool_name"),
                                "pattern": fix.get("error_pattern", ""),
                                "fix": fix.get("fix_applied", ""),
                            }
                        )

    except Exception as e:
        logger.debug(f"Error checking known issues: {e}")

    return {
        "matches": matches,
        "has_known_issues": len(matches) > 0,
    }


def learn_tool_fix(
    tool_name: str,
    error_pattern: str,
    root_cause: str,
    fix_description: str,
) -> bool:
    """
    Save a fix to memory after it works.

    Use this after successfully fixing a tool error to remember the solution.
    The next time this pattern appears, check_known_issues() will show the fix.

    Args:
        tool_name: Name of the tool that failed (e.g., "bonfire_deploy")
        error_pattern: The error pattern to match (e.g., "manifest unknown")
        root_cause: Why it failed (e.g., "Short SHA doesn't exist in Quay")
        fix_description: What fixed it (e.g., "Use full 40-char SHA")

    Returns:
        True if successfully saved, False otherwise

    Example:
        memory.learn_tool_fix(
            tool_name="gitlab_mr_list",
            error_pattern="no such host",
            root_cause="VPN not connected",
            fix_description="Run vpn_connect() to connect to Red Hat VPN"
        )
    """
    try:
        fixes_file = MEMORY_DIR / "learned" / "tool_fixes.yaml"
        fixes_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing fixes
        if fixes_file.exists():
            with open(fixes_file) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"tool_fixes": [], "stats": {"total_learned": 0}}

        if "tool_fixes" not in data:
            data["tool_fixes"] = []
        if "stats" not in data:
            data["stats"] = {"total_learned": 0}

        # Check if this pattern already exists
        for existing in data["tool_fixes"]:
            if (
                existing.get("tool_name") == tool_name
                and existing.get("error_pattern") == error_pattern
            ):
                # Update existing entry
                existing["root_cause"] = root_cause
                existing["fix_applied"] = fix_description
                existing["last_seen"] = datetime.now().isoformat()
                existing["occurrences"] = existing.get("occurrences", 1) + 1
                break
        else:
            # Add new entry
            data["tool_fixes"].append(
                {
                    "tool_name": tool_name,
                    "error_pattern": error_pattern,
                    "root_cause": root_cause,
                    "fix_applied": fix_description,
                    "learned_at": datetime.now().isoformat(),
                    "last_seen": datetime.now().isoformat(),
                    "occurrences": 1,
                }
            )
            data["stats"]["total_learned"] = data["stats"].get("total_learned", 0) + 1

        # Keep only last 100 fixes
        data["tool_fixes"] = data["tool_fixes"][-100:]
        data["last_updated"] = datetime.now().isoformat()

        # Write back
        with open(fixes_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.debug(f"Learned fix for {tool_name}: {error_pattern}")
        return True

    except Exception as e:
        logger.warning(f"Failed to learn tool fix: {e}")
        return False


def record_tool_failure(
    tool_name: str,
    error_text: str,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Record a tool failure for pattern analysis.

    This logs failures without necessarily having a fix yet.
    Useful for tracking recurring issues that need investigation.

    Args:
        tool_name: Name of the tool that failed
        error_text: Error message
        context: Additional context (skill name, inputs, etc.)

    Returns:
        True if successfully recorded, False otherwise
    """
    try:
        failures_file = MEMORY_DIR / "learned" / "tool_failures.yaml"
        failures_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing failures
        if failures_file.exists():
            with open(failures_file) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {"failures": [], "stats": {"total_failures": 0}}

        if "failures" not in data:
            data["failures"] = []
        if "stats" not in data:
            data["stats"] = {"total_failures": 0}

        # Add failure entry
        entry = {
            "tool": tool_name,
            "error_snippet": error_text[:200] if error_text else "",
            "timestamp": datetime.now().isoformat(),
            "context": context or {},
        }
        data["failures"].append(entry)
        data["stats"]["total_failures"] = data["stats"].get("total_failures", 0) + 1

        # Keep only last 100 failures
        data["failures"] = data["failures"][-100:]
        data["last_updated"] = datetime.now().isoformat()

        # Write back
        with open(failures_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        return True

    except Exception as e:
        logger.warning(f"Failed to record tool failure: {e}")
        return False
