"""Workflow Tools - High-level workflow coordination tools.

Provides workflow tools for common development tasks:
- workflow_start_work: Get context to start working on a Jira issue
- workflow_check_deploy_readiness: Check if MR is ready to deploy
- workflow_review_feedback: Get guidance on addressing review feedback
- workflow_create_branch: Create a feature branch from a Jira issue
- workflow_prepare_mr: Prepare a Merge Request
- workflow_run_local_checks: Run local linting and validation
- workflow_monitor_pipelines: Monitor GitLab + Konflux pipelines
- workflow_handle_review: Prepare to handle MR review feedback
- workflow_daily_standup: Generate a summary of recent work
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.types import TextContent

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import load_config, resolve_repo_path, run_cmd_full

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

# Alias for run command
run_cmd = run_cmd_full

# Load repository paths from config
REPOS_CONFIG = load_config()
repos_data = REPOS_CONFIG.get("repositories", {})
if isinstance(repos_data, dict):
    REPO_PATHS = {
        name: info.get("path", "") for name, info in repos_data.items() if info.get("path")
    }
else:
    REPO_PATHS = {}


def resolve_path(repo: str) -> str:
    """Resolve repo name to path."""
    if repo in REPO_PATHS:
        return REPO_PATHS[repo]
    # Try shared resolver
    resolved = resolve_repo_path(repo)
    if os.path.isdir(resolved):
        return resolved
    raise ValueError(f"Unknown repository: {repo}")


def register_workflow_tools(server: "FastMCP") -> int:
    """Register workflow tools with the MCP server."""
    tool_count = 0

    @server.tool()
    async def workflow_start_work(issue_key: str) -> list[TextContent]:
        """
        Get all context needed to start working on a Jira issue.

        This suggests a branch name and provides next steps for development.
        For full Jira and GitLab details, use the aa-jira and aa-gitlab servers.

        Args:
            issue_key: Jira issue key (e.g., AAP-12345)

        Returns:
            Suggested workflow for starting work on the issue.
        """
        issue_key = issue_key.upper()

        # Generate branch name
        branch_name = f"{issue_key}-feature"

        result = f"""# Starting Work on {issue_key}

## 📋 Issue
View issue details: `jira_view_issue('{issue_key}')`

## 🚀 Suggested Workflow

1. **Get issue details:**
   - `jira_view_issue('{issue_key}')`

2. **Check for existing MRs:**
   - `gitlab_search_mrs_by_issue('your-backend', '{issue_key}')`

3. **Create branch:**
   ```bash
   git checkout -b {branch_name} origin/main
   ```

4. **Implement changes**

5. **Run local checks:**
   - `lint_python(repo='.')`
   - `test_run(repo='.')`
   - `precommit_run(repo='.')`

6. **Push and create MR:**
   ```bash
   git push -u origin {branch_name}
   ```
   - `gitlab_mr_create(project='your-backend', title='{issue_key} - feature description')`

### Commit Message Format
```
{issue_key} - feat: <description>
```

## 🔗 Quick Links
- Jira: [configured in config.json]/browse/{issue_key}
- GitLab: [configured in config.json]/project/merge_requests
"""

        return [TextContent(type="text", text=result)]

    tool_count += 1

    @server.tool()
    async def workflow_check_deploy_readiness(
        project: str,
        mr_id: int,
        environment: str = "stage",
    ) -> list[TextContent]:
        """
        Check if a merge request is ready to deploy.

        Provides a checklist for deployment readiness.
        Use individual tools (gitlab, konflux, prometheus) for detailed status.

        Args:
            project: Project name or path
            mr_id: Merge request IID
            environment: Target environment ("stage" or "prod")

        Returns:
            Deployment readiness checklist.
        """
        result = f"""# Deployment Readiness Checklist: !{mr_id}

## Pre-Deployment Checks

Run these tools to verify readiness:

### 1. GitLab Pipeline
```
gitlab_ci_status(project='{project}')
gitlab_mr_view(project='{project}', mr_id={mr_id})
```

### 2. Konflux Integration Tests
```
konflux_list_pipelines(namespace='your-tenant')
```

### 3. Monitoring Status ({environment})
```
prometheus_check_health(namespace='your-app-{environment}', environment='{environment}')
prometheus_get_alerts(environment='{environment}')
```

### 4. Image Availability
```
quay_list_aa_tags()
```

## Deployment Steps

1. ✅ GitLab pipeline passed
2. ✅ Konflux tests passed
3. ✅ No critical alerts in {environment}
4. ✅ Image built and pushed to Quay

## Environment URLs

- Stage: [configured in config.json clusters.stage]
- Prod: [configured in config.json clusters.production]
"""

        return [TextContent(type="text", text=result)]

    tool_count += 1

    @server.tool()
    async def workflow_review_feedback(
        project: str,
        mr_id: int,
    ) -> list[TextContent]:
        """
        Get guidance on addressing review feedback.

        Args:
            project: Project name or path
            mr_id: Merge request IID

        Returns:
            Guide for addressing review feedback.
        """
        result = f"""# Addressing Review Feedback: !{mr_id}

