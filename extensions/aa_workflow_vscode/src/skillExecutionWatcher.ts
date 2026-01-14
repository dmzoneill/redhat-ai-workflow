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
import { SkillFlowchartPanel, getSkillFlowchartPanel } from "./skillFlowchartPanel";

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
    | "retry";
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

    // Auto-open flowchart panel when a skill starts OR completes (if we missed the start)
    if (isNewSkill) {
      console.log(`[SkillWatcher] New skill detected: ${state.skillName} (status: ${state.status})`);
      this._autoOpenFlowchartPanel(state.skillName);
      return; // Events will be processed after panel opens
    }

    // Get or create flowchart panel
    const panel = getSkillFlowchartPanel();
    if (!panel) {
      // Panel not open, just update status bar
      return;
    }

    // Process new events
    const newEvents = this._getNewEvents(previousExecution, state);
    for (const event of newEvents) {
      this._processEvent(panel, event);
    }
  }

  /**
   * Auto-open the flowchart panel when a skill starts
   */
  private async _autoOpenFlowchartPanel(skillName: string): Promise<void> {
    try {
      // Execute the command to open the flowchart panel
      await vscode.commands.executeCommand("aa-workflow.openSkillFlowchart");

      // Give the panel time to initialize
      await new Promise(resolve => setTimeout(resolve, 100));

      // Get the panel and load the skill
      const panel = getSkillFlowchartPanel();
      if (panel) {
        await panel.loadSkill(skillName);
        panel.startExecution(skillName);

        // Process any events that came in while we were opening
        if (this._currentExecution) {
          for (const event of this._currentExecution.events) {
            this._processEvent(panel, event);
          }
        }
      }
    } catch (e) {
      console.error("Failed to auto-open flowchart panel:", e);
    }
  }

  /**
   * Get events that are new since last update
   */
  private _getNewEvents(
    previous: SkillExecutionState | undefined,
    current: SkillExecutionState
  ): SkillExecutionEvent[] {
    if (!previous || previous.skillName !== current.skillName) {
      return current.events;
    }

    const previousCount = previous.events.length;
    return current.events.slice(previousCount);
  }

  /**
   * Process a single execution event
   */
  private _processEvent(
    panel: SkillFlowchartPanel,
    event: SkillExecutionEvent
  ): void {
    switch (event.type) {
      case "skill_start":
        // Load skill and start execution visualization
        if (event.data?.steps) {
          panel.loadSkill(event.skillName).then(() => {
            panel.startExecution(event.skillName);
          });
        } else {
          panel.startExecution(event.skillName);
        }
        break;

      case "step_start":
        if (event.stepIndex !== undefined) {
          panel.updateStep(event.stepIndex, "running");
        }
        break;

      case "step_complete":
        if (event.stepIndex !== undefined) {
          panel.updateStep(event.stepIndex, "success", {
            duration: event.data?.duration,
            result: event.data?.result,
          });
        }
        break;

      case "step_failed":
        if (event.stepIndex !== undefined) {
          panel.updateStep(event.stepIndex, "failed", {
            duration: event.data?.duration,
            error: event.data?.error,
          });
        }
        break;

      case "step_skipped":
        if (event.stepIndex !== undefined) {
          panel.updateStep(event.stepIndex, "skipped");
        }
        break;

      case "skill_complete":
        panel.completeExecution(event.data?.success ?? false);
        break;

      case "memory_read":
        if (event.stepIndex !== undefined && event.data?.memoryKey) {
          panel.recordMemoryOperation(
            event.stepIndex,
            "read",
            event.data.memoryKey
          );
        }
        break;

      case "memory_write":
        if (event.stepIndex !== undefined && event.data?.memoryKey) {
          panel.recordMemoryOperation(
            event.stepIndex,
            "write",
            event.data.memoryKey
          );
        }
        break;

      case "auto_heal":
        if (event.stepIndex !== undefined) {
          panel.recordHealing(
            event.stepIndex,
            event.data?.healingDetails || "Auto-healed"
          );
        }
        break;

      case "retry":
        if (event.stepIndex !== undefined) {
          panel.recordRetry(event.stepIndex);
        }
        break;
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
