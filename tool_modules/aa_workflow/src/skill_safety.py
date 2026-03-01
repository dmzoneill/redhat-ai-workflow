"""Sprint safety guard - protects worktree from data loss before bot work."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


class SprintSafetyGuard:
    """Safety guard for Sprint Bot to protect worktree from data loss.

    Before the bot starts work on an issue, this guard:
    1. Checks git_status for uncommitted changes
    2. Auto-stashes with descriptive message via git_stash tool
    3. Verifies not on main/master branch
    4. Checks for rebase/merge in progress

    Usage:
        guard = SprintSafetyGuard(server, repo_path)
        result = await guard.check_and_prepare(issue_key)
        if not result["safe"]:
            # Handle unsafe state
            print(result["reason"])
    """

    # Branches that should never be worked on directly
    PROTECTED_BRANCHES = {"main", "master", "develop", "production", "staging"}

    def __init__(
        self,
        server: FastMCP | None = None,
        repo_path: str = ".",
        auto_stash: bool = True,
    ):
        """Initialize the safety guard.

        Args:
            server: FastMCP server for calling git tools
            repo_path: Path to the repository
            auto_stash: Whether to automatically stash uncommitted changes
        """
        self.server = server
        self.repo_path = repo_path
        self.auto_stash = auto_stash
        self._stash_created = False
        self._original_branch: str | None = None

    async def check_git_status(self) -> dict[str, Any]:
        """Check git status for uncommitted changes.

        Returns:
            Dict with status info:
            - clean: bool - True if worktree is clean
            - modified: list - Modified files
            - staged: list - Staged files
            - untracked: list - Untracked files
            - branch: str - Current branch name
            - in_progress: str | None - "rebase", "merge", or None
        """
        result: dict[str, Any] = {
            "clean": True,
            "modified": [],
            "staged": [],
            "untracked": [],
            "branch": "",
            "in_progress": None,
        }

        if not self.server:
            logger.warning("No server available for git_status check")
            return result

        try:
            # Call git_status tool
            status_result = await self.server.call_tool(
                "git_status", {"repo": self.repo_path}
            )

            # Parse the result
            if status_result and len(status_result.content) > 0:
                first = status_result.content[0]
                text = first.text if hasattr(first, "text") else str(first)

                # Check for modifications
                if "modified:" in text.lower() or "changes not staged" in text.lower():
                    result["clean"] = False
                    # Extract modified files (simplified parsing)
                    for line in text.split("\n"):
                        if "modified:" in line.lower():
                            result["modified"].append(line.strip())

                if "changes to be committed" in text.lower():
                    result["clean"] = False
                    result["staged"].append("(staged changes present)")

                if "untracked files" in text.lower():
                    # Untracked files don't make it "dirty" for our purposes
                    result["untracked"].append("(untracked files present)")

                # Check for rebase/merge in progress
                if "rebase in progress" in text.lower():
                    result["in_progress"] = "rebase"
                    result["clean"] = False
                elif (
                    "merge in progress" in text.lower()
                    or "you have unmerged paths" in text.lower()
                ):
                    result["in_progress"] = "merge"
                    result["clean"] = False

                # Extract branch name
                if "on branch" in text.lower():
                    for line in text.split("\n"):
                        if "on branch" in line.lower():
                            parts = line.split()
                            if len(parts) >= 3:
                                result["branch"] = parts[-1]
                                break

        except Exception as e:
            logger.error(f"Error checking git status: {e}")

        self._original_branch = result["branch"]
        return result

    async def stash_changes(self, issue_key: str) -> dict[str, Any]:
        """Stash uncommitted changes with a descriptive message.

        Args:
            issue_key: Jira issue key for the stash message

        Returns:
            Dict with stash result:
            - success: bool
            - message: str
        """
        if not self.server:
            return {"success": False, "message": "No server available"}

        try:
            stash_message = f"Auto-stash before {issue_key} - Sprint Bot"
            result = await self.server.call_tool(
                "git_stash",
                {
                    "repo": self.repo_path,
                    "action": "push",
                    "message": stash_message,
                },
            )

            first = result.content[0] if result and result.content else None
            text = first.text if first and hasattr(first, "text") else str(result)
            self._stash_created = "saved" in text.lower() or "stash" in text.lower()

            return {
                "success": self._stash_created,
                "message": (
                    f"Stashed changes: {stash_message}"
                    if self._stash_created
                    else "No changes to stash"
                ),
            }

        except Exception as e:
            logger.error(f"Error stashing changes: {e}")
            return {"success": False, "message": str(e)}

    async def check_and_prepare(self, issue_key: str) -> dict[str, Any]:
        """Check safety and prepare worktree for work.

        This is the main entry point. It:
        1. Checks git status
        2. Validates we're not on a protected branch
        3. Auto-stashes if needed and enabled
        4. Returns safety status

        Args:
            issue_key: Jira issue key for context

        Returns:
            Dict with:
            - safe: bool - True if safe to proceed
            - reason: str - Explanation if not safe
            - stashed: bool - True if changes were stashed
            - branch: str - Current branch
            - warnings: list - Non-blocking warnings
        """
        result: dict[str, Any] = {
            "safe": True,
            "reason": "",
            "stashed": False,
            "branch": "",
            "warnings": [],
        }

        # Check git status
        status = await self.check_git_status()
        result["branch"] = status["branch"]

        # Check for rebase/merge in progress
        if status["in_progress"]:
            result["safe"] = False
            result["reason"] = (
                f"A {status['in_progress']} is in progress. Please complete or abort it first."
            )
            return result

        # Check for protected branch
        if status["branch"].lower() in self.PROTECTED_BRANCHES:
            result["safe"] = False
            result["reason"] = (
                f"Currently on protected branch '{status['branch']}'. "
                "Please create a feature branch first."
            )
            return result

        # Handle uncommitted changes
        if not status["clean"]:
            if self.auto_stash:
                stash_result = await self.stash_changes(issue_key)
                if stash_result["success"]:
                    result["stashed"] = True
                    result["warnings"].append(
                        f"Stashed uncommitted changes: {stash_result['message']}"
                    )
                else:
                    result["safe"] = False
                    result["reason"] = (
                        f"Failed to stash uncommitted changes: {stash_result['message']}"
                    )
                    return result
            else:
                result["safe"] = False
                result["reason"] = (
                    "Uncommitted changes detected. Please commit or stash them first, "
                    "or enable auto_stash."
                )
                return result

        # Add warnings for untracked files
        if status["untracked"]:
            result["warnings"].append("Untracked files present (not stashed)")

        return result

    async def restore_stash(self) -> dict[str, Any]:
        """Restore stashed changes after work is complete or aborted.

        Returns:
            Dict with restore result
        """
        if not self._stash_created:
            return {"success": True, "message": "No stash to restore"}

        if not self.server:
            return {"success": False, "message": "No server available"}

        try:
            result = await self.server.call_tool(
                "git_stash",
                {
                    "repo": self.repo_path,
                    "action": "pop",
                },
            )

            first = result.content[0] if result and result.content else None
            text = first.text if first and hasattr(first, "text") else str(result)
            success = "dropped" in text.lower() or "applied" in text.lower()

            return {
                "success": success,
                "message": "Restored stashed changes" if success else text,
            }

        except Exception as e:
            logger.error(f"Error restoring stash: {e}")
            return {"success": False, "message": str(e)}
