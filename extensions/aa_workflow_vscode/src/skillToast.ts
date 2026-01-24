/**
 * Skill Toast Manager - Non-blocking toast notifications for skill execution.
 *
 * Features:
 * - Expandable toast showing current skill progress
 * - Real-time step updates via WebSocket
 * - Confirmation dialogs with countdown timer
 * - Timer pauses when user interacts
 * - Stacking support for multiple skills/confirmations
 */

import * as vscode from 'vscode';
import {
  SkillWebSocketClient,
  SkillState,
  PendingConfirmation,
  AutoHealEvent,
  getSkillWebSocketClient,
} from './skillWebSocket';
import { createLogger } from './logger';

const logger = createLogger("SkillToast");

export class SkillToastManager {
  private statusBarItem: vscode.StatusBarItem;
  private wsClient: SkillWebSocketClient;
  private outputChannel: vscode.OutputChannel;

  // Track state for quick access
  private runningSkills: Map<string, SkillState> = new Map();
  private pendingConfirmations: Map<string, PendingConfirmation> = new Map();

  constructor(private readonly context: vscode.ExtensionContext) {
    this.wsClient = getSkillWebSocketClient();
    this.outputChannel = vscode.window.createOutputChannel('Skill Execution');

    // Create status bar item
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      100
    );
    this.statusBarItem.command = 'aa-workflow.showSkillToast';
    context.subscriptions.push(this.statusBarItem);

    // Register commands
    context.subscriptions.push(
      vscode.commands.registerCommand('aa-workflow.showSkillToast', () =>
        this.showDetailedStatus()
      )
    );

    // Subscribe to WebSocket events
    this.setupEventHandlers();

    // Connect to WebSocket
    this.wsClient.connect();

