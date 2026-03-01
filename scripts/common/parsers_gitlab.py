"""
GitLab and merge request parsers.

Functions for parsing GitLab MR list, comments, pipeline status,
and extracting MR IDs, URLs, authors, and review status.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from scripts.common.config_loader import get_gitlab_url, load_config
except ModuleNotFoundError:
    from common.config_loader import (  # type: ignore[no-redef]
        get_gitlab_url,
        load_config,
    )

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


def parse_mr_list(
    output: str, include_author: bool = False
) -> List[Dict[str, Any]]:  # noqa: C901
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
        single_match = re.search(
            r"!(\d+)\s+\S+\s+(.+?)\s*\((\w+)\)\s*←\s*\(([^)]+)\)", line
        )
        if single_match:
            mr = {
                "iid": int(single_match.group(1)),
                "id": int(single_match.group(1)),
                "title": single_match.group(2).strip()[:60],
                "target_branch": single_match.group(3).strip(),
                "branch": single_match.group(4).strip(),
            }
            if include_author:
                author_match = re.search(r"@(\w+)", line)
                if author_match:
                    mr["author"] = author_match.group(1)
            mrs.append(mr)
            continue

        single_match_no_branch = re.search(r"!(\d+)\s+\S+\s+(.+?)\s*\((\w+)\)$", line)
        if single_match_no_branch:
            mr = {
                "iid": int(single_match_no_branch.group(1)),
                "id": int(single_match_no_branch.group(1)),
                "title": single_match_no_branch.group(2).strip()[:60],
                "target_branch": single_match_no_branch.group(3).strip(),
                "branch": "",
            }
            if include_author:
                author_match = re.search(r"@(\w+)", line)
                if author_match:
                    mr["author"] = author_match.group(1)
            mrs.append(mr)
            continue

        iid_match = re.search(
            r"!(\d+)|IID[:\s]+(\d+)|mr_id[:\s]+(\d+)", line, re.IGNORECASE
        )
        if iid_match:
            if current_mr.get("iid"):
                mrs.append(current_mr)
            iid = int(iid_match.group(1) or iid_match.group(2) or iid_match.group(3))
            current_mr = {"iid": iid, "id": iid, "branch": ""}

        title_match = re.search(r"Title[:\s]+(.+)", line, re.IGNORECASE)
        if title_match and current_mr.get("iid") and not current_mr.get("title"):
            current_mr["title"] = title_match.group(1).strip()[:60]

        branch_match = re.search(r"[Ss]ource[_ ]?[Bb]ranch[:\s]+(\S+)", line)
        if branch_match and current_mr.get("iid") and not current_mr.get("branch"):
            current_mr["branch"] = branch_match.group(1).strip()

        if include_author:
            author_match = re.search(r"Author[:\s]+(\w+)|@(\w+)", line)
            if author_match and current_mr.get("iid") and not current_mr.get("author"):
                current_mr["author"] = author_match.group(1) or author_match.group(2)

    if current_mr.get("iid"):
        mrs.append(current_mr)

    seen = set()
    unique = []
    for mr in mrs:
        if mr["iid"] not in seen:
            seen.add(mr["iid"])
            unique.append(mr)

    return unique


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


def filter_human_comments(
    comments: List[Dict[str, Any]], exclude_author: Optional[str] = None
) -> List[Dict[str, Any]]:
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
        and (
            not exclude_author or c.get("author", "").lower() != exclude_author.lower()
        )
    ]


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

    if "passed" in output_lower or "success" in output_lower:
        result["status"] = "passed"
    elif "failed" in output_lower:
        result["status"] = "failed"
    elif "running" in output_lower or "pending" in output_lower:
        result["status"] = "running"
    elif "canceled" in output_lower or "cancelled" in output_lower:
        result["status"] = "canceled"

    url_match = re.search(r"(https?://[^\s]+/pipelines/\d+)", str(output))
    if url_match:
        result["url"] = url_match.group(1)

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

    try:
        data = json.loads(output)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass

    current_comment: Dict[str, Any] = {}
    for line in str(output).split("\n"):
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


def analyze_mr_status(
    details: str, my_username: Optional[str] = None
) -> Dict[str, Any]:
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

    result["is_approved"] = bool(
        re.search(r"approved|LGTM|:white_check_mark:|✅", details, re.IGNORECASE)
    )

    result["has_conflicts"] = bool(
        re.search(
            r"cannot be merged|has conflicts|merge conflicts?|needs rebase|unable to merge",
            details,
            re.IGNORECASE,
        )
    )

    has_merge_commits = bool(
        re.search(r"merge branch|merge.*into|merge commit", details, re.IGNORECASE)
    )
    result["needs_rebase"] = result["has_conflicts"] or has_merge_commits

    result["pipeline_failed"] = bool(
        re.search(r"pipeline.*failed|CI.*failed|build.*failed", details, re.IGNORECASE)
    )

    result["unresolved"] = bool(
        re.search(
            r"unresolved|open discussion|needs work|request.*change",
            details,
            re.IGNORECASE,
        )
    )

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


def separate_mrs_by_author(
    mrs: List[Dict[str, Any]], my_username: str
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Separate MRs into own MRs and MRs to review (by others).

    Args:
        mrs: List of MR dicts (must include 'author' key)
        my_username: Current user's username

    Returns:
        Dict with 'my_mrs' and 'to_review' lists
    """
    my_mrs = []
    to_review = []

    my_identities = {my_username.lower()}

    try:
        config = load_config()
        user_config = config.get("user", {})

        for key in ["username", "gitlab_username", "jira_username"]:
            if user_config.get(key):
                my_identities.add(user_config[key].lower())

        if user_config.get("email"):
            my_identities.add(user_config["email"].lower())
            email_user = user_config["email"].split("@")[0].lower()
            my_identities.add(email_user)

        for alias in user_config.get("email_aliases", []):
            my_identities.add(alias.lower())
            alias_user = alias.split("@")[0].lower()
            my_identities.add(alias_user)

        if user_config.get("full_name"):
            full_name = user_config["full_name"].lower()
            my_identities.add(full_name)
            my_identities.add(full_name.replace("'", ""))
            my_identities.add(full_name.replace(" ", "_"))
    except Exception as e:
        logger.debug(f"Suppressed error in separate_mrs_by_author: {e}")

    for mr in mrs:
        author = (mr.get("author", "") or "").lower()
        is_mine = any(
            identity in author or author == identity for identity in my_identities
        )
        if is_mine:
            my_mrs.append(mr)
        else:
            to_review.append(mr)

    return {"my_mrs": my_mrs, "to_review": to_review}


