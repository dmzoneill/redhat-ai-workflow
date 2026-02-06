/**
 * Performance Tab for Command Center
 *
 * Provides UI for PSE Competency Performance Tracking:
 * - Sunburst chart showing competency progress
 * - Progress bars for individual competencies
 * - Quarterly questions section with evidence counts
 * - Manual activity logging
 * - Highlights and gaps display
 *
 * Data is read from quarterly performance summary files.
 */

import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { createLogger } from "./logger";

const logger = createLogger("PerformanceTab");

// Performance data directory
const PERFORMANCE_DIR = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "performance"
);

// ==================== INTERFACES ====================

export interface CompetencyScore {
  points: number;
  percentage: number;
}

export interface QuestionSummary {
  id: string;
  text: string;
  evidence_count: number;
  notes_count: number;
  has_summary: boolean;
  last_evaluated: string | null;
}

export interface PerformanceState {
  last_updated: string;
  quarter: string;
  day_of_quarter: number;
  overall_percentage: number;
  competencies: Record<string, CompetencyScore>;
  sunburst_data?: SunburstData;
  highlights: string[];
  gaps: string[];
  questions_summary?: QuestionSummary[];
}

export interface SunburstData {
  center: { label: string; value: number };
  inner: SunburstCategory[];
}

export interface SunburstCategory {
  id: string;
  name: string;
  value: number;
  children: SunburstChild[];
}

export interface SunburstChild {
  id: string;
  name: string;
  value: number;
}

// ==================== STATE LOADING ====================

function getPerformanceSummaryPath(): string {
  // Get current quarter's summary file
  const now = new Date();
  const year = now.getFullYear();
  const quarter = Math.floor(now.getMonth() / 3) + 1;
  return path.join(PERFORMANCE_DIR, String(year), `q${quarter}`, "performance", "summary.json");
}

export function loadPerformanceState(): PerformanceState {
  try {
    const summaryPath = getPerformanceSummaryPath();
    if (fs.existsSync(summaryPath)) {
      const content = fs.readFileSync(summaryPath, "utf-8");
      const summary = JSON.parse(content);

      // Map summary.json format to PerformanceState
      return {
        last_updated: summary.last_updated || new Date().toISOString(),
        quarter: getCurrentQuarter(),
        day_of_quarter: getDayOfQuarter(),
        overall_percentage: summary.overall_percentage || 0,
        competencies: summary.competencies || {},
        sunburst_data: summary.sunburst_data,
        highlights: summary.highlights || [],
        gaps: summary.gaps || [],
        questions_summary: summary.questions_summary,
      };
    }
  } catch (e) {
    logger.error("Failed to load performance state", e);
  }

  // Return default state
  return {
    last_updated: new Date().toISOString(),
    quarter: getCurrentQuarter(),
    day_of_quarter: getDayOfQuarter(),
    overall_percentage: 0,
    competencies: {},
    highlights: [],
    gaps: [],
  };
}

function getCurrentQuarter(): string {
  const now = new Date();
  const quarter = Math.floor(now.getMonth() / 3) + 1;
  return `Q${quarter} ${now.getFullYear()}`;
}

function getDayOfQuarter(): number {
  const now = new Date();
  const quarter = Math.floor(now.getMonth() / 3);
  const quarterStart = new Date(now.getFullYear(), quarter * 3, 1);
  return Math.floor((now.getTime() - quarterStart.getTime()) / (1000 * 60 * 60 * 24)) + 1;
}

// ==================== HELPER FUNCTIONS ====================

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function getColorForPercentage(pct: number): string {
  if (pct >= 80) return "#10b981"; // Green
  if (pct >= 50) return "#f59e0b"; // Yellow
  if (pct >= 25) return "#f97316"; // Orange
  return "#ef4444"; // Red
}

function getStatusIcon(pct: number): string {
  if (pct >= 80) return "✓";
  if (pct < 50) return "⚠";
  return "";
}

