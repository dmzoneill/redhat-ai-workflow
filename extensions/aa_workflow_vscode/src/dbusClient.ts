/**
 * Centralized D-Bus Client for AI Workflow Extension
 *
 * This module provides a type-safe, centralized interface for all D-Bus
 * communication with the AI Workflow daemons. Instead of scattered queryDBus()
 * calls throughout the codebase, all D-Bus operations go through this client.
 *
 * Benefits:
 * - Type safety: Each method returns typed data
 * - Single import: `import { dbus } from "./dbusClient"`
 * - Testable: Can mock the client for unit tests
 * - Discoverable: IDE autocomplete shows available methods
 * - Error handling: Centralized retry/timeout logic
 * - Persistent connection: Single D-Bus connection reused for all calls
 *
 * Architecture:
 *   UI Component -> DBusClient -> dbus-next (persistent) -> D-Bus Daemon
 */

import DBusNext, { MessageBus, ClientInterface, ProxyObject } from "dbus-next";
import { createLogger } from "./logger";

const logger = createLogger("DBusClient");

// ============================================================================
// D-Bus Service Configuration
// ============================================================================

const DBUS_CONFIG = {
  sprint: {
    service: "com.aiworkflow.BotSprint",
    path: "/com/aiworkflow/BotSprint",
    interface: "com.aiworkflow.BotSprint",
  },
  meet: {
    service: "com.aiworkflow.BotMeet",
    path: "/com/aiworkflow/BotMeet",
    interface: "com.aiworkflow.BotMeet",
  },
  cron: {
    service: "com.aiworkflow.BotCron",
    path: "/com/aiworkflow/BotCron",
    interface: "com.aiworkflow.BotCron",
  },
  session: {
    service: "com.aiworkflow.BotSession",
    path: "/com/aiworkflow/BotSession",
    interface: "com.aiworkflow.BotSession",
  },
  slack: {
    service: "com.aiworkflow.BotSlack",
    path: "/com/aiworkflow/BotSlack",
    interface: "com.aiworkflow.BotSlack",
  },
  video: {
    service: "com.aiworkflow.BotVideo",
    path: "/com/aiworkflow/BotVideo",
    interface: "com.aiworkflow.BotVideo",
  },
  stats: {
    service: "com.aiworkflow.BotStats",
    path: "/com/aiworkflow/BotStats",
    interface: "com.aiworkflow.BotStats",
  },
  config: {
    service: "com.aiworkflow.BotConfig",
    path: "/com/aiworkflow/BotConfig",
    interface: "com.aiworkflow.BotConfig",
  },
  memory: {
    service: "com.aiworkflow.Memory",
    path: "/com/aiworkflow/Memory",
    interface: "com.aiworkflow.Memory",
  },
  slop: {
    service: "com.aiworkflow.BotSlop",
    path: "/com/aiworkflow/BotSlop",
    interface: "com.aiworkflow.BotSlop",
  },
} as const;

type DaemonName = keyof typeof DBUS_CONFIG;

// ============================================================================
// Type Definitions
// ============================================================================

// Sprint Types
export interface SprintIssue {
  key: string;
  summary: string;
  storyPoints: number;
  priority: string;
  jiraStatus: string;
  assignee: string;
  approvalStatus: "pending" | "approved" | "rejected" | "in_progress" | "completed" | "blocked" | "waiting";
  waitingReason?: string;
  priorityReasoning: string[];
  estimatedActions: string[];
  chatId?: string;
  timeline: Array<{ timestamp: string; action: string; description: string }>;
  issueType?: string;
  created?: string;
  hasWorkLog?: boolean;
  workLogPath?: string;
  hasTrace?: boolean;
  tracePath?: string;
}

export interface SprintInfo {
  id: string;
  name: string;
  startDate: string;
  endDate: string;
  totalPoints: number;
  completedPoints: number;
}

export interface SprintState {
  currentSprint: SprintInfo | null;
  nextSprint: SprintInfo | null;
  issues: SprintIssue[];
  automaticMode: boolean;
  manuallyStarted: boolean;
  backgroundTasks: boolean;
  lastUpdated: string;
  processingIssue: string | null;
  workflowConfig?: WorkflowConfig;
  runtime?: {
    is_active: boolean;
    within_working_hours: boolean;
    issues_processed: number;
    issues_completed: number;
    last_jira_refresh: string | null;
  };
}

export interface WorkflowConfig {
  statusMappings: Record<string, {
    displayName: string;
    icon: string;
    color: string;
    description: string;
    jiraStatuses: string[];
    botCanWork: boolean;
    uiOrder: number;
    showApproveButtons?: boolean;
    botMonitors?: boolean;
  }>;
  mergeHoldPatterns: string[];
  spikeKeywords: string[];
  version: string;
}

// Meet Types
export interface Meeting {
  id: string;
  title: string;
  url: string;
  startTime: string;
  endTime?: string;
  organizer: string;
  status: "pending" | "approved" | "joined" | "ended" | "rejected" | "missed" | "skipped" | "scheduled" | "failed" | "active";
  botMode?: string;
  calendarName?: string;
}

export interface ActiveMeeting extends Meeting {
  sessionId: string;
  screenshotPath?: string;
  screenshotUpdated?: string;
}

export interface MonitoredCalendar {
  id: string;
  name: string;
  enabled: boolean;
}

export interface MeetState {
  schedulerRunning: boolean;
  upcomingMeetings: Meeting[];
  currentMeetings: ActiveMeeting[];
  monitoredCalendars: MonitoredCalendar[];
  lastPoll?: string;
  nextMeeting?: Meeting;
  countdown?: string;
  countdownSeconds?: number;
  updated_at?: string;
}

// Cron Types
export interface CronJob {
  name: string;
  description: string;
  skill: string;
  cron: string;
  trigger: string;
  persona: string;
  enabled: boolean;
  notify: string[];
  next_run: string | null;
}

export interface CronHistoryEntry {
  job_name: string;
  skill: string;
  timestamp: string;
  success: boolean;
  duration_ms: number;
  error: string | null;
  output_preview: string;
  session_name: string;
}

export interface CronState {
  enabled: boolean;
  timezone: string;
  execution_mode: string;
  jobs: CronJob[];
  history: CronHistoryEntry[];
  total_history: number;
  updated_at?: string;
}

