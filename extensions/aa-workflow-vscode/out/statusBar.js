"use strict";
/**
 * Status Bar Manager
 *
 * Creates and manages status bar items showing:
 * - Slack daemon status (online/offline/errors)
 * - Active Jira issue
 * - Environment health (stage/prod)
 * - Active MR status
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
exports.StatusBarManager = void 0;
const vscode = __importStar(require("vscode"));
class StatusBarManager {
    slackItem;
    issueItem;
    envItem;
    mrItem;
    dataProvider;
    constructor(context, dataProvider) {
        this.dataProvider = dataProvider;
        // Create status bar items (right side, ordered by priority)
        // Higher priority = further left
        // Slack status - leftmost
        this.slackItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
        this.slackItem.command = "aa-workflow.showStatus";
        this.slackItem.tooltip = "AI Workflow: Slack Status";
        context.subscriptions.push(this.slackItem);
        // Active issue
        this.issueItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
        this.issueItem.command = "aa-workflow.openJiraIssue";
        this.issueItem.tooltip = "AI Workflow: Click to open in Jira";
        context.subscriptions.push(this.issueItem);
        // Environment health
        this.envItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 98);
        this.envItem.command = "aa-workflow.investigateAlert";
        this.envItem.tooltip = "AI Workflow: Environment Health";
        context.subscriptions.push(this.envItem);
        // Active MR
        this.mrItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 97);
        this.mrItem.command = "aa-workflow.openMR";
        this.mrItem.tooltip = "AI Workflow: Click to open MR";
        context.subscriptions.push(this.mrItem);
        // Initial visibility based on config
        this.updateVisibility();
        // Listen for config changes
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration("aa-workflow")) {
                this.updateVisibility();
                this.update();
            }
        });
    }
    updateVisibility() {
        const config = vscode.workspace.getConfiguration("aa-workflow");
        if (config.get("showSlackStatus", true)) {
            this.slackItem.show();
        }
        else {
            this.slackItem.hide();
        }
        if (config.get("showActiveIssue", true)) {
            this.issueItem.show();
        }
        else {
            this.issueItem.hide();
        }
        if (config.get("showEnvironment", true)) {
            this.envItem.show();
        }
        else {
            this.envItem.hide();
        }
        if (config.get("showActiveMR", true)) {
            this.mrItem.show();
        }
        else {
            this.mrItem.hide();
        }
    }
    update() {
        const status = this.dataProvider.getStatus();
        this.updateSlackItem(status);
        this.updateIssueItem(status);
        this.updateEnvItem(status);
        this.updateMrItem(status);
    }
    updateSlackItem(status) {
        if (!status.slack) {
            this.slackItem.text = "$(circle-slash) Slack";
            this.slackItem.backgroundColor = undefined;
            this.slackItem.tooltip = "Slack daemon not running";
            return;
        }
        if (status.slack.errors > 0) {
            this.slackItem.text = `$(error) Slack: ${status.slack.errors}`;
            this.slackItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
            this.slackItem.tooltip = `Slack daemon has ${status.slack.errors} errors`;
        }
        else if (status.slack.online) {
            this.slackItem.text = "$(check) Slack";
            this.slackItem.backgroundColor = undefined;
            this.slackItem.tooltip = `Slack daemon online\nPolls: ${status.slack.polls}\nProcessed: ${status.slack.processed}`;
        }
        else {
            this.slackItem.text = "$(circle-slash) Slack";
            this.slackItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
            this.slackItem.tooltip = "Slack daemon offline";
        }
    }
    updateIssueItem(status) {
        if (!status.activeIssue) {
            this.issueItem.text = "$(issue-draft) No issue";
            this.issueItem.tooltip = "No active Jira issue";
            return;
        }
        const issue = status.activeIssue;
        this.issueItem.text = `$(issues) ${issue.key}`;
        this.issueItem.tooltip = `${issue.key}: ${issue.summary}\nStatus: ${issue.status}\nBranch: ${issue.branch || "none"}`;
    }
    updateEnvItem(status) {
        const env = status.environment;
        if (!env) {
            this.envItem.text = "$(cloud) Env: ?";
            this.envItem.backgroundColor = undefined;
            this.envItem.tooltip = "Environment status unknown";
            return;
        }
        const alertCount = (env.stageAlerts || 0) + (env.prodAlerts || 0);
        if (env.prodAlerts && env.prodAlerts > 0) {
            // Production alerts - critical
            this.envItem.text = `$(flame) Prod: ${env.prodAlerts}`;
            this.envItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
            this.envItem.tooltip = `⚠️ Production has ${env.prodAlerts} alerts!\nClick to investigate`;
        }
        else if (env.stageAlerts && env.stageAlerts > 0) {
            // Stage alerts - warning
            this.envItem.text = `$(warning) Stage: ${env.stageAlerts}`;
            this.envItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
            this.envItem.tooltip = `Stage has ${env.stageAlerts} alerts\nClick to investigate`;
        }
        else if (alertCount === 0) {
            // All healthy
            this.envItem.text = "$(pass) Env OK";
            this.envItem.backgroundColor = undefined;
            this.envItem.tooltip = "Stage: ✅ Healthy\nProd: ✅ Healthy";
        }
        else {
            this.envItem.text = "$(cloud) Env";
            this.envItem.backgroundColor = undefined;
        }
    }
    updateMrItem(status) {
        if (!status.activeMR) {
            this.mrItem.text = "$(git-pull-request) No MR";
            this.mrItem.tooltip = "No active merge request";
            return;
        }
        const mr = status.activeMR;
        let icon = "$(git-pull-request)";
        let bgColor;
        switch (mr.pipelineStatus) {
            case "success":
            case "passed":
                icon = "$(pass)";
                break;
            case "failed":
                icon = "$(error)";
                bgColor = new vscode.ThemeColor("statusBarItem.errorBackground");
                break;
            case "running":
                icon = "$(sync~spin)";
                break;
            case "pending":
                icon = "$(clock)";
                break;
        }
        this.mrItem.text = `${icon} !${mr.id}`;
        this.mrItem.backgroundColor = bgColor;
        this.mrItem.tooltip = `MR !${mr.id}: ${mr.title}\nPipeline: ${mr.pipelineStatus}\nReviews: ${mr.needsReview ? "Needs review" : "Approved"}`;
    }
    dispose() {
        this.slackItem.dispose();
        this.issueItem.dispose();
        this.envItem.dispose();
        this.mrItem.dispose();
    }
}
exports.StatusBarManager = StatusBarManager;
//# sourceMappingURL=statusBar.js.map
