/**
 * Skill Execution Visualizer
 *
 * Shows real-time flowchart of skill execution in a webview panel.
 * Similar to GitHub Actions visualization.
 *
 * Features:
 * - Step-by-step progress
 * - Conditional branch visualization
 * - Duration tracking
 * - Error highlighting
 * - Click to expand step details
 */

import * as vscode from "vscode";
import { exec } from "child_process";
import { promisify } from "util";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

const execAsync = promisify(exec);

interface SkillStep {
  name: string;
  description?: string;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  duration?: number;
  output?: string;
  error?: string;
}

interface SkillExecution {
  skillName: string;
  startTime: Date;
  status: "running" | "success" | "failed";
  steps: SkillStep[];
  totalDuration?: number;
}

export class SkillVisualizerPanel {
  public static currentPanel: SkillVisualizerPanel | undefined;
  private readonly _panel: vscode.WebviewPanel;
  private _disposables: vscode.Disposable[] = [];
  private _execution: SkillExecution | undefined;
  private _pollInterval: NodeJS.Timeout | undefined;

  public static createOrShow(extensionUri: vscode.Uri) {
    const column = vscode.window.activeTextEditor
      ? vscode.window.activeTextEditor.viewColumn
      : undefined;

    if (SkillVisualizerPanel.currentPanel) {
      SkillVisualizerPanel.currentPanel._panel.reveal(column);
      return SkillVisualizerPanel.currentPanel;
    }

    const panel = vscode.window.createWebviewPanel(
      "aaSkillVisualizer",
      "Skill Execution",
      column || vscode.ViewColumn.Two,
      {
        enableScripts: true,
        retainContextWhenHidden: true,
      }
    );

    SkillVisualizerPanel.currentPanel = new SkillVisualizerPanel(
      panel,
      extensionUri
    );
    return SkillVisualizerPanel.currentPanel;
  }

  private constructor(panel: vscode.WebviewPanel, extensionUri: vscode.Uri) {
    this._panel = panel;
    this._updateContent();

    this._panel.onDidDispose(() => this.dispose(), null, this._disposables);

    // Handle messages from webview
    this._panel.webview.onDidReceiveMessage(
      async (message) => {
        switch (message.command) {
          case "expandStep":
            // Could show step details in a new panel
            break;
          case "retry":
            // Could retry failed step
            break;
        }
      },
      null,
      this._disposables
    );
  }

  /**
   * Show execution of a skill
   */
  public showExecution(skillName: string, steps: string[]) {
    this._execution = {
      skillName,
      startTime: new Date(),
      status: "running",
      steps: steps.map((name) => ({
        name,
        status: "pending",
      })),
    };
    this._updateContent();
  }

  /**
   * Update a step's status
   */
  public updateStep(
    stepIndex: number,
    status: SkillStep["status"],
    details?: { duration?: number; output?: string; error?: string }
  ) {
    if (!this._execution || stepIndex >= this._execution.steps.length) return;

    const step = this._execution.steps[stepIndex];
    step.status = status;
    if (details?.duration) step.duration = details.duration;
    if (details?.output) step.output = details.output;
    if (details?.error) step.error = details.error;

    this._updateContent();
  }

  /**
   * Mark execution as complete
   */
  public complete(success: boolean, totalDuration: number) {
    if (!this._execution) return;

    this._execution.status = success ? "success" : "failed";
    this._execution.totalDuration = totalDuration;
    this._updateContent();
  }

  /**
   * Load skill from YAML and show its structure
   */
  public async loadSkillFromFile(skillName: string) {
    try {
      const skillsDir = path.join(
        os.homedir(),
        "src",
        "redhat-ai-workflow",
        "skills"
      );
      const skillPath = path.join(skillsDir, `${skillName}.yaml`);

      if (!fs.existsSync(skillPath)) {
        vscode.window.showErrorMessage(`Skill not found: ${skillName}`);
        return;
      }

      const content = fs.readFileSync(skillPath, "utf-8");

      // Extract steps from YAML
      const steps: string[] = [];
      const stepMatches = content.matchAll(/-\s+name:\s*(.+)/g);
      for (const match of stepMatches) {
        steps.push(match[1].trim());
      }

      if (steps.length > 0) {
        this.showExecution(skillName, steps);
      }
    } catch (e) {
      console.error("Failed to load skill:", e);
    }
  }

  private _updateContent() {
    this._panel.webview.html = this._getHtml();
  }

