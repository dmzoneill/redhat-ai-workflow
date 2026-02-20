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

const logger = createLogger("PerformanceTab");

// ============================================================
// Interfaces
// ============================================================

interface CompetencyScore {
  points: number;
  percentage: number;
}

interface QuestionNote {
  text: string;
  added_at: string;
}

interface QuestionSummary {
  id: string;
  text: string;
  subtext?: string;
  evidence_count: number;
  notes_count: number;
  has_summary: boolean;
  llm_summary?: string | null;
  last_evaluated: string | null;
  evidence_ids?: string[];
  manual_notes?: QuestionNote[];
}

interface QuestionEvidence {
  id: string;
  title: string;
  source: string;
  date: string;
  points: number;
  competencies: string[];
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
  executive_senders: string[];
  executive_emails: ExecutiveEmailSummary[];
}

interface ExecutiveEmailSummary {
  email_id: string;
  sender: string;
  subject: string;
  date: string;
}

interface ScoringCompConfig {
  base_points: number;
  phrases: string[];
  keywords: string[];
  event_types: string[];
  name: string;
  category: string;
  level_title?: string;
  level_description?: string;
}

interface EngineeringLevel {
  id: string;
  name: string;
  short: string;
}

interface ScoringConfig {
  min_signals: number;
  daily_cap: number;
  target_per_competency: number;
  engineering_level: string;
  engineering_levels?: EngineeringLevel[];
  competencies: Record<string, ScoringCompConfig>;
}

// ============================================================
// Pillar definitions (matching Red Hat Engineering Competencies)
// ============================================================

const PILLAR_DEFS: Record<string, { color: string; icon: string }> = {
  "Technical Contribution": { color: "#2196F3", icon: "\u{1F527}" },
  "Leadership":             { color: "#F44336", icon: "\u{1F310}" },
  "Mentorship":             { color: "#FF9800", icon: "\u{1F393}" },
  "End-to-End Delivery":    { color: "#4CAF50", icon: "\u{1F680}" },
};

function hexToHsl(hex: string): [number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [Math.round(h * 360), Math.round(s * 100), Math.round(l * 100)];
}

