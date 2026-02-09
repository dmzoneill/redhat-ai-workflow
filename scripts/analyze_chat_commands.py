#!/usr/bin/env python3
"""
Analyze AI chat logs across Cursor, Claude Code, Gemini CLI, and Codex
to find direct shell/CLI commands that should be converted to MCP tools.

Data Sources:
  1. Cursor chat SQLite: ~/.cursor/chats/*/store.db (blobs table)
  2. Claude Code sessions: ~/.claude/projects/*/*.jsonl
  3. Gemini CLI sessions: ~/.gemini/tmp/*/chats/session-*.json
  4. Codex sessions: ~/.codex/sessions/**/*.jsonl

Output: JSON report of all direct commands found, categorized by type.
"""

import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from glob import glob

# Commands that indicate direct CLI usage (should be MCP tools)
COMMAND_PATTERNS = [
    # Network/API
    (r"\bcurl\s+", "curl", "network"),
    (r"\bwget\s+", "wget", "network"),
    (r"\bhttpie\s+", "httpie", "network"),
    (r"\bhttp\s+(?:GET|POST|PUT|DELETE|PATCH|HEAD)", "httpie", "network"),
    # Kubernetes/OpenShift
    (r"\bkubectl\s+", "kubectl", "kubernetes"),
    (
        r"\boc\s+(?:get|describe|logs|exec|rsh|apply|delete|create|patch|label"
        r"|annotate|rollout|scale|adm|project|new-project|login|whoami|status)",
        "oc",
        "kubernetes",
    ),
    (r"\bhelm\s+", "helm", "kubernetes"),
    (r"\bbonfire\s+", "bonfire", "kubernetes"),
    # Git
    (
        r"\bgit\s+(?:clone|pull|push|fetch|checkout|branch|merge|rebase|stash"
        r"|log|diff|status|add|commit|reset|tag|remote|cherry-pick|bisect|revert)",
        "git",
        "git",
    ),
    # Docker/Podman
    (
        r"\bdocker\s+(?:build|run|push|pull|exec|logs|ps|images|stop|rm|rmi|compose|inspect|network|volume)",
        "docker",
        "container",
    ),
    (
        r"\bpodman\s+(?:build|run|push|pull|exec|logs|ps|images|stop|rm|rmi|compose|inspect|network|volume)",
        "podman",
        "container",
    ),
    (r"\bskopeo\s+", "skopeo", "container"),
    # Cloud/Infrastructure
    (r"\baws\s+", "aws", "cloud"),
    (r"\bgcloud\s+", "gcloud", "cloud"),
    (r"\baz\s+", "az", "cloud"),
    (r"\bterraform\s+", "terraform", "infrastructure"),
    (r"\bansible(?:-playbook)?\s+", "ansible", "infrastructure"),
    # Package managers
    (r"\bpip\s+install\b", "pip", "package_mgmt"),
    (r"\bnpm\s+(?:install|run|start|test|build|publish)", "npm", "package_mgmt"),
    (r"\byarn\s+", "yarn", "package_mgmt"),
    (r"\bdnf\s+", "dnf", "package_mgmt"),
    (r"\bapt(?:-get)?\s+", "apt", "package_mgmt"),
    (r"\bbrew\s+", "brew", "package_mgmt"),
    (r"\bpipenv\s+", "pipenv", "package_mgmt"),
    # Build/Test
    (r"\bmake\s+", "make", "build"),
    (r"\bpytest\b", "pytest", "test"),
    (r"\btox\b", "tox", "test"),
    (r"\bflake8\b", "flake8", "lint"),
    (r"\bruff\b", "ruff", "lint"),
    (r"\bmypy\b", "mypy", "lint"),
    (r"\bpylint\b", "pylint", "lint"),
    (r"\bblack\b", "black", "lint"),
    (r"\bisort\b", "isort", "lint"),
    # System/File
    (r"\bssh\s+", "ssh", "system"),
    (r"\bscp\s+", "scp", "system"),
    (r"\brsync\s+", "rsync", "system"),
    (r"\bsudo\s+", "sudo", "system"),
    (r"\bsystemctl\s+", "systemctl", "system"),
    (r"\bjournalctl\b", "journalctl", "system"),
    # Jira/GitLab CLI
    (r"\bjira\s+", "jira-cli", "project_mgmt"),
    (r"\bglab\s+", "glab", "project_mgmt"),
    (r"\bgh\s+", "gh", "project_mgmt"),
    # Database
    (r"\bpsql\s+", "psql", "database"),
    (r"\bmysql\s+", "mysql", "database"),
    (r"\bredis-cli\b", "redis-cli", "database"),
    # Monitoring
    (r"\bpromtool\b", "promtool", "monitoring"),
    # Konflux/Tekton
    (r"\btkn\s+", "tkn", "cicd"),
    (r"\bkflux\s+", "kflux", "cicd"),
    # Python/Node execution
    (r"\bpython3?\s+-[mc]\s+", "python", "runtime"),
    (r"\bnode\s+-e\s+", "node", "runtime"),
    # OpenSSL/Security
    (r"\bopenssl\s+", "openssl", "security"),
    (r"\bpass\s+(?:show|insert|generate|ls)", "pass", "security"),
    # Red Hat specific
    (r"\brhtoken\b", "rhtoken", "redhat"),
    (r"\bocm\s+", "ocm", "redhat"),
    # Misc
    (r"\bjq\s+", "jq", "data_processing"),
    (r"\byq\s+", "yq", "data_processing"),
    (r"\bbase64\s+", "base64", "data_processing"),
    (r"\benvsubst\b", "envsubst", "data_processing"),
]


