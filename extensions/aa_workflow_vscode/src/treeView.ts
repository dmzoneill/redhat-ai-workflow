/**
 * Workflow Tree View Provider
 *
 * Shows a hierarchical view of current work context in the Explorer sidebar:
 *
 * WORKFLOW EXPLORER
 * ├── 📋 Active Work
 * │   ├── AAP-61214 - Fix billing calculation
 * │   │   ├── Branch: aap-61214-fix-billing
 * │   │   ├── MR: !1459 (Draft)
 * │   │   └── Pipeline: ✅ Passed
 * │   └── AAP-61200 - Add retry logic
 * ├── 🚀 Namespaces
 * │   ├── ephemeral-abc123 (mine, 2h left)
 * │   └── ephemeral-xyz789 (team)
 * ├── 🔔 Alerts
 * │   ├── ⚠️ HighMemoryUsage (stage)
 * │   └── 🔴 PodCrashLooping (prod)
 * └── 📝 Follow-ups
 *     ├── Address review comments on MR !1459
 *     └── Schedule meeting for AAP-61200
 */

import * as vscode from "vscode";
import { WorkflowDataProvider, WorkflowStatus } from "./dataProvider";

// Tree item types
type TreeItemType =
  | "root"
  | "issue"
  | "issue-detail"
  | "mr"
  | "namespace"
  | "alert"
  | "followup";

export class WorkflowTreeItem extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly itemType: TreeItemType,
    public readonly data?: any
  ) {
    super(label, collapsibleState);
    this.contextValue = itemType;
  }
}

