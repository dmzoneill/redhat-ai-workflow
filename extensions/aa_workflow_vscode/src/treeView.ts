/**
 * Workflow Tree View Provider
 *
 * Shows a hierarchical view of current work context in the Explorer sidebar:
 *
 * WORKFLOW EXPLORER
 * ├── ⚡ Quick Actions
 * │   ├── ☕ Morning Briefing
 * │   ├── 🚀 Start Work on Issue
 * │   ├── 📝 Create MR
 * │   └── 🍺 End of Day
 * ├── 📋 Active Work
 * │   ├── AAP-61214 - Fix billing calculation
 * │   │   ├── Branch: aap-61214-fix-billing
 * │   │   ├── MR: !1459 (Draft) ✅ Passed
 * │   │   └── Status: In Progress
 * │   └── [+ Add Issue]
 * ├── 🚀 Namespaces
 * │   ├── ephemeral-abc123 (2h left)
 * │   │   └── MR !1459 • sha:abc123
 * │   └── [+ Deploy to Ephemeral]
 * ├── 🔔 Alerts (2)
 * │   ├── 🔴 PodCrashLooping (prod) - Click to investigate
 * │   └── ⚠️ HighMemoryUsage (stage)
 * ├── 📝 Follow-ups
 * │   ├── 🔴 Address review comments on !1459
 * │   └── ⚪ Update documentation
 * └── 🎯 Skills
 *     ├── investigate_alert
 *     ├── create_mr
 *     └── [View All Skills...]
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { WorkflowDataProvider, WorkflowStatus } from "./dataProvider";
import { getSkillsDir } from "./paths";

// Tree item types for context menu handling
type TreeItemType =
  | "root"
  | "action"
  | "issue"
  | "issue-detail"
  | "mr"
  | "namespace"
  | "namespace-detail"
  | "alert"
  | "followup"
  | "skill"
  | "add-item";

export class WorkflowTreeItem extends vscode.TreeItem {
  public data?: any;

  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly itemType: TreeItemType,
    data?: any
  ) {
    super(label, collapsibleState);
    this.contextValue = itemType;
    this.data = data;
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
  private skillsDir: string;

  constructor(dataProvider: WorkflowDataProvider) {
    this.dataProvider = dataProvider;
    this.skillsDir = getSkillsDir();
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
        // Check if this is a skill category with embedded data
        if (element.data?.categorySkills) {
          return this.getSkillCategoryItems(element.data.categorySkills);
        }
        return this.getCategoryChildren(element.label);
      case "issue":
        return this.getIssueDetails(element.data);
      case "namespace":
        return this.getNamespaceDetails(element.data);
      default:
        return [];
    }
  }

  private getRootItems(): WorkflowTreeItem[] {
    const status = this.dataProvider.getStatus();
    const items: WorkflowTreeItem[] = [];

    // Quick Actions - always first
    const quickActionsItem = new WorkflowTreeItem(
      "Quick Actions",
      vscode.TreeItemCollapsibleState.Expanded,
      "root"
    );
    quickActionsItem.iconPath = new vscode.ThemeIcon(
      "zap",
      new vscode.ThemeColor("charts.yellow")
    );
    items.push(quickActionsItem);

    // Active Work section
    const hasWork = status.activeIssue || status.activeMR;
    const activeWorkItem = new WorkflowTreeItem(
      "Active Work",
      hasWork
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.Collapsed,
      "root"
    );
    activeWorkItem.iconPath = new vscode.ThemeIcon(
      "tasklist",
      hasWork ? new vscode.ThemeColor("charts.blue") : undefined
    );
    if (hasWork) {
      activeWorkItem.description = status.activeIssue?.key || "";
    }
    items.push(activeWorkItem);

    // Namespaces section
    const namespaceCount = status.namespaces?.length || 0;
    const namespaceItem = new WorkflowTreeItem(
      "Namespaces",
      namespaceCount > 0
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.Collapsed,
      "root"
    );
    namespaceItem.iconPath = new vscode.ThemeIcon(
      "cloud",
      namespaceCount > 0 ? new vscode.ThemeColor("charts.purple") : undefined
    );
    if (namespaceCount > 0) {
      namespaceItem.description = `${namespaceCount} active`;
    }
    items.push(namespaceItem);

    // Alerts section - with count badge
    const alertCount =
      (status.environment?.stageAlerts || 0) +
      (status.environment?.prodAlerts || 0);
    const alertsItem = new WorkflowTreeItem(
      "Alerts",
      alertCount > 0
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.Collapsed,
      "root"
    );
    if (alertCount > 0) {
      alertsItem.iconPath = new vscode.ThemeIcon(
        "bell-dot",
        status.environment?.prodAlerts
          ? new vscode.ThemeColor("charts.red")
          : new vscode.ThemeColor("charts.yellow")
      );
      alertsItem.description = `${alertCount} active`;
    } else {
      alertsItem.iconPath = new vscode.ThemeIcon("bell");
      alertsItem.description = "All clear";
    }
    items.push(alertsItem);

    // Follow-ups section
    const followUpCount = status.followUps?.length || 0;
    const followUpsItem = new WorkflowTreeItem(
      "Follow-ups",
      followUpCount > 0
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.Collapsed,
      "root"
    );
    followUpsItem.iconPath = new vscode.ThemeIcon(
      followUpCount > 0 ? "checklist" : "check-all"
    );
    if (followUpCount > 0) {
      followUpsItem.description = `${followUpCount} pending`;
    }
    items.push(followUpsItem);

    // Skills section
    const skillsItem = new WorkflowTreeItem(
      "Skills",
      vscode.TreeItemCollapsibleState.Collapsed,
      "root"
    );
    skillsItem.iconPath = new vscode.ThemeIcon(
      "wand",
      new vscode.ThemeColor("charts.green")
    );
    skillsItem.description = "Workflows";
    items.push(skillsItem);

    return items;
  }

  private async getCategoryChildren(
    category: string
  ): Promise<WorkflowTreeItem[]> {
    const status = this.dataProvider.getStatus();

    if (category.includes("Quick Actions")) {
      return this.getQuickActionItems();
    } else if (category.includes("Active Work")) {
      return this.getActiveWorkItems(status);
    } else if (category.includes("Namespaces")) {
      return this.getNamespaceItems();
    } else if (category.includes("Alerts")) {
      return this.getAlertItems(status);
    } else if (category.includes("Follow-ups")) {
      return this.getFollowupItems();
    } else if (category.includes("Skills")) {
      return this.getSkillItems();
    }

    return [];
  }

  private getQuickActionItems(): WorkflowTreeItem[] {
    const actions = [
      {
        label: "Morning Briefing",
        icon: "coffee",
        description: "/coffee",
        command: "aa-workflow.coffee",
        color: "charts.orange",
      },
      {
        label: "Start Work on Issue",
        icon: "rocket",
        description: "/start-work",
        command: "aa-workflow.startWork",
        color: "charts.blue",
      },
      {
        label: "Create MR",
        icon: "git-pull-request-create",
        description: "/create-mr",
        command: "aa-workflow.runSkill",
        color: "charts.green",
      },
      {
        label: "Run Skill...",
        icon: "play",
        description: "All skills",
        command: "aa-workflow.runSkill",
        color: "charts.purple",
      },
      {
        label: "End of Day",
        icon: "debug-stop",
        description: "/beer",
        command: "aa-workflow.beer",
        color: "charts.yellow",
      },
    ];

    return actions.map((action) => {
      const item = new WorkflowTreeItem(
        action.label,
        vscode.TreeItemCollapsibleState.None,
        "action"
      );
      item.iconPath = new vscode.ThemeIcon(
        action.icon,
        new vscode.ThemeColor(action.color)
      );
      item.description = action.description;
      item.command = {
        command: action.command,
        title: action.label,
      };
      item.tooltip = `Click to run: ${action.description}`;
      return item;
    });
  }

  private getActiveWorkItems(status: WorkflowStatus): WorkflowTreeItem[] {
    const items: WorkflowTreeItem[] = [];

    // Add active issue with details
    if (status.activeIssue) {
      const issue = status.activeIssue;
      const statusIcon = this.getStatusEmoji(issue.status);
      const item = new WorkflowTreeItem(
        issue.key,
        vscode.TreeItemCollapsibleState.Expanded,
        "issue",
        issue
      );
      item.iconPath = new vscode.ThemeIcon(
        "issues",
        new vscode.ThemeColor("charts.blue")
      );
      item.description = this.truncate(issue.summary, 35);
      item.tooltip = new vscode.MarkdownString(
        `### ${issue.key}\n\n` +
          `**${issue.summary}**\n\n` +
          `${statusIcon} Status: ${issue.status}\n\n` +
          `---\n` +
          `$(link-external) Click to open in Jira`,
        true
      );
      item.tooltip.isTrusted = true;
      item.command = {
        command: "aa-workflow.openJiraIssue",
        title: "Open in Jira",
      };
      items.push(item);
    }

    // Add active MR (if not under issue)
    if (status.activeMR && !status.activeIssue) {
      items.push(this.createMRItem(status.activeMR));
    }

    // Empty state with call to action
    if (items.length === 0) {
      const emptyItem = new WorkflowTreeItem(
        "No active work",
        vscode.TreeItemCollapsibleState.None,
        "add-item"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      emptyItem.description = "Click to start";
      emptyItem.command = {
        command: "aa-workflow.startWork",
        title: "Start Work",
      };
      items.push(emptyItem);
    }

    // Add new issue action
    const addItem = new WorkflowTreeItem(
      "Start work on issue...",
      vscode.TreeItemCollapsibleState.None,
      "add-item"
    );
    addItem.iconPath = new vscode.ThemeIcon(
      "add",
      new vscode.ThemeColor("charts.green")
    );
    addItem.command = {
      command: "aa-workflow.startWork",
      title: "Start Work",
    };
    items.push(addItem);

    return items;
  }

  private getIssueDetails(issue: any): WorkflowTreeItem[] {
    const items: WorkflowTreeItem[] = [];
    const status = this.dataProvider.getStatus();

    // Status with emoji
    const statusEmoji = this.getStatusEmoji(issue.status);
    const statusItem = new WorkflowTreeItem(
      `${statusEmoji} ${issue.status}`,
      vscode.TreeItemCollapsibleState.None,
      "issue-detail"
    );
    statusItem.iconPath = new vscode.ThemeIcon("circle-outline");
    items.push(statusItem);

    // Branch
    if (issue.branch) {
      const branchItem = new WorkflowTreeItem(
        issue.branch,
        vscode.TreeItemCollapsibleState.None,
        "issue-detail"
      );
      branchItem.iconPath = new vscode.ThemeIcon(
        "git-branch",
        new vscode.ThemeColor("charts.green")
      );
      branchItem.description = "branch";
      items.push(branchItem);
    }

    // Associated MR
    if (status.activeMR) {
      items.push(this.createMRItem(status.activeMR));
    }

    // Repo
    if (issue.repo) {
      const repoItem = new WorkflowTreeItem(
        issue.repo,
        vscode.TreeItemCollapsibleState.None,
        "issue-detail"
      );
      repoItem.iconPath = new vscode.ThemeIcon("repo");
      repoItem.description = "repo";
      items.push(repoItem);
    }

    return items;
  }

  private createMRItem(mr: any): WorkflowTreeItem {
    const pipelineIcon = this.getPipelineIcon(mr.pipelineStatus);
    const pipelineColor = this.getPipelineColor(mr.pipelineStatus);

    const item = new WorkflowTreeItem(
      `!${mr.id}`,
      vscode.TreeItemCollapsibleState.None,
      "mr",
      mr
    );
    item.iconPath = new vscode.ThemeIcon(
      "git-pull-request",
      pipelineColor ? new vscode.ThemeColor(pipelineColor) : undefined
    );
    item.description = `${pipelineIcon} ${this.truncate(mr.title, 30)}`;
    item.tooltip = new vscode.MarkdownString(
      `### MR !${mr.id}\n\n` +
        `**${mr.title}**\n\n` +
        `| | |\n|---|---|\n` +
        `| Pipeline | ${pipelineIcon} ${mr.pipelineStatus} |\n` +
        `| Review | ${mr.needsReview ? "Needs review" : "Approved"} |\n\n` +
        `---\n` +
        `$(link-external) Click to open in GitLab`,
      true
    );
    item.tooltip.isTrusted = true;
    item.command = {
      command: "aa-workflow.openMR",
      title: "Open MR",
    };
    return item;
  }

  private async getNamespaceItems(): Promise<WorkflowTreeItem[]> {
    const status = this.dataProvider.getStatus();
    const items: WorkflowTreeItem[] = [];

    if (status.namespaces && status.namespaces.length > 0) {
      for (const ns of status.namespaces) {
        const isActive =
          ns.status === "active" || ns.status === "running" || !ns.status;
        const item = new WorkflowTreeItem(
          ns.name.replace("ephemeral-", ""),
          vscode.TreeItemCollapsibleState.Collapsed,
          "namespace",
          ns
        );
        item.iconPath = new vscode.ThemeIcon(
          isActive ? "vm-running" : "vm-outline",
          isActive ? new vscode.ThemeColor("charts.purple") : undefined
        );
        item.description = ns.expires
          ? `expires ${ns.expires}`
          : ns.status || "active";
        item.tooltip = new vscode.MarkdownString(
          `### $(cloud) ${ns.name}\n\n` +
            `| | |\n|---|---|\n` +
            `| Status | ${ns.status || "active"} |\n` +
            `| MR | ${ns.mrId ? `!${ns.mrId}` : "N/A"} |\n` +
            `| Commit | ${ns.commitSha ? `\`${ns.commitSha.substring(0, 8)}\`` : "N/A"} |\n` +
            `| Expires | ${ns.expires || "N/A"} |`,
          true
        );
        item.tooltip.isTrusted = true;
        item.command = {
          command: "aa-workflow.showNamespace",
          title: "Show Namespace",
        };
        items.push(item);
      }
    }

    // Empty state
    if (items.length === 0) {
      const emptyItem = new WorkflowTreeItem(
        "No active namespaces",
        vscode.TreeItemCollapsibleState.None,
        "add-item"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      items.push(emptyItem);
    }

    // Add deploy action
    const addItem = new WorkflowTreeItem(
      "Deploy to ephemeral...",
      vscode.TreeItemCollapsibleState.None,
      "add-item"
    );
    addItem.iconPath = new vscode.ThemeIcon(
      "cloud-upload",
      new vscode.ThemeColor("charts.green")
    );
    addItem.command = {
      command: "aa-workflow.runSkill",
      title: "Deploy",
    };
    items.push(addItem);

    return items;
  }

  private getNamespaceDetails(ns: any): WorkflowTreeItem[] {
    const items: WorkflowTreeItem[] = [];

    if (ns.mrId) {
      const mrItem = new WorkflowTreeItem(
        `MR !${ns.mrId}`,
        vscode.TreeItemCollapsibleState.None,
        "namespace-detail"
      );
      mrItem.iconPath = new vscode.ThemeIcon("git-pull-request");
      items.push(mrItem);
    }

    if (ns.commitSha) {
      const shaItem = new WorkflowTreeItem(
        ns.commitSha.substring(0, 8),
        vscode.TreeItemCollapsibleState.None,
        "namespace-detail"
      );
      shaItem.iconPath = new vscode.ThemeIcon("git-commit");
      shaItem.description = "commit";
      items.push(shaItem);
    }

    if (ns.deployedAt) {
      const deployedItem = new WorkflowTreeItem(
        ns.deployedAt,
        vscode.TreeItemCollapsibleState.None,
        "namespace-detail"
      );
      deployedItem.iconPath = new vscode.ThemeIcon("clock");
      deployedItem.description = "deployed";
      items.push(deployedItem);
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
      unknownItem.description = "Check connection";
      items.push(unknownItem);
      return items;
    }

    // Production alerts - critical, shown first
    if (env.prodAlerts > 0) {
      const prodItem = new WorkflowTreeItem(
        `Production`,
        vscode.TreeItemCollapsibleState.None,
        "alert",
        { environment: "prod" }
      );
      prodItem.iconPath = new vscode.ThemeIcon(
        "flame",
        new vscode.ThemeColor("charts.red")
      );
      prodItem.description = `${env.prodAlerts} alert${env.prodAlerts > 1 ? "s" : ""} — Click to investigate`;
      prodItem.command = {
        command: "aa-workflow.investigateAlert",
        title: "Investigate",
      };
      items.push(prodItem);
    }

    // Stage alerts
    if (env.stageAlerts > 0) {
      const stageItem = new WorkflowTreeItem(
        `Stage`,
        vscode.TreeItemCollapsibleState.None,
        "alert",
        { environment: "stage" }
      );
      stageItem.iconPath = new vscode.ThemeIcon(
        "warning",
        new vscode.ThemeColor("charts.yellow")
      );
      stageItem.description = `${env.stageAlerts} alert${env.stageAlerts > 1 ? "s" : ""}`;
      stageItem.command = {
        command: "aa-workflow.investigateAlert",
        title: "Investigate",
      };
      items.push(stageItem);
    }

    // All healthy state
    if (env.prodAlerts === 0 && env.stageAlerts === 0) {
      const stageHealthy = new WorkflowTreeItem(
        "Stage",
        vscode.TreeItemCollapsibleState.None,
        "alert"
      );
      stageHealthy.iconPath = new vscode.ThemeIcon(
        "pass",
        new vscode.ThemeColor("charts.green")
      );
      stageHealthy.description = "Healthy";
      items.push(stageHealthy);

      const prodHealthy = new WorkflowTreeItem(
        "Production",
        vscode.TreeItemCollapsibleState.None,
        "alert"
      );
      prodHealthy.iconPath = new vscode.ThemeIcon(
        "pass",
        new vscode.ThemeColor("charts.green")
      );
      prodHealthy.description = "Healthy";
      items.push(prodHealthy);
    }

    return items;
  }

  private async getFollowupItems(): Promise<WorkflowTreeItem[]> {
    const status = this.dataProvider.getStatus();
    const items: WorkflowTreeItem[] = [];

    if (status.followUps && status.followUps.length > 0) {
      for (const fu of status.followUps) {
        const priorityColor = this.getPriorityColor(fu.priority);
        const item = new WorkflowTreeItem(
          this.truncate(fu.task, 45),
          vscode.TreeItemCollapsibleState.None,
          "followup",
          fu
        );
        item.iconPath = new vscode.ThemeIcon(
          fu.priority === "high" ? "circle-filled" : "circle-outline",
          priorityColor ? new vscode.ThemeColor(priorityColor) : undefined
        );
        item.description = fu.due || fu.priority;
        item.tooltip = new vscode.MarkdownString(
          `### Follow-up\n\n` +
            `**${fu.task}**\n\n` +
            `| | |\n|---|---|\n` +
            `| Priority | ${fu.priority} |\n` +
            `| Due | ${fu.due || "N/A"} |\n` +
            (fu.issueKey ? `| Jira | ${fu.issueKey} |\n` : "") +
            (fu.mrId ? `| MR | !${fu.mrId} |` : ""),
          true
        );
        item.tooltip.isTrusted = true;
        items.push(item);
      }
    }

    // Empty state
    if (items.length === 0) {
      const emptyItem = new WorkflowTreeItem(
        "No follow-ups",
        vscode.TreeItemCollapsibleState.None,
        "followup"
      );
      emptyItem.iconPath = new vscode.ThemeIcon(
        "check-all",
        new vscode.ThemeColor("charts.green")
      );
      emptyItem.description = "All caught up!";
      items.push(emptyItem);
    }

    return items;
  }

  private getSkillItems(): WorkflowTreeItem[] {
    const skills = this.loadSkillsFromDisk();

    // Categorize skills - categories are detected from skill metadata (tags/personas)
    // or inferred from skill name patterns
    const categories: Record<string, { icon: string; color: string; skills: typeof skills }> = {
      "Daily": { icon: "calendar", color: "charts.yellow", skills: [] },
      "Development": { icon: "code", color: "charts.blue", skills: [] },
      "DevOps": { icon: "server-process", color: "charts.green", skills: [] },
      "Jira": { icon: "issues", color: "charts.orange", skills: [] },
      "Memory": { icon: "database", color: "charts.purple", skills: [] },
      "Knowledge": { icon: "book", color: "charts.cyan", skills: [] },
      "Project": { icon: "folder-library", color: "charts.pink", skills: [] },
      "Other": { icon: "extensions", color: "charts.gray", skills: [] },
    };

    // Categorize each skill - first check tags from YAML, then fall back to name patterns
    for (const skill of skills) {
      // Check if skill has category from tags
      if (skill.tags?.includes("daily") || skill.tags?.includes("routine")) {
        categories["Daily"].skills.push(skill);
      } else if (skill.tags?.includes("knowledge") || skill.name.includes("knowledge") ||
                 skill.name.includes("bootstrap_knowledge") || skill.name.includes("learn_architecture")) {
        categories["Knowledge"].skills.push(skill);
      } else if (skill.tags?.includes("project") || skill.name.includes("add_project") ||
                 skill.name.includes("project_")) {
        categories["Project"].skills.push(skill);
      } else if (skill.tags?.includes("memory") || skill.name.startsWith("memory_") ||
                 skill.name.includes("learn_pattern") || skill.name.includes("suggest_patterns")) {
        categories["Memory"].skills.push(skill);
      } else if (skill.tags?.includes("jira") || skill.name.includes("jira") ||
                 skill.name.includes("issue") || skill.name.includes("sprint") ||
                 ["schedule_meeting", "notify_team", "update_docs"].includes(skill.name)) {
        categories["Jira"].skills.push(skill);
      } else if (skill.tags?.includes("devops") || skill.tags?.includes("deployment") ||
                 skill.name.includes("ephemeral") || skill.name.includes("deploy") ||
                 skill.name.includes("alert") || skill.name.includes("debug_prod") ||
                 skill.name.includes("rollout") || skill.name.includes("scale") ||
                 skill.name.includes("silence") || skill.name.includes("environment") ||
                 skill.name.includes("konflux") || skill.name.includes("release") ||
                 skill.name.includes("hotfix") || skill.name.includes("appinterface") ||
                 skill.name.includes("ci_") || skill.name.includes("pipeline") ||
                 skill.name.includes("secrets") || skill.name.includes("vulnerabilities")) {
        categories["DevOps"].skills.push(skill);
      } else if (skill.tags?.includes("development") || skill.tags?.includes("git") ||
                 skill.name.includes("_mr") || skill.name.includes("mr_") ||
                 skill.name.includes("_pr") || skill.name.includes("pr_") ||
                 skill.name.includes("branch") || skill.name.includes("review") ||
                 skill.name === "start_work" || skill.name === "create_mr") {
        categories["Development"].skills.push(skill);
      } else if (["coffee", "beer", "standup_summary", "weekly_summary"].includes(skill.name)) {
        categories["Daily"].skills.push(skill);
      } else {
        categories["Other"].skills.push(skill);
      }
    }

    const items: WorkflowTreeItem[] = [];

    // Add categorized skills
    for (const [categoryName, category] of Object.entries(categories)) {
      if (category.skills.length === 0) continue;

      // Category header
      const categoryItem = new WorkflowTreeItem(
        `${categoryName} (${category.skills.length})`,
        vscode.TreeItemCollapsibleState.Collapsed,
        "root"
      );
      categoryItem.iconPath = new vscode.ThemeIcon(
        category.icon,
        new vscode.ThemeColor(category.color)
      );
      // Store skills in data for getChildren
      categoryItem.data = { categorySkills: category.skills };
      items.push(categoryItem);
    }

    // Quick summary at top
    const totalItem = new WorkflowTreeItem(
      `${skills.length} skills available`,
      vscode.TreeItemCollapsibleState.None,
      "add-item"
    );
    totalItem.iconPath = new vscode.ThemeIcon("info");
    totalItem.description = "Click to run any";
    totalItem.command = {
      command: "aa-workflow.runSkill",
      title: "Run Skill",
    };
    items.unshift(totalItem);

    return items;
  }

  private getSkillCategoryItems(categorySkills: any[]): WorkflowTreeItem[] {
    return categorySkills.map((skill) => {
      const item = new WorkflowTreeItem(
        skill.label,
        vscode.TreeItemCollapsibleState.None,
        "skill",
        skill
      );
      item.iconPath = new vscode.ThemeIcon(this.getSkillIcon(skill.name));
      item.description = skill.name;
      item.tooltip = new vscode.MarkdownString(
        `### ${skill.label}\n\n${skill.description}\n\n---\n_Click to run this skill_`,
        true
      );
      item.tooltip.isTrusted = true;
      item.command = {
        command: "aa-workflow.runSkillByName",
        title: "Run Skill",
        arguments: [skill.name],
      };
      return item;
    });
  }

  private loadSkillsFromDisk(): Array<{ name: string; label: string; description: string; tags?: string[]; personas?: string[] }> {
    const skills: Array<{ name: string; label: string; description: string; tags?: string[]; personas?: string[] }> = [];

    try {
      if (!fs.existsSync(this.skillsDir)) {
        return skills;
      }

      const files = fs.readdirSync(this.skillsDir).filter((f) => f.endsWith(".yaml"));

      for (const file of files) {
        try {
          const content = fs.readFileSync(path.join(this.skillsDir, file), "utf-8");

          // Simple YAML parsing for name, description, tags, and personas
          const nameMatch = content.match(/^name:\s*(.+)$/m);
          const descMatch = content.match(/^description:\s*\|?\s*\n?\s*(.+?)(?:\n\s*\n|\n\s*[a-z]+:)/ms);

          // Extract tags array
          const tagsMatch = content.match(/^tags:\s*\n((?:\s+-\s*.+\n?)+)/m);
          let tags: string[] | undefined;
          if (tagsMatch) {
            tags = tagsMatch[1]
              .split('\n')
              .map(line => line.replace(/^\s*-\s*/, '').trim())
              .filter(t => t.length > 0);
          }

          // Extract personas array
          const personasMatch = content.match(/^personas:\s*\n((?:\s+-\s*.+\n?)+)/m);
          let personas: string[] | undefined;
          if (personasMatch) {
            personas = personasMatch[1]
              .split('\n')
              .map(line => line.replace(/^\s*-\s*/, '').trim())
              .filter(p => p.length > 0);
          }

          if (nameMatch) {
            const name = nameMatch[1].trim();
            const description = descMatch
              ? descMatch[1].trim().split('\n')[0].trim()  // First line of description
              : `Run ${name} skill`;

            // Convert snake_case to Title Case for label
            const label = name
              .split("_")
              .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
              .join(" ");

            skills.push({ name, label, description, tags, personas });
          }
        } catch (e) {
          // Skip files that can't be parsed
        }
      }

      // Sort alphabetically by label
      skills.sort((a, b) => a.label.localeCompare(b.label));
    } catch (e) {
      console.error("Failed to load skills:", e);
    }

    return skills;
  }

  private getSkillIcon(skillName: string): string {
    const iconMap: Record<string, string> = {
      // Daily
      coffee: "coffee",
      beer: "beaker",
      standup_summary: "checklist",
      weekly_summary: "calendar",
      // Development
      start_work: "rocket",
      create_mr: "git-pull-request-create",
      review_pr: "eye",
      review_pr_multiagent: "organization",
      review_all_prs: "checklist",
      check_mr_feedback: "comment-discussion",
      check_my_prs: "git-pull-request",
      rebase_pr: "git-merge",
      sync_branch: "sync",
      cleanup_branches: "trash",
      mark_mr_ready: "check",
      close_mr: "git-pull-request-closed",
      notify_mr: "megaphone",
      // DevOps
      deploy_to_ephemeral: "cloud-upload",
      test_mr_ephemeral: "beaker",
      extend_ephemeral: "clock",
      investigate_alert: "search",
      investigate_slack_alert: "comment-discussion",
      debug_prod: "bug",
      rollout_restart: "debug-restart",
      scale_deployment: "arrow-both",
      silence_alert: "bell-slash",
      environment_overview: "server",
      konflux_status: "package",
      release_to_prod: "rocket",
      release_aa_backend_prod: "rocket",
      hotfix: "flame",
      check_ci_health: "pulse",
      ci_retry: "refresh",
      cancel_pipeline: "stop",
      check_integration_tests: "beaker",
      check_secrets: "key",
      scan_vulnerabilities: "shield",
      appinterface_check: "checklist",
      // Jira
      create_jira_issue: "new-file",
      clone_jira_issue: "files",
      close_issue: "issue-closed",
      jira_hygiene: "tools",
      sprint_planning: "project",
      schedule_meeting: "calendar",
      notify_team: "broadcast",
      update_docs: "book",
      // Memory
      memory_view: "eye",
      memory_edit: "edit",
      memory_cleanup: "trash",
      memory_init: "add",
      learn_pattern: "lightbulb",
      suggest_patterns: "sparkle",
      // Knowledge
      bootstrap_knowledge: "book",
      learn_architecture: "symbol-structure",
      knowledge_scan: "search",
      knowledge_load: "cloud-download",
      knowledge_update: "edit",
      knowledge_learn: "mortar-board",
      knowledge_list: "list-tree",
      // Project
      add_project: "new-folder",
      project_detect: "search",
      project_list: "folder-library",
      project_remove: "trash",
      project_update: "edit",
      // Other
      slack_daemon_control: "comment",
      test_error_recovery: "bug",
    };

    // Try exact match first
    if (iconMap[skillName]) {
      return iconMap[skillName];
    }

    // Try pattern-based icon inference
    if (skillName.includes("knowledge")) return "book";
    if (skillName.includes("project")) return "folder";
    if (skillName.includes("memory")) return "database";
    if (skillName.includes("learn")) return "lightbulb";
    if (skillName.includes("review")) return "eye";
    if (skillName.includes("deploy")) return "cloud-upload";
    if (skillName.includes("alert")) return "bell";
    if (skillName.includes("test")) return "beaker";
    if (skillName.includes("release")) return "rocket";
    if (skillName.includes("mr") || skillName.includes("pr")) return "git-pull-request";
    if (skillName.includes("branch")) return "git-branch";
    if (skillName.includes("jira") || skillName.includes("issue")) return "issues";
    if (skillName.includes("scan")) return "search";
    if (skillName.includes("check")) return "checklist";

    return "play";
  }

  private getStatusEmoji(status: string): string {
    const statusLower = status.toLowerCase();
    if (statusLower.includes("done") || statusLower.includes("closed"))
      return "✅";
    if (statusLower.includes("progress")) return "🔵";
    if (statusLower.includes("review")) return "👀";
    if (statusLower.includes("blocked")) return "🛑";
    if (statusLower.includes("open") || statusLower.includes("new")) return "⚪";
    return "⚪";
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
      case "canceled":
      case "cancelled":
        return "⛔";
      default:
        return "❓";
    }
  }

  private getPipelineColor(status: string): string | undefined {
    switch (status) {
      case "success":
      case "passed":
        return "charts.green";
      case "failed":
        return "charts.red";
      case "running":
        return "charts.blue";
      case "pending":
        return "charts.yellow";
      default:
        return undefined;
    }
  }

  private getPriorityColor(priority: string): string | undefined {
    switch (priority) {
      case "high":
        return "charts.red";
      case "medium":
        return "charts.yellow";
      case "low":
        return "charts.green";
      default:
        return undefined;
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
