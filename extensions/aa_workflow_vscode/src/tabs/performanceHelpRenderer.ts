/**
 * Performance Help Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getHelpContent for the
 * scoring reference guide with inline JS for interactive diagrams.
 */

import type { PerformanceState } from "./performanceTypes";
import {
  PILLAR_DEFS,
  LEVEL_SCALES,
  DEFAULT_SCOPE_MULTIPLIERS,
  SCOPE_LABELS,
  ROLE_WEIGHTS_ALL,
  PILLAR_WEIGHTS_ALL,
  DEFAULT_LEVEL_SCALE,
} from "./performanceConfig";

export interface HelpHelpers {
  formatCompetencyName(id: string): string;
  escapeHtml(s: string): string;
}

function renderSignalLookupRows(
  state: PerformanceState,
  helpers: HelpHelpers
): string {
  const cfg = state.scoring_config;
  if (!cfg?.competencies)
    return '<tr><td colspan="6" class="text-secondary">No scoring config loaded.</td></tr>';

  return Object.entries(cfg.competencies)
    .map(([id, c]) => {
      const pillarColor = PILLAR_DEFS[c.category]?.color || "#888";
      const eventTypes =
        c.event_types.length > 0
          ? c.event_types.join(", ")
          : "<span class='text-secondary'>--</span>";
      const phrases =
        c.phrases
          .slice(0, 5)
          .map((p) => `<code>${helpers.escapeHtml(p)}</code>`)
          .join(" ") +
        (c.phrases.length > 5
          ? ` <span class="text-secondary">+${c.phrases.length - 5} more</span>`
          : "");
      const keywords =
        c.keywords
          .slice(0, 5)
          .map((k) => `<code>${helpers.escapeHtml(k)}</code>`)
          .join(" ") +
        (c.keywords.length > 5
          ? ` <span class="text-secondary">+${c.keywords.length - 5} more</span>`
          : "");

      return `
        <tr class="perf-help-signal-row" data-search="${helpers.escapeHtml(
          (c.name +
            " " +
            c.category +
            " " +
            c.event_types.join(" ") +
            " " +
            c.phrases.join(" ") +
            " " +
            c.keywords.join(" ")
          ).toLowerCase()
        )}">
          <td><strong>${helpers.escapeHtml(c.name)}</strong></td>
          <td><span class="perf-help-pillar-badge" style="background:${pillarColor}22;color:${pillarColor};border:1px solid ${pillarColor}44">${helpers.escapeHtml(c.category)}</span></td>
          <td class="text-center">${c.base_points}</td>
          <td class="text-sm">${eventTypes}</td>
          <td class="text-sm">${phrases}</td>
          <td class="text-sm">${keywords}</td>
        </tr>
      `;
    })
    .join("");
}

