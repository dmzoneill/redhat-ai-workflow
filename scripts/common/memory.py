"""
Common memory helpers for skills.

These functions provide a consistent interface for reading and writing
to memory files, reducing code duplication across skills.

Memory directory structure:
  ~/src/redhat-ai-workflow/memory/
  ├── state/
  │   ├── current_work.yaml  - Active issues, MRs, follow-ups
  │   └── environments.yaml  - Stage/prod health, namespaces
  ├── learned/
  │   ├── patterns.yaml      - Error patterns for debugging
  │   ├── runbooks.yaml      - Operational procedures
  │   ├── teammate_preferences.yaml
  │   └── service_quirks.yaml
  └── logs/
      └── YYYY-MM-DD.yaml    - Session logs
"""

import fcntl
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Memory directory - relative to project root
MEMORY_DIR = Path.home() / "src/redhat-ai-workflow/memory"

logger = logging.getLogger(__name__)


def get_memory_path(key: str) -> Path:
    """
    Get the full path to a memory file.

    Args:
        key: Memory key like "state/current_work" or "learned/patterns"

    Returns:
        Full path to the memory file (with .yaml extension)
    """
    if not key.endswith(".yaml"):
        key = f"{key}.yaml"
    return MEMORY_DIR / key


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


def append_to_list(key: str, list_path: str, item: Dict[str, Any], match_key: Optional[str] = None) -> bool:
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
                            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
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
                data[list_path] = [item for item in data[list_path] if str(item.get(match_key, "")) != str(match_value)]

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


def add_follow_up(task: str, priority: str = "normal", issue_key: str = "", mr_id: int = 0) -> bool:
    """
    Add a follow-up task.

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


def save_shared_context(skill_name: str, context: Dict[str, Any], ttl_hours: int = 1) -> bool:
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
        expires_at = datetime.fromisoformat(investigation["expires_at"].replace("Z", "+00:00"))
        if datetime.now().replace(tzinfo=None) > expires_at.replace(tzinfo=None):
            # Expired
            return None
    except (ValueError, KeyError):
        return None

    context: Optional[Dict[str, Any]] = investigation.get("context")
    return context