// Session Types
export interface WorkspaceSession {
  id: string;
  name: string;
  project?: string;
  persona?: string;
  issueKey?: string;
  lastActive?: string;
  chatCount?: number;
}

export interface WorkspaceInfo {
  uri: string;
  name: string;
  sessions: WorkspaceSession[];
  activeSessionId?: string;
  lastActive?: string;
}

export interface SessionState {
  workspaces: Record<string, WorkspaceInfo>;
  workspace_count: number;
  total_sessions: number;
  active_workspace?: string;
  updated_at?: string;
}

// Stats Types
export interface AgentStats {
  version?: number;
  created?: string;
  last_updated?: string;
  lifetime: {
    tool_calls: number;
    tool_successes: number;
    tool_failures: number;
    tool_duration_ms?: number;
    skill_executions: number;
    skill_successes: number;
    skill_failures: number;
    memory_reads: number;
    memory_writes: number;
    lines_written: number;
    sessions: number;
  };
  current_session: {
    started: string;
    tool_calls: number;
    skill_executions: number;
    memory_ops: number;
  };
  daily: Record<string, {
    tool_calls: number;
    skill_executions: number;
    sessions?: number;
    memory_reads?: number;
    memory_writes?: number;
    tools_used?: Record<string, number>;
    skills_run?: Record<string, number>;
  }>;
  // Optional fields from file-based stats
  tools?: Record<string, any>;
  skills?: Record<string, any>;
}

export interface InferenceStats {
  total_requests: number;
  total_tokens: number;
  total_cost: number;
  by_model: Record<string, {
    requests: number;
    input_tokens: number;
    output_tokens: number;
    cost: number;
  }>;
}

export interface SkillExecution {
  skill_name: string;
  status: "running" | "completed" | "failed" | "idle";
  started_at?: string;
  completed_at?: string;
  current_step?: string;
  progress?: number;
  error?: string;
}

export interface PerformanceData {
  last_updated: string;
  quarter: string;
  day_of_quarter: number;
  overall_percentage: number;
  competencies: Record<string, { points: number; percentage: number }>;
  highlights: string[];
  gaps: string[];
  questions_summary?: Array<{
    id: string;
    text: string;
    evidence_count: number;
    notes_count: number;
    has_summary: boolean;
    last_evaluated: string | null;
  }>;
}

export interface StatsState {
  agent_stats: AgentStats | null;
  inference_stats: InferenceStats | null;
  skill_execution: SkillExecution | null;
  performance: PerformanceData | null;
  updated_at: string;
}

// Config Types
export interface SkillDefinition {
  name: string;
  description: string;
  version: string;
  inputs: Array<{
    name: string;
    type: string;
    required: boolean;
    description: string;
  }>;
  step_count: number;
  file: string;
}

export interface PersonaDefinition {
  name: string;
  description: string;
  tools: string[];
  skills: string[];
  file: string;
}

export interface ToolParameter {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: ToolParameter[];
  source_file?: string;
  line_number?: number;
}

export interface ToolModuleInfo {
  name: string;
  full_name: string;
  path: string;
  tool_count: number;
  tools: ToolInfo[];
  description?: string;
}

export interface ConfigState {
  skills_count: number;
  personas_count: number;
  tool_modules_count: number;
  skills_loaded_at: string | null;
  personas_loaded_at: string | null;
  config_loaded_at: string | null;
  cache_valid: boolean;
}

// Memory Types
export interface MemoryHealth {
  totalSize: string;
  sessionLogs: number;
  patterns: number;
  lastSession: string;
}

export interface MemoryFiles {
  state: string[];
  learned: string[];
  sessions: string[];
  knowledge: Array<{
    project: string;
    persona: string;
    confidence: number;
  }>;
}

export interface CurrentWork {
  activeIssue?: {
    key: string;
    summary: string;
    branch?: string;
    repo?: string;
    status?: string;
  } | null;
  activeMR?: {
    id: number;
    title: string;
    status?: string;
  } | null;
  activeIssues?: Array<{
    key: string;
    summary: string;
    branch?: string;
    repo?: string;
    status?: string;
  }>;
  openMRs?: Array<{
    id: number;
    title: string;
    status?: string;
    project?: string;
    url?: string;
    pipeline_status?: string;
    needs_review?: boolean;
  }>;
  followUps?: Array<{
    task: string;
    priority: string;
    issue_key?: string;
    mr_id?: number;
    due?: string;
    created?: string;
  }>;
}

export interface EnvironmentStatus {
  name: string;
  status: string;
  lastChecked?: string;
  alerts?: Array<{
    name: string;
    severity?: string;
  }>;
  namespaces?: Array<{
    name: string;
    mr_id?: string;
    commit_sha?: string;
    deployed_at?: string;
    expires?: string;
    status?: string;
  }>;
}

// Generic D-Bus Result
export interface DBusResult<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

// ============================================================================
// D-Bus Client Class - Persistent Connection via dbus-next
// ============================================================================

class DBusClient {
  private bus: MessageBus | null = null;
  private proxyCache: Map<string, ProxyObject> = new Map();
  private interfaceCache: Map<string, ClientInterface> = new Map();
  private connecting: Promise<void> | null = null;
  private connectionAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000; // Start with 1 second
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;

  // ==========================================================================
  // Connection Management
  // ==========================================================================

  /**
   * Get or create the persistent D-Bus session bus connection
   */
  private async ensureConnected(): Promise<MessageBus> {
    if (this.bus) {
      return this.bus;
    }

    // Avoid multiple concurrent connection attempts
    if (this.connecting) {
      await this.connecting;
      return this.bus!;
    }

    this.connecting = this.connect();
    try {
      await this.connecting;
      return this.bus!;
    } finally {
      this.connecting = null;
    }
  }

  /**
   * Establish the D-Bus connection
   */
  private async connect(): Promise<void> {
    try {
      this.bus = DBusNext.sessionBus();

      // Handle disconnection
      this.bus.on("error", (err: Error) => {
        logger.error(`Connection error: ${err.message}`);
        this.handleDisconnect();
      });

      // Reset reconnection state on successful connection
      this.connectionAttempts = 0;
      this.reconnectDelay = 1000;

      logger.log("Connected to session bus (persistent connection)");
    } catch (err) {
      logger.error("Failed to connect", err);
      throw err;
    }
  }

