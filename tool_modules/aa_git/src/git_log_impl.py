# pylint: disable=duplicate-code
"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import logging

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.utils import resolve_repo_path, truncate_output

logger = logging.getLogger(__name__)

from tool_modules.aa_git.src.git_tools_impl import (  # pylint: disable=ungrouped-imports,wrong-import-position
    _build_log_args,
    _format_log_output,
    run_git,
)


async def _git_log_impl(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments
    repo: str,
    limit: int = 10,
    oneline: bool = True,
    author: str = "",
    since: str = "",
    until: str = "",
    branch: str = "",
    range_spec: str = "",
    merges_only: bool = False,
    no_merges: bool = False,
    count_only: bool = False,
    numstat: bool = False,
) -> str:
    """
    Show commit history with optional filters.

    Args:
        repo: Repository name or path
        limit: Maximum commits to show
        oneline: Use compact format
        author: Filter by author name/email
        since: Only commits after date (e.g., "2024-01-01", "yesterday", "1 week ago")
        until: Only commits before date
        branch: Specific branch to show (default: current)
        range_spec: Commit range (e.g., "origin/main..HEAD", "main..feature")
        merges_only: Show only merge commits (--merges)
        no_merges: Exclude merge commits (--no-merges)
        count_only: Return only count of commits (for range comparisons)
        numstat: Show number of added/deleted lines per file (--numstat)

    Returns:
        Commit history or count.

    Examples:
        git_log(repo, range_spec="origin/main..HEAD")  # Commits ahead of main
        git_log(repo, merges_only=True, range_spec="main..feature")  # Merge commits only
        git_log(repo, count_only=True, range_spec="HEAD..origin/main")  # How many behind
        git_log(repo, numstat=True, since="1 week ago")  # Lines changed this week
    """
    path = resolve_repo_path(repo)

    # Count-only mode
    if count_only:
        args = ["rev-list", "--count"]
        if range_spec:
            args.append(range_spec)
        elif branch:
            args.append(branch)
        else:
            args.append("HEAD")

        success, output = await run_git(args, cwd=path)
        if not success:
            return f"❌ Failed to count: {output}"
        return output.strip()

    # Regular log - build args with helper
    args = _build_log_args(
        limit,
        oneline,
        author,
        since,
        until,
        merges_only,
        no_merges,
        numstat,
        range_spec,
        branch,
    )

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to get log: {output}"

    # Format output with helper
    return _format_log_output(
        repo,
        output,
        limit,
        oneline,
        author,
        since,
        until,
        range_spec,
        merges_only,
        no_merges,
    )


