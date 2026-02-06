# Message Flow Architecture

## Webview to Extension Communication

```mermaid
sequenceDiagram
    participant User
    participant Webview
    participant CCP as CommandCenterPanel
    participant TM as TabManager
    participant Tab as SessionsTab
    participant MR as MessageRouter

    User->>Webview: Click "Refresh Sessions"
    Webview->>CCP: postMessage({command: 'refreshSessions'})

    CCP->>TM: handleMessage(message)
    TM->>Tab: handleMessage(message)

    alt Tab handles message
        Tab->>Tab: await this.refresh()
        Tab-->>TM: return true
        TM-->>CCP: return true
    else Tab doesn't handle
        Tab-->>TM: return false
        TM-->>CCP: return false
        CCP->>MR: route(message, context)
        MR->>MR: find matching handler
        MR->>MR: handler.handle(message)
    end
```

## Extension to Webview Communication

```mermaid
sequenceDiagram
    participant Service as Business Logic
    participant MB as MessageBus
    participant Subscribers as Local Subscribers
    participant Webview

    Service->>Service: Update sessions
    Service->>MB: publish('sessionsUpdated', {sessions})

    par Notify subscribers
        MB->>Subscribers: handler(message)
    and Send to webview
        MB->>Webview: postMessage(message)
    end

    Webview->>Webview: window.addEventListener('message')
    Webview->>Webview: updateSessionsUI(sessions)
```

## Message Router Pattern

```mermaid
flowchart TB
    subgraph MessageRouter
        route["route(message, context)"]

        subgraph Handlers
            sh["SessionHandler"]
            slh["SlackHandler"]
            ch["CommandHandler"]
            ih["InferenceHandler"]
            vh["VideoHandler"]
            uh["UtilityHandler"]
        end
    end

    msg["Incoming Message"] --> route

    route --> check1{canHandle?}
    check1 -->|yes| sh
    check1 -->|no| check2{canHandle?}
    check2 -->|yes| slh
    check2 -->|no| check3{canHandle?}
    check3 -->|yes| ch
    check3 -->|no| checkN{...}
    checkN -->|no handler| default["Default Handler"]

    sh --> handled["Message Handled"]
    slh --> handled
    ch --> handled
```

## Handler Commands

```mermaid
flowchart LR
    subgraph SessionHandler
        s1["refresh"]
        s2["openChatSession"]
        s3["viewMeetingNotes"]
    end

    subgraph SlackHandler
        sl1["loadSlackHistory"]
        sl2["replyToSlackThread"]
        sl3["refreshSlackChannels"]
        sl4["searchSlackUsers"]
    end

    subgraph CommandHandler
        c1["openJira"]
        c2["openMR"]
        c3["switchAgent"]
        c4["startWork"]
        c5["coffee / beer"]
    end

    subgraph InferenceHandler
        i1["runInferenceTest"]
        i2["getInferenceStats"]
        i3["semanticSearch"]
    end

    subgraph UtilityHandler
        u1["ping"]
        u2["webviewLog"]
    end
```

## Tab-First Message Handling

```mermaid
flowchart TB
    subgraph Before["BEFORE (Centralized)"]
        mr1["MessageRouter"]
        smh1["SessionMessageHandler"]

        mr1 --> smh1
        smh1 --> cmd1["copySessionId"]
        smh1 --> cmd2["searchSessions"]
        smh1 --> cmd3["changeGroupBy"]
        smh1 --> cmd4["changeViewMode"]
        smh1 --> cmd5["refreshSessions"]
    end

    subgraph After["AFTER (Tab-First)"]
        st["SessionsTab.handleMessage()"]
        st --> tcmd1["copySessionId"]
        st --> tcmd2["searchSessions"]
        st --> tcmd3["changeGroupBy"]
        st --> tcmd4["changeViewMode"]

        mr2["MessageRouter"]
        smh2["SessionMessageHandler (reduced)"]
        mr2 --> smh2
        smh2 --> vcmd1["openChatSession"]
        smh2 --> vcmd2["viewMeetingNotes"]
    end

    style Before fill:#ffebee
    style After fill:#e8f5e9
```

## Complete Message Flow

```mermaid
flowchart TB
    subgraph Webview
        btn["Button Click"]
        post["vscode.postMessage()"]
        listen["window.addEventListener"]
        update["Update UI"]
    end

    subgraph Extension
        recv["onDidReceiveMessage"]
        tm["TabManager.handleMessage"]
        tab["Tab.handleMessage"]
        mr["MessageRouter.route"]
        handler["Handler.handle"]
        mb["MessageBus.publish"]
        send["webview.postMessage"]
    end

    subgraph Backend
        dbus["D-Bus Client"]
        daemon["Daemon"]
    end

    btn --> post
    post --> recv
    recv --> tm
    tm --> tab

    tab -->|handled| dbus
    tab -->|not handled| mr
    mr --> handler
    handler --> dbus

    dbus <--> daemon

    dbus --> mb
    mb --> send
    send --> listen
    listen --> update

    style Webview fill:#e3f2fd
    style Extension fill:#fff8e1
    style Backend fill:#f3e5f5
```