def extract_web_url(text: str, pattern: Optional[str] = None) -> Optional[str]:
    """
    Extract a URL from text.

    Args:
        text: Text to search for URLs
        pattern: Optional regex pattern to match specific URLs.
                 Default matches any https:// URL.

    Returns:
        First matching URL, or None if not found
    """
    if not text:
        return None

    if pattern:
        url_pattern = rf"(https://\S*{pattern}\S*)"
    else:
        url_pattern = r"(https://\S+)"

    match = re.search(url_pattern, str(text))
    if match:
        url = match.group(1)
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

    match = re.search(
        r"!(\d+)|IID[:\s]+(\d+)|mr_id[:\s]+(\d+)", str(text), re.IGNORECASE
    )
    if match:
        return int(match.group(1) or match.group(2) or match.group(3))

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


def linkify_mr_ids(
    text: str,
    project_path: str = "automation-analytics/automation-analytics-backend",
    slack_format: bool = False,
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

    base_url = f"{get_gitlab_url()}/{project_path}/-/merge_requests"

    mr_pattern = re.compile(r"!(\d+)")

    def replace_mr(match: re.Match) -> str:
        mr_id = match.group(1)
        url = f"{base_url}/{mr_id}"
        if slack_format:
            return f"<{url}|!{mr_id}>"
        return f"[!{mr_id}]({url})"

    return mr_pattern.sub(replace_mr, str(text))


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

    comment_blocks = re.split(
        r"\n(\w+) commented (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", str(text)
    )

    comments = []
    idx = 1
    while idx < len(comment_blocks) - 1:
        author = comment_blocks[idx]
        timestamp_str = comment_blocks[idx + 1]

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


def analyze_review_status(
    details: str, reviewer_username: str, author: str = ""
) -> Dict:
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

    my_comments = re.findall(
        rf"({reviewer_username}).*?commented|reviewed by.*?({reviewer_username})",
        details,
        re.IGNORECASE,
    )
    my_feedback_exists = len(my_comments) > 0

    author_replied = False
    if author:
        author_replied = bool(
            re.search(rf"{author}.*?commented|replied", details, re.IGNORECASE)
        )

    already_approved = bool(
        re.search(
            rf"approved by.*?{reviewer_username}|LGTM|Looks good",
            details,
            re.IGNORECASE,
        )
    )

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


__all__ = [
    "analyze_mr_status",
    "analyze_review_status",
    "BOT_PATTERNS",
    "extract_author_from_mr",
    "extract_branch_from_mr",
    "extract_mr_id_from_text",
    "extract_mr_id_from_url",
    "extract_mr_url",
    "extract_web_url",
    "filter_human_comments",
    "is_bot_comment",
    "linkify_mr_ids",
    "parse_mr_comments",
    "parse_mr_list",
    "parse_pipeline_status",
    "separate_mrs_by_author",
    "split_mr_comments",
]
