/**
 * Performance Tab Type Definitions
 *
 * All interfaces extracted from PerformanceTab.ts for shared use
 * across renderer modules, action handlers, and the main tab.
 */

export interface CompetencyScore {
  points: number;
  percentage: number;
  no_enrichment_points?: number;
  no_enrichment_percentage?: number;
  peer_comparable_points?: number;
  peer_comparable_percentage?: number;
}

export interface QuestionNote {
  text: string;
  added_at: string;
}

export interface QuestionSummary {
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

export interface QuestionEvidence {
  id: string;
  title: string;
  source: string;
  date: string;
  points: number;
  competencies: string[];
}

export interface CapturedDay {
  date: string;
  event_count: number;
  total_points: number;
  sources: string[];
  category_points: Record<string, number>;
}

export interface CoverageInfo {
  total_weekdays: number;
  captured: number;
  percentage: number;
}

export interface PillarPoints {
  technical: number;
  leadership: number;
  mentorship: number;
  delivery: number;
}

export interface IssueNode {
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

export interface IssueSummary {
  total_points: number;
  aligned_points: number;
  unaligned_points: number;
  alignment_pct: number;
  scope_points: Record<string, number>;
  pillar_points: PillarPoints;
  tag_counts: Record<string, number>;
}

export interface IssueHierarchy {
  strategies: IssueNode[];
  unattached_epics: IssueNode[];
  uncategorized: IssueNode[];
  total_issues: number;
  cached: boolean;
  summary: IssueSummary;
}

export interface IssueLineageEntry {
  key: string;
  summary: string;
  epic?: { key: string; summary: string };
  anstrat?: { key: string; summary: string };
}

export interface DayEvent {
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

export interface DayDetail {
  date: string;
  events: DayEvent[];
  daily_points: Record<string, number>;
  daily_total: number;
  category_points: Record<string, number>;
  has_data: boolean;
}

export interface CompetencyEvidence {
  date: string;
  title: string;
  source: string;
  type: string;
  points: number;
  issue_keys: string[];
  url?: string;
  match_reason?: string;
}

export interface CompetencyMeta {
  name: string;
  category: string;
  goal: string;
  description: string;
  percentage: number;
  points: number;
  target: number;
  evidence_count: number;
}

export interface GapSuggestion {
  percentage: number;
  points: number;
  target: number;
  deficit: number;
  suggestions: string[];
  evidence_count: number;
  goal?: string;
  description?: string;
  category?: string;
  ai_suggestion?: string;
}

export interface StrategyAlignmentPriority {
  name: string;
  context: string;
  status: "covered" | "gap";
  pillar: string;
  issue_keys: string[];
  matched_user_issues: string[];
  matched_mrs: string[];
  senders: string[];
  owner_names?: string[];
  sender_names?: string[];
}

export interface SenderRelationship {
  sender: string;
  anstrat_key: string;
  match_types: string[];
  evidence: string[];
  confidence: number;
}

export interface SenderSummary {
  total_emails: number;
  jira_issues?: number;
  gdrive_docs?: number;
  anstrat_count: number;
  top_themes: string[];
  coverage: number;
}

export interface StrategyAlignment {
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

export interface PerformanceState {
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

export interface DistributionStats {
  min: number;
  max: number;
  median: number;
  p25: number;
  p75: number;
  avg: number;
  count: number;
}

export interface PeerLevelData {
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

export interface PeerBenchmarks {
  levels: Record<string, PeerLevelData>;
  last_updated: string | null;
}

export interface OrgStats {
  available: boolean;
  total_org_chart: number;
  total_resolved: number;
  total_unresolved: number;
  by_level: Record<string, number>;
  sampled_per_level: Record<string, number>;
  selected_per_level: number;
  generated: string;
}

export interface ExecutiveEmailSummary {
  email_id: string;
  sender: string;
  subject: string;
  date: string;
}

export interface ScoringCompConfig {
  base_points: number;
  phrases: string[];
  keywords: string[];
  event_types: string[];
  name: string;
  category: string;
  level_title?: string;
  level_description?: string;
}

export interface EngineeringLevel {
  id: string;
  name: string;
  short: string;
}

export interface StrategyAlignmentConfig {
  enabled?: boolean;
  bonus_multiplier?: number;
  enrich_classification?: boolean;
  min_text_overlap_words?: number;
}

export interface NpuSettingsConfig {
  enabled?: boolean;
  device?: string;
  confidence_threshold?: number;
  bonus_signals?: number;
}

export interface LevelWeights {
  pillar_weights?: Record<string, number>;
  role_weights?: Record<string, Record<string, number>>;
  target_scale?: number;
}

export interface ScoringConfig {
  min_signals: number;
  daily_cap: number;
  target_per_competency: number;
  engineering_level: string;
  engineering_levels?: EngineeringLevel[];
  competencies: Record<string, ScoringCompConfig>;
  scope_multipliers?: Record<string, number>;
  level_weights?: LevelWeights;
  strategy_alignment?: StrategyAlignmentConfig;
  npu_settings?: NpuSettingsConfig;
}
