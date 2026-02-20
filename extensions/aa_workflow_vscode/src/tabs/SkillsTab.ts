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
import { SkillsGraphData } from "../dbusClient";

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
  source: "chat" | "cron" | "slack" | "manual" | "api";
  elapsed: number;
  totalSteps?: number;
  /** Track which update source added this skill to prevent duplicates */
  addedBy?: "websocket" | "filewatcher" | "dbus";
  /** Timestamp when this skill was added (for deduplication window) */
  addedAt?: number;
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
  private skillView: "info" | "workflow" | "yaml" | "mindmap" = "info";
  private workflowViewMode: "horizontal" | "vertical" = "horizontal";
  private wsClient: SkillWebSocketClient | null = null;
  private wsDisposables: vscode.Disposable[] = [];
  private _lastRunningSkillsStructuralFP: string = "";  // Structural changes (add/remove/status)
  private _lastRunningSkillsProgressFP: string = "";   // Progress changes (step updates)

  // Mind map data
  private mindMapData: SkillsGraphData | null = null;
  private lastMindMapLoad: number = 0;
  private static readonly MINDMAP_MIN_INTERVAL_MS = 60000; // 60 seconds

  // Throttling: skills list rarely changes, don't refresh more than once per 30 seconds
  private lastSkillsListLoad: number = 0;
  private static readonly SKILLS_LIST_MIN_INTERVAL_MS = 30000; // 30 seconds

  // Flag to force next render even if mind map is active (for user-initiated view changes)
  private forceNextRender: boolean = false;

  /**
   * Check if the mind map view is currently active.
   */
  public isMindMapActive(): boolean {
    return this.skillView === "mindmap";
  }

  /**
   * Check and consume the force-render flag.
   * Used by the render callback in commandCenter to allow renders that would
   * otherwise be skipped (e.g., the initial render when switching TO mind map view).
   */
  public consumeForceRender(): boolean {
    if (this.forceNextRender) {
      this.forceNextRender = false;
      return true;
    }
    return false;
  }

  /**
   * Conditionally trigger re-render, skipping if mind map or running workflow is active.
   * - Mind map: D3 force simulation would restart
   * - Running workflow: step changes use incremental CSS updates instead
   *
   * Set forceNextRender = true BEFORE calling this to force a render for structural changes
   * (skill started/completed) even during an active workflow or mind map.
   */
  private notifyNeedsRenderIfNotMindMap(): void {
    // Check the force flag but don't consume it here - consumeForceRender()
    // handles consumption so the render callback in commandCenter also sees it.
    const forced = this.forceNextRender;

    if (!forced && this.isMindMapActive()) {
      logger.log("Skipping re-render - mind map is active");
      return;
    }

    // Skip full re-render if viewing a running workflow (uses incremental CSS updates)
    const inWorkflowMode = this.skillView === "workflow" &&
                           this.detailedExecution?.status === "running";
    if (!forced && inWorkflowMode) {
      logger.log("Skipping full re-render - workflow in incremental CSS update mode");
      return;
    }

    this.notifyNeedsRender();
  }

  /**
   * Build a STRUCTURAL fingerprint of running skills.
   * Only changes when skills are added, removed, or change status.
   * Does NOT change on step progress updates - those use incremental CSS updates.
   */
  private _buildRunningSkillsStructuralFingerprint(): string {
    return this.runningSkills
      .map(s => `${s.executionId}:${s.status}`)
      .sort()
      .join("|");
  }

  /**
   * Build a PROGRESS fingerprint of running skills.
   * Changes when step progress updates (used for incremental CSS updates).
   */
  private _buildRunningSkillsProgressFingerprint(): string {
    return this.runningSkills
      .map(s => `${s.executionId}:${s.status}:${s.progress}:${s.currentStep}`)
      .sort()
      .join("|");
  }

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
      // Use notifyNeedsRenderIfNotMindMap to avoid restarting D3 simulation.
      //
      // Note: onSkillUpdate and onStepUpdate fire for the SAME step transition.
      // To avoid double-renders, we only trigger render from onStepUpdate
      // (which has more detail). onSkillUpdate just updates internal state.
      this.wsDisposables.push(
        this.wsClient.onSkillStarted((skill) => {
          logger.log(`WebSocket: Skill started - ${skill.skillName}`);
          this.addOrUpdateRunningSkill(skill);
          this.forceNextRender = true; // Structural change - force full re-render
          this.notifyNeedsRenderIfNotMindMap();
        })
      );

      this.wsDisposables.push(
        this.wsClient.onSkillUpdate((skill) => {
          logger.log(`WebSocket: Skill update - ${skill.skillName} step ${skill.currentStep}/${skill.totalSteps}`);
          this.addOrUpdateRunningSkill(skill);
          // Don't render here - onStepUpdate fires for the same event with more detail
        })
      );

      this.wsDisposables.push(
        this.wsClient.onSkillCompleted(({ skillId, success }) => {
          logger.log(`WebSocket: Skill completed - ${skillId} success=${success}`);
          this.markSkillCompleted(skillId, success);
          this.forceNextRender = true; // Structural change - force full re-render
          this.notifyNeedsRenderIfNotMindMap();
        })
      );

      this.wsDisposables.push(
        this.wsClient.onStepUpdate(({ skillId, step }) => {
          logger.log(`WebSocket: Step update - ${skillId} step ${step.index}: ${step.status}`);
          this.updateSkillStep(skillId, step);
          // Try incremental CSS update first (no flicker), fall back to full re-render
          if (this.selectedSkill && this.skillView === "workflow" && this.sendIncrementalStepUpdate()) {
            logger.log("WebSocket: Step update sent as incremental CSS update");
          } else {
            this.notifyNeedsRenderIfNotMindMap();
          }
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

  /**
   * Add or update a running skill from WebSocket events.
   * WebSocket is the primary/authoritative source for real-time updates.
   */
  private addOrUpdateRunningSkill(skill: SkillState): void {
    const now = Date.now();

    // Check for existing by executionId (most reliable)
    const existingById = this.runningSkills.find(s => s.executionId === skill.skillId);

    // Check for existing by skillName that's running (fallback for ID mismatch)
    const existingByName = this.runningSkills.find(s =>
      s.skillName === skill.skillName && s.status === "running"
    );

    const existing = existingById || existingByName;

    const progress = skill.totalSteps > 0
      ? Math.round((skill.currentStep / skill.totalSteps) * 100)
      : 0;

    const elapsed = Date.now() - skill.startedAt.getTime();

    if (existing) {
      // Update existing entry
      // Always update executionId to WebSocket's ID (authoritative)
      existing.executionId = skill.skillId;
      existing.status = skill.status === "running" ? "running" : skill.status === "completed" ? "completed" : "failed";
      existing.progress = progress;
      existing.currentStep = skill.currentStepName || `Step ${skill.currentStep}`;
      existing.elapsed = elapsed;
      existing.totalSteps = skill.totalSteps;
      existing.addedBy = "websocket"; // WebSocket takes ownership
      // Update source if we now have a real source from WebSocket
      if (skill.source && skill.source !== "manual") {
        existing.source = skill.source;
      }
    } else {
      // Add new entry - WebSocket is authoritative
      this.runningSkills.push({
        executionId: skill.skillId,
        skillName: skill.skillName,
        status: skill.status === "running" ? "running" : skill.status === "completed" ? "completed" : "failed",
        progress,
        currentStep: skill.currentStepName || `Step ${skill.currentStep}`,
        startedAt: skill.startedAt.toISOString(),
        source: skill.source || "chat",
        elapsed,
        totalSteps: skill.totalSteps,
        addedBy: "websocket",
        addedAt: now,
      });
      logger.log(`Added running skill from WebSocket: ${skill.skillName} (${skill.skillId})`);
    }

    // Clean up any duplicates that might have snuck in from race conditions
    this.deduplicateRunningSkills();

    // Auto-set watchingExecutionId if user is viewing this skill's workflow
    // This ensures progress circles update when a skill starts running while viewing it
    logger.log(`addOrUpdateRunningSkill: checking auto-watch - watchingExecutionId=${this.watchingExecutionId}, selectedSkill=${this.selectedSkill}, skill.skillName=${skill.skillName}, skillView=${this.skillView}, status=${skill.status}`);
    if (!this.watchingExecutionId &&
        this.selectedSkill === skill.skillName &&
        this.skillView === "workflow" &&
        skill.status === "running") {
      this.watchingExecutionId = skill.skillId;
      // Initialize detailedExecution for real-time updates
      this.detailedExecution = {
        executionId: skill.skillId,
        skillName: skill.skillName,
        status: "running",
        currentStepIndex: skill.currentStep,
        totalSteps: skill.totalSteps,
        steps: [],
        startTime: skill.startedAt.toISOString(),
      };
      logger.log(`Auto-set watchingExecutionId for ${skill.skillName} (${skill.skillId}) - user viewing workflow`);
    }

    // Update detailedExecution if we're watching THIS skill
    // This keeps the workflow view in sync with WebSocket updates
    if (this.watchingExecutionId === skill.skillId && this.detailedExecution) {
      this.detailedExecution.currentStepIndex = skill.currentStep;
      this.detailedExecution.totalSteps = skill.totalSteps;
      this.detailedExecution.status = skill.status;
      logger.log(`addOrUpdateRunningSkill: Updated detailedExecution for watched skill ${skill.skillName} - step ${skill.currentStep}/${skill.totalSteps}`);
    }
  }

  /**
   * Remove duplicate running skills, keeping the one with the most authoritative source.
   * Priority: websocket > filewatcher > dbus
   */
  private deduplicateRunningSkills(): void {
    const seen = new Map<string, RunningSkill>();
    const toRemove: string[] = [];

    for (const skill of this.runningSkills) {
      if (skill.status !== "running") continue;

      const key = skill.skillName;
      const existing = seen.get(key);

      if (existing) {
        // Duplicate found - decide which to keep
        const existingPriority = this.getSourcePriority(existing.addedBy);
        const newPriority = this.getSourcePriority(skill.addedBy);

        if (newPriority > existingPriority) {
          // New one is more authoritative, remove the old one
          toRemove.push(existing.executionId);
          seen.set(key, skill);
          logger.warn(`Dedup: Keeping ${skill.skillName} from ${skill.addedBy}, removing from ${existing.addedBy}`);
        } else {
          // Old one is more authoritative, remove the new one
          toRemove.push(skill.executionId);
          logger.warn(`Dedup: Keeping ${skill.skillName} from ${existing.addedBy}, removing from ${skill.addedBy}`);
        }
      } else {
        seen.set(key, skill);
      }
    }

    if (toRemove.length > 0) {
      this.runningSkills = this.runningSkills.filter(s => !toRemove.includes(s.executionId));
      logger.log(`Removed ${toRemove.length} duplicate running skills`);
    }
  }

  /**
   * Get priority for deduplication. Higher = more authoritative.
   */
  private getSourcePriority(source?: string): number {
    switch (source) {
      case "websocket": return 3;
      case "filewatcher": return 2;
      case "dbus": return 1;
      default: return 0;
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
        this.forceNextRender = true; // Structural change
        this.notifyNeedsRenderIfNotMindMap();
      }, 5000);
    }
  }

  private updateSkillStep(skillId: string, step: any): void {
    logger.log(`updateSkillStep: skillId=${skillId}, step=${JSON.stringify(step)}`);
    const skill = this.runningSkills.find(s => s.executionId === skillId);
    if (skill) {
      skill.currentStep = step?.name || `Step ${step?.index}`;
    }

    // Auto-set watchingExecutionId if user is viewing this skill's workflow but hasn't explicitly selected it
    // This handles the race condition where step updates arrive before addOrUpdateRunningSkill
    logger.log(`updateSkillStep: checking auto-watch - watchingExecutionId=${this.watchingExecutionId}, skill=${skill?.skillName}, selectedSkill=${this.selectedSkill}, skillView=${this.skillView}`);
    if (!this.watchingExecutionId && skill &&
        this.selectedSkill === skill.skillName &&
        this.skillView === "workflow") {
      this.watchingExecutionId = skillId;
      this.detailedExecution = {
        executionId: skillId,
        skillName: skill.skillName,
        status: "running",
        currentStepIndex: step.index || 0,
        totalSteps: skill.totalSteps || 0,
        steps: [],
        startTime: skill.startedAt,
      };
      logger.log(`Auto-set watchingExecutionId in updateSkillStep for ${skill.skillName} (${skillId})`);
    }

    // Also update detailedExecution.steps if we're watching this execution
    // This ensures the workflow circles update in real-time via WebSocket
    if (this.watchingExecutionId === skillId && this.detailedExecution) {
      const stepIndex = step.index;
      if (stepIndex !== undefined && stepIndex >= 0) {
        // Ensure steps array is large enough
        if (!this.detailedExecution.steps) {
          this.detailedExecution.steps = [];
        }
        // Expand array if needed
        while (this.detailedExecution.steps.length <= stepIndex) {
          this.detailedExecution.steps.push({ name: `Step ${this.detailedExecution.steps.length + 1}`, status: "pending" });
        }
        // Update the step status
        // Map "completed" from WebSocket to "success" for our ExecutionStep interface
        const mappedStatus = step.status === "completed" ? "success" : step.status;
        this.detailedExecution.steps[stepIndex] = {
          ...this.detailedExecution.steps[stepIndex],
          status: mappedStatus as "pending" | "running" | "success" | "failed" | "skipped",
          name: step.name || this.detailedExecution.steps[stepIndex].name,
          duration: step.endTime && step.startTime ? new Date(step.endTime).getTime() - new Date(step.startTime).getTime() : undefined,
          error: step.error,
        };
        // Update current step index
        if (step.status === "running") {
          this.detailedExecution.currentStepIndex = stepIndex;
        }
        logger.log(`WebSocket: Updated detailedExecution step ${stepIndex} to ${step.status}`);
      }
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

  protected computeDataFingerprint(): string {
    const parts = [
      this.skills.length,
      this._buildRunningSkillsStructuralFingerprint(),
      this.selectedSkill ?? "",
      this.skillView,
      this.workflowViewMode,
      this.detailedExecution?.status ?? "",
      this.mindMapData ? 1 : 0,
    ];
    return parts.join("|");
  }

  async loadData(): Promise<void> {
    const now = Date.now();
    const timeSinceLastLoad = now - this.lastSkillsListLoad;

    // Throttle skills list loading - it rarely changes
    const shouldLoadSkillsList = timeSinceLastLoad >= SkillsTab.SKILLS_LIST_MIN_INTERVAL_MS || this.skills.length === 0;

    if (shouldLoadSkillsList) {
      logger.log("loadData() starting - loading skills list...");
      try {
        // Load skills list via D-Bus
        const skillsResult = await dbus.config_getSkillsList();
        if (skillsResult.success && skillsResult.data) {
          const data = skillsResult.data as any;
          this.skills = data.skills || [];
          this.categorizeSkills();
          this.lastSkillsListLoad = now;
          logger.log(`Loaded ${this.skills.length} skills`);
        } else if (skillsResult.error) {
          this.lastError = `Skills list failed: ${skillsResult.error}`;
          logger.warn(this.lastError);
        }
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : String(error);
        logger.error("Error loading skills list", error);
      }
    } else {
      logger.log(`loadData() skipping skills list - last load ${Math.round(timeSinceLastLoad / 1000)}s ago (min interval: ${SkillsTab.SKILLS_LIST_MIN_INTERVAL_MS / 1000}s)`);
    }

    // Always load current execution status (this is lightweight and changes frequently)
    try {
      const execResult = await dbus.stats_getSkillExecution();
      if (execResult.success && execResult.data) {
        const data = execResult.data as any;
        this.currentExecution = data.execution || null;
        this.updateRunningSkills();
      }
    } catch (error) {
      logger.warn(`Skill execution check failed: ${error}`);
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

  /**
   * Update running skills from D-Bus polling.
   * D-Bus is the lowest priority source - only add if not already tracked.
   */
  private updateRunningSkills(): void {
    if (this.currentExecution && this.currentExecution.status === "running") {
      const now = Date.now();
      const skillName = this.currentExecution.skill_name;

      // Check if already tracked by any source
      const existing = this.runningSkills.find(
        (s) => s.skillName === skillName && s.status === "running"
      );

      if (existing) {
        // Update progress/step but DON'T change ownership or executionId
        existing.progress = this.currentExecution.progress || existing.progress;
        existing.currentStep = this.currentExecution.current_step || existing.currentStep;
      } else {
        // Only add if not recently added by another source (within 2 seconds)
        const recentlyAdded = this.runningSkills.some(
          rs => rs.skillName === skillName &&
                rs.addedAt &&
                (now - rs.addedAt) < 2000
        );

        if (!recentlyAdded) {
          this.runningSkills.push({
            executionId: (this.currentExecution as any).execution_id || `exec-${Date.now()}`,
            skillName: skillName,
            status: "running",
            progress: this.currentExecution.progress || 0,
            currentStep: this.currentExecution.current_step || "",
            startedAt: this.currentExecution.started_at || new Date().toISOString(),
            source: (this.currentExecution as any).source || "chat",
            elapsed: 0,
            addedBy: "dbus",
            addedAt: now,
          });
          logger.log(`Added running skill from D-Bus: ${skillName}`);
        } else {
          logger.log(`Skipping duplicate from D-Bus (recently added): ${skillName}`);
        }
      }

      // Run deduplication
      this.deduplicateRunningSkills();
    }
  }

  getContent(): string {
    const runningCount = this.runningSkills.filter(
      (s) => s.status === "running"
    ).length;

    // Mind Map view takes over the entire content area
    if (this.skillView === "mindmap") {
      return `
        <!-- Running Skills Panel -->
        ${runningCount > 0 ? this.getRunningSkillsHtml() : ""}

        <!-- Mind Map Full View -->
        <div class="mindmap-container">
          <div class="mindmap-header-compact">
            <div class="mindmap-header-top">
              <div class="flex-row mindmap-header-left">
                <span class="mindmap-icon">🧠</span>
                <div class="mindmap-title-block">
                  <span class="mindmap-title-text">Skills Mind Map</span>
                  <span class="mindmap-stats-inline" id="mindmapStatsInline"></span>
                </div>
              </div>
              <div class="view-toggle">
                <button class="toggle-btn" data-view="info">List View</button>
                <button class="toggle-btn active" data-view="mindmap">Mind Map</button>
              </div>
            </div>
            <div class="mindmap-header-controls">
              <select class="mindmap-select" id="personaSelect">
                <option value="none">All Personas</option>
              </select>
              <select class="mindmap-select" id="categorySelect">
                <option value="all">All Categories</option>
              </select>
              <div class="mindmap-toggles">
                <label class="toggle-label"><input type="checkbox" id="toggleTools" checked /> Tools</label>
                <label class="toggle-label"><input type="checkbox" id="toggleIntents" checked /> Intents</label>
                <label class="toggle-label"><input type="checkbox" id="toggleLabels" /> Labels</label>
                <label class="toggle-label"><input type="checkbox" id="toggleSticky" /> Sticky</label>
              </div>
              <button class="btn btn-xs mindmap-physics-toggle" id="physicsToggle" title="Physics Controls">⚙️</button>
            </div>
          </div>
          <div class="mindmap-content" id="mindmapContent">
            ${this.getMindMapHtml()}
          </div>
        </div>
      `;
    }

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
          <div class="flex-between skills-main-header">
            <div class="skills-main-title">
              ${this.selectedSkill ? this.selectedSkill : "Select a skill"}
            </div>
            <div class="view-toggle">
              <button class="toggle-btn ${this.skillView === "info" ? "active" : ""}" data-view="info">Info</button>
              <button class="toggle-btn ${this.skillView === "workflow" ? "active" : ""}" data-view="workflow">Workflow</button>
              <button class="toggle-btn ${this.skillView === "yaml" ? "active" : ""}" data-view="yaml">YAML</button>
              <button class="toggle-btn" data-view="mindmap" title="View all skills as a mind map">🧠</button>
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
        <div class="flex-between running-skills-header">
          <div class="flex-row running-skills-title">
            <span class="running-indicator"></span>
            Running Skills (${running.length})
          </div>
          <div class="actions-row running-skills-actions">
            <button class="btn btn-xs btn-danger" data-action="clearStaleSkills">Clear Stale</button>
          </div>
        </div>
        <div class="flex-col running-skills-list">
    `;

    running.forEach((skill) => {
      const elapsed = this.formatDuration(skill.elapsed);
      html += `
        <div class="item-row running-skill-item" data-execution-id="${skill.executionId}">
          <div class="flex-col running-skill-progress">
            <div class="running-skill-progress-bar">
              <div class="running-skill-progress-fill" style="width: ${skill.progress}%"></div>
            </div>
            <div class="running-skill-progress-text">${skill.progress}%</div>
          </div>
          <div class="label-sm text-meta running-skill-info">
            <div class="label-sm text-meta running-skill-name">${this.escapeHtml(skill.skillName)}</div>
            <div class="flex-row running-skill-source">
              <span class="${skill.source === 'slack' ? 'dot ' : ''}source-badge ${skill.source}">${skill.source}</span>
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
      <div class="flex-col skill-info-view">
        <div class="card skill-info-card">
          <div class="skill-info-title">${this.escapeHtml(skill.name)} ${skill.version ? `<span class="skill-version">v${skill.version}</span>` : ""}</div>
          <div class="skill-info-desc">${this.escapeHtml(skill.description || "No description")}</div>
        </div>

        ${skill.inputs && skill.inputs.length > 0 ? `
          <div class="skill-inputs-section">
            <div class="flex-row skill-inputs-title">📥 Inputs</div>
            ${skill.inputs.map((input) => `
              <div class="item-row skill-input-item">
                <span class="skill-input-name">${input.name}${input.required ? " *" : ""}</span>
                <span class="font-semibold skill-input-type">${input.type || "any"}</span>
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
              <span class="label-sm stat-label">Steps</span>
            </div>
            <div class="skill-stat">
              <span class="stat-value">${skill.inputs?.length || 0}</span>
              <span class="label-sm stat-label">Inputs</span>
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
        <div class="flex-col skill-workflow-view">
          <div class="flex-between workflow-header">
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
    logger.log(`getSkillWorkflowView: detailedExecution?.skillName=${this.detailedExecution?.skillName}, skill.name=${skill.name}, watchingExecutionId=${this.watchingExecutionId}`);
    const isExecuting = this.detailedExecution?.skillName === skill.name;
    const execStatus = isExecuting ? this.detailedExecution!.status : "ready";
    const execStep = isExecuting ? `${this.detailedExecution!.currentStepIndex + 1}/${this.detailedExecution!.totalSteps}` : "";
    const statusText = isExecuting ? `Step ${execStep} • ${this.capitalizeFirst(execStatus)}` : "Ready";
    const statusClass = isExecuting && execStatus === "running" ? "status-running" : "";

    return `
      <div class="flex-col skill-workflow-view">
        <div class="flex-between workflow-header">
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
      logger.log(`getExecutionStepStatus(${index}): No detailedExecution or steps`);
      return null;
    }
    if (this.detailedExecution.skillName !== this.selectedSkill) {
      logger.log(`getExecutionStepStatus(${index}): skillName mismatch - detailedExecution.skillName='${this.detailedExecution.skillName}' vs selectedSkill='${this.selectedSkill}'`);
      return null;
    }
    const step = this.detailedExecution.steps[index] || null;
    if (step) {
      logger.log(`getExecutionStepStatus(${index}): Found step with status='${step.status}'`);
    }
    return step;
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

  /**
   * Send incremental step status updates to the webview without a full re-render.
   * This updates CSS classes and icons on individual step nodes in-place,
   * avoiding the expensive innerHTML replacement that causes flickering.
   *
   * Returns true if the incremental update was sent, false if a full re-render
   * is needed (e.g., webview context not available).
   */
  private sendIncrementalStepUpdate(): boolean {
    if (!this.detailedExecution || !this.selectedSkillData?.steps) {
      return false;
    }

    const steps = this.selectedSkillData.steps;
    const stepUpdates: Array<{
      index: number;
      status: string;
      icon: string;
      tooltip?: string;
      lifecycleHtml?: string;
    }> = [];

    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const execStep = this.getExecutionStepStatus(i);
      const status = execStep?.status || "pending";
      const isSkillCall = (step.tool || "") === "skill_run";
      const icon = this.getStepIcon(status, i + 1, isSkillCall);

      // Build tooltip
      const tooltipParts = [step.description || step.name || `Step ${i + 1}`];
      if (isSkillCall && step.args?.skill_name) {
        tooltipParts.push(`Calls skill: ${step.args.skill_name}`);
      } else if (step.tool) {
        tooltipParts.push(`Tool: ${step.tool}`);
      }
      if (execStep?.duration) {
        tooltipParts.push(`Duration: ${this.formatDuration(execStep.duration)}`);
      }
      if (execStep?.error) {
        tooltipParts.push(`Error: ${execStep.error}`);
      }

      // Build lifecycle indicators
      const lifecycleIndicators = this.getLifecycleIndicators(step, execStep);

      stepUpdates.push({
        index: i,
        status,
        icon,
        tooltip: tooltipParts.join("\n"),
        lifecycleHtml: lifecycleIndicators.length > 0 ? lifecycleIndicators.join("") : "",
      });
    }

    // Build meta status
    const isExecuting = this.detailedExecution.skillName === this.selectedSkill;
    const execStatus = isExecuting ? this.detailedExecution.status : "ready";
    const execStep = isExecuting
      ? `${this.detailedExecution.currentStepIndex + 1}/${this.detailedExecution.totalSteps}`
      : "";
    const statusText = isExecuting ? `Step ${execStep} • ${this.capitalizeFirst(execStatus)}` : "Ready";
    const statusClass = isExecuting && execStatus === "running" ? "status-running" : "";

    return this.postMessageToWebview({
      type: "stepStatusUpdate",
      steps: stepUpdates,
      metaHtml: `Steps: ${steps.length} • Status: ${statusText}`,
      metaClass: statusClass,
    });
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
    if (step.compute) tags.push(`<span class="dot step-tag compute">🐍 compute</span>`);
    if (step.condition) tags.push(`<span class="dot step-tag condition">❓ conditional</span>`);
    if (step.on_error === "continue" || step.on_error === "retry") {
      tags.push(`<span class="step-tag can-retry">↩️ can retry</span>`);
    }

    // Lifecycle tags
    const memoryReadTools = ["memory_read", "memory_query", "check_known_issues"];
    const memoryWriteTools = ["memory_write", "memory_update", "memory_append", "memory_session_log"];
    const searchTools = ["knowledge_query", "knowledge_search", "semantic_search", "code_search"];

    if (memoryReadTools.some(t => tool.includes(t))) {
      tags.push(`<span class="dot step-tag memory-read">📖 memory read</span>`);
    }
    if (memoryWriteTools.some(t => tool.includes(t))) {
      tags.push(`<span class="dot step-tag memory-write">💾 memory write</span>`);
    }
    if (searchTools.some(t => tool.includes(t))) {
      tags.push(`<span class="dot step-tag semantic-search">🔍 search</span>`);
    }

    const skillCallClass = isSkillCall ? "skill-call" : "";

    return `
      <div class="step-node pending ${skillCallClass}">
        ${!isLast ? '<div class="step-connector"></div>' : ''}
        <div class="step-icon">${isSkillCall ? "⚡" : stepNumber}</div>
        <div class="step-content">
          <div class="flex-between step-header">
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

    // Use raw YAML content if available (from D-Bus), otherwise format as YAML-like
    let yamlContent: string;
    if (skillData._raw_yaml) {
      yamlContent = skillData._raw_yaml;
    } else {
      // Fallback: format as YAML-like (not perfect but better than JSON)
      yamlContent = this.formatAsYaml(skillData);
    }

    return `
      <div class="skill-yaml-view">
        <div class="flex-between yaml-header">
          <span class="yaml-title">${this.escapeHtml(skill.name)}.yaml</span>
          <button class="btn btn-xs" data-action="openSkillFile" data-skill="${skill.name}">📄 Open in Editor</button>
        </div>
        <pre class="yaml-content"><code>${this.escapeHtml(yamlContent)}</code></pre>
      </div>
    `;
  }

  /**
   * Generate the Mind Map visualization HTML with embedded D3.js
   */
  private getMindMapHtml(): string {
    logger.log(`getMindMapHtml: mindMapData=${!!this.mindMapData}, nodes=${this.mindMapData?.nodes?.length || 0}`);
    if (!this.mindMapData) {
      logger.warn("getMindMapHtml: NO DATA - showing loading state");
      return `
        <div class="mindmap-loading">
          <div class="loading-spinner"></div>
          <p>Loading mind map data...</p>
          <p class="mindmap-loading-hint">Make sure the config daemon is running (aa-daemon start config)</p>
        </div>
      `;
    }

    const stats = this.mindMapData.stats || { skill_count: 0, tool_count: 0, intent_count: 0, link_count: 0, persona_count: 0, categories: {} };
    logger.log(`getMindMapHtml: HAS DATA - ${stats.skill_count} skills, ${stats.link_count} links, rendering SVG+JSON`);
    const graphDataJson = JSON.stringify(this.mindMapData);

    // Generate persona options for the select
    const personaOptions = Object.keys(this.mindMapData.personas || {}).map(p =>
      `<option value="${p}">${this.capitalizeFirst(p)}</option>`
    ).join('');

    // Generate category options for the select
    const categoryOptions = Object.keys(stats.categories || {}).map(c =>
      `<option value="${c}">${this.capitalizeFirst(c)}</option>`
    ).join('');

    return `
      <div class="mindmap-wrapper">
        <!-- Physics Controls Panel (collapsible) -->
        <div class="mindmap-physics-panel" id="physicsPanel" style="display: none;">
          <div class="physics-row">
            <div class="physics-control">
              <label for="chargeSlider">Repulsion <span class="physics-value" id="chargeValue">-120</span></label>
              <input type="range" id="chargeSlider" min="-400" max="0" step="10" value="-120" />
            </div>
            <div class="physics-control">
              <label for="linkDistSlider">Link Distance <span class="physics-value" id="linkDistValue">70</span></label>
              <input type="range" id="linkDistSlider" min="20" max="250" step="5" value="70" />
            </div>
            <div class="physics-control">
              <label for="collisionSlider">Padding <span class="physics-value" id="collisionValue">5</span></label>
              <input type="range" id="collisionSlider" min="0" max="30" step="1" value="5" />
            </div>
          </div>
          <div class="physics-row">
            <div class="physics-control">
              <label for="centerSlider">Centering <span class="physics-value" id="centerValue">0.05</span></label>
              <input type="range" id="centerSlider" min="0" max="100" step="1" value="5" />
            </div>
            <div class="physics-control">
              <label for="decaySlider">Cooling <span class="physics-value" id="decayValue">0.023</span></label>
              <input type="range" id="decaySlider" min="1" max="100" step="1" value="23" />
            </div>
            <div class="physics-control">
              <label for="velocitySlider">Friction <span class="physics-value" id="velocityValue">0.40</span></label>
              <input type="range" id="velocitySlider" min="0" max="100" step="1" value="40" />
            </div>
          </div>
          <div class="physics-row physics-actions">
            <button class="btn btn-xs" id="physicsReset" title="Reset to defaults">Reset</button>
            <button class="btn btn-xs" id="physicsReheat" title="Restart simulation">Reheat</button>
            <button class="btn btn-xs" id="physicsPause" title="Pause/resume simulation">Pause</button>
            <button class="btn btn-xs" id="physicsUnstick" title="Release all pinned nodes">Unstick All</button>
          </div>
        </div>

        <!-- Graph Container -->
        <div class="mindmap-graph" id="mindmapGraph">
          <svg id="mindmapSvg" class="svg-full">
            <defs>
              <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                <feMerge>
                  <feMergeNode in="coloredBlur"/>
                  <feMergeNode in="SourceGraphic"/>
                </feMerge>
              </filter>
            </defs>
          </svg>
        </div>

        <!-- Tooltip -->
        <div class="mindmap-tooltip" id="mindmapTooltip"></div>

        <!-- Legend (compact, bottom-left) -->
        <div class="mindmap-legend-compact">
          <span class="legend-item-compact"><span class="dot legend-dot legend-dot-root"></span>Skill</span>
          <span class="legend-item-compact"><span class="dot legend-dot legend-dot-tool"></span>Tool</span>
          <span class="legend-item-compact"><span class="dot legend-dot legend-dot-intent"></span>Intent</span>
        </div>
      </div>

      <!-- Data for populating header controls -->
      <script type="application/json" id="mindmapPersonaOptions">${personaOptions}</script>
      <script type="application/json" id="mindmapCategoryOptions">${categoryOptions}</script>
      <script type="application/json" id="mindmapStatsData">${JSON.stringify(stats)}</script>

      <!-- Embed graph data for JavaScript -->
      <script id="mindmapDataScript" type="application/json">${graphDataJson}</script>
    `;
  }

  /**
   * Format data as YAML-like string (simple formatter for display)
   */
  private formatAsYaml(data: any, indent: number = 0): string {
    const spaces = "  ".repeat(indent);
    const lines: string[] = [];

    if (data === null || data === undefined) {
      return "null";
    }

    if (typeof data !== "object") {
      return String(data);
    }

    if (Array.isArray(data)) {
      for (const item of data) {
        if (typeof item === "object" && item !== null) {
          lines.push(`${spaces}-`);
          const subYaml = this.formatAsYaml(item, indent + 1);
          lines.push(subYaml);
        } else {
          lines.push(`${spaces}- ${item}`);
        }
      }
      return lines.join("\n");
    }

    // Object
    for (const [key, value] of Object.entries(data)) {
      // Skip internal fields
      if (key.startsWith("_")) continue;

      if (value === null || value === undefined) {
        lines.push(`${spaces}${key}: null`);
      } else if (typeof value === "object") {
        if (Array.isArray(value) && value.length === 0) {
          lines.push(`${spaces}${key}: []`);
        } else if (typeof value === "object" && Object.keys(value).length === 0) {
          lines.push(`${spaces}${key}: {}`);
        } else {
          lines.push(`${spaces}${key}:`);
          lines.push(this.formatAsYaml(value, indent + 1));
        }
      } else if (typeof value === "string" && (value.includes("\n") || value.includes(":"))) {
        // Multi-line or special strings
        lines.push(`${spaces}${key}: |`);
        for (const line of value.split("\n")) {
          lines.push(`${spaces}  ${line}`);
        }
      } else {
        lines.push(`${spaces}${key}: ${value}`);
      }
    }

    return lines.join("\n");
  }

  getStyles(): string {
    // Mind map styles are now in unified.css
    return "";
  }

  getScript(): string {
    // Use centralized event delegation system - handlers survive content updates
    return `
      (function() {
        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('skills', function(action, element, e) {
          const skillName = element.dataset.skill;
          const executionId = element.dataset.executionId;

          switch(action) {
            case 'runSkill':
              if (skillName) {
                vscode.postMessage({ command: 'runSkill', skillName });
              }
              break;
            case 'openSkillFile':
              if (skillName) {
                vscode.postMessage({ command: 'openSkillFile', skillName });
              }
              break;
            case 'clearStaleSkills':
              vscode.postMessage({ command: 'clearStaleSkills' });
              break;
            case 'clearSkillExecution':
              if (executionId) {
                vscode.postMessage({ command: 'clearSkillExecution', executionId });
              }
              break;
          }
        });

        // Additional click handling for non-data-action elements
        const skillsContainer = document.getElementById('skills');
        if (skillsContainer && !skillsContainer.dataset.extraClickInit) {
          skillsContainer.dataset.extraClickInit = 'true';

          skillsContainer.addEventListener('click', function(e) {
            const target = e.target;
            // Skip if already handled by data-action
            if (target.closest('[data-action]')) return;

            const skillItem = target.closest('.skill-item');
            const viewToggle = target.closest('.toggle-btn[data-view]');
            const workflowViewBtn = target.closest('.toggle-btn[data-workflow-view]');
            const skillCallBadge = target.closest('.skill-call-badge');
            const runningSkillItem = target.closest('.running-skill-item');
            const personaBtn = target.closest('.persona-btn');
            const categoryBtn = target.closest('.category-btn');

            // Skill view toggle (Info/Workflow/YAML/MindMap)
            if (viewToggle && viewToggle.dataset.view) {
              vscode.postMessage({ command: 'setSkillView', view: viewToggle.dataset.view });
              return;
            }

            // Workflow view mode toggle (Horizontal/Vertical)
            if (workflowViewBtn && workflowViewBtn.dataset.workflowView) {
              vscode.postMessage({ command: 'setWorkflowViewMode', mode: workflowViewBtn.dataset.workflowView });
              return;
            }

            // Persona button clicks (mind map filtering)
            if (personaBtn && personaBtn.dataset.persona !== undefined) {
              vscode.postMessage({ command: 'setMindMapPersona', persona: personaBtn.dataset.persona });
              return;
            }

            // Category button clicks (mind map filtering)
            if (categoryBtn && categoryBtn.dataset.category !== undefined) {
              vscode.postMessage({ command: 'setMindMapCategory', category: categoryBtn.dataset.category });
              return;
            }

            // Skill call badge clicks (navigate to called skill)
            if (skillCallBadge && skillCallBadge.dataset.skill) {
              vscode.postMessage({ command: 'loadSkill', skillName: skillCallBadge.dataset.skill });
              return;
            }

            // Running skill item clicks (open flowchart) - but not if clicking clear button
            if (runningSkillItem && !target.closest('.clear-skill-btn')) {
              const executionId = runningSkillItem.dataset.executionId;
              if (executionId) {
                vscode.postMessage({ command: 'openRunningSkillFlowchart', executionId });
              }
              return;
            }

            // Skill item clicks (for selection)
            if (skillItem && skillItem.dataset.skill) {
              vscode.postMessage({ command: 'loadSkill', skillName: skillItem.dataset.skill });
              return;
            }
          });

          // Input delegation for search (client-side filtering)
          skillsContainer.addEventListener('input', function(e) {
            if (e.target.id === 'skillSearch') {
              const query = e.target.value.toLowerCase();
              skillsContainer.querySelectorAll('.skill-item').forEach(item => {
                const name = item.querySelector('.skill-item-name')?.textContent?.toLowerCase() || '';
                const desc = item.querySelector('.skill-item-desc')?.textContent?.toLowerCase() || '';
                const skillName = (item.dataset.skill || '').toLowerCase();
                item.style.display = (name.includes(query) || desc.includes(query) || skillName.includes(query)) ? '' : 'none';
              });
            }
          });
        }

        // Initialize mind map if present (delay to ensure DOM is ready)
        setTimeout(function() {
          if (typeof initMindMap === 'function') {
            initMindMap();
          }
        }, 100);
      })();

      // Mind Map D3.js Initialization
      var mindMapState = {
        graphData: null,
        simulation: null,
        selectedPersona: 'none',
        selectedCategory: 'all',
        showTools: true,
        showIntents: true,
        showLabels: false,
        // Physics controls
        sticky: false,
        chargeStrength: -120,
        linkDistance: 70,
        collisionRadius: 5,
        centerStrength: 0.05,
        alphaDecay: 0.0228,
        velocityDecay: 0.4
      };

      function initMindMap() {
        const dataScript = document.getElementById('mindmapDataScript');
        const svg = document.getElementById('mindmapSvg');

        // Not on mind map view
        if (!dataScript || !svg) {
          console.log('[MindMap] Elements not found - not on mind map view');
          return;
        }

        try {
          const dataText = dataScript.textContent || dataScript.innerText;
          if (!dataText || dataText.trim() === '') {
            console.warn('[MindMap] Data script is empty');
            return;
          }

          mindMapState.graphData = JSON.parse(dataText);
          if (!mindMapState.graphData || !mindMapState.graphData.nodes) {
            console.warn('[MindMap] Data has no nodes');
            return;
          }

          console.log('[MindMap] Data loaded: ' + mindMapState.graphData.nodes.length + ' nodes, ' + (mindMapState.graphData.links?.length || 0) + ' links');

          // Populate header controls
          populateHeaderControls();

          // Check if D3 is loaded
          if (typeof d3 === 'undefined') {
            console.warn('[MindMap] D3.js not loaded yet, retrying in 500ms...');
            setTimeout(initMindMap, 500);
            return;
          }

          console.log('[MindMap] D3.js loaded, setting up filters and creating graph...');

          // Set up filter handlers (every time since DOM is recreated)
          setupMindMapFilters();

          createMindMapGraph(mindMapState.graphData);
          console.log('[MindMap] initMindMap complete, simulation=' + !!mindMapState.simulation);
        } catch (e) {
          console.error('[MindMap] Failed to initialize mind map: ' + e);
        }
      }

      function populateHeaderControls() {
        // Populate stats in header
        const statsEl = document.getElementById('mindmapStatsInline');
        const statsData = document.getElementById('mindmapStatsData');
        if (statsEl && statsData) {
          try {
            const stats = JSON.parse(statsData.textContent || '{}');
            statsEl.textContent = stats.skill_count + ' skills · ' + stats.tool_count + ' tools · ' + stats.intent_count + ' intents';
          } catch (e) {}
        }

        // Populate persona select
        const personaSelect = document.getElementById('personaSelect');
        const personaOptions = document.getElementById('mindmapPersonaOptions');
        if (personaSelect && personaOptions && mindMapState.graphData?.personas) {
          // Add persona options
          Object.keys(mindMapState.graphData.personas).forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p.charAt(0).toUpperCase() + p.slice(1);
            personaSelect.appendChild(opt);
          });
        }

        // Populate category select
        const categorySelect = document.getElementById('categorySelect');
        if (categorySelect && mindMapState.graphData?.stats?.categories) {
          Object.keys(mindMapState.graphData.stats.categories).forEach(c => {
            const opt = document.createElement('option');
            opt.value = c;
            opt.textContent = c.charAt(0).toUpperCase() + c.slice(1);
            categorySelect.appendChild(opt);
          });
        }
      }

      function setupMindMapFilters() {
        // Guard: prevent duplicate handler registration when initMindMap() is
        // called multiple times for the same DOM (e.g. from both rAF and setTimeout).
        // Stacked toggle handlers cancel each other out, making buttons appear dead.
        var svg = document.getElementById('mindmapSvg');
        if (svg && svg.dataset.filtersInit) return;
        if (svg) svg.dataset.filtersInit = '1';

        // Persona select
        const personaSelect = document.getElementById('personaSelect');
        if (personaSelect) {
          personaSelect.addEventListener('change', function() {
            mindMapState.selectedPersona = this.value === 'none' ? 'none' : this.value;
            applyMindMapFilters();
          });
        }

        // Category select
        const categorySelect = document.getElementById('categorySelect');
        if (categorySelect) {
          categorySelect.addEventListener('change', function() {
            mindMapState.selectedCategory = this.value;
            applyMindMapFilters();
          });
        }

        // Toggle checkboxes
        const toggleTools = document.getElementById('toggleTools');
        const toggleIntents = document.getElementById('toggleIntents');
        const toggleLabels = document.getElementById('toggleLabels');

        if (toggleTools) {
          toggleTools.addEventListener('change', function() {
            mindMapState.showTools = this.checked;
            applyMindMapFilters();
          });
        }
        if (toggleIntents) {
          toggleIntents.addEventListener('change', function() {
            mindMapState.showIntents = this.checked;
            applyMindMapFilters();
          });
        }
        if (toggleLabels) {
          toggleLabels.addEventListener('change', function() {
            mindMapState.showLabels = this.checked;
            applyMindMapLabels();
          });
        }

        // Sticky toggle
        const toggleSticky = document.getElementById('toggleSticky');
        if (toggleSticky) {
          toggleSticky.addEventListener('change', function() {
            mindMapState.sticky = this.checked;
          });
        }

        // Physics panel toggle
        const physicsToggle = document.getElementById('physicsToggle');
        const physicsPanel = document.getElementById('physicsPanel');
        if (physicsToggle && physicsPanel) {
          physicsToggle.addEventListener('click', function() {
            const isVisible = physicsPanel.style.display !== 'none';
            physicsPanel.style.display = isVisible ? 'none' : 'flex';
            physicsToggle.classList.toggle('active', !isVisible);
          });
        }

        // Physics sliders
        setupPhysicsSlider('chargeSlider', 'chargeValue', function(v) {
          mindMapState.chargeStrength = v;
          updateSimulationForce('charge', function(sim) {
            sim.force('charge').strength(function(d) {
              var base = v;
              return d.type === 'skill' ? base * 1.25 : base * 0.4;
            });
          });
        }, function(v) { return v; });

        setupPhysicsSlider('linkDistSlider', 'linkDistValue', function(v) {
          mindMapState.linkDistance = v;
          updateSimulationForce('link', function(sim) {
            sim.force('link').distance(function(d) {
              return d.type === 'calls' ? v * 1.15 : v;
            });
          });
        }, function(v) { return v; });

        setupPhysicsSlider('collisionSlider', 'collisionValue', function(v) {
          mindMapState.collisionRadius = v;
          updateSimulationForce('collision', function(sim) {
            sim.force('collision').radius(function(d) {
              return (d.size || 8) + v;
            });
          });
        }, function(v) { return v; });

        setupPhysicsSlider('centerSlider', 'centerValue', function(v) {
          var mapped = v / 100;
          mindMapState.centerStrength = mapped;
          updateSimulationForce('center', function(sim) {
            sim.force('center').strength(mapped);
          });
        }, function(v) { return (v / 100).toFixed(2); });

        setupPhysicsSlider('decaySlider', 'decayValue', function(v) {
          var mapped = v / 1000;
          mindMapState.alphaDecay = mapped;
          if (mindMapState.simulation) {
            mindMapState.simulation.alphaDecay(mapped);
          }
        }, function(v) { return (v / 1000).toFixed(3); });

        setupPhysicsSlider('velocitySlider', 'velocityValue', function(v) {
          var mapped = v / 100;
          mindMapState.velocityDecay = mapped;
          if (mindMapState.simulation) {
            mindMapState.simulation.velocityDecay(mapped);
          }
        }, function(v) { return (v / 100).toFixed(2); });

        // Physics action buttons
        var resetBtn = document.getElementById('physicsReset');
        if (resetBtn) {
          resetBtn.addEventListener('click', function() {
            resetPhysicsDefaults();
          });
        }

        var reheatBtn = document.getElementById('physicsReheat');
        if (reheatBtn) {
          reheatBtn.addEventListener('click', function() {
            if (mindMapState.simulation) {
              mindMapState.simulation.alpha(1).restart();
            }
          });
        }

        var pauseBtn = document.getElementById('physicsPause');
        if (pauseBtn) {
          pauseBtn.addEventListener('click', function() {
            if (mindMapState.simulation) {
              if (mindMapState.simulation.alpha() > 0.001) {
                mindMapState.simulation.stop();
                pauseBtn.textContent = 'Resume';
              } else {
                mindMapState.simulation.alpha(0.3).restart();
                pauseBtn.textContent = 'Pause';
              }
            }
          });
        }

        var unstickBtn = document.getElementById('physicsUnstick');
        if (unstickBtn) {
          unstickBtn.addEventListener('click', function() {
            if (mindMapState.simulation) {
              mindMapState.simulation.nodes().forEach(function(d) {
                d.fx = null;
                d.fy = null;
              });
              mindMapState.simulation.alpha(0.3).restart();
            }
          });
        }
      }

      function setupPhysicsSlider(sliderId, valueId, onUpdate, formatFn) {
        var slider = document.getElementById(sliderId);
        var valueEl = document.getElementById(valueId);
        if (slider) {
          slider.addEventListener('input', function() {
            var v = parseFloat(this.value);
            if (valueEl) valueEl.textContent = formatFn(v);
            console.log('[MindMap] Slider ' + sliderId + ' = ' + v + ', sim=' + !!mindMapState.simulation);
            onUpdate(v);
          });
        } else {
          console.log('[MindMap] Slider not found: ' + sliderId);
        }
      }

      function updateSimulationForce(forceName, updateFn) {
        if (!mindMapState.simulation) {
          console.log('[MindMap] updateSimulationForce(' + forceName + '): no simulation');
          return;
        }
        var force = mindMapState.simulation.force(forceName);
        if (!force) {
          console.log('[MindMap] updateSimulationForce(' + forceName + '): force not found');
          return;
        }
        updateFn(mindMapState.simulation);
        mindMapState.simulation.alpha(0.3).restart();
      }

      function resetPhysicsDefaults() {
        var defaults = {
          chargeStrength: -120, linkDistance: 70, collisionRadius: 5,
          centerStrength: 0.05, alphaDecay: 0.0228, velocityDecay: 0.4
        };
        Object.assign(mindMapState, defaults);

        // Update slider positions and labels
        setSlider('chargeSlider', 'chargeValue', -120, String(-120));
        setSlider('linkDistSlider', 'linkDistValue', 70, '70');
        setSlider('collisionSlider', 'collisionValue', 5, '5');
        setSlider('centerSlider', 'centerValue', 5, '0.05');
        setSlider('decaySlider', 'decayValue', 23, '0.023');
        setSlider('velocitySlider', 'velocityValue', 40, '0.40');

        // Apply to simulation
        if (mindMapState.simulation) {
          var sim = mindMapState.simulation;
          sim.force('charge').strength(function(d) { return d.type === 'skill' ? -150 : -50; });
          sim.force('link').distance(function(d) { return d.type === 'calls' ? 80 : 60; });
          sim.force('collision').radius(function(d) { return (d.size || 8) + 5; });
          sim.force('center').strength(0.05);
          sim.alphaDecay(0.0228);
          sim.velocityDecay(0.4);
          sim.alpha(0.5).restart();
        }
      }

      function setSlider(sliderId, valueId, sliderVal, displayVal) {
        var s = document.getElementById(sliderId);
        var v = document.getElementById(valueId);
        if (s) s.value = String(sliderVal);
        if (v) v.textContent = displayVal;
      }

      function applyMindMapFilters() {
        if (!mindMapState.graphData) return;

        const { selectedPersona, selectedCategory, showTools, showIntents } = mindMapState;
        const { nodes, links, personas } = mindMapState.graphData;

        // Get skills for selected persona
        const personaSkills = selectedPersona !== 'none' && personas[selectedPersona]
          ? new Set(personas[selectedPersona].skills)
          : null;

        // Apply filters to nodes
        const svgEl = d3.select('#mindmapSvg');
        const nodeSelection = svgEl.selectAll('.node');
        const linkSelection = svgEl.selectAll('.link');

        // Persona colors for glow effect
        const personaColors = {
          developer: '#667eea',
          devops: '#4ecdc4',
          incident: '#ff6b6b',
          release: '#f7dc6f',
          researcher: '#bb8fce'
        };
        const personaColor = personaColors[selectedPersona] || '#667eea';

        // Filter nodes
        nodeSelection.each(function(d) {
          const node = d3.select(this);
          let visible = true;
          let personaActive = false;

          // Type filter (tools/intents)
          if (d.type === 'tool' && !showTools) visible = false;
          if (d.type === 'intent' && !showIntents) visible = false;

          // Category filter
          if (selectedCategory !== 'all' && d.type === 'skill' && d.category !== selectedCategory) {
            visible = false;
          }

          // Persona filter
          if (personaSkills) {
            if (d.type === 'skill') {
              personaActive = personaSkills.has(d.id);
            } else if (d.type === 'tool') {
              // Tool is active if any persona skill uses it
              personaActive = nodes.some(n =>
                n.type === 'skill' && personaSkills.has(n.id) && (n.tools || []).includes(d.id.replace('tool_', ''))
              );
            } else if (d.type === 'intent') {
              // Intent is active if any persona skill has it
              personaActive = nodes.some(n =>
                n.type === 'skill' && personaSkills.has(n.id) && (n.intents || []).includes(d.id.replace('intent_', ''))
              );
            }
          }

          // Apply classes
          node.classed('hidden', !visible);
          node.style('display', visible ? null : 'none');

          if (personaSkills) {
            node.classed('persona-active', personaActive);
            node.classed('persona-inactive', !personaActive);
            node.select('.glow-ring').attr('stroke', personaColor);
            node.style('--persona-color', personaColor);
          } else {
            node.classed('persona-active', false);
            node.classed('persona-inactive', false);
          }
        });

        // Filter links
        linkSelection.each(function(l) {
          const link = d3.select(this);
          const sourceId = l.source.id || l.source;
          const targetId = l.target.id || l.target;

          // Check if both ends are visible
          const sourceNode = nodes.find(n => n.id === sourceId);
          const targetNode = nodes.find(n => n.id === targetId);

          let visible = true;
          if (sourceNode?.type === 'tool' && !showTools) visible = false;
          if (targetNode?.type === 'tool' && !showTools) visible = false;
          if (sourceNode?.type === 'intent' && !showIntents) visible = false;
          if (targetNode?.type === 'intent' && !showIntents) visible = false;

          link.style('display', visible ? null : 'none');

          // Persona highlighting for links
          if (personaSkills) {
            const sourceActive = sourceNode?.type === 'skill' ? personaSkills.has(sourceId) : false;
            const targetActive = targetNode?.type === 'skill' ? personaSkills.has(targetId) : false;
            const linkActive = sourceActive || targetActive;

            link.classed('persona-active', linkActive);
            link.classed('persona-inactive', !linkActive);
            link.style('--persona-color', personaColor);
          } else {
            link.classed('persona-active', false);
            link.classed('persona-inactive', false);
          }
        });
      }

      function applyMindMapLabels() {
        const svgEl = d3.select('#mindmapSvg');
        const labels = svgEl.selectAll('.node-label');

        if (mindMapState.showLabels) {
          // Add labels if they don't exist
          if (labels.empty()) {
            svgEl.selectAll('.node').each(function(d) {
              if (d.type === 'skill') {
                d3.select(this).append('text')
                  .attr('class', 'node-label')
                  .attr('dy', d.size + 12)
                  .attr('text-anchor', 'middle')
                  .attr('fill', 'var(--vscode-foreground)')
                  .attr('font-size', '10px')
                  .text(d.label.length > 15 ? d.label.substring(0, 12) + '...' : d.label);
              }
            });
          } else {
            labels.style('display', null);
          }
        } else {
          labels.style('display', 'none');
        }
      }

      function createMindMapGraph(graphData) {
        console.log('[MindMap] createMindMapGraph called with ' + (graphData.nodes?.length || 0) + ' nodes, ' + (graphData.links?.length || 0) + ' links');

        const svgEl = d3.select('#mindmapSvg');
        const container = document.querySelector('.mindmap-graph');
        if (!container) {
          console.error('[MindMap] .mindmap-graph container not found');
          return;
        }

        const width = container.clientWidth || 800;
        const height = container.clientHeight || 600;

        console.log('[MindMap] container size: ' + width + 'x' + height);

        // Clear existing
        svgEl.selectAll('g').remove();

        // Category colors
        const categoryColors = {
          code: '#ff6b6b',
          deploy: '#4ecdc4',
          jira: '#45b7d1',
          incident: '#f7dc6f',
          daily: '#bb8fce',
          memory: '#82e0aa',
          comms: '#f8b500',
          maintenance: '#95a5a6',
          other: '#667eea',
          tool: '#4ecdc4',
          intent: '#ffe66d'
        };

        // Filter nodes based on current state
        let filteredNodes = graphData.nodes;
        if (!mindMapState.showTools) {
          filteredNodes = filteredNodes.filter(n => n.type !== 'tool');
        }
        if (!mindMapState.showIntents) {
          filteredNodes = filteredNodes.filter(n => n.type !== 'intent');
        }
        if (mindMapState.selectedCategory !== 'all') {
          filteredNodes = filteredNodes.filter(n =>
            n.type !== 'skill' || n.category === mindMapState.selectedCategory
          );
        }

        const nodeIds = new Set(filteredNodes.map(n => n.id));
        const filteredLinks = graphData.links.filter(l => {
          const sourceId = l.source.id || l.source;
          const targetId = l.target.id || l.target;
          return nodeIds.has(sourceId) && nodeIds.has(targetId);
        });

        // Create zoom behavior
        const zoom = d3.zoom()
          .scaleExtent([0.1, 4])
          .on('zoom', (event) => {
            g.attr('transform', event.transform);
          });

        svgEl.call(zoom);

        // Main group for zoom/pan
        const g = svgEl.append('g');

        // Create simulation using physics state
        var cs = mindMapState.chargeStrength;
        var ld = mindMapState.linkDistance;
        var cr = mindMapState.collisionRadius;
        var cStr = mindMapState.centerStrength;

        const simulation = d3.forceSimulation(filteredNodes)
          .force('link', d3.forceLink(filteredLinks)
            .id(d => d.id)
            .distance(d => d.type === 'calls' ? ld * 1.15 : ld)
            .strength(d => d.strength || 0.5))
          .force('charge', d3.forceManyBody()
            .strength(d => d.type === 'skill' ? cs * 1.25 : cs * 0.4))
          .force('center', d3.forceCenter(width / 2, height / 2).strength(cStr))
          .force('collision', d3.forceCollide()
            .radius(d => (d.size || 8) + cr))
          .alphaDecay(mindMapState.alphaDecay)
          .velocityDecay(mindMapState.velocityDecay);

        // Store simulation reference for live controls
        mindMapState.simulation = simulation;
        console.log('[MindMap] Simulation created and stored, forces: link=' + !!simulation.force('link') + ' charge=' + !!simulation.force('charge') + ' center=' + !!simulation.force('center') + ' collision=' + !!simulation.force('collision'));

        // Draw links
        const link = g.append('g')
          .attr('class', 'links')
          .selectAll('line')
          .data(filteredLinks)
          .enter()
          .append('line')
          .attr('class', d => 'link ' + d.type)
          .attr('stroke-width', d => d.type === 'calls' ? 2 : 1);

        // Draw nodes
        const node = g.append('g')
          .attr('class', 'nodes')
          .selectAll('g')
          .data(filteredNodes)
          .enter()
          .append('g')
          .attr('class', 'node')
          .call(d3.drag()
            .on('start', dragstarted)
            .on('drag', dragged)
            .on('end', dragended));

        console.log('[MindMap] Created ' + node.size() + ' D3 nodes and ' + link.size() + ' D3 links (filtered from ' + filteredNodes.length + ' nodes, ' + filteredLinks.length + ' links)');

        // Glow ring
        node.append('circle')
          .attr('class', 'glow-ring')
          .attr('r', d => (d.size || 8) + 6)
          .attr('stroke', '#667eea');

        // Main node circle
        node.append('circle')
          .attr('class', 'main')
          .attr('r', d => d.size || 8)
          .attr('fill', d => categoryColors[d.category] || categoryColors.other)
          .attr('stroke', d => d3.color(categoryColors[d.category] || categoryColors.other).brighter(0.5));

        // Inner highlight
        node.append('circle')
          .attr('r', d => (d.size || 8) * 0.4)
          .attr('fill', 'rgba(255,255,255,0.3)')
          .attr('cx', d => -(d.size || 8) * 0.2)
          .attr('cy', d => -(d.size || 8) * 0.2);

        // Hover interactions
        node.on('mouseenter', (event, d) => {
          highlightConnections(d, filteredNodes, filteredLinks, node, link);
          showTooltip(event, d, categoryColors);
        })
        .on('mousemove', (event) => {
          moveTooltip(event);
        })
        .on('mouseleave', () => {
          resetHighlights(node, link);
          hideTooltip();
        })
        .on('click', (event, d) => {
          if (d.type === 'skill') {
            vscode.postMessage({ command: 'loadSkill', skillName: d.id });
            vscode.postMessage({ command: 'setSkillView', view: 'info' });
          }
        });

        // Update positions on tick
        simulation.on('tick', () => {
          link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);

          node.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
        });

        // Initial zoom to fit
        setTimeout(() => {
          const bounds = g.node().getBBox();
          const fullWidth = bounds.width || 1;
          const fullHeight = bounds.height || 1;
          const midX = bounds.x + fullWidth / 2;
          const midY = bounds.y + fullHeight / 2;

          const scale = 0.8 / Math.max(fullWidth / width, fullHeight / height);
          const translate = [width / 2 - scale * midX, height / 2 - scale * midY];

          svgEl.transition()
            .duration(750)
            .call(zoom.transform, d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale));
        }, 1000);

        // Drag functions - respects sticky mode
        function dragstarted(event, d) {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x;
          d.fy = d.y;
        }

        function dragged(event, d) {
          d.fx = event.x;
          d.fy = event.y;
        }

        function dragended(event, d) {
          if (!event.active) simulation.alphaTarget(0);
          // In sticky mode, keep the node pinned where dropped
          if (!mindMapState.sticky) {
            d.fx = null;
            d.fy = null;
          }
        }
      }

      function highlightConnections(d, nodes, links, nodeSelection, linkSelection) {
        const connectedIds = new Set([d.id]);

        links.forEach(l => {
          const sourceId = l.source.id || l.source;
          const targetId = l.target.id || l.target;
          if (sourceId === d.id) connectedIds.add(targetId);
          if (targetId === d.id) connectedIds.add(sourceId);
        });

        nodeSelection.classed('dimmed', n => !connectedIds.has(n.id));
        nodeSelection.classed('highlighted', n => connectedIds.has(n.id));

        linkSelection.classed('dimmed', l => {
          const sourceId = l.source.id || l.source;
          const targetId = l.target.id || l.target;
          return sourceId !== d.id && targetId !== d.id;
        });
        linkSelection.classed('highlighted', l => {
          const sourceId = l.source.id || l.source;
          const targetId = l.target.id || l.target;
          return sourceId === d.id || targetId === d.id;
        });
      }

      function resetHighlights(nodeSelection, linkSelection) {
        nodeSelection.classed('dimmed', false).classed('highlighted', false);
        linkSelection.classed('dimmed', false).classed('highlighted', false);
      }

      function showTooltip(event, d, categoryColors) {
        const tooltip = document.getElementById('mindmapTooltip');
        if (!tooltip) return;

        const color = categoryColors[d.category] || categoryColors.other;
        let html = '<h3>' + escapeHtml(d.label) + '<span class="type-badge" style="background: ' + color + '">' + d.type + '</span></h3>';

        if (d.description) {
          html += '<p class="description">' + escapeHtml(d.description.substring(0, 150)) + (d.description.length > 150 ? '...' : '') + '</p>';
        }

        if (d.type === 'skill') {
          if (d.personas && d.personas.length > 0) {
            html += '<div class="meta-tags">';
            d.personas.forEach(function(p) {
              html += '<span class="meta-tag">' + p + '</span>';
            });
            html += '</div>';
          }
        }

        tooltip.innerHTML = html;
        tooltip.classList.add('visible');
        moveTooltip(event);
      }

      function moveTooltip(event) {
        const tooltip = document.getElementById('mindmapTooltip');
        if (!tooltip) return;

        const container = document.querySelector('.mindmap-graph');
        if (!container) return;

        const rect = container.getBoundingClientRect();
        const x = event.clientX - rect.left + 15;
        const y = event.clientY - rect.top + 15;

        tooltip.style.left = x + 'px';
        tooltip.style.top = y + 'px';
      }

      function hideTooltip() {
        const tooltip = document.getElementById('mindmapTooltip');
        if (tooltip) {
          tooltip.classList.remove('visible');
        }
      }

      function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
      }
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
        logger.log(`setSkillView: view=${message.view}, skills.length=${this.skills.length}, mindMapData=${!!this.mindMapData}`);
        // Build mind map data immediately if needed
        if (message.view === "mindmap" && !this.mindMapData) {
          logger.log("Mind map: no data yet, building from local skills...");
          if (this.skills.length > 0) {
            try {
              this.mindMapData = this.buildGraphFromSkills();
              logger.log(`Mind map: built graph - nodes=${this.mindMapData?.nodes?.length}, links=${this.mindMapData?.links?.length}, stats=${JSON.stringify(this.mindMapData?.stats)}`);
            } catch (e) {
              logger.error(`Mind map: buildGraphFromSkills FAILED: ${e}`);
            }
          } else {
            logger.warn("Mind map: this.skills is EMPTY - cannot build graph");
          }
          // Also try D-Bus async for richer data
          this.loadMindMapData().catch(e => logger.warn(`Mind map: async D-Bus load failed: ${e}`));
        }
        if (message.view === "mindmap") {
          logger.log(`Mind map: rendering with mindMapData=${!!this.mindMapData}, nodes=${this.mindMapData?.nodes?.length || 0}`);
        }
        this.forceNextRender = true;
        this.notifyNeedsRender();
        return true;

      case "setMindMapPersona":
        // Handle persona filtering in mind map (client-side for now)
        this.notifyNeedsRender();
        return true;

      case "setMindMapCategory":
        // Handle category filtering in mind map (client-side for now)
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
        // Update running skills from the skill execution watcher (file-based)
        // File watcher is secondary to WebSocket - only add skills not already tracked by WebSocket
        if (message.runningSkills && Array.isArray(message.runningSkills)) {
          const now = Date.now();

          for (const s of message.runningSkills) {
            const execId = s.executionId || `exec-${Date.now()}`;

            // Check if already tracked by executionId
            const existingById = this.runningSkills.find(rs => rs.executionId === execId);

            // Check if already tracked by skillName (running)
            const existingByName = this.runningSkills.find(
              rs => rs.skillName === s.skillName && rs.status === "running"
            );

            const existing = existingById || existingByName;

            const newStatus = s.status === "running" ? "running" : s.status === "success" ? "completed" : "failed";
            const newProgress = s.totalSteps > 0 ? Math.round((s.currentStepIndex / s.totalSteps) * 100) : 0;
            const newSource = (s.source as "chat" | "cron" | "slack" | "manual" | "api") || "chat";

            if (existing) {
              // Update existing entry, but DON'T overwrite WebSocket-owned skills' executionId
              // WebSocket is authoritative for IDs
              if (existing.addedBy !== "websocket") {
                existing.executionId = execId;
                existing.addedBy = "filewatcher";
              }
              existing.status = newStatus;
              existing.progress = newProgress;
              existing.currentStep = `Step ${s.currentStepIndex + 1}/${s.totalSteps}`;
              existing.elapsed = s.elapsedMs || 0;
              // Update source if file has a real source
              if (newSource !== "manual") {
                existing.source = newSource;
              }
            } else {
              // Only add if not recently added (within 2 seconds) - prevents race condition duplicates
              const recentlyAdded = this.runningSkills.some(
                rs => rs.skillName === s.skillName &&
                      rs.addedAt &&
                      (now - rs.addedAt) < 2000
              );

              if (!recentlyAdded) {
                // Add new entry from file watcher
                this.runningSkills.push({
                  executionId: execId,
                  skillName: s.skillName,
                  status: newStatus,
                  progress: newProgress,
                  currentStep: `Step ${s.currentStepIndex + 1}/${s.totalSteps}`,
                  startedAt: s.startTime || new Date().toISOString(),
                  source: newSource,
                  elapsed: s.elapsedMs || 0,
                  addedBy: "filewatcher",
                  addedAt: now,
                });
                logger.log(`Added running skill from file watcher: ${s.skillName} (${execId})`);
              } else {
                logger.log(`Skipping duplicate from file watcher (recently added): ${s.skillName}`);
              }
            }
          }

          // Remove skills that are no longer in the file (completed/removed)
          // But only remove file-watcher-owned skills, not WebSocket-owned ones
          const fileSkillIds = new Set(message.runningSkills.map((s: any) => s.executionId));
          const fileSkillNames = new Set(message.runningSkills.map((s: any) => s.skillName));
          this.runningSkills = this.runningSkills.filter(rs => {
            // Keep if still in file by ID or name
            if (fileSkillIds.has(rs.executionId)) return true;
            if (fileSkillNames.has(rs.skillName) && rs.status === "running") return true;
            // Keep completed/failed for a bit (they'll be cleaned up by timeout)
            if (rs.status !== "running") return true;
            // Keep WebSocket-owned skills even if not in file (WebSocket is authoritative)
            if (rs.addedBy === "websocket") return true;
            // Remove stale running skills not in file
            return false;
          });

          // Final deduplication pass
          this.deduplicateRunningSkills();

          // Two-level change detection:
          // 1. Structural changes (skill added/removed/status changed) -> full re-render
          // 2. Progress changes (step updates) -> incremental CSS update only
          const newStructuralFP = this._buildRunningSkillsStructuralFingerprint();
          const newProgressFP = this._buildRunningSkillsProgressFingerprint();

          if (newStructuralFP !== this._lastRunningSkillsStructuralFP) {
            // Structure changed (new skill, skill completed, etc.) - full re-render needed
            this._lastRunningSkillsStructuralFP = newStructuralFP;
            this._lastRunningSkillsProgressFP = newProgressFP;
            logger.log(`Updated running skills: ${this.runningSkills.length} skills (structural change, full re-render)`);
            this.forceNextRender = true; // Structural change bypasses workflow incremental mode
            this.notifyNeedsRenderIfNotMindMap();
          } else if (newProgressFP !== this._lastRunningSkillsProgressFP) {
            // Only progress changed - use incremental update if viewing workflow
            this._lastRunningSkillsProgressFP = newProgressFP;
            if (this.skillView === "workflow" && this.sendIncrementalStepUpdate()) {
              logger.log(`Updated running skills: ${this.runningSkills.length} skills (progress change, incremental update)`);
            } else {
              logger.log(`Updated running skills: ${this.runningSkills.length} skills (progress change, full re-render)`);
              this.notifyNeedsRenderIfNotMindMap();
            }
          } else {
            logger.log(`Updated running skills: ${this.runningSkills.length} skills (no change, skipping render)`);
          }
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

          // Send incremental CSS update instead of full re-render to avoid flickering
          if (this.selectedSkill === exec.skillName && this.skillView === "workflow") {
            this.sendIncrementalStepUpdate();
            // No fallback to full re-render - if incremental fails, webview is gone anyway
          }
        }
        return true;

      default:
        return false;
    }
  }

  /**
   * Load mind map graph data from D-Bus
   */
  private async loadMindMapData(): Promise<void> {
    const now = Date.now();
    const timeSinceLastLoad = now - this.lastMindMapLoad;

    // Throttle mind map loading
    if (timeSinceLastLoad < SkillsTab.MINDMAP_MIN_INTERVAL_MS && this.mindMapData) {
      logger.log(`Skipping mind map load - last load ${Math.round(timeSinceLastLoad / 1000)}s ago`);
      return;
    }

    logger.log("Loading mind map data via D-Bus...");
    try {
      const result = await dbus.config_getSkillsGraph();
      if (result.success && result.data) {
        const dbusGraph = (result.data as any).graph || result.data;
        const dbusNodeCount = dbusGraph?.nodes?.length || 0;
        const localNodeCount = this.mindMapData?.nodes?.length || 0;
        logger.log(`Mind map D-Bus returned ${dbusNodeCount} nodes (local has ${localNodeCount})`);
        // Only use D-Bus data if it's richer than what we already have
        if (dbusNodeCount > localNodeCount) {
          this.mindMapData = dbusGraph;
          this.lastMindMapLoad = now;
          this.forceNextRender = true;
          this.notifyNeedsRender();
        } else {
          logger.log("Mind map D-Bus data not richer than local - keeping local");
        }
        return;
      } else if (result.error) {
        logger.warn(`Mind map D-Bus load failed: ${result.error}, falling back to local data`);
      }
    } catch (error) {
      logger.warn(`Mind map D-Bus error: ${error}, falling back to local data`);
    }

    // Fallback: build graph from already-loaded skills list
    if (this.skills.length > 0) {
      this.mindMapData = this.buildGraphFromSkills();
      this.lastMindMapLoad = now;
      logger.log(`Built mind map from local skills: ${this.mindMapData?.stats?.skill_count || 0} skills`);
      this.forceNextRender = true;
      this.notifyNeedsRender();
    }
  }

  /**
   * Build graph data from already-loaded skills list (fallback when D-Bus unavailable)
   */
  private buildGraphFromSkills(): SkillsGraphData {
    const nodes: any[] = [];
    const links: any[] = [];
    const toolNodes: Record<string, any> = {};
    const intentNodes: Record<string, any> = {};
    const allTools = new Set<string>();
    const categories: Record<string, number> = {};

    const categoryKeywords: Record<string, string[]> = {
      code: ["git", "commit", "branch", "mr", "pr", "review", "lint", "code"],
      deploy: ["deploy", "ephemeral", "namespace", "bonfire", "rollout", "scale"],
      jira: ["jira", "issue", "sprint", "ticket", "hygiene"],
      incident: ["alert", "incident", "debug", "investigate", "silence"],
      daily: ["coffee", "beer", "standup", "weekly", "morning", "evening"],
      memory: ["memory", "learn", "pattern", "knowledge", "bootstrap"],
      comms: ["slack", "notify", "schedule", "meeting", "team"],
      maintenance: ["cleanup", "sync", "reindex", "refresh"],
    };

    const intentKeywords = [
      "create", "review", "deploy", "investigate", "check", "start",
      "close", "update", "notify", "schedule", "debug", "release",
      "sync", "cleanup", "learn", "scan", "extend", "cancel",
    ];

    for (const skill of this.skills) {
      const nameLower = skill.name.toLowerCase();
      const descLower = (skill.description || "").toLowerCase();

      // Categorize
      let category = "other";
      for (const [cat, keywords] of Object.entries(categoryKeywords)) {
        if (keywords.some(kw => nameLower.includes(kw) || descLower.includes(kw))) {
          category = cat;
          break;
        }
      }
      categories[category] = (categories[category] || 0) + 1;

      // Extract intents
      const skillIntents: string[] = [];
      for (const intent of intentKeywords) {
        if (nameLower.includes(intent) || descLower.includes(intent)) {
          skillIntents.push(intent);
          if (!intentNodes[intent]) {
            intentNodes[intent] = {
              id: `intent_${intent}`,
              type: "intent",
              category: "intent",
              label: intent.charAt(0).toUpperCase() + intent.slice(1),
              size: 6,
            };
          }
        }
      }

      // Skill node
      nodes.push({
        id: skill.name,
        type: "skill",
        category,
        label: skill.name.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()),
        description: (skill.description || "").substring(0, 300),
        tools: [],
        intents: skillIntents,
        outputs: [],
        personas: [],
        size: 8 + Math.min(skill.step_count || 0, 20),
      });

      // Intent links
      for (const intent of skillIntents) {
        links.push({
          source: `intent_${intent}`,
          target: skill.name,
          type: "triggers",
          strength: 0.5,
        });
      }
    }

    nodes.push(...Object.values(toolNodes));
    nodes.push(...Object.values(intentNodes));

    return {
      nodes,
      links,
      personas: {},
      stats: {
        skill_count: this.skills.length,
        tool_count: allTools.size,
        intent_count: Object.keys(intentNodes).length,
        link_count: links.length,
        persona_count: 0,
        categories,
      },
    };
  }

  private async loadSkill(skillName: string): Promise<void> {
    this.selectedSkill = skillName;

    // Clear execution watching when switching skills from sidebar
    // (selectRunningSkill sets watchingExecutionId BEFORE calling loadSkill)
    // If watchingExecutionId is set and matches a running skill with this name, keep it
    const isWatchingThisSkill = this.watchingExecutionId &&
      this.runningSkills.some(s => s.executionId === this.watchingExecutionId && s.skillName === skillName);

    if (!isWatchingThisSkill) {
      // Check if this skill happens to be running - auto-attach to it
      // This handles the case where a user clicks a running skill from the sidebar
      // (not from the Running Skills panel)
      const runningInstance = this.runningSkills.find(
        s => s.skillName === skillName && s.status === "running"
      );
      if (runningInstance) {
        logger.log(`loadSkill: Auto-attaching to running execution ${runningInstance.executionId} for ${skillName}`);
        this.watchingExecutionId = runningInstance.executionId;
        // Initialize with progress-based step status (will be refined by next update)
        const totalSteps = runningInstance.totalSteps || 0;
        const currentStepIndex = totalSteps > 0
          ? Math.floor((runningInstance.progress / 100) * totalSteps)
          : 0;
        this.detailedExecution = {
          executionId: runningInstance.executionId,
          skillName: runningInstance.skillName,
          status: "running",
          currentStepIndex: currentStepIndex,
          totalSteps: totalSteps,
          steps: [],
          startTime: runningInstance.startedAt,
        };
      } else {
        // User clicked a skill from sidebar that's not running
        // Clear execution state to show static template
        this.watchingExecutionId = null;
        this.detailedExecution = null;
      }
    }

    try {
      const result = await dbus.config_getSkillDefinition(skillName);
      if (result.success && result.data) {
        this.selectedSkillData = (result.data as any).skill || result.data;
      }
    } catch (error) {
      logger.error("Error loading skill", error);
    }

    // If we auto-attached to a running execution above, populate the steps
    // array from the skill definition so the initial render shows correct statuses
    if (this.detailedExecution && this.selectedSkillData?.steps && this.detailedExecution.steps.length === 0) {
      const currentStepIndex = this.detailedExecution.currentStepIndex;
      this.detailedExecution.steps = this.selectedSkillData.steps.map((step: any, index: number) => {
        let status: "pending" | "running" | "success" | "failed" | "skipped" = "pending";
        if (index < currentStepIndex) {
          status = "success";
        } else if (index === currentStepIndex) {
          status = "running";
        }
        return {
          name: step.name || `Step ${index + 1}`,
          description: step.description,
          tool: step.tool,
          status: status,
        };
      });
      logger.log(`loadSkill: Pre-populated ${this.detailedExecution.steps.length} step statuses (current: ${currentStepIndex})`);
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

    // Copy to clipboard first (always works)
    await vscode.env.clipboard.writeText(command);
    logger.log(`Copied to clipboard: ${command}`);

    try {
      // Try to use the registered VS Code command if available
      const hasCommand = await vscode.commands.getCommands(true).then(
        cmds => cmds.includes("aa-workflow.runSkillByName")
      );

      if (hasCommand) {
        logger.log("Using aa-workflow.runSkillByName command");
        await vscode.commands.executeCommand("aa-workflow.runSkillByName", skill);
        return;
      }

      // Fallback: Try to create a new composer and paste
      logger.log("Trying composer approach...");

      // Create new composer tab
      await vscode.commands.executeCommand("composer.createNewComposerTab");

      // Wait a bit for the composer to open
      await new Promise(resolve => setTimeout(resolve, 500));

      // Try to focus and use editor.action.clipboardPasteAction
      await vscode.commands.executeCommand("composer.focusComposer");
      await new Promise(resolve => setTimeout(resolve, 200));

      // Try to paste using VS Code's paste command
      try {
        await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
        logger.log("Pasted via editor.action.clipboardPasteAction");
      } catch (pasteError) {
        logger.warn("editor.action.clipboardPasteAction failed, trying ydotool...");

        // Try ydotool as last resort
        try {
          const { sendPaste, sendEnter, sleep } = await import("../chatUtils");
          sendPaste();
          await sleep(300);
          sendEnter();
        } catch (ydotoolError) {
          logger.warn("ydotool also failed");
        }
      }

      vscode.window.showInformationMessage(
        `🚀 Skill command copied! Paste in chat: ${command}`
      );
    } catch (e) {
      logger.error(`Failed to run skill: ${e}`);

      // Show message with the copied command
      vscode.window.showInformationMessage(
        `📋 Command copied to clipboard: ${command}. Open a new chat and paste (Ctrl+V).`
      );
    }
  }

  private async openSkillFile(skillName: string): Promise<void> {
    const skill = this.skills.find((s) => s.name === skillName);

    // Try multiple sources for the file path
    let filePath: string | undefined;

    if (skill?.file) {
      filePath = skill.file;
    } else if (this.selectedSkillData?.file) {
      filePath = this.selectedSkillData.file;
    } else {
      // Fallback: construct path from workspace and skill name
      const workspaceFolders = vscode.workspace.workspaceFolders;
      if (workspaceFolders && workspaceFolders.length > 0) {
        const workspaceRoot = workspaceFolders[0].uri.fsPath;
        filePath = `${workspaceRoot}/skills/${skillName}.yaml`;
      }
    }

    if (filePath) {
      try {
        const doc = await vscode.workspace.openTextDocument(filePath);
        await vscode.window.showTextDocument(doc);
        logger.log(`Opened skill file: ${filePath}`);
      } catch (e) {
        logger.error(`Failed to open skill file: ${filePath}`, e);
        vscode.window.showErrorMessage(`Could not open skill file: ${filePath}`);
      }
    } else {
      logger.warn(`No file path found for skill: ${skillName}`);
      vscode.window.showWarningMessage(`Could not find file path for skill: ${skillName}`);
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

    // Set the execution ID we're watching BEFORE anything else
    // This ensures execution updates are accepted
    this.watchingExecutionId = executionId;

    // Calculate current step index from progress percentage
    // progress is 0-100, totalSteps tells us how many steps
    const totalSteps = runningSkill.totalSteps || 0;
    const currentStepIndex = totalSteps > 0
      ? Math.floor((runningSkill.progress / 100) * totalSteps)
      : 0;

    // Initialize detailedExecution BEFORE loadSkill
    // This ensures the workflow view has data even during async operations
    // loadSkill will NOT clear this because watchingExecutionId is already set
    this.detailedExecution = {
      executionId: executionId,
      skillName: runningSkill.skillName,
      status: runningSkill.status,
      currentStepIndex: currentStepIndex,
      totalSteps: totalSteps,
      steps: [],
      startTime: runningSkill.startedAt,
    };
    logger.log(`selectRunningSkill: Initialized detailedExecution for ${runningSkill.skillName} (${executionId}) at step ${currentStepIndex}/${totalSteps} (progress: ${runningSkill.progress}%)`);

    // Switch to workflow view to show the flowchart
    this.skillView = "workflow";

    // Load the skill definition (async - may trigger re-renders)
    await this.loadSkill(runningSkill.skillName);

    // After loadSkill, pre-populate the steps array from the skill definition
    // This is critical - without this, getExecutionStepStatus returns null for all steps
    if (this.selectedSkillData?.steps && this.detailedExecution) {
      const skillSteps = this.selectedSkillData.steps;
      this.detailedExecution.steps = skillSteps.map((step: any, index: number) => {
        // Determine status based on currentStepIndex:
        // - Steps before currentStepIndex are completed (success)
        // - Step at currentStepIndex is running
        // - Steps after currentStepIndex are pending
        let status: "pending" | "running" | "success" | "failed" | "skipped" = "pending";
        if (index < currentStepIndex) {
          status = "success";
        } else if (index === currentStepIndex) {
          status = "running";
        }
        return {
          name: step.name || `Step ${index + 1}`,
          description: step.description,
          tool: step.tool,
          status: status,
        };
      });
      logger.log(`selectRunningSkill: Pre-populated ${this.detailedExecution.steps.length} steps from skill definition, steps 0-${currentStepIndex - 1} marked success, step ${currentStepIndex} running`);
    }

    // Also set the execution ID in the watcher so it sends us updates
    const watcher = getSkillExecutionWatcher();
    if (watcher && this.detailedExecution) {
      watcher.selectExecution(executionId);

      // Try to get more detailed state from watcher if available
      const execState = watcher.getSelectedExecution();
      if (execState) {
        // Update currentStepIndex from watcher (may be more up-to-date)
        if (execState.currentStepIndex > this.detailedExecution.currentStepIndex) {
          // Mark steps between old and new currentStepIndex as success
          for (let i = this.detailedExecution.currentStepIndex; i < execState.currentStepIndex; i++) {
            if (this.detailedExecution.steps[i]) {
              this.detailedExecution.steps[i].status = "success";
            }
          }
          this.detailedExecution.currentStepIndex = execState.currentStepIndex;
          // Mark new current step as running
          if (this.detailedExecution.steps[execState.currentStepIndex]) {
            this.detailedExecution.steps[execState.currentStepIndex].status = "running";
          }
        }

        // Extract step statuses from events (these override our defaults)
        type StepStatus = "pending" | "running" | "success" | "failed" | "skipped";
        const stepStatuses = new Map<number, { status: StepStatus; duration?: number; error?: string }>();
        for (const event of execState.events) {
          if (event.stepIndex !== undefined) {
            if (event.type === 'step_complete') {
              stepStatuses.set(event.stepIndex, {
                status: 'success',
                duration: event.data?.duration,
              });
            } else if (event.type === 'step_failed') {
              stepStatuses.set(event.stepIndex, {
                status: 'failed',
                error: event.data?.error,
              });
            } else if (event.type === 'step_skipped') {
              stepStatuses.set(event.stepIndex, { status: 'skipped' });
            }
            // Don't override with 'running' from step_start - our currentStepIndex logic handles that
          }
        }

        // Update detailedExecution.steps with status info from events
        if (stepStatuses.size > 0) {
          for (const [index, info] of stepStatuses) {
            if (this.detailedExecution.steps[index]) {
              this.detailedExecution.steps[index].status = info.status;
              if (info.duration) this.detailedExecution.steps[index].duration = info.duration;
              if (info.error) this.detailedExecution.steps[index].error = info.error;
            }
          }
          logger.log(`selectRunningSkill: Applied ${stepStatuses.size} step statuses from watcher events`);
        }
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
