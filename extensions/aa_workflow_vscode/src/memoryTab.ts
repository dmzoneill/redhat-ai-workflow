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
    } else if (label.includes("Learned")) {
      return this.getLearnedItems();
    } else if (label.includes("Knowledge")) {
      return this.getKnowledgeItems();
    } else if (label.includes("Statistics")) {
      return this.getStatisticsItems();
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

    // Vector Reindexes
    const reindexItem = new MemoryTreeItem(
      `Vector Reindexes: ${stats.statistics.vectorReindexes}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    reindexItem.iconPath = new vscode.ThemeIcon("search", new vscode.ThemeColor("charts.blue"));
    reindexItem.tooltip = "Number of times the vector index has been rebuilt";
    items.push(reindexItem);

    // Knowledge Bootstraps
    const bootstrapItem = new MemoryTreeItem(
      `Knowledge Bootstraps: ${stats.statistics.knowledgeBootstraps}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    bootstrapItem.iconPath = new vscode.ThemeIcon("book", new vscode.ThemeColor("charts.purple"));
    bootstrapItem.tooltip = "Number of knowledge bootstrap operations";
    items.push(bootstrapItem);

    // Work Analyses
    const analysesItem = new MemoryTreeItem(
      `Work Analyses: ${stats.statistics.workAnalyses}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    analysesItem.iconPath = new vscode.ThemeIcon("graph", new vscode.ThemeColor("charts.green"));
    analysesItem.tooltip = "Number of work analysis reports generated";
    items.push(analysesItem);

    // Daily Patterns
    const dailyItem = new MemoryTreeItem(
      `Daily Patterns: ${stats.learned.dailyPatterns}`,
      vscode.TreeItemCollapsibleState.None,
      "detail"
    );
    dailyItem.iconPath = new vscode.ThemeIcon("calendar", new vscode.ThemeColor("charts.yellow"));
    dailyItem.tooltip = "Number of daily activity patterns recorded";
    items.push(dailyItem);

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
            `Repo: ${item.repo || "N/A"}`
          );
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
          treeItem.tooltip = `${item.title}\nStatus: ${item.status || "open"}`;
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
            `Synced to Jira: ${item.jira_synced ? "Yes" : "No"}`
          );
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
            `Expires: ${item.expires || "N/A"}`
          );
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
            (item.commands ? `**Commands:**\n${item.commands.map((c: string) => `- \`${c}\``).join("\n")}` : "")
          );
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
            `**Time:** ${item.timestamp || "N/A"}`
          );
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
            `**Verified:** ${item.verified ? "Yes" : "No"}`
          );
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

  return treeProvider;
}
