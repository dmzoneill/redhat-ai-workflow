/**
 * Inference Tab
 *
 * Provides UI for tool filtering configuration and inference testing:
 * - Inference Context Inspector with rich result display
 * - Configure primary engine (NPU, iGPU, NVIDIA, CPU)
 * - Fallback strategy settings
 * - Persona statistics and auto-detection
 * - Inference test runner with quick test buttons
 * - Ollama instance management
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";
import { execAsync } from "../utils";

const logger = createLogger("InferenceTab");

// Ollama instance configuration
const OLLAMA_INSTANCES = [
  { name: "NPU", device: "Intel NPU", port: 11434, unit: "ollama-npu.service", model: "qwen2.5:0.5b" },
  { name: "iGPU", device: "Intel iGPU", port: 11435, unit: "ollama-igpu.service", model: "llama3.2:3b" },
  { name: "NVIDIA", device: "NVIDIA GPU", port: 11436, unit: "ollama-nvidia.service", model: "llama3:7b" },
  { name: "CPU", device: "CPU", port: 11437, unit: "ollama-cpu.service", model: "qwen2.5:0.5b" },
];

interface OllamaInstance {
  name: string;
  url: string;
  device: string;
  status: "online" | "offline" | "loading";
  model?: string;
  lastResponse?: number;
}

interface InferenceConfig {
  primaryEngine: "npu" | "igpu" | "nvidia" | "cpu";
  fallbackStrategy: "keyword_match" | "expanded_baseline" | "all_tools";
  maxCategories: number;
  enableFiltering: boolean;
  enableNpu: boolean;
  enableCache: boolean;
}

interface PersonaStats {
  name: string;
  toolCount: number;
  lastUsed?: string;
}

/** Full inference test result from the backend */
interface InferenceResult {
  tools: string[];
  tool_count: number;
  reduction_pct: number;
  methods: string[];
  persona: string;
  persona_auto_detected?: boolean;
  persona_detection_reason?: string;
  persona_prompt?: string;
  persona_categories?: string[];
  skill_detected: string | null;
  latency_ms: number;
  message_preview: string;
  error?: string;
  context?: {
    persona_prompt?: string;
    skill?: {
      name: string;
      description?: string;
      inputs?: Array<{ name: string; required?: boolean }>;
      tools?: string[];
      memory_ops?: { reads: any[]; writes: any[] };
    };
    npu?: { method?: string };
  };
  memory_state?: {
    current_repo?: string;
    current_branch?: string;
    active_issues?: Array<{ key: string } | string>;
    notes?: string;
  };
  environment?: {
    vpn_connected?: boolean;
    kubeconfigs?: Record<string, boolean>;
  };
  session_log?: Array<{ time?: string; action: string }>;
  learned_patterns?: Array<{ pattern: string; fix: string }>;
}

export class InferenceTab extends BaseTab {
  private config: InferenceConfig = {
    primaryEngine: "npu",
    fallbackStrategy: "keyword_match",
    maxCategories: 3,
    enableFiltering: true,
    enableNpu: true,
    enableCache: true,
  };
  private ollamaInstances: OllamaInstance[] = [];
  private personaStats: PersonaStats[] = [];
  private availablePersonas: string[] = [];
  private testResult: InferenceResult | null = null;
  private isRunningTest = false;

