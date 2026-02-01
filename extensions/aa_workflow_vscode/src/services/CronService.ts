/**
 * CronService - Cron Scheduler Business Logic
 *
 * Handles all cron-related operations without direct UI dependencies.
 * Uses MessageBus for UI communication and NotificationService for user feedback.
 */

import * as vscode from "vscode";
import { dbus } from "../dbusClient";
import { StateStore } from "../state";
import { MessageBus } from "./MessageBus";
import { NotificationService } from "./NotificationService";
import { createLogger } from "../logger";

const logger = createLogger("CronService");

// ============================================================================
// Types
// ============================================================================

export interface CronServiceDependencies {
  state: StateStore;
  messages: MessageBus;
  notifications: NotificationService;
}

export interface CronJob {
  name: string;
  description?: string;
  skill: string;
  cron?: string;
  trigger?: string;
  poll_interval?: string;
  condition?: string;
  inputs?: Record<string, any>;
  notify?: string[];
  enabled: boolean;
  persona?: string;
}

export interface CronExecution {
  job_name: string;
  skill: string;
  timestamp: string;
  success: boolean;
  duration_ms?: number;
  error?: string;
  output_preview?: string;
  session_name?: string;
}

export interface CronConfig {
  enabled: boolean;
  timezone: string;
  jobs: CronJob[];
  execution_mode: string;
}

// ============================================================================
// CronService Class
// ============================================================================

export class CronService {
  private state: StateStore;
  private messages: MessageBus;
  private notifications: NotificationService;

  // Cache for synchronous access
  private _cachedConfig: CronConfig | null = null;
  private _cachedHistory: CronExecution[] = [];

  constructor(deps: CronServiceDependencies) {
    this.state = deps.state;
    this.messages = deps.messages;
    this.notifications = deps.notifications;
  }

  // ============================================================================
  // Configuration
  // ============================================================================

  /**
   * Load cron configuration from D-Bus
   */
  async loadConfig(): Promise<CronConfig | null> {
    try {
      // Read all config via D-Bus (uses ConfigManager for thread-safe access)
      const configResult = await dbus.cron_getConfig("schedules");

      const configData = configResult.data as any;
      if (!configResult.success || !configData?.success) {
        logger.log("D-Bus get_config failed, preserving cached cron config");
        return this._cachedConfig;
      }

      const schedules = configData.value || {};

      // Get enabled state from D-Bus (uses StateManager)
      const statsResult = await dbus.cron_getState();

      if (!statsResult.success) {
        logger.log("D-Bus GetStats failed, preserving cached cron config");
        return this._cachedConfig;
      }

      const statsData = statsResult.data as any;
      const enabled = statsData?.state?.enabled || false;

      const config: CronConfig = {
        enabled,
        timezone: schedules.timezone || "UTC",
        jobs: schedules.jobs || [],
        execution_mode: schedules.execution_mode || "claude_cli",
      };

      this._cachedConfig = config;
      return config;
    } catch (e) {
      logger.error("Failed to load cron config via D-Bus", e);
      return this._cachedConfig;
    }
  }

  /**
   * Get cached config (synchronous)
   */
  getConfig(): CronConfig {
    return this._cachedConfig || {
      enabled: false,
      timezone: "UTC",
      jobs: [],
      execution_mode: "claude_cli",
    };
  }

  // ============================================================================
  // History
  // ============================================================================

  /**
   * Load cron execution history from D-Bus
   */
  async loadHistory(limit: number = 10): Promise<CronExecution[]> {
    try {
      const result = await dbus.cron_getHistory(limit);
      if (result.success && result.data) {
        const data = result.data as any;
        const history = data.history || [];
        this._cachedHistory = history;
        return history;
      }
    } catch (e) {
      logger.error("Failed to load cron history via D-Bus", e);
    }
    return this._cachedHistory;
  }

  /**
   * Get cached history (synchronous)
   */
  getHistory(limit: number = 10): CronExecution[] {
    return this._cachedHistory.slice(0, limit);
  }

  // ============================================================================
  // Refresh Data
  // ============================================================================

  /**
   * Refresh all cron data and publish to UI
   */
  async refreshData(historyLimit: number = 10): Promise<void> {
    const [config, history] = await Promise.all([
      this.loadConfig(),
      this.loadHistory(historyLimit),
    ]);

    const configToSend = config || this.getConfig();

    this.messages.publish("cronData", {
      config: configToSend,
      history,
      totalHistory: history.length,
      currentLimit: historyLimit,
    });
  }

  // ============================================================================
  // Scheduler Control
  // ============================================================================

  /**
   * Toggle the scheduler on/off
   */
  async toggleScheduler(): Promise<boolean> {
    try {
      const config = await this.loadConfig();
      const currentState = config?.enabled || false;
      const newState = !currentState;

      logger.log(`Toggling scheduler: ${currentState} -> ${newState}`);

      const result = await dbus.cron_toggleScheduler(newState);

      if (result.success) {
        this.notifications.info(
          `Scheduler ${newState ? "enabled ✅" : "disabled ⏸️"}. ${
            newState ? "Jobs will start running within 30 seconds." : "Jobs are paused."
          }`
        );

        this.messages.publish("schedulerToggled", { enabled: newState });
        await this.refreshData();
        return true;
      } else {
        this.notifications.error(`Failed to toggle scheduler via D-Bus: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to toggle scheduler: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Job Control
  // ============================================================================

  /**
   * Toggle a specific cron job on/off
   */
  async toggleJob(jobName: string, enabled: boolean): Promise<boolean> {
    try {
      logger.log(`Toggling job: ${jobName} -> ${enabled}`);

      const result = await dbus.cron_toggleJob(jobName, enabled);

      if (result.success) {
        this.notifications.info(`Cron job "${jobName}" ${enabled ? "enabled" : "disabled"}`);
        await this.refreshData();
        return true;
      } else {
        this.notifications.error(`Failed to toggle cron job via D-Bus: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to toggle cron job: ${e.message}`);
      return false;
    }
  }

  /**
   * Run a cron job immediately
   * Note: This copies a command to clipboard for the user to paste in Cursor chat
   */
  async runJobNow(jobName: string): Promise<boolean> {
    try {
      const config = await this.loadConfig();
      const job = config?.jobs.find((j) => j.name === jobName);

      if (job) {
        const command = `cron_run_now("${jobName}")`;
        await vscode.env.clipboard.writeText(command);
        this.notifications.info(
          `Command copied to clipboard: ${command}\nPaste in Cursor chat to run.`
        );
        return true;
      } else {
        this.notifications.error(`Job "${jobName}" not found`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to run cron job: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Job Queries
  // ============================================================================

  /**
   * Get a specific job by name
   */
  getJob(jobName: string): CronJob | undefined {
    return this._cachedConfig?.jobs.find((j) => j.name === jobName);
  }

  /**
   * Get all enabled jobs
   */
  getEnabledJobs(): CronJob[] {
    return this._cachedConfig?.jobs.filter((j) => j.enabled) || [];
  }

  /**
   * Get all disabled jobs
   */
  getDisabledJobs(): CronJob[] {
    return this._cachedConfig?.jobs.filter((j) => !j.enabled) || [];
  }
}
