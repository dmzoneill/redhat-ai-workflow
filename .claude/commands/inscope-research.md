---
name: inscope-research
description: "Query Red Hat InScope AI assistants for authoritative answers about"
arguments:
  - name: question
    required: true
  - name: assistants
  - name: refresh_auth
---
# Inscope Research

Query Red Hat InScope AI assistants for authoritative answers about

## Instructions

```text
skill_run("inscope_research", '{"question": "$QUESTION", "assistants": "", "refresh_auth": ""}')
```

## What It Does

Query Red Hat InScope AI assistants for authoritative answers about
internal services and documentation.

InScope provides specialized assistants for:
- App Interface (RDS, namespaces, onboarding)
- Clowder (ClowdApps, config, deployment)
- Konflux (CI/CD pipelines, releases)
- And more

Features:
- Auto-selects best assistant based on question
- Query specific assistants
- Auto-refresh authentication if needed

Uses: inscope_ask, inscope_query, inscope_list_assistants,
inscope_auth_status, inscope_auto_login, inscope_save_token

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `question` | Question to ask InScope | Yes |
| `assistants` | Comma-separated assistant names (e.g., 'app-interface,clowder'). Leave empty for auto-select. | No |
| `refresh_auth` | Force re-authentication before querying | No |