def extract_commands_from_text(text, source_info=""):
    """Extract CLI commands from text content."""
    commands = []
    if not text:
        return commands

    lines = text.split("\n")
    for i, line in enumerate(lines):
        line = line.strip()
        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        for pattern, cmd_name, category in COMMAND_PATTERNS:
            if re.search(pattern, line):
                # Clean up the command line
                cmd_line = line
                # Remove common prefixes
                cmd_line = re.sub(r"^[$>%]\s*", "", cmd_line)
                cmd_line = re.sub(r"^```\w*\s*", "", cmd_line)
                cmd_line = cmd_line.rstrip("`")

                if (
                    len(cmd_line) > 10 and len(cmd_line) < 1000
                ):  # Reasonable command length
                    commands.append(
                        {
                            "command": cmd_line,
                            "tool": cmd_name,
                            "category": category,
                            "source": source_info,
                            "line_context": i,
                        }
                    )
                break  # Only match first pattern per line

    return commands


def process_cursor_chats():
    """Process Cursor SQLite chat databases."""
    print("=== Processing Cursor Chat Databases ===", file=sys.stderr)
    commands = []
    db_files = glob(os.path.expanduser("~/.cursor/chats/**/store.db"), recursive=True)

    for db_file in db_files:
        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

            # Get blobs
            cursor.execute("SELECT id, data FROM blobs")
            for blob_id, data in cursor.fetchall():
                try:
                    if isinstance(data, bytes):
                        text = data.decode("utf-8", errors="ignore")
                    else:
                        text = str(data)

                    # Try to parse as JSON to extract tool calls / commands
                    try:
                        json_data = json.loads(text)
                        if isinstance(json_data, list):
                            for msg in json_data:
                                if isinstance(msg, dict):
                                    content = msg.get("content", "")
                                    role = msg.get("role", "")
                                    if isinstance(content, str):
                                        cmds = extract_commands_from_text(
                                            content,
                                            f"cursor:{db_file}:blob:{blob_id[:12]}:role:{role}",
                                        )
                                        commands.extend(cmds)
                                    elif isinstance(content, list):
                                        for part in content:
                                            if isinstance(part, dict):
                                                t = part.get("text", "") or part.get(
                                                    "content", ""
                                                )
                                                if t:
                                                    cmds = extract_commands_from_text(
                                                        t,
                                                        f"cursor:{db_file}:blob:{blob_id[:12]}:role:{role}",
                                                    )
                                                    commands.extend(cmds)
                        elif isinstance(json_data, dict):
                            # Might be a single message or config
                            content = json_data.get("content", "")
                            if isinstance(content, str):
                                cmds = extract_commands_from_text(
                                    content, f"cursor:{db_file}:blob:{blob_id[:12]}"
                                )
                                commands.extend(cmds)
                    except json.JSONDecodeError:
                        # Not JSON, treat as raw text
                        cmds = extract_commands_from_text(
                            text, f"cursor:{db_file}:blob:{blob_id[:12]}"
                        )
                        commands.extend(cmds)

                except Exception as e:
                    print(
                        f"  Error processing blob {blob_id[:12]}: {e}", file=sys.stderr
                    )

            conn.close()
        except Exception as e:
            print(f"  Error with DB {db_file}: {e}", file=sys.stderr)

    print(f"  Found {len(commands)} commands in Cursor chats", file=sys.stderr)
    return commands


