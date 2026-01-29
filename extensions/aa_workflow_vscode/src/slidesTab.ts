/**
 * Slides Tab - Google Slides presentation management UI
 *
 * Shows a hierarchical view of presentations:
 *
 * SLIDES EXPLORER
 * ├── 📊 My Presentations
 * │   ├── AI Workflow Overview
 * │   │   ├── 12 slides
 * │   │   └── Modified: 2 days ago
 * │   ├── Context Engineering
 * │   │   ├── 8 slides
 * │   │   └── Modified: 1 week ago
 * │   └── Onboarding Guide
 * │       ├── 15 slides
 * │       └── Modified: 3 weeks ago
 * ├── 🔧 Actions
 * │   ├── Create New Presentation
 * │   ├── List All Presentations
 * │   └── Check Status
 * └── 📚 Templates
 *     ├── Tech Talk Template
 *     └── Project Update Template
 */

import * as vscode from "vscode";
import * as path from "path";
import * as os from "os";
import { createLogger } from "./logger";

const logger = createLogger("SlidesTab");

// Tree item types for context menu handling
type SlidesItemType =
  | "category"
  | "presentation"
  | "slide"
  | "action"
  | "template"
  | "detail";

export class SlidesTreeItem extends vscode.TreeItem {
  public data?: any;

  constructor(
    public readonly label: string,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState,
    public readonly itemType: SlidesItemType,
    data?: any
  ) {
    super(label, collapsibleState);
    this.contextValue = itemType;
    this.data = data;
  }
}

interface PresentationInfo {
  id: string;
  name: string;
  modifiedTime: string;
  webViewLink: string;
  slideCount?: number;
}

interface SlidesStats {
  presentations: PresentationInfo[];
  templates: PresentationInfo[];
  lastRefresh: string | null;
  isConnected: boolean;
  error: string | null;
}