  /**
   * Handle disconnection - clear caches and attempt reconnect
   */
  private handleDisconnect(): void {
    // Cancel any pending reconnection first
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Remove all listeners and disconnect to prevent memory leak
    if (this.bus) {
      try {
        this.bus.removeAllListeners();
        this.bus.disconnect();
      } catch {
        // Ignore disconnect errors
      }
    }
    this.bus = null;

    // Clear cached interfaces (they hold listeners)
    for (const iface of this.interfaceCache.values()) {
      try {
        (iface as any).removeAllListeners?.();
      } catch {
        // Ignore errors
      }
    }
    this.proxyCache.clear();
    this.interfaceCache.clear();

    // Attempt reconnection with exponential backoff
    if (this.connectionAttempts < this.maxReconnectAttempts) {
      this.connectionAttempts++;
      const delay = this.reconnectDelay * Math.pow(2, this.connectionAttempts - 1);
      logger.log(`Reconnecting in ${delay}ms (attempt ${this.connectionAttempts})`);
      this.reconnectTimeout = setTimeout(() => {
        this.reconnectTimeout = null;
        this.ensureConnected().catch(() => {});
      }, delay);
    }
  }

  /**
   * Get or create a proxy object for a service
   */
  private async getProxy(daemon: DaemonName): Promise<ProxyObject> {
    const config = DBUS_CONFIG[daemon];
    const cacheKey = `${config.service}:${config.path}`;

    if (this.proxyCache.has(cacheKey)) {
      return this.proxyCache.get(cacheKey)!;
    }

    const bus = await this.ensureConnected();
    const proxy = await bus.getProxyObject(config.service, config.path);
    this.proxyCache.set(cacheKey, proxy);
    return proxy;
  }

  /**
   * Get or create an interface for a daemon
   */
  private async getInterface(daemon: DaemonName): Promise<ClientInterface> {
    const config = DBUS_CONFIG[daemon];
    const cacheKey = `${config.service}:${config.path}:${config.interface}`;

    if (this.interfaceCache.has(cacheKey)) {
      return this.interfaceCache.get(cacheKey)!;
    }

    const proxy = await this.getProxy(daemon);
    const iface = proxy.getInterface(config.interface);
    this.interfaceCache.set(cacheKey, iface);
    return iface;
  }

  /**
   * Disconnect and cleanup
   */
  public disconnect(): void {
    // Cancel any pending reconnection
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    // Clean up interfaces
    for (const iface of this.interfaceCache.values()) {
      try {
        (iface as any).removeAllListeners?.();
      } catch {
        // Ignore errors
      }
    }

    // Remove bus listeners and disconnect
    if (this.bus) {
      try {
        this.bus.removeAllListeners();
        this.bus.disconnect();
      } catch {
        // Ignore errors
      }
      this.bus = null;
      logger.log("Disconnected from session bus");
    }

    this.proxyCache.clear();
    this.interfaceCache.clear();
  }

  // ==========================================================================
  // Core D-Bus Communication
  // ==========================================================================

  /**
   * Execute a raw D-Bus method call using persistent connection
   */
  private async queryDBus(
    daemon: DaemonName,
    method: string,
    args?: { type: string; value: string }[]
  ): Promise<DBusResult> {
    try {
      const iface = await this.getInterface(daemon);

      // Convert args to proper types for dbus-next
      const callArgs: unknown[] = [];
      if (args) {
        for (const arg of args) {
          if (arg.type === "string") {
            callArgs.push(arg.value);
          } else if (arg.type === "int32") {
            callArgs.push(parseInt(arg.value, 10));
          } else if (arg.type === "boolean") {
            callArgs.push(arg.value === "true");
          } else {
            callArgs.push(arg.value);
          }
        }
      }

      // Call the method dynamically
      const result = await (iface as any)[method](...callArgs);

      // Parse result - dbus-next returns native types
      let data = result;
      if (typeof result === "string") {
        try {
          data = JSON.parse(result);
        } catch {
          // Keep as string if not JSON
        }
      }

      return { success: true, data };
    } catch (e: unknown) {
      const error = e instanceof Error ? e.message : "D-Bus query failed";

      // Check if it's a connection error and trigger reconnect
      if (error.includes("connection") || error.includes("disconnected")) {
        this.handleDisconnect();
      }

      return { success: false, error };
    }
  }

  /**
   * Call a custom method on a daemon via CallMethod D-Bus interface
   */
  private async callMethod<T = unknown>(
    daemon: DaemonName,
    methodName: string,
    params: Record<string, unknown> = {}
  ): Promise<DBusResult<T>> {
    try {
      const result = await this.queryDBus(daemon, "CallMethod", [
        { type: "string", value: methodName },
        { type: "string", value: JSON.stringify(params) },
      ]);

      if (result.success && result.data) {
        const parsed = typeof result.data === "string" ? JSON.parse(result.data) : result.data;
        return {
          success: parsed.success !== false,
          data: parsed as T,
          error: parsed.error,
        };
      }
      return { success: false, error: result.error || "D-Bus call failed" };
    } catch (e: unknown) {
      const error = e instanceof Error ? e.message : "D-Bus call failed";
      return { success: false, error };
    }
  }

  // ==========================================================================
  // Sprint Bot Methods
  // ==========================================================================

  /**
   * Get full sprint state including issues, config, and runtime status
   */
  async sprint_getState(): Promise<DBusResult<{ state: SprintState }>> {
    return this.callMethod("sprint", "get_state");
  }

  /**
   * Approve an issue for the sprint bot to work on
   */
  async sprint_approve(issueKey: string): Promise<DBusResult> {
    return this.callMethod("sprint", "approve_issue", { issue_key: issueKey });
  }

  /**
   * Reject an issue (remove from sprint bot queue)
   */
  async sprint_reject(issueKey: string): Promise<DBusResult> {
    return this.callMethod("sprint", "reject_issue", { issue_key: issueKey });
  }

  /**
   * Abort processing of an issue
   */
  async sprint_abort(issueKey: string): Promise<DBusResult> {
    return this.callMethod("sprint", "abort_issue", { issue_key: issueKey });
  }

