/**
 * Performance Tab Configuration Constants
 *
 * All hardcoded values extracted from PerformanceTab.ts.
 * Inline JS sections that duplicate these values should reference this
 * file's exports (or embed them via JSON.stringify where needed).
 */

// ------------------------------------------------------------------
// Engineering Level labels, colors, and scales
// ------------------------------------------------------------------

export const LEVEL_LABELS: Record<string, string> = {
  ase: "Associate SE",
  se: "Software Engineer",
  sse: "Senior SE",
  pse: "Principal SE",
  spse: "Sr Principal SE",
  de: "Distinguished",
  sde: "Sr Distinguished",
  fellow: "Fellow",
};

export const LEVEL_COLORS: Record<string, string> = {
  ase: "#64748b",
  se: "#3b82f6",
  sse: "#06b6d4",
  pse: "#8b5cf6",
  spse: "#f59e0b",
  de: "#ef4444",
  you: "#10b981",
};

export const LEVEL_SCALES: Record<string, number> = {
  ase: 0.65,
  se: 0.9,
  sse: 1.25,
  pse: 1.6,
  spse: 2.0,
  de: 2.5,
  sde: 3.1,
  fellow: 3.75,
};

export const DEFAULT_LEVEL_SCALE = 1.25;

// ------------------------------------------------------------------
// Data-source colors
// ------------------------------------------------------------------

export const SOURCE_COLORS: Record<string, string> = {
  git: "#f97316",
  jira: "#3b82f6",
  gitlab: "#8b5cf6",
  github: "#10b981",
  gdrive: "#22c55e",
  meeting: "#ec4899",
};

// ------------------------------------------------------------------
// Scope multipliers (commit → strategy), colors, and labels
// ------------------------------------------------------------------

export const DEFAULT_SCOPE_MULTIPLIERS: Record<string, number> = {
  commit: 1,
  story: 2,
  epic: 4,
  anstrat: 7,
  strategy: 10,
};

export const SCOPE_COLORS: Record<string, string> = {
  commit: "#3b82f6",
  story: "#10b981",
  epic: "#f59e0b",
  anstrat: "#ef4444",
  meeting: "#8b5cf6",
  doc: "#06b6d4",
};

export const SCOPE_LABELS: Record<string, string> = {
  commit: "Git Commits",
  story: "Stories / Tasks / Bugs",
  epic: "Epics",
  anstrat: "Initiatives (ANSTRAT)",
  strategy: "Executive Priorities",
};

// ------------------------------------------------------------------
// Pillar definitions (matches Red Hat Engineering Competencies)
// ------------------------------------------------------------------

export const PILLAR_DEFS: Record<string, { color: string; icon: string }> = {
  "Technical Contribution": { color: "#2196F3", icon: "\u{1F527}" },
  Leadership: { color: "#F44336", icon: "\u{1F310}" },
  Mentorship: { color: "#FF9800", icon: "\u{1F393}" },
  "End-to-End Delivery": { color: "#4CAF50", icon: "\u{1F680}" },
};

export const PILLAR_NAMES = [
  "Technical Contribution",
  "Leadership",
  "Mentorship",
  "End-to-End Delivery",
] as const;

// ------------------------------------------------------------------
// Tag category mapping and colors
// ------------------------------------------------------------------

export const TAG_CATEGORY_MAP: Record<string, string> = {
  feat: "worktype",
  fix: "worktype",
  refactor: "worktype",
  test: "quality",
  review: "quality",
  docs: "quality",
  billing: "domain",
  auth: "domain",
  api: "domain",
  config: "domain",
  mock: "domain",
  deploy: "ops",
  pipeline: "ops",
  "ci/cd": "ops",
  release: "ops",
  grafana: "monitoring",
  monitoring: "monitoring",
  alert: "monitoring",
  security: "monitoring",
  performance: "monitoring",
  migration: "ops",
  integration: "domain",
};

export const TAG_CATEGORY_COLORS: Record<string, string> = {
  worktype: "#3b82f6",
  quality: "#10b981",
  domain: "#8b5cf6",
  ops: "#f97316",
  monitoring: "#ef4444",
  other: "#6b7280",
};

// ------------------------------------------------------------------
// Color thresholds (percentage → color)
// ------------------------------------------------------------------

export const COLOR_THRESHOLDS = {
  excellent: { min: 80, color: "#10b981" },
  good: { min: 50, color: "#f59e0b" },
  warning: { min: 25, color: "#f97316" },
  poor: { min: 0, color: "#ef4444" },
} as const;

export const COVERAGE_THRESHOLDS = {
  good: { min: 70, color: "#10b981" },
  fair: { min: 40, color: "#f59e0b" },
  poor: { min: 0, color: "#ef4444" },
} as const;

export const FORECAST_THRESHOLDS = {
  positive: 80,
  neutral: 60,
} as const;

