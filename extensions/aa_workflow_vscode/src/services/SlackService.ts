/**
 * SlackService - Slack Integration Business Logic
 *
 * Handles all Slack-related operations without direct UI dependencies.
 * Uses MessageBus for UI communication and NotificationService for user feedback.
 */

import { dbus } from "../dbusClient";
import { StateStore } from "../state";
import { MessageBus } from "./MessageBus";
import { NotificationService } from "./NotificationService";
import { createLogger } from "../logger";

const logger = createLogger("SlackService");

// ============================================================================
// Types
// ============================================================================

export interface SlackServiceDependencies {
  state: StateStore;
  messages: MessageBus;
  notifications: NotificationService;
}

export interface SlackMessage {
  id: string;
  channel: string;
  text: string;
  user?: string;
  timestamp?: string;
  thread_ts?: string;
}

export interface SlackChannel {
  id: string;
  name: string;
  is_member?: boolean;
  is_private?: boolean;
}

export interface SlackUser {
  id: string;
  name: string;
  real_name?: string;
  display_name?: string;
}

export interface SlackPendingMessage {
  id: string;
  channel: string;
  text: string;
  created_at: string;
}

export interface SlackCacheStats {
  channels_cached?: number;
  users_cached?: number;
  last_refresh?: string;
}

export interface SlackSearchResult {
  messages: SlackMessage[];
  total: number;
  remaining?: number;
  rateLimited?: boolean;
  error?: string;
}

// ============================================================================
// SlackService Class
// ============================================================================

export class SlackService {
  private state: StateStore;
  private messages: MessageBus;
  private notifications: NotificationService;

  constructor(deps: SlackServiceDependencies) {
    this.state = deps.state;
    this.messages = deps.messages;
    this.notifications = deps.notifications;
  }

  // ============================================================================
  // Message History
  // ============================================================================

  /**
   * Load message history
   */
  async loadHistory(limit: number = 50): Promise<SlackMessage[]> {
    try {
      const result = await dbus.slack_getHistory(limit);

      if (result.success && result.data) {
        const data = result.data as any;
        const messages = Array.isArray(data) ? data : (data.messages || []);
        this.messages.publish("slackHistory", { messages });
        return messages;
      } else {
        this.messages.publish("slackHistory", { messages: [] });
        return [];
      }
    } catch (e) {
      this.messages.publish("slackHistory", { messages: [] });
      return [];
    }
  }

  // ============================================================================
  // Sending Messages
  // ============================================================================

