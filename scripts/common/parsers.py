"""
Common parsers for MCP tool output.
These functions are used by multiple skills to avoid code duplication.
"""

import re
from typing import Any, Dict, List, Optional

from scripts.common.config_loader import get_jira_url

# Bot patterns for filtering out non-human comments
BOT_PATTERNS = [
    r"group_\d+_bot",
    r"konflux",
    r"Starting Pipelinerun",
    r"stone-prod",
    r"tkn pr logs",
    r"Integration test for component",
    r"aap-aa-on-pull-request",
    r"^/retest",
    r"^/approve",
]


def parse_mr_list(output: str, include_author: bool = False) -> List[Dict[str, Any]]:  # noqa: C901
    """
    Parse gitlab_mr_list output into structured MR data.

    Handles multiple output formats:
    - Single line: "!1452  project!1452  AAP-58394 - feat... (main) ← (branch-name)"
    - Multi-line with IID, Title, Author on separate lines

    Args:
        output: Raw output from glab mr list
        include_author: Whether to extract author from output

    Returns:
        List of dicts with 'iid' (or 'id'), 'title', 'branch', and optionally 'author' keys
    """
    mrs: List[Dict[str, Any]] = []
    if not output:
        return mrs

    lines = str(output).split("\n")
    current_mr: Dict[str, Any] = {}

    for line in lines:
        # Try single-line format first: "!1452  project!1452  Title (main) ← (branch-name)"
        # The branch is in the format: (target) ← (source)
        single_match = re.search(r"!(\d+)\s+\S+\s+(.+?)\s*\(main\)\s*←\s*\(([^)]+)\)", line)
        if single_match:
            mr = {
                "iid": int(single_match.group(1)),
                "id": int(single_match.group(1)),  # Alias for compatibility
                "title": single_match.group(2).strip()[:60],
                "branch": single_match.group(3).strip(),
            }
            if include_author:
                author_match = re.search(r"@(\w+)", line)
                if author_match:
                    mr["author"] = author_match.group(1)
            mrs.append(mr)
            continue

        # Fallback: Try without branch info (older format)
        single_match_no_branch = re.search(r"!(\d+)\s+\S+\s+(.+?)\s*\(main\)", line)
        if single_match_no_branch:
            mr = {
                "iid": int(single_match_no_branch.group(1)),
                "id": int(single_match_no_branch.group(1)),  # Alias for compatibility
                "title": single_match_no_branch.group(2).strip()[:60],
                "branch": "",  # No branch info available
            }
            if include_author:
                author_match = re.search(r"@(\w+)", line)
                if author_match:
                    mr["author"] = author_match.group(1)
            mrs.append(mr)
            continue

        # Multi-line format: Look for IID pattern
        iid_match = re.search(r"!(\d+)|IID[:\s]+(\d+)|mr_id[:\s]+(\d+)", line, re.IGNORECASE)
        if iid_match:
            # Save previous MR if exists
            if current_mr.get("iid"):
                mrs.append(current_mr)
            iid = int(iid_match.group(1) or iid_match.group(2) or iid_match.group(3))
            current_mr = {"iid": iid, "id": iid, "branch": ""}  # Both for compatibility

        # Extract title
        title_match = re.search(r"Title[:\s]+(.+)", line, re.IGNORECASE)
        if title_match and current_mr.get("iid") and not current_mr.get("title"):
            current_mr["title"] = title_match.group(1).strip()[:60]

        # Extract source branch
        branch_match = re.search(r"[Ss]ource[_ ]?[Bb]ranch[:\s]+(\S+)", line)
        if branch_match and current_mr.get("iid") and not current_mr.get("branch"):
            current_mr["branch"] = branch_match.group(1).strip()

        # Extract author if requested
        if include_author:
            author_match = re.search(r"Author[:\s]+(\w+)|@(\w+)", line)
            if author_match and current_mr.get("iid") and not current_mr.get("author"):
                current_mr["author"] = author_match.group(1) or author_match.group(2)

    # Don't forget the last one
    if current_mr.get("iid"):
        mrs.append(current_mr)

    # Deduplicate by IID
    seen = set()
    unique = []
    for mr in mrs:
        if mr["iid"] not in seen:
            seen.add(mr["iid"])
            unique.append(mr)

    return unique


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
            namespaces.append({"name": match.group(1), "expires": match.group(2).strip()})
        elif "ephemeral-" in line:
            # Fallback: just get the namespace name
            ns_match = re.search(r"(ephemeral-\w+)", line)
            if ns_match:
                namespaces.append({"name": ns_match.group(1), "expires": "unknown"})
    return namespaces


