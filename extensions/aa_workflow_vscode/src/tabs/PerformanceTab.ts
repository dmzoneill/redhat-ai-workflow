/**
 * Performance Tab (QC - Quarterly Connection)
 *
 * 7-tab layout:
 *   Overview   - Header summary, overall score, sunburst legend, quick stats, gaps alert
 *   Calendar   - Data coverage badge, month calendar, enriched day detail with event table
 *   Issues     - ANSTRAT > Epic > Issue hierarchy with Jira links
 *   Mindmap    - Issue mindmap SVG (full-width)
 *   Competencies - Sunburst chart, expandable competency bars with evidence
 *   Progress   - Quarterly questions, highlights
 *   Log        - Manual activity entry
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";
import { createNewChat } from "../chatUtils";
import {
  QUARTER_DAYS,
  PERFORMANCE_TABS,
  getColorForPercentage,
} from "./performanceConfig";
import { getPerformanceScript } from "./performanceScript";
import { getSettingsContent } from "./performanceSettingsRenderer";
import { getProgressContent } from "./performanceProgressRenderer";
import { getHelpContent } from "./performanceHelpRenderer";
import { getOverviewContent } from "./performanceOverviewRenderer";
import { getPeersContent } from "./performancePeersRenderer";
import { getCalendarContent } from "./performanceCalendarRenderer";
import { getIssuesContent } from "./performanceIssuesRenderer";
import { getMindmapContent } from "./performanceMindmapRenderer";
import { getCompetenciesContent } from "./performanceCompetenciesRenderer";
import { handlePerformanceActionDispatch, ActionContext } from "./performanceActions";
import type {
  CompetencyScore, QuestionNote, QuestionSummary, QuestionEvidence,
  CapturedDay, CoverageInfo, PillarPoints, IssueNode, IssueSummary,
  IssueHierarchy, IssueLineageEntry, DayEvent, DayDetail,
  CompetencyEvidence, CompetencyMeta,
  StrategyAlignmentPriority, SenderRelationship, SenderSummary,
  StrategyAlignment, PerformanceState, DistributionStats,
  PeerLevelData, PeerBenchmarks, OrgStats, ExecutiveEmailSummary,
  ScoringCompConfig, EngineeringLevel, ScoringConfig,
} from "./performanceTypes";

const logger = createLogger("PerformanceTab");

// Types from performanceTypes.ts, constants from performanceConfig.ts

// ============================================================
// PerformanceTab
// ============================================================

export class PerformanceTab extends BaseTab {
  private state: PerformanceState = {
    last_updated: new Date().toISOString(),
    quarter: this.getCurrentQuarter(),
    day_of_quarter: this.getDayOfQuarter(),
    overall_percentage: 0,
    no_enrichment_overall: 0,
    peer_comparable_overall: 0,
    event_counts_by_source: {},
    comparable_event_counts_by_source: {},
    competencies: {},
    highlights: [],
    gaps: [],
    captured_days: [],
    coverage: { total_weekdays: 0, captured: 0, percentage: 0 },
    issue_hierarchy: null,
    selected_date: null,
    calendar_month: new Date().getMonth(),
    calendar_year: new Date().getFullYear(),
    active_tab: "overview",
    day_detail: null,
    competency_evidence: {},
    competency_meta: {},
    gap_suggestions: {},
    expanded_competency: null,
    scoring_config: null,
    scoring_config_expanded: false,
    scoring_comp_expanded: null,
    strategy_alignment: null,
    executive_senders: [],
    executive_emails: [],
    peer_benchmarks: null,
    org_stats: null,
    competency_view: "sunburst",
    heatmap_mode: "peer_comparable",
    event_volume_mode: "comparable",
    session_enrichment: true,
    peer_comparison_mode: "comparable",
    ai_peer_narrative: null,
    ai_peer_differentiators: null,
    ai_overview_digest: null,
    ai_calendar_insights: null,
    ai_promotion_readiness: null,
  };

  private _scoringSaveTimer: ReturnType<typeof setTimeout> | null = null;
  private _settingsDirty = false;
  private _settingsRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  private _pendingLevelRefresh = false;
  private _postSaveRefreshTimer: ReturnType<typeof setTimeout> | null = null;

  private _expandedQuestions = new Set<string>();
  private _questionEvidence = new Map<string, QuestionEvidence[]>();
  private _questionEvidenceLoading = new Set<string>();
  private _excludedEvidence = new Map<string, Set<string>>();

  constructor() {
    super({
      id: "performance",
      label: "QC",
      icon: "\u{1F4CA}",
    });
  }

  protected computeDataFingerprint(): string {
    const s = this.state;
    const parts = [
      s.overall_percentage,
      s.quarter,
      s.day_of_quarter,
      s.captured_days?.length ?? 0,
      s.coverage?.captured ?? 0,
      s.issue_hierarchy?.total_issues ?? 0,
      s.issue_hierarchy?.cached ? 1 : 0,
      Object.keys(s.competencies || {}).length,
      Object.keys(s.competency_evidence || {}).length,
      Object.keys(s.gap_suggestions || {}).length,
      s.scoring_config?.engineering_level ?? "",
      s.scoring_config?.target_per_competency ?? 0,
      s.executive_emails?.length ?? 0,
      s.executive_senders?.length ?? 0,
      s.strategy_alignment?.coverage_summary?.coverage_pct ?? 0,
      s.active_tab,
      s.selected_date ?? "",
      s.day_detail?.date ?? "",
      s.day_detail?.events?.length ?? 0,
      s.expanded_competency ?? "",
      s.scoring_config_expanded ? 1 : 0,
      s.scoring_comp_expanded ?? "",
      s.highlights?.length ?? 0,
      s.gaps?.length ?? 0,
    ];
    return parts.join("|");
  }

  getBadge(): { text: string; class?: string } | null {
    if (this.state.overall_percentage > 0) {
      return { text: `${this.state.overall_percentage}%`, class: "" };
    }
    return null;
  }

  private getCurrentQuarter(): string {
    const now = new Date();
    const quarter = Math.floor(now.getMonth() / 3) + 1;
    return `Q${quarter} ${now.getFullYear()}`;
  }

  private getDayOfQuarter(): number {
    const now = new Date();
    const quarter = Math.floor(now.getMonth() / 3);
    const quarterStart = new Date(now.getFullYear(), quarter * 3, 1);
    return Math.floor((now.getTime() - quarterStart.getTime()) / (1000 * 60 * 60 * 24)) + 1;
  }

  // ============================================================
  // Helpers
  // ============================================================

  /** Render an issue key as a clickable Jira link */
  private renderIssueLink(key: string): string {
    return `<a class="perf-issue-link" href="#" data-action="openIssue" data-key="${this.escapeHtml(key)}">${this.escapeHtml(key)}</a>`;
  }

  /** Render multiple issue keys as links */
  private renderIssueLinks(keys: string[]): string {
    if (!keys || keys.length === 0) return "";
    return keys.map(k => this.renderIssueLink(k)).join(" ");
  }

  // ============================================================
  // Data Loading
  // ============================================================

  async loadData(): Promise<void> {
    try {
      // Fire all D-Bus calls in parallel for speed
      const [
        stateResult,
        capturedResult,
        hierarchyResult,
        evidenceResult,
        cfgResult,
        sendersResult,
        emailsResult,
        peerResult,
        orgStatsResult,
      ] = await Promise.allSettled([
        dbus.stats_getState(),
        dbus.stats_getCapturedDays(),
        dbus.stats_getIssueHierarchy(false),
        dbus.stats_getCompetencyEvidence(),
        dbus.stats_getScoringConfig(),
        dbus.stats_getExecutiveSenders(),
        dbus.stats_listExecutiveEmails(),
        dbus.stats_getPeerBenchmarks(),
        dbus.stats_getOrgStats(),
      ]);

      // Process results -- order matches the call order above

      if (stateResult.status === "fulfilled") {
        const r = stateResult.value;
        if (r.success && r.data) {
          const statsState = r.data.state;
          if (statsState?.performance) {
            this.state = { ...this.state, ...statsState.performance };
            logger.info(`Loaded performance data: ${this.state.overall_percentage}%`);
          } else {
            logger.warn("No performance data in stats state -- resetting to defaults");
            this.state.overall_percentage = 0;
            this.state.peer_comparable_overall = 0;
            this.state.event_counts_by_source = {};
            this.state.comparable_event_counts_by_source = {};
            this.state.competencies = {};
            this.state.highlights = [];
            this.state.gaps = [];
            this.state.strategy_alignment = null;
          }
        }
      } else {
        logger.warn(`Failed to load state: ${stateResult.reason}`);
      }

      if (capturedResult.status === "fulfilled") {
        const r = capturedResult.value;
        if (r.success && r.data) {
          const data = r.data as any;
          this.state.captured_days = Array.isArray(data.days) ? data.days : [];
          this.state.coverage = data.coverage || this.state.coverage;
        }
      } else {
        logger.warn(`Failed to load captured days: ${capturedResult.reason}`);
      }

      if (hierarchyResult.status === "fulfilled") {
        const r = hierarchyResult.value;
        if (r.success && r.data) {
          const raw = r.data as any;
          this.state.issue_hierarchy = {
            strategies: Array.isArray(raw.strategies) ? raw.strategies : [],
            unattached_epics: Array.isArray(raw.unattached_epics) ? raw.unattached_epics : [],
            uncategorized: Array.isArray(raw.uncategorized) ? raw.uncategorized : [],
            total_issues: raw.total_issues || 0,
            cached: raw.cached || false,
            summary: raw.summary || { total_points: 0, aligned_points: 0, unaligned_points: 0, alignment_pct: 0, scope_points: {}, pillar_points: { technical: 0, leadership: 0, mentorship: 0, delivery: 0 }, tag_counts: {} },
          };
        }
      } else {
        logger.warn(`Failed to load issue hierarchy: ${hierarchyResult.reason}`);
      }

      if (evidenceResult.status === "fulfilled") {
        const r = evidenceResult.value;
        if (r.success && r.data) {
          const raw = r.data as any;
          this.state.competency_evidence = raw.competency_evidence || {};
          this.state.competency_meta = raw.competency_meta || {};
          this.state.gap_suggestions = raw.gap_suggestions || {};
        }
      } else {
        logger.warn(`Failed to load competency evidence: ${evidenceResult.reason}`);
      }

      if (cfgResult.status === "fulfilled") {
        const r = cfgResult.value;
        if (r.success && r.data) {
          this.state.scoring_config = (r.data as any).config || null;
        }
      } else {
        logger.warn(`Failed to load scoring config: ${cfgResult.reason}`);
      }

      if (this.state.strategy_alignment === undefined) {
        this.state.strategy_alignment = null;
      }

      if (sendersResult.status === "fulfilled") {
        const r = sendersResult.value;
        if (r.success && r.data) {
          this.state.executive_senders = (r.data as any).senders || [];
        }
      } else {
        logger.warn(`Failed to load executive senders: ${sendersResult.reason}`);
      }

      if (emailsResult.status === "fulfilled") {
        const r = emailsResult.value;
        if (r.success && r.data) {
          this.state.executive_emails = (r.data as any).emails || [];
        }
      } else {
        logger.warn(`Failed to load executive emails: ${emailsResult.reason}`);
      }

      if (peerResult.status === "fulfilled") {
        const r = peerResult.value;
        if (r.success && r.data) {
          this.state.peer_benchmarks = (r.data as any).benchmarks || null;
        }
      } else {
        logger.warn(`Failed to load peer benchmarks: ${peerResult.reason}`);
      }

      if (orgStatsResult.status === "fulfilled") {
        const r = orgStatsResult.value;
        if (r.success && r.data) {
          this.state.org_stats = r.data as OrgStats;
        }
      } else {
        logger.warn(`Failed to load org stats: ${orgStatsResult.reason}`);
      }

      // Load AI insights (non-blocking, fire-and-forget)
      this._loadAIInsights(dbus);
    } catch (error) {
      logger.error("Error loading data", error);
    }
  }

  private async _loadAIInsights(dbus: any): Promise<void> {
    const loads = [
      (async () => {
        try {
          const r = await dbus.stats_getPeerNarrative();
          if (r.success && r.data) this.state.ai_peer_narrative = r.data as any;
        } catch { /* AI features are optional */ }
      })(),
      (async () => {
        try {
          const r = await dbus.stats_getPeerDifferentiators();
          if (r.success && r.data) this.state.ai_peer_differentiators = r.data as any;
        } catch { /* AI features are optional */ }
      })(),
      (async () => {
        try {
          const r = await dbus.stats_getOverviewDigest();
          if (r.success && r.data) this.state.ai_overview_digest = r.data as any;
        } catch { /* AI features are optional */ }
      })(),
      (async () => {
        try {
          const r = await dbus.stats_getCalendarInsights();
          if (r.success && r.data) this.state.ai_calendar_insights = r.data as any;
        } catch { /* AI features are optional */ }
      })(),
    ];
    await Promise.allSettled(loads);
    this.notifyNeedsRender();
  }

  // ============================================================
  // Main Content
  // ============================================================

  private forceNextRender: boolean = false;

  isMindMapActive(): boolean {
    return this.state.active_tab === "mindmap";
  }

  isSettingsActive(): boolean {
    return this.state.active_tab === "settings";
  }

  public consumeForceRender(): boolean {
    if (this.forceNextRender) {
      this.forceNextRender = false;
      return true;
    }
    return false;
  }

  getContent(): string {
    const quarterProgress = Math.round((this.state.day_of_quarter / QUARTER_DAYS) * 100);
    const tab = this.state.active_tab;

    const tabs = PERFORMANCE_TABS;

    const tabBar = tabs.map(t =>
      `<button class="flex-row meetings-subtab${t.id === tab ? " active" : ""}" data-action="switchTab" data-key="${t.id}">${t.icon} ${t.label}</button>`
    ).join("");

    return `
      <!-- Header -->
      <div class="section mb-8">
        <div class="flex-between">
          <div>
            <h2 class="section-title m-0">${this.escapeHtml(this.state.quarter)} Quarterly Connection</h2>
            <div class="text-secondary text-sm mt-4">Day ${this.state.day_of_quarter} of 90 &middot; ${this.getEffectiveOverall()}% overall &middot; ${this.state.coverage.captured}/${this.state.coverage.total_weekdays} days captured</div>
          </div>
          <div class="d-flex gap-8 items-center">
            <button class="btn btn-xs btn-ghost" data-action="collectDaily" title="Collect today's data (user + peers)">Collect Today</button>
            <button class="btn btn-xs btn-ghost" data-action="backfill" title="Backfill all quarter data (user, peers, emails)">Backfill</button>
            <button class="btn btn-xs btn-ghost perf-btn-ghost-subtle" data-action="toggleBackfillOptions" title="Filtered backfill options">Backfill...</button>
            <button class="btn btn-xs btn-ghost" data-action="exportReport" title="Export quarterly report">Export</button>
            <div class="flex-row perf-quarter-progress">
              <div class="progress-bar">
                <div class="progress-fill" style="width: ${quarterProgress}%;"></div>
              </div>
              <span class="perf-progress-text">${quarterProgress}%</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Unified backfill progress indicator with phase event bar -->
      <div id="peerBackfillProgress" class="backfill-progress-panel hidden">
        <div class="backfill-progress-header">
          <span class="backfill-progress-title" id="peerProgressTitle">Backfill</span>
          <span class="text-xs" id="peerProgressPct">0%</span>
          <button class="btn btn-xs backfill-cancel-btn" id="backfillCancelBtn" data-action="cancelBackfill" title="Cancel backfill">Cancel</button>
        </div>
        <div class="backfill-phase-bar" id="backfillPhaseBar">
          <div class="backfill-phase-segment" data-phase="resolve_github" title="Resolve GitHub users"></div>
          <div class="backfill-phase-segment" data-phase="prefetch" title="Pre-fetch caches"></div>
          <div class="backfill-phase-segment" data-phase="index_gdrive" title="Index Google Drive"></div>
          <div class="backfill-phase-segment" data-phase="index_meetings" title="Index meetings"></div>
          <div class="backfill-phase-segment backfill-phase-collect" data-phase="collecting" title="Collect peer data"></div>
          <div class="backfill-phase-segment" data-phase="benchmarks" title="Update benchmarks"></div>
        </div>
        <div class="backfill-phase-labels">
          <span data-phase="resolve_github">GitHub</span>
          <span data-phase="prefetch">Cache</span>
          <span data-phase="index_gdrive">Drive</span>
          <span data-phase="index_meetings">Meets</span>
          <span data-phase="collecting" class="backfill-phase-label-collect">Collect</span>
          <span data-phase="benchmarks">Bench</span>
        </div>
        <div class="backfill-progress-detail">
          <span class="text-xs text-secondary" id="peerProgressText">Starting backfill...</span>
          <span class="text-xs text-secondary" id="peerProgressElapsed"></span>
        </div>
      </div>

      <!-- Unified backfill options panel -->
      <div id="backfillOptionsPanel" class="perf-backfill-panel hidden">
        <div class="perf-backfill-title">Backfill Options</div>
        <div class="perf-backfill-row">
          <div>
            <div class="text-xs text-secondary perf-backfill-section-label">Sources</div>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfSrcGit" checked /> Git</label>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfSrcJira" checked /> Jira</label>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfSrcGitlab" checked /> GitLab</label>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfSrcGithub" checked /> GitHub</label>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfSrcGdrive" checked /> Google Drive</label>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfSrcMeeting" checked /> Calendar / Meet</label>
          </div>
          <div>
            <div class="text-xs text-secondary perf-backfill-section-label">Scope</div>
            <label class="perf-backfill-option-label perf-backfill-option-label--spaced"><input type="checkbox" id="bfScopeUser" checked /> My data</label>
            <label class="perf-backfill-option-label perf-backfill-option-label--spaced"><input type="checkbox" id="bfScopePeers" checked /> Peer data</label>
            <label class="perf-backfill-option-label"><input type="checkbox" id="bfScopeEmails" checked /> Executive emails</label>
          </div>
          <div>
            <div class="text-xs text-secondary perf-backfill-section-label">Date Range</div>
            <select id="bfDateRange" class="perf-backfill-select">
              <option value="full">Full Quarter</option>
              <option value="7">Last 7 days</option>
              <option value="14">Last 14 days</option>
              <option value="30">Last 30 days</option>
            </select>
          </div>
        </div>
        <div class="perf-backfill-actions">
          <button class="btn btn-sm btn-primary" data-action="startFilteredBackfill">Start Backfill</button>
          <button class="btn btn-sm btn-secondary" data-action="rescorePeers">Re-score Only</button>
          <button class="btn btn-sm btn-danger" data-action="scrubData" title="Delete all collected data for this quarter">Scrub All Data</button>
          <button class="btn btn-sm perf-btn-close-subtle" data-action="cancelBackfillOptions">Close</button>
        </div>
      </div>

      <!-- Sub-tabs Navigation -->
      <div class="meetings-subtabs">${tabBar}</div>

      <!-- Tab Panels -->
      <div class="perf-tab-panels">
        ${tab === "overview" ? getOverviewContent(this.state, this.getOverviewHelpers()) : ""}
        ${tab === "calendar" ? getCalendarContent(this.state, this.getCalendarHelpers()) : ""}
        ${tab === "issues" ? getIssuesContent(this.state, this.getIssuesHelpers()) : ""}
        ${tab === "mindmap" ? getMindmapContent(this.state, this.getMindmapHelpers()) : ""}
        ${tab === "competencies" ? getCompetenciesContent(this.state, this.getCompetenciesHelpers()) : ""}
        ${tab === "progress" ? getProgressContent(this.state, this.getProgressHelpers()) : ""}
        ${tab === "settings" ? getSettingsContent(this.state, this.getSettingsHelpers()) : ""}
        ${tab === "peers" ? getPeersContent(this.state, this.getPeersHelpers()) : ""}
        ${tab === "log" ? this.renderLogTab() : ""}
        ${tab === "help" ? getHelpContent(this.state, this.getHelpHelpers()) : ""}
      </div>
    `;
  }

  // ============================================================
  // Tab Content Renderers
  // ============================================================

  private renderLogTab(): string {
    return `
      <div class="perf-tab-panel">
        <div class="section">
          <div class="section-title">Log Manual Activity</div>
          <div class="flex-row perf-manual-form">
            <select class="perf-select" id="activityCategory">
              <option value="speaking">Speaking</option>
              <option value="presentation">Presentation</option>
              <option value="demo">Demo</option>
              <option value="mentorship">Mentorship</option>
              <option value="blog">Blog Post</option>
              <option value="other">Other</option>
            </select>
            <input type="text" id="activityDescription" placeholder="Description of activity..."
                   oninput="if(this.value.length>10){this.dispatchEvent(new CustomEvent('classify-log',{bubbles:true,detail:{description:this.value}}))}" />
            <button class="btn btn-sm btn-primary" data-action="logActivity">Log</button>
          </div>
          <div class="text-secondary text-xs mt-4">AI auto-categorizes as you type</div>
        </div>
      </div>
    `;
  }

  private getTypeIcon(type: string): string {
    switch (type) {
      case "strategy": return "\u{1F3AF}";
      case "epic": return "\u{1F4E6}";
      case "story": return "\u{1F4D6}";
      case "bug": return "\u{1F41B}";
      case "task": return "\u{2705}";
      default: return "\u{1F4CB}";
    }
  }

  private getEffectivePercentage(compId: string): number {
    const c = this.state.competencies[compId];
    if (!c) return 0;
    if (!this.state.session_enrichment && c.no_enrichment_percentage != null) {
      return c.no_enrichment_percentage;
    }
    return c.percentage;
  }

  private getEffectiveOverall(): number {
    if (!this.state.session_enrichment && this.state.no_enrichment_overall > 0) {
      return this.state.no_enrichment_overall;
    }
    return this.state.overall_percentage;
  }

  private getColorForPercentage(pct: number): string {
    return getColorForPercentage(pct);
  }

  private formatCompetencyName(id: string): string {
    return id.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
  }

  private getSettingsHelpers() {
    return {
      escapeHtml: (s: string) => this.escapeHtml(s),
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
    };
  }

  private getProgressHelpers() {
    return {
      escapeHtml: (s: string) => this.escapeHtml(s),
      safeText: (s: string) => this.safeText(s),
      getEmptyStateHtml: (icon: string, msg: string) => this.getEmptyStateHtml(icon, msg),
      isQuestionExpanded: (id: string) => this._expandedQuestions.has(id),
      getQuestionEvidence: (id: string) => this._questionEvidence.get(id),
      isQuestionLoading: (id: string) => this._questionEvidenceLoading.has(id),
      getExcludedEvidence: (id: string) => this._excludedEvidence.get(id) || new Set<string>(),
    };
  }

  private getHelpHelpers() {
    return {
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
      escapeHtml: (s: string) => this.escapeHtml(s),
    };
  }

  private getOverviewHelpers() {
    return {
      getEffectivePercentage: (compId: string) => this.getEffectivePercentage(compId),
      getEffectiveOverall: () => this.getEffectiveOverall(),
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
      escapeHtml: (s: string) => this.escapeHtml(s),
      getEmptyStateHtml: (icon: string, msg: string) => this.getEmptyStateHtml(icon, msg),
      renderIssueLink: (key: string) => this.renderIssueLink(key),
      renderIssueLinks: (keys: string[]) => this.renderIssueLinks(keys),
      safeText: (text: string) => this.safeText(text),
    };
  }

  private getPeersHelpers() {
    return {
      getEffectivePercentage: (compId: string) => this.getEffectivePercentage(compId),
      getEffectiveOverall: () => this.getEffectiveOverall(),
      escapeHtml: (s: string) => this.escapeHtml(s),
    };
  }

  private getCalendarHelpers() {
    return {
      escapeHtml: (s: string) => this.escapeHtml(s),
      getEmptyStateHtml: (icon: string, msg: string) => this.getEmptyStateHtml(icon, msg),
      safeText: (s: string) => this.safeText(s),
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
      renderIssueLink: (key: string) => this.renderIssueLink(key),
      renderIssueLinks: (keys: string[]) => this.renderIssueLinks(keys),
    };
  }

  private getIssuesHelpers() {
    return {
      escapeHtml: (s: string) => this.escapeHtml(s),
      getEmptyStateHtml: (icon: string, msg: string) => this.getEmptyStateHtml(icon, msg),
      safeText: (s: string) => this.safeText(s),
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
      renderIssueLink: (key: string) => this.renderIssueLink(key),
      renderIssueLinks: (keys: string[]) => this.renderIssueLinks(keys),
      getTypeIcon: (type: string) => this.getTypeIcon(type),
    };
  }

  private getMindmapHelpers() {
    return {
      getEffectivePercentage: (compId: string) => this.getEffectivePercentage(compId),
      getEffectiveOverall: () => this.getEffectiveOverall(),
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
      escapeHtml: (s: string) => this.escapeHtml(s),
      getEmptyStateHtml: (icon: string, msg: string) => this.getEmptyStateHtml(icon, msg),
    };
  }

  private getCompetenciesHelpers() {
    return {
      getEffectivePercentage: (compId: string) => this.getEffectivePercentage(compId),
      getEffectiveOverall: () => this.getEffectiveOverall(),
      formatCompetencyName: (id: string) => this.formatCompetencyName(id),
      escapeHtml: (s: string) => this.escapeHtml(s),
      getEmptyStateHtml: (icon: string, msg: string) => this.getEmptyStateHtml(icon, msg),
      renderIssueLink: (key: string) => this.renderIssueLink(key),
      renderIssueLinks: (keys: string[]) => this.renderIssueLinks(keys),
      safeText: (s: string) => this.safeText(s),
    };
  }

  // ============================================================
  // Styles & Scripts
  // ============================================================

  getStyles(): string {
    return "";
  }

  getScript(): string {
    return getPerformanceScript();
  }

  // ============================================================
  // Settings & Refresh (used by performanceActions)
  // ============================================================

  private _settingsRenderTimer: ReturnType<typeof setTimeout> | null = null;
  private deferredSettingsRender(): void {
    if (this._settingsRenderTimer) {
      clearTimeout(this._settingsRenderTimer);
    }
    this._settingsRenderTimer = null;
    this.invalidateFingerprint();
    this.notifyNeedsRender();
  }

  private debouncedSaveScoringConfig(delayMs: number = 1500): void {
    if (this._scoringSaveTimer) {
      clearTimeout(this._scoringSaveTimer);
    }
    this._scoringSaveTimer = setTimeout(() => {
      this._scoringSaveTimer = null;
      this.saveScoringConfig();
    }, delayMs);
  }

  private async saveScoringConfig(): Promise<void> {
    if (!this.state.scoring_config) return;
    try {
      const cfg = this.state.scoring_config;
      const payload: Record<string, unknown> = {
        min_signals: cfg.min_signals,
        daily_cap: cfg.daily_cap,
        target_per_competency: cfg.target_per_competency,
        engineering_level: cfg.engineering_level || "sse",
        competencies: {} as Record<string, unknown>,
      };
      if (cfg.scope_multipliers) {
        payload.scope_multipliers = cfg.scope_multipliers;
      }
      if (cfg.level_weights) {
        const lw = cfg.level_weights;
        if (lw.role_weights || lw.pillar_weights) {
          payload.level_weight_overrides = {
            role_weights: lw.role_weights,
            pillar_weights: lw.pillar_weights,
          };
        }
      }
      if (cfg.strategy_alignment) {
        payload.strategy_alignment = cfg.strategy_alignment;
      }
      if (cfg.npu_settings) {
        payload.npu_settings = cfg.npu_settings;
      }
      for (const [id, comp] of Object.entries(cfg.competencies)) {
        (payload.competencies as Record<string, unknown>)[id] = {
          base_points: comp.base_points,
          phrases: comp.phrases,
          keywords: comp.keywords,
          event_types: comp.event_types,
        };
      }
      const result = await dbus.stats_setScoringConfig(payload);
      if (result.success) {
        this._settingsDirty = true;
        this.schedulePostSaveRefresh();
        if (this._pendingLevelRefresh) {
          this._pendingLevelRefresh = false;
          this.deferredSettingsRefresh();
        }
      } else {
        vscode.window.showErrorMessage(`Failed to save config: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error saving config: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private schedulePostSaveRefresh(): void {
    if (this._postSaveRefreshTimer) {
      clearTimeout(this._postSaveRefreshTimer);
    }
    this._postSaveRefreshTimer = setTimeout(async () => {
      this._postSaveRefreshTimer = null;
      await this.refreshPreservingUIState();
    }, 300);
  }

  private deferredSettingsRefresh(): void {
    if (this._settingsRefreshTimer) {
      clearTimeout(this._settingsRefreshTimer);
    }
    this._settingsRefreshTimer = setTimeout(async () => {
      this._settingsRefreshTimer = null;
      try {
        const cfgResult = await dbus.stats_getScoringConfig();
        if (cfgResult.success && cfgResult.data) {
          this.state.scoring_config = (cfgResult.data as any).config || null;
          this.invalidateFingerprint();
          this.notifyNeedsRender();
        }
      } catch {
        // Silently ignore - user can manually refresh
      }
    }, 1000);
  }

  private async refreshPreservingUIState(): Promise<void> {
    const savedTab = this.state.active_tab;
    const savedConfigExpanded = this.state.scoring_config_expanded;
    const savedCompExpanded = this.state.scoring_comp_expanded;
    const savedExpandedCompetency = this.state.expanded_competency;
    const savedDate = this.state.selected_date;

    await this.refresh();

    this.state.active_tab = savedTab;
    this.state.scoring_config_expanded = savedConfigExpanded;
    this.state.scoring_comp_expanded = savedCompExpanded;
    this.state.expanded_competency = savedExpandedCompetency;
    this.state.selected_date = savedDate;
    this.notifyNeedsRender();
  }

  // ============================================================
  // Message Handling
  // ============================================================

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "performanceDataUpdate":
        if (message.data) {
          this.state = { ...this.state, ...message.data };
        }
        this.notifyNeedsRender();
        return true;

      case "performanceAction":
        await this.handlePerformanceAction(message.action, message);
        return true;

      case "switchHeatmapMode":
      case "switchPeerComparisonMode":
      case "switchEventVolumeMode":
      case "toggleSessionEnrichment":
        await this.handlePerformanceAction(msgType, message);
        return true;

      default:
        return false;
    }
  }

  private getActionContext(): ActionContext {
    const self = this;
    return {
      get state() { return self.state; },
      set state(v) { self.state = v; },
      notifyNeedsRender: () => this.notifyNeedsRender(),
      postMessageToWebview: (msg: any) => this.postMessageToWebview(msg),
      refresh: () => this.refresh(),
      refreshPreservingUIState: () => this.refreshPreservingUIState(),
      debouncedSaveScoringConfig: (delay?: number) => this.debouncedSaveScoringConfig(delay),
      deferredSettingsRender: () => this.deferredSettingsRender(),
      escapeHtml: (s: string) => this.escapeHtml(s),
      safeText: (s: string) => this.safeText(s),
      get forceNextRender() { return self.forceNextRender; },
      set forceNextRender(v) { self.forceNextRender = v; },
      get _settingsDirty() { return self._settingsDirty; },
      set _settingsDirty(v) { self._settingsDirty = v; },
      get _settingsRefreshTimer() { return self._settingsRefreshTimer; },
      set _settingsRefreshTimer(v) { self._settingsRefreshTimer = v; },
      get _expandedQuestions() { return self._expandedQuestions; },
      get _questionEvidence() { return self._questionEvidence; },
      get _questionEvidenceLoading() { return self._questionEvidenceLoading; },
      get _excludedEvidence() { return self._excludedEvidence; },
      get _backfillPollInterval() { return (self as any)._backfillPollInterval; },
      set _backfillPollInterval(v) { (self as any)._backfillPollInterval = v; },
      get _backfillEverRanning() { return (self as any)._backfillEverRanning ?? false; },
      set _backfillEverRanning(v) { (self as any)._backfillEverRanning = v; },
    };
  }

  private async handlePerformanceAction(action: string, message: any): Promise<boolean> {
    return handlePerformanceActionDispatch(this.getActionContext(), action, message);
  }
}
