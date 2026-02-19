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

const logger = createLogger("PerformanceTab");

// ============================================================
// Interfaces
// ============================================================

interface CompetencyScore {
  points: number;
  percentage: number;
}

interface QuestionSummary {
  id: string;
  text: string;
  evidence_count: number;
  notes_count: number;
  has_summary: boolean;
  last_evaluated: string | null;
}

interface CapturedDay {
  date: string;
  event_count: number;
  total_points: number;
  sources: string[];
  category_points: Record<string, number>;
}

interface CoverageInfo {
  total_weekdays: number;
  captured: number;
  percentage: number;
}

interface IssueNode {
  key: string;
  summary: string;
  type: string;
  points: number;
  event_count: number;
  keywords: string[];
  children: IssueNode[];
}

interface IssueHierarchy {
  strategies: IssueNode[];
  unattached_epics: IssueNode[];
  uncategorized: IssueNode[];
  total_issues: number;
  cached: boolean;
}

interface IssueLineageEntry {
  key: string;
  summary: string;
  epic?: { key: string; summary: string };
  anstrat?: { key: string; summary: string };
}

interface DayEvent {
  id: string;
  source: string;
  type: string;
  item_id: string;
  title: string;
  timestamp: string;
  points: Record<string, number>;
  issue_keys?: string[];
  lineage?: IssueLineageEntry[];
}

interface DayDetail {
  date: string;
  events: DayEvent[];
  daily_points: Record<string, number>;
  daily_total: number;
  category_points: Record<string, number>;
  has_data: boolean;
}

interface CompetencyEvidence {
  date: string;
  title: string;
  source: string;
  type: string;
  points: number;
  issue_keys: string[];
  url?: string;
  match_reason?: string;
}

interface CompetencyMeta {
  name: string;
  category: string;
  goal: string;
  description: string;
  percentage: number;
  points: number;
  target: number;
  evidence_count: number;
}

interface GapSuggestion {
  percentage: number;
  points: number;
  target: number;
  deficit: number;
  suggestions: string[];
  evidence_count: number;
  goal?: string;
  description?: string;
  category?: string;
}

interface StrategyAlignmentPriority {
  name: string;
  context: string;
  status: "covered" | "gap";
  pillar: string;
  issue_keys: string[];
  matched_user_issues: string[];
  matched_mrs: string[];
  senders: string[];
}

interface StrategyAlignment {
  emails_loaded: number;
  senders: string[];
  priorities: StrategyAlignmentPriority[];
  themes: { name: string; matched_keywords: string[]; strength: number }[];
  pillar_summary: Record<string, { competency_points: number; priority_count: number; covered: number; gaps: number }>;
  coverage_summary: { total_priorities: number; covered: number; gaps: number; coverage_pct: number };
  user_work_summary?: { jira_issues: number; gitlab_mrs: number };
}

interface PerformanceState {
  last_updated: string;
  quarter: string;
  day_of_quarter: number;
  overall_percentage: number;
  competencies: Record<string, CompetencyScore>;
  highlights: string[];
  gaps: string[];
  questions_summary?: QuestionSummary[];
  captured_days: CapturedDay[];
  coverage: CoverageInfo;
  issue_hierarchy: IssueHierarchy | null;
  selected_date: string | null;
  calendar_month: number;
  calendar_year: number;
  active_tab: string;
  day_detail: DayDetail | null;
  competency_evidence: Record<string, CompetencyEvidence[]>;
  competency_meta: Record<string, CompetencyMeta>;
  gap_suggestions: Record<string, GapSuggestion>;
  expanded_competency: string | null;
  scoring_config: ScoringConfig | null;
  scoring_config_expanded: boolean;
  scoring_comp_expanded: string | null;
  strategy_alignment: StrategyAlignment | null;
}

interface ScoringCompConfig {
  base_points: number;
  phrases: string[];
  keywords: string[];
  event_types: string[];
  name: string;
  category: string;
}

interface ScoringConfig {
  min_signals: number;
  daily_cap: number;
  target_per_competency: number;
  competencies: Record<string, ScoringCompConfig>;
}

// ============================================================
// PerformanceTab
// ============================================================

export class PerformanceTab extends BaseTab {
  private state: PerformanceState = {
    last_updated: new Date().toISOString(),
    quarter: this.getCurrentQuarter(),
    day_of_quarter: this.getDayOfQuarter(),
    overall_percentage: 0,
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
  };

