/**
 * Slack Tab
 *
 * Displays Slack bot status, channels, pending messages, and history.
 * Uses D-Bus to communicate with the Slack daemon.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus } from "./BaseTab";
import { createLogger } from "../logger";

const logger = createLogger("SlackTab");

interface SlackChannel {
  channel_id: string;  // D-Bus uses channel_id, not id
  name: string;
  display_name?: string;
  is_private: boolean;
  is_member: boolean;
  num_members?: number;
  purpose?: string;
  topic?: string;
}

interface SlackMessage {
  id: string;
  channel_id: string;
  channel_name: string;
  user_id: string;
  user_name: string;
  text: string;
  timestamp: string;
  thread_ts?: string;
  status: "pending" | "approved" | "rejected" | "sent" | "skipped";
  response?: string;
  intent?: string;
  classification?: string;
  created_at?: number;
  processed_at?: number;
}

interface SlackStatus {
  connected: boolean;
  bot_user_id?: string;
  team_name?: string;
  channels_count: number;
  pending_count: number;
  processed_today: number;
  last_message_at?: string;
  uptime_seconds?: number;
  polls?: number;
  errors?: number;
  messages_seen?: number;
}

interface CacheStats {
  channels_cached?: number;
  member_channels?: number;
  users_cached?: number;
  users_with_avatar?: number;
  last_refresh?: string;
}

interface SyncStatus {
  running: boolean;
  current_task?: string;
  progress?: number;
  channels_synced?: number;
  users_synced?: number;
  errors?: number;
}

interface SlackUser {
  user_id: string;
  name: string;
  real_name?: string;
  display_name?: string;
  email?: string;
  avatar_hash?: string;
}

interface SlackDM {
  channel_id: string;
  name: string;
  display_name?: string;
  type: string;
}

interface SlackCommand {
  name: string;
  description: string;
  usage?: string;
}

interface ThreadReply {
  user: string;
  user_name?: string;
  text: string;
  ts: string;
}

export class SlackTab extends BaseTab {
  private status: SlackStatus | null = null;
  private channels: SlackChannel[] = [];
  private pendingMessages: SlackMessage[] = [];
  private history: SlackMessage[] = [];
  private selectedChannel: string | null = null;
  private historyLimit = 20;
  private cacheStats: CacheStats | null = null;
  private syncStatus: SyncStatus | null = null;
  private searchQuery = "";
  private searchResults: SlackMessage[] = [];
  private showAdvanced = false;
  private dms: SlackDM[] = [];
  private commands: SlackCommand[] = [];
  private userSearchQuery = "";
  private userSearchResults: SlackUser[] = [];
  private threadView: { channelId: string; threadTs: string; replies: ThreadReply[] } | null = null;

  constructor() {
    super({
      id: "slack",
      label: "Slack",
      icon: "💬",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    if (this.pendingMessages.length > 0) {
      return { text: `${this.pendingMessages.length}`, class: "warning" };
    }
    if (this.status?.connected) {
      return { text: "●", class: "status-green" };
    }
    return { text: "○", class: "status-red" };
  }

  async loadData(): Promise<void> {
    try {
      // Load all data in parallel for faster loading
      const [statusResult, pendingResult, channelsResult, historyResult, channelCacheResult, userCacheResult, syncResult, dmsResult, commandsResult] = await Promise.all([
        dbus.slack_getStatus(),
        dbus.slack_getPending(),
        dbus.slack_getMyChannels(),
        dbus.slack_getHistory(this.historyLimit),
        dbus.slack_getChannelCacheStats(),
        dbus.slack_getUserCacheStats(),
        dbus.slack_getSyncStatus(),
        dbus.slack_getSidebarDMs(),
        dbus.slack_getCommandList(),
      ]);

      // Parse pending messages - D-Bus returns array directly
      if (pendingResult.success && pendingResult.data) {
        const data = pendingResult.data as any;
        // Handle both array and object with messages property
        this.pendingMessages = Array.isArray(data) ? data : (data.messages || []);
      } else {
        this.pendingMessages = [];
      }

      // Parse channels - D-Bus returns { success, count, channels: [...] }
      if (channelsResult.success && channelsResult.data) {
        const data = channelsResult.data as any;
        this.channels = data.channels || [];
      } else {
        this.channels = [];
      }

      // Parse history - D-Bus returns array directly
      if (historyResult.success && historyResult.data) {
        const data = historyResult.data as any;
        // Handle both array and object with messages property
        this.history = Array.isArray(data) ? data : (data.messages || []);
      } else {
        this.history = [];
      }

      // Parse cache stats
      if (channelCacheResult.success && channelCacheResult.data) {
        const channelData = channelCacheResult.data as any;
        const userData = userCacheResult.success ? userCacheResult.data as any : {};
        this.cacheStats = {
          channels_cached: channelData.total_channels || channelData.channels_cached || 0,
          member_channels: channelData.member_channels || 0,
          users_cached: userData.total_users || userData.users_cached || 0,
          users_with_avatar: userData.with_avatar || 0,
          last_refresh: channelData.last_refresh || userData.last_refresh,
        };
      }

      // Parse sync status
      if (syncResult.success && syncResult.data) {
        const data = syncResult.data as any;
        this.syncStatus = {
          running: data.running || data.is_running || false,
          current_task: data.current_task,
          progress: data.progress,
          channels_synced: data.channels_synced,
          users_synced: data.users_synced,
          errors: data.errors,
        };
      }

      // Parse DMs
      if (dmsResult.success && dmsResult.data) {
        const data = dmsResult.data as any;
        this.dms = data.dms || [];
      } else {
        this.dms = [];
      }

      // Parse commands
      if (commandsResult.success && commandsResult.data) {
        const data = commandsResult.data as any;
        this.commands = data.commands || [];
      } else {
        this.commands = [];
      }

      // Parse status - D-Bus returns { running, uptime, messages_processed, pending_approvals, ... }
      if (statusResult.success && statusResult.data) {
        const data = statusResult.data as any;
        this.status = {
          // D-Bus returns "running" not "connected"
          connected: data.connected ?? data.running ?? false,
          bot_user_id: data.bot_user_id,
          team_name: data.team_name,
          // Use the actual counts from the loaded data
          channels_count: this.channels.length,
          pending_count: this.pendingMessages.length,
          processed_today: data.messages_processed ?? data.processed_today ?? 0,
          last_message_at: data.last_message_at,
          uptime_seconds: data.uptime_seconds ?? data.uptime,
          polls: data.polls,
          errors: data.errors,
          messages_seen: data.messages_seen,
        };
      } else {
        // Even if status fails, we can still show data if we have it
        this.status = {
          connected: false,
          channels_count: this.channels.length,
          pending_count: this.pendingMessages.length,
          processed_today: 0,
        };
      }
    } catch (error) {
      logger.error("Error loading data", error);
      this.status = null;
    }
  }

  getContent(): string {
    if (!this.status) {
      return this.getLoadingHtml("Loading Slack data...");
    }

    return `
      <!-- Slack Status -->
      <div class="section">
        <div class="section-title">💬 Slack Bot Status</div>
        <div class="grid-4">
          <div class="stat-card ${this.status.connected ? "green" : "red"}">
            <div class="stat-icon">${this.status.connected ? "✓" : "✕"}</div>
            <div class="stat-value">${this.status.connected ? "Connected" : "Offline"}</div>
            <div class="stat-label">Status</div>
          </div>
          <div class="stat-card blue">
            <div class="stat-icon">📢</div>
            <div class="stat-value">${this.status.channels_count}</div>
            <div class="stat-label">Channels</div>
          </div>
          <div class="stat-card ${this.status.pending_count > 0 ? "yellow" : "green"}">
            <div class="stat-icon">⏳</div>
            <div class="stat-value">${this.status.pending_count}</div>
            <div class="stat-label">Pending</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">📊</div>
            <div class="stat-value">${this.status.processed_today}</div>
            <div class="stat-label">Today</div>
          </div>
        </div>
      </div>

      <!-- Slack Controls -->
      <div class="section">
        <div class="slack-controls">
          <button class="btn btn-xs btn-success" data-action="approveAllSlack" ${this.pendingMessages.length === 0 ? "disabled" : ""}>
            ✓ Approve All (${this.pendingMessages.length})
          </button>
          <button class="btn btn-xs" data-action="toggleAdvanced">${this.showAdvanced ? "▼" : "▶"} Advanced</button>
        </div>
      </div>

      <!-- Advanced Controls (collapsible) -->
      ${this.showAdvanced ? this.getAdvancedControlsHtml() : ""}

      <!-- Pending Messages -->
      ${this.pendingMessages.length > 0 ? this.getPendingMessagesHtml() : ""}

      <!-- Message Search -->
      <div class="section">
        <div class="section-title">🔍 Search Messages</div>
        <div class="slack-search-box">
          <input type="text" class="slack-search-input" placeholder="Search Slack messages..."
                 value="${this.escapeHtml(this.searchQuery)}" data-action="searchInput" />
          <button class="btn btn-xs" data-action="searchSlack">Search</button>
        </div>
        ${this.searchResults.length > 0 ? this.getSearchResultsHtml() : ""}
      </div>

      <!-- Thread View (if viewing a thread) -->
      ${this.threadView ? this.getThreadViewHtml() : ""}

      <!-- Direct Messages -->
      ${this.dms.length > 0 ? `
      <div class="section">
        <div class="section-title">💬 Direct Messages (${this.dms.length})</div>
        <div class="slack-dms-grid">
          ${this.dms.map(dm => this.getDMCardHtml(dm)).join("")}
        </div>
      </div>
      ` : ""}

      <!-- Channels -->
      <div class="section">
        <div class="section-title">📢 Channels (${this.channels.length})</div>
        <div class="slack-channels-grid">
          ${this.channels.length > 0 ? this.channels.map((ch) => this.getChannelCardHtml(ch)).join("") : this.getEmptyStateHtml("📢", "No channels found")}
        </div>
      </div>

      <!-- Message History -->
      <div class="section">
        <div class="section-title">📜 Recent Messages (${this.history.length})</div>
        <div class="slack-history-list">
          ${this.history.length > 0 ? this.history.map((msg) => this.getHistoryItemHtml(msg)).join("") : this.getEmptyStateHtml("📜", "No message history")}
        </div>
        ${this.history.length >= this.historyLimit ? `
          <div class="section-actions">
            <button class="btn btn-xs" data-action="loadMoreSlackHistory">Load More</button>
          </div>
        ` : ""}
      </div>
    `;
  }

  private getAdvancedControlsHtml(): string {
    const uptime = this.status?.uptime_seconds
      ? this.formatDuration(this.status.uptime_seconds * 1000)
      : "unknown";

    const syncRunning = this.syncStatus?.running || false;

    return `
      <div class="section slack-advanced">
        <!-- Cache Stats -->
        <div class="slack-subsection">
          <div class="slack-subsection-title">📦 Cache Statistics</div>
          <div class="slack-stats-row">
            <span>Channels cached: <strong>${this.cacheStats?.channels_cached || 0}</strong></span>
            <span>Member channels: <strong>${this.cacheStats?.member_channels || 0}</strong></span>
            <span>Users cached: <strong>${this.cacheStats?.users_cached || 0}</strong></span>
            <span>With avatars: <strong>${this.cacheStats?.users_with_avatar || 0}</strong></span>
          </div>
        </div>

        <!-- Background Sync -->
        <div class="slack-subsection">
          <div class="slack-subsection-title">🔄 Background Sync</div>
          <div class="slack-stats-row">
            <span>Status: <strong class="${syncRunning ? "text-success" : ""}">${syncRunning ? "Running" : "Stopped"}</strong></span>
            ${this.syncStatus?.current_task ? `<span>Task: <strong>${this.escapeHtml(this.syncStatus.current_task)}</strong></span>` : ""}
            ${this.syncStatus?.channels_synced ? `<span>Channels: <strong>${this.syncStatus.channels_synced}</strong></span>` : ""}
            ${this.syncStatus?.users_synced ? `<span>Users: <strong>${this.syncStatus.users_synced}</strong></span>` : ""}
          </div>
          <div class="slack-controls">
            <button class="btn btn-xs ${syncRunning ? "btn-danger" : "btn-success"}" data-action="${syncRunning ? "stopSync" : "startSync"}">
              ${syncRunning ? "⏹ Stop Sync" : "▶ Start Sync"}
            </button>
            <button class="btn btn-xs btn-ghost" data-action="triggerSync" data-sync-type="channels">Sync Channels</button>
            <button class="btn btn-xs btn-ghost" data-action="triggerSync" data-sync-type="users">Sync Users</button>
            <button class="btn btn-xs btn-ghost" data-action="triggerSync" data-sync-type="avatars">Sync Avatars</button>
          </div>
        </div>

        <!-- Daemon Stats -->
        <div class="slack-subsection">
          <div class="slack-subsection-title">🤖 Daemon Statistics</div>
          <div class="slack-stats-row">
            <span>Uptime: <strong>${uptime}</strong></span>
            <span>Polls: <strong>${this.status?.polls || 0}</strong></span>
            <span>Messages seen: <strong>${this.status?.messages_seen || 0}</strong></span>
            <span>Errors: <strong class="${(this.status?.errors || 0) > 0 ? "text-error" : ""}">${this.status?.errors || 0}</strong></span>
          </div>
          <div class="slack-controls">
            <button class="btn btn-xs btn-ghost" data-action="healthCheck">🏥 Health Check</button>
            <button class="btn btn-xs btn-ghost" data-action="toggleDebug">🐛 Toggle Debug</button>
          </div>
        </div>

        <!-- User Search -->
        <div class="slack-subsection">
          <div class="slack-subsection-title">👤 User Search</div>
          <div class="slack-search-box">
            <input type="text" class="slack-search-input" placeholder="Search users by name or email..."
                   value="${this.escapeHtml(this.userSearchQuery)}" data-action="userSearchInput" />
            <button class="btn btn-xs" data-action="searchUsers">Search</button>
          </div>
          ${this.userSearchResults.length > 0 ? this.getUserSearchResultsHtml() : ""}
        </div>

        <!-- Compose Message -->
        <div class="slack-subsection">
          <div class="slack-subsection-title">✉️ Send Message</div>
          <div class="slack-compose">
            <select class="slack-channel-select" data-action="selectChannel">
              <option value="">Select channel...</option>
              ${this.channels.map(ch => `<option value="${ch.channel_id}">#${this.escapeHtml(ch.name)}</option>`).join("")}
              ${this.dms.length > 0 ? `<optgroup label="Direct Messages">
                ${this.dms.map(dm => `<option value="${dm.channel_id}">💬 ${this.escapeHtml(dm.display_name || dm.name)}</option>`).join("")}
              </optgroup>` : ""}
            </select>
            <textarea class="slack-message-input" placeholder="Type your message..." rows="2" data-action="messageInput"></textarea>
            <button class="btn btn-xs btn-primary" data-action="sendMessage">Send</button>
          </div>
        </div>

        <!-- Available Commands -->
        ${this.commands.length > 0 ? `
        <div class="slack-subsection">
          <div class="slack-subsection-title">⚡ Available @me Commands (${this.commands.length})</div>
          <div class="slack-commands-list">
            ${this.commands.slice(0, 10).map(cmd => `
              <div class="slack-command-item">
                <span class="slack-command-name">@me ${this.escapeHtml(cmd.name)}</span>
                <span class="slack-command-desc">${this.escapeHtml(cmd.description || "")}</span>
              </div>
            `).join("")}
            ${this.commands.length > 10 ? `<div class="slack-command-more">...and ${this.commands.length - 10} more</div>` : ""}
          </div>
        </div>
        ` : ""}
      </div>
    `;
  }

  private getUserSearchResultsHtml(): string {
    return `
      <div class="slack-user-results">
        ${this.userSearchResults.map(user => `
          <div class="slack-user-item">
            <div class="slack-user-avatar">👤</div>
            <div class="slack-user-info">
              <div class="slack-user-name">${this.escapeHtml(user.display_name || user.real_name || user.name)}</div>
              <div class="slack-user-handle">@${this.escapeHtml(user.name)}</div>
              ${user.email ? `<div class="slack-user-email">${this.escapeHtml(user.email)}</div>` : ""}
            </div>
            <button class="btn btn-xs" data-action="viewUserProfile" data-user-id="${user.user_id}">View</button>
          </div>
        `).join("")}
      </div>
    `;
  }

  private getSearchResultsHtml(): string {
    return `
      <div class="slack-search-results">
        <div class="slack-search-count">${this.searchResults.length} results</div>
        ${this.searchResults.map(msg => this.getSearchResultItemHtml(msg)).join("")}
      </div>
    `;
  }

  private getSearchResultItemHtml(msg: SlackMessage): string {
    const timeValue = msg.created_at
      ? new Date(msg.created_at * 1000).toISOString()
      : msg.timestamp;

    return `
      <div class="slack-search-item">
        <div class="slack-search-header">
          <span class="slack-search-channel">#${this.escapeHtml(msg.channel_name || "unknown")}</span>
          <span class="slack-search-user">@${this.escapeHtml(msg.user_name || "unknown")}</span>
          <span class="slack-search-time">${this.formatRelativeTime(timeValue)}</span>
        </div>
        <div class="slack-search-text">${this.escapeHtml(msg.text || "")}</div>
      </div>
    `;
  }

  private getThreadViewHtml(): string {
    if (!this.threadView) return "";

    return `
      <div class="section slack-thread-view">
        <div class="section-title">
          💬 Thread View
          <button class="btn btn-xs btn-danger ml-auto" data-action="closeThread">✕ Close</button>
        </div>
        <div class="slack-thread-replies">
          ${this.threadView.replies.length > 0
            ? this.threadView.replies.map(reply => `
              <div class="slack-thread-reply">
                <div class="slack-thread-reply-header">
                  <span class="slack-thread-reply-user">@${this.escapeHtml(reply.user_name || reply.user)}</span>
                  <span class="slack-thread-reply-time">${this.formatRelativeTime(reply.ts)}</span>
                </div>
                <div class="slack-thread-reply-text">${this.escapeHtml(reply.text)}</div>
              </div>
            `).join("")
            : this.getEmptyStateHtml("💬", "No replies in thread")
          }
        </div>
      </div>
    `;
  }

  private getDMCardHtml(dm: SlackDM): string {
    return `
      <div class="slack-dm-card" data-channel-id="${dm.channel_id}">
        <div class="slack-dm-icon">💬</div>
        <div class="slack-dm-info">
          <div class="slack-dm-name">${this.escapeHtml(dm.display_name || dm.name)}</div>
          <div class="slack-dm-type">${dm.type === "im" ? "Direct Message" : "Group DM"}</div>
        </div>
        <button class="btn btn-xs" data-action="openSlackChannel" data-channel="${dm.channel_id}">Open</button>
      </div>
    `;
  }

  private getPendingMessagesHtml(): string {
    return `
      <div class="section">
        <div class="section-title">⏳ Pending Approval (${this.pendingMessages.length})</div>
        <div class="slack-pending-list">
          ${this.pendingMessages.map((msg) => this.getPendingMessageHtml(msg)).join("")}
        </div>
      </div>
    `;
  }

  private getPendingMessageHtml(msg: SlackMessage): string {
    // Format timestamp - use created_at (unix timestamp) if available
    const timeValue = msg.created_at
      ? new Date(msg.created_at * 1000).toISOString()
      : msg.timestamp;

    return `
      <div class="slack-pending-item" data-message-id="${msg.id}">
        <div class="slack-pending-header">
          <div class="slack-pending-channel">#${this.escapeHtml(msg.channel_name || "unknown")}</div>
          <div class="slack-pending-user">@${this.escapeHtml(msg.user_name || "unknown")}</div>
          ${msg.intent ? `<div class="slack-pending-intent">${this.escapeHtml(msg.intent)}</div>` : ""}
          <div class="slack-pending-time">${this.formatRelativeTime(timeValue)}</div>
        </div>
        <div class="slack-pending-text">${this.escapeHtml(msg.text || "")}</div>
        ${msg.response ? `<div class="slack-pending-response">Proposed response: ${this.escapeHtml(msg.response)}</div>` : ""}
        <div class="slack-pending-actions">
          <button class="btn btn-xs btn-success" data-action="approveSlackMessage" data-message-id="${msg.id}">✓ Approve</button>
          <button class="btn btn-xs btn-danger" data-action="rejectSlackMessage" data-message-id="${msg.id}">✕ Reject</button>
          <button class="btn btn-xs" data-action="viewSlackThread" data-channel="${msg.channel_id}" data-thread="${msg.thread_ts || msg.timestamp}">💬 View Thread</button>
        </div>
      </div>
    `;
  }

  private getChannelCardHtml(channel: SlackChannel): string {
    const channelId = channel.channel_id;
    const isSelected = this.selectedChannel === channelId;
    const displayName = channel.display_name || channel.name;

    return `
      <div class="slack-channel-card ${isSelected ? "selected" : ""}" data-channel-id="${channelId}">
        <div class="slack-channel-icon">${channel.is_private ? "🔒" : "#"}</div>
        <div class="slack-channel-info">
          <div class="slack-channel-name">${this.escapeHtml(displayName)}</div>
          ${channel.num_members ? `<div class="slack-channel-members">${channel.num_members} members</div>` : ""}
        </div>
        <button class="btn btn-xs" data-action="openSlackChannel" data-channel="${channelId}">Open</button>
      </div>
    `;
  }

  private getHistoryItemHtml(msg: SlackMessage): string {
    // Map status to icons and classes
    // D-Bus returns: pending, approved, rejected, sent, skipped
    let statusIcon = "○";
    let statusClass = "pending";

    switch (msg.status) {
      case "sent":
        statusIcon = "✓";
        statusClass = "success";
        break;
      case "approved":
        statusIcon = "⏳";
        statusClass = "pending";
        break;
      case "rejected":
      case "skipped":
        statusIcon = "✕";
        statusClass = "failed";
        break;
      case "pending":
      default:
        statusIcon = "○";
        statusClass = "pending";
        break;
    }

    // Format timestamp - use created_at (unix timestamp) if available, otherwise use timestamp string
    const timeValue = msg.created_at
      ? new Date(msg.created_at * 1000).toISOString()
      : msg.timestamp;

    return `
      <div class="slack-history-item ${statusClass}">
        <div class="slack-history-status ${statusClass}">${statusIcon}</div>
        <div class="slack-history-info">
          <div class="slack-history-header">
            <span class="slack-history-channel">#${this.escapeHtml(msg.channel_name || "unknown")}</span>
            <span class="slack-history-user">@${this.escapeHtml(msg.user_name || "unknown")}</span>
            ${msg.intent ? `<span class="slack-history-intent">${this.escapeHtml(msg.intent)}</span>` : ""}
          </div>
          <div class="slack-history-text">${this.escapeHtml(msg.text || "").substring(0, 100)}${(msg.text || "").length > 100 ? "..." : ""}</div>
          ${msg.response ? `<div class="slack-history-response">↳ ${this.escapeHtml(msg.response).substring(0, 80)}${msg.response.length > 80 ? "..." : ""}</div>` : ""}
        </div>
        <div class="slack-history-time">${this.formatRelativeTime(timeValue)}</div>
      </div>
    `;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return `
      // Refresh Slack
      document.querySelectorAll('[data-action="refreshSlack"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'refreshSlack' });
        });
      });

      // Approve all
      document.querySelectorAll('[data-action="approveAllSlack"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'approveAllSlack' });
        });
      });

      // Reload config
      document.querySelectorAll('[data-action="reloadSlackConfig"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'reloadSlackConfig' });
        });
      });

      // Toggle advanced
      document.querySelectorAll('[data-action="toggleAdvanced"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'toggleAdvanced' });
        });
      });

      // Approve single message
      document.querySelectorAll('[data-action="approveSlackMessage"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const messageId = btn.dataset.messageId;
          if (messageId) {
            vscode.postMessage({ command: 'approveSlackMessage', messageId });
          }
        });
      });

      // Reject single message
      document.querySelectorAll('[data-action="rejectSlackMessage"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const messageId = btn.dataset.messageId;
          if (messageId) {
            vscode.postMessage({ command: 'rejectSlackMessage', messageId });
          }
        });
      });

      // Open channel
      document.querySelectorAll('[data-action="openSlackChannel"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const channelId = btn.dataset.channel;
          if (channelId) {
            vscode.postMessage({ command: 'openSlackChannel', channelId });
          }
        });
      });

      // Load more history
      document.querySelectorAll('[data-action="loadMoreSlackHistory"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'loadMoreSlackHistory', limit: 50 });
        });
      });

      // Search messages
      document.querySelectorAll('[data-action="searchSlack"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const input = document.querySelector('[data-action="searchInput"]');
          if (input) {
            vscode.postMessage({ command: 'searchSlack', query: input.value });
          }
        });
      });

      // Search on Enter key
      document.querySelectorAll('[data-action="searchInput"]').forEach(input => {
        input.addEventListener('keypress', (e) => {
          if (e.key === 'Enter') {
            vscode.postMessage({ command: 'searchSlack', query: input.value });
          }
        });
      });

      // Refresh channel cache
      document.querySelectorAll('[data-action="refreshChannelCache"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'refreshChannelCache' });
        });
      });

      // Refresh user cache
      document.querySelectorAll('[data-action="refreshUserCache"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'refreshUserCache' });
        });
      });

      // Health check
      document.querySelectorAll('[data-action="healthCheck"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'healthCheck' });
        });
      });

      // Toggle debug
      document.querySelectorAll('[data-action="toggleDebug"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'toggleDebug' });
        });
      });

      // Send message
      document.querySelectorAll('[data-action="sendMessage"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const channelSelect = document.querySelector('[data-action="selectChannel"]');
          const messageInput = document.querySelector('[data-action="messageInput"]');
          if (channelSelect && messageInput) {
            vscode.postMessage({
              command: 'sendSlackMessage',
              channelId: channelSelect.value,
              text: messageInput.value
            });
          }
        });
      });

      // Start/Stop sync
      document.querySelectorAll('[data-action="startSync"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'startSync' });
        });
      });

      document.querySelectorAll('[data-action="stopSync"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'stopSync' });
        });
      });

      // Trigger specific sync
      document.querySelectorAll('[data-action="triggerSync"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const syncType = btn.dataset.syncType;
          if (syncType) {
            vscode.postMessage({ command: 'triggerSync', syncType });
          }
        });
      });

      // User search
      document.querySelectorAll('[data-action="searchUsers"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const input = document.querySelector('[data-action="userSearchInput"]');
          if (input) {
            vscode.postMessage({ command: 'searchUsers', query: input.value });
          }
        });
      });

      document.querySelectorAll('[data-action="userSearchInput"]').forEach(input => {
        input.addEventListener('keypress', (e) => {
          if (e.key === 'Enter') {
            vscode.postMessage({ command: 'searchUsers', query: input.value });
          }
        });
      });

      // View user profile
      document.querySelectorAll('[data-action="viewUserProfile"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const userId = btn.dataset.userId;
          if (userId) {
            vscode.postMessage({ command: 'viewUserProfile', userId });
          }
        });
      });

      // View thread
      document.querySelectorAll('[data-action="viewSlackThread"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const channelId = btn.dataset.channel;
          const threadTs = btn.dataset.thread;
          if (channelId && threadTs) {
            vscode.postMessage({ command: 'viewThread', channelId, threadTs });
          }
        });
      });

      // Close thread
      document.querySelectorAll('[data-action="closeThread"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'closeThread' });
        });
      });
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "refreshSlack":
        await this.refresh();
        return true;

      case "approveAllSlack":
        await this.approveAll();
        return true;

      case "reloadSlackConfig":
        await this.reloadConfig();
        return true;

      case "toggleAdvanced":
        this.showAdvanced = !this.showAdvanced;
        this.notifyNeedsRender();
        return true;

      case "approveSlackMessage":
        await this.approveMessage(message.messageId);
        return true;

      case "rejectSlackMessage":
        await this.rejectMessage(message.messageId);
        return true;

      case "openSlackChannel":
        await this.openChannel(message.channelId);
        return true;

      case "loadMoreSlackHistory":
        this.historyLimit = message.limit || 50;
        await this.refresh();
        return true;

      case "searchSlack":
        await this.searchMessages(message.query);
        return true;

      case "refreshChannelCache":
        await this.refreshChannelCache();
        return true;

      case "refreshUserCache":
        await this.refreshUserCache();
        return true;

      case "healthCheck":
        await this.healthCheck();
        return true;

      case "toggleDebug":
        await this.toggleDebug();
        return true;

      case "sendSlackMessage":
        await this.sendMessage(message.channelId, message.text);
        return true;

      case "startSync":
        await this.startSync();
        return true;

      case "stopSync":
        await this.stopSync();
        return true;

      case "triggerSync":
        await this.triggerSync(message.syncType);
        return true;

      case "searchUsers":
        await this.searchUsers(message.query);
        return true;

      case "viewUserProfile":
        await this.viewUserProfile(message.userId);
        return true;

      case "viewThread":
        await this.viewThread(message.channelId, message.threadTs);
        return true;

      case "closeThread":
        this.threadView = null;
        this.notifyNeedsRender();
        return true;

      default:
        return false;
    }
  }

  private async approveAll(): Promise<void> {
    const result = await dbus.slack_approveAll();
    if (!result.success) {
      logger.error(`Failed to approve all: ${result.error}`);
    }
    await this.refresh();
  }

  private async reloadConfig(): Promise<void> {
    const result = await dbus.slack_reloadConfig();
    if (!result.success) {
      logger.error(`Failed to reload config: ${result.error}`);
    }
    await this.refresh();
  }

  private async approveMessage(messageId: string): Promise<void> {
    const result = await dbus.slack_approveMessage(messageId);
    if (!result.success) {
      logger.error(`Failed to approve message: ${result.error}`);
    }
    await this.refresh();
  }

  private async rejectMessage(messageId: string): Promise<void> {
    const result = await dbus.slack_rejectMessage(messageId);
    if (!result.success) {
      logger.error(`Failed to reject message: ${result.error}`);
    }
    await this.refresh();
  }

  private async openChannel(channelId: string): Promise<void> {
    this.selectedChannel = channelId;
    // Open Slack in browser
    const channel = this.channels.find((c) => c.channel_id === channelId);
    if (channel) {
      // Use team name if available, otherwise use default redhat-internal
      const teamName = this.status?.team_name || "redhat-internal";
      const url = `https://${teamName}.slack.com/archives/${channelId}`;
      vscode.env.openExternal(vscode.Uri.parse(url));
    }
  }

  private async searchMessages(query: string): Promise<void> {
    if (!query || query.trim().length === 0) {
      this.searchResults = [];
      this.searchQuery = "";
      this.notifyNeedsRender();
      return;
    }

    this.searchQuery = query;
    const result = await dbus.slack_searchMessages(query, 20);
    if (result.success && result.data) {
      const data = result.data as any;
      this.searchResults = data.messages || [];
      if (data.rate_limited) {
        vscode.window.showWarningMessage("Slack search rate limited. Try again later.");
      }
    } else {
      this.searchResults = [];
      logger.error(`Search failed: ${result.error}`);
    }
    this.notifyNeedsRender();
  }

  private async refreshChannelCache(): Promise<void> {
    vscode.window.showInformationMessage("Refreshing channel cache...");
    const result = await dbus.slack_refreshChannelCache();
    if (result.success) {
      const data = result.data as any;
      vscode.window.showInformationMessage(`Cached ${data.channels_cached || 0} channels`);
      await this.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to refresh: ${result.error}`);
    }
  }

  private async refreshUserCache(): Promise<void> {
    vscode.window.showInformationMessage("Refreshing user cache...");
    const result = await dbus.slack_refreshUserCache();
    if (result.success) {
      const data = result.data as any;
      const msg = data.skipped
        ? "User cache is recent, skipped refresh"
        : `Cached ${data.users_cached || 0} users`;
      vscode.window.showInformationMessage(msg);
      await this.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to refresh: ${result.error}`);
    }
  }

  private async healthCheck(): Promise<void> {
    const result = await dbus.slack_healthCheck();
    if (result.success && result.data) {
      const data = result.data as any;
      const status = data.healthy ? "✅ Healthy" : "❌ Unhealthy";
      const details = [
        `Status: ${status}`,
        `Session: ${data.session_active ? "Active" : "Inactive"}`,
        `State DB: ${data.state_db_active ? "Active" : "Inactive"}`,
        `Listener: ${data.listener_active ? "Active" : "Inactive"}`,
      ].join("\n");
      vscode.window.showInformationMessage(details);
    } else {
      vscode.window.showErrorMessage(`Health check failed: ${result.error}`);
    }
  }

  private async toggleDebug(): Promise<void> {
    // Toggle debug mode (we don't track state, so just toggle)
    const result = await dbus.slack_setDebugMode(true);
    if (result.success) {
      vscode.window.showInformationMessage("Debug mode toggled");
    } else {
      vscode.window.showErrorMessage(`Failed to toggle debug: ${result.error}`);
    }
  }

  private async sendMessage(channelId: string, text: string): Promise<void> {
    if (!channelId) {
      vscode.window.showWarningMessage("Please select a channel");
      return;
    }
    if (!text || text.trim().length === 0) {
      vscode.window.showWarningMessage("Please enter a message");
      return;
    }

    const result = await dbus.slack_sendMessage(channelId, text);
    if (result.success) {
      vscode.window.showInformationMessage("Message sent!");
      await this.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to send: ${result.error}`);
    }
  }

  private async startSync(): Promise<void> {
    vscode.window.showInformationMessage("Starting background sync...");
    const result = await dbus.slack_startSync();
    if (result.success) {
      vscode.window.showInformationMessage("Background sync started");
      await this.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to start sync: ${result.error}`);
    }
  }

  private async stopSync(): Promise<void> {
    const result = await dbus.slack_stopSync();
    if (result.success) {
      vscode.window.showInformationMessage("Background sync stopped");
      await this.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to stop sync: ${result.error}`);
    }
  }

  private async triggerSync(syncType: string): Promise<void> {
    vscode.window.showInformationMessage(`Triggering ${syncType} sync...`);
    const result = await dbus.slack_triggerSync(syncType);
    if (result.success) {
      const data = result.data as any;
      vscode.window.showInformationMessage(data.message || `${syncType} sync triggered`);
      await this.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to trigger sync: ${result.error}`);
    }
  }

  private async searchUsers(query: string): Promise<void> {
    if (!query || query.trim().length === 0) {
      this.userSearchResults = [];
      this.userSearchQuery = "";
      this.notifyNeedsRender();
      return;
    }

    this.userSearchQuery = query;
    const result = await dbus.slack_searchUsers(query);
    if (result.success && result.data) {
      const data = result.data as any;
      this.userSearchResults = data.results || data.users || [];
    } else {
      this.userSearchResults = [];
      logger.error(`User search failed: ${result.error}`);
    }
    this.notifyNeedsRender();
  }

  private async viewUserProfile(userId: string): Promise<void> {
    const result = await dbus.slack_getUserProfile(userId);
    if (result.success && result.data) {
      const data = result.data as any;
      const profile = data.profile || data;
      const info = [
        `Name: ${profile.real_name || profile.display_name || "Unknown"}`,
        profile.title ? `Title: ${profile.title}` : null,
        profile.email ? `Email: ${profile.email}` : null,
        profile.phone ? `Phone: ${profile.phone}` : null,
      ].filter(Boolean).join("\n");
      vscode.window.showInformationMessage(info);
    } else {
      vscode.window.showErrorMessage(`Failed to load profile: ${result.error}`);
    }
  }

  private async viewThread(channelId: string, threadTs: string): Promise<void> {
    const result = await dbus.slack_getThreadReplies(channelId, threadTs, 50);
    if (result.success && result.data) {
      const data = result.data as any;
      this.threadView = {
        channelId,
        threadTs,
        replies: data.messages || data.replies || [],
      };
      this.notifyNeedsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to load thread: ${result.error}`);
    }
  }
}
