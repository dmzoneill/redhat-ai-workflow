/**
 * Sessions Tab
 *
 * Displays active sessions, workspaces, and session management.
 * Uses D-Bus to communicate with the Session daemon.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus } from "./BaseTab";
import { createLogger } from "../logger";
import { PersonaDefinition, ToolModuleInfo } from "../dbusClient";

const logger = createLogger("SessionsTab");

// Default Jira URL - will be loaded from config
const DEFAULT_JIRA_URL = "https://issues.redhat.com";

interface PersonaToolInfo {
  toolCount: number;
  skillCount: number;
}

interface Session {
  id: string;
  name: string;
  project?: string;
  persona?: string;
  created_at: string;
  last_active?: string;
  status: "active" | "idle" | "closed";
  workspace_uri?: string;
  tool_count?: number;
  tool_call_count?: number;
  issue_key?: string;
  is_active?: boolean;
}

interface Workspace {
  uri: string;
  name: string;
  session_id?: string;
  persona?: string;
  tools_loaded?: number;
  last_active?: string;
}

interface SessionStats {
  total_sessions: number;
  active_sessions: number;
  total_tool_calls: number;
  total_skill_runs: number;
}

export class SessionsTab extends BaseTab {
  private sessions: Session[] = [];
  private workspaces: Workspace[] = [];
  private stats: SessionStats | null = null;
  private groupBy: "none" | "project" | "persona" = "project";
  private viewMode: "card" | "table" = "card";
  private searchQuery = "";
  private jiraUrl = DEFAULT_JIRA_URL;
  private personaCache: Map<string, PersonaDefinition> = new Map();
  private toolModuleCache: Map<string, number> = new Map(); // module name -> tool count

  constructor() {
    super({
      id: "sessions",
      label: "Sessions",
      icon: "💬",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    // Show total session count
    if (this.sessions.length > 0) {
      return { text: `${this.sessions.length}` };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load sessions via D-Bus
      logger.log("Calling session_list()...");
      const sessionsResult = await dbus.session_list();
      logger.log(`session_list() result: success=${sessionsResult.success}, hasData=${!!sessionsResult.data}, error=${sessionsResult.error || 'none'}`);
      if (sessionsResult.success && sessionsResult.data) {
        const data = sessionsResult.data as any;
        logger.log(`Data keys: ${Object.keys(data).join(', ')}`);
        const rawSessions = data.sessions || [];
        logger.log(`Raw sessions count: ${rawSessions.length}`);
        if (rawSessions.length > 0) {
          logger.log(`First session keys: ${Object.keys(rawSessions[0]).join(', ')}`);
        }
        // Map D-Bus session data to our Session interface
        this.sessions = rawSessions.map((s: any) => ({
          id: s.session_id || s.id,
          name: s.name || `Session ${(s.session_id || s.id || '').slice(0, 8)}`,
          project: s.project,
          persona: s.persona,
          created_at: s.started_at || s.created_at,
          last_active: s.last_activity || s.last_active,
          status: s.is_active ? "active" : "idle",
          workspace_uri: s.workspace_uri,
          tool_count: s.tool_count || 0,
          tool_call_count: s.tool_call_count || 0,
          issue_key: s.issue_key,
          is_active: s.is_active,
        }));
        logger.log(`Mapped ${this.sessions.length} sessions`);
      } else if (sessionsResult.error) {
        this.lastError = `Session list failed: ${sessionsResult.error}`;
        logger.warn(this.lastError);
      }

      // Load stats via D-Bus
      logger.log("Calling session_getStats()...");
      const statsResult = await dbus.session_getStats();
      logger.log(`session_getStats() result: success=${statsResult.success}, error=${statsResult.error || 'none'}`);
      if (statsResult.success && statsResult.data) {
        const data = statsResult.data as any;
        this.stats = data.stats || data;
        logger.log(`Loaded stats: total=${this.stats?.total_sessions}, active=${this.stats?.active_sessions}`);
      } else if (statsResult.error) {
        logger.warn(`Session stats failed: ${statsResult.error}`);
      }

      // Load tool modules to get actual tool counts per module
      logger.log("Calling config_getToolModules()...");
      const modulesResult = await dbus.config_getToolModules();
      if (modulesResult.success && modulesResult.data) {
        const data = modulesResult.data as any;
        const modules = data.modules || [];
        this.toolModuleCache.clear();
        modules.forEach((m: ToolModuleInfo) => {
          // Store by both full name (aa_git) and short name (git)
          this.toolModuleCache.set(m.name, m.tool_count || 0);
          this.toolModuleCache.set(m.full_name, m.tool_count || 0);
        });
        logger.log(`Loaded ${this.toolModuleCache.size} tool modules into cache`);
      }

      // Load personas for tool/skill counts
      logger.log("Calling config_getPersonasList()...");
      const personasResult = await dbus.config_getPersonasList();
      if (personasResult.success && personasResult.data) {
        const data = personasResult.data as any;
        const personas = data.personas || [];
        this.personaCache.clear();
        personas.forEach((p: PersonaDefinition) => {
          this.personaCache.set(p.name.toLowerCase(), p);
        });
        logger.log(`Loaded ${this.personaCache.size} personas into cache`);
      }

      // Load Jira URL from config
      const configResult = await dbus.config_getConfig();
      if (configResult.success && configResult.data) {
        const config = (configResult.data as any).config || configResult.data;
        if (config.jira?.url) {
          this.jiraUrl = config.jira.url;
          logger.log(`Loaded Jira URL: ${this.jiraUrl}`);
        }
      }

      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  getContent(): string {
    // Show error state if data loading failed
    if (this.lastError) {
      return `
        <div class="section">
          <div class="section-title">💬 Session Overview</div>
          ${this.getErrorHtml(`Failed to load sessions: ${this.lastError}`)}
          <div class="mt-16">
            <button class="btn btn-sm" data-action="refreshSessions">⟳ Retry</button>
          </div>
        </div>
      `;
    }

    const groupTitle = this.groupBy === "project" ? "Sessions by Project"
                     : this.groupBy === "persona" ? "Sessions by Persona"
                     : "All Sessions";

    return `
      <!-- Header with title and controls -->
      <div class="section">
        <div class="session-header">
          <div class="session-header-title">💬 ${groupTitle}</div>
          <div class="session-header-controls">
            <div class="session-search">
              <input type="text" placeholder="🔍 Search chats..." id="sessionSearch" value="${this.escapeHtml(this.searchQuery)}" />
            </div>
            <div class="view-toggle">
              <button id="sessionViewCard" data-action="viewCard" class="toggle-btn ${this.viewMode === "card" ? "active" : ""}">🗂️ Cards</button>
              <button id="sessionViewTable" data-action="viewTable" class="toggle-btn ${this.viewMode === "table" ? "active" : ""}">📋 Table</button>
            </div>
            <div class="session-count">${this.sessions.length} session(s) • Auto-refresh 5s</div>
          </div>
        </div>
      </div>

      <!-- Sessions List -->
      <div class="section">
        ${this.viewMode === "card" ? this.getSessionCardsHtml() : this.getSessionTableHtml()}
      </div>
    `;
  }

  private getSessionCardsHtml(): string {
    const filteredSessions = this.filterSessions();
    const groupedSessions = this.groupSessions(filteredSessions);

    if (Object.keys(groupedSessions).length === 0) {
      return this.getEmptyStateHtml("💬", "No sessions found");
    }

    let html = "";
    for (const [group, sessions] of Object.entries(groupedSessions)) {
      if (this.groupBy !== "none") {
        html += `<div class="session-group-title">${this.escapeHtml(group)}</div>`;
      }
      html += `<div class="session-cards-grid">`;
      sessions.forEach((session) => {
        html += this.getSessionCardHtml(session);
      });
      html += `</div>`;
    }

    return html;
  }

  private getSessionCardHtml(session: Session): string {
    const statusClass = session.status === "active" ? "active" : session.status === "idle" ? "idle" : "closed";
    const statusIcon = session.status === "active" ? "●" : session.status === "idle" ? "◐" : "○";

    return `
      <div class="session-card ${statusClass}" data-session-id="${session.id}">
        <div class="session-card-header">
          <div class="session-card-status ${statusClass}">${statusIcon}</div>
          <div class="session-card-name">${this.escapeHtml(session.name || session.id)}</div>
        </div>
        <div class="session-card-meta">
          ${session.project ? `<span class="session-project">📁 ${this.escapeHtml(session.project)}</span>` : ""}
          ${session.persona ? `<span class="session-persona">${this.getPersonaBadgeHtml(session.persona)}</span>` : ""}
        </div>
        <div class="session-card-stats">
          ${session.tool_count ? `<span>🔧 ${session.tool_count} tools</span>` : ""}
          <span>📅 ${this.formatRelativeTime(session.created_at)}</span>
        </div>
        <div class="session-card-actions">
          <button class="btn btn-xs" data-action="openSession" data-session-id="${session.id}">Open</button>
          <button class="btn btn-xs btn-icon" data-action="copySessionId" data-session-id="${session.id}">📋</button>
          ${session.status !== "closed" ? `<button class="btn btn-xs btn-danger btn-icon" data-action="closeSession" data-session-id="${session.id}">✕</button>` : ""}
        </div>
      </div>
    `;
  }

  private getSessionTableHtml(): string {
    const filteredSessions = this.filterSessions();

    if (filteredSessions.length === 0) {
      return this.getEmptyStateHtml("💬", "No sessions found");
    }

    return `
      <table class="session-table">
        <thead>
          <tr>
            <th></th>
            <th>NAME</th>
            <th>PROJECT</th>
            <th>PERSONA</th>
            <th>ISSUE</th>
            <th>LAST ACTIVE</th>
            <th>TOOLS</th>
            <th>SKILLS</th>
            <th>ACTIONS</th>
          </tr>
        </thead>
        <tbody>
          ${filteredSessions.map((session) => this.getSessionRowHtml(session)).join("")}
        </tbody>
      </table>
    `;
  }

  /**
   * Get tool count for a persona by summing up tools from all its modules
   */
  private getPersonaToolCount(personaName: string | undefined): number {
    if (!personaName) return 0;
    const persona = this.personaCache.get(personaName.toLowerCase());
    if (!persona?.tools) return 0;

    // Sum up tool counts from each module in the persona
    let totalTools = 0;
    for (const moduleName of persona.tools) {
      // Try both the module name as-is and with aa_ prefix
      const count = this.toolModuleCache.get(moduleName)
                 || this.toolModuleCache.get(`aa_${moduleName}`)
                 || 0;
      totalTools += count;
    }
    return totalTools;
  }

  /**
   * Get skill count for a persona
   */
  private getPersonaSkillCount(personaName: string | undefined): number {
    if (!personaName) return 0;
    const persona = this.personaCache.get(personaName.toLowerCase());
    return persona?.skills?.length || 0;
  }

  private getSessionRowHtml(session: Session): string {
    const isActive = session.is_active || session.status === "active";
    const statusIcon = isActive ? "●" : "◐";
    const statusClass = isActive ? "active" : "idle";

    // Format issue keys as clickable links
    const issueKeys = session.issue_key ? session.issue_key.split(',').map(k => k.trim()).filter(k => k) : [];
    const issueHtml = issueKeys.length > 0
      ? issueKeys.slice(0, 3).map(k =>
          `<a href="${this.jiraUrl}/browse/${this.escapeHtml(k)}" class="issue-link" target="_blank">${this.escapeHtml(k)}</a>`
        ).join('')
        + (issueKeys.length > 3 ? `<span class="issue-badge more">+${issueKeys.length - 3}</span>` : '')
      : '-';

    // Get tool and skill counts from persona
    const toolCount = this.getPersonaToolCount(session.persona);
    const skillCount = this.getPersonaSkillCount(session.persona);

    const sessionName = session.name || session.id;

    return `
      <tr class="${statusClass}" data-session-id="${session.id}">
        <td>
          <span class="session-status-icon ${statusClass}">${statusIcon}</span>
        </td>
        <td class="session-name-cell">
          ${isActive ? '<span class="active-badge">ACTIVE</span>' : ''}
          <span class="session-name-link" data-action="openChatSession" data-session-id="${session.id}" data-session-name="${this.escapeHtml(sessionName).replace(/"/g, '&quot;')}" title="Click to find this chat">
            ${this.escapeHtml(sessionName)}
          </span>
        </td>
        <td>${session.project ? this.escapeHtml(session.project) : "-"}</td>
        <td>${session.persona ? this.getPersonaBadgeHtml(session.persona) : "-"}</td>
        <td class="issue-cell">${issueHtml}</td>
        <td>${this.formatRelativeTime(session.last_active)}</td>
        <td class="center">${toolCount || "-"}</td>
        <td class="center">${skillCount || "-"}</td>
        <td class="actions-cell">
          <button class="btn btn-xs btn-icon" data-action="copySessionId" data-session-id="${session.id}" title="Copy ID">📋</button>
          <button class="btn btn-xs btn-icon" data-action="openChatSession" data-session-id="${session.id}" data-session-name="${this.escapeHtml(sessionName).replace(/"/g, '&quot;')}" title="Open Chat">🔗</button>
        </td>
      </tr>
    `;
  }

  private filterSessions(): Session[] {
    let filtered = this.sessions;

    if (this.searchQuery) {
      const query = this.searchQuery.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.name?.toLowerCase().includes(query) ||
          s.id.toLowerCase().includes(query) ||
          s.project?.toLowerCase().includes(query) ||
          s.persona?.toLowerCase().includes(query)
      );
    }

    // Sort by last_active descending (most recent first)
    return filtered.sort((a, b) => {
      const dateA = a.last_active ? new Date(a.last_active).getTime() : 0;
      const dateB = b.last_active ? new Date(b.last_active).getTime() : 0;
      return dateB - dateA;
    });
  }

  private groupSessions(sessions: Session[]): Record<string, Session[]> {
    if (this.groupBy === "none") {
      return { "": sessions };
    }

    const groups: Record<string, Session[]> = {};
    sessions.forEach((session) => {
      const key =
        this.groupBy === "project"
          ? session.project || "No Project"
          : session.persona || "No Persona";
      if (!groups[key]) groups[key] = [];
      groups[key].push(session);
    });

    return groups;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    // Use centralized event delegation system - handlers survive content updates
    // and can be re-registered without duplicates
    return `
      (function() {
        console.log('[SessionsTab] Script running, TabEventDelegation available:', typeof TabEventDelegation !== 'undefined');
        
        // Register click handler for sessions tab
        TabEventDelegation.registerClickHandler('sessions', function(action, element, e) {
          console.log('[SessionsTab] Click handler called with action:', action);
          const sessionId = element.dataset.sessionId;
          
          switch(action) {
            case 'newSession':
              vscode.postMessage({ command: 'newSession' });
              break;
            case 'openSession':
              if (sessionId) vscode.postMessage({ command: 'openSession', sessionId });
              break;
            case 'openChatSession':
              if (sessionId) {
                const sessionName = element.dataset.sessionName;
                vscode.postMessage({ command: 'openChatSession', sessionId, sessionName });
              }
              break;
            case 'copySessionId':
              if (sessionId) vscode.postMessage({ command: 'copySessionId', sessionId });
              break;
            case 'closeSession':
              if (sessionId) vscode.postMessage({ command: 'closeSession', sessionId });
              break;
            case 'refreshSessions':
              vscode.postMessage({ command: 'refreshSessions' });
              break;
            case 'viewCard':
              vscode.postMessage({ command: 'changeSessionViewMode', value: 'card' });
              break;
            case 'viewTable':
              vscode.postMessage({ command: 'changeSessionViewMode', value: 'table' });
              break;
          }
        });

        // Register change handler for dropdowns
        TabEventDelegation.registerChangeHandler('sessions', function(element, e) {
          if (element.id === 'sessionGroupBy') {
            vscode.postMessage({ command: 'changeSessionGroupBy', value: element.value });
          }
        });

        // Register keypress handler for search (Enter key)
        TabEventDelegation.registerKeypressHandler('sessions', function(element, e) {
          if (element.id === 'sessionSearch' && e.key === 'Enter') {
            vscode.postMessage({ command: 'searchSessions', query: element.value });
          }
        });

        // Also handle input event for live search (debounced)
        const sessionsContainer = document.getElementById('sessions');
        if (sessionsContainer && !sessionsContainer.dataset.inputInit) {
          sessionsContainer.dataset.inputInit = 'true';
          sessionsContainer.addEventListener('input', function(e) {
            if (e.target.id === 'sessionSearch') {
              vscode.postMessage({ command: 'searchSessions', query: e.target.value });
            }
          });
        }
      })();
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;
    logger.log(`handleMessage: ${msgType}`);

    switch (msgType) {
      case "searchSessions":
        this.searchQuery = message.query || "";
        logger.log(`searchSessions: query="${this.searchQuery}"`);
        // Trigger re-render to show filtered results
        this.notifyNeedsRender();
        return true;

      case "changeSessionGroupBy":
        this.groupBy = message.value as "none" | "project" | "persona";
        logger.log(`changeSessionGroupBy: groupBy="${this.groupBy}"`);
        // Trigger re-render to show new grouping
        this.notifyNeedsRender();
        return true;

      case "changeSessionViewMode":
        const newViewMode = message.value as "card" | "table";
        logger.log(`changeSessionViewMode: current="${this.viewMode}", new="${newViewMode}"`);
        if (this.viewMode !== newViewMode) {
          this.viewMode = newViewMode;
          logger.log(`changeSessionViewMode: viewMode changed to "${this.viewMode}", calling notifyNeedsRender`);
          this.notifyNeedsRender();
        } else {
          logger.log(`changeSessionViewMode: viewMode unchanged, skipping render`);
        }
        return true;

      case "refreshSessions":
        await this.refresh();
        return true;

      case "newSession":
        await this.createNewSession();
        return true;

      case "openSession":
        await this.openSession(message.sessionId);
        return true;

      // Note: openChatSession is handled by SessionMessageHandler in messageRouter.ts
      // which calls SessionService.openChatSession() - don't duplicate here

      case "copySessionId":
        await this.copySessionId(message.sessionId);
        return true;

      case "closeSession":
        await this.closeSession(message.sessionId);
        return true;

      // === NEW: Workspace handlers (Phase 3.5) ===
      case "viewWorkspaceTools":
        await this.viewWorkspaceTools(message.workspaceUri);
        return true;

      case "switchToWorkspace":
        await this.switchToWorkspace(message.workspaceUri);
        return true;

      case "changeWorkspacePersona":
        await this.changeWorkspacePersona(message.workspaceUri, message.persona);
        return true;

      case "removeWorkspace":
        await this.removeWorkspace(message.workspaceUri);
        return true;

      default:
        return false;
    }
  }

  private async createNewSession(): Promise<void> {
    const result = await dbus.session_start();
    if (!result.success) {
      logger.error("Failed to create session", result.error);
    }
    await this.refresh();
  }

  private async openSession(sessionId: string): Promise<void> {
    // Switch to the session
    const result = await dbus.session_switch(sessionId);
    if (!result.success) {
      logger.error("Failed to switch session", result.error);
    }
  }

  private async copySessionId(sessionId: string): Promise<void> {
    await vscode.env.clipboard.writeText(sessionId);
    vscode.window.showInformationMessage(`Session ID copied: ${sessionId}`);
  }

  private async closeSession(sessionId: string): Promise<void> {
    const result = await dbus.session_close(sessionId);
    if (!result.success) {
      logger.error("Failed to close session", result.error);
    }
    await this.refresh();
  }

  // === NEW: Workspace handlers (Phase 3.5) ===

  private async viewWorkspaceTools(workspaceUri: string): Promise<void> {
    if (!workspaceUri) return;

    try {
      logger.log(`Viewing tools for workspace: ${workspaceUri}`);
      const result = await dbus.workspace_getTools(workspaceUri);
      if (result.success && result.data) {
        const data = result.data as any;
        const tools = data.tools || [];
        
        // Show tools in a quick pick or information message
        if (tools.length > 0) {
          const toolList = tools.slice(0, 20).map((t: any) => t.name || t).join(', ');
          const more = tools.length > 20 ? ` (+${tools.length - 20} more)` : '';
          vscode.window.showInformationMessage(`Workspace Tools: ${toolList}${more}`);
        } else {
          vscode.window.showInformationMessage("No tools loaded for this workspace");
        }
      } else {
        vscode.window.showErrorMessage(`Failed to get workspace tools: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error getting workspace tools: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async switchToWorkspace(workspaceUri: string): Promise<void> {
    if (!workspaceUri) return;

    try {
      logger.log(`Switching to workspace: ${workspaceUri}`);
      const result = await dbus.workspace_switch(workspaceUri);
      if (result.success) {
        vscode.window.showInformationMessage(`Switched to workspace`);
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to switch workspace: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error switching workspace: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async changeWorkspacePersona(workspaceUri: string, persona: string): Promise<void> {
    if (!workspaceUri) return;

    try {
      // If no persona provided, show a quick pick
      let selectedPersona = persona;
      if (!selectedPersona) {
        const personas = Array.from(this.personaCache.keys());
        selectedPersona = await vscode.window.showQuickPick(personas, {
          placeHolder: "Select a persona for this workspace",
        }) || "";
      }

      if (!selectedPersona) return;

      logger.log(`Changing workspace ${workspaceUri} persona to: ${selectedPersona}`);
      const result = await dbus.workspace_setPersona(workspaceUri, selectedPersona);
      if (result.success) {
        vscode.window.showInformationMessage(`Workspace persona changed to: ${selectedPersona}`);
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to change persona: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error changing persona: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async removeWorkspace(workspaceUri: string): Promise<void> {
    if (!workspaceUri) return;

    try {
      // Confirm removal
      const confirm = await vscode.window.showWarningMessage(
        `Remove workspace from tracking?`,
        { modal: true },
        "Remove"
      );

      if (confirm !== "Remove") return;

      logger.log(`Removing workspace: ${workspaceUri}`);
      const result = await dbus.workspace_remove(workspaceUri);
      if (result.success) {
        vscode.window.showInformationMessage("Workspace removed");
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to remove workspace: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error removing workspace: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}
