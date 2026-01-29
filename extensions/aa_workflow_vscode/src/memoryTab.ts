/**
 * Memory Tab - Comprehensive view of the AI Workflow memory system
 *
 * Shows a hierarchical view of all memory categories:
 *
 * MEMORY EXPLORER
 * ├── 📊 State (Current Work)
 * │   ├── Active Issues (2)
 * │   │   ├── AAP-61661 - Enable pytest-xdist...
 * │   │   └── AAP-61214 - Fix billing...
 * │   ├── Open MRs (8)
 * │   │   ├── !1491 - AAP-58394 fix(billing)
 * │   │   └── ...
 * │   ├── Follow-ups (1)
 * │   └── Discovered Work (3)
 * ├── 🌍 Environments
 * │   ├── Stage: degraded (2 alerts)
 * │   ├── Production: degraded
 * │   ├── Ephemeral (3 namespaces)
 * │   └── Konflux: unknown
 * ├── 📚 Learned Patterns
 * │   ├── Error Patterns (8)
 * │   ├── Auth Patterns (3)
 * │   ├── Pipeline Patterns (4)
 * │   ├── Tool Failures (25)
 * │   └── Tool Fixes (3)
 * ├── 📖 Knowledge Base
 * │   ├── Projects (5)
 * │   │   ├── automation-analytics-backend
 * │   │   │   ├── developer
 * │   │   │   ├── devops
 * │   │   │   ├── incident
 * │   │   │   └── release
 * │   │   └── ...
 * │   └── Last Bootstrap: 2026-01-20
 * └── 📈 Statistics
 *     ├── Vector Reindexes: 48
 *     ├── Knowledge Bootstraps: 2
 *     └── Work Analyses: 13
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import * as yaml from "js-yaml";
import { getMemoryDir } from "./paths";
import { createLogger } from "./logger";

const logger = createLogger("MemoryTab");

// Tree item types for context menu handling
type MemoryItemType =
  | "category"
  | "subcategory"
  | "item"
  | "detail"
  | "action"
  | "file";

export class MemoryTreeItem extends vscode.TreeItem {
  public data?: any;
  public filePath?: string;

  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly itemType: MemoryItemType,
    data?: any,
    filePath?: string
  ) {
    super(label, collapsibleState);
    this.contextValue = itemType;
    this.data = data;
    this.filePath = filePath;
  }
}

interface SessionInfo {
  session_id: string;
  name: string | null;
  persona: string;
  project: string | null;
  issue_key: string | null;
  started_at: string | null;
  last_activity: string | null;
  tool_call_count: number;
  is_active: boolean;
}

interface MemoryStats {
  state: {
    activeIssues: number;
    openMrs: number;
    followUps: number;
    discoveredWork: number;
  };
  environments: {
    stage: { status: string; alerts: number };
    production: { status: string; alerts: number };
    ephemeral: { namespaces: number };
    konflux: { status: string };
  };
  learned: {
    errorPatterns: number;
    authPatterns: number;
    pipelinePatterns: number;
    toolFailures: number;
    toolFixes: number;
    dailyPatterns: number;
  };
  knowledge: {
    projects: string[];
    personas: string[];
    lastBootstrap: string | null;
  };
  statistics: {
    vectorReindexes: number;
    knowledgeBootstraps: number;
    workAnalyses: number;
  };
  sessions: {
    total: number;
    active: number;
    recentSessions: SessionInfo[];
  };
}

export class MemoryTreeProvider
  implements vscode.TreeDataProvider<MemoryTreeItem>
{
  private _onDidChangeTreeData: vscode.EventEmitter<
    MemoryTreeItem | undefined | null | void
  > = new vscode.EventEmitter<MemoryTreeItem | undefined | null | void>();
  readonly onDidChangeTreeData: vscode.Event<
    MemoryTreeItem | undefined | null | void
  > = this._onDidChangeTreeData.event;

  private memoryDir: string;
  private cachedStats: MemoryStats | null = null;

  constructor() {
    this.memoryDir = getMemoryDir();
  }

  refresh(): void {
    this.cachedStats = null;
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: MemoryTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: MemoryTreeItem): Promise<MemoryTreeItem[]> {
    if (!element) {
      return this.getRootItems();
    }

    // Get children based on parent
    const label = element.label as string;

    if (label.includes("State")) {
      return this.getStateItems();
    } else if (label.includes("Environments")) {
      return this.getEnvironmentItems();
    } else if (label.includes("Sessions")) {
      return this.getSessionItems();
    } else if (label.includes("Learned")) {
      return this.getLearnedItems();
    } else if (label.includes("Knowledge")) {
      return this.getKnowledgeItems();
    } else if (label.includes("Statistics")) {
      return this.getStatisticsItems();
    } else if (label.includes("Memory Actions")) {
      return this.getMemoryActionItems();
    } else if (element.data?.children) {
      return element.data.children;
    } else if (element.data?.items) {
      return this.getItemDetails(element.data.items, element.data.type);
    }

    return [];
  }

  private loadStats(): MemoryStats {
    if (this.cachedStats) {
      return this.cachedStats;
    }

    const stats: MemoryStats = {
      state: { activeIssues: 0, openMrs: 0, followUps: 0, discoveredWork: 0 },
      environments: {
        stage: { status: "unknown", alerts: 0 },
        production: { status: "unknown", alerts: 0 },
        ephemeral: { namespaces: 0 },
        konflux: { status: "unknown" },
      },
      learned: {
        errorPatterns: 0,
        authPatterns: 0,
        pipelinePatterns: 0,
        toolFailures: 0,
        toolFixes: 0,
        dailyPatterns: 0,
      },
      knowledge: { projects: [], personas: [], lastBootstrap: null },
      statistics: { vectorReindexes: 0, knowledgeBootstraps: 0, workAnalyses: 0 },
      sessions: { total: 0, active: 0, recentSessions: [] },
    };

    try {
      // Load current_work.yaml
      const currentWorkPath = path.join(this.memoryDir, "state", "current_work.yaml");
      if (fs.existsSync(currentWorkPath)) {
        const content = yaml.load(fs.readFileSync(currentWorkPath, "utf-8")) as any;
        stats.state.activeIssues = content?.active_issues?.length || 0;
        stats.state.openMrs = content?.open_mrs?.length || 0;
        stats.state.followUps = content?.follow_ups?.length || 0;
        stats.state.discoveredWork = content?.discovered_work?.length || 0;
      }

      // Load environments.yaml
      const envPath = path.join(this.memoryDir, "state", "environments.yaml");
      if (fs.existsSync(envPath)) {
        const content = yaml.load(fs.readFileSync(envPath, "utf-8")) as any;
        const envs = content?.environments || {};

        stats.environments.stage.status = envs?.stage?.status || "unknown";
        stats.environments.stage.alerts = envs?.stage?.alerts?.length || 0;
        stats.environments.production.status = envs?.production?.status || "unknown";
        stats.environments.production.alerts = envs?.production?.alerts?.length || 0;
        stats.environments.ephemeral.namespaces = envs?.ephemeral?.active_namespaces?.length || 0;
        stats.environments.konflux.status = envs?.konflux?.status || "unknown";

        // Also check top-level stage.alerts
        if (content?.["stage.alerts"]) {
          stats.environments.stage.alerts = content["stage.alerts"].length;
        }
      }

      // Load patterns.yaml
      const patternsPath = path.join(this.memoryDir, "learned", "patterns.yaml");
      if (fs.existsSync(patternsPath)) {
        const content = yaml.load(fs.readFileSync(patternsPath, "utf-8")) as any;
        stats.learned.errorPatterns = content?.error_patterns?.length || 0;
        stats.learned.authPatterns = content?.auth_patterns?.length || 0;
        stats.learned.pipelinePatterns = content?.pipeline_patterns?.length || 0;
        stats.learned.dailyPatterns = content?.daily_patterns?.length || 0;
        stats.statistics.vectorReindexes = content?.vector_reindexes?.length || 0;
        stats.statistics.knowledgeBootstraps = content?.knowledge_bootstraps_all?.length || 0;
        stats.statistics.workAnalyses = content?.work_analyses?.length || 0;
      }

      // Load tool_failures.yaml
      const failuresPath = path.join(this.memoryDir, "learned", "tool_failures.yaml");
      if (fs.existsSync(failuresPath)) {
        const content = yaml.load(fs.readFileSync(failuresPath, "utf-8")) as any;
        stats.learned.toolFailures = content?.failures?.length || 0;
        stats.learned.toolFixes = content?.learned_fixes?.length || 0;
      }

      // Load knowledge.yaml
      const knowledgePath = path.join(this.memoryDir, "state", "knowledge.yaml");
      if (fs.existsSync(knowledgePath)) {
        const content = yaml.load(fs.readFileSync(knowledgePath, "utf-8")) as any;
        stats.knowledge.projects = Object.keys(content?.projects || {});
        stats.knowledge.personas = content?.last_full_bootstrap?.personas || [];
        stats.knowledge.lastBootstrap = content?.last_full_bootstrap?.timestamp || null;
      }

      // Scan knowledge/personas directory for projects
      const personasDir = path.join(this.memoryDir, "knowledge", "personas");
      if (fs.existsSync(personasDir)) {
        const personas = fs.readdirSync(personasDir).filter(f =>
          fs.statSync(path.join(personasDir, f)).isDirectory() && !f.startsWith(".")
        );
        if (personas.length > 0) {
          stats.knowledge.personas = personas;
        }
      }

      // Load sessions from workspace_states.json (centralized in ~/.config/aa-workflow/)
      const workspaceStatesPath = path.join(os.homedir(), ".config", "aa-workflow", "workspace_states.json");
      if (fs.existsSync(workspaceStatesPath)) {
        const content = JSON.parse(fs.readFileSync(workspaceStatesPath, "utf-8"));
        const workspaces = content?.workspaces || {};

        // Collect all sessions from all workspaces
        const allSessions: SessionInfo[] = [];
        let activeCount = 0;

        for (const [uri, workspace] of Object.entries(workspaces)) {
          const ws = workspace as any;
          const activeSessionId = ws.active_session_id;
          const sessions = ws.sessions || {};

          for (const [sessionId, session] of Object.entries(sessions)) {
            const s = session as any;
            const isActive = sessionId === activeSessionId;
            if (isActive) activeCount++;

            allSessions.push({
              session_id: s.session_id,
              name: s.name,
              persona: s.persona,
              project: s.project,
              issue_key: s.issue_key,
              started_at: s.started_at,
              last_activity: s.last_activity,
              tool_call_count: s.tool_call_count || 0,
              is_active: isActive,
            });
          }
        }

        // Sort by last_activity descending (most recent first)
        allSessions.sort((a, b) => {
          const aTime = a.last_activity ? new Date(a.last_activity).getTime() : 0;
          const bTime = b.last_activity ? new Date(b.last_activity).getTime() : 0;
          return bTime - aTime;
        });

        stats.sessions.total = allSessions.length;
        stats.sessions.active = activeCount;
        stats.sessions.recentSessions = allSessions.slice(0, 15); // Keep top 15
      }

    } catch (e) {
      logger.error("Failed to load memory stats", e);
    }

    this.cachedStats = stats;
    return stats;
  }

  private getRootItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];

    // State (Current Work)
    const stateItem = new MemoryTreeItem(
      "State",
      vscode.TreeItemCollapsibleState.Expanded,
      "category"
    );
    stateItem.iconPath = new vscode.ThemeIcon(
      "database",
      new vscode.ThemeColor("charts.blue")
    );
    const totalState = stats.state.activeIssues + stats.state.openMrs +
                       stats.state.followUps + stats.state.discoveredWork;
    stateItem.description = `${totalState} items`;
    stateItem.tooltip = "Current work state: active issues, MRs, follow-ups";
    items.push(stateItem);

    // Environments
    const envItem = new MemoryTreeItem(
      "Environments",
      vscode.TreeItemCollapsibleState.Expanded,
      "category"
    );
    const hasAlerts = stats.environments.stage.alerts > 0 ||
                      stats.environments.production.alerts > 0;
    envItem.iconPath = new vscode.ThemeIcon(
      hasAlerts ? "server-environment" : "server",
      hasAlerts ? new vscode.ThemeColor("charts.red") : new vscode.ThemeColor("charts.green")
    );
    envItem.description = hasAlerts
      ? `${stats.environments.stage.alerts + stats.environments.production.alerts} alerts`
      : "All healthy";
    items.push(envItem);

    // Sessions
    const sessionsItem = new MemoryTreeItem(
      "Sessions",
      stats.sessions.total > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "category"
    );
    sessionsItem.iconPath = new vscode.ThemeIcon(
      "history",
      stats.sessions.active > 0 ? new vscode.ThemeColor("charts.green") : undefined
    );
    sessionsItem.description = stats.sessions.total > 0
      ? `${stats.sessions.total} total, ${stats.sessions.active} active`
      : "No sessions";
    sessionsItem.tooltip = "Recent AI assistant sessions from MCP server";
    items.push(sessionsItem);

    // Learned Patterns
    const learnedItem = new MemoryTreeItem(
      "Learned Patterns",
      vscode.TreeItemCollapsibleState.Collapsed,
      "category"
    );
    learnedItem.iconPath = new vscode.ThemeIcon(
      "lightbulb",
      new vscode.ThemeColor("charts.yellow")
    );
    const totalLearned = stats.learned.errorPatterns + stats.learned.authPatterns +
                         stats.learned.pipelinePatterns + stats.learned.toolFailures;
    learnedItem.description = `${totalLearned} patterns`;
    items.push(learnedItem);

    // Knowledge Base
    const knowledgeItem = new MemoryTreeItem(
      "Knowledge Base",
      vscode.TreeItemCollapsibleState.Collapsed,
      "category"
    );
    knowledgeItem.iconPath = new vscode.ThemeIcon(
      "book",
      new vscode.ThemeColor("charts.purple")
    );
    knowledgeItem.description = `${stats.knowledge.projects.length} projects`;
    items.push(knowledgeItem);

    // Statistics
    const statsItem = new MemoryTreeItem(
      "Statistics",
      vscode.TreeItemCollapsibleState.Collapsed,
      "category"
    );
    statsItem.iconPath = new vscode.ThemeIcon(
      "graph",
      new vscode.ThemeColor("charts.cyan")
    );
    statsItem.description = "Usage & indexing";
    items.push(statsItem);

    // Quick Actions
    const actionsItem = new MemoryTreeItem(
      "Memory Actions",
      vscode.TreeItemCollapsibleState.Collapsed,
      "category"
    );
    actionsItem.iconPath = new vscode.ThemeIcon(
      "tools",
      new vscode.ThemeColor("charts.orange")
    );
    actionsItem.description = "View, edit, cleanup";
    items.push(actionsItem);

    return items;
  }

  private getStateItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];
    const currentWorkPath = path.join(this.memoryDir, "state", "current_work.yaml");

    // Load actual data for details
    let currentWork: any = {};
    try {
      if (fs.existsSync(currentWorkPath)) {
        currentWork = yaml.load(fs.readFileSync(currentWorkPath, "utf-8")) as any || {};
      }
    } catch (e) {
      logger.error("Failed to load current_work.yaml", e);
    }

    // Active Issues
    const issuesItem = new MemoryTreeItem(
      `Active Issues (${stats.state.activeIssues})`,
      stats.state.activeIssues > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: currentWork.active_issues || [], type: "issue" }
    );
    issuesItem.iconPath = new vscode.ThemeIcon(
      "issues",
      stats.state.activeIssues > 0 ? new vscode.ThemeColor("charts.blue") : undefined
    );
    items.push(issuesItem);

    // Open MRs
    const mrsItem = new MemoryTreeItem(
      `Open MRs (${stats.state.openMrs})`,
      stats.state.openMrs > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: currentWork.open_mrs || [], type: "mr" }
    );
    mrsItem.iconPath = new vscode.ThemeIcon(
      "git-pull-request",
      stats.state.openMrs > 0 ? new vscode.ThemeColor("charts.green") : undefined
    );
    items.push(mrsItem);

    // Follow-ups
    const followUpsItem = new MemoryTreeItem(
      `Follow-ups (${stats.state.followUps})`,
      stats.state.followUps > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: currentWork.follow_ups || [], type: "followup" }
    );
    followUpsItem.iconPath = new vscode.ThemeIcon(
      "checklist",
      stats.state.followUps > 0 ? new vscode.ThemeColor("charts.yellow") : undefined
    );
    items.push(followUpsItem);

    // Discovered Work
    const discoveredItem = new MemoryTreeItem(
      `Discovered Work (${stats.state.discoveredWork})`,
      stats.state.discoveredWork > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: currentWork.discovered_work || [], type: "discovered" }
    );
    discoveredItem.iconPath = new vscode.ThemeIcon(
      "search",
      stats.state.discoveredWork > 0 ? new vscode.ThemeColor("charts.purple") : undefined
    );
    items.push(discoveredItem);

    // Last updated
    if (currentWork.last_updated) {
      const lastUpdated = new MemoryTreeItem(
        `Last updated: ${this.formatDate(currentWork.last_updated)}`,
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      lastUpdated.iconPath = new vscode.ThemeIcon("clock");
      items.push(lastUpdated);
    }

    // Open file action
    const openFileItem = new MemoryTreeItem(
      "Open current_work.yaml",
      vscode.TreeItemCollapsibleState.None,
      "action",
      null,
      currentWorkPath
    );
    openFileItem.iconPath = new vscode.ThemeIcon("go-to-file");
    openFileItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open File",
      arguments: [currentWorkPath],
    };
    items.push(openFileItem);

    return items;
  }

  private getEnvironmentItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];
    const envPath = path.join(this.memoryDir, "state", "environments.yaml");

    // Load actual data
    let envData: any = {};
    try {
      if (fs.existsSync(envPath)) {
        envData = yaml.load(fs.readFileSync(envPath, "utf-8")) as any || {};
      }
    } catch (e) {
      logger.error("Failed to load environments.yaml", e);
    }

    // Stage
    const stageItem = new MemoryTreeItem(
      `Stage: ${stats.environments.stage.status}`,
      vscode.TreeItemCollapsibleState.None,
      "item"
    );
    stageItem.iconPath = new vscode.ThemeIcon(
      stats.environments.stage.alerts > 0 ? "warning" : "pass",
      stats.environments.stage.alerts > 0
        ? new vscode.ThemeColor("charts.yellow")
        : new vscode.ThemeColor("charts.green")
    );
    if (stats.environments.stage.alerts > 0) {
      stageItem.description = `${stats.environments.stage.alerts} alert(s)`;
      stageItem.tooltip = "Click to investigate stage alerts";
      stageItem.command = {
        command: "aa-workflow.investigateAlert",
        title: "Investigate Alerts",
      };
    }
    items.push(stageItem);

    // Production
    const prodItem = new MemoryTreeItem(
      `Production: ${stats.environments.production.status}`,
      vscode.TreeItemCollapsibleState.None,
      "item"
    );
    prodItem.iconPath = new vscode.ThemeIcon(
      stats.environments.production.alerts > 0 ? "flame" : "pass",
      stats.environments.production.alerts > 0
        ? new vscode.ThemeColor("charts.red")
        : new vscode.ThemeColor("charts.green")
    );
    if (stats.environments.production.alerts > 0) {
      prodItem.description = `${stats.environments.production.alerts} alert(s)`;
      prodItem.tooltip = "Click to investigate production alerts";
      prodItem.command = {
        command: "aa-workflow.investigateAlert",
        title: "Investigate Alerts",
      };
    }
    items.push(prodItem);

    // Ephemeral
    const ephemeralItem = new MemoryTreeItem(
      `Ephemeral Namespaces`,
      stats.environments.ephemeral.namespaces > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: envData?.environments?.ephemeral?.active_namespaces || [], type: "namespace" }
    );
    ephemeralItem.iconPath = new vscode.ThemeIcon(
      "cloud",
      stats.environments.ephemeral.namespaces > 0
        ? new vscode.ThemeColor("charts.purple")
        : undefined
    );
    ephemeralItem.description = `${stats.environments.ephemeral.namespaces} active`;
    items.push(ephemeralItem);

    // Konflux
    const konfluxItem = new MemoryTreeItem(
      `Konflux: ${stats.environments.konflux.status}`,
      vscode.TreeItemCollapsibleState.None,
      "item"
    );
    konfluxItem.iconPath = new vscode.ThemeIcon(
      "package",
      stats.environments.konflux.status === "active"
        ? new vscode.ThemeColor("charts.green")
        : undefined
    );
    items.push(konfluxItem);

    // Open file action
    const openFileItem = new MemoryTreeItem(
      "Open environments.yaml",
      vscode.TreeItemCollapsibleState.None,
      "action",
      null,
      envPath
    );
    openFileItem.iconPath = new vscode.ThemeIcon("go-to-file");
    openFileItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open File",
      arguments: [envPath],
    };
    items.push(openFileItem);

    return items;
  }

  private getSessionItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];

    if (stats.sessions.recentSessions.length === 0) {
      const emptyItem = new MemoryTreeItem(
        "No sessions found",
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      emptyItem.description = "Start a session with session_start()";
      items.push(emptyItem);
      return items;
    }

    // Show recent sessions
    for (const session of stats.sessions.recentSessions) {
      const displayName = session.name || session.session_id.substring(0, 8);
      const sessionItem = new MemoryTreeItem(
        this.truncate(displayName, 40),
        vscode.TreeItemCollapsibleState.None,
        "item",
        session
      );

      // Icon based on active status
      sessionItem.iconPath = new vscode.ThemeIcon(
        session.is_active ? "debug-start" : "history",
        session.is_active ? new vscode.ThemeColor("charts.green") : undefined
      );

      // Description shows persona and time
      const timeAgo = session.last_activity ? this.formatDate(session.last_activity) : "unknown";
      sessionItem.description = `${session.persona} • ${timeAgo}`;

      // Rich tooltip
      sessionItem.tooltip = new vscode.MarkdownString(
        `**${session.name || "Unnamed Session"}**\n\n` +
        `| | |\n|---|---|\n` +
        `| Status | ${session.is_active ? "🟢 Active" : "⚪ Inactive"} |\n` +
        `| Persona | ${session.persona} |\n` +
        `| Project | ${session.project || "N/A"} |\n` +
        `| Issue | ${session.issue_key || "N/A"} |\n` +
        `| Tool Calls | ${session.tool_call_count} |\n` +
        `| Started | ${session.started_at ? this.formatDate(session.started_at) : "N/A"} |\n` +
        `| Last Activity | ${timeAgo} |\n\n` +
        `Session ID: \`${session.session_id}\`\n\n` +
        `_Click to ${session.is_active ? "view session info" : "resume this session"}_`
      );

      // Click to resume or view session
      sessionItem.command = {
        command: "aa-workflow.sessionAction",
        title: session.is_active ? "View Session" : "Resume Session",
        arguments: [session.session_id, session.is_active],
      };

      items.push(sessionItem);
    }

    // Show total count if there are more
    if (stats.sessions.total > stats.sessions.recentSessions.length) {
      const moreItem = new MemoryTreeItem(
        `... and ${stats.sessions.total - stats.sessions.recentSessions.length} more sessions`,
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      moreItem.iconPath = new vscode.ThemeIcon("ellipsis");
      moreItem.command = {
        command: "aa-workflow.listAllSessions",
        title: "List All Sessions",
      };
      items.push(moreItem);
    }

    // Action to start new session
    const newSessionItem = new MemoryTreeItem(
      "Start New Session",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    newSessionItem.iconPath = new vscode.ThemeIcon("add", new vscode.ThemeColor("charts.green"));
    newSessionItem.description = "session_start()";
    newSessionItem.command = {
      command: "aa-workflow.startNewSession",
      title: "Start New Session",
    };
    items.push(newSessionItem);

    // Open workspace_states.json (centralized in ~/.config/aa-workflow/)
    const workspaceStatesPath = path.join(os.homedir(), ".config", "aa-workflow", "workspace_states.json");
    const openFileItem = new MemoryTreeItem(
      "Open workspace_states.json",
      vscode.TreeItemCollapsibleState.None,
      "action",
      null,
      workspaceStatesPath
    );
    openFileItem.iconPath = new vscode.ThemeIcon("go-to-file");
    openFileItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open File",
      arguments: [workspaceStatesPath],
    };
    items.push(openFileItem);

    return items;
  }

  private getLearnedItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];
    const patternsPath = path.join(this.memoryDir, "learned", "patterns.yaml");
    const failuresPath = path.join(this.memoryDir, "learned", "tool_failures.yaml");

    // Load actual data
    let patterns: any = {};
    let failures: any = {};
    try {
      if (fs.existsSync(patternsPath)) {
        patterns = yaml.load(fs.readFileSync(patternsPath, "utf-8")) as any || {};
      }
      if (fs.existsSync(failuresPath)) {
        failures = yaml.load(fs.readFileSync(failuresPath, "utf-8")) as any || {};
      }
    } catch (e) {
      logger.error("Failed to load learned patterns", e);
    }

    // Error Patterns
    const errorItem = new MemoryTreeItem(
      `Error Patterns (${stats.learned.errorPatterns})`,
      stats.learned.errorPatterns > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: patterns.error_patterns || [], type: "pattern" }
    );
    errorItem.iconPath = new vscode.ThemeIcon("bug", new vscode.ThemeColor("charts.red"));
    items.push(errorItem);

    // Auth Patterns
    const authItem = new MemoryTreeItem(
      `Auth Patterns (${stats.learned.authPatterns})`,
      stats.learned.authPatterns > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: patterns.auth_patterns || [], type: "pattern" }
    );
    authItem.iconPath = new vscode.ThemeIcon("key", new vscode.ThemeColor("charts.yellow"));
    items.push(authItem);

    // Pipeline Patterns
    const pipelineItem = new MemoryTreeItem(
      `Pipeline Patterns (${stats.learned.pipelinePatterns})`,
      stats.learned.pipelinePatterns > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: patterns.pipeline_patterns || [], type: "pattern" }
    );
    pipelineItem.iconPath = new vscode.ThemeIcon("play-circle", new vscode.ThemeColor("charts.blue"));
    items.push(pipelineItem);

    // Tool Failures (with auto-fix stats)
    const failuresItem = new MemoryTreeItem(
      `Tool Failures (${stats.learned.toolFailures})`,
      stats.learned.toolFailures > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: failures.failures || [], type: "failure" }
    );
    failuresItem.iconPath = new vscode.ThemeIcon("error", new vscode.ThemeColor("charts.orange"));
    if (failures.stats?.auto_fixed) {
      failuresItem.description = `${failures.stats.auto_fixed} auto-fixed`;
    }
    items.push(failuresItem);

    // Learned Fixes
    const fixesItem = new MemoryTreeItem(
      `Learned Fixes (${stats.learned.toolFixes})`,
      stats.learned.toolFixes > 0
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
      "subcategory",
      { items: failures.learned_fixes || [], type: "fix" }
    );
    fixesItem.iconPath = new vscode.ThemeIcon("wrench", new vscode.ThemeColor("charts.green"));
    items.push(fixesItem);

    // Open files
    const openPatternsItem = new MemoryTreeItem(
      "Open patterns.yaml",
      vscode.TreeItemCollapsibleState.None,
      "action",
      null,
      patternsPath
    );
    openPatternsItem.iconPath = new vscode.ThemeIcon("go-to-file");
    openPatternsItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open File",
      arguments: [patternsPath],
    };
    items.push(openPatternsItem);

    const openFailuresItem = new MemoryTreeItem(
      "Open tool_failures.yaml",
      vscode.TreeItemCollapsibleState.None,
      "action",
      null,
      failuresPath
    );
    openFailuresItem.iconPath = new vscode.ThemeIcon("go-to-file");
    openFailuresItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open File",
      arguments: [failuresPath],
    };
    items.push(openFailuresItem);

    return items;
  }

  private getKnowledgeItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];
    const personasDir = path.join(this.memoryDir, "knowledge", "personas");

    // Projects with personas
    for (const persona of stats.knowledge.personas) {
      const personaPath = path.join(personasDir, persona);
      if (!fs.existsSync(personaPath)) continue;

      const projects = fs.readdirSync(personaPath)
        .filter(f => f.endsWith(".yaml"))
        .map(f => f.replace(".yaml", ""));

      const personaItem = new MemoryTreeItem(
        `${this.capitalize(persona)} Knowledge`,
        projects.length > 0
          ? vscode.TreeItemCollapsibleState.Collapsed
          : vscode.TreeItemCollapsibleState.None,
        "subcategory",
        {
          items: projects.map(p => ({
            name: p,
            path: path.join(personaPath, `${p}.yaml`)
          })),
          type: "knowledge_file"
        }
      );
      personaItem.iconPath = new vscode.ThemeIcon(
        this.getPersonaIcon(persona),
        new vscode.ThemeColor(this.getPersonaColor(persona))
      );
      personaItem.description = `${projects.length} projects`;
      items.push(personaItem);
    }

    // Last bootstrap info
    if (stats.knowledge.lastBootstrap) {
      const bootstrapItem = new MemoryTreeItem(
        `Last Bootstrap: ${this.formatDate(stats.knowledge.lastBootstrap)}`,
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      bootstrapItem.iconPath = new vscode.ThemeIcon("sync");
      items.push(bootstrapItem);
    }

    // Open knowledge.yaml
    const knowledgePath = path.join(this.memoryDir, "state", "knowledge.yaml");
    const openKnowledgeItem = new MemoryTreeItem(
      "Open knowledge.yaml",
      vscode.TreeItemCollapsibleState.None,
      "action",
      null,
      knowledgePath
    );
    openKnowledgeItem.iconPath = new vscode.ThemeIcon("go-to-file");
    openKnowledgeItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open File",
      arguments: [knowledgePath],
    };
    items.push(openKnowledgeItem);

    return items;
  }

  private getStatisticsItems(): MemoryTreeItem[] {
    const stats = this.loadStats();
    const items: MemoryTreeItem[] = [];
    const patternsPath = path.join(this.memoryDir, "learned", "patterns.yaml");

    // Vector Reindexes
    const reindexItem = new MemoryTreeItem(
      `Vector Reindexes: ${stats.statistics.vectorReindexes}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    reindexItem.iconPath = new vscode.ThemeIcon("search", new vscode.ThemeColor("charts.blue"));
    reindexItem.tooltip = "Number of times the vector index has been rebuilt. Click to view patterns.yaml";
    reindexItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open patterns.yaml",
      arguments: [patternsPath],
    };
    items.push(reindexItem);

    // Knowledge Bootstraps
    const bootstrapItem = new MemoryTreeItem(
      `Knowledge Bootstraps: ${stats.statistics.knowledgeBootstraps}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    bootstrapItem.iconPath = new vscode.ThemeIcon("book", new vscode.ThemeColor("charts.purple"));
    bootstrapItem.tooltip = "Number of knowledge bootstrap operations. Click to run bootstrap skill";
    bootstrapItem.command = {
      command: "aa-workflow.runSkillByName",
      title: "Run Bootstrap",
      arguments: ["bootstrap_knowledge"],
    };
    items.push(bootstrapItem);

    // Work Analyses
    const analysesItem = new MemoryTreeItem(
      `Work Analyses: ${stats.statistics.workAnalyses}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    analysesItem.iconPath = new vscode.ThemeIcon("graph", new vscode.ThemeColor("charts.green"));
    analysesItem.tooltip = "Number of work analysis reports generated. Click to run work analysis";
    analysesItem.command = {
      command: "aa-workflow.workAnalysis",
      title: "Run Work Analysis",
    };
    items.push(analysesItem);

    // Daily Patterns
    const dailyItem = new MemoryTreeItem(
      `Daily Patterns: ${stats.learned.dailyPatterns}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    dailyItem.iconPath = new vscode.ThemeIcon("calendar", new vscode.ThemeColor("charts.yellow"));
    dailyItem.tooltip = "Number of daily activity patterns recorded. Click to view patterns.yaml";
    dailyItem.command = {
      command: "aa-workflow.openMemoryFile",
      title: "Open patterns.yaml",
      arguments: [patternsPath],
    };
    items.push(dailyItem);

    return items;
  }

  private getMemoryActionItems(): MemoryTreeItem[] {
    const items: MemoryTreeItem[] = [];

    // View Memory
    const viewItem = new MemoryTreeItem(
      "View Memory Summary",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    viewItem.iconPath = new vscode.ThemeIcon("eye", new vscode.ThemeColor("charts.blue"));
    viewItem.description = "Run memory_view skill";
    viewItem.tooltip = "Get a comprehensive summary of all memory contents";
    viewItem.command = {
      command: "aa-workflow.runSkillByName",
      title: "View Memory",
      arguments: ["memory_view"],
    };
    items.push(viewItem);

    // Edit Memory
    const editItem = new MemoryTreeItem(
      "Edit Memory",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    editItem.iconPath = new vscode.ThemeIcon("edit", new vscode.ThemeColor("charts.yellow"));
    editItem.description = "Run memory_edit skill";
    editItem.tooltip = "Interactively edit memory entries";
    editItem.command = {
      command: "aa-workflow.runSkillByName",
      title: "Edit Memory",
      arguments: ["memory_edit"],
    };
    items.push(editItem);

    // Cleanup Memory
    const cleanupItem = new MemoryTreeItem(
      "Cleanup Memory",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    cleanupItem.iconPath = new vscode.ThemeIcon("trash", new vscode.ThemeColor("charts.red"));
    cleanupItem.description = "Run memory_cleanup skill";
    cleanupItem.tooltip = "Remove stale entries and optimize memory";
    cleanupItem.command = {
      command: "aa-workflow.runSkillByName",
      title: "Cleanup Memory",
      arguments: ["memory_cleanup"],
    };
    items.push(cleanupItem);

    // Learn Pattern
    const learnItem = new MemoryTreeItem(
      "Learn New Pattern",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    learnItem.iconPath = new vscode.ThemeIcon("lightbulb", new vscode.ThemeColor("charts.green"));
    learnItem.description = "Run learn_pattern skill";
    learnItem.tooltip = "Teach the system a new error pattern and fix";
    learnItem.command = {
      command: "aa-workflow.runSkillByName",
      title: "Learn Pattern",
      arguments: ["learn_pattern"],
    };
    items.push(learnItem);

    // Bootstrap Knowledge
    const bootstrapItem = new MemoryTreeItem(
      "Bootstrap Knowledge",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    bootstrapItem.iconPath = new vscode.ThemeIcon("book", new vscode.ThemeColor("charts.purple"));
    bootstrapItem.description = "Run bootstrap_knowledge skill";
    bootstrapItem.tooltip = "Generate knowledge files for all projects and personas";
    bootstrapItem.command = {
      command: "aa-workflow.runSkillByName",
      title: "Bootstrap Knowledge",
      arguments: ["bootstrap_knowledge"],
    };
    items.push(bootstrapItem);

    // Open Memory Directory
    const openDirItem = new MemoryTreeItem(
      "Open Memory Directory",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    openDirItem.iconPath = new vscode.ThemeIcon("folder-opened", new vscode.ThemeColor("charts.orange"));
    openDirItem.description = this.memoryDir;
    openDirItem.tooltip = "Open the memory directory in the file explorer";
    openDirItem.command = {
      command: "revealFileInOS",
      title: "Open Directory",
      arguments: [vscode.Uri.file(this.memoryDir)],
    };
    items.push(openDirItem);

    // Refresh Memory
    const refreshItem = new MemoryTreeItem(
      "Refresh Memory View",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    refreshItem.iconPath = new vscode.ThemeIcon("refresh", new vscode.ThemeColor("charts.cyan"));
    refreshItem.description = "Reload all memory data";
    refreshItem.tooltip = "Refresh the memory tree view";
    refreshItem.command = {
      command: "aa-workflow.refreshMemory",
      title: "Refresh",
    };
    items.push(refreshItem);

    return items;
  }

  private getItemDetails(items: any[], type: string): MemoryTreeItem[] {
    const result: MemoryTreeItem[] = [];

    for (const item of items.slice(0, 20)) { // Limit to 20 items
      let treeItem: MemoryTreeItem;

      switch (type) {
        case "issue":
          treeItem = new MemoryTreeItem(
            item.key || "Unknown",
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("issues");
          treeItem.description = this.truncate(item.summary || "", 40);
          treeItem.tooltip = new vscode.MarkdownString(
            `**${item.key}**\n\n${item.summary}\n\n` +
            `Status: ${item.status || "Unknown"}\n` +
            `Branch: ${item.branch || "N/A"}\n` +
            `Repo: ${item.repo || "N/A"}\n\n` +
            `_Click to open in Jira_`
          );
          // Click to open in Jira
          treeItem.command = {
            command: "aa-workflow.openJiraIssueByKey",
            title: "Open in Jira",
            arguments: [item.key],
          };
          break;

        case "mr":
          treeItem = new MemoryTreeItem(
            `!${item.id}`,
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("git-pull-request");
          treeItem.description = this.truncate(item.title || "", 40);
          treeItem.tooltip = new vscode.MarkdownString(
            `**!${item.id}**\n\n${item.title}\n\nStatus: ${item.status || "open"}\n\n_Click to open in GitLab_`
          );
          // Click to open in GitLab
          treeItem.command = {
            command: "aa-workflow.openMRById",
            title: "Open in GitLab",
            arguments: [item.id, item.project],
          };
          break;

        case "followup":
          treeItem = new MemoryTreeItem(
            this.truncate(item.task || "Unknown", 50),
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon(
            item.priority === "high" ? "circle-filled" : "circle-outline",
            item.priority === "high" ? new vscode.ThemeColor("charts.red") : undefined
          );
          treeItem.description = item.priority || "normal";
          treeItem.tooltip = new vscode.MarkdownString(
            `**Follow-up:** ${item.task}\n\n` +
            `Priority: ${item.priority || "normal"}\n` +
            (item.issue_key ? `Issue: ${item.issue_key}\n` : "") +
            (item.mr_id ? `MR: !${item.mr_id}\n` : "") +
            `\n_Click to copy task to clipboard_`
          );
          // Click to copy task
          treeItem.command = {
            command: "aa-workflow.copyToClipboard",
            title: "Copy Task",
            arguments: [item.task, "Follow-up task copied to clipboard"],
          };
          break;

        case "discovered":
          treeItem = new MemoryTreeItem(
            this.truncate(item.task || "Unknown", 50),
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("search");
          treeItem.description = item.work_type || "discovered_work";
          treeItem.tooltip = new vscode.MarkdownString(
            `**${item.task}**\n\n` +
            `Type: ${item.work_type || "discovered_work"}\n` +
            `Priority: ${item.priority || "medium"}\n` +
            `Source: ${item.source_skill || "unknown"}\n` +
            `Synced to Jira: ${item.jira_synced ? `Yes (${item.jira_key})` : "No"}\n\n` +
            (item.jira_synced ? `_Click to open Jira issue_` : `_Click to sync to Jira_`)
          );
          // Click to open Jira if synced, or sync if not
          if (item.jira_synced && item.jira_key) {
            treeItem.command = {
              command: "aa-workflow.openJiraIssueByKey",
              title: "Open in Jira",
              arguments: [item.jira_key],
            };
          } else {
            treeItem.command = {
              command: "aa-workflow.syncDiscoveredWork",
              title: "Sync to Jira",
              arguments: [item.task],
            };
          }
          break;

        case "namespace":
          treeItem = new MemoryTreeItem(
            item.name || "Unknown",
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("cloud");
          treeItem.description = item.mr_id ? `MR !${item.mr_id}` : "";
          treeItem.tooltip = new vscode.MarkdownString(
            `**${item.name}**\n\n` +
            `MR: ${item.mr_id || "N/A"}\n` +
            `Commit: ${item.commit || "N/A"}\n` +
            `Expires: ${item.expires || "N/A"}\n\n` +
            `_Click to show namespace actions_`
          );
          // Click to show namespace actions
          treeItem.command = {
            command: "aa-workflow.showNamespaceActions",
            title: "Namespace Actions",
            arguments: [item.name],
          };
          break;

        case "pattern":
          treeItem = new MemoryTreeItem(
            item.pattern || "Unknown pattern",
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("regex");
          treeItem.description = this.truncate(item.meaning || item.fix || "", 30);
          treeItem.tooltip = new vscode.MarkdownString(
            `**Pattern:** \`${item.pattern}\`\n\n` +
            `**Meaning:** ${item.meaning || "N/A"}\n\n` +
            `**Fix:** ${item.fix || "N/A"}\n\n` +
            (item.commands ? `**Commands:**\n${item.commands.map((c: string) => `- \`${c}\``).join("\n")}\n\n` : "") +
            `_Click to copy fix command_`
          );
          // Click to copy fix or first command
          const copyText = item.commands?.[0] || item.fix || item.pattern;
          treeItem.command = {
            command: "aa-workflow.copyToClipboard",
            title: "Copy Fix",
            arguments: [copyText, "Fix command copied to clipboard"],
          };
          break;

        case "failure":
          treeItem = new MemoryTreeItem(
            item.tool || "Unknown tool",
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon(
            item.success ? "pass" : "error",
            item.success ? new vscode.ThemeColor("charts.green") : new vscode.ThemeColor("charts.red")
          );
          treeItem.description = item.error_type || "";
          treeItem.tooltip = new vscode.MarkdownString(
            `**Tool:** ${item.tool}\n\n` +
            `**Error Type:** ${item.error_type || "unknown"}\n\n` +
            `**Fix Applied:** ${item.fix_applied || "N/A"}\n\n` +
            `**Success:** ${item.success ? "Yes" : "No"}\n\n` +
            `**Time:** ${item.timestamp || "N/A"}\n\n` +
            `_Click to debug this tool_`
          );
          // Click to run debug_tool
          treeItem.command = {
            command: "aa-workflow.debugTool",
            title: "Debug Tool",
            arguments: [item.tool, item.error_snippet],
          };
          break;

        case "fix":
          treeItem = new MemoryTreeItem(
            item.tool || "Unknown tool",
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("wrench", new vscode.ThemeColor("charts.green"));
          treeItem.description = this.truncate(item.error_pattern || "", 30);
          treeItem.tooltip = new vscode.MarkdownString(
            `**Tool:** ${item.tool}\n\n` +
            `**Error Pattern:** \`${item.error_pattern}\`\n\n` +
            `**Root Cause:** ${item.root_cause || "N/A"}\n\n` +
            `**Fix:** ${item.fix || "N/A"}\n\n` +
            `**Verified:** ${item.verified ? "Yes" : "No"}\n\n` +
            `_Click to copy fix description_`
          );
          // Click to copy fix description
          treeItem.command = {
            command: "aa-workflow.copyToClipboard",
            title: "Copy Fix",
            arguments: [item.fix || item.root_cause || "", "Fix description copied to clipboard"],
          };
          break;

        case "knowledge_file":
          treeItem = new MemoryTreeItem(
            item.name || "Unknown",
            vscode.TreeItemCollapsibleState.None,
            "file",
            item,
            item.path
          );
          treeItem.iconPath = new vscode.ThemeIcon("file-code");
          treeItem.tooltip = `Click to open ${item.name}.yaml`;
          treeItem.command = {
            command: "aa-workflow.openMemoryFile",
            title: "Open File",
            arguments: [item.path],
          };
          break;

        default:
          treeItem = new MemoryTreeItem(
            JSON.stringify(item).substring(0, 50),
            vscode.TreeItemCollapsibleState.None,
            "item",
            item
          );
          treeItem.iconPath = new vscode.ThemeIcon("json");
          // Click to show raw JSON
          treeItem.command = {
            command: "aa-workflow.showItemDetails",
            title: "Show Details",
            arguments: [item],
          };
      }

      result.push(treeItem);
    }

    if (items.length > 20) {
      const moreItem = new MemoryTreeItem(
        `... and ${items.length - 20} more`,
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      moreItem.iconPath = new vscode.ThemeIcon("ellipsis");
      // Click to open the source file
      moreItem.command = {
        command: "aa-workflow.openMemoryFile",
        title: "Open Source File",
        arguments: [path.join(this.memoryDir, "state", "current_work.yaml")],
      };
      result.push(moreItem);
    }

    return result;
  }

  private truncate(str: string, maxLen: number): string {
    if (str.length <= maxLen) return str;
    return str.substring(0, maxLen - 3) + "...";
  }

  private formatDate(dateStr: string): string {
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diff = now.getTime() - date.getTime();
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const days = Math.floor(hours / 24);

      if (hours < 1) return "just now";
      if (hours < 24) return `${hours}h ago`;
      if (days < 7) return `${days}d ago`;
      return date.toLocaleDateString();
    } catch {
      return dateStr;
    }
  }

  private capitalize(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  private getPersonaIcon(persona: string): string {
    const icons: Record<string, string> = {
      developer: "code",
      devops: "server-process",
      incident: "flame",
      release: "rocket",
    };
    return icons[persona] || "account";
  }

  private getPersonaColor(persona: string): string {
    const colors: Record<string, string> = {
      developer: "charts.blue",
      devops: "charts.green",
      incident: "charts.red",
      release: "charts.purple",
    };
    return colors[persona] || "charts.gray";
  }
}

export function registerMemoryTab(
  context: vscode.ExtensionContext
): MemoryTreeProvider {
  const treeProvider = new MemoryTreeProvider();

  const treeView = vscode.window.createTreeView("aaWorkflowMemory", {
    treeDataProvider: treeProvider,
    showCollapseAll: true,
  });

  context.subscriptions.push(treeView);

  // Register refresh command
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.refreshMemory", () => {
      treeProvider.refresh();
    })
  );

  // Register open file command
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openMemoryFile", (filePath: string) => {
      if (filePath && fs.existsSync(filePath)) {
        vscode.workspace.openTextDocument(filePath).then((doc) => {
          vscode.window.showTextDocument(doc);
        });
      }
    })
  );

  // Register memory skill commands
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.memoryView", () => {
      vscode.commands.executeCommand("aa-workflow.runSkillByName", "memory_view");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.memoryEdit", () => {
      vscode.commands.executeCommand("aa-workflow.runSkillByName", "memory_edit");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.memoryCleanup", () => {
      vscode.commands.executeCommand("aa-workflow.runSkillByName", "memory_cleanup");
    })
  );

  // Open Jira issue by key (for memory items)
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openJiraIssueByKey", (issueKey: string) => {
      if (issueKey) {
        const jiraUrl = "https://issues.redhat.com";
        vscode.env.openExternal(vscode.Uri.parse(`${jiraUrl}/browse/${issueKey}`));
      }
    })
  );

  // Open MR by ID (for memory items)
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.openMRById", (mrId: number, project?: string) => {
      if (mrId) {
        const gitlabUrl = "https://gitlab.cee.redhat.com";
        // If project is provided, use it; otherwise use default
        const projectPath = project || "automation-analytics/automation-analytics-backend";
        vscode.env.openExternal(vscode.Uri.parse(`${gitlabUrl}/${projectPath}/-/merge_requests/${mrId}`));
      }
    })
  );

  // Copy to clipboard helper
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.copyToClipboard", async (text: string, message: string) => {
      if (text) {
        await vscode.env.clipboard.writeText(text);
        vscode.window.showInformationMessage(message || "Copied to clipboard");
      }
    })
  );

  // Show namespace actions
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.showNamespaceActions", async (namespaceName: string) => {
      const action = await vscode.window.showQuickPick(
        [
          { label: "$(terminal) Copy kubectl command", value: "kubectl" },
          { label: "$(list-flat) Copy get pods command", value: "pods" },
          { label: "$(output) Copy logs command", value: "logs" },
          { label: "$(clock) Extend namespace", value: "extend" },
          { label: "$(trash) Release namespace", value: "release" },
        ],
        { placeHolder: `Actions for ${namespaceName}` }
      );

      if (!action) return;

      let cmd = "";
      switch (action.value) {
        case "kubectl":
          cmd = `kubectl --kubeconfig=~/.kube/config.e -n ${namespaceName}`;
          break;
        case "pods":
          cmd = `kubectl --kubeconfig=~/.kube/config.e get pods -n ${namespaceName}`;
          break;
        case "logs":
          cmd = `kubectl --kubeconfig=~/.kube/config.e logs -n ${namespaceName} -l app=<pod-label> --tail=100`;
          break;
        case "extend":
          cmd = `skill_run("extend_ephemeral", '{"namespace": "${namespaceName}"}')`;
          break;
        case "release":
          cmd = `KUBECONFIG=~/.kube/config.e bonfire namespace release ${namespaceName} --force`;
          break;
      }

      if (cmd) {
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage(`Command copied: ${cmd.substring(0, 50)}...`);
      }
    })
  );

  // Sync discovered work to Jira
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.syncDiscoveredWork", async (task: string) => {
      const confirm = await vscode.window.showInformationMessage(
        `Create Jira issue for: "${task.substring(0, 50)}..."?`,
        "Create Issue",
        "Cancel"
      );

      if (confirm === "Create Issue") {
        // Copy the skill command to run
        const cmd = `skill_run("sync_discovered_work", '{"task": "${task.replace(/"/g, '\\"')}"}')`;
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage("Sync command copied. Paste in chat to create Jira issue.");
      }
    })
  );

  // Debug tool command
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.debugTool", async (toolName: string, errorSnippet?: string) => {
      const cmd = errorSnippet
        ? `debug_tool("${toolName}", "${errorSnippet.substring(0, 100).replace(/"/g, '\\"')}")`
        : `debug_tool("${toolName}")`;

      await vscode.env.clipboard.writeText(cmd);
      vscode.window.showInformationMessage(`Debug command copied for ${toolName}. Paste in chat to debug.`);
    })
  );

  // Show item details (for unknown types)
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.showItemDetails", async (item: any) => {
      const output = vscode.window.createOutputChannel("Memory Item Details");
      output.clear();
      output.appendLine("=== Memory Item Details ===");
      output.appendLine("");
      output.appendLine(JSON.stringify(item, null, 2));
      output.show();
    })
  );

  // Session action (resume or view)
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.sessionAction", async (sessionId: string, isActive: boolean) => {
      if (isActive) {
        // Show session info
        const cmd = `session_info(session_id="${sessionId}")`;
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage("Session info command copied. Paste in chat to view details.");
      } else {
        // Resume session
        const cmd = `session_start(session_id="${sessionId}")`;
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage("Resume session command copied. Paste in chat to resume.");
      }
    })
  );

  // List all sessions
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.listAllSessions", async () => {
      const cmd = `session_list()`;
      await vscode.env.clipboard.writeText(cmd);
      vscode.window.showInformationMessage("Session list command copied. Paste in chat to see all sessions.");
    })
  );

  // Start new session
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.startNewSession", async () => {
      const agents = [
        { label: "$(robot) Default", value: "", description: "Auto-detect persona" },
        { label: "$(code) Developer", value: "developer", description: "Coding, PRs, code review" },
        { label: "$(server-process) DevOps", value: "devops", description: "Deployments, k8s, ephemeral" },
        { label: "$(flame) Incident", value: "incident", description: "Production issues, alerts" },
        { label: "$(package) Release", value: "release", description: "Shipping, Konflux, Quay" },
      ];

      const selected = await vscode.window.showQuickPick(agents, {
        placeHolder: "Select a persona for the new session",
      });

      if (!selected) return;

      const sessionName = await vscode.window.showInputBox({
        prompt: "Session name (optional)",
        placeHolder: "e.g., Fix billing bug",
      });

      let cmd = "session_start(";
      const args: string[] = [];
      if (selected.value) {
        args.push(`agent="${selected.value}"`);
      }
      if (sessionName) {
        args.push(`name="${sessionName}"`);
      }
      cmd += args.join(", ") + ")";

      await vscode.env.clipboard.writeText(cmd);
      vscode.window.showInformationMessage("Start session command copied. Paste in chat to begin.");
    })
  );

  return treeProvider;
}