## Get Review Comments
```
gitlab_mr_comments(project='{project}', mr_id={mr_id})
gitlab_mr_view(project='{project}', mr_id={mr_id})
```

## Workflow for Addressing Feedback

1. **Read all comments:**
   - Focus on unresolved comments first
   - Note any blocking concerns

2. **For each comment:**
   - If code change needed: make the fix
   - If discussion needed: reply with your reasoning
   - If won't fix: explain why in a reply

3. **After making changes:**
   ```bash
   git add -A
   git commit -m "Address review feedback"
   git push
   ```

4. **Reply to comments:**
   ```
   gitlab_mr_comment(project='{project}', mr_id={mr_id}, message='Addressed: <description>')
   ```

5. **Re-request review:**
   - GitLab will automatically notify reviewers of new commits

## Tips

- Address all comments before requesting re-review
- Use "resolve" threads for simple fixes
- Keep discussions focused on the code change
"""

        return [TextContent(type="text", text=result)]

    tool_count += 1

    @server.tool()
    async def workflow_create_branch(
        issue_key: str,
        repo: str,
        branch_type: str = "feature",
    ) -> list[TextContent]:
        """
        Create a feature branch from a Jira issue.

        Args:
            issue_key: Jira issue key (e.g., "AAP-12345")
            repo: Repository name or path
            branch_type: Branch prefix (feature, bugfix, hotfix)

        Returns:
            Branch creation status.
        """
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        issue_key = issue_key.upper()
        branch_name = f"{branch_type}/{issue_key}-work"

        lines = [f"## Creating Branch for `{issue_key}`", ""]

        # 1. Fetch latest
        success, stdout, stderr = await run_cmd(["git", "fetch", "--all", "--prune"], cwd=path)
        lines.append("### 1. Fetch latest")
        lines.append("✅ Fetched" if success else f"⚠️ {stderr[:50]}")

        # 2. Check for existing branch
        success, stdout, stderr = await run_cmd(
            ["git", "branch", "-a", "--list", f"*{issue_key}*"], cwd=path
        )
        if stdout.strip():
            lines.append("\n### Existing branch found:")
            lines.append(f"```\n{stdout.strip()}\n```")
            lines.append("\nTo switch to it: `git checkout <branch-name>`")
            return [TextContent(type="text", text="\n".join(lines))]

        # 3. Checkout main and pull
        await run_cmd(["git", "checkout", "main"], cwd=path)
        await run_cmd(["git", "pull", "--rebase"], cwd=path)

        # 4. Create branch
        success, stdout, stderr = await run_cmd(["git", "checkout", "-b", branch_name], cwd=path)
        if not success:
            return [TextContent(type="text", text=f"❌ Failed to create branch: {stderr}")]

        lines.append(f"\n### 2. Created branch: `{branch_name}`")
        lines.append(f"\n**Ready to start work on {issue_key}!**")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def workflow_prepare_mr(
        issue_key: str,
        repo: str,
        draft: bool = True,
    ) -> list[TextContent]:
        """
        Prepare a Merge Request - push branch and provide glab command.

        Args:
            issue_key: Jira issue key
            repo: Repository name
            draft: Create as draft MR

        Returns:
            MR preparation result.
        """
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Preparing MR for `{issue_key}`", ""]

        # 1. Get current branch
        success, stdout, stderr = await run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path
        )
        if not success:
            return [TextContent(type="text", text="❌ Failed to get branch")]
        current_branch = stdout.strip()
        lines.append(f"**Branch:** `{current_branch}`")

        # 2. Push branch
        lines.append("\n### 1. Pushing branch...")
        success, stdout, stderr = await run_cmd(
            ["git", "push", "-u", "origin", current_branch], cwd=path
        )
        if success:
            lines.append("✅ Pushed")
        else:
            if "up-to-date" in stderr.lower() or "already exists" in stderr.lower():
                lines.append("✅ Branch already pushed")
            else:
                return [TextContent(type="text", text=f"❌ Push failed: {stderr}")]

        # 3. Provide glab command
        lines.append("\n### 2. Create MR with glab:")
        draft_flag = "--draft" if draft else ""
        lines.append("```bash")
        lines.append(f'glab mr create --title "{issue_key}: Description" {draft_flag} --yes')
        lines.append("```")

        lines.append("\n### Or use the gitlab_mr_create tool")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def workflow_run_local_checks(
        repo: str,
        skip_tests: bool = False,
    ) -> list[TextContent]:
        """
        Run local linting and validation before pushing.

        Args:
            repo: Repository name
            skip_tests: Skip running tests

        Returns:
            Lint results.
        """
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Local Checks: `{repo}`", ""]
        all_passed = True

        # Detect and run appropriate linters
        if (Path(path) / "pyproject.toml").exists():
            # Python project
            for cmd_name, cmd in [
                ("black --check", ["black", "--check", "."]),
                ("isort --check", ["isort", "--check-only", "."]),
                ("flake8", ["flake8", "."]),
            ]:
                lines.append(f"\n### {cmd_name}")
                success, stdout, stderr = await run_cmd(cmd, cwd=path)
                if success:
                    lines.append("✅ Passed")
                else:
                    lines.append("❌ Failed")
                    all_passed = False
                    output = stderr or stdout
                    if output:
                        lines.append(f"```\n{output[:1000]}\n```")

        if (Path(path) / "package.json").exists():
            # Node project
            lines.append("\n### npm run lint")
            success, stdout, stderr = await run_cmd(["npm", "run", "lint"], cwd=path)
            if success:
                lines.append("✅ Passed")
            else:
                lines.append("❌ Failed")
                all_passed = False

        if not skip_tests:
            lines.append("\n---")
            lines.append("*To include tests, use `test_run()`*")

        lines.append("")
        if all_passed:
            lines.append("## ✅ All checks passed!")
        else:
            lines.append("## ❌ Some checks failed")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def workflow_monitor_pipelines(
        repo: str,
        branch: str = "",
    ) -> list[TextContent]:
        """
        Monitor all pipelines for a branch (GitLab + Konflux).

        Args:
            repo: Repository name
            branch: Branch to check (default: current)

        Returns:
            Pipeline status summary.
        """
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Pipeline Status: `{repo}`", ""]

        # Get current branch
        if not branch:
            success, stdout, _ = await run_cmd(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path
            )
            branch = stdout.strip() if success else "unknown"
        lines.append(f"**Branch:** `{branch}`")

        # GitLab CI status
        lines.append("\n### GitLab CI")
        success, stdout, stderr = await run_cmd(["glab", "ci", "status"], cwd=path)
        if success:
            lines.append(f"```\n{stdout}\n```")
        else:
            lines.append(f"⚠️ {stderr[:100]}")

        # Konflux hint
        lines.append("\n### Konflux")
        lines.append("Use `konflux_list_pipelines()` for Konflux pipeline status")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def workflow_handle_review(
        issue_key: str,
        repo: str,
    ) -> list[TextContent]:
        """
        Prepare to handle MR review feedback.

        Args:
            issue_key: Jira issue key
            repo: Repository name

        Returns:
            Review feedback summary and next steps.
        """
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Handling Review: `{issue_key}`", ""]

        # Find and switch to branch
        success, stdout, _ = await run_cmd(
            ["git", "branch", "-a", "--list", f"*{issue_key}*"], cwd=path
        )
        if stdout.strip():
            branch = stdout.strip().split("\n")[0].strip().replace("* ", "")
            lines.append(f"**Branch:** `{branch}`")

            # Pull latest
            await run_cmd(["git", "checkout", branch], cwd=path)
            await run_cmd(["git", "pull", "--rebase"], cwd=path)
            lines.append("✅ Switched and pulled latest")
        else:
            lines.append("⚠️ Branch not found")

        lines.append("\n### Next Steps")
        lines.append("1. Use `gitlab_mr_view()` to see MR details")
        lines.append("2. Use `gitlab_mr_comments()` to see review comments")
        lines.append("3. Make changes and commit")
        lines.append("4. `git push` to update MR")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    @server.tool()
    async def workflow_daily_standup(
        author: str = "",
    ) -> list[TextContent]:
        """
        Generate a summary of recent work for standup.

        Args:
            author: Git author name (default: from git config)

        Returns:
            Summary of recent work.
        """
        lines = ["## 📋 Daily Standup Summary", ""]

        # Get git author
        if not author:
            success, stdout, _ = await run_cmd(["git", "config", "user.name"])
            author = stdout.strip() if success else ""
        if author:
            lines.append(f"**Author:** {author}")

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        lines.append(f"**Since:** {yesterday}")
        lines.append("")

        # Check each configured repo for recent commits
        lines.append("### Recent Commits")
        for name, path in REPO_PATHS.items():
            if not path or not os.path.isdir(path):
                continue
            success, stdout, _ = await run_cmd(
                [
                    "git",
                    "log",
                    f"--since={yesterday}",
                    f"--author={author}" if author else "--all",
                    "--oneline",
                    "-5",
                ],
                cwd=path,
            )
            if success and stdout.strip():
                lines.append(f"\n**{name}:**")
                for line in stdout.strip().split("\n")[:5]:
                    lines.append(f"- {line}")

        lines.append("\n### Open MRs")
        lines.append("Use `gitlab_mr_list()` with author filter to see your open MRs")

        lines.append("\n### Jira Issues")
        lines.append("Use `jira_my_issues()` to see your assigned issues")

        return [TextContent(type="text", text="\n".join(lines))]

    tool_count += 1

    return tool_count