  constructor() {
    super({
      id: "performance",
      label: "QC",
      icon: "\u{1F4CA}",
    });
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
      // Load performance state from stats daemon
      const result = await dbus.stats_getState();
      if (result.success && result.data) {
        const statsState = result.data.state;
        if (statsState?.performance) {
          this.state = {
            ...this.state,
            ...statsState.performance,
          };
          logger.info(`Loaded performance data: ${this.state.overall_percentage}%`);
        } else {
          logger.warn("No performance data in stats state");
        }
      }

      // Load captured days for calendar
      try {
        const capturedResult = await dbus.stats_getCapturedDays();
        if (capturedResult.success && capturedResult.data) {
          const data = capturedResult.data as any;
          this.state.captured_days = Array.isArray(data.days) ? data.days : [];
          this.state.coverage = data.coverage || this.state.coverage;
        }
      } catch (e) {
        logger.warn(`Failed to load captured days: ${e}`);
      }

      // Load issue hierarchy (from cache, no Jira refresh)
      try {
        const hierarchyResult = await dbus.stats_getIssueHierarchy(false);
        if (hierarchyResult.success && hierarchyResult.data) {
          const raw = hierarchyResult.data as any;
          this.state.issue_hierarchy = {
            strategies: Array.isArray(raw.strategies) ? raw.strategies : [],
            unattached_epics: Array.isArray(raw.unattached_epics) ? raw.unattached_epics : [],
            uncategorized: Array.isArray(raw.uncategorized) ? raw.uncategorized : [],
            total_issues: raw.total_issues || 0,
            cached: raw.cached || false,
          };
        }
      } catch (e) {
        logger.warn(`Failed to load issue hierarchy: ${e}`);
      }

      // Load competency evidence (for Competencies tab)
      try {
        const evidenceResult = await dbus.stats_getCompetencyEvidence();
        if (evidenceResult.success && evidenceResult.data) {
          const raw = evidenceResult.data as any;
          this.state.competency_evidence = raw.competency_evidence || {};
          this.state.competency_meta = raw.competency_meta || {};
          this.state.gap_suggestions = raw.gap_suggestions || {};
        }
      } catch (e) {
        logger.warn(`Failed to load competency evidence: ${e}`);
      }

      // Load scoring config (for Competencies settings panel)
      try {
        const cfgResult = await dbus.stats_getScoringConfig();
        if (cfgResult.success && cfgResult.data) {
          this.state.scoring_config = (cfgResult.data as any).config || null;
        }
      } catch (e) {
        logger.warn(`Failed to load scoring config: ${e}`);
      }

      // Strategy alignment is loaded from the summary via stats_getState
      // (summary.strategy_alignment is spread into this.state above)
      // Ensure it's populated from the state data
      if (this.state.strategy_alignment === undefined) {
        this.state.strategy_alignment = null;
      }
    } catch (error) {
      logger.error("Error loading data", error);
    }
  }

  // ============================================================
  // Main Content
  // ============================================================

  getContent(): string {
    const quarterProgress = Math.round((this.state.day_of_quarter / 90) * 100);
    const tab = this.state.active_tab;

    const tabs = [
      { id: "overview", label: "Overview", icon: "\u{1F4CA}" },
      { id: "calendar", label: "Calendar", icon: "\u{1F4C5}" },
      { id: "issues", label: "Issues", icon: "\u{1F4CB}" },
      { id: "mindmap", label: "Mindmap", icon: "\u{1F578}\uFE0F" },
      { id: "competencies", label: "Competencies", icon: "\u{1F3AF}" },
      { id: "progress", label: "Progress", icon: "\u{2705}" },
      { id: "settings", label: "Settings", icon: "\u2699\uFE0F" },
      { id: "log", label: "Log", icon: "\u{270F}\uFE0F" },
    ];

    const tabBar = tabs.map(t =>
      `<button class="perf-tab${t.id === tab ? " perf-tab--active" : ""}" data-action="switchTab" data-key="${t.id}">${t.icon} ${t.label}</button>`
    ).join("");

    return `
      <!-- Compact Header -->
      <div class="perf-header">
        <div class="perf-header-info">
          <div class="perf-title">${this.escapeHtml(this.state.quarter)} Quarterly Connection</div>
          <div class="perf-subtitle">Day ${this.state.day_of_quarter} of 90 &middot; ${this.state.overall_percentage}% overall &middot; ${this.state.coverage.captured}/${this.state.coverage.total_weekdays} days captured</div>
        </div>
        <div class="perf-header-stats">
          <div class="perf-header-actions">
            <button class="btn btn-xs" data-action="collectDaily" title="Collect today's data">Collect Today</button>
            <button class="btn btn-xs" data-action="backfill" title="Backfill missing days">Backfill</button>
            <button class="btn btn-xs" data-action="exportReport" title="Export quarterly report">Export</button>
          </div>
          <div class="perf-quarter-progress">
            <div class="progress-bar">
              <div class="progress-fill" style="width: ${quarterProgress}%;"></div>
            </div>
            <span class="perf-progress-text">${quarterProgress}%</span>
          </div>
        </div>
      </div>

      <!-- Tab Bar -->
      <div class="perf-tab-bar">${tabBar}</div>

      <!-- Tab Panels -->
      <div class="perf-tab-panels">
        ${tab === "overview" ? this.renderOverviewTab() : ""}
        ${tab === "calendar" ? this.renderCalendarTab() : ""}
        ${tab === "issues" ? this.renderIssuesTab() : ""}
        ${tab === "mindmap" ? this.renderMindmapTab() : ""}
        ${tab === "competencies" ? this.renderCompetenciesTab() : ""}
        ${tab === "progress" ? this.renderProgressTab() : ""}
        ${tab === "settings" ? this.renderSettingsTab() : ""}
        ${tab === "log" ? this.renderLogTab() : ""}
      </div>
    `;
  }

  // ============================================================
  // Tab Content Renderers
  // ============================================================

  private renderOverviewTab(): string {
    const align = this.state.strategy_alignment;
    const coveragePct = align?.coverage_summary?.coverage_pct ?? 0;
    const coverageColor = coveragePct >= 70 ? "#10b981" : coveragePct >= 40 ? "#f59e0b" : "#ef4444";

    const quickStatsHtml = `
      <div class="grid-4">
        <div class="stat-card">
          <div class="stat-value">${this.state.overall_percentage}%</div>
          <div class="stat-label">Overall Score</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${this.state.coverage.captured}</div>
          <div class="stat-label">Days Captured</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${this.state.issue_hierarchy?.total_issues || 0}</div>
          <div class="stat-label">Issues Tracked</div>
        </div>
        <div class="stat-card" style="border-color: ${coverageColor}33;">
          <div class="stat-value" style="color: ${coverageColor};">${coveragePct}%</div>
          <div class="stat-label">Strategy Coverage</div>
        </div>
      </div>
    `;

    // Pillar summary cards
    const pillarColors: Record<string, string> = {
      "Technical Excellence": "#58a6ff",
      "Leadership & Influence": "#f0883e",
      "Delivery & Impact": "#3fb950",
    };
    const pillarIcons: Record<string, string> = {
      "Technical Excellence": "\u{1F527}",
      "Leadership & Influence": "\u{1F310}",
      "Delivery & Impact": "\u{1F680}",
    };
    const pillarData = align?.pillar_summary || {};
    let pillarHtml = `<div class="section"><div class="section-title">Competency Pillars &amp; Strategy Alignment</div><div class="grid-3">`;
    for (const [pname, color] of Object.entries(pillarColors)) {
      const pd = pillarData[pname] || { competency_points: 0, priority_count: 0, covered: 0, gaps: 0 };
      const icon = pillarIcons[pname] || "";
      const catComps = Object.entries(this.state.competencies).filter(([id]) => {
        const meta = this.state.competency_meta[id];
        return meta?.category === pname;
      });
      const avgPct = catComps.length > 0
        ? Math.round(catComps.reduce((s, [, c]) => s + c.percentage, 0) / catComps.length)
        : 0;

      pillarHtml += `
        <div class="card" style="border-top: 3px solid ${color}; text-align: center;">
          <div class="card-header" style="justify-content: center;">
            <span>${icon}</span>
            <span class="card-title">${this.escapeHtml(pname)}</span>
          </div>
          <div class="stat-value" style="color: ${color}; font-size: 1.8rem;">${avgPct}%</div>
          <div class="progress-bar my-12">
            <div class="progress-fill" style="width: ${Math.min(avgPct, 100)}%; background: ${color};"></div>
          </div>
          <div class="text-secondary text-sm">
            <span>${pd.competency_points} pts</span> &middot;
            <span>${pd.priority_count} exec priorities</span> &middot;
            <span>${pd.covered} covered</span>
          </div>
        </div>
      `;
    }
    pillarHtml += `</div></div>`;

    // Strategy alignment priorities
    let strategyHtml = "";
    if (align && align.priorities.length > 0) {
      strategyHtml += `<div class="section"><div class="section-title">Executive Strategy Alignment</div>`;
      strategyHtml += `<div class="progress-bar">`;
      strategyHtml += `<div class="progress-fill" style="width: ${coveragePct}%; background: ${coverageColor};"></div>`;
      strategyHtml += `</div>`;
      strategyHtml += `<div class="overview-alignment-stats">`;
      strategyHtml += `<span>${align.coverage_summary.covered} of ${align.coverage_summary.total_priorities} priorities covered</span>`;
      strategyHtml += `<span>${align.emails_loaded} executive emails processed</span>`;
      if (align.senders.length > 0) {
        strategyHtml += `<span>From: ${align.senders.map(s => this.escapeHtml(s)).join(", ")}</span>`;
      }
      const uws = align.user_work_summary;
      if (uws) {
        strategyHtml += `<span>Aligned against: ${uws.jira_issues} Jira issues &amp; ${uws.gitlab_mrs} GitLab MRs</span>`;
      }
      strategyHtml += `</div>`;

      strategyHtml += `<div class="overview-priorities">`;
      for (const prio of align.priorities) {
        const statusClass = prio.status === "covered" ? "overview-prio-covered" : "overview-prio-gap";
        const statusIcon = prio.status === "covered" ? "\u2705" : "\u26A0\uFE0F";
        const pillarColor = pillarColors[prio.pillar] || "#888";
        const issueLinks = prio.matched_user_issues.map(k => this.renderIssueLink(k)).join(" ");
        const mrLinks = (prio.matched_mrs || []).map(m => `<span class="overview-mr-badge">${this.escapeHtml(m)}</span>`).join(" ");
        const allMatches = [issueLinks, mrLinks].filter(Boolean).join(" ");

        strategyHtml += `
          <div class="overview-priority ${statusClass}">
            <div class="overview-priority-header">
              <span class="overview-priority-status">${statusIcon}</span>
              <span class="overview-priority-name">${this.escapeHtml(prio.name)}</span>
              <span class="overview-priority-pillar" style="background: ${pillarColor}22; color: ${pillarColor}; border: 1px solid ${pillarColor}44;">${this.escapeHtml(prio.pillar)}</span>
            </div>
            ${prio.context ? `<div class="overview-priority-context">${this.escapeHtml(prio.context.substring(0, 150))}</div>` : ""}
            ${allMatches ? `<div class="overview-priority-matches">${allMatches}</div>` : `<div class="overview-priority-gap-msg">No matching deliverables</div>`}
          </div>
        `;
      }
      strategyHtml += `</div></div>`;

      // Gaps alert
      const gapPrios = align.priorities.filter(p => p.status === "gap");
      if (gapPrios.length > 0) {
        strategyHtml += `<div class="section"><div class="section-title">Strategy Gaps (${gapPrios.length})</div>`;
        strategyHtml += `<div class="grid-auto">`;
        for (const g of gapPrios) {
          strategyHtml += `
            <div class="card">
              <div class="card-title">${this.escapeHtml(g.name)}</div>
              <div class="text-secondary text-sm">${this.escapeHtml(g.pillar)}</div>
              <div class="text-secondary text-sm" style="margin-top: 4px;">Consider aligning work to this executive priority</div>
            </div>
          `;
        }
        strategyHtml += `</div></div>`;
      }
    } else {
      strategyHtml = `
        <div class="section">
          <div class="section-title">Executive Strategy Alignment</div>
          <div class="empty-state">
            <div class="empty-state-text">No executive emails collected yet. Use the Backfill button above to fetch emails for the quarter, or wait for the daily collection to capture them automatically.</div>
          </div>
        </div>
      `;
    }

    return `
      <div class="perf-tab-panel">
        ${quickStatsHtml}
        ${pillarHtml}
        ${strategyHtml}
      </div>
    `;
  }

  private renderCalendarTab(): string {
    return `
      <div class="perf-tab-panel">
        <!-- Calendar -->
        <div class="section">
          <div class="section-title">
            <span>Data Coverage</span>
            <span class="perf-coverage-badge">${this.state.coverage.captured} of ${this.state.coverage.total_weekdays} days (${this.state.coverage.percentage}%)</span>
          </div>
          ${this.renderCalendar()}
        </div>

        <!-- Day Detail (shown when a day is clicked) -->
        ${this.renderDayDetail()}
      </div>
    `;
  }

  private renderIssuesTab(): string {
    return `
      <div class="perf-tab-panel">
        <div class="section">
          <div class="section-title">
            <span>Delivered Issues</span>
            <button class="btn btn-xs" data-action="refreshHierarchy">Refresh from Jira</button>
          </div>
          ${this.renderIssueHierarchy()}
        </div>
      </div>
    `;
  }

  private renderMindmapTab(): string {
    return `
      <div class="perf-tab-panel">
        <div class="section">
          <div class="section-title">Issue Mindmap</div>
          <div class="perf-mindmap-container">
            ${this.renderMindmap()}
          </div>
        </div>
      </div>
    `;
  }

  private renderCompetenciesTab(): string {
    return `
      <div class="perf-tab-panel">
        <!-- Sunburst -->
        <div class="section">
          <div class="section-title">Competency Sunburst</div>
          <div class="perf-sunburst-container">
            ${this.generateSunburstSVG()}
          </div>
        </div>

        <!-- Expandable Competency Bars -->
        <div class="section">
          <div class="section-title">Competency Scores (click to expand)</div>
          ${this.renderExpandableCompetencyBars()}
        </div>

        <!-- Gap Suggestions -->
        ${this.renderGapsWithSuggestions()}
      </div>
    `;
  }

  private renderSettingsTab(): string {
    const cfg = this.state.scoring_config;
    if (!cfg) {
      return `<div class="perf-tab-panel"><div class="section"><p>Loading scoring configuration...</p></div></div>`;
    }

    const categories: Record<string, [string, ScoringCompConfig][]> = {};
    for (const [id, comp] of Object.entries(cfg.competencies)) {
      const cat = comp.category || "Other";
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push([id, comp]);
    }

    const knownEventTypes = [
      "commit", "mr_merged", "pr_merged", "pr_opened",
      "pr_reviewed", "issue_resolved", "issue_created",
      "issue_opened", "issue_closed", "review_given",
    ];

    let compCards = "";
    for (const [category, entries] of Object.entries(categories)) {
      compCards += `<div class="scoring-category-label">${this.escapeHtml(category)}</div>`;
      for (const [compId, comp] of entries) {
        const compExpanded = this.state.scoring_comp_expanded === compId;
        const compIcon = compExpanded ? "\u25BC" : "\u25B6";
        compCards += `
          <div class="scoring-comp-card${compExpanded ? " expanded" : ""}">
            <div class="scoring-comp-header" data-action="toggleScoringComp" data-key="${this.escapeHtml(compId)}">
              <span class="scoring-comp-icon">${compIcon}</span>
              <span class="scoring-comp-name">${this.escapeHtml(comp.name)}</span>
              <span class="scoring-comp-pts">${comp.base_points} pts</span>
            </div>
        `;

        if (compExpanded) {
          compCards += `
            <div class="scoring-comp-body" data-comp="${this.escapeHtml(compId)}">
              <div class="scoring-field-row">
                <label>Base Points</label>
                <input type="number" class="scoring-input scoring-comp-input"
                       data-comp="${this.escapeHtml(compId)}" data-field="base_points"
                       value="${comp.base_points}" min="1" max="10" />
              </div>

              <div class="scoring-field-row">
                <label>Event Types</label>
                <div class="scoring-chips">
                  ${knownEventTypes.map(et => {
                    const active = comp.event_types.includes(et);
                    return `<span class="scoring-chip${active ? " active" : ""}"
                                  data-action="toggleEventType" data-comp="${this.escapeHtml(compId)}"
                                  data-value="${this.escapeHtml(et)}">${this.escapeHtml(et)}</span>`;
                  }).join("")}
                </div>
              </div>

              <div class="scoring-field-row">
                <label>Phrases</label>
                <div class="scoring-tags">
                  ${comp.phrases.map(p =>
                    `<span class="scoring-tag">${this.escapeHtml(p)}<span class="scoring-tag-x"
                      data-action="removePhrase" data-comp="${this.escapeHtml(compId)}"
                      data-value="${this.escapeHtml(p)}">&times;</span></span>`
                  ).join("")}
                  <input type="text" class="scoring-tag-input" placeholder="+ add phrase"
                         data-action="addPhrase" data-comp="${this.escapeHtml(compId)}" />
                </div>
              </div>

              <div class="scoring-field-row">
                <label>Keywords</label>
                <div class="scoring-tags">
                  ${comp.keywords.map(k =>
                    `<span class="scoring-tag">${this.escapeHtml(k)}<span class="scoring-tag-x"
                      data-action="removeKeyword" data-comp="${this.escapeHtml(compId)}"
                      data-value="${this.escapeHtml(k)}">&times;</span></span>`
                  ).join("")}
                  <input type="text" class="scoring-tag-input" placeholder="+ add keyword"
                         data-action="addKeyword" data-comp="${this.escapeHtml(compId)}" />
                </div>
              </div>
            </div>
          `;
        }
        compCards += `</div>`;
      }
    }

    return `
      <div class="perf-tab-panel">
        <div class="section scoring-settings">
          <div class="section-title">Global Scoring Parameters</div>
          <div class="scoring-globals">
            <div class="scoring-global-field">
              <label>Min Signals</label>
              <input type="number" class="scoring-input" data-field="min_signals"
                     value="${cfg.min_signals}" min="1" max="5" />
              <span class="scoring-hint">Matches needed per event</span>
            </div>
            <div class="scoring-global-field">
              <label>Daily Cap</label>
              <input type="number" class="scoring-input" data-field="daily_cap"
                     value="${cfg.daily_cap}" min="1" max="50" />
              <span class="scoring-hint">Max pts per competency/day</span>
            </div>
            <div class="scoring-global-field">
              <label>Quarter Target</label>
              <input type="number" class="scoring-input" data-field="target_per_competency"
                     value="${cfg.target_per_competency}" min="10" max="500" />
              <span class="scoring-hint">Points for 100%</span>
            </div>
          </div>
        </div>

        <div class="section scoring-settings">
          <div class="section-title">Per-Competency Configuration</div>
          ${compCards}
        </div>

        <div class="scoring-actions">
          <button class="btn btn-sm btn-primary" data-action="saveScoringConfig">Save &amp; Re-evaluate</button>
          <button class="btn btn-sm" data-action="resetScoringConfig">Reset to Defaults</button>
        </div>
      </div>
    `;
  }

  private renderProgressTab(): string {
    return `
      <div class="perf-tab-panel">
        <!-- Quarterly Questions -->
        <div class="section">
          <div class="section-title">
            <span>Quarterly Questions</span>
            <button class="btn btn-xs" data-action="evaluateAll">Re-evaluate All</button>
          </div>
          ${this.renderQuestions()}
        </div>

        <!-- Highlights -->
        <div class="section">
          <div class="section-title">Recent Highlights</div>
          ${this.renderHighlights()}
        </div>
      </div>
    `;
  }

  private renderLogTab(): string {
    return `
      <div class="perf-tab-panel">
        <div class="section">
          <div class="section-title">Log Manual Activity</div>
          <div class="perf-manual-form">
            <select class="perf-select" id="activityCategory">
              <option value="speaking">Speaking</option>
              <option value="presentation">Presentation</option>
              <option value="demo">Demo</option>
              <option value="mentorship">Mentorship</option>
              <option value="blog">Blog Post</option>
              <option value="other">Other</option>
            </select>
            <input type="text" id="activityDescription" placeholder="Description of activity..." />
            <button class="btn btn-sm btn-primary" data-action="logActivity">Log</button>
          </div>
        </div>
      </div>
    `;
  }

  // ============================================================
  // Calendar
  // ============================================================

  private renderCalendar(): string {
    const month = this.state.calendar_month;
    const year = this.state.calendar_year;

    const monthNames = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];

    const capturedSet = new Map<string, CapturedDay>();
    for (const day of this.state.captured_days) {
      capturedSet.set(day.date, day);
    }

    const currentQuarter = Math.floor(month / 3);
    const quarterStartMonth = currentQuarter * 3;
    const quarterEndMonth = quarterStartMonth + 2;

    const canGoPrev = month > quarterStartMonth;
    const canGoNext = month < quarterEndMonth;

    const firstDay = new Date(year, month, 1);
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const startWeekday = firstDay.getDay();

    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

    let html = `
      <div class="perf-calendar">
        <div class="perf-calendar-nav">
          <button class="btn btn-xs ${canGoPrev ? "" : "disabled"}" data-action="prevMonth" ${canGoPrev ? "" : "disabled"}>&#9664;</button>
          <span class="perf-calendar-month">${monthNames[month]} ${year}</span>
          <button class="btn btn-xs ${canGoNext ? "" : "disabled"}" data-action="nextMonth" ${canGoNext ? "" : "disabled"}>&#9654;</button>
        </div>
        <div class="perf-calendar-grid">
          <div class="perf-calendar-header">Mon</div>
          <div class="perf-calendar-header">Tue</div>
          <div class="perf-calendar-header">Wed</div>
          <div class="perf-calendar-header">Thu</div>
          <div class="perf-calendar-header">Fri</div>
    `;

    let mondayOffset = startWeekday === 0 ? 6 : startWeekday - 1;
    for (let i = 0; i < Math.min(mondayOffset, 5); i++) {
      html += `<div class="perf-calendar-day empty"></div>`;
    }

    for (let d = 1; d <= daysInMonth; d++) {
      const dateObj = new Date(year, month, d);
      const weekday = dateObj.getDay();
      if (weekday === 0 || weekday === 6) continue;

      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const captured = capturedSet.get(dateStr);
      const isToday = dateStr === todayStr;
      const isFuture = dateObj > today;
      const isSelected = dateStr === this.state.selected_date;

      let classes = "perf-calendar-day";
      if (captured) classes += " captured";
      else if (!isFuture) classes += " missing";
      if (isToday) classes += " today";
      if (isFuture) classes += " future";
      if (isSelected) classes += " selected";

      const dot = captured
        ? `<span class="perf-calendar-dot captured"></span>`
        : (!isFuture ? `<span class="perf-calendar-dot missing"></span>` : "");

      let eventInfo = "";
      if (captured) {
        const cp = captured.category_points || {};
        const tech = cp["Technical Excellence"] || 0;
        const lead = cp["Leadership & Influence"] || 0;
        const deliv = cp["Delivery & Impact"] || 0;
        const maxCat = Math.max(tech, lead, deliv, 1);
        eventInfo = `
          <div class="perf-cal-cats">
            <div class="perf-cal-cat-bar" title="Technical: ${tech}pts" style="height:${Math.round(tech / maxCat * 12)}px; background:#58a6ff;"></div>
            <div class="perf-cal-cat-bar" title="Leadership: ${lead}pts" style="height:${Math.round(lead / maxCat * 12)}px; background:#f0883e;"></div>
            <div class="perf-cal-cat-bar" title="Delivery: ${deliv}pts" style="height:${Math.round(deliv / maxCat * 12)}px; background:#3fb950;"></div>
          </div>
          <span class="perf-calendar-events">${captured.total_points}pts</span>
        `;
      }

      html += `
        <div class="${classes}" data-action="selectDay" data-date="${dateStr}">
          <span class="perf-calendar-num">${d}</span>
          ${dot}
          ${eventInfo}
        </div>
      `;
    }

    html += `</div></div>`;
    return html;
  }

  // ============================================================
  // Day Detail (enriched with event table and Jira links)
  // ============================================================

  private renderDayDetail(): string {
    if (!this.state.selected_date) return "";

    const day = this.state.captured_days.find((d) => d.date === this.state.selected_date);
    const detail = this.state.day_detail;

    if (!day) {
      return `
        <div class="section perf-day-detail">
          <div class="section-title">
            <span>${this.state.selected_date}</span>
            <button class="btn btn-xs" data-action="closeDay">Close</button>
          </div>
          <div class="empty-state">
            <div class="empty-state-icon">--</div>
            <div class="empty-state-text">No data captured for this day.</div>
          </div>
        </div>
      `;
    }

    // Category breakdown
    const cp = detail?.category_points || day.category_points || {};
    const tech = cp["Technical Excellence"] || 0;
    const lead = cp["Leadership & Influence"] || 0;
    const deliv = cp["Delivery & Impact"] || 0;

    let html = `
      <div class="section perf-day-detail">
        <div class="section-title">
          <span>${this.state.selected_date}</span>
          <button class="btn btn-xs" data-action="closeDay">Close</button>
        </div>
        <div class="perf-day-stats">
          <div class="perf-day-stat">
            <span class="perf-day-stat-value">${day.event_count}</span>
            <span class="perf-day-stat-label">Events</span>
          </div>
          <div class="perf-day-stat">
            <span class="perf-day-stat-value">${day.total_points}</span>
            <span class="perf-day-stat-label">Points</span>
          </div>
          <div class="perf-day-stat">
            <span class="perf-day-stat-value">${day.sources.join(", ") || "none"}</span>
            <span class="perf-day-stat-label">Sources</span>
          </div>
        </div>
        <div class="perf-day-categories">
          <div class="perf-day-cat"><span class="perf-day-cat-dot" style="background:#58a6ff;"></span> Technical ${tech}pts</div>
          <div class="perf-day-cat"><span class="perf-day-cat-dot" style="background:#f0883e;"></span> Leadership ${lead}pts</div>
          <div class="perf-day-cat"><span class="perf-day-cat-dot" style="background:#3fb950;"></span> Delivery ${deliv}pts</div>
        </div>
    `;

    // Event list with lineage
    if (detail && detail.has_data && detail.events.length > 0) {
      html += `<div class="perf-day-events">`;
      for (const ev of detail.events) {
        const pts = Object.values(ev.points || {}).reduce((a: number, b: number) => a + b, 0);

        // Build lineage breadcrumbs
        let lineageHtml = "";
        if (ev.lineage && ev.lineage.length > 0) {
          const crumbs: string[] = [];
          for (const lin of ev.lineage) {
            const parts: string[] = [];
            if (lin.anstrat) {
              parts.push(`<a class="perf-issue-link perf-lineage-anstrat" href="#" data-action="openIssue" data-key="${this.escapeHtml(lin.anstrat.key)}" title="${this.escapeHtml(lin.anstrat.summary)}">${this.escapeHtml(lin.anstrat.key)}</a>`);
            }
            if (lin.epic) {
              parts.push(`<a class="perf-issue-link perf-lineage-epic" href="#" data-action="openIssue" data-key="${this.escapeHtml(lin.epic.key)}" title="${this.escapeHtml(lin.epic.summary)}">${this.escapeHtml(lin.epic.key)}</a>`);
            }
            parts.push(`<a class="perf-issue-link" href="#" data-action="openIssue" data-key="${this.escapeHtml(lin.key)}" title="${this.escapeHtml(lin.summary)}">${this.escapeHtml(lin.key)}</a>`);
            crumbs.push(parts.join(`<span class="perf-lineage-sep">\u203A</span>`));
          }
          lineageHtml = `<div class="perf-event-lineage">${crumbs.join(" ")}</div>`;
        } else {
          const issueLinks = this.renderIssueLinks(ev.issue_keys || []);
          if (issueLinks) lineageHtml = `<div class="perf-event-lineage">${issueLinks}</div>`;
        }

        html += `
          <div class="card perf-day-event-card">
            <div class="perf-day-event-top">
              <span class="perf-source-badge perf-source-${this.escapeHtml(ev.source)}">${this.escapeHtml(ev.source)}</span>
              <span class="perf-day-event-type">${this.escapeHtml(ev.type)}</span>
              <span class="perf-day-event-pts">${pts}pts</span>
            </div>
            <div class="perf-day-event-title">${this.escapeHtml(ev.title)}</div>
            ${lineageHtml}
          </div>
        `;
      }
      html += `</div>`;
    } else if (detail === null) {
      html += `<div class="perf-loading-hint">Loading event details...</div>`;
    }

    html += `</div>`;
    return html;
  }

  // ============================================================
  // Issue Hierarchy
  // ============================================================

  private renderIssueHierarchy(): string {
    const h = this.state.issue_hierarchy;
    if (!h || !h.total_issues) {
      return this.getEmptyStateHtml("--", "No issue data captured yet. Run daily collection to start tracking.");
    }

    const strategies = Array.isArray(h.strategies) ? h.strategies : [];
    const unattachedEpics = Array.isArray(h.unattached_epics) ? h.unattached_epics : [];
    const uncategorized = Array.isArray(h.uncategorized) ? h.uncategorized : [];

    const cacheNote = h.cached
      ? `<div class="perf-hierarchy-note">Using cached hierarchy. Click "Refresh from Jira" for live data.</div>`
      : "";

    let html = `<div class="perf-hierarchy">${cacheNote}`;

    for (const strat of strategies) {
      html += this.renderTreeNode(strat, 0, "strategy");
    }
    for (const epic of unattachedEpics) {
      html += this.renderTreeNode(epic, 0, "epic");
    }
    if (uncategorized.length > 0) {
      html += `<div class="perf-tree-group-label">Other Issues</div>`;
      for (const issue of uncategorized) {
        html += this.renderTreeNode(issue, 0, "issue");
      }
    }

    html += `</div>`;
    return html;
  }

  private renderTreeNode(node: IssueNode, depth: number, nodeType: string): string {
    if (!node) return "";
    const children = Array.isArray(node.children) ? node.children : [];
    const hasChildren = children.length > 0;
    const indent = depth * 20;
    const toggle = hasChildren
      ? `<span class="perf-tree-toggle" data-action="toggleNode" data-key="${this.escapeHtml(node.key)}">&#9654;</span>`
      : `<span class="perf-tree-toggle-spacer"></span>`;

    const typeIcon = this.getTypeIcon(nodeType);
    const badge = nodeType === "strategy"
      ? "perf-strategy-badge"
      : nodeType === "epic"
        ? "perf-epic-badge"
        : "perf-issue-badge";

    const keywords = node.keywords && node.keywords.length > 0
      ? `<div class="perf-issue-tags">${node.keywords.map((k) => `<span class="perf-issue-tag">${this.escapeHtml(k)}</span>`).join("")}</div>`
      : "";

    const summary = node.summary
      ? `<span class="perf-tree-summary">${this.escapeHtml(node.summary)}</span>`
      : "";

    let html = `
      <div class="perf-tree-node depth-${depth}" style="padding-left: ${indent}px;" data-key="${this.escapeHtml(node.key)}">
        <div class="perf-tree-node-header">
          ${toggle}
          <span class="perf-tree-icon">${typeIcon}</span>
          <span class="${badge}">${this.renderIssueLink(node.key)}</span>
          ${summary}
          <span class="perf-tree-points">${node.points}pts</span>
          <span class="perf-tree-count">${node.event_count || ""}ev</span>
        </div>
        ${keywords}
      </div>
    `;

    if (hasChildren) {
      html += `<div class="perf-tree-children" data-parent="${this.escapeHtml(node.key)}">`;
      for (const child of children) {
        const childChildren = Array.isArray(child.children) ? child.children : [];
        const childType = childChildren.length > 0 ? "epic" : "issue";
        html += this.renderTreeNode(child, depth + 1, childType);
      }
      html += `</div>`;
    }

    return html;
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

  // ============================================================
  // Mindmap
  // ============================================================

  private renderMindmap(): string {
    const h = this.state.issue_hierarchy;
    if (!h || !h.total_issues) {
      return this.getEmptyStateHtml("--", "Issue mindmap will appear after data collection.");
    }

    const strategies = Array.isArray(h.strategies) ? h.strategies : [];
    const unattachedEpics = Array.isArray(h.unattached_epics) ? h.unattached_epics : [];
    const uncatIssues = Array.isArray(h.uncategorized) ? h.uncategorized : [];

    const groups: IssueNode[] = [
      ...strategies,
      ...unattachedEpics,
    ];

    if (groups.length === 0 && uncatIssues.length > 0) {
      groups.push({
        key: "Other",
        summary: "Uncategorized Issues",
        type: "group",
        points: uncatIssues.reduce((s, i) => s + i.points, 0),
        event_count: uncatIssues.reduce((s, i) => s + (i.event_count || 0), 0),
        keywords: [],
        children: uncatIssues,
      });
    }

    if (groups.length === 0) {
      return this.getEmptyStateHtml("--", "No issue groups to display.");
    }

    // Dynamic canvas sizing based on content
    const totalEpics = groups.reduce((s, g) => s + (g.children || []).length, 0);
    const totalLeaf = groups.reduce((s, g) =>
      s + (g.children || []).reduce((s2, c) => s2 + (c.children || []).length, 0), 0);
    const canvas = Math.max(700, Math.min(1100, 500 + totalEpics * 50 + totalLeaf * 20));
    const width = canvas;
    const height = canvas;
    const cx = width / 2;
    const cy = height / 2;

    const colors = ["#3b82f6", "#8b5cf6", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#06b6d4", "#f97316"];
    let paths = "";

    // Center node -- prominent
    const centerR = 48;
    paths += `
      <circle cx="${cx}" cy="${cy}" r="${centerR}" fill="var(--badge-bg, #334155)" opacity="0.12"/>
      <circle cx="${cx}" cy="${cy}" r="${centerR}" fill="none" stroke="var(--badge-bg, #334155)"
              stroke-width="2.5" opacity="0.25"/>
      <text x="${cx}" y="${cy - 10}" text-anchor="middle" dominant-baseline="middle"
            font-size="24" font-weight="800" fill="var(--text-primary, #e0e0e0)">${this.escapeHtml(this.state.quarter)}</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle"
            font-size="15" fill="var(--text-secondary, #888)">${h.total_issues} issues</text>
    `;

    const angleStep = (2 * Math.PI) / groups.length;
    const stratRadius = Math.round(canvas * 0.22);
    const epicRadius = Math.round(canvas * 0.14);
    const issueRadius = Math.round(canvas * 0.10);
    const maxEpics = 8;
    const maxIssues = 6;

    groups.forEach((group, gi) => {
      const angle = gi * angleStep - Math.PI / 2;
      const gx = cx + stratRadius * Math.cos(angle);
      const gy = cy + stratRadius * Math.sin(angle);
      const color = colors[gi % colors.length];

      // Line: center -> strategy
      paths += `<line x1="${cx}" y1="${cy}" x2="${gx}" y2="${gy}" stroke="${color}" stroke-width="5" opacity="0.45"/>`;

      const groupSize = Math.min(Math.max(group.points / 5, 38), 60);
      paths += `
        <circle cx="${gx}" cy="${gy}" r="${groupSize}" fill="${color}" opacity="0.2" stroke="${color}" stroke-width="3"/>
        <text x="${gx}" y="${gy - 7}" text-anchor="middle" dominant-baseline="middle"
              font-size="16" fill="var(--text-primary, #e0e0e0)" font-weight="800">${this.escapeHtml(group.key.replace(/^ANSTRAT-/, "AN-"))}</text>
        <text x="${gx}" y="${gy + 13}" text-anchor="middle"
              font-size="13" fill="var(--text-secondary, #aaa)" font-weight="600">${group.points}pts</text>
      `;

      // Ring 2: Epics
      const children = group.children || [];
      if (children.length > 0) {
        const nCh = children.length;
        const childSpan = Math.min(Math.PI * 1.1, Math.max(nCh * 0.65, 0.8));
        const childStep = childSpan / Math.max(nCh - 1, 1);
        const childStart = angle - childSpan / 2;

        children.slice(0, maxEpics).forEach((child, ci) => {
          const childAngle = nCh === 1 ? angle : childStart + ci * childStep;
          const ex = gx + epicRadius * Math.cos(childAngle);
          const ey = gy + epicRadius * Math.sin(childAngle);
          const leafSize = Math.min(Math.max(child.points / 5, 24), 36);

          // Line: strategy -> epic
          paths += `<line x1="${gx}" y1="${gy}" x2="${ex}" y2="${ey}" stroke="${color}" stroke-width="3" opacity="0.4"/>`;
          paths += `
            <circle cx="${ex}" cy="${ey}" r="${leafSize}" fill="${color}" opacity="0.5" stroke="${color}" stroke-width="2">
              <title>${this.escapeHtml(child.key)}: ${this.escapeHtml(child.summary || "")} (${child.points}pts)</title>
            </circle>
            <text x="${ex}" y="${ey}" text-anchor="middle" dominant-baseline="middle"
                  font-size="14" font-weight="700" fill="var(--text-primary, #e0e0e0)">
              <title>${this.escapeHtml(child.key)}</title>
              ${this.escapeHtml(child.key.replace(/^AAP-/, ""))}
            </text>
          `;

          // Ring 3: Issues (children of epics)
          const issues = child.children || [];
          if (issues.length > 0) {
            const nIss = issues.length;
            const issueSpan = Math.min(Math.PI * 0.9, Math.max(nIss * 0.45, 0.6));
            const issueStep = issueSpan / Math.max(nIss - 1, 1);
            const issueStart = childAngle - issueSpan / 2;

            issues.slice(0, maxIssues).forEach((issue, ii) => {
              const issueAngle = nIss === 1 ? childAngle : issueStart + ii * issueStep;
              const ix = ex + issueRadius * Math.cos(issueAngle);
              const iy = ey + issueRadius * Math.sin(issueAngle);
              const issueSz = Math.min(Math.max(issue.points / 6, 20), 28);

              // Line: epic -> issue
              paths += `<line x1="${ex}" y1="${ey}" x2="${ix}" y2="${iy}" stroke="${color}" stroke-width="2" opacity="0.35"/>`;
              paths += `
                <circle cx="${ix}" cy="${iy}" r="${issueSz}" fill="${color}" opacity="0.75" stroke="${color}" stroke-width="1.5">
                  <title>${this.escapeHtml(issue.key)}: ${this.escapeHtml(issue.summary || "")} (${issue.points}pts)</title>
                </circle>
                <text x="${ix}" y="${iy}" text-anchor="middle" dominant-baseline="middle"
                      font-size="12" font-weight="700" fill="#fff">${this.escapeHtml(issue.key.replace(/^AAP-/, ""))}</text>
              `;
            });

            const leftover = issues.length - maxIssues;
            if (leftover > 0) {
              const lx = ex + (issueRadius + 18) * Math.cos(childAngle);
              const ly = ey + (issueRadius + 18) * Math.sin(childAngle);
              paths += `<text x="${lx}" y="${ly}" text-anchor="middle" font-size="12" font-weight="bold" fill="var(--text-secondary, #999)">+${leftover}</text>`;
            }
          }
        });
      }
    });

    return `
      <svg class="perf-mindmap-svg" viewBox="0 0 ${width} ${height}"
           xmlns="http://www.w3.org/2000/svg" style="width:100%;height:auto;">
        <style>text { font-family: system-ui, -apple-system, sans-serif; }</style>
        ${paths}
      </svg>
    `;
  }

  // ============================================================
  // Sunburst (existing, preserved)
  // ============================================================

  private generateSunburstSVG(): string {
    const width = 350;
    const height = 350;
    const cx = width / 2;
    const cy = height / 2;
    const innerRadius = 55;
    const middleRadius = 100;
    const outerRadius = 145;

    const competencies = this.state.competencies;
    const overall = this.state.overall_percentage;

    const metaCategories = [
      {
        id: "technical_excellence",
        name: "Technical Excellence",
        competencies: ["technical_contribution", "technical_knowledge", "creativity_innovation", "continuous_improvement"],
      },
      {
        id: "leadership_influence",
        name: "Leadership & Influence",
        competencies: ["leadership", "collaboration", "mentorship", "speaking_publicity"],
      },
      {
        id: "delivery_impact",
        name: "Delivery & Impact",
        competencies: ["portfolio_impact", "planning_execution", "end_to_end_delivery", "opportunity_recognition"],
      },
    ];

    let paths = "";

    const centerColor = this.getColorForPercentage(overall);
    paths += `
      <circle cx="${cx}" cy="${cy}" r="${innerRadius - 5}" fill="${centerColor}" opacity="0.2"/>
      <text x="${cx}" y="${cy - 8}" text-anchor="middle" dominant-baseline="middle"
            font-size="28" font-weight="bold" fill="${centerColor}">${overall}%</text>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle"
            font-size="10" fill="#888">Overall</text>
    `;

    const categoryAngle = 360 / metaCategories.length;
    let startAngle = -90;

    metaCategories.forEach((cat) => {
      const catValues = cat.competencies.map((c) => competencies[c]?.percentage || 0);
      const catAvg = catValues.length > 0 ? Math.round(catValues.reduce((a, b) => a + b, 0) / catValues.length) : 0;
      const catColor = this.getColorForPercentage(catAvg);

      const catPath = this.arcPath(cx, cy, innerRadius, middleRadius, startAngle, categoryAngle - 2);
      paths += `
        <path d="${catPath}" fill="${catColor}" opacity="0.5" stroke="var(--bg-primary, #1a1a2e)" stroke-width="2">
          <title>${cat.name}: ${catAvg}%</title>
        </path>
      `;

      const compAngle = categoryAngle / cat.competencies.length;
      let compStart = startAngle;

      cat.competencies.forEach((compId) => {
        const compPct = competencies[compId]?.percentage || 0;
        const compColor = this.getColorForPercentage(compPct);
        const compPath = this.arcPath(cx, cy, middleRadius, outerRadius, compStart, compAngle - 1);

        paths += `
          <path d="${compPath}" fill="${compColor}" opacity="0.8"
                stroke="var(--bg-primary, #1a1a2e)" stroke-width="1">
            <title>${this.formatCompetencyName(compId)}: ${compPct}%</title>
          </path>
        `;

        compStart += compAngle;
      });

      startAngle += categoryAngle;
    });

    return `
      <svg class="perf-sunburst-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
           xmlns="http://www.w3.org/2000/svg">
        <style>text { font-family: system-ui, -apple-system, sans-serif; }</style>
        ${paths}
      </svg>
    `;
  }

  private arcPath(cx: number, cy: number, innerR: number, outerR: number, startAngle: number, sweepAngle: number): string {
    const startRad = (startAngle * Math.PI) / 180;
    const endRad = ((startAngle + sweepAngle) * Math.PI) / 180;

    const x1Outer = cx + outerR * Math.cos(startRad);
    const y1Outer = cy + outerR * Math.sin(startRad);
    const x2Outer = cx + outerR * Math.cos(endRad);
    const y2Outer = cy + outerR * Math.sin(endRad);

    const x1Inner = cx + innerR * Math.cos(startRad);
    const y1Inner = cy + innerR * Math.sin(startRad);
    const x2Inner = cx + innerR * Math.cos(endRad);
    const y2Inner = cy + innerR * Math.sin(endRad);

    const largeArc = sweepAngle > 180 ? 1 : 0;

    return `M ${x1Outer} ${y1Outer} A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2Outer} ${y2Outer} L ${x2Inner} ${y2Inner} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x1Inner} ${y1Inner} Z`;
  }

  private getColorForPercentage(pct: number): string {
    if (pct >= 80) return "#10b981";
    if (pct >= 50) return "#f59e0b";
    if (pct >= 25) return "#f97316";
    return "#ef4444";
  }

  private formatCompetencyName(id: string): string {
    return id.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
  }

  // ============================================================
  // Expandable Competency Bars with Evidence
  // ============================================================

  private renderExpandableCompetencyBars(): string {
    const sorted = Object.entries(this.state.competencies).sort((a, b) => b[1].percentage - a[1].percentage);

    if (sorted.length === 0) {
      return this.getEmptyStateHtml("--", "No competency data yet. Run daily collection to start tracking.");
    }

    // Group by category from meta
    const categories: Record<string, [string, CompetencyScore][]> = {};
    for (const entry of sorted) {
      const [id] = entry;
      const meta = this.state.competency_meta[id];
      const cat = meta?.category || "Other";
      if (!categories[cat]) categories[cat] = [];
      categories[cat].push(entry);
    }

    let html = "";
    for (const [category, entries] of Object.entries(categories)) {
      html += `<div class="perf-comp-category">
        <div class="perf-comp-category-label">${this.escapeHtml(category)}</div>`;

      for (const [id, score] of entries) {
        const color = this.getColorForPercentage(score.percentage);
        const icon = score.percentage >= 80 ? "\u2713" : score.percentage < 50 ? "\u26A0" : "";
        const isExpanded = this.state.expanded_competency === id;
        const evidence = this.state.competency_evidence[id] || [];
        const meta = this.state.competency_meta[id];
        const expandedClass = isExpanded ? " expanded" : "";

        let expandedContent = "";
        if (isExpanded) {
          // Goal and description section
          const goalHtml = meta ? `
            <div class="perf-comp-goal">
              <div class="perf-comp-goal-text">${this.escapeHtml(meta.goal)}</div>
              <div class="perf-comp-description">${this.escapeHtml(meta.description)}</div>
              <div class="perf-comp-progress-summary">
                ${meta.points}/${meta.target} pts &middot; ${evidence.length} contributing events
              </div>
            </div>
          ` : "";

          if (evidence.length > 0) {
            expandedContent = `
              ${goalHtml}
              <div class="perf-evidence-list">
                ${evidence.map(ev => {
                  const titleHtml = ev.url
                    ? `<a href="${this.escapeHtml(ev.url)}" class="perf-event-link">${this.escapeHtml(ev.title)}</a>`
                    : this.escapeHtml(ev.title);
                  return `
                    <div class="perf-evidence-card">
                      <div class="perf-evidence-card-top">
                        <span class="perf-source-badge perf-source-${this.escapeHtml(ev.source)}">${this.escapeHtml(ev.source)}</span>
                        <span class="perf-evidence-date">${this.escapeHtml(ev.date)}</span>
                        <span class="perf-evidence-pts">${ev.points} pts</span>
                      </div>
                      <div class="perf-evidence-card-title">${titleHtml}</div>
                      <div class="perf-evidence-card-meta">
                        ${ev.match_reason ? `<span class="perf-match-reason">${this.escapeHtml(ev.match_reason)}</span>` : ""}
                        ${ev.issue_keys?.length ? `<span class="perf-evidence-issues">${this.renderIssueLinks(ev.issue_keys)}</span>` : ""}
                      </div>
                    </div>
                  `;
                }).join("")}
              </div>
            `;
          } else {
            expandedContent = `
              ${goalHtml}
              <div class="perf-evidence-empty">No evidence recorded yet for this competency.</div>
            `;
          }
        }

        html += `
          <div class="perf-competency-row${expandedClass}">
            <div class="perf-competency-header" data-action="toggleCompetency" data-key="${this.escapeHtml(id)}">
              <div class="perf-comp-header-top">
                <span class="perf-competency-expand-icon">${isExpanded ? "\u25BC" : "\u25B6"}</span>
                <span class="perf-competency-name">${this.escapeHtml(meta?.name || this.formatCompetencyName(id))}</span>
                <span class="perf-competency-value">${score.percentage}%</span>
                <span class="perf-competency-status">${icon}</span>
              </div>
              <div class="perf-comp-header-bar">
                <div class="progress-bar">
                  <div class="progress-fill" style="width: ${Math.min(score.percentage, 100)}%; background: ${color};"></div>
                </div>
                <span class="perf-competency-count">${score.points} pts &middot; ${evidence.length} events</span>
              </div>
            </div>
            ${expandedContent}
          </div>
        `;
      }

      html += `</div>`;
    }

    return html;
  }

  // ============================================================
  // Gaps Alert (actionable with suggestions)
  // ============================================================

  private renderGapsAlert(): string {
    if (this.state.gaps.length === 0) return "";

    const gapItems = this.state.gaps.map((gap) => {
      const pct = this.state.competencies[gap]?.percentage || 0;
      const meta = this.state.competency_meta[gap];
      const name = meta?.name || this.formatCompetencyName(gap);
      const goal = meta?.goal || "";
      const color = this.getColorForPercentage(pct);
      return `
        <div class="perf-gaps-item">
          <div class="perf-gaps-item-header">
            <span class="perf-gaps-item-name">${this.escapeHtml(name)}</span>
            <span class="perf-gaps-item-pct" style="color: ${color};">${pct}%</span>
          </div>
          ${goal ? `<div class="perf-gaps-item-goal">${this.escapeHtml(goal)}</div>` : ""}
        </div>
      `;
    }).join("");

    return `
      <div class="perf-gaps-alert">
        <div class="perf-gaps-title">Areas Needing Attention</div>
        <div class="perf-gaps-items">${gapItems}</div>
      </div>
    `;
  }

  private renderGapsWithSuggestions(): string {
    const gaps = this.state.gap_suggestions;
    const gapKeys = Object.keys(gaps);
    if (gapKeys.length === 0) return "";

    // Group gaps by category
    const catGroups: Record<string, [string, GapSuggestion][]> = {};
    for (const [compId, gap] of Object.entries(gaps)) {
      const cat = gap.category || "Other";
      if (!catGroups[cat]) catGroups[cat] = [];
      catGroups[cat].push([compId, gap]);
    }

    let html = `<div class="section">
      <div class="section-title">Gaps & Growth Opportunities</div>
      <div class="perf-gap-intro">
        These competencies are below 50% of the quarterly target.
        Each card shows the goal you're working towards, your current progress, and specific actions to close the gap.
      </div>
      <div class="perf-gap-cards">`;

    for (const [category, entries] of Object.entries(catGroups)) {
      html += `<div class="perf-gap-category-label">${this.escapeHtml(category)}</div>`;

      for (const [compId, gap] of entries) {
        const color = this.getColorForPercentage(gap.percentage);
        const evidence = this.state.competency_evidence[compId] || [];
        const meta = this.state.competency_meta[compId];
        const name = meta?.name || this.formatCompetencyName(compId);
        const goal = gap.goal || meta?.goal || "";
        const description = gap.description || meta?.description || "";
        const deficit = gap.deficit || (gap.target - gap.points);

        html += `
          <div class="card perf-gap-card">
            <div class="perf-gap-card-header">
              <span class="card-title">${this.escapeHtml(name)}</span>
              <span class="perf-gap-card-pct" style="color: ${color};">${gap.percentage}%</span>
            </div>
            ${goal ? `<div class="perf-gap-card-goal">${this.escapeHtml(goal)}</div>` : ""}
            <div class="progress-bar my-12">
              <div class="progress-fill" style="width: ${gap.percentage}%; background: ${color};"></div>
            </div>
            <div class="perf-gap-card-meta">
              ${gap.points}/${gap.target} pts &middot; ${gap.evidence_count} events &middot;
              <strong>${deficit} pts</strong> needed to reach target
            </div>
            ${description ? `<div class="perf-gap-card-desc">${this.escapeHtml(description)}</div>` : ""}
            <div class="perf-gap-card-suggestions">
              <div class="perf-gap-card-subtitle">Actions to close this gap:</div>
              <ul>
                ${gap.suggestions.map(s => `<li>${this.escapeHtml(s)}</li>`).join("")}
              </ul>
            </div>
            ${evidence.length > 0 ? `
              <div class="perf-gap-card-evidence">
                <div class="perf-gap-card-subtitle">What you've done so far (${evidence.length}):</div>
                ${evidence.slice(0, 3).map(ev => {
                  const titleHtml = ev.url
                    ? `<a href="${this.escapeHtml(ev.url)}" class="perf-gap-evidence-link">${this.escapeHtml(ev.title)}</a>`
                    : this.escapeHtml(ev.title);
                  return `
                    <div class="perf-gap-evidence-item">
                      <span class="perf-gap-evidence-date">${this.escapeHtml(ev.date)}</span>
                      <span class="perf-gap-evidence-title">${titleHtml}</span>
                      ${ev.match_reason ? `<span class="perf-gap-evidence-reason">${this.escapeHtml(ev.match_reason)}</span>` : ""}
                      ${this.renderIssueLinks(ev.issue_keys)}
                    </div>
                  `;
                }).join("")}
              </div>
            ` : `
              <div class="perf-gap-card-no-evidence">
                No activity recorded yet for this competency. Start with the suggestions above.
              </div>
            `}
          </div>
        `;
      }
    }

    html += `</div></div>`;
    return html;
  }

  // ============================================================
  // Strategy Tab
  // ============================================================

  // ============================================================
  // Questions (existing, preserved)
  // ============================================================

  private renderQuestions(): string {
    const questions = this.state.questions_summary;
    if (!questions || questions.length === 0) {
      return this.getEmptyStateHtml("--", "Questions will appear after first data collection.");
    }

    return questions.map((q) => {
      const statusClass = q.has_summary ? "evaluated" : "pending";
      const statusText = q.has_summary ? "Evaluated" : "Pending";

      return `
        <div class="card perf-question-card" data-question-id="${this.escapeHtml(q.id)}">
          <div class="perf-question-header">
            <span class="perf-question-text">${this.escapeHtml(q.text)}</span>
            <span class="perf-question-status ${statusClass}">${statusText}</span>
          </div>
          <div class="perf-question-meta">
            <span>${q.evidence_count} evidence</span>
            <span>${q.notes_count} notes</span>
          </div>
          <div class="perf-question-actions">
            <button class="btn btn-xs" data-action="viewSummary" data-question="${this.escapeHtml(q.id)}">View</button>
            <button class="btn btn-xs" data-action="addNote" data-question="${this.escapeHtml(q.id)}">Add Note</button>
            <button class="btn btn-xs" data-action="evaluate" data-question="${this.escapeHtml(q.id)}">Evaluate</button>
          </div>
        </div>
      `;
    }).join("");
  }

  // ============================================================
  // Highlights (existing, preserved)
  // ============================================================

  private renderHighlights(): string {
    if (this.state.highlights.length === 0) {
      return this.getEmptyStateHtml("--", "Highlights will appear as you complete work.");
    }

    return this.state.highlights.slice(0, 5).map((h) => `
      <div class="perf-highlight-item">
        <span>${this.escapeHtml(h)}</span>
      </div>
    `).join("");
  }

  // ============================================================
  // Styles & Scripts
  // ============================================================

  getStyles(): string {
    return "";
  }

  getScript(): string {
    return `
      (function() {
        TabEventDelegation.registerClickHandler('performance', function(action, element, e) {
          e.stopPropagation();
          var questionId = element.getAttribute('data-question');
          var dateVal = element.getAttribute('data-date');
          var keyVal = element.getAttribute('data-key');

          if (action === 'logActivity') {
            var category = document.getElementById('activityCategory')?.value;
            var description = document.getElementById('activityDescription')?.value;
            if (description) {
              vscode.postMessage({
                command: 'performanceAction',
                action: 'logActivity',
                category: category,
                description: description
              });
              document.getElementById('activityDescription').value = '';
            }
          } else if (action === 'switchTab') {
            var tabId = keyVal;
            document.querySelectorAll('.perf-tab').forEach(function(btn) {
              btn.classList.toggle('perf-tab--active', btn.getAttribute('data-key') === tabId);
            });
            vscode.postMessage({
              command: 'performanceAction',
              action: 'switchTab',
              key: tabId
            });
          } else if (action === 'selectDay') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'selectDay',
              date: dateVal
            });
          } else if (action === 'closeDay') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'closeDay'
            });
          } else if (action === 'prevMonth' || action === 'nextMonth') {
            vscode.postMessage({
              command: 'performanceAction',
              action: action
            });
          } else if (action === 'toggleNode') {
            var parent = element.closest('.perf-tree-node');
            if (parent) {
              var childrenDiv = parent.nextElementSibling;
              if (childrenDiv && childrenDiv.classList.contains('perf-tree-children')) {
                childrenDiv.classList.toggle('collapsed');
                element.classList.toggle('expanded');
              }
            }
          } else if (action === 'toggleCompetency') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'toggleCompetency',
              key: keyVal
            });
          } else if (action === 'openIssue') {
            vscode.postMessage({
              command: 'performanceAction',
              action: 'openIssue',
              key: keyVal
            });
          } else if (action === 'toggleScoringSettings' || action === 'saveScoringConfig' || action === 'resetScoringConfig') {
            vscode.postMessage({ command: 'performanceAction', action: action });
          } else if (action === 'toggleScoringComp') {
            vscode.postMessage({ command: 'performanceAction', action: action, key: keyVal });
          } else if (action === 'toggleEventType') {
            vscode.postMessage({
              command: 'performanceAction', action: action,
              comp: target.closest('[data-comp]')?.dataset?.comp || target.dataset.comp,
              value: target.dataset.value
            });
          } else if (action === 'removePhrase' || action === 'removeKeyword') {
            vscode.postMessage({
              command: 'performanceAction', action: action,
              comp: target.dataset.comp, value: target.dataset.value
            });
          } else {
            vscode.postMessage({
              command: 'performanceAction',
              action: action,
              questionId: questionId,
              key: keyVal
            });
          }
        });

        // Tag input: Enter key adds a phrase/keyword
        document.addEventListener('keydown', function(e) {
          var input = e.target;
          if (!input || !input.classList || !input.classList.contains('scoring-tag-input')) return;
          if (e.key !== 'Enter') return;
          e.preventDefault();
          var val = input.value.trim();
          if (!val) return;
          var act = input.dataset.action;
          var comp = input.dataset.comp;
          vscode.postMessage({ command: 'performanceAction', action: act, comp: comp, value: val });
          input.value = '';
        });

        // Number input changes for globals and base_points
        document.addEventListener('change', function(e) {
          var input = e.target;
          if (!input || !input.classList || !input.classList.contains('scoring-input')) return;
          var field = input.dataset.field;
          var comp = input.dataset.comp;
          var val = parseInt(input.value, 10);
          if (isNaN(val)) return;
          if (comp) {
            vscode.postMessage({ command: 'performanceAction', action: 'updateCompBasePoints', comp: comp, value: val });
          } else if (field) {
            vscode.postMessage({ command: 'performanceAction', action: 'updateScoringGlobal', field: field, value: val });
          }
        });
      })();
    `;
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

      default:
        return false;
    }
  }

  private async handlePerformanceAction(action: string, message: any): Promise<void> {
    logger.log(`Performance action: ${action}`);

    switch (action) {
      case "collectDaily":
        await this.collectDailyData();
        break;
      case "backfill":
        await this.backfillAll();
        break;
      case "exportReport":
        await this.exportReport();
        break;
      case "logActivity":
        await this.logActivity(message.category, message.description);
        break;
      case "evaluateAll":
        await this.evaluateAllQuestions();
        break;
      case "viewSummary":
        await this.viewQuestionSummary(message.questionId);
        break;
      case "addNote":
        await this.addNoteToQuestion(message.questionId);
        break;
      case "evaluate":
        await this.evaluateQuestion(message.questionId);
        break;
      case "switchTab":
        this.state.active_tab = message.key || "overview";
        this.notifyNeedsRender();
        break;
      case "refreshHierarchy":
        await this.refreshHierarchy();
        break;
      case "selectDay":
        this.state.selected_date = message.date || null;
        this.state.day_detail = null;
        this.notifyNeedsRender();
        // Fetch day detail asynchronously
        if (this.state.selected_date) {
          this.loadDayDetail(this.state.selected_date);
        }
        break;
      case "closeDay":
        this.state.selected_date = null;
        this.state.day_detail = null;
        this.notifyNeedsRender();
        break;
      case "prevMonth":
        this.navigateMonth(-1);
        break;
      case "nextMonth":
        this.navigateMonth(1);
        break;
      case "toggleCompetency":
        this.state.expanded_competency =
          this.state.expanded_competency === message.key ? null : message.key;
        this.notifyNeedsRender();
        break;
      case "openIssue":
        if (message.key) {
          const issueKey = message.key as string;
          // Open Jira issue in browser
          const baseUrl = issueKey.startsWith("ANSTRAT-")
            ? "https://issues.redhat.com/browse/"
            : "https://issues.redhat.com/browse/";
          vscode.env.openExternal(vscode.Uri.parse(`${baseUrl}${issueKey}`));
        }
        break;
      // ---- Scoring Config Actions ----
      case "toggleScoringSettings":
        this.state.scoring_config_expanded = !this.state.scoring_config_expanded;
        this.notifyNeedsRender();
        break;
      case "toggleScoringComp":
        this.state.scoring_comp_expanded =
          this.state.scoring_comp_expanded === message.key ? null : message.key;
        this.notifyNeedsRender();
        break;
      case "saveScoringConfig":
        await this.saveScoringConfig();
        break;
      case "resetScoringConfig":
        await this.resetScoringConfig();
        break;
      case "toggleEventType":
        this.toggleScoringEventType(message.comp, message.value);
        break;
      case "removePhrase":
        this.removeScoringTag("phrases", message.comp, message.value);
        break;
      case "removeKeyword":
        this.removeScoringTag("keywords", message.comp, message.value);
        break;
      case "addPhrase":
        this.addScoringTag("phrases", message.comp, message.value);
        break;
      case "addKeyword":
        this.addScoringTag("keywords", message.comp, message.value);
        break;
      case "updateScoringGlobal":
        this.updateScoringGlobal(message.field, message.value);
        break;
      case "updateCompBasePoints":
        this.updateCompBasePoints(message.comp, message.value);
        break;
      default:
        logger.warn(`Unknown performance action: ${action}`);
    }
  }

  // ============================================================
  // Action Handlers
  // ============================================================

  private navigateMonth(delta: number): void {
    let newMonth = this.state.calendar_month + delta;
    let newYear = this.state.calendar_year;
    if (newMonth < 0) { newMonth = 11; newYear--; }
    if (newMonth > 11) { newMonth = 0; newYear++; }

    const quarter = Math.floor(this.state.calendar_month / 3);
    const qStart = quarter * 3;
    const qEnd = qStart + 2;
    if (newMonth < qStart || newMonth > qEnd) return;

    this.state.calendar_month = newMonth;
    this.state.calendar_year = newYear;
    this.notifyNeedsRender();
  }

  private async loadDayDetail(dateStr: string): Promise<void> {
    try {
      const result = await dbus.stats_getDayDetail(dateStr);
      if (result.success && result.data) {
        const raw = result.data as any;
        this.state.day_detail = {
          date: raw.date || dateStr,
          events: Array.isArray(raw.events) ? raw.events : [],
          daily_points: raw.daily_points || {},
          daily_total: raw.daily_total || 0,
          category_points: raw.category_points || {},
          has_data: raw.has_data || false,
        };
        this.notifyNeedsRender();
      }
    } catch (e) {
      logger.warn(`Failed to load day detail: ${e}`);
    }
  }

  private async refreshHierarchy(): Promise<void> {
    vscode.window.showInformationMessage("Refreshing issue hierarchy from Jira...");
    try {
      const result = await dbus.stats_getIssueHierarchy(true);
      if (result.success && result.data) {
        const raw = result.data as any;
        this.state.issue_hierarchy = {
          strategies: Array.isArray(raw.strategies) ? raw.strategies : [],
          unattached_epics: Array.isArray(raw.unattached_epics) ? raw.unattached_epics : [],
          uncategorized: Array.isArray(raw.uncategorized) ? raw.uncategorized : [],
          total_issues: raw.total_issues || 0,
          cached: raw.cached || false,
        };
        vscode.window.showInformationMessage("Issue hierarchy refreshed");
        this.notifyNeedsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to refresh hierarchy: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error refreshing hierarchy: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async collectDailyData(): Promise<void> {
    vscode.window.showInformationMessage("Collecting today's performance data...");
    try {
      const result = await dbus.stats_collectDaily();
      if (result.success) {
        const data = result.data as any;
        vscode.window.showInformationMessage(`Daily data collected: ${data?.event_count || 0} events, ${data?.daily_total || 0} points`);
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to collect data: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error collecting data: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async backfillAll(): Promise<void> {
    vscode.window.showInformationMessage("Re-collecting all quarter data (Jira, GitLab, emails)...");
    try {
      const [daysResult, emailsResult] = await Promise.all([
        dbus.stats_backfill(),
        dbus.stats_backfillExecutiveEmails(),
      ]);

      const parts: string[] = [];
      if (daysResult.success) {
        const d = daysResult.data as any;
        parts.push(`${d?.days_processed || 0} days re-collected`);
      } else {
        parts.push(`days failed: ${daysResult.error}`);
      }
      if (emailsResult.success) {
        const e = emailsResult.data as any;
        const total = (e?.total_new || 0) + (e?.total_skipped || 0);
        parts.push(`${total} emails (${e?.total_new || 0} new)`);
      } else {
        parts.push(`emails failed: ${emailsResult.error}`);
      }

      vscode.window.showInformationMessage(`Backfill complete: ${parts.join(", ")}`);
      await this.refresh();
    } catch (error) {
      vscode.window.showErrorMessage(`Error backfilling: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async exportReport(): Promise<void> {
    vscode.window.showInformationMessage("Generating PDF report... this may take a moment.");
    try {
      const result = await dbus.stats_exportReport("pdf");
      if (result.success && result.data) {
        const data = result.data as any;
        if (data.path) {
          vscode.window.showInformationMessage(`PDF report exported to: ${data.path}`);
          const fileUri = vscode.Uri.file(data.path);
          await vscode.env.openExternal(fileUri);
        } else {
          vscode.window.showInformationMessage("Report exported successfully");
        }
      } else {
        vscode.window.showErrorMessage(`Failed to export: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error exporting: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async logActivity(category: string, description: string): Promise<void> {
    if (!description) {
      vscode.window.showWarningMessage("Please enter a description");
      return;
    }
    try {
      const result = await dbus.stats_logActivity(category, description);
      if (result.success) {
        vscode.window.showInformationMessage(`Activity logged: ${category}`);
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to log activity: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error logging activity: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async evaluateAllQuestions(): Promise<void> {
    vscode.window.showInformationMessage("Re-evaluating all questions...");
    try {
      const result = await dbus.stats_evaluateAll();
      if (result.success) {
        vscode.window.showInformationMessage("All questions re-evaluated");
        await this.refreshPreservingUIState();
      } else {
        vscode.window.showErrorMessage(`Failed to evaluate: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error evaluating: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async viewQuestionSummary(questionId: string): Promise<void> {
    if (!questionId) return;
    try {
      const result = await dbus.stats_getQuestionSummary(questionId);
      if (result.success && result.data) {
        const data = result.data as any;
        const summary = data.summary || "No summary available";
        vscode.window.showInformationMessage(summary, { modal: true });
      } else {
        vscode.window.showErrorMessage(`Failed to get summary: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error getting summary: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async addNoteToQuestion(questionId: string): Promise<void> {
    if (!questionId) return;
    const note = await vscode.window.showInputBox({
      prompt: "Enter a note for this question",
      placeHolder: "Your note...",
    });
    if (!note) return;
    try {
      const result = await dbus.stats_addNote(questionId, note);
      if (result.success) {
        vscode.window.showInformationMessage("Note added");
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to add note: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error adding note: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async evaluateQuestion(questionId: string): Promise<void> {
    if (!questionId) return;
    vscode.window.showInformationMessage(`Evaluating question ${questionId}...`);
    try {
      const result = await dbus.stats_evaluateQuestion(questionId);
      if (result.success) {
        vscode.window.showInformationMessage("Question evaluated");
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Failed to evaluate: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error evaluating: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  // ============================================================
  // Scoring Config Handlers
  // ============================================================

  private updateScoringGlobal(field: string, value: number): void {
    if (!this.state.scoring_config || !field) return;
    (this.state.scoring_config as any)[field] = value;
  }

  private updateCompBasePoints(compId: string, value: number): void {
    if (!this.state.scoring_config?.competencies?.[compId]) return;
    this.state.scoring_config.competencies[compId].base_points = value;
  }

  private toggleScoringEventType(compId: string, eventType: string): void {
    if (!this.state.scoring_config?.competencies?.[compId] || !eventType) return;
    const comp = this.state.scoring_config.competencies[compId];
    const idx = comp.event_types.indexOf(eventType);
    if (idx >= 0) {
      comp.event_types.splice(idx, 1);
    } else {
      comp.event_types.push(eventType);
    }
    this.notifyNeedsRender();
  }

  private removeScoringTag(field: "phrases" | "keywords", compId: string, value: string): void {
    if (!this.state.scoring_config?.competencies?.[compId] || !value) return;
    const arr = this.state.scoring_config.competencies[compId][field];
    const idx = arr.indexOf(value);
    if (idx >= 0) {
      arr.splice(idx, 1);
      this.notifyNeedsRender();
    }
  }

  private addScoringTag(field: "phrases" | "keywords", compId: string, value: string): void {
    if (!this.state.scoring_config?.competencies?.[compId] || !value) return;
    const arr = this.state.scoring_config.competencies[compId][field];
    if (!arr.includes(value)) {
      arr.push(value);
      this.notifyNeedsRender();
    }
  }

  private async saveScoringConfig(): Promise<void> {
    if (!this.state.scoring_config) return;
    vscode.window.showInformationMessage("Saving scoring config and re-evaluating...");
    try {
      const cfg = this.state.scoring_config;
      const payload: Record<string, unknown> = {
        min_signals: cfg.min_signals,
        daily_cap: cfg.daily_cap,
        target_per_competency: cfg.target_per_competency,
        competencies: {} as Record<string, unknown>,
      };
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
        const re = (result.data as any)?.re_evaluated || 0;
        vscode.window.showInformationMessage(`Config saved. ${re} days re-evaluated.`);
        await this.refreshPreservingUIState();
      } else {
        vscode.window.showErrorMessage(`Failed to save config: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error saving config: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async resetScoringConfig(): Promise<void> {
    vscode.window.showInformationMessage("Resetting scoring config to defaults...");
    try {
      const result = await dbus.stats_resetScoringConfig();
      if (result.success) {
        vscode.window.showInformationMessage("Config reset to defaults. Scores re-evaluated.");
        await this.refreshPreservingUIState();
      } else {
        vscode.window.showErrorMessage(`Failed to reset: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error resetting: ${error instanceof Error ? error.message : String(error)}`);
    }
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
}
