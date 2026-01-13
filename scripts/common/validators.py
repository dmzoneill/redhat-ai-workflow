"""
Shared validation functions for AI Workflow skills.

Import and use in compute blocks:
    from scripts.common.validators import validate_git_repo, check_tools
"""

import os
import shutil
import sys
from pathlib import Path

# Add project root to path for server imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.utils import run_cmd_sync  # noqa: E402


def validate_git_repo(repo_path: str = ".") -> dict:
    """
    Validate that path is a git repository and check for issues.

    Returns:
        dict with keys: valid, git_dir, issues, current_branch, is_detached

    Raises:
        ValueError if not a git repository
    """
    repo = repo_path if repo_path != "." else os.getcwd()

    # Check if git repo - git doesn't need shell env
    success, output = run_cmd_sync(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo,
        use_shell=False,
    )

    if not success:
        raise ValueError(f"Not a git repository: {repo}")

    git_dir = output.strip()
    if not git_dir.startswith("/"):
        git_dir = os.path.join(repo, git_dir)

    issues = []

    # Check for rebase in progress
    rebase_merge = os.path.join(git_dir, "rebase-merge")
    rebase_apply = os.path.join(git_dir, "rebase-apply")
    if os.path.exists(rebase_merge) or os.path.exists(rebase_apply):
        issues.append("rebase_in_progress")

    # Check for merge in progress
    merge_head = os.path.join(git_dir, "MERGE_HEAD")
    if os.path.exists(merge_head):
        issues.append("merge_in_progress")

    # Check for cherry-pick in progress
    cherry_pick = os.path.join(git_dir, "CHERRY_PICK_HEAD")
    if os.path.exists(cherry_pick):
        issues.append("cherry_pick_in_progress")

    # Get current branch
    success, output = run_cmd_sync(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        use_shell=False,
    )
    current_branch = output.strip() if success else None
    is_detached = current_branch == "HEAD"

    if is_detached:
        issues.append("detached_head")

    return {
        "valid": True,
        "git_dir": git_dir,
        "issues": issues,
        "current_branch": current_branch,
        "is_detached": is_detached,
    }


def check_uncommitted_changes(repo_path: str = ".") -> dict:
    """
    Check for uncommitted changes in the repository.

    Returns:
        dict with keys: has_changes, staged, unstaged, untracked, count
    """
    repo = repo_path if repo_path != "." else os.getcwd()

    success, output = run_cmd_sync(
        ["git", "status", "--porcelain"],
        cwd=repo,
        use_shell=False,
    )

    if not success:
        return {"has_changes": False, "error": output}

    lines = [ln for ln in output.strip().split("\n") if ln]

    staged = [ln for ln in lines if ln[0] in "MADRC"]
    unstaged = [ln for ln in lines if ln[1] in "MADRC"]
    untracked = [ln for ln in lines if ln.startswith("??")]

    return {
        "has_changes": len(lines) > 0,
        "staged": len(staged),
        "unstaged": len(unstaged),
        "untracked": len(untracked),
        "count": len(lines),
        "files": lines[:10],
    }


def check_tools(required: list[str]) -> dict:
    """
    Check if required CLI tools are available.

    Args:
        required: List of tool names (e.g., ["git", "glab", "black"])

    Returns:
        dict with keys: all_available, missing, available
    """
    available = []
    missing = []

    for tool in required:
        if shutil.which(tool):
            available.append(tool)
        else:
            missing.append(tool)

    return {
        "all_available": len(missing) == 0,
        "missing": missing,
        "available": available,
    }


def check_branch_exists(branch: str, repo_path: str = ".", check_remote: bool = True) -> dict:
    """
    Check if a branch exists locally or remotely.

    Returns:
        dict with keys: exists, local, remote, full_name
    """
    repo = repo_path if repo_path != "." else os.getcwd()

    # Check local
    success, _ = run_cmd_sync(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=repo,
        use_shell=False,
    )
    local_exists = success

    # Check remote
    remote_exists = False
    if check_remote:
        success, _ = run_cmd_sync(
            ["git", "show-ref", "--verify", f"refs/remotes/origin/{branch}"],
            cwd=repo,
            use_shell=False,
        )
        remote_exists = success

    return {
        "exists": local_exists or remote_exists,
        "local": local_exists,
        "remote": remote_exists,
        "full_name": f"origin/{branch}" if remote_exists else branch,
    }