export class SlidesTreeProvider
  implements vscode.TreeDataProvider<SlidesTreeItem>
{
  private _onDidChangeTreeData: vscode.EventEmitter<
    SlidesTreeItem | undefined | null | void
  > = new vscode.EventEmitter<SlidesTreeItem | undefined | null | void>();
  readonly onDidChangeTreeData: vscode.Event<
    SlidesTreeItem | undefined | null | void
  > = this._onDidChangeTreeData.event;

  private cachedStats: SlidesStats | null = null;
  private isLoading: boolean = false;

  constructor() {}

  refresh(): void {
    this.cachedStats = null;
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: SlidesTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: SlidesTreeItem): Promise<SlidesTreeItem[]> {
    if (!element) {
      return this.getRootItems();
    }

    const label = element.label as string;

    if (label.includes("Presentations")) {
      return this.getPresentationItems();
    } else if (label.includes("Actions")) {
      return this.getActionItems();
    } else if (label.includes("Templates")) {
      return this.getTemplateItems();
    } else if (element.data?.slides) {
      return this.getSlideItems(element.data.slides);
    }

    return [];
  }

  private async loadStats(): Promise<SlidesStats> {
    if (this.cachedStats) {
      return this.cachedStats;
    }

    const stats: SlidesStats = {
      presentations: [],
      templates: [],
      lastRefresh: new Date().toISOString(),
      isConnected: false,
      error: null,
    };

    // Note: In a real implementation, this would call the MCP server
    // to get the actual list of presentations. For now, we show
    // placeholder data that guides users to use the tools.

    // Check if we have cached presentation data
    try {
      const configPath = path.join(
        os.homedir(),
        ".config",
        "aa-workflow",
        "slides_cache.json"
      );
      const fs = require("fs");
      if (fs.existsSync(configPath)) {
        const cached = JSON.parse(fs.readFileSync(configPath, "utf-8"));
        stats.presentations = cached.presentations || [];
        stats.templates = cached.templates || [];
        stats.isConnected = true;
      }
    } catch (e) {
      logger.debug("No cached slides data found");
    }

    this.cachedStats = stats;
    return stats;
  }

  private async getRootItems(): Promise<SlidesTreeItem[]> {
    const stats = await this.loadStats();
    const items: SlidesTreeItem[] = [];

    // My Presentations
    const presentationsItem = new SlidesTreeItem(
      "My Presentations",
      vscode.TreeItemCollapsibleState.Expanded,
      "category"
    );
    presentationsItem.iconPath = new vscode.ThemeIcon(
      "preview",
      new vscode.ThemeColor("charts.blue")
    );
    presentationsItem.description = stats.presentations.length > 0
      ? `${stats.presentations.length} found`
      : "Click refresh to load";
    items.push(presentationsItem);

    // Actions
    const actionsItem = new SlidesTreeItem(
      "Actions",
      vscode.TreeItemCollapsibleState.Expanded,
      "category"
    );
    actionsItem.iconPath = new vscode.ThemeIcon(
      "tools",
      new vscode.ThemeColor("charts.orange")
    );
    actionsItem.description = "Create & manage";
    items.push(actionsItem);

    // Templates
    const templatesItem = new SlidesTreeItem(
      "Templates",
      vscode.TreeItemCollapsibleState.Collapsed,
      "category"
    );
    templatesItem.iconPath = new vscode.ThemeIcon(
      "file-code",
      new vscode.ThemeColor("charts.purple")
    );
    templatesItem.description = stats.templates.length > 0
      ? `${stats.templates.length} available`
      : "No templates saved";
    items.push(templatesItem);

    return items;
  }

  private async getPresentationItems(): Promise<SlidesTreeItem[]> {
    const stats = await this.loadStats();
    const items: SlidesTreeItem[] = [];

    if (stats.presentations.length === 0) {
      // Show helpful message
      const emptyItem = new SlidesTreeItem(
        "No presentations loaded",
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      emptyItem.description = "Use 'List Presentations' action";
      items.push(emptyItem);

      const helpItem = new SlidesTreeItem(
        "Run: google_slides_list()",
        vscode.TreeItemCollapsibleState.None,
        "action"
      );
      helpItem.iconPath = new vscode.ThemeIcon("terminal");
      helpItem.command = {
        command: "aa-workflow.copyToClipboard",
        title: "Copy Command",
        arguments: ["google_slides_list()", "Command copied to clipboard"],
      };
      items.push(helpItem);

      return items;
    }

    for (const pres of stats.presentations) {
      const presItem = new SlidesTreeItem(
        pres.name,
        vscode.TreeItemCollapsibleState.Collapsed,
        "presentation",
        pres
      );
      presItem.iconPath = new vscode.ThemeIcon(
        "file-media",
        new vscode.ThemeColor("charts.blue")
      );
      presItem.description = this.formatDate(pres.modifiedTime);
      presItem.tooltip = new vscode.MarkdownString(
        `**${pres.name}**\n\n` +
        `| | |\n|---|---|\n` +
        `| ID | \`${pres.id}\` |\n` +
        `| Modified | ${pres.modifiedTime} |\n` +
        `| Slides | ${pres.slideCount || "Unknown"} |\n\n` +
        `_Click to open in Google Slides_`
      );
      presItem.command = {
        command: "aa-workflow.openPresentation",
        title: "Open Presentation",
        arguments: [pres.id, pres.webViewLink],
      };
      items.push(presItem);
    }

    return items;
  }

  private async getActionItems(): Promise<SlidesTreeItem[]> {
    const items: SlidesTreeItem[] = [];

    // Create New Presentation
    const createItem = new SlidesTreeItem(
      "Create New Presentation",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    createItem.iconPath = new vscode.ThemeIcon(
      "add",
      new vscode.ThemeColor("charts.green")
    );
    createItem.description = "skill: create_slide_deck";
    createItem.tooltip = "Create a new Google Slides presentation";
    createItem.command = {
      command: "aa-workflow.createPresentation",
      title: "Create Presentation",
    };
    items.push(createItem);

    // List All Presentations
    const listItem = new SlidesTreeItem(
      "List All Presentations",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    listItem.iconPath = new vscode.ThemeIcon(
      "list-flat",
      new vscode.ThemeColor("charts.blue")
    );
    listItem.description = "skill: list_presentations";
    listItem.tooltip = "Refresh the list of presentations from Google Drive";
    listItem.command = {
      command: "aa-workflow.listPresentations",
      title: "List Presentations",
    };
    items.push(listItem);

    // Check Status
    const statusItem = new SlidesTreeItem(
      "Check Google Slides Status",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    statusItem.iconPath = new vscode.ThemeIcon(
      "plug",
      new vscode.ThemeColor("charts.yellow")
    );
    statusItem.description = "google_slides_status()";
    statusItem.tooltip = "Check Google Slides API connection status";
    statusItem.command = {
      command: "aa-workflow.checkSlidesStatus",
      title: "Check Status",
    };
    items.push(statusItem);

    // Export to PDF
    const exportItem = new SlidesTreeItem(
      "Export to PDF",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    exportItem.iconPath = new vscode.ThemeIcon(
      "export",
      new vscode.ThemeColor("charts.purple")
    );
    exportItem.description = "skill: export_presentation";
    exportItem.tooltip = "Export a presentation to PDF format";
    exportItem.command = {
      command: "aa-workflow.exportPresentation",
      title: "Export to PDF",
    };
    items.push(exportItem);

    // Load Presentations Persona
    const personaItem = new SlidesTreeItem(
      "Load Presentations Persona",
      vscode.TreeItemCollapsibleState.None,
      "action"
    );
    personaItem.iconPath = new vscode.ThemeIcon(
      "account",
      new vscode.ThemeColor("charts.cyan")
    );
    personaItem.description = 'persona_load("presentations")';
    personaItem.tooltip = "Load the presentations persona with all slide tools";
    personaItem.command = {
      command: "aa-workflow.loadPersona",
      title: "Load Persona",
      arguments: ["presentations"],
    };
    items.push(personaItem);

    return items;
  }

  private async getTemplateItems(): Promise<SlidesTreeItem[]> {
    const stats = await this.loadStats();
    const items: SlidesTreeItem[] = [];

    if (stats.templates.length === 0) {
      const emptyItem = new SlidesTreeItem(
        "No templates saved",
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      emptyItem.iconPath = new vscode.ThemeIcon("info");
      emptyItem.description = "Save a presentation as template";
      items.push(emptyItem);

      const helpItem = new SlidesTreeItem(
        "To save as template:",
        vscode.TreeItemCollapsibleState.None,
        "detail"
      );
      helpItem.iconPath = new vscode.ThemeIcon("lightbulb");
      helpItem.description = "Use presentation ID in create_slide_deck";
      items.push(helpItem);

      return items;
    }

    for (const template of stats.templates) {
      const templateItem = new SlidesTreeItem(
        template.name,
        vscode.TreeItemCollapsibleState.None,
        "template",
        template
      );
      templateItem.iconPath = new vscode.ThemeIcon(
        "file-code",
        new vscode.ThemeColor("charts.purple")
      );
      templateItem.description = `ID: ${template.id.substring(0, 8)}...`;
      templateItem.tooltip = new vscode.MarkdownString(
        `**Template: ${template.name}**\n\n` +
        `ID: \`${template.id}\`\n\n` +
        `Use with:\n` +
        `\`\`\`\n` +
        `google_slides_create("New Presentation", template_id="${template.id}")\n` +
        `\`\`\``
      );
      templateItem.command = {
        command: "aa-workflow.useTemplate",
        title: "Use Template",
        arguments: [template.id, template.name],
      };
      items.push(templateItem);
    }

    return items;
  }

  private getSlideItems(slides: any[]): SlidesTreeItem[] {
    const items: SlidesTreeItem[] = [];

    for (let i = 0; i < slides.length; i++) {
      const slide = slides[i];
      const slideItem = new SlidesTreeItem(
        `Slide ${i + 1}: ${slide.title || "Untitled"}`,
        vscode.TreeItemCollapsibleState.None,
        "slide",
        slide
      );
      slideItem.iconPath = new vscode.ThemeIcon("file");
      slideItem.description = slide.layout || "";
      items.push(slideItem);
    }

    return items;
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
      if (days < 30) return `${Math.floor(days / 7)}w ago`;
      return date.toLocaleDateString();
    } catch {
      return dateStr;
    }
  }
}

export function registerSlidesTab(
  context: vscode.ExtensionContext
): SlidesTreeProvider {
  const treeProvider = new SlidesTreeProvider();

  const treeView = vscode.window.createTreeView("aaWorkflowSlides", {
    treeDataProvider: treeProvider,
    showCollapseAll: true,
  });

  context.subscriptions.push(treeView);

  // Register refresh command
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.refreshSlides", () => {
      treeProvider.refresh();
    })
  );

  // Open presentation in browser
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.openPresentation",
      (presentationId: string, webViewLink: string) => {
        if (webViewLink) {
          vscode.env.openExternal(vscode.Uri.parse(webViewLink));
        } else if (presentationId) {
          vscode.env.openExternal(
            vscode.Uri.parse(
              `https://docs.google.com/presentation/d/${presentationId}/edit`
            )
          );
        }
      }
    )
  );

  // Create new presentation
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.createPresentation",
      async () => {
        const title = await vscode.window.showInputBox({
          prompt: "Presentation title",
          placeHolder: "e.g., AI Workflow Overview",
        });

        if (!title) return;

        const hasOutline = await vscode.window.showQuickPick(
          [
            { label: "$(file) Blank presentation", value: "blank" },
            { label: "$(list-tree) From outline", value: "outline" },
            { label: "$(search) From topic (auto-generate)", value: "topic" },
          ],
          { placeHolder: "How would you like to create the presentation?" }
        );

        if (!hasOutline) return;

        let cmd = "";
        if (hasOutline.value === "blank") {
          cmd = `skill_run("create_slide_deck", '{"title": "${title}"}')`;
        } else if (hasOutline.value === "outline") {
          const outline = await vscode.window.showInputBox({
            prompt: "Enter markdown outline (# Section, ## Slide, - Bullet)",
            placeHolder: "# Introduction\\n## Overview\\n- Point 1\\n- Point 2",
          });
          if (outline) {
            const escapedOutline = outline.replace(/"/g, '\\"');
            cmd = `skill_run("create_slide_deck", '{"title": "${title}", "outline": "${escapedOutline}"}')`;
          }
        } else if (hasOutline.value === "topic") {
          const topic = await vscode.window.showInputBox({
            prompt: "Enter topic to research",
            placeHolder: "e.g., MCP Protocol, AI Personas",
          });
          if (topic) {
            cmd = `skill_run("create_slide_deck", '{"title": "${title}", "topic": "${topic}"}')`;
          }
        }

        if (cmd) {
          await vscode.env.clipboard.writeText(cmd);
          vscode.window.showInformationMessage(
            "Create presentation command copied. Paste in chat to execute."
          );
        }
      }
    )
  );

  // List presentations
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.listPresentations", async () => {
      const cmd = 'skill_run("list_presentations", "{}")';
      await vscode.env.clipboard.writeText(cmd);
      vscode.window.showInformationMessage(
        "List presentations command copied. Paste in chat to execute."
      );
    })
  );

  // Check slides status
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.checkSlidesStatus", async () => {
      const cmd = "google_slides_status()";
      await vscode.env.clipboard.writeText(cmd);
      vscode.window.showInformationMessage(
        "Status command copied. Paste in chat to check connection."
      );
    })
  );

  // Export presentation
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.exportPresentation",
      async () => {
        const presentationId = await vscode.window.showInputBox({
          prompt: "Presentation ID to export",
          placeHolder: "Enter the presentation ID",
        });

        if (!presentationId) return;

        const outputPath = await vscode.window.showInputBox({
          prompt: "Output path (leave empty for default)",
          placeHolder: "e.g., ~/presentations/output.pdf",
        });

        let cmd = `skill_run("export_presentation", '{"presentation_id": "${presentationId}"`;
        if (outputPath) {
          cmd += `, "output_path": "${outputPath}"`;
        }
        cmd += "}')";

        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage(
          "Export command copied. Paste in chat to execute."
        );
      }
    )
  );

  // Load persona
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.loadPersona",
      async (persona: string) => {
        const cmd = `persona_load("${persona}")`;
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage(
          `Load ${persona} persona command copied. Paste in chat to execute.`
        );
      }
    )
  );

  // Use template
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.useTemplate",
      async (templateId: string, templateName: string) => {
        const title = await vscode.window.showInputBox({
          prompt: "Title for new presentation",
          placeHolder: `Copy of ${templateName}`,
          value: `Copy of ${templateName}`,
        });

        if (!title) return;

        const cmd = `google_slides_create("${title}", template_id="${templateId}")`;
        await vscode.env.clipboard.writeText(cmd);
        vscode.window.showInformationMessage(
          "Create from template command copied. Paste in chat to execute."
        );
      }
    )
  );

  return treeProvider;
}
