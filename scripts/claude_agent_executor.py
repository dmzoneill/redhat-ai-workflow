"""Tool executor for Claude Agent."""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional, cast

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from scripts.common.context_resolver import ContextResolver

    RESOLVER_AVAILABLE = True
except ImportError:
    RESOLVER_AVAILABLE = False
    ContextResolver = None

try:
    from scripts.skill_hooks import SkillHooks

    HOOKS_AVAILABLE = True
except ImportError:
    HOOKS_AVAILABLE = False
    SkillHooks = None

try:
    PROJECT_ROOT = Path(__file__).parent.parent
    sys.path.insert(0, str(PROJECT_ROOT))
    from server.debuggable import _check_known_issues_sync, _format_known_issues

    KNOWN_ISSUES_AVAILABLE = True
except ImportError:
    KNOWN_ISSUES_AVAILABLE = False

    def _check_known_issues_sync(tool_name="", error_text=""):
        return []

    def _format_known_issues(matches):
        return ""


try:
    sys.path.insert(
        0, str(Path(__file__).parent.parent / "tool_modules" / "aa_workflow" / "src")
    )
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import yaml as skill_yaml
    from skill_engine import SkillExecutor, SkillExecutorConfig

    SKILL_EXECUTOR_AVAILABLE = True
    SKILLS_DIR = Path(__file__).parent.parent / "skills"
