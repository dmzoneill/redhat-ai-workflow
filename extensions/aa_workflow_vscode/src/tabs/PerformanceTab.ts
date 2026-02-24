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
  no_enrichment_points?: number;
  no_enrichment_percentage?: number;
  peer_comparable_points?: number;
  peer_comparable_percentage?: number;
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

interface PillarPoints {
  technical: number;
  leadership: number;
  mentorship: number;
  delivery: number;
}

interface IssueNode {
  key: string;
  summary: string;
  type: string;
  points: number;
  event_count: number;
  keywords: string[];
  strategy_aligned: boolean;
  strategy_names: string[];
  pillar_points: PillarPoints;
  scope_points: Record<string, number>;
  children: IssueNode[];
}

interface IssueSummary {
  total_points: number;
  aligned_points: number;
  unaligned_points: number;
  alignment_pct: number;
  scope_points: Record<string, number>;
  pillar_points: PillarPoints;
  tag_counts: Record<string, number>;
}

interface IssueHierarchy {
  strategies: IssueNode[];
  unattached_epics: IssueNode[];
  uncategorized: IssueNode[];
  total_issues: number;
  cached: boolean;
  summary: IssueSummary;
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
  owner_names?: string[];
}

interface SenderRelationship {
  sender: string;
  anstrat_key: string;
  match_types: string[];
  evidence: string[];
  confidence: number;
}

interface SenderSummary {
  total_emails: number;
  jira_issues?: number;
  gdrive_docs?: number;
  anstrat_count: number;
  top_themes: string[];
  coverage: number;
}

// Ownership is derived passively (emails, Jira reporter, GDrive), not from Jira assignee.

interface StrategyAlignment {
  emails_loaded: number;
  senders: string[];
  priorities: StrategyAlignmentPriority[];
  themes: { name: string; matched_keywords: string[]; strength: number }[];
  pillar_summary: Record<string, { competency_points: number; priority_count: number; covered: number; gaps: number }>;
  coverage_summary: { total_priorities: number; covered: number; gaps: number; coverage_pct: number };
  user_work_summary?: { jira_issues: number; gitlab_mrs: number };
  sender_relationships?: { relationships: SenderRelationship[]; sender_summaries: Record<string, SenderSummary>; data_sources?: Record<string, number> };
  anstrat_catalog_count?: number;
  jira_activity_summary?: Record<string, { issue_count: number; projects: string[]; themes: string[] }>;
  gdrive_summary?: { total_docs: number; direct_docs: number; keyword_docs: number };
}

interface PerformanceState {
  last_updated: string;
  quarter: string;
  day_of_quarter: number;
  overall_percentage: number;
  no_enrichment_overall: number;
  peer_comparable_overall: number;
  event_counts_by_source: Record<string, number>;
  comparable_event_counts_by_source: Record<string, number>;
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
  peer_benchmarks: PeerBenchmarks | null;
  org_stats: OrgStats | null;
  competency_view: "sunburst" | "mindmap";
  heatmap_mode: "percentage" | "raw_points" | "peer_comparable";
  event_volume_mode: "all" | "comparable";
  session_enrichment: boolean;
  peer_comparison_mode: "raw" | "comparable";
  ai_peer_narrative: { narrative: string; source: string } | null;
  ai_peer_differentiators: {
    level_differentiators: Record<string, { competency: string; name: string; level_avg: number; others_avg: number; factor: number }[]>;
    user_vs_target: { strengths: { name: string; user: number; target: number; delta: number }[]; gaps: { name: string; user: number; target: number; delta: number }[]; target_level: string; target_label: string };
  } | null;
  ai_overview_digest: { digest: string; trend: { projected_final: number | null; status: string }; source: string } | null;
  ai_calendar_insights: { patterns: { type: string; message: string; severity: string }[]; forecast: { current_pct: number; projected_pct: number; remaining_weekdays: number } | null } | null;
  ai_promotion_readiness: {
    next_level: string; next_level_label: string; target_overall: number;
    ready_count: number; total_competencies: number;
    assessments: { name: string; user_pct: number; target_pct: number; delta: number; status: string }[];
    summary: string; source: string;
  } | null;
}

interface DistributionStats {
  min: number;
  max: number;
  median: number;
  p25: number;
  p75: number;
  avg: number;
  count: number;
}

interface PeerLevelData {
  engineers: string[];
  peer_count: number;
  roster_count?: number;
  avg_competency_pct: Record<string, number>;
  avg_competency_points: Record<string, number>;
  avg_overall_pct: number;
  comparable_avg_competency_pct?: Record<string, number>;
  comparable_avg_overall_pct?: number;
  comparable_stats_competency?: Record<string, DistributionStats>;
  comparable_stats_overall?: DistributionStats;
  avg_daily_events: number;
  avg_days_with_events?: number;
  avg_event_counts_by_source: Record<string, number>;
  stats_overall?: DistributionStats;
  stats_competency?: Record<string, DistributionStats>;
}

interface PeerBenchmarks {
  levels: Record<string, PeerLevelData>;
  last_updated: string | null;
}

interface OrgStats {
  available: boolean;
  total_org_chart: number;
  total_resolved: number;
  total_unresolved: number;
  by_level: Record<string, number>;
  sampled_per_level: Record<string, number>;
  selected_per_level: number;
  generated: string;
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
      { id: "peers", label: "Peers", icon: "\u{1F465}" },
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
            <div class="text-secondary text-sm mt-4">Day ${this.state.day_of_quarter} of 90 &middot; ${this.getEffectiveOverall()}% overall &middot; ${this.state.coverage.captured}/${this.state.coverage.total_weekdays} days captured</div>
          </div>
          <div class="d-flex gap-8 items-center">
            <button class="btn btn-xs btn-ghost" data-action="collectDaily" title="Collect today's data (user + peers)">Collect Today</button>
            <button class="btn btn-xs btn-ghost" data-action="backfill" title="Backfill all quarter data (user, peers, emails)">Backfill</button>
            <button class="btn btn-xs btn-ghost" data-action="toggleBackfillOptions" title="Filtered backfill options" style="opacity:0.8;">Backfill...</button>
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
      <div id="peerBackfillProgress" class="backfill-progress-panel" style="display:none;">
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
      <div id="backfillOptionsPanel" style="display:none; margin-bottom:8px; padding:12px; border:1px solid var(--vscode-panel-border); border-radius:6px; background:var(--vscode-editor-background);">
        <div style="font-weight:600; margin-bottom:8px; font-size:12px;">Backfill Options</div>
        <div style="display:flex; gap:16px; flex-wrap:wrap; align-items:start;">
          <div>
            <div class="text-xs text-secondary" style="margin-bottom:4px;">Sources</div>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfSrcGit" checked /> Git</label>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfSrcJira" checked /> Jira</label>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfSrcGitlab" checked /> GitLab</label>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfSrcGithub" checked /> GitHub</label>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfSrcGdrive" checked /> Google Drive</label>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfSrcMeeting" checked /> Calendar / Meet</label>
          </div>
          <div>
            <div class="text-xs text-secondary" style="margin-bottom:4px;">Scope</div>
            <label style="display:block; font-size:11px; cursor:pointer; margin-bottom:4px;"><input type="checkbox" id="bfScopeUser" checked /> My data</label>
            <label style="display:block; font-size:11px; cursor:pointer; margin-bottom:4px;"><input type="checkbox" id="bfScopePeers" checked /> Peer data</label>
            <label style="display:block; font-size:11px; cursor:pointer;"><input type="checkbox" id="bfScopeEmails" checked /> Executive emails</label>
          </div>
          <div>
            <div class="text-xs text-secondary" style="margin-bottom:4px;">Date Range</div>
            <select id="bfDateRange" style="font-size:11px; padding:2px 4px; background:var(--vscode-input-background); color:var(--vscode-input-foreground); border:1px solid var(--vscode-input-border); border-radius:3px;">
              <option value="full">Full Quarter</option>
              <option value="7">Last 7 days</option>
              <option value="14">Last 14 days</option>
              <option value="30">Last 30 days</option>
            </select>
          </div>
        </div>
        <div style="margin-top:10px; display:flex; gap:8px;">
          <button class="btn btn-sm btn-primary" data-action="startFilteredBackfill">Start Backfill</button>
          <button class="btn btn-sm btn-secondary" data-action="rescorePeers">Re-score Only</button>
          <button class="btn btn-sm btn-danger" data-action="scrubData" title="Delete all collected data for this quarter">Scrub All Data</button>
          <button class="btn btn-sm" data-action="cancelBackfillOptions" style="opacity:0.7;">Close</button>
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
        ${tab === "peers" ? this.renderPeersTab() : ""}
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

    const enrichmentOn = this.state.session_enrichment;
    const displayOverall = enrichmentOn ? this.state.overall_percentage : (this.state.no_enrichment_overall || this.state.overall_percentage);
    const enrichToggle = `<label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;color:var(--vscode-descriptionForeground);margin-top:2px;" title="Session enrichment adds keywords from daily session logs to boost competency matches. Toggle off to see raw signal-only scores."><input type="checkbox" ${enrichmentOn ? "checked" : ""} onchange="vscode.postMessage({type:'toggleSessionEnrichment'})" style="cursor:pointer;" />Enriched</label>`;
    const quickStatsHtml = `
      <div class="grid-4 mb-16">
        <div class="card stat-card">
          <div class="stat-value">${displayOverall}%</div>
          <div class="text-meta stat-label">Overall Score ${enrichToggle}</div>
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
        ? Math.round(catComps.reduce((s, [id]) => s + this.getEffectivePercentage(id), 0) / catComps.length)
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
    const donutContainerHtml = align && align.priorities.length > 0
      ? `<span class="qc-donut-inline"><svg id="qcCoverageDonut" class="qc-donut-svg" width="80" height="80"></svg></span>`
      : "";

    let strategyHtml = "";
    if (align && align.priorities.length > 0) {
      strategyHtml += `<div class="section"><div class="section-title">Executive Strategy Alignment ${donutContainerHtml}</div>`;
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

      // Sender summary cards (passive ownership via emails, Jira reporter, GDrive)
      const senderSummaries = align.sender_relationships?.sender_summaries || {};
      const senderEmails = Object.keys(senderSummaries);
      const jiraActivitySummary = align.jira_activity_summary || {};
      const dataSources = align.sender_relationships?.data_sources || {};
      if (senderEmails.length > 0) {
        const srcParts: string[] = [];
        if (dataSources.emails) { srcParts.push(`${dataSources.emails} emails`); }
        if (dataSources.jira_activity) { srcParts.push(`${dataSources.jira_activity} Jira reported`); }
        if (dataSources.gdrive) { srcParts.push(`${dataSources.gdrive} GDrive docs`); }
        if (dataSources.meetings) { srcParts.push(`${dataSources.meetings} meetings`); }
        if (srcParts.length > 0) {
          strategyHtml += `<div class="data-sources-indicator">Passive signals: ${srcParts.join(" &bull; ")}</div>`;
        }

        strategyHtml += `<div class="ownership-summary-row">`;
        for (const email of senderEmails) {
          const summary = senderSummaries[email];
          const anstratCount = summary.anstrat_count || 0;
          const topThemes = (summary.top_themes || []).slice(0, 4).map((t: string) => this.escapeHtml(t)).join(", ");
          const jiraAct = jiraActivitySummary[email];
          const jiraIssueCount = summary.jira_issues || jiraAct?.issue_count || 0;
          const gdriveDocCount = summary.gdrive_docs || 0;
          const jiraProjects = jiraAct?.projects || [];
          const displayName = email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, c => c.toUpperCase());

          strategyHtml += `
            <div class="ownership-card">
              <div class="ownership-card-name">${this.escapeHtml(displayName)}</div>
              <div class="ownership-card-stats">
                <span title="ANSTRAT issues linked via passive signals">${anstratCount} ANSTRATs</span>
                ${summary.total_emails ? `<span title="Executive emails parsed">${summary.total_emails} emails</span>` : ""}
                ${jiraIssueCount > 0 ? `<span title="Jira issues reported (last 90d)" class="source-jira">${jiraIssueCount} reported</span>` : ""}
                ${gdriveDocCount > 0 ? `<span title="Related Google Drive docs" class="source-gdrive">${gdriveDocCount} docs</span>` : ""}
              </div>
              ${jiraProjects.length > 0 ? `<div class="ownership-card-projects">${jiraProjects.join(", ")}</div>` : ""}
              ${topThemes ? `<div class="ownership-card-themes">${topThemes}</div>` : ""}
            </div>
          `;
        }
        strategyHtml += `</div>`;
      }

      // Group priorities by owner
      const ownerGrouped = new Map<string, StrategyAlignmentPriority[]>();
      const unownedPrios: StrategyAlignmentPriority[] = [];
      for (const prio of align.priorities) {
        const senders = (prio as any).sender_names || prio.owner_names || [];
        if (senders.length > 0) {
          for (const senderName of senders) {
            if (!ownerGrouped.has(senderName)) ownerGrouped.set(senderName, []);
            ownerGrouped.get(senderName)!.push(prio);
          }
        } else {
          unownedPrios.push(prio);
        }
      }

      const renderPrioCard = (prio: StrategyAlignmentPriority) => {
        const statusClass = prio.status === "covered" ? "overview-prio-covered" : "overview-prio-gap";
        const statusIcon = prio.status === "covered" ? "\u2705" : "\u26A0\uFE0F";
        const pillarColor = PILLAR_DEFS[prio.pillar]?.color || "#888";
        const issueLinks = prio.matched_user_issues.map(k => this.renderIssueLink(k)).join(" ");
        const mrLinks = (prio.matched_mrs || []).map(m => `<span class="overview-mr-badge">${this.escapeHtml(m)}</span>`).join(" ");
        const allMatches = [issueLinks, mrLinks].filter(Boolean).join(" ");
        const ownerBadges = ((prio as any).sender_names || prio.owner_names || []).map((n: string) =>
          `<span class="ownership-badge">${this.escapeHtml(n)}</span>`
        ).join(" ");

        return `
          <div class="overview-priority ${statusClass}">
            <div class="flex-row overview-priority-header">
              <span class="overview-priority-status">${statusIcon}</span>
              <span class="overview-priority-name">${this.escapeHtml(prio.name)}</span>
              <span class="overview-priority-pillar" style="background: ${pillarColor}22; color: ${pillarColor}; border: 1px solid ${pillarColor}44;">${this.escapeHtml(prio.pillar)}</span>
              ${ownerBadges}
            </div>
            ${prio.context ? `<div class="overview-priority-context">${this.escapeHtml(prio.context.substring(0, 150))}</div>` : ""}
            ${allMatches ? `<div class="overview-priority-matches">${allMatches}</div>` : `<div class="overview-priority-gap-msg">No matching deliverables</div>`}
          </div>
        `;
      };

      // Render grouped by owner if we have ownership data, otherwise flat list
      if (ownerGrouped.size > 0) {
        for (const [ownerName, prios] of ownerGrouped.entries()) {
          const coveredCount = prios.filter(p => p.status === "covered").length;
          strategyHtml += `<div class="section owner-group-section">`;
          strategyHtml += `<div class="section-title owner-group-title">`;
          strategyHtml += `<span class="owner-group-icon">\u{1F464}</span> ${this.escapeHtml(ownerName)}`;
          strategyHtml += `<span class="owner-group-stats">${coveredCount}/${prios.length} covered</span>`;
          strategyHtml += `</div>`;
          strategyHtml += `<div class="flex-col gap-6 overview-priorities">`;
          for (const prio of prios) {
            strategyHtml += renderPrioCard(prio);
          }
          strategyHtml += `</div></div>`;
        }
        if (unownedPrios.length > 0) {
          strategyHtml += `<div class="section owner-group-section">`;
          strategyHtml += `<div class="section-title owner-group-title">Unassigned Priorities</div>`;
          strategyHtml += `<div class="flex-col gap-6 overview-priorities">`;
          for (const prio of unownedPrios) {
            strategyHtml += renderPrioCard(prio);
          }
          strategyHtml += `</div></div>`;
        }
      } else {
        strategyHtml += `<div class="flex-col gap-6 overview-priorities">`;
        for (const prio of align.priorities) {
          strategyHtml += renderPrioCard(prio);
        }
        strategyHtml += `</div></div>`;
      }

      // Gaps alert
      const gapPrios = align.priorities.filter(p => p.status === "gap");
      if (gapPrios.length > 0) {
        strategyHtml += `<div class="section"><div class="section-title">Strategy Gaps (${gapPrios.length})</div>`;
        strategyHtml += `<div class="grid-auto">`;
        for (const g of gapPrios) {
          const gapOwners = ((g as any).sender_names || g.owner_names || []).map((n: string) => this.escapeHtml(n)).join(", ");
          strategyHtml += `
            <div class="card">
              <div class="card-title">${this.escapeHtml(g.name)}</div>
              <div class="text-secondary text-sm">${this.escapeHtml(g.pillar)}</div>
              ${gapOwners ? `<div class="text-secondary text-sm mt-4">Owner: ${gapOwners}</div>` : ""}
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

    // AI Digest
    let digestHtml = "";
    const digest = this.state.ai_overview_digest;
    if (digest) {
      const src = digest.source === "ai" ? "AI" : "Analysis";
      let trendBadge = "";
      if (digest.trend?.projected_final != null) {
        const trendClass = digest.trend.status === "on_track" ? "positive" : digest.trend.status === "at_risk" ? "neutral" : "negative";
        const trendLabel = digest.trend.status === "on_track" ? "On Track" : digest.trend.status === "at_risk" ? "At Risk" : "Behind";
        trendBadge = `<span class="ai-trend-badge ${trendClass}">${trendLabel} &mdash; projected ${digest.trend.projected_final}%</span>`;
      }
      digestHtml = `
        <div class="section">
          <div class="section-title">Weekly Digest <span class="ai-badge">${this.escapeHtml(src)}</span> ${trendBadge}</div>
          <div class="ai-insight-card">${this.escapeHtml(digest.digest)}</div>
        </div>`;
    }

    // Build pillar averages for charts
    const pillarAvgs: Record<string, number> = {};
    for (const [pname] of Object.entries(PILLAR_DEFS)) {
      const catComps = Object.entries(this.state.competencies).filter(([id]) =>
        this.state.competency_meta[id]?.category === pname
      );
      pillarAvgs[pname] = catComps.length > 0
        ? Math.round(catComps.reduce((s, [id]) => s + this.getEffectivePercentage(id), 0) / catComps.length)
        : 0;
    }

    // Chart data for D3 overview visualizations
    const chartData = {
      captured_days: this.state.captured_days.slice().sort((a, b) => a.date.localeCompare(b.date)),
      day_of_quarter: this.state.day_of_quarter,
      overall_percentage: this.getEffectiveOverall(),
      total_weekdays: this.state.coverage.total_weekdays,
      captured: this.state.coverage.captured,
      trend: digest?.trend || null,
      pillar_summary: align?.pillar_summary || {},
      pillar_avgs: pillarAvgs,
      pillar_colors: Object.fromEntries(Object.entries(PILLAR_DEFS).map(([k, v]) => [k, v.color])),
      coverage_summary: align?.coverage_summary || { total_priorities: 0, covered: 0, gaps: 0, coverage_pct: 0 },
    };
    const chartDataJson = JSON.stringify(chartData);

