/**
 * Notification Watcher
 *
 * Watches for general notifications from the backend (daemons, tools, skills)
 * and displays them as toast messages in VS Code.
 *
 * The backend writes notifications to:
 *   ~/.config/aa-workflow/notifications.json
 *
 * This file watches that file and shows appropriate toast notifications.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { createLogger } from "./logger";

const logger = createLogger("NotificationWatcher");

// ============================================================================
// File Locking Utilities (same as skillExecutionWatcher.ts)
// ============================================================================

const LOCK_TIMEOUT_MS = 5000;
const LOCK_RETRY_INTERVAL_MS = 50;
const LOCK_STALE_MS = 10000;

async function acquireFileLock(filePath: string): Promise<boolean> {
  const lockPath = filePath + ".lock";
  const startTime = Date.now();

  while (Date.now() - startTime < LOCK_TIMEOUT_MS) {
    try {
      if (fs.existsSync(lockPath)) {
        const stat = fs.statSync(lockPath);
        const lockAge = Date.now() - stat.mtimeMs;
        if (lockAge > LOCK_STALE_MS) {
          try {
            fs.unlinkSync(lockPath);
          } catch {
            // Another process may have removed it
          }
        }
      }

      const fd = fs.openSync(
        lockPath,
        fs.constants.O_CREAT | fs.constants.O_EXCL | fs.constants.O_WRONLY
      );
      fs.writeSync(fd, `${process.pid}\n${Date.now()}`);
      fs.closeSync(fd);
      return true;
    } catch (e: any) {
      if (e.code === "EEXIST") {
        await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_INTERVAL_MS));
      } else {
        logger.error("Error acquiring lock:", e);
        return false;
      }
    }
  }

  logger.warn("Timeout waiting for file lock");
  return false;
}

function releaseFileLock(filePath: string): void {
  const lockPath = filePath + ".lock";
  try {
    fs.unlinkSync(lockPath);
  } catch (e: any) {
    if (e.code !== "ENOENT") {
      logger.error("Error releasing lock:", e);
    }
  }
}

async function withFileLock<T>(filePath: string, fn: () => T): Promise<T | null> {
  const acquired = await acquireFileLock(filePath);
  if (!acquired) {
    logger.error("Failed to acquire file lock, skipping operation");
    return null;
  }

  try {
    return fn();
  } finally {
    releaseFileLock(filePath);
  }
}

// ============================================================================
// Types
// ============================================================================

export type NotificationLevel = "info" | "warning" | "error";
export type NotificationCategory =
  | "skill"
  | "persona"
  | "session"
  | "cron"
  | "meet"
  | "sprint"
  | "slack"
  | "auto_heal"
  | "git"
  | "jira"
  | "gitlab"
  | "memory"
  | "daemon";

export interface NotificationAction {
  label: string;
  command: string;
}

export interface Notification {
  id: string;
  category: NotificationCategory;
  eventType: string;
  title: string;
  message: string;
  level: NotificationLevel;
  timestamp: string;
  actions: NotificationAction[];
  data: Record<string, any>;
  source?: string;
  read: boolean;
}

export interface NotificationFile {
  notifications: Notification[];
  lastUpdated: string;
  version: number;
}

// ============================================================================
// Notification Watcher
// ============================================================================

export class NotificationWatcher {
  private _watcher: fs.FSWatcher | undefined;
  private _notificationFilePath: string;
  private _lastModified: number = 0;
  private _disposables: vscode.Disposable[] = [];
  private _seenNotificationIds: Set<string> = new Set();
  private _enabled: boolean = true;

  // Category-specific enable flags (from settings)
  private _categorySettings: Record<NotificationCategory, boolean> = {
    skill: true,
    persona: true,
    session: true,
    cron: true,
    meet: true,
    sprint: true,
    slack: true,
    auto_heal: true,
    git: true,
    jira: true,
    gitlab: true,
    memory: false, // Off by default (can be noisy)
    daemon: true,
  };

  constructor() {
    this._notificationFilePath = path.join(
      os.homedir(),
      ".config",
      "aa-workflow",
      "notifications.json"
    );

    // Load settings
    this._loadSettings();

    // Listen for settings changes
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("aa-workflow.notifications")) {
        this._loadSettings();
      }
    });
  }

  /**
   * Load notification settings from VS Code configuration
   */
  private _loadSettings(): void {
    const config = vscode.workspace.getConfiguration("aa-workflow.notifications");

    this._enabled = config.get<boolean>("enabled", true);

    // Load category-specific settings
    for (const category of Object.keys(this._categorySettings) as NotificationCategory[]) {
      this._categorySettings[category] = config.get<boolean>(category, this._categorySettings[category]);
    }

    logger.info(`Notification settings loaded: enabled=${this._enabled}`);
  }

  /**
   * Start watching for notifications
   */
  public start(): void {
    // Ensure directory exists
    const dir = path.dirname(this._notificationFilePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }

    // Watch the notification file
    try {
      this._watcher = fs.watch(
        dir,
        { persistent: false },
        (eventType, filename) => {
          if (filename === "notifications.json") {
            this._onFileChange();
          }
        }
      );
    } catch (e) {
      logger.error("Failed to start notification watcher:", e);
      // Fallback to polling
      this._startPolling();
    }

    // Initial check
    this._onFileChange();
  }

  /**
   * Fallback polling for systems where fs.watch doesn't work well
   */
  private _startPolling(): void {
    const pollInterval = setInterval(() => {
      this._onFileChange();
    }, 1000); // Check every second

    this._disposables.push({
      dispose: () => clearInterval(pollInterval),
    });
  }

  /**
   * Handle file change event
   */
  private async _onFileChange(): Promise<void> {
    if (!this._enabled) {
      return;
    }

    try {
      if (!fs.existsSync(this._notificationFilePath)) {
        return;
      }

      const stat = fs.statSync(this._notificationFilePath);
      if (stat.mtimeMs <= this._lastModified) {
        return; // No change
      }
      this._lastModified = stat.mtimeMs;

      // Read with lock
      const data = await withFileLock(this._notificationFilePath, () => {
        const content = fs.readFileSync(this._notificationFilePath, "utf-8");
        return JSON.parse(content) as NotificationFile;
      });

      if (!data) {
        return;
      }

      // Process new notifications
      for (const notification of data.notifications) {
        if (!this._seenNotificationIds.has(notification.id)) {
          this._seenNotificationIds.add(notification.id);
          this._showNotification(notification);
        }
      }

      // Clean up old seen IDs (keep last 100)
      if (this._seenNotificationIds.size > 100) {
        const ids = Array.from(this._seenNotificationIds);
        this._seenNotificationIds = new Set(ids.slice(-100));
      }
    } catch (e) {
      logger.error("Error processing notification file:", e);
    }
  }

  /**
   * Show a notification as a VS Code toast
   */
  private _showNotification(notification: Notification): void {
    // Check if this category is enabled
    if (!this._categorySettings[notification.category]) {
      logger.debug(`Skipping notification for disabled category: ${notification.category}`);
      return;
    }

    // Build action buttons
    const actions = notification.actions.map((a) => a.label);

    // Show appropriate toast type based on level
    let promise: Thenable<string | undefined>;

    switch (notification.level) {
      case "error":
        promise = vscode.window.showErrorMessage(
          `${notification.title}: ${notification.message}`,
          ...actions
        );
        break;
      case "warning":
        promise = vscode.window.showWarningMessage(
          `${notification.title}: ${notification.message}`,
          ...actions
        );
        break;
      case "info":
      default:
        promise = vscode.window.showInformationMessage(
          `${notification.title}: ${notification.message}`,
          ...actions
        );
        break;
    }

    // Handle action button clicks
    promise.then((selected) => {
      if (selected) {
        const action = notification.actions.find((a) => a.label === selected);
        if (action && action.command) {
          vscode.commands.executeCommand(action.command, notification.data);
        }
      }
    });

    logger.info(
      `Showed notification: [${notification.level}] ${notification.category}/${notification.eventType}: ${notification.title}`
    );
  }

  /**
   * Stop watching
   */
  public stop(): void {
    if (this._watcher) {
      this._watcher.close();
      this._watcher = undefined;
    }

    for (const disposable of this._disposables) {
      disposable.dispose();
    }
    this._disposables = [];
  }

  /**
   * Dispose
   */
  public dispose(): void {
    this.stop();
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let _instance: NotificationWatcher | undefined;

export function getNotificationWatcher(): NotificationWatcher {
  if (!_instance) {
    _instance = new NotificationWatcher();
  }
  return _instance;
}

export function startNotificationWatcher(): void {
  getNotificationWatcher().start();
}

export function stopNotificationWatcher(): void {
  if (_instance) {
    _instance.stop();
  }
}
