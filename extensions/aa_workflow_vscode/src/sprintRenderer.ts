/**
 * Sprint Tab for Command Center
 *
 * Provides UI for the Sprint Bot Autopilot:
 * - Sprint issues list with approve/reject/abort buttons
 * - Color-coded status indicators (red=blocked, yellow=waiting, blue=review, green=done)
 * - Priority reasoning display
 * - Event timeline per issue
 * - Sprint history (collapsed by default)
 * - Tool gap requests section
 *
 * ARCHITECTURE: Sprint state is loaded via D-Bus from the Sprint daemon.
 * The commandCenter.ts uses dbus.sprint_getState() for all sprint data.
 */

import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { dbus } from "./dbusClient";
import { createLogger } from "./logger";

const logger = createLogger("SprintTabLegacy");

// Workspace root - the redhat-ai-workflow project directory
const WORKSPACE_ROOT = path.join(os.homedir(), "src", "redhat-ai-workflow");

// Tool requests file (YAML - MCP-managed memory, not daemon state)
const TOOL_REQUESTS_FILE = path.join(
  WORKSPACE_ROOT,
  "memory",
  "learned",
  "tool_requests.yaml"
);

// ==================== INTERFACES ====================

export interface SprintIssue {
  key: string;
  summary: string;
  storyPoints: number;
  priority: string;
  jiraStatus: string;
  assignee: string;
  approvalStatus:
    | "pending"
    | "approved"
    | "rejected"
    | "in_progress"
    | "completed"
    | "blocked"
    | "waiting";
  waitingReason?: string;
  priorityReasoning: string[];
  estimatedActions: string[];
  chatId?: string;
  timeline: TimelineEvent[];
  issueType?: string;
  created?: string;
  hasWorkLog?: boolean;  // True if background work was done (can open in Cursor)
  workLogPath?: string;  // Path to the work log file
  hasTrace?: boolean;    // True if execution trace exists
  tracePath?: string;    // Path to the trace file
}

// Execution trace interfaces
export interface ExecutionStep {
  step_id: string;
  name: string;
  timestamp: string;
  duration_ms?: number;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  decision?: string;
  reason?: string;
  error?: string;
  skill_name?: string;
  tool_name?: string;
  chat_id?: string;
}

export interface StateTransition {
  from_state: string;
  to_state: string;
  timestamp: string;
  trigger?: string;
  data?: Record<string, unknown>;
}

export interface ExecutionTrace {
  issue_key: string;
  workflow_type: string;
  execution_mode: string;
  started_at: string;
  completed_at?: string;
  current_state: string;
  state_description: string;
  steps: ExecutionStep[];
  transitions: StateTransition[];
  summary: {
    total_steps: number;
    successful_steps: number;
    failed_steps: number;
    total_duration_ms: number;
    total_transitions: number;
    final_state: string;
  };
}

export interface TimelineEvent {
  timestamp: string;
  action: string;
  description: string;
  chatLink?: string;
  jiraLink?: string;
}

export interface CompletedSprint {
  id: string;
  name: string;
  startDate: string;
  endDate: string;
  totalPoints: number;
  completedPoints: number;
  issues: SprintIssue[];
  timeline: TimelineEvent[];
  collapsed: boolean;
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
  nextSprint: SprintInfo | null;  // Upcoming sprint (may be empty)
  issues: SprintIssue[];
  automaticMode: boolean;  // If true, bot runs on schedule (Mon-Fri 9-5)
  manuallyStarted: boolean;  // If true, bot is running now (ignores schedule)
  backgroundTasks: boolean;  // If true, return to current chat after launching new task
  lastUpdated: string;
  processingIssue: string | null;
}

export interface ToolGapRequest {
  id: string;
  timestamp: string;
  suggested_tool_name: string;
  desired_action: string;
  context: string;
  suggested_args: Record<string, unknown>;
  workaround_used: string | null;
  requesting_skills: string[];
  issue_key: string | null;
  vote_count: number;
  status: "open" | "in_progress" | "implemented" | "rejected";
}

// Workflow configuration loaded from YAML via workspace state
export interface StatusMappingConfig {
  displayName: string;
  icon: string;
  color: string;
  description: string;
  jiraStatuses: string[];
  botCanWork: boolean;
  uiOrder: number;
  showApproveButtons?: boolean;
  botMonitors?: boolean;
}

export interface WorkflowConfig {
  statusMappings: Record<string, StatusMappingConfig>;
  mergeHoldPatterns: string[];
  spikeKeywords: string[];
  version: string;
}

// ==================== STATE LOADING ====================
//
// ARCHITECTURE: All sprint state is loaded via D-Bus from the Sprint daemon.
// Use dbus.sprint_getState() for sprint data, dbus.sprint_getHistory() for history,
// dbus.sprint_getTrace() for traces, and dbus.sprint_listTraces() for trace list.

/**
 * Load an execution trace for an issue via D-Bus.
 */
export async function loadExecutionTraceAsync(issueKey: string): Promise<ExecutionTrace | null> {
  try {
    const result = await dbus.sprint_getTrace(issueKey);
    if (result.success && result.data) {
      const data = result.data as any;
      return data.trace as ExecutionTrace;
    }
  } catch (e) {
    logger.error(`Failed to load trace for ${issueKey} via D-Bus`, e);
  }
  return null;
}

/**
 * @deprecated Use loadExecutionTraceAsync() instead.
 * Synchronous stub that returns null - traces must be loaded via D-Bus.
 */
export function loadExecutionTrace(issueKey: string): ExecutionTrace | null {
  logger.warn(`loadExecutionTrace(${issueKey}) is deprecated - use loadExecutionTraceAsync()`);
  return null;
}

/**
 * List all available traces via D-Bus.
 */
