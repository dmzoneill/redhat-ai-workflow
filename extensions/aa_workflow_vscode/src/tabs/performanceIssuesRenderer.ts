/**
 * Issues tab renderer for Performance panel.
 * Extracted from PerformanceTab.ts renderIssuesTab and related methods.
 */

import type { PerformanceState, IssueNode, IssueHierarchy } from "./performanceTypes";
import {
  SCOPE_COLORS,
  TAG_CATEGORY_COLORS,
  getColorForPercentage,
  getBarColor,
  getTagCategory,
} from "./performanceConfig";

export interface IssuesHelpers {
  escapeHtml(s: string): string;
  getEmptyStateHtml(icon: string, msg: string): string;
  safeText(s: string): string;
  formatCompetencyName(id: string): string;
  renderIssueLink(key: string): string;
  renderIssueLinks(keys: string[]): string;
  getTypeIcon(type: string): string;
}

function getMaxPoints(hierarchy: IssueHierarchy): number {
  let max = 0;
  const walk = (nodes: IssueNode[]) => {
    for (const n of nodes) {
      if (n.points > max) max = n.points;
      if (n.children) walk(n.children);
    }
  };
  walk(hierarchy.strategies || []);
  walk(hierarchy.unattached_epics || []);
  walk(hierarchy.uncategorized || []);
  return max || 1;
}

function countDescendants(node: IssueNode): number {
  let count = 0;
  const walk = (n: IssueNode) => {
    if (n.children) {
      for (const c of n.children) {
        count++;
        walk(c);
      }
    }
  };
  walk(node);
  return count;
}

function collectAllTags(node: IssueNode): string[] {
  const tags = new Set<string>();
  const walk = (n: IssueNode) => {
    for (const k of n.keywords || []) tags.add(k);
    if (n.children) n.children.forEach(walk);
  };
  walk(node);
  return [...tags];
}

function renderCardTags(node: IssueNode, helpers: IssuesHelpers): string {
  const allTags: Record<string, number> = {};
  const walk = (n: IssueNode) => {
    for (const k of n.keywords || []) {
      allTags[k] = (allTags[k] || 0) + 1;
    }
    if (n.children) n.children.forEach(walk);
  };
  walk(node);
  const sorted = Object.entries(allTags).sort((a, b) => b[1] - a[1]);
  if (sorted.length === 0) return "";
  return `<div class="issue-card-tags">${sorted
    .slice(0, 8)
    .map(([tag]) => {
      const cat = getTagCategory(tag);
      return `<span class="perf-issue-tag perf-tag-${cat}">${helpers.escapeHtml(tag)}</span>`;
    })
    .join("")}</div>`;
}

