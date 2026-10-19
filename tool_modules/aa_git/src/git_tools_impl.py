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
from server.utils import resolve_repo_path, run_cmd, truncate_output
from tool_modules.aa_docker.src.tools_basic import (  # pylint: disable=ungrouped-imports
    _docker_compose_status_impl as _docker_status_impl,
)
from tool_modules.aa_docker.src.tools_basic import (
    _shared__docker_compose_up_impl,
    _shared__docker_cp_impl,
    _shared__docker_exec_impl,
)

logger = logging.getLogger(__name__)


async def run_git(
    args: list[str],
    cwd: str | None = None,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Run git command and return (success, output)."""
    cmd = ["git"] + args
    return await run_cmd(cmd, cwd=cwd, timeout=timeout)


# ==================== TOOL IMPLEMENTATIONS ====================


@auto_heal()
async def _code_format_impl(
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
async def _code_lint_impl(  # pylint: disable=too-many-arguments,too-many-positional-arguments
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

    # Parse output to count issues
    lines = output.strip().split("\n") if output.strip() else []
    issue_count = len([ln for ln in lines if ln.strip() and ":" in ln])

    # Truncate if too long
    output = truncate_output(
        output,
        max_length=3000,
        suffix=f"\n\n... truncated ({issue_count} total issues)",
    )

    return (
        f"⚠️ Linting issues found ({tool}): {issue_count} issues\n\n```\n{output}\n```"
    )


@auto_heal()
async def _docker_compose_status_impl(repo: str, filter_name: str = "") -> str:
    return await _docker_status_impl(repo, filter_name)


_docker_compose_status_impl.__doc__ = _docker_status_impl.__doc__


@auto_heal()
async def _docker_compose_up_impl(
    repo: str, detach: bool = True, services: str = "", timeout: int = 180
) -> str:
    return await _shared__docker_compose_up_impl(repo, detach, services, timeout)


_docker_compose_up_impl.__doc__ = _shared__docker_compose_up_impl.__doc__


@auto_heal()
async def _docker_cp_impl(
    source: str, destination: str, to_container: bool = True
) -> str:
    return await _shared__docker_cp_impl(source, destination, to_container)


_docker_cp_impl.__doc__ = _shared__docker_cp_impl.__doc__


@auto_heal()
async def _docker_exec_impl(container: str, command: str, timeout: int = 300) -> str:
    return await _shared__docker_exec_impl(container, command, timeout)


_docker_exec_impl.__doc__ = _shared__docker_exec_impl.__doc__


@auto_heal()
async def _git_add_impl(repo: str, files: str = ".") -> str:
    """Stage files for commit."""
    path = resolve_repo_path(repo)

    args = ["add"] + files.split()

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to stage files: {output}"

    _, staged = await run_git(["diff", "--staged", "--name-only"], cwd=path)

    lines = ["✅ Files staged", ""]
    for f in staged.strip().split("\n")[:20]:
        if f:
            lines.append(f"- `{f}`")

    return "\n".join(lines)


@auto_heal()
async def _git_branch_create_impl(
    repo: str, branch_name: str, base: str = "", checkout: bool = True
) -> str:
    """Create a new branch."""
    path = resolve_repo_path(repo)

    if checkout:
        args = ["checkout", "-b", branch_name]
        if base:
            args.append(base)
    else:
        args = ["branch", branch_name]
        if base:
            args.append(base)

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to create branch: {output}"

    lines = [f"✅ Created branch `{branch_name}`", f"**Repository:** `{repo}`"]
    if base:
        lines.append(f"**Base:** `{base}`")
    if checkout:
        lines.append(f"**Switched to:** `{branch_name}`")

    return "\n".join(lines)


@auto_heal()
async def _git_branch_list_impl(  # pylint: disable=too-many-locals
    repo: str,
    all_branches: bool = False,
    merged: str = "",
    no_merged: str = "",
) -> str:
    """
    List branches in a repository.

    Args:
        repo: Repository path
        all_branches: Include remote branches
        merged: Show branches merged into specified branch (e.g., "main")
        no_merged: Show branches NOT merged into specified branch

    Returns:
        Branch list.
    """
    path = resolve_repo_path(repo)

    args = [
        "branch",
        "--format=%(refname:short)|%(upstream:short)|%(committerdate:relative)",
    ]
    if all_branches:
        args.append("-a")
    if merged:
        args.append(f"--merged={merged}")
    if no_merged:
        args.append(f"--no-merged={no_merged}")

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to list branches: {output}"

    _, current = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    current = current.strip()

    lines = [f"## Branches in `{repo}`", f"**Current:** `{current}`", ""]

    for line in output.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|")
        branch = parts[0]
        upstream = parts[1] if len(parts) > 1 else ""
        date = parts[2] if len(parts) > 2 else ""

        icon = "→" if branch == current else " "
        track = f" → `{upstream}`" if upstream else ""
        age = f" ({date})" if date else ""

        lines.append(f"{icon} `{branch}`{track}{age}")

    return "\n".join(lines)


@auto_heal()
async def _git_checkout_impl(
    repo: str,
    target: str,
    create: bool = False,
    force_create: bool = False,
    start_point: str = "",
) -> str:
    """
    Switch branches or restore files.

    Args:
        repo: Repository path
        target: Branch name or file to checkout
        create: Create new branch (-b flag)
        force_create: Force create branch, resetting if exists (-B flag)
        start_point: Starting point for new branch (e.g., "origin/main")

    Returns:
        Checkout result.

    Examples:
        git_checkout(repo, "main")  # Switch to main
        git_checkout(repo, "feature", create=True)  # Create and switch
        git_checkout(repo, "feature", force_create=True, start_point="origin/feature")
    """
    path = resolve_repo_path(repo)

    args = ["checkout"]
    if force_create:
        args.append("-B")
    elif create:
        args.append("-b")
    args.append(target)

    if start_point:
        args.append(start_point)

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to checkout: {output}"

    action = "Created and switched" if (create or force_create) else "Switched"
    return f"✅ {action} to `{target}`\n\n{output}"


@auto_heal()
def _load_commit_config():
    """Load commit configuration from config.json."""
    try:
        from scripts.common.config_loader import (  # pylint: disable=import-outside-toplevel
            format_commit_message,
            get_commit_format,
        )

        commit_cfg = get_commit_format()
        valid_types = commit_cfg["types"]
        return valid_types, format_commit_message, True
    except ImportError:
        valid_types = [
            "feat",
            "fix",
            "refactor",
            "docs",
            "test",
            "chore",
            "style",
            "perf",
        ]
        return valid_types, None, False


async def _detect_issue_key(path: str) -> str:
    """Auto-detect issue key from branch name."""
    import re  # pylint: disable=import-outside-toplevel

    success, branch_name = await run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd=path
    )
    if success and branch_name:
        # Match any project pattern: PROJ-12345 (3-6 digits)
        match = re.match(r"([A-Z]{2,10}-\d{3,6})", branch_name.strip().upper())
        if match:
            return match.group(1)
    return ""


def _detect_commit_type(  # pylint: disable=too-many-return-statements
    message: str,
) -> str:  # pylint: disable=too-many-return-statements
    """Auto-detect commit type from message content."""
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["fix", "bug", "issue", "error", "patch"]):
        return "fix"
    if any(w in msg_lower for w in ["add", "new", "feature", "implement", "create"]):
        return "feat"
    if any(w in msg_lower for w in ["refactor", "clean", "improve", "restructure"]):
        return "refactor"
    if any(w in msg_lower for w in ["doc", "readme", "comment", "documentation"]):
        return "docs"
    if any(w in msg_lower for w in ["test", "spec", "coverage"]):
        return "test"
    if any(w in msg_lower for w in ["style", "format", "lint"]):
        return "style"
    if any(w in msg_lower for w in ["perf", "performance", "optimize", "speed"]):
        return "perf"
    return "chore"


def _format_commit_msg(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    message: str,
    issue_key: str,
    commit_type: str,
    scope: str,
    formatter_func,
    use_config: bool,
) -> str:
    """Format commit message using config pattern or fallback."""
    if use_config and issue_key and formatter_func:
        return formatter_func(
            description=message,
            issue_key=issue_key,
            commit_type=commit_type or "chore",
            scope=scope,
        )
    if issue_key:
        # Fallback formatting
        if scope:
            return f"{issue_key} - {commit_type or 'chore'}({scope}): {message}"
        return f"{issue_key} - {commit_type or 'chore'}: {message}"
    return message


async def _git_commit_impl(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments
    repo: str,
    message: str,
    all_changes: bool = False,
    issue_key: str = "",
    commit_type: str = "",
    scope: str = "",
    run_lint: bool = False,
) -> str:
    """
    Commit staged changes with optional conventional commit format.

    Args:
        repo: Repository path
        message: Commit message
        all_changes: Stage all changes before commit (-a flag)
        issue_key: Jira issue key for conventional commit prefix
        commit_type: Commit type (feat, fix, refactor, etc.)
        scope: Optional scope for conventional commit
        run_lint: Run black/flake8 check before committing (blocks on errors)

    Returns:
        Commit result or lint error.

    Commit Format (from config.json):
        {issue_key} - {type}({scope}): {description}

    Valid types are loaded from config.json commit_format.types.
    """
    path = resolve_repo_path(repo)

    # Load commit format helpers from config.json
    valid_types, formatter_func, use_config = _load_commit_config()

    # Auto-detect issue key from branch name if not provided
    if not issue_key:
        issue_key = await _detect_issue_key(path)

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

    # Auto-detect commit type from message content if not provided
    if issue_key and not commit_type:
        commit_type = _detect_commit_type(message)

    # Validate commit type against config
    if issue_key and commit_type and commit_type not in valid_types:
        return (
            f"❌ Invalid commit type '{commit_type}'.\n\n"
            f"Valid types: {', '.join(valid_types)}\n\n"
            f"Use one of these types or update config.json commit_format.types"
        )

    # Format commit message using config pattern
    formatted_message = _format_commit_msg(
        message, issue_key, commit_type, scope, formatter_func, use_config
    )

    args = ["commit", "-m", formatted_message]
    if all_changes:
        args.insert(1, "-a")

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to commit: {output}"

    _, hash_ = await run_git(["rev-parse", "--short", "HEAD"], cwd=path)

    return (
        f"✅ Committed as `{hash_.strip()}`\n\n"
        f"**Message:** `{formatted_message}`\n\n{output}\n\n"
        "⚠️ IMPORTANT: Do NOT add any Co-Authored-By lines to commits in this repository."
    )


@auto_heal()
async def _git_config_get_impl(repo: str, key: str) -> str:
    """
    Get a git config value.

    Args:
        repo: Repository path
        key: Config key (e.g., "user.email", "user.name", "remote.origin.url")

    Returns:
        Config value or error message.
    """
    path = resolve_repo_path(repo)

    success, output = await run_git(["config", "--get", key], cwd=path)
    if not success:
        return f"❌ Config key not found: {key}"

    return output.strip()


@auto_heal()
async def _git_diff_impl(repo: str, staged: bool = False, file: str = "") -> str:
    """Show uncommitted changes."""
    path = resolve_repo_path(repo)

    args = ["diff", "--stat"]
    if staged:
        args.append("--staged")
    if file:
        args.extend(["--", file])

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to get diff: {output}"

    if not output.strip():
        return "No changes to show"

    args2 = ["diff"]
    if staged:
        args2.append("--staged")
    if file:
        args2.extend(["--", file])

    _, full_diff = await run_git(args2, cwd=path)
    full_diff = truncate_output(full_diff, max_length=10000)

    lines = [
        f"## Diff: `{repo}`" + (" (staged)" if staged else ""),
        "",
        "### Summary",
        "```",
        output,
        "```",
        "",
        "### Changes",
        "```diff",
        full_diff,
        "```",
    ]

    return "\n".join(lines)


@auto_heal()
async def _git_diff_tree_impl(
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
async def _git_fetch_impl(
    repo: str,
    prune: bool = True,
    remote: str = "",
    branch: str = "",
    refspec: str = "",
) -> str:
    """
    Fetch changes from remote without merging.

    Args:
        repo: Repository path
        prune: Remove remote-tracking refs that no longer exist on remote
        remote: Specific remote to fetch from (default: all)
        branch: Specific branch to fetch
        refspec: Custom refspec (e.g., "merge-requests/123/head:mr-123")

    Returns:
        Fetch result.
    """
    path = resolve_repo_path(repo)

    args = ["fetch"]
    if not remote and not refspec:
        args.append("--all")
    if prune:
        args.append("--prune")
    if remote:
        args.append(remote)
    if branch and not refspec:
        args.append(branch)
    if refspec:
        if not remote:
            args.append("origin")
        args.append(refspec)

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to fetch: {output}"

    return f"✅ Fetched successfully\n\n{output or 'Already up to date.'}"


@auto_heal()
def _build_log_args(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    limit: int,
    oneline: bool,
    author: str,
    since: str,
    until: str,
    merges_only: bool,
    no_merges: bool,
    numstat: bool,
    range_spec: str,
    branch: str,
) -> list:
    """Build git log command arguments from parameters."""
    if oneline:
        args = ["log", f"-{limit}", "--oneline", "--decorate"]
    else:
        args = ["log", f"-{limit}", "--format=%h|%an|%ar|%s"]

    if author:
        args.append(f"--author={author}")
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    if merges_only:
        args.append("--merges")
    if no_merges:
        args.append("--no-merges")
    if numstat:
        args.append("--numstat")
        if oneline:
            # For numstat with oneline, use a different format
            args = [a for a in args if a != "--oneline"]
            args.insert(2, "--pretty=format:%h %s")

    # Range or branch comes last
    if range_spec:
        args.append(range_spec)
    elif branch:
        args.append(branch)

    return args


def _format_log_output(  # pylint: disable=too-many-arguments,too-many-locals,too-many-positional-arguments
    repo: str,
    output: str,
    limit: int,
    oneline: bool,
    author: str,
    since: str,
    until: str,
    range_spec: str,
    merges_only: bool,
    no_merges: bool,
) -> str:
    """Format git log output with headers and filters."""
    # Build header
    filters = []
    if author:
        filters.append(f"by {author}")
    if since:
        filters.append(f"since {since}")
    if until:
        filters.append(f"until {until}")
    if range_spec:
        filters.append(f"range {range_spec}")
    if merges_only:
        filters.append("merges only")
    if no_merges:
        filters.append("no merges")
    filter_str = f" ({', '.join(filters)})" if filters else ""

    lines = [f"## Recent Commits in `{repo}`{filter_str}", ""]

    if not output.strip():
        lines.append("*No commits found matching criteria*")
        return "\n".join(lines)

    if oneline:
        for line in output.strip().split("\n")[:limit]:
            lines.append(f"- `{line}`")
    else:
        for line in output.strip().split("\n")[:limit]:
            parts = line.split("|")
            if len(parts) >= 4:
                hash_, author_name, date, msg = parts[0], parts[1], parts[2], parts[3]
                lines.append(f"- `{hash_}` {msg}")
                lines.append(f"  *{author_name}* - {date}")

    return "\n".join(lines)
