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


def parse_mr_list(output: str) -> List[Dict[str, Any]]:
    """
    Parse gitlab_mr_list output into structured MR data.
    
    Args:
        output: Raw output from glab mr list
        
    Returns:
        List of dicts with 'id' and 'title' keys
    """
    mrs = []
    if not output:
        return mrs
        
    for line in str(output).split('\n'):
        # Parse: !1452  automation-analytics/automation-analytics-backend!1452  AAP-58394 - feat(clowder)... (main)
        match = re.search(r'!(\d+)\s+\S+\s+(.+?)\s*\(main\)', line)
        if match:
            mrs.append({
                "id": int(match.group(1)),
                "title": match.group(2).strip()[:60]
            })
    return mrs


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