function hslToHex(h: number, s: number, l: number): string {
  const sn = s / 100, ln = l / 100;
  const a = sn * Math.min(ln, 1 - ln);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = ln - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

type PillarTintType = "competency" | "anstrat" | "epic" | "issue" | "strategy";

/**
 * Derive a pillar-affiliated color from the base pillar hex.
 *
 * - competency: pillar hue, saturation scaled by score (Option C)
 * - anstrat:    pillar hue lightened 10%
 * - epic:       pillar hue lightened 25%
 * - issue:      pillar hue lightened 35%, reduced saturation
 * - strategy:   pillar hue; covered=bright, gap=desaturated+lighter
 */
function pillarTint(
  pillarHex: string,
  nodeType: PillarTintType,
  scorePct?: number,
  isCovered?: boolean,
): string {
  const [h, s, l] = hexToHsl(pillarHex);
  switch (nodeType) {
    case "competency": {
      const pct = Math.max(0, Math.min(100, scorePct ?? 50));
      const satAdj = Math.round(s * (0.4 + 0.6 * (pct / 100)));
      const litAdj = Math.round(l + (100 - pct) * 0.15);
      return hslToHex(h, Math.min(satAdj, 100), Math.min(litAdj, 85));
    }
    case "anstrat":
      return hslToHex(h, Math.min(s, 75), Math.min(l + 10, 65));
    case "epic":
      return hslToHex(h, Math.min(s - 10, 70), Math.min(l + 20, 72));
    case "issue":
      return hslToHex(h, Math.max(s - 20, 30), Math.min(l + 30, 78));
    case "strategy":
      if (isCovered) return hslToHex(h, Math.min(s + 10, 90), Math.min(l + 5, 60));
      return hslToHex(h, Math.max(s - 35, 20), Math.min(l + 25, 75));
    default:
      return pillarHex;
  }
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
    executive_senders: [],
    executive_emails: [],
  };

  private _scoringSaveTimer: ReturnType<typeof setTimeout> | null = null;
  private _settingsDirty = false;
  private _settingsRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  private _pendingLevelRefresh = false;

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

      // Load executive email senders from config
      try {
        const sendersResult = await dbus.stats_getExecutiveSenders();
        if (sendersResult.success && sendersResult.data) {
          this.state.executive_senders = (sendersResult.data as any).senders || [];
        }
      } catch (e) {
        logger.warn(`Failed to load executive senders: ${e}`);
      }

      // Load cached executive emails for the quarter
      try {
        const emailsResult = await dbus.stats_listExecutiveEmails();
        if (emailsResult.success && emailsResult.data) {
          this.state.executive_emails = (emailsResult.data as any).emails || [];
        }
      } catch (e) {
        logger.warn(`Failed to load executive emails: ${e}`);
      }
    } catch (error) {
      logger.error("Error loading data", error);
    }
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
      { id: "help", label: "Help", icon: "\u2753" },
    ];

    const tabBar = tabs.map(t =>
      `<button class="flex-row meetings-subtab${t.id === tab ? " active" : ""}" data-action="switchTab" data-key="${t.id}">${t.icon} ${t.label}</button>`
    ).join("");

    return `
      <!-- Header -->
      <div class="section mb-8">
        <div class="flex-between">
          <div>
            <h2 class="section-title m-0">${this.escapeHtml(this.state.quarter)} Quarterly Connection</h2>
            <div class="text-secondary text-sm mt-4">Day ${this.state.day_of_quarter} of 90 &middot; ${this.state.overall_percentage}% overall &middot; ${this.state.coverage.captured}/${this.state.coverage.total_weekdays} days captured</div>
          </div>
          <div class="d-flex gap-8 items-center">
            <button class="btn btn-xs btn-ghost" data-action="collectDaily" title="Collect today's data">Collect Today</button>
            <button class="btn btn-xs btn-ghost" data-action="backfill" title="Backfill missing days">Backfill</button>
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

      <!-- Sub-tabs Navigation -->
      <div class="meetings-subtabs">${tabBar}</div>

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
        ${tab === "help" ? this.renderHelpTab() : ""}
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
        <div class="card stat-card">
          <div class="stat-value">${this.state.overall_percentage}%</div>
          <div class="text-meta stat-label">Overall Score</div>
        </div>
        <div class="card stat-card">
          <div class="stat-value">${this.state.coverage.captured}</div>
          <div class="text-meta stat-label">Days Captured</div>
        </div>
        <div class="card stat-card">
          <div class="stat-value">${this.state.issue_hierarchy?.total_issues || 0}</div>
          <div class="text-meta stat-label">Issues Tracked</div>
        </div>
        <div class="card stat-card" style="border-color: ${coverageColor}33;">
          <div class="stat-value" style="color: ${coverageColor};">${coveragePct}%</div>
          <div class="text-meta stat-label">Strategy Coverage</div>
        </div>
      </div>
    `;

    // Pillar summary cards
    const pillarData = align?.pillar_summary || {};
    const pillarCount = Object.keys(PILLAR_DEFS).length;
    let pillarHtml = `<div class="section"><div class="section-title">Competency Pillars &amp; Strategy Alignment</div><div class="grid-${pillarCount}">`;
    for (const [pname, pdef] of Object.entries(PILLAR_DEFS)) {
      const color = pdef.color;
      const pd = pillarData[pname] || { competency_points: 0, priority_count: 0, covered: 0, gaps: 0 };
      const icon = pdef.icon;
      const catComps = Object.entries(this.state.competencies).filter(([id]) => {
        const meta = this.state.competency_meta[id];
        return meta?.category === pname;
      });
      const avgPct = catComps.length > 0
        ? Math.round(catComps.reduce((s, [, c]) => s + c.percentage, 0) / catComps.length)
        : 0;

      pillarHtml += `
        <div class="card card-centered" style="border-top: 3px solid ${color};">
          <div class="item-row card-header card-header-centered">
            <span>${icon}</span>
            <span class="card-title">${this.escapeHtml(pname)}</span>
          </div>
          <div class="stat-value perf-stat-value-lg" style="color: ${color};">${avgPct}%</div>
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

      strategyHtml += `<div class="flex-col gap-6 overview-priorities">`;
      for (const prio of align.priorities) {
        const statusClass = prio.status === "covered" ? "overview-prio-covered" : "overview-prio-gap";
        const statusIcon = prio.status === "covered" ? "\u2705" : "\u26A0\uFE0F";
        const pillarColor = PILLAR_DEFS[prio.pillar]?.color || "#888";
        const issueLinks = prio.matched_user_issues.map(k => this.renderIssueLink(k)).join(" ");
        const mrLinks = (prio.matched_mrs || []).map(m => `<span class="overview-mr-badge">${this.escapeHtml(m)}</span>`).join(" ");
        const allMatches = [issueLinks, mrLinks].filter(Boolean).join(" ");

        strategyHtml += `
          <div class="overview-priority ${statusClass}">
            <div class="flex-row overview-priority-header">
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
              <div class="text-secondary text-sm mt-4">Consider aligning work to this executive priority</div>
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
            ${this.renderMindmapD3()}
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
          <div class="perf-sunburst-container text-center">
            ${this.generateSunburstSVG()}
          </div>
          <div class="perf-sunburst-ring-legend">
            <div class="perf-sunburst-ring-item"><span class="ring-num">1</span> <b>Pillar</b> &mdash; ${Object.keys(PILLAR_DEFS).length} competency pillars (color = pillar, opacity = score)</div>
            <div class="perf-sunburst-ring-item"><span class="ring-num">2</span> <b>Competency</b> &mdash; ${Object.keys(this.state.competencies).length} individual competencies (color = red/yellow/green by %)</div>
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
        const levelBadge = comp.level_title
          ? `<span class="scoring-comp-level">${this.escapeHtml(comp.level_title)}</span>`
          : "";
        compCards += `
          <div class="card scoring-comp-card${compExpanded ? " expanded" : ""}">
            <div class="flex-row scoring-comp-header" data-action="toggleScoringComp" data-key="${this.escapeHtml(compId)}">
              <span class="scoring-comp-icon">${compIcon}</span>
              <span class="scoring-comp-name">${this.escapeHtml(comp.name)}</span>
              ${levelBadge}
              <span class="scoring-comp-pts">${comp.base_points} pts</span>
            </div>
        `;

        if (compExpanded) {
          const levelTitle = comp.level_title ? `<strong>${this.escapeHtml(comp.level_title)}</strong>` : "";
          const levelDesc = comp.level_description ? `<p class="perf-level-desc">${this.escapeHtml(comp.level_description)}</p>` : "";
          const levelBlock = (levelTitle || levelDesc)
            ? `<div class="scoring-field-row scoring-field-column">
                 <label class="mb-4">Level Expectation</label>
                 <div class="text-md">${levelTitle}${levelDesc}</div>
               </div>`
            : "";
          compCards += `
            <div class="scoring-comp-body" data-comp="${this.escapeHtml(compId)}">
              ${levelBlock}
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

    const levels = cfg.engineering_levels || [];
    const currentLevel = cfg.engineering_level || "sse";
    const levelOptions = levels.map(l =>
      `<option value="${this.escapeHtml(l.id)}"${l.id === currentLevel ? " selected" : ""}>${this.escapeHtml(l.name)}</option>`
    ).join("");

    const scopeMult = (cfg as any).scope_multipliers || {};
    const scopeRows = ["commit", "story", "epic", "anstrat", "strategy"];
    const scopeDescriptions: Record<string, string> = {
      commit: "Individual code commits",
      story: "Jira stories/tasks/bugs",
      epic: "Epics spanning multiple stories",
      anstrat: "Strategic initiatives (ANSTRATs)",
      strategy: "Executive strategy deliverables",
    };

    let scopeMultTable = "";
    for (const scope of scopeRows) {
      const val = scopeMult[scope] ?? 1;
      scopeMultTable += `
        <div class="scoring-field-row scoring-field-row-inline">
          <span class="scoring-scope-label">${this.escapeHtml(scope)}</span>
          <input type="number" class="scoring-input"
                 data-action="setScopeMultiplier" data-scope="${this.escapeHtml(scope)}"
                 value="${val}" min="1" max="20" step="1" />
          <span class="scoring-hint scoring-hint-flush">${scopeDescriptions[scope] || ""}</span>
        </div>`;
    }

    const levelWeights = (cfg as any).level_weights || {};
    const targetScale = levelWeights.target_scale ?? 1.0;
    const effectiveTarget = Math.round((cfg.target_per_competency || 100) * targetScale);
    const roleWeights = levelWeights.role_weights || {};
    const pillarWeights = levelWeights.pillar_weights || {};
    const roles = ["reporter", "assignee", "contributor"];

    let roleWeightTable = `
      <table class="scoring-weight-table">
        <thead><tr><th>Scope</th><th>Reporter</th><th>Assignee</th><th>Contributor</th></tr></thead>
        <tbody>`;
    for (const scope of scopeRows) {
      const sw = roleWeights[scope] || {};
      roleWeightTable += `<tr>
        <td class="capitalize-bold">${this.escapeHtml(scope)}</td>`;
      for (const role of roles) {
        const val = sw[role] ?? 1.0;
        roleWeightTable += `<td><input type="number" class="scoring-input scoring-input-narrow"
          data-action="setRoleWeight" data-scope="${this.escapeHtml(scope)}" data-role="${this.escapeHtml(role)}"
          value="${val}" min="0" max="10" step="0.1" /></td>`;
      }
      roleWeightTable += `</tr>`;
    }
    roleWeightTable += `</tbody></table>`;

    const pillarNames = ["Technical Contribution", "Leadership", "Mentorship", "End-to-End Delivery"];
    let pillarWeightRows = "";
    for (const pillar of pillarNames) {
      const val = pillarWeights[pillar] ?? 1.0;
      pillarWeightRows += `
        <div class="scoring-field-row scoring-field-row-compact">
          <span class="scoring-pillar-label">${this.escapeHtml(pillar)}</span>
          <input type="number" class="scoring-input"
                 data-action="setPillarWeight" data-pillar="${this.escapeHtml(pillar)}"
                 value="${val}" min="0" max="3" step="0.1" />
        </div>`;
    }

    const stratCfg = (cfg as any).strategy_alignment || {};
    const stratEnabled = stratCfg.enabled !== false;
    const stratBonus = stratCfg.bonus_multiplier ?? 1.5;
    const stratEnrichClass = stratCfg.enrich_classification !== false;
    const stratMinOverlap = stratCfg.min_text_overlap_words ?? 3;

    const npuCfg = (cfg as any).npu_settings || {};
    const npuEnabled = npuCfg.enabled === true;
    const npuDevice = npuCfg.device || "CPU";
    const npuThreshold = npuCfg.confidence_threshold ?? 0.35;
    const npuBonusSignals = npuCfg.bonus_signals ?? 2;

    return `
      <div class="perf-tab-panel">
        <div class="section scoring-settings">
          <div class="section-title">Engineering Level</div>
          <div class="scoring-globals">
            <div class="scoring-global-field scoring-global-field-full">
              <label>Your Level</label>
              <select class="perf-select scoring-level-select" data-action="setEngineeringLevel">
                ${levelOptions}
              </select>
              <span class="scoring-hint">Level affects scoring weights, targets, and competency descriptions</span>
            </div>
          </div>
          <div class="scoring-globals mt-8">
            <div class="scoring-global-field">
              <label>Target Scale</label>
              <span class="scoring-value">${targetScale}x</span>
              <span class="scoring-hint">Effective target: ${effectiveTarget} pts for 100%</span>
            </div>
          </div>
        </div>

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
              <span class="scoring-hint">Base points for 100% (scaled by level)</span>
            </div>
          </div>
        </div>

        <div class="section scoring-settings">
          <div class="section-title">Scope Multipliers</div>
          <p class="scoring-hint scoring-hint-mb">Higher-scope work items earn more points. Stories are baseline; epics and ANSTRATs earn proportionally more.</p>
          ${scopeMultTable}
        </div>

        <div class="section scoring-settings">
          <div class="section-title">Level Weight Matrix <span class="scoring-hint font-normal">(${this.escapeHtml(currentLevel.toUpperCase())})</span></div>
          <p class="scoring-hint scoring-hint-mb">Role weights by scope: reporter (defined work) vs assignee (delivered) vs contributor (reviewed/commented).</p>
          ${roleWeightTable}
          <div class="mt-12">
            <div class="scoring-category-label">Pillar Weights</div>
            <p class="scoring-hint scoring-hint-sm">Emphasis areas for your level. Higher = more credit for that category.</p>
            ${pillarWeightRows}
          </div>
          <div class="scoring-example-box">
            <strong>Example: Epic (scope=4x) as ${this.escapeHtml(currentLevel.toUpperCase())} assignee in Technical Contribution</strong>
            <div class="scoring-example-detail">
              base(3) &times; scope(${scopeMult.epic ?? 4}) &times; role(${(roleWeights.epic || {}).assignee ?? 1.0}) &times; pillar(${pillarWeights["Technical Contribution"] ?? 1.0}) = <strong>${Math.round(3 * (scopeMult.epic ?? 4) * ((roleWeights.epic || {}).assignee ?? 1.0) * (pillarWeights["Technical Contribution"] ?? 1.0))} pts</strong>
            </div>
          </div>
        </div>

        <div class="section scoring-settings">
          <div class="section-title">Strategy Alignment</div>
          <p class="scoring-hint scoring-hint-mb">Reward work that aligns with director-communicated business priorities from executive emails.</p>
          <div class="scoring-globals">
            <div class="scoring-global-field">
              <label>Enabled</label>
              <label class="scoring-toggle">
                <input type="checkbox" data-action="setStrategyEnabled" ${stratEnabled ? "checked" : ""} />
                <span class="scoring-toggle-label">${stratEnabled ? "On" : "Off"}</span>
              </label>
            </div>
            <div class="scoring-global-field">
              <label>Bonus Multiplier</label>
              <input type="number" class="scoring-input"
                     data-action="setStrategyBonus" value="${stratBonus}" min="1" max="3" step="0.1" />
              <span class="scoring-hint">Applied to strategy-aligned events</span>
            </div>
            <div class="scoring-global-field">
              <label>Enrich Classification</label>
              <label class="scoring-toggle">
                <input type="checkbox" data-action="setStrategyEnrich" ${stratEnrichClass ? "checked" : ""} />
                <span class="scoring-toggle-label">${stratEnrichClass ? "On" : "Off"}</span>
              </label>
              <span class="scoring-hint">Append strategy context to event text</span>
            </div>
            <div class="scoring-global-field">
              <label>Min Text Overlap</label>
              <input type="number" class="scoring-input"
                     data-action="setStrategyMinOverlap" value="${stratMinOverlap}" min="1" max="10" step="1" />
              <span class="scoring-hint">Words needed for fuzzy match</span>
            </div>
          </div>
        </div>

        <div class="section scoring-settings">
          <div class="section-title">Executive Email Sources</div>
          <p class="scoring-hint scoring-hint-mb">Director emails scraped for strategy alignment. Add or remove sender addresses, and manage the cached email archive.</p>

          <div class="exec-senders-section">
            <label class="scoring-field-label scoring-label-block">Configured Senders</label>
            <div class="flex-row flex-wrap gap-6 scoring-tags exec-senders-list">
              ${this.state.executive_senders.map(s =>
                `<span class="scoring-tag">${this.escapeHtml(s)}<span class="scoring-tag-x"
                  data-action="removeExecutiveSender"
                  data-value="${this.escapeHtml(s)}">&times;</span></span>`
              ).join("")}
              <input type="text" class="scoring-tag-input" placeholder="+ add email address"
                     data-action="addExecutiveSender" />
            </div>
            ${this.state.executive_senders.length === 0
              ? `<span class="scoring-hint text-warning">No senders configured. Strategy alignment requires at least one director email.</span>`
              : ""}
          </div>

          <div class="mt-12">
            <label class="scoring-field-label scoring-label-block">Cached Emails (${this.state.executive_emails.length})</label>
            ${this.state.executive_emails.length > 0
              ? `<div class="exec-emails-list">
                  ${this.state.executive_emails.slice(0, 20).map(em => `
                    <div class="exec-email-row">
                      <span class="exec-email-date">${this.escapeHtml(em.date || "")}</span>
                      <span class="exec-email-sender">${this.escapeHtml(em.sender || "")}</span>
                      <span class="exec-email-subject">${this.escapeHtml((em.subject || "").substring(0, 60))}</span>
                      <span class="exec-email-delete scoring-tag-x"
                            data-action="deleteExecutiveEmail"
                            data-value="${this.escapeHtml(em.email_id)}"
                            title="Delete cached email">&times;</span>
                    </div>
                  `).join("")}
                  ${this.state.executive_emails.length > 20
                    ? `<div class="scoring-hint p-8">...and ${this.state.executive_emails.length - 20} more</div>`
                    : ""}
                </div>`
              : `<span class="scoring-hint">No cached emails. Use Backfill to fetch this quarter's emails.</span>`
            }
          </div>

          <div class="d-flex gap-8 mt-12">
            <button class="btn btn-sm btn-primary" data-action="backfillExecutiveEmails">Backfill Quarter</button>
            <button class="btn btn-sm" data-action="refreshExecutiveEmails">Refresh List</button>
          </div>
        </div>

        <div class="section scoring-settings">
          <div class="section-title">NPU Classification</div>
          <p class="scoring-hint scoring-hint-mb">Optional: Use embedding similarity (all-MiniLM-L6-v2) for smarter competency matching beyond keywords.</p>
          <div class="scoring-globals">
            <div class="scoring-global-field">
              <label>Enabled</label>
              <label class="scoring-toggle">
                <input type="checkbox" data-action="setNpuEnabled" ${npuEnabled ? "checked" : ""} />
                <span class="scoring-toggle-label">${npuEnabled ? "On" : "Off"}</span>
              </label>
            </div>
            <div class="scoring-global-field">
              <label>Device</label>
              <select class="perf-select scoring-input" data-action="setNpuDevice">
                <option value="CPU" ${npuDevice === "CPU" ? "selected" : ""}>CPU</option>
                <option value="NPU" ${npuDevice === "NPU" ? "selected" : ""}>NPU</option>
                <option value="AUTO" ${npuDevice === "AUTO" ? "selected" : ""}>Auto</option>
              </select>
            </div>
            <div class="scoring-global-field">
              <label>Confidence</label>
              <input type="number" class="scoring-input"
                     data-action="setNpuThreshold" value="${npuThreshold}" min="0.1" max="0.9" step="0.05" />
              <span class="scoring-hint">Similarity threshold</span>
            </div>
            <div class="scoring-global-field">
              <label>Bonus Signals</label>
              <input type="number" class="scoring-input"
                     data-action="setNpuBonusSignals" value="${npuBonusSignals}" min="1" max="5" step="1" />
              <span class="scoring-hint">Extra signals per NPU match</span>
            </div>
          </div>
        </div>

        <div class="section scoring-settings">
          <div class="section-title">Per-Competency Configuration</div>
          ${compCards}
        </div>

        <div class="scoring-actions">
          <button class="btn btn-sm" data-action="resetScoringConfig">Reset to Defaults</button>
        </div>
      </div>
    `;
  }

  private renderProgressTab(): string {
    return `
      <div class="perf-tab-panel">
        <!-- Evaluation Strategy -->
        <div class="section">
          <div class="perf-strategy-outline">
            <div class="perf-strategy-title">How Evaluation Works</div>
            <div class="perf-strategy-steps">
              <div class="perf-strategy-step">
                <span class="perf-strategy-num">1</span>
                <span>Events are auto-tagged to questions by competency category during daily collection</span>
              </div>
              <div class="perf-strategy-step">
                <span class="perf-strategy-num">2</span>
                <span>The top 20 evidence items (by points) are selected per question</span>
              </div>
              <div class="perf-strategy-step">
                <span class="perf-strategy-num">3</span>
                <span>Evidence + manual notes + competency scores are sent to the LLM</span>
              </div>
              <div class="perf-strategy-step">
                <span class="perf-strategy-num">4</span>
                <span>A first-person draft response is generated, ready for your review form</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Quarterly Questions -->
        <div class="section">
          <div class="section-title">
            <span>Quarterly Questions</span>
            <button class="btn btn-xs" data-action="addQuestion">+ Add Question</button>
            <button class="btn btn-xs" data-action="evaluateAll">Re-score All</button>
          </div>
          <div class="perf-add-question-form" id="addQuestionForm">
            <input type="text" id="newQuestionText" placeholder="Enter your question..." />
            <div class="actions-row perf-add-question-actions">
              <button class="btn btn-xs btn-primary" data-action="saveQuestion">Save</button>
              <button class="btn btn-xs" data-action="cancelAddQuestion">Cancel</button>
            </div>
          </div>
          <div class="perf-question-cards">
            ${this.renderQuestions()}
          </div>
        </div>
      </div>
    `;
  }

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
        const catVals = Object.keys(PILLAR_DEFS).map(k => cp[k] || 0);
        const maxCat = Math.max(...catVals, 1);
        const calBars = Object.entries(PILLAR_DEFS).map(([pn, pd]) => {
          const v = cp[pn] || 0;
          return `<div class="perf-cal-cat-bar" title="${this.escapeHtml(pn)}: ${v}pts" style="height:${Math.round(v / maxCat * 12)}px; background:${pd.color};"></div>`;
        }).join("");
        eventInfo = `
          <div class="perf-cal-cats">${calBars}</div>
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
    const catBreakdown = Object.entries(PILLAR_DEFS).map(([pn, pd]) => {
      const v = cp[pn] || 0;
      return `<div class="perf-day-cat"><span class="perf-day-cat-dot" style="background:${pd.color};"></span> ${this.escapeHtml(pn)} ${v}pts</div>`;
    }).join("\n          ");

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
          ${catBreakdown}
        </div>
    `;

    // Event list with lineage
    if (detail && detail.has_data && detail.events.length > 0) {
      html += `<div class="flex-col gap-4 perf-day-events">`;
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
              <span class="text-muted-sm perf-day-event-type">${this.escapeHtml(ev.type)}</span>
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

  private getHeatColor(pct: number): string {
    if (pct >= 80) return "#10b981";
    if (pct >= 50) return "#f59e0b";
    if (pct >= 25) return "#f97316";
    return "#ef4444";
  }

  /**
   * Build a unified graph combining:
   *   Root -> Pillars -> Competencies (heat-colored circles)
   *                   -> ANSTRATs (hexagon-ish) -> Epics -> Issues
   *   Plus Strategy diamonds at the outer ring with evidence links
   *   Pillars connect to ANSTRATs via issue-key overlap with competency evidence
   */
  private buildCombinedMindmapGraph(): { nodes: any[]; links: any[]; view: string; pillarInfo: any[]; stats: any } | null {
    const meta = this.state.competency_meta || {};
    const comps = this.state.competencies || {};
    const h = this.state.issue_hierarchy;
    const hasCompetencies = Object.keys(meta).length > 0;
    const hasIssues = h && h.total_issues > 0;

    if (!hasCompetencies && !hasIssues) return null;

    const nodes: any[] = [];
    const links: any[] = [];

    const pillarNames = Object.keys(PILLAR_DEFS);
    const angleStep = 360 / pillarNames.length;
    const pillarDefs: Record<string, { label: string; color: string; angle: number; compIds: string[] }> = {};
    pillarNames.forEach((name, i) => {
      pillarDefs[name] = { label: name, color: PILLAR_DEFS[name].color, angle: i * angleStep, compIds: [] };
    });

    for (const [compId, m] of Object.entries(meta)) {
      const cat = m.category || "Technical Contribution";
      if (pillarDefs[cat]) pillarDefs[cat].compIds.push(compId);
    }

    const allPillarIds = Object.keys(pillarDefs).map(n => `pillar_${n.replace(/[^a-z]/gi, "_")}`);

    // ---- Root ----
    const rootId = "root";
    const overallPct = this.state.overall_percentage || 0;
    nodes.push({
      id: rootId,
      label: this.state.quarter,
      sublabel: `${overallPct}% overall`,
      type: "root",
      percentage: overallPct,
      size: 30,
      color: "#667eea",
      pillars: allPillarIds,
    });

    let compCount = 0;
    let anstratCount = 0;
    let epicCount = 0;
    let issueCount = 0;
    let stratCount = 0;
    let evidenceLinkCount = 0;

    // Build per-competency issue key sets for linking
    const compEvidenceKeys: Record<string, Set<string>> = {};
    for (const [compId, events] of Object.entries(this.state.competency_evidence || {})) {
      const keys = new Set<string>();
      for (const ev of events) {
        for (const k of (ev.issue_keys || [])) keys.add(k);
      }
      compEvidenceKeys[compId] = keys;
    }

    // Collect all issue keys per ANSTRAT for pillar-linking
    const anstratIssueKeys: Record<string, Set<string>> = {};

    // ---- Pillars + Competencies ----
    for (const [pillarName, pDef] of Object.entries(pillarDefs)) {
      const pillarId = `pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;
      const pillarComps = pDef.compIds;
      const avgPct = pillarComps.length > 0
        ? Math.round(pillarComps.reduce((s, id) => s + (comps[id]?.percentage || 0), 0) / pillarComps.length)
        : 0;

      const pillarSummary = this.state.strategy_alignment?.pillar_summary?.[pillarName];

      nodes.push({
        id: pillarId,
        label: pDef.label,
        type: "pillar",
        percentage: avgPct,
        size: 22,
        color: pDef.color,
        heatColor: this.getHeatColor(avgPct),
        angle: pDef.angle,
        compCount: pillarComps.length,
        priorityCount: pillarSummary?.priority_count || 0,
        covered: pillarSummary?.covered || 0,
        gaps: pillarSummary?.gaps || 0,
        pillars: [pillarId],
      });
      links.push({ source: rootId, target: pillarId, type: "hierarchy" });

      for (const compId of pillarComps) {
        compCount++;
        const m = meta[compId];
        const c = comps[compId];
        const pct = c?.percentage || m?.percentage || 0;
        const evidenceCount = m?.evidence_count || 0;

        const nodeId = `comp_${compId}`;
        const compTint = pillarTint(pDef.color, "competency", pct);
        nodes.push({
          id: nodeId,
          compId,
          label: m.name,
          type: "competency",
          category: m.category,
          goal: m.goal,
          description: m.description,
          percentage: pct,
          points: c?.points || m?.points || 0,
          target: m.target || 100,
          evidenceCount,
          size: Math.min(Math.max(evidenceCount * 1.5 + 8, 8), 20),
          color: compTint,
          heatColor: compTint,
          pillarColor: pDef.color,
          pillarId,
          pillarAngle: pDef.angle,
          pillars: [pillarId],
        });
        links.push({ source: pillarId, target: nodeId, type: "hierarchy" });
      }
    }

    // ---- ANSTRAT / Epic / Issue hierarchy ----
    if (hasIssues && h) {
      const issueStrategies = Array.isArray(h.strategies) ? h.strategies : [];
      const unattachedEpics = Array.isArray(h.unattached_epics) ? h.unattached_epics : [];
      const uncatIssues = Array.isArray(h.uncategorized) ? h.uncategorized : [];

      const fallbackAnstratColor = "#06b6d4";
      const fallbackEpicColor = "#f97316";
      const fallbackIssueColor = "#e879f9";

      const pillarIdToHex: Record<string, string> = {};
      for (const [pn, pd] of Object.entries(pillarDefs)) {
        pillarIdToHex[`pillar_${pn.replace(/[^a-z]/gi, "_")}`] = pd.color;
      }

      // Build ANSTRAT groups (only real ANSTRATs)
      const anstratNodeIds: string[] = [];
      issueStrategies.forEach((group, gi) => {
        anstratCount++;
        const gId = `anstrat_${gi}`;
        anstratNodeIds.push(gId);
        const allKeys = new Set<string>();

        nodes.push({
          id: gId,
          label: group.key.replace(/^ANSTRAT-/, "AN-"),
          fullKey: group.key,
          summary: group.summary,
          type: "anstrat",
          points: group.points,
          size: Math.min(Math.max(group.points / 8, 16), 24),
          color: fallbackAnstratColor,
          eventCount: group.event_count || 0,
          pillars: [] as string[],
        });

        (group.children || []).forEach((child, ci) => {
          epicCount++;
          const cId = `${gId}_epic_${ci}`;
          nodes.push({
            id: cId,
            label: child.key.replace(/^AAP-/, ""),
            fullKey: child.key,
            summary: child.summary,
            type: "epic",
            points: child.points,
            size: Math.min(Math.max(child.points / 8, 10), 18),
            color: fallbackEpicColor,
            eventCount: child.event_count || 0,
            parentAnstrat: gId,
            pillars: [] as string[],
          });
          links.push({ source: gId, target: cId, type: "parent" });
          allKeys.add(child.key);

          (child.children || []).forEach((issue, ii) => {
            issueCount++;
            const iId = `${cId}_issue_${ii}`;
            nodes.push({
              id: iId,
              label: issue.key.replace(/^AAP-/, ""),
              fullKey: issue.key,
              summary: issue.summary,
              type: issue.type || "task",
              points: issue.points,
              size: Math.min(Math.max(issue.points / 10, 6), 12),
              color: fallbackIssueColor,
              eventCount: issue.event_count || 0,
              parentAnstrat: gId,
              pillars: [] as string[],
            });
            links.push({ source: cId, target: iId, type: "parent" });
            allKeys.add(issue.key);
          });
        });

        anstratIssueKeys[gId] = allKeys;
      });

      // Helper: find best pillar for an issue key via competency evidence overlap
      const findPillarForKey = (key: string): string | null => {
        for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
          if (compKeys.has(key)) {
            const cat = meta[compId]?.category || "Technical Contribution";
            return `pillar_${cat.replace(/[^a-z]/gi, "_")}`;
          }
        }
        return null;
      };

      // Unattached epics: link directly to pillar nodes
      unattachedEpics.forEach((epic, ei) => {
        epicCount++;
        const eId = `unattached_epic_${ei}`;
        const pillar = findPillarForKey(epic.key);
        const targetPillar = pillar || rootId;

        const epicPillarHex = pillar ? (pillarIdToHex[pillar] || fallbackEpicColor) : fallbackEpicColor;
        nodes.push({
          id: eId,
          label: epic.key.replace(/^AAP-/, ""),
          fullKey: epic.key,
          summary: epic.summary,
          type: "epic",
          points: epic.points,
          size: Math.min(Math.max(epic.points / 8, 10), 18),
          color: pillar ? pillarTint(epicPillarHex, "epic") : fallbackEpicColor,
          eventCount: epic.event_count || 0,
          pillars: pillar ? [pillar] : allPillarIds.slice(),
        });
        links.push({ source: targetPillar, target: eId, type: "hierarchy" });

        (epic.children || []).forEach((issue, ii) => {
          issueCount++;
          const iId = `${eId}_issue_${ii}`;
          const issuePillar = findPillarForKey(issue.key) || pillar;
          const issuePillarHex = issuePillar ? (pillarIdToHex[issuePillar] || fallbackIssueColor) : fallbackIssueColor;
          nodes.push({
            id: iId,
            label: issue.key.replace(/^AAP-/, ""),
            fullKey: issue.key,
            summary: issue.summary,
            type: issue.type || "task",
            points: issue.points,
            size: Math.min(Math.max(issue.points / 10, 6), 12),
            color: issuePillar ? pillarTint(issuePillarHex, "issue") : fallbackIssueColor,
            eventCount: issue.event_count || 0,
            pillars: issuePillar ? [issuePillar] : allPillarIds.slice(),
          });
          links.push({ source: eId, target: iId, type: "parent" });
        });
      });

      // Uncategorized issues: link directly to pillar nodes
      uncatIssues.forEach((issue, ui) => {
        issueCount++;
        const uId = `uncat_issue_${ui}`;
        const pillar = findPillarForKey(issue.key);
        const targetPillar = pillar || rootId;
        const uncatPillarHex = pillar ? (pillarIdToHex[pillar] || fallbackIssueColor) : fallbackIssueColor;

        nodes.push({
          id: uId,
          label: issue.key.replace(/^AAP-/, ""),
          fullKey: issue.key,
          summary: issue.summary,
          type: issue.type || "task",
          points: issue.points,
          size: Math.min(Math.max(issue.points / 10, 6), 12),
          color: pillar ? pillarTint(uncatPillarHex, "issue") : fallbackIssueColor,
          eventCount: issue.event_count || 0,
          pillars: pillar ? [pillar] : allPillarIds.slice(),
        });
        links.push({ source: targetPillar, target: uId, type: "hierarchy" });
      });

      // Link ANSTRATs to competency leaf nodes that share issue keys (solid lines)
      const nodeMap = new Map(nodes.map(n => [n.id, n]));
      for (const [gId, issueKeys] of Object.entries(anstratIssueKeys)) {
        const linkedCompIds: string[] = [];

        for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
          let shared = 0;
          for (const k of compKeys) {
            if (issueKeys.has(k)) shared++;
          }
          if (shared > 0) {
            linkedCompIds.push(compId);
            links.push({
              source: `comp_${compId}`,
              target: gId,
              type: "comp_anstrat",
              weight: shared,
            });
          }
        }

        const anstratNode = nodeMap.get(gId);
        if (linkedCompIds.length > 0 && anstratNode) {
          const assocPillars = new Set<string>();
          for (const cid of linkedCompIds) {
            const cat = meta[cid]?.category || "Technical Contribution";
            assocPillars.add(`pillar_${cat.replace(/[^a-z]/gi, "_")}`);
          }
          anstratNode.pillars = Array.from(assocPillars);
        } else {
          if (anstratNode) anstratNode.pillars = allPillarIds.slice();
          links.push({ source: rootId, target: gId, type: "parent" });
        }

        // Propagate pillar associations to child epics and issues
        const anstratPillars = anstratNode?.pillars || allPillarIds;
        for (const n of nodes) {
          if (n.parentAnstrat === gId) {
            n.pillars = anstratPillars;
          }
        }
      }

      // Recolor ANSTRAT/epic/issue nodes now that pillars are assigned
      for (const n of nodes) {
        if (n.pillars && n.pillars.length > 0 && n.pillars.length < allPillarIds.length) {
          const primaryPillarHex = pillarIdToHex[n.pillars[0]] || "#888";
          if (n.type === "anstrat") n.color = pillarTint(primaryPillarHex, "anstrat");
          else if (n.type === "epic") n.color = pillarTint(primaryPillarHex, "epic");
          else if (n.type === "task" || n.type === "bug" || n.type === "story") n.color = pillarTint(primaryPillarHex, "issue");
        }
      }
    }

    // ---- Executive Strategy diamonds ----
    const alignment = this.state.strategy_alignment;
    if (alignment?.priorities) {
      for (const [pi, priority] of alignment.priorities.entries()) {
        stratCount++;
        const stratId = `execstrat_${pi}`;
        const isCovered = priority.status === "covered";
        const pillarName = priority.pillar || "End-to-End Delivery";
        const pillarId = `pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;

        const stratPillars = new Set<string>([pillarId]);
        const priorityKeys = new Set(priority.issue_keys || []);

        for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
          let shared = 0;
          for (const k of compKeys) {
            if (priorityKeys.has(k)) shared++;
          }
          if (shared > 0) {
            evidenceLinkCount++;
            links.push({
              source: `comp_${compId}`,
              target: stratId,
              type: "evidence",
              weight: shared,
            });
            const compCat = meta[compId]?.category || "Technical Contribution";
            stratPillars.add(`pillar_${compCat.replace(/[^a-z]/gi, "_")}`);
          }
        }

        const stratPillarHex = PILLAR_DEFS[pillarName]?.color || "#888";
        const stratTint = pillarTint(stratPillarHex, "strategy", undefined, isCovered);
        nodes.push({
          id: stratId,
          label: priority.name.length > 30 ? priority.name.substring(0, 27) + "..." : priority.name,
          fullLabel: priority.name,
          type: "strategy",
          status: priority.status,
          context: priority.context,
          pillar: pillarName,
          size: 12,
          color: stratTint,
          heatColor: stratTint,
          isCovered,
          issueKeys: priority.issue_keys || [],
          matchedIssues: priority.matched_user_issues || [],
          matchedMrs: priority.matched_mrs || [],
          pillarId,
          pillars: Array.from(stratPillars),
        });

        links.push({ source: pillarId, target: stratId, type: "pillar_strategy" });
      }

      // Link ANSTRATs to strategies where they share issue keys (solid lines)
      for (const [pi2, priority2] of alignment.priorities.entries()) {
        const stratId2 = `execstrat_${pi2}`;
        const stratKeys = new Set(priority2.issue_keys || []);
        if (stratKeys.size === 0) continue;

        for (const [gId, issueKeys] of Object.entries(anstratIssueKeys)) {
          let shared = 0;
          for (const k of issueKeys) {
            if (stratKeys.has(k)) shared++;
          }
          if (shared > 0) {
            links.push({
              source: gId,
              target: stratId2,
              type: "anstrat_strategy",
              weight: shared,
            });
          }
        }
      }
    }

    const pillarInfo = Object.entries(pillarDefs).map(([name, def]) => ({
      id: `pillar_${name.replace(/[^a-z]/gi, "_")}`,
      label: def.label,
      color: def.color,
    }));

    return {
      nodes,
      links,
      view: "combined",
      pillarInfo,
      stats: {
        pillars: Object.keys(pillarDefs).length,
        competencies: compCount,
        anstrats: anstratCount,
        epics: epicCount,
        issues: issueCount,
        strategies: stratCount,
        evidenceLinks: evidenceLinkCount,
      },
    };
  }

  private renderMindmapD3(): string {
    const graphData = this.buildCombinedMindmapGraph();

    if (!graphData) {
      return this.getEmptyStateHtml("--", "Mindmap will appear after data collection.");
    }

    const graphJson = JSON.stringify(graphData);
    const s = graphData.stats;

    const parts: string[] = [];
    if (s.pillars) parts.push(`${s.pillars} pillars`);
    if (s.competencies) parts.push(`${s.competencies} competencies`);
    if (s.anstrats) parts.push(`${s.anstrats} ANSTRATs`);
    if (s.epics) parts.push(`${s.epics} epics`);
    if (s.issues) parts.push(`${s.issues} issues`);
    if (s.strategies) parts.push(`${s.strategies} strategies`);
    const statsHtml = parts.join(" &middot; ");

    const pillarCheckboxes = graphData.pillarInfo.map((p: any) =>
      `<label class="perf-mindmap-toggle perf-pillar-filter" style="color:${p.color}">` +
      `<input type="checkbox" class="perfMmPillarChk" data-pillar="${this.escapeHtml(p.id)}" checked /> ${this.escapeHtml(p.label)}</label>`
    ).join("");

    return `
      <div class="perf-mindmap-d3-wrapper">
        <div class="perf-mindmap-d3-header">
          <div class="perf-mindmap-d3-filters">
            ${pillarCheckboxes}
            <span class="perf-mindmap-d3-sep">|</span>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="competency" checked /> Competencies</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="anstrat" checked /> ANSTRATs</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="epic" checked /> Epics</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="task,bug,story" checked /> Issues</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="strategy" checked /> Strategies</label>
          </div>
          <span class="perf-mindmap-d3-stats" id="perfMindmapStats">${statsHtml}</span>
          <div class="perf-mindmap-d3-controls">
            <label class="perf-mindmap-toggle"><input type="checkbox" id="perfMmLabels" /> Labels</label>
            <label class="perf-mindmap-toggle"><input type="checkbox" id="perfMmSticky" /> Sticky</label>
            <button class="btn btn-xs" id="perfMmReheat" title="Reheat simulation">Reheat</button>
            <button class="btn btn-xs" id="perfMmFit" title="Fit to view">Fit</button>
            <button class="btn btn-xs mindmap-physics-toggle" id="perfMmPhysicsToggle" title="Physics Controls" data-action="togglePerfPhysics">&#x2699;&#xFE0F;</button>
          </div>
        </div>
        <div class="mindmap-physics-panel" id="perfMmPhysicsPanel" style="display: none;">
          <div class="physics-row">
            <div class="physics-control">
              <label for="perfMmChargeSlider">Repulsion <span class="physics-value" id="perfMmChargeValue">-200</span></label>
              <input type="range" id="perfMmChargeSlider" min="-800" max="0" step="10" value="-200" />
            </div>
            <div class="physics-control">
              <label for="perfMmLinkDistSlider">Link Distance <span class="physics-value" id="perfMmLinkDistValue">120</span></label>
              <input type="range" id="perfMmLinkDistSlider" min="20" max="400" step="5" value="120" />
            </div>
            <div class="physics-control">
              <label for="perfMmCollisionSlider">Padding <span class="physics-value" id="perfMmCollisionValue">4</span></label>
              <input type="range" id="perfMmCollisionSlider" min="0" max="30" step="1" value="4" />
            </div>
          </div>
          <div class="physics-row">
            <div class="physics-control">
              <label for="perfMmRadialSlider">Radial Spread <span class="physics-value" id="perfMmRadialValue">1.0</span></label>
              <input type="range" id="perfMmRadialSlider" min="20" max="300" step="5" value="100" />
            </div>
            <div class="physics-control">
              <label for="perfMmDecaySlider">Cooling <span class="physics-value" id="perfMmDecayValue">0.012</span></label>
              <input type="range" id="perfMmDecaySlider" min="1" max="100" step="1" value="12" />
            </div>
            <div class="physics-control">
              <label for="perfMmVelocitySlider">Friction <span class="physics-value" id="perfMmVelocityValue">0.35</span></label>
              <input type="range" id="perfMmVelocitySlider" min="0" max="100" step="1" value="35" />
            </div>
          </div>
          <div class="physics-row physics-actions">
            <button class="btn btn-xs" id="perfMmPhysicsReset" title="Reset to defaults">Reset</button>
            <button class="btn btn-xs" id="perfMmPhysicsPause" title="Pause/resume simulation">Pause</button>
            <button class="btn btn-xs" id="perfMmPhysicsUnstick" title="Release all pinned nodes">Unstick All</button>
          </div>
        </div>
        <div class="perf-mindmap-d3-graph" id="perfMindmapGraph">
          <svg id="perfMindmapSvg" class="svg-full">
            <defs>
              <filter id="perfGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="2.5" result="blur"/>
                <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
              <filter id="perfHeatGlow" x="-100%" y="-100%" width="300%" height="300%">
                <feGaussianBlur stdDeviation="25" result="blur"/>
                <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            </defs>
          </svg>
        </div>
        <div class="perf-mindmap-d3-tooltip" id="perfMindmapTooltip"></div>
        <div class="perf-mindmap-d3-legend">
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-root"></span>Root</span>
          ${Object.entries(PILLAR_DEFS).map(([name, def]) =>
            `<span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot" style="background:${def.color}"></span>${name}</span>`
          ).join("\n          ")}
          <span class="legend-separator">|</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-ring legend-dot-default"></span>Pillar</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-small"></span>Competency</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-roundrect legend-dot-default"></span>ANSTRAT</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-triangle legend-dot-default"></span>Epic</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-square legend-dot-default"></span>Issue</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-diamond-legend legend-dot-default"></span>Strategy</span>
          <span class="legend-separator">|</span>
          <span class="flex-row gap-4 legend-item-compact" title="Solid diamond = covered"><span class="dot legend-dot perf-mm-diamond-legend legend-dot-default"></span>Covered</span>
          <span class="flex-row gap-4 legend-item-compact" title="Dashed diamond = gap"><span class="dot legend-dot perf-mm-diamond-legend perf-help-dot-comparison"></span>Gap</span>
        </div>
      </div>
      <script id="perfMindmapData" type="application/json">${graphJson}</script>
    `;
  }

  // ============================================================
  // Sunburst (existing, preserved)
  // ============================================================

  private generateSunburstSVG(): string {
    const width = 590;
    const height = 590;
    const cx = width / 2;
    const cy = height / 2;
    const r0 = 80;
    const r1 = 155;
    const r2 = 260;

    const competencies = this.state.competencies;
    const overall = this.state.overall_percentage;

    const pillarColors: Record<string, string> = {};
    for (const [pn, pd] of Object.entries(PILLAR_DEFS)) pillarColors[pn] = pd.color;

    const catMap: Record<string, string[]> = {};
    for (const [compId, m] of Object.entries(this.state.competency_meta)) {
      const cat = m.category || "Technical Contribution";
      if (!catMap[cat]) catMap[cat] = [];
      catMap[cat].push(compId);
    }
    const metaCategories = Object.keys(PILLAR_DEFS).map(name => ({
      id: name.toLowerCase().replace(/[^a-z]+/g, "_"),
      name,
      competencies: catMap[name] || [],
    }));

    let paths = "";
    const bg = "var(--bg-primary, #1a1a2e)";

    const centerColor = this.getColorForPercentage(overall);
    paths += `
      <circle cx="${cx}" cy="${cy}" r="${r0 - 5}" fill="${centerColor}" opacity="0.15"/>
      <circle cx="${cx}" cy="${cy}" r="${r0 - 5}" fill="none" stroke="${centerColor}" stroke-width="2" opacity="0.4"/>
      <text x="${cx}" y="${cy - 12}" text-anchor="middle" dominant-baseline="middle"
            font-size="38" font-weight="bold" fill="${centerColor}">${overall}%</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle"
            font-size="13" fill="#888">${this.state.quarter || "Q1 2026"}</text>
    `;

    const categoryAngle = 360 / metaCategories.length;
    let startAngle = -90;

    metaCategories.forEach((cat) => {
      const pColor = pillarColors[cat.name] || "#888";
      const catValues = cat.competencies.map((c) => competencies[c]?.percentage || 0);
      const catAvg = catValues.length > 0 ? Math.round(catValues.reduce((a, b) => a + b, 0) / catValues.length) : 0;

      // Ring 1: Pillar segment
      const catPath = this.arcPath(cx, cy, r0, r1, startAngle, categoryAngle - 2);
      const catOpacity = 0.3 + (catAvg / 100) * 0.5;
      paths += `
        <path d="${catPath}" fill="${pColor}" opacity="${catOpacity.toFixed(2)}" stroke="${bg}" stroke-width="2">
          <title>${cat.name}: ${catAvg}%</title>
        </path>
      `;

      const labelRad = ((startAngle + categoryAngle / 2) * Math.PI) / 180;
      const labelR = (r0 + r1) / 2;
      const lx = cx + labelR * Math.cos(labelRad);
      const ly = cy + labelR * Math.sin(labelRad);
      const labelAngle = startAngle + categoryAngle / 2;
      const rotate = labelAngle > 0 && labelAngle < 180 ? labelAngle + 90 + 180 : labelAngle + 90;
      const pillarShort = cat.name.replace("End-to-End ", "E2E ").replace("Technical ", "Tech ");
      paths += `
        <text x="${lx.toFixed(1)}" y="${(ly - 8).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
              font-size="11" font-weight="600" fill="#fff" opacity="0.9"
              transform="rotate(${rotate.toFixed(1)},${lx.toFixed(1)},${ly.toFixed(1)})">${pillarShort}</text>
        <text x="${lx.toFixed(1)}" y="${(ly + 6).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
              font-size="12" font-weight="700" fill="#fff" opacity="0.95"
              transform="rotate(${rotate.toFixed(1)},${lx.toFixed(1)},${ly.toFixed(1)})">${catAvg}%</text>
      `;

      // Ring 2: Competency segments
      const compAngle = categoryAngle / Math.max(cat.competencies.length, 1);
      let compStart = startAngle;

      cat.competencies.forEach((compId) => {
        const compPct = competencies[compId]?.percentage || 0;
        const compColor = this.getColorForPercentage(compPct);
        const compPath = this.arcPath(cx, cy, r1, r2, compStart, compAngle - 1);

        paths += `
          <path d="${compPath}" fill="${compColor}" opacity="0.8"
                stroke="${bg}" stroke-width="1">
            <title>${this.formatCompetencyName(compId)}: ${compPct}%</title>
          </path>
        `;

        const cRad = ((compStart + compAngle / 2) * Math.PI) / 180;
        const cR = (r1 + r2) / 2;
        const clx = cx + cR * Math.cos(cRad);
        const cly = cy + cR * Math.sin(cRad);
        const cAngle = compStart + compAngle / 2;
        const cRotate = cAngle > 0 && cAngle < 180 ? cAngle + 90 + 180 : cAngle + 90;
        const shortName = this.formatCompetencyName(compId);
        const displayName = shortName.length > 18 ? shortName.substring(0, 16) + ".." : shortName;
        paths += `
          <text x="${clx.toFixed(1)}" y="${(cly - 6).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
                font-size="10" fill="#fff" opacity="0.85"
                transform="rotate(${cRotate.toFixed(1)},${clx.toFixed(1)},${cly.toFixed(1)})">${displayName}</text>
          <text x="${clx.toFixed(1)}" y="${(cly + 7).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
                font-size="11" font-weight="600" fill="#fff" opacity="0.95"
                transform="rotate(${cRotate.toFixed(1)},${clx.toFixed(1)},${cly.toFixed(1)})">${compPct}%</text>
        `;

        compStart += compAngle;
      });

      startAngle += categoryAngle;
    });

    // Legend
    const legendY = height - 10;
    let legendX = 30;
    const legendItems = Object.entries(PILLAR_DEFS).map(([name, def]) => ({
      color: def.color, label: name.replace("End-to-End ", "E2E "),
    }));
    legendItems.forEach((item) => {
      paths += `<rect x="${legendX}" y="${legendY - 10}" width="14" height="14" rx="2" fill="${item.color}" opacity="0.8"/>`;
      paths += `<text x="${legendX + 18}" y="${legendY}" font-size="16" fill="#888">${item.label}</text>`;
      legendX += item.label.length * 9.5 + 28;
    });

    return `
      <svg class="perf-sunburst-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
           xmlns="http://www.w3.org/2000/svg">
        <style>
          text { font-family: system-ui, -apple-system, sans-serif; }
          path:hover { opacity: 1 !important; filter: brightness(1.2); }
        </style>
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
              <div class="flex-col perf-evidence-list">
                ${evidence.map(ev => {
                  const titleHtml = ev.url
                    ? `<a href="${this.escapeHtml(ev.url)}" class="perf-event-link">${this.escapeHtml(ev.title)}</a>`
                    : this.escapeHtml(ev.title);
                  return `
                    <div class="card perf-evidence-card">
                      <div class="perf-evidence-card-top">
                        <span class="perf-source-badge perf-source-${this.escapeHtml(ev.source)}">${this.escapeHtml(ev.source)}</span>
                        <span class="perf-evidence-date">${this.escapeHtml(ev.date)}</span>
                        <span class="perf-evidence-pts">${ev.points} pts</span>
                      </div>
                      <div class="perf-evidence-card-title">${titleHtml}</div>
                      <div class="flex-row perf-evidence-card-meta">
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
            <div class="flex-col gap-4 perf-competency-header" data-action="toggleCompetency" data-key="${this.escapeHtml(id)}">
              <div class="perf-comp-header-top">
                <span class="perf-competency-expand-icon">${isExpanded ? "\u25BC" : "\u25B6"}</span>
                <span class="perf-competency-name">${this.escapeHtml(meta?.name || this.formatCompetencyName(id))}</span>
                <span class="perf-competency-value">${score.percentage}%</span>
                <span class="perf-competency-status">${icon}</span>
              </div>
              <div class="flex-row perf-comp-header-bar">
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
          <div class="flex-between perf-gaps-item-header">
            <span class="font-semibold perf-gaps-item-name">${this.escapeHtml(name)}</span>
            <span class="perf-gaps-item-pct" style="color: ${color};">${pct}%</span>
          </div>
          ${goal ? `<div class="perf-gaps-item-goal">${this.escapeHtml(goal)}</div>` : ""}
        </div>
      `;
    }).join("");

    return `
      <div class="perf-gaps-alert">
        <div class="perf-gaps-title">Areas Needing Attention</div>
        <div class="flex-col gap-6 perf-gaps-items">${gapItems}</div>
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
            <div class="flex-between perf-gap-card-header">
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
  // Questions
  // ============================================================

  private renderQuestions(): string {
    const questions = this.state.questions_summary;
    if (!questions || questions.length === 0) {
      return this.getEmptyStateHtml("--", "Questions will appear after first data collection. Run collect_daily or backfill to populate.");
    }

    return questions.map((q) => {
      const isExpanded = this._expandedQuestions.has(q.id);
      const evidence = this._questionEvidence.get(q.id);
      const isLoading = this._questionEvidenceLoading.has(q.id);
      const excluded = this._excludedEvidence.get(q.id) || new Set<string>();
      const selectedCount = evidence ? evidence.length - excluded.size : q.evidence_count;
      const totalPoints = evidence
        ? evidence.filter(e => !excluded.has(e.id)).reduce((sum, e) => sum + e.points, 0)
        : 0;

      return `
        <div class="card perf-question-card ${isExpanded ? "expanded" : ""}" data-question-id="${this.escapeHtml(q.id)}">
          <div class="perf-question-header">
            <span class="perf-question-text">${this.escapeHtml(q.text)}</span>
            <button class="perf-question-remove" data-action="removeQuestion" data-question="${this.escapeHtml(q.id)}" title="Remove question">&times;</button>
          </div>
          ${q.subtext ? `<div class="perf-question-subtext">${this.escapeHtml(q.subtext)}</div>` : ""}

          ${q.llm_summary ? `
            <div class="perf-question-summary">
              <div class="perf-question-summary-label">AI Draft ${q.last_evaluated ? `<span class="perf-question-eval-date">${new Date(q.last_evaluated).toLocaleDateString()}</span>` : ""}</div>
              <div class="perf-question-summary-text">${this.escapeHtml(q.llm_summary)}</div>
            </div>
          ` : ""}

          <div class="perf-question-data-bar" data-action="toggleEvidence" data-question="${this.escapeHtml(q.id)}">
            <span class="perf-question-data-toggle">${isExpanded ? "&#9660;" : "&#9654;"}</span>
            <span class="perf-question-data-counts">
              ${q.evidence_count} evidence items${evidence ? ` (${selectedCount} selected, ${totalPoints} pts)` : ""}
              &middot; ${q.notes_count} notes
            </span>
            ${isLoading ? `<span class="perf-question-loading">Loading...</span>` : ""}
          </div>

          ${isExpanded ? this.renderQuestionEvidencePanel(q, evidence, excluded) : ""}

          <div class="actions-row perf-question-actions">
            <button class="btn btn-xs" data-action="addNote" data-question="${this.escapeHtml(q.id)}">Add Note</button>
            <button class="btn btn-xs btn-primary" data-action="evaluate" data-question="${this.escapeHtml(q.id)}">${q.has_summary ? "Re-evaluate" : "Evaluate"}</button>
          </div>
        </div>
      `;
    }).join("");
  }

  private renderQuestionEvidencePanel(
    q: QuestionSummary,
    evidence: QuestionEvidence[] | undefined,
    excluded: Set<string>,
  ): string {
    if (!evidence || evidence.length === 0) {
      return `<div class="perf-evidence-panel"><div class="perf-evidence-empty">No evidence collected yet. Run daily collection first.</div></div>`;
    }

    const items = evidence.map((e) => {
      const checked = !excluded.has(e.id);
      return `
        <label class="perf-evidence-item ${checked ? "" : "excluded"}" data-evidence-id="${this.escapeHtml(e.id)}">
          <input type="checkbox" ${checked ? "checked" : ""} data-action="toggleEvidenceItem" data-question="${this.escapeHtml(q.id)}" data-evidence="${this.escapeHtml(e.id)}" />
          <span class="perf-evidence-title">${this.escapeHtml(e.title || e.id)}</span>
          <span class="perf-evidence-source">${this.escapeHtml(e.source)}</span>
          <span class="perf-evidence-points">${e.points} pts</span>
        </label>
      `;
    });

    const notes = q.manual_notes || [];
    const notesHtml = notes.length > 0 ? `
      <div class="perf-evidence-notes">
        <div class="perf-evidence-notes-label">Manual Notes</div>
        ${notes.map(n => `<div class="perf-evidence-note">${this.escapeHtml(n.text)}</div>`).join("")}
      </div>
    ` : "";

    return `
      <div class="perf-evidence-panel">
        <div class="perf-evidence-header">
          <span>${evidence.length} items sorted by points (top 20 sent to LLM)</span>
          <button class="btn btn-xs" data-action="selectAllEvidence" data-question="${this.escapeHtml(q.id)}">Select All</button>
          <button class="btn btn-xs" data-action="deselectAllEvidence" data-question="${this.escapeHtml(q.id)}">Deselect All</button>
        </div>
        <div class="flex-col perf-evidence-list">${items.join("")}</div>
        ${notesHtml}
      </div>
    `;
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
  // Help Tab
  // ============================================================

  private renderHelpTab(): string {
    const cfg = this.state.scoring_config;
    const level = cfg?.engineering_level || "sse";
    const levels = cfg?.engineering_levels || [];
    const levelName = levels.find(l => l.id === level)?.name || level.toUpperCase();

    const scopeMultipliers: Record<string, number> = { commit: 1, story: 2, epic: 4, anstrat: 7, strategy: 10 };
    const scopeLabels: Record<string, string> = { commit: "Git Commits", story: "Stories / Tasks / Bugs", epic: "Epics", anstrat: "Initiatives (ANSTRAT)", strategy: "Executive Priorities" };

    const levelScales: Record<string, number> = { ase: 0.65, se: 0.9, sse: 1.25, pse: 1.6, spse: 2.0, de: 2.5, sde: 3.1, fellow: 3.75 };
    const levelSummaries: Record<string, string> = {
      ase: "Learns and becomes proficient under guidance.",
      se: "Solid contributions, performs well independently.",
      sse: "Expert and owner of a specific area, enables others.",
      pse: "Expert across a group of projects, steers collaboration.",
      spse: "Expert in multiple areas, recognizable business impact.",
      de: "Strategic influencer affecting industry changes.",
      sde: "Authority on numerous strategic technology areas.",
      fellow: "Strategic thinking across company businesses.",
    };

    const roleWeightsAll: Record<string, Record<string, Record<string, number>>> = {
      ase:    { commit: {reporter:1.0,assignee:1.0,contributor:0.5}, story: {reporter:1.0,assignee:1.0,contributor:0.5}, epic: {reporter:3.0,assignee:2.0,contributor:1.0}, anstrat: {reporter:5.0,assignee:4.0,contributor:2.0}, strategy: {reporter:6.0,assignee:5.0,contributor:2.5} },
      se:     { commit: {reporter:1.0,assignee:1.0,contributor:0.5}, story: {reporter:1.0,assignee:1.0,contributor:0.5}, epic: {reporter:2.5,assignee:1.8,contributor:0.8}, anstrat: {reporter:4.0,assignee:3.0,contributor:1.5}, strategy: {reporter:5.0,assignee:4.0,contributor:2.0} },
      sse:    { commit: {reporter:0.8,assignee:0.8,contributor:0.4}, story: {reporter:0.8,assignee:0.8,contributor:0.4}, epic: {reporter:1.5,assignee:1.2,contributor:0.6}, anstrat: {reporter:3.0,assignee:2.0,contributor:1.0}, strategy: {reporter:4.0,assignee:3.0,contributor:1.5} },
      pse:    { commit: {reporter:0.4,assignee:0.4,contributor:0.2}, story: {reporter:0.5,assignee:0.4,contributor:0.2}, epic: {reporter:1.0,assignee:0.8,contributor:0.4}, anstrat: {reporter:1.5,assignee:1.2,contributor:0.6}, strategy: {reporter:2.0,assignee:1.5,contributor:0.8} },
      spse:   { commit: {reporter:0.3,assignee:0.3,contributor:0.1}, story: {reporter:0.3,assignee:0.2,contributor:0.1}, epic: {reporter:0.7,assignee:0.5,contributor:0.3}, anstrat: {reporter:1.0,assignee:1.0,contributor:0.5}, strategy: {reporter:1.5,assignee:1.2,contributor:0.6} },
      de:     { commit: {reporter:0.2,assignee:0.2,contributor:0.1}, story: {reporter:0.2,assignee:0.2,contributor:0.1}, epic: {reporter:0.5,assignee:0.4,contributor:0.2}, anstrat: {reporter:0.8,assignee:0.8,contributor:0.4}, strategy: {reporter:1.2,assignee:1.0,contributor:0.5} },
      sde:    { commit: {reporter:0.1,assignee:0.1,contributor:0.05}, story: {reporter:0.1,assignee:0.1,contributor:0.05}, epic: {reporter:0.4,assignee:0.3,contributor:0.15}, anstrat: {reporter:0.7,assignee:0.7,contributor:0.35}, strategy: {reporter:1.0,assignee:1.0,contributor:0.5} },
      fellow: { commit: {reporter:0.1,assignee:0.1,contributor:0.05}, story: {reporter:0.1,assignee:0.1,contributor:0.05}, epic: {reporter:0.3,assignee:0.2,contributor:0.1}, anstrat: {reporter:0.6,assignee:0.6,contributor:0.3}, strategy: {reporter:1.0,assignee:1.0,contributor:0.5} },
    };

    const pillarWeightsAll: Record<string, Record<string, number>> = {
      ase:    { "Technical Contribution": 1.3, "Leadership": 0.5, "Mentorship": 0.3, "End-to-End Delivery": 0.8 },
      se:     { "Technical Contribution": 1.2, "Leadership": 0.7, "Mentorship": 0.5, "End-to-End Delivery": 1.0 },
      sse:    { "Technical Contribution": 1.0, "Leadership": 1.0, "Mentorship": 0.8, "End-to-End Delivery": 1.0 },
      pse:    { "Technical Contribution": 0.8, "Leadership": 1.3, "Mentorship": 1.2, "End-to-End Delivery": 1.2 },
      spse:   { "Technical Contribution": 0.7, "Leadership": 1.4, "Mentorship": 1.3, "End-to-End Delivery": 1.3 },
      de:     { "Technical Contribution": 0.6, "Leadership": 1.5, "Mentorship": 1.4, "End-to-End Delivery": 1.4 },
      sde:    { "Technical Contribution": 0.5, "Leadership": 1.5, "Mentorship": 1.5, "End-to-End Delivery": 1.5 },
      fellow: { "Technical Contribution": 0.5, "Leadership": 1.5, "Mentorship": 1.5, "End-to-End Delivery": 1.5 },
    };

    const roleWeights = roleWeightsAll[level] || roleWeightsAll["sse"];
    const pillarWeights = pillarWeightsAll[level] || pillarWeightsAll["sse"];
    const targetScale = levelScales[level] || 1.25;
    const baseTarget = cfg?.target_per_competency || 100;
    const effectiveTarget = Math.max(Math.round(baseTarget * targetScale), 1);
    const minSignals = cfg?.min_signals || 2;
    const dailyCap = cfg?.daily_cap || 15;

    const competencyData = Object.entries(this.state.competencies).map(([id, c]) => {
      const meta = this.state.competency_meta[id];
      return { id, name: meta?.name || this.formatCompetencyName(id), category: meta?.category || "Other", points: c.points, percentage: c.percentage };
    });

    const helpData = JSON.stringify({
      level, levelName, scopeMultipliers, roleWeightsAll, pillarWeightsAll,
      levelScales, levelSummaries, baseTarget, minSignals, dailyCap,
      pillarColors: Object.fromEntries(Object.entries(PILLAR_DEFS).map(([k, v]) => [k, v.color])),
      competencyData,
    });

    return `
      <div class="perf-tab-panel perf-help">
        <script id="perfHelpData" type="application/json">${helpData}</script>

        <!-- ===== GROUP 1: How It Works ===== -->
        <details class="perf-help-group" open>
          <summary class="perf-help-group-header">How It Works</summary>

          <!-- 1.1 Scoring Pipeline -->
          <div class="section perf-help-section">
            <div class="section-title">Scoring Pipeline</div>
            <p class="text-secondary text-sm">Every work event flows through this pipeline from data collection to your quarterly score.</p>
            <div id="perf-help-pipeline" class="perf-help-diagram perf-help-pipeline-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-source"></span>Data Source</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-processing"></span>Processing</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-gate"></span>Signal Gate</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-output"></span>Output</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-cap"></span>Cap/Limit</span>
            </div>
          </div>

          <!-- 1.2 Vertex Pyramid -->
          <div class="section perf-help-section">
            <div class="section-title">Scope Vertex Weights</div>
            <p class="text-secondary text-sm">Higher-scope work earns proportionally more points. The scope multiplier is determined by where an event sits in the Jira hierarchy.</p>
            <div id="perf-help-pyramid" class="perf-help-diagram perf-help-pyramid-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-gradient"></span>Higher scope = more points</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-strategy-bonus"></span>Strategy Alignment Bonus (1.5x)</span>
            </div>
          </div>

          <!-- 1.3 Formula Breakdown -->
          <div class="section perf-help-section">
            <div class="section-title">Scoring Formula</div>
            <p class="text-secondary text-sm">Each qualifying event produces points per competency using this formula. Values shown are for <strong>${this.escapeHtml(levelName)}</strong>.</p>
            <div class="perf-help-formula">
              <div class="perf-help-formula-row">
                <div class="perf-help-factor perf-help-factor-blue">
                  <div class="perf-help-factor-value">3</div>
                  <div class="perf-help-factor-label">base_points</div>
                </div>
                <span class="perf-help-operator">&times;</span>
                <div class="perf-help-factor perf-help-factor-orange">
                  <div class="perf-help-factor-value">x4</div>
                  <div class="perf-help-factor-label">scope (epic)</div>
                </div>
                <span class="perf-help-operator">&times;</span>
                <div class="perf-help-factor perf-help-factor-purple">
                  <div class="perf-help-factor-value">${roleWeights.epic?.assignee ?? 1.2}</div>
                  <div class="perf-help-factor-label">role (assignee)</div>
                </div>
                <span class="perf-help-operator">&times;</span>
                <div class="perf-help-factor perf-help-factor-info">
                  <div class="perf-help-factor-value">${pillarWeights["Technical Contribution"] ?? 1.0}</div>
                  <div class="perf-help-factor-label">pillar (Tech)</div>
                </div>
                <span class="perf-help-operator">&times;</span>
                <div class="perf-help-factor perf-help-factor-gold">
                  <div class="perf-help-factor-value">1.5</div>
                  <div class="perf-help-factor-label">strategy</div>
                </div>
                <span class="perf-help-operator">=</span>
                <div class="perf-help-factor perf-help-factor-result">
                  <div class="perf-help-factor-value">${Math.round(3 * 4 * (roleWeights.epic?.assignee ?? 1.2) * (pillarWeights["Technical Contribution"] ?? 1.0) * 1.5)}</div>
                  <div class="perf-help-factor-label">points</div>
                </div>
              </div>
            </div>
            <div class="perf-help-formula-details">
              <div class="perf-help-detail-card">
                <strong>Signal Gate</strong>
                <p>An event must generate &ge; ${minSignals} signals to earn any points. Signals: event_type match, phrase matches, keyword matches, NPU classifier bonus, contribution type, cross-team, review decisions.</p>
              </div>
              <div class="perf-help-detail-card">
                <strong>Daily Cap</strong>
                <p>Maximum ${dailyCap} points per competency per day. Prevents any single day from dominating your score.</p>
              </div>
              <div class="perf-help-detail-card">
                <strong>NPU Classification</strong>
                <p>Uses all-MiniLM-L6-v2 model via OpenVINO. Cosine similarity &ge; 0.35 between event text and competency descriptors adds 2 bonus signals.</p>
              </div>
              <div class="perf-help-detail-card">
                <strong>Quarterly Target</strong>
                <p>Effective target per competency: ${baseTarget} &times; ${targetScale} = <strong>${effectiveTarget}</strong>. Overall score = average of all competency percentages.</p>
              </div>
            </div>
          </div>

          <!-- 1.4 Signal Lookup -->
          <div class="section perf-help-section">
            <div class="section-title">Signal Lookup</div>
            <p class="text-secondary text-sm">What earns points for each competency. Filter to find specific phrases or event types.</p>
            <input type="text" id="perf-help-signal-filter" class="perf-help-filter-input" placeholder="Filter competencies..." />
            <div class="perf-help-signal-table-wrap">
              <table class="perf-help-signal-table">
                <thead>
                  <tr><th>Competency</th><th>Pillar</th><th>Base</th><th>Event Types</th><th>Phrases (sample)</th><th>Keywords</th></tr>
                </thead>
                <tbody>
                  ${this.renderSignalLookupRows()}
                </tbody>
              </table>
            </div>
          </div>
        </details>

        <!-- ===== GROUP 2: Your Configuration ===== -->
        <details class="perf-help-group" open>
          <summary class="perf-help-group-header">Your Configuration (${this.escapeHtml(levelName)})</summary>

          <!-- 2.1 Engineering Levels -->
          <div class="section perf-help-section">
            <div class="section-title">Engineering Levels &amp; Target Scales</div>
            <p class="text-secondary text-sm">Your level determines the effective target per competency. Higher levels have higher targets, reflecting broader expected impact.</p>
            <div id="perf-help-levels" class="perf-help-diagram perf-help-levels-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-current"></span>Your Level (${this.escapeHtml(level.toUpperCase())})</span>
              <span class="perf-help-legend-item">effective_target = ${baseTarget} &times; target_scale</span>
            </div>
          </div>

          <!-- 2.2 Role Weight Heatmap -->
          <div class="section perf-help-section">
            <div class="section-title">Role Weight Matrix (${this.escapeHtml(level.toUpperCase())})</div>
            <p class="text-secondary text-sm">How scope and role interact. Reporter on strategy-level work earns the highest multiplier. At senior levels, commit-scope weights decrease &mdash; the system rewards higher-scope impact.</p>
            <div id="perf-help-heatmap" class="perf-help-diagram perf-help-heatmap-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-high-weight"></span>High weight</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-low-weight"></span>Low weight</span>
              <span class="perf-help-legend-item">Cell value = role_weight multiplier</span>
            </div>
          </div>

          <!-- 2.3 Pillar Weights Radar -->
          <div class="section perf-help-section">
            <div class="section-title">Pillar Weight Balance (${this.escapeHtml(level.toUpperCase())})</div>
            <p class="text-secondary text-sm">How the four competency pillars are weighted at your level. Junior levels emphasize Technical Contribution; senior levels shift toward Leadership and Mentorship.</p>
            <div id="perf-help-radar" class="perf-help-diagram perf-help-radar-container"></div>
            <div class="perf-help-legend">
              ${Object.entries(PILLAR_DEFS).map(([name, def]) =>
                `<span class="perf-help-legend-item"><span class="perf-help-dot" style="background:${def.color}"></span>${this.escapeHtml(name)}: ${pillarWeights[name] ?? "?"}</span>`
              ).join("")}
            </div>
          </div>

          <!-- 2.4 Level Comparison -->
          <div class="section perf-help-section">
            <div class="section-title">Level Comparison</div>
            <p class="text-secondary text-sm">Compare your current level with another to see how weights and targets change.</p>
            <div class="perf-help-compare-controls">
              <span class="text-sm">Your level: <strong>${this.escapeHtml(level.toUpperCase())}</strong></span>
              <span class="text-sm">Compare with:</span>
              <select id="perf-help-compare-level" class="perf-help-select">
                ${Object.keys(levelScales).filter(l => l !== level).map(l =>
                  `<option value="${l}">${l.toUpperCase()}</option>`
                ).join("")}
              </select>
            </div>
            <div class="perf-help-compare-layout">
              <div id="perf-help-compare" class="perf-help-diagram perf-help-compare-container"></div>
              <div id="perf-help-compare-radar" class="perf-help-diagram perf-help-compare-radar-container"></div>
            </div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-current"></span>Your Level (solid)</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-comparison"></span>Comparison (dashed)</span>
            </div>
          </div>
        </details>

        <!-- ===== GROUP 3: Your Data ===== -->
        <details class="perf-help-group">
          <summary class="perf-help-group-header">Your Data</summary>

          <!-- 3.1 Event Trace -->
          <div class="section perf-help-section">
            <div class="section-title">Live Event Trace</div>
            <p class="text-secondary text-sm">Pick a captured day and event to see exactly how it was scored step-by-step.</p>
            <div class="perf-help-trace-controls">
              <select id="perf-help-trace-date" class="perf-help-select" data-action="helpTraceDate">
                <option value="">Select a day...</option>
                ${this.state.captured_days.slice(-30).reverse().map(d =>
                  `<option value="${d.date}">${d.date} (${d.event_count} events, ${d.total_points} pts)</option>`
                ).join("")}
              </select>
            </div>
            <div id="perf-help-trace" class="perf-help-diagram perf-help-trace-container">
              <div class="perf-help-empty">Select a day above to trace an event.</div>
            </div>
          </div>

          <!-- 3.2 Point Attribution Treemap -->
          <div class="section perf-help-section">
            <div class="section-title">Point Attribution</div>
            <p class="text-secondary text-sm">Where your quarterly points come from, decomposed by competency pillar.</p>
            <div id="perf-help-treemap" class="perf-help-diagram perf-help-treemap-container"></div>
            <div class="perf-help-legend">
              ${Object.entries(PILLAR_DEFS).map(([name, def]) =>
                `<span class="perf-help-legend-item"><span class="perf-help-dot" style="background:${def.color}"></span>${this.escapeHtml(name)}</span>`
              ).join("")}
            </div>
          </div>

          <!-- 3.3 Daily Cap Impact -->
          <div class="section perf-help-section">
            <div class="section-title">Daily Cap Impact</div>
            <p class="text-secondary text-sm">How often each competency hit the ${dailyCap}-point daily cap. Frequently capped competencies suggest diversifying your work.</p>
            <div id="perf-help-cap" class="perf-help-diagram perf-help-cap-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-capped"></span>Frequently capped</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-uncapped"></span>Rarely capped</span>
              <span class="perf-help-legend-item">Cap = ${dailyCap} pts/competency/day</span>
            </div>
          </div>

          <!-- 3.4 What-If Calculator -->
          <div class="section perf-help-section">
            <div class="section-title">What-If Calculator</div>
            <p class="text-secondary text-sm">Simulate how different event parameters affect your score.</p>
            <div class="perf-help-whatif-form">
              <div class="perf-help-whatif-row">
                <label>Competency</label>
                <select id="perf-help-wi-comp" class="perf-help-select">
                  ${Object.entries(cfg?.competencies || {}).map(([id, c]) =>
                    `<option value="${id}" data-base="${c.base_points}" data-category="${this.escapeHtml(c.category)}">${this.escapeHtml(c.name)} (base: ${c.base_points})</option>`
                  ).join("")}
                </select>
              </div>
              <div class="perf-help-whatif-row">
                <label>Scope</label>
                <select id="perf-help-wi-scope" class="perf-help-select">
                  ${Object.entries(scopeMultipliers).map(([s, m]) =>
                    `<option value="${s}" ${s === "epic" ? "selected" : ""}>x${m} ${this.escapeHtml(scopeLabels[s] || s)}</option>`
                  ).join("")}
                </select>
              </div>
              <div class="perf-help-whatif-row">
                <label>Role</label>
                <select id="perf-help-wi-role" class="perf-help-select">
                  <option value="reporter">Reporter</option>
                  <option value="assignee" selected>Assignee</option>
                  <option value="contributor">Contributor</option>
                </select>
              </div>
              <div class="perf-help-whatif-row">
                <label>Strategy Aligned</label>
                <input type="checkbox" id="perf-help-wi-strat" />
              </div>
            </div>
            <div id="perf-help-whatif-result" class="perf-help-whatif-result">
              <span class="text-secondary">Adjust the inputs above to see the calculated score.</span>
            </div>
          </div>
        </details>
      </div>
    `;
  }

  private renderSignalLookupRows(): string {
    const cfg = this.state.scoring_config;
    if (!cfg?.competencies) return "<tr><td colspan=\"6\" class=\"text-secondary\">No scoring config loaded.</td></tr>";

    return Object.entries(cfg.competencies).map(([id, c]) => {
      const pillarColor = PILLAR_DEFS[c.category]?.color || "#888";
      const eventTypes = c.event_types.length > 0 ? c.event_types.join(", ") : "<span class='text-secondary'>--</span>";
      const phrases = c.phrases.slice(0, 5).map(p => `<code>${this.escapeHtml(p)}</code>`).join(" ") + (c.phrases.length > 5 ? ` <span class="text-secondary">+${c.phrases.length - 5} more</span>` : "");
      const keywords = c.keywords.slice(0, 5).map(k => `<code>${this.escapeHtml(k)}</code>`).join(" ") + (c.keywords.length > 5 ? ` <span class="text-secondary">+${c.keywords.length - 5} more</span>` : "");

      return `
        <tr class="perf-help-signal-row" data-search="${this.escapeHtml((c.name + " " + c.category + " " + c.event_types.join(" ") + " " + c.phrases.join(" ") + " " + c.keywords.join(" ")).toLowerCase())}">
          <td><strong>${this.escapeHtml(c.name)}</strong></td>
          <td><span class="perf-help-pillar-badge" style="background:${pillarColor}22;color:${pillarColor};border:1px solid ${pillarColor}44">${this.escapeHtml(c.category)}</span></td>
          <td class="text-center">${c.base_points}</td>
          <td class="text-sm">${eventTypes}</td>
          <td class="text-sm">${phrases}</td>
          <td class="text-sm">${keywords}</td>
        </tr>
      `;
    }).join("");
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
            document.querySelectorAll('.meetings-subtab').forEach(function(btn) {
              btn.classList.toggle('active', btn.getAttribute('data-key') === tabId);
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
          } else if (action === 'togglePerfPhysics') {
            var pp = document.getElementById('perfMmPhysicsPanel');
            if (pp) {
              if (pp.style.display === 'none' || pp.style.display === '') {
                pp.style.display = 'flex';
                element.classList.add('active');
              } else {
                pp.style.display = 'none';
                element.classList.remove('active');
              }
            }
          } else if (action === 'toggleScoringSettings' || action === 'resetScoringConfig') {
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
          } else if (action === 'removeExecutiveSender' || action === 'deleteExecutiveEmail') {
            vscode.postMessage({
              command: 'performanceAction', action: action,
              value: target.dataset.value
            });
          } else if (action === 'addQuestion') {
            var form = document.getElementById('addQuestionForm');
            if (form) {
              form.classList.toggle('visible');
              var inp = document.getElementById('newQuestionText');
              if (inp && form.classList.contains('visible')) inp.focus();
            }
          } else if (action === 'cancelAddQuestion') {
            var form2 = document.getElementById('addQuestionForm');
            if (form2) form2.classList.remove('visible');
            var inp2 = document.getElementById('newQuestionText');
            if (inp2) inp2.value = '';
          } else if (action === 'saveQuestion') {
            var inp3 = document.getElementById('newQuestionText');
            var text = inp3 ? inp3.value.trim() : '';
            if (text) {
              vscode.postMessage({ command: 'performanceAction', action: 'saveQuestion', description: text });
              inp3.value = '';
              var form3 = document.getElementById('addQuestionForm');
              if (form3) form3.classList.remove('visible');
            }
          } else if (action === 'removeQuestion') {
            var qId = element.getAttribute('data-question');
            if (qId && confirm('Remove this question? Evidence and notes will be lost.')) {
              vscode.postMessage({ command: 'performanceAction', action: 'removeQuestion', questionId: qId });
            }
          } else {
            var evidenceId = element.getAttribute('data-evidence');
            vscode.postMessage({
              command: 'performanceAction',
              action: action,
              questionId: questionId,
              evidenceId: evidenceId,
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

        // Engineering level selector
        document.addEventListener('change', function(e) {
          var sel = e.target;
          if (!sel || !sel.classList || !sel.classList.contains('scoring-level-select')) return;
          vscode.postMessage({ command: 'performanceAction', action: 'setEngineeringLevel', value: sel.value });
        });

        // Number input changes for globals, base_points, and new scoring fields
        document.addEventListener('change', function(e) {
          var input = e.target;
          if (!input) return;

          // Handle scoring toggle checkboxes
          if (input.type === 'checkbox' && input.dataset && input.dataset.action) {
            vscode.postMessage({
              command: 'performanceAction',
              action: input.dataset.action,
              value: input.checked
            });
            return;
          }

          // Handle select elements with data-action
          if (input.tagName === 'SELECT' && input.dataset && input.dataset.action) {
            vscode.postMessage({
              command: 'performanceAction',
              action: input.dataset.action,
              value: input.value
            });
            return;
          }

          if (!input.classList || !input.classList.contains('scoring-input')) return;

          // New action-based inputs (scope multipliers, role weights, pillar weights, etc.)
          var act = input.dataset.action;
          if (act) {
            var msg = { command: 'performanceAction', action: act, value: input.value };
            if (input.dataset.scope) msg.scope = input.dataset.scope;
            if (input.dataset.role) msg.role = input.dataset.role;
            if (input.dataset.pillar) msg.pillar = input.dataset.pillar;
            vscode.postMessage(msg);
            return;
          }

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

      // ============ QC Mind Map (D3 Force-Directed - Issues + Competencies views) ============
      (function() {
        var perfMmState = {
          simulation: null,
          showLabels: false,
          sticky: false,
          zoom: null,
          svg: null,
          g: null,
          nodeSelection: null,
          linkSelection: null,
          allLinks: null,
          glowG: null,
          pillarNodes: null,
          chargeStrength: -200,
          linkDistance: 120,
          collisionRadius: 4,
          radialScale: 1.0,
          alphaDecay: 0.012,
          velocityDecay: 0.35,
          paused: false
        };

        function escapeHtml(s) {
          if (!s) return '';
          return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        function fitPerfMindmap(svg, g, zoomBehavior, width, height) {
          if (!g || !g.node()) return;
          var bounds = g.node().getBBox();
          if (!bounds.width || !bounds.height) return;
          var scale = 0.85 / Math.max(bounds.width / width, bounds.height / height);
          scale = Math.min(Math.max(scale, 0.15), 3);
          var tx = width / 2 - scale * (bounds.x + bounds.width / 2);
          var ty = height / 2 - scale * (bounds.y + bounds.height / 2);
          svg.transition().duration(750)
            .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
        }

        function togglePerfMmLabels(g) {
          var existing = g.selectAll('.perf-mm-opt-label');
          if (perfMmState.showLabels) {
            if (existing.empty()) {
              g.selectAll('.perf-mm-node').each(function(d) {
                if (d.type === 'root') return;
                d3.select(this).append('text')
                  .attr('class', 'perf-mm-opt-label')
                  .attr('dy', (d.size || 8) + 12)
                  .attr('text-anchor', 'middle')
                  .attr('fill', 'var(--vscode-foreground, #ccc)')
                  .attr('font-size', d.type === 'pillar' || d.type === 'strategy' ? '11px' : '9px')
                  .text(function(dd) {
                    var t = dd.fullLabel || dd.fullKey || dd.label;
                    return t.length > 22 ? t.substring(0, 19) + '...' : t;
                  });
              });
            } else { existing.style('display', null); }
          } else { existing.style('display', 'none'); }
        }

        function applyFilters() {
          // Gather visible pillars
          var visiblePillars = new Set();
          document.querySelectorAll('.perfMmPillarChk').forEach(function(chk) {
            if (chk.checked) visiblePillars.add(chk.dataset.pillar);
          });

          // Gather visible node types from checkboxes
          var checkedTypes = new Set();
          document.querySelectorAll('.perfMmTypeChk').forEach(function(chk) {
            if (chk.checked) {
              chk.dataset.types.split(',').forEach(function(t) { checkedTypes.add(t); });
            }
          });

          // Cascade: if ANSTRATs hidden -> epics hidden -> issues hidden
          var showAnstrat = checkedTypes.has('anstrat');
          var showEpic = checkedTypes.has('epic');
          var showIssue = checkedTypes.has('task') || checkedTypes.has('bug') || checkedTypes.has('story');

          var visibleTypes = new Set();
          visibleTypes.add('root');
          visibleTypes.add('pillar');
          if (checkedTypes.has('competency')) visibleTypes.add('competency');
          if (checkedTypes.has('strategy')) visibleTypes.add('strategy');
          if (showAnstrat) visibleTypes.add('anstrat');
          if (showAnstrat && showEpic) visibleTypes.add('epic');
          if (showAnstrat && showEpic && showIssue) {
            visibleTypes.add('task');
            visibleTypes.add('bug');
            visibleTypes.add('story');
          }

          if (!perfMmState.nodeSelection || !perfMmState.linkSelection) return;

          // Build a map of hidden node IDs for parent-cascade on unattached nodes
          var hiddenParents = new Set();

          perfMmState.nodeSelection.each(function(d) {
            var visible = true;
            if (d.type === 'root') { visible = true; }
            else if (d.type === 'pillar') {
              visible = visiblePillars.has(d.id);
            } else {
              var typeOk = visibleTypes.has(d.type);
              var pillarOk = true;
              if (d.pillars && d.pillars.length > 0) {
                pillarOk = d.pillars.some(function(p) { return visiblePillars.has(p); });
              }
              visible = typeOk && pillarOk;
            }
            d._visible = visible;
            if (!visible) hiddenParents.add(d.id);
            d3.select(this)
              .style('opacity', visible ? null : 0.06)
              .style('pointer-events', visible ? null : 'none');
          });

          perfMmState.linkSelection.each(function(d) {
            var src = typeof d.source === 'object' ? d.source : null;
            var tgt = typeof d.target === 'object' ? d.target : null;
            var visible = (!src || src._visible !== false) && (!tgt || tgt._visible !== false);
            d3.select(this).style('opacity', visible ? null : 0.03);
          });

          // Fade heat glows for hidden pillars
          if (perfMmState.glowG && perfMmState.pillarNodes) {
            perfMmState.pillarNodes.forEach(function(p, i) {
              var pct = Math.max(0, Math.min(100, p.percentage || 0));
              var vis = visiblePillars.has(p.id);
              d3.select(perfMmState.glowG.selectAll('.perf-mm-heat-glow').nodes()[i])
                .attr('opacity', vis ? (0.02 + (pct / 100) * 0.10) : 0);
            });
          }
        }

        function setupControls(container) {
          var labelsChk = document.getElementById('perfMmLabels');
          if (labelsChk) {
            labelsChk.checked = perfMmState.showLabels;
            labelsChk.addEventListener('change', function() {
              perfMmState.showLabels = this.checked;
              if (perfMmState.g) togglePerfMmLabels(perfMmState.g);
            });
          }
          var stickyChk = document.getElementById('perfMmSticky');
          if (stickyChk) {
            stickyChk.checked = perfMmState.sticky;
            stickyChk.addEventListener('change', function() { perfMmState.sticky = this.checked; });
          }
          var reheatBtn = document.getElementById('perfMmReheat');
          if (reheatBtn) {
            reheatBtn.addEventListener('click', function() {
              if (perfMmState.simulation) {
                perfMmState.simulation.nodes().forEach(function(d) { d.fx = null; d.fy = null; });
                perfMmState.simulation.alpha(1).restart();
              }
            });
          }
          var fitBtn = document.getElementById('perfMmFit');
          if (fitBtn) {
            fitBtn.addEventListener('click', function() {
              fitPerfMindmap(perfMmState.svg, perfMmState.g, perfMmState.zoom,
                container.clientWidth || 800, container.clientHeight || 600);
            });
          }

          // Pillar filter checkboxes
          document.querySelectorAll('.perfMmPillarChk').forEach(function(chk) {
            chk.addEventListener('change', applyFilters);
          });

          // Node type filter checkboxes
          document.querySelectorAll('.perfMmTypeChk').forEach(function(chk) {
            chk.addEventListener('change', applyFilters);
          });

          // Physics panel toggle - use document-level listener to survive DOM updates
          if (!window._perfPhysicsToggleAttached) {
            window._perfPhysicsToggleAttached = true;
            document.addEventListener('click', function(e) {
              var btn = e.target.closest && e.target.closest('#perfMmPhysicsToggle');
              if (!btn) return;
              var pp = document.getElementById('perfMmPhysicsPanel');
              if (!pp) return;
              e.preventDefault();
              e.stopPropagation();
              if (pp.style.display === 'none' || pp.style.display === '') {
                pp.style.display = 'flex';
                btn.classList.add('active');
              } else {
                pp.style.display = 'none';
                btn.classList.remove('active');
              }
            }, true);
          }

          // Helper: setup a physics slider
          function perfMmSetupSlider(sliderId, valueId, onUpdate, formatFn) {
            var slider = document.getElementById(sliderId);
            var valueEl = document.getElementById(valueId);
            if (slider) {
              slider.addEventListener('input', function() {
                var v = parseFloat(this.value);
                if (valueEl) valueEl.textContent = formatFn(v);
                onUpdate(v);
              });
            }
          }

          function perfMmSetSlider(sliderId, valueId, sliderVal, displayVal) {
            var s = document.getElementById(sliderId);
            var v = document.getElementById(valueId);
            if (s) s.value = sliderVal;
            if (v) v.textContent = displayVal;
          }

          function perfMmUpdateForce(forceName, updateFn) {
            if (perfMmState.simulation && perfMmState.simulation.force(forceName)) {
              updateFn(perfMmState.simulation);
              perfMmState.simulation.alpha(0.3).restart();
            }
          }

          // Repulsion slider
          perfMmSetupSlider('perfMmChargeSlider', 'perfMmChargeValue', function(v) {
            perfMmState.chargeStrength = v;
            perfMmUpdateForce('charge', function(sim) {
              var ratio = v / -200;
              sim.force('charge').strength(function(d) {
                if (d.type === 'root') return -600 * ratio;
                if (d.type === 'pillar') return -350 * ratio;
                if (d.type === 'competency') return -100 * ratio;
                if (d.type === 'anstrat') return -180 * ratio;
                if (d.type === 'epic') return -80 * ratio;
                if (d.type === 'strategy') return -60 * ratio;
                return -30 * ratio;
              });
            });
          }, function(v) { return String(v); });

          // Link distance slider
          perfMmSetupSlider('perfMmLinkDistSlider', 'perfMmLinkDistValue', function(v) {
            perfMmState.linkDistance = v;
            perfMmUpdateForce('link', function(sim) {
              var ratio = v / 120;
              sim.force('link').distance(function(d) {
                if (d.type === 'evidence') return 250 * ratio;
                if (d.type === 'comp_anstrat') return 120 * ratio;
                if (d.type === 'anstrat_strategy') return 140 * ratio;
                if (d.type === 'pillar_strategy') return 160 * ratio;
                var src = typeof d.source === 'object' ? d.source : null;
                var tgt = typeof d.target === 'object' ? d.target : null;
                if (src && src.type === 'root') return 160 * ratio;
                if (src && src.type === 'pillar' && tgt && tgt.type === 'competency') return 140 * ratio;
                if (src && src.type === 'anstrat') return 70 * ratio;
                if (tgt && (tgt.type === 'task' || tgt.type === 'bug' || tgt.type === 'story')) return 45 * ratio;
                return 90 * ratio;
              });
            });
          }, function(v) { return String(v); });

          // Collision padding slider
          perfMmSetupSlider('perfMmCollisionSlider', 'perfMmCollisionValue', function(v) {
            perfMmState.collisionRadius = v;
            perfMmUpdateForce('collision', function(sim) {
              sim.force('collision').radius(function(d) { return (d.size || 8) + v; });
            });
          }, function(v) { return String(v); });

          // Radial spread slider
          perfMmSetupSlider('perfMmRadialSlider', 'perfMmRadialValue', function(v) {
            var scale = v / 100;
            perfMmState.radialScale = scale;
            if (perfMmState.simulation) {
              var sim = perfMmState.simulation;
              var cx2 = (container.clientWidth || 800) / 2;
              var cy2 = (container.clientHeight || 600) / 2;
              sim.force('radial_pillar', d3.forceRadial(220 * scale, cx2, cy2).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }));
              sim.force('radial_comp', d3.forceRadial(360 * scale, cx2, cy2).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }));
              sim.force('radial_anstrat', d3.forceRadial(220 * scale, cx2, cy2).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }));
              sim.force('radial_strat', d3.forceRadial(450 * scale, cx2, cy2).strength(function(d) { return d.type === 'strategy' ? 0.3 : 0; }));
              sim.alpha(0.3).restart();
            }
          }, function(v) { return (v / 100).toFixed(1); });

          // Cooling slider
          perfMmSetupSlider('perfMmDecaySlider', 'perfMmDecayValue', function(v) {
            var mapped = v / 1000;
            perfMmState.alphaDecay = mapped;
            if (perfMmState.simulation) perfMmState.simulation.alphaDecay(mapped);
          }, function(v) { return (v / 1000).toFixed(3); });

          // Friction slider
          perfMmSetupSlider('perfMmVelocitySlider', 'perfMmVelocityValue', function(v) {
            var mapped = v / 100;
            perfMmState.velocityDecay = mapped;
            if (perfMmState.simulation) perfMmState.simulation.velocityDecay(mapped);
          }, function(v) { return (v / 100).toFixed(2); });

          // Reset button
          var physResetBtn = document.getElementById('perfMmPhysicsReset');
          if (physResetBtn) {
            physResetBtn.addEventListener('click', function() {
              perfMmState.chargeStrength = -200;
              perfMmState.linkDistance = 120;
              perfMmState.collisionRadius = 4;
              perfMmState.radialScale = 1.0;
              perfMmState.alphaDecay = 0.012;
              perfMmState.velocityDecay = 0.35;
              perfMmSetSlider('perfMmChargeSlider', 'perfMmChargeValue', '-200', '-200');
              perfMmSetSlider('perfMmLinkDistSlider', 'perfMmLinkDistValue', '120', '120');
              perfMmSetSlider('perfMmCollisionSlider', 'perfMmCollisionValue', '4', '4');
              perfMmSetSlider('perfMmRadialSlider', 'perfMmRadialValue', '100', '1.0');
              perfMmSetSlider('perfMmDecaySlider', 'perfMmDecayValue', '12', '0.012');
              perfMmSetSlider('perfMmVelocitySlider', 'perfMmVelocityValue', '35', '0.35');
              if (perfMmState.simulation) {
                perfMmState.simulation.alphaDecay(0.012).velocityDecay(0.35).alpha(0.5).restart();
              }
            });
          }

          // Pause button
          var physPauseBtn = document.getElementById('perfMmPhysicsPause');
          if (physPauseBtn) {
            physPauseBtn.addEventListener('click', function() {
              if (perfMmState.simulation) {
                if (perfMmState.paused) {
                  perfMmState.simulation.alpha(0.3).restart();
                  physPauseBtn.textContent = 'Pause';
                } else {
                  perfMmState.simulation.stop();
                  physPauseBtn.textContent = 'Resume';
                }
                perfMmState.paused = !perfMmState.paused;
              }
            });
          }

          // Unstick All button
          var physUnstickBtn = document.getElementById('perfMmPhysicsUnstick');
          if (physUnstickBtn) {
            physUnstickBtn.addEventListener('click', function() {
              if (perfMmState.simulation) {
                perfMmState.simulation.nodes().forEach(function(d) { d.fx = null; d.fy = null; });
                perfMmState.simulation.alpha(0.3).restart();
              }
            });
          }
        }

        function makeDrag(simulation) {
          return d3.drag()
            .on('start', function(event, d) {
              if (!event.active) simulation.alphaTarget(0.3).restart();
              d.fx = d.x; d.fy = d.y;
            })
            .on('drag', function(event, d) { d.fx = event.x; d.fy = event.y; })
            .on('end', function(event, d) {
              if (!event.active) simulation.alphaTarget(0);
              if (!perfMmState.sticky) { d.fx = null; d.fy = null; }
            });
        }

        function setupTooltipAndHighlight(node, link, links, tooltip) {
          node.on('mouseenter', function(event, d) {
            if (!tooltip) return;
            var html = '';
            if (d.type === 'competency') {
              html = '<strong>' + escapeHtml(d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">' + escapeHtml(d.category || 'Competency') + '</span>';
              html += '<div class="perf-mm-tt-meta">' + d.percentage + '% &middot; ' + d.points + '/' + d.target + ' pts &middot; ' + d.evidenceCount + ' evidence</div>';
              if (d.goal) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.goal) + '</div>';
            } else if (d.type === 'strategy') {
              html = '<strong>' + escapeHtml(d.fullLabel || d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">' + (d.status === 'covered' ? 'Covered' : 'Gap') + '</span>';
              if (d.context) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.context.substring(0, 150)) + '</div>';
              if (d.matchedIssues && d.matchedIssues.length) html += '<div class="perf-mm-tt-meta">' + d.matchedIssues.length + ' matched issues</div>';
              if (d.matchedMrs && d.matchedMrs.length) html += '<div class="perf-mm-tt-meta">' + d.matchedMrs.length + ' matched MRs</div>';
            } else if (d.type === 'pillar') {
              html = '<strong>' + escapeHtml(d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.heatColor + '">' + d.percentage + '%</span>';
              html += '<div class="perf-mm-tt-meta">' + d.compCount + ' competencies &middot; ' + d.priorityCount + ' priorities &middot; ' + d.covered + ' covered &middot; ' + d.gaps + ' gaps</div>';
            } else if (d.type === 'anstrat') {
              html = '<strong>' + escapeHtml(d.fullKey || d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">ANSTRAT</span>';
              if (d.summary) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.summary.substring(0, 150)) + '</div>';
              if (d.points) html += '<div class="perf-mm-tt-meta">' + d.points + ' pts</div>';
              if (d.eventCount) html += '<div class="perf-mm-tt-meta">' + d.eventCount + ' events</div>';
            } else {
              var typeLabels = { root: 'Quarter', strategy: 'Strategy', epic: 'Epic', story: 'Story', bug: 'Bug', task: 'Task', group: 'Group', anstrat: 'ANSTRAT' };
              html = '<strong>' + escapeHtml(d.fullKey || d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:' + d.color + '">' + (typeLabels[d.type] || d.type) + '</span>';
              if (d.summary) html += '<div class="perf-mm-tt-summary">' + escapeHtml(d.summary.substring(0, 120)) + '</div>';
              if (d.points) html += '<div class="perf-mm-tt-meta">' + d.points + ' pts</div>';
              if (d.eventCount) html += '<div class="perf-mm-tt-meta">' + d.eventCount + ' events</div>';
            }
            tooltip.innerHTML = html;
            tooltip.style.display = 'block';
            var connectedIds = new Set([d.id]);
            links.forEach(function(l) {
              var sid = l.source.id || l.source;
              var tid = l.target.id || l.target;
              if (sid === d.id) connectedIds.add(tid);
              if (tid === d.id) connectedIds.add(sid);
            });
            node.classed('perf-mm-dimmed', function(n) { return !connectedIds.has(n.id); });
            link.classed('perf-mm-dimmed', function(l) {
              var sid = l.source.id || l.source;
              var tid = l.target.id || l.target;
              return sid !== d.id && tid !== d.id;
            });
          })
          .on('mousemove', function(event) {
            if (!tooltip) return;
            var ctr = document.getElementById('perfMindmapGraph');
            if (!ctr) return;
            var rect = ctr.getBoundingClientRect();
            tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
            tooltip.style.top = (event.clientY - rect.top - 10) + 'px';
          })
          .on('mouseleave', function() {
            if (tooltip) tooltip.style.display = 'none';
            node.classed('perf-mm-dimmed', false);
            link.classed('perf-mm-dimmed', false);
          })
          .on('click', function(event, d) {
            if (d.fullKey && d.fullKey.startsWith('AAP-')) {
              vscode.postMessage({ command: 'performanceAction', action: 'openIssue', key: d.fullKey });
            }
          });
        }

        // ---- Combined unified view ----
        function renderCombinedView(graphData, svg, g, container, width, height) {
          var nodes = graphData.nodes.map(function(d) { return Object.assign({}, d); });
          var links = graphData.links.map(function(d) { return Object.assign({}, d); });

          var cx = width / 2, cy = height / 2;

          // Pre-position nodes radially by type
          var anstratIdx = 0;
          var anstratTotal = nodes.filter(function(d) { return d.type === 'anstrat'; }).length;
          nodes.forEach(function(d) {
            if (d.type === 'root') { d.x = cx; d.y = cy; }
            else if (d.type === 'pillar') {
              var rad = (d.angle || 0) * Math.PI / 180 - Math.PI / 2;
              d.x = cx + 220 * Math.cos(rad);
              d.y = cy + 220 * Math.sin(rad);
            } else if (d.type === 'competency') {
              var pRad = (d.pillarAngle || 0) * Math.PI / 180 - Math.PI / 2;
              var spread = (Math.random() - 0.5) * 0.5;
              d.x = cx + 360 * Math.cos(pRad + spread);
              d.y = cy + 360 * Math.sin(pRad + spread);
            } else if (d.type === 'anstrat') {
              var aRad = (anstratIdx / Math.max(anstratTotal, 1)) * Math.PI * 2 - Math.PI / 2;
              d.x = cx + 220 * Math.cos(aRad);
              d.y = cy + 220 * Math.sin(aRad);
              anstratIdx++;
            } else if (d.type === 'epic') {
              d.x = cx + (Math.random() - 0.5) * 600;
              d.y = cy + (Math.random() - 0.5) * 600;
            } else if (d.type === 'strategy') {
              var sAngle = Math.random() * Math.PI * 2;
              d.x = cx + 450 * Math.cos(sAngle);
              d.y = cy + 450 * Math.sin(sAngle);
            } else {
              d.x = cx + (Math.random() - 0.5) * 800;
              d.y = cy + (Math.random() - 0.5) * 800;
            }
          });

          // Pillar heat glow backgrounds – radius and opacity scale with competency %
          var pillarNodes = nodes.filter(function(d) { return d.type === 'pillar'; });
          var glowG = g.append('g').attr('class', 'perf-mm-heat-glows');
          pillarNodes.forEach(function(p) {
            var pct = Math.max(0, Math.min(100, p.percentage || 0));
            var glowR = 60 + (pct / 100) * 220;
            var glowOpacity = 0.02 + (pct / 100) * 0.10;
            glowG.append('circle')
              .attr('class', 'perf-mm-heat-glow')
              .attr('cx', p.x).attr('cy', p.y).attr('r', glowR)
              .attr('fill', p.color || '#555')
              .attr('opacity', glowOpacity)
              .attr('filter', 'url(#perfHeatGlow)');
          });

          var simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(function(d) { return d.id; })
              .distance(function(d) {
                if (d.type === 'evidence') return 250;
                if (d.type === 'comp_anstrat') return 120;
                if (d.type === 'anstrat_strategy') return 140;
                if (d.type === 'pillar_strategy') return 160;
                var src = typeof d.source === 'object' ? d.source : null;
                var tgt = typeof d.target === 'object' ? d.target : null;
                if (src && src.type === 'root') return 220;
                if (src && src.type === 'pillar' && tgt && tgt.type === 'competency') return 160;
                if (src && src.type === 'anstrat') return 70;
                if (tgt && (tgt.type === 'task' || tgt.type === 'bug' || tgt.type === 'story')) return 45;
                return 90;
              })
              .strength(function(d) {
                if (d.type === 'evidence') return 0.1;
                if (d.type === 'comp_anstrat') return 0.4;
                if (d.type === 'anstrat_strategy') return 0.35;
                if (d.type === 'pillar_strategy') return 0.35;
                return 0.45;
              }))
            .force('charge', d3.forceManyBody().strength(function(d) {
              if (d.type === 'root') return -800;
              if (d.type === 'pillar') return -600;
              if (d.type === 'competency') return -120;
              if (d.type === 'anstrat') return -180;
              if (d.type === 'epic') return -80;
              if (d.type === 'strategy') return -60;
              return -30;
            }))
            .force('radial_pillar', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }))
            .force('radial_comp', d3.forceRadial(360, cx, cy).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }))
            .force('radial_anstrat', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }))
            .force('radial_strat', d3.forceRadial(450, cx, cy).strength(function(d) { return d.type === 'strategy' ? 0.3 : 0; }))
            .force('center_root', d3.forceRadial(0, cx, cy).strength(function(d) { return d.type === 'root' ? 1 : 0; }))
            .force('collision', d3.forceCollide().radius(function(d) {
              if (d.type === 'pillar') return (d.size || 22) + 40;
              return (d.size || 8) + 4;
            }))
            .alphaDecay(0.012).velocityDecay(0.35);

          simulation.force('angular_pin', function(alpha) {
            var strength = 0.15 * alpha;
            nodes.forEach(function(d) {
              if (d.type !== 'pillar' || d.angle == null) return;
              var targetRad = d.angle * Math.PI / 180 - Math.PI / 2;
              var tx = cx + 220 * Math.cos(targetRad);
              var ty = cy + 220 * Math.sin(targetRad);
              d.vx += (tx - d.x) * strength;
              d.vy += (ty - d.y) * strength;
            });
          });
          perfMmState.simulation = simulation;

          // Draw links
          var link = g.append('g').attr('class', 'perf-mm-links').selectAll('line').data(links).enter().append('line')
            .attr('class', function(d) {
              if (d.type === 'evidence') return 'perf-mm-link perf-mm-link--evidence';
              if (d.type === 'comp_anstrat') return 'perf-mm-link perf-mm-link--comp-anstrat';
              if (d.type === 'anstrat_strategy') return 'perf-mm-link perf-mm-link--anstrat-strategy';
              if (d.type === 'pillar_strategy') return 'perf-mm-link perf-mm-link--pillar-strategy';
              return 'perf-mm-link';
            })
            .attr('stroke', function(d) {
              var src = typeof d.source === 'object' ? d.source : null;
              if (d.type === 'evidence') return src ? (src.color || '#8b5cf6') : '#8b5cf6';
              if (d.type === 'comp_anstrat') return src ? (src.color || '#10b981') : '#10b981';
              if (d.type === 'anstrat_strategy') {
                return src ? (src.color || '#f59e0b') : '#f59e0b';
              }
              if (d.type === 'pillar_strategy') return src ? (src.color || '#888') : '#888';
              return src ? (src.color || '#555') : '#555';
            })
            .attr('stroke-opacity', function(d) {
              if (d.type === 'evidence') return 0.4;
              if (d.type === 'comp_anstrat') return 0.7;
              if (d.type === 'anstrat_strategy') return 0.7;
              if (d.type === 'pillar_strategy') return 0.55;
              return 0.3;
            })
            .attr('stroke-width', function(d) {
              if (d.type === 'evidence') return Math.min((d.weight || 1) * 1.2, 4);
              if (d.type === 'comp_anstrat') return Math.min((d.weight || 1) + 1.5, 4);
              if (d.type === 'anstrat_strategy') return Math.min((d.weight || 1) + 1.5, 4);
              if (d.type === 'pillar_strategy') return 2.5;
              var src = typeof d.source === 'object' ? d.source : null;
              if (src && src.type === 'root') return 3;
              if (src && src.type === 'pillar') return 2;
              if (src && src.type === 'anstrat') return 1.8;
              return 1;
            })
            .attr('stroke-dasharray', function(d) {
              if (d.type === 'evidence') return '6,4';
              if (d.type === 'pillar_strategy') return '6,3,2,3';
              return 'none';
            });

          // Draw nodes
          var node = g.append('g').attr('class', 'perf-mm-nodes').selectAll('g').data(nodes).enter().append('g')
            .attr('class', function(d) { return 'perf-mm-node perf-mm-node--' + d.type; })
            .call(makeDrag(simulation));

          // Root glow
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('class', 'perf-mm-glow')
            .attr('r', function(d) { return (d.size || 30) + 6; })
            .attr('fill', 'none').attr('stroke', '#667eea').attr('stroke-width', 2).attr('stroke-opacity', 0.3);

          // Root circle
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('class', 'perf-mm-circle')
            .attr('r', function(d) { return d.size || 30; })
            .attr('fill', '#667eea').attr('stroke', '#8b9cf5').attr('stroke-width', 3);

          // Pillar ring nodes -- always use the pillar's own color, not heat color
          node.filter(function(d) { return d.type === 'pillar'; })
            .append('circle').attr('class', 'perf-mm-ring')
            .attr('r', function(d) { return d.size || 22; })
            .attr('fill', 'none')
            .attr('stroke', function(d) { return d.color; })
            .attr('stroke-width', 3).attr('stroke-opacity', 0.7);

          // Competency circles (heat colored)
          node.filter(function(d) { return d.type === 'competency'; })
            .append('circle').attr('class', 'perf-mm-circle')
            .attr('r', function(d) { return d.size || 10; })
            .attr('fill', function(d) { return d.heatColor || d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.heatColor || d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5);

          // ANSTRAT nodes -- rounded rectangles via rect
          node.filter(function(d) { return d.type === 'anstrat'; })
            .append('rect').attr('class', 'perf-mm-anstrat-rect')
            .attr('width', function(d) { return (d.size || 16) * 4; })
            .attr('height', function(d) { return (d.size || 16) * 2.8; })
            .attr('x', function(d) { return -(d.size || 16) * 2; })
            .attr('y', function(d) { return -(d.size || 16) * 1.4; })
            .attr('rx', 5).attr('ry', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5).attr('opacity', 0.9);

          // Epic triangles (pointing up)
          node.filter(function(d) { return d.type === 'epic'; })
            .append('polygon').attr('class', 'perf-mm-triangle')
            .attr('points', function(d) {
              var s = d.size || 10;
              return '0,' + (-s) + ' ' + (s * 0.9) + ',' + (s * 0.7) + ' ' + (-s * 0.9) + ',' + (s * 0.7);
            })
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1);

          // Issue squares (task/bug/story)
          node.filter(function(d) { return d.type === 'task' || d.type === 'bug' || d.type === 'story'; })
            .append('rect').attr('class', 'perf-mm-issue-rect')
            .attr('width', function(d) { var s = d.size || 6; return s * 1.6; })
            .attr('height', function(d) { var s = d.size || 6; return s * 1.6; })
            .attr('x', function(d) { var s = d.size || 6; return -s * 0.8; })
            .attr('y', function(d) { var s = d.size || 6; return -s * 0.8; })
            .attr('rx', 2).attr('ry', 2)
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('fill-opacity', 0.7)
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.3).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 0.8);

          // Strategy diamonds -- covered=solid bright, gap=dashed dimmer
          node.filter(function(d) { return d.type === 'strategy'; })
            .append('polygon').attr('class', 'perf-mm-diamond')
            .attr('points', function(d) {
              var s = d.size || 12;
              return '0,' + (-s) + ' ' + s + ',0 0,' + s + ' ' + (-s) + ',0';
            })
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', function(d) { return d.isCovered ? 1.5 : 2; })
            .attr('stroke-dasharray', function(d) { return d.isCovered ? 'none' : '4,2'; })
            .attr('opacity', function(d) { return d.isCovered ? 0.9 : 0.65; });

          // Secondary pillar dot for multi-pillar ANSTRAT nodes
          var pillarColors = {};
          (graphData.pillarInfo || []).forEach(function(p) { pillarColors[p.id] = p.color; });
          node.filter(function(d) { return d.type === 'anstrat' && d.pillars && d.pillars.length > 1; })
            .each(function(d) {
              var sel = d3.select(this);
              for (var pi = 1; pi < Math.min(d.pillars.length, 4); pi++) {
                var dotColor = pillarColors[d.pillars[pi]] || '#888';
                sel.append('circle')
                  .attr('r', 4)
                  .attr('cx', (d.size || 16) * 2 - 6 - (pi - 1) * 10)
                  .attr('cy', -(d.size || 16) * 1.4 + 4)
                  .attr('fill', dotColor)
                  .attr('stroke', '#111')
                  .attr('stroke-width', 0.5);
              }
            });

          // Inner highlight for competency and root
          node.filter(function(d) { return d.type === 'competency' || d.type === 'root'; })
            .append('circle')
            .attr('r', function(d) { return (d.size || 8) * 0.3; })
            .attr('fill', 'rgba(255,255,255,0.2)')
            .attr('cx', function(d) { return -(d.size || 8) * 0.12; })
            .attr('cy', function(d) { return -(d.size || 8) * 0.12; });

          // Root percentage label
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('class', 'perf-mm-label perf-mm-label--root').attr('text-anchor', 'middle')
            .attr('dy', 5).attr('fill', '#fff').attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });

          // Root quarter label above
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', function(d) { return -d.size - 8; })
            .attr('fill', 'var(--vscode-foreground, #e0e0e0)').attr('font-size', '12px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Pillar labels -- use pillar color, not heat color
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('class', 'perf-mm-label').attr('text-anchor', 'middle')
            .attr('dy', function(d) { return -(d.size || 22) - 8; })
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '11px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Percentage inside pillar ring
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });

          // ANSTRAT labels inside rect
          node.filter(function(d) { return d.type === 'anstrat'; }).append('text')
            .attr('class', 'perf-mm-label').attr('text-anchor', 'middle')
            .attr('dy', 4).attr('fill', '#fff').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          var tooltip = document.getElementById('perfMindmapTooltip');
          setupTooltipAndHighlight(node, link, links, tooltip);

          // Store selections for pillar filter
          perfMmState.nodeSelection = node;
          perfMmState.linkSelection = link;
          perfMmState.allLinks = links;
          perfMmState.glowG = glowG;
          perfMmState.pillarNodes = pillarNodes;

          simulation.on('tick', function() {
            pillarNodes.forEach(function(p, i) {
              d3.select(glowG.selectAll('.perf-mm-heat-glow').nodes()[i])
                .attr('cx', p.x).attr('cy', p.y);
            });
            link.attr('x1', function(d) { return d.source.x; }).attr('y1', function(d) { return d.source.y; })
                .attr('x2', function(d) { return d.target.x; }).attr('y2', function(d) { return d.target.y; });
            node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
          });

          setTimeout(function() { fitPerfMindmap(svg, g, perfMmState.zoom, width, height); }, 1500);
        }

        // ---- Main init ----
        function initPerfMindmap() {
          var dataEl = document.getElementById('perfMindmapData');
          var svgEl = document.getElementById('perfMindmapSvg');
          if (!dataEl || !svgEl) return;

          if (typeof d3 === 'undefined') { setTimeout(initPerfMindmap, 500); return; }

          var graphData;
          try {
            graphData = JSON.parse(dataEl.textContent || '');
            if (!graphData || !graphData.nodes) return;
          } catch (e) { return; }

          var container = document.getElementById('perfMindmapGraph');
          if (!container) return;

          var width = container.clientWidth || 800;
          var height = container.clientHeight || 600;

          var svg = d3.select('#perfMindmapSvg');
          svg.selectAll('g.perf-mm-root').remove();

          var zoomBehavior = d3.zoom().scaleExtent([0.15, 4])
            .on('zoom', function(event) { g.attr('transform', event.transform); });
          svg.call(zoomBehavior);

          var g = svg.append('g').attr('class', 'perf-mm-root');
          perfMmState.svg = svg;
          perfMmState.g = g;
          perfMmState.zoom = zoomBehavior;

          renderCombinedView(graphData, svg, g, container, width, height);
          setupControls(container);
        }

        window._initPerfMindmap = initPerfMindmap;
        setTimeout(initPerfMindmap, 150);
      })();

      // ============ QC Help Tab (D3 Diagrams) ============
      (function() {
        function initPerfHelp() {
          var dataEl = document.getElementById('perfHelpData');
          if (!dataEl) return;
          var hd;
          try { hd = JSON.parse(dataEl.textContent || '{}'); } catch(e) { return; }
          if (!hd.scopeMultipliers) return;

          initPipeline();
          initPyramid(hd);
          initLevelBars(hd);
          initHeatmap(hd);
          initRadar(hd);
          initCompare(hd);
          initTreemap(hd);
          initCapChart(hd);
          initWhatIf(hd);
          initSignalFilter();
          initTraceSelector();
        }

        // 1.1 Pipeline Flow
        function initPipeline() {
          var container = document.getElementById('perf-help-pipeline');
          if (!container || container.querySelector('svg')) return;

          var W = container.clientWidth || 700;
          var H = 340;
          var svg = d3.select(container).append('svg').attr('width', W).attr('height', H).attr('viewBox', '0 0 ' + W + ' ' + H);

          svg.append('defs').append('marker').attr('id', 'pipeline-arrow').attr('viewBox', '0 0 10 10')
            .attr('refX', 10).attr('refY', 5).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#888');

          var stages = [
            { label: 'Git', color: '#60a5fa', x: 40, y: 30, w: 80, h: 32 },
            { label: 'GitLab', color: '#60a5fa', x: 140, y: 30, w: 80, h: 32 },
            { label: 'GitHub', color: '#60a5fa', x: 240, y: 30, w: 80, h: 32 },
            { label: 'Jira', color: '#60a5fa', x: 340, y: 30, w: 80, h: 32 },
            { label: 'Gmail', color: '#60a5fa', x: 440, y: 30, w: 80, h: 32 },

            { label: 'Event Collection', color: '#a78bfa', x: W/2 - 90, y: 90, w: 180, h: 32 },

            { label: 'Scope Detection', color: '#a78bfa', x: 60, y: 150, w: 130, h: 28 },
            { label: 'Role Detection', color: '#a78bfa', x: 210, y: 150, w: 130, h: 28 },
            { label: 'Classification', color: '#a78bfa', x: 360, y: 150, w: 130, h: 28 },
            { label: 'Strategy Align', color: '#a78bfa', x: 510, y: 150, w: 130, h: 28 },

            { label: 'Signal Counting (>= 2)', color: '#f59e0b', x: W/2 - 110, y: 210, w: 220, h: 32 },
            { label: 'Score Formula', color: '#10b981', x: W/2 - 80, y: 260, w: 160, h: 32 },
            { label: 'Daily Cap (15/comp)', color: '#ef4444', x: W/2 - 90, y: 305, w: 180, h: 28 },
          ];

          stages.forEach(function(s) {
            var g = svg.append('g').attr('class', 'perf-help-pipeline-node');
            g.append('rect').attr('x', s.x).attr('y', s.y).attr('width', s.w).attr('height', s.h)
              .attr('rx', 6).attr('fill', s.color + '22').attr('stroke', s.color).attr('stroke-width', 1.5);
            g.append('text').attr('x', s.x + s.w/2).attr('y', s.y + s.h/2).text(s.label);
          });

          var edges = [
            // Sources to Collection
            [80, 62, W/2, 90], [180, 62, W/2, 90], [280, 62, W/2, 90], [380, 62, W/2, 90], [480, 62, W/2, 90],
            // Collection to Enrichment
            [W/2, 122, 125, 150], [W/2, 122, 275, 150], [W/2, 122, 425, 150], [W/2, 122, 575, 150],
            // Enrichment to Signals
            [125, 178, W/2, 210], [275, 178, W/2, 210], [425, 178, W/2, 210], [575, 178, W/2, 210],
            // Signals to Formula
            [W/2, 242, W/2, 260],
            // Formula to Cap
            [W/2, 292, W/2, 305],
          ];

          edges.forEach(function(e) {
            svg.append('line').attr('class', 'perf-help-pipeline-edge')
              .attr('x1', e[0]).attr('y1', e[1]).attr('x2', e[2]).attr('y2', e[3]);
          });
        }

        // 1.2 Pyramid
        function initPyramid(hd) {
          var container = document.getElementById('perf-help-pyramid');
          if (!container || container.querySelector('.perf-help-pyramid-tier')) return;

          var tiers = [
            { name: 'Strategy', mult: 10, type: 'Executive Priorities', color: '#dc2626' },
            { name: 'ANSTRAT', mult: 7, type: 'Initiatives', color: '#ea580c' },
            { name: 'Epic', mult: 4, type: 'Epics', color: '#d97706' },
            { name: 'Story', mult: 2, type: 'Stories / Tasks / Bugs', color: '#65a30d' },
            { name: 'Commit', mult: 1, type: 'Git Commits', color: '#0891b2' },
          ];

          tiers.forEach(function(t, i) {
            var widthPct = 30 + (tiers.length - 1 - i) * 15;
            var div = document.createElement('div');
            div.className = 'perf-help-pyramid-tier';
            div.innerHTML = '<div class="perf-help-pyramid-block" style="width:' + widthPct + '%;background:' + t.color + '">' +
              '<div class="perf-help-pyramid-mult">x' + t.mult + '</div>' +
              '<div class="perf-help-pyramid-label">' + t.name + '</div>' +
              '<div class="perf-help-pyramid-type">' + t.type + '</div>' +
            '</div>';
            container.appendChild(div);
          });

          var bonus = document.createElement('div');
          bonus.className = 'perf-help-strategy-bonus';
          bonus.innerHTML = '<strong>Strategy Alignment Bonus:</strong> Events matching executive priorities receive an additional <strong>1.5x</strong> multiplier on top of the scope multiplier.';
          container.appendChild(bonus);
        }

        // 2.1 Level Bars
        function initLevelBars(hd) {
          var container = document.getElementById('perf-help-levels');
          if (!container || container.querySelector('.perf-help-level-bar-row')) return;

          var order = ['ase','se','sse','pse','spse','de','sde','fellow'];
          var maxTarget = hd.baseTarget * 3.75;

          order.forEach(function(lid) {
            var scale = hd.levelScales[lid] || 1.0;
            var effectiveTarget = Math.round(hd.baseTarget * scale);
            var pct = Math.round((effectiveTarget / maxTarget) * 100);
            var isActive = lid === hd.level;
            var summary = hd.levelSummaries[lid] || '';

            var row = document.createElement('div');
            row.className = 'perf-help-level-bar-row';
            row.innerHTML =
              '<div class="perf-help-level-label' + (isActive ? ' active' : '') + '">' + lid.toUpperCase() + '</div>' +
              '<div class="perf-help-level-bar-track" title="' + summary + '">' +
                '<div class="perf-help-level-bar-fill' + (isActive ? ' active' : '') + '" style="width:' + pct + '%">' +
                  '<span class="perf-help-level-bar-text">' + scale + 'x &rarr; ' + effectiveTarget + '</span>' +
                '</div>' +
              '</div>';
            container.appendChild(row);
          });
        }

        // 2.2 Heatmap
        function initHeatmap(hd) {
          var container = document.getElementById('perf-help-heatmap');
          if (!container || container.querySelector('.perf-help-heatmap')) return;

          var rw = hd.roleWeightsAll[hd.level] || {};
          var scopes = ['commit', 'story', 'epic', 'anstrat', 'strategy'];
          var roles = ['reporter', 'assignee', 'contributor'];

          var maxVal = 0;
          scopes.forEach(function(s) { roles.forEach(function(r) {
            var v = (rw[s] || {})[r] || 0;
            if (v > maxVal) maxVal = v;
          }); });

          var grid = document.createElement('div');
          grid.className = 'perf-help-heatmap';
          grid.style.gridTemplateColumns = '80px repeat(3, 1fr)';

          grid.innerHTML = '<div></div>' + roles.map(function(r) {
            return '<div class="perf-help-heatmap-header">' + r.charAt(0).toUpperCase() + r.slice(1) + '</div>';
          }).join('');

          scopes.forEach(function(s) {
            grid.innerHTML += '<div class="perf-help-heatmap-row-label">' + s + '</div>';
            roles.forEach(function(r) {
              var v = (rw[s] || {})[r] || 0;
              var intensity = maxVal > 0 ? v / maxVal : 0;
              var r_c = Math.round(26 + (190 - 26) * (1 - intensity));
              var g_c = Math.round(54 + (227 - 54) * (1 - intensity));
              var b_c = Math.round(93 + (248 - 93) * (1 - intensity));
              var bg = 'rgb(' + r_c + ',' + g_c + ',' + b_c + ')';
              var textColor = intensity > 0.5 ? '#fff' : '#1a365d';
              grid.innerHTML += '<div class="perf-help-heatmap-cell" style="background:' + bg + ';color:' + textColor + '">' + v + '</div>';
            });
          });

          container.appendChild(grid);
        }

        // 2.3 Radar
        function initRadar(hd) {
          var container = document.getElementById('perf-help-radar');
          if (!container || container.querySelector('svg')) return;

          var pw = hd.pillarWeightsAll[hd.level] || {};
          var pillars = Object.keys(hd.pillarColors);
          var n = pillars.length;
          if (n === 0) return;

          var size = 320, cx = size/2, cy = size/2, R = 120;
          var svg = d3.select(container).append('svg').attr('width', size).attr('height', size)
            .attr('viewBox', '0 0 ' + size + ' ' + size);

          var maxW = 0;
          pillars.forEach(function(p) { if ((pw[p] || 0) > maxW) maxW = pw[p]; });
          maxW = Math.max(maxW, 1.5);

          // Grid circles
          [0.25, 0.5, 0.75, 1.0].forEach(function(f) {
            svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', R * f)
              .attr('fill', 'none').attr('stroke', '#333').attr('stroke-width', 0.5);
          });

          // Axes
          var angleStep = (2 * Math.PI) / n;
          pillars.forEach(function(p, i) {
            var angle = -Math.PI/2 + i * angleStep;
            var ex = cx + R * Math.cos(angle);
            var ey = cy + R * Math.sin(angle);
            svg.append('line').attr('x1', cx).attr('y1', cy).attr('x2', ex).attr('y2', ey)
              .attr('stroke', '#444').attr('stroke-width', 0.5);

            var lx = cx + (R + 24) * Math.cos(angle);
            var ly = cy + (R + 24) * Math.sin(angle);
            svg.append('text').attr('x', lx).attr('y', ly)
              .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
              .attr('font-size', '10px').attr('fill', hd.pillarColors[p] || '#888')
              .text(p.replace('End-to-End ', 'E2E '));
          });

          // Polygon
          var points = pillars.map(function(p, i) {
            var angle = -Math.PI/2 + i * angleStep;
            var r = R * ((pw[p] || 0) / maxW);
            return (cx + r * Math.cos(angle)) + ',' + (cy + r * Math.sin(angle));
          }).join(' ');

          svg.append('polygon').attr('points', points)
            .attr('fill', 'var(--rh-red, #ee0000)').attr('fill-opacity', 0.15)
            .attr('stroke', 'var(--rh-red, #ee0000)').attr('stroke-width', 2);

          // Value dots
          pillars.forEach(function(p, i) {
            var angle = -Math.PI/2 + i * angleStep;
            var r = R * ((pw[p] || 0) / maxW);
            var px = cx + r * Math.cos(angle);
            var py = cy + r * Math.sin(angle);
            svg.append('circle').attr('cx', px).attr('cy', py).attr('r', 4)
              .attr('fill', hd.pillarColors[p] || '#888');
            svg.append('text').attr('x', px).attr('y', py - 10)
              .attr('text-anchor', 'middle').attr('font-size', '11px').attr('font-weight', 'bold')
              .attr('fill', hd.pillarColors[p] || '#888').text(pw[p] || 0);
          });
        }

        // 2.4 Level Compare
        function initCompare(hd) {
          var container = document.getElementById('perf-help-compare');
          var radarContainer = document.getElementById('perf-help-compare-radar');
          var select = document.getElementById('perf-help-compare-level');
          if (!container || !select) return;

          function render() {
            container.innerHTML = '';
            var cmpLevel = select.value;
            var myPw = hd.pillarWeightsAll[hd.level] || {};
            var cmpPw = hd.pillarWeightsAll[cmpLevel] || {};
            var myScale = hd.levelScales[hd.level] || 1;
            var cmpScale = hd.levelScales[cmpLevel] || 1;

            var grid = document.createElement('div');
            grid.className = 'perf-help-compare-grid';

            function colHtml(title, levelId, scale, pw) {
              var target = Math.round(hd.baseTarget * scale);
              var html = '<div class="perf-help-compare-col"><h4>' + title + ' (' + levelId.toUpperCase() + ')</h4>';
              html += '<div class="perf-help-compare-stat"><span>Target Scale</span><span>' + scale + 'x &rarr; ' + target + '</span></div>';
              Object.keys(hd.pillarColors).forEach(function(p) {
                html += '<div class="perf-help-compare-stat"><span>' + p.replace('End-to-End', 'E2E') + '</span><span>' + (pw[p] || 0) + '</span></div>';
              });
              html += '</div>';
              return html;
            }

            grid.innerHTML = colHtml('Your Level', hd.level, myScale, myPw) +
                             colHtml('Compare', cmpLevel, cmpScale, cmpPw);

            container.appendChild(grid);

            // Delta summary
            var deltaDiv = document.createElement('div');
            deltaDiv.style.cssText = 'margin-top:10px;display:flex;flex-wrap:wrap;gap:12px;justify-content:center;font-size:11px;';
            Object.keys(hd.pillarColors).forEach(function(p) {
              var diff = ((cmpPw[p] || 0) - (myPw[p] || 0));
              var cls = diff > 0 ? 'up' : diff < 0 ? 'down' : 'same';
              var arrow = diff > 0 ? '\u2191' : diff < 0 ? '\u2193' : '=';
              deltaDiv.innerHTML += '<span class="font-semibold perf-help-compare-delta ' + cls + '">' +
                p.replace('End-to-End', 'E2E') + ': ' + arrow + ' ' + Math.abs(diff).toFixed(1) + '</span>';
            });
            container.appendChild(deltaDiv);

            renderCompareRadar(hd, radarContainer, myPw, cmpPw, hd.level, cmpLevel);
          }

          render();
          select.addEventListener('change', render);
        }

        function renderCompareRadar(hd, container, myPw, cmpPw, myLevel, cmpLevel) {
          if (!container || typeof d3 === 'undefined') return;
          container.innerHTML = '';

          var pillars = Object.keys(hd.pillarColors);
          var n = pillars.length;
          if (n === 0) return;

          var size = 320, cx = size / 2, cy = size / 2, R = 110;
          var svg = d3.select(container).append('svg')
            .attr('width', size).attr('height', size)
            .attr('viewBox', '0 0 ' + size + ' ' + size);

          var maxW = 0;
          pillars.forEach(function(p) {
            var v1 = myPw[p] || 0, v2 = cmpPw[p] || 0;
            if (v1 > maxW) maxW = v1;
            if (v2 > maxW) maxW = v2;
          });
          maxW = Math.max(maxW, 1.5);

          var angleStep = (2 * Math.PI) / n;

          [0.25, 0.5, 0.75, 1.0].forEach(function(f) {
            svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', R * f)
              .attr('fill', 'none').attr('stroke', '#333').attr('stroke-width', 0.5);
          });

          pillars.forEach(function(p, i) {
            var angle = -Math.PI / 2 + i * angleStep;
            var ex = cx + R * Math.cos(angle);
            var ey = cy + R * Math.sin(angle);
            svg.append('line').attr('x1', cx).attr('y1', cy).attr('x2', ex).attr('y2', ey)
              .attr('stroke', '#444').attr('stroke-width', 0.5);

            var lx = cx + (R + 28) * Math.cos(angle);
            var ly = cy + (R + 28) * Math.sin(angle);
            svg.append('text').attr('x', lx).attr('y', ly)
              .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
              .attr('font-size', '10px').attr('fill', hd.pillarColors[p] || '#888')
              .text(p.replace('End-to-End ', 'E2E '));
          });

          function polyPoints(pw) {
            return pillars.map(function(p, i) {
              var angle = -Math.PI / 2 + i * angleStep;
              var r = R * ((pw[p] || 0) / maxW);
              return (cx + r * Math.cos(angle)) + ',' + (cy + r * Math.sin(angle));
            }).join(' ');
          }

          svg.append('polygon').attr('points', polyPoints(cmpPw))
            .attr('fill', '#888').attr('fill-opacity', 0.08)
            .attr('stroke', '#888').attr('stroke-width', 1.5)
            .attr('stroke-dasharray', '6,3');

          svg.append('polygon').attr('points', polyPoints(myPw))
            .attr('fill', 'var(--rh-red, #ee0000)').attr('fill-opacity', 0.15)
            .attr('stroke', 'var(--rh-red, #ee0000)').attr('stroke-width', 2);

          pillars.forEach(function(p, i) {
            var angle = -Math.PI / 2 + i * angleStep;

            var r1 = R * ((myPw[p] || 0) / maxW);
            svg.append('circle')
              .attr('cx', cx + r1 * Math.cos(angle)).attr('cy', cy + r1 * Math.sin(angle))
              .attr('r', 4).attr('fill', 'var(--rh-red, #ee0000)');
            svg.append('text')
              .attr('x', cx + r1 * Math.cos(angle)).attr('y', cy + r1 * Math.sin(angle) - 10)
              .attr('text-anchor', 'middle').attr('font-size', '10px').attr('font-weight', 'bold')
              .attr('fill', 'var(--rh-red, #ee0000)').text(myPw[p] || 0);

            var r2 = R * ((cmpPw[p] || 0) / maxW);
            svg.append('circle')
              .attr('cx', cx + r2 * Math.cos(angle)).attr('cy', cy + r2 * Math.sin(angle))
              .attr('r', 3).attr('fill', '#888').attr('stroke', '#fff').attr('stroke-width', 0.5);
          });

          svg.append('text').attr('x', 8).attr('y', size - 6)
            .attr('font-size', '9px').attr('fill', 'var(--rh-red, #ee0000)')
            .text('\u25CF ' + myLevel.toUpperCase());
          svg.append('text').attr('x', 8).attr('y', size - 18)
            .attr('font-size', '9px').attr('fill', '#888')
            .text('\u25CB ' + cmpLevel.toUpperCase() + ' (dashed)');
        }

        // 3.2 Treemap
        function initTreemap(hd) {
          var container = document.getElementById('perf-help-treemap');
          if (!container || container.querySelector('svg') || typeof d3 === 'undefined') return;

          var tab = document.getElementById('performance');
          if (!tab) return;

          var compEls = tab.querySelectorAll('[data-action="toggleCompetency"]');
          var treeData = { name: 'Score', children: [] };
          var pillarMap = {};

          compEls.forEach(function(el) {
            var key = el.getAttribute('data-key');
            if (!key) return;
            var ptsEl = el.querySelector('.perf-comp-score-pts, .stat-value');
            var pts = ptsEl ? parseInt(ptsEl.textContent, 10) : 0;
            if (isNaN(pts) || pts <= 0) pts = 1;

            var catEl = el.closest('.section');
            var catTitle = 'Technical Contribution';
            if (catEl) {
              var titleEl = catEl.querySelector('.section-title');
              if (titleEl) catTitle = titleEl.textContent.trim();
            }
            if (!pillarMap[catTitle]) pillarMap[catTitle] = { name: catTitle, children: [] };

            var label = el.textContent.trim().split('\\n')[0].trim();
            pillarMap[catTitle].children.push({ name: label || key, value: pts });
          });

          // Fallback: use meta from perfHelpData if no DOM competency elements
          if (Object.keys(pillarMap).length === 0) {
            Object.keys(hd.pillarColors).forEach(function(p) {
              pillarMap[p] = { name: p, children: [{ name: p + ' (no data)', value: 1 }] };
            });
          }

          Object.keys(pillarMap).forEach(function(p) {
            treeData.children.push(pillarMap[p]);
          });

          var W = container.clientWidth || 600;
          var H = 250;
          var svg = d3.select(container).append('svg').attr('width', W).attr('height', H);

          var root = d3.hierarchy(treeData).sum(function(d) { return d.value || 0; }).sort(function(a, b) { return b.value - a.value; });
          d3.treemap().size([W, H]).padding(2)(root);

          var cell = svg.selectAll('g').data(root.leaves()).enter().append('g')
            .attr('class', 'perf-help-treemap-cell')
            .attr('transform', function(d) { return 'translate(' + d.x0 + ',' + d.y0 + ')'; });

          cell.append('rect')
            .attr('width', function(d) { return Math.max(0, d.x1 - d.x0); })
            .attr('height', function(d) { return Math.max(0, d.y1 - d.y0); })
            .attr('rx', 3)
            .attr('fill', function(d) {
              var parent = d.parent ? d.parent.data.name : '';
              return hd.pillarColors[parent] || '#555';
            })
            .attr('fill-opacity', 0.7);

          cell.append('text')
            .attr('x', 4).attr('y', 14)
            .text(function(d) {
              var w = d.x1 - d.x0;
              if (w < 40) return '';
              var t = d.data.name;
              return t.length > Math.floor(w / 6) ? t.substring(0, Math.floor(w / 6) - 2) + '..' : t;
            });

          cell.append('text')
            .attr('x', 4).attr('y', 26).attr('font-size', '9px').attr('fill-opacity', 0.7)
            .text(function(d) { return (d.x1 - d.x0) > 50 ? d.value + ' pts' : ''; });
        }

        // 3.3 Cap Impact
        function initCapChart(hd) {
          var container = document.getElementById('perf-help-cap');
          if (!container || container.querySelector('.perf-help-level-bar-row')) return;

          var comps = hd.competencyData || [];
          if (comps.length === 0) {
            var msgDiv = document.createElement('div');
            msgDiv.className = 'perf-help-empty';
            msgDiv.textContent = 'Cap impact analysis requires daily event data. Use Collect or Backfill to populate, then return here.';
            container.appendChild(msgDiv);
            return;
          }

          var target = Math.round(hd.baseTarget * (hd.levelScales[hd.level] || 1.25));

          comps.forEach(function(c) {
            var pts = c.points || 0;
            var label = c.name || c.id;
            var pct = target > 0 ? Math.min(Math.round(pts / target * 100), 100) : 0;
            var color = pct >= 75 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#ef4444';

            var row = document.createElement('div');
            row.className = 'perf-help-level-bar-row';
            row.innerHTML =
              '<div class="perf-help-level-label perf-help-level-label-wide">' + (label.length > 18 ? label.substring(0,16) + '..' : label) + '</div>' +
              '<div class="perf-help-level-bar-track">' +
                '<div class="perf-help-level-bar-fill" style="width:' + pct + '%;background:' + color + '">' +
                  '<span class="perf-help-level-bar-text">' + pts + '/' + target + ' (' + pct + '%)</span>' +
                '</div>' +
              '</div>';
            container.appendChild(row);
          });
        }

        // 3.4 What-If
        function initWhatIf(hd) {
          var compSel = document.getElementById('perf-help-wi-comp');
          var scopeSel = document.getElementById('perf-help-wi-scope');
          var roleSel = document.getElementById('perf-help-wi-role');
          var stratChk = document.getElementById('perf-help-wi-strat');
          var resultDiv = document.getElementById('perf-help-whatif-result');
          if (!compSel || !scopeSel || !roleSel || !stratChk || !resultDiv) return;

          function calc() {
            var opt = compSel.options[compSel.selectedIndex];
            var base = parseInt(opt.getAttribute('data-base') || '3', 10);
            var category = opt.getAttribute('data-category') || 'Technical Contribution';
            var scope = scopeSel.value;
            var role = roleSel.value;
            var aligned = stratChk.checked;

            var scopeMult = hd.scopeMultipliers[scope] || 1;
            var rw = hd.roleWeightsAll[hd.level] || {};
            var roleWeight = (rw[scope] || {})[role] || 1.0;
            var pw = hd.pillarWeightsAll[hd.level] || {};
            var pillarWeight = pw[category] || 1.0;
            var stratBonus = aligned ? 1.5 : 1.0;
            var result = Math.round(base * scopeMult * roleWeight * pillarWeight * stratBonus);

            resultDiv.innerHTML =
              '<div class="perf-help-formula-row">' +
                '<div class="perf-help-factor perf-help-factor-blue"><div class="perf-help-factor-value">' + base + '</div><div class="perf-help-factor-label">base</div></div>' +
                '<span class="perf-help-operator">&times;</span>' +
                '<div class="perf-help-factor perf-help-factor-orange"><div class="perf-help-factor-value">x' + scopeMult + '</div><div class="perf-help-factor-label">' + scope + '</div></div>' +
                '<span class="perf-help-operator">&times;</span>' +
                '<div class="perf-help-factor perf-help-factor-purple"><div class="perf-help-factor-value">' + roleWeight + '</div><div class="perf-help-factor-label">' + role + '</div></div>' +
                '<span class="perf-help-operator">&times;</span>' +
                '<div class="perf-help-factor" style="border-color:' + (hd.pillarColors[category] || '#888') + '"><div class="perf-help-factor-value">' + pillarWeight + '</div><div class="perf-help-factor-label">pillar</div></div>' +
                '<span class="perf-help-operator">&times;</span>' +
                '<div class="perf-help-factor perf-help-factor-gold"><div class="perf-help-factor-value">' + stratBonus + '</div><div class="perf-help-factor-label">strategy</div></div>' +
                '<span class="perf-help-operator">=</span>' +
                '<div class="perf-help-factor perf-help-factor-result"><div class="perf-help-factor-value">' + result + '</div><div class="perf-help-factor-label">points</div></div>' +
              '</div>';
          }

          calc();
          compSel.addEventListener('change', calc);
          scopeSel.addEventListener('change', calc);
          roleSel.addEventListener('change', calc);
          stratChk.addEventListener('change', calc);
        }

        // 1.4 Signal Filter
        function initSignalFilter() {
          var input = document.getElementById('perf-help-signal-filter');
          if (!input) return;
          input.addEventListener('input', function() {
            var query = input.value.toLowerCase();
            document.querySelectorAll('.perf-help-signal-row').forEach(function(row) {
              var searchText = row.getAttribute('data-search') || '';
              row.classList.toggle('hidden', query.length > 0 && searchText.indexOf(query) === -1);
            });
          });
        }

        // 3.1 Event Trace
        function initTraceSelector() {
          var dateSel = document.getElementById('perf-help-trace-date');
          var container = document.getElementById('perf-help-trace');
          if (!dateSel || !container) return;

          dateSel.addEventListener('change', function() {
            var date = dateSel.value;
            if (!date) {
              container.innerHTML = '<div class="perf-help-empty">Select a day above to trace an event.</div>';
              return;
            }
            container.innerHTML = '<div class="perf-help-empty">Loading events for ' + date + '...</div>';
            vscode.postMessage({ command: 'performanceAction', action: 'helpTraceDate', date: date });
          });
        }

        // Listen for trace results
        window.addEventListener('message', function(event) {
          var msg = event.data;
          if (msg && msg.command === 'helpTraceResult' && msg.html) {
            var traceContainer = document.getElementById('perf-help-trace');
            if (traceContainer) traceContainer.innerHTML = msg.html;
          }
        });

        window._initPerfHelp = initPerfHelp;
        setTimeout(initPerfHelp, 200);
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
      case "addNote":
        await this.addNoteToQuestion(message.questionId);
        break;
      case "evaluate":
        await this.evaluateQuestion(message.questionId);
        break;
      case "toggleEvidence":
        await this.toggleEvidencePanel(message.questionId);
        break;
      case "toggleEvidenceItem":
        this.toggleEvidenceItem(message.questionId, message.evidenceId);
        break;
      case "selectAllEvidence":
        this.selectAllEvidence(message.questionId);
        break;
      case "deselectAllEvidence":
        this.deselectAllEvidence(message.questionId);
        break;
      case "switchTab": {
        const leavingSettings = this.state.active_tab === "settings";
        this.state.active_tab = message.key || "overview";
        if (this.state.active_tab === "mindmap" || this.state.active_tab === "help") {
          this.forceNextRender = true;
        }
        if (leavingSettings && this._settingsDirty) {
          this._settingsDirty = false;
          if (this._settingsRefreshTimer) {
            clearTimeout(this._settingsRefreshTimer);
            this._settingsRefreshTimer = null;
          }
          this.refresh();
        } else {
          this.notifyNeedsRender();
        }
        break;
      }
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
      case "setEngineeringLevel":
        this.setEngineeringLevel(message.value);
        break;
      case "setScopeMultiplier":
        this.setScopeMultiplier(message.scope, message.value);
        break;
      case "setRoleWeight":
        this.setRoleWeight(message.scope, message.role, message.value);
        break;
      case "setPillarWeight":
        this.setPillarWeight(message.pillar, message.value);
        break;
      case "setStrategyEnabled":
        this.setStrategyField("enabled", message.value);
        break;
      case "setStrategyBonus":
        this.setStrategyField("bonus_multiplier", parseFloat(message.value));
        break;
      case "setStrategyEnrich":
        this.setStrategyField("enrich_classification", message.value);
        break;
      case "setStrategyMinOverlap":
        this.setStrategyField("min_text_overlap_words", parseInt(message.value, 10));
        break;
      case "setNpuEnabled":
        this.setNpuField("enabled", message.value);
        break;
      case "setNpuDevice":
        this.setNpuField("device", message.value);
        break;
      case "setNpuThreshold":
        this.setNpuField("confidence_threshold", parseFloat(message.value));
        break;
      case "setNpuBonusSignals":
        this.setNpuField("bonus_signals", parseInt(message.value, 10));
        break;

      // ---- Executive Email Sources ----
      case "addExecutiveSender":
        await this.addExecutiveSender(message.value);
        break;
      case "removeExecutiveSender":
        await this.removeExecutiveSender(message.value);
        break;
      case "deleteExecutiveEmail":
        await this.deleteExecutiveEmail(message.value);
        break;
      case "backfillExecutiveEmails":
        await this.backfillExecutiveEmails();
        break;
      case "refreshExecutiveEmails":
        await this.refreshExecutiveEmails();
        break;
      case "helpTraceDate":
        await this.loadHelpTraceEvents(message.date);
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

  private async addNoteToQuestion(questionId: string): Promise<void> {
    if (!questionId) return;
    const note = await vscode.window.showInputBox({
      prompt: "Enter a note for this question",
      placeHolder: "Your note...",
    });
    if (!note) return;
    try {
      const result = await dbus.stats_addQuestionNote(questionId, note);
      if (result.success) {
        const data = result.data as any;
        if (data?.questions_summary) {
          this.state.questions_summary = data.questions_summary;
        }
        this.notifyNeedsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to add note: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error adding note: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async evaluateQuestion(questionId: string): Promise<void> {
    if (!questionId) return;
    const excluded = this._excludedEvidence.get(questionId);
    const excludedList = excluded ? Array.from(excluded) : [];

    const inputObj: Record<string, any> = { question_id: questionId };
    if (excludedList.length > 0) {
      inputObj.exclude_evidence = excludedList;
    }

    const evidence = this._questionEvidence.get(questionId);
    const question = this.state.questions_summary?.find(q => q.id === questionId);
    const totalEvidence = evidence ? evidence.length : (question?.evidence_count || 0);
    const selectedCount = evidence ? evidence.length - excludedList.length : totalEvidence;
    const notesCount = question?.notes_count || 0;

    const evalCommand = `Evaluate the quarterly performance question "${questionId}" using AI.

Step 1: Run the evaluate skill to gather evidence and build the prompt:
skill_run("performance_evaluate_questions", '${JSON.stringify(inputObj)}')

Step 2: Read the evidence and prompt from the skill output, then write a 2-3 paragraph first-person response highlighting significant accomplishments with specific examples and metrics.

Step 3: Save your generated response using:
performance_save_evaluation("${questionId}", "<your generated response>")

There are ${selectedCount} of ${totalEvidence} evidence items and ${notesCount} notes available.
After saving, the QC tab will show the result inline on the card.`;

    vscode.window.showInformationMessage(`Evaluating "${questionId}" (${selectedCount} items)...`);
    await createNewChat({
      message: evalCommand,
      autoSubmit: true,
      returnToPrevious: true,
    });
  }

  private async toggleEvidencePanel(questionId: string): Promise<void> {
    if (!questionId) return;

    if (this._expandedQuestions.has(questionId)) {
      this._expandedQuestions.delete(questionId);
      this.notifyNeedsRender();
      return;
    }

    this._expandedQuestions.add(questionId);

    if (!this._questionEvidence.has(questionId)) {
      this._questionEvidenceLoading.add(questionId);
      this.notifyNeedsRender();

      try {
        const result = await dbus.stats_getQuestionDetail(questionId);
        if (result.success && result.data) {
          const data = result.data as any;
          this._questionEvidence.set(questionId, data.evidence || []);
        }
      } catch (error) {
        logger.log(`Failed to load evidence for ${questionId}: ${error}`);
      } finally {
        this._questionEvidenceLoading.delete(questionId);
      }
    }

    this.notifyNeedsRender();
  }

  private toggleEvidenceItem(questionId: string, evidenceId: string): void {
    if (!questionId || !evidenceId) return;
    let excluded = this._excludedEvidence.get(questionId);
    if (!excluded) {
      excluded = new Set<string>();
      this._excludedEvidence.set(questionId, excluded);
    }

    if (excluded.has(evidenceId)) {
      excluded.delete(evidenceId);
    } else {
      excluded.add(evidenceId);
    }
    this.notifyNeedsRender();
  }

  private selectAllEvidence(questionId: string): void {
    if (!questionId) return;
    this._excludedEvidence.delete(questionId);
    this.notifyNeedsRender();
  }

  private deselectAllEvidence(questionId: string): void {
    if (!questionId) return;
    const evidence = this._questionEvidence.get(questionId);
    if (!evidence) return;
    this._excludedEvidence.set(questionId, new Set(evidence.map(e => e.id)));
    this.notifyNeedsRender();
  }

  // ============================================================
  // Scoring Config Handlers
  // ============================================================

  private setEngineeringLevel(level: string): void {
    if (!this.state.scoring_config || !level) return;
    this.state.scoring_config.engineering_level = level;
    this._pendingLevelRefresh = true;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private setScopeMultiplier(scope: string, value: string | number): void {
    if (!this.state.scoring_config || !scope) return;
    const cfg = this.state.scoring_config as any;
    if (!cfg.scope_multipliers) cfg.scope_multipliers = {};
    cfg.scope_multipliers[scope] = typeof value === "string" ? parseInt(value, 10) : value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private setRoleWeight(scope: string, role: string, value: string | number): void {
    if (!this.state.scoring_config || !scope || !role) return;
    const cfg = this.state.scoring_config as any;
    if (!cfg.level_weights) cfg.level_weights = {};
    if (!cfg.level_weights.role_weights) cfg.level_weights.role_weights = {};
    if (!cfg.level_weights.role_weights[scope]) cfg.level_weights.role_weights[scope] = {};
    cfg.level_weights.role_weights[scope][role] = typeof value === "string" ? parseFloat(value) : value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private setPillarWeight(pillar: string, value: string | number): void {
    if (!this.state.scoring_config || !pillar) return;
    const cfg = this.state.scoring_config as any;
    if (!cfg.level_weights) cfg.level_weights = {};
    if (!cfg.level_weights.pillar_weights) cfg.level_weights.pillar_weights = {};
    cfg.level_weights.pillar_weights[pillar] = typeof value === "string" ? parseFloat(value) : value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private setStrategyField(field: string, value: unknown): void {
    if (!this.state.scoring_config) return;
    const cfg = this.state.scoring_config as any;
    if (!cfg.strategy_alignment) cfg.strategy_alignment = {};
    cfg.strategy_alignment[field] = value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private setNpuField(field: string, value: unknown): void {
    if (!this.state.scoring_config) return;
    const cfg = this.state.scoring_config as any;
    if (!cfg.npu_settings) cfg.npu_settings = {};
    cfg.npu_settings[field] = value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private updateScoringGlobal(field: string, value: number): void {
    if (!this.state.scoring_config || !field) return;
    (this.state.scoring_config as any)[field] = value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private updateCompBasePoints(compId: string, value: number): void {
    if (!this.state.scoring_config?.competencies?.[compId]) return;
    this.state.scoring_config.competencies[compId].base_points = value;
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
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
    this.debouncedSaveScoringConfig();
    this.deferredSettingsRender();
  }

  private removeScoringTag(field: "phrases" | "keywords", compId: string, value: string): void {
    if (!this.state.scoring_config?.competencies?.[compId] || !value) return;
    const arr = this.state.scoring_config.competencies[compId][field];
    const idx = arr.indexOf(value);
    if (idx >= 0) {
      arr.splice(idx, 1);
      this.debouncedSaveScoringConfig();
      this.deferredSettingsRender();
    }
  }

  private addScoringTag(field: "phrases" | "keywords", compId: string, value: string): void {
    if (!this.state.scoring_config?.competencies?.[compId] || !value) return;
    const arr = this.state.scoring_config.competencies[compId][field];
    if (!arr.includes(value)) {
      arr.push(value);
      this.debouncedSaveScoringConfig();
      this.deferredSettingsRender();
    }
  }

  // ============================================================
  // Executive Email Source Management
  // ============================================================

  private async addExecutiveSender(email: string): Promise<void> {
    if (!email || !email.includes("@")) return;
    const normalized = email.trim().toLowerCase();
    if (this.state.executive_senders.includes(normalized)) return;
    const updated = [...this.state.executive_senders, normalized];
    try {
      const result = await dbus.stats_setExecutiveSenders(updated);
      if (result.success && result.data) {
        this.state.executive_senders = (result.data as any).senders || updated;
        this.deferredSettingsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to add sender: ${result.error}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Error adding sender: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private async removeExecutiveSender(email: string): Promise<void> {
    if (!email) return;
    const updated = this.state.executive_senders.filter(s => s !== email);
    try {
      const result = await dbus.stats_setExecutiveSenders(updated);
      if (result.success && result.data) {
        this.state.executive_senders = (result.data as any).senders || updated;
        this.deferredSettingsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to remove sender: ${result.error}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Error removing sender: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private async deleteExecutiveEmail(emailId: string): Promise<void> {
    if (!emailId) return;
    try {
      const result = await dbus.stats_deleteExecutiveEmail(emailId);
      if (result.success) {
        this.state.executive_emails = this.state.executive_emails.filter(e => e.email_id !== emailId);
        this.deferredSettingsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to delete email: ${result.error}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Error deleting email: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private async backfillExecutiveEmails(): Promise<void> {
    vscode.window.showInformationMessage("Backfilling executive emails for this quarter...");
    try {
      const result = await dbus.stats_backfillExecutiveEmails();
      if (result.success) {
        const data = result.data as any;
        vscode.window.showInformationMessage(
          `Backfill complete: ${data?.new_emails ?? 0} new emails fetched`
        );
        await this.refreshExecutiveEmails();
      } else {
        vscode.window.showErrorMessage(`Backfill failed: ${result.error}`);
      }
    } catch (e) {
      vscode.window.showErrorMessage(`Backfill error: ${e instanceof Error ? e.message : String(e)}`);
    }
  }

  private async refreshExecutiveEmails(): Promise<void> {
    try {
      const result = await dbus.stats_listExecutiveEmails();
      if (result.success && result.data) {
        this.state.executive_emails = (result.data as any).emails || [];
        this.deferredSettingsRender();
      }
    } catch (e) {
      logger.warn(`Failed to refresh executive emails: ${e}`);
    }
  }

  /**
   * Re-render after a settings change. With morphdom in place, the render
   * patches only changed DOM nodes so it is safe to run immediately without
   * destroying form state, scroll, or focus.  We still debounce at 150ms
   * (the BaseTab default) to coalesce rapid-fire changes (e.g. typing).
   */
  private _settingsRenderTimer: ReturnType<typeof setTimeout> | null = null;
  private deferredSettingsRender(): void {
    if (this._settingsRenderTimer) {
      clearTimeout(this._settingsRenderTimer);
    }
    this._settingsRenderTimer = null;
    this.invalidateFingerprint();
    this.notifyNeedsRender();
  }

  private debouncedSaveScoringConfig(): void {
    if (this._scoringSaveTimer) {
      clearTimeout(this._scoringSaveTimer);
    }
    this._scoringSaveTimer = setTimeout(() => {
      this._scoringSaveTimer = null;
      this.saveScoringConfig();
    }, 1500);
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
      if ((cfg as any).scope_multipliers) {
        payload.scope_multipliers = (cfg as any).scope_multipliers;
      }
      if ((cfg as any).level_weights) {
        const lw = (cfg as any).level_weights;
        if (lw.role_weights || lw.pillar_weights) {
          payload.level_weight_overrides = {
            role_weights: lw.role_weights,
            pillar_weights: lw.pillar_weights,
          };
        }
      }
      if ((cfg as any).strategy_alignment) {
        payload.strategy_alignment = (cfg as any).strategy_alignment;
      }
      if ((cfg as any).npu_settings) {
        payload.npu_settings = (cfg as any).npu_settings;
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

  /**
   * Schedule a deferred refresh that reloads config from the backend.
   * Fires 1s after the last call so rapid changes coalesce.
   */
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

  private async loadHelpTraceEvents(dateStr: string): Promise<void> {
    try {
      const result = await dbus.stats_getDayDetail(dateStr);
      if (result.success && result.data) {
        const raw = result.data as any;
        const events: DayEvent[] = Array.isArray(raw.events) ? raw.events : [];

        const cfg = this.state.scoring_config;
        const level = cfg?.engineering_level || "sse";
        const scopeMultipliers: Record<string, number> = { commit: 1, story: 2, epic: 4, anstrat: 7, strategy: 10 };

        let traceHtml = "";
        if (events.length === 0) {
          traceHtml = `<div class="perf-help-empty">No events found for ${this.escapeHtml(dateStr)}.</div>`;
        } else {
          traceHtml = events.slice(0, 10).map((ev, idx) => {
            const scope = (ev as any).scope || "story";
            const role = (ev as any).role || "assignee";
            const strategyAligned = (ev as any).strategy_aligned || false;
            const scopeMult = scopeMultipliers[scope] || 1;
            const totalPts = Object.values(ev.points || {}).reduce((s: number, v: number) => s + v, 0);
            const compsHit = Object.keys(ev.points || {}).length;
            const lineageStr = (ev.lineage || []).map(l =>
              `${this.escapeHtml(l.key)}${l.epic ? ` &rarr; ${this.escapeHtml(l.epic.key)}` : ""}${l.anstrat ? ` &rarr; ${this.escapeHtml(l.anstrat.key)}` : ""}`
            ).join(", ") || "none";

            return `
              <div class="perf-help-trace-step pass">
                <div class="perf-help-trace-step-num">${idx + 1}</div>
                <div class="perf-help-trace-step-content">
                  <strong>${this.escapeHtml(ev.title || ev.item_id)}</strong>
                  <div class="text-secondary text-sm mt-4">
                    Source: <strong>${this.escapeHtml(ev.source)}</strong> &middot;
                    Type: <strong>${this.escapeHtml(ev.type)}</strong> &middot;
                    Scope: <strong>${this.escapeHtml(scope)} (x${scopeMult})</strong> &middot;
                    Role: <strong>${this.escapeHtml(role)}</strong>
                    ${strategyAligned ? ` &middot; <span class="text-strategy">Strategy Aligned (1.5x)</span>` : ""}
                  </div>
                  <div class="text-secondary text-sm">Lineage: ${lineageStr}</div>
                  <div class="text-sm mt-4">
                    <strong>${totalPts} pts</strong> across ${compsHit} competencies:
                    ${Object.entries(ev.points || {}).map(([c, p]) =>
                      `<span class="mr-6">${this.escapeHtml(c)}: ${p}</span>`
                    ).join("")}
                  </div>
                </div>
              </div>
            `;
          }).join("");

          if (events.length > 10) {
            traceHtml += `<div class="perf-help-empty">Showing 10 of ${events.length} events.</div>`;
          }
        }

        this.postMessageToWebview({
          command: "helpTraceResult",
          html: traceHtml,
        });
      }
    } catch (e) {
      logger.warn(`Failed to load help trace events: ${e}`);
      this.postMessageToWebview({
        command: "helpTraceResult",
        html: `<div class="perf-help-empty">Failed to load events.</div>`,
      });
    }
  }
}
