"""
Common parsers for MCP tool output.
These functions are used by multiple skills to avoid code duplication.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from scripts.common.config_loader import get_jira_url  # noqa: E402

try:
    from .parsers_gitlab import *  # noqa: F401, F403
except ImportError:
    from scripts.common.parsers_gitlab import *  # noqa: F401, F403


def parse_jira_issues(output: str) -> List[Dict[str, str]]:
    """
    Parse jira_search output into structured issue data.

    Args:
        output: Raw output from jira search

    Returns:
        List of dicts with 'key' and 'summary' keys
    """
    issues: List[Dict[str, str]] = []
    if not output:
        return issues

    for line in str(output).split("\n"):
        # Parse: AAP-12345  Summary text or AAP-12345: Summary text
        match = re.match(r"(AAP-\d+)[:\s]+(.+)", line)
        if match:
            issues.append({"key": match.group(1), "summary": match.group(2)[:50]})
    return issues


def parse_namespaces(output: str) -> List[Dict[str, str]]:
    """
    Parse bonfire namespace list output.

    Args:
        output: Raw output from bonfire namespace list

    Returns:
        List of dicts with 'name' and 'expires' keys
    """
    namespaces: List[Dict[str, str]] = []
    if not output:
        return namespaces

    for line in str(output).split("\n"):
        # Parse: ephemeral-xxxxx  expires in 2h 30m
        match = re.search(r"(ephemeral-\w+)\s+.*?(\d+[hm].*?)(?:\s|$)", line)
        if match:
            namespaces.append(
                {"name": match.group(1), "expires": match.group(2).strip()}
            )
        elif "ephemeral-" in line:
            # Fallback: just get the namespace name
            ns_match = re.search(r"(ephemeral-\w+)", line)
            if ns_match:
                namespaces.append({"name": ns_match.group(1), "expires": "unknown"})
    return namespaces


def parse_git_log(output: str) -> List[Dict[str, str]]:
    """
    Parse git log --oneline output into structured commit data.

    Args:
        output: Raw output from git log --oneline or similar

    Returns:
        List of dicts with 'sha' and 'message' keys
    """
    commits: List[Dict[str, str]] = []
    if not output:
        return commits

    for line in str(output).strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Handle markdown formatted output like "- `abc1234 commit message`"
        md_match = re.search(r"`([a-f0-9]{7,})\s+(.+?)`", line)
        if md_match:
            commits.append(
                {"sha": md_match.group(1)[:7], "message": md_match.group(2)[:60]}
            )
            continue

        # Standard git log --oneline format: "abc1234 commit message"
        parts = line.split(" ", 1)
        if len(parts) >= 1 and re.match(r"^[a-f0-9]{7,}$", parts[0]):
            commits.append(
                {"sha": parts[0][:7], "message": parts[1] if len(parts) > 1 else ""}
            )
    return commits


def parse_git_branches(output: str, issue_key: Optional[str] = None) -> List[str]:
    """
    Parse git branch output into branch names.

    Handles multiple formats:
    - Raw git branch -a output: "* main", "  feature-branch", "  remotes/origin/main"
    - Formatted markdown from git_branch_list tool:
        "## Branches in `/repo`"
        "**Current:** `branch-name`"
        "  `branch1` → `origin/branch1` (3 weeks ago)"

    Args:
        output: Raw output from git branch -a or git_branch_list tool
        issue_key: Optional issue key to filter branches

    Returns:
        List of branch names (cleaned)
    """
    branches: List[str] = []
    if not output:
        return branches

    for line in str(output).split("\n"):
        branch = None

        # Handle formatted markdown from git_branch_list tool
        # Format: "**Current:** `branch-name`"
        current_match = re.search(r"\*\*Current:\*\*\s*`([^`]+)`", line)
        if current_match:
            branch = current_match.group(1)
        else:
            # Format: "  `branch-name` → `origin/branch-name` (time ago)"
            # or: "→ `branch-name` → `origin/branch-name` (time ago)"
            backtick_match = re.search(r"^\s*[→\s]*`([^`]+)`", line)
            if backtick_match:
                branch = backtick_match.group(1)
            else:
                # Fallback: Raw git branch output
                # Clean the branch name from raw format
                branch = line.strip().replace("* ", "").replace("remotes/origin/", "")

        if not branch or branch in ["main", "master", "HEAD", ""]:
            continue

        # Skip header lines
        if branch.startswith("##") or branch.startswith("Branches in"):
            continue

        # Filter by issue key if provided
        if issue_key and issue_key.upper() not in branch.upper():
            continue

        if branch not in branches:
            branches.append(branch)

    return branches


def parse_kubectl_pods(output: str) -> List[Dict[str, Any]]:
    """
    Parse kubectl get pods output into structured pod data.

    Args:
        output: Raw output from kubectl get pods

    Returns:
        List of dicts with pod info (name, ready, status, restarts, age)
    """
    pods: List[Dict[str, Any]] = []
    if not output:
        return pods

    for line in str(output).split("\n"):
        if not line.strip() or line.startswith("NAME"):
            continue

        parts = line.split()
        if len(parts) >= 3:
            pod: Dict[str, Any] = {
                "name": parts[0],
                "ready": parts[1] if len(parts) > 1 else "?/?",
                "status": parts[2] if len(parts) > 2 else "Unknown",
                "restarts": parts[3] if len(parts) > 3 else "0",
                "age": parts[4] if len(parts) > 4 else "?",
            }

            # Mark health status
            pod["healthy"] = (
                pod["status"] == "Running"
                and pod["ready"].split("/")[0] == pod["ready"].split("/")[1]
            )
            pods.append(pod)

    return pods


def parse_stale_branches(output: str, max_age_days: int = 30) -> List[str]:
    """
    Parse git branches and filter for stale ones.

    Args:
        output: Raw output from git branch
        max_age_days: Not used (future: check commit age)

    Returns:
        List of stale branch names
    """
    branches = parse_git_branches(output)
    # For now just return non-main branches; future: check commit dates
    return [b for b in branches if b not in ["main", "master", "develop"]][:5]


def parse_git_conflicts(status_output: str) -> List[Dict[str, str]]:
    """
    Parse git status output for merge/rebase conflicts.

    Args:
        status_output: Raw output from git status or git status --porcelain

    Returns:
        List of dicts with 'file' and 'type' keys
    """
    conflicts: List[Dict[str, str]] = []
    if not status_output:
        return conflicts

    for line in str(status_output).split("\n"):
        line = line.strip()
        if not line:
            continue

        # Porcelain format: "UU file.py" or "AA file.py"
        if line.startswith("UU ") or line.startswith("AA "):
            conflicts.append(
                {
                    "file": line[3:],
                    "type": "both modified" if line.startswith("UU") else "both added",
                }
            )
        # Human readable: "both modified: file.py"
        elif "both modified" in line.lower():
            match = re.search(r":\s*(.+)$", line)
            if match:
                conflicts.append(
                    {"file": match.group(1).strip(), "type": "both modified"}
                )
        elif "both added" in line.lower():
            match = re.search(r":\s*(.+)$", line)
            if match:
                conflicts.append({"file": match.group(1).strip(), "type": "both added"})

    return conflicts


def extract_jira_key(text: str) -> Optional[str]:
    """
    Extract Jira issue key from text (commit message, branch name, etc).

    Args:
        text: Text to search

    Returns:
        Jira key like 'AAP-12345' or None
    """
    if not text:
        return None

    match = re.search(r"\b([A-Z]{2,10}-\d+)\b", str(text))
    return match.group(1) if match else None


def validate_jira_key(key: str) -> bool:
    """
    Validate that a string is a properly formatted Jira issue key.

    Args:
        key: The string to validate (e.g., "AAP-12345")

    Returns:
        True if valid Jira key format, False otherwise
    """
    if not key:
        return False
    return bool(re.match(r"^[A-Z]{2,10}-\d+$", str(key).strip().upper()))


def parse_jira_status(issue_details: str) -> Optional[str]:
    """
    Extract status from Jira issue details.

    Args:
        issue_details: Raw output from jira_view_issue

    Returns:
        Status string or None
    """
    if not issue_details:
        return None

    match = re.search(r"Status[:\s]+(\S+)", str(issue_details), re.IGNORECASE)
    return match.group(1) if match else None


def parse_conflict_markers(content: str) -> List[Dict[str, str]]:
    """
    Parse git conflict markers from file content.

    Args:
        content: File content with conflict markers

    Returns:
        List of dicts with 'ours', 'theirs', and 'full_marker' keys
    """
    conflicts: List[Dict[str, str]] = []
    if not content:
        return conflicts

    # Pattern: <<<<<<< ... ======= ... >>>>>>>
    pattern = r"<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>>[^\n]*"
    matches = re.findall(pattern, str(content), re.DOTALL)

    for ours, theirs in matches:
        conflicts.append({"ours": ours.strip(), "theirs": theirs.strip()})

    return conflicts


def extract_conflict_files(output: str) -> List[str]:
    """
    Extract list of conflicting files from rebase/merge output.

    Args:
        output: Output from git rebase or git merge

    Returns:
        List of file paths with conflicts
    """
    if not output:
        return []

    # Pattern: "- `filename`" or "CONFLICT (content): filename"
    files = []

    # Markdown format
    md_files = re.findall(r"- `([^`]+)`", str(output))
    files.extend(md_files)

    # Git conflict format
    conflict_files = re.findall(
        r"CONFLICT \([^)]+\):\s*(?:Merge conflict in\s*)?(\S+)", str(output)
    )
    files.extend(conflict_files)

    return list(set(files))  # Deduplicate


def extract_current_branch(git_status_output: str) -> Optional[str]:
    """
    Extract the current branch name from git status output.

    Args:
        git_status_output: Raw output from git status

    Returns:
        Current branch name or None
    """
    if not git_status_output:
        return None

    match = re.search(r"On branch (\S+)", str(git_status_output))
    return match.group(1) if match else None


def parse_prometheus_alert(message: str) -> Dict[str, Any]:
    """
    Parse Prometheus alert message from Slack or AlertManager.

    Args:
        message: Raw alert message (may contain HTML)

    Returns:
        Dict with:
        - alert_name: Name of the alert
        - firing_count: Number of firing instances
        - description: Alert description
        - namespace: Affected namespace (if found)
        - is_billing: Whether this is a billing-related alert
        - links: Dict of extracted links (grafana, prometheus, alertmanager, etc.)
    """
    import html

    if not message:
        return {
            "alert_name": "Unknown Alert",
            "firing_count": 1,
            "description": "",
            "namespace": None,
            "is_billing": False,
            "links": {},
        }

    msg = html.unescape(str(message))

    # Extract alert name (pattern: Alert: NAME [FIRING:N])
    alert_name_match = re.search(r"Alert:\s*([^\[]+)", msg, re.IGNORECASE)
    alert_name = (
        alert_name_match.group(1).strip() if alert_name_match else "Unknown Alert"
    )

    # Extract firing count
    firing_match = re.search(r"\[FIRING:(\d+)\]", msg)
    firing_count = int(firing_match.group(1)) if firing_match else 1

    # Extract description (text after alert name)
    desc_match = re.search(r"\[FIRING:\d+\]\s*(.+?)(?:<|$)", msg, re.DOTALL)
    description = desc_match.group(1).strip()[:500] if desc_match else ""

    # Extract namespace from links or message
    ns_match = re.search(r"namespace[=:]([a-z0-9-]+)", msg, re.IGNORECASE)
    namespace = ns_match.group(1) if ns_match else None

    # Check if billing-related
    billing_keywords = [
        "billing",
        "subscription",
        "vcpu",
        "host_count",
        "infra_usage",
        "metering",
        "swatch",
        "rhsm",
    ]
    is_billing = any(kw in msg.lower() for kw in billing_keywords)

    # Extract links
    links = {}
    link_patterns = {
        "alertmanager": r'href="(https://alertmanager[^"]+)"',
        "grafana": r'href="(https://grafana[^"]+)"',
        "prometheus": r'href="(https://prometheus[^"]+)"',
        "runbook": r'href="(https://gitlab[^"]+\.rst)"',
        "console": r'href="(https://console-openshift[^"]+)"',
        "silence": r'href="(https://alertmanager[^"]+silences[^"]+)"',
    }
    for name, pattern in link_patterns.items():
        match = re.search(pattern, msg)
        if match:
            links[name] = match.group(1)

    return {
        "alert_name": alert_name,
        "firing_count": firing_count,
        "description": description,
        "namespace": namespace,
        "is_billing": is_billing,
        "links": links,
    }


def extract_billing_event_number(jira_output: str) -> int:
    """
    Extract the next billing event number from Jira search results.

    Args:
        jira_output: Raw output from jira_search for BillingEvent issues

    Returns:
        Next billing event number (highest found + 1, or 1 if none found)
    """
    if not jira_output:
        return 1

    billing_numbers = re.findall(r"BillingEvent\s*(\d+)", str(jira_output))
    if billing_numbers:
        highest = max(int(n) for n in billing_numbers)
        return highest + 1
    return 1


def parse_quay_manifest(output: str) -> Optional[Dict[str, str]]:
    """
    Parse Quay manifest output for image digest.

    Args:
        output: Raw output from quay_get_manifest or similar

    Returns:
        Dict with 'digest' (sha256 hash) and 'full_digest' (sha256:hash), or None
    """
    if not output or "not found" in output.lower():
        return None

    # Format: **Manifest Digest:** `sha256:abc123...` or sha256:abc123
    digest_match = re.search(r"sha256:([a-f0-9]{64})", str(output))
    if digest_match:
        digest = digest_match.group(1)
        return {"digest": digest, "full_digest": f"sha256:{digest}"}
    return None


def extract_ephemeral_namespace(output: str) -> Optional[str]:
    """
    Extract ephemeral namespace name from bonfire output.

    Args:
        output: Raw output from bonfire namespace commands

    Returns:
        Namespace name like 'ephemeral-abc123' or None
    """
    if not output:
        return None

    match = re.search(r"(ephemeral-[a-z0-9]+)", str(output).lower())
    return match.group(1) if match else None


def extract_git_sha(text: str) -> Optional[str]:
    """
    Extract git SHA from text (commit message, MR details, etc.).

    Args:
        text: Text containing a git SHA

    Returns:
        Git SHA (7-40 chars) or None
    """
    if not text:
        return None

    # Try with label first
    sha_match = re.search(r"SHA[:\s]+`?([a-f0-9]{7,40})`?", str(text), re.IGNORECASE)
    if sha_match:
        return sha_match.group(1)

    # Try standalone SHA
    sha_match = re.search(r"\b([a-f0-9]{40})\b", str(text))
    if sha_match:
        return sha_match.group(1)

    # Try short SHA (must be at word boundary)
    sha_match = re.search(r"\b([a-f0-9]{7,12})\b", str(text))
    if sha_match:
        return sha_match.group(1)

    return None


def parse_error_logs(logs: str, max_errors: int = 5) -> List[str]:
    """
    Extract error patterns from log output.

    Args:
        logs: Raw log output
        max_errors: Maximum number of errors to return

    Returns:
        List of error messages (truncated to 200 chars each)
    """
    if not logs:
        return []

    error_patterns = [
        r"(Error|ERROR|Exception|EXCEPTION):\s*(.+?)(?:\n|$)",
        r"(Failed|FAILED):\s*(.+?)(?:\n|$)",
        r"(Traceback|traceback)(.+?)(?:\n\n|\Z)",
    ]

    errors_found = []
    for pattern in error_patterns:
        matches = re.findall(pattern, str(logs), re.MULTILINE | re.DOTALL)
        for match in matches[:3]:  # Limit to 3 per pattern
            error_text = match[1] if isinstance(match, tuple) else match
            if len(error_text) > 20:  # Filter noise
                errors_found.append(error_text[:200])

    return errors_found[:max_errors]


def extract_version_suffix(text: str) -> Optional[int]:
    """
    Extract version number from text with -v{N} suffix.

    Args:
        text: Text like "branch-name-v3" or "release-2024-01-15-v2"

    Returns:
        Version number as int, or None if no version suffix
    """
    if not text:
        return None

    match = re.search(r"-v(\d+)$", str(text))
    return int(match.group(1)) if match else None


def get_next_version(branches: List[str], base_name: str) -> int:
    """
    Get the next version number for a branch series.

    Args:
        branches: List of existing branch names
        base_name: Base name to filter by (e.g., "aa-release-2024-01-15")

    Returns:
        Next version number (1 if no existing versions)
    """
    versions = [1]  # Default to 1 if no matches

    for branch in branches:
        if base_name in branch:
            version = extract_version_suffix(branch)
            if version:
                versions.append(version)

    return max(versions) + 1 if versions else 1


def parse_deploy_clowder_ref(
    content: str, namespace_pattern: str = "tower-analytics-prod"
) -> Optional[str]:
    """
    Extract ref SHA from deploy-clowder.yml content.

    Args:
        content: File content from deploy-clowder.yml
        namespace_pattern: Pattern to match namespace file (default: tower-analytics-prod)

    Returns:
        Git SHA reference or None
    """
    if not content:
        return None

    # Pattern: $ref: .../namespace.yml followed by ref: <sha>
    pattern = rf"\$ref:.*{namespace_pattern}\.yml\s*\n\s*ref:\s*([a-f0-9]+)"
    match = re.search(pattern, str(content))
    return match.group(1) if match else None


def update_deploy_clowder_ref(
    content: str, new_sha: str, namespace_pattern: str = "tower-analytics-prod"
) -> tuple[str, bool]:
    """
    Update ref SHA in deploy-clowder.yml content.

    Args:
        content: File content from deploy-clowder.yml
        new_sha: New SHA to set
        namespace_pattern: Pattern to match namespace file (default: tower-analytics-prod)

    Returns:
        Tuple of (updated_content, success_bool)
    """
    if not content:
        return content, False

    # Pattern: $ref: .../namespace.yml followed by ref: <sha>
    pattern = (
        rf"(\$ref:\s*/services/insights/tower-analytics/namespaces/"
        rf"{namespace_pattern}\.yml\s*\n\s*ref:\s*)([a-f0-9]+)"
    )

    new_content, count = re.subn(pattern, rf"\g<1>{new_sha}", str(content))
    return new_content, count > 0


def extract_json_from_output(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object from mixed text output.

    Args:
        text: Raw text that may contain JSON

    Returns:
        Parsed dict or None if no valid JSON found
    """
    import json

    if not text:
        return None

    json_match = re.search(r"\{.*\}", str(text), re.DOTALL)
    if json_match:
        try:
            result: Dict[str, Any] = json.loads(json_match.group())
            return result
        except json.JSONDecodeError:
            return None
    return None


