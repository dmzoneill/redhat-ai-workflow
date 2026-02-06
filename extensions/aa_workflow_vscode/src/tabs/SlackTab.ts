/**
 * Slack Tab
 *
 * Displays Slack bot status, channels, pending messages, and history.
 * 
 * Architecture: Uses SlackService (via this.services.slack) for business logic.
 * Falls back to direct D-Bus calls for operations not yet in the service.
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

/** Result from a single source in persona test */
interface PersonaTestSource {
  source: string;
  found: boolean;
  count: number;
  results: any[];
  error?: string;
  latency_ms?: number;
}

/** Full persona test result */
interface PersonaTestResult {
  query: string;
  elapsed_ms: number;
  sources: PersonaTestSource[];
  sources_used: string[];
  total_results: number;
  status: {
    slack_persona: {
      synced: boolean;
      total_messages?: number;
      last_sync?: string;
      db_size_mb?: number;
      conversations?: number;
      error?: string;
    };
    code_search: {
      indexed: boolean;
      chunks?: number;
      files?: number;
      index_age?: string;
      is_stale?: boolean;
      error?: string;
    };
    inscope?: {
      available: boolean;
      authenticated?: boolean;
      assistants?: number;
      error?: string;
    };
  };
  project: string;
  error?: string;
  // Formatted context ready for injection (from new ContextInjector)
  formatted?: string;
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
  
  // Context Injection state
  private contextTestQuery = "";
  private contextTestResult: PersonaTestResult | null = null;
  private isGatheringContext = false;
  private contextSourceStatus: {
    slack: { available: boolean; count?: number; error?: string };
    code: { available: boolean; count?: number; error?: string };
    jira: { available: boolean; count?: number; error?: string };
    memory: { available: boolean; count?: number; error?: string };
  } = {
    slack: { available: false },
    code: { available: false },
    jira: { available: false },
    memory: { available: false },
  };
  private recentChannelMessages: SlackMessage[] = [];
  private selectedThreadForContext: string | null = null;
  
  // Legacy - keeping for compatibility
  private personaTestQuery = "";
  private personaTestResult: PersonaTestResult | null = null;
  private isRunningPersonaTest = false;
  private showPersonaTest = false;

