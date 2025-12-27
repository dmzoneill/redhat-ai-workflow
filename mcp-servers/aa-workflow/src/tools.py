"""Workflow MCP Server - High-level workflow and local development tools.

Provides workflow coordination and local development tools:
- workflow_start_work: Get context to start working on a Jira issue
- workflow_check_deploy_readiness: Check if MR is ready to deploy
- workflow_review_feedback: Get review comments on an MR
- lint_python: Run Python linters (black, flake8, isort)
- lint_yaml: Validate YAML files
- lint_dockerfile: Lint Dockerfiles with hadolint
- test_run: Run tests (pytest/npm)
- test_coverage: Get coverage report
- security_scan: Run security scanning (bandit/npm audit)
- precommit_run: Run pre-commit hooks
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

# Add aa-common to path for shared utilities
SERVERS_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(SERVERS_DIR / "aa-common"))

from src.utils import (
    get_username,
    load_config,
    resolve_repo_path,
    run_cmd_full,
    run_cmd_shell,
)

logger = logging.getLogger(__name__)


REPOS_CONFIG = load_config()
# Repos are stored as dict: {"name": {"path": "...", ...}}
repos_data = REPOS_CONFIG.get("repositories", {})
if isinstance(repos_data, dict):
    REPO_PATHS = {
        name: info.get("path", "") for name, info in repos_data.items() if info.get("path")
    }
else:
    REPO_PATHS = {}

# GitHub configuration for error reporting
GITHUB_REPO = "dmzoneill/redhat-ai-workflow"
GITHUB_ISSUES_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/issues"

# Track recently created issues to avoid duplicates (in-memory cache)
_recent_issues: dict[str, float] = {}
_ISSUE_DEDUP_SECONDS = 3600  # Don't create duplicate issues within 1 hour


def _get_github_token() -> str | None:
    """Get GitHub token from environment."""
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


def _issue_fingerprint(tool: str, error: str) -> str:
    """Create a fingerprint for deduplication."""
    import hashlib

    # Use first 100 chars of error to group similar errors
    content = f"{tool}:{error[:100]}"
    return hashlib.md5(content.encode()).hexdigest()[:12]


async def create_github_issue(
    tool: str, error: str, context: str = "", skill: str = "", labels: list[str] | None = None
) -> dict:
    """
    Create a GitHub issue for a tool/skill failure.

    Returns:
        dict with 'success', 'issue_url', and 'message'
    """
    import time

    import httpx

    # Check for duplicate
    fingerprint = _issue_fingerprint(tool, error)
    now = time.time()

    if fingerprint in _recent_issues:
        last_created = _recent_issues[fingerprint]
        if now - last_created < _ISSUE_DEDUP_SECONDS:
            return {
                "success": False,
                "issue_url": None,
                "message": f"Similar issue recently created (dedup: {fingerprint})",
            }

    # Check for GitHub token
    token = _get_github_token()
    if not token:
        # Fall back to URL generation
        url = format_github_issue_url(tool, error, context)
        return {
            "success": False,
            "issue_url": url,
            "message": "No GITHUB_TOKEN - use this link to create manually",
        }

    # Build issue body
    import platform
    import sys

    body = f"""## 🐛 Automated Error Report

**Tool/Skill:** `{tool}`
{f"**Skill:** `{skill}`" if skill else ""}

### Error
```
{error[:1000]}
```

### Context
{context[:500] if context else "No additional context provided"}

### Environment
- **Python:** {sys.version.split()[0]}
- **Platform:** {platform.system()} {platform.release()}
- **Fingerprint:** `{fingerprint}`

---
*This issue was automatically created by AI Workflow error tracking.*
"""

    # Determine labels
    issue_labels = labels or ["bug", "automated"]
    if "jira" in tool.lower() or "rh-issue" in error.lower():
        issue_labels.append("jira")
    if "gitlab" in tool.lower():
        issue_labels.append("gitlab")
    if "k8s" in tool.lower() or "kubectl" in tool.lower():
        issue_labels.append("kubernetes")

    # Create the issue
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GITHUB_API_URL,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "AI-Workflow-Error-Reporter",
                },
                json={"title": f"[Auto] Tool Error: {tool}", "body": body, "labels": issue_labels},
                timeout=30.0,
            )

            if response.status_code == 201:
                data = response.json()
                issue_url = data.get("html_url", "")
                _recent_issues[fingerprint] = now

                logger.info(f"Created GitHub issue: {issue_url}")
                return {
                    "success": True,
                    "issue_url": issue_url,
                    "message": f"Issue created: {issue_url}",
                }
            else:
                logger.warning(
                    f"Failed to create issue: {response.status_code} - {response.text[:200]}"
                )
                url = format_github_issue_url(tool, error, context)
                return {
                    "success": False,
                    "issue_url": url,
                    "message": f"API error {response.status_code} - use link to create manually",
                }

    except Exception as e:
        logger.error(f"Error creating GitHub issue: {e}")
        url = format_github_issue_url(tool, error, context)
        return {
            "success": False,
            "issue_url": url,
            "message": f"Failed: {e} - use link to create manually",
        }


def format_github_issue_url(tool: str, error: str, context: str = "") -> str:
    """Generate a pre-filled GitHub issue URL for tool errors."""
    import urllib.parse

    title = f"Tool Error: {tool}"
    body = f"""## Error Report

**Tool:** `{tool}`
**Error:** 
```
{error[:500]}
```

**Context:**
{context[:200] if context else "No additional context"}

**Environment:**
- AI Workflow version: (please fill in)
- Python version: (please fill in)

**Steps to reproduce:**
1. (describe what you were doing)

**Expected behavior:**
(what should have happened)
"""
    params = urllib.parse.urlencode({"title": title, "body": body, "labels": "bug,tool-error"})
    return f"{GITHUB_ISSUES_URL}?{params}"


# ==================== Helper Functions ====================

# run_cmd is imported from src.utils as run_cmd_full
run_cmd = run_cmd_full


def resolve_path(repo: str) -> str:
    """Resolve repo name to path."""
    if repo in REPO_PATHS:
        return REPO_PATHS[repo]
    # Try shared resolver
    resolved = resolve_repo_path(repo)
    if os.path.isdir(resolved):
        return resolved
    raise ValueError(f"Unknown repository: {repo}")


# ==================== WORKFLOW TOOLS ====================


def register_tools(server: "FastMCP") -> int:
    """Register tools with the MCP server."""

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
        slug = issue_key.lower().replace("-", "")
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

    # ==================== INFRASTRUCTURE CONNECTIVITY ====================

    @server.tool()
    async def vpn_connect() -> list[TextContent]:
        """
        Connect to the Red Hat VPN.

        Use this when tools fail with 'No route to host' or similar network errors.

        The VPN is required for:
        - Ephemeral cluster access
        - Stage cluster access
        - Konflux cluster access
        - Internal GitLab access

        Returns:
            VPN connection result.
        """
        config = load_config()
        paths = config.get("paths", {})

        # Get VPN script path from config or use default
        vpn_script = paths.get("vpn_connect_script")
        if not vpn_script:
            # Default location
            vpn_script = os.path.expanduser("~/src/redhatter/src/redhatter_vpn/vpn-connect")

        vpn_script = os.path.expanduser(vpn_script)

        if not os.path.exists(vpn_script):
            return [
                TextContent(
                    type="text",
                    text=f"""❌ VPN connect script not found at: {vpn_script}

**To fix:**
1. Clone the redhatter repo or ensure the script exists
2. Or add to config.json:
```json
{{
  "paths": {{
    "vpn_connect_script": "/path/to/vpn-connect"
  }}
}}
```

💡 Alternatively, run manually: `vpn-connect` or use your VPN client.""",
                )
            ]

        lines = ["## Connecting to VPN...", ""]

        try:
            # Run the VPN connect script through user's login shell
            # This ensures proper environment and any GUI prompts work
            success, stdout, stderr = await run_cmd_shell(
                [vpn_script],
                timeout=120,  # VPN connection can take time
            )

            output = stdout + stderr

            if (
                success
                or "successfully activated" in output.lower()
                or "connection successfully" in output.lower()
            ):
                lines.append("✅ VPN connected successfully")
            else:
                lines.append("⚠️ VPN connection may have failed")

            lines.append("")
            lines.append("```")
            lines.append(output[-2000:] if len(output) > 2000 else output)
            lines.append("```")

        except asyncio.TimeoutError:
            lines.append("❌ VPN connection timed out after 120s")
            lines.append("Try running manually: `vpn-connect`")
        except Exception as e:
            lines.append(f"❌ Error: {e}")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def kube_login(
        cluster: str,
    ) -> list[TextContent]:
        """
        Refresh Kubernetes credentials for a cluster.

        Use this when tools fail with 'Unauthorized', 'token expired', or similar auth errors.

        Args:
            cluster: Cluster to login to:
                     - 's' or 'stage' = Stage cluster
                     - 'p' or 'prod' = Production cluster
                     - 'k' or 'konflux' = Konflux cluster
                     - 'e' or 'ephemeral' = Ephemeral cluster

        Returns:
            Login result with new token info.
        """
        # Normalize cluster name to short form
        cluster_map = {
            "stage": "s",
            "production": "p",
            "prod": "p",
            "konflux": "k",
            "ephemeral": "e",
        }

        short_cluster = cluster_map.get(cluster.lower(), cluster.lower())

        if short_cluster not in ["s", "p", "k", "e"]:
            return [
                TextContent(
                    type="text",
                    text=f"""❌ Unknown cluster: {cluster}

