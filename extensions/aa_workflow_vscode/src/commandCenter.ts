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
import { loadMeetBotState, getMeetingsTabStyles, getMeetingsTabContent, getMeetingsTabScript, getUpcomingMeetingsHtml, MeetBotState } from "./meetingsTab";
import { loadSprintState, loadSprintHistory, loadToolGapRequests, getSprintTabContent, getSprintTabScript, SprintState } from "./sprintTab";
import { loadActiveLoops, getCreateSessionTabContent, getCreateSessionTabScript, getCreateSessionTabStyles } from "./createSessionTab";
import { loadPerformanceState, getPerformanceTabContent, PerformanceState } from "./performanceTab";
import { createLogger } from "./logger";
import { RefreshCoordinator, RefreshPriority, StateSection } from "./refreshCoordinator";

const logger = createLogger("CommandCenter");

/**
 * Execute a command using spawn with bash --norc --noprofile to avoid sourcing
 * .bashrc.d scripts (which can trigger Bitwarden password prompts).
 *
 * This replaces exec() which spawns an interactive shell by default.
 */
async function execAsync(command: string, options?: { timeout?: number; cwd?: string }): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    // Use bash with --norc --noprofile to prevent sourcing any startup files
    // -c tells bash to execute the following command string
    const proc = spawn('/bin/bash', ['--norc', '--noprofile', '-c', command], {
      cwd: options?.cwd,
      env: {
        ...process.env,
        // Extra safety: clear env vars that could trigger rc file sourcing
        BASH_ENV: '',
        ENV: '',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    let killed = false;

    // Handle timeout
    const timeout = options?.timeout || 30000;
    const timer = setTimeout(() => {
      killed = true;
      proc.kill('SIGTERM');
      reject(new Error(`Command timed out after ${timeout}ms`));
    }, timeout);

    proc.stdout.on('data', (data) => { stdout += data.toString(); });
    proc.stderr.on('data', (data) => { stderr += data.toString(); });

    proc.on('close', (code) => {
      clearTimeout(timer);
      if (killed) return;

      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        const error = new Error(`Command failed with exit code ${code}: ${stderr}`);
        (error as any).code = code;
        (error as any).stdout = stdout;
        (error as any).stderr = stderr;
        reject(error);
      }
    });

    proc.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

// Debug output channel - logs to output channel without auto-showing
let debugChannel: vscode.OutputChannel | undefined;
function debugLog(msg: string) {
  if (!debugChannel) {
    debugChannel = vscode.window.createOutputChannel("CommandCenter Debug");
  }
  const timestamp = new Date().toISOString().substr(11, 12);
  debugChannel.appendLine(`[${timestamp}] ${msg}`);
  // Don't auto-show - user can open "CommandCenter Debug" output channel manually if needed
  // debugChannel.show(true);
}

// ============================================================================
// Constants
// ============================================================================

const STATS_FILE = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "agent_stats.json"
);

const EXECUTION_FILE = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "skill_execution.json"
);

const CONFIG_FILE = path.join(
  os.homedir(),
  "src",
  "redhat-ai-workflow",
  "config.json"
);

const CRON_HISTORY_FILE = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "cron_history.json"
);

// Centralized state directory
const AA_CONFIG_DIR = path.join(os.homedir(), ".config", "aa-workflow");

// Per-service state files (each service writes its own file)
const SESSION_STATE_FILE = path.join(AA_CONFIG_DIR, "session_state.json");
const SPRINT_STATE_FILE = path.join(AA_CONFIG_DIR, "sprint_state_v2.json");
const MEET_STATE_FILE = path.join(AA_CONFIG_DIR, "meet_state.json");
const CRON_STATE_FILE = path.join(AA_CONFIG_DIR, "cron_state.json");

// Legacy unified state file (for backward compatibility during migration)
const WORKSPACE_STATES_FILE = path.join(AA_CONFIG_DIR, "workspace_states.json");

const DBUS_SERVICES = [
  {
    name: "Slack Agent",
    service: "com.aiworkflow.BotSlack",
    path: "/com/aiworkflow/BotSlack",
    interface: "com.aiworkflow.BotSlack",
    icon: "💬",
    systemdUnit: "bot-slack.service",
    methods: [
      { name: "GetStatus", description: "Get daemon status and stats", args: [] },
      { name: "GetPending", description: "Get pending approval messages", args: [] },
      { name: "GetHistory", description: "Get message history", args: [
        { name: "limit", type: "int32", default: "10" },
        { name: "channel_id", type: "string", default: "" },
        { name: "user_id", type: "string", default: "" },
        { name: "status", type: "string", default: "" },
      ]},
      { name: "ApproveAll", description: "Approve all pending messages", args: [] },
      { name: "ReloadConfig", description: "Reload daemon configuration", args: [] },
      { name: "Shutdown", description: "Gracefully shutdown the daemon", args: [] },
    ],
  },
  {
    name: "Cron Scheduler",
    service: "com.aiworkflow.BotCron",
    path: "/com/aiworkflow/BotCron",
    interface: "com.aiworkflow.BotCron",
    icon: "🕐",
    systemdUnit: "bot-cron.service",
    methods: [
      { name: "GetStatus", description: "Get scheduler status and stats", args: [] },
      { name: "GetStats", description: "Get scheduler statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "list_jobs" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the scheduler", args: [] },
    ],
  },
  {
    name: "Meet Bot",
    service: "com.aiworkflow.BotMeet",
    path: "/com/aiworkflow/BotMeet",
    interface: "com.aiworkflow.BotMeet",
    icon: "🎥",
    systemdUnit: "bot-meet.service",
    methods: [
      { name: "GetStatus", description: "Get bot status and upcoming meetings", args: [] },
      { name: "GetStats", description: "Get bot statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "list_meetings" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
  {
    name: "Sprint Bot",
    service: "com.aiworkflow.BotSprint",
    path: "/com/aiworkflow/BotSprint",
    interface: "com.aiworkflow.BotSprint",
    icon: "🏃",
    systemdUnit: "bot-sprint.service",
    methods: [
      { name: "GetStatus", description: "Get bot status and sprint info", args: [] },
      { name: "GetStats", description: "Get bot statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "list_issues" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
  {
    name: "Session Manager",
    service: "com.aiworkflow.BotSession",
    path: "/com/aiworkflow/BotSession",
    interface: "com.aiworkflow.BotSession",
    icon: "💬",
    systemdUnit: "bot-session.service",
    methods: [
      { name: "GetStatus", description: "Get session manager status", args: [] },
      { name: "GetStats", description: "Get session statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_sessions" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the manager", args: [] },
    ],
  },
  {
    name: "Video Bot",
    service: "com.aiworkflow.BotVideo",
    path: "/com/aiworkflow/BotVideo",
    interface: "com.aiworkflow.BotVideo",
    icon: "📹",
    systemdUnit: "bot-video.service",
    methods: [
      { name: "GetStatus", description: "Get video bot status", args: [] },
      { name: "GetStats", description: "Get video statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_render_stats" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
];

// ============================================================================
// Types
// ============================================================================

interface MeetingReference {
  meeting_id: number;
  title: string;
  date: string;
  matches: number;
}

interface ChatSession {
  session_id: string;
  workspace_uri: string;
  persona: string;
  project: string | null;  // Per-session project (can differ from workspace)
  is_project_auto_detected: boolean;  // Whether project was auto-detected
  issue_key: string | null;
  branch: string | null;
  // Dual tool count system
  static_tool_count?: number;  // Baseline from persona YAML (all tools available)
  dynamic_tool_count?: number;  // Context-aware from NPU filter (tools for current message)
  tool_count?: number;  // Computed: dynamic > 0 ? dynamic : static (for display)
  last_filter_message?: string | null;  // Message that triggered last NPU filter
  last_filter_time?: string | null;  // When last NPU filter was run
  // Deprecated
  active_tools?: string[];  // Deprecated: old format, use tool_count
  // Timestamps
  started_at: string | null;
  last_activity: string | null;
  name: string | null;
  last_tool: string | null;
  last_tool_time: string | null;
  tool_call_count: number;
  meeting_references?: MeetingReference[];  // Meetings where session's issues were discussed
  is_active?: boolean;      // Added when flattened
}

interface WorkspaceState {
  workspace_uri: string;
  project: string | null;
  is_auto_detected: boolean;
  active_session_id: string | null;
  sessions: { [sessionId: string]: ChatSession };
  created_at: string | null;
  last_activity: string | null;
}

interface WorkspaceExportedState {
  [workspaceUri: string]: WorkspaceState;
}

interface AgentStats {
  lifetime: {
    tool_calls: number;
    tool_successes: number;
    tool_failures: number;
    skill_executions: number;
    skill_successes: number;
    skill_failures: number;
    memory_reads: number;
    memory_writes: number;
    lines_written: number;
    sessions: number;
  };
  daily: Record<string, any>;
  tools: Record<string, any>;
  skills: Record<string, any>;
  current_session: {
    started: string;
    tool_calls: number;
    skill_executions: number;
    memory_ops: number;
  };
  created?: string;
  last_updated?: string;
}

interface SkillStep {
  name: string;
  description?: string;
  tool?: string;
  compute?: string;
  condition?: string;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  duration?: number;
  result?: string;
  error?: string;
}

interface SkillExecution {
  executionId?: string;
  skillName: string;
  status: "idle" | "running" | "success" | "failed";
  currentStepIndex: number;
  totalSteps: number;
  steps: SkillStep[];
  startTime?: string;
  endTime?: string;
  source?: string;  // "chat", "cron", "slack", "api"
  sourceDetails?: string;
  sessionName?: string;
}

// Summary of a running skill for the Running Skills panel
interface RunningSkillSummary {
  executionId: string;
  skillName: string;
  source: string;
  sourceDetails?: string;
  sessionName?: string;
  status: "running" | "success" | "failed";
  currentStepIndex: number;
  totalSteps: number;
  startTime: string;
  elapsedMs: number;
}

interface SkillDefinition {
  name: string;
  description: string;
  category?: string;
  inputs?: Array<{ name: string; type: string; required: boolean; description?: string }>;
  steps?: Array<{ name: string; description?: string; tool?: string; compute?: string }>;
}

interface CronJob {
  name: string;
  description?: string;
  skill: string;
  cron?: string;
  trigger?: string;
  poll_interval?: string;
  condition?: string;
  inputs?: Record<string, any>;
  notify?: string[];
  enabled: boolean;
  persona?: string;
}

interface CronExecution {
  job_name: string;
  skill: string;
  timestamp: string;
  success: boolean;
  duration_ms?: number;
  error?: string;
  output_preview?: string;
  session_name?: string;
}

interface ToolModule {
  name: string;
  displayName: string;
  description: string;
  toolCount: number;
  tools: ToolDefinition[];
}

interface ToolDefinition {
  name: string;
  description: string;
  module: string;
}

interface Persona {
  name: string;
  fileName?: string;  // The actual filename (e.g., "developer-slim")
  description: string;
  tools: string[];      // Tool module names (e.g., ["workflow", "git_basic"])
  toolCount: number;    // Actual count of tools across all modules
  skills: string[];
  personaFile?: string;
  isSlim?: boolean;    // Is this a slim variant?
  isInternal?: boolean; // Is this an internal config (core, universal)?
  isAgent?: boolean;   // Is this an autonomous agent (slack)?
}

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

  // Unified state from workspace_states.json (v3)
  private _services: Record<string, any> = {};
  private _ollama: Record<string, any> = {};
  private _cronData: any = {};
  private _slackChannels: string[] = [];
  private _sprintIssues: any[] = [];
  private _sprintIssuesUpdated: string = "";
  private _meetData: any = {};

  // Unified refresh coordinator - handles all UI updates with debouncing and change detection
  private _refreshCoordinator: RefreshCoordinator | null = null;

  // Debounce timer for workspace watcher
  private _workspaceWatcherDebounce: NodeJS.Timeout | null = null;

  public static createOrShow(
    extensionUri: vscode.Uri,
    dataProvider: WorkflowDataProvider,
    initialTab?: string
  ) {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (CommandCenterPanel.currentPanel) {
      CommandCenterPanel.currentPanel._panel.reveal(column);
      if (initialTab) {
        CommandCenterPanel.currentPanel.switchTab(initialTab);
      }
      return CommandCenterPanel.currentPanel;
    }

    // Allow access to screenshot directory for meeting images
    const homeDir = process.env.HOME || process.env.USERPROFILE || '';
    const screenshotDir = vscode.Uri.file(`${homeDir}/.config/aa-workflow/meet_bot/screenshots`);

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

    CommandCenterPanel.currentPanel = new CommandCenterPanel(
      panel,
      extensionUri,
      dataProvider,
      initialTab
    );

    return CommandCenterPanel.currentPanel;
  }

  public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri, dataProvider: WorkflowDataProvider) {
    console.log("[CommandCenter] revive() called - restoring panel from VS Code");
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
    this._panel.webview.postMessage({
      command: "skillExecutionUpdate",
      execution,
    });
    // NOTE: Auto-switch to skills tab removed - now using toast notifications instead
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

    this._panel.webview.postMessage({
      command: "runningSkillsUpdate",
      runningSkills,
      staleCount,
    });
  }

  private constructor(
    panel: vscode.WebviewPanel,
    extensionUri: vscode.Uri,
    dataProvider: WorkflowDataProvider,
    initialTab?: string
  ) {
    debugLog("Constructor called - setting up panel");
    this._panel = panel;
    this._extensionUri = extensionUri;
    this._dataProvider = dataProvider;
    this._currentTab = initialTab || "overview";

    // Initialize the unified refresh coordinator
    this._refreshCoordinator = new RefreshCoordinator(panel);

    // CRITICAL: Set up message handler FIRST, before any HTML is set
    // This ensures we don't miss any messages from the webview
    debugLog("Setting up onDidReceiveMessage handler FIRST");
    this._panel.webview.onDidReceiveMessage(
      async (message) => {
        // Support both 'command' and 'type' message formats
        const msgType = message.command || message.type;
        debugLog(`Received message: ${msgType} - ${JSON.stringify(message)}`);
        switch (msgType) {
          case "ping":
            // Respond to ping to confirm extension is connected
            this._panel.webview.postMessage({ command: "pong" });
            break;
          case "refresh":
            // Sync with Cursor DB and refresh UI (same as refreshWorkspaces)
            await this._syncAndRefreshSessions();
            break;
          case "refreshWorkspaces":
            await this._syncAndRefreshSessions();
            break;
          case "changeSessionGroupBy":
            this._sessionGroupBy = message.value as 'none' | 'project' | 'persona';
            this._updateWorkspacesTab();
            break;
          case "changeSessionViewMode":
            this._sessionViewMode = message.value as 'card' | 'table';
            this._updateWorkspacesTab();
            break;
          case "changePersonaViewMode":
            this._personaViewMode = message.value as 'card' | 'table';
            // Full update needed since personas tab content changes significantly
            this.update(true);
            break;
          case "viewWorkspaceTools":
            this._viewWorkspaceTools(message.uri);
            break;
          case "switchToWorkspace":
            this._switchToWorkspace(message.uri);
            break;
          case "changeWorkspacePersona":
            this._changeWorkspacePersona(message.uri, message.persona);
            break;
          case "removeWorkspace":
            this._removeWorkspace(message.uri);
            break;
          case "copySessionId":
            await this._copySessionId(message.sessionId);
            break;
          case "openChatSession":
            console.log('[AA-WORKFLOW] openChatSession message received:', message.sessionId, message.sessionName);
            await this._openChatSession(message.sessionId, message.sessionName);
            break;
          case "searchSessions":
            await this._searchSessions(message.query);
            break;
          case "refreshSessionsNow":
            // Trigger immediate refresh via D-Bus
            await this._triggerImmediateRefresh();
            break;
          case "viewMeetingNotes":
            await this._viewMeetingNotes(message.sessionId);
            break;
          case "switchTab":
            this._currentTab = message.tab;
            logger.log(`Switched to tab: ${message.tab}`);
            // Load sprint data from file when switching to sprint tab
            // NOTE: Don't trigger full sync here - it takes too long and causes race conditions
            // Full sync happens on explicit refresh or periodically via cron
            if (message.tab === "sprint") {
              logger.log("Sprint tab selected - loading from file (no sync)");
              this._loadSprintFromFile();
            }
            break;
          case "openJira":
            vscode.commands.executeCommand("aa-workflow.openJira");
            break;
          case "openMR":
            vscode.commands.executeCommand("aa-workflow.openMR");
            break;
          case "runSkill":
            if (message.skillName) {
              // Run specific skill in a new chat
              await this._runSkillInNewChat(message.skillName);
            } else {
              // Open skill picker
              vscode.commands.executeCommand("aa-workflow.runSkill");
            }
            break;
          case "switchAgent":
            vscode.commands.executeCommand("aa-workflow.switchAgent");
            break;
          case "startWork":
            vscode.commands.executeCommand("aa-workflow.startWork");
            break;
          case "coffee":
            vscode.commands.executeCommand("aa-workflow.coffee");
            break;
          case "beer":
            vscode.commands.executeCommand("aa-workflow.beer");
            break;
          case "queryDBus":
            await this.handleDBusQuery(message.service, message.method, message.args);
            break;
          case "refreshServices":
            // Handled by unified background sync - trigger manual sync
            this._backgroundSync();
            break;
          case "serviceControl":
            await this.handleServiceControl(message.action, message.service);
            break;
          case "loadSlackHistory":
            await this.loadSlackHistory();
            break;
          case "sendSlackMessage":
            await this.sendSlackMessage(message.channel, message.text, message.threadTs || "");
            break;
          case "replyToSlackThread":
            await this.sendSlackMessage(message.channel, message.text, message.threadTs);
            break;
          case "refreshSlackChannels":
            // Handled by unified background sync - trigger manual sync
            this._backgroundSync();
            break;
          case "searchSlackUsers":
            await this.searchSlackUsers(message.query);
            break;
          case "refreshSlackTargets":
            await this.refreshSlackTargets();
            break;
          case "searchSlackMessages":
            await this.searchSlackMessages(message.query);
            break;
          case "refreshSlackPending":
            await this.refreshSlackPending();
            break;
          case "approveSlackMessage":
            await this.approveSlackMessage(message.messageId);
            break;
          case "rejectSlackMessage":
            await this.rejectSlackMessage(message.messageId);
            break;
          case "approveAllSlack":
            await this.approveAllSlackMessages();
            break;
          case "refreshSlackCache":
            await this.refreshSlackCache();
            break;
          case "refreshSlackCacheStats":
            await this.refreshSlackCacheStats();
            break;
          case "loadSlackChannelBrowser":
            await this.loadSlackChannelBrowser(message.query || "");
            break;
          case "loadSlackUserBrowser":
            await this.loadSlackUserBrowser(message.query || "");
            break;
          case "loadSlackCommands":
            await this.loadSlackCommands();
            break;
          case "sendSlackCommand":
            await this.sendSlackCommand(message.commandName, message.args);
            break;
          case "loadSlackConfig":
            await this.loadSlackConfig();
            break;
          case "setSlackDebugMode":
            await this.setSlackDebugMode(message.enabled);
            break;
          case "loadSkill":
            await this.loadSkillDefinition(message.skillName);
            break;
          case "openSkillFile":
            await this.openSkillFile(message.skillName);
            break;
          case "selectRunningSkill":
            // User clicked on a running skill to view it
            this._selectRunningSkill(message.executionId);
            break;
          case "clearStaleSkills":
            // User clicked "Clear Stale" button
            this._clearStaleSkills();
            break;
          case "clearSkillExecution":
            // User clicked clear button on a specific skill
            this._clearSkillExecution(message.executionId);
            break;
          case "openSkillFlowchart":
            console.log("[CommandCenter] Received openSkillFlowchart message:", message);
            // Send acknowledgment back to webview so we can see in webview console
            this._panel.webview.postMessage({
              command: "debug",
              message: `Extension received openSkillFlowchart for: ${message.skillName}`
            });
            await this.openSkillFlowchart(message.skillName);
            break;
          case "refreshCron":
            // Handled by unified background sync - trigger manual sync
            this._backgroundSync();
            break;
          case "loadMoreCronHistory":
            await this.refreshCronData(message.limit || 20);
            break;
          case "toggleScheduler":
            await this.toggleScheduler();
            break;
          case "toggleCronJob":
            await this.toggleCronJob(message.jobName, message.enabled);
            break;
          case "runCronJobNow":
            await this.runCronJobNow(message.jobName);
            break;
          case "openConfigFile":
            console.log("[CommandCenter] Received openConfigFile command from webview");
            await this.openConfigFile();
            break;
          case "loadPersona":
            await this.loadPersona(message.personaName);
            break;
          case "viewPersonaFile":
            await this.openPersonaFile(message.personaName);
            break;
          case "refreshIssues":
            // Handled by unified background sync - trigger manual sync
            this._backgroundSync();
            break;
          case "openJiraBoard":
            vscode.env.openExternal(vscode.Uri.parse("https://issues.redhat.com/secure/RapidBoard.jspa?rapidView=14813"));
            break;
          case "openJiraIssue":
            if (message.issueKey) {
              vscode.env.openExternal(vscode.Uri.parse(`https://issues.redhat.com/browse/${message.issueKey}`));
            }
            break;
          case "semanticSearch":
            await this.executeSemanticSearch(message.query, message.project);
            break;
          case "refreshOllamaStatus":
            // Handled by unified background sync - trigger manual sync
            this._backgroundSync();
            break;
          case "testOllamaInstance":
            await this.testOllamaInstance(message.instance);
            break;
          case "runInferenceTest":
            debugLog(`runInferenceTest: msg=${message.message}, persona=${message.persona}, skill=${message.skill}`);
            await this.runInferenceTest(message.message, message.persona, message.skill);
            break;
          case "getInferenceStats":
            await this.getInferenceStats();
            break;
          case "updateInferenceConfig":
            await this.updateInferenceConfig(message.key, message.value);
            break;
          // Meeting bot controls
          case "approveMeeting":
            await this.handleMeetingApproval(message.meetingId, message.meetUrl, message.mode || "notes");
            break;
          case "rejectMeeting":
            await this.handleMeetingRejection(message.meetingId);
            break;
          case "unapproveMeeting":
            await this.handleMeetingUnapproval(message.meetingId);
            break;
          case "joinMeetingNow":
            await this.handleJoinMeetingNow(message.meetUrl, message.title, message.mode || "notes");
            break;
          case "setMeetingMode":
            await this.handleSetMeetingMode(message.meetingId, message.mode);
            break;
          case "startScheduler":
            await this.handleStartScheduler();
            break;
          case "stopScheduler":
            await this.handleStopScheduler();
            break;
          case "leaveMeeting":
            await this.handleLeaveMeeting(message.sessionId);
            break;
          case "leaveAllMeetings":
            await this.handleLeaveAllMeetings();
            break;
          case "muteAudio":
            await this.handleMuteAudio(message.sessionId);
            break;
          case "unmuteAudio":
            await this.handleUnmuteAudio(message.sessionId);
            break;
          case "testTTS":
            await this.handleTestTTS(message.sessionId);
            break;
          case "testAvatar":
            await this.handleTestAvatar(message.sessionId);
            break;
          case "preloadJira":
            await this.handlePreloadJira(message.sessionId);
            break;
          case "setDefaultMode":
            await this.handleSetDefaultMode(message.mode);
            break;
          case "refreshCalendar":
            await this.handleRefreshCalendar();
            break;
          // Meeting history actions
          case "viewNote":
            await this.handleViewNote(message.noteId);
            break;
          case "viewTranscript":
            await this.handleViewTranscript(message.noteId);
            break;
          case "viewBotLog":
            await this.handleViewBotLog(message.noteId);
            break;
          case "viewLinkedIssues":
            await this.handleViewLinkedIssues(message.noteId);
            break;
          case "searchNotes":
            await this.handleSearchNotes(message.query);
            break;
          case "copyTranscript":
            await this.handleCopyTranscript();
            break;
          case "clearCaptions":
            await this.handleClearCaptions();
            break;
          // Video preview controls
          case "startVideoPreview":
            await this.handleStartVideoPreview(message.device, message.mode || 'webrtc');
            break;
          case "stopVideoPreview":
            await this.handleStopVideoPreview();
            break;
          case "getVideoPreviewFrame":
            await this.handleGetVideoPreviewFrame();
            break;
          case "webviewLog":
            // Log messages from webview to Output panel
            debugLog(`[Webview] ${message.message}`);
            break;
          // Create Session tab actions
          case "createSessionAction":
            await this.handleCreateSessionAction(message.action, message);
            break;
          // Sprint bot controls
          case "sprintAction":
            await this.handleSprintAction(message.action, message.issueKey, message.chatId, message.enabled);
            break;
          // Performance tracking actions
          case "performanceAction":
            await this.handlePerformanceAction(message.action, message.questionId, message.category, message.description);
            break;
        }
      },
      null,
      this._disposables
    );

    // Now set up the rest of the panel after message handler is ready
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // Handle panel visibility changes (e.g., after system wake or tab switch)
    this._panel.onDidChangeViewState(
      (e) => {
        if (e.webviewPanel.visible) {
          debugLog("Panel became visible - refreshing data");
          // Clear cache and force fresh sync when panel becomes visible
          // This handles system wake scenarios where data may be stale
          this._clearSyncCache();
          // Invalidate coordinator cache to force updates
          if (this._refreshCoordinator) {
            this._refreshCoordinator.invalidateCache();
          }
          // Background sync will trigger file watcher which calls _dispatchAllUIUpdates
          this._backgroundSync();
        }
      },
      null,
      this._disposables
    );

    // Load workspace state before first render
    this._loadWorkspaceState();

    // Set the HTML content (this may trigger messages from the webview)
    this.update(true); // Force full render on initial load
    this.startExecutionWatcher();
    this._setupWorkspaceWatcher();

    // Initial data dispatch after first load (environments and inference stats are separate)
    setTimeout(() => {
      this._dispatchAllUIUpdates();
      this.checkEnvironmentHealth();
      this.getInferenceStats();
      // Also refresh service status via D-Bus on initial load
      this._refreshServicesViaDBus().catch(e => {
        debugLog(`Failed to refresh services via D-Bus on init: ${e}`);
      });
      // Load Slack discovery data (cache stats, channel browser, user browser, pending, config)
      this.refreshSlackCacheStats().catch(e => {
        debugLog(`Failed to load Slack cache stats on init: ${e}`);
      });
      this.loadSlackChannelBrowser("").catch(e => {
        debugLog(`Failed to load Slack channel browser on init: ${e}`);
      });
      this.loadSlackUserBrowser("").catch(e => {
        debugLog(`Failed to load Slack user browser on init: ${e}`);
      });
      this.refreshSlackPending().catch(e => {
        debugLog(`Failed to load Slack pending on init: ${e}`);
      });
      this.loadSlackConfig().catch(e => {
        debugLog(`Failed to load Slack config on init: ${e}`);
      });
      this.refreshSlackTargets().catch(e => {
        debugLog(`Failed to load Slack targets on init: ${e}`);
      });
      // Load sprint issues for the Overview page
      this._loadSprintFromFile();
    }, 500);

    // Auto-refresh every 10 seconds with background sync
    // The sync script updates workspace_states.json, and the file watcher triggers UI update
    this._refreshInterval = setInterval(() => {
      this._backgroundSync();
    }, 10000);

    debugLog("Constructor complete - panel ready");
  }

  /**
   * Clear the sync cache file to force fresh data on next sync.
   * Used after system wake or when data seems stale.
   */
  private _clearSyncCache(): void {
    try {
      const cacheFile = path.join(AA_CONFIG_DIR, 'sync_cache.json');
      if (fs.existsSync(cacheFile)) {
        fs.unlinkSync(cacheFile);
        debugLog("Cleared sync cache");
      }
    } catch (e) {
      debugLog(`Failed to clear sync cache: ${e}`);
    }
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
      console.error("[CommandCenter] Failed to refresh Ollama status:", error);
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
      console.error(`[CommandCenter] Failed to test ${instance}:`, error);
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
    try {
      // Call Python backend to run actual inference
      const { spawn } = require("child_process");

      // Escape the message for shell/JSON safety
      const escapedMessage = message.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/'/g, "\\'");
      const escapedPreview = message.substring(0, 50).replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/'/g, "\\'");

      // Get the project root from workspace folders (not extension install location)
      const workspaceFolders = vscode.workspace.workspaceFolders;
      const projectRoot = workspaceFolders && workspaceFolders.length > 0
        ? workspaceFolders[0].uri.fsPath
        : path.join(os.homedir(), "src", "redhat-ai-workflow");

      const pythonScript = `
import sys
import json
import time
import os
from pathlib import Path

# Add project root to path for proper module imports
project_root = Path("${projectRoot}")
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "tool_modules"))

try:
    from aa_ollama.src.tool_filter import HybridToolFilter
    import yaml

    filter_instance = HybridToolFilter()

    start = time.time()
    result = filter_instance.filter(
        message="${escapedMessage}",
        persona="${persona}",
        detected_skill="${skill}" if "${skill}" else None
    )
    latency_ms = (time.time() - start) * 1000

    # Get the actual persona (may have been auto-detected)
    actual_persona = result.get("persona", "${persona}") or "developer"
    persona_auto_detected = result.get("persona_auto_detected", False)
    persona_detection_reason = result.get("persona_detection_reason", "")

    # === GATHER FULL CONTEXT ===

    # 1. Memory State (current_work.yaml) + detect current repo/branch from git
    memory_state = {}
    try:
        memory_path = Path.home() / ".aa-workflow" / "memory" / "state" / "current_work.yaml"
        if memory_path.exists():
            with open(memory_path) as f:
                memory_state = yaml.safe_load(f) or {}
    except:
        pass

    # Detect current repo and branch from git if not in memory
    import subprocess
    try:
        if not memory_state.get("repo"):
            # Get repo name from remote URL or folder name
            try:
                remote_url = subprocess.check_output(
                    ["git", "config", "--get", "remote.origin.url"],
                    cwd=str(project_root), stderr=subprocess.DEVNULL
                ).decode().strip()
                # Extract repo name from URL
                repo_name = remote_url.rstrip("/").split("/")[-1].replace(".git", "")
                memory_state["repo"] = repo_name
            except:
                memory_state["repo"] = project_root.name

        if not memory_state.get("current_branch"):
            try:
                branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=str(project_root), stderr=subprocess.DEVNULL
                ).decode().strip()
                memory_state["current_branch"] = branch
            except:
                pass
    except:
        pass

    # 2. Environment Status
    env_status = {
        "vpn_connected": os.path.exists(os.path.expanduser("~/.aa-workflow/.vpn_connected")),
        "kubeconfigs": {
            "stage": os.path.exists(os.path.expanduser("~/.kube/config.s")),
            "prod": os.path.exists(os.path.expanduser("~/.kube/config.p")),
            "ephemeral": os.path.exists(os.path.expanduser("~/.kube/config.e")),
            "konflux": os.path.exists(os.path.expanduser("~/.kube/config.k")),
        },
        "ollama_instances": [],
    }

    # Check Ollama instances
    try:
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            for name, inst in config.get("ollama_instances", {}).items():
                env_status["ollama_instances"].append({
                    "name": name,
                    "url": inst.get("url", ""),
                    "device": inst.get("device", "unknown"),
                })
    except:
        pass

    # 3. Persona System Prompt + Tool Categories (from personas/ and config.json)
    persona_prompt = ""
    persona_categories = []
    persona_tool_modules = []
    try:
        persona_path = project_root / "personas" / f"{actual_persona}.yaml"
        if persona_path.exists():
            with open(persona_path) as f:
                persona_data = yaml.safe_load(f) or {}
            persona_prompt = persona_data.get("description", "")[:500]
            # Tool modules from persona YAML
            persona_tool_modules = persona_data.get("tools", [])
    except:
        pass

    # Get categories from config.json persona_baselines
    try:
        config_path = project_root / "config.json"
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)
            baseline = config.get("persona_baselines", {}).get(actual_persona, {})
            persona_categories = baseline.get("categories", [])
    except:
        pass

    # 4. Session Log (today's actions)
    session_log = []
    try:
        from datetime import date
        log_path = Path.home() / ".aa-workflow" / "memory" / "sessions" / f"{date.today().isoformat()}.yaml"
        if log_path.exists():
            with open(log_path) as f:
                log_data = yaml.safe_load(f) or {}
            session_log = log_data.get("actions", [])[-5:]  # Last 5 actions
    except:
        pass

    # 5. Semantic Search Results - get from filter context if available
    semantic_results = []
    try:
        # Get semantic results from the filter's context if available
        ctx = result.get("context", {})
        semantic_results = ctx.get("semantic_knowledge", [])[:5]
    except:
        pass

    # 6. Learned Patterns (from memory)
    learned_patterns = []
    try:
        patterns_path = Path.home() / ".aa-workflow" / "memory" / "learned" / "patterns.yaml"
        if patterns_path.exists():
            with open(patterns_path) as f:
                patterns_data = yaml.safe_load(f) or {}
            # Get patterns relevant to detected skill or persona
            for pattern in patterns_data.get("error_patterns", [])[:3]:
                learned_patterns.append({
                    "pattern": pattern.get("pattern", ""),
                    "fix": pattern.get("fix", ""),
                })
    except:
        pass

    # Build output with full context
    output = {
        "tools": result.get("tools", [])[:50],
        "tool_count": len(result.get("tools", [])),
        "reduction_pct": result.get("reduction_pct", 0),
        "methods": result.get("methods", []),
        "persona": actual_persona,
        "persona_auto_detected": persona_auto_detected,
        "persona_detection_reason": persona_detection_reason,
        "skill_detected": result.get("skill_detected"),
        "latency_ms": round(latency_ms, 1),
        "message_preview": "${escapedPreview}",
        "context": result.get("context", {}),
        "semantic_results": semantic_results,
        # Additional context sections
        "memory_state": {
            "active_issues": memory_state.get("active_issues", [])[:3],
            "current_branch": memory_state.get("current_branch"),
            "current_repo": memory_state.get("repo"),
            "notes": memory_state.get("notes", "")[:200] if memory_state.get("notes") else None,
        },
        "environment": env_status,
        "persona_prompt": persona_prompt,
        "persona_categories": persona_categories,
        "persona_tool_modules": persona_tool_modules,
        "session_log": session_log,
        "learned_patterns": learned_patterns,
    }

    print(json.dumps(output))
except Exception as e:
    import traceback
    # Fallback to placeholder if backend not available
    print(json.dumps({
        "tools": ["skill_run", "jira_view_issue", "gitlab_mr_view"],
        "tool_count": 3,
        "reduction_pct": 98.6,
        "methods": ["layer1_core", "layer2_persona"],
        "persona": "${persona}",
        "skill_detected": "${skill}" if "${skill}" else None,
        "latency_ms": 2,
        "message_preview": "${escapedPreview}",
        "error": str(e),
        "traceback": traceback.format_exc()
    }))
`;

      debugLog(`Running inference with projectRoot: ${projectRoot}`);
      debugLog(`Python script length: ${pythonScript.length} chars`);

      const python = spawn("python3", ["-c", pythonScript], {
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

  private async getInferenceStats(): Promise<void> {
    try {
      // Read stats from file
      const statsPath = path.join(
        process.env.HOME || "",
        ".config",
        "aa-workflow",
        "inference_stats.json"
      );

      // Get all available personas from the personas directory
      const allPersonas = this.loadPersonas()
        .filter(p => !p.isInternal && !p.isSlim)  // Filter out internal and slim variants
        .map(p => p.name);

      if (fs.existsSync(statsPath)) {
        const data = JSON.parse(fs.readFileSync(statsPath, "utf-8"));
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
      console.error("[CommandCenter] Failed to get inference stats:", error);
    }
  }

  private async updateInferenceConfig(key: string, value: any): Promise<void> {
    try {
      // Use D-Bus to update config (uses ConfigManager for thread-safe writes)
      // The key format is "section.subkey" - we need to split into section and key
      const parts = key.split(".");
      const section = parts[0];
      const subKey = parts.slice(1).join(".");

      console.log("[CommandCenter] updateInferenceConfig via D-Bus:", section, subKey, value);

      const result = await this.queryDBus(
        "com.aiworkflow.BotCron",
        "/com/aiworkflow/BotCron",
        "com.aiworkflow.BotCron",
        "CallMethod",
        [
          { type: "string", value: "update_config" },
          { type: "string", value: JSON.stringify({ section, key: subKey, value }) }
        ]
      );

      if (result.success && result.data?.success) {
        console.log("[CommandCenter] D-Bus update_config result:", result.data);
        vscode.window.showInformationMessage(`Updated inference config: ${key}`);
      } else {
        const errorMsg = result.data?.error || result.error || "Unknown error";
        console.error("[CommandCenter] D-Bus update_config failed:", errorMsg);
        vscode.window.showErrorMessage(`Failed to update config via D-Bus: ${errorMsg}`);
      }
    } catch (error) {
      console.error("[CommandCenter] Failed to update inference config:", error);
      vscode.window.showErrorMessage(`Failed to update config: ${error}`);
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
          console.error("Semantic search stderr:", stderr);
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
          console.error("Failed to parse search result:", stdout);
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

  private startExecutionWatcher() {
    try {
      const dir = path.dirname(EXECUTION_FILE);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      this._executionWatcher = fs.watch(dir, (eventType, filename) => {
        if (filename === "skill_execution.json") {
          this.loadExecutionState();
        }
      });

      // Also request current running skills from the watcher on startup
      // This ensures the Running Skills panel is populated when the Command Center opens
      this._loadRunningSkillsFromWatcher();
    } catch (e) {
      console.error("Failed to start execution watcher:", e);
    }
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

  private loadExecutionState() {
    try {
      if (fs.existsSync(EXECUTION_FILE)) {
        const content = fs.readFileSync(EXECUTION_FILE, "utf-8");
        const state = JSON.parse(content);
        this.updateSkillExecution(state);
      }
    } catch (e) {
      // File might be mid-write
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

    // Dispose the refresh coordinator
    if (this._refreshCoordinator) {
      this._refreshCoordinator.dispose();
      this._refreshCoordinator = null;
    }

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

  private loadStats(): AgentStats | null {
    try {
      if (fs.existsSync(STATS_FILE)) {
        const content = fs.readFileSync(STATS_FILE, "utf-8");
        return JSON.parse(content);
      }
    } catch (e) {
      console.error("Failed to load agent stats:", e);
    }
    return null;
  }

  private loadCurrentWork(): {
    activeIssue: any;
    activeMR: any;
    followUps: any[];
    sprintIssues: any[];
    activeRepo: string | null;
    // Aggregated totals across all workspaces/sessions
    totalActiveIssues: number;
    totalActiveMRs: number;
    allActiveIssues: { key: string; summary: string; project: string; workspace: string }[];
    allActiveMRs: { id: string; title: string; project: string; workspace: string }[];
  } {
    // First, aggregate from workspace state (multiple workspaces/sessions)
    let totalActiveIssues = 0;
    let totalActiveMRs = 0;
    const allActiveIssues: { key: string; summary: string; project: string; workspace: string }[] = [];
    const allActiveMRs: { id: string; title: string; project: string; workspace: string }[] = [];
    const seenIssues = new Set<string>();
    const seenMRs = new Set<string>();

    if (this._workspaceState) {
      for (const [uri, ws] of Object.entries(this._workspaceState)) {
        const workspaceName = ws.project || path.basename(uri.replace('file://', ''));

        // Check all sessions in this workspace
        for (const session of Object.values(ws.sessions || {})) {
          // Count active issues
          if (session.issue_key && !seenIssues.has(session.issue_key)) {
            seenIssues.add(session.issue_key);
            totalActiveIssues++;
            allActiveIssues.push({
              key: session.issue_key,
              summary: (session as any).issue_summary || (session as any).summary || '',
              project: session.project || ws.project || workspaceName,
              workspace: workspaceName
            });
          }

          // Count active branches (as proxy for MRs - branches typically have associated MRs)
          if (session.branch && !seenMRs.has(session.branch)) {
            seenMRs.add(session.branch);
            // We'll count branches as potential MRs
          }
        }
      }
    }

    try {
      const memoryDir = getMemoryDir();
      const workFile = path.join(memoryDir, "state", "current_work.yaml");
      if (fs.existsSync(workFile)) {
        const content = fs.readFileSync(workFile, "utf-8");
        const lines = content.split("\n");
        let activeIssue: any = null;
        let activeMR: any = null;
        let activeRepo: string | null = null;
        const followUps: any[] = [];
        const sprintIssues: any[] = [];

        let inActiveIssues = false;
        let inOpenMRs = false;
        let inFollowUps = false;
        let inSprintIssues = false;
        let currentIssueData: any = {};
        let currentMRData: any = {};
        const allOpenMRs: any[] = [];

        for (const line of lines) {
          // Detect section starts
          if (line.startsWith("active_issues:")) {
            inActiveIssues = true;
            inOpenMRs = false;
            inFollowUps = false;
            inSprintIssues = false;
            continue;
          }
          if (line.startsWith("open_mrs:")) {
            inOpenMRs = true;
            inActiveIssues = false;
            inFollowUps = false;
            inSprintIssues = false;
            continue;
          }
          if (line.startsWith("follow_ups:")) {
            inFollowUps = true;
            inActiveIssues = false;
            inOpenMRs = false;
            inSprintIssues = false;
            continue;
          }
          if (line.startsWith("sprint_issues:")) {
            inSprintIssues = true;
            inActiveIssues = false;
            inOpenMRs = false;
            inFollowUps = false;
            continue;
          }
          // Reset on other top-level keys
          if (line.match(/^[a-z_]+:/) && !line.startsWith("  ")) {
            inActiveIssues = false;
            inOpenMRs = false;
            inFollowUps = false;
            inSprintIssues = false;
          }

          if (inActiveIssues) {
            // New list item starts
            if (line.trim().startsWith("- ")) {
              // Save previous issue if we have one
              if (currentIssueData.key && !activeIssue) {
                activeIssue = { ...currentIssueData };
                activeRepo = currentIssueData.repo || null;
              }
              currentIssueData = {};
              // Check if it's "- key:" format
              if (line.trim().startsWith("- key:")) {
                currentIssueData.key = line.split(":")[1]?.trim();
              } else if (line.trim().startsWith("- branch:")) {
                currentIssueData.branch = line.split(":")[1]?.trim();
              }
            } else if (line.trim().startsWith("key:")) {
              currentIssueData.key = line.split(":")[1]?.trim();
            } else if (line.trim().startsWith("repo:")) {
              currentIssueData.repo = line.split(":")[1]?.trim();
            } else if (line.trim().startsWith("branch:")) {
              currentIssueData.branch = line.split(":")[1]?.trim();
            } else if (line.trim().startsWith("status:")) {
              currentIssueData.status = line.split(":")[1]?.trim();
            } else if (line.trim().startsWith("summary:")) {
              currentIssueData.summary = line.split(":").slice(1).join(":").trim();
            }
          }

          // Parse open MRs - collect all MRs then find the one matching active issue
          if (inOpenMRs) {
            if (line.trim().startsWith("- id:")) {
              // New MR item - save previous if exists
              if (currentMRData.id) {
                allOpenMRs.push({ ...currentMRData });
              }
              currentMRData = { id: line.split(":")[1]?.trim() };
            } else if (line.trim().startsWith("id:")) {
              currentMRData.id = line.split(":")[1]?.trim();
            } else if (line.trim().startsWith("title:")) {
              currentMRData.title = line.split(":").slice(1).join(":").trim().replace(/^['"]|['"]$/g, '');
            } else if (line.trim().startsWith("status:")) {
              currentMRData.status = line.split(":")[1]?.trim();
            }
          }
          if (inFollowUps && line.trim().startsWith("- ")) {
            const item = line.trim().substring(2);
            if (item) {
              followUps.push(item);
            }
          }
          if (inSprintIssues && line.trim().startsWith("- key:")) {
            const key = line.split(":")[1]?.trim();
            if (key) {
              sprintIssues.push({ key });
            }
          }
        }

        // Don't forget the last issue if we were still parsing
        if (inActiveIssues && currentIssueData.key && !activeIssue) {
          activeIssue = { ...currentIssueData };
          activeRepo = currentIssueData.repo || null;
        }

        // Don't forget the last MR if we were still parsing
        if (currentMRData.id) {
          allOpenMRs.push({ ...currentMRData });
        }

        // Find the MR that matches the active issue (by issue key in title)
        if (activeIssue && activeIssue.key && allOpenMRs.length > 0) {
          const matchingMR = allOpenMRs.find(mr =>
            mr.title && mr.title.includes(activeIssue.key)
          );
          if (matchingMR) {
            activeMR = matchingMR;
          }
        }

        // Fallback to first open MR if no match found
        if (!activeMR && allOpenMRs.length > 0) {
          activeMR = allOpenMRs[0];
        }

        // Add MRs from current_work.yaml to totals (deduplicate by ID)
        // Default project from active issue's repo, or extract from title, or use default
        const defaultProject = activeRepo || (activeIssue?.repo) || 'automation-analytics-backend';
        for (const mr of allOpenMRs) {
          if (mr.id && !seenMRs.has(mr.id)) {
            seenMRs.add(mr.id);
            totalActiveMRs++;
            allActiveMRs.push({
              id: mr.id,
              title: mr.title || '',
              project: mr.project || defaultProject,
              workspace: 'current'
            });
          }
        }

        return {
          activeIssue,
          activeMR,
          followUps,
          sprintIssues,
          activeRepo,
          totalActiveIssues,
          totalActiveMRs,
          allActiveIssues,
          allActiveMRs
        };
      }
    } catch (e) {
      console.error("Failed to load current work:", e);
    }
    return {
      activeIssue: null,
      activeMR: null,
      followUps: [],
      sprintIssues: [],
      activeRepo: null,
      totalActiveIssues,
      totalActiveMRs,
      allActiveIssues,
      allActiveMRs
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
      console.error("Failed to fetch open MRs:", e);
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
   * Refresh sprint issues from cache file and update the UI.
   *
   * NOTE: The UI does NOT spawn sync processes. The sprint bot service
   * handles periodic updates to workspace_states.json. This method only
   * reads from the cache file.
   */
  private async refreshSprintIssues(): Promise<void> {
    logger.log("refreshSprintIssues() called - loading from cache");
    this._loadSprintFromFile();
  }

  /**
   * Load sprint data from cache file and update UI.
   */
  private _loadSprintFromFile(): void {
    logger.log("_loadSprintFromFile() called");
    try {
      // Reload workspace state from file
      this._loadWorkspaceState();

      // Get sprint issues from the loaded state
      const sprintData = (this._workspaceState as any)?.sprint || {};
      const issues = sprintData.issues || [];

      logger.log(`Loaded ${issues.length} sprint issues from cache`);

      // Update the Overview tab's issue list (for backward compatibility)
      this._panel.webview.postMessage({
        type: "sprintIssuesUpdate",
        issues: issues.map((i: any) => ({
          key: i.key,
          type: i.issueType,
          status: i.jiraStatus,
          priority: i.priority,
          summary: i.summary,
          assignee: i.assignee,
          storyPoints: i.storyPoints,
        })),
      });

      // Update Sprint tab with data from file
      const sprintState = loadSprintState();
      const sprintHistory = loadSprintHistory();
      const toolGapRequests = loadToolGapRequests();
      this._panel.webview.postMessage({
        type: "sprintTabUpdate",
        issues: sprintState.issues,
        renderedHtml: getSprintTabContent(sprintState, sprintHistory, toolGapRequests, this._dataProvider.getJiraUrl()),
      });
    } catch (e) {
      console.error("Failed to load sprint from cache:", e);
      this._panel.webview.postMessage({
        type: "sprintIssuesError",
        error: "Failed to load issues from cache",
      });
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

  private loadSkillsList(): SkillDefinition[] {
    const skills: SkillDefinition[] = [];
    try {
      const skillsDir = getSkillsDir();
      if (fs.existsSync(skillsDir)) {
        const files = fs.readdirSync(skillsDir);
        for (const file of files) {
          if (file.endsWith(".yaml") || file.endsWith(".yml")) {
            try {
              const content = fs.readFileSync(path.join(skillsDir, file), "utf-8");
              const name = file.replace(/\.ya?ml$/, "");

              // Simple YAML parsing for key fields
              let description = "";
              let category = "general";

              // Handle both single-line and multi-line YAML descriptions
              // Multi-line: description: |
              //               First line of description
              // Single-line: description: "Some description"
              const multiLineMatch = content.match(/description:\s*\|\s*\n\s+(.+)/);
              const singleLineMatch = content.match(/description:\s*["']?([^"'|\n]+)/);

              if (multiLineMatch) {
                description = multiLineMatch[1].trim();
              } else if (singleLineMatch) {
                description = singleLineMatch[1].trim();
              }

              // Only match top-level category: (at start of line, not indented)
              const catMatch = content.match(/^category:\s*["']?([^"'\n]+)/m);
              if (catMatch) category = catMatch[1].trim();

              skills.push({ name, description, category });
            } catch {
              // Skip invalid files
            }
          }
        }
      }
    } catch (e) {
      console.error("Failed to load skills:", e);
    }
    return skills.sort((a, b) => a.name.localeCompare(b.name));
  }

  private async loadSkillDefinition(skillName: string) {
    try {
      const skillsDir = getSkillsDir();
      const filePath = path.join(skillsDir, `${skillName}.yaml`);

      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, "utf-8");
        this._panel.webview.postMessage({
          command: "skillDefinition",
          skillName,
          content,
        });
      }
    } catch (e) {
      console.error("Failed to load skill definition:", e);
    }
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

  private async openSkillFlowchart(skillName?: string) {
    try {
      // Import SkillFlowchartPanel directly to ensure we use the same module instance
      // This is critical for the static currentPanel variable to work correctly
      const { SkillFlowchartPanel } = await import("./skillFlowchartPanel");

      // Use createOrShow directly - this properly reuses existing panels
      const panel = SkillFlowchartPanel.createOrShow(this._extensionUri, "bottom");

      if (skillName) {
        panel.loadSkill(skillName);
      }
    } catch (e) {
      console.error("[CommandCenter] Failed to open skill flowchart:", e);
      vscode.window.showErrorMessage(`Failed to open skill flowchart: ${e}`);
    }
  }

  private getMemoryHealth(): { totalSize: string; sessionLogs: number; lastSession: string; patterns: number } {
    try {
      const memoryDir = getMemoryDir();
      let totalBytes = 0;
      let sessionLogs = 0;
      let lastSession = "Unknown";
      let patterns = 0;

      if (fs.existsSync(memoryDir)) {
        const sessionsDir = path.join(memoryDir, "sessions");
        if (fs.existsSync(sessionsDir)) {
          const sessions = fs.readdirSync(sessionsDir).filter(f => f.endsWith(".yaml") && f !== ".gitkeep");
          sessionLogs = sessions.length;
          if (sessions.length > 0) {
            const sorted = sessions.sort().reverse();
            lastSession = sorted[0].replace(".yaml", "");
          }
        }

        // Count patterns from learned files
        const learnedDir = path.join(memoryDir, "learned");
        if (fs.existsSync(learnedDir)) {
          const learnedFiles = fs.readdirSync(learnedDir).filter(f => f.endsWith(".yaml"));
          patterns = learnedFiles.length;
        }

        const walkDir = (dir: string) => {
          try {
            const items = fs.readdirSync(dir);
            for (const item of items) {
              const fullPath = path.join(dir, item);
              const stat = fs.statSync(fullPath);
              if (stat.isDirectory()) {
                walkDir(fullPath);
              } else {
                totalBytes += stat.size;
              }
            }
          } catch {
            // Ignore permission errors
          }
        };
        walkDir(memoryDir);
      }

      return {
        totalSize:
          totalBytes > 1024 * 1024
            ? `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`
            : totalBytes > 1024
              ? `${(totalBytes / 1024).toFixed(1)} KB`
              : `${totalBytes} B`,
        sessionLogs,
        lastSession,
        patterns,
      };
    } catch (e) {
      console.error("Failed to get memory health:", e);
      return { totalSize: "Unknown", sessionLogs: 0, lastSession: "Unknown", patterns: 0 };
    }
  }

  private loadMemoryFiles(): { state: string[]; learned: string[]; sessions: string[]; knowledge: { project: string; persona: string; confidence: number }[] } {
    const result = {
      state: [] as string[],
      learned: [] as string[],
      sessions: [] as string[],
      knowledge: [] as { project: string; persona: string; confidence: number }[]
    };
    try {
      const memoryDir = getMemoryDir();

      const stateDir = path.join(memoryDir, "state");
      if (fs.existsSync(stateDir)) {
        result.state = fs.readdirSync(stateDir).filter(f => f.endsWith(".yaml"));
      }

      const learnedDir = path.join(memoryDir, "learned");
      if (fs.existsSync(learnedDir)) {
        result.learned = fs.readdirSync(learnedDir).filter(f => f.endsWith(".yaml"));
      }

      const sessionsDir = path.join(memoryDir, "sessions");
      if (fs.existsSync(sessionsDir)) {
        result.sessions = fs.readdirSync(sessionsDir)
          .filter(f => f.endsWith(".yaml") && f !== "example.yaml" && f !== ".gitkeep")
          .sort()
          .reverse()
          .slice(0, 20);
      }

      // Load knowledge files from memory/knowledge/personas/
      const knowledgeDir = path.join(memoryDir, "knowledge", "personas");
      if (fs.existsSync(knowledgeDir)) {
        const personas = fs.readdirSync(knowledgeDir).filter(f => {
          const stat = fs.statSync(path.join(knowledgeDir, f));
          return stat.isDirectory();
        });

        for (const persona of personas) {
          const personaDir = path.join(knowledgeDir, persona);
          const files = fs.readdirSync(personaDir).filter(f => f.endsWith(".yaml"));

          for (const file of files) {
            try {
              const content = fs.readFileSync(path.join(personaDir, file), "utf-8");
              // Parse YAML to get confidence
              const confidenceMatch = content.match(/confidence:\s*([\d.]+)/);
              const confidence = confidenceMatch ? parseFloat(confidenceMatch[1]) : 0;

              result.knowledge.push({
                project: file.replace(".yaml", ""),
                persona: persona,
                confidence: Math.round(confidence * 100)
              });
            } catch (e) {
              // Skip files that can't be parsed
            }
          }
        }
      }
    } catch (e) {
      console.error("Failed to load memory files:", e);
    }
    return result;
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
          // Refresh status after a short delay with HIGH priority (user action)
          setTimeout(() => {
            this._loadWorkspaceState();
            this._dispatchAllUIUpdates(RefreshPriority.HIGH);
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
          // Refresh with HIGH priority (user action)
          setTimeout(() => {
            this._loadWorkspaceState();
            this._dispatchAllUIUpdates(RefreshPriority.HIGH);
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
          // Persona selected - load tools for that persona
          if (message.personaId) {
            debugLog(`[CreateSession] Persona selected: ${message.personaId}`);
            // Load persona YAML to get tool list
            const personaPath = path.join(os.homedir(), "src", "redhat-ai-workflow", "personas", `${message.personaId}.yaml`);
            try {
              if (fs.existsSync(personaPath)) {
                const yaml = require("js-yaml");
                const personaData = yaml.load(fs.readFileSync(personaPath, "utf-8"));
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
  // Sprint Bot Control Methods
  // ============================================================================

  private async handleSprintAction(action: string, issueKey?: string, chatId?: string, enabled?: boolean) {
    try {
      const sprintStateFile = path.join(
        os.homedir(),
        ".config",
        "aa-workflow",
        "sprint_state.json"
      );

      // Load current state
      let state: SprintState = {
        currentSprint: null,
        nextSprint: null,
        issues: [],
        automaticMode: false,
        manuallyStarted: false,
        backgroundTasks: false,
        lastUpdated: new Date().toISOString(),
        processingIssue: null,
      };

      if (fs.existsSync(sprintStateFile)) {
        try {
          state = JSON.parse(fs.readFileSync(sprintStateFile, "utf-8"));
        } catch (e) {
          console.error("Failed to parse sprint state:", e);
        }
      }

      switch (action) {
        case "approve":
          if (issueKey) {
            const issue = state.issues.find((i) => i.key === issueKey);
            if (issue) {
              issue.approvalStatus = "approved";
              issue.timeline.push({
                timestamp: new Date().toISOString(),
                action: "approved",
                description: "Issue approved for automated work",
              });
              vscode.window.showInformationMessage(`Approved ${issueKey} for sprint bot`);
            }
          }
          break;

        case "reject":
          // Unapprove - set back to pending
          if (issueKey) {
            const issue = state.issues.find((i) => i.key === issueKey);
            if (issue) {
              issue.approvalStatus = "pending";
              issue.timeline.push({
                timestamp: new Date().toISOString(),
                action: "unapproved",
                description: "Issue unapproved - removed from bot queue",
              });
              vscode.window.showInformationMessage(`Unapproved ${issueKey}`);
            }
          }
          break;

        case "abort":
          if (issueKey) {
            const issue = state.issues.find((i) => i.key === issueKey);
            if (issue) {
              issue.approvalStatus = "blocked";
              issue.timeline.push({
                timestamp: new Date().toISOString(),
                action: "aborted",
                description: "User took control - automated work stopped",
              });
              if (state.processingIssue === issueKey) {
                state.processingIssue = null;
              }
              vscode.window.showInformationMessage(`Aborted ${issueKey} - you can now work on it manually`);
            }
          }
          break;

        case "approveAll":
          const pendingIssues = state.issues.filter(
            (i) => i.approvalStatus === "pending" || i.approvalStatus === "waiting"
          );
          for (const issue of pendingIssues) {
            issue.approvalStatus = "approved";
            issue.timeline.push({
              timestamp: new Date().toISOString(),
              action: "approved",
              description: "Issue approved (batch approval)",
            });
          }
          vscode.window.showInformationMessage(`Approved ${pendingIssues.length} issues`);
          break;

        case "rejectAll":
          // Unapprove all - set approved issues back to pending
          const approvedIssues = state.issues.filter(
            (i) => i.approvalStatus === "approved"
          );
          for (const issue of approvedIssues) {
            issue.approvalStatus = "pending";
            issue.timeline.push({
              timestamp: new Date().toISOString(),
              action: "unapproved",
              description: "Issue unapproved (batch unapproval)",
            });
          }
          vscode.window.showInformationMessage(`Unapproved ${approvedIssues.length} issues`);
          break;

        case "toggleAutomatic":
          state.automaticMode = enabled ?? !state.automaticMode;
          vscode.window.showInformationMessage(
            `Sprint bot automatic mode ${state.automaticMode ? "enabled (Mon-Fri 9-5)" : "disabled"}`
          );
          break;

        case "startBot":
          state.manuallyStarted = true;
          vscode.window.showInformationMessage(
            "Sprint bot started manually - will process approved issues now"
          );
          break;

        case "stopBot":
          state.manuallyStarted = false;
          state.processingIssue = null;
          vscode.window.showInformationMessage(
            "Sprint bot stopped"
          );
          break;

        case "startIssue":
          // Start an issue immediately via D-Bus, bypassing all checks
          if (issueKey) {
            logger.log(`Starting issue immediately: ${issueKey}`);
            try {
              // Determine if we should use background mode
              // If backgroundTasks is false, we want foreground (chat opens in front)
              const useBackground = state.backgroundTasks;

              const dbusResult = await this.queryDBus(
                "com.aiworkflow.BotSprint",
                "/com/aiworkflow/BotSprint",
                "com.aiworkflow.BotSprint",
                "CallMethod",
                [
                  { type: "string", value: "start_issue" },
                  { type: "string", value: JSON.stringify({ issue_key: issueKey, background: useBackground }) },
                ]
              );

              if (dbusResult.success && dbusResult.data) {
                const parsed = typeof dbusResult.data === "string"
                  ? JSON.parse(dbusResult.data)
                  : dbusResult.data;
                if (parsed.success) {
                  const modeMsg = useBackground ? "in background" : "in foreground";
                  vscode.window.showInformationMessage(
                    `Started ${issueKey} ${modeMsg}. ${parsed.message || ""}`
                  );
                  // Update local state to reflect the change
                  const issue = state.issues.find((i) => i.key === issueKey);
                  if (issue) {
                    issue.approvalStatus = "in_progress";
                    if (parsed.chat_id) {
                      issue.chatId = parsed.chat_id;
                    }
                  }
                  state.processingIssue = issueKey;
                } else {
                  vscode.window.showErrorMessage(
                    `Failed to start ${issueKey}: ${parsed.error || "Unknown error"}`
                  );
                }
              } else {
                vscode.window.showErrorMessage(
                  `Failed to start ${issueKey}: ${dbusResult.error || "D-Bus call failed"}`
                );
              }
            } catch (e: any) {
              logger.error(`Failed to start ${issueKey}: ${e.message}`);
              vscode.window.showErrorMessage(
                `Failed to start ${issueKey}: ${e.message}`
              );
            }
          }
          break;

        // Legacy support for toggleBot
        case "toggleBot":
          state.automaticMode = enabled ?? !state.automaticMode;
          vscode.window.showInformationMessage(
            `Sprint bot automatic mode ${state.automaticMode ? "enabled" : "disabled"}`
          );
          break;

        case "openChat":
          if (chatId) {
            // Try to open the chat - this is experimental
            try {
              await vscode.commands.executeCommand("composer.showComposerHistory");
              vscode.window.showInformationMessage(
                `Looking for chat for ${issueKey}... Check the chat history panel.`
              );
            } catch (e) {
              vscode.window.showWarningMessage(
                `Could not open chat directly. Chat ID: ${chatId}`
              );
            }
          }
          break;

        case "openInCursor":
          // Open background work log in Cursor for interactive continuation
          if (issueKey) {
            logger.log(`Opening ${issueKey} in Cursor for interactive continuation`);
            try {
              const dbusResult = await this.queryDBus(
                "com.aiworkflow.BotSprint",
                "/com/aiworkflow/BotSprint",
                "com.aiworkflow.BotSprint",
                "CallMethod",
                [
                  { type: "string", value: "open_in_cursor" },
                  { type: "string", value: JSON.stringify({ issue_key: issueKey }) },
                ]
              );

              if (dbusResult.success && dbusResult.data) {
                const parsed = typeof dbusResult.data === "string"
                  ? JSON.parse(dbusResult.data)
                  : dbusResult.data;
                if (parsed.success) {
                  vscode.window.showInformationMessage(
                    `Opened ${issueKey} in Cursor. Review the context and continue working.`
                  );
                  // Update the issue with the new chat ID
                  const issue = state.issues.find((i) => i.key === issueKey);
                  if (issue && parsed.chat_id) {
                    issue.chatId = parsed.chat_id;
                  }
                } else {
                  vscode.window.showErrorMessage(
                    `Failed to open ${issueKey}: ${parsed.error || "Unknown error"}`
                  );
                }
              } else {
                vscode.window.showErrorMessage(
                  `Failed to open ${issueKey}: ${dbusResult.error || "D-Bus call failed"}`
                );
              }
            } catch (e: any) {
              logger.error(`Failed to open ${issueKey} in Cursor: ${e.message}`);
              vscode.window.showErrorMessage(
                `Failed to open ${issueKey} in Cursor: ${e.message}`
              );
            }
          }
          break;

        // loadSprint removed - sprint data is auto-loaded by MCP server

        case "viewTimeline":
          if (issueKey) {
            const issue = state.issues.find((i) => i.key === issueKey);
            if (issue && issue.timeline.length > 0) {
              const content = issue.timeline
                .map((e) => `[${e.timestamp}] ${e.action}: ${e.description}`)
                .join("\n");
              const doc = await vscode.workspace.openTextDocument({
                content: `Timeline for ${issueKey}\n${"=".repeat(40)}\n\n${content}`,
                language: "markdown",
              });
              await vscode.window.showTextDocument(doc);
            } else {
              vscode.window.showInformationMessage(`No timeline events for ${issueKey}`);
            }
          }
          break;

        case "testChatLauncher":
          logger.log("testChatLauncher action received, backgroundTasks: " + state.backgroundTasks);
          await this.testChatLauncher(undefined, state.backgroundTasks || false);
          return; // Don't save state for test action

        case "toggleBackgroundTasks":
          state.backgroundTasks = enabled ?? !state.backgroundTasks;
          logger.log("Background tasks toggled: " + state.backgroundTasks);
          break;

        default:
          logger.log("Unknown sprint action: " + action);
      }

      // Save updated state to source file (for MCP server)
      state.lastUpdated = new Date().toISOString();
      const stateDir = path.dirname(sprintStateFile);
      if (!fs.existsSync(stateDir)) {
        fs.mkdirSync(stateDir, { recursive: true });
      }
      fs.writeFileSync(sprintStateFile, JSON.stringify(state, null, 2));

      // Also update the unified workspace_states.json for immediate UI feedback
      try {
        if (fs.existsSync(WORKSPACE_STATES_FILE)) {
          const unified = JSON.parse(fs.readFileSync(WORKSPACE_STATES_FILE, "utf-8"));
          unified.sprint = state;
          unified.exported_at = new Date().toISOString();
          fs.writeFileSync(WORKSPACE_STATES_FILE, JSON.stringify(unified, null, 2));
        }
      } catch (e) {
        console.error("Failed to update unified state:", e);
      }

      // Use incremental update instead of full re-render to avoid UI blanking
      const sprintState = loadSprintState();
      const sprintHistory = loadSprintHistory();
      const toolGapRequests = loadToolGapRequests();
      this._panel.webview.postMessage({
        type: "sprintTabUpdate",
        issues: sprintState.issues,
        renderedHtml: getSprintTabContent(sprintState, sprintHistory, toolGapRequests, this._dataProvider.getJiraUrl()),
      });
    } catch (e: any) {
      vscode.window.showErrorMessage(`Sprint action failed: ${e.message}`);
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

      // Use incremental badge update instead of full re-render
      const performanceState = loadPerformanceState();
      this._panel.webview.postMessage({
        type: "performanceTabBadgeUpdate",
        percentage: performanceState.overall_percentage || 0,
      });
    } catch (e: any) {
      vscode.window.showErrorMessage(`Performance action failed: ${e.message}`);
    }
  }

  /**
   * Test the chat launcher functionality.
   * Creates a new Cursor chat and pastes a skill_run command.
   */
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
  // Meeting Bot Control Methods
  // ============================================================================

  private async handleMeetingApproval(meetingId: string, meetUrl: string, mode: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "approve_meeting" },
          { type: "string", value: JSON.stringify([meetingId, mode]) }
        ]
      );

      if (result.success) {
        // Send success message to webview (UI already updated optimistically)
        this._panel.webview.postMessage({
          type: "meetingApproved",
          meetingId,
          success: true,
          mode,
        });
        vscode.window.showInformationMessage(`Meeting approved (${mode} mode)`);
        // Trigger refresh to update UI
        this._backgroundSync();
      } else {
        // Send failure message to webview so it can revert optimistic update
        this._panel.webview.postMessage({
          type: "meetingApproved",
          meetingId,
          success: false,
          error: result.error,
        });
        vscode.window.showErrorMessage(`Failed to approve meeting: ${result.error}`);
      }
    } catch (e: any) {
      // Send failure message to webview so it can revert optimistic update
      this._panel.webview.postMessage({
        type: "meetingApproved",
        meetingId,
        success: false,
        error: e.message,
      });
      vscode.window.showErrorMessage(`Failed to approve meeting: ${e.message}`);
    }
  }

  private async handleMeetingRejection(meetingId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "reject_meeting" },
          { type: "string", value: JSON.stringify([meetingId]) }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage("Meeting rejected");
        this._backgroundSync();
      } else {
        vscode.window.showErrorMessage(`Failed to reject meeting: ${result.error}`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to reject meeting: ${e.message}`);
    }
  }

  private async handleMeetingUnapproval(meetingId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "unapprove_meeting" },
          { type: "string", value: JSON.stringify([meetingId]) }
        ]
      );

      if (result.success) {
        // Send success message to webview
        this._panel.webview.postMessage({
          type: "meetingUnapproved",
          meetingId,
          success: true,
        });
        vscode.window.showInformationMessage("Meeting marked as skipped");
        this._backgroundSync();
      } else {
        // Send failure message to webview so it can revert optimistic update
        this._panel.webview.postMessage({
          type: "meetingUnapproved",
          meetingId,
          success: false,
          error: result.error,
        });
        vscode.window.showErrorMessage(`Failed to unapprove meeting: ${result.error}`);
      }
    } catch (e: any) {
      this._panel.webview.postMessage({
        type: "meetingUnapproved",
        meetingId,
        success: false,
        error: e.message,
      });
      vscode.window.showErrorMessage(`Failed to unapprove meeting: ${e.message}`);
    }
  }

  private async handleJoinMeetingNow(meetUrl: string, title: string, mode: string) {
    debugLog(`handleJoinMeetingNow called: url=${meetUrl}, title=${title}, mode=${mode}`);

    // Show immediate feedback - the join is async on the daemon side
    vscode.window.showInformationMessage(`🎥 Joining meeting: ${title}...`);
    this._panel.webview.postMessage({
      type: "meetingJoining",
      meetUrl,
      title,
      success: true,
      status: "joining",
      message: "Starting browser and logging in...",
    });

    try {
      debugLog(`Calling D-Bus CallMethod for join_meeting...`);
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "join_meeting" },
          { type: "string", value: JSON.stringify([meetUrl, title, mode]) }
        ]
      );
      debugLog(`D-Bus result: ${JSON.stringify(result)}`);

      if (result.success) {
        // The daemon returns immediately with status="joining"
        // The actual join happens in the background
        const data = result.data as any;
        if (data?.status === "joining") {
          vscode.window.showInformationMessage(`🎥 Join started - browser is loading...`);
        } else {
          vscode.window.showInformationMessage(`✅ Joined meeting: ${title}`);
        }
        // Start polling for status updates
        this._backgroundSync();
        // Poll more frequently while joining
        setTimeout(() => this._backgroundSync(), 5000);
        setTimeout(() => this._backgroundSync(), 15000);
        setTimeout(() => this._backgroundSync(), 30000);
      } else {
        // Send failure message to webview
        this._panel.webview.postMessage({
          type: "meetingJoining",
          meetUrl,
          title,
          success: false,
          error: result.error,
        });
        vscode.window.showErrorMessage(`Failed to join meeting: ${result.error}`);
      }
    } catch (e: any) {
      // D-Bus timeout is expected for long operations - check if it's actually joining
      debugLog(`D-Bus error (may be timeout): ${e.message}`);
      if (e.message.includes("NoReply") || e.message.includes("timeout")) {
        // This is likely a timeout - the daemon is probably still joining
        vscode.window.showInformationMessage(`🎥 Join in progress - please wait...`);
        // Poll for status
        setTimeout(() => this._backgroundSync(), 5000);
        setTimeout(() => this._backgroundSync(), 15000);
      } else {
        // Actual error
        this._panel.webview.postMessage({
          type: "meetingJoining",
          meetUrl,
          title,
          success: false,
          error: e.message,
        });
        vscode.window.showErrorMessage(`Failed to join meeting: ${e.message}`);
      }
    }
  }

  private async handleSetMeetingMode(meetingId: string, mode: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "set_meeting_mode" },
          { type: "string", value: JSON.stringify([meetingId, mode]) }
        ]
      );

      if (result.success) {
        // Silent success - UI already updated optimistically
        this._backgroundSync();
      }
    } catch (e: any) {
      console.error(`Failed to set meeting mode: ${e.message}`);
    }
  }

  private async handleStartScheduler() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "start_scheduler" },
          { type: "string", value: "[]" }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage("Meeting scheduler started");
        this._backgroundSync();
      } else {
        vscode.window.showErrorMessage(`Failed to start scheduler: ${result.error}`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to start scheduler: ${e.message}`);
    }
  }

  private async handleStopScheduler() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "stop_scheduler" },
          { type: "string", value: "[]" }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage("Meeting scheduler stopped");
        this._backgroundSync();
      } else {
        vscode.window.showErrorMessage(`Failed to stop scheduler: ${result.error}`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to stop scheduler: ${e.message}`);
    }
  }

  private async handleLeaveMeeting(sessionId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "leave_meeting" },
          { type: "string", value: JSON.stringify([sessionId]) }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage("Left meeting");
        // Clear the cached meet data to force fresh fetch
        this._meetData = {};
        // Delete the sync cache file to force fresh data
        this._clearSyncCache();
        // Invalidate coordinator cache to force updates
        if (this._refreshCoordinator) {
          this._refreshCoordinator.invalidateSections(["meetings"]);
        }
        // Run sync with HIGH priority (user action)
        this._backgroundSync();
        // Single delayed refresh with HIGH priority
        setTimeout(() => {
          this._loadWorkspaceState();
          this._dispatchAllUIUpdates(RefreshPriority.HIGH);
        }, 2000);
      } else {
        vscode.window.showErrorMessage(`Failed to leave meeting: ${result.error}`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to leave meeting: ${e.message}`);
    }
  }

  private async handleLeaveAllMeetings() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "leave_all_meetings" },
          { type: "string", value: "[]" }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage("Left all meetings");
        this._backgroundSync();
      } else {
        vscode.window.showErrorMessage(`Failed to leave meetings: ${result.error}`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to leave meetings: ${e.message}`);
    }
  }

  private async handleMuteAudio(sessionId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "mute_audio" },
          { type: "string", value: JSON.stringify([sessionId]) }
        ]
      );

      if (result.success) {
        // Send confirmation to webview
        this._panel.webview.postMessage({
          type: "audioStateChanged",
          muted: true,
          sessionId,
        });
      } else {
        vscode.window.showErrorMessage(`Failed to mute audio: ${result.error}`);
        // Revert UI state
        this._panel.webview.postMessage({
          type: "audioStateChanged",
          muted: false,
          sessionId,
          error: result.error,
        });
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to mute audio: ${e.message}`);
    }
  }

  private async handleUnmuteAudio(sessionId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "unmute_audio" },
          { type: "string", value: JSON.stringify([sessionId]) }
        ]
      );

      if (result.success) {
        // Send confirmation to webview
        this._panel.webview.postMessage({
          type: "audioStateChanged",
          muted: false,
          sessionId,
        });
      } else {
        vscode.window.showErrorMessage(`Failed to unmute audio: ${result.error}`);
        // Revert UI state
        this._panel.webview.postMessage({
          type: "audioStateChanged",
          muted: true,
          sessionId,
          error: result.error,
        });
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to unmute audio: ${e.message}`);
    }
  }

  private async handleTestTTS(sessionId?: string) {
    try {
      const args = sessionId ? JSON.stringify([sessionId]) : "[]";
      await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "test_tts" },
          { type: "string", value: args }
        ]
      );
      vscode.window.showInformationMessage(
        sessionId ? `TTS test sent to meeting ${sessionId}` : "TTS test sent"
      );
    } catch (e: any) {
      vscode.window.showErrorMessage(`TTS test failed: ${e.message}`);
    }
  }

  private async handleTestAvatar(sessionId?: string) {
    try {
      const args = sessionId ? JSON.stringify([sessionId]) : "[]";
      await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "test_avatar" },
          { type: "string", value: args }
        ]
      );
      vscode.window.showInformationMessage(
        sessionId ? `Avatar test sent to meeting ${sessionId}` : "Avatar test sent"
      );
    } catch (e: any) {
      vscode.window.showErrorMessage(`Avatar test failed: ${e.message}`);
    }
  }

  private async handlePreloadJira(sessionId?: string) {
    try {
      const args = sessionId ? JSON.stringify([sessionId]) : "[]";
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "preload_jira" },
          { type: "string", value: args }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage("Jira context preloaded");
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to preload Jira: ${e.message}`);
    }
  }

  private async handleSetDefaultMode(mode: string) {
    try {
      await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "set_default_mode" },
          { type: "string", value: JSON.stringify([mode]) }
        ]
      );
    } catch (e: any) {
      console.error(`Failed to set default mode: ${e.message}`);
    }
  }

  private async handleRefreshCalendar() {
    try {
      await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "refresh_calendars" },
          { type: "string", value: "[]" }
        ]
      );
      this._backgroundSync();
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to refresh calendars: ${e.message}`);
    }
  }

  // Meeting history handlers
  private async handleViewNote(noteId: number) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "get_meeting_note" },
          { type: "string", value: JSON.stringify([noteId]) }
        ]
      );

      if (result.success && result.data) {
        const note = typeof result.data === 'string' ? JSON.parse(result.data) : result.data;
        // Open in a new editor tab
        const doc = await vscode.workspace.openTextDocument({
          content: this.formatMeetingNote(note),
          language: 'markdown'
        });
        await vscode.window.showTextDocument(doc, { preview: false });
      } else {
        vscode.window.showWarningMessage(`Meeting note ${noteId} not found`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to load meeting note: ${e.message}`);
    }
  }

  private async handleViewTranscript(noteId: number) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "get_transcript" },
          { type: "string", value: JSON.stringify([noteId]) }
        ]
      );

      if (result.success && result.data) {
        const transcript = typeof result.data === 'string' ? JSON.parse(result.data) : result.data;
        // Format transcript entries
        const content = this.formatTranscript(transcript);
        const doc = await vscode.workspace.openTextDocument({
          content: content,
          language: 'markdown'
        });
        await vscode.window.showTextDocument(doc, { preview: false });
      } else {
        vscode.window.showWarningMessage(`Transcript for meeting ${noteId} not found`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to load transcript: ${e.message}`);
    }
  }

  private async handleViewBotLog(noteId: number) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "get_bot_log" },
          { type: "string", value: JSON.stringify([noteId]) }
        ]
      );

      if (result.success && result.data) {
        const log = typeof result.data === 'string' ? JSON.parse(result.data) : result.data;
        const content = this.formatBotLog(log);
        const doc = await vscode.workspace.openTextDocument({
          content: content,
          language: 'log'
        });
        await vscode.window.showTextDocument(doc, { preview: false });
      } else {
        vscode.window.showWarningMessage(`Bot log for meeting ${noteId} not found`);
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to load bot log: ${e.message}`);
    }
  }

  private async handleViewLinkedIssues(noteId: number) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "get_linked_issues" },
          { type: "string", value: JSON.stringify([noteId]) }
        ]
      );

      if (result.success && result.data) {
        const issues = typeof result.data === 'string' ? JSON.parse(result.data) : result.data;
        if (Array.isArray(issues) && issues.length > 0) {
          // Show quick pick to select an issue to open
          const items = issues.map((issue: any) => ({
            label: issue.key || issue.id,
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
          vscode.window.showInformationMessage('No linked issues found for this meeting');
        }
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to load linked issues: ${e.message}`);
    }
  }

  private async handleSearchNotes(query: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "search_notes" },
          { type: "string", value: JSON.stringify([query]) }
        ]
      );

      if (result.success && result.data) {
        const notes = typeof result.data === 'string' ? JSON.parse(result.data) : result.data;
        // Update the UI with search results
        this._panel.webview.postMessage({
          type: 'searchResults',
          notes: notes
        });
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Search failed: ${e.message}`);
    }
  }

  private async handleCopyTranscript() {
    try {
      // Get current meeting's captions from the state
      if (fs.existsSync(WORKSPACE_STATES_FILE)) {
        const content = fs.readFileSync(WORKSPACE_STATES_FILE, 'utf-8');
        const state = JSON.parse(content);
        const meetData = state.meetBot || {};
        const captions = meetData.captions || [];

        if (captions.length > 0) {
          const text = captions.map((c: any) => `[${c.speaker}] ${c.text}`).join('\n');
          await vscode.env.clipboard.writeText(text);
          vscode.window.showInformationMessage(`Copied ${captions.length} captions to clipboard`);
        } else {
          vscode.window.showInformationMessage('No captions to copy');
        }
      }
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to copy transcript: ${e.message}`);
    }
  }

  private async handleClearCaptions() {
    try {
      await this.queryDBus(
        "com.aiworkflow.BotMeet",
        "/com/aiworkflow/BotMeet",
        "com.aiworkflow.BotMeet",
        "CallMethod",
        [
          { type: "string", value: "clear_captions" },
          { type: "string", value: "[]" }
        ]
      );
      this._backgroundSync();
      vscode.window.showInformationMessage('Captions cleared');
    } catch (e: any) {
      vscode.window.showErrorMessage(`Failed to clear captions: ${e.message}`);
    }
  }

  // Video preview state
  private _videoPreviewActive = false;
  private _videoPreviewDevice = "/dev/video10";
  private _videoPreviewMode = "webrtc";
  private _videoPreviewProcess: any = null;

  /**
   * Start video preview in the specified mode.
   *
   * Modes:
   * - webrtc: Hardware-accelerated H.264 via Intel VAAPI, streamed via WebRTC (~6W, <50ms latency)
   * - mjpeg: Hardware JPEG encoding via VAAPI, HTTP stream (~8W, ~100ms latency)
   * - snapshot: Legacy ffmpeg frame capture (~35W, ~500ms latency)
   */
  private async handleStartVideoPreview(device: string, mode: string = 'webrtc') {
    this._videoPreviewDevice = device || "/dev/video10";
    this._videoPreviewMode = mode;
    this._videoPreviewActive = true;

    debugLog(`Starting video preview: device=${device}, mode=${mode}`);

    if (mode === 'webrtc' || mode === 'mjpeg') {
      // For WebRTC/MJPEG modes, we need to start the streaming pipeline via D-Bus
      // The video daemon handles the Intel VAAPI encoding
      try {
        await this.queryDBus(
          "com.aiworkflow.BotVideo",
          "/com/aiworkflow/BotVideo",
          "com.aiworkflow.BotVideo",
          "StartStreaming",
          [
            { type: "string", value: device },
            { type: "string", value: mode },
            { type: "string", value: String(mode === 'webrtc' ? 8765 : 8766) }  // signaling/mjpeg port
          ]
        );

        this._panel.webview.postMessage({
          type: 'videoPreviewStarted',
          mode: mode,
          device: device
        });

        debugLog(`Video streaming started via D-Bus: ${mode}`);
      } catch (e: any) {
        debugLog(`D-Bus streaming start failed: ${e.message}, falling back to direct check`);

        // Check if device exists for snapshot fallback
        if (!fs.existsSync(this._videoPreviewDevice)) {
          this._panel.webview.postMessage({
            type: 'videoPreviewError',
            error: `Device ${this._videoPreviewDevice} not found. Start the video daemon first.`
          });
          return;
        }

        // For WebRTC, the webview will connect directly to ws://localhost:8765
        // For MJPEG, the webview will connect directly to http://localhost:8766/stream.mjpeg
        this._panel.webview.postMessage({
          type: 'videoPreviewStarted',
          mode: mode,
          device: device,
          note: 'Connecting directly to streaming server'
        });
      }
    } else {
      // Snapshot mode - check if device exists
      if (!fs.existsSync(this._videoPreviewDevice)) {
        this._panel.webview.postMessage({
          type: 'videoPreviewError',
          error: `Device ${this._videoPreviewDevice} not found. Is the video daemon running?`
        });
        return;
      }

      this._panel.webview.postMessage({
        type: 'videoPreviewStarted',
        mode: 'snapshot',
        device: device
      });
    }
  }

  private async handleStopVideoPreview() {
    this._videoPreviewActive = false;

    // Stop streaming via D-Bus if using WebRTC/MJPEG
    if (this._videoPreviewMode === 'webrtc' || this._videoPreviewMode === 'mjpeg') {
      try {
        await this.queryDBus(
          "com.aiworkflow.BotVideo",
          "/com/aiworkflow/BotVideo",
          "com.aiworkflow.BotVideo",
          "StopStreaming",
          []
        );
        debugLog("Video streaming stopped via D-Bus");
      } catch (e: any) {
        debugLog(`D-Bus streaming stop failed: ${e.message}`);
      }
    }

    // Kill any running ffmpeg process (snapshot mode)
    if (this._videoPreviewProcess) {
      try {
        this._videoPreviewProcess.kill();
      } catch (e) {
        // Ignore
      }
      this._videoPreviewProcess = null;
    }

    debugLog("Stopped video preview");
  }

  /**
   * Get a single frame for snapshot mode (legacy, high CPU usage).
   *
   * This uses ffmpeg to capture from v4l2, which is inefficient but works
   * without the streaming pipeline. Use WebRTC or MJPEG modes for better
   * performance.
   */
  private async handleGetVideoPreviewFrame() {
    if (!this._videoPreviewActive || this._videoPreviewMode !== 'snapshot') {
      return;
    }

    try {
      // Capture a single frame from the v4l2 device using ffmpeg
      // Output as JPEG to stdout, then convert to base64
      const tmpFile = `/tmp/video_preview_${Date.now()}.jpg`;

      await execAsync(
        `ffmpeg -f v4l2 -video_size 640x360 -i ${this._videoPreviewDevice} -vframes 1 -f image2 -y ${tmpFile} 2>/dev/null`,
        { timeout: 2000 }
      );

      // Read the file and convert to base64
      if (fs.existsSync(tmpFile)) {
        const imageBuffer = fs.readFileSync(tmpFile);
        const base64 = imageBuffer.toString('base64');
        const dataUrl = `data:image/jpeg;base64,${base64}`;

        // Get resolution from device
        let resolution = "640x360";
        try {
          const { stdout } = await execAsync(
            `v4l2-ctl -d ${this._videoPreviewDevice} --get-fmt-video 2>/dev/null | grep "Width/Height" | head -1`,
            { timeout: 1000 }
          );
          const match = stdout.match(/(\d+)\/(\d+)/);
          if (match) {
            resolution = `${match[1]}x${match[2]}`;
          }
        } catch (e) {
          // Use default
        }

        // Send frame to webview
        this._panel.webview.postMessage({
          type: 'videoPreviewFrame',
          dataUrl: dataUrl,
          resolution: resolution
        });

        // Clean up temp file
        try {
          fs.unlinkSync(tmpFile);
        } catch (e) {
          // Ignore
        }
      }
    } catch (e: any) {
      // Don't spam errors - just skip this frame
      debugLog(`Video preview frame error: ${e.message}`);
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

  private async loadSlackHistory() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "GetHistory",
        [
          { type: "int32", value: "50" },
          { type: "string", value: "" },
          { type: "string", value: "" },
          { type: "string", value: "" }
        ]
      );

      if (result.success && result.data) {
        // GetHistory returns a JSON array directly
        const messages = Array.isArray(result.data) ? result.data : (result.data.messages || []);
        this._panel.webview.postMessage({
          type: "slackHistory",
          messages: messages,
        });
      } else {
        // Try reading from log file
        const logFile = path.join(os.homedir(), ".config", "aa-workflow", "slack_messages.json");
        if (fs.existsSync(logFile)) {
          const content = fs.readFileSync(logFile, "utf-8");
          const messages = JSON.parse(content);
          this._panel.webview.postMessage({
            type: "slackHistory",
            messages: messages.slice(-50),
          });
        } else {
          this._panel.webview.postMessage({
            type: "slackHistory",
            messages: [],
          });
        }
      }
    } catch (e) {
      this._panel.webview.postMessage({
        type: "slackHistory",
        messages: [],
      });
    }
  }

  private async sendSlackMessage(channel: string, text: string, threadTs: string = "") {
    try {
      if (!channel || !text) {
        vscode.window.showWarningMessage("Please select a channel/user and enter a message");
        return;
      }

      // Send via D-Bus (Slack daemon)
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "SendMessage",
        [
          { type: "string", value: channel },
          { type: "string", value: text },
          { type: "string", value: threadTs || "" }  // thread_ts for replies
        ]
      );

      if (result.success) {
        const replyMsg = threadTs ? "Reply sent successfully" : "Message sent successfully";
        vscode.window.showInformationMessage(replyMsg);
        this._panel.webview.postMessage({
          type: "slackMessageSent",
          success: true,
          isReply: !!threadTs,
        });
        // Refresh history to show the new message
        await this.loadSlackHistory();
      } else {
        vscode.window.showErrorMessage(`Failed to send message: ${result.error || "Unknown error"}`);
        this._panel.webview.postMessage({
          type: "slackMessageSent",
          success: false,
          error: result.error,
        });
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to send message: ${e}`);
      this._panel.webview.postMessage({
        type: "slackMessageSent",
        success: false,
        error: String(e),
      });
    }
  }


  private async refreshSlackChannels() {
    try {
      // Query via D-Bus (Slack daemon)
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "GetMyChannels",
        []
      );

      if (result.success && result.data) {
        const channels = Array.isArray(result.data) ? result.data : (result.data.channels || []);
        this._panel.webview.postMessage({
          type: "slackChannels",
          channels: channels,
        });
      } else {
        this._panel.webview.postMessage({
          type: "slackChannels",
          channels: [],
        });
      }
    } catch (e) {
      this._panel.webview.postMessage({
        type: "slackChannels",
        channels: [],
      });
    }
  }

  private async searchSlackUsers(query: string) {
    try {
      // Search Slack directly via SearchAndCacheUsers (finds users not in local cache)
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "SearchAndCacheUsers",
        [
          { type: "string", value: query },
          { type: "int32", value: "30" }
        ]
      );

      if (result.success && result.data) {
        const users = result.data.results || result.data.users || [];
        this._panel.webview.postMessage({
          type: "slackUsers",
          users: users,
        });
      } else {
        this._panel.webview.postMessage({
          type: "slackUsers",
          users: [],
        });
      }
    } catch (e) {
      this._panel.webview.postMessage({
        type: "slackUsers",
        users: [],
      });
    }
  }

  private async refreshSlackTargets() {
    try {
      // Refresh channels via D-Bus (Slack daemon)
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "GetMyChannels",
        []
      );
      if (result.success && result.data) {
        const channels = Array.isArray(result.data) ? result.data : (result.data.channels || []);
        this._panel.webview.postMessage({
          type: "slackChannels",
          channels: channels,
        });
      }
    } catch (e) {
      console.error("Failed to refresh Slack targets:", e);
    }
  }

  private async searchSlackMessages(query: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "SearchMessages",
        [
          { type: "string", value: query },
          { type: "int32", value: "30" }
        ]
      );
      if (result.success && result.data) {
        this._panel.webview.postMessage({
          type: "slackSearchResults",
          results: result.data.messages || [],
          total: result.data.total || 0,
          remaining: result.data.searches_remaining_today,
          rateLimited: result.data.rate_limited || false,
          error: result.data.error || null,
        });
      } else {
        this._panel.webview.postMessage({
          type: "slackSearchResults",
          results: [],
          error: result.data?.error || "Search failed",
        });
      }
    } catch (e) {
      this._panel.webview.postMessage({
        type: "slackSearchResults",
        results: [],
        error: String(e),
      });
    }
  }

  private async refreshSlackPending() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "GetPending",
        []
      );
      if (result.success) {
        const pending = Array.isArray(result.data) ? result.data : [];
        this._panel.webview.postMessage({
          type: "slackPending",
          pending: pending,
        });
      }
    } catch (e) {
      console.error("Failed to refresh Slack pending:", e);
    }
  }

  private async approveSlackMessage(messageId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "ApproveMessage",
        [{ type: "string", value: messageId }]
      );
      if (result.success) {
        vscode.window.showInformationMessage("Message approved and sent");
        await this.refreshSlackPending();
      } else {
        vscode.window.showErrorMessage(`Failed to approve: ${result.data?.error || "Unknown error"}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to approve: ${e}`);
    }
  }

  private async rejectSlackMessage(messageId: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "RejectMessage",
        [{ type: "string", value: messageId }]
      );
      if (result.success) {
        vscode.window.showInformationMessage("Message rejected");
        await this.refreshSlackPending();
      } else {
        vscode.window.showErrorMessage(`Failed to reject: ${result.data?.error || "Unknown error"}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to reject: ${e}`);
    }
  }

  private async approveAllSlackMessages() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "ApproveAll",
        []
      );
      if (result.success && result.data) {
        const approved = result.data.approved || 0;
        const failed = result.data.failed || 0;
        vscode.window.showInformationMessage(`Approved ${approved} messages${failed > 0 ? `, ${failed} failed` : ""}`);
        await this.refreshSlackPending();
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to approve all: ${e}`);
    }
  }

  private async refreshSlackCache() {
    try {
      vscode.window.showInformationMessage("Refreshing Slack cache from API...");

      // Refresh both channel and user caches
      const [channelResult, userResult] = await Promise.all([
        this.queryDBus(
          "com.aiworkflow.BotSlack",
          "/com/aiworkflow/BotSlack",
          "com.aiworkflow.BotSlack",
          "RefreshChannelCache",
          []
        ),
        this.queryDBus(
          "com.aiworkflow.BotSlack",
          "/com/aiworkflow/BotSlack",
          "com.aiworkflow.BotSlack",
          "RefreshUserCache",
          []
        )
      ]);

      const channelCount = channelResult.data?.channels_cached || 0;
      const userCount = userResult.data?.users_cached || 0;
      const userSkipped = userResult.data?.skipped ? " (cached)" : "";

      vscode.window.showInformationMessage(`Cache refreshed: ${channelCount} channels, ${userCount} users${userSkipped}`);

      // Refresh the UI
      await this.refreshSlackCacheStats();
      await this.loadSlackChannelBrowser("");
      await this.loadSlackUserBrowser("");
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to refresh cache: ${e}`);
    }
  }

  private async refreshSlackCacheStats() {
    try {
      const [channelStats, userStats] = await Promise.all([
        this.queryDBus(
          "com.aiworkflow.BotSlack",
          "/com/aiworkflow/BotSlack",
          "com.aiworkflow.BotSlack",
          "GetChannelCacheStats",
          []
        ),
        this.queryDBus(
          "com.aiworkflow.BotSlack",
          "/com/aiworkflow/BotSlack",
          "com.aiworkflow.BotSlack",
          "GetUserCacheStats",
          []
        )
      ]);

      this._panel.webview.postMessage({
        type: "slackCacheStats",
        channelStats: channelStats.data || {},
        userStats: userStats.data || {},
      });
    } catch (e) {
      console.error("Failed to refresh cache stats:", e);
    }
  }

  private async loadSlackChannelBrowser(query: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "FindChannel",
        [{ type: "string", value: query }]
      );
      if (result.success && result.data) {
        this._panel.webview.postMessage({
          type: "slackChannelBrowser",
          channels: result.data.channels || [],
          count: result.data.count || 0,
        });
      }
    } catch (e) {
      console.error("Failed to load channel browser:", e);
    }
  }

  private async loadSlackCommands() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "GetCommandList",
        []
      );
      if (result.success && result.data) {
        this._panel.webview.postMessage({
          type: "slackCommands",
          commands: result.data.commands || [],
        });
      }
    } catch (e) {
      console.error("Failed to load Slack commands:", e);
    }
  }

  private async sendSlackCommand(command: string, args: Record<string, string>) {
    try {
      // Build the @me command string
      let commandStr = `@me ${command}`;
      for (const [key, value] of Object.entries(args)) {
        if (value) {
          commandStr += ` --${key}="${value}"`;
        }
      }

      // Get the self-DM channel from config or use a default
      const selfDmChannel = ""; // Will send to self-DM

      // Send via D-Bus
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "SendMessage",
        [
          { type: "string", value: selfDmChannel },
          { type: "string", value: commandStr },
          { type: "string", value: "" }
        ]
      );

      if (result.success) {
        vscode.window.showInformationMessage(`Command sent: ${command}`);
        this._panel.webview.postMessage({
          type: "slackCommandSent",
          success: true,
          command: command,
        });
      } else {
        vscode.window.showErrorMessage(`Failed to send command: ${result.error || "Unknown error"}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to send command: ${e}`);
    }
  }

  private async loadSlackConfig() {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "GetConfig",
        []
      );
      if (result.success && result.data) {
        this._panel.webview.postMessage({
          type: "slackConfig",
          config: result.data.config || {},
        });
      }
    } catch (e) {
      console.error("Failed to load Slack config:", e);
    }
  }

  private async setSlackDebugMode(enabled: boolean) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "SetDebugMode",
        [{ type: "string", value: enabled ? "true" : "false" }]
      );
      if (result.success) {
        vscode.window.showInformationMessage(`Debug mode ${enabled ? "enabled" : "disabled"}`);
        this._panel.webview.postMessage({
          type: "slackDebugModeChanged",
          enabled: enabled,
        });
      } else {
        vscode.window.showErrorMessage(`Failed to set debug mode: ${result.error || "Unknown error"}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to set debug mode: ${e}`);
    }
  }

  private async loadSlackUserBrowser(query: string) {
    try {
      const result = await this.queryDBus(
        "com.aiworkflow.BotSlack",
        "/com/aiworkflow/BotSlack",
        "com.aiworkflow.BotSlack",
        "FindUser",
        [{ type: "string", value: query }]
      );
      if (result.success && result.data) {
        this._panel.webview.postMessage({
          type: "slackUserBrowser",
          users: result.data.users || [],
          count: result.data.count || 0,
        });
      }
    } catch (e) {
      console.error("Failed to load user browser:", e);
    }
  }


  // ============================================================================
  // Cron Management
  // ============================================================================

  private async loadCronConfigAsync(): Promise<{ enabled: boolean; timezone: string; jobs: CronJob[]; execution_mode: string } | null> {
    try {
      // Read all config via D-Bus (uses ConfigManager for thread-safe access)
      const configResult = await this.queryDBus(
        "com.aiworkflow.BotCron",
        "/com/aiworkflow/BotCron",
        "com.aiworkflow.BotCron",
        "CallMethod",
        [
          { type: "string", value: "get_config" },
          { type: "string", value: JSON.stringify({ section: "schedules", key: "" }) }
        ]
      );

      // If config fetch failed, return null to preserve cached data
      if (!configResult.success || !configResult.data?.success) {
        debugLog("D-Bus get_config failed, preserving cached cron config");
        return null;
      }

      const schedules = configResult.data.value || {};

      // Get enabled state from D-Bus (uses StateManager)
      const statsResult = await this.queryDBus(
        "com.aiworkflow.BotCron",
        "/com/aiworkflow/BotCron",
        "com.aiworkflow.BotCron",
        "GetStats"
      );

      // If stats fetch failed, return null to preserve cached data
      if (!statsResult.success) {
        debugLog("D-Bus GetStats failed, preserving cached cron config");
        return null;
      }

      const enabled = statsResult.data?.enabled || false;

      return {
        enabled: enabled,
        timezone: schedules.timezone || "UTC",
        jobs: schedules.jobs || [],
        execution_mode: schedules.execution_mode || "claude_cli",
      };
    } catch (e) {
      console.error("Failed to load cron config via D-Bus:", e);
      return null;  // Return null to preserve cached data
    }
  }

  // Synchronous wrapper that returns cached data (for backward compatibility)
  private loadCronConfig(): { enabled: boolean; timezone: string; jobs: CronJob[]; execution_mode: string } {
    // Return cached data if available, otherwise return defaults
    // The async version should be called to refresh the cache
    return this._cachedCronConfig || { enabled: false, timezone: "UTC", jobs: [], execution_mode: "claude_cli" };
  }

  private _cachedCronConfig: { enabled: boolean; timezone: string; jobs: CronJob[]; execution_mode: string } | null = null;

  private loadCronHistory(limit: number = 10): CronExecution[] {
    try {
      if (fs.existsSync(CRON_HISTORY_FILE)) {
        const content = fs.readFileSync(CRON_HISTORY_FILE, "utf-8");
        const history = JSON.parse(content);
        const executions = history.executions || [];
        // Get last N executions and reverse so newest is first
        return executions.slice(-limit).reverse();
      }
    } catch (e) {
      console.error("Failed to load cron history:", e);
    }
    return [];
  }

  private getCronHistoryTotal(): number {
    try {
      if (fs.existsSync(CRON_HISTORY_FILE)) {
        const content = fs.readFileSync(CRON_HISTORY_FILE, "utf-8");
        const history = JSON.parse(content);
        return (history.executions || []).length;
      }
    } catch (e) {
      console.error("Failed to get cron history count:", e);
    }
    return 0;
  }

  private async refreshCronData(historyLimit: number = 10) {
    // Reload cron state from file (cron daemon owns this file)
    this._loadWorkspaceState();

    // Use cron state file as primary source
    let configToSend = this._cronData;
    if (!configToSend || !configToSend.jobs || configToSend.jobs.length === 0) {
      // State file empty, try D-Bus as fallback
      const cronConfig = await this.loadCronConfigAsync();
      if (cronConfig !== null) {
        this._cachedCronConfig = cronConfig;
        configToSend = cronConfig;
      }
    }
    // Final fallback to defaults
    configToSend = configToSend || { enabled: false, timezone: "UTC", jobs: [], execution_mode: "claude_cli" };

    const cronHistory = this.loadCronHistory(historyLimit);
    const totalHistory = this.getCronHistoryTotal();

    this._panel.webview.postMessage({
      type: "cronData",
      config: configToSend,
      history: cronHistory,
      totalHistory: totalHistory,
      currentLimit: historyLimit,
    });
  }

  private async toggleScheduler() {
    console.log("[CommandCenter] toggleScheduler called");
    try {
      // Get current state from D-Bus (thread-safe), fall back to cached or workspace state
      const cronConfig = await this.loadCronConfigAsync();
      const configToUse = cronConfig || this._cachedCronConfig || this._cronData || { enabled: false, timezone: "UTC", jobs: [], execution_mode: "claude_cli" };
      const currentState = configToUse.enabled;
      const newState = !currentState;

      console.log("[CommandCenter] Current schedules.enabled:", currentState, "-> toggling to:", newState);

      // Use D-Bus to toggle scheduler state (uses StateManager for thread-safe writes)
      const result = await this.queryDBus(
        "com.aiworkflow.BotCron",
        "/com/aiworkflow/BotCron",
        "com.aiworkflow.BotCron",
        "CallMethod",
        [
          { type: "string", value: "toggle_scheduler" },
          { type: "string", value: JSON.stringify({ enabled: newState }) }
        ]
      );

      if (result.success) {
        console.log("[CommandCenter] D-Bus toggle_scheduler result:", result.data);

        vscode.window.showInformationMessage(
          `Scheduler ${newState ? "enabled ✅" : "disabled ⏸️"}. ${newState ? "Jobs will start running within 30 seconds." : "Jobs are paused."}`
        );

        // Update the UI
        console.log("[CommandCenter] Sending schedulerToggled message with enabled:", newState);
        this._panel.webview.postMessage({
          type: "schedulerToggled",
          enabled: newState,
        });

        await this.refreshCronData();
      } else {
        console.error("[CommandCenter] D-Bus toggle_scheduler failed:", result.error);
        vscode.window.showErrorMessage(`Failed to toggle scheduler via D-Bus: ${result.error}`);
      }
    } catch (e) {
      console.error("[CommandCenter] toggleScheduler error:", e);
      vscode.window.showErrorMessage(`Failed to toggle scheduler: ${e}`);
    }
  }

  private async toggleCronJob(jobName: string, enabled: boolean) {
    try {
      console.log("[CommandCenter] toggleCronJob called:", jobName, "->", enabled);

      // Use D-Bus to toggle job state (uses StateManager for thread-safe writes)
      const result = await this.queryDBus(
        "com.aiworkflow.BotCron",
        "/com/aiworkflow/BotCron",
        "com.aiworkflow.BotCron",
        "CallMethod",
        [
          { type: "string", value: "toggle_job" },
          { type: "string", value: JSON.stringify({ job_name: jobName, enabled: enabled }) }
        ]
      );

      if (result.success) {
        console.log("[CommandCenter] D-Bus toggle_job result:", result.data);
        vscode.window.showInformationMessage(
          `Cron job "${jobName}" ${enabled ? "enabled" : "disabled"}`
        );
        await this.refreshCronData();
      } else {
        console.error("[CommandCenter] D-Bus toggle_job failed:", result.error);
        vscode.window.showErrorMessage(`Failed to toggle cron job via D-Bus: ${result.error}`);
      }
    } catch (e) {
      console.error("[CommandCenter] toggleCronJob error:", e);
      vscode.window.showErrorMessage(`Failed to toggle cron job: ${e}`);
    }
  }

  private async runCronJobNow(jobName: string) {
    try {
      // Send command to Cursor chat to run the skill
      const cronConfig = await this.loadCronConfigAsync();
      const configToUse = cronConfig || this._cachedCronConfig || this._cronData || { enabled: false, timezone: "UTC", jobs: [], execution_mode: "claude_cli" };
      const job = configToUse.jobs.find((j: any) => j.name === jobName);

      if (job) {
        const command = `cron_run_now("${jobName}")`;
        await vscode.env.clipboard.writeText(command);
        vscode.window.showInformationMessage(
          `Command copied to clipboard: ${command}\nPaste in Cursor chat to run.`
        );
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Failed to run cron job: ${e}`);
    }
  }

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

  private loadToolModules(): ToolModule[] {
    const modules: ToolModule[] = [];
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      path.join(os.homedir(), "src", "redhat-ai-workflow");
    const toolModulesDir = path.join(workspaceRoot, "tool_modules");

    try {
      if (!fs.existsSync(toolModulesDir)) return modules;

      const dirs = fs.readdirSync(toolModulesDir).filter(d =>
        d.startsWith("aa_") && fs.statSync(path.join(toolModulesDir, d)).isDirectory()
      );

      for (const dir of dirs) {
        const moduleName = dir.replace("aa_", "");
        const srcDir = path.join(toolModulesDir, dir, "src");

        if (!fs.existsSync(srcDir)) continue;

        const tools: ToolDefinition[] = [];
        const pyFiles = fs.readdirSync(srcDir).filter(f => f.endsWith(".py"));

        for (const pyFile of pyFiles) {
          const filePath = path.join(srcDir, pyFile);
          try {
            const content = fs.readFileSync(filePath, "utf-8");

            // Find tool registrations: @registry.tool() followed by async def
            // Pattern handles:
            // 1. Optional decorators between @registry.tool() and async def (like @auto_heal())
            // 2. Multi-line function signatures with type hints
            // 3. Docstrings that may span multiple lines
            const toolMatches = content.matchAll(/@registry\.tool\(\)\s*\n(?:[ \t]*@[^\n]+\n)*[ \t]*async def (\w+)\([^)]*\)[^:]*:[ \t]*\n[ \t]*"""([\s\S]*?)"""/g);

            for (const match of toolMatches) {
              const toolName = match[1];
              // Get first non-empty line of docstring as description
              const docLines = match[2].split("\n").map(l => l.trim()).filter(l => l && !l.startsWith("Args:") && !l.startsWith("Returns:"));
              let description = docLines[0] || "";
              // Clean up description
              if (description.length > 100) {
                description = description.substring(0, 97) + "...";
              }
              tools.push({ name: toolName, description, module: moduleName });
            }
          } catch {
            // Skip files that can't be read
          }
        }

        if (tools.length > 0) {
          modules.push({
            name: moduleName,
            displayName: this._formatModuleName(moduleName),
            description: this._getModuleDescription(moduleName),
            toolCount: tools.length,
            tools: tools.sort((a, b) => a.name.localeCompare(b.name)),
          });
        }
      }
    } catch (e) {
      console.error("Failed to load tool modules:", e);
    }

    return modules.sort((a, b) => a.displayName.localeCompare(b.displayName));
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
   * Get cached personas or load them if not cached.
   */
  private getPersonas(): Persona[] {
    if (!this._personasCache) {
      this._personasCache = this.loadPersonas();
    }
    return this._personasCache;
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

  private loadPersonas(): Persona[] {
    const personas: Persona[] = [];
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
      path.join(os.homedir(), "src", "redhat-ai-workflow");
    const personasDir = path.join(workspaceRoot, "personas");

    try {
      if (!fs.existsSync(personasDir)) return personas;

      // Auto-discover all .yaml files
      const files = fs.readdirSync(personasDir).filter(f => f.endsWith(".yaml"));

      for (const file of files) {
        try {
          const content = fs.readFileSync(path.join(personasDir, file), "utf-8");
          const fileName = file.replace(".yaml", "");

          const nameMatch = content.match(/^name:\s*(\w+)/m);
          const descMatch = content.match(/^description:\s*(.+)/m);
          const personaFileMatch = content.match(/^persona:\s*(.+)/m);

          // Determine persona type/category
          const isSlim = fileName.includes("-slim");
          const isInternal = ["core", "universal"].includes(fileName);
          const isAgent = fileName === "slack"; // Slack is an autonomous agent, not a user persona

          // Extract tools list - handles blank lines and comments within the section
          const toolsMatch = content.match(/^tools:\s*\n((?:(?:\s+-\s+[\w_]+\s*(?:#[^\n]*)?|\s*#[^\n]*|\s*)\n)*)/m);
          const tools: string[] = [];
          if (toolsMatch) {
            const toolLines = toolsMatch[1].match(/^\s+-\s+([\w_]+)/gm);
            if (toolLines) {
              tools.push(...toolLines.map(t => t.replace(/^\s+-\s+/, "").trim()));
            }
          }

          // Extract skills list - handles blank lines and comments within the section
          const skills: string[] = [];
          const skillsStart = content.indexOf("skills:");
          if (skillsStart !== -1) {
            // Get everything after 'skills:'
            const afterSkills = content.substring(skillsStart + 7);
            // Find the next top-level key (line starting with letter, no indent)
            const nextKeyMatch = afterSkills.match(/\n[a-z_]+:/);
            const skillsSection = nextKeyMatch
              ? afterSkills.substring(0, nextKeyMatch.index)
              : afterSkills;
            // Extract skill names from the section
            const skillLines = skillsSection.match(/^\s+-\s+([\w_]+)/gm);
            if (skillLines) {
              skills.push(...skillLines.map(s => s.replace(/^\s+-\s+/, "").trim()));
            }
          }

          // Get the display name (use filename if no name field)
          const displayName = nameMatch ? nameMatch[1] : fileName;

          // Calculate actual tool count by summing tools in each module
          const toolCount = tools.reduce((sum, moduleName) => {
            return sum + this.countToolsInModule(moduleName);
          }, 0);

          personas.push({
            name: displayName,
            fileName: fileName,
            description: descMatch ? descMatch[1].trim() : "",
            tools,
            toolCount,
            skills,
            personaFile: personaFileMatch ? personaFileMatch[1].trim() : undefined,
            isSlim,
            isInternal,
            isAgent,
          });
        } catch {
          // Skip invalid files
        }
      }
    } catch (e) {
      console.error("Failed to load personas:", e);
    }

    // Sort: main personas first, then slim variants, then internal/agents
    return personas.sort((a, b) => {
      // Internal and agents go last
      if (a.isInternal !== b.isInternal) return a.isInternal ? 1 : -1;
      if (a.isAgent !== b.isAgent) return a.isAgent ? 1 : -1;
      // Slim variants after their main persona
      if (a.isSlim !== b.isSlim) return a.isSlim ? 1 : -1;
      // Alphabetical within groups
      return a.name.localeCompare(b.name);
    });
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

  private _loadWorkspaceState(): void {
    // Load state from per-service state files
    // Each service writes its own file, we read and merge them here

    // 1. Load session state (workspaces, sessions)
    try {
      if (fs.existsSync(SESSION_STATE_FILE)) {
        const content = fs.readFileSync(SESSION_STATE_FILE, "utf8");
        const sessionState = JSON.parse(content);
        this._workspaceState = sessionState.workspaces || {};
        this._workspaceCount = sessionState.workspace_count || Object.keys(this._workspaceState || {}).length;
        debugLog(`Loaded session state: ${this._workspaceCount} workspaces, ${sessionState.session_count || 0} sessions`);
      } else {
        // Fallback to legacy file
        this._loadLegacySessionState();
      }
    } catch (error) {
      debugLog(`Error loading session state: ${error}`);
      this._loadLegacySessionState();
    }

    // 2. Load meet state
    try {
      if (fs.existsSync(MEET_STATE_FILE)) {
        const content = fs.readFileSync(MEET_STATE_FILE, "utf8");
        this._meetData = JSON.parse(content);
        debugLog(`Loaded meet state: ${this._meetData.upcomingMeetings?.length || 0} upcoming`);
      } else {
        this._meetData = {};
      }
    } catch (error) {
      debugLog(`Error loading meet state: ${error}`);
      this._meetData = {};
    }

    // 3. Load cron state
    try {
      if (fs.existsSync(CRON_STATE_FILE)) {
        const content = fs.readFileSync(CRON_STATE_FILE, "utf8");
        this._cronData = JSON.parse(content);
        debugLog(`Loaded cron state: ${this._cronData.jobs?.length || 0} jobs`);
      } else {
        this._cronData = {};
      }
    } catch (error) {
      debugLog(`Error loading cron state: ${error}`);
      this._cronData = {};
    }

    // 4. Load ollama/slack from legacy file
    // NOTE: Services are now loaded via D-Bus in _refreshServicesViaDBus(), not from file
    // We preserve existing this._services data to avoid overwriting D-Bus results
    try {
      if (fs.existsSync(WORKSPACE_STATES_FILE)) {
        const content = fs.readFileSync(WORKSPACE_STATES_FILE, "utf8");
        const parsed = JSON.parse(content);
        // Don't overwrite services - they come from D-Bus now
        // this._services = parsed.services || {};
        this._ollama = parsed.ollama || {};
        this._slackChannels = parsed.slack_channels || [];
      } else {
        // Don't reset services - they come from D-Bus
        this._ollama = {};
        this._slackChannels = [];
      }
    } catch (error) {
      // Don't reset services - they come from D-Bus
      this._ollama = {};
      this._slackChannels = [];
    }

    // Sprint state is loaded separately via _loadSprintFromFile()
    this._sprintIssues = [];
    this._sprintIssuesUpdated = "";
  }

  private _loadLegacySessionState(): void {
    // Fallback to legacy workspace_states.json for session data
    try {
      if (fs.existsSync(WORKSPACE_STATES_FILE)) {
        const content = fs.readFileSync(WORKSPACE_STATES_FILE, "utf8");
        const parsed = JSON.parse(content);
        if (parsed.workspaces) {
          this._workspaceState = parsed.workspaces as WorkspaceExportedState;
          this._workspaceCount = parsed.workspace_count || Object.keys(this._workspaceState || {}).length;
        } else {
          this._workspaceState = parsed as WorkspaceExportedState;
          this._workspaceCount = Object.keys(this._workspaceState || {}).length;
        }
        debugLog(`Loaded legacy session state: ${this._workspaceCount} workspaces`);
      } else {
        this._workspaceState = null;
        this._workspaceCount = 0;
      }
    } catch (error) {
      this._workspaceState = null;
      this._workspaceCount = 0;
    }
  }

  private _setupWorkspaceWatcher(): void {
    try {
      const dir = AA_CONFIG_DIR;
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }

      // Watch for changes to any state file
      const stateFiles = new Set([
        "session_state.json",
        "sprint_state_v2.json",
        "meet_state.json",
        "cron_state.json",
        "workspace_states.json",  // Legacy fallback
      ]);

      this._workspaceWatcher = fs.watch(dir, (eventType, filename) => {
        if (filename && stateFiles.has(filename)) {
          // Debounce is now handled by RefreshCoordinator
          // Just load state and dispatch - coordinator handles the rest
          if (this._workspaceWatcherDebounce) {
            clearTimeout(this._workspaceWatcherDebounce);
          }
          this._workspaceWatcherDebounce = setTimeout(() => {
            debugLog(`State file changed: ${filename} (${eventType})`);
            this._loadWorkspaceState();
            // Use LOW priority for file watcher updates (background)
            this._dispatchAllUIUpdates(RefreshPriority.LOW);
          }, 100); // Reduced debounce since coordinator handles it
        }
      });
      debugLog("State file watcher set up");
    } catch (error) {
      debugLog(`Error setting up workspace watcher: ${error}`);
    }
  }

  /**
   * Dispatch updates to ALL UI sections from unified state.
   * Called when workspace_states.json changes.
   *
   * Uses the RefreshCoordinator for centralized state management,
   * debouncing, and change detection to eliminate UI flicker.
   */
  private _dispatchAllUIUpdates(priority: RefreshPriority = RefreshPriority.NORMAL): void {
    if (!this._refreshCoordinator) {
      debugLog("RefreshCoordinator not initialized, skipping dispatch");
      return;
    }

    // Collect all state updates
    const updates: Array<{ section: StateSection; data: any }> = [];

    // Services
    updates.push({
      section: "services",
      data: {
        list: this._formatServicesForUI(),
        mcp: this._services.mcp || { running: false }
      }
    });

    // Ollama
    updates.push({
      section: "ollama",
      data: { status: this._ollama }
    });

    // Cron
    updates.push({
      section: "cron",
      data: {
        enabled: this._cronData.enabled || false,
        timezone: this._cronData.timezone || "UTC",
        jobs: this._cronData.jobs || [],
        execution_mode: this._cronData.execution_mode || "claude_cli",
        history: this._cronData.history || [],
        total_history: this._cronData.total_history || 0
      }
    });

    // Slack
    updates.push({
      section: "slack",
      data: { channels: this._slackChannels }
    });

    // Sprint (badge only for background updates)
    const sprintState = loadSprintState();
    const pendingCount = (sprintState.issues || []).filter(
      (i: any) => i.approvalStatus === "pending" || i.approvalStatus === "waiting"
    ).length;
    updates.push({
      section: "sprint",
      data: {
        issues: sprintState.issues || [],
        pendingCount,
        totalIssues: sprintState.issues?.length || 0
        // Note: renderedHtml is NOT included for background updates to avoid expensive regeneration
      }
    });

    // Meetings
    const meetBotState = loadMeetBotState(this._meetData);
    updates.push({
      section: "meetings",
      data: {
        currentMeeting: meetBotState.currentMeeting,
        currentMeetings: meetBotState.currentMeetings || [],
        upcomingMeetings: meetBotState.upcomingMeetings || [],
        renderedUpcomingHtml: getUpcomingMeetingsHtml(meetBotState)
      }
    });

    // Performance
    const performanceState = loadPerformanceState();
    updates.push({
      section: "performance",
      data: { overall_percentage: performanceState.overall_percentage || 0 }
    });

    // Sessions (workspaces)
    if (this._workspaceState) {
      updates.push({
        section: "sessions",
        data: {
          workspaces: this._workspaceState.workspaces || [],
          totalCount: this._workspaceCount
        }
      });
    }

    // Overview stats
    const stats = this.loadStats();
    const workflowStatus = this._dataProvider.getStatus();
    const currentWork = this.loadCurrentWork();
    const memoryHealth = this.getMemoryHealth();
    const today = new Date().toISOString().split("T")[0];
    const todayStats = stats?.daily?.[today] || { tool_calls: 0, skill_executions: 0 };
    const session = stats?.current_session || { tool_calls: 0, skill_executions: 0, memory_ops: 0 };
    const lifetime = stats?.lifetime || { tool_calls: 0, tool_successes: 0 };
    const toolSuccessRate = lifetime.tool_calls > 0
      ? Math.round((lifetime.tool_successes / lifetime.tool_calls) * 100)
      : 100;

    updates.push({
      section: "overview",
      data: {
        stats,
        todayStats,
        session,
        toolSuccessRate,
        workflowStatus,
        currentWork,
        workspaceCount: this._workspaceCount,
        memoryHealth
      }
    });

    // Send all updates through the coordinator
    const changedSections = this._refreshCoordinator.updateSections(updates, priority);

    if (changedSections.length > 0) {
      debugLog(`RefreshCoordinator: ${changedSections.length} sections changed: ${changedSections.join(", ")}`);
    }

    // Also update workspaces tab (has its own rendering logic)
    this._updateWorkspacesTab();
  }

  /**
   * Format services data for UI consumption.
   */
  private _formatServicesForUI(): any[] {
    const serviceNames = ["slack", "cron", "meet", "sprint", "video"];
    return serviceNames.map(name => {
      const svc = this._services[name] || {};
      return {
        name: name === "slack" ? "Slack Agent" :
              name === "cron" ? "Cron Scheduler" :
              name === "meet" ? "Meet Bot" :
              name === "sprint" ? "Sprint Bot" : "Video Bot",
        ...svc,
      };
    });
  }

  /**
   * Background refresh - reloads data from cache file and queries D-Bus for service status.
   * Called every 10 seconds by the interval timer.
   *
   * NOTE: The UI does NOT spawn sync processes. The sprint bot service
   * (cron job) handles periodic updates to workspace_states.json.
   * The UI only reads from the cache file, but queries D-Bus directly for service status.
   */
  private _backgroundSync(): void {
    // Clear personas cache to ensure fresh data on next access
    this._personasCache = null;

    // Just reload from file and update UI - no sync process spawning
    this._loadWorkspaceState();
    this.update(false);
    this.getInferenceStats();

    // Also refresh service status via D-Bus (services don't write to workspace_states.json)
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
        };
        const key = keyMap[service.service];
        if (key) {
          this._services[key] = { running: false, error: "Service not available" };
        }
      }
    }

    debugLog(`_refreshServicesViaDBus: Final this._services = ${JSON.stringify(this._services)}`);
    // Dispatch UI update with new service status
    this._dispatchAllUIUpdates(RefreshPriority.LOW);
  }

  /**
   * Refresh sessions from cache file.
   *
   * NOTE: The UI does NOT spawn sync processes. The cron service
   * handles periodic updates to workspace_states.json.
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
          <div style="font-size: 0.8rem; margin-top: 8px;">
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
              <th style="width: 3%;"></th>
              <th style="text-align: left; width: 22%;">Name</th>
              <th style="width: 14%;">Project</th>
              <th style="width: 12%;">Persona</th>
              <th style="width: 12%;">Issue</th>
              <th style="width: 8%;">Last Active</th>
              <th style="width: 5%;">Tools</th>
              <th style="width: 5%;">Skills</th>
              <th style="width: 14%;">Actions</th>
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
              const isDynamic = (session.dynamic_tool_count ?? 0) > 0;
              const toolCount = session.tool_count ?? session.static_tool_count ?? (session as any).active_tools?.length ?? 0;
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
                <td style="text-align: left;">
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
          <div style="font-size: 0.8rem; margin-top: 8px;">
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
    const isDynamic = (session.dynamic_tool_count ?? 0) > 0;
    const toolCount = session.tool_count ?? session.static_tool_count ?? session.active_tools?.length ?? 0;
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
    const toolCount = activeSession?.tool_count ?? activeSession?.active_tools?.length ?? 0;
    const persona = activeSession?.persona || 'developer';

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

      // Open Quick Open with the chat name
      const searchQuery = chatName ? `chat:${chatName}` : 'chat:';
      await vscode.commands.executeCommand('workbench.action.quickOpen', searchQuery);

      // Auto-press Enter after a short delay to select the first result
      await sleep(250);
      sendEnter();

      if (chatName) {
        console.log(`[CommandCenter] Opening chat: "${chatName}"`);
      }

    } catch (error) {
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
      const result = await this.queryDBus(
        "com.aiworkflow.BotSession",
        "/com/aiworkflow/BotSession",
        "com.aiworkflow.BotSession",
        "CallMethod",
        [
          { type: "string", value: "search_chats" },
          { type: "string", value: JSON.stringify([query, 20]) }
        ]
      );

      if (result.success && result.data) {
        const searchResult = typeof result.data === "string" ? JSON.parse(result.data) : result.data;
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
      const result = await this.queryDBus(
        "com.aiworkflow.BotSession",
        "/com/aiworkflow/BotSession",
        "com.aiworkflow.BotSession",
        "CallMethod",
        [
          { type: "string", value: "refresh_now" },
          { type: "string", value: "[]" }
        ]
      );

      if (result.success) {
        debugLog("Triggered immediate refresh via D-Bus");
        // The daemon will update workspace_states.json, and our file watcher will pick it up
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
      // Remove from local state
      delete this._workspaceState[uri];
      this._workspaceCount = Object.keys(this._workspaceState).length;

      // Update the JSON file
      try {
        const exportData = {
          version: 1,
          exported_at: new Date().toISOString(),
          workspace_count: this._workspaceCount,
          workspaces: this._workspaceState,
        };
        fs.writeFileSync(WORKSPACE_STATES_FILE, JSON.stringify(exportData, null, 2));
        vscode.window.showInformationMessage(`Removed workspace: ${project}`);
      } catch (error) {
        vscode.window.showErrorMessage(`Failed to save workspace state: ${error}`);
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
    try {
      const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ||
        path.join(os.homedir(), "src", "redhat-ai-workflow");
      const personasDir = path.join(workspaceRoot, "personas");

      // Try to read the active agent from memory
      const memoryDir = getMemoryDir();
      const currentWorkPath = path.join(memoryDir, "state", "current_work.yaml");

      let agentName = "developer"; // Default

      if (fs.existsSync(currentWorkPath)) {
        const content = fs.readFileSync(currentWorkPath, "utf-8");
        const agentMatch = content.match(/active_agent:\s*(\w+)/);
        if (agentMatch) agentName = agentMatch[1];
      }

      // Load the agent's tool list
      const agentFile = path.join(personasDir, `${agentName}.yaml`);
      if (fs.existsSync(agentFile)) {
        const content = fs.readFileSync(agentFile, "utf-8");
        const toolsMatch = content.match(/tools:\s*\n((?:\s+-\s+\w+\s*(?:#[^\n]*)?\n)+)/);
        if (toolsMatch) {
          const tools = toolsMatch[1].match(/^\s+-\s+(\w+)/gm)?.map(t => t.replace(/^\s+-\s+/, "").trim()) || [];
          return { name: agentName, tools };
        }
      }

      return { name: agentName, tools: [] };
    } catch (e) {
      return { name: "unknown", tools: [] };
    }
  }

  // ============================================================================
  // Update / Render
  // ============================================================================

  public async update(forceFullRender: boolean = false) {
    // Clear personas cache to ensure fresh data
    this._personasCache = null;

    const stats = this.loadStats();
    const workflowStatus = this._dataProvider.getStatus();
    const currentWork = this.loadCurrentWork();
    const skills = this.loadSkillsList();
    const memoryHealth = this.getMemoryHealth();
    const memoryFiles = this.loadMemoryFiles();
    const vectorStats = this.loadVectorStats();
    // Use cron state file as primary source (cron daemon owns this file)
    // Only fall back to D-Bus if state file is empty/missing
    let cronConfig = this._cronData;
    if (!cronConfig || !cronConfig.jobs || cronConfig.jobs.length === 0) {
      // State file empty, try D-Bus as fallback
      const cronConfigResult = await this.loadCronConfigAsync();
      if (cronConfigResult !== null) {
        this._cachedCronConfig = cronConfigResult;
        cronConfig = cronConfigResult;
      }
    }
    // Final fallback to defaults
    cronConfig = cronConfig || { enabled: false, timezone: "UTC", jobs: [], execution_mode: "claude_cli" };
    const cronHistory = this.loadCronHistory();
    const toolModules = this.loadToolModules();
    const activeAgent = this.getActiveAgent();
    const personas = this.loadPersonas();
    const meetBotState = loadMeetBotState(this._meetData);
    const sprintState = loadSprintState();
    const sprintHistory = loadSprintHistory();
    const toolGapRequests = loadToolGapRequests();
    const performanceState = loadPerformanceState();

    // On first render or forced, do full HTML render
    if (forceFullRender || !this._panel.webview.html) {
      const html = this._getHtmlForWebview(
        stats,
        workflowStatus,
        currentWork,
        skills,
        memoryHealth,
        memoryFiles,
        vectorStats,
        cronConfig,
        cronHistory,
        toolModules,
        activeAgent,
        personas,
        meetBotState,
        sprintState,
        sprintHistory,
        toolGapRequests,
        performanceState
      );
      // Debug: Check if template literals are being evaluated
      if (html.includes('${JSON.stringify')) {
        console.error('[CommandCenter] BUG: Template literals not evaluated! HTML contains literal ${JSON.stringify}');
        console.error('[CommandCenter] First occurrence at:', html.indexOf('${JSON.stringify'));
      }
      // Debug: Log a snippet of the script section to verify it's correct
      const scriptStart = html.indexOf('<script nonce=');
      const scriptSnippet = html.substring(scriptStart, scriptStart + 500);
      console.log('[CommandCenter] Script section preview:', scriptSnippet.substring(0, 300));
      this._panel.webview.html = html;
    } else {
      // For subsequent updates, just send data via postMessage to preserve UI state
      // Calculate derived values for the update
      const today = new Date().toISOString().split("T")[0];
      const todayStats = stats?.daily?.[today] || { tool_calls: 0, skill_executions: 0 };
      const session = stats?.current_session || { tool_calls: 0, skill_executions: 0, memory_ops: 0 };
      const lifetime = stats?.lifetime || { tool_calls: 0, tool_successes: 0 };
      const toolSuccessRate = lifetime.tool_calls > 0
        ? Math.round((lifetime.tool_successes / lifetime.tool_calls) * 100)
        : 100;

      this._panel.webview.postMessage({
        type: "dataUpdate",
        stats,
        todayStats,
        session,
        toolSuccessRate,
        workflowStatus,
        currentWork,
        workspaceCount: this._workspaceCount,
        memoryHealth,
        cronConfig,
        cronHistory,
      });
    }
  }

  private _formatNumber(num: number): string {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
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

  // ============================================================================
  // HTML Generation
  // ============================================================================

  private _getHtmlForWebview(
    stats: AgentStats | null,
    workflowStatus: any,
    currentWork: {
      activeIssue: any;
      activeMR: any;
      followUps: any[];
      sprintIssues: any[];
      activeRepo: string | null;
      totalActiveIssues: number;
      totalActiveMRs: number;
      allActiveIssues: { key: string; project: string; workspace: string }[];
      allActiveMRs: { id: string; project: string; workspace: string }[];
    },
    skills: SkillDefinition[],
    memoryHealth: { totalSize: string; sessionLogs: number; lastSession: string; patterns: number },
    memoryFiles: { state: string[]; learned: string[]; sessions: string[]; knowledge: { project: string; persona: string; confidence: number }[] },
    vectorStats: { projects: any[]; totals: { indexedCount: number; totalChunks: number; totalFiles: number; totalSize: string; totalSearches: number; watchersActive: number } },
    cronConfig: { enabled: boolean; timezone: string; jobs: CronJob[]; execution_mode: string },
    cronHistory: CronExecution[],
    toolModules: ToolModule[],
    activeAgent: { name: string; tools: string[] },
    personas: Persona[],
    meetBotState: MeetBotState,
    sprintState: SprintState,
    sprintHistory: any[],
    toolGapRequests: any[],
    performanceState: PerformanceState
  ): string {
    const nonce = getNonce();

    const lifetime = stats?.lifetime || {
      tool_calls: 0,
      tool_successes: 0,
      tool_failures: 0,
      skill_executions: 0,
      skill_successes: 0,
      skill_failures: 0,
      memory_reads: 0,
      memory_writes: 0,
      lines_written: 0,
      sessions: 0,
    };

    const session = stats?.current_session || {
      started: "",
      tool_calls: 0,
      skill_executions: 0,
      memory_ops: 0,
    };

    const today = new Date().toISOString().split("T")[0];
    const todayStats = stats?.daily?.[today] || {
      tool_calls: 0,
      skill_executions: 0,
    };

    const toolSuccessRate = lifetime.tool_calls > 0
      ? Math.round((lifetime.tool_successes / lifetime.tool_calls) * 100)
      : 100;

    const skillSuccessRate = lifetime.skill_executions > 0
      ? Math.round((lifetime.skill_successes / lifetime.skill_executions) * 100)
      : 100;

    // Get historical daily stats (last 7 days)
    const dailyHistory: Array<{date: string; tool_calls: number; skill_executions: number; sessions: number; memory_ops: number}> = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dateKey = d.toISOString().split("T")[0];
      const dayStats = stats?.daily?.[dateKey];
      dailyHistory.push({
        date: dateKey,
        tool_calls: dayStats?.tool_calls || 0,
        skill_executions: dayStats?.skill_executions || 0,
        sessions: dayStats?.sessions || 0,
        memory_ops: (dayStats?.memory_reads || 0) + (dayStats?.memory_writes || 0),
      });
    }
    const maxToolCalls = Math.max(...dailyHistory.map(d => d.tool_calls), 1);

    // Group skills by category
    const skillsByCategory: Record<string, SkillDefinition[]> = {};
    for (const skill of skills) {
      const cat = skill.category || "general";
      if (!skillsByCategory[cat]) skillsByCategory[cat] = [];
      skillsByCategory[cat].push(skill);
    }

    // Calculate totals for tab badges
    const totalTools = toolModules.reduce((sum, m) => sum + m.toolCount, 0);
    const totalSkills = skills.length;
    const totalPersonas = personas.filter(p => !p.isInternal && !p.isSlim).length;

    // Check service status for services tab indicator
    // Include: D-Bus services + MCP server + Ollama instances
    const servicesList = this._formatServicesForUI();
    const runningServices = servicesList.filter(s => s.running).length;

    // Count MCP as a service
    const mcpRunning = this._services.mcp?.running ? 1 : 0;

    // Count Ollama instances (from this._ollama or check cache)
    const ollamaInstances = ["npu", "igpu", "nvidia", "cpu"];
    const ollamaRunning = ollamaInstances.filter(name => this._ollama[name]?.available).length;

    // Total: D-Bus services + MCP + 4 Ollama instances
    const totalServices = servicesList.length + 1 + ollamaInstances.length;
    const totalRunning = runningServices + mcpRunning + ollamaRunning;
    const offlineCount = totalServices - totalRunning;

    // Color scheme: green = all online, orange = 1-2 offline (degraded), red = 3+ offline
    const servicesStatusColor = offlineCount === 0 ? 'status-green' : offlineCount < 3 ? 'status-yellow' : 'status-red';
    const servicesStatusIcon = offlineCount === 0 ? '●' : offlineCount < 3 ? '◐' : '○';

    return `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}' 'unsafe-inline'; img-src ${this._panel.webview.cspSource} https: data:; connect-src ws://localhost:* wss://localhost:*;">
      <title>AI Workflow Command Center</title>
      <style>
        :root {
          --bg-primary: var(--vscode-editor-background);
          --bg-secondary: var(--vscode-sideBar-background);
          --bg-card: var(--vscode-editorWidget-background);
          --text-primary: var(--vscode-editor-foreground);
          --text-secondary: var(--vscode-descriptionForeground);
          --border: var(--vscode-widget-border);
          --accent: var(--vscode-button-background);
          --accent-hover: var(--vscode-button-hoverBackground);
          --success: #10b981;
          --warning: #f59e0b;
          --error: #ef4444;
          --info: #3b82f6;
          --purple: #8b5cf6;
          --cyan: #06b6d4;
          --pink: #ec4899;
          --orange: #f97316;
          --redhat: #EE0000;
        }

        * {
          margin: 0;
          padding: 0;
          box-sizing: border-box;
        }

        body {
          font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
          background: var(--bg-primary);
          color: var(--text-primary);
          line-height: 1.6;
          min-height: 100vh;
          display: flex;
          flex-direction: column;
        }

        .main-content {
          flex: 1;
        }

        /* ============================================ */
        /* Header with Agent Avatar */
        /* ============================================ */
        .header {
          display: flex;
          align-items: center;
          gap: 20px;
          padding: 20px 24px;
          background: linear-gradient(135deg,
            rgba(139, 92, 246, 0.1) 0%,
            rgba(6, 182, 212, 0.1) 50%,
            rgba(236, 72, 153, 0.05) 100%);
          border-bottom: 1px solid var(--border);
          flex-shrink: 0; /* Don't shrink the header */
        }

        .agent-avatar {
          position: relative;
          width: 70px;
          height: 85px;
          flex-shrink: 0;
        }

        .agent-hat {
          position: absolute;
          top: 0;
          left: 50%;
          transform: translateX(-50%);
          width: 55px;
          height: 30px;
          z-index: 10;
        }

        .agent-ring {
          position: absolute;
          top: 15px;
          left: 0;
          right: 0;
          height: 70px;
          border-radius: 50%;
          border: 2px solid transparent;
          background: linear-gradient(var(--bg-primary), var(--bg-primary)) padding-box,
                      conic-gradient(from 0deg, var(--purple), var(--cyan), var(--pink), var(--purple)) border-box;
          animation: spin 4s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }

        .agent-body {
          position: absolute;
          top: 20px;
          left: 5px;
          right: 5px;
          height: 60px;
          border-radius: 50%;
          background: linear-gradient(145deg, var(--bg-card), var(--bg-secondary));
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 28px;
        }

        .agent-status {
          position: absolute;
          bottom: 10px;
          right: 0;
          width: 14px;
          height: 14px;
          border-radius: 50%;
          background: var(--success);
          border: 2px solid var(--bg-primary);
          box-shadow: 0 0 8px var(--success);
        }

        .header-info {
          flex: 1;
        }

        .header-title {
          font-size: 1.4rem;
          font-weight: 700;
          margin-bottom: 4px;
        }

        .header-subtitle {
          font-size: 0.85rem;
          color: var(--text-secondary);
        }

        .header-stats {
          display: flex;
          gap: 24px;
        }

        .header-stat {
          text-align: center;
        }

        .header-stat-value {
          font-size: 1.2rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .header-stat-label {
          font-size: 0.7rem;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        /* ============================================ */
        /* Tabs - Compact Vertical Layout */
        /* ============================================ */
        .tabs {
          display: flex;
          gap: 0;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border);
          padding: 4px 8px;
          flex-shrink: 0; /* Don't shrink the tab bar */
          justify-content: center;
        }

        .tab {
          padding: 5px 10px 8px;
          border: none;
          background: transparent;
          color: var(--text-secondary);
          font-size: 0.8rem;
          cursor: pointer;
          border-bottom: 2px solid transparent;
          transition: all 0.2s;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 2px;
          min-width: 48px;
        }

        .tab:hover {
          color: var(--text-primary);
          background: rgba(255, 255, 255, 0.05);
        }

        .tab.active {
          color: var(--text-primary);
          border-bottom-color: var(--accent);
          background: rgba(255, 255, 255, 0.05);
        }

        .tab-badge {
          background: var(--accent);
          color: var(--vscode-button-foreground);
          font-size: 0.7rem;
          padding: 2px 5px;
          border-radius: 10px;
          font-weight: 600;
          min-height: 15px;
          line-height: 15px;
          order: -1; /* Move badge to top */
        }

        .tab-badge.running {
          background: var(--warning);
          animation: pulse 1s ease-in-out infinite;
        }

        .tab-badge-placeholder {
          min-height: 19px;
          order: -1; /* Keep placeholder at top for alignment */
        }

        .tab-badge-status {
          background: transparent;
          font-size: 0.7rem;
          padding: 0;
        }

        .tab-badge-status.status-green {
          color: var(--success);
        }

        .tab-badge-status.status-yellow {
          color: var(--warning);
        }

        .tab-badge-status.status-red {
          color: var(--error);
        }

        .tab-icon {
          font-size: 1.375rem;
          line-height: 1;
          margin: 6px 0;
        }

        .tab-label {
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: 0.4px;
          white-space: nowrap;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }

        /* ============================================ */
        /* Tab Content */
        /* ============================================ */
        .tab-content {
          display: none;
          padding: 20px 24px;
        }

        .tab-content.active {
          display: block;
        }

        /* ============================================ */
        /* Cards & Grids */
        /* ============================================ */
        .section {
          margin-bottom: 24px;
        }

        .section-title {
          font-size: 1rem;
          font-weight: 600;
          margin-bottom: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .grid-2 {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 16px;
        }

        .grid-3 {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 16px;
        }

        .grid-4 {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 16px;
        }

        @media (max-width: 900px) {
          .grid-4 {
            grid-template-columns: repeat(2, 1fr);
          }
        }

        .grid-4 {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 12px;
        }

        .grid-5 {
          display: grid;
          grid-template-columns: repeat(5, 1fr);
          gap: 12px;
        }

        @media (max-width: 1000px) {
          .grid-5 { grid-template-columns: repeat(3, 1fr); }
        }

        @media (max-width: 800px) {
          .grid-3, .grid-4, .grid-5 { grid-template-columns: repeat(2, 1fr); }
        }

        .card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 16px;
        }

        .card-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
        }

        .card-icon {
          width: 40px;
          height: 40px;
          border-radius: 10px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 20px;
        }

        .card-icon.purple { background: rgba(139, 92, 246, 0.15); }
        .card-icon.cyan { background: rgba(6, 182, 212, 0.15); }
        .card-icon.pink { background: rgba(236, 72, 153, 0.15); }
        .card-icon.green { background: rgba(16, 185, 129, 0.15); }
        .card-icon.orange { background: rgba(245, 158, 11, 0.15); }
        .card-icon.red { background: rgba(239, 68, 68, 0.15); }

        .card-title {
          font-weight: 600;
          font-size: 0.95rem;
        }

        .card-subtitle {
          font-size: 0.8rem;
          color: var(--text-secondary);
        }

        /* Current Work List (aggregated issues/MRs) */
        .current-work-list {
          display: flex;
          flex-direction: column;
          gap: 4px;
          margin: 8px 0;
          padding: 8px;
          background: var(--bg-tertiary);
          border-radius: 6px;
          max-height: 240px;
          overflow-y: auto;
        }

        .current-work-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 4px 8px;
          background: var(--bg-card);
          border-radius: 4px;
          font-size: 0.8rem;
        }

        .current-work-item:hover {
          background: rgba(59, 130, 246, 0.1);
        }

        .work-item-key {
          font-weight: 600;
          color: var(--accent);
        }

        .work-item-project {
          color: var(--text-muted);
          font-size: 0.75rem;
        }

        .work-item-more {
          text-align: center;
          font-size: 0.75rem;
          color: var(--text-muted);
          padding: 4px;
        }

        /* Sprint Issues */
        .sprint-issues {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .sprint-issue {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 12px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .sprint-issue:hover {
          border-color: var(--accent);
          background: rgba(59, 130, 246, 0.05);
        }

        .sprint-issue-icon {
          font-size: 1rem;
          min-width: 24px;
        }

        .sprint-issue-key {
          font-weight: 600;
          color: var(--accent);
          min-width: 90px;
        }

        .sprint-issue-summary {
          flex: 1;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .sprint-issue-priority {
          font-size: 0.75rem;
          min-width: 50px;
          text-align: center;
        }

        .sprint-issue-status {
          font-size: 0.75rem;
          padding: 2px 8px;
          border-radius: 4px;
          background: var(--bg-tertiary);
          color: var(--text-secondary);
          min-width: 70px;
          text-align: center;
        }

        .sprint-issue-status.in-progress {
          background: rgba(59, 130, 246, 0.15);
          color: var(--accent);
        }

        .sprint-issue-status.done {
          background: rgba(16, 185, 129, 0.15);
          color: var(--success);
        }

        .section-actions {
          display: flex;
          gap: 8px;
          margin-top: 12px;
        }

        .loading-placeholder {
          padding: 20px;
          text-align: center;
          color: var(--text-secondary);
          font-style: italic;
        }

        /* Stat Cards */
        .stat-card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 16px;
          border-top: 3px solid var(--border);
        }

        .stat-card.purple { border-top-color: var(--purple); }
        .stat-card.cyan { border-top-color: var(--cyan); }
        .stat-card.pink { border-top-color: var(--pink); }
        .stat-card.orange { border-top-color: var(--orange); }
        .stat-card.green { border-top-color: var(--success); }
        .stat-card.blue { border-top-color: #3b82f6; }
        .stat-card.red { border-top-color: var(--error); }

        .stat-card.clickable {
          cursor: pointer;
          transition: all 0.2s ease;
        }

        .stat-card.clickable:hover {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
          border-color: var(--accent);
        }

        .stat-icon {
          font-size: 24px;
          margin-bottom: 8px;
        }

        .stat-value {
          font-size: 1.8rem;
          font-weight: 700;
        }

        .stat-label {
          font-size: 0.8rem;
          color: var(--text-secondary);
        }

        .stat-sub {
          font-size: 0.75rem;
          color: var(--text-secondary);
          margin-top: 4px;
        }

        /* History Chart */
        .history-chart {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          height: 140px;
          padding: 16px;
          padding-top: 24px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          gap: 8px;
        }

        .history-bar-container {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          height: 100%;
          justify-content: flex-end;
        }

        .history-bar-value {
          font-size: 0.7rem;
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 4px;
        }

        .history-bar {
          width: 100%;
          max-width: 40px;
          background: linear-gradient(180deg, var(--purple) 0%, rgba(139, 92, 246, 0.5) 100%);
          border-radius: 4px 4px 0 0;
          min-height: 4px;
          transition: all 0.3s ease;
        }

        .history-bar.today {
          background: linear-gradient(180deg, var(--cyan) 0%, rgba(6, 182, 212, 0.5) 100%);
          box-shadow: 0 0 10px rgba(6, 182, 212, 0.3);
        }

        .history-bar:hover {
          transform: scaleY(1.05);
          filter: brightness(1.1);
        }

        .history-bar-label {
          font-size: 0.7rem;
          color: var(--text-secondary);
          margin-top: 6px;
        }

        .history-legend {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-top: 8px;
          padding: 0 8px;
          font-size: 0.75rem;
          color: var(--text-secondary);
        }

        .history-legend-item {
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .legend-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
        }

        .legend-dot.purple {
          background: var(--purple);
        }

        /* Progress Ring */
        .progress-ring {
          position: relative;
          width: 60px;
          height: 60px;
        }

        .progress-ring svg {
          transform: rotate(-90deg);
        }

        .progress-ring circle {
          fill: none;
          stroke-width: 5;
        }

        .progress-ring .bg {
          stroke: var(--border);
        }

        .progress-ring .progress {
          stroke: var(--success);
          stroke-linecap: round;
          transition: stroke-dashoffset 0.5s;
        }

        .progress-ring .value {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 0.75rem;
          font-weight: 700;
        }

        /* ============================================ */
        /* Skills Tab */
        /* ============================================ */

        /* Running Skills Panel */
        .running-skills-panel {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          margin-bottom: 16px;
          overflow: hidden;
        }

        .running-skills-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px;
          background: linear-gradient(135deg, rgba(139, 92, 246, 0.1), rgba(59, 130, 246, 0.1));
          border-bottom: 1px solid var(--border);
        }

        .running-skills-title {
          display: flex;
          align-items: center;
          gap: 10px;
          font-weight: 600;
          font-size: 0.9rem;
        }

        .running-skills-actions {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .stale-warning {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 2px 8px;
          background: rgba(234, 179, 8, 0.2);
          border: 1px solid var(--yellow);
          border-radius: 12px;
          font-size: 0.75rem;
          color: var(--yellow);
          font-weight: 500;
        }

        .btn-danger {
          color: var(--error) !important;
          border-color: var(--error) !important;
        }

        .btn-danger:hover {
          background: rgba(239, 68, 68, 0.15) !important;
        }

        .running-skill-item.stale {
          background: rgba(234, 179, 8, 0.1);
          border-left: 3px solid var(--yellow);
        }

        .running-skill-item.stale .running-skill-elapsed {
          color: var(--yellow);
          font-weight: 600;
        }

        .running-skill-item .clear-skill-btn {
          opacity: 0;
          padding: 2px 6px;
          font-size: 0.7rem;
          background: transparent;
          border: 1px solid var(--error);
          color: var(--error);
          border-radius: 4px;
          cursor: pointer;
          transition: opacity 0.2s, background 0.2s;
        }

        .running-skill-item:hover .clear-skill-btn {
          opacity: 1;
        }

        .running-skill-item .clear-skill-btn:hover {
          background: rgba(239, 68, 68, 0.15);
        }

        .running-indicator {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: var(--purple);
          animation: pulse-glow 1.5s ease-in-out infinite;
        }

        @keyframes pulse-glow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
          50% { box-shadow: 0 0 0 6px rgba(139, 92, 246, 0); }
        }

        .running-skills-list {
          padding: 8px;
          max-height: 200px;
          overflow-y: auto;
        }

        .running-skills-list.collapsed {
          display: none;
        }

        .running-skill-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 12px;
          border-radius: 8px;
          cursor: pointer;
          transition: background 0.2s;
          margin-bottom: 4px;
        }

        .running-skill-item:hover {
          background: var(--bg-secondary);
        }

        .running-skill-item.selected {
          background: rgba(139, 92, 246, 0.15);
          border-left: 3px solid var(--purple);
        }

        .running-skill-progress {
          flex-shrink: 0;
          width: 80px;
        }

        .running-skill-progress-bar {
          height: 6px;
          background: var(--border);
          border-radius: 3px;
          overflow: hidden;
        }

        .running-skill-progress-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--purple), var(--cyan));
          border-radius: 3px;
          transition: width 0.3s ease;
          animation: progress-shimmer 1.5s ease-in-out infinite;
        }

        @keyframes progress-shimmer {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.7; }
        }

        .running-skill-progress-text {
          font-size: 0.7rem;
          color: var(--text-secondary);
          text-align: center;
          margin-top: 2px;
        }

        .running-skill-info {
          flex: 1;
          min-width: 0;
        }

        .running-skill-name {
          font-weight: 600;
          font-size: 0.85rem;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .running-skill-source {
          font-size: 0.75rem;
          color: var(--text-secondary);
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .running-skill-source .source-badge {
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 0.65rem;
          font-weight: 600;
          text-transform: uppercase;
        }

        .running-skill-source .source-badge.chat {
          background: rgba(59, 130, 246, 0.2);
          color: var(--cyan);
        }

        .running-skill-source .source-badge.cron {
          background: rgba(245, 158, 11, 0.2);
          color: var(--warning);
        }

        .running-skill-source .source-badge.slack {
          background: rgba(139, 92, 246, 0.2);
          color: var(--purple);
        }

        .running-skill-elapsed {
          font-size: 0.75rem;
          color: var(--text-muted);
          font-family: var(--font-mono);
          flex-shrink: 0;
        }

        .skills-layout {
          display: grid;
          grid-template-columns: 280px 1fr;
          gap: 20px;
          height: calc(100vh - 220px);
        }

        .skills-sidebar {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .skills-search {
          padding: 12px;
          border-bottom: 1px solid var(--border);
        }

        .skills-search input {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid var(--border);
          border-radius: 6px;
          background: var(--bg-secondary);
          color: var(--text-primary);
          font-size: 0.85rem;
        }

        .skills-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }

        .skill-category {
          margin-bottom: 12px;
        }

        .skill-category-title {
          font-size: 0.7rem;
          text-transform: uppercase;
          color: var(--text-secondary);
          padding: 4px 8px;
          font-weight: 600;
        }

        .skill-item {
          padding: 10px 12px;
          border-radius: 6px;
          cursor: pointer;
          transition: background 0.2s;
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .skill-item:hover {
          background: var(--bg-secondary);
        }

        .skill-item.selected {
          background: rgba(139, 92, 246, 0.15);
          border-left: 3px solid var(--purple);
        }

        .skill-item-icon {
          font-size: 16px;
        }

        .skill-item-name {
          font-size: 0.85rem;
          font-weight: 500;
        }

        .skill-item-desc {
          font-size: 0.75rem;
          color: var(--text-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .skills-main {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .skills-main-header {
          padding: 16px;
          border-bottom: 1px solid var(--border);
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .skills-main-title {
          font-size: 1.1rem;
          font-weight: 600;
        }

        .skills-main-content {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }

        /* View Toggle */
        .view-toggle {
          display: flex;
          background: var(--bg-tertiary);
          border-radius: 6px;
          padding: 2px;
        }

        .toggle-btn {
          padding: 4px 10px;
          border: none;
          background: transparent;
          color: var(--text-muted);
          cursor: pointer;
          border-radius: 4px;
          font-size: 0.9rem;
          transition: all 0.2s;
        }

        .toggle-btn:hover {
          color: var(--text-primary);
        }

        .toggle-btn.active {
          background: var(--accent);
          color: white;
        }

        /* Slack User Dropdown */
        .slack-user-dropdown {
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }

        .slack-user-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px;
          cursor: pointer;
          transition: background 0.15s;
        }

        .slack-user-item:hover {
          background: var(--bg-tertiary);
        }

        .slack-user-avatar {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: var(--accent);
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 600;
          font-size: 0.9rem;
          color: white;
        }

        .slack-user-info {
          flex: 1;
          min-width: 0;
        }

        .slack-user-name {
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .slack-user-email {
          font-size: 0.8rem;
          color: var(--text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .slack-no-results {
          padding: 16px;
          text-align: center;
          color: var(--text-muted);
        }

        /* Skill YAML View */
        .skill-yaml-view {
          background: var(--bg-tertiary);
          border-radius: 8px;
          padding: 16px;
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 0.8rem;
          line-height: 1.5;
          overflow-x: auto;
          white-space: pre-wrap;
          word-break: break-word;
        }

        /* Skill Workflow View */
        .skill-workflow-view {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        /* Skill Info View */
        .skill-info-view {
          display: flex;
          flex-direction: column;
          gap: 16px;
          padding: 8px 0;
        }

        .skill-stats-section {
          background: var(--bg-tertiary);
          border-radius: 8px;
          padding: 16px;
        }

        .skill-stats-title {
          font-weight: 600;
          margin-bottom: 12px;
          color: var(--text-primary);
        }

        .skill-stats-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
          gap: 12px;
        }

        .skill-stat {
          display: flex;
          flex-direction: column;
          align-items: center;
          padding: 12px;
          background: var(--bg-secondary);
          border-radius: 6px;
        }

        .skill-stat .stat-value {
          font-size: 1.5rem;
          font-weight: 700;
          color: var(--text-primary);
        }

        .skill-stat .stat-label {
          font-size: 0.75rem;
          color: var(--text-muted);
          margin-top: 4px;
        }

        /* Full Flowchart View */
        .skill-flowchart-full {
          display: flex;
          flex-direction: column;
          height: 100%;
          gap: 12px;
        }

        .flowchart-header {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 12px 16px;
          background: var(--bg-tertiary);
          border-radius: 8px;
        }

        .flowchart-title {
          font-weight: 600;
          font-size: 1.1rem;
        }

        .flowchart-stats {
          display: flex;
          gap: 16px;
          margin-left: auto;
        }

        .flowchart-stat {
          font-size: 0.85rem;
          color: var(--text-secondary);
        }

        .flowchart-stat strong {
          color: var(--text-primary);
        }

        .flowchart-view-toggle {
          margin-left: auto;
        }

        .flowchart-view-toggle button {
          padding: 6px 12px;
          border: none;
          background: var(--bg-tertiary);
          color: var(--text-secondary);
          cursor: pointer;
          font-size: 0.85rem;
          transition: all 0.2s;
        }

        .flowchart-view-toggle button:first-child {
          border-radius: 6px 0 0 6px;
        }

        .flowchart-view-toggle button:last-child {
          border-radius: 0 6px 6px 0;
        }

        .flowchart-view-toggle button.active {
          background: var(--accent);
          color: white;
        }

        .flowchart-view-toggle button:hover:not(.active) {
          background: var(--bg-secondary);
          color: var(--text-primary);
        }

        .flowchart-legend {
          display: flex;
          gap: 16px;
          padding: 8px 16px;
          background: var(--bg-secondary);
          border-radius: 6px;
          font-size: 0.8rem;
        }

        .flowchart-legend .legend-item {
          color: var(--text-muted);
          cursor: help;
        }

        .flowchart-container-full {
          flex: 1;
          overflow: auto;
          padding: 16px;
          background: var(--bg-tertiary);
          border-radius: 8px;
        }

        .flowchart-wrap-full {
          display: flex;
          flex-wrap: wrap;
          align-items: flex-start;
          gap: 20px 0;
          padding: 8px 0;
        }

        .flowchart-vertical-full {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 8px 0;
        }

        .skill-info-card {
          background: var(--bg-tertiary);
          border-radius: 8px;
          padding: 16px;
          border-left: 3px solid var(--accent);
        }

        .skill-info-title {
          font-weight: 600;
          margin-bottom: 8px;
          color: var(--text-primary);
        }

        .skill-info-desc {
          color: var(--text-secondary);
          font-size: 0.9rem;
          line-height: 1.5;
        }

        .skill-inputs-section {
          background: var(--bg-tertiary);
          border-radius: 8px;
          padding: 16px;
        }

        .skill-inputs-title {
          font-weight: 600;
          margin-bottom: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .skill-input-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 8px 12px;
          background: var(--bg-secondary);
          border-radius: 6px;
          margin-bottom: 8px;
        }

        .skill-input-name {
          font-weight: 600;
          color: var(--text-primary);
          min-width: 120px;
        }

        .skill-input-type {
          font-size: 0.75rem;
          padding: 2px 6px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          color: var(--text-muted);
        }

        .skill-input-desc {
          flex: 1;
          color: var(--text-secondary);
          font-size: 0.85rem;
        }

        .skill-input-default {
          font-size: 0.75rem;
          color: var(--text-muted);
        }

        .skill-steps-section {
          background: var(--bg-tertiary);
          border-radius: 8px;
          padding: 16px;
        }

        .skill-steps-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .skill-steps-title {
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        /* Flowchart */
        .flowchart-container {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .flowchart-wrap {
          display: flex;
          flex-wrap: wrap;
          align-items: flex-start;
          gap: 20px 0;
          padding: 8px 0;
        }

        /* Horizontal Step Node */
        .step-node-h {
          display: flex;
          flex-direction: column;
          align-items: center;
          width: 170px;
          min-height: 100px;
          position: relative;
          flex-shrink: 0;
          padding: 0 8px;
        }

        .step-connector-h {
          position: absolute;
          top: 24px;
          left: 50%;
          width: calc(100% - 16px);
          height: 2px;
          background: var(--border);
          z-index: 0;
        }

        .step-node-h.row-last .step-connector-h {
          display: none;
        }

        .step-icon-h {
          width: 48px;
          height: 48px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 18px;
          font-weight: 700;
          z-index: 1;
          border: 2px solid var(--border);
          background: var(--bg-card);
          transition: all 0.3s;
          margin-bottom: 8px;
        }

        .step-node-h.pending .step-icon-h { border-color: var(--border); color: var(--text-muted); }
        .step-node-h.running .step-icon-h {
          border-color: var(--warning);
          color: var(--warning);
          box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.2);
          animation: pulse-ring 1.5s ease-out infinite;
        }
        .step-node-h.success .step-icon-h {
          border-color: var(--success);
          background: var(--success);
          color: white;
        }
        .step-node-h.failed .step-icon-h {
          border-color: var(--error);
          background: var(--error);
          color: white;
        }
        .step-node-h.skipped .step-icon-h {
          border-color: var(--text-secondary);
          opacity: 0.5;
        }

        @keyframes pulse-ring {
          0% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4); }
          70% { box-shadow: 0 0 0 8px rgba(245, 158, 11, 0); }
          100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0); }
        }

        .step-content-h {
          text-align: center;
          padding: 0 4px;
        }

        .step-name-h {
          font-weight: 600;
          font-size: 12px;
          margin-bottom: 4px;
          word-wrap: break-word;
          max-width: 160px;
        }

        .step-type-h {
          font-size: 11px;
          color: var(--text-secondary);
          display: flex;
          justify-content: center;
          gap: 5px;
          flex-wrap: wrap;
          margin-top: 2px;
        }

        .step-type-h .tag {
          padding: 2px 5px;
          border-radius: 3px;
          background: var(--bg-secondary);
          font-size: 11px;
        }

        .step-type-h .tag.tool { background: rgba(59, 130, 246, 0.2); color: var(--info); }
        .step-type-h .tag.compute { background: rgba(139, 92, 246, 0.2); color: var(--purple); }

        .step-duration-h {
          font-size: 9px;
          color: var(--text-secondary);
          margin-top: 2px;
          font-family: var(--vscode-editor-font-family);
        }

        /* Lifecycle Indicators */
        .step-lifecycle-h {
          position: absolute;
          top: -8px;
          left: 50%;
          transform: translateX(-50%);
          display: flex;
          gap: 2px;
          z-index: 2;
        }

        .lifecycle-indicator {
          font-size: 12px;
          width: 20px;
          height: 20px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 50%;
          background: var(--bg-card);
          border: 1px solid var(--border);
          cursor: help;
          transition: transform 0.2s;
        }

        .lifecycle-indicator:hover {
          transform: scale(1.2);
          z-index: 10;
        }

        .lifecycle-indicator.memory-read {
          background: rgba(59, 130, 246, 0.2);
          border-color: var(--info);
        }

        .lifecycle-indicator.memory-write {
          background: rgba(16, 185, 129, 0.2);
          border-color: var(--success);
        }

        .lifecycle-indicator.semantic-search {
          background: rgba(168, 85, 247, 0.2);
          border-color: var(--purple);
        }

        .lifecycle-indicator.auto-heal {
          background: rgba(245, 158, 11, 0.2);
          border-color: var(--warning);
        }

        .lifecycle-indicator.can-retry {
          background: rgba(139, 92, 246, 0.15);
          border-color: var(--purple);
        }

        .lifecycle-indicator.can-auto-heal {
          background: rgba(236, 72, 153, 0.2);
          border-color: var(--pink);
        }

        .lifecycle-indicator.healed {
          background: rgba(16, 185, 129, 0.3);
          border-color: var(--success);
          animation: healed-glow 1s ease-out;
        }

        .lifecycle-indicator.retry-count {
          background: rgba(245, 158, 11, 0.2);
          border-color: var(--warning);
          font-size: 10px;
          width: auto;
          padding: 1px 5px;
          border-radius: 10px;
        }

        @keyframes healed-glow {
          0% { box-shadow: 0 0 8px var(--success); }
          100% { box-shadow: none; }
        }

        /* Remediation step styling */
        .step-node-h.remediation .step-icon-h {
          border-style: dashed;
        }

        .step-node-h.remediation .step-connector-h {
          border-top: 2px dashed var(--warning);
          background: none;
          height: 0;
        }

        /* Vertical Flowchart (for detailed view) */
        .flowchart-vertical {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .step-node {
          display: flex;
          align-items: flex-start;
          margin-bottom: 8px;
          position: relative;
        }

        .step-connector {
          position: absolute;
          left: 15px;
          top: 32px;
          bottom: -8px;
          width: 2px;
          background: var(--border);
        }

        .step-node:last-child .step-connector {
          display: none;
        }

        .step-icon {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          flex-shrink: 0;
          z-index: 1;
          border: 2px solid var(--border);
          background: var(--bg-card);
          transition: all 0.3s;
        }

        .step-node.pending .step-icon { border-color: var(--border); color: var(--text-muted); }
        .step-node.running .step-icon {
          border-color: var(--warning);
          color: var(--warning);
          animation: spin 1s linear infinite;
        }
        .step-node.success .step-icon {
          border-color: var(--success);
          background: var(--success);
          color: white;
        }
        .step-node.failed .step-icon {
          border-color: var(--error);
          background: var(--error);
          color: white;
        }
        .step-node.skipped .step-icon {
          border-color: var(--text-secondary);
          opacity: 0.5;
        }

        .step-content {
          flex: 1;
          margin-left: 12px;
          min-width: 0;
          background: var(--bg-secondary);
          border-radius: 8px;
          padding: 12px;
        }

        .step-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 4px;
        }

        .step-name {
          font-weight: 600;
          font-size: 13px;
        }

        .step-duration {
          font-size: 11px;
          color: var(--text-secondary);
          font-family: var(--vscode-editor-font-family);
        }

        .step-desc {
          font-size: 12px;
          color: var(--text-secondary);
          margin-bottom: 8px;
        }

        .step-meta {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .step-tag {
          font-size: 10px;
          padding: 2px 6px;
          border-radius: 4px;
          background: var(--bg-card);
          color: var(--text-secondary);
          font-family: var(--vscode-editor-font-family);
        }

        .step-tag.tool { background: rgba(59, 130, 246, 0.2); color: var(--info); }
        .step-tag.compute { background: rgba(139, 92, 246, 0.2); color: var(--purple); }
        .step-tag.condition { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
        .step-tag.memory-read { background: rgba(59, 130, 246, 0.15); color: var(--info); }
        .step-tag.memory-write { background: rgba(16, 185, 129, 0.15); color: var(--success); }
        .step-tag.auto-heal { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
        .step-tag.can-retry { background: rgba(139, 92, 246, 0.1); color: var(--purple); }
        .step-tag.can-auto-heal { background: rgba(236, 72, 153, 0.15); color: var(--pink); }
        .step-tag.healed { background: rgba(16, 185, 129, 0.2); color: var(--success); }
        .step-tag.retry-count { background: rgba(245, 158, 11, 0.15); color: var(--warning); }

        .step-error {
          margin-top: 8px;
          padding: 8px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid var(--error);
          border-radius: 4px;
          font-size: 12px;
          color: var(--error);
        }

        .step-result {
          margin-top: 8px;
          padding: 8px;
          background: var(--bg-card);
          border-radius: 4px;
          font-size: 11px;
          font-family: var(--vscode-editor-font-family);
          max-height: 100px;
          overflow-y: auto;
          white-space: pre-wrap;
          word-break: break-all;
        }

        /* ============================================ */
        /* Services Tab */
        /* ============================================ */
        .service-card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          overflow: hidden;
        }

        .service-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border);
        }

        .service-title {
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .service-status {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.85rem;
        }

        .status-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
        }

        .status-dot.online { background: var(--success); box-shadow: 0 0 6px var(--success); }
        .status-dot.offline { background: var(--error); }
        .status-dot.checking { background: var(--warning); animation: pulse 1s infinite; }
        .status-dot.error { background: var(--error); box-shadow: 0 0 6px var(--error); }

        .service-content {
          padding: 16px;
        }

        .service-row {
          display: flex;
          justify-content: space-between;
          padding: 6px 0;
          border-bottom: 1px solid var(--border);
          font-size: 0.85rem;
        }

        .service-row:last-child {
          border-bottom: none;
        }

        .service-row span:first-child {
          color: var(--text-secondary);
        }

        .service-actions {
          display: flex;
          gap: 8px;
          padding: 12px 16px;
          border-top: 1px solid var(--border);
          background: var(--bg-secondary);
        }

        .service-actions .btn {
          flex: 1;
          font-size: 0.75rem;
          padding: 6px 8px;
        }

        .service-card.service-offline {
          opacity: 0.7;
        }

        .service-card.service-offline .service-header {
          background: var(--bg-tertiary);
        }

        /* Slack Messages */
        .slack-messages {
          max-height: 300px;
          overflow-y: auto;
        }

        .slack-message {
          display: flex;
          gap: 12px;
          padding: 12px;
          border-bottom: 1px solid var(--border);
        }

        .slack-message:last-child {
          border-bottom: none;
        }

        .slack-avatar {
          width: 32px;
          height: 32px;
          border-radius: 6px;
          background: var(--bg-secondary);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          flex-shrink: 0;
        }

        .slack-content {
          flex: 1;
          min-width: 0;
        }

        .slack-header {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-bottom: 4px;
        }

        .slack-user {
          font-weight: 600;
          font-size: 0.85rem;
        }

        .slack-time {
          font-size: 0.7rem;
          color: var(--text-secondary);
        }

        .slack-text {
          font-size: 0.85rem;
        }

        .slack-response {
          margin-top: 8px;
          padding: 8px;
          background: rgba(16, 185, 129, 0.1);
          border-radius: 4px;
          border-left: 2px solid var(--success);
          font-size: 0.8rem;
        }

        .slack-channel {
          font-size: 0.75rem;
          color: var(--text-muted);
          background: var(--bg-tertiary);
          padding: 1px 6px;
          border-radius: 3px;
        }

        .slack-reply-btn {
          margin-left: auto;
          opacity: 0;
          transition: opacity 0.2s;
        }

        .slack-message:hover .slack-reply-btn {
          opacity: 1;
        }

        .btn-tiny {
          padding: 2px 6px;
          font-size: 0.7rem;
        }

        /* Toggle Switch */
        .toggle-switch {
          position: relative;
          display: inline-block;
          width: 40px;
          height: 20px;
        }

        .toggle-switch input {
          opacity: 0;
          width: 0;
          height: 0;
        }

        .toggle-slider {
          position: absolute;
          cursor: pointer;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background-color: var(--bg-tertiary);
          transition: 0.3s;
          border-radius: 20px;
        }

        .toggle-slider:before {
          position: absolute;
          content: "";
          height: 14px;
          width: 14px;
          left: 3px;
          bottom: 3px;
          background-color: var(--text-muted);
          transition: 0.3s;
          border-radius: 50%;
        }

        .toggle-switch input:checked + .toggle-slider {
          background-color: var(--primary);
        }

        .toggle-switch input:checked + .toggle-slider:before {
          transform: translateX(20px);
          background-color: white;
        }

        /* Quick Reply Modal */
        .quick-reply-modal {
          display: none;
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          z-index: 1000;
          align-items: center;
          justify-content: center;
        }

        .quick-reply-content {
          background: var(--bg-primary);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 20px;
          width: 90%;
          max-width: 500px;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }

        .quick-reply-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
        }

        .quick-reply-title {
          font-weight: 600;
          font-size: 1rem;
        }

        .quick-reply-channel {
          font-size: 0.85rem;
          color: var(--text-muted);
        }

        .quick-reply-input {
          width: 100%;
          padding: 12px;
          border: 1px solid var(--border);
          border-radius: 6px;
          background: var(--bg-secondary);
          color: var(--text-primary);
          font-size: 0.9rem;
          margin-bottom: 16px;
          resize: vertical;
          min-height: 80px;
        }

        .quick-reply-actions {
          display: flex;
          justify-content: flex-end;
          gap: 8px;
        }

        /* Slack Pending Approvals */
        .slack-pending-item {
          display: flex;
          gap: 12px;
          padding: 12px;
          border-bottom: 1px solid var(--border);
          align-items: flex-start;
        }

        .slack-pending-item:last-child {
          border-bottom: none;
        }

        .slack-pending-content {
          flex: 1;
          min-width: 0;
        }

        .slack-pending-actions {
          display: flex;
          gap: 6px;
          flex-shrink: 0;
        }

        .slack-pending-meta {
          font-size: 0.75rem;
          color: var(--text-secondary);
          margin-top: 4px;
        }

        /* Slack Search Results */
        .slack-search-result {
          display: flex;
          gap: 12px;
          padding: 10px 12px;
          border-bottom: 1px solid var(--border);
          cursor: pointer;
          transition: background 0.15s;
        }

        .slack-search-result:hover {
          background: var(--bg-secondary);
        }

        .slack-search-result:last-child {
          border-bottom: none;
        }

        .slack-search-channel {
          font-size: 0.7rem;
          color: var(--text-secondary);
          background: var(--bg-tertiary);
          padding: 2px 6px;
          border-radius: 4px;
        }

        .slack-search-text {
          font-size: 0.85rem;
          margin-top: 4px;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }

        /* Slack Channel/User Browser */
        .slack-browser-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 10px;
          border-radius: 6px;
          cursor: pointer;
          transition: background 0.15s;
        }

        .slack-browser-item:hover {
          background: var(--bg-secondary);
        }

        .slack-browser-avatar {
          width: 28px;
          height: 28px;
          border-radius: 6px;
          background: var(--bg-tertiary);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          flex-shrink: 0;
          overflow: hidden;
        }

        .slack-browser-avatar img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .slack-browser-info {
          flex: 1;
          min-width: 0;
        }

        .slack-browser-name {
          font-size: 0.85rem;
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .slack-browser-meta {
          font-size: 0.7rem;
          color: var(--text-secondary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .slack-browser-id {
          font-size: 0.65rem;
          color: var(--text-muted);
          font-family: 'Fira Code', monospace;
        }

        .slack-browser-badge {
          font-size: 0.65rem;
          padding: 2px 6px;
          border-radius: 4px;
          background: var(--bg-tertiary);
          color: var(--text-secondary);
        }

        .slack-browser-badge.member {
          background: rgba(16, 185, 129, 0.2);
          color: var(--success);
        }

        /* D-Bus Explorer */
        .dbus-controls {
          display: flex;
          gap: 8px;
          margin-bottom: 12px;
        }

        .dbus-controls select {
          flex: 1;
          padding: 8px 12px;
          border: 1px solid var(--vscode-dropdown-border, var(--border));
          border-radius: 6px;
          background: var(--vscode-dropdown-background, var(--vscode-input-background, #3c3c3c));
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground, #cccccc));
          font-size: 0.85rem;
          cursor: pointer;
        }

        .dbus-controls select option {
          background: var(--vscode-dropdown-listBackground, var(--vscode-dropdown-background, #3c3c3c));
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground, #cccccc));
        }

        .dbus-controls .btn {
          flex-shrink: 0;
        }

        .dbus-result {
          background: var(--bg-secondary);
          border-radius: 6px;
          padding: 12px;
          font-family: 'Fira Code', monospace;
          font-size: 0.8rem;
          max-height: 200px;
          overflow-y: auto;
        }

        /* ============================================ */
        /* Memory Tab */
        /* ============================================ */
        .memory-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }

        .memory-list {
          max-height: 300px;
          overflow-y: auto;
        }

        .memory-item {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px;
          border-radius: 6px;
          cursor: pointer;
          transition: background 0.2s;
        }

        .memory-item:hover {
          background: var(--bg-secondary);
        }

        .memory-item-icon {
          font-size: 16px;
        }

        .memory-item-name {
          font-size: 0.85rem;
        }

        /* Vector Projects Table */
        .vector-projects-table {
          overflow-x: auto;
        }

        .vector-projects-table table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.85rem;
        }

        .vector-projects-table thead {
          background: var(--bg-tertiary);
          position: sticky;
          top: 0;
        }

        .vector-projects-table th {
          padding: 10px 12px;
          text-align: left;
          font-weight: 600;
          color: var(--text-secondary);
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          border-bottom: 1px solid var(--border);
          white-space: nowrap;
        }

        .vector-projects-table td {
          padding: 12px;
          border-bottom: 1px solid var(--border-light, rgba(255,255,255,0.05));
          vertical-align: middle;
        }

        .vector-projects-table tbody tr {
          transition: background 0.15s ease;
        }

        .vector-projects-table tbody tr:hover {
          background: var(--bg-secondary);
        }

        .vector-projects-table tbody tr:last-child td {
          border-bottom: none;
        }

        .vector-projects-table tbody tr.stale {
          background: rgba(234, 179, 8, 0.05);
        }

        .vector-projects-table tbody tr.stale:hover {
          background: rgba(234, 179, 8, 0.1);
        }

        .vector-projects-table .col-status {
          width: 40px;
          text-align: center;
        }

        .vector-projects-table .col-project {
          min-width: 180px;
        }

        .vector-projects-table .project-name {
          font-weight: 500;
          color: var(--text-primary);
        }

        .vector-projects-table .col-files,
        .vector-projects-table .col-chunks,
        .vector-projects-table .col-size,
        .vector-projects-table .col-searches,
        .vector-projects-table .col-avg {
          text-align: right;
          color: var(--text-secondary);
          font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
          font-size: 0.8rem;
        }

        .vector-projects-table .col-age {
          text-align: right;
          color: var(--text-tertiary);
          white-space: nowrap;
        }

        .vector-projects-table .col-age.stale-text {
          color: var(--yellow);
        }

        @media (max-width: 900px) {
          .vector-projects-table .col-avg,
          .vector-projects-table .col-searches {
            display: none;
          }
        }

        @media (max-width: 700px) {
          .vector-projects-table .col-size {
            display: none;
          }
        }

        /* Semantic Search Box */
        .semantic-search-container {
          margin-top: 16px;
        }

        .semantic-search-box {
          display: flex;
          gap: 8px;
          margin-bottom: 12px;
          align-items: flex-start;
        }

        .semantic-search-box textarea {
          flex: 1;
          padding: 10px 14px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: var(--bg-secondary);
          color: var(--text-primary);
          font-size: 0.9rem;
          min-height: 80px;
          resize: vertical;
          font-family: inherit;
          line-height: 1.4;
        }

        .semantic-search-box textarea:focus {
          outline: none;
          border-color: var(--accent);
          box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2);
        }

        .semantic-search-box textarea::placeholder {
          color: var(--text-tertiary);
        }

        .semantic-search-box select {
          padding: 10px 12px;
          border: 1px solid var(--vscode-dropdown-border, var(--border));
          border-radius: 8px;
          background: var(--vscode-dropdown-background, var(--vscode-input-background, #3c3c3c));
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground, #cccccc));
          font-size: 0.85rem;
          cursor: pointer;
          min-width: 180px;
        }

        .semantic-search-box select option {
          background: var(--vscode-dropdown-listBackground, var(--vscode-dropdown-background, #3c3c3c));
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground, #cccccc));
        }

        .semantic-search-box select:focus {
          outline: none;
          border-color: var(--vscode-focusBorder, var(--accent));
        }

        .semantic-search-results {
          max-height: 500px;
          overflow-y: auto;
          border-radius: 8px;
        }

        .search-result-item {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 8px;
          margin-bottom: 12px;
          overflow: hidden;
        }

        .search-result-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 10px 14px;
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border);
        }

        .search-result-file {
          font-family: 'Fira Code', monospace;
          font-size: 0.8rem;
          color: var(--cyan);
        }

        .search-result-meta {
          display: flex;
          gap: 12px;
          font-size: 0.75rem;
          color: var(--text-secondary);
        }

        .search-result-relevance {
          color: var(--green);
          font-weight: 600;
        }

        .search-result-code {
          padding: 12px 14px;
          font-family: 'Fira Code', monospace;
          font-size: 0.8rem;
          line-height: 1.5;
          overflow-x: auto;
          white-space: pre-wrap;
          word-break: break-word;
          background: var(--bg-primary);
          color: var(--text-primary);
          max-height: 200px;
          overflow-y: auto;
        }

        .search-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          padding: 30px;
          color: var(--text-secondary);
        }

        .search-loading-spinner {
          width: 20px;
          height: 20px;
          border: 2px solid var(--border);
          border-top-color: var(--accent);
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          to { transform: rotate(360deg); }
        }

        .search-empty {
          text-align: center;
          padding: 30px;
          color: var(--text-secondary);
        }

        .search-error {
          padding: 16px;
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid var(--red);
          border-radius: 8px;
          color: var(--red);
        }

        /* ============================================ */
        /* Buttons */
        /* ============================================ */
        .btn {
          padding: 8px 16px;
          border: none;
          border-radius: 6px;
          font-size: 0.85rem;
          cursor: pointer;
          transition: all 0.2s;
          display: inline-flex;
          align-items: center;
          gap: 6px;
        }

        .btn-primary {
          background: var(--vscode-button-background, #0e639c) !important;
          color: var(--vscode-button-foreground, white) !important;
        }

        .btn-primary:hover {
          background: var(--vscode-button-hoverBackground, #1177bb) !important;
        }

        .btn-secondary {
          background: var(--bg-secondary);
          color: var(--text-primary);
          border: 1px solid var(--border);
        }

        .btn-secondary:hover {
          background: var(--bg-card);
        }

        .btn-ghost {
          background: transparent;
          color: var(--text-secondary);
        }

        .btn-ghost:hover {
          color: var(--text-primary);
          background: var(--bg-secondary);
        }

        .btn-accent {
          background: linear-gradient(135deg, #8b5cf6, #6366f1);
          color: white;
        }

        .btn-accent:hover {
          background: linear-gradient(135deg, #7c3aed, #4f46e5);
        }

        .btn-small {
          padding: 4px 10px;
          font-size: 0.75rem;
        }

        /* Quick Actions */
        .quick-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        /* ============================================ */
        /* Footer */
        /* ============================================ */
        .footer {
          flex-shrink: 0; /* Don't shrink the footer */
          padding: 12px 24px;
          border-top: 1px solid var(--border);
          display: flex;
          justify-content: space-between;
          align-items: center;
          font-size: 0.75rem;
          color: var(--text-secondary);
          background: var(--bg-secondary);
        }

        .redhat-branding {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .redhat-name {
          font-weight: 600;
          color: #EE0000;
        }

        /* Empty State */
        .empty-state {
          text-align: center;
          padding: 40px;
          color: var(--text-secondary);
        }

        .empty-state-icon {
          font-size: 48px;
          margin-bottom: 12px;
          opacity: 0.5;
        }

        /* JSON formatting */
        .json-key { color: var(--cyan); }
        .json-string { color: var(--success); }
        .json-number { color: var(--warning); }
        .json-boolean { color: var(--purple); }

        /* VPN Banner */
        .vpn-banner {
          padding: 0 !important;
          margin-bottom: 16px !important;
        }

        .vpn-banner-content {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 12px 16px;
          background: rgba(245, 158, 11, 0.1);
          border: 1px solid var(--warning);
          border-radius: 8px;
          font-size: 0.85rem;
          color: var(--warning);
        }

        .vpn-banner-icon {
          font-size: 1.2rem;
        }

        .vpn-banner-text {
          flex: 1;
        }

        /* ============================================ */
        /* Tools Tab */
        /* ============================================ */
        .tools-container {
          display: flex;
          gap: 16px;
          height: calc(100vh - 280px);
          min-height: 400px;
        }

        .tools-sidebar {
          width: 280px;
          flex-shrink: 0;
          background: var(--bg-secondary);
          border-radius: 12px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }

        .tools-search {
          padding: 12px;
          border-bottom: 1px solid var(--border);
        }

        .tools-search input {
          width: 100%;
          padding: 8px 12px;
          background: var(--bg-tertiary);
          border: 1px solid var(--border);
          border-radius: 6px;
          color: var(--text-primary);
          font-size: 0.9rem;
        }

        .tools-modules-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
        }

        .tool-module-item {
          padding: 12px;
          border-radius: 8px;
          cursor: pointer;
          margin-bottom: 4px;
          transition: all 0.2s;
        }

        .tool-module-item:hover {
          background: var(--bg-tertiary);
        }

        .tool-module-item.selected {
          background: rgba(139, 92, 246, 0.2);
          border-left: 3px solid var(--accent);
        }

        .tool-module-item.active {
          border-left: 3px solid #22c55e;
        }

        .tool-module-name {
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .tool-module-count {
          font-size: 0.75rem;
          padding: 2px 6px;
          background: var(--bg-tertiary);
          border-radius: 4px;
          color: var(--text-muted);
        }

        .tool-module-desc {
          font-size: 0.8rem;
          color: var(--text-muted);
          margin-top: 4px;
        }

        .tools-main {
          flex: 1;
          background: var(--bg-secondary);
          border-radius: 12px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
        }

        .tools-main-header {
          padding: 16px;
          border-bottom: 1px solid var(--border);
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .tools-main-title {
          font-size: 1.1rem;
          font-weight: 600;
        }

        .tools-main-content {
          flex: 1;
          overflow-y: auto;
          padding: 16px;
        }

        .tool-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .tool-item {
          padding: 12px 16px;
          background: var(--bg-tertiary);
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .tool-item:hover {
          background: rgba(139, 92, 246, 0.1);
        }

        .tool-item-name {
          font-weight: 600;
          color: var(--text-primary);
          font-family: 'JetBrains Mono', 'Fira Code', monospace;
          font-size: 0.9rem;
        }

        .tool-item-desc {
          font-size: 0.8rem;
          color: var(--text-secondary);
          margin-top: 4px;
        }

        .agent-badge {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          background: linear-gradient(135deg, rgba(139, 92, 246, 0.2), rgba(59, 130, 246, 0.2));
          border-radius: 6px;
          font-size: 0.8rem;
          color: var(--text-primary);
        }

        .agent-badge-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #22c55e;
        }

        /* ============================================ */
        /* Personas Tab */
        /* ============================================ */
        .personas-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
          gap: 16px;
        }

        .persona-card {
          background: var(--bg-secondary);
          border-radius: 12px;
          overflow: hidden;
          transition: all 0.2s;
          border: 2px solid transparent;
        }

        .persona-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
        }

        .persona-card.active {
          border-color: var(--accent);
        }

        .persona-card.selected {
          border-color: var(--success);
          background: var(--bg-tertiary);
          box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
        }

        .persona-card {
          cursor: pointer;
        }

        .persona-header {
          padding: 20px;
          display: flex;
          align-items: center;
          gap: 16px;
          border-bottom: 1px solid var(--border);
        }

        .persona-icon {
          width: 56px;
          height: 56px;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 1.8rem;
        }

        .persona-icon.purple { background: linear-gradient(135deg, rgba(139, 92, 246, 0.3), rgba(139, 92, 246, 0.1)); }
        .persona-icon.cyan { background: linear-gradient(135deg, rgba(6, 182, 212, 0.3), rgba(6, 182, 212, 0.1)); }
        .persona-icon.pink { background: linear-gradient(135deg, rgba(236, 72, 153, 0.3), rgba(236, 72, 153, 0.1)); }
        .persona-icon.green { background: linear-gradient(135deg, rgba(34, 197, 94, 0.3), rgba(34, 197, 94, 0.1)); }
        .persona-icon.orange { background: linear-gradient(135deg, rgba(251, 146, 60, 0.3), rgba(251, 146, 60, 0.1)); }
        .persona-icon.blue { background: linear-gradient(135deg, rgba(59, 130, 246, 0.3), rgba(59, 130, 246, 0.1)); }
        .persona-icon.gray { background: linear-gradient(135deg, rgba(107, 114, 128, 0.3), rgba(107, 114, 128, 0.1)); }
        .persona-icon.yellow { background: linear-gradient(135deg, rgba(234, 179, 8, 0.3), rgba(234, 179, 8, 0.1)); }
        .persona-icon.teal { background: linear-gradient(135deg, rgba(20, 184, 166, 0.3), rgba(20, 184, 166, 0.1)); }
        .persona-icon.indigo { background: linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(99, 102, 241, 0.1)); }
        .persona-icon.amber { background: linear-gradient(135deg, rgba(245, 158, 11, 0.3), rgba(245, 158, 11, 0.1)); }
        .persona-icon.slate { background: linear-gradient(135deg, rgba(100, 116, 139, 0.3), rgba(100, 116, 139, 0.1)); }
        .persona-icon.violet { background: linear-gradient(135deg, rgba(167, 139, 250, 0.3), rgba(167, 139, 250, 0.1)); }

        .persona-info {
          flex: 1;
        }

        .persona-name {
          font-size: 1.2rem;
          font-weight: 600;
          text-transform: capitalize;
        }

        .persona-desc {
          color: var(--text-secondary);
          font-size: 0.9rem;
          margin-top: 4px;
        }

        .persona-active-badge {
          padding: 4px 10px;
          background: var(--accent);
          color: white;
          border-radius: 6px;
          font-size: 0.75rem;
          font-weight: 500;
        }

        .persona-type-badge {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 0.65rem;
          font-weight: 600;
          text-transform: uppercase;
          margin-left: 8px;
          vertical-align: middle;
        }

        .persona-type-badge.slim {
          background: rgba(251, 191, 36, 0.2);
          color: #fbbf24;
        }

        .persona-type-badge.internal {
          background: rgba(107, 114, 128, 0.2);
          color: #9ca3af;
        }

        .persona-type-badge.agent {
          background: rgba(59, 130, 246, 0.2);
          color: #60a5fa;
        }

        .persona-card.slim {
          opacity: 0.85;
        }

        .persona-card.internal,
        .persona-card.agent {
          opacity: 0.7;
          border-style: dashed;
        }

        .persona-tag.empty {
          background: rgba(107, 114, 128, 0.2);
          color: var(--text-muted);
          font-style: italic;
        }

        .persona-body {
          padding: 20px;
        }

        .persona-section {
          margin-bottom: 16px;
        }

        .persona-section:last-child {
          margin-bottom: 0;
        }

        .persona-section-title {
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--text-muted);
          text-transform: uppercase;
          letter-spacing: 0.5px;
          margin-bottom: 8px;
        }

        .persona-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .persona-tag {
          padding: 4px 10px;
          background: var(--bg-tertiary);
          border-radius: 6px;
          font-size: 0.8rem;
          color: var(--text-secondary);
        }

        .persona-tag.tool {
          border-left: 2px solid var(--accent);
        }

        .persona-tag.skill {
          border-left: 2px solid #22c55e;
        }

        .persona-footer {
          padding: 16px 20px;
          border-top: 1px solid var(--border);
          display: flex;
          gap: 8px;
        }

        /* ============================================ */
        /* Workspace Tab */
        /* ============================================ */
        .workspaces-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
          gap: 20px;
        }

        /* Search Spinner */
        .search-spinner {
          width: 14px;
          height: 14px;
          border: 2px solid var(--border);
          border-top-color: var(--accent);
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
          to { transform: translateY(-50%) rotate(360deg); }
        }

        /* Search input focus state */
        #sessionSearchInput:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
        }

        /* Group By Select */
        .group-by-select {
          padding: 6px 12px;
          border-radius: 6px;
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          color: var(--text-primary);
          font-size: 0.85rem;
          cursor: pointer;
          outline: none;
        }
        .group-by-select:hover {
          border-color: var(--accent);
        }
        .group-by-select:focus {
          border-color: var(--accent);
          box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2);
        }

        /* Session Groups */
        .session-group {
          margin-bottom: 24px;
        }
        .session-group-header {
          display: flex;
          align-items: center;
          padding: 12px 16px;
          background: var(--bg-secondary);
          border-radius: 10px;
          margin-bottom: 12px;
          border-left: 4px solid var(--accent);
        }
        .session-group-header.cyan { border-left-color: #06b6d4; }
        .session-group-header.green { border-left-color: #22c55e; }
        .session-group-header.red { border-left-color: #ef4444; }
        .session-group-header.purple { border-left-color: #8b5cf6; }
        .session-group-header.blue { border-left-color: #3b82f6; }
        .session-group-header.gray { border-left-color: #6b7280; }
        .session-group-header .group-icon {
          font-size: 1.3rem;
          margin-right: 12px;
        }
        .session-group-header .group-name {
          flex: 1;
          font-weight: 600;
          font-size: 1rem;
          color: var(--text-primary);
        }
        .session-group-header .group-count {
          color: var(--text-muted);
          font-size: 0.85rem;
          background: var(--bg-tertiary);
          padding: 4px 10px;
          border-radius: 12px;
        }
        .session-group-content {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 16px;
          padding-left: 8px;
        }

        .workspace-card {
          background: var(--bg-secondary);
          border-radius: 12px;
          overflow: hidden;
          transition: all 0.2s;
          border: 2px solid transparent;
        }

        .workspace-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
          border-color: var(--border);
        }

        .workspace-header {
          padding: 16px 20px;
          display: flex;
          align-items: center;
          gap: 16px;
          border-bottom: 1px solid var(--border);
          background: var(--bg-tertiary);
        }

        .workspace-icon {
          width: 48px;
          height: 48px;
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 1.5rem;
        }

        .workspace-icon.purple { background: rgba(139, 92, 246, 0.2); }
        .workspace-icon.cyan { background: rgba(6, 182, 212, 0.2); }
        .workspace-icon.pink { background: rgba(236, 72, 153, 0.2); }
        .workspace-icon.green { background: rgba(16, 185, 129, 0.2); }
        .workspace-icon.orange { background: rgba(249, 115, 22, 0.2); }
        .workspace-icon.blue { background: rgba(59, 130, 246, 0.2); }
        .workspace-icon.gray { background: rgba(107, 114, 128, 0.2); }

        .workspace-info {
          flex: 1;
          min-width: 0;
        }

        .workspace-project {
          font-weight: 600;
          font-size: 1.1rem;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .workspace-uri {
          font-size: 0.8rem;
          color: var(--text-muted);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .workspace-body {
          padding: 16px 20px;
        }

        .workspace-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 0;
          border-bottom: 1px solid var(--border);
        }

        .workspace-row:last-child {
          border-bottom: none;
        }

        .workspace-label {
          font-size: 0.85rem;
          color: var(--text-muted);
        }

        .workspace-value {
          font-size: 0.85rem;
          color: var(--text-primary);
          font-weight: 500;
        }

        .persona-badge {
          padding: 4px 10px;
          border-radius: 6px;
          font-size: 0.8rem;
        }

        .persona-badge.purple { background: rgba(139, 92, 246, 0.2); color: #a78bfa; }
        .persona-badge.cyan { background: rgba(6, 182, 212, 0.2); color: #22d3ee; }
        .persona-badge.pink { background: rgba(236, 72, 153, 0.2); color: #f472b6; }
        .persona-badge.green { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .persona-badge.orange { background: rgba(249, 115, 22, 0.2); color: #fb923c; }
        .persona-badge.blue { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
        .persona-badge.gray { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }
        .persona-badge.yellow { background: rgba(234, 179, 8, 0.2); color: #facc15; }
        .persona-badge.teal { background: rgba(20, 184, 166, 0.2); color: #2dd4bf; }
        .persona-badge.indigo { background: rgba(99, 102, 241, 0.2); color: #818cf8; }
        .persona-badge.amber { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
        .persona-badge.slate { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }
        .persona-badge.violet { background: rgba(167, 139, 250, 0.2); color: #a78bfa; }

        .issue-badges {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
        }

        .issue-badge {
          display: inline-block;
          padding: 4px 10px;
          background: rgba(59, 130, 246, 0.2);
          color: #60a5fa;
          border-radius: 6px;
          font-family: monospace;
          font-size: 0.85rem;
        }

        .issue-link {
          text-decoration: none;
          cursor: pointer;
          transition: background 0.2s, color 0.2s;
        }

        .issue-link:hover {
          background: rgba(59, 130, 246, 0.4);
          color: #93c5fd;
        }

        .branch-badge {
          padding: 4px 10px;
          background: rgba(16, 185, 129, 0.2);
          color: #34d399;
          border-radius: 6px;
          font-family: monospace;
          max-width: 200px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .project-badge {
          padding: 4px 10px;
          background: rgba(139, 92, 246, 0.2);
          color: #a78bfa;
          border-radius: 6px;
          font-weight: 500;
          max-width: 200px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .workspace-footer {
          padding: 12px 20px;
          border-top: 1px solid var(--border);
          display: flex;
          gap: 8px;
          justify-content: flex-end;
        }

        .persona-select {
          padding: 6px 12px;
          border-radius: 6px;
          border: 1px solid var(--border);
          background: var(--bg-tertiary);
          color: var(--text-primary);
          font-size: 0.85rem;
          cursor: pointer;
          min-width: 140px;
        }

        .persona-select:hover {
          border-color: var(--accent);
        }

        .persona-select:focus {
          outline: none;
          border-color: var(--accent);
          box-shadow: 0 0 0 2px rgba(139, 92, 246, 0.2);
        }

        .persona-select.purple { border-left: 3px solid #8b5cf6; }
        .persona-select.cyan { border-left: 3px solid #06b6d4; }
        .persona-select.pink { border-left: 3px solid #ec4899; }
        .persona-select.green { border-left: 3px solid #10b981; }
        .persona-select.orange { border-left: 3px solid #f97316; }
        .persona-select.blue { border-left: 3px solid #3b82f6; }
        .persona-select.gray { border-left: 3px solid #6b7280; }

        .workspace-badge {
          padding: 4px 10px;
          background: rgba(6, 182, 212, 0.2);
          color: #22d3ee;
          border-radius: 6px;
          font-size: 0.75rem;
          font-weight: 500;
        }

        /* ============================================ */
        /* Session Cards (within Workspaces) */
        /* ============================================ */
        .sessions-container {
          margin-top: 16px;
          padding-top: 16px;
          border-top: 1px solid var(--border);
        }

        .sessions-header {
          font-size: 0.9rem;
          font-weight: 600;
          color: var(--text-secondary);
          margin-bottom: 12px;
        }

        .no-sessions {
          padding: 16px;
          text-align: center;
          color: var(--text-muted);
          font-size: 0.85rem;
          background: var(--bg-tertiary);
          border-radius: 8px;
        }

        .session-card {
          background: var(--bg-tertiary);
          border-radius: 8px;
          margin-bottom: 12px;
          border: 1px solid var(--border);
          transition: all 0.2s;
        }

        .session-card:last-child {
          margin-bottom: 0;
        }

        .session-card:hover {
          border-color: var(--accent);
        }

        .session-card.session-active {
          border-color: #10b981;
          box-shadow: 0 0 0 1px rgba(16, 185, 129, 0.3);
        }

        .session-header {
          padding: 12px 16px;
          display: flex;
          align-items: center;
          gap: 12px;
          border-bottom: 1px solid var(--border);
        }

        .session-header.clickable {
          cursor: pointer;
          transition: background 0.15s ease;
        }

        .session-header.clickable:hover {
          background: var(--bg-tertiary);
        }

        .session-header .open-chat-hint {
          opacity: 0;
          transition: opacity 0.15s ease;
          margin-left: auto;
          font-size: 1rem;
        }

        .session-header.clickable:hover .open-chat-hint {
          opacity: 0.7;
        }

        .session-icon {
          width: 36px;
          height: 36px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 1.1rem;
        }

        .session-icon.purple { background: rgba(139, 92, 246, 0.2); }
        .session-icon.cyan { background: rgba(6, 182, 212, 0.2); }
        .session-icon.pink { background: rgba(236, 72, 153, 0.2); }
        .session-icon.green { background: rgba(16, 185, 129, 0.2); }
        .session-icon.orange { background: rgba(249, 115, 22, 0.2); }
        .session-icon.blue { background: rgba(59, 130, 246, 0.2); }
        .session-icon.gray { background: rgba(107, 114, 128, 0.2); }
        .session-icon.yellow { background: rgba(234, 179, 8, 0.2); }
        .session-icon.teal { background: rgba(20, 184, 166, 0.2); }
        .session-icon.indigo { background: rgba(99, 102, 241, 0.2); }
        .session-icon.amber { background: rgba(245, 158, 11, 0.2); }
        .session-icon.slate { background: rgba(100, 116, 139, 0.2); }
        .session-icon.violet { background: rgba(167, 139, 250, 0.2); }

        .session-info {
          flex: 1;
          min-width: 0;
        }

        .session-name {
          font-weight: 500;
          font-size: 0.95rem;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .session-id {
          font-size: 0.75rem;
          color: var(--text-muted);
          font-family: monospace;
        }

        .active-badge {
          padding: 2px 8px;
          background: rgba(16, 185, 129, 0.2);
          color: #34d399;
          border-radius: 4px;
          font-size: 0.7rem;
          font-weight: 600;
          text-transform: uppercase;
        }

        .session-body {
          padding: 12px 16px;
        }

        .session-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 6px 0;
          border-bottom: 1px solid var(--border);
        }

        .session-row:last-child {
          border-bottom: none;
        }

        .session-label {
          font-size: 0.8rem;
          color: var(--text-muted);
          flex-shrink: 0;
        }

        .session-value {
          font-size: 0.8rem;
          color: var(--text-primary);
          font-weight: 500;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 200px;
        }

        .session-footer {
          padding: 10px 16px;
          border-top: 1px solid var(--border);
          display: flex;
          gap: 8px;
          justify-content: flex-end;
        }

        /* ============================================ */
        /* Cron Tab */
        /* ============================================ */
        .cron-jobs-list {
          padding: 8px;
        }

        .cron-job-item {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 16px;
          border-radius: 8px;
          background: var(--bg-secondary);
          margin-bottom: 8px;
          transition: all 0.2s;
        }

        .cron-job-item:hover {
          background: rgba(139, 92, 246, 0.1);
        }

        .cron-job-item.disabled {
          opacity: 0.5;
        }

        .cron-job-toggle {
          flex-shrink: 0;
        }

        .toggle-switch {
          position: relative;
          display: inline-block;
          width: 44px;
          height: 24px;
        }

        .toggle-switch input {
          opacity: 0;
          width: 0;
          height: 0;
        }

        .toggle-slider {
          position: absolute;
          cursor: pointer;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background-color: var(--border);
          transition: 0.3s;
          border-radius: 24px;
        }

        .toggle-slider:before {
          position: absolute;
          content: "";
          height: 18px;
          width: 18px;
          left: 3px;
          bottom: 3px;
          background-color: white;
          transition: 0.3s;
          border-radius: 50%;
        }

        .toggle-switch input:checked + .toggle-slider {
          background-color: var(--success);
        }

        .toggle-switch input:checked + .toggle-slider:before {
          transform: translateX(20px);
        }

        .cron-job-info {
          flex: 1;
          min-width: 0;
        }

        .cron-job-name {
          font-weight: 600;
          font-size: 0.95rem;
          margin-bottom: 4px;
        }

        .cron-job-desc {
          font-size: 0.8rem;
          color: var(--text-secondary);
          margin-bottom: 8px;
        }

        .cron-job-schedule {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .cron-badge {
          font-size: 0.7rem;
          padding: 3px 8px;
          border-radius: 12px;
          background: var(--bg-card);
          border: 1px solid var(--border);
        }

        .cron-badge.cron {
          background: rgba(245, 158, 11, 0.15);
          border-color: var(--warning);
          color: var(--warning);
        }

        .cron-badge.poll {
          background: rgba(6, 182, 212, 0.15);
          border-color: var(--cyan);
          color: var(--cyan);
        }

        .cron-badge.skill {
          background: rgba(139, 92, 246, 0.15);
          border-color: var(--purple);
          color: var(--purple);
        }

        .cron-badge.notify {
          background: rgba(16, 185, 129, 0.15);
          border-color: var(--success);
          color: var(--success);
        }

        .cron-badge.persona {
          background: rgba(59, 130, 246, 0.15);
          border-color: var(--primary);
          color: var(--primary);
        }

        .cron-job-actions {
          flex-shrink: 0;
        }

        .cron-history-list {
          padding: 8px;
        }

        .cron-history-item {
          display: flex;
          align-items: flex-start;
          gap: 12px;
          padding: 12px;
          border-radius: 6px;
          background: var(--bg-secondary);
          margin-bottom: 6px;
        }

        .cron-history-item.success {
          border-left: 3px solid var(--success);
        }

        .cron-history-item.failed {
          border-left: 3px solid var(--error);
        }

        .cron-history-status {
          font-size: 18px;
          flex-shrink: 0;
        }

        .cron-history-info {
          flex: 1;
          min-width: 0;
        }

        .cron-history-name {
          font-weight: 600;
          font-size: 0.9rem;
          margin-bottom: 4px;
        }

        .cron-history-session {
          font-size: 0.75rem;
          color: var(--text-muted);
          margin-bottom: 4px;
          font-family: var(--font-mono, monospace);
        }

        .cron-history-details {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          font-size: 0.75rem;
          color: var(--text-secondary);
        }

        .cron-history-error {
          margin-top: 8px;
          padding: 10px 12px;
          background: rgba(239, 68, 68, 0.1);
          border-radius: 4px;
          font-size: 0.8rem;
          color: var(--error);
          border-left: 3px solid var(--error);
        }

        .cron-history-error-type {
          font-weight: 600;
          margin-bottom: 4px;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        .cron-history-error-message {
          font-family: var(--font-mono, monospace);
          font-size: 0.75rem;
          word-break: break-word;
          opacity: 0.9;
        }

        .cron-history-output {
          margin-top: 8px;
          padding: 10px 12px;
          background: rgba(34, 197, 94, 0.1);
          border-radius: 4px;
          font-size: 0.8rem;
          color: var(--text-primary);
          border-left: 3px solid var(--success);
          max-height: 120px;
          overflow-y: auto;
          white-space: pre-wrap;
          font-family: var(--font-mono, monospace);
        }

        .cron-history-duration {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }

        .cron-history-duration.timeout {
          color: var(--warning, #f59e0b);
          font-weight: 600;
        }

        .cron-history-duration.slow {
          color: var(--warning, #f59e0b);
        }

        .cron-history-duration.fast {
          color: var(--success);
        }

        .cron-history-load-more {
          display: flex;
          justify-content: center;
          padding: 12px;
          border-top: 1px solid var(--border);
          margin-top: 8px;
        }

        .cron-history-load-more button {
          font-size: 0.85rem;
        }

        .cron-reference {
          display: grid;
          gap: 8px;
        }

        .cron-ref-row {
          display: flex;
          align-items: center;
          gap: 16px;
          padding: 8px 12px;
          background: var(--bg-secondary);
          border-radius: 6px;
        }

        .cron-ref-row code {
          font-family: 'Fira Code', monospace;
          font-size: 0.85rem;
          color: var(--cyan);
          min-width: 140px;
        }

        .cron-ref-row span {
          font-size: 0.85rem;
          color: var(--text-secondary);
        }

        /* ============================================ */
        /* Inference Tab */
        /* ============================================ */
        .config-select {
          background: var(--vscode-dropdown-background, var(--vscode-input-background, #3c3c3c));
          border: 1px solid var(--vscode-dropdown-border, var(--border));
          border-radius: 6px;
          padding: 8px 12px;
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground, #cccccc));
          font-size: 13px;
          width: 100%;
          cursor: pointer;
        }

        .config-select option {
          background: var(--vscode-dropdown-listBackground, var(--vscode-dropdown-background, #3c3c3c));
          color: var(--vscode-dropdown-foreground, var(--vscode-input-foreground, #cccccc));
          padding: 8px;
        }

        .config-select option:hover,
        .config-select option:checked {
          background: var(--vscode-list-activeSelectionBackground, #094771);
          color: var(--vscode-list-activeSelectionForeground, #ffffff);
        }

        .config-select:focus {
          outline: none;
          border-color: var(--vscode-focusBorder, var(--accent));
        }

        .config-item {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .config-item label {
          font-size: 12px;
          color: var(--text-muted);
          font-weight: 500;
        }

        .config-toggles {
          display: flex;
          gap: 24px;
          flex-wrap: wrap;
        }

        .toggle-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          cursor: pointer;
        }

        .toggle-label input[type="checkbox"] {
          width: 16px;
          height: 16px;
          accent-color: var(--accent);
        }

        .histogram-bars {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .histogram-bar-container {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .histogram-label {
          width: 80px;
          font-size: 12px;
          color: var(--text-muted);
          text-align: right;
        }

        .histogram-bar {
          height: 20px;
          background: linear-gradient(90deg, var(--purple), var(--cyan));
          border-radius: 4px;
          transition: width 0.3s ease;
          min-width: 4px;
        }

        .histogram-value {
          font-size: 12px;
          color: var(--text-secondary);
          min-width: 40px;
        }

        .inspector-form {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .form-row {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .form-row label {
          font-size: 12px;
          color: var(--text-muted);
          font-weight: 500;
        }

        .form-input {
          background: var(--bg-input);
          border: 1px solid var(--border);
          border-radius: 6px;
          padding: 10px 12px;
          color: var(--text);
          font-size: 14px;
          width: 100%;
        }

        .form-input:focus {
          outline: none;
          border-color: var(--accent);
        }

        .form-actions {
          display: flex;
          gap: 12px;
        }

        .inspector-result {
          margin-top: 16px;
          padding: 16px;
          background: var(--bg-tertiary);
          border-radius: 8px;
          border: 1px solid var(--border);
        }

        .result-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 12px;
        }

        .result-status {
          font-size: 16px;
          font-weight: 600;
          color: var(--success);
        }

        .result-meta {
          font-size: 13px;
          color: var(--text-muted);
        }

        .result-layers {
          display: flex;
          flex-direction: column;
          gap: 8px;
          margin-bottom: 12px;
        }

        .result-layer {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 13px;
          padding: 8px 12px;
          background: var(--bg-card);
          border-radius: 6px;
        }

        .result-layer-name {
          font-weight: 500;
          min-width: 120px;
        }

        .result-layer-value {
          color: var(--text-secondary);
        }

        .result-tools {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          padding-top: 12px;
          border-top: 1px solid var(--border);
        }

        .tools-grid {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .tool-chip {
          padding: 4px 8px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 4px;
          font-size: 11px;
          font-family: var(--font-mono);
          color: var(--text-secondary);
        }

        .tool-chip.more {
          background: var(--purple);
          color: white;
          border-color: var(--purple);
        }

        .layer-badge {
          display: inline-block;
          padding: 4px 10px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 4px;
          font-size: 12px;
          margin-right: 4px;
        }

        .skill-detected {
          padding: 8px 12px;
          background: var(--purple);
          color: white;
          border-radius: 6px;
          margin-bottom: 12px;
          font-size: 13px;
        }

        .instance-status {
          font-size: 12px;
          padding: 2px 8px;
          border-radius: 4px;
        }

        .instance-status.online {
          color: var(--success);
        }

        .instance-status.offline {
          color: var(--text-muted);
        }

        .instance-status.error {
          color: var(--error);
        }

        .history-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: var(--bg-card);
          border-radius: 6px;
          margin-bottom: 6px;
          font-size: 12px;
        }

        .history-message {
          flex: 1;
          color: var(--text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .history-tools {
          color: var(--purple);
          margin: 0 12px;
        }

        .history-time {
          color: var(--text-muted);
          font-family: var(--font-mono);
        }

        .result-tool-tag {
          font-size: 11px;
          padding: 4px 8px;
          background: var(--bg-input);
          border-radius: 4px;
          color: var(--text-secondary);
        }

        .quick-tests {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .btn-ghost {
          background: transparent;
          border: 1px solid var(--border);
          color: var(--text-secondary);
        }

        .btn-ghost:hover {
          background: var(--bg-hover);
          border-color: var(--accent);
          color: var(--text);
        }

        .history-list {
          display: flex;
          flex-direction: column;
          gap: 8px;
          max-height: 300px;
          overflow-y: auto;
        }

        .history-item {
          padding: 12px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 8px;
        }

        .history-item-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }

        .history-item-time {
          font-size: 12px;
          color: var(--text-muted);
        }

        .history-item-message {
          font-size: 13px;
          color: var(--text);
          margin-bottom: 8px;
        }

        .history-item-meta {
          display: flex;
          gap: 16px;
          font-size: 12px;
          color: var(--text-secondary);
        }

        .history-item-meta span {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        /* ============================================ */
        /* Data Tables - Persona Statistics */
        /* ============================================ */
        .table-container {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 12px;
          overflow: hidden;
        }

        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 0.85rem;
        }

        .data-table thead {
          background: linear-gradient(135deg,
            rgba(139, 92, 246, 0.15) 0%,
            rgba(6, 182, 212, 0.1) 100%);
        }

        .data-table th {
          padding: 14px 12px;
          text-align: left;
          font-weight: 600;
          font-size: 0.75rem;
          text-transform: uppercase;
          letter-spacing: 0.5px;
          color: var(--text-secondary);
          border-bottom: 1px solid var(--border);
        }

        .data-table th:first-child {
          padding-left: 20px;
        }

        .data-table th:last-child {
          padding-right: 20px;
        }

        .data-table tbody tr {
          transition: all 0.15s ease;
        }

        .data-table tbody tr:hover {
          background: rgba(139, 92, 246, 0.08);
        }

        .data-table tbody tr:not(:last-child) {
          border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .data-table td {
          padding: 14px 12px;
          color: var(--text-primary);
        }

        .data-table td:first-child {
          padding-left: 20px;
          font-weight: 600;
        }

        .data-table td:last-child {
          padding-right: 20px;
        }

        /* Persona name styling with dynamic accent color */
        .data-table td:first-child {
          position: relative;
        }

        .data-table tbody tr td:first-child::before {
          content: '';
          position: absolute;
          left: 0;
          top: 50%;
          transform: translateY(-50%);
          width: 3px;
          height: 60%;
          border-radius: 0 2px 2px 0;
          background: var(--row-accent, var(--purple));
        }

        .data-table tbody tr:hover td:first-child::before {
          height: 80%;
          width: 4px;
        }

        /* Numeric columns - right align */
        .data-table td:not(:first-child) {
          text-align: center;
          font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
          font-size: 0.8rem;
        }

        .data-table th:not(:first-child) {
          text-align: center;
        }

        /* Empty state */
        .data-table .empty-state {
          padding: 40px 20px;
          text-align: center;
          color: var(--text-secondary);
          font-style: italic;
        }

        /* Table view active row */
        .data-table tbody tr.row-active {
          background: rgba(139, 92, 246, 0.1);
        }

        /* Small badges for table view */
        .persona-icon-small {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 24px;
          height: 24px;
          border-radius: 6px;
          font-size: 0.9rem;
        }
        .persona-icon-small.cyan { background: rgba(6, 182, 212, 0.2); }
        .persona-icon-small.green { background: rgba(16, 185, 129, 0.2); }
        .persona-icon-small.red { background: rgba(239, 68, 68, 0.2); }
        .persona-icon-small.purple { background: rgba(139, 92, 246, 0.2); }
        .persona-icon-small.orange { background: rgba(249, 115, 22, 0.2); }
        .persona-icon-small.pink { background: rgba(236, 72, 153, 0.2); }
        .persona-icon-small.yellow { background: rgba(234, 179, 8, 0.2); }
        .persona-icon-small.teal { background: rgba(20, 184, 166, 0.2); }
        .persona-icon-small.indigo { background: rgba(99, 102, 241, 0.2); }
        .persona-icon-small.amber { background: rgba(245, 158, 11, 0.2); }
        .persona-icon-small.slate { background: rgba(100, 116, 139, 0.2); }
        .persona-icon-small.violet { background: rgba(167, 139, 250, 0.2); }
        .persona-icon-small.blue { background: rgba(59, 130, 246, 0.2); }
        .persona-icon-small.gray { background: rgba(107, 114, 128, 0.2); }

        .persona-badge-small {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 4px;
          font-size: 0.75rem;
          font-weight: 500;
        }
        .persona-badge-small.cyan { background: rgba(6, 182, 212, 0.2); color: #22d3ee; }
        .persona-badge-small.green { background: rgba(16, 185, 129, 0.2); color: #34d399; }
        .persona-badge-small.red { background: rgba(239, 68, 68, 0.2); color: #f87171; }
        .persona-badge-small.purple { background: rgba(139, 92, 246, 0.2); color: #a78bfa; }
        .persona-badge-small.orange { background: rgba(249, 115, 22, 0.2); color: #fb923c; }
        .persona-badge-small.pink { background: rgba(236, 72, 153, 0.2); color: #f472b6; }
        .persona-badge-small.yellow { background: rgba(234, 179, 8, 0.2); color: #facc15; }
        .persona-badge-small.teal { background: rgba(20, 184, 166, 0.2); color: #2dd4bf; }
        .persona-badge-small.indigo { background: rgba(99, 102, 241, 0.2); color: #818cf8; }
        .persona-badge-small.amber { background: rgba(245, 158, 11, 0.2); color: #fbbf24; }
        .persona-badge-small.slate { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }
        .persona-badge-small.violet { background: rgba(167, 139, 250, 0.2); color: #a78bfa; }
        .persona-badge-small.blue { background: rgba(59, 130, 246, 0.2); color: #60a5fa; }
        .persona-badge-small.gray { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }

        .active-badge-small {
          display: inline-block;
          padding: 1px 6px;
          border-radius: 4px;
          font-size: 0.65rem;
          font-weight: 600;
          background: rgba(16, 185, 129, 0.2);
          color: var(--green);
          text-transform: uppercase;
        }

        .issue-badge-small {
          display: inline-block;
          padding: 2px 6px;
          border-radius: 4px;
          font-size: 0.75rem;
          background: rgba(249, 115, 22, 0.15);
          color: var(--orange);
          margin: 1px;
          white-space: nowrap;
        }

        /* Issue cell and container for table view */
        .issue-cell {
          max-width: 250px;
        }

        .issue-badges-container {
          display: flex;
          flex-wrap: wrap;
          gap: 2px;
          max-width: 250px;
          justify-content: center;
        }

        .meeting-notes-btn {
          background: rgba(139, 92, 246, 0.15) !important;
          color: var(--purple) !important;
        }

        .meeting-notes-btn:hover {
          background: rgba(139, 92, 246, 0.3) !important;
        }

        /* Table containers - need to span full width when inside grid */
        .sessions-table-container,
        .personas-table-container {
          overflow-x: auto;
          width: 100%;
          grid-column: 1 / -1; /* Span all grid columns */
        }

        .sessions-table-container .data-table,
        .personas-table-container .data-table {
          width: 100%;
          min-width: 800px; /* Ensure minimum width for all columns */
          table-layout: auto;
        }

        /* Sessions table specific - fixed layout for column control */
        .sessions-data-table {
          table-layout: fixed;
        }

        /* When table view is active, make grid a single column */
        .workspaces-grid:has(.sessions-table-container) {
          display: block;
        }

        /* Clickable cells in tables */
        .data-table .clickable {
          cursor: pointer;
        }
        .data-table .clickable:hover {
          color: var(--cyan);
          text-decoration: underline;
        }

        /* History list improvements */
        .history-list .history-item {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 12px 16px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 8px;
          border-left: 3px solid var(--purple);
          transition: all 0.15s ease;
        }

        .history-list .history-item:hover {
          background: rgba(139, 92, 246, 0.08);
          border-left-color: var(--cyan);
        }

        .history-list .history-message {
          flex: 1;
          font-size: 0.85rem;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          margin-right: 16px;
        }

        .history-list .history-tools {
          font-size: 0.75rem;
          font-weight: 600;
          color: var(--cyan);
          background: rgba(6, 182, 212, 0.15);
          padding: 4px 10px;
          border-radius: 12px;
          margin-right: 12px;
          white-space: nowrap;
        }

        .history-list .history-time {
          font-size: 0.75rem;
          color: var(--text-secondary);
          font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
          min-width: 70px;
          text-align: right;
        }

        /* Latency histogram improvements */
        .latency-histogram {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 16px 20px;
        }

        .latency-histogram h3 {
          color: var(--text-secondary);
          margin-bottom: 16px;
        }

        .histogram-bars {
          display: flex;
          flex-direction: column;
          gap: 10px;
        }

        .histogram-bar-container {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .histogram-label {
          font-size: 0.8rem;
          color: var(--text-secondary);
          min-width: 70px;
          text-align: right;
        }

        .histogram-bar {
          height: 24px;
          border-radius: 4px;
          background: linear-gradient(90deg, var(--purple) 0%, var(--cyan) 100%);
          transition: width 0.5s ease;
          min-width: 4px;
        }

        .histogram-value {
          font-size: 0.8rem;
          font-weight: 600;
          color: var(--text-primary);
          min-width: 40px;
        }

        ${getMeetingsTabStyles()}
      </style>
    </head>
    <body>
      <div class="main-content">
      <!-- Header -->
      <div class="header">
        <div class="agent-avatar">
          <svg class="agent-hat" viewBox="0 0 100 55" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="50" cy="50" rx="48" ry="8" fill="rgba(0,0,0,0.2)"/>
            <ellipse cx="50" cy="45" rx="48" ry="10" fill="#EE0000"/>
            <path d="M25 45 Q25 20 50 15 Q75 20 75 45" fill="#EE0000"/>
            <rect x="25" y="38" width="50" height="8" fill="#1a1a1a"/>
          </svg>
          <div class="agent-ring"></div>
          <div class="agent-body">🤖</div>
          <div class="agent-status"></div>
        </div>
        <div class="header-info">
          <h1 class="header-title">AI Workflow Command Center</h1>
          <p class="header-subtitle">Your intelligent development assistant • Session active</p>
        </div>
        <div class="header-stats">
          <div class="header-stat">
            <div class="header-stat-value" id="statToolCalls">${this._formatNumber(lifetime.tool_calls)}</div>
            <div class="header-stat-label">Tool<br/>Calls</div>
          </div>
          <div class="header-stat">
            <div class="header-stat-value" id="statSkills">${lifetime.skill_executions}</div>
            <div class="header-stat-label">Skills<br/>Called</div>
          </div>
          <div class="header-stat">
            <div class="header-stat-value" id="statSessions">${lifetime.sessions}</div>
            <div class="header-stat-label">Sessions<br/>Initiated</div>
          </div>
        </div>
      </div>

      <!-- Tabs - Compact Vertical Layout -->
      <div class="tabs">
        <button class="tab ${this._currentTab === "overview" ? "active" : ""}" data-tab="overview" id="tab-overview">
          <span class="tab-badge-placeholder"></span>
          <span class="tab-icon">📊</span>
          <span class="tab-label">Overview</span>
        </button>
        <button class="tab ${this._currentTab === "create" ? "active" : ""}" data-tab="create" id="tab-create">
          <span class="tab-badge-placeholder"></span>
          <span class="tab-icon">✨</span>
          <span class="tab-label">Create</span>
        </button>
        <button class="tab ${this._currentTab === "sprint" ? "active" : ""}" data-tab="sprint" id="tab-sprint">
          <span class="tab-badge" id="sprintTabBadge" style="${sprintState.issues.length > 0 ? '' : 'display: none;'}">${sprintState.issues.length}</span>
          ${sprintState.issues.length === 0 ? '<span class="tab-badge-placeholder"></span>' : ''}
          <span class="tab-icon">🏃</span>
          <span class="tab-label">Sprint</span>
        </button>
        <button class="tab ${this._currentTab === "workspaces" ? "active" : ""}" data-tab="workspaces" id="tab-workspaces">
          <span class="tab-badge" id="workspacesBadge">${this._getTotalSessionCount()}</span>
          <span class="tab-icon">💬</span>
          <span class="tab-label">Sessions</span>
        </button>
        <button class="tab ${this._currentTab === "personas" ? "active" : ""}" data-tab="personas" id="tab-personas">
          <span class="tab-badge" id="personasTabBadge">${totalPersonas}</span>
          <span class="tab-icon">🤖</span>
          <span class="tab-label">Personas</span>
        </button>
        <button class="tab ${this._currentTab === "skills" ? "active" : ""}" data-tab="skills" id="tab-skills">
          <span class="tab-badge" id="skillsBadge" data-total="${totalSkills}">${totalSkills}</span>
          <span class="tab-icon">⚡</span>
          <span class="tab-label">Skills</span>
        </button>
        <button class="tab ${this._currentTab === "tools" ? "active" : ""}" data-tab="tools" id="tab-tools">
          <span class="tab-badge" id="toolsTabBadge">${totalTools}</span>
          <span class="tab-icon">🔧</span>
          <span class="tab-label">Tools</span>
        </button>
        <button class="tab ${this._currentTab === "memory" ? "active" : ""}" data-tab="memory" id="tab-memory">
          <span class="tab-badge" id="memoryTabBadge">${memoryHealth.totalSize}</span>
          <span class="tab-icon">🧠</span>
          <span class="tab-label">Memory</span>
        </button>
        <button class="tab ${this._currentTab === "meetings" ? "active" : ""}" data-tab="meetings" id="tab-meetings">
          <span class="tab-badge ${meetBotState.currentMeeting ? 'running' : ''}" id="meetingsTabBadge" style="${meetBotState.currentMeeting || meetBotState.upcomingMeetings.length > 0 ? '' : 'display: none;'}">${meetBotState.currentMeeting ? 'Live' : meetBotState.upcomingMeetings.length}</span>
          ${!meetBotState.currentMeeting && meetBotState.upcomingMeetings.length === 0 ? '<span class="tab-badge-placeholder"></span>' : ''}
          <span class="tab-icon">🎥</span>
          <span class="tab-label">Meetings</span>
        </button>
        <button class="tab ${this._currentTab === "slack" ? "active" : ""}" data-tab="slack" id="tab-slack">
          <span class="tab-badge-placeholder"></span>
          <span class="tab-icon">💬</span>
          <span class="tab-label">Slack</span>
        </button>
        <button class="tab ${this._currentTab === "inference" ? "active" : ""}" data-tab="inference" id="tab-inference">
          <span class="tab-badge-placeholder"></span>
          <span class="tab-icon">🧪</span>
          <span class="tab-label">Inference</span>
        </button>
        <button class="tab ${this._currentTab === "cron" ? "active" : ""}" data-tab="cron" id="tab-cron">
          <span class="tab-badge" id="cronTabBadge" style="${cronConfig.enabled && cronConfig.jobs.filter(j => j.enabled).length > 0 ? '' : 'display: none;'}">${cronConfig.jobs.filter(j => j.enabled).length}</span>
          ${!(cronConfig.enabled && cronConfig.jobs.filter(j => j.enabled).length > 0) ? '<span class="tab-badge-placeholder"></span>' : ''}
          <span class="tab-icon">🕐</span>
          <span class="tab-label">Cron</span>
        </button>
        <button class="tab ${this._currentTab === "services" ? "active" : ""}" data-tab="services" id="tab-services">
          <span class="tab-badge tab-badge-status ${servicesStatusColor}" id="servicesTabBadge" title="${totalRunning}/${totalServices} online">${servicesStatusIcon}</span>
          <span class="tab-icon">🔌</span>
          <span class="tab-label">Services</span>
        </button>
        <button class="tab ${this._currentTab === "performance" ? "active" : ""}" data-tab="performance" id="tab-performance">
          <span class="tab-badge" id="performanceTabBadge" style="${performanceState.overall_percentage > 0 ? '' : 'display: none;'}">${performanceState.overall_percentage}%</span>
          ${performanceState.overall_percentage === 0 ? '<span class="tab-badge-placeholder"></span>' : ''}
          <span class="tab-icon">📊</span>
          <span class="tab-label">QC</span>
        </button>
      </div>

      <!-- Overview Tab -->
      <div class="tab-content ${this._currentTab === "overview" ? "active" : ""}" id="overview">
        <!-- Today's Stats -->
        <div class="section">
          <h2 class="section-title">📊 Today's Activity</h2>
          <div class="grid-4">
            <div class="stat-card purple">
              <div class="stat-icon">🔧</div>
              <div class="stat-value" id="todayToolCalls">${todayStats.tool_calls || 0}</div>
              <div class="stat-label">Tool Calls</div>
              <div class="stat-sub">Session: <span id="sessionToolCalls">${session.tool_calls}</span></div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">⚡</div>
              <div class="stat-value" id="todaySkillRuns">${todayStats.skill_executions || 0}</div>
              <div class="stat-label">Skills Run</div>
              <div class="stat-sub">Session: <span id="sessionSkillRuns">${session.skill_executions}</span></div>
            </div>
            <div class="stat-card pink">
              <div class="stat-icon">🧠</div>
              <div class="stat-value" id="sessionMemoryOps">${session.memory_ops || 0}</div>
              <div class="stat-label">Memory Ops</div>
              <div class="stat-sub">This session</div>
            </div>
            <div class="stat-card green">
              <div class="stat-icon">✅</div>
              <div class="stat-value" id="toolSuccessRate">${toolSuccessRate}%</div>
              <div class="stat-label">Success Rate</div>
              <div class="stat-sub">All time</div>
            </div>
          </div>
        </div>

        <!-- Historical Trend -->
        <div class="section">
          <h2 class="section-title">📈 7-Day History</h2>
          <div class="history-chart">
            ${dailyHistory.map((day, i) => {
              const barHeight = Math.max((day.tool_calls / maxToolCalls) * 100, 4);
              const dayName = new Date(day.date).toLocaleDateString('en-US', { weekday: 'short' });
              const isToday = i === dailyHistory.length - 1;
              return `
                <div class="history-bar-container" title="${day.date}: ${day.tool_calls} tools, ${day.skill_executions} skills, ${day.sessions} sessions">
                  <span class="history-bar-value">${day.tool_calls}</span>
                  <div class="history-bar ${isToday ? 'today' : ''}" style="height: ${barHeight}%;"></div>
                  <div class="history-bar-label">${dayName}</div>
                </div>
              `;
            }).join('')}
          </div>
          <div class="history-legend">
            <span class="history-legend-item"><span class="legend-dot purple"></span> Tool Calls</span>
            <span class="history-legend-item">Total: ${lifetime.tool_calls} tools, ${lifetime.skill_executions} skills, ${lifetime.sessions} sessions</span>
          </div>
        </div>

        <!-- Current Work -->
        <div class="section">
          <h2 class="section-title">📋 Current Work</h2>
          <div class="grid-2">
            <div class="card" id="currentIssueCard">
              <div class="card-header">
                <div class="card-icon purple">📋</div>
                <div>
                  <div class="card-title" id="currentIssueKey">${currentWork.totalActiveIssues > 0 ? `${currentWork.totalActiveIssues} Active Issue${currentWork.totalActiveIssues > 1 ? 's' : ''}` : "No Active Issues"}</div>
                  <div class="card-subtitle" id="currentIssueStatus">${currentWork.totalActiveIssues > 0 ? `Across ${this._workspaceCount || 1} workspace${(this._workspaceCount || 1) > 1 ? 's' : ''}` : "Start work to track an issue"}</div>
                </div>
              </div>
              ${currentWork.allActiveIssues.length > 0 ? `
              <div class="current-work-list" id="activeIssuesList">
                ${currentWork.allActiveIssues.map((issue: any) => `
                  <div class="current-work-item" title="${issue.summary || issue.project}">
                    <span class="work-item-key">${issue.key}</span>
                    <span class="work-item-project">${issue.project}</span>
                  </div>
                `).join('')}
              </div>
              ` : ''}
              <div id="currentIssueActions">
              ${currentWork.totalActiveIssues > 0
                ? `<button class="btn btn-secondary btn-small" data-action="openJira">Open in Jira</button>`
                : `<button class="btn btn-primary btn-small" data-action="startWork">Start Work</button>`
              }
              </div>
            </div>
            <div class="card" id="currentMRCard">
              <div class="card-header">
                <div class="card-icon cyan">🔀</div>
                <div>
                  <div class="card-title" id="currentMRTitle">${currentWork.totalActiveMRs > 0 ? `${currentWork.totalActiveMRs} Active MR${currentWork.totalActiveMRs > 1 ? 's' : ''}` : "No Active MRs"}</div>
                  <div class="card-subtitle" id="currentMRStatus">${currentWork.totalActiveMRs > 0 ? "Open" : "Create an MR when ready"}</div>
                </div>
              </div>
              ${currentWork.allActiveMRs.length > 0 ? `
              <div class="current-work-list" id="activeMRsList">
                ${currentWork.allActiveMRs.map((mr: any) => `
                  <div class="current-work-item" title="${mr.title || mr.project}">
                    <span class="work-item-key">!${mr.id}</span>
                    <span class="work-item-project">${mr.project}</span>
                  </div>
                `).join('')}
              </div>
              ` : ''}
              <div id="currentMRActions">
              ${currentWork.totalActiveMRs > 0
                ? `<button class="btn btn-secondary btn-small" data-action="openMR">Open in GitLab</button>`
                : ``
              }
              </div>
            </div>
          </div>
        </div>

        <!-- My Assigned Issues -->
        <div class="section">
          <h2 class="section-title">📋 My Assigned Issues</h2>
          <div class="sprint-issues" id="sprintIssues">
            <div class="loading-placeholder">Loading assigned issues...</div>
          </div>
          <div class="section-actions">
            <button class="btn btn-ghost btn-small" data-action="openJiraBoard">📊 Open Jira Board</button>
          </div>
        </div>

        <!-- VPN Status (only show if disconnected) -->
        <div class="section vpn-banner" id="vpnBanner" style="display: ${!workflowStatus.vpn?.connected ? 'block' : 'none'};">
          <div class="vpn-banner-content">
            <span class="vpn-banner-icon">🔓</span>
            <span class="vpn-banner-text">VPN not connected - GitLab access may be limited</span>
          </div>
        </div>

        <!-- Environments -->
        <div class="section">
          <h2 class="section-title">🌍 Environments</h2>
          <div class="grid-2">
            <div class="card" id="stageCard">
              <div class="card-header">
                <div class="card-icon ${workflowStatus.environment?.stageStatus === "healthy" ? "green" : workflowStatus.environment?.stageStatus === "degraded" ? "orange" : ""}" id="stageIcon">
                  ${workflowStatus.environment?.stageStatus === "healthy" ? "✅" : workflowStatus.environment?.stageStatus === "degraded" ? "⚠️" : "❓"}
                </div>
                <div>
                  <div class="card-title">Stage</div>
                  <div class="card-subtitle" id="stageStatus">${workflowStatus.environment?.stageStatus || "Not monitored"}</div>
                </div>
              </div>
            </div>
            <div class="card" id="prodCard">
              <div class="card-header">
                <div class="card-icon ${workflowStatus.environment?.prodStatus === "healthy" ? "green" : workflowStatus.environment?.prodStatus === "degraded" ? "orange" : ""}" id="prodIcon">
                  ${workflowStatus.environment?.prodStatus === "healthy" ? "✅" : workflowStatus.environment?.prodStatus === "degraded" ? "⚠️" : "❓"}
                </div>
                <div>
                  <div class="card-title">Production</div>
                  <div class="card-subtitle" id="prodStatus">${workflowStatus.environment?.prodStatus || "Not monitored"}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>

      <!-- Sessions Tab -->
      <div class="tab-content ${this._currentTab === "workspaces" ? "active" : ""}" id="workspaces">
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2 class="section-title" style="margin: 0;">💬 Sessions by Project</h2>
            <div style="display: flex; gap: 8px; align-items: center;">
              <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="session">▶ Start</button>
              <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="session">⏹ Stop</button>
              <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="session">📋 Logs</button>
              <div class="search-box" style="position: relative; margin-left: 8px;">
                <input type="text" id="sessionSearchInput" placeholder="Search chats..."
                  style="padding: 6px 12px 6px 32px; border-radius: 6px; background: var(--bg-secondary); border: 1px solid var(--border); color: var(--text-primary); font-size: 0.85rem; width: 200px; outline: none;"
                  onkeyup="if(event.key === 'Enter') { vscode.postMessage({ command: 'searchSessions', query: this.value }); }"
                />
                <span id="sessionSearchIcon" style="position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-muted);">🔍</span>
                <span id="sessionSearchSpinner" style="position: absolute; left: 10px; top: 50%; transform: translateY(-50%); display: none;" class="search-spinner"></span>
                <button id="sessionSearchClear" style="position: absolute; right: 8px; top: 50%; transform: translateY(-50%); background: none; border: none; color: var(--text-muted); cursor: pointer; display: none; font-size: 12px;" title="Clear search">✕</button>
              </div>
              <div class="view-toggle" id="sessionViewToggle">
                <button class="toggle-btn ${this._sessionViewMode === 'card' ? 'active' : ''}" data-action="changeSessionViewMode" data-value="card" title="Card View">🃏 Cards</button>
                <button class="toggle-btn ${this._sessionViewMode === 'table' ? 'active' : ''}" data-action="changeSessionViewMode" data-value="table" title="Table View">📋 Table</button>
              </div>
              <span style="font-size: 0.9rem; color: var(--text-muted);">
                ${this._getTotalSessionCount()} session(s)
              </span>
            </div>
          </div>

          <!-- Search Results (hidden by default) -->
          <div id="sessionSearchResults" style="display: none; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
              <h3 style="margin: 0; font-size: 1rem; color: var(--text-primary);">🔍 Search Results <span id="searchResultCount" style="color: var(--text-muted); font-weight: normal;"></span></h3>
              <button id="clearSearchBtn" class="btn btn-secondary" style="padding: 4px 12px; font-size: 0.8rem;">Clear Search</button>
            </div>
            <div id="searchResultsContent" class="workspaces-grid"></div>
          </div>

          <div class="workspaces-grid" id="workspacesGrid">
            ${this._renderWorkspaces()}
          </div>
        </div>

        <div class="section">
          <h2 class="section-title">📊 Session Stats</h2>
          <div class="grid-4">
            <div class="stat-card purple">
              <div class="stat-icon">🖥️</div>
              <div class="stat-value" id="totalWorkspaces">${this._workspaceCount || 0}</div>
              <div class="stat-label">Workspace</div>
            </div>
            <div class="stat-card orange">
              <div class="stat-icon">💬</div>
              <div class="stat-value" id="totalSessions">${this._getTotalSessionCount()}</div>
              <div class="stat-label">Sessions</div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">🤖</div>
              <div class="stat-value" id="uniquePersonas">${this._getUniquePersonaCount()}</div>
              <div class="stat-label">Personas</div>
            </div>
            <div class="stat-card green">
              <div class="stat-icon">📁</div>
              <div class="stat-value" id="uniqueProjects">${this._getUniqueProjectCount()}</div>
              <div class="stat-label">Projects</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Skills Tab -->
      <div class="tab-content ${this._currentTab === "skills" ? "active" : ""}" id="skills">
        <!-- Running Skills Panel -->
        <div class="running-skills-panel" id="runningSkillsPanel" style="display: none;">
          <div class="running-skills-header">
            <div class="running-skills-title">
              <span class="running-indicator"></span>
              <span id="runningSkillsCount">0</span> Running Skills
              <span id="staleSkillsWarning" class="stale-warning" style="display: none;" title="Some skills appear stuck">
                ⚠️ <span id="staleSkillsCount">0</span> stale
              </span>
            </div>
            <div class="running-skills-actions">
              <button class="btn btn-ghost btn-small btn-danger" id="clearStaleSkills" title="Clear stale/dead skill executions" style="display: none;">🗑️ Clear Stale</button>
              <button class="btn btn-ghost btn-small" id="toggleRunningSkills" title="Collapse">▼</button>
            </div>
          </div>
          <div class="running-skills-list" id="runningSkillsList">
            <!-- Populated dynamically -->
          </div>
        </div>

        <div class="skills-layout">
          <div class="skills-sidebar">
            <div class="skills-search">
              <input type="text" placeholder="Search skills..." id="skillSearch">
            </div>
            <div class="skills-list" id="skillsList">
              ${Object.entries(skillsByCategory).map(([category, catSkills]) => `
                <div class="skill-category" data-category="${category}">
                  <div class="skill-category-title">${category}</div>
                  ${catSkills.map(skill => `
                    <div class="skill-item" data-skill="${skill.name}">
                      <div class="skill-item-icon">${this._getSkillIcon(skill.name)}</div>
                      <div>
                        <div class="skill-item-name">${skill.name}</div>
                        <div class="skill-item-desc">${skill.description || ""}</div>
                      </div>
                    </div>
                  `).join("")}
                </div>
              `).join("")}
            </div>
          </div>
          <div class="skills-main">
            <div class="skills-main-header">
              <div class="skills-main-title"><span id="selectedSkillIcon" style="margin-right: 8px;"></span><span id="selectedSkillName">Select a skill</span></div>
              <div style="display: flex; gap: 8px; align-items: center;">
                <div class="view-toggle" id="skillViewToggle" style="display: none;">
                  <button class="toggle-btn active" data-view="info" title="Skill Info">📋 Info</button>
                  <button class="toggle-btn" data-view="workflow" title="Workflow Flowchart">🔀 Workflow</button>
                  <button class="toggle-btn" data-view="yaml" title="YAML Source">📝 Code</button>
                </div>
                <button class="btn btn-primary btn-small" data-action="runSelectedSkill">▶ Run</button>
                <button class="btn btn-ghost btn-small" data-action="openSelectedSkillFile">📄 Edit</button>
              </div>
            </div>
            <div class="skills-main-content" id="skillContent">
              <div class="empty-state">
                <div class="empty-state-icon">⚡</div>
                <div>Select a skill from the list</div>
                <div style="font-size: 0.8rem; margin-top: 8px;">Or run a skill to see its execution flowchart</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Services Tab -->
      <div class="tab-content ${this._currentTab === "services" ? "active" : ""}" id="services">
        <!-- Ollama Instance Status -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">🖥️ Ollama Instances</h2>
          </div>
          <div class="grid-4" id="ollamaInstances">
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">🟢 NPU</div>
                <div class="service-status" id="npuStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Host</span><span id="npuHost">:11434</span></div>
                <div class="service-row"><span>Model</span><span id="npuModel">qwen2.5:0.5b</span></div>
                <div class="service-row"><span>Power</span><span id="npuPower">2-5W</span></div>
                <div class="service-row"><span>Latency</span><span id="npuLatency">--</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-primary btn-small" data-instance="npu">Test</button>
              </div>
            </div>
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">🟡 iGPU</div>
                <div class="service-status" id="igpuStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Host</span><span id="igpuHost">:11435</span></div>
                <div class="service-row"><span>Model</span><span id="igpuModel">llama3.2:3b</span></div>
                <div class="service-row"><span>Power</span><span id="igpuPower">8-15W</span></div>
                <div class="service-row"><span>Latency</span><span id="igpuLatency">--</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-primary btn-small" data-instance="igpu">Test</button>
              </div>
            </div>
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">🟠 NVIDIA</div>
                <div class="service-status" id="nvidiaStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Host</span><span id="nvidiaHost">:11436</span></div>
                <div class="service-row"><span>Model</span><span id="nvidiaModel">llama3:7b</span></div>
                <div class="service-row"><span>Power</span><span id="nvidiaPower">40-60W</span></div>
                <div class="service-row"><span>Latency</span><span id="nvidiaLatency">--</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-primary btn-small" data-instance="nvidia">Test</button>
              </div>
            </div>
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">⚫ CPU</div>
                <div class="service-status" id="cpuStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Host</span><span id="cpuHost">:11437</span></div>
                <div class="service-row"><span>Model</span><span id="cpuModel">qwen2.5:0.5b</span></div>
                <div class="service-row"><span>Power</span><span id="cpuPower">15-35W</span></div>
                <div class="service-row"><span>Latency</span><span id="cpuLatency">--</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-primary btn-small" data-instance="cpu">Test</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Service Status Cards -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">🔌 Background Services</h2>
          </div>
          <div class="grid-2">
            <!-- Slack Agent -->
            <div class="service-card" id="slackServiceCard">
              <div class="service-header">
                <div class="service-title">💬 Slack Agent</div>
                <div class="service-status" id="slackStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content" id="slackDetails">
                <div class="service-row"><span>Status</span><span>Checking...</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="slack">▶ Start</button>
                <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="slack">⏹ Stop</button>
                <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="slack">📋 Logs</button>
              </div>
            </div>

            <!-- Cron Scheduler -->
            <div class="service-card" id="cronServiceCard">
              <div class="service-header">
                <div class="service-title">🕐 Cron Scheduler</div>
                <div class="service-status" id="cronStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content" id="cronDetails">
                <div class="service-row"><span>Status</span><span>Checking...</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="cron">▶ Start</button>
                <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="cron">⏹ Stop</button>
                <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="cron">📋 Logs</button>
              </div>
            </div>

            <!-- Meet Bot -->
            <div class="service-card" id="meetServiceCard">
              <div class="service-header">
                <div class="service-title">🎥 Meet Bot</div>
                <div class="service-status" id="meetStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content" id="meetDetails">
                <div class="service-row"><span>Status</span><span>Checking...</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="meet">▶ Start</button>
                <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="meet">⏹ Stop</button>
                <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="meet">📋 Logs</button>
              </div>
            </div>

            <!-- Sprint Bot -->
            <div class="service-card" id="sprintServiceCard">
              <div class="service-header">
                <div class="service-title">🏃 Sprint Bot</div>
                <div class="service-status" id="sprintStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content" id="sprintDetails">
                <div class="service-row"><span>Status</span><span>Checking...</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="sprint">▶ Start</button>
                <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="sprint">⏹ Stop</button>
                <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="sprint">📋 Logs</button>
              </div>
            </div>

            <!-- Video Bot -->
            <div class="service-card" id="videoServiceCard">
              <div class="service-header">
                <div class="service-title">📹 Video Bot</div>
                <div class="service-status" id="videoStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content" id="videoDetails">
                <div class="service-row"><span>Status</span><span>Checking...</span></div>
              </div>
              <div class="service-actions">
                <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="video">▶ Start</button>
                <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="video">⏹ Stop</button>
                <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="video">📋 Logs</button>
              </div>
            </div>

            <!-- MCP Server -->
            <div class="service-card" id="mcpServiceCard">
              <div class="service-header">
                <div class="service-title">🔧 MCP Server</div>
                <div class="service-status" id="mcpStatus">
                  <span class="status-dot checking"></span> Checking...
                </div>
              </div>
              <div class="service-content" id="mcpDetails">
                <div class="service-row"><span>Status</span><span>Checking...</span></div>
              </div>
              <div class="service-actions">
                <span class="text-muted" style="font-size: 0.8rem;">Managed by Cursor</span>
              </div>
            </div>
          </div>
        </div>

        <!-- D-Bus Explorer -->
        <div class="section" style="margin-top: 20px;">
          <h2 class="section-title">🔌 D-Bus Explorer</h2>
          <div class="service-card">
            <div class="service-content">
              <div class="dbus-controls">
                <select id="dbusService">
                  <option value="">Select Service...</option>
                  ${DBUS_SERVICES.map(s => `<option value="${s.name}">${s.icon} ${s.name}</option>`).join("")}
                </select>
                <select id="dbusMethod">
                  <option value="">Select Method...</option>
                </select>
                <button class="btn btn-primary btn-small" id="dbusQueryBtn">Execute</button>
              </div>
              <div class="dbus-args" id="dbusArgs" style="display: none; margin-top: 12px;">
                <!-- Dynamic argument inputs will be inserted here -->
              </div>
              <div class="dbus-result" id="dbusResult">
                Select a service and method to query
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Inference Tab -->
      <div class="tab-content ${this._currentTab === "inference" ? "active" : ""}" id="inference">
        <!-- Configuration -->
        <div class="section">
          <h2 class="section-title">⚙️ Tool Filtering Configuration</h2>
          <div class="card">
            <div class="grid-3">
              <div class="config-item">
                <label>Primary Engine</label>
                <select id="inferenceEngine" class="config-select">
                  <option value="npu" selected>NPU (qwen2.5:0.5b)</option>
                  <option value="igpu">iGPU (llama3.2:3b)</option>
                  <option value="nvidia">NVIDIA (llama3:7b)</option>
                  <option value="cpu">CPU (qwen2.5:0.5b)</option>
                </select>
              </div>
              <div class="config-item">
                <label>Fallback Strategy</label>
                <select id="fallbackStrategy" class="config-select">
                  <option value="keyword_match" selected>Keyword Match</option>
                  <option value="expanded_baseline">Expanded Baseline</option>
                  <option value="all_tools">All Tools (No Filter)</option>
                </select>
              </div>
              <div class="config-item">
                <label>Max Categories</label>
                <select id="maxCategories" class="config-select">
                  <option value="2">2</option>
                  <option value="3" selected>3</option>
                  <option value="4">4</option>
                  <option value="5">5</option>
                </select>
              </div>
            </div>
            <div class="config-toggles" style="margin-top: 16px;">
              <label class="toggle-label">
                <input type="checkbox" id="enableFiltering" checked>
                <span>Enable Tool Pre-filtering</span>
              </label>
              <label class="toggle-label">
                <input type="checkbox" id="enableNpu" checked>
                <span>Enable NPU (Layer 4)</span>
              </label>
              <label class="toggle-label">
                <input type="checkbox" id="enableCache" checked>
                <span>Enable Cache</span>
              </label>
            </div>
          </div>
        </div>

        <!-- Persona Statistics -->
        <div class="section">
          <h2 class="section-title">📊 Persona Tool Statistics</h2>
          <div class="table-container">
            <table class="data-table" id="personaStatsTable">
              <thead>
                <tr>
                  <th>Persona</th>
                  <th>Requests</th>
                  <th>Min Tools</th>
                  <th>Max Tools</th>
                  <th>Mean</th>
                  <th>Median</th>
                  <th>Tier 1 Only</th>
                  <th>Tier 2 (Skill)</th>
                  <th>Tier 3 (NPU)</th>
                </tr>
              </thead>
              <tbody id="personaStatsBody">
                <tr><td colspan="9" class="empty-state">No statistics yet</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Recent History -->
        <div class="section">
          <h2 class="section-title">📜 Recent Inference History</h2>
          <div class="history-list" id="inferenceHistory">
            <div class="empty-state">No inference history yet</div>
          </div>
        </div>

        <!-- Performance Metrics -->
        <div class="section">
          <h2 class="section-title">⏱️ Performance Metrics</h2>
          <div class="grid-4">
            <div class="stat-card purple">
              <div class="stat-icon">⚡</div>
              <div class="stat-value" id="avgLatency">--</div>
              <div class="stat-label">Avg Latency</div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">📉</div>
              <div class="stat-value" id="avgReduction">--</div>
              <div class="stat-label">Avg Reduction</div>
            </div>
            <div class="stat-card green">
              <div class="stat-icon">💾</div>
              <div class="stat-value" id="cacheHitRate">--</div>
              <div class="stat-label">Cache Hit Rate</div>
            </div>
            <div class="stat-card pink">
              <div class="stat-icon">🔢</div>
              <div class="stat-value" id="totalRequests">0</div>
              <div class="stat-label">Total Requests</div>
            </div>
          </div>
          <div class="latency-histogram" style="margin-top: 16px;">
            <h3 style="font-size: 14px; margin-bottom: 8px;">Latency Distribution</h3>
            <div class="histogram-bars" id="latencyHistogram">
              <div class="histogram-bar-container">
                <span class="histogram-label">&lt;10ms</span>
                <div class="histogram-bar" id="latency-10" style="width: 0%;"></div>
                <span class="histogram-value" id="latency-10-pct">0%</span>
              </div>
              <div class="histogram-bar-container">
                <span class="histogram-label">10-100ms</span>
                <div class="histogram-bar" id="latency-100" style="width: 0%;"></div>
                <span class="histogram-value" id="latency-100-pct">0%</span>
              </div>
              <div class="histogram-bar-container">
                <span class="histogram-label">100-500ms</span>
                <div class="histogram-bar" id="latency-500" style="width: 0%;"></div>
                <span class="histogram-value" id="latency-500-pct">0%</span>
              </div>
              <div class="histogram-bar-container">
                <span class="histogram-label">&gt;500ms</span>
                <div class="histogram-bar" id="latency-over" style="width: 0%;"></div>
                <span class="histogram-value" id="latency-over-pct">0%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Inference Context Inspector -->
        <div class="section">
          <h2 class="section-title">🧪 Inference Context Inspector</h2>
          <p style="color: var(--vscode-descriptionForeground); font-size: 12px; margin-bottom: 12px;">
            Preview the full context that would be sent to Claude for any message. Shows persona, memory, tools, and semantic knowledge.
          </p>
          <div class="card">
            <div class="inspector-form">
              <div class="form-row">
                <label>Test Message</label>
                <input type="text" id="testMessage" class="form-input" placeholder="deploy MR 1459 to ephemeral" />
              </div>
              <div class="form-row grid-2">
                <div>
                  <label>Persona (Auto-detect)</label>
                  <select id="testPersona" class="config-select">
                    <option value="" selected>Auto-detect from message</option>
                    <option value="developer">Developer</option>
                    <option value="devops">DevOps</option>
                    <option value="incident">Incident</option>
                    <option value="release">Release</option>
                  </select>
                </div>
                <div>
                  <label>Skill (Auto-detect)</label>
                  <select id="testSkill" class="config-select">
                    <option value="" selected>Auto-detect from message</option>
                    ${skills.map(s => `<option value="${s.name}">${s.name}</option>`).join('')}
                  </select>
                </div>
              </div>
              <div class="form-actions">
                <button class="btn btn-primary" id="runInferenceTest">🔍 Run Inference</button>
                <button class="btn btn-secondary" id="copyInferenceResult">📋 Copy Result</button>
              </div>
            </div>
            <div class="inspector-result" id="inferenceResult" style="display: none;">
              <div class="result-header">
                <span class="result-status" id="resultStatus">✅ 23 tools</span>
                <span class="result-meta" id="resultMeta">in 8ms (89.6% reduction)</span>
              </div>
              <div class="result-layers" id="resultLayers">
                <!-- Populated by JS -->
              </div>
              <div class="result-tools" id="resultTools">
                <!-- Populated by JS -->
              </div>
            </div>
            <div class="quick-tests" style="margin-top: 16px;">
              <span style="font-size: 12px; color: var(--text-muted);">Quick Tests:</span>
              <button class="btn btn-small btn-ghost" data-test="hello">hello</button>
              <button class="btn btn-small btn-ghost" data-test="MR 1459">MR 1459</button>
              <button class="btn btn-small btn-ghost" data-test="AAP-12345">AAP-12345</button>
              <button class="btn btn-small btn-ghost" data-test="deploy MR 1459">deploy MR</button>
              <button class="btn btn-small btn-ghost" data-test="debug error">debug error</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Meetings Tab -->
      <div class="tab-content ${this._currentTab === "meetings" ? "active" : ""}" id="meetings">
        ${getMeetingsTabContent(meetBotState, this._panel.webview)}
      </div>

      <!-- Performance Tab -->
      <div class="tab-content ${this._currentTab === "performance" ? "active" : ""}" id="performance">
        ${getPerformanceTabContent(performanceState)}
      </div>

      <!-- Slack Tab -->
      <div class="tab-content ${this._currentTab === "slack" ? "active" : ""}" id="slack">
        <!-- Slack Agent Status -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">💬 Slack Agent</h2>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="slack">▶ Start</button>
              <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="slack">⏹ Stop</button>
              <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="slack">📋 Logs</button>
            </div>
          </div>
          <div class="grid-4">
            <div class="stat-card" id="slackStatusCard">
              <div class="stat-icon">📡</div>
              <div class="stat-value" id="slackAgentStatus">--</div>
              <div class="stat-label">Status</div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">⏱️</div>
              <div class="stat-value" id="slackUptime">--</div>
              <div class="stat-label">Uptime</div>
            </div>
            <div class="stat-card purple">
              <div class="stat-icon">📨</div>
              <div class="stat-value" id="slackProcessed">0</div>
              <div class="stat-label">Processed</div>
            </div>
            <div class="stat-card pink">
              <div class="stat-icon">⏳</div>
              <div class="stat-value" id="slackPending">0</div>
              <div class="stat-label">Pending</div>
            </div>
          </div>
          <div class="grid-4" style="margin-top: 12px;">
            <div class="stat-card blue">
              <div class="stat-icon">🔄</div>
              <div class="stat-value" id="slackPolls">0</div>
              <div class="stat-label">Polls</div>
            </div>
            <div class="stat-card green">
              <div class="stat-icon">💬</div>
              <div class="stat-value" id="slackResponded">0</div>
              <div class="stat-label">Responded</div>
            </div>
            <div class="stat-card orange">
              <div class="stat-icon">👀</div>
              <div class="stat-value" id="slackSeen">0</div>
              <div class="stat-label">Seen</div>
            </div>
            <div class="stat-card" id="slackErrorsCard">
              <div class="stat-icon">❌</div>
              <div class="stat-value" id="slackErrors">0</div>
              <div class="stat-label">Errors</div>
            </div>
          </div>
        </div>

        <!-- Message Composer -->
        <div class="section">
          <h2 class="section-title">✍️ Send Message</h2>
          <div class="service-card">
            <div class="service-content">
              <!-- Target Type Toggle -->
              <div style="display: flex; gap: 8px; margin-bottom: 12px;">
                <div class="view-toggle" id="slackTargetToggle">
                  <button class="toggle-btn active" data-action="setSlackTarget" data-value="channel" title="Send to Channel">#️⃣ Channel</button>
                  <button class="toggle-btn" data-action="setSlackTarget" data-value="user" title="Direct Message">👤 User</button>
                </div>
                <button class="btn btn-ghost btn-small" data-action="refreshSlackTargets" title="Refresh channels and users">🔄</button>
                <button class="btn btn-primary btn-small" data-action="openCommandBuilder" title="Build @me command">🤖 @me</button>
              </div>
              <!-- Channel Select (shown by default) -->
              <div id="slackChannelContainer" style="display: flex; gap: 12px; margin-bottom: 12px;">
                <select id="slackChannel" style="flex: 1; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary);">
                  <option value="">Select Channel...</option>
                </select>
              </div>
              <!-- User Select (hidden by default) -->
              <div id="slackUserContainer" style="display: none; gap: 12px; margin-bottom: 12px;">
                <div style="flex: 1; position: relative;">
                  <input type="text" id="slackUserSearch" placeholder="Search users..." style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary);">
                  <div id="slackUserResults" class="slack-user-dropdown" style="display: none; position: absolute; top: 100%; left: 0; right: 0; max-height: 200px; overflow-y: auto; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 6px; margin-top: 4px; z-index: 100;"></div>
                </div>
                <input type="hidden" id="slackSelectedUser" value="">
                <div id="slackSelectedUserDisplay" style="display: none; padding: 8px 12px; background: var(--bg-tertiary); border-radius: 6px; align-items: center; gap: 8px;">
                  <span id="slackSelectedUserName"></span>
                  <button class="btn btn-ghost btn-small" data-action="clearSlackUser" style="padding: 2px 6px;">✕</button>
                </div>
              </div>
              <!-- Message Input -->
              <div style="display: flex; gap: 12px;">
                <input type="text" id="slackMessageInput" placeholder="Type a message..." style="flex: 1; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary);">
                <button class="btn btn-primary" data-action="sendSlackMessage">Send</button>
              </div>
            </div>
          </div>
        </div>

        <!-- Pending Approvals -->
        <div class="section" id="slackPendingSection">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">⏳ Pending Approvals <span id="slackPendingBadge" class="badge" style="display: none;">0</span></h2>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-ghost btn-small" data-action="approveAllSlack" title="Approve all pending">✅ Approve All</button>
              <button class="btn btn-ghost btn-small" data-action="refreshSlackPending" title="Refresh">🔄</button>
            </div>
          </div>
          <div class="service-card">
            <div id="slackPendingList" style="max-height: 300px; overflow-y: auto;">
              <div class="empty-state">
                <div class="empty-state-icon">✅</div>
                <div>No pending approvals</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Message Search -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">🔍 Search Messages</h2>
            <span id="slackSearchRemaining" style="font-size: 0.75rem; color: var(--text-secondary);"></span>
          </div>
          <div class="service-card">
            <div class="service-content">
              <div style="display: flex; gap: 12px; margin-bottom: 12px;">
                <input type="text" id="slackSearchInput" placeholder="Search Slack messages..." style="flex: 1; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary);">
                <button class="btn btn-primary" data-action="searchSlackMessages">Search</button>
              </div>
              <div id="slackSearchResults" style="max-height: 300px; overflow-y: auto;">
                <div class="empty-state" style="padding: 20px;">
                  <div class="empty-state-icon">🔍</div>
                  <div>Enter a search query</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Message Feed -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">📬 Message Feed</h2>
          </div>
          <div class="service-card">
            <div class="slack-messages" id="slackMessages" style="max-height: 500px;">
              <div class="empty-state">
                <div class="empty-state-icon">💬</div>
                <div>No messages yet</div>
                <div style="font-size: 0.8rem; margin-top: 8px; color: var(--text-muted);">Messages will appear automatically</div>
              </div>
            </div>
          </div>
        </div>

        <!-- Channel & User Browser -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">📚 Discovery</h2>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-ghost btn-small" data-action="refreshSlackCache" title="Refresh cache from Slack API">🔄 Refresh Cache</button>
            </div>
          </div>
          <div class="grid-2">
            <!-- Channel Browser -->
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">📢 Channels</div>
                <span id="slackChannelCount" style="font-size: 0.75rem; color: var(--text-secondary);">0 channels</span>
              </div>
              <div class="service-content" style="padding: 8px;">
                <input type="text" id="slackChannelSearch" placeholder="Filter channels..." style="width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary); margin-bottom: 8px; font-size: 0.85rem;">
                <div id="slackChannelBrowser" style="max-height: 250px; overflow-y: auto;">
                  <div class="empty-state" style="padding: 20px;">
                    <div>Loading channels...</div>
                  </div>
                </div>
              </div>
            </div>
            <!-- User Browser -->
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">👥 Users</div>
                <span id="slackUserCount" style="font-size: 0.75rem; color: var(--text-secondary);">0 users</span>
              </div>
              <div class="service-content" style="padding: 8px;">
                <input type="text" id="slackUserBrowserSearch" placeholder="Filter users..." style="width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary); margin-bottom: 8px; font-size: 0.85rem;">
                <div id="slackUserBrowser" style="max-height: 250px; overflow-y: auto;">
                  <div class="empty-state" style="padding: 20px;">
                    <div>Loading users...</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Cache Stats -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">📊 Cache Statistics</h2>
          </div>
          <div class="grid-2">
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">📢 Channel Cache</div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Total Channels</span><span id="slackCacheChannelTotal">--</span></div>
                <div class="service-row"><span>Member Channels</span><span id="slackCacheChannelMember">--</span></div>
                <div class="service-row"><span>Cache Age</span><span id="slackCacheChannelAge">--</span></div>
              </div>
            </div>
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">👥 User Cache</div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Total Users</span><span id="slackCacheUserTotal">--</span></div>
                <div class="service-row"><span>With Avatar</span><span id="slackCacheUserAvatar">--</span></div>
                <div class="service-row"><span>With Email</span><span id="slackCacheUserEmail">--</span></div>
                <div class="service-row"><span>Cache Age</span><span id="slackCacheUserAge">--</span></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Bot Configuration -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">⚙️ Bot Configuration</h2>
            <button class="btn btn-ghost btn-small" data-action="loadSlackConfig" title="Reload configuration">🔄 Reload</button>
          </div>
          <div class="grid-2">
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">🔧 Quick Settings</div>
              </div>
              <div class="service-content">
                <div class="service-row" style="justify-content: space-between;">
                  <span>Debug Mode</span>
                  <label class="toggle-switch">
                    <input type="checkbox" id="slackDebugModeToggle" onchange="toggleSlackDebugMode(this.checked)">
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">When enabled, bot processes but doesn't respond</div>
              </div>
            </div>
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">📋 Config Summary</div>
              </div>
              <div class="service-content">
                <div class="service-row"><span>Watched Channels</span><span id="slackConfigWatchedCount">--</span></div>
                <div class="service-row"><span>Alert Channels</span><span id="slackConfigAlertCount">--</span></div>
                <div class="service-row"><span>Safe Users</span><span id="slackConfigSafeCount">--</span></div>
                <div class="service-row"><span>Concerned Users</span><span id="slackConfigConcernedCount">--</span></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Quick Reply Modal -->
        <div class="quick-reply-modal" id="quickReplyModal" onclick="if(event.target === this) hideQuickReply()">
          <div class="quick-reply-content" onclick="event.stopPropagation()">
            <div class="quick-reply-header">
              <div>
                <div class="quick-reply-title">↩️ Reply in Thread</div>
                <div class="quick-reply-channel" id="quickReplyChannelLabel"></div>
              </div>
              <button class="btn btn-ghost btn-small" onclick="hideQuickReply()">✕</button>
            </div>
            <textarea class="quick-reply-input" id="quickReplyInput" placeholder="Type your reply..." onkeydown="if(event.key === 'Enter' && (event.metaKey || event.ctrlKey)) sendQuickReply()"></textarea>
            <div class="quick-reply-actions">
              <button class="btn btn-ghost" onclick="hideQuickReply()">Cancel</button>
              <button class="btn btn-primary" onclick="sendQuickReply()">Send Reply</button>
            </div>
          </div>
        </div>

        <!-- Command Builder Modal -->
        <div class="quick-reply-modal" id="commandBuilderModal" onclick="if(event.target === this) hideCommandBuilder()">
          <div class="quick-reply-content" style="max-width: 600px;" onclick="event.stopPropagation()">
            <div class="quick-reply-header">
              <div>
                <div class="quick-reply-title">🤖 @me Command Builder</div>
                <div class="quick-reply-channel">Build and send @me commands</div>
              </div>
              <button class="btn btn-ghost btn-small" onclick="hideCommandBuilder()">✕</button>
            </div>

            <!-- Command Selection -->
            <div style="margin-bottom: 16px;">
              <label style="display: block; font-size: 0.85rem; margin-bottom: 6px; font-weight: 500;">Select Command</label>
              <select id="commandBuilderSelect" onchange="onCommandSelect()" style="width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; background: var(--bg-secondary); color: var(--text-primary);">
                <option value="">Choose a command...</option>
              </select>
            </div>

            <!-- Command Description -->
            <div id="commandBuilderDescription" style="display: none; margin-bottom: 16px; padding: 12px; background: var(--bg-tertiary); border-radius: 6px; font-size: 0.85rem;">
            </div>

            <!-- Command Parameters -->
            <div id="commandBuilderParams" style="display: none; margin-bottom: 16px;">
              <label style="display: block; font-size: 0.85rem; margin-bottom: 6px; font-weight: 500;">Parameters</label>
              <div id="commandBuilderParamInputs"></div>
            </div>

            <!-- Command Preview -->
            <div id="commandBuilderPreview" style="display: none; margin-bottom: 16px;">
              <label style="display: block; font-size: 0.85rem; margin-bottom: 6px; font-weight: 500;">Preview</label>
              <code id="commandBuilderPreviewText" style="display: block; padding: 10px 12px; background: var(--bg-tertiary); border-radius: 6px; font-size: 0.85rem; word-break: break-all;"></code>
            </div>

            <div class="quick-reply-actions">
              <button class="btn btn-ghost" onclick="hideCommandBuilder()">Cancel</button>
              <button class="btn btn-primary" id="commandBuilderSendBtn" onclick="sendBuiltCommand()" disabled>Send Command</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Tools Tab -->
      <div class="tab-content ${this._currentTab === "tools" ? "active" : ""}" id="tools">
        <!-- Active Agent -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">🔧 MCP Tools</h2>
            <div class="agent-badge">
              <span class="agent-badge-dot"></span>
              <span>Agent: ${activeAgent.name}</span>
              <span style="color: var(--text-muted);">(${activeAgent.tools.length} modules)</span>
            </div>
          </div>

          <div class="tools-container">
            <!-- Modules Sidebar -->
            <div class="tools-sidebar">
              <div class="tools-search">
                <input type="text" placeholder="Search tools..." id="toolSearch">
              </div>
              <div class="tools-modules-list" id="toolModulesList">
                ${toolModules.map(mod => `
                  <div class="tool-module-item ${activeAgent.tools.includes(mod.name) ? "active" : ""}" data-module="${mod.name}">
                    <div class="tool-module-name">
                      ${this._getModuleIcon(mod.name)} ${mod.displayName}
                      <span class="tool-module-count">${mod.toolCount}</span>
                    </div>
                    <div class="tool-module-desc">${mod.description}</div>
                  </div>
                `).join("")}
              </div>
            </div>

            <!-- Tools Main -->
            <div class="tools-main">
              <div class="tools-main-header">
                <div class="tools-main-title" id="selectedModuleName">Select a module</div>
                <div>
                  <span id="toolCountBadge" style="font-size: 0.8rem; color: var(--text-muted);"></span>
                </div>
              </div>
              <div class="tools-main-content" id="toolsContent">
                <div class="empty-state">
                  <div class="empty-state-icon">🔧</div>
                  <div>Select a module from the list</div>
                  <div style="font-size: 0.8rem; margin-top: 8px;">
                    ${toolModules.reduce((sum, m) => sum + m.toolCount, 0)} tools available across ${toolModules.length} modules
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Personas Tab -->
      <div class="tab-content ${this._currentTab === "personas" ? "active" : ""}" id="personas">
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h2 class="section-title" style="margin: 0;">🤖 Available Personas</h2>
            <div style="display: flex; gap: 12px; align-items: center;">
              <div class="view-toggle" id="personaViewToggle">
                <button class="toggle-btn ${this._personaViewMode === 'card' ? 'active' : ''}" data-action="changePersonaViewMode" data-value="card" title="Card View">🃏 Cards</button>
                <button class="toggle-btn ${this._personaViewMode === 'table' ? 'active' : ''}" data-action="changePersonaViewMode" data-value="table" title="Table View">📋 Table</button>
              </div>
              <span style="font-size: 0.9rem; color: var(--text-muted);">
                ${personas.length} personas configured
              </span>
            </div>
          </div>

          ${this._personaViewMode === 'table' ? `
          <div class="personas-table-container">
            <table class="data-table">
              <thead>
                <tr>
                  <th></th>
                  <th style="text-align: left;">Name</th>
                  <th style="text-align: left;">Description</th>
                  <th>Tools</th>
                  <th>Skills</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                ${personas.map(persona => {
                  const isActive = activeAgent.name === persona.name || activeAgent.name === persona.fileName;
                  const displayFileName = persona.fileName || persona.name;
                  const typeBadge = persona.isSlim ? ' <span class="persona-type-badge slim">slim</span>' :
                                   persona.isInternal ? ' <span class="persona-type-badge internal">internal</span>' :
                                   persona.isAgent ? ' <span class="persona-type-badge agent">agent</span>' : '';
                  return `
                  <tr class="${isActive ? 'row-active' : ''}">
                    <td><span class="persona-icon-small ${this._getPersonaColor(persona.name)}">${this._getPersonaIcon(persona.name)}</span></td>
                    <td style="text-align: left;"><strong>${persona.name}</strong>${typeBadge}${isActive ? ' <span class="active-badge-small">Active</span>' : ''}</td>
                    <td style="text-align: left;">${persona.description || displayFileName}</td>
                    <td title="${persona.tools.length} modules: ${persona.tools.join(', ')}">${persona.toolCount}</td>
                    <td>${persona.skills.length || 'all'}</td>
                    <td>
                      <button class="btn btn-${isActive ? "ghost" : "primary"} btn-small" data-action="loadPersona" data-persona="${displayFileName}" ${isActive ? "disabled" : ""} title="${isActive ? "Currently active" : "Load this persona"}">
                        ${isActive ? "✓" : "🔄"}
                      </button>
                      <button class="btn btn-ghost btn-small" data-action="viewPersonaFile" data-persona="${displayFileName}" title="View persona config file">📄</button>
                    </td>
                  </tr>
                  `;
                }).join("")}
              </tbody>
            </table>
          </div>
          ` : `
          <div class="personas-grid">
            ${this._renderPersonaCards(personas, activeAgent)}
          </div>
          `}

        </div>
      </div>

      <!-- Memory Tab -->
      <div class="tab-content ${this._currentTab === "memory" ? "active" : ""}" id="memory">
        <!-- Memory Stats -->
        <div class="section">
          <h2 class="section-title">📊 Memory Health</h2>
          <div class="grid-5">
            <div class="stat-card purple">
              <div class="stat-icon">💾</div>
              <div class="stat-value" id="memTotalSize">${memoryHealth.totalSize}</div>
              <div class="stat-label">Total Size</div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">📝</div>
              <div class="stat-value" id="memSessionLogs">${memoryHealth.sessionLogs}</div>
              <div class="stat-label">Session Logs</div>
            </div>
            <div class="stat-card pink">
              <div class="stat-icon">🧠</div>
              <div class="stat-value" id="memPatterns">${memoryHealth.patterns}</div>
              <div class="stat-label">Patterns</div>
            </div>
            <div class="stat-card orange">
              <div class="stat-icon">📚</div>
              <div class="stat-value" id="memKnowledge">${memoryFiles.knowledge.length}</div>
              <div class="stat-label">Knowledge</div>
            </div>
            <div class="stat-card green">
              <div class="stat-icon">📅</div>
              <div class="stat-value" id="memLastSession" style="font-size: 1rem;">${memoryHealth.lastSession}</div>
              <div class="stat-label">Last Session</div>
            </div>
          </div>
        </div>

        <!-- Memory Browser -->
        <div class="section">
          <h2 class="section-title">📁 Memory Browser</h2>
          <div class="memory-grid">
            <div class="card">
              <div class="card-header">
                <div class="card-icon purple">📋</div>
                <div class="card-title">State Files</div>
              </div>
              <div class="memory-list">
                ${memoryFiles.state.map(f => `
                  <div class="memory-item">
                    <div class="memory-item-icon">📄</div>
                    <div class="memory-item-name">${f}</div>
                  </div>
                `).join("") || '<div class="empty-state">No state files</div>'}
              </div>
            </div>
            <div class="card">
              <div class="card-header">
                <div class="card-icon cyan">🧠</div>
                <div class="card-title">Learned Patterns</div>
              </div>
              <div class="memory-list">
                ${memoryFiles.learned.map(f => `
                  <div class="memory-item">
                    <div class="memory-item-icon">📄</div>
                    <div class="memory-item-name">${f}</div>
                  </div>
                `).join("") || '<div class="empty-state">No learned files</div>'}
              </div>
            </div>
          </div>
        </div>

        <!-- Project Knowledge -->
        <div class="section">
          <h2 class="section-title">📚 Project Knowledge</h2>
          <div class="card">
            <div class="card-header">
              <div class="card-icon green">🎓</div>
              <div class="card-title">Indexed Projects</div>
            </div>
            <div class="memory-list">
              ${memoryFiles.knowledge.length > 0 ? memoryFiles.knowledge.map(k => `
                <div class="memory-item" style="display: flex; justify-content: space-between; align-items: center;">
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <div class="memory-item-icon">📦</div>
                    <div class="memory-item-name">${k.project}</div>
                    <span class="badge" style="background: var(--purple); font-size: 0.7rem;">${k.persona}</span>
                  </div>
                  <div style="display: flex; align-items: center; gap: 8px;">
                    <div class="progress-bar" style="width: 60px; height: 6px; background: var(--bg-tertiary); border-radius: 3px; overflow: hidden;">
                      <div style="width: ${k.confidence}%; height: 100%; background: ${k.confidence >= 70 ? 'var(--green)' : k.confidence >= 40 ? 'var(--yellow)' : 'var(--red)'}; border-radius: 3px;"></div>
                    </div>
                    <span style="font-size: 0.75rem; color: var(--text-secondary); min-width: 35px;">${k.confidence}%</span>
                  </div>
                </div>
              `).join("") : `
                <div class="empty-state">
                  <p>No project knowledge indexed yet.</p>
                  <p style="font-size: 0.8rem; color: var(--text-tertiary);">Run <code>knowledge_scan("project-name")</code> to index a project.</p>
                </div>
              `}
            </div>
          </div>
        </div>

        <!-- Vector Search -->
        <div class="section">
          <h2 class="section-title">🔍 Vector Search</h2>
          <div class="grid-4">
            <div class="stat-card purple">
              <div class="stat-icon">📦</div>
              <div class="stat-value">${vectorStats.totals.indexedCount}</div>
              <div class="stat-label">Indexed Projects</div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">🧩</div>
              <div class="stat-value">${vectorStats.totals.totalChunks.toLocaleString()}</div>
              <div class="stat-label">Code Chunks</div>
            </div>
            <div class="stat-card pink">
              <div class="stat-icon">💾</div>
              <div class="stat-value">${vectorStats.totals.totalSize}</div>
              <div class="stat-label">Disk Usage</div>
            </div>
            <div class="stat-card green">
              <div class="stat-icon">🔎</div>
              <div class="stat-value">${vectorStats.totals.totalSearches.toLocaleString()}</div>
              <div class="stat-label">Total Searches</div>
            </div>
          </div>
          ${vectorStats.projects.filter(p => p.indexed).length > 0 ? `
          <div class="card" style="margin-top: 12px;">
            <div class="card-header">
              <div class="card-icon cyan">🗄️</div>
              <div class="card-title">Indexed Projects</div>
            </div>
            <div class="vector-projects-table">
              <table>
                <thead>
                  <tr>
                    <th class="col-status"></th>
                    <th class="col-project">Project</th>
                    <th class="col-files">Files</th>
                    <th class="col-chunks">Chunks</th>
                    <th class="col-size">Size</th>
                    <th class="col-searches">Searches</th>
                    <th class="col-avg">Avg Time</th>
                    <th class="col-age">Last Indexed</th>
                  </tr>
                </thead>
                <tbody>
                  ${vectorStats.projects.filter(p => p.indexed).map(p => `
                  <tr class="${p.isStale ? 'stale' : ''}">
                    <td class="col-status">${p.isStale ? '⚠️' : '✅'}</td>
                    <td class="col-project">
                      <span class="project-name">${p.project}</span>
                    </td>
                    <td class="col-files">${p.files?.toLocaleString()}</td>
                    <td class="col-chunks">${p.chunks?.toLocaleString()}</td>
                    <td class="col-size">${p.diskSize}</td>
                    <td class="col-searches">${p.searches}</td>
                    <td class="col-avg">${p.avgSearchMs?.toFixed(0)}ms</td>
                    <td class="col-age ${p.isStale ? 'stale-text' : ''}">${p.indexAge}</td>
                  </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
          </div>
          ` : `
          <div class="card" style="margin-top: 12px;">
            <div class="empty-state">
              <p>No projects indexed for vector search.</p>
              <p style="font-size: 0.8rem; color: var(--text-tertiary);">Run <code>code_index("project-name")</code> to index a project.</p>
            </div>
          </div>
          `}

          <!-- Semantic Search Box -->
          <div class="semantic-search-container">
            <div class="card">
              <div class="card-header">
                <div class="card-icon purple">🔮</div>
                <div class="card-title">Semantic Code Search</div>
              </div>
              <div style="padding: 16px;">
                <p style="margin: 0 0 12px 0; font-size: 0.85rem; color: var(--text-secondary);">
                  Ask questions about your code in natural language. The search finds code by meaning, not just text matching.
                </p>
                <div class="semantic-search-box">
                  <textarea
                    id="semanticSearchInput"
                    placeholder="e.g., How does billing calculate vCPU hours?"
                    rows="3"
                  ></textarea>
                  <select id="semanticSearchProject">
                    <option value="">Select project...</option>
                    <option value="__all__">🔍 Search All Projects</option>
                    ${vectorStats.projects.filter(p => p.indexed).map(p => `
                      <option value="${p.project}" ${currentWork.activeRepo === p.project ? 'selected' : ''}>${p.project}${currentWork.activeRepo === p.project ? ' (active)' : ''}</option>
                    `).join("")}
                  </select>
                  <button class="btn btn-primary" id="semanticSearchBtn">
                    🔍 Search
                  </button>
                </div>
                ${currentWork.activeRepo ? `
                <p style="margin: 8px 0 0 0; font-size: 0.8rem; color: var(--text-tertiary);">
                  📍 Working on <strong>${currentWork.activeIssue?.key || 'issue'}</strong> in <code style="background: var(--bg-tertiary); padding: 2px 6px; border-radius: 4px;">${currentWork.activeRepo}</code>
                </p>
                ` : ''}
                <div id="semanticSearchResults">
                  <div class="search-empty">
                    <div style="font-size: 2rem; margin-bottom: 8px;">🔮</div>
                    <div>Enter a question to search your indexed code</div>
                    <div style="font-size: 0.8rem; margin-top: 8px; color: var(--text-tertiary);">
                      Examples: "Where is authentication handled?", "How do we validate API input?"
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Recent Sessions -->
        <div class="section">
          <h2 class="section-title">📅 Recent Sessions</h2>
          <div class="card">
            <div class="memory-list">
              ${memoryFiles.sessions.map(f => `
                <div class="memory-item">
                  <div class="memory-item-icon">📝</div>
                  <div class="memory-item-name">${f.replace(".yaml", "")}</div>
                </div>
              `).join("") || '<div class="empty-state">No session logs</div>'}
            </div>
          </div>
        </div>
      </div>

      <!-- Cron Tab -->
      <div class="tab-content ${this._currentTab === "cron" ? "active" : ""}" id="cron">
        <!-- Cron Status -->
        <div class="section">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 class="section-title" style="margin: 0;">🕐 Scheduler Status</h2>
            <div style="display: flex; gap: 8px;">
              <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="cron">▶ Start</button>
              <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="cron">⏹ Stop</button>
              <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="cron">📋 Logs</button>
            </div>
          </div>
          <div class="grid-4">
            <div class="stat-card ${cronConfig.enabled ? "green" : ""} clickable" id="cronEnabledCard" data-action="toggleScheduler" title="Click to ${cronConfig.enabled ? 'disable' : 'enable'} scheduler">
              <div class="stat-icon" id="cronEnabledIcon">${cronConfig.enabled ? "✅" : "⏸️"}</div>
              <div class="stat-value" id="cronEnabled">${cronConfig.enabled ? "Active" : "Disabled"}</div>
              <div class="stat-label">Scheduler</div>
              <button class="btn ${cronConfig.enabled ? 'btn-secondary' : 'btn-primary'} btn-small" style="margin-top: 8px;" data-action="toggleScheduler">
                ${cronConfig.enabled ? "⏸️ Disable" : "▶️ Enable"}
              </button>
            </div>
            <div class="stat-card purple">
              <div class="stat-icon">📋</div>
              <div class="stat-value" id="cronJobCount">${cronConfig.jobs.length}</div>
              <div class="stat-label">Total Jobs</div>
            </div>
            <div class="stat-card cyan">
              <div class="stat-icon">▶️</div>
              <div class="stat-value" id="cronEnabledCount">${cronConfig.jobs.filter(j => j.enabled).length}</div>
              <div class="stat-label">Enabled</div>
            </div>
            <div class="stat-card pink">
              <div class="stat-icon">🌍</div>
              <div class="stat-value" id="cronTimezone" style="font-size: 1rem;">${cronConfig.timezone}</div>
              <div class="stat-label">Timezone</div>
            </div>
          </div>
          <div class="grid-2" style="margin-top: 12px;">
            <div class="stat-card ${cronConfig.execution_mode === 'claude_cli' ? 'green' : 'orange'}">
              <div class="stat-icon">${cronConfig.execution_mode === 'claude_cli' ? '🤖' : '⚡'}</div>
              <div class="stat-value" style="font-size: 0.9rem;">${cronConfig.execution_mode === 'claude_cli' ? 'Claude CLI' : 'Direct'}</div>
              <div class="stat-label">Execution Mode</div>
            </div>
            <div class="stat-card">
              <div class="stat-icon">📁</div>
              <div class="stat-value" style="font-size: 0.75rem;">~/.config/aa-workflow/cron_logs/</div>
              <div class="stat-label">Log Directory</div>
            </div>
          </div>
        </div>

        <!-- Scheduled Jobs -->
        <div class="section">
          <h2 class="section-title">📅 Scheduled Jobs</h2>
          <div class="card">
            <div class="card-header" style="justify-content: space-between;">
              <div style="display: flex; align-items: center; gap: 12px;">
                <div class="card-icon purple">📋</div>
                <div class="card-title">Cron Jobs</div>
              </div>
              <button class="btn btn-ghost btn-small" data-action="openConfigFile">⚙️ Edit Config</button>
            </div>
            <div class="cron-jobs-list">
              ${cronConfig.jobs.length === 0 ? `
                <div class="empty-state">
                  <div class="empty-state-icon">🕐</div>
                  <div>No cron jobs configured</div>
                  <div style="font-size: 0.8rem; margin-top: 8px;">Add jobs to config.json schedules section</div>
                  <button class="btn btn-primary btn-small" style="margin-top: 12px;" data-action="openConfigFile">Open Config</button>
                </div>
              ` : cronConfig.jobs.map(job => `
                <div class="cron-job-item ${job.enabled ? "" : "disabled"}" data-job="${job.name}">
                  <div class="cron-job-toggle">
                    <label class="toggle-switch">
                      <input type="checkbox" ${job.enabled ? "checked" : ""}>
                      <span class="toggle-slider"></span>
                    </label>
                  </div>
                  <div class="cron-job-info">
                    <div class="cron-job-name">${job.name}</div>
                    <div class="cron-job-desc">${job.description || `Runs skill: ${job.skill}`}</div>
                    <div class="cron-job-schedule">
                      ${job.cron ? `<span class="cron-badge cron">⏰ ${job.cron}</span>` : ""}
                      ${job.trigger === "poll" ? `<span class="cron-badge poll">🔄 Poll: ${job.poll_interval || "5m"}</span>` : ""}
                      <span class="cron-badge skill">⚡ ${job.skill}</span>
                      ${job.persona ? `<span class="cron-badge persona">👤 ${job.persona}</span>` : ""}
                      ${job.notify ? `<span class="cron-badge notify">🔔 ${job.notify.join(", ")}</span>` : ""}
                    </div>
                  </div>
                  <div class="cron-job-actions">
                    <button class="btn btn-ghost btn-small" data-run-job="${job.name}" title="Run now">▶️</button>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>
        </div>

        <!-- Execution History -->
        <div class="section">
          <h2 class="section-title">📜 Recent Executions</h2>
          <div class="card">
            <div class="cron-history-list" data-current-limit="10" data-total="${this.getCronHistoryTotal()}">
              ${cronHistory.length === 0 ? `
                <div class="empty-state">
                  <div class="empty-state-icon">📜</div>
                  <div>No execution history</div>
                  <div style="font-size: 0.8rem; margin-top: 8px;">Jobs will appear here after they run</div>
                </div>
              ` : cronHistory.slice(0, 10).map(exec => {
                // Format duration with color coding
                const formatDuration = (ms: number | undefined) => {
                  if (!ms) return "";
                  const seconds = Math.floor(ms / 1000);
                  const minutes = Math.floor(seconds / 60);
                  const isTimeout = ms >= 600000; // 10 minutes
                  const isSlow = ms >= 300000; // 5 minutes
                  const durationClass = isTimeout ? "timeout" : isSlow ? "slow" : "fast";
                  const durationText = minutes >= 1 ? `${minutes}m ${seconds % 60}s` : `${seconds}s`;
                  const icon = isTimeout ? "⏰" : "⏱️";
                  return `<span class="cron-history-duration ${durationClass}">${icon} ${durationText}</span>`;
                };

                // Categorize error type
                const categorizeError = (error: string | undefined) => {
                  if (!error) return null;
                  let errorType = "Error";
                  let errorIcon = "❌";
                  if (error.includes("timed out") || error.includes("timeout")) {
                    errorType = "Timeout";
                    errorIcon = "⏰";
                  } else if (error.includes("API Error") || error.includes("oauth2") || error.includes("getaddrinfo")) {
                    errorType = "Network/API Error";
                    errorIcon = "🌐";
                  } else if (error.includes("exited with code")) {
                    errorType = "Process Error";
                    errorIcon = "💥";
                  } else if (error.includes("permission") || error.includes("unauthorized")) {
                    errorType = "Auth Error";
                    errorIcon = "🔒";
                  }
                  return { type: errorType, icon: errorIcon, message: error };
                };

                const errorInfo = categorizeError(exec.error);

                return `
                <div class="cron-history-item ${exec.success ? "success" : "failed"}">
                  <div class="cron-history-status">${exec.success ? "✅" : "❌"}</div>
                  <div class="cron-history-info">
                    <div class="cron-history-name">${exec.job_name}</div>
                    ${exec.session_name ? `<div class="cron-history-session">💬 ${exec.session_name}</div>` : ""}
                    <div class="cron-history-details">
                      <span>⚡ ${exec.skill}</span>
                      ${formatDuration(exec.duration_ms)}
                      <span>🕐 ${new Date(exec.timestamp).toLocaleString()}</span>
                    </div>
                    ${errorInfo ? `
                      <div class="cron-history-error">
                        <div class="cron-history-error-type">${errorInfo.icon} ${errorInfo.type}</div>
                        <div class="cron-history-error-message">${errorInfo.message}</div>
                      </div>
                    ` : ""}
                    ${exec.output_preview ? `<div class="cron-history-output">${exec.output_preview}</div>` : ""}
                  </div>
                </div>
              `}).join("")}
            </div>
            ${this.getCronHistoryTotal() > 10 ? `
              <div class="cron-history-load-more">
                <button class="btn btn-ghost" data-action="loadMoreCronHistory" data-current="10">
                  📜 Load 10 more (${this.getCronHistoryTotal() - 10} remaining)
                </button>
              </div>
            ` : ""}
          </div>
        </div>

        <!-- Quick Reference -->
        <div class="section">
          <h2 class="section-title">📖 Cron Syntax Reference</h2>
          <div class="card">
            <div class="cron-reference">
              <div class="cron-ref-row">
                <code>30 8 * * 1-5</code>
                <span>8:30 AM on weekdays</span>
              </div>
              <div class="cron-ref-row">
                <code>0 17 * * 1-5</code>
                <span>5:00 PM on weekdays</span>
              </div>
              <div class="cron-ref-row">
                <code>*/30 * * * *</code>
                <span>Every 30 minutes</span>
              </div>
              <div class="cron-ref-row">
                <code>0 */4 * * *</code>
                <span>Every 4 hours</span>
              </div>
              <div class="cron-ref-row">
                <code>0 9 * * 1</code>
                <span>9:00 AM every Monday</span>
              </div>
            </div>
            <div style="margin-top: 12px; font-size: 0.8rem; color: var(--text-secondary);">
              Format: <code>minute hour day-of-month month day-of-week</code>
            </div>
          </div>
        </div>
      </div>

      <!-- Create Session Tab -->
      <div class="tab-content ${this._currentTab === "create" ? "active" : ""}" id="create">
        <div id="create-session-content">
          ${getCreateSessionTabContent()}
        </div>
      </div>

      <!-- Sprint Tab -->
      <div class="tab-content ${this._currentTab === "sprint" ? "active" : ""}" id="sprint">
        <div id="sprint-content">
          ${getSprintTabContent(sprintState, sprintHistory, toolGapRequests, this._dataProvider.getJiraUrl())}
        </div>
      </div>

      </div><!-- end main-content -->

      <!-- Footer -->
      <div class="footer">
        <span>Session started ${this._formatTime(session.started)}</span>
        <span class="redhat-branding">🎩 <span class="redhat-name">Red Hat</span> AI Workflow</span>
        <span id="lastUpdatedTime">Last updated: ${new Date().toLocaleTimeString()}</span>
      </div>

      <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();

        // Global error handler for debugging
        window.onerror = function(msg, url, lineNo, columnNo, error) {
          console.error('[GLOBAL ERROR]', msg, 'at line', lineNo, ':', columnNo);
          console.error('[GLOBAL ERROR] Stack:', error ? error.stack : 'no stack');
          return false;
        };
        window.addEventListener('unhandledrejection', function(event) {
          console.error('[UNHANDLED PROMISE]', event.reason);
        });
        console.log('[DEBUG] Command Center script starting...');

        const dbusServices = ${JSON.stringify(DBUS_SERVICES)};
        const toolModulesData = ${JSON.stringify(toolModules)};
        const personasData = ${JSON.stringify(personas)};
        let selectedSkill = null;
        let currentExecution = null;
        let executingSkillName = null; // Track which skill is currently executing
        let currentSkillYaml = '';
        let currentSkillData = null;
        let currentSkillView = 'info'; // 'info', 'workflow', or 'yaml'
        let showingExecution = false; // Are we showing execution view vs definition view?
        let selectedModule = null;
        let extensionConnected = false;

        // Check if extension is connected by sending a ping
        // If we don't get a pong within 2 seconds, show a reconnect message
        function checkExtensionConnection() {
          vscode.postMessage({ command: 'ping' });
          setTimeout(() => {
            if (!extensionConnected) {
              console.warn('[CommandCenter-Webview] Extension not responding - panel may need refresh');
              // Show a prominent warning banner at the top
              if (!document.getElementById('reconnectBanner')) {
                const banner = document.createElement('div');
                banner.id = 'reconnectBanner';
                banner.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; background: #f59e0b; color: #000; padding: 12px 20px; text-align: center; font-weight: 600; z-index: 9999; display: flex; justify-content: center; align-items: center; gap: 16px;';
                banner.innerHTML = '⚠️ Command Center is disconnected from the extension. <button onclick="location.reload()" style="background: #000; color: #fff; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-weight: 600;">Reload Panel</button> <span style="font-weight: normal; font-size: 0.9em;">or close this tab and reopen via Command Palette</span>';
                document.body.insertBefore(banner, document.body.firstChild);
                // Add padding to body so content isn't hidden behind banner
                document.body.style.paddingTop = '60px';
              }
            }
          }, 2000);
        }

        // Run connection check on load
        checkExtensionConnection();

        // Simple YAML parser for skill files
        function parseSkillYaml(yaml) {
          const result = {
            name: '',
            description: '',
            version: '',
            inputs: [],
            steps: []
          };

          try {
            // Extract name
            const nameMatch = yaml.match(/^name:\\s*(.+)/m);
            if (nameMatch) result.name = nameMatch[1].trim();

            // Extract description (handle multi-line)
            const descMatch = yaml.match(/^description:\\s*\\|\\s*\\n([\\s\\S]*?)(?=^\\w+:|^$)/m);
            if (descMatch) {
              result.description = descMatch[1].split('\\n').map(l => l.trim()).filter(l => l).join('\\n');
            } else {
              const singleDescMatch = yaml.match(/^description:\\s*["']?([^"'\\n]+)/m);
              if (singleDescMatch) result.description = singleDescMatch[1].trim();
            }

            // Extract version
            const versionMatch = yaml.match(/^version:\\s*["']?([^"'\\n]+)/m);
            if (versionMatch) result.version = versionMatch[1].trim();

            // Extract inputs section
            const inputsMatch = yaml.match(/^inputs:\\s*\\n([\\s\\S]*?)(?=^steps:|^$)/m);
            if (inputsMatch) {
              const inputBlocks = inputsMatch[1].split(/^\\s*-\\s+name:/m).filter(b => b.trim());
              inputBlocks.forEach(block => {
                const input = { name: '', type: '', required: false, default: '', description: '' };
                const nameM = block.match(/^\\s*(.+)/);
                if (nameM) input.name = nameM[1].trim();
                const typeM = block.match(/type:\\s*(.+)/);
                if (typeM) input.type = typeM[1].trim();
                const reqM = block.match(/required:\\s*(.+)/);
                if (reqM) input.required = reqM[1].trim() === 'true';
                const defM = block.match(/default:\\s*(.+)/);
                if (defM) input.default = defM[1].trim();
                const descM = block.match(/description:\\s*["']?([^"'\\n]+)/);
                if (descM) input.description = descM[1].trim();
                if (input.name) result.inputs.push(input);
              });
            }

            // Extract steps section - find "steps:" and capture until end of file
            // Note: outputs can appear before or after steps, so we can't use it as a boundary
            const stepsStartIdx = yaml.indexOf('\\nsteps:');

            if (stepsStartIdx !== -1) {
              // Steps section goes to end of file (steps is always the last major section in our skills)
              const stepsSection = yaml.substring(stepsStartIdx + 7); // +7 for "\\nsteps:"

              // Find all step definitions by looking for "- name:" pattern
              const stepMatches = stepsSection.matchAll(/^\\s*-\\s+name:\\s*(.+)$/gm);
              const stepPositions = [];
              for (const match of stepMatches) {
                stepPositions.push({
                  name: match[1].trim(),
                  index: match.index
                });
              }

              // Extract each step block
              stepPositions.forEach((pos, i) => {
                const nextIdx = i + 1 < stepPositions.length ? stepPositions[i + 1].index : stepsSection.length;
                const block = stepsSection.substring(pos.index, nextIdx);

                const step = {
                  name: pos.name,
                  description: '',
                  tool: '',
                  compute: '',
                  condition: '',
                  onError: '',
                  memoryRead: [],
                  memoryWrite: [],
                  semanticSearch: [],
                  isAutoRemediation: false,
                  canRetry: false
                };

                const descM = block.match(/description:\\s*["']?([^"'\\n]+)/);
                if (descM) step.description = descM[1].trim();

                const toolM = block.match(/tool:\\s*(.+)/);
                if (toolM) step.tool = toolM[1].trim();

                const condM = block.match(/condition:\\s*["']?([^"'\\n]+)/);
                if (condM) step.condition = condM[1].trim();

                const errorM = block.match(/on_error:\\s*(.+)/);
                if (errorM) step.onError = errorM[1].trim();

                if (block.includes('compute:')) step.compute = 'python';

                // Simple lifecycle analysis
                const lowerName = step.name.toLowerCase();
                const lowerDesc = step.description.toLowerCase();

                // Memory read tools
                const memoryReadTools = ['memory_read', 'memory_query', 'check_known_issues', 'memory_stats'];
                if (memoryReadTools.some(t => step.tool.includes(t))) {
                  if (step.tool.includes('check_known_issues')) {
                    step.memoryRead.push('learned/patterns', 'learned/tool_fixes');
                  } else {
                    step.memoryRead.push('memory');
                  }
                }

                // Memory write tools
                const memoryWriteTools = ['memory_write', 'memory_update', 'memory_append', 'memory_session_log', 'learn_tool_fix'];
                if (memoryWriteTools.some(t => step.tool.includes(t))) {
                  if (step.tool.includes('learn_tool_fix')) {
                    step.memoryWrite.push('learned/tool_fixes');
                  } else if (step.tool.includes('memory_session_log')) {
                    step.memoryWrite.push('session_log');
                  } else {
                    step.memoryWrite.push('memory');
                  }
                }

                // Semantic search tools (knowledge/vector search)
                const semanticSearchTools = ['knowledge_query', 'knowledge_scan', 'knowledge_search', 'vector_search', 'codebase_search', 'semantic_search'];
                if (semanticSearchTools.some(t => step.tool.includes(t))) {
                  const searchType = step.tool.includes('knowledge') ? 'knowledge' :
                                    step.tool.includes('vector') ? 'vector' :
                                    step.tool.includes('codebase') ? 'codebase' : 'semantic';
                  step.semanticSearch.push(searchType);
                }

                // Detect memory operations in compute blocks by name patterns
                const memoryReadPatterns = ['load_config', 'read_memory', 'get_context', 'check_', 'validate_', 'parse_', 'aggregate_known'];
                const memoryWritePatterns = ['save_', 'update_memory', 'log_session', 'record_', 'learn_', 'store_'];

                if (step.compute) {
                  if (memoryReadPatterns.some(p => lowerName.includes(p))) {
                    step.memoryRead.push('config/context');
                  }
                  if (memoryWritePatterns.some(p => lowerName.includes(p))) {
                    step.memoryWrite.push('state/context');
                  }
                }

                if (['retry', 'heal', 'fix', 'recover', 'fallback', 'remediat'].some(p => lowerName.includes(p) || lowerDesc.includes(p))) {
                  step.isAutoRemediation = true;
                }

                // Also detect learn_ steps as auto-remediation
                if (lowerName.startsWith('learn_') && step.tool.includes('learn_tool_fix')) {
                  step.isAutoRemediation = true;
                }

                if (step.onError === 'continue' || step.onError === 'retry' || step.tool.startsWith('jira_') || step.tool.startsWith('gitlab_')) {
                  step.canRetry = true;
                }

                if (step.name) result.steps.push(step);
              });
            }
          } catch (e) {
            console.error('Failed to parse skill YAML:', e);
          }

          return result;
        }

        // Render skill view based on current mode
        function renderSkillView(view) {
          currentSkillView = view;
          const content = document.getElementById('skillContent');

          // Update toggle buttons
          document.querySelectorAll('.toggle-btn').forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-view') === view);
          });

          if (view === 'yaml') {
            // Show raw YAML code
            content.innerHTML = '<div class="skill-yaml-view">' + escapeHtml(currentSkillYaml) + '</div>';
          } else if (view === 'workflow') {
            // Show FULL graphical flowchart only
            renderFullFlowchartView(content);
          } else {
            // Default: info view - description + inputs
            renderInfoView(content);
          }
        }

        // Render info view (description + inputs)
        function renderInfoView(container) {
          if (!currentSkillData) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚡</div><div>No skill data</div></div>';
            return;
          }

          const data = currentSkillData;
          let html = '<div class="skill-info-view">';

          // Skill info card
          html += '<div class="skill-info-card">';
          html += '<div class="skill-info-title">' + (data.name || 'Unnamed Skill') + (data.version ? ' <span style="font-weight: normal; color: var(--text-muted);">v' + data.version + '</span>' : '') + '</div>';
          html += '<div class="skill-info-desc">' + (data.description || 'No description').replace(/\\n/g, '<br>') + '</div>';
          html += '</div>';

          // Inputs section
          if (data.inputs && data.inputs.length > 0) {
            html += '<div class="skill-inputs-section">';
            html += '<div class="skill-inputs-title">📥 Inputs</div>';
            data.inputs.forEach(input => {
              html += '<div class="skill-input-item">';
              html += '<span class="skill-input-name">' + input.name + (input.required ? ' *' : '') + '</span>';
              html += '<span class="skill-input-type">' + (input.type || 'any') + '</span>';
              html += '<span class="skill-input-desc">' + (input.description || '') + '</span>';
              if (input.default) {
                html += '<span class="skill-input-default">default: ' + input.default + '</span>';
              }
              html += '</div>';
            });
            html += '</div>';
          }

          // Quick stats
          html += '<div class="skill-stats-section">';
          html += '<div class="skill-stats-title">📊 Quick Stats</div>';
          html += '<div class="skill-stats-grid">';
          html += '<div class="skill-stat"><span class="stat-value">' + data.steps.length + '</span><span class="stat-label">Steps</span></div>';
          html += '<div class="skill-stat"><span class="stat-value">' + data.inputs.length + '</span><span class="stat-label">Inputs</span></div>';
          const toolSteps = data.steps.filter(s => s.tool).length;
          const computeSteps = data.steps.filter(s => s.compute).length;
          html += '<div class="skill-stat"><span class="stat-value">' + toolSteps + '</span><span class="stat-label">Tool Calls</span></div>';
          html += '<div class="skill-stat"><span class="stat-value">' + computeSteps + '</span><span class="stat-label">Compute</span></div>';
          html += '</div>';
          html += '</div>';

          html += '</div>';
          container.innerHTML = html;
        }

        // Render FULL flowchart view (takes up entire content area)
        function renderFullFlowchartView(container) {
          if (!currentSkillData) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚡</div><div>No skill data</div></div>';
            return;
          }

          const data = currentSkillData;
          let html = '<div class="skill-flowchart-full">';

          // Header with stats
          html += '<div class="flowchart-header">';
          html += '<div class="flowchart-title">' + (data.name || 'Workflow') + '</div>';
          html += '<div class="flowchart-stats">';
          html += '<span class="flowchart-stat">Steps: <strong>' + data.steps.length + '</strong></span>';
          html += '<span class="flowchart-stat">Status: <strong>Ready</strong></span>';
          html += '</div>';
          html += '<div class="view-toggle flowchart-view-toggle">';
          html += '<button class="active" data-action="setFlowchartHorizontal">━ Horizontal</button>';
          html += '<button data-action="setFlowchartVertical">┃ Vertical</button>';
          html += '</div>';
          html += '</div>';

          // Legend
          html += '<div class="flowchart-legend">';
          html += '<span class="legend-item" title="Memory Read">📖 Read</span>';
          html += '<span class="legend-item" title="Memory Write">💾 Write</span>';
          html += '<span class="legend-item" title="Semantic Search (knowledge/vector)">🔍 Search</span>';
          html += '<span class="legend-item" title="Tool Call">🔧 Tool</span>';
          html += '<span class="legend-item" title="Python Compute">🐍 Compute</span>';
          html += '<span class="legend-item" title="Conditional">❓ Conditional</span>';
          html += '<span class="legend-item" title="Auto-remediation">🔄 Auto-heal</span>';
          html += '</div>';

          // Flowchart container
          html += '<div id="flowchart-container" class="flowchart-container-full">';

          // Horizontal View (default)
          html += '<div id="flowchart-horizontal" class="flowchart-wrap-full">';
          data.steps.forEach((step, idx) => {
            const isLast = idx === data.steps.length - 1;
            html += getHorizontalStepHtml(step, idx, isLast);
          });
          html += '</div>';

          // Vertical View
          html += '<div id="flowchart-vertical" class="flowchart-vertical-full" style="display: none;">';
          data.steps.forEach((step, idx) => {
            html += getStepHtml(step, idx);
          });
          html += '</div>';

          html += '</div>'; // end flowchart-container
          html += '</div>'; // end skill-flowchart-full
          container.innerHTML = html;
        }

        function escapeHtml(text) {
          const div = document.createElement('div');
          div.textContent = text;
          return div.innerHTML;
        }

        function getStepIcon(status, stepNumber) {
          switch (status) {
            case 'success': return '✓';
            case 'failed': return '✕';
            case 'running': return '◐';
            case 'skipped': return '–';
            default: return stepNumber !== undefined ? String(stepNumber) : '○';
          }
        }

        function formatDuration(ms) {
          if (ms === undefined || ms === null || ms === '' || isNaN(ms)) return '';
          ms = Number(ms);
          if (isNaN(ms) || ms <= 0) return '';
          if (ms < 1000) return ms + 'ms';
          if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
          const mins = Math.floor(ms / 60000);
          const secs = Math.floor((ms % 60000) / 1000);
          return mins + 'm ' + secs + 's';
        }

        function getHorizontalStepHtml(step, index, isLastInRow, isExecution = false) {
          const stepNumber = index + 1;
          const status = step.status || 'pending';
          const icon = getStepIcon(status, stepNumber);
          const duration = formatDuration(step.duration);
          const isRemediation = step.isAutoRemediation;

          // Build type tags
          let typeTags = '';
          if (step.tool) typeTags += '<span class="tag tool" title="Tool: ' + escapeHtml(step.tool) + '">🔧</span>';
          if (step.compute) typeTags += '<span class="tag compute" title="Python compute">🐍</span>';
          if (step.condition) typeTags += '<span class="tag condition" title="Conditional: ' + escapeHtml(step.condition) + '">❓</span>';

          // Build lifecycle indicators
          let lifecycleHtml = '<div class="step-lifecycle-h">';
          if (step.memoryRead && step.memoryRead.length > 0) {
            lifecycleHtml += '<span class="lifecycle-indicator memory-read" title="Memory Read: ' + escapeHtml(step.memoryRead.join(', ')) + '">📖</span>';
          }
          if (step.memoryWrite && step.memoryWrite.length > 0) {
            lifecycleHtml += '<span class="lifecycle-indicator memory-write" title="Memory Write: ' + escapeHtml(step.memoryWrite.join(', ')) + '">💾</span>';
          }
          if (step.semanticSearch && step.semanticSearch.length > 0) {
            lifecycleHtml += '<span class="lifecycle-indicator semantic-search" title="Semantic Search: ' + escapeHtml(step.semanticSearch.join(', ')) + '">🔍</span>';
          }
          if (step.isAutoRemediation) {
            lifecycleHtml += '<span class="lifecycle-indicator auto-heal" title="Auto-remediation step">🔄</span>';
          }
          if (step.canAutoHeal && !step.isAutoRemediation) {
            lifecycleHtml += '<span class="lifecycle-indicator can-auto-heal" title="Can auto-heal on error (kube_login, vpn_connect, auth refresh)">🩹</span>';
          }
          if (step.canRetry && !step.isAutoRemediation) {
            lifecycleHtml += '<span class="lifecycle-indicator can-retry" title="Can retry on error">↩️</span>';
          }
          if (step.healingApplied) {
            lifecycleHtml += '<span class="lifecycle-indicator healed" title="Auto-heal applied: ' + escapeHtml(step.healingDetails || 'Fixed') + '">✨</span>';
          }
          if (step.retryCount > 0) {
            lifecycleHtml += '<span class="lifecycle-indicator retry-count" title="Retried ' + step.retryCount + ' time(s)">🔁' + step.retryCount + '</span>';
          }
          lifecycleHtml += '</div>';

          const rowLastClass = isLastInRow ? 'row-last' : '';

          return \`
            <div class="step-node-h \${status} \${isRemediation ? 'remediation' : ''} \${rowLastClass}" data-step-index="\${index}" title="\${step.description || step.name}">
              <div class="step-connector-h"></div>
              \${lifecycleHtml}
              <div class="step-icon-h">\${icon}</div>
              <div class="step-content-h">
                <div class="step-name-h">\${step.name}</div>
                <div class="step-type-h">\${typeTags}</div>
                \${duration ? '<div class="step-duration-h">' + duration + '</div>' : ""}
              </div>
            </div>
          \`;
        }

        function getStepHtml(step, index, isExecution = false) {
          const stepNumber = index + 1;
          const status = step.status || 'pending';
          const icon = getStepIcon(status, stepNumber);
          const duration = formatDuration(step.duration);
          const isRemediation = step.isAutoRemediation;

          // Build tags
          let tagsHtml = '<div class="step-meta">';
          if (step.tool) tagsHtml += '<span class="step-tag tool">🔧 ' + escapeHtml(step.tool) + '</span>';
          if (step.compute) tagsHtml += '<span class="step-tag compute">🐍 compute</span>';
          if (step.condition) tagsHtml += '<span class="step-tag condition" title="' + escapeHtml(step.condition) + '">❓ conditional</span>';
          if (step.memoryRead && step.memoryRead.length > 0) tagsHtml += '<span class="step-tag memory-read">📖 ' + escapeHtml(step.memoryRead.join(', ')) + '</span>';
          if (step.memoryWrite && step.memoryWrite.length > 0) tagsHtml += '<span class="step-tag memory-write">💾 ' + escapeHtml(step.memoryWrite.join(', ')) + '</span>';
          if (step.semanticSearch && step.semanticSearch.length > 0) tagsHtml += '<span class="step-tag semantic-search">🔍 ' + escapeHtml(step.semanticSearch.join(', ')) + '</span>';
          if (step.isAutoRemediation) tagsHtml += '<span class="step-tag auto-heal">🔄 auto-remediation</span>';
          if (step.canAutoHeal && !step.isAutoRemediation) tagsHtml += '<span class="step-tag can-auto-heal">🩹 auto-heal</span>';
          if (step.canRetry && !step.isAutoRemediation) tagsHtml += '<span class="step-tag can-retry">↩️ can retry</span>';
          if (step.healingApplied) tagsHtml += '<span class="step-tag healed">✨ healed</span>';
          if (step.retryCount > 0) tagsHtml += '<span class="step-tag retry-count">🔁 retried ' + step.retryCount + 'x</span>';
          tagsHtml += '</div>';

          return \`
            <div class="step-node \${status} \${isRemediation ? 'remediation' : ''}" data-step-index="\${index}">
              <div class="step-connector"></div>
              <div class="step-icon">\${icon}</div>
              <div class="step-content">
                <div class="step-header">
                  <span class="step-name">\${step.name}</span>
                  <span class="step-duration">\${duration}</span>
                </div>
                \${step.description ? '<div class="step-desc">' + escapeHtml(step.description) + '</div>' : ""}
                \${tagsHtml}
                \${step.error ? '<div class="step-error">❌ ' + escapeHtml(step.error) + '</div>' : ""}
                \${step.result ? '<div class="step-result">' + escapeHtml(step.result.slice(0, 300)) + '</div>' : ""}
              </div>
            </div>
          \`;
        }

        function renderWorkflowView(container) {
          if (!currentSkillData) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚡</div><div>No skill data</div></div>';
            return;
          }

          const data = currentSkillData;
          let html = '<div class="skill-workflow-view">';

          // Skill info card
          html += '<div class="skill-info-card">';
          html += '<div class="skill-info-title">' + (data.name || 'Unnamed Skill') + (data.version ? ' <span style="font-weight: normal; color: var(--text-muted);">v' + data.version + '</span>' : '') + '</div>';
          html += '<div class="skill-info-desc">' + (data.description || 'No description').replace(/\\n/g, '<br>') + '</div>';
          html += '</div>';

          // Inputs section
          if (data.inputs && data.inputs.length > 0) {
            html += '<div class="skill-inputs-section">';
            html += '<div class="skill-inputs-title">📥 Inputs</div>';
            data.inputs.forEach(input => {
              html += '<div class="skill-input-item">';
              html += '<span class="skill-input-name">' + input.name + '</span>';
              html += '<span class="skill-input-type">' + (input.type || 'any') + '</span>';
              html += '<span class="skill-input-desc">' + (input.description || '') + '</span>';
              if (input.default) {
                html += '<span class="skill-input-default">default: ' + input.default + '</span>';
              }
              html += '</div>';
            });
            html += '</div>';
          }

          // Flowchart Section
          html += '<div class="skill-steps-section">';
          html += '<div class="skill-steps-header">';
          html += '<div class="skill-steps-title">📊 Workflow Flowchart</div>';
          html += '<div class="flowchart-view-toggle">';
          html += '<button class="active" data-action="setFlowchartHorizontal">━ Horizontal</button>';
          html += '<button data-action="setFlowchartVertical">┃ Vertical</button>';
          html += '</div>';
          html += '</div>';

          html += '<div id="flowchart-container" class="flowchart-container">';

          // Horizontal View
          html += '<div id="flowchart-horizontal" class="flowchart-wrap">';
          data.steps.forEach((step, idx) => {
            const isLast = idx === data.steps.length - 1;
            html += getHorizontalStepHtml(step, idx, isLast);
          });
          html += '</div>';

          // Vertical View
          html += '<div id="flowchart-vertical" class="flowchart-vertical" style="display: none;">';
          data.steps.forEach((step, idx) => {
            html += getStepHtml(step, idx);
          });
          html += '</div>';

          html += '</div>'; // end flowchart-container
          html += '</div>'; // end skill-steps-section

          html += '</div>';
          container.innerHTML = html;
        }

        function setFlowchartView(view) {
          const horizontal = document.getElementById('flowchart-horizontal');
          const vertical = document.getElementById('flowchart-vertical');

          // Find buttons in either context (skill-flowchart-full or skill-steps-section)
          const buttons = document.querySelectorAll('.flowchart-view-toggle button, .skill-steps-section .view-toggle button');

          console.log('[Flowchart] setFlowchartView:', view, 'horizontal:', !!horizontal, 'vertical:', !!vertical);

          if (horizontal && vertical) {
            horizontal.style.display = view === 'horizontal' ? 'flex' : 'none';
            vertical.style.display = view === 'vertical' ? 'flex' : 'none';
            console.log('[Flowchart] Set horizontal display:', horizontal.style.display, 'vertical display:', vertical.style.display);
          }

          buttons.forEach(btn => {
            const action = btn.getAttribute('data-action');
            const isActive = (view === 'horizontal' && action === 'setFlowchartHorizontal') ||
                           (view === 'vertical' && action === 'setFlowchartVertical');
            btn.classList.toggle('active', isActive);
          });
        }


        // Tab switching
        function switchTab(tabId) {
          console.log('[DEBUG] switchTab called with:', tabId);
          document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
          document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
          const tabBtn = document.querySelector('[data-tab="' + tabId + '"]');
          const tabContent = document.getElementById(tabId);
          console.log('[DEBUG] tabBtn found:', !!tabBtn, 'tabContent found:', !!tabContent);
          if (tabBtn) tabBtn.classList.add('active');
          if (tabContent) tabContent.classList.add('active');
          vscode.postMessage({ command: 'switchTab', tab: tabId });
        }

        // Commands
        function refresh() { vscode.postMessage({ command: 'refresh' }); }
        function openJira() { vscode.postMessage({ command: 'openJira' }); }
        function openMR() { vscode.postMessage({ command: 'openMR' }); }
        function runSkill() { vscode.postMessage({ command: 'runSkill' }); }
        function switchAgent() { vscode.postMessage({ command: 'switchAgent' }); }
        function startWork() { vscode.postMessage({ command: 'startWork' }); }
        function coffee() { vscode.postMessage({ command: 'coffee' }); }
        function beer() { vscode.postMessage({ command: 'beer' }); }
        function loadSlackHistory() { vscode.postMessage({ command: 'loadSlackHistory' }); }

        // Slack target type state
        let slackTargetType = 'channel';
        let slackUsers = [];
        let slackUserSearchTimeout = null;

        function setSlackTarget(type) {
          slackTargetType = type;
          const channelContainer = document.getElementById('slackChannelContainer');
          const userContainer = document.getElementById('slackUserContainer');
          const toggleBtns = document.querySelectorAll('#slackTargetToggle .toggle-btn');

          toggleBtns.forEach(btn => {
            btn.classList.toggle('active', btn.getAttribute('data-value') === type);
          });

          if (type === 'channel') {
            channelContainer.style.display = 'flex';
            userContainer.style.display = 'none';
          } else {
            channelContainer.style.display = 'none';
            userContainer.style.display = 'flex';
          }
        }

        function searchSlackUsers(query) {
          if (slackUserSearchTimeout) clearTimeout(slackUserSearchTimeout);
          slackUserSearchTimeout = setTimeout(() => {
            vscode.postMessage({ command: 'searchSlackUsers', query: query });
          }, 300);
        }

        function selectSlackUser(userId, userName, realName) {
          document.getElementById('slackSelectedUser').value = userId;
          document.getElementById('slackUserSearch').style.display = 'none';
          document.getElementById('slackUserResults').style.display = 'none';
          const display = document.getElementById('slackSelectedUserDisplay');
          display.style.display = 'flex';
          document.getElementById('slackSelectedUserName').textContent = realName || userName;
        }

        function clearSlackUser() {
          document.getElementById('slackSelectedUser').value = '';
          document.getElementById('slackUserSearch').value = '';
          document.getElementById('slackUserSearch').style.display = 'block';
          document.getElementById('slackSelectedUserDisplay').style.display = 'none';
          document.getElementById('slackUserResults').style.display = 'none';
        }

        function renderSlackUserResults(users) {
          const container = document.getElementById('slackUserResults');
          if (!users || users.length === 0) {
            container.innerHTML = '<div class="slack-no-results">No users found</div>';
            container.style.display = 'block';
            return;
          }
          container.innerHTML = users.map(u => \`
            <div class="slack-user-item" onclick="selectSlackUser('\${u.user_id || u.id}', '\${(u.name || '').replace(/'/g, "\\\\'")}', '\${(u.real_name || u.name || '').replace(/'/g, "\\\\'")}')">
              <div class="slack-user-avatar">\${(u.real_name || u.name || '?').charAt(0).toUpperCase()}</div>
              <div class="slack-user-info">
                <div class="slack-user-name">\${u.real_name || u.name}</div>
                <div class="slack-user-email">\${u.email || '@' + u.name}</div>
              </div>
            </div>
          \`).join('');
          container.style.display = 'block';
        }

        function sendSlackMessage() {
          let target = '';
          if (slackTargetType === 'channel') {
            target = document.getElementById('slackChannel')?.value;
          } else {
            target = document.getElementById('slackSelectedUser')?.value;
          }
          const text = document.getElementById('slackMessageInput')?.value;
          if (target && text) {
            vscode.postMessage({ command: 'sendSlackMessage', channel: target, text: text, targetType: slackTargetType });
            document.getElementById('slackMessageInput').value = '';
          } else if (!target) {
            // Show feedback
            const msg = slackTargetType === 'channel' ? 'Please select a channel' : 'Please select a user';
            console.log('[Slack] ' + msg);
          }
        }

        function refreshSlackTargets() {
          vscode.postMessage({ command: 'refreshSlackTargets' });
        }

        function refreshSlackChannels() { vscode.postMessage({ command: 'refreshSlackChannels' }); }

        // Make slack functions globally available
        window.selectSlackUser = selectSlackUser;
        window.clearSlackUser = clearSlackUser;

        // Services
        function refreshServices() { vscode.postMessage({ command: 'refreshServices' }); }
        function serviceControl(action, service) {
          vscode.postMessage({ command: 'serviceControl', action: action, service: service });
        }

        // Sessions
        function refreshWorkspaces() { vscode.postMessage({ command: 'refreshWorkspaces' }); }
        function viewWorkspaceTools(uri) { vscode.postMessage({ command: 'viewWorkspaceTools', uri: uri }); }
        function switchToWorkspace(uri) { vscode.postMessage({ command: 'switchToWorkspace', uri: uri }); }
        function removeWorkspace(uri) { vscode.postMessage({ command: 'removeWorkspace', uri: uri }); }
        function copySessionId(sessionId) { vscode.postMessage({ command: 'copySessionId', sessionId: sessionId }); }
        function openChatSession(sessionId, sessionName) {
          console.log('[AA-WORKFLOW-WEBVIEW] openChatSession clicked, sessionId:', sessionId, 'name:', sessionName);
          // Show immediate feedback
          const toast = document.createElement('div');
          toast.style.cssText = 'position:fixed;top:20px;right:20px;background:#10b981;color:white;padding:12px 20px;border-radius:8px;z-index:9999;font-weight:bold;';
          toast.textContent = '🔍 Finding: ' + (sessionName || sessionId) + '...';
          document.body.appendChild(toast);
          setTimeout(() => toast.remove(), 3000);
          vscode.postMessage({ command: 'openChatSession', sessionId: sessionId, sessionName: sessionName });
        }
        function changeWorkspacePersona(selectEl) {
          const uri = selectEl.getAttribute('data-workspace-uri');
          const persona = selectEl.value;
          vscode.postMessage({ command: 'changeWorkspacePersona', uri: uri, persona: persona });
        }
        // Make changeWorkspacePersona available globally for inline onchange
        window.changeWorkspacePersona = changeWorkspacePersona;

        // Cron
        function refreshCron() { vscode.postMessage({ command: 'refreshCron' }); }
        function toggleScheduler() {
          console.log('[Webview] toggleScheduler button clicked, sending message to extension');
          vscode.postMessage({ command: 'toggleScheduler' });
        }
        function toggleCronJob(jobName, enabled) { vscode.postMessage({ command: 'toggleCronJob', jobName, enabled }); }
        function runCronJobNow(jobName) { vscode.postMessage({ command: 'runCronJobNow', jobName }); }
        function loadMoreCronHistory(btn) {
          const currentLimit = parseInt(btn.getAttribute('data-current') || '10', 10);
          const newLimit = currentLimit + 10;
          btn.setAttribute('data-current', newLimit.toString());
          btn.innerHTML = '⏳ Loading...';
          btn.disabled = true;
          vscode.postMessage({ command: 'loadMoreCronHistory', limit: newLimit });
        }
        function openConfigFile() {
          console.log('[Webview] openConfigFile called, sending message to extension');
          try {
            vscode.postMessage({ command: 'openConfigFile' });
            console.log('[Webview] openConfigFile message sent successfully');
          } catch (err) {
            console.error('[Webview] openConfigFile error:', err);
          }
        }

        // Skills
        function filterSkills() {
          const searchEl = document.getElementById('skillSearch');
          if (!searchEl) return;
          const query = searchEl.value.toLowerCase();
          document.querySelectorAll('.skill-item').forEach(item => {
            const name = item.dataset.skill.toLowerCase();
            item.style.display = name.includes(query) ? '' : 'none';
          });
        }

        function selectSkill(skillName) {
          selectedSkill = skillName;
          document.querySelectorAll('.skill-item').forEach(i => i.classList.remove('selected'));
          const skillItem = document.querySelector('[data-skill="' + skillName + '"]');
          if (skillItem) {
            skillItem.classList.add('selected');
            // Get the icon from the skill item
            const iconEl = skillItem.querySelector('.skill-item-icon');
            const icon = iconEl ? iconEl.textContent : '⚡';
            const skillIconEl = document.getElementById('selectedSkillIcon');
            if (skillIconEl) skillIconEl.textContent = icon;
          }
          const skillNameEl = document.getElementById('selectedSkillName');
          if (skillNameEl) skillNameEl.textContent = skillName;

          // If selecting the currently executing skill, show execution view
          if (skillName === executingSkillName && currentExecution && currentExecution.steps) {
            showingExecution = true;
            const viewToggle = document.getElementById('skillViewToggle');
            if (viewToggle) viewToggle.style.display = 'none';
            renderFlowchart(currentExecution.steps);
          } else {
            // Otherwise load the skill definition
            showingExecution = false;
            vscode.postMessage({ command: 'loadSkill', skillName });
          }
        }

        function runSelectedSkill() {
          if (selectedSkill) {
            vscode.postMessage({ command: 'runSkill', skillName: selectedSkill });
          } else {
            runSkill();
          }
        }

        function openSelectedSkillFile() {
          if (selectedSkill) {
            vscode.postMessage({ command: 'openSkillFile', skillName: selectedSkill });
          }
        }


        // Tools
        function selectModule(moduleName) {
          selectedModule = moduleName;

          // Update UI
          document.querySelectorAll('.tool-module-item').forEach(item => {
            item.classList.toggle('selected', item.getAttribute('data-module') === moduleName);
          });

          const module = toolModulesData.find(m => m.name === moduleName);
          if (!module) return;

          const moduleNameEl = document.getElementById('selectedModuleName');
          const toolCountEl = document.getElementById('toolCountBadge');
          if (moduleNameEl) moduleNameEl.textContent = module.displayName;
          if (toolCountEl) toolCountEl.textContent = module.toolCount + ' tools';

          // Render tools list
          const content = document.getElementById('toolsContent');
          if (module.tools.length === 0) {
            content.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🔧</div><div>No tools found in this module</div></div>';
            return;
          }

          let html = '<div class="tool-list">';
          module.tools.forEach(tool => {
            html += \`
              <div class="tool-item" data-tool="\${tool.name}">
                <div class="tool-item-name">\${tool.name}</div>
                <div class="tool-item-desc">\${tool.description || 'No description'}</div>
              </div>
            \`;
          });
          html += '</div>';
          content.innerHTML = html;
        }

        function filterTools() {
          const searchEl = document.getElementById('toolSearch');
          if (!searchEl) return;
          const query = searchEl.value.toLowerCase();

          document.querySelectorAll('.tool-module-item').forEach(item => {
            const moduleName = item.getAttribute('data-module');
            const module = toolModulesData.find(m => m.name === moduleName);

            // Check if module name or any tool name matches
            const moduleMatches = module.displayName.toLowerCase().includes(query);
            const toolMatches = module.tools.some(t =>
              t.name.toLowerCase().includes(query) ||
              (t.description && t.description.toLowerCase().includes(query))
            );

            item.style.display = (moduleMatches || toolMatches || query === '') ? '' : 'none';
          });

          // If a module is selected, also filter the tools list
          if (selectedModule) {
            document.querySelectorAll('.tool-item').forEach(item => {
              const toolName = item.getAttribute('data-tool');
              const module = toolModulesData.find(m => m.name === selectedModule);
              const tool = module?.tools.find(t => t.name === toolName);

              const matches = toolName.toLowerCase().includes(query) ||
                (tool?.description && tool.description.toLowerCase().includes(query));

              item.style.display = (matches || query === '') ? '' : 'none';
            });
          }
        }


        // D-Bus
        function updateDbusMethods() {
          const serviceEl = document.getElementById('dbusService');
          const methodSelect = document.getElementById('dbusMethod');
          const argsDiv = document.getElementById('dbusArgs');
          if (!serviceEl || !methodSelect || !argsDiv) return;
          const serviceName = serviceEl.value;
          methodSelect.innerHTML = '<option value="">Select Method...</option>';
          argsDiv.style.display = 'none';
          argsDiv.innerHTML = '';

          const service = dbusServices.find(s => s.name === serviceName);
          if (service) {
            service.methods.forEach(m => {
              methodSelect.innerHTML += '<option value="' + m.name + '">' + m.name + ' - ' + m.description + '</option>';
            });
          }
        }

        function updateDbusArgs() {
          const serviceEl = document.getElementById('dbusService');
          const methodEl = document.getElementById('dbusMethod');
          const argsDiv = document.getElementById('dbusArgs');
          if (!serviceEl || !methodEl || !argsDiv) return;
          const serviceName = serviceEl.value;
          const methodName = methodEl.value;
          argsDiv.innerHTML = '';
          argsDiv.style.display = 'none';

          const service = dbusServices.find(s => s.name === serviceName);
          if (!service) return;

          const method = service.methods.find(m => m.name === methodName);
          if (!method || !method.args || method.args.length === 0) return;

          argsDiv.style.display = 'block';
          let html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px;">';
          method.args.forEach(arg => {
            html += \`
              <div>
                <label style="font-size: 0.75rem; color: var(--text-muted); display: block; margin-bottom: 4px;">\${arg.name} (\${arg.type})</label>
                <input type="\${arg.type === 'int32' ? 'number' : 'text'}"
                       id="dbusArg_\${arg.name}"
                       value="\${arg.default || ''}"
                       placeholder="\${arg.name}"
                       style="width: 100%; padding: 6px 10px; background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 6px; color: var(--text-primary); font-size: 0.85rem;">
              </div>
            \`;
          });
          html += '</div>';
          argsDiv.innerHTML = html;
        }

        function queryDbus() {
          const serviceEl = document.getElementById('dbusService');
          const methodEl = document.getElementById('dbusMethod');
          if (!serviceEl || !methodEl) return;
          const serviceName = serviceEl.value;
          const methodName = methodEl.value;
          if (!serviceName || !methodName) return;

          // Collect arguments
          const service = dbusServices.find(s => s.name === serviceName);
          const method = service?.methods.find(m => m.name === methodName);
          const args = {};

          if (method?.args) {
            method.args.forEach(arg => {
              const input = document.getElementById('dbusArg_' + arg.name);
              if (input) {
                args[arg.name] = input.value;
              }
            });
          }

          const resultEl = document.getElementById('dbusResult');
          if (resultEl) resultEl.innerHTML = 'Querying...';
          vscode.postMessage({ command: 'queryDBus', service: serviceName, method: methodName, args });
        }

        // Render skill flowchart for active execution
        // Uses incremental updates to avoid full DOM replacement
        let lastRenderedSteps = null;
        let executionFlowchartInitialized = false;

        // Analyze step for lifecycle indicators (memory, search, remediation)
        function analyzeStepLifecycle(step) {
          const tool = step.tool || '';
          const name = step.name || '';
          const onError = step.onError || '';

          // Initialize lifecycle arrays if not present
          step.memoryRead = step.memoryRead || [];
          step.memoryWrite = step.memoryWrite || [];
          step.semanticSearch = step.semanticSearch || [];

          // Memory read tools
          const memoryReadTools = ['memory_read', 'memory_query', 'check_known_issues', 'memory_stats'];
          if (memoryReadTools.some(t => tool.includes(t))) {
            if (tool.includes('check_known_issues')) {
              step.memoryRead.push('learned/patterns', 'learned/tool_fixes');
            } else {
              step.memoryRead.push('memory');
            }
          }

          // Memory write tools
          const memoryWriteTools = ['memory_write', 'memory_update', 'memory_append', 'memory_session_log', 'learn_tool_fix'];
          if (memoryWriteTools.some(t => tool.includes(t))) {
            if (tool.includes('learn_tool_fix')) {
              step.memoryWrite.push('learned/tool_fixes');
            } else if (tool.includes('memory_session_log')) {
              step.memoryWrite.push('session_log');
            } else {
              step.memoryWrite.push('memory');
            }
          }

          // Semantic search tools
          const semanticSearchTools = ['knowledge_query', 'knowledge_scan', 'knowledge_search', 'vector_search', 'codebase_search', 'semantic_search'];
          if (semanticSearchTools.some(t => tool.includes(t))) {
            const searchType = tool.includes('knowledge') ? 'knowledge' :
                              tool.includes('vector') ? 'vector' :
                              tool.includes('codebase') ? 'codebase' : 'semantic';
            step.semanticSearch.push(searchType);
          }

          // Detect memory operations in compute blocks by name patterns
          const memoryReadPatterns = ['load_config', 'read_memory', 'get_context', 'check_', 'validate_', 'parse_', 'aggregate_known'];
          const memoryWritePatterns = ['save_', 'update_memory', 'log_session', 'record_', 'learn_', 'store_'];

          if (step.compute) {
            const lowerName = name.toLowerCase();
            if (memoryReadPatterns.some(p => lowerName.includes(p))) {
              step.memoryRead.push('config/context');
            }
            if (memoryWritePatterns.some(p => lowerName.includes(p))) {
              step.memoryWrite.push('state/context');
            }
          }

          // Auto-remediation detection
          const lowerName = name.toLowerCase();
          const lowerDesc = (step.description || '').toLowerCase();
          if (['retry', 'heal', 'fix', 'recover', 'fallback', 'remediat'].some(p => lowerName.includes(p) || lowerDesc.includes(p))) {
            step.isAutoRemediation = true;
          }

          // Also detect learn_ steps as auto-remediation
          if (lowerName.startsWith('learn_') && tool.includes('learn_tool_fix')) {
            step.isAutoRemediation = true;
          }

          // Can retry detection
          if (onError === 'continue' || onError === 'retry' || tool.startsWith('jira_') || tool.startsWith('gitlab_')) {
            step.canRetry = true;
          }

          return step;
        }

        // Running Skills Panel state
        let runningSkillsCollapsed = false;
        let selectedRunningSkillId = null;

        // Stale detection thresholds (in ms)
        const STALE_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes total runtime
        const INACTIVE_THRESHOLD_MS = 10 * 60 * 1000; // 10 minutes since last event

        function isSkillStale(skill) {
          // Stale if running for more than 30 minutes
          if (skill.elapsedMs > STALE_THRESHOLD_MS) {
            return true;
          }
          // Note: We can't check last event time from the summary, but the watcher does
          return false;
        }

        function updateRunningSkillsPanel(runningSkills, staleCount) {
          const panel = document.getElementById('runningSkillsPanel');
          const list = document.getElementById('runningSkillsList');
          const countEl = document.getElementById('runningSkillsCount');
          const badge = document.getElementById('skillsBadge');
          const staleWarning = document.getElementById('staleSkillsWarning');
          const staleCountEl = document.getElementById('staleSkillsCount');
          const clearStaleBtn = document.getElementById('clearStaleSkills');

          if (!runningSkills || runningSkills.length === 0) {
            // Hide panel when no skills running
            if (panel) panel.style.display = 'none';
            if (badge) {
              // Restore total skills count from data attribute
              const totalSkills = badge.getAttribute('data-total') || '';
              badge.textContent = totalSkills;
              badge.style.display = '';
              badge.classList.remove('running');
            }
            if (staleWarning) staleWarning.style.display = 'none';
            if (clearStaleBtn) clearStaleBtn.style.display = 'none';
            return;
          }

          // Show panel
          if (panel) panel.style.display = 'block';
          if (countEl) countEl.textContent = runningSkills.length;
          if (badge) {
            badge.style.display = '';
            badge.classList.add('running');
            badge.textContent = runningSkills.length > 1 ? runningSkills.length + ' Running' : 'Running';
          }

          // Count stale skills (client-side check based on elapsed time)
          const clientStaleCount = staleCount !== undefined ? staleCount : runningSkills.filter(s => isSkillStale(s)).length;

          // Show/hide stale warning and clear button
          if (staleWarning) {
            staleWarning.style.display = clientStaleCount > 0 ? 'inline-flex' : 'none';
          }
          if (staleCountEl) {
            staleCountEl.textContent = clientStaleCount;
          }
          if (clearStaleBtn) {
            clearStaleBtn.style.display = clientStaleCount > 0 ? 'inline-flex' : 'none';
          }

          // Render running skills list
          if (list && !runningSkillsCollapsed) {
            list.innerHTML = runningSkills.map(skill => {
              const progress = Math.round(((skill.currentStepIndex + 1) / skill.totalSteps) * 100);
              const elapsed = formatElapsed(skill.elapsedMs);
              const sourceClass = skill.source || 'chat';
              const sourceLabel = skill.source === 'cron' ? (skill.sourceDetails || 'Cron') :
                                  skill.source === 'slack' ? 'Slack' :
                                  (skill.sessionName || 'Chat');
              const isSelected = skill.executionId === selectedRunningSkillId;
              const isStale = isSkillStale(skill);

              return '<div class="running-skill-item' + (isSelected ? ' selected' : '') + (isStale ? ' stale' : '') + '" data-execution-id="' + skill.executionId + '">' +
                '<div class="running-skill-progress">' +
                  '<div class="running-skill-progress-bar">' +
                    '<div class="running-skill-progress-fill" style="width: ' + progress + '%;"></div>' +
                  '</div>' +
                  '<div class="running-skill-progress-text">' + (skill.currentStepIndex + 1) + '/' + skill.totalSteps + '</div>' +
                '</div>' +
                '<div class="running-skill-info">' +
                  '<div class="running-skill-name">' + escapeHtml(skill.skillName) + (isStale ? ' ⚠️' : '') + '</div>' +
                  '<div class="running-skill-source">' +
                    '<span class="source-badge ' + sourceClass + '">' + sourceClass + '</span>' +
                    '<span>' + escapeHtml(sourceLabel) + '</span>' +
                  '</div>' +
                '</div>' +
                '<div class="running-skill-elapsed">' + elapsed + '</div>' +
                '<button class="clear-skill-btn" data-execution-id="' + skill.executionId + '" title="Clear this execution">✕</button>' +
              '</div>';
            }).join('');

            // Add click handlers for skill items
            list.querySelectorAll('.running-skill-item').forEach(item => {
              item.addEventListener('click', (e) => {
                // Don't select if clicking the clear button
                if (e.target.classList.contains('clear-skill-btn')) return;

                const execId = item.getAttribute('data-execution-id');
                selectedRunningSkillId = execId;
                // Update selection UI
                list.querySelectorAll('.running-skill-item').forEach(i => i.classList.remove('selected'));
                item.classList.add('selected');
                // Tell extension to select this execution
                vscode.postMessage({ command: 'selectRunningSkill', executionId: execId });
              });
            });

            // Add click handlers for individual clear buttons
            list.querySelectorAll('.clear-skill-btn').forEach(btn => {
              btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const execId = btn.getAttribute('data-execution-id');
                if (execId) {
                  vscode.postMessage({ command: 'clearSkillExecution', executionId: execId });
                }
              });
            });
          }
        }

        function formatElapsed(ms) {
          if (!ms || ms < 0) return '--';
          const seconds = Math.floor(ms / 1000);
          if (seconds < 60) return seconds + 's';
          const minutes = Math.floor(seconds / 60);
          const secs = seconds % 60;
          if (minutes < 60) return minutes + 'm ' + secs + 's';
          const hours = Math.floor(minutes / 60);
          const mins = minutes % 60;
          return hours + 'h ' + mins + 'm';
        }

        // Toggle running skills panel collapse
        const toggleBtn = document.getElementById('toggleRunningSkills');
        if (toggleBtn) {
          toggleBtn.addEventListener('click', () => {
            runningSkillsCollapsed = !runningSkillsCollapsed;
            const list = document.getElementById('runningSkillsList');
            if (list) {
              list.classList.toggle('collapsed', runningSkillsCollapsed);
            }
            toggleBtn.textContent = runningSkillsCollapsed ? '▶' : '▼';
          });
        }

        // Clear stale skills button
        const clearStaleBtn = document.getElementById('clearStaleSkills');
        if (clearStaleBtn) {
          clearStaleBtn.addEventListener('click', () => {
            vscode.postMessage({ command: 'clearStaleSkills' });
          });
        }

        function renderFlowchart(steps) {
          const container = document.getElementById('skillContent');
          if (!steps || steps.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">⚡</div><div>No steps to display</div></div>';
            executionFlowchartInitialized = false;
            lastRenderedSteps = null;
            return;
          }

          // Analyze each step for lifecycle indicators
          steps.forEach(step => analyzeStepLifecycle(step));

          // If we are currently in yaml view, don't force switch to flowchart unless desired
          if (currentSkillView === 'yaml') return;

          // Check if we can do an incremental update
          const existingFlowchart = document.getElementById('flowchart-container');
          if (existingFlowchart && executionFlowchartInitialized && lastRenderedSteps && lastRenderedSteps.length === steps.length) {
            // Incremental update - only update changed steps
            updateFlowchartSteps(steps);
            lastRenderedSteps = JSON.parse(JSON.stringify(steps));
            return;
          }

          // Full render needed (first time or structure changed)
          let html = '<div class="skill-workflow-view">';

          // Execution info
          html += '<div class="skill-info-card" style="border-left: 4px solid var(--warning);">';
          html += '<div class="skill-info-title">🔄 Active Execution</div>';
          html += '<div class="skill-info-desc">Viewing real-time progress for the running skill.</div>';
          html += '</div>';

          // Flowchart Section
          html += '<div class="skill-steps-section">';
          html += '<div class="skill-steps-header">';
          html += '<div class="skill-steps-title">📊 Execution Flowchart</div>';
          html += '<div class="flowchart-view-toggle">';
          html += '<button class="active" data-action="setFlowchartHorizontal">━ Horizontal</button>';
          html += '<button data-action="setFlowchartVertical">┃ Vertical</button>';
          html += '</div>';
          html += '</div>';

          html += '<div id="flowchart-container" class="flowchart-container">';

          // Horizontal View
          html += '<div id="flowchart-horizontal" class="flowchart-wrap">';
          steps.forEach((step, idx) => {
            const isLast = idx === steps.length - 1;
            html += getHorizontalStepHtml(step, idx, isLast, true);
          });
          html += '</div>';

          // Vertical View
          html += '<div id="flowchart-vertical" class="flowchart-vertical" style="display: none;">';
          steps.forEach((step, idx) => {
            html += getStepHtml(step, idx, true);
          });
          html += '</div>';

          html += '</div>'; // end flowchart-container
          html += '</div>'; // end skill-steps-section
          html += '</div>';

          container.innerHTML = html;
          executionFlowchartInitialized = true;
          lastRenderedSteps = JSON.parse(JSON.stringify(steps));
        }

        // Incremental update - only update step nodes that changed
        function updateFlowchartSteps(steps) {
          steps.forEach((step, idx) => {
            const lastStep = lastRenderedSteps[idx];

            // Check if this step changed
            if (lastStep &&
                lastStep.status === step.status &&
                lastStep.duration === step.duration &&
                lastStep.error === step.error &&
                lastStep.healingApplied === step.healingApplied &&
                lastStep.retryCount === step.retryCount) {
              return; // No change, skip
            }

            // Update horizontal step node
            const hNode = document.querySelector('#flowchart-horizontal [data-step-index="' + idx + '"]');
            if (hNode) {
              // Update status class
              hNode.className = hNode.className.replace(/\\\\b(pending|running|success|failed|skipped)\\\\b/g, '');
              hNode.classList.add(step.status || 'pending');

              // Update icon
              const icon = hNode.querySelector('.step-icon-h');
              if (icon) {
                icon.textContent = getStepIcon(step.status, idx + 1);
              }

              // Update duration
              const duration = hNode.querySelector('.step-duration-h');
              if (duration && step.duration) {
                duration.textContent = formatDuration(step.duration);
              }

              // Add healing indicator if needed
              if (step.healingApplied && !hNode.querySelector('.lifecycle-indicator.healed')) {
                const lifecycle = hNode.querySelector('.step-lifecycle-h') || document.createElement('div');
                if (!lifecycle.classList.contains('step-lifecycle-h')) {
                  lifecycle.className = 'step-lifecycle-h';
                  hNode.insertBefore(lifecycle, hNode.firstChild);
                }
                lifecycle.innerHTML += '<span class="lifecycle-indicator healed" title="Auto-heal applied: ' + escapeHtml(step.healingDetails || 'Fixed') + '">✨</span>';
              }
            }

            // Update vertical step node
            const vNode = document.querySelector('#flowchart-vertical [data-step-index="' + idx + '"]');
            if (vNode) {
              // Update status class
              vNode.className = vNode.className.replace(/\\\\b(pending|running|success|failed|skipped)\\\\b/g, '');
              vNode.classList.add(step.status || 'pending');

              // Update icon
              const icon = vNode.querySelector('.step-icon');
              if (icon) {
                icon.textContent = getStepIcon(step.status, idx + 1);
              }

              // Update duration
              const duration = vNode.querySelector('.step-duration');
              if (duration && step.duration) {
                duration.textContent = formatDuration(step.duration);
              }

              // Show error if failed
              if (step.status === 'failed' && step.error) {
                let errorDiv = vNode.querySelector('.step-error');
                if (!errorDiv) {
                  errorDiv = document.createElement('div');
                  errorDiv.className = 'step-error';
                  vNode.querySelector('.step-content').appendChild(errorDiv);
                }
                errorDiv.textContent = '❌ ' + step.error;
              }

              // Show healing if applied
              if (step.healingApplied) {
                let healDiv = vNode.querySelector('.step-healed');
                if (!healDiv) {
                  healDiv = document.createElement('div');
                  healDiv.className = 'step-healed';
                  vNode.querySelector('.step-content').appendChild(healDiv);
                }
                healDiv.textContent = '✨ Auto-healed: ' + (step.healingDetails || 'Applied fix');
              }
            }
          });

          // Auto-scroll to running step
          const runningStep = document.querySelector('.step-node-h.running, .step-node.running');
          if (runningStep) {
            runningStep.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
          }
        }

        // Helper to get step icon based on status
        function getStepIcon(status, stepNumber) {
          switch (status) {
            case 'success': return '✓';
            case 'failed': return '✕';
            case 'running': return '◐';
            case 'skipped': return '–';
            default: return stepNumber !== undefined ? String(stepNumber) : '○';
          }
        }

        // Helper to format duration
        function formatDuration(ms) {
          if (ms === undefined || ms === null || ms === '' || isNaN(ms)) return '';
          ms = Number(ms);
          if (isNaN(ms) || ms <= 0) return '';
          if (ms < 1000) return ms + 'ms';
          if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
          const mins = Math.floor(ms / 60000);
          const secs = Math.floor((ms % 60000) / 1000);
          return mins + 'm ' + secs + 's';
        }

        // Handle messages from extension
        window.addEventListener('message', event => {
          const message = event.data;


          // Handle pong response - extension is connected
          if (message.command === 'pong') {
            extensionConnected = true;
            const warning = document.getElementById('reconnectWarning');
            if (warning) warning.remove();
            return;
          }

          // Handle batch updates from RefreshCoordinator
          // This processes multiple messages in a single frame for efficiency
          if (message.type === 'batchUpdate' && message.messages) {
            requestAnimationFrame(() => {
              for (const msg of message.messages) {
                // Re-dispatch each message through the normal handler
                window.dispatchEvent(new MessageEvent('message', { data: msg }));
              }
            });
            return;
          }

          if (message.command === 'switchTab') {
            switchTab(message.tab);
          }

          if (message.command === 'skillExecutionUpdate') {
            currentExecution = message.execution;
            executingSkillName = message.execution.skillName;
            const badge = document.getElementById('skillsBadge');

            if (message.execution.status === 'running') {
              if (badge) {
                badge.style.display = '';
                badge.classList.add('running');
                badge.textContent = 'Running';
              }

              // Auto-select the executing skill in the sidebar
              const skillItem = document.querySelector('[data-skill="' + executingSkillName + '"]');
              if (skillItem && !skillItem.classList.contains('selected')) {
                document.querySelectorAll('.skill-item').forEach(i => i.classList.remove('selected'));
                skillItem.classList.add('selected');
                selectedSkill = executingSkillName;
              }
            } else {
              if (badge) {
                // Restore total skills count from data attribute
                const totalSkills = badge.getAttribute('data-total') || '';
                badge.textContent = totalSkills;
                badge.style.display = '';
                badge.classList.remove('running');
              }
              // Keep executingSkillName so we can still show completed execution
            }

            // Update flowchart if we're viewing the executing skill or no skill selected
            if (message.execution.steps && (!selectedSkill || selectedSkill === executingSkillName)) {
              showingExecution = true;
              const skillNameEl = document.getElementById('selectedSkillName');
              if (skillNameEl) skillNameEl.textContent = message.execution.skillName;
              // Get the icon from the skill item if available
              const skillItem = document.querySelector('[data-skill="' + message.execution.skillName + '"]');
              const skillIconEl = document.getElementById('selectedSkillIcon');
              if (skillItem) {
                const iconEl = skillItem.querySelector('.skill-item-icon');
                if (skillIconEl) skillIconEl.textContent = iconEl ? iconEl.textContent : '⚡';
              } else {
                if (skillIconEl) skillIconEl.textContent = '⚡';
              }
              // Hide the view toggle when showing execution (execution has its own controls)
              const viewToggle = document.getElementById('skillViewToggle');
              if (viewToggle) viewToggle.style.display = 'none';
              renderFlowchart(message.execution.steps);
            }
          }

          if (message.command === 'runningSkillsUpdate') {
            updateRunningSkillsPanel(message.runningSkills, message.staleCount);
          }

          if (message.command === 'skillDefinition') {
            // Store the raw content and parsed data
            currentSkillYaml = message.content;
            currentSkillData = parseSkillYaml(message.content);

            // Show the view toggle
            const viewToggle = document.getElementById('skillViewToggle');
            if (viewToggle) viewToggle.style.display = 'flex';

            // Render the current view (default: workflow)
            renderSkillView(currentSkillView);
          }

          if (message.type === 'dbusResult') {
            const resultDiv = document.getElementById('dbusResult');
            if (message.success) {
              resultDiv.innerHTML = '<pre>' + JSON.stringify(message.data, null, 2) + '</pre>';
            } else {
              resultDiv.innerHTML = '<span style="color: var(--error);">❌ ' + message.error + '</span>';
            }
          }

          if (message.type === 'slackHistory') {
            renderSlackMessages(message.messages);
          }

          if (message.type === 'slackChannels') {
            const select = document.getElementById('slackChannel');
            if (select) {
              select.innerHTML = '<option value="">Select Channel...</option>';
              (message.channels || []).forEach(ch => {
                const opt = document.createElement('option');
                opt.value = ch.id || ch.channel_id || ch.name;
                opt.textContent = '#' + (ch.name || ch.id);
                select.appendChild(opt);
              });
            }
          }

          if (message.type === 'slackUsers') {
            renderSlackUserResults(message.users || []);
          }

          if (message.type === 'slackMessageSent') {
            if (message.success) {
              console.log('[Slack] Message sent successfully');
              // Optionally show a toast
            } else {
              console.error('[Slack] Failed to send message:', message.error);
            }
          }

          if (message.type === 'slackSearchResults') {
            renderSlackSearchResults(message);
          }

          if (message.type === 'slackPending') {
            renderSlackPending(message.pending || []);
          }

          if (message.type === 'slackCacheStats') {
            updateSlackCacheStats(message.channelStats, message.userStats);
          }

          if (message.type === 'slackChannelBrowser') {
            renderSlackChannelBrowser(message.channels || [], message.count || 0);
          }

          if (message.type === 'slackUserBrowser') {
            renderSlackUserBrowser(message.users || [], message.count || 0);
          }

          if (message.type === 'slackCommands') {
            populateCommandSelect(message.commands || []);
          }

          if (message.type === 'slackCommandSent') {
            if (message.success) {
              console.log('[Slack] Command sent: ' + message.command);
            }
          }

          if (message.type === 'slackConfig') {
            updateSlackConfigUI(message.config);
          }

          if (message.type === 'slackDebugModeChanged') {
            const toggle = document.getElementById('slackDebugModeToggle');
            if (toggle) toggle.checked = message.enabled;
          }

          if (message.type === 'serviceStatus') {
            updateServiceStatus(message);
          }

          if (message.type === 'schedulerToggled') {
            console.log('[CommandCenter] Received schedulerToggled message:', message.enabled);
            updateSchedulerUI(message.enabled);
          }

          if (message.type === 'cronData') {
            // Update scheduler status from refreshed cron data
            if (message.config) {
              // Get current job count to detect potential stale/empty data
              const currentJobCount = parseInt(document.getElementById('cronJobCount')?.textContent || '0', 10);
              const newJobCount = (message.config.jobs || []).length;

              // Skip cron config update if we're receiving 0 jobs but previously had jobs
              // This prevents flicker from transient D-Bus failures
              if (newJobCount === 0 && currentJobCount > 0) {
                console.log('[Cron] Skipping config update with 0 jobs (had ' + currentJobCount + ' jobs) - likely stale data');
                // Don't return - still process history update below
              } else {
                updateSchedulerUI(message.config.enabled);
                updateText('cronJobCount', newJobCount);
                const enabledJobs = (message.config.jobs || []).filter(j => j.enabled).length;
                updateText('cronEnabledCount', enabledJobs);
                // Update the tab badge (only if changed)
                const cronTabBadge = document.getElementById('cronTabBadge');
                if (cronTabBadge) {
                  const newText = enabledJobs.toString();
                  const newDisplay = message.config.enabled && enabledJobs > 0 ? '' : 'none';
                  if (cronTabBadge.textContent !== newText) {
                    cronTabBadge.textContent = newText;
                  }
                  if (cronTabBadge.style.display !== newDisplay) {
                    cronTabBadge.style.display = newDisplay;
                  }
                }
                // Update the jobs list dynamically (has internal hash check)
                updateCronJobs(message.config.jobs || []);
              }
            }
            // Update execution history (has internal hash check)
            if (message.history !== undefined) {
              updateCronHistory(message.history, message.totalHistory, message.currentLimit);
            }
          }

          if (message.type === 'dataUpdate') {
            // Update only dynamic data elements without destroying UI state
            updateDynamicData(message);
          }

          if (message.type === 'updateWorkspaces') {
            updateWorkspacesTab(message);
          }

          // Handle search results
          if (message.type === 'searchResults') {
            handleSearchResults(message);
          }

          // Incremental Sprint tab update (avoids full DOM re-render)
          if (message.type === 'sprintTabUpdate') {
            updateSprintTab(message);
          }

          // Sprint badge-only update (lightweight, for frequent syncs)
          if (message.type === 'sprintBadgeUpdate') {
            const badge = document.getElementById('sprintTabBadge');
            if (badge) {
              // Show total issues count, not just pending
              const totalIssues = message.totalIssues || message.pendingCount || 0;
              badge.textContent = totalIssues.toString();
              badge.style.display = totalIssues > 0 ? '' : 'none';
            }
          }

          // Incremental Meetings tab badge update
          if (message.type === 'meetingsTabBadgeUpdate') {
            updateMeetingsTabBadge(message);
            // Also update the upcoming meetings list if we have rendered HTML
            if (message.renderedUpcomingHtml !== undefined) {
              const upcomingList = document.querySelector('.upcoming-meetings-list');
              if (upcomingList) {
                upcomingList.innerHTML = message.renderedUpcomingHtml;
              }
            }
          }

          // Incremental Performance tab badge update
          if (message.type === 'performanceTabBadgeUpdate') {
            updatePerformanceTabBadge(message.percentage);
          }

          if (message.type === 'sprintIssuesLoading') {
            const container = document.getElementById('sprintIssues');
            if (container) {
              container.innerHTML = '<div class="loading-placeholder">Loading assigned issues...</div>';
            }
          }

          if (message.type === 'sprintIssuesUpdate') {
            updateSprintIssues(message.issues);
          }

          if (message.type === 'sprintIssuesError') {
            const container = document.getElementById('sprintIssues');
            if (container) {
              container.innerHTML = '<div class="loading-placeholder" style="color: var(--error);">Failed to load issues. Will retry on next auto-refresh.</div>';
            }
          }

          if (message.type === 'environmentUpdate') {
            // Update stage status
            const stageStatus = document.getElementById('stageStatus');
            const stageIcon = document.getElementById('stageIcon');
            if (stageStatus && message.stage) {
              stageStatus.textContent = message.stage;
              if (stageIcon) {
                stageIcon.textContent = message.stage === 'healthy' ? '✅' : message.stage === 'degraded' ? '⚠️' : '❓';
                stageIcon.className = 'card-icon ' + (message.stage === 'healthy' ? 'green' : message.stage === 'degraded' ? 'orange' : '');
              }
            }
            // Update prod status
            const prodStatus = document.getElementById('prodStatus');
            const prodIcon = document.getElementById('prodIcon');
            if (prodStatus && message.prod) {
              prodStatus.textContent = message.prod;
              if (prodIcon) {
                prodIcon.textContent = message.prod === 'healthy' ? '✅' : message.prod === 'degraded' ? '⚠️' : '❓';
                prodIcon.className = 'card-icon ' + (message.prod === 'healthy' ? 'green' : message.prod === 'degraded' ? 'orange' : '');
              }
            }
          }

          // Semantic search handlers
          if (message.command === 'semanticSearchLoading') {
            const resultsDiv = document.getElementById('semanticSearchResults');
            if (resultsDiv) {
              resultsDiv.innerHTML = \`
                <div class="search-loading">
                  <div class="search-loading-spinner"></div>
                  <span>Searching...</span>
                </div>
              \`;
            }
          }

          if (message.command === 'semanticSearchResult') {
            const resultsDiv = document.getElementById('semanticSearchResults');
            if (!resultsDiv) return;

            if (message.error) {
              resultsDiv.innerHTML = \`
                <div class="search-error">
                  <strong>❌ Error:</strong> \${escapeHtml(message.error)}
                </div>
              \`;
              return;
            }

            if (!message.results || message.results.length === 0) {
              resultsDiv.innerHTML = \`
                <div class="search-empty">
                  <div style="font-size: 2rem; margin-bottom: 8px;">🔍</div>
                  <div>No results found for "\${escapeHtml(message.query)}"</div>
                  <div style="font-size: 0.8rem; margin-top: 8px; color: var(--text-tertiary);">
                    Try a different query or check if the project is indexed
                  </div>
                </div>
              \`;
              return;
            }

            // Show which projects were searched if searching all
            const searchedInfo = message.searchedProjects
              ? \` across \${message.searchedProjects.length} project(s)\`
              : '';

            let html = \`<div style="margin-bottom: 12px; font-size: 0.85rem; color: var(--text-secondary);">
              Found \${message.results.length} result(s) for "<strong>\${escapeHtml(message.query)}</strong>"\${searchedInfo}
            </div>\`;

            message.results.forEach((result, index) => {
              const relevancePercent = Math.round((result.similarity || 0) * 100);
              const relevanceColor = relevancePercent >= 70 ? 'var(--green)' : relevancePercent >= 40 ? 'var(--yellow)' : 'var(--text-secondary)';
              const projectBadge = result.project
                ? \`<span style="background: var(--purple); color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; margin-right: 8px;">\${escapeHtml(result.project)}</span>\`
                : '';

              html += \`
                <div class="search-result-item">
                  <div class="search-result-header">
                    <span class="search-result-file">\${projectBadge}\${escapeHtml(result.file_path)}</span>
                    <div class="search-result-meta">
                      <span>Lines \${result.start_line}-\${result.end_line}</span>
                      <span>\${escapeHtml(result.type || 'code')}</span>
                      <span class="search-result-relevance" style="color: \${relevanceColor}">\${relevancePercent}% match</span>
                    </div>
                  </div>
                  <pre class="search-result-code">\${escapeHtml(result.content || '')}</pre>
                </div>
              \`;
            });

            resultsDiv.innerHTML = html;
          }

          // Ollama status update handler
          if (message.command === 'ollamaStatusUpdate') {
            const instances = ['npu', 'igpu', 'nvidia', 'cpu'];
            instances.forEach(inst => {
              const statusEl = document.getElementById(inst + 'Status');

              if (statusEl && message.data && message.data[inst]) {
                const available = message.data[inst].available;
                if (available) {
                  statusEl.innerHTML = '<span class="status-dot online"></span> Online';
                } else {
                  statusEl.innerHTML = '<span class="status-dot offline"></span> Offline';
                }
              } else if (statusEl && message.error) {
                statusEl.innerHTML = '<span class="status-dot error"></span> Error';
              }
            });
            // Update services tab badge
            updateServicesTabBadge();
          }

          // Ollama test result handler
          if (message.command === 'ollamaTestResult') {
            const instance = message.instance;
            const statusEl = document.getElementById(instance + 'Status');
            const latencyEl = document.getElementById(instance + 'Latency');

            if (statusEl) {
              if (message.error) {
                statusEl.innerHTML = '<span class="status-dot error"></span> Error';
              } else if (message.data && message.data.success) {
                statusEl.innerHTML = '<span class="status-dot online"></span> OK';
                if (latencyEl && message.data.latency) {
                  latencyEl.textContent = message.data.latency + 'ms';
                }
              }
            }
          }

          // Inference test result handler
          if (message.command === 'inferenceTestResult') {
            // Debug: console.log('[CommandCenter-Webview] Received inferenceTestResult:', message.data);

            const resultDiv = document.getElementById('inferenceResult');

            if (resultDiv && message.data) {
              const data = message.data;
              const ctx = data.context || {};
              const mem = data.memory_state || {};
              const env = data.environment || {};

              // Build the layer badges
              const methods = data.methods || [];
              const layerNames = {
                'layer1_core': '🔵 Core',
                'layer2_persona': '🟢 Persona',
                'layer3_skill': '🎯 Skill',
                'layer4_npu': '🟣 NPU',
                'layer4_keyword_fallback': '🟡 Keyword',
                'fast_path': '⚡ Fast',
              };
              const layerBadges = methods.map(m => '<span class="layer-badge" style="background: rgba(139,92,246,0.2); padding: 2px 8px; border-radius: 12px; font-size: 11px;">' + (layerNames[m] || m) + '</span>').join(' → ');

              // Error banner if any
              const escapeHtml = (str) => (str || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
              const errorBanner = data.error
                ? '<div style="background: var(--vscode-inputValidation-errorBackground); padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; color: var(--vscode-errorForeground);">⚠️ ' + escapeHtml(data.error) + '</div>'
                : '';

              // === Build Context Sections ===
              let contextHtml = '';

              // Summary header
              const finalToolCount = (data.tools || []).length;
              contextHtml += '<div style="display: flex; align-items: baseline; gap: 12px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--vscode-widget-border);">' +
                '<span style="font-size: 1.3em; font-weight: bold; color: var(--vscode-testing-iconPassed);">✅ ' + finalToolCount + ' tools</span>' +
                '<span style="color: var(--vscode-descriptionForeground);">' + (data.latency_ms || 0) + 'ms • ' + (data.reduction_pct || 0).toFixed(1) + '% reduction</span>' +
                '<span style="margin-left: auto;">' + layerBadges + '</span>' +
              '</div>';

              // === 1. SYSTEM PROMPT / PERSONA SECTION ===
              const personaIcons = { developer: '👨‍💻', devops: '🔧', incident: '🚨', release: '📦' };
              const personaPrompt = data.persona_prompt || ctx.persona_prompt || '';
              const personaCategories = data.persona_categories || [];
              const personaAutoDetected = data.persona_auto_detected || false;
              const personaReason = data.persona_detection_reason || 'passed_in';
              contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(34,197,94,0.1); border-radius: 8px; border-left: 3px solid #22c55e;">' +
                '<div style="font-weight: bold; margin-bottom: 8px;">' + (personaIcons[data.persona] || '👤') + ' System Prompt (Persona: ' + escapeHtml(data.persona) + ')' +
                  (personaAutoDetected ? ' <span style="background: rgba(34,197,94,0.3); padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: normal;">🔍 Auto-detected via ' + escapeHtml(personaReason) + '</span>' : '') +
                '</div>' +
                (personaCategories.length > 0 ? '<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 8px;">Tool Categories: <span style="color: var(--vscode-foreground);">' + personaCategories.map(c => escapeHtml(c)).join(', ') + '</span></div>' : '<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 8px;">Tool Categories: <span style="opacity: 0.5;">none configured</span></div>') +
                (personaPrompt ? '<div style="font-size: 11px; font-style: italic; color: var(--vscode-descriptionForeground); padding: 8px; background: rgba(0,0,0,0.1); border-radius: 4px; max-height: 80px; overflow-y: auto;">"' + escapeHtml(personaPrompt.substring(0, 300)) + (personaPrompt.length > 300 ? '..."' : '"') + '</div>' : '') +
              '</div>';

              // === 2. MEMORY STATE SECTION (with inline environment status) ===
              const kubeconfigs = env.kubeconfigs || {};
              const activeIssues = mem.active_issues || [];
              contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(168,85,247,0.1); border-radius: 8px; border-left: 3px solid #a855f7;">' +
                '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
                  '<span style="font-weight: bold;">🧠 Memory State</span>' +
                  '<span style="font-size: 11px; display: flex; gap: 8px;">' +
                    '<span>' + (env.vpn_connected ? '🟢' : '🔴') + ' VPN</span>' +
                    '<span>' + (kubeconfigs.stage ? '🟢' : '⚪') + ' Stage</span>' +
                    '<span>' + (kubeconfigs.prod ? '🟢' : '⚪') + ' Prod</span>' +
                    '<span>' + (kubeconfigs.ephemeral ? '🟢' : '⚪') + ' Eph</span>' +
                  '</span>' +
                '</div>' +
                '<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 12px;">' +
                  '<div><span style="color: var(--vscode-descriptionForeground);">Current Repo:</span> <code>' + escapeHtml(mem.current_repo || 'none') + '</code></div>' +
                  '<div><span style="color: var(--vscode-descriptionForeground);">Current Branch:</span> <code>' + escapeHtml(mem.current_branch || 'none') + '</code></div>' +
                '</div>' +
                (activeIssues.length > 0 ?
                  '<div style="margin-top: 8px;"><span style="color: var(--vscode-descriptionForeground); font-size: 12px;">Active Issues:</span>' +
                  '<div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">' +
                    activeIssues.map(i => '<span style="background: rgba(168,85,247,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + escapeHtml(i.key || i) + '</span>').join('') +
                  '</div></div>' : '<div style="margin-top: 8px; font-size: 11px; color: var(--vscode-descriptionForeground);">No active issues</div>') +
                (mem.notes ? '<div style="margin-top: 8px; font-size: 11px; padding: 6px; background: rgba(0,0,0,0.1); border-radius: 4px;"><strong>Notes:</strong> ' + escapeHtml(mem.notes) + '</div>' : '') +
              '</div>';

              // === 3. SESSION LOG SECTION ===
              const sessionLog = data.session_log || [];
              if (sessionLog.length > 0) {
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(99,102,241,0.1); border-radius: 8px; border-left: 3px solid #6366f1;">' +
                  '<div style="font-weight: bold; margin-bottom: 8px;">📝 Session Log (Recent Actions)</div>' +
                  '<div style="font-size: 11px; display: flex; flex-direction: column; gap: 4px; max-height: 100px; overflow-y: auto;">' +
                    sessionLog.map(a =>
                      '<div style="padding: 4px 8px; background: rgba(0,0,0,0.1); border-radius: 4px;">' +
                        '<span style="color: var(--vscode-descriptionForeground);">' + escapeHtml((a.time || '').substring(11, 19)) + '</span> ' +
                        escapeHtml(a.action || a) +
                      '</div>'
                    ).join('') +
                  '</div>' +
                '</div>';
              }

              // === 5. SKILL SECTION ===
              if (ctx.skill && ctx.skill.name) {
                const memOps = ctx.skill.memory_ops || { reads: [], writes: [] };
                // Format skill description - replace markdown headers and newlines
                let skillDesc = ctx.skill.description || '';
                skillDesc = skillDesc
                  .replace(/##\\s+/g, '<br><strong>')  // ## headers
                  .replace(/\\n-\\s+/g, '<br>• ')       // - bullet points
                  .replace(/\\n\\n/g, '<br><br>')       // double newlines
                  .replace(/\\n/g, '<br>')             // single newlines
                  .replace(/<strong>([^<]+)(<br>|$)/g, '<strong>$1</strong>$2');  // close strong tags
                // Truncate if too long
                if (skillDesc.length > 500) {
                  skillDesc = skillDesc.substring(0, 500) + '...';
                }
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(139,92,246,0.1); border-radius: 8px; border-left: 3px solid #8b5cf6;">' +
                  '<div style="font-weight: bold; margin-bottom: 8px;">🎯 Detected Skill: ' + escapeHtml(ctx.skill.name) + '</div>' +
                  (skillDesc ? '<div style="font-size: 12px; margin-bottom: 8px; max-height: 120px; overflow-y: auto; padding: 8px; background: rgba(0,0,0,0.1); border-radius: 4px;">' + skillDesc + '</div>' : '') +
                  (ctx.skill.inputs && ctx.skill.inputs.length > 0 ?
                    '<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 6px;">Inputs: ' +
                      ctx.skill.inputs.map(i => '<code style="background: rgba(139,92,246,0.2); padding: 1px 4px; border-radius: 3px;">' + (i.name || i) + (i.required ? '*' : '') + '</code>').join(', ') +
                    '</div>' : '') +
                  '<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 6px;">Tools used by skill:</div>' +
                  '<div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px;">' +
                    (ctx.skill.tools || []).map(t => '<span class="tool-chip" style="background: rgba(139,92,246,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t + '</span>').join('') +
                  '</div>' +
                  (memOps.reads.length > 0 || memOps.writes.length > 0 ?
                    '<div style="font-size: 11px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(139,92,246,0.2);">' +
                      '<div style="color: var(--vscode-descriptionForeground); margin-bottom: 4px;">Memory Operations:</div>' +
                      (memOps.reads.length > 0 ? '<div style="margin-bottom: 4px;">📖 Reads: ' + memOps.reads.map(r => '<code style="background: rgba(34,197,94,0.2); padding: 1px 4px; border-radius: 3px; font-size: 10px;">' + (r.key || r.tool || 'unknown') + '</code>').join(' ') + '</div>' : '') +
                      (memOps.writes.length > 0 ? '<div>✏️ Writes: ' + memOps.writes.map(w => '<code style="background: rgba(245,158,11,0.2); padding: 1px 4px; border-radius: 3px; font-size: 10px;">' + (w.key || w.tool || 'unknown') + '</code>').join(' ') + '</div>' : '') +
                    '</div>' : '') +
                '</div>';
              }

              // === 6. LEARNED PATTERNS SECTION ===
              const learnedPatterns = data.learned_patterns || [];
              if (learnedPatterns.length > 0) {
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(236,72,153,0.1); border-radius: 8px; border-left: 3px solid #ec4899;">' +
                  '<div style="font-weight: bold; margin-bottom: 8px;">💡 Learned Patterns</div>' +
                  '<div style="font-size: 11px; display: flex; flex-direction: column; gap: 6px;">' +
                    learnedPatterns.map(p =>
                      '<div style="padding: 6px 8px; background: rgba(0,0,0,0.1); border-radius: 4px;">' +
                        '<div style="color: var(--vscode-errorForeground);">Pattern: ' + escapeHtml((p.pattern || '').substring(0, 50)) + '</div>' +
                        '<div style="color: var(--vscode-testing-iconPassed);">Fix: ' + escapeHtml((p.fix || '').substring(0, 100)) + '</div>' +
                      '</div>'
                    ).join('') +
                  '</div>' +
                '</div>';
              }

              // === 7. NPU/AI CLASSIFICATION SECTION ===
              const npuMethodNames = { npu: '🧠 NPU Inference', keyword_fallback: '🔤 Keyword Match', expanded_baseline: '📊 Expanded Baseline', fast_path: '⚡ Fast Path (skipped NPU)' };
              const npuMethod = ctx.npu && ctx.npu.method ? ctx.npu.method : null;
              const npuSkipped = methods.includes('fast_path') || methods.includes('layer3_skill');
              contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(236,72,153,' + (npuMethod ? '0.1' : '0.05') + '); border-radius: 8px; border-left: 3px solid ' + (npuMethod ? '#ec4899' : 'rgba(236,72,153,0.3)') + ';">' +
                '<div style="font-weight: bold; margin-bottom: 8px; ' + (npuMethod ? '' : 'opacity: 0.6;') + '">' +
                  (npuMethod ? npuMethodNames[npuMethod] || '🤖 AI Classification: ' + npuMethod : '🧠 NPU Inference') +
                '</div>';
              if (npuMethod && ctx.npu) {
                contextHtml += (ctx.npu.categories && ctx.npu.categories.length > 0 ?
                    '<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 6px;">Added categories: ' + ctx.npu.categories.join(', ') + '</div>' : '') +
                  '<div style="display: flex; flex-wrap: wrap; gap: 4px;">' +
                    (ctx.npu.tools || []).map(t => '<span class="tool-chip" style="background: rgba(236,72,153,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t + '</span>').join('') +
                  '</div>';
              } else {
                contextHtml += '<div style="font-size: 11px; color: var(--vscode-descriptionForeground);">' +
                  (npuSkipped ? 'Skipped - skill detection or fast path provided sufficient tools' : 'Not triggered - persona baseline was sufficient') +
                '</div>';
              }
              contextHtml += '</div>';

              // === 8. FAST MATCH SECTION ===
              if (ctx.fast_match && ctx.fast_match.categories && ctx.fast_match.categories.length > 0) {
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(251,191,36,0.1); border-radius: 8px; border-left: 3px solid #fbbf24;">' +
                  '<div style="font-weight: bold; margin-bottom: 8px;">⚡ Fast Pattern Match</div>' +
                  '<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 6px;">Matched: ' + ctx.fast_match.categories.join(', ') + '</div>' +
                  '<div style="display: flex; flex-wrap: wrap; gap: 4px;">' +
                    (ctx.fast_match.tools || []).slice(0, 10).map(t => '<span class="tool-chip" style="background: rgba(251,191,36,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t + '</span>').join('') +
                  '</div>' +
                '</div>';
              }

              // === 9. CORE TOOLS SECTION ===
              if (ctx.core && ctx.core.tools && ctx.core.tools.length > 0) {
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(59,130,246,0.1); border-radius: 8px; border-left: 3px solid #3b82f6;">' +
                  '<div style="font-weight: bold; margin-bottom: 8px;">🔵 Core Tools (Always Included)</div>' +
                  '<div style="display: flex; flex-wrap: wrap; gap: 4px;">' +
                    ctx.core.tools.map(t => '<span class="tool-chip" style="background: rgba(59,130,246,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t + '</span>').join('') +
                  '</div>' +
                '</div>';
              }

              // === 10. SEMANTIC SEARCH RESULTS ===
              const semanticResults = ctx.semantic_knowledge || [];
              if (semanticResults.length > 0) {
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(14,165,233,0.1); border-radius: 8px; border-left: 3px solid #0ea5e9;">' +
                  '<div style="font-weight: bold; margin-bottom: 8px;">🔍 Semantic Knowledge (' + semanticResults.length + ' matches)</div>' +
                  '<div style="font-size: 11px; color: var(--vscode-descriptionForeground); margin-bottom: 8px;">Code snippets from vector search that would enrich the context:</div>' +
                  '<div style="display: flex; flex-direction: column; gap: 8px; max-height: 200px; overflow-y: auto;">' +
                    semanticResults.map(r =>
                      '<div style="background: var(--vscode-editor-background); padding: 8px; border-radius: 4px; border: 1px solid var(--vscode-widget-border);">' +
                        '<div style="display: flex; justify-content: space-between; margin-bottom: 4px;">' +
                          '<code style="font-size: 11px; color: var(--vscode-textLink-foreground);">' + (r.file || 'unknown') + (r.lines ? ':' + r.lines : '') + '</code>' +
                          '<span style="font-size: 10px; color: var(--vscode-descriptionForeground);">' + ((r.relevance || 0) * 100).toFixed(0) + '% match</span>' +
                        '</div>' +
                        '<pre style="margin: 0; font-size: 10px; white-space: pre-wrap; max-height: 60px; overflow: hidden; color: var(--vscode-editor-foreground);">' + (r.content || '').substring(0, 200) + '</pre>' +
                      '</div>'
                    ).join('') +
                  '</div>' +
                '</div>';
              } else {
                contextHtml += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(14,165,233,0.05); border-radius: 8px; border-left: 3px solid rgba(14,165,233,0.3);">' +
                  '<div style="font-weight: bold; margin-bottom: 8px; opacity: 0.6;">🔍 Semantic Knowledge</div>' +
                  '<div style="font-size: 11px; color: var(--vscode-descriptionForeground);">No code snippets found (vector search may not be indexed for this project)</div>' +
                '</div>';
              }

              // === 11. FINAL TOOLS LIST ===
              const tools = data.tools || [];
              contextHtml += '<div class="context-section" style="padding: 12px; background: var(--vscode-editor-background); border-radius: 8px; border: 1px solid var(--vscode-widget-border);">' +
                '<div style="font-weight: bold; margin-bottom: 8px;">📋 Final Tool List (' + tools.length + ' tools)</div>' +
                '<div style="display: flex; flex-wrap: wrap; gap: 4px; max-height: 150px; overflow-y: auto;">' +
                  tools.map(t => '<span class="tool-chip" style="background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t + '</span>').join('') +
                '</div>' +
              '</div>';

              // Rebuild the entire result HTML
              resultDiv.style.display = 'block';
              resultDiv.innerHTML = errorBanner + contextHtml;
            }
          }

          // Inference stats update handler
          if (message.command === 'inferenceStatsUpdate') {
            const data = message.data;
            if (!data) return;

            // Update stats cards
            const totalEl = document.getElementById('inferenceTotal');
            if (totalEl) totalEl.textContent = data.total_requests || 0;

            const cacheHitEl = document.getElementById('inferenceCacheHit');
            if (cacheHitEl && data.cache) {
              const rate = data.cache.hit_rate || 0;
              cacheHitEl.textContent = rate.toFixed(1) + '%';
            }

            // Update history
            const historyEl = document.getElementById('inferenceHistory');
            if (historyEl && data.recent_history && data.recent_history.length > 0) {
              historyEl.innerHTML = data.recent_history.slice(0, 10).map(h => {
                const msg = h.message_preview || h.message || '';
                return '<div class="history-item">' +
                  '<span class="history-message">' + msg.substring(0, 40) + (msg.length > 40 ? '...' : '') + '</span>' +
                  '<span class="history-tools">' + (h.tool_count || 0) + ' tools</span>' +
                  '<span class="history-time">' + (h.latency_ms || 0).toFixed(0) + 'ms</span>' +
                  '</div>';
              }).join('');
            }

            // Update persona stats table
            const personaStatsBody = document.getElementById('personaStatsBody');
            if (personaStatsBody) {
              // Dynamic color palette - cycles through colors for any number of personas
              const colorPalette = [
                'var(--purple)',   // #8b5cf6
                'var(--cyan)',     // #06b6d4
                'var(--pink)',     // #ec4899
                'var(--orange)',   // #f97316
                'var(--success)',  // #10b981 (green)
                'var(--info)',     // #3b82f6 (blue)
                'var(--warning)',  // #f59e0b (amber)
                '#a855f7',         // violet
                '#14b8a6',         // teal
                '#f43f5e',         // rose
              ];

              // Generate a simple hash to get consistent color for each persona name
              const getPersonaColor = (name, idx) => {
                let hash = 0;
                for (let i = 0; i < name.length; i++) {
                  hash = ((hash << 5) - hash) + name.charCodeAt(i);
                  hash = hash & hash;
                }
                return colorPalette[Math.abs(hash) % colorPalette.length];
              };

              // Generate icon based on first letter or known patterns
              const getPersonaIcon = (name) => {
                const lower = name.toLowerCase();
                // Check for common patterns in the name
                if (lower.includes('dev') && lower.includes('ops')) return '🔧';
                if (lower.includes('develop')) return '👨‍💻';
                if (lower.includes('incident') || lower.includes('oncall')) return '🚨';
                if (lower.includes('release') || lower.includes('ship')) return '📦';
                if (lower.includes('admin')) return '👑';
                if (lower.includes('slack')) return '💬';
                if (lower.includes('test')) return '🧪';
                if (lower.includes('security') || lower.includes('sec')) return '🔒';
                if (lower.includes('data')) return '📊';
                if (lower.includes('ml') || lower.includes('ai')) return '🤖';
                if (lower.includes('infra')) return '🏗️';
                if (lower.includes('platform')) return '🌐';
                if (lower.includes('support')) return '🎧';
                if (lower.includes('qa')) return '✅';
                if (lower.includes('core')) return '⚙️';
                if (lower.includes('universal')) return '🌍';
                // Default: use first letter as emoji-style or generic icon
                return '👤';
              };

              // Build list of all personas to show (available + any with stats)
              const availablePersonas = data.available_personas || [];
              const personasWithStats = Object.keys(data.by_persona || {});
              const allPersonas = [...new Set([...availablePersonas, ...personasWithStats])].sort();

              if (allPersonas.length > 0) {
                personaStatsBody.innerHTML = allPersonas.map((persona, idx) => {
                  const stats = (data.by_persona || {})[persona] || {};
                  const hasStats = stats.requests > 0;
                  const icon = getPersonaIcon(persona);
                  const color = getPersonaColor(persona, idx);
                  const tierTotal = (stats.tier1_only || 0) + (stats.tier2_skill || 0) + (stats.tier3_npu || 0);
                  const rowOpacity = hasStats ? '1' : '0.5';

                  return '<tr style="--row-accent: ' + color + '; opacity: ' + rowOpacity + ';">' +
                    '<td><span style="margin-right: 8px;">' + icon + '</span>' + persona + '</td>' +
                    '<td><span style="font-weight: 700; color: ' + color + ';">' + (stats.requests || 0) + '</span></td>' +
                    '<td>' + (hasStats ? stats.tools_min : '-') + '</td>' +
                    '<td>' + (hasStats ? stats.tools_max : '-') + '</td>' +
                    '<td><span style="font-weight: 600;">' + (hasStats ? (stats.tools_mean || 0).toFixed(1) : '-') + '</span></td>' +
                    '<td>' + (hasStats ? stats.tools_median : '-') + '</td>' +
                    '<td>' + (tierTotal > 0 ? '<span style="opacity: ' + ((stats.tier1_only || 0) / tierTotal * 0.7 + 0.3) + ';">' + (stats.tier1_only || 0) + '</span>' : (hasStats ? '0' : '-')) + '</td>' +
                    '<td>' + (tierTotal > 0 ? '<span style="color: var(--cyan); opacity: ' + ((stats.tier2_skill || 0) / tierTotal * 0.7 + 0.3) + ';">' + (stats.tier2_skill || 0) + '</span>' : (hasStats ? '0' : '-')) + '</td>' +
                    '<td>' + (tierTotal > 0 ? '<span style="color: var(--pink); opacity: ' + ((stats.tier3_npu || 0) / tierTotal * 0.7 + 0.3) + ';">' + (stats.tier3_npu || 0) + '</span>' : (hasStats ? '0' : '-')) + '</td>' +
                    '</tr>';
                }).join('');
              } else {
                personaStatsBody.innerHTML = '<tr><td colspan="9" class="empty-state">No personas configured</td></tr>';
              }
            }

            // Update performance metrics
            const avgLatencyEl = document.getElementById('avgLatency');
            const avgReductionEl = document.getElementById('avgReduction');
            const cacheHitRateEl = document.getElementById('cacheHitRate');
            const totalRequestsEl = document.getElementById('totalRequests');

            if (totalRequestsEl) totalRequestsEl.textContent = data.total_requests || 0;
            if (cacheHitRateEl && data.cache) {
              cacheHitRateEl.textContent = ((data.cache.hit_rate || 0) * 100).toFixed(1) + '%';
            }

            // Calculate avg latency and reduction from recent history
            if (data.recent_history && data.recent_history.length > 0) {
              const avgLatency = data.recent_history.reduce((sum, h) => sum + (h.latency_ms || 0), 0) / data.recent_history.length;
              const avgReduction = data.recent_history.reduce((sum, h) => sum + (h.reduction_pct || 0), 0) / data.recent_history.length;
              if (avgLatencyEl) avgLatencyEl.textContent = avgLatency.toFixed(0) + 'ms';
              if (avgReductionEl) avgReductionEl.textContent = avgReduction.toFixed(1) + '%';
            }

            // Update latency histogram
            if (data.latency) {
              const total = Object.values(data.latency).reduce((a, b) => a + b, 0);
              if (total > 0) {
                const updateBar = (id, count) => {
                  const bar = document.getElementById(id);
                  const pct = document.getElementById(id + '-pct');
                  const percent = (count / total) * 100;
                  if (bar) bar.style.width = percent + '%';
                  if (pct) pct.textContent = percent.toFixed(0) + '%';
                };
                updateBar('latency-10', data.latency['<10ms'] || 0);
                updateBar('latency-100', data.latency['10-100ms'] || 0);
                updateBar('latency-500', data.latency['100-500ms'] || 0);
                updateBar('latency-over', data.latency['>500ms'] || 0);
              }
            }
          }
        });

        function updateSprintIssues(issues) {
          const container = document.getElementById('sprintIssues');
          if (!container) return;

          if (!issues || issues.length === 0) {
            container.innerHTML = '<div class="loading-placeholder">No assigned issues in current sprint</div>';
            return;
          }

          const typeIcons = {
            'Story': '📖',
            'Bug': '🐛',
            'Task': '✅',
            'Epic': '🎯',
            'Spike': '🔬'
          };

          const priorityColors = {
            'Blocker': 'var(--error)',
            'Critical': 'var(--error)',
            'Major': 'var(--warning)',
            'Normal': 'var(--text-secondary)',
            'Minor': 'var(--text-muted)'
          };

          container.innerHTML = issues.map(issue => {
            const statusClass = issue.status?.toLowerCase().includes('progress') ? 'in-progress' :
                               issue.status?.toLowerCase().includes('done') || issue.status?.toLowerCase().includes('review') ? 'done' : '';
            const icon = typeIcons[issue.type] || '📋';
            const priorityColor = priorityColors[issue.priority] || 'var(--text-secondary)';
            return \`
              <div class="sprint-issue" data-issue="\${issue.key}">
                <span class="sprint-issue-icon">\${icon}</span>
                <span class="sprint-issue-key">\${issue.key}</span>
                <span class="sprint-issue-summary">\${issue.summary || ''}</span>
                <span class="sprint-issue-priority" style="color: \${priorityColor}">\${issue.priority || ''}</span>
                <span class="sprint-issue-status \${statusClass}">\${issue.status || 'Open'}</span>
              </div>
            \`;
          }).join('');

          // Add click handlers
          container.querySelectorAll('.sprint-issue').forEach(el => {
            el.addEventListener('click', () => {
              const key = el.getAttribute('data-issue');
              if (key) {
                vscode.postMessage({ command: 'openJiraIssue', issueKey: key });
              }
            });
          });
        }

        function updateWorkspacesTab(data) {
          // Update session count badge
          const badge = document.getElementById('workspacesBadge');
          if (badge) {
            badge.textContent = data.totalSessions || '0';
          }

          // Update stats
          const totalEl = document.getElementById('totalWorkspaces');
          if (totalEl) totalEl.textContent = data.count || '0';

          const personasEl = document.getElementById('uniquePersonas');
          if (personasEl) personasEl.textContent = data.uniquePersonas || '0';

          const projectsEl = document.getElementById('uniqueProjects');
          if (projectsEl) projectsEl.textContent = data.uniqueProjects || '0';

          // Update total sessions count in header
          const sessionsCountEl = document.querySelector('.workspaces-grid')?.parentElement?.querySelector('[style*="font-size: 0.9rem"]');
          if (sessionsCountEl) {
            sessionsCountEl.textContent = \`\${data.totalSessions || 0} session(s)\`;
          }

          // Update group by select to match current state
          const groupBySelect = document.getElementById('sessionGroupBy');
          if (groupBySelect && data.groupBy) {
            groupBySelect.value = data.groupBy;
          }

          // Update workspace grid with pre-rendered HTML
          const grid = document.getElementById('workspacesGrid');
          if (grid && data.renderedHtml !== undefined) {
            grid.innerHTML = data.renderedHtml;
          }
        }

        // Show/hide search loading state
        function setSearchLoading(loading) {
          const searchIcon = document.getElementById('sessionSearchIcon');
          const searchSpinner = document.getElementById('sessionSearchSpinner');
          const searchInput = document.getElementById('sessionSearchInput');

          if (searchIcon) searchIcon.style.display = loading ? 'none' : 'block';
          if (searchSpinner) searchSpinner.style.display = loading ? 'block' : 'none';
          if (searchInput) searchInput.style.opacity = loading ? '0.7' : '1';
        }

        // Handle search results
        function handleSearchResults(data) {
          // Hide loading state
          setSearchLoading(false);

          const resultsContainer = document.getElementById('sessionSearchResults');
          const resultsContent = document.getElementById('searchResultsContent');
          const resultCount = document.getElementById('searchResultCount');
          const searchInput = document.getElementById('sessionSearchInput');
          const clearBtn = document.getElementById('sessionSearchClear');
          const mainGrid = document.getElementById('workspacesGrid');

          if (!data.query || data.query.trim() === '') {
            // Clear search - show main grid
            if (resultsContainer) resultsContainer.style.display = 'none';
            if (mainGrid) mainGrid.style.display = '';
            if (clearBtn) clearBtn.style.display = 'none';
            return;
          }

          // Show search results
          if (resultsContainer) resultsContainer.style.display = 'block';
          if (mainGrid) mainGrid.style.display = 'none';
          if (clearBtn) clearBtn.style.display = 'block';

          // Update count
          const isLocal = data.isLocalSearch ? ' (name only)' : '';
          if (resultCount) {
            resultCount.textContent = \`(\${data.results?.length || 0} found\${isLocal})\`;
          }

          // Render results
          if (resultsContent && data.results) {
            if (data.results.length === 0) {
              resultsContent.innerHTML = \`
                <div class="empty-state" style="grid-column: 1 / -1;">
                  <div class="empty-state-icon">🔍</div>
                  <div>No results found for "\${data.query}"</div>
                  <div style="font-size: 0.8rem; margin-top: 8px; color: var(--text-muted);">
                    \${data.isLocalSearch ? 'Tip: Start the Session Daemon for full-text search' : 'Try a different search term'}
                  </div>
                </div>
              \`;
            } else {
              resultsContent.innerHTML = data.results.map(r => \`
                <div class="session-card" style="cursor: pointer;" onclick="vscode.postMessage({ command: 'openChatSession', sessionId: '\${r.session_id}', sessionName: '\${(r.name || '').replace(/'/g, "\\\\'")}' })">
                  <div class="session-header">
                    <span class="session-name">\${r.name || 'Unnamed'}</span>
                    <span class="session-project" style="background: var(--bg-secondary); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem;">\${r.project}</span>
                  </div>
                  \${r.name_match ? '<div style="color: var(--green); font-size: 0.8rem; margin-top: 4px;">✓ Name matches</div>' : ''}
                  \${r.content_matches && r.content_matches.length > 0 ? \`
                    <div style="margin-top: 8px; font-size: 0.8rem; color: var(--text-muted);">
                      \${r.content_matches.slice(0, 2).map(m => \`
                        <div style="background: var(--bg-secondary); padding: 6px 8px; border-radius: 4px; margin-top: 4px; border-left: 2px solid var(--accent);">
                          <span style="color: var(--text-muted); font-size: 0.7rem;">\${m.role}:</span> \${m.snippet}
                        </div>
                      \`).join('')}
                      \${r.match_count > 2 ? \`<div style="margin-top: 4px; color: var(--text-muted);">+\${r.match_count - 2} more matches</div>\` : ''}
                    </div>
                  \` : ''}
                </div>
              \`).join('');
            }
          }
        }

        // Setup search input handlers
        document.addEventListener('DOMContentLoaded', function() {
          const searchInput = document.getElementById('sessionSearchInput');
          const clearBtn = document.getElementById('sessionSearchClear');
          const clearSearchBtn = document.getElementById('clearSearchBtn');

          if (searchInput) {
            let searchTimeout;
            searchInput.addEventListener('input', function() {
              clearTimeout(searchTimeout);
              const query = this.value.trim();

              // Show/hide clear button
              if (clearBtn) {
                clearBtn.style.display = query ? 'block' : 'none';
              }

              // Debounce search
              if (query.length >= 2) {
                // Show loading spinner
                setSearchLoading(true);
                searchTimeout = setTimeout(() => {
                  vscode.postMessage({ command: 'searchSessions', query: query });
                }, 300);
              } else if (query.length === 0) {
                // Clear results
                setSearchLoading(false);
                vscode.postMessage({ command: 'searchSessions', query: '' });
              }
            });

            // Also handle Enter key
            searchInput.addEventListener('keydown', function(e) {
              if (e.key === 'Enter' && this.value.trim().length >= 2) {
                clearTimeout(searchTimeout);
                setSearchLoading(true);
                vscode.postMessage({ command: 'searchSessions', query: this.value.trim() });
              }
            });
          }

          if (clearBtn) {
            clearBtn.addEventListener('click', function() {
              if (searchInput) searchInput.value = '';
              this.style.display = 'none';
              setSearchLoading(false);
              vscode.postMessage({ command: 'searchSessions', query: '' });
            });
          }

          if (clearSearchBtn) {
            clearSearchBtn.addEventListener('click', function() {
              if (searchInput) searchInput.value = '';
              if (clearBtn) clearBtn.style.display = 'none';
              setSearchLoading(false);
              vscode.postMessage({ command: 'searchSessions', query: '' });
            });
          }
        });

        // Cache for detecting sprint content changes to avoid unnecessary DOM updates
        let _lastSprintContentHash = '';

        // Incremental update for Sprint tab - avoids full DOM re-render
        // Uses hash comparison to skip unnecessary DOM updates
        function updateSprintTab(data) {
          // Update sprint tab badge - show total issues count
          const badge = document.getElementById('sprintTabBadge');
          if (badge) {
            const totalIssues = (data.issues || []).length;
            if (badge.textContent !== totalIssues.toString()) {
              badge.textContent = totalIssues.toString();
            }
            const shouldShow = totalIssues > 0;
            if ((badge.style.display === 'none') !== !shouldShow) {
              badge.style.display = shouldShow ? '' : 'none';
            }
          }

          // Update sprint content container with pre-rendered HTML
          const container = document.getElementById('sprint-content');
          if (container && data.renderedHtml !== undefined) {
            // Create a simple hash to detect changes (avoids unnecessary DOM thrashing)
            // Use issues array as the hash since it's smaller than full HTML
            const newHash = JSON.stringify(data.issues || []);
            if (newHash === _lastSprintContentHash) {
              console.log('[CommandCenter] updateSprintTab: No changes detected, skipping DOM update');
              return;
            }
            _lastSprintContentHash = newHash;

            // Use requestAnimationFrame to batch the DOM update
            requestAnimationFrame(() => {
              container.innerHTML = data.renderedHtml;
              // Re-initialize sprint tab event handlers after content update
              if (typeof initSprintTab === 'function') {
                initSprintTab();
              }
            });
          }
        }

        // Incremental update for Meetings tab badge
        function updateMeetingsTabBadge(data) {
          const badge = document.getElementById('meetingsTabBadge');
          if (badge) {
            const isLive = data.currentMeeting || (data.currentMeetings && data.currentMeetings.length > 0);
            const upcomingCount = (data.upcomingMeetings || []).length;

            if (isLive) {
              badge.textContent = 'Live';
              badge.className = 'tab-badge running';
              badge.style.display = '';
            } else if (upcomingCount > 0) {
              badge.textContent = upcomingCount.toString();
              badge.className = 'tab-badge';
              badge.style.display = '';
            } else {
              badge.style.display = 'none';
            }
          }
        }

        // Incremental update for Performance tab badge
        function updatePerformanceTabBadge(percentage) {
          const badge = document.getElementById('performanceTabBadge');
          if (badge) {
            badge.textContent = percentage + '%';
            badge.style.display = percentage > 0 ? '' : 'none';
          }
        }

        function renderWorkspaceCard(uri, ws) {
          const project = ws.project || ws.auto_detected_project || 'No project';
          const shortUri = uri.replace('file://', '').split('/').slice(-2).join('/');

          // Get active session data (sessions are now stored in ws.sessions)
          const activeSessionId = ws.active_session_id;
          const sessions = ws.sessions || {};
          const activeSession = activeSessionId ? sessions[activeSessionId] : null;

          // Get persona, tools, and started_at from active session (with fallbacks)
          const persona = activeSession?.persona || ws.persona || 'No persona';
          const personaIcon = getPersonaIcon(persona);
          const personaColor = getPersonaColor(persona);
          const toolCount = activeSession?.tool_count ?? activeSession?.active_tools?.length ?? 0;
          const startedAt = activeSession?.started_at
            ? new Date(activeSession.started_at).toLocaleString()
            : (ws.started_at ? new Date(ws.started_at).toLocaleString() : 'Unknown');

          // Available personas for the dropdown
          const availablePersonas = ['developer', 'devops', 'incident', 'release'];

          return \`
            <div class="workspace-card" data-workspace-uri="\${uri}">
              <div class="workspace-header">
                <div class="workspace-icon \${personaColor}">\${personaIcon}</div>
                <div class="workspace-info">
                  <div class="workspace-project">\${project}</div>
                  <div class="workspace-uri" title="\${uri}">\${shortUri}</div>
                </div>
              </div>
              <div class="workspace-body">
                <div class="workspace-row">
                  <span class="workspace-label">Persona</span>
                  <select class="persona-select \${personaColor}" data-workspace-uri="\${uri}" onchange="changeWorkspacePersona(this)">
                    \${availablePersonas.map(p => \`
                      <option value="\${p}" \${p === persona ? 'selected' : ''}>\${getPersonaIcon(p)} \${p}</option>
                    \`).join('')}
                    \${!availablePersonas.includes(persona) && persona !== 'No persona' ? \`<option value="\${persona}" selected>\${personaIcon} \${persona}</option>\` : ''}
                  </select>
                </div>
                \${(activeSession?.issue_key || ws.issue_key) ? \`
                <div class="workspace-row">
                  <span class="workspace-label">Issue</span>
                  <span class="workspace-value issue-badge">\${activeSession?.issue_key || ws.issue_key}</span>
                </div>
                \` : ''}
                \${(activeSession?.branch || ws.branch) ? \`
                <div class="workspace-row">
                  <span class="workspace-label">Branch</span>
                  <span class="workspace-value branch-badge">\${activeSession?.branch || ws.branch}</span>
                </div>
                \` : ''}
                <div class="workspace-row">
                  <span class="workspace-label">Tools</span>
                  <span class="workspace-value">\${toolCount} active</span>
                </div>
                <div class="workspace-row">
                  <span class="workspace-label">Started</span>
                  <span class="workspace-value">\${startedAt}</span>
                </div>
              </div>
              <div class="workspace-footer">
                <button class="btn btn-ghost btn-small" data-action="viewWorkspaceTools" data-uri="\${uri}">
                  🔧 Tools
                </button>
                <button class="btn btn-ghost btn-small" data-action="switchToWorkspace" data-uri="\${uri}">
                  🔄 Switch
                </button>
              </div>
            </div>
          \`;
        }

        function getPersonaIcon(name) {
          const iconMap = {
            developer: '👨‍💻',
            devops: '🔧',
            incident: '🚨',
            release: '📦',
            admin: '📊',
            slack: '💬',
            core: '⚙️',
            universal: '🌐',
          };
          return iconMap[name] || '🤖';
        }

        function getPersonaColor(name) {
          const colorMap = {
            developer: 'purple',
            devops: 'cyan',
            incident: 'pink',
            release: 'green',
            admin: 'orange',
            slack: 'blue',
            core: 'gray',
            universal: 'gray',
          };
          return colorMap[name] || 'purple';
        }

        // Global helper to safely update element text
        function updateText(id, value) {
          const el = document.getElementById(id);
          if (el && el.textContent !== String(value)) {
            el.textContent = value;
          }
        }

        // Global helper to safely update element HTML
        function updateHtml(id, html) {
          const el = document.getElementById(id);
          if (el && el.innerHTML !== html) {
            el.innerHTML = html;
          }
        }

        function updateDynamicData(data) {

          // Update stats in header
          if (data.stats && data.stats.lifetime) {
            updateText('statToolCalls', data.stats.lifetime.tool_calls || '0');
            updateText('statSkills', data.stats.lifetime.skill_executions || '0');
            updateText('statSessions', data.stats.lifetime.sessions || '0');
          }

          // Update Today's Activity stats (Overview tab)
          if (data.todayStats) {
            updateText('todayToolCalls', data.todayStats.tool_calls || 0);
            updateText('todaySkillRuns', data.todayStats.skill_executions || 0);
          }

          // Update session stats
          if (data.session) {
            updateText('sessionToolCalls', data.session.tool_calls || 0);
            updateText('sessionSkillRuns', data.session.skill_executions || 0);
            updateText('sessionMemoryOps', data.session.memory_ops || 0);
          }

          // Update success rate
          if (data.toolSuccessRate !== undefined) {
            updateText('toolSuccessRate', data.toolSuccessRate + '%');
          }

          // Update current work (aggregated issues and MRs across workspaces)
          if (data.currentWork) {
            const totalIssues = data.currentWork.totalActiveIssues || 0;
            const totalMRs = data.currentWork.totalActiveMRs || 0;
            const allIssues = data.currentWork.allActiveIssues || [];
            const allMRs = data.currentWork.allActiveMRs || [];

            // Update issue card title and status
            const issueTitle = totalIssues > 0
              ? totalIssues + ' Active Issue' + (totalIssues > 1 ? 's' : '')
              : 'No Active Issues';
            const issueStatus = totalIssues > 0
              ? 'Across ' + (data.workspaceCount || 1) + ' workspace' + ((data.workspaceCount || 1) > 1 ? 's' : '')
              : 'Start work to track an issue';

            updateText('currentIssueKey', issueTitle);
            updateText('currentIssueStatus', issueStatus);

            // Update issue list
            const issuesList = document.getElementById('activeIssuesList');
            if (issuesList) {
              if (allIssues.length > 0) {
                const issuesHtml = allIssues.map(issue =>
                  '<div class="current-work-item" title="' + (issue.summary || issue.project) + '">' +
                  '<span class="work-item-key">' + issue.key + '</span>' +
                  '<span class="work-item-project">' + issue.project + '</span>' +
                  '</div>'
                ).join('');
                issuesList.innerHTML = issuesHtml;
                issuesList.style.display = 'flex';
              } else {
                issuesList.style.display = 'none';
              }
            }

            const issueActions = document.getElementById('currentIssueActions');
            if (issueActions) {
              const newIssueHtml = totalIssues > 0
                ? '<button class="btn btn-secondary btn-small" data-action="openJira">Open in Jira</button>'
                : '<button class="btn btn-primary btn-small" data-action="startWork">Start Work</button>';
              if (issueActions.innerHTML.trim() !== newIssueHtml.trim()) {
                issueActions.innerHTML = newIssueHtml;
                // Re-attach event listener
                const btn = issueActions.querySelector('[data-action]');
                if (btn) {
                  btn.addEventListener('click', () => {
                    const action = btn.getAttribute('data-action');
                    if (action === 'openJira') openJira();
                    else if (action === 'startWork') startWork();
                  });
                }
              }
            }

            // Update MR card title and status
            const mrTitle = totalMRs > 0
              ? totalMRs + ' Active MR' + (totalMRs > 1 ? 's' : '')
              : 'No Active MRs';
            const mrStatus = totalMRs > 0 ? 'Open' : 'Create an MR when ready';

            updateText('currentMRTitle', mrTitle);
            updateText('currentMRStatus', mrStatus);

            // Update MR list
            const mrsList = document.getElementById('activeMRsList');
            if (mrsList) {
              if (allMRs.length > 0) {
                const mrsHtml = allMRs.map(mr =>
                  '<div class="current-work-item" title="' + (mr.title || mr.project) + '">' +
                  '<span class="work-item-key">!' + mr.id + '</span>' +
                  '<span class="work-item-project">' + mr.project + '</span>' +
                  '</div>'
                ).join('');
                mrsList.innerHTML = mrsHtml;
                mrsList.style.display = 'flex';
              } else {
                mrsList.style.display = 'none';
              }
            }

            const mrActions = document.getElementById('currentMRActions');
            if (mrActions) {
              const newMRHtml = totalMRs > 0
                ? '<button class="btn btn-secondary btn-small" data-action="openMR">Open in GitLab</button>'
                : '';
              if (mrActions.innerHTML.trim() !== newMRHtml.trim()) {
                mrActions.innerHTML = newMRHtml;
                // Re-attach event listener
                const btn = mrActions.querySelector('[data-action]');
                if (btn) {
                  btn.addEventListener('click', () => openMR());
                }
              }
            }
          }

          // Update memory health stats
          if (data.memoryHealth) {
            updateText('memTotalSize', data.memoryHealth.totalSize || '0 B');
            updateText('memSessionLogs', data.memoryHealth.sessionLogs || '0');
            updateText('memPatterns', data.memoryHealth.patterns || '0');
            updateText('memLastSession', data.memoryHealth.lastSession || 'Unknown');
          }

          // Update workflow status (VPN, environments, etc.)
          if (data.workflowStatus) {
            // Update VPN banner visibility
            const vpnBanner = document.getElementById('vpnBanner');
            if (vpnBanner) {
              vpnBanner.style.display = data.workflowStatus.vpn?.connected ? 'none' : 'flex';
            }

            // Update environment status with icons
            const stageStatus = document.getElementById('stageStatus');
            const stageIcon = document.getElementById('stageIcon');
            if (stageStatus && data.workflowStatus.environment?.stageStatus) {
              const status = data.workflowStatus.environment.stageStatus;
              updateText('stageStatus', status);
              if (stageIcon) {
                stageIcon.textContent = status === 'healthy' ? '✅' : status === 'degraded' ? '⚠️' : '❓';
                stageIcon.className = 'card-icon ' + (status === 'healthy' ? 'green' : status === 'degraded' ? 'orange' : '');
              }
            }

            const prodStatus = document.getElementById('prodStatus');
            const prodIcon = document.getElementById('prodIcon');
            if (prodStatus && data.workflowStatus.environment?.prodStatus) {
              const status = data.workflowStatus.environment.prodStatus;
              updateText('prodStatus', status);
              if (prodIcon) {
                prodIcon.textContent = status === 'healthy' ? '✅' : status === 'degraded' ? '⚠️' : '❓';
                prodIcon.className = 'card-icon ' + (status === 'healthy' ? 'green' : status === 'degraded' ? 'orange' : '');
              }
            }
          }

          // Update cron status
          if (data.cronConfig) {
            // Get current job count to detect potential stale/empty data
            const currentJobCount = parseInt(document.getElementById('cronJobCount')?.textContent || '0', 10);
            const newJobCount = (data.cronConfig.jobs || []).length;

            // Skip update if we're receiving 0 jobs but previously had jobs
            // This prevents flicker from transient D-Bus failures
            if (newJobCount === 0 && currentJobCount > 0) {
              console.log('[Cron] Skipping dataUpdate with 0 jobs (had ' + currentJobCount + ' jobs) - likely stale data');
            } else {
              updateSchedulerUI(data.cronConfig.enabled);
              updateText('cronJobCount', newJobCount);
              const enabledJobs = (data.cronConfig.jobs || []).filter(j => j.enabled).length;
              updateText('cronEnabledCount', enabledJobs);
              // Update the tab badge (only if changed)
              const cronTabBadge = document.getElementById('cronTabBadge');
              if (cronTabBadge) {
                const newText = enabledJobs.toString();
                const newDisplay = data.cronConfig.enabled && enabledJobs > 0 ? '' : 'none';
                if (cronTabBadge.textContent !== newText) {
                  cronTabBadge.textContent = newText;
                }
                if (cronTabBadge.style.display !== newDisplay) {
                  cronTabBadge.style.display = newDisplay;
                }
              }
            }
          }

          // Update last updated timestamp (only update if visible to avoid layout thrashing)
          const lastUpdatedEl = document.getElementById('lastUpdatedTime');
          if (lastUpdatedEl && document.visibilityState === 'visible') {
            const newTime = 'Last updated: ' + new Date().toLocaleTimeString();
            if (lastUpdatedEl.textContent !== newTime) {
              lastUpdatedEl.textContent = newTime;
            }
          }
        }

        function renderSlackMessages(messages) {
          const container = document.getElementById('slackMessages');
          if (!messages || messages.length === 0) {
            container.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💬</div><div>No messages</div></div>';
            return;
          }

          container.innerHTML = messages.map(msg => {
            const channelId = msg.channel_id || '';
            const threadTs = msg.thread_ts || msg.ts || msg.timestamp || '';
            const hasThread = threadTs && channelId;

            return \`
            <div class="slack-message" data-channel="\${channelId}" data-thread="\${threadTs}">
              <div class="slack-avatar">\${(msg.user_name || '?').charAt(0).toUpperCase()}</div>
              <div class="slack-content">
                <div class="slack-header">
                  <span class="slack-user">\${msg.user_name || 'Unknown'}</span>
                  <span class="slack-channel">\${msg.channel_name ? '#' + msg.channel_name : ''}</span>
                  <span class="slack-time">\${msg.created_at ? new Date(msg.created_at * 1000).toLocaleTimeString() : ''}</span>
                  \${hasThread ? '<button class="btn btn-ghost btn-tiny slack-reply-btn" onclick="showQuickReply(\\'' + channelId + '\\', \\'' + threadTs + '\\', \\'' + (msg.channel_name || '') + '\\')">↩️ Reply</button>' : ''}
                </div>
                <div class="slack-text">\${msg.text || ''}</div>
                \${msg.response ? '<div class="slack-response">🤖 ' + msg.response + '</div>' : ''}
              </div>
            </div>
          \`;
          }).join('');
        }

        // Quick reply state
        let quickReplyChannel = '';
        let quickReplyThread = '';

        function showQuickReply(channelId, threadTs, channelName) {
          quickReplyChannel = channelId;
          quickReplyThread = threadTs;

          const modal = document.getElementById('quickReplyModal');
          const channelLabel = document.getElementById('quickReplyChannelLabel');
          const input = document.getElementById('quickReplyInput');

          if (modal && channelLabel && input) {
            channelLabel.textContent = channelName ? '#' + channelName : channelId;
            input.value = '';
            modal.style.display = 'flex';
            input.focus();
          }
        }

        function hideQuickReply() {
          const modal = document.getElementById('quickReplyModal');
          if (modal) {
            modal.style.display = 'none';
          }
          quickReplyChannel = '';
          quickReplyThread = '';
        }

        function sendQuickReply() {
          const input = document.getElementById('quickReplyInput');
          const text = input?.value?.trim();

          if (text && quickReplyChannel && quickReplyThread) {
            vscode.postMessage({
              command: 'replyToSlackThread',
              channel: quickReplyChannel,
              text: text,
              threadTs: quickReplyThread
            });
            hideQuickReply();
          }
        }

        // Command Builder state
        let commandBuilderCommands = [];
        let selectedCommand = null;

        function showCommandBuilder() {
          const modal = document.getElementById('commandBuilderModal');
          if (modal) {
            modal.style.display = 'flex';
            // Load commands if not already loaded
            if (commandBuilderCommands.length === 0) {
              vscode.postMessage({ command: 'loadSlackCommands' });
            }
          }
        }

        function hideCommandBuilder() {
          const modal = document.getElementById('commandBuilderModal');
          if (modal) {
            modal.style.display = 'none';
          }
          selectedCommand = null;
        }

        function populateCommandSelect(commands) {
          commandBuilderCommands = commands;
          const select = document.getElementById('commandBuilderSelect');
          if (!select) return;

          // Group by type
          const grouped = { builtin: [], skill: [], tool: [] };
          commands.forEach(cmd => {
            const type = cmd.type || 'skill';
            if (grouped[type]) grouped[type].push(cmd);
          });

          let html = '<option value="">Choose a command...</option>';

          if (grouped.builtin.length > 0) {
            html += '<optgroup label="Built-in Commands">';
            grouped.builtin.forEach(cmd => {
              html += '<option value="' + cmd.name + '">' + cmd.name + ' - ' + (cmd.description || '').substring(0, 40) + '</option>';
            });
            html += '</optgroup>';
          }

          if (grouped.skill.length > 0) {
            html += '<optgroup label="Skills">';
            grouped.skill.forEach(cmd => {
              html += '<option value="' + cmd.name + '">' + cmd.name + ' - ' + (cmd.description || '').substring(0, 40) + '</option>';
            });
            html += '</optgroup>';
          }

          if (grouped.tool.length > 0) {
            html += '<optgroup label="Tools">';
            grouped.tool.slice(0, 20).forEach(cmd => {
              html += '<option value="' + cmd.name + '">' + cmd.name + ' - ' + (cmd.description || '').substring(0, 40) + '</option>';
            });
            if (grouped.tool.length > 20) {
              html += '<option disabled>... and ' + (grouped.tool.length - 20) + ' more</option>';
            }
            html += '</optgroup>';
          }

          select.innerHTML = html;
        }

        function onCommandSelect() {
          const select = document.getElementById('commandBuilderSelect');
          const cmdName = select?.value;

          if (!cmdName) {
            selectedCommand = null;
            document.getElementById('commandBuilderDescription').style.display = 'none';
            document.getElementById('commandBuilderParams').style.display = 'none';
            document.getElementById('commandBuilderPreview').style.display = 'none';
            document.getElementById('commandBuilderSendBtn').disabled = true;
            return;
          }

          selectedCommand = commandBuilderCommands.find(c => c.name === cmdName);
          if (!selectedCommand) return;

          // Show description
          const descEl = document.getElementById('commandBuilderDescription');
          descEl.innerHTML = '<strong>' + selectedCommand.name + '</strong><br>' +
            (selectedCommand.description || 'No description') +
            (selectedCommand.contextual ? '<br><span style="color: var(--warning);">🧵 Supports thread context</span>' : '');
          descEl.style.display = 'block';

          // Show parameters
          const paramsEl = document.getElementById('commandBuilderParams');
          const inputsEl = document.getElementById('commandBuilderParamInputs');

          if (selectedCommand.inputs && selectedCommand.inputs.length > 0) {
            inputsEl.innerHTML = selectedCommand.inputs.map(inp => {
              const required = inp.required ? ' <span style="color: var(--error);">*</span>' : '';
              return '<div style="margin-bottom: 12px;">' +
                '<label style="display: block; font-size: 0.8rem; margin-bottom: 4px;">' + inp.name + required + '</label>' +
                '<input type="text" class="cmd-param-input" data-param="' + inp.name + '" placeholder="' + (inp.description || inp.name) + '" ' +
                'style="width: 100%; padding: 8px 10px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-secondary); color: var(--text-primary); font-size: 0.85rem;" ' +
                'oninput="updateCommandPreview()">' +
                '</div>';
            }).join('');
            paramsEl.style.display = 'block';
          } else {
            inputsEl.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem;">No parameters required</div>';
            paramsEl.style.display = 'block';
          }

          // Show preview
          document.getElementById('commandBuilderPreview').style.display = 'block';
          document.getElementById('commandBuilderSendBtn').disabled = false;
          updateCommandPreview();
        }

        function updateCommandPreview() {
          if (!selectedCommand) return;

          let preview = '@me ' + selectedCommand.name;
          const inputs = document.querySelectorAll('.cmd-param-input');
          inputs.forEach(input => {
            const value = input.value.trim();
            if (value) {
              preview += ' --' + input.dataset.param + '="' + value + '"';
            }
          });

          document.getElementById('commandBuilderPreviewText').textContent = preview;
        }

        function sendBuiltCommand() {
          if (!selectedCommand) return;

          const args = {};
          const inputs = document.querySelectorAll('.cmd-param-input');
          inputs.forEach(input => {
            const value = input.value.trim();
            if (value) {
              args[input.dataset.param] = value;
            }
          });

          vscode.postMessage({
            command: 'sendSlackCommand',
            commandName: selectedCommand.name,
            args: args
          });

          hideCommandBuilder();
        }

        // Slack Config UI functions
        function toggleSlackDebugMode(enabled) {
          vscode.postMessage({ command: 'setSlackDebugMode', enabled: enabled });
        }

        function loadSlackConfig() {
          vscode.postMessage({ command: 'loadSlackConfig' });
        }

        function updateSlackConfigUI(config) {
          // Update watched channels count
          const watchedCount = document.getElementById('slackConfigWatchedCount');
          if (watchedCount) {
            const count = (config.watched_channels || []).length;
            watchedCount.textContent = count;
          }

          // Update alert channels count
          const alertCount = document.getElementById('slackConfigAlertCount');
          if (alertCount) {
            const count = Object.keys(config.alert_channels || {}).length;
            alertCount.textContent = count;
          }

          // Update safe users count
          const safeCount = document.getElementById('slackConfigSafeCount');
          if (safeCount && config.user_classification) {
            const safeList = config.user_classification.safe_list || {};
            const count = (safeList.user_ids || []).length + (safeList.user_names || []).length;
            safeCount.textContent = count;
          }

          // Update concerned users count
          const concernedCount = document.getElementById('slackConfigConcernedCount');
          if (concernedCount && config.user_classification) {
            const concernedList = config.user_classification.concerned_list || {};
            const count = (concernedList.user_ids || []).length + (concernedList.user_names || []).length;
            concernedCount.textContent = count;
          }

          // Update debug mode toggle
          const debugToggle = document.getElementById('slackDebugModeToggle');
          if (debugToggle) {
            debugToggle.checked = config.debug_mode || false;
          }
        }

        function renderSlackSearchResults(data) {
          const container = document.getElementById('slackSearchResults');
          const remaining = document.getElementById('slackSearchRemaining');

          if (remaining && data.remaining !== undefined) {
            remaining.textContent = data.remaining + ' searches remaining today';
          }

          if (data.rateLimited) {
            container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-icon">⏳</div><div>Rate limited</div><div style="font-size: 0.75rem; margin-top: 4px; color: var(--text-muted);">' + (data.error || 'Please wait before searching again') + '</div></div>';
            return;
          }

          if (data.error) {
            container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-icon">❌</div><div>Search failed</div><div style="font-size: 0.75rem; margin-top: 4px; color: var(--text-muted);">' + data.error + '</div></div>';
            return;
          }

          if (!data.results || data.results.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-icon">🔍</div><div>No results found</div></div>';
            return;
          }

          container.innerHTML = data.results.map(msg => \`
            <div class="slack-search-result" onclick="window.open('\${msg.permalink}', '_blank')">
              <div class="slack-avatar">\${(msg.username || '?').charAt(0).toUpperCase()}</div>
              <div style="flex: 1; min-width: 0;">
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span class="slack-user">\${msg.username || 'Unknown'}</span>
                  <span class="slack-search-channel">#\${msg.channel_name || 'unknown'}</span>
                </div>
                <div class="slack-search-text">\${msg.text || ''}</div>
              </div>
            </div>
          \`).join('');
        }

        function renderSlackPending(pending) {
          const container = document.getElementById('slackPendingList');
          const badge = document.getElementById('slackPendingBadge');

          if (badge) {
            if (pending.length > 0) {
              badge.textContent = pending.length;
              badge.style.display = 'inline-block';
            } else {
              badge.style.display = 'none';
            }
          }

          if (!pending || pending.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div class="empty-state-icon">✅</div><div>No pending approvals</div></div>';
            return;
          }

          container.innerHTML = pending.map(msg => \`
            <div class="slack-pending-item">
              <div class="slack-avatar">\${(msg.user_name || '?').charAt(0).toUpperCase()}</div>
              <div class="slack-pending-content">
                <div class="slack-header">
                  <span class="slack-user">\${msg.user_name || 'Unknown'}</span>
                  <span class="slack-time">\${msg.created_at ? new Date(msg.created_at * 1000).toLocaleTimeString() : ''}</span>
                </div>
                <div class="slack-text">\${msg.text || ''}</div>
                <div class="slack-response" style="margin-top: 8px;">🤖 \${msg.response || 'No response generated'}</div>
                <div class="slack-pending-meta">\${msg.channel_name || msg.channel_id} • \${msg.classification || 'unknown'}</div>
              </div>
              <div class="slack-pending-actions">
                <button class="btn btn-primary btn-small" onclick="approveSlackMessage('\${msg.id}')">✅</button>
                <button class="btn btn-ghost btn-small" onclick="rejectSlackMessage('\${msg.id}')">❌</button>
              </div>
            </div>
          \`).join('');
        }

        function approveSlackMessage(messageId) {
          vscode.postMessage({ command: 'approveSlackMessage', messageId: messageId });
        }

        function rejectSlackMessage(messageId) {
          vscode.postMessage({ command: 'rejectSlackMessage', messageId: messageId });
        }

        function updateSlackCacheStats(channelStats, userStats) {
          // Channel stats
          const channelTotal = document.getElementById('slackCacheChannelTotal');
          const channelMember = document.getElementById('slackCacheChannelMember');
          const channelAge = document.getElementById('slackCacheChannelAge');

          if (channelTotal) channelTotal.textContent = channelStats.total_channels || 0;
          if (channelMember) channelMember.textContent = channelStats.member_channels || 0;
          if (channelAge) {
            const age = channelStats.cache_age_seconds;
            if (age === null || age === undefined) {
              channelAge.textContent = 'Never';
            } else if (age < 60) {
              channelAge.textContent = Math.round(age) + 's ago';
            } else if (age < 3600) {
              channelAge.textContent = Math.round(age / 60) + 'm ago';
            } else {
              channelAge.textContent = Math.round(age / 3600) + 'h ago';
            }
          }

          // User stats
          const userTotal = document.getElementById('slackCacheUserTotal');
          const userAvatar = document.getElementById('slackCacheUserAvatar');
          const userEmail = document.getElementById('slackCacheUserEmail');
          const userAge = document.getElementById('slackCacheUserAge');

          if (userTotal) userTotal.textContent = userStats.total_users || 0;
          if (userAvatar) userAvatar.textContent = userStats.with_avatar || 0;
          if (userEmail) userEmail.textContent = userStats.with_email || 0;
          if (userAge) {
            const age = userStats.cache_age_seconds;
            if (age === null || age === undefined) {
              userAge.textContent = 'Never';
            } else if (age < 60) {
              userAge.textContent = Math.round(age) + 's ago';
            } else if (age < 3600) {
              userAge.textContent = Math.round(age / 60) + 'm ago';
            } else {
              userAge.textContent = Math.round(age / 3600) + 'h ago';
            }
          }
        }

        function renderSlackChannelBrowser(channels, count) {
          const container = document.getElementById('slackChannelBrowser');
          const countEl = document.getElementById('slackChannelCount');

          if (countEl) countEl.textContent = count + ' channels';

          if (!channels || channels.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div>No channels found</div></div>';
            return;
          }

          container.innerHTML = channels.map(ch => \`
            <div class="slack-browser-item" onclick="copyToClipboard('\${ch.channel_id}')">
              <div class="slack-browser-avatar">#</div>
              <div class="slack-browser-info">
                <div class="slack-browser-name">#\${ch.name || 'unknown'}</div>
                <div class="slack-browser-meta">\${ch.purpose ? ch.purpose.substring(0, 50) + (ch.purpose.length > 50 ? '...' : '') : ''}</div>
              </div>
              \${ch.is_member ? '<span class="slack-browser-badge member">Member</span>' : ''}
              <span class="slack-browser-id">\${ch.channel_id}</span>
            </div>
          \`).join('');
        }

        function renderSlackUserBrowser(users, count) {
          const container = document.getElementById('slackUserBrowser');
          const countEl = document.getElementById('slackUserCount');

          if (countEl) countEl.textContent = count + ' users';

          if (!users || users.length === 0) {
            container.innerHTML = '<div class="empty-state" style="padding: 20px;"><div>No users found</div></div>';
            return;
          }

          container.innerHTML = users.map(u => \`
            <div class="slack-browser-item" onclick="copyToClipboard('\${u.user_id}')">
              <div class="slack-browser-avatar">
                \${u.avatar_url ? '<img src="' + u.avatar_url + '" alt="">' : (u.display_name || u.user_name || '?').charAt(0).toUpperCase()}
              </div>
              <div class="slack-browser-info">
                <div class="slack-browser-name">\${u.display_name || u.user_name || 'Unknown'}</div>
                <div class="slack-browser-meta">\${u.real_name || ''}\${u.email ? ' • ' + u.email : ''}</div>
              </div>
              <span class="slack-browser-id">\${u.user_id}</span>
            </div>
          \`).join('');
        }

        function copyToClipboard(text) {
          navigator.clipboard.writeText(text).then(() => {
            // Could show a toast here
            console.log('Copied to clipboard:', text);
          });
        }

        function updateSchedulerUI(enabled) {
          console.log('[CommandCenter] updateSchedulerUI called with enabled:', enabled);
          const card = document.getElementById('cronEnabledCard');
          const icon = document.getElementById('cronEnabledIcon');
          const value = document.getElementById('cronEnabled');

          if (!card || !icon || !value) {
            console.error('[CommandCenter] updateSchedulerUI: Missing DOM elements', { card: !!card, icon: !!icon, value: !!value });
            return;
          }

          const btn = card.querySelector('button');

          if (enabled) {
            card.classList.add('green');
            card.title = 'Click to disable scheduler';
            icon.textContent = '✅';
            value.textContent = 'Active';
            if (btn) {
              btn.className = 'btn btn-secondary btn-small';
              btn.innerHTML = '⏸️ Disable';
              btn.style.marginTop = '8px';
            }
          } else {
            card.classList.remove('green');
            card.title = 'Click to enable scheduler';
            icon.textContent = '⏸️';
            value.textContent = 'Disabled';
            if (btn) {
              btn.className = 'btn btn-primary btn-small';
              btn.innerHTML = '▶️ Enable';
              btn.style.marginTop = '8px';
            }
          }
          console.log('[CommandCenter] updateSchedulerUI completed');
        }

        // Cache for detecting actual changes to avoid unnecessary DOM updates
        let _lastCronHistoryHash = '';

        function updateCronHistory(history, totalHistory, currentLimit) {
          console.log('[CommandCenter] updateCronHistory called with', history?.length || 0, 'entries, total:', totalHistory, 'limit:', currentLimit);
          const container = document.querySelector('.cron-history-list');
          if (!container) {
            console.error('[CommandCenter] updateCronHistory: .cron-history-list not found');
            return;
          }

          // Create a hash to detect changes (avoids unnecessary DOM thrashing)
          const newHash = JSON.stringify({ history: history || [], totalHistory, currentLimit });
          if (newHash === _lastCronHistoryHash) {
            console.log('[CommandCenter] updateCronHistory: No changes detected, skipping DOM update');
            return;
          }
          _lastCronHistoryHash = newHash;

          // Build the new HTML content
          let newHtml;
          if (!history || history.length === 0) {
            newHtml = \`
              <div class="empty-state">
                <div class="empty-state-icon">📜</div>
                <div>No execution history</div>
                <div style="font-size: 0.8rem; margin-top: 8px;">Jobs will appear here after they run</div>
              </div>
            \`;
          } else {
            // Helper to format duration with color coding
            const formatDuration = (ms) => {
              if (!ms) return '';
              const seconds = Math.floor(ms / 1000);
              const minutes = Math.floor(seconds / 60);
              const isTimeout = ms >= 600000; // 10 minutes
              const isSlow = ms >= 300000; // 5 minutes
              const durationClass = isTimeout ? 'timeout' : isSlow ? 'slow' : 'fast';
              const durationText = minutes >= 1 ? minutes + 'm ' + (seconds % 60) + 's' : seconds + 's';
              const icon = isTimeout ? '⏰' : '⏱️';
              return '<span class="cron-history-duration ' + durationClass + '">' + icon + ' ' + durationText + '</span>';
            };

            // Helper to categorize error type
            const categorizeError = (error) => {
              if (!error) return null;
              let errorType = 'Error';
              let errorIcon = '❌';
              if (error.includes('timed out') || error.includes('timeout')) {
                errorType = 'Timeout';
                errorIcon = '⏰';
              } else if (error.includes('API Error') || error.includes('oauth2') || error.includes('getaddrinfo')) {
                errorType = 'Network/API Error';
                errorIcon = '🌐';
              } else if (error.includes('exited with code')) {
                errorType = 'Process Error';
                errorIcon = '💥';
              } else if (error.includes('permission') || error.includes('unauthorized')) {
                errorType = 'Auth Error';
                errorIcon = '🔒';
              }
              return { type: errorType, icon: errorIcon, message: error };
            };

            newHtml = history.map(exec => {
              const errorInfo = categorizeError(exec.error);
              return \`
              <div class="cron-history-item \${exec.success ? 'success' : 'failed'}">
                <div class="cron-history-status">\${exec.success ? '✅' : '❌'}</div>
                <div class="cron-history-info">
                  <div class="cron-history-name">\${exec.job_name}</div>
                  \${exec.session_name ? \`<div class="cron-history-session">💬 \${exec.session_name}</div>\` : ''}
                  <div class="cron-history-details">
                    <span>⚡ \${exec.skill}</span>
                    \${formatDuration(exec.duration_ms)}
                    <span>🕐 \${new Date(exec.timestamp).toLocaleString()}</span>
                  </div>
                  \${errorInfo ? \`
                    <div class="cron-history-error">
                      <div class="cron-history-error-type">\${errorInfo.icon} \${errorInfo.type}</div>
                      <div class="cron-history-error-message">\${errorInfo.message}</div>
                    </div>
                  \` : ''}
                  \${exec.output_preview ? \`<div class="cron-history-output">\${exec.output_preview}</div>\` : ''}
                </div>
              </div>
            \`}).join('');
          }

          // Update the DOM
          container.innerHTML = newHtml;

          // Update or create the "Load More" button
          let loadMoreContainer = document.querySelector('.cron-history-load-more');
          const remaining = (totalHistory || 0) - (currentLimit || history?.length || 0);

          if (remaining > 0) {
            if (!loadMoreContainer) {
              loadMoreContainer = document.createElement('div');
              loadMoreContainer.className = 'cron-history-load-more';
              container.parentElement.appendChild(loadMoreContainer);
            }
            loadMoreContainer.innerHTML = \`
              <button class="btn btn-ghost" data-action="loadMoreCronHistory" data-current="\${currentLimit || history?.length || 10}">
                📜 Load 10 more (\${remaining} remaining)
              </button>
            \`;
          } else if (loadMoreContainer) {
            loadMoreContainer.remove();
          }

          console.log('[CommandCenter] updateCronHistory completed');
        }

        // Cache for detecting actual changes to avoid unnecessary DOM updates
        let _lastCronJobsHash = '';

        function updateCronJobs(jobs) {
          // Check hash FIRST before any DOM operations or HTML generation
          const newHash = JSON.stringify(jobs || []);
          if (newHash === _lastCronJobsHash) {
            // No changes - skip everything
            return;
          }
          _lastCronJobsHash = newHash;

          console.log('[CommandCenter] updateCronJobs: Data changed, updating DOM');
          const container = document.querySelector('.cron-jobs-list');
          if (!container) {
            console.error('[CommandCenter] updateCronJobs: .cron-jobs-list not found');
            return;
          }

          // Build the new HTML content (only if data changed)
          let newHtml;
          if (!jobs || jobs.length === 0) {
            newHtml = \`
              <div class="empty-state">
                <div class="empty-state-icon">🕐</div>
                <div>No cron jobs configured</div>
                <div style="font-size: 0.8rem; margin-top: 8px;">Add jobs to config.json schedules section</div>
                <button class="btn btn-primary btn-small" style="margin-top: 12px;" data-action="openConfigFile">Open Config</button>
              </div>
            \`;
          } else {
            newHtml = jobs.map(job => \`
              <div class="cron-job-item \${job.enabled ? '' : 'disabled'}" data-job="\${job.name}">
                <div class="cron-job-toggle">
                  <label class="toggle-switch">
                    <input type="checkbox" \${job.enabled ? 'checked' : ''}>
                    <span class="toggle-slider"></span>
                  </label>
                </div>
                <div class="cron-job-info">
                  <div class="cron-job-name">\${job.name}</div>
                  <div class="cron-job-desc">\${job.description || 'Runs skill: ' + job.skill}</div>
                  <div class="cron-job-schedule">
                    \${job.cron ? \`<span class="cron-badge cron">⏰ \${job.cron}</span>\` : ''}
                    \${job.trigger === 'poll' ? \`<span class="cron-badge poll">🔄 Poll: \${job.poll_interval || '5m'}</span>\` : ''}
                    <span class="cron-badge skill">⚡ \${job.skill}</span>
                    \${job.persona ? \`<span class="cron-badge persona">👤 \${job.persona}</span>\` : ''}
                    \${job.notify ? \`<span class="cron-badge notify">🔔 \${job.notify.join(', ')}</span>\` : ''}
                  </div>
                </div>
                <div class="cron-job-actions">
                  <button class="btn btn-ghost btn-small" data-run-job="\${job.name}" title="Run now">▶️</button>
                </div>
              </div>
            \`).join('');
          }

          // Update the DOM
          container.innerHTML = newHtml;

          // Re-attach event listeners for toggle switches and run buttons
          if (jobs && jobs.length > 0) {
            container.querySelectorAll('.cron-job-item').forEach(item => {
              const jobName = item.getAttribute('data-job');
              const toggle = item.querySelector('input[type="checkbox"]');
              const runBtn = item.querySelector('[data-run-job]');

              if (toggle) {
                toggle.addEventListener('change', (e) => {
                  vscode.postMessage({ command: 'toggleCronJob', jobName: jobName, enabled: e.target.checked });
                });
              }
              if (runBtn) {
                runBtn.addEventListener('click', () => {
                  vscode.postMessage({ command: 'runCronJobNow', jobName: jobName });
                });
              }
            });
          }
          console.log('[CommandCenter] updateCronJobs completed');
        }

        function formatUptime(seconds) {
          if (!seconds || seconds < 0) return '--';
          if (seconds < 60) return Math.floor(seconds) + 's';
          if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
          if (seconds < 86400) return (seconds / 3600).toFixed(1) + 'h';
          return (seconds / 86400).toFixed(1) + 'd';
        }

        // Update services tab badge based on current DOM state
        function updateServicesTabBadge() {
          const badge = document.getElementById('servicesTabBadge');
          if (!badge) return;

          // Count online services from DOM
          const serviceCards = ['slackServiceCard', 'cronServiceCard', 'meetServiceCard', 'sprintServiceCard', 'videoServiceCard'];
          let servicesOnline = 0;
          serviceCards.forEach(id => {
            const card = document.getElementById(id);
            if (card && !card.classList.contains('service-offline')) {
              servicesOnline++;
            }
          });

          // Check MCP
          const mcpCard = document.getElementById('mcpServiceCard');
          const mcpOnline = mcpCard && !mcpCard.classList.contains('service-offline') ? 1 : 0;

          // Check Ollama instances from status dots
          const ollamaInstances = ['npu', 'igpu', 'nvidia', 'cpu'];
          let ollamaOnline = 0;
          ollamaInstances.forEach(inst => {
            const statusEl = document.getElementById(inst + 'Status');
            if (statusEl && statusEl.innerHTML.includes('online')) {
              ollamaOnline++;
            }
          });

          const totalServices = serviceCards.length + 1 + ollamaInstances.length; // 5 + 1 + 4 = 10
          const totalOnline = servicesOnline + mcpOnline + ollamaOnline;
          const offlineCount = totalServices - totalOnline;

          // Update badge: green = all online, orange = 1-2 offline, red = 3+ offline
          badge.className = 'tab-badge tab-badge-status ' + (offlineCount === 0 ? 'status-green' : offlineCount < 3 ? 'status-yellow' : 'status-red');
          badge.textContent = offlineCount === 0 ? '●' : offlineCount < 3 ? '◐' : '○';
          badge.title = totalOnline + '/' + totalServices + ' online';
        }

        // Cache for detecting service status changes to avoid unnecessary DOM updates
        let _lastServiceStatusHash = '';

        // Helper to update innerHTML only if content changed
        function updateInnerHTMLIfChanged(element, newContent) {
          if (element && element.innerHTML !== newContent) {
            element.innerHTML = newContent;
            return true;
          }
          return false;
        }

        function updateServiceStatus(message) {
          // Create a hash to detect changes (avoids unnecessary DOM thrashing)
          const newHash = JSON.stringify(message);
          if (newHash === _lastServiceStatusHash) {
            // No changes, skip DOM updates entirely
            return;
          }
          _lastServiceStatusHash = newHash;

          // Slack Agent
          const slackService = message.services.find(s => s.name === 'Slack Agent');
          if (slackService) {
            const slackStatus = document.getElementById('slackStatus');
            const slackDetails = document.getElementById('slackDetails');
            const slackCard = document.getElementById('slackServiceCard');

            // Update Slack Tab stats
            const slackAgentStatus = document.getElementById('slackAgentStatus');
            const slackStatusCard = document.getElementById('slackStatusCard');
            const slackUptime = document.getElementById('slackUptime');
            const slackProcessed = document.getElementById('slackProcessed');
            const slackPending = document.getElementById('slackPending');
            const slackPolls = document.getElementById('slackPolls');
            const slackResponded = document.getElementById('slackResponded');
            const slackSeen = document.getElementById('slackSeen');
            const slackErrors = document.getElementById('slackErrors');
            const slackErrorsCard = document.getElementById('slackErrorsCard');

            if (slackService.running) {
              updateInnerHTMLIfChanged(slackStatus, '<span class="status-dot online"></span> Online');
              slackCard?.classList.remove('service-offline');
              const status = slackService.status || {};
              updateInnerHTMLIfChanged(slackDetails, \`
                <div class="service-row"><span>Uptime</span><span>\${formatUptime(status.uptime)}</span></div>
                <div class="service-row"><span>Polls</span><span>\${status.polls || 0}</span></div>
                <div class="service-row"><span>Processed</span><span>\${status.messages_processed || 0}</span></div>
                <div class="service-row"><span>Pending</span><span>\${status.pending_approvals || 0}</span></div>
              \`);

              // Update Slack Tab - Row 1
              if (slackAgentStatus) slackAgentStatus.textContent = 'Online';
              if (slackStatusCard) slackStatusCard.classList.add('green');
              if (slackUptime) slackUptime.textContent = formatUptime(status.uptime);
              if (slackProcessed) slackProcessed.textContent = status.messages_processed || 0;
              if (slackPending) slackPending.textContent = status.pending_approvals || 0;

              // Update Slack Tab - Row 2
              if (slackPolls) slackPolls.textContent = status.polls || 0;
              if (slackResponded) slackResponded.textContent = status.messages_responded || 0;
              if (slackSeen) slackSeen.textContent = status.messages_seen || 0;
              if (slackErrors) slackErrors.textContent = status.errors || 0;
              // Highlight errors card if there are errors
              if (slackErrorsCard) {
                if ((status.errors || 0) > 0) {
                  slackErrorsCard.classList.add('red');
                } else {
                  slackErrorsCard.classList.remove('red');
                }
              }
            } else {
              updateInnerHTMLIfChanged(slackStatus, '<span class="status-dot offline"></span> Offline');
              slackCard?.classList.add('service-offline');
              updateInnerHTMLIfChanged(slackDetails, '<div class="service-row"><span>Status</span><span>Not running</span></div>');

              // Update Slack Tab - Row 1
              if (slackAgentStatus) slackAgentStatus.textContent = 'Offline';
              if (slackStatusCard) slackStatusCard.classList.remove('green');
              if (slackUptime) slackUptime.textContent = '--';
              if (slackProcessed) slackProcessed.textContent = '0';
              if (slackPending) slackPending.textContent = '0';

              // Update Slack Tab - Row 2
              if (slackPolls) slackPolls.textContent = '0';
              if (slackResponded) slackResponded.textContent = '0';
              if (slackSeen) slackSeen.textContent = '0';
              if (slackErrors) slackErrors.textContent = '0';
              if (slackErrorsCard) slackErrorsCard.classList.remove('red');
            }
          }

          // Cron Scheduler
          const cronService = message.services.find(s => s.name === 'Cron Scheduler');
          if (cronService) {
            const cronStatus = document.getElementById('cronStatus');
            const cronDetails = document.getElementById('cronDetails');
            const cronCard = document.getElementById('cronServiceCard');

            if (cronService.running) {
              updateInnerHTMLIfChanged(cronStatus, '<span class="status-dot online"></span> Online');
              cronCard?.classList.remove('service-offline');
              const status = cronService.status || {};
              updateInnerHTMLIfChanged(cronDetails, \`
                <div class="service-row"><span>Uptime</span><span>\${formatUptime(status.uptime)}</span></div>
                <div class="service-row"><span>Jobs</span><span>\${status.job_count || 0}</span></div>
                <div class="service-row"><span>Executed</span><span>\${status.jobs_executed || 0}</span></div>
                <div class="service-row"><span>Mode</span><span>\${status.execution_mode || 'direct'}</span></div>
              \`);
            } else {
              updateInnerHTMLIfChanged(cronStatus, '<span class="status-dot offline"></span> Offline');
              cronCard?.classList.add('service-offline');
              updateInnerHTMLIfChanged(cronDetails, '<div class="service-row"><span>Status</span><span>Not running</span></div>');
            }
          }

          // Meet Bot
          const meetService = message.services.find(s => s.name === 'Meet Bot');
          if (meetService) {
            const meetStatus = document.getElementById('meetStatus');
            const meetDetails = document.getElementById('meetDetails');
            const meetCard = document.getElementById('meetServiceCard');

            if (meetService.running) {
              updateInnerHTMLIfChanged(meetStatus, '<span class="status-dot online"></span> Online');
              meetCard?.classList.remove('service-offline');
              const status = meetService.status || {};
              updateInnerHTMLIfChanged(meetDetails, \`
                <div class="service-row"><span>Uptime</span><span>\${formatUptime(status.uptime)}</span></div>
                <div class="service-row"><span>Current</span><span>\${status.current_meeting || 'None'}</span></div>
                <div class="service-row"><span>Upcoming</span><span>\${status.upcoming_count || 0}</span></div>
                <div class="service-row"><span>Completed</span><span>\${status.completed_today || 0}</span></div>
              \`);
            } else {
              updateInnerHTMLIfChanged(meetStatus, '<span class="status-dot offline"></span> Offline');
              meetCard?.classList.add('service-offline');
              updateInnerHTMLIfChanged(meetDetails, '<div class="service-row"><span>Status</span><span>Not running</span></div>');
            }
          }

          // Sprint Bot
          const sprintService = message.services.find(s => s.name === 'Sprint Bot');
          if (sprintService) {
            const sprintStatus = document.getElementById('sprintStatus');
            const sprintDetails = document.getElementById('sprintDetails');
            const sprintCard = document.getElementById('sprintServiceCard');

            if (sprintService.running) {
              updateInnerHTMLIfChanged(sprintStatus, '<span class="status-dot online"></span> Online');
              sprintCard?.classList.remove('service-offline');
              const status = sprintService.status || {};
              const isActive = status.is_active || status.manually_started || (status.automatic_mode && status.within_working_hours);
              const modeText = status.manually_started ? 'Manual' : (status.automatic_mode ? 'Auto' : 'Paused');
              updateInnerHTMLIfChanged(sprintDetails, \`
                <div class="service-row"><span>Mode</span><span>\${modeText}</span></div>
                <div class="service-row"><span>Active</span><span>\${isActive ? 'Yes' : 'No'}</span></div>
                <div class="service-row"><span>Issues</span><span>\${status.total_issues || 0}</span></div>
                <div class="service-row"><span>Processed</span><span>\${status.issues_processed || 0}</span></div>
              \`);
            } else {
              updateInnerHTMLIfChanged(sprintStatus, '<span class="status-dot offline"></span> Offline');
              sprintCard?.classList.add('service-offline');
              updateInnerHTMLIfChanged(sprintDetails, '<div class="service-row"><span>Status</span><span>Not running</span></div>');
            }
          }

          // Video Bot
          const videoService = message.services.find(s => s.name === 'Video Bot');
          if (videoService) {
            const videoStatus = document.getElementById('videoStatus');
            const videoDetails = document.getElementById('videoDetails');
            const videoCard = document.getElementById('videoServiceCard');

            if (videoService.running) {
              updateInnerHTMLIfChanged(videoStatus, '<span class="status-dot online"></span> Online');
              videoCard?.classList.remove('service-offline');
              const status = videoService.status || {};
              updateInnerHTMLIfChanged(videoDetails, \`
                <div class="service-row"><span>Uptime</span><span>\${formatUptime(status.uptime)}</span></div>
                <div class="service-row"><span>Status</span><span>\${status.status || 'idle'}</span></div>
                <div class="service-row"><span>Device</span><span>\${status.device || 'None'}</span></div>
                <div class="service-row"><span>Frames</span><span>\${status.frames_rendered || 0}</span></div>
              \`);
            } else {
              updateInnerHTMLIfChanged(videoStatus, '<span class="status-dot offline"></span> Offline');
              videoCard?.classList.add('service-offline');
              updateInnerHTMLIfChanged(videoDetails, '<div class="service-row"><span>Status</span><span>Not running</span></div>');
            }
          }

          // MCP Server
          const mcpStatus = document.getElementById('mcpStatus');
          const mcpDetails = document.getElementById('mcpDetails');
          const mcpCard = document.getElementById('mcpServiceCard');

          if (message.mcp && message.mcp.running) {
            updateInnerHTMLIfChanged(mcpStatus, '<span class="status-dot online"></span> Running');
            mcpCard?.classList.remove('service-offline');
            updateInnerHTMLIfChanged(mcpDetails, '<div class="service-row"><span>PID</span><span>' + (message.mcp.pid || '-') + '</span></div>');
          } else {
            updateInnerHTMLIfChanged(mcpStatus, '<span class="status-dot offline"></span> Stopped');
            mcpCard?.classList.add('service-offline');
            updateInnerHTMLIfChanged(mcpDetails, '<div class="service-row"><span>Status</span><span>Not running</span></div>');
          }

          // Update services tab badge based on current status
          updateServicesTabBadge();
        }

        // Services are auto-refreshed via unified background sync
        // No manual refresh needed on load

        // ============================================
        // Event Listeners (CSP-compliant)
        // ============================================

        // Tab switching
        console.log('[DEBUG] Setting up tab event listeners...');
        const tabs = document.querySelectorAll('.tab[data-tab]');
        console.log('[DEBUG] Found', tabs.length, 'tabs');
        tabs.forEach((tab, index) => {
          const tabId = tab.getAttribute('data-tab');
          console.log('[DEBUG] Adding listener to tab', index, ':', tabId);
          tab.addEventListener('click', (e) => {
            console.log('[DEBUG] Tab clicked:', tabId, 'event:', e);
            if (tabId) switchTab(tabId);
          });
        });
        console.log('[DEBUG] Tab listeners setup complete');

        // Quick action buttons - use event delegation for dynamically created buttons
        document.body.addEventListener('click', (e) => {
          const btn = e.target.closest('[data-action]');
          if (!btn) return;

          const action = btn.getAttribute('data-action');
          // Debug: console.log('[CommandCenter-Webview] Button clicked, action:', action);
          switch(action) {
            case 'refresh': refresh(); break;
            case 'openJira': openJira(); break;
            case 'openMR': openMR(); break;
            case 'runSkill': runSkill(); break;
            case 'switchAgent': switchAgent(); break;
            case 'startWork': startWork(); break;
            case 'coffee': coffee(); break;
            case 'beer': beer(); break;
            case 'loadSlackHistory': loadSlackHistory(); break;
            case 'sendSlackMessage': sendSlackMessage(); break;
            case 'refreshSlackChannels': refreshSlackChannels(); break;
            case 'refreshCron': refreshCron(); break;
            case 'loadMoreCronHistory': loadMoreCronHistory(btn); break;
            case 'toggleScheduler': toggleScheduler(); break;
            case 'openConfigFile':
              console.log('[Webview] openConfigFile action triggered from button');
              openConfigFile();
              break;
            case 'refreshServices': refreshServices(); break;
            case 'serviceStart': serviceControl('start', btn.getAttribute('data-service')); break;
            case 'serviceStop': serviceControl('stop', btn.getAttribute('data-service')); break;
            case 'serviceLogs': serviceControl('logs', btn.getAttribute('data-service')); break;
            case 'runSelectedSkill': runSelectedSkill(); break;
            case 'openSelectedSkillFile': openSelectedSkillFile(); break;
            case 'setFlowchartHorizontal': setFlowchartView('horizontal'); break;
            case 'setFlowchartVertical': setFlowchartView('vertical'); break;
            case 'refreshWorkspaces': refreshWorkspaces(); break;
            case 'viewWorkspaceTools': viewWorkspaceTools(btn.getAttribute('data-uri')); break;
            case 'switchToWorkspace': switchToWorkspace(btn.getAttribute('data-uri')); break;
            case 'removeWorkspace': removeWorkspace(btn.getAttribute('data-uri')); break;
            case 'copySessionId': copySessionId(btn.getAttribute('data-session-id')); break;
            case 'openChatSession':
              console.log('[AA-WORKFLOW-WEBVIEW] openChatSession action triggered');
              openChatSession(btn.getAttribute('data-session-id'), btn.getAttribute('data-session-name'));
              break;
            case 'changeSessionViewMode':
              vscode.postMessage({ command: 'changeSessionViewMode', value: btn.getAttribute('data-value') });
              break;
            case 'changePersonaViewMode':
              vscode.postMessage({ command: 'changePersonaViewMode', value: btn.getAttribute('data-value') });
              break;
            case 'setSlackTarget':
              setSlackTarget(btn.getAttribute('data-value'));
              break;
            case 'refreshSlackTargets':
              refreshSlackTargets();
              break;
            case 'openCommandBuilder':
              showCommandBuilder();
              break;
            case 'loadSlackConfig':
              loadSlackConfig();
              break;
            case 'clearSlackUser':
              clearSlackUser();
              break;
            case 'searchSlackMessages':
              const searchQuery = document.getElementById('slackSearchInput')?.value;
              if (searchQuery) {
                vscode.postMessage({ command: 'searchSlackMessages', query: searchQuery });
              }
              break;
            case 'refreshSlackPending':
              vscode.postMessage({ command: 'refreshSlackPending' });
              break;
            case 'approveAllSlack':
              vscode.postMessage({ command: 'approveAllSlack' });
              break;
            case 'refreshSlackCache':
              vscode.postMessage({ command: 'refreshSlackCache' });
              break;
            default: break; // Unknown action
          }
        });

        // Slack search input - enter key
        const slackSearchInput = document.getElementById('slackSearchInput');
        if (slackSearchInput) {
          slackSearchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
              const query = e.target.value;
              if (query) {
                vscode.postMessage({ command: 'searchSlackMessages', query: query });
              }
            }
          });
        }

        // Slack channel browser filter
        const slackChannelSearchInput = document.getElementById('slackChannelSearch');
        if (slackChannelSearchInput) {
          let channelSearchTimeout;
          slackChannelSearchInput.addEventListener('input', (e) => {
            clearTimeout(channelSearchTimeout);
            channelSearchTimeout = setTimeout(() => {
              vscode.postMessage({ command: 'loadSlackChannelBrowser', query: e.target.value });
            }, 300);
          });
        }

        // Slack user browser filter
        const slackUserBrowserSearchInput = document.getElementById('slackUserBrowserSearch');
        if (slackUserBrowserSearchInput) {
          let userSearchTimeout;
          slackUserBrowserSearchInput.addEventListener('input', (e) => {
            clearTimeout(userSearchTimeout);
            userSearchTimeout = setTimeout(() => {
              vscode.postMessage({ command: 'loadSlackUserBrowser', query: e.target.value });
            }, 300);
          });
        }

        // Slack user search input
        const slackUserSearchInput = document.getElementById('slackUserSearch');
        if (slackUserSearchInput) {
          slackUserSearchInput.addEventListener('input', (e) => {
            const query = e.target.value;
            if (query.length >= 2) {
              searchSlackUsers(query);
            } else {
              document.getElementById('slackUserResults').style.display = 'none';
            }
          });
          slackUserSearchInput.addEventListener('focus', () => {
            const query = slackUserSearchInput.value;
            if (query.length >= 2) {
              searchSlackUsers(query);
            }
          });
        }

        // Hide user dropdown when clicking outside
        document.addEventListener('click', (e) => {
          const userContainer = document.getElementById('slackUserContainer');
          const userResults = document.getElementById('slackUserResults');
          if (userContainer && userResults && !userContainer.contains(e.target)) {
            userResults.style.display = 'none';
          }
        });

        // Skill search
        const skillSearchInput = document.getElementById('skillSearch');
        if (skillSearchInput) {
          skillSearchInput.addEventListener('input', filterSkills);
        }

        // Skill items
        document.querySelectorAll('.skill-item[data-skill]').forEach(item => {
          item.addEventListener('click', () => {
            const skillName = item.getAttribute('data-skill');
            if (skillName) selectSkill(skillName);
          });
        });

        // Skill view toggle
        document.querySelectorAll('.toggle-btn[data-view]').forEach(btn => {
          btn.addEventListener('click', () => {
            const view = btn.getAttribute('data-view');
            if (view && currentSkillYaml) {
              renderSkillView(view);
            }
          });
        });

        // Tool module items
        document.querySelectorAll('.tool-module-item[data-module]').forEach(item => {
          item.addEventListener('click', () => {
            const moduleName = item.getAttribute('data-module');
            if (moduleName) selectModule(moduleName);
          });
        });

        // Tool search
        const toolSearchInput = document.getElementById('toolSearch');
        if (toolSearchInput) {
          toolSearchInput.addEventListener('input', filterTools);
        }

        // Persona buttons
        document.querySelectorAll('[data-action="loadPersona"]').forEach(btn => {
          btn.addEventListener('click', () => {
            const personaName = btn.getAttribute('data-persona');
            if (personaName) {
              vscode.postMessage({ command: 'loadPersona', personaName });
            }
          });
        });

        document.querySelectorAll('[data-action="viewPersonaFile"]').forEach(btn => {
          btn.addEventListener('click', () => {
            const personaName = btn.getAttribute('data-persona');
            if (personaName) {
              vscode.postMessage({ command: 'viewPersonaFile', personaName });
            }
          });
        });

        // Persona card click to load persona in new chat
        document.querySelectorAll('.persona-card[data-persona]').forEach(card => {
          card.addEventListener('click', (e) => {
            // Don't trigger if clicking a button inside the card
            if (e.target.closest('button')) return;

            const personaName = card.getAttribute('data-persona');
            if (personaName) {
              // Load the persona in a new chat instead of showing details
              vscode.postMessage({ command: 'loadPersona', personaName });
            }
          });
        });

        // Cron job toggles
        document.querySelectorAll('.cron-job-toggle input[type="checkbox"]').forEach(toggle => {
          toggle.addEventListener('change', (e) => {
            const jobName = toggle.closest('.cron-job-item')?.getAttribute('data-job');
            if (jobName) toggleCronJob(jobName, e.target.checked);
          });
        });

        // Cron job run buttons
        document.querySelectorAll('[data-run-job]').forEach(btn => {
          btn.addEventListener('click', () => {
            const jobName = btn.getAttribute('data-run-job');
            if (jobName) runCronJobNow(jobName);
          });
        });

        // D-Bus controls
        const dbusServiceSelect = document.getElementById('dbusService');
        if (dbusServiceSelect) {
          dbusServiceSelect.addEventListener('change', updateDbusMethods);
        }

        const dbusMethodSelect = document.getElementById('dbusMethod');
        if (dbusMethodSelect) {
          dbusMethodSelect.addEventListener('change', updateDbusArgs);
        }

        const dbusQueryBtn = document.getElementById('dbusQueryBtn');
        if (dbusQueryBtn) {
          dbusQueryBtn.addEventListener('click', queryDbus);
        }

        // Semantic search handlers
        const semanticSearchBtn = document.getElementById('semanticSearchBtn');
        const semanticSearchInput = document.getElementById('semanticSearchInput');
        const semanticSearchProject = document.getElementById('semanticSearchProject');

        function executeSemanticSearch() {
          const query = semanticSearchInput?.value?.trim();
          const project = semanticSearchProject?.value;

          if (!query) {
            alert('Please enter a search query');
            return;
          }
          if (!project) {
            alert('Please select a project');
            return;
          }

          vscode.postMessage({
            command: 'semanticSearch',
            query: query,
            project: project
          });
        }

        if (semanticSearchBtn) {
          semanticSearchBtn.addEventListener('click', executeSemanticSearch);
        }

        if (semanticSearchInput) {
          semanticSearchInput.addEventListener('keypress', (e) => {
            // Enter triggers search, Shift+Enter allows newlines
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              executeSemanticSearch();
            }
          });
        }

        // ============================================
        // Ollama / Inference Event Listeners
        // ============================================

        // Ollama status is auto-refreshed via unified background sync
        // No manual refresh button needed

        // Test Ollama instance buttons
        document.querySelectorAll('[data-instance]').forEach(btn => {
          btn.addEventListener('click', () => {
            const instance = btn.getAttribute('data-instance');
            if (instance) {
              // Testing Ollama instance
              const statusEl = document.getElementById(instance + 'Status');
              if (statusEl) {
                statusEl.innerHTML = '<span class="status-dot checking"></span> Testing...';
              }
              vscode.postMessage({ command: 'testOllamaInstance', instance: instance });
            }
          });
        });

        // Run Inference Test button
        const runInferenceBtn = document.getElementById('runInferenceTest');
        if (runInferenceBtn) {
          runInferenceBtn.addEventListener('click', () => {
            const messageInput = document.getElementById('testMessage');
            const personaSelect = document.getElementById('testPersona');
            const skillSelect = document.getElementById('testSkill');

            const message = messageInput ? messageInput.value : '';
            const persona = personaSelect ? personaSelect.value : 'developer';
            const skill = skillSelect ? skillSelect.value : '';

            if (!message.trim()) {
              alert('Please enter a test message');
              return;
            }

            // Debug: console.log('[CommandCenter-Webview] Running inference test:', { message, persona, skill });

            // Show loading state
            const resultDiv = document.getElementById('inferenceResult');
            if (resultDiv) {
              resultDiv.style.display = 'block';
              resultDiv.innerHTML = '<div style="text-align: center; padding: 20px;"><span class="status-dot checking"></span> Running inference...</div>';
            }

            vscode.postMessage({
              command: 'runInferenceTest',
              message: message,
              persona: persona,
              skill: skill
            });
          });
        }

        // Copy inference result button
        const copyResultBtn = document.getElementById('copyInferenceResult');
        if (copyResultBtn) {
          copyResultBtn.addEventListener('click', () => {
            const resultDiv = document.getElementById('inferenceResult');
            if (resultDiv) {
              navigator.clipboard.writeText(resultDiv.innerText);
            }
          });
        }

        // Ollama status is auto-refreshed via unified background sync
        // No manual refresh needed on page load

        // Meetings Tab Functions
        ${getMeetingsTabScript()}

        // Create Session Tab Functions
        ${getCreateSessionTabScript()}

        // Sprint Tab Functions
        ${getSprintTabScript()}

      </script>
    </body>
    </html>`;
  }
}

// ============================================================================
// Helper Functions
// ============================================================================

function getNonce(): string {
  let text = "";
  const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
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
  console.log("[CommandCenter] Registering serializer early...");
  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer("aaCommandCenter", {
      async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel, _state: any) {
        console.log("[CommandCenter] Serializer deserializeWebviewPanel called - reviving panel");
        CommandCenterPanel.revive(webviewPanel, context.extensionUri, dataProvider);
      }
    })
  );
}

/**
 * Check if there's a Command Center panel that needs reconnection.
 * This handles the case where VS Code restored a panel before our serializer was ready.
 */
export function ensureCommandCenterConnected(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider
) {
  // If we already have a currentPanel, we're good
  if (CommandCenterPanel.currentPanel) {
    console.log("[CommandCenter] Panel already connected");
    return;
  }

  // Check if there's a visible Command Center panel that we need to reconnect to
  // Unfortunately VS Code doesn't provide a way to enumerate existing webview panels,
  // so we can't directly reconnect. The best we can do is ensure the serializer is
  // registered and hope VS Code calls it.
  console.log("[CommandCenter] No panel connected - serializer should handle restoration");
}