export const PEER_SAMPLE_THRESHOLDS = {
  minimum: 3,
  adequate: 5,
} as const;

// ------------------------------------------------------------------
// Numeric limits
// ------------------------------------------------------------------

export const QUARTER_DAYS = 90;
export const TAG_BAR_MAX = 10;
export const SUBJECT_MAX_LEN = 60;
export const LABEL_MAX_LEN = 12;

// ------------------------------------------------------------------
// URLs
// ------------------------------------------------------------------

export const JIRA_BROWSE_URL = "https://issues.redhat.com/browse/";

// ------------------------------------------------------------------
// Mindmap physics defaults
// ------------------------------------------------------------------

export const MINDMAP_PHYSICS_DEFAULTS = {
  chargeStrength: -200,
  linkDistance: 120,
  collisionRadius: 4,
  radialScale: 1.0,
  alphaDecay: 0.012,
  velocityDecay: 0.35,
} as const;

export const MINDMAP_SLIDER_RANGES = {
  charge: { min: -800, max: 0, step: 10, initial: -200 },
  linkDist: { min: 20, max: 400, step: 5, initial: 120 },
  collision: { min: 0, max: 30, step: 1, initial: 4 },
  radial: { min: 20, max: 300, step: 5, initial: 100 },
  decay: { min: 1, max: 100, step: 1, initial: 12 },
  velocity: { min: 0, max: 100, step: 1, initial: 35 },
} as const;

// ------------------------------------------------------------------
// NPU threshold default
// ------------------------------------------------------------------

export const DEFAULT_NPU_CONFIDENCE_THRESHOLD = 0.35;

// ------------------------------------------------------------------
// Tab definitions
// ------------------------------------------------------------------

export const PERFORMANCE_TABS = [
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
] as const;

// ------------------------------------------------------------------
// Default role weights per level (scope × role → weight)
// ------------------------------------------------------------------

export const ROLE_WEIGHTS_ALL: Record<
  string,
  Record<string, Record<string, number>>
> = {
  ase: {
    commit: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
    story: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
    epic: { reporter: 3.0, assignee: 2.0, contributor: 1.0 },
    anstrat: { reporter: 5.0, assignee: 4.0, contributor: 2.0 },
    strategy: { reporter: 6.0, assignee: 5.0, contributor: 2.5 },
  },
  se: {
    commit: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
    story: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
    epic: { reporter: 2.5, assignee: 1.8, contributor: 0.8 },
    anstrat: { reporter: 4.0, assignee: 3.0, contributor: 1.5 },
    strategy: { reporter: 5.0, assignee: 4.0, contributor: 2.0 },
  },
  sse: {
    commit: { reporter: 0.8, assignee: 0.8, contributor: 0.4 },
    story: { reporter: 0.8, assignee: 0.8, contributor: 0.4 },
    epic: { reporter: 1.5, assignee: 1.2, contributor: 0.6 },
    anstrat: { reporter: 3.0, assignee: 2.0, contributor: 1.0 },
    strategy: { reporter: 4.0, assignee: 3.0, contributor: 1.5 },
  },
  pse: {
    commit: { reporter: 0.4, assignee: 0.4, contributor: 0.2 },
    story: { reporter: 0.5, assignee: 0.4, contributor: 0.2 },
    epic: { reporter: 1.0, assignee: 0.8, contributor: 0.4 },
    anstrat: { reporter: 1.5, assignee: 1.2, contributor: 0.6 },
    strategy: { reporter: 2.0, assignee: 1.5, contributor: 0.8 },
  },
  spse: {
    commit: { reporter: 0.3, assignee: 0.3, contributor: 0.1 },
    story: { reporter: 0.3, assignee: 0.2, contributor: 0.1 },
    epic: { reporter: 0.7, assignee: 0.5, contributor: 0.3 },
    anstrat: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
    strategy: { reporter: 1.5, assignee: 1.2, contributor: 0.6 },
  },
  de: {
    commit: { reporter: 0.2, assignee: 0.2, contributor: 0.1 },
    story: { reporter: 0.2, assignee: 0.2, contributor: 0.1 },
    epic: { reporter: 0.5, assignee: 0.4, contributor: 0.2 },
    anstrat: { reporter: 0.8, assignee: 0.8, contributor: 0.4 },
    strategy: { reporter: 1.2, assignee: 1.0, contributor: 0.5 },
  },
  sde: {
    commit: { reporter: 0.1, assignee: 0.1, contributor: 0.05 },
    story: { reporter: 0.1, assignee: 0.1, contributor: 0.05 },
    epic: { reporter: 0.4, assignee: 0.3, contributor: 0.15 },
    anstrat: { reporter: 0.7, assignee: 0.7, contributor: 0.35 },
    strategy: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
  },
  fellow: {
    commit: { reporter: 0.1, assignee: 0.1, contributor: 0.05 },
    story: { reporter: 0.1, assignee: 0.1, contributor: 0.05 },
    epic: { reporter: 0.3, assignee: 0.2, contributor: 0.1 },
    anstrat: { reporter: 0.6, assignee: 0.6, contributor: 0.3 },
    strategy: { reporter: 1.0, assignee: 1.0, contributor: 0.5 },
  },
};