    // Update status bar initially
    this.updateStatusBar();
  }

  private setupEventHandlers(): void {
    // Skill lifecycle
    this.wsClient.onSkillStarted((skill) => {
      this.runningSkills.set(skill.skillId, skill);
      this.updateStatusBar();
      this.showSkillStartedNotification(skill);
      this.logToOutput(`🚀 Skill started: ${skill.skillName}`);
    });

    this.wsClient.onSkillUpdate((skill) => {
      this.runningSkills.set(skill.skillId, skill);
      this.updateStatusBar();
    });

    this.wsClient.onSkillCompleted(({ skillId, success }) => {
      const skill = this.runningSkills.get(skillId);
      if (skill) {
        if (success) {
          this.showSkillCompletedNotification(skill);
          this.logToOutput(`✅ Skill completed: ${skill.skillName}`);
        } else {
          this.showSkillFailedNotification(skill);
          this.logToOutput(`❌ Skill failed: ${skill.skillName}`);
        }
      }

      // Remove after delay
      setTimeout(() => {
        this.runningSkills.delete(skillId);
        this.updateStatusBar();
      }, 5000);
    });

    // Step updates
    this.wsClient.onStepUpdate(({ skillId, step }) => {
      const skill = this.runningSkills.get(skillId);
      if (skill) {
        const statusIcon =
          step.status === 'completed'
            ? '✓'
            : step.status === 'failed'
            ? '✗'
            : step.status === 'running'
            ? '▶'
            : '○';
        this.logToOutput(
          `  ${statusIcon} [${step.index + 1}] ${step.name}${
            step.durationMs ? ` (${(step.durationMs / 1000).toFixed(1)}s)` : ''
          }`
        );
      }
    });

    // Auto-heal events
    this.wsClient.onAutoHeal((event) => {
      this.handleAutoHealEvent(event);
    });

    // Confirmation requests
    this.wsClient.onConfirmationRequired((conf) => {
      this.pendingConfirmations.set(conf.id, conf);
      this.updateStatusBar();
      this.showConfirmationDialog(conf);
    });

    this.wsClient.onConfirmationResolved((id) => {
      this.pendingConfirmations.delete(id);
      this.updateStatusBar();
    });

    // Connection status
    this.wsClient.onConnectionChange((connected) => {
      if (connected) {
        this.logToOutput('🔌 Connected to MCP server');
      } else {
        this.logToOutput('🔌 Disconnected from MCP server');
      }
      this.updateStatusBar();
    });
  }

  private updateStatusBar(): void {
    const skillCount = this.runningSkills.size;
    const confCount = this.pendingConfirmations.size;

    if (skillCount === 0 && confCount === 0) {
      // Show connection status when idle
      if (this.wsClient.isConnected) {
        this.statusBarItem.text = '$(check) Skills';
        this.statusBarItem.tooltip = 'Connected to MCP server - No skills running';
      } else {
        this.statusBarItem.text = '$(debug-disconnect) Skills';
        this.statusBarItem.tooltip = 'Disconnected from MCP server';
      }
      this.statusBarItem.backgroundColor = undefined;
    } else if (confCount > 0) {
      // Confirmation pending - highlight
      this.statusBarItem.text = `$(alert) Skills (${confCount} pending)`;
      this.statusBarItem.tooltip = `${confCount} confirmation(s) waiting`;
      this.statusBarItem.backgroundColor = new vscode.ThemeColor(
        'statusBarItem.warningBackground'
      );
    } else {
      // Skills running
      const skill = Array.from(this.runningSkills.values())[0];
      const progress = skill
        ? Math.round(((skill.currentStep + 1) / skill.totalSteps) * 100)
        : 0;
      this.statusBarItem.text = `$(sync~spin) ${skill?.skillName || 'Skill'} ${progress}%`;
      this.statusBarItem.tooltip = skill
        ? `${skill.skillName}: Step ${skill.currentStep + 1}/${skill.totalSteps} - ${skill.currentStepName}`
        : 'Skills running';
      this.statusBarItem.backgroundColor = undefined;
    }

    this.statusBarItem.show();
  }

  private showSkillStartedNotification(skill: SkillState): void {
    vscode.window
      .showInformationMessage(
        `🚀 Skill started: ${skill.skillName} (${skill.totalSteps} steps)`,
        'Show Output'
      )
      .then((action) => {
        if (action === 'Show Output') {
          this.outputChannel.show();
        }
      });
  }

  private showSkillCompletedNotification(skill: SkillState): void {
    const completedSteps = skill.steps.filter((s) => s.status === 'completed').length;
    vscode.window.showInformationMessage(
      `✅ Skill completed: ${skill.skillName} (${completedSteps}/${skill.totalSteps} steps)`
    );
  }

  private showSkillFailedNotification(skill: SkillState): void {
    const failedStep = skill.steps.find((s) => s.status === 'failed');
    const message = failedStep
      ? `❌ Skill failed: ${skill.skillName} at step "${failedStep.name}"`
      : `❌ Skill failed: ${skill.skillName}`;

    vscode.window
      .showErrorMessage(message, 'Show Output')
      .then((action) => {
        if (action === 'Show Output') {
          this.outputChannel.show();
        }
      });
  }

  private handleAutoHealEvent(event: AutoHealEvent): void {
    if (event.success !== undefined) {
      // Auto-heal completed
      if (event.success) {
        this.logToOutput(`  🩹 Auto-heal successful: ${event.fixAction}`);
        vscode.window.showInformationMessage(
          `🩹 Auto-heal successful: ${event.fixAction}`
        );
      } else {
        this.logToOutput(`  ⚠️ Auto-heal failed: ${event.fixAction}`);
      }
    } else {
      // Auto-heal triggered
      this.logToOutput(
        `  🩹 Auto-heal triggered: ${event.errorType} → ${event.fixAction}`
      );
      vscode.window.showWarningMessage(
        `🩹 Auto-healing ${event.errorType} error with ${event.fixAction}...`
      );
    }
  }

  private async showConfirmationDialog(conf: PendingConfirmation): Promise<void> {
    // Build the message
    let message = `⚠️ Skill paused: ${conf.prompt}`;
    if (conf.claudeSuggestion) {
      message += `\n\n💡 Suggestion: ${conf.claudeSuggestion}`;
    }
    message += `\n\n⏱️ Auto-proceeding in ${conf.timeoutSeconds}s...`;

    // Map options to button labels
    const buttonMap: Record<string, string> = {
      let_claude: 'Let Claude Handle',
      retry_with_fix: 'Retry with Fix',
      abort: 'Abort Skill',
    };

    const buttons = conf.options.map((opt) => buttonMap[opt] || opt);

    // Show dialog with countdown in title
    // Note: VS Code doesn't support dynamic updates to dialogs,
    // so we show a static dialog and rely on the server timeout
    const result = await vscode.window.showWarningMessage(
      message,
      { modal: false },
      ...buttons
    );

    if (result) {
      // Map button back to response
      const responseMap: Record<string, string> = {
        'Let Claude Handle': 'let_claude',
        'Retry with Fix': 'retry_with_fix',
        'Abort Skill': 'abort',
      };
      const response = responseMap[result] || result.toLowerCase().replace(/ /g, '_');

      // Ask about remembering
      const remember = await this.askRememberChoice(conf);

      this.wsClient.respondToConfirmation(conf.id, response, remember);
      this.logToOutput(`  📝 User responded: ${response}`);
    }
    // If no result (dialog dismissed), server timeout will handle it
  }

  private async askRememberChoice(
    conf: PendingConfirmation
  ): Promise<'none' | 'this-error' | 'this-skill' | 'always'> {
    const options = [
      { label: "Don't remember", value: 'none' as const },
      { label: 'Remember for this error type', value: 'this-error' as const },
      { label: 'Remember for this skill', value: 'this-skill' as const },
      { label: 'Always let Claude handle errors', value: 'always' as const },
    ];

    const selected = await vscode.window.showQuickPick(options, {
      placeHolder: 'Remember this choice?',
      title: 'Save Preference',
    });

    return selected?.value || 'none';
  }

  private showDetailedStatus(): void {
    // Show output channel with current status
    this.outputChannel.show();

    // Log current state
    this.logToOutput('\n--- Current Status ---');
    this.logToOutput(`Connected: ${this.wsClient.isConnected}`);
    this.logToOutput(`Running skills: ${this.runningSkills.size}`);
    this.logToOutput(`Pending confirmations: ${this.pendingConfirmations.size}`);

    for (const skill of this.runningSkills.values()) {
      this.logToOutput(
        `\n📋 ${skill.skillName} [${skill.currentStep + 1}/${skill.totalSteps}]`
      );
      this.logToOutput(`   Current: ${skill.currentStepName}`);
      this.logToOutput(`   Status: ${skill.status}`);
    }

    for (const conf of this.pendingConfirmations.values()) {
      this.logToOutput(`\n⚠️ Confirmation: ${conf.prompt}`);
      this.logToOutput(`   Remaining: ${conf.remainingSeconds}s`);
    }

    this.logToOutput('----------------------\n');
  }

  private logToOutput(message: string): void {
    const timestamp = new Date().toLocaleTimeString();
    this.outputChannel.appendLine(`[${timestamp}] ${message}`);
  }

  dispose(): void {
    this.statusBarItem.dispose();
    this.outputChannel.dispose();
  }
}

