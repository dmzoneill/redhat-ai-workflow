/**
 * Create Session Tab for Command Center
 *
 * Provides UI for building "super prompts" with context engineering:
 * - Context Builder: Select personas, skills, tools, memory, meetings, slack, code search
 * - Ralph Wiggum Loop: Configure autonomous task loops with TODO.md tracking
 * - Session Inspector: View/analyze Claude Console and Gemini sessions
 * - Cursor DB Integration: Inject context into Cursor chats
 *
 * This tab enables users to create highly contextual prompts for AI sessions.
 */

import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// Config directory for Ralph Wiggum loops
const AA_CONFIG_DIR = path.join(os.homedir(), ".config", "aa-workflow");
const RALPH_LOOPS_DIR = path.join(AA_CONFIG_DIR, "ralph_loops");

// ==================== INTERFACES ====================

export interface RalphLoopConfig {
  session_id: string;
  max_iterations: number;
  current_iteration: number;
  todo_path: string;
  completion_criteria: string[];
  started_at: string;
  workspace_path?: string;
}

export interface ContextSource {
  type: "persona" | "skill" | "tool" | "memory" | "meeting" | "slack" | "code" | "jira";
  id: string;
  name: string;
  selected: boolean;
  preview?: string;
  tokens?: number;
}

export interface ExternalSession {
  id: string;
  source: "claude" | "gemini";
  name: string;
  timestamp: string;
  messageCount: number;
  preview?: string;
}

export interface CreateSessionState {
  selectedPersona: string | null;
  selectedSkills: string[];
  selectedTools: string[];
  memoryPaths: string[];
  slackQuery: string;
  codeQuery: string;
  issueKey: string;
  ralphEnabled: boolean;
  ralphConfig: Partial<RalphLoopConfig>;
  activeLoops: RalphLoopConfig[];
}

// ==================== STATE LOADING ====================

/**
 * Load active Ralph Wiggum loops
 */
export function loadActiveLoops(): RalphLoopConfig[] {
  const loops: RalphLoopConfig[] = [];

  try {
    if (fs.existsSync(RALPH_LOOPS_DIR)) {
      const files = fs.readdirSync(RALPH_LOOPS_DIR).filter(f => f.startsWith("session_") && f.endsWith(".json"));
      for (const file of files) {
        try {
          const content = fs.readFileSync(path.join(RALPH_LOOPS_DIR, file), "utf-8");
          loops.push(JSON.parse(content));
        } catch (e) {
          console.error(`Failed to load loop config ${file}:`, e);
        }
      }
    }
  } catch (e) {
    console.error("Failed to list ralph loops:", e);
  }

  return loops.sort((a, b) => b.started_at.localeCompare(a.started_at));
}

/**
 * Load available personas from personas directory
 */
export function loadPersonaList(): { id: string; name: string; description: string }[] {
  const personasDir = path.join(os.homedir(), "src", "redhat-ai-workflow", "personas");
  const personas: { id: string; name: string; description: string }[] = [];

  try {
    if (fs.existsSync(personasDir)) {
      const files = fs.readdirSync(personasDir).filter(f => f.endsWith(".yaml"));
      for (const file of files) {
        const id = file.replace(".yaml", "");
        // Simple name extraction
        personas.push({
          id,
          name: id.charAt(0).toUpperCase() + id.slice(1),
          description: `${id} persona`
        });
      }
    }
  } catch (e) {
    console.error("Failed to load personas:", e);
  }

  return personas;
}

/**
 * Load available skills from skills directory
 */
export function loadSkillList(): { id: string; name: string; category: string }[] {
  const skillsDir = path.join(os.homedir(), "src", "redhat-ai-workflow", "skills");
  const skills: { id: string; name: string; category: string }[] = [];

  try {
    if (fs.existsSync(skillsDir)) {
      const files = fs.readdirSync(skillsDir, { withFileTypes: true });
      for (const file of files) {
        if (file.isFile() && file.name.endsWith(".yaml")) {
          const id = file.name.replace(".yaml", "");
          skills.push({
            id,
            name: id.replace(/_/g, " "),
            category: "general"
          });
        } else if (file.isDirectory()) {
          // Handle subdirectories like performance/
          const subDir = path.join(skillsDir, file.name);
          const subFiles = fs.readdirSync(subDir).filter(f => f.endsWith(".yaml"));
          for (const subFile of subFiles) {
            const id = `${file.name}/${subFile.replace(".yaml", "")}`;
            skills.push({
              id,
              name: subFile.replace(".yaml", "").replace(/_/g, " "),
              category: file.name
            });
          }
        }
      }
    }
  } catch (e) {
    console.error("Failed to load skills:", e);
  }

  return skills;
}

// ==================== HELPER FUNCTIONS ====================

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return timestamp;
  }
}

// ==================== CSS STYLES ====================