function formatCompetencyName(id: string): string {
  return id
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// ==================== CSS STYLES ====================
// NOTE: All CSS has been moved to src/webview/styles/unified.css

function getPerformanceTabStyles(): string {
  // All styles are now in unified.css
  return "";
}


// ==================== SVG CHART GENERATION ====================

function generateSunburstSVG(state: PerformanceState): string {
  const width = 350;
  const height = 350;
  const cx = width / 2;
  const cy = height / 2;
  const innerRadius = 55;
  const middleRadius = 100;
  const outerRadius = 145;

  const competencies = state.competencies;
  const overall = state.overall_percentage;

  // Define meta-categories
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

  // Center circle with overall percentage
  const centerColor = getColorForPercentage(overall);
  paths += `
    <circle cx="${cx}" cy="${cy}" r="${innerRadius - 5}" fill="${centerColor}" opacity="0.2"/>
    <text x="${cx}" y="${cy - 8}" text-anchor="middle" dominant-baseline="middle"
          font-size="28" font-weight="bold" fill="${centerColor}">${overall}%</text>
    <text x="${cx}" y="${cy + 14}" text-anchor="middle"
          font-size="10" fill="var(--text-muted, #888)">Overall</text>
  `;

  // Inner ring - meta categories
  const categoryAngle = 360 / metaCategories.length;
  let startAngle = -90;

  metaCategories.forEach((cat, catIndex) => {
    // Calculate category average
    const catValues = cat.competencies.map((c) => competencies[c]?.percentage || 0);
    const catAvg = catValues.length > 0 ? Math.round(catValues.reduce((a, b) => a + b, 0) / catValues.length) : 0;
    const catColor = getColorForPercentage(catAvg);

    // Draw category arc
    const catPath = arcPath(cx, cy, innerRadius, middleRadius, startAngle, categoryAngle - 2);
    paths += `
      <path d="${catPath}" fill="${catColor}" opacity="0.5" stroke="var(--bg-primary, #1a1a2e)" stroke-width="2">
        <title>${cat.name}: ${catAvg}%</title>
      </path>
    `;

    // Outer ring - individual competencies
    const compAngle = categoryAngle / cat.competencies.length;
    let compStart = startAngle;

    cat.competencies.forEach((compId) => {
      const compPct = competencies[compId]?.percentage || 0;
      const compColor = getColorForPercentage(compPct);
      const compPath = arcPath(cx, cy, middleRadius, outerRadius, compStart, compAngle - 1);

      paths += `
        <path d="${compPath}" fill="${compColor}" opacity="0.8"
              stroke="var(--bg-primary, #1a1a2e)" stroke-width="1">
          <title>${formatCompetencyName(compId)}: ${compPct}%</title>
        </path>
      `;

      compStart += compAngle;
    });

    startAngle += categoryAngle;
  });

  return `
    <svg class="sunburst-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
         xmlns="http://www.w3.org/2000/svg">
      <style>
        text { font-family: system-ui, -apple-system, sans-serif; }
      </style>
      ${paths}
    </svg>
  `;
}

function arcPath(
  cx: number,
  cy: number,
  innerR: number,
  outerR: number,
  startAngle: number,
  sweepAngle: number
): string {
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

// ==================== HTML GENERATION ====================

function renderCompetencyBars(competencies: Record<string, CompetencyScore>): string {
  const sorted = Object.entries(competencies).sort((a, b) => b[1].percentage - a[1].percentage);

  if (sorted.length === 0) {
    return '<div class="empty-state"><div class="empty-state-text">No competency data yet. Run daily collection to start tracking.</div></div>';
  }

  return sorted
    .map(([id, score]) => {
      const color = getColorForPercentage(score.percentage);
      const icon = getStatusIcon(score.percentage);
      return `
        <div class="competency-row">
          <span class="competency-name">${escapeHtml(formatCompetencyName(id))}</span>
          <div class="competency-bar-container">
            <div class="competency-bar-fill" style="width: ${Math.min(score.percentage, 100)}%; background: ${color};"></div>
          </div>
          <span class="competency-value">${score.percentage}%</span>
          <span class="competency-status">${icon}</span>
        </div>
      `;
    })
    .join("");
}

function renderGapsAlert(gaps: string[], competencies: Record<string, CompetencyScore>): string {
  if (gaps.length === 0) return "";

  const gapsList = gaps
    .map((gap) => {
      const pct = competencies[gap]?.percentage || 0;
      return `${formatCompetencyName(gap)} (${pct}%)`;
    })
    .join(", ");

  return `
    <div class="gaps-alert">
      <div class="gaps-alert-title">⚠️ Areas Needing Attention</div>
      <div class="gaps-list">${escapeHtml(gapsList)}</div>
    </div>
  `;
}

function renderQuestions(questions: QuestionSummary[] | undefined): string {
  if (!questions || questions.length === 0) {
    return `
      <div class="empty-state p-24">
        <div class="empty-state-text">Questions will appear after first data collection.</div>
      </div>
    `;
  }

  return questions
    .map((q) => {
      const statusClass = q.has_summary ? "evaluated" : "pending";
      const statusText = q.has_summary ? "🤖 Evaluated" : "⏳ Pending";
      const evalDate = q.last_evaluated ? ` (${q.last_evaluated.substring(0, 10)})` : "";

      return `
        <div class="question-card" data-question-id="${escapeHtml(q.id)}">
          <div class="question-header">
            <span class="question-text">${escapeHtml(q.text)}</span>
            <span class="question-status ${statusClass}">${statusText}${evalDate}</span>
          </div>
          <div class="question-meta">
            <span>📊 ${q.evidence_count} evidence</span>
            <span>📝 ${q.notes_count} notes</span>
          </div>
          <div class="question-actions">
            <button class="question-btn" data-action="viewSummary" data-question="${escapeHtml(q.id)}">View Summary</button>
            <button class="question-btn" data-action="addNote" data-question="${escapeHtml(q.id)}">Add Note</button>
            <button class="question-btn" data-action="evaluate" data-question="${escapeHtml(q.id)}">Evaluate</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderHighlights(highlights: string[]): string {
  if (highlights.length === 0) {
    return '<div class="empty-state p-16"><div class="empty-state-text">Highlights will appear as you complete work.</div></div>';
  }

  return highlights
    .slice(0, 5)
    .map((h) => `<div class="highlight-item"><span class="highlight-icon">✨</span><span>${escapeHtml(h)}</span></div>`)
    .join("");
}

// ==================== MAIN EXPORT ====================

// NOTE: getPerformanceTabContent() was removed as dead code.
// The PerformanceTab class in tabs/PerformanceTab.ts provides the actual implementation.

export function getEmptyPerformanceState(): PerformanceState {
  return {
    last_updated: new Date().toISOString(),
    quarter: getCurrentQuarter(),
    day_of_quarter: getDayOfQuarter(),
    overall_percentage: 0,
    competencies: {},
    highlights: [],
    gaps: [],
  };
}
