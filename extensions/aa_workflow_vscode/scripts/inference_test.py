#!/usr/bin/env python3
"""
Inference Test Script

Runs the HybridToolFilter to test tool filtering for a given message,
persona, and skill. Returns a JSON object with the filtered tools and
context information.

Usage:
    python3 inference_test.py --message "..." --persona "developer" [--skill "..."] [--project-root "/path/to/project"]
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run inference test")
    parser.add_argument("--message", required=True, help="The message to test")
    parser.add_argument("--persona", default="developer", help="The persona to use")
    parser.add_argument("--skill", default="", help="The detected skill (optional)")
    parser.add_argument("--project-root", default="", help="Project root directory")
    return parser.parse_args()


def get_memory_state(project_root: Path) -> dict:
    """Load memory state from current_work.yaml and detect git info."""
    memory_state = {}

    # Load from YAML file
    try:
        import yaml

        memory_path = Path.home() / ".aa-workflow" / "memory" / "state" / "current_work.yaml"
        if memory_path.exists():
            with open(memory_path) as f:
                memory_state = yaml.safe_load(f) or {}
    except Exception:
        pass

    # Detect current repo and branch from git if not in memory
    try:
        if not memory_state.get("repo"):
            try:
                remote_url = (
                    subprocess.check_output(
                        ["git", "config", "--get", "remote.origin.url"],
                        cwd=str(project_root),
                        stderr=subprocess.DEVNULL,
                    )
                    .decode()
                    .strip()
                )
                repo_name = remote_url.rstrip("/").split("/")[-1].replace(".git", "")
                memory_state["repo"] = repo_name
            except Exception:
                memory_state["repo"] = project_root.name

        if not memory_state.get("current_branch"):
            try:
                branch = (
                    subprocess.check_output(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(project_root), stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )
                memory_state["current_branch"] = branch
            except Exception:
                pass
    except Exception:
        pass

    return memory_state


def get_environment_status(project_root: Path) -> dict:
    """Get environment status (VPN, kubeconfigs, Ollama instances)."""
    env_status = {
        "vpn_connected": os.path.exists(os.path.expanduser("~/.aa-workflow/.vpn_connected")),
        "kubeconfigs": {
            "stage": os.path.exists(os.path.expanduser("~/.kube/config.s")),
            "prod": os.path.exists(os.path.expanduser("~/.kube/config.p")),
            "ephemeral": os.path.exists(os.path.expanduser("~/.kube/config.e")),
            "konflux": os.path.exists(os.path.expanduser("~/.kube/config.k")),
        },
        "ollama_instances": [],
    }

    # Check Ollama instances from config
    try:
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            for name, inst in config.get("ollama_instances", {}).items():
                env_status["ollama_instances"].append(
                    {
                        "name": name,
                        "url": inst.get("url", ""),
                        "device": inst.get("device", "unknown"),
                    }
                )
    except Exception:
        pass

    return env_status


def get_persona_info(project_root: Path, persona: str) -> tuple:
    """Get persona prompt, categories, and tool modules."""
    import yaml

    persona_prompt = ""
    persona_categories = []
    persona_tool_modules = []

    # Load from persona YAML
    try:
        persona_path = project_root / "personas" / f"{persona}.yaml"
        if persona_path.exists():
            with open(persona_path) as f:
                persona_data = yaml.safe_load(f) or {}
            persona_prompt = persona_data.get("description", "")[:500]
            persona_tool_modules = persona_data.get("tools", [])
    except Exception:
        pass

    # Get categories from config.json persona_baselines
    try:
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            baseline = config.get("persona_baselines", {}).get(persona, {})
            persona_categories = baseline.get("categories", [])
    except Exception:
        pass

    return persona_prompt, persona_categories, persona_tool_modules


def get_session_log() -> list:
    """Get today's session log (last 5 actions)."""
    from datetime import date

    import yaml

    session_log = []
    try:
        log_path = Path.home() / ".aa-workflow" / "memory" / "sessions" / f"{date.today().isoformat()}.yaml"
        if log_path.exists():
            with open(log_path) as f:
                log_data = yaml.safe_load(f) or {}
            session_log = log_data.get("actions", [])[-5:]
    except Exception:
        pass

    return session_log


