"""
Common parsers for MCP tool output.
These functions are used by multiple skills to avoid code duplication.
"""
import re
from typing import List, Dict, Any, Optional


# Bot patterns for filtering out non-human comments
BOT_PATTERNS = [
    r'group_\d+_bot',
    r'konflux',
    r'Starting Pipelinerun',
    r'stone-prod',
    r'tkn pr logs',
    r'Integration test for component',
    r'aap-aa-on-pull-request',
    r'^/retest',
    r'^/approve',
]


def parse_mr_list(output: str, include_author: bool = False) -> List[Dict[str, Any]]:
    """
    Parse gitlab_mr_list output into structured MR data.
    
    Handles multiple output formats:
    - Single line: "!1452  project!1452  AAP-58394 - feat... (main)"
    - Multi-line with IID, Title, Author on separate lines
    
    Args:
        output: Raw output from glab mr list
        include_author: Whether to extract author from output
        
    Returns:
        List of dicts with 'iid' (or 'id'), 'title', and optionally 'author' keys
    """
    mrs = []
    if not output:
        return mrs
    
    lines = str(output).split('\n')
    current_mr = {}
    
    for line in lines:
        # Try single-line format first: "!1452  project!1452  Title (main)"
        single_match = re.search(r'!(\d+)\s+\S+\s+(.+?)\s*\(main\)', line)
        if single_match:
            mr = {
                "iid": int(single_match.group(1)),
                "id": int(single_match.group(1)),  # Alias for compatibility
                "title": single_match.group(2).strip()[:60]
            }
            if include_author:
                author_match = re.search(r'@(\w+)', line)
                if author_match:
                    mr["author"] = author_match.group(1)
            mrs.append(mr)
            continue
        
        # Multi-line format: Look for IID pattern
        iid_match = re.search(r'!(\d+)|IID[:\s]+(\d+)|mr_id[:\s]+(\d+)', line, re.IGNORECASE)
        if iid_match:
            # Save previous MR if exists
            if current_mr.get('iid'):
                mrs.append(current_mr)
            iid = int(iid_match.group(1) or iid_match.group(2) or iid_match.group(3))
            current_mr = {'iid': iid, 'id': iid}  # Both for compatibility
        
        # Extract title
        title_match = re.search(r'Title[:\s]+(.+)', line, re.IGNORECASE)
        if title_match and current_mr.get('iid') and not current_mr.get('title'):
            current_mr['title'] = title_match.group(1).strip()[:60]
        
        # Extract author if requested
        if include_author:
            author_match = re.search(r'Author[:\s]+(\w+)|@(\w+)', line)
            if author_match and current_mr.get('iid') and not current_mr.get('author'):
                current_mr['author'] = author_match.group(1) or author_match.group(2)
    
    # Don't forget the last one
    if current_mr.get('iid'):
        mrs.append(current_mr)
    
    # Deduplicate by IID
    seen = set()
    unique = []
    for mr in mrs:
        if mr['iid'] not in seen:
            seen.add(mr['iid'])
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
    issues = []
    if not output:
        return issues
        
    for line in str(output).split('\n'):
        # Parse: AAP-12345  Summary text or AAP-12345: Summary text
        match = re.match(r'(AAP-\d+)[:\s]+(.+)', line)
        if match:
            issues.append({
                "key": match.group(1),
                "summary": match.group(2)[:50]
            })
    return issues


def parse_namespaces(output: str) -> List[Dict[str, str]]:
    """
    Parse bonfire namespace list output.
    
    Args:
        output: Raw output from bonfire namespace list
        
    Returns:
        List of dicts with 'name' and 'expires' keys
    """
    namespaces = []
    if not output:
        return namespaces
        
    for line in str(output).split('\n'):
        # Parse: ephemeral-xxxxx  expires in 2h 30m
        match = re.search(r'(ephemeral-\w+)\s+.*?(\d+[hm].*?)(?:\s|$)', line)
        if match:
            namespaces.append({
                "name": match.group(1),
                "expires": match.group(2).strip()
            })
        elif 'ephemeral-' in line:
            # Fallback: just get the namespace name
            ns_match = re.search(r'(ephemeral-\w+)', line)
            if ns_match:
                namespaces.append({
                    "name": ns_match.group(1),
                    "expires": "unknown"
                })
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


def filter_human_comments(
    comments: List[Dict[str, Any]], 
    exclude_author: Optional[str] = None
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
        c for c in comments
        if not is_bot_comment(c.get('text', ''), c.get('author', ''))
        and (not exclude_author or c.get('author', '').lower() != exclude_author.lower())
    ]


