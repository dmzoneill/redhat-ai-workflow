"""Git Extra Tools - Advanced git and development operations.

This module provides advanced git tools and build/docker utilities.
For basic git operations, see tools_basic.py.

Tools included (~17):
- git_show, git_diff_tree, git_reset, git_clean, git_rebase
- git_rev_parse, git_merge, git_merge_abort
- code_format, code_lint, make_target
- docker_compose_status, docker_compose_up, docker_compose_down
- docker_cp, docker_exec
"""

import logging

from mcp.server.fastmcp import FastMCP

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path, run_cmd, truncate_output

# Setup project path for server imports
from tool_modules.common import PROJECT_ROOT  # noqa: F401 - side effect: adds to sys.path

logger = logging.getLogger(__name__)


async def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run git command and return (success, output)."""
    cmd = ["git"] + args
    return await run_cmd(cmd, cwd=cwd, timeout=timeout)


def register_tools(server: FastMCP) -> int:
    """Register advanced git tools with the MCP server."""
    registry = ToolRegistry(server)

    # ==================== ADVANCED GIT ====================

    @auto_heal()
    @registry.tool()
    async def git_show(
        repo: str,
        commit: str = "HEAD",
        format: str = "",
        name_only: bool = False,
    ) -> str:
        """
        Show commit details.

        Args:
            repo: Repository path
            commit: Commit SHA or reference (default: HEAD)
            format: Custom format string (e.g., "%s%n%b" for subject+body)
            name_only: Show only file names, not diff

        Returns:
            Commit details.
        """
        path = resolve_repo_path(repo)

        args = ["show", commit]
        if format:
            args.append(f"--format={format}")
        if name_only:
            args.append("--name-only")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to show commit: {output}"

        return truncate_output(output, max_length=5000)

    @auto_heal()
    @registry.tool()
    async def git_diff_tree(
        repo: str,
        commit: str,
        name_only: bool = True,
    ) -> str:
        """
        Get list of files changed in a commit.

        Args:
            repo: Repository path
            commit: Commit SHA to inspect
            name_only: Return only filenames (default: True)

        Returns:
            List of changed files.
        """
        path = resolve_repo_path(repo)

        args = ["diff-tree", "--no-commit-id", "-r", commit]
        if name_only:
            args.append("--name-only")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to get diff-tree: {output}"

        return output.strip()

    @auto_heal()
    @registry.tool()
    async def git_reset(repo: str, target: str = "HEAD", mode: str = "mixed") -> str:
        """Reset current HEAD to specified state."""
        path = resolve_repo_path(repo)

        args = ["reset", f"--{mode}", target]

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to reset: {output}"

        warning = "⚠️ Changes discarded!" if mode == "hard" else ""
        return f"✅ Reset to `{target}` ({mode}) {warning}\n\n{output or 'Done'}"

    @auto_heal()
    @registry.tool()
    async def git_clean(repo: str, dry_run: bool = True) -> str:
        """Remove untracked files."""
        path = resolve_repo_path(repo)

        args = ["clean", "-fd"]
        if dry_run:
            args.append("-n")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to clean: {output}"

        prefix = "Would remove" if dry_run else "Removed"
        if not output.strip():
            return "No untracked files to remove"

        lines = [f"## {prefix}:", ""]
        for line in output.strip().split("\n"):
            lines.append(f"- {line}")

        if dry_run:
            lines.append("\n*Run with dry_run=False to actually delete*")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def git_rebase(
        repo: str,
        onto: str = "",
        abort: bool = False,
        continue_rebase: bool = False,
        skip: bool = False,
        interactive: bool = False,
    ) -> str:
        """
        Rebase current branch onto another branch, or manage in-progress rebase.

        Args:
            repo: Repository path
            onto: Branch/commit to rebase onto (e.g., "origin/main", "main")
            abort: Abort an in-progress rebase
            continue_rebase: Continue after resolving conflicts
            skip: Skip current commit and continue rebase
            interactive: Use interactive rebase (opens editor - not recommended for automation)

        Returns:
            Rebase status with conflict information if any.
        """
        path = resolve_repo_path(repo)

        # Handle rebase control operations
        if abort:
            success, output = await run_git(["rebase", "--abort"], cwd=path)
            if success:
                return "✅ Rebase aborted. Back to original state."
            return f"❌ Failed to abort rebase: {output}"

        if continue_rebase:
            success, output = await run_git(["rebase", "--continue"], cwd=path)
            if success:
                return f"✅ Rebase continued successfully.\n\n{output}"
            return f"❌ Conflicts remain or rebase failed:\n{output}"

        if skip:
            success, output = await run_git(["rebase", "--skip"], cwd=path)
            if success:
                return f"✅ Skipped commit, continuing rebase.\n\n{output}"
            return f"❌ Failed to skip: {output}"

        # Start new rebase
        if not onto:
            return "❌ Must specify 'onto' branch for rebase, or use abort/continue_rebase/skip"

        args = ["rebase"]
        if interactive:
            args.append("-i")
        args.append(onto)

        success, output = await run_git(args, cwd=path)

        if success:
            return f"✅ Successfully rebased onto `{onto}`\n\n{output or 'Rebase complete.'}"

        # Check for conflicts
        status_ok, status_output = await run_git(["status", "--porcelain"], cwd=path)

        conflict_files = []
        if status_ok:
            for line in status_output.split("\n"):
                if line.startswith("UU") or line.startswith("AA") or line.startswith("DU") or line.startswith("UD"):
                    conflict_files.append(line[3:].strip())

        if conflict_files:
            lines = [
                f"⚠️ Rebase paused - {len(conflict_files)} conflict(s) detected",
                "",
                "**Conflict files:**",
            ]
            for f in conflict_files[:10]:
                lines.append(f"- `{f}`")
            if len(conflict_files) > 10:
                lines.append(f"- ... and {len(conflict_files) - 10} more")

            lines.extend(
                [
                    "",
                    "**Next steps:**",
                    "1. Resolve conflicts in the files above",
                    "2. Stage resolved files: `git_add(repo, 'file1 file2')`",
                    "3. Continue: `git_rebase(repo, continue_rebase=True)`",
                    "   Or abort: `git_rebase(repo, abort=True)`",
                ]
            )
            return "\n".join(lines)

        return f"❌ Rebase failed:\n{output}"

    @auto_heal()
    @registry.tool()
    async def git_rev_parse(
        repo: str,
        ref: str,
        short: bool = False,
        verify: bool = True,
    ) -> str:
        """
        Resolve a git reference to its SHA.

        Args:
            repo: Repository path
            ref: Reference to resolve (branch, tag, short SHA, HEAD, etc.)
            short: Return short SHA (7 chars) instead of full 40-char
            verify: Verify the reference exists (fail if not found)

        Returns:
            The resolved SHA, or error message.
        """
        path = resolve_repo_path(repo)

        args = ["rev-parse"]
        if verify:
            args.append("--verify")
        if short:
            args.append("--short")
        args.append(ref)

        success, output = await run_git(args, cwd=path)

        if not success:
            await run_git(["fetch", "origin"], cwd=path)
            success, output = await run_git(args, cwd=path)

        if not success:
            return f"❌ Could not resolve ref '{ref}': {output}"

        sha = output.strip()

        if not sha or (not short and len(sha) != 40) or (short and len(sha) < 7):
            return f"❌ Invalid SHA returned for '{ref}': {sha}"

        return sha

    @auto_heal()
    @registry.tool()
    async def git_merge(
        repo: str,
        target: str,
        no_commit: bool = False,
        no_ff: bool = False,
        message: str = "",
    ) -> str:
        """
        Merge a branch into the current branch.

        Args:
            repo: Repository path
            target: Branch or commit to merge
            no_commit: Don't commit the merge (for testing mergeability)
            no_ff: Always create a merge commit, even if fast-forward is possible
            message: Custom merge commit message

        Returns:
            Merge result.
        """
        path = resolve_repo_path(repo)

        args = ["merge"]
        if no_commit:
            args.append("--no-commit")
        if no_ff:
            args.append("--no-ff")
        if message:
            args.extend(["-m", message])
        args.append(target)

        success, output = await run_git(args, cwd=path)

        if success:
            return f"✅ Merged {target} successfully\n\n{output}"

        if "conflict" in output.lower():
            return f"⚠️ Merge conflicts detected:\n\n{output}"

        return f"❌ Merge failed: {output}"

    @auto_heal()
    @registry.tool()
    async def git_merge_abort(repo: str) -> str:
        """
        Abort an in-progress merge.

        Args:
            repo: Repository path

        Returns:
            Success or error message.
        """
        path = resolve_repo_path(repo)

        success, output = await run_git(["merge", "--abort"], cwd=path)

        if success:
            return "✅ Merge aborted. Working tree restored."
        return f"❌ Failed to abort merge (perhaps no merge in progress?): {output}"

    # ==================== CODE FORMATTING ====================

    @auto_heal()
    @registry.tool()
    async def code_format(
        repo: str,
        check_only: bool = False,
        tool: str = "black",
        paths: str = ".",
    ) -> str:
        """
        Format code using black, isort, or ruff.

        Args:
            repo: Repository path
            check_only: Just check formatting, don't modify files
            tool: Formatter to use (black, isort, ruff)
            paths: Paths to format (default: current directory)

        Returns:
            Formatting result.
        """
        path = resolve_repo_path(repo)

        if tool == "black":
            cmd = ["black"]
            if check_only:
                cmd.append("--check")
            cmd.extend(paths.split())
        elif tool == "isort":
            cmd = ["isort"]
            if check_only:
                cmd.append("--check-only")
            cmd.extend(paths.split())
        elif tool == "ruff":
            cmd = ["ruff", "format"]
            if check_only:
                cmd.append("--check")
            cmd.extend(paths.split())
        else:
            return f"❌ Unknown formatter: {tool}. Use 'black', 'isort', or 'ruff'"

        success, output = await run_cmd(cmd, cwd=path, timeout=120)

        if success:
            if check_only:
                return f"✅ Code formatting check passed ({tool})"
            return f"✅ Code formatted with {tool}\n\n{output or 'All files formatted.'}"

        if check_only:
            return f"⚠️ Formatting issues found ({tool}):\n\n{output}"
        return f"❌ Formatting failed:\n{output}"

    @auto_heal()
    @registry.tool()
    async def code_lint(
        repo: str,
        tool: str = "flake8",
        paths: str = ".",
        max_line_length: int = 100,
        ignore: str = "E501,W503,E203",
        exclude: str = ".git,__pycache__,migrations,venv,.venv",
    ) -> str:
        """
        Run linting checks on code using flake8, ruff, or pylint.

        Args:
            repo: Repository path
            tool: Linter to use (flake8, ruff, pylint)
            paths: Paths to lint (default: current directory)
            max_line_length: Maximum line length (default: 100)
            ignore: Comma-separated error codes to ignore
            exclude: Comma-separated directories to exclude

        Returns:
            Linting results with issues found.
        """
        path = resolve_repo_path(repo)

        if tool == "flake8":
            cmd = [
                "flake8",
                f"--max-line-length={max_line_length}",
                f"--ignore={ignore}",
                f"--exclude={exclude}",
            ]
            cmd.extend(paths.split())
        elif tool == "ruff":
            cmd = ["ruff", "check"]
            if ignore:
                cmd.extend(["--ignore", ignore])
            cmd.extend(paths.split())
        elif tool == "pylint":
            cmd = ["pylint", f"--max-line-length={max_line_length}"]
            if ignore:
                cmd.extend([f"--disable={ignore}"])
            cmd.extend(paths.split())
        else:
            return f"❌ Unknown linter: {tool}. Use 'flake8', 'ruff', or 'pylint'"

        success, output = await run_cmd(cmd, cwd=path, timeout=120)

        if success:
            return f"✅ Linting passed ({tool}) - no issues found"

        lines = output.strip().split("\n") if output.strip() else []
        issue_count = len([ln for ln in lines if ln.strip() and ":" in ln])

        output = truncate_output(
            output,
            max_length=3000,
            suffix=f"\n\n... truncated ({issue_count} total issues)",
        )

        return f"⚠️ Linting issues found ({tool}): {issue_count} issues\n\n```\n{output}\n```"

    # ==================== BUILD/MAKE ====================

    @auto_heal()
    @registry.tool()
    async def make_target(
        repo: str,
        target: str,
        timeout: int = 120,
    ) -> str:
        """
        Run a make target in the repository.

        Args:
            repo: Repository path
            target: Make target to run (e.g., "test", "migrations", "data", "build")
            timeout: Timeout in seconds

        Returns:
            Make output.
        """
        path = resolve_repo_path(repo)

        cmd = ["make", target]
        success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

        if success:
            return f"✅ make {target} completed\n\n{truncate_output(output, 2000, mode='tail')}"
        return f"❌ make {target} failed:\n{truncate_output(output, 2000, mode='tail')}"

    # ==================== DOCKER ====================

    @auto_heal()
    @registry.tool()
    async def docker_compose_status(
        repo: str,
        filter_name: str = "",
    ) -> str:
        """
        Check docker-compose container status.

        Args:
            repo: Repository path (where docker-compose.yml is)
            filter_name: Filter containers by name

        Returns:
            Container status.
        """
        _path = resolve_repo_path(repo)  # noqa: F841 - may be used for validation

        cmd = ["docker", "ps", "--format", "{{.Names}}|{{.Status}}|{{.Ports}}"]
        if filter_name:
            cmd.extend(["--filter", f"name={filter_name}"])

        success, output = await run_cmd(cmd, timeout=30)

        if not success:
            return f"❌ Docker not running or not available: {output}"

        if not output.strip():
            return "No containers running" + (f" matching '{filter_name}'" if filter_name else "")

        lines = ["## Docker Containers", ""]
        for line in output.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 2:
                name, status = parts[0], parts[1]
                ports = parts[2] if len(parts) > 2 else ""
                icon = "🟢" if "Up" in status else "🔴"
                lines.append(f"{icon} **{name}**: {status}")
                if ports:
                    lines.append(f"   Ports: {ports}")

        return "\n".join(lines)

    @auto_heal()
    @registry.tool()
    async def docker_compose_up(
        repo: str,
        detach: bool = True,
        services: str = "",
        timeout: int = 180,
    ) -> str:
        """
        Start docker-compose services.

        Args:
            repo: Repository path (where docker-compose.yml is)
            detach: Run in background
            services: Specific services to start (space-separated, empty = all)
            timeout: Timeout in seconds

        Returns:
            Startup result.
        """
        path = resolve_repo_path(repo)

        cmd = ["docker-compose", "up"]
        if detach:
            cmd.append("-d")
        if services:
            cmd.extend(services.split())

        success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

        if success:
            return f"✅ docker-compose up completed\n\n{truncate_output(output, max_length=1000, mode='tail')}"
        return f"❌ docker-compose up failed:\n{output}"

    @auto_heal()
    @registry.tool()
    async def docker_compose_down(
        repo: str,
        volumes: bool = False,
        timeout: int = 60,
    ) -> str:
        """
        Stop docker-compose services.

        Args:
            repo: Repository path
            volumes: Also remove volumes
            timeout: Timeout in seconds

        Returns:
            Shutdown result.
        """
        path = resolve_repo_path(repo)

        cmd = ["docker-compose", "down"]
        if volumes:
            cmd.append("-v")

        success, output = await run_cmd(cmd, cwd=path, timeout=timeout)

        if success:
            return f"✅ docker-compose down completed\n\n{output}"
        return f"❌ docker-compose down failed:\n{output}"

    @auto_heal()
    @registry.tool()
    async def docker_cp(
        source: str,
        destination: str,
        to_container: bool = True,
    ) -> str:
        """
        Copy files to/from a Docker container.

        Args:
            source: Source path (local path or container:path)
            destination: Destination path (container:path or local path)
            to_container: If True, copy from local to container

        Returns:
            Copy result.
        """
        cmd = ["docker", "cp", source, destination]

        success, output = await run_cmd(cmd, timeout=60)

        if success:
            direction = "to container" if to_container else "from container"
            return f"✅ Copied {direction}: {source} → {destination}"
        return f"❌ Copy failed: {output}"

    @auto_heal()
    @registry.tool()
    async def docker_exec(
        container: str,
        command: str,
        timeout: int = 300,
    ) -> str:
        """
        Execute a command in a running Docker container.

        Args:
            container: Container name or ID
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            Command output.
        """
        cmd = ["docker", "exec", container, "bash", "-c", command]

        success, output = await run_cmd(cmd, timeout=timeout)

        if success:
            return f"## Docker exec: {command[:50]}...\n\n```\n{output}\n```"
        return f"❌ Docker exec failed:\n{output}"

    return registry.count
