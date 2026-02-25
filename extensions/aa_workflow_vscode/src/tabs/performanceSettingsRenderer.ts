/**
 * Performance Settings Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getSettingsContent for
 * the scoring config UI with sliders, dropdowns, competency cards, etc.
 */

import type {
  PerformanceState,
  ScoringConfig,
  ScoringCompConfig,
  EngineeringLevel,
  LevelWeights,
  StrategyAlignmentConfig,
  NpuSettingsConfig,
} from "./performanceTypes";
import {
  PILLAR_NAMES,
  DEFAULT_NPU_CONFIDENCE_THRESHOLD,
} from "./performanceConfig";

export interface SettingsHelpers {
  escapeHtml(s: string): string;
  formatCompetencyName(id: string): string;
}

export function getSettingsContent(
  state: PerformanceState,
  helpers: SettingsHelpers
): string {
  const cfg = state.scoring_config;
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
    "commit",
    "mr_merged",
    "pr_merged",
    "pr_opened",
    "pr_reviewed",
    "issue_resolved",
    "issue_created",
    "issue_opened",
    "issue_closed",
    "review_given",
    "gdrive_doc_created",
    "gdrive_doc_contributed",
    "gdrive_sheet_created",
    "gdrive_sheet_contributed",
    "gdrive_slides_created",
    "gdrive_slides_contributed",
    "meeting_organized",
    "meeting_attended",
  ];

  let compCards = "";
  for (const [category, entries] of Object.entries(categories)) {
    compCards += `<div class="scoring-category-label">${helpers.escapeHtml(category)}</div>`;
    for (const [compId, comp] of entries) {
      const compExpanded = state.scoring_comp_expanded === compId;
      const compIcon = compExpanded ? "\u25BC" : "\u25B6";
      const levelBadge = comp.level_title
        ? `<span class="scoring-comp-level">${helpers.escapeHtml(comp.level_title)}</span>`
        : "";
      compCards += `
          <div class="card scoring-comp-card${compExpanded ? " expanded" : ""}">
            <div class="flex-row scoring-comp-header" data-action="toggleScoringComp" data-key="${helpers.escapeHtml(compId)}">
              <span class="scoring-comp-icon">${compIcon}</span>
              <span class="scoring-comp-name">${helpers.escapeHtml(comp.name)}</span>
              ${levelBadge}
              <span class="scoring-comp-pts">${comp.base_points} pts</span>
            </div>
        `;

      if (compExpanded) {
        const levelTitle = comp.level_title
          ? `<strong>${helpers.escapeHtml(comp.level_title)}</strong>`
          : "";
        const levelDesc = comp.level_description
          ? `<p class="perf-level-desc">${helpers.escapeHtml(comp.level_description)}</p>`
          : "";
        const levelBlock =
          levelTitle || levelDesc
            ? `<div class="scoring-field-row scoring-field-column">
                 <label class="mb-4">Level Expectation</label>
                 <div class="text-md">${levelTitle}${levelDesc}</div>
               </div>`
            : "";
        compCards += `
            <div class="scoring-comp-body" data-comp="${helpers.escapeHtml(compId)}">
              ${levelBlock}
              <div class="scoring-field-row">
                <label>Base Points</label>
                <input type="number" class="scoring-input scoring-comp-input"
                       data-comp="${helpers.escapeHtml(compId)}" data-field="base_points"
                       value="${comp.base_points}" min="1" max="10" />
              </div>

              <div class="scoring-field-row">
                <label>Event Types</label>
                <div class="scoring-chips">
                  ${knownEventTypes
                    .map((et) => {
                      const active = comp.event_types.includes(et);
                      return `<span class="scoring-chip${active ? " active" : ""}"
                                  data-action="toggleEventType" data-comp="${helpers.escapeHtml(compId)}"
                                  data-value="${helpers.escapeHtml(et)}">${helpers.escapeHtml(et)}</span>`;
                    })
                    .join("")}
                </div>
              </div>

              <div class="scoring-field-row">
                <label>Phrases</label>
                <div class="scoring-tags">
                  ${comp.phrases
                    .map(
                      (p) =>
                        `<span class="scoring-tag">${helpers.escapeHtml(p)}<span class="scoring-tag-x"
                      data-action="removePhrase" data-comp="${helpers.escapeHtml(compId)}"
                      data-value="${helpers.escapeHtml(p)}">&times;</span></span>`
                    )
                    .join("")}
                  <input type="text" class="scoring-tag-input" placeholder="+ add phrase"
                         data-action="addPhrase" data-comp="${helpers.escapeHtml(compId)}" />
                </div>
              </div>

              <div class="scoring-field-row">
                <label>Keywords</label>
                <div class="scoring-tags">
                  ${comp.keywords
                    .map(
                      (k) =>
                        `<span class="scoring-tag">${helpers.escapeHtml(k)}<span class="scoring-tag-x"
                      data-action="removeKeyword" data-comp="${helpers.escapeHtml(compId)}"
                      data-value="${helpers.escapeHtml(k)}">&times;</span></span>`
                    )
                    .join("")}
                  <input type="text" class="scoring-tag-input" placeholder="+ add keyword"
                         data-action="addKeyword" data-comp="${helpers.escapeHtml(compId)}" />
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
  const levelOptions = levels
    .map(
      (l) =>
        `<option value="${helpers.escapeHtml(l.id)}"${l.id === currentLevel ? " selected" : ""}>${helpers.escapeHtml(l.name)}</option>`
    )
    .join("");

  const scopeMult = cfg.scope_multipliers || {};
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
          <span class="scoring-scope-label">${helpers.escapeHtml(scope)}</span>
          <input type="number" class="scoring-input"
                 data-action="setScopeMultiplier" data-scope="${helpers.escapeHtml(scope)}"
                 value="${val}" min="1" max="20" step="1" />
          <span class="scoring-hint scoring-hint-flush">${scopeDescriptions[scope] || ""}</span>
        </div>`;
  }

  const levelWeights: LevelWeights = cfg.level_weights || {};
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
        <td class="capitalize-bold">${helpers.escapeHtml(scope)}</td>`;
    for (const role of roles) {
      const val = sw[role] ?? 1.0;
      roleWeightTable += `<td><input type="number" class="scoring-input scoring-input-narrow"
          data-action="setRoleWeight" data-scope="${helpers.escapeHtml(scope)}" data-role="${helpers.escapeHtml(role)}"
          value="${val}" min="0" max="10" step="0.1" /></td>`;
    }
    roleWeightTable += `</tr>`;
  }
  roleWeightTable += `</tbody></table>`;

  const pillarNames = [...PILLAR_NAMES];
  let pillarWeightRows = "";
  for (const pillar of pillarNames) {
    const val = pillarWeights[pillar] ?? 1.0;
    pillarWeightRows += `
        <div class="scoring-field-row scoring-field-row-compact">
          <span class="scoring-pillar-label">${helpers.escapeHtml(pillar)}</span>
          <input type="number" class="scoring-input"
                 data-action="setPillarWeight" data-pillar="${helpers.escapeHtml(pillar)}"
                 value="${val}" min="0" max="3" step="0.1" />
        </div>`;
  }

  const stratCfg: StrategyAlignmentConfig = cfg.strategy_alignment || {};
  const stratEnabled = stratCfg.enabled !== false;
  const stratBonus = stratCfg.bonus_multiplier ?? 1.5;
  const stratEnrichClass = stratCfg.enrich_classification !== false;
  const stratMinOverlap = stratCfg.min_text_overlap_words ?? 3;

  const npuCfg: NpuSettingsConfig = cfg.npu_settings || {};
  const npuEnabled = npuCfg.enabled === true;
  const npuDevice = npuCfg.device || "CPU";
  const npuThreshold =
    npuCfg.confidence_threshold ?? DEFAULT_NPU_CONFIDENCE_THRESHOLD;
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
          <div class="section-title">Level Weight Matrix <span class="scoring-hint font-normal">(${helpers.escapeHtml(currentLevel.toUpperCase())})</span></div>
          <p class="scoring-hint scoring-hint-mb">Role weights by scope: reporter (defined work) vs assignee (delivered) vs contributor (reviewed/commented).</p>
          ${roleWeightTable}
          <div class="mt-12">
            <div class="scoring-category-label">Pillar Weights</div>
            <p class="scoring-hint scoring-hint-sm">Emphasis areas for your level. Higher = more credit for that category.</p>
            ${pillarWeightRows}
          </div>
          <div class="scoring-example-box">
            <strong>Example: Epic (scope=4x) as ${helpers.escapeHtml(currentLevel.toUpperCase())} assignee in Technical Contribution</strong>
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
              ${state.executive_senders
                .map(
                  (s) =>
                    `<span class="scoring-tag">${helpers.escapeHtml(s)}<span class="scoring-tag-x"
                  data-action="removeExecutiveSender"
                  data-value="${helpers.escapeHtml(s)}">&times;</span></span>`
                )
                .join("")}
              <input type="text" class="scoring-tag-input" placeholder="+ add email address"
                     data-action="addExecutiveSender" />
            </div>
            ${state.executive_senders.length === 0
              ? `<span class="scoring-hint text-warning">No senders configured. Strategy alignment requires at least one director email.</span>`
              : ""}
          </div>

          <div class="mt-12">
            <label class="scoring-field-label scoring-label-block">Cached Emails (${state.executive_emails.length})</label>
            ${state.executive_emails.length > 0
              ? `<div class="exec-emails-list">
                  ${state.executive_emails
                    .slice(0, 20)
                    .map(
                      (em) => `
                    <div class="exec-email-row">
                      <span class="exec-email-date">${helpers.escapeHtml(em.date || "")}</span>
                      <span class="exec-email-sender">${helpers.escapeHtml(em.sender || "")}</span>
                      <span class="exec-email-subject">${helpers.escapeHtml((em.subject || "").substring(0, 60))}</span>
                      <span class="exec-email-delete scoring-tag-x"
                            data-action="deleteExecutiveEmail"
                            data-value="${helpers.escapeHtml(em.email_id)}"
                            title="Delete cached email">&times;</span>
                    </div>
                  `
                    )
                    .join("")}
                  ${state.executive_emails.length > 20
                    ? `<div class="scoring-hint p-8">...and ${state.executive_emails.length - 20} more</div>`
                    : ""}
                </div>`
              : `<span class="scoring-hint">No cached emails. Use Backfill to fetch this quarter's emails.</span>`}
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