def parse_alertmanager_output(text: str) -> List[Dict]:
    """
    Parse alertmanager-style output for alert details.

    Args:
        text: Raw alertmanager output text

    Returns:
        List of alert dicts with name, severity, message
    """
    if not text:
        return []

    alerts = []
    current_alert = None
    lines = str(text).split("\n")

    for line in lines:
        if "alertname" in line.lower():
            match = re.search(r"alertname[=:\s]+(\S+)", line, re.IGNORECASE)
            if match:
                if current_alert:
                    alerts.append(current_alert)
                current_alert = {"name": match.group(1), "severity": "warning"}
        if current_alert and "severity" in line.lower():
            match = re.search(r"severity[=:\s]+(\S+)", line, re.IGNORECASE)
            if match:
                current_alert["severity"] = match.group(1)
        if current_alert and (
            "message" in line.lower() or "description" in line.lower()
        ):
            current_alert["message"] = line.strip()[:100]

    if current_alert:
        alerts.append(current_alert)

    return alerts


def extract_all_jira_keys(text: str) -> List[str]:
    """
    Extract all Jira issue keys from text.

    Args:
        text: Text that may contain multiple Jira keys

    Returns:
        List of Jira keys (e.g., ["AAP-12345", "AAP-67890"])
    """
    if not text:
        return []

    return re.findall(r"([A-Z]+-\d+)", str(text))