export async function listTracesAsync(): Promise<{ issueKey: string; state: string; startedAt: string }[]> {
  try {
    const result = await dbus.sprint_listTraces();
    if (result.success && result.data) {
      const data = result.data as any;
      const traces = data.traces || [];
      return traces.map((t: any) => ({
        issueKey: t.issue_key,
        state: t.state,
        startedAt: t.started_at,
      }));
    }
  } catch (e) {
    logger.error("Failed to list traces via D-Bus", e);
  }
  return [];
}

/**
 * @deprecated Use listTracesAsync() instead.
 * Synchronous stub that returns empty array - traces must be loaded via D-Bus.
 */
export function listTraces(): { issueKey: string; state: string; startedAt: string }[] {
  logger.warn("listTraces() is deprecated - use listTracesAsync()");
  return [];
}

/**
 * Load workflow configuration via D-Bus.
 * Falls back to defaults if D-Bus call fails.
 */
export async function loadWorkflowConfigAsync(): Promise<WorkflowConfig> {
  try {
    const result = await dbus.sprint_getState();
    if (result.success && result.data) {
      const data = result.data as any;
      const state = data.state || data;
      const config = state.workflowConfig as WorkflowConfig | undefined;
      if (config && config.statusMappings) {
        return config;
      }
    }
  } catch (e) {
    logger.error("Failed to load workflow config via D-Bus", e);
  }
  return getDefaultWorkflowConfig();
}

/**
 * @deprecated Use loadWorkflowConfigAsync() instead.
 * Returns default config - workflow config should be loaded via D-Bus.
 */
export function loadWorkflowConfig(): WorkflowConfig {
  logger.warn("loadWorkflowConfig() is deprecated - use loadWorkflowConfigAsync()");
  return getDefaultWorkflowConfig();
}

/**
 * Get default workflow configuration (fallback)
 */
function getDefaultWorkflowConfig(): WorkflowConfig {
  return {
    statusMappings: {
      not_ready: {
        displayName: "Not Ready",
        icon: "⚠️",
        color: "yellow",
        description: "Need refinement before bot can work",
        jiraStatuses: ["new", "refinement"],
        botCanWork: false,
        uiOrder: 1,
      },
      ready: {
        displayName: "Ready",
        icon: "📋",
        color: "blue",
        description: "Refined and ready for bot to implement",
        jiraStatuses: ["to do", "open", "backlog", "ready"],
        botCanWork: true,
        uiOrder: 2,
        showApproveButtons: true,
      },
      in_progress: {
        displayName: "In Progress",
        icon: "🔄",
        color: "blue",
        description: "Currently being worked on",
        jiraStatuses: ["in progress", "in development"],
        botCanWork: false,
        uiOrder: 3,
      },
      review: {
        displayName: "Review",
        icon: "👀",
        color: "purple",
        description: "Awaiting code review",
        jiraStatuses: ["review", "in review", "code review"],
        botCanWork: false,
        uiOrder: 4,
        botMonitors: true,
      },
      done: {
        displayName: "Done",
        icon: "✅",
        color: "green",
        description: "Completed",
        jiraStatuses: ["done", "closed", "resolved"],
        botCanWork: false,
        uiOrder: 5,
      },
    },
    mergeHoldPatterns: ["don't merge", "do not merge", "hold off", "wip"],
    spikeKeywords: ["research", "investigate", "spike", "poc"],
    version: "1.0",
  };
}

/**
 * @deprecated Use dbus.sprint_getState() from dbusClient.ts instead.
 * This function reads directly from the sprint state file.
 * Sprint state should be loaded via D-Bus from the Sprint daemon.
 */
export function loadSprintState(): SprintState {
  logger.warn("loadSprintState() is deprecated - use dbus.sprint_getState()");
  return getEmptySprintState();
}

/**
 * Load sprint history via D-Bus from Sprint daemon.
 */
export async function loadSprintHistoryAsync(): Promise<CompletedSprint[]> {
  try {
    const result = await dbus.sprint_getHistory();
    if (result.success && result.data) {
      const data = result.data as any;
      return data.history || [];
    }
  } catch (e) {
    logger.error("Failed to load sprint history via D-Bus", e);
  }
  return [];
}

/**
 * @deprecated Use loadSprintHistoryAsync() instead.
 * Returns empty array - sprint history should be loaded via D-Bus.
 */
export function loadSprintHistory(): CompletedSprint[] {
  logger.warn("loadSprintHistory() is deprecated - use loadSprintHistoryAsync()");
  return [];
}

/**
 * Load tool gap requests from YAML file
 */
export function loadToolGapRequests(): ToolGapRequest[] {
  try {
    if (fs.existsSync(TOOL_REQUESTS_FILE)) {
      const content = fs.readFileSync(TOOL_REQUESTS_FILE, "utf-8");
      // Simple YAML parsing for our structure
      const requests: ToolGapRequest[] = [];
      const lines = content.split("\n");
      let currentRequest: Partial<ToolGapRequest> | null = null;

      for (const line of lines) {
        if (line.startsWith("  - id:")) {
          if (currentRequest && currentRequest.id) {
            requests.push(currentRequest as ToolGapRequest);
          }
          currentRequest = {
            id: line.split(":")[1]?.trim() || "",
            vote_count: 1,
            status: "open",
            requesting_skills: [],
            suggested_args: {},
          };
        } else if (currentRequest && line.startsWith("    ")) {
          const [key, ...valueParts] = line.trim().split(":");
          const value = valueParts.join(":").trim();
          if (key && value) {
            (currentRequest as Record<string, unknown>)[key] = value;
          }
        }
      }
      if (currentRequest && currentRequest.id) {
        requests.push(currentRequest as ToolGapRequest);
      }
      return requests;
    }
  } catch (e) {
    logger.error("Failed to load tool gap requests", e);
  }
  return [];
}

