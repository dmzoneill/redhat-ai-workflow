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
 * Data is read from the unified workspace_states.json file.
 */

import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// Unified state file
const WORKSPACE_STATE_FILE = path.join(
  os.homedir(),
  ".mcp",
  "workspace_states",
  "workspace_states.json"
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

function loadUnifiedState(): Record<string, unknown> {
  try {
    if (fs.existsSync(WORKSPACE_STATE_FILE)) {
      const content = fs.readFileSync(WORKSPACE_STATE_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) {
    console.error("Failed to load workspace state:", e);
  }
  return {};
}

export function loadPerformanceState(): PerformanceState {
  try {
    const unified = loadUnifiedState();
    const perf = unified.performance as PerformanceState | undefined;
    if (perf) {
      return perf;
    }
  } catch (e) {
    console.error("Failed to load performance state:", e);
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

function getPerformanceTabStyles(): string {
  return `
    /* Performance Tab Styles */
    .performance-container {
      padding: 0;
    }

    .performance-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding: 16px;
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
    }

    .performance-title {
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .performance-meta {
      display: flex;
      gap: 16px;
      align-items: center;
    }

    .quarter-progress {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .quarter-progress-bar {
      width: 200px;
      height: 8px;
      background: var(--bg-secondary);
      border-radius: 4px;
      overflow: hidden;
    }

    .quarter-progress-fill {
      height: 100%;
      background: linear-gradient(90deg, #3b82f6, #60a5fa);
      border-radius: 4px;
      transition: width 0.3s ease;
    }

    .quarter-progress-text {
      font-size: 0.85rem;
      color: var(--text-muted);
    }

    .overall-score {
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--accent-color);
    }

    /* Sunburst Chart Container */
    .sunburst-container {
      display: flex;
      justify-content: center;
      align-items: center;
      padding: 20px;
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
      margin-bottom: 20px;
    }

    .sunburst-svg {
      max-width: 100%;
      height: auto;
    }

    /* Meta Categories Legend */
    .meta-categories {
      display: flex;
      justify-content: center;
      gap: 24px;
      margin-top: 12px;
      font-size: 0.85rem;
    }

    .meta-category {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .meta-category-dot {
      width: 12px;
      height: 12px;
      border-radius: 50%;
    }

    /* Competency Progress Section */
    .competency-section {
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
      padding: 16px;
      margin-bottom: 20px;
    }

    .section-title {
      font-size: 1rem;
      font-weight: 600;
      color: var(--text-primary);
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .competency-row {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
    }

    .competency-name {
      width: 180px;
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    .competency-bar-container {
      flex: 1;
      height: 20px;
      background: var(--bg-secondary);
      border-radius: 10px;
      overflow: hidden;
    }

    .competency-bar-fill {
      height: 100%;
      border-radius: 10px;
      transition: width 0.3s ease;
    }

    .competency-value {
      width: 60px;
      text-align: right;
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--text-primary);
    }

    .competency-status {
      width: 20px;
      text-align: center;
    }

    /* Gaps Alert */
    .gaps-alert {
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid rgba(239, 68, 68, 0.3);
      border-radius: 8px;
      padding: 12px;
      margin-top: 12px;
    }

    .gaps-alert-title {
      font-size: 0.85rem;
      font-weight: 600;
      color: #ef4444;
      margin-bottom: 8px;
    }

    .gaps-list {
      font-size: 0.8rem;
      color: var(--text-secondary);
    }

    /* Questions Section */
    .questions-section {
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
      padding: 16px;
      margin-bottom: 20px;
    }

    .question-card {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 12px;
      margin-bottom: 12px;
    }

    .question-card:last-child {
      margin-bottom: 0;
    }

    .question-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 8px;
    }

    .question-text {
      font-size: 0.9rem;
      font-weight: 500;
      color: var(--text-primary);
      flex: 1;
    }

    .question-status {
      font-size: 0.75rem;
      padding: 2px 8px;
      border-radius: 4px;
      background: var(--bg-primary);
    }

    .question-status.evaluated {
      background: rgba(16, 185, 129, 0.2);
      color: #10b981;
    }

    .question-status.pending {
      background: rgba(245, 158, 11, 0.2);
      color: #f59e0b;
    }

    .question-meta {
      display: flex;
      gap: 16px;
      font-size: 0.8rem;
      color: var(--text-muted);
    }

    .question-actions {
      display: flex;
      gap: 8px;
      margin-top: 8px;
    }

    .question-btn {
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 0.75rem;
      cursor: pointer;
      border: none;
      background: var(--bg-primary);
      color: var(--text-secondary);
      transition: all 0.2s ease;
    }

    .question-btn:hover {
      background: var(--accent-color);
      color: white;
    }

    /* Highlights Section */
    .highlights-section {
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
      padding: 16px;
      margin-bottom: 20px;
    }

    .highlight-item {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 8px 0;
      border-bottom: 1px solid var(--border-color);
      font-size: 0.85rem;
      color: var(--text-secondary);
    }

    .highlight-item:last-child {
      border-bottom: none;
    }

    .highlight-icon {
      color: #10b981;
    }

    /* Manual Entry Section */
    .manual-entry-section {
      background: var(--card-bg);
      border-radius: 12px;
      border: 1px solid var(--border-color);
      padding: 16px;
    }

    .manual-entry-form {
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .manual-entry-select {
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid var(--border-color);
      background: var(--bg-secondary);
      color: var(--text-primary);
      font-size: 0.85rem;
    }

    .manual-entry-input {
      flex: 1;
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid var(--border-color);
      background: var(--bg-secondary);
      color: var(--text-primary);
      font-size: 0.85rem;
    }

    .manual-entry-btn {
      padding: 8px 16px;
      border-radius: 6px;
      border: none;
      background: var(--accent-color);
      color: white;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .manual-entry-btn:hover {
      opacity: 0.9;
    }

    /* Action Buttons */
    .action-buttons {
      display: flex;
      gap: 8px;
      margin-top: 16px;
    }

    .action-btn {
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      border: 1px solid var(--border-color);
      background: var(--bg-secondary);
      color: var(--text-primary);
      transition: all 0.2s ease;
    }

    .action-btn:hover {
      background: var(--accent-color);
      color: white;
      border-color: var(--accent-color);
    }

    .action-btn.primary {
      background: var(--accent-color);
      color: white;
      border-color: var(--accent-color);
    }

    /* Empty State */
    .empty-state {
      text-align: center;
      padding: 48px 24px;
      color: var(--text-muted);
    }

    .empty-state-icon {
      font-size: 3rem;
      margin-bottom: 16px;
    }

    .empty-state-title {
      font-size: 1.1rem;
      font-weight: 500;
      margin-bottom: 8px;
      color: var(--text-secondary);
    }

    .empty-state-text {
      font-size: 0.9rem;
    }
  `;
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
      <div class="empty-state" style="padding: 24px;">
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
    return '<div class="empty-state" style="padding: 16px;"><div class="empty-state-text">Highlights will appear as you complete work.</div></div>';
  }

  return highlights
    .slice(0, 5)
    .map((h) => `<div class="highlight-item"><span class="highlight-icon">✨</span><span>${escapeHtml(h)}</span></div>`)
    .join("");
}

// ==================== MAIN EXPORT ====================

export function getPerformanceTabContent(state: PerformanceState): string {
  const styles = getPerformanceTabStyles();
  const quarterProgress = Math.round((state.day_of_quarter / 90) * 100);

  return `
    <style>${styles}</style>

    <div class="performance-container">
      <!-- Header -->
      <div class="performance-header">
        <div>
          <div class="performance-title">📊 ${escapeHtml(state.quarter)} Quarterly Connection</div>
          <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">
            Day ${state.day_of_quarter} of 90
          </div>
        </div>
        <div class="performance-meta">
          <div class="quarter-progress">
            <div class="quarter-progress-bar">
              <div class="quarter-progress-fill" style="width: ${quarterProgress}%;"></div>
            </div>
            <span class="quarter-progress-text">${quarterProgress}% of quarter</span>
          </div>
          <div class="overall-score">${state.overall_percentage}%</div>
        </div>
      </div>

      <!-- Sunburst Chart -->
      <div class="sunburst-container">
        ${generateSunburstSVG(state)}
      </div>

      <!-- Meta Categories Legend -->
      <div class="meta-categories">
        <div class="meta-category">
          <div class="meta-category-dot" style="background: #3b82f6;"></div>
          <span>Technical Excellence</span>
        </div>
        <div class="meta-category">
          <div class="meta-category-dot" style="background: #8b5cf6;"></div>
          <span>Leadership & Influence</span>
        </div>
        <div class="meta-category">
          <div class="meta-category-dot" style="background: #10b981;"></div>
          <span>Delivery & Impact</span>
        </div>
      </div>

      <!-- Competency Progress -->
      <div class="competency-section">
        <div class="section-title">📈 Competency Progress</div>
        ${renderCompetencyBars(state.competencies)}
        ${renderGapsAlert(state.gaps, state.competencies)}
      </div>

      <!-- Quarterly Questions -->
      <div class="questions-section">
        <div class="section-title" style="display: flex; justify-content: space-between; align-items: center;">
          <span>📋 Quarterly Questions</span>
          <button class="action-btn" data-action="evaluateAll">Re-evaluate All</button>
        </div>
        ${renderQuestions(state.questions_summary)}
      </div>

      <!-- Highlights -->
      <div class="highlights-section">
        <div class="section-title">✨ Recent Highlights</div>
        ${renderHighlights(state.highlights)}
      </div>

      <!-- Manual Entry -->
      <div class="manual-entry-section">
        <div class="section-title">📝 Log Manual Activity</div>
        <div class="manual-entry-form">
          <select class="manual-entry-select" id="activityCategory">
            <option value="speaking">Speaking</option>
            <option value="presentation">Presentation</option>
            <option value="demo">Demo</option>
            <option value="mentorship">Mentorship</option>
            <option value="blog">Blog Post</option>
            <option value="other">Other</option>
          </select>
          <input type="text" class="manual-entry-input" id="activityDescription" placeholder="Description of activity...">
          <button class="manual-entry-btn" data-action="logActivity">Log</button>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="action-buttons">
        <button class="action-btn primary" data-action="collectDaily">🔄 Collect Today's Data</button>
        <button class="action-btn" data-action="backfill">📅 Backfill Missing</button>
        <button class="action-btn" data-action="exportReport">📄 Export Report</button>
      </div>
    </div>

    <script>
      (function() {
        // Action button handlers
        document.querySelectorAll('[data-action]').forEach(btn => {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const action = this.getAttribute('data-action');
            const questionId = this.getAttribute('data-question');

            if (action === 'logActivity') {
              const category = document.getElementById('activityCategory').value;
              const description = document.getElementById('activityDescription').value;
              if (description && vscode) {
                vscode.postMessage({
                  command: 'performanceAction',
                  action: 'logActivity',
                  category: category,
                  description: description
                });
                document.getElementById('activityDescription').value = '';
              }
            } else if (vscode) {
              vscode.postMessage({
                command: 'performanceAction',
                action: action,
                questionId: questionId
              });
            }
          });
        });
      })();
    </script>
  `;
}

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