  /**
   * Start working on an issue immediately
   */
  async sprint_startIssue(issueKey: string, background = false): Promise<DBusResult> {
    return this.callMethod("sprint", "start_issue", { issue_key: issueKey, background });
  }

  /**
   * Open an issue in Cursor
   */
  async sprint_openInCursor(issueKey: string): Promise<DBusResult> {
    return this.callMethod("sprint", "open_in_cursor", { issue_key: issueKey });
  }

  /**
   * Approve all pending issues
   */
  async sprint_approveAll(): Promise<DBusResult> {
    return this.callMethod("sprint", "approve_all");
  }

  /**
   * Reject all pending issues
   */
  async sprint_rejectAll(): Promise<DBusResult> {
    return this.callMethod("sprint", "reject_all");
  }

  /**
   * Enable the sprint bot (automatic mode)
   */
  async sprint_enable(): Promise<DBusResult> {
    return this.callMethod("sprint", "enable");
  }

  /**
   * Disable the sprint bot
   */
  async sprint_disable(): Promise<DBusResult> {
    return this.callMethod("sprint", "disable");
  }

  /**
   * Start the sprint bot manually (ignores schedule)
   */
  async sprint_start(): Promise<DBusResult> {
    return this.callMethod("sprint", "start");
  }

  /**
   * Stop the sprint bot
   */
  async sprint_stop(): Promise<DBusResult> {
    return this.callMethod("sprint", "stop");
  }

  /**
   * Toggle background task mode
   */
  async sprint_toggleBackground(enabled?: boolean): Promise<DBusResult> {
    return this.callMethod("sprint", "toggle_background", enabled !== undefined ? { enabled } : {});
  }

  /**
   * Refresh sprint data from Jira
   */
  async sprint_refresh(): Promise<DBusResult> {
    return this.callMethod("sprint", "refresh");
  }

  /**
   * Get sprint history (completed sprints)
   */
  async sprint_getHistory(): Promise<DBusResult<{ history: any[] }>> {
    return this.callMethod("sprint", "get_history");
  }

  /**
   * Get execution trace for an issue
   */
  async sprint_getTrace(issueKey: string): Promise<DBusResult<{ trace: any }>> {
    return this.callMethod("sprint", "get_trace", { issue_key: issueKey });
  }

  /**
   * List all available execution traces
   */
  async sprint_listTraces(): Promise<DBusResult<{ traces: Array<{ issue_key: string; state: string; started_at: string }> }>> {
    return this.callMethod("sprint", "list_traces");
  }

  // ==========================================================================
  // Meet Bot Methods
  // ==========================================================================

  /**
   * Get full meeting state including upcoming and current meetings
   */
  async meet_getState(): Promise<DBusResult<{ state: MeetState }>> {
    return this.callMethod("meet", "get_state");
  }

  /**
   * Approve a meeting for the bot to join
   */
  async meet_approve(eventId: string, mode = "notes"): Promise<DBusResult> {
    return this.callMethod("meet", "approve_meeting", { event_id: eventId, mode });
  }

  /**
   * Reject a meeting (skip it)
   */
  async meet_reject(eventId: string): Promise<DBusResult> {
    return this.callMethod("meet", "skip_meeting", { event_id: eventId });
  }

  /**
   * Unapprove a meeting (revert to pending/skipped)
   */
  async meet_unapprove(eventId: string): Promise<DBusResult> {
    return this.callMethod("meet", "unapprove_meeting", { event_id: eventId });
  }

  /**
   * Join a meeting immediately
   */
  async meet_join(meetUrl: string, title?: string, mode = "notes", videoEnabled = false): Promise<DBusResult> {
    return this.callMethod("meet", "join_meeting", { meet_url: meetUrl, title, mode, video_enabled: videoEnabled });
  }

  /**
   * Leave a meeting
   */
  async meet_leave(eventId: string): Promise<DBusResult> {
    return this.callMethod("meet", "leave_meeting", { event_id: eventId });
  }

  /**
   * Approve all pending meetings
   */
  async meet_approveAll(): Promise<DBusResult> {
    return this.callMethod("meet", "approve_all");
  }

  /**
   * Reject all pending meetings
   */
  async meet_rejectAll(): Promise<DBusResult> {
    return this.callMethod("meet", "reject_all");
  }

  /**
   * Refresh calendar data
   */
  async meet_refresh(): Promise<DBusResult> {
    return this.callMethod("meet", "refresh");
  }

  /**
   * Unapprove all meetings
   */
  async meet_unapproveAll(): Promise<DBusResult> {
    return this.callMethod("meet", "unapprove_all");
  }

  /**
   * Join all approved meetings
   */
  async meet_joinAll(): Promise<DBusResult> {
    return this.callMethod("meet", "join_all");
  }

  /**
   * Leave all active meetings
   */
  async meet_leaveAll(): Promise<DBusResult> {
    return this.callMethod("meet", "leave_all");
  }

  /**
   * Toggle the meeting scheduler
   */
  async meet_toggleScheduler(enabled: boolean): Promise<DBusResult> {
    return this.callMethod("meet", "toggle_scheduler", { enabled });
  }

  /**
   * Toggle a calendar's enabled state
   */
  async meet_toggleCalendar(calendarId: string, enabled: boolean): Promise<DBusResult> {
    return this.callMethod("meet", "toggle_calendar", { calendar_id: calendarId, enabled });
  }

  /**
   * Set meeting mode for a meeting
   */
  async meet_setMeetingMode(meetingId: string, mode: string): Promise<DBusResult> {
    return this.callMethod("meet", "set_meeting_mode", { meeting_id: meetingId, mode });
  }

  /**
   * Set bot mode (interactive or notes)
   */
  async meet_setBotMode(mode: "interactive" | "notes"): Promise<DBusResult> {
    return this.callMethod("meet", "set_bot_mode", { mode });
  }

  /**
   * Set video enabled state
   */
  async meet_setVideoEnabled(enabled: boolean): Promise<DBusResult> {
    return this.callMethod("meet", "set_video_enabled", { enabled });
  }

  /**
   * Set video quality
   */
  async meet_setVideoQuality(quality: string): Promise<DBusResult> {
    return this.callMethod("meet", "set_video_quality", { quality });
  }