@auto_heal()
async def _git_merge_impl(
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
async def _git_merge_abort_impl(repo: str) -> str:
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


@auto_heal()
async def _git_pull_impl(repo: str, rebase: bool = False) -> str:
    """Pull changes from remote."""
    path = resolve_repo_path(repo)

    args = ["pull"]
    if rebase:
        args.append("--rebase")

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to pull: {output}"

    return f"✅ Pulled successfully\n\n{output}"


@auto_heal()
async def _git_push_impl(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    repo: str,
    branch: str = "",
    set_upstream: bool = False,
    force: bool = False,
    dry_run: bool = False,
    run_lint: bool = False,
) -> str:
    """
    Push commits to remote.

    Args:
        repo: Repository path
        branch: Branch to push (default: current)
        set_upstream: Set upstream tracking (-u flag)
        force: Force push with lease (--force-with-lease)
        dry_run: Show what would be pushed without pushing
        run_lint: Run black/flake8 check before pushing (blocks on errors)

    Returns:
        Push result or lint error.
    """
    path = resolve_repo_path(repo)

    # Run linting if requested
    if run_lint:
        try:
            from scripts.common.lint_utils import (  # pylint: disable=import-outside-toplevel
                format_lint_error,
                run_lint_check,
            )  # pylint: disable=import-outside-toplevel

            lint_result = run_lint_check(path)
            if not lint_result.passed:
                return format_lint_error(lint_result)
        except ImportError:
            # Fallback if lint_utils not available
            pass

    args = ["push"]
    if dry_run:
        args.append("--dry-run")
    if set_upstream:
        args.extend(["-u", "origin"])
    if force:
        args.append("--force-with-lease")
    if branch:
        if not set_upstream:
            args.append("origin")
        args.append(branch)

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to push: {output}"

    prefix = "(dry-run) " if dry_run else ""
    return f"✅ {prefix}Pushed successfully\n\n{output}"


@auto_heal()
async def _handle_rebase_conflicts(path: str) -> str:
    """Check for rebase conflicts and return formatted message."""
    status_ok, status_output = await run_git(["status", "--porcelain"], cwd=path)

    conflict_files = []
    if status_ok:
        for line in status_output.split("\n"):
            # UU = both modified, AA = both added, DU = deleted by us
            if (
                line.startswith("UU")
                or line.startswith("AA")
                or line.startswith("DU")
                or line.startswith("UD")
            ):
                conflict_files.append(line[3:].strip())

    if not conflict_files:
        return ""

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


async def _git_rebase_impl(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-return-statements
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
        return (
            f"✅ Successfully rebased onto `{onto}`\n\n{output or 'Rebase complete.'}"
        )

    # Check for conflicts using helper
    conflict_msg = await _handle_rebase_conflicts(path)
    if conflict_msg:
        return conflict_msg

    return f"❌ Rebase failed:\n{output}"


@auto_heal()
async def _git_reset_impl(repo: str, target: str = "HEAD", mode: str = "mixed") -> str:
    """Reset current HEAD to specified state."""
    path = resolve_repo_path(repo)

    args = ["reset", f"--{mode}", target]

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to reset: {output}"

    warning = "⚠️ Changes discarded!" if mode == "hard" else ""
    return f"✅ Reset to `{target}` ({mode}) {warning}\n\n{output or 'Done'}"


@auto_heal()
async def _git_rev_parse_impl(
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

    Examples:
        git_rev_parse(repo, "HEAD")           -> "a1b2c3d4e5..."
        git_rev_parse(repo, "main")           -> "f6g7h8i9..."
        git_rev_parse(repo, "abc123", short=True) -> "abc1234"
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
        # Try fetching and retrying
        await run_git(["fetch", "origin"], cwd=path)
        success, output = await run_git(args, cwd=path)

    if not success:
        return f"❌ Could not resolve ref '{ref}': {output}"

    sha = output.strip()

    # Validate SHA format
    if not sha or (not short and len(sha) != 40) or (short and len(sha) < 7):
        return f"❌ Invalid SHA returned for '{ref}': {sha}"

    return sha


@auto_heal()
async def _git_show_impl(
    repo: str,
    commit: str = "HEAD",
    format: str = "",  # pylint: disable=redefined-builtin
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
async def _git_stash_impl(repo: str, action: str = "push", message: str = "") -> str:
    """Stash or restore changes."""
    path = resolve_repo_path(repo)

    args = ["stash", action]
    if action == "push" and message:
        args.extend(["-m", message])

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to stash: {output}"

    if action == "list":
        if not output.strip():
            return "No stashes"
        lines = ["## Stash List", ""]
        for line in output.strip().split("\n"):
            lines.append(f"- {line}")
        return "\n".join(lines)

    return f"✅ Stash {action} successful\n\n{output or 'Done'}"


async def _git_blame_impl(repo: str, file: str, lines: str = "") -> str:
    """Get blame information for a file.

    Args:
        repo: Repository path
        file: File path to blame
        lines: Optional line range (e.g., "1,10" for lines 1-10)

    Returns:
        Blame output showing who last modified each line.
    """
    path = resolve_repo_path(repo)

    args = ["blame", "--porcelain"]
    if lines:
        args.extend(["-L", lines])
    args.append(file)

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to get blame: {output}"

    # Parse porcelain output to extract authors
    authors: dict[str, int] = {}
    current_author = None

    for line in output.split("\n"):
        if line.startswith("author "):
            current_author = line[7:]
            authors[current_author] = authors.get(current_author, 0) + 1

    # Format output
    lines_out = ["## Blame Summary", ""]
    for author, count in sorted(authors.items(), key=lambda x: -x[1]):
        lines_out.append(f"- **{author}**: {count} lines")

    return "\n".join(lines_out)


@auto_heal()
def _parse_status_output(output: str) -> tuple[list, list, list]:
    """Parse git status porcelain output into staged, modified, untracked lists."""
    staged = []
    modified = []
    untracked = []

    for line in output.strip().split("\n"):
        if not line:
            continue
        status = line[:2]
        file = line[3:]

        if status[0] in "MADRC":
            staged.append(f"  - `{file}`")
        if status[1] == "M":
            modified.append(f"  - `{file}`")
        elif status == "??":
            untracked.append(f"  - `{file}`")

    return staged, modified, untracked


def _format_status_sections(staged: list, modified: list, untracked: list) -> list:
    """Format status sections for display."""
    lines = []

    if staged:
        lines.append("\n### Staged")
        lines.extend(staged)
    if modified:
        lines.append("\n### Modified (unstaged)")
        lines.extend(modified)
    if untracked:
        lines.append("\n### Untracked")
        lines.extend(untracked[:10])
        if len(untracked) > 10:
            lines.append(f"  - ... and {len(untracked) - 10} more")

    return lines