def parse_git_log(output: str) -> List[Dict[str, str]]:
    """
    Parse git log --oneline output into structured commit data.
    
    Args:
        output: Raw output from git log --oneline or similar
        
    Returns:
        List of dicts with 'sha' and 'message' keys
    """
    commits = []
    if not output:
        return commits
        
    for line in str(output).strip().split('\n'):
        line = line.strip()
        if not line:
            continue
            
        # Handle markdown formatted output like "- `abc1234 commit message`"
        md_match = re.search(r'`([a-f0-9]{7,})\s+(.+?)`', line)
        if md_match:
            commits.append({
                "sha": md_match.group(1)[:7],
                "message": md_match.group(2)[:60]
            })
            continue
            
        # Standard git log --oneline format: "abc1234 commit message"
        parts = line.split(' ', 1)
        if len(parts) >= 1 and re.match(r'^[a-f0-9]{7,}$', parts[0]):
            commits.append({
                "sha": parts[0][:7],
                "message": parts[1] if len(parts) > 1 else ""
            })
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
    branches = []
    if not output:
        return branches
        
    for line in str(output).split('\n'):
        # Clean the branch name
        branch = line.strip().replace('* ', '').replace('remotes/origin/', '')
        if not branch or branch in ['main', 'master', 'HEAD']:
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
    pods = []
    if not output:
        return pods
        
    for line in str(output).split('\n'):
        if not line.strip() or line.startswith('NAME'):
            continue
            
        parts = line.split()
        if len(parts) >= 3:
            pod = {
                "name": parts[0],
                "ready": parts[1] if len(parts) > 1 else "?/?",
                "status": parts[2] if len(parts) > 2 else "Unknown",
                "restarts": parts[3] if len(parts) > 3 else "0",
                "age": parts[4] if len(parts) > 4 else "?"
            }
            
            # Mark health status
            pod["healthy"] = pod["status"] == "Running" and pod["ready"].split('/')[0] == pod["ready"].split('/')[1]
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
    return [b for b in branches if b not in ['main', 'master', 'develop']][:5]


def parse_git_conflicts(status_output: str) -> List[Dict[str, str]]:
    """
    Parse git status output for merge/rebase conflicts.
    
    Args:
        status_output: Raw output from git status or git status --porcelain
        
    Returns:
        List of dicts with 'file' and 'type' keys
    """
    conflicts = []
    if not status_output:
        return conflicts
        
    for line in str(status_output).split('\n'):
        line = line.strip()
        if not line:
            continue
            
        # Porcelain format: "UU file.py" or "AA file.py"
        if line.startswith('UU ') or line.startswith('AA '):
            conflicts.append({
                "file": line[3:],
                "type": "both modified" if line.startswith('UU') else "both added"
            })
        # Human readable: "both modified: file.py"
        elif 'both modified' in line.lower():
            match = re.search(r':\s*(.+)$', line)
            if match:
                conflicts.append({
                    "file": match.group(1).strip(),
                    "type": "both modified"
                })
        elif 'both added' in line.lower():
            match = re.search(r':\s*(.+)$', line)
            if match:
                conflicts.append({
                    "file": match.group(1).strip(),
                    "type": "both added"
                })
                
    return conflicts