// ==================== HELPER FUNCTIONS ====================

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getStatusColor(status: SprintIssue["approvalStatus"]): string {
  switch (status) {
    case "blocked":
      return "#ef4444"; // Red
    case "pending":
    case "waiting":
      return "#f59e0b"; // Yellow
    case "in_progress":
      return "#3b82f6"; // Blue
    case "completed":
      return "#10b981"; // Green
    case "rejected":
      return "#6b7280"; // Gray
    case "approved":
      return "#8b5cf6"; // Purple
    default:
      return "#6b7280"; // Gray
  }
}

function getStatusIcon(status: SprintIssue["approvalStatus"]): string {
  switch (status) {
    case "blocked":
      return "🔴";
    case "pending":
      return "🟡";
    case "waiting":
      return "⏳";
    case "in_progress":
      return "🔵";
    case "completed":
      return "🟢";
    case "rejected":
      return "⚪";
    case "approved":
      return "🟣";
    default:
      return "⚪";
  }
}

function getJiraStatusColor(status: string): string {
  const s = (status || "").toLowerCase();
  if (s.includes("done") || s.includes("closed") || s.includes("resolved") || s.includes("released")) {
    return "#10b981"; // Green
  }
  if (s.includes("review")) {
    return "#8b5cf6"; // Purple
  }
  if (s.includes("progress") || s.includes("development")) {
    return "#3b82f6"; // Blue
  }
  if (s.includes("blocked") || s.includes("impediment")) {
    return "#ef4444"; // Red
  }
  // New, To Do, Backlog, Refinement
  return "#f59e0b"; // Yellow/Orange
}

function getPriorityIcon(priority: string): string {
  switch (priority.toLowerCase()) {
    case "blocker":
      return "🚨";
    case "critical":
      return "🔥";
    case "major":
      return "⬆️";
    case "minor":
      return "⬇️";
    case "trivial":
      return "📝";
    default:
      return "➖";
  }
}

function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return timestamp;
  }
}

// ==================== CSS STYLES ====================
// NOTE: All CSS has been moved to src/webview/styles/unified.css
// The getSprintTabStyles() function has been removed.

// ==================== HTML GENERATION ====================

function renderIssueCard(issue: SprintIssue, jiraUrl: string, ignored: boolean = false): string {
  const priorityIcon = getPriorityIcon(issue.priority);
  const isMajor = issue.priority.toLowerCase() === "major" || issue.priority.toLowerCase() === "critical";

  const showApproveReject =
    !ignored && (issue.approvalStatus === "pending" || issue.approvalStatus === "waiting");
  const showAbort = !ignored && issue.approvalStatus === "in_progress";
  const showChat = !ignored && !!issue.chatId;
  // Show "Open in Cursor" for issues that have background work logs
  const showOpenInCursor = !ignored && issue.hasWorkLog && !issue.chatId;
  // Show "View Trace" for issues that have execution traces
  const showViewTrace = !ignored && issue.hasTrace;
  // Show "Start" button for issues that can be started immediately (pending, waiting, approved, blocked)
  const showStartIssue = !ignored && ["pending", "waiting", "approved", "blocked"].includes(issue.approvalStatus);

  // Always show Jira status in the badge (it's the actual workflow status)
  // The approval status only affects the action buttons
  const displayStatus = issue.jiraStatus || "Unknown";
  const ignoredClass = ignored ? "ignored" : "";

  // Get color based on approval status (for the icon indicator)
  const approvalColor = getStatusColor(issue.approvalStatus);
  const approvalIcon = getStatusIcon(issue.approvalStatus);

  // Get color for Jira status badge
  const jiraStatusColor = getJiraStatusColor(issue.jiraStatus);

  return `
    <div class="sprint-issue ${issue.approvalStatus} ${ignoredClass}" data-issue-key="${escapeHtml(issue.key)}">
      <div class="issue-col-key">
        <span class="approval-indicator" title="Bot status: ${issue.approvalStatus}">${approvalIcon}</span>
        <a class="issue-key ${ignoredClass}" href="${jiraUrl}/browse/${escapeHtml(issue.key)}" target="_blank">
          ${escapeHtml(issue.key)}
        </a>
        ${issue.hasWorkLog ? `<span class="work-log-indicator" title="Has background work log">📋</span>` : ""}
        ${issue.hasTrace ? `<span class="trace-indicator" title="Has execution trace">🔍</span>` : ""}
      </div>
      <div class="issue-col-summary">
        <div class="issue-summary ${ignoredClass}">${escapeHtml(issue.summary)}</div>
        ${issue.waitingReason ? `<div class="waiting-reason">⏳ ${escapeHtml(issue.waitingReason)}</div>` : ""}
        ${ignored ? `<div class="ignored-reason">🚫 User-managed</div>` : ""}
      </div>
      <div class="issue-col-points">
        <span class="issue-badge points ${ignoredClass} ${!issue.storyPoints ? "missing" : ""}">📊 ${issue.storyPoints || "?"} pts</span>
      </div>
      <div class="issue-col-priority">
        <span class="issue-badge priority ${isMajor ? "major" : ""} ${ignoredClass}">${priorityIcon} ${escapeHtml(issue.priority)}</span>
      </div>
      <div class="issue-col-status">
        <span class="issue-badge status ${ignoredClass} ${ignored ? "ignored" : ""}" data-status-color="${ignored ? "" : jiraStatusColor}">
          ${escapeHtml(displayStatus)}
        </span>
      </div>
      <div class="issue-col-actions">
        ${ignored ? `
          <span class="text-sm text-muted">No actions</span>
        ` : `
          <div class="issue-actions">
            ${showStartIssue ? `<button class="issue-btn start" data-action="startIssue" data-issue="${escapeHtml(issue.key)}" title="Start this issue immediately (bypasses all checks)">▶ Force Start</button>` : ""}
            ${issue.approvalStatus === "pending" || issue.approvalStatus === "waiting" ? `<button class="issue-btn approve" data-action="approve" data-issue="${escapeHtml(issue.key)}">✓ Approve</button>` : ""}
            ${issue.approvalStatus === "approved" ? `<button class="issue-btn reject" data-action="reject" data-issue="${escapeHtml(issue.key)}">✗ Unapprove</button>` : ""}
            ${showAbort ? `<button class="issue-btn abort" data-action="abort" data-issue="${escapeHtml(issue.key)}">⏹ Abort</button>` : ""}
            ${showChat ? `<button class="issue-btn chat" data-action="openChat" data-issue="${escapeHtml(issue.key)}" data-chat-id="${escapeHtml(issue.chatId || "")}">💬 Chat</button>` : ""}
            ${showOpenInCursor ? `<button class="issue-btn open-cursor" data-action="openInCursor" data-issue="${escapeHtml(issue.key)}" title="Open background work in Cursor for interactive continuation">📂 Open in Cursor</button>` : ""}
            ${showViewTrace ? `<button class="issue-btn trace" data-action="viewTrace" data-issue="${escapeHtml(issue.key)}" title="View execution trace and state machine">🔍 Trace</button>` : ""}
          </div>
        `}
      </div>
    </div>
  `;
}

