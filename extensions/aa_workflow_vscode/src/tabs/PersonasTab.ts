/**
 * Personas Tab
 *
 * Displays available personas and allows switching between them.
 * Uses D-Bus to communicate with the Config daemon.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("PersonasTab");

interface Persona {
  name: string;
  description: string;
  tools: string[];
  tool_count: number;
  skills: string[];
  skills_count: number;
  file: string;
  icon?: string;
  category?: string;
}

interface ActiveAgent {
  name: string;
  persona: string;
  tools: string[];
  tool_count: number;
}

export class PersonasTab extends BaseTab {
  private personas: Persona[] = [];
  private activeAgent: ActiveAgent | null = null;
  private selectedPersona: string | null = null;
  private viewMode: "card" | "table" = "card";
  private searchQuery = "";

  constructor() {
    super({
      id: "personas",
      label: "Personas",
      icon: "🎭",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    // Show total persona count
    if (this.personas.length > 0) {
      return { text: `${this.personas.length}` };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load personas list via D-Bus
      logger.log("Calling config_getPersonasList()...");
      const personasResult = await dbus.config_getPersonasList();
      logger.log(`config_getPersonasList() result: success=${personasResult.success}, error=${personasResult.error || 'none'}`);
      if (personasResult.success && personasResult.data) {
        const data = personasResult.data as any;
        this.personas = data.personas || [];
        this.categorizePersonas();
        logger.log(`Loaded ${this.personas.length} personas`);
      } else if (personasResult.error) {
        this.lastError = `Personas list failed: ${personasResult.error}`;
        logger.warn(this.lastError);
      }

      // Load active agent
      logger.log("Calling memory_getCurrentWork()...");
      const agentResult = await dbus.memory_getCurrentWork();
      logger.log(`memory_getCurrentWork() result: success=${agentResult.success}, error=${agentResult.error || 'none'}`);
      if (agentResult.success && agentResult.data) {
        const data = agentResult.data as any;
        if (data.active_persona) {
          this.activeAgent = {
            name: data.active_persona,
            persona: data.active_persona,
            tools: data.tools || [],
            tool_count: data.tools?.length || 0,
          };
          logger.log(`Active agent: ${this.activeAgent.name}`);
        }
      } else if (agentResult.error) {
        logger.warn(`Current work failed: ${agentResult.error}`);
      }
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  private categorizePersonas(): void {
    this.personas.forEach((persona) => {
      const name = persona.name.toLowerCase();

      // Assign unique icon per persona using shared mapping from BaseTab
      persona.icon = this.getPersonaIcon(persona.name);

      // Compute counts if not already set
      if (persona.tool_count === undefined) {
        persona.tool_count = persona.tools?.length || 0;
      }
      if (persona.skills_count === undefined) {
        persona.skills_count = persona.skills?.length || 0;
      }

      // Categorize for grouping
      if (name.includes("dev") || name.includes("code")) {
        persona.category = "Development";
      } else if (name.includes("ops") || name.includes("deploy")) {
        persona.category = "DevOps";
      } else if (name.includes("incident") || name.includes("debug")) {
        persona.category = "Incident";
      } else if (name.includes("release") || name.includes("prod")) {
        persona.category = "Release";
      } else if (name.includes("admin") || name.includes("slack")) {
        persona.category = "Admin";
      } else {
        persona.category = "General";
      }
    });
  }

  getContent(): string {
    return `
      <!-- Persona Controls -->
      <div class="section">
        <div class="persona-controls">
          <div class="persona-count">${this.personas.length} persona(s)</div>
          <div class="view-toggle">
            <button id="personaViewCard" data-action="viewCard" class="toggle-btn ${this.viewMode === "card" ? "active" : ""}">🗂️ Cards</button>
            <button id="personaViewTable" data-action="viewTable" class="toggle-btn ${this.viewMode === "table" ? "active" : ""}">📋 Table</button>
          </div>
        </div>
      </div>

      <!-- Personas List -->
      <div class="section">
        <div class="section-title">📋 Available Personas (${this.personas.length})</div>
        ${this.viewMode === "card" ? this.getPersonaCardsHtml() : this.getPersonaTableHtml()}
      </div>
    `;
  }

  private getActiveAgentHtml(): string {
    if (!this.activeAgent) {
      return this.getEmptyStateHtml("🎭", "No active agent");
    }

    return `
      <div class="active-agent-card">
        <div class="active-agent-header">
          <div class="active-agent-icon">🎭</div>
          <div class="active-agent-info">
            <div class="active-agent-name">${this.escapeHtml(this.activeAgent.name)}</div>
            <div class="active-agent-tools">${this.activeAgent.tool_count} tools loaded</div>
          </div>
        </div>
        <div class="active-agent-tools-list">
          ${this.activeAgent.tools.slice(0, 10).map((tool) => `<span class="tool-badge">${this.escapeHtml(tool)}</span>`).join("")}
          ${this.activeAgent.tools.length > 10 ? `<span class="tool-badge more">+${this.activeAgent.tools.length - 10} more</span>` : ""}
        </div>
      </div>
    `;
  }

  private getPersonaCardsHtml(): string {
    const filteredPersonas = this.filterPersonas();
    const groupedPersonas = this.groupPersonas(filteredPersonas);

    if (Object.keys(groupedPersonas).length === 0) {
      return this.getEmptyStateHtml("🎭", "No personas found");
    }

    let html = "";
    for (const [category, personas] of Object.entries(groupedPersonas)) {
      html += `<div class="persona-category-title">${this.escapeHtml(category)}</div>`;
      html += `<div class="persona-cards-grid">`;
      personas.forEach((persona) => {
        html += this.getPersonaCardHtml(persona);
      });
      html += `</div>`;
    }

    return html;
  }

  private getPersonaCardHtml(persona: Persona): string {
    const isActive = this.activeAgent?.persona === persona.name;
    const isSelected = this.selectedPersona === persona.name;
    const color = this.getPersonaColor(persona.name);

    return `
      <div class="persona-card ${isActive ? "active" : ""} ${isSelected ? "selected" : ""}" data-persona="${persona.name}">
        <div class="persona-card-header">
          <div class="persona-card-icon">${persona.icon || "🎭"}</div>
          <div class="persona-card-name">${this.escapeHtml(persona.name)}</div>
          ${isActive ? '<span class="persona-active-badge">Active</span>' : ""}
        </div>
        <div class="persona-card-description">${this.escapeHtml(persona.description || "")}</div>
        <div class="persona-card-stats">
          <span>🔧 ${persona.tool_count} tools</span>
          <span>⚡ ${persona.skills_count} skills</span>
        </div>
        <div class="persona-card-actions">
          <button class="btn btn-xs" data-action="loadPersona" data-persona="${persona.name}" ${isActive ? "disabled" : ""} title="Send to current chat">
            ${isActive ? "Active" : "Load"}
          </button>
          <button class="btn btn-xs btn-primary" data-action="startPersonaChat" data-persona="${persona.name}" title="Start new chat with this persona">Start</button>
        </div>
      </div>
    `;
  }

  private getPersonaTableHtml(): string {
    const filteredPersonas = this.filterPersonas();

    if (filteredPersonas.length === 0) {
      return this.getEmptyStateHtml("🎭", "No personas found");
    }

    return `
      <table class="persona-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Category</th>
            <th>Description</th>
            <th>Tools</th>
            <th>Skills</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          ${filteredPersonas.map((persona) => this.getPersonaRowHtml(persona)).join("")}
        </tbody>
      </table>
    `;
  }

  private getPersonaRowHtml(persona: Persona): string {
    const isActive = this.activeAgent?.persona === persona.name;
    const color = this.getPersonaColor(persona.name);

    return `
      <tr class="${isActive ? "active" : ""}" data-persona="${persona.name}">
        <td>
          <span class="persona-icon">${persona.icon || "🎭"}</span>
          <span class="persona-name-text">${this.escapeHtml(persona.name)}</span>
          ${isActive ? '<span class="persona-active-badge">Active</span>' : ""}
        </td>
        <td>${persona.category || "-"}</td>
        <td>${this.escapeHtml(persona.description || "")}</td>
        <td>${persona.tool_count}</td>
        <td>${persona.skills_count}</td>
        <td class="action-buttons">
          <button class="btn btn-tiny" data-action="loadPersona" data-persona="${persona.name}" ${isActive ? "disabled" : ""} title="Send to current chat">
            ${isActive ? "Active" : "Load"}
          </button>
          <button class="btn btn-tiny btn-primary" data-action="startPersonaChat" data-persona="${persona.name}" title="Start new chat">Start</button>
        </td>
      </tr>
    `;
  }

  private filterPersonas(): Persona[] {
    if (!this.searchQuery) return this.personas;

    const query = this.searchQuery.toLowerCase();
    return this.personas.filter(
      (p) =>
        p.name.toLowerCase().includes(query) ||
        p.description?.toLowerCase().includes(query) ||
        p.category?.toLowerCase().includes(query)
    );
  }

  private groupPersonas(personas: Persona[]): Record<string, Persona[]> {
    const groups: Record<string, Persona[]> = {};
    personas.forEach((persona) => {
      const category = persona.category || "General";
      if (!groups[category]) groups[category] = [];
      groups[category].push(persona);
    });
    return groups;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    // Use event delegation on the #personas container so handlers survive content updates
    return `
      (function() {
        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('personas', function(action, element, e) {
          const persona = element.dataset.persona;

          switch(action) {
            case 'loadPersona':
              if (persona) vscode.postMessage({ command: 'loadPersona', persona });
              break;
            case 'startPersonaChat':
              if (persona) vscode.postMessage({ command: 'startPersonaChat', persona });
              break;
            case 'viewPersonaDetails':
              if (persona) vscode.postMessage({ command: 'viewPersonaDetails', persona });
              break;
            case 'refreshPersonas':
              vscode.postMessage({ command: 'refreshPersonas' });
              break;
            case 'viewCard':
              vscode.postMessage({ command: 'changePersonaViewMode', value: 'card' });
              break;
            case 'viewTable':
              vscode.postMessage({ command: 'changePersonaViewMode', value: 'table' });
              break;
          }
        });

        // Additional click handling for non-data-action elements
        const personasContainer = document.getElementById('personas');
        if (personasContainer && !personasContainer.dataset.extraClickInit) {
          personasContainer.dataset.extraClickInit = 'true';

          personasContainer.addEventListener('click', function(e) {
            const target = e.target;
            // Skip if already handled by data-action
            if (target.closest('[data-action]')) return;

            // Persona card clicks (for selection, but not on buttons)
            const personaCard = target.closest('.persona-card');
            if (personaCard && target.tagName !== 'BUTTON') {
              const persona = personaCard.dataset.persona;
              if (persona) {
                vscode.postMessage({ command: 'selectPersona', persona });
              }
              return;
            }
          });

          // Input delegation for search
          personasContainer.addEventListener('input', function(e) {
            if (e.target.id === 'personaSearch') {
              vscode.postMessage({ command: 'searchPersonas', query: e.target.value });
            }
          });
        }
      })();
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "searchPersonas":
        this.searchQuery = message.query || "";
        // Trigger re-render to show filtered results
        this.notifyNeedsRender();
        return true;

      case "changePersonaViewMode":
        this.viewMode = message.value as "card" | "table";
        // Trigger re-render to show new view mode
        this.notifyNeedsRender();
        return true;

      case "refreshPersonas":
        await this.refresh();
        return true;

      case "loadPersona":
        await this.loadPersonaToCurrentChat(message.persona);
        return true;

      case "startPersonaChat":
        await this.startNewChatWithPersona(message.persona);
        return true;

      case "viewPersonaDetails":
        await this.viewPersonaDetails(message.persona);
        return true;

      case "selectPersona":
        this.selectedPersona = message.persona;
        return true;

      default:
        return false;
    }
  }

  private async loadPersonaToCurrentChat(personaName: string): Promise<void> {
    // Send persona_load command to current/existing chat
    const command = `persona_load("${personaName}")`;
    await vscode.env.clipboard.writeText(command);

    // Focus the composer and paste
    try {
      await vscode.commands.executeCommand("composer.focusComposer");
      // Use ydotool to paste (Ctrl+V)
      const { sendPaste, sendEnter, sleep } = await import("../chatUtils");
      await sleep(100);
      sendPaste();
      await sleep(100);
      sendEnter();
      vscode.window.showInformationMessage(`🔄 Loading ${personaName} persona in current chat...`);
    } catch (e) {
      // Fallback: just copy to clipboard
      vscode.window.showInformationMessage(`📋 Copied: ${command} - Paste in your chat to load the persona.`);
    }
  }

  private async startNewChatWithPersona(personaName: string): Promise<void> {
    // Create new composer, paste command, submit (matching SkillsTab approach)
    const command = `persona_load("${personaName}")`;

    try {
      const { sendPaste, sendEnter, sleep } = await import("../chatUtils");

      // Step 1: Copy command to clipboard
      logger.log(`Starting new chat with persona: ${personaName}`);
      await vscode.env.clipboard.writeText(command);

      // Step 2: Create new composer tab
      logger.log("Creating new composer tab...");
      await vscode.commands.executeCommand("composer.createNewComposerTab");
      await sleep(500);

      // Step 3: Press Enter to accept the "new chat" prompt
      logger.log("Pressing Enter to accept prompt...");
      const enterResult1 = sendEnter();
      logger.log(`Enter result: ${enterResult1}`);
      await sleep(600);

      // Step 4: Focus the composer input
      logger.log("Focusing composer...");
      await vscode.commands.executeCommand("composer.focusComposer");
      await sleep(300);

      // Step 5: Paste the command (Ctrl+V via ydotool)
      logger.log("Pasting command...");
      const pasteResult = sendPaste();
      logger.log(`Paste result: ${pasteResult}`);
      await sleep(400);

      // Step 6: Press Enter to submit
      logger.log("Pressing Enter to submit...");
      const enterResult2 = sendEnter();
      logger.log(`Enter result: ${enterResult2}`);

      vscode.window.showInformationMessage(`🚀 Started new chat with ${personaName} persona`);
    } catch (e) {
      logger.error("Failed to start persona chat", e);
      await vscode.env.clipboard.writeText(command);
      vscode.window.showInformationMessage(`📋 Copied: ${command} - Open a new chat and paste.`);
    }
  }

  private async viewPersonaDetails(personaName: string): Promise<void> {
    const persona = this.personas.find((p) => p.name === personaName);
    if (persona && persona.file) {
      const doc = await vscode.workspace.openTextDocument(persona.file);
      await vscode.window.showTextDocument(doc);
    }
  }
}
