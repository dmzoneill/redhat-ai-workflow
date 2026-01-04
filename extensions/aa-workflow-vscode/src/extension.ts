/**
 * AI Workflow VSCode Extension
 *
 * Provides real-time status indicators and quick actions for the AI Workflow system.
 *
 * Features:
 * - Status bar items showing Slack daemon, active issue, environment health, MR status
 * - Click actions to open Jira, GitLab, or run investigations
 * - Command palette integration for common workflows
 */

import * as vscode from "vscode";
import { StatusBarManager } from "./statusBar";
import { WorkflowDataProvider } from "./dataProvider";
import { registerCommands } from "./commands";
import { registerTreeView, WorkflowTreeProvider } from "./treeView";
import { registerNotifications, NotificationManager } from "./notifications";
import { registerDashboard } from "./dashboard";
import { registerSkillVisualizer } from "./skillVisualizer";

let statusBarManager: StatusBarManager | undefined;
let dataProvider: WorkflowDataProvider | undefined;
let treeProvider: WorkflowTreeProvider | undefined;
let notificationManager: NotificationManager | undefined;
let refreshInterval: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext) {
  console.log("AI Workflow extension activating...");

  // Initialize the data provider (connects to D-Bus/memory)
  dataProvider = new WorkflowDataProvider();

  // Initialize status bar items
  statusBarManager = new StatusBarManager(context, dataProvider);

  // Initialize tree view
  treeProvider = registerTreeView(context, dataProvider);

  // Initialize notifications
  notificationManager = registerNotifications(context, dataProvider);

  // Initialize dashboard webview
  registerDashboard(context, dataProvider);

  // Initialize skill visualizer
  registerSkillVisualizer(context);

  // Register commands
  registerCommands(context, dataProvider, statusBarManager);

  // Start periodic refresh
  const config = vscode.workspace.getConfiguration("aa-workflow");
  const intervalSeconds = config.get<number>("refreshInterval", 30);

  refreshInterval = setInterval(async () => {
    await dataProvider?.refresh();
    statusBarManager?.update();
    treeProvider?.refresh();
    await notificationManager?.checkAndNotify();
  }, intervalSeconds * 1000);

  // Initial update
  dataProvider.refresh().then(() => {
    statusBarManager?.update();
    treeProvider?.refresh();
  });

  console.log("AI Workflow extension activated!");
}

export function deactivate() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
  }
  statusBarManager?.dispose();
  notificationManager?.dispose();
  dataProvider?.dispose();
}