export function getHelpContent(
  state: PerformanceState,
  helpers: HelpHelpers
): string {
  const cfg = state.scoring_config;
  const level = cfg?.engineering_level || "sse";
  const levels = cfg?.engineering_levels || [];
  const levelName =
    levels.find((l) => l.id === level)?.name || level.toUpperCase();

  const scopeMultipliers = DEFAULT_SCOPE_MULTIPLIERS;
  const scopeLabels = SCOPE_LABELS;

  const levelScales = LEVEL_SCALES;
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

  const roleWeightsAll = ROLE_WEIGHTS_ALL;
  const pillarWeightsAll = PILLAR_WEIGHTS_ALL;

  const roleWeights = roleWeightsAll[level] || roleWeightsAll["sse"];
  const pillarWeights = pillarWeightsAll[level] || pillarWeightsAll["sse"];
  const targetScale = levelScales[level] || DEFAULT_LEVEL_SCALE;
  const baseTarget = cfg?.target_per_competency || 100;
  const effectiveTarget = Math.max(Math.round(baseTarget * targetScale), 1);
  const minSignals = cfg?.min_signals || 2;
  const dailyCap = cfg?.daily_cap || 15;

  const competencyData = Object.entries(state.competencies).map(
    ([id, c]) => {
      const meta = state.competency_meta[id];
      return {
        id,
        name: meta?.name || helpers.formatCompetencyName(id),
        category: meta?.category || "Other",
        points: c.points,
        percentage: c.percentage,
      };
    }
  );

  const competencyDefs = Object.entries(cfg?.competencies || {}).map(
    ([id, c]) => ({
      id,
      name: c.name,
      base_points: c.base_points,
      category: c.category,
    })
  );

  const helpData = JSON.stringify({
    level,
    levelName,
    scopeMultipliers,
    scopeLabels,
    roleWeightsAll,
    pillarWeightsAll,
    levelScales,
    levelSummaries,
    baseTarget,
    minSignals,
    dailyCap,
    pillarColors: Object.fromEntries(
      Object.entries(PILLAR_DEFS).map(([k, v]) => [k, v.color])
    ),
    competencyData,
    competencyDefs,
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
            <p class="text-secondary text-sm">Interactive graph showing how each event is scored. Adjust the controls to see how vertices change the scoring path. Level: <strong>${helpers.escapeHtml(levelName)}</strong>.</p>
            <div class="dag-controls">
              <div class="dag-control-group">
                <label class="dag-control-label">Competency</label>
                <select id="dag-comp" class="perf-help-select">
                  ${Object.entries(cfg?.competencies || {})
                    .map(
                      ([id, c]) =>
                        `<option value="${id}" data-base="${c.base_points}" data-category="${helpers.escapeHtml(c.category)}">${helpers.escapeHtml(c.name)} (${c.base_points})</option>`
                    )
                    .join("")}
                </select>
              </div>
              <div class="dag-control-group">
                <label class="dag-control-label">Scope</label>
                <select id="dag-scope" class="perf-help-select">
                  ${Object.entries(scopeMultipliers)
                    .map(
                      ([s, m]) =>
                        `<option value="${s}" ${s === "epic" ? "selected" : ""}>x${m} ${helpers.escapeHtml(scopeLabels[s] || s)}</option>`
                    )
                    .join("")}
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
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-input"></span>Input</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-multiplier"></span>Multiplier</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-gate"></span>Gate</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-output"></span>Output</span>
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-cap"></span>Blocked / Capped</span>
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
                  ${renderSignalLookupRows(state, helpers)}
                </tbody>
              </table>
            </div>
          </div>
        </details>

        <!-- ===== GROUP 2: Your Configuration ===== -->
        <details class="perf-help-group" open>
          <summary class="perf-help-group-header">Your Configuration (${helpers.escapeHtml(levelName)})</summary>

          <!-- 2.1 Engineering Levels -->
          <div class="section perf-help-section">
            <div class="section-title">Engineering Levels &amp; Target Scales</div>
            <p class="text-secondary text-sm">Your level determines the effective target per competency. Higher levels have higher targets, reflecting broader expected impact.</p>
            <div id="perf-help-levels" class="perf-help-diagram perf-help-levels-container"></div>
            <div class="perf-help-legend">
              <span class="perf-help-legend-item"><span class="perf-help-dot perf-help-dot-current"></span>Your Level (${helpers.escapeHtml(level.toUpperCase())})</span>
              <span class="perf-help-legend-item">effective_target = ${baseTarget} &times; target_scale</span>
            </div>
          </div>

          <!-- 2.2 Role Weight Heatmap -->
          <div class="section perf-help-section">
            <div class="section-title">Role Weight Matrix (${helpers.escapeHtml(level.toUpperCase())})</div>
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
            <div class="section-title">Pillar Weight Balance (${helpers.escapeHtml(level.toUpperCase())})</div>
            <p class="text-secondary text-sm">How the four competency pillars are weighted at your level. Junior levels emphasize Technical Contribution; senior levels shift toward Leadership and Mentorship.</p>
            <div id="perf-help-radar" class="perf-help-diagram perf-help-radar-container"></div>
            <div class="perf-help-legend">
              ${Object.entries(PILLAR_DEFS)
                .map(
                  ([name, def]) =>
                    `<span class="perf-help-legend-item"><span class="perf-help-dot" style="background:${def.color}"></span>${helpers.escapeHtml(name)}: ${pillarWeights[name] ?? "?"}</span>`
                )
                .join("")}
            </div>
          </div>

          <!-- 2.4 Level Comparison -->
          <div class="section perf-help-section">
            <div class="section-title">Level Comparison</div>
            <p class="text-secondary text-sm">Compare your current level with another to see how weights and targets change.</p>
            <div class="perf-help-compare-controls">
              <span class="text-sm">Your level: <strong>${helpers.escapeHtml(level.toUpperCase())}</strong></span>
              <span class="text-sm">Compare with:</span>
              <select id="perf-help-compare-level" class="perf-help-select">
                ${Object.keys(levelScales)
                  .filter((l) => l !== level)
                  .map((l) => `<option value="${l}">${l.toUpperCase()}</option>`)
                  .join("")}
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
                ${state.captured_days
                  .slice(-30)
                  .reverse()
                  .map(
                    (d) =>
                      `<option value="${d.date}">${d.date} (${d.event_count} events, ${d.total_points} pts)</option>`
                  )
                  .join("")}
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
              ${Object.entries(PILLAR_DEFS)
                .map(
                  ([name, def]) =>
                    `<span class="perf-help-legend-item"><span class="perf-help-dot" style="background:${def.color}"></span>${helpers.escapeHtml(name)}</span>`
                )
                .join("")}
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