  /**
   * Set video position
   */
  async meet_setVideoPosition(position: string): Promise<DBusResult> {
    return this.callMethod("meet", "set_video_position", { position });
  }

  /**
   * Set video size
   */
  async meet_setVideoSize(size: string): Promise<DBusResult> {
    return this.callMethod("meet", "set_video_size", { size });
  }

  /**
   * Set video opacity
   */
  async meet_setVideoOpacity(opacity: number): Promise<DBusResult> {
    return this.callMethod("meet", "set_video_opacity", { opacity });
  }

  /**
   * Start the meeting scheduler
   */
  async meet_startScheduler(): Promise<DBusResult> {
    return this.callMethod("meet", "start_scheduler");
  }

  /**
   * Stop the meeting scheduler
   */
  async meet_stopScheduler(): Promise<DBusResult> {
    return this.callMethod("meet", "stop_scheduler");
  }

  /**
   * Mute audio in a meeting
   */
  async meet_muteAudio(sessionId: string): Promise<DBusResult> {
    return this.callMethod("meet", "mute_audio", { session_id: sessionId });
  }

  /**
   * Unmute audio in a meeting
   */
  async meet_unmuteAudio(sessionId: string): Promise<DBusResult> {
    return this.callMethod("meet", "unmute_audio", { session_id: sessionId });
  }

  /**
   * Test TTS in a meeting
   */
  async meet_testTts(sessionId?: string): Promise<DBusResult> {
    return this.callMethod("meet", "test_tts", sessionId ? { session_id: sessionId } : {});
  }

  /**
   * Test avatar in a meeting
   */
  async meet_testAvatar(sessionId?: string): Promise<DBusResult> {
    return this.callMethod("meet", "test_avatar", sessionId ? { session_id: sessionId } : {});
  }

  /**
   * Preload Jira data for a meeting
   */
  async meet_preloadJira(sessionId?: string): Promise<DBusResult> {
    return this.callMethod("meet", "preload_jira", sessionId ? { session_id: sessionId } : {});
  }

  /**
   * Set default meeting mode
   */
  async meet_setDefaultMode(mode: string): Promise<DBusResult> {
    return this.callMethod("meet", "set_default_mode", { mode });
  }

  /**
   * Refresh calendars
   */
  async meet_refreshCalendars(): Promise<DBusResult> {
    return this.callMethod("meet", "refresh_calendars");
  }

  /**
   * Get a meeting note
   */
  async meet_getMeetingNote(noteId: number): Promise<DBusResult> {
    return this.callMethod("meet", "get_meeting_note", { note_id: noteId });
  }

  /**
   * Get transcript for a meeting
   */
  async meet_getTranscript(noteId: number): Promise<DBusResult> {
    return this.callMethod("meet", "get_transcript", { note_id: noteId });
  }

  /**
   * Get bot log for a meeting
   */
  async meet_getBotLog(noteId: number): Promise<DBusResult> {
    return this.callMethod("meet", "get_bot_log", { note_id: noteId });
  }

  /**
   * Get linked issues for a meeting
   */
  async meet_getLinkedIssues(noteId: number): Promise<DBusResult> {
    return this.callMethod("meet", "get_linked_issues", { note_id: noteId });
  }

  /**
   * Search meeting notes
   */
  async meet_searchNotes(query: string): Promise<DBusResult> {
    return this.callMethod("meet", "search_notes", { query });
  }

  /**
   * Clear captions
   */
  async meet_clearCaptions(): Promise<DBusResult> {
    return this.callMethod("meet", "clear_captions");
  }

  // ==========================================================================
  // Cron Bot Methods
  // ==========================================================================

  /**
   * Get full cron state including jobs and history
   */
  async cron_getState(): Promise<DBusResult<{ state: CronState }>> {
    return this.callMethod("cron", "get_state");
  }

  /**
   * Get cron execution history
   */
  async cron_getHistory(limit = 20): Promise<DBusResult<{ history: CronHistoryEntry[] }>> {
    return this.callMethod("cron", "get_history", { limit });
  }

  /**
   * Enable a cron job
   */
  async cron_enableJob(jobName: string): Promise<DBusResult> {
    return this.callMethod("cron", "enable_job", { job_name: jobName });
  }

  /**
   * Disable a cron job
   */
  async cron_disableJob(jobName: string): Promise<DBusResult> {
    return this.callMethod("cron", "disable_job", { job_name: jobName });
  }

  /**
   * Run a cron job immediately
   */
  async cron_runJob(jobName: string): Promise<DBusResult> {
    return this.callMethod("cron", "run_job", { job_name: jobName });
  }

  /**
   * Reload cron configuration
   */
  async cron_reload(): Promise<DBusResult> {
    return this.callMethod("cron", "reload_config");
  }

  /**
   * Toggle the cron scheduler enabled state
   */
  async cron_toggleScheduler(enabled: boolean): Promise<DBusResult> {
    return this.callMethod("cron", "toggle_scheduler", { enabled });
  }

  /**
   * Toggle a specific job's enabled state
   */
  async cron_toggleJob(jobName: string, enabled: boolean): Promise<DBusResult> {
    return this.callMethod("cron", "toggle_job", { job_name: jobName, enabled });
  }

  /**
   * Get cron configuration
   */
  async cron_getConfig(section?: string, key?: string): Promise<DBusResult> {
    return this.callMethod("cron", "get_config", { section, key });
  }

  /**
   * Update cron configuration
   */
  async cron_updateConfig(section: string, key: string, value: unknown): Promise<DBusResult> {
    return this.callMethod("cron", "update_config", { section, key, value });
  }

  // ==========================================================================
  // Session Bot Methods
  // ==========================================================================

  /**
   * Get full session state including workspaces and sessions
   */
  async session_getState(): Promise<DBusResult<SessionState>> {
    return this.callMethod("session", "get_state");
  }

  /**
   * Remove a workspace from tracking
   */
  async session_removeWorkspace(uri: string): Promise<DBusResult> {
    return this.callMethod("session", "remove_workspace", { uri });
  }

  /**
   * Trigger a sync of session data
   */
  async session_sync(): Promise<DBusResult> {
    return this.callMethod("session", "sync");
  }

