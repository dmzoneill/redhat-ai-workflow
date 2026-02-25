/**
 * Performance Progress Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getProgressContent for
 * the quarterly questions UI with evidence panels and evaluation controls.
 */

import type {
  PerformanceState,
  QuestionSummary,
  QuestionEvidence,
} from "./performanceTypes";

export interface ProgressHelpers {
  escapeHtml(s: string): string;
  safeText(s: string): string;
  getEmptyStateHtml(icon: string, msg: string): string;
  isQuestionExpanded(id: string): boolean;
  getQuestionEvidence(id: string): QuestionEvidence[] | undefined;
  isQuestionLoading(id: string): boolean;
  getExcludedEvidence(id: string): Set<string>;
}

function renderQuestions(
  state: PerformanceState,
  helpers: ProgressHelpers
): string {
  const questions = state.questions_summary;
  if (!questions || questions.length === 0) {
    return helpers.getEmptyStateHtml(
      "--",
      "Questions will appear after first data collection. Run collect_daily or backfill to populate."
    );
  }

  return questions
    .map((q) => {
      const isExpanded = helpers.isQuestionExpanded(q.id);
      const evidence = helpers.getQuestionEvidence(q.id);
      const isLoading = helpers.isQuestionLoading(q.id);
      const excluded = helpers.getExcludedEvidence(q.id);
      const selectedCount = evidence
        ? evidence.length - excluded.size
        : q.evidence_count;
      const totalPoints = evidence
        ? evidence.filter((e) => !excluded.has(e.id)).reduce((sum, e) => sum + e.points, 0)
        : 0;

      return `
        <div class="card perf-question-card ${isExpanded ? "expanded" : ""}" data-question-id="${helpers.escapeHtml(q.id)}">
          <div class="perf-question-header">
            <span class="perf-question-text">${helpers.escapeHtml(q.text)}</span>
            <button class="perf-question-remove" data-action="removeQuestion" data-question="${helpers.escapeHtml(q.id)}" title="Remove question">&times;</button>
          </div>
          ${q.subtext ? `<div class="perf-question-subtext">${helpers.escapeHtml(q.subtext)}</div>` : ""}

          ${q.llm_summary ? `
            <div class="perf-question-summary">
              <div class="perf-question-summary-label">AI Draft ${q.last_evaluated ? `<span class="perf-question-eval-date">${new Date(q.last_evaluated).toLocaleDateString()}</span>` : ""}</div>
              <div class="perf-question-summary-text">${helpers.escapeHtml(q.llm_summary)}</div>
            </div>
          ` : ""}

          <div class="perf-question-data-bar" data-action="toggleEvidence" data-question="${helpers.escapeHtml(q.id)}">
            <span class="perf-question-data-toggle">${isExpanded ? "&#9660;" : "&#9654;"}</span>
            <span class="perf-question-data-counts">
              ${q.evidence_count} evidence items${evidence ? ` (${selectedCount} selected, ${totalPoints} pts)` : ""}
              &middot; ${q.notes_count} notes
            </span>
            ${isLoading ? `<span class="perf-question-loading">Loading...</span>` : ""}
          </div>

          ${isExpanded ? renderQuestionEvidencePanel(q, evidence, excluded, helpers) : ""}

          <div class="actions-row perf-question-actions">
            <button class="btn btn-xs" data-action="addNote" data-question="${helpers.escapeHtml(q.id)}">Add Note</button>
            <button class="btn btn-xs btn-primary" data-action="evaluateQuestionLocal" data-question="${helpers.escapeHtml(q.id)}">Evaluate (Local)</button>
            <button class="btn btn-xs" data-action="evaluate" data-question="${helpers.escapeHtml(q.id)}">${q.has_summary ? "Re-evaluate (Chat)" : "Evaluate (Chat)"}</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function renderQuestionEvidencePanel(
  q: QuestionSummary,
  evidence: QuestionEvidence[] | undefined,
  excluded: Set<string>,
  helpers: ProgressHelpers
): string {
  if (!evidence || evidence.length === 0) {
    return `<div class="perf-evidence-panel"><div class="perf-evidence-empty">No evidence collected yet. Run daily collection first.</div></div>`;
  }

  const items = evidence.map((e) => {
    const checked = !excluded.has(e.id);
    return `
        <label class="perf-evidence-item ${checked ? "" : "excluded"}" data-evidence-id="${helpers.escapeHtml(e.id)}">
          <input type="checkbox" ${checked ? "checked" : ""} data-action="toggleEvidenceItem" data-question="${helpers.escapeHtml(q.id)}" data-evidence="${helpers.escapeHtml(e.id)}" />
          <span class="perf-evidence-title">${helpers.escapeHtml(e.title || e.id)}</span>
          <span class="perf-evidence-source">${helpers.escapeHtml(e.source)}</span>
          <span class="perf-evidence-points">${e.points} pts</span>
        </label>
      `;
  });

  const notes = q.manual_notes || [];
  const notesHtml =
    notes.length > 0
      ? `
      <div class="perf-evidence-notes">
        <div class="perf-evidence-notes-label">Manual Notes</div>
        ${notes.map((n) => `<div class="perf-evidence-note">${helpers.escapeHtml(n.text)}</div>`).join("")}
      </div>
    `
      : "";

  return `
      <div class="perf-evidence-panel">
        <div class="perf-evidence-header">
          <span>${evidence.length} items sorted by points (top 20 sent to LLM)</span>
          <button class="btn btn-xs" data-action="selectAllEvidence" data-question="${helpers.escapeHtml(q.id)}">Select All</button>
          <button class="btn btn-xs" data-action="deselectAllEvidence" data-question="${helpers.escapeHtml(q.id)}">Deselect All</button>
        </div>
        <div class="flex-col perf-evidence-list">${items.join("")}</div>
        ${notesHtml}
      </div>
    `;
}

export function getProgressContent(
  state: PerformanceState,
  helpers: ProgressHelpers
): string {
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
            ${renderQuestions(state, helpers)}
          </div>
        </div>
      </div>
    `;
}