  constructor() {
    super({
      id: "inference",
      label: "Inference",
      icon: "🧠",
    });
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load Ollama instances by checking systemd service status
      logger.log("Checking Ollama instance status via systemctl...");
      await this.loadOllamaInstances();

      // Load persona stats
      logger.log("Calling config_getPersonasList()...");
      const personasResult = await dbus.config_getPersonasList();
      logger.log(`config_getPersonasList() result: success=${personasResult.success}, error=${personasResult.error || 'none'}`);
      if (personasResult.success && personasResult.data) {
        const data = personasResult.data as any;
        const personas = data.personas || [];
        this.personaStats = personas
          .filter((p: any) => !p.is_internal && !p.is_slim)
          .map((p: any) => ({
            name: p.name,
            // tool_count may not be provided; fall back to tools array length (modules, not individual tools)
            toolCount: p.tool_count ?? (p.tools?.length || 0),
            lastUsed: p.last_used,
          }));
        // Build available personas list for the dropdown
        this.availablePersonas = personas
          .filter((p: any) => !p.is_internal && !p.is_slim)
          .map((p: any) => p.name);
        logger.log(`Loaded ${this.personaStats.length} persona stats, ${this.availablePersonas.length} available`);
      } else if (personasResult.error) {
        this.lastError = `Personas list failed: ${personasResult.error}`;
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
      <!-- Inference Context Inspector -->
      <div class="section">
        <div class="section-title">🧪 Inference Context Inspector</div>
        <p class="text-secondary text-sm mb-12">
          Preview the full context that would be sent to Claude for any message. Shows persona, memory, tools, and semantic knowledge.
        </p>
        <div class="card">
          <div class="inspector-form">
            <div class="form-row">
              <label>Test Message</label>
              <input type="text" id="inferenceTestMessage" class="form-input" placeholder="deploy MR 1459 to ephemeral" value="Deploy my MR to ephemeral and check the pods" />
            </div>
            <div class="form-row grid-2">
              <div>
                <label>Persona (Auto-detect)</label>
                <select id="inferenceTestPersona" class="inference-select">
                  <option value="" selected>Auto-detect from message</option>
                  ${this.availablePersonas.map(p => `<option value="${this.escapeHtml(p)}">${this.escapeHtml(p)}</option>`).join("")}
                </select>
              </div>
              <div>
                <label>Skill (Auto-detect)</label>
                <select id="inferenceTestSkill" class="inference-select">
                  <option value="" selected>Auto-detect from message</option>
                </select>
              </div>
            </div>
            <div class="form-actions d-flex gap-8 mt-12">
              <button class="btn btn-primary" data-action="runInferenceTest" ${this.isRunningTest ? "disabled" : ""}>
                ${this.isRunningTest ? "⏳ Running..." : "🔍 Run Inference"}
              </button>
              <button class="btn btn-secondary" data-action="copyInferenceResult">📋 Copy Result</button>
            </div>
          </div>

          <!-- Results Area -->
          <div class="inference-result-area mt-16 ${this.testResult ? "" : "d-none"}" id="inferenceResultArea">
            ${this.testResult ? this.renderInferenceResult(this.testResult) : ""}
          </div>

          <!-- Quick Tests -->
          <div class="quick-tests mt-16 pt-12 border-t">
            <span class="text-sm text-muted">Quick Tests:</span>
            <button class="btn btn-sm btn-ghost" data-quick-test="hello">hello</button>
            <button class="btn btn-sm btn-ghost" data-quick-test="MR 1459">MR 1459</button>
            <button class="btn btn-sm btn-ghost" data-quick-test="AAP-12345">AAP-12345</button>
            <button class="btn btn-sm btn-ghost" data-quick-test="deploy MR 1459 to ephemeral">deploy MR</button>
            <button class="btn btn-sm btn-ghost" data-quick-test="debug production error">debug error</button>
            <button class="btn btn-sm btn-ghost" data-quick-test="check alerts">check alerts</button>
          </div>
        </div>
      </div>

      <!-- Configuration -->
      <div class="section">
        <div class="section-title">⚙️ Tool Filtering Configuration</div>
        <div class="card">
          <div class="grid-3">
            <div class="inference-config-item">
              <label>Primary Engine</label>
              <select id="inferenceEngine" class="inference-select">
                <option value="npu" ${this.config.primaryEngine === "npu" ? "selected" : ""}>NPU (qwen2.5:0.5b)</option>
                <option value="igpu" ${this.config.primaryEngine === "igpu" ? "selected" : ""}>iGPU (llama3.2:3b)</option>
                <option value="nvidia" ${this.config.primaryEngine === "nvidia" ? "selected" : ""}>NVIDIA (llama3:7b)</option>
                <option value="cpu" ${this.config.primaryEngine === "cpu" ? "selected" : ""}>CPU (qwen2.5:0.5b)</option>
              </select>
            </div>
            <div class="inference-config-item">
              <label>Fallback Strategy</label>
              <select id="fallbackStrategy" class="inference-select">
                <option value="keyword_match" ${this.config.fallbackStrategy === "keyword_match" ? "selected" : ""}>Keyword Match</option>
                <option value="expanded_baseline" ${this.config.fallbackStrategy === "expanded_baseline" ? "selected" : ""}>Expanded Baseline</option>
                <option value="all_tools" ${this.config.fallbackStrategy === "all_tools" ? "selected" : ""}>All Tools (No Filter)</option>
              </select>
            </div>
            <div class="inference-config-item">
              <label>Max Categories</label>
              <select id="maxCategories" class="inference-select">
                <option value="2" ${this.config.maxCategories === 2 ? "selected" : ""}>2</option>
                <option value="3" ${this.config.maxCategories === 3 ? "selected" : ""}>3</option>
                <option value="4" ${this.config.maxCategories === 4 ? "selected" : ""}>4</option>
                <option value="5" ${this.config.maxCategories === 5 ? "selected" : ""}>5</option>
              </select>
            </div>
          </div>
          <div class="inference-toggles">
            <label class="inference-toggle-label">
              <input type="checkbox" id="enableFiltering" ${this.config.enableFiltering ? "checked" : ""}>
              <span>Enable Tool Pre-filtering</span>
            </label>
            <label class="inference-toggle-label">
              <input type="checkbox" id="enableNpu" ${this.config.enableNpu ? "checked" : ""}>
              <span>Enable NPU (Layer 4)</span>
            </label>
            <label class="inference-toggle-label">
              <input type="checkbox" id="enableCache" ${this.config.enableCache ? "checked" : ""}>
              <span>Enable Cache</span>
            </label>
          </div>
        </div>
      </div>

      <!-- Persona Statistics -->
      <div class="section">
        <div class="section-title">📊 Persona Statistics</div>
        <div class="inference-persona-grid">
          ${this.personaStats.map((p) => `
            <div class="inference-persona-card">
              <div class="inference-persona-name">${this.getPersonaIcon(p.name)} ${this.escapeHtml(p.name)}</div>
              <div class="inference-persona-tools">${p.toolCount} tools</div>
              ${p.lastUsed ? `<div class="inference-persona-used">Last: ${this.formatRelativeTime(p.lastUsed)}</div>` : ""}
            </div>
          `).join("")}
          ${this.personaStats.length === 0 ? '<div class="empty-state">No persona statistics available</div>' : ""}
        </div>
      </div>

      <!-- Ollama Instances -->
      <div class="section">
        <div class="section-title">🦙 Ollama Instances</div>
        <div class="inference-ollama-grid">
          ${this.ollamaInstances.map((instance) => `
            <div class="inference-ollama-card ${instance.status}">
              <div class="inference-ollama-header">
                <span class="inference-ollama-name">${this.escapeHtml(instance.name)}</span>
                <span class="inference-ollama-status status-${instance.status}">${instance.status}</span>
              </div>
              <div class="inference-ollama-device">${this.escapeHtml(instance.device)}</div>
              <div class="inference-ollama-url">${this.escapeHtml(instance.url)}</div>
              ${instance.model ? `<div class="inference-ollama-model">Model: ${this.escapeHtml(instance.model)}</div>` : ""}
              <div class="inference-ollama-actions">
                <button class="btn btn-xs" data-action="testOllama" data-instance="${this.escapeHtml(instance.name)}">Test</button>
              </div>
            </div>
          `).join("")}
          ${this.ollamaInstances.length === 0 ? this.getEmptyOllamaHtml() : ""}
        </div>
      </div>

      <!-- Save Configuration -->
      <div class="inference-save-actions">
        <button class="btn btn-sm btn-danger" data-action="resetConfig">Reset to Defaults</button>
        <button class="btn btn-sm btn-primary" data-action="saveConfig">💾 Save Configuration</button>
      </div>
    `;
  }

  /**
   * Render the rich inference result display
   */
  private renderInferenceResult(data: InferenceResult): string {
    const ctx = data.context || {};
    const mem = data.memory_state || {};
    const env = data.environment || {};

    // Build the layer badges
    const methods = data.methods || [];
    const layerNames: Record<string, string> = {
      layer1_core: "🔵 Core",
      layer2_persona: "🟢 Persona",
      layer3_skill: "🎯 Skill",
      layer4_npu: "🟣 NPU",
      layer4_keyword_fallback: "🟡 Keyword",
      fast_path: "⚡ Fast",
      timeout_fallback: "⏱️ Timeout",
      spawn_error_fallback: "❌ Error",
    };
    const layerBadges = methods
      .map((m) => `<span class="layer-badge">${layerNames[m] || m}</span>`)
      .join(" → ");

    // Error banner if any
    const errorBanner = data.error
      ? `<div class="error-banner mb-12">⚠️ ${this.escapeHtml(data.error)}</div>`
      : "";

    let html = errorBanner;

    // Summary header
    const finalToolCount = (data.tools || []).length;
    html += `<div class="d-flex items-baseline gap-12 mb-16 pb-12 border-b">
      <span class="text-xl font-bold text-success">✅ ${finalToolCount} tools</span>
      <span class="text-secondary">${data.latency_ms || 0}ms • ${(data.reduction_pct || 0).toFixed(1)}% reduction</span>
      <span class="ml-auto">${layerBadges}</span>
    </div>`;

    // === 1. SYSTEM PROMPT / PERSONA SECTION ===
    const personaIcons: Record<string, string> = { developer: "👨‍💻", devops: "🔧", incident: "🚨", release: "📦" };
    const personaPrompt = data.persona_prompt || ctx.persona_prompt || "";
    const personaCategories = data.persona_categories || [];
    const personaAutoDetected = data.persona_auto_detected || false;
    const personaReason = data.persona_detection_reason || "passed_in";

    html += `<div class="context-section green">
      <div class="section-header">${personaIcons[data.persona] || "👤"} System Prompt (Persona: ${this.escapeHtml(data.persona)})
        ${personaAutoDetected ? `<span class="chip green text-2xs font-normal">🔍 Auto-detected via ${this.escapeHtml(personaReason)}</span>` : ""}
      </div>
      ${personaCategories.length > 0
        ? `<div class="text-sm text-secondary mb-8">Tool Categories: <span class="text-primary">${personaCategories.map((c) => this.escapeHtml(c)).join(", ")}</span></div>`
        : `<div class="text-sm text-secondary mb-8">Tool Categories: <span class="opacity-50">none configured</span></div>`}
      ${personaPrompt ? `<div class="text-2xs text-secondary p-8 rounded scroll-container short" style="font-style: italic;">"${this.escapeHtml(personaPrompt.substring(0, 300))}${personaPrompt.length > 300 ? '..."' : '"'}</div>` : ""}
    </div>`;

    // === 2. MEMORY STATE SECTION (with inline environment status) ===
    const kubeconfigs = env.kubeconfigs || {};
    const activeIssues = mem.active_issues || [];
    html += `<div class="context-section purple">
      <div class="flex-between mb-8">
        <span class="font-bold">🧠 Memory State</span>
        <span class="text-2xs d-flex gap-8">
          <span>${env.vpn_connected ? "🟢" : "🔴"} VPN</span>
          <span>${kubeconfigs.stage ? "🟢" : "⚪"} Stage</span>
          <span>${kubeconfigs.prod ? "🟢" : "⚪"} Prod</span>
          <span>${kubeconfigs.ephemeral ? "🟢" : "⚪"} Eph</span>
        </span>
      </div>
      <div class="d-grid grid-cols-2 gap-8 text-sm">
        <div><span class="text-secondary">Current Repo:</span> <code>${this.escapeHtml(mem.current_repo || "none")}</code></div>
        <div><span class="text-secondary">Current Branch:</span> <code>${this.escapeHtml(mem.current_branch || "none")}</code></div>
      </div>
      ${activeIssues.length > 0
        ? `<div class="mt-8"><span class="text-secondary text-sm">Active Issues:</span>
          <div class="d-flex flex-wrap gap-4 mt-4">
            ${activeIssues.map((i) => `<span class="chip purple">${this.escapeHtml(typeof i === "string" ? i : i.key)}</span>`).join("")}
          </div></div>`
        : `<div class="mt-8 text-2xs text-secondary">No active issues</div>`}
      ${mem.notes ? `<div class="mt-8 text-2xs p-6 rounded dark-bg"><strong>Notes:</strong> ${this.escapeHtml(mem.notes)}</div>` : ""}
    </div>`;

    // === 3. SESSION LOG SECTION ===
    const sessionLog = data.session_log || [];
    if (sessionLog.length > 0) {
      html += `<div class="context-section indigo">
        <div class="section-header">📝 Session Log (Recent Actions)</div>
        <div class="text-2xs d-flex flex-col gap-4 scroll-container">
          ${sessionLog.map((a) => `<div class="action-log-item">
            <span class="text-secondary">${this.escapeHtml((a.time || "").substring(11, 19))}</span> ${this.escapeHtml(a.action)}
          </div>`).join("")}
        </div>
      </div>`;
    }

    // === 4. SKILL SECTION ===
    if (ctx.skill && ctx.skill.name) {
      const memOps = ctx.skill.memory_ops || { reads: [], writes: [] };
      let skillDesc = ctx.skill.description || "";
      if (skillDesc.length > 500) {
        skillDesc = skillDesc.substring(0, 500) + "...";
      }
      html += `<div class="context-section violet">
        <div class="section-header">🎯 Detected Skill: ${this.escapeHtml(ctx.skill.name)}</div>
        ${skillDesc ? `<div class="text-sm mb-8 scroll-container tall p-8 rounded dark-bg">${this.escapeHtml(skillDesc)}</div>` : ""}
        ${ctx.skill.inputs && ctx.skill.inputs.length > 0
          ? `<div class="text-sm text-secondary mb-6">Inputs: ${ctx.skill.inputs.map((i) => `<code class="code-inline purple">${i.name || i}${i.required ? "*" : ""}</code>`).join(", ")}</div>`
          : ""}
        <div class="text-sm text-secondary mb-6">Tools used by skill:</div>
        <div class="d-flex flex-wrap gap-4 mb-8">
          ${(ctx.skill.tools || []).map((t) => `<span class="chip purple">${t}</span>`).join("")}
        </div>
        ${memOps.reads.length > 0 || memOps.writes.length > 0
          ? `<div class="text-2xs mt-8 pt-8 border-t">
            <div class="text-secondary mb-4">Memory Operations:</div>
            ${memOps.reads.length > 0 ? `<div class="mb-4">📖 Reads: ${memOps.reads.map((r: any) => `<code class="code-inline green text-2xs">${r.key || r.tool || "unknown"}</code>`).join(" ")}</div>` : ""}
            ${memOps.writes.length > 0 ? `<div>✏️ Writes: ${memOps.writes.map((w: any) => `<code class="code-inline orange text-2xs">${w.key || w.tool || "unknown"}</code>`).join(" ")}</div>` : ""}
          </div>`
          : ""}
      </div>`;
    }

    // === 5. LEARNED PATTERNS SECTION ===
    const learnedPatterns = data.learned_patterns || [];
    if (learnedPatterns.length > 0) {
      html += `<div class="context-section pink">
        <div class="section-header">💡 Learned Patterns</div>
        <div class="text-2xs d-flex flex-col gap-6">
          ${learnedPatterns.map((p) => `<div class="pattern-item">
            <div class="text-error">Pattern: ${this.escapeHtml((p.pattern || "").substring(0, 50))}</div>
            <div class="text-success">Fix: ${this.escapeHtml((p.fix || "").substring(0, 100))}</div>
          </div>`).join("")}
        </div>
      </div>`;
    }

    // === 6. TOOLS LIST ===
    const tools = data.tools || [];
    if (tools.length > 0) {
      html += `<div class="context-section blue">
        <div class="section-header">🔧 Filtered Tools (${tools.length})</div>
        <div class="d-flex flex-wrap gap-4">
          ${tools.slice(0, 30).map((t) => `<span class="chip blue">${this.escapeHtml(t)}</span>`).join("")}
          ${tools.length > 30 ? `<span class="chip text-secondary">+${tools.length - 30} more</span>` : ""}
        </div>
      </div>`;
    }

    return html;
  }

  private getEmptyOllamaHtml(): string {
    return `
      <div class="inference-ollama-empty">
        <div class="inference-ollama-empty-icon">🦙</div>
        <div class="inference-ollama-empty-title">No Ollama Instances</div>
        <div class="inference-ollama-empty-text">
          Configure Ollama instances in config.json to enable local inference.
        </div>
      </div>
    `;
  }

  /**
   * Load Ollama instance status by checking systemd services
   */
  private async loadOllamaInstances(): Promise<void> {
    try {
      // Check all Ollama services in a single systemctl call
      const units = OLLAMA_INSTANCES.map(i => i.unit).join(" ");
      const { stdout } = await execAsync(
        `systemctl is-active ${units} 2>/dev/null || true`
      );
      const states = stdout.trim().split("\n");

      this.ollamaInstances = OLLAMA_INSTANCES.map((inst, idx) => {
        const isActive = states[idx] === "active";
        return {
          name: inst.name,
          url: `http://localhost:${inst.port}`,
          device: inst.device,
          status: isActive ? "online" as const : "offline" as const,
          model: inst.model,
        };
      });

      const onlineCount = this.ollamaInstances.filter(i => i.status === "online").length;
      logger.log(`Loaded ${this.ollamaInstances.length} Ollama instances (${onlineCount} online)`);
    } catch (error) {
      logger.error("Failed to load Ollama instances", error);
      // Set all instances to offline on error
      this.ollamaInstances = OLLAMA_INSTANCES.map(inst => ({
        name: inst.name,
        url: `http://localhost:${inst.port}`,
        device: inst.device,
        status: "offline" as const,
        model: inst.model,
      }));
    }
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    // Use centralized event delegation system - handlers survive content updates
    return `
      (function() {
        function runInferenceTest() {
          const message = document.getElementById('inferenceTestMessage')?.value || '';
          const persona = document.getElementById('inferenceTestPersona')?.value || '';
          const skill = document.getElementById('inferenceTestSkill')?.value || '';
          if (message) {
            vscode.postMessage({
              command: 'runInferenceTest',
              message: message,
              persona: persona,
              skill: skill
            });
          }
        }

        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('inference', function(action, element, e) {
          switch (action) {
            case 'runInferenceTest':
              runInferenceTest();
              break;
            case 'copyInferenceResult': {
              const resultArea = document.getElementById('inferenceResultArea');
              if (resultArea && resultArea.textContent) {
                navigator.clipboard.writeText(resultArea.textContent).then(() => {
                  // Could show a toast here
                }).catch(err => {
                  console.error('Failed to copy:', err);
                });
              }
              break;
            }
            case 'clearTestResults': {
              const results = document.getElementById('inferenceResultArea');
              if (results) {
                results.style.display = 'none';
                results.innerHTML = '';
              }
              break;
            }
            case 'testOllama': {
              const instance = element.getAttribute('data-instance');
              if (instance) {
                vscode.postMessage({ command: 'testOllamaInstance', instance: instance });
              }
              break;
            }
            case 'resetConfig':
              vscode.postMessage({ command: 'resetInferenceConfig' });
              break;
            case 'saveConfig':
              vscode.postMessage({ command: 'saveInferenceConfig' });
              break;
          }
        });

        // Register keypress handler for Enter key
        TabEventDelegation.registerKeypressHandler('inference', function(element, e) {
          if (element.id === 'inferenceTestMessage' && e.key === 'Enter') {
            runInferenceTest();
          }
        });

        // Register change handler for config selects and toggles
        TabEventDelegation.registerChangeHandler('inference', function(element, e) {
          const configFields = ['inferenceEngine', 'fallbackStrategy', 'maxCategories'];
          const toggleFields = ['enableFiltering', 'enableNpu', 'enableCache'];
          
          if (configFields.includes(element.id)) {
            vscode.postMessage({
              command: 'inferenceConfigChange',
              field: element.id,
              value: element.value
            });
          } else if (toggleFields.includes(element.id)) {
            vscode.postMessage({
              command: 'inferenceConfigChange',
              field: element.id,
              value: element.checked
            });
          }
        });

        // Additional click handling for quick-test buttons (not data-action)
        const inferenceContainer = document.getElementById('inference');
        if (inferenceContainer && !inferenceContainer.dataset.extraClickInit) {
          inferenceContainer.dataset.extraClickInit = 'true';
          
          inferenceContainer.addEventListener('click', function(e) {
            const quickTestBtn = e.target.closest('[data-quick-test]');
            if (quickTestBtn) {
              const testMsg = quickTestBtn.getAttribute('data-quick-test');
              const msgInput = document.getElementById('inferenceTestMessage');
              if (msgInput && testMsg) {
                msgInput.value = testMsg;
                runInferenceTest();
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
      case "inferenceTestResult":
        // The backend sends the result in message.data
        if (message.data) {
          this.testResult = message.data as InferenceResult;
          logger.log(`Received inference result: ${this.testResult.tool_count} tools, persona: ${this.testResult.persona}`);
        }
        this.isRunningTest = false;
        this.notifyNeedsRender();
        return true;

      case "inferenceTestStarted":
        this.isRunningTest = true;
        this.notifyNeedsRender();
        return true;

      case "inferenceConfigChange":
        // Update local config
        if (message.field in this.config) {
          (this.config as any)[message.field] = message.value;
        }
        return true;

      case "inferenceStatsUpdate":
        // Handle stats update from the backend
        if (message.data) {
          const data = message.data as any;
          if (data.available_personas) {
            this.availablePersonas = data.available_personas;
          }
        }
        return true;

      // === NEW: Action handlers for inference operations ===
      case "runInferenceTest":
        await this.runInferenceTest(message.message, message.persona, message.skill);
        return true;

      case "testOllamaInstance":
        await this.testOllamaInstance(message.instance);
        return true;

      case "resetInferenceConfig":
        await this.resetConfig();
        return true;

      case "saveInferenceConfig":
        await this.saveConfig();
        return true;

      default:
        return false;
    }
  }

  // === Action handlers ===

  private async runInferenceTest(testMessage: string, persona?: string, skill?: string): Promise<void> {
    if (!testMessage) {
      vscode.window.showWarningMessage("Please enter a test message");
      return;
    }

    this.isRunningTest = true;
    this.notifyNeedsRender();

    try {
      logger.log(`Running inference test: message="${testMessage}", persona="${persona || 'auto'}", skill="${skill || 'auto'}"`);
      
      // Call D-Bus to run the inference test
      const result = await dbus.config_getInferenceContext(testMessage);
      
      if (result.success && result.data) {
        const data = result.data as any;
        this.testResult = data.context || data;
        logger.log(`Inference test complete: ${this.testResult?.tool_count || 0} tools`);
      } else {
        this.testResult = {
          tools: [],
          tool_count: 0,
          reduction_pct: 0,
          methods: [],
          persona: persona || "unknown",
          skill_detected: null,
          latency_ms: 0,
          message_preview: testMessage,
          error: result.error || "Failed to run inference test",
        };
        logger.error(`Inference test failed: ${result.error}`);
      }
    } catch (error) {
      this.testResult = {
        tools: [],
        tool_count: 0,
        reduction_pct: 0,
        methods: [],
        persona: persona || "unknown",
        skill_detected: null,
        latency_ms: 0,
        message_preview: testMessage,
        error: error instanceof Error ? error.message : String(error),
      };
      logger.error("Inference test error", error);
    }

    this.isRunningTest = false;
    this.notifyNeedsRender();
  }

  private async testOllamaInstance(instanceName: string): Promise<void> {
    const instance = this.ollamaInstances.find(i => i.name === instanceName);
    if (!instance) {
      vscode.window.showErrorMessage(`Unknown Ollama instance: ${instanceName}`);
      return;
    }

    try {
      logger.log(`Testing Ollama instance: ${instanceName} at ${instance.url}`);
      vscode.window.showInformationMessage(`Testing ${instanceName}...`);

      // Simple health check via curl
      const { stdout, stderr } = await execAsync(
        `curl -s -o /dev/null -w "%{http_code}" ${instance.url}/api/tags 2>/dev/null || echo "000"`,
        { timeout: 5000 }
      );
      
      const statusCode = stdout.trim();
      if (statusCode === "200") {
        vscode.window.showInformationMessage(`✅ ${instanceName} is healthy`);
        // Update instance status
        instance.status = "online";
      } else {
        vscode.window.showWarningMessage(`⚠️ ${instanceName} returned status ${statusCode}`);
        instance.status = "offline";
      }
      
      this.notifyNeedsRender();
    } catch (error) {
      vscode.window.showErrorMessage(`❌ ${instanceName} test failed: ${error instanceof Error ? error.message : String(error)}`);
      instance.status = "offline";
      this.notifyNeedsRender();
    }
  }

  private async resetConfig(): Promise<void> {
    this.config = {
      primaryEngine: "npu",
      fallbackStrategy: "keyword_match",
      maxCategories: 3,
      enableFiltering: true,
      enableNpu: true,
      enableCache: true,
    };
    vscode.window.showInformationMessage("Inference configuration reset to defaults");
    this.notifyNeedsRender();
  }

  private async saveConfig(): Promise<void> {
    try {
      logger.log(`Saving inference config: ${JSON.stringify(this.config)}`);
      
      // Save config via D-Bus
      const result = await dbus.config_setConfig("inference", JSON.stringify(this.config));
      
      if (result.success) {
        vscode.window.showInformationMessage("✅ Inference configuration saved");
      } else {
        vscode.window.showErrorMessage(`Failed to save config: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to save config: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}