function renderSprintHistory(history: CompletedSprint[]): string {
  if (history.length === 0) {
    return "";
  }

  return `
    <div class="sprint-history">
      <div class="sprint-history-header" data-action="toggleHistory">
        <span class="sprint-history-title">📚 Previous Sprints (${history.length})</span>
        <span>▶</span>
      </div>
      <div class="sprint-history-content" id="sprintHistoryContent">
        ${history
          .map(
            (sprint) => `
          <div class="past-sprint">
            <div class="past-sprint-header">
              <span class="past-sprint-name">${escapeHtml(sprint.name)}</span>
              <span class="past-sprint-dates">${formatTimestamp(sprint.startDate)} - ${formatTimestamp(sprint.endDate)}</span>
            </div>
            <div class="past-sprint-stats">
              <span>✅ ${sprint.completedPoints}/${sprint.totalPoints} points</span>
              <span>📋 ${sprint.issues.length} issues</span>
              <span>${Math.round((sprint.completedPoints / sprint.totalPoints) * 100)}% complete</span>
            </div>
          </div>
        `
          )
          .join("")}
      </div>
    </div>
  `;
}

function renderToolRequests(requests: ToolGapRequest[]): string {
  const openRequests = requests
    .filter((r) => r.status === "open")
    .sort((a, b) => b.vote_count - a.vote_count)
    .slice(0, 5);

  if (openRequests.length === 0) {
    return `
      <div class="tool-requests">
        <h3 class="section-title">🔧 Tool Requests</h3>
        <div class="empty-state p-24">
          <div>No tool gaps recorded yet.</div>
          <div class="text-base mt-8">
            When skills need tools that don't exist, they'll appear here.
          </div>
        </div>
      </div>
    `;
  }

  return `
    <div class="tool-requests">
      <h3 class="section-title">🔧 Most Requested Tools</h3>
      ${openRequests
        .map(
          (req) => `
        <div class="tool-request-card">
          <div class="tool-request-header">
            <span class="tool-request-name">${escapeHtml(req.suggested_tool_name)}</span>
            <span class="tool-request-votes">👍 ${req.vote_count} request${req.vote_count !== 1 ? "s" : ""}</span>
          </div>
          <div class="tool-request-action">${escapeHtml(req.desired_action)}</div>
          ${req.requesting_skills && req.requesting_skills.length > 0 ? `<div class="tool-request-skills">Used by: ${req.requesting_skills.map((s) => escapeHtml(s)).join(", ")}</div>` : ""}
        </div>
      `
        )
        .join("")}
    </div>
  `;
}

// ==================== TRACE VIEWER ====================

/**
 * Generate a Mermaid state diagram for an execution trace
 */
export function generateTraceMermaid(trace: ExecutionTrace): string {
  const lines: string[] = ["stateDiagram-v2"];

  // State descriptions
  const stateDescriptions: Record<string, string> = {
    idle: "Not started",
    loading: "Loading issue",
    analyzing: "Analyzing issue",
    classifying: "Determining type",
    checking_actionable: "Checking actionable",
    transitioning_jira: "Updating Jira",
    starting_work: "Creating branch",
    researching: "Searching code",
    building_prompt: "Building prompt",
    launching_chat: "Opening chat",
    implementing: "Making changes",
    documenting: "Documenting",
    creating_mr: "Creating MR",
    awaiting_review: "Awaiting review",
    merging: "Merging",
    closing: "Closing issue",
    blocked: "Blocked",
    completed: "Completed",
    failed: "Failed",
  };

  // Add state definitions
  lines.push("    %% State definitions");
  for (const [state, desc] of Object.entries(stateDescriptions)) {
    lines.push(`    ${state}: ${desc}`);
  }

  // Add transitions from the trace
  lines.push("");
  lines.push("    %% Actual transitions taken");

  // Collect visited states
  const visitedStates = new Set<string>(["idle"]);
  for (const trans of trace.transitions) {
    visitedStates.add(trans.to_state);
    lines.push(`    ${trans.from_state} --> ${trans.to_state}${trans.trigger ? `: ${trans.trigger}` : ""}`);
  }

  // Add start/end markers
  lines.push("");
  lines.push("    [*] --> idle");
  if (trace.current_state === "completed") {
    lines.push("    completed --> [*]");
  } else if (trace.current_state === "failed") {
    lines.push("    failed --> [*]");
  }

  // Style visited states
  lines.push("");
  lines.push("    %% Highlight path taken");
  for (const state of visitedStates) {
    if (state === trace.current_state) {
      if (state === "completed") {
        lines.push(`    style ${state} fill:#90EE90,stroke:#228B22,stroke-width:3px`);
      } else if (state === "failed" || state === "blocked") {
        lines.push(`    style ${state} fill:#FFB6C1,stroke:#DC143C,stroke-width:3px`);
      } else {
        lines.push(`    style ${state} fill:#FFD700,stroke:#FF8C00,stroke-width:3px`);
      }
    } else {
      lines.push(`    style ${state} fill:#98FB98,stroke:#32CD32`);
    }
  }

  return lines.join("\n");
}

