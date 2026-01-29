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
 * Data is read from the unified workspace_states.json file.
 * The UI only reads from cache - services (sprint bot, cron) maintain the cache.
 */

import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// Workspace root - the redhat-ai-workflow project directory
// This is where the memory/ folder lives
const WORKSPACE_ROOT = path.join(os.homedir(), "src", "redhat-ai-workflow");

// Sprint daemon's state file (each service owns its own file)
const SPRINT_STATE_FILE = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "sprint_state_v2.json"
);

// Legacy unified state file (fallback)
const WORKSPACE_STATE_FILE = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "workspace_states.json"
);

// Tool requests file (YAML, separate from JSON state)
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

/**
 * Load sprint state from sprint daemon's state file
 * Falls back to legacy unified file if new file doesn't exist
 */
function loadSprintStateFromFile(): Record<string, unknown> {
  // Try new per-service state file first
  try {
    if (fs.existsSync(SPRINT_STATE_FILE)) {
      const content = fs.readFileSync(SPRINT_STATE_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) {
    console.error("Failed to load sprint state file:", e);
  }

  // Fallback to legacy unified file
  try {
    if (fs.existsSync(WORKSPACE_STATE_FILE)) {
      const content = fs.readFileSync(WORKSPACE_STATE_FILE, "utf-8");
      const unified = JSON.parse(content);
      return unified.sprint || {};
    }
  } catch (e) {
    console.error("Failed to load legacy workspace state:", e);
  }
  return {};
}

/**
 * Load unified workspace state from file (for workflow config)
 */
function loadUnifiedState(): Record<string, unknown> {
  // Try sprint state file first (it includes workflowConfig)
  try {
    if (fs.existsSync(SPRINT_STATE_FILE)) {
      const content = fs.readFileSync(SPRINT_STATE_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) {
    // Fall through to legacy
  }

  // Fallback to legacy file
  try {
    if (fs.existsSync(WORKSPACE_STATE_FILE)) {
      const content = fs.readFileSync(WORKSPACE_STATE_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) {
    console.error("Failed to load workspace state:", e);
  }
  return {};
}

// Trace storage directory - consistent with other memory/state files
// Uses the workspace root's memory folder
const TRACES_DIR = path.join(WORKSPACE_ROOT, "memory", "state", "sprint_traces");

/**
 * Load an execution trace for an issue
 */
export function loadExecutionTrace(issueKey: string): ExecutionTrace | null {
  try {
    const tracePath = path.join(TRACES_DIR, `${issueKey}.yaml`);
    if (fs.existsSync(tracePath)) {
      const content = fs.readFileSync(tracePath, "utf-8");
      // Parse YAML - simple approach for our structure
      const yaml = require("js-yaml");
      return yaml.load(content) as ExecutionTrace;
    }
  } catch (e) {
    console.error(`Failed to load trace for ${issueKey}:`, e);
  }
  return null;
}

/**
 * List all available traces
 */
export function listTraces(): { issueKey: string; state: string; startedAt: string }[] {
  const traces: { issueKey: string; state: string; startedAt: string }[] = [];

  try {
    if (fs.existsSync(TRACES_DIR)) {
      const files = fs.readdirSync(TRACES_DIR).filter(f => f.endsWith(".yaml"));
      for (const file of files) {
        const issueKey = file.replace(".yaml", "");
        const trace = loadExecutionTrace(issueKey);
        if (trace) {
          traces.push({
            issueKey: trace.issue_key,
            state: trace.current_state,
            startedAt: trace.started_at,
          });
        }
      }
    }
  } catch (e) {
    console.error("Failed to list traces:", e);
  }

  return traces.sort((a, b) => b.startedAt.localeCompare(a.startedAt));
}

/**
 * Load workflow configuration from workspace state
 * Falls back to defaults if not available
 */
export function loadWorkflowConfig(): WorkflowConfig {
  try {
    const unified = loadUnifiedState();
    const config = unified.workflowConfig as WorkflowConfig | undefined;
    if (config && config.statusMappings) {
      return config;
    }
  } catch (e) {
    console.error("Failed to load workflow config:", e);
  }

  // Return default config if not available
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
 * Load sprint state from sprint daemon's state file
 */
export function loadSprintState(): SprintState {
  try {
    const sprint = loadSprintStateFromFile();
    if (sprint && Object.keys(sprint).length > 0) {
      // Handle backward compatibility with old 'botEnabled' field
      const automaticMode = sprint.automaticMode !== undefined
        ? sprint.automaticMode as boolean
        : (sprint.botEnabled as boolean | undefined) ?? false;

      return {
        currentSprint: sprint.currentSprint as SprintInfo | null ?? null,
        nextSprint: sprint.nextSprint as SprintInfo | null ?? null,
        issues: sprint.issues as SprintIssue[] ?? [],
        automaticMode,
        manuallyStarted: sprint.manuallyStarted as boolean ?? false,
        backgroundTasks: sprint.backgroundTasks as boolean ?? false,
        lastUpdated: sprint.lastUpdated as string ?? new Date().toISOString(),
        processingIssue: sprint.processingIssue as string | null ?? null,
      };
    }
  } catch (e) {
    console.error("Failed to load sprint state:", e);
  }

  // Return default state
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

/**
 * Load sprint history from unified workspace_states.json
 */
export function loadSprintHistory(): CompletedSprint[] {
  try {
    const unified = loadUnifiedState();
    const history = unified.sprint_history as CompletedSprint[] | undefined;
    if (history) {
      return history;
    }
  } catch (e) {
    console.error("Failed to load sprint history:", e);
  }
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
    console.error("Failed to load tool gap requests:", e);
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

function getSprintTabStyles(): string {
  return `
    /* Sprint Tab Styles */
    .sprint-container {
      padding: 0;
    }

    /* Sprint Headers - Current and Next side by side */
    .sprint-headers {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 16px;
    }

    .sprint-header {
      padding: 16px;
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
      position: relative;
    }

    .sprint-header.current {
      border-left: 4px solid #10b981;
    }

    .sprint-header.next {
      border-left: 4px solid #6366f1;
      opacity: 0.85;
    }

    .sprint-header-badge {
      position: absolute;
      top: 8px;
      right: 12px;
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.5px;
      padding: 2px 8px;
      border-radius: 4px;
      background: var(--bg-secondary);
      color: var(--text-muted);
    }

    .sprint-header.current .sprint-header-badge {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
    }

    .sprint-header.next .sprint-header-badge {
      background: rgba(99, 102, 241, 0.15);
      color: #6366f1;
    }

    .sprint-header-content {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .sprint-title {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .sprint-dates {
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .sprint-stats {
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    /* Bot Controls Bar */
    .bot-controls-bar {
      display: flex;
      justify-content: flex-end;
      margin-bottom: 16px;
      padding: 12px 16px;
      background: var(--card-bg);
      border-radius: 8px;
      border: 1px solid var(--border-color);
    }

    .sprint-meta {
      display: flex;
      gap: 16px;
      align-items: center;
    }

    .sprint-progress {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 4px;
    }

    .sprint-progress-bar {
      width: 100%;
      max-width: 150px;
      height: 6px;
      background: var(--bg-secondary);
      border-radius: 3px;
      overflow: hidden;
    }

    .sprint-progress-fill {
      height: 100%;
      background: linear-gradient(90deg, #10b981, #34d399);
      border-radius: 3px;
      transition: width 0.3s ease;
    }

    .sprint-progress-text {
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    /* Issue List - Table Layout */
    .sprint-issues {
      display: table;
      width: 100%;
      border-collapse: separate;
      border-spacing: 0 8px;
    }

    .sprint-issue {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 16px;
      transition: all 0.2s ease;
    }

    .sprint-issue:hover {
      border-color: var(--accent-color);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    }

    .sprint-issue.blocked {
      border-left: 4px solid #ef4444;
    }

    .sprint-issue.waiting {
      border-left: 4px solid #f59e0b;
    }

    .sprint-issue.in_progress {
      border-left: 4px solid #3b82f6;
    }

    .sprint-issue.completed {
      border-left: 4px solid #10b981;
    }

    /* Issue Table Layout */
    .sprint-issues-table {
      display: table;
      width: 100%;
      border-collapse: separate;
      border-spacing: 0 8px;
    }

    .sprint-issue {
      display: table-row;
    }

    .sprint-issue > div {
      display: table-cell;
      vertical-align: middle;
      padding: 12px 8px;
      background: var(--card-bg);
      border-top: 1px solid var(--border-color);
      border-bottom: 1px solid var(--border-color);
    }

    .sprint-issue > div:first-child {
      border-left: 4px solid var(--border-color);
      border-top-left-radius: 8px;
      border-bottom-left-radius: 8px;
      padding-left: 12px;
    }

    .sprint-issue > div:last-child {
      border-right: 1px solid var(--border-color);
      border-top-right-radius: 8px;
      border-bottom-right-radius: 8px;
      padding-right: 12px;
    }

    /* Status color borders */
    .sprint-issue.pending > div:first-child { border-left-color: #f59e0b; }
    .sprint-issue.approved > div:first-child { border-left-color: #3b82f6; }
    .sprint-issue.rejected > div:first-child { border-left-color: #6b7280; }
    .sprint-issue.blocked > div:first-child { border-left-color: #ef4444; }
    .sprint-issue.waiting > div:first-child { border-left-color: #f59e0b; }
    .sprint-issue.in_progress > div:first-child { border-left-color: #3b82f6; }
    .sprint-issue.completed > div:first-child { border-left-color: #10b981; }

    .issue-col-key {
      width: 120px;
      white-space: nowrap;
    }

    .issue-col-summary {
      min-width: 200px;
    }

    .issue-col-points {
      width: 70px;
      text-align: center;
    }

    .issue-col-priority {
      width: 90px;
      text-align: center;
    }

    .issue-col-status {
      width: 100px;
      text-align: center;
    }

    .issue-col-actions {
      width: 220px;
      text-align: right;
      white-space: nowrap;
    }

    .issue-key {
      font-weight: 600;
      color: var(--accent-color);
      cursor: pointer;
      text-decoration: none;
      font-size: 0.9rem;
    }

    .issue-key:hover {
      text-decoration: underline;
    }

    .issue-summary {
      font-size: 0.9rem;
      color: var(--text-primary);
      line-height: 1.3;
    }

    .issue-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 4px;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 0.75rem;
      font-weight: 500;
      background: var(--bg-secondary);
      color: var(--text-secondary);
    }

    .issue-badge.points {
      background: rgba(139, 92, 246, 0.15);
      color: #a78bfa;
    }

    .issue-badge.points.missing {
      background: rgba(245, 158, 11, 0.2);
      color: #f59e0b;
      border: 1px dashed #f59e0b;
    }

    .issue-badge.priority {
      background: rgba(239, 68, 68, 0.15);
      color: #f87171;
    }

    .issue-badge.priority.major {
      background: rgba(239, 68, 68, 0.2);
      color: #ef4444;
    }

    .issue-badge.status {
      background: rgba(59, 130, 246, 0.15);
      color: #60a5fa;
    }

    /* Issue Actions */
    .issue-actions {
      display: inline-flex;
      gap: 6px;
    }

    .issue-btn {
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 0.8rem;
      font-weight: 500;
      cursor: pointer;
      border: none;
      transition: all 0.2s ease;
    }

    .issue-btn.approve {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
    }

    .issue-btn.approve:hover {
      background: rgba(16, 185, 129, 0.25);
    }

    .issue-btn.reject {
      background: rgba(107, 114, 128, 0.15);
      color: #9ca3af;
    }

    .issue-btn.reject:hover {
      background: rgba(107, 114, 128, 0.25);
    }

    .issue-btn.abort {
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
    }

    .issue-btn.abort:hover {
      background: rgba(239, 68, 68, 0.25);
    }

    .issue-btn.chat {
      background: rgba(59, 130, 246, 0.15);
      color: #3b82f6;
    }

    .issue-btn.chat:hover {
      background: rgba(59, 130, 246, 0.25);
    }

    .issue-btn.open-cursor {
      background: rgba(168, 85, 247, 0.15);
      color: #a855f7;
    }

    .issue-btn.open-cursor:hover {
      background: rgba(168, 85, 247, 0.25);
    }

    .issue-btn.timeline {
      background: rgba(139, 92, 246, 0.15);
      color: #a78bfa;
    }

    .issue-btn.timeline:hover {
      background: rgba(139, 92, 246, 0.25);
    }

    .work-log-indicator {
      margin-left: 4px;
      font-size: 0.75rem;
      opacity: 0.8;
      cursor: help;
    }

    .approval-indicator {
      margin-right: 4px;
      font-size: 0.875rem;
      cursor: help;
    }

    .issue-btn.hygiene {
      background: rgba(245, 158, 11, 0.15);
      color: #f59e0b;
    }

    .issue-btn.hygiene:hover {
      background: rgba(245, 158, 11, 0.25);
    }

    .issue-btn.start {
      background: rgba(16, 185, 129, 0.15);
      color: #10b981;
    }

    .issue-btn.start:hover {
      background: rgba(16, 185, 129, 0.25);
    }

    .issue-btn.stop {
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
    }

    .issue-btn.stop:hover {
      background: rgba(239, 68, 68, 0.25);
    }

    /* Section actions (Approve All / Reject All) */
    .section-actions {
      display: flex;
      gap: 8px;
    }

    /* Priority Reasoning */
    .priority-reasoning {
      margin-top: 8px;
      padding: 8px 12px;
      background: var(--bg-secondary);
      border-radius: 8px;
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .priority-reasoning-title {
      font-weight: 600;
      margin-bottom: 4px;
      color: var(--text-secondary);
    }

    .priority-reasoning-list {
      list-style: none;
      padding: 0;
      margin: 0;
    }

    .priority-reasoning-list li {
      padding: 2px 0;
    }

    /* Timeline */
    .issue-timeline {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--border-color);
    }

    .timeline-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
      font-size: 0.85rem;
      color: var(--text-muted);
    }

    .timeline-toggle:hover {
      color: var(--text-primary);
    }

    .timeline-events {
      margin-top: 8px;
      display: none;
    }

    .timeline-events.expanded {
      display: block;
    }

    .timeline-event {
      display: flex;
      gap: 12px;
      padding: 8px 0;
      border-left: 2px solid var(--border-color);
      padding-left: 12px;
      margin-left: 4px;
    }

    .timeline-event-time {
      font-size: 0.75rem;
      color: var(--text-muted);
      min-width: 80px;
    }

    .timeline-event-content {
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    .timeline-event-link {
      color: var(--accent-color);
      text-decoration: none;
    }

    .timeline-event-link:hover {
      text-decoration: underline;
    }

    /* Sprint History */
    .sprint-history {
      margin-top: 24px;
    }

    .sprint-history-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: pointer;
      padding: 12px 16px;
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
    }

    .sprint-history-header:hover {
      background: var(--bg-secondary);
    }

    .sprint-history-title {
      font-weight: 600;
      color: var(--text-primary);
    }

    .sprint-history-content {
      display: none;
      margin-top: 12px;
    }

    .sprint-history-content.expanded {
      display: block;
    }

    .past-sprint {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 8px;
    }

    .past-sprint-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .past-sprint-name {
      font-weight: 500;
      color: var(--text-primary);
    }

    .past-sprint-dates {
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .past-sprint-stats {
      display: flex;
      gap: 16px;
      margin-top: 8px;
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    /* Trace Viewer Styles */
    .trace-viewer {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }

    .trace-viewer .trace-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border-color);
    }

    .trace-viewer .trace-header h3 {
      margin: 0;
      flex: 1;
      font-size: 1.1rem;
    }

    .trace-state {
      padding: 4px 12px;
      border-radius: 12px;
      font-size: 0.75rem;
      font-weight: 600;
      color: white;
      text-transform: uppercase;
    }

    .trace-close {
      background: none;
      border: none;
      font-size: 1.2rem;
      cursor: pointer;
      color: var(--text-muted);
      padding: 4px 8px;
    }

    .trace-close:hover {
      color: var(--text-primary);
    }

    .trace-info {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 16px;
      font-size: 0.85rem;
    }

    .trace-info-item {
      color: var(--text-secondary);
    }

    .trace-info-item strong {
      color: var(--text-primary);
    }

    .trace-tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
    }

    .trace-tab {
      padding: 8px 16px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    .trace-tab:hover {
      background: var(--bg-tertiary);
    }

    .trace-tab.active {
      background: var(--accent-color);
      color: white;
      border-color: var(--accent-color);
    }

    .trace-tab-content {
      display: none;
    }

    .trace-tab-content.active {
      display: block;
    }

    .trace-timeline {
      max-height: 500px;
      overflow-y: auto;
    }

    .trace-summary {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      padding: 12px;
      background: var(--bg-secondary);
      border-radius: 8px;
      margin-bottom: 16px;
      font-size: 0.85rem;
    }

    .trace-summary-item {
      color: var(--text-secondary);
    }

    .trace-steps {
      position: relative;
      padding-left: 24px;
    }

    .trace-steps::before {
      content: '';
      position: absolute;
      left: 8px;
      top: 0;
      bottom: 0;
      width: 2px;
      background: var(--border-color);
    }

    .trace-step {
      display: flex;
      gap: 12px;
      margin-bottom: 12px;
      position: relative;
    }

    .trace-marker {
      position: absolute;
      left: -24px;
      width: 20px;
      height: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.9rem;
      background: var(--card-bg);
      z-index: 1;
    }

    .trace-content {
      flex: 1;
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 10px 14px;
      border-left: 3px solid var(--border-color);
    }

    .trace-step.success .trace-content {
      border-left-color: #10b981;
    }

    .trace-step.failed .trace-content {
      border-left-color: #ef4444;
    }

    .trace-step.running .trace-content {
      border-left-color: #f59e0b;
    }

    .trace-step.skipped .trace-content {
      border-left-color: #6b7280;
      opacity: 0.7;
    }

    .trace-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 6px;
    }

    .trace-time {
      font-size: 0.75rem;
      color: var(--text-muted);
      font-family: monospace;
    }

    .trace-name {
      font-weight: 500;
      color: var(--text-primary);
    }

    .trace-duration {
      font-size: 0.75rem;
      color: var(--text-muted);
      background: var(--bg-tertiary);
      padding: 2px 6px;
      border-radius: 4px;
    }

    .trace-details {
      font-size: 0.8rem;
      color: var(--text-secondary);
    }

    .trace-decision {
      margin-bottom: 4px;
    }

    .trace-reason {
      color: var(--text-muted);
      margin-bottom: 4px;
    }

    .trace-inputs, .trace-outputs {
      font-family: monospace;
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-bottom: 2px;
    }

    .trace-error {
      color: #ef4444;
      margin-top: 4px;
    }

    .trace-skill, .trace-tool {
      font-size: 0.75rem;
      color: var(--accent-color);
    }

    .trace-chat a {
      color: var(--accent-color);
      text-decoration: none;
    }

    .trace-chat a:hover {
      text-decoration: underline;
    }

    .trace-mermaid {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 16px;
    }

    .trace-mermaid pre {
      margin: 0;
      white-space: pre-wrap;
      font-size: 0.8rem;
      font-family: monospace;
      color: var(--text-secondary);
    }

    .trace-mermaid-note {
      margin-top: 12px;
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .trace-empty {
      text-align: center;
      padding: 32px;
      color: var(--text-muted);
    }

    /* View Trace button on issue cards */
    .issue-btn.trace {
      background: rgba(139, 92, 246, 0.15);
      color: #8b5cf6;
    }

    .issue-btn.trace:hover {
      background: rgba(139, 92, 246, 0.25);
    }

    /* Tool Requests Section */
    .tool-requests {
      margin-top: 24px;
    }

    .tool-request-card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 8px;
    }

    .tool-request-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .tool-request-name {
      font-family: monospace;
      font-weight: 600;
      color: var(--accent-color);
    }

    .tool-request-votes {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .tool-request-action {
      font-size: 0.85rem;
      color: var(--text-secondary);
      margin-top: 4px;
    }

    .tool-request-skills {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 4px;
    }

    /* Empty State */
    .sprint-empty {
      text-align: center;
      padding: 48px 24px;
      color: var(--text-muted);
    }

    .sprint-empty-icon {
      font-size: 3rem;
      margin-bottom: 16px;
    }

    .sprint-empty-title {
      font-size: 1.1rem;
      font-weight: 500;
      margin-bottom: 8px;
      color: var(--text-secondary);
    }

    .sprint-empty-text {
      font-size: 0.9rem;
    }

    /* Bot Controls */
    .bot-controls {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .bot-toggle {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .bot-toggle-switch {
      position: relative;
      width: 44px;
      height: 24px;
      background: var(--bg-secondary);
      border-radius: 12px;
      cursor: pointer;
      transition: background 0.2s ease;
    }

    .bot-toggle-switch.active {
      background: #10b981;
    }

    .bot-toggle-switch::after {
      content: '';
      position: absolute;
      top: 2px;
      left: 2px;
      width: 20px;
      height: 20px;
      background: white;
      border-radius: 50%;
      transition: transform 0.2s ease;
    }

    .bot-toggle-switch.active::after {
      transform: translateX(20px);
    }

    .bot-toggle-label {
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    /* Subtabs */
    .sprint-subtabs {
      display: flex;
      gap: 4px;
      margin-bottom: 16px;
      padding: 4px;
      background: var(--bg-secondary);
      border-radius: 8px;
    }

    .sprint-subtab {
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      border: none;
      background: transparent;
      color: var(--text-muted);
      transition: all 0.2s ease;
    }

    .sprint-subtab:hover {
      color: var(--text-primary);
    }

    .sprint-subtab.active {
      background: var(--card-bg);
      color: var(--text-primary);
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }

    .sprint-subtab-content {
      display: none;
    }

    .sprint-subtab-content.active {
      display: block;
    }

    /* Waiting reason tooltip */
    .waiting-reason {
      font-size: 0.8rem;
      color: #f59e0b;
      margin-top: 4px;
      font-style: italic;
    }

    /* Sprint Sections */
    .sprint-section {
      margin-bottom: 24px;
    }

    .sprint-section-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
      padding: 12px 16px;
      background: var(--card-bg);
      border-radius: 8px;
      border: 1px solid var(--border-color);
    }

    .sprint-section-title {
      font-weight: 600;
      font-size: 1rem;
      color: var(--text-primary);
    }

    .sprint-section-subtitle {
      font-size: 0.8rem;
      color: var(--text-muted);
      flex: 1;
    }

    /* Section variants */
    .sprint-section.ready .sprint-section-header {
      border-left: 3px solid #10b981;
    }

    .sprint-section.ready .sprint-section-title {
      color: #10b981;
    }

    .sprint-section.in-progress .sprint-section-header {
      border-left: 3px solid #3b82f6;
      background: rgba(59, 130, 246, 0.05);
    }

    .sprint-section.in-progress .sprint-section-title {
      color: #3b82f6;
    }

    .sprint-section.review .sprint-section-header {
      border-left: 3px solid #8b5cf6;
      background: rgba(139, 92, 246, 0.05);
    }

    .sprint-section.review .sprint-section-title {
      color: #8b5cf6;
    }

    .sprint-section.done .sprint-section-header {
      border-left: 3px solid #6b7280;
      background: var(--bg-secondary);
    }

    .sprint-section.done .sprint-section-title {
      color: var(--text-muted);
    }

    .sprint-section.not-ready .sprint-section-header {
      border-left: 3px solid #f59e0b;
      background: rgba(245, 158, 11, 0.05);
    }

    .sprint-section.not-ready .sprint-section-title {
      color: #f59e0b;
    }

    .sprint-empty-inline {
      padding: 16px;
      text-align: center;
      color: var(--text-muted);
      font-size: 0.85rem;
      background: var(--bg-secondary);
      border-radius: 8px;
    }

    /* Ignored/Not Actionable issues styling */
    .ignored-reason {
      font-size: 0.75rem;
      color: #6b7280;
      margin-top: 4px;
      font-style: italic;
    }

    .sprint-issue.ignored > div {
      opacity: 0.7;
    }

    .sprint-issue.ignored > div:first-child {
      border-left-color: #6b7280 !important;
    }

    .issue-key.ignored,
    .issue-summary.ignored {
      color: var(--text-muted) !important;
    }

    .issue-badge.ignored {
      opacity: 0.6;
    }
  `;
}

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
        <span class="issue-badge status ${ignoredClass}" style="background: ${ignored ? "#6b728020" : jiraStatusColor + "20"}; color: ${ignored ? "#6b7280" : jiraStatusColor};">
          ${escapeHtml(displayStatus)}
        </span>
      </div>
      <div class="issue-col-actions">
        ${ignored ? `
          <span style="font-size: 0.75rem; color: var(--text-muted);">No actions</span>
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
        <div class="sprint-empty" style="padding: 24px;">
          <div>No tool gaps recorded yet.</div>
          <div style="font-size: 0.85rem; margin-top: 8px;">
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
        <span class="trace-state" style="background-color: ${stateColor};">${escapeHtml(trace.current_state)}</span>
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
  const styles = getSprintTabStyles();

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
    <style>${styles}</style>

    <div class="sprint-container">
      <!-- Sprint Bot Header with Controls -->
      <div class="section" style="margin-bottom: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <h2 class="section-title" style="margin: 0;">🏃 Sprint Bot</h2>
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-ghost btn-small" data-action="serviceStart" data-service="sprint">▶ Start</button>
            <button class="btn btn-ghost btn-small" data-action="serviceStop" data-service="sprint">⏹ Stop</button>
            <button class="btn btn-ghost btn-small" data-action="serviceLogs" data-service="sprint">📋 Logs</button>
          </div>
        </div>
      </div>

      <!-- Sprint Headers - Current and Next -->
      <div class="sprint-headers">
        <!-- Current Sprint -->
        <div class="sprint-header current">
          <div class="sprint-header-badge">CURRENT</div>
          <div class="sprint-header-content">
            <div class="sprint-title">🏃 ${state.currentSprint ? escapeHtml(state.currentSprint.name) : "No Active Sprint"}</div>
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

          <!-- Manual Start/Stop Button -->
          <button class="issue-btn ${state.manuallyStarted ? "abort" : "approve"}" style="margin-left: 16px;" data-action="${state.manuallyStarted ? "stopBot" : "startBot"}" title="${state.manuallyStarted ? "Stop the bot immediately" : "Start processing approved issues now (ignores schedule)"}">
            ${state.manuallyStarted ? "⏹ Stop" : "▶ Start"}
          </button>

          <!-- Status Indicator -->
          <span class="bot-status-indicator" style="margin-left: 12px; font-size: 0.85rem; color: var(--text-muted);">
            ${state.manuallyStarted
              ? '<span style="color: #10b981;">● Running (manual)</span>'
              : state.automaticMode
                ? '<span style="color: #3b82f6;">○ Scheduled (Mon-Fri 9-5)</span>'
                : '<span style="color: #6b7280;">○ Idle</span>'
            }
          </span>

          <div style="flex: 1;"></div>

          <!-- Background Toggle -->
          <div class="bot-toggle" title="When enabled, new issue chats open in background and you stay in your current chat">
            <div class="bot-toggle-switch ${state.backgroundTasks ? "active" : ""}" data-action="toggleBackgroundTasks"></div>
            <span class="bot-toggle-label">Background</span>
          </div>

          <!-- Jira Hygiene Button -->
          <button class="issue-btn hygiene" style="margin-left: 16px;" data-action="runHygiene" title="Check for missing story points, descriptions, etc.">
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
                <button class="issue-btn approve" data-action="approveAll">✓ Approve All</button>
                <button class="issue-btn reject" data-action="rejectAll">✗ Unapprove All</button>
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
  return `
    // Sprint Tab Functions
    function initSprintTab() {
      console.log('[SprintTab] Initializing sprint tab...');

      // Subtab switching
      document.querySelectorAll('.sprint-subtab').forEach(tab => {
        tab.addEventListener('click', function() {
          const subtab = this.getAttribute('data-subtab');

          // Update tab buttons
          document.querySelectorAll('.sprint-subtab').forEach(t => t.classList.remove('active'));
          this.classList.add('active');

          // Update content
          document.querySelectorAll('.sprint-subtab-content').forEach(c => c.classList.remove('active'));
          document.getElementById('subtab-' + subtab)?.classList.add('active');
        });
      });

      // Timeline toggle
      document.querySelectorAll('.timeline-toggle').forEach(toggle => {
        toggle.addEventListener('click', function() {
          const issueKey = this.getAttribute('data-issue');
          const events = document.getElementById('timeline-' + issueKey);
          if (events) {
            events.classList.toggle('expanded');
            this.textContent = events.classList.contains('expanded')
              ? '▼ ' + this.textContent.substring(2)
              : '▶ ' + this.textContent.substring(2);
          }
        });
      });

      // History toggle
      document.querySelector('[data-action="toggleHistory"]')?.addEventListener('click', function() {
        const content = document.getElementById('sprintHistoryContent');
        if (content) {
          content.classList.toggle('expanded');
          const arrow = this.querySelector('span:last-child');
          if (arrow) {
            arrow.textContent = content.classList.contains('expanded') ? '▼' : '▶';
          }
        }
      });

      // Issue actions (including Test Chat button)
      document.querySelectorAll('.sprint-container .issue-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
          e.stopPropagation();
          const action = this.getAttribute('data-action');
          const issueKey = this.getAttribute('data-issue');
          const chatId = this.getAttribute('data-chat-id');

          console.log('[SprintTab] Button clicked:', { action, issueKey, chatId });

          if (action && vscode) {
            console.log('[SprintTab] Posting message:', { command: 'sprintAction', action });
            vscode.postMessage({
              command: 'sprintAction',
              action: action,
              issueKey: issueKey,
              chatId: chatId
            });
          }
        });
      });

      // Automatic mode toggle
      document.querySelector('.bot-toggle-switch[data-action="toggleAutomatic"]')?.addEventListener('click', function() {
        this.classList.toggle('active');
        if (vscode) {
          vscode.postMessage({
            command: 'sprintAction',
            action: 'toggleAutomatic',
            enabled: this.classList.contains('active')
          });
        }
      });

      // Background tasks toggle
      document.querySelector('.bot-toggle-switch[data-action="toggleBackgroundTasks"]')?.addEventListener('click', function() {
        this.classList.toggle('active');
        if (vscode) {
          vscode.postMessage({
            command: 'sprintAction',
            action: 'toggleBackgroundTasks',
            enabled: this.classList.contains('active')
          });
        }
      });

      console.log('[SprintTab] Sprint tab initialized');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initSprintTab);
    } else {
      initSprintTab();
    }
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
