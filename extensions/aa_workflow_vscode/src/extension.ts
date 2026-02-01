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
import { registerMemoryTab, MemoryTreeProvider } from "./memoryTreeView";
import { registerSlidesTab, SlidesTreeProvider } from "./slidesTreeView";
import { registerNotifications, NotificationManager } from "./notifications";
import { registerCommandCenter, registerCommandCenterSerializer, getCommandCenterPanel } from "./commandCenter";
import { registerSkillExecutionWatcher } from "./skillExecutionWatcher";
import { getWorkspaceStateProvider, disposeWorkspaceStateProvider, WorkspaceStateProvider } from "./workspaceStateProvider";
import { registerTestCommand } from "./testChatRefresh";
import { SkillToastManager, SkillToastWebview } from "./skillToast";
import { disposeSkillWebSocketClient } from "./skillWebSocket";
import { registerChatDbusService, unregisterChatDbusService } from "./chatDbusService";
import { createLogger, disposeLogger } from "./logger";
import { getNotificationWatcher, stopNotificationWatcher } from "./notificationWatcher";

const logger = createLogger("Extension");

let statusBarManager: StatusBarManager | undefined;
let dataProvider: WorkflowDataProvider | undefined;
let treeProvider: WorkflowTreeProvider | undefined;
let memoryTreeProvider: MemoryTreeProvider | undefined;
let slidesTreeProvider: SlidesTreeProvider | undefined;
let notificationManager: NotificationManager | undefined;
let workspaceStateProvider: WorkspaceStateProvider | undefined;
let skillToastManager: SkillToastManager | undefined;
let skillToastWebview: SkillToastWebview | undefined;
let refreshInterval: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext) {
  logger.log("AI Workflow extension activating...");

  // Initialize the data provider FIRST (needed by serializers)
  dataProvider = new WorkflowDataProvider();

  // Initialize workspace state provider (watches MCP server exports)
  workspaceStateProvider = getWorkspaceStateProvider();
  logger.log("Workspace state provider initialized");

  // Listen for workspace state changes
  workspaceStateProvider.onDidChange((state) => {
    logger.log(`Workspace state changed: ${state?.workspace_count || 0} workspace(s)`);
    // Refresh UI when workspace state changes
    treeProvider?.refresh();
    statusBarManager?.update();
  });

  // IMPORTANT: Register webview serializers IMMEDIATELY after data provider
  // This ensures VS Code can restore panels even if other init takes time
  logger.log("Registering webview serializers...");
  registerCommandCenterSerializer(context, dataProvider);

  // Initialize status bar items
  statusBarManager = new StatusBarManager(context, dataProvider);

  // Initialize tree view
  treeProvider = registerTreeView(context, dataProvider);

  // Initialize memory tab
  memoryTreeProvider = registerMemoryTab(context);
  logger.log("Memory tab initialized");

  // Initialize slides tab
  slidesTreeProvider = registerSlidesTab(context);
  logger.log("Slides tab initialized");

  // Initialize notifications
  notificationManager = registerNotifications(context, dataProvider);

  // Initialize unified Command Center commands (serializer already registered above)
  registerCommandCenter(context, dataProvider);

  // Initialize skill execution watcher (connects to MCP server and updates Command Center)
  registerSkillExecutionWatcher(context);

  // Initialize skill toast manager (WebSocket-based real-time updates)
  skillToastManager = new SkillToastManager(context);
  logger.log("Skill toast manager initialized (WebSocket)");

  // Register command to show detailed skill toast webview
  skillToastWebview = new SkillToastWebview(context);
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.showSkillToastWebview", () => {
      skillToastWebview?.show();
    })
  );

  // Register test commands for debugging
  registerTestCommand(context);

  // Register Chat D-Bus service for background processes
  registerChatDbusService().catch((e) => {
    logger.warn("Failed to register Chat D-Bus service: " + e.message);
  });

  // Start notification watcher (watches notifications.json for toast messages)
  const notificationWatcher = getNotificationWatcher();
  notificationWatcher.start();
  context.subscriptions.push({ dispose: () => notificationWatcher.dispose() });
  logger.log("Notification watcher started");

  // Legacy command aliases removed - only openCommandCenter is exposed

  // Register commands
  registerCommands(context, dataProvider, statusBarManager);

  // Start periodic refresh
  const config = vscode.workspace.getConfiguration("aa-workflow");
  const intervalSeconds = config.get<number>("refreshInterval", 30);

  refreshInterval = setInterval(async () => {
    await dataProvider?.refresh();
    statusBarManager?.update();
    treeProvider?.refresh();
    memoryTreeProvider?.refresh();
    slidesTreeProvider?.refresh();
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

  logger.log("AI Workflow extension activated!");
}

export async function deactivate() {
  logger.log("AI Workflow extension deactivating...");

  // Clear interval first to stop any pending refreshes
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = undefined;
  }

  // Dispose in reverse order of creation, with error handling
  try {
    // Unregister D-Bus service first (may have pending calls)
    await unregisterChatDbusService();
  } catch (e: any) {
    logger.error("Error unregistering D-Bus service", e);
  }

  try {
    disposeSkillWebSocketClient();
  } catch (e: any) {
    logger.error("Error disposing WebSocket client", e);
  }

  try {
    stopNotificationWatcher();
  } catch (e: any) {
    logger.error("Error stopping notification watcher", e);
  }

  try {
    disposeWorkspaceStateProvider();
  } catch (e: any) {
    logger.error("Error disposing workspace state provider", e);
  }

  try {
    skillToastWebview?.dispose();
    skillToastManager?.dispose();
    dataProvider?.dispose();
    notificationManager?.dispose();
    statusBarManager?.dispose();
  } catch (e: any) {
    logger.error("Error disposing UI components", e);
  }

  // Dispose logger last
  disposeLogger();
}

/**
 * Get the workspace state provider instance (for use by other modules)
 */
export function getWorkspaceState(): WorkspaceStateProvider | undefined {
  return workspaceStateProvider;
}
