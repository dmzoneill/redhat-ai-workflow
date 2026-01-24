/**
 * Skill Flowchart Panel
 *
 * Shows skill execution flowchart in the bottom panel area (like terminal).
 * Displays real-time progress of skill steps with a visual flowchart.
 *
 * Features:
 * - Mermaid-style flowchart visualization
 * - Real-time step progress updates
 * - Conditional branch visualization
 * - Step timing and status
 * - Expandable step details
 * - Error highlighting with diagnostics
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { createLogger } from "./logger";

const logger = createLogger("Flowchart");

// ============================================================================
// Types
// ============================================================================

export interface SkillStep {
  name: string;
  description?: string;
  tool?: string;
  compute?: string;
  condition?: string;
  args?: Record<string, string>;
  output?: string;
  onError?: string;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  duration?: number;
  result?: string;
  error?: string;
  startTime?: number;
  // Lifecycle indicators
  memoryRead?: string[];      // Memory keys read by this step
  memoryWrite?: string[];     // Memory keys written by this step
  semanticSearch?: string[];  // Semantic/knowledge search operations
  isAutoRemediation?: boolean; // Step is part of auto-remediation
  canRetry?: boolean;         // Step can be retried on failure
  retryCount?: number;        // Number of retries attempted
  healingApplied?: boolean;   // Auto-heal was applied
  healingDetails?: string;    // What was healed
  // Sub-skill call indicator
  isSkillCall?: boolean;      // Step calls another skill via skill_run
  calledSkillName?: string;   // Name of the skill being called
}

export interface SkillDefinition {
  name: string;
  description: string;
  version?: string;
  inputs: Array<{
    name: string;
    type: string;
    required: boolean;
    default?: string;
    description?: string;
  }>;
  steps: SkillStep[];
  outputs?: Array<{
    name: string;
    value: string;
  }>;
}

export interface SkillExecution {
  skill: SkillDefinition;
  status: "idle" | "running" | "success" | "failed";
  currentStepIndex: number;
  startTime?: number;
  endTime?: number;
  totalDuration?: number;
  inputs?: Record<string, unknown>;
}

// ============================================================================
// Skill Flowchart Panel
// ============================================================================

export class SkillFlowchartPanel {
  public static currentPanel: SkillFlowchartPanel | undefined;
  private readonly _panel: vscode.WebviewPanel;
  private readonly _extensionUri: vscode.Uri;
  private _disposables: vscode.Disposable[] = [];
  private _execution: SkillExecution | undefined;
  private _availableSkills: string[] = [];

  public static createOrShow(
    extensionUri: vscode.Uri,
    position: "side" | "bottom" = "bottom"
  ): SkillFlowchartPanel {
    console.log("[SkillFlowchartPanel] ========================================");
    console.log("[SkillFlowchartPanel] createOrShow called");
    console.log("[SkillFlowchartPanel] currentPanel exists:", !!SkillFlowchartPanel.currentPanel);
    console.log("[SkillFlowchartPanel] ========================================");

    // Check if panel already exists in our static variable
    if (SkillFlowchartPanel.currentPanel) {
      console.log("[SkillFlowchartPanel] Reusing existing panel from static variable, revealing...");
      SkillFlowchartPanel.currentPanel._panel.reveal();
      return SkillFlowchartPanel.currentPanel;
    }

    // Debug: Log all open tabs to understand what's happening
    console.log("[SkillFlowchartPanel] Scanning all open tabs...");
    let tabCount = 0;
    for (const group of vscode.window.tabGroups.all) {
      for (const tab of group.tabs) {
        tabCount++;
        const input = tab.input as any;
        console.log(`[SkillFlowchartPanel] Tab ${tabCount}: label="${tab.label}", viewType="${input?.viewType || 'N/A'}", uri="${input?.uri?.toString() || 'N/A'}"`);
      }
    }
    console.log(`[SkillFlowchartPanel] Total tabs found: ${tabCount}`);

    // Look for existing flowchart tab
    const existingTab = vscode.window.tabGroups.all
      .flatMap(group => group.tabs)
      .find(tab => {
        const input = tab.input as { viewType?: string } | undefined;
        const isMatch = input?.viewType === "aaSkillFlowchart";
        if (tab.label.includes("Flowchart") || tab.label.includes("Skill")) {
          console.log(`[SkillFlowchartPanel] Potential match: label="${tab.label}", viewType="${input?.viewType}", isMatch=${isMatch}`);
        }
        return isMatch;
      });

    if (existingTab) {
      console.log("[SkillFlowchartPanel] Found existing tab - closing zombie and creating fresh");
      vscode.window.tabGroups.close(existingTab);
    } else {
      console.log("[SkillFlowchartPanel] No existing aaSkillFlowchart tab found");
    }

    console.log("[SkillFlowchartPanel] Creating NEW panel");

    // Determine view column based on position preference
    // For "bottom", we use ViewColumn.Active which will open in the panel area
    // if the user has the panel area focused, or beside the editor otherwise
    const viewColumn =
      position === "bottom" ? vscode.ViewColumn.Beside : vscode.ViewColumn.Two;

    // Create panel
    const panel = vscode.window.createWebviewPanel(
      "aaSkillFlowchart",
      "⚡ Skill Flowchart",
      {
        viewColumn,
        preserveFocus: true,
      },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [extensionUri],
      }
    );

    SkillFlowchartPanel.currentPanel = new SkillFlowchartPanel(
      panel,
      extensionUri
    );
    return SkillFlowchartPanel.currentPanel;
  }

  public static revive(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    console.log("[SkillFlowchartPanel] ========================================");
    console.log("[SkillFlowchartPanel] revive() called - restoring panel from VS Code");
    console.log("[SkillFlowchartPanel] Previous currentPanel:", SkillFlowchartPanel.currentPanel);
    SkillFlowchartPanel.currentPanel = new SkillFlowchartPanel(panel, extensionUri);
    console.log("[SkillFlowchartPanel] New currentPanel set:", !!SkillFlowchartPanel.currentPanel);
    console.log("[SkillFlowchartPanel] ========================================");
  }

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    this._panel = panel;
    this._extensionUri = extensionUri;

    // Load available skills
    this._loadAvailableSkills();

    // Set initial content
    this._updateContent();

    // Handle panel disposal
    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // Handle messages from webview
    this._panel.webview.onDidReceiveMessage(
      async (message) => {
        console.log('Received message from webview:', message);
        switch (message.command) {
          case "loadSkill":
            console.log('Loading skill:', message.skillName);
            await this.loadSkill(message.skillName);
            break;
          case "runSkill":
            await this._runSkill(message.skillName, message.inputs);
            break;
          case "expandStep":
            // Show step details in hover or modal
            break;
          case "refresh":
            this._loadAvailableSkills();
            this._updateContent();
            break;
        }
      },
      null,
      this._disposables
    );
  }

  // ============================================================================
  // Public API
  // ============================================================================

  /**
   * Load a skill definition and show its flowchart
   */
  public async loadSkill(skillName: string): Promise<void> {
    // Empty skill name means go back to picker
    if (!skillName) {
      this._execution = undefined;
      this._updateContent();
      return;
    }

    const skill = await this._parseSkillYaml(skillName);
    if (!skill) {
      vscode.window.showErrorMessage(`Could not load skill: ${skillName}`);
      return;
    }

    this._execution = {
      skill,
      status: "idle",
      currentStepIndex: -1,
    };

    this._updateContent();
  }

  /**
   * Start execution visualization for a skill
   */
  public startExecution(skillName: string, inputs?: Record<string, unknown>): void {
    if (!this._execution || this._execution.skill.name !== skillName) {
      // Load skill first
      this.loadSkill(skillName).then(() => {
        this._startExecutionInternal(inputs);
      });
    } else {
      this._startExecutionInternal(inputs);
    }
  }

  private _startExecutionInternal(inputs?: Record<string, unknown>): void {
    if (!this._execution) return;

    this._execution.status = "running";
    this._execution.currentStepIndex = 0;
    this._execution.startTime = Date.now();
    this._execution.inputs = inputs;

    // Reset all steps to pending
    this._execution.skill.steps.forEach((step) => {
      step.status = "pending";
      step.duration = undefined;
      step.result = undefined;
      step.error = undefined;
    });

    // Mark first step as running
    if (this._execution.skill.steps.length > 0) {
      this._execution.skill.steps[0].status = "running";
      this._execution.skill.steps[0].startTime = Date.now();
    }

    this._updateContent();
  }

  /**
   * Update a step's status during execution
   */
  public updateStep(
    stepIndex: number,
    status: SkillStep["status"],
    details?: {
      duration?: number;
      result?: string;
      error?: string;
      memoryRead?: string[];
      memoryWrite?: string[];
      healingApplied?: boolean;
      healingDetails?: string;
      retryCount?: number;
    }
  ): void {
    if (!this._execution || stepIndex >= this._execution.skill.steps.length) {
      return;
    }

    const step = this._execution.skill.steps[stepIndex];
    step.status = status;

    if (details?.duration !== undefined) step.duration = details.duration;
    if (details?.result !== undefined) step.result = details.result;
    if (details?.error !== undefined) step.error = details.error;

    // Lifecycle updates
    if (details?.memoryRead) {
      step.memoryRead = [...(step.memoryRead || []), ...details.memoryRead];
    }
    if (details?.memoryWrite) {
      step.memoryWrite = [...(step.memoryWrite || []), ...details.memoryWrite];
    }
    if (details?.healingApplied !== undefined) {
      step.healingApplied = details.healingApplied;
    }
    if (details?.healingDetails !== undefined) {
      step.healingDetails = details.healingDetails;
    }
    if (details?.retryCount !== undefined) {
      step.retryCount = details.retryCount;
    }

    // If step completed, move to next
    if (status === "success" || status === "failed" || status === "skipped") {
      this._execution.currentStepIndex = stepIndex + 1;

      // Mark next step as running if exists
      if (this._execution.currentStepIndex < this._execution.skill.steps.length) {
        const nextStep = this._execution.skill.steps[this._execution.currentStepIndex];
        nextStep.status = "running";
        nextStep.startTime = Date.now();
      }
    }

    this._updateContent();
  }

  /**
   * Record a memory operation for a step
   */
  public recordMemoryOperation(
    stepIndex: number,
    operation: "read" | "write",
    key: string
  ): void {
    if (!this._execution || stepIndex >= this._execution.skill.steps.length) {
      return;
    }

    const step = this._execution.skill.steps[stepIndex];
    if (operation === "read") {
      step.memoryRead = step.memoryRead || [];
      if (!step.memoryRead.includes(key)) {
        step.memoryRead.push(key);
      }
    } else {
      step.memoryWrite = step.memoryWrite || [];
      if (!step.memoryWrite.includes(key)) {
        step.memoryWrite.push(key);
      }
    }

    this._updateContent();
  }

  /**
   * Record an auto-healing event for a step
   */
  public recordHealing(
    stepIndex: number,
    details: string
  ): void {
    if (!this._execution || stepIndex >= this._execution.skill.steps.length) {
      return;
    }

    const step = this._execution.skill.steps[stepIndex];
    step.healingApplied = true;
    step.healingDetails = details;

    this._updateContent();
  }

  /**
   * Record a retry for a step
   */
  public recordRetry(stepIndex: number): void {
    if (!this._execution || stepIndex >= this._execution.skill.steps.length) {
      return;
    }

    const step = this._execution.skill.steps[stepIndex];
    step.retryCount = (step.retryCount || 0) + 1;

    this._updateContent();
  }

  /**
   * Mark execution as complete
   */
  public completeExecution(success: boolean): void {
    if (!this._execution) return;

    this._execution.status = success ? "success" : "failed";
    this._execution.endTime = Date.now();
    this._execution.totalDuration = this._execution.startTime
      ? this._execution.endTime - this._execution.startTime
      : 0;

    this._updateContent();
  }

  // ============================================================================
  // Private Methods
  // ============================================================================

  private _loadAvailableSkills(): void {
    const skillsDir = path.join(
      os.homedir(),
      "src",
      "redhat-ai-workflow",
      "skills"
    );

    try {
      if (fs.existsSync(skillsDir)) {
        this._availableSkills = fs
          .readdirSync(skillsDir)
          .filter((f) => f.endsWith(".yaml"))
          .map((f) => f.replace(".yaml", ""))
          .sort();
      }
    } catch (e) {
      console.error("Failed to load skills:", e);
      this._availableSkills = [];
    }
  }

  private async _parseSkillYaml(skillName: string): Promise<SkillDefinition | null> {
    const skillsDir = path.join(
      os.homedir(),
      "src",
      "redhat-ai-workflow",
      "skills"
    );
    const skillPath = path.join(skillsDir, `${skillName}.yaml`);

    try {
      if (!fs.existsSync(skillPath)) {
        return null;
      }

      const content = fs.readFileSync(skillPath, "utf-8");
      return this._parseYamlContent(content, skillName);
    } catch (e) {
      console.error(`Failed to parse skill ${skillName}:`, e);
      return null;
    }
  }

  private _parseYamlContent(content: string, skillName: string): SkillDefinition {
    // Simple YAML parser for skill files
    const lines = content.split("\n");
    const skill: SkillDefinition = {
      name: skillName,
      description: "",
      inputs: [],
      steps: [],
    };

    let currentSection = "";
    let currentStep: Partial<SkillStep> | null = null;
    let currentInput: Record<string, string> | null = null;
    let currentArgs: Record<string, string> = {};
    let inArgsBlock = false;

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;

      // Top-level fields
      if (line.startsWith("name:")) {
        skill.name = line.split(":")[1]?.trim() || skillName;
      } else if (line.startsWith("description:")) {
        const desc = line.split(":").slice(1).join(":").trim();
        if (desc && !desc.startsWith("|")) {
          skill.description = desc;
        }
      } else if (line.startsWith("version:")) {
        skill.version = line.split(":")[1]?.trim().replace(/"/g, "");
      } else if (line.startsWith("inputs:")) {
        currentSection = "inputs";
      } else if (line.startsWith("steps:")) {
        currentSection = "steps";
      } else if (line.startsWith("outputs:")) {
        currentSection = "outputs";
      }

      // Parse steps section
      if (currentSection === "steps") {
        const stepMatch = line.match(/^\s+-\s+name:\s*(.+)/);
        if (stepMatch) {
          // Save previous step with lifecycle analysis
          if (currentStep && currentStep.name) {
            this._analyzeStepLifecycle(currentStep, currentArgs);
            skill.steps.push({
              ...currentStep,
              args: { ...currentArgs },
              status: "pending",
            } as SkillStep);
          }
          currentStep = { name: stepMatch[1].trim() };
          currentArgs = {};
          inArgsBlock = false;
        } else if (currentStep) {
          // Parse step properties
          const descMatch = line.match(/^\s+description:\s*["']?(.+?)["']?\s*$/);
          const toolMatch = line.match(/^\s+tool:\s*(.+)/);
          const conditionMatch = line.match(/^\s+condition:\s*["']?(.+?)["']?\s*$/);
          const outputMatch = line.match(/^\s+output:\s*(.+)/);
          const onErrorMatch = line.match(/^\s+on_error:\s*(.+)/);

          if (descMatch) currentStep.description = descMatch[1];
          if (toolMatch) currentStep.tool = toolMatch[1].trim();
          if (conditionMatch) currentStep.condition = conditionMatch[1];
          if (outputMatch) currentStep.output = outputMatch[1].trim();
          if (onErrorMatch) currentStep.onError = onErrorMatch[1].trim();

          // Check for compute block
          if (line.match(/^\s+compute:\s*\|/)) {
            currentStep.compute = "python";
          }

          // Parse args block
          if (line.match(/^\s+args:\s*$/)) {
            inArgsBlock = true;
          } else if (inArgsBlock && line.match(/^\s{6,}\w+:/)) {
            const argMatch = line.match(/^\s+(\w+):\s*["']?(.+?)["']?\s*$/);
            if (argMatch) {
              currentArgs[argMatch[1]] = argMatch[2];
            }
          } else if (inArgsBlock && !line.match(/^\s{6,}/)) {
            inArgsBlock = false;
          }
        }
      }

      // Parse inputs section
      if (currentSection === "inputs") {
        const inputMatch = line.match(/^\s+-\s+name:\s*(.+)/);
        if (inputMatch) {
          if (currentInput && currentInput.name) {
            skill.inputs.push({
              name: currentInput.name,
              type: currentInput.type || "string",
              required: currentInput.required === "true",
              default: currentInput.default,
              description: currentInput.description,
            });
          }
          currentInput = { name: inputMatch[1].trim() };
        } else if (currentInput) {
          const typeMatch = line.match(/^\s+type:\s*(.+)/);
          const requiredMatch = line.match(/^\s+required:\s*(.+)/);
          const defaultMatch = line.match(/^\s+default:\s*(.+)/);
          const descMatch = line.match(/^\s+description:\s*["']?(.+?)["']?\s*$/);

          if (typeMatch) currentInput.type = typeMatch[1].trim();
          if (requiredMatch) currentInput.required = requiredMatch[1].trim();
          if (defaultMatch) currentInput.default = defaultMatch[1].trim();
          if (descMatch) currentInput.description = descMatch[1];
        }
      }
    }

    // Save last step
    if (currentStep && currentStep.name) {
      this._analyzeStepLifecycle(currentStep, currentArgs);
      skill.steps.push({
        ...currentStep,
        args: { ...currentArgs },
        status: "pending",
      } as SkillStep);
    }

    // Save last input
    if (currentInput && currentInput.name) {
      skill.inputs.push({
        name: currentInput.name,
        type: currentInput.type || "string",
        required: currentInput.required === "true",
        default: currentInput.default,
        description: currentInput.description,
      });
    }

    return skill;
  }

  /**
   * Analyze a step for memory operations and auto-remediation patterns
   */
  private _analyzeStepLifecycle(
    step: Partial<SkillStep>,
    args: Record<string, string>
  ): void {
    const tool = step.tool || "";
    const name = step.name || "";
    const onError = step.onError || "";

    // Memory read operations
    const memoryReadTools = [
      "memory_read",
      "memory_query",
      "check_known_issues",
      "memory_stats",
    ];
    if (memoryReadTools.some((t) => tool.includes(t))) {
      step.memoryRead = step.memoryRead || [];
      if (args.key) {
        step.memoryRead.push(args.key);
      } else if (tool === "check_known_issues") {
        step.memoryRead.push("learned/patterns", "learned/tool_fixes");
      }
    }

    // Memory write operations
    const memoryWriteTools = [
      "memory_write",
      "memory_update",
      "memory_append",
      "memory_session_log",
      "learn_tool_fix",
    ];
    if (memoryWriteTools.some((t) => tool.includes(t))) {
      step.memoryWrite = step.memoryWrite || [];
      if (args.key) {
        step.memoryWrite.push(args.key);
      } else if (tool === "memory_session_log") {
        step.memoryWrite.push("session_log");
      } else if (tool === "learn_tool_fix") {
        step.memoryWrite.push("learned/tool_fixes");
      }
    }

    // Semantic search operations (knowledge/vector search)
    const semanticSearchTools = [
      "knowledge_query",
      "knowledge_scan",
      "knowledge_search",
      "vector_search",
      "codebase_search",
      "semantic_search",
    ];
    if (semanticSearchTools.some((t) => tool.includes(t))) {
      step.semanticSearch = step.semanticSearch || [];
      const searchType = tool.includes("knowledge")
        ? "knowledge"
        : tool.includes("vector")
          ? "vector"
          : tool.includes("codebase")
            ? "codebase"
            : "semantic";
      step.semanticSearch.push(searchType);
    }

    // Detect memory operations in compute blocks by name patterns
    const memoryReadPatterns = [
      "load_config",
      "read_memory",
      "get_context",
      "check_",
      "validate_",
      "parse_",
    ];
    const memoryWritePatterns = [
      "save_",
      "update_memory",
      "log_session",
      "track_",
      "store_",
    ];

    if (step.compute) {
      if (memoryReadPatterns.some((p) => name.toLowerCase().includes(p))) {
        step.memoryRead = step.memoryRead || [];
        step.memoryRead.push("config/context");
      }
      if (memoryWritePatterns.some((p) => name.toLowerCase().includes(p))) {
        step.memoryWrite = step.memoryWrite || [];
        step.memoryWrite.push("state/context");
      }
    }

    // Auto-remediation detection
    const autoRemediationPatterns = [
      "retry",
      "heal",
      "fix",
      "recover",
      "fallback",
      "remediat",
    ];
    const isAutoRemediation =
      autoRemediationPatterns.some((p) => name.toLowerCase().includes(p)) ||
      autoRemediationPatterns.some((p) => (step.description || "").toLowerCase().includes(p));

    if (isAutoRemediation) {
      step.isAutoRemediation = true;
    }

    // Can retry on error
    if (onError === "continue" || onError === "retry") {
      step.canRetry = true;
    }

    // Jira/GitLab operations often have auto-heal
    const autoHealTools = [
      "jira_",
      "gitlab_",
      "bonfire_",
      "kubectl_",
      "konflux_",
    ];
    if (autoHealTools.some((t) => tool.startsWith(t))) {
      step.canRetry = true;
    }

    // Detect skill_run calls (sub-skill invocations)
    if (tool === "skill_run") {
      step.isSkillCall = true;
      // Extract the skill name from args
      if (args.skill_name) {
        step.calledSkillName = args.skill_name;
      }
    }
  }

  private async _runSkill(skillName: string, inputs: Record<string, unknown>): Promise<void> {
    const inputsJson = JSON.stringify(inputs);
    const command = `skill_run("${skillName}"${inputsJson !== "{}" ? `, '${inputsJson}'` : ""})`;

    // Always copy to clipboard as backup
    await vscode.env.clipboard.writeText(command);

    // Try multiple approaches to send to chat
    let success = false;

    // Approach 1: Try Cursor-specific chat commands
    const cursorChatCommands = [
      // Cursor's internal chat commands (may vary by version)
      { open: "aichat.newchataction", insert: null, send: null },
      { open: "cursor.chat.new", insert: null, send: null },
    ];

    for (const cmds of cursorChatCommands) {
      try {
        await vscode.commands.executeCommand(cmds.open);
        // Small delay to let chat open
        await new Promise(resolve => setTimeout(resolve, 200));
        // Try to type the command using keyboard simulation
        await vscode.commands.executeCommand("type", { text: command });
        success = true;
        vscode.window.showInformationMessage(`🚀 Running: ${skillName} - Press Enter to send!`);
        break;
      } catch {
        // Command not available, try next
      }
    }

    // Approach 2: Try VS Code standard chat API
    if (!success) {
      try {
        // Focus the chat panel
        await vscode.commands.executeCommand("workbench.action.chat.open");
        await new Promise(resolve => setTimeout(resolve, 200));

        // Try to insert text into chat
        try {
          await vscode.commands.executeCommand("chat.insertIntoInput", command);
          success = true;
          vscode.window.showInformationMessage(`🚀 Running: ${skillName} - Press Enter to send!`);
        } catch {
          // insertIntoInput not available, try type command
          try {
            await vscode.commands.executeCommand("type", { text: command });
            success = true;
            vscode.window.showInformationMessage(`🚀 Running: ${skillName} - Press Enter to send!`);
          } catch {
            // type command failed
          }
        }
      } catch {
        // Chat open failed
      }
    }

    // Approach 3: Try workbench.panel.chat focus + paste
    if (!success) {
      try {
        await vscode.commands.executeCommand("workbench.panel.chat.view.copilot.focus");
        await new Promise(resolve => setTimeout(resolve, 200));
        await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
        success = true;
        vscode.window.showInformationMessage(`🚀 Pasted: ${skillName} - Press Enter to send!`);
      } catch {
        // Focus failed
      }
    }

    // Fallback: Show message with instructions
    if (!success) {
      const selection = await vscode.window.showInformationMessage(
        `📋 Copied to clipboard: ${command}`,
        "Open New Chat",
        "Paste (Ctrl+V)"
      );

      if (selection === "Open New Chat") {
        // Try to open any chat
        const openCommands = [
          "workbench.action.chat.open",
          "workbench.action.chat.newChat",
          "aichat.newchataction",
        ];
        for (const cmd of openCommands) {
          try {
            await vscode.commands.executeCommand(cmd);
            break;
          } catch {
            // Try next
          }
        }
      }
    }
  }

  private _updateContent(): void {
    this._panel.webview.html = this._getHtml();
  }

  private _getHtml(): string {
    const nonce = getNonce();
    const exec = this._execution;
    const webview = this._panel.webview;

    // Use webview's cspSource for proper CSP
    const cspSource = webview.cspSource;

    return `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; img-src ${cspSource} data:;">
      <title>Skill Flowchart</title>
      <style>
        ${this._getStyles()}
      </style>
    </head>
    <body>
      ${exec ? this._getExecutionHtml(exec) : this._getSkillPickerHtml()}
      <script nonce="${nonce}">
        ${this._getScript()}
      </script>
    </body>
    </html>`;
  }

  private _getStyles(): string {
    return `
      :root {
        --bg-primary: var(--vscode-editor-background);
        --bg-secondary: var(--vscode-sideBar-background);
        --bg-card: var(--vscode-editorWidget-background);
        --text-primary: var(--vscode-editor-foreground);
        --text-secondary: var(--vscode-descriptionForeground);
        --text-muted: var(--vscode-disabledForeground);
        --border: var(--vscode-widget-border);
        --accent: var(--vscode-button-background);
        --success: #10b981;
        --warning: #f59e0b;
        --error: #ef4444;
        --info: #3b82f6;
        --pending: #6b7280;
        --running: #8b5cf6;
      }

      * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
      }

      body {
        font-family: var(--vscode-font-family);
        font-size: 13px;
        background: var(--bg-primary);
        color: var(--text-primary);
        padding: 12px 16px;
        overflow-x: auto;
      }

      /* Header - Compact for bottom drawer */
      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid var(--border);
      }

      .header h1 {
        font-size: 14px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .header-actions {
        display: flex;
        gap: 8px;
        align-items: center;
      }

      .status-badge {
        padding: 3px 8px;
        border-radius: 10px;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
      }

      .status-badge.idle { background: var(--pending); color: white; }
      .status-badge.running { background: var(--running); color: white; animation: pulse 2s infinite; }
      .status-badge.success { background: var(--success); color: white; }
      .status-badge.failed { background: var(--error); color: white; }

      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.7; }
      }

      /* Skill Picker - Horizontal for bottom drawer */
      .skill-picker {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 20px;
      }

      .skill-picker-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 16px;
      }

      .skill-picker-icon {
        font-size: 32px;
        opacity: 0.8;
      }

      .skill-picker h2 {
        font-size: 16px;
        margin-bottom: 4px;
      }

      .skill-picker p {
        color: var(--text-secondary);
        font-size: 12px;
      }

      .skill-search {
        margin-bottom: 16px;
      }

      .skill-search input {
        width: 100%;
        max-width: 400px;
        padding: 10px 16px;
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--bg-card);
        color: var(--text-primary);
        font-size: 14px;
        outline: none;
        transition: border-color 0.2s;
      }

      .skill-search input:focus {
        border-color: var(--accent);
      }

      .skill-search input::placeholder {
        color: var(--text-secondary);
      }

      .skill-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        justify-content: flex-start;
        max-width: 100%;
        padding: 4px;
      }

      .skill-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 10px 14px;
        cursor: pointer;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 160px;
      }

      .skill-card:hover {
        border-color: var(--accent);
        background: var(--bg-secondary);
      }

      .skill-card-icon {
        font-size: 18px;
      }

      .skill-card-info {
        flex: 1;
        min-width: 0;
      }

      .skill-card-name {
        font-weight: 600;
        font-size: 12px;
      }

      .skill-card-desc {
        font-size: 10px;
        color: var(--text-secondary);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      /* Flowchart Container - Horizontal layout for bottom drawer */
      .flowchart-container {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }

      /* Dynamic flex-wrap flowchart - adjusts to container width */
      .flowchart-horizontal {
        padding: 12px 0;
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

      /* Hide connector on last item (handled via JS class) */
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

      .step-node-h.pending .step-icon-h { border-color: var(--pending); color: var(--pending); }
      .step-node-h.running .step-icon-h {
        border-color: var(--running);
        color: var(--running);
        box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.2);
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
        border-color: var(--pending);
        opacity: 0.5;
      }

      @keyframes pulse-ring {
        0% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
        70% { box-shadow: 0 0 0 8px rgba(139, 92, 246, 0); }
        100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0); }
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
        color: var(--text-muted);
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
      .step-type-h .tag.compute { background: rgba(139, 92, 246, 0.2); color: var(--running); }
      .step-type-h .tag.skill-call { background: rgba(245, 158, 11, 0.3); color: var(--warning); font-weight: 600; }

      .step-duration-h {
        font-size: 9px;
        color: var(--text-muted);
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

      .lifecycle-indicator.auto-heal {
        background: rgba(245, 158, 11, 0.2);
        border-color: var(--warning);
      }

      .lifecycle-indicator.can-retry {
        background: rgba(139, 92, 246, 0.15);
        border-color: var(--running);
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

      .step-node.remediation .step-icon {
        border-style: dashed;
      }

      .step-node.remediation .step-connector {
        border-left: 2px dashed var(--warning);
        background: none;
        width: 0;
      }

      /* Skill call step styling - makes sub-skill calls visually distinct */
      .step-node-h.skill-call .step-icon-h {
        border-width: 3px;
        border-color: var(--warning);
        background: rgba(245, 158, 11, 0.15);
        box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
      }

      .step-node-h.skill-call.pending .step-icon-h {
        border-color: var(--warning);
        color: var(--warning);
      }

      .step-node-h.skill-call .step-name-h {
        color: var(--warning);
      }

      .step-node-h.skill-call .skill-call-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        padding: 2px 6px;
        background: rgba(245, 158, 11, 0.25);
        border: 1px solid var(--warning);
        border-radius: 4px;
        font-size: 10px;
        color: var(--warning);
        margin-top: 4px;
        font-weight: 600;
      }

      .step-node-h.skill-call .skill-call-badge:hover {
        background: rgba(245, 158, 11, 0.35);
        cursor: pointer;
      }

      .step-node.skill-call .step-icon {
        border-width: 3px;
        border-color: var(--warning);
        background: rgba(245, 158, 11, 0.15);
      }

      .step-node.skill-call .step-name {
        color: var(--warning);
      }

      /* Summary Bar */
      .summary-bar {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 8px 12px;
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: 12px;
      }

      .summary-item {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .summary-label {
        color: var(--text-secondary);
      }

      .summary-value {
        font-weight: 600;
      }

      .summary-value.success { color: var(--success); }
      .summary-value.failed { color: var(--error); }
      .summary-value.running { color: var(--running); }

      .progress-bar-inline {
        flex: 1;
        height: 6px;
        background: var(--border);
        border-radius: 3px;
        overflow: hidden;
        min-width: 100px;
        max-width: 200px;
      }

      .progress-fill {
        height: 100%;
        background: var(--success);
        transition: width 0.3s ease;
        border-radius: 3px;
      }

      .progress-fill.running {
        background: linear-gradient(90deg, var(--running), var(--info));
        animation: progress-shimmer 1.5s ease-in-out infinite;
      }

      @keyframes progress-shimmer {
        0% { opacity: 1; }
        50% { opacity: 0.7; }
        100% { opacity: 1; }
      }

      .summary-legend {
        display: flex;
        gap: 8px;
        margin-left: auto;
        padding-left: 16px;
        border-left: 1px solid var(--border);
      }

      .legend-item {
        font-size: 12px;
        cursor: help;
        opacity: 0.7;
        transition: opacity 0.2s;
      }

      .legend-item:hover {
        opacity: 1;
      }

      /* Vertical Flowchart (for detailed view) */
      .flowchart-vertical {
        display: none;
      }

      .flowchart-vertical.show {
        display: block;
      }

      /* Step Node Vertical */
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

      .step-node.pending .step-icon { border-color: var(--pending); color: var(--pending); }
      .step-node.running .step-icon {
        border-color: var(--running);
        color: var(--running);
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
        border-color: var(--pending);
        opacity: 0.5;
      }

      @keyframes spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
      }

      .step-content {
        flex: 1;
        margin-left: 12px;
        min-width: 0;
      }

      .step-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 2px;
      }

      .step-name {
        font-weight: 600;
        font-size: 13px;
      }

      .step-duration {
        font-size: 11px;
        color: var(--text-muted);
        font-family: var(--vscode-editor-font-family);
      }

      .step-desc {
        font-size: 12px;
        color: var(--text-secondary);
        margin-bottom: 4px;
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
        background: var(--bg-secondary);
        color: var(--text-secondary);
        font-family: var(--vscode-editor-font-family);
      }

      .step-tag.tool { background: rgba(59, 130, 246, 0.2); color: var(--info); }
      .step-tag.compute { background: rgba(139, 92, 246, 0.2); color: var(--running); }
      .step-tag.condition { background: rgba(245, 158, 11, 0.2); color: var(--warning); }
      .step-tag.skill-call {
        background: rgba(245, 158, 11, 0.3);
        color: var(--warning);
        font-weight: 600;
        border: 1px solid var(--warning);
        cursor: pointer;
      }
      .step-tag.skill-call:hover {
        background: rgba(245, 158, 11, 0.4);
      }
      .step-tag.memory-read { background: rgba(59, 130, 246, 0.15); color: var(--info); }
      .step-tag.memory-write { background: rgba(16, 185, 129, 0.15); color: var(--success); }
      .step-tag.auto-heal { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
      .step-tag.can-retry { background: rgba(139, 92, 246, 0.1); color: var(--running); }
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

      .step-healed {
        margin-top: 8px;
        padding: 8px;
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid var(--success);
        border-radius: 4px;
        font-size: 12px;
        color: var(--success);
      }

      .step-result {
        margin-top: 8px;
        padding: 8px;
        background: var(--bg-secondary);
        border-radius: 4px;
        font-size: 11px;
        font-family: var(--vscode-editor-font-family);
        max-height: 100px;
        overflow-y: auto;
        white-space: pre-wrap;
        word-break: break-all;
      }

      /* Buttons */
      .btn {
        padding: 5px 10px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 11px;
        font-weight: 500;
        transition: all 0.2s;
      }

      .btn-primary {
        background: var(--accent);
        color: var(--vscode-button-foreground);
      }

      .btn-primary:hover {
        opacity: 0.9;
      }

      .btn-secondary {
        background: var(--bg-secondary);
        border: 1px solid var(--border);
        color: var(--text-primary);
      }

      .btn-secondary:hover {
        background: var(--bg-card);
      }

      .btn-icon {
        padding: 4px 8px;
        background: transparent;
        border: 1px solid var(--border);
        color: var(--text-secondary);
      }

      .btn-icon:hover {
        background: var(--bg-secondary);
        color: var(--text-primary);
      }

      /* View Toggle */
      .view-toggle {
        display: flex;
        gap: 4px;
        background: var(--bg-secondary);
        padding: 2px;
        border-radius: 4px;
      }

      .view-toggle button {
        padding: 4px 8px;
        border: none;
        background: transparent;
        color: var(--text-secondary);
        cursor: pointer;
        border-radius: 3px;
        font-size: 11px;
      }

      .view-toggle button.active {
        background: var(--bg-card);
        color: var(--text-primary);
      }

      .view-toggle button:hover:not(.active) {
        color: var(--text-primary);
      }
    `;
  }

  private _getSkillPickerHtml(): string {
    // Map of skill names to icons and descriptions
    const skillMeta: Record<string, { icon: string; desc: string }> = {
      start_work: { icon: "🚀", desc: "Begin work on Jira issue" },
      create_mr: { icon: "📝", desc: "Create merge request" },
      test_mr_ephemeral: { icon: "🧪", desc: "Test MR in ephemeral" },
      coffee: { icon: "☕", desc: "Morning briefing" },
      beer: { icon: "🍺", desc: "End of day summary" },
      investigate_alert: { icon: "🔍", desc: "Investigate alert" },
      investigate_slack_alert: { icon: "🔔", desc: "Investigate Slack alert" },
      review_pr: { icon: "👀", desc: "Review pull request" },
      review_pr_multiagent: { icon: "👥", desc: "Multi-agent PR review" },
      review_all_prs: { icon: "📋", desc: "Review all open PRs" },
      close_issue: { icon: "✅", desc: "Close Jira issue" },
      close_mr: { icon: "🔒", desc: "Close merge request" },
      standup_summary: { icon: "📊", desc: "Generate standup" },
      memory_view: { icon: "🧠", desc: "View memory" },
      memory_edit: { icon: "✏️", desc: "Edit memory" },
      memory_cleanup: { icon: "🧹", desc: "Cleanup memory" },
      memory_init: { icon: "🔧", desc: "Initialize memory" },
      weekly_summary: { icon: "📅", desc: "Weekly summary" },
      deploy_to_ephemeral: { icon: "🚢", desc: "Deploy to ephemeral" },
      extend_ephemeral: { icon: "⏰", desc: "Extend ephemeral namespace" },
      check_ci_health: { icon: "💚", desc: "Check CI health" },
      check_integration_tests: { icon: "🔬", desc: "Check integration tests" },
      check_mr_feedback: { icon: "💬", desc: "Check MR feedback" },
      check_my_prs: { icon: "📌", desc: "Check my PRs" },
      check_secrets: { icon: "🔐", desc: "Check secrets" },
      ci_retry: { icon: "🔄", desc: "Retry CI pipeline" },
      cancel_pipeline: { icon: "⛔", desc: "Cancel pipeline" },
      cleanup_branches: { icon: "🌿", desc: "Cleanup branches" },
      clone_jira_issue: { icon: "📋", desc: "Clone Jira issue" },
      create_jira_issue: { icon: "🎫", desc: "Create Jira issue" },
      debug_prod: { icon: "🐛", desc: "Debug production" },
      environment_overview: { icon: "🌍", desc: "Environment overview" },
      hotfix: { icon: "🔥", desc: "Create hotfix" },
      jira_hygiene: { icon: "🧼", desc: "Jira hygiene check" },
      konflux_status: { icon: "🔷", desc: "Konflux status" },
      learn_pattern: { icon: "📚", desc: "Learn new pattern" },
      mark_mr_ready: { icon: "✨", desc: "Mark MR ready" },
      notify_mr: { icon: "📣", desc: "Notify about MR" },
      notify_team: { icon: "📢", desc: "Notify team" },
      rebase_pr: { icon: "🔀", desc: "Rebase PR" },
      release_aa_backend_prod: { icon: "🎯", desc: "Release AA backend to prod" },
      release_to_prod: { icon: "🚀", desc: "Release to production" },
      rollout_restart: { icon: "♻️", desc: "Rollout restart" },
      scale_deployment: { icon: "📈", desc: "Scale deployment" },
      scan_vulnerabilities: { icon: "🛡️", desc: "Scan vulnerabilities" },
      schedule_meeting: { icon: "📆", desc: "Schedule meeting" },
      silence_alert: { icon: "🔇", desc: "Silence alert" },
      slack_daemon_control: { icon: "💬", desc: "Slack daemon control" },
      sprint_planning: { icon: "📝", desc: "Sprint planning" },
      suggest_patterns: { icon: "💡", desc: "Suggest patterns" },
      sync_branch: { icon: "🔄", desc: "Sync branch" },
      test_error_recovery: { icon: "🧪", desc: "Test error recovery" },
      update_docs: { icon: "📖", desc: "Update documentation" },
      appinterface_check: { icon: "🔌", desc: "App interface check" },
    };

    const skillCards = this._availableSkills
      .map((name) => {
        const meta = skillMeta[name] || { icon: "⚡", desc: "Workflow skill" };
        return `
          <div class="skill-card" data-skill="${name}">
            <span class="skill-card-icon">${meta.icon}</span>
            <div class="skill-card-info">
              <div class="skill-card-name">${name.replace(/_/g, " ")}</div>
              <div class="skill-card-desc">${meta.desc}</div>
            </div>
          </div>
        `;
      })
      .join("");

    return `
      <div class="header">
        <h1>⚡ Skill Flowchart</h1>
      </div>
      <div class="skill-picker">
        <div class="skill-picker-header">
          <div class="skill-picker-icon">🔄</div>
          <div>
            <h2>Select a Skill to Visualize</h2>
            <p>Choose from ${this._availableSkills.length} available skills</p>
          </div>
        </div>
        <div class="skill-search">
          <input type="text" id="skillSearch" placeholder="🔍 Search skills..." />
        </div>
        <div class="skill-grid" id="skillGrid">
          ${skillCards}
        </div>
      </div>
    `;
  }

  private _getExecutionHtml(exec: SkillExecution): string {
    const skill = exec.skill;
    const completedSteps = skill.steps.filter(
      (s) => s.status === "success" || s.status === "skipped"
    ).length;
    const failedSteps = skill.steps.filter((s) => s.status === "failed").length;
    const runningStep = skill.steps.findIndex((s) => s.status === "running");
    const progress = Math.round((completedSteps / skill.steps.length) * 100);

    // Dynamic flex-wrap flowchart - wraps based on container width
    const horizontalStepsHtml = this._generateFlexFlowchart(skill.steps);

    const statusIcon =
      exec.status === "running"
        ? "🔄"
        : exec.status === "success"
          ? "✅"
          : exec.status === "failed"
            ? "❌"
            : "⏸️";

    const totalTime = exec.totalDuration
      ? this._formatDuration(exec.totalDuration)
      : exec.startTime
        ? this._formatDuration(Date.now() - exec.startTime)
        : "--";

    const currentStepName = runningStep >= 0
      ? skill.steps[runningStep].name
      : completedSteps === skill.steps.length
        ? "Complete"
        : "Ready";

    return `
      <div class="header">
        <h1>${statusIcon} ${skill.name.replace(/_/g, " ")}</h1>
        <div class="header-actions">
          <div class="view-toggle">
            <button class="active" data-view="horizontal">━ Horizontal</button>
            <button data-view="vertical">┃ Vertical</button>
          </div>
          <button class="btn btn-primary" id="runSkillBtn" data-skill="${skill.name}">▶ Run</button>
          <button class="btn btn-secondary" id="backBtn">← Back</button>
        </div>
      </div>

      <div class="summary-bar">
        <div class="summary-item">
          <span class="summary-label">Status:</span>
          <span class="summary-value ${exec.status}">${exec.status}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Step:</span>
          <span class="summary-value">${runningStep >= 0 ? runningStep + 1 : completedSteps}/${skill.steps.length}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">Current:</span>
          <span class="summary-value">${currentStepName}</span>
        </div>
        <div class="progress-bar-inline">
          <div class="progress-fill ${exec.status === "running" ? "running" : ""}" style="width: ${progress}%"></div>
        </div>
        <div class="summary-item">
          <span class="summary-label">Time:</span>
          <span class="summary-value">${totalTime}</span>
        </div>
        ${failedSteps > 0 ? `
        <div class="summary-item">
          <span class="summary-label">Failed:</span>
          <span class="summary-value failed">${failedSteps}</span>
        </div>
        ` : ""}
        <div class="summary-legend">
          <span class="legend-item" title="Calls another skill">⚡</span>
          <span class="legend-item" title="Memory Read">📖</span>
          <span class="legend-item" title="Memory Write">💾</span>
          <span class="legend-item" title="Auto-remediation">🔄</span>
          <span class="legend-item" title="Can Retry">↩️</span>
          <span class="legend-item" title="Healed">✨</span>
        </div>
      </div>

      <div class="flowchart-container">
        <div class="flowchart-horizontal" id="flowchart-horizontal">
          ${horizontalStepsHtml}
        </div>
        <div class="flowchart-vertical" id="flowchart-vertical" style="display: none;">
          ${skill.steps.map((step, index) => this._getStepHtml(step, index)).join("")}
        </div>
      </div>
    `;
  }

  private _generateFlexFlowchart(steps: SkillStep[]): string {
    // Simple flex-wrap layout - browser handles wrapping based on container width
    const stepsHtml = steps.map((step, index) => {
      const isLast = index === steps.length - 1;
      return this._getHorizontalStepHtml(step, index, isLast);
    }).join("");

    return `<div class="flowchart-wrap">${stepsHtml}</div>`;
  }

  private _getHorizontalStepHtml(step: SkillStep, index: number, isLastInRow: boolean = false): string {
    const stepNumber = index + 1;
    const icon = step.isSkillCall ? "⚡" : this._getStepIcon(step.status, stepNumber);
    const duration = step.duration ? this._formatDuration(step.duration) : "";

    // Build type tags
    const typeTags: string[] = [];
    // Show skill call badge prominently instead of generic tool icon
    if (step.isSkillCall) {
      // Don't add generic tool tag for skill calls - we show a special badge below
    } else if (step.tool) {
      typeTags.push(`<span class="tag tool" title="Tool: ${step.tool}">🔧</span>`);
    }
    if (step.compute) typeTags.push(`<span class="tag compute" title="Python compute">🐍</span>`);

    // Build lifecycle indicators
    const lifecycleIndicators: string[] = [];

    // Memory read indicator
    if (step.memoryRead && step.memoryRead.length > 0) {
      const memKeys = step.memoryRead.join(", ");
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator memory-read" title="Memory Read: ${memKeys}">📖</span>`
      );
    }

    // Memory write indicator
    if (step.memoryWrite && step.memoryWrite.length > 0) {
      const memKeys = step.memoryWrite.join(", ");
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator memory-write" title="Memory Write: ${memKeys}">💾</span>`
      );
    }

    // Semantic search indicator
    if (step.semanticSearch && step.semanticSearch.length > 0) {
      const searchTypes = step.semanticSearch.join(", ");
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator semantic-search" title="Semantic Search: ${searchTypes}">🔍</span>`
      );
    }

    // Auto-remediation indicator
    if (step.isAutoRemediation) {
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator auto-heal" title="Auto-remediation step">🔄</span>`
      );
    }

    // Can retry indicator
    if (step.canRetry && !step.isAutoRemediation) {
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator can-retry" title="Can retry on error">↩️</span>`
      );
    }

    // Healing applied indicator (runtime)
    if (step.healingApplied) {
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator healed" title="Auto-heal applied: ${step.healingDetails || 'Fixed'}">✨</span>`
      );
    }

    // Retry count indicator (runtime)
    if (step.retryCount && step.retryCount > 0) {
      lifecycleIndicators.push(
        `<span class="lifecycle-indicator retry-count" title="Retried ${step.retryCount} time(s)">🔁${step.retryCount}</span>`
      );
    }

    // Conditional step indicator
    if (step.condition) {
      typeTags.push(`<span class="tag condition" title="Conditional: ${this._escapeHtml(step.condition)}">❓</span>`);
    }

    const lifecycleHtml = lifecycleIndicators.length > 0
      ? `<div class="step-lifecycle-h">${lifecycleIndicators.join("")}</div>`
      : "";

    const typeTagsHtml = typeTags.length > 0
      ? `<div class="step-type-h">${typeTags.join("")}</div>`
      : "";

    // Build tooltip with full details
    const tooltipParts = [step.description || step.name];
    if (step.isSkillCall && step.calledSkillName) {
      tooltipParts.push(`Calls skill: ${step.calledSkillName}`);
    } else if (step.tool) {
      tooltipParts.push(`Tool: ${step.tool}`);
    }
    if (step.memoryRead?.length) tooltipParts.push(`Reads: ${step.memoryRead.join(", ")}`);
    if (step.memoryWrite?.length) tooltipParts.push(`Writes: ${step.memoryWrite.join(", ")}`);
    if (step.isAutoRemediation) tooltipParts.push("Auto-remediation step");
    const tooltip = tooltipParts.join("\n");

    const rowLastClass = isLastInRow ? "row-last" : "";
    const skillCallClass = step.isSkillCall ? "skill-call" : "";

    // Build skill call badge if this step calls another skill
    const skillCallBadge = step.isSkillCall && step.calledSkillName
      ? `<div class="skill-call-badge" data-skill="${this._escapeHtml(step.calledSkillName)}" title="Click to view ${step.calledSkillName} skill">⚡ ${this._escapeHtml(step.calledSkillName)}</div>`
      : "";

    return `
      <div class="step-node-h ${step.status} ${step.isAutoRemediation ? "remediation" : ""} ${skillCallClass} ${rowLastClass}" title="${this._escapeHtml(tooltip)}">
        <div class="step-connector-h"></div>
        ${lifecycleHtml}
        <div class="step-icon-h">${icon}</div>
        <div class="step-content-h">
          <div class="step-name-h">${this._escapeHtml(step.name)}</div>
          ${typeTagsHtml}
          ${skillCallBadge}
          ${duration ? `<div class="step-duration-h">${duration}</div>` : ""}
        </div>
      </div>
    `;
  }

  private _getStepHtml(step: SkillStep, index: number): string {
    const stepNumber = index + 1;
    const icon = step.isSkillCall ? "⚡" : this._getStepIcon(step.status, stepNumber);
    const duration = step.duration ? this._formatDuration(step.duration) : "";

    // Build tags
    const tags: string[] = [];
    // Show skill call prominently instead of generic tool
    if (step.isSkillCall && step.calledSkillName) {
      tags.push(`<span class="step-tag skill-call" data-skill="${this._escapeHtml(step.calledSkillName)}">⚡ calls: ${step.calledSkillName}</span>`);
    } else if (step.tool) {
      tags.push(`<span class="step-tag tool">🔧 ${step.tool}</span>`);
    }
    if (step.compute) tags.push(`<span class="step-tag compute">🐍 compute</span>`);
    if (step.condition) tags.push(`<span class="step-tag condition">❓ conditional</span>`);

    // Lifecycle tags
    if (step.memoryRead && step.memoryRead.length > 0) {
      tags.push(`<span class="step-tag memory-read">📖 ${step.memoryRead.join(", ")}</span>`);
    }
    if (step.memoryWrite && step.memoryWrite.length > 0) {
      tags.push(`<span class="step-tag memory-write">💾 ${step.memoryWrite.join(", ")}</span>`);
    }
    if (step.semanticSearch && step.semanticSearch.length > 0) {
      tags.push(`<span class="step-tag semantic-search">🔍 ${step.semanticSearch.join(", ")}</span>`);
    }
    if (step.isAutoRemediation) {
      tags.push(`<span class="step-tag auto-heal">🔄 auto-remediation</span>`);
    }
    if (step.canRetry && !step.isAutoRemediation) {
      tags.push(`<span class="step-tag can-retry">↩️ can retry</span>`);
    }
    if (step.healingApplied) {
      tags.push(`<span class="step-tag healed">✨ healed: ${step.healingDetails || "fixed"}</span>`);
    }
    if (step.retryCount && step.retryCount > 0) {
      tags.push(`<span class="step-tag retry-count">🔁 retried ${step.retryCount}x</span>`);
    }

    const skillCallClass = step.isSkillCall ? "skill-call" : "";

    return `
      <div class="step-node ${step.status} ${step.isAutoRemediation ? "remediation" : ""} ${skillCallClass}">
        <div class="step-connector"></div>
        <div class="step-icon">${icon}</div>
        <div class="step-content">
          <div class="step-header">
            <span class="step-name">${this._escapeHtml(step.name)}</span>
            <span class="step-duration">${duration}</span>
          </div>
          ${step.description ? `<div class="step-desc">${this._escapeHtml(step.description)}</div>` : ""}
          ${tags.length > 0 ? `<div class="step-meta">${tags.join("")}</div>` : ""}
          ${step.error ? `<div class="step-error">❌ ${this._escapeHtml(step.error)}</div>` : ""}
          ${step.healingApplied ? `<div class="step-healed">✨ Auto-healed: ${this._escapeHtml(step.healingDetails || "Applied fix")}</div>` : ""}
          ${step.result ? `<div class="step-result">${this._escapeHtml(step.result.slice(0, 300))}</div>` : ""}
        </div>
      </div>
    `;
  }

  private _getInputsHtml(
    inputs: SkillDefinition["inputs"],
    values?: Record<string, unknown>
  ): string {
    const inputItems = inputs
      .slice(0, 5)
      .map((input) => {
        const value = values?.[input.name] ?? input.default ?? "--";
        return `
          <div class="info-item">
            <span class="info-label">${input.name}${input.required ? "*" : ""}</span>
            <span class="info-value">${String(value).slice(0, 20)}</span>
          </div>
        `;
      })
      .join("");

    return `
      <div class="info-section">
        <div class="info-title">Inputs</div>
        ${inputItems}
      </div>
    `;
  }

  private _getStepIcon(status: SkillStep["status"], stepNumber?: number): string {
    switch (status) {
      case "success":
        return "✓";
      case "failed":
        return "✕";
      case "running":
        return "◐";
      case "skipped":
        return "–";
      default:
        // For pending steps, show the step number
        return stepNumber !== undefined ? String(stepNumber) : "○";
    }
  }

  private _formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const mins = Math.floor(ms / 60000);
    const secs = Math.floor((ms % 60000) / 1000);
    return `${mins}m ${secs}s`;
  }

  private _escapeHtml(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  private _getScript(): string {
    return `
      const vscode = acquireVsCodeApi();
      let currentView = 'horizontal';

      function loadSkill(skillName) {
        console.log('loadSkill called with:', skillName);
        vscode.postMessage({ command: 'loadSkill', skillName: skillName || '' });
      }

      function runSkill(skillName) {
        vscode.postMessage({ command: 'runSkill', skillName, inputs: {} });
      }

      function filterSkills(query) {
        const grid = document.getElementById('skillGrid');
        if (!grid) return;

        const cards = grid.querySelectorAll('.skill-card');
        const lowerQuery = query.toLowerCase();

        cards.forEach(card => {
          const skillName = card.getAttribute('data-skill') || '';
          const displayName = skillName.replace(/_/g, ' ');
          const matches = skillName.toLowerCase().includes(lowerQuery) ||
                          displayName.toLowerCase().includes(lowerQuery);
          card.style.display = matches ? 'flex' : 'none';
        });
      }

      function setView(view) {
        currentView = view;
        const horizontal = document.getElementById('flowchart-horizontal');
        const vertical = document.getElementById('flowchart-vertical');
        const buttons = document.querySelectorAll('.view-toggle button');

        if (horizontal && vertical) {
          if (view === 'horizontal') {
            horizontal.style.display = 'block';
            vertical.style.display = 'none';
          } else {
            horizontal.style.display = 'none';
            vertical.style.display = 'block';
          }
        }

        buttons.forEach(btn => {
          btn.classList.remove('active');
          if ((view === 'horizontal' && btn.textContent.includes('Horizontal')) ||
              (view === 'vertical' && btn.textContent.includes('Vertical'))) {
            btn.classList.add('active');
          }
        });
      }

      // Auto-scroll to running step
      function scrollToRunningStep() {
        const runningStep = document.querySelector('.step-node-h.running');
        if (runningStep) {
          runningStep.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
        }
      }

      // Set up event listeners (CSP-compliant, no inline handlers)
      function setupEventListeners() {
        // Skill cards click handler
        document.querySelectorAll('.skill-card').forEach(card => {
          card.addEventListener('click', () => {
            const skillName = card.getAttribute('data-skill');
            if (skillName) loadSkill(skillName);
          });
        });

        // Skill call badges - click to navigate to called skill
        document.querySelectorAll('.skill-call-badge, .step-tag.skill-call').forEach(badge => {
          badge.addEventListener('click', (e) => {
            e.stopPropagation();
            const skillName = badge.getAttribute('data-skill');
            if (skillName) loadSkill(skillName);
          });
        });

        // Search input
        const searchInput = document.getElementById('skillSearch');
        if (searchInput) {
          searchInput.addEventListener('input', (e) => {
            filterSkills(e.target.value);
          });
        }

        // Back button
        const backBtn = document.getElementById('backBtn');
        if (backBtn) {
          backBtn.addEventListener('click', () => loadSkill(''));
        }

        // Run skill button
        const runSkillBtn = document.getElementById('runSkillBtn');
        if (runSkillBtn) {
          runSkillBtn.addEventListener('click', () => {
            const skillName = runSkillBtn.getAttribute('data-skill');
            if (skillName) runSkill(skillName);
          });
        }

        // View toggle buttons
        document.querySelectorAll('.view-toggle button').forEach(btn => {
          btn.addEventListener('click', () => {
            const view = btn.getAttribute('data-view');
            if (view) setView(view);
          });
        });
      }

      // Initialize when DOM is ready
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupEventListeners);
      } else {
        setupEventListeners();
      }

      // Initial scroll
      setTimeout(scrollToRunningStep, 100);
    `;
  }

  public dispose(): void {
    console.log("[SkillFlowchartPanel] ========================================");
    console.log("[SkillFlowchartPanel] dispose() called - clearing currentPanel");
    console.log("[SkillFlowchartPanel] currentPanel before clear:", !!SkillFlowchartPanel.currentPanel);
    SkillFlowchartPanel.currentPanel = undefined;
    console.log("[SkillFlowchartPanel] currentPanel after clear:", SkillFlowchartPanel.currentPanel);
    console.log("[SkillFlowchartPanel] ========================================");
    this._panel.dispose();
    while (this._disposables.length) {
      const x = this._disposables.pop();
      if (x) {
        x.dispose();
      }
    }
  }
}

// ============================================================================
// Utilities
// ============================================================================

function getNonce(): string {
  let text = "";
  const possible =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

// ============================================================================
// Registration
// ============================================================================

/**
 * Get the current flowchart panel instance (if any)
 */
export function getSkillFlowchartPanel(): SkillFlowchartPanel | undefined {
  return SkillFlowchartPanel.currentPanel;
}

export function registerSkillFlowchartPanel(
  context: vscode.ExtensionContext
): void {
  // Register serializer to revive panel after restart
  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer("aaSkillFlowchart", {
      async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel, _state: any) {
        console.log("[SkillFlowchartPanel] Serializer deserializeWebviewPanel called - reviving panel");
        SkillFlowchartPanel.revive(webviewPanel, context.extensionUri);
      }
    })
  );

  console.log("[SkillFlowchartPanel] registerSkillFlowchartPanel complete, serializer registered");
}