export function getCreateSessionTabStyles(): string {
  return `
    /* Create Session Tab Styles */
    .create-session-container {
      padding: 0;
    }

    /* Section Cards */
    .create-section {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 12px;
      padding: 16px;
      margin-bottom: 16px;
    }

    .create-section-header {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border-color);
    }

    .create-section-title {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
      flex: 1;
    }

    .create-section-subtitle {
      font-size: 0.85rem;
      color: var(--text-muted);
    }

    /* Context Builder */
    .context-builder {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }

    .context-source-group {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 12px;
    }

    .context-source-title {
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .context-source-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      max-height: 200px;
      overflow-y: auto;
    }

    .context-source-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      background: var(--card-bg);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s ease;
      border: 1px solid transparent;
    }

    .context-source-item:hover {
      border-color: var(--accent-color);
    }

    .context-source-item.selected {
      background: rgba(99, 102, 241, 0.15);
      border-color: var(--accent-color);
    }

    .context-source-item input[type="checkbox"] {
      margin: 0;
    }

    .context-source-name {
      flex: 1;
      font-size: 0.85rem;
      color: var(--text-primary);
    }

    .context-source-tokens {
      font-size: 0.75rem;
      color: var(--text-muted);
      background: var(--bg-secondary);
      padding: 2px 6px;
      border-radius: 4px;
    }

    /* Search Inputs */
    .search-input-group {
      margin-top: 12px;
    }

    .search-input-label {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }

    .search-input {
      width: 100%;
      padding: 8px 12px;
      border: 1px solid var(--border-color);
      border-radius: 6px;
      background: var(--card-bg);
      color: var(--text-primary);
      font-size: 0.85rem;
    }

    .search-input:focus {
      outline: none;
      border-color: var(--accent-color);
    }

    .search-btn {
      margin-top: 8px;
      padding: 6px 12px;
      background: rgba(99, 102, 241, 0.15);
      color: var(--accent-color);
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.8rem;
      font-weight: 500;
    }

    .search-btn:hover {
      background: rgba(99, 102, 241, 0.25);
    }

    /* Issue Key Input */
    .issue-key-input {
      display: flex;
      gap: 8px;
      align-items: center;
      margin-bottom: 16px;
    }

    .issue-key-input input {
      flex: 1;
      padding: 10px 14px;
      border: 2px solid var(--border-color);
      border-radius: 8px;
      background: var(--card-bg);
      color: var(--text-primary);
      font-size: 1rem;
      font-weight: 500;
    }

    .issue-key-input input:focus {
      outline: none;
      border-color: var(--accent-color);
    }

    .auto-context-btn {
      padding: 10px 16px;
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
      white-space: nowrap;
    }

    .auto-context-btn:hover {
      opacity: 0.9;
    }

    /* Ralph Wiggum Config */
    .ralph-config {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 16px;
    }

    .ralph-toggle {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 16px;
    }

    .ralph-toggle-switch {
      position: relative;
      width: 48px;
      height: 26px;
      background: var(--border-color);
      border-radius: 13px;
      cursor: pointer;
      transition: background 0.2s ease;
    }

    .ralph-toggle-switch.active {
      background: #10b981;
    }

    .ralph-toggle-switch::after {
      content: '';
      position: absolute;
      top: 3px;
      left: 3px;
      width: 20px;
      height: 20px;
      background: white;
      border-radius: 50%;
      transition: transform 0.2s ease;
    }

    .ralph-toggle-switch.active::after {
      transform: translateX(22px);
    }

    .ralph-toggle-label {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .ralph-options {
      display: none;
      flex-direction: column;
      gap: 12px;
    }

    .ralph-options.visible {
      display: flex;
    }

    .ralph-option {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .ralph-option label {
      font-size: 0.8rem;
      color: var(--text-secondary);
    }

    .ralph-option input,
    .ralph-option textarea {
      padding: 8px 12px;
      border: 1px solid var(--border-color);
      border-radius: 6px;
      background: var(--card-bg);
      color: var(--text-primary);
      font-size: 0.85rem;
    }

    .ralph-option textarea {
      min-height: 150px;
      resize: vertical;
      font-family: monospace;
    }

    .ralph-slider {
      display: flex;
      align-items: center;
      gap: 12px;
    }

    .ralph-slider input[type="range"] {
      flex: 1;
    }

    .ralph-slider-value {
      min-width: 40px;
      text-align: center;
      font-weight: 600;
      color: var(--text-primary);
    }

    /* Active Loops Panel */
    .active-loops {
      margin-top: 16px;
    }

    .active-loops-title {
      font-size: 0.9rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 8px;
    }

    .active-loop-card {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      background: var(--card-bg);
      border-radius: 8px;
      border: 1px solid var(--border-color);
      margin-bottom: 8px;
    }

    .active-loop-info {
      flex: 1;
    }

    .active-loop-session {
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--text-primary);
    }

    .active-loop-progress {
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .active-loop-progress-bar {
      width: 100px;
      height: 4px;
      background: var(--bg-secondary);
      border-radius: 2px;
      overflow: hidden;
      margin-top: 4px;
    }

    .active-loop-progress-fill {
      height: 100%;
      background: #10b981;
      transition: width 0.3s ease;
    }

    .active-loop-stop {
      padding: 6px 12px;
      background: rgba(239, 68, 68, 0.15);
      color: #ef4444;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.8rem;
      font-weight: 500;
    }

    .active-loop-stop:hover {
      background: rgba(239, 68, 68, 0.25);
    }

    /* Session Inspector */
    .session-inspector {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }

    .session-source {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 12px;
    }

    .session-source-header {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 12px;
    }

    .session-source-icon {
      font-size: 1.5rem;
    }

    .session-source-name {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .session-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 200px;
      overflow-y: auto;
    }

    .session-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: var(--card-bg);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s ease;
      border: 1px solid transparent;
    }

    .session-item:hover {
      border-color: var(--accent-color);
    }

    .session-item-info {
      flex: 1;
    }

    .session-item-name {
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--text-primary);
    }

    .session-item-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    .session-item-actions {
      display: flex;
      gap: 4px;
    }

    .session-action-btn {
      padding: 4px 8px;
      background: rgba(99, 102, 241, 0.15);
      color: var(--accent-color);
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.75rem;
    }

    .session-action-btn:hover {
      background: rgba(99, 102, 241, 0.25);
    }

    /* Super Prompt Preview */
    .prompt-preview {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 16px;
    }

    .prompt-preview-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }

    .prompt-preview-title {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .prompt-preview-tokens {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.85rem;
    }

    .token-count {
      font-weight: 600;
      color: var(--accent-color);
    }

    .token-warning {
      color: #f59e0b;
    }

    .token-danger {
      color: #ef4444;
    }

    .prompt-preview-content {
      background: var(--card-bg);
      border-radius: 6px;
      padding: 12px;
      max-height: 300px;
      overflow-y: auto;
      font-family: monospace;
      font-size: 0.8rem;
      line-height: 1.5;
      color: var(--text-secondary);
      white-space: pre-wrap;
    }

    .prompt-preview-section {
      margin-bottom: 12px;
      padding-bottom: 12px;
      border-bottom: 1px dashed var(--border-color);
    }

    .prompt-preview-section:last-child {
      margin-bottom: 0;
      padding-bottom: 0;
      border-bottom: none;
    }

    .prompt-preview-section-title {
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 4px;
    }

    /* Action Buttons */
    .create-session-actions {
      display: flex;
      gap: 12px;
      justify-content: flex-end;
      margin-top: 16px;
    }

    .create-btn {
      padding: 12px 24px;
      border-radius: 8px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .create-btn.primary {
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      color: white;
      border: none;
    }

    .create-btn.primary:hover {
      opacity: 0.9;
      transform: translateY(-1px);
    }

    .create-btn.secondary {
      background: var(--bg-secondary);
      color: var(--text-primary);
      border: 1px solid var(--border-color);
    }

    .create-btn.secondary:hover {
      background: var(--card-bg);
      border-color: var(--accent-color);
    }

    /* Empty State */
    .create-empty {
      text-align: center;
      padding: 32px;
      color: var(--text-muted);
    }

    .create-empty-icon {
      font-size: 2.5rem;
      margin-bottom: 12px;
    }

    /* Persona Selector */
    .persona-selector {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .persona-chip {
      padding: 8px 16px;
      background: var(--bg-secondary);
      border: 1px solid var(--border-color);
      border-radius: 20px;
      cursor: pointer;
      font-size: 0.85rem;
      color: var(--text-secondary);
      transition: all 0.2s ease;
    }

    .persona-chip:hover {
      border-color: var(--accent-color);
      color: var(--text-primary);
    }

    .persona-chip.selected {
      background: linear-gradient(135deg, #6366f1, #8b5cf6);
      border-color: transparent;
      color: white;
      font-weight: 600;
      box-shadow: 0 2px 8px rgba(99, 102, 241, 0.4);
    }

    /* Jira Issue Preview */
    .jira-preview {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 12px;
      margin-top: 12px;
      border-left: 3px solid #6366f1;
    }

    .jira-preview-title {
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 8px;
    }

    .jira-preview-field {
      font-size: 0.85rem;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }

    .jira-preview-field strong {
      color: var(--text-primary);
    }

    .jira-preview-description {
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--border-color);
      max-height: 100px;
      overflow-y: auto;
    }

    .loading-spinner {
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid var(--border-color);
      border-top-color: var(--accent-color);
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-right: 8px;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  `;
}