  /**
   * Search chats in session history
   */
  async session_searchChats(query: string, limit = 20): Promise<DBusResult> {
    return this.callMethod("session", "search_chats", { query, limit });
  }

  /**
   * Trigger an immediate refresh of session data
   */
  async session_refreshNow(): Promise<DBusResult> {
    return this.callMethod("session", "refresh_now");
  }

  /**
   * List all sessions
   */
  async session_list(): Promise<DBusResult<{ sessions: any[] }>> {
    return this.callMethod("session", "get_sessions");
  }

  /**
   * Get session statistics
   * Note: Stats are included in get_sessions response, so we use that
   */
  async session_getStats(): Promise<DBusResult<{ stats: any }>> {
    // The session daemon doesn't have a separate get_stats handler
    // Stats are included in the get_sessions response
    const result = await this.callMethod("session", "get_sessions");
    if (result.success && result.data) {
      const data = result.data as any;
      return {
        success: true,
        data: {
          stats: {
            total_sessions: data.session_count || 0,
            active_sessions: data.sessions?.filter((s: any) => s.is_active).length || 0,
            total_tool_calls: 0,  // Not tracked in session daemon
            total_skill_runs: 0,  // Not tracked in session daemon
          }
        }
      };
    }
    return { success: false, error: result.error || "Failed to get session stats" };
  }

  /**
   * Start a new session
   */
  async session_start(name?: string, project?: string, persona?: string): Promise<DBusResult> {
    return this.callMethod("session", "start", { name, project, persona });
  }

  /**
   * Switch to a session
   */
  async session_switch(sessionId: string): Promise<DBusResult> {
    return this.callMethod("session", "switch", { session_id: sessionId });
  }

  /**
   * Close a session
   */
  async session_close(sessionId: string): Promise<DBusResult> {
    return this.callMethod("session", "close", { session_id: sessionId });
  }

  // ==========================================================================
  // Slack Bot Methods
  // ==========================================================================

  /**
   * Get Slack bot status
   */
  async slack_getStatus(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetStatus");
  }

  /**
   * Get pending Slack messages awaiting approval
   */
  async slack_getPending(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetPending");
  }

  /**
   * Get Slack message history
   */
  async slack_getHistory(limit = 10, channelId = "", userId = "", status = ""): Promise<DBusResult> {
    return this.queryDBus("slack", "GetHistory", [
      { type: "int32", value: String(limit) },
      { type: "string", value: channelId },
      { type: "string", value: userId },
      { type: "string", value: status },
    ]);
  }

  /**
   * Approve all pending Slack messages
   */
  async slack_approveAll(): Promise<DBusResult> {
    return this.queryDBus("slack", "ApproveAll");
  }

  /**
   * Send a Slack message
   */
  async slack_sendMessage(channelId: string, text: string, threadTs?: string): Promise<DBusResult> {
    return this.queryDBus("slack", "SendMessage", [
      { type: "string", value: channelId },
      { type: "string", value: text },
      { type: "string", value: threadTs || "" },
    ]);
  }

  /**
   * Get channels the bot is a member of
   */
  async slack_getMyChannels(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetMyChannels");
  }

  /**
   * Search and cache Slack users
   */
  async slack_searchUsers(query: string): Promise<DBusResult> {
    return this.queryDBus("slack", "SearchAndCacheUsers", [
      { type: "string", value: query },
    ]);
  }

  /**
   * Search Slack messages
   */
  async slack_searchMessages(query: string, limit = 20): Promise<DBusResult> {
    return this.queryDBus("slack", "SearchMessages", [
      { type: "string", value: query },
      { type: "int32", value: String(limit) },
    ]);
  }

  /**
   * Approve a specific Slack message
   */
  async slack_approveMessage(messageId: string): Promise<DBusResult> {
    return this.queryDBus("slack", "ApproveMessage", [
      { type: "string", value: messageId },
    ]);
  }

  /**
   * Reject a specific Slack message
   */
  async slack_rejectMessage(messageId: string): Promise<DBusResult> {
    return this.queryDBus("slack", "RejectMessage", [
      { type: "string", value: messageId },
    ]);
  }

  /**
   * Reload Slack daemon configuration
   */
  async slack_reloadConfig(): Promise<DBusResult> {
    return this.queryDBus("slack", "ReloadConfig");
  }

  /**
   * Refresh channel cache from Slack API
   */
  async slack_refreshChannelCache(): Promise<DBusResult> {
    return this.queryDBus("slack", "RefreshChannelCache");
  }

  /**
   * Refresh user cache from Slack API
   */
  async slack_refreshUserCache(): Promise<DBusResult> {
    return this.queryDBus("slack", "RefreshUserCache");
  }

  /**
   * Get channel cache statistics
   */
  async slack_getChannelCacheStats(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetChannelCacheStats");
  }

  /**
   * Get user cache statistics
   */
  async slack_getUserCacheStats(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetUserCacheStats");
  }

  /**
   * Find a channel by query
   */
  async slack_findChannel(query: string): Promise<DBusResult> {
    return this.queryDBus("slack", "FindChannel", [
      { type: "string", value: query },
    ]);
  }

  /**
   * Find a user by query
   */
  async slack_findUser(query: string): Promise<DBusResult> {
    return this.queryDBus("slack", "FindUser", [
      { type: "string", value: query },
    ]);
  }

  /**
   * Get list of available commands
   */
  async slack_getCommandList(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetCommandList");
  }

  /**
   * Get Slack daemon configuration
   */
  async slack_getConfig(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetConfig");
  }

  /**
   * Set debug mode
   */
  async slack_setDebugMode(enabled: boolean): Promise<DBusResult> {
    return this.queryDBus("slack", "SetDebugMode", [
      { type: "string", value: enabled ? "true" : "false" },
    ]);
  }

  /**
   * Perform a health check on the Slack daemon
   */
  async slack_healthCheck(): Promise<DBusResult> {
    return this.queryDBus("slack", "HealthCheck");
  }

  /**
   * Get sync status
   */
  async slack_getSyncStatus(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetSyncStatus");
  }

  /**
   * Start background sync
   */
  async slack_startSync(): Promise<DBusResult> {
    return this.queryDBus("slack", "StartSync");
  }

