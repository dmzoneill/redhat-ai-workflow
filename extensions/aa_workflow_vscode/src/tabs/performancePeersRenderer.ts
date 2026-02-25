/**
 * Performance Peers Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getPeersContent and
 * peer-related chart/table helpers for use by the main tab.
 */

import type {
  PerformanceState,
  PeerBenchmarks,
  OrgStats,
  DistributionStats,
} from "./performanceTypes";
import {
  LEVEL_LABELS,
  LEVEL_COLORS,
  SOURCE_COLORS,
} from "./performanceConfig";

export interface PeersHelpers {
  getEffectivePercentage(compId: string): number;
  getEffectiveOverall(): number;
  escapeHtml(s: string): string;
}

export function getPeersContent(state: PerformanceState, helpers: PeersHelpers): string {
  const benchmarks = state.peer_benchmarks;
  const orgStats = state.org_stats;
  const levelLabels = LEVEL_LABELS;
  const levelColors = LEVEL_COLORS;

  let orgOverviewHtml = "";
  if (orgStats?.available) {
    orgOverviewHtml = `
      <div class="section">
        <div class="section-title">Organization Overview</div>
        <div class="peer-chart-row">
          ${renderOrgLevelDistribution(orgStats, levelLabels, levelColors)}
          ${renderOrgDonut(orgStats, levelColors)}
          ${renderPeerSampleCoverage(orgStats, levelColors)}
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
  Object.keys(state.competencies).forEach(c => allCompIds.add(c));
  for (const lk of activeLevels) {
    Object.keys(benchmarks.levels[lk].avg_competency_pct || {}).forEach(c => allCompIds.add(c));
  }
  const sortedComps = Array.from(allCompIds).sort();

  const statsSummaryHtml = renderPeerStatsSummary(state, benchmarks, activeLevels, levelLabels, levelColors, helpers);
  const levelDistTableHtml = renderLevelDistributionTable(state, benchmarks, activeLevels, levelLabels, levelColors, helpers);

  const cmpMode = state.peer_comparison_mode || "comparable";
  const rawActive = cmpMode === "raw" ? " active" : "";
  const cmpActive = cmpMode === "comparable" ? " active" : "";
  const enrichOn = state.session_enrichment;
  const comparisonToggle = `<div class="heatmap-mode-toggle heatmap-mode-toggle--comparison">
    <div>
      <button class="heatmap-mode-btn${rawActive}" onclick="vscode.postMessage({type:'switchPeerComparisonMode',mode:'raw'})">Raw</button>
      <button class="heatmap-mode-btn${cmpActive}" onclick="vscode.postMessage({type:'switchPeerComparisonMode',mode:'comparable'})">Normalized</button>
    </div>
    <label class="perf-enrich-toggle" title="Session enrichment adds keywords from daily session logs to boost competency matches. Toggle off to see raw signal-only scores."><input type="checkbox" ${enrichOn ? "checked" : ""} onchange="vscode.postMessage({type:'toggleSessionEnrichment'})" />Enriched</label>
  </div>`;

  const benchmarkRow = `
    <div class="section">
      <div class="section-title">Benchmark Comparison ${comparisonToggle}</div>
      <div class="peer-chart-row peer-chart-row--2col">
        ${renderLevelComparisonBars(state, benchmarks, activeLevels, levelLabels, levelColors, helpers)}
        ${renderEventStackedBars(state, benchmarks, activeLevels, levelLabels, levelColors, helpers)}
      </div>
      <div class="peer-heatmap-section">
        ${renderCompetencyHeatmap(state, benchmarks, activeLevels, levelLabels, levelColors, helpers)}
      </div>
    </div>`;

  const radarSvg = renderPeerRadar(state, sortedComps, activeLevels, benchmarks, levelColors, helpers);

  let barsHtml = '<div class="peer-grouped-bars">';
  for (const compId of sortedComps) {
    const name = compId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    barsHtml += `<div class="peer-comp-group"><div class="peer-comp-name">${helpers.escapeHtml(name)}</div>`;

    const isComp = (state.peer_comparison_mode || "comparable") === "comparable";
    const userPct = isComp
      ? (state.competencies[compId]?.peer_comparable_percentage ?? state.competencies[compId]?.percentage ?? 0)
      : helpers.getEffectivePercentage(compId);
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
      barsHtml += `<div class="peer-bar-row"><span class="peer-bar-label" style="color:${color}">${helpers.escapeHtml(label)}</span><div class="peer-bar-track">${rangeHtml}<div class="peer-bar-fill" style="width:${pct}%;background:${color};"></div></div><span class="peer-bar-value">${valueText}</span></div>`;
    }

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
        barsHtml += `<tr><td style="color:${color}">${helpers.escapeHtml(levelLabels[lk] || lk)}</td><td>${cs.count}</td><td>${cs.min}%</td><td>${cs.avg}%</td><td>${cs.median}%</td><td>${cs.max}%</td><td>${cs.p25}%</td><td>${cs.p75}%</td></tr>`;
      }
      barsHtml += `</tbody></table></details>`;
    }

    barsHtml += `</div>`;
  }
  barsHtml += "</div>";

  const volumeTableHtml = renderVolumeTable(benchmarks, activeLevels, levelLabels, levelColors, helpers);

  const lastUpdated = benchmarks.last_updated ? new Date(benchmarks.last_updated).toLocaleString() : "Never";

  let narrativeHtml = "";
  if (state.ai_peer_narrative?.narrative) {
    const src = state.ai_peer_narrative.source === "ai" ? "AI" : "Analysis";
    narrativeHtml = `
      <div class="section">
        <div class="section-title">AI Insights <span class="ai-badge">${helpers.escapeHtml(src)}</span></div>
        <div class="ai-insight-card">${helpers.escapeHtml(state.ai_peer_narrative.narrative)}</div>
      </div>`;
  }

  let diffHtml = "";
  const diff = state.ai_peer_differentiators;
  if (diff?.user_vs_target) {
    const uvt = diff.user_vs_target;
    if (uvt.strengths.length > 0 || uvt.gaps.length > 0) {
      diffHtml = `<div class="section"><div class="section-title">vs ${helpers.escapeHtml(uvt.target_label)} Benchmarks</div><div class="ai-diff-grid">`;
      if (uvt.strengths.length > 0) {
        diffHtml += `<div class="ai-diff-col"><div class="ai-diff-header ai-diff-positive">Strengths</div>`;
        for (const s of uvt.strengths.slice(0, 5)) {
          diffHtml += `<div class="ai-diff-item"><span class="ai-diff-name">${helpers.escapeHtml(s.name)}</span><span class="ai-diff-delta positive">+${s.delta}%</span></div>`;
        }
        diffHtml += `</div>`;
      }
      if (uvt.gaps.length > 0) {
        diffHtml += `<div class="ai-diff-col"><div class="ai-diff-header ai-diff-negative">Gaps</div>`;
        for (const g of uvt.gaps.slice(0, 5)) {
          diffHtml += `<div class="ai-diff-item"><span class="ai-diff-name">${helpers.escapeHtml(g.name)}</span><span class="ai-diff-delta negative">${g.delta}%</span></div>`;
        }
        diffHtml += `</div>`;
      }
      diffHtml += `</div></div>`;
    }
  }

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
        <div class="text-secondary text-xs mt-4">Last updated: ${helpers.escapeHtml(lastUpdated)}</div>
      </div>

      ${orgOverviewHtml}
      ${statsSummaryHtml}
      ${benchmarkRow}
      ${levelDistTableHtml}

      ${narrativeHtml}
      ${diffHtml}
      ${renderPromotionReadiness(state, helpers)}

      <div class="section">
        <div class="section-title">Competency Radar</div>
        <div class="peer-radar-container">${radarSvg}</div>
        ${renderRadarStatsLegend(benchmarks, activeLevels, levelLabels, levelColors, helpers)}
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
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Org Overview (Row 1)
// ---------------------------------------------------------------------------

export function renderOrgLevelDistribution(
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

export function renderOrgDonut(
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

export function renderPeerSampleCoverage(
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

// ---------------------------------------------------------------------------
// Peer Stats & Charts
// ---------------------------------------------------------------------------

export function renderPeerStatsSummary(
  state: PerformanceState,
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
): string {
  const isComp = (state.peer_comparison_mode || "comparable") === "comparable";
  const userLevel = state.scoring_config?.engineering_level || "sse";
  const targetLevel = activeLevels.includes(userLevel) ? userLevel : activeLevels[activeLevels.length - 1];
  if (!targetLevel) return "";
  const ld = benchmarks.levels[targetLevel];
  const stats = isComp ? (ld?.comparable_stats_overall ?? ld?.stats_overall) : ld?.stats_overall;
  if (!stats || stats.count === 0) return "";

  const userPct = isComp && state.peer_comparable_overall > 0
    ? state.peer_comparable_overall
    : helpers.getEffectiveOverall();
  const color = levelColors[targetLevel] || "#888";
  const label = levelLabels[targetLevel] || targetLevel.toUpperCase();
  const modeLabel = isComp ? " (Normalized)" : "";

  const card = (title: string, value: string, highlight?: string) =>
    `<div class="peer-overall-card"><div class="peer-overall-label">${helpers.escapeHtml(title)}</div><div class="peer-overall-value" style="color:${highlight || "var(--text-primary)"}">${value}</div></div>`;

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
      <div class="section-title">Your Score vs ${helpers.escapeHtml(label)} Peers (N=${stats.count}${coverageNote})${modeLabel}</div>
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

export function renderLevelComparisonBars(
  state: PerformanceState,
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
): string {
  const isComparable = (state.peer_comparison_mode || "comparable") === "comparable";
  const userPct = isComparable && state.peer_comparable_overall > 0
    ? state.peer_comparable_overall
    : helpers.getEffectiveOverall();
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

    svg += `<text x="${labelWidth - 8}" y="${y + barHeight / 2 + 5}" text-anchor="end" fill="${item.color}" font-size="13" font-weight="600">${helpers.escapeHtml(item.label)}</text>`;
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

    if (i === 0 && !isComparable && state.peer_comparable_overall > 0 && state.peer_comparable_overall < item.pct) {
      const pcW = Math.round((state.peer_comparable_overall / maxPct) * trackWidth);
      svg += `<line x1="${labelWidth + pcW}" y1="${y}" x2="${labelWidth + pcW}" y2="${y + barHeight}" stroke="${item.color}" stroke-width="2" stroke-dasharray="3,2" opacity="0.6"/>`;
      labelText += ` (normalized: ${state.peer_comparable_overall}%)`;
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

export function renderEventStackedBars(
  state: PerformanceState,
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
): string {
  const sourceColors = SOURCE_COLORS;

  const volMode = state.event_volume_mode || "comparable";
  const isComparable = volMode === "comparable";
  const allCounts = state.event_counts_by_source || {};
  const compCounts = state.comparable_event_counts_by_source || {};
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
      <span class="peer-stacked-label" style="color:${row.color}">${helpers.escapeHtml(row.label)}</span>
      <div class="peer-stacked-track">${segHtml}</div>
      <span class="peer-stacked-total">${row.total.toFixed(0)}</span>
    </div>`;
  }

  let legendHtml = `<div class="peer-stacked-legend">`;
  for (const src of sources) {
    const color = sourceColors[src] || "#666";
    legendHtml += `<span class="peer-stacked-legend-item"><span class="peer-stacked-legend-swatch" style="background:${color}"></span>${helpers.escapeHtml(src)}</span>`;
  }
  legendHtml += `</div>`;

  const allBtn = `<button class="heatmap-mode-btn${!isComparable ? " active" : ""}" onclick="vscode.postMessage({type:'switchEventVolumeMode',mode:'all'})">All</button>`;
  const compBtn = `<button class="heatmap-mode-btn${isComparable ? " active" : ""}" onclick="vscode.postMessage({type:'switchEventVolumeMode',mode:'comparable'})">Comparable</button>`;
  const toggleHtml = `<div class="heatmap-mode-toggle heatmap-mode-toggle--stacked">${allBtn}${compBtn}</div>`;

  const primaryOnlySources = ["session", "gdrive"].filter(s => (allCounts[s] || 0) > 0);
  let coverageNote = "";
  if (!isComparable && primaryOnlySources.length > 0) {
    const allTotal = sources.reduce((s, src) => s + (allCounts[src] || 0), 0);
    const pctExclusive = Math.round(
      primaryOnlySources.reduce((s, src) => s + (allCounts[src] || 0), 0) / Math.max(allTotal, 1) * 100,
    );
    coverageNote = `<div class="chart-subtitle chart-subtitle--warning">${pctExclusive}% of your events come from sources peers lack (${primaryOnlySources.join(", ")})</div>`;
  }

  let parityWarnings = "";
  const sharedSources = sources.filter(s => s !== "session");
  for (const lk of activeLevels) {
    const peerCounts = benchmarks.levels[lk]?.avg_event_counts_by_source || {};
    const missingSources = sharedSources.filter(s => (userCounts[s] || 0) > 0 && (peerCounts[s] || 0) === 0);
    if (missingSources.length > 0) {
      const label = levelLabels[lk] || lk;
      parityWarnings += `<div class="chart-subtitle chart-subtitle--warning">${helpers.escapeHtml(label)} peers have no ${missingSources.join(", ")} events</div>`;
    }
  }

  let coverageIndicator = "";
  const coverageParts: string[] = [];
  for (const lk of activeLevels) {
    const ld = benchmarks.levels[lk];
    const avgDays = ld?.avg_days_with_events ?? 0;
    if (avgDays > 0) {
      const label = levelLabels[lk] || lk;
      coverageParts.push(`${helpers.escapeHtml(label)}: ${avgDays.toFixed(0)}d avg`);
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

export function renderCompetencyHeatmap(
  state: PerformanceState,
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
): string {
  const allCompIds = new Set<string>();
  Object.keys(state.competencies).forEach(c => allCompIds.add(c));
  for (const lk of activeLevels) {
    Object.keys(benchmarks.levels[lk]?.avg_competency_pct || {}).forEach(c => allCompIds.add(c));
  }
  const sortedComps = Array.from(allCompIds).sort();
  if (sortedComps.length === 0) return "";

  const mode = state.heatmap_mode || "percentage";
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
    html += `<div class="peer-heatmap-row-label" title="${helpers.escapeHtml(name)}">${helpers.escapeHtml(name)}</div>`;

    for (const col of cols) {
      let displayVal: number;
      let suffix = "%";
      let maxVal = 100;
      let spreadAnnotation = "";

      if (col === "you") {
        if (isRawPoints) {
          displayVal = state.competencies[compId]?.points ?? 0;
          suffix = "";
          maxVal = 300;
        } else if (isPeerComparable) {
          displayVal = state.competencies[compId]?.peer_comparable_percentage ?? 0;
        } else {
          displayVal = helpers.getEffectivePercentage(compId);
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
      const tooltipParts = [`${helpers.escapeHtml(name)}: ${displayVal}${suffix}`];
      if (col === "you" && isPeerComparable) {
        const fullPct = state.competencies[compId]?.percentage ?? 0;
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

export function renderPeerRadar(
  state: PerformanceState,
  compIds: string[],
  activeLevels: string[],
  benchmarks: PeerBenchmarks,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
): string {
  const n = compIds.length;
  if (n < 3) return "<p>Not enough competencies for radar chart.</p>";

  const width = 500, height = 500;
  const cx = width / 2, cy = height / 2;
  const maxR = Math.min(cx, cy) * 0.7;
  let svg = `<svg width="100%" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg"><style>text { font-family: system-ui, -apple-system, sans-serif; font-size: 10px; }</style>`;

  for (const ringPct of [25, 50, 75, 100]) {
    const r = maxR * ringPct / 100;
    const pts = compIds.map((_, i) => {
      const a = (2 * Math.PI * i / n) - Math.PI / 2;
      return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    }).join(" ");
    svg += `<polygon points="${pts}" fill="none" stroke="var(--vscode-widget-border, #ddd)" stroke-width="0.5"/>`;
  }

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
    svg += `<text x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${anchor}" dominant-baseline="middle" fill="var(--vscode-foreground, #666)">${helpers.escapeHtml(name)}</text>`;
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

  const isComp = (state.peer_comparison_mode || "comparable") === "comparable";

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

  for (const lk of activeLevels) {
    const profile = isComp
      ? (benchmarks.levels[lk]?.comparable_avg_competency_pct ?? benchmarks.levels[lk].avg_competency_pct ?? {})
      : (benchmarks.levels[lk].avg_competency_pct || {});
    svg += makePolygon(profile, levelColors[lk] || "#888", 0.6, true);
  }

  const userProfile: Record<string, number> = {};
  for (const cid of compIds) {
    userProfile[cid] = isComp
      ? (state.competencies[cid]?.peer_comparable_percentage ?? state.competencies[cid]?.percentage ?? 0)
      : helpers.getEffectivePercentage(cid);
  }
  svg += makePolygon(userProfile, levelColors.you, 1.0, false);

  let legendX = 10;
  const legendY = height - 15;
  const items: [string, string][] = [["you", "You"], ...activeLevels.map(lk => [lk, ({se: "Senior", pse: "Principal", spse: "Sr Principal", de: "Distinguished"} as Record<string, string>)[lk] || lk] as [string, string])];
  for (const [lk, label] of items) {
    const color = levelColors[lk] || "#888";
    const dash = lk === "you" ? "" : ` stroke-dasharray="6,4"`;
    svg += `<line x1="${legendX}" y1="${legendY}" x2="${legendX + 18}" y2="${legendY}" stroke="${color}" stroke-width="2"${dash}/>`;
    svg += `<text x="${legendX + 22}" y="${legendY + 3}" fill="var(--vscode-foreground, #666)" font-size="9">${helpers.escapeHtml(label)}</text>`;
    legendX += 85;
  }

  svg += "</svg>";
  return svg;
}

export function renderLevelDistributionTable(
  state: PerformanceState,
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
): string {
  const isComp = (state.peer_comparison_mode || "comparable") === "comparable";
  const hasStats = activeLevels.some(lk => {
    const st = isComp
      ? (benchmarks.levels[lk]?.comparable_stats_overall ?? benchmarks.levels[lk]?.stats_overall)
      : benchmarks.levels[lk]?.stats_overall;
    return (st?.count ?? 0) > 0;
  });
  if (!hasStats) return "";

  const userLevel = state.scoring_config?.engineering_level || "sse";
  const modeLabel = isComp ? " (Normalized)" : "";
  let html = `<div class="section"><div class="section-title">Level Distribution (Overall Score)${modeLabel}</div>`;
  html += `<table class="peer-volume-table"><thead><tr><th>Level</th><th>Peers</th><th>Min</th><th>P25</th><th>Avg</th><th>Median</th><th>P75</th><th>Max</th></tr></thead><tbody>`;
  for (const lk of activeLevels) {
    const st = isComp
      ? (benchmarks.levels[lk]?.comparable_stats_overall ?? benchmarks.levels[lk]?.stats_overall)
      : benchmarks.levels[lk]?.stats_overall;
    if (!st) continue;
    const color = levelColors[lk] || "#888";
    const rowClass = lk === userLevel ? " peer-row-highlight" : "";
    const rosterN = benchmarks.levels[lk]?.roster_count ?? 0;
    const peersLabel = rosterN > 0 ? `${st.count}/${rosterN}` : `${st.count}`;
    const lowNMark = st.count < 5 ? ' <span class="peer-warning-mark" title="Low sample size">\u26A0</span>' : "";
    html += `<tr${rowClass ? ` class="${rowClass.trim()}"` : ""}><td class="peer-level-cell" style="color:${color}">${helpers.escapeHtml(levelLabels[lk] || lk)}</td><td>${peersLabel}${lowNMark}</td><td>${st.min}%</td><td>${st.p25}%</td><td>${st.avg}%</td><td>${st.median}%</td><td>${st.p75}%</td><td>${st.max}%</td></tr>`;
  }
  html += `</tbody></table></div>`;
  return html;
}

export function renderVolumeTable(
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
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
    html += `<th style="color:${color}">${helpers.escapeHtml(levelLabels[lk] || lk)}</th>`;
  }
  html += `</tr></thead><tbody>`;

  for (const src of sources) {
    html += `<tr><td>${helpers.escapeHtml(src.charAt(0).toUpperCase() + src.slice(1))}</td>`;
    for (const lk of activeLevels) {
      const val = benchmarks.levels[lk]?.avg_event_counts_by_source?.[src] ?? 0;
      const display = typeof val === "number" && !Number.isInteger(val) ? val.toFixed(1) : String(val);
      html += `<td>${display}</td>`;
    }
    html += `</tr>`;
  }

  html += `<tr class="peer-volume-total"><td>Total</td>`;
  for (const lk of activeLevels) {
    const total = sources.reduce((s, src) => s + (benchmarks.levels[lk]?.avg_event_counts_by_source?.[src] ?? 0), 0);
    html += `<td>${total.toFixed(1)}</td>`;
  }
  html += `</tr></tbody></table></div>`;
  return html;
}

export function renderRadarStatsLegend(
  benchmarks: PeerBenchmarks,
  activeLevels: string[],
  levelLabels: Record<string, string>,
  levelColors: Record<string, string>,
  helpers: PeersHelpers,
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
    const lowN = st.count < 5 ? ' <span class="peer-warning-mark">\u26A0</span>' : "";
    html += `<span class="peer-radar-stats-item" style="color:${color}"><strong>${helpers.escapeHtml(label)}</strong>: avg ${st.avg}% &middot; min ${st.min}% &middot; max ${st.max}% &middot; median ${st.median}% (${nLabel})${lowN}</span>`;
  }
  html += `</div>`;
  return html;
}

export function renderPromotionReadiness(state: PerformanceState, helpers: PeersHelpers): string {
  const promo = state.ai_promotion_readiness;
  if (!promo) return "";

  let assessHtml = "";
  for (const a of promo.assessments) {
    const cls = a.status === "ready" ? "positive" : a.status === "almost" ? "neutral" : "negative";
    const icon = a.status === "ready" ? "\u2705" : a.status === "almost" ? "\u{1F7E1}" : "\u274C";
    assessHtml += `<div class="promo-assess-row ${cls}"><span class="promo-icon">${icon}</span><span class="promo-comp">${helpers.escapeHtml(a.name)}</span><span class="promo-pct">${a.user_pct}% / ${a.target_pct}%</span><span class="promo-delta">${a.delta >= 0 ? "+" : ""}${a.delta}%</span></div>`;
  }

  const src = promo.source === "ai" ? "AI" : "Analysis";
  return `
    <div class="section">
      <div class="section-title">Promotion Readiness: ${helpers.escapeHtml(promo.next_level_label)} <span class="ai-badge">${helpers.escapeHtml(src)}</span></div>
      <div class="ai-insight-card">${helpers.escapeHtml(promo.summary)}</div>
      <div class="promo-summary mt-8">Meeting ${promo.ready_count}/${promo.total_competencies} competency benchmarks</div>
      <div class="promo-assessments mt-8">${assessHtml}</div>
    </div>`;
}