function renderTreeNode(
  node: IssueNode,
  depth: number,
  nodeType: string,
  maxPts: number,
  helpers: IssuesHelpers,
): string {
  if (!node) return "";
  const children = Array.isArray(node.children) ? node.children : [];
  const hasChildren = children.length > 0;
  const indent = depth * 20;
  const toggle = hasChildren
    ? `<span class="perf-tree-toggle" data-action="toggleNode" data-key="${helpers.escapeHtml(node.key)}">&#9654;</span>`
    : `<span class="perf-tree-toggle-spacer"></span>`;

  const typeIcon = helpers.getTypeIcon(nodeType);
  const badge =
    nodeType === "strategy"
      ? "perf-strategy-badge"
      : nodeType === "epic"
        ? "perf-epic-badge"
        : "perf-issue-badge";

  const keywords =
    node.keywords && node.keywords.length > 0
      ? `<div class="perf-issue-tags">${node.keywords
          .map((k) => {
            const cat = getTagCategory(k);
            return `<span class="perf-issue-tag perf-tag-${cat}" data-tag="${helpers.escapeHtml(k)}">${helpers.escapeHtml(k)}</span>`;
          })
          .join("")}</div>`
      : "";

  const summary = node.summary
    ? `<span class="perf-tree-summary">${helpers.safeText(node.summary)}</span>`
    : "";

  const pct = maxPts > 0 ? Math.round((node.points / maxPts) * 100) : 0;
  const barColor =
    pct >= 80 ? "var(--success)" : pct >= 50 ? "var(--warning)" : pct >= 25 ? "#f97316" : "var(--error)";
  const pointsBar = `
    <span class="perf-tree-points-wrap">
      <span class="perf-tree-points-bar" style="width: ${Math.max(pct, 4)}%; background: ${barColor};"></span>
      <span class="perf-tree-points-label">${node.points}pts</span>
    </span>`;

  const aligned = node.strategy_aligned;
  const stratNames = (node.strategy_names || []).join(", ");
  const stratBadge = aligned
    ? `<span class="perf-strat-aligned" title="${helpers.escapeHtml(stratNames || "Strategy aligned")}">&#9632;</span>`
    : `<span class="perf-strat-unaligned" title="Not strategy-aligned">&#9633;</span>`;

  const pp = node.pillar_points || { technical: 0, leadership: 0, mentorship: 0, delivery: 0 };
  const pillarTotal = pp.technical + pp.leadership + pp.mentorship + pp.delivery;
  let pillarBar = "";
  if (pillarTotal > 0) {
    const techPct = Math.round((pp.technical / pillarTotal) * 100);
    const leadPct = Math.round((pp.leadership / pillarTotal) * 100);
    const mentPct = Math.round((pp.mentorship / pillarTotal) * 100);
    const delPct = 100 - techPct - leadPct - mentPct;
    pillarBar = `
      <div class="perf-pillar-microbar" title="Tech: ${pp.technical} | Lead: ${pp.leadership} | Ment: ${pp.mentorship} | E2E: ${pp.delivery}">
        <span class="perf-pillar-seg perf-pillar-tech" style="width:${techPct}%"></span>
        <span class="perf-pillar-seg perf-pillar-lead" style="width:${leadPct}%"></span>
        <span class="perf-pillar-seg perf-pillar-ment" style="width:${mentPct}%"></span>
        <span class="perf-pillar-seg perf-pillar-del" style="width:${delPct}%"></span>
      </div>`;
  }

  let html = `
    <div class="perf-tree-node depth-${depth}" style="padding-left: ${indent}px;" data-key="${helpers.escapeHtml(node.key)}" data-tags="${helpers.escapeHtml((node.keywords || []).join(","))}">
      <div class="perf-tree-node-header">
        ${toggle}
        <span class="perf-tree-icon">${typeIcon}</span>
        ${stratBadge}
        <span class="${badge}">${helpers.renderIssueLink(node.key)}</span>
        ${summary}
        ${pointsBar}
        <span class="perf-tree-count">${node.event_count || ""}ev</span>
      </div>
      ${pillarBar}
      ${keywords}
    </div>
  `;

  if (hasChildren) {
    html += `<div class="perf-tree-children" data-parent="${helpers.escapeHtml(node.key)}">`;
    for (const child of children) {
      const childChildren = Array.isArray(child.children) ? child.children : [];
      const childType = childChildren.length > 0 ? "epic" : "issue";
      html += renderTreeNode(child, depth + 1, childType, maxPts, helpers);
    }
    html += `</div>`;
  }

  return html;
}