// ------------------------------------------------------------------
// Default pillar weights per level
// ------------------------------------------------------------------

export const PILLAR_WEIGHTS_ALL: Record<string, Record<string, number>> = {
  ase: {
    "Technical Contribution": 1.3,
    Leadership: 0.5,
    Mentorship: 0.3,
    "End-to-End Delivery": 0.8,
  },
  se: {
    "Technical Contribution": 1.2,
    Leadership: 0.7,
    Mentorship: 0.5,
    "End-to-End Delivery": 1.0,
  },
  sse: {
    "Technical Contribution": 1.0,
    Leadership: 1.0,
    Mentorship: 0.8,
    "End-to-End Delivery": 1.0,
  },
  pse: {
    "Technical Contribution": 0.8,
    Leadership: 1.3,
    Mentorship: 1.2,
    "End-to-End Delivery": 1.2,
  },
  spse: {
    "Technical Contribution": 0.7,
    Leadership: 1.4,
    Mentorship: 1.3,
    "End-to-End Delivery": 1.3,
  },
  de: {
    "Technical Contribution": 0.6,
    Leadership: 1.5,
    Mentorship: 1.4,
    "End-to-End Delivery": 1.4,
  },
  sde: {
    "Technical Contribution": 0.5,
    Leadership: 1.5,
    Mentorship: 1.5,
    "End-to-End Delivery": 1.5,
  },
  fellow: {
    "Technical Contribution": 0.5,
    Leadership: 1.5,
    Mentorship: 1.5,
    "End-to-End Delivery": 1.5,
  },
};

// ------------------------------------------------------------------
// Helper functions (shared color logic)
// ------------------------------------------------------------------

/** Map percentage to RAG color using standard thresholds */
export function getColorForPercentage(pct: number): string {
  if (pct >= COLOR_THRESHOLDS.excellent.min) return COLOR_THRESHOLDS.excellent.color;
  if (pct >= COLOR_THRESHOLDS.good.min) return COLOR_THRESHOLDS.good.color;
  if (pct >= COLOR_THRESHOLDS.warning.min) return COLOR_THRESHOLDS.warning.color;
  return COLOR_THRESHOLDS.poor.color;
}

/** Map percentage to coverage bar color */
export function getCoverageColor(pct: number): string {
  if (pct >= COVERAGE_THRESHOLDS.good.min) return COVERAGE_THRESHOLDS.good.color;
  if (pct >= COVERAGE_THRESHOLDS.fair.min) return COVERAGE_THRESHOLDS.fair.color;
  return COVERAGE_THRESHOLDS.poor.color;
}

/** Map percentage to CSS variable bar color (uses --success/--warning/--error) */
export function getBarColor(
  pct: number,
  variant: "standard" | "coverage" = "standard",
): string {
  if (variant === "coverage") {
    return pct >= 70
      ? "var(--success)"
      : pct >= 40
        ? "var(--warning)"
        : "var(--error)";
  }
  if (pct >= 80) return "var(--success)";
  if (pct >= 50) return "var(--warning)";
  if (pct >= 25) return "#f97316";
  return "var(--error)";
}

/** Get tag category from tag name */
export function getTagCategory(tag: string): string {
  return TAG_CATEGORY_MAP[tag] || "other";
}

/** Get color for a tag category */
export function getTagCategoryColor(tag: string): string {
  return TAG_CATEGORY_COLORS[getTagCategory(tag)] || TAG_CATEGORY_COLORS.other;
}

// ------------------------------------------------------------------
// Hex/HSL conversion and pillar tinting (shared by mindmap, competencies)
// ------------------------------------------------------------------

/** Convert hex color to HSL [h, s, l] */
export function hexToHsl(hex: string): [number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b);
  let h = 0,
    s = 0;
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

/** Convert HSL to hex color */
export function hslToHex(h: number, s: number, l: number): string {
  const sn = s / 100,
    ln = l / 100;
  const a = sn * Math.min(ln, 1 - ln);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = ln - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color)
      .toString(16)
      .padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

export type PillarTintType = "competency" | "anstrat" | "epic" | "issue" | "strategy";

/**
 * Derive a pillar-affiliated color from the base pillar hex.
 * - competency: pillar hue, saturation scaled by score
 * - anstrat: pillar hue lightened 10%
 * - epic: pillar hue lightened 25%
 * - issue: pillar hue lightened 35%, reduced saturation
 * - strategy: pillar hue; covered=bright, gap=desaturated+lighter
 */
export function pillarTint(
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
