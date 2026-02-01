/**
 * NotificationService - Centralized User Notifications
 *
 * A notification service that:
 * - Provides a consistent API for showing notifications
 * - Can be disabled for testing
 * - Keeps history of notifications
 * - Supports notification preferences
 *
 * This replaces the 185+ scattered vscode.window.show* calls.
 */

import * as vscode from "vscode";
import { createLogger } from "../logger";

const logger = createLogger("NotificationService");

// ============================================================================
// Types
// ============================================================================

export enum NotificationType {
  INFO = "info",
  WARNING = "warning",
  ERROR = "error",
}

export interface Notification {
  type: NotificationType;
  message: string;
  actions?: string[];
  timestamp: string;
  selectedAction?: string;
}

export interface NotificationOptions {
  /** Actions to show as buttons */
  actions?: string[];
  /** Whether to log to output channel */
  log?: boolean;
  /** Whether to suppress the notification (still recorded in history) */
  silent?: boolean;
}

export interface NotificationServiceOptions {
  /** Enable/disable all notifications */
  enabled?: boolean;
  /** Maximum history size */
  maxHistory?: number;
  /** Output channel for logging */
  outputChannel?: vscode.OutputChannel;
}

// ============================================================================
// NotificationService Class
// ============================================================================

export class NotificationService {
  private enabled: boolean;
  private history: Notification[] = [];
  private maxHistory: number;
  private outputChannel: vscode.OutputChannel | null;
  private listeners: Set<(notification: Notification) => void> = new Set();
  private suppressedTypes: Set<NotificationType> = new Set();

  constructor(options: NotificationServiceOptions = {}) {
    this.enabled = options.enabled ?? true;
    this.maxHistory = options.maxHistory ?? 100;
    this.outputChannel = options.outputChannel ?? null;
  }

  // ============================================================================
  // Core Notification Methods
  // ============================================================================

  /**
   * Show an information notification
   */
  info(message: string, options?: NotificationOptions): Promise<string | undefined> {
    return this.notify(NotificationType.INFO, message, options);
  }

  /**
   * Show a warning notification
   */
  warning(message: string, options?: NotificationOptions): Promise<string | undefined> {
    return this.notify(NotificationType.WARNING, message, options);
  }

  /**
   * Show an error notification
   */
  error(message: string, options?: NotificationOptions): Promise<string | undefined> {
    return this.notify(NotificationType.ERROR, message, options);
  }

  /**
   * Show a notification of any type
   */
  async notify(
    type: NotificationType,
    message: string,
    options: NotificationOptions = {}
  ): Promise<string | undefined> {
    const notification: Notification = {
      type,
      message,
      actions: options.actions,
      timestamp: new Date().toISOString(),
    };

    // Record in history
    this.recordHistory(notification);

    // Notify listeners
    this.notifyListeners(notification);

    // Log to output channel if requested
    if (options.log && this.outputChannel) {
      this.outputChannel.appendLine(`[${type.toUpperCase()}] ${message}`);
    }

    // Check if we should actually show the notification
    if (!this.enabled || options.silent || this.suppressedTypes.has(type)) {
      return undefined;
    }

    // Show the notification
    let result: string | undefined;
    const actions = options.actions || [];

    switch (type) {
      case NotificationType.INFO:
        result = await vscode.window.showInformationMessage(message, ...actions);
        break;
      case NotificationType.WARNING:
        result = await vscode.window.showWarningMessage(message, ...actions);
        break;
      case NotificationType.ERROR:
        result = await vscode.window.showErrorMessage(message, ...actions);
        break;
    }

    // Record selected action
    if (result) {
      notification.selectedAction = result;
    }

    return result;
  }

  // ============================================================================
  // Convenience Methods
  // ============================================================================

  /**
   * Show a success notification (info with checkmark)
   */
  success(message: string, options?: NotificationOptions): Promise<string | undefined> {
    return this.info(`✅ ${message}`, options);
  }

  /**
   * Show a failure notification (error with X)
   */
  failure(message: string, options?: NotificationOptions): Promise<string | undefined> {
    return this.error(`❌ ${message}`, options);
  }

  /**
   * Show a progress notification (info with spinner emoji)
   */
  progress(message: string, options?: NotificationOptions): Promise<string | undefined> {
    return this.info(`⏳ ${message}`, options);
  }

  /**
   * Show a notification with Yes/No actions
   */
  async confirm(message: string): Promise<boolean> {
    const result = await this.notify(NotificationType.WARNING, message, {
      actions: ["Yes", "No"],
    });
    return result === "Yes";
  }

  // ============================================================================
  // Configuration
  // ============================================================================

  /**
   * Enable all notifications
   */
  enable(): void {
    this.enabled = true;
  }

  /**
   * Disable all notifications (still recorded in history)
   */
  disable(): void {
    this.enabled = false;
  }

  /**
   * Check if notifications are enabled
   */
  isEnabled(): boolean {
    return this.enabled;
  }

  /**
   * Suppress a specific notification type
   */
  suppress(type: NotificationType): void {
    this.suppressedTypes.add(type);
  }

  /**
   * Unsuppress a specific notification type
   */
  unsuppress(type: NotificationType): void {
    this.suppressedTypes.delete(type);
  }

  /**
   * Set the output channel for logging
   */
  setOutputChannel(channel: vscode.OutputChannel): void {
    this.outputChannel = channel;
  }

  // ============================================================================
  // History & Listeners
  // ============================================================================

  /**
   * Get notification history
   */
  getHistory(): Notification[] {
    return [...this.history];
  }

  /**
   * Get history filtered by type
   */
  getHistoryByType(type: NotificationType): Notification[] {
    return this.history.filter(n => n.type === type);
  }

  /**
   * Clear notification history
   */
  clearHistory(): void {
    this.history = [];
  }

  /**
   * Subscribe to notifications
   * Returns an unsubscribe function
   */
  onNotification(handler: (notification: Notification) => void): () => void {
    this.listeners.add(handler);
    return () => this.listeners.delete(handler);
  }

  /**
   * Get count of notifications by type
   */
  getCount(type?: NotificationType): number {
    if (type) {
      return this.history.filter(n => n.type === type).length;
    }
    return this.history.length;
  }

  // ============================================================================
  // Internal Methods
  // ============================================================================

  private recordHistory(notification: Notification): void {
    this.history.push(notification);

    // Trim history if needed
    if (this.history.length > this.maxHistory) {
      this.history = this.history.slice(-this.maxHistory);
    }
  }

  private notifyListeners(notification: Notification): void {
    for (const listener of this.listeners) {
      try {
        listener(notification);
      } catch (e) {
        logger.error("Listener error", e);
      }
    }
  }

  // ============================================================================
  // Cleanup
  // ============================================================================

  /**
   * Dispose of the notification service
   */
  dispose(): void {
    this.listeners.clear();
    this.history = [];
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let notificationServiceInstance: NotificationService | null = null;

export function getNotificationService(): NotificationService {
  if (!notificationServiceInstance) {
    notificationServiceInstance = new NotificationService();
  }
  return notificationServiceInstance;
}

export function resetNotificationService(): void {
  if (notificationServiceInstance) {
    notificationServiceInstance.dispose();
  }
  notificationServiceInstance = null;
}
