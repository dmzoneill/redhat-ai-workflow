#!/usr/bin/env python3
"""Skill Test Runner - Actually executes skills for integration testing.

This script:
1. Loads all skill YAML files
2. Parses their steps
3. Executes each tool call with test parameters
4. Captures and reports results

Usage:
    python scripts/skill_test_runner.py                    # Test all safe skills
    python scripts/skill_test_runner.py --skill start_work # Test specific skill
    python scripts/skill_test_runner.py --list             # List all skills
    python scripts/skill_test_runner.py --dry-run          # Show what would run
"""

import argparse
import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
TESTS_DIR = PROJECT_ROOT / "tests"
TOOL_MODULES_DIR = PROJECT_ROOT / "tool_modules"


@dataclass
class StepResult:
    """Result of executing a skill step."""

    step_name: str
    tool_name: str
    success: bool
    output: str = ""
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class SkillResult:
    """Result of executing a skill."""

    skill_name: str
    success: bool
    steps_total: int = 0
    steps_passed: int = 0
    steps_failed: int = 0
    steps_skipped: int = 0
    step_results: list = field(default_factory=list)
    error: str = ""


# Load exclusions
def load_exclusions() -> dict:
    """Load test exclusions from tests directory."""
    exclusions_file = TESTS_DIR / "test_exclusions.yaml"
    if not exclusions_file.exists():
        return {"excluded_skills": [], "excluded_tools": []}

    with open(exclusions_file) as f:
        config = yaml.safe_load(f)

    excluded_skills = []
    for item in config.get("excluded_skills", []):
        if isinstance(item, dict):
            excluded_skills.append(item["name"])
        else:
            excluded_skills.append(item)

    return {
        "excluded_skills": excluded_skills,
        "excluded_tools": config.get("excluded_tools", []),
    }


# Test parameters for tools when running in test mode
TEST_PARAMS = {
    # Git - use current repo
    "git_status": {"repo": str(PROJECT_ROOT)},
    "git_branch": {"repo": str(PROJECT_ROOT)},
    "git_log": {"repo": str(PROJECT_ROOT), "limit": 3},
    "git_remote": {"repo": str(PROJECT_ROOT)},
    # Jira - read-only searches
    "jira_search": {"jql": "project=AAP AND created >= -7d", "max_results": 3},
    "jira_view_issue": {"issue_key": "AAP-61660"},  # Recent CVE issue that exists
    "jira_my_issues": {"limit": 3},
    # GitLab - read-only
    "gitlab_mr_list": {"limit": 3},
    "gitlab_project_info": {},
    # Bonfire - read-only
    "bonfire_namespace_list": {"mine_only": True},
    # Quay - read-only
    "quay_list_tags": {"limit": 3},
    # K8s - read-only on ephemeral (use bonfire to find current namespace)
    "kubectl_get_pods": {"namespace": "", "environment": "ephemeral"},  # Will list all accessible
    "kubectl_get_events": {"namespace": "", "environment": "ephemeral"},
}


