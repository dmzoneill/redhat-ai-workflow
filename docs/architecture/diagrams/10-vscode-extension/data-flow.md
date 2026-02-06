# Data Flow Architecture

## Complete Data Flow

```mermaid
sequenceDiagram
    participant User
    participant Webview
    participant CCP as CommandCenterPanel
    participant TM as TabManager
    participant Tab as SessionsTab
    participant DBus as D-Bus Client
    participant Daemon as Session Daemon
    
    User->>Webview: Click "Refresh Sessions"
    Note over Webview: ① postMessage
    Webview->>CCP: {command: 'refreshSessions'}
    
    Note over CCP: ② onDidReceiveMessage
    CCP->>TM: handleMessage(message)
    
    Note over TM: ③ handleMessage
    TM->>Tab: handleMessage(message)
    
    Note over Tab: ④ handleMessage
    Tab->>Tab: await this.refresh()
    
    Note over Tab: ⑤ D-Bus call
    Tab->>DBus: session_list()
    
    Note over DBus: ⑥ IPC
    DBus->>Daemon: D-Bus method call
    Daemon-->>DBus: {sessions: [...], stats: {...}}
    
    Note over Tab: ⑦ Response
    DBus-->>Tab: result
    Tab->>Tab: this.sessions = result.data.sessions
    
    Note over Tab: ⑧ notifyNeedsRender
    Tab->>CCP: notifyNeedsRender()
    
    Note over CCP: ⑨ setHtml
    CCP->>Webview: updateWebview()
    Webview->>User: Display updated sessions
```

## Tab Data Loading Flow

```mermaid
flowchart TB
    subgraph Init["Panel Initialization"]
        show["CommandCenterPanel.show()"]
        load["tabManager.loadAllData()"]
    end
    
    subgraph Parallel["Parallel Loading (Promise.all)"]
        t1["OverviewTab.loadData()"]
        t2["SessionsTab.loadData()"]
        t3["SkillsTab.loadData()"]
        t4["MeetingsTab.loadData()"]
        tn["...Tab.loadData()"]
    end
    
    subgraph Timeout["With Timeout (5s per tab)"]
        race["Promise.race([<br/>  tab.loadData(),<br/>  timeout(5000)<br/>])"]
    end
    
    subgraph DBus["D-Bus Calls"]
        session["session_list()"]
        skill["skill_list()"]
        meet["meet_getState()"]
        cron["cron_list()"]
    end
    
    show --> load
    load --> Parallel
    t1 & t2 & t3 & t4 & tn --> Timeout
    Timeout --> DBus
    
    style Parallel fill:#e8f5e9
    style Timeout fill:#fff3e0
```

## Refresh with Retry Logic

```mermaid
flowchart TB
    start["refresh(maxRetries = 2)"]
    loading["this.isLoading = true"]
    
    subgraph Loop["for attempt = 1 to maxRetries"]
        try["try { await loadData() }"]
        success{"Success?"}
        
        clear["this.lastError = null<br/>this.isLoading = false"]
        render1["notifyNeedsRender()"]
        return1["return"]
        
        catch["catch (error)"]
        setError["this.lastError = error.message"]
        log["logger.warn(...)"]
        
        moreRetries{"attempt < maxRetries?"}
        backoff["delay = 500 * 2^(attempt-1)<br/>await sleep(delay)"]
    end
    
    exhausted["All retries exhausted"]
    logError["logger.error(...)"]
    setLoading["this.isLoading = false"]
    render2["notifyNeedsRender()"]
    
    start --> loading --> try
    try --> success
    success -->|yes| clear --> render1 --> return1
    success -->|no| catch --> setError --> log --> moreRetries
    moreRetries -->|yes| backoff --> try
    moreRetries -->|no| exhausted --> logError --> setLoading --> render2
    
    style success fill:#c8e6c9
    style exhausted fill:#ffcdd2
```

## Retry Timing

```mermaid
gantt
    title Retry with Exponential Backoff
    dateFormat X
    axisFormat %L ms
    
    section Attempt 1
    loadData()     :a1, 0, 100
    
    section Backoff 1
    sleep(500ms)   :b1, 100, 600
    
    section Attempt 2
    loadData()     :a2, 600, 700
    
    section Backoff 2
    sleep(1000ms)  :b2, 700, 1700
    
    section Attempt 3
    loadData()     :a3, 1700, 1800
```

## State Change Propagation

```mermaid
flowchart TB
    subgraph Update["State Update"]
        call["stateStore.setWorkspaces({<br/>  workspaces: newWorkspaces,<br/>  count: 5<br/>})"]
    end
    
    subgraph Emit["Event Emission"]
        emit1["emit('workspaces:changed', data, oldValue)"]
        emit2["emit('state:changed', 'workspaces', data)"]
    end
    
    subgraph Listeners["Event Listeners"]
        l1["UI Update Listener<br/>→ this.updateWebview()"]
        l2["Badge Update Listener<br/>→ updateStatusBar(count)"]
        l3["Logging Listener<br/>→ logger.log(...)"]
    end
    
    call --> emit1 & emit2
    emit1 --> l1 & l2
    emit2 --> l3
```

## State Sections

```mermaid
flowchart LR
    subgraph StateStore
        state["AppState"]
    end
    
    subgraph Sections
        workspaces["workspaces<br/>WorkspacesState"]
        services["services<br/>ServicesState"]
        meetings["meetings<br/>MeetingsState"]
        sprint["sprint<br/>SprintStateContainer"]
        cron["cron<br/>CronState"]
        slack["slack<br/>SlackState"]
        memory["memory<br/>MemoryState"]
        skills["skills<br/>SkillsState"]
        personas["personas<br/>PersonasState"]
        tools["tools<br/>ToolsState"]
    end
    
    state --> workspaces & services & meetings & sprint & cron
    state --> slack & memory & skills & personas & tools
```

## Data Flow Summary

```mermaid
flowchart LR
    subgraph User["User Layer"]
        action["User Action"]
        display["Display Update"]
    end
    
    subgraph Webview["Webview Layer"]
        post["postMessage"]
        listen["addEventListener"]
    end
    
    subgraph Extension["Extension Layer"]
        recv["onDidReceiveMessage"]
        tab["Tab.handleMessage"]
        service["Service Logic"]
        msgbus["MessageBus.publish"]
        send["webview.postMessage"]
    end
    
    subgraph Backend["Backend Layer"]
        dbus["D-Bus Client"]
        daemon["Daemon"]
    end
    
    action --> post --> recv --> tab --> service --> dbus
    dbus <--> daemon
    dbus --> msgbus --> send --> listen --> display
    
    style User fill:#e8f5e9
    style Webview fill:#e3f2fd
    style Extension fill:#fff3e0
    style Backend fill:#f3e5f5
```
