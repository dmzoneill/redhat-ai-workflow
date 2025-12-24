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

