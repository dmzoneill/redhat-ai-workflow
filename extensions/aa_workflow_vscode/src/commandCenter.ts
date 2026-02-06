/**
 * Command Center - Unified Tabbed Interface
 *
 * Single panel that consolidates all AI Workflow views into tabs:
 * - Overview: Agent stats, current work, environments
 * - Skills: Skill browser + real-time execution flowchart
 * - Services: Slack bot, MCP server, D-Bus explorer
 * - Memory: Memory browser, session logs, patterns
 *
 * Features:
 * - Auto-switches to Skills tab when a skill starts executing
 * - Programmatic tab switching via postMessage API
 * - Real-time updates from file watchers and D-Bus
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import * as http from "http";
import { spawn } from "child_process";
import { WorkflowDataProvider } from "./dataProvider";
import { getSkillsDir, getMemoryDir } from "./paths";
import { CONFIG_FILE, AA_CONFIG_DIR, DBUS_SERVICES } from "./constants";
import { getStateStore, StateStore } from "./state";
import {
  Container,
  createContainer,
  getMessageBus,
  getNotificationService,
  MeetingService,
  SlackService,
  SessionService,
  CronService,
  SprintService,
  VideoService,
  NotificationType,
} from "./services";
import type {
  ChatSession,
  WorkspaceState,
  WorkspaceExportedState,
  SkillStep,
  SkillExecution,
  RunningSkillSummary,
  ToolDefinitionCC as ToolDefinition,
  ToolModuleCC as ToolModule,
  PersonaCC as Persona,
  MeetingReference,
  SkillDefinition,
  CronJob,
  CronExecution,
  AgentStats,
} from "./data/types";
import { loadMeetBotState, getUpcomingMeetingsHtml, MeetBotState } from "./meetingsRenderer";
import { loadSprintHistory, loadToolGapRequests, getSprintTabContent, SprintState } from "./sprintRenderer";
import { loadPerformanceState, PerformanceState } from "./performanceRenderer";
import { createLogger } from "./logger";
// NOTE: RefreshCoordinator removed - it was sending messages that were never handled in the webview.
// UI updates now go through TabManager and tabContentUpdate messages.
import { dbus } from "./dbusClient";
import { execAsync, getNonce } from "./utils";
import {
  MessageRouter,
  MessageContext,
  UtilityMessageHandler,
  CommandMessageHandler,
  SessionMessageHandler,
  // NOTE: SprintMessageHandler removed - SprintTab handles sprintAction directly
  // NOTE: MeetingMessageHandler removed - MeetingsTab handles meeting messages directly
  SlackMessageHandler,
  // NOTE: SkillMessageHandler removed - SkillsTab handles skill messages directly
  ServiceMessageHandler,
  // NOTE: CronMessageHandler removed - CronTab handles cron messages directly
  MeetingHistoryMessageHandler,
  VideoPreviewMessageHandler,
  MeetingAudioMessageHandler,
  InferenceMessageHandler,
  SlackPersonaTestHandler,
  // NOTE: PersonaMessageHandler removed - PersonasTab handles persona messages directly
  WorkspaceMessageHandler,
  TabMessageHandler,
  CreateSessionMessageHandler,
  PerformanceMessageHandler,
  TabManager,
  HtmlGenerator,
} from "./panels";

const logger = createLogger("CommandCenter");

// Debug logging - uses the main AI Workflow output channel
function debugLog(msg: string) {
  logger.log(msg);
}

// Constants imported from ./constants.ts
// Types imported from ./data/types.ts


// ============================================================================
// Command Center Panel
// ============================================================================

export class CommandCenterPanel {
  public static currentPanel: CommandCenterPanel | undefined;
  private readonly _panel: vscode.WebviewPanel;
  private readonly _extensionUri: vscode.Uri;
  private readonly _dataProvider: WorkflowDataProvider;
  private _disposables: vscode.Disposable[] = [];
  private _refreshInterval: NodeJS.Timeout | undefined;
  private _executionWatcher: fs.FSWatcher | undefined;
  private _workspaceWatcher: fs.FSWatcher | undefined;
  private _currentExecution: SkillExecution | undefined;
  private _runningSkills: RunningSkillSummary[] = [];  // All running skills
  private _currentTab: string = "overview";
  private _workspaceState: WorkspaceExportedState | null = null;
  private _workspaceCount: number = 0;
  private _sessionGroupBy: 'none' | 'project' | 'persona' = 'project';
  private _sessionViewMode: 'card' | 'table' = 'card';
  private _personaViewMode: 'card' | 'table' = 'card';

  // Cached personas for skill lookup
  private _personasCache: Persona[] | null = null;

  // Message router for handling webview messages
  private _messageRouter: MessageRouter;

  // Tab manager for modular tab handling
  private _tabManager: TabManager;

  // HTML generator for modular HTML generation
  private _htmlGenerator: HtmlGenerator | null = null;

  // ============================================================================
  // New Architecture: Services and State
  // ============================================================================

  // Dependency injection container
  private _container: Container | null = null;

  // Centralized state store (replaces scattered cache variables)
  private _stateStore: StateStore;

  // Domain services (extracted business logic)
  private _meetingService: MeetingService | null = null;
  private _slackService: SlackService | null = null;
  private _sessionService: SessionService | null = null;
  private _cronService: CronService | null = null;
  private _sprintService: SprintService | null = null;
  private _videoService: VideoService | null = null;

  // Service state (loaded via D-Bus from daemons)
  // TODO: Migrate these to StateStore
  private _services: Record<string, any> = {};
  private _ollama: Record<string, any> = {};
  private _cronData: any = {};
  private _slackChannels: string[] = [];
  private _sprintIssues: any[] = [];
  private _sprintIssuesUpdated: string = "";
  private _meetData: any = {};
  // Cached sprint state from D-Bus (for sync access in UI updates)
  private _cachedSprintState: SprintState | null = null;

  // NOTE: _refreshCoordinator removed - UI updates now go through TabManager

  // Debounce timer for workspace watcher
  private _workspaceWatcherDebounce: NodeJS.Timeout | null = null;

  public static createOrShow(
    extensionUri: vscode.Uri,
    dataProvider: WorkflowDataProvider,
    initialTab?: string
  ) {
    debugLog(`createOrShow() called - initialTab: ${initialTab || 'none'}`);
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;
    debugLog(`createOrShow() - column: ${column}, currentPanel exists: ${!!CommandCenterPanel.currentPanel}`);

    if (CommandCenterPanel.currentPanel) {
      debugLog("createOrShow() - reusing existing panel, revealing...");
      CommandCenterPanel.currentPanel._panel.reveal(column);
      if (initialTab) {
        debugLog(`createOrShow() - switching to tab: ${initialTab}`);
        CommandCenterPanel.currentPanel.switchTab(initialTab);
      }
      return CommandCenterPanel.currentPanel;
    }

    debugLog("createOrShow() - creating NEW panel");
    // Allow access to screenshot directory for meeting images
    const homeDir = process.env.HOME || process.env.USERPROFILE || '';
    const screenshotDir = vscode.Uri.file(`${homeDir}/.config/aa-workflow/meet_bot/screenshots`);
    debugLog(`createOrShow() - screenshotDir: ${screenshotDir.fsPath}`);

    const panel = vscode.window.createWebviewPanel(
      "aaCommandCenter",
      "AI Workflow Command Center",
      column || vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [extensionUri, screenshotDir],
      }
    );
    debugLog("createOrShow() - webview panel created");

    CommandCenterPanel.currentPanel = new CommandCenterPanel(
      panel,
      extensionUri,
      dataProvider,
      initialTab
    );
    debugLog("createOrShow() - CommandCenterPanel instance created");

    return CommandCenterPanel.currentPanel;
  }

  public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, dataProvider: WorkflowDataProvider) {
    debugLog("revive() called - restoring panel from VS Code");
    CommandCenterPanel.currentPanel = new CommandCenterPanel(panel, extensionUri, dataProvider);
    // Also update the module-level variable so getCommandCenterPanel() works after revive
    commandCenterPanel = CommandCenterPanel.currentPanel;
  }

  /**
   * Switch to a specific tab programmatically
   */
  public switchTab(tabId: string) {
    this._currentTab = tabId;
    this._panel.webview.postMessage({ command: "switchTab", tab: tabId });
  }

  /**
   * Update skill execution state (called by watcher)
   * This updates the currently selected/viewed execution
   */
  public updateSkillExecution(execution: SkillExecution) {
    this._currentExecution = execution;

    // Route through TabManager so SkillsTab can update the workflow view
    debugLog(`updateSkillExecution: ${execution.skillName} step ${execution.currentStepIndex}/${execution.totalSteps}`);
    this._tabManager.handleMessage({
      command: "skillExecutionUpdate",
      execution,
    }).then(handled => {
      debugLog(`updateSkillExecution: handled=${handled}`);
    });
  }

  /**
   * Update the list of all running skills (called by watcher)
   * This updates the Running Skills panel
   */
  public updateRunningSkills(runningSkills: RunningSkillSummary[]) {
    this._runningSkills = runningSkills;

    // Get stale count from watcher
    let staleCount = 0;
    try {
      const { getSkillExecutionWatcher } = require("./skillExecutionWatcher");
      const watcher = getSkillExecutionWatcher();
      if (watcher) {
        staleCount = watcher.getStaleExecutionCount();
      }
    } catch (e) {
      // Ignore errors getting stale count
    }

    // Directly update the SkillsTab through TabManager
    // This is more reliable than postMessage since the webview message handler
    // doesn't forward runningSkillsUpdate to tabs
    debugLog(`updateRunningSkills: ${runningSkills.length} skills, ${staleCount} stale`);
    this._tabManager.handleMessage({
      command: "runningSkillsUpdate",
      runningSkills,
      staleCount,
    }).then(handled => {
      debugLog(`updateRunningSkills: handled=${handled}`);
    });
  }

  private constructor(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri,
    dataProvider: WorkflowDataProvider,
    initialTab?: string
  ) {
    debugLog("Constructor called - setting up panel");
    debugLog(`Constructor - initialTab: ${initialTab || 'overview'}`);
    this._panel = panel;
    this._extensionUri = extensionUri;
    this._dataProvider = dataProvider;
    this._currentTab = initialTab || "overview";

    // ========================================================================
    // Initialize new architecture: Container, StateStore, and Services
    // ========================================================================
    debugLog("Constructor - initializing StateStore...");
    // Initialize centralized state store
    this._stateStore = getStateStore();
    debugLog("Constructor - StateStore initialized");

    debugLog("Constructor - creating DI Container...");
    // Initialize DI container with panel context
    this._container = createContainer({ panel, extensionUri });
    debugLog("Constructor - Container created");

    debugLog("Constructor - connecting MessageBus to webview...");
    // Connect MessageBus to webview
    const messageBus = getMessageBus();
    messageBus.connect(panel.webview);
    debugLog("Constructor - MessageBus connected");

    debugLog("Constructor - initializing services...");
    // Initialize MeetingService with dependencies
    this._meetingService = new MeetingService({
      state: this._stateStore,
      messages: messageBus,
      notifications: getNotificationService(),
    });
    debugLog("Constructor - MeetingService initialized");

    // Wire up sync callback so MeetingService can trigger refreshes
    this._meetingService.setOnSyncRequested(() => this._backgroundSync());

    // Initialize SlackService with dependencies
    this._slackService = new SlackService({
      state: this._stateStore,
      messages: messageBus,
      notifications: getNotificationService(),
    });
    debugLog("Constructor - SlackService initialized");

    // Initialize SessionService with dependencies
    this._sessionService = new SessionService({
      state: this._stateStore,
      messages: messageBus,
      notifications: getNotificationService(),
    });
    debugLog("Constructor - SessionService initialized");

    // Initialize CronService with dependencies
    this._cronService = new CronService({
      state: this._stateStore,
      messages: messageBus,
      notifications: getNotificationService(),
    });
    debugLog("Constructor - CronService initialized");

    // Initialize SprintService with dependencies
    this._sprintService = new SprintService({
      state: this._stateStore,
      messages: messageBus,
      notifications: getNotificationService(),
      queryDBus: (service, path, iface, method, args) => this.queryDBus(service, path, iface, method, args),
    });
    debugLog("Constructor - SprintService initialized");

    // Wire up refresh callback for SprintService
    this._sprintService.setOnRefreshUI(() => this._loadSprintFromFile());

    // Initialize VideoService with dependencies
    this._videoService = new VideoService({
      state: this._stateStore,
      messages: messageBus,
      notifications: getNotificationService(),
      queryDBus: (service, path, iface, method, args) => this.queryDBus(service, path, iface, method, args),
    });
    debugLog("Constructor - VideoService initialized");

    debugLog("Constructor - all services initialized successfully");

    // Initialize the message router with all handlers
    this._messageRouter = new MessageRouter()
      .register(new UtilityMessageHandler())
      .register(new CommandMessageHandler())
      .register(new SessionMessageHandler({
        // NOTE: copySessionId, searchSessions removed - SessionsTab handles them directly
        onRefresh: () => this._syncAndRefreshSessions(),
        onOpenChatSession: async (sessionId: string, sessionName?: string) => {
          await this._sessionService!.openChatSession(sessionId, sessionName);
        },
        onViewMeetingNotes: async (sessionId: string) => {
          await this._sessionService!.viewMeetingNotes(sessionId);
        },
      }))
      // NOTE: SprintMessageHandler removed - SprintTab handles sprintAction directly via D-Bus
      // NOTE: MeetingMessageHandler removed - MeetingsTab handles meeting messages directly via D-Bus
      .register(new SlackMessageHandler({
        // NOTE: sendSlackMessage, approveSlackMessage, rejectSlackMessage, approveAllSlack removed
        // - SlackTab handles them directly via D-Bus
        onLoadHistory: async () => {
          await this._slackService!.loadHistory();
        },
        onReplyToThread: async (channel: string, text: string, threadTs?: string) => {
          await this._slackService!.sendMessage(channel, text, threadTs || "");
        },
        onRefreshChannels: async () => {
          await this._slackService!.getMyChannels();
        },
        onSearchUsers: async (query: string) => {
          await this._slackService!.searchUsers(query);
        },
        onRefreshTargets: async () => {
          await this._slackService!.getMyChannels();
        },
        onSearchMessages: async (query: string) => {
          await this._slackService!.searchMessages(query);
        },
        onRefreshPending: async () => {
          await this._slackService!.getPending();
        },
        onRefreshCache: async () => {
          await this._slackService!.refreshCache();
        },
        onRefreshCacheStats: async () => {
          await this._slackService!.getCacheStats();
        },
        onLoadChannelBrowser: async (query: string) => {
          await this._slackService!.findChannel(query);
        },
        onLoadUserBrowser: async (query: string) => {
          await this._slackService!.findUser(query);
        },
        onLoadCommands: async () => {
          await this._slackService!.getCommands();
        },
        onSendCommand: async (commandName: string, args: any) => {
          await this._slackService!.sendCommand(commandName, args);
        },
        onLoadConfig: async () => {
          await this._slackService!.getConfig();
        },
        onSetDebugMode: async (enabled: boolean) => {
          await this._slackService!.setDebugMode(enabled);
        },
      }))
      // NOTE: SkillMessageHandler removed - SkillsTab handles skill messages directly
      .register(new ServiceMessageHandler({
        // NOTE: refreshServices, serviceControl, testOllamaInstance removed - ServicesTab handles them directly
        onQueryDBus: (service: string, method: string, args: any[]) => this.handleDBusQuery(service, method, args as unknown as Record<string, string>),
        onRefreshOllamaStatus: async () => { this._backgroundSync(); },
      }))
      // NOTE: CronMessageHandler removed - CronTab handles cron messages directly via D-Bus
      .register(new MeetingHistoryMessageHandler({
        // Using MeetingService for decoupled business logic
        onViewNote: (noteId: string) => this._handleViewNoteWithService(parseInt(noteId, 10)),
        onViewTranscript: (noteId: string) => this._handleViewTranscriptWithService(parseInt(noteId, 10)),
        onViewBotLog: (noteId: string) => this._handleViewBotLogWithService(parseInt(noteId, 10)),
        onViewLinkedIssues: (noteId: string) => this._handleViewLinkedIssuesWithService(parseInt(noteId, 10)),
        onSearchNotes: async (query: string) => {
          await this._meetingService!.searchNotes(query);
        },
        onCopyTranscript: async () => {
          await this._meetingService!.copyTranscript();
        },
        onClearCaptions: async () => {
          await this._meetingService!.clearCaptions();
        },
      }))
      .register(new VideoPreviewMessageHandler({
        // Using VideoService for decoupled business logic
        onStartVideoPreview: async (device: string, mode: string) => {
          await this._videoService!.startPreview(device, mode as any);
        },
        onStopVideoPreview: async () => {
          await this._videoService!.stopPreview();
        },
        onGetVideoPreviewFrame: async () => {
          await this._videoService!.captureAndPublishFrame();
        },
      }))
      .register(new MeetingAudioMessageHandler({
        // Using MeetingService for decoupled business logic
        onMuteAudio: async (sessionId: string) => {
          await this._meetingService!.muteAudio(sessionId);
        },
        onUnmuteAudio: async (sessionId: string) => {
          await this._meetingService!.unmuteAudio(sessionId);
        },
        onTestTTS: async (sessionId: string) => {
          await this._meetingService!.testTTS(sessionId);
        },
        onTestAvatar: async (sessionId: string) => {
          await this._meetingService!.testAvatar(sessionId);
        },
        onPreloadJira: async (sessionId: string) => {
          await this._meetingService!.preloadJira(sessionId);
        },
        onSetDefaultMode: async (mode: string) => {
          await this._meetingService!.setDefaultMode(mode);
        },
      }))
      .register(new InferenceMessageHandler({
        onRunInferenceTest: (message: string, persona: string, skill: string) => this.runInferenceTest(message, persona, skill),
        onGetInferenceStats: () => this.getInferenceStats(),
        onUpdateInferenceConfig: (key: string, value: any) => this.updateInferenceConfig(key, value),
        onSemanticSearch: (query: string, project: string) => this.executeSemanticSearch(query, project),
        onResetInferenceConfig: () => this.resetInferenceConfig(),
        onSaveInferenceConfig: () => this.saveInferenceConfig(),
      }))
      .register(new SlackPersonaTestHandler({
        onRunPersonaTest: (query: string) => this.runContextTest(query),
        onFetchContextStatus: () => this.fetchContextStatus(),
      }))
      // NOTE: PersonaMessageHandler removed - PersonasTab handles persona messages directly
      .register(new WorkspaceMessageHandler({
        // NOTE: changeSessionGroupBy, changeSessionViewMode, refreshSessionsNow removed - SessionsTab handles them directly
        onViewWorkspaceTools: (uri: string) => this._viewWorkspaceTools(uri),
        onSwitchToWorkspace: (uri: string) => this._switchToWorkspace(uri),
        onChangeWorkspacePersona: (uri: string, persona: string) => this._changeWorkspacePersona(uri, persona),
        onRemoveWorkspace: (uri: string) => this._removeWorkspace(uri),
      }))
      .register(new TabMessageHandler({
        onSwitchTab: (tab: string) => {
          this._currentTab = tab;
          // Also update the TabManager's active tab so getActiveTab() returns the correct tab
          this._tabManager.switchTab(tab);
          logger.log(`Switched to tab: ${tab}`);
          if (tab === "sprint") {
            logger.log("Sprint tab selected - loading from file (no sync)");
            this._loadSprintFromFile();
          }
          // Re-render the tab content to show latest data
          // This is needed because tab data may have changed while viewing another tab
          this._triggerTabRerender();
        },
        onOpenConfigFile: () => this.openConfigFile(),
        onRefreshIssues: () => this._backgroundSync(),
      }))
      .register(new CreateSessionMessageHandler({
        onCreateSessionAction: (action: string, message: any) => this.handleCreateSessionAction(action, message),
      }))
      .register(new PerformanceMessageHandler({
        onPerformanceAction: (action: string, questionId?: string, category?: string, description?: string) =>
          this.handlePerformanceAction(action, questionId, category, description),
      }));

    debugLog("Constructor - initializing TabManager...");
    // Initialize the tab manager
    this._tabManager = new TabManager();
    this._tabManager.setContext({
      extensionUri: this._extensionUri,
      webview: this._panel.webview,
    });
    // Inject services into tabs so they can use Services instead of D-Bus directly
    this._tabManager.setServices({
      meeting: this._meetingService,
      slack: this._slackService,
      session: this._sessionService,
      cron: this._cronService,
      sprint: this._sprintService,
      video: this._videoService,
    });
    // Set up render callback so tabs can trigger re-renders when their state changes
    this._tabManager.setRenderCallback(() => {
      debugLog("Tab requested re-render");
      this._triggerTabRerender();
    });
    debugLog("Constructor - TabManager initialized");

    debugLog("Constructor - initializing HtmlGenerator...");
    // Initialize the HTML generator
    this._htmlGenerator = new HtmlGenerator(this._tabManager, {
      extensionUri: this._extensionUri,
      webview: this._panel.webview,
      currentTab: this._currentTab,
    });
    debugLog("Constructor - HtmlGenerator initialized");

    // NOTE: RefreshCoordinator removed - UI updates go through TabManager

    // CRITICAL: Set up message handler FIRST, before any HTML is set
    // This ensures we don't miss any messages from the webview
    debugLog("Constructor - setting up onDidReceiveMessage handler FIRST");
    this._panel.webview.onDidReceiveMessage(
      async (message) => {
        // Support both 'command' and 'type' message formats
        const msgType = message.command || message.type;
        debugLog(`Received message: ${msgType} - ${JSON.stringify(message)}`);

        // First, try to handle via TabManager (for tab-specific messages)
        const handledByTab = await this._tabManager.handleMessage(message);
        if (handledByTab) {
          debugLog(`Message handled by TabManager: ${msgType}`);
          return;
        }

        // Second, try to handle via MessageRouter
        const routerContext: MessageContext = {
          panel: this._panel,
          extensionUri: this._extensionUri,
          postMessage: (msg) => this._panel.webview.postMessage(msg),
        };
        const handledByRouter = await this._messageRouter.route(message, routerContext);
        if (handledByRouter) {
          debugLog(`Message handled by MessageRouter: ${msgType}`);
          return;
        }

        // All messages should be handled by TabManager or MessageRouter
        // Log any unhandled messages for debugging
        debugLog(`Unhandled message type: ${msgType}`);
      },
      null,
      this._disposables
    );

    // Now set up the rest of the panel after message handler is ready
    debugLog("Constructor - setting up onDidDispose handler");
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // Handle panel visibility changes (e.g., after system wake or tab switch)
    debugLog("Constructor - setting up onDidChangeViewState handler");
    this._panel.onDidChangeViewState(
      (e) => {
        if (e.webviewPanel.visible) {
          debugLog("Panel became visible - refreshing data");
          // Background sync will refresh tab data
          this._backgroundSync();
        }
      },
      null,
      this._disposables
    );

    // Load workspace state before first render
    debugLog("Constructor - loading workspace state...");
    this._loadWorkspaceState();
    debugLog("Constructor - workspace state loaded");

    // Set the HTML content (this may trigger messages from the webview)
    debugLog("Constructor - calling update(true) for initial HTML render...");
    this.update(true); // Force full render on initial load
    debugLog("Constructor - update(true) completed");

    debugLog("Constructor - starting execution watcher...");
    this.startExecutionWatcher();
    debugLog("Constructor - execution watcher started");

    debugLog("Constructor - setting up workspace watcher...");
    this._setupWorkspaceWatcher();
    debugLog("Constructor - workspace watcher setup complete");

    // Initial data dispatch after first load (environments and inference stats are separate)
    setTimeout(() => {
      this._dispatchAllUIUpdates();
      this.checkEnvironmentHealth();
      this.getInferenceStats();
      // Also refresh service status via D-Bus on initial load
      this._refreshServicesViaDBus().catch(e => {
        debugLog(`Failed to refresh services via D-Bus on init: ${e}`);
      });
      // Load Slack discovery data via SlackService
      if (this._slackService) {
        this._slackService.getCacheStats().catch(e => {
          debugLog(`Failed to load Slack cache stats on init: ${e}`);
        });
        this._slackService.findChannel("").catch(e => {
          debugLog(`Failed to load Slack channel browser on init: ${e}`);
        });
        this._slackService.findUser("").catch(e => {
          debugLog(`Failed to load Slack user browser on init: ${e}`);
        });
        this._slackService.getPending().catch(e => {
          debugLog(`Failed to load Slack pending on init: ${e}`);
        });
        this._slackService.getConfig().catch(e => {
          debugLog(`Failed to load Slack config on init: ${e}`);
        });
        this._slackService.getMyChannels().catch(e => {
          debugLog(`Failed to load Slack targets on init: ${e}`);
        });
      }
      // Load sprint issues for the Overview page
      this._loadSprintFromFile();
    }, 500);

    // Tiered auto-refresh using epoch time modulo for different data types:
    // - Every 1 second: Session state (active session detection - critical for UI)
    // - Every 5 seconds: Meetings (current meeting status, countdown timers)
    // - Every 10 seconds: Everything else (services, ollama, MCP, inference stats)
    // This provides responsive session updates while avoiding excessive polling for slower-changing data
    this._refreshInterval = setInterval(() => {
      this._tieredBackgroundSync();
    }, 1000);

    debugLog("Constructor complete - panel ready");
  }

  private async refreshOllamaStatus(): Promise<void> {
    try {
      // Check Ollama instances via systemd status (system-level services)
      const instances = [
        { name: "npu", port: 11434, unit: "ollama-npu.service" },
        { name: "igpu", port: 11435, unit: "ollama-igpu.service" },
        { name: "nvidia", port: 11436, unit: "ollama-nvidia.service" },
        { name: "cpu", port: 11437, unit: "ollama-cpu.service" },
      ];

      const statuses: Record<string, any> = {};

      // Check all instances via single systemctl call
      const { stdout } = await execAsync(
        "systemctl is-active ollama-npu.service ollama-igpu.service ollama-nvidia.service ollama-cpu.service 2>/dev/null || true"
      );
      const states = stdout.trim().split("\n");

      instances.forEach((inst, idx) => {
        const isActive = states[idx] === "active";
        statuses[inst.name] = {
          available: isActive,
          port: inst.port,
        };
      });

      // Update internal cache for tab badge calculation
      this._ollama = statuses;

      this._panel.webview.postMessage({
        command: "ollamaStatusUpdate",
        data: statuses,
      });
    } catch (error) {
      debugLog(`Failed to refresh Ollama status: ${error}`);
      this._panel.webview.postMessage({
        command: "ollamaStatusUpdate",
        error: String(error),
      });
    }
  }

  private async testOllamaInstance(instance: string): Promise<void> {
    const portMap: Record<string, number> = {
      npu: 11434,
      igpu: 11435,
      nvidia: 11436,
      cpu: 11437,
    };
    const port = portMap[instance] || 11434;

    const startTime = Date.now();
    const postData = JSON.stringify({
      model: "qwen2.5:0.5b",
      prompt: "Say hello in one word:",
      stream: false,
      options: { num_predict: 10 },
    });

    const req = http.request(
      {
        hostname: "localhost",
        port: port,
        path: "/api/generate",
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(postData),
        },
        timeout: 30000,
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => {
          data += chunk;
        });
        res.on("end", () => {
          const latency = Date.now() - startTime;
          if (res.statusCode === 200) {
            try {
              const parsed = JSON.parse(data) as { response?: string };
              this._panel.webview.postMessage({
                command: "ollamaTestResult",
                instance,
                data: { success: true, response: parsed.response || "", latency },
              });
            } catch {
              this._panel.webview.postMessage({
                command: "ollamaTestResult",
                instance,
                error: "Invalid JSON response",
              });
            }
          } else {
            this._panel.webview.postMessage({
              command: "ollamaTestResult",
              instance,
              error: `HTTP ${res.statusCode}`,
            });
          }
        });
      }
    );

    req.on("error", (error) => {
      debugLog(`Failed to test ${instance}: ${error}`);
      this._panel.webview.postMessage({
        command: "ollamaTestResult",
        instance,
        error: String(error),
      });
    });

    req.on("timeout", () => {
      req.destroy();
      this._panel.webview.postMessage({
        command: "ollamaTestResult",
        instance,
        error: "Request timeout",
      });
    });

    req.write(postData);
    req.end();
  }

  private async runInferenceTest(message: string, persona: string, skill: string): Promise<void> {
    debugLog(`runInferenceTest called: message="${message}", persona="${persona}", skill="${skill}"`);

    if (!message) {
      debugLog("runInferenceTest: No message provided, aborting");
      vscode.window.showWarningMessage("Please enter a test message");
      return;
    }

    try {
      // Get the project root from workspace folders (not extension install location)
      const workspaceFolders = vscode.workspace.workspaceFolders;
      const projectRoot = workspaceFolders && workspaceFolders.length > 0
        ? workspaceFolders[0].uri.fsPath
        : path.join(os.homedir(), "src", "redhat-ai-workflow");

      // Use external Python script instead of inline script
      const scriptPath = path.join(this._extensionUri.fsPath, "scripts", "inference_test.py");
      const args = [
        scriptPath,
        "--message", message,
        "--persona", persona,
        "--project-root", projectRoot,
      ];
      if (skill) {
        args.push("--skill", skill);
      }

      debugLog(`Running inference with scriptPath: ${scriptPath}`);
      debugLog(`Args: ${args.join(" ")}`);

      const python = spawn("python3", args, {
        cwd: projectRoot,
      });
      let output = "";
      let errorOutput = "";

      debugLog(`Python process spawned, pid: ${python.pid}`);

      // Set a timeout to kill the process if it takes too long
      // NPU inference can take 30-60s on first run (model loading)
      const timeoutId = setTimeout(() => {
        debugLog("Python process timed out after 120s, killing...");
        python.kill();
        this._panel.webview.postMessage({
          command: "inferenceTestResult",
          data: {
            tools: ["skill_run", "jira_view_issue", "gitlab_mr_view"],
            tool_count: 3,
            reduction_pct: 98.6,
            methods: ["timeout_fallback"],
            persona: persona,
            skill_detected: skill || null,
            latency_ms: 120000,
            message_preview: message.substring(0, 50),
            error: "Inference timed out after 120 seconds (NPU may need warming up)",
          },
        });
      }, 120000);

      python.stdout.on("data", (data: Buffer) => {
        output += data.toString();
        debugLog(`Python stdout: ${data.toString().substring(0, 200)}`);
      });

      python.stderr.on("data", (data: Buffer) => {
        errorOutput += data.toString();
        debugLog(`Python stderr: ${data.toString().substring(0, 500)}`);
      });

      python.on("error", (err: Error) => {
        clearTimeout(timeoutId);
        debugLog(`Python spawn error: ${err.message}`);
        this._panel.webview.postMessage({
          command: "inferenceTestResult",
          data: {
            tools: ["skill_run", "jira_view_issue", "gitlab_mr_view"],
            tool_count: 3,
            reduction_pct: 98.6,
            methods: ["spawn_error_fallback"],
            persona: persona,
            skill_detected: skill || null,
            latency_ms: 0,
            message_preview: message.substring(0, 50),
            error: "Failed to spawn Python: " + err.message,
          },
        });
      });

      python.on("close", (code: number) => {
        clearTimeout(timeoutId);
        debugLog(`Python closed with code: ${code}, output length: ${output.length}, stderr length: ${errorOutput.length}`);
        debugLog(`Raw output first 500 chars: ${output.substring(0, 500)}`);
        debugLog(`Raw output last 200 chars: ${output.substring(Math.max(0, output.length - 200))}`);
        if (errorOutput) {
          debugLog(`Stderr: ${errorOutput.substring(0, 500)}`);
        }
        try {
          const trimmedOutput = output.trim();
          debugLog(`Trimmed output length: ${trimmedOutput.length}`);
          const data = JSON.parse(trimmedOutput);
          debugLog(`Posting inferenceTestResult with ${data.tool_count} tools, persona: ${data.persona}`);
          this._panel.webview.postMessage({
            command: "inferenceTestResult",
            data,
          });
          debugLog("Posted inferenceTestResult to webview");
        } catch (parseErr) {
          debugLog(`Failed to parse output: ${parseErr}`);
          debugLog(`Full raw output: ${output}`);
          // Fallback to placeholder
          this._panel.webview.postMessage({
            command: "inferenceTestResult",
            data: {
              tools: ["skill_run", "jira_view_issue", "gitlab_mr_view"],
              tool_count: 3,
              reduction_pct: 98.6,
              methods: ["layer1_core", "layer2_persona"],
              persona: persona,
              skill_detected: skill || null,
              latency_ms: 2,
              message_preview: message.substring(0, 50),
              error: errorOutput || "Failed to parse response: " + String(parseErr),
            },
          });
        }
      });
    } catch (error) {
      // Fallback to placeholder on any error
      this._panel.webview.postMessage({
        command: "inferenceTestResult",
        data: {
          tools: ["skill_run", "jira_view_issue", "gitlab_mr_view"],
          tool_count: 3,
          reduction_pct: 98.6,
          methods: ["layer1_core", "layer2_persona"],
          persona: persona,
          skill_detected: skill || null,
          latency_ms: 2,
          message_preview: message.substring(0, 50),
          error: String(error),
        },
      });
    }
  }

  /**
   * Run context injection test.
   * Tests what knowledge sources would be used to answer a question.
   */
  private async runContextTest(query: string): Promise<void> {
    debugLog(`runContextTest called: query="${query}"`);

    if (!query) {
      debugLog("runContextTest: No query provided, aborting");
      vscode.window.showWarningMessage("Please enter a test query");
      return;
    }

    try {
      // Notify that test is starting - update SlackTab state
      const slackTab = this._tabManager.getTab("slack");
      if (slackTab) {
        slackTab.handleMessage({ command: "contextTestStarted" });
        slackTab.handleMessage({ command: "contextTestQueryUpdate", query });
      }
      this._panel.webview.postMessage({
        command: "contextTestStarted",
      });
      // Also send legacy command for compatibility
      this._panel.webview.postMessage({
        command: "personaTestStarted",
      });

      // Get the project root from workspace folders
      const workspaceFolders = vscode.workspace.workspaceFolders;
      const projectRoot = workspaceFolders && workspaceFolders.length > 0
        ? workspaceFolders[0].uri.fsPath
        : path.join(os.homedir(), "src", "redhat-ai-workflow");

      // Use external Python script
      const scriptPath = path.join(this._extensionUri.fsPath, "scripts", "slack_persona_test.py");
      const args = [
        scriptPath,
        "--query", query,
        "--project-root", projectRoot,
        "--include-jira",
        "--include-code",
        "--include-memory",
        "--include-inscope",
      ];

      debugLog(`Running context test with scriptPath: ${scriptPath}`);
      debugLog(`Args: ${args.join(" ")}`);

      const python = spawn("python3", args, {
        cwd: projectRoot,
      });
      let output = "";
      let errorOutput = "";

      debugLog(`Python process spawned, pid: ${python.pid}`);

      // Set a timeout (45 seconds - context gathering can take a while)
      const timeoutId = setTimeout(() => {
        debugLog("Python process timed out after 45s, killing...");
        python.kill();
        const timeoutData = {
          query: query,
          error: "Context gathering timed out after 45 seconds",
          sources: [],
          sources_used: [],
          total_results: 0,
        };
        // Update SlackTab state
        const slackTab = this._tabManager.getTab("slack");
        if (slackTab) {
          slackTab.handleMessage({ command: "contextTestResult", data: timeoutData });
        }
        this._panel.webview.postMessage({
          command: "contextTestResult",
          data: timeoutData,
        });
      }, 45000);

      python.stdout.on("data", (data: Buffer) => {
        output += data.toString();
        debugLog(`Python stdout: ${data.toString().substring(0, 200)}`);
      });

      python.stderr.on("data", (data: Buffer) => {
        errorOutput += data.toString();
        debugLog(`Python stderr: ${data.toString().substring(0, 500)}`);
      });

      python.on("error", (err: Error) => {
        clearTimeout(timeoutId);
        debugLog(`Python spawn error: ${err.message}`);
        const errorData = {
          query: query,
          error: "Failed to spawn Python: " + err.message,
          sources: [],
          sources_used: [],
          total_results: 0,
        };
        // Update SlackTab state
        const slackTab = this._tabManager.getTab("slack");
        if (slackTab) {
          slackTab.handleMessage({ command: "contextTestResult", data: errorData });
        }
        this._panel.webview.postMessage({
          command: "contextTestResult",
          data: errorData,
        });
      });

      python.on("close", (code: number) => {
        clearTimeout(timeoutId);
        debugLog(`Python closed with code: ${code}, output length: ${output.length}`);
        try {
          const trimmedOutput = output.trim();
          const data = JSON.parse(trimmedOutput);
          debugLog(`Posting contextTestResult with ${data.total_results} results`);
          
          // Update the SlackTab's state directly and trigger re-render
          const slackTab = this._tabManager.getTab("slack");
          if (slackTab) {
            slackTab.handleMessage({ command: "contextTestResult", data });
          }
          
          // Also send to webview for any direct UI updates
          this._panel.webview.postMessage({
            command: "contextTestResult",
            data,
          });
          // Also send legacy command for compatibility
          this._panel.webview.postMessage({
            command: "personaTestResult",
            data,
          });
        } catch (parseErr) {
          debugLog(`Failed to parse output: ${parseErr}`);
          const errorData = {
            query: query,
            error: errorOutput || "Failed to parse response: " + String(parseErr),
            sources: [],
            sources_used: [],
            total_results: 0,
          };
          // Update SlackTab state
          const slackTab = this._tabManager.getTab("slack");
          if (slackTab) {
            slackTab.handleMessage({ command: "contextTestResult", data: errorData });
          }
          this._panel.webview.postMessage({
            command: "personaTestResult",
            data: errorData,
          });
        }
      });
    } catch (error) {
      const errorData = {
        query: query,
        error: String(error),
        sources: [],
        sources_used: [],
        total_results: 0,
      };
      // Update SlackTab state
      const slackTab = this._tabManager.getTab("slack");
      if (slackTab) {
        slackTab.handleMessage({ command: "contextTestResult", data: errorData });
      }
      this._panel.webview.postMessage({
        command: "personaTestResult",
        data: errorData,
      });
    }
  }

  /**
   * Fetch context injection status without running a full test.
   * This is called on initial load to show the status of knowledge sources.
   */
  private async fetchContextStatus(): Promise<void> {
    debugLog("fetchContextStatus called");

    try {
      // Get the project root from workspace folders
      const workspaceFolders = vscode.workspace.workspaceFolders;
      const projectRoot = workspaceFolders && workspaceFolders.length > 0
        ? workspaceFolders[0].uri.fsPath
        : path.join(os.homedir(), "src", "redhat-ai-workflow");

      // Use external Python script with --status-only flag
      const scriptPath = path.join(this._extensionUri.fsPath, "scripts", "slack_persona_test.py");
      const args = [
        scriptPath,
        "--status-only",
        "--project-root", projectRoot,
      ];

      debugLog(`Running status fetch with scriptPath: ${scriptPath}`);

      const python = spawn("python3", args, {
        cwd: projectRoot,
      });
      let output = "";
      let errorOutput = "";

      // Set a shorter timeout for status-only (10 seconds)
      const timeoutId = setTimeout(() => {
        debugLog("Status fetch timed out after 10s, killing...");
        python.kill();
      }, 10000);

      python.stdout.on("data", (data: Buffer) => {
        output += data.toString();
      });

      python.stderr.on("data", (data: Buffer) => {
        errorOutput += data.toString();
        // Only log actual errors, not warnings
        if (!data.toString().includes("DeprecationWarning")) {
          debugLog(`Status fetch stderr: ${data.toString().substring(0, 200)}`);
        }
      });

      python.on("error", (err: Error) => {
        clearTimeout(timeoutId);
        debugLog(`Status fetch spawn error: ${err.message}`);
      });

      python.on("close", (code: number) => {
        clearTimeout(timeoutId);
        debugLog(`Status fetch closed with code: ${code}`);
        try {
          const trimmedOutput = output.trim();
          const data = JSON.parse(trimmedOutput);
          debugLog(`Posting contextTestResult (status only) with status: ${JSON.stringify(data.status)}`);
          // Update SlackTab state directly
          const slackTab = this._tabManager.getTab("slack");
          if (slackTab) {
            slackTab.handleMessage({ command: "contextTestResult", data });
          }
          // Send as contextTestResult so it populates the status in SlackTab
          this._panel.webview.postMessage({
            command: "contextTestResult",
            data,
          });
        } catch (parseErr) {
          debugLog(`Failed to parse status output: ${parseErr}`);
        }
      });
    } catch (error) {
      debugLog(`fetchContextStatus error: ${error}`);
    }
  }

  private async getInferenceStats(): Promise<void> {
    try {
      // Get all available personas from the personas directory
      const allPersonas = this.getCachedPersonas()
        .filter(p => !p.isInternal && !p.isSlim)  // Filter out internal and slim variants
        .map(p => p.name);

      // Load inference stats via D-Bus from Stats daemon
      const result = await dbus.stats_getInferenceStats();

      if (result.success && result.data) {
        const data = (result.data as any).stats || result.data;
        // Add the list of all available personas
        data.available_personas = allPersonas;
        this._panel.webview.postMessage({
          command: "inferenceStatsUpdate",
          data,
        });
      } else {
        // Return empty stats with all available personas
        this._panel.webview.postMessage({
          command: "inferenceStatsUpdate",
          data: {
            total_requests: 0,
            by_persona: {},
            available_personas: allPersonas,
            latency: { "<10ms": 0, "10-100ms": 0, "100-500ms": 0, ">500ms": 0 },
            cache: { hits: 0, misses: 0, hit_rate: 0 },
            recent_history: [],
          },
        });
      }
    } catch (error) {
      debugLog(`Failed to get inference stats: ${error}`);
    }
  }

  private async updateInferenceConfig(key: string, value: any): Promise<void> {
    try {
      // Use D-Bus to update config (uses ConfigManager for thread-safe writes)
      // The key format is "section.subkey" - we need to split into section and key
      const parts = key.split(".");
      const section = parts[0];
      const subKey = parts.slice(1).join(".");

      debugLog(`updateInferenceConfig via D-Bus: ${section}, ${subKey}, ${value}`);

      const result = await dbus.cron_updateConfig(section, subKey, value);

      const data = result.data as any;
      if (result.success && data?.success) {
        debugLog(`D-Bus update_config result: ${JSON.stringify(data)}`);
        vscode.window.showInformationMessage(`Updated inference config: ${key}`);
      } else {
        const errorMsg = data?.error || result.error || "Unknown error";
        debugLog(`D-Bus update_config failed: ${errorMsg}`);
        vscode.window.showErrorMessage(`Failed to update config via D-Bus: ${errorMsg}`);
      }
    } catch (error) {
      debugLog(`Failed to update inference config: ${error}`);
      vscode.window.showErrorMessage(`Failed to update config: ${error}`);
    }
  }

  private async resetInferenceConfig(): Promise<void> {
    try {
      // Reset inference config to defaults via D-Bus
      const defaults = {
        "inference.primary_engine": "npu",
        "inference.fallback_strategy": "keyword_match",
        "inference.max_categories": 3,
        "inference.enable_filtering": true,
        "inference.enable_npu": true,
        "inference.enable_cache": true,
      };

      for (const [key, value] of Object.entries(defaults)) {
        await this.updateInferenceConfig(key, value);
      }

      vscode.window.showInformationMessage("Inference config reset to defaults");
    } catch (error) {
      debugLog(`Failed to reset inference config: ${error}`);
      vscode.window.showErrorMessage(`Failed to reset config: ${error}`);
    }
  }

  private async saveInferenceConfig(): Promise<void> {
    try {
      // The config is already saved via updateInferenceConfig calls
      // This just triggers a reload to confirm the save
      const result = await dbus.cron_reload();
      if (result.success) {
        vscode.window.showInformationMessage("Inference configuration saved");
      } else {
        const errorMsg = result.error || "Unknown error";
        vscode.window.showErrorMessage(`Failed to save config: ${errorMsg}`);
      }
    } catch (error) {
      debugLog(`Failed to save inference config: ${error}`);
      vscode.window.showErrorMessage(`Failed to save config: ${error}`);
    }
  }

  private async executeSemanticSearch(query: string, project: string): Promise<void> {
    if (!query || !project) {
      this._panel.webview.postMessage({
        command: "semanticSearchResult",
        error: "Please enter a query and select a project",
      });
      return;
    }

    // Send loading state
    this._panel.webview.postMessage({
      command: "semanticSearchLoading",
    });

    try {
      // Execute the code_search tool via the MCP server using Python subprocess
      const { spawn } = require("child_process");

      // Handle "search all projects" option
      const searchAllProjects = project === "__all__";

      const pythonScript = searchAllProjects ? `
import sys
import json
sys.path.insert(0, '${path.join(__dirname, "..", "..", "..", "tool_modules", "aa_code_search", "src")}')
from tools_basic import _search_code, get_all_vector_stats

try:
    # Get all indexed projects
    all_stats = get_all_vector_stats()
    indexed_projects = [p["project"] for p in all_stats.get("projects", []) if p.get("indexed")]

    all_results = []
    for proj in indexed_projects:
        try:
            results = _search_code(
                query="${query.replace(/"/g, '\\"')}",
                project=proj,
                limit=5,  # Fewer per project when searching all
                auto_update=False
            )
            if results and not (len(results) == 1 and "error" in results[0]):
                for r in results:
                    r["project"] = proj  # Add project name to each result
                all_results.extend(results)
        except Exception as e:
            pass  # Skip projects that fail

    # Sort by similarity and take top 15
    all_results.sort(key=lambda x: x.get("similarity", 0), reverse=True)
    all_results = all_results[:15]

    print(json.dumps({"success": True, "results": all_results, "searched_projects": indexed_projects}))
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
` : `
import sys
import json
sys.path.insert(0, '${path.join(__dirname, "..", "..", "..", "tool_modules", "aa_code_search", "src")}')
from tools_basic import _search_code

try:
    results = _search_code(
        query="${query.replace(/"/g, '\\"')}",
        project="${project.replace(/"/g, '\\"')}",
        limit=10,
        auto_update=False
    )
    print(json.dumps({"success": True, "results": results}))
except Exception as e:
    print(json.dumps({"success": False, "error": str(e)}))
`;

      const python = spawn("python3", ["-c", pythonScript], {
        cwd: path.join(__dirname, "..", "..", ".."),
        env: { ...process.env, PYTHONPATH: path.join(__dirname, "..", "..", "..", "tool_modules", "aa_code_search", "src") },
      });

      let stdout = "";
      let stderr = "";

      python.stdout.on("data", (data: Buffer) => {
        stdout += data.toString();
      });

      python.stderr.on("data", (data: Buffer) => {
        stderr += data.toString();
      });

      python.on("close", (code: number) => {
        if (code !== 0) {
          debugLog(`Semantic search stderr: ${stderr}`);
          this._panel.webview.postMessage({
            command: "semanticSearchResult",
            error: `Search failed: ${stderr || "Unknown error"}`,
          });
          return;
        }

        try {
          const result = JSON.parse(stdout.trim());
          if (result.success) {
            this._panel.webview.postMessage({
              command: "semanticSearchResult",
              results: result.results,
              query: query,
              searchedProjects: result.searched_projects,
            });
          } else {
            this._panel.webview.postMessage({
              command: "semanticSearchResult",
              error: result.error,
            });
          }
        } catch (e) {
          debugLog(`Failed to parse search result: ${stdout}`);
          this._panel.webview.postMessage({
            command: "semanticSearchResult",
            error: `Failed to parse results: ${e}`,
          });
        }
      });
    } catch (e) {
      this._panel.webview.postMessage({
        command: "semanticSearchResult",
        error: `Search failed: ${e}`,
      });
    }
  }

  /**
   * Start watching for skill execution updates.
   * Now uses D-Bus polling instead of file watching.
   */
  private startExecutionWatcher() {
    // File watching removed - skill execution state comes from D-Bus via stats daemon
    // The 10-second auto-refresh interval handles updates via D-Bus polling
    debugLog("Skill execution state loaded via D-Bus - no file watching needed");

    // Load initial state via D-Bus
    this.loadExecutionStateAsync().catch(e => {
      debugLog(`Initial skill execution load failed: ${e}`);
    });

    // Also request current running skills from the watcher on startup
    // This ensures the Running Skills panel is populated when the Command Center opens
    this._loadRunningSkillsFromWatcher();
  }

  /**
   * Load running skills from the SkillExecutionWatcher and update the UI.
   * This is called on startup to populate the Running Skills panel.
   */
  private _loadRunningSkillsFromWatcher() {
    try {
      const { getSkillExecutionWatcher } = require("./skillExecutionWatcher");
      const watcher = getSkillExecutionWatcher();
      if (watcher) {
        const runningExecutions = watcher.getRunningExecutions();
        const staleCount = watcher.getStaleExecutionCount();
        debugLog(`Loading ${runningExecutions.length} running skills from watcher (${staleCount} stale)`);
        this.updateRunningSkills(runningExecutions);
      }
    } catch (e) {
      debugLog(`Failed to load running skills from watcher: ${e}`);
    }
  }

  /**
   * Trigger async execution state load (synchronous wrapper).
   * Call loadExecutionStateAsync() directly for async access.
   */
  private triggerExecutionStateLoad() {
    // Trigger async load - results will update UI when ready
    this.loadExecutionStateAsync().catch(e => {
      // Silently ignore errors - D-Bus may not be available
    });
  }

  /**
   * Load skill execution state via D-Bus from Stats daemon.
   */
  private async loadExecutionStateAsync(): Promise<void> {
    try {
      const result = await dbus.stats_getSkillExecution();
      if (result.success && result.data) {
        const data = (result.data as any).execution || result.data;
        this.updateSkillExecution(data);
      }
    } catch (e) {
      // D-Bus may not be available
    }
  }

  public dispose() {
    CommandCenterPanel.currentPanel = undefined;

    if (this._refreshInterval) {
      clearInterval(this._refreshInterval);
    }

    if (this._executionWatcher) {
      this._executionWatcher.close();
    }

    if (this._workspaceWatcher) {
      this._workspaceWatcher.close();
    }

    if (this._workspaceWatcherDebounce) {
      clearTimeout(this._workspaceWatcherDebounce);
    }

    // NOTE: RefreshCoordinator disposal removed - it was dead code

    this._panel.dispose();

    while (this._disposables.length) {
      const x = this._disposables.pop();
      if (x) {
        x.dispose();
      }
    }
  }

  // ============================================================================
  // Data Loading
  // ============================================================================

  /**
   * Returns cached agent stats (synchronous access).
   * Call loadStatsAsync() to refresh the cache.
   */
  private getCachedStats(): AgentStats | null {
    return this._cachedAgentStats;
  }

  private _cachedAgentStats: AgentStats | null = null;

  /**
   * Load agent stats via StatsDaemon D-Bus.
   * Falls back to file read if D-Bus unavailable.
   */
  private async loadStatsAsync(): Promise<AgentStats | null> {
    try {
      const result = await dbus.stats_getAgentStats();
      if (result.success && result.data?.stats) {
        this._cachedAgentStats = result.data.stats;
        return this._cachedAgentStats;
      }
    } catch (e) {
      debugLog(`Failed to load stats via D-Bus: ${e}`);
    }
    return this._cachedAgentStats;
  }

  /**
   * Returns cached current work (synchronous access).
   * Call loadCurrentWorkAsync() to refresh the cache.
   */
  private getCachedCurrentWork(): {
    activeIssue: any;
    activeMR: any;
    followUps: any[];
    sprintIssues: any[];
    activeRepo: string | null;
    totalActiveIssues: number;
    totalActiveMRs: number;
    allActiveIssues: { key: string; summary: string; project: string; workspace: string }[];
    allActiveMRs: { id: string; title: string; project: string; workspace: string }[];
  } {
    return this._cachedCurrentWork || {
      activeIssue: null,
      activeMR: null,
      followUps: [],
      sprintIssues: [],
      activeRepo: null,
      totalActiveIssues: 0,
      totalActiveMRs: 0,
      allActiveIssues: [],
      allActiveMRs: []
    };
  }

  /**
   * Fetch open MRs from GitLab via MCP tool
   */
  private async fetchOpenMRs(): Promise<any[]> {
    try {
      const { stdout } = await execAsync(
        `cd ~/src/redhat-ai-workflow && source .venv/bin/activate && python -c "
import asyncio
from tool_modules.aa_gitlab.src.tools_basic import _gitlab_mr_list_impl
result = asyncio.run(_gitlab_mr_list_impl('automation-analytics/automation-analytics-backend', 'opened', '', '', '', ''))
print(result[0].text if result else '[]')
" 2>/dev/null | head -50`,
        { timeout: 15000 }
      );
      // Parse the output - it's markdown table format
      const lines = stdout.trim().split("\n");
      const mrs: any[] = [];
      for (const line of lines) {
        const match = line.match(/^\|\s*!(\d+)\s*\|/);
        if (match) {
          mrs.push({ iid: match[1] });
        }
      }
      return mrs.slice(0, 5); // Return top 5
    } catch (e) {
      debugLog(`Failed to fetch open MRs: ${e}`);
      return [];
    }
  }

  /**
   * Fetch sprint issues from Jira via rh-issue CLI
   * Uses JQL: assignee = currentUser() AND sprint in openSprints()
   */
  private async fetchSprintIssues(): Promise<any[]> {
    try {
      // Use rh-issue CLI directly - it's more reliable than Python imports
      // The rh-issue script needs to run from its project directory
      const homeDir = process.env.HOME || os.homedir();
      const jiraCreatorDir = path.join(homeDir, "src", "jira-creator");
      const rhIssuePath = path.join(homeDir, "bin", "rh-issue");

      // Run with explicit working directory and required env vars
      // The rh-issue CLI needs JIRA_* environment variables
      // JIRA_AFFECTS_VERSION can be empty but the CLI requires it to be set to something
      const { stdout } = await execAsync(
        `/bin/bash -c 'source ~/.bashrc 2>/dev/null; export JIRA_AFFECTS_VERSION="\${JIRA_AFFECTS_VERSION:-N/A}"; cd "${jiraCreatorDir}" && ${rhIssuePath} search "assignee = currentUser() AND sprint in openSprints()" --max-results 20'`,
        { timeout: 30000 }
      );

      logger.log(`Jira search output (first 300 chars): ${stdout.substring(0, 300)}`);

      // Parse the output - it's markdown table format
      // Format: Key | Issuetype | Status | Priority | Summary | Assignee | Reporter | Sprint | Story Points | Blocked
      const lines = stdout.trim().split("\n");
      const issues: any[] = [];
      for (const line of lines) {
        // Skip header and separator lines
        if (line.startsWith("Key") || line.startsWith("-") || line.startsWith("📊") || line.trim() === "") {
          continue;
        }
        // Split by | and parse all columns
        const cols = line.split("|").map(c => c.trim());
        if (cols.length >= 8 && cols[0].match(/^AAP-\d+$/)) {
          issues.push({
            key: cols[0],
            type: cols[1],
            status: cols[2],
            priority: cols[3],
            summary: cols[4].substring(0, 60) + (cols[4].length > 60 ? '...' : ''),
            assignee: cols[5] || '',
            reporter: cols[6] || '',
            sprint: cols[7] || '',  // Capture sprint name
            storyPoints: parseInt(cols[8]) || 0,
            blocked: cols[9] === 'Yes' || cols[9] === 'true'
          });
        }
      }

      logger.log(`Parsed ${issues.length} issues from Jira`);
      return issues;
    } catch (e: any) {
      logger.error("Failed to fetch sprint issues", e);
      // Log the actual error message
      if (e.stderr) {
        logger.error(`stderr: ${e.stderr}`);
      }
      if (e.stdout) {
        logger.log(`stdout was: ${e.stdout}`);
      }
      return [];
    }
  }

  /**
   * Refresh sprint issues via D-Bus and update the UI.
   *
   * ARCHITECTURE: Sprint state is loaded via D-Bus from the Sprint daemon.
   * The UI polls the daemon every 10 seconds for fresh data.
   */
  private async refreshSprintIssues(): Promise<void> {
    logger.log("refreshSprintIssues() called - loading from cache");
    this._loadSprintFromFile();
  }

  /**
   * Load sprint data via D-Bus and update UI.
   *
   * ARCHITECTURE: Sprint state is loaded via D-Bus from the sprint daemon.
   */
  private _loadSprintFromFile(): void {
    logger.log("_loadSprintFromFile() called - loading via D-Bus");
    // Trigger async D-Bus load
    this._loadSprintViaDBusAndUpdateUI().catch(e => {
      console.error("Failed to load sprint via D-Bus:", e);
    });
  }

  /**
   * Load sprint state via D-Bus and update UI (async implementation).
   */
  private async _loadSprintViaDBusAndUpdateUI(): Promise<void> {
    try {
      const sprintData = await this._loadSprintStateViaDBus();

      if (!sprintData) {
        logger.log("No sprint data from D-Bus");
        return;
      }

      const issues = sprintData.issues || [];
      logger.log(`Loaded ${issues.length} sprint issues via D-Bus`);

      // Build SprintState from D-Bus data
      const sprintState: SprintState = {
        currentSprint: sprintData.currentSprint || null,
        nextSprint: sprintData.nextSprint || null,
        issues: issues,
        automaticMode: sprintData.automaticMode ?? false,
        manuallyStarted: sprintData.manuallyStarted ?? false,
        backgroundTasks: sprintData.backgroundTasks ?? false,
        lastUpdated: sprintData.lastUpdated || new Date().toISOString(),
        processingIssue: sprintData.processingIssue || null,
      };

      // Cache for synchronous access in UI updates
      this._cachedSprintState = sprintState;

      // NOTE: Dead postMessage calls removed (sprintIssuesUpdate, sprintTabUpdate)
      // These messages were never handled in the webview.
      // The SprintTab class handles its own rendering via TabManager.
    } catch (e) {
      console.error("Failed to load sprint via D-Bus:", e);
    }
  }

  /**
   * Check environment health by testing kubectl connectivity
   */
  private async checkEnvironmentHealth(): Promise<void> {
    const envFile = path.join(getMemoryDir(), "state", "environments.yaml");

    // Check stage
    try {
      const { stdout: stageOut } = await execAsync(
        `kubectl --kubeconfig=/home/daoneill/.kube/config.s get pods -n tower-analytics-stage --no-headers 2>&1 | head -1`,
        { timeout: 10000 }
      );
      const stageHealthy = stageOut.includes("Running");

      // Check prod
      const { stdout: prodOut } = await execAsync(
        `kubectl --kubeconfig=/home/daoneill/.kube/config.p get pods -n tower-analytics-prod --no-headers 2>&1 | head -1`,
        { timeout: 10000 }
      );
      const prodHealthy = prodOut.includes("Running");

      // Update environments.yaml
      if (fs.existsSync(envFile)) {
        let content = fs.readFileSync(envFile, "utf-8");
        const now = new Date().toISOString();

        // Update stage status
        content = content.replace(
          /(stage:[\s\S]*?status:\s*)\w+/,
          `$1${stageHealthy ? "healthy" : "degraded"}`
        );
        content = content.replace(
          /(stage:[\s\S]*?last_check:\s*)'[^']*'/,
          `$1'${now}'`
        );

        // Update prod status
        content = content.replace(
          /(production:[\s\S]*?status:\s*)\w+/,
          `$1${prodHealthy ? "healthy" : "degraded"}`
        );
        content = content.replace(
          /(production:[\s\S]*?last_check:\s*)'[^']*'/,
          `$1'${now}'`
        );

        fs.writeFileSync(envFile, content);
      }

      // Update UI
      this._panel.webview.postMessage({
        type: "environmentUpdate",
        stage: stageHealthy ? "healthy" : "degraded",
        prod: prodHealthy ? "healthy" : "degraded",
      });
    } catch (e) {
      console.error("Failed to check environment health:", e);
    }
  }

  // Cache for skills loaded via D-Bus
  private _skillsCache: SkillDefinition[] | null = null;

  /**
   * Load skills list via D-Bus from ConfigDaemon.
   * Falls back to file-based loading if D-Bus fails.
   */
  private async loadSkillsListAsync(): Promise<SkillDefinition[]> {
    try {
      const result = await dbus.config_getSkillsList();
      if (result.success && result.data) {
        const data = result.data as any;
        const skills = (data.skills || []).map((s: any) => ({
          name: s.name,
          description: s.description || "",
          category: "general",
        }));
        this._skillsCache = skills;
        return skills;
      }
    } catch (e) {
      console.error("Failed to load skills via D-Bus:", e);
    }
    return this._skillsCache || [];
  }

  /**
   * Returns cached skills list (synchronous access).
   * Call loadSkillsListAsync() to refresh the cache.
   */
  private getCachedSkillsList(): SkillDefinition[] {
    return this._skillsCache || [];
  }

  private async loadSkillDefinition(skillName: string) {
    try {
      const result = await dbus.config_getSkillDefinition(skillName);
      if (result.success && result.data) {
        const data = result.data as any;
        const skill = data.skill;
        if (skill && skill._raw_yaml) {
          this._panel.webview.postMessage({
            command: "skillDefinition",
            skillName,
            content: skill._raw_yaml,
          });
          return;
        }
      }
    } catch (e) {
      console.error("Failed to load skill definition via D-Bus:", e);
    }
    // Send empty content if D-Bus failed
    this._panel.webview.postMessage({
      command: "skillDefinition",
      skillName,
      content: `# Skill ${skillName} not available`,
    });
  }

  /**
   * Select a running skill to view its execution details
   */
  private _selectRunningSkill(executionId: string) {
    // Import the watcher to select the execution
    const { getSkillExecutionWatcher } = require("./skillExecutionWatcher");
    const watcher = getSkillExecutionWatcher();
    if (watcher) {
      watcher.selectExecution(executionId);
    }
  }

  /**
   * Clear all stale/dead skill executions
   */
  private async _clearStaleSkills() {
    const { getSkillExecutionWatcher } = require("./skillExecutionWatcher");
    const watcher = getSkillExecutionWatcher();
    if (watcher) {
      const cleared = await watcher.clearStaleExecutions();
      if (cleared > 0) {
        vscode.window.showInformationMessage(`Cleared ${cleared} stale skill execution(s)`);
      } else {
        vscode.window.showInformationMessage("No stale skill executions to clear");
      }
    }
  }

  /**
   * Clear a specific skill execution
   */
  private async _clearSkillExecution(executionId: string) {
    const { getSkillExecutionWatcher } = require("./skillExecutionWatcher");
    const watcher = getSkillExecutionWatcher();
    if (watcher) {
      const success = await watcher.clearExecution(executionId);
      if (success) {
        vscode.window.showInformationMessage("Skill execution cleared");
      } else {
        vscode.window.showWarningMessage("Failed to clear skill execution");
      }
    }
  }

  private async openSkillFile(skillName: string) {
    try {
      const skillsDir = getSkillsDir();
      const filePath = path.join(skillsDir, `${skillName}.yaml`);

      if (fs.existsSync(filePath)) {
        const doc = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(doc);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to open skill file: ${e}`);
    }
  }

  /**
   * Returns cached memory health (synchronous access).
   * Call getMemoryHealthAsync() to refresh the cache.
   */
  private getCachedMemoryHealth(): { totalSize: string; sessionLogs: number; lastSession: string; patterns: number } {
    return this._cachedMemoryHealth || { totalSize: "Unknown", sessionLogs: 0, lastSession: "Unknown", patterns: 0 };
  }

  /**
   * Returns cached memory files (synchronous access).
   * Call loadMemoryFilesAsync() to refresh the cache.
   */
  private getCachedMemoryFiles(): { state: string[]; learned: string[]; sessions: string[]; knowledge: { project: string; persona: string; confidence: number }[] } {
    return this._cachedMemoryFiles || { state: [], learned: [], sessions: [], knowledge: [] };
  }

  // Cache for memory health
  private _cachedMemoryHealth: { totalSize: string; sessionLogs: number; lastSession: string; patterns: number } | null = null;

  /**
   * Load memory health via MemoryDaemon D-Bus.
   */
  private async getMemoryHealthAsync(): Promise<{ totalSize: string; sessionLogs: number; lastSession: string; patterns: number }> {
    try {
      const result = await dbus.memory_getHealth();
      if (result.success && result.data?.health) {
        const health = result.data.health;
        this._cachedMemoryHealth = {
          totalSize: health.totalSize || "Unknown",
          sessionLogs: health.sessionLogs || 0,
          lastSession: health.lastSession || "Unknown",
          patterns: health.patterns || 0,
        };
        return this._cachedMemoryHealth;
      }
    } catch (e) {
      console.error("Failed to load memory health via D-Bus:", e);
    }
    return this._cachedMemoryHealth || { totalSize: "Unknown", sessionLogs: 0, lastSession: "Unknown", patterns: 0 };
  }

  // Cache for memory files
  private _cachedMemoryFiles: { state: string[]; learned: string[]; sessions: string[]; knowledge: { project: string; persona: string; confidence: number }[] } | null = null;

  /**
   * Load memory files via MemoryDaemon D-Bus.
   */
  private async loadMemoryFilesAsync(): Promise<{ state: string[]; learned: string[]; sessions: string[]; knowledge: { project: string; persona: string; confidence: number }[] }> {
    try {
      const result = await dbus.memory_getFiles();
      if (result.success && result.data?.files) {
        const files = result.data.files;
        this._cachedMemoryFiles = {
          state: files.state || [],
          learned: files.learned || [],
          sessions: files.sessions || [],
          knowledge: (files.knowledge || []).map((k: any) => ({
            project: k.persona || "",
            persona: k.file || "",
            confidence: k.confidence || 0,
          })),
        };
        return this._cachedMemoryFiles;
      }
    } catch (e) {
      console.error("Failed to load memory files via D-Bus:", e);
    }
    return this._cachedMemoryFiles || { state: [], learned: [], sessions: [], knowledge: [] };
  }

  // Cache for current work
  private _cachedCurrentWork: {
    activeIssue: any;
    activeMR: any;
    followUps: any[];
    sprintIssues: any[];
    activeRepo: string | null;
    totalActiveIssues: number;
    totalActiveMRs: number;
    allActiveIssues: { key: string; summary: string; project: string; workspace: string }[];
    allActiveMRs: { id: string; title: string; project: string; workspace: string }[];
  } | null = null;

  /**
   * Load current work via MemoryDaemon D-Bus.
   */
  private async loadCurrentWorkAsync(): Promise<{
    activeIssue: any;
    activeMR: any;
    followUps: any[];
    sprintIssues: any[];
    activeRepo: string | null;
    totalActiveIssues: number;
    totalActiveMRs: number;
    allActiveIssues: { key: string; summary: string; project: string; workspace: string }[];
    allActiveMRs: { id: string; title: string; project: string; workspace: string }[];
  }> {
    try {
      const result = await dbus.memory_getCurrentWork();
      if (result.success && result.data?.work) {
        const work = result.data.work;
        // Map D-Bus response to expected format
        const activeIssue = work.activeIssue || (work.activeIssues?.[0]) || null;
        const activeMR = work.activeMR || (work.openMRs?.[0]) || null;
        const activeRepo = activeIssue?.repo || null;

        this._cachedCurrentWork = {
          activeIssue,
          activeMR,
          followUps: work.followUps || [],
          sprintIssues: [],
          activeRepo,
          totalActiveIssues: work.activeIssues?.length || (activeIssue ? 1 : 0),
          totalActiveMRs: work.openMRs?.length || (activeMR ? 1 : 0),
          allActiveIssues: (work.activeIssues || []).map((i: any) => ({
            key: i.key || "",
            summary: i.summary || "",
            project: i.repo || "automation-analytics-backend",
            workspace: "current",
          })),
          allActiveMRs: (work.openMRs || []).map((m: any) => ({
            id: String(m.id || ""),
            title: m.title || "",
            project: "automation-analytics-backend",
            workspace: "current",
          })),
        };
        return this._cachedCurrentWork;
      }
    } catch (e) {
      console.error("Failed to load current work via D-Bus:", e);
    }
    return this._cachedCurrentWork || {
      activeIssue: null,
      activeMR: null,
      followUps: [],
      sprintIssues: [],
      activeRepo: null,
      totalActiveIssues: 0,
      totalActiveMRs: 0,
      allActiveIssues: [],
      allActiveMRs: []
    };
  }

  private loadVectorStats(): {
    projects: { project: string; indexed: boolean; files?: number; chunks?: number; diskSize?: string; indexAge?: string; isStale?: boolean; searches?: number; avgSearchMs?: number; watcherActive?: boolean }[];
    totals: { indexedCount: number; totalChunks: number; totalFiles: number; totalSize: string; totalSearches: number; watchersActive: number };
  } {
    const result = {
      projects: [] as any[],
      totals: {
        indexedCount: 0,
        totalChunks: 0,
        totalFiles: 0,
        totalSize: "0 B",
        totalSearches: 0,
        watchersActive: 0,
      }
    };

    try {
      const vectorDir = path.join(os.homedir(), ".cache", "aa-workflow", "vectors");
      if (!fs.existsSync(vectorDir)) {
        return result;
      }

      const projects = fs.readdirSync(vectorDir).filter(f => {
        const stat = fs.statSync(path.join(vectorDir, f));
        return stat.isDirectory();
      });

      let totalSizeBytes = 0;

      for (const project of projects) {
        const metadataPath = path.join(vectorDir, project, "metadata.json");
        if (!fs.existsSync(metadataPath)) {
          result.projects.push({ project, indexed: false });
          continue;
        }

        try {
          const metadata = JSON.parse(fs.readFileSync(metadataPath, "utf-8"));

          // Calculate disk size
          let diskSizeBytes = 0;
          const projectDir = path.join(vectorDir, project);
          const walkDir = (dir: string) => {
            const files = fs.readdirSync(dir);
            for (const file of files) {
              const filePath = path.join(dir, file);
              const stat = fs.statSync(filePath);
              if (stat.isDirectory()) {
                walkDir(filePath);
              } else {
                diskSizeBytes += stat.size;
              }
            }
          };
          walkDir(projectDir);
          totalSizeBytes += diskSizeBytes;

          // Format disk size
          let diskSize = "0 B";
          if (diskSizeBytes >= 1024 * 1024) {
            diskSize = `${(diskSizeBytes / (1024 * 1024)).toFixed(1)} MB`;
          } else if (diskSizeBytes >= 1024) {
            diskSize = `${(diskSizeBytes / 1024).toFixed(1)} KB`;
          } else {
            diskSize = `${diskSizeBytes} B`;
          }

          // Calculate index age
          let indexAge = "Unknown";
          let isStale = false;
          const indexedAt = metadata.indexed_at;
          if (indexedAt) {
            const indexedTime = new Date(indexedAt);
            const now = new Date();
            const ageMs = now.getTime() - indexedTime.getTime();
            const ageMinutes = ageMs / (1000 * 60);
            const ageHours = ageMinutes / 60;
            const ageDays = ageHours / 24;

            if (ageDays >= 1) {
              indexAge = `${Math.floor(ageDays)}d ago`;
            } else if (ageHours >= 1) {
              indexAge = `${Math.floor(ageHours)}h ago`;
            } else if (ageMinutes >= 1) {
              indexAge = `${Math.floor(ageMinutes)}m ago`;
            } else {
              indexAge = "just now";
            }
            isStale = ageMinutes > 60;
          }

          // Get search stats
          const searchStats = metadata.search_stats || {};
          const chunks = metadata.stats?.chunks_created || 0;
          const files = Object.keys(metadata.file_hashes || {}).length;

          result.projects.push({
            project,
            indexed: true,
            files,
            chunks,
            diskSize,
            indexAge,
            isStale,
            searches: searchStats.total_searches || 0,
            avgSearchMs: searchStats.avg_search_time_ms || 0,
            watcherActive: false, // Can't easily check from extension
          });

          result.totals.indexedCount++;
          result.totals.totalChunks += chunks;
          result.totals.totalFiles += files;
          result.totals.totalSearches += searchStats.total_searches || 0;
        } catch (e) {
          result.projects.push({ project, indexed: false });
        }
      }

      // Format total size
      if (totalSizeBytes >= 1024 * 1024) {
        result.totals.totalSize = `${(totalSizeBytes / (1024 * 1024)).toFixed(1)} MB`;
      } else if (totalSizeBytes >= 1024) {
        result.totals.totalSize = `${(totalSizeBytes / 1024).toFixed(1)} KB`;
      } else {
        result.totals.totalSize = `${totalSizeBytes} B`;
      }
    } catch (e) {
      console.error("Failed to load vector stats:", e);
    }

    return result;
  }

  // ============================================================================
  // D-Bus / Services
  // ============================================================================

  private async handleDBusQuery(serviceName: string, methodName: string, methodArgs?: Record<string, string>) {
    const service = DBUS_SERVICES.find((s) => s.name === serviceName);
    if (!service) {
      this._panel.webview.postMessage({
        type: "dbusResult",
        success: false,
        error: "Service not found",
      });
      return;
    }

    const methodDef = service.methods.find(m => m.name === methodName);

    // Build D-Bus arguments from method definition
    let dbusArgs: { type: string; value: string }[] | undefined;
    if (methodDef?.args && methodDef.args.length > 0) {
      dbusArgs = methodDef.args.map(arg => ({
        type: arg.type === "int32" ? "int32" : "string",
        value: methodArgs?.[arg.name] ?? arg.default ?? "",
      }));
    }

    const result = await this.queryDBus(
      service.service,
      service.path,
      service.interface,
      methodName,
      dbusArgs
    );

    this._panel.webview.postMessage({
      type: "dbusResult",
      service: serviceName,
      method: methodName,
      ...result,
    });
  }

  private async queryDBus(
    service: string,
    objectPath: string,
    iface: string,
    method: string,
    args?: { type: string; value: string }[]
  ): Promise<{ success: boolean; data?: any; error?: string }> {
    try {
      // Explicitly set DBUS_SESSION_BUS_ADDRESS in case Cursor doesn't inherit it
      const uid = process.getuid ? process.getuid() : 1000;
      const dbusAddr = process.env.DBUS_SESSION_BUS_ADDRESS || `unix:path=/run/user/${uid}/bus`;
      let cmd = `DBUS_SESSION_BUS_ADDRESS="${dbusAddr}" dbus-send --session --print-reply --dest=${service} ${objectPath} ${iface}.${method}`;

      // Add arguments if provided
      if (args && args.length > 0) {
        for (const arg of args) {
          // Escape double quotes and backslashes for shell
          const escapedValue = arg.value
            .replace(/\\/g, '\\\\')  // Escape backslashes first
            .replace(/"/g, '\\"');    // Escape double quotes
          cmd += ` ${arg.type}:"${escapedValue}"`;
        }
      }

      debugLog(`D-Bus command: ${cmd}`);
      const { stdout } = await execAsync(cmd, { timeout: 30000 });  // 30s timeout for join operations

      // Parse D-Bus output
      const data = this.parseDBusOutput(stdout);
      return { success: true, data };
    } catch (e: any) {
      return { success: false, error: e.message || "D-Bus query failed" };
    }
  }

  private parseDBusOutput(output: string): any {
    try {
      // Look for JSON object in the output
      const jsonObjMatch = output.match(/string\s+"(\{[\s\S]*\})"/);
      if (jsonObjMatch) {
        return JSON.parse(jsonObjMatch[1]);
      }

      // Look for JSON array in the output
      const jsonArrMatch = output.match(/string\s+"(\[[\s\S]*\])"/);
      if (jsonArrMatch) {
        return JSON.parse(jsonArrMatch[1]);
      }

      // Parse simple values
      const lines = output.split("\n").filter(l => l.trim());
      const result: Record<string, any> = {};

      for (const line of lines) {
        const stringMatch = line.match(/string\s+"([^"]*)"/);
        if (stringMatch) {
          return stringMatch[1];
        }
        const intMatch = line.match(/int32\s+(\d+)/);
        if (intMatch) {
          return parseInt(intMatch[1], 10);
        }
        const boolMatch = line.match(/boolean\s+(true|false)/);
        if (boolMatch) {
          return boolMatch[1] === "true";
        }
      }

      return output;
    } catch {
      return output;
    }
  }

  private async refreshServiceStatus() {
    const serviceStatuses: any[] = [];

    for (const service of DBUS_SERVICES) {
      const status = await this.checkServiceStatus(service);
      serviceStatuses.push({
        name: service.name,
        ...status,
      });
    }

    const mcpStatus = await this.checkMCPServerStatus();

    this._panel.webview.postMessage({
      type: "serviceStatus",
      services: serviceStatuses,
      mcp: mcpStatus,
    });
  }

  private async checkServiceStatus(service: typeof DBUS_SERVICES[0]): Promise<any> {
    try {
      const result = await this.queryDBus(
        service.service,
        service.path,
        service.interface,
        "GetStatus"
      );

      if (result.success) {
        return { running: true, status: result.data };
      }
      return { running: false, error: result.error };
    } catch {
      return { running: false, error: "Service not available" };
    }
  }

  private async checkMCPServerStatus(): Promise<{ running: boolean; pid?: number }> {
    try {
      // Check for MCP server running - could be via mcp_proxy.py or directly via "python -m server"
      const { stdout } = await execAsync("pgrep -f 'mcp_proxy.py|python.*-m server'");
      const pids = stdout.trim().split("\n").filter(Boolean);
      if (pids.length > 0) {
        const pid = parseInt(pids[0], 10);
        const status = { running: !isNaN(pid), pid };
        // Update internal cache for tab badge calculation
        this._services.mcp = status;
        return status;
      }
      this._services.mcp = { running: false };
      return { running: false };
    } catch {
      this._services.mcp = { running: false };
      return { running: false };
    }
  }

  private async handleServiceControl(action: string, service: string) {
    // Map service names to systemd units
    const serviceUnits: Record<string, string> = {
      slack: "bot-slack.service",
      cron: "bot-cron.service",
      meet: "bot-meet.service",
      sprint: "bot-sprint.service",
      video: "bot-video.service",
      session: "bot-session.service",
      config: "bot-config.service",
      memory: "bot-memory.service",
      stats: "bot-stats.service",
      slop: "bot-slop.service",
    };

    const unit = serviceUnits[service];
    if (!unit) {
      vscode.window.showErrorMessage(`Unknown service: ${service}`);
      return;
    }

    try {
      switch (action) {
        case "start":
          await execAsync(`systemctl --user start ${unit}`);
          vscode.window.showInformationMessage(`Started ${service} service`);
          // Refresh status after a short delay
          setTimeout(() => {
            this._loadWorkspaceState();
            this._dispatchAllUIUpdates();
          }, 1000);
          break;

        case "stop":
          // Try D-Bus shutdown first for graceful stop
          const dbusService = DBUS_SERVICES.find(s => s.name.toLowerCase().includes(service));
          if (dbusService) {
            try {
              await this.queryDBus(
                dbusService.service,
                dbusService.path,
                dbusService.interface,
                "Shutdown"
              );
              vscode.window.showInformationMessage(`Stopping ${service} service...`);
            } catch {
              // Fall back to systemctl
              await execAsync(`systemctl --user stop ${unit}`);
              vscode.window.showInformationMessage(`Stopped ${service} service`);
            }
          } else {
            await execAsync(`systemctl --user stop ${unit}`);
            vscode.window.showInformationMessage(`Stopped ${service} service`);
          }
          // Refresh after a short delay
          setTimeout(() => {
            this._loadWorkspaceState();
            this._dispatchAllUIUpdates();
          }, 1000);
          break;

        case "logs":
          // Always use journalctl -f in a terminal for live log streaming
          const terminal = vscode.window.createTerminal(`${service} logs`);
          terminal.show();
          terminal.sendText(`journalctl --user -u ${unit} -f`);
          break;
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Service control failed: ${e.message}`);
    }
  }

  // ============================================================================
  // Create Session Tab Methods
  // ============================================================================

  /**
   * Call an MCP tool via HTTP to the workflow server
   */
  private async callMcpTool(toolName: string, args: any): Promise<any> {
    try {
      const response = await new Promise<any>((resolve, reject) => {
        const postData = JSON.stringify({ tool: toolName, args });
        const req = http.request({
          hostname: "localhost",
          port: 8765,
          path: "/api/tool",
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(postData)
          }
        }, (res) => {
          let data = "";
          res.on("data", chunk => data += chunk);
          res.on("end", () => {
            try {
              resolve(JSON.parse(data));
            } catch {
              resolve({ result: data });
            }
          });
        });
        req.on("error", reject);
        req.setTimeout(30000, () => {
          req.destroy();
          reject(new Error("Request timeout"));
        });
        req.write(postData);
        req.end();
      });
      return response;
    } catch (e: any) {
      debugLog(`[CreateSession] MCP tool call failed: ${e.message}`);
      return { error: e.message };
    }
  }

  /**
   * Load Cursor chat sessions from the workspace
   */
  private loadCursorSessions(): any[] {
    const sessions: any[] = [];

    try {
      // Get workspace URI
      const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
      if (!workspaceFolder) return sessions;

      const workspaceUri = workspaceFolder.uri.toString();

      // Import the function from workspace_state module (it's already used elsewhere)
      const { list_cursor_chats, get_cursor_chat_issue_keys, get_cursor_chat_personas } = require("./workspaceStateProvider");

      // Use the existing list_cursor_chats function pattern
      const workspaceStorageDir = path.join(os.homedir(), ".config", "Cursor", "User", "workspaceStorage");

      if (!fs.existsSync(workspaceStorageDir)) return sessions;

      // Find matching workspace storage
      for (const storageDir of fs.readdirSync(workspaceStorageDir)) {
        const storagePath = path.join(workspaceStorageDir, storageDir);
        if (!fs.statSync(storagePath).isDirectory()) continue;

        const workspaceJson = path.join(storagePath, "workspace.json");
        if (!fs.existsSync(workspaceJson)) continue;

        try {
          const workspaceData = JSON.parse(fs.readFileSync(workspaceJson, "utf-8"));
          const folderUri = workspaceData.folder || "";

          if (folderUri === workspaceUri) {
            const dbPath = path.join(storagePath, "state.vscdb");
            if (!fs.existsSync(dbPath)) continue;

            // Query the database
            const { execSync } = require("child_process");
            const query = "SELECT value FROM ItemTable WHERE key = 'composer.composerData'";
            const result = execSync(`sqlite3 "${dbPath}" "${query}"`, { encoding: "utf-8", timeout: 5000 });

            if (result.trim()) {
              const composerData = JSON.parse(result.trim());
              const allComposers = composerData.allComposers || [];

              // Filter and sort chats
              const activeChats = allComposers
                .filter((c: any) => !c.isArchived && !c.isDraft && (c.name || c.lastUpdatedAt))
                .sort((a: any, b: any) => (b.lastUpdatedAt || 0) - (a.lastUpdatedAt || 0))
                .slice(0, 10);

              for (const chat of activeChats) {
                sessions.push({
                  id: chat.composerId,
                  name: chat.name || "Unnamed chat",
                  lastUpdated: chat.lastUpdatedAt,
                  source: "cursor",
                  // These would need additional DB queries to populate
                  issueKey: null,
                  persona: null
                });
              }
            }
            break; // Found matching workspace
          }
        } catch (e) {
          debugLog(`[CreateSession] Error parsing workspace.json: ${e}`);
        }
      }
    } catch (e: any) {
      debugLog(`[CreateSession] Error loading Cursor sessions: ${e.message}`);
    }

    return sessions;
  }

  /**
   * Load Claude Console sessions from ~/.claude/
   */
  private loadClaudeSessions(): any[] {
    const sessions: any[] = [];
    const claudeDir = path.join(os.homedir(), ".claude");
    const claudeConfigDir = path.join(os.homedir(), ".config", "claude-code");

    for (const baseDir of [claudeDir, claudeConfigDir]) {
      if (!fs.existsSync(baseDir)) continue;

      const projectsDir = path.join(baseDir, "projects");
      if (fs.existsSync(projectsDir)) {
        try {
          const projects = fs.readdirSync(projectsDir, { withFileTypes: true });
          for (const project of projects) {
            if (project.isDirectory()) {
              const projectPath = path.join(projectsDir, project.name);
              const sessionFiles = fs.readdirSync(projectPath).filter(f => f.endsWith(".jsonl"));
              for (const sessionFile of sessionFiles.slice(0, 5)) { // Limit per project
                sessions.push({
                  id: sessionFile.replace(".jsonl", ""),
                  name: project.name,
                  path: path.join(projectPath, sessionFile),
                  source: "claude"
                });
              }
            }
          }
        } catch (e) {
          debugLog(`[CreateSession] Error reading Claude sessions: ${e}`);
        }
      }
    }

    return sessions.slice(0, 10); // Limit total
  }

  /**
   * Load Gemini sessions from import directory
   */
  private loadGeminiSessions(): any[] {
    const sessions: any[] = [];
    const geminiDir = path.join(os.homedir(), ".config", "aa-workflow", "gemini_sessions");

    if (fs.existsSync(geminiDir)) {
      try {
        const files = fs.readdirSync(geminiDir).filter(f => f.endsWith(".json"));
        for (const file of files.slice(0, 10)) {
          sessions.push({
            id: file.replace(".json", ""),
            name: file.replace(".json", ""),
            path: path.join(geminiDir, file),
            source: "gemini"
          });
        }
      } catch (e) {
        debugLog(`[CreateSession] Error reading Gemini sessions: ${e}`);
      }
    }

    return sessions;
  }

  private async handleCreateSessionAction(action: string, message: any) {
    try {
      switch (action) {
        case "autoContext":
          // Auto-populate context based on issue key
          if (message.issueKey) {
            // Send loading state to webview
            this._panel?.webview.postMessage({
              command: 'jiraLoading',
              issueKey: message.issueKey
            });

            try {
              // Call Jira tool via MCP to get issue details
              const result = await this.callMcpTool("jira_get_issue", { issue_key: message.issueKey });
              if (result && !result.error) {
                this._panel?.webview.postMessage({
                  command: 'jiraData',
                  issueKey: message.issueKey,
                  data: result
                });
              } else {
                this._panel?.webview.postMessage({
                  command: 'jiraError',
                  issueKey: message.issueKey,
                  error: result?.error || 'Failed to fetch issue'
                });
              }
            } catch (e: any) {
              this._panel?.webview.postMessage({
                command: 'jiraError',
                issueKey: message.issueKey,
                error: e.message
              });
            }
          }
          break;

        case "searchSlack":
          // Search Slack messages
          if (message.query) {
            try {
              const result = await this.callMcpTool("slack_search_messages", { query: message.query, limit: 10 });
              this._panel?.webview.postMessage({
                command: 'slackResults',
                query: message.query,
                results: result?.messages || []
              });
            } catch (e: any) {
              vscode.window.showErrorMessage(`Slack search failed: ${e.message}`);
            }
          }
          break;

        case "searchCode":
          // Search code using vector search
          if (message.query) {
            try {
              const result = await this.callMcpTool("code_search", { query: message.query, limit: 5 });
              this._panel?.webview.postMessage({
                command: 'codeResults',
                query: message.query,
                results: result?.results || []
              });
            } catch (e: any) {
              vscode.window.showErrorMessage(`Code search failed: ${e.message}`);
            }
          }
          break;

        case "selectPersona":
          // Persona selected - load tools for that persona via D-Bus
          if (message.personaId) {
            debugLog(`[CreateSession] Persona selected: ${message.personaId}`);
            try {
              const result = await dbus.config_getPersonaDefinition(message.personaId);
              if (result.success && result.data) {
                const personaData = (result.data as any).persona || result.data;
                const tools = personaData?.tools || [];
                this._panel?.webview.postMessage({
                  command: 'personaTools',
                  personaId: message.personaId,
                  tools: tools
                });
              }
            } catch (e: any) {
              debugLog(`[CreateSession] Failed to load persona tools: ${e.message}`);
            }
          }
          break;

        case "loadSessions":
          // Load external sessions (Cursor, Claude Console, and Gemini)
          try {
            const cursorSessions = this.loadCursorSessions();
            const claudeSessions = this.loadClaudeSessions();
            const geminiSessions = this.loadGeminiSessions();
            this._panel?.webview.postMessage({
              command: 'externalSessions',
              cursor: cursorSessions,
              claude: claudeSessions,
              gemini: geminiSessions
            });
          } catch (e: any) {
            debugLog(`[CreateSession] Failed to load sessions: ${e.message}`);
          }
          break;

        case "stopLoop":
          // Stop a Ralph Wiggum loop
          if (message.sessionId) {
            const loopConfigPath = path.join(
              os.homedir(),
              ".config",
              "aa-workflow",
              "ralph_loops",
              `session_${message.sessionId}.json`
            );
            if (fs.existsSync(loopConfigPath)) {
              fs.unlinkSync(loopConfigPath);
              vscode.window.showInformationMessage(`Stopped loop for session ${message.sessionId}`);
              this._dispatchAllUIUpdates();
            }
          }
          break;

        case "createSession":
          // Create a new session with the configured context
          if (message.config) {
            const config = message.config;
            debugLog(`[CreateSession] Creating session with config: ${JSON.stringify(config)}`);

            // If Ralph Wiggum is enabled, set up the loop
            if (config.ralph?.enabled) {
              const loopsDir = path.join(os.homedir(), ".config", "aa-workflow", "ralph_loops");
              if (!fs.existsSync(loopsDir)) {
                fs.mkdirSync(loopsDir, { recursive: true });
              }

              // Generate a session ID
              const sessionId = `cursor_${Date.now().toString(36)}`;
              const loopConfig = {
                session_id: sessionId,
                max_iterations: config.ralph.maxIterations || 10,
                current_iteration: 0,
                todo_path: path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir(), "TODO.md"),
                completion_criteria: config.ralph.criteria ? [config.ralph.criteria] : [],
                started_at: new Date().toISOString(),
              };

              // Write loop config
              const loopConfigPath = path.join(loopsDir, `session_${sessionId}.json`);
              fs.writeFileSync(loopConfigPath, JSON.stringify(loopConfig, null, 2));

              // Generate TODO.md from goals
              if (config.ralph.goals) {
                const todoPath = loopConfig.todo_path;
                const todoContent = `# TODO - Session ${sessionId}\n\n${config.ralph.goals.split('\n').map((g: string) => g.trim()).filter((g: string) => g).map((g: string) => `- [ ] ${g}`).join('\n')}\n`;
                fs.writeFileSync(todoPath, todoContent);
                vscode.window.showInformationMessage(`Created TODO.md with ${config.ralph.goals.split('\n').filter((g: string) => g.trim()).length} tasks`);
              }

              // Set up Cursor hooks if not already configured
              const hooksPath = path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || os.homedir(), ".cursor", "hooks.json");
              if (!fs.existsSync(hooksPath)) {
                const hooksDir = path.dirname(hooksPath);
                if (!fs.existsSync(hooksDir)) {
                  fs.mkdirSync(hooksDir, { recursive: true });
                }
                const hooksConfig = {
                  version: 1,
                  hooks: {
                    stop: [{
                      command: `python ${path.join(os.homedir(), ".config", "aa-workflow", "ralph_wiggum_hook.py")}`
                    }]
                  }
                };
                fs.writeFileSync(hooksPath, JSON.stringify(hooksConfig, null, 2));
                vscode.window.showInformationMessage("Created .cursor/hooks.json for Ralph Wiggum loop");
              }
            }

            vscode.window.showInformationMessage("Session created! Open a new Cursor chat to start.");
            this._dispatchAllUIUpdates();
          }
          break;

        case "saveTemplate":
          // Save the current configuration as a template
          if (message.config) {
            vscode.window.showInformationMessage("Template saving - feature coming soon");
          }
          break;

        case "importGemini":
          // Import Gemini session
          const options: vscode.OpenDialogOptions = {
            canSelectMany: false,
            openLabel: "Import Gemini Session",
            filters: { "JSON files": ["json"] }
          };
          const fileUri = await vscode.window.showOpenDialog(options);
          if (fileUri && fileUri[0]) {
            vscode.window.showInformationMessage(`Importing Gemini session from ${fileUri[0].fsPath}`);
            // TODO: Parse and import the session
          }
          break;

        default:
          debugLog(`[CreateSession] Unknown action: ${action}`);
      }
    } catch (e: any) {
      console.error("[CreateSession] Error:", e);
      vscode.window.showErrorMessage(`Create session error: ${e.message}`);
    }
  }

  // ============================================================================
  // Performance Tracking Control Methods
  // ============================================================================

  private async handlePerformanceAction(action: string, questionId?: string, category?: string, description?: string) {
    try {
      switch (action) {
        case "collectDaily":
          // Run the daily collection skill
          vscode.window.showInformationMessage("Starting daily performance collection...");
          await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
          await this.sleep(500);
          await vscode.commands.executeCommand("composer.focusComposer");
          await this.sleep(200);

          const collectCommand = `Run the daily performance collection skill:

skill_run("performance/collect_daily")

This will fetch today's work from Jira, GitLab, and local git repos, map to competencies, and save the daily data.`;

          await vscode.env.clipboard.writeText(collectCommand);
          await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
          await this.sleep(200);
          await vscode.commands.executeCommand("composer.submitChat");
          break;

        case "backfill":
          // Run the backfill skill
          vscode.window.showInformationMessage("Starting performance backfill...");
          await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
          await this.sleep(500);
          await vscode.commands.executeCommand("composer.focusComposer");
          await this.sleep(200);

          const backfillCommand = `Run the backfill skill to fill in missing days:

skill_run("performance/backfill_missing")

This will find any missing weekdays this quarter and collect data for them.`;

          await vscode.env.clipboard.writeText(backfillCommand);
          await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
          await this.sleep(200);
          await vscode.commands.executeCommand("composer.submitChat");
          break;

        case "evaluateAll":
        case "evaluate":
          // Run the evaluation skill
          const evalTarget = questionId ? `question "${questionId}"` : "all questions";
          vscode.window.showInformationMessage(`Evaluating ${evalTarget} with AI...`);
          await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
          await this.sleep(500);
          await vscode.commands.executeCommand("composer.focusComposer");
          await this.sleep(200);

          const evalInput = questionId ? `'{"question_id": "${questionId}"}'` : "";
          const evalCommand = `Run the question evaluation skill:

skill_run("performance/evaluate_questions"${evalInput ? `, ${evalInput}` : ""})

This will use AI to generate summaries for ${evalTarget} based on collected evidence.`;

          await vscode.env.clipboard.writeText(evalCommand);
          await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
          await this.sleep(200);
          await vscode.commands.executeCommand("composer.submitChat");
          break;

        case "exportReport":
          // Run the export skill
          vscode.window.showInformationMessage("Generating performance report...");
          await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
          await this.sleep(500);
          await vscode.commands.executeCommand("composer.focusComposer");
          await this.sleep(200);

          const exportCommand = `Run the report export skill:

skill_run("performance/export_report")

This will generate a comprehensive quarterly report in markdown format.`;

          await vscode.env.clipboard.writeText(exportCommand);
          await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
          await this.sleep(200);
          await vscode.commands.executeCommand("composer.submitChat");
          break;

        case "logActivity":
          if (category && description) {
            // Log manual activity via MCP tool
            vscode.window.showInformationMessage(`Logging ${category} activity...`);
            await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
            await this.sleep(500);
            await vscode.commands.executeCommand("composer.focusComposer");
            await this.sleep(200);

            const logCommand = `Log this manual performance activity:

performance_log_activity("${category}", "${description.replace(/"/g, '\\"')}")

This will add the activity to today's performance data.`;

            await vscode.env.clipboard.writeText(logCommand);
            await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
            await this.sleep(200);
            await vscode.commands.executeCommand("composer.submitChat");
          }
          break;

        case "addNote":
          if (questionId) {
            // Prompt for note text
            const noteText = await vscode.window.showInputBox({
              prompt: `Add a note for question: ${questionId}`,
              placeHolder: "Enter your note...",
            });

            if (noteText) {
              vscode.window.showInformationMessage(`Adding note to ${questionId}...`);
              await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
              await this.sleep(500);
              await vscode.commands.executeCommand("composer.focusComposer");
              await this.sleep(200);

              const noteCommand = `Add this note to the quarterly question:

performance_question_note("${questionId}", "${noteText.replace(/"/g, '\\"')}")

This will add the note as evidence for the question.`;

              await vscode.env.clipboard.writeText(noteCommand);
              await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
              await this.sleep(200);
              await vscode.commands.executeCommand("composer.submitChat");
            }
          }
          break;

        case "viewSummary":
          if (questionId) {
            // Show the question summary in a new document
            vscode.window.showInformationMessage(`Loading summary for ${questionId}...`);
            await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
            await this.sleep(500);
            await vscode.commands.executeCommand("composer.focusComposer");
            await this.sleep(200);

            const viewCommand = `Show the summary for this quarterly question:

performance_questions("${questionId}")

Display the question text, evidence, notes, and AI-generated summary.`;

            await vscode.env.clipboard.writeText(viewCommand);
            await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
            await this.sleep(200);
            await vscode.commands.executeCommand("composer.submitChat");
          }
          break;
      }

      // NOTE: performanceTabBadgeUpdate message removed - it was never handled in webview.
      // The PerformanceTab class handles its own badge updates via TabManager.
    } catch (e: any) {
      vscode.window.showErrorMessage(`Performance action failed: ${e.message}`);
    }
  }

  /**
   * Launch a new chat for a sprint issue.
   * @param issueKey Optional issue key - if not provided, prompts user
   * @param returnToCurrentChat If true, returns to the previously active chat after launching
   */
  private async testChatLauncher(issueKey?: string, returnToCurrentChat: boolean = false) {
    logger.log("testChatLauncher() called, returnToCurrentChat: " + returnToCurrentChat);

    try {
      // Import chat utilities
      const chatUtils = await import('./chatUtils');
      const { launchIssueChat, sendEnter, getActiveChatId, getComposerData } = chatUtils;

      // Debug: Show what we're getting from the database
      const composerData = getComposerData();
      const currentChatId = getActiveChatId();

      logger.log("Debug - composerData: " + (composerData ? "found" : "null"));
      logger.log("Debug - currentChatId: " + currentChatId);

      // If no issue key provided, prompt for one
      if (!issueKey) {
        const issueKeyPromise = vscode.window.showInputBox({
          prompt: "Enter a Jira issue key",
          placeHolder: "AAP-12345",
          value: "AAP-TEST-001",
        });

        // Auto-press Enter after a short delay to accept the default value
        setTimeout(() => {
          logger.log("Auto-pressing Enter for issue key input...");
          sendEnter();
        }, 250);

        issueKey = await issueKeyPromise;
      }

      if (!issueKey) {
        return;
      }

      // Launch the issue chat using the utility function
      // Format: "AAP-12345 short description" - Cursor keeps the issue key this way
      const chatId = await launchIssueChat(issueKey, {
        returnToPrevious: true,  // Return to current chat after creating new one
        autoApprove: false,
        summary: "sprint work",  // Short description that follows the issue key
      });

      if (chatId) {
        logger.log("Chat launched for " + issueKey + " chatId: " + chatId);

        // Wait a moment for Cursor to auto-name the chat, then verify
        logger.log("Waiting for Cursor to auto-name the chat...");
        await new Promise(resolve => setTimeout(resolve, 2000));

        // Check what name Cursor gave the chat
        const updatedData = getComposerData();
        const newChat = updatedData?.allComposers?.find((c: any) => c.composerId === chatId);
        const chatName = newChat?.name || "Unknown";

        logger.log("========================================");
        logger.log("VERIFICATION RESULTS");
        logger.log("========================================");
        logger.log("Expected pattern: '" + issueKey + " sprint work'");
        logger.log("Actual chat name: '" + chatName + "'");

        const hasIssueKey = chatName.includes(issueKey);
        if (hasIssueKey) {
          logger.log("SUCCESS: Chat name contains issue key!");
          vscode.window.showInformationMessage(
            `✅ Chat created: "${chatName}" - Issue key preserved!`
          );
        } else {
          logger.log("WARNING: Chat name does NOT contain issue key");
          vscode.window.showWarningMessage(
            `⚠️ Chat created but name is "${chatName}" - issue key was stripped`
          );
        }
      } else {
        logger.log("Chat launched for " + issueKey + " (no chatId returned)");
        vscode.window.showWarningMessage(`Chat created for ${issueKey} but no ID returned`);
      }

    } catch (e: any) {
      vscode.window.showErrorMessage(`Chat launcher failed: ${e.message}`);
      logger.error("Chat launcher error", e);
    }
  }

  /**
   * Helper to sleep for a given number of milliseconds
   */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // ============================================================================
  // Meeting History Handlers (using MeetingService)
  // These methods use MeetingService for data but handle VSCode-specific UI
  // ============================================================================

  private async _handleViewNoteWithService(noteId: number): Promise<void> {
    const note = await this._meetingService!.getMeetingNote(noteId);
    if (note) {
      const content = this._meetingService!.formatMeetingNote(note);
      const doc = await vscode.workspace.openTextDocument({
        content,
        language: 'markdown'
      });
      await vscode.window.showTextDocument(doc, { preview: false });
    } else {
      getNotificationService().warning(`Meeting note ${noteId} not found`);
    }
  }

  private async _handleViewTranscriptWithService(noteId: number): Promise<void> {
    const transcript = await this._meetingService!.getTranscript(noteId);
    if (transcript) {
      const content = this._meetingService!.formatTranscript(transcript);
      const doc = await vscode.workspace.openTextDocument({
        content,
        language: 'markdown'
      });
      await vscode.window.showTextDocument(doc, { preview: false });
    } else {
      getNotificationService().warning(`Transcript for meeting ${noteId} not found`);
    }
  }

  private async _handleViewBotLogWithService(noteId: number): Promise<void> {
    const log = await this._meetingService!.getBotLog(noteId);
    if (log) {
      const content = this._meetingService!.formatBotLog(log);
      const doc = await vscode.workspace.openTextDocument({
        content,
        language: 'log'
      });
      await vscode.window.showTextDocument(doc, { preview: false });
    } else {
      getNotificationService().warning(`Bot log for meeting ${noteId} not found`);
    }
  }

  private async _handleViewLinkedIssuesWithService(noteId: number): Promise<void> {
    const issues = await this._meetingService!.getLinkedIssues(noteId);
    if (issues && issues.length > 0) {
      const items = issues.map((issue) => ({
        label: issue.key || issue.id || 'Unknown',
        description: issue.summary || issue.title,
        url: issue.url || `https://issues.redhat.com/browse/${issue.key || issue.id}`
      }));
      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: 'Select an issue to open'
      });
      if (selected) {
        vscode.env.openExternal(vscode.Uri.parse(selected.url));
      }
    } else {
      getNotificationService().info('No linked issues found for this meeting');
    }
  }

  // Formatting helpers for meeting data
  private formatMeetingNote(note: any): string {
    const lines = [
      `# ${note.title || 'Meeting Notes'}`,
      '',
      `**Date:** ${note.date || 'Unknown'}`,
      `**Duration:** ${note.duration || 0} minutes`,
      `**Participants:** ${note.participants?.join(', ') || 'Unknown'}`,
      '',
      '## Summary',
      note.summary || '_No summary available_',
      '',
      '## Action Items',
      ...(note.actionItems?.map((item: string) => `- [ ] ${item}`) || ['_No action items_']),
      '',
      '## Key Points',
      ...(note.keyPoints?.map((point: string) => `- ${point}`) || ['_No key points_']),
      '',
    ];
    return lines.join('\n');
  }

  private formatTranscript(transcript: any): string {
    const entries = Array.isArray(transcript) ? transcript : (transcript.entries || []);
    const lines = [
      '# Meeting Transcript',
      '',
      `_${entries.length} entries_`,
      '',
      '---',
      '',
    ];

    for (const entry of entries) {
      const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '';
      lines.push(`**${entry.speaker || 'Unknown'}** ${time ? `(${time})` : ''}`);
      lines.push(entry.text || '');
      lines.push('');
    }

    return lines.join('\n');
  }

  private formatBotLog(log: any): string {
    const entries = Array.isArray(log) ? log : (log.entries || []);
    const lines = [
      '=== Meeting Bot Log ===',
      '',
    ];

    for (const entry of entries) {
      const time = entry.timestamp ? new Date(entry.timestamp).toISOString() : '';
      const level = entry.level || 'INFO';
      lines.push(`[${time}] [${level}] ${entry.message || entry.text || ''}`);
    }

    return lines.join('\n');
  }

  // ============================================================================
  // Config File Management
  // ============================================================================

  private async openConfigFile() {
    console.log("[CommandCenter] openConfigFile called, CONFIG_FILE:", CONFIG_FILE);
    try {
      if (fs.existsSync(CONFIG_FILE)) {
        console.log("[CommandCenter] Config file exists, opening...");
        const doc = await vscode.workspace.openTextDocument(CONFIG_FILE);
        await vscode.window.showTextDocument(doc);
        console.log("[CommandCenter] Config file opened successfully");
      } else {
        console.log("[CommandCenter] Config file not found at:", CONFIG_FILE);
        vscode.window.showErrorMessage("Config file not found");
      }
    } catch (e) {
      console.error("[CommandCenter] openConfigFile error:", e);
      vscode.window.showErrorMessage(`Failed to open config file: ${e}`);
    }
  }

  // ============================================================================
  // Tools Management
  // ============================================================================

  // Cache for tool modules loaded via D-Bus
  private _toolModulesCache: ToolModule[] | null = null;

  /**
   * Load tool modules via D-Bus from ConfigDaemon.
   */
  private async loadToolModulesAsync(): Promise<ToolModule[]> {
    try {
      const result = await dbus.config_getToolModules();
      if (result.success && result.data) {
        const data = result.data as any;
        const modules: ToolModule[] = (data.modules || []).map((m: any) => ({
          name: m.name,
          displayName: this._formatModuleName(m.name),
          description: this._getModuleDescription(m.name),
          toolCount: m.tool_count || 0,
          tools: [],
        }));
        this._toolModulesCache = modules.sort((a, b) => a.displayName.localeCompare(b.displayName));
        return this._toolModulesCache;
      }
    } catch (e) {
      console.error("Failed to load tool modules via D-Bus:", e);
    }
    return this._toolModulesCache || [];
  }

  /**
   * Returns cached tool modules (synchronous access).
   * Call loadToolModulesAsync() to refresh the cache.
   */
  private getCachedToolModules(): ToolModule[] {
    return this._toolModulesCache || [];
  }

  private _formatModuleName(name: string): string {
    const nameMap: Record<string, string> = {
      workflow: "Core Workflow",
      git: "Git",
      gitlab: "GitLab",
      jira: "Jira",
      k8s: "Kubernetes",
      bonfire: "Bonfire",
      quay: "Quay",
      konflux: "Konflux",
      prometheus: "Prometheus",
      alertmanager: "Alertmanager",
      kibana: "Kibana",
      slack: "Slack",
      google_calendar: "Google Calendar",
      concur: "SAP Concur",
      lint: "Linting",
      appinterface: "App Interface",
      dev_workflow: "Dev Workflow",
    };
    return nameMap[name] || name.split("_").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  }

  private _getModuleDescription(name: string): string {
    const descMap: Record<string, string> = {
      workflow: "Core tools: memory, sessions, skills, agents • All personas",
      git: "Git operations: commits, branches, diffs • 👨‍💻 📦",
      gitlab: "GitLab: MRs, CI/CD, pipelines • 👨‍💻",
      jira: "Jira: issues, sprints, comments • All personas",
      k8s: "Kubernetes: pods, deployments, logs • 🔧 🚨",
      bonfire: "Bonfire: ephemeral environments • 🔧",
      quay: "Quay: container images, tags • 🔧 📦",
      konflux: "Konflux: builds, pipelines • 📦",
      prometheus: "Prometheus: metrics, alerts • 🚨",
      alertmanager: "Alertmanager: alert management • 🚨",
      kibana: "Kibana: log search, dashboards • 🚨",
      slack: "Slack: messages, channels • 📊",
      google_calendar: "Google Calendar: events, meetings • 📊",
      concur: "SAP Concur: expense management • 📊",
      lint: "Code linting: flake8, black, ruff • 👨‍💻",
      appinterface: "App Interface: SaaS deployments • 📦",
      dev_workflow: "Development workflow helpers • 👨‍💻",
    };
    return descMap[name] || `Tools for ${name}`;
  }

  private _getModuleIcon(name: string): string {
    const iconMap: Record<string, string> = {
      workflow: "⚡",
      git: "📦",
      gitlab: "🦊",
      jira: "🎫",
      k8s: "☸️",
      bonfire: "🔥",
      quay: "🐳",
      konflux: "🔄",
      prometheus: "📊",
      alertmanager: "🚨",
      kibana: "📋",
      slack: "💬",
      google_calendar: "📅",
      concur: "💰",
      lint: "🔍",
      appinterface: "🔌",
      dev_workflow: "🛠️",
    };
    return iconMap[name] || "🔧";
  }

  /**
   * Get cached personas, triggering async load if not cached.
   */
  private getPersonas(): Persona[] {
    if (!this._personasCache) {
      // Trigger async load to populate cache
      this.loadPersonasAsync().catch(e => console.error("Failed to load personas:", e));
    }
    return this._personasCache || [];
  }

  /**
   * Get skills for a specific persona name.
   */
  private getSkillsForPersona(personaName: string): string[] {
    const personas = this.getPersonas();
    const persona = personas.find(p =>
      p.name === personaName ||
      p.fileName === personaName
    );
    return persona?.skills || [];
  }

  /**
   * Get tool count for a specific persona by calculating from its tool modules.
   * This is used as a fallback when session.tool_count is not available.
   */
  private getToolCountForPersona(personaName: string): number {
    const personas = this.getPersonas();
    const persona = personas.find(p =>
      p.name === personaName ||
      p.fileName === personaName
    );
    // Use cached toolCount from persona if available
    if (persona?.toolCount) {
      return persona.toolCount;
    }
    // Otherwise calculate from tool modules
    if (persona?.tools) {
      return persona.tools.reduce((sum: number, moduleName: string) => {
        return sum + this.countToolsInModule(moduleName);
      }, 0);
    }
    return 0;
  }

  /**
   * Count actual tools in a tool module by scanning for @tool decorators.
   */
  private countToolsInModule(moduleName: string): number {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      path.join(os.homedir(), "src", "redhat-ai-workflow");

    // Handle _basic and _extra suffixes
    const baseName = moduleName.replace("_basic", "").replace("_extra", "");
    const moduleDir = path.join(workspaceRoot, "tool_modules", `aa_${baseName}`, "src");

    if (!fs.existsSync(moduleDir)) {
      return 0;
    }

    // Determine which file to check
    let filesToCheck: string[];
    if (moduleName.endsWith("_basic")) {
      filesToCheck = ["tools_basic.py"];
    } else if (moduleName.endsWith("_extra")) {
      filesToCheck = ["tools_extra.py"];
    } else {
      filesToCheck = ["tools_basic.py", "tools.py"];
    }

    for (const filename of filesToCheck) {
      const toolsFile = path.join(moduleDir, filename);
      if (fs.existsSync(toolsFile)) {
        try {
          const content = fs.readFileSync(toolsFile, "utf-8");
          // Count @server.tool, @registry.tool, or @mcp.tool decorators
          const matches = content.match(/@(?:server|registry|mcp)\.tool\s*\(/g);
          return matches ? matches.length : 0;
        } catch {
          // Ignore read errors
        }
      }
    }
    return 0;
  }

  /**
   * Load personas via D-Bus from ConfigDaemon.
   * Falls back to file-based loading if D-Bus fails.
   */
  private async loadPersonasAsync(): Promise<Persona[]> {
    try {
      const result = await dbus.config_getPersonasList();
      if (result.success && result.data) {
        const data = result.data as any;
        const personas: Persona[] = (data.personas || []).map((p: any) => {
          const fileName = p.file ? path.basename(p.file).replace(".yaml", "") : p.name;
          const isSlim = fileName.includes("-slim");
          const isInternal = ["core", "universal"].includes(fileName);
          const isAgent = fileName === "slack";

          // Calculate tool count from tools list
          const toolCount = (p.tools || []).reduce((sum: number, moduleName: string) => {
            return sum + this.countToolsInModule(moduleName);
          }, 0);

          return {
            name: p.name,
            fileName,
            description: p.description || "",
            tools: p.tools || [],
            toolCount,
            skills: p.skills || [],
            personaFile: undefined,
            isSlim,
            isInternal,
            isAgent,
          };
        });

        // Sort and cache
        this._personasCache = this.sortPersonas(personas);
        return this._personasCache;
      }
    } catch (e) {
      console.error("Failed to load personas via D-Bus:", e);
    }
    return this._personasCache || [];
  }

  /**
   * Sort personas: main personas first, then slim variants, then internal/agents.
   */
  private sortPersonas(personas: Persona[]): Persona[] {
    return personas.sort((a, b) => {
      if (a.isInternal !== b.isInternal) return a.isInternal ? 1 : -1;
      if (a.isAgent !== b.isAgent) return a.isAgent ? 1 : -1;
      if (a.isSlim !== b.isSlim) return a.isSlim ? 1 : -1;
      return a.name.localeCompare(b.name);
    });
  }

  /**
   * Returns cached personas (synchronous access).
   * Call loadPersonasAsync() to refresh the cache.
   */
  private getCachedPersonas(): Persona[] {
    return this._personasCache || [];
  }

  private _getPersonaIcon(name: string): string {
    const iconMap: Record<string, string> = {
      developer: "👨‍💻",
      devops: "🔧",
      incident: "🚨",
      release: "📦",
      admin: "📊",
      slack: "💬",
      core: "⚙️",
      universal: "🌐",
      researcher: "🔍",
      meetings: "📅",
      observability: "📈",
      project: "📁",
      workspace: "🏠",
      code: "💻",
    };
    return iconMap[name] || "🤖";
  }

  private _getPersonaColor(name: string): string {
    const colorMap: Record<string, string> = {
      developer: "purple",
      devops: "cyan",
      incident: "pink",
      release: "green",
      admin: "orange",
      slack: "blue",
      core: "gray",
      universal: "gray",
      researcher: "yellow",
      meetings: "teal",
      observability: "indigo",
      project: "amber",
      workspace: "slate",
      code: "violet",
    };
    return colorMap[name] || "purple";
  }

  private _renderPersonaCards(personas: Persona[], activeAgent: { name: string }): string {
    return personas.map(persona => {
      const isActive = activeAgent.name === persona.name || activeAgent.name === persona.fileName;
      const displayFileName = persona.fileName || persona.name;
      const typeBadge = persona.isSlim ? '<span class="persona-type-badge slim">slim</span>' :
                       persona.isInternal ? '<span class="persona-type-badge internal">internal</span>' :
                       persona.isAgent ? '<span class="persona-type-badge agent">agent</span>' : '';

      const toolTags = persona.tools.slice(0, 6).map(t => `<span class="persona-tag tool">${t}</span>`).join("");
      const moreTools = persona.tools.length > 6 ? `<span class="persona-tag">+${persona.tools.length - 6} more</span>` : '';
      const noTools = persona.tools.length === 0 ? '<span class="persona-tag empty">none defined</span>' : '';

      const skillTags = persona.skills.slice(0, 8).map(s => `<span class="persona-tag skill">${s}</span>`).join("");
      const moreSkills = persona.skills.length > 8 ? `<span class="persona-tag">+${persona.skills.length - 8} more</span>` : '';
      const noSkills = persona.skills.length === 0 ? '<span class="persona-tag empty">all skills</span>' : '';

      return `
      <div class="persona-card ${isActive ? "active" : ""} ${persona.isSlim ? "slim" : ""} ${persona.isInternal ? "internal" : ""} ${persona.isAgent ? "agent" : ""}" data-persona="${displayFileName}">
        <div class="persona-header">
          <div class="persona-icon ${this._getPersonaColor(persona.name)}">
            ${this._getPersonaIcon(persona.name)}
          </div>
          <div class="persona-info">
            <div class="persona-name">${persona.name}${typeBadge}</div>
            <div class="persona-desc">${persona.description || displayFileName}</div>
          </div>
          ${isActive ? '<span class="persona-active-badge">Active</span>' : ''}
        </div>
        <div class="persona-body">
          <div class="persona-section">
            <div class="persona-section-title">🔧 Tools (${persona.toolCount}) from ${persona.tools.length} modules</div>
            <div class="persona-tags">
              ${toolTags}${moreTools}${noTools}
            </div>
          </div>
          <div class="persona-section">
            <div class="persona-section-title">⚡ Skills (${persona.skills.length})</div>
            <div class="persona-tags">
              ${skillTags}${moreSkills}${noSkills}
            </div>
          </div>
        </div>
        <div class="persona-footer">
          <button class="btn btn-${isActive ? "ghost" : "primary"} btn-small" data-action="loadPersona" data-persona="${displayFileName}" ${isActive ? "disabled" : ""}>
            ${isActive ? "✓ Active" : "🔄 Load"}
          </button>
          <button class="btn btn-ghost btn-small" data-action="viewPersonaFile" data-persona="${displayFileName}">
            📄 View Config
          </button>
        </div>
      </div>
      `;
    }).join("");
  }

  private _formatRelativeTime(isoString: string): string {
    try {
      const date = new Date(isoString);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      const diffDays = Math.floor(diffMs / 86400000);

      if (diffMins < 1) return "Just now";
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays < 7) return `${diffDays}d ago`;
      return date.toLocaleDateString();
    } catch {
      return "Unknown";
    }
  }

  // ============================================================================
  // Workspace State Methods
  // ============================================================================

  /**
   * Load all daemon state via D-Bus.
   *
   * ARCHITECTURE: UI communicates with daemons ONLY via D-Bus.
   * - All reads go through D-Bus get_state methods
   * - All writes go through D-Bus action methods
   * - State files are internal to daemons (UI never reads/writes them)
   *
   * This prevents race conditions and ensures daemons own their state.
   */
  private _loadWorkspaceState(): void {
    // Trigger async D-Bus load - results will update UI when ready
    this._loadWorkspaceStateViaDBus().catch(e => {
      debugLog(`D-Bus state load failed, using cached data: ${e}`);
    });
  }

  /**
   * Load all daemon state via D-Bus (async implementation).
   */
  private async _loadWorkspaceStateViaDBus(): Promise<void> {
    // Load all daemon states in parallel via D-Bus
    const [sessionResult, meetResult, cronResult] = await Promise.all([
      this._loadSessionStateViaDBus(),
      this._loadMeetStateViaDBus(),
      this._loadCronStateViaDBus(),
    ]);

    // Update UI state from D-Bus results
    if (sessionResult) {
      this._workspaceState = sessionResult.workspaces || {};
      this._workspaceCount = sessionResult.workspace_count || Object.keys(this._workspaceState || {}).length;
      debugLog(`D-Bus session state: ${this._workspaceCount} workspaces`);
    }

    if (meetResult) {
      this._meetData = meetResult;
      debugLog(`D-Bus meet state: ${this._meetData.upcomingMeetings?.length || 0} upcoming`);
    }

    if (cronResult) {
      this._cronData = cronResult;
      debugLog(`D-Bus cron state: ${this._cronData.jobs?.length || 0} jobs`);
    }

    // Sprint state is loaded separately via _loadSprintStateViaDBus()
    this._sprintIssues = [];
    this._sprintIssuesUpdated = "";

    // Ollama/slack - these don't have daemons yet, keep empty for now
    // TODO: Add to slack daemon when D-Bus interface is added
    this._ollama = {};
    this._slackChannels = [];
  }

  /**
   * Load session state via D-Bus from BotSession daemon.
   */
  private async _loadSessionStateViaDBus(): Promise<any> {
    try {
      const result = await dbus.session_getState();

      if (result.success && result.data) {
        const data = result.data as any;
        // Handle both direct state and wrapped {success, state} format
        if (data.state) {
          return data.state;
        }
        return data;
      }
      debugLog(`Session D-Bus get_state failed: ${result.error}`);
      return null;
    } catch (e: any) {
      debugLog(`Session D-Bus error: ${e.message}`);
      return null;
    }
  }

  /**
   * Load meet state via D-Bus from BotMeet daemon.
   */
  private async _loadMeetStateViaDBus(): Promise<any> {
    try {
      const result = await dbus.meet_getState();

      if (result.success && result.data) {
        if (result.data.state) {
          return result.data.state;
        }
        return result.data;
      }
      debugLog(`Meet D-Bus get_state failed: ${result.error}`);
      return null;
    } catch (e: any) {
      debugLog(`Meet D-Bus error: ${e.message}`);
      return null;
    }
  }

  /**
   * Load cron state via D-Bus from BotCron daemon.
   */
  private async _loadCronStateViaDBus(): Promise<any> {
    try {
      const result = await dbus.cron_getState();

      if (result.success && result.data) {
        if (result.data.state) {
          return result.data.state;
        }
        return result.data;
      }
      debugLog(`Cron D-Bus get_state failed: ${result.error}`);
      return null;
    } catch (e: any) {
      debugLog(`Cron D-Bus error: ${e.message}`);
      return null;
    }
  }

  /**
   * Load sprint state via D-Bus from BotSprint daemon.
   */
  private async _loadSprintStateViaDBus(): Promise<any> {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSprint",
        "/com/aiworkflow/BotSprint",
        "com.aiworkflow.BotSprint",
        "CallMethod",
        [
          { type: "string", value: "get_state" },
          { type: "string", value: "{}" },
        ]
      );

      if (result.success && result.data) {
        if (result.data.state) {
          return result.data.state;
        }
        return result.data;
      }
      debugLog(`Sprint D-Bus get_state failed: ${result.error}`);
      return null;
    } catch (e: any) {
      debugLog(`Sprint D-Bus error: ${e.message}`);
      return null;
    }
  }

  /**
   * ARCHITECTURE: State is now loaded via D-Bus from daemons.
   * File watching is REMOVED - D-Bus polling handles all updates.
   *
   * The 10-second auto-refresh interval in the constructor calls
   * _loadWorkspaceState() which loads state via D-Bus from all daemons.
   */
  private _setupWorkspaceWatcher(): void {
    // File watching removed - all state comes from D-Bus now
    // The 10-second auto-refresh interval handles updates via D-Bus polling
    debugLog("State loaded via D-Bus - no file watching needed");
  }

  /**
   * Dispatch updates to UI sections.
   * 
   * NOTE: RefreshCoordinator was removed - it was sending messages that were never handled
   * in the webview. UI updates now go through TabManager and tabContentUpdate messages.
   * This method is kept for backward compatibility but only updates workspaces.
   */
  private _dispatchAllUIUpdates(_priority?: any): void {
    // Update workspaces tab (has its own rendering logic)
    this._updateWorkspacesTab();
  }

  /**
   * Format services data for UI consumption.
   */
  private _formatServicesForUI(): any[] {
    const serviceNames = ["slack", "cron", "meet", "sprint", "video", "session", "config", "memory", "stats"];
    const nameMap: Record<string, string> = {
      slack: "Slack Agent",
      cron: "Cron Scheduler",
      meet: "Meet Bot",
      sprint: "Sprint Bot",
      video: "Video Bot",
      session: "Session Manager",
      config: "Config Daemon",
      memory: "Memory Daemon",
      stats: "Stats Daemon",
    };
    return serviceNames.map(name => {
      const svc = this._services[name] || {};
      return {
        name: nameMap[name] || name,
        ...svc,
      };
    });
  }

  /**
   * Tiered background sync using epoch time modulo for efficient polling.
   * Called every 1 second by the interval timer.
   *
   * STAGGERED REFRESH SCHEDULE (to avoid D-Bus request spikes):
   * 
   * Second 0:  Session state only
   * Second 1:  Session state only
   * Second 2:  Session state + Slop tab (if not active)
   * Second 3:  Session state only
   * Second 4:  Session state + Meetings tab (if not active)
   * Second 5:  Session state + Active tab refresh + Badge update
   * Second 6:  Session state + Cron tab (if not active)
   * Second 7:  Session state only
   * Second 8:  Session state + Slack tab (if not active)
   * Second 9:  Session state only
   * Second 10: Session state + Active tab + Background sync (services, Ollama, MCP)
   * ... pattern repeats with staggered critical tab refreshes
   *
   * This spreads D-Bus load across time instead of bursting at specific seconds.
   */
  private _tieredBackgroundSync(): void {
    const epochSecond = Math.floor(Date.now() / 1000);
    const cycleSecond = epochSecond % 30; // 30-second cycle

    // TIER 1: Every 1 second - Session state (active session detection)
    // This is critical for showing which session is currently active
    this._loadSessionStateViaDBus().then(sessionResult => {
      if (sessionResult) {
        this._workspaceState = sessionResult.workspaces || {};
        this._workspaceCount = sessionResult.workspace_count || Object.keys(this._workspaceState || {}).length;
        this._updateWorkspacesTab();
      }
    }).catch(e => {
      debugLog(`Tiered sync: Failed to load session state: ${e}`);
    });

    // TIER 2: Every 5 seconds - Refresh active tab + update all badges
    // Fires at: 0, 5, 10, 15, 20, 25
    if (cycleSecond % 5 === 0) {
      const activeTab = this._tabManager.getTab(this._currentTab);
      if (activeTab) {
        this._logActivity(`Refreshing ${this._currentTab}`);
        activeTab.loadData().then(() => {
          this._triggerTabRerender();
          this._updateAllTabBadges();
        }).catch(e => {
          debugLog(`Tiered sync: Failed to refresh active tab ${this._currentTab}: ${e}`);
        });
      } else {
        // Still update badges even if no active tab
        this._updateAllTabBadges();
      }
    }

    // TIER 3: Every 10 seconds - Background sync (services, Ollama, MCP)
    // Fires at: 0, 10, 20 - but OFFSET by 1 second to avoid collision with Tier 2
    if (cycleSecond === 1 || cycleSecond === 11 || cycleSecond === 21) {
      this._backgroundSync();
    }

    // TIER 4: Staggered critical tab refresh (one tab per designated second)
    // Each critical tab gets refreshed once per 30-second cycle, spread out
    // This prevents D-Bus request spikes
    this._refreshStaggeredTab(cycleSecond);
  }

  /**
   * Refresh a single critical tab based on the current cycle second.
   * Spreads tab refreshes across the 30-second cycle to avoid D-Bus spikes.
   * 
   * Schedule:
   *   Second 2:  slop
   *   Second 4:  meetings  
   *   Second 6:  cron
   *   Second 8:  slack
   *   Second 12: services
   *   Second 14: inference
   *   Second 16: slop (2nd refresh for running scans)
   *   Second 18: skills (skill list rarely changes, 30s is enough)
   *   Second 22: meetings (2nd refresh for active meetings)
   */
  private _refreshStaggeredTab(cycleSecond: number): void {
    const schedule: Record<number, string> = {
      2: "slop",
      4: "meetings",
      6: "cron",
      8: "slack",
      12: "services",
      14: "inference",
      16: "slop",      // Extra refresh for slop (running scans need updates)
      18: "skills",    // Skills list rarely changes, 30s refresh is enough
      22: "meetings",  // Extra refresh for meetings (active meetings need updates)
    };

    const tabId = schedule[cycleSecond];
    if (!tabId) return;

    // Skip if this is the active tab (already refreshed every 5 seconds)
    if (tabId === this._currentTab) {
      debugLog(`Staggered refresh: Skipping ${tabId} (active tab)`);
      return;
    }

    const tab = this._tabManager.getTab(tabId);
    if (tab) {
      debugLog(`Staggered refresh: Loading ${tabId} at cycle second ${cycleSecond}`);
      this._logActivity(`Syncing ${tabId}`);
      tab.loadData().then(() => {
        // Update badges after this tab loads
        this._updateAllTabBadges();
      }).catch(e => {
        debugLog(`Staggered refresh: Failed to refresh ${tabId}: ${e}`);
      });
    }
  }

  /**
   * Log an activity message to the header activity log.
   * Shows the user what background refreshes are happening.
   */
  private _logActivity(message: string): void {
    if (this._panel) {
      this._panel.webview.postMessage({
        command: "activityLog",
        text: message,
      });
    }
  }

  /**
   * Update all tab badges by sending badge data to the webview.
   * This is lightweight - just reads cached state from tabs.
   */
  private _updateAllTabBadges(): void {
    const badges = this._tabManager.getAllBadges();
    if (this._panel) {
      this._panel.webview.postMessage({
        command: "updateBadges",
        badges: badges,
      });
    }
  }

  /**
   * Full background refresh - reloads ALL data from cache and D-Bus.
   * Called every 10 seconds by _tieredBackgroundSync(), and also used for
   * manual refresh requests (user clicks refresh button) or after user actions.
   *
   * ARCHITECTURE: All daemon state is loaded via D-Bus polling.
   * No file watching or sync processes are used.
   */
  private _backgroundSync(): void {
    this._logActivity("Background sync");
    
    // Clear personas cache to ensure fresh data on next access
    this._personasCache = null;

    // Just reload from file and update UI - no sync process spawning
    this._loadWorkspaceState();
    this.update(false);
    this.getInferenceStats();

    // Also refresh service status via D-Bus
    // This is async but we don't need to wait - it will dispatch its own UI update when done
    this._refreshServicesViaDBus().catch(e => {
      debugLog(`Failed to refresh services via D-Bus: ${e}`);
    });

    // Refresh Ollama status via systemd
    this.refreshOllamaStatus().catch(e => {
      debugLog(`Failed to refresh Ollama status: ${e}`);
    });

    // Refresh MCP server status
    this.checkMCPServerStatus().catch(e => {
      debugLog(`Failed to check MCP status: ${e}`);
    });
  }

  /**
   * Refresh service status by querying D-Bus directly.
   * Updates this._services which is used by _formatServicesForUI().
   */
  private async _refreshServicesViaDBus(): Promise<void> {
    debugLog(`_refreshServicesViaDBus: Starting refresh for ${DBUS_SERVICES.length} services`);

    for (const service of DBUS_SERVICES) {
      try {
        debugLog(`_refreshServicesViaDBus: Querying ${service.service}`);
        const result = await this.queryDBus(
          service.service,
          service.path,
          service.interface,
          "GetStatus"
        );
        debugLog(`_refreshServicesViaDBus: ${service.service} result: success=${result.success}, data=${JSON.stringify(result.data)?.substring(0, 100)}`);

        // Map D-Bus service name to our internal key
        const keyMap: Record<string, string> = {
          "com.aiworkflow.BotSlack": "slack",
          "com.aiworkflow.BotCron": "cron",
          "com.aiworkflow.BotMeet": "meet",
          "com.aiworkflow.BotSprint": "sprint",
          "com.aiworkflow.BotSession": "session",
          "com.aiworkflow.BotVideo": "video",
          "com.aiworkflow.BotConfig": "config",
          "com.aiworkflow.Memory": "memory",
          "com.aiworkflow.BotStats": "stats",
        };
        const key = keyMap[service.service];
        if (key) {
          if (result.success) {
            this._services[key] = { running: true, status: result.data };
            debugLog(`_refreshServicesViaDBus: Set ${key} to running=true`);
          } else {
            this._services[key] = { running: false, error: result.error };
            debugLog(`_refreshServicesViaDBus: Set ${key} to running=false, error=${result.error}`);
          }
        }
      } catch (e) {
        // Service not available - mark as not running
        debugLog(`_refreshServicesViaDBus: Exception for ${service.service}: ${e}`);
        const keyMap: Record<string, string> = {
          "com.aiworkflow.BotSlack": "slack",
          "com.aiworkflow.BotCron": "cron",
          "com.aiworkflow.BotMeet": "meet",
          "com.aiworkflow.BotSprint": "sprint",
          "com.aiworkflow.BotSession": "session",
          "com.aiworkflow.BotVideo": "video",
          "com.aiworkflow.BotConfig": "config",
          "com.aiworkflow.Memory": "memory",
          "com.aiworkflow.BotStats": "stats",
        };
        const key = keyMap[service.service];
        if (key) {
          this._services[key] = { running: false, error: "Service not available" };
        }
      }
    }

    debugLog(`_refreshServicesViaDBus: Final this._services = ${JSON.stringify(this._services)}`);
    // Dispatch UI update with new service status
    this._dispatchAllUIUpdates();
  }

  /**
   * Refresh sessions via D-Bus from the Session daemon.
   *
   * ARCHITECTURE: Session state is loaded via D-Bus polling.
   */
  private async _syncAndRefreshSessions(): Promise<void> {
    // Show loading state briefly
    this._panel.webview.postMessage({
      command: "updateSessionsLoading",
      loading: true,
    });

    // Reload from file and refresh UI
    this._loadWorkspaceState();
    this._updateWorkspacesTab();

    this._panel.webview.postMessage({
      command: "updateSessionsLoading",
      loading: false,
    });
  }

  /**
   * Trigger a re-render of the active tab's content.
   * Called when a tab's internal state changes (e.g., view mode toggle).
   */
  private _triggerTabRerender(): void {
    if (!this._panel.webview) {
      debugLog("_triggerTabRerender: No webview, skipping");
      return;
    }

    // Get the active tab's content and send it to the webview
    const activeTabId = this._tabManager.getActiveTabId();
    const activeTab = this._tabManager.getActiveTab();
    debugLog(`_triggerTabRerender: activeTabId=${activeTabId}, _currentTab=${this._currentTab}`);

    // Use _currentTab as fallback if TabManager's activeTabId is out of sync
    const targetTabId = this._currentTab || activeTabId;
    const targetTab = this._tabManager.getTab(targetTabId) || activeTab;

    if (!targetTab) {
      debugLog("_triggerTabRerender: No target tab found");
      return;
    }

    try {
      // Use getContent() to get just the inner content, not the wrapper div
      // The webview already has the wrapper div with id="${tabId}"
      const content = targetTab.getContent();
      const styles = targetTab.getStyles();
      const script = targetTab.getScript();

      debugLog(`_triggerTabRerender: Tab ${targetTab.getId()}, content length: ${content?.length || 0}, script length: ${script?.length || 0}`);

      // Log first 200 chars of content for debugging
      if (content) {
        debugLog(`_triggerTabRerender: Content preview: ${content.substring(0, 200).replace(/\n/g, ' ')}...`);
      }

      this._panel.webview.postMessage({
        type: "tabContentUpdate",
        tabId: targetTab.getId(),
        content,
        styles,
        script,
      });
      debugLog("_triggerTabRerender: Message sent");
    } catch (err) {
      debugLog(`_triggerTabRerender: Error - ${err}`);
    }
  }

  private _updateWorkspacesTab(): void {
    if (this._panel.webview) {
      this._panel.webview.postMessage({
        type: "updateWorkspaces",
        workspaces: this._workspaceState,
        count: this._workspaceCount,
        totalSessions: this._getTotalSessionCount(),
        uniquePersonas: this._getUniquePersonaCount(),
        uniqueProjects: this._getUniqueProjectCount(),
        groupBy: this._sessionGroupBy,
        // Always send pre-rendered HTML to ensure consistency
        renderedHtml: this._renderWorkspaces(),
      });
    }
  }

  private _updatePersonasTab(): void {
    if (this._panel.webview) {
      this._panel.webview.postMessage({
        type: "updatePersonas",
        viewMode: this._personaViewMode,
      });
    }
  }

  private _getUniquePersonaCount(): number {
    if (!this._workspaceState) return 0;
    const personas = new Set<string>();
    Object.values(this._workspaceState).forEach((ws) => {
      // Count personas from all sessions
      Object.values(ws.sessions || {}).forEach((session) => {
        if (session.persona) personas.add(session.persona);
      });
    });
    return personas.size;
  }

  private _getUniqueProjectCount(): number {
    if (!this._workspaceState) return 0;
    const projects = new Set<string>();
    Object.values(this._workspaceState).forEach((ws) => {
      // Count workspace-level project
      if (ws.project) projects.add(ws.project);
      // Also count per-session projects (sessions can have different projects)
      Object.values(ws.sessions || {}).forEach((session) => {
        if (session.project) projects.add(session.project);
      });
    });
    return projects.size;
  }

  private _getTotalSessionCount(): number {
    // Only count initialized MCP sessions
    let count = 0;
    if (this._workspaceState) {
      Object.values(this._workspaceState).forEach((ws) => {
        count += Object.keys(ws.sessions || {}).length;
      });
    }
    return count;
  }

  private _renderWorkspaces(): string {
    // Always try to render sessions grouped (shows Cursor chats if no MCP sessions)
    if (this._sessionViewMode === 'table') {
      return this._renderSessionsTable();
    }
    return this._renderSessionsGrouped();
  }

  private _renderSessionsTable(): string {
    // Collect all sessions for table view
    const allSessions: Array<{ session: ChatSession; workspaceUri: string; workspaceProject: string | null; isActive: boolean }> = [];

    // Get the active session ID from workspace state (synced from Cursor's lastFocusedComposerIds)
    let activeSessionId: string | null = null;
    if (this._workspaceState) {
      for (const [uri, ws] of Object.entries(this._workspaceState)) {
        if (ws.active_session_id) {
          activeSessionId = ws.active_session_id;
        }
        const sessions = ws.sessions || {};
        for (const [sid, session] of Object.entries(sessions)) {
          allSessions.push({
            session: session as ChatSession,
            workspaceUri: uri,
            workspaceProject: ws.project,
            isActive: sid === ws.active_session_id
          });
        }
      }
    }

    if (allSessions.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-state-icon">💬</div>
          <div>No active sessions</div>
          <div class="text-sm mt-8">
            Start a session with <code>session_start()</code> in a Cursor chat
          </div>
        </div>
      `;
    }

    // Sort by last activity (most recent first)
    allSessions.sort((a, b) => {
      const aTime = a.session?.last_activity ? new Date(a.session.last_activity).getTime() : 0;
      const bTime = b.session?.last_activity ? new Date(b.session.last_activity).getTime() : 0;
      return bTime - aTime;
    });

    // If no active session from Cursor, mark the most recent as active
    const hasActiveSession = allSessions.some(s => s.isActive);
    if (!hasActiveSession && allSessions.length > 0) {
      allSessions[0].isActive = true;
    }

    return `
      <div class="sessions-table-container">
        <table class="data-table sessions-data-table">
          <thead>
            <tr>
              <th class="col-icon"></th>
              <th class="col-name text-left">Name</th>
              <th class="col-project">Project</th>
              <th class="col-persona">Persona</th>
              <th class="col-issue">Issue</th>
              <th class="col-time">Last Active</th>
              <th class="col-count">Tools</th>
              <th class="col-count">Skills</th>
              <th class="col-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            ${allSessions.map(item => {
              const session = item.session;
              const sessionId = session.session_id;
              const persona = session.persona || "developer";
              const personaIcon = this._getPersonaIcon(persona);
              const personaColor = this._getPersonaColor(persona);
              // Dual tool count: show dynamic (filtered) if available, else static (baseline)
              // If no tool count stored, calculate from persona's tool modules
              const isDynamic = (session.dynamic_tool_count ?? 0) > 0;
              let toolCount = session.tool_count ?? session.static_tool_count ?? (session as any).active_tools?.length ?? 0;
              if (toolCount === 0) {
                // Fallback: calculate from persona's tool modules
                toolCount = this.getToolCountForPersona(persona);
              }
              const toolLabel = isDynamic ? `${toolCount} ⚡` : `${toolCount}`;
              const toolTitle = isDynamic
                ? `${toolCount} tools (filtered for context)`
                : `${toolCount} tools available for ${persona}`;
              // Get skills for this persona
              const skills = this.getSkillsForPersona(persona);
              const skillsCount = skills.length > 0 ? skills.length : 'all';
              const skillsTitle = skills.length > 0
                ? `${skills.length} skills: ${skills.join(', ')}`
                : 'All skills available';
              const lastActivity = session.last_activity ? this._formatRelativeTime(session.last_activity) : "Unknown";
              const sessionName = session.name || `Session ${sessionId.substring(0, 6)}`;
              const sessionProject = (session as any).project || item.workspaceProject || '-';
              const issueKeys = session.issue_key ? session.issue_key.split(', ') : [];

              return `
              <tr class="${item.isActive ? 'row-active' : ''}" data-session-id="${sessionId}">
                <td><span class="persona-icon-small ${personaColor}">${personaIcon}</span></td>
                <td class="text-left">
                  <span class="clickable" data-action="openChatSession" data-session-id="${sessionId}" data-session-name="${sessionName.replace(/"/g, '&quot;')}" title="Click to find this chat">
                    <strong>${sessionName}</strong>
                  </span>
                  ${item.isActive ? ' <span class="active-badge-small">Active</span>' : ''}
                </td>
                <td>${sessionProject}</td>
                <td><span class="persona-badge-small ${personaColor}">${persona}</span></td>
                <td class="issue-cell">${issueKeys.length > 0 ? `<div class="issue-badges-container">${issueKeys.map(k => `<a href="https://issues.redhat.com/browse/${k}" class="issue-badge-small issue-link" title="Open ${k} in Jira">${k}</a>`).join('')}</div>` : '-'}</td>
                <td>${lastActivity}</td>
                <td title="${toolTitle}">${toolLabel}</td>
                <td title="${skillsTitle}">${skillsCount}</td>
                <td>
                  <button class="btn btn-ghost btn-small" data-action="copySessionId" data-session-id="${sessionId}" title="Copy Session ID">📋</button>
                  <button class="btn btn-ghost btn-small" data-action="viewSessionTools" data-session-id="${sessionId}" title="View Tools">🔧</button>
                  ${session.meeting_references && session.meeting_references.length > 0 ? `<button class="btn btn-ghost btn-small meeting-notes-btn" data-action="viewMeetingNotes" data-session-id="${sessionId}" title="View ${session.meeting_references.length} meeting(s) where issues were discussed">📝</button>` : ''}
                </td>
              </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  private _renderSessionsGrouped(): string {
    // Only show initialized MCP sessions
    const allSessions: Array<{ session: ChatSession; workspaceUri: string; workspaceProject: string | null; isActive: boolean }> = [];

    if (this._workspaceState) {
      for (const [uri, ws] of Object.entries(this._workspaceState)) {
        const sessions = ws.sessions || {};
        for (const [sid, session] of Object.entries(sessions)) {
          allSessions.push({
            session: session as ChatSession,
            workspaceUri: uri,
            workspaceProject: ws.project,
            isActive: sid === ws.active_session_id  // From Cursor's lastFocusedComposerIds
          });
        }
      }
    }

    if (allSessions.length === 0) {
      return `
        <div class="empty-state">
          <div class="empty-state-icon">💬</div>
          <div>No active sessions</div>
          <div class="text-sm mt-8">
            Start a session with <code>session_start()</code> in a Cursor chat
          </div>
        </div>
      `;
    }

    // Sort all sessions by last_activity to find the most recent one
    allSessions.sort((a, b) => {
      const aTime = a.session?.last_activity ? new Date(a.session.last_activity).getTime() : 0;
      const bTime = b.session?.last_activity ? new Date(b.session.last_activity).getTime() : 0;
      return bTime - aTime;
    });

    // If no active session from Cursor, mark the most recent as active
    const hasActiveSession = allSessions.some(s => s.isActive);
    if (!hasActiveSession && allSessions.length > 0) {
      allSessions[0].isActive = true;
    }

    // Group sessions by project
    const groups: Map<string, typeof allSessions> = new Map();

    for (const item of allSessions) {
      const groupKey = (item.session as any)?.project || item.workspaceProject || 'No Project';
      if (!groups.has(groupKey)) {
        groups.set(groupKey, []);
      }
      groups.get(groupKey)!.push(item);
    }

    const sortedGroups = Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === 'No Project') return 1;
      if (b[0] === 'No Project') return -1;
      return a[0].localeCompare(b[0]);
    });

    return sortedGroups.map(([groupName, items]) => {
      const groupIcon = this._getGroupIcon(groupName);
      const groupColor = this._getGroupColor(groupName);

      // Sort within group by last_activity (already sorted globally, but re-sort for display)
      items.sort((a, b) => {
        const aTime = a.session?.last_activity ? new Date(a.session.last_activity).getTime() : 0;
        const bTime = b.session?.last_activity ? new Date(b.session.last_activity).getTime() : 0;
        return bTime - aTime;
      });

      const sessionsHtml = items.map(item =>
        this._renderSessionCard(item.session!.session_id, item.session!, item.isActive)
      ).join('');

      return `
        <div class="session-group">
          <div class="session-group-header ${groupColor}">
            <span class="group-icon">${groupIcon}</span>
            <span class="group-name">${groupName}</span>
            <span class="group-count">${items.length} session${items.length !== 1 ? 's' : ''}</span>
          </div>
          <div class="session-group-content">
            ${sessionsHtml}
          </div>
        </div>
      `;
    }).join('');
  }

  private _getGroupIcon(groupName: string): string {
    // Icons for personas
    const personaIcons: Record<string, string> = {
      'developer': '👨‍💻',
      'devops': '🔧',
      'incident': '🚨',
      'release': '🚀'
    };

    if (personaIcons[groupName.toLowerCase()]) {
      return personaIcons[groupName.toLowerCase()];
    }

    // Icons for projects (or default)
    if (groupName === 'No Project') return '📁';
    return '📦';
  }

  private _getGroupColor(groupName: string): string {
    // Colors for personas
    const personaColors: Record<string, string> = {
      'developer': 'cyan',
      'devops': 'green',
      'incident': 'red',
      'release': 'purple'
    };

    if (personaColors[groupName.toLowerCase()]) {
      return personaColors[groupName.toLowerCase()];
    }

    // Default color for projects
    if (groupName === 'No Project') return 'gray';
    return 'blue';
  }

  private _renderWorkspaceCard(uri: string, ws: WorkspaceState): string {
    const project = ws.project || "No project";
    const shortUri = uri.replace("file://", "").split("/").slice(-2).join("/");
    const isAutoDetected = ws.is_auto_detected ? " (auto)" : "";
    const lastActivity = ws.last_activity ? this._formatRelativeTime(ws.last_activity) : "Unknown";
    const sessionCount = Object.keys(ws.sessions || {}).length;

    // Render sessions within this workspace
    const sessionsHtml = this._renderWorkspaceSessions(ws);

    return `
      <div class="workspace-card" data-workspace-uri="${uri}">
        <div class="workspace-header">
          <div class="workspace-icon cyan">📁</div>
          <div class="workspace-info">
            <div class="workspace-project">${project}${isAutoDetected}</div>
            <div class="workspace-uri" title="${uri}">${shortUri}</div>
          </div>
          <div class="workspace-badge">${sessionCount} session${sessionCount !== 1 ? 's' : ''}</div>
        </div>
        <div class="workspace-body">
          <div class="workspace-row">
            <span class="workspace-label">Last Active</span>
            <span class="workspace-value">${lastActivity}</span>
          </div>
          ${sessionsHtml}
        </div>
        <div class="workspace-footer">
          <button class="btn btn-ghost btn-small" data-action="removeWorkspace" data-uri="${uri}">
            🗑️ Remove Workspace
          </button>
        </div>
      </div>
    `;
  }

  private _renderWorkspaceSessions(ws: WorkspaceState): string {
    const sessions = ws.sessions || {};
    const sessionEntries = Object.entries(sessions);

    if (sessionEntries.length === 0) {
      return `<div class="no-sessions">No active sessions. Run session_start() in a chat.</div>`;
    }

    // Sort by last_activity, most recent first
    sessionEntries.sort((a, b) => {
      const aTime = a[1].last_activity ? new Date(a[1].last_activity).getTime() : 0;
      const bTime = b[1].last_activity ? new Date(b[1].last_activity).getTime() : 0;
      return bTime - aTime;
    });

    return `
      <div class="sessions-container">
        <div class="sessions-header">💬 Chat Sessions</div>
        ${sessionEntries.map(([sid, session]) => this._renderSessionCard(sid, session, ws.active_session_id === sid)).join("")}
      </div>
    `;
  }

  private _renderSessionCard(sessionId: string, session: ChatSession, isActive: boolean): string {
    const persona = session.persona || "developer";
    const personaIcon = this._getPersonaIcon(persona);
    const personaColor = this._getPersonaColor(persona);
    // Dual tool count: show dynamic (filtered) if available, else static (baseline)
    // If no tool count stored, calculate from persona's tool modules
    const isDynamic = (session.dynamic_tool_count ?? 0) > 0;
    let toolCount = session.tool_count ?? session.static_tool_count ?? session.active_tools?.length ?? 0;
    if (toolCount === 0) {
      // Fallback: calculate from persona's tool modules
      toolCount = this.getToolCountForPersona(persona);
    }
    const toolLabel = isDynamic ? `${toolCount} (filtered)` : `${toolCount} available`;
    const lastActivity = session.last_activity ? this._formatRelativeTime(session.last_activity) : "Unknown";
    const sessionName = session.name || `Session ${sessionId.substring(0, 6)}`;
    const activeClass = isActive ? "session-active" : "";

    // Per-session project support
    const sessionProject = (session as any).project || null;
    const isProjectAutoDetected = (session as any).is_project_auto_detected || false;
    const projectSuffix = isProjectAutoDetected ? " (auto)" : "";

    // Format last tool info
    const lastTool = session.last_tool || null;
    const lastToolTime = session.last_tool_time ? this._formatRelativeTime(session.last_tool_time) : null;
    const toolCallCount = session.tool_call_count || 0;

    // Get skills for this persona
    const skills = this.getSkillsForPersona(persona);
    const skillsLabel = skills.length > 0
      ? `${skills.length} available`
      : "all skills";
    const skillsPreview = skills.length > 0
      ? skills.slice(0, 3).join(", ") + (skills.length > 3 ? ` +${skills.length - 3} more` : "")
      : "";

    return `
      <div class="session-card ${activeClass}" data-session-id="${sessionId}">
        <div class="session-header clickable" data-action="openChatSession" data-session-id="${sessionId}" data-session-name="${sessionName.replace(/"/g, '&quot;')}" title="Click to find this chat session">
          <div class="session-icon ${personaColor}">${personaIcon}</div>
          <div class="session-info">
            <div class="session-name">${sessionName}</div>
          </div>
          ${isActive ? '<span class="active-badge">Active</span>' : ''}
          <span class="open-chat-hint">🔍</span>
        </div>
        <div class="session-body">
          ${sessionProject ? `
          <div class="session-row">
            <span class="session-label">Project</span>
            <span class="session-value project-badge">${sessionProject}${projectSuffix}</span>
          </div>
          ` : ""}
          <div class="session-row">
            <span class="session-label">Persona</span>
            <span class="session-value persona-badge ${personaColor}">${persona}</span>
          </div>
          ${session.issue_key ? `
          <div class="session-row">
            <span class="session-label">Issue${session.issue_key.includes(',') ? 's' : ''}</span>
            <span class="session-value issue-badges">${session.issue_key.split(', ').map((k: string) => `<a href="https://issues.redhat.com/browse/${k}" class="issue-badge issue-link" title="Open ${k} in Jira">${k}</a>`).join(' ')}</span>
          </div>
          ` : ""}
          ${session.branch ? `
          <div class="session-row">
            <span class="session-label">Branch</span>
            <span class="session-value branch-badge">${session.branch}</span>
          </div>
          ` : ""}
          <div class="session-row">
            <span class="session-label">Tools</span>
            <span class="session-value">${toolLabel}</span>
          </div>
          <div class="session-row">
            <span class="session-label">Skills</span>
            <span class="session-value" title="${skills.join(', ') || 'All skills available'}">${skillsLabel}${skillsPreview ? ` (${skillsPreview})` : ''}</span>
          </div>
          <div class="session-row">
            <span class="session-label">Last Active</span>
            <span class="session-value">${lastActivity}</span>
          </div>
          ${lastTool ? `
          <div class="session-row">
            <span class="session-label">Last Tool</span>
            <span class="session-value"><code>${lastTool}</code> ${lastToolTime ? `(${lastToolTime})` : ''}</span>
          </div>
          <div class="session-row">
            <span class="session-label">Tool Calls</span>
            <span class="session-value">${toolCallCount} total</span>
          </div>
          ` : ""}
        </div>
        <div class="session-footer">
          <button class="btn btn-ghost btn-small" data-action="copySessionId" data-session-id="${sessionId}" title="Copy session ID to clipboard">
            📋 Copy ID
          </button>
          <button class="btn btn-ghost btn-small" data-action="viewSessionTools" data-session-id="${sessionId}">
            🔧 Tools
          </button>
          ${session.meeting_references && session.meeting_references.length > 0 ? `
          <button class="btn btn-ghost btn-small meeting-notes-btn" data-action="viewMeetingNotes" data-session-id="${sessionId}" title="View meeting notes where issues were discussed">
            📝 Notes (${session.meeting_references.length})
          </button>
          ` : ''}
          <button class="btn btn-ghost btn-small" data-action="removeSession" data-session-id="${sessionId}" data-workspace-uri="${session.workspace_uri}">
            🗑️ Remove
          </button>
        </div>
      </div>
    `;
  }

  private _viewWorkspaceTools(uri: string): void {
    if (!this._workspaceState || !this._workspaceState[uri]) {
      vscode.window.showWarningMessage(`Workspace not found: ${uri}`);
      return;
    }

    const ws = this._workspaceState[uri];
    const activeSession = ws.active_session_id ? ws.sessions[ws.active_session_id] : null;
    const persona = activeSession?.persona || 'developer';
    let toolCount = activeSession?.tool_count ?? activeSession?.active_tools?.length ?? 0;
    if (toolCount === 0) {
      toolCount = this.getToolCountForPersona(persona);
    }

    // Show info about tools (we no longer store the full list)
    vscode.window.showInformationMessage(
      `${persona} persona has ${toolCount} tools loaded. Use tool_list() in chat to see them.`
    );
  }

  private async _switchToWorkspace(uri: string): Promise<void> {
    if (!this._workspaceState || !this._workspaceState[uri]) {
      vscode.window.showWarningMessage(`Workspace not found: ${uri}`);
      return;
    }

    const ws = this._workspaceState[uri];
    const folderPath = uri.replace("file://", "");

    // Check if folder exists
    if (!fs.existsSync(folderPath)) {
      vscode.window.showWarningMessage(`Folder not found: ${folderPath}`);
      return;
    }

    // Open the folder in a new window
    const folderUri = vscode.Uri.file(folderPath);
    await vscode.commands.executeCommand("vscode.openFolder", folderUri, { forceNewWindow: false });
  }

  private async _viewMeetingNotes(sessionId: string): Promise<void> {
    // Find the session across all workspaces
    let session: ChatSession | null = null;
    if (this._workspaceState) {
      for (const ws of Object.values(this._workspaceState)) {
        if (ws.sessions && ws.sessions[sessionId]) {
          session = ws.sessions[sessionId];
          break;
        }
      }
    }

    if (!session || !session.meeting_references || session.meeting_references.length === 0) {
      vscode.window.showInformationMessage('No meeting notes found for this session.');
      return;
    }

    // Build a quick pick list of meetings
    const items = session.meeting_references.map((ref: MeetingReference) => ({
      label: `📝 ${ref.title}`,
      description: ref.date,
      detail: `${ref.matches} mention${ref.matches > 1 ? 's' : ''} of session issues`,
      meetingId: ref.meeting_id,
    }));

    const selected = await vscode.window.showQuickPick(items, {
      placeHolder: `Select a meeting to view notes (${session.issue_key || 'no issues'})`,
      title: 'Meeting Notes',
    });

    if (selected) {
      // Open the meeting notes - for now, show info about how to access them
      // In the future, this could open a webview with the transcript
      const dbPath = path.join(os.homedir(), '.config', 'aa-workflow', 'meetings.db');

      if (fs.existsSync(dbPath)) {
        // Query the transcript for this meeting
        try {
          const { spawnSync } = require('child_process');
          const query = `SELECT speaker, text, timestamp FROM transcripts WHERE meeting_id = ${selected.meetingId} ORDER BY timestamp LIMIT 50`;
          // Use spawnSync to avoid shell/bashrc sourcing
          const sqlResult = spawnSync('sqlite3', ['-separator', '|||', dbPath, query], { encoding: 'utf8', timeout: 5000 });
          const result = sqlResult.stdout || '';

          if (result.trim()) {
            // Create a markdown preview of the transcript
            const lines = result.trim().split('\n');
            let markdown = `# ${selected.label.replace('📝 ', '')}\n\n**Date:** ${selected.description}\n\n## Transcript (first 50 entries)\n\n`;

            for (const line of lines) {
              const parts = line.split('|||');
              if (parts.length >= 3) {
                const [speaker, text, timestamp] = parts;
                const time = timestamp.split('T')[1]?.substring(0, 5) || '';
                markdown += `**${speaker}** (${time}): ${text}\n\n`;
              }
            }

            // Show in a new untitled document
            const doc = await vscode.workspace.openTextDocument({
              content: markdown,
              language: 'markdown'
            });
            await vscode.window.showTextDocument(doc, { preview: true });
          } else {
            vscode.window.showInformationMessage(`No transcript found for meeting: ${selected.label}`);
          }
        } catch (error: any) {
          vscode.window.showWarningMessage(`Failed to load transcript: ${error.message}`);
        }
      } else {
        vscode.window.showInformationMessage(
          `Meeting: ${selected.label}\nDate: ${selected.description}\n\nMeeting database not found at ${dbPath}`
        );
      }
    }
  }

  private async _changeWorkspacePersona(uri: string, persona: string): Promise<void> {
    if (!this._workspaceState || !this._workspaceState[uri]) {
      vscode.window.showWarningMessage(`Workspace not found: ${uri}`);
      return;
    }

    const ws = this._workspaceState[uri];
    const project = ws.project || "unknown";
    const activeSession = ws.active_session_id ? ws.sessions[ws.active_session_id] : null;
    const currentPersona = activeSession?.persona || "none";

    // Show notification that persona change was requested
    vscode.window.showInformationMessage(
      `Persona change requested for ${project}: ${currentPersona} → ${persona}. ` +
      `Use persona_load("${persona}") in the chat to apply.`
    );

    // Note: Actually changing the persona requires calling the MCP server
    // which should be done through the chat interface. This UI just shows
    // the current state and provides a hint about how to change it.
  }

  private async _copySessionId(sessionId: string): Promise<void> {
    try {
      await vscode.env.clipboard.writeText(sessionId);
      vscode.window.showInformationMessage(
        `Session ID copied: ${sessionId}. Search for this in your Cursor chat history to find the session.`
      );
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to copy session ID: ${error}`);
    }
  }

  private async _openChatSession(sessionId: string, sessionName?: string): Promise<void> {
    try {
      // Import chat utilities
      const { openChatById, getChatNameById, sendEnter, sleep } = await import('./chatUtils');

      // Get chat name from database
      const chatName = getChatNameById(sessionId) || sessionName;
      console.log(`[CommandCenter] _openChatSession called - sessionId: ${sessionId}, sessionName: ${sessionName}, resolved chatName: ${chatName}`);

      // Open Quick Open with the chat name
      const searchQuery = chatName ? `chat:${chatName}` : 'chat:';
      console.log(`[CommandCenter] Opening Quick Open with query: "${searchQuery}"`);
      await vscode.commands.executeCommand('workbench.action.quickOpen', searchQuery);

      // Wait for Quick Open to populate results (500ms is more reliable than 250ms)
      console.log(`[CommandCenter] Waiting 500ms for Quick Open to populate...`);
      await sleep(500);

      // Send Enter to select the first result
      console.log(`[CommandCenter] Sending Enter via ydotool...`);
      const enterResult = sendEnter();
      console.log(`[CommandCenter] sendEnter() returned: ${enterResult}`);

      if (!enterResult) {
        console.error(`[CommandCenter] sendEnter() failed - ydotool may not be running or socket not available`);
      }

      if (chatName) {
        console.log(`[CommandCenter] Opening chat: "${chatName}"`);
      }

    } catch (error) {
      console.error(`[CommandCenter] _openChatSession error:`, error);
      vscode.window.showErrorMessage(`Failed to open chat: ${error}`);
    }
  }

  /**
   * Search sessions via D-Bus Session Daemon
   */
  private async _searchSessions(query: string): Promise<void> {
    if (!query || query.trim().length === 0) {
      this._panel.webview.postMessage({
        type: "searchResults",
        results: [],
        query: "",
        error: null,
      });
      return;
    }

    try {
      // Call D-Bus to search chats
      const result = await dbus.session_searchChats(query, 20);

      if (result.success && result.data) {
        const data = result.data as any;
        const searchResult = typeof data === "string" ? JSON.parse(data) : data;
        this._panel.webview.postMessage({
          type: "searchResults",
          results: searchResult.results || [],
          query: query,
          totalFound: searchResult.total_found || 0,
          error: searchResult.error || null,
        });
      } else {
        // D-Bus call failed - daemon might not be running
        // Fall back to local search of session names
        this._searchSessionsLocal(query);
      }
    } catch (error) {
      debugLog(`Search via D-Bus failed: ${error}, falling back to local search`);
      this._searchSessionsLocal(query);
    }
  }

  /**
   * Local fallback search - searches session names only (no chat content)
   */
  private _searchSessionsLocal(query: string): void {
    const queryLower = query.toLowerCase();
    const results: any[] = [];

    if (this._workspaceState) {
      for (const [uri, ws] of Object.entries(this._workspaceState)) {
        const sessions = ws.sessions || {};
        for (const [sid, session] of Object.entries(sessions)) {
          const sess = session as any;
          const name = sess.name || "";
          const issueKey = sess.issue_key || "";

          if (name.toLowerCase().includes(queryLower) || issueKey.toLowerCase().includes(queryLower)) {
            results.push({
              session_id: sid,
              name: name || `Session ${sid.substring(0, 8)}`,
              project: sess.project || ws.project || "unknown",
              workspace_uri: uri,
              name_match: true,
              content_matches: [],
              match_count: 0,
              last_updated: sess.last_activity,
            });
          }
        }
      }
    }

    this._panel.webview.postMessage({
      type: "searchResults",
      results: results,
      query: query,
      totalFound: results.length,
      error: null,
      isLocalSearch: true,
    });
  }

  /**
   * Trigger immediate refresh via D-Bus Session Daemon
   */
  private async _triggerImmediateRefresh(): Promise<void> {
    try {
      const result = await dbus.session_refreshNow();

      if (result.success) {
        debugLog("Triggered immediate refresh via D-Bus");
        // The daemon will update its state, and the next D-Bus poll will pick it up
      } else {
        // Daemon not running, fall back to direct sync
        debugLog("D-Bus refresh failed, falling back to direct sync");
        await this._syncAndRefreshSessions();
      }
    } catch (error) {
      debugLog(`D-Bus refresh failed: ${error}, falling back to direct sync`);
      await this._syncAndRefreshSessions();
    }
  }

  /**
   * Run a skill in a new chat session
   * Creates a new chat, sends the skill_run command, and auto-submits
   */
  private async _runSkillInNewChat(skillName: string): Promise<void> {
    try {
      const { createNewChat } = await import('./chatUtils');

      // Build the skill command
      const command = `skill_run("${skillName}")`;

      // Create a new chat with the skill command
      // Title will be the skill name for easy identification
      const skillLabel = skillName
        .split("_")
        .map((word: string) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");

      logger.log(`Running skill "${skillName}" in new chat`);

      const chatId = await createNewChat({
        message: command,
        title: `Skill: ${skillLabel}`,
        autoSubmit: true,
        delay: 150,
      });

      if (chatId) {
        logger.log(`Created new chat ${chatId} for skill ${skillName}`);
      } else {
        // Fallback: copy to clipboard
        await vscode.env.clipboard.writeText(command);
        vscode.window.showInformationMessage(
          `Skill command copied to clipboard. Paste in a new chat to run: ${command}`
        );
      }
    } catch (error) {
      logger.log(`Failed to run skill in new chat: ${error}`);
      // Fallback: use the existing runSkillByName command
      vscode.commands.executeCommand("aa-workflow.runSkillByName", skillName);
    }
  }

  /**
   * Remove a workspace from tracking via D-Bus.
   *
   * ARCHITECTURE: State modifications go through D-Bus to the daemon.
   * The session daemon owns the workspace state.
   */
  private async _removeWorkspace(uri: string): Promise<void> {
    if (!this._workspaceState || !this._workspaceState[uri]) {
      vscode.window.showWarningMessage(`Workspace not found: ${uri}`);
      return;
    }

    const ws = this._workspaceState[uri];
    const project = ws.project || uri;

    // Confirm removal
    const result = await vscode.window.showWarningMessage(
      `Remove workspace "${project}" from tracking?`,
      { modal: true },
      "Remove"
    );

    if (result === "Remove") {
      try {
        // Remove via D-Bus - session daemon owns the state
        const dbusResult = await dbus.session_removeWorkspace(uri);

        const data = dbusResult.data as any;
        if (dbusResult.success && data?.success) {
          // Update local state from D-Bus response
          delete this._workspaceState[uri];
          this._workspaceCount = Object.keys(this._workspaceState).length;
          vscode.window.showInformationMessage(`Removed workspace: ${project}`);
        } else {
          const errorMsg = data?.error || dbusResult.error || "Unknown error";
          vscode.window.showErrorMessage(`Failed to remove workspace: ${errorMsg}`);
        }
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to remove workspace: ${error}`);
      }

      // Update UI
      this._updateWorkspacesTab();
      this.update(false);
    }
  }

  private async loadPersona(personaName: string) {
    try {
      const { createNewChat } = await import("./chatUtils");
      const command = `agent_load("${personaName}")`;

      // Use createNewChat which handles clipboard, paste, and ydotool Enter
      const chatId = await createNewChat({
        message: command,
        title: `${personaName} persona`,
        autoSubmit: true,  // Will send Enter via ydotool
      });

      if (chatId) {
        vscode.window.showInformationMessage(`🚀 Loading ${personaName} persona...`);
      } else {
        // Fallback: copy to clipboard
        await vscode.env.clipboard.writeText(command);
        vscode.window.showInformationMessage(
          `📋 Copied to clipboard: ${command} - Open a new chat and paste to load the persona.`
        );
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to load persona: ${e}`);
    }
  }

  private async openPersonaFile(personaName: string) {
    try {
      const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
        path.join(os.homedir(), "src", "redhat-ai-workflow");
      const personaFile = path.join(workspaceRoot, "personas", `${personaName}.yaml`);

      if (fs.existsSync(personaFile)) {
        const doc = await vscode.workspace.openTextDocument(personaFile);
        await vscode.window.showTextDocument(doc);
      } else {
        vscode.window.showErrorMessage(`Persona file not found: ${personaFile}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to open persona file: ${e}`);
    }
  }

  private getActiveAgent(): { name: string; tools: string[] } {
    // Return cached value synchronously - use getActiveAgentAsync for fresh data
    return this._activeAgentCache || { name: "developer", tools: [] };
  }

  private _activeAgentCache: { name: string; tools: string[] } | null = null;

  private async getActiveAgentAsync(): Promise<{ name: string; tools: string[] }> {
    try {
      // Get active agent from memory via D-Bus
      const workResult = await dbus.memory_getCurrentWork();
      let agentName = "developer"; // Default

      if (workResult.success && workResult.data) {
        const work = (workResult.data as any).work || workResult.data;
        agentName = work?.active_agent || work?.persona || "developer";
      }

      // Get persona tools via D-Bus
      const personaResult = await dbus.config_getPersonaDefinition(agentName);
      if (personaResult.success && personaResult.data) {
        const persona = (personaResult.data as any).persona || personaResult.data;
        const tools = persona?.tools || [];
        this._activeAgentCache = { name: agentName, tools };
        return this._activeAgentCache;
      }

      this._activeAgentCache = { name: agentName, tools: [] };
      return this._activeAgentCache;
    } catch (e) {
      return { name: "unknown", tools: [] };
    }
  }

  // ============================================================================
  // Update / Render
  // ============================================================================

  public async update(forceFullRender: boolean = false) {
    // Use modular HTML generation
    debugLog(`update() called, forceFullRender: ${forceFullRender}`);
    try {
      await this.updateModular(forceFullRender);
      debugLog("update() completed successfully");
    } catch (err) {
      debugLog(`update() failed: ${err}`);
    }
  }

  /**
   * Update using the modular HTML generator.
   * This is the new, cleaner approach that uses external CSS/JS files and tab classes.
   * Call this instead of update() to use the modular system.
   */
  public async updateModular(forceFullRender: boolean = false) {
    debugLog("updateModular() starting...");

    // Load stats via D-Bus
    debugLog("Loading stats...");
    const stats = await this.loadStatsAsync();
    debugLog(`Stats loaded: ${stats ? "yes" : "no"}`);

    // On first render or forced, do full HTML render using modular generator
    if (forceFullRender || !this._panel.webview.html) {
      debugLog(`Generating full HTML (forceFullRender: ${forceFullRender}, hasHtml: ${!!this._panel.webview.html})`);
      try {
        const html = await this._getHtmlForWebviewModular(stats);
        debugLog(`Got HTML from generator, length: ${html?.length ?? 'undefined'}`);
        if (html && html.length > 0) {
          this._panel.webview.html = html;
          debugLog(`Webview HTML set successfully, verified length: ${this._panel.webview.html?.length ?? 'undefined'}`);
        } else {
          debugLog(`ERROR: HTML is empty or undefined!`);
        }
      } catch (err) {
        debugLog(`ERROR generating HTML: ${err}`);
      }
    } else {
      // For subsequent updates, refresh the active tab's data and send update
      await this._tabManager.loadActiveTabData();

      // Send data update to webview
      const lifetime = stats?.lifetime || { tool_calls: 0, skill_executions: 0, sessions: 0 };
      this._panel.webview.postMessage({
        type: "dataUpdate",
        stats: {
          toolCalls: lifetime.tool_calls,
          skillExecutions: lifetime.skill_executions,
          sessions: lifetime.sessions,
        },
        badges: this._tabManager.getAllBadges(),
      });
    }
  }

  private _formatNumber(num: number): string {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  }

  /**
   * Generate HTML using the modular HtmlGenerator approach.
   * This is a simplified alternative to _getHtmlForWebview that uses
   * external CSS/JS files and tab classes for content generation.
   */
  private async _getHtmlForWebviewModular(stats: AgentStats | null): Promise<string> {
    if (!this._htmlGenerator) {
      debugLog("ERROR: HtmlGenerator not initialized!");
      return "<html><body>Error: HtmlGenerator not initialized</body></html>";
    }

    // Load data for all tabs
    debugLog("Loading data for all tabs...");
    try {
      await this._tabManager.loadAllData();
      debugLog("Tab data loaded successfully");
    } catch (err) {
      debugLog(`Error loading tab data: ${err}`);
    }

    // Get header stats from the stats object
    const lifetime = stats?.lifetime || {
      tool_calls: 0,
      skill_executions: 0,
      sessions: 0,
    };

    debugLog(`Generating HTML with stats: tool_calls=${lifetime.tool_calls}, skill_executions=${lifetime.skill_executions}, sessions=${lifetime.sessions}`);
    const html = this._htmlGenerator.generateHtml({
      toolCalls: lifetime.tool_calls,
      skillExecutions: lifetime.skill_executions,
      sessions: lifetime.sessions ?? 0,
    });

    debugLog(`Generated HTML length: ${html.length}`);
    if (html.length < 1000) {
      debugLog(`WARNING: HTML seems too short! Content: ${html.substring(0, 500)}`);
    }

    return html;
  }

  private _formatTime(timestamp: string | undefined): string {
    if (!timestamp) return "Unknown";
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "Unknown";
    }
  }

  private _getSkillIcon(skillName: string): string {
    // Map skill names to appropriate icons
    const iconMap: Record<string, string> = {
      // Daily routines
      coffee: "☕",
      beer: "🍺",
      standup: "📋",

      // Git/PR workflows
      start_work: "🚀",
      create_mr: "📝",
      check_my_prs: "🔀",
      check_mr_feedback: "💬",
      close_mr: "✅",
      close_issue: "✔️",

      // CI/CD
      check_ci_health: "🔧",
      ci_retry: "🔄",
      cancel_pipeline: "⏹️",
      check_integration_tests: "🧪",

      // Deployment
      deploy_ephemeral: "🚀",
      test_mr_ephemeral: "🧪",
      release_namespace: "🗑️",

      // Jira
      create_jira_issue: "📋",
      clone_jira_issue: "📑",

      // Monitoring/Alerts
      investigate_alert: "🔍",
      check_alerts: "🚨",

      // Cleanup/Maintenance
      cleanup_branches: "🧹",
      check_secrets: "🔐",

      // Knowledge/Memory
      bootstrap_knowledge: "📚",
      add_project: "➕",

      // App Interface
      appinterface_check: "🔌",
    };

    // Check for exact match
    if (iconMap[skillName]) {
      return iconMap[skillName];
    }

    // Check for partial matches
    const name = skillName.toLowerCase();
    if (name.includes("deploy") || name.includes("release")) return "🚀";
    if (name.includes("test") || name.includes("check")) return "🧪";
    if (name.includes("mr") || name.includes("pr")) return "🔀";
    if (name.includes("jira") || name.includes("issue")) return "📋";
    if (name.includes("alert") || name.includes("incident")) return "🚨";
    if (name.includes("cleanup") || name.includes("clean")) return "🧹";
    if (name.includes("ci") || name.includes("pipeline")) return "🔧";
    if (name.includes("git") || name.includes("branch")) return "🌿";
    if (name.includes("secret") || name.includes("auth")) return "🔐";
    if (name.includes("knowledge") || name.includes("learn")) return "📚";

    // Default icon
    return "⚡";
  }
}

// ============================================================================
// Registration
// ============================================================================

let commandCenterPanel: CommandCenterPanel | undefined;

export function getCommandCenterPanel(): CommandCenterPanel | undefined {
  // Return the static panel if it exists (handles both command-opened and revived panels)
  // The module-level variable may be undefined if the panel was revived from a previous session
  return commandCenterPanel ?? CommandCenterPanel.currentPanel;
}

export function registerCommandCenter(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider
) {
  // Register command to open Command Center
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openCommandCenter", (initialTab?: string) => {
      commandCenterPanel = CommandCenterPanel.createOrShow(
        context.extensionUri,
        dataProvider,
        initialTab
      );
    })
  );

  // Convenience commands for specific tabs
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openSkillsTab", () => {
      commandCenterPanel = CommandCenterPanel.createOrShow(
        context.extensionUri,
        dataProvider,
        "skills"
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openServicesTab", () => {
      commandCenterPanel = CommandCenterPanel.createOrShow(
        context.extensionUri,
        dataProvider,
        "services"
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openMemoryTab", () => {
      commandCenterPanel = CommandCenterPanel.createOrShow(
        context.extensionUri,
        dataProvider,
        "memory"
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openCronTab", () => {
      commandCenterPanel = CommandCenterPanel.createOrShow(
        context.extensionUri,
        dataProvider,
        "cron"
      );
    })
  );

}

/**
 * Register the Command Center serializer early in activation.
 * This MUST be called before any other initialization to ensure VS Code
 * can restore panels properly after a restart.
 */
export function registerCommandCenterSerializer(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider
) {
  debugLog("registerCommandCenterSerializer() - registering serializer early...");
  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer("aaCommandCenter", {
      async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel, _state: any) {
        debugLog("Serializer deserializeWebviewPanel called - reviving panel");
        CommandCenterPanel.revive(webviewPanel, context.extensionUri, dataProvider);
        debugLog("Serializer deserializeWebviewPanel - revive complete");
      }
    })
  );
  debugLog("registerCommandCenterSerializer() - serializer registered");
}

/**
 * Check if there's a Command Center panel that needs reconnection.
 * This handles the case where VS Code restored a panel before our serializer was ready.
 */
export function ensureCommandCenterConnected(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider
) {
  debugLog("ensureCommandCenterConnected() called");
  // If we already have a currentPanel, we're good
  if (CommandCenterPanel.currentPanel) {
    debugLog("ensureCommandCenterConnected() - panel already connected");
    return;
  }

  // Check if there's a visible Command Center panel that we need to reconnect to
  // Unfortunately VS Code doesn't provide a way to enumerate existing webview panels,
  // so we can't directly reconnect. The best we can do is ensure the serializer is
  // registered and hope VS Code calls it.
  debugLog("ensureCommandCenterConnected() - no panel connected, serializer should handle restoration");
}
