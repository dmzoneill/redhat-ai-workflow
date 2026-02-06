# Extension Watcher

> VSCode extension synchronization daemon

## Diagram

```mermaid
sequenceDiagram
    participant VSCode as VSCode Extension
    participant Watcher as ExtensionWatcher
    participant DBus as D-Bus
    participant MCP as MCP Server
    participant Memory as Memory System

    Watcher->>VSCode: Watch extension state
    
    loop Monitor Loop
        VSCode->>Watcher: State change detected
        Watcher->>Watcher: Parse change
        
        alt Tab change
            Watcher->>DBus: Emit TabChanged signal
            DBus->>MCP: Update context
        else Panel action
            Watcher->>DBus: Emit PanelAction signal
            DBus->>MCP: Process action
        else Settings change
            Watcher->>Memory: Update settings
        end
    end

    MCP->>Watcher: Request extension action
    Watcher->>VSCode: Execute action
    VSCode-->>Watcher: Result
    Watcher-->>MCP: Action result
```

## Class Structure

```mermaid
classDiagram
    class ExtensionWatcher {
        +name: str = "extension-watcher"
        +service_name: str
        -_vscode_state: dict
        -_watchers: list
        +startup() async
        +run_daemon() async
        +shutdown() async
        +get_extension_state(): dict
        +execute_action(action, params): dict
        +get_service_stats() async
    }

    class VSCodeStateReader {
        +read_state(): dict
        +watch_changes(callback)
        +get_active_tab(): str
        +get_open_files(): list
    }

    class ActionExecutor {
        +execute(action, params): dict
        +open_file(path)
        +show_panel(panel)
        +run_command(cmd)
    }

    class SignalEmitter {
        +emit_tab_changed(tab)
        +emit_panel_action(action)
        +emit_file_opened(path)
    }

    ExtensionWatcher --> VSCodeStateReader
    ExtensionWatcher --> ActionExecutor
    ExtensionWatcher --> SignalEmitter
```

## State Synchronization

```mermaid
flowchart TB
    subgraph VSCode[VSCode Extension]
        TABS[Active Tabs]
        PANELS[Panels]
        FILES[Open Files]
        SETTINGS[Settings]
    end

    subgraph Watcher[Extension Watcher]
        READER[State Reader]
        DIFFER[State Differ]
        EMITTER[Signal Emitter]
    end

    subgraph Consumers[State Consumers]
        MCP[MCP Server]
        SESSION[Session Daemon]
        MEMORY[Memory Daemon]
    end

    TABS --> READER
    PANELS --> READER
    FILES --> READER
    SETTINGS --> READER

    READER --> DIFFER
    DIFFER --> EMITTER

    EMITTER --> MCP
    EMITTER --> SESSION
    EMITTER --> MEMORY
```

## Components

| Component | File | Description |
|-----------|------|-------------|
| ExtensionWatcher | `services/extension_watcher/daemon.py` | Main daemon class |
| VSCodeStateReader | Internal | State reading |
| ActionExecutor | Internal | Action execution |

## D-Bus Methods

| Method | Description |
|--------|-------------|
| `get_extension_state()` | Get current state |
| `execute_action(action, params)` | Execute action |
| `get_active_tab()` | Get active tab |
| `get_open_files()` | List open files |
| `show_panel(panel)` | Show panel |
| `run_command(cmd)` | Run VSCode command |

## D-Bus Signals

| Signal | Parameters | Description |
|--------|------------|-------------|
| TabChanged | tab_id, tab_name | Active tab changed |
| PanelAction | action, params | Panel action triggered |
| FileOpened | path | File opened |
| FileClosed | path | File closed |
| SettingsChanged | key, value | Settings changed |

## Watched State

| State | Description | Signal |
|-------|-------------|--------|
| Active tab | Currently selected tab | TabChanged |
| Open files | List of open files | FileOpened/Closed |
| Panel state | Panel visibility | PanelAction |
| Settings | Extension settings | SettingsChanged |

## Actions

| Action | Parameters | Description |
|--------|------------|-------------|
| `open_file` | path | Open file in editor |
| `show_panel` | panel_id | Show specific panel |
| `run_command` | command | Run VSCode command |
| `refresh_tab` | tab_id | Refresh tab content |
| `update_setting` | key, value | Update setting |

## Related Diagrams

- [Daemon Overview](./daemon-overview.md)
- [VSCode Extension](../09-deployment/vscode-extension.md)
- [Session Daemon](./session-daemon.md)
