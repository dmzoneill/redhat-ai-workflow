/**
 * Tools Tab
 *
 * Displays available tool modules and their tools.
 * Uses D-Bus to communicate with the Config daemon.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("ToolsTab");

interface Tool {
  name: string;
  description: string;
  parameters?: Array<{
    name: string;
    type: string;
    required: boolean;
    description: string;
  }>;
}

interface ToolModule {
  name: string;
  displayName: string;
  description: string;
  tools: Tool[];
  toolCount: number;
  category?: string;
  icon?: string;
}

export class ToolsTab extends BaseTab {
  private modules: ToolModule[] = [];
  private selectedModule: string | null = null;
  private selectedTool: string | null = null;
  private searchQuery = "";
  private totalTools = 0;

  constructor() {
    super({
      id: "tools",
      label: "Tools",
      icon: "🔧",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    if (this.totalTools > 0) {
      return { text: `${this.totalTools}`, class: "" };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load tool modules via D-Bus
      logger.log("Calling config_getToolModules()...");
      const result = await dbus.config_getToolModules();
      logger.log(`config_getToolModules() result: success=${result.success}, error=${result.error || 'none'}`);
      if (result.success && result.data) {
        const data = result.data as any;
        // Map snake_case from D-Bus to camelCase for TypeScript
        this.modules = (data.modules || []).map((m: any) => ({
          name: m.name,
          displayName: m.full_name || m.name,
          description: m.description || "",
          tools: (m.tools || []).map((t: any) => ({
            name: t.name,
            description: t.description || "",
            parameters: (t.parameters || []).map((p: any) => ({
              name: p.name,
              type: p.type || "any",
              required: p.required ?? true,
              description: p.description || "",
            })),
          })),
          toolCount: m.tool_count || 0,
          category: m.category,
          icon: m.icon,
        }));
        this.categorizeModules();
        this.totalTools = this.modules.reduce((sum, m) => sum + (m.toolCount || 0), 0);
        logger.log(`Loaded ${this.modules.length} modules with ${this.totalTools} total tools`);
      } else if (result.error) {
        this.lastError = `Tool modules failed: ${result.error}`;
        logger.warn(this.lastError);
      }
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  private categorizeModules(): void {
    this.modules.forEach((module) => {
      const name = module.name.toLowerCase();
      if (name.includes("git") || name.includes("gitlab")) {
        module.category = "Version Control";
        module.icon = "🔀";
      } else if (name.includes("jira") || name.includes("issue")) {
        module.category = "Issue Tracking";
        module.icon = "📋";
      } else if (name.includes("k8s") || name.includes("bonfire") || name.includes("deploy")) {
        module.category = "DevOps";
        module.icon = "🚀";
      } else if (name.includes("slack") || name.includes("meet")) {
        module.category = "Communication";
        module.icon = "💬";
      } else if (name.includes("memory") || name.includes("workflow")) {
        module.category = "Workflow";
        module.icon = "⚙️";
      } else if (name.includes("ollama") || name.includes("code_search")) {
        module.category = "AI/Search";
        module.icon = "🤖";
      } else {
        module.category = "General";
        module.icon = "🔧";
      }
    });

    // Auto-select first module if none selected
    if (!this.selectedModule && this.modules.length > 0) {
      this.selectedModule = this.modules[0].name;
    }
  }

  getContent(): string {
    return `
      <!-- Tools Overview -->
      <div class="section">
        <div class="section-title">🔧 Tool Modules</div>
        <div class="grid-3">
          <div class="stat-card blue">
            <div class="stat-icon">📦</div>
            <div class="stat-value">${this.modules.length}</div>
            <div class="stat-label">Modules</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">🔧</div>
            <div class="stat-value">${this.totalTools}</div>
            <div class="stat-label">Total Tools</div>
          </div>
          <div class="stat-card cyan">
            <div class="stat-icon">📊</div>
            <div class="stat-value">${this.getCategoryCount()}</div>
            <div class="stat-label">Categories</div>
          </div>
        </div>
      </div>

      <!-- Search and Controls -->
      <div class="section">
        <div class="tools-controls">
          <div class="tools-search">
            <input type="text" placeholder="Search tools..." id="toolSearch" value="${this.escapeHtml(this.searchQuery)}" />
          </div>
        </div>
      </div>

      <!-- Tools Browser -->
      <div class="section">
        <div class="tools-browser">
          <div class="tools-sidebar">
            ${this.getModulesListHtml()}
          </div>
          <div class="tools-main">
            ${this.getToolsContentHtml()}
          </div>
        </div>
      </div>
    `;
  }

  private getCategoryCount(): number {
    const categories = new Set(this.modules.map((m) => m.category));
    return categories.size;
  }

  private getModulesListHtml(): string {
    const filteredModules = this.filterModules();
    const groupedModules = this.groupModules(filteredModules);

    let html = "";
    for (const [category, modules] of Object.entries(groupedModules)) {
      html += `<div class="tools-category-title">${this.escapeHtml(category)}</div>`;
      modules.forEach((module) => {
        const isSelected = this.selectedModule === module.name;
        html += `
          <div class="tools-module-item ${isSelected ? "selected" : ""}" data-module="${module.name}">
            <span class="tools-module-icon">${module.icon || "📦"}</span>
            <div class="tools-module-info">
              <div class="tools-module-name">${this.escapeHtml(module.displayName || module.name)}</div>
              <div class="tools-module-count">${module.toolCount} tools</div>
            </div>
          </div>
        `;
      });
    }

    return html || '<div class="loading-placeholder">No modules found</div>';
  }

  private getToolsContentHtml(): string {
    if (!this.selectedModule) {
      return this.getEmptyStateHtml("📦", "Select a module to view its tools");
    }

    const module = this.modules.find((m) => m.name === this.selectedModule);
    if (!module) {
      logger.log(`Module not found: ${this.selectedModule}, available: ${this.modules.map(m => m.name).join(', ')}`);
      return this.getEmptyStateHtml("❓", "Module not found");
    }

    logger.log(`Rendering module ${module.name} with ${module.tools.length} tools`);

    if (!module.tools || module.tools.length === 0) {
      return `
        <div class="tools-module-header">
          <div class="tools-module-title">
            <span>${module.icon || "📦"}</span>
            ${this.escapeHtml(module.displayName || module.name)}
          </div>
          <div class="tools-module-desc">${this.escapeHtml(module.description || "")}</div>
        </div>
        <div class="tools-list">
          ${this.getEmptyStateHtml("🔧", "No tools found in this module")}
        </div>
      `;
    }

    return `
      <div class="tools-module-header">
        <div class="tools-module-title">
          <span>${module.icon || "📦"}</span>
          ${this.escapeHtml(module.displayName || module.name)}
        </div>
        <div class="tools-module-desc">${this.escapeHtml(module.description || "")}</div>
      </div>
      <div class="tools-list">
        ${module.tools.map((tool) => this.getToolItemHtml(tool)).join("")}
      </div>
    `;
  }

  private getToolItemHtml(tool: Tool): string {
    const isSelected = this.selectedTool === tool.name;
    const paramCount = tool.parameters?.length || 0;

    return `
      <div class="tool-item ${isSelected ? "selected" : ""}" data-tool="${tool.name}">
        <div class="tool-item-header">
          <div class="tool-item-name">${this.escapeHtml(tool.name)}</div>
          <div class="tool-item-params">${paramCount} params</div>
        </div>
        <div class="tool-item-desc">${this.escapeHtml(tool.description || "").substring(0, 100)}</div>
        ${isSelected && tool.parameters && tool.parameters.length > 0 ? `
          <div class="tool-item-params-list">
            ${tool.parameters.map((p) => `
              <div class="tool-param">
                <span class="tool-param-name">${p.name}${p.required ? " *" : ""}</span>
                <span class="tool-param-type">${p.type}</span>
                <span class="tool-param-desc">${this.escapeHtml(p.description || "")}</span>
              </div>
            `).join("")}
          </div>
        ` : ""}
      </div>
    `;
  }

  private filterModules(): ToolModule[] {
    if (!this.searchQuery) return this.modules;

    const query = this.searchQuery.toLowerCase();
    return this.modules.filter(
      (m) =>
        m.name.toLowerCase().includes(query) ||
        m.displayName?.toLowerCase().includes(query) ||
        m.description?.toLowerCase().includes(query) ||
        m.tools.some((t) => t.name.toLowerCase().includes(query))
    );
  }

  private groupModules(modules: ToolModule[]): Record<string, ToolModule[]> {
    const groups: Record<string, ToolModule[]> = {};
    modules.forEach((module) => {
      const category = module.category || "General";
      if (!groups[category]) groups[category] = [];
      groups[category].push(module);
    });
    return groups;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return `
      // Search tools
      const toolSearch = document.getElementById('toolSearch');
      if (toolSearch) {
        toolSearch.addEventListener('input', (e) => {
          vscode.postMessage({ command: 'searchTools', query: e.target.value });
        });
      }

      // Refresh tools
      document.querySelectorAll('[data-action="refreshTools"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'refreshTools' });
        });
      });

      // Select module
      document.querySelectorAll('.tools-module-item').forEach(item => {
        item.addEventListener('click', () => {
          const moduleName = item.dataset.module;
          if (moduleName) {
            vscode.postMessage({ command: 'selectToolModule', module: moduleName });
          }
        });
      });

      // Select tool
      document.querySelectorAll('.tool-item').forEach(item => {
        item.addEventListener('click', () => {
          const toolName = item.dataset.tool;
          if (toolName) {
            vscode.postMessage({ command: 'selectTool', tool: toolName });
          }
        });
      });
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;
    logger.log(`handleMessage: ${msgType}`);

    switch (msgType) {
      case "searchTools":
        this.searchQuery = message.query || "";
        this.notifyNeedsRender();
        return true;

      case "refreshTools":
        await this.refresh();
        return true;

      case "selectToolModule":
        this.selectedModule = message.module;
        this.selectedTool = null;
        this.notifyNeedsRender();
        return true;

      case "selectTool":
        this.selectedTool = message.tool;
        this.notifyNeedsRender();
        return true;

      default:
        return false;
    }
  }
}
