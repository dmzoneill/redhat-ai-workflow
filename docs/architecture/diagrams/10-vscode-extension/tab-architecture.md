# Tab Architecture

## Tab Class Hierarchy

```mermaid
classDiagram
    class BaseTab {
        <<abstract>>
        #id: string
        #label: string
        #icon: string
        #context: TabContext
        #services: ServiceContainer
        #isLoading: boolean
        #lastError: string
        +getId() string
        +getLabel() string
        +setServices(services)
        +setContext(context)
        +loadData()* Promise~void~
        +getContent()* string
        +getStyles() string
        +getScript() string
        +handleMessage(msg) boolean
        +onActivate() void
        +onDeactivate() void
        +refresh(retries) Promise
        #escapeHtml(text) string
        #formatDuration(ms) string
        #formatRelativeTime(ts) string
        #getPersonaBadgeHtml(name) string
        #notifyNeedsRender() void
    }
    
    BaseTab <|-- OverviewTab
    BaseTab <|-- SessionsTab
    BaseTab <|-- SkillsTab
    BaseTab <|-- MeetingsTab
    BaseTab <|-- SprintTab
    BaseTab <|-- CronTab
    BaseTab <|-- SlackTab
    BaseTab <|-- MemoryTab
    BaseTab <|-- PersonasTab
    BaseTab <|-- ToolsTab
    BaseTab <|-- CreateTab
    BaseTab <|-- InferenceTab
    BaseTab <|-- PerformanceTab
    BaseTab <|-- ServicesTab
    BaseTab <|-- SlopTab
```

## Tab MVC Pattern

```mermaid
flowchart TB
    subgraph Model["MODEL"]
        ss["StateStore"]
        svc["Services"]
        dbus["D-Bus Data"]
    end
    
    subgraph Controller["CONTROLLER"]
        tab["Tab Instance"]
        hm["handleMessage()"]
    end
    
    subgraph View["VIEW"]
        gc["getContent()"]
        html["HTML Output"]
    end
    
    Model -->|"loadData()"| Controller
    Controller -->|"getContent()"| View
    
    user["User Action"] -->|"message"| hm
    hm -->|"update"| Model
    Model -->|"refresh"| gc
    gc --> html
    
    style Model fill:#e3f2fd
    style Controller fill:#fff8e1
    style View fill:#e8f5e9
```

## Tab Lifecycle

```mermaid
sequenceDiagram
    participant TM as TabManager
    participant Tab as Tab Instance
    participant Svc as Services
    participant DBus as D-Bus
    
    TM->>Tab: new Tab(config)
    TM->>Tab: setServices(container)
    TM->>Tab: setContext(webview)
    TM->>Tab: setRenderCallback(fn)
    
    TM->>Tab: loadData()
    Tab->>DBus: fetch data
    DBus-->>Tab: response
    Tab->>Tab: store data
    
    TM->>Tab: getContent()
    Tab-->>TM: HTML string
    
    Note over Tab: Tab is now active
    
    loop User Interactions
        Tab->>Tab: handleMessage(msg)
        Tab->>Svc: business logic
        Svc->>DBus: D-Bus call
        DBus-->>Svc: response
        Tab->>Tab: notifyNeedsRender()
    end
    
    TM->>Tab: onDeactivate()
```

## Tab Registration Flow

```mermaid
flowchart TB
    subgraph TabManager
        constructor["constructor()"]
        register["registerDefaultTabs()"]
        
        constructor --> register
        
        register --> t1["new OverviewTab()"]
        register --> t2["new CreateTab()"]
        register --> t3["new SprintTab()"]
        register --> t4["new SessionsTab()"]
        register --> t5["new PersonasTab()"]
        register --> t6["new SkillsTab()"]
        register --> t7["new ToolsTab()"]
        register --> t8["new MemoryTab()"]
        register --> t9["new MeetingsTab()"]
        register --> t10["new SlackTab()"]
        register --> t11["new InferenceTab()"]
        register --> t12["new CronTab()"]
        register --> t13["new ServicesTab()"]
        register --> t14["new PerformanceTab()"]
        register --> t15["new SlopTab()"]
    end
    
    subgraph Registration["registerTab(tab)"]
        step1["tabs.set(tab.getId(), tab)"]
        step2["tab.setContext(context)"]
        step3["tab.setRenderCallback(callback)"]
        step4["tab.setServices(services)"]
        
        step1 --> step2 --> step3 --> step4
    end
    
    t1 & t2 & t3 & t4 & t5 --> Registration
    t6 & t7 & t8 & t9 & t10 --> Registration
    t11 & t12 & t13 & t14 & t15 --> Registration
```

## BaseTab Interface

```mermaid
classDiagram
    class TabConfig {
        +id: string
        +label: string
        +icon: string
        +badge?: string|number
        +badgeClass?: string
    }
    
    class TabContext {
        +extensionUri: Uri
        +webview: Webview
        +postMessage(msg): void
    }
    
    class ServiceContainer {
        +state: StateStore
        +messages: MessageBus
        +notifications: NotificationService
        +dbus: DBusClient
    }
    
    class BaseTab {
        <<abstract>>
        -_onNeedsRender: RenderCallback
        +constructor(config: TabConfig)
        +setServices(services: ServiceContainer)
        +setContext(context: TabContext)
        +setRenderCallback(callback)
        +loadData()* Promise
        +getContent()* string
    }
    
    TabConfig --> BaseTab : configures
    TabContext --> BaseTab : provides context
    ServiceContainer --> BaseTab : injected
```