// ==================== Webview-based Toast (Alternative) ====================

/**
 * A more sophisticated toast using a webview panel.
 * This provides the expandable UI with timer slider as discussed.
 */
export class SkillToastWebview {
  private panel: vscode.WebviewPanel | null = null;
  private wsClient: SkillWebSocketClient;
  private isExpanded = false;
  private isPaused = false;

  constructor(
    private readonly context: vscode.ExtensionContext,
    wsClient?: SkillWebSocketClient
  ) {
    this.wsClient = wsClient || getSkillWebSocketClient();
  }

  show(): void {
    if (this.panel) {
      this.panel.reveal();
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      'skillToast',
      'Skill Status',
      {
        viewColumn: vscode.ViewColumn.Two,
        preserveFocus: true,
      },
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    this.panel.webview.html = this.getWebviewContent();

    // Handle messages from webview
    this.panel.webview.onDidReceiveMessage((message) => {
      switch (message.type) {
        case 'expand':
          this.isExpanded = true;
          break;
        case 'collapse':
          this.isExpanded = false;
          break;
        case 'pause_timer':
          this.isPaused = true;
          if (message.id) {
            this.wsClient.pauseConfirmationTimer(message.id);
          }
          break;
        case 'resume_timer':
          this.isPaused = false;
          if (message.id) {
            this.wsClient.resumeConfirmationTimer(message.id);
          }
          break;
        case 'respond':
          this.wsClient.respondToConfirmation(
            message.id,
            message.response,
            message.remember || 'none'
          );
          break;
        case 'close':
          this.panel?.dispose();
          break;
      }
    });

    // Subscribe to updates
    this.wsClient.onSkillUpdate(() => this.updateWebview());
    this.wsClient.onConfirmationRequired(() => this.updateWebview());
    this.wsClient.onConfirmationResolved(() => this.updateWebview());

    this.panel.onDidDispose(() => {
      this.panel = null;
    });
  }

  private updateWebview(): void {
    if (!this.panel) {
      return;
    }

    const skills = this.wsClient.getRunningSkills();
    const confirmations = this.wsClient.getPendingConfirmations();

    this.panel.webview.postMessage({
      type: 'update',
      skills: skills.map((s) => ({
        ...s,
        startedAt: s.startedAt.toISOString(),
      })),
      confirmations: confirmations.map((c) => ({
        ...c,
        createdAt: c.createdAt.toISOString(),
      })),
      isExpanded: this.isExpanded,
      isPaused: this.isPaused,
    });
  }

  private getWebviewContent(): string {
    return `<!DOCTYPE html>
<html>
<head>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      color: var(--vscode-foreground);
      background: var(--vscode-editor-background);
      padding: 8px;
    }

    .toast {
      background: var(--vscode-notifications-background);
      border: 1px solid var(--vscode-notifications-border);
      border-radius: 4px;
      overflow: hidden;
      margin-bottom: 8px;
    }

    .toast-header {
      display: flex;
      align-items: center;
      padding: 8px 12px;
      cursor: pointer;
      gap: 8px;
    }

    .toast-header:hover {
      background: var(--vscode-list-hoverBackground);
    }

    .skill-icon { font-size: 14px; }
    .skill-name { flex: 1; font-weight: 500; }
    .step-info { color: var(--vscode-descriptionForeground); font-size: 12px; }

    .progress-bar {
      height: 3px;
      background: var(--vscode-progressBar-background);
    }
    .progress-fill {
      height: 100%;
      background: var(--vscode-progressBar-foreground, #0078d4);
      transition: width 0.3s ease;
    }

    .toast-body {
      display: none;
      padding: 12px;
      border-top: 1px solid var(--vscode-notifications-border);
    }
    .toast.expanded .toast-body { display: block; }

    .step-list {
      list-style: none;
      margin-bottom: 12px;
    }
    .step-item {
      display: flex;
      align-items: center;
      padding: 4px 0;
      gap: 8px;
    }
    .step-icon { width: 16px; text-align: center; }
    .step-name { flex: 1; }
    .step-duration { color: var(--vscode-descriptionForeground); font-size: 11px; }

    .step-pending .step-icon { color: var(--vscode-descriptionForeground); }
    .step-running .step-icon { color: var(--vscode-progressBar-foreground); }
    .step-completed .step-icon { color: var(--vscode-testing-iconPassed); }
    .step-failed .step-icon { color: var(--vscode-testing-iconFailed); }

    .confirmation {
      background: var(--vscode-inputValidation-warningBackground);
      border: 1px solid var(--vscode-inputValidation-warningBorder);
      border-radius: 4px;
      padding: 12px;
      margin-top: 12px;
    }

    .confirmation-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    }

    .confirmation-timer {
      margin-left: auto;
      font-weight: bold;
    }

    .confirmation-prompt {
      margin-bottom: 8px;
    }

    .confirmation-suggestion {
      background: var(--vscode-textBlockQuote-background);
      padding: 8px;
      border-radius: 4px;
      margin-bottom: 12px;
      font-size: 12px;
    }

    .timer-bar {
      height: 4px;
      background: var(--vscode-progressBar-background);
      border-radius: 2px;
      margin-bottom: 12px;
      cursor: pointer;
    }
    .timer-fill {
      height: 100%;
      background: var(--vscode-notificationsWarningIcon-foreground, #cca700);
      border-radius: 2px;
      transition: width 1s linear;
    }
    .timer-bar.paused .timer-fill {
      background: var(--vscode-descriptionForeground);
    }

    .confirmation-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .confirmation-actions button {
      padding: 6px 12px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 12px;
    }

    .btn-primary {
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
    }
    .btn-primary:hover {
      background: var(--vscode-button-hoverBackground);
    }

    .btn-secondary {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
    }

    .remember-option {
      margin-top: 8px;
      font-size: 11px;
    }
    .remember-option select {
      margin-left: 8px;
      padding: 2px 4px;
      background: var(--vscode-dropdown-background);
      color: var(--vscode-dropdown-foreground);
      border: 1px solid var(--vscode-dropdown-border);
    }

    .empty-state {
      text-align: center;
      padding: 20px;
      color: var(--vscode-descriptionForeground);
    }
  </style>
</head>
<body>
  <div id="toast-container"></div>

  <script>
    const vscode = acquireVsCodeApi();
    let state = { skills: [], confirmations: [], isExpanded: false, isPaused: false };

    window.addEventListener('message', event => {
      const message = event.data;
      if (message.type === 'update') {
        state = message;
        render();
      }
    });

    function render() {
      const container = document.getElementById('toast-container');

      if (state.skills.length === 0 && state.confirmations.length === 0) {
        container.innerHTML = '<div class="empty-state">No skills running</div>';
        return;
      }

      let html = '';

      // Render each skill
      for (const skill of state.skills) {
        const progress = ((skill.currentStep + 1) / skill.totalSteps) * 100;
        html += \`
          <div class="toast \${state.isExpanded ? 'expanded' : ''}" data-skill-id="\${skill.skillId}">
            <div class="toast-header" onclick="toggleExpand('\${skill.skillId}')">
              <span class="skill-icon">\${skill.status === 'running' ? '▶' : skill.status === 'completed' ? '✓' : '✗'}</span>
              <span class="skill-name">\${skill.skillName}</span>
              <span class="step-info">[\${skill.currentStep + 1}/\${skill.totalSteps}] \${skill.currentStepName || ''}</span>
              <span class="expand-icon">\${state.isExpanded ? '▼' : '▲'}</span>
            </div>

            <div class="progress-bar">
              <div class="progress-fill" style="width: \${progress}%"></div>
            </div>

            <div class="toast-body">
              \${renderSteps(skill)}
            </div>
          </div>
        \`;
      }

      // Render confirmations
      for (const conf of state.confirmations) {
        html += renderConfirmation(conf);
      }

      container.innerHTML = html;
    }

    function renderSteps(skill) {
      const visibleSteps = skill.steps.slice(
        Math.max(0, skill.currentStep - 2),
        skill.currentStep + 3
      );

      return \`
        <ul class="step-list">
          \${visibleSteps.map(step => \`
            <li class="step-item step-\${step.status}">
              <span class="step-icon">
                \${step.status === 'pending' ? '○' :
                  step.status === 'running' ? '▶' :
                  step.status === 'completed' ? '✓' :
                  step.status === 'skipped' ? '⏭' : '✗'}
              </span>
              <span class="step-name">\${step.index + 1}. \${step.name || 'Step'}</span>
              <span class="step-duration">
                \${step.durationMs ? (step.durationMs / 1000).toFixed(1) + 's' :
                  step.status === 'running' ? 'running...' : ''}
              </span>
            </li>
          \`).join('')}
        </ul>
      \`;
    }

    function renderConfirmation(conf) {
      const percent = (conf.remainingSeconds / conf.timeoutSeconds) * 100;

      return \`
        <div class="confirmation" onclick="pauseTimer('\${conf.id}')">
          <div class="confirmation-header">
            <span>⚠️ CONFIRMATION REQUIRED</span>
            <span class="confirmation-timer">\${conf.remainingSeconds}s</span>
          </div>

          <div class="confirmation-prompt">\${conf.prompt}</div>

          \${conf.claudeSuggestion ? \`
            <div class="confirmation-suggestion">
              💡 \${conf.claudeSuggestion}
            </div>
          \` : ''}

          <div class="timer-bar \${state.isPaused ? 'paused' : ''}" onclick="togglePause(event, '\${conf.id}')">
            <div class="timer-fill" style="width: \${percent}%"></div>
          </div>

          <div class="confirmation-actions">
            <button class="btn-primary" onclick="respond('\${conf.id}', 'let_claude')">
              Let Claude Handle
            </button>
            <button class="btn-secondary" onclick="respond('\${conf.id}', 'retry_with_fix')">
              Retry with Fix
            </button>
            <button class="btn-secondary" onclick="respond('\${conf.id}', 'abort')">
              Abort
            </button>
          </div>

          <div class="remember-option">
            <label>
              Remember:
              <select id="remember-\${conf.id}">
                <option value="none">Don't remember</option>
                <option value="this-error">For this error type</option>
                <option value="this-skill">For this skill</option>
                <option value="always">Always let Claude handle</option>
              </select>
            </label>
          </div>
        </div>
      \`;
    }

    function toggleExpand(skillId) {
      vscode.postMessage({ type: state.isExpanded ? 'collapse' : 'expand' });
    }

    function pauseTimer(id) {
      if (!state.isPaused) {
        vscode.postMessage({ type: 'pause_timer', id });
      }
    }

    function togglePause(event, id) {
      event.stopPropagation();
      vscode.postMessage({ type: state.isPaused ? 'resume_timer' : 'pause_timer', id });
    }

    function respond(id, response) {
      const remember = document.getElementById('remember-' + id)?.value || 'none';
      vscode.postMessage({ type: 'respond', id, response, remember });
    }

    // Initial render
    render();
  </script>
</body>
</html>`;
  }

  dispose(): void {
    this.panel?.dispose();
  }
}
