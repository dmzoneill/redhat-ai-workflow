# Service Architecture

## Dependency Injection Container

```mermaid
classDiagram
    class Container {
        -services: Map~string, ServiceDescriptor~
        -options: ContainerOptions
        -disposed: boolean
        +register(key, factory, singleton) this
        +registerInstance(key, instance) this
        +get~T~(key) T
        +has(key) boolean
        +getKeys() string[]
        +dispose() void
        +state StateStore
        +messages MessageBus
        +notifications NotificationService
        +dbusClient DBusClient
    }

    class ServiceDescriptor {
        +factory: ServiceFactory
        +instance?: T
        +singleton: boolean
    }

    class ContainerOptions {
        +panel?: WebviewPanel
        +extensionUri?: Uri
    }

    Container --> ServiceDescriptor : manages
    Container --> ContainerOptions : configured by
```

## Service Keys

```mermaid
flowchart TB
    subgraph CoreServices["Core Services"]
        state["state → StateStore"]
        messages["messages → MessageBus"]
        notifications["notifications → NotificationService"]
        dbus["dbus → D-Bus Client"]
    end

    subgraph DomainServices["Domain Services"]
        meeting["meetingService → MeetingService"]
        slack["slackService → SlackService"]
        sprint["sprintService → SprintService"]
        cron["cronService → CronService"]
        session["sessionService → SessionService"]
        memory["memoryService → MemoryService"]
        skill["skillService → SkillService"]
    end

    container["Container"] --> CoreServices
    container --> DomainServices
```

## Service Layer Architecture

```mermaid
flowchart TB
    subgraph UI["TABS (UI Layer)"]
        mt["MeetingsTab"]
        st["SlackTab"]
        ct["CronTab"]
        spt["SprintTab"]
    end

    subgraph BL["SERVICES (Business Logic)"]
        ms["MeetingService<br/>- joinMeeting<br/>- leaveMeeting<br/>- muteAudio"]
        ss["SlackService<br/>- sendMessage<br/>- getChannels<br/>- approve"]
        cs["CronService<br/>- runJob<br/>- toggleJob<br/>- getHistory"]
    end

    subgraph DBUS["D-BUS CLIENT"]
        meet_call["meet_join()<br/>meet_leave()<br/>meet_mute()"]
        slack_call["slack_send()<br/>slack_getChannels()"]
        cron_call["cron_runJob()<br/>cron_toggleJob()"]
    end

    subgraph Daemons["BACKEND DAEMONS"]
        meet_d["bot-meet"]
        slack_d["bot-slack"]
        cron_d["bot-cron"]
    end

    mt --> ms
    st --> ss
    ct --> cs
    spt --> ms

    ms --> meet_call
    ss --> slack_call
    cs --> cron_call

    meet_call <-->|"D-Bus IPC"| meet_d
    slack_call <-->|"D-Bus IPC"| slack_d
    cron_call <-->|"D-Bus IPC"| cron_d

    style UI fill:#e8f5e9
    style BL fill:#fff3e0
    style DBUS fill:#e3f2fd
    style Daemons fill:#f3e5f5
```

## StateStore Architecture

```mermaid
classDiagram
    class StateStore {
        <<EventEmitter>>
        -state: AppState
        +getState() AppState
        +get~K~(section) AppState[K]
        +set~K~(section, data) void
        +update~K~(section, partial) void
        +batchUpdate(updates) void
        +invalidate(section) void
        +invalidateAll() void
        +isLoaded(section) boolean
        +workspaces WorkspacesState
        +services ServicesState
        +meetings MeetingsState
        +sprint SprintStateContainer
        +cron CronState
        +slack SlackState
        +memory MemoryState
        +skills SkillsState
        +personas PersonasState
        +tools ToolsState
    }

    class AppState {
        +workspaces: WorkspacesState
        +services: ServicesState
        +meetings: MeetingsState
        +sprint: SprintStateContainer
        +cron: CronState
        +slack: SlackState
        +memory: MemoryState
        +skills: SkillsState
        +personas: PersonasState
        +tools: ToolsState
        +ollama: OllamaState
        +inference: InferenceState
        +stats: AgentStats
        +videoPreview: VideoPreviewState
        +currentTab: string
    }

    StateStore --> AppState : manages
```

