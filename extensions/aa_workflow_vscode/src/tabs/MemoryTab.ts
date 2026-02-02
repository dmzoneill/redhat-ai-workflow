/**
 * Memory Tab
 *
 * Displays memory browser, session logs, learned patterns, and tool fixes.
 * Uses D-Bus to communicate with the Memory daemon.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("MemoryTab");

interface MemoryFile {
  path: string;
  name: string;
  type: "file" | "directory";
  size?: number;
  modified?: string;
  category?: string;
}

interface SessionLog {
  timestamp: string;
  session_id: string;
  session_name?: string;
  action: string;
  details: string;
}

interface LearnedPattern {
  id: string;
  pattern: string;
  context: string;
  learned_at: string;
  usage_count: number;
  // Fields from daemon (may differ from interface)
  type?: string;
  count?: number;
  lastUsed?: string;
}

interface ToolFix {
  id: string;
  tool_name: string;
  error_pattern: string;
  fix_description: string;
  learned_at: string;
  applied_count: number;
  // Additional fields from daemon
  root_cause?: string;
  verified?: boolean;
}


interface VectorDatabase {
  name: string;
  type: string;
  document_count: number;
  last_updated?: string;
  size?: string;
  status: "ready" | "indexing" | "error";
}

interface SlackDatabase {
  channels_count: number;
  users_count: number;
  messages_count: number;
  last_sync?: string;
  size?: string;
}

export class MemoryTab extends BaseTab {
  private memoryFiles: MemoryFile[] = [];
  private sessionLogs: SessionLog[] = [];
  private learnedPatterns: LearnedPattern[] = [];
  private toolFixes: ToolFix[] = [];
  private selectedCategory: string = "state";
  private selectedFile: string | null = null;
  private fileContent: string | null = null;
  private totalSize: string = "";
  private vectorDatabases: VectorDatabase[] = [];
  private slackDatabase: SlackDatabase | null = null;

  constructor() {
    super({
      id: "memory",
      label: "Memory",
      icon: "🧠",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    if (this.totalSize) {
      return { text: this.totalSize, class: "" };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load memory health for total size badge
      logger.log("Calling memory_getHealth()...");
      const healthResult = await dbus.memory_getHealth();
      logger.log(`memory_getHealth() result: success=${healthResult.success}, error=${healthResult.error || 'none'}`);
      if (healthResult.success && healthResult.data) {
        const data = healthResult.data as any;
        const health = data.health || data;
        this.totalSize = health.totalSize || health.total_size || "";
        logger.log(`Memory total size: ${this.totalSize}`);
      }

      // Load memory files for selected category
      logger.log("Calling memory_getFiles()...");
      const filesResult = await dbus.memory_getFiles();
      logger.log(`memory_getFiles() result: success=${filesResult.success}, error=${filesResult.error || 'none'}`);
      if (filesResult.success && filesResult.data) {
        const data = filesResult.data as any;
        // Files are grouped by category - extract the selected category's files
        const allFiles = data.files || {};
        logger.log(`Available categories: ${Object.keys(allFiles).join(', ')}`);
        const categoryFiles = allFiles[this.selectedCategory] || [];
        logger.log(`Files in ${this.selectedCategory}: ${categoryFiles.length}`);
        // Convert to array of file objects with name and path properties
        this.memoryFiles = categoryFiles.map((f: any) => {
          if (typeof f === 'string') {
            return { name: f, path: `${this.selectedCategory}/${f}`, type: 'file' as const };
          }
          return {
            name: f.file || f.name || f,
            path: f.path || `${this.selectedCategory}/${f.file || f.name || f}`,
            type: 'file' as const
          };
        });

        // Auto-select first file if none selected and files exist
        if (!this.selectedFile && this.memoryFiles.length > 0) {
          this.loadFile(this.memoryFiles[0].path);
        }
      }

      // Load learned patterns via get_learned_patterns handler (UI-friendly format)
      logger.log("Calling memory_getLearnedPatterns()...");
      const patternsResult = await dbus.memory_getLearnedPatterns();
      logger.log(`memory_getLearnedPatterns() result: success=${patternsResult.success}, error=${patternsResult.error || 'none'}`);
      if (patternsResult.success && patternsResult.data) {
        const data = patternsResult.data as any;
        this.learnedPatterns = data.patterns || [];
        logger.log(`Loaded ${this.learnedPatterns.length} patterns`);
      }

      // Load session logs
      logger.log("Calling memory_getSessionLogs()...");
      const logsResult = await dbus.memory_getSessionLogs(20);
      logger.log(`memory_getSessionLogs() result: success=${logsResult.success}, error=${logsResult.error || 'none'}`);
      if (logsResult.success && logsResult.data) {
        const data = logsResult.data as any;
        this.sessionLogs = data.logs || [];
        logger.log(`Loaded ${this.sessionLogs.length} session logs`);
      }

      // Load tool fixes
      logger.log("Calling memory_getToolFixes()...");
      const fixesResult = await dbus.memory_getToolFixes();
      logger.log(`memory_getToolFixes() result: success=${fixesResult.success}, error=${fixesResult.error || 'none'}`);
      if (fixesResult.success && fixesResult.data) {
        const data = fixesResult.data as any;
        this.toolFixes = data.fixes || [];
        logger.log(`Loaded ${this.toolFixes.length} tool fixes`);
      }

      // Load vector databases (code search indexes)
      // Read from vector DB metadata files directly
      logger.log("Loading vector database stats...");
      try {
        const vectorDbPath = `${process.env.HOME}/.cache/aa-workflow/vectors`;
        const fs = await import("fs");
        const path = await import("path");

        if (fs.existsSync(vectorDbPath)) {
          const entries = fs.readdirSync(vectorDbPath).filter((f: string) => {
            // Skip openvino_cache and other non-project directories
            if (f === "openvino_cache" || f.startsWith(".") || f.includes("{{")) {
              return false;
            }
            const metaPath = path.join(vectorDbPath, f, "metadata.json");
            return fs.existsSync(metaPath);
          });

          this.vectorDatabases = entries.map((proj: string) => {
            const metaPath = path.join(vectorDbPath, proj, "metadata.json");
            const projPath = path.join(vectorDbPath, proj);
            try {
              const meta = JSON.parse(fs.readFileSync(metaPath, "utf-8"));
              const stats = meta.stats || {};
              const fileHashes = meta.file_hashes || {};

              // Calculate directory size
              let totalSize = 0;
              const calcSize = (dir: string) => {
                const items = fs.readdirSync(dir, { withFileTypes: true });
                for (const item of items) {
                  const fullPath = path.join(dir, item.name);
                  if (item.isDirectory()) {
                    calcSize(fullPath);
                  } else {
                    totalSize += fs.statSync(fullPath).size;
                  }
                }
              };
              calcSize(projPath);

              const filesCount = Object.keys(fileHashes).length;
              const chunksCount = stats.chunks_created || 0;

              return {
                name: proj,
                type: "code (LanceDB)",
                document_count: chunksCount > 0 ? chunksCount : filesCount,
                last_updated: meta.indexed_at,
                size: `${(totalSize / 1024 / 1024).toFixed(1)} MB`,
                status: (stats.errors && stats.errors.length > 0) ? "error" as const : "ready" as const,
              };
            } catch (e) {
              logger.log(`Error loading metadata for ${proj}: ${e}`);
              return {
                name: proj,
                type: "code",
                document_count: 0,
                status: "error" as const,
              };
            }
          });
          logger.log(`Loaded ${this.vectorDatabases.length} vector databases`);
        }
      } catch (e) {
        logger.log(`Vector database load error: ${e}`);
      }

      // Load Slack database stats
      logger.log("Calling slack_getChannelCacheStats() and slack_getUserCacheStats()...");
      try {
        const channelStats = await dbus.slack_getChannelCacheStats();
        const userStats = await dbus.slack_getUserCacheStats();

        logger.log(`Channel stats result: ${JSON.stringify(channelStats)}`);
        logger.log(`User stats result: ${JSON.stringify(userStats)}`);

        // D-Bus returns JSON with success field inside the data
        const channelData = channelStats.success ? (channelStats.data as any) : null;
        const userData = userStats.success ? (userStats.data as any) : null;

        // Check if the inner data has success: true
        const channelOk = channelData?.success !== false;
        const userOk = userData?.success !== false;

        if ((channelOk && channelData) || (userOk && userData)) {
          // Format cache age as relative time
          let lastSync: string | undefined;
          const cacheAgeSeconds = channelData?.cache_age_seconds || userData?.cache_age_seconds;
          if (cacheAgeSeconds) {
            if (cacheAgeSeconds < 60) {
              lastSync = `${Math.round(cacheAgeSeconds)}s ago`;
            } else if (cacheAgeSeconds < 3600) {
              lastSync = `${Math.round(cacheAgeSeconds / 60)}m ago`;
            } else if (cacheAgeSeconds < 86400) {
              lastSync = `${Math.round(cacheAgeSeconds / 3600)}h ago`;
            } else {
              lastSync = `${Math.round(cacheAgeSeconds / 86400)}d ago`;
            }
          }

          this.slackDatabase = {
            channels_count: channelData?.total_channels || 0,
            users_count: userData?.total_users || 0,
            messages_count: 0, // Messages aren't cached long-term
            last_sync: lastSync,
            size: undefined,
          };
          logger.log(`Loaded Slack database stats: ${this.slackDatabase.channels_count} channels, ${this.slackDatabase.users_count} users`);
        } else {
          logger.log(`No Slack cache data available - channelData: ${JSON.stringify(channelData)}, userData: ${JSON.stringify(userData)}`);
        }
      } catch (e) {
        logger.log(`Slack cache stats error: ${e}`);
      }

      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  getContent(): string {
    return `
      <!-- Memory Browser -->
      <div class="section memory-browser-section">
        <div class="memory-browser-header">
          <div class="memory-tabs">
            ${this.getCategoriesHtml()}
          </div>
        </div>
        <div class="memory-browser">
          <div class="memory-sidebar">
            <div class="memory-files">
              ${this.getFilesListHtml()}
            </div>
          </div>
          <div class="memory-content">
            ${this.getFileContentHtml()}
          </div>
        </div>
      </div>

      <!-- Vector Databases (Code Search) -->
      <div class="section">
        <div class="section-title">🔍 Vector Databases</div>
        ${this.getVectorDatabasesHtml()}
      </div>

      <!-- Slack Database -->
      <div class="section">
        <div class="section-title">💬 Slack Database</div>
        ${this.getSlackDatabaseHtml()}
      </div>

      <!-- Session Logs -->
      <div class="section">
        <div class="section-title">📜 Session Logs</div>
        <div class="session-logs-list">
          ${this.sessionLogs.length > 0 ? this.sessionLogs.map((log) => this.getSessionLogHtml(log)).join("") : this.getEmptyStateHtml("📜", "No session logs")}
        </div>
      </div>

      <!-- Learned Patterns -->
      <div class="section collapsible">
        <div class="section-title" data-toggle="patterns">
          📚 Learned Patterns (${this.learnedPatterns.length})
          <span class="collapse-icon">▼</span>
        </div>
        <div class="section-content" id="patterns-content">
          ${this.learnedPatterns.length > 0 ? this.learnedPatterns.map((p) => this.getPatternHtml(p)).join("") : this.getEmptyStateHtml("📚", "No learned patterns")}
        </div>
      </div>

      <!-- Tool Fixes -->
      <div class="section collapsible">
        <div class="section-title" data-toggle="fixes">
          🔧 Tool Fixes (${this.toolFixes.length})
          <span class="collapse-icon">▼</span>
        </div>
        <div class="section-content" id="fixes-content">
          ${this.toolFixes.length > 0 ? this.toolFixes.map((f) => this.getToolFixHtml(f)).join("") : this.getEmptyStateHtml("🔧", "No tool fixes")}
        </div>
      </div>
    `;
  }

  private getCategoriesHtml(): string {
    const categories = [
      { id: "state", label: "State", icon: "📊", description: "Project state & context" },
      { id: "learned", label: "Learned", icon: "🧠", description: "Patterns & knowledge" },
      { id: "session", label: "Sessions", icon: "💬", description: "Session history" },
      { id: "style", label: "Style", icon: "🎨", description: "Code style preferences" },
    ];

    return categories
      .map(
        (cat) => `
        <button class="memory-tab ${this.selectedCategory === cat.id ? "active" : ""}"
                data-category="${cat.id}"
                title="${cat.description}">
          <span class="memory-tab-icon">${cat.icon}</span>
          <span class="memory-tab-label">${cat.label}</span>
        </button>
      `
      )
      .join("");
  }

  private getFilesListHtml(): string {
    const fileCount = this.memoryFiles.length;
    const header = `<div class="memory-files-header">${fileCount} file${fileCount !== 1 ? 's' : ''}</div>`;
    
    if (this.memoryFiles.length === 0) {
      return header + '<div class="memory-files-empty">No files in this category</div>';
    }

    const files = this.memoryFiles
      .map(
        (file) => `
        <div class="memory-file ${this.selectedFile === file.path ? "selected" : ""}"
             data-file="${file.path}">
          <span class="memory-file-icon">${file.type === "directory" ? "📁" : "📄"}</span>
          <span class="memory-file-name">${this.escapeHtml(file.name)}</span>
        </div>
      `
      )
      .join("");
    
    return header + `<div class="memory-files-list">${files}</div>`;
  }

  private getFileContentHtml(): string {
    if (!this.selectedFile) {
      return this.getEmptyStateHtml("📄", "Select a file to view");
    }

    if (!this.fileContent) {
      return this.getLoadingHtml("Loading file...");
    }

    return `
      <div class="memory-file-header">
        <span class="memory-file-path">${this.escapeHtml(this.selectedFile)}</span>
        <button class="btn btn-xs" data-action="editMemoryFile" data-file="${this.selectedFile}">✏️ Edit</button>
      </div>
      <pre class="memory-file-content">${this.escapeHtml(this.fileContent)}</pre>
    `;
  }

  private getSessionLogHtml(log: SessionLog): string {
    return `
      <div class="session-log-item">
        <div class="session-log-time">${this.formatRelativeTime(log.timestamp)}</div>
        <div class="session-log-action">${this.escapeHtml(log.action)}</div>
        <div class="session-log-details">${this.escapeHtml(log.details)}</div>
        ${log.session_name ? `<div class="session-log-session">${this.escapeHtml(log.session_name)}</div>` : ""}
      </div>
    `;
  }

  private getPatternHtml(pattern: LearnedPattern): string {
    // Map daemon fields to interface fields (daemon uses: type, count, lastUsed)
    const usageCount = pattern.usage_count ?? pattern.count ?? 0;
    const context = pattern.context ?? pattern.type ?? "unknown";
    const learnedAt = pattern.learned_at ?? pattern.lastUsed ?? "";

    return `
      <div class="learned-pattern-item">
        <div class="pattern-header">
          <span class="pattern-name">${this.escapeHtml(pattern.pattern || "Unknown pattern")}</span>
          <span class="pattern-usage">Used ${usageCount}x</span>
        </div>
        <div class="pattern-context">${this.escapeHtml(context)}</div>
        <div class="pattern-time">Learned ${learnedAt ? this.formatRelativeTime(learnedAt) : "unknown"}</div>
      </div>
    `;
  }

  private getToolFixHtml(fix: ToolFix): string {
    const appliedCount = fix.applied_count ?? 0;
    const learnedAt = fix.learned_at || "";
    const verified = fix.verified ? "✓ Verified" : "";

    return `
      <div class="tool-fix-item">
        <div class="fix-header">
          <span class="fix-tool">${this.escapeHtml(fix.tool_name || "Unknown tool")}</span>
          <span class="fix-applied">${verified} ${appliedCount > 0 ? `Applied ${appliedCount}x` : ""}</span>
        </div>
        <div class="fix-error">${this.escapeHtml(fix.error_pattern || "")}</div>
        <div class="fix-description">${this.escapeHtml(fix.fix_description || "")}</div>
        ${fix.root_cause ? `<div class="fix-root-cause">Root cause: ${this.escapeHtml(fix.root_cause)}</div>` : ""}
        <div class="fix-time">${learnedAt ? `Learned ${this.formatRelativeTime(learnedAt)}` : ""}</div>
      </div>
    `;
  }

  private getVectorDatabasesHtml(): string {
    if (this.vectorDatabases.length === 0) {
      return this.getEmptyStateHtml("🔍", "No vector databases indexed");
    }

    return `
      <div class="vector-databases-grid">
        ${this.vectorDatabases.map((db) => `
          <div class="vector-db-card ${db.status}">
            <div class="vector-db-header">
              <span class="vector-db-name">${this.escapeHtml(db.name)}</span>
              <span class="vector-db-status status-${db.status}">${db.status}</span>
            </div>
            <div class="vector-db-type">${this.escapeHtml(db.type)}</div>
            <div class="vector-db-stats">
              <span>📄 ${db.document_count.toLocaleString()} documents</span>
              ${db.size ? `<span>💾 ${db.size}</span>` : ""}
            </div>
            ${db.last_updated ? `<div class="vector-db-updated">Updated ${this.formatRelativeTime(db.last_updated)}</div>` : ""}
            <div class="vector-db-actions">
              <button class="btn btn-xs" data-action="reindexVectorDb" data-db="${this.escapeHtml(db.name)}">🔄 Reindex</button>
              <button class="btn btn-xs" data-action="searchVectorDb" data-db="${this.escapeHtml(db.name)}">🔍 Search</button>
            </div>
          </div>
        `).join("")}
      </div>
    `;
  }

  private getSlackDatabaseHtml(): string {
    if (!this.slackDatabase) {
      return this.getEmptyStateHtml("💬", "Slack database not available");
    }

    const db = this.slackDatabase;
    return `
      <div class="slack-db-card">
        <div class="slack-db-stats">
          <div class="slack-db-stat">
            <div class="slack-db-stat-value">${db.channels_count.toLocaleString()}</div>
            <div class="slack-db-stat-label">Channels</div>
          </div>
          <div class="slack-db-stat">
            <div class="slack-db-stat-value">${db.users_count.toLocaleString()}</div>
            <div class="slack-db-stat-label">Users</div>
          </div>
          <div class="slack-db-stat">
            <div class="slack-db-stat-value">${db.messages_count.toLocaleString()}</div>
            <div class="slack-db-stat-label">Messages</div>
          </div>
          ${db.size ? `
            <div class="slack-db-stat">
              <div class="slack-db-stat-value">${db.size}</div>
              <div class="slack-db-stat-label">Size</div>
            </div>
          ` : ""}
        </div>
        ${db.last_sync ? `<div class="slack-db-sync">Last synced ${this.formatRelativeTime(db.last_sync)}</div>` : ""}
        <div class="slack-db-actions">
          <button class="btn btn-xs btn-primary" data-action="syncSlackDb">🔄 Sync Now</button>
          <button class="btn btn-xs" data-action="searchSlackDb">🔍 Search Messages</button>
        </div>
      </div>
    `;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return `
      // Use event delegation for memory tab - attach to document to survive re-renders
      document.addEventListener('click', (e) => {
        // Memory category tab selection
        const memoryTab = e.target.closest('.memory-tab');
        if (memoryTab) {
          const category = memoryTab.dataset.category;
          if (category) {
            console.log('[MemoryTab] Category clicked:', category);
            vscode.postMessage({ command: 'selectMemoryCategory', category });
          }
          return;
        }

        // File selection
        const memoryFile = e.target.closest('.memory-file');
        if (memoryFile) {
          const file = memoryFile.dataset.file;
          if (file) {
            console.log('[MemoryTab] File clicked:', file);
            vscode.postMessage({ command: 'selectMemoryFile', file });
          }
          return;
        }

        // Edit file button
        const editBtn = e.target.closest('[data-action="editMemoryFile"]');
        if (editBtn) {
          const file = editBtn.dataset.file;
          if (file) {
            console.log('[MemoryTab] Edit clicked:', file);
            vscode.postMessage({ command: 'editMemoryFile', file });
          }
          return;
        }

        // Collapsible sections
        const collapseTitle = e.target.closest('.collapsible .section-title');
        if (collapseTitle) {
          const section = collapseTitle.closest('.collapsible');
          if (section) {
            section.classList.toggle('collapsed');
          }
          return;
        }
      });
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;
    logger.log(`handleMessage: ${msgType}, message: ${JSON.stringify(message)}`);

    switch (msgType) {
      case "selectMemoryCategory":
        logger.log(`Selecting category: ${message.category}`);
        this.selectedCategory = message.category;
        this.selectedFile = null;
        this.fileContent = null;
        await this.refresh();
        return true;

      case "selectMemoryFile":
        logger.log(`Selecting file: ${message.file}`);
        await this.loadFile(message.file);
        return true;

      case "editMemoryFile":
        await this.editFile(message.file);
        return true;

      case "refreshMemory":
        await this.refresh();
        return true;

      default:
        return false;
    }
  }

  private async loadFile(filePath: string): Promise<void> {
    logger.log(`loadFile: ${filePath}`);
    this.selectedFile = filePath;
    try {
      const result = await dbus.memory_readFile(filePath);
      logger.log(`memory_readFile result: success=${result.success}, error=${result.error || 'none'}`);
      if (result.success && result.data) {
        const data = result.data as any;
        const content = data.content;
        // Content is a parsed YAML object, convert to formatted string for display
        if (content === null || content === undefined) {
          this.fileContent = "(empty)";
        } else if (typeof content === 'string') {
          this.fileContent = content;
        } else {
          // Format as YAML-like JSON for readability
          this.fileContent = JSON.stringify(content, null, 2);
        }
        logger.log(`File content loaded: ${(this.fileContent || "").length} chars`);
      } else {
        this.fileContent = `Error: ${result.error || 'Unknown error'}`;
      }
    } catch (error) {
      logger.error("Error loading file", error);
      this.fileContent = `Error loading file: ${error}`;
    }
    this.notifyNeedsRender();
  }

  private async editFile(filePath: string): Promise<void> {
    // Open file in editor
    const memoryDir = await dbus.memory_getMemoryDir();
    if (memoryDir.success && memoryDir.data) {
      const fullPath = `${(memoryDir.data as any).path}/${filePath}`;
      const doc = await vscode.workspace.openTextDocument(fullPath);
      await vscode.window.showTextDocument(doc);
    }
  }
}
