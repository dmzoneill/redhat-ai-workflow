/**
 * Notification Manager
 *
 * Shows toast notifications for important workflow events:
 * - MR approved
 * - Pipeline failed
 * - Alert firing
 * - Namespace expiring
 * - Slack messages received/processed
 * - Pending approvals
 *
 * Subscribes to D-Bus signals for real-time updates using dbus-monitor.
 */

import * as vscode from "vscode";
import { WorkflowDataProvider, WorkflowStatus } from "./dataProvider";
import { spawn, ChildProcess } from "child_process";
import { createLogger } from "./logger";

const logger = createLogger("Notifications");

// D-Bus signal types we listen for
interface SlackMessageSignal {
  type: "MessageReceived" | "MessageProcessed" | "PendingApproval";
  data: any;
}

/**
 * Execute a command using spawn with bash --norc --noprofile to avoid sourcing
 * .bashrc.d scripts (which can trigger Bitwarden password prompts).
 */
async function execAsync(command: string, options?: { timeout?: number; cwd?: string }): Promise<{ stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    const proc = spawn('/bin/bash', ['--norc', '--noprofile', '-c', command], {
      cwd: options?.cwd,
      env: {
        ...process.env,
        BASH_ENV: '',
        ENV: '',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';
    let killed = false;

    const timeout = options?.timeout || 30000;
    const timer = setTimeout(() => {
      killed = true;
      proc.kill('SIGTERM');
      reject(new Error(`Command timed out after ${timeout}ms`));
    }, timeout);

    proc.stdout.on('data', (data) => { stdout += data.toString(); });
    proc.stderr.on('data', (data) => { stderr += data.toString(); });

    proc.on('close', (code) => {
      clearTimeout(timer);
      if (killed) return;

      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        const error = new Error(`Command failed with exit code ${code}: ${stderr}`);
        (error as any).code = code;
        reject(error);
      }
    });

    proc.on('error', (err) => {
      clearTimeout(timer);
      reject(err);
    });
  });
}

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
  private dbusMonitor: ChildProcess | null = null;
  private signalBuffer: string = "";
  private onSlackSignal: ((signal: SlackMessageSignal) => void) | null = null;

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
   * Set callback for Slack signal events (used by CommandCenter for real-time updates)
   */
  public setSlackSignalCallback(callback: (signal: SlackMessageSignal) => void): void {
    this.onSlackSignal = callback;
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
    // Poll D-Bus for Slack events every 30 seconds (fallback)
    this.dbusWatcher = setInterval(async () => {
      try {
        await this.checkSlackEvents();
      } catch {
        // D-Bus not available, skip
      }
    }, 30000);

    // Start real-time D-Bus signal monitoring
    this.startDbusSignalMonitor();
  }

  /**
   * Start dbus-monitor to listen for real-time signals from Slack daemon
   */
  private startDbusSignalMonitor(): void {
    try {
      // Use dbus-monitor to watch for signals from our services
      this.dbusMonitor = spawn('/bin/bash', ['--norc', '--noprofile', '-c',
        `dbus-monitor --session "type='signal',interface='com.aiworkflow.BotSlack'"`
      ], {
        env: {
          ...process.env,
          BASH_ENV: '',
          ENV: '',
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      });

      this.dbusMonitor.stdout?.on('data', (data: Buffer) => {
        this.handleDbusMonitorOutput(data.toString());
      });

      this.dbusMonitor.stderr?.on('data', (data: Buffer) => {
        logger.debug(`dbus-monitor stderr: ${data.toString()}`);
      });

      this.dbusMonitor.on('close', (code) => {
        logger.debug(`dbus-monitor exited with code ${code}`);
        this.dbusMonitor = null;
        // Restart after a delay if it wasn't intentionally stopped
        setTimeout(() => {
          if (!this.dbusMonitor) {
            this.startDbusSignalMonitor();
          }
        }, 5000);
      });

      this.dbusMonitor.on('error', (err) => {
        logger.error(`dbus-monitor error: ${err.message}`);
        this.dbusMonitor = null;
      });

      logger.info("D-Bus signal monitor started");
    } catch (err) {
      logger.error(`Failed to start dbus-monitor: ${err}`);
    }
  }

  /**
   * Parse dbus-monitor output and handle signals
   */
  private handleDbusMonitorOutput(output: string): void {
    this.signalBuffer += output;

    // dbus-monitor output format:
    // signal time=... sender=... -> destination=... serial=... path=/... interface=... member=MessageReceived
    //    string "json_data"

    // Split by signal boundaries
    const signalPattern = /signal\s+time=[\d.]+\s+sender=[^\s]+\s+->\s+destination=[^\s]+\s+serial=\d+\s+path=([^\s]+)\s+interface=([^\s]+)\s+member=(\w+)/g;

    let match;
    while ((match = signalPattern.exec(this.signalBuffer)) !== null) {
      const [fullMatch, path, iface, member] = match;
      const startIndex = match.index + fullMatch.length;

      // Find the string argument that follows
      const stringPattern = /\s+string\s+"([^"]*)"/;
      const remaining = this.signalBuffer.substring(startIndex);
      const stringMatch = stringPattern.exec(remaining);

      if (stringMatch && iface === "com.aiworkflow.BotSlack") {
        const jsonData = stringMatch[1];
        this.handleSlackSignal(member, jsonData);

        // Clear processed part of buffer
        const endIndex = startIndex + stringMatch.index + stringMatch[0].length;
        this.signalBuffer = this.signalBuffer.substring(match.index + endIndex);
        signalPattern.lastIndex = 0; // Reset regex
      }
    }

    // Prevent buffer from growing too large
    if (this.signalBuffer.length > 10000) {
      this.signalBuffer = this.signalBuffer.substring(this.signalBuffer.length - 5000);
    }
  }

  /**
   * Handle a Slack D-Bus signal
   */
  private handleSlackSignal(signalName: string, jsonData: string): void {
    try {
      const data = JSON.parse(jsonData);
      logger.debug(`Received Slack signal: ${signalName}`);

      // Notify callback if set (for CommandCenter real-time updates)
      if (this.onSlackSignal) {
        this.onSlackSignal({
          type: signalName as SlackMessageSignal["type"],
          data
        });
      }

      // Handle specific signals
      switch (signalName) {
        case "MessageReceived":
          this.handleMessageReceived(data);
          break;
        case "MessageProcessed":
          this.handleMessageProcessed(data);
          break;
        case "PendingApproval":
          this.handlePendingApproval(data);
          break;
      }
    } catch (err) {
      logger.error(`Failed to parse signal data: ${err}`);
    }
  }

  /**
   * Handle MessageReceived signal - new message from Slack
   */
  private handleMessageReceived(data: any): void {
    // Only show notification for important messages (mentions, DMs)
    if (data.is_mention || data.is_dm) {
      const userName = data.user_name || "Someone";
      const channelName = data.channel_name || "a channel";
      const preview = (data.text || "").substring(0, 50);

      vscode.window.showInformationMessage(
        `💬 ${userName} in ${channelName}: ${preview}...`
      );
    }
  }

  /**
   * Handle MessageProcessed signal - bot processed a message
   */
  private handleMessageProcessed(data: any): void {
    // Could update UI to show processing status
    logger.debug(`Message processed: ${data.message_id} - ${data.status}`);
  }

  /**
   * Handle PendingApproval signal - message needs approval
   */
  private handlePendingApproval(data: any): void {
    const userName = data.user_name || "Someone";
    const preview = (data.response_text || "").substring(0, 80);

    vscode.window.showWarningMessage(
      `⏳ Pending approval for ${userName}: ${preview}...`,
      "View Pending"
    ).then(action => {
      if (action === "View Pending") {
        vscode.commands.executeCommand("aa-workflow.openCommandCenter", "slack");
      }
    });
  }

  /**
   * Stop the D-Bus signal monitor
   */
  private stopDbusSignalMonitor(): void {
    if (this.dbusMonitor) {
      this.dbusMonitor.kill();
      this.dbusMonitor = null;
    }
  }

  private async checkSlackEvents(): Promise<void> {
    try {
      // Check for new unread messages via D-Bus
      const { stdout } = await execAsync(
        `dbus-send --session --print-reply --dest=com.aiworkflow.BotSlack ` +
          `/com/aiworkflow/BotSlack com.aiworkflow.BotSlack.GetPending`
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
    this.stopDbusSignalMonitor();
  }
}

// Export the signal type for use by other modules
export type { SlackMessageSignal };

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
