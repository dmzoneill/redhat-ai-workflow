"""
Jira utilities for the AI workflow tools.

Includes:
- Markdown to Jira wiki markup converter
- Field name normalization
- Issue type normalization
"""
import re
from typing import Dict, Any, Optional


def markdown_to_jira(text: str) -> str:
    """
    Convert Markdown to Jira wiki markup.
    
    Args:
        text: Markdown formatted text
        
    Returns:
        Jira wiki markup formatted text
        
    Examples:
        >>> markdown_to_jira("# Heading")
        'h1. Heading'
        >>> markdown_to_jira("**bold**")
        '*bold*'
        >>> markdown_to_jira("`code`")
        '{{code}}'
    """
    if not text:
        return text
    
    # Headings: ### -> h3. (process in reverse order to avoid conflicts)
    text = re.sub(r'^######\s+(.+)$', r'h6. \1', text, flags=re.MULTILINE)
    text = re.sub(r'^#####\s+(.+)$', r'h5. \1', text, flags=re.MULTILINE)
    text = re.sub(r'^####\s+(.+)$', r'h4. \1', text, flags=re.MULTILINE)
    text = re.sub(r'^###\s+(.+)$', r'h3. \1', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.+)$', r'h2. \1', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.+)$', r'h1. \1', text, flags=re.MULTILINE)
    
    # Code blocks: ```lang\n...\n``` -> {code:lang}\n...\n{code}
    text = re.sub(
        r'```(\w+)\n(.*?)\n```', 
        r'{code:\1}\n\2\n{code}', 
        text, 
        flags=re.DOTALL
    )
    text = re.sub(
        r'```\n?(.*?)\n?```', 
        r'{code}\n\1\n{code}', 
        text, 
        flags=re.DOTALL
    )
    
    # Inline code: `code` -> {{code}} (before bold/italic to avoid conflicts)
    text = re.sub(r'`([^`]+)`', r'{{\1}}', text)
    
    # Bold: **text** -> *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
    
    # Italic: _text_ stays as _text_ in Jira
    # But markdown *text* (single asterisk) needs to become _text_
    # Only convert if not already bold
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'_\1_', text)
    
    # Strikethrough: ~~text~~ -> -text-
    text = re.sub(r'~~(.+?)~~', r'-\1-', text)
    
    # Unordered lists: - item -> * item
    text = re.sub(r'^- ', r'* ', text, flags=re.MULTILINE)
    text = re.sub(r'^  - ', r'** ', text, flags=re.MULTILINE)
    text = re.sub(r'^    - ', r'*** ', text, flags=re.MULTILINE)
    text = re.sub(r'^      - ', r'**** ', text, flags=re.MULTILINE)
    
    # Ordered lists: 1. item -> # item
    text = re.sub(r'^\d+\.\s+', r'# ', text, flags=re.MULTILINE)
    text = re.sub(r'^  \d+\.\s+', r'## ', text, flags=re.MULTILINE)
    text = re.sub(r'^    \d+\.\s+', r'### ', text, flags=re.MULTILINE)
    
    # Links: [text](url) -> [text|url]
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'[\1|\2]', text)
    
    # Images: ![alt](url) -> !url!
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'!\2!', text)
    
    # Blockquotes: > text -> {quote}text{quote}
    # Multi-line quotes
    lines = text.split('\n')
    in_quote = False
    result_lines = []
    for line in lines:
        if line.startswith('> '):
            if not in_quote:
                result_lines.append('{quote}')
                in_quote = True
            result_lines.append(line[2:])
        else:
            if in_quote:
                result_lines.append('{quote}')
                in_quote = False
            result_lines.append(line)
    if in_quote:
        result_lines.append('{quote}')
    text = '\n'.join(result_lines)
    
    # Horizontal rule: --- or *** -> ----
    text = re.sub(r'^[-*]{3,}$', r'----', text, flags=re.MULTILINE)
    
    return text


def normalize_issue_type(issue_type: str) -> str:
    """
    Normalize issue type to lowercase.
    
    Args:
        issue_type: Issue type in any case (Story, STORY, story)
        
    Returns:
        Lowercase issue type
        
    Examples:
        >>> normalize_issue_type("Story")
        'story'
        >>> normalize_issue_type("BUG")
        'bug'
    """
    valid_types = {'bug', 'story', 'epic', 'task', 'sub-task', 'subtask'}
    normalized = issue_type.lower().strip()
    
    # Handle common aliases
    aliases = {
        'sub-task': 'subtask',
        'feature': 'story',
        'issue': 'task',
    }
    normalized = aliases.get(normalized, normalized)
    
    if normalized not in valid_types:
        raise ValueError(
            f"Invalid issue type: '{issue_type}'. "
            f"Valid types: {', '.join(sorted(valid_types))}"
        )
    
    return normalized


