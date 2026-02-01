/**
 * Command Registration
 *
 * Registers all command palette commands and their handlers.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { WorkflowDataProvider } from "./dataProvider";
import { StatusBarManager } from "./statusBar";
import { getSkillsDir, getCommandsDir } from "./paths";
import { dbus } from "./dbusClient";
import { createLogger } from "./logger";

const logger = createLogger("Commands");

// Cache of available slash commands (loaded from .cursor/commands/)
let availableSlashCommands: Set<string> | null = null;

/**
 * Load available slash commands from .cursor/commands/ directory.
 * Returns a Set of command names (without leading slash).
 *
 * Cursor stores custom slash commands in the workspace's .cursor/commands/ folder.
 * Each .md file defines a command that Claude can execute.
 */
function loadAvailableSlashCommands(): Set<string> {
  if (availableSlashCommands !== null) {
    return availableSlashCommands;
  }

  availableSlashCommands = new Set();

  try {
    const commandsDir = getCommandsDir();
    if (fs.existsSync(commandsDir)) {
      const files = fs.readdirSync(commandsDir);
      for (const file of files) {
        if (file.endsWith(".md")) {
          // Remove .md extension to get command name
          const commandName = file.slice(0, -3);
          availableSlashCommands.add(commandName);
        }
      }
    }
  } catch {
    // Ignore errors, return empty set
  }

  return availableSlashCommands;
}

/**
 * Convert a skill name (snake_case) to potential slash command name (kebab-case).
 * e.g., "investigate_alert" -> "investigate-alert"
 */
function skillNameToCommandName(skillName: string): string {
  return skillName.replace(/_/g, "-");
}

/**
 * Find the slash command for a skill, if one exists.
 * Dynamically checks .cursor/commands/ directory.
 *
 * Tries multiple patterns:
 * 1. Direct match: skill "coffee" -> command "coffee"
 * 2. Kebab-case: skill "start_work" -> command "start-work"
 * 3. Common variations: skill "investigate_alert" -> command "investigate-alert"
 */
function getSlashCommandForSkill(skillName: string): string | null {
  const commands = loadAvailableSlashCommands();

  // Try direct match first (e.g., "coffee" -> "/coffee")
  if (commands.has(skillName)) {
    return `/${skillName}`;
  }

  // Try kebab-case conversion (e.g., "start_work" -> "/start-work")
  const kebabCase = skillNameToCommandName(skillName);
  if (commands.has(kebabCase)) {
    return `/${kebabCase}`;
  }

  // No matching command found
  return null;
}

/**
 * Check if a slash command exists in .cursor/commands/
 */
