/**
 * Notification Manager
 *
 * Shows toast notifications for important workflow events:
 * - MR approved
 * - Pipeline failed
 * - Alert firing
 * - Namespace expiring
 *
 * Can subscribe to D-Bus signals for real-time updates.
 */

import * as vscode from "vscode";
import { WorkflowDataProvider, WorkflowStatus } from "./dataProvider";
import { exec } from "child_process";
import { promisify } from "util";

const execAsync = promisify(exec);

interface NotificationState {
  lastAlertCount: number;
  lastPipelineStatus: string;
  lastMrId: number;
  shownNotifications: Set<string>;
}

export class NotificationManager {
  private dataProvider: WorkflowDataProvider;
  private state: NotificationState;
  private dbusWatcher: ReturnType<typeof setInterval> | undefined;

  constructor(dataProvider: WorkflowDataProvider) {
    this.dataProvider = dataProvider;
    this.state = {
      lastAlertCount: 0,
      lastPipelineStatus: "",
      lastMrId: 0,
      shownNotifications: new Set(),
    };
  }

  /**
   * Check for changes and show notifications
   */
  public async checkAndNotify(): Promise<void> {
    const status = this.dataProvider.getStatus();

    await Promise.all([
      this.checkAlerts(status),
      this.checkPipeline(status),
      this.checkMR(status),
    ]);
  }

  private async checkAlerts(status: WorkflowStatus): Promise<void> {
    const env = status.environment;
    if (!env) return;

    const currentAlertCount = (env.stageAlerts || 0) + (env.prodAlerts || 0);

    // New alerts appeared
    if (currentAlertCount > this.state.lastAlertCount) {
      const newAlerts = currentAlertCount - this.state.lastAlertCount;

      if (env.prodAlerts && env.prodAlerts > 0) {
        // Production alert - critical
        const action = await vscode.window.showErrorMessage(
          `🔴 Production Alert: ${env.prodAlerts} alert${env.prodAlerts > 1 ? "s" : ""} firing`,
          "Investigate",
          "Dismiss"
        );
        if (action === "Investigate") {
          vscode.commands.executeCommand("aa-workflow.investigateAlert");
        }
      } else if (env.stageAlerts && env.stageAlerts > 0) {
        // Stage alert - warning
        const action = await vscode.window.showWarningMessage(
          `⚠️ Stage Alert: ${env.stageAlerts} alert${env.stageAlerts > 1 ? "s" : ""} firing`,
          "Investigate",
          "Dismiss"
        );
        if (action === "Investigate") {
          vscode.commands.executeCommand("aa-workflow.investigateAlert");
        }
      }
    }

    this.state.lastAlertCount = currentAlertCount;
  }

  private async checkPipeline(status: WorkflowStatus): Promise<void> {
    const mr = status.activeMR;
    if (!mr) return;

    const notificationKey = `pipeline-${mr.id}-${mr.pipelineStatus}`;

    // Don't show if we've already notified for this state
    if (this.state.shownNotifications.has(notificationKey)) {
      return;
    }

    // Pipeline status changed to failed
    if (
      mr.pipelineStatus === "failed" &&
      this.state.lastPipelineStatus !== "failed"
    ) {
      const action = await vscode.window.showErrorMessage(
        `❌ Pipeline failed for MR !${mr.id}`,
        "View MR",
        "Dismiss"
      );
      if (action === "View MR") {
        vscode.commands.executeCommand("aa-workflow.openMR");
      }
      this.state.shownNotifications.add(notificationKey);
    }

    // Pipeline succeeded after being failed
    if (
      mr.pipelineStatus === "success" &&
      this.state.lastPipelineStatus === "failed"
    ) {
      vscode.window.showInformationMessage(
        `✅ Pipeline passed for MR !${mr.id}`
      );
      this.state.shownNotifications.add(notificationKey);
    }

    this.state.lastPipelineStatus = mr.pipelineStatus;
    this.state.lastMrId = mr.id;
  }

  private async checkMR(status: WorkflowStatus): Promise<void> {
    const mr = status.activeMR;
    if (!mr) return;

    // Check if MR needs review and pipeline passed
    if (
      mr.needsReview &&
      (mr.pipelineStatus === "success" || mr.pipelineStatus === "passed")
    ) {
      const notificationKey = `review-needed-${mr.id}`;

      if (!this.state.shownNotifications.has(notificationKey)) {
        const action = await vscode.window.showInformationMessage(
          `🔍 MR !${mr.id} is ready for review`,
          "Open MR",
          "Dismiss"
        );
        if (action === "Open MR") {
          vscode.commands.executeCommand("aa-workflow.openMR");
        }
        this.state.shownNotifications.add(notificationKey);
      }
    }
  }

  /**
   * Start watching D-Bus for real-time events
   */
  public startDbusWatcher(): void {
    // Poll D-Bus for Slack events every 30 seconds
    this.dbusWatcher = setInterval(async () => {
      try {
        await this.checkSlackEvents();
      } catch {
        // D-Bus not available, skip
      }
    }, 30000);
  }

  private async checkSlackEvents(): Promise<void> {
    try {
      // Check for new unread messages via D-Bus
      const { stdout } = await execAsync(
        `dbus-send --session --print-reply --dest=com.aiworkflow.SlackAgent ` +
          `/com/aiworkflow/SlackAgent com.aiworkflow.SlackAgent.GetPending`
      );

      // Parse response for pending message count
      const countMatch = stdout.match(/int32\s+(\d+)/);
      if (countMatch) {
        const pendingCount = parseInt(countMatch[1], 10);
        if (pendingCount > 0) {
          vscode.window.showInformationMessage(
            `📬 ${pendingCount} pending Slack message${pendingCount > 1 ? "s" : ""} awaiting approval`
          );
        }
      }
    } catch {
      // D-Bus not available
    }
  }

  /**
   * Show a custom notification
   */
  public async showNotification(
    type: "info" | "warning" | "error",
    message: string,
    actions?: string[]
  ): Promise<string | undefined> {
    switch (type) {
      case "error":
        return vscode.window.showErrorMessage(message, ...(actions || []));
      case "warning":
        return vscode.window.showWarningMessage(message, ...(actions || []));
      default:
        return vscode.window.showInformationMessage(message, ...(actions || []));
    }
  }

  public dispose(): void {
    if (this.dbusWatcher) {
      clearInterval(this.dbusWatcher);
    }
  }
}

export function registerNotifications(
  context: vscode.ExtensionContext,
  dataProvider: WorkflowDataProvider
): NotificationManager {
  const notificationManager = new NotificationManager(dataProvider);

  // Start D-Bus watcher for real-time events
  notificationManager.startDbusWatcher();

  // Register command to manually check notifications
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.checkNotifications",
      async () => {
        await dataProvider.refresh();
        await notificationManager.checkAndNotify();
      }
    )
  );

  return notificationManager;
}







