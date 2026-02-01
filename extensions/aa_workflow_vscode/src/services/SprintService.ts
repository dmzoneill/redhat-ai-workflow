/**
 * SprintService - Sprint Bot Business Logic
 *
 * Handles all sprint-related operations without direct UI dependencies.
 * Uses MessageBus for UI communication and NotificationService for user feedback.
 */

import { dbus } from "../dbusClient";
import { StateStore } from "../state";
import { MessageBus } from "./MessageBus";
import { NotificationService } from "./NotificationService";
import { createLogger } from "../logger";

const logger = createLogger("SprintService");

// ============================================================================
// Types
// ============================================================================

export interface SprintServiceDependencies {
  state: StateStore;
  messages: MessageBus;
  notifications: NotificationService;
  queryDBus: (service: string, path: string, iface: string, method: string, args?: any[]) => Promise<any>;
}

export interface SprintIssue {
  key: string;
  summary: string;
  status: string;
  assignee?: string;
  priority?: string;
  approved?: boolean;
  working?: boolean;
  completed?: boolean;
  aborted?: boolean;
}

export interface SprintState {
  automaticMode: boolean;
  backgroundTasks: boolean;
  running: boolean;
  currentIssue?: string;
  issues: SprintIssue[];
}

export interface SprintBotResult {
  success: boolean;
  data?: any;
  error?: string;
}

// ============================================================================
// SprintService Class
// ============================================================================

export class SprintService {
  private state: StateStore;
  private messages: MessageBus;
  private notifications: NotificationService;
  private queryDBus: SprintServiceDependencies['queryDBus'];
  private onRefreshUI: (() => void) | null = null;

  private readonly SPRINT_DBUS = {
    service: "com.aiworkflow.BotSprint",
    path: "/com/aiworkflow/BotSprint",
    interface: "com.aiworkflow.BotSprint",
  };

  constructor(deps: SprintServiceDependencies) {
    this.state = deps.state;
    this.messages = deps.messages;
    this.notifications = deps.notifications;
    this.queryDBus = deps.queryDBus;
  }

  /**
   * Set callback for when UI refresh is needed
   */
  setOnRefreshUI(callback: () => void): void {
    this.onRefreshUI = callback;
  }

  private refreshUI(): void {
    if (this.onRefreshUI) {
      this.onRefreshUI();
    }
  }

  // ============================================================================
  // D-Bus Helper
  // ============================================================================

  /**
   * Call sprint bot D-Bus method
   */
  private async callSprintBot(
    method: string,
    params: Record<string, unknown> = {}
  ): Promise<SprintBotResult> {
    try {
      const result = await this.queryDBus(
        this.SPRINT_DBUS.service,
        this.SPRINT_DBUS.path,
        this.SPRINT_DBUS.interface,
        "CallMethod",
        [
          { type: "string", value: method },
          { type: "string", value: JSON.stringify(params) },
        ]
      );

      if (result.success && result.data) {
        const parsed = typeof result.data === "string" ? JSON.parse(result.data) : result.data;
        return { success: parsed.success !== false, data: parsed, error: parsed.error };
      }
      return { success: false, error: result.error || "D-Bus call failed" };
    } catch (e: any) {
      return { success: false, error: e.message };
    }
  }

  // ============================================================================
  // State
  // ============================================================================

  /**
   * Get current sprint bot state
   */
  async getState(): Promise<SprintState | null> {
    const result = await this.callSprintBot("get_state", {});
    if (result.success && result.data?.state) {
      return result.data.state as SprintState;
    }
    return null;
  }

  // ============================================================================
  // Issue Actions
  // ============================================================================

