"""Git tool definitions.

This module provides the tool registration function that can be called
by the shared server infrastructure.
"""

import logging
import os

from mcp.server.fastmcp import FastMCP

# Setup project path for server imports (must be before server imports)
from tool_modules.common import PROJECT_ROOT  # Sets up sys.path

__project_root__ = PROJECT_ROOT  # Module initialization


from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from server.utils import resolve_repo_path, run_cmd, truncate_output

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
async def _code_lint_impl(
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

    return f"⚠️ Linting issues found ({tool}): {issue_count} issues\n\n```\n{output}\n```"


@auto_heal()
async def _docker_compose_status_impl(
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
    # Validate repo path exists

    resolve_repo_path(repo)

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
async def _docker_compose_up_impl(
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
async def _docker_cp_impl(
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

    Examples:
        docker_cp("/tmp/script.sh", "my_container:/tmp/script.sh", to_container=True)
        docker_cp("my_container:/var/log/app.log", "/tmp/app.log", to_container=False)
    """
    cmd = ["docker", "cp", source, destination]

    success, output = await run_cmd(cmd, timeout=60)

    if success:
        direction = "to container" if to_container else "from container"
        return f"✅ Copied {direction}: {source} → {destination}"
    return f"❌ Copy failed: {output}"


@auto_heal()
async def _docker_exec_impl(
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
async def _git_branch_create_impl(repo: str, branch_name: str, base: str = "", checkout: bool = True) -> str:
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
async def _git_branch_list_impl(
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

    args = ["branch", "--format=%(refname:short)|%(upstream:short)|%(committerdate:relative)"]
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
        from scripts.common.config_loader import format_commit_message, get_commit_format

        commit_cfg = get_commit_format()
        valid_types = commit_cfg["types"]
        return valid_types, format_commit_message, True
    except ImportError:
        valid_types = ["feat", "fix", "refactor", "docs", "test", "chore", "style", "perf"]
        return valid_types, None, False


async def _detect_issue_key(path: str) -> str:
    """Auto-detect issue key from branch name."""
    import re

    success, branch_name = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    if success and branch_name:
        # Match any project pattern: PROJ-12345 (3-6 digits)
        match = re.match(r"([A-Z]{2,10}-\d{3,6})", branch_name.strip().upper())
        if match:
            return match.group(1)
    return ""


def _detect_commit_type(message: str) -> str:
    """Auto-detect commit type from message content."""
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["fix", "bug", "issue", "error", "patch"]):
        return "fix"
    elif any(w in msg_lower for w in ["add", "new", "feature", "implement", "create"]):
        return "feat"
    elif any(w in msg_lower for w in ["refactor", "clean", "improve", "restructure"]):
        return "refactor"
    elif any(w in msg_lower for w in ["doc", "readme", "comment", "documentation"]):
        return "docs"
    elif any(w in msg_lower for w in ["test", "spec", "coverage"]):
        return "test"
    elif any(w in msg_lower for w in ["style", "format", "lint"]):
        return "style"
    elif any(w in msg_lower for w in ["perf", "performance", "optimize", "speed"]):
        return "perf"
    else:
        return "chore"


def _format_commit_msg(
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
    elif issue_key:
        # Fallback formatting
        if scope:
            return f"{issue_key} - {commit_type or 'chore'}({scope}): {message}"
        else:
            return f"{issue_key} - {commit_type or 'chore'}: {message}"
    else:
        return message


async def _git_commit_impl(
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
            from scripts.common.lint_utils import format_lint_error, run_lint_check

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
    formatted_message = _format_commit_msg(message, issue_key, commit_type, scope, formatter_func, use_config)

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
def _build_log_args(
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


def _format_log_output(
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


async def _git_log_impl(
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
    args = _build_log_args(limit, oneline, author, since, until, merges_only, no_merges, numstat, range_spec, branch)

    success, output = await run_git(args, cwd=path)
    if not success:
        return f"❌ Failed to get log: {output}"

    # Format output with helper
    return _format_log_output(repo, output, limit, oneline, author, since, until, range_spec, merges_only, no_merges)


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
async def _git_push_impl(
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
            from scripts.common.lint_utils import format_lint_error, run_lint_check

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
            if line.startswith("UU") or line.startswith("AA") or line.startswith("DU") or line.startswith("UD"):
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


async def _git_rebase_impl(
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


async def _git_status_impl(repo: str) -> str:
    """
    Get the current status of a git repository.

    Args:
        repo: Repository path (e.g., "/home/user/src/myproject" or "myproject")

    Returns:
        Current branch, staged/unstaged changes, untracked files.
    """
    path = resolve_repo_path(repo)
    if not os.path.isdir(path):
        return f"❌ Not a directory: {path}"

    lines = [f"## Git Status: `{repo}`", ""]

    success, branch = await run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    if success:
        lines.append(f"**Branch:** `{branch.strip()}`")

    success, output = await run_git(["status", "--porcelain"], cwd=path)
    if not success:
        return f"❌ Failed to get status: {output}"

    if not output.strip():
        lines.append("\n✅ Working tree clean")
    else:
        # Parse output using helper
        staged, modified, untracked = _parse_status_output(output)

        # Format sections using helper
        lines.extend(_format_status_sections(staged, modified, untracked))

    success, output = await run_git(["rev-list", "--left-right", "--count", "@{u}...HEAD"], cwd=path)
    if success and output.strip():
        parts = output.strip().split()
        if len(parts) == 2:
            behind, ahead = int(parts[0]), int(parts[1])
            if ahead or behind:
                lines.append(f"\n**Sync:** ↑{ahead} ahead, ↓{behind} behind remote")

    return "\n".join(lines)


@auto_heal()
async def _make_target_impl(
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


def _register_code_quality_tools(registry: ToolRegistry) -> None:
    """Register code quality tools."""

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
        return await _code_format_impl(repo, check_only, tool, paths)

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
        return await _code_lint_impl(repo, tool, paths, max_line_length, ignore, exclude)


def _register_docker_tools(registry: ToolRegistry) -> None:
    """Register docker tools."""

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
        return await _docker_compose_status_impl(repo, filter_name)

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
        return await _docker_compose_up_impl(repo, detach, services, timeout)

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

        Examples:
            docker_cp("/tmp/script.sh", "my_container:/tmp/script.sh", to_container=True)
            docker_cp("my_container:/var/log/app.log", "/tmp/app.log", to_container=False)
        """
        return await _docker_cp_impl(source, destination, to_container)

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
        return await _docker_exec_impl(container, command, timeout)


def _register_git_basic_ops_tools(registry: ToolRegistry) -> None:
    """Register git basic ops tools."""

    @auto_heal()
    @registry.tool()
    async def git_add(repo: str, files: str = ".") -> str:
        """Stage files for commit."""
        return await _git_add_impl(repo, files)

    @auto_heal()
    @registry.tool()
    async def git_status(repo: str) -> str:
        """
        Get the current status of a git repository.

        Args:
            repo: Repository path (e.g., "/home/user/src/myproject" or "myproject")

        Returns:
            Current branch, staged/unstaged changes, untracked files.
        """
        return await _git_status_impl(repo)

    @auto_heal()
    @registry.tool()
    async def git_diff(repo: str, staged: bool = False, file: str = "") -> str:
        """Show uncommitted changes."""
        return await _git_diff_impl(repo, staged, file)

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
        return await _git_diff_tree_impl(repo, commit, name_only)

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
        return await _git_show_impl(repo, commit, format, name_only)

    @auto_heal()
    @registry.tool()
    async def git_log(
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
        return await _git_log_impl(
            repo, limit, oneline, author, since, until, branch, range_spec, merges_only, no_merges, count_only, numstat
        )


def _register_git_branching_tools(registry: ToolRegistry) -> None:
    """Register git branching tools."""

    @auto_heal()
    @registry.tool()
    async def git_branch_create(repo: str, branch_name: str, base: str = "", checkout: bool = True) -> str:
        """Create a new branch."""
        return await _git_branch_create_impl(repo, branch_name, base, checkout)

    @auto_heal()
    @registry.tool()
    async def git_branch_list(
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
        return await _git_branch_list_impl(repo, all_branches, merged, no_merged)

    @auto_heal()
    @registry.tool()
    async def git_checkout(
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
        return await _git_checkout_impl(repo, target, create, force_create, start_point)

    @auto_heal()
    @registry.tool()
    async def git_config_get(repo: str, key: str) -> str:
        """
        Get a git config value.

        Args:
            repo: Repository path
            key: Config key (e.g., "user.email", "user.name", "remote.origin.url")

        Returns:
            Config value or error message.
        """
        return await _git_config_get_impl(repo, key)


def _register_git_commits_tools(registry: ToolRegistry) -> None:
    """Register git commits tools."""

    @auto_heal()
    @registry.tool()
    async def git_commit(
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
        return await _git_commit_impl(repo, message, all_changes, issue_key, commit_type, scope, run_lint)

    @auto_heal()
    @registry.tool()
    async def git_fetch(
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
        return await _git_fetch_impl(repo, prune, remote, branch, refspec)

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

        Examples:
            git_rev_parse(repo, "HEAD")           -> "a1b2c3d4e5..."
            git_rev_parse(repo, "main")           -> "f6g7h8i9..."
            git_rev_parse(repo, "abc123", short=True) -> "abc1234"
        """
        return await _git_rev_parse_impl(repo, ref, short, verify)


def _register_git_remote_tools(registry: ToolRegistry) -> None:
    """Register git remote tools."""

    @auto_heal()
    @registry.tool()
    async def git_pull(repo: str, rebase: bool = False) -> str:
        """Pull changes from remote."""
        return await _git_pull_impl(repo, rebase)

    @auto_heal()
    @registry.tool()
    async def git_push(
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
        return await _git_push_impl(repo, branch, set_upstream, force, dry_run, run_lint)


def _register_git_advanced_tools(registry: ToolRegistry) -> None:
    """Register git advanced tools."""

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
        return await _git_merge_impl(repo, target, no_commit, no_ff, message)

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
        return await _git_merge_abort_impl(repo)

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
        return await _git_rebase_impl(repo, onto, abort, continue_rebase, skip, interactive)

    @auto_heal()
    @registry.tool()
    async def git_reset(repo: str, target: str = "HEAD", mode: str = "mixed") -> str:
        """Reset current HEAD to specified state."""
        return await _git_reset_impl(repo, target, mode)

    @auto_heal()
    @registry.tool()
    async def git_stash(repo: str, action: str = "push", message: str = "") -> str:
        """Stash or restore changes."""
        return await _git_stash_impl(repo, action, message)


def _register_build_tools(registry: ToolRegistry) -> None:
    """Register build tools."""

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
        return await _make_target_impl(repo, target, timeout)


def register_tools(server: FastMCP) -> int:
    """
    Register git tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    _register_code_quality_tools(registry)
    _register_docker_tools(registry)
    _register_git_basic_ops_tools(registry)
    _register_git_branching_tools(registry)
    _register_git_commits_tools(registry)
    _register_git_remote_tools(registry)
    _register_git_advanced_tools(registry)
    _register_build_tools(registry)

    return registry.count