// ==================== HTML GENERATION ====================

function renderActiveLoops(loops: RalphLoopConfig[]): string {
  if (loops.length === 0) {
    return `
      <div class="create-empty" style="padding: 16px;">
        <div>No active loops</div>
        <div style="font-size: 0.8rem; margin-top: 4px;">Start a Ralph Wiggum loop to see it here</div>
      </div>
    `;
  }

  return loops.map(loop => {
    const progress = loop.max_iterations > 0
      ? Math.round((loop.current_iteration / loop.max_iterations) * 100)
      : 0;

    return `
      <div class="active-loop-card" data-session-id="${escapeHtml(loop.session_id)}">
        <div class="active-loop-info">
          <div class="active-loop-session">${escapeHtml(loop.session_id.substring(0, 8))}...</div>
          <div class="active-loop-progress">
            Iteration ${loop.current_iteration}/${loop.max_iterations}
          </div>
          <div class="active-loop-progress-bar">
            <div class="active-loop-progress-fill" style="width: ${progress}%;"></div>
          </div>
        </div>
        <button class="active-loop-stop" data-action="stopLoop" data-session-id="${escapeHtml(loop.session_id)}">
          ⏹ Stop
        </button>
      </div>
    `;
  }).join("");
}

function renderPersonaSelector(personas: { id: string; name: string }[], selectedPersona: string | null): string {
  return `
    <div class="persona-selector">
      ${personas.map(p => `
        <div class="persona-chip ${selectedPersona === p.id ? 'selected' : ''}"
             data-action="selectPersona" data-persona-id="${escapeHtml(p.id)}">
          ${escapeHtml(p.name)}
        </div>
      `).join("")}
    </div>
  `;
}