  /**
   * Send a message to a channel or user
   */
  async sendMessage(channel: string, text: string, threadTs: string = ""): Promise<boolean> {
    if (!channel || !text) {
      this.notifications.warning("Please select a channel/user and enter a message");
      return false;
    }

    try {
      const result = await dbus.slack_sendMessage(channel, text, threadTs);

      if (result.success) {
        const replyMsg = threadTs ? "Reply sent successfully" : "Message sent successfully";
        this.notifications.info(replyMsg);
        this.messages.publish("slackMessageSent", {
          success: true,
          isReply: !!threadTs,
        });
        // Refresh history to show the new message
        await this.loadHistory();
        return true;
      } else {
        this.notifications.error(`Failed to send message: ${result.error || "Unknown error"}`);
        this.messages.publish("slackMessageSent", {
          success: false,
          error: result.error,
        });
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to send message: ${e.message}`);
      this.messages.publish("slackMessageSent", {
        success: false,
        error: e.message,
      });
      return false;
    }
  }

  // ============================================================================
  // Channels
  // ============================================================================

  /**
   * Get channels the user is a member of
   */
  async getMyChannels(): Promise<SlackChannel[]> {
    try {
      const result = await dbus.slack_getMyChannels();

      if (result.success && result.data) {
        const data = result.data as any;
        const channels = Array.isArray(data) ? data : (data.channels || []);
        this.messages.publish("slackChannels", { channels });
        return channels;
      } else {
        this.messages.publish("slackChannels", { channels: [] });
        return [];
      }
    } catch (e) {
      this.messages.publish("slackChannels", { channels: [] });
      return [];
    }
  }

  /**
   * Search/browse channels from cache
   */
  async findChannel(query: string): Promise<{ channels: SlackChannel[]; count: number }> {
    try {
      const result = await dbus.slack_findChannel(query);
      if (result.success && result.data) {
        const data = result.data as any;
        const response = {
          channels: data.channels || [],
          count: data.count || 0,
        };
        this.messages.publish("slackChannelBrowser", response);
        return response;
      }
      return { channels: [], count: 0 };
    } catch (e) {
      logger.error("Failed to load channel browser", e);
      return { channels: [], count: 0 };
    }
  }

  // ============================================================================
  // Users
  // ============================================================================

  /**
   * Search users (via API, not just cache)
   */
  async searchUsers(query: string): Promise<SlackUser[]> {
    try {
      const result = await dbus.slack_searchUsers(query);

      if (result.success && result.data) {
        const data = result.data as any;
        const users = data.results || data.users || [];
        this.messages.publish("slackUsers", { users });
        return users;
      } else {
        this.messages.publish("slackUsers", { users: [] });
        return [];
      }
    } catch (e) {
      this.messages.publish("slackUsers", { users: [] });
      return [];
    }
  }

  /**
   * Search/browse users from cache
   */
  async findUser(query: string): Promise<{ users: SlackUser[]; count: number }> {
    try {
      const result = await dbus.slack_findUser(query);
      if (result.success && result.data) {
        const data = result.data as any;
        const response = {
          users: data.users || [],
          count: data.count || 0,
        };
        this.messages.publish("slackUserBrowser", response);
        return response;
      }
      return { users: [], count: 0 };
    } catch (e) {
      logger.error("Failed to load user browser", e);
      return { users: [], count: 0 };
    }
  }

  // ============================================================================
  // Message Search
  // ============================================================================

  /**
   * Search messages
   */
  async searchMessages(query: string, limit: number = 30): Promise<SlackSearchResult> {
    try {
      const result = await dbus.slack_searchMessages(query, limit);
      if (result.success && result.data) {
        const data = result.data as any;
        const response: SlackSearchResult = {
          messages: data.messages || [],
          total: data.total || 0,
          remaining: data.searches_remaining_today,
          rateLimited: data.rate_limited || false,
          error: data.error || undefined,
        };
        this.messages.publish("slackSearchResults", {
          results: response.messages,
          total: response.total,
          remaining: response.remaining,
          rateLimited: response.rateLimited,
          error: response.error,
        });
        return response;
      } else {
        const data = result.data as any;
        const response: SlackSearchResult = {
          messages: [],
          total: 0,
          error: data?.error || "Search failed",
        };
        this.messages.publish("slackSearchResults", {
          results: [],
          error: response.error,
        });
        return response;
      }
    } catch (e: any) {
      const response: SlackSearchResult = {
        messages: [],
        total: 0,
        error: e.message,
      };
      this.messages.publish("slackSearchResults", {
        results: [],
        error: e.message,
      });
      return response;
    }
  }

  // ============================================================================
  // Pending Messages (Approval Queue)
  // ============================================================================

  /**
   * Get pending messages awaiting approval
   */
  async getPending(): Promise<SlackPendingMessage[]> {
    try {
      const result = await dbus.slack_getPending();
      if (result.success) {
        const pending = Array.isArray(result.data) ? result.data : [];
        this.messages.publish("slackPending", { pending });
        return pending as SlackPendingMessage[];
      }
      return [];
    } catch (e) {
      logger.error("Failed to refresh Slack pending", e);
      return [];
    }
  }

  /**
   * Approve a pending message
   */
  async approveMessage(messageId: string): Promise<boolean> {
    try {
      const result = await dbus.slack_approveMessage(messageId);
      if (result.success) {
        this.notifications.info("Message approved and sent");
        await this.getPending();
        return true;
      } else {
        const data = result.data as any;
        this.notifications.error(`Failed to approve: ${data?.error || "Unknown error"}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to approve: ${e.message}`);
      return false;
    }
  }

  /**
   * Reject a pending message
   */
  async rejectMessage(messageId: string): Promise<boolean> {
    try {
      const result = await dbus.slack_rejectMessage(messageId);
      if (result.success) {
        this.notifications.info("Message rejected");
        await this.getPending();
        return true;
      } else {
        const data = result.data as any;
        this.notifications.error(`Failed to reject: ${data?.error || "Unknown error"}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to reject: ${e.message}`);
      return false;
    }
  }

  /**
   * Approve all pending messages
   */
  async approveAll(): Promise<{ approved: number; failed: number }> {
    try {
      const result = await dbus.slack_approveAll();
      if (result.success && result.data) {
        const data = result.data as any;
        const approved = data.approved || 0;
        const failed = data.failed || 0;
        this.notifications.info(
          `Approved ${approved} messages${failed > 0 ? `, ${failed} failed` : ""}`
        );
        await this.getPending();
        return { approved, failed };
      }
      return { approved: 0, failed: 0 };
    } catch (e: any) {
      this.notifications.error(`Failed to approve all: ${e.message}`);
      return { approved: 0, failed: 0 };
    }
  }

  // ============================================================================
  // Cache Management
  // ============================================================================

  /**
   * Refresh the Slack cache from API
   */
  async refreshCache(): Promise<{ channels: number; users: number }> {
    this.notifications.info("Refreshing Slack cache from API...");

    try {
      const [channelResult, userResult] = await Promise.all([
        dbus.slack_refreshChannelCache(),
        dbus.slack_refreshUserCache(),
      ]);

      const channelData = channelResult.data as any;
      const userData = userResult.data as any;
      const channelCount = channelData?.channels_cached || 0;
      const userCount = userData?.users_cached || 0;
      const userSkipped = userData?.skipped ? " (cached)" : "";

      this.notifications.info(
        `Cache refreshed: ${channelCount} channels, ${userCount} users${userSkipped}`
      );

      // Refresh the UI
      await this.getCacheStats();
      await this.findChannel("");
      await this.findUser("");

      return { channels: channelCount, users: userCount };
    } catch (e: any) {
      this.notifications.error(`Failed to refresh cache: ${e.message}`);
      return { channels: 0, users: 0 };
    }
  }

  /**
   * Get cache statistics
   */
  async getCacheStats(): Promise<{ channelStats: SlackCacheStats; userStats: SlackCacheStats }> {
    try {
      const [channelStats, userStats] = await Promise.all([
        dbus.slack_getChannelCacheStats(),
        dbus.slack_getUserCacheStats(),
      ]);

      const response = {
        channelStats: (channelStats.data || {}) as SlackCacheStats,
        userStats: (userStats.data || {}) as SlackCacheStats,
      };

      this.messages.publish("slackCacheStats", response);
      return response;
    } catch (e) {
      logger.error("Failed to refresh cache stats", e);
      return { channelStats: {}, userStats: {} };
    }
  }

  // ============================================================================
  // Commands
  // ============================================================================

  /**
   * Get available Slack commands
   */
  async getCommands(): Promise<any[]> {
    try {
      const result = await dbus.slack_getCommandList();
      if (result.success && result.data) {
        const data = result.data as any;
        const commands = data.commands || [];
        this.messages.publish("slackCommands", { commands });
        return commands;
      }
      return [];
    } catch (e) {
      logger.error("Failed to load Slack commands", e);
      return [];
    }
  }

  /**
   * Send a command via Slack
   */
  async sendCommand(command: string, args: Record<string, string>): Promise<boolean> {
    try {
      // Build the @me command string
      let commandStr = `@me ${command}`;
      for (const [key, value] of Object.entries(args)) {
        if (value) {
          commandStr += ` --${key}="${value}"`;
        }
      }

      // Send via D-Bus (empty channel = self-DM)
      const result = await dbus.slack_sendMessage("", commandStr);

      if (result.success) {
        this.notifications.info(`Command sent: ${command}`);
        this.messages.publish("slackCommandSent", {
          success: true,
          command,
        });
        return true;
      } else {
        this.notifications.error(`Failed to send command: ${result.error || "Unknown error"}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to send command: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Configuration
  // ============================================================================

  /**
   * Get Slack configuration
   */
  async getConfig(): Promise<Record<string, any>> {
    try {
      const result = await dbus.slack_getConfig();
      if (result.success && result.data) {
        const data = result.data as any;
        const config = data.config || {};
        this.messages.publish("slackConfig", { config });
        return config;
      }
      return {};
    } catch (e) {
      logger.error("Failed to load Slack config", e);
      return {};
    }
  }

  /**
   * Set debug mode
   */
  async setDebugMode(enabled: boolean): Promise<boolean> {
    try {
      const result = await dbus.slack_setDebugMode(enabled);
      if (result.success) {
        this.notifications.info(`Debug mode ${enabled ? "enabled" : "disabled"}`);
        this.messages.publish("slackDebugModeChanged", { enabled });
        return true;
      } else {
        this.notifications.error(`Failed to set debug mode: ${result.error || "Unknown error"}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to set debug mode: ${e.message}`);
      return false;
    }
  }
}
