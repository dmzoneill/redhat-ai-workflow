/**
 * Command Registration
 *
 * Registers all command palette commands and their handlers.
 */

import * as vscode from "vscode";
import { WorkflowDataProvider } from "./dataProvider";
import { StatusBarManager } from "./statusBar";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

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
      output.appendLine(`Last updated: ${status.lastUpdated?.toISOString() || "never"}`);
      output.appendLine("");

      // Slack
      output.appendLine("## Slack Daemon");
      if (status.slack) {
        output.appendLine(`  Status: ${status.slack.online ? "Online" : "Offline"}`);
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
        output.appendLine(`  Stage: ${status.environment.stageStatus} (${status.environment.stageAlerts} alerts)`);
        output.appendLine(`  Prod: ${status.environment.prodStatus} (${status.environment.prodAlerts} alerts)`);
      } else {
        output.appendLine("  Status unknown");
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

      let environment = "stage";
      if (status.environment?.prodAlerts && status.environment.prodAlerts > 0) {
        environment = "prod";
      }

      // Show quick pick for environment
      const selected = await vscode.window.showQuickPick(
        [
          { label: "Stage", value: "stage", description: `${status.environment?.stageAlerts || 0} alerts` },
          { label: "Production", value: "prod", description: `${status.environment?.prodAlerts || 0} alerts` },
        ],
        { placeHolder: "Select environment to investigate" }
      );

      if (!selected) {
        return;
      }

      // Open terminal and run investigate skill
      const terminal = vscode.window.createTerminal("AI Workflow");
      terminal.sendText(`cd ~/src/redhat-ai-workflow`);
      terminal.sendText(
        `echo "Use: skill_run('investigate_alert', '{\"environment\": \"${selected.value}\"}')" && echo "Or run /investigate in the chat"`
      );
      terminal.show();

      vscode.window.showInformationMessage(
        `To investigate ${selected.label} alerts, use the chat command: /investigate ${selected.value}`
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

  // Run skill picker
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.runSkill", async () => {
      const skills = [
        { label: "☕ Coffee", description: "Morning briefing", skill: "coffee" },
        { label: "🍺 Beer", description: "End of day summary", skill: "beer" },
        { label: "🚀 Start Work", description: "Begin work on Jira issue", skill: "start_work" },
        { label: "📝 Create MR", description: "Create merge request", skill: "create_mr" },
        { label: "🔍 Review PR", description: "Review a pull request", skill: "review_pr" },
        { label: "🚨 Investigate Alert", description: "Investigate environment alert", skill: "investigate_alert" },
        { label: "📊 Standup Summary", description: "Generate standup summary", skill: "standup_summary" },
        { label: "✅ Close Issue", description: "Close a Jira issue", skill: "close_issue" },
        { label: "🧠 Memory View", description: "View persistent memory", skill: "memory_view" },
      ];

      const selected = await vscode.window.showQuickPick(skills, {
        placeHolder: "Select a skill to run",
      });

      if (!selected) {
        return;
      }

      vscode.window.showInformationMessage(
        `To run ${selected.label}, use the chat command: /${selected.skill}`
      );
    })
  );

  // Start work shortcut
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.startWork", async () => {
      const issueKey = await vscode.window.showInputBox({
        prompt: "Enter Jira issue key to start work on",
        placeHolder: "AAP-12345",
      });

      if (!issueKey) {
        return;
      }

      vscode.window.showInformationMessage(
        `To start work on ${issueKey}, use the chat command: /start-work ${issueKey}`
      );
    })
  );

  // Coffee shortcut
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.coffee", async () => {
      vscode.window.showInformationMessage(
        "To run the morning briefing, use the chat command: /coffee"
      );
    })
  );

  // Beer shortcut
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.beer", async () => {
      vscode.window.showInformationMessage(
        "To run the end of day summary, use the chat command: /beer"
      );
    })
  );
}