/**
 * Render the execution trace timeline as HTML
 */
export function renderTraceTimeline(trace: ExecutionTrace): string {
  const steps = trace.steps;

  if (steps.length === 0) {
    return '<div class="trace-empty">No execution steps recorded</div>';
  }

  const stepHtml = steps.map((step, index) => {
    // Status icon and class
    let icon: string;
    let statusClass: string;
    switch (step.status) {
      case "success":
        icon = "✅";
        statusClass = "success";
        break;
      case "failed":
        icon = "❌";
        statusClass = "failed";
        break;
      case "running":
        icon = "🔄";
        statusClass = "running";
        break;
      case "skipped":
        icon = "⏭️";
        statusClass = "skipped";
        break;
      default:
        icon = "⏳";
        statusClass = "pending";
    }

    // Format timestamp
    let timeStr = "";
    try {
      const ts = new Date(step.timestamp);
      timeStr = ts.toLocaleTimeString();
    } catch {
      timeStr = step.timestamp.substring(11, 19);
    }

    // Build details
    const details: string[] = [];

    if (step.decision) {
      details.push(`<div class="trace-decision"><strong>Decision:</strong> ${escapeHtml(step.decision)}</div>`);
    }
    if (step.reason) {
      details.push(`<div class="trace-reason"><em>${escapeHtml(step.reason)}</em></div>`);
    }
    if (step.inputs && Object.keys(step.inputs).length > 0) {
      const inputStr = Object.entries(step.inputs)
        .slice(0, 3)
        .map(([k, v]) => `${k}=${JSON.stringify(v).substring(0, 50)}`)
        .join(", ");
      details.push(`<div class="trace-inputs">Inputs: ${escapeHtml(inputStr)}</div>`);
    }
    if (step.outputs && Object.keys(step.outputs).length > 0) {
      const outputStr = Object.entries(step.outputs)
        .slice(0, 3)
        .map(([k, v]) => `${k}=${JSON.stringify(v).substring(0, 50)}`)
        .join(", ");
      details.push(`<div class="trace-outputs">Outputs: ${escapeHtml(outputStr)}</div>`);
    }
    if (step.error) {
      details.push(`<div class="trace-error">Error: ${escapeHtml(step.error.substring(0, 200))}</div>`);
    }
    if (step.skill_name) {
      details.push(`<div class="trace-skill">Skill: ${escapeHtml(step.skill_name)}</div>`);
    }
    if (step.tool_name) {
      details.push(`<div class="trace-tool">Tool: ${escapeHtml(step.tool_name)}</div>`);
    }
    if (step.chat_id) {
      details.push(`<div class="trace-chat"><a href="#" data-action="openChat" data-chat-id="${escapeHtml(step.chat_id)}">Open Chat</a></div>`);
    }

    return `
      <div class="trace-step ${statusClass}">
        <div class="trace-marker">${icon}</div>
        <div class="trace-content">
          <div class="trace-header">
            <span class="trace-time">${timeStr}</span>
            <span class="trace-name">${escapeHtml(step.name)}</span>
            ${step.duration_ms ? `<span class="trace-duration">${step.duration_ms}ms</span>` : ""}
          </div>
          ${details.length > 0 ? `<div class="trace-details">${details.join("")}</div>` : ""}
        </div>
      </div>
    `;
  }).join("");

  return `
    <div class="trace-timeline">
      <div class="trace-summary">
        <span class="trace-summary-item">📊 ${trace.summary.total_steps} steps</span>
        <span class="trace-summary-item">✅ ${trace.summary.successful_steps} success</span>
        <span class="trace-summary-item">❌ ${trace.summary.failed_steps} failed</span>
        <span class="trace-summary-item">⏱️ ${Math.round(trace.summary.total_duration_ms / 1000)}s total</span>
        <span class="trace-summary-item">🔄 ${trace.summary.total_transitions} transitions</span>
      </div>
      <div class="trace-steps">
        ${stepHtml}
      </div>
    </div>
  `;
}

/**
 * Render the full trace viewer panel
 */
export function renderTraceViewer(issueKey: string): string {
  const trace = loadExecutionTrace(issueKey);

  if (!trace) {
    return `
      <div class="trace-viewer">
        <div class="trace-header">
          <h3>Execution Trace: ${escapeHtml(issueKey)}</h3>
          <button class="trace-close" data-action="closeTrace">✕</button>
        </div>
        <div class="trace-empty">
          <p>No execution trace found for this issue.</p>
          <p>Traces are created when the sprint bot processes an issue.</p>
        </div>
      </div>
    `;
  }

  const mermaid = generateTraceMermaid(trace);
  const timeline = renderTraceTimeline(trace);

  // State badge color
  let stateColor = "gray";
  if (trace.current_state === "completed") stateColor = "green";
  else if (trace.current_state === "failed" || trace.current_state === "blocked") stateColor = "red";
  else if (trace.current_state === "implementing" || trace.current_state === "awaiting_review") stateColor = "blue";

  return `
    <div class="trace-viewer">
      <div class="trace-header">
        <h3>Execution Trace: ${escapeHtml(issueKey)}</h3>
        <span class="trace-state state-${stateColor}">${escapeHtml(trace.current_state)}</span>
        <button class="trace-close" data-action="closeTrace">✕</button>
      </div>

      <div class="trace-info">
        <div class="trace-info-item">
          <strong>Type:</strong> ${escapeHtml(trace.workflow_type || "unknown")}
        </div>
        <div class="trace-info-item">
          <strong>Mode:</strong> ${escapeHtml(trace.execution_mode)}
        </div>
        <div class="trace-info-item">
          <strong>Started:</strong> ${formatTimestamp(trace.started_at)}
        </div>
        ${trace.completed_at ? `
          <div class="trace-info-item">
            <strong>Completed:</strong> ${formatTimestamp(trace.completed_at)}
          </div>
        ` : ""}
      </div>

      <div class="trace-tabs">
        <button class="trace-tab active" data-trace-tab="timeline">📋 Timeline</button>
        <button class="trace-tab" data-trace-tab="diagram">🔀 State Diagram</button>
      </div>

      <div class="trace-tab-content active" id="trace-timeline">
        ${timeline}
      </div>

      <div class="trace-tab-content" id="trace-diagram">
        <div class="trace-mermaid">
          <pre class="mermaid">${escapeHtml(mermaid)}</pre>
          <p class="trace-mermaid-note">
            <em>Note: Copy the diagram code above and paste into a Mermaid renderer to visualize.</em>
          </p>
        </div>
      </div>
    </div>
  `;
}

