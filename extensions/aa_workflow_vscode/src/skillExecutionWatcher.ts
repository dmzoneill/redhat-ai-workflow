/**
 * Skill Execution Watcher
 *
 * Watches for skill execution events from the MCP server and updates
 * the flowchart panel in real-time.
 *
 * The MCP server writes execution state to:
 *   ~/.config/aa-workflow/skill_execution.json
 *
 * This file watches that file and dispatches events to the flowchart panel.
 *
 * Supports multiple concurrent skill executions:
 * - Tracks all running executions from different sources (chat, cron, etc.)
 * - Shows toast notifications when skills start (instead of auto-switching tabs)
 * - Provides list of running executions for the Running Skills panel
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { getCommandCenterPanel } from "./commandCenter";
import { createLogger } from "./logger";

const logger = createLogger("SkillWatcher");

// ============================================================================
// File Locking Utilities
// ============================================================================

const LOCK_TIMEOUT_MS = 5000; // Max time to wait for lock
const LOCK_RETRY_INTERVAL_MS = 50; // How often to retry acquiring lock
const LOCK_STALE_MS = 10000; // Consider lock stale if older than this

/**
 * Acquire a file lock using a lockfile.
 * Returns true if lock acquired, false if timeout.
 */
async function acquireFileLock(filePath: string): Promise<boolean> {
  const lockPath = filePath + ".lock";
  const startTime = Date.now();

  while (Date.now() - startTime < LOCK_TIMEOUT_MS) {
    try {
      // Check if lock exists and is stale
      if (fs.existsSync(lockPath)) {
        const stat = fs.statSync(lockPath);
        const lockAge = Date.now() - stat.mtimeMs;
        if (lockAge > LOCK_STALE_MS) {
          // Lock is stale, remove it
          try {
            fs.unlinkSync(lockPath);
            logger.log(`Removed stale lock file (age: ${lockAge}ms)`);
          } catch {
            // Another process may have removed it
          }
        }
      }

      // Try to create lock file exclusively
      // O_CREAT | O_EXCL ensures atomic create-if-not-exists
      const fd = fs.openSync(lockPath, fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY);
      // Write our PID for debugging
      fs.writeSync(fd, `${process.pid}\n${Date.now()}`);
      fs.closeSync(fd);
      return true;
    } catch (e: any) {
      if (e.code === "EEXIST") {
        // Lock exists, wait and retry
        await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_INTERVAL_MS));
      } else {
        // Unexpected error
        logger.error("Error acquiring lock", e);
        return false;
      }
    }
  }

  logger.warn("Timeout waiting for file lock");
  return false;
}

/**
 * Release a file lock.
 */
function releaseFileLock(filePath: string): void {
  const lockPath = filePath + ".lock";
  try {
    fs.unlinkSync(lockPath);
  } catch (e: any) {
    if (e.code !== "ENOENT") {
      logger.error("Error releasing lock", e);
    }
  }
}

/**
 * Execute a function with file lock protection.
 * Ensures exclusive access to the file during the operation.
 */
async function withFileLock<T>(filePath: string, fn: () => T): Promise<T | null> {
  const acquired = await acquireFileLock(filePath);
  if (!acquired) {
    logger.error("Failed to acquire file lock, skipping operation");
    return null;
  }

  try {
    return fn();
  } finally {
    releaseFileLock(filePath);
  }
}

// ============================================================================
// Types
// ============================================================================

export interface SkillExecutionEvent {
  type:
    | "skill_start"
    | "step_start"
    | "step_complete"
    | "step_failed"
    | "step_skipped"
    | "skill_complete"
    | "memory_read"
    | "memory_write"
    | "auto_heal"
    | "retry"
    | "semantic_search"
    | "remediation_step";
  timestamp: string;
  skillName: string;
  executionId?: string;
  stepIndex?: number;
  stepName?: string;
  data?: {
    duration?: number;
    result?: string;
    error?: string;
    memoryKey?: string;
    healingDetails?: string;
    retryCount?: number;
    totalSteps?: number;
    success?: boolean;
    searchQuery?: string;
    tool?: string;
    reason?: string;
    steps?: Array<{
      name: string;
      description?: string;
      tool?: string;
      compute?: boolean;
      condition?: string;
    }>;
  };
}

