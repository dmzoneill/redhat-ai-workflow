/**
 * Sprint Tab
 *
 * Displays sprint bot status, issues, and controls.
 * 
 * Architecture: Uses SprintService (via this.services.sprint) for business logic.
 * This eliminates duplicate D-Bus calls and keeps business logic in one place.
 */

import { BaseTab, TabConfig, dbus } from "./BaseTab";
import { createLogger } from "../logger";

const logger = createLogger("SprintTab");
import {
  SprintState,
  SprintIssue,
  ToolGapRequest,
  CompletedSprint,
  loadSprintHistory,
  loadToolGapRequests,
  getSprintTabContent,
  getSprintTabScript,
} from "../sprintRenderer";

export class SprintTab extends BaseTab {
  private state: SprintState | null = null;
  private toolGapRequests: ToolGapRequest[] = [];
  private sprintHistory: CompletedSprint[] = [];
  private issueCount = 0;
  private pendingCount = 0;
  private inProgressCount = 0;

  constructor() {
    super({
      id: "sprint",
      label: "Sprint",
      icon: "🎯",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    if (this.inProgressCount > 0) {
      return { text: `${this.inProgressCount}`, class: "running" };
    }
    if (this.pendingCount > 0) {
      return { text: `${this.pendingCount}`, class: "" };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load sprint state via SprintService (preferred) or D-Bus (fallback)
      if (this.services.sprint) {
        logger.log("Using SprintService.getState()...");
        const state = await this.services.sprint.getState();
        if (state) {
          this.state = state as any;
          logger.log(`State loaded via service: ${this.state?.issues?.length || 0} issues`);
          this.updateCounts();
        } else {
          this.lastError = "Sprint state returned null";
          logger.warn(this.lastError);
        }
      } else {
        // Fallback to direct D-Bus if service not injected
        logger.log("Falling back to direct D-Bus call...");
        const result = await dbus.sprint_getState();
        logger.log(`sprint_getState() result: success=${result.success}, error=${result.error || 'none'}`);
        if (result.success && result.data) {
          const data = result.data as any;
          logger.log(`Data keys: ${Object.keys(data).join(', ')}`);
          this.state = data.state || data;
          logger.log(`State loaded: ${this.state?.issues?.length || 0} issues`);
          this.updateCounts();
        } else if (result.error) {
          this.lastError = `Sprint state failed: ${result.error}`;
          logger.warn(this.lastError);
        }
      }

      // Load tool gap requests (still file-based for now)
      this.toolGapRequests = loadToolGapRequests();

      // Load sprint history (still file-based for now)
      this.sprintHistory = loadSprintHistory();
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
      this.state = null;
    }
  }

  private updateCounts(): void {
    if (!this.state) {
      this.issueCount = 0;
      this.pendingCount = 0;
      this.inProgressCount = 0;
      return;
    }

    const issues = this.state.issues || [];
    this.issueCount = issues.length;
    this.pendingCount = issues.filter(
      (i) => i.approvalStatus === "pending"
    ).length;
    this.inProgressCount = issues.filter(
      (i) => i.approvalStatus === "in_progress"
    ).length;
  }

  getContent(): string {
    if (!this.state) {
      return this.getLoadingHtml("Loading sprint data...");
    }
    return getSprintTabContent(this.state, this.sprintHistory, this.toolGapRequests);
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return getSprintTabScript();
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "sprintAction":
        await this.handleSprintAction(message.action, message);
        return true;

      case "refreshSprint":
        await this.refreshSprint();
        return true;

      default:
        return false;
    }
  }

  private async handleSprintAction(
    action: string,
    message: any
  ): Promise<void> {
    const issueKey = message.issueKey;

    // Use SprintService if available (preferred), otherwise fall back to D-Bus
    if (this.services.sprint) {
      logger.log(`Using SprintService for action: ${action}`);
      await this.services.sprint.handleAction(action, issueKey, message.chatId, message.enabled);
    } else {
      // Fallback to direct D-Bus calls
      logger.log(`Falling back to D-Bus for action: ${action}`);
      switch (action) {
        case "approve":
          if (issueKey) await dbus.sprint_approve(issueKey);
          break;
        case "reject":
          if (issueKey) await dbus.sprint_reject(issueKey);
          break;
        case "abort":
          if (issueKey) await dbus.sprint_abort(issueKey);
          break;
        case "start":
          if (issueKey) await dbus.sprint_startIssue(issueKey, message.background || false);
          break;
        case "openInCursor":
          if (issueKey) await dbus.sprint_openInCursor(issueKey);
          break;
        case "approveAll":
          await dbus.sprint_approveAll();
          break;
        case "rejectAll":
          await dbus.sprint_rejectAll();
          break;
        case "enable":
          await dbus.sprint_enable();
          break;
        case "disable":
          await dbus.sprint_disable();
          break;
        case "startBot":
          await dbus.sprint_start();
          break;
        case "stopBot":
          await dbus.sprint_stop();
          break;
        case "toggleBackground":
          await dbus.sprint_toggleBackground(message.enabled);
          break;
      }
    }

    await this.refresh();
  }

  private async refreshSprint(): Promise<void> {
    // Use SprintService if available (preferred), otherwise fall back to D-Bus
    if (this.services.sprint) {
      logger.log("Using SprintService.refresh()");
      await this.services.sprint.refresh();
    } else {
      logger.log("Falling back to D-Bus for refresh");
      const result = await dbus.sprint_refresh();
      if (!result.success) {
        logger.error("Failed to refresh sprint", result.error);
      }
    }
    await this.refresh();
  }
}