**Valid options:**
- `s` or `stage` = Stage cluster
- `p` or `prod` = Production cluster
- `k` or `konflux` = Konflux cluster
- `e` or `ephemeral` = Ephemeral cluster""",
                )
            ]

        cluster_names = {
            "s": "Stage",
            "p": "Production",
            "k": "Konflux",
            "e": "Ephemeral",
        }

        lines = [f"## Logging into {cluster_names[short_cluster]} cluster...", ""]

        kubeconfig_suffix = {
            "s": ".s",
            "p": ".p",
            "k": ".k",
            "e": ".e",
        }
        kubeconfig = os.path.expanduser(f"~/.kube/config{kubeconfig_suffix[short_cluster]}")

        try:
            # First, check if existing credentials are valid
            needs_reauth = False
            if os.path.exists(kubeconfig):
                test_success, _, _ = await run_cmd_full(
                    ["oc", "--kubeconfig", kubeconfig, "whoami"],
                    timeout=10,
                )
                if not test_success:
                    lines.append("⚠️ Existing credentials are stale, cleaning up...")
                    lines.append("")
                    needs_reauth = True
                    # Clean up stale config so kube will force re-auth
                    await run_cmd_shell(["kube-clean", short_cluster], timeout=30)

            lines.append("🌐 *A browser window may open for SSO authentication*")
            lines.append("")

            # Run kube through user's login shell to get:
            # - DISPLAY/XAUTHORITY for browser auth (rhtoken opens Chrome)
            # - Access to kube bash function from ~/.bashrc.d/01-redhatter-kubeconfig.sh
            kube_cmd = ["kube", short_cluster]

            # Longer timeout for browser-based SSO auth
            success, stdout, stderr = await run_cmd_shell(
                kube_cmd,
                timeout=120,  # 2 minutes for SSO
            )

            output = stdout + stderr

            if success:
                lines.append(f"✅ Logged into {cluster_names[short_cluster]} cluster")
            else:
                lines.append(f"⚠️ Login may have issues")

            lines.append("")
            lines.append("```")
            lines.append(output[-1500:] if len(output) > 1500 else output)
            lines.append("```")

            # Test the connection
            if os.path.exists(kubeconfig):
                lines.append("")
                lines.append("### Testing connection...")

                test_success, test_out, test_err = await run_cmd_full(
                    [
                        "kubectl",
                        "--kubeconfig",
                        kubeconfig,
                        "get",
                        "ns",
                        "--no-headers",
                        "-o",
                        "name",
                    ],
                    timeout=30,
                )

                if test_success:
                    ns_count = len(test_out.strip().split("\n")) if test_out.strip() else 0
                    lines.append(f"✅ Connection verified ({ns_count} namespaces accessible)")
                else:
                    lines.append(f"⚠️ Connection test failed: {test_err}")

        except FileNotFoundError:
            lines.append("❌ `kube` command not found")
            lines.append("")
            lines.append("The `kube` script should be in your PATH. It typically:")
            lines.append("1. Runs `oc login` with the appropriate cluster URL")
            lines.append("2. Saves credentials to `~/.kube/config.{s,p,k,e}`")
            lines.append("")
            lines.append("**Alternative manual login:**")
            lines.append("```bash")
            lines.append("oc login --server=<cluster-url>")
            lines.append("```")
        except Exception as e:
            lines.append(f"❌ Error: {e}")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== PYTHON LINTING ====================

    @server.tool()
    async def lint_python(
        repo: str,
        fix: bool = False,
    ) -> list[TextContent]:
        """
        Run Python linters (black, flake8, isort).

        Args:
            repo: Repository name or path
            fix: Apply fixes automatically (black, isort)

        Returns:
            Lint results with issues found.
        """
        try:
            path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Python Linting: `{repo}`", ""]
        all_passed = True

        # 1. Black
        lines.append("### Black (formatting)")
        black_args = ["black", "."]
        if not fix:
            black_args.append("--check")

        success, stdout, stderr = await run_cmd(black_args, cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("❌ Issues found")
            all_passed = False
            output = stderr or stdout
            if output:
                lines.append(f"```\n{output[:1500]}\n```")
        lines.append("")

        # 2. isort
        lines.append("### isort (imports)")
        isort_args = ["isort", "."]
        if not fix:
            isort_args.append("--check-only")

        success, stdout, stderr = await run_cmd(isort_args, cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("❌ Issues found")
            all_passed = False
            output = stderr or stdout
            if output:
                lines.append(f"```\n{output[:1500]}\n```")
        lines.append("")

        # 3. Flake8
        lines.append("### Flake8 (style)")
        success, stdout, stderr = await run_cmd(["flake8", ".", "--max-line-length=120"], cwd=path)
        if success:
            lines.append("✅ Passed")
        else:
            lines.append("❌ Issues found")
            all_passed = False
            if stdout:
                issue_count = len(stdout.strip().split("\n"))
                lines.append(f"Found {issue_count} issues:")
                lines.append(f"```\n{stdout[:2000]}\n```")
        lines.append("")

        # 4. mypy (optional)
        mypy_config = Path(path) / "mypy.ini"
        pyproject = Path(path) / "pyproject.toml"

        if mypy_config.exists() or (pyproject.exists() and "mypy" in pyproject.read_text()):
            lines.append("### mypy (types)")
            success, stdout, stderr = await run_cmd(["mypy", "."], cwd=path)
            if success:
                lines.append("✅ Passed")
            else:
                lines.append("⚠️ Type issues")
                if stdout:
                    lines.append(f"```\n{stdout[:1500]}\n```")

        # Summary
        lines.append("")
        if all_passed:
            lines.append("## ✅ All Python checks passed!")
        else:
            lines.append("## ❌ Some checks failed")
            if not fix:
                lines.append("*Run with fix=True to auto-fix formatting issues*")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def lint_yaml(
        repo: str,
        path_filter: str = ".",
    ) -> list[TextContent]:
        """
        Validate YAML files using yamllint.

        Args:
            repo: Repository name or path
            path_filter: Specific path to lint (default: all)

        Returns:
            YAML validation results.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        target = os.path.join(repo_path, path_filter)

        success, stdout, stderr = await run_cmd(
            ["yamllint", "-f", "parsable", target], cwd=repo_path
        )

        lines = [f"## YAML Linting: `{repo}`", ""]

        if success:
            lines.append("✅ All YAML files valid")
        else:
            output = stdout or stderr
            if output:
                issues = output.strip().split("\n")
                lines.append(f"❌ Found {len(issues)} issues:")
                lines.append("```")
                for issue in issues[:30]:
                    lines.append(issue)
                if len(issues) > 30:
                    lines.append(f"... and {len(issues) - 30} more")
                lines.append("```")
            else:
                lines.append("❌ Validation failed")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def lint_dockerfile(
        repo: str,
        dockerfile: str = "Dockerfile",
    ) -> list[TextContent]:
        """
        Lint Dockerfile using hadolint.

        Args:
            repo: Repository name or path
            dockerfile: Path to Dockerfile (relative to repo)

        Returns:
            Dockerfile best practice suggestions.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        dockerfile_path = os.path.join(repo_path, dockerfile)

        if not os.path.exists(dockerfile_path):
            return [TextContent(type="text", text=f"❌ Dockerfile not found: {dockerfile}")]

        success, stdout, stderr = await run_cmd(["hadolint", dockerfile_path])

        lines = [f"## Dockerfile Linting: `{dockerfile}`", ""]

        if success and not stdout.strip():
            lines.append("✅ No issues found")
        else:
            output = stdout or stderr
            if output:
                lines.append("⚠️ Suggestions:")
                lines.append("```")
                lines.append(output[:2000])
                lines.append("```")
            else:
                lines.append("❌ Linting failed")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== TESTING ====================

    @server.tool()
    async def test_run(
        repo: str,
        test_path: str = "",
        verbose: bool = False,
        coverage: bool = False,
    ) -> list[TextContent]:
        """
        Run tests (pytest or npm test).

        Args:
            repo: Repository name or path
            test_path: Specific test file/directory (optional)
            verbose: Show verbose output
            coverage: Run with coverage

        Returns:
            Test results summary.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Running Tests: `{repo}`", ""]

        # Detect test framework
        if (Path(repo_path) / "pyproject.toml").exists() or (
            Path(repo_path) / "pytest.ini"
        ).exists():
            # Python/pytest
            cmd = ["pytest"]
            if test_path:
                cmd.append(test_path)
            if verbose:
                cmd.append("-v")
            if coverage:
                cmd.extend(["--cov=.", "--cov-report=term-missing"])

            lines.append("**Framework:** pytest")
            lines.append(f"**Command:** `{' '.join(cmd)}`")
            lines.append("")

        elif (Path(repo_path) / "package.json").exists():
            # Node.js
            cmd = ["npm", "test"]
            if test_path:
                cmd.extend(["--", test_path])

            lines.append("**Framework:** npm test")
            lines.append("")
        else:
            return [TextContent(type="text", text="⚠️ No test framework detected (pytest/npm)")]

        success, stdout, stderr = await run_cmd(cmd, cwd=repo_path, timeout=600)

        output = stdout + "\n" + stderr

        # Parse pytest output for summary
        if "pytest" in cmd[0]:
            for line in output.split("\n"):
                if "passed" in line or "failed" in line or "error" in line:
                    if "=" in line:
                        lines.append(f"**Result:** {line.strip()}")
                        break

        if success:
            lines.append("\n✅ Tests passed!")
        else:
            lines.append("\n❌ Tests failed")

        # Add output
        lines.append("\n### Output")
        lines.append("```")
        if len(output) > 5000:
            lines.append("... (truncated)\n")
            lines.append(output[-4500:])
        else:
            lines.append(output)
        lines.append("```")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def test_coverage(repo: str) -> list[TextContent]:
        """
        Get test coverage report.

        Args:
            repo: Repository name or path

        Returns:
            Coverage percentage and uncovered files.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Test Coverage: `{repo}`", ""]

        success, stdout, stderr = await run_cmd(
            ["pytest", "--cov=.", "--cov-report=term-missing", "-q"], cwd=repo_path, timeout=600
        )

        output = stdout + "\n" + stderr

        in_coverage = False
        coverage_lines = []
        for line in output.split("\n"):
            if "TOTAL" in line or "coverage:" in line.lower():
                coverage_lines.append(line)
            elif "Name" in line and "Stmts" in line:
                in_coverage = True
                coverage_lines.append(line)
            elif in_coverage and line.strip():
                if line.startswith("---") or line.startswith("==="):
                    in_coverage = False
                else:
                    coverage_lines.append(line)

        if coverage_lines:
            lines.append("```")
            lines.extend(coverage_lines[:30])
            lines.append("```")
        else:
            lines.append("⚠️ Could not parse coverage output")
            lines.append(f"```\n{output[:2000]}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== SECURITY ====================

    @server.tool()
    async def security_scan(repo: str) -> list[TextContent]:
        """
        Run security scan (bandit for Python, npm audit for Node).

        Args:
            repo: Repository name or path

        Returns:
            Security vulnerabilities found.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        lines = [f"## Security Scan: `{repo}`", ""]

        # Python
        if (Path(repo_path) / "pyproject.toml").exists() or (
            Path(repo_path) / "requirements.txt"
        ).exists():
            lines.append("### Bandit (Python)")
            success, stdout, stderr = await run_cmd(
                ["bandit", "-r", ".", "-f", "txt", "-ll"], cwd=repo_path
            )

            if success:
                lines.append("✅ No issues found")
            else:
                output = stdout or stderr
                lines.append(f"```\n{output[:2000]}\n```")

        # Node.js
        if (Path(repo_path) / "package.json").exists():
            lines.append("\n### npm audit")
            success, stdout, stderr = await run_cmd(["npm", "audit", "--json"], cwd=repo_path)

            try:
                audit = json.loads(stdout)
                vulns = audit.get("metadata", {}).get("vulnerabilities", {})
                total = sum(vulns.values())

                if total == 0:
                    lines.append("✅ No vulnerabilities found")
                else:
                    lines.append(f"⚠️ Found {total} vulnerabilities:")
                    for severity, count in vulns.items():
                        if count > 0:
                            lines.append(f"  - {severity}: {count}")
            except:
                lines.append(f"```\n{stdout[:1500]}\n```")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== PRE-COMMIT ====================

    @server.tool()
    async def precommit_run(
        repo: str,
        all_files: bool = False,
    ) -> list[TextContent]:
        """
        Run pre-commit hooks.

        Args:
            repo: Repository name or path
            all_files: Run on all files (not just staged)

        Returns:
            Pre-commit hook results.
        """
        try:
            repo_path = resolve_path(repo)
        except ValueError as e:
            return [TextContent(type="text", text=f"❌ {e}")]

        if not (Path(repo_path) / ".pre-commit-config.yaml").exists():
            return [TextContent(type="text", text="⚠️ No .pre-commit-config.yaml found")]

        cmd = ["pre-commit", "run"]
        if all_files:
            cmd.append("--all-files")

        success, stdout, stderr = await run_cmd(cmd, cwd=repo_path, timeout=300)

        lines = [f"## Pre-commit: `{repo}`", ""]

        output = stdout or stderr

        for line in output.split("\n"):
            if "Passed" in line:
                lines.append(f"✅ {line}")
            elif "Failed" in line:
                lines.append(f"❌ {line}")
            elif "Skipped" in line:
                lines.append(f"⏭️ {line}")
            elif line.strip() and not line.startswith(" "):
                lines.append(line)

        if success:
            lines.append("\n## ✅ All hooks passed!")
        else:
            lines.append("\n## ❌ Some hooks failed")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== BRANCH WORKFLOWS (from workflow_cli_tools) ====================

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
            lines.append(f"\n### Existing branch found:")
            lines.append(f"```\n{stdout.strip()}\n```")
            lines.append(f"\nTo switch to it: `git checkout <branch-name>`")
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
            return [TextContent(type="text", text=f"❌ Failed to get branch")]
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
        lines.append(f"```bash")
        lines.append(f'glab mr create --title "{issue_key}: Description" {draft_flag} --yes')
        lines.append(f"```")

        lines.append(f"\n### Or use the gitlab_mr_create tool")

        return [TextContent(type="text", text="\n".join(lines))]

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
        from datetime import datetime, timedelta

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

    # ==================== SKILLS ====================
    # Executable multi-step workflows

    # Path: tools.py -> src -> aa-workflow -> mcp-servers -> ai-workflow
    SKILLS_DIR = Path(__file__).parent.parent.parent.parent / "skills"

    @server.tool()
    async def skill_list() -> list[TextContent]:
        """
        List all available skills (reusable workflows).

        Skills are multi-step workflows that combine MCP tools with logic.
        Use skill_run() to execute a skill.

        Returns:
            List of available skills with descriptions.
        """
        skills = []
        if SKILLS_DIR.exists():
            for f in SKILLS_DIR.glob("*.yaml"):
                if f.name == "README.md":
                    continue
                try:
                    import yaml

                    with open(f) as fp:
                        data = yaml.safe_load(fp)
                    skills.append(
                        {
                            "name": data.get("name", f.stem),
                            "description": data.get("description", "No description"),
                            "inputs": [i["name"] for i in data.get("inputs", [])],
                        }
                    )
                except Exception as e:
                    skills.append(
                        {"name": f.stem, "description": f"Error loading: {e}", "inputs": []}
                    )

        if not skills:
            return [
                TextContent(
                    type="text", text="No skills found. Create .yaml files in skills/ directory."
                )
            ]

        lines = ["## Available Skills\n"]
        for s in skills:
            inputs = ", ".join(s["inputs"]) if s["inputs"] else "none"
            lines.append(f"### {s['name']}")
            lines.append(f"{s['description']}")
            lines.append(f"**Inputs:** {inputs}\n")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== SKILL EXECUTION ENGINE ====================

    class SkillExecutor:
        """Full skill execution engine with debug support."""

        def __init__(self, skill: dict, inputs: dict, debug: bool = False):
            self.skill = skill
            self.inputs = inputs
            self.debug = debug
            # Load config.json config for compute blocks
            self.config = load_config()
            self.context = {
                "inputs": inputs,
                "config": self.config,  # Make config available in templates
            }
            self.log: list[str] = []
            self.step_results: list[dict] = []
            self.start_time = None

        def _debug(self, msg: str):
            """Add debug message."""
            if self.debug:
                import time

                elapsed = f"[{time.time() - self.start_time:.2f}s]" if self.start_time else ""
                self.log.append(f"🔍 {elapsed} {msg}")

        def _template(self, text: str) -> str:
            """Resolve {{ variable }} templates in text."""
            import re

            def replace_var(match):
                var_path = match.group(1).strip()
                try:
                    # Navigate the context for nested paths like "inputs.issue_key" or "issue.summary"
                    # Also handles array indexing like "pr_ids_to_check[0]" or "items[0].name"
                    value = self.context

                    # Split by '.' but preserve array indices
                    # e.g., "pr_ids_to_check[0]" -> ["pr_ids_to_check[0]"]
                    # e.g., "items[0].name" -> ["items[0]", "name"]
                    parts = var_path.split(".")

                    for part in parts:
                        # Check for array index: "var[0]" or "var[1]"
                        array_match = re.match(r"^(\w+)\[(\d+)\]$", part)
                        if array_match:
                            var_name, index = array_match.groups()
                            index = int(index)
                            # Get the variable
                            if isinstance(value, dict):
                                value = value.get(var_name)
                            elif hasattr(value, var_name):
                                value = getattr(value, var_name)
                            else:
                                return match.group(0)
                            # Get the index
                            if isinstance(value, (list, tuple)) and index < len(value):
                                value = value[index]
                            else:
                                return match.group(0)
                        elif isinstance(value, dict):
                            value = value.get(part, match.group(0))
                            if value == match.group(0):
                                return value  # Key not found
                        elif hasattr(value, part):
                            value = getattr(value, part)
                        else:
                            return match.group(0)  # Keep original if not found
                    return str(value) if value is not None else ""
                except Exception:
                    return match.group(0)

            # Replace {{ var }} patterns
            result = re.sub(r"\{\{\s*([^}]+)\s*\}\}", replace_var, str(text))
            return result

        def _template_dict(self, d: dict) -> dict:
            """Recursively template a dictionary."""
            result = {}
            for k, v in d.items():
                if isinstance(v, str):
                    result[k] = self._template(v)
                elif isinstance(v, dict):
                    result[k] = self._template_dict(v)
                elif isinstance(v, list):
                    result[k] = [self._template(i) if isinstance(i, str) else i for i in v]
                else:
                    result[k] = v
            return result

        def _eval_condition(self, condition: str) -> bool:
            """Safely evaluate a condition expression."""
            self._debug(f"Evaluating condition: {condition}")

            # Template the condition first
            templated = self._template(condition)
            self._debug(f"  → Templated: {templated}")

            # Create safe eval context
            safe_context = {
                "len": len,
                "any": any,
                "all": all,
                "True": True,
                "False": False,
                "None": None,
                **self.context,
            }

            try:
                result = eval(templated, {"__builtins__": {}}, safe_context)
                self._debug(f"  → Result: {result}")
                return bool(result)
            except Exception as e:
                self._debug(f"  → Error: {e}, defaulting to True")
                return True  # Default to executing if we can't evaluate

        def _exec_compute(self, code: str, output_name: str) -> any:
            """Execute a compute block (limited Python)."""
            self._debug(f"Executing compute block for '{output_name}'")

            # Create execution context
            local_vars = dict(self.context)
            local_vars["inputs"] = self.inputs
            local_vars["config"] = self.config  # Make config available

            # Import commonly needed modules for compute blocks
            import os
            import re
            from datetime import datetime, timedelta
            from pathlib import Path

            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                ZoneInfo = None

            # Add project root to sys.path for 'from scripts.common.X' imports
            PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))

            # Try to import parsers and config_loader
            try:
                from scripts.common import parsers
                from scripts.common.config_loader import (
                    get_timezone,
                )
                from scripts.common.config_loader import load_config as load_skill_config
            except ImportError:
                parsers = None
                load_skill_config = None
                get_timezone = None

            # Try to import Google API modules
            try:
                from google.oauth2.credentials import Credentials as GoogleCredentials
                from googleapiclient.discovery import build as google_build
            except ImportError:
                GoogleCredentials = None
                google_build = None

            # Add safe built-ins with __import__ for flexibility
            safe_globals = {
                "__builtins__": {
                    # Core types
                    "len": len,
                    "str": str,
                    "int": int,
                    "float": float,
                    "list": list,
                    "dict": dict,
                    "bool": bool,
                    "tuple": tuple,
                    "set": set,
                    # Iteration
                    "range": range,
                    "enumerate": enumerate,
                    "zip": zip,
                    "map": map,
                    "filter": filter,
                    # Aggregation
                    "sorted": sorted,
                    "min": min,
                    "max": max,
                    "sum": sum,
                    "any": any,
                    "all": all,
                    # Type checking
                    "isinstance": isinstance,
                    "type": type,
                    "hasattr": hasattr,
                    "getattr": getattr,
                    # String/repr
                    "repr": repr,
                    "print": print,
                    "dir": dir,
                    "vars": vars,
                    # Exceptions
                    "Exception": Exception,
                    "ValueError": ValueError,
                    "TypeError": TypeError,
                    "KeyError": KeyError,
                    "AttributeError": AttributeError,
                    "IndexError": IndexError,
                    "ImportError": ImportError,
                    # Constants
                    "True": True,
                    "False": False,
                    "None": None,
                    # I/O
                    "open": open,
                    # Allow imports for flexibility
                    "__import__": __import__,
                },
                # Pre-imported modules
                "re": re,
                "os": os,
                "Path": Path,
                "datetime": datetime,
                "timedelta": timedelta,
                "ZoneInfo": ZoneInfo,
                # Parsers module
                "parsers": parsers,
                "load_config": load_skill_config,
                "get_timezone": get_timezone,
                # Google API
                "GoogleCredentials": GoogleCredentials,
                "google_build": google_build,
            }

            try:
                # Template the code
                templated_code = self._template(code)
                self._debug(f"  → Code: {templated_code[:100]}...")

                # Execute
                exec(templated_code, safe_globals, local_vars)

                # Check for return value or output variable
                if output_name in local_vars:
                    result = local_vars[output_name]
                elif "result" in local_vars:
                    result = local_vars["result"]
                elif "return" in templated_code:
                    # Simple return extraction
                    for line in reversed(templated_code.split("\n")):
                        if line.strip().startswith("return "):
                            expr = line.strip()[7:]
                            result = eval(expr, safe_globals, local_vars)
                            break
                    else:
                        result = None
                else:
                    result = None

                self._debug(f"  → Result: {str(result)[:100]}")
                return result

            except Exception as e:
                self._debug(f"  → Compute error: {e}")
                return f"<compute error: {e}>"

        async def _exec_tool(self, tool_name: str, args: dict) -> dict:
            """Execute a tool and return its result."""
            import time

            start = time.time()

            self._debug(f"Calling tool: {tool_name}")
            self._debug(f"  → Args: {json.dumps(args)[:200]}")

            # Determine module for this tool
            module_prefixes = {
                "git_": "git",
                "jira_": "jira",
                "gitlab_": "gitlab",
                "kubectl_": "k8s",
                "k8s_": "k8s",
                "prometheus_": "prometheus",
                "alertmanager_": "alertmanager",
                "kibana_": "kibana",
                "konflux_": "konflux",
                "tkn_": "konflux",
                "bonfire_": "bonfire",
                "quay_": "quay",
                "appinterface_": "appinterface",
                # Workflow tools (various prefixes)
                "workflow_": "workflow",
                "lint_": "workflow",
                "test_": "workflow",
                "security_": "workflow",
                "precommit_": "workflow",
                "memory_": "workflow",
                "agent_": "workflow",
                "skill_": "workflow",
                "session_": "workflow",
                "tool_": "workflow",
            }

            module = None
            for prefix, mod in module_prefixes.items():
                if tool_name.startswith(prefix):
                    module = mod
                    break

            if not module:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}

            # Load and execute
            SERVERS_DIR = Path(__file__).parent.parent.parent

            # Special case for workflow tools - they're in this file
            if module == "workflow":
                # Try to call from the current server
                try:
                    result = await server.call_tool(tool_name, args)
                    duration = time.time() - start
                    self._debug(f"  → Completed in {duration:.2f}s")

                    if isinstance(result, tuple):
                        result = result[0]
                    if isinstance(result, list) and result:
                        text = result[0].text if hasattr(result[0], "text") else str(result[0])
                        return {"success": True, "result": text, "duration": duration}
                    return {"success": True, "result": str(result), "duration": duration}
                except Exception as e:
                    return {"success": False, "error": str(e)}

            tools_file = SERVERS_DIR / f"aa-{module}" / "src" / "tools.py"

            if not tools_file.exists():
                return {"success": False, "error": f"Module not found: {module}"}

            try:
                import importlib.util

                temp_server = FastMCP(f"skill-{module}")
                spec = importlib.util.spec_from_file_location(f"skill_{module}", tools_file)
                if spec is None or spec.loader is None:
                    return {"success": False, "error": f"Could not load: {module}"}

                loaded_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(loaded_module)

                if hasattr(loaded_module, "register_tools"):
                    loaded_module.register_tools(temp_server)

                result = await temp_server.call_tool(tool_name, args)
                duration = time.time() - start

                self._debug(f"  → Completed in {duration:.2f}s")

                if isinstance(result, tuple):
                    result = result[0]
                if isinstance(result, list) and result:
                    text = result[0].text if hasattr(result[0], "text") else str(result[0])
                    return {"success": True, "result": text, "duration": duration}

                return {"success": True, "result": str(result), "duration": duration}

            except Exception as e:
                self._debug(f"  → Error: {e}")
                return {"success": False, "error": str(e)}

        async def execute(self) -> str:
            """Execute all steps and return the result."""
            import time

            self.start_time = time.time()

            skill_name = self.skill.get("name", "unknown")
            self._debug(f"Starting skill: {skill_name}")
            self._debug(f"Inputs: {json.dumps(self.inputs)}")

            # Apply defaults
            for inp in self.skill.get("inputs", []):
                name = inp["name"]
                if name not in self.inputs and "default" in inp:
                    self.inputs[name] = inp["default"]
                    self.context["inputs"] = self.inputs
                    self._debug(f"Applied default: {name} = {inp['default']}")

            # Also load any defaults section
            defaults = self.skill.get("defaults", {})
            self.context["defaults"] = defaults

            output_lines = [f"## 🚀 Executing Skill: {skill_name}\n"]
            output_lines.append(f"*{self.skill.get('description', '')}*\n")

            if self.debug:
                output_lines.append("### 📋 Inputs")
                for k, v in self.inputs.items():
                    output_lines.append(f"- `{k}`: {v}")
                output_lines.append("")

            output_lines.append("### 📝 Execution Log\n")

            step_num = 0
            for step in self.skill.get("steps", []):
                step_num += 1
                step_name = step.get("name", f"step_{step_num}")

                # Check condition
                if "condition" in step:
                    if not self._eval_condition(step["condition"]):
                        self._debug(f"Skipping step '{step_name}' - condition false")
                        output_lines.append(
                            f"⏭️ **Step {step_num}: {step_name}** - *skipped (condition false)*\n"
                        )
                        continue

                # Handle 'then' blocks (conditional execution)
                if "then" in step:
                    self._debug(f"Processing 'then' block")
                    for then_item in step["then"]:
                        if "return" in then_item:
                            # Early return
                            ret = then_item["return"]
                            templated = (
                                self._template_dict(ret)
                                if isinstance(ret, dict)
                                else self._template(str(ret))
                            )
                            self._debug(f"Early return: {templated}")

                            total_time = time.time() - self.start_time
                            output_lines.append(f"✅ **Early Exit**\n{templated}\n")
                            output_lines.append(f"\n---\n⏱️ *Completed in {total_time:.2f}s*")

                            if self.debug and self.log:
                                output_lines.append("\n\n### 🔍 Debug Log\n```")
                                output_lines.extend(self.log)
                                output_lines.append("```")

                            return "\n".join(output_lines)
                    continue

                # Execute tool step
                if "tool" in step:
                    tool = step["tool"]
                    raw_args = step.get("args", {})
                    args = self._template_dict(raw_args)

                    output_lines.append(f"🔧 **Step {step_num}: {step_name}**")
                    output_lines.append(f"   *Tool: `{tool}`*")

                    result = await self._exec_tool(tool, args)

                    if result["success"]:
                        # Store output in context
                        output_name = step.get("output", step_name)
                        self.context[output_name] = result["result"]

                        # Also try to parse as structured data
                        try:
                            # Check if it looks like a structured response
                            if ":" in result["result"]:
                                # Simple key-value extraction
                                parsed = {}
                                for line in result["result"].split("\n"):
                                    if ":" in line and not line.strip().startswith("#"):
                                        key, _, val = line.partition(":")
                                        parsed[key.strip().lower().replace(" ", "_")] = val.strip()
                                if parsed:
                                    self.context[f"{output_name}_parsed"] = parsed
                        except Exception:
                            pass

                        duration = result.get("duration", 0)
                        output_lines.append(f"   ✅ Success ({duration:.2f}s)")

                        # Show truncated result
                        result_preview = result["result"][:300]
                        if len(result["result"]) > 300:
                            result_preview += "..."
                        output_lines.append(f"   ```\n   {result_preview}\n   ```\n")

                        self.step_results.append(
                            {"step": step_name, "tool": tool, "success": True, "duration": duration}
                        )
                    else:
                        output_lines.append(f"   ❌ Error: {result['error']}")

                        # Auto-create GitHub issue for tool failures
                        skill_name = self.skill.get("name", "unknown")
                        context = f"Skill: {skill_name}, Step: {step_name}"

                        try:
                            issue_result = await create_github_issue(
                                tool=tool, error=result["error"], context=context, skill=skill_name
                            )

                            if issue_result["success"]:
                                output_lines.append(
                                    f"\n   🐛 **Issue created:** {issue_result['issue_url']}"
                                )
                            elif issue_result["issue_url"]:
                                output_lines.append(f"\n   💡 **Report this error:**")
                                output_lines.append(
                                    f"   📝 [Create GitHub Issue]({issue_result['issue_url']})"
                                )
                                if "dedup" in issue_result.get("message", ""):
                                    output_lines.append(f"   *(Similar issue recently reported)*")
                        except Exception as e:
                            self._debug(f"Failed to create issue: {e}")

                        # Check on_error behavior
                        on_error = step.get("on_error", "fail")
                        if on_error == "continue":
                            output_lines.append(
                                f"   *Continuing despite error (on_error: continue)*\n"
                            )
                            self.step_results.append(
                                {
                                    "step": step_name,
                                    "tool": tool,
                                    "success": False,
                                    "error": result["error"],
                                }
                            )
                        else:
                            output_lines.append(f"\n⛔ **Skill failed at step {step_num}**")
                            break

                # Execute compute step
                elif "compute" in step:
                    output_name = step.get("output", step_name)
                    output_lines.append(f"🧮 **Step {step_num}: {step_name}** (compute)")

                    result = self._exec_compute(step["compute"], output_name)
                    self.context[output_name] = result

                    output_lines.append(f"   → `{output_name}` = {str(result)[:100]}\n")

                # Description/manual step
                elif "description" in step:
                    output_lines.append(f"📝 **Step {step_num}: {step_name}** (manual)")
                    output_lines.append(f"   {self._template(step['description'])}\n")

            # Generate outputs
            if self.skill.get("outputs"):
                output_lines.append("\n### 📤 Outputs\n")
                for out in self.skill["outputs"]:
                    out_name = out.get("name", "output")
                    if "value" in out:
                        templated = self._template(out["value"])
                        output_lines.append(f"**{out_name}:**\n{templated}\n")
                    elif "compute" in out:
                        result = self._exec_compute(out["compute"], out_name)
                        output_lines.append(f"**{out_name}:** {result}\n")

            # Summary
            total_time = time.time() - self.start_time
            success_count = sum(1 for r in self.step_results if r.get("success"))
            fail_count = sum(1 for r in self.step_results if not r.get("success"))

            output_lines.append(
                f"\n---\n⏱️ *Completed in {total_time:.2f}s* | ✅ {success_count} succeeded | ❌ {fail_count} failed"
            )

            # Debug log
            if self.debug and self.log:
                output_lines.append("\n\n### 🔍 Debug Log\n```")
                output_lines.extend(self.log)
                output_lines.append("```")

            return "\n".join(output_lines)

    @server.tool()
    async def skill_run(
        skill_name: str, inputs: str = "{}", execute: bool = True, debug: bool = False
    ) -> list[TextContent]:
        """
        Execute a skill (multi-step workflow).

        Skills chain multiple MCP tools together with logic and conditions.

        Args:
            skill_name: Name of the skill (e.g., "start_work", "investigate_alert")
            inputs: JSON object with input parameters (e.g., '{"issue_key": "AAP-12345"}')
            execute: If True (default), actually run the tools. If False, just show the plan.
            debug: If True, show detailed execution trace with timing.

        Returns:
            Execution results or plan preview.

        Examples:
            skill_run("start_work", '{"issue_key": "AAP-12345", "repo": "backend"}')
            skill_run("investigate_alert", '{"environment": "stage"}', debug=True)
            skill_run("create_mr", '{"issue_key": "AAP-12345"}', execute=False)  # Plan only
        """
        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            available = [f.stem for f in SKILLS_DIR.glob("*.yaml")] if SKILLS_DIR.exists() else []
            return [
                TextContent(
                    type="text",
                    text=f"❌ Skill not found: {skill_name}\n\nAvailable: {', '.join(available) or 'none'}",
                )
            ]

        try:
            import yaml

            with open(skill_file) as f:
                skill = yaml.safe_load(f)

            # Parse inputs
            try:
                input_data = json.loads(inputs) if inputs else {}
            except json.JSONDecodeError:
                return [TextContent(type="text", text=f"❌ Invalid inputs JSON: {inputs}")]

            # Validate required inputs
            missing = []
            for inp in skill.get("inputs", []):
                if inp.get("required", False) and inp["name"] not in input_data:
                    if "default" not in inp:
                        missing.append(inp["name"])

            if missing:
                # Show required inputs help
                lines = [f"❌ Missing required inputs: {', '.join(missing)}\n"]
                lines.append("### Required Inputs\n")
                for inp in skill.get("inputs", []):
                    req = "**required**" if inp.get("required") else "optional"
                    default = f" (default: {inp['default']})" if "default" in inp else ""
                    lines.append(
                        f"- `{inp['name']}` ({inp.get('type', 'string')}) - {req}{default}"
                    )
                    if inp.get("description"):
                        lines.append(f"  {inp['description']}")
                return [TextContent(type="text", text="\n".join(lines))]

            if not execute:
                # Plan-only mode - show what would be executed
                lines = [f"## 📋 Skill Plan: {skill.get('name', skill_name)}\n"]
                lines.append(f"*{skill.get('description', '')}*\n")
                lines.append("### Inputs")
                for k, v in input_data.items():
                    lines.append(f"- `{k}`: {v}")
                lines.append("\n### Steps to Execute\n")

                step_num = 0
                for step in skill.get("steps", []):
                    step_num += 1
                    name = step.get("name", f"step_{step_num}")

                    if "tool" in step:
                        lines.append(f"{step_num}. **{name}** → `{step['tool']}`")
                        if step.get("condition"):
                            lines.append(f"   *Condition: {step['condition']}*")
                    elif "compute" in step:
                        lines.append(f"{step_num}. **{name}** → compute")
                    elif "description" in step:
                        lines.append(f"{step_num}. **{name}** → manual step")

                lines.append("\n*Run with `execute=True` to execute this plan*")
                return [TextContent(type="text", text="\n".join(lines))]

            # Full execution
            executor = SkillExecutor(skill, input_data, debug=debug)
            result = await executor.execute()

            return [TextContent(type="text", text=result)]

        except Exception as e:
            import traceback

            if debug:
                return [
                    TextContent(
                        type="text", text=f"❌ Error: {e}\n\n```\n{traceback.format_exc()}\n```"
                    )
                ]
            return [TextContent(type="text", text=f"❌ Error loading skill: {e}")]

    # ==================== AGENTS ====================
    # Load specialized personas

    AGENTS_DIR = Path(__file__).parent.parent.parent.parent / "agents"

    @server.tool()
    async def agent_list() -> list[TextContent]:
        """
        List all available agent personas.

        Agents are specialized AI personas with specific expertise, tools, and workflows.
        Use agent_load() to get an agent's full context.

        Returns:
            List of available agents with their focus areas.
        """
        agents = []
        if AGENTS_DIR.exists():
            for f in AGENTS_DIR.glob("*.md"):
                if f.name == "README.md":
                    continue
                try:
                    content = f.read_text()
                    # Extract first heading and first paragraph
                    lines = content.split("\n")
                    name = f.stem
                    role = ""
                    for line in lines:
                        if line.startswith("# "):
                            name = line[2:].strip()
                        elif line.startswith("## Your Role"):
                            idx = lines.index(line)
                            if idx + 1 < len(lines):
                                role = lines[idx + 1].strip("- ")
                            break
                    agents.append({"name": f.stem, "title": name, "role": role})
                except Exception as e:
                    agents.append({"name": f.stem, "title": f.stem, "role": f"Error: {e}"})

        if not agents:
            return [
                TextContent(
                    type="text", text="No agents found. Create .md files in agents/ directory."
                )
            ]

        lines = ["## Available Agents\n"]
        for a in agents:
            lines.append(f"### {a['title']} (`{a['name']}`)")
            lines.append(f"{a['role']}\n")

        lines.append("\nUse `agent_load(agent_name)` to load an agent's full context.")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def agent_load(agent_name: str, ctx=None) -> list[TextContent]:
        """
        Load an agent with its full toolset and persona.

        This dynamically switches to the specified agent by:
        1. Unloading current tools (except core tools)
        2. Loading the agent's tool modules
        3. Notifying Cursor of the tool change
        4. Returning the agent's persona for adoption

        Args:
            agent_name: Agent to load (e.g., "devops", "developer", "incident", "release")

        Returns:
            Agent context with confirmation of tools loaded.
        """
        # Try dynamic loading first
        try:
            import sys

            # Add aa-common to path if needed
            common_path = str(Path(__file__).parent.parent.parent / "aa-common")
            if common_path not in sys.path:
                sys.path.insert(0, common_path)

            from src.agent_loader import get_loader

            loader = get_loader()
            if loader and ctx:
                # Dynamic mode - switch tools
                result = await loader.switch_agent(agent_name, ctx)

                if result["success"]:
                    lines = [
                        f"## 🔄 Agent Switched: {agent_name}",
                        "",
                        f"**Description:** {result['description']}",
                        f"**Modules:** {', '.join(result['modules_loaded'])}",
                        f"**Tools loaded:** {result['tool_count']}",
                        "",
                        "---",
                        "",
                        "⚠️ **IMPORTANT:** Call tools DIRECTLY by name now!",
                        "   ✅ `bonfire_namespace_list(mine_only=True)`",
                        "   ❌ `tool_exec('bonfire_namespace_list', ...)`",
                        "",
                        "This way Cursor shows the actual tool name instead of 'tool_exec'.",
                        "",
                        "---",
                        "",
                        result["persona"],
                    ]
                    return [TextContent(type="text", text="\n".join(lines))]
                else:
                    return [
                        TextContent(
                            type="text",
                            text=f"❌ {result['error']}\n\nAvailable: {', '.join(result.get('available', []))}",
                        )
                    ]
        except Exception as e:
            logger.warning(f"Dynamic loading not available: {e}")

        # Fallback: just load persona (static mode)
        agent_file = AGENTS_DIR / f"{agent_name}.md"
        if not agent_file.exists():
            return [
                TextContent(
                    type="text",
                    text=f"❌ Agent not found: {agent_name}\n\nUse agent_list() to see available agents.",
                )
            ]

        try:
            content = agent_file.read_text()
            return [
                TextContent(
                    type="text",
                    text=f"## Loading Agent: {agent_name}\n\n*(Static mode - tools unchanged)*\n\n---\n\n{content}",
                )
            ]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error loading agent: {e}")]

    # ==================== MEMORY ====================
    # Persistent context across sessions

    MEMORY_DIR = Path(__file__).parent.parent.parent.parent / "memory"

    @server.tool()
    async def memory_read(key: str = "") -> list[TextContent]:
        """
        Read from persistent memory.

        Memory stores context that persists across Claude sessions:
        - state/current_work.yaml - Active issues, branches, MRs
        - state/environments.yaml - Stage/prod health status
        - learned/patterns.yaml - Error patterns and solutions
        - learned/runbooks.yaml - Procedures that worked

        Args:
            key: Memory key to read (e.g., "state/current_work", "learned/patterns")
                 Leave empty to list available memory files.

        Returns:
            Memory contents or list of available memory files.
        """
        if not key:
            # List available memory
            lines = ["## Available Memory\n"]
            for subdir in ["state", "learned", "sessions"]:
                d = MEMORY_DIR / subdir
                if d.exists():
                    lines.append(f"### {subdir}/")
                    for f in d.glob("*.yaml"):
                        lines.append(f"- {subdir}/{f.stem}")
            return [TextContent(type="text", text="\n".join(lines))]

        # Handle with or without .yaml extension
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key
        if not memory_file.exists():
            return [
                TextContent(
                    type="text",
                    text=f"❌ Memory not found: {key}\n\nUse memory_read() without args to see available memory.",
                )
            ]

        try:
            content = memory_file.read_text()
            return [TextContent(type="text", text=f"## Memory: {key}\n\n```yaml\n{content}\n```")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error reading memory: {e}")]

    @server.tool()
    async def memory_write(key: str, content: str) -> list[TextContent]:
        """
        Write to persistent memory.

        Updates a memory file with new content. Use this to save:
        - Current work state (what you're working on)
        - Learned patterns (solutions that worked)
        - Session notes (context for next session)

        Args:
            key: Memory key to write (e.g., "state/current_work", "learned/patterns")
            content: YAML content to write

        Returns:
            Confirmation of the write.
        """
        # Handle with or without .yaml extension
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key

        # Ensure parent directory exists
        memory_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Validate YAML
            import yaml

            yaml.safe_load(content)

            # Write to file
            memory_file.write_text(content)

            return [TextContent(type="text", text=f"✅ Memory saved: {key}")]
        except yaml.YAMLError as e:
            return [TextContent(type="text", text=f"❌ Invalid YAML: {e}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error writing memory: {e}")]

    @server.tool()
    async def memory_update(key: str, path: str, value: str) -> list[TextContent]:
        """
        Update a specific field in memory.

        Updates a single field in a YAML memory file without rewriting everything.

        Args:
            key: Memory file (e.g., "state/current_work")
            path: Dot-separated path to the field (e.g., "active_issues", "notes")
            value: New value (as YAML string)

        Returns:
            Confirmation of the update.
        """
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key
        if not memory_file.exists():
            return [TextContent(type="text", text=f"❌ Memory not found: {key}")]

        try:
            import yaml

            # Load existing
            with open(memory_file) as f:
                data = yaml.safe_load(f) or {}

            # Parse the new value
            new_value = yaml.safe_load(value)

            # Navigate to the path and update
            parts = path.split(".")
            target = data
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]
            target[parts[-1]] = new_value

            # Write back
            with open(memory_file, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            return [TextContent(type="text", text=f"✅ Updated {key}: {path} = {value}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error updating memory: {e}")]

    @server.tool()
    async def memory_append(key: str, list_path: str, item: str) -> list[TextContent]:
        """
        Append an item to a list in memory.

        Useful for adding to lists like active_issues, follow_ups, recent_alerts.

        Args:
            key: Memory file (e.g., "state/current_work")
            list_path: Path to the list (e.g., "active_issues", "follow_ups")
            item: Item to append (as YAML string, e.g., '{"key": "AAP-123", "status": "In Progress"}')

        Returns:
            Confirmation of the append.
        """
        if not key.endswith(".yaml"):
            key = f"{key}.yaml"

        memory_file = MEMORY_DIR / key
        if not memory_file.exists():
            return [TextContent(type="text", text=f"❌ Memory not found: {key}")]

        try:
            import yaml

            # Load existing
            with open(memory_file) as f:
                data = yaml.safe_load(f) or {}

            # Parse the new item
            new_item = yaml.safe_load(item)

            # Navigate to the list
            parts = list_path.split(".")
            target = data
            for part in parts[:-1]:
                if part not in target:
                    target[part] = {}
                target = target[part]

            # Ensure it's a list and append
            if parts[-1] not in target:
                target[parts[-1]] = []
            if not isinstance(target[parts[-1]], list):
                return [TextContent(type="text", text=f"❌ {list_path} is not a list")]

            target[parts[-1]].append(new_item)

            # Write back
            with open(memory_file, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            return [TextContent(type="text", text=f"✅ Appended to {key}: {list_path}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error appending to memory: {e}")]

    @server.tool()
    async def memory_session_log(action: str, details: str = "") -> list[TextContent]:
        """
        Log an action to today's session log.

        Creates a running log of what was done during this session.
        Useful for handoff to future sessions.

        Args:
            action: What was done (e.g., "Started work on AAP-12345")
            details: Additional details (optional)

        Returns:
            Confirmation of the log entry.
        """
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        session_file = MEMORY_DIR / "sessions" / f"{today}.yaml"
        session_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            import yaml

            # Load existing or create new
            if session_file.exists():
                with open(session_file) as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {"date": today, "entries": []}

            if "entries" not in data:
                data["entries"] = []

            # Add entry
            entry = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "action": action,
            }
            if details:
                entry["details"] = details

            data["entries"].append(entry)

            # Write back
            with open(session_file, "w") as f:
                yaml.dump(data, f, default_flow_style=False)

            return [TextContent(type="text", text=f"✅ Logged: {action}")]
        except Exception as e:
            return [TextContent(type="text", text=f"❌ Error logging: {e}")]

    # ==================== SESSION BOOTSTRAP ====================

    @server.tool()
    async def session_start(agent: str = "") -> list[TextContent]:
        """
        Initialize a new session with full context.

        This is the FIRST tool to call when starting work. It loads:
        - Current work state (active issues, branches, MRs)
        - Today's session history (if resuming)
        - Optionally loads an agent persona

        Args:
            agent: Optional agent to load ("devops", "developer", "incident", "release")

        Returns:
            Complete session context to get started.
        """
        from datetime import datetime

        import yaml

        lines = ["# 🚀 Session Started\n"]

        # Load current work
        current_work_file = MEMORY_DIR / "state" / "current_work.yaml"
        if current_work_file.exists():
            try:
                with open(current_work_file) as f:
                    work = yaml.safe_load(f) or {}

                active = work.get("active_issues", [])
                mrs = work.get("open_mrs", [])
                followups = work.get("follow_ups", [])

                if active or mrs or followups:
                    lines.append("## 📋 Current Work\n")

                    if active:
                        lines.append("### Active Issues")
                        for issue in active:
                            lines.append(
                                f"- **{issue.get('key', '?')}**: {issue.get('summary', 'No summary')}"
                            )
                            lines.append(
                                f"  Status: {issue.get('status', '?')} | Branch: `{issue.get('branch', '?')}`"
                            )
                        lines.append("")

                    if mrs:
                        lines.append("### Open MRs")
                        for mr in mrs:
                            lines.append(
                                f"- **!{mr.get('id', '?')}**: {mr.get('title', 'No title')}"
                            )
                            lines.append(f"  Pipeline: {mr.get('pipeline_status', '?')}")
                        lines.append("")

                    if followups:
                        lines.append("### Follow-ups")
                        for fu in followups:
                            lines.append(
                                f"- {fu.get('task', '?')} (priority: {fu.get('priority', 'normal')})"
                            )
                        lines.append("")
                else:
                    lines.append("*No active work tracked. Use `memory_append` to track issues.*\n")

            except Exception as e:
                lines.append(f"*Could not load work state: {e}*\n")

        # Load today's session history
        today = datetime.now().strftime("%Y-%m-%d")
        session_file = MEMORY_DIR / "sessions" / f"{today}.yaml"
        if session_file.exists():
            try:
                with open(session_file) as f:
                    session = yaml.safe_load(f) or {}
                entries = session.get("entries", [])
                if entries:
                    lines.append("## 📝 Today's Session History\n")
                    for entry in entries[-5:]:  # Last 5 entries
                        lines.append(f"- [{entry.get('time', '?')}] {entry.get('action', '?')}")
                    lines.append("")
            except Exception:
                pass

        # Load agent if specified
        if agent:
            agent_file = AGENTS_DIR / f"{agent}.md"
            if agent_file.exists():
                lines.append(f"## 🤖 Agent: {agent}\n")
                lines.append("*Loading agent persona...*\n")
                lines.append("---\n")
                lines.append(agent_file.read_text())
            else:
                lines.append(
                    f"*Agent '{agent}' not found. Available: devops, developer, incident, release*\n"
                )
        else:
            lines.append("## 💡 Available Agents\n")
            lines.append("Load one with `agent_load(name)` or `session_start(agent='name')`:\n")
            lines.append("- **devops** - Infrastructure, monitoring, deployments")
            lines.append("- **developer** - Coding, PRs, code review")
            lines.append("- **incident** - Production issues, triage")
            lines.append("- **release** - Shipping, coordination")
            lines.append("")

        # Show available skills
        lines.append("## ⚡ Quick Skills\n")
        lines.append("Run with `skill_run(name, inputs)`:\n")
        lines.append("- **start_work** - Begin Jira issue (creates branch, updates status)")
        lines.append("- **create_mr** - Create MR with proper formatting")
        lines.append("- **investigate_alert** - Systematic alert investigation")
        lines.append("")

        # Log session start
        await memory_session_log("Session started", f"Agent: {agent or 'none'}")

        return [TextContent(type="text", text="\n".join(lines))]

    # ==================== DYNAMIC TOOL EXECUTION ====================
    # Meta-tool pattern: ONE tool that can execute ANY tool from any module

    # Registry of all available tools (loaded on demand)
    _tool_registry: dict = {}
    _tools_loaded = False

    def _load_all_tools():
        """Lazy-load all tool functions into registry."""
        nonlocal _tools_loaded
        if _tools_loaded:
            return

        import importlib.util

        tool_modules = {
            "git": "aa-git",
            "jira": "aa-jira",
            "gitlab": "aa-gitlab",
            "k8s": "aa-k8s",
            "prometheus": "aa-prometheus",
            "alertmanager": "aa-alertmanager",
            "kibana": "aa-kibana",
            "konflux": "aa-konflux",
            "bonfire": "aa-bonfire",
            "quay": "aa-quay",
            "appinterface": "aa-appinterface",
        }

        SERVERS_DIR = Path(__file__).parent.parent.parent.parent

        for module_name, dir_name in tool_modules.items():
            tools_file = SERVERS_DIR / dir_name / "src" / "tools.py"
            if not tools_file.exists():
                continue

            try:
                # Read the file and extract tool functions
                content = tools_file.read_text()
                # Store module info for dynamic execution
                _tool_registry[module_name] = {
                    "path": str(tools_file),
                    "available": True,
                }
            except Exception:
                pass

        _tools_loaded = True

    @server.tool()
    async def tool_list(module: str = "") -> list[TextContent]:
        """
        List all available tools across all modules.

        Use this to discover tools that aren't directly loaded.
        Then use tool_exec() to run them.

        Args:
            module: Filter by module (git, jira, gitlab, k8s, etc.)
                   Leave empty to list all modules.

        Returns:
            List of available tools and their descriptions.
        """
        # Tool counts per module
        tool_counts = {
            "git": [
                "git_status",
                "git_branch_list",
                "git_branch_create",
                "git_checkout",
                "git_log",
                "git_diff",
                "git_add",
                "git_commit",
                "git_push",
                "git_pull",
                "git_stash",
                "git_fetch",
                "git_merge",
                "git_rebase",
                "git_remote",
            ],
            "jira": [
                "jira_view_issue",
                "jira_view_issue_json",
                "jira_search",
                "jira_list_issues",
                "jira_my_issues",
                "jira_list_blocked",
                "jira_lint",
                "jira_set_status",
                "jira_assign",
                "jira_unassign",
                "jira_add_comment",
                "jira_block",
                "jira_unblock",
                "jira_add_to_sprint",
                "jira_remove_sprint",
                "jira_create_issue",
                "jira_clone_issue",
                "jira_add_link",
                "jira_add_flag",
                "jira_remove_flag",
                "jira_open_browser",
            ],
            "gitlab": [
                "gitlab_mr_list",
                "gitlab_mr_view",
                "gitlab_mr_create",
                "gitlab_mr_update",
                "gitlab_mr_approve",
                "gitlab_mr_revoke",
                "gitlab_mr_merge",
                "gitlab_mr_close",
                "gitlab_mr_reopen",
                "gitlab_mr_comment",
                "gitlab_mr_diff",
                "gitlab_mr_rebase",
                "gitlab_mr_checkout",
                "gitlab_mr_approvers",
                "gitlab_ci_list",
                "gitlab_ci_status",
                "gitlab_ci_view",
                "gitlab_ci_run",
                "gitlab_ci_retry",
                "gitlab_ci_cancel",
                "gitlab_ci_trace",
                "gitlab_ci_lint",
                "gitlab_repo_view",
                "gitlab_repo_clone",
                "gitlab_issue_list",
                "gitlab_issue_view",
                "gitlab_issue_create",
                "gitlab_label_list",
                "gitlab_release_list",
                "gitlab_user_info",
            ],
            "k8s": [
                "kubectl_get_pods",
                "kubectl_describe_pod",
                "kubectl_logs",
                "kubectl_delete_pod",
                "kubectl_get_deployments",
                "kubectl_describe_deployment",
                "kubectl_rollout_status",
                "kubectl_rollout_restart",
                "kubectl_scale",
                "kubectl_get_services",
                "kubectl_get_events",
                "kubectl_get",
                "kubectl_exec",
                "kubectl_top_pods",
            ],
            "prometheus": [
                "prometheus_query",
                "prometheus_query_range",
                "prometheus_alerts",
                "prometheus_rules",
                "prometheus_targets",
                "prometheus_labels",
                "prometheus_series",
                "prometheus_namespace_metrics",
                "prometheus_error_rate",
                "prometheus_pod_health",
                "prometheus_grafana_link",
            ],
            "alertmanager": [
                "alertmanager_silences",
                "alertmanager_create_silence",
                "alertmanager_delete_silence",
                "alertmanager_status",
                "alertmanager_alerts",
            ],
            "kibana": [
                "kibana_search_logs",
                "kibana_get_errors",
                "kibana_get_pod_logs",
                "kibana_trace_request",
                "kibana_get_link",
                "kibana_error_link",
                "kibana_status",
                "kibana_index_patterns",
                "kibana_list_dashboards",
            ],
            "konflux": [
                "konflux_list_applications",
                "konflux_get_application",
                "konflux_list_components",
                "konflux_get_component",
                "konflux_list_snapshots",
                "konflux_get_snapshot",
                "konflux_list_integration_tests",
                "konflux_get_test_results",
                "konflux_list_releases",
                "konflux_get_release",
                "konflux_list_release_plans",
                "konflux_list_builds",
                "konflux_get_build_logs",
                "konflux_list_environments",
                "konflux_namespace_summary",
            ],
            "bonfire": [
                "bonfire_version",
                "bonfire_namespace_reserve",
                "bonfire_namespace_list",
                "bonfire_namespace_describe",
                "bonfire_namespace_release",
                "bonfire_namespace_extend",
                "bonfire_namespace_wait",
                "bonfire_apps_list",
                "bonfire_apps_dependencies",
                "bonfire_deploy",
                "bonfire_deploy_with_reserve",
                "bonfire_process",
                "bonfire_deploy_env",
                "bonfire_process_env",
                "bonfire_deploy_iqe_cji",
                "bonfire_pool_list",
                "bonfire_deploy_aa",
            ],
            "quay": [
                "quay_get_repository",
                "quay_list_tags",
                "quay_get_tag",
                "quay_check_image_exists",
                "quay_get_vulnerabilities",
                "quay_get_manifest",
                "quay_check_aa_image",
                "quay_list_aa_tags",
            ],
            "appinterface": [
                "appinterface_validate",
                "appinterface_get_saas",
                "appinterface_diff",
                "appinterface_resources",
                "appinterface_search",
                "appinterface_clusters",
            ],
        }

        if module:
            if module not in tool_counts:
                return [
                    TextContent(
                        type="text",
                        text=f"❌ Unknown module: {module}\n\nAvailable: {', '.join(tool_counts.keys())}",
                    )
                ]

            tools = tool_counts[module]
            lines = [f"## Module: {module}\n", f"**{len(tools)} tools available:**\n"]
            for t in tools:
                lines.append(f"- `{t}`")
            lines.append(f"\n*Use `tool_exec('{tools[0]}', '{{}}')` to run*")
            return [TextContent(type="text", text="\n".join(lines))]

        # List all modules
        lines = ["## Available Tool Modules\n"]
        total = 0
        for mod, tools in tool_counts.items():
            lines.append(f"- **{mod}**: {len(tools)} tools")
            total += len(tools)
        lines.append(f"\n**Total: {total} tools**")
        lines.append("\nUse `tool_list(module='git')` to see tools in a module")
        lines.append("\n**💡 TIP:** After loading an agent, call tools DIRECTLY by name:")
        lines.append("   `bonfire_namespace_list(mine_only=True)`  ← Cursor shows actual name")
        lines.append("   NOT: `tool_exec('bonfire_namespace_list', ...)`  ← Shows as 'tool_exec'")
        lines.append("\nUse `tool_exec()` only for tools from non-loaded agents.")

        return [TextContent(type="text", text="\n".join(lines))]

    @server.tool()
    async def tool_exec(tool_name: str, args: str = "{}") -> list[TextContent]:
        """
        Execute ANY tool from ANY module dynamically.

        This is a meta-tool that can run tools not directly loaded.
        First use tool_list() to see available tools.

        Args:
            tool_name: Full tool name (e.g., "gitlab_mr_list", "kibana_search_logs")
            args: JSON string of arguments (e.g., '{"project": "backend", "state": "opened"}')

        Returns:
            Tool execution result.

        Example:
            tool_exec("gitlab_mr_list", '{"project": "your-backend"}')
        """
        # Determine which module the tool belongs to
        module_prefixes = {
            "git_": "git",
            "jira_": "jira",
            "gitlab_": "gitlab",
            "kubectl_": "k8s",
            "k8s_": "k8s",
            "prometheus_": "prometheus",
            "alertmanager_": "alertmanager",
            "kibana_": "kibana",
            "konflux_": "konflux",
            "tkn_": "konflux",
            "bonfire_": "bonfire",
            "quay_": "quay",
            "appinterface_": "appinterface",
            # Workflow tools
            "workflow_": "workflow",
            "lint_": "workflow",
            "test_": "workflow",
            "security_": "workflow",
            "precommit_": "workflow",
            "memory_": "workflow",
            "agent_": "workflow",
            "skill_": "workflow",
            "session_": "workflow",
            "tool_": "workflow",
        }

        module = None
        for prefix, mod in module_prefixes.items():
            if tool_name.startswith(prefix):
                module = mod
                break

        if not module:
            # Could be a workflow tool without prefix
            return [
                TextContent(
                    type="text",
                    text=f"❌ Unknown tool: {tool_name}\n\n"
                    f"Use tool_list() to see available tools.",
                )
            ]

        # Parse arguments
        try:
            tool_args = json.loads(args) if args else {}
        except json.JSONDecodeError as e:
            return [TextContent(type="text", text=f"❌ Invalid JSON args: {e}")]

        # Load and execute the tool module
        # Path: tools.py -> src -> aa-workflow -> mcp-servers
        SERVERS_DIR = Path(__file__).parent.parent.parent
        tools_file = SERVERS_DIR / f"aa-{module}" / "src" / "tools.py"

        if not tools_file.exists():
            return [TextContent(type="text", text=f"❌ Module not found: {module}")]

        try:
            import importlib.util

            # Create a temporary server to register tools
            temp_server = FastMCP(f"temp-{module}")

            # Load the module
            spec = importlib.util.spec_from_file_location(f"aa_{module}_tools_exec", tools_file)
            if spec is None or spec.loader is None:
                return [TextContent(type="text", text=f"❌ Could not load module: {module}")]

            loaded_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded_module)

            # Register tools with temp server
            if hasattr(loaded_module, "register_tools"):
                loaded_module.register_tools(temp_server)

            # Execute the tool
            result = await temp_server.call_tool(tool_name, tool_args)

            # Extract text from result
            if isinstance(result, tuple):
                result = result[0]
            if isinstance(result, list) and len(result) > 0:
                if hasattr(result[0], "text"):
                    return [TextContent(type="text", text=result[0].text)]
                return [TextContent(type="text", text=str(result[0]))]

            return [TextContent(type="text", text=str(result))]

        except Exception as e:
            error_msg = str(e)
            lines = [f"❌ Error executing {tool_name}: {error_msg}"]

            # Auto-create GitHub issue for all tool failures
            try:
                issue_result = await create_github_issue(
                    tool=tool_name, error=error_msg, context=f"Args: {args}"
                )

                if issue_result["success"]:
                    lines.append("")
                    lines.append(f"🐛 **Issue created:** {issue_result['issue_url']}")
                elif issue_result["issue_url"]:
                    lines.append("")
                    lines.append("💡 **Report this error:**")
                    lines.append(f"📝 [Create GitHub Issue]({issue_result['issue_url']})")
                    if "dedup" in issue_result.get("message", ""):
                        lines.append("*(Similar issue recently reported)*")
            except Exception as issue_err:
                logger.debug(f"Failed to create GitHub issue: {issue_err}")

            return [TextContent(type="text", text="\n".join(lines))]

    # ==================== PROMPTS ====================
    # Pre-defined conversation templates

    @server.prompt()
    async def session_init() -> str:
        """
        Initialize a new work session.

        Use this prompt to start a productive session with full context.
        """
        return """You are an AI assistant helping with software development.

Start by calling session_start() to load your current work context.

If you know the type of work:
- DevOps tasks: session_start(agent="devops")
- Development: session_start(agent="developer")
- Incidents: session_start(agent="incident")
- Releases: session_start(agent="release")

After loading context, ask what the user wants to work on today."""

    @server.prompt()
    async def debug_guide() -> str:
        """
        Guide for debugging production issues.

        Provides a systematic approach to production debugging.
        """
        return """# Production Debugging Guide

## 1. Gather Context
- Which namespace? (tower-analytics-prod or tower-analytics-prod-billing)
- Any specific alert that fired?
- When did the issue start?

## 2. Check Pod Health
```
kubectl_get_pods(namespace="tower-analytics-prod", environment="prod")
```
Look for: CrashLoopBackOff, OOMKilled, Pending, high restarts

## 3. Check Events
```
kubectl_get_events(namespace="tower-analytics-prod", environment="prod")
```
Look for: Warning, Error, FailedScheduling

## 4. Check Logs
```
kubectl_logs(pod="<pod-name>", namespace="tower-analytics-prod", environment="prod", tail=100)
```
Grep for: error, exception, fatal, timeout

## 5. Check Alerts
```
prometheus_alerts(environment="prod")
```

## 6. Check Recent Deployments
Was there a recent deployment? Check app-interface for recent changes.

## 7. Match Against Known Patterns
Use memory_read("learned/patterns") to check for known issues.

## 8. Document Findings
Use memory_session_log() to record what you find."""

    @server.prompt()
    async def review_guide() -> str:
        """
        Guide for reviewing merge requests.

        Provides a structured approach to code review.
        """
        return """# Code Review Guide

## 1. Get MR Context
```
gitlab_mr_view(project="<project>", mr_id=<id>)
```

## 2. Check Linked Jira
```
jira_view_issue("<ISSUE-KEY>")
```
- Does the MR address the issue requirements?
- Are acceptance criteria met?

## 3. Review Changes
```
gitlab_mr_diff(project="<project>", mr_id=<id>)
```

### What to Look For:
- **Security**: SQL injection, secrets in code, unsafe deserialization
- **Performance**: N+1 queries, missing indexes, large memory allocations
- **Correctness**: Edge cases, error handling, race conditions
- **Style**: Consistent with codebase, clear naming, appropriate comments

## 4. Check Pipeline
```
gitlab_ci_status(project="<project>")
```
- All tests passing?
- No linter failures?

## 5. Provide Feedback
Be constructive, specific, and kind. Suggest alternatives, don't just criticize."""

    # ==================== RESOURCES ====================
    # Data sources the AI can read

    @server.resource("memory://state/current_work")
    async def resource_current_work() -> str:
        """Current work state - active issues, branches, MRs."""
        import yaml

        work_file = MEMORY_DIR / "state" / "current_work.yaml"
        if work_file.exists():
            return work_file.read_text()
        return "# No current work tracked\nactive_issues: []\nopen_mrs: []\nfollow_ups: []"

    @server.resource("memory://learned/patterns")
    async def resource_patterns() -> str:
        """Known error patterns and solutions."""
        patterns_file = MEMORY_DIR / "learned" / "patterns.yaml"
        if patterns_file.exists():
            return patterns_file.read_text()
        return "# No patterns recorded yet\npatterns: []"

    @server.resource("config://agents")
    async def resource_agents() -> str:
        """Available agent configurations."""
        import yaml

        agents = []
        if AGENTS_DIR.exists():
            for f in AGENTS_DIR.glob("*.yaml"):
                try:
                    with open(f) as fp:
                        data = yaml.safe_load(fp)
                    agents.append(
                        {
                            "name": data.get("name", f.stem),
                            "description": data.get("description", ""),
                            "tools": data.get("tools", []),
                            "skills": data.get("skills", []),
                        }
                    )
                except Exception:
                    pass
        return yaml.dump({"agents": agents}, default_flow_style=False)

    @server.resource("config://skills")
    async def resource_skills() -> str:
        """Available skill definitions."""
        import yaml

        skills = []
        if SKILLS_DIR.exists():
            for f in SKILLS_DIR.glob("*.yaml"):
                try:
                    with open(f) as fp:
                        data = yaml.safe_load(fp)
                    skills.append(
                        {
                            "name": data.get("name", f.stem),
                            "description": data.get("description", ""),
                            "inputs": [i.get("name") for i in data.get("inputs", [])],
                        }
                    )
                except Exception:
                    pass
        return yaml.dump({"skills": skills}, default_flow_style=False)

    @server.resource("config://repositories")
    async def resource_repositories() -> str:
        """Configured repositories from config.json."""
        import yaml

        config = load_config()
        repos = config.get("repositories", {})
        return yaml.dump({"repositories": repos}, default_flow_style=False)

    # ==================== ENTRY POINT ====================

    # Count registered tools
    tool_count = (
        16 + 2 + 2 + 5 + 1 + 2 + 2
    )  # Original + skills + agents + memory + bootstrap + dynamic + infrastructure (vpn, kube)
    return tool_count
