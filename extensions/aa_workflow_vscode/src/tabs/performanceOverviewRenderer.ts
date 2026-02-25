/**
 * Performance Overview Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getOverviewContent and
 * shared render helpers (expandable bars, gaps, highlights) for use
 * by the Competencies tab and other consumers.
 */

import type {
  PerformanceState,
  GapSuggestion,
  CompetencyScore,
  CompetencyEvidence,
  StrategyAlignmentPriority,
} from "./performanceTypes";
import { PILLAR_DEFS, getColorForPercentage, getCoverageColor } from "./performanceConfig";

export interface OverviewHelpers {
  getEffectivePercentage(compId: string): number;
  getEffectiveOverall(): number;
  formatCompetencyName(id: string): string;
  escapeHtml(s: string): string;
  getEmptyStateHtml(icon: string, msg: string): string;
  renderIssueLink(key: string): string;
  renderIssueLinks(keys: string[]): string;
  safeText(text: string): string;
}

export function getOverviewContent(state: PerformanceState, helpers: OverviewHelpers): string {
  const align = state.strategy_alignment;
  const coveragePct = align?.coverage_summary?.coverage_pct ?? 0;
  const coverageColor = getCoverageColor(coveragePct);

  const enrichmentOn = state.session_enrichment;
  const displayOverall = enrichmentOn ? state.overall_percentage : (state.no_enrichment_overall || state.overall_percentage);
  const enrichToggle = `<label class="perf-enrich-toggle perf-enrich-toggle--overview" title="Session enrichment adds keywords from daily session logs to boost competency matches. Toggle off to see raw signal-only scores."><input type="checkbox" ${enrichmentOn ? "checked" : ""} onchange="vscode.postMessage({type:'toggleSessionEnrichment'})" />Enriched</label>`;
  const quickStatsHtml = `
    <div class="grid-4 mb-16">
      <div class="card stat-card">
        <div class="stat-value">${displayOverall}%</div>
        <div class="text-meta stat-label">Overall Score ${enrichToggle}</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${state.coverage.captured}</div>
        <div class="text-meta stat-label">Days Captured</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">${state.issue_hierarchy?.total_issues || 0}</div>
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
    const catComps = Object.entries(state.competencies).filter(([id]) => {
      const meta = state.competency_meta[id];
      return meta?.category === pname;
    });
    const avgPct = catComps.length > 0
      ? Math.round(catComps.reduce((s, [id]) => s + helpers.getEffectivePercentage(id), 0) / catComps.length)
      : 0;

    pillarHtml += `
      <div class="card card-centered" style="border-top: 3px solid ${color};">
        <div class="item-row card-header card-header-centered">
          <span>${icon}</span>
          <span class="card-title">${helpers.escapeHtml(pname)}</span>
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
      strategyHtml += `<span>From: ${align.senders.map(s => helpers.escapeHtml(s)).join(", ")}</span>`;
    }
    const uws = align.user_work_summary;
    if (uws) {
      strategyHtml += `<span>Aligned against: ${uws.jira_issues} Jira issues &amp; ${uws.gitlab_mrs} GitLab MRs</span>`;
    }
    strategyHtml += `</div>`;

    // Sender summary cards
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
        const topThemes = (summary.top_themes || []).slice(0, 4).map((t: string) => helpers.escapeHtml(t)).join(", ");
        const jiraAct = jiraActivitySummary[email];
        const jiraIssueCount = summary.jira_issues || jiraAct?.issue_count || 0;
        const gdriveDocCount = summary.gdrive_docs || 0;
        const jiraProjects = jiraAct?.projects || [];
        const displayName = email.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, c => c.toUpperCase());

        strategyHtml += `
          <div class="ownership-card">
            <div class="ownership-card-name">${helpers.escapeHtml(displayName)}</div>
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
      const senders = prio.sender_names || prio.owner_names || [];
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
      const issueLinks = prio.matched_user_issues.map(k => helpers.renderIssueLink(k)).join(" ");
      const mrLinks = (prio.matched_mrs || []).map(m => `<span class="overview-mr-badge">${helpers.escapeHtml(m)}</span>`).join(" ");
      const allMatches = [issueLinks, mrLinks].filter(Boolean).join(" ");
      const ownerBadges = (prio.sender_names || prio.owner_names || []).map((n: string) =>
        `<span class="ownership-badge">${helpers.escapeHtml(n)}</span>`
      ).join(" ");

      return `
        <div class="overview-priority ${statusClass}">
          <div class="flex-row overview-priority-header">
            <span class="overview-priority-status">${statusIcon}</span>
            <span class="overview-priority-name">${helpers.escapeHtml(prio.name)}</span>
            <span class="overview-priority-pillar" style="background: ${pillarColor}22; color: ${pillarColor}; border: 1px solid ${pillarColor}44;">${helpers.escapeHtml(prio.pillar)}</span>
            ${ownerBadges}
          </div>
          ${prio.context ? `<div class="overview-priority-context">${helpers.escapeHtml(prio.context.substring(0, 150))}</div>` : ""}
          ${allMatches ? `<div class="overview-priority-matches">${allMatches}</div>` : `<div class="overview-priority-gap-msg">No matching deliverables</div>`}
        </div>
      `;
    };

    if (ownerGrouped.size > 0) {
      for (const [ownerName, prios] of ownerGrouped.entries()) {
        const coveredCount = prios.filter(p => p.status === "covered").length;
        strategyHtml += `<div class="section owner-group-section">`;
        strategyHtml += `<div class="section-title owner-group-title">`;
        strategyHtml += `<span class="owner-group-icon">\u{1F464}</span> ${helpers.escapeHtml(ownerName)}`;
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
        const gapOwners = (g.sender_names || g.owner_names || []).map((n: string) => helpers.escapeHtml(n)).join(", ");
        strategyHtml += `
          <div class="card">
            <div class="card-title">${helpers.escapeHtml(g.name)}</div>
            <div class="text-secondary text-sm">${helpers.escapeHtml(g.pillar)}</div>
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
  const digest = state.ai_overview_digest;
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
        <div class="section-title">Weekly Digest <span class="ai-badge">${helpers.escapeHtml(src)}</span> ${trendBadge}</div>
        <div class="ai-insight-card">${helpers.escapeHtml(digest.digest)}</div>
      </div>`;
  }

  // Build pillar averages for charts
  const pillarAvgs: Record<string, number> = {};
  for (const [pname] of Object.entries(PILLAR_DEFS)) {
    const catComps = Object.entries(state.competencies).filter(([id]) =>
      state.competency_meta[id]?.category === pname
    );
    pillarAvgs[pname] = catComps.length > 0
      ? Math.round(catComps.reduce((s, [id]) => s + helpers.getEffectivePercentage(id), 0) / catComps.length)
      : 0;
  }

  // Chart data for D3 overview visualizations
  const chartData = {
    captured_days: state.captured_days.slice().sort((a, b) => a.date.localeCompare(b.date)),
    day_of_quarter: state.day_of_quarter,
    overall_percentage: helpers.getEffectiveOverall(),
    total_weekdays: state.coverage.total_weekdays,
    captured: state.coverage.captured,
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
              <span class="qc-chart-legend-item"><span class="qc-chart-legend-swatch qc-chart-legend-swatch--actual"></span>Actual</span>
              <span class="qc-chart-legend-item"><span class="qc-chart-legend-swatch qc-chart-legend-swatch--projected"></span>Projected</span>
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
            <span class="qc-heatmap-legend-cell qc-heatmap-legend-cell--1"></span>
            <span class="qc-heatmap-legend-cell qc-heatmap-legend-cell--2"></span>
            <span class="qc-heatmap-legend-cell qc-heatmap-legend-cell--3"></span>
            <span class="qc-heatmap-legend-cell qc-heatmap-legend-cell--4"></span>
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

// ---------------------------------------------------------------------------
// Shared helpers for Competencies tab (exported for use by other renderers)
// ---------------------------------------------------------------------------

export function renderExpandableCompetencyBars(
  state: PerformanceState,
  helpers: OverviewHelpers,
): string {
  const sorted = Object.entries(state.competencies).sort((a, b) => b[1].percentage - a[1].percentage);

  if (sorted.length === 0) {
    return helpers.getEmptyStateHtml("--", "No competency data yet. Run daily collection to start tracking.");
  }

  const categories: Record<string, [string, CompetencyScore][]> = {};
  for (const entry of sorted) {
    const [id] = entry;
    const meta = state.competency_meta[id];
    const cat = meta?.category || "Other";
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(entry);
  }

  let html = "";
  for (const [category, entries] of Object.entries(categories)) {
    html += `<div class="perf-comp-category">
      <div class="perf-comp-category-label">${helpers.escapeHtml(category)}</div>`;

    for (const [id, score] of entries) {
      const color = getColorForPercentage(score.percentage);
      const icon = score.percentage >= 80 ? "\u2713" : score.percentage < 50 ? "\u26A0" : "";
      const isExpanded = state.expanded_competency === id;
      const evidence = state.competency_evidence[id] || [];
      const meta = state.competency_meta[id];
      const expandedClass = isExpanded ? " expanded" : "";

      let expandedContent = "";
      if (isExpanded) {
        const goalHtml = meta ? `
          <div class="perf-comp-goal">
            <div class="perf-comp-goal-text">${helpers.escapeHtml(meta.goal)}</div>
            <div class="perf-comp-description">${helpers.escapeHtml(meta.description)}</div>
            <div class="perf-comp-progress-summary">
              ${meta.points}/${meta.target} pts &middot; ${evidence.length} contributing events
            </div>
          </div>
        ` : "";

        if (evidence.length > 0) {
          expandedContent = `
            ${goalHtml}
            <div class="flex-col perf-evidence-list">
              ${evidence.map((ev: CompetencyEvidence) => {
                const titleHtml = ev.url
                  ? `<a href="${helpers.escapeHtml(ev.url)}" class="perf-event-link">${helpers.safeText(ev.title)}</a>`
                  : helpers.safeText(ev.title);
                return `
                  <div class="card perf-evidence-card">
                    <div class="perf-evidence-card-top">
                      <span class="perf-source-badge perf-source-${helpers.escapeHtml(ev.source)}">${helpers.escapeHtml(ev.source)}</span>
                      <span class="perf-evidence-date">${helpers.escapeHtml(ev.date)}</span>
                      <span class="perf-evidence-pts">${ev.points} pts</span>
                    </div>
                    <div class="perf-evidence-card-title">${titleHtml}</div>
                    <div class="flex-row perf-evidence-card-meta">
                      ${ev.match_reason ? `<span class="perf-match-reason">${helpers.escapeHtml(ev.match_reason)}</span>` : ""}
                      ${ev.issue_keys?.length ? `<span class="perf-evidence-issues">${helpers.renderIssueLinks(ev.issue_keys)}</span>` : ""}
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
          <div class="flex-col gap-4 perf-competency-header" data-action="toggleCompetency" data-key="${helpers.escapeHtml(id)}">
            <div class="perf-comp-header-top">
              <span class="perf-competency-expand-icon">${isExpanded ? "\u25BC" : "\u25B6"}</span>
              <span class="perf-competency-name">${helpers.escapeHtml(meta?.name || helpers.formatCompetencyName(id))}</span>
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

export function renderGapsAlert(state: PerformanceState, helpers: OverviewHelpers): string {
  if (state.gaps.length === 0) return "";

  const gapItems = state.gaps.map((gap) => {
    const pct = helpers.getEffectivePercentage(gap);
    const meta = state.competency_meta[gap];
    const name = meta?.name || helpers.formatCompetencyName(gap);
    const goal = meta?.goal || "";
    const color = getColorForPercentage(pct);
    return `
      <div class="perf-gaps-item">
        <div class="flex-between perf-gaps-item-header">
          <span class="font-semibold perf-gaps-item-name">${helpers.escapeHtml(name)}</span>
          <span class="perf-gaps-item-pct" style="color: ${color};">${pct}%</span>
        </div>
        ${goal ? `<div class="perf-gaps-item-goal">${helpers.escapeHtml(goal)}</div>` : ""}
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

export function renderGapsWithSuggestions(
  state: PerformanceState,
  helpers: OverviewHelpers,
): string {
  const gaps = state.gap_suggestions;
  const gapKeys = Object.keys(gaps);
  if (gapKeys.length === 0) return "";

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
    html += `<div class="perf-gap-category-label">${helpers.escapeHtml(category)}</div>`;

    for (const [compId, gap] of entries) {
      const color = getColorForPercentage(gap.percentage);
      const evidence = state.competency_evidence[compId] || [];
      const meta = state.competency_meta[compId];
      const name = meta?.name || helpers.formatCompetencyName(compId);
      const goal = gap.goal || meta?.goal || "";
      const description = gap.description || meta?.description || "";
      const deficit = gap.deficit || (gap.target - gap.points);

      html += `
        <div class="card perf-gap-card">
          <div class="flex-between perf-gap-card-header">
            <span class="card-title">${helpers.escapeHtml(name)}</span>
            <span class="perf-gap-card-pct" style="color: ${color};">${gap.percentage}%</span>
          </div>
          ${goal ? `<div class="perf-gap-card-goal">${helpers.escapeHtml(goal)}</div>` : ""}
          <div class="progress-bar my-12">
            <div class="progress-fill" style="width: ${gap.percentage}%; background: ${color};"></div>
          </div>
          <div class="perf-gap-card-meta">
            ${gap.points}/${gap.target} pts &middot; ${gap.evidence_count} events &middot;
            <strong>${deficit} pts</strong> needed to reach target
          </div>
          ${description ? `<div class="perf-gap-card-desc">${helpers.escapeHtml(description)}</div>` : ""}
          <div class="perf-gap-card-suggestions">
            <div class="perf-gap-card-subtitle">Actions to close this gap:</div>
            <ul>
              ${gap.suggestions.map(s => `<li>${helpers.escapeHtml(s)}</li>`).join("")}
            </ul>
            ${gap.ai_suggestion ? `<div class="ai-insight-card mt-8">${helpers.escapeHtml(gap.ai_suggestion)}</div>` : `<button class="btn btn-xs mt-4" data-action="getGapCoach" data-competency="${helpers.escapeHtml(compId)}">AI Coach</button>`}
          </div>
          ${evidence.length > 0 ? `
            <div class="perf-gap-card-evidence">
              <div class="perf-gap-card-subtitle">What you've done so far (${evidence.length}):</div>
              ${evidence.slice(0, 3).map((ev: CompetencyEvidence) => {
                const titleHtml = ev.url
                  ? `<a href="${helpers.escapeHtml(ev.url)}" class="perf-gap-evidence-link">${helpers.safeText(ev.title)}</a>`
                  : helpers.safeText(ev.title);
                return `
                  <div class="perf-gap-evidence-item">
                    <span class="perf-gap-evidence-date">${helpers.escapeHtml(ev.date)}</span>
                    <span class="perf-gap-evidence-title">${titleHtml}</span>
                    ${ev.match_reason ? `<span class="perf-gap-evidence-reason">${helpers.escapeHtml(ev.match_reason)}</span>` : ""}
                    ${helpers.renderIssueLinks(ev.issue_keys)}
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

export function renderHighlights(state: PerformanceState, helpers: OverviewHelpers): string {
  if (state.highlights.length === 0) {
    return helpers.getEmptyStateHtml("--", "Highlights will appear as you complete work.");
  }

  return state.highlights.slice(0, 5).map((h) => `
    <div class="perf-highlight-item">
      <span>${helpers.escapeHtml(h)}</span>
    </div>
  `).join("");
}