export class WorkflowTreeProvider
  implements vscode.TreeDataProvider<WorkflowTreeItem>
{
  private _onDidChangeTreeData: vscode.EventEmitter<
    WorkflowTreeItem | undefined | null | void
  > = new vscode.EventEmitter<WorkflowTreeItem | undefined | null | void>();
  readonly onDidChangeTreeData: vscode.Event<
    WorkflowTreeItem | undefined | null | void
  > = this._onDidChangeTreeData.event;

  private dataProvider: WorkflowDataProvider;

  constructor(dataProvider: WorkflowDataProvider) {
    this.dataProvider = dataProvider;
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: WorkflowTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: WorkflowTreeItem): Promise<WorkflowTreeItem[]> {
    if (!element) {
      // Root level - show main categories
      return this.getRootItems();
    }

    // Get children based on parent type
    switch (element.itemType) {
      case "root":
        return this.getCategoryChildren(element.label);
      case "issue":
        return this.getIssueDetails(element.data);
      default:
        return [];
    }
  }

  private getRootItems(): WorkflowTreeItem[] {
    const status = this.dataProvider.getStatus();

    const items: WorkflowTreeItem[] = [];

    // Active Work section
    items.push(
      new WorkflowTreeItem(
        "📋 Active Work",
        vscode.TreeItemCollapsibleState.Expanded,
        "root"
      )
    );

    // Namespaces section (if we have any)
    items.push(
      new WorkflowTreeItem(
        "🚀 Namespaces",
        vscode.TreeItemCollapsibleState.Collapsed,
        "root"
      )
    );

    // Alerts section
    const alertCount =
      (status.environment?.stageAlerts || 0) +
      (status.environment?.prodAlerts || 0);
    items.push(
      new WorkflowTreeItem(
        `🔔 Alerts${alertCount > 0 ? ` (${alertCount})` : ""}`,
        alertCount > 0
          ? vscode.TreeItemCollapsibleState.Expanded
          : vscode.TreeItemCollapsibleState.Collapsed,
        "root"
      )
    );

    // Follow-ups section
    items.push(
      new WorkflowTreeItem(
        "📝 Follow-ups",
        vscode.TreeItemCollapsibleState.Collapsed,
        "root"
      )
    );

    return items;
  }

  private async getCategoryChildren(
    category: string
  ): Promise<WorkflowTreeItem[]> {
    const status = this.dataProvider.getStatus();

    if (category.includes("Active Work")) {
      return this.getActiveWorkItems(status);
    } else if (category.includes("Namespaces")) {
      return this.getNamespaceItems();
    } else if (category.includes("Alerts")) {
      return this.getAlertItems(status);
    } else if (category.includes("Follow-ups")) {
      return this.getFollowupItems();
    }

    return [];
  }

  private getActiveWorkItems(status: WorkflowStatus): WorkflowTreeItem[] {
    const items: WorkflowTreeItem[] = [];

    // Add active issue
    if (status.activeIssue) {
      const issue = status.activeIssue;
      const item = new WorkflowTreeItem(
        `${issue.key} - ${this.truncate(issue.summary, 40)}`,
        vscode.TreeItemCollapsibleState.Expanded,
        "issue",
        issue
      );
      item.iconPath = new vscode.ThemeIcon("issues");
      item.tooltip = `${issue.key}: ${issue.summary}\nStatus: ${issue.status}`;
      item.command = {
        command: "aa-workflow.openJiraIssue",
        title: "Open in Jira",
      };
      items.push(item);
    }

    // Add active MR
    if (status.activeMR) {
      const mr = status.activeMR;
      const pipelineIcon = this.getPipelineIcon(mr.pipelineStatus);
      const item = new WorkflowTreeItem(
        `!${mr.id} - ${this.truncate(mr.title, 40)}`,
        vscode.TreeItemCollapsibleState.None,
        "mr",
        mr
      );
      item.iconPath = new vscode.ThemeIcon("git-pull-request");
      item.description = `${pipelineIcon} ${mr.pipelineStatus}`;
      item.tooltip = `MR !${mr.id}: ${mr.title}\nPipeline: ${mr.pipelineStatus}\nNeeds Review: ${mr.needsReview}`;
      item.command = {
        command: "aa-workflow.openMR",
        title: "Open MR",
      };
      items.push(item);
    }

    if (items.length === 0) {
      const emptyItem = new WorkflowTreeItem(
        "No active work",
        vscode.TreeItemCollapsibleState.None,
        "issue-detail"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      items.push(emptyItem);
    }

    return items;
  }

  private getIssueDetails(issue: any): WorkflowTreeItem[] {
    const items: WorkflowTreeItem[] = [];

    if (issue.branch) {
      const branchItem = new WorkflowTreeItem(
        `Branch: ${issue.branch}`,
        vscode.TreeItemCollapsibleState.None,
        "issue-detail"
      );
      branchItem.iconPath = new vscode.ThemeIcon("git-branch");
      items.push(branchItem);
    }

    if (issue.status) {
      const statusItem = new WorkflowTreeItem(
        `Status: ${issue.status}`,
        vscode.TreeItemCollapsibleState.None,
        "issue-detail"
      );
      statusItem.iconPath = new vscode.ThemeIcon("circle-outline");
      items.push(statusItem);
    }

    if (issue.repo) {
      const repoItem = new WorkflowTreeItem(
        `Repo: ${issue.repo}`,
        vscode.TreeItemCollapsibleState.None,
        "issue-detail"
      );
      repoItem.iconPath = new vscode.ThemeIcon("repo");
      items.push(repoItem);
    }

    return items;
  }

  private async getNamespaceItems(): Promise<WorkflowTreeItem[]> {
    const status = this.dataProvider.getStatus();
    const items: WorkflowTreeItem[] = [];

    if (!status.namespaces || status.namespaces.length === 0) {
      const emptyItem = new WorkflowTreeItem(
        "No active namespaces",
        vscode.TreeItemCollapsibleState.None,
        "namespace"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      items.push(emptyItem);
      return items;
    }

    for (const ns of status.namespaces) {
      const item = new WorkflowTreeItem(
        ns.name,
        vscode.TreeItemCollapsibleState.None,
        "namespace",
        ns
      );
      item.iconPath = new vscode.ThemeIcon(
        ns.status === "active" ? "vm-running" : "vm-outline"
      );
      item.description = ns.expires || "";
      item.tooltip = `Namespace: ${ns.name}\nMR: ${ns.mrId || "N/A"}\nDeployed: ${ns.deployedAt || "N/A"}\nExpires: ${ns.expires || "N/A"}`;
      items.push(item);
    }

    return items;
  }

  private getAlertItems(status: WorkflowStatus): WorkflowTreeItem[] {
    const items: WorkflowTreeItem[] = [];
    const env = status.environment;

    if (!env) {
      const unknownItem = new WorkflowTreeItem(
        "Status unknown",
        vscode.TreeItemCollapsibleState.None,
        "alert"
      );
      unknownItem.iconPath = new vscode.ThemeIcon("question");
      items.push(unknownItem);
      return items;
    }

    // Production alerts
    if (env.prodAlerts > 0) {
      const prodItem = new WorkflowTreeItem(
        `🔴 Production: ${env.prodAlerts} alert${env.prodAlerts > 1 ? "s" : ""}`,
        vscode.TreeItemCollapsibleState.None,
        "alert",
        { environment: "prod" }
      );
      prodItem.iconPath = new vscode.ThemeIcon("flame");
      prodItem.command = {
        command: "aa-workflow.investigateAlert",
        title: "Investigate",
      };
      items.push(prodItem);
    }

    // Stage alerts
    if (env.stageAlerts > 0) {
      const stageItem = new WorkflowTreeItem(
        `⚠️ Stage: ${env.stageAlerts} alert${env.stageAlerts > 1 ? "s" : ""}`,
        vscode.TreeItemCollapsibleState.None,
        "alert",
        { environment: "stage" }
      );
      stageItem.iconPath = new vscode.ThemeIcon("warning");
      stageItem.command = {
        command: "aa-workflow.investigateAlert",
        title: "Investigate",
      };
      items.push(stageItem);
    }

    // All healthy
    if (env.prodAlerts === 0 && env.stageAlerts === 0) {
      const healthyItem = new WorkflowTreeItem(
        "✅ All environments healthy",
        vscode.TreeItemCollapsibleState.None,
        "alert"
      );
      healthyItem.iconPath = new vscode.ThemeIcon("pass");
      items.push(healthyItem);
    }

    return items;
  }

  private async getFollowupItems(): Promise<WorkflowTreeItem[]> {
    const status = this.dataProvider.getStatus();
    const items: WorkflowTreeItem[] = [];

    if (!status.followUps || status.followUps.length === 0) {
      const emptyItem = new WorkflowTreeItem(
        "No follow-ups",
        vscode.TreeItemCollapsibleState.None,
        "followup"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      items.push(emptyItem);
      return items;
    }

    for (const fu of status.followUps) {
      const priorityIcon =
        fu.priority === "high"
          ? "🔴"
          : fu.priority === "medium"
            ? "🟡"
            : "⚪";
      const item = new WorkflowTreeItem(
        `${priorityIcon} ${this.truncate(fu.task, 50)}`,
        vscode.TreeItemCollapsibleState.None,
        "followup",
        fu
      );
      item.iconPath = new vscode.ThemeIcon("checklist");
      item.description = fu.due || "";
      item.tooltip = `${fu.task}\nPriority: ${fu.priority}\nDue: ${fu.due || "N/A"}${fu.issueKey ? `\nJira: ${fu.issueKey}` : ""}${fu.mrId ? `\nMR: !${fu.mrId}` : ""}`;
      items.push(item);
    }

    return items;
  }

  private getPipelineIcon(status: string): string {
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

  private truncate(str: string, maxLen: number): string {
    if (str.length <= maxLen) return str;
    return str.substring(0, maxLen - 3) + "...";
  }
}

export function registerTreeView(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider
): WorkflowTreeProvider {
  const treeProvider = new WorkflowTreeProvider(dataProvider);

  const treeView = vscode.window.createTreeView("aaWorkflowExplorer", {
    treeDataProvider: treeProvider,
    showCollapseAll: true,
  });

  context.subscriptions.push(treeView);

  // Register refresh command
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.refreshTree", () => {
      dataProvider.refresh().then(() => {
        treeProvider.refresh();
      });
    })
  );

  return treeProvider;
}