  constructor() {
    super({
      id: "slack",
      label: "Slack",
      icon: "💬",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    // Show error indicator if we have an error and no data
    if (this.lastError && !this.status) {
      return { text: "!", class: "error" };
    }

    if (this.pendingMessages.length > 0) {
      return { text: `${this.pendingMessages.length}`, class: "warning" };
    }
    if (this.status?.connected) {
      return { text: "●", class: "status-green" };
    }
    return { text: "○", class: "status-red" };
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    let hasAnyData = false;

    try {
      // Load data in batches to avoid D-Bus request spikes
      // Batch 1: Critical data (status, pending, channels)
      logger.log("loadData() - Batch 1: Fetching status, pending, channels...");
      const [statusResult, pendingResult, channelsResult] = await Promise.all([
        dbus.slack_getStatus(),
        dbus.slack_getPending(),
        dbus.slack_getMyChannels(),
      ]);
      // Log errors only
      if (!statusResult.success) logger.error(`Status error: ${statusResult.error}`);
      if (!pendingResult.success) logger.error(`Pending error: ${pendingResult.error}`);
      if (!channelsResult.success) logger.error(`Channels error: ${channelsResult.error}`);

      // Batch 2: Secondary data (history, cache stats) - slight delay to spread load
      await new Promise(resolve => setTimeout(resolve, 100));
      const [historyResult, channelCacheResult, userCacheResult] = await Promise.all([
        dbus.slack_getHistory(this.historyLimit),
        dbus.slack_getChannelCacheStats(),
        dbus.slack_getUserCacheStats(),
      ]);

      // Batch 3: Tertiary data (sync status, DMs, commands) - another slight delay
      await new Promise(resolve => setTimeout(resolve, 100));
      const [syncResult, dmsResult, commandsResult] = await Promise.all([
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
        // D-Bus returns {success, count, channels} - we need the channels array
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
        hasAnyData = true;
      } else {
        // Even if status fails, we can still show data if we have it
        this.status = {
          connected: false,
          channels_count: this.channels.length,
          pending_count: this.pendingMessages.length,
          processed_today: 0,
        };
        hasAnyData = this.channels.length > 0 || this.pendingMessages.length > 0;
      }

      // Clear error on success
      if (hasAnyData) {
        this.lastError = null;
      }
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
      // Don't reset status - preserve partial data
    }

    logger.log("loadData() complete");
    this.notifyNeedsRender();
  }

  getContent(): string {
    // Show error state if we have an error and no data
    if (this.lastError && !this.status) {
      return this.getErrorHtml(`Failed to load Slack data: ${this.lastError}`);
    }

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

      <!-- Context Injection Section - Always visible -->
      ${this.getContextInjectionSectionHtml()}

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

  /**
   * Context Injection Section - Always visible section showing:
   * 1. All knowledge sources with status
   * 2. Input field to test questions/sentences
   * 3. Thread/channel context fetching
   * 4. Results from context gathering
   */
  private getContextInjectionSectionHtml(): string {
    const status = this.contextTestResult?.status;
    const slackStatus = status?.slack_persona;
    const codeStatus = status?.code_search;
    const inscopeStatus = status?.inscope;
    const hasTestResult = !!this.contextTestResult;
    
    // Get source results if available
    const slackSource = this.contextTestResult?.sources?.find(s => s.source === "slack" || s.source === "slack_persona");
    const codeSource = this.contextTestResult?.sources?.find(s => s.source === "code" || s.source === "code_search");
    const jiraSource = this.contextTestResult?.sources?.find(s => s.source === "jira");
    const memorySource = this.contextTestResult?.sources?.find(s => s.source === "memory");
    const inscopeSource = this.contextTestResult?.sources?.find(s => s.source === "inscope");

    // Helper to render status - show neutral state if no test has been run
    const renderSlackStatus = () => {
      if (!hasTestResult) return `<span class="text-secondary">⏳ Run test to check</span>`;
      if (slackStatus?.synced) return `<span class="text-success">✅ ${(slackStatus.total_messages || 0).toLocaleString()} messages</span>`;
      if (slackStatus?.error) return `<span class="text-error">❌ ${slackStatus.error}</span>`;
      return `<span class="text-warning">⚠️ Not synced</span>`;
    };
    
    const renderCodeStatus = () => {
      if (!hasTestResult) return `<span class="text-secondary">⏳ Run test to check</span>`;
      if (codeStatus?.indexed) return `<span class="text-success">✅ ${(codeStatus.chunks || 0).toLocaleString()} chunks</span>`;
      if (codeStatus?.error) return `<span class="text-error">❌ ${codeStatus.error}</span>`;
      return `<span class="text-warning">⚠️ Not indexed</span>`;
    };
    
    const renderInscopeStatus = () => {
      if (!hasTestResult) return `<span class="text-secondary">⏳ Run test to check</span>`;
      if (inscopeStatus?.authenticated) return `<span class="text-success">✅ ${inscopeStatus.assistants || 20} assistants</span>`;
      if (inscopeStatus?.error) return `<span class="text-error">❌ ${inscopeStatus.error}</span>`;
      return `<span class="text-warning">⚠️ Not authenticated</span>`;
    };

    return `
      <div class="section context-injection-section">
        <div class="section-title">🧠 Persona Context Injection</div>
        <p class="text-secondary text-sm mb-16">
          The Slack persona gathers context from multiple knowledge sources before responding.
          Test what context would be injected for any question or message.
        </p>

        <!-- Knowledge Sources Status Grid - 5 columns -->
        <div class="context-sources-grid">
          
          <!-- Slack Vector DB -->
          <div class="context-source-card purple">
            <div class="card-header">
              <span class="card-icon">💬</span>
              <div>
                <div class="card-title">Slack History</div>
                <div class="card-subtitle">Past conversations</div>
              </div>
            </div>
            <div class="card-status">
              ${renderSlackStatus()}
            </div>
            ${slackSource?.found ? `<div class="card-meta">${slackSource.count} results (${slackSource.latency_ms?.toFixed(0) || 0}ms)</div>` : ""}
          </div>

          <!-- Code Vector DB -->
          <div class="context-source-card blue">
            <div class="card-header">
              <span class="card-icon">📁</span>
              <div>
                <div class="card-title">Code Search</div>
                <div class="card-subtitle">Codebase knowledge</div>
              </div>
            </div>
            <div class="card-status">
              ${renderCodeStatus()}
            </div>
            ${codeSource?.found ? `<div class="card-meta">${codeSource.count} results (${codeSource.latency_ms?.toFixed(0) || 0}ms)</div>` : ""}
          </div>

          <!-- InScope AI -->
          <div class="context-source-card pink">
            <div class="card-header">
              <span class="card-icon">🤖</span>
              <div>
                <div class="card-title">InScope AI</div>
                <div class="card-subtitle">RH Documentation</div>
              </div>
            </div>
            <div class="card-status">
              ${renderInscopeStatus()}
            </div>
            ${inscopeSource?.found ? `<div class="card-meta">${inscopeSource.count} response (${inscopeSource.latency_ms?.toFixed(0) || 0}ms)</div>` : ""}
          </div>

          <!-- Jira -->
          <div class="context-source-card orange">
            <div class="card-header">
              <span class="card-icon">🎫</span>
              <div>
                <div class="card-title">Jira Issues</div>
                <div class="card-subtitle">Auto-detect keys</div>
              </div>
            </div>
            <div class="card-status">
              ${jiraSource?.found 
                ? `<span class="text-success">✅ ${jiraSource.count} issues</span>`
                : `<span class="text-secondary">Detects AAP-XXXXX</span>`}
            </div>
            ${jiraSource?.found ? `<div class="card-meta">(${jiraSource.latency_ms?.toFixed(0) || 0}ms)</div>` : ""}
          </div>

          <!-- Memory -->
          <div class="context-source-card green">
            <div class="card-header">
              <span class="card-icon">🧠</span>
              <div>
                <div class="card-title">Memory</div>
                <div class="card-subtitle">Current work context</div>
              </div>
            </div>
            <div class="card-status">
              ${memorySource?.found 
                ? `<span class="text-success">✅ ${memorySource.count} items</span>`
                : `<span class="text-secondary">Active issues, branch</span>`}
            </div>
            ${memorySource?.found ? `<div class="card-meta">(${memorySource.latency_ms?.toFixed(0) || 0}ms)</div>` : ""}
          </div>
        </div>

        <!-- Test Input Section -->
        <div class="context-test-section">
          <div class="font-bold mb-12">Test Context Gathering</div>
          
          <!-- Input field -->
          <div class="d-flex gap-8 mb-12">
            <input type="text" 
                   class="context-test-input flex-1" 
                   id="contextTestQuery"
                   placeholder="Enter a question or sentence to test... e.g., 'How does billing work?'"
                   value="${this.escapeHtml(this.contextTestQuery)}" />
            <button class="btn btn-primary px-16"
                    data-action="runContextTest" 
                    ${this.isGatheringContext ? "disabled" : ""}>
              ${this.isGatheringContext ? "⏳ Gathering..." : "🔍 Gather Context"}
            </button>
          </div>

          <!-- Quick test examples -->
          <div class="example-tags">
            <span class="label">Examples:</span>
            <button class="btn btn-xs btn-ghost" data-context-test="How does billing work?">billing</button>
            <button class="btn btn-xs btn-ghost" data-context-test="What is the release process?">release</button>
            <button class="btn btn-xs btn-ghost" data-context-test="How do ephemeral deployments work?">ephemeral</button>
            <button class="btn btn-xs btn-ghost" data-context-test="AAP-12345 status">Jira lookup</button>
            <button class="btn btn-xs btn-ghost" data-context-test="What am I currently working on?">current work</button>
            <button class="btn btn-xs btn-ghost" data-context-test="How do I debug production issues?">debugging</button>
          </div>

          <!-- Context source options -->
          <div class="options-row">
            <span class="text-sm text-secondary">Additional context:</span>
            <label class="option-label">
              <input type="checkbox" id="includeThreadContext" checked /> 
              Thread context
            </label>
            <label class="option-label">
              <input type="checkbox" id="includeChannelRecent" checked /> 
              Recent channel messages
            </label>
            <button class="btn btn-xs ml-auto" data-action="fetchChannelContext">
              📥 Fetch Channel Context
            </button>
          </div>
        </div>

        <!-- Results Section -->
        ${this.contextTestResult ? this.getContextResultsHtml() : ""}
      </div>
    `;
  }

  /**
   * Render the context gathering results
   */
  private getContextResultsHtml(): string {
    if (!this.contextTestResult) return "";

    const result = this.contextTestResult;
    const sources = result.sources || [];

    // Error banner
    if (result.error) {
      return `
        <div class="error-banner">
          ⚠️ Error: ${this.escapeHtml(result.error)}
        </div>
      `;
    }

    const successfulSources = sources.filter(s => s.found).length;

    let html = `
      <div class="context-results mt-16">
        <!-- Summary bar -->
        <div class="success-banner">
          <div class="banner-content">
            <span class="banner-title">
              ✅ Found ${result.total_results} context items
            </span>
            <span class="banner-subtitle">
              from ${successfulSources} sources in ${result.elapsed_ms}ms
            </span>
          </div>
          <div class="text-sm text-secondary">
            Query: "${this.escapeHtml(result.query.substring(0, 50))}${result.query.length > 50 ? "..." : ""}"
          </div>
        </div>

        <!-- Results by source -->
        <div class="d-flex flex-col gap-12">
    `;

    for (const source of sources) {
      const sourceConfig = this.getSourceConfig(source.source);
      
      html += `
        <div class="context-source-results card overflow-hidden">
          <div class="flex-between p-12 border-b" style="background: rgba(${sourceConfig.color},0.1);">
            <div class="d-flex items-center gap-8">
              <span class="text-lg">${sourceConfig.icon}</span>
              <span class="font-bold">${sourceConfig.name}</span>
            </div>
            <span class="text-sm text-secondary">
              ${source.found ? `${source.count} results` : `❌ ${source.error || "No results"}`}
              ${source.latency_ms ? ` • ${source.latency_ms.toFixed(0)}ms` : ""}
            </span>
          </div>
      `;

      if (source.found && source.results.length > 0) {
        html += `<div class="p-12 d-flex flex-col gap-8">`;
        
        for (const item of source.results.slice(0, 5)) {
          html += this.renderContextResultItem(source.source, item, sourceConfig.color);
        }
        
        if (source.results.length > 5) {
          html += `<div class="text-center p-8 text-secondary text-sm">
            ...and ${source.results.length - 5} more results
          </div>`;
        }
        
        html += `</div>`;
      }

      html += `</div>`;
    }

    html += `
        </div>
      </div>
    `;

    // Add formatted context preview if available
    if (result.formatted) {
      html += `
        <div class="mt-16">
          <div class="font-bold mb-8 d-flex items-center gap-8">
            📋 Formatted Context (injected into prompt)
            <button class="btn btn-xs" data-action="copyFormattedContext">Copy</button>
          </div>
          <pre class="code-preview">${this.escapeHtml(result.formatted)}</pre>
        </div>
      `;
    }

    return html;
  }

  private getSourceConfig(source: string): { icon: string; name: string; color: string } {
    const configs: Record<string, { icon: string; name: string; color: string }> = {
      "slack": { icon: "💬", name: "Slack Conversations", color: "139,92,246" },
      "slack_persona": { icon: "💬", name: "Slack Conversations", color: "139,92,246" },
      "code": { icon: "📁", name: "Code Search", color: "59,130,246" },
      "code_search": { icon: "📁", name: "Code Search", color: "59,130,246" },
      "inscope": { icon: "🤖", name: "InScope AI", color: "236,72,153" },
      "jira": { icon: "🎫", name: "Jira Issues", color: "245,158,11" },
      "memory": { icon: "🧠", name: "Memory / Current Work", color: "34,197,94" },
    };
    return configs[source] || { icon: "📋", name: source, color: "100,100,100" };
  }

  private renderContextResultItem(source: string, item: any, color: string): string {
    // Map source to CSS class for background color
    const bgClass = this.getSourceBgClass(source);
    
    if (source === "slack" || source === "slack_persona") {
      return `
        <div class="result-item ${bgClass}">
          <div class="result-item-header">
            <span class="font-bold">@${this.escapeHtml(item.user || "unknown")}</span>
            <div class="d-flex gap-8 text-secondary">
              <span>${item.channel_type || ""}</span>
              <span>${item.datetime || ""}</span>
              <span class="text-success">${item.relevance || 0}%</span>
            </div>
          </div>
          <div class="text-primary">${this.escapeHtml((item.text || "").substring(0, 300))}${(item.text || "").length > 300 ? "..." : ""}</div>
        </div>
      `;
    } else if (source === "code" || source === "code_search") {
      return `
        <div class="result-item ${bgClass}">
          <div class="result-item-header">
            <span class="mono">${this.escapeHtml(item.file || "")}:${item.lines || ""}</span>
            <span class="text-success">${item.relevance || 0}%</span>
          </div>
          <div class="text-secondary mb-4">${item.type || ""} <code>${this.escapeHtml(item.name || "")}</code></div>
          ${item.preview ? `<pre class="code-preview m-0 p-8 text-2xs">${this.escapeHtml((item.preview || "").substring(0, 200))}</pre>` : ""}
        </div>
      `;
    } else if (source === "jira") {
      return `
        <div class="result-item ${bgClass}">
          <span class="font-bold">${this.escapeHtml(item.key || "")}</span>
          ${item.summary ? `<span class="ml-8">${this.escapeHtml((item.summary || "").substring(0, 100))}</span>` : ""}
          <span class="text-secondary ml-8">${this.escapeHtml(item.status || item.note || "")}</span>
        </div>
      `;
    } else if (source === "memory") {
      const itemType = item.type || "";
      let content = "";
      if (itemType === "active_issues") {
        content = `Active issues: ${(item.items || []).join(", ")}`;
      } else if (itemType === "current_branch") {
        content = `Current branch: ${item.value || ""}`;
      } else if (itemType === "learned_patterns") {
        content = `Patterns: ${(item.items || []).map((p: any) => p.pattern).join(", ")}`;
      } else {
        content = JSON.stringify(item);
      }
      return `
        <div class="result-item ${bgClass}">
          <span class="font-bold">${this.escapeHtml(itemType)}</span>
          <div class="mt-4">${this.escapeHtml(content)}</div>
        </div>
      `;
    } else if (source === "inscope") {
      const assistant = item.assistant || "Unknown Assistant";
      const response = item.response || "";
      const sources = item.sources || [];
      
      let sourcesHtml = "";
      if (sources.length > 0) {
        sourcesHtml = `
          <div class="mt-8 pt-8 border-t">
            <div class="text-2xs text-secondary mb-4">Sources:</div>
            ${sources.map((s: any) => `
              <div class="text-2xs">
                ${s.url ? `<a href="${this.escapeHtml(s.url)}" class="link">${this.escapeHtml(s.title || s.url)}</a>` : this.escapeHtml(s.title || "")}
              </div>
            `).join("")}
          </div>
        `;
      }
      
      return `
        <div class="result-item ${bgClass}">
          <div class="result-item-header">
            <span class="font-bold">🤖 ${this.escapeHtml(assistant)}</span>
          </div>
          <div class="text-primary whitespace-pre-wrap">${this.escapeHtml(response.substring(0, 500))}${response.length > 500 ? "..." : ""}</div>
          ${sourcesHtml}
        </div>
      `;
    }
    return `<div class="result-item ${bgClass}">${this.escapeHtml(JSON.stringify(item))}</div>`;
  }

  private getSourceBgClass(source: string): string {
    const classMap: Record<string, string> = {
      "slack": "purple-bg",
      "slack_persona": "purple-bg",
      "code": "blue-bg",
      "code_search": "blue-bg",
      "inscope": "pink-bg",
      "jira": "orange-bg",
      "memory": "green-bg",
    };
    return classMap[source] || "dark-bg";
  }

  // Keep legacy method for backward compatibility
  private getPersonaTestHtml(): string {
    return this.getContextInjectionSectionHtml();
  }

  private getPersonaTestResultsHtml(): string {
    if (!this.personaTestResult) return "";

    const result = this.personaTestResult;
    const sources = result.sources || [];

    // Error banner
    if (result.error) {
      return `
        <div class="error-banner mt-12">
          ⚠️ Error: ${this.escapeHtml(result.error)}
        </div>
      `;
    }

    // Count successful sources
    const successfulSources = sources.filter(s => s.found).length;

    // Summary
    let html = `
      <div class="slack-persona-test-results mt-12">
        <div class="success-banner p-8 mb-12">
          <span class="font-bold text-success">✅ ${result.total_results} results from ${successfulSources} sources</span>
          <span class="text-secondary text-sm">${result.elapsed_ms}ms</span>
        </div>
    `;

    // Results by source
    for (const source of sources) {
      const sourceConfig = this.getSourceConfig(source.source);
      const bgClass = this.getSourceBgClass(source.source);

      html += `
        <div class="slack-persona-source card mb-12 p-12">
          <div class="flex-between mb-8">
            <span class="font-bold">${sourceConfig.icon} ${sourceConfig.name}</span>
            <span class="text-2xs text-secondary">
              ${source.found ? `${source.count} results` : `❌ ${source.error || "No results"}`}
              ${source.latency_ms ? ` (${Math.round(source.latency_ms)}ms)` : ""}
            </span>
          </div>
      `;

      if (source.found && source.results.length > 0) {
        html += `<div class="slack-persona-source-results d-flex flex-col gap-6">`;

        for (const item of source.results.slice(0, 5)) {
          if (source.source === "slack_persona" || source.source === "slack") {
            html += `
              <div class="result-item ${bgClass}">
                <div class="flex-between mb-4">
                  <span class="text-secondary">@${this.escapeHtml(item.user || "unknown")} (${item.channel_type || "unknown"})</span>
                  <span class="text-success">${item.relevance || 0}%</span>
                </div>
                <div class="text-primary">${this.escapeHtml((item.text || "").substring(0, 200))}${(item.text || "").length > 200 ? "..." : ""}</div>
              </div>
            `;
          } else if (source.source === "code_search" || source.source === "code") {
            html += `
              <div class="result-item ${bgClass}">
                <div class="flex-between mb-4">
                  <span class="mono">${this.escapeHtml(item.file || "")}:${item.lines || ""}</span>
                  <span class="text-success">${item.relevance || 0}%</span>
                </div>
                <div class="text-secondary">${item.type || ""} <code>${this.escapeHtml(item.name || "")}</code></div>
                ${item.preview ? `<div class="mt-4 mono text-2xs text-secondary overflow-hidden max-h-60 whitespace-pre-wrap">${this.escapeHtml((item.preview || "").substring(0, 150))}</div>` : ""}
              </div>
            `;
          } else if (source.source === "jira") {
            html += `
              <div class="result-item ${bgClass}">
                <span class="font-bold">${this.escapeHtml(item.key || "")}</span>
                ${item.summary ? `<span class="ml-8">${this.escapeHtml((item.summary || "").substring(0, 100))}</span>` : ""}
                <span class="text-secondary ml-8">${this.escapeHtml(item.status || item.note || "")}</span>
              </div>
            `;
          } else if (source.source === "memory") {
            // Memory items have different structure
            const itemType = item.type || "";
            let memoryContent = "";
            if (itemType === "active_issues") {
              memoryContent = `Active issues: ${(item.items || []).join(", ")}`;
            } else if (itemType === "current_branch") {
              memoryContent = `Current branch: ${item.value || ""}`;
            } else if (itemType === "learned_patterns") {
              memoryContent = `Learned patterns: ${(item.items || []).map((p: any) => p.pattern).join(", ")}`;
            } else {
              memoryContent = JSON.stringify(item);
            }
            html += `
              <div class="result-item ${bgClass}">
                <span class="font-bold">${this.escapeHtml(itemType)}</span>
                <div class="text-primary mt-4">${this.escapeHtml(memoryContent)}</div>
              </div>
            `;
          }
        }

        html += `</div>`;
      }

      html += `</div>`;
    }

    html += `</div>`;
    return html;
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
    // Use centralized event delegation system - handlers survive content updates
    return `
      // ============ Slack Tab Event Delegation ============
      (function() {
        const slackContainer = document.getElementById('slack');
        
        // Fetch context injection status on page load (only once)
        if (slackContainer && !slackContainer.dataset.contextFetched) {
          slackContainer.dataset.contextFetched = 'true';
          const statusCards = slackContainer.querySelectorAll('.context-source-card');
          const hasStatus = Array.from(statusCards).some(card => 
            card.textContent?.includes('messages') || card.textContent?.includes('chunks')
          );
          if (!hasStatus) {
            console.log('[SlackTab] Fetching context injection status on load');
            vscode.postMessage({ command: 'fetchContextStatus' });
          }
        }

        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('slack', function(action, element, e) {
          switch(action) {
            case 'refreshSlack':
              vscode.postMessage({ command: 'refreshSlack' });
              break;
            case 'approveAllSlack':
              vscode.postMessage({ command: 'approveAllSlack' });
              break;
            case 'reloadSlackConfig':
              vscode.postMessage({ command: 'reloadSlackConfig' });
              break;
            case 'toggleAdvanced':
              vscode.postMessage({ command: 'toggleAdvanced' });
              break;
            case 'approveSlackMessage':
              if (element.dataset.messageId) {
                vscode.postMessage({ command: 'approveSlackMessage', messageId: element.dataset.messageId });
              }
              break;
            case 'rejectSlackMessage':
              if (element.dataset.messageId) {
                vscode.postMessage({ command: 'rejectSlackMessage', messageId: element.dataset.messageId });
              }
              break;
            case 'openSlackChannel':
              if (element.dataset.channel) {
                vscode.postMessage({ command: 'openSlackChannel', channelId: element.dataset.channel });
              }
              break;
            case 'loadMoreSlackHistory':
              vscode.postMessage({ command: 'loadMoreSlackHistory', limit: 50 });
              break;
            case 'searchSlack': {
              const input = document.querySelector('#slack [data-action="searchInput"]');
              vscode.postMessage({ command: 'searchSlack', query: input ? input.value : '' });
              break;
            }
            case 'refreshChannelCache':
              vscode.postMessage({ command: 'refreshChannelCache' });
              break;
            case 'refreshUserCache':
              vscode.postMessage({ command: 'refreshUserCache' });
              break;
            case 'healthCheck':
              vscode.postMessage({ command: 'healthCheck' });
              break;
            case 'toggleDebug':
              vscode.postMessage({ command: 'toggleDebug' });
              break;
            case 'sendMessage': {
              const channelSelect = document.querySelector('#slack [data-action="selectChannel"]');
              const messageInput = document.querySelector('#slack [data-action="messageInput"]');
              vscode.postMessage({
                command: 'sendSlackMessage',
                channelId: channelSelect ? channelSelect.value : '',
                text: messageInput ? messageInput.value : ''
              });
              break;
            }
            case 'startSync':
              vscode.postMessage({ command: 'startSync' });
              break;
            case 'stopSync':
              vscode.postMessage({ command: 'stopSync' });
              break;
            case 'triggerSync':
              if (element.dataset.syncType) {
                vscode.postMessage({ command: 'triggerSync', syncType: element.dataset.syncType });
              }
              break;
            case 'searchUsers': {
              const input = document.querySelector('#slack [data-action="userSearchInput"]');
              vscode.postMessage({ command: 'searchUsers', query: input ? input.value : '' });
              break;
            }
            case 'viewUserProfile':
              if (element.dataset.userId) {
                vscode.postMessage({ command: 'viewUserProfile', userId: element.dataset.userId });
              }
              break;
            case 'viewSlackThread':
              if (element.dataset.channel && element.dataset.thread) {
                vscode.postMessage({ command: 'viewThread', channelId: element.dataset.channel, threadTs: element.dataset.thread });
              }
              break;
            case 'closeThread':
              vscode.postMessage({ command: 'closeThread' });
              break;
            case 'runContextTest': {
              const input = document.getElementById('contextTestQuery');
              const includeThread = document.getElementById('includeThreadContext');
              const includeChannel = document.getElementById('includeChannelRecent');
              const query = input ? input.value.trim() : '';
              if (query) {
                vscode.postMessage({ 
                  command: 'runContextTest', 
                  query: query,
                  includeThread: includeThread ? includeThread.checked : true,
                  includeChannel: includeChannel ? includeChannel.checked : true
                });
              } else {
                // Send anyway to show the error message from the extension
                vscode.postMessage({ command: 'runContextTest', query: '' });
              }
              break;
            }
            case 'fetchChannelContext':
              vscode.postMessage({ command: 'fetchChannelContext' });
              break;
            case 'copyFormattedContext':
              vscode.postMessage({ command: 'copyFormattedContext' });
              break;
            case 'togglePersonaTest':
              vscode.postMessage({ command: 'togglePersonaTest' });
              break;
            case 'runPersonaTest': {
              const input = document.getElementById('contextTestQuery') || document.getElementById('personaTestQuery');
              if (input && input.value) {
                vscode.postMessage({ command: 'runContextTest', query: input.value });
              }
              break;
            }
          }
        });

        // Handle data-context-test example buttons (populate input field)
        // Use a guard to prevent duplicate listeners
        if (!document.body.dataset.slackContextTestInit) {
          document.body.dataset.slackContextTestInit = 'true';
          document.addEventListener('click', function(e) {
            const target = e.target.closest('[data-context-test]');
            if (target) {
              const query = target.getAttribute('data-context-test');
              const input = document.getElementById('contextTestQuery');
              if (input && query) {
                input.value = query;
                input.focus();
                // Sync value back to extension
                vscode.postMessage({ command: 'contextTestQueryUpdate', query: query });
              }
            }
          });
          
          // Sync context test input value as user types (to preserve during refresh)
          document.addEventListener('input', function(e) {
            const target = e.target;
            if (target && target.id === 'contextTestQuery') {
              vscode.postMessage({ command: 'contextTestQueryUpdate', query: target.value });
            }
          });
        }

        // Register keypress handler for Enter key
        TabEventDelegation.registerKeypressHandler('slack', function(element, e) {
          if (e.key !== 'Enter') return;
          
          // Search input
          if (element.dataset && element.dataset.action === 'searchInput') {
            vscode.postMessage({ command: 'searchSlack', query: element.value });
            return;
          }
          
          // User search input
          if (element.dataset && element.dataset.action === 'userSearchInput') {
            vscode.postMessage({ command: 'searchUsers', query: element.value });
            return;
          }
          
          // Context test input
          if (element.id === 'contextTestQuery') {
            const includeThread = document.getElementById('includeThreadContext');
            const includeChannel = document.getElementById('includeChannelRecent');
            if (element.value) {
              vscode.postMessage({ 
                command: 'runContextTest', 
                query: element.value,
                includeThread: includeThread ? includeThread.checked : true,
                includeChannel: includeChannel ? includeChannel.checked : true
              });
            }
            return;
          }
        });
      })();
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

      case "togglePersonaTest":
        this.showPersonaTest = !this.showPersonaTest;
        this.notifyNeedsRender();
        return true;

      // ============ Context Injection Handlers ============
      
      case "contextTestResult":
        // Received context gathering result from the backend
        if (message.data) {
          this.contextTestResult = message.data as PersonaTestResult;
          // Also update legacy for compatibility
          this.personaTestResult = message.data as PersonaTestResult;
        }
        this.isGatheringContext = false;
        this.isRunningPersonaTest = false;
        this.notifyNeedsRender();
        return true;

      case "contextTestStarted":
        this.isGatheringContext = true;
        this.isRunningPersonaTest = true;
        this.notifyNeedsRender();
        return true;

      case "contextTestQueryUpdate":
        // Update the query field (don't re-render - just sync the value)
        if (message.query !== undefined) {
          this.contextTestQuery = message.query;
          this.personaTestQuery = message.query;
        }
        // Don't call notifyNeedsRender() - we're just syncing the input value
        return true;

      case "channelContextFetched":
        // Received recent channel messages for context
        if (message.messages) {
          this.recentChannelMessages = message.messages;
        }
        this.notifyNeedsRender();
        return true;

      // Legacy handlers (redirect to new ones)
      case "personaTestResult":
        // Received result from the backend
        if (message.data) {
          this.contextTestResult = message.data as PersonaTestResult;
          this.personaTestResult = message.data as PersonaTestResult;
        }
        this.isGatheringContext = false;
        this.isRunningPersonaTest = false;
        this.notifyNeedsRender();
        return true;

      case "personaTestStarted":
        this.isGatheringContext = true;
        this.isRunningPersonaTest = true;
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

      // === NEW: Missing handlers from Phase 3.2 ===
      // NOTE: runPersonaTest and runContextTest are handled by MessageRouter -> commandCenter.runContextTest()
      // which uses the Python script approach. DO NOT handle here - let it fall through to MessageRouter.

      case "fetchContextStatus":
        // Context status is already loaded in loadData
        this.notifyNeedsRender();
        return true;

      case "loadSlackChannelBrowser":
        await this.loadChannelBrowser(message.query || "");
        return true;

      case "loadSlackUserBrowser":
        await this.loadUserBrowser(message.query || "");
        return true;

      case "loadSlackCommands":
        await this.loadCommands();
        return true;

      case "sendSlackCommand":
        await this.sendCommand(message.command, message.args || {});
        return true;

      case "loadSlackConfig":
        await this.loadSlackConfig();
        return true;

      default:
        return false;
    }
  }

  private async approveAll(): Promise<void> {
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.approveAll()");
      await this.services.slack.approveAll();
    } else {
      logger.log("Falling back to D-Bus for approveAll");
      const result = await dbus.slack_approveAll();
      if (!result.success) {
        logger.error(`Failed to approve all: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async reloadConfig(): Promise<void> {
    // No service method for this yet, use D-Bus directly
    const result = await dbus.slack_reloadConfig();
    if (!result.success) {
      logger.error(`Failed to reload config: ${result.error}`);
    }
    await this.refresh();
  }

  private async approveMessage(messageId: string): Promise<void> {
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.approveMessage()");
      await this.services.slack.approveMessage(messageId);
    } else {
      logger.log("Falling back to D-Bus for approveMessage");
      const result = await dbus.slack_approveMessage(messageId);
      if (!result.success) {
        logger.error(`Failed to approve message: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async rejectMessage(messageId: string): Promise<void> {
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.rejectMessage()");
      await this.services.slack.rejectMessage(messageId);
    } else {
      logger.log("Falling back to D-Bus for rejectMessage");
      const result = await dbus.slack_rejectMessage(messageId);
      if (!result.success) {
        logger.error(`Failed to reject message: ${result.error}`);
      }
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
    
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.searchMessages()");
      const searchResult = await this.services.slack.searchMessages(query, 20);
      // Map SlackService messages to local SlackMessage format
      this.searchResults = (searchResult.messages || []).map((m: any) => ({
        id: m.id,
        channel_id: m.channel || "",
        channel_name: m.channel || "",
        user_id: m.user || "",
        user_name: m.user || "",
        text: m.text,
        timestamp: m.timestamp || "",
        thread_ts: m.thread_ts,
        status: "sent" as const,
      }));
      if (searchResult.rateLimited) {
        vscode.window.showWarningMessage("Slack search rate limited. Try again later.");
      }
    } else {
      logger.log("Falling back to D-Bus for searchMessages");
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
    }
    this.notifyNeedsRender();
  }

  private async refreshChannelCache(): Promise<void> {
    vscode.window.showInformationMessage("Refreshing channel cache...");
    
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.refreshCache()");
      const stats = await this.services.slack.refreshCache();
      vscode.window.showInformationMessage(`Cached ${stats.channels} channels, ${stats.users} users`);
    } else {
      logger.log("Falling back to D-Bus for refreshChannelCache");
      const result = await dbus.slack_refreshChannelCache();
      if (result.success) {
        const data = result.data as any;
        vscode.window.showInformationMessage(`Cached ${data.channels_cached || 0} channels`);
      } else {
        vscode.window.showErrorMessage(`Failed to refresh: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async refreshUserCache(): Promise<void> {
    vscode.window.showInformationMessage("Refreshing user cache...");
    
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.refreshCache() for users");
      // SlackService.refreshCache() handles both channels and users
      const stats = await this.services.slack.refreshCache();
      vscode.window.showInformationMessage(`Cached ${stats.users} users`);
    } else {
      logger.log("Falling back to D-Bus for refreshUserCache");
      const result = await dbus.slack_refreshUserCache();
      if (result.success) {
        const data = result.data as any;
        const msg = data.skipped
          ? "User cache is recent, skipped refresh"
          : `Cached ${data.users_cached || 0} users`;
        vscode.window.showInformationMessage(msg);
      } else {
        vscode.window.showErrorMessage(`Failed to refresh: ${result.error}`);
      }
    }
    await this.refresh();
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
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.setDebugMode()");
      await this.services.slack.setDebugMode(true);
    } else {
      logger.log("Falling back to D-Bus for toggleDebug");
      const result = await dbus.slack_setDebugMode(true);
      if (result.success) {
        vscode.window.showInformationMessage("Debug mode toggled");
      } else {
        vscode.window.showErrorMessage(`Failed to toggle debug: ${result.error}`);
      }
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

    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.sendMessage()");
      const success = await this.services.slack.sendMessage(channelId, text);
      if (success) {
        await this.refresh();
      }
    } else {
      logger.log("Falling back to D-Bus for sendMessage");
      const result = await dbus.slack_sendMessage(channelId, text);
      if (result.success) {
        vscode.window.showInformationMessage("Message sent!");
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to send: ${result.error}`);
      }
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
    
    // Use SlackService if available (preferred), otherwise fall back to D-Bus
    if (this.services.slack) {
      logger.log("Using SlackService.searchUsers()");
      const users = await this.services.slack.searchUsers(query);
      this.userSearchResults = users as any[];
    } else {
      logger.log("Falling back to D-Bus for searchUsers");
      const result = await dbus.slack_searchUsers(query);
      if (result.success && result.data) {
        const data = result.data as any;
        this.userSearchResults = data.results || data.users || [];
      } else {
        this.userSearchResults = [];
        logger.error(`User search failed: ${result.error}`);
      }
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

  // === NEW: Phase 3.2 handlers ===

  private async runContextTest(testMessage: string, persona?: string): Promise<void> {
    if (!testMessage) {
      vscode.window.showWarningMessage("Please enter a test message");
      return;
    }

    this.isGatheringContext = true;
    this.isRunningPersonaTest = true;
    this.notifyNeedsRender();

    try {
      logger.log(`Running context test: message="${testMessage}", persona="${persona || 'auto'}"`);
      
      // Call D-Bus to run the persona/context test
      const result = await dbus.slack_runPersonaTest(testMessage, persona || "");
      
      if (result.success && result.data) {
        const data = result.data as any;
        this.contextTestResult = data;
        this.personaTestResult = data;
        logger.log(`Context test complete`);
      } else {
        logger.error(`Context test failed: ${result.error}`);
        vscode.window.showErrorMessage(`Context test failed: ${result.error}`);
      }
    } catch (error) {
      logger.error("Context test error", error);
      vscode.window.showErrorMessage(`Context test error: ${error instanceof Error ? error.message : String(error)}`);
    }

    this.isGatheringContext = false;
    this.isRunningPersonaTest = false;
    this.notifyNeedsRender();
  }

  private async loadChannelBrowser(query: string): Promise<void> {
    try {
      // Use SlackService if available (preferred), otherwise fall back to D-Bus
      if (this.services.slack) {
        logger.log("Using SlackService.findChannel()");
        const result = await this.services.slack.findChannel(query);
        // Result is published via MessageBus, but we can also store it locally
        logger.log(`Found ${result.count} channels`);
      } else {
        logger.log("Falling back to D-Bus for loadChannelBrowser");
        const result = await dbus.slack_findChannel(query);
        if (result.success && result.data) {
          const data = result.data as any;
          logger.log(`Found ${data.count || 0} channels`);
        }
      }
    } catch (error) {
      logger.error("Failed to load channel browser", error);
    }
    this.notifyNeedsRender();
  }

  private async loadUserBrowser(query: string): Promise<void> {
    try {
      // Use SlackService if available (preferred), otherwise fall back to D-Bus
      if (this.services.slack) {
        logger.log("Using SlackService.findUser()");
        const result = await this.services.slack.findUser(query);
        logger.log(`Found ${result.count} users`);
      } else {
        logger.log("Falling back to D-Bus for loadUserBrowser");
        const result = await dbus.slack_findUser(query);
        if (result.success && result.data) {
          const data = result.data as any;
          logger.log(`Found ${data.count || 0} users`);
        }
      }
    } catch (error) {
      logger.error("Failed to load user browser", error);
    }
    this.notifyNeedsRender();
  }

  private async loadCommands(): Promise<void> {
    try {
      // Use SlackService if available (preferred), otherwise fall back to D-Bus
      if (this.services.slack) {
        logger.log("Using SlackService.getCommands()");
        const commands = await this.services.slack.getCommands();
        this.commands = commands;
      } else {
        logger.log("Falling back to D-Bus for loadCommands");
        const result = await dbus.slack_getCommandList();
        if (result.success && result.data) {
          const data = result.data as any;
          this.commands = data.commands || [];
        }
      }
    } catch (error) {
      logger.error("Failed to load commands", error);
    }
    this.notifyNeedsRender();
  }

  private async sendCommand(command: string, args: Record<string, string>): Promise<void> {
    if (!command) {
      vscode.window.showWarningMessage("Please select a command");
      return;
    }

    try {
      // Use SlackService if available (preferred), otherwise fall back to D-Bus
      if (this.services.slack) {
        logger.log(`Using SlackService.sendCommand(): ${command}`);
        await this.services.slack.sendCommand(command, args);
      } else {
        logger.log(`Falling back to D-Bus for sendCommand: ${command}`);
        // Build the @me command string
        let commandStr = `@me ${command}`;
        for (const [key, value] of Object.entries(args)) {
          if (value) {
            commandStr += ` --${key}="${value}"`;
          }
        }
        const result = await dbus.slack_sendMessage("", commandStr);
        if (result.success) {
          vscode.window.showInformationMessage(`Command sent: ${command}`);
        } else {
          vscode.window.showErrorMessage(`Failed to send command: ${result.error}`);
        }
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to send command: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.refresh();
  }

  private async loadSlackConfig(): Promise<void> {
    try {
      // Use SlackService if available (preferred), otherwise fall back to D-Bus
      if (this.services.slack) {
        logger.log("Using SlackService.getConfig()");
        await this.services.slack.getConfig();
      } else {
        logger.log("Falling back to D-Bus for loadSlackConfig");
        const result = await dbus.slack_getConfig();
        if (result.success && result.data) {
          logger.log("Slack config loaded");
        }
      }
    } catch (error) {
      logger.error("Failed to load Slack config", error);
    }
    this.notifyNeedsRender();
  }
}
