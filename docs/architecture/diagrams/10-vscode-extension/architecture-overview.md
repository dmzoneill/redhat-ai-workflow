# VSCode Extension Architecture Overview

## High-Level Architecture

```mermaid
flowchart TB
    subgraph Extension["VSCode Extension"]
        entry["extension.ts<br/>(entry point)"]
        
        subgraph Panel["CommandCenterPanel (Orchestrator)"]
            tm["TabManager"]
            mr["MessageRouter"]
            hg["HtmlGenerator"]
            container["Container (DI)"]
        end
        
        subgraph Tabs["Tabs (15)"]
            overview["OverviewTab"]
            sessions["SessionsTab"]
            skills["SkillsTab"]
            meetings["MeetingsTab"]
            sprint["SprintTab"]
            more["..."]
        end
        
        subgraph Services["Services"]
            state["StateStore"]
            msgbus["MessageBus"]
            meeting["MeetingService"]
            slack["SlackService"]
            cron["CronService"]
        end
        
        dbus["D-Bus Client"]
    end
    
    subgraph Daemons["Backend Daemons (systemd)"]
        session_d["Session Daemon"]
        meet_d["Meet Daemon"]
        slack_d["Slack Daemon"]
        cron_d["Cron Daemon"]
        sprint_d["Sprint Daemon"]
        memory_d["Memory Daemon"]
    end
    
    entry --> Panel
    tm --> Tabs
    container --> Services
    Tabs --> Services
    Services --> dbus
    dbus <-->|"D-Bus IPC"| Daemons
    
    style entry fill:#e1f5fe
    style Panel fill:#fff3e0
    style Tabs fill:#e8f5e9
    style Services fill:#fce4ec
    style Daemons fill:#f3e5f5
```

## Component Relationships

```mermaid
flowchart LR
    subgraph Initialization
        ext["extension.ts"] --> ccp["CommandCenterPanel"]
    end
    
    subgraph Coordination
        ccp --> tm["TabManager"]
        ccp --> mr["MessageRouter"]
        ccp --> hg["HtmlGenerator"]
        ccp --> cont["Container"]
    end
    
    subgraph TabSystem
        tm --> bt["BaseTab"]
        bt --> t1["Tab 1"]
        bt --> t2["Tab 2"]
        bt --> tn["Tab N"]
    end
    
    subgraph ServiceLayer
        cont --> ss["StateStore"]
        cont --> mb["MessageBus"]
        cont --> svc["Domain Services"]
    end
    
    TabSystem -->|"uses"| ServiceLayer
    ServiceLayer -->|"D-Bus"| daemon["Daemons"]
```

## Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **extension.ts** | Entry point, registers commands, initializes panel |
| **CommandCenterPanel** | Main orchestrator, coordinates all components |
| **TabManager** | Tab lifecycle, switching, data loading |
| **MessageRouter** | Routes webview messages to handlers |
| **Container** | Dependency injection for services |
| **BaseTab** | Abstract base class for all tabs |
| **Services** | Business logic, decoupled from UI |
| **StateStore** | Centralized reactive state management |
| **MessageBus** | Pub/sub for UI communication |
| **D-Bus Client** | Communication with backend daemons |

## Key Design Patterns

```mermaid
mindmap
  root((Design Patterns))
    MVC in Tabs
      Model: Services
      View: getContent
      Controller: handleMessage
    Dependency Injection
      Container manages instances
      Services injected into tabs
    Pub/Sub
      MessageBus
      Decoupled communication
    Reactive State
      StateStore
      Event-based updates
    Handler Pattern
      MessageRouter
      Pluggable handlers
```