function renderContextBuilder(): string {
  // Load skills at render time
  const skills = loadSkillList();
  const skillsHtml = skills.length > 0
    ? skills.slice(0, 20).map(s => `
        <div class="context-source-item" data-source="skill" data-skill-id="${escapeHtml(s.id)}">
          <input type="checkbox" />
          <span class="context-source-name">${escapeHtml(s.name)}</span>
          <span class="context-source-tokens">${escapeHtml(s.category)}</span>
        </div>
      `).join("")
    : '<div class="create-empty" style="padding: 12px; font-size: 0.8rem;">No skills found</div>';

  return `
    <div class="context-builder">
      <!-- Left Column: Skills & Tools -->
      <div>
        <div class="context-source-group">
          <div class="context-source-title">
            <span>⚡</span> Skills (${skills.length})
          </div>
          <div class="context-source-list" id="skillSourceList">
            ${skillsHtml}
          </div>
        </div>

        <div class="context-source-group" style="margin-top: 12px;">
          <div class="context-source-title">
            <span>🔧</span> Tools
          </div>
          <div class="context-source-list" id="toolSourceList">
            <div class="create-empty" style="padding: 12px; font-size: 0.8rem;">
              <span id="toolsPlaceholder">Select a persona to load tools</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Memory, Slack, Code Search -->
      <div>
        <div class="context-source-group">
          <div class="context-source-title">
            <span>🧠</span> Memory
          </div>
          <div class="context-source-list" id="memorySourceList">
            <div class="context-source-item" data-source="memory" data-path="state/current_work">
              <input type="checkbox" checked />
              <span class="context-source-name">Current Work</span>
            </div>
            <div class="context-source-item" data-source="memory" data-path="learned/patterns">
              <input type="checkbox" checked />
              <span class="context-source-name">Learned Patterns</span>
            </div>
            <div class="context-source-item" data-source="memory" data-path="state/environments">
              <input type="checkbox" />
              <span class="context-source-name">Environments</span>
            </div>
            <div class="context-source-item" data-source="memory" data-path="state/session_history">
              <input type="checkbox" />
              <span class="context-source-name">Session History</span>
            </div>
          </div>
        </div>

        <div class="context-source-group" style="margin-top: 12px;">
          <div class="context-source-title">
            <span>💬</span> Slack Search
          </div>
          <div class="search-input-group">
            <input type="text" class="search-input" id="slackSearchQuery"
                   placeholder="Search Slack messages..." />
            <button class="search-btn" data-action="searchSlack">🔍 Search</button>
          </div>
          <div id="slackSearchResults" style="margin-top: 8px;"></div>
        </div>

        <div class="context-source-group" style="margin-top: 12px;">
          <div class="context-source-title">
            <span>🔎</span> Code Search (Vector)
          </div>
          <div class="search-input-group">
            <input type="text" class="search-input" id="codeSearchQuery"
                   placeholder="Semantic code search..." />
            <button class="search-btn" data-action="searchCode">🔍 Search</button>
          </div>
          <div id="codeSearchResults" style="margin-top: 8px;"></div>
        </div>
      </div>
    </div>
  `;
}

