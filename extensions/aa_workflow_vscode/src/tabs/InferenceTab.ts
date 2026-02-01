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
        <p style="color: var(--vscode-descriptionForeground); font-size: 12px; margin-bottom: 12px;">
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
            <div class="form-actions" style="display: flex; gap: 8px; margin-top: 12px;">
              <button class="btn btn-primary" data-action="runInferenceTest" ${this.isRunningTest ? "disabled" : ""}>
                ${this.isRunningTest ? "⏳ Running..." : "🔍 Run Inference"}
              </button>
              <button class="btn btn-secondary" data-action="copyInferenceResult">📋 Copy Result</button>
            </div>
          </div>

          <!-- Results Area -->
          <div class="inference-result-area" id="inferenceResultArea" style="margin-top: 16px; ${this.testResult ? "" : "display: none;"}">
            ${this.testResult ? this.renderInferenceResult(this.testResult) : ""}
          </div>

          <!-- Quick Tests -->
          <div class="quick-tests" style="margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--vscode-widget-border);">
            <span style="font-size: 12px; color: var(--text-muted);">Quick Tests:</span>
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
      .map((m) => `<span class="layer-badge" style="background: rgba(139,92,246,0.2); padding: 2px 8px; border-radius: 12px; font-size: 11px;">${layerNames[m] || m}</span>`)
      .join(" → ");

    // Error banner if any
    const errorBanner = data.error
      ? `<div style="background: var(--vscode-inputValidation-errorBackground); padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; color: var(--vscode-errorForeground);">⚠️ ${this.escapeHtml(data.error)}</div>`
      : "";

    let html = errorBanner;

    // Summary header
    const finalToolCount = (data.tools || []).length;
    html += `<div style="display: flex; align-items: baseline; gap: 12px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--vscode-widget-border);">
      <span style="font-size: 1.3em; font-weight: bold; color: var(--vscode-testing-iconPassed);">✅ ${finalToolCount} tools</span>
      <span style="color: var(--vscode-descriptionForeground);">${data.latency_ms || 0}ms • ${(data.reduction_pct || 0).toFixed(1)}% reduction</span>
      <span style="margin-left: auto;">${layerBadges}</span>
    </div>`;

    // === 1. SYSTEM PROMPT / PERSONA SECTION ===
    const personaIcons: Record<string, string> = { developer: "👨‍💻", devops: "🔧", incident: "🚨", release: "📦" };
    const personaPrompt = data.persona_prompt || ctx.persona_prompt || "";
    const personaCategories = data.persona_categories || [];
    const personaAutoDetected = data.persona_auto_detected || false;
    const personaReason = data.persona_detection_reason || "passed_in";

    html += `<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(34,197,94,0.1); border-radius: 8px; border-left: 3px solid #22c55e;">
      <div style="font-weight: bold; margin-bottom: 8px;">${personaIcons[data.persona] || "👤"} System Prompt (Persona: ${this.escapeHtml(data.persona)})
        ${personaAutoDetected ? `<span style="background: rgba(34,197,94,0.3); padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: normal;">🔍 Auto-detected via ${this.escapeHtml(personaReason)}</span>` : ""}
      </div>
      ${personaCategories.length > 0
        ? `<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 8px;">Tool Categories: <span style="color: var(--vscode-foreground);">${personaCategories.map((c) => this.escapeHtml(c)).join(", ")}</span></div>`
        : `<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 8px;">Tool Categories: <span style="opacity: 0.5;">none configured</span></div>`}
      ${personaPrompt ? `<div style="font-size: 11px; font-style: italic; color: var(--vscode-descriptionForeground); padding: 8px; background: rgba(0,0,0,0.1); border-radius: 4px; max-height: 80px; overflow-y: auto;">"${this.escapeHtml(personaPrompt.substring(0, 300))}${personaPrompt.length > 300 ? '..."' : '"'}</div>` : ""}
    </div>`;

    // === 2. MEMORY STATE SECTION (with inline environment status) ===
    const kubeconfigs = env.kubeconfigs || {};
    const activeIssues = mem.active_issues || [];
    html += `<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(168,85,247,0.1); border-radius: 8px; border-left: 3px solid #a855f7;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span style="font-weight: bold;">🧠 Memory State</span>
        <span style="font-size: 11px; display: flex; gap: 8px;">
          <span>${env.vpn_connected ? "🟢" : "🔴"} VPN</span>
          <span>${kubeconfigs.stage ? "🟢" : "⚪"} Stage</span>
          <span>${kubeconfigs.prod ? "🟢" : "⚪"} Prod</span>
          <span>${kubeconfigs.ephemeral ? "🟢" : "⚪"} Eph</span>
        </span>
      </div>
      <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 12px;">
        <div><span style="color: var(--vscode-descriptionForeground);">Current Repo:</span> <code>${this.escapeHtml(mem.current_repo || "none")}</code></div>
        <div><span style="color: var(--vscode-descriptionForeground);">Current Branch:</span> <code>${this.escapeHtml(mem.current_branch || "none")}</code></div>
      </div>
      ${activeIssues.length > 0
        ? `<div style="margin-top: 8px;"><span style="color: var(--vscode-descriptionForeground); font-size: 12px;">Active Issues:</span>
          <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px;">
            ${activeIssues.map((i) => `<span style="background: rgba(168,85,247,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${this.escapeHtml(typeof i === "string" ? i : i.key)}</span>`).join("")}
          </div></div>`
        : `<div style="margin-top: 8px; font-size: 11px; color: var(--vscode-descriptionForeground);">No active issues</div>`}
      ${mem.notes ? `<div style="margin-top: 8px; font-size: 11px; padding: 6px; background: rgba(0,0,0,0.1); border-radius: 4px;"><strong>Notes:</strong> ${this.escapeHtml(mem.notes)}</div>` : ""}
    </div>`;

    // === 3. SESSION LOG SECTION ===
    const sessionLog = data.session_log || [];
    if (sessionLog.length > 0) {
      html += `<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(99,102,241,0.1); border-radius: 8px; border-left: 3px solid #6366f1;">
        <div style="font-weight: bold; margin-bottom: 8px;">📝 Session Log (Recent Actions)</div>
        <div style="font-size: 11px; display: flex; flex-direction: column; gap: 4px; max-height: 100px; overflow-y: auto;">
          ${sessionLog.map((a) => `<div style="padding: 4px 8px; background: rgba(0,0,0,0.1); border-radius: 4px;">
            <span style="color: var(--vscode-descriptionForeground);">${this.escapeHtml((a.time || "").substring(11, 19))}</span> ${this.escapeHtml(a.action)}
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
      html += `<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(139,92,246,0.1); border-radius: 8px; border-left: 3px solid #8b5cf6;">
        <div style="font-weight: bold; margin-bottom: 8px;">🎯 Detected Skill: ${this.escapeHtml(ctx.skill.name)}</div>
        ${skillDesc ? `<div style="font-size: 12px; margin-bottom: 8px; max-height: 120px; overflow-y: auto; padding: 8px; background: rgba(0,0,0,0.1); border-radius: 4px;">${this.escapeHtml(skillDesc)}</div>` : ""}
        ${ctx.skill.inputs && ctx.skill.inputs.length > 0
          ? `<div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 6px;">Inputs: ${ctx.skill.inputs.map((i) => `<code style="background: rgba(139,92,246,0.2); padding: 1px 4px; border-radius: 3px;">${i.name || i}${i.required ? "*" : ""}</code>`).join(", ")}</div>`
          : ""}
        <div style="font-size: 12px; color: var(--vscode-descriptionForeground); margin-bottom: 6px;">Tools used by skill:</div>
        <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px;">
          ${(ctx.skill.tools || []).map((t) => `<span class="tool-chip" style="background: rgba(139,92,246,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${t}</span>`).join("")}
        </div>
        ${memOps.reads.length > 0 || memOps.writes.length > 0
          ? `<div style="font-size: 11px; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(139,92,246,0.2);">
            <div style="color: var(--vscode-descriptionForeground); margin-bottom: 4px;">Memory Operations:</div>
            ${memOps.reads.length > 0 ? `<div style="margin-bottom: 4px;">📖 Reads: ${memOps.reads.map((r: any) => `<code style="background: rgba(34,197,94,0.2); padding: 1px 4px; border-radius: 3px; font-size: 10px;">${r.key || r.tool || "unknown"}</code>`).join(" ")}</div>` : ""}
            ${memOps.writes.length > 0 ? `<div>✏️ Writes: ${memOps.writes.map((w: any) => `<code style="background: rgba(245,158,11,0.2); padding: 1px 4px; border-radius: 3px; font-size: 10px;">${w.key || w.tool || "unknown"}</code>`).join(" ")}</div>` : ""}
          </div>`
          : ""}
      </div>`;
    }

    // === 5. LEARNED PATTERNS SECTION ===
    const learnedPatterns = data.learned_patterns || [];
    if (learnedPatterns.length > 0) {
      html += `<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(236,72,153,0.1); border-radius: 8px; border-left: 3px solid #ec4899;">
        <div style="font-weight: bold; margin-bottom: 8px;">💡 Learned Patterns</div>
        <div style="font-size: 11px; display: flex; flex-direction: column; gap: 6px;">
          ${learnedPatterns.map((p) => `<div style="padding: 6px 8px; background: rgba(0,0,0,0.1); border-radius: 4px;">
            <div style="color: var(--vscode-errorForeground);">Pattern: ${this.escapeHtml((p.pattern || "").substring(0, 50))}</div>
            <div style="color: var(--vscode-testing-iconPassed);">Fix: ${this.escapeHtml((p.fix || "").substring(0, 100))}</div>
          </div>`).join("")}
        </div>
      </div>`;
    }

    // === 6. TOOLS LIST ===
    const tools = data.tools || [];
    if (tools.length > 0) {
      html += `<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(59,130,246,0.1); border-radius: 8px; border-left: 3px solid #3b82f6;">
        <div style="font-weight: bold; margin-bottom: 8px;">🔧 Filtered Tools (${tools.length})</div>
        <div style="display: flex; flex-wrap: wrap; gap: 4px;">
          ${tools.slice(0, 30).map((t) => `<span style="background: rgba(59,130,246,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">${this.escapeHtml(t)}</span>`).join("")}
          ${tools.length > 30 ? `<span style="padding: 2px 6px; font-size: 11px; color: var(--vscode-descriptionForeground);">+${tools.length - 30} more</span>` : ""}
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
    return `
      // Inference Tab initialization
      (function() {
        // Config change handlers
        ['inferenceEngine', 'fallbackStrategy', 'maxCategories'].forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            el.addEventListener('change', function() {
              vscode.postMessage({
                command: 'inferenceConfigChange',
                field: id,
                value: this.value
              });
            });
          }
        });

        // Toggle handlers
        ['enableFiltering', 'enableNpu', 'enableCache'].forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            el.addEventListener('change', function() {
              vscode.postMessage({
                command: 'inferenceConfigChange',
                field: id,
                value: this.checked
              });
            });
          }
        });

        // Action buttons
        document.querySelectorAll('[data-action]').forEach(btn => {
          btn.addEventListener('click', function() {
            const action = this.getAttribute('data-action');
            handleInferenceAction(action, this);
          });
        });

        // Quick test buttons
        document.querySelectorAll('[data-quick-test]').forEach(btn => {
          btn.addEventListener('click', function() {
            const testMsg = this.getAttribute('data-quick-test');
            const msgInput = document.getElementById('inferenceTestMessage');
            if (msgInput && testMsg) {
              msgInput.value = testMsg;
              runInferenceTest();
            }
          });
        });

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

        function handleInferenceAction(action, element) {
          switch (action) {
            case 'runInferenceTest':
              runInferenceTest();
              break;
            case 'copyInferenceResult':
              const resultArea = document.getElementById('inferenceResultArea');
              if (resultArea && resultArea.textContent) {
                navigator.clipboard.writeText(resultArea.textContent).then(() => {
                  // Could show a toast here
                }).catch(err => {
                  console.error('Failed to copy:', err);
                });
              }
              break;
            case 'clearTestResults':
              const results = document.getElementById('inferenceResultArea');
              if (results) {
                results.style.display = 'none';
                results.innerHTML = '';
              }
              break;
            case 'testOllama':
              const instance = element.getAttribute('data-instance');
              if (instance) {
                vscode.postMessage({ command: 'testOllamaInstance', instance: instance });
              }
              break;
            case 'resetConfig':
              vscode.postMessage({ command: 'resetInferenceConfig' });
              break;
            case 'saveConfig':
              vscode.postMessage({ command: 'saveInferenceConfig' });
              break;
          }
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

      default:
        return false;
    }
  }
}