function renderIssuesDashboard(state: PerformanceState, helpers: IssuesHelpers): string {
  const h = state.issue_hierarchy;
  if (!h || !h.summary) return "";
  const s = h.summary;

  const dataJson = JSON.stringify({
    strategies: (h.strategies || []).map((st: IssueNode) => ({
      key: st.key,
      summary: st.summary,
      points: st.points,
      children: (st.children || []).map((ep: IssueNode) => ({
        key: ep.key,
        summary: ep.summary,
        points: ep.points,
        children: (ep.children || []).map((is: IssueNode) => ({
          key: is.key,
          summary: is.summary,
          points: is.points,
        })),
      })),
    })),
    scope_points: s.scope_points,
    alignment_pct: s.alignment_pct,
    aligned_points: s.aligned_points,
    unaligned_points: s.unaligned_points,
    tag_counts: s.tag_counts,
    pillar_points: s.pillar_points,
    total_points: s.total_points,
  });

  const strategies = h.strategies || [];
  const maxStratPts = Math.max(...strategies.map((st: IssueNode) => st.points || 0), 1);
  const stratFallback =
    strategies.length > 0
      ? strategies
          .map((st: IssueNode) => {
            const pct = Math.max(Math.round(((st.points || 0) / maxStratPts) * 100), 4);
            return `<div class="issues-dash-strat-row">
            <span class="issues-dash-strat-key">${helpers.escapeHtml(st.key.replace("ANSTRAT-", "S-"))}</span>
            <span class="issues-dash-strat-bar" style="width:${pct}%"></span>
            <span class="issues-dash-strat-pts">${st.points || 0}</span>
          </div>`;
          })
          .join("")
      : `<div class="text-muted-sm">No strategy data</div>`;

  const scopeColors = SCOPE_COLORS;
  const scopeEntries = Object.entries(s.scope_points || {}).filter(([, v]) => (v as number) > 0);
  const scopeTotal = scopeEntries.reduce((sum, [, v]) => sum + (v as number), 0);
  const scopeFallback =
    scopeTotal > 0
      ? `<div class="issues-dash-scope-total">${scopeTotal}</div>
         <div class="issues-dash-scope-legend">${scopeEntries
           .map(
             ([k, v]) =>
               `<span class="issues-dash-scope-item"><span class="issues-dash-scope-dot" style="background:${scopeColors[k] || "#6b7280"}"></span>${k}: ${v}</span>`,
           )
           .join("")}</div>`
      : `<div class="text-muted-sm">No scope data</div>`;

  const pct = s.alignment_pct || 0;
  const aligned = s.aligned_points || 0;
  const unaligned = s.unaligned_points || 0;
  const barColor = getBarColor(pct, "coverage");
  const gaugeFallback = `
    <div class="issues-gauge-pct">${pct}%</div>
    <div class="issues-gauge-label">of points are strategy-aligned</div>
    <div class="issues-gauge-bar"><div class="issues-gauge-fill" style="width:${pct}%;background:${barColor};"></div></div>
    <div class="issues-gauge-legend">
      <span><span class="issues-gauge-dot" style="background:${barColor}"></span>Aligned: ${aligned}pts</span>
      <span><span class="issues-gauge-dot" style="background:var(--bg-tertiary)"></span>Other: ${unaligned}pts</span>
    </div>`;

  const tagEntries = Object.entries(s.tag_counts || {});
  const maxTagCount = tagEntries.reduce((m, [, v]) => Math.max(m, v as number), 0) || 1;
  const tagFallback =
    tagEntries.length > 0
      ? tagEntries
          .slice(0, 10)
          .map(([tag, count]) => {
            const tagPct = Math.max(Math.round(((count as number) / maxTagCount) * 100), 4);
            const cat = getTagCategory(tag);
            return `<div class="issues-tag-bar-row">
            <span class="issues-tag-bar-label">${helpers.escapeHtml(tag)}</span>
            <span class="issues-tag-bar-fill" style="width:${tagPct}%;background:${TAG_CATEGORY_COLORS[cat] || TAG_CATEGORY_COLORS.other};"></span>
            <span class="issues-tag-bar-count">${count}</span>
          </div>`;
          })
          .join("")
      : `<div class="text-muted-sm">No tag data</div>`;

  return `
    <div class="issues-dashboard">
      <div class="issues-dashboard-row">
        <div class="issues-dash-card">
          <div class="issues-dash-title">Strategy Points</div>
          <div id="issuesDashTreemap" class="issues-dash-chart">${stratFallback}</div>
        </div>
        <div class="issues-dash-card">
          <div class="issues-dash-title">Points by Scope</div>
          <div id="issuesDashDonut" class="issues-dash-chart issues-dash-scope-fallback">${scopeFallback}</div>
        </div>
        <div class="issues-dash-card">
          <div class="issues-dash-title">Strategy Alignment</div>
          <div id="issuesDashGauge" class="issues-dash-chart issues-dash-gauge">${gaugeFallback}</div>
        </div>
        <div class="issues-dash-card issues-dash-card-wide">
          <div class="issues-dash-title">Tag Distribution</div>
          <div id="issuesDashTags" class="issues-dash-chart">${tagFallback}</div>
        </div>
      </div>
    </div>
    <script type="application/json" id="issuesDashboardData">${dataJson}</script>
  `;
}

function renderTagFilterBar(state: PerformanceState, helpers: IssuesHelpers): string {
  const h = state.issue_hierarchy;
  if (!h || !h.summary || !h.summary.tag_counts) return "";
  const tags = Object.keys(h.summary.tag_counts);
  if (tags.length === 0) return "";
  return `
    <div class="issues-tag-filter-bar">
      <span class="issues-tag-filter-label">Filter:</span>
      ${tags
        .map((t) => {
          const cat = getTagCategory(t);
          return `<button class="issues-tag-filter-btn perf-tag-${cat}" data-action="filterTag" data-tag="${helpers.escapeHtml(t)}">${helpers.escapeHtml(t)}</button>`;
        })
        .join("")}
      <button class="issues-tag-filter-btn issues-tag-clear" data-action="filterTag" data-tag="">all</button>
    </div>`;
}

function renderIssueHierarchy(state: PerformanceState, helpers: IssuesHelpers): string {
  const h = state.issue_hierarchy;
  if (!h || !h.total_issues) {
    return helpers.getEmptyStateHtml("--", "No issue data captured yet. Run daily collection to start tracking.");
  }

  const strategies = Array.isArray(h.strategies) ? h.strategies : [];
  const unattachedEpics = Array.isArray(h.unattached_epics) ? h.unattached_epics : [];
  const uncategorized = Array.isArray(h.uncategorized) ? h.uncategorized : [];
  const maxPts = getMaxPoints(h);

  const cacheNote = h.cached
    ? `<div class="perf-hierarchy-note">Using cached hierarchy. Click "Refresh from Jira" for live data.</div>`
    : "";

  let html = `<div class="perf-hierarchy">${cacheNote}`;

  for (const strat of strategies) {
    const stratPts = strat.points || 0;
    const childCount = countDescendants(strat);
    const barColor = getColorForPercentage(maxPts > 0 ? Math.round((stratPts / maxPts) * 100) : 0);
    const allStratTags = collectAllTags(strat);
    html += `
      <div class="issue-card" data-key="${helpers.escapeHtml(strat.key)}" data-tags="${helpers.escapeHtml(allStratTags.join(","))}">
        <div class="issue-card-header">
          <span class="perf-tree-toggle" data-action="toggleNode" data-key="${helpers.escapeHtml(strat.key)}">&#9654;</span>
          <span class="issue-card-icon">\u{1F3AF}</span>
          <span class="issue-card-key">${helpers.renderIssueLink(strat.key)}</span>
          <span class="issue-card-summary">${helpers.safeText(strat.summary || "")}</span>
        </div>
        <div class="issue-card-stats">
          <span class="issue-card-stat">
            <span class="issue-card-stat-value" style="color:${barColor}">${stratPts}</span>
            <span class="issue-card-stat-label">points</span>
          </span>
          <span class="issue-card-stat">
            <span class="issue-card-stat-value">${childCount}</span>
            <span class="issue-card-stat-label">issues</span>
          </span>
          <span class="issue-card-stat">
            <span class="issue-card-stat-value">${strat.event_count || 0}</span>
            <span class="issue-card-stat-label">events</span>
          </span>
          <span class="issue-card-bar-wrap">
            <span class="issue-card-bar" style="width:${maxPts > 0 ? Math.max(Math.round((stratPts / maxPts) * 100), 4) : 4}%;background:${barColor};"></span>
          </span>
        </div>
        ${renderCardTags(strat, helpers)}
        <div class="perf-tree-children" data-parent="${helpers.escapeHtml(strat.key)}">
          ${(strat.children || [])
            .map((child: IssueNode) => {
              const childChildren = Array.isArray(child.children) ? child.children : [];
              const childType = childChildren.length > 0 ? "epic" : "issue";
              return renderTreeNode(child, 1, childType, maxPts, helpers);
            })
            .join("")}
        </div>
      </div>`;
  }

  const unalignedItems = [...unattachedEpics, ...uncategorized];
  if (unalignedItems.length > 0) {
    const unalignedPts = unalignedItems.reduce((sum, n) => sum + (n.points || 0), 0);
    const unalignedEvents = unalignedItems.reduce((sum, n) => sum + (n.event_count || 0), 0);
    html += `
      <div class="issue-card issue-card-unaligned" data-tags="${helpers.escapeHtml(unalignedItems.flatMap((n) => n.keywords || []).join(","))}">
        <div class="issue-card-header">
          <span class="perf-tree-toggle" data-action="toggleNode" data-key="__unaligned__">&#9654;</span>
          <span class="issue-card-icon">\u{1F4CB}</span>
          <span class="issue-card-summary">Unaligned Work <span class="text-muted-sm">(not linked to a strategy)</span></span>
        </div>
        <div class="issue-card-stats">
          <span class="issue-card-stat">
            <span class="issue-card-stat-value">${unalignedPts}</span>
            <span class="issue-card-stat-label">points</span>
          </span>
          <span class="issue-card-stat">
            <span class="issue-card-stat-value">${unalignedItems.length}</span>
            <span class="issue-card-stat-label">issues</span>
          </span>
          <span class="issue-card-stat">
            <span class="issue-card-stat-value">${unalignedEvents}</span>
            <span class="issue-card-stat-label">events</span>
          </span>
        </div>
        <div class="perf-tree-children" data-parent="__unaligned__">`;
    for (const epic of unattachedEpics) {
      html += renderTreeNode(epic, 1, "epic", maxPts, helpers);
    }
    for (const issue of uncategorized) {
      html += renderTreeNode(issue, 1, "issue", maxPts, helpers);
    }
    html += `
        </div>
      </div>`;
  }

  html += `</div>`;
  return html;
}

export function getIssuesContent(state: PerformanceState, helpers: IssuesHelpers): string {
  return `
    <div class="perf-tab-panel">
      ${renderIssuesDashboard(state, helpers)}
      <div class="section">
        <div class="section-title">
          <span>Delivered Issues</span>
          <div class="d-flex gap-8">
            <button class="btn btn-xs" data-action="detectMissingLinks">Detect Missing Links</button>
            <button class="btn btn-xs" data-action="refreshHierarchy">Refresh from Jira</button>
          </div>
        </div>
        ${renderTagFilterBar(state, helpers)}
        <div class="issue-cards-grid">
          ${renderIssueHierarchy(state, helpers)}
        </div>
      </div>
      <div id="missingLinksContainer"></div>
    </div>
  `;
}