## StateStore Events

```mermaid
flowchart LR
    subgraph StateStore
        set["set(section, data)"]
        update["update(section, partial)"]
        batch["batchUpdate(updates)"]
        invalidate["invalidate(section)"]
    end

    subgraph Events
        changed["'{section}:changed'"]
        state_changed["'state:changed'"]
        batch_changed["'state:batch-changed'"]
        invalidated["'{section}:invalidated'"]
        reset["'state:reset'"]
    end

    set --> changed
    set --> state_changed
    update --> changed
    update --> state_changed
    batch --> batch_changed
    invalidate --> invalidated
```

## MessageBus Architecture

```mermaid
flowchart TB
    subgraph Publishers
        svc["Service.doSomething()"]
        pub["messageBus.publish('dataUpdated', {result})"]
    end

    subgraph MessageBus
        queue["Message Queue<br/>- Optional batching<br/>- Message history<br/>- Wildcard support"]
    end

    subgraph Subscribers
        local["Local Subscribers<br/>messageBus.subscribe()"]
        webview["Webview<br/>webview.postMessage()"]
    end

    svc --> pub
    pub --> queue
    queue --> local
    queue --> webview

    style Publishers fill:#e8f5e9
    style MessageBus fill:#fff3e0
    style Subscribers fill:#e3f2fd
```

## MessageBus Class

```mermaid
classDiagram
    class MessageBus {
        -webview: Webview
        -subscribers: Map~string, Set~MessageHandler~~
        -options: MessageBusOptions
        -batchQueue: UIMessage[]
        -messageHistory: UIMessage[]
        +connect(webview) void
        +disconnect() void
        +isConnected() boolean
        +publish(type, payload) void
        +publishBatch(messages) void
        +subscribe(type, handler) unsubscribe
        +subscribeMany(types, handler) unsubscribe
        +once(type, handler) unsubscribe
        +getHistory() UIMessage[]
        +clearHistory() void
        +dispose() void
    }

    class UIMessage {
        +type: string
        +[key: string]: any
    }

    class MessageBusOptions {
        +debug?: boolean
        +batchWindow?: number
    }

    MessageBus --> UIMessage : publishes
    MessageBus --> MessageBusOptions : configured by
```

## Service Injection Flow

```mermaid
sequenceDiagram
    participant CCP as CommandCenterPanel
    participant Cont as Container
    participant TM as TabManager
    participant Tab as Tab Instance

    Note over CCP: 1. Container Creation
    CCP->>Cont: createContainer({panel})
    Cont->>Cont: registerCoreServices()
    Note over Cont: StateStore, MessageBus,<br/>NotificationService, D-Bus

    Note over CCP: 2. Service Container
    CCP->>CCP: Build serviceContainer object

    Note over CCP: 3. Inject into TabManager
    CCP->>TM: setServices(serviceContainer)

    loop For each tab
        TM->>Tab: setServices(services)
    end

    Note over Tab: 4. Tab Usage
    Tab->>Tab: this.services.state.get('sessions')
    Tab->>Tab: this.services.messages.publish(...)
```

## Singleton Pattern

```mermaid
flowchart TB
    subgraph Global["Global Singletons"]
        gss["getStateStore()"]
        gmb["getMessageBus()"]
        gns["getNotificationService()"]
        gc["getContainer()"]
    end

    subgraph Instances["Singleton Instances"]
        ss["stateStoreInstance"]
        mb["messageBusInstance"]
        ns["notificationServiceInstance"]
        cont["globalContainer"]
    end

    subgraph Reset["Reset Functions"]
        rss["resetStateStore()"]
        rmb["resetMessageBus()"]
        rns["resetNotificationService()"]
        rc["resetContainer()"]
    end

    gss --> ss
    gmb --> mb
    gns --> ns
    gc --> cont

    rss -.->|"dispose & null"| ss
    rmb -.->|"dispose & null"| mb
    rns -.->|"dispose & null"| ns
    rc -.->|"dispose & null"| cont
```
