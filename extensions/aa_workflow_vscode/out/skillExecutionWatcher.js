"use strict";
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
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.SkillExecutionWatcher = void 0;
exports.registerSkillExecutionWatcher = registerSkillExecutionWatcher;
exports.getSkillExecutionWatcher = getSkillExecutionWatcher;
const vscode = __importStar(require("vscode"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const os = __importStar(require("os"));
const skillFlowchartPanel_1 = require("./skillFlowchartPanel");
// ============================================================================
// Skill Execution Watcher
// ============================================================================
class SkillExecutionWatcher {
    _watcher;
    _executionFilePath;
    _lastModified = 0;
    _disposables = [];
    _statusBarItem;
    _currentExecution;
    constructor() {
        this._executionFilePath = path.join(os.homedir(), ".config", "aa-workflow", "skill_execution.json");
        // Create status bar item for skill execution
        this._statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 90);
        this._statusBarItem.command = "aa-workflow.openSkillFlowchart";
        this._disposables.push(this._statusBarItem);
    }
    /**
     * Start watching for skill execution events
     */
    start() {
        // Ensure directory exists
        const dir = path.dirname(this._executionFilePath);
        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }
        // Watch the execution file
        try {
            // Use polling for cross-platform compatibility
            this._watcher = fs.watch(dir, { persistent: false }, (eventType, filename) => {
                if (filename === "skill_execution.json") {
                    this._onFileChange();
                }
            });
        }
        catch (e) {
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
    _startPolling() {
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
    _onFileChange() {
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
            const state = JSON.parse(content);
            console.log(`[SkillWatcher] File changed: ${state.skillName} - status: ${state.status}, step: ${state.currentStepIndex}/${state.totalSteps}`);
            this._processExecutionState(state);
        }
        catch (e) {
            console.error("[SkillWatcher] Error processing file:", e);
        }
    }
    /**
     * Process execution state and update UI
     */
    _processExecutionState(state) {
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
        const panel = (0, skillFlowchartPanel_1.getSkillFlowchartPanel)();
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
    async _autoOpenFlowchartPanel(skillName) {
        try {
            // Execute the command to open the flowchart panel
            await vscode.commands.executeCommand("aa-workflow.openSkillFlowchart");
            // Give the panel time to initialize
            await new Promise(resolve => setTimeout(resolve, 100));
            // Get the panel and load the skill
            const panel = (0, skillFlowchartPanel_1.getSkillFlowchartPanel)();
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
        }
        catch (e) {
            console.error("Failed to auto-open flowchart panel:", e);
        }
    }
    /**
     * Get events that are new since last update
     */
    _getNewEvents(previous, current) {
        if (!previous || previous.skillName !== current.skillName) {
            return current.events;
        }
        const previousCount = previous.events.length;
        return current.events.slice(previousCount);
    }
    /**
     * Process a single execution event
     */
    _processEvent(panel, event) {
        switch (event.type) {
            case "skill_start":
                // Load skill and start execution visualization
                if (event.data?.steps) {
                    panel.loadSkill(event.skillName).then(() => {
                        panel.startExecution(event.skillName);
                    });
                }
                else {
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
                    panel.recordMemoryOperation(event.stepIndex, "read", event.data.memoryKey);
                }
                break;
            case "memory_write":
                if (event.stepIndex !== undefined && event.data?.memoryKey) {
                    panel.recordMemoryOperation(event.stepIndex, "write", event.data.memoryKey);
                }
                break;
            case "auto_heal":
                if (event.stepIndex !== undefined) {
                    panel.recordHealing(event.stepIndex, event.data?.healingDetails || "Auto-healed");
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
    _updateStatusBar(state) {
        if (state.status === "running") {
            const progress = `${state.currentStepIndex + 1}/${state.totalSteps}`;
            this._statusBarItem.text = `$(sync~spin) ${state.skillName} [${progress}]`;
            this._statusBarItem.tooltip = `Skill "${state.skillName}" running - click to view flowchart`;
            this._statusBarItem.backgroundColor = undefined;
            this._statusBarItem.show();
        }
        else if (state.status === "success") {
            this._statusBarItem.text = `$(check) ${state.skillName}`;
            this._statusBarItem.tooltip = `Skill "${state.skillName}" completed successfully`;
            this._statusBarItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
            this._statusBarItem.show();
            // Hide after 5 seconds
            setTimeout(() => this._hideStatusBar(), 5000);
        }
        else if (state.status === "failed") {
            this._statusBarItem.text = `$(error) ${state.skillName}`;
            this._statusBarItem.tooltip = `Skill "${state.skillName}" failed - click to view details`;
            this._statusBarItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
            this._statusBarItem.show();
            // Hide after 10 seconds
            setTimeout(() => this._hideStatusBar(), 10000);
        }
    }
    /**
     * Hide the status bar item
     */
    _hideStatusBar() {
        this._statusBarItem.hide();
    }
    /**
     * Stop watching
     */
    stop() {
        if (this._watcher) {
            this._watcher.close();
            this._watcher = undefined;
        }
    }
    /**
     * Dispose resources
     */
    dispose() {
        this.stop();
        while (this._disposables.length) {
            const d = this._disposables.pop();
            if (d) {
                d.dispose();
            }
        }
    }
}
exports.SkillExecutionWatcher = SkillExecutionWatcher;
// ============================================================================
// Registration
// ============================================================================
let watcher;
function registerSkillExecutionWatcher(context) {
    watcher = new SkillExecutionWatcher();
    watcher.start();
    context.subscriptions.push({
        dispose: () => watcher?.dispose(),
    });
    return watcher;
}
function getSkillExecutionWatcher() {
    return watcher;
}
//# sourceMappingURL=skillExecutionWatcher.js.map