def check_can_force_push(branch: str, repo_path: str = ".") -> dict:
    """
    Check if force push is allowed on a branch.

    Returns:
        dict with keys: allowed, reason
    """
    repo = repo_path if repo_path != "." else os.getcwd()

    # Try dry-run force push
    success, output = run_cmd_sync(
        ["git", "push", "--dry-run", "--force-with-lease", "origin", branch],
        cwd=repo,
        use_shell=False,
    )

    stderr = output.lower()

    if "protected branch" in stderr:
        return {"allowed": False, "reason": "Branch is protected"}

    if "permission denied" in stderr or "403" in stderr:
        return {"allowed": False, "reason": "Permission denied"}

    if "remote rejected" in stderr:
        return {"allowed": False, "reason": "Remote rejected push"}

    # Even if non-zero, may just mean nothing to push
    return {"allowed": True, "reason": "OK"}


def validate_jira_issue(issue_key: str) -> dict:
    """
    Validate Jira issue key format.

    Returns:
        dict with keys: valid, project, number
    """
    import re

    match = re.match(r"^([A-Z]+-)?(\d+)$", issue_key.upper())
    if not match:
        match = re.match(r"^([A-Z]+)-(\d+)$", issue_key.upper())

    if match:
        return {
            "valid": True,
            "project": match.group(1).rstrip("-") if match.group(1) else "AAP",
            "number": int(match.group(2)),
            "key": f"{match.group(1) or 'AAP-'}{match.group(2)}".upper(),
        }

    return {"valid": False, "project": None, "number": None, "key": issue_key}


def check_commits_ahead_behind(base: str = "origin/main", repo_path: str = ".") -> dict:
    """
    Check how many commits ahead/behind of base branch.

    Returns:
        dict with keys: ahead, behind, diverged
    """
    repo = repo_path if repo_path != "." else os.getcwd()

    # Fetch first
    run_cmd_sync(["git", "fetch", "origin"], cwd=repo, use_shell=False)

    # Get ahead count
    success, output = run_cmd_sync(
        ["git", "rev-list", "--count", f"{base}..HEAD"],
        cwd=repo,
        use_shell=False,
    )
    ahead = int(output.strip()) if success else 0

    # Get behind count
    success, output = run_cmd_sync(
        ["git", "rev-list", "--count", f"HEAD..{base}"],
        cwd=repo,
        use_shell=False,
    )
    behind = int(output.strip()) if success else 0

    return {
        "ahead": ahead,
        "behind": behind,
        "diverged": ahead > 0 and behind > 0,
        "up_to_date": behind == 0,
    }


def estimate_diff_size(base: str = "origin/main", repo_path: str = ".") -> dict:
    """
    Estimate the size of diff against base.

    Returns:
        dict with keys: lines_added, lines_removed, files_changed, is_large
    """
    import re

    repo = repo_path if repo_path != "." else os.getcwd()

    success, output = run_cmd_sync(
        ["git", "diff", "--stat", base],
        cwd=repo,
        use_shell=False,
    )

    lines = output.strip().split("\n") if success else []

    # Parse last line: "X files changed, Y insertions(+), Z deletions(-)"
    files_changed = 0
    lines_added = 0
    lines_removed = 0

    if lines:
        last_line = lines[-1]
        files_match = re.search(r"(\d+) files? changed", last_line)
        add_match = re.search(r"(\d+) insertions?", last_line)
        del_match = re.search(r"(\d+) deletions?", last_line)

        files_changed = int(files_match.group(1)) if files_match else 0
        lines_added = int(add_match.group(1)) if add_match else 0
        lines_removed = int(del_match.group(1)) if del_match else 0

    total_lines = lines_added + lines_removed
    is_large = total_lines > 5000 or files_changed > 50

    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "total_lines": total_lines,
        "is_large": is_large,
    }