// ==================== MAIN EXPORT ====================

/**
 * Generate the Sprint tab content HTML
 */
export function getSprintTabContent(
  state: SprintState,
  history: CompletedSprint[],
  toolRequests: ToolGapRequest[],
  jiraUrl: string = "https://issues.redhat.com"
): string {
  // Note: All styles are now in unified.css

  // Calculate progress
  const totalPoints = state.currentSprint?.totalPoints || 0;
  const completedPoints = state.currentSprint?.completedPoints || 0;
  const progressPercent =
    totalPoints > 0 ? Math.round((completedPoints / totalPoints) * 100) : 0;

  // Load workflow configuration (from YAML via workspace state)
  const workflowConfig = loadWorkflowConfig();

  // Helper to check if a Jira status matches a workflow stage
  const matchesStage = (jiraStatus: string, stage: string): boolean => {
    const statusLower = (jiraStatus || "").toLowerCase();
    const stageConfig = workflowConfig.statusMappings[stage];
    if (!stageConfig) return false;
    return stageConfig.jiraStatuses.some(s => statusLower.includes(s.toLowerCase()));
  };

  // Split issues into sections based on Jira status (using workflow config)
  // Note: approvalStatus is the bot's internal tracking, jiraStatus is the actual Jira workflow status

  const notReadyIssues = state.issues.filter((i) => matchesStage(i.jiraStatus, "not_ready"));
  const readyIssues = state.issues.filter((i) => matchesStage(i.jiraStatus, "ready"));
  const inProgressIssues = state.issues.filter((i) => matchesStage(i.jiraStatus, "in_progress"));
  const reviewIssues = state.issues.filter((i) => matchesStage(i.jiraStatus, "review"));
  const doneIssues = state.issues.filter((i) => matchesStage(i.jiraStatus, "done"));

  // Get display config for each stage
  const notReadyConfig = workflowConfig.statusMappings.not_ready;
  const readyConfig = workflowConfig.statusMappings.ready;
  const inProgressConfig = workflowConfig.statusMappings.in_progress;
  const reviewConfig = workflowConfig.statusMappings.review;
  const doneConfig = workflowConfig.statusMappings.done;

  // For backward compatibility
  const pendingIssues = readyIssues;
  const blockedIssues = state.issues.filter(
    (i) => i.approvalStatus === "blocked"
  );

  return `
    <div class="sprint-container">
      <!-- Sprint Bot Header -->
      <div class="section mb-8">
        <h2 class="section-title m-0">🎯 Sprint Bot</h2>
      </div>

      <!-- Sprint Headers - Current and Next -->
      <div class="sprint-headers">
        <!-- Current Sprint -->
        <div class="sprint-header current">
          <div class="sprint-header-badge">CURRENT</div>
          <div class="sprint-header-content">
            <div class="sprint-title">🎯 ${state.currentSprint ? escapeHtml(state.currentSprint.name) : "No Active Sprint"}</div>
            ${state.currentSprint ? `
              <div class="sprint-dates">
                ${formatTimestamp(state.currentSprint.startDate)} - ${formatTimestamp(state.currentSprint.endDate)}
              </div>
              <div class="sprint-progress">
                <div class="sprint-progress-bar">
                  <div class="sprint-progress-fill" style="width: ${progressPercent}%;"></div>
                </div>
                <span class="sprint-progress-text">${completedPoints}/${totalPoints} pts (${progressPercent}%)</span>
              </div>
            ` : `
              <div class="sprint-dates">No active sprint loaded from Jira</div>
            `}
          </div>
        </div>

        <!-- Next Sprint -->
        <div class="sprint-header next">
          <div class="sprint-header-badge">NEXT</div>
          <div class="sprint-header-content">
            <div class="sprint-title">📅 ${state.nextSprint ? escapeHtml(state.nextSprint.name) : "No Upcoming Sprint"}</div>
            ${state.nextSprint ? `
              <div class="sprint-dates">
                ${formatTimestamp(state.nextSprint.startDate)} - ${formatTimestamp(state.nextSprint.endDate)}
              </div>
              <div class="sprint-stats">
                ${state.nextSprint.totalPoints} pts planned
              </div>
            ` : `
              <div class="sprint-dates">No upcoming sprint scheduled</div>
            `}
          </div>
        </div>
      </div>

      <!-- Bot Controls -->
      <div class="bot-controls-bar">
        <div class="bot-controls">
          <!-- Automatic Mode Toggle -->
          <div class="bot-toggle" title="When enabled, bot automatically processes approved issues during working hours (Mon-Fri 9am-5pm)">
            <div class="bot-toggle-switch ${state.automaticMode ? "active" : ""}" data-action="toggleAutomatic"></div>
            <span class="bot-toggle-label">Automatic</span>
          </div>

          <!-- Manual Start/Stop Button - Styled like Meetings tab -->
          ${state.manuallyStarted ? `
            <div class="bot-status-pill running ml-16">
              <span class="status-dot online"></span>
              <span>Running</span>
              <button class="btn btn-xs btn-danger" data-action="stopBot" title="Stop the bot immediately">Stop</button>
            </div>
          ` : `
            <button class="btn btn-sm btn-success ml-16" data-action="startBot" title="Start processing approved issues now (ignores schedule)">
              ▶ Start
            </button>
          `}

          <!-- Status Indicator -->
          <span class="bot-status-indicator ml-12 text-base text-muted">
            ${state.manuallyStarted
              ? '<span class="text-success">● Running (manual)</span>'
              : state.automaticMode
                ? '<span class="text-info">○ Scheduled (Mon-Fri 9-5)</span>'
                : '<span class="text-muted">○ Idle</span>'
            }
          </span>

          <div class="flex-spacer"></div>

          <!-- Background Toggle -->
          <div class="bot-toggle" title="When enabled, new issue chats open in background and you stay in your current chat">
            <div class="bot-toggle-switch ${state.backgroundTasks ? "active" : ""}" data-action="toggleBackgroundTasks"></div>
            <span class="bot-toggle-label">Background</span>
          </div>

          <!-- Jira Hygiene Button -->
          <button class="btn btn-sm btn-warning ml-16" data-action="runHygiene" title="Check for missing story points, descriptions, etc.">
            🧹 Jira Hygiene
          </button>
        </div>
      </div>

      <!-- Subtabs -->
      <div class="sprint-subtabs">
        <button class="sprint-subtab active" data-subtab="all">
          📋 All Issues (${state.issues.length})
        </button>
        <button class="sprint-subtab" data-subtab="tools">
          🔧 Tools
        </button>
      </div>

      <!-- All Issues Tab - Split into Not Ready, Ready, In Progress, Review, Done -->
      <!-- Status mappings loaded from workflow config (config.json -> sprint section) -->
      <div class="sprint-subtab-content active" id="subtab-all">
        <!-- Not Ready Section - Need refinement first -->
        <div class="sprint-section not-ready">
          <div class="sprint-section-header">
            <span class="sprint-section-title">${notReadyConfig?.icon || "⚠️"} ${notReadyConfig?.displayName || "Not Ready"} (${notReadyIssues.length})</span>
            <span class="sprint-section-subtitle">${notReadyConfig?.description || "Need refinement before bot can work"}</span>
          </div>
          ${
            notReadyIssues.length > 0
              ? `
            <div class="sprint-issues">
              ${notReadyIssues.map((issue) => renderIssueCard(issue, jiraUrl, false)).join("")}
            </div>
          `
              : `
            <div class="sprint-empty-inline">
              <span>No issues need refinement</span>
            </div>
          `
          }
        </div>

        <!-- Ready Section - Bot can work on these -->
        <div class="sprint-section ready">
          <div class="sprint-section-header">
            <span class="sprint-section-title">${readyConfig?.icon || "📋"} ${readyConfig?.displayName || "Ready"} (${readyIssues.length})</span>
            <span class="sprint-section-subtitle">${readyConfig?.description || "Refined and ready for bot to implement"}</span>
            ${readyIssues.length > 0 && readyConfig?.showApproveButtons !== false ? `
              <div class="section-actions">
                <button class="btn btn-xs btn-success" data-action="approveAll">✓ Approve All</button>
                <button class="btn btn-xs" data-action="rejectAll">✗ Unapprove All</button>
              </div>
            ` : ""}
          </div>
          ${
            readyIssues.length > 0
              ? `
            <div class="sprint-issues">
              ${readyIssues.map((issue) => renderIssueCard(issue, jiraUrl, false)).join("")}
            </div>
          `
              : `
            <div class="sprint-empty-inline">
              <span>No ready issues</span>
            </div>
          `
          }
        </div>

        <!-- In Progress Section - Currently being worked on -->
        <div class="sprint-section in-progress">
          <div class="sprint-section-header">
            <span class="sprint-section-title">${inProgressConfig?.icon || "🔄"} ${inProgressConfig?.displayName || "In Progress"} (${inProgressIssues.length})</span>
            <span class="sprint-section-subtitle">${inProgressConfig?.description || "Currently being worked on"}</span>
          </div>
          ${
            inProgressIssues.length > 0
              ? `
            <div class="sprint-issues">
              ${inProgressIssues.map((issue) => renderIssueCard(issue, jiraUrl, false)).join("")}
            </div>
          `
              : `
            <div class="sprint-empty-inline">
              <span>No issues in progress</span>
            </div>
          `
          }
        </div>

        <!-- Review Section - Awaiting code review -->
        <div class="sprint-section review">
          <div class="sprint-section-header">
            <span class="sprint-section-title">${reviewConfig?.icon || "👀"} ${reviewConfig?.displayName || "Review"} (${reviewIssues.length})</span>
            <span class="sprint-section-subtitle">${reviewConfig?.description || "Awaiting code review"}${reviewConfig?.botMonitors ? " - bot monitors for comments" : ""}</span>
          </div>
          ${
            reviewIssues.length > 0
              ? `
            <div class="sprint-issues">
              ${reviewIssues.map((issue) => renderIssueCard(issue, jiraUrl, false)).join("")}
            </div>
          `
              : `
            <div class="sprint-empty-inline">
              <span>No issues in review</span>
            </div>
          `
          }
        </div>

        <!-- Done Section - Completed -->
        <div class="sprint-section done">
          <div class="sprint-section-header">
            <span class="sprint-section-title">${doneConfig?.icon || "✅"} ${doneConfig?.displayName || "Done"} (${doneIssues.length})</span>
            <span class="sprint-section-subtitle">${doneConfig?.description || "Completed"}</span>
          </div>
          ${
            doneIssues.length > 0
              ? `
            <div class="sprint-issues">
              ${doneIssues.map((issue) => renderIssueCard(issue, jiraUrl, false)).join("")}
            </div>
          `
              : `
            <div class="sprint-empty-inline">
              <span>No completed issues yet</span>
            </div>
          `
          }
        </div>
      </div>

      <!-- Tools Tab -->
      <div class="sprint-subtab-content" id="subtab-tools">
        ${renderToolRequests(toolRequests)}
      </div>

      <!-- Sprint History -->
      ${renderSprintHistory(history)}
    </div>
  `;
}

