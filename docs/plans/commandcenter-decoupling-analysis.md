# CommandCenter Decoupling Analysis

## Executive Summary

The remaining 6,393 lines in `commandCenter.ts` suffer from **God Object anti-pattern** - a single class that knows too much and does too much. The tight coupling stems from three core issues:

1. **State Management Sprawl** - 25+ private cache variables scattered throughout
2. **UI Communication Coupling** - 89 direct `postMessage` calls embedded in business logic
3. **Notification Side Effects** - 185 `vscode.window.show*` calls mixed with domain logic

## Current Architecture Problems

### Problem 1: State Management Sprawl

```typescript
// 25+ private cache variables - each managed independently
private _workspaceState: WorkspaceExportedState | null = null;
private _workspaceCount: number = 0;
private _services: Record<string, any> = {};
private _ollama: Record<string, any> = {};
private _cronData: any = {};
private _slackChannels: string[] = [];
private _sprintIssues: any[] = [];
private _meetData: any = {};
private _cachedSprintState: SprintState | null = null;
private _cachedAgentStats: AgentStats | null = null;
private _cachedMemoryHealth: {...} | null = null;
private _cachedMemoryFiles: {...} | null = null;
private _cachedCurrentWork: {...} | null = null;
private _cachedCronConfig: {...} | null = null;
private _cachedCronHistory: CronExecution[] = [];
private _skillsCache: SkillDefinition[] | null = null;
private _personasCache: Persona[] | null = null;
private _toolModulesCache: ToolModule[] | null = null;
// ... and more
```

**Why this is bad:**
- No single source of truth
- Cache invalidation is manual and error-prone
- Each cache has its own loading/refreshing logic
- State updates scattered across 50+ methods

### Problem 2: UI Communication Coupling

Every business method directly calls `this._panel.webview.postMessage()`:

```typescript
private async handleMeetingApproval(meetingId: string, meetUrl: string, mode: string) {
  const result = await dbus.meet_approve(meetingId, mode);
  if (result.success) {
    // Business logic mixed with UI communication
    this._panel.webview.postMessage({
      type: "meetingApproved",
      meetingId,
      success: true,
      mode,
    });
    vscode.window.showInformationMessage(`Meeting approved (${mode} mode)`);
    this._backgroundSync();  // Side effect
  }
}
```

**Why this is bad:**
- Business logic cannot be tested without mocking VSCode
- Methods have hidden dependencies (panel, webview)
- Cannot reuse logic in different contexts (CLI, API)
- Violates Single Responsibility Principle

### Problem 3: Notification Side Effects

185 calls to `vscode.window.show*` scattered throughout:

```typescript
vscode.window.showInformationMessage(`Meeting approved (${mode} mode)`);
vscode.window.showErrorMessage(`Failed to approve meeting: ${result.error}`);
vscode.window.showWarningMessage(`Session not found: ${sessionId}`);
```

**Why this is bad:**
- Cannot test business logic without UI popups
- No way to batch or suppress notifications
- Inconsistent notification patterns
- Hard to implement notification preferences

## Proposed Architecture

### Solution 1: Centralized State Store

Create a reactive state store that:
- Holds all cached state in one place
- Emits change events when state updates
- Handles cache invalidation automatically
- Provides typed accessors

```typescript
// src/state/StateStore.ts
export class StateStore extends EventEmitter {
  private state: AppState = {
    workspace: { workspaces: {}, count: 0 },
    services: {},
    meetings: { upcoming: [], active: [], history: [] },
    sprint: { issues: [], state: null },
    cron: { config: null, history: [] },
    slack: { channels: [], pending: [], config: null },
    memory: { health: null, files: null, currentWork: null },
    skills: { definitions: [], running: [], current: null },
    personas: [],
    tools: [],
    stats: null,
  };

  // Typed getters
  get workspace(): WorkspaceState { return this.state.workspace; }
  get meetings(): MeetingsState { return this.state.meetings; }

  // Typed setters that emit events
  setWorkspace(data: Partial<WorkspaceState>): void {
    this.state.workspace = { ...this.state.workspace, ...data };
    this.emit('workspace:changed', this.state.workspace);
  }

  // Batch updates
  update(updates: Partial<AppState>): void {
    Object.assign(this.state, updates);
    this.emit('state:changed', this.state);
  }

  // Cache invalidation
  invalidate(section?: keyof AppState): void {
    if (section) {
      this.state[section] = getDefaultState(section);
    } else {
      this.state = getDefaultAppState();
    }
    this.emit('state:invalidated', section);
  }
}
```

### Solution 2: Message Bus for UI Communication

