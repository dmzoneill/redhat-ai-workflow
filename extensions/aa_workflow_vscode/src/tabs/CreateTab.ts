/**
 * Create Tab
 *
 * Provides UI for building "super prompts" with context engineering:
 * - Context Builder: Select personas, skills, tools, memory, meetings, slack, code search
 * - Ralph Wiggum Loop: Configure autonomous task loops with TODO.md tracking
 * - Session Inspector: View/analyze Claude Console and Gemini sessions
 * - Cursor DB Integration: Inject context into Cursor chats
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("CreateTab");

interface RalphLoopConfig {
  session_id: string;
  max_iterations: number;
  current_iteration: number;
  todo_path: string;
  completion_criteria: string[];
  started_at: string;
  workspace_path?: string;
}

interface PersonaInfo {
  id: string;
  name: string;
  description: string;
}

interface SkillInfo {
  id: string;
  name: string;
  category: string;
}

export class CreateTab extends BaseTab {
  private personas: PersonaInfo[] = [];
  private skills: SkillInfo[] = [];
  private activeLoops: RalphLoopConfig[] = [];
  private selectedPersona: string | null = null;
  private ralphEnabled = false;

  constructor() {
    super({
      id: "create",
      label: "Create",
      icon: "✨",
    });
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load personas
      logger.log("Calling config_getPersonasList()...");
      const personasResult = await dbus.config_getPersonasList();
      logger.log(`config_getPersonasList() result: success=${personasResult.success}, error=${personasResult.error || 'none'}`);
      if (personasResult.success && personasResult.data) {
        const data = personasResult.data as any;
        this.personas = (data.personas || []).map((p: any) => ({
          id: p.name,
          name: p.name.charAt(0).toUpperCase() + p.name.slice(1),
          description: p.description || `${p.name} persona`,
        }));
        logger.log(`Loaded ${this.personas.length} personas`);
      } else if (personasResult.error) {
        logger.warn(`Personas list failed: ${personasResult.error}`);
      }

      // Load skills
      logger.log("Calling config_getSkillsList()...");
      const skillsResult = await dbus.config_getSkillsList();
      logger.log(`config_getSkillsList() result: success=${skillsResult.success}, error=${skillsResult.error || 'none'}`);
      if (skillsResult.success && skillsResult.data) {
        const data = skillsResult.data as any;
        this.skills = (data.skills || []).map((s: any) => ({
          id: s.name,
          name: s.name.replace(/_/g, " "),
          category: "general",
        }));
        logger.log(`Loaded ${this.skills.length} skills`);
      } else if (skillsResult.error) {
        this.lastError = `Skills list failed: ${skillsResult.error}`;
        logger.warn(this.lastError);
      }
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  getContent(): string {
    return `
      <!-- Issue Key Auto-Context -->
      <div class="section">
        <div class="section-title">🎯 Quick Start</div>
        <div class="create-quick-start">
          <input type="text" id="issueKeyInput" placeholder="AAP-12345" class="create-issue-input" />
          <button class="btn btn-sm btn-primary" data-action="autoContext">
            ✨ Auto-Context
          </button>
        </div>
        <div id="jiraPreviewContainer" class="create-jira-preview"></div>
      </div>

      <!-- Persona Selection -->
      <div class="section">
        <div class="section-title">🤖 Persona</div>
        <div class="create-persona-selector">
          ${this.personas.map((p) => `
            <div class="create-persona-chip ${this.selectedPersona === p.id ? "selected" : ""}"
                 data-action="selectPersona" data-persona-id="${p.id}">
              ${this.escapeHtml(p.name)}
            </div>
          `).join("")}
          ${this.personas.length === 0 ? '<div class="empty-state-mini">No personas found</div>' : ""}
        </div>
      </div>

      <!-- Context Builder -->
      <div class="section">
        <div class="section-title">🧩 Context Builder</div>
        <div class="create-context-builder">
          <!-- Skills & Tools Column -->
          <div class="create-context-column">
            <div class="create-context-group">
              <div class="create-context-title">⚡ Skills (${this.skills.length})</div>
              <div class="create-context-list" id="skillSourceList">
                ${this.skills.slice(0, 20).map((s) => `
                  <div class="create-context-item" data-source="skill" data-skill-id="${s.id}">
                    <input type="checkbox" />
                    <span class="create-context-name">${this.escapeHtml(s.name)}</span>
                    <span class="create-context-meta">${this.escapeHtml(s.category)}</span>
                  </div>
                `).join("")}
                ${this.skills.length === 0 ? '<div class="empty-state-mini">No skills found</div>' : ""}
              </div>
            </div>

            <div class="create-context-group">
              <div class="create-context-title">🔧 Tools</div>
              <div class="create-context-list" id="toolSourceList">
                <div class="empty-state-mini" id="toolsPlaceholder">Select a persona to load tools</div>
              </div>
            </div>
          </div>

          <!-- Memory, Slack, Code Column -->
          <div class="create-context-column">
            <div class="create-context-group">
              <div class="create-context-title">🧠 Memory</div>
              <div class="create-context-list" id="memorySourceList">
                <div class="create-context-item selected" data-source="memory" data-path="state/current_work">
                  <input type="checkbox" checked />
                  <span class="create-context-name">Current Work</span>
                </div>
                <div class="create-context-item selected" data-source="memory" data-path="learned/patterns">
                  <input type="checkbox" checked />
                  <span class="create-context-name">Learned Patterns</span>
                </div>
                <div class="create-context-item" data-source="memory" data-path="state/environments">
                  <input type="checkbox" />
                  <span class="create-context-name">Environments</span>
                </div>
                <div class="create-context-item" data-source="memory" data-path="state/session_history">
                  <input type="checkbox" />
                  <span class="create-context-name">Session History</span>
                </div>
              </div>
            </div>

            <div class="create-context-group">
              <div class="create-context-title">💬 Slack Search</div>
              <div class="create-search-group">
                <input type="text" id="slackSearchQuery" placeholder="Search Slack messages..." />
                <button class="btn btn-xs" data-action="searchSlack">🔍</button>
              </div>
              <div id="slackSearchResults"></div>
            </div>

            <div class="create-context-group">
              <div class="create-context-title">🔎 Code Search</div>
              <div class="create-search-group">
                <input type="text" id="codeSearchQuery" placeholder="Semantic code search..." />
                <button class="btn btn-xs" data-action="searchCode">🔍</button>
              </div>
              <div id="codeSearchResults"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Ralph Wiggum Loop -->
      <div class="section">
        <div class="section-title">🔄 Ralph Wiggum Loop</div>
        <div class="create-ralph-config">
          <div class="create-ralph-toggle">
            <div class="toggle-switch ${this.ralphEnabled ? "active" : ""}" id="ralphToggle" data-action="toggleRalph"></div>
            <span class="create-ralph-label">Enable Autonomous Loop</span>
          </div>

          <div class="create-ralph-options ${this.ralphEnabled ? "visible" : ""}" id="ralphOptions">
            <div class="create-ralph-option">
              <label>Goals (TODO.md will be generated)</label>
              <textarea id="ralphGoals" placeholder="Describe what you want to accomplish..."></textarea>
            </div>

            <div class="create-ralph-option">
              <label>Completion Criteria</label>
              <input type="text" id="ralphCriteria" placeholder="e.g., All tests pass, No linter errors" />
            </div>

            <div class="create-ralph-option">
              <label>Max Iterations</label>
              <div class="create-ralph-slider">
                <input type="range" id="ralphMaxIterations" min="1" max="50" value="10" />
                <span id="ralphMaxIterationsValue">10</span>
              </div>
            </div>
          </div>

          <div class="create-active-loops" id="activeLoopsPanel">
            <div class="create-active-loops-title">Active Loops</div>
            ${this.renderActiveLoops()}
          </div>
        </div>
      </div>

      <!-- Session Inspector -->
      <div class="section">
        <div class="section-title">🔍 Session Inspector</div>
        <div class="create-session-inspector">
          <div class="create-session-source">
            <div class="create-session-header">
              <span class="create-session-icon">🟣</span>
              <span>Cursor Chats</span>
            </div>
            <div class="create-session-list" id="cursorSessionList">
              <div class="empty-state-mini">Loading...</div>
            </div>
          </div>

          <div class="create-session-source">
            <div class="create-session-header">
              <span class="create-session-icon">🟠</span>
              <span>Claude Code</span>
            </div>
            <div class="create-session-list" id="claudeSessionList">
              <div class="empty-state-mini">No sessions found</div>
            </div>
          </div>

          <div class="create-session-source">
            <div class="create-session-header">
              <span class="create-session-icon">🔵</span>
              <span>Gemini</span>
            </div>
            <div class="create-session-list" id="geminiSessionList">
              <div class="empty-state-mini">No sessions found</div>
            </div>
            <button class="btn btn-xs" data-action="importGemini">📥 Import</button>
          </div>
        </div>
      </div>

      <!-- Prompt Preview -->
      <div class="section">
        <div class="section-title">📝 Preview</div>
        <div class="create-prompt-preview">
          <div class="create-prompt-header">
            <span>Super Prompt Preview</span>
            <div class="create-token-count">
              <span>Estimated:</span>
              <span class="create-token-value" id="tokenCount">0</span>
              <span>tokens</span>
            </div>
          </div>
          <div class="create-prompt-content" id="promptPreviewContent">
            <div class="empty-state-mini">Select context sources to build your super prompt</div>
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="create-actions">
        <button class="btn btn-sm btn-danger" data-action="clearAll">🗑️ Clear All</button>
        <button class="btn btn-sm btn-primary" data-action="saveTemplate">💾 Save Template</button>
        <button class="btn btn-sm btn-primary" data-action="createSession">🚀 Create Session</button>
      </div>
    `;
  }

  private renderActiveLoops(): string {
    if (this.activeLoops.length === 0) {
      return '<div class="empty-state-mini">No active loops</div>';
    }

    return this.activeLoops.map((loop) => {
      const progress = loop.max_iterations > 0
        ? Math.round((loop.current_iteration / loop.max_iterations) * 100)
        : 0;

      return `
        <div class="create-loop-card" data-session-id="${this.escapeHtml(loop.session_id)}">
          <div class="create-loop-info">
            <div class="create-loop-session">${this.escapeHtml(loop.session_id.substring(0, 8))}...</div>
            <div class="create-loop-progress">Iteration ${loop.current_iteration}/${loop.max_iterations}</div>
            <div class="create-loop-bar">
              <div class="create-loop-fill" style="width: ${progress}%;"></div>
            </div>
          </div>
          <button class="btn btn-xs btn-danger" data-action="stopLoop" data-session-id="${this.escapeHtml(loop.session_id)}">
            ⏹ Stop
          </button>
        </div>
      `;
    }).join("");
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    // Use centralized event delegation system - handlers survive content updates
    return `
      (function() {
        const createContainer = document.getElementById('create');

        function gatherConfig() {
          return {
            issueKey: document.getElementById('issueKeyInput')?.value || '',
            persona: document.querySelector('.create-persona-chip.selected')?.getAttribute('data-persona-id') || null,
            ralph: {
              enabled: document.getElementById('ralphToggle')?.classList.contains('active') || false,
              goals: document.getElementById('ralphGoals')?.value || '',
              criteria: document.getElementById('ralphCriteria')?.value || '',
              maxIterations: parseInt(document.getElementById('ralphMaxIterations')?.value || '10')
            }
          };
        }

        function clearAllSelections() {
          const issueInput = document.getElementById('issueKeyInput');
          if (issueInput) issueInput.value = '';
          if (createContainer) {
            createContainer.querySelectorAll('.create-persona-chip').forEach(c => c.classList.remove('selected'));
            createContainer.querySelectorAll('.create-context-item input[type="checkbox"]').forEach(cb => {
              cb.checked = false;
              cb.closest('.create-context-item')?.classList.remove('selected');
            });
          }
        }

        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('create', function(action, element, e) {
          switch (action) {
            case 'autoContext': {
              const issueKey = document.getElementById('issueKeyInput')?.value;
              if (issueKey) {
                vscode.postMessage({ command: 'createAutoContext', issueKey: issueKey });
              }
              break;
            }
            case 'searchSlack': {
              const slackQuery = document.getElementById('slackSearchQuery')?.value;
              if (slackQuery) {
                vscode.postMessage({ command: 'createSearchSlack', query: slackQuery });
              }
              break;
            }
            case 'searchCode': {
              const codeQuery = document.getElementById('codeSearchQuery')?.value;
              if (codeQuery) {
                vscode.postMessage({ command: 'createSearchCode', query: codeQuery });
              }
              break;
            }
            case 'toggleRalph': {
              const ralphToggle = document.getElementById('ralphToggle');
              const ralphOptions = document.getElementById('ralphOptions');
              if (ralphToggle) {
                ralphToggle.classList.toggle('active');
                if (ralphOptions) {
                  ralphOptions.classList.toggle('visible', ralphToggle.classList.contains('active'));
                }
              }
              break;
            }
            case 'stopLoop': {
              const sessionId = element.getAttribute('data-session-id');
              if (sessionId) {
                vscode.postMessage({ command: 'createStopLoop', sessionId: sessionId });
              }
              break;
            }
            case 'createSession':
              vscode.postMessage({ command: 'createSession', config: gatherConfig() });
              break;
            case 'clearAll':
              clearAllSelections();
              break;
            case 'saveTemplate':
              vscode.postMessage({ command: 'createSaveTemplate', config: gatherConfig() });
              break;
            case 'importGemini':
              vscode.postMessage({ command: 'createImportGemini' });
              break;
          }
        });

        // Additional click handling for non-data-action elements
        if (createContainer && !createContainer.dataset.extraClickInit) {
          createContainer.dataset.extraClickInit = 'true';
          
          createContainer.addEventListener('click', function(e) {
            const target = e.target;
            // Skip if already handled by data-action
            if (target.closest('[data-action]')) return;
            
            // Ralph toggle (also has data-action but we handle it specially)
            if (target.id === 'ralphToggle' || target.closest('#ralphToggle')) {
              const ralphToggle = document.getElementById('ralphToggle');
              const ralphOptions = document.getElementById('ralphOptions');
              if (ralphToggle) {
                ralphToggle.classList.toggle('active');
                if (ralphOptions) {
                  ralphOptions.classList.toggle('visible', ralphToggle.classList.contains('active'));
                }
              }
              return;
            }
            
            // Context item selection
            const contextItem = target.closest('.create-context-item');
            if (contextItem) {
              if (target.tagName !== 'INPUT') {
                const checkbox = contextItem.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = !checkbox.checked;
              }
              contextItem.classList.toggle('selected', contextItem.querySelector('input')?.checked);
              return;
            }
            
            // Persona chip selection
            const personaChip = target.closest('.create-persona-chip');
            if (personaChip) {
              createContainer.querySelectorAll('.create-persona-chip').forEach(c => c.classList.remove('selected'));
              personaChip.classList.add('selected');
              const personaId = personaChip.getAttribute('data-persona-id');
              vscode.postMessage({ command: 'createSelectPersona', personaId: personaId });
              return;
            }
          });

          // Input delegation for slider
          createContainer.addEventListener('input', function(e) {
            if (e.target.id === 'ralphMaxIterations') {
              const maxIterValue = document.getElementById('ralphMaxIterationsValue');
              if (maxIterValue) {
                maxIterValue.textContent = e.target.value;
              }
            }
          });
        }
      })();
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "createSelectPersona":
        this.selectedPersona = message.personaId;
        return true;

      case "createAutoContext":
      case "createSearchSlack":
      case "createSearchCode":
      case "createSession":
      case "createSaveTemplate":
      case "createStopLoop":
      case "createImportGemini":
        // These are handled by the main CommandCenterPanel
        return false;

      default:
        return false;
    }
  }
}