/**
 * Get the JavaScript for the Sprint tab
 * This should be included in the main script section of the webview
 */
export function getSprintTabScript(): string {
  // Use centralized event delegation system - handlers survive content updates
  return `
    (function() {
      const sprintContainer = document.getElementById('sprint');

      console.log('[SprintTab] Initializing sprint tab with centralized event delegation...');

      // Register click handler - can be called multiple times safely
      TabEventDelegation.registerClickHandler('sprint', function(action, element, e) {
        e.stopPropagation();
        const issueKey = element.getAttribute('data-issue');
        const chatId = element.getAttribute('data-chat-id');

        console.log('[SprintTab] Action clicked:', { action, issueKey, chatId });

        // Handle toggle history specially
        if (action === 'toggleHistory') {
          const content = document.getElementById('sprintHistoryContent');
          if (content) {
            content.classList.toggle('expanded');
            const arrow = element.querySelector('span:last-child');
            if (arrow) {
              arrow.textContent = content.classList.contains('expanded') ? '▼' : '▶';
            }
          }
          return;
        }

        // All other actions go to backend
        if (vscode) {
          vscode.postMessage({
            command: 'sprintAction',
            action: action,
            issueKey: issueKey,
            chatId: chatId
          });
        }
      });

      // Additional click handling for non-data-action elements
      if (sprintContainer && !sprintContainer.dataset.extraClickInit) {
        sprintContainer.dataset.extraClickInit = 'true';

        sprintContainer.addEventListener('click', function(e) {
          const target = e.target;
          // Skip if already handled by data-action
          if (target.closest('[data-action]')) return;

          // Subtab switching
          const subtab = target.closest('.sprint-subtab');
          if (subtab) {
            const subtabId = subtab.getAttribute('data-subtab');

            // Update tab buttons
            sprintContainer.querySelectorAll('.sprint-subtab').forEach(t => t.classList.remove('active'));
            subtab.classList.add('active');

            // Update content
            sprintContainer.querySelectorAll('.sprint-subtab-content').forEach(c => c.classList.remove('active'));
            const content = document.getElementById('subtab-' + subtabId);
            if (content) content.classList.add('active');
            return;
          }

          // Trace tab switching (Timeline/Diagram)
          const traceTab = target.closest('.trace-tab');
          if (traceTab) {
            const traceTabId = traceTab.getAttribute('data-trace-tab');

            // Update trace tab buttons
            document.querySelectorAll('.trace-tab').forEach(t => t.classList.remove('active'));
            traceTab.classList.add('active');

            // Update trace tab content
            document.querySelectorAll('.trace-tab-content').forEach(c => c.classList.remove('active'));
            const traceContent = document.getElementById('trace-' + traceTabId);
            if (traceContent) traceContent.classList.add('active');
            console.log('[SprintTab] Trace tab switched to:', traceTabId);
            return;
          }

          // Timeline toggle
          const timelineToggle = target.closest('.timeline-toggle');
          if (timelineToggle) {
            const issueKey = timelineToggle.getAttribute('data-issue');
            const events = document.getElementById('timeline-' + issueKey);
            if (events) {
              events.classList.toggle('expanded');
              timelineToggle.textContent = events.classList.contains('expanded')
                ? '▼ ' + timelineToggle.textContent.substring(2)
                : '▶ ' + timelineToggle.textContent.substring(2);
            }
            return;
          }

          // Issue action buttons (legacy .issue-btn without data-action)
          const issueBtn = target.closest('.issue-btn');
          if (issueBtn) {
            e.stopPropagation();
            const action = issueBtn.getAttribute('data-action');
            const issueKey = issueBtn.getAttribute('data-issue');
            const chatId = issueBtn.getAttribute('data-chat-id');

            console.log('[SprintTab] Button clicked:', { action, issueKey, chatId });

            if (action && vscode) {
              vscode.postMessage({
                command: 'sprintAction',
                action: action,
                issueKey: issueKey,
                chatId: chatId
              });
            }
            return;
          }

          // Bot toggle switches
          const toggleSwitch = target.closest('.bot-toggle-switch');
          if (toggleSwitch) {
            const action = toggleSwitch.getAttribute('data-action');
            toggleSwitch.classList.toggle('active');

            if (action === 'toggleAutomatic' && vscode) {
              vscode.postMessage({
                command: 'sprintAction',
                action: 'toggleAutomatic',
                enabled: toggleSwitch.classList.contains('active')
              });
            } else if (action === 'toggleBackgroundTasks' && vscode) {
              vscode.postMessage({
                command: 'sprintAction',
                action: 'toggleBackgroundTasks',
                enabled: toggleSwitch.classList.contains('active')
              });
            }
            return;
          }
        });
      }

      console.log('[SprintTab] Sprint tab initialized with centralized event delegation');
    })();
  `;
}

/**
 * Get default empty state
 */
export function getEmptySprintState(): SprintState {
  return {
    currentSprint: null,
    nextSprint: null,
    issues: [],
    automaticMode: false,
    manuallyStarted: false,
    backgroundTasks: false,
    lastUpdated: new Date().toISOString(),
    processingIssue: null,
  };
}
