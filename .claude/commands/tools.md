---
name: tools
description: "Discover all available MCP tools."
---
# 🔧 List Tools

Discover all available MCP tools.

## Instructions

```
tool_list()
```

## Options

```bash
# List all modules
tool_list()

# List tools in a specific module
tool_list(module='git')
tool_list(module='gitlab')
tool_list(module='jira')
tool_list(module='k8s')
tool_list(module='prometheus')
tool_list(module='alertmanager')
tool_list(module='kibana')
tool_list(module='konflux')
tool_list(module='bonfire')
tool_list(module='quay')
tool_list(module='appinterface')
```

## Available Modules

| Module | Tools | Description |
|--------|-------|-------------|
| `git` | 15 | Local git operations |
| `jira` | 21 | Jira issue management |
| `gitlab` | 30 | GitLab MRs, pipelines, CI |
| `k8s` | 14 | Kubernetes pods, logs, exec |
| `prometheus` | 11 | Metrics queries |
| `alertmanager` | 5 | Alert management |
| `kibana` | 9 | Log searching |
| `konflux` | 15 | Build pipelines |
| `bonfire` | 17 | Ephemeral namespaces |
| `quay` | 8 | Container registry |
| `appinterface` | 6 | App-interface configs |

## Calling Tools

After discovering a tool, call it directly:

```python
# Direct call (preferred - shows actual tool name in Cursor)
git_log(repo='/path/to/repo', limit=10)
gitlab_mr_list(project='backend', state='opened')
jira_search(jql='project = AAP AND status = "In Progress"')

# Via tool_exec (for tools from non-loaded personas)
tool_exec('bonfire_namespace_list', '{"mine_only": true}')
```

## See Also

- `/personas` - Load specialized tool sets
- `/list-skills` - See available skills