Create a message bus that decouples business logic from UI:

```typescript
// src/messaging/MessageBus.ts
export interface UIMessage {
  type: string;
  payload: any;
}

export class MessageBus {
  private subscribers: Map<string, Set<(msg: UIMessage) => void>> = new Map();
  private webview: vscode.Webview | null = null;

  // Connect to webview (called once during panel setup)
  connect(webview: vscode.Webview): void {
    this.webview = webview;
  }

  // Business logic calls this - no direct webview dependency
  publish(type: string, payload: any): void {
    const msg = { type, payload };

    // Notify local subscribers (for testing, logging)
    this.subscribers.get(type)?.forEach(fn => fn(msg));
    this.subscribers.get('*')?.forEach(fn => fn(msg));

    // Send to webview if connected
    this.webview?.postMessage(msg);
  }

  // For testing and debugging
  subscribe(type: string, handler: (msg: UIMessage) => void): () => void {
    if (!this.subscribers.has(type)) {
      this.subscribers.set(type, new Set());
    }
    this.subscribers.get(type)!.add(handler);
    return () => this.subscribers.get(type)?.delete(handler);
  }
}
```

### Solution 3: Notification Service

Create a notification service that can be configured and tested:

```typescript
// src/services/NotificationService.ts
export enum NotificationType {
  INFO = 'info',
  WARNING = 'warning',
  ERROR = 'error',
}

export interface Notification {
  type: NotificationType;
  message: string;
  actions?: string[];
}

export class NotificationService {
  private enabled: boolean = true;
  private history: Notification[] = [];
  private listeners: Set<(n: Notification) => void> = new Set();

  // Business logic calls this
  notify(type: NotificationType, message: string, actions?: string[]): void {
    const notification = { type, message, actions };
    this.history.push(notification);
    this.listeners.forEach(fn => fn(notification));

    if (!this.enabled) return;

    switch (type) {
      case NotificationType.INFO:
        vscode.window.showInformationMessage(message, ...(actions || []));
        break;
      case NotificationType.WARNING:
        vscode.window.showWarningMessage(message, ...(actions || []));
        break;
      case NotificationType.ERROR:
        vscode.window.showErrorMessage(message, ...(actions || []));
        break;
    }
  }

  // For testing
  disable(): void { this.enabled = false; }
  enable(): void { this.enabled = true; }
  getHistory(): Notification[] { return [...this.history]; }
  onNotification(fn: (n: Notification) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}
```

### Solution 4: Domain Services

Extract business logic into domain-specific services:

```typescript
// src/services/MeetingService.ts
export class MeetingService {
  constructor(
    private dbus: DBusClient,
    private state: StateStore,
    private messages: MessageBus,
    private notifications: NotificationService,
  ) {}

  async approveMeeting(meetingId: string, mode: string): Promise<boolean> {
    const result = await this.dbus.meet_approve(meetingId, mode);

    if (result.success) {
      this.messages.publish('meetingApproved', { meetingId, success: true, mode });
      this.notifications.notify(NotificationType.INFO, `Meeting approved (${mode} mode)`);
      this.state.invalidate('meetings');
      return true;
    } else {
      this.messages.publish('meetingApproved', { meetingId, success: false, error: result.error });
      this.notifications.notify(NotificationType.ERROR, `Failed to approve meeting: ${result.error}`);
      return false;
    }
  }

  async rejectMeeting(meetingId: string): Promise<boolean> {
    const result = await this.dbus.meet_reject(meetingId);
    // ... similar pattern
  }

  // Pure business logic - no UI dependencies
  async joinMeeting(meetUrl: string, title: string, mode: string, videoEnabled: boolean): Promise<void> {
    this.notifications.notify(NotificationType.INFO, `🎥 Joining meeting: ${title}...`);
    this.messages.publish('meetingJoining', { meetUrl, title, status: 'joining' });

    try {
      const result = await this.dbus.meet_join(meetUrl, title, mode, videoEnabled);
      if (result.success) {
        this.messages.publish('meetingJoined', { meetUrl, title, success: true });
        this.state.invalidate('meetings');
      } else {
        this.messages.publish('meetingJoined', { meetUrl, title, success: false, error: result.error });
        this.notifications.notify(NotificationType.ERROR, `Failed to join meeting: ${result.error}`);
      }
    } catch (e: any) {
      // Handle timeout gracefully
      if (e.message.includes('timeout')) {
        this.notifications.notify(NotificationType.INFO, `🎥 Join in progress - please wait...`);
      } else {
        this.messages.publish('meetingJoined', { meetUrl, title, success: false, error: e.message });
        this.notifications.notify(NotificationType.ERROR, `Failed to join meeting: ${e.message}`);
      }
    }
  }
}
```