def parse_pipeline_status(output: str) -> Dict[str, Any]:
    """
    Parse GitLab CI pipeline status output.
    
    Args:
        output: Raw output from glab ci status or gitlab_ci_status
        
    Returns:
        Dict with 'status', 'url', 'jobs' keys
    """
    result = {
        "status": "unknown",
        "url": None,
        "jobs": [],
        "failed_jobs": [],
    }
    
    if not output:
        return result
        
    output_lower = str(output).lower()
    
    # Determine overall status
    if 'passed' in output_lower or 'success' in output_lower:
        result["status"] = "passed"
    elif 'failed' in output_lower:
        result["status"] = "failed"
    elif 'running' in output_lower or 'pending' in output_lower:
        result["status"] = "running"
    elif 'canceled' in output_lower or 'cancelled' in output_lower:
        result["status"] = "canceled"
        
    # Extract URL if present
    url_match = re.search(r'(https?://[^\s]+/pipelines/\d+)', str(output))
    if url_match:
        result["url"] = url_match.group(1)
        
    # Extract failed jobs
    for line in str(output).split('\n'):
        if 'failed' in line.lower() and ':' in line:
            job_match = re.match(r'(\w[\w-]+):\s*failed', line.strip(), re.IGNORECASE)
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
    comments = []
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
    current_comment = {}
    for line in str(output).split('\n'):
        # Author line: "@username commented 2 days ago"
        author_match = re.match(r'@(\w+)\s+commented\s+(.+)', line)
        if author_match:
            if current_comment:
                comments.append(current_comment)
            current_comment = {
                "author": author_match.group(1),
                "date": author_match.group(2),
                "text": ""
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
        
    match = re.search(r'\b([A-Z]{2,10}-\d+)\b', str(text))
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
        "action": "Waiting for reviewers"
    }
    
    # Check approval status
    result["is_approved"] = bool(re.search(
        r'approved|LGTM|:white_check_mark:|✅', 
        details, re.IGNORECASE
    ))
    
    # Check for merge conflicts
    result["has_conflicts"] = bool(re.search(
        r'cannot be merged|has conflicts|merge conflicts?|needs rebase|unable to merge',
        details, re.IGNORECASE
    ))
    
    # Check for merge commits (should rebase)
    has_merge_commits = bool(re.search(
        r'merge branch|merge.*into|merge commit', 
        details, re.IGNORECASE
    ))
    result["needs_rebase"] = result["has_conflicts"] or has_merge_commits
    
    # Check pipeline status
    result["pipeline_failed"] = bool(re.search(
        r'pipeline.*failed|CI.*failed|build.*failed', 
        details, re.IGNORECASE
    ))
    
    # Check for unresolved discussions
    result["unresolved"] = bool(re.search(
        r'unresolved|open discussion|needs work|request.*change', 
        details, re.IGNORECASE
    ))
    
    # Look for reviewer comments (not from me)
    comment_patterns = [
        r'(\w+)\s+commented',
        r'Review by\s+(\w+)',
        r'@(\w+)\s+:',
        r'Feedback from\s+(\w+)',
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


def separate_mrs_by_author(
    mrs: List[Dict[str, Any]], 
    my_username: str
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
    my_user = my_username.lower()
    
    for mr in mrs:
        author = (mr.get('author', '') or '').lower()
        if my_user in author or author == my_user:
            my_mrs.append(mr)
        else:
            to_review.append(mr)
    
    return {
        'my_mrs': my_mrs,
        'to_review': to_review
    }


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
    return bool(re.match(r'^[A-Z]{2,10}-\d+$', str(key).strip().upper()))


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
        
    match = re.match(r'https?://[^/]+/(.+?)/-/merge_requests/(\d+)', str(url))
    if match:
        return {
            "project": match.group(1),
            "mr_id": int(match.group(2))
        }
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
    match = re.search(r'!(\d+)|IID[:\s]+(\d+)|mr_id[:\s]+(\d+)', str(text), re.IGNORECASE)
    if match:
        return int(match.group(1) or match.group(2) or match.group(3))
    
    # Fallback: find any 2-5 digit number
    nums = re.findall(r'\b(\d{2,5})\b', str(text))
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
        r'[Ss]ource[_ ]?[Bb]ranch[:\s]+(\S+)',
        r'source_branch.*?[:\s]+(\S+)',
        r'Branch:\s*(\S+)',
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
    
    match = re.search(r'Author[:\s]+@?(\w+)', str(mr_details), re.IGNORECASE)
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
    
    match = re.search(r'Status[:\s]+(\S+)', str(issue_details), re.IGNORECASE)
    return match.group(1) if match else None


def parse_conflict_markers(content: str) -> List[Dict[str, str]]:
    """
    Parse git conflict markers from file content.
    
    Args:
        content: File content with conflict markers
        
    Returns:
        List of dicts with 'ours', 'theirs', and 'full_marker' keys
    """
    conflicts = []
    if not content:
        return conflicts
    
    # Pattern: <<<<<<< ... ======= ... >>>>>>>
    pattern = r'<<<<<<<[^\n]*\n(.*?)=======\n(.*?)>>>>>>>[^\n]*'
    matches = re.findall(pattern, str(content), re.DOTALL)
    
    for ours, theirs in matches:
        conflicts.append({
            "ours": ours.strip(),
            "theirs": theirs.strip()
        })
    
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
    md_files = re.findall(r'- `([^`]+)`', str(output))
    files.extend(md_files)
    
    # Git conflict format
    conflict_files = re.findall(r'CONFLICT \([^)]+\):\s*(?:Merge conflict in\s*)?(\S+)', str(output))
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