  private _getHtml(): string {
    const nonce = getNonce();
    const exec = this._execution;

    if (!exec) {
      return this._getEmptyHtml(nonce);
    }

    const stepsHtml = exec.steps
      .map((step, index) => {
        const icon = this._getStepIcon(step.status);
        const statusClass = step.status;
        const duration = step.duration
          ? `${(step.duration / 1000).toFixed(2)}s`
          : "";

        return `
        <div class="step ${statusClass}" data-index="${index}">
          <div class="step-connector ${index === 0 ? "first" : ""}"></div>
          <div class="step-node">
            <div class="step-icon">${icon}</div>
          </div>
          <div class="step-content">
            <div class="step-header">
              <span class="step-name">${index + 1}. ${this._escapeHtml(step.name)}</span>
              <span class="step-duration">${duration}</span>
            </div>
            ${step.description ? `<div class="step-desc">${this._escapeHtml(step.description)}</div>` : ""}
            ${step.error ? `<div class="step-error">❌ ${this._escapeHtml(step.error)}</div>` : ""}
            ${step.output ? `<pre class="step-output">${this._escapeHtml(step.output.slice(0, 500))}</pre>` : ""}
          </div>
        </div>
      `;
      })
      .join("");

    const statusIcon =
      exec.status === "running"
        ? "🔄"
        : exec.status === "success"
          ? "✅"
          : "❌";
    const statusText =
      exec.status === "running"
        ? "Running..."
        : exec.status === "success"
          ? "Completed"
          : "Failed";
    const totalTime = exec.totalDuration
      ? `${(exec.totalDuration / 1000).toFixed(2)}s`
      : "";

    return `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
      <title>Skill Execution</title>
      <style>
        :root {
          --bg-primary: var(--vscode-editor-background);
          --bg-card: var(--vscode-editorWidget-background);
          --text-primary: var(--vscode-editor-foreground);
          --text-secondary: var(--vscode-descriptionForeground);
          --border: var(--vscode-widget-border);
          --success: #10b981;
          --warning: #f59e0b;
          --error: #ef4444;
          --info: #3b82f6;
          --pending: #6b7280;
        }

        * {
          margin: 0;
          padding: 0;
          box-sizing: border-box;
        }

        body {
          font-family: var(--vscode-font-family);
          background: var(--bg-primary);
          color: var(--text-primary);
          padding: 20px;
        }

        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid var(--border);
        }

        .header h1 {
          font-size: 1.25rem;
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .status {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 14px;
        }

        .status.running { color: var(--info); }
        .status.success { color: var(--success); }
        .status.failed { color: var(--error); }

        .timeline {
          position: relative;
          padding-left: 40px;
        }

        .step {
          position: relative;
          margin-bottom: 16px;
          display: flex;
          align-items: flex-start;
        }

        .step-connector {
          position: absolute;
          left: -32px;
          top: 24px;
          bottom: -16px;
          width: 2px;
          background: var(--border);
        }

        .step:last-child .step-connector {
          display: none;
        }

        .step-connector.first {
          top: 12px;
        }

        .step-node {
          position: absolute;
          left: -40px;
          width: 24px;
          height: 24px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 14px;
          background: var(--bg-card);
          border: 2px solid var(--border);
          z-index: 1;
        }

        .step.pending .step-node { border-color: var(--pending); }
        .step.running .step-node { border-color: var(--info); animation: pulse 1.5s infinite; }
        .step.success .step-node { border-color: var(--success); background: var(--success); }
        .step.failed .step-node { border-color: var(--error); background: var(--error); }
        .step.skipped .step-node { border-color: var(--pending); opacity: 0.5; }

        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(59, 130, 246, 0.4); }
          50% { box-shadow: 0 0 0 8px rgba(59, 130, 246, 0); }
        }

        .step-icon {
          font-size: 12px;
        }

        .step.success .step-icon,
        .step.failed .step-icon {
          color: white;
        }

        .step-content {
          flex: 1;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 6px;
          padding: 12px;
        }

        .step.running .step-content {
          border-color: var(--info);
        }

        .step.failed .step-content {
          border-color: var(--error);
        }

        .step-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .step-name {
          font-weight: 600;
        }

        .step-duration {
          color: var(--text-secondary);
          font-size: 12px;
          font-family: var(--vscode-editor-font-family);
        }

        .step-desc {
          color: var(--text-secondary);
          font-size: 13px;
          margin-top: 4px;
        }

        .step-error {
          color: var(--error);
          font-size: 13px;
          margin-top: 8px;
          padding: 8px;
          background: rgba(239, 68, 68, 0.1);
          border-radius: 4px;
        }

        .step-output {
          margin-top: 8px;
          padding: 8px;
          background: var(--bg-primary);
          border-radius: 4px;
          font-family: var(--vscode-editor-font-family);
          font-size: 12px;
          overflow-x: auto;
          white-space: pre-wrap;
          word-break: break-all;
          max-height: 200px;
          overflow-y: auto;
        }

        .summary {
          margin-top: 24px;
          padding: 16px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 8px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .summary-stats {
          display: flex;
          gap: 24px;
        }

        .stat {
          text-align: center;
        }

        .stat-value {
          font-size: 24px;
          font-weight: 600;
        }

        .stat-label {
          font-size: 12px;
          color: var(--text-secondary);
        }
      </style>
    </head>
    <body>
      <div class="header">
        <h1>🔄 ${this._escapeHtml(exec.skillName)}</h1>
        <div class="status ${exec.status}">
          <span>${statusIcon}</span>
          <span>${statusText}</span>
          ${totalTime ? `<span>• ${totalTime}</span>` : ""}
        </div>
      </div>

      <div class="timeline">
        ${stepsHtml}
      </div>

      ${
        exec.status !== "running"
          ? `
      <div class="summary">
        <div class="summary-stats">
          <div class="stat">
            <div class="stat-value">${exec.steps.filter((s) => s.status === "success").length}</div>
            <div class="stat-label">Passed</div>
          </div>
          <div class="stat">
            <div class="stat-value">${exec.steps.filter((s) => s.status === "failed").length}</div>
            <div class="stat-label">Failed</div>
          </div>
          <div class="stat">
            <div class="stat-value">${exec.steps.filter((s) => s.status === "skipped").length}</div>
            <div class="stat-label">Skipped</div>
          </div>
        </div>
        <div>
          <strong>Total:</strong> ${totalTime}
        </div>
      </div>
      `
          : ""
      }

      <script nonce="${nonce}">
        // Could add interactivity here
      </script>
    </body>
    </html>`;
  }