function renderRalphConfig(activeLoops: RalphLoopConfig[]): string {
  return `
    <div class="ralph-config">
      <div class="ralph-toggle">
        <div class="ralph-toggle-switch" id="ralphToggle" data-action="toggleRalph"></div>
        <span class="ralph-toggle-label">Enable Ralph Wiggum Loop</span>
      </div>

      <div class="ralph-options" id="ralphOptions">
        <div class="ralph-option">
          <label>Goals (TODO.md will be generated)</label>
          <textarea id="ralphGoals" placeholder="Describe what you want to accomplish...
Example:
- Implement the user authentication feature
- Add unit tests for all new functions
- Update documentation"></textarea>
        </div>

        <div class="ralph-option">
          <label>Completion Criteria</label>
          <input type="text" id="ralphCriteria" placeholder="e.g., All tests pass, No linter errors" />
        </div>

        <div class="ralph-option">
          <label>Max Iterations</label>
          <div class="ralph-slider">
            <input type="range" id="ralphMaxIterations" min="1" max="50" value="10" />
            <span class="ralph-slider-value" id="ralphMaxIterationsValue">10</span>
          </div>
        </div>
      </div>

      <div class="active-loops" id="activeLoopsPanel">
        <div class="active-loops-title">🔄 Active Loops</div>
        ${renderActiveLoops(activeLoops)}
      </div>
    </div>
  `;
}

function renderSessionInspector(): string {
  return `
    <div class="session-inspector" style="grid-template-columns: 1fr 1fr 1fr;">
      <!-- Cursor Sessions -->
      <div class="session-source">
        <div class="session-source-header">
          <span class="session-source-icon">🟣</span>
          <span class="session-source-name">Cursor Chats</span>
        </div>
        <div class="session-list" id="cursorSessionList">
          <div class="create-empty" style="padding: 16px; font-size: 0.8rem;">
            <div>Loading Cursor sessions...</div>
          </div>
        </div>
      </div>

      <!-- Claude Console Sessions -->
      <div class="session-source">
        <div class="session-source-header">
          <span class="session-source-icon">🟠</span>
          <span class="session-source-name">Claude Code</span>
        </div>
        <div class="session-list" id="claudeSessionList">
          <div class="create-empty" style="padding: 16px; font-size: 0.8rem;">
            <div>No Claude sessions found</div>
            <div style="margin-top: 4px;">Sessions from ~/.claude/ will appear here</div>
          </div>
        </div>
      </div>

      <!-- Gemini Sessions -->
      <div class="session-source">
        <div class="session-source-header">
          <span class="session-source-icon">🔵</span>
          <span class="session-source-name">Gemini</span>
        </div>
        <div class="session-list" id="geminiSessionList">
          <div class="create-empty" style="padding: 16px; font-size: 0.8rem;">
            <div>No Gemini sessions found</div>
            <div style="margin-top: 4px;">Import from AI Studio</div>
          </div>
        </div>
        <button class="search-btn" style="margin-top: 8px;" data-action="importGemini">
          📥 Import Session
        </button>
      </div>
    </div>
  `;
}

function renderPromptPreview(): string {
  return `
    <div class="prompt-preview">
      <div class="prompt-preview-header">
        <span class="prompt-preview-title">📝 Super Prompt Preview</span>
        <div class="prompt-preview-tokens">
          <span>Estimated:</span>
          <span class="token-count" id="tokenCount">0</span>
          <span>tokens</span>
        </div>
      </div>
      <div class="prompt-preview-content" id="promptPreviewContent">
        <div class="create-empty">
          Select context sources to build your super prompt
        </div>
      </div>
    </div>
  `;
}

// ==================== MAIN EXPORT ====================

/**
 * Generate the Create Session tab content HTML
 */
export function getCreateSessionTabContent(): string {
  const styles = getCreateSessionTabStyles();
  const personas = loadPersonaList();
  const activeLoops = loadActiveLoops();

  return `
    <style>${styles}</style>

    <div class="create-session-container">
      <!-- Issue Key Auto-Context -->
      <div class="create-section">
        <div class="create-section-header">
          <span class="create-section-title">🎯 Quick Start</span>
          <span class="create-section-subtitle">Enter an issue key to auto-populate context</span>
        </div>
        <div class="issue-key-input">
          <input type="text" id="issueKeyInput" placeholder="AAP-12345" />
          <button class="auto-context-btn" data-action="autoContext">
            ✨ Auto-Context
          </button>
        </div>
        <div id="jiraPreviewContainer"></div>
      </div>

      <!-- Persona Selection -->
      <div class="create-section">
        <div class="create-section-header">
          <span class="create-section-title">🤖 Persona</span>
          <span class="create-section-subtitle">Select a base persona for tool context</span>
        </div>
        ${renderPersonaSelector(personas, null)}
      </div>

      <!-- Context Builder -->
      <div class="create-section">
        <div class="create-section-header">
          <span class="create-section-title">🧩 Context Builder</span>
          <span class="create-section-subtitle">Select sources to include in your super prompt</span>
        </div>
        ${renderContextBuilder()}
      </div>

      <!-- Ralph Wiggum Loop Config -->
      <div class="create-section">
        <div class="create-section-header">
          <span class="create-section-title">🔄 Ralph Wiggum Loop</span>
          <span class="create-section-subtitle">Configure autonomous task execution</span>
        </div>
        ${renderRalphConfig(activeLoops)}
      </div>

      <!-- Session Inspector -->
      <div class="create-section">
        <div class="create-section-header">
          <span class="create-section-title">🔍 Session Inspector</span>
          <span class="create-section-subtitle">Analyze sessions from Claude Console and Gemini</span>
        </div>
        ${renderSessionInspector()}
      </div>

      <!-- Prompt Preview -->
      <div class="create-section">
        <div class="create-section-header">
          <span class="create-section-title">📝 Preview</span>
          <span class="create-section-subtitle">Review your assembled super prompt</span>
        </div>
        ${renderPromptPreview()}
      </div>

      <!-- Action Buttons -->
      <div class="create-session-actions">
        <button class="create-btn secondary" data-action="clearAll">
          🗑️ Clear All
        </button>
        <button class="create-btn secondary" data-action="saveTemplate">
          💾 Save Template
        </button>
        <button class="create-btn primary" data-action="createSession">
          🚀 Create Session
        </button>
      </div>
    </div>
  `;
}