### Solution 5: Dependency Injection Container

Wire everything together with a simple DI container:

```typescript
// src/container.ts
export class Container {
  private instances: Map<string, any> = new Map();

  register<T>(key: string, factory: () => T): void {
    this.instances.set(key, factory());
  }

  get<T>(key: string): T {
    return this.instances.get(key) as T;
  }
}

// src/bootstrap.ts
export function createContainer(panel: vscode.WebviewPanel, extensionUri: vscode.Uri): Container {
  const container = new Container();

  // Core services
  container.register('state', () => new StateStore());
  container.register('messages', () => {
    const bus = new MessageBus();
    bus.connect(panel.webview);
    return bus;
  });
  container.register('notifications', () => new NotificationService());
  container.register('dbus', () => dbus);

  // Domain services
  container.register('meetingService', () => new MeetingService(
    container.get('dbus'),
    container.get('state'),
    container.get('messages'),
    container.get('notifications'),
  ));
  container.register('slackService', () => new SlackService(...));
  container.register('sprintService', () => new SprintService(...));
  container.register('cronService', () => new CronService(...));
  container.register('sessionService', () => new SessionService(...));

  return container;
}
```

## Refactored CommandCenterPanel

After extraction, `CommandCenterPanel` becomes a thin coordinator:

```typescript
export class CommandCenterPanel {
  private container: Container;
  private state: StateStore;
  private messages: MessageBus;

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, dataProvider: WorkflowDataProvider) {
    this.container = createContainer(panel, extensionUri);
    this.state = this.container.get('state');
    this.messages = this.container.get('messages');

    // Wire up state changes to UI updates
    this.state.on('state:changed', () => this.updateHtml());

    // Wire up message handlers to services
    this.setupMessageHandlers();

    // Initial render
    this.updateHtml();

    // Start background sync
    this.startBackgroundSync();
  }

  private setupMessageHandlers(): void {
    const meetingService = this.container.get<MeetingService>('meetingService');

    this._messageRouter = new MessageRouter()
      .register(new MeetingMessageHandler({
        onApproveMeeting: (id, url, mode) => meetingService.approveMeeting(id, mode),
        onRejectMeeting: (id) => meetingService.rejectMeeting(id),
        onJoinMeetingNow: (url, title, mode, video) => meetingService.joinMeeting(url, title, mode, video),
        // ... etc
      }));
  }

  private async startBackgroundSync(): Promise<void> {
    const syncService = this.container.get<SyncService>('syncService');
    setInterval(() => syncService.sync(), 10000);
  }
}
```

## Implementation Plan

### Phase 1: Infrastructure (Low Risk)
1. Create `StateStore` class
2. Create `MessageBus` class
3. Create `NotificationService` class
4. Create `Container` class

### Phase 2: Extract Services (Medium Risk)
1. `MeetingService` - Meeting bot control methods (~35 methods)
2. `SlackService` - Slack integration methods (~20 methods)
3. `SprintService` - Sprint management methods (~10 methods)
4. `CronService` - Cron management methods (~10 methods)
5. `SessionService` - Session management methods (~15 methods)
6. `MemoryService` - Memory browser methods (~10 methods)
7. `SkillService` - Skill management methods (~10 methods)

### Phase 3: Migrate State (Medium Risk)
1. Move all `_cached*` variables to `StateStore`
2. Update all state reads to use `StateStore`
3. Update all state writes to use `StateStore.set*()`
4. Remove individual cache invalidation calls

### Phase 4: Migrate UI Communication (Low Risk)
1. Replace `this._panel.webview.postMessage()` with `this.messages.publish()`
2. Replace `vscode.window.show*()` with `this.notifications.notify()`
3. Remove direct panel/webview references from services

### Phase 5: Cleanup (Low Risk)
1. Remove dead code from `CommandCenterPanel`
2. Update tests to use new services
3. Document new architecture

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| `commandCenter.ts` lines | 6,393 | ~800 |
| Private cache variables | 25+ | 0 |
| Direct postMessage calls | 89 | 0 |
| Direct notification calls | 185 | 0 |
| Testable business logic | ~10% | ~90% |

## Benefits

1. **Testability** - Services can be unit tested without VSCode mocks
2. **Reusability** - Services can be used from CLI, API, or other UIs
3. **Maintainability** - Each service has single responsibility
4. **Debuggability** - State changes are centralized and observable
5. **Extensibility** - New features just add new services
6. **Type Safety** - Typed state store prevents runtime errors