def is_bot_comment(text: str, author: str = "") -> bool:
    """
    Check if a comment appears to be from a bot.

    Args:
        text: Comment text
        author: Comment author name (optional)

    Returns:
        True if comment appears to be from a bot
    """
    combined = f"{author} {text}"
    return any(re.search(pattern, combined, re.IGNORECASE) for pattern in BOT_PATTERNS)


def filter_human_comments(comments: List[Dict[str, Any]], exclude_author: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Filter out bot comments and optionally exclude a specific author.

    Args:
        comments: List of comment dicts with 'author' and 'text' keys
        exclude_author: Author to exclude (e.g., current user)

    Returns:
        Filtered list of human comments
    """
    return [
        c
        for c in comments
        if not is_bot_comment(c.get("text", ""), c.get("author", ""))
        and (not exclude_author or c.get("author", "").lower() != exclude_author.lower())
    ]


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
            commits.append({"sha": md_match.group(1)[:7], "message": md_match.group(2)[:60]})
            continue

        # Standard git log --oneline format: "abc1234 commit message"
        parts = line.split(" ", 1)
        if len(parts) >= 1 and re.match(r"^[a-f0-9]{7,}$", parts[0]):
            commits.append({"sha": parts[0][:7], "message": parts[1] if len(parts) > 1 else ""})
    return commits


def parse_git_branches(output: str, issue_key: Optional[str] = None) -> List[str]:
    """
    Parse git branch output into branch names.

    Args:
        output: Raw output from git branch -a
        issue_key: Optional issue key to filter branches

    Returns:
        List of branch names (cleaned)
    """
    branches: List[str] = []
    if not output:
        return branches

    for line in str(output).split("\n"):
        # Clean the branch name
        branch = line.strip().replace("* ", "").replace("remotes/origin/", "")
        if not branch or branch in ["main", "master", "HEAD"]:
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
            pod["healthy"] = pod["status"] == "Running" and pod["ready"].split("/")[0] == pod["ready"].split("/")[1]
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
                conflicts.append({"file": match.group(1).strip(), "type": "both modified"})
        elif "both added" in line.lower():
            match = re.search(r":\s*(.+)$", line)
            if match:
                conflicts.append({"file": match.group(1).strip(), "type": "both added"})

    return conflicts


def parse_pipeline_status(output: str) -> Dict[str, Any]:
    """
    Parse GitLab CI pipeline status output.

    Args:
        output: Raw output from glab ci status or gitlab_ci_status

    Returns:
        Dict with 'status', 'url', 'jobs' keys
    """
    result: Dict[str, Any] = {
        "status": "unknown",
        "url": None,
        "jobs": [],
        "failed_jobs": [],
    }

    if not output:
        return result

    output_lower = str(output).lower()

    # Determine overall status
    if "passed" in output_lower or "success" in output_lower:
        result["status"] = "passed"
    elif "failed" in output_lower:
        result["status"] = "failed"
    elif "running" in output_lower or "pending" in output_lower:
        result["status"] = "running"
    elif "canceled" in output_lower or "cancelled" in output_lower:
        result["status"] = "canceled"

    # Extract URL if present
    url_match = re.search(r"(https?://[^\s]+/pipelines/\d+)", str(output))
    if url_match:
        result["url"] = url_match.group(1)

    # Extract failed jobs
    for line in str(output).split("\n"):
        if "failed" in line.lower() and ":" in line:
            job_match = re.match(r"(\w[\w-]+):\s*failed", line.strip(), re.IGNORECASE)
            if job_match:
                result["failed_jobs"].append(job_match.group(1))

    return result


def parse_mr_comments(output: str) -> List[Dict[str, Any]]:
    """
    Parse GitLab MR comments output.

    Args:
        output: Raw output from gitlab_mr_comments or glab mr view --comments

    Returns:
        List of dicts with 'author', 'text', 'date' keys
    """
    comments: List[Dict[str, Any]] = []
    if not output:
        return comments

    # Try JSON format first
    try:
        import json

        data = json.loads(output)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    # Parse text format
    current_comment: Dict[str, Any] = {}
    for line in str(output).split("\n"):
        # Author line: "@username commented 2 days ago"
        author_match = re.match(r"@(\w+)\s+commented\s+(.+)", line)
        if author_match:
            if current_comment:
                comments.append(current_comment)
            current_comment = {
                "author": author_match.group(1),
                "date": author_match.group(2),
                "text": "",
            }
        elif current_comment and line.strip():
            current_comment["text"] += line.strip() + " "

    if current_comment:
        comments.append(current_comment)

    return comments


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


def analyze_mr_status(details: str, my_username: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze MR details for approval status, conflicts, pipeline, and feedback.

    Args:
        details: Raw MR details output from gitlab_mr_view
        my_username: Current user's username (to filter own comments)

    Returns:
        Dict with status analysis including:
        - is_approved: bool
        - has_conflicts: bool
        - needs_rebase: bool
        - pipeline_failed: bool
        - has_feedback: bool
        - reviewers: list of usernames who commented
        - unresolved: bool (has unresolved discussions)
        - status: string ('approved', 'needs_response', 'needs_rebase', etc)
        - action: string (suggested action)
    """
    details = str(details) if details else ""

    result = {
        "is_approved": False,
        "has_conflicts": False,
        "needs_rebase": False,
        "pipeline_failed": False,
        "has_feedback": False,
        "reviewers": [],
        "unresolved": False,
        "status": "awaiting_review",
        "action": "Waiting for reviewers",
    }

    # Check approval status
    result["is_approved"] = bool(re.search(r"approved|LGTM|:white_check_mark:|✅", details, re.IGNORECASE))

    # Check for merge conflicts
    result["has_conflicts"] = bool(
        re.search(
            r"cannot be merged|has conflicts|merge conflicts?|needs rebase|unable to merge",
            details,
            re.IGNORECASE,
        )
    )

    # Check for merge commits (should rebase)
    has_merge_commits = bool(re.search(r"merge branch|merge.*into|merge commit", details, re.IGNORECASE))
    result["needs_rebase"] = result["has_conflicts"] or has_merge_commits

    # Check pipeline status
    result["pipeline_failed"] = bool(re.search(r"pipeline.*failed|CI.*failed|build.*failed", details, re.IGNORECASE))

    # Check for unresolved discussions
    result["unresolved"] = bool(
        re.search(r"unresolved|open discussion|needs work|request.*change", details, re.IGNORECASE)
    )

    # Look for reviewer comments (not from me)
    comment_patterns = [
        r"(\w+)\s+commented",
        r"Review by\s+(\w+)",
        r"@(\w+)\s+:",
        r"Feedback from\s+(\w+)",
    ]

    my_user = (my_username or "").lower()
    reviewers = set()
    for pattern in comment_patterns:
        matches = re.findall(pattern, details, re.IGNORECASE)
        for match in matches:
            if match.lower() != my_user:
                reviewers.add(match)

    result["reviewers"] = list(reviewers)
    result["has_feedback"] = len(reviewers) > 0

    # Determine status
    if result["has_conflicts"]:
        result["status"] = "needs_rebase"
        result["action"] = "Has merge conflicts - needs rebase"
    elif result["is_approved"] and not result["unresolved"]:
        result["status"] = "approved"
        result["action"] = "Ready to merge!"
    elif result["unresolved"] or (result["has_feedback"] and not result["is_approved"]):
        result["status"] = "needs_response"
        result["action"] = "Reviewer feedback needs your response"
    elif result["pipeline_failed"]:
        result["status"] = "pipeline_failed"
        result["action"] = "Fix pipeline before review"
    elif has_merge_commits:
        result["status"] = "needs_rebase"
        result["action"] = "Has merge commits - consider rebasing"
    else:
        result["status"] = "awaiting_review"
        result["action"] = "Waiting for reviewers"

    return result


def separate_mrs_by_author(mrs: List[Dict[str, Any]], my_username: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Separate MRs into own MRs and MRs to review (by others).

    Args:
        mrs: List of MR dicts (must include 'author' key)
        my_username: Current user's username

    Returns:
        Dict with 'my_mrs' and 'to_review' lists
    """
    from scripts.common.config_loader import load_config

    my_mrs = []
    to_review = []

    # Build list of all user identities to check against
    my_identities = {my_username.lower()}

    # Load additional identities from config
    try:
        config = load_config()
        user_config = config.get("user", {})

        # Add all configured usernames
        for key in ["username", "gitlab_username", "jira_username"]:
            if user_config.get(key):
                my_identities.add(user_config[key].lower())

        # Add email and email aliases
        if user_config.get("email"):
            my_identities.add(user_config["email"].lower())
            # Also add the username part of the email
            email_user = user_config["email"].split("@")[0].lower()
            my_identities.add(email_user)

        for alias in user_config.get("email_aliases", []):
            my_identities.add(alias.lower())
            # Also add the username part of each alias
            alias_user = alias.split("@")[0].lower()
            my_identities.add(alias_user)

        # Add full name variations
        if user_config.get("full_name"):
            full_name = user_config["full_name"].lower()
            my_identities.add(full_name)
            # Also add without apostrophe and with underscores
            my_identities.add(full_name.replace("'", ""))
            my_identities.add(full_name.replace(" ", "_"))
    except Exception:
        pass  # Fall back to just my_username

    for mr in mrs:
        author = (mr.get("author", "") or "").lower()
        # Check if author matches any of our identities
        is_mine = any(identity in author or author == identity for identity in my_identities)
        if is_mine:
            my_mrs.append(mr)
        else:
            to_review.append(mr)

    return {"my_mrs": my_mrs, "to_review": to_review}


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


def extract_web_url(text: str, pattern: Optional[str] = None) -> Optional[str]:
    """
    Extract a URL from text.

    Args:
        text: Text to search for URLs
        pattern: Optional regex pattern to match specific URLs.
                 Default matches any https:// URL.

    Returns:
        First matching URL, or None if not found

    Examples:
        >>> extract_web_url("Check out https://example.com/page")
        'https://example.com/page'
        >>> extract_web_url("MR at https://gitlab.com/org/repo/-/merge_requests/123", r'merge_requests/\\d+')
        'https://gitlab.com/org/repo/-/merge_requests/123'
    """
    if not text:
        return None

    # Build pattern - match URLs, optionally containing a specific pattern
    if pattern:
        url_pattern = rf"(https://\S*{pattern}\S*)"
    else:
        url_pattern = r"(https://\S+)"

    match = re.search(url_pattern, str(text))
    if match:
        url = match.group(1)
        # Clean up trailing punctuation that might be captured
        url = url.rstrip(".,;:'\")")
        return url
    return None


def extract_mr_url(text: str) -> Optional[str]:
    """
    Extract a GitLab merge request URL from text.

    Args:
        text: Text to search for MR URLs

    Returns:
        First MR URL found, or None
    """
    return extract_web_url(text, r"merge_requests/\d+")


def extract_mr_id_from_url(url: str) -> Optional[Dict[str, Any]]:
    """
    Extract project and MR ID from a GitLab MR URL.

    Args:
        url: GitLab MR URL like "https://gitlab.com/group/project/-/merge_requests/123"

    Returns:
        Dict with 'project' and 'mr_id' keys, or None if not a valid URL
    """
    if not url:
        return None

    match = re.match(r"https?://[^/]+/(.+?)/-/merge_requests/(\d+)", str(url))
    if match:
        return {"project": match.group(1), "mr_id": int(match.group(2))}
    return None


def extract_mr_id_from_text(text: str) -> Optional[int]:
    """
    Extract MR ID from text containing patterns like !123, IID: 123, etc.

    Args:
        text: Text to search for MR ID

    Returns:
        MR ID as integer, or None if not found
    """
    if not text:
        return None

    # Try common patterns
    match = re.search(r"!(\d+)|IID[:\s]+(\d+)|mr_id[:\s]+(\d+)", str(text), re.IGNORECASE)
    if match:
        return int(match.group(1) or match.group(2) or match.group(3))

    # Fallback: find any 2-5 digit number
    nums = re.findall(r"\b(\d{2,5})\b", str(text))
    if nums:
        return int(nums[0])

    return None


def extract_branch_from_mr(mr_details: str) -> Optional[str]:
    """
    Extract source branch name from MR details output.

    Args:
        mr_details: Raw output from gitlab_mr_view

    Returns:
        Source branch name or None
    """
    if not mr_details:
        return None

    # Try various patterns
    patterns = [
        r"[Ss]ource[_ ]?[Bb]ranch[:\s]+(\S+)",
        r"source_branch.*?[:\s]+(\S+)",
        r"Branch:\s*(\S+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, str(mr_details), re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def extract_author_from_mr(mr_details: str) -> Optional[str]:
    """
    Extract author username from MR details output.

    Args:
        mr_details: Raw output from gitlab_mr_view

    Returns:
        Author username or None
    """
    if not mr_details:
        return None

    match = re.search(r"Author[:\s]+@?(\w+)", str(mr_details), re.IGNORECASE)
    return match.group(1) if match else None


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
    conflict_files = re.findall(r"CONFLICT \([^)]+\):\s*(?:Merge conflict in\s*)?(\S+)", str(output))
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
    alert_name = alert_name_match.group(1).strip() if alert_name_match else "Unknown Alert"

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


def parse_deploy_clowder_ref(content: str, namespace_pattern: str = "tower-analytics-prod") -> Optional[str]:
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
        if current_alert and ("message" in line.lower() or "description" in line.lower()):
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


def linkify_jira_keys(text: str, jira_url: Optional[str] = None, slack_format: bool = False) -> str:
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


def linkify_mr_ids(
    text: str, project_path: str = "automation-analytics/automation-analytics-backend", slack_format: bool = False
) -> str:
    """
    Replace MR IDs (!123) in text with markdown links.

    Args:
        text: Text containing MR IDs
        project_path: GitLab project path
        slack_format: Whether to use Slack link format

    Returns:
        Text with MR IDs converted to links
    """
    if not text:
        return text

    from scripts.common.config_loader import get_gitlab_url

    base_url = f"{get_gitlab_url()}/{project_path}/-/merge_requests"

    # Match !123 pattern
    mr_pattern = re.compile(r"!(\d+)")

    def replace_mr(match: re.Match) -> str:
        mr_id = match.group(1)
        url = f"{base_url}/{mr_id}"
        if slack_format:
            return f"<{url}|!{mr_id}>"
        return f"[!{mr_id}]({url})"

    return mr_pattern.sub(replace_mr, str(text))


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

    pattern = r"(<<<<<<<[^\n]*\n" + re.escape(ours) + r"=======\n" + re.escape(theirs) + r">>>>>>>[^\n]*\n?)"
    match = re.search(pattern, str(content), re.DOTALL)
    return match.group(1) if match else None


def split_mr_comments(text: str) -> List[tuple]:
    """
    Split MR comments text into structured comment blocks.

    Args:
        text: Raw comments text in format "username commented YYYY-MM-DD HH:MM:SS...\ncomment text"

    Returns:
        List of tuples: [(author, timestamp_str, comment_text), ...]
    """
    if not text:
        return []

    # Split on comment header pattern
    comment_blocks = re.split(r"\n(\w+) commented (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", str(text))

    comments = []
    idx = 1
    while idx < len(comment_blocks) - 1:
        author = comment_blocks[idx]
        timestamp_str = comment_blocks[idx + 1]

        # Get the comment text (next block until next comment)
        if idx + 2 < len(comment_blocks):
            comment_text = (
                comment_blocks[idx + 2].split("\n\n")[0]
                if "\n\n" in comment_blocks[idx + 2]
                else comment_blocks[idx + 2]
            )
        else:
            comment_text = ""

        comments.append((author, timestamp_str, comment_text.strip()))
        idx += 3

    return comments


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


def find_transition_name(transitions_text: str, target_variations: Optional[List[str]] = None) -> Optional[str]:
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


def analyze_review_status(details: str, reviewer_username: str, author: str = "") -> Dict:
    """
    Analyze MR details to determine review workflow status.

    Args:
        details: Raw MR details text
        reviewer_username: Username of the reviewer
        author: Username of the MR author (optional)

    Returns:
        Dict with review status analysis:
        - my_feedback_exists: bool
        - author_replied: bool
        - already_approved: bool
        - recommended_action: str
        - reason: str
    """
    if not details or not reviewer_username:
        return {
            "my_feedback_exists": False,
            "author_replied": False,
            "already_approved": False,
            "recommended_action": "needs_full_review",
            "reason": "No details available",
        }

    # Look for reviewer's previous comments/feedback
    my_comments = re.findall(
        rf"({reviewer_username}).*?commented|reviewed by.*?({reviewer_username})",
        details,
        re.IGNORECASE,
    )
    my_feedback_exists = len(my_comments) > 0

    # Look for author's replies after feedback
    author_replied = False
    if author:
        author_replied = bool(re.search(rf"{author}.*?commented|replied", details, re.IGNORECASE))

    # Check if already approved
    already_approved = bool(re.search(rf"approved by.*?{reviewer_username}|LGTM|Looks good", details, re.IGNORECASE))

    # Determine recommended action
    if already_approved:
        action = "skip"
        reason = "Already approved"
    elif not my_feedback_exists:
        action = "needs_full_review"
        reason = "No previous review from me"
    elif my_feedback_exists and not author_replied:
        action = "skip"
        reason = "Waiting for author response"
    elif my_feedback_exists and author_replied:
        action = "needs_followup"
        reason = "Author replied, check if issues resolved"
    else:
        action = "needs_full_review"
        reason = "Unclear status"

    return {
        "my_feedback_exists": my_feedback_exists,
        "author_replied": author_replied,
        "already_approved": already_approved,
        "recommended_action": action,
        "reason": reason,
    }
