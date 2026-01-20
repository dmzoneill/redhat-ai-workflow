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
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { getCommandCenterPanel } from "./commandCenter";

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
  skillName: string;
  status: "running" | "success" | "failed";
  currentStepIndex: number;
  totalSteps: number;
  startTime: string;
  endTime?: string;
  events: SkillExecutionEvent[];
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
  private _currentExecution: SkillExecutionState | undefined;

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
    this._statusBarItem.command = "aa-workflow.openSkillFlowchart";
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
      console.error("Failed to start skill execution watcher:", e);
      // Fallback to polling
      this._startPolling();
    }

    // Initial check
    this._onFileChange();
  }

  /**
   * Fallback polling for systems where fs.watch doesn't work well
   */
  private _startPolling(): void {
    const pollInterval = setInterval(() => {
      this._onFileChange();
    }, 500);

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
      const state: SkillExecutionState = JSON.parse(content);

      console.log(`[SkillWatcher] File changed: ${state.skillName} - status: ${state.status}, step: ${state.currentStepIndex}/${state.totalSteps}`);

      this._processExecutionState(state);
    } catch (e) {
      console.error("[SkillWatcher] Error processing file:", e);
    }
  }

  /**
   * Process execution state and update UI
   */
  private _processExecutionState(state: SkillExecutionState): void {
    const previousExecution = this._currentExecution;
    this._currentExecution = state;

    // Update status bar
    this._updateStatusBar(state);

    // Check if this is a new skill (either starting or just completed that we haven't seen)
    const isNewSkill = !previousExecution ||
      previousExecution.skillName !== state.skillName ||
      previousExecution.startTime !== state.startTime;

    // Auto-open flowchart panel when a skill starts
    // Don't auto-open for completed skills on initial load (stale state)
    if (isNewSkill) {
      console.log(`[SkillWatcher] New skill detected: ${state.skillName} (status: ${state.status})`);

      // Only auto-open if skill is currently running
      // Skip completed skills to avoid showing stale state on extension startup
      if (state.status === "running") {
        this._autoOpenFlowchartPanel(state.skillName);
        return; // Events will be processed after panel opens
      } else {
        // For completed skills, just update status bar but don't auto-open panel
        console.log(`[SkillWatcher] Skipping auto-open for completed skill: ${state.skillName}`);
        return;
      }
    }

    // Update Command Center if open
    const commandCenter = getCommandCenterPanel();
    if (commandCenter) {
      // Convert state to execution format for Command Center
      const execution = {
        skillName: state.skillName,
        status: state.status,
        currentStepIndex: state.currentStepIndex,
        totalSteps: state.totalSteps,
        steps: this._buildStepsFromEvents(state),
        startTime: state.startTime,
        endTime: state.endTime,
      };
      commandCenter.updateSkillExecution(execution);
    }
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
   * Auto-open the Command Center Skills tab when a skill starts
   */
  private async _autoOpenFlowchartPanel(skillName: string): Promise<void> {
    try {
      // Open Command Center and switch to Skills tab
      await vscode.commands.executeCommand("aa-workflow.openCommandCenter", "skills");

      // Give the panel time to initialize
      await new Promise(resolve => setTimeout(resolve, 100));

      // Update with current execution state
      const commandCenter = getCommandCenterPanel();
      if (commandCenter && this._currentExecution) {
        const execution = {
          skillName: this._currentExecution.skillName,
          status: this._currentExecution.status,
          currentStepIndex: this._currentExecution.currentStepIndex,
          totalSteps: this._currentExecution.totalSteps,
          steps: this._buildStepsFromEvents(this._currentExecution),
          startTime: this._currentExecution.startTime,
          endTime: this._currentExecution.endTime,
        };
        commandCenter.updateSkillExecution(execution);
      }
    } catch (e) {
      console.error("Failed to auto-open Command Center:", e);
    }
  }

  /**
   * Update status bar with current execution state
   */
  private _updateStatusBar(state: SkillExecutionState): void {
    if (state.status === "running") {
      const progress = `${state.currentStepIndex + 1}/${state.totalSteps}`;
      this._statusBarItem.text = `$(sync~spin) ${state.skillName} [${progress}]`;
      this._statusBarItem.tooltip = `Skill "${state.skillName}" running - click to view flowchart`;
      this._statusBarItem.backgroundColor = undefined;
      this._statusBarItem.show();
    } else if (state.status === "success") {
      this._statusBarItem.text = `$(check) ${state.skillName}`;
      this._statusBarItem.tooltip = `Skill "${state.skillName}" completed successfully`;
      this._statusBarItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.warningBackground"
      );
      this._statusBarItem.show();

      // Hide after 5 seconds
      setTimeout(() => this._hideStatusBar(), 5000);
    } else if (state.status === "failed") {
      this._statusBarItem.text = `$(error) ${state.skillName}`;
      this._statusBarItem.tooltip = `Skill "${state.skillName}" failed - click to view details`;
      this._statusBarItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.errorBackground"
      );
      this._statusBarItem.show();

      // Hide after 10 seconds
      setTimeout(() => this._hideStatusBar(), 10000);
    }
  }

  /**
   * Hide the status bar item
   */
  private _hideStatusBar(): void {
    this._statusBarItem.hide();
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