  /**
   * Stop background sync
   */
  async slack_stopSync(): Promise<DBusResult> {
    return this.queryDBus("slack", "StopSync");
  }

  /**
   * Trigger a specific sync operation
   */
  async slack_triggerSync(syncType: string): Promise<DBusResult> {
    return this.queryDBus("slack", "TriggerSync", [
      { type: "string", value: syncType },
    ]);
  }

  /**
   * Get thread replies
   */
  async slack_getThreadReplies(channelId: string, threadTs: string, limit: number = 50): Promise<DBusResult> {
    return this.queryDBus("slack", "GetThreadReplies", [
      { type: "string", value: channelId },
      { type: "string", value: threadTs },
      { type: "int32", value: String(limit) },
    ]);
  }

  /**
   * Get thread context (AI-friendly format)
   */
  async slack_getThreadContext(channelId: string, threadTs: string): Promise<DBusResult> {
    return this.queryDBus("slack", "GetThreadContext", [
      { type: "string", value: channelId },
      { type: "string", value: threadTs },
    ]);
  }

  /**
   * Get user profile
   */
  async slack_getUserProfile(userId: string): Promise<DBusResult> {
    return this.queryDBus("slack", "GetUserProfile", [
      { type: "string", value: userId },
    ]);
  }

  /**
   * Get sidebar DMs
   */
  async slack_getSidebarDMs(): Promise<DBusResult> {
    return this.queryDBus("slack", "GetSidebarDMs");
  }

  /**
   * Get channel history
   */
  async slack_getChannelHistory(channelId: string, limit: number = 50, oldest: string = "", latest: string = ""): Promise<DBusResult> {
    return this.queryDBus("slack", "GetChannelHistory", [
      { type: "string", value: channelId },
      { type: "int32", value: String(limit) },
      { type: "string", value: oldest },
      { type: "string", value: latest },
    ]);
  }

  /**
   * List channel members
   */
  async slack_listChannelMembers(channelId: string, count: number = 100): Promise<DBusResult> {
    return this.queryDBus("slack", "ListChannelMembers", [
      { type: "string", value: channelId },
      { type: "int32", value: String(count) },
    ]);
  }

  // ==========================================================================
  // Stats Bot Methods
  // ==========================================================================

  /**
   * Get full stats state including agent stats, inference stats, and skill execution
   */
  async stats_getState(): Promise<DBusResult<{ state: StatsState }>> {
    return this.callMethod("stats", "get_state");
  }

  /**
   * Get agent statistics (tool calls, skill executions, etc.)
   */
  async stats_getAgentStats(): Promise<DBusResult<{ stats: AgentStats }>> {
    return this.callMethod("stats", "get_agent_stats");
  }

  /**
   * Get inference statistics (LLM usage, tokens, costs)
   */
  async stats_getInferenceStats(): Promise<DBusResult<{ stats: InferenceStats }>> {
    return this.callMethod("stats", "get_inference_stats");
  }

  /**
   * Get current skill execution state
   */
  async stats_getSkillExecution(): Promise<DBusResult<{ execution: SkillExecution }>> {
    return this.callMethod("stats", "get_skill_execution");
  }

  // ==========================================================================
  // Utility Methods
  // ==========================================================================

  /**
   * Map daemon names to their systemd unit names
   */
  private static readonly SYSTEMD_UNITS: Record<DaemonName, string> = {
    sprint: "bot-sprint.service",
    meet: "bot-meet.service",
    cron: "bot-cron.service",
    session: "bot-session.service",
    slack: "bot-slack.service",
    video: "bot-video.service",
    stats: "bot-stats.service",
    config: "bot-config.service",
    memory: "bot-memory.service",
    slop: "bot-slop.service",
  };

  /**
   * Check if a daemon is running using systemctl is-active.
   * This is more reliable than D-Bus for checking service status because:
   * 1. D-Bus requires the service to be registered and responding
   * 2. Cached D-Bus proxies can become stale
   * 3. systemctl directly queries systemd for the actual service state
   */
  async isRunning(daemon: DaemonName): Promise<boolean> {
    const unit = DBusClient.SYSTEMD_UNITS[daemon];
    if (!unit) {
      logger.error(`Unknown daemon: ${daemon}`);
      return false;
    }

    try {
      const { exec } = await import("child_process");
      const { promisify } = await import("util");
      const execPromise = promisify(exec);

      // systemctl is-active returns exit code 0 if active, non-zero otherwise
      const { stdout } = await execPromise(`systemctl --user is-active ${unit}`, {
        timeout: 5000,
      });
      const status = stdout.trim();
      return status === "active";
    } catch (error: unknown) {
      // Non-zero exit code means service is not active
      // This is expected for inactive services, not an error
      return false;
    }
  }

  /**
   * Get status of all daemons using systemctl
   */
  async getAllStatus(): Promise<Record<DaemonName, boolean>> {
    const daemons = Object.keys(DBUS_CONFIG) as DaemonName[];

    // Check all services in parallel using systemctl
    const results = await Promise.all(
      daemons.map(async (d) => [d, await this.isRunning(d)] as const)
    );
    return Object.fromEntries(results) as Record<DaemonName, boolean>;
  }

  // ==========================================================================
  // Config Daemon Methods
  // ==========================================================================

  /**
   * Get list of all skills with metadata
   */
  async config_getSkillsList(): Promise<DBusResult<{ skills: SkillDefinition[] }>> {
    return this.callMethod("config", "get_skills_list");
  }

  /**
   * Get full skill definition by name
   */
  async config_getSkillDefinition(name: string): Promise<DBusResult<{ skill: any }>> {
    return this.callMethod("config", "get_skill_definition", { name });
  }

  /**
   * Get list of all personas with metadata
   */
  async config_getPersonasList(): Promise<DBusResult<{ personas: PersonaDefinition[] }>> {
    return this.callMethod("config", "get_personas_list");
  }

  /**
   * Get full persona definition by name
   */
  async config_getPersonaDefinition(name: string): Promise<DBusResult<{ persona: any }>> {
    return this.callMethod("config", "get_persona_definition", { name });
  }

  /**
   * Get list of all tool modules with metadata
   */
  async config_getToolModules(): Promise<DBusResult<{ modules: ToolModuleInfo[] }>> {
    return this.callMethod("config", "get_tool_modules");
  }

