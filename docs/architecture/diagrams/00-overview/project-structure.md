# Project Structure

> Directory layout and organization of the codebase

## Diagram

```mermaid
graph TB
    ROOT[redhat-ai-workflow/]

    subgraph CoreDirs[Core Directories]
        SERVER[server/]
        SERVICES[services/]
        TOOLS[tool_modules/]
        SKILLS[skills/]
        PERSONAS[personas/]
        MEMORY[memory/]
    end

    subgraph SupportDirs[Support Directories]
        DOCS[docs/]
        TESTS[tests/]
        SCRIPTS[scripts/]
        EXTENSIONS[extensions/]
        SYSTEMD[systemd/]
    end

    subgraph ConfigFiles[Configuration]
        CONFIG_JSON[config.json]
        STATE_JSON[state.json]
        PYPROJECT[pyproject.toml]
        MCP_JSON[.mcp.json]
    end

    ROOT --> CoreDirs
    ROOT --> SupportDirs
    ROOT --> ConfigFiles

    subgraph ServerContents[server/ Contents]
        MAIN[main.py]
        PERSONA_LOADER[persona_loader.py]
        SKILL_ENGINE_REF[skill_engine ref]
        TOOL_REGISTRY[tool_registry.py]
        STATE_MGR[state_manager.py]
        CONFIG_MGR[config_manager.py]
        SESSION_BUILDER[session_builder.py]
        AUTO_HEAL[auto_heal_decorator.py]
        WEBSOCKET[websocket_server.py]
        USAGE_PATTERN[usage_pattern_*.py]
    end

    SERVER --> ServerContents

    subgraph ServicesContents[services/ Contents]
        BASE[base/]
        SLACK_SVC[slack/]
        SPRINT_SVC[sprint/]
        MEET_SVC[meet/]
        VIDEO_SVC[video/]
        SESSION_SVC[session/]
        CRON_SVC[cron/]
        MEMORY_SVC[memory/]
        CONFIG_SVC[config/]
        SLOP_SVC[slop/]
        STATS_SVC[stats/]
    end

    SERVICES --> ServicesContents

    subgraph ToolsContents[tool_modules/ Contents]
        AA_WORKFLOW[aa_workflow/]
        AA_JIRA[aa_jira/]
        AA_GITLAB[aa_gitlab/]
        AA_GIT[aa_git/]
        AA_K8S[aa_k8s/]
        AA_BONFIRE[aa_bonfire/]
        AA_SLACK[aa_slack/]
        AA_MEET[aa_meet_bot/]
        AA_MORE[... 41 more]
    end

    TOOLS --> ToolsContents

    subgraph MemoryContents[memory/ Contents]
        MEM_STATE[state/]
        MEM_LEARNED[learned/]
        MEM_KNOWLEDGE[knowledge/]
        MEM_SESSIONS[sessions/]
        MEM_STYLE[style/]
    end

    MEMORY --> MemoryContents

    subgraph DocsContents[docs/ Contents]
        ARCH[architecture/]
        AI_RULES[ai-rules/]
        COMMANDS[commands/]
        DAEMONS_DOC[daemons/]
        PLANS[plans/]
        SKILLS_DOC[skills/]
        TOOL_DOCS[tool-modules/]
    end

    DOCS --> DocsContents
```

## Directory Details

### Core Directories

| Directory | Files | Purpose |
|-----------|-------|---------|
| `server/` | 29 | MCP server core components |
| `services/` | 61 | Background daemon services |
| `tool_modules/` | 302 | 49 tool module packages |
| `skills/` | 95 | YAML skill definitions |
| `personas/` | 36 | Persona YAML and docs |
| `memory/` | 127 | Persistent memory storage |

### Support Directories

| Directory | Files | Purpose |
|-----------|-------|---------|
| `docs/` | 400+ | Documentation |
| `tests/` | 33 | Test suite |
| `scripts/` | 15 | Utility scripts |
| `extensions/` | 2133 | VSCode extension |
| `systemd/` | 13 | Service definitions |

### Configuration Files

| File | Purpose |
|------|---------|
| `config.json` | Project configuration |
| `state.json` | Runtime state |
| `pyproject.toml` | Python project config |
| `.mcp.json` | MCP server config |
| `.cursorrules` | AI assistant rules |
| `CLAUDE.md` | Claude Code rules |
| `AGENTS.md` | Cross-tool AI rules |

### Tool Module Structure

Each tool module follows this pattern:
```
aa_<name>/
├── pyproject.toml      # Package config
├── src/
│   ├── __init__.py
│   ├── tools_basic.py  # Core tools
│   ├── tools_core.py   # Essential tools (optional)
│   ├── tools_extra.py  # Extended tools (optional)
│   └── adapter.py      # Memory adapter (optional)
```

### Memory Structure

```
memory/
├── state/              # Current runtime state
│   ├── current_work.yaml
│   ├── environments.yaml
│   └── projects/
├── learned/            # ML-derived patterns
│   ├── patterns.yaml
│   ├── tool_fixes.yaml
│   └── tool_failures.yaml
├── knowledge/          # Domain knowledge
│   └── personas/
├── sessions/           # Session logs
└── style/              # Style profiles
```

## Related Diagrams

- [System Architecture](./system-architecture.md)
- [Tool Module Structure](../03-tools/tool-module-structure.md)
- [Memory Architecture](../06-memory/memory-architecture.md)