# Mapping from snake_case to Jira Title Case field names
FIELD_NAME_MAP = {
    # Input variations -> Jira field name
    'user_story': 'User Story',
    'userstory': 'User Story',
    'acceptance_criteria': 'Acceptance Criteria',
    'acceptancecriteria': 'Acceptance Criteria',
    'supporting_documentation': 'Supporting Documentation',
    'supportingdocumentation': 'Supporting Documentation',
    'supporting_docs': 'Supporting Documentation',
    'definition_of_done': 'Definition of Done',
    'definitionofdone': 'Definition of Done',
    'dod': 'Definition of Done',
    'description': 'Description',
    'summary': 'Summary',
    'labels': 'Labels',
    'components': 'Components',
    'story_points': 'Story Points',
    'storypoints': 'Story Points',
    'points': 'Story Points',
    'epic_link': 'Epic Link',
    'epiclink': 'Epic Link',
    'epic': 'Epic Link',
    'assignee': 'Assignee',
    'reporter': 'Reporter',
    'priority': 'Priority',
    'fix_version': 'Fix Version',
    'fixversion': 'Fix Version',
    'sprint': 'Sprint',
}


def normalize_field_name(field_name: str) -> str:
    """
    Normalize field name to Jira's expected Title Case format.
    
    Args:
        field_name: Field name in any format
        
    Returns:
        Jira-compatible Title Case field name
        
    Examples:
        >>> normalize_field_name("user_story")
        'User Story'
        >>> normalize_field_name("acceptance_criteria")
        'Acceptance Criteria'
    """
    # Already in correct format?
    if field_name in FIELD_NAME_MAP.values():
        return field_name
    
    # Normalize to lowercase for lookup
    lookup_key = field_name.lower().replace(' ', '_').replace('-', '_')
    
    if lookup_key in FIELD_NAME_MAP:
        return FIELD_NAME_MAP[lookup_key]
    
    # Unknown field - convert snake_case to Title Case as fallback
    return ' '.join(word.capitalize() for word in field_name.replace('_', ' ').split())


def normalize_jira_input(data: Dict[str, Any], convert_markdown: bool = True) -> Dict[str, Any]:
    """
    Normalize a dictionary of Jira fields.
    
    - Converts field names to Title Case
    - Optionally converts Markdown to Jira markup
    
    Args:
        data: Dictionary of field name -> value
        convert_markdown: Whether to convert Markdown values
        
    Returns:
        Normalized dictionary
    """
    result = {}
    
    # Fields that typically contain formatted text
    text_fields = {
        'User Story', 'Description', 'Acceptance Criteria',
        'Supporting Documentation', 'Definition of Done'
    }
    
    for key, value in data.items():
        normalized_key = normalize_field_name(key)
        
        if convert_markdown and normalized_key in text_fields and isinstance(value, str):
            value = markdown_to_jira(value)
        
        result[normalized_key] = value
    
    return result


def build_jira_yaml(
    summary: str,
    issue_type: str,
    description: str = "",
    user_story: str = "",
    acceptance_criteria: str = "",
    supporting_documentation: str = "",
    definition_of_done: str = "",
    labels: list = None,
    components: list = None,
    story_points: int = None,
    epic_link: str = "",
    convert_markdown: bool = True,
) -> str:
    """
    Build a YAML string for rh-issue CLI input.
    
    All text fields accept Markdown and are auto-converted to Jira markup.
    
    Args:
        summary: Issue summary/title
        issue_type: story, bug, task, epic
        description: Issue description
        user_story: User story text
        acceptance_criteria: Acceptance criteria
        supporting_documentation: Supporting docs
        definition_of_done: Definition of done
        labels: List of labels
        components: List of components
        story_points: Story points estimate
        epic_link: Epic issue key to link to
        convert_markdown: Whether to convert Markdown to Jira markup
        
    Returns:
        YAML string ready for rh-issue --input-file
    """
    import yaml
    
    data = {"Summary": summary}
    
    if description:
        data["Description"] = markdown_to_jira(description) if convert_markdown else description
    
    if user_story:
        data["User Story"] = markdown_to_jira(user_story) if convert_markdown else user_story
    
    if acceptance_criteria:
        data["Acceptance Criteria"] = markdown_to_jira(acceptance_criteria) if convert_markdown else acceptance_criteria
    
    if supporting_documentation:
        data["Supporting Documentation"] = markdown_to_jira(supporting_documentation) if convert_markdown else supporting_documentation
    
    if definition_of_done:
        data["Definition of Done"] = markdown_to_jira(definition_of_done) if convert_markdown else definition_of_done
    
    if labels:
        data["Labels"] = labels if isinstance(labels, list) else [labels]
    
    if components:
        data["Components"] = components if isinstance(components, list) else [components]
    
    if story_points is not None:
        data["Story Points"] = story_points
    
    if epic_link:
        data["Epic Link"] = epic_link
    
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)

