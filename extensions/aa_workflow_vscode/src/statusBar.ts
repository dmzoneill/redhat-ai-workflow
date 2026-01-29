/**
 * Status Bar Manager
 *
 * Creates and manages status bar items showing:
 * - Active Jira issue (clickable)
 * - Environment health (stage/prod with alert counts)
 * - Active MR status with pipeline indicator
 * - Active agent/persona
 * - Slack daemon status
 * - Ephemeral namespace (when deployed)
 *
 * Design goals:
 * - Compact but informative
 * - Color-coded status at a glance
 * - Rich tooltips with actions
 * - Consistent iconography
 */

import * as vscode from "vscode";
import { WorkflowDataProvider, WorkflowStatus } from "./dataProvider";

// Status bar priority order (higher = further left)
const PRIORITY = {
  VPN: 104,
  AGENT: 103,
  SLACK: 102,
  ISSUE: 101,
  ENV: 100,
  MR: 99,
  NAMESPACE: 98,
};

export class StatusBarManager {
  private vpnItem: vscode.StatusBarItem;
  private agentItem: vscode.StatusBarItem;
  private slackItem: vscode.StatusBarItem;
  private issueItem: vscode.StatusBarItem;
  private envItem: vscode.StatusBarItem;
  private mrItem: vscode.StatusBarItem;
  private namespaceItem: vscode.StatusBarItem;

  private dataProvider: WorkflowDataProvider;
  private currentAgent: string = "";
  private slackPendingCount: number = 0;

  constructor(
    context: vscode.ExtensionContext,
    dataProvider: WorkflowDataProvider
  ) {
    this.dataProvider = dataProvider;

    // VPN status - only shown when disconnected
    this.vpnItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.VPN
    );
    this.vpnItem.name = "VPN Status";
    this.vpnItem.command = "aa-workflow.openCommandCenter";
    context.subscriptions.push(this.vpnItem);