def process_claude_sessions():
    """Process Claude Code session JSONL files."""
    print("=== Processing Claude Code Sessions ===", file=sys.stderr)
    commands = []
    project_dirs = glob(os.path.expanduser("~/.claude/projects/*/"))

    session_count = 0
    for project_dir in project_dirs:
        project_name = os.path.basename(project_dir.rstrip("/"))
        session_files = glob(os.path.join(project_dir, "*.jsonl"))
        # Also include subagent sessions
        session_files += glob(os.path.join(project_dir, "*/subagents/*.jsonl"))

        for session_file in session_files:
            session_count += 1
            try:
                with open(session_file, "r", errors="ignore", encoding="utf-8") as f:
                    for _line_num, line in enumerate(f):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)

                            # Claude Code format: messages with tool_use
                            if entry.get("type") == "assistant":
                                # Check for tool calls (shell commands)
                                message = entry.get("message", {})
                                content = message.get("content", [])
                                if isinstance(content, list):
                                    for block in content:
                                        if isinstance(block, dict):
                                            if block.get("type") == "tool_use":
                                                tool_name = block.get("name", "")
                                                tool_input = block.get("input", {})
                                                if tool_name in (
                                                    "Bash",
                                                    "bash",
                                                    "execute_command",
                                                    "run_terminal_command",
                                                ):
                                                    cmd = tool_input.get(
                                                        "command", ""
                                                    ) or tool_input.get("cmd", "")
                                                    if cmd:
                                                        cmds = extract_commands_from_text(
                                                            cmd,
                                                            f"claude:{project_name}:{os.path.basename(session_file)}",
                                                        )
                                                        commands.extend(cmds)
                                            elif block.get("type") == "text":
                                                text = block.get("text", "")
                                                cmds = extract_commands_from_text(
                                                    text,
                                                    f"claude:{project_name}:{os.path.basename(session_file)}",
                                                )
                                                commands.extend(cmds)

                            elif entry.get("type") == "human":
                                message = entry.get("message", {})
                                content = message.get("content", [])
                                if isinstance(content, str):
                                    cmds = extract_commands_from_text(
                                        content,
                                        f"claude:{project_name}:{os.path.basename(session_file)}:user",
                                    )
                                    commands.extend(cmds)
                                elif isinstance(content, list):
                                    for block in content:
                                        if (
                                            isinstance(block, dict)
                                            and block.get("type") == "text"
                                        ):
                                            cmds = extract_commands_from_text(
                                                block.get("text", ""),
                                                f"claude:{project_name}:{os.path.basename(session_file)}:user",
                                            )
                                            commands.extend(cmds)

                            # Also check tool_result blocks for commands
                            elif entry.get("type") == "tool_result":
                                content = entry.get("content", "")
                                if isinstance(content, str):
                                    cmds = extract_commands_from_text(
                                        content,
                                        f"claude:{project_name}:{os.path.basename(session_file)}:result",
                                    )
                                    commands.extend(cmds)

                        except json.JSONDecodeError:
                            continue

            except Exception as e:
                print(f"  Error with {session_file}: {e}", file=sys.stderr)

    print(
        f"  Processed {session_count} sessions, found {len(commands)} commands",
        file=sys.stderr,
    )
    return commands


def process_gemini_sessions():
    """Process Gemini CLI session JSON files."""
    print("=== Processing Gemini CLI Sessions ===", file=sys.stderr)
    commands = []
    session_files = glob(os.path.expanduser("~/.gemini/tmp/*/chats/session-*.json"))

    for session_file in session_files:
        try:
            with open(session_file, "r", errors="ignore", encoding="utf-8") as f:
                data = json.load(f)

            messages = data.get("messages", [])
            for msg in messages:
                msg_type = msg.get("type", "")
                content = msg.get("content", "")

                # Check tool calls
                tool_calls = msg.get("toolCalls", [])
                for tc in tool_calls:
                    tc_name = tc.get("id", "").split("-")[0] if tc.get("id") else ""
                    tc_args = tc.get("args", {})
                    if (
                        "shell" in tc_name.lower()
                        or "command" in tc_name.lower()
                        or "bash" in tc_name.lower()
                    ):
                        cmd = tc_args.get("command", "") or tc_args.get("cmd", "")
                        if cmd:
                            cmds = extract_commands_from_text(
                                cmd, f"gemini:{os.path.basename(session_file)}"
                            )
                            commands.extend(cmds)

                # Also check raw content for commands
                if isinstance(content, str) and content:
                    cmds = extract_commands_from_text(
                        content,
                        f"gemini:{os.path.basename(session_file)}:type:{msg_type}",
                    )
                    commands.extend(cmds)

                # Check tool results
                tool_results = msg.get("toolResults", [])
                for tr in tool_results:
                    result_text = tr.get("result", "")
                    if isinstance(result_text, str):
                        cmds = extract_commands_from_text(
                            result_text,
                            f"gemini:{os.path.basename(session_file)}:result",
                        )
                        commands.extend(cmds)

        except Exception as e:
            print(f"  Error with {session_file}: {e}", file=sys.stderr)

    print(
        f"  Found {len(commands)} commands in {len(session_files)} Gemini sessions",
        file=sys.stderr,
    )
    return commands