export interface SkillExecutionState {
  executionId: string;
  skillName: string;
  workspaceUri: string;
  sessionId?: string;
  sessionName?: string;
  source: string;  // "chat", "cron", "slack", "api"
  sourceDetails?: string;
  status: "running" | "success" | "failed";
  currentStepIndex: number;
  totalSteps: number;
  startTime: string;
  endTime?: string;
  events: SkillExecutionEvent[];
}

// New multi-execution file format
export interface MultiExecutionFile {
  executions: { [executionId: string]: SkillExecutionState };
  lastUpdated: string;
  version?: number;
}

// Execution summary for UI
export interface ExecutionSummary {
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

// ============================================================================
// Skill Execution Watcher
// ============================================================================

export class SkillExecutionWatcher {
  private _watcher: fs.FSWatcher | undefined;
  private _executionFilePath: string;
  private _lastModified: number = 0;
  private _disposables: vscode.Disposable[] = [];
  private _statusBarItem: vscode.StatusBarItem;

  // Multi-execution tracking
  private _executions: Map<string, SkillExecutionState> = new Map();
  private _seenExecutionIds: Set<string> = new Set();  // Track which executions we've notified about
  private _selectedExecutionId: string | undefined;  // Currently selected execution for viewing
  private _lastStateFingerprint: string = "";  // Change detection to avoid redundant UI updates

  constructor() {
    this._executionFilePath = path.join(
      os.homedir(),
      ".config",
      "aa-workflow",
      "skill_execution.json"
    );

    // Create status bar item for skill execution
    this._statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      90
    );
    this._statusBarItem.command = "aa-workflow.openCommandCenter";
    this._disposables.push(this._statusBarItem);
  }