except ImportError:
    SKILL_EXECUTOR_AVAILABLE = False
    skill_yaml = None
    SkillExecutor = None
    SkillExecutorConfig = None
    SKILLS_DIR = None

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tools by calling the appropriate CLI commands or MCP tools.

    Uses ContextResolver to determine repo paths from URLs and issue keys.
    Uses SkillHooks to emit event notifications (DMs to PR authors, team updates).
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root: Path = project_root
        self.rh_issue: str = os.getenv("RH_ISSUE_CLI", "rh-issue")

        # Initialize context resolver for repo path lookups
        self.resolver: Optional[Any] = None  # Type is ContextResolver when available
        if RESOLVER_AVAILABLE:
            try:
                self.resolver = ContextResolver()
                logger.info(
                    f"Context resolver loaded with {len(self.resolver.repos)} repositories"
                )
            except Exception as e:
                logger.warning(f"Failed to load context resolver: {e}")

        # Initialize skill hooks for event notifications
        self.hooks: Optional[Any] = None  # Type is SkillHooks when available
        if HOOKS_AVAILABLE:
            try:
                self.hooks = SkillHooks.from_config()
                logger.info("Skill hooks initialized for event notifications")
            except Exception as e:
                logger.warning(f"Failed to load skill hooks: {e}")

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool and return the result."""
        logger.info(f"Executing tool: {tool_name} with {arguments}")

        try:
            # Route to appropriate handler
            if tool_name.startswith("jira_"):
                return await self._execute_jira(tool_name, arguments)
            elif tool_name.startswith("gitlab_"):
                return await self._execute_gitlab(tool_name, arguments)
            elif tool_name.startswith("git_"):
                return await self._execute_git(tool_name, arguments)
            elif tool_name.startswith("k8s_"):
                return await self._execute_k8s(tool_name, arguments)
            elif tool_name.startswith("bonfire_"):
                return await self._execute_bonfire(tool_name, arguments)
            elif tool_name.startswith("quay_"):
                return await self._execute_quay(tool_name, arguments)
            elif tool_name.startswith("memory_"):
                return await self._execute_memory(tool_name, arguments)
            elif tool_name.startswith("slack_"):
                return await self._execute_slack(tool_name, arguments)
            elif tool_name == "skill_run":
                return await self._execute_skill(arguments)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Tool execution error for {tool_name}: {error_msg}", exc_info=True
            )

            # Check for known issues from memory
            matches = _check_known_issues_sync(
                tool_name=tool_name, error_text=error_msg
            )
            known_text = _format_known_issues(matches)

            if known_text:
                return f"❌ Error with {tool_name}: {error_msg}\n{known_text}"
            else:
                return (
                    f"❌ The {tool_name} tool failed: {error_msg}\n\n"
                    f"💡 **Auto-fix:** `debug_tool('{tool_name}')`\n"
                    f"📚 **After fixing:** `learn_tool_fix('{tool_name}', '<pattern>', '<cause>', '<fix>')`"
                )

    async def _run_command(
        self,
        cmd: list[str],
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
    ) -> str:
        """Run a shell command and return output."""
        try:
            run_env = os.environ.copy()
            if env:
                run_env.update(env)

            # CRITICAL: Clear virtualenv variables to allow pipenv commands (like rh-issue) to work
            # Without this, pipenv detects our venv and uses it instead of jira-creator's venv
            for var in ["VIRTUAL_ENV", "PIPENV_ACTIVE", "PYTHONHOME"]:
                run_env.pop(var, None)
            run_env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=cwd or str(self.project_root),
                env=run_env,
            )
            output = result.stdout
            if result.returncode != 0 and result.stderr:
                output += f"\nError: {result.stderr}"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "The command timed out. Please try a simpler request."
        except Exception as e:
            logger.error(f"Command execution failed: {e}", exc_info=True)
            return "Unable to execute that command right now."

    async def _execute_jira(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Jira tools via rh-issue CLI."""
        if tool_name == "jira_view":
            key = args.get("issue_key", "")
            return await self._run_command([self.rh_issue, "view", key])
        elif tool_name == "jira_search":
            jql = args.get("jql", "")
            max_results = args.get("max_results", 10)
            return await self._run_command(
                [self.rh_issue, "search", jql, "--max", str(max_results)]
            )
        elif tool_name == "jira_comment":
            key = args.get("issue_key", "")
            comment = args.get("comment", "")
            return await self._run_command([self.rh_issue, "comment", key, comment])
        return f"Unknown Jira tool: {tool_name}"

    def _resolve_gitlab_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """Resolve GitLab project, MR ID, and execution context from arguments."""
        mr_input = args.get("mr_id", "") or args.get("url", "")
        project = args.get("repo", args.get("project", ""))
        mr_id = ""
        local_repo_path = None

        # Use context resolver if available
        if self.resolver and mr_input:
            ctx = self.resolver.from_message(mr_input)
            if ctx.gitlab_project:
                project = ctx.gitlab_project
            if ctx.mr_id:
                mr_id = ctx.mr_id
            if ctx.repo_path:
                local_repo_path = ctx.repo_path
                logger.info(f"Resolved GitLab project to local path: {local_repo_path}")

        # Fallback: manual URL parsing
        if not project or not mr_id:
            url_match = re.match(
                r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", mr_input
            )
            if url_match:
                project = project or url_match.group(1)
                mr_id = mr_id or url_match.group(2)
            else:
                mr_id = mr_id or mr_input.lstrip("!").strip()

        # Try to resolve local path from project if we don't have it yet
        if not local_repo_path and project and self.resolver:
            local_repo_path = self.resolver.get_repo_path(project)

        # Determine how to run glab
        if local_repo_path and Path(local_repo_path).exists():
            run_cwd = local_repo_path
            use_repo_flag = False
            logger.info(f"Running glab from local repo: {run_cwd}")
        else:
            run_cwd = None
            use_repo_flag = True
            logger.info(f"Running glab with --repo flag: {project}")

        return {
            "project": project,
            "mr_id": mr_id,
            "run_cwd": run_cwd,
            "use_repo_flag": use_repo_flag,
        }

    async def _gitlab_mr_view(
        self, mr_id: str, project: str, run_cwd: str | None, use_repo_flag: bool
    ) -> str:
        """Execute gitlab_mr_view tool."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_view"
        cmd = ["glab", "mr", "view", mr_id, "--web=false"]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        return await self._run_command(cmd, cwd=run_cwd)

    async def _gitlab_mr_list(
        self,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_list tool."""
        cmd = ["glab", "mr", "list"]
        if args.get("author"):
            cmd.extend(["--author", args["author"]])
        cmd.extend(["--state", args.get("state", "opened")])
        if use_repo_flag:
            cmd.extend(["--repo", project])
        return await self._run_command(cmd, cwd=run_cwd)

    async def _gitlab_pipeline_status(
        self, project: str, run_cwd: str | None, use_repo_flag: bool
    ) -> str:
        """Execute gitlab_pipeline_status tool."""
        cmd = ["glab", "ci", "status"]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        return await self._run_command(cmd, cwd=run_cwd)

    async def _gitlab_mr_approve(
        self,
        mr_id: str,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_approve tool with event emission."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_approve"
        cmd = ["glab", "mr", "approve", mr_id]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        result = await self._run_command(cmd, cwd=run_cwd)

        # Emit approval event
        if self.hooks and "error" not in result.lower():
            await self.hooks.emit(
                "review_approved",
                {
                    "mr_id": mr_id,
                    "author": args.get("author", ""),
                    "project": project,
                    "target_branch": args.get("target_branch", "main"),
                },
            )
        return result

    async def _gitlab_mr_comment(
        self,
        mr_id: str,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_comment tool with event emission."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_comment"
        comment = args.get("comment", args.get("body", ""))
        if not comment:
            return "Comment text is required"
        cmd = ["glab", "mr", "note", mr_id, "-m", comment]
        if use_repo_flag:
            cmd.extend(["--repo", project])
        result = await self._run_command(cmd, cwd=run_cwd)

        # Emit comment event
        if self.hooks and "error" not in result.lower():
            await self.hooks.emit(
                "review_comment",
                {"mr_id": mr_id, "author": args.get("author", ""), "project": project},
            )
        return result

    async def _gitlab_mr_merge(
        self,
        mr_id: str,
        project: str,
        run_cwd: str | None,
        use_repo_flag: bool,
        args: dict[str, Any],
    ) -> str:
        """Execute gitlab_mr_merge tool with event emission."""
        if not mr_id:
            return "MR ID is required for gitlab_mr_merge"
        cmd = ["glab", "mr", "merge", mr_id, "--yes"]
        if args.get("squash"):
            cmd.append("--squash")
        if use_repo_flag:
            cmd.extend(["--repo", project])
        result = await self._run_command(cmd, cwd=run_cwd)

        # Emit merge event
        if self.hooks and "error" not in result.lower():
            await self.hooks.emit(
                "mr_merged",
                {
                    "mr_id": mr_id,
                    "author": args.get("author", ""),
                    "project": project,
                    "target_branch": args.get("target_branch", "main"),
                },
            )
        return result

    async def _execute_gitlab(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute GitLab tools.

        Uses ContextResolver to parse URLs and resolve project paths.
        """
        ctx = self._resolve_gitlab_context(args)
        project = ctx["project"]
        mr_id = ctx["mr_id"]
        run_cwd = ctx["run_cwd"]
        use_repo_flag = ctx["use_repo_flag"]

        if not project:
            return "Project/repo is required. Provide a full GitLab URL or specify the project."

        if tool_name == "gitlab_mr_view":
            return await self._gitlab_mr_view(mr_id, project, run_cwd, use_repo_flag)
        elif tool_name == "gitlab_mr_list":
            return await self._gitlab_mr_list(project, run_cwd, use_repo_flag, args)
        elif tool_name == "gitlab_pipeline_status":
            return await self._gitlab_pipeline_status(project, run_cwd, use_repo_flag)
        elif tool_name == "gitlab_mr_approve":
            return await self._gitlab_mr_approve(
                mr_id, project, run_cwd, use_repo_flag, args
            )
        elif tool_name == "gitlab_mr_comment":
            return await self._gitlab_mr_comment(
                mr_id, project, run_cwd, use_repo_flag, args
            )
        elif tool_name == "gitlab_mr_merge":
            return await self._gitlab_mr_merge(
                mr_id, project, run_cwd, use_repo_flag, args
            )

        return f"Unknown GitLab tool: {tool_name}"

    async def _execute_git(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute Git tools.

        Uses ContextResolver to resolve repo paths from issue keys or repo names.
        """
        repo_path = args.get("repo_path", "")

        # Try to resolve repo path from context if not provided
        if not repo_path and self.resolver:
            # Check for issue key in args that might hint at repo
            issue_key = args.get("issue_key", "")
            if issue_key:
                ctx = self.resolver.from_issue_key(issue_key)
                if ctx.repo_path:
                    repo_path = ctx.repo_path
                    logger.info(f"Resolved git repo from issue key: {repo_path}")

            # Check for repo name
            repo_name = args.get("repo_name", "")
            if repo_name and not repo_path:
                ctx = self.resolver.from_repo_name(repo_name)
                if ctx.repo_path:
                    repo_path = ctx.repo_path

        # Default to project root if still no path
        if not repo_path:
            repo_path = str(self.project_root)

        # Validate path exists
        if not Path(repo_path).exists():
            return f"Repository path not found: {repo_path}"

        if tool_name == "git_status":
            return await self._run_command(["git", "status", "-sb"], cwd=repo_path)
        elif tool_name == "git_log":
            count = args.get("count", 10)
            return await self._run_command(
                ["git", "log", f"-{count}", "--oneline"], cwd=repo_path
            )
        return f"Unknown Git tool: {tool_name}"

    def _get_kubeconfig(self, environment: str) -> str:
        """Get kubeconfig path for environment."""
        env_map = {
            "stage": "config.s",
            "s": "config.s",
            "production": "config.p",
            "prod": "config.p",
            "p": "config.p",
            "ephemeral": "config.e",
            "e": "config.e",
            "appsre-pipelines": "config.ap",
            "ap": "config.ap",
        }
        config_name = env_map.get(environment.lower(), f"config.{environment}")
        return str(Path.home() / ".kube" / config_name)

    async def _execute_k8s(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Kubernetes tools via kubectl."""
        namespace = args.get("namespace", "")
        environment = args.get("environment", "stage")

        # Detect ephemeral namespace
        if namespace.startswith("ephemeral-") or namespace.startswith(
            "tower-analytics-pr-"
        ):
            environment = "ephemeral"

        kubeconfig = self._get_kubeconfig(environment)
        env = {"KUBECONFIG": kubeconfig}

        if tool_name == "k8s_get_pods":
            return await self._run_command(
                ["kubectl", "get", "pods", "-n", namespace], env=env
            )
        elif tool_name == "k8s_get_events":
            return await self._run_command(
                [
                    "kubectl",
                    "get",
                    "events",
                    "-n",
                    namespace,
                    "--sort-by=.lastTimestamp",
                ],
                env=env,
            )
        elif tool_name == "k8s_logs":
            pod = args.get("pod", "")
            tail = args.get("tail", 100)
            return await self._run_command(
                ["kubectl", "logs", "-n", namespace, pod, f"--tail={tail}"], env=env
            )
        return f"Unknown K8s tool: {tool_name}"

    def _get_bonfire_env(self) -> dict[str, str]:
        """Get environment for bonfire commands (ephemeral cluster)."""
        env = os.environ.copy()
        kubeconfig = Path.home() / ".kube" / "config.e"
        env["KUBECONFIG"] = str(kubeconfig)
        return env

    async def _execute_bonfire(self, tool_name: str, args: dict[str, Any]) -> str:
        """
        Execute bonfire tools for ephemeral namespace management.

        ALWAYS uses KUBECONFIG=~/.kube/config.e for ephemeral cluster.
        Uses the exact ITS deploy pattern for AA deployments.
        """
        env = self._get_bonfire_env()

        if tool_name == "bonfire_namespace_reserve":
            duration = args.get("duration", "2h")
            cmd = [
                "bonfire",
                "namespace",
                "reserve",
                "--duration",
                duration,
                "--pool",
                "default",
                "--timeout",
                "600",
                "--force",
            ]
            return await self._run_command(cmd, env=env)

        elif tool_name == "bonfire_namespace_list":
            mine_only = args.get("mine_only", True)
            cmd = ["bonfire", "namespace", "list"]
            if mine_only:
                cmd.append("--mine")
            return await self._run_command(cmd, env=env)

        elif tool_name == "bonfire_namespace_release":
            namespace = args.get("namespace", "")
            if not namespace:
                return "Error: namespace is required"

            # Safety: verify ownership first
            check_cmd = ["bonfire", "namespace", "list", "--mine"]
            check_result = await self._run_command(check_cmd, env=env)

            if namespace not in check_result:
                return f"Cannot release namespace '{namespace}' - not in your namespaces:\n{check_result}"

            cmd = ["bonfire", "namespace", "release", namespace]
            return await self._run_command(cmd, env=env)

        elif tool_name == "bonfire_deploy_aa":
            namespace = args.get("namespace", "")
            template_ref = args.get("template_ref", "")
            image_tag = args.get("image_tag", "")
            billing = args.get("billing", False)

            # Validate required args
            if not all([namespace, template_ref, image_tag]):
                return "Error: namespace, template_ref, and image_tag are all required"

            # Validate template_ref is 40 chars
            if len(template_ref) != 40:
                return f"Error: template_ref must be 40-char git SHA, got {len(template_ref)} chars"

            # Strip sha256: prefix if present
            digest = image_tag
            if digest.startswith("sha256:"):
                digest = digest[7:]

            # Validate image_tag is 64 chars
            if len(digest) != 64:
                return (
                    f"Error: image_tag must be 64-char sha256 digest, got {len(digest)} chars. "
                    "Use quay_get_tag to get the digest."
                )

            # Select component and image
            component = (
                "tower-analytics-billing-clowdapp"
                if billing
                else "tower-analytics-clowdapp"
            )
            image_base = "quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"
            repository = "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"

            # HARD STOP: Check if image exists in Quay before deploying
            logger.info(f"Checking if image exists: {image_base}:{template_ref}")
            image_ref = (
                f"docker://quay.io/redhat-user-workloads/{repository}:{template_ref}"
            )
            check_cmd = ["skopeo", "inspect", "--raw", image_ref]
            check_result = await self._run_command(check_cmd)

            if (
                "manifest unknown" in check_result.lower()
                or "error" in check_result.lower()
            ):
                return f"""❌ **STOP: Image not found in Quay**

The image for commit `{template_ref[:12]}` does not exist in redhat-user-workloads.

**Image checked:** `{image_base}:{template_ref}`

**Possible causes:**
1. Konflux hasn't built the image yet (check pipeline status)
2. The commit SHA is incorrect
3. The build failed

**What to do:**
1. Check Konflux build status for this commit
2. Wait for the build to complete
3. Retry once the image is available

**DO NOT** proceed with deployment - it will fail with ImagePullBackOff."""

            # Verify we got a valid manifest (contains schemaVersion or mediaType)
            if "schemaVersion" not in check_result and "mediaType" not in check_result:
                return f"""⚠️ **Image check inconclusive**

Got unexpected response when checking image:
```
{check_result[:500]}
```

Please verify the image exists before proceeding."""

            logger.info(f"Image verified: {image_base}:{template_ref}")

            # Build exact ITS command
            cmd = [
                "bonfire",
                "deploy",
                "--source=appsre",
                "--ref-env",
                "insights-production",
                "--namespace",
                namespace,
                "--timeout",
                "900",
                "--optional-deps-method",
                "hybrid",
                "--frontends",
                "false",
                "--component",
                component,
                "--no-remove-resources",
                "all",
                "--set-template-ref",
                f"{component}={template_ref}",
                "--set-parameter",
                f"{component}/IMAGE={image_base}@sha256",
                "--set-parameter",
                f"{component}/IMAGE_TAG={digest}",
                "tower-analytics",
            ]

            logger.info(
                f"Bonfire deploy command: KUBECONFIG={env['KUBECONFIG']} {' '.join(cmd)}"
            )
            return await self._run_command(cmd, env=env)

        return f"Unknown bonfire tool: {tool_name}"

    async def _execute_quay(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Quay tools to check images."""
        if tool_name == "quay_get_tag":
            repository = args.get("repository", "")
            tag = args.get("tag", "")

            if not repository or not tag:
                return "Error: repository and tag are required"

            # Use skopeo to inspect the image
            image_ref = f"docker://quay.io/redhat-user-workloads/{repository}:{tag}"
            cmd = ["skopeo", "inspect", image_ref]

            result = await self._run_command(cmd)

            if "manifest unknown" in result.lower() or "error" in result.lower():
                return (
                    f"Image not found: {repository}:{tag}\n\n"
                    "The image may not be built yet. Check Konflux build status."
                )

            # Extract digest from result
            try:
                digest_match = re.search(r'"Digest":\s*"sha256:([a-f0-9]{64})"', result)
                if digest_match:
                    digest = digest_match.group(1)
                    return (
                        f"Image found!\n\n**Tag:** {tag}\n**Manifest Digest:** sha256:{digest}\n\n"
                        "Use the 64-char digest (without 'sha256:' prefix) as image_tag for bonfire_deploy_aa."
                    )
            except Exception as e:
                logger.debug(f"Suppressed error in _execute_quay: {e}")

            return f"Image exists but could not parse digest:\n{result[:500]}"

        return f"Unknown Quay tool: {tool_name}"

    def _execute_memory_read(self, key: str, read_memory) -> str:
        """Execute memory_read tool."""
        if not key:
            # List available memory files
            memory_dir = Path.home() / ".config/aa_workflow/memory"
            if not memory_dir.exists():
                return "No memory directory found"
            files = []
            for f in memory_dir.rglob("*.yaml"):
                rel_path = f.relative_to(memory_dir)
                files.append(str(rel_path).replace(".yaml", ""))
            return "Available memory files:\n" + "\n".join(
                f"- {f}" for f in sorted(files)
            )

        data = read_memory(key)
        if not data:
            return f"Memory file '{key}' is empty or not found"

        import yaml

        return f"## Memory: {key}\n```yaml\n{yaml.safe_dump(data, default_flow_style=False)}\n```"

    def _execute_memory_append(
        self, key: str, list_path: str, item_str: Any, append_to_list
    ) -> str:
        """Execute memory_append tool."""
        if not key or not list_path:
            return "Error: key and list_path are required"

        # Parse item
        try:
            import yaml

            item = yaml.safe_load(item_str) if isinstance(item_str, str) else item_str
        except Exception as e:
            logger.debug(f"Suppressed error in _execute_memory_append: {e}")
            item = {"value": item_str}

        append_to_list(key, list_path, item)
        return f"Appended to {key}.{list_path}"

    def _execute_memory_session_log(self, action: str, details: str) -> str:
        """Execute memory_session_log tool."""
        if not action:
            return "Error: action is required"

        # Use session log from memory tools
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            from scripts.common.config_loader import get_timezone
            from scripts.common.memory import read_memory as read_mem
            from scripts.common.memory import write_memory

            tz = ZoneInfo(get_timezone())
            today = datetime.now(tz).strftime("%Y-%m-%d")
            log_key = f"sessions/{today}"

            # Read existing log
            log_data = read_mem(log_key)
            if not log_data:
                log_data = {"date": today, "entries": []}

            # Add entry
            entry = {
                "time": datetime.now(tz).strftime("%H:%M"),
                "action": action,
            }
            if details:
                entry["details"] = details

            log_data.setdefault("entries", []).append(entry)
            write_memory(log_key, log_data)

            return f"Logged: {action}"
        except Exception as e:
            return f"Failed to log: {e}"

    async def _execute_memory(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute memory tools using scripts.common.memory helpers."""
        try:
            # Import memory helpers
            from scripts.common.memory import append_to_list, read_memory
        except ImportError:
            return "Memory tools not available (scripts.common.memory not found)"

        if tool_name == "memory_read":
            return self._execute_memory_read(args.get("key", ""), read_memory)
        elif tool_name == "memory_append":
            return self._execute_memory_append(
                args.get("key", ""),
                args.get("list_path", ""),
                args.get("item", "{}"),
                append_to_list,
            )
        elif tool_name == "memory_session_log":
            return self._execute_memory_session_log(
                args.get("action", ""), args.get("details", "")
            )

        return f"Unknown memory tool: {tool_name}"

    async def _execute_slack(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute Slack tools via D-Bus or direct API."""
        if tool_name == "slack_send_message":
            channel_id = args.get("channel_id", "")
            text = args.get("text", "")
            thread_ts = args.get("thread_ts", "")

            if not channel_id or not text:
                return "Error: channel_id and text are required"

            try:
                if str(self.project_root) not in sys.path:
                    sys.path.insert(0, str(self.project_root))

                from services.slack.dbus import SlackAgentClient

                client = SlackAgentClient()
                if await client.connect():
                    result = await client.send_message(
                        channel_id, text, thread_ts or ""
                    )
                    await client.disconnect()
                    if result.get("success"):
                        return f"✅ Message sent to {channel_id}" + (
                            f" in thread {thread_ts}" if thread_ts else ""
                        )
                    else:
                        return f"❌ Failed to send message: {result.get('error', 'unknown error')}"
                else:
                    return "❌ D-Bus not connected - is slack-daemon running?"

            except Exception as e:
                logger.error(f"Slack send failed: {e}")
                return f"❌ Error sending to Slack: {e}"

        return f"Unknown Slack tool: {tool_name}"

    async def _execute_skill(self, args: dict[str, Any]) -> str:
        """
        Execute a workflow skill from YAML using the full SkillExecutor.

        This now uses the actual skill engine from aa_workflow MCP server,
        providing full skill execution with all steps, conditions, and tools.
        """
        skill_name = args.get("skill_name", "")
        inputs = args.get("inputs", {})

        # Ensure inputs is a dict (might be passed as JSON string)
        if isinstance(inputs, str):
            try:
                inputs = json.loads(inputs)
            except json.JSONDecodeError:
                inputs = {}

        # ALWAYS default to slack_format=True when called from the Slack agent
        if "slack_format" not in inputs:
            inputs["slack_format"] = True

        # Check if skill executor is available
        if not SKILL_EXECUTOR_AVAILABLE:
            logger.warning("Skill executor not available, using inline fallback")
            # Fall back to inline executor for test_mr_ephemeral
            if skill_name == "test_mr_ephemeral":
                return await self._skill_test_mr_ephemeral(inputs)
            return f"Skill executor not available. Cannot run: {skill_name}"

        # Check if skill file exists
        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            # List available skills
            available = (
                [f.stem for f in SKILLS_DIR.glob("*.yaml")]
                if SKILLS_DIR.exists()
                else []
            )
            return f"❌ Skill not found: {skill_name}\n\nAvailable: {', '.join(sorted(available)) or 'none'}"

        # Load and execute the skill
        try:
            with open(skill_file, encoding="utf-8") as f:
                skill = skill_yaml.safe_load(f)

            # Create executor and run
            agent_config = SkillExecutorConfig(
                debug=True,  # Enable debug for visibility
                source="slack",  # Claude agent is typically invoked from Slack
            )
            executor = SkillExecutor(
                skill=skill,
                inputs=inputs,
                config=agent_config,
                server=None,  # No MCP server needed - tools loaded dynamically
            )

            # Execute and return result
            result = await executor.execute()
            return cast(str, result)

        except Exception as e:
            logger.error(f"Skill execution error for {skill_name}: {e}", exc_info=True)
            # Fall back to inline executor for test_mr_ephemeral if skill engine fails
            if skill_name == "test_mr_ephemeral":
                logger.info("Falling back to inline executor for test_mr_ephemeral")
                return await self._skill_test_mr_ephemeral(inputs)
            return f"❌ Skill execution failed: {e}"

    async def _skill_test_mr_ephemeral(self, inputs: dict[str, Any]) -> str:
        """Execute test_mr_ephemeral skill inline using bonfire tools."""
        mr_id = inputs.get("mr_id")
        commit_sha: str = str(inputs.get("commit_sha") or "")
        billing = inputs.get("billing", False)
        duration = inputs.get("duration", "2h")

        if not mr_id and not commit_sha:
            return "Error: need either mr_id or commit_sha"

        # Step 1: Get commit SHA from MR if needed
        if mr_id and not commit_sha:
            mr_cmd = ["glab", "api", f"projects/:id/merge_requests/{mr_id}"]
            mr_result = await self._run_command(mr_cmd)

            try:
                mr_data = json.loads(mr_result)
                commit_sha = mr_data.get("sha", "")
                mr_state = mr_data.get("state", "")

                # If MR is merged, use the merge commit SHA
                if mr_state == "merged":
                    merge_sha = mr_data.get("merge_commit_sha", "")
                    if merge_sha:
                        commit_sha = merge_sha
                        logger.info(
                            f"MR {mr_id} is merged, using merge commit: {commit_sha[:12]}"
                        )

            except Exception as e:
                sha_match = re.search(r"[a-f0-9]{40}", mr_result)
                if sha_match:
                    commit_sha = sha_match.group(0)
                else:
                    return f"Could not get commit SHA from MR {mr_id}: {e}"

        # Validate/expand commit_sha
        if len(commit_sha) != 40:
            expand_result = await self._run_command(["git", "rev-parse", commit_sha])
            if len(expand_result.strip()) == 40:
                commit_sha = expand_result.strip()
            else:
                return f"Invalid commit SHA: {commit_sha}. Need 40-char SHA."

        # Step 2: Check if image exists in Quay
        quay_result = await self._execute_quay(
            "quay_get_tag",
            {
                "repository": "aap-aa-tenant/aap-aa-main/automation-analytics-backend-main",
                "tag": commit_sha,
            },
        )

        if "not found" in quay_result.lower() or "error" in quay_result.lower():
            return f"""❌ Image not ready for commit {commit_sha[:12]}.

The Konflux build may still be in progress. Check back in a few minutes.

{quay_result}"""

        # Extract digest
        digest_match = re.search(r"sha256:([a-f0-9]{64})", quay_result)
        if not digest_match:
            return f"Could not extract sha256 digest from Quay:\n{quay_result[:500]}"

        image_digest = digest_match.group(1)

        # Step 3: Reserve namespace
        reserve_result = await self._execute_bonfire(
            "bonfire_namespace_reserve",
            {
                "duration": duration,
            },
        )

        ns_match = re.search(r"(ephemeral-[a-z0-9]+)", reserve_result.lower())
        if not ns_match:
            return f"Could not reserve namespace:\n{reserve_result}"

        namespace = ns_match.group(1)

        # Step 4: Deploy
        deploy_result = await self._execute_bonfire(
            "bonfire_deploy_aa",
            {
                "namespace": namespace,
                "template_ref": commit_sha,
                "image_tag": image_digest,
                "billing": billing,
            },
        )

        component = "billing" if billing else "main"
        return f"""## ✅ Ephemeral Deployment Complete

**MR:** {mr_id or 'N/A'}
**Commit:** `{commit_sha[:12]}`
**Namespace:** `{namespace}`
**Component:** {component}

{deploy_result}

**Next steps:**
- Check pods: `k8s_get_pods` with namespace='{namespace}'
- Release when done: `bonfire_namespace_release` with namespace='{namespace}'"""


__all__ = ["ToolExecutor"]