function slashCommandExists(commandName: string): boolean {
  const commands = loadAvailableSlashCommands();
  // Remove leading slash if present
  const name = commandName.replace(/^\//, "");
  return commands.has(name);
}

/**
 * Invalidate the slash commands cache (call when files might have changed)
 */
function invalidateSlashCommandsCache(): void {
  availableSlashCommands = null;
}

/**
 * Send a message to the Cursor chat and submit it automatically.
 *
 * This uses Cursor's internal commands to:
 * 1. Open a new chat in agent mode
 * 2. Prefill the text via clipboard + paste
 * 3. Submit the message
 *
 * Cursor is an Electron app, so we use internal commands where available.
 */
async function sendToCursorChat(message: string): Promise<boolean> {
  // Save current clipboard content to restore later
  const previousClipboard = await vscode.env.clipboard.readText();

  try {
    // Method 1: Open agent chat, paste from clipboard, and submit
    // This is the most reliable method as it works with the DOM input
    await vscode.env.clipboard.writeText(message);

    // Open or focus the composer in agent mode
    try {
      await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
    } catch {
      // Fallback: try opening regular chat
      await vscode.commands.executeCommand("workbench.action.chat.open");
    }

    // Wait for the chat panel to be ready
    await new Promise((resolve) => setTimeout(resolve, 150));

    // Focus the composer input
    try {
      await vscode.commands.executeCommand("composer.focusComposer");
    } catch {
      // May not be needed if already focused
    }

    await new Promise((resolve) => setTimeout(resolve, 50));

    // Paste the message using the standard paste command
    await vscode.commands.executeCommand("editor.action.clipboardPasteAction");

    await new Promise((resolve) => setTimeout(resolve, 50));

    // Submit the chat
    try {
      await vscode.commands.executeCommand("composer.submitChat");
    } catch {
      try {
        await vscode.commands.executeCommand("composer.submit");
      } catch {
        await vscode.commands.executeCommand("workbench.action.chat.submit");
      }
    }

    return true;
  } catch (error) {
    logger.error("Failed to send to chat", error);
    return false;
  } finally {
    // Restore previous clipboard content after a short delay
    setTimeout(async () => {
      try {
        await vscode.env.clipboard.writeText(previousClipboard);
      } catch {
        // Ignore clipboard restore errors
      }
    }, 500);
  }
}

/**
 * Send message to chat with fallback to clipboard notification.
 */
async function sendOrCopyToChat(message: string, description: string): Promise<void> {
  const config = vscode.workspace.getConfiguration("aa-workflow");
  const autoSend = config.get<boolean>("autoSendToChat", true);

  if (autoSend) {
    const sent = await sendToCursorChat(message);
    if (sent) {
      return;
    }
  }

  // Fallback: Copy to clipboard and show notification with action
  await vscode.env.clipboard.writeText(message);
  const action = await vscode.window.showInformationMessage(
    `${description} - Copied to clipboard. Paste in chat to run.`,
    "Open Chat"
  );
  if (action === "Open Chat") {
    await vscode.commands.executeCommand("workbench.action.chat.open");
  }
}

/**
 * Load all skills from the skills directory
 */
let _skillsCache: Array<{ name: string; label: string; description: string }> = [];

async function loadSkillsFromDbusAsync(): Promise<Array<{
  name: string;
  label: string;
  description: string;
}>> {
  try {
    const result = await dbus.config_getSkillsList();
    if (result.success && result.data) {
      const data = result.data as any;
      const skills = (data.skills || []).map((s: any) => {
        const name = s.name;
        const label = name
          .split("_")
          .map((word: string) => word.charAt(0).toUpperCase() + word.slice(1))
          .join(" ");
        return {
          name,
          label,
          description: s.description || `Run ${name} skill`,
        };
      });
      _skillsCache = skills.sort((a: any, b: any) => a.label.localeCompare(b.label));
      return _skillsCache;
    }
  } catch (e) {
    logger.error("Failed to load skills via D-Bus", e);
  }
  return _skillsCache;
}

function loadSkillsFromDisk(): Array<{
  name: string;
  label: string;
  description: string;
}> {
  // Return cached skills (populated by async D-Bus call)
  return _skillsCache;
}

/**
 * Get appropriate icon for a skill.
 * Uses exact matches first, then pattern-based inference for unknown skills.
 */
function getSkillIcon(skillName: string): string {
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

  // Pattern-based icon inference for new/unknown skills
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

export function registerCommands(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider,
  statusBarManager: StatusBarManager
) {
  // Show full status in output panel
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.showStatus", async () => {
      const status = dataProvider.getStatus();
      const output = vscode.window.createOutputChannel("AI Workflow Status");

      output.clear();
      output.appendLine("=== AI Workflow Status ===");
      output.appendLine(
        `Last updated: ${status.lastUpdated?.toISOString() || "never"}`
      );
      output.appendLine("");

      // Slack
      output.appendLine("## Slack Daemon");
      if (status.slack) {
        output.appendLine(
          `  Status: ${status.slack.online ? "Online" : "Offline"}`
        );
        output.appendLine(`  Polls: ${status.slack.polls}`);
        output.appendLine(`  Processed: ${status.slack.processed}`);
        output.appendLine(`  Responded: ${status.slack.responded}`);
        output.appendLine(`  Errors: ${status.slack.errors}`);
      } else {
        output.appendLine("  Not running");
      }
      output.appendLine("");

      // Active Issue
      output.appendLine("## Active Issue");
      if (status.activeIssue) {
        output.appendLine(`  Key: ${status.activeIssue.key}`);
        output.appendLine(`  Summary: ${status.activeIssue.summary}`);
        output.appendLine(`  Status: ${status.activeIssue.status}`);
        output.appendLine(`  Branch: ${status.activeIssue.branch || "none"}`);
      } else {
        output.appendLine("  No active issue");
      }
      output.appendLine("");

      // Active MR
      output.appendLine("## Active MR");
      if (status.activeMR) {
        output.appendLine(`  ID: !${status.activeMR.id}`);
        output.appendLine(`  Title: ${status.activeMR.title}`);
        output.appendLine(`  Pipeline: ${status.activeMR.pipelineStatus}`);
        output.appendLine(`  Needs Review: ${status.activeMR.needsReview}`);
      } else {
        output.appendLine("  No active MR");
      }
      output.appendLine("");

      // Environment
      output.appendLine("## Environment");
      if (status.environment) {
        output.appendLine(
          `  Stage: ${status.environment.stageStatus} (${status.environment.stageAlerts} alerts)`
        );
        output.appendLine(
          `  Prod: ${status.environment.prodStatus} (${status.environment.prodAlerts} alerts)`
        );
      } else {
        output.appendLine("  Status unknown");
      }
      output.appendLine("");

      // Namespaces
      output.appendLine("## Ephemeral Namespaces");
      if (status.namespaces && status.namespaces.length > 0) {
        for (const ns of status.namespaces) {
          output.appendLine(`  - ${ns.name}`);
          output.appendLine(`    Status: ${ns.status || "unknown"}`);
          if (ns.mrId) output.appendLine(`    MR: !${ns.mrId}`);
          if (ns.expires) output.appendLine(`    Expires: ${ns.expires}`);
        }
      } else {
        output.appendLine("  No active namespaces");
      }

      output.show();
    })
  );

  // Open Jira issue in browser
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openJiraIssue", async () => {
      const status = dataProvider.getStatus();

      if (!status.activeIssue) {
        // Ask for issue key
        const key = await vscode.window.showInputBox({
          prompt: "Enter Jira issue key",
          placeHolder: "AAP-12345",
        });
        if (key) {
          const url = `${dataProvider.getJiraUrl()}/browse/${key}`;
          vscode.env.openExternal(vscode.Uri.parse(url));
        }
        return;
      }

      const url = `${dataProvider.getJiraUrl()}/browse/${status.activeIssue.key}`;
      vscode.env.openExternal(vscode.Uri.parse(url));
    })
  );

  // Open MR in browser
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openMR", async () => {
      const status = dataProvider.getStatus();

      if (!status.activeMR) {
        vscode.window.showInformationMessage("No active merge request");
        return;
      }

      if (status.activeMR.url) {
        vscode.env.openExternal(vscode.Uri.parse(status.activeMR.url));
      } else {
        const url = `${dataProvider.getGitLabUrl()}/${status.activeMR.project}/-/merge_requests/${status.activeMR.id}`;
        vscode.env.openExternal(vscode.Uri.parse(url));
      }
    })
  );

  // Investigate alert - opens terminal with skill
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.investigateAlert", async () => {
      const status = dataProvider.getStatus();

      // Show quick pick for environment
      const selected = await vscode.window.showQuickPick(
        [
          {
            label: "$(server) Stage",
            value: "stage",
            description: `${status.environment?.stageAlerts || 0} alerts`,
          },
          {
            label: "$(flame) Production",
            value: "prod",
            description: `${status.environment?.prodAlerts || 0} alerts`,
          },
        ],
        { placeHolder: "Select environment to investigate" }
      );

      if (!selected) {
        return;
      }

      const envName = selected.label.replace(/\$\([^)]+\)\s*/, "");
      // Use slash command with argument for full context
      await sendOrCopyToChat(
        `/investigate-alert ${selected.value}`,
        `Investigating ${envName} alerts`
      );
    })
  );

  // Refresh status
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.refreshStatus", async () => {
      await dataProvider.refresh();
      statusBarManager.update();
      vscode.window.showInformationMessage("AI Workflow status refreshed");
    })
  );

  // Switch agent/persona
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.switchAgent", async () => {
      const agents = [
        {
          label: "$(robot) Core",
          value: "",
          description: "Base tools only",
        },
        {
          label: "$(code) Developer",
          value: "developer",
          description: "Coding, PRs, code review",
        },
        {
          label: "$(server-process) DevOps",
          value: "devops",
          description: "Deployments, k8s, ephemeral",
        },
        {
          label: "$(flame) Incident",
          value: "incident",
          description: "Production issues, alerts",
        },
        {
          label: "$(package) Release",
          value: "release",
          description: "Shipping, Konflux, Quay",
        },
      ];

      const selected = await vscode.window.showQuickPick(agents, {
        placeHolder: "Select an agent to load",
      });

      if (!selected) {
        return;
      }

      // Update status bar
      statusBarManager.setAgent(selected.value);

      // Send the slash command to load the agent (uses .cursor/commands/load-*.md context)
      if (selected.value) {
        const agentName = selected.label.replace(/\$\([^)]+\)\s*/, "");
        // Use slash command if it exists, otherwise use persona_load directly
        const slashCmd = `/load-${selected.value}`;
        if (slashCommandExists(slashCmd)) {
          await sendOrCopyToChat(slashCmd, `Loading ${agentName} agent`);
        } else {
          await sendOrCopyToChat(
            `persona_load("${selected.value}")`,
            `Loading ${agentName} agent`
          );
        }
      } else {
        vscode.window.showInformationMessage(
          "Core mode - base workflow tools only"
        );
      }
    })
  );

  // Show namespace details
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.showNamespace", async () => {
      const status = dataProvider.getStatus();
      const namespaces = status.namespaces || [];

      if (namespaces.length === 0) {
        vscode.window.showInformationMessage("No active ephemeral namespaces");
        return;
      }

      const items = namespaces.map((ns) => ({
        label: `$(cloud-upload) ${ns.name}`,
        description: ns.status || "active",
        detail: ns.mrId
          ? `MR !${ns.mrId} • ${ns.commitSha?.substring(0, 8) || ""}${ns.expires ? ` • Expires: ${ns.expires}` : ""}`
          : undefined,
        ns,
      }));

      const selected = await vscode.window.showQuickPick(items, {
        placeHolder: "Select a namespace",
      });

      if (!selected) {
        return;
      }

      // Show namespace actions
      const action = await vscode.window.showQuickPick(
        [
          { label: "$(terminal) Open Shell", value: "shell" },
          { label: "$(list-flat) View Pods", value: "pods" },
          { label: "$(output) View Logs", value: "logs" },
          { label: "$(trash) Release Namespace", value: "release" },
        ],
        { placeHolder: `Actions for ${selected.ns.name}` }
      );

      if (!action) {
        return;
      }

      // Show command hints
      switch (action.value) {
        case "shell":
          vscode.window.showInformationMessage(
            `Run: kubectl --kubeconfig=~/.kube/config.e exec -it -n ${selected.ns.name} <pod> -- bash`
          );
          break;
        case "pods":
          vscode.window.showInformationMessage(
            `Run: kubectl --kubeconfig=~/.kube/config.e get pods -n ${selected.ns.name}`
          );
          break;
        case "logs":
          vscode.window.showInformationMessage(
            `Run: kubectl --kubeconfig=~/.kube/config.e logs -n ${selected.ns.name} <pod>`
          );
          break;
        case "release":
          vscode.window.showInformationMessage(
            `To release: bonfire namespace release ${selected.ns.name}`
          );
          break;
      }
    })
  );

  // Run skill picker - dynamically loads all skills from disk
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.runSkill", async () => {
      const skills = loadSkillsFromDisk();

      if (skills.length === 0) {
        vscode.window.showWarningMessage(
          "No skills found. Check that skills directory exists."
        );
        return;
      }

      const quickPickItems = skills.map((skill) => ({
        label: `$(${getSkillIcon(skill.name)}) ${skill.label}`,
        description: skill.name,
        detail: skill.description,
        skill: skill.name,
      }));

      const selected = await vscode.window.showQuickPick(quickPickItems, {
        placeHolder: `Select a skill to run (${skills.length} available)`,
        matchOnDescription: true,
        matchOnDetail: true,
      });

      if (!selected) {
        return;
      }

      const skillLabel = selected.label.replace(/\$\([^)]+\)\s*/, "");

      // Use slash command if available (provides full context from .cursor/commands/)
      const slashCmd = getSlashCommandForSkill(selected.skill);
      if (slashCmd && slashCommandExists(slashCmd)) {
        await sendOrCopyToChat(slashCmd, `Running ${skillLabel}`);
      } else {
        await sendOrCopyToChat(
          `skill_run("${selected.skill}")`,
          `Running ${skillLabel} skill`
        );
      }
    })
  );

  // Run skill by name (called from tree view)
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.runSkillByName",
      async (skillName: string) => {
        if (!skillName) {
          // Fall back to picker
          vscode.commands.executeCommand("aa-workflow.runSkill");
          return;
        }

        // Use slash command if available
        const slashCmd = getSlashCommandForSkill(skillName);
        if (slashCmd && slashCommandExists(slashCmd)) {
          await sendOrCopyToChat(slashCmd, `Running ${skillName}`);
        } else {
          await sendOrCopyToChat(
            `skill_run("${skillName}")`,
            `Running ${skillName} skill`
          );
        }
      }
    )
  );

  // Start work shortcut - uses /start-work slash command with argument
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.startWork", async () => {
      const issueKey = await vscode.window.showInputBox({
        prompt: "Enter Jira issue key to start work on",
        placeHolder: "AAP-12345",
        validateInput: (value) => {
          if (!value) return null;
          if (!/^[A-Z]+-\d+$/.test(value)) {
            return "Issue key should be in format: PROJECT-12345";
          }
          return null;
        },
      });

      if (!issueKey) {
        return;
      }

      // Use slash command with argument for full context
      await sendOrCopyToChat(
        `/start-work ${issueKey}`,
        `Starting work on ${issueKey}`
      );
    })
  );

  // Coffee shortcut - uses /coffee slash command for full context
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.coffee", async () => {
      await sendOrCopyToChat("/coffee", "Running morning briefing ☕");
    })
  );

  // Beer shortcut - uses /beer slash command for full context
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.beer", async () => {
      await sendOrCopyToChat("/beer", "Running end of day summary 🍺");
    })
  );

  // Work Analysis - generate work activity report
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.workAnalysis", async () => {
      // Ask for optional date range
      const rangeChoice = await vscode.window.showQuickPick(
        [
          {
            label: "$(calendar) Last 6 months (default)",
            value: "default",
            description: "Full 6-month analysis",
          },
          {
            label: "$(calendar) Last month",
            value: "1month",
            description: "Past 30 days",
          },
          {
            label: "$(calendar) Last 2 weeks",
            value: "2weeks",
            description: "Sprint review period",
          },
          {
            label: "$(calendar) Custom range...",
            value: "custom",
            description: "Specify start and end dates",
          },
        ],
        {
          placeHolder: "Select time period for work analysis",
          title: "Work Analysis Report",
        }
      );

      if (!rangeChoice) {
        return;
      }

      let args = "{}";

      if (rangeChoice.value === "1month") {
        const endDate = new Date().toISOString().split("T")[0];
        const startDate = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)
          .toISOString()
          .split("T")[0];
        args = `{"start_date": "${startDate}", "end_date": "${endDate}"}`;
      } else if (rangeChoice.value === "2weeks") {
        const endDate = new Date().toISOString().split("T")[0];
        const startDate = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000)
          .toISOString()
          .split("T")[0];
        args = `{"start_date": "${startDate}", "end_date": "${endDate}"}`;
      } else if (rangeChoice.value === "custom") {
        const startDate = await vscode.window.showInputBox({
          prompt: "Start date (YYYY-MM-DD)",
          placeHolder: "2025-01-01",
          validateInput: (value) => {
            if (!value) return "Start date is required";
            if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
              return "Use YYYY-MM-DD format";
            }
            return null;
          },
        });

        if (!startDate) {
          return;
        }

        const endDate = await vscode.window.showInputBox({
          prompt: "End date (YYYY-MM-DD)",
          placeHolder: new Date().toISOString().split("T")[0],
          value: new Date().toISOString().split("T")[0],
          validateInput: (value) => {
            if (!value) return "End date is required";
            if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
              return "Use YYYY-MM-DD format";
            }
            return null;
          },
        });

        if (!endDate) {
          return;
        }

        args = `{"start_date": "${startDate}", "end_date": "${endDate}"}`;
      }

      await sendOrCopyToChat(
        `skill_run("work_analysis", '${args}')`,
        "Generating work analysis report 📊"
      );
    })
  );
}