def linkify_jira_keys(
    text: str, jira_url: Optional[str] = None, slack_format: bool = False
) -> str:
    """
    Replace Jira keys in text with markdown links.

    Handles patterns like:
    - AAP-12345 (simple key)
    - AAP-12345-description (branch-style key with suffix)

    Args:
        text: Text containing Jira keys
        jira_url: Base URL for Jira (default: from config)
        slack_format: Whether to use Slack's <URL|Text> format instead of markdown

    Returns:
        Text with Jira keys converted to markdown links
    """
    if jira_url is None:
        jira_url = get_jira_url()
    if not text:
        return text

    # Match AAP-XXXXX pattern, capturing just the key portion
    # This handles both "AAP-12345" and "AAP-12345-some-description"
    jira_pattern = re.compile(r"\b([A-Z]+-\d+)(-[\w-]+)?\b")

    def replace_jira(match: re.Match) -> str:
        key = match.group(1)  # Just the project-12345 part
        suffix = match.group(2) or ""  # Optional -description suffix
        if slack_format:
            return f"<{jira_url}/browse/{key}|{key}{suffix}>"
        return f"[{key}{suffix}]({jira_url}/browse/{key})"

    return jira_pattern.sub(replace_jira, str(text))


def find_full_conflict_marker(content: str, ours: str, theirs: str) -> Optional[str]:
    """
    Find the full conflict marker including commit ref for a given ours/theirs pair.

    Args:
        content: Full file content with conflict markers
        ours: The "ours" (HEAD) side of the conflict
        theirs: The "theirs" (incoming) side of the conflict

    Returns:
        Full conflict marker string if found, or None
    """
    if not content:
        return None

    pattern = (
        r"(<<<<<<<[^\n]*\n"
        + re.escape(ours)
        + r"=======\n"
        + re.escape(theirs)
        + r">>>>>>>[^\n]*\n?)"
    )
    match = re.search(pattern, str(content), re.DOTALL)
    return match.group(1) if match else None


def slugify_text(text: str, max_length: int = 40) -> str:
    """
    Convert text to a slug suitable for branch names.

    Args:
        text: Input text to slugify
        max_length: Maximum length of output slug

    Returns:
        Lowercase slug with only alphanumeric and hyphens
    """
    if not text:
        return ""

    slug = str(text)[:max_length].lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def find_transition_name(
    transitions_text: str, target_variations: Optional[List[str]] = None
) -> Optional[str]:
    """
    Find exact transition name from available transitions text.

    Args:
        transitions_text: Raw text of available transitions
        target_variations: List of status variations to look for (default: Done, Close, Resolve, Complete)

    Returns:
        Exact transition name if found, or None
    """
    if not transitions_text:
        return None

    if target_variations is None:
        target_variations = ["Done", "Close", "Resolve", "Complete"]

    for variation in target_variations:
        if variation.lower() in transitions_text.lower():
            # Try to extract exact transition name
            match = re.search(rf"({variation}[^,\n]*)", transitions_text, re.IGNORECASE)
            if match:
                return match.group(1).strip()

    return None
