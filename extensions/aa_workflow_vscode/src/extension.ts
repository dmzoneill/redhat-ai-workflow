/**
 * AI Workflow VSCode Extension
 *
 * Provides real-time status indicators and quick actions for the AI Workflow system.
 *
 * Features:
 * - Status bar items showing Slack daemon, active issue, environment health, MR status
 * - Click actions to open Jira, GitLab, or run investigations
 * - Command palette integration for common workflows
 * - Workspace state tracking from MCP server
 */

import * as vscode from "vscode";
import { StatusBarManager } from "./statusBar";
import { WorkflowDataProvider } from "./dataProvider";
import { registerCommands } from "./commands";
import { registerTreeView, WorkflowTreeProvider } from "./treeView";
import { registerNotifications, NotificationManager } from "./notifications";
import { registerCommandCenter, registerCommandCenterSerializer, getCommandCenterPanel } from "./commandCenter";
import { registerSkillExecutionWatcher } from "./skillExecutionWatcher";
import { registerSkillFlowchartPanel } from "./skillFlowchartPanel";
import { getWorkspaceStateProvider, disposeWorkspaceStateProvider, WorkspaceStateProvider } from "./workspaceStateProvider";

let statusBarManager: StatusBarManager | undefined;
let dataProvider: WorkflowDataProvider | undefined;
let treeProvider: WorkflowTreeProvider | undefined;
let notificationManager: NotificationManager | undefined;
let workspaceStateProvider: WorkspaceStateProvider | undefined;
let refreshInterval: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext) {
  console.log("AI Workflow extension activating...");

  // Initialize the data provider FIRST (needed by serializers)
  dataProvider = new WorkflowDataProvider();

  // Initialize workspace state provider (watches MCP server exports)
  workspaceStateProvider = getWorkspaceStateProvider();
  console.log("[Extension] Workspace state provider initialized");

  // Listen for workspace state changes
  workspaceStateProvider.onDidChange((state) => {
    console.log(`[Extension] Workspace state changed: ${state?.workspace_count || 0} workspace(s)`);
    // Refresh UI when workspace state changes
    treeProvider?.refresh();
    statusBarManager?.update();
  });

  // IMPORTANT: Register webview serializers IMMEDIATELY after data provider
  // This ensures VS Code can restore panels even if other init takes time
  // Both serializers must be registered before VS Code tries to restore any panels
  console.log("[Extension] Registering webview serializers...");
  registerSkillFlowchartPanel(context);
  registerCommandCenterSerializer(context, dataProvider);

  // Initialize status bar items
  statusBarManager = new StatusBarManager(context, dataProvider);

  // Initialize tree view
  treeProvider = registerTreeView(context, dataProvider);

  // Initialize notifications
  notificationManager = registerNotifications(context, dataProvider);

  // Initialize unified Command Center commands (serializer already registered above)
  registerCommandCenter(context, dataProvider);

  // Initialize skill execution watcher (connects to MCP server and updates Command Center)
  registerSkillExecutionWatcher(context);

  // Register "Open All Views" command (now just opens Command Center)
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openAllViews", async () => {
      await vscode.commands.executeCommand("aa-workflow.openCommandCenter");
      await vscode.commands.executeCommand("aaWorkflowExplorer.focus");
    })
  );

  // Legacy command aliases for backwards compatibility
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openDashboard", () => {
      vscode.commands.executeCommand("aa-workflow.openCommandCenter", "overview");
    })
  );
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openAgentOverview", () => {
      vscode.commands.executeCommand("aa-workflow.openCommandCenter", "overview");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openSkillVisualizer", () => {
      vscode.commands.executeCommand("aa-workflow.openCommandCenter", "skills");
    })
  );

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

    // Set default agent from config
    const defaultAgent = config.get<string>("defaultAgent", "");
    if (defaultAgent && statusBarManager) {
      statusBarManager.setAgent(defaultAgent);
    }
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
  disposeWorkspaceStateProvider();
}

/**
 * Get the workspace state provider instance (for use by other modules)
 */
export function getWorkspaceState(): WorkspaceStateProvider | undefined {
  return workspaceStateProvider;
}
