/**
 * Performance Tab (QC)
 *
 * Provides UI for PSE Competency Performance Tracking:
 * - Sunburst chart showing competency progress
 * - Progress bars for individual competencies
 * - Quarterly questions section with evidence counts
 * - Manual activity logging
 * - Highlights and gaps display
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("PerformanceTab");

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

interface PerformanceState {
  last_updated: string;
  quarter: string;
  day_of_quarter: number;
  overall_percentage: number;
  competencies: Record<string, CompetencyScore>;
  highlights: string[];
  gaps: string[];
  questions_summary?: QuestionSummary[];
}

export class PerformanceTab extends BaseTab {
  private state: PerformanceState = {
    last_updated: new Date().toISOString(),
    quarter: this.getCurrentQuarter(),
    day_of_quarter: this.getDayOfQuarter(),
    overall_percentage: 0,
    competencies: {},
    highlights: [],
    gaps: [],
  };

  constructor() {
    super({
      id: "performance",
      label: "QC",
      icon: "📊",
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

  async loadData(): Promise<void> {
    try {
      // Load performance state from stats daemon
      const result = await dbus.stats_getState();
      if (result.success && result.data) {
        // The data structure is { state: { performance: {...}, ... } }
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
    } catch (error) {
      logger.error("Error loading data", error);
    }
  }

  getContent(): string {
    const quarterProgress = Math.round((this.state.day_of_quarter / 90) * 100);

    return `
      <!-- Header -->
      <div class="perf-header">
        <div class="perf-header-info">
          <div class="perf-title">📊 ${this.escapeHtml(this.state.quarter)} Quarterly Connection</div>
          <div class="perf-subtitle">Day ${this.state.day_of_quarter} of 90</div>
        </div>
        <div class="perf-header-stats">
          <div class="perf-quarter-progress">
            <div class="perf-progress-bar">
              <div class="perf-progress-fill" style="width: ${quarterProgress}%;"></div>
            </div>
            <span class="perf-progress-text">${quarterProgress}% of quarter</span>
          </div>
          <div class="perf-overall-score">${this.state.overall_percentage}%</div>
        </div>
      </div>

      <!-- Sunburst Chart -->
      <div class="section">
        <div class="perf-sunburst-container">
          ${this.generateSunburstSVG()}
        </div>
        <div class="perf-meta-categories">
          <div class="perf-meta-category">
            <div class="perf-meta-dot blue"></div>
            <span>Technical Excellence</span>
          </div>
          <div class="perf-meta-category">
            <div class="perf-meta-dot purple"></div>
            <span>Leadership & Influence</span>
          </div>
          <div class="perf-meta-category">
            <div class="perf-meta-dot green"></div>
            <span>Delivery & Impact</span>
          </div>
        </div>
      </div>

      <!-- Competency Progress -->
      <div class="section">
        <div class="section-title">📈 Competency Progress</div>
        ${this.renderCompetencyBars()}
        ${this.renderGapsAlert()}
      </div>

      <!-- Quarterly Questions -->
      <div class="section">
        <div class="section-title">
          <span>📋 Quarterly Questions</span>
          <button class="btn btn-xs" data-action="evaluateAll">Re-evaluate All</button>
        </div>
        ${this.renderQuestions()}
      </div>

      <!-- Highlights -->
      <div class="section">
        <div class="section-title">✨ Recent Highlights</div>
        ${this.renderHighlights()}
      </div>

      <!-- Manual Entry -->
      <div class="section">
        <div class="section-title">📝 Log Manual Activity</div>
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

      <!-- Action Buttons -->
      <div class="perf-actions">
        <button class="btn btn-sm btn-primary" data-action="collectDaily">🔄 Collect Today's Data</button>
        <button class="btn btn-sm" data-action="backfill">📅 Backfill Missing</button>
        <button class="btn btn-sm" data-action="exportReport">📄 Export Report</button>
      </div>
    `;
  }

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

    // Center circle with overall percentage
    const centerColor = this.getColorForPercentage(overall);
    paths += `
      <circle cx="${cx}" cy="${cy}" r="${innerRadius - 5}" fill="${centerColor}" opacity="0.2"/>
      <text x="${cx}" y="${cy - 8}" text-anchor="middle" dominant-baseline="middle"
            font-size="28" font-weight="bold" fill="${centerColor}">${overall}%</text>
      <text x="${cx}" y="${cy + 14}" text-anchor="middle"
            font-size="10" fill="#888">Overall</text>
    `;

    // Inner ring - meta categories
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

  private renderCompetencyBars(): string {
    const sorted = Object.entries(this.state.competencies).sort((a, b) => b[1].percentage - a[1].percentage);

    if (sorted.length === 0) {
      return this.getEmptyStateHtml("📊", "No competency data yet. Run daily collection to start tracking.");
    }

    return sorted.map(([id, score]) => {
      const color = this.getColorForPercentage(score.percentage);
      const icon = score.percentage >= 80 ? "✓" : score.percentage < 50 ? "⚠" : "";

      return `
        <div class="perf-competency-row">
          <span class="perf-competency-name">${this.escapeHtml(this.formatCompetencyName(id))}</span>
          <div class="perf-competency-bar">
            <div class="perf-competency-fill" style="width: ${Math.min(score.percentage, 100)}%; background: ${color};"></div>
          </div>
          <span class="perf-competency-value">${score.percentage}%</span>
          <span class="perf-competency-status">${icon}</span>
        </div>
      `;
    }).join("");
  }

  private renderGapsAlert(): string {
    if (this.state.gaps.length === 0) return "";

    const gapsList = this.state.gaps.map((gap) => {
      const pct = this.state.competencies[gap]?.percentage || 0;
      return `${this.formatCompetencyName(gap)} (${pct}%)`;
    }).join(", ");

    return `
      <div class="perf-gaps-alert">
        <div class="perf-gaps-title">⚠️ Areas Needing Attention</div>
        <div class="perf-gaps-list">${this.escapeHtml(gapsList)}</div>
      </div>
    `;
  }

  private renderQuestions(): string {
    const questions = this.state.questions_summary;
    if (!questions || questions.length === 0) {
      return this.getEmptyStateHtml("📋", "Questions will appear after first data collection.");
    }

    return questions.map((q) => {
      const statusClass = q.has_summary ? "evaluated" : "pending";
      const statusText = q.has_summary ? "🤖 Evaluated" : "⏳ Pending";

      return `
        <div class="perf-question-card" data-question-id="${this.escapeHtml(q.id)}">
          <div class="perf-question-header">
            <span class="perf-question-text">${this.escapeHtml(q.text)}</span>
            <span class="perf-question-status ${statusClass}">${statusText}</span>
          </div>
          <div class="perf-question-meta">
            <span>📊 ${q.evidence_count} evidence</span>
            <span>📝 ${q.notes_count} notes</span>
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

  private renderHighlights(): string {
    if (this.state.highlights.length === 0) {
      return this.getEmptyStateHtml("✨", "Highlights will appear as you complete work.");
    }

    return this.state.highlights.slice(0, 5).map((h) => `
      <div class="perf-highlight-item">
        <span class="perf-highlight-icon">✨</span>
        <span>${this.escapeHtml(h)}</span>
      </div>
    `).join("");
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return `
      // Performance Tab initialization
      (function() {
        document.querySelectorAll('[data-action]').forEach(btn => {
          btn.addEventListener('click', function(e) {
            e.stopPropagation();
            const action = this.getAttribute('data-action');
            const questionId = this.getAttribute('data-question');

            if (action === 'logActivity') {
              const category = document.getElementById('activityCategory')?.value;
              const description = document.getElementById('activityDescription')?.value;
              if (description) {
                vscode.postMessage({
                  command: 'performanceAction',
                  action: 'logActivity',
                  category: category,
                  description: description
                });
                document.getElementById('activityDescription').value = '';
              }
            } else {
              vscode.postMessage({
                command: 'performanceAction',
                action: action,
                questionId: questionId
              });
            }
          });
        });
      })();
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "performanceDataUpdate":
        if (message.data) {
          this.state = { ...this.state, ...message.data };
        }
        return true;

      default:
        return false;
    }
  }
}