  private _getEmptyHtml(nonce: string): string {
    return `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline';">
      <title>Skill Execution</title>
      <style>
        body {
          font-family: var(--vscode-font-family);
          background: var(--vscode-editor-background);
          color: var(--vscode-editor-foreground);
          padding: 40px;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 80vh;
          text-align: center;
        }
        .icon { font-size: 48px; margin-bottom: 16px; }
        h2 { margin-bottom: 8px; }
        p { color: var(--vscode-descriptionForeground); }
      </style>
    </head>
    <body>
      <div class="icon">🔄</div>
      <h2>No Skill Running</h2>
      <p>Run a skill to see execution progress here.</p>
      <p style="margin-top: 16px;">
        Use <code>AI Workflow: Run Skill...</code> from command palette<br>
        or run a skill from chat.
      </p>
    </body>
    </html>`;
  }

  private _getStepIcon(status: SkillStep["status"]): string {
    switch (status) {
      case "success":
        return "✓";
      case "failed":
        return "✕";
      case "running":
        return "●";
      case "skipped":
        return "○";
      default:
        return "○";
    }
  }

  private _escapeHtml(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  public dispose() {
    SkillVisualizerPanel.currentPanel = undefined;
    if (this._pollInterval) {
      clearInterval(this._pollInterval);
    }
    this._panel.dispose();
    while (this._disposables.length) {
      const x = this._disposables.pop();
      if (x) {
        x.dispose();
      }
    }
  }
}

function getNonce() {
  let text = "";
  const possible =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}

export function registerSkillVisualizer(context: vscode.ExtensionContext) {
  // Command to open visualizer
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openSkillVisualizer", () => {
      SkillVisualizerPanel.createOrShow(context.extensionUri);
    })
  );

  // Command to visualize a specific skill
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.visualizeSkill",
      async (skillName?: string) => {
        if (!skillName) {
          // Show skill picker
          const skillsDir = path.join(
            os.homedir(),
            "src",
            "redhat-ai-workflow",
            "skills"
          );
          try {
            const files = fs.readdirSync(skillsDir).filter((f) => f.endsWith(".yaml"));
            const skills = files.map((f) => f.replace(".yaml", ""));

            skillName = await vscode.window.showQuickPick(skills, {
              placeHolder: "Select a skill to visualize",
            });
          } catch {
            vscode.window.showErrorMessage("Could not list skills");
            return;
          }
        }

        if (skillName) {
          const panel = SkillVisualizerPanel.createOrShow(context.extensionUri);
          await panel.loadSkillFromFile(skillName);
        }
      }
    )
  );
}