  /**
   * Approve an issue for sprint bot processing
   */
  async approveIssue(issueKey: string): Promise<boolean> {
    const result = await this.callSprintBot("approve_issue", { issue_key: issueKey });
    if (result.success) {
      this.notifications.info(`Approved ${issueKey} for sprint bot`);
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to approve ${issueKey}: ${result.error}`);
      return false;
    }
  }

  /**
   * Reject/unapprove an issue
   */
  async rejectIssue(issueKey: string): Promise<boolean> {
    const result = await this.callSprintBot("reject_issue", { issue_key: issueKey });
    if (result.success) {
      this.notifications.info(`Unapproved ${issueKey}`);
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to unapprove ${issueKey}: ${result.error}`);
      return false;
    }
  }

  /**
   * Abort an issue (stop bot processing, allow manual work)
   */
  async abortIssue(issueKey: string): Promise<boolean> {
    const result = await this.callSprintBot("abort_issue", { issue_key: issueKey });
    if (result.success) {
      this.notifications.info(`Aborted ${issueKey} - you can now work on it manually`);
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to abort ${issueKey}: ${result.error}`);
      return false;
    }
  }

  /**
   * Start working on an issue immediately
   */
  async startIssue(issueKey: string): Promise<boolean> {
    // Get current background mode via D-Bus
    const state = await this.getState();
    const useBackground = state?.backgroundTasks ?? false;

    const result = await this.callSprintBot("start_issue", {
      issue_key: issueKey,
      background: useBackground,
    });

    if (result.success) {
      const modeMsg = useBackground ? "in background" : "in foreground";
      this.notifications.info(`Started ${issueKey} ${modeMsg}. ${result.data?.message || ""}`);
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to start ${issueKey}: ${result.error}`);
      return false;
    }
  }

  /**
   * Open an issue in Cursor for interactive continuation
   */
  async openInCursor(issueKey: string): Promise<boolean> {
    const result = await this.callSprintBot("open_in_cursor", { issue_key: issueKey });
    if (result.success) {
      this.notifications.info(`Opened ${issueKey} in Cursor. Review the context and continue working.`);
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to open ${issueKey}: ${result.error}`);
      return false;
    }
  }

  // ============================================================================
  // Batch Actions
  // ============================================================================

  /**
   * Approve all pending issues
   */
  async approveAll(): Promise<{ count: number; success: boolean }> {
    const result = await this.callSprintBot("approve_all", {});
    if (result.success) {
      const count = result.data?.approved_count || 0;
      this.notifications.info(`Approved ${count} issues`);
      this.refreshUI();
      return { count, success: true };
    } else {
      this.notifications.error(`Failed to approve all: ${result.error}`);
      return { count: 0, success: false };
    }
  }

  /**
   * Reject all pending issues
   */
  async rejectAll(): Promise<{ count: number; success: boolean }> {
    const result = await this.callSprintBot("reject_all", {});
    if (result.success) {
      const count = result.data?.rejected_count || 0;
      this.notifications.info(`Unapproved ${count} issues`);
      this.refreshUI();
      return { count, success: true };
    } else {
      this.notifications.error(`Failed to unapprove all: ${result.error}`);
      return { count: 0, success: false };
    }
  }

  // ============================================================================
  // Bot Control
  // ============================================================================

  /**
   * Toggle automatic mode (Mon-Fri 9-5)
   */
  async toggleAutomatic(enabled?: boolean): Promise<boolean> {
    const state = await this.getState();
    const currentAutomatic = state?.automaticMode ?? false;
    const targetEnabled = enabled ?? !currentAutomatic;
    const method = targetEnabled ? "enable" : "disable";

    const result = await this.callSprintBot(method, {});
    if (result.success) {
      this.notifications.info(
        `Sprint bot automatic mode ${targetEnabled ? "enabled (Mon-Fri 9-5)" : "disabled"}`
      );
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to toggle automatic mode: ${result.error}`);
      return false;
    }
  }

  /**
   * Start the sprint bot manually
   */
  async startBot(): Promise<boolean> {
    const result = await this.callSprintBot("start", {});
    if (result.success) {
      this.notifications.info("Sprint bot started manually - will process approved issues now");
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to start bot: ${result.error}`);
      return false;
    }
  }

  /**
   * Stop the sprint bot
   */
  async stopBot(): Promise<boolean> {
    const result = await this.callSprintBot("stop", {});
    if (result.success) {
      this.notifications.info("Sprint bot stopped");
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to stop bot: ${result.error}`);
      return false;
    }
  }

  /**
   * Toggle background task mode
   */
  async toggleBackgroundTasks(enabled?: boolean): Promise<boolean> {
    const result = await this.callSprintBot("toggle_background", { enabled });
    if (result.success) {
      const mode = result.data?.backgroundTasks ? "enabled" : "disabled";
      this.notifications.info(`Background tasks ${mode}`);
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to toggle background tasks: ${result.error}`);
      return false;
    }
  }

  // ============================================================================
  // Action Dispatcher
  // ============================================================================

  /**
   * Refresh sprint data from Jira
   */
  async refresh(): Promise<boolean> {
    const result = await this.callSprintBot("refresh", {});
    if (result.success) {
      this.notifications.info("Sprint data refreshed from Jira");
      this.refreshUI();
      return true;
    } else {
      this.notifications.error(`Failed to refresh: ${result.error}`);
      return false;
    }
  }

  /**
   * Get issue timeline
   */
  async getIssueTimeline(issueKey: string): Promise<{ timestamp: string; action: string; description: string }[]> {
    const state = await this.getState();
    const issues = (state as any)?.issues || [];
    const issue = issues.find((i: any) => i.key === issueKey);
    return issue?.timeline || [];
  }

  /**
   * Check if background tasks are enabled
   */
  async isBackgroundTasksEnabled(): Promise<boolean> {
    const state = await this.getState();
    return state?.backgroundTasks ?? false;
  }

  /**
   * Handle sprint action by name (for backward compatibility with message handlers)
   * Note: Some actions (openChat, viewTimeline, testChatLauncher) require VSCode UI
   * and should be handled by the caller after calling this method.
   */
  async handleAction(
    action: string,
    issueKey?: string,
    _chatId?: string,
    enabled?: boolean
  ): Promise<{ handled: boolean; action?: string; data?: any }> {
    switch (action) {
      // Issue-level actions
      case "approve":
        if (issueKey) await this.approveIssue(issueKey);
        return { handled: true };
      case "reject":
        if (issueKey) await this.rejectIssue(issueKey);
        return { handled: true };
      case "abort":
        if (issueKey) await this.abortIssue(issueKey);
        return { handled: true };
      case "startIssue":
        if (issueKey) await this.startIssue(issueKey);
        return { handled: true };
      case "openInCursor":
        if (issueKey) await this.openInCursor(issueKey);
        return { handled: true };

      // Batch actions
      case "approveAll":
        await this.approveAll();
        return { handled: true };
      case "rejectAll":
        await this.rejectAll();
        return { handled: true };

      // Bot control actions
      case "toggleAutomatic":
      case "toggleBot":
        await this.toggleAutomatic(enabled);
        return { handled: true };
      case "startBot":
        await this.startBot();
        return { handled: true };
      case "stopBot":
        await this.stopBot();
        return { handled: true };
      case "toggleBackgroundTasks":
        await this.toggleBackgroundTasks(enabled);
        return { handled: true };
      case "refresh":
        await this.refresh();
        return { handled: true };

      // Actions that need VSCode UI handling by caller
      case "openChat":
        return { handled: false, action: "openChat", data: { issueKey } };
      case "viewTimeline":
        if (issueKey) {
          const timeline = await this.getIssueTimeline(issueKey);
          return { handled: false, action: "viewTimeline", data: { issueKey, timeline } };
        }
        return { handled: true };
      case "testChatLauncher":
        const bgTasks = await this.isBackgroundTasksEnabled();
        return { handled: false, action: "testChatLauncher", data: { backgroundTasks: bgTasks } };

      default:
        logger.warn(`Unknown action: ${action}`);
        return { handled: true };
    }
  }
}
