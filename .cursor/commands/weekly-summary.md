# 📊 Weekly Summary

Generate a summary of work from session logs.

## Usage

**Default (past 7 days):**
```text
skill_run("weekly_summary", '{}')
```

**Custom period:**
```text
skill_run("weekly_summary", '{"days": 14}')
```

**Slack format:**
```text
skill_run("weekly_summary", '{"format": "slack"}')
```

## What It Includes

- **Issues worked**: Jira issues mentioned in session logs
- **MRs created/reviewed**: Merge requests tracked
- **Deployments**: Ephemeral and other deployments
- **Debug sessions**: Investigation and debugging work
- **Patterns learned**: New error patterns saved
- **Currently active**: Active issues and open MRs from memory

## Example

```text
/weekly-summary
```

This generates a comprehensive summary useful for:
- Weekly team standups
- Sprint reviews
- Personal progress tracking