    // Agent/Persona indicator - shows which mode we're in
    this.agentItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.AGENT
    );
    this.agentItem.name = "AI Workflow Agent";
    this.agentItem.command = "aa-workflow.switchAgent";
    context.subscriptions.push(this.agentItem);

    // Slack status
    this.slackItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.SLACK
    );
    this.slackItem.name = "Slack Daemon";
    this.slackItem.command = "aa-workflow.showStatus";
    context.subscriptions.push(this.slackItem);

    // Active issue
    this.issueItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.ISSUE
    );
    this.issueItem.name = "Active Jira Issue";
    this.issueItem.command = "aa-workflow.openJiraIssue";
    context.subscriptions.push(this.issueItem);

    // Environment health
    this.envItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.ENV
    );
    this.envItem.name = "Environment Status";
    this.envItem.command = "aa-workflow.investigateAlert";
    context.subscriptions.push(this.envItem);

    // Active MR with pipeline
    this.mrItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.MR
    );
    this.mrItem.name = "Active Merge Request";
    this.mrItem.command = "aa-workflow.openMR";
    context.subscriptions.push(this.mrItem);

    // Ephemeral namespace
    this.namespaceItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Right,
      PRIORITY.NAMESPACE
    );
    this.namespaceItem.name = "Ephemeral Namespace";
    this.namespaceItem.command = "aa-workflow.showNamespace";
    context.subscriptions.push(this.namespaceItem);

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

  private updateVisibility() {
    const config = vscode.workspace.getConfiguration("aa-workflow");

    // Agent always shown
    this.agentItem.show();

    if (config.get<boolean>("showSlackStatus", true)) {
      this.slackItem.show();
    } else {
      this.slackItem.hide();
    }

    if (config.get<boolean>("showActiveIssue", true)) {
      this.issueItem.show();
    } else {
      this.issueItem.hide();
    }

    if (config.get<boolean>("showEnvironment", true)) {
      this.envItem.show();
    } else {
      this.envItem.hide();
    }

    if (config.get<boolean>("showActiveMR", true)) {
      this.mrItem.show();
    } else {
      this.mrItem.hide();
    }

    // Namespace only shown when active
    // (controlled in updateNamespaceItem)
  }

  public update() {
    const status = this.dataProvider.getStatus();
    this.updateVpnItem(status);
    this.updateAgentItem();
    this.updateSlackItem(status);
    this.updateIssueItem(status);
    this.updateEnvItem(status);
    this.updateMrItem(status);
    this.updateNamespaceItem(status);
  }

  public setAgent(agent: string) {
    this.currentAgent = agent;
    this.updateAgentItem();
  }

  /**
   * Update the Slack pending count (called from notification manager)
   */
  public setSlackPendingCount(count: number) {
    this.slackPendingCount = count;
    this.updateSlackItem(this.dataProvider.getStatus());
  }

  private updateVpnItem(status: WorkflowStatus) {
    if (!status.vpn || status.vpn.connected) {
      // VPN connected or unknown - hide the warning
      this.vpnItem.hide();
      return;
    }

    // VPN disconnected - show warning
    this.vpnItem.text = "$(shield) VPN Off";
    this.vpnItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
    this.vpnItem.color = undefined;
    this.vpnItem.tooltip = new vscode.MarkdownString(
      `### $(shield) VPN Not Connected\n\n` +
        `**Status:** Disconnected\n\n` +
        `⚠️ Connect to Red Hat VPN for:\n` +
        `- GitLab access\n` +
        `- Internal services\n\n` +
        `_Note: Jira is accessible without VPN_\n\n` +
        `---\n` +
        `Click to open Command Center`,
      true
    );
    this.vpnItem.tooltip.isTrusted = true;
    this.vpnItem.show();
  }

  private updateAgentItem() {
    const agentIcons: Record<string, string> = {
      developer: "$(code)",
      devops: "$(server-process)",
      incident: "$(flame)",
      release: "$(package)",
      "": "$(robot)",
    };

    const agentColors: Record<string, string> = {
      developer: "charts.blue",
      devops: "charts.green",
      incident: "charts.red",
      release: "charts.purple",
    };

    // Get workspace info for enhanced display
    const workspaceInfo = this.dataProvider.getWorkspaceInfo?.() || {};
    const persona = workspaceInfo.persona || this.currentAgent || "";
    const project = workspaceInfo.project || workspaceInfo.auto_detected_project || "";

    const agent = persona || "";
    const icon = agentIcons[agent] || "$(robot)";
    const displayName = agent
      ? agent.charAt(0).toUpperCase() + agent.slice(1)
      : "Core";

    // Show project in status bar if available
    if (project) {
      const shortProject = project.split("/").pop() || project;
      this.agentItem.text = `${icon} ${displayName} • ${shortProject}`;
    } else {
      this.agentItem.text = `${icon} ${displayName}`;
    }

    if (agent && agentColors[agent]) {
      // Use a subtle color indicator
      this.agentItem.color = new vscode.ThemeColor(agentColors[agent]);
    } else {
      this.agentItem.color = undefined;
    }

    // Build tooltip with workspace context
    let tooltipContent = `### $(robot) AI Workflow Agent\n\n`;
    tooltipContent += `**Persona:** ${displayName}\n`;

    if (project) {
      tooltipContent += `**Project:** ${project}\n`;
    }

    if (workspaceInfo.issue_key) {
      tooltipContent += `**Issue:** ${workspaceInfo.issue_key}\n`;
    }

    if (workspaceInfo.branch) {
      tooltipContent += `**Branch:** ${workspaceInfo.branch}\n`;
    }

    const toolCount = workspaceInfo.active_tools?.length || 0;
    if (toolCount > 0) {
      tooltipContent += `**Tools:** ${toolCount} active\n`;
    }

    tooltipContent += `\n---\n\n`;
    tooltipContent += `Click to switch agents:\n`;
    tooltipContent += `- $(code) Developer - coding, PRs\n`;
    tooltipContent += `- $(server-process) DevOps - deployments, k8s\n`;
    tooltipContent += `- $(flame) Incident - production issues\n`;
    tooltipContent += `- $(package) Release - shipping`;

    this.agentItem.tooltip = new vscode.MarkdownString(tooltipContent, true);
    this.agentItem.tooltip.isTrusted = true;
  }

  private updateSlackItem(status: WorkflowStatus) {
    if (!status.slack) {
      this.slackItem.text = "$(circle-slash) Slack";
      this.slackItem.backgroundColor = undefined;
      this.slackItem.color = new vscode.ThemeColor("disabledForeground");
      this.slackItem.tooltip = new vscode.MarkdownString(
        `### $(circle-slash) Slack Daemon\n\n` +
          `**Status:** Not running\n\n` +
          `_Start the daemon to receive Slack notifications_`,
        true
      );
      return;
    }

    if (status.slack.errors > 0) {
      this.slackItem.text = `$(error) Slack ${status.slack.errors}`;
      this.slackItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.errorBackground"
      );
      this.slackItem.color = undefined;
      this.slackItem.tooltip = new vscode.MarkdownString(
        `### $(error) Slack Daemon Error\n\n` +
          `**Errors:** ${status.slack.errors}\n\n` +
          `Click to view details and clear errors.`,
        true
      );
    } else if (status.slack.online) {
      // Show pending count badge if there are pending messages
      const pendingBadge = this.slackPendingCount > 0 ? ` (${this.slackPendingCount})` : "";
      const pendingIcon = this.slackPendingCount > 0 ? "$(bell-dot)" : "$(check)";

      this.slackItem.text = `${pendingIcon} Slack${pendingBadge}`;

      if (this.slackPendingCount > 0) {
        this.slackItem.backgroundColor = new vscode.ThemeColor(
          "statusBarItem.warningBackground"
        );
        this.slackItem.color = undefined;
      } else {
        this.slackItem.backgroundColor = undefined;
        this.slackItem.color = new vscode.ThemeColor("charts.green");
      }

      // Build tooltip with pending info
      let tooltipContent = `### ${pendingIcon} Slack Daemon Online\n\n`;

      if (this.slackPendingCount > 0) {
        tooltipContent += `**⏳ ${this.slackPendingCount} pending approval${this.slackPendingCount > 1 ? "s" : ""}**\n\n`;
      }

      tooltipContent += `| Metric | Value |\n`;
      tooltipContent += `|--------|-------|\n`;
      tooltipContent += `| Polls | ${status.slack.polls} |\n`;
      tooltipContent += `| Processed | ${status.slack.processed} |\n`;
      tooltipContent += `| Responded | ${status.slack.responded} |`;

      if (this.slackPendingCount > 0) {
        tooltipContent += `\n\n---\n$(bell) Click to view pending messages`;
      }

      this.slackItem.tooltip = new vscode.MarkdownString(tooltipContent, true);
      this.slackItem.tooltip.isTrusted = true;
    } else {
      this.slackItem.text = "$(circle-slash) Slack";
      this.slackItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.warningBackground"
      );
      this.slackItem.color = undefined;
      this.slackItem.tooltip = new vscode.MarkdownString(
        `### $(warning) Slack Daemon Offline\n\n` +
          `The daemon is installed but not responding.\n\n` +
          `Click to restart.`,
        true
      );
    }
  }

  private updateIssueItem(status: WorkflowStatus) {
    if (!status.activeIssue) {
      this.issueItem.text = "$(issue-draft) No issue";
      this.issueItem.color = new vscode.ThemeColor("disabledForeground");
      this.issueItem.backgroundColor = undefined;
      this.issueItem.tooltip = new vscode.MarkdownString(
        `### $(issue-draft) No Active Issue\n\n` +
          `Use \`/start AAP-XXXXX\` or run the **Start Work** command to begin.`,
        true
      );
      return;
    }

    const issue = status.activeIssue;
    const statusIcon = this.getIssueStatusIcon(issue.status);

    this.issueItem.text = `$(issues) ${issue.key}`;
    this.issueItem.color = undefined;
    this.issueItem.backgroundColor = undefined;

    const branchInfo = issue.branch
      ? `\n**Branch:** \`${issue.branch}\``
      : "\n_No branch created_";

    this.issueItem.tooltip = new vscode.MarkdownString(
      `### $(issues) ${issue.key}\n\n` +
        `**${issue.summary}**\n\n` +
        `${statusIcon} **Status:** ${issue.status}${branchInfo}\n\n` +
        `---\n` +
        `$(link-external) Click to open in Jira`,
      true
    );
    this.issueItem.tooltip.isTrusted = true;
  }

  private getIssueStatusIcon(status: string): string {
    const statusLower = status.toLowerCase();
    if (statusLower.includes("done") || statusLower.includes("closed")) {
      return "$(check)";
    }
    if (statusLower.includes("progress")) {
      return "$(play)";
    }
    if (statusLower.includes("review")) {
      return "$(eye)";
    }
    if (statusLower.includes("blocked")) {
      return "$(stop)";
    }
    return "$(circle-outline)";
  }

  private updateEnvItem(status: WorkflowStatus) {
    const env = status.environment;

    if (!env) {
      this.envItem.text = "$(cloud) Env: ?";
      this.envItem.backgroundColor = undefined;
      this.envItem.color = new vscode.ThemeColor("disabledForeground");
      this.envItem.tooltip = new vscode.MarkdownString(
        `### $(cloud) Environment Status\n\n` +
          `_Unable to fetch environment data_\n\n` +
          `Check that memory files exist.`,
        true
      );
      return;
    }

    const totalAlerts = (env.stageAlerts || 0) + (env.prodAlerts || 0);

    if (env.prodAlerts && env.prodAlerts > 0) {
      // Production alerts - CRITICAL
      this.envItem.text = `$(flame) Prod ${env.prodAlerts}`;
      this.envItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.errorBackground"
      );
      this.envItem.color = undefined;
      this.envItem.tooltip = new vscode.MarkdownString(
        `### $(flame) Production Alerts!\n\n` +
          `| Environment | Status | Alerts |\n` +
          `|-------------|--------|--------|\n` +
          `| Stage | ${env.stageStatus} | ${env.stageAlerts || 0} |\n` +
          `| **Production** | **${env.prodStatus}** | **${env.prodAlerts}** |\n\n` +
          `---\n` +
          `$(alert) **Action Required:** Click to investigate`,
        true
      );
    } else if (env.stageAlerts && env.stageAlerts > 0) {
      // Stage alerts - Warning
      this.envItem.text = `$(warning) Stage ${env.stageAlerts}`;
      this.envItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.warningBackground"
      );
      this.envItem.color = undefined;
      this.envItem.tooltip = new vscode.MarkdownString(
        `### $(warning) Stage Alerts\n\n` +
          `| Environment | Status | Alerts |\n` +
          `|-------------|--------|--------|\n` +
          `| **Stage** | **${env.stageStatus}** | **${env.stageAlerts}** |\n` +
          `| Production | ${env.prodStatus} | ${env.prodAlerts || 0} |\n\n` +
          `---\n` +
          `Click to investigate`,
        true
      );
    } else {
      // All healthy
      this.envItem.text = "$(pass) Env";
      this.envItem.backgroundColor = undefined;
      this.envItem.color = new vscode.ThemeColor("charts.green");
      this.envItem.tooltip = new vscode.MarkdownString(
        `### $(pass) All Environments Healthy\n\n` +
          `| Environment | Status |\n` +
          `|-------------|--------|\n` +
          `| Stage | $(check) ${env.stageStatus} |\n` +
          `| Production | $(check) ${env.prodStatus} |`,
        true
      );
    }
    this.envItem.tooltip.isTrusted = true;
  }

  private updateMrItem(status: WorkflowStatus) {
    if (!status.activeMR) {
      this.mrItem.text = "$(git-pull-request) No MR";
      this.mrItem.color = new vscode.ThemeColor("disabledForeground");
      this.mrItem.backgroundColor = undefined;
      this.mrItem.tooltip = new vscode.MarkdownString(
        `### $(git-pull-request) No Active MR\n\n` +
          `Create an MR with the **Create MR** command\n` +
          `or push a branch to start one.`,
        true
      );
      return;
    }

    const mr = status.activeMR;
    const { icon, iconColor, bgColor, statusText } = this.getPipelineDisplay(
      mr.pipelineStatus
    );

    // Compact display: icon + MR number + pipeline icon
    this.mrItem.text = `${icon} !${mr.id}`;
    this.mrItem.backgroundColor = bgColor;
    this.mrItem.color = iconColor;

    const reviewStatus = mr.needsReview
      ? "$(eye) Needs review"
      : "$(check) Approved";

    this.mrItem.tooltip = new vscode.MarkdownString(
      `### ${icon} MR !${mr.id}\n\n` +
        `**${mr.title}**\n\n` +
        `| | |\n` +
        `|---|---|\n` +
        `| Pipeline | ${statusText} |\n` +
        `| Review | ${reviewStatus} |\n` +
        `| Project | ${mr.project} |\n\n` +
        `---\n` +
        `$(link-external) Click to open in GitLab`,
      true
    );
    this.mrItem.tooltip.isTrusted = true;
  }

  private getPipelineDisplay(pipelineStatus: string): {
    icon: string;
    iconColor?: vscode.ThemeColor;
    bgColor?: vscode.ThemeColor;
    statusText: string;
  } {
    switch (pipelineStatus) {
      case "success":
      case "passed":
        return {
          icon: "$(pass)",
          iconColor: new vscode.ThemeColor("charts.green"),
          statusText: "$(check) Passed",
        };
      case "failed":
        return {
          icon: "$(error)",
          bgColor: new vscode.ThemeColor("statusBarItem.errorBackground"),
          statusText: "$(error) Failed",
        };
      case "running":
        return {
          icon: "$(sync~spin)",
          iconColor: new vscode.ThemeColor("charts.blue"),
          statusText: "$(sync~spin) Running",
        };
      case "pending":
        return {
          icon: "$(clock)",
          iconColor: new vscode.ThemeColor("charts.yellow"),
          statusText: "$(clock) Pending",
        };
      case "canceled":
      case "cancelled":
        return {
          icon: "$(circle-slash)",
          statusText: "$(circle-slash) Canceled",
        };
      default:
        return {
          icon: "$(git-pull-request)",
          statusText: `$(question) ${pipelineStatus}`,
        };
    }
  }

  private updateNamespaceItem(status: WorkflowStatus) {
    const namespaces = status.namespaces || [];
    const activeNamespaces = namespaces.filter(
      (ns) => ns.status !== "expired" && ns.status !== "deleted"
    );

    if (activeNamespaces.length === 0) {
      this.namespaceItem.hide();
      return;
    }

    const ns = activeNamespaces[0];
    const shortName = ns.name.replace("ephemeral-", "eph-");

    this.namespaceItem.text = `$(cloud-upload) ${shortName}`;
    this.namespaceItem.color = new vscode.ThemeColor("charts.purple");
    this.namespaceItem.backgroundColor = undefined;

    const expiresInfo = ns.expires ? `\n**Expires:** ${ns.expires}` : "";
    const mrInfo = ns.mrId ? `\n**MR:** !${ns.mrId}` : "";
    const shaInfo = ns.commitSha
      ? `\n**Commit:** \`${ns.commitSha.substring(0, 8)}\``
      : "";

    this.namespaceItem.tooltip = new vscode.MarkdownString(
      `### $(cloud-upload) Ephemeral Namespace\n\n` +
        `**Name:** \`${ns.name}\`${mrInfo}${shaInfo}${expiresInfo}\n\n` +
        `**Status:** ${ns.status || "active"}\n\n` +
        `---\n` +
        `Click to manage namespace`,
      true
    );
    this.namespaceItem.tooltip.isTrusted = true;
    this.namespaceItem.show();
  }

  public dispose() {
    this.vpnItem.dispose();
    this.agentItem.dispose();
    this.slackItem.dispose();
    this.issueItem.dispose();
    this.envItem.dispose();
    this.mrItem.dispose();
    this.namespaceItem.dispose();
  }
}