def process_codex_sessions():
    """Process Codex session JSONL files."""
    print("=== Processing Codex Sessions ===", file=sys.stderr)
    commands = []
    session_files = glob(
        os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True
    )
    # Also check history
    history_file = os.path.expanduser("~/.codex/history.jsonl")
    if os.path.exists(history_file):
        session_files.append(history_file)

    for session_file in session_files:
        try:
            with open(session_file, "r", errors="ignore", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Codex format: check for shell commands in various fields
                        text = entry.get("text", "")
                        if text:
                            cmds = extract_commands_from_text(
                                text, f"codex:{os.path.basename(session_file)}"
                            )
                            commands.extend(cmds)

                        # Check for tool calls
                        for key in ("tool_calls", "function_calls", "actions"):
                            calls = entry.get(key, [])
                            if isinstance(calls, list):
                                for call in calls:
                                    if isinstance(call, dict):
                                        cmd = call.get("command", "") or call.get(
                                            "input", ""
                                        )
                                        if cmd:
                                            cmds = extract_commands_from_text(
                                                cmd,
                                                f"codex:{os.path.basename(session_file)}",
                                            )
                                            commands.extend(cmds)

                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            print(f"  Error with {session_file}: {e}", file=sys.stderr)

    print(
        f"  Found {len(commands)} commands in {len(session_files)} Codex sessions",
        file=sys.stderr,
    )
    return commands


def deduplicate_commands(commands):
    """Deduplicate commands, keeping count and all sources."""
    deduped = defaultdict(
        lambda: {"count": 0, "sources": set(), "category": "", "tool": ""}
    )

    for cmd in commands:
        # Normalize command for dedup (strip variable parts like specific file paths)
        key = cmd["command"].strip()
        deduped[key]["count"] += 1
        deduped[key]["sources"].add(
            cmd["source"].split(":")[0]
        )  # Just keep source type
        deduped[key]["category"] = cmd["category"]
        deduped[key]["tool"] = cmd["tool"]

    result = []
    for cmd_text, info in deduped.items():
        result.append(
            {
                "command": cmd_text,
                "tool": info["tool"],
                "category": info["category"],
                "count": info["count"],
                "sources": sorted(info["sources"]),
            }
        )

    return sorted(result, key=lambda x: (-x["count"], x["category"], x["tool"]))


def generate_report(all_commands):
    """Generate the final analysis report."""
    deduped = deduplicate_commands(all_commands)

    # Category summary
    category_counts = Counter()
    tool_counts = Counter()
    source_counts = Counter()

    for cmd in all_commands:
        category_counts[cmd["category"]] += 1
        tool_counts[cmd["tool"]] += 1
        source_counts[cmd["source"].split(":")[0]] += 1

    report = {
        "summary": {
            "total_commands_found": len(all_commands),
            "unique_commands": len(deduped),
            "by_category": dict(category_counts.most_common()),
            "by_tool": dict(tool_counts.most_common()),
            "by_source": dict(source_counts.most_common()),
        },
        "commands_by_category": {},
        "top_commands": deduped[:100],  # Top 100 most frequent
    }

    # Group by category
    for cmd in deduped:
        cat = cmd["category"]
        if cat not in report["commands_by_category"]:
            report["commands_by_category"][cat] = []
        report["commands_by_category"][cat].append(cmd)

    return report


def main():
    print("Starting comprehensive chat command analysis...", file=sys.stderr)
    print(f"Date: {__import__('datetime').datetime.now().isoformat()}", file=sys.stderr)

    all_commands = []

    # Process all sources
    all_commands.extend(process_cursor_chats())
    all_commands.extend(process_claude_sessions())
    all_commands.extend(process_gemini_sessions())
    all_commands.extend(process_codex_sessions())

    print(f"\n=== TOTAL: {len(all_commands)} commands found ===", file=sys.stderr)

    # Generate and output report
    report = generate_report(all_commands)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