  /**
   * Start watching for skill execution events
   */
  public start(): void {
    // Ensure directory exists
    const dir = path.dirname(this._executionFilePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Watch the execution file
    try {
      // Use polling for cross-platform compatibility
      this._watcher = fs.watch(
        dir,
        { persistent: false },
        (eventType, filename) => {
          if (filename === "skill_execution.json") {
            this._onFileChange();
          }
        }
      );
    } catch (e) {
      logger.error("Failed to start skill execution watcher", e);
    }

    // Always start polling as backup - fs.watch is unreliable on Linux
    this._startPolling();

    // Initial check
    this._onFileChange();
  }

  /**
   * Fallback polling for systems where fs.watch doesn't work well.
   * Polls at 1s intervals - this is a backup for the WebSocket which
   * provides real-time updates. The file watcher is secondary.
   */
  private _startPolling(): void {
    const pollInterval = setInterval(() => {
      this._onFileChange();
    }, 1000);

    this._disposables.push({
      dispose: () => clearInterval(pollInterval),
    });
  }

  /**
   * Handle file change event
   */
  private _onFileChange(): void {
    try {
      if (!fs.existsSync(this._executionFilePath)) {
        return;
      }

      const stat = fs.statSync(this._executionFilePath);
      if (stat.mtimeMs <= this._lastModified) {
        return; // No change
      }
      this._lastModified = stat.mtimeMs;

      const content = fs.readFileSync(this._executionFilePath, "utf-8");
      const data = JSON.parse(content);

      // Handle both old single-execution format and new multi-execution format
      if (data.executions) {
        // New multi-execution format
        this._processMultiExecutionState(data as MultiExecutionFile);
      } else if (data.skillName) {
        // Old single-execution format (backward compatibility)
        const state = data as SkillExecutionState;
        // Generate a fake execution ID for old format
        const execId = `legacy_${state.skillName}_${state.startTime}`;
        state.executionId = execId;
        state.source = state.source || "chat";
        this._processMultiExecutionState({
          executions: { [execId]: state },
          lastUpdated: new Date().toISOString(),
        });
      }
    } catch (e) {
      logger.error("Error processing file", e);
    }
  }

  /**
   * Build a fingerprint of the execution state for change detection.
   * Only includes fields that matter for the UI display.
   */
  private _buildStateFingerprint(data: MultiExecutionFile): string {
    const parts: string[] = [];
    for (const [execId, state] of Object.entries(data.executions)) {
      // Include status, step index, and event count - these are what drive UI changes
      parts.push(`${execId}:${state.status}:${state.currentStepIndex}:${state.events?.length || 0}`);
    }
    return parts.sort().join("|");
  }

  /**
   * Process multi-execution state and update UI
   */
  private _processMultiExecutionState(data: MultiExecutionFile): void {
    const newExecutions = new Map<string, SkillExecutionState>();
    const runningCount = { count: 0 };

    for (const [execId, state] of Object.entries(data.executions)) {
      newExecutions.set(execId, state);

      if (state.status === "running") {
        runningCount.count++;
      }

      // Check if this is a new execution we haven't seen
      if (!this._seenExecutionIds.has(execId)) {
        this._seenExecutionIds.add(execId);

        // Only show toast for running skills (not completed ones on startup)
        if (state.status === "running") {
          this._showSkillStartedToast(state);
        }
      }

      // Check if execution just completed
      const prevState = this._executions.get(execId);
      if (prevState?.status === "running" && state.status !== "running") {
        this._showSkillCompletedToast(state);
      }
    }

    this._executions = newExecutions;

    // Update status bar (lightweight - always OK)
    this._updateStatusBar(runningCount.count);

    // Only update Command Center if the state actually changed.
    // This prevents redundant re-renders when the file is polled
    // but nothing meaningful has changed since the last update.
    const fingerprint = this._buildStateFingerprint(data);
    if (fingerprint !== this._lastStateFingerprint) {
      this._lastStateFingerprint = fingerprint;
      this._updateCommandCenter();
    } else {
      logger.log("Skipping Command Center update - state unchanged");
    }
  }

  /**
   * Show toast notification when a skill starts
   */
  private _showSkillStartedToast(state: SkillExecutionState): void {
    const sourceLabel = this._getSourceLabel(state);
    const message = `Skill "${state.skillName}" started${sourceLabel}`;

    vscode.window.showInformationMessage(message, "View").then((selection) => {
      if (selection === "View") {
        this._selectedExecutionId = state.executionId;
        vscode.commands.executeCommand("aa-workflow.openCommandCenter", "skills");
      }
    });

    logger.log(`New skill started: ${state.skillName} (${state.source})`);
  }

  /**
   * Show toast notification when a skill completes
   */
  private _showSkillCompletedToast(state: SkillExecutionState): void {
    const sourceLabel = this._getSourceLabel(state);
    const icon = state.status === "success" ? "$(check)" : "$(error)";
    const statusText = state.status === "success" ? "completed" : "failed";
    const message = `${icon} Skill "${state.skillName}" ${statusText}${sourceLabel}`;

    if (state.status === "failed") {
      vscode.window.showWarningMessage(message, "View Details").then((selection) => {
        if (selection === "View Details") {
          this._selectedExecutionId = state.executionId;
          vscode.commands.executeCommand("aa-workflow.openCommandCenter", "skills");
        }
      });
    }
    // Don't show toast for successful completions (too noisy)
  }

  /**
   * Get a human-readable source label
   */
  private _getSourceLabel(state: SkillExecutionState): string {
    if (state.source === "cron") {
      return state.sourceDetails ? ` (cron: ${state.sourceDetails})` : " (cron)";
    } else if (state.source === "slack") {
      return " (Slack)";
    } else if (state.sessionName) {
      return ` (${state.sessionName})`;
    }
    return "";
  }

  /**
   * Update status bar with running execution count
   */
  private _updateStatusBar(runningCount: number): void {
    if (runningCount === 0) {
      this._statusBarItem.hide();
      return;
    }

    if (runningCount === 1) {
      // Show single skill name
      const running = this.getRunningExecutions()[0];
      if (running) {
        const progress = `${running.currentStepIndex + 1}/${running.totalSteps}`;
        this._statusBarItem.text = `$(sync~spin) ${running.skillName} [${progress}]`;
        this._statusBarItem.tooltip = `Skill "${running.skillName}" running - click to view`;
      }
    } else {
      // Show count for multiple skills
      this._statusBarItem.text = `$(sync~spin) ${runningCount} skills running`;
      this._statusBarItem.tooltip = `${runningCount} skills running - click to view`;
    }

    this._statusBarItem.backgroundColor = undefined;
    this._statusBarItem.show();
  }

  /**
   * Update Command Center with current execution state
   */
  private _updateCommandCenter(): void {
    const commandCenter = getCommandCenterPanel();
    if (!commandCenter) {
      logger.log("Command Center panel not available, skipping update");
      return;
    }

    // Get all running executions for the panel
    const runningExecutions = this.getRunningExecutions();
    logger.log(`Updating Command Center with ${runningExecutions.length} running executions`);

    // Send all running executions to Command Center
    commandCenter.updateRunningSkills(runningExecutions);

    // If there's a selected execution, send its detailed state
    const selectedExec = this._selectedExecutionId
      ? this._executions.get(this._selectedExecutionId)
      : runningExecutions[0] ? this._executions.get(runningExecutions[0].executionId) : undefined;

    if (selectedExec) {
      const execution = {
        executionId: selectedExec.executionId,
        skillName: selectedExec.skillName,
        status: selectedExec.status,
        currentStepIndex: selectedExec.currentStepIndex,
        totalSteps: selectedExec.totalSteps,
        steps: this._buildStepsFromEvents(selectedExec),
        startTime: selectedExec.startTime,
        endTime: selectedExec.endTime,
        source: selectedExec.source,
        sourceDetails: selectedExec.sourceDetails,
        sessionName: selectedExec.sessionName,
      };
      commandCenter.updateSkillExecution(execution);
    }
  }

  /**
   * Get all running executions as summaries
   */
  public getRunningExecutions(): ExecutionSummary[] {
    const now = Date.now();
    const running: ExecutionSummary[] = [];

    for (const [execId, state] of this._executions) {
      if (state.status === "running") {
        const startTime = new Date(state.startTime).getTime();
        running.push({
          executionId: execId,
          skillName: state.skillName,
          source: state.source,
          sourceDetails: state.sourceDetails,
          sessionName: state.sessionName,
          status: state.status,
          currentStepIndex: state.currentStepIndex,
          totalSteps: state.totalSteps,
          startTime: state.startTime,
          elapsedMs: now - startTime,
        });
      }
    }

    // Sort by start time (newest first)
    running.sort((a, b) => new Date(b.startTime).getTime() - new Date(a.startTime).getTime());

    return running;
  }

  /**
   * Get all executions (running and recent completed)
   */
  public getAllExecutions(): ExecutionSummary[] {
    const now = Date.now();
    const all: ExecutionSummary[] = [];

    for (const [execId, state] of this._executions) {
      const startTime = new Date(state.startTime).getTime();
      all.push({
        executionId: execId,
        skillName: state.skillName,
        source: state.source,
        sourceDetails: state.sourceDetails,
        sessionName: state.sessionName,
        status: state.status,
        currentStepIndex: state.currentStepIndex,
        totalSteps: state.totalSteps,
        startTime: state.startTime,
        elapsedMs: now - startTime,
      });
    }

    // Sort by start time (newest first)
    all.sort((a, b) => new Date(b.startTime).getTime() - new Date(a.startTime).getTime());

    return all;
  }

  /**
   * Check if an execution is stale (running too long without progress)
   * A skill is considered stale if:
   * - It's been "running" for more than 30 minutes, OR
   * - It's been "running" for more than 10 minutes with no recent events
   */
  public isExecutionStale(state: SkillExecutionState): boolean {
    if (state.status !== "running") {
      return false;
    }

    const now = Date.now();
    const startTime = new Date(state.startTime).getTime();
    const elapsedMs = now - startTime;

    // Stale if running for more than 30 minutes
    const STALE_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes
    if (elapsedMs > STALE_THRESHOLD_MS) {
      return true;
    }

    // Check last event time - stale if no events in last 10 minutes
    const INACTIVE_THRESHOLD_MS = 10 * 60 * 1000; // 10 minutes
    if (state.events && state.events.length > 0) {
      const lastEvent = state.events[state.events.length - 1];
      const lastEventTime = new Date(lastEvent.timestamp).getTime();
      const timeSinceLastEvent = now - lastEventTime;
      if (timeSinceLastEvent > INACTIVE_THRESHOLD_MS) {
        return true;
      }
    }

    return false;
  }

  /**
   * Get count of stale executions
   */
  public getStaleExecutionCount(): number {
    let count = 0;
    for (const state of this._executions.values()) {
      if (this.isExecutionStale(state)) {
        count++;
      }
    }
    return count;
  }

  /**
   * Clear stale executions from the execution file
   * Marks them as failed and removes from tracking
   * Uses file locking to prevent race conditions with the MCP server
   */
  public async clearStaleExecutions(): Promise<number> {
    const staleIds: string[] = [];

    // Find all stale executions
    for (const [execId, state] of this._executions) {
      if (this.isExecutionStale(state)) {
        staleIds.push(execId);
      }
    }

    if (staleIds.length === 0) {
      return 0;
    }

    // Update the execution file with lock protection
    const result = await withFileLock(this._executionFilePath, () => {
      try {
        if (!fs.existsSync(this._executionFilePath)) {
          return 0;
        }

        const content = fs.readFileSync(this._executionFilePath, "utf-8");
        const data = JSON.parse(content) as MultiExecutionFile;

        // Mark stale executions as failed and set end time
        let clearedCount = 0;
        for (const execId of staleIds) {
          if (data.executions[execId]) {
            data.executions[execId].status = "failed";
            data.executions[execId].endTime = new Date().toISOString();
            // Add a failure event
            data.executions[execId].events.push({
              type: "skill_complete",
              timestamp: new Date().toISOString(),
              skillName: data.executions[execId].skillName,
              executionId: execId,
              data: {
                success: false,
                error: "Execution marked as stale/dead (no activity for extended period)",
              },
            });
            clearedCount++;
          }
          // Remove from our tracking
          this._executions.delete(execId);
        }

        // Write back to file atomically
        data.lastUpdated = new Date().toISOString();
        const tmpFile = this._executionFilePath + ".tmp";
        fs.writeFileSync(tmpFile, JSON.stringify(data, null, 2));
        fs.renameSync(tmpFile, this._executionFilePath);

        logger.log(`Cleared ${clearedCount} stale execution(s)`);
        return clearedCount;
      } catch (e) {
        logger.error("Error clearing stale executions", e);
        return 0;
      }
    });

    const clearedCount = result ?? 0;

    // Update UI
    this._updateStatusBar(this.getRunningExecutions().length);
    this._updateCommandCenter();

    return clearedCount;
  }

  /**
   * Clear a specific execution by ID
   * Uses file locking to prevent race conditions with the MCP server
   */
  public async clearExecution(executionId: string): Promise<boolean> {
    // Update the execution file with lock protection
    const result = await withFileLock(this._executionFilePath, () => {
      try {
        if (!fs.existsSync(this._executionFilePath)) {
          return false;
        }

        const content = fs.readFileSync(this._executionFilePath, "utf-8");
        const data = JSON.parse(content) as MultiExecutionFile;

        if (!data.executions[executionId]) {
          return false;
        }

        // Mark as failed
        data.executions[executionId].status = "failed";
        data.executions[executionId].endTime = new Date().toISOString();
        data.executions[executionId].events.push({
          type: "skill_complete",
          timestamp: new Date().toISOString(),
          skillName: data.executions[executionId].skillName,
          executionId: executionId,
          data: {
            success: false,
            error: "Execution manually cleared by user",
          },
        });

        // Remove from tracking
        this._executions.delete(executionId);
        this._seenExecutionIds.delete(executionId);

        // Write back atomically
        data.lastUpdated = new Date().toISOString();
        const tmpFile = this._executionFilePath + ".tmp";
        fs.writeFileSync(tmpFile, JSON.stringify(data, null, 2));
        fs.renameSync(tmpFile, this._executionFilePath);

        logger.log(`Cleared execution: ${executionId}`);
        return true;
      } catch (e) {
        logger.error("Error clearing execution", e);
        return false;
      }
    });

    const success = result ?? false;

    // Update UI
    this._updateStatusBar(this.getRunningExecutions().length);
    this._updateCommandCenter();

    return success;
  }

  /**
   * Select an execution to view in detail
   */
  public selectExecution(executionId: string): void {
    this._selectedExecutionId = executionId;
    this._updateCommandCenter();
  }

  /**
   * Get the currently selected execution
   */
  public getSelectedExecution(): SkillExecutionState | undefined {
    if (this._selectedExecutionId) {
      return this._executions.get(this._selectedExecutionId);
    }
    // Default to first running execution
    const running = this.getRunningExecutions();
    if (running.length > 0) {
      return this._executions.get(running[0].executionId);
    }
    return undefined;
  }

  /**
   * Build steps array from events for display
   */
  private _buildStepsFromEvents(state: SkillExecutionState): any[] {
    const steps: any[] = [];
    const stepMap = new Map<number, any>();

    for (const event of state.events) {
      if (event.type === "skill_start" && event.data?.steps) {
        // Initialize steps from skill_start event
        event.data.steps.forEach((step: any, index: number) => {
          const onError = step.on_error || "";
          const tool = step.tool || "";
          const lowerName = (step.name || "").toLowerCase();
          const lowerDesc = (step.description || "").toLowerCase();

          // Detect static remediation steps from name/description patterns
          const remediationPatterns = ["retry", "heal", "fix", "recover", "fallback", "remediat"];
          const isStaticRemediation = remediationPatterns.some(p =>
            lowerName.includes(p) || lowerDesc.includes(p)
          ) || (lowerName.startsWith("learn_") && tool.includes("learn_tool_fix"));

          stepMap.set(index, {
            name: step.name,
            description: step.description,
            tool: step.tool,
            status: "pending",
            compute: step.compute,
            condition: step.condition,
            canAutoHeal: onError === "auto_heal",
            // canRetry: steps with continue/retry on_error, or common API tools
            canRetry: onError === "continue" || onError === "retry" ||
                      tool.startsWith("jira_") || tool.startsWith("gitlab_"),
            // isAutoRemediation: static detection from step name/description
            isAutoRemediation: isStaticRemediation,
          });
        });
      } else if (event.stepIndex !== undefined) {
        const step = stepMap.get(event.stepIndex) || { name: event.stepName || `Step ${event.stepIndex + 1}` };

        switch (event.type) {
          case "step_start":
            step.status = "running";
            break;
          case "step_complete":
            step.status = "success";
            step.duration = event.data?.duration;
            step.result = event.data?.result;
            break;
          case "step_failed":
            step.status = "failed";
            step.error = event.data?.error;
            step.duration = event.data?.duration;
            break;
          case "step_skipped":
            step.status = "skipped";
            break;
          case "memory_read":
            step.memoryRead = step.memoryRead || [];
            if (event.data?.memoryKey && !step.memoryRead.includes(event.data.memoryKey)) {
              step.memoryRead.push(event.data.memoryKey);
            }
            break;
          case "memory_write":
            step.memoryWrite = step.memoryWrite || [];
            if (event.data?.memoryKey && !step.memoryWrite.includes(event.data.memoryKey)) {
              step.memoryWrite.push(event.data.memoryKey);
            }
            break;
          case "auto_heal":
            step.healingApplied = true;
            step.healingDetails = event.data?.healingDetails;
            break;
          case "retry":
            step.retryCount = (step.retryCount || 0) + 1;
            break;
          case "semantic_search":
            step.semanticSearch = step.semanticSearch || [];
            if (event.data?.searchQuery && !step.semanticSearch.includes(event.data.searchQuery)) {
              step.semanticSearch.push(event.data.searchQuery);
            }
            break;
          case "remediation_step":
            step.isAutoRemediation = true;
            step.remediationTool = event.data?.tool;
            step.remediationReason = event.data?.reason;
            break;
        }

        stepMap.set(event.stepIndex, step);
      }
    }

    // Convert map to array
    for (let i = 0; i < state.totalSteps; i++) {
      steps.push(stepMap.get(i) || { name: `Step ${i + 1}`, status: "pending" });
    }

    return steps;
  }

  /**
   * Stop watching
   */
  public stop(): void {
    if (this._watcher) {
      this._watcher.close();
      this._watcher = undefined;
    }
  }

  /**
   * Dispose resources
   */
  public dispose(): void {
    this.stop();
    while (this._disposables.length) {
      const d = this._disposables.pop();
      if (d) {
        d.dispose();
      }
    }
  }
}

// ============================================================================
// Registration
// ============================================================================

let watcher: SkillExecutionWatcher | undefined;

export function registerSkillExecutionWatcher(
  context: vscode.ExtensionContext
): SkillExecutionWatcher {
  watcher = new SkillExecutionWatcher();
  watcher.start();

  context.subscriptions.push({
    dispose: () => watcher?.dispose(),
  });

  return watcher;
}

export function getSkillExecutionWatcher(): SkillExecutionWatcher | undefined {
  return watcher;
}