    return `
      <div class="perf-tab-panel">
        ${quickStatsHtml}
        <div class="qc-charts-row">
          <div class="qc-trend-container">
            <div class="qc-chart-header">
              <span class="qc-chart-title">Quarter Score Trend</span>
              <div class="qc-chart-legend">
                <span class="qc-chart-legend-item"><span class="qc-chart-legend-swatch" style="background:#10b981;"></span>Actual</span>
                <span class="qc-chart-legend-item"><span class="qc-chart-legend-swatch" style="background:#10b981;opacity:0.4;border-top:2px dashed #10b981;height:0;"></span>Projected</span>
              </div>
            </div>
            <svg id="qcTrendChart" class="qc-trend-svg"></svg>
          </div>
        </div>
        <div class="qc-heatmap-container">
          <div class="qc-chart-header">
            <span class="qc-chart-title">Daily Activity</span>
            <div class="qc-heatmap-legend">
              <span>Less</span>
              <span class="qc-heatmap-legend-cell" style="background:rgba(16,185,129,0.1);"></span>
              <span class="qc-heatmap-legend-cell" style="background:rgba(16,185,129,0.3);"></span>
              <span class="qc-heatmap-legend-cell" style="background:rgba(16,185,129,0.6);"></span>
              <span class="qc-heatmap-legend-cell" style="background:#10b981;"></span>
              <span>More</span>
            </div>
          </div>
          <div id="qcHeatmapStrip" class="qc-heatmap-strip"></div>
        </div>
        ${digestHtml}
        <div class="qc-pillar-chart-container">
          <div class="qc-chart-title">Pillar Comparison</div>
          <svg id="qcPillarChart" class="qc-pillar-svg"></svg>
        </div>
        ${pillarHtml}
        ${strategyHtml}
        <div id="qcTooltip" class="qc-tooltip"></div>
        <script id="qcOverviewChartData" type="application/json">${chartDataJson}</script>
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
          ${this.renderMonthlyTrend()}
          <div class="cal-charts-row">
            ${this.renderCalendar()}
            ${this.renderMonthlyDonut()}
          </div>
          ${this.renderDayOfWeekHeatmap()}
        </div>

        <!-- Day Detail (shown when a day is clicked) -->
        ${this.renderDayDetail()}

        <!-- AI Calendar Insights -->
        ${this._renderCalendarInsights()}
      </div>
    `;
  }

  private _renderCalendarInsights(): string {
    const insights = this.state.ai_calendar_insights;
    if (!insights) return "";

    let html = "";
    if (insights.patterns.length > 0 || insights.forecast) {
      html += `<div class="section"><div class="section-title">AI Insights</div>`;
      if (insights.forecast) {
        const fc = insights.forecast;
        const fcClass = fc.projected_pct >= 80 ? "positive" : fc.projected_pct >= 60 ? "neutral" : "negative";
        html += `<div class="ai-forecast"><span class="ai-trend-badge ${fcClass}">Coverage forecast: ${fc.projected_pct}%</span> <span class="text-secondary text-sm">${fc.remaining_weekdays} weekdays remaining</span></div>`;
      }
      for (const p of insights.patterns) {
        const cls = p.severity === "positive" ? "positive" : p.severity === "warning" ? "negative" : "neutral";
        html += `<div class="ai-pattern-item ${cls}">${this.escapeHtml(p.message)}</div>`;
      }
      html += `</div>`;
    }
    return html;
  }

  private renderIssuesDashboard(): string {
    const h = this.state.issue_hierarchy;
    if (!h || !h.summary) return "";
    const s = h.summary;

    const dataJson = JSON.stringify({
      strategies: (h.strategies || []).map((st: IssueNode) => ({
        key: st.key, summary: st.summary, points: st.points,
        children: (st.children || []).map((ep: IssueNode) => ({
          key: ep.key, summary: ep.summary, points: ep.points,
          children: (ep.children || []).map((is: IssueNode) => ({
            key: is.key, summary: is.summary, points: is.points,
          })),
        })),
      })),
      scope_points: s.scope_points,
      alignment_pct: s.alignment_pct,
      aligned_points: s.aligned_points,
      unaligned_points: s.unaligned_points,
      tag_counts: s.tag_counts,
      pillar_points: s.pillar_points,
      total_points: s.total_points,
    });

    // Server-rendered fallback for Strategy Points (replaced by D3 treemap when available)
    const strategies = h.strategies || [];
    const maxStratPts = Math.max(...strategies.map((st: IssueNode) => st.points || 0), 1);
    const stratFallback = strategies.length > 0
      ? strategies.map((st: IssueNode) => {
          const pct = Math.max(Math.round(((st.points || 0) / maxStratPts) * 100), 4);
          return `<div class="issues-dash-strat-row">
            <span class="issues-dash-strat-key">${this.escapeHtml(st.key.replace("ANSTRAT-", "S-"))}</span>
            <span class="issues-dash-strat-bar" style="width:${pct}%"></span>
            <span class="issues-dash-strat-pts">${st.points || 0}</span>
          </div>`;
        }).join("")
      : `<div class="text-muted-sm">No strategy data</div>`;

    // Server-rendered fallback for Points by Scope
    const scopeColors: Record<string, string> = { commit: "#3b82f6", story: "#10b981", epic: "#f59e0b", anstrat: "#ef4444", meeting: "#8b5cf6", doc: "#06b6d4" };
    const scopeEntries = Object.entries(s.scope_points || {}).filter(([, v]) => (v as number) > 0);
    const scopeTotal = scopeEntries.reduce((sum, [, v]) => sum + (v as number), 0);
    const scopeFallback = scopeTotal > 0
      ? `<div class="issues-dash-scope-total">${scopeTotal}</div>
         <div class="issues-dash-scope-legend">${scopeEntries.map(([k, v]) =>
           `<span class="issues-dash-scope-item"><span class="issues-dash-scope-dot" style="background:${scopeColors[k] || "#6b7280"}"></span>${k}: ${v}</span>`
         ).join("")}</div>`
      : `<div class="text-muted-sm">No scope data</div>`;

    // Server-rendered gauge for Strategy Alignment
    const pct = s.alignment_pct || 0;
    const aligned = s.aligned_points || 0;
    const unaligned = s.unaligned_points || 0;
    const barColor = pct >= 70 ? "var(--success)" : pct >= 40 ? "var(--warning)" : "var(--error)";
    const gaugeFallback = `
      <div class="issues-gauge-pct">${pct}%</div>
      <div class="issues-gauge-label">of points are strategy-aligned</div>
      <div class="issues-gauge-bar"><div class="issues-gauge-fill" style="width:${pct}%;background:${barColor};"></div></div>
      <div class="issues-gauge-legend">
        <span><span class="issues-gauge-dot" style="background:${barColor}"></span>Aligned: ${aligned}pts</span>
        <span><span class="issues-gauge-dot" style="background:var(--bg-tertiary)"></span>Other: ${unaligned}pts</span>
      </div>`;

    // Server-rendered tag bars
    const tagEntries = Object.entries(s.tag_counts || {});
    const maxTagCount = tagEntries.reduce((m, [, v]) => Math.max(m, v as number), 0) || 1;
    const tagFallback = tagEntries.length > 0
      ? tagEntries.slice(0, 10).map(([tag, count]) => {
          const tagPct = Math.max(Math.round(((count as number) / maxTagCount) * 100), 4);
          const cat = this.getTagCategory(tag);
          const catColors: Record<string, string> = {
            worktype: "#3b82f6", quality: "#10b981", domain: "#8b5cf6",
            ops: "#f97316", monitoring: "#ef4444", other: "#6b7280",
          };
          return `<div class="issues-tag-bar-row">
            <span class="issues-tag-bar-label">${this.escapeHtml(tag)}</span>
            <span class="issues-tag-bar-fill" style="width:${tagPct}%;background:${catColors[cat] || "#6b7280"};"></span>
            <span class="issues-tag-bar-count">${count}</span>
          </div>`;
        }).join("")
      : `<div class="text-muted-sm">No tag data</div>`;

    return `
      <div class="issues-dashboard">
        <div class="issues-dashboard-row">
          <div class="issues-dash-card">
            <div class="issues-dash-title">Strategy Points</div>
            <div id="issuesDashTreemap" class="issues-dash-chart">${stratFallback}</div>
          </div>
          <div class="issues-dash-card">
            <div class="issues-dash-title">Points by Scope</div>
            <div id="issuesDashDonut" class="issues-dash-chart issues-dash-scope-fallback">${scopeFallback}</div>
          </div>
          <div class="issues-dash-card">
            <div class="issues-dash-title">Strategy Alignment</div>
            <div id="issuesDashGauge" class="issues-dash-chart issues-dash-gauge">${gaugeFallback}</div>
          </div>
          <div class="issues-dash-card issues-dash-card-wide">
            <div class="issues-dash-title">Tag Distribution</div>
            <div id="issuesDashTags" class="issues-dash-chart">${tagFallback}</div>
          </div>
        </div>
      </div>
      <script type="application/json" id="issuesDashboardData">${dataJson}</script>
    `;
  }

  private renderTagFilterBar(): string {
    const h = this.state.issue_hierarchy;
    if (!h || !h.summary || !h.summary.tag_counts) return "";
    const tags = Object.keys(h.summary.tag_counts);
    if (tags.length === 0) return "";
    return `
      <div class="issues-tag-filter-bar">
        <span class="issues-tag-filter-label">Filter:</span>
        ${tags.map((t) => {
          const cat = this.getTagCategory(t);
          return `<button class="issues-tag-filter-btn perf-tag-${cat}" data-action="filterTag" data-tag="${this.escapeHtml(t)}">${this.escapeHtml(t)}</button>`;
        }).join("")}
        <button class="issues-tag-filter-btn issues-tag-clear" data-action="filterTag" data-tag="">all</button>
      </div>`;
  }

  private renderIssuesTab(): string {
    return `
      <div class="perf-tab-panel">
        ${this.renderIssuesDashboard()}
        <div class="section">
          <div class="section-title">
            <span>Delivered Issues</span>
            <div class="d-flex gap-8">
              <button class="btn btn-xs" data-action="detectMissingLinks">Detect Missing Links</button>
              <button class="btn btn-xs" data-action="refreshHierarchy">Refresh from Jira</button>
            </div>
          </div>
          ${this.renderTagFilterBar()}
          <div class="issue-cards-grid">
            ${this.renderIssueHierarchy()}
          </div>
        </div>
        <div id="missingLinksContainer"></div>
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
    const view = this.state.competency_view || "sunburst";
    const toggleHtml = `
      <div class="perf-chart-view-toggle">
        <button class="perf-chart-view-btn${view === "sunburst" ? " active" : ""}"
                data-action="switchCompView" data-view="sunburst">Sunburst</button>
        <button class="perf-chart-view-btn${view === "mindmap" ? " active" : ""}"
                data-action="switchCompView" data-view="mindmap">Mindmap</button>
      </div>`;

    const chartHtml = view === "sunburst"
      ? this.renderSunburstView()
      : this.renderWeightedMindmapView();

    return `
      <div class="perf-tab-panel">
        ${toggleHtml}
        ${chartHtml}

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

  private renderSunburstView(): string {
    return `
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
    `;
  }

  // ============================================================
  // Weighted Competency Mindmap
  // ============================================================

  private buildWeightedCompetencyGraph(): { nodes: any[]; links: any[]; pillarInfo: any[]; stats: any } | null {
    const meta = this.state.competency_meta || {};
    const comps = this.state.competencies || {};
    const evidence = this.state.competency_evidence || {};
    const h = this.state.issue_hierarchy;
    const cfg = this.state.scoring_config;
    const hasCompetencies = Object.keys(meta).length > 0;
    const hasIssues = h && h.total_issues > 0;

    if (!hasCompetencies && !hasIssues) return null;

    const scopeMult: Record<string, number> = (cfg as any)?.scope_multipliers || { commit: 1, story: 2, epic: 4, anstrat: 7, strategy: 10 };
    const levelWeights = (cfg as any)?.level_weights || {};
    const pillarWeightsMap: Record<string, number> = levelWeights.pillar_weights || {};
    const roleWeightsMap: Record<string, Record<string, number>> = levelWeights.role_weights || {};
    const targetPerComp = cfg?.target_per_competency || 100;
    const targetScale = levelWeights.target_scale ?? 1.0;
    const effectiveTarget = Math.round(targetPerComp * targetScale);

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

    // Per-competency issue key sets for cross-linking
    const compEvidenceKeys: Record<string, Set<string>> = {};
    const compEvidencePoints: Record<string, Record<string, number>> = {};
    for (const [compId, events] of Object.entries(evidence)) {
      const keys = new Set<string>();
      const keyPoints: Record<string, number> = {};
      for (const ev of events) {
        for (const k of (ev.issue_keys || [])) {
          keys.add(k);
          keyPoints[k] = (keyPoints[k] || 0) + ev.points;
        }
      }
      compEvidenceKeys[compId] = keys;
      compEvidencePoints[compId] = keyPoints;
    }

    // Root node
    const rootId = "wm_root";
    const overallPct = this.getEffectiveOverall() || 0;
    nodes.push({
      id: rootId,
      label: this.state.quarter,
      sublabel: `${overallPct}%`,
      type: "root",
      percentage: overallPct,
      size: 32,
      color: "#667eea",
      pillars: allPillarIds,
      weightInfo: `Overall: ${overallPct}%`,
    });

    let compCount = 0, anstratCount = 0, epicCount = 0, issueCount = 0, stratCount = 0, evidenceLinkCount = 0;

    // Pillar + Competency nodes (Data Set 1)
    for (const [pillarName, pDef] of Object.entries(pillarDefs)) {
      const pillarId = `wm_pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;
      const pillarComps = pDef.compIds;
      const avgPct = pillarComps.length > 0
        ? Math.round(pillarComps.reduce((s, id) => s + (comps[id]?.percentage || 0), 0) / pillarComps.length)
        : 0;
      const totalPts = pillarComps.reduce((s, id) => s + (comps[id]?.points || 0), 0);
      const pw = pillarWeightsMap[pillarName] ?? 1.0;

      nodes.push({
        id: pillarId,
        label: pDef.label,
        sublabel: `${avgPct}% \u00B7 w=${pw}`,
        type: "pillar",
        percentage: avgPct,
        size: 24,
        color: pDef.color,
        heatColor: this.getHeatColor(avgPct),
        angle: pDef.angle,
        compCount: pillarComps.length,
        pillars: [pillarId],
        weightInfo: `Avg: ${avgPct}% | ${totalPts}pts | pillar_w: ${pw}`,
      });
      links.push({ source: rootId, target: pillarId, type: "hierarchy", label: `w=${pw}` });

      for (const compId of pillarComps) {
        compCount++;
        const m = meta[compId];
        const c = comps[compId];
        const pct = c?.percentage || m?.percentage || 0;
        const pts = c?.points || m?.points || 0;
        const target = m?.target || effectiveTarget;
        const evCount = m?.evidence_count || 0;
        const basePoints = cfg?.competencies?.[compId]?.base_points || 0;

        const nodeId = `wm_comp_${compId}`;
        const compTint = pillarTint(pDef.color, "competency", pct);
        nodes.push({
          id: nodeId,
          compId,
          label: m.name,
          sublabel: `${pts}/${target} (${pct}%)`,
          type: "competency",
          category: m.category,
          percentage: pct,
          points: pts,
          target,
          evidenceCount: evCount,
          size: Math.min(Math.max(evCount * 1.5 + 8, 8), 20),
          color: compTint,
          heatColor: compTint,
          pillarColor: pDef.color,
          pillarId,
          pillarAngle: pDef.angle,
          pillars: [pillarId],
          weightInfo: `${pts}/${target} = ${pct}% | base: ${basePoints} | ${evCount} events`,
        });
        links.push({ source: pillarId, target: nodeId, type: "hierarchy" });
      }
    }

    // Work hierarchy nodes (Data Set 2)
    if (hasIssues && h) {
      const issueStrategies = Array.isArray(h.strategies) ? h.strategies : [];
      const unattachedEpics = Array.isArray(h.unattached_epics) ? h.unattached_epics : [];
      const uncatIssues = Array.isArray(h.uncategorized) ? h.uncategorized : [];

      const pillarIdToHex: Record<string, string> = {};
      for (const [pn, pd] of Object.entries(pillarDefs)) {
        pillarIdToHex[`wm_pillar_${pn.replace(/[^a-z]/gi, "_")}`] = pd.color;
      }

      const anstratIssueKeys: Record<string, Set<string>> = {};
      const anstratNodeIds: string[] = [];

      const anstratScopeMult = scopeMult.anstrat ?? 7;
      const epicScopeMult = scopeMult.epic ?? 4;
      const storyScopeMult = scopeMult.story ?? 2;

      // ANSTRAT groups
      issueStrategies.forEach((group, gi) => {
        anstratCount++;
        const gId = `wm_anstrat_${gi}`;
        anstratNodeIds.push(gId);
        const allKeys = new Set<string>();

        nodes.push({
          id: gId,
          label: group.key.replace(/^ANSTRAT-/, "AN-"),
          fullKey: group.key,
          summary: group.summary,
          sublabel: `${group.points}pts \u00D7${anstratScopeMult}`,
          type: "anstrat",
          points: group.points,
          size: Math.min(Math.max(group.points / 8, 16), 24),
          color: "#06b6d4",
          eventCount: group.event_count || 0,
          pillars: [] as string[],
          weightInfo: `${group.points}pts | scope: \u00D7${anstratScopeMult} | ${group.event_count || 0} events`,
        });

        (group.children || []).forEach((child, ci) => {
          epicCount++;
          const cId = `${gId}_epic_${ci}`;
          nodes.push({
            id: cId,
            label: child.key.replace(/^AAP-/, ""),
            fullKey: child.key,
            summary: child.summary,
            sublabel: `${child.points}pts \u00D7${epicScopeMult}`,
            type: "epic",
            points: child.points,
            size: Math.min(Math.max(child.points / 8, 10), 18),
            color: "#f97316",
            eventCount: child.event_count || 0,
            parentAnstrat: gId,
            pillars: [] as string[],
            weightInfo: `${child.points}pts | scope: \u00D7${epicScopeMult} | ${child.event_count || 0} events`,
          });
          links.push({ source: gId, target: cId, type: "parent", label: `\u00D7${epicScopeMult}` });
          allKeys.add(child.key);

          (child.children || []).forEach((issue, ii) => {
            issueCount++;
            const iId = `${cId}_issue_${ii}`;
            nodes.push({
              id: iId,
              label: issue.key.replace(/^AAP-/, ""),
              fullKey: issue.key,
              summary: issue.summary,
              sublabel: `${issue.points}pts \u00D7${storyScopeMult}`,
              type: issue.type || "task",
              points: issue.points,
              size: Math.min(Math.max(issue.points / 10, 6), 12),
              color: "#e879f9",
              eventCount: issue.event_count || 0,
              parentAnstrat: gId,
              pillars: [] as string[],
              weightInfo: `${issue.points}pts | scope: \u00D7${storyScopeMult} | ${issue.event_count || 0} events`,
            });
            links.push({ source: cId, target: iId, type: "parent", label: `\u00D7${storyScopeMult}` });
            allKeys.add(issue.key);
          });
        });

        anstratIssueKeys[gId] = allKeys;
      });

      // Pillar assignment for ANSTRATs via evidence overlap
      const findPillarForKey = (key: string): string | null => {
        for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
          if (compKeys.has(key)) {
            const cat = meta[compId]?.category || "Technical Contribution";
            return `wm_pillar_${cat.replace(/[^a-z]/gi, "_")}`;
          }
        }
        return null;
      };

      const nodeMap = new Map(nodes.map(n => [n.id, n]));
      for (const [gId, issueKeys] of Object.entries(anstratIssueKeys)) {
        const linkedCompIds: string[] = [];

        for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
          let shared = 0;
          let sharedPts = 0;
          for (const k of compKeys) {
            if (issueKeys.has(k)) {
              shared++;
              sharedPts += compEvidencePoints[compId]?.[k] || 0;
            }
          }
          if (shared > 0) {
            linkedCompIds.push(compId);
            evidenceLinkCount++;
            links.push({
              source: `wm_comp_${compId}`,
              target: gId,
              type: "evidence",
              weight: shared,
              points: sharedPts,
              label: `${sharedPts}pts`,
            });
          }
        }

        const anstratNode = nodeMap.get(gId);
        if (linkedCompIds.length > 0 && anstratNode) {
          const assocPillars = new Set<string>();
          for (const cid of linkedCompIds) {
            const cat = meta[cid]?.category || "Technical Contribution";
            assocPillars.add(`wm_pillar_${cat.replace(/[^a-z]/gi, "_")}`);
          }
          anstratNode.pillars = Array.from(assocPillars);
        } else {
          if (anstratNode) anstratNode.pillars = allPillarIds.slice();
          links.push({ source: rootId, target: gId, type: "parent" });
        }

        const anstratPillars = anstratNode?.pillars || allPillarIds;
        for (const n of nodes) {
          if (n.parentAnstrat === gId) n.pillars = anstratPillars;
        }
      }

      // Unattached epics
      unattachedEpics.forEach((epic, ei) => {
        epicCount++;
        const eId = `wm_unattached_epic_${ei}`;
        const pillar = findPillarForKey(epic.key);
        const target = pillar || rootId;
        nodes.push({
          id: eId,
          label: epic.key.replace(/^AAP-/, ""),
          fullKey: epic.key,
          summary: epic.summary,
          sublabel: `${epic.points}pts \u00D7${epicScopeMult}`,
          type: "epic",
          points: epic.points,
          size: Math.min(Math.max(epic.points / 8, 10), 18),
          color: "#f97316",
          eventCount: epic.event_count || 0,
          pillars: pillar ? [pillar] : allPillarIds.slice(),
          weightInfo: `${epic.points}pts | scope: \u00D7${epicScopeMult}`,
        });
        links.push({ source: target, target: eId, type: "hierarchy" });

        (epic.children || []).forEach((issue, ii) => {
          issueCount++;
          const iId = `${eId}_issue_${ii}`;
          const issuePillar = findPillarForKey(issue.key) || pillar;
          const issuePillarHex = issuePillar ? (pillarIdToHex[issuePillar] || "#e879f9") : "#e879f9";
          nodes.push({
            id: iId,
            label: issue.key.replace(/^AAP-/, ""),
            fullKey: issue.key,
            summary: issue.summary,
            sublabel: `${issue.points}pts \u00D7${storyScopeMult}`,
            type: issue.type || "task",
            points: issue.points,
            size: Math.min(Math.max(issue.points / 10, 6), 12),
            color: issuePillar ? pillarTint(issuePillarHex, "issue") : "#e879f9",
            eventCount: issue.event_count || 0,
            pillars: issuePillar ? [issuePillar] : allPillarIds.slice(),
            weightInfo: `${issue.points}pts | scope: \u00D7${storyScopeMult}`,
          });
          links.push({ source: eId, target: iId, type: "parent" });
        });
      });

      // Uncategorized issues
      uncatIssues.forEach((issue, ui) => {
        issueCount++;
        const uId = `wm_uncat_${ui}`;
        const pillar = findPillarForKey(issue.key);
        const target = pillar || rootId;
        const uncatHex = pillar ? (pillarIdToHex[pillar] || "#e879f9") : "#e879f9";

        nodes.push({
          id: uId,
          label: issue.key.replace(/^AAP-/, ""),
          fullKey: issue.key,
          summary: issue.summary,
          sublabel: `${issue.points}pts \u00D7${storyScopeMult}`,
          type: issue.type || "task",
          points: issue.points,
          size: Math.min(Math.max(issue.points / 10, 6), 12),
          color: pillar ? pillarTint(uncatHex, "issue") : "#e879f9",
          eventCount: issue.event_count || 0,
          pillars: pillar ? [pillar] : allPillarIds.slice(),
          weightInfo: `${issue.points}pts | scope: \u00D7${storyScopeMult}`,
        });
        links.push({ source: target, target: uId, type: "hierarchy" });
      });

      // Recolor issue nodes with pillar associations (ANSTRATs/Epics keep fixed colors per legend)
      for (const n of nodes) {
        if (n.pillars && n.pillars.length > 0 && n.pillars.length < allPillarIds.length) {
          const primaryHex = pillarIdToHex[n.pillars[0]] || "#888";
          if (n.type === "task" || n.type === "bug" || n.type === "story") n.color = pillarTint(primaryHex, "issue");
        }
      }
    }

    // Strategy diamonds
    const alignment = this.state.strategy_alignment;
    if (alignment?.priorities) {
      const strategyScopeMult = scopeMult.strategy ?? 10;
      for (const [pi, priority] of alignment.priorities.entries()) {
        stratCount++;
        const stratId = `wm_strat_${pi}`;
        const isCovered = priority.status === "covered";
        const pillarName = priority.pillar || "End-to-End Delivery";
        const pillarId = `wm_pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;
        const stratPillars = new Set<string>([pillarId]);
        const priorityKeys = new Set(priority.issue_keys || []);

        let totalEvidencePts = 0;
        for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
          let shared = 0;
          let sharedPts = 0;
          for (const k of compKeys) {
            if (priorityKeys.has(k)) {
              shared++;
              sharedPts += compEvidencePoints[compId]?.[k] || 0;
            }
          }
          if (shared > 0) {
            evidenceLinkCount++;
            totalEvidencePts += sharedPts;
            links.push({
              source: `wm_comp_${compId}`,
              target: stratId,
              type: "evidence",
              weight: shared,
              points: sharedPts,
              label: `${sharedPts}pts`,
            });
            const compCat = meta[compId]?.category || "Technical Contribution";
            stratPillars.add(`wm_pillar_${compCat.replace(/[^a-z]/gi, "_")}`);
          }
        }

        const stratPillarHex = PILLAR_DEFS[pillarName]?.color || "#888";
        const stratTint = pillarTint(stratPillarHex, "strategy", undefined, isCovered);
        nodes.push({
          id: stratId,
          label: priority.name.length > 30 ? priority.name.substring(0, 27) + "..." : priority.name,
          fullLabel: priority.name,
          sublabel: isCovered ? `${totalEvidencePts}pts \u2713` : "gap",
          type: "strategy",
          status: priority.status,
          size: 14,
          color: stratTint,
          heatColor: stratTint,
          isCovered,
          pillarId,
          pillars: Array.from(stratPillars),
          weightInfo: `${isCovered ? "Covered" : "Gap"} | ${totalEvidencePts}pts | scope: \u00D7${strategyScopeMult}`,
        });
        links.push({ source: pillarId, target: stratId, type: "pillar_strategy", label: `\u00D7${strategyScopeMult}` });
      }
    }

    // ---- Sender/Owner nodes ----
    let ownerCount = 0;
    const wmSenderSummaries = alignment?.sender_relationships?.sender_summaries || {};
    const wmSenderRels = alignment?.sender_relationships?.relationships || [];
    const wmOwnerColor = "#e0e0e0";
    const wmAnstratNodeMap = new Map(nodes.filter(n => n.type === "anstrat").map(n => [n.fullKey, n.id]));

    const wmEmailToDisplay = new Map<string, string>();
    const wmDisplayToEmail = new Map<string, string>();
    for (const [email] of Object.entries(wmSenderSummaries)) {
      const dn = email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
      wmEmailToDisplay.set(email, dn);
      wmDisplayToEmail.set(dn, email);
    }

    const wmEmailToAnstratViaStrategy = new Map<string, Set<string>>();
    if (alignment?.priorities) {
      for (const priority of alignment.priorities) {
        const senderNames: string[] = (priority as any).sender_names || priority.owner_names || [];
        const prioIssueKeys = priority.issue_keys || [];
        const prioAnstratNodeIds: string[] = [];
        for (const k of prioIssueKeys) {
          const nid = wmAnstratNodeMap.get(k);
          if (nid) prioAnstratNodeIds.push(nid);
        }
        if (prioAnstratNodeIds.length === 0) continue;
        for (const sn of senderNames) {
          const email = wmDisplayToEmail.get(sn) || sn;
          if (!wmEmailToAnstratViaStrategy.has(email)) wmEmailToAnstratViaStrategy.set(email, new Set());
          for (const nid of prioAnstratNodeIds) wmEmailToAnstratViaStrategy.get(email)!.add(nid);
        }
      }
    }

    for (const [email, summary] of Object.entries(wmSenderSummaries)) {
      const senderAnstrats = wmSenderRels
        .filter(r => r.sender === email)
        .map(r => r.anstrat_key);
      const linkedAnstratIds: string[] = [];
      for (const key of senderAnstrats) {
        const nodeId = wmAnstratNodeMap.get(key);
        if (nodeId && !linkedAnstratIds.includes(nodeId)) linkedAnstratIds.push(nodeId);
      }
      const strategyLinked = wmEmailToAnstratViaStrategy.get(email);
      if (strategyLinked) {
        for (const nid of strategyLinked) {
          if (!linkedAnstratIds.includes(nid)) linkedAnstratIds.push(nid);
        }
      }

      ownerCount++;
      const ownerId = `wm_owner_${email.replace(/[^a-z0-9]/gi, "_")}`;
      const displayName = wmEmailToDisplay.get(email) || email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());

      const ownerPillars = new Set<string>();
      for (const anId of linkedAnstratIds) {
        const anNode = nodes.find(n => n.id === anId);
        if (anNode?.pillars) {
          for (const p of anNode.pillars) ownerPillars.add(p);
        }
      }

      nodes.push({
        id: ownerId,
        label: displayName,
        email,
        type: "owner",
        size: 18,
        color: wmOwnerColor,
        issueCount: (summary as SenderSummary).anstrat_count || senderAnstrats.length,
        linkedCount: linkedAnstratIds.length,
        themes: ((summary as SenderSummary).top_themes || []).slice(0, 5),
        pillars: ownerPillars.size > 0 ? Array.from(ownerPillars) : Object.keys(pillarDefs).map(n => `wm_pillar_${n.replace(/[^a-z]/gi, "_")}`),
      });

      if (linkedAnstratIds.length > 0) {
        for (const anId of linkedAnstratIds) {
          links.push({ source: ownerId, target: anId, type: "owner_anstrat", weight: 1 });
        }
      } else {
        links.push({ source: ownerId, target: rootId, type: "owner_anstrat", weight: 1 });
      }
    }

    const pillarInfo = Object.entries(pillarDefs).map(([name, def]) => ({
      id: `wm_pillar_${name.replace(/[^a-z]/gi, "_")}`,
      label: def.label,
      color: def.color,
    }));

    return {
      nodes,
      links,
      pillarInfo,
      stats: {
        pillars: Object.keys(pillarDefs).length,
        competencies: compCount,
        anstrats: anstratCount,
        owners: ownerCount,
        epics: epicCount,
        issues: issueCount,
        strategies: stratCount,
        evidenceLinks: evidenceLinkCount,
      },
    };
  }

  private renderWeightedMindmapView(): string {
    const graphData = this.buildWeightedCompetencyGraph();

    if (!graphData) {
      return this.getEmptyStateHtml("--", "Weighted mindmap will appear after data collection.");
    }

    const graphJson = JSON.stringify(graphData);
    const s = graphData.stats;

    const parts: string[] = [];
    if (s.pillars) parts.push(`${s.pillars} pillars`);
    if (s.competencies) parts.push(`${s.competencies} competencies`);
    if (s.anstrats) parts.push(`${s.anstrats} ANSTRATs`);
    if (s.owners) parts.push(`${s.owners} owners`);
    if (s.epics) parts.push(`${s.epics} epics`);
    if (s.issues) parts.push(`${s.issues} issues`);
    if (s.strategies) parts.push(`${s.strategies} strategies`);
    if (s.evidenceLinks) parts.push(`${s.evidenceLinks} cross-links`);
    const statsHtml = parts.join(" &middot; ");

    const pillarCheckboxes = graphData.pillarInfo.map((p: any) =>
      `<label class="perf-mindmap-toggle perf-pillar-filter" style="color:${p.color}">` +
      `<input type="checkbox" class="wmPillarChk" data-pillar="${this.escapeHtml(p.id)}" checked /> ${this.escapeHtml(p.label)}</label>`
    ).join("");

    return `
      <div class="section">
        <div class="section-title">Weighted Competency Mindmap</div>
        <div class="perf-wm-d3-wrapper">
          <div class="perf-mindmap-d3-header">
            <div class="perf-mindmap-d3-filters">
              ${pillarCheckboxes}
              <span class="perf-mindmap-d3-sep">|</span>
              <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="competency" checked /> Competencies</label>
              <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="anstrat" checked /> ANSTRATs</label>
              <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="epic" checked /> Epics</label>
              <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="task,bug,story" checked /> Issues</label>
              <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="strategy" checked /> Strategies</label>
              <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="owner" checked /> Owners</label>
            </div>
            <span class="perf-mindmap-d3-stats" id="wmStats">${statsHtml}</span>
            <div class="perf-mindmap-d3-controls">
              <label class="perf-mindmap-toggle"><input type="checkbox" id="wmLabels" checked /> Labels</label>
              <label class="perf-mindmap-toggle"><input type="checkbox" id="wmWeights" checked /> Weights</label>
              <label class="perf-mindmap-toggle"><input type="checkbox" id="wmSticky" /> Sticky</label>
              <button class="btn btn-xs" id="wmReheat" title="Reheat simulation">Reheat</button>
              <button class="btn btn-xs" id="wmFit" title="Fit to view">Fit</button>
            </div>
          </div>
          <div class="perf-mindmap-d3-graph" id="wmGraph">
            <svg id="wmSvg" class="svg-full">
              <defs>
                <filter id="wmGlow" x="-50%" y="-50%" width="200%" height="200%">
                  <feGaussianBlur stdDeviation="2.5" result="blur"/>
                  <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                </filter>
              </defs>
            </svg>
          </div>
          <div class="perf-mindmap-d3-tooltip" id="wmTooltip"></div>
          <div class="perf-mindmap-d3-legend">
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-root"></span>Root</span>
            ${Object.entries(PILLAR_DEFS).map(([name, def]) =>
              `<span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot" style="background:${def.color}"></span>${name}</span>`
            ).join("\n            ")}
            <span class="legend-separator">|</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-ring legend-dot-default"></span>Pillar</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-small"></span>Competency</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-roundrect legend-dot-default"></span>ANSTRAT</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-triangle legend-dot-default"></span>Epic</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-square legend-dot-default"></span>Issue</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-diamond-legend legend-dot-default"></span>Strategy</span>
            <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-hexagon" style="background:#e0e0e0"></span>Owner</span>
            <span class="legend-separator">|</span>
            <span class="flex-row gap-4 legend-item-compact wm-legend-evidence"><span class="dot legend-dot" style="border:2px dashed #f59e0b;background:transparent;"></span>Evidence Link</span>
          </div>
        </div>
      </div>
      <script id="wmGraphData" type="application/json">${graphJson}</script>
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
      "gdrive_doc_created", "gdrive_doc_contributed",
      "gdrive_sheet_created", "gdrive_sheet_contributed",
      "gdrive_slides_created", "gdrive_slides_contributed",
      "meeting_organized", "meeting_attended",
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
          <button class="btn btn-sm btn-secondary" data-action="suggestConfigTune">AI Auto-Tune Suggestions</button>
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
                <span>Events from all sources (Git, Jira, GitLab, GitHub, Gmail, Google Drive, Calendar/Meet) are auto-tagged to questions by competency category during daily collection</span>
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
            <button class="btn btn-xs btn-warning" data-action="clearDrafts">Clear Drafts</button>
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

  private renderPeersTab(): string {
    const benchmarks = this.state.peer_benchmarks;
    const orgStats = this.state.org_stats;
    const levelLabels: Record<string, string> = {
      ase: "Associate SE",
      se: "Software Engineer",
      sse: "Senior SE",
      pse: "Principal SE",
      spse: "Sr Principal SE",
      de: "Distinguished",
    };
    const levelColors: Record<string, string> = {
      ase: "#64748b",
      se: "#3b82f6",
      sse: "#06b6d4",
      pse: "#8b5cf6",
      spse: "#f59e0b",
      de: "#ef4444",
      you: "#10b981",
    };

    // Row 1: Org Overview (always visible when org_roster data available)
    let orgOverviewHtml = "";
    if (orgStats?.available) {
      orgOverviewHtml = `
        <div class="section">
          <div class="section-title">Organization Overview</div>
          <div class="peer-chart-row">
            ${this.renderOrgLevelDistribution(orgStats, levelLabels, levelColors)}
            ${this.renderOrgDonut(orgStats, levelColors)}
            ${this.renderPeerSampleCoverage(orgStats, levelColors)}
          </div>
        </div>`;
    }

    if (!benchmarks || !benchmarks.levels || Object.keys(benchmarks.levels).length === 0) {
      return `
        <div class="perf-tab-panel">
          ${orgOverviewHtml}
          <div class="section">
            <div class="section-title">Peer Comparison</div>
            <div class="empty-state-text">No peer data collected yet.</div>
            <p class="text-secondary text-sm mt-8">Use the <strong>Collect Today</strong> or <strong>Backfill</strong> buttons above to gather data for configured peer engineers across levels.</p>
          </div>
        </div>`;
    }

    const activeLevels = ["ase", "se", "sse", "pse", "spse", "de"].filter(lk => benchmarks.levels[lk]);
    const allCompIds = new Set<string>();
    Object.keys(this.state.competencies).forEach(c => allCompIds.add(c));
    for (const lk of activeLevels) {
      Object.keys(benchmarks.levels[lk].avg_competency_pct || {}).forEach(c => allCompIds.add(c));
    }
    const sortedComps = Array.from(allCompIds).sort();

    // Peer stats summary cards (Your Score vs target level distribution)
    const statsSummaryHtml = this.renderPeerStatsSummary(benchmarks, activeLevels, levelLabels, levelColors);

    // Level distribution table
    const levelDistTableHtml = this.renderLevelDistributionTable(benchmarks, activeLevels, levelLabels, levelColors);

    // Global comparison mode toggle + enrichment toggle
    const cmpMode = this.state.peer_comparison_mode || "comparable";
    const rawActive = cmpMode === "raw" ? " active" : "";
    const cmpActive = cmpMode === "comparable" ? " active" : "";
    const enrichOn = this.state.session_enrichment;
    const comparisonToggle = `<div class="heatmap-mode-toggle" style="margin-bottom:8px;display:flex;align-items:center;gap:12px;">
      <div>
        <button class="heatmap-mode-btn${rawActive}" onclick="vscode.postMessage({type:'switchPeerComparisonMode',mode:'raw'})">Raw</button>
        <button class="heatmap-mode-btn${cmpActive}" onclick="vscode.postMessage({type:'switchPeerComparisonMode',mode:'comparable'})">Normalized</button>
      </div>
      <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;font-size:11px;color:var(--vscode-descriptionForeground);" title="Session enrichment adds keywords from daily session logs to boost competency matches. Toggle off to see raw signal-only scores."><input type="checkbox" ${enrichOn ? "checked" : ""} onchange="vscode.postMessage({type:'toggleSessionEnrichment'})" style="cursor:pointer;" />Enriched</label>
    </div>`;

    // Benchmark Comparison: two charts side-by-side, heatmap full-width below
    const benchmarkRow = `
      <div class="section">
        <div class="section-title">Benchmark Comparison ${comparisonToggle}</div>
        <div class="peer-chart-row peer-chart-row--2col">
          ${this.renderLevelComparisonBars(benchmarks, activeLevels, levelLabels, levelColors)}
          ${this.renderEventStackedBars(benchmarks, activeLevels, levelLabels, levelColors)}
        </div>
        <div class="peer-heatmap-section">
          ${this.renderCompetencyHeatmap(benchmarks, activeLevels, levelLabels, levelColors)}
        </div>
      </div>`;
    const heatmapRow = "";

    // Radar chart (SVG in JS)
    const radarSvg = this.renderPeerRadar(sortedComps, activeLevels, benchmarks, levelColors);

    // Grouped competency bars with collapsible per-level stats tables
    let barsHtml = '<div class="peer-grouped-bars">';
    for (const compId of sortedComps) {
      const name = compId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
      barsHtml += `<div class="peer-comp-group"><div class="peer-comp-name">${this.escapeHtml(name)}</div>`;

      const isComp = (this.state.peer_comparison_mode || "comparable") === "comparable";
      const userPct = isComp
        ? (this.state.competencies[compId]?.peer_comparable_percentage ?? this.state.competencies[compId]?.percentage ?? 0)
        : this.getEffectivePercentage(compId);
      barsHtml += `<div class="peer-bar-row"><span class="peer-bar-label" style="color:${levelColors.you}">You</span><div class="peer-bar-track"><div class="peer-bar-fill" style="width:${userPct}%;background:${levelColors.you};"></div></div><span class="peer-bar-value">${userPct}%</span></div>`;

      for (const lk of activeLevels) {
        const ld = benchmarks.levels[lk];
        const pct = isComp
          ? (ld?.comparable_avg_competency_pct?.[compId] ?? ld?.avg_competency_pct?.[compId] ?? 0)
          : (ld?.avg_competency_pct?.[compId] ?? 0);
        const label = levelLabels[lk] || lk;
        const color = levelColors[lk] || "#888";
        const compStats = isComp
          ? (ld?.comparable_stats_competency?.[compId] ?? ld?.stats_competency?.[compId])
          : ld?.stats_competency?.[compId];
        let rangeHtml = "";
        let valueText = `${pct}%`;
        if (compStats && compStats.count > 1) {
          rangeHtml = `<div class="peer-bar-range" style="left:${compStats.min}%;width:${Math.max(compStats.max - compStats.min, 1)}%;background:${color};"></div>`;
          rangeHtml += `<div class="peer-bar-median" style="left:${compStats.median}%;background:${color};"></div>`;
          valueText = `${pct}% (${compStats.min}–${compStats.max}%)`;
        }
        barsHtml += `<div class="peer-bar-row"><span class="peer-bar-label" style="color:${color}">${this.escapeHtml(label)}</span><div class="peer-bar-track">${rangeHtml}<div class="peer-bar-fill" style="width:${pct}%;background:${color};"></div></div><span class="peer-bar-value">${valueText}</span></div>`;
      }

      // Collapsible stats detail table for this competency
      const hasAnyStats = activeLevels.some(lk => {
        const st = isComp
          ? (benchmarks.levels[lk]?.comparable_stats_competency?.[compId] ?? benchmarks.levels[lk]?.stats_competency?.[compId])
          : benchmarks.levels[lk]?.stats_competency?.[compId];
        return (st?.count ?? 0) > 0;
      });
      if (hasAnyStats) {
        barsHtml += `<details class="peer-comp-stats-detail"><summary class="peer-comp-stats-toggle">Distribution Details</summary>`;
        barsHtml += `<table class="peer-volume-table"><thead><tr><th>Level</th><th>N</th><th>Min</th><th>Avg</th><th>Median</th><th>Max</th><th>P25</th><th>P75</th></tr></thead><tbody>`;
        for (const lk of activeLevels) {
          const cs = isComp
            ? (benchmarks.levels[lk]?.comparable_stats_competency?.[compId] ?? benchmarks.levels[lk]?.stats_competency?.[compId])
            : benchmarks.levels[lk]?.stats_competency?.[compId];
          if (!cs) continue;
          const color = levelColors[lk] || "#888";
          barsHtml += `<tr><td style="color:${color}">${this.escapeHtml(levelLabels[lk] || lk)}</td><td>${cs.count}</td><td>${cs.min}%</td><td>${cs.avg}%</td><td>${cs.median}%</td><td>${cs.max}%</td><td>${cs.p25}%</td><td>${cs.p75}%</td></tr>`;
        }
        barsHtml += `</tbody></table></details>`;
      }

      barsHtml += `</div>`;
    }
    barsHtml += "</div>";

    // Volume summary table (You vs peer levels by event source)
    const volumeTableHtml = this.renderVolumeTable(benchmarks, activeLevels, levelLabels, levelColors);

    const lastUpdated = benchmarks.last_updated ? new Date(benchmarks.last_updated).toLocaleString() : "Never";

    // AI Narrative
    let narrativeHtml = "";
    if (this.state.ai_peer_narrative?.narrative) {
      const src = this.state.ai_peer_narrative.source === "ai" ? "AI" : "Analysis";
      narrativeHtml = `
        <div class="section">
          <div class="section-title">AI Insights <span class="ai-badge">${this.escapeHtml(src)}</span></div>
          <div class="ai-insight-card">${this.escapeHtml(this.state.ai_peer_narrative.narrative)}</div>
        </div>`;
    }

    // AI Differentiators
    let diffHtml = "";
    const diff = this.state.ai_peer_differentiators;
    if (diff?.user_vs_target) {
      const uvt = diff.user_vs_target;
      if (uvt.strengths.length > 0 || uvt.gaps.length > 0) {
        diffHtml = `<div class="section"><div class="section-title">vs ${this.escapeHtml(uvt.target_label)} Benchmarks</div><div class="ai-diff-grid">`;
        if (uvt.strengths.length > 0) {
          diffHtml += `<div class="ai-diff-col"><div class="ai-diff-header ai-diff-positive">Strengths</div>`;
          for (const s of uvt.strengths.slice(0, 5)) {
            diffHtml += `<div class="ai-diff-item"><span class="ai-diff-name">${this.escapeHtml(s.name)}</span><span class="ai-diff-delta positive">+${s.delta}%</span></div>`;
          }
          diffHtml += `</div>`;
        }
        if (uvt.gaps.length > 0) {
          diffHtml += `<div class="ai-diff-col"><div class="ai-diff-header ai-diff-negative">Gaps</div>`;
          for (const g of uvt.gaps.slice(0, 5)) {
            diffHtml += `<div class="ai-diff-item"><span class="ai-diff-name">${this.escapeHtml(g.name)}</span><span class="ai-diff-delta negative">${g.delta}%</span></div>`;
          }
          diffHtml += `</div>`;
        }
        diffHtml += `</div></div>`;
      }
    }

    // Promotion readiness button
    const promoHtml = `<button class="btn btn-sm btn-secondary" data-action="loadPromotionReadiness">Promotion Readiness</button>`;

    return `
      <div class="perf-tab-panel">
        <div class="section">
          <div class="flex-between">
            <div class="section-title">Peer Comparison</div>
            <div class="d-flex gap-8">
              ${promoHtml}
            </div>
          </div>
          <div class="text-secondary text-xs mt-4">Last updated: ${this.escapeHtml(lastUpdated)}</div>
        </div>

        ${orgOverviewHtml}
        ${statsSummaryHtml}
        ${benchmarkRow}
        ${heatmapRow}
        ${levelDistTableHtml}

        ${narrativeHtml}
        ${diffHtml}
        ${this._renderPromotionReadiness()}

        <div class="section">
          <div class="section-title">Competency Radar</div>
          <div class="peer-radar-container">${radarSvg}</div>
          ${this.renderRadarStatsLegend(benchmarks, activeLevels, levelLabels, levelColors)}
        </div>

        <div class="section">
          <div class="section-title">Competency Breakdown by Level</div>
          ${barsHtml}
        </div>

        ${volumeTableHtml}

        <div class="section">
          <div class="flex-between">
            <div class="section-title">Growth Trajectory</div>
            <button class="btn btn-xs" data-action="loadPeerGrowth">Load Growth Data</button>
          </div>
          <div id="peerGrowthContainer" class="peer-growth-container"></div>
        </div>
      </div>`;
  }

  private renderPeerStatsSummary(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const isComp = (this.state.peer_comparison_mode || "comparable") === "comparable";
    const userLevel = this.state.scoring_config?.engineering_level || "sse";
    const targetLevel = activeLevels.includes(userLevel) ? userLevel : activeLevels[activeLevels.length - 1];
    if (!targetLevel) return "";
    const ld = benchmarks.levels[targetLevel];
    const stats = isComp ? (ld?.comparable_stats_overall ?? ld?.stats_overall) : ld?.stats_overall;
    if (!stats || stats.count === 0) return "";

    const userPct = isComp && this.state.peer_comparable_overall > 0
      ? this.state.peer_comparable_overall
      : this.getEffectiveOverall();
    const color = levelColors[targetLevel] || "#888";
    const label = levelLabels[targetLevel] || targetLevel.toUpperCase();
    const modeLabel = isComp ? " (Normalized)" : "";

    const card = (title: string, value: string, highlight?: string) =>
      `<div class="peer-overall-card"><div class="peer-overall-label">${this.escapeHtml(title)}</div><div class="peer-overall-value" style="color:${highlight || "var(--text-primary)"}">${value}</div></div>`;

    const rosterN = ld?.roster_count ?? 0;
    const coveragePct = rosterN > 0 ? Math.round((stats.count / rosterN) * 100) : 0;
    const coverageNote = rosterN > 0 ? ` of ${rosterN} in roster` : "";
    let warning = "";
    if (stats.count < 3) {
      warning = `<div class="peer-warning peer-warning-critical">Too few peers with data (N=${stats.count}${coverageNote}) &mdash; comparison is unreliable</div>`;
    } else if (stats.count < 5) {
      warning = `<div class="peer-warning peer-warning-low">Low sample size (N=${stats.count}${coverageNote}, ${coveragePct}% coverage) &mdash; interpret with caution</div>`;
    }

    return `
      <div class="section">
        <div class="section-title">Your Score vs ${this.escapeHtml(label)} Peers (N=${stats.count}${coverageNote})${modeLabel}</div>
        ${warning}
        <div class="peer-overall-grid">
          ${card("Your Score", `${userPct}%`, levelColors.you)}
          ${card("Min", `${stats.min}%`, color)}
          ${card("P25", `${stats.p25}%`, color)}
          ${card("Avg", `${stats.avg}%`, color)}
          ${card("Median", `${stats.median}%`, color)}
          ${card("P75", `${stats.p75}%`, color)}
          ${card("Max", `${stats.max}%`, color)}
        </div>
      </div>`;
  }

  private renderLevelDistributionTable(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const isComp = (this.state.peer_comparison_mode || "comparable") === "comparable";
    const hasStats = activeLevels.some(lk => {
      const st = isComp
        ? (benchmarks.levels[lk]?.comparable_stats_overall ?? benchmarks.levels[lk]?.stats_overall)
        : benchmarks.levels[lk]?.stats_overall;
      return (st?.count ?? 0) > 0;
    });
    if (!hasStats) return "";

    const userLevel = this.state.scoring_config?.engineering_level || "sse";
    const modeLabel = isComp ? " (Normalized)" : "";
    let html = `<div class="section"><div class="section-title">Level Distribution (Overall Score)${modeLabel}</div>`;
    html += `<table class="peer-volume-table"><thead><tr><th>Level</th><th>Peers</th><th>Min</th><th>P25</th><th>Avg</th><th>Median</th><th>P75</th><th>Max</th></tr></thead><tbody>`;
    for (const lk of activeLevels) {
      const st = isComp
        ? (benchmarks.levels[lk]?.comparable_stats_overall ?? benchmarks.levels[lk]?.stats_overall)
        : benchmarks.levels[lk]?.stats_overall;
      if (!st) continue;
      const color = levelColors[lk] || "#888";
      const highlight = lk === userLevel ? ` style="background:var(--bg-tertiary, rgba(255,255,255,0.05))"` : "";
      const rosterN = benchmarks.levels[lk]?.roster_count ?? 0;
      const peersLabel = rosterN > 0 ? `${st.count}/${rosterN}` : `${st.count}`;
      const lowNMark = st.count < 5 ? ' <span style="color:var(--warning)" title="Low sample size">\u26A0</span>' : "";
      html += `<tr${highlight}><td style="color:${color};font-weight:700">${this.escapeHtml(levelLabels[lk] || lk)}</td><td>${peersLabel}${lowNMark}</td><td>${st.min}%</td><td>${st.p25}%</td><td>${st.avg}%</td><td>${st.median}%</td><td>${st.p75}%</td><td>${st.max}%</td></tr>`;
    }
    html += `</tbody></table></div>`;
    return html;
  }

  private renderVolumeTable(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const allSources = new Set<string>();
    for (const lk of activeLevels) {
      Object.keys(benchmarks.levels[lk]?.avg_event_counts_by_source || {}).forEach(s => allSources.add(s));
    }
    const sources = Array.from(allSources).sort();
    if (sources.length === 0) return "";

    let html = `<div class="section"><div class="section-title">Event Volume Comparison (Avg Daily Events)</div>`;
    html += `<table class="peer-volume-table"><thead><tr><th>Source</th>`;
    for (const lk of activeLevels) {
      const color = levelColors[lk] || "#888";
      html += `<th style="color:${color}">${this.escapeHtml(levelLabels[lk] || lk)}</th>`;
    }
    html += `</tr></thead><tbody>`;

    for (const src of sources) {
      html += `<tr><td>${this.escapeHtml(src.charAt(0).toUpperCase() + src.slice(1))}</td>`;
      for (const lk of activeLevels) {
        const val = benchmarks.levels[lk]?.avg_event_counts_by_source?.[src] ?? 0;
        const display = typeof val === "number" && !Number.isInteger(val) ? val.toFixed(1) : String(val);
        html += `<td>${display}</td>`;
      }
      html += `</tr>`;
    }

    // Total row
    html += `<tr style="font-weight:700;border-top:2px solid var(--border)"><td>Total</td>`;
    for (const lk of activeLevels) {
      const total = sources.reduce((s, src) => s + (benchmarks.levels[lk]?.avg_event_counts_by_source?.[src] ?? 0), 0);
      html += `<td>${total.toFixed(1)}</td>`;
    }
    html += `</tr></tbody></table></div>`;
    return html;
  }

  private renderRadarStatsLegend(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const hasStats = activeLevels.some(lk => (benchmarks.levels[lk]?.stats_overall?.count ?? 0) > 1);
    if (!hasStats) return "";

    let html = `<div class="peer-radar-stats-legend">`;
    for (const lk of activeLevels) {
      const st = benchmarks.levels[lk]?.stats_overall;
      if (!st || st.count < 2) continue;
      const color = levelColors[lk] || "#888";
      const label = levelLabels[lk] || lk;
      const rosterN = benchmarks.levels[lk]?.roster_count ?? 0;
      const nLabel = rosterN > 0 ? `N=${st.count}/${rosterN}` : `N=${st.count}`;
      const lowN = st.count < 5 ? ' <span style="color:var(--warning)">\u26A0</span>' : "";
      html += `<span class="peer-radar-stats-item" style="color:${color}"><strong>${this.escapeHtml(label)}</strong>: avg ${st.avg}% &middot; min ${st.min}% &middot; max ${st.max}% &middot; median ${st.median}% (${nLabel})${lowN}</span>`;
    }
    html += `</div>`;
    return html;
  }

  private _renderPromotionReadiness(): string {
    const promo = this.state.ai_promotion_readiness;
    if (!promo) return "";

    let assessHtml = "";
    for (const a of promo.assessments) {
      const cls = a.status === "ready" ? "positive" : a.status === "almost" ? "neutral" : "negative";
      const icon = a.status === "ready" ? "\u2705" : a.status === "almost" ? "\u{1F7E1}" : "\u274C";
      assessHtml += `<div class="promo-assess-row ${cls}"><span class="promo-icon">${icon}</span><span class="promo-comp">${this.escapeHtml(a.name)}</span><span class="promo-pct">${a.user_pct}% / ${a.target_pct}%</span><span class="promo-delta">${a.delta >= 0 ? "+" : ""}${a.delta}%</span></div>`;
    }

    const src = promo.source === "ai" ? "AI" : "Analysis";
    return `
      <div class="section">
        <div class="section-title">Promotion Readiness: ${this.escapeHtml(promo.next_level_label)} <span class="ai-badge">${this.escapeHtml(src)}</span></div>
        <div class="ai-insight-card">${this.escapeHtml(promo.summary)}</div>
        <div class="promo-summary mt-8">Meeting ${promo.ready_count}/${promo.total_competencies} competency benchmarks</div>
        <div class="promo-assessments mt-8">${assessHtml}</div>
      </div>`;
  }

  // ============================================================
  // Peer Charts: Org Overview (Row 1) + Benchmark Charts (Row 2)
  // ============================================================

  private renderOrgLevelDistribution(
    orgStats: OrgStats,
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const byLevel = orgStats.by_level;
    const orderedLevels = ["ase", "se", "sse", "pse", "spse", "de"].filter(l => byLevel[l] !== undefined);
    const maxCount = Math.max(...orderedLevels.map(l => byLevel[l] || 0), 1);

    let barsHtml = "";
    for (const lk of orderedLevels) {
      const count = byLevel[lk] || 0;
      const pct = Math.round((count / maxCount) * 100);
      const color = levelColors[lk] || "#888";
      const label = (lk === "ase" ? "ASE" : lk === "se" ? "SE" : lk === "sse" ? "SSE" : lk === "pse" ? "PSE" : lk === "spse" ? "SPSE" : "DE");
      const highlighted = lk === "pse" ? " highlighted" : "";
      barsHtml += `<div class="org-bar-row">
        <span class="org-bar-label" style="color:${color}">${label}</span>
        <div class="org-bar-track">
          <div class="org-bar-fill${highlighted}" style="width:${pct}%;background:${color};"></div>
        </div>
        <span class="org-bar-count">${count}</span>
      </div>`;
    }

    return `<div class="peer-chart-cell">
      <div class="chart-title">Org Level Distribution</div>
      ${barsHtml}
      <div class="chart-subtitle">${orgStats.total_resolved} engineers resolved of ${orgStats.total_org_chart} total</div>
    </div>`;
  }

  private renderOrgDonut(
    orgStats: OrgStats,
    levelColors: Record<string, string>,
  ): string {
    const byLevel = orgStats.by_level;
    const orderedLevels = ["ase", "se", "sse", "pse", "spse", "de"].filter(l => byLevel[l] !== undefined);
    const total = orderedLevels.reduce((sum, l) => sum + (byLevel[l] || 0), 0);
    if (total === 0) return `<div class="peer-chart-cell"><div class="chart-title">Org Composition</div><p class="text-secondary text-xs">No data</p></div>`;

    const size = 180;
    const cx = size / 2, cy = size / 2;
    const outerR = 80, innerR = 50;

    let svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">`;

    let startAngle = -Math.PI / 2;
    for (const lk of orderedLevels) {
      const count = byLevel[lk] || 0;
      if (count === 0) continue;
      const sliceAngle = (count / total) * 2 * Math.PI;
      const endAngle = startAngle + sliceAngle;
      const largeArc = sliceAngle > Math.PI ? 1 : 0;

      const x1o = cx + outerR * Math.cos(startAngle);
      const y1o = cy + outerR * Math.sin(startAngle);
      const x2o = cx + outerR * Math.cos(endAngle);
      const y2o = cy + outerR * Math.sin(endAngle);
      const x1i = cx + innerR * Math.cos(endAngle);
      const y1i = cy + innerR * Math.sin(endAngle);
      const x2i = cx + innerR * Math.cos(startAngle);
      const y2i = cy + innerR * Math.sin(startAngle);

      const color = levelColors[lk] || "#888";
      const d = `M ${x1o.toFixed(1)} ${y1o.toFixed(1)} A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2o.toFixed(1)} ${y2o.toFixed(1)} L ${x1i.toFixed(1)} ${y1i.toFixed(1)} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x2i.toFixed(1)} ${y2i.toFixed(1)} Z`;
      svg += `<path d="${d}" fill="${color}" opacity="0.85"><title>${lk.toUpperCase()}: ${count} (${Math.round(count / total * 100)}%)</title></path>`;

      startAngle = endAngle;
    }

    svg += `<text x="${cx}" y="${cy - 6}" text-anchor="middle" fill="var(--vscode-foreground, #ccc)" font-size="22" font-weight="800">${total}</text>`;
    svg += `<text x="${cx}" y="${cy + 12}" text-anchor="middle" fill="var(--vscode-descriptionForeground, #888)" font-size="10">engineers</text>`;
    svg += `</svg>`;

    let legendHtml = `<div class="peer-donut-legend">`;
    for (const lk of orderedLevels) {
      const count = byLevel[lk] || 0;
      if (count === 0) continue;
      const color = levelColors[lk] || "#888";
      const label = lk.toUpperCase();
      legendHtml += `<span class="peer-donut-legend-item"><span class="peer-donut-legend-dot" style="background:${color}"></span>${label} ${count}</span>`;
    }
    legendHtml += `</div>`;

    return `<div class="peer-chart-cell">
      <div class="chart-title">Org Composition</div>
      <div class="peer-donut-container">${svg}</div>
      ${legendHtml}
    </div>`;
  }

  private renderPeerSampleCoverage(
    orgStats: OrgStats,
    levelColors: Record<string, string>,
  ): string {
    const orderedLevels = ["ase", "se", "sse", "pse", "spse", "de"].filter(
      l => orgStats.by_level[l] !== undefined || orgStats.sampled_per_level[l] !== undefined,
    );

    let rowsHtml = "";
    for (const lk of orderedLevels) {
      const total = orgStats.by_level[lk] || 0;
      const sampled = orgStats.sampled_per_level[lk] || 0;
      const pct = total > 0 ? Math.round((sampled / total) * 100) : 0;
      const color = levelColors[lk] || "#888";
      const label = lk.toUpperCase();
      rowsHtml += `<div class="peer-sample-row">
        <span class="peer-sample-label" style="color:${color}">${label}</span>
        <div class="peer-sample-track">
          <div class="peer-sample-fill" style="width:${pct}%;background:${color};"></div>
        </div>
        <span class="peer-sample-text">${sampled}/${total}</span>
      </div>`;
    }

    return `<div class="peer-chart-cell">
      <div class="chart-title">Peer Coverage</div>
      ${rowsHtml}
      <div class="chart-subtitle">${orgStats.total_unresolved} engineers unresolved in roster</div>
    </div>`;
  }

  private renderLevelComparisonBars(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const isComparable = (this.state.peer_comparison_mode || "comparable") === "comparable";
    const userPct = isComparable && this.state.peer_comparable_overall > 0
      ? this.state.peer_comparable_overall
      : this.getEffectiveOverall();
    const allMax = activeLevels.reduce((m, lk) => {
      const ld = benchmarks.levels[lk];
      const st = isComparable ? (ld?.comparable_stats_overall ?? ld?.stats_overall) : ld?.stats_overall;
      const avg = isComparable ? (ld?.comparable_avg_overall_pct ?? ld?.avg_overall_pct ?? 0) : (ld?.avg_overall_pct ?? 0);
      return Math.max(m, st?.max ?? avg);
    }, userPct);
    const maxPct = Math.max(allMax, 1);

    const barWidth = 460, barHeight = 28;
    const gap = 8;
    const labelWidth = 100;
    const trackWidth = barWidth - labelWidth - 60;

    interface BarItem { label: string; pct: number; color: string; stats?: DistributionStats }
    const items: BarItem[] = [
      { label: "You", pct: userPct, color: levelColors.you },
      ...activeLevels.map(lk => {
        const ld = benchmarks.levels[lk];
        return {
          label: levelLabels[lk] || lk,
          pct: isComparable ? (ld?.comparable_avg_overall_pct ?? ld?.avg_overall_pct ?? 0) : (ld?.avg_overall_pct ?? 0),
          color: levelColors[lk] || "#888",
          stats: isComparable ? (ld?.comparable_stats_overall ?? ld?.stats_overall) : ld?.stats_overall,
        };
      }),
    ];

    const totalHeight = items.length * (barHeight + gap);
    let svg = `<svg width="100%" viewBox="0 0 ${barWidth} ${totalHeight}" xmlns="http://www.w3.org/2000/svg">`;

    items.forEach((item, i) => {
      const y = i * (barHeight + gap);
      const w = Math.round((item.pct / maxPct) * trackWidth);

      svg += `<text x="${labelWidth - 8}" y="${y + barHeight / 2 + 5}" text-anchor="end" fill="${item.color}" font-size="13" font-weight="600">${this.escapeHtml(item.label)}</text>`;
      svg += `<rect x="${labelWidth}" y="${y}" width="${trackWidth}" height="${barHeight}" rx="4" fill="var(--vscode-editor-background, #1e1e1e)" opacity="0.5"/>`;

      if (item.stats && item.stats.count > 1) {
        const st = item.stats;
        const xMin = labelWidth + Math.round((st.min / maxPct) * trackWidth);
        const xMax = labelWidth + Math.round((st.max / maxPct) * trackWidth);
        const rangeW = Math.max(xMax - xMin, 2);
        svg += `<rect x="${xMin}" y="${y + 2}" width="${rangeW}" height="${barHeight - 4}" rx="3" fill="${item.color}" opacity="0.15"/>`;
        const midY = y + barHeight / 2;
        svg += `<line x1="${xMin}" y1="${midY - 5}" x2="${xMin}" y2="${midY + 5}" stroke="${item.color}" stroke-width="1.5" opacity="0.5"/>`;
        svg += `<line x1="${xMax}" y1="${midY - 5}" x2="${xMax}" y2="${midY + 5}" stroke="${item.color}" stroke-width="1.5" opacity="0.5"/>`;
        svg += `<line x1="${xMin}" y1="${midY}" x2="${xMax}" y2="${midY}" stroke="${item.color}" stroke-width="1" opacity="0.35"/>`;
        const xMed = labelWidth + Math.round((st.median / maxPct) * trackWidth);
        svg += `<line x1="${xMed}" y1="${y + 2}" x2="${xMed}" y2="${y + barHeight - 2}" stroke="${item.color}" stroke-width="2" opacity="0.7"/>`;
      }

      svg += `<rect x="${labelWidth}" y="${y}" width="${Math.max(w, 2)}" height="${barHeight}" rx="4" fill="${item.color}" opacity="0.8"/>`;

      let labelText = `${item.pct}%`;
      if (item.stats && item.stats.count > 1) {
        labelText = `${item.pct}% (${item.stats.min}\u2013${item.stats.max}%)`;
      }

      if (i === 0 && !isComparable && this.state.peer_comparable_overall > 0 && this.state.peer_comparable_overall < item.pct) {
        const pcW = Math.round((this.state.peer_comparable_overall / maxPct) * trackWidth);
        svg += `<line x1="${labelWidth + pcW}" y1="${y}" x2="${labelWidth + pcW}" y2="${y + barHeight}" stroke="${item.color}" stroke-width="2" stroke-dasharray="3,2" opacity="0.6"/>`;
        labelText += ` (normalized: ${this.state.peer_comparable_overall}%)`;
      }

      svg += `<text x="${labelWidth + w + 6}" y="${y + barHeight / 2 + 5}" fill="var(--vscode-foreground, #ccc)" font-size="12" font-weight="600">${labelText}</text>`;
    });

    svg += `</svg>`;

    const modeLabel = isComparable ? " (Normalized)" : "";
    return `<div class="peer-chart-cell">
      <div class="chart-title">Overall Score Comparison${modeLabel}</div>
      ${svg}
    </div>`;
  }

  private renderEventStackedBars(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const sourceColors: Record<string, string> = {
      git: "#f97316",
      jira: "#3b82f6",
      gitlab: "#8b5cf6",
      github: "#10b981",
      gdrive: "#22c55e",
      meeting: "#ec4899",
    };

    const volMode = this.state.event_volume_mode || "comparable";
    const isComparable = volMode === "comparable";
    const allCounts = this.state.event_counts_by_source || {};
    const compCounts = this.state.comparable_event_counts_by_source || {};
    const userCounts = isComparable && Object.keys(compCounts).length > 0 ? compCounts : allCounts;

    const allSources = new Set<string>();
    Object.keys(userCounts).forEach(s => allSources.add(s));
    for (const lk of activeLevels) {
      Object.keys(benchmarks.levels[lk]?.avg_event_counts_by_source || {}).forEach(s => allSources.add(s));
    }
    const sources = Array.from(allSources).sort();

    const userTotal = sources.reduce((s, src) => s + (userCounts[src] || 0), 0);

    const rows: { label: string; color: string; counts: Record<string, number>; total: number }[] = [
      { label: "You", color: levelColors.you, counts: userCounts, total: userTotal },
    ];
    for (const lk of activeLevels) {
      const counts = benchmarks.levels[lk]?.avg_event_counts_by_source || {};
      const total = sources.reduce((s, src) => s + (counts[src] || 0), 0);
      rows.push({ label: levelLabels[lk] || lk, color: levelColors[lk] || "#888", counts, total });
    }
    const maxTotal = Math.max(...rows.map(r => r.total), 1);

    let barsHtml = "";
    for (const row of rows) {
      let segHtml = "";
      for (const src of sources) {
        const val = row.counts[src] || 0;
        const pct = row.total > 0 ? (val / maxTotal) * 100 : 0;
        const color = sourceColors[src] || "#666";
        segHtml += `<div class="peer-stacked-segment" style="width:${pct.toFixed(1)}%;background:${color};" title="${src}: ${val.toFixed(1)}"></div>`;
      }
      barsHtml += `<div class="peer-stacked-row">
        <span class="peer-stacked-label" style="color:${row.color}">${this.escapeHtml(row.label)}</span>
        <div class="peer-stacked-track">${segHtml}</div>
        <span class="peer-stacked-total">${row.total.toFixed(0)}</span>
      </div>`;
    }

    let legendHtml = `<div class="peer-stacked-legend">`;
    for (const src of sources) {
      const color = sourceColors[src] || "#666";
      legendHtml += `<span class="peer-stacked-legend-item"><span class="peer-stacked-legend-swatch" style="background:${color}"></span>${this.escapeHtml(src)}</span>`;
    }
    legendHtml += `</div>`;

    const allBtn = `<button class="heatmap-mode-btn${!isComparable ? " active" : ""}" onclick="vscode.postMessage({type:'switchEventVolumeMode',mode:'all'})">All</button>`;
    const compBtn = `<button class="heatmap-mode-btn${isComparable ? " active" : ""}" onclick="vscode.postMessage({type:'switchEventVolumeMode',mode:'comparable'})">Comparable</button>`;
    const toggleHtml = `<div class="heatmap-mode-toggle" style="margin-bottom:6px;">${allBtn}${compBtn}</div>`;

    const primaryOnlySources = ["session", "gdrive"].filter(s => (allCounts[s] || 0) > 0);
    let coverageNote = "";
    if (!isComparable && primaryOnlySources.length > 0) {
      const allTotal = sources.reduce((s, src) => s + (allCounts[src] || 0), 0);
      const pctExclusive = Math.round(
        primaryOnlySources.reduce((s, src) => s + (allCounts[src] || 0), 0) / Math.max(allTotal, 1) * 100,
      );
      coverageNote = `<div class="chart-subtitle" style="color:var(--warning,#f59e0b);">${pctExclusive}% of your events come from sources peers lack (${primaryOnlySources.join(", ")})</div>`;
    }

    let parityWarnings = "";
    const sharedSources = sources.filter(s => s !== "session");
    for (const lk of activeLevels) {
      const peerCounts = benchmarks.levels[lk]?.avg_event_counts_by_source || {};
      const missingSources = sharedSources.filter(s => (userCounts[s] || 0) > 0 && (peerCounts[s] || 0) === 0);
      if (missingSources.length > 0) {
        const label = levelLabels[lk] || lk;
        parityWarnings += `<div class="chart-subtitle" style="color:var(--warning,#f59e0b);">${this.escapeHtml(label)} peers have no ${missingSources.join(", ")} events</div>`;
      }
    }

    let coverageIndicator = "";
    const coverageParts: string[] = [];
    for (const lk of activeLevels) {
      const ld = benchmarks.levels[lk];
      const avgDays = ld?.avg_days_with_events ?? 0;
      if (avgDays > 0) {
        const label = levelLabels[lk] || lk;
        coverageParts.push(`${this.escapeHtml(label)}: ${avgDays.toFixed(0)}d avg`);
      }
    }
    if (coverageParts.length > 0) {
      coverageIndicator = `<div class="chart-subtitle">Data coverage: ${coverageParts.join(" | ")}</div>`;
    }

    const modeLabel = isComparable ? " (Comparable Only)" : "";
    return `<div class="peer-chart-cell">
      <div class="chart-title">Event Volume by Source${modeLabel}</div>
      ${toggleHtml}
      ${barsHtml}
      ${legendHtml}
      <div class="chart-subtitle">Cumulative events (peer values are level averages)</div>
      ${coverageNote}
      ${parityWarnings}
      ${coverageIndicator}
    </div>`;
  }

  private renderCompetencyHeatmap(
    benchmarks: PeerBenchmarks,
    activeLevels: string[],
    levelLabels: Record<string, string>,
    levelColors: Record<string, string>,
  ): string {
    const allCompIds = new Set<string>();
    Object.keys(this.state.competencies).forEach(c => allCompIds.add(c));
    for (const lk of activeLevels) {
      Object.keys(benchmarks.levels[lk]?.avg_competency_pct || {}).forEach(c => allCompIds.add(c));
    }
    const sortedComps = Array.from(allCompIds).sort();
    if (sortedComps.length === 0) return "";

    const mode = this.state.heatmap_mode || "percentage";
    const isPeerComparable = mode === "peer_comparable";
    const isRawPoints = mode === "raw_points";

    const cols = ["you", ...activeLevels];
    const gridCols = `minmax(220px, 1.2fr) repeat(${cols.length}, minmax(60px, 1fr))`;

    const modeButtons = [
      { key: "percentage", label: "%" },
      { key: "raw_points", label: "Pts" },
      { key: "peer_comparable", label: "Normalized" },
    ];
    let toggleHtml = `<div class="heatmap-mode-toggle">`;
    for (const mb of modeButtons) {
      const active = mode === mb.key ? " active" : "";
      toggleHtml += `<button class="heatmap-mode-btn${active}" onclick="vscode.postMessage({type:'switchHeatmapMode',mode:'${mb.key}'})">${mb.label}</button>`;
    }
    toggleHtml += `</div>`;

    let html = `<div class="peer-heatmap" style="grid-template-columns: ${gridCols};">`;

    html += `<div class="peer-heatmap-header"></div>`;
    for (const col of cols) {
      let label = col === "you" ? "You" : (levelLabels[col] || col.toUpperCase());
      if (col === "you" && isPeerComparable) label = "You (Normalized)";
      const color = levelColors[col] || "var(--text-secondary)";
      html += `<div class="peer-heatmap-header" style="color:${color}">${label}</div>`;
    }

    for (const compId of sortedComps) {
      const name = compId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
      html += `<div class="peer-heatmap-row-label" title="${this.escapeHtml(name)}">${this.escapeHtml(name)}</div>`;

      for (const col of cols) {
        let displayVal: number;
        let suffix = "%";
        let maxVal = 100;
        let spreadAnnotation = "";

        if (col === "you") {
          if (isRawPoints) {
            displayVal = this.state.competencies[compId]?.points ?? 0;
            suffix = "";
            maxVal = 300;
          } else if (isPeerComparable) {
            displayVal = this.state.competencies[compId]?.peer_comparable_percentage ?? 0;
          } else {
            displayVal = this.getEffectivePercentage(compId);
          }
        } else {
          if (isRawPoints) {
            displayVal = benchmarks.levels[col]?.avg_competency_points?.[compId] ?? 0;
            suffix = "";
            maxVal = 300;
          } else if (isPeerComparable) {
            displayVal = benchmarks.levels[col]?.comparable_avg_competency_pct?.[compId]
              ?? benchmarks.levels[col]?.avg_competency_pct?.[compId] ?? 0;
          } else {
            displayVal = benchmarks.levels[col]?.avg_competency_pct?.[compId] ?? 0;
          }
          const statsSource = isPeerComparable
            ? (benchmarks.levels[col]?.comparable_stats_competency?.[compId] ?? benchmarks.levels[col]?.stats_competency?.[compId])
            : benchmarks.levels[col]?.stats_competency?.[compId];
          if (statsSource && statsSource.count > 1 && !isRawPoints) {
            const spread = Math.round(statsSource.max - statsSource.min);
            spreadAnnotation = `<span class="heatmap-spread" title="Spread: ${statsSource.min}\u2013${statsSource.max}%">\u00b1${Math.round(spread / 2)}</span>`;
          }
        }

        const color = levelColors[col] || "#888";
        const intensity = Math.max(0.1, Math.min(1, displayVal / maxVal));
        const textColor = intensity > 0.5 ? "#fff" : "var(--vscode-foreground, #ccc)";
        const tooltipParts = [`${this.escapeHtml(name)}: ${displayVal}${suffix}`];
        if (col === "you" && isPeerComparable) {
          const fullPct = this.state.competencies[compId]?.percentage ?? 0;
          tooltipParts.push(`Full score: ${fullPct}%`);
          tooltipParts.push("Excludes: session events, personal GDrive, strategy bonus");
        }
        if (col !== "you" && !isRawPoints) {
          const tooltipStats = isPeerComparable
            ? (benchmarks.levels[col]?.comparable_stats_competency?.[compId] ?? benchmarks.levels[col]?.stats_competency?.[compId])
            : benchmarks.levels[col]?.stats_competency?.[compId];
          if (tooltipStats && tooltipStats.count > 1) {
            tooltipParts.push(`Range: ${tooltipStats.min}\u2013${tooltipStats.max}%`);
            tooltipParts.push(`Median: ${tooltipStats.median}%`);
            tooltipParts.push(`N=${tooltipStats.count}`);
          }
          if (isPeerComparable) {
            tooltipParts.push("Strategy bonus normalized");
          }
        }
        const label = displayVal > 0 ? displayVal + suffix : "-";
        html += `<div class="peer-heatmap-cell" style="background:${color};opacity:${intensity.toFixed(2)};color:${textColor};" title="${tooltipParts.join('\n')}">${label}${spreadAnnotation}</div>`;
      }
    }

    html += `</div>`;

    const modeLabel = isPeerComparable ? "Peer-Comparable" : isRawPoints ? "Raw Points" : "Percentage";

    return `<div class="peer-heatmap-fullwidth">
      <div class="chart-title">Competency Heatmap <span class="chart-subtitle-inline">${modeLabel}</span> ${toggleHtml}</div>
      ${html}
    </div>`;
  }

  private renderPeerRadar(
    compIds: string[],
    activeLevels: string[],
    benchmarks: PeerBenchmarks,
    levelColors: Record<string, string>,
  ): string {
    const n = compIds.length;
    if (n < 3) return "<p>Not enough competencies for radar chart.</p>";

    const width = 500, height = 500;
    const cx = width / 2, cy = height / 2;
    const maxR = Math.min(cx, cy) * 0.7;
    let svg = `<svg width="100%" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg"><style>text { font-family: system-ui, -apple-system, sans-serif; font-size: 10px; }</style>`;

    // Grid rings
    for (const ringPct of [25, 50, 75, 100]) {
      const r = maxR * ringPct / 100;
      const pts = compIds.map((_, i) => {
        const a = (2 * Math.PI * i / n) - Math.PI / 2;
        return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
      }).join(" ");
      svg += `<polygon points="${pts}" fill="none" stroke="var(--vscode-widget-border, #ddd)" stroke-width="0.5"/>`;
    }

    // Axis lines + labels
    for (let i = 0; i < n; i++) {
      const a = (2 * Math.PI * i / n) - Math.PI / 2;
      const lx = cx + maxR * Math.cos(a);
      const ly = cy + maxR * Math.sin(a);
      svg += `<line x1="${cx}" y1="${cy}" x2="${lx.toFixed(1)}" y2="${ly.toFixed(1)}" stroke="var(--vscode-widget-border, #eee)" stroke-width="0.5"/>`;

      const labelR = maxR + 18;
      const tx = cx + labelR * Math.cos(a);
      const ty = cy + labelR * Math.sin(a);
      let name = compIds[i].replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
      if (name.length > 14) name = name.substring(0, 12) + "..";
      const anchor = Math.abs(Math.cos(a)) > 0.3 ? (Math.cos(a) > 0 ? "start" : "end") : "middle";
      svg += `<text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}" dominant-baseline="middle" fill="var(--vscode-foreground, #666)">${this.escapeHtml(name)}</text>`;
    }

    const makePolygon = (profile: Record<string, number>, color: string, opacity: number, dashed: boolean) => {
      const pts = compIds.map((cid, i) => {
        const pct = Math.min(profile[cid] ?? 0, 100);
        const r = maxR * pct / 100;
        const a = (2 * Math.PI * i / n) - Math.PI / 2;
        return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
      }).join(" ");
      const dash = dashed ? ` stroke-dasharray="6,4"` : "";
      return `<polygon points="${pts}" fill="${color}" fill-opacity="${opacity * 0.12}" stroke="${color}" stroke-width="2" stroke-opacity="${opacity}"${dash}/>`;
    };

    const isComp = (this.state.peer_comparison_mode || "comparable") === "comparable";

    // Peer min-max range bands (shaded area between min and max polygons)
    for (const lk of activeLevels) {
      const statsComp = isComp
        ? (benchmarks.levels[lk]?.comparable_stats_competency ?? benchmarks.levels[lk]?.stats_competency)
        : benchmarks.levels[lk]?.stats_competency;
      if (statsComp) {
        const hasRange = compIds.some(cid => statsComp[cid] && statsComp[cid].count > 1);
        if (hasRange) {
          const minPts = compIds.map((cid, i) => {
            const pct = Math.min(statsComp[cid]?.min ?? 0, 100);
            const r = maxR * pct / 100;
            const a = (2 * Math.PI * i / n) - Math.PI / 2;
            return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
          });
          const maxPts = compIds.map((cid, i) => {
            const pct = Math.min(statsComp[cid]?.max ?? 0, 100);
            const r = maxR * pct / 100;
            const a = (2 * Math.PI * i / n) - Math.PI / 2;
            return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
          });
          const bandPath = `M ${maxPts[0]} ` + maxPts.slice(1).map(p => `L ${p}`).join(" ") + " Z "
            + `M ${minPts[0]} ` + minPts.slice(1).map(p => `L ${p}`).join(" ") + " Z";
          const color = levelColors[lk] || "#888";
          svg += `<path d="${bandPath}" fill="${color}" fill-opacity="0.08" fill-rule="evenodd" stroke="${color}" stroke-width="0.5" stroke-opacity="0.2"/>`;
        }
      }
    }

    // Peer polygons (dashed) -- average line
    for (const lk of activeLevels) {
      const profile = isComp
        ? (benchmarks.levels[lk]?.comparable_avg_competency_pct ?? benchmarks.levels[lk].avg_competency_pct ?? {})
        : (benchmarks.levels[lk].avg_competency_pct || {});
      svg += makePolygon(profile, levelColors[lk] || "#888", 0.6, true);
    }

    // User polygon (solid)
    const userProfile: Record<string, number> = {};
    for (const cid of compIds) {
      userProfile[cid] = isComp
        ? (this.state.competencies[cid]?.peer_comparable_percentage ?? this.state.competencies[cid]?.percentage ?? 0)
        : this.getEffectivePercentage(cid);
    }
    svg += makePolygon(userProfile, levelColors.you, 1.0, false);

    // Legend
    let legendX = 10;
    const legendY = height - 15;
    const items: [string, string][] = [["you", "You"], ...activeLevels.map(lk => [lk, ({se: "Senior", pse: "Principal", spse: "Sr Principal", de: "Distinguished"} as Record<string, string>)[lk] || lk] as [string, string])];
    for (const [lk, label] of items) {
      const color = levelColors[lk] || "#888";
      const dash = lk === "you" ? "" : ` stroke-dasharray="6,4"`;
      svg += `<line x1="${legendX}" y1="${legendY}" x2="${legendX + 18}" y2="${legendY}" stroke="${color}" stroke-width="2"${dash}/>`;
      svg += `<text x="${legendX + 22}" y="${legendY + 3}" fill="var(--vscode-foreground, #666)" font-size="9">${this.escapeHtml(label)}</text>`;
      legendX += 85;
    }

    svg += "</svg>";
    return svg;
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
            <input type="text" id="activityDescription" placeholder="Description of activity..."
                   oninput="if(this.value.length>10){this.dispatchEvent(new CustomEvent('classify-log',{bubbles:true,detail:{description:this.value}}))}" />
            <button class="btn btn-sm btn-primary" data-action="logActivity">Log</button>
          </div>
          <div class="text-secondary text-xs mt-4">AI auto-categorizes as you type</div>
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
  // Calendar Graphs
  // ============================================================

  private _getMonthDays(): CapturedDay[] {
    const m = this.state.calendar_month;
    const y = this.state.calendar_year;
    const prefix = `${y}-${String(m + 1).padStart(2, "0")}-`;
    return this.state.captured_days.filter(d => d.date.startsWith(prefix));
  }

  private renderMonthlyTrend(): string {
    const monthDays = this._getMonthDays();
    if (monthDays.length < 2) return "";

    const sorted = [...monthDays].sort((a, b) => a.date.localeCompare(b.date));
    const pillars = Object.keys(PILLAR_DEFS);
    const maxPts = Math.max(...sorted.map(d => d.total_points), 1);

    const w = 600, h = 70, padX = 4, padY = 4;
    const plotW = w - padX * 2;
    const plotH = h - padY * 2;
    const n = sorted.length;

    const pillarPaths: string[] = [];
    for (const pn of pillars) {
      const color = PILLAR_DEFS[pn].color;
      const pts: string[] = [];
      for (let i = 0; i < n; i++) {
        const x = padX + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
        const v = sorted[i].category_points?.[pn] || 0;
        const y2 = padY + plotH - (v / maxPts) * plotH;
        pts.push(`${x.toFixed(1)},${y2.toFixed(1)}`);
      }
      pillarPaths.push(
        `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>`,
      );
    }

    const totalPts: string[] = [];
    const dotsSvg: string[] = [];
    for (let i = 0; i < n; i++) {
      const x = padX + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
      const y2 = padY + plotH - (sorted[i].total_points / maxPts) * plotH;
      totalPts.push(`${x.toFixed(1)},${y2.toFixed(1)}`);
      const dayNum = parseInt(sorted[i].date.split("-")[2], 10);
      dotsSvg.push(
        `<circle cx="${x.toFixed(1)}" cy="${y2.toFixed(1)}" r="2.5" fill="var(--vscode-foreground, #ccc)" opacity="0.6"><title>${dayNum}: ${sorted[i].total_points}pts</title></circle>`,
      );
    }

    const gridLines: string[] = [];
    for (let g = 0; g <= 2; g++) {
      const gy = padY + (g / 2) * plotH;
      gridLines.push(`<line x1="${padX}" y1="${gy.toFixed(1)}" x2="${w - padX}" y2="${gy.toFixed(1)}" stroke="var(--vscode-widget-border, #333)" stroke-width="0.5" opacity="0.3"/>`);
    }

    const legend = pillars.map(pn =>
      `<span class="cal-trend-legend-item"><span class="cal-trend-legend-swatch" style="background:${PILLAR_DEFS[pn].color}"></span>${pn.split(" ")[0]}</span>`,
    ).join("");

    return `
      <div class="cal-trend-wrap">
        <div class="cal-trend-header">
          <span class="cal-trend-title">Daily Trend</span>
          <div class="cal-trend-legend">${legend}</div>
        </div>
        <svg class="cal-trend-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
          ${gridLines.join("")}
          ${pillarPaths.join("")}
          <polyline points="${totalPts.join(" ")}" fill="none" stroke="var(--vscode-foreground, #ccc)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.5" stroke-dasharray="4,3"/>
          ${dotsSvg.join("")}
        </svg>
      </div>
    `;
  }

  private renderMonthlyDonut(): string {
    const monthDays = this._getMonthDays();
    if (monthDays.length === 0) return "";

    const pillars = Object.keys(PILLAR_DEFS);
    const sums: Record<string, number> = {};
    let grandTotal = 0;
    for (const pn of pillars) sums[pn] = 0;
    for (const day of monthDays) {
      for (const pn of pillars) {
        const v = day.category_points?.[pn] || 0;
        sums[pn] += v;
        grandTotal += v;
      }
    }
    if (grandTotal === 0) return "";

    const size = 200;
    const cx = size / 2, cy = size / 2;
    const outerR = 90, innerR = 58;
    const avgPerDay = Math.round(grandTotal / monthDays.length);

    let svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">`;
    let startAngle = -Math.PI / 2;

    for (const pn of pillars) {
      const v = sums[pn];
      if (v === 0) continue;
      const sliceAngle = (v / grandTotal) * 2 * Math.PI;
      const endAngle = startAngle + sliceAngle;
      const largeArc = sliceAngle > Math.PI ? 1 : 0;

      const x1o = cx + outerR * Math.cos(startAngle);
      const y1o = cy + outerR * Math.sin(startAngle);
      const x2o = cx + outerR * Math.cos(endAngle);
      const y2o = cy + outerR * Math.sin(endAngle);
      const x1i = cx + innerR * Math.cos(endAngle);
      const y1i = cy + innerR * Math.sin(endAngle);
      const x2i = cx + innerR * Math.cos(startAngle);
      const y2i = cy + innerR * Math.sin(startAngle);

      const color = PILLAR_DEFS[pn].color;
      const d = `M ${x1o.toFixed(1)} ${y1o.toFixed(1)} A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2o.toFixed(1)} ${y2o.toFixed(1)} L ${x1i.toFixed(1)} ${y1i.toFixed(1)} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x2i.toFixed(1)} ${y2i.toFixed(1)} Z`;
      svg += `<path d="${d}" fill="${color}" opacity="0.85"><title>${this.escapeHtml(pn)}: ${v}pts (${Math.round(v / grandTotal * 100)}%)</title></path>`;
      startAngle = endAngle;
    }

    svg += `<text x="${cx}" y="${cy - 6}" text-anchor="middle" fill="var(--vscode-foreground, #ccc)" font-size="26" font-weight="800">${avgPerDay}</text>`;
    svg += `<text x="${cx}" y="${cy + 14}" text-anchor="middle" fill="var(--vscode-descriptionForeground, #888)" font-size="12">avg/day</text>`;
    svg += `</svg>`;

    const legendItems = pillars.map(pn => {
      const v = sums[pn];
      return `<div class="cal-donut-legend-item">
        <span class="cal-donut-legend-dot" style="background:${PILLAR_DEFS[pn].color}"></span>
        <span>${pn}</span>
        <span class="cal-donut-legend-pts">${v}</span>
      </div>`;
    }).join("");

    return `
      <div class="cal-donut-panel">
        <div class="cal-donut-container">${svg}</div>
        <div class="cal-donut-legend">${legendItems}</div>
      </div>
    `;
  }

  private renderDayOfWeekHeatmap(): string {
    const monthDays = this._getMonthDays();
    if (monthDays.length === 0) return "";

    const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri"];
    const pillars = Object.keys(PILLAR_DEFS);
    const buckets: { total: number; count: number; cats: Record<string, number> }[] =
      Array.from({ length: 5 }, () => ({ total: 0, count: 0, cats: {} }));

    for (const pn of pillars) {
      for (const b of buckets) b.cats[pn] = 0;
    }

    for (const day of monthDays) {
      const dateObj = new Date(day.date + "T12:00:00");
      const wd = dateObj.getDay();
      if (wd === 0 || wd === 6) continue;
      const idx = wd - 1;
      buckets[idx].total += day.total_points;
      buckets[idx].count += 1;
      for (const pn of pillars) {
        buckets[idx].cats[pn] += day.category_points?.[pn] || 0;
      }
    }

    const avgs = buckets.map(b => b.count > 0 ? Math.round(b.total / b.count) : 0);
    const maxAvg = Math.max(...avgs, 1);

    const cells = dayNames.map((name, i) => {
      const avg = avgs[i];
      const count = buckets[i].count;
      const intensity = avg / maxAvg;
      const bgAlpha = (0.08 + intensity * 0.25).toFixed(2);
      const textColor = intensity > 0.6 ? "var(--text-primary)" : "var(--text-secondary)";

      const catMax = Math.max(...pillars.map(pn => buckets[i].cats[pn] || 0), 1);
      const bars = pillars.map(pn => {
        const v = count > 0 ? Math.round(buckets[i].cats[pn] / count) : 0;
        return `<div class="cal-dow-bar" style="height:${Math.round((v / catMax) * 14)}px; background:${PILLAR_DEFS[pn].color};" title="${this.escapeHtml(pn)}: ${v}"></div>`;
      }).join("");

      return `
        <div class="cal-dow-cell" style="background:rgba(255,255,255,${bgAlpha}); color:${textColor};">
          <span class="cal-dow-label">${name}</span>
          <span class="cal-dow-value">${avg}</span>
          <span class="cal-dow-sub" style="color:var(--text-secondary);">${count} day${count !== 1 ? "s" : ""}</span>
          <div class="cal-dow-bars">${bars}</div>
        </div>
      `;
    }).join("");

    return `
      <div class="cal-dow-strip">${cells}</div>
    `;
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
              parts.push(`<a class="perf-issue-link perf-lineage-anstrat" href="#" data-action="openIssue" data-key="${this.escapeHtml(lin.anstrat.key)}" title="${this.safeText(lin.anstrat.summary)}">${this.escapeHtml(lin.anstrat.key)}</a>`);
            }
            if (lin.epic) {
              parts.push(`<a class="perf-issue-link perf-lineage-epic" href="#" data-action="openIssue" data-key="${this.escapeHtml(lin.epic.key)}" title="${this.safeText(lin.epic.summary)}">${this.escapeHtml(lin.epic.key)}</a>`);
            }
            parts.push(`<a class="perf-issue-link" href="#" data-action="openIssue" data-key="${this.escapeHtml(lin.key)}" title="${this.safeText(lin.summary)}">${this.escapeHtml(lin.key)}</a>`);
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
            <div class="perf-day-event-title">${this.safeText(ev.title)}</div>
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

  private getMaxPoints(hierarchy: IssueHierarchy): number {
    let max = 0;
    const walk = (nodes: IssueNode[]) => {
      for (const n of nodes) {
        if (n.points > max) max = n.points;
        if (n.children) walk(n.children);
      }
    };
    walk(hierarchy.strategies || []);
    walk(hierarchy.unattached_epics || []);
    walk(hierarchy.uncategorized || []);
    return max || 1;
  }

  private getTagCategory(tag: string): string {
    const map: Record<string, string> = {
      feat: "worktype", fix: "worktype", refactor: "worktype",
      test: "quality", review: "quality", docs: "quality",
      billing: "domain", auth: "domain", api: "domain", config: "domain", mock: "domain",
      deploy: "ops", pipeline: "ops", "ci/cd": "ops", release: "ops",
      grafana: "monitoring", monitoring: "monitoring", alert: "monitoring",
      security: "monitoring", performance: "monitoring",
      migration: "ops", integration: "domain",
    };
    return map[tag] || "other";
  }

  private renderIssueHierarchy(): string {
    const h = this.state.issue_hierarchy;
    if (!h || !h.total_issues) {
      return this.getEmptyStateHtml("--", "No issue data captured yet. Run daily collection to start tracking.");
    }

    const strategies = Array.isArray(h.strategies) ? h.strategies : [];
    const unattachedEpics = Array.isArray(h.unattached_epics) ? h.unattached_epics : [];
    const uncategorized = Array.isArray(h.uncategorized) ? h.uncategorized : [];
    const maxPts = this.getMaxPoints(h);

    const cacheNote = h.cached
      ? `<div class="perf-hierarchy-note">Using cached hierarchy. Click "Refresh from Jira" for live data.</div>`
      : "";

    let html = `<div class="perf-hierarchy">${cacheNote}`;

    // Card-based layout: one card per strategy
    for (const strat of strategies) {
      const stratPts = strat.points || 0;
      const childCount = this.countDescendants(strat);
      const barColor = this.getHeatColor(maxPts > 0 ? Math.round((stratPts / maxPts) * 100) : 0);
      const allStratTags = this.collectAllTags(strat);
      html += `
        <div class="issue-card" data-key="${this.escapeHtml(strat.key)}" data-tags="${this.escapeHtml(allStratTags.join(","))}">
          <div class="issue-card-header">
            <span class="perf-tree-toggle" data-action="toggleNode" data-key="${this.escapeHtml(strat.key)}">&#9654;</span>
            <span class="issue-card-icon">\u{1F3AF}</span>
            <span class="issue-card-key">${this.renderIssueLink(strat.key)}</span>
            <span class="issue-card-summary">${this.safeText(strat.summary || "")}</span>
          </div>
          <div class="issue-card-stats">
            <span class="issue-card-stat">
              <span class="issue-card-stat-value" style="color:${barColor}">${stratPts}</span>
              <span class="issue-card-stat-label">points</span>
            </span>
            <span class="issue-card-stat">
              <span class="issue-card-stat-value">${childCount}</span>
              <span class="issue-card-stat-label">issues</span>
            </span>
            <span class="issue-card-stat">
              <span class="issue-card-stat-value">${strat.event_count || 0}</span>
              <span class="issue-card-stat-label">events</span>
            </span>
            <span class="issue-card-bar-wrap">
              <span class="issue-card-bar" style="width:${maxPts > 0 ? Math.max(Math.round((stratPts / maxPts) * 100), 4) : 4}%;background:${barColor};"></span>
            </span>
          </div>
          ${this.renderCardTags(strat)}
          <div class="perf-tree-children" data-parent="${this.escapeHtml(strat.key)}">
            ${(strat.children || []).map((child: IssueNode) => {
              const childChildren = Array.isArray(child.children) ? child.children : [];
              const childType = childChildren.length > 0 ? "epic" : "issue";
              return this.renderTreeNode(child, 1, childType, maxPts);
            }).join("")}
          </div>
        </div>`;
    }

    // Unaligned Work card - epics and issues not linked to any strategy
    const unalignedItems = [...unattachedEpics, ...uncategorized];
    if (unalignedItems.length > 0) {
      const unalignedPts = unalignedItems.reduce((sum, n) => sum + (n.points || 0), 0);
      const unalignedEvents = unalignedItems.reduce((sum, n) => sum + (n.event_count || 0), 0);
      html += `
        <div class="issue-card issue-card-unaligned" data-tags="${this.escapeHtml(unalignedItems.flatMap(n => n.keywords || []).join(","))}">
          <div class="issue-card-header">
            <span class="perf-tree-toggle" data-action="toggleNode" data-key="__unaligned__">&#9654;</span>
            <span class="issue-card-icon">\u{1F4CB}</span>
            <span class="issue-card-summary">Unaligned Work <span class="text-muted-sm">(not linked to a strategy)</span></span>
          </div>
          <div class="issue-card-stats">
            <span class="issue-card-stat">
              <span class="issue-card-stat-value">${unalignedPts}</span>
              <span class="issue-card-stat-label">points</span>
            </span>
            <span class="issue-card-stat">
              <span class="issue-card-stat-value">${unalignedItems.length}</span>
              <span class="issue-card-stat-label">issues</span>
            </span>
            <span class="issue-card-stat">
              <span class="issue-card-stat-value">${unalignedEvents}</span>
              <span class="issue-card-stat-label">events</span>
            </span>
          </div>
          <div class="perf-tree-children" data-parent="__unaligned__">`;
      for (const epic of unattachedEpics) {
        html += this.renderTreeNode(epic, 1, "epic", maxPts);
      }
      for (const issue of uncategorized) {
        html += this.renderTreeNode(issue, 1, "issue", maxPts);
      }
      html += `
          </div>
        </div>`;
    }

    html += `</div>`;
    return html;
  }

  private countDescendants(node: IssueNode): number {
    let count = 0;
    const walk = (n: IssueNode) => {
      if (n.children) {
        for (const c of n.children) {
          count++;
          walk(c);
        }
      }
    };
    walk(node);
    return count;
  }

  private renderCardTags(node: IssueNode): string {
    const allTags: Record<string, number> = {};
    const walk = (n: IssueNode) => {
      for (const k of (n.keywords || [])) {
        allTags[k] = (allTags[k] || 0) + 1;
      }
      if (n.children) n.children.forEach(walk);
    };
    walk(node);
    const sorted = Object.entries(allTags).sort((a, b) => b[1] - a[1]);
    if (sorted.length === 0) return "";
    return `<div class="issue-card-tags">${sorted.slice(0, 8).map(([tag]) => {
      const cat = this.getTagCategory(tag);
      return `<span class="perf-issue-tag perf-tag-${cat}">${this.escapeHtml(tag)}</span>`;
    }).join("")}</div>`;
  }

  private collectAllTags(node: IssueNode): string[] {
    const tags = new Set<string>();
    const walk = (n: IssueNode) => {
      for (const k of (n.keywords || [])) tags.add(k);
      if (n.children) n.children.forEach(walk);
    };
    walk(node);
    return [...tags];
  }

  private renderTreeNode(node: IssueNode, depth: number, nodeType: string, maxPts: number): string {
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

    // Color-coded tags by category
    const keywords = node.keywords && node.keywords.length > 0
      ? `<div class="perf-issue-tags">${node.keywords.map((k) => {
          const cat = this.getTagCategory(k);
          return `<span class="perf-issue-tag perf-tag-${cat}" data-tag="${this.escapeHtml(k)}">${this.escapeHtml(k)}</span>`;
        }).join("")}</div>`
      : "";

    const summary = node.summary
      ? `<span class="perf-tree-summary">${this.safeText(node.summary)}</span>`
      : "";

    // Points bar - proportional width, color by score band
    const pct = maxPts > 0 ? Math.round((node.points / maxPts) * 100) : 0;
    const barColor = pct >= 80 ? "var(--success)" : pct >= 50 ? "var(--warning)" : pct >= 25 ? "#f97316" : "var(--error)";
    const pointsBar = `
      <span class="perf-tree-points-wrap">
        <span class="perf-tree-points-bar" style="width: ${Math.max(pct, 4)}%; background: ${barColor};"></span>
        <span class="perf-tree-points-label">${node.points}pts</span>
      </span>`;

    // Strategy alignment badge
    const aligned = node.strategy_aligned;
    const stratNames = (node.strategy_names || []).join(", ");
    const stratBadge = aligned
      ? `<span class="perf-strat-aligned" title="${this.escapeHtml(stratNames || "Strategy aligned")}">&#9632;</span>`
      : `<span class="perf-strat-unaligned" title="Not strategy-aligned">&#9633;</span>`;

    // Pillar micro-bars (only if node has meaningful points)
    const pp = node.pillar_points || { technical: 0, leadership: 0, mentorship: 0, delivery: 0 };
    const pillarTotal = pp.technical + pp.leadership + pp.mentorship + pp.delivery;
    let pillarBar = "";
    if (pillarTotal > 0) {
      const techPct = Math.round((pp.technical / pillarTotal) * 100);
      const leadPct = Math.round((pp.leadership / pillarTotal) * 100);
      const mentPct = Math.round((pp.mentorship / pillarTotal) * 100);
      const delPct = 100 - techPct - leadPct - mentPct;
      pillarBar = `
        <div class="perf-pillar-microbar" title="Tech: ${pp.technical} | Lead: ${pp.leadership} | Ment: ${pp.mentorship} | E2E: ${pp.delivery}">
          <span class="perf-pillar-seg perf-pillar-tech" style="width:${techPct}%"></span>
          <span class="perf-pillar-seg perf-pillar-lead" style="width:${leadPct}%"></span>
          <span class="perf-pillar-seg perf-pillar-ment" style="width:${mentPct}%"></span>
          <span class="perf-pillar-seg perf-pillar-del" style="width:${delPct}%"></span>
        </div>`;
    }

    let html = `
      <div class="perf-tree-node depth-${depth}" style="padding-left: ${indent}px;" data-key="${this.escapeHtml(node.key)}" data-tags="${this.escapeHtml((node.keywords || []).join(","))}">
        <div class="perf-tree-node-header">
          ${toggle}
          <span class="perf-tree-icon">${typeIcon}</span>
          ${stratBadge}
          <span class="${badge}">${this.renderIssueLink(node.key)}</span>
          ${summary}
          ${pointsBar}
          <span class="perf-tree-count">${node.event_count || ""}ev</span>
        </div>
        ${pillarBar}
        ${keywords}
      </div>
    `;

    if (hasChildren) {
      html += `<div class="perf-tree-children" data-parent="${this.escapeHtml(node.key)}">`;
      for (const child of children) {
        const childChildren = Array.isArray(child.children) ? child.children : [];
        const childType = childChildren.length > 0 ? "epic" : "issue";
        html += this.renderTreeNode(child, depth + 1, childType, maxPts);
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
    const overallPct = this.getEffectiveOverall() || 0;
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

        nodes.push({
          id: eId,
          label: epic.key.replace(/^AAP-/, ""),
          fullKey: epic.key,
          summary: epic.summary,
          type: "epic",
          points: epic.points,
          size: Math.min(Math.max(epic.points / 8, 10), 18),
          color: fallbackEpicColor,
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

      // Recolor issue nodes with pillar associations (ANSTRATs/Epics keep fixed colors per legend)
      for (const n of nodes) {
        if (n.pillars && n.pillars.length > 0 && n.pillars.length < allPillarIds.length) {
          const primaryPillarHex = pillarIdToHex[n.pillars[0]] || "#888";
          if (n.type === "task" || n.type === "bug" || n.type === "story") n.color = pillarTint(primaryPillarHex, "issue");
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

    // ---- Sender nodes (derived from passive signals, not Jira assignee) ----
    let ownerCount = 0;
    const senderSummariesGraph = alignment?.sender_relationships?.sender_summaries || {};
    const senderRelationships = alignment?.sender_relationships?.relationships || [];
    const ownerColor = "#e0e0e0";
    const anstratNodeMap = new Map(nodes.filter(n => n.type === "anstrat").map(n => [n.fullKey, n.id]));

    // Build email→display name lookup from priorities for secondary matching
    const emailToDisplay = new Map<string, string>();
    const displayToEmail = new Map<string, string>();
    for (const [email] of Object.entries(senderSummariesGraph)) {
      const dn = email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
      emailToDisplay.set(email, dn);
      displayToEmail.set(dn, email);
    }

    // Secondary matching: sender → priority → issue_keys → ANSTRAT nodes
    const emailToAnstratViaStrategy = new Map<string, Set<string>>();
    if (alignment?.priorities) {
      for (const priority of alignment.priorities) {
        const senderNames: string[] = (priority as any).sender_names || priority.owner_names || [];
        const prioIssueKeys = priority.issue_keys || [];
        const prioAnstratNodeIds: string[] = [];
        for (const k of prioIssueKeys) {
          const nid = anstratNodeMap.get(k);
          if (nid) prioAnstratNodeIds.push(nid);
        }
        if (prioAnstratNodeIds.length === 0) continue;
        for (const sn of senderNames) {
          const email = displayToEmail.get(sn) || sn;
          if (!emailToAnstratViaStrategy.has(email)) emailToAnstratViaStrategy.set(email, new Set());
          for (const nid of prioAnstratNodeIds) emailToAnstratViaStrategy.get(email)!.add(nid);
        }
      }
    }

    for (const [email, summary] of Object.entries(senderSummariesGraph)) {
      const senderAnstrats = senderRelationships
        .filter(r => r.sender === email)
        .map(r => r.anstrat_key);
      const linkedAnstratIds: string[] = [];
      for (const key of senderAnstrats) {
        const nodeId = anstratNodeMap.get(key);
        if (nodeId && !linkedAnstratIds.includes(nodeId)) linkedAnstratIds.push(nodeId);
      }
      // Also include matches found via strategy priorities
      const strategyLinked = emailToAnstratViaStrategy.get(email);
      if (strategyLinked) {
        for (const nid of strategyLinked) {
          if (!linkedAnstratIds.includes(nid)) linkedAnstratIds.push(nid);
        }
      }

      ownerCount++;
      const ownerId = `owner_${email.replace(/[^a-z0-9]/gi, "_")}`;
      const displayName = emailToDisplay.get(email) || email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());

      const ownerPillars = new Set<string>();
      for (const anId of linkedAnstratIds) {
        const anNode = nodes.find(n => n.id === anId);
        if (anNode?.pillars) {
          for (const p of anNode.pillars) ownerPillars.add(p);
        }
      }

      nodes.push({
        id: ownerId,
        label: displayName,
        email,
        type: "owner",
        size: 18,
        color: ownerColor,
        issueCount: (summary as SenderSummary).anstrat_count || senderAnstrats.length,
        linkedCount: linkedAnstratIds.length,
        themes: ((summary as SenderSummary).top_themes || []).slice(0, 5),
        pillars: ownerPillars.size > 0 ? Array.from(ownerPillars) : allPillarIds.slice(),
      });

      if (linkedAnstratIds.length > 0) {
        for (const anId of linkedAnstratIds) {
          links.push({
            source: ownerId,
            target: anId,
            type: "owner_anstrat",
            weight: 1,
          });
        }
      } else {
        // No specific ANSTRAT match -- link to root so the node is still visible
        links.push({
          source: ownerId,
          target: rootId,
          type: "owner_anstrat",
          weight: 1,
        });
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
        owners: ownerCount,
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
    if (s.owners) parts.push(`${s.owners} owners`);
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
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="owner" checked /> Owners</label>
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
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-hexagon legend-dot-default" style="background:#e0e0e0"></span>Owner</span>
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
    const overall = this.getEffectiveOverall();

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
      const catValues = cat.competencies.map((c) => this.getEffectivePercentage(c));
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
        const compPct = this.getEffectivePercentage(compId);
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
                    ? `<a href="${this.escapeHtml(ev.url)}" class="perf-event-link">${this.safeText(ev.title)}</a>`
                    : this.safeText(ev.title);
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
      const pct = this.getEffectivePercentage(gap);
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
              ${(gap as any).ai_suggestion ? `<div class="ai-insight-card mt-8">${this.escapeHtml((gap as any).ai_suggestion)}</div>` : `<button class="btn btn-xs mt-4" data-action="getGapCoach" data-competency="${this.escapeHtml(compId)}">AI Coach</button>`}
            </div>
            ${evidence.length > 0 ? `
              <div class="perf-gap-card-evidence">
                <div class="perf-gap-card-subtitle">What you've done so far (${evidence.length}):</div>
                ${evidence.slice(0, 3).map(ev => {
                  const titleHtml = ev.url
                    ? `<a href="${this.escapeHtml(ev.url)}" class="perf-gap-evidence-link">${this.safeText(ev.title)}</a>`
                    : this.safeText(ev.title);
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
            <button class="btn btn-xs btn-primary" data-action="evaluateQuestionLocal" data-question="${this.escapeHtml(q.id)}">Evaluate (Local)</button>
            <button class="btn btn-xs" data-action="evaluate" data-question="${this.escapeHtml(q.id)}">${q.has_summary ? "Re-evaluate (Chat)" : "Evaluate (Chat)"}</button>
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

    const competencyDefs = Object.entries(cfg?.competencies || {}).map(([id, c]) => ({
      id, name: c.name, base_points: c.base_points, category: c.category,
    }));

    const helpData = JSON.stringify({
      level, levelName, scopeMultipliers, scopeLabels, roleWeightsAll, pillarWeightsAll,
      levelScales, levelSummaries, baseTarget, minSignals, dailyCap,
      pillarColors: Object.fromEntries(Object.entries(PILLAR_DEFS).map(([k, v]) => [k, v.color])),
      competencyData, competencyDefs,
    });

    return `
      <div class="perf-tab-panel perf-help">
        <script id="perfHelpData" type="application/json">${helpData}</script>

        <!-- Ask AI -->
        <div class="section">
          <div class="section-title">Ask AI <span class="ai-badge">AI</span></div>
          <div class="ai-ask-container">
            <input type="text" class="ai-ask-input" id="aiAskInput" placeholder="Ask about scoring, e.g. 'Why is my leadership score low?'" />
            <button class="btn btn-sm btn-primary" data-action="askAI">Ask</button>
          </div>
          <div id="aiAnswerContainer"></div>
        </div>

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
            <p class="text-secondary text-sm">Higher-scope work earns proportionally more points. The scope multiplier is determined by where an event sits in the Jira hierarchy. Google Drive and Calendar events use filename/title classification to infer scope.</p>
            <div id="perf-help-pyramid" class="perf-help-diagram perf-help-pyramid-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-gradient"></span>Higher scope = more points</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-strategy-bonus"></span>Strategy Alignment Bonus (1.5x)</span>
            </div>
          </div>

          <!-- 1.3 Interactive Scoring DAG -->
          <div class="section perf-help-section">
            <div class="section-title">Scoring Formula</div>
            <p class="text-secondary text-sm">Interactive graph showing how each event is scored. Adjust the controls to see how vertices change the scoring path. Level: <strong>${this.escapeHtml(levelName)}</strong>.</p>
            <div class="dag-controls">
              <div class="dag-control-group">
                <label class="dag-control-label">Competency</label>
                <select id="dag-comp" class="perf-help-select">
                  ${Object.entries(cfg?.competencies || {}).map(([id, c]) =>
                    `<option value="${id}" data-base="${c.base_points}" data-category="${this.escapeHtml(c.category)}">${this.escapeHtml(c.name)} (${c.base_points})</option>`
                  ).join("")}
                </select>
              </div>
              <div class="dag-control-group">
                <label class="dag-control-label">Scope</label>
                <select id="dag-scope" class="perf-help-select">
                  ${Object.entries(scopeMultipliers).map(([s, m]) =>
                    `<option value="${s}" ${s === "epic" ? "selected" : ""}>x${m} ${this.escapeHtml(scopeLabels[s] || s)}</option>`
                  ).join("")}
                </select>
              </div>
              <div class="dag-control-group">
                <label class="dag-control-label">Role</label>
                <select id="dag-role" class="perf-help-select">
                  <option value="reporter">Reporter</option>
                  <option value="assignee" selected>Assignee</option>
                  <option value="contributor">Contributor</option>
                </select>
              </div>
              <div class="dag-control-group">
                <label class="dag-control-label">Strategy</label>
                <select id="dag-strat" class="perf-help-select">
                  <option value="0">Not aligned</option>
                  <option value="1">Aligned (1.5x)</option>
                </select>
              </div>
              <div class="dag-control-group">
                <label class="dag-control-label">Signals</label>
                <input type="range" id="dag-signals" min="0" max="7" value="3" class="dag-slider" />
                <span id="dag-signals-val" class="dag-slider-val">3</span>
              </div>
            </div>
            <div id="perf-help-dag" class="perf-help-diagram dag-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot" style="background:#60a5fa"></span>Input</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot" style="background:#a78bfa"></span>Multiplier</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot" style="background:#f59e0b"></span>Gate</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot" style="background:#10b981"></span>Output</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot" style="background:#ef4444"></span>Blocked / Capped</span>
            </div>
            <div class="perf-help-formula-details">
              <div class="perf-help-detail-card">
                <strong>Signal Gate</strong>
                <p>An event must generate &ge; ${minSignals} signals to earn any points. Signals: event_type match, phrase matches, keyword matches, NPU classifier bonus, contribution type, cross-team, review decisions. Events are collected from Git, GitLab, GitHub, Jira, Gmail, Google Calendar / Meet attendance, and Google Drive (Docs, Sheets, Slides).</p>
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

          <!-- What-If Calculator replaced by interactive Scoring DAG in section 1.3 -->
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
          } else if (action === 'switchCompView') {
            var viewId = element.getAttribute('data-view') || 'sunburst';
            document.querySelectorAll('.perf-chart-view-btn').forEach(function(btn) {
              btn.classList.toggle('active', btn.getAttribute('data-view') === viewId);
            });
            vscode.postMessage({
              command: 'performanceAction',
              action: 'switchCompView',
              view: viewId
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
            var treeParent = element.closest('.perf-tree-node');
            var cardParent = element.closest('.issue-card');
            if (treeParent) {
              var childrenDiv = treeParent.nextElementSibling;
              if (childrenDiv && childrenDiv.classList.contains('perf-tree-children')) {
                childrenDiv.classList.toggle('collapsed');
                element.classList.toggle('expanded');
              }
            } else if (cardParent) {
              var cardChildren = cardParent.querySelector('.perf-tree-children');
              if (cardChildren) {
                cardChildren.classList.toggle('collapsed');
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
            if (qId) {
              vscode.postMessage({ command: 'performanceAction', action: 'removeQuestion', questionId: qId });
            }
          } else if (action === 'clearDrafts') {
            vscode.postMessage({ command: 'performanceAction', action: 'clearDrafts' });
          } else if (action === 'askAI') {
            var aiInput = document.getElementById('aiAskInput');
            var aiQuestion = aiInput ? aiInput.value.trim() : '';
            if (aiQuestion) {
              vscode.postMessage({ command: 'performanceAction', action: 'askAI', question: aiQuestion });
            }
          } else if (action === 'getGapCoach') {
            var compId = element.getAttribute('data-competency');
            if (compId) {
              vscode.postMessage({ command: 'performanceAction', action: 'getGapCoach', competencyId: compId });
            }
          } else if (action === 'explainScore') {
            var compId2 = element.getAttribute('data-competency');
            if (compId2) {
              vscode.postMessage({ command: 'performanceAction', action: 'explainScore', competencyId: compId2 });
            }
          } else if (action === 'startFilteredBackfill') {
            var git = document.getElementById('bfSrcGit');
            var jira = document.getElementById('bfSrcJira');
            var gitlab = document.getElementById('bfSrcGitlab');
            var github = document.getElementById('bfSrcGithub');
            var gdrive = document.getElementById('bfSrcGdrive');
            var meeting = document.getElementById('bfSrcMeeting');
            var scopeUser = document.getElementById('bfScopeUser');
            var scopePeers = document.getElementById('bfScopePeers');
            var scopeEmails = document.getElementById('bfScopeEmails');
            var drSel = document.getElementById('bfDateRange');
            vscode.postMessage({
              command: 'performanceAction',
              action: 'startFilteredBackfill',
              srcGit: git ? git.checked : true,
              srcJira: jira ? jira.checked : true,
              srcGitlab: gitlab ? gitlab.checked : true,
              srcGithub: github ? github.checked : true,
              srcGdrive: gdrive ? gdrive.checked : true,
              srcMeeting: meeting ? meeting.checked : true,
              scopeUser: scopeUser ? scopeUser.checked : true,
              scopePeers: scopePeers ? scopePeers.checked : true,
              scopeEmails: scopeEmails ? scopeEmails.checked : true,
              dateRange: drSel ? drSel.value : 'full'
            });
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
          if (checkedTypes.has('owner')) visibleTypes.add('owner');
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
            } else if (d.type === 'owner') {
              visible = visibleTypes.has('owner');
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
              .style('opacity', visible ? 1 : 0.06)
              .style('pointer-events', visible ? 'auto' : 'none');
          });

          perfMmState.linkSelection.each(function(d) {
            var src = typeof d.source === 'object' ? d.source : null;
            var tgt = typeof d.target === 'object' ? d.target : null;
            var visible = (!src || src._visible !== false) && (!tgt || tgt._visible !== false);
            d3.select(this).style('opacity', visible ? 1 : 0.03);
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
                if (d.type === 'owner') return -200 * ratio;
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
                if (d.type === 'owner_anstrat') return 100 * ratio;
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
            } else if (d.type === 'owner') {
              html = '<strong>' + escapeHtml(d.label) + '</strong>';
              html += ' <span class="perf-mm-tt-type" style="background:#e0e0e0">Owner</span>';
              if (d.email) html += '<div class="perf-mm-tt-meta">' + escapeHtml(d.email) + '</div>';
              html += '<div class="perf-mm-tt-meta">' + d.issueCount + ' ANSTRAT issues &middot; ' + d.linkedCount + ' linked</div>';
              if (d.themes && d.themes.length) html += '<div class="perf-mm-tt-summary">Themes: ' + d.themes.map(escapeHtml).join(', ') + '</div>';
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
                if (d.type === 'owner_anstrat') return 100;
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
                if (d.type === 'owner_anstrat') return 0.5;
                if (d.type === 'pillar_strategy') return 0.35;
                return 0.45;
              }))
            .force('charge', d3.forceManyBody().strength(function(d) {
              if (d.type === 'root') return -800;
              if (d.type === 'pillar') return -600;
              if (d.type === 'competency') return -120;
              if (d.type === 'anstrat') return -180;
              if (d.type === 'owner') return -200;
              if (d.type === 'epic') return -80;
              if (d.type === 'strategy') return -60;
              return -30;
            }))
            .force('radial_pillar', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }))
            .force('radial_comp', d3.forceRadial(360, cx, cy).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }))
            .force('radial_anstrat', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }))
            .force('radial_owner', d3.forceRadial(180, cx, cy).strength(function(d) { return d.type === 'owner' ? 0.2 : 0; }))
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
              if (d.type === 'owner_anstrat') return 'perf-mm-link perf-mm-link--owner-anstrat';
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
              if (d.type === 'owner_anstrat') return '#e0e0e0';
              if (d.type === 'pillar_strategy') return src ? (src.color || '#888') : '#888';
              return src ? (src.color || '#555') : '#555';
            })
            .attr('stroke-opacity', function(d) {
              if (d.type === 'evidence') return 0.4;
              if (d.type === 'comp_anstrat') return 0.7;
              if (d.type === 'anstrat_strategy') return 0.7;
              if (d.type === 'owner_anstrat') return 0.6;
              if (d.type === 'pillar_strategy') return 0.55;
              return 0.3;
            })
            .attr('stroke-width', function(d) {
              if (d.type === 'evidence') return Math.min((d.weight || 1) * 1.2, 4);
              if (d.type === 'comp_anstrat') return Math.min((d.weight || 1) + 1.5, 4);
              if (d.type === 'anstrat_strategy') return Math.min((d.weight || 1) + 1.5, 4);
              if (d.type === 'owner_anstrat') return 2;
              if (d.type === 'pillar_strategy') return 2.5;
              var src = typeof d.source === 'object' ? d.source : null;
              if (src && src.type === 'root') return 3;
              if (src && src.type === 'pillar') return 2;
              if (src && src.type === 'anstrat') return 1.8;
              return 1;
            })
            .attr('stroke-dasharray', function(d) {
              if (d.type === 'evidence') return '6,4';
              if (d.type === 'owner_anstrat') return '4,3';
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

          // Owner hexagons
          node.filter(function(d) { return d.type === 'owner'; })
            .append('polygon').attr('class', 'perf-mm-hexagon')
            .attr('points', function(d) {
              var s = d.size || 18;
              var pts = [];
              for (var i = 0; i < 6; i++) {
                var angle = (Math.PI / 3) * i - Math.PI / 6;
                pts.push(Math.cos(angle) * s + ',' + Math.sin(angle) * s);
              }
              return pts.join(' ');
            })
            .attr('fill', function(d) { return d.color; })
            .attr('fill-opacity', 0.8)
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.6).toString(); } catch(e) { return '#c084fc'; } })
            .attr('stroke-width', 2);

          // Owner label inside hexagon
          node.filter(function(d) { return d.type === 'owner'; }).append('text')
            .attr('class', 'perf-mm-label perf-mm-label--owner').attr('text-anchor', 'middle')
            .attr('dy', 4).attr('fill', '#1a1a2e').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { var n = d.label || ''; return n.length > 12 ? n.substring(0, 10) + '..' : n; });

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

      // ============ Weighted Competency Mindmap (D3) ============
      (function() {
        var wmState = { simulation: null, svg: null, g: null, zoom: null,
          nodeSelection: null, linkSelection: null, allLinks: null,
          edgeLabelSelection: null };

        function initWeightedMindmap() {
          var dataEl = document.getElementById('wmGraphData');
          var svgEl = document.getElementById('wmSvg');
          if (!dataEl || !svgEl) return;
          if (typeof d3 === 'undefined') { setTimeout(initWeightedMindmap, 500); return; }

          var graphData;
          try {
            graphData = JSON.parse(dataEl.textContent || '');
            if (!graphData || !graphData.nodes) return;
          } catch (e) { return; }

          var container = document.getElementById('wmGraph');
          if (!container) return;

          var width = container.clientWidth || 800;
          var height = container.clientHeight || 600;
          var cx = width / 2, cy = height / 2;

          var svg = d3.select('#wmSvg');
          svg.selectAll('g.wm-root').remove();

          var zoomBehavior = d3.zoom().scaleExtent([0.15, 4])
            .on('zoom', function(event) { rootG.attr('transform', event.transform); });
          svg.call(zoomBehavior);

          var rootG = svg.append('g').attr('class', 'wm-root');
          wmState.svg = svg;
          wmState.g = rootG;
          wmState.zoom = zoomBehavior;

          var nodes = graphData.nodes.map(function(d) { return Object.assign({}, d); });
          var links = graphData.links.map(function(d) { return Object.assign({}, d); });

          // Pre-position nodes radially
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
            } else if (d.type === 'strategy') {
              var sAngle = Math.random() * Math.PI * 2;
              d.x = cx + 450 * Math.cos(sAngle);
              d.y = cy + 450 * Math.sin(sAngle);
            } else if (d.type === 'owner') {
              var oAngle = Math.random() * Math.PI * 2;
              d.x = cx + 300 * Math.cos(oAngle);
              d.y = cy + 300 * Math.sin(oAngle);
            } else {
              d.x = cx + (Math.random() - 0.5) * 700;
              d.y = cy + (Math.random() - 0.5) * 700;
            }
          });

          var simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(function(d) { return d.id; })
              .distance(function(d) {
                if (d.type === 'evidence') return 200;
                if (d.type === 'pillar_strategy') return 160;
                if (d.type === 'owner_anstrat') return 120;
                var src = typeof d.source === 'object' ? d.source : null;
                var tgt = typeof d.target === 'object' ? d.target : null;
                if (src && src.type === 'root') return 220;
                if (src && src.type === 'pillar' && tgt && tgt.type === 'competency') return 160;
                if (src && src.type === 'anstrat') return 70;
                if (tgt && (tgt.type === 'task' || tgt.type === 'bug' || tgt.type === 'story')) return 45;
                return 90;
              })
              .strength(function(d) {
                if (d.type === 'evidence') return 0.15;
                if (d.type === 'owner_anstrat') return 0.25;
                return 0.45;
              }))
            .force('charge', d3.forceManyBody().strength(function(d) {
              if (d.type === 'root') return -800;
              if (d.type === 'pillar') return -600;
              if (d.type === 'competency') return -120;
              if (d.type === 'anstrat') return -180;
              if (d.type === 'epic') return -80;
              if (d.type === 'strategy') return -60;
              if (d.type === 'owner') return -140;
              return -30;
            }))
            .force('radial_pillar', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'pillar' ? 0.85 : 0; }))
            .force('radial_comp', d3.forceRadial(360, cx, cy).strength(function(d) { return d.type === 'competency' ? 0.25 : 0; }))
            .force('radial_anstrat', d3.forceRadial(220, cx, cy).strength(function(d) { return d.type === 'anstrat' ? 0.15 : 0; }))
            .force('radial_strat', d3.forceRadial(450, cx, cy).strength(function(d) { return d.type === 'strategy' ? 0.3 : 0; }))
            .force('radial_owner', d3.forceRadial(300, cx, cy).strength(function(d) { return d.type === 'owner' ? 0.2 : 0; }))
            .force('center_root', d3.forceRadial(0, cx, cy).strength(function(d) { return d.type === 'root' ? 1 : 0; }))
            .force('collision', d3.forceCollide().radius(function(d) {
              if (d.type === 'pillar') return (d.size || 22) + 40;
              if (d.type === 'owner') return (d.size || 18) + 8;
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
          wmState.simulation = simulation;

          // Links
          var link = rootG.append('g').attr('class', 'wm-links').selectAll('line').data(links).enter().append('line')
            .attr('class', function(d) {
              if (d.type === 'evidence') return 'perf-mm-link perf-mm-link--evidence';
              if (d.type === 'pillar_strategy') return 'perf-mm-link perf-mm-link--pillar-strategy';
              if (d.type === 'owner_anstrat') return 'perf-mm-link perf-mm-link--owner';
              return 'perf-mm-link';
            })
            .attr('stroke', function(d) {
              var src = typeof d.source === 'object' ? d.source : null;
              if (d.type === 'evidence') return '#f59e0b';
              if (d.type === 'pillar_strategy') return src ? (src.color || '#888') : '#888';
              if (d.type === 'owner_anstrat') return '#e0e0e0';
              return src ? (src.color || '#555') : '#555';
            })
            .attr('stroke-opacity', function(d) {
              if (d.type === 'evidence') return 0.5;
              if (d.type === 'pillar_strategy') return 0.55;
              if (d.type === 'owner_anstrat') return 0.45;
              return 0.3;
            })
            .attr('stroke-width', function(d) {
              if (d.type === 'evidence') return Math.min((d.weight || 1) * 1.5, 4);
              if (d.type === 'pillar_strategy') return 2.5;
              if (d.type === 'owner_anstrat') return 1.5;
              var src = typeof d.source === 'object' ? d.source : null;
              if (src && src.type === 'root') return 3;
              if (src && src.type === 'pillar') return 2;
              if (src && src.type === 'anstrat') return 1.8;
              return 1;
            })
            .attr('stroke-dasharray', function(d) {
              if (d.type === 'evidence') return '6,4';
              if (d.type === 'pillar_strategy') return '6,3,2,3';
              if (d.type === 'owner_anstrat') return '4,3';
              return 'none';
            });
          wmState.linkSelection = link;
          wmState.allLinks = links;

          // Edge weight labels
          var edgeLabels = rootG.append('g').attr('class', 'wm-edge-labels').selectAll('text')
            .data(links.filter(function(d) { return d.label; })).enter().append('text')
            .attr('class', 'wm-edge-label')
            .attr('text-anchor', 'middle')
            .attr('fill', 'var(--vscode-foreground, #aaa)')
            .attr('font-size', '8px')
            .attr('opacity', 0.7)
            .text(function(d) { return d.label; });
          wmState.edgeLabelSelection = edgeLabels;

          // Nodes
          var node = rootG.append('g').attr('class', 'wm-nodes').selectAll('g').data(nodes).enter().append('g')
            .attr('class', function(d) { return 'perf-mm-node perf-mm-node--' + d.type; })
            .call(d3.drag()
              .on('start', function(event, d) {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x; d.fy = d.y;
              })
              .on('drag', function(event, d) { d.fx = event.x; d.fy = event.y; })
              .on('end', function(event, d) {
                if (!event.active) simulation.alphaTarget(0);
                var stickyEl = document.getElementById('wmSticky');
                if (!(stickyEl && stickyEl.checked)) { d.fx = null; d.fy = null; }
              })
            );

          // Root glow + circle
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('r', function(d) { return (d.size || 30) + 6; })
            .attr('fill', 'none').attr('stroke', '#667eea').attr('stroke-width', 2).attr('stroke-opacity', 0.3);
          node.filter(function(d) { return d.type === 'root'; })
            .append('circle').attr('r', function(d) { return d.size || 30; })
            .attr('fill', '#667eea').attr('stroke', '#8b9cf5').attr('stroke-width', 3);

          // Pillar ring
          node.filter(function(d) { return d.type === 'pillar'; })
            .append('circle').attr('r', function(d) { return d.size || 22; })
            .attr('fill', 'none').attr('stroke', function(d) { return d.color; })
            .attr('stroke-width', 3).attr('stroke-opacity', 0.7);

          // Competency circles
          node.filter(function(d) { return d.type === 'competency'; })
            .append('circle').attr('r', function(d) { return d.size || 10; })
            .attr('fill', function(d) { return d.heatColor || d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.heatColor || d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5);

          // ANSTRAT rounded rects
          node.filter(function(d) { return d.type === 'anstrat'; })
            .append('rect')
            .attr('width', function(d) { return (d.size || 16) * 4; })
            .attr('height', function(d) { return (d.size || 16) * 2.8; })
            .attr('x', function(d) { return -(d.size || 16) * 2; })
            .attr('y', function(d) { return -(d.size || 16) * 1.4; })
            .attr('rx', 5).attr('ry', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1.5).attr('opacity', 0.9);

          // Epic triangles
          node.filter(function(d) { return d.type === 'epic'; })
            .append('polygon')
            .attr('points', function(d) {
              var s = d.size || 10;
              return '0,' + (-s) + ' ' + (s * 0.9) + ',' + (s * 0.7) + ' ' + (-s * 0.9) + ',' + (s * 0.7);
            })
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.4).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 1);

          // Issue squares
          node.filter(function(d) { return d.type === 'task' || d.type === 'bug' || d.type === 'story'; })
            .append('rect')
            .attr('width', function(d) { return (d.size || 6) * 1.6; })
            .attr('height', function(d) { return (d.size || 6) * 1.6; })
            .attr('x', function(d) { return -(d.size || 6) * 0.8; })
            .attr('y', function(d) { return -(d.size || 6) * 0.8; })
            .attr('rx', 2).attr('ry', 2)
            .attr('fill', function(d) { return d.color || '#888'; })
            .attr('fill-opacity', 0.7)
            .attr('stroke', function(d) { try { return d3.color(d.color || '#888').brighter(0.3).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', 0.8);

          // Strategy diamonds
          node.filter(function(d) { return d.type === 'strategy'; })
            .append('polygon')
            .attr('points', function(d) {
              var s = d.size || 12;
              return '0,' + (-s) + ' ' + s + ',0 0,' + s + ' ' + (-s) + ',0';
            })
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.5).toString(); } catch(e) { return '#999'; } })
            .attr('stroke-width', function(d) { return d.isCovered ? 1.5 : 2; })
            .attr('stroke-dasharray', function(d) { return d.isCovered ? 'none' : '4,2'; })
            .attr('opacity', function(d) { return d.isCovered ? 0.9 : 0.65; });

          // Owner hexagons
          node.filter(function(d) { return d.type === 'owner'; })
            .append('polygon').attr('class', 'perf-mm-hexagon')
            .attr('points', function(d) {
              var s = d.size || 18;
              var pts = [];
              for (var i = 0; i < 6; i++) {
                var a = Math.PI / 3 * i - Math.PI / 6;
                pts.push(Math.round(s * Math.cos(a)) + ',' + Math.round(s * Math.sin(a)));
              }
              return pts.join(' ');
            })
            .attr('fill', function(d) { return d.color; })
            .attr('stroke', function(d) { try { return d3.color(d.color).brighter(0.4).toString(); } catch(e) { return '#ccc'; } })
            .attr('stroke-width', 2);
          node.filter(function(d) { return d.type === 'owner'; }).append('text')
            .attr('class', 'perf-mm-label perf-mm-label--owner').attr('text-anchor', 'middle')
            .attr('dy', 4).attr('fill', '#1a1a2e').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { var n = d.label || ''; return n.length > 12 ? n.substring(0, 10) + '..' : n; });

          // Root percentage
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 5)
            .attr('fill', '#fff').attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });
          node.filter(function(d) { return d.type === 'root'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', function(d) { return -d.size - 8; })
            .attr('fill', 'var(--vscode-foreground, #e0e0e0)').attr('font-size', '12px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Pillar labels + pct
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('class', 'perf-mm-label').attr('text-anchor', 'middle')
            .attr('dy', function(d) { return -(d.size || 22) - 8; })
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '11px').attr('font-weight', '600')
            .text(function(d) { return d.label; });
          node.filter(function(d) { return d.type === 'pillar'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 5)
            .attr('fill', function(d) { return d.color; })
            .attr('font-size', '12px').attr('font-weight', '700')
            .text(function(d) { return d.percentage + '%'; });

          // ANSTRAT labels
          node.filter(function(d) { return d.type === 'anstrat'; }).append('text')
            .attr('text-anchor', 'middle').attr('dy', 4)
            .attr('fill', '#fff').attr('font-size', '9px').attr('font-weight', '600')
            .text(function(d) { return d.label; });

          // Weight sublabels (persistent, togglable)
          var sublabelGroup = node.append('text')
            .attr('class', 'wm-sublabel')
            .attr('text-anchor', 'middle')
            .attr('fill', 'var(--vscode-foreground, #aaa)')
            .attr('font-size', '7px')
            .attr('opacity', 0.8)
            .attr('dy', function(d) {
              if (d.type === 'root') return (d.size || 30) + 16;
              if (d.type === 'pillar') return (d.size || 22) + 14;
              if (d.type === 'competency') return (d.size || 10) + 12;
              if (d.type === 'anstrat') return (d.size || 16) * 1.4 + 12;
              if (d.type === 'epic') return (d.size || 10) + 14;
              if (d.type === 'strategy') return (d.size || 12) + 14;
              if (d.type === 'owner') return (d.size || 18) + 14;
              return (d.size || 6) * 0.8 + 12;
            })
            .text(function(d) { return d.sublabel || ''; });

          // Tooltip
          var tooltip = document.getElementById('wmTooltip');
          node.on('mouseenter', function(event, d) {
            if (!tooltip) return;
            var lines = ['<b>' + (d.fullLabel || d.label) + '</b>'];
            if (d.summary) lines.push(d.summary);
            if (d.weightInfo) lines.push('<span class="wm-tooltip-weight">' + d.weightInfo + '</span>');
            if (d.percentage != null) lines.push('Score: ' + d.percentage + '%');
            if (d.points != null) lines.push('Points: ' + d.points);
            if (d.evidenceCount != null) lines.push('Evidence: ' + d.evidenceCount + ' events');
            if (d.type === 'owner') {
              if (d.email) lines.push(d.email);
              if (d.issueCount != null) lines.push('ANSTRATs: ' + d.issueCount);
              if (d.linkedCount != null) lines.push('Linked: ' + d.linkedCount);
              if (d.themes && d.themes.length) lines.push('Themes: ' + d.themes.join(', '));
            }
            tooltip.innerHTML = lines.join('<br>');
            tooltip.style.display = 'block';
            tooltip.style.left = (event.offsetX + 12) + 'px';
            tooltip.style.top = (event.offsetY - 10) + 'px';
          })
          .on('mousemove', function(event) {
            if (tooltip) {
              tooltip.style.left = (event.offsetX + 12) + 'px';
              tooltip.style.top = (event.offsetY - 10) + 'px';
            }
          })
          .on('mouseleave', function() { if (tooltip) tooltip.style.display = 'none'; });

          wmState.nodeSelection = node;

          // Controls
          var labelsEl = document.getElementById('wmLabels');
          var weightsEl = document.getElementById('wmWeights');
          if (labelsEl) {
            labelsEl.addEventListener('change', function() {
              var show = labelsEl.checked;
              node.selectAll('.perf-mm-label').attr('opacity', show ? 1 : 0);
            });
          }
          if (weightsEl) {
            weightsEl.addEventListener('change', function() {
              var show = weightsEl.checked;
              sublabelGroup.attr('opacity', show ? 0.8 : 0);
              edgeLabels.attr('opacity', show ? 0.7 : 0);
            });
          }
          var reheatBtn = document.getElementById('wmReheat');
          if (reheatBtn) {
            reheatBtn.addEventListener('click', function() { simulation.alpha(1).restart(); });
          }
          var fitBtn = document.getElementById('wmFit');
          if (fitBtn) {
            fitBtn.addEventListener('click', function() {
              var bounds = rootG.node().getBBox();
              if (!bounds.width || !bounds.height) return;
              var pad = 40;
              var scaleX = width / (bounds.width + pad * 2);
              var scaleY = height / (bounds.height + pad * 2);
              var scale = Math.min(scaleX, scaleY, 2);
              var tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
              var ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
              svg.transition().duration(500).call(
                zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
              );
            });
          }

          // Pillar & type filter checkboxes (live in sibling header div, not inside #wmGraph)
          var wrapper = container.closest('.perf-wm-d3-wrapper') || document;
          var pillarChks = wrapper.querySelectorAll('.wmPillarChk');
          var typeChks = wrapper.querySelectorAll('.wmTypeChk');
          function applyFilters() {
            var activePillars = {};
            pillarChks.forEach(function(el) { if (el.checked) activePillars[el.getAttribute('data-pillar')] = true; });
            var activeTypes = {};
            typeChks.forEach(function(el) {
              if (el.checked) {
                (el.getAttribute('data-types') || '').split(',').forEach(function(t) { activeTypes[t.trim()] = true; });
              }
            });
            function isNodeHidden(n) {
              if (!n || n.type === 'root') return false;
              if (n.type !== 'pillar' && !activeTypes[n.type]) return true;
              if (n.type === 'owner') return false;
              if (n.pillars && n.pillars.length) {
                return !n.pillars.some(function(p) { return activePillars[p]; });
              }
              return false;
            }
            node.attr('display', function(d) { return isNodeHidden(d) ? 'none' : 'inline'; });
            link.attr('display', function(d) {
              var src = typeof d.source === 'object' ? d.source : null;
              var tgt = typeof d.target === 'object' ? d.target : null;
              return (isNodeHidden(src) || isNodeHidden(tgt)) ? 'none' : 'inline';
            });
          }
          pillarChks.forEach(function(el) { el.addEventListener('change', applyFilters); });
          typeChks.forEach(function(el) { el.addEventListener('change', applyFilters); });

          // Tick
          simulation.on('tick', function() {
            link.attr('x1', function(d) { return d.source.x; }).attr('y1', function(d) { return d.source.y; })
                .attr('x2', function(d) { return d.target.x; }).attr('y2', function(d) { return d.target.y; });
            edgeLabels
              .attr('x', function(d) { return (d.source.x + d.target.x) / 2; })
              .attr('y', function(d) { return (d.source.y + d.target.y) / 2 - 3; });
            node.attr('transform', function(d) { return 'translate(' + d.x + ',' + d.y + ')'; });
          });

          // Auto-fit after settling
          setTimeout(function() {
            var bounds = rootG.node().getBBox();
            if (!bounds.width || !bounds.height) return;
            var pad = 40;
            var scaleX = width / (bounds.width + pad * 2);
            var scaleY = height / (bounds.height + pad * 2);
            var scale = Math.min(scaleX, scaleY, 2);
            var tx = width / 2 - (bounds.x + bounds.width / 2) * scale;
            var ty = height / 2 - (bounds.y + bounds.height / 2) * scale;
            svg.transition().duration(500).call(
              zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale)
            );
          }, 1500);
        }

        window._initWeightedMindmap = initWeightedMindmap;
        setTimeout(initWeightedMindmap, 200);
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
          initScoringDAG(hd);
          initSignalFilter();
          initTraceSelector();
        }

        // 1.1 Pipeline Flow
        function initPipeline() {
          var container = document.getElementById('perf-help-pipeline');
          if (!container || container.querySelector('svg')) return;

          var W = container.clientWidth || 700;
          var H = 410;
          var cx = W / 2;
          var svg = d3.select(container).append('svg').attr('width', W).attr('height', H).attr('viewBox', '0 0 ' + W + ' ' + H);

          svg.append('defs').append('marker').attr('id', 'pipeline-arrow').attr('viewBox', '0 0 10 10')
            .attr('refX', 10).attr('refY', 5).attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#888');

          var srcW = 84, srcH = 38, srcY = 30, srcCount = 7;
          var srcGap = 10;
          var srcTotalW = srcCount * srcW + (srcCount - 1) * srcGap;
          var srcX0 = cx - srcTotalW / 2;

          var enrW = 156, enrH = 34, enrY = 180, enrCount = 4;
          var enrGap = 12;
          var enrTotalW = enrCount * enrW + (enrCount - 1) * enrGap;
          var enrX0 = cx - enrTotalW / 2;

          var ecY = 105, ecW = 280, ecH = 38;
          var sigY = 256, sigW = 280, sigH = 38;
          var fmY = 320, fmW = 192, fmH = 38;
          var capY = 376, capW = 216, capH = 34;

          var sources = ['Git', 'GitLab', 'GitHub', 'Jira', 'Gmail', 'Calendar', 'GDrive'];
          var enrichments = ['Scope Detection', 'Role Detection', 'Classification', 'Strategy Align'];

          var stages = [];
          sources.forEach(function(label, i) {
            stages.push({ label: label, color: '#60a5fa', x: srcX0 + i * (srcW + srcGap), y: srcY, w: srcW, h: srcH });
          });
          stages.push({ label: 'Event Collection', color: '#a78bfa', x: cx - ecW / 2, y: ecY, w: ecW, h: ecH });
          enrichments.forEach(function(label, i) {
            stages.push({ label: label, color: '#a78bfa', x: enrX0 + i * (enrW + enrGap), y: enrY, w: enrW, h: enrH });
          });
          stages.push({ label: 'Signal Counting (>= 2)', color: '#f59e0b', x: cx - sigW / 2, y: sigY, w: sigW, h: sigH });
          stages.push({ label: 'Score Formula', color: '#10b981', x: cx - fmW / 2, y: fmY, w: fmW, h: fmH });
          stages.push({ label: 'Daily Cap (15/comp)', color: '#ef4444', x: cx - capW / 2, y: capY, w: capW, h: capH });

          stages.forEach(function(s) {
            var g = svg.append('g').attr('class', 'perf-help-pipeline-node');
            g.append('rect').attr('x', s.x).attr('y', s.y).attr('width', s.w).attr('height', s.h)
              .attr('rx', 6).attr('fill', s.color + '22').attr('stroke', s.color).attr('stroke-width', 1.5);
            g.append('text').attr('x', s.x + s.w / 2).attr('y', s.y + s.h / 2).text(s.label);
          });

          function bezier(x1, y1, x2, y2) {
            var my = (y1 + y2) / 2;
            return 'M' + x1 + ',' + y1 + ' C' + x1 + ',' + my + ' ' + x2 + ',' + my + ' ' + x2 + ',' + y2;
          }

          var ecLeft = cx - ecW / 2;
          var ecSpanSrc = ecW / (srcCount + 1);
          var ecSpanEnr = ecW / (enrCount + 1);
          var sigLeft = cx - sigW / 2;
          var sigSpanEnr = sigW / (enrCount + 1);

          sources.forEach(function(_label, i) {
            var sx = srcX0 + i * (srcW + srcGap) + srcW / 2;
            var sy = srcY + srcH;
            var tx = ecLeft + (i + 1) * ecSpanSrc;
            var ty = ecY;
            svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(sx, sy, tx, ty));
          });

          enrichments.forEach(function(_label, i) {
            var sx = ecLeft + (i + 1) * ecSpanEnr;
            var sy = ecY + ecH;
            var tx = enrX0 + i * (enrW + enrGap) + enrW / 2;
            var ty = enrY;
            svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(sx, sy, tx, ty));
          });

          enrichments.forEach(function(_label, i) {
            var sx = enrX0 + i * (enrW + enrGap) + enrW / 2;
            var sy = enrY + enrH;
            var tx = sigLeft + (i + 1) * sigSpanEnr;
            var ty = sigY;
            svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(sx, sy, tx, ty));
          });

          svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(cx, sigY + sigH, cx, fmY));
          svg.append('path').attr('class', 'perf-help-pipeline-edge').attr('d', bezier(cx, fmY + fmH, cx, capY));
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
            var widthPct = 24 + (tiers.length - 1 - i) * 12;
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

          var size = 600, cx = size/2, cy = size/2, R = 220;
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

            var lx = cx + (R + 40) * Math.cos(angle);
            var ly = cy + (R + 40) * Math.sin(angle);
            svg.append('text').attr('x', lx).attr('y', ly)
              .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
              .attr('font-size', '14px').attr('font-weight', '600').attr('fill', hd.pillarColors[p] || '#888')
              .text(p);
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
            svg.append('circle').attr('cx', px).attr('cy', py).attr('r', 5)
              .attr('fill', hd.pillarColors[p] || '#888');
            svg.append('text').attr('x', px).attr('y', py - 14)
              .attr('text-anchor', 'middle').attr('font-size', '14px').attr('font-weight', 'bold')
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

          var size = 600, cx = size / 2, cy = size / 2, R = 220;
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

            var lx = cx + (R + 40) * Math.cos(angle);
            var ly = cy + (R + 40) * Math.sin(angle);
            svg.append('text').attr('x', lx).attr('y', ly)
              .attr('text-anchor', 'middle').attr('dominant-baseline', 'middle')
              .attr('font-size', '14px').attr('font-weight', '600').attr('fill', hd.pillarColors[p] || '#888')
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
              .attr('x', cx + r1 * Math.cos(angle)).attr('y', cy + r1 * Math.sin(angle) - 14)
              .attr('text-anchor', 'middle').attr('font-size', '14px').attr('font-weight', 'bold')
              .attr('fill', 'var(--rh-red, #ee0000)').text(myPw[p] || 0);

            var r2 = R * ((cmpPw[p] || 0) / maxW);
            svg.append('circle')
              .attr('cx', cx + r2 * Math.cos(angle)).attr('cy', cy + r2 * Math.sin(angle))
              .attr('r', 3).attr('fill', '#888').attr('stroke', '#fff').attr('stroke-width', 0.5);
          });

          svg.append('text').attr('x', 8).attr('y', size - 8)
            .attr('font-size', '13px').attr('fill', 'var(--rh-red, #ee0000)')
            .text('\u25CF ' + myLevel.toUpperCase());
          svg.append('text').attr('x', 8).attr('y', size - 26)
            .attr('font-size', '13px').attr('fill', '#888')
            .text('\u25CB ' + cmpLevel.toUpperCase() + ' (dashed)');
        }

        // 3.2 Treemap
        function initTreemap(hd) {
          var container = document.getElementById('perf-help-treemap');
          if (!container || container.querySelector('svg') || typeof d3 === 'undefined') return;

          var treeData = { name: 'Score', children: [] };
          var pillarMap = {};
          var comps = hd.competencyData || [];

          comps.forEach(function(c) {
            var cat = c.category || 'Other';
            var pts = c.points || 0;
            if (pts <= 0) pts = 1;
            if (!pillarMap[cat]) pillarMap[cat] = { name: cat, children: [] };
            pillarMap[cat].children.push({ name: c.name || c.id, value: pts });
          });

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
              '<div class="perf-help-level-label perf-help-level-label-wide">' + (label.length > 24 ? label.substring(0,22) + '..' : label) + '</div>' +
              '<div class="perf-help-level-bar-track">' +
                '<div class="perf-help-level-bar-fill" style="width:' + pct + '%;background:' + color + '">' +
                  '<span class="perf-help-level-bar-text">' + pts + '/' + target + ' (' + pct + '%)</span>' +
                '</div>' +
              '</div>';
            container.appendChild(row);
          });
        }

        // 1.3 Interactive Scoring DAG
        function initScoringDAG(hd) {
          var container = document.getElementById('perf-help-dag');
          if (!container || container.querySelector('svg')) return;

          var compSel = document.getElementById('dag-comp');
          var scopeSel = document.getElementById('dag-scope');
          var roleSel = document.getElementById('dag-role');
          var stratSel = document.getElementById('dag-strat');
          var sigSlider = document.getElementById('dag-signals');
          var sigVal = document.getElementById('dag-signals-val');
          if (!compSel || !scopeSel || !roleSel || !stratSel || !sigSlider) return;

          var W = container.clientWidth || 700;
          var H = 320;
          var svg = d3.select(container).append('svg')
            .attr('width', W).attr('height', H)
            .attr('viewBox', '0 0 ' + W + ' ' + H);

          svg.append('defs').append('marker').attr('id', 'dag-arrow')
            .attr('viewBox', '0 0 10 10').attr('refX', 10).attr('refY', 5)
            .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#888');

          svg.append('defs').append('marker').attr('id', 'dag-arrow-green')
            .attr('viewBox', '0 0 10 10').attr('refX', 10).attr('refY', 5)
            .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#10b981');

          svg.append('defs').append('marker').attr('id', 'dag-arrow-red')
            .attr('viewBox', '0 0 10 10').attr('refX', 10).attr('refY', 5)
            .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
            .append('path').attr('d', 'M 0 0 L 10 5 L 0 10 z').attr('fill', '#ef4444');

          var nodeW = 96, nodeH = 52;
          var mainY = H / 2 - nodeH / 2;
          var gatedY = mainY + 90;
          var padL = 10;
          var gap = (W - padL * 2 - nodeW * 8) / 7;
          if (gap < 12) gap = 12;

          function nx(col) { return padL + col * (nodeW + gap); }

          var nodeDefs = [
            { id: 'event',   col: 0, y: mainY,  color: '#60a5fa', label: 'Work Event',    type: 'input' },
            { id: 'gate',    col: 1, y: mainY,  color: '#f59e0b', label: 'Signal Gate',   type: 'gate' },
            { id: 'base',    col: 2, y: mainY,  color: '#60a5fa', label: 'base_points',   type: 'mult' },
            { id: 'scope',   col: 3, y: mainY,  color: '#a78bfa', label: 'scope',         type: 'mult' },
            { id: 'role',    col: 4, y: mainY,  color: '#a78bfa', label: 'role',           type: 'mult' },
            { id: 'pillar',  col: 5, y: mainY,  color: '#a78bfa', label: 'pillar',         type: 'mult' },
            { id: 'strat',   col: 6, y: mainY,  color: '#a78bfa', label: 'strategy',       type: 'mult' },
            { id: 'raw',     col: 7, y: mainY - 30, color: '#10b981', label: 'Raw Score',  type: 'output' },
            { id: 'cap',     col: 7, y: mainY + 30, color: '#10b981', label: 'Final',      type: 'output' },
            { id: 'gated',   col: 2, y: gatedY, color: '#ef4444', label: 'Blocked',        type: 'dead' },
          ];

          var edgeDefs = [
            { from: 'event', to: 'gate',   path: 'main' },
            { from: 'gate',  to: 'base',   path: 'pass' },
            { from: 'gate',  to: 'gated',  path: 'fail' },
            { from: 'base',  to: 'scope',  path: 'pass' },
            { from: 'scope', to: 'role',   path: 'pass' },
            { from: 'role',  to: 'pillar', path: 'pass' },
            { from: 'pillar',to: 'strat',  path: 'pass' },
            { from: 'strat', to: 'raw',    path: 'pass' },
            { from: 'raw',   to: 'cap',    path: 'cap' },
          ];

          function nodeById(id) {
            for (var i = 0; i < nodeDefs.length; i++) {
              if (nodeDefs[i].id === id) return nodeDefs[i];
            }
            return null;
          }

          function edgePath(fromN, toN) {
            var x1 = nx(fromN.col) + nodeW;
            var y1 = fromN.y + nodeH / 2;
            var x2 = nx(toN.col);
            var y2 = toN.y + nodeH / 2;
            if (fromN.col === toN.col) {
              x1 = nx(fromN.col) + nodeW / 2;
              x2 = nx(toN.col) + nodeW / 2;
              y1 = fromN.y + nodeH;
              y2 = toN.y;
            }
            var mx = (x1 + x2) / 2;
            return 'M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' + x2 + ',' + y2;
          }

          var edgeGroup = svg.append('g').attr('class', 'dag-edges');
          var nodeGroup = svg.append('g').attr('class', 'dag-nodes');
          var labelGroup = svg.append('g').attr('class', 'dag-labels');

          var edgeEls = {};
          edgeDefs.forEach(function(e) {
            var fn = nodeById(e.from);
            var tn = nodeById(e.to);
            if (!fn || !tn) return;
            edgeEls[e.from + '-' + e.to] = edgeGroup.append('path')
              .attr('class', 'dag-edge')
              .attr('d', edgePath(fn, tn))
              .attr('fill', 'none')
              .attr('stroke', '#555')
              .attr('stroke-width', 2)
              .attr('marker-end', 'url(#dag-arrow)');
          });

          var nodeEls = {};
          var valueEls = {};
          var labelEls = {};
          nodeDefs.forEach(function(n) {
            var g = nodeGroup.append('g')
              .attr('transform', 'translate(' + nx(n.col) + ',' + n.y + ')');

            nodeEls[n.id] = g.append('rect')
              .attr('width', nodeW).attr('height', nodeH)
              .attr('rx', 8)
              .attr('fill', n.color + '18')
              .attr('stroke', n.color)
              .attr('stroke-width', 2);

            labelEls[n.id] = g.append('text')
              .attr('x', nodeW / 2).attr('y', 18)
              .attr('text-anchor', 'middle')
              .attr('fill', '#ccc')
              .attr('font-size', '11px')
              .attr('font-weight', '600')
              .text(n.label);

            valueEls[n.id] = g.append('text')
              .attr('x', nodeW / 2).attr('y', 38)
              .attr('text-anchor', 'middle')
              .attr('fill', n.color)
              .attr('font-size', '14px')
              .attr('font-weight', '700')
              .text('');
          });

          var edgeLabelEls = {};
          edgeDefs.forEach(function(e) {
            var fn = nodeById(e.from);
            var tn = nodeById(e.to);
            if (!fn || !tn) return;
            var x1 = nx(fn.col) + nodeW;
            var y1 = fn.y + nodeH / 2;
            var x2 = nx(tn.col);
            var y2 = tn.y + nodeH / 2;
            if (fn.col === tn.col) {
              x1 = nx(fn.col) + nodeW / 2;
              x2 = nx(tn.col) + nodeW / 2;
              y1 = fn.y + nodeH;
              y2 = tn.y;
            }
            edgeLabelEls[e.from + '-' + e.to] = labelGroup.append('text')
              .attr('x', (x1 + x2) / 2)
              .attr('y', (y1 + y2) / 2 - 6)
              .attr('text-anchor', 'middle')
              .attr('fill', '#888')
              .attr('font-size', '10px')
              .text('');
          });

          function update() {
            var opt = compSel.options[compSel.selectedIndex];
            var base = parseInt(opt.getAttribute('data-base') || '3', 10);
            var category = opt.getAttribute('data-category') || 'Technical Contribution';
            var scope = scopeSel.value;
            var role = roleSel.value;
            var aligned = stratSel.value === '1';
            var signals = parseInt(sigSlider.value, 10);
            var minSig = hd.minSignals || 2;

            if (sigVal) sigVal.textContent = '' + signals;

            var scopeMult = hd.scopeMultipliers[scope] || 1;
            var rw = hd.roleWeightsAll[hd.level] || {};
            var roleWeight = (rw[scope] || {})[role] || 1.0;
            var pw = hd.pillarWeightsAll[hd.level] || {};
            var pillarWeight = pw[category] || 1.0;
            var stratBonus = aligned ? 1.5 : 1.0;
            var rawScore = Math.round(base * scopeMult * roleWeight * pillarWeight * stratBonus);
            var cap = hd.dailyCap || 15;
            var capped = rawScore > cap;
            var finalScore = Math.min(rawScore, cap);
            var gated = signals < minSig;

            valueEls['event'].text(signals + ' sig');
            valueEls['gate'].text(signals + ' / ' + minSig);
            valueEls['base'].text(gated ? '-' : base);
            valueEls['scope'].text(gated ? '-' : 'x' + scopeMult);
            valueEls['role'].text(gated ? '-' : roleWeight);
            valueEls['pillar'].text(gated ? '-' : pillarWeight);
            valueEls['strat'].text(gated ? '-' : (aligned ? '1.5x' : '1.0x'));
            valueEls['raw'].text(gated ? '-' : rawScore);
            valueEls['cap'].text(gated ? '0' : finalScore);
            valueEls['gated'].text('0 pts');

            edgeLabelEls['gate-base'].text(gated ? '' : 'pass');
            edgeLabelEls['gate-gated'].text(gated ? 'fail' : '');
            edgeLabelEls['base-scope'].text(gated ? '' : 'x' + scopeMult);
            edgeLabelEls['scope-role'].text(gated ? '' : 'x' + roleWeight);
            edgeLabelEls['role-pillar'].text(gated ? '' : 'x' + pillarWeight);
            edgeLabelEls['pillar-strat'].text(gated ? '' : (aligned ? 'x1.5' : 'x1.0'));
            edgeLabelEls['strat-raw'].text(gated ? '' : '= ' + rawScore);
            edgeLabelEls['raw-cap'].text(!gated && capped ? 'cap ' + cap : '');

            var passColor = '#10b981';
            var failColor = '#ef4444';
            var dimColor = '#333';
            var dimStroke = '#444';

            function setEdge(key, color, width, dash, marker) {
              var e = edgeEls[key];
              if (!e) return;
              e.transition().duration(400)
                .attr('stroke', color)
                .attr('stroke-width', width)
                .attr('stroke-dasharray', dash || null)
                .attr('marker-end', 'url(#' + marker + ')');
            }

            function setNode(id, strokeColor, fillOpacity) {
              var n = nodeEls[id];
              if (!n) return;
              var nd = nodeById(id);
              n.transition().duration(400)
                .attr('stroke', strokeColor)
                .attr('fill', strokeColor + (fillOpacity || '18'));
            }

            setEdge('event-gate', gated ? failColor : passColor, 2.5, null, gated ? 'dag-arrow-red' : 'dag-arrow-green');
            setNode('event', '#60a5fa', '18');
            setNode('gate', gated ? failColor : '#f59e0b', '18');

            var passNodes = ['base', 'scope', 'role', 'pillar', 'strat'];
            var passEdges = ['gate-base', 'base-scope', 'scope-role', 'role-pillar', 'pillar-strat', 'strat-raw'];

            passNodes.forEach(function(id) {
              var nd = nodeById(id);
              if (gated) {
                setNode(id, dimStroke, '08');
                valueEls[id].transition().duration(400).attr('fill', dimColor);
              } else {
                setNode(id, nd.color, '18');
                valueEls[id].transition().duration(400).attr('fill', nd.color);
              }
            });

            passEdges.forEach(function(key) {
              if (gated) {
                setEdge(key, dimStroke, 1, '4,3', 'dag-arrow');
              } else {
                setEdge(key, passColor, 2.5, null, 'dag-arrow-green');
              }
            });

            setEdge('gate-gated', gated ? failColor : dimStroke, gated ? 2.5 : 1, gated ? null : '4,3', gated ? 'dag-arrow-red' : 'dag-arrow');
            setNode('gated', gated ? failColor : dimStroke, gated ? '20' : '08');
            valueEls['gated'].transition().duration(400).attr('fill', gated ? failColor : dimColor);
            labelEls['gated'].transition().duration(400).attr('fill', gated ? '#fca5a5' : dimColor);

            if (!gated) {
              setNode('raw', passColor, '18');
              valueEls['raw'].transition().duration(400).attr('fill', passColor);
              setEdge('raw-cap', capped ? '#f59e0b' : passColor, 2, null, capped ? 'dag-arrow' : 'dag-arrow-green');
              setNode('cap', capped ? '#f59e0b' : passColor, capped ? '20' : '18');
              valueEls['cap'].transition().duration(400).attr('fill', capped ? '#f59e0b' : passColor);
            } else {
              setNode('raw', dimStroke, '08');
              setNode('cap', dimStroke, '08');
              valueEls['raw'].transition().duration(400).attr('fill', dimColor);
              valueEls['cap'].transition().duration(400).attr('fill', dimColor);
              setEdge('raw-cap', dimStroke, 1, '4,3', 'dag-arrow');
            }
          }

          update();
          compSel.addEventListener('change', update);
          scopeSel.addEventListener('change', update);
          roleSel.addEventListener('change', update);
          stratSel.addEventListener('change', update);
          sigSlider.addEventListener('input', update);
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
          if (msg && msg.command === 'aiAnswer' && msg.answer) {
            var container = document.getElementById('aiAnswerContainer');
            if (container) {
              container.innerHTML = '<div class="ai-answer-card">' +
                msg.answer.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</div>';
            }
          }
          if (msg && msg.command === 'missingLinksResult' && msg.suggestions) {
            var mlc = document.getElementById('missingLinksContainer');
            if (mlc) {
              var sug = msg.suggestions;
              if (sug.length === 0) {
                mlc.innerHTML = '';
              } else {
                var mlHtml = '<div class="section"><div class="section-title">Suggested Missing Links <span class="ai-badge">AI</span></div>';
                for (var mi = 0; mi < sug.length; mi++) {
                  var s = sug[mi];
                  mlHtml += '<div class="ai-diff-item"><span class="ai-diff-name">' +
                    (s.issue ? s.issue.key : '') + ': ' + (s.issue ? s.issue.summary : '').substring(0, 60) +
                    '</span><span class="text-secondary text-xs"> &rarr; ' +
                    (s.suggested_anstrat ? s.suggested_anstrat.key : '') + ' (' + (s.similarity * 100).toFixed(0) + '% match)</span></div>';
                }
                mlHtml += '</div>';
                mlc.innerHTML = mlHtml;
              }
            }
          }
          if (msg && msg.command === 'peerGrowthData' && msg.data) {
            var gc = document.getElementById('peerGrowthContainer');
            if (gc) {
              var d = msg.data;
              var html = '';
              var levelColors = { se: '#10b981', pse: '#3b82f6', spse: '#8b5cf6', de: '#f59e0b' };
              var levelLabels = { se: 'Senior', pse: 'Principal', spse: 'Sr Principal', de: 'Distinguished' };
              var userSeries = d.user_series || [];
              if (userSeries.length > 0) {
                var maxPts = 1;
                for (var si = 0; si < userSeries.length; si++) {
                  if (userSeries[si].total_points > maxPts) maxPts = userSeries[si].total_points;
                }
                for (var lk in (d.level_series || {})) {
                  var ls = d.level_series[lk];
                  for (var li = 0; li < ls.length; li++) {
                    if (ls[li].total_points > maxPts) maxPts = ls[li].total_points;
                  }
                }
                var w = 400, h = 80;
                var svg = '<svg viewBox="0 0 ' + w + ' ' + h + '" class="peer-sparkline-svg">';
                function toPath(series, color, dashed) {
                  if (!series || series.length < 2) return '';
                  var pts = [];
                  for (var pi = 0; pi < series.length; pi++) {
                    var x = (pi / (series.length - 1)) * w;
                    var y = h - (series[pi].total_points / maxPts) * (h - 5);
                    pts.push(x.toFixed(1) + ',' + y.toFixed(1));
                  }
                  return '<polyline points="' + pts.join(' ') + '" fill="none" stroke="' + color + '" stroke-width="' + (dashed ? '1' : '2') + '"' + (dashed ? ' stroke-dasharray="4,3"' : '') + '/>';
                }
                svg += toPath(userSeries, '#667eea', false);
                for (var lk2 in (d.level_series || {})) {
                  svg += toPath(d.level_series[lk2], levelColors[lk2] || '#888', true);
                }
                svg += '</svg>';
                var legend = '<div class="peer-sparkline-legend"><span class="peer-spark-leg"><span style="background:#667eea" class="peer-spark-dot"></span>You</span>';
                for (var lk3 in (d.level_series || {})) {
                  legend += '<span class="peer-spark-leg"><span style="background:' + (levelColors[lk3] || '#888') + '" class="peer-spark-dot"></span>' + (levelLabels[lk3] || lk3) + '</span>';
                }
                legend += '</div>';
                html = svg + legend;
              } else {
                html = '<div class="text-secondary text-sm">No daily data available for growth trajectory.</div>';
              }
              gc.innerHTML = html;
            }
          }
          if (msg && (msg.command === 'peerBackfillStarted' || msg.command === 'peerBackfillProgress' || msg.command === 'peerBackfillComplete' || msg.command === 'peerBackfillCancelled')) {
            var pbEl = document.getElementById('peerBackfillProgress');
            var pbPct = document.getElementById('peerProgressPct');
            var pbText = document.getElementById('peerProgressText');
            var pbElapsed = document.getElementById('peerProgressElapsed');
            var pbTitle = document.getElementById('peerProgressTitle');
            var cancelBtn = document.getElementById('backfillCancelBtn');
            var allPhaseSegs = document.querySelectorAll('.backfill-phase-segment');
            var allPhaseLabels = document.querySelectorAll('.backfill-phase-labels span');

            function updatePhaseBar(pr) {
              var phases = ['resolve_github', 'prefetch', 'index_gdrive', 'index_meetings', 'collecting', 'benchmarks'];
              var completed = pr.phases_completed || [];
              var current = pr.phase || '';
              allPhaseSegs.forEach(function(seg) {
                var ph = seg.getAttribute('data-phase');
                seg.classList.remove('phase-done', 'phase-active', 'phase-pending');
                if (completed.indexOf(ph) >= 0) {
                  seg.classList.add('phase-done');
                } else if (ph === current) {
                  seg.classList.add('phase-active');
                } else {
                  seg.classList.add('phase-pending');
                }
              });
              allPhaseLabels.forEach(function(lbl) {
                var ph = lbl.getAttribute('data-phase');
                lbl.classList.remove('label-done', 'label-active');
                if (completed.indexOf(ph) >= 0) lbl.classList.add('label-done');
                else if (ph === current) lbl.classList.add('label-active');
              });
            }

            if (pbEl) {
              if (msg.command === 'peerBackfillStarted') {
                pbEl.style.display = 'block';
                pbEl.classList.remove('backfill-complete', 'backfill-cancelled');
                if (pbPct) pbPct.textContent = '0%';
                if (pbText) pbText.textContent = 'Starting backfill...';
                if (pbElapsed) pbElapsed.textContent = '';
                if (cancelBtn) cancelBtn.style.display = 'inline-block';
                allPhaseSegs.forEach(function(s) { s.classList.remove('phase-done', 'phase-active'); s.classList.add('phase-pending'); });
              } else if (msg.command === 'peerBackfillProgress' && msg.progress) {
                pbEl.style.display = 'block';
                var pr = msg.progress;
                var pctVal = (pr.total_peers > 0 && pr.total_days > 0)
                  ? Math.round(((pr.completed_peers * pr.total_days + pr.completed_days) / (pr.total_peers * pr.total_days)) * 100)
                  : 0;
                if (pbPct) pbPct.textContent = Math.min(pctVal, 100) + '%';
                updatePhaseBar(pr);
                if (pbText) {
                  var filterNote = (pr.filter_info && pr.filter_info !== 'all') ? ' [' + pr.filter_info + ']' : '';
                  var txt = '';
                  if (pr.phase === 'collecting' && pr.current_peer) {
                    txt = pr.current_peer;
                    if (pr.current_level) txt += ' (' + pr.current_level.toUpperCase() + ')';
                    txt += ' — ' + pr.completed_peers + '/' + pr.total_peers + ' peers';
                  } else if (pr.phase_detail) {
                    txt = pr.phase_detail;
                  } else if (pr.current_peer) {
                    txt = pr.current_peer;
                  } else {
                    txt = 'Preparing...';
                  }
                  txt += filterNote;
                  pbText.textContent = txt;
                }
                if (pbElapsed && pr.elapsed_seconds > 0) {
                  var m = Math.floor(pr.elapsed_seconds / 60);
                  var s = pr.elapsed_seconds % 60;
                  pbElapsed.textContent = m > 0 ? m + 'm ' + s + 's' : s + 's';
                }
              } else if (msg.command === 'peerBackfillComplete') {
                var pc = msg.progress || {};
                var completeFilter = (pc.filter_info && pc.filter_info !== 'all') ? ' [' + pc.filter_info + ']' : '';
                pbEl.classList.add('backfill-complete');
                if (pbPct) pbPct.textContent = '100%';
                if (cancelBtn) cancelBtn.style.display = 'none';
                updatePhaseBar({ phases_completed: ['resolve_github','prefetch','index_gdrive','index_meetings','collecting','benchmarks'], phase: 'complete' });
                if (pbText) {
                  pbText.textContent = 'Complete: ' +
                    (pc.completed_peers || 0) + ' peers, ' +
                    (pc.total_events || 0) + ' events' + completeFilter;
                }
                if (pbElapsed && pc.elapsed_seconds > 0) {
                  var m2 = Math.floor(pc.elapsed_seconds / 60);
                  var s2 = pc.elapsed_seconds % 60;
                  pbElapsed.textContent = m2 > 0 ? m2 + 'm ' + s2 + 's' : s2 + 's';
                }
                setTimeout(function() { if (pbEl) pbEl.style.display = 'none'; }, 10000);
              } else if (msg.command === 'peerBackfillCancelled') {
                pbEl.classList.add('backfill-cancelled');
                if (pbPct) pbPct.textContent = '--';
                if (cancelBtn) cancelBtn.style.display = 'none';
                if (pbText) pbText.textContent = 'Backfill cancelled';
                setTimeout(function() { if (pbEl) pbEl.style.display = 'none'; }, 5000);
              }
            }
          }
          if (msg && msg.command === 'toggleBackfillOptions') {
            var bfPanel = document.getElementById('backfillOptionsPanel');
            if (bfPanel) bfPanel.style.display = bfPanel.style.display === 'none' ? 'block' : 'none';
          }
          if (msg && msg.command === 'hideBackfillOptions') {
            var bfPanel2 = document.getElementById('backfillOptionsPanel');
            if (bfPanel2) bfPanel2.style.display = 'none';
          }
          if (msg && msg.command === 'aiLogCategory' && msg.category) {
            var catSelect = document.getElementById('activityCategory');
            if (catSelect) {
              for (var i = 0; i < catSelect.options.length; i++) {
                if (catSelect.options[i].value.toLowerCase() === msg.category.toLowerCase()) {
                  catSelect.selectedIndex = i;
                  break;
                }
              }
            }
          }
        });

        window._initPerfHelp = initPerfHelp;
        setTimeout(initPerfHelp, 200);
      })();

      // ============ QC Overview Charts (D3) ============
      (function() {
        function initQcOverviewCharts() {
          var dataEl = document.getElementById('qcOverviewChartData');
          if (!dataEl || typeof d3 === 'undefined') return;
          var data;
          try { data = JSON.parse(dataEl.textContent); } catch(e) { return; }
          if (!data) return;

          _renderTrendChart(data);
          _renderHeatmap(data);
          _renderPillarChart(data);
          _renderCoverageDonut(data);
        }

        var tooltip = null;
        function showTip(evt, html) {
          if (!tooltip) tooltip = document.getElementById('qcTooltip');
          if (!tooltip) return;
          tooltip.innerHTML = html;
          tooltip.style.display = 'block';
          tooltip.style.left = (evt.clientX + 12) + 'px';
          tooltip.style.top = (evt.clientY - 28) + 'px';
        }
        function hideTip() {
          if (!tooltip) tooltip = document.getElementById('qcTooltip');
          if (tooltip) tooltip.style.display = 'none';
        }

        function _renderTrendChart(data) {
          var svg = d3.select('#qcTrendChart');
          if (svg.empty()) return;
          svg.selectAll('*').remove();

          var days = data.captured_days || [];
          if (days.length < 2) {
            svg.append('text').attr('x', '50%').attr('y', '50%')
              .attr('text-anchor', 'middle').attr('fill', 'var(--text-muted)')
              .attr('font-size', '12px').text('Not enough data for trend chart');
            return;
          }

          var margin = { top: 20, right: 40, bottom: 30, left: 50 };
          var node = svg.node();
          var containerW = node.parentElement ? node.parentElement.getBoundingClientRect().width : 0;
          var width = (containerW || node.clientWidth || 600) - margin.left - margin.right;
          var height = 180 - margin.top - margin.bottom;
          svg.attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' 180');
          var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

          var cumulative = [];
          var running = 0;
          for (var i = 0; i < days.length; i++) {
            running += days[i].total_points;
            cumulative.push({ dayIdx: i + 1, value: running, date: days[i].date, pts: days[i].total_points });
          }

          var currentTotal = running;
          var overallPct = data.overall_percentage || 0;
          var totalDays = data.total_weekdays || 65;
          var projectedFinal = data.trend && data.trend.projected_final != null ? data.trend.projected_final : null;
          var trendStatus = data.trend ? data.trend.status : 'insufficient_data';

          var trendColor = trendStatus === 'on_track' ? '#10b981' : trendStatus === 'at_risk' ? '#f59e0b' : '#ef4444';

          var pctData = cumulative.map(function(d) {
            return { dayIdx: d.dayIdx, pct: currentTotal > 0 ? Math.round(overallPct * d.value / currentTotal) : 0, date: d.date, pts: d.pts, raw: d.value };
          });

          var xMax = Math.max(totalDays, cumulative.length + 5);
          var x = d3.scaleLinear().domain([1, xMax]).range([0, width]);
          var yMax = Math.max(100, projectedFinal || overallPct, d3.max(pctData, function(d) { return d.pct; }) || 100);
          var y = d3.scaleLinear().domain([0, Math.min(yMax * 1.1, 120)]).range([height, 0]);

          g.append('g').attr('transform', 'translate(0,' + height + ')')
            .call(d3.axisBottom(x).ticks(Math.min(10, xMax / 5)).tickFormat(function(d) { return 'Day ' + d; }))
            .selectAll('text,line,path').attr('stroke', 'var(--text-muted)').attr('fill', 'var(--text-muted)').attr('font-size', '10px');

          g.append('g')
            .call(d3.axisLeft(y).ticks(5).tickFormat(function(d) { return d + '%'; }))
            .selectAll('text,line,path').attr('stroke', 'var(--text-muted)').attr('fill', 'var(--text-muted)').attr('font-size', '10px');

          g.selectAll('.grid-line').data(y.ticks(5)).enter()
            .append('line')
            .attr('x1', 0).attr('x2', width)
            .attr('y1', function(d) { return y(d); }).attr('y2', function(d) { return y(d); })
            .attr('stroke', 'var(--border)').attr('stroke-dasharray', '2,3').attr('opacity', 0.4);

          [60, 80].forEach(function(threshold) {
            if (threshold <= yMax * 1.1) {
              g.append('line')
                .attr('x1', 0).attr('x2', width)
                .attr('y1', y(threshold)).attr('y2', y(threshold))
                .attr('stroke', threshold === 80 ? '#10b981' : '#f59e0b')
                .attr('stroke-dasharray', '4,4').attr('opacity', 0.35);
              g.append('text').attr('x', width + 4).attr('y', y(threshold) + 3)
                .attr('fill', threshold === 80 ? '#10b981' : '#f59e0b')
                .attr('font-size', '9px').text(threshold + '%');
            }
          });

          var area = d3.area()
            .x(function(d) { return x(d.dayIdx); })
            .y0(height)
            .y1(function(d) { return y(d.pct); })
            .curve(d3.curveMonotoneX);

          g.append('path').datum(pctData)
            .attr('d', area)
            .attr('fill', trendColor).attr('opacity', 0.08);

          var line = d3.line()
            .x(function(d) { return x(d.dayIdx); })
            .y(function(d) { return y(d.pct); })
            .curve(d3.curveMonotoneX);

          g.append('path').datum(pctData)
            .attr('d', line)
            .attr('fill', 'none').attr('stroke', trendColor).attr('stroke-width', 2.5);

          if (projectedFinal != null && pctData.length > 0) {
            var lastPt = pctData[pctData.length - 1];
            g.append('line')
              .attr('x1', x(lastPt.dayIdx)).attr('y1', y(lastPt.pct))
              .attr('x2', x(totalDays)).attr('y2', y(Math.min(projectedFinal, yMax * 1.1)))
              .attr('stroke', trendColor).attr('stroke-width', 2)
              .attr('stroke-dasharray', '6,4').attr('opacity', 0.5);

            g.append('circle')
              .attr('cx', x(totalDays)).attr('cy', y(Math.min(projectedFinal, yMax * 1.1)))
              .attr('r', 4).attr('fill', trendColor).attr('opacity', 0.5);
            g.append('text')
              .attr('x', x(totalDays)).attr('y', y(Math.min(projectedFinal, yMax * 1.1)) - 8)
              .attr('text-anchor', 'middle').attr('fill', trendColor)
              .attr('font-size', '10px').attr('font-weight', '600')
              .text(projectedFinal + '%');
          }

          if (pctData.length > 0) {
            var last = pctData[pctData.length - 1];
            g.append('circle')
              .attr('cx', x(last.dayIdx)).attr('cy', y(last.pct))
              .attr('r', 5).attr('fill', trendColor).attr('stroke', 'var(--bg-secondary)').attr('stroke-width', 2);
            g.append('text')
              .attr('x', x(last.dayIdx) + 8).attr('y', y(last.pct) + 4)
              .attr('fill', trendColor).attr('font-size', '11px').attr('font-weight', '700')
              .text(overallPct + '%');
          }

          var bisect = d3.bisector(function(d) { return d.dayIdx; }).left;
          var focus = g.append('g').style('display', 'none');
          focus.append('circle').attr('r', 4).attr('fill', trendColor).attr('stroke', '#fff').attr('stroke-width', 1.5);
          focus.append('line').attr('class', 'focus-line').attr('y1', 0).attr('stroke', 'var(--text-muted)').attr('stroke-dasharray', '2,2').attr('opacity', 0.4);

          svg.append('rect')
            .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')')
            .attr('width', width).attr('height', height)
            .attr('fill', 'transparent')
            .on('mousemove', function(event) {
              var coords = d3.pointer(event, g.node());
              var xDay = x.invert(coords[0]);
              var idx = bisect(pctData, xDay, 1);
              if (idx >= pctData.length) idx = pctData.length - 1;
              if (idx < 0) idx = 0;
              var d0 = pctData[Math.max(0, idx - 1)], d1 = pctData[idx];
              var d = (d1 && Math.abs(xDay - d0.dayIdx) > Math.abs(xDay - d1.dayIdx)) ? d1 : d0;
              if (!d) return;
              focus.style('display', null);
              focus.attr('transform', 'translate(' + x(d.dayIdx) + ',' + y(d.pct) + ')');
              focus.select('.focus-line').attr('y2', height - y(d.pct));
              showTip(event, '<b>' + d.date + '</b> (Day ' + d.dayIdx + ')<br>' + d.pct + '% &bull; +' + d.pts + ' pts');
            })
            .on('mouseleave', function() { focus.style('display', 'none'); hideTip(); });
        }

        function _renderHeatmap(data) {
          var container = document.getElementById('qcHeatmapStrip');
          if (!container) return;
          container.innerHTML = '';

          var days = data.captured_days || [];
          if (days.length === 0) return;

          var maxPts = d3.max(days, function(d) { return d.total_points; }) || 1;

          var allDates = new Set(days.map(function(d) { return d.date; }));
          var first = days[0].date;
          var last = days[days.length - 1].date;
          var cur = new Date(first);
          var end = new Date(last);
          var allWeekdays = [];
          while (cur <= end) {
            var dow = cur.getDay();
            if (dow !== 0 && dow !== 6) {
              allWeekdays.push(cur.toISOString().slice(0, 10));
            }
            cur.setDate(cur.getDate() + 1);
          }

          allWeekdays.forEach(function(dateStr) {
            var cell = document.createElement('div');
            cell.style.width = '12px';
            cell.style.height = '12px';
            cell.style.borderRadius = '2px';
            cell.style.cursor = 'default';
            cell.style.transition = 'transform 0.15s';

            var dayData = days.find(function(d) { return d.date === dateStr; });
            if (dayData) {
              var intensity = Math.min(dayData.total_points / maxPts, 1);
              var alpha = 0.1 + intensity * 0.9;
              cell.style.background = 'rgba(16,185,129,' + alpha.toFixed(2) + ')';
              cell.title = dateStr + ': ' + dayData.total_points + ' pts, ' + dayData.event_count + ' events';
            } else {
              cell.style.background = 'var(--bg-tertiary)';
              cell.title = dateStr + ': no data';
            }

            cell.addEventListener('mouseenter', function(e) {
              cell.style.transform = 'scale(1.6)';
              cell.style.zIndex = '1';
              showTip(e, cell.title);
            });
            cell.addEventListener('mouseleave', function() {
              cell.style.transform = '';
              cell.style.zIndex = '';
              hideTip();
            });

            container.appendChild(cell);
          });
        }

        function _renderPillarChart(data) {
          var svg = d3.select('#qcPillarChart');
          if (svg.empty()) return;
          svg.selectAll('*').remove();

          var pillars = data.pillar_avgs || {};
          var colors = data.pillar_colors || {};
          var summary = data.pillar_summary || {};
          var names = Object.keys(pillars);
          if (names.length === 0) return;

          var margin = { top: 10, right: 60, bottom: 10, left: 160 };
          var node = svg.node();
          var containerW = node.parentElement ? node.parentElement.getBoundingClientRect().width : 0;
          var width = (containerW || node.clientWidth || 600) - margin.left - margin.right;
          var height = 160 - margin.top - margin.bottom;
          svg.attr('viewBox', '0 0 ' + (width + margin.left + margin.right) + ' 160');
          var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

          var barHeight = Math.min(28, Math.floor(height / names.length) - 8);
          var y = d3.scaleBand().domain(names).range([0, height]).padding(0.25);
          var x = d3.scaleLinear().domain([0, 100]).range([0, width]);

          names.forEach(function(name) {
            var pct = pillars[name] || 0;
            var color = colors[name] || '#888';
            var ps = summary[name] || {};
            var yPos = y(name) + y.bandwidth() / 2;

            g.append('rect')
              .attr('x', 0).attr('y', y(name))
              .attr('width', width).attr('height', y.bandwidth())
              .attr('fill', 'var(--bg-tertiary)').attr('rx', 4);

            g.append('rect')
              .attr('x', 0).attr('y', y(name))
              .attr('width', x(Math.min(pct, 100))).attr('height', y.bandwidth())
              .attr('fill', color).attr('opacity', 0.8).attr('rx', 4);

            g.append('text')
              .attr('x', -8).attr('y', yPos + 1)
              .attr('text-anchor', 'end').attr('fill', 'var(--text-primary)')
              .attr('font-size', '12px').attr('font-weight', '600')
              .text(name);

            g.append('text')
              .attr('x', x(Math.min(pct, 100)) + 6).attr('y', yPos + 1)
              .attr('fill', color).attr('font-size', '12px').attr('font-weight', '700')
              .text(pct + '%');

            if (ps.priority_count > 0) {
              g.append('text')
                .attr('x', width + 8).attr('y', yPos + 1)
                .attr('fill', 'var(--text-muted)').attr('font-size', '10px')
                .text(ps.covered + '/' + ps.priority_count);
            }
          });
        }

        function _renderCoverageDonut(data) {
          var svg = d3.select('#qcCoverageDonut');
          if (svg.empty()) return;
          svg.selectAll('*').remove();

          var cs = data.coverage_summary || {};
          var covered = cs.covered || 0;
          var gaps = cs.gaps || 0;
          var total = covered + gaps;
          if (total === 0) return;
          var pct = cs.coverage_pct || 0;

          var size = 80;
          var radius = size / 2;
          var innerR = radius * 0.6;
          var g = svg.append('g').attr('transform', 'translate(' + radius + ',' + radius + ')');

          var arc = d3.arc().innerRadius(innerR).outerRadius(radius);
          var pie = d3.pie().value(function(d) { return d.value; }).sort(null).padAngle(0.03);

          var slices = pie([
            { label: 'Covered', value: covered, color: '#10b981' },
            { label: 'Gaps', value: gaps, color: '#ef4444' }
          ]);

          g.selectAll('path').data(slices).enter()
            .append('path')
            .attr('d', arc)
            .attr('fill', function(d) { return d.data.color; })
            .attr('opacity', 0.85)
            .on('mouseenter', function(event, d) {
              d3.select(this).attr('opacity', 1);
              showTip(event, d.data.label + ': ' + d.data.value);
            })
            .on('mouseleave', function() {
              d3.select(this).attr('opacity', 0.85);
              hideTip();
            });

          g.append('text')
            .attr('text-anchor', 'middle').attr('dy', '0.1em')
            .attr('fill', pct >= 50 ? '#10b981' : '#ef4444')
            .attr('font-size', '16px').attr('font-weight', '700')
            .text(pct + '%');

          g.append('text')
            .attr('text-anchor', 'middle').attr('dy', '1.4em')
            .attr('fill', 'var(--text-muted)')
            .attr('font-size', '8px')
            .text(covered + '/' + total);
        }

        window._initQcOverviewCharts = initQcOverviewCharts;
        setTimeout(initQcOverviewCharts, 100);
      })();

      // ============ Issues Dashboard Charts (D3) ============
      (function() {
        var TAG_COLORS = {
          worktype: '#3b82f6', quality: '#10b981', domain: '#8b5cf6',
          ops: '#f97316', monitoring: '#ef4444', other: '#6b7280'
        };
        var TAG_CAT_MAP = {
          feat:'worktype', fix:'worktype', refactor:'worktype',
          test:'quality', review:'quality', docs:'quality',
          billing:'domain', auth:'domain', api:'domain', config:'domain', mock:'domain',
          deploy:'ops', pipeline:'ops', 'ci/cd':'ops', release:'ops',
          grafana:'monitoring', monitoring:'monitoring', alert:'monitoring',
          security:'monitoring', performance:'monitoring',
          migration:'ops', integration:'domain'
        };

        function getTagColor(tag) {
          return TAG_COLORS[TAG_CAT_MAP[tag] || 'other'] || TAG_COLORS.other;
        }

        function initIssuesDashboard() {
          var dataEl = document.getElementById('issuesDashboardData');
          if (!dataEl) return;
          if (typeof d3 === 'undefined') { setTimeout(initIssuesDashboard, 500); return; }

          var dd;
          try { dd = JSON.parse(dataEl.textContent || '{}'); } catch(e) { return; }

          initTreemap(dd);
          initDonut(dd);
          initGauge(dd);
          initTagChart(dd);
        }

        function initTreemap(dd) {
          var container = document.getElementById('issuesDashTreemap');
          if (!container || !dd.strategies || !dd.strategies.length) return;

          var w = container.clientWidth;
          var h = container.clientHeight;
          if (!w || w < 50) { setTimeout(function() { initTreemap(dd); }, 300); return; }
          if (!h || h < 40) h = 130;
          container.innerHTML = '';

          var root = { name: 'root', children: dd.strategies.map(function(s) {
            return {
              name: s.key.replace('ANSTRAT-','S-'),
              value: Math.max(s.points, 1),
              fullKey: s.key,
              summary: (s.summary || '').substring(0, 40),
              children: (s.children || []).map(function(e) {
                return { name: e.key, value: Math.max(e.points, 1), summary: (e.summary || '').substring(0, 30) };
              })
            };
          })};

          var hier = d3.hierarchy(root).sum(function(d) { return d.children && d.children.length ? 0 : d.value; });
          d3.treemap().size([w, h]).padding(2).round(true)(hier);

          var svg = d3.select(container).append('svg').attr('width', w).attr('height', h);
          var colorScale = d3.scaleOrdinal(d3.schemeTableau10);

          var leaves = hier.leaves();
          var cells = svg.selectAll('g').data(leaves).enter().append('g')
            .attr('transform', function(d) { return 'translate(' + d.x0 + ',' + d.y0 + ')'; });

          cells.append('rect')
            .attr('width', function(d) { return Math.max(d.x1 - d.x0, 0); })
            .attr('height', function(d) { return Math.max(d.y1 - d.y0, 0); })
            .attr('rx', 2)
            .attr('fill', function(d) {
              var anc = d.parent;
              while (anc && anc.depth > 1) anc = anc.parent;
              return colorScale(anc ? anc.data.name : d.data.name);
            })
            .attr('opacity', 0.8)
            .style('cursor', 'pointer')
            .append('title')
            .text(function(d) { return d.data.name + ': ' + d.value + 'pts' + (d.data.summary ? '\\n' + d.data.summary : ''); });

          cells.each(function(d) {
            var cw = d.x1 - d.x0;
            var ch = d.y1 - d.y0;
            if (cw > 30 && ch > 14) {
              d3.select(this).append('text')
                .attr('x', 3).attr('y', 11)
                .attr('class', 'issues-treemap-label')
                .text(function(dd) {
                  var label = dd.data.name;
                  return label.length > cw / 6 ? label.substring(0, Math.floor(cw / 6)) : label;
                });
            }
          });
        }

        function initDonut(dd) {
          var container = document.getElementById('issuesDashDonut');
          if (!container || !dd.scope_points) return;
          container.innerHTML = '';

          var w = container.clientWidth || 140;
          var h = container.clientHeight || 110;
          var radius = Math.min(w, h) / 2 - 4;

          var data = Object.entries(dd.scope_points).filter(function(e) { return e[1] > 0; });
          if (!data.length) return;

          var scopeColors = { commit: '#3b82f6', story: '#10b981', epic: '#f59e0b', anstrat: '#ef4444', meeting: '#8b5cf6', doc: '#06b6d4' };
          var total = data.reduce(function(s, d) { return s + d[1]; }, 0);

          var svg = d3.select(container).append('svg').attr('width', w).attr('height', h);
          var g = svg.append('g').attr('transform', 'translate(' + w/2 + ',' + h/2 + ')');

          var pie = d3.pie().value(function(d) { return d[1]; }).sort(null);
          var arc = d3.arc().innerRadius(radius * 0.55).outerRadius(radius);

          g.selectAll('path').data(pie(data)).enter().append('path')
            .attr('d', arc)
            .attr('fill', function(d) { return scopeColors[d.data[0]] || '#6b7280'; })
            .attr('opacity', 0.85)
            .append('title')
            .text(function(d) { return d.data[0] + ': ' + d.data[1] + 'pts (' + Math.round(d.data[1]/total*100) + '%)'; });

          g.append('text').attr('class', 'issues-donut-center').attr('dy', '0.35em').text(total);

          var legend = d3.select(container).append('div')
            .style('display', 'flex').style('gap', '8px').style('justify-content', 'center')
            .style('flex-wrap', 'wrap').style('margin-top', '2px');
          data.forEach(function(d) {
            legend.append('span')
              .style('font-size', '11px').style('color', 'var(--text-secondary)')
              .html('<span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:'
                + (scopeColors[d[0]] || '#6b7280') + ';margin-right:3px;"></span>' + d[0]);
          });
        }

        function initGauge(dd) {
          var container = document.getElementById('issuesDashGauge');
          if (!container) return;
          container.innerHTML = '';

          var pct = dd.alignment_pct || 0;
          var aligned = dd.aligned_points || 0;
          var unaligned = dd.unaligned_points || 0;

          var barColor = pct >= 70 ? 'var(--success)' : pct >= 40 ? 'var(--warning)' : 'var(--error)';

          container.innerHTML =
            '<div class="issues-gauge-pct">' + pct + '%</div>' +
            '<div class="issues-gauge-label">of points are strategy-aligned</div>' +
            '<div class="issues-gauge-bar"><div class="issues-gauge-fill" style="width:' + pct + '%;background:' + barColor + ';"></div></div>' +
            '<div class="issues-gauge-legend">' +
              '<span><span class="issues-gauge-dot" style="background:' + barColor + '"></span>Aligned: ' + aligned + 'pts</span>' +
              '<span><span class="issues-gauge-dot" style="background:var(--bg-tertiary)"></span>Other: ' + unaligned + 'pts</span>' +
            '</div>';
        }

        function initTagChart(dd) {
          var container = document.getElementById('issuesDashTags');
          if (!container || !dd.tag_counts) return;
          container.innerHTML = '';

          var tags = Object.entries(dd.tag_counts);
          if (!tags.length) return;
          var maxCount = tags.reduce(function(m, t) { return Math.max(m, t[1]); }, 0) || 1;

          var html = '';
          tags.slice(0, 10).forEach(function(t) {
            var pct = Math.round(t[1] / maxCount * 100);
            html += '<div class="issues-tag-bar-row">' +
              '<span class="issues-tag-bar-label">' + t[0] + '</span>' +
              '<span class="issues-tag-bar-fill" style="width:' + Math.max(pct, 4) + '%;background:' + getTagColor(t[0]) + ';"></span>' +
              '<span class="issues-tag-bar-count">' + t[1] + '</span>' +
            '</div>';
          });
          container.innerHTML = html;
        }

        window._initIssuesDashboard = initIssuesDashboard;
        setTimeout(initIssuesDashboard, 250);
      })();

      // ============ Issues Tag Filter ============
      (function() {
        function setupTagFilter() {
          document.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-action="filterTag"]');
            if (!btn) return;
            var tag = btn.getAttribute('data-tag') || '';

            document.querySelectorAll('.issues-tag-filter-btn').forEach(function(b) {
              b.classList.remove('active');
            });

            if (tag) {
              btn.classList.add('active');
              document.querySelectorAll('.perf-tree-node').forEach(function(node) {
                var nodeTags = (node.getAttribute('data-tags') || '').split(',');
                if (nodeTags.indexOf(tag) >= 0 || node.querySelector('.perf-tree-toggle')) {
                  node.classList.remove('tag-filtered-out');
                } else {
                  node.classList.add('tag-filtered-out');
                }
              });
              document.querySelectorAll('.issue-card').forEach(function(card) {
                var cardTags = (card.getAttribute('data-tags') || '').split(',');
                if (cardTags.indexOf(tag) >= 0) {
                  card.classList.remove('tag-filtered-out');
                } else {
                  card.classList.add('tag-filtered-out');
                }
              });
            } else {
              document.querySelectorAll('.perf-tree-node').forEach(function(node) {
                node.classList.remove('tag-filtered-out');
              });
              document.querySelectorAll('.issue-card').forEach(function(card) {
                card.classList.remove('tag-filtered-out');
              });
            }
          });
        }
        setupTagFilter();
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

  private async handlePerformanceAction(action: string, message: any): Promise<boolean> {
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
      case "collectPeers":
        await this.collectPeers(false);
        break;
      case "collectPeersBackfill":
        await this.collectPeers(true);
        break;
      case "toggleBackfillOptions":
        this.postMessageToWebview({ command: "toggleBackfillOptions" });
        break;
      case "cancelBackfillOptions":
        this.postMessageToWebview({ command: "hideBackfillOptions" });
        break;
      case "startFilteredBackfill":
        await this._startFilteredBackfill(message);
        break;
      case "rescorePeers":
        await this._rescorePeers();
        break;
      case "cancelBackfill":
        await this._cancelBackfill();
        break;
      case "scrubData":
        await this._scrubData();
        break;
      case "loadPromotionReadiness":
        await this._loadPromotionReadiness();
        break;
      case "loadPeerGrowth":
        await this._loadPeerGrowth();
        break;
      case "evaluateQuestionLocal":
        await this._evaluateQuestionLocal(message.questionId);
        break;
      case "classifyLogEntry":
        await this._classifyLogEntry(message.description);
        break;
      case "askAI":
        await this._askAI(message.question);
        break;
      case "getGapCoach":
        await this._loadGapCoach(message.competencyId);
        break;
      case "explainScore":
        await this._explainScore(message.competencyId);
        break;
      case "suggestConfigTune":
        await this._suggestConfigTune();
        break;
      case "detectMissingLinks":
        await this._detectMissingLinks();
        break;
      case "clearDrafts":
        await this.clearAllDrafts();
        break;
      case "saveQuestion":
        await this.saveQuestion(message.description);
        break;
      case "removeQuestion":
        await this.removeQuestion(message.questionId);
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
      case "switchCompView":
        this.state.competency_view = (message.view === "mindmap") ? "mindmap" : "sunburst";
        if (this.state.competency_view === "mindmap") {
          this.forceNextRender = true;
        }
        this.notifyNeedsRender();
        break;
      case "switchHeatmapMode": {
        const modes = ["percentage", "raw_points", "peer_comparable"] as const;
        const validMode = modes.find(m => m === message.mode);
        if (validMode) {
          this.state.heatmap_mode = validMode;
          this.notifyNeedsRender();
        }
        break;
      }
      case "switchEventVolumeMode": {
        this.state.event_volume_mode = message.mode === "all" ? "all" : "comparable";
        this.notifyNeedsRender();
        break;
      }
      case "toggleSessionEnrichment": {
        this.state.session_enrichment = !this.state.session_enrichment;
        this.notifyNeedsRender();
        break;
      }
      case "switchPeerComparisonMode": {
        const cm = message.mode === "raw" ? "raw" : "comparable";
        this.state.peer_comparison_mode = cm;
        this.state.heatmap_mode = cm === "comparable" ? "peer_comparable" : "percentage";
        this.state.event_volume_mode = cm === "comparable" ? "comparable" : "all";
        this.notifyNeedsRender();
        break;
      }
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
        return false;
    }
    return true;
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
          summary: raw.summary || { total_points: 0, aligned_points: 0, unaligned_points: 0, alignment_pct: 0, scope_points: {}, pillar_points: { technical: 0, leadership: 0, mentorship: 0, delivery: 0 }, tag_counts: {} },
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
    vscode.window.showInformationMessage("Collecting today's data (user + peers)...");
    try {
      const [dailyResult, peersResult] = await Promise.all([
        dbus.stats_collectDaily(),
        dbus.stats_collectPeers(false),
      ]);

      const parts: string[] = [];
      if (dailyResult.success) {
        const data = dailyResult.data as any;
        parts.push(`${data?.event_count || 0} events, ${data?.daily_total || 0} points`);
      } else {
        parts.push(`daily failed: ${dailyResult.error}`);
      }
      if (peersResult.success) {
        const pd = peersResult.data as any;
        parts.push(`${pd?.peers_processed ?? 0} peers`);
      } else {
        parts.push(`peers failed: ${peersResult.error}`);
      }

      vscode.window.showInformationMessage(`Daily collection complete: ${parts.join(", ")}`);
      await this.refresh();
    } catch (error) {
      vscode.window.showErrorMessage(`Error collecting data: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async backfillAll(): Promise<void> {
    vscode.window.showInformationMessage("Backfilling all quarter data (metadata, user, peers, emails)...");
    try {
      // Phase 1: Sync metadata caches (strategy ownership, sender sources, Jira hierarchy)
      vscode.window.showInformationMessage("Phase 1/4: Syncing metadata (strategy, senders, hierarchy)...");
      await Promise.allSettled([
        dbus.stats_syncAnstratOwnership(),
        dbus.stats_syncSenderSources(),
        dbus.stats_getIssueHierarchy(true),
      ]);

      // Phase 2: Collect user data + executive emails in parallel
      vscode.window.showInformationMessage("Phase 2/4: Collecting user data and executive emails...");
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

      // Phase 3: Re-evaluate/re-score with fresh metadata
      vscode.window.showInformationMessage("Phase 3/4: Re-scoring with fresh metadata...");
      await dbus.stats_evaluateAll();

      vscode.window.showInformationMessage(`User backfill done: ${parts.join(", ")}. Phase 4/4: Starting peer backfill...`);

      // Phase 4: Backfill all peer data in the background
      try {
        const peersResult = await dbus.stats_collectPeers(true);
        if (peersResult.success) {
          this.postMessageToWebview({ command: "peerBackfillStarted" });
          this._backfillPollInterval = setInterval(() => this._pollBackfillProgress(), 2000);
        } else {
          vscode.window.showErrorMessage(`Peer backfill failed: ${peersResult.error}`);
          await this.refresh();
        }
      } catch (peerError) {
        vscode.window.showErrorMessage(`Peer backfill error: ${peerError instanceof Error ? peerError.message : String(peerError)}`);
        await this.refresh();
      }
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

  private _backfillPollInterval?: ReturnType<typeof setInterval>;

  private async collectPeers(backfill: boolean): Promise<void> {
    if (!backfill) {
      vscode.window.showInformationMessage("Collecting peer data for today...");
      try {
        const result = await dbus.stats_collectPeers(false);
        if (result.success) {
          const data = result.data as any;
          vscode.window.showInformationMessage(
            `Peer collection complete: ${data?.peers_processed ?? 0} peers processed`
          );
          await this.refresh();
        } else {
          vscode.window.showErrorMessage(`Peer collection failed: ${result.error}`);
        }
      } catch (error) {
        vscode.window.showErrorMessage(
          `Error collecting peers: ${error instanceof Error ? error.message : String(error)}`
        );
      }
      return;
    }

    vscode.window.showInformationMessage("Starting peer backfill (runs in background)...");
    try {
      const result = await dbus.stats_collectPeers(true);
      if (result.success) {
        this.postMessageToWebview({ command: "peerBackfillStarted" });
        this._backfillPollInterval = setInterval(() => this._pollBackfillProgress(), 2000);
      } else {
        vscode.window.showErrorMessage(`Peer backfill failed: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Error starting backfill: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  private async _startFilteredBackfill(message: any): Promise<void> {
    const allSourceKeys = ["git", "jira", "gitlab", "github", "gdrive", "meeting"] as const;
    const sources: string[] = [];
    if (message.srcGit) sources.push("git");
    if (message.srcJira) sources.push("jira");
    if (message.srcGitlab) sources.push("gitlab");
    if (message.srcGithub) sources.push("github");
    if (message.srcGdrive) sources.push("gdrive");
    if (message.srcMeeting) sources.push("meeting");

    const scopeUser = message.scopeUser !== false;
    const scopePeers = message.scopePeers !== false;
    const scopeEmails = message.scopeEmails !== false;

    if (sources.length === 0) {
      vscode.window.showWarningMessage("Select at least one source to backfill.");
      return;
    }
    if (!scopeUser && !scopePeers && !scopeEmails) {
      vscode.window.showWarningMessage("Select at least one scope (My data, Peers, or Emails).");
      return;
    }

    const options: { sources?: string[]; dateStart?: string; dateEnd?: string } = {};
    if (sources.length < allSourceKeys.length) {
      options.sources = sources;
    }
    const dateRange = message.dateRange as string;
    if (dateRange && dateRange !== "full") {
      const days = parseInt(dateRange, 10);
      if (!isNaN(days)) {
        const now = new Date();
        const start = new Date(now);
        start.setDate(start.getDate() - days);
        options.dateStart = start.toISOString().slice(0, 10);
      }
    }

    const scopeParts: string[] = [];
    if (scopeUser) scopeParts.push("user");
    if (scopePeers) scopeParts.push("peers");
    if (scopeEmails) scopeParts.push("emails");
    const label = sources.length < allSourceKeys.length ? sources.join(", ") : "all sources";
    const rangeLabel = dateRange === "full" ? "full quarter" : `last ${dateRange} days`;
    vscode.window.showInformationMessage(`Starting backfill: ${scopeParts.join("+")} — ${label}, ${rangeLabel}...`);

    this.postMessageToWebview({ command: "hideBackfillOptions" });

    try {
      if (scopeUser) {
        vscode.window.showInformationMessage("Syncing metadata (strategy, senders, hierarchy)...");
        await Promise.allSettled([
          dbus.stats_syncAnstratOwnership(),
          dbus.stats_syncSenderSources(),
          dbus.stats_getIssueHierarchy(true),
        ]);
      }

      const promises: Promise<any>[] = [];

      if (scopeUser) {
        promises.push(dbus.stats_backfill());
      }
      if (scopeEmails) {
        promises.push(dbus.stats_backfillExecutiveEmails());
      }

      if (promises.length > 0) {
        const results = await Promise.all(promises);
        const parts: string[] = [];
        let idx = 0;
        if (scopeUser) {
          const r = results[idx++];
          if (r.success) {
            parts.push(`${(r.data as any)?.days_processed || 0} days`);
          } else {
            parts.push(`user failed: ${r.error}`);
          }
        }
        if (scopeEmails) {
          const r = results[idx++];
          if (r.success) {
            const e = r.data as any;
            parts.push(`${(e?.total_new || 0) + (e?.total_skipped || 0)} emails`);
          } else {
            parts.push(`emails failed: ${r.error}`);
          }
        }
        if (parts.length > 0) {
          vscode.window.showInformationMessage(`Backfill progress: ${parts.join(", ")}`);
        }
      }

      if (scopeUser) {
        vscode.window.showInformationMessage("Re-scoring with fresh metadata...");
        await dbus.stats_evaluateAll();
      }

      if (scopePeers) {
        const result = await dbus.stats_collectPeers(true, options);
        if (result.success) {
          this.postMessageToWebview({ command: "peerBackfillStarted" });
          this._backfillPollInterval = setInterval(() => this._pollBackfillProgress(), 2000);
        } else {
          vscode.window.showErrorMessage(`Peer backfill failed: ${result.error}`);
          await this.refresh();
        }
      } else {
        await this.refresh();
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Error starting filtered backfill: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  private async _rescorePeers(): Promise<void> {
    vscode.window.showInformationMessage("Re-scoring peer data (no re-collection)...");
    this.postMessageToWebview({ command: "hideBackfillOptions" });
    try {
      const result = await dbus.stats_rescorePeers();
      if (result.success) {
        const data = result.data as any;
        vscode.window.showInformationMessage(
          `Re-score complete: ${data?.files_updated ?? 0} files, ${data?.peers_updated ?? 0} peers updated`
        );
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Re-score failed: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Error re-scoring peers: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  private async _cancelBackfill(): Promise<void> {
    try {
      const result = await dbus.stats_cancelBackfill();
      if (this._backfillPollInterval) {
        clearInterval(this._backfillPollInterval);
        this._backfillPollInterval = undefined;
      }
      this._backfillEverRanning = false;
      this.postMessageToWebview({ command: "peerBackfillCancelled" });
      if (result.success) {
        vscode.window.showInformationMessage("Backfill cancelled.");
      } else {
        vscode.window.showErrorMessage(`Cancel failed: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Error cancelling backfill: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  private async _scrubData(): Promise<void> {
    const confirm = await vscode.window.showWarningMessage(
      "This will delete ALL collected performance data for the current quarter (user daily data, peer data, caches, executive emails). This cannot be undone.",
      { modal: true },
      "Scrub All Data"
    );
    if (confirm !== "Scrub All Data") return;

    this.postMessageToWebview({ command: "hideBackfillOptions" });
    try {
      const result = await dbus.stats_scrubData();
      if (result.success) {
        const data = result.data as any;
        vscode.window.showInformationMessage(
          `Data scrubbed: ${data?.message ?? "Done"}. Run Backfill to re-collect.`
        );
        this.state.overall_percentage = 0;
        this.state.peer_comparable_overall = 0;
        this.state.event_counts_by_source = {};
        this.state.competencies = {};
        this.state.highlights = [];
        this.state.gaps = [];
        this.state.captured_days = [];
        this.state.coverage = { total_weekdays: 0, captured: 0, percentage: 0 };
        this.state.issue_hierarchy = null;
        this.state.day_detail = null;
        this.state.competency_evidence = {};
        this.state.competency_meta = {};
        this.state.gap_suggestions = {};
        this.state.strategy_alignment = null;
        this.state.executive_emails = [];
        this.state.peer_benchmarks = null;
        this.state.org_stats = null;
        this.state.ai_peer_narrative = null;
        this.state.ai_peer_differentiators = null;
        this.state.ai_overview_digest = null;
        this.state.ai_calendar_insights = null;
        this.state.ai_promotion_readiness = null;
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Scrub failed: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Error scrubbing data: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  private _backfillEverRanning = false;

  private async _pollBackfillProgress(): Promise<void> {
    try {
      const result = await dbus.stats_getPeerBackfillProgress();
      if (!result.success) return;
      const p = result.data as any;

      if (p.running) {
        this._backfillEverRanning = true;
      }

      this.postMessageToWebview({ command: "peerBackfillProgress", progress: p });

      if (!p.running && this._backfillEverRanning) {
        this._backfillEverRanning = false;
        if (this._backfillPollInterval) {
          clearInterval(this._backfillPollInterval);
          this._backfillPollInterval = undefined;
        }
        if (p.cancelled) {
          this.postMessageToWebview({ command: "peerBackfillCancelled" });
          vscode.window.showInformationMessage("Backfill was cancelled.");
        } else {
          const evts = p.total_events ?? 0;
          const peers = p.completed_peers ?? 0;
          const secs = p.elapsed_seconds ?? 0;
          const errs = (p.errors?.length ?? 0);
          const filterInfo = (p.filter_info && p.filter_info !== "all") ? ` [${p.filter_info}]` : "";
          vscode.window.showInformationMessage(
            `Peer backfill complete: ${peers} peers, ${evts} events in ${secs}s` +
            (errs > 0 ? ` (${errs} errors)` : "") + filterInfo
          );
          this.postMessageToWebview({ command: "peerBackfillComplete", progress: p });
        }
        await this.refresh();
      }
    } catch {
      // polling failure is transient, just skip
    }
  }

  // ==================== AI Feature Handlers ====================

  private async _loadPeerGrowth(): Promise<void> {
    try {
      const result = await dbus.stats_getPeerGrowthData();
      if (result.success && result.data) {
        const data = result.data as any;
        this.postMessageToWebview({ command: "peerGrowthData", data });
      } else {
        vscode.window.showWarningMessage("No growth data available.");
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to load growth data: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async _loadPromotionReadiness(): Promise<void> {
    try {
      const result = await dbus.stats_getPromotionReadiness();
      if (result.success && result.data) {
        this.state.ai_promotion_readiness = result.data as any;
        this.notifyNeedsRender();
      } else {
        vscode.window.showWarningMessage(`Promotion readiness: ${result.error || "No data"}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Failed to load promotion readiness: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async _evaluateQuestionLocal(questionId: string): Promise<void> {
    if (!questionId) return;
    vscode.window.showInformationMessage("Evaluating question with local LLM...");
    try {
      const result = await dbus.stats_evaluateQuestionLocal(questionId);
      if (result.success && result.data) {
        const data = result.data as any;
        vscode.window.showInformationMessage(`Evaluation complete (${data.model || "local LLM"})`);
        await this.refresh();
      } else {
        vscode.window.showErrorMessage(`Evaluation failed: ${result.error || "Unknown error"}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Local evaluation error: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async _classifyLogEntry(description: string): Promise<void> {
    if (!description || description.length < 5) return;
    try {
      const result = await dbus.stats_classifyLogEntry(description);
      if (result.success && result.data) {
        const cat = (result.data as any).category;
        if (cat) {
          this.postMessageToWebview({ command: "aiLogCategory", category: cat });
        }
      }
    } catch { /* classification is best-effort */ }
  }

  private async _askAI(question: string): Promise<void> {
    if (!question) return;
    try {
      const result = await dbus.stats_askAI(question);
      if (result.success && result.data) {
        const answer = (result.data as any).answer || "No answer available.";
        this.postMessageToWebview({ command: "aiAnswer", answer, question });
      }
    } catch (error) {
      this.postMessageToWebview({
        command: "aiAnswer",
        answer: "AI is currently unavailable.",
        question,
      });
    }
  }

  private async _loadGapCoach(competencyId: string): Promise<void> {
    if (!competencyId) return;
    try {
      const result = await dbus.stats_getGapCoach(competencyId);
      if (result.success && result.data) {
        const suggestion = (result.data as any).suggestion || "";
        if (suggestion) {
          this.state.gap_suggestions[competencyId] = {
            ...(this.state.gap_suggestions[competencyId] || {}),
            ai_suggestion: suggestion,
          } as any;
          this.notifyNeedsRender();
        }
      }
    } catch { /* gap coach is best-effort */ }
  }

  private async _explainScore(competencyId: string): Promise<void> {
    if (!competencyId) return;
    try {
      const result = await dbus.stats_explainCompetencyScore(competencyId);
      if (result.success && result.data) {
        const explanation = (result.data as any).explanation || "";
        if (explanation) {
          vscode.window.showInformationMessage(explanation.substring(0, 500));
        }
      }
    } catch { /* explanation is best-effort */ }
  }

  private async _detectMissingLinks(): Promise<void> {
    vscode.window.showInformationMessage("Scanning for orphan issues...");
    try {
      const result = await dbus.stats_detectMissingLinks();
      if (result.success && result.data) {
        const suggestions = (result.data as any).suggestions || [];
        this.postMessageToWebview({ command: "missingLinksResult", suggestions });
        if (suggestions.length === 0) {
          vscode.window.showInformationMessage("No missing links found -- all issues appear well-connected.");
        }
      } else {
        vscode.window.showWarningMessage(result.error || "Missing link detection unavailable.");
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Missing link detection failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async _suggestConfigTune(): Promise<void> {
    try {
      const result = await dbus.stats_suggestConfigTune();
      if (result.success && result.data) {
        const suggestions = (result.data as any).suggestions || [];
        if (suggestions.length === 0) {
          vscode.window.showInformationMessage("No config adjustments suggested -- your settings look balanced.");
        } else {
          const msgs = suggestions.map((s: any) => s.message).join("\n\n");
          vscode.window.showInformationMessage(msgs.substring(0, 500));
        }
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Config tune failed: ${error instanceof Error ? error.message : String(error)}`);
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

  private async clearAllDrafts(): Promise<void> {
    const answer = await vscode.window.showWarningMessage(
      "Clear all AI-generated drafts? You can re-generate them later.",
      "Clear Drafts",
      "Cancel",
    );
    if (answer !== "Clear Drafts") return;

    try {
      const result = await dbus.stats_clearDrafts();
      if (result.success) {
        const data = result.data as any;
        const cleared = data?.cleared || 0;
        if (data?.questions_summary) {
          this.state.questions_summary = data.questions_summary;
        }
        vscode.window.showInformationMessage(`Cleared ${cleared} AI draft${cleared !== 1 ? "s" : ""}`);
        this.notifyNeedsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to clear drafts: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error clearing drafts: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async saveQuestion(description: string): Promise<void> {
    if (!description) return;

    try {
      const result = await dbus.stats_addQuestion(description);
      if (result.success) {
        const data = result.data as any;
        if (data?.questions_summary) {
          this.state.questions_summary = data.questions_summary;
        }
        vscode.window.showInformationMessage("Question added.");
        this.notifyNeedsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to add question: ${result.error || "Unknown error"}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error adding question: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private async removeQuestion(questionId: string): Promise<void> {
    if (!questionId) return;

    const answer = await vscode.window.showWarningMessage(
      "Remove this question? Evidence and notes will be lost.",
      "Remove",
      "Cancel",
    );
    if (answer !== "Remove") return;

    try {
      const result = await dbus.stats_removeQuestion(questionId);
      if (result.success) {
        const data = result.data as any;
        if (data?.questions_summary) {
          this.state.questions_summary = data.questions_summary;
        }
        vscode.window.showInformationMessage("Question removed.");
        this.notifyNeedsRender();
      } else {
        vscode.window.showErrorMessage(`Failed to remove question: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(`Error removing question: ${error instanceof Error ? error.message : String(error)}`);
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
    const delay = (field === "min_signals" || field === "daily_cap") ? 500 : 1500;
    this.debouncedSaveScoringConfig(delay);
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
        const totalNew = data?.total_new ?? 0;
        const senders: Array<{sender: string; found?: number; new?: number; error?: string}> = data?.senders ?? [];
        const failed = senders.filter(s => s.error);
        const empty = senders.filter(s => !s.error && (s.found ?? 0) === 0);
        let msg = `Backfill complete: ${totalNew} new emails fetched`;
        if (empty.length > 0) {
          msg += ` | No emails found for: ${empty.map(s => s.sender).join(", ")}`;
        }
        if (failed.length > 0) {
          msg += ` | Failed: ${failed.map(s => `${s.sender} (${s.error})`).join(", ")}`;
        }
        if (failed.length > 0) {
          vscode.window.showWarningMessage(msg);
        } else {
          vscode.window.showInformationMessage(msg);
        }
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

  /**
   * After a successful config save + backend re-evaluation, reload all
   * data so charts reflect the new scores.  Debounced at 300ms so rapid
   * saves (e.g. typing base_points) coalesce into a single reload.
   */
  private schedulePostSaveRefresh(): void {
    if (this._postSaveRefreshTimer) {
      clearTimeout(this._postSaveRefreshTimer);
    }
    this._postSaveRefreshTimer = setTimeout(async () => {
      this._postSaveRefreshTimer = null;
      await this.refreshPreservingUIState();
    }, 300);
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
                  <strong>${this.safeText(ev.title || ev.item_id)}</strong>
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
