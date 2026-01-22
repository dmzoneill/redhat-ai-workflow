# Summarize Findings

Summarize research findings into actionable insights.

## Instructions

```text
skill_run("summarize_findings", '{"topic": "$TOPIC"}')
```

## What It Does

1. Aggregates findings from previous research
2. Extracts key insights and patterns
3. Creates a concise summary with recommendations

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `topic` | Topic to summarize findings for | Yes |
| `format` | Output format: 'brief', 'detailed' | No |

## Examples

```bash
# Summarize research findings
skill_run("summarize_findings", '{"topic": "authentication implementation"}')

# Brief summary
skill_run("summarize_findings", '{"topic": "caching strategy", "format": "brief"}')
```

## Use After

- `research_topic` - To summarize your research
- `compare_options` - To summarize your comparison
