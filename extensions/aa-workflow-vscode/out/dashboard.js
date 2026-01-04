"use strict";
/**
 * Dashboard Webview
 *
 * Rich visual dashboard showing:
 * - Current work overview
 * - Environment health
 * - Recent activity
 * - Quick actions
 *
 * Uses HTML/CSS/JS webview with message passing to extension.
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
exports.DashboardPanel = void 0;
exports.registerDashboard = registerDashboard;
const vscode = __importStar(require("vscode"));
class DashboardPanel {
    static currentPanel;
    _panel;
    _extensionUri;
    _dataProvider;
    _disposables = [];
    static createOrShow(extensionUri, dataProvider) {
        const column = vscode.window.activeTextEditor
            ? vscode.window.activeTextEditor.viewColumn
            : undefined;
        // If we already have a panel, show it
        if (DashboardPanel.currentPanel) {
            DashboardPanel.currentPanel._panel.reveal(column);
            DashboardPanel.currentPanel.update();
            return;
        }
        // Create a new panel
        const panel = vscode.window.createWebviewPanel("aaWorkflowDashboard", "AI Workflow Dashboard", column || vscode.ViewColumn.One, {
            enableScripts: true,
            retainContextWhenHidden: true,
            localResourceRoots: [extensionUri],
        });
        DashboardPanel.currentPanel = new DashboardPanel(panel, extensionUri, dataProvider);
    }
    constructor(panel, extensionUri, dataProvider) {
        this._panel = panel;
        this._extensionUri = extensionUri;
        this._dataProvider = dataProvider;
        // Set initial content
        this.update();
        // Listen for when the panel is disposed
        this._panel.onDidDispose(() => this.dispose(), null, this._disposables);
        // Handle messages from the webview
        this._panel.webview.onDidReceiveMessage(async (message) => {
            switch (message.command) {
                case "refresh":
                    await this._dataProvider.refresh();
                    this.update();
                    break;
                case "openJira":
                    vscode.commands.executeCommand("aa-workflow.openJiraIssue");
                    break;
                case "openMR":
                    vscode.commands.executeCommand("aa-workflow.openMR");
                    break;
                case "investigate":
                    vscode.commands.executeCommand("aa-workflow.investigateAlert");
                    break;
                case "runSkill":
                    vscode.commands.executeCommand("aa-workflow.runSkill");
                    break;
            }
        }, null, this._disposables);
    }
    update() {
        const status = this._dataProvider.getStatus();
        this._panel.webview.html = this._getHtmlForWebview(status);
    }
    _getHtmlForWebview(status) {
        const nonce = getNonce();
        // Build data for the dashboard
        const issueHtml = status.activeIssue
            ? `<div class="card issue-card">
          <div class="card-icon">📋</div>
          <div class="card-content">
            <div class="card-title">${status.activeIssue.key}</div>
            <div class="card-subtitle">${this._escapeHtml(status.activeIssue.summary)}</div>
            <div class="card-meta">
              <span class="badge ${this._getStatusClass(status.activeIssue.status)}">${status.activeIssue.status}</span>
              ${status.activeIssue.branch ? `<span class="branch">🌿 ${status.activeIssue.branch}</span>` : ""}
            </div>
          </div>
          <button class="card-action" onclick="openJira()">Open</button>
        </div>`
            : `<div class="card empty-card">
          <div class="card-icon">📋</div>
          <div class="card-content">
            <div class="card-title">No Active Issue</div>
            <div class="card-subtitle">Use /start-work to begin</div>
          </div>
        </div>`;
        const mrHtml = status.activeMR
            ? `<div class="card mr-card">
          <div class="card-icon">🔀</div>
          <div class="card-content">
            <div class="card-title">!${status.activeMR.id}</div>
            <div class="card-subtitle">${this._escapeHtml(status.activeMR.title)}</div>
            <div class="card-meta">
              <span class="badge ${this._getPipelineClass(status.activeMR.pipelineStatus)}">${this._getPipelineIcon(status.activeMR.pipelineStatus)} ${status.activeMR.pipelineStatus}</span>
              ${status.activeMR.needsReview ? '<span class="badge warning">Needs Review</span>' : ""}
            </div>
          </div>
          <button class="card-action" onclick="openMR()">Open</button>
        </div>`
            : `<div class="card empty-card">
          <div class="card-icon">🔀</div>
          <div class="card-content">
            <div class="card-title">No Active MR</div>
            <div class="card-subtitle">Use /create-mr to create</div>
          </div>
        </div>`;
        const envHtml = this._getEnvironmentHtml(status);
        const followUpsHtml = this._getFollowUpsHtml(status);
        const namespacesHtml = this._getNamespacesHtml(status);
        return `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
      <title>AI Workflow Dashboard</title>
      <style>
        :root {
          --bg-primary: var(--vscode-editor-background);
          --bg-secondary: var(--vscode-sideBar-background);
          --bg-card: var(--vscode-editorWidget-background);
          --text-primary: var(--vscode-editor-foreground);
          --text-secondary: var(--vscode-descriptionForeground);
          --border: var(--vscode-widget-border);
          --accent: var(--vscode-button-background);
          --success: #10b981;
          --warning: #f59e0b;
          --error: #ef4444;
          --info: #3b82f6;
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
          line-height: 1.5;
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
          font-size: 1.5rem;
          font-weight: 600;
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .header-actions {
          display: flex;
          gap: 8px;
        }

        .btn {
          padding: 6px 12px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 13px;
          background: var(--accent);
          color: var(--vscode-button-foreground);
          transition: opacity 0.2s;
        }

        .btn:hover {
          opacity: 0.9;
        }

        .btn-secondary {
          background: var(--bg-secondary);
          border: 1px solid var(--border);
          color: var(--text-primary);
        }

        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
          gap: 16px;
          margin-bottom: 24px;
        }

        .section {
          margin-bottom: 24px;
        }

        .section-title {
          font-size: 1rem;
          font-weight: 600;
          margin-bottom: 12px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .card {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 16px;
          display: flex;
          align-items: flex-start;
          gap: 12px;
          transition: border-color 0.2s;
        }

        .card:hover {
          border-color: var(--accent);
        }

        .card-icon {
          font-size: 24px;
          flex-shrink: 0;
        }

        .card-content {
          flex: 1;
          min-width: 0;
        }

        .card-title {
          font-weight: 600;
          margin-bottom: 4px;
        }

        .card-subtitle {
          color: var(--text-secondary);
          font-size: 13px;
          margin-bottom: 8px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .card-meta {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          align-items: center;
        }

        .card-action {
          padding: 6px 12px;
          border: 1px solid var(--border);
          border-radius: 4px;
          background: transparent;
          color: var(--text-primary);
          cursor: pointer;
          font-size: 12px;
          flex-shrink: 0;
        }

        .card-action:hover {
          background: var(--bg-secondary);
        }

        .badge {
          padding: 2px 8px;
          border-radius: 12px;
          font-size: 11px;
          font-weight: 500;
          text-transform: uppercase;
        }

        .badge.success { background: var(--success); color: white; }
        .badge.warning { background: var(--warning); color: black; }
        .badge.error { background: var(--error); color: white; }
        .badge.info { background: var(--info); color: white; }
        .badge.neutral { background: var(--bg-secondary); color: var(--text-primary); }

        .branch {
          font-size: 12px;
          color: var(--text-secondary);
          font-family: var(--vscode-editor-font-family);
        }

        .env-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          gap: 12px;
        }

        .env-card {
          padding: 12px;
          border-radius: 6px;
          text-align: center;
        }

        .env-card.healthy {
          background: rgba(16, 185, 129, 0.1);
          border: 1px solid var(--success);
        }

        .env-card.warning {
          background: rgba(245, 158, 11, 0.1);
          border: 1px solid var(--warning);
        }

        .env-card.critical {
          background: rgba(239, 68, 68, 0.1);
          border: 1px solid var(--error);
        }

        .env-name {
          font-weight: 600;
          margin-bottom: 4px;
        }

        .env-status {
          font-size: 24px;
        }

        .list {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .list-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 8px 12px;
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 6px;
          font-size: 13px;
        }

        .list-item-icon {
          flex-shrink: 0;
        }

        .list-item-content {
          flex: 1;
          min-width: 0;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .list-item-meta {
          color: var(--text-secondary);
          font-size: 12px;
          flex-shrink: 0;
        }

        .empty-state {
          color: var(--text-secondary);
          font-style: italic;
          padding: 12px;
        }

        .quick-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }

        .quick-action {
          padding: 8px 16px;
          border: 1px solid var(--border);
          border-radius: 6px;
          background: var(--bg-card);
          color: var(--text-primary);
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 13px;
          transition: all 0.2s;
        }

        .quick-action:hover {
          background: var(--accent);
          color: var(--vscode-button-foreground);
          border-color: var(--accent);
        }

        .timestamp {
          color: var(--text-secondary);
          font-size: 12px;
        }
      </style>
    </head>
    <body>
      <div class="header">
        <h1>🚀 AI Workflow Dashboard</h1>
        <div class="header-actions">
          <span class="timestamp">Updated: ${status.lastUpdated ? new Date(status.lastUpdated).toLocaleTimeString() : "Never"}</span>
          <button class="btn btn-secondary" onclick="refresh()">↻ Refresh</button>
        </div>
      </div>

      <div class="section">
        <div class="section-title">📋 Current Work</div>
        <div class="grid">
          ${issueHtml}
          ${mrHtml}
        </div>
      </div>

      <div class="section">
        <div class="section-title">🌍 Environments</div>
        ${envHtml}
      </div>

      <div class="grid">
        <div class="section">
          <div class="section-title">🚀 Namespaces</div>
          ${namespacesHtml}
        </div>
        <div class="section">
          <div class="section-title">📝 Follow-ups</div>
          ${followUpsHtml}
        </div>
      </div>

      <div class="section">
        <div class="section-title">⚡ Quick Actions</div>
        <div class="quick-actions">
          <button class="quick-action" onclick="runSkill()">🎯 Run Skill</button>
          <button class="quick-action" onclick="vscode.postMessage({command: 'coffee'})">☕ Coffee</button>
          <button class="quick-action" onclick="vscode.postMessage({command: 'beer'})">🍺 Beer</button>
          <button class="quick-action" onclick="investigate()">🔍 Investigate</button>
        </div>
      </div>

      <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();

        function refresh() {
          vscode.postMessage({ command: 'refresh' });
        }

        function openJira() {
          vscode.postMessage({ command: 'openJira' });
        }

        function openMR() {
          vscode.postMessage({ command: 'openMR' });
        }

        function investigate() {
          vscode.postMessage({ command: 'investigate' });
        }

        function runSkill() {
          vscode.postMessage({ command: 'runSkill' });
        }
      </script>
    </body>
    </html>`;
    }
    _getEnvironmentHtml(status) {
        const env = status.environment;
        if (!env) {
            return '<div class="empty-state">Environment status unknown</div>';
        }
        const stageClass = env.stageAlerts > 0
            ? env.stageAlerts > 2
                ? "critical"
                : "warning"
            : "healthy";
        const prodClass = env.prodAlerts > 0
            ? env.prodAlerts > 2
                ? "critical"
                : "warning"
            : "healthy";
        return `<div class="env-grid">
      <div class="env-card ${stageClass}">
        <div class="env-status">${stageClass === "healthy" ? "✅" : stageClass === "warning" ? "⚠️" : "🔴"}</div>
        <div class="env-name">Stage</div>
        <div class="env-alerts">${env.stageAlerts} alerts</div>
      </div>
      <div class="env-card ${prodClass}">
        <div class="env-status">${prodClass === "healthy" ? "✅" : prodClass === "warning" ? "⚠️" : "🔴"}</div>
        <div class="env-name">Production</div>
        <div class="env-alerts">${env.prodAlerts} alerts</div>
      </div>
    </div>`;
    }
    _getFollowUpsHtml(status) {
        if (!status.followUps || status.followUps.length === 0) {
            return '<div class="empty-state">No follow-ups</div>';
        }
        const items = status.followUps
            .slice(0, 5)
            .map((fu) => {
            const icon = fu.priority === "high"
                ? "🔴"
                : fu.priority === "medium"
                    ? "🟡"
                    : "⚪";
            return `<div class="list-item">
        <span class="list-item-icon">${icon}</span>
        <span class="list-item-content">${this._escapeHtml(fu.task)}</span>
        <span class="list-item-meta">${fu.due || ""}</span>
      </div>`;
        })
            .join("");
        return `<div class="list">${items}</div>`;
    }
    _getNamespacesHtml(status) {
        if (!status.namespaces || status.namespaces.length === 0) {
            return '<div class="empty-state">No active namespaces</div>';
        }
        const items = status.namespaces
            .map((ns) => {
            const icon = ns.status === "active" ? "🟢" : "⚪";
            return `<div class="list-item">
        <span class="list-item-icon">${icon}</span>
        <span class="list-item-content">${ns.name}</span>
        <span class="list-item-meta">${ns.expires || ""}</span>
      </div>`;
        })
            .join("");
        return `<div class="list">${items}</div>`;
    }
    _getStatusClass(status) {
        const lower = status.toLowerCase();
        if (lower.includes("done") || lower.includes("closed"))
            return "success";
        if (lower.includes("progress"))
            return "info";
        if (lower.includes("blocked"))
            return "error";
        return "neutral";
    }
    _getPipelineClass(status) {
        switch (status) {
            case "success":
            case "passed":
                return "success";
            case "failed":
                return "error";
            case "running":
                return "info";
            default:
                return "neutral";
        }
    }
    _getPipelineIcon(status) {
        switch (status) {
            case "success":
            case "passed":
                return "✅";
            case "failed":
                return "❌";
            case "running":
                return "🔄";
            case "pending":
                return "⏳";
            default:
                return "❓";
        }
    }
    _escapeHtml(text) {
        return text
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }
    dispose() {
        DashboardPanel.currentPanel = undefined;
        this._panel.dispose();
        while (this._disposables.length) {
            const x = this._disposables.pop();
            if (x) {
                x.dispose();
            }
        }
    }
}
exports.DashboardPanel = DashboardPanel;
function getNonce() {
    let text = "";
    const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
function registerDashboard(context, dataProvider) {
    context.subscriptions.push(vscode.commands.registerCommand("aa-workflow.openDashboard", () => {
        DashboardPanel.createOrShow(context.extensionUri, dataProvider);
    }));
}
//# sourceMappingURL=dashboard.js.map