def get_learned_patterns() -> list:
    """Get learned patterns from memory."""
    import yaml

    learned_patterns = []
    try:
        patterns_path = Path.home() / ".aa-workflow" / "memory" / "learned" / "patterns.yaml"
        if patterns_path.exists():
            with open(patterns_path) as f:
                patterns_data = yaml.safe_load(f) or {}
            for pattern in patterns_data.get("error_patterns", [])[:3]:
                learned_patterns.append(
                    {
                        "pattern": pattern.get("pattern", ""),
                        "fix": pattern.get("fix", ""),
                    }
                )
    except Exception:
        pass

    return learned_patterns


def run_inference(message: str, persona: str, skill: str, project_root: Path) -> dict:
    """Run the inference test and return results."""
    from aa_ollama.src.tool_filter import HybridToolFilter

    filter_instance = HybridToolFilter()

    start = time.time()
    result = filter_instance.filter(message=message, persona=persona, detected_skill=skill if skill else None)
    latency_ms = (time.time() - start) * 1000

    # Get the actual persona (may have been auto-detected)
    actual_persona = result.get("persona", persona) or "developer"
    persona_auto_detected = result.get("persona_auto_detected", False)
    persona_detection_reason = result.get("persona_detection_reason", "")

    # Gather context
    memory_state = get_memory_state(project_root)
    env_status = get_environment_status(project_root)
    persona_prompt, persona_categories, persona_tool_modules = get_persona_info(project_root, actual_persona)
    session_log = get_session_log()
    learned_patterns = get_learned_patterns()

    # Get semantic results from filter context if available
    semantic_results = []
    try:
        ctx = result.get("context", {})
        semantic_results = ctx.get("semantic_knowledge", [])[:5]
    except Exception:
        pass

    # Build output
    output = {
        "tools": result.get("tools", [])[:50],
        "tool_count": len(result.get("tools", [])),
        "reduction_pct": result.get("reduction_pct", 0),
        "methods": result.get("methods", []),
        "persona": actual_persona,
        "persona_auto_detected": persona_auto_detected,
        "persona_detection_reason": persona_detection_reason,
        "skill_detected": result.get("skill_detected"),
        "latency_ms": round(latency_ms, 1),
        "message_preview": message[:50],
        "context": result.get("context", {}),
        "semantic_results": semantic_results,
        "memory_state": {
            "active_issues": memory_state.get("active_issues", [])[:3],
            "current_branch": memory_state.get("current_branch"),
            "current_repo": memory_state.get("repo"),
            "notes": memory_state.get("notes", "")[:200] if memory_state.get("notes") else None,
        },
        "environment": env_status,
        "persona_prompt": persona_prompt,
        "persona_categories": persona_categories,
        "persona_tool_modules": persona_tool_modules,
        "session_log": session_log,
        "learned_patterns": learned_patterns,
    }

    return output


def main():
    """Main entry point."""
    args = parse_args()

    # Determine project root
    if args.project_root:
        project_root = Path(args.project_root)
    else:
        project_root = Path.home() / "src" / "redhat-ai-workflow"

    # Add project root to path for proper module imports
    sys.path.insert(0, str(project_root))
    sys.path.insert(0, str(project_root / "tool_modules"))

    try:
        output = run_inference(args.message, args.persona, args.skill, project_root)
        print(json.dumps(output))
    except Exception as e:
        import traceback

        # Fallback to placeholder if backend not available
        print(
            json.dumps(
                {
                    "tools": ["skill_run", "jira_view_issue", "gitlab_mr_view"],
                    "tool_count": 3,
                    "reduction_pct": 98.6,
                    "methods": ["layer1_core", "layer2_persona"],
                    "persona": args.persona,
                    "skill_detected": args.skill if args.skill else None,
                    "latency_ms": 2,
                    "message_preview": args.message[:50],
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                }
            )
        )


if __name__ == "__main__":
    main()