  /**
   * Get project configuration
   */
  async config_getConfig(): Promise<DBusResult<{ config: any }>> {
    return this.callMethod("config", "get_config");
  }

  /**
   * Invalidate config cache (force reload)
   */
  async config_invalidateCache(cacheType: "all" | "skills" | "personas" | "tool_modules" | "config" = "all"): Promise<DBusResult> {
    return this.callMethod("config", "invalidate_cache", { cache_type: cacheType });
  }

  /**
   * Get config daemon state
   */
  async config_getState(): Promise<DBusResult<{ state: ConfigState }>> {
    return this.callMethod("config", "get_state");
  }

  // ==========================================================================
  // Memory Daemon Methods
  // ==========================================================================

  /**
   * Get memory health statistics
   */
  async memory_getHealth(): Promise<DBusResult<{ health: MemoryHealth }>> {
    return this.callMethod("memory", "get_health");
  }

  /**
   * Get list of memory files by category
   */
  async memory_getFiles(): Promise<DBusResult<{ files: MemoryFiles }>> {
    return this.callMethod("memory", "get_files");
  }

  /**
   * Get current work state (active issue, MR, follow-ups)
   */
  async memory_getCurrentWork(): Promise<DBusResult<{ work: CurrentWork }>> {
    return this.callMethod("memory", "get_current_work");
  }

  /**
   * Get environment statuses
   */
  async memory_getEnvironments(): Promise<DBusResult<{ environments: EnvironmentStatus[] }>> {
    return this.callMethod("memory", "get_environments");
  }

  /**
   * Read a memory file by path
   */
  async memory_read(path: string): Promise<DBusResult<{ content: any }>> {
    return this.callMethod("memory", "read", { path });
  }

  /**
   * Write to a memory file
   */
  async memory_write(path: string, content: any): Promise<DBusResult> {
    return this.callMethod("memory", "write", { path, content: JSON.stringify(content) });
  }

  /**
   * Append to a memory file
   */
  async memory_append(path: string, key: string, value: any): Promise<DBusResult> {
    return this.callMethod("memory", "append", { path, key, value: JSON.stringify(value) });
  }

  /**
   * Get learned patterns from memory (raw format)
   */
  async memory_getPatterns(): Promise<DBusResult<{ patterns: any[] }>> {
    return this.callMethod("memory", "get_patterns");
  }

  /**
   * Get learned patterns in UI-friendly format
   */
  async memory_getLearnedPatterns(): Promise<DBusResult<{ patterns: any[] }>> {
    return this.callMethod("memory", "get_learned_patterns");
  }

  /**
   * Get memory daemon state
   */
  async memory_getState(): Promise<DBusResult<{ state: any }>> {
    return this.callMethod("memory", "get_state");
  }

  /**
   * List memory files in a category
   */
  async memory_listFiles(category: string): Promise<DBusResult<{ files: any[] }>> {
    return this.callMethod("memory", "list_files", { category });
  }

  /**
   * Read a memory file
   */
  async memory_readFile(path: string): Promise<DBusResult<{ content: string }>> {
    return this.callMethod("memory", "read", { path });
  }

  /**
   * Get session logs
   */
  async memory_getSessionLogs(limit: number = 20): Promise<DBusResult<{ logs: any[] }>> {
    return this.callMethod("memory", "get_session_logs", { limit });
  }

  /**
   * Get tool fixes
   */
  async memory_getToolFixes(): Promise<DBusResult<{ fixes: any[] }>> {
    return this.callMethod("memory", "get_tool_fixes");
  }

  /**
   * Get memory directory path
   */
  async memory_getMemoryDir(): Promise<DBusResult<{ path: string }>> {
    return this.callMethod("memory", "get_memory_dir");
  }

  // ==========================================================================
  // Slop Bot Methods
  // ==========================================================================

  /**
   * Get slop bot loop status
   */
  async slop_getLoopStatus(): Promise<DBusResult<any>> {
    return this.callMethod("slop", "get_loop_status");
  }

  /**
   * Get slop findings with optional filters
   */
  async slop_getFindings(
    loop?: string,
    severity?: string,
    status?: string,
    limit: number = 100
  ): Promise<DBusResult<{ findings: any[]; count: number }>> {
    return this.callMethod("slop", "get_findings", { loop, severity, status, limit });
  }

  /**
   * Get slop statistics
   */
  async slop_getStats(): Promise<DBusResult<any>> {
    return this.callMethod("slop", "get_stats");
  }

  /**
   * Trigger immediate scan of all loops
   */
  async slop_scanNow(): Promise<DBusResult> {
    return this.callMethod("slop", "scan_now");
  }

  /**
   * Run specific loops by name
   */
  async slop_runLoops(loops: string[]): Promise<DBusResult> {
    return this.callMethod("slop", "scan_loops", { loops });
  }

  /**
   * Stop a specific loop
   */
  async slop_stopLoop(loopName: string): Promise<DBusResult> {
    return this.callMethod("slop", "stop_loop", { loop_name: loopName });
  }

  /**
   * Stop all running loops
   */
  async slop_stopAll(): Promise<DBusResult> {
    return this.callMethod("slop", "stop_all");
  }

  /**
   * Acknowledge a finding
   */
  async slop_acknowledge(findingId: string): Promise<DBusResult> {
    return this.callMethod("slop", "acknowledge", { finding_id: findingId });
  }

  /**
   * Mark a finding as fixed
   */
  async slop_markFixed(findingId: string): Promise<DBusResult> {
    return this.callMethod("slop", "mark_fixed", { finding_id: findingId });
  }

  /**
   * Mark a finding as false positive
   */
  async slop_markFalsePositive(findingId: string): Promise<DBusResult> {
    return this.callMethod("slop", "mark_false_positive", { finding_id: findingId });
  }

  /**
   * Get findings by loop name
   */
  async slop_getFindingsByLoop(loopName: string): Promise<DBusResult<{ findings: any[] }>> {
    return this.callMethod("slop", "get_findings_by_loop", { loop_name: loopName });
  }
}

// Export singleton instance
export const dbus = new DBusClient();

// Export class for testing
export { DBusClient };