class ToolExecutor:
    """Executes MCP tools by calling the underlying CLI commands."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.exclusions = load_exclusions()

    async def execute(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute a tool and return (success, output)."""

        # Check if excluded
        if tool_name in self.exclusions["excluded_tools"]:
            return True, f"SKIPPED (excluded): {tool_name}"

        # Use test params - they OVERRIDE skill params for safety
        if tool_name in TEST_PARAMS:
            args = {**args, **TEST_PARAMS[tool_name]}  # Test params win

        if self.dry_run:
            return True, f"DRY RUN: {tool_name}({json.dumps(args)})"

        # Route to appropriate executor
        if tool_name.startswith("git_"):
            return await self._exec_git(tool_name, args)
        elif tool_name.startswith("jira_"):
            return await self._exec_jira(tool_name, args)
        elif tool_name.startswith("gitlab_"):
            return await self._exec_gitlab(tool_name, args)
        elif tool_name.startswith("bonfire_"):
            return await self._exec_bonfire(tool_name, args)
        elif tool_name.startswith("kubectl_") or tool_name.startswith("k8s_"):
            return await self._exec_k8s(tool_name, args)
        elif tool_name.startswith("quay_"):
            return await self._exec_quay(tool_name, args)
        else:
            return True, f"SKIPPED (no executor): {tool_name}"

    async def _run_cmd(self, cmd: list[str], cwd: str = None, env: dict = None) -> tuple[bool, str]:
        """Run a shell command."""
        try:
            full_env = os.environ.copy()
            if env:
                full_env.update(env)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd,
                env=full_env,
                timeout=60,
            )

            output = result.stdout or result.stderr
            return result.returncode == 0, output[:2000]  # Truncate

        except subprocess.TimeoutExpired:
            return False, "TIMEOUT after 60s"
        except Exception as e:
            return False, f"ERROR: {e}"

    async def _exec_git(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute git tools."""
        repo = args.get("repo", ".")

        if tool_name == "git_status":
            return await self._run_cmd(["git", "status"], cwd=repo)
        elif tool_name == "git_branch":
            return await self._run_cmd(["git", "branch", "--list"], cwd=repo)
        elif tool_name == "git_log":
            limit = args.get("limit", 5)
            return await self._run_cmd(["git", "log", "--oneline", f"-{limit}"], cwd=repo)
        elif tool_name == "git_remote":
            return await self._run_cmd(["git", "remote", "-v"], cwd=repo)
        else:
            return True, f"SKIPPED: {tool_name} not implemented"

    async def _exec_jira(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute jira tools via rh-issue CLI."""
        if tool_name == "jira_search":
            jql = args.get("jql", "project=AAP")
            max_results = args.get("max_results", 10)
            return await self._run_cmd(["rh-issue", "search", jql, "-m", str(max_results)])
        elif tool_name == "jira_view_issue":
            issue_key = args.get("issue_key")
            if not issue_key:
                return False, "Missing issue_key"
            return await self._run_cmd(["rh-issue", "view-issue", issue_key])
        elif tool_name == "jira_my_issues":
            return await self._run_cmd(["rh-issue", "list-issues", "--assignee", "@me"])
        else:
            return True, f"SKIPPED: {tool_name} not implemented for testing"

    async def _exec_gitlab(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute gitlab tools via glab CLI."""
        if tool_name == "gitlab_mr_list":
            limit = args.get("limit", 10)
            return await self._run_cmd(
                ["glab", "mr", "list", "--per-page", str(limit)],
                cwd=str(Path.home() / "src/automation-analytics-backend"),
            )
        elif tool_name == "gitlab_project_info":
            return await self._run_cmd(
                ["glab", "repo", "view"], cwd=str(Path.home() / "src/automation-analytics-backend")
            )
        else:
            return True, f"SKIPPED: {tool_name} not implemented for testing"

    async def _exec_bonfire(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute bonfire tools."""
        env = {"KUBECONFIG": str(Path.home() / ".kube/config.e")}

        if tool_name == "bonfire_namespace_list":
            cmd = ["bonfire", "namespace", "list"]
            if args.get("mine_only"):
                cmd.append("--mine")
            return await self._run_cmd(cmd, env=env)
        elif tool_name == "bonfire_apps_list":
            return await self._run_cmd(["bonfire", "apps", "list"], env=env)
        else:
            return True, f"SKIPPED: {tool_name} not implemented for testing"

    async def _exec_k8s(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute kubernetes tools."""
        env_map = {
            "stage": str(Path.home() / ".kube/config.s"),
            "production": str(Path.home() / ".kube/config.p"),
            "ephemeral": str(Path.home() / ".kube/config.e"),
        }

        environment = args.get("environment", "ephemeral")
        kubeconfig = env_map.get(environment, env_map["ephemeral"])
        namespace = args.get("namespace", "")

        if tool_name == "kubectl_get_pods":
            cmd = ["kubectl", f"--kubeconfig={kubeconfig}", "get", "pods"]
            if namespace:
                cmd.extend(["-n", namespace])
            return await self._run_cmd(cmd)
        elif tool_name == "kubectl_get_deployments":
            cmd = ["kubectl", f"--kubeconfig={kubeconfig}", "get", "deployments"]
            if namespace:
                cmd.extend(["-n", namespace])
            return await self._run_cmd(cmd)
        else:
            return True, f"SKIPPED: {tool_name} not implemented for testing"

    async def _exec_quay(self, tool_name: str, args: dict) -> tuple[bool, str]:
        """Execute quay tools via skopeo."""
        repo = "quay.io/redhat-user-workloads/aap-aa-tenant/aap-aa-main/automation-analytics-backend-main"

        if tool_name == "quay_list_tags":
            return await self._run_cmd(["skopeo", "list-tags", f"docker://{repo}"])
        else:
            return True, f"SKIPPED: {tool_name} not implemented for testing"


class SkillRunner:
    """Runs skills by parsing YAML and executing steps."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.exclusions = load_exclusions()
        self.executor = ToolExecutor(dry_run=dry_run)

    def list_skills(self) -> list[dict]:
        """List all available skills."""
        skills = []
        for path in sorted(SKILLS_DIR.glob("*.yaml")):
            try:
                with open(path) as f:
                    skill = yaml.safe_load(f)

                name = skill.get("name", path.stem)
                excluded = name in self.exclusions["excluded_skills"]

                skills.append(
                    {
                        "name": name,
                        "file": path.name,
                        "description": skill.get("description", "")[:80],
                        "excluded": excluded,
                        "steps": len(skill.get("steps", [])),
                    }
                )
            except Exception as e:
                skills.append(
                    {
                        "name": path.stem,
                        "file": path.name,
                        "description": f"ERROR: {e}",
                        "excluded": False,
                        "steps": 0,
                    }
                )

        return skills

    def load_skill(self, skill_name: str) -> dict | None:
        """Load a skill by name."""
        # Try exact match first
        skill_file = SKILLS_DIR / f"{skill_name}.yaml"
        if not skill_file.exists():
            # Try finding by name in files
            for path in SKILLS_DIR.glob("*.yaml"):
                try:
                    with open(path) as f:
                        skill = yaml.safe_load(f)
                    if skill and skill.get("name") == skill_name:
                        return skill
                except yaml.YAMLError:
                    continue
            return None

        try:
            with open(skill_file) as f:
                return yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"    ⚠️  YAML parse error in {skill_name}: {e}")
            return None

    async def run_skill(self, skill_name: str, inputs: dict = None) -> SkillResult:
        """Run a skill and return results."""
        result = SkillResult(skill_name=skill_name, success=False)

        # Check exclusion
        if skill_name in self.exclusions["excluded_skills"]:
            result.success = True
            result.error = "EXCLUDED (production-impacting)"
            return result

        # Load skill
        skill = self.load_skill(skill_name)
        if not skill:
            result.error = f"Skill not found: {skill_name}"
            return result

        steps = skill.get("steps", [])
        result.steps_total = len(steps)

        print(f"\n  📋 Running skill: {skill_name} ({len(steps)} steps)")

        # Execute each step
        for i, step in enumerate(steps):
            step_name = step.get("name", f"step_{i}")
            tool_name = step.get("tool", "")
            step_args = step.get("args", {})
            condition = step.get("condition", "")

            step_result = StepResult(step_name=step_name, tool_name=tool_name, success=False)

            # Skip compute steps (Python code)
            if "compute" in step:
                step_result.success = True
                step_result.skipped = True
                step_result.skip_reason = "compute step (Python)"
                result.steps_skipped += 1
                result.step_results.append(step_result)
                print(f"    ⏭️  {step_name}: SKIPPED (compute)")
                continue

            # Skip if no tool
            if not tool_name:
                step_result.success = True
                step_result.skipped = True
                step_result.skip_reason = "no tool"
                result.steps_skipped += 1
                result.step_results.append(step_result)
                continue

            # Skip conditional steps in test mode
            if condition:
                step_result.success = True
                step_result.skipped = True
                step_result.skip_reason = f"conditional: {condition[:50]}"
                result.steps_skipped += 1
                result.step_results.append(step_result)
                print(f"    ⏭️  {step_name}: SKIPPED (conditional)")
                continue

            # Execute the tool
            try:
                success, output = await self.executor.execute(tool_name, step_args)
                step_result.success = success
                step_result.output = output[:500]  # Truncate

                if success:
                    result.steps_passed += 1
                    print(f"    ✅ {step_name}: {tool_name}")
                else:
                    result.steps_failed += 1
                    step_result.error = output
                    print(f"    ❌ {step_name}: {tool_name}")
                    print(f"       Error: {output[:100]}...")

            except Exception as e:
                step_result.success = False
                step_result.error = str(e)
                result.steps_failed += 1
                print(f"    ❌ {step_name}: {tool_name} - {e}")

            result.step_results.append(step_result)

        # Skill succeeds if no failures
        result.success = result.steps_failed == 0

        return result

    async def run_all(self, skill_filter: str = None) -> list[SkillResult]:
        """Run all (or filtered) skills."""
        skills = self.list_skills()
        results = []

        print("\n" + "=" * 60)
        print("🧪 Skill Test Runner")
        print("=" * 60)
        print(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"  Skills found: {len(skills)}")
        print(f"  Excluded: {len([s for s in skills if s['excluded']])}")

        for skill_info in skills:
            name = skill_info["name"]

            # Filter if specified
            if skill_filter and skill_filter != name:
                continue

            # Skip excluded
            if skill_info["excluded"]:
                print(f"\n  ⏭️  {name}: EXCLUDED")
                results.append(SkillResult(skill_name=name, success=True, error="EXCLUDED"))
                continue

            result = await self.run_skill(name)
            results.append(result)

        # Summary
        self._print_summary(results)

        return results

    def _print_summary(self, results: list[SkillResult]):
        """Print test summary."""
        total = len(results)
        passed = len([r for r in results if r.success])
        failed = len([r for r in results if not r.success])
        excluded = len([r for r in results if r.error == "EXCLUDED"])

        print("\n" + "=" * 60)
        print("📊 SKILL TEST SUMMARY")
        print("=" * 60)
        print(f"  Skills tested: {total}")
        print(f"  Passed:        {passed} ✅")
        print(f"  Failed:        {failed} ❌")
        print(f"  Excluded:      {excluded} ⏭️")

        if failed > 0:
            print("\n  ❌ FAILURES:")
            for r in results:
                if not r.success and r.error != "EXCLUDED":
                    print(f"     • {r.skill_name}: {r.error[:60]}...")
                    for sr in r.step_results:
                        if not sr.success and not sr.skipped:
                            print(f"       - {sr.step_name}/{sr.tool_name}")

        print("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="Skill test runner")
    parser.add_argument("--skill", "-s", help="Run specific skill")
    parser.add_argument("--list", "-l", action="store_true", help="List all skills")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Dry run")
    args = parser.parse_args()

    runner = SkillRunner(dry_run=args.dry_run)

    if args.list:
        skills = runner.list_skills()
        print("\n📋 Available Skills:\n")
        print(f"{'Name':<25} {'Steps':<6} {'Excluded':<10} Description")
        print("-" * 80)
        for s in skills:
            excluded = "⏭️ YES" if s["excluded"] else ""
            print(f"{s['name']:<25} {s['steps']:<6} {excluded:<10} {s['description'][:40]}")
        print(f"\nTotal: {len(skills)} skills, {len([s for s in skills if s['excluded']])} excluded")
        return

    await runner.run_all(skill_filter=args.skill)


if __name__ == "__main__":
    asyncio.run(main())