/**
 * Get the JavaScript for the Create Session tab
 */
export function getCreateSessionTabScript(): string {
  return `
    // Create Session Tab Functions
    function initCreateSessionTab() {
      console.log('[CreateSessionTab] Initializing create session tab...');

      // Ralph Wiggum toggle
      const ralphToggle = document.getElementById('ralphToggle');
      const ralphOptions = document.getElementById('ralphOptions');

      if (ralphToggle) {
        ralphToggle.addEventListener('click', function() {
          this.classList.toggle('active');
          if (ralphOptions) {
            ralphOptions.classList.toggle('visible', this.classList.contains('active'));
          }
        });
      }

      // Max iterations slider
      const maxIterationsSlider = document.getElementById('ralphMaxIterations');
      const maxIterationsValue = document.getElementById('ralphMaxIterationsValue');

      if (maxIterationsSlider && maxIterationsValue) {
        maxIterationsSlider.addEventListener('input', function() {
          maxIterationsValue.textContent = this.value;
        });
      }

      // Context source item selection
      document.querySelectorAll('.context-source-item').forEach(item => {
        item.addEventListener('click', function(e) {
          if (e.target.tagName !== 'INPUT') {
            const checkbox = this.querySelector('input[type="checkbox"]');
            if (checkbox) {
              checkbox.checked = !checkbox.checked;
            }
          }
          this.classList.toggle('selected', this.querySelector('input')?.checked);
          updatePromptPreview();
        });
      });

      // Persona chip selection
      document.querySelectorAll('.persona-chip').forEach(chip => {
        chip.addEventListener('click', function() {
          document.querySelectorAll('.persona-chip').forEach(c => c.classList.remove('selected'));
          this.classList.add('selected');

          const personaId = this.getAttribute('data-persona-id');
          if (vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'selectPersona',
              personaId: personaId
            });
          }
          updatePromptPreview();
        });
      });

      // Action buttons
      document.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', function() {
          const action = this.getAttribute('data-action');
          handleCreateSessionAction(action, this);
        });
      });

      console.log('[CreateSessionTab] Create session tab initialized');
    }

    function handleCreateSessionAction(action, element) {
      console.log('[CreateSessionTab] Action:', action);

      switch (action) {
        case 'autoContext':
          const issueKey = document.getElementById('issueKeyInput')?.value;
          if (issueKey && vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'autoContext',
              issueKey: issueKey
            });
          }
          break;

        case 'searchSlack':
          const slackQuery = document.getElementById('slackSearchQuery')?.value;
          if (slackQuery && vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'searchSlack',
              query: slackQuery
            });
          }
          break;

        case 'searchCode':
          const codeQuery = document.getElementById('codeSearchQuery')?.value;
          if (codeQuery && vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'searchCode',
              query: codeQuery
            });
          }
          break;

        case 'stopLoop':
          const sessionId = element.getAttribute('data-session-id');
          if (sessionId && vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'stopLoop',
              sessionId: sessionId
            });
          }
          break;

        case 'createSession':
          const config = gatherSessionConfig();
          if (vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'createSession',
              config: config
            });
          }
          break;

        case 'clearAll':
          clearAllSelections();
          break;

        case 'saveTemplate':
          const templateConfig = gatherSessionConfig();
          if (vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'saveTemplate',
              config: templateConfig
            });
          }
          break;

        case 'importGemini':
          if (vscode) {
            vscode.postMessage({
              command: 'createSessionAction',
              action: 'importGemini'
            });
          }
          break;

        default:
          console.log('[CreateSessionTab] Unknown action:', action);
      }
    }

    function gatherSessionConfig() {
      const config = {
        issueKey: document.getElementById('issueKeyInput')?.value || '',
        persona: document.querySelector('.persona-chip.selected')?.getAttribute('data-persona-id') || null,
        skills: [],
        tools: [],
        memory: [],
        slackQuery: document.getElementById('slackSearchQuery')?.value || '',
        codeQuery: document.getElementById('codeSearchQuery')?.value || '',
        ralph: {
          enabled: document.getElementById('ralphToggle')?.classList.contains('active') || false,
          goals: document.getElementById('ralphGoals')?.value || '',
          criteria: document.getElementById('ralphCriteria')?.value || '',
          maxIterations: parseInt(document.getElementById('ralphMaxIterations')?.value || '10')
        }
      };

      // Gather selected memory paths
      document.querySelectorAll('#memorySourceList .context-source-item').forEach(item => {
        const checkbox = item.querySelector('input[type="checkbox"]');
        if (checkbox?.checked) {
          config.memory.push(item.getAttribute('data-path'));
        }
      });

      return config;
    }

    function clearAllSelections() {
      document.getElementById('issueKeyInput').value = '';
      document.querySelectorAll('.persona-chip').forEach(c => c.classList.remove('selected'));
      document.querySelectorAll('.context-source-item input[type="checkbox"]').forEach(cb => {
        cb.checked = false;
        cb.closest('.context-source-item')?.classList.remove('selected');
      });
      document.getElementById('slackSearchQuery').value = '';
      document.getElementById('codeSearchQuery').value = '';
      document.getElementById('ralphGoals').value = '';
      document.getElementById('ralphCriteria').value = '';
      document.getElementById('ralphMaxIterations').value = '10';
      document.getElementById('ralphMaxIterationsValue').textContent = '10';
      document.getElementById('ralphToggle')?.classList.remove('active');
      document.getElementById('ralphOptions')?.classList.remove('visible');
      updatePromptPreview();
    }

    function updatePromptPreview() {
      const config = gatherSessionConfig();
      let preview = '';
      let tokenEstimate = 0;

      if (config.persona) {
        preview += '=== PERSONA ===\\n' + config.persona + '\\n\\n';
        tokenEstimate += 500; // Rough estimate
      }

      if (config.memory.length > 0) {
        preview += '=== MEMORY ===\\n' + config.memory.join('\\n') + '\\n\\n';
        tokenEstimate += config.memory.length * 200;
      }

      if (config.issueKey) {
        preview += '=== ISSUE ===\\n' + config.issueKey + '\\n\\n';
        tokenEstimate += 300;
      }

      if (config.ralph.enabled) {
        preview += '=== RALPH WIGGUM LOOP ===\\n';
        preview += 'Max Iterations: ' + config.ralph.maxIterations + '\\n';
        preview += 'Goals:\\n' + config.ralph.goals + '\\n';
        preview += 'Criteria: ' + config.ralph.criteria + '\\n\\n';
        tokenEstimate += 200;
      }

      const previewContent = document.getElementById('promptPreviewContent');
      const tokenCount = document.getElementById('tokenCount');

      if (previewContent) {
        if (preview) {
          previewContent.innerHTML = '<pre>' + preview + '</pre>';
        } else {
          previewContent.innerHTML = '<div class="create-empty">Select context sources to build your super prompt</div>';
        }
      }

      if (tokenCount) {
        tokenCount.textContent = tokenEstimate.toLocaleString();
        tokenCount.className = 'token-count';
        if (tokenEstimate > 100000) {
          tokenCount.classList.add('token-danger');
        } else if (tokenEstimate > 50000) {
          tokenCount.classList.add('token-warning');
        }
      }
    }

    // Handle messages from extension
    window.addEventListener('message', event => {
      const message = event.data;
      console.log('[CreateSessionTab] Received message:', message.command);

      switch (message.command) {
        case 'jiraLoading':
          const container = document.getElementById('jiraPreviewContainer');
          if (container) {
            container.innerHTML = '<div class="jira-preview"><span class="loading-spinner"></span>Loading ' + message.issueKey + '...</div>';
          }
          break;

        case 'jiraData':
          const jiraContainer = document.getElementById('jiraPreviewContainer');
          if (jiraContainer && message.data) {
            const d = message.data;
            jiraContainer.innerHTML = \`
              <div class="jira-preview">
                <div class="jira-preview-title">\${d.key || message.issueKey}: \${d.summary || 'No summary'}</div>
                <div class="jira-preview-field"><strong>Status:</strong> \${d.status || 'Unknown'}</div>
                <div class="jira-preview-field"><strong>Priority:</strong> \${d.priority || 'Unknown'}</div>
                <div class="jira-preview-field"><strong>Assignee:</strong> \${d.assignee || 'Unassigned'}</div>
                \${d.description ? '<div class="jira-preview-description">' + d.description.substring(0, 500) + '</div>' : ''}
              </div>
            \`;
            updatePromptPreview();
          }
          break;

        case 'jiraError':
          const errorContainer = document.getElementById('jiraPreviewContainer');
          if (errorContainer) {
            errorContainer.innerHTML = '<div class="jira-preview" style="border-left-color: #ef4444;"><strong>Error:</strong> ' + message.error + '</div>';
          }
          break;

        case 'personaTools':
          const toolsList = document.getElementById('toolSourceList');
          if (toolsList && message.tools) {
            if (message.tools.length > 0) {
              toolsList.innerHTML = message.tools.map(tool => \`
                <div class="context-source-item" data-source="tool" data-tool-id="\${tool}">
                  <input type="checkbox" />
                  <span class="context-source-name">\${tool}</span>
                </div>
              \`).join('');
              // Re-attach click handlers
              toolsList.querySelectorAll('.context-source-item').forEach(item => {
                item.addEventListener('click', function(e) {
                  if (e.target.tagName !== 'INPUT') {
                    const checkbox = this.querySelector('input[type="checkbox"]');
                    if (checkbox) checkbox.checked = !checkbox.checked;
                  }
                  this.classList.toggle('selected', this.querySelector('input')?.checked);
                  updatePromptPreview();
                });
              });
            } else {
              toolsList.innerHTML = '<div class="create-empty" style="padding: 12px; font-size: 0.8rem;">No tools defined for this persona</div>';
            }
          }
          break;

        case 'slackResults':
          const slackResults = document.getElementById('slackSearchResults');
          if (slackResults && message.results) {
            if (message.results.length > 0) {
              slackResults.innerHTML = message.results.slice(0, 5).map(msg => \`
                <div class="context-source-item selected" data-source="slack">
                  <input type="checkbox" checked />
                  <span class="context-source-name">\${msg.user || 'Unknown'}: \${(msg.text || '').substring(0, 50)}...</span>
                </div>
              \`).join('');
            } else {
              slackResults.innerHTML = '<div style="font-size: 0.8rem; color: var(--text-muted);">No results found</div>';
            }
            updatePromptPreview();
          }
          break;

        case 'codeResults':
          const codeResults = document.getElementById('codeSearchResults');
          if (codeResults && message.results) {
            if (message.results.length > 0) {
              codeResults.innerHTML = message.results.slice(0, 5).map(result => \`
                <div class="context-source-item selected" data-source="code">
                  <input type="checkbox" checked />
                  <span class="context-source-name">\${result.file || 'Unknown file'}</span>
                </div>
              \`).join('');
            } else {
              codeResults.innerHTML = '<div style="font-size: 0.8rem; color: var(--text-muted);">No results found</div>';
            }
            updatePromptPreview();
          }
          break;

        case 'externalSessions':
          // Update Cursor sessions list
          const cursorList = document.getElementById('cursorSessionList');
          if (cursorList && message.cursor) {
            if (message.cursor.length > 0) {
              cursorList.innerHTML = message.cursor.map(s => \`
                <div class="session-item" data-session-id="\${s.id}" data-source="cursor">
                  <div class="session-item-info">
                    <div class="session-item-name">\${s.name || 'Unnamed chat'}</div>
                    <div class="session-item-meta">\${s.issueKey ? '🎫 ' + s.issueKey : ''} \${s.persona ? '🤖 ' + s.persona : ''}</div>
                  </div>
                  <button class="session-action-btn" data-action="useSession" data-session-id="\${s.id}" data-source="cursor">Use</button>
                </div>
              \`).join('');
            } else {
              cursorList.innerHTML = '<div class="create-empty" style="padding: 16px; font-size: 0.8rem;">No Cursor chats found</div>';
            }
          }

          // Update Claude sessions list
          const claudeList = document.getElementById('claudeSessionList');
          if (claudeList && message.claude) {
            if (message.claude.length > 0) {
              claudeList.innerHTML = message.claude.map(s => \`
                <div class="session-item" data-session-id="\${s.id}" data-source="claude">
                  <div class="session-item-info">
                    <div class="session-item-name">\${s.name}</div>
                    <div class="session-item-meta">\${s.id.substring(0, 8)}...</div>
                  </div>
                  <button class="session-action-btn" data-action="viewSession" data-session-id="\${s.id}">View</button>
                </div>
              \`).join('');
            } else {
              claudeList.innerHTML = '<div class="create-empty" style="padding: 16px; font-size: 0.8rem;">No Claude sessions found</div>';
            }
          }

          // Update Gemini sessions list
          const geminiList = document.getElementById('geminiSessionList');
          if (geminiList && message.gemini) {
            if (message.gemini.length > 0) {
              geminiList.innerHTML = message.gemini.map(s => \`
                <div class="session-item" data-session-id="\${s.id}" data-source="gemini">
                  <div class="session-item-info">
                    <div class="session-item-name">\${s.name}</div>
                    <div class="session-item-meta">\${s.id.substring(0, 8)}...</div>
                  </div>
                  <button class="session-action-btn" data-action="viewSession" data-session-id="\${s.id}">View</button>
                </div>
              \`).join('');
            } else {
              geminiList.innerHTML = '<div class="create-empty" style="padding: 16px; font-size: 0.8rem;">No Gemini sessions found</div>';
            }
          }
          break;
      }
    });

    // Request external sessions on load
    function loadExternalSessions() {
      if (vscode) {
        vscode.postMessage({
          command: 'createSessionAction',
          action: 'loadSessions'
        });
      }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        initCreateSessionTab();
        loadExternalSessions();
      });
    } else {
      initCreateSessionTab();
      loadExternalSessions();
    }
  `;
}
