/**
 * Skills Tab
 *
 * Displays skill browser, execution flowchart, and running skills.
 * Uses D-Bus to communicate with the Config and Stats daemons.
 * Integrates with WebSocket for real-time skill execution updates.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";
import { getSkillWebSocketClient, SkillState, SkillWebSocketClient } from "../skillWebSocket";
import { getSkillExecutionWatcher } from "../skillExecutionWatcher";

const logger = createLogger("SkillsTab");

interface SkillDefinition {
  name: string;
  description: string;
  version: string;
  inputs: Array<{
    name: string;
    type: string;
    required: boolean;
    description: string;
  }>;
  step_count: number;
  file: string;
  category?: string;
}

interface RunningSkill {
  executionId: string;
  skillName: string;
  status: "running" | "completed" | "failed";
  progress: number;
  currentStep: string;
  startedAt: string;
  source: "chat" | "cron" | "slack" | "manual";
  elapsed: number;
}

interface SkillExecution {
  skill_name: string;
  status: "running" | "completed" | "failed" | "idle";
  started_at?: string;
  completed_at?: string;
  current_step?: string;
  progress?: number;
  error?: string;
}

interface ExecutionStep {
  name: string;
  description?: string;
  tool?: string;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  duration?: number;
  error?: string;
  memoryRead?: string[];
  memoryWrite?: string[];
  healingApplied?: boolean;
  retryCount?: number;
}

interface DetailedExecution {
  executionId: string;
  skillName: string;
  status: string;
  currentStepIndex: number;
  totalSteps: number;
  steps: ExecutionStep[];
  startTime?: string;
  endTime?: string;
}

export class SkillsTab extends BaseTab {
  private skills: SkillDefinition[] = [];
  private runningSkills: RunningSkill[] = [];
  private selectedSkill: string | null = null;
  private selectedSkillData: any = null;
  private currentExecution: SkillExecution | null = null;
  private detailedExecution: DetailedExecution | null = null;  // Live execution with step status
  private watchingExecutionId: string | null = null;  // Execution ID user explicitly selected to watch
  private skillView: "info" | "workflow" | "yaml" = "info";
  private workflowViewMode: "horizontal" | "vertical" = "horizontal";
  private wsClient: SkillWebSocketClient | null = null;
  private wsDisposables: vscode.Disposable[] = [];

  constructor() {
    super({
      id: "skills",
      label: "Skills",
      icon: "⚡",
    });

    // Connect to WebSocket for real-time skill updates
    this.setupWebSocketConnection();
  }

  private setupWebSocketConnection(): void {
    try {
      this.wsClient = getSkillWebSocketClient();

      // Subscribe to skill events
      this.wsDisposables.push(
        this.wsClient.onSkillStarted((skill) => {
          logger.log(`WebSocket: Skill started - ${skill.skillName}`);
          this.addOrUpdateRunningSkill(skill);
          this.notifyNeedsRender();
        })
      );

      this.wsDisposables.push(
        this.wsClient.onSkillUpdate((skill) => {
          logger.log(`WebSocket: Skill update - ${skill.skillName} step ${skill.currentStep}/${skill.totalSteps}`);
          this.addOrUpdateRunningSkill(skill);
          this.notifyNeedsRender();
        })
      );

      this.wsDisposables.push(
        this.wsClient.onSkillCompleted(({ skillId, success }) => {
          logger.log(`WebSocket: Skill completed - ${skillId} success=${success}`);
          this.markSkillCompleted(skillId, success);
          this.notifyNeedsRender();
        })
      );

      this.wsDisposables.push(
        this.wsClient.onStepUpdate(({ skillId, step }) => {
          logger.log(`WebSocket: Step update - ${skillId} step ${step.index}: ${step.status}`);
          this.updateSkillStep(skillId, step);
          this.notifyNeedsRender();
        })
      );

      // Load any currently running skills
      this.loadRunningSkillsFromWebSocket();

      logger.log("WebSocket connection setup complete");
    } catch (e) {
      logger.warn(`Failed to setup WebSocket connection: ${e}`);
    }
  }

  private loadRunningSkillsFromWebSocket(): void {
    if (!this.wsClient) return;

    const running = this.wsClient.getRunningSkills();
    logger.log(`Loading ${running.length} running skills from WebSocket`);

    for (const skill of running) {
      this.addOrUpdateRunningSkill(skill);
    }
  }

  private addOrUpdateRunningSkill(skill: SkillState): void {
    const existing = this.runningSkills.find(s => s.executionId === skill.skillId);

    const progress = skill.totalSteps > 0
      ? Math.round((skill.currentStep / skill.totalSteps) * 100)
      : 0;

    const elapsed = Date.now() - skill.startedAt.getTime();

    if (existing) {
      existing.status = skill.status === "running" ? "running" : skill.status === "completed" ? "completed" : "failed";
      existing.progress = progress;
      existing.currentStep = skill.currentStepName || `Step ${skill.currentStep}`;
      existing.elapsed = elapsed;
    } else {
      this.runningSkills.push({
        executionId: skill.skillId,
        skillName: skill.skillName,
        status: skill.status === "running" ? "running" : skill.status === "completed" ? "completed" : "failed",
        progress,
        currentStep: skill.currentStepName || `Step ${skill.currentStep}`,
        startedAt: skill.startedAt.toISOString(),
        source: "manual",
        elapsed,
      });
    }
  }

  private markSkillCompleted(skillId: string, success: boolean): void {
    const skill = this.runningSkills.find(s => s.executionId === skillId);
    if (skill) {
      skill.status = success ? "completed" : "failed";
      skill.progress = 100;

      // Remove after a delay
      setTimeout(() => {
        this.runningSkills = this.runningSkills.filter(s => s.executionId !== skillId);
        this.notifyNeedsRender();
      }, 5000);
    }
  }

  private updateSkillStep(skillId: string, step: any): void {
    const skill = this.runningSkills.find(s => s.executionId === skillId);
    if (skill) {
      skill.currentStep = step.name || `Step ${step.index}`;
    }
  }

  dispose(): void {
    // Clean up WebSocket subscriptions
    for (const d of this.wsDisposables) {
      d.dispose();
    }
    this.wsDisposables = [];
  }

  getBadge(): { text: string; class?: string } | null {
    // Show "Running" with glow effect if any skills are running
    const runningCount = this.runningSkills.filter(
      (s) => s.status === "running"
    ).length;
    if (runningCount > 0) {
      return { text: "Running", class: "running-glow" };
    }
    // Show total skill count
    if (this.skills.length > 0) {
      return { text: `${this.skills.length}` };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Load skills list via D-Bus
      logger.log("Calling config_getSkillsList()...");
      const skillsResult = await dbus.config_getSkillsList();
      logger.log(`config_getSkillsList() result: success=${skillsResult.success}, error=${skillsResult.error || 'none'}`);
      if (skillsResult.success && skillsResult.data) {
        const data = skillsResult.data as any;
        this.skills = data.skills || [];
        this.categorizeSkills();
        logger.log(`Loaded ${this.skills.length} skills`);
      } else if (skillsResult.error) {
        this.lastError = `Skills list failed: ${skillsResult.error}`;
        logger.warn(this.lastError);
      }

      // Load current skill execution via D-Bus
      logger.log("Calling stats_getSkillExecution()...");
      const execResult = await dbus.stats_getSkillExecution();
      logger.log(`stats_getSkillExecution() result: success=${execResult.success}, error=${execResult.error || 'none'}`);
      if (execResult.success && execResult.data) {
        const data = execResult.data as any;
        this.currentExecution = data.execution || null;
        this.updateRunningSkills();
        logger.log(`Current execution: ${this.currentExecution?.skill_name || 'none'}`);
      } else if (execResult.error) {
        logger.warn(`Skill execution failed: ${execResult.error}`);
      }
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  private categorizeSkills(): void {
    // Categorize skills based on naming patterns
    this.skills.forEach((skill) => {
      const name = skill.name.toLowerCase();
      if (name.includes("deploy") || name.includes("ephemeral")) {
        skill.category = "DevOps";
      } else if (name.includes("jira") || name.includes("issue")) {
        skill.category = "Jira";
      } else if (name.includes("gitlab") || name.includes("mr")) {
        skill.category = "GitLab";
      } else if (name.includes("slack")) {
        skill.category = "Slack";
      } else if (name.includes("coffee") || name.includes("beer")) {
        skill.category = "Daily";
      } else {
        skill.category = "General";
      }
    });

    // Auto-select first skill if none selected
    if (!this.selectedSkill && this.skills.length > 0) {
      this.loadSkill(this.skills[0].name);
    }
  }

  private updateRunningSkills(): void {
    if (this.currentExecution && this.currentExecution.status === "running") {
      const existing = this.runningSkills.find(
        (s) => s.skillName === this.currentExecution!.skill_name
      );
      if (!existing) {
        this.runningSkills.push({
          executionId: `exec-${Date.now()}`,
          skillName: this.currentExecution.skill_name,
          status: "running",
          progress: this.currentExecution.progress || 0,
          currentStep: this.currentExecution.current_step || "",
          startedAt: this.currentExecution.started_at || new Date().toISOString(),
          source: "manual",
          elapsed: 0,
        });
      }
    }
  }

  getContent(): string {
    const runningCount = this.runningSkills.filter(
      (s) => s.status === "running"
    ).length;

    return `
      <!-- Running Skills Panel -->
      ${runningCount > 0 ? this.getRunningSkillsHtml() : ""}

      <!-- Skills Layout -->
      <div class="skills-layout">
        <!-- Skills Sidebar -->
        <div class="skills-sidebar">
          <div class="skills-search">
            <input type="text" placeholder="Search skills..." id="skillSearch" />
          </div>
          <div class="skills-list">
            ${this.getSkillsListHtml()}
          </div>
        </div>

        <!-- Skills Main Content -->
        <div class="skills-main">
          <div class="skills-main-header">
            <div class="skills-main-title">
              ${this.selectedSkill ? this.selectedSkill : "Select a skill"}
            </div>
            <div class="view-toggle">
              <button class="toggle-btn ${this.skillView === "info" ? "active" : ""}" data-view="info">Info</button>
              <button class="toggle-btn ${this.skillView === "workflow" ? "active" : ""}" data-view="workflow">Workflow</button>
              <button class="toggle-btn ${this.skillView === "yaml" ? "active" : ""}" data-view="yaml">YAML</button>
            </div>
          </div>
          <div class="skills-main-content" id="skillContent">
            ${this.getSkillContentHtml()}
          </div>
        </div>
      </div>
    `;
  }

  private getRunningSkillsHtml(): string {
    const running = this.runningSkills.filter((s) => s.status === "running");
    if (running.length === 0) return "";

    let html = `
      <div class="running-skills-panel">
        <div class="running-skills-header">
          <div class="running-skills-title">
            <span class="running-indicator"></span>
            Running Skills (${running.length})
          </div>
          <div class="running-skills-actions">
            <button class="btn btn-xs btn-danger" data-action="clearStaleSkills">Clear Stale</button>
          </div>
        </div>
        <div class="running-skills-list">
    `;

    running.forEach((skill) => {
      const elapsed = this.formatDuration(skill.elapsed);
      html += `
        <div class="running-skill-item" data-execution-id="${skill.executionId}">
          <div class="running-skill-progress">
            <div class="running-skill-progress-bar">
              <div class="running-skill-progress-fill" style="width: ${skill.progress}%"></div>
            </div>
            <div class="running-skill-progress-text">${skill.progress}%</div>
          </div>
          <div class="running-skill-info">
            <div class="running-skill-name">${this.escapeHtml(skill.skillName)}</div>
            <div class="running-skill-source">
              <span class="source-badge ${skill.source}">${skill.source}</span>
              ${skill.currentStep ? `Step: ${this.escapeHtml(skill.currentStep)}` : ""}
            </div>
          </div>
          <div class="running-skill-elapsed">${elapsed}</div>
          <button class="clear-skill-btn" data-action="clearSkillExecution" data-execution-id="${skill.executionId}">×</button>
        </div>
      `;
    });

    html += `
        </div>
      </div>
    `;

    return html;
  }

  private getSkillsListHtml(): string {
    // Group skills by category
    const categories: Record<string, SkillDefinition[]> = {};
    this.skills.forEach((skill) => {
      const cat = skill.category || "General";
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push(skill);
    });

    let html = "";
    Object.entries(categories)
      .sort(([a], [b]) => a.localeCompare(b))
      .forEach(([category, skills]) => {
        html += `
          <div class="skill-category">
            <div class="skill-category-title">${category}</div>
        `;
        skills.forEach((skill) => {
          const isSelected = this.selectedSkill === skill.name;
          html += `
            <div class="skill-item ${isSelected ? "selected" : ""}" data-skill="${skill.name}">
              <span class="skill-item-icon">⚡</span>
              <div>
                <div class="skill-item-name">${this.escapeHtml(skill.name)}</div>
                <div class="skill-item-desc">${this.escapeHtml(skill.description || "").substring(0, 50)}</div>
              </div>
            </div>
          `;
        });
        html += `</div>`;
      });

    return html || '<div class="loading-placeholder">No skills found</div>';
  }

  private getSkillContentHtml(): string {
    if (!this.selectedSkill) {
      return this.getEmptyStateHtml("⚡", "Select a skill to view details");
    }

    const skill = this.skills.find((s) => s.name === this.selectedSkill);
    if (!skill) {
      return this.getEmptyStateHtml("❓", "Skill not found");
    }

    // YAML view
    if (this.skillView === "yaml") {
      return this.getSkillYamlView(skill);
    }

    // Workflow view
    if (this.skillView === "workflow") {
      return this.getSkillWorkflowView(skill);
    }

    // Info view (default)
    return this.getSkillInfoView(skill);
  }

  private getSkillInfoView(skill: SkillDefinition): string {
    return `
      <div class="skill-info-view">
        <div class="skill-info-card">
          <div class="skill-info-title">${this.escapeHtml(skill.name)} ${skill.version ? `<span class="skill-version">v${skill.version}</span>` : ""}</div>
          <div class="skill-info-desc">${this.escapeHtml(skill.description || "No description")}</div>
        </div>

        ${skill.inputs && skill.inputs.length > 0 ? `
          <div class="skill-inputs-section">
            <div class="skill-inputs-title">📥 Inputs</div>
            ${skill.inputs.map((input) => `
              <div class="skill-input-item">
                <span class="skill-input-name">${input.name}${input.required ? " *" : ""}</span>
                <span class="skill-input-type">${input.type || "any"}</span>
                <span class="skill-input-desc">${this.escapeHtml(input.description || "")}</span>
              </div>
            `).join("")}
          </div>
        ` : ""}

        <div class="skill-stats-section">
          <div class="skill-stats-title">📊 Quick Stats</div>
          <div class="skill-stats-grid">
            <div class="skill-stat">
              <span class="stat-value">${skill.step_count || 0}</span>
              <span class="stat-label">Steps</span>
            </div>
            <div class="skill-stat">
              <span class="stat-value">${skill.inputs?.length || 0}</span>
              <span class="stat-label">Inputs</span>
            </div>
          </div>
        </div>

        <div class="section-actions">
          <button class="btn btn-sm btn-primary" data-action="runSkill" data-skill="${skill.name}">▶ Run Skill</button>
          <button class="btn btn-sm" data-action="openSkillFile" data-skill="${skill.name}">📄 Open File</button>
        </div>
      </div>
    `;
  }

  private getSkillWorkflowView(skill: SkillDefinition): string {
    const skillData = this.selectedSkillData;
    const steps = skillData?.steps || [];

    if (steps.length === 0) {
      return `
        <div class="skill-workflow-view">
          <div class="workflow-header">
            <div class="workflow-title">${this.escapeHtml(skill.name)}</div>
            <div class="workflow-meta">Steps: ${skill.step_count || 0} • Status: Ready</div>
          </div>
          <div class="workflow-empty">
            <p>No step data available. Click "Open File" to view the skill YAML.</p>
            <button class="btn btn-sm" data-action="openSkillFile" data-skill="${skill.name}">📄 Open File</button>
          </div>
        </div>
      `;
    }

    // Generate horizontal flowchart with circles and connecting lines
    const horizontalStepsHtml = steps.map((step: any, index: number) =>
      this.getHorizontalStepHtml(step, index, index === steps.length - 1)
    ).join("");

    // Generate vertical flowchart
    const verticalStepsHtml = steps.map((step: any, index: number) =>
      this.getVerticalStepHtml(step, index, index === steps.length - 1)
    ).join("");

    // Get execution status for this skill
    const isExecuting = this.detailedExecution?.skillName === skill.name;
    const execStatus = isExecuting ? this.detailedExecution!.status : "ready";
    const execStep = isExecuting ? `${this.detailedExecution!.currentStepIndex + 1}/${this.detailedExecution!.totalSteps}` : "";
    const statusText = isExecuting ? `Step ${execStep} • ${this.capitalizeFirst(execStatus)}` : "Ready";
    const statusClass = isExecuting && execStatus === "running" ? "status-running" : "";

    return `
      <div class="skill-workflow-view">
        <div class="workflow-header">
          <div class="workflow-title">${this.escapeHtml(skill.name)}</div>
          <div class="workflow-header-right">
            <div class="workflow-meta ${statusClass}">Steps: ${steps.length} • Status: ${statusText}</div>
            <div class="view-toggle">
              <button class="toggle-btn ${this.workflowViewMode === "horizontal" ? "active" : ""}" data-workflow-view="horizontal">━ Horizontal</button>
              <button class="toggle-btn ${this.workflowViewMode === "vertical" ? "active" : ""}" data-workflow-view="vertical">┃ Vertical</button>
            </div>
          </div>
        </div>
        <div class="workflow-legend">
          <span class="legend-item" title="Memory Read"><span class="legend-icon">📖</span> Read</span>
          <span class="legend-item" title="Memory Write"><span class="legend-icon">💾</span> Write</span>
          <span class="legend-item" title="Semantic Search"><span class="legend-icon">🔍</span> Search</span>
          <span class="legend-item" title="Tool Call"><span class="legend-icon">🔧</span> Tool</span>
          <span class="legend-item" title="Python Compute"><span class="legend-icon">🐍</span> Compute</span>
          <span class="legend-item" title="Conditional"><span class="legend-icon">❓</span> Conditional</span>
          <span class="legend-item" title="Auto-remediation"><span class="legend-icon">🔄</span> Auto-heal</span>
          <span class="legend-item" title="Can Retry"><span class="legend-icon">↩️</span> Retry</span>
        </div>
        <div class="flowchart-horizontal" id="flowchart-horizontal" style="display: ${this.workflowViewMode === "horizontal" ? "block" : "none"};">
          <div class="flowchart-wrap">
            ${horizontalStepsHtml}
          </div>
        </div>
        <div class="flowchart-vertical" id="flowchart-vertical" style="display: ${this.workflowViewMode === "vertical" ? "block" : "none"};">
          ${verticalStepsHtml}
        </div>
        <div class="section-actions">
          <button class="btn btn-sm btn-primary" data-action="runSkill" data-skill="${skill.name}">▶ Run Skill</button>
          <button class="btn btn-sm" data-action="openSkillFile" data-skill="${skill.name}">📄 Open File</button>
        </div>
      </div>
    `;
  }

  private getHorizontalStepHtml(step: any, index: number, isLast: boolean): string {
    const stepNumber = index + 1;
    const tool = step.tool || "";
    const name = step.name || `Step ${stepNumber}`;

    // Get execution status for this step if available
    const execStep = this.getExecutionStepStatus(index);
    const status = execStep?.status || "pending";

    // Analyze step for lifecycle indicators
    const lifecycleIndicators = this.getLifecycleIndicators(step, execStep);
    const typeTags = this.getStepTypeTags(step);

    // Determine if this is a skill call
    const isSkillCall = tool === "skill_run";
    const calledSkillName = isSkillCall && step.args?.skill_name ? step.args.skill_name : null;

    // Build tooltip
    const tooltipParts = [step.description || name];
    if (isSkillCall && calledSkillName) {
      tooltipParts.push(`Calls skill: ${calledSkillName}`);
    } else if (tool) {
      tooltipParts.push(`Tool: ${tool}`);
    }
    if (execStep?.duration) {
      tooltipParts.push(`Duration: ${this.formatDuration(execStep.duration)}`);
    }
    if (execStep?.error) {
      tooltipParts.push(`Error: ${execStep.error}`);
    }
    const tooltip = tooltipParts.join("\n");

    const skillCallClass = isSkillCall ? "skill-call" : "";
    const rowLastClass = isLast ? "row-last" : "";

    // Skill call badge
    const skillCallBadge = isSkillCall && calledSkillName
      ? `<div class="skill-call-badge" data-skill="${this.escapeHtml(calledSkillName)}" title="Click to view ${calledSkillName} skill">⚡ ${this.escapeHtml(calledSkillName)}</div>`
      : "";

    // Icon based on status
    const icon = this.getStepIcon(status, stepNumber, isSkillCall);

    return `
      <div class="step-node-h ${status} ${skillCallClass} ${rowLastClass}" title="${this.escapeHtml(tooltip)}" data-step-index="${index}">
        <div class="step-connector-h"></div>
        ${lifecycleIndicators.length > 0 ? `<div class="step-lifecycle-h">${lifecycleIndicators.join("")}</div>` : ""}
        <div class="step-icon-h">${icon}</div>
        <div class="step-content-h">
          <div class="step-name-h">${this.escapeHtml(name)}</div>
          ${typeTags.length > 0 ? `<div class="step-type-h">${typeTags.join("")}</div>` : ""}
          ${skillCallBadge}
        </div>
      </div>
    `;
  }

  /**
   * Get execution status for a step by index
   */
  private getExecutionStepStatus(index: number): ExecutionStep | null {
    if (!this.detailedExecution || !this.detailedExecution.steps) {
      return null;
    }
    if (this.detailedExecution.skillName !== this.selectedSkill) {
      return null;
    }
    return this.detailedExecution.steps[index] || null;
  }

  /**
   * Get icon for step based on status
   */
  private getStepIcon(status: string, stepNumber: number, isSkillCall: boolean): string {
    if (isSkillCall) return "⚡";
    switch (status) {
      case "running": return "⏳";
      case "success": return "✓";
      case "failed": return "✗";
      case "skipped": return "⊘";
      default: return String(stepNumber);
    }
  }

  private getVerticalStepHtml(step: any, index: number, isLast: boolean): string {
    const stepNumber = index + 1;
    const tool = step.tool || "";
    const name = step.name || `Step ${stepNumber}`;

    // Build tags
    const tags: string[] = [];
    const isSkillCall = tool === "skill_run";
    const calledSkillName = isSkillCall && step.args?.skill_name ? step.args.skill_name : null;

    if (isSkillCall && calledSkillName) {
      tags.push(`<span class="step-tag skill-call" data-skill="${this.escapeHtml(calledSkillName)}">⚡ calls: ${calledSkillName}</span>`);
    } else if (tool) {
      tags.push(`<span class="step-tag tool">🔧 ${tool}</span>`);
    }
    if (step.compute) tags.push(`<span class="step-tag compute">🐍 compute</span>`);
    if (step.condition) tags.push(`<span class="step-tag condition">❓ conditional</span>`);
    if (step.on_error === "continue" || step.on_error === "retry") {
      tags.push(`<span class="step-tag can-retry">↩️ can retry</span>`);
    }

    // Lifecycle tags
    const memoryReadTools = ["memory_read", "memory_query", "check_known_issues"];
    const memoryWriteTools = ["memory_write", "memory_update", "memory_append", "memory_session_log"];
    const searchTools = ["knowledge_query", "knowledge_search", "semantic_search", "code_search"];

    if (memoryReadTools.some(t => tool.includes(t))) {
      tags.push(`<span class="step-tag memory-read">📖 memory read</span>`);
    }
    if (memoryWriteTools.some(t => tool.includes(t))) {
      tags.push(`<span class="step-tag memory-write">💾 memory write</span>`);
    }
    if (searchTools.some(t => tool.includes(t))) {
      tags.push(`<span class="step-tag semantic-search">🔍 search</span>`);
    }

    const skillCallClass = isSkillCall ? "skill-call" : "";

    return `
      <div class="step-node pending ${skillCallClass}">
        ${!isLast ? '<div class="step-connector"></div>' : ''}
        <div class="step-icon">${isSkillCall ? "⚡" : stepNumber}</div>
        <div class="step-content">
          <div class="step-header">
            <span class="step-name">${this.escapeHtml(name)}</span>
          </div>
          ${step.description ? `<div class="step-desc">${this.escapeHtml(step.description)}</div>` : ""}
          ${tags.length > 0 ? `<div class="step-meta">${tags.join("")}</div>` : ""}
        </div>
      </div>
    `;
  }

  private getLifecycleIndicators(step: any, execStep?: ExecutionStep | null): string[] {
    const indicators: string[] = [];
    const tool = step.tool || "";
    const name = step.name || "";

    // Memory read operations (static or from execution)
    const memoryReadTools = ["memory_read", "memory_query", "check_known_issues"];
    if (memoryReadTools.some(t => tool.includes(t)) || name.toLowerCase().includes("load_config") || (execStep?.memoryRead && execStep.memoryRead.length > 0)) {
      indicators.push(`<span class="lifecycle-indicator memory-read" title="Memory Read">📖</span>`);
    }

    // Memory write operations (static or from execution)
    const memoryWriteTools = ["memory_write", "memory_update", "memory_append", "memory_session_log", "learn_tool_fix"];
    if (memoryWriteTools.some(t => tool.includes(t)) || name.toLowerCase().includes("save_") || (execStep?.memoryWrite && execStep.memoryWrite.length > 0)) {
      indicators.push(`<span class="lifecycle-indicator memory-write" title="Memory Write">💾</span>`);
    }

    // Semantic search
    const searchTools = ["knowledge_query", "knowledge_search", "semantic_search", "code_search", "vector_search"];
    if (searchTools.some(t => tool.includes(t))) {
      indicators.push(`<span class="lifecycle-indicator semantic-search" title="Semantic Search">🔍</span>`);
    }

    // Auto-remediation / healing applied during execution
    const autoRemediationPatterns = ["retry", "heal", "fix", "recover", "fallback"];
    if (autoRemediationPatterns.some(p => name.toLowerCase().includes(p)) || execStep?.healingApplied) {
      indicators.push(`<span class="lifecycle-indicator auto-heal" title="Auto-remediation">🔄</span>`);
    }

    // Can retry / retry count from execution
    if (step.on_error === "continue" || step.on_error === "retry" || (execStep?.retryCount && execStep.retryCount > 0)) {
      const retryText = execStep?.retryCount ? `Retried ${execStep.retryCount}x` : "Can Retry";
      indicators.push(`<span class="lifecycle-indicator can-retry" title="${retryText}">↩️</span>`);
    }

    return indicators;
  }

  private getStepTypeTags(step: any): string[] {
    const tags: string[] = [];
    const tool = step.tool || "";

    // Skip generic tool tag for skill calls - we show a special badge
    if (tool === "skill_run") {
      // Don't add tool tag
    } else if (tool) {
      tags.push(`<span class="tag tool" title="Tool: ${tool}">🔧</span>`);
    }
    if (step.compute) {
      tags.push(`<span class="tag compute" title="Python compute">🐍</span>`);
    }
    if (step.condition) {
      tags.push(`<span class="tag condition" title="Conditional: ${this.escapeHtml(step.condition)}">❓</span>`);
    }

    return tags;
  }

  private getSkillYamlView(skill: SkillDefinition): string {
    const skillData = this.selectedSkillData;

    if (!skillData) {
      return `
        <div class="skill-yaml-view">
          <div class="yaml-loading">Loading YAML...</div>
          <div class="section-actions mt-16">
            <button class="btn btn-sm" data-action="openSkillFile" data-skill="${skill.name}">📄 Open File in Editor</button>
          </div>
        </div>
      `;
    }

    // Format the skill data as YAML-like display
    const yamlContent = JSON.stringify(skillData, null, 2);

    return `
      <div class="skill-yaml-view">
        <div class="yaml-header">
          <span class="yaml-title">${this.escapeHtml(skill.name)}.yaml</span>
          <button class="btn btn-xs" data-action="openSkillFile" data-skill="${skill.name}">📄 Open in Editor</button>
        </div>
        <pre class="yaml-content"><code>${this.escapeHtml(yamlContent)}</code></pre>
      </div>
    `;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  // Large block of inline styles removed - they are now in skills.css
  // The following is a minimal placeholder to maintain file structure
  private _legacyStylesRemoved = `
      .skills-main {
        /* styles moved to skills.css */
      }

      .skills-main-header {
        padding: 16px;
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
      }

      .skills-main-title {
        font-size: 1.1rem;
        font-weight: 600;
      }

      .skills-main-content {
        flex: 1;
        padding: 16px;
      }

      .skill-info-view {
        display: flex;
        flex-direction: column;
        gap: 16px;
        padding: 8px 0;
      }

      .skill-info-card {
        background: var(--bg-tertiary);
        border-radius: 8px;
        padding: 16px;
        border-left: 3px solid var(--accent);
      }

      .skill-info-title {
        font-weight: 600;
        margin-bottom: 8px;
        color: var(--text-primary);
      }

      .skill-info-desc {
        color: var(--text-secondary);
        font-size: 0.9rem;
        line-height: 1.5;
      }

      .skill-inputs-section {
        background: var(--bg-tertiary);
        border-radius: 8px;
        padding: 16px;
      }

      .skill-inputs-title {
        font-weight: 600;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      .skill-input-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 8px 12px;
        background: var(--bg-secondary);
        border-radius: 6px;
        margin-bottom: 8px;
      }

      .skill-input-name {
        font-weight: 600;
        color: var(--text-primary);
        min-width: 120px;
      }

      .skill-input-type {
        font-size: 0.75rem;
        padding: 2px 6px;
        background: var(--bg-tertiary);
        border-radius: 4px;
        color: var(--text-muted);
      }

      .skill-input-desc {
        flex: 1;
        color: var(--text-secondary);
        font-size: 0.85rem;
      }

      .skill-stats-section {
        background: var(--bg-tertiary);
        border-radius: 8px;
        padding: 16px;
      }

      .skill-stats-title {
        font-weight: 600;
        margin-bottom: 12px;
        color: var(--text-primary);
      }

      .skill-stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
        gap: 12px;
      }

      .skill-stat {
        display: flex;
        flex-direction: column;
        align-items: center;
        padding: 12px;
        background: var(--bg-secondary);
        border-radius: 6px;
      }

      .skill-stat .stat-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: var(--text-primary);
      }

      .skill-stat .stat-label {
        font-size: 0.75rem;
        color: var(--text-muted);
        margin-top: 4px;
      }

      .skill-yaml-view {
        background: var(--bg-tertiary);
        border-radius: 8px;
        padding: 16px;
      }

      .yaml-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--border);
      }

      .yaml-title {
        font-family: var(--font-mono);
        font-weight: 600;
        color: var(--text-primary);
      }

      .yaml-content {
        font-family: var(--font-mono);
        font-size: 0.8rem;
        line-height: 1.5;
        overflow-x: auto;
        white-space: pre-wrap;
        word-break: break-word;
        background: var(--bg-secondary);
        padding: 16px;
        border-radius: 6px;
      }

      .yaml-loading {
        text-align: center;
        padding: 40px;
        color: var(--text-muted);
      }

      /* Workflow View Styles */
      .skill-workflow-view {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }

      .workflow-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding-bottom: 12px;
        border-bottom: 1px solid var(--border);
      }

      .workflow-header-right {
        display: flex;
        align-items: center;
        gap: 16px;
      }

      .workflow-title {
        font-size: 1.1rem;
        font-weight: 600;
      }

      .workflow-meta {
        font-size: 0.85rem;
        color: var(--text-secondary);
      }

      .workflow-meta.status-running {
        color: #8b5cf6;
        font-weight: 500;
        animation: pulse-text 1.5s ease-in-out infinite;
      }

      @keyframes pulse-text {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
      }

      .workflow-legend {
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        padding: 12px;
        background: var(--bg-tertiary);
        border-radius: 8px;
        font-size: 0.8rem;
      }

      .legend-item {
        display: flex;
        align-items: center;
        gap: 6px;
        color: var(--text-secondary);
        cursor: help;
      }

      .legend-icon {
        font-size: 1rem;
      }

      .workflow-empty {
        text-align: center;
        padding: 40px;
        color: var(--text-muted);
      }

      .workflow-empty p {
        margin-bottom: 16px;
      }

      /* Horizontal Flowchart - Circles with connecting lines */
      .flowchart-horizontal {
        padding: 12px 0;
        overflow: hidden;
      }

      .flowchart-wrap {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-start;
        gap: 20px 0;
        padding: 8px 0;
      }

      .step-node-h {
        display: flex;
        flex-direction: column;
        align-items: center;
        width: 140px;
        min-height: 100px;
        position: relative;
        flex-shrink: 0;
        padding: 0 8px;
      }

      .step-connector-h {
        position: absolute;
        top: 24px;
        left: 50%;
        width: calc(100% - 16px);
        height: 2px;
        background: var(--border);
        z-index: 0;
      }

      .step-node-h.row-last .step-connector-h {
        display: none;
      }

      .step-icon-h {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        font-weight: 700;
        z-index: 1;
        border: 2px solid var(--border);
        background: var(--bg-card);
        transition: all 0.3s;
        margin-bottom: 8px;
      }

      .step-node-h.pending .step-icon-h {
        border-color: #6b7280;
        color: #6b7280;
      }

      .step-node-h.running .step-icon-h {
        border-color: #8b5cf6;
        color: #8b5cf6;
        box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.2);
        animation: pulse-ring 1.5s ease-out infinite;
      }

      .step-node-h.success .step-icon-h {
        border-color: #10b981;
        background: #10b981;
        color: white;
      }

      .step-node-h.failed .step-icon-h {
        border-color: #ef4444;
        background: #ef4444;
        color: white;
      }

      .step-node-h.skill-call .step-icon-h {
        border-width: 3px;
        border-color: #f59e0b;
        background: rgba(245, 158, 11, 0.15);
        box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
      }

      @keyframes pulse-ring {
        0% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
        70% { box-shadow: 0 0 0 8px rgba(139, 92, 246, 0); }
        100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0); }
      }

      .step-content-h {
        text-align: center;
        padding: 0 4px;
      }

      .step-name-h {
        font-weight: 600;
        font-size: 11px;
        margin-bottom: 4px;
        word-wrap: break-word;
        max-width: 130px;
        line-height: 1.3;
      }

      .step-type-h {
        font-size: 11px;
        color: var(--text-muted);
        display: flex;
        justify-content: center;
        gap: 5px;
        flex-wrap: wrap;
        margin-top: 2px;
      }

      .step-type-h .tag {
        padding: 2px 5px;
        border-radius: 3px;
        background: var(--bg-secondary);
        font-size: 10px;
      }

      .step-type-h .tag.tool { background: rgba(59, 130, 246, 0.2); color: #3b82f6; }
      .step-type-h .tag.compute { background: rgba(139, 92, 246, 0.2); color: #8b5cf6; }
      .step-type-h .tag.condition { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }

      /* Lifecycle Indicators - Badges above circles */
      .step-lifecycle-h {
        position: absolute;
        top: -8px;
        left: 50%;
        transform: translateX(-50%);
        display: flex;
        gap: 2px;
        z-index: 2;
      }

      .lifecycle-indicator {
        font-size: 11px;
        width: 18px;
        height: 18px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 50%;
        background: var(--bg-card);
        border: 1px solid var(--border);
        cursor: help;
        transition: transform 0.2s;
      }

      .lifecycle-indicator:hover {
        transform: scale(1.2);
        z-index: 10;
      }

      .lifecycle-indicator.memory-read {
        background: rgba(59, 130, 246, 0.2);
        border-color: #3b82f6;
      }

      .lifecycle-indicator.memory-write {
        background: rgba(16, 185, 129, 0.2);
        border-color: #10b981;
      }

      .lifecycle-indicator.semantic-search {
        background: rgba(139, 92, 246, 0.2);
        border-color: #8b5cf6;
      }

      .lifecycle-indicator.auto-heal {
        background: rgba(245, 158, 11, 0.2);
        border-color: #f59e0b;
      }

      .lifecycle-indicator.can-retry {
        background: rgba(139, 92, 246, 0.15);
        border-color: #8b5cf6;
      }

      /* Skill call badge */
      .skill-call-badge {
        display: inline-flex;
        align-items: center;
        gap: 3px;
        padding: 2px 6px;
        background: rgba(245, 158, 11, 0.25);
        border: 1px solid #f59e0b;
        border-radius: 4px;
        font-size: 9px;
        color: #f59e0b;
        margin-top: 4px;
        font-weight: 600;
        cursor: pointer;
      }

      .skill-call-badge:hover {
        background: rgba(245, 158, 11, 0.35);
      }

      /* Vertical Flowchart */
      .flowchart-vertical {
        padding: 12px 0;
      }

      .step-node {
        display: flex;
        align-items: flex-start;
        margin-bottom: 8px;
        position: relative;
        padding-left: 8px;
      }

      .step-connector {
        position: absolute;
        left: 23px;
        top: 32px;
        bottom: -8px;
        width: 2px;
        background: var(--border);
      }

      .step-node:last-child .step-connector {
        display: none;
      }

      .step-icon {
        width: 32px;
        height: 32px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 14px;
        font-weight: 600;
        flex-shrink: 0;
        z-index: 1;
        border: 2px solid var(--border);
        background: var(--bg-card);
        transition: all 0.3s;
      }

      .step-node.pending .step-icon {
        border-color: #6b7280;
        color: #6b7280;
      }

      .step-node.skill-call .step-icon {
        border-width: 2px;
        border-color: #f59e0b;
        background: rgba(245, 158, 11, 0.15);
      }

      .step-content {
        flex: 1;
        margin-left: 12px;
        min-width: 0;
      }

      .step-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 2px;
      }

      .step-name {
        font-weight: 600;
        font-size: 13px;
      }

      .step-desc {
        font-size: 12px;
        color: var(--text-secondary);
        margin-bottom: 4px;
      }

      .step-meta {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
      }

      .step-tag {
        font-size: 10px;
        padding: 2px 6px;
        border-radius: 4px;
        background: var(--bg-secondary);
        color: var(--text-secondary);
        font-family: var(--font-mono);
      }

      .step-tag.tool { background: rgba(59, 130, 246, 0.2); color: #3b82f6; }
      .step-tag.compute { background: rgba(139, 92, 246, 0.2); color: #8b5cf6; }
      .step-tag.condition { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
      .step-tag.skill-call {
        background: rgba(245, 158, 11, 0.3);
        color: #f59e0b;
        font-weight: 600;
        border: 1px solid #f59e0b;
        cursor: pointer;
      }
      .step-tag.memory-read { background: rgba(59, 130, 246, 0.15); color: #3b82f6; }
      .step-tag.memory-write { background: rgba(16, 185, 129, 0.15); color: #10b981; }
      .step-tag.semantic-search { background: rgba(139, 92, 246, 0.15); color: #8b5cf6; }
      .step-tag.can-retry { background: rgba(139, 92, 246, 0.1); color: #8b5cf6; }

      /* Running Skills Panel */
      .running-skills-panel {
        background: var(--bg-tertiary);
        border: 1px solid var(--border);
        border-radius: 10px;
        margin-bottom: 20px;
        overflow: hidden;
      }

      .running-skills-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 12px 16px;
        background: rgba(139, 92, 246, 0.1);
        border-bottom: 1px solid var(--border);
      }

      .running-skills-title {
        display: flex;
        align-items: center;
        gap: 8px;
        font-weight: 600;
        color: var(--text-primary);
      }

      .running-indicator {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #10b981;
        animation: pulse 1.5s ease-in-out infinite;
      }

      @keyframes pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50% { opacity: 0.5; transform: scale(1.2); }
      }

      .running-skills-actions {
        display: flex;
        gap: 8px;
      }

      .running-skills-list {
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        max-height: 300px;
        overflow-y: auto;
      }

      .running-skill-item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: var(--bg-card);
        border-radius: 8px;
        border: 1px solid var(--border);
        cursor: pointer;
        transition: all 0.2s;
      }

      .running-skill-item:hover {
        border-color: var(--purple);
        background: rgba(139, 92, 246, 0.05);
      }

      .running-skill-progress {
        width: 60px;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
      }

      .running-skill-progress-bar {
        width: 100%;
        height: 4px;
        background: var(--bg-secondary);
        border-radius: 2px;
        overflow: hidden;
      }

      .running-skill-progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #8b5cf6, #6366f1);
        border-radius: 2px;
        transition: width 0.3s ease;
      }

      .running-skill-progress-text {
        font-size: 0.7rem;
        color: var(--text-muted);
        font-weight: 600;
      }

      .running-skill-info {
        flex: 1;
        min-width: 0;
      }

      .running-skill-name {
        font-weight: 600;
        font-size: 0.9rem;
        color: var(--text-primary);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .running-skill-source {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 0.75rem;
        color: var(--text-secondary);
        margin-top: 2px;
      }

      .source-badge {
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.65rem;
        font-weight: 600;
        text-transform: uppercase;
      }

      .source-badge.chat { background: rgba(59, 130, 246, 0.2); color: #3b82f6; }
      .source-badge.cron { background: rgba(245, 158, 11, 0.2); color: #f59e0b; }
      .source-badge.slack { background: rgba(16, 185, 129, 0.2); color: #10b981; }
      .source-badge.manual { background: rgba(139, 92, 246, 0.2); color: #8b5cf6; }

      .running-skill-elapsed {
        font-size: 0.8rem;
        color: var(--text-muted);
        font-family: var(--font-mono);
        min-width: 60px;
        text-align: right;
      }

      .clear-skill-btn {
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: none;
        background: rgba(239, 68, 68, 0.1);
        color: #ef4444;
        cursor: pointer;
        font-size: 14px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all 0.2s;
      }

      .clear-skill-btn:hover {
        background: rgba(239, 68, 68, 0.2);
      }
    `;

  getScript(): string {
    return `
      // Skill search
      const skillSearch = document.getElementById('skillSearch');
      if (skillSearch) {
        skillSearch.addEventListener('input', (e) => {
          const query = e.target.value.toLowerCase();
          document.querySelectorAll('.skill-item').forEach(item => {
            const name = item.querySelector('.skill-item-name')?.textContent?.toLowerCase() || '';
            const desc = item.querySelector('.skill-item-desc')?.textContent?.toLowerCase() || '';
            item.style.display = (name.includes(query) || desc.includes(query)) ? '' : 'none';
          });
        });
      }

      // Skill selection
      document.querySelectorAll('.skill-item').forEach(item => {
        item.addEventListener('click', () => {
          const skillName = item.dataset.skill;
          if (skillName) {
            vscode.postMessage({ command: 'loadSkill', skillName });
          }
        });
      });

      // View toggle
      document.querySelectorAll('.toggle-btn[data-view]').forEach(btn => {
        btn.addEventListener('click', () => {
          const view = btn.dataset.view;
          vscode.postMessage({ command: 'setSkillView', view });
        });
      });

      // Run skill button
      document.querySelectorAll('[data-action="runSkill"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const skillName = btn.dataset.skill;
          if (skillName) {
            vscode.postMessage({ command: 'runSkill', skillName });
          }
        });
      });

      // Open skill file button
      document.querySelectorAll('[data-action="openSkillFile"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const skillName = btn.dataset.skill;
          if (skillName) {
            vscode.postMessage({ command: 'openSkillFile', skillName });
          }
        });
      });
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;
    logger.log(`handleMessage: ${msgType}`);

    switch (msgType) {
      case "loadSkill":
        await this.loadSkill(message.skillName);
        this.notifyNeedsRender();
        return true;

      case "setSkillView":
        this.skillView = message.view;
        this.notifyNeedsRender();
        return true;

      case "setWorkflowViewMode":
        this.workflowViewMode = message.mode;
        this.notifyNeedsRender();
        return true;

      case "runSkill":
        await this.runSkill(message.skillName);
        return true;

      case "openSkillFile":
        await this.openSkillFile(message.skillName);
        return true;

      case "clearStaleSkills":
        await this.clearStaleSkillsFromFile();
        this.notifyNeedsRender();
        return true;

      case "clearSkillExecution":
        await this.clearSkillExecutionFromFile(message.executionId);
        this.notifyNeedsRender();
        return true;

      case "openRunningSkillFlowchart":
        if (message.executionId) {
          await this.selectRunningSkill(message.executionId);
          this.notifyNeedsRender();
        }
        return true;

      case "runningSkillsUpdate":
        // Update running skills from the skill execution watcher
        if (message.runningSkills && Array.isArray(message.runningSkills)) {
          this.runningSkills = message.runningSkills.map((s: any) => ({
            executionId: s.executionId || `exec-${Date.now()}`,
            skillName: s.skillName,
            status: s.status === "running" ? "running" : s.status === "success" ? "completed" : "failed",
            progress: s.totalSteps > 0 ? Math.round((s.currentStepIndex / s.totalSteps) * 100) : 0,
            currentStep: `Step ${s.currentStepIndex + 1}/${s.totalSteps}`,
            startedAt: s.startTime || new Date().toISOString(),
            source: (s.source as "chat" | "cron" | "slack" | "manual") || "manual",
            elapsed: s.elapsedMs || 0,
          }));
          logger.log(`Updated running skills: ${this.runningSkills.length} skills`);
          this.notifyNeedsRender();
        }
        return true;

      case "skillExecutionUpdate":
        // Update detailed execution with step status (from watcher)
        // Only update if user explicitly selected this execution to watch
        if (message.execution && this.watchingExecutionId === message.execution.executionId) {
          const exec = message.execution;
          this.detailedExecution = {
            executionId: exec.executionId,
            skillName: exec.skillName,
            status: exec.status,
            currentStepIndex: exec.currentStepIndex,
            totalSteps: exec.totalSteps,
            steps: exec.steps || [],
            startTime: exec.startTime,
            endTime: exec.endTime,
          };
          logger.log(`Execution update: ${exec.skillName} step ${exec.currentStepIndex}/${exec.totalSteps}, ${exec.steps?.length || 0} steps with status`);

          // If viewing this skill's workflow, re-render to show step progress
          if (this.selectedSkill === exec.skillName && this.skillView === "workflow") {
            this.notifyNeedsRender();
          }
        }
        return true;

      default:
        return false;
    }
  }

  private async loadSkill(skillName: string): Promise<void> {
    this.selectedSkill = skillName;

    // Clear execution watching when switching skills from sidebar
    // (selectRunningSkill sets watchingExecutionId BEFORE calling loadSkill)
    // If watchingExecutionId is set and matches a running skill with this name, keep it
    const isWatchingThisSkill = this.watchingExecutionId &&
      this.runningSkills.some(s => s.executionId === this.watchingExecutionId && s.skillName === skillName);

    if (!isWatchingThisSkill) {
      // User clicked a skill from sidebar, not from Running Skills
      // Clear execution state to show static template
      this.watchingExecutionId = null;
      this.detailedExecution = null;
    }

    try {
      const result = await dbus.config_getSkillDefinition(skillName);
      if (result.success && result.data) {
        this.selectedSkillData = (result.data as any).skill || result.data;
      }
    } catch (error) {
      logger.error("Error loading skill", error);
    }
  }

  private async runSkill(skillName?: string): Promise<void> {
    const skill = skillName || this.selectedSkill;
    if (!skill) {
      logger.warn("runSkill called but no skill selected");
      vscode.window.showWarningMessage("No skill selected. Please select a skill first.");
      return;
    }

    logger.log(`Running skill: ${skill}`);

    // Build the command to run in chat
    const command = `skill_run("${skill}")`;

    try {
      // Import chatUtils functions
      const { sendEnter, sendPaste, sleep } = await import("../chatUtils");

      // Step 1: Copy command to clipboard
      logger.log(`Step 1: Copying command to clipboard: ${command}`);
      await vscode.env.clipboard.writeText(command);

      // Step 2: Create new composer tab
      logger.log("Step 2: Creating new composer tab...");
      await vscode.commands.executeCommand("composer.createNewComposerTab");
      await sleep(500);

      // Step 3: Press Enter to accept the "new chat" prompt
      logger.log("Step 3: Pressing Enter to accept prompt...");
      const enterResult1 = sendEnter();
      logger.log(`Enter result: ${enterResult1}`);
      await sleep(600);

      // Step 4: Focus the composer input
      logger.log("Step 4: Focusing composer...");
      await vscode.commands.executeCommand("composer.focusComposer");
      await sleep(300);

      // Step 5: Paste the command (Ctrl+V via ydotool)
      logger.log("Step 5: Pasting command (Ctrl+V)...");
      const pasteResult = sendPaste();
      logger.log(`Paste result: ${pasteResult}`);
      await sleep(400);

      // Step 6: Press Enter to submit
      logger.log("Step 6: Pressing Enter to submit...");
      const enterResult2 = sendEnter();
      logger.log(`Enter result: ${enterResult2}`);

      vscode.window.showInformationMessage(`🚀 Running skill: ${skill}`);
    } catch (e) {
      logger.error(`Failed to run skill: ${e}`);

      // Fallback: Copy to clipboard and show instructions
      await vscode.env.clipboard.writeText(command);
      vscode.window.showWarningMessage(
        `Could not auto-launch chat. Command copied to clipboard: ${command}. Open a new chat and paste.`
      );
    }
  }

  private async openSkillFile(skillName: string): Promise<void> {
    const skill = this.skills.find((s) => s.name === skillName);
    if (skill && skill.file) {
      const doc = await vscode.workspace.openTextDocument(skill.file);
      await vscode.window.showTextDocument(doc);
    }
  }

  private clearStaleSkills(): void {
    // Remove skills that have been running for more than 30 minutes
    const thirtyMinutes = 30 * 60 * 1000;
    this.runningSkills = this.runningSkills.filter(
      (s) => s.elapsed < thirtyMinutes || s.status !== "running"
    );
  }

  private clearSkillExecution(executionId: string): void {
    this.runningSkills = this.runningSkills.filter(
      (s) => s.executionId !== executionId
    );
  }

  /**
   * Clear stale skills from the execution file (persists the change)
   */
  private async clearStaleSkillsFromFile(): Promise<void> {
    const watcher = getSkillExecutionWatcher();
    if (watcher) {
      const cleared = await watcher.clearStaleExecutions();
      logger.log(`Cleared ${cleared} stale executions from file`);
      // Also clear from local state
      this.clearStaleSkills();
    } else {
      // Fallback to local-only clear
      this.clearStaleSkills();
    }
  }

  /**
   * Clear a specific skill execution from the file (persists the change)
   */
  private async clearSkillExecutionFromFile(executionId: string): Promise<void> {
    const watcher = getSkillExecutionWatcher();
    if (watcher) {
      const success = await watcher.clearExecution(executionId);
      logger.log(`Cleared execution ${executionId}: ${success}`);
      // Also clear from local state
      this.clearSkillExecution(executionId);
    } else {
      // Fallback to local-only clear
      this.clearSkillExecution(executionId);
    }
  }

  /**
   * Select a running skill to view its workflow inline
   */
  private async selectRunningSkill(executionId: string): Promise<void> {
    const runningSkill = this.runningSkills.find(s => s.executionId === executionId);
    if (!runningSkill) {
      logger.warn(`Skill execution not found: ${executionId}`);
      return;
    }

    // Set the execution ID we're watching BEFORE loading skill
    // This ensures execution updates are accepted
    this.watchingExecutionId = executionId;

    // Load the skill definition
    await this.loadSkill(runningSkill.skillName);

    // Switch to workflow view to show the flowchart
    this.skillView = "workflow";

    // Set the execution ID in the watcher so it sends us updates
    const watcher = getSkillExecutionWatcher();
    if (watcher) {
      watcher.selectExecution(executionId);

      // Get the current execution state immediately
      const execState = watcher.getSelectedExecution();
      if (execState) {
        this.detailedExecution = {
          executionId: execState.executionId,
          skillName: execState.skillName,
          status: execState.status,
          currentStepIndex: execState.currentStepIndex,
          totalSteps: execState.totalSteps,
          steps: [], // Will be populated by next update
          startTime: execState.startTime,
          endTime: execState.endTime,
        };
      }
    }

    logger.log(`Selected running skill: ${runningSkill.skillName} (${executionId})`);
  }

  /**
   * Capitalize first letter of a string
   */
  private capitalizeFirst(str: string): string {
    if (!str) return str;
    return str.charAt(0).toUpperCase() + str.slice(1);
  }
}
