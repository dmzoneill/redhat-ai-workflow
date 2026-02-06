# Config System

> Configuration loading hierarchy and management

## Diagram

```mermaid
graph TB
    subgraph ConfigFiles[Configuration Files]
        CONFIG_JSON[config.json<br/>Static configuration]
        STATE_JSON[state.json<br/>Runtime state]
        MCP_JSON[.mcp.json<br/>MCP server config]
    end

    subgraph Managers[Config Managers]
        CONFIG_MGR[ConfigManager<br/>config_manager.py]
        STATE_MGR[StateManager<br/>state_manager.py]
    end

    subgraph Loaders[Config Loaders]
        UTILS[utils.load_config]
        PATHS[paths.py constants]
    end

    subgraph Consumers[Config Consumers]
        SERVER[MCP Server]
        DAEMONS[Daemons]
        TOOLS[Tool Modules]
        SKILLS[Skill Engine]
    end

    CONFIG_JSON --> CONFIG_MGR
    STATE_JSON --> STATE_MGR
    MCP_JSON --> SERVER

    CONFIG_MGR --> UTILS
    STATE_MGR --> UTILS
    PATHS --> UTILS

    UTILS --> SERVER
    UTILS --> DAEMONS
    UTILS --> TOOLS
    UTILS --> SKILLS
```

## Configuration Hierarchy

```mermaid
flowchart TB
    subgraph Level1[Project Level]
        CONFIG[config.json]
        STATE[state.json]
    end

    subgraph Level2[User Level]
        USER_CONFIG[~/.config/aa-workflow/config.json]
        USER_STATE[~/.config/aa-workflow/state.json]
    end

    subgraph Level3[Environment]
        ENV_VARS[Environment Variables]
    end

    subgraph Merged[Merged Configuration]
        FINAL[Final Config]
    end

    CONFIG --> FINAL
    USER_CONFIG --> FINAL
    ENV_VARS --> FINAL
    STATE --> FINAL
    USER_STATE --> FINAL

    Note1[Project overrides user]
    Note2[Env vars override all]
```

## Config Manager Class

```mermaid
classDiagram
    class ConfigManager {
        +config_file: Path
        -_cache: dict
        -_last_mtime: float
        +get(section, key, default): Any
        +get_section(section): dict
        +update_section(section, data)
        +reload()
        +flush()
    }

    class ConfigSections {
        <<structure>>
        +projects: dict
        +agent: dict
        +schedules: dict
        +paths: dict
        +credentials: dict
        +integrations: dict
    }

    ConfigManager --> ConfigSections : manages
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| ConfigManager | `server/config_manager.py` | Config file manager |
| StateManager | `server/state_manager.py` | State file manager |
| load_config | `server/utils.py` | Config loading utility |
| paths | `server/paths.py` | Path constants |
| config.py | `server/config.py` | Config constants |

## Config Sections

| Section | Purpose | Example Keys |
|---------|---------|--------------|
| projects | Project definitions | gitlab_url, jira_project |
| agent | Agent settings | default_persona, tool_limit |
| schedules | Cron schedules | jobs, poll_sources |
| paths | File paths | vpn_script, kubeconfig |
| credentials | Auth config | jira_token_env, gitlab_token_env |
| integrations | External services | slack_workspace, google_project |

## State vs Config

| Aspect | config.json | state.json |
|--------|-------------|------------|
| Purpose | Static settings | Runtime state |
| Changes | Manual edits | Programmatic |
| Examples | URLs, paths | Enabled flags, toggles |
| Persistence | Git tracked | Local only |

## Environment Variables

| Variable | Purpose |
|----------|---------|
| AA_CONFIG_DIR | Config directory override |
| AA_PROJECT | Active project override |
| JIRA_JPAT | Jira API token |
| GITLAB_TOKEN | GitLab API token |
| SLACK_TOKEN | Slack API token |

## Related Diagrams

- [State Manager](./state-manager.md)
- [MCP Server Core](./mcp-server-core.md)
- [Project Structure](../00-overview/project-structure.md)
