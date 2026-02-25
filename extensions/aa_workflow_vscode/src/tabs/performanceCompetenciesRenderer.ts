/**
 * Performance Competencies Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getCompetenciesContent for the
 * Competencies tab (Sunburst / Weighted Mindmap view, expandable bars, gaps).
 */

import type { PerformanceState, SenderSummary } from "./performanceTypes";
import { PILLAR_DEFS, DEFAULT_SCOPE_MULTIPLIERS, getColorForPercentage, pillarTint } from "./performanceConfig";
import {
  renderExpandableCompetencyBars,
  renderGapsWithSuggestions,
} from "./performanceOverviewRenderer";
import type { OverviewHelpers } from "./performanceOverviewRenderer";

export interface CompetenciesHelpers {
  getEffectivePercentage(compId: string): number;
  getEffectiveOverall(): number;
  formatCompetencyName(id: string): string;
  escapeHtml(s: string): string;
  getEmptyStateHtml(icon: string, msg: string): string;
  renderIssueLink(key: string): string;
  renderIssueLinks(keys: string[]): string;
  safeText(s: string): string;
}

function arcPath(
  cx: number,
  cy: number,
  innerR: number,
  outerR: number,
  startAngle: number,
  sweepAngle: number,
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

// ---------------------------------------------------------------------------
// Sunburst
// ---------------------------------------------------------------------------

function generateSunburstSVG(
  state: PerformanceState,
  helpers: CompetenciesHelpers,
): string {
  const width = 590;
  const height = 590;
  const cx = width / 2;
  const cy = height / 2;
  const r0 = 80;
  const r1 = 155;
  const r2 = 260;

  const competencies = state.competencies;
  const overall = helpers.getEffectiveOverall();

  const pillarColors: Record<string, string> = {};
  for (const [pn, pd] of Object.entries(PILLAR_DEFS)) pillarColors[pn] = pd.color;

  const catMap: Record<string, string[]> = {};
  for (const [compId, m] of Object.entries(state.competency_meta)) {
    const cat = m.category || "Technical Contribution";
    if (!catMap[cat]) catMap[cat] = [];
    catMap[cat].push(compId);
  }
  const metaCategories = Object.keys(PILLAR_DEFS).map((name) => ({
    id: name.toLowerCase().replace(/[^a-z]+/g, "_"),
    name,
    competencies: catMap[name] || [],
  }));

  let paths = "";
  const bg = "var(--bg-primary, #1a1a2e)";

  const centerColor = getColorForPercentage(overall);
  paths += `
      <circle cx="${cx}" cy="${cy}" r="${r0 - 5}" fill="${centerColor}" opacity="0.15"/>
      <circle cx="${cx}" cy="${cy}" r="${r0 - 5}" fill="none" stroke="${centerColor}" stroke-width="2" opacity="0.4"/>
      <text x="${cx}" y="${cy - 12}" text-anchor="middle" dominant-baseline="middle"
            font-size="38" font-weight="bold" fill="${centerColor}">${overall}%</text>
      <text x="${cx}" y="${cy + 16}" text-anchor="middle"
            font-size="13" fill="#888">${state.quarter || "Q1 2026"}</text>
    `;

  const categoryAngle = 360 / metaCategories.length;
  let startAngle = -90;

  metaCategories.forEach((cat) => {
    const pColor = pillarColors[cat.name] || "#888";
    const catValues = cat.competencies.map((c) => helpers.getEffectivePercentage(c));
    const catAvg =
      catValues.length > 0
        ? Math.round(catValues.reduce((a, b) => a + b, 0) / catValues.length)
        : 0;

    const catPath = arcPath(cx, cy, r0, r1, startAngle, categoryAngle - 2);
    const catOpacity = 0.3 + (catAvg / 100) * 0.5;
    paths += `
        <path d="${catPath}" fill="${pColor}" opacity="${catOpacity.toFixed(2)}" stroke="${bg}" stroke-width="2">
          <title>${cat.name}: ${catAvg}%</title>
        </path>
      `;

    const labelRad = ((startAngle + categoryAngle / 2) * Math.PI) / 180;
    const labelR = (r0 + r1) / 2;
    const lx = cx + labelR * Math.cos(labelRad);
    const ly = cy + labelR * Math.sin(labelRad);
    const labelAngle = startAngle + categoryAngle / 2;
    const rotate =
      labelAngle > 0 && labelAngle < 180 ? labelAngle + 90 + 180 : labelAngle + 90;
    const pillarShort = cat.name
      .replace("End-to-End ", "E2E ")
      .replace("Technical ", "Tech ");
    paths += `
        <text x="${lx.toFixed(1)}" y="${(ly - 8).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
              font-size="11" font-weight="600" fill="#fff" opacity="0.9"
              transform="rotate(${rotate.toFixed(1)},${lx.toFixed(1)},${ly.toFixed(1)})">${pillarShort}</text>
        <text x="${lx.toFixed(1)}" y="${(ly + 6).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
              font-size="12" font-weight="700" fill="#fff" opacity="0.95"
              transform="rotate(${rotate.toFixed(1)},${lx.toFixed(1)},${ly.toFixed(1)})">${catAvg}%</text>
      `;

    const compAngle = categoryAngle / Math.max(cat.competencies.length, 1);
    let compStart = startAngle;

    cat.competencies.forEach((compId) => {
      const compPct = helpers.getEffectivePercentage(compId);
      const compColor = getColorForPercentage(compPct);
      const compPath = arcPath(cx, cy, r1, r2, compStart, compAngle - 1);

      paths += `
          <path d="${compPath}" fill="${compColor}" opacity="0.8"
                stroke="${bg}" stroke-width="1">
            <title>${helpers.formatCompetencyName(compId)}: ${compPct}%</title>
          </path>
        `;

      const cRad = ((compStart + compAngle / 2) * Math.PI) / 180;
      const cR = (r1 + r2) / 2;
      const clx = cx + cR * Math.cos(cRad);
      const cly = cy + cR * Math.sin(cRad);
      const cAngle = compStart + compAngle / 2;
      const cRotate =
        cAngle > 0 && cAngle < 180 ? cAngle + 90 + 180 : cAngle + 90;
      const shortName = helpers.formatCompetencyName(compId);
      const displayName =
        shortName.length > 18 ? shortName.substring(0, 16) + ".." : shortName;
      paths += `
          <text x="${clx.toFixed(1)}" y="${(cly - 6).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
                font-size="10" fill="#fff" opacity="0.85"
                transform="rotate(${cRotate.toFixed(1)},${clx.toFixed(1)},${cly.toFixed(1)})">${displayName}</text>
          <text x="${clx.toFixed(1)}" y="${(cly + 7).toFixed(1)}" text-anchor="middle" dominant-baseline="middle"
                font-size="11" font-weight="600" fill="#fff" opacity="0.95"
                transform="rotate(${cRotate.toFixed(1)},${clx.toFixed(1)},${cly.toFixed(1)})">${compPct}%</text>
        `;

      compStart += compAngle;
    });

    startAngle += categoryAngle;
  });

  const legendY = height - 10;
  let legendX = 30;
  const legendItems = Object.entries(PILLAR_DEFS).map(([name, def]) => ({
    color: def.color,
    label: name.replace("End-to-End ", "E2E "),
  }));
  legendItems.forEach((item) => {
    paths += `<rect x="${legendX}" y="${legendY - 10}" width="14" height="14" rx="2" fill="${item.color}" opacity="0.8"/>`;
    paths += `<text x="${legendX + 18}" y="${legendY}" font-size="16" fill="#888">${item.label}</text>`;
    legendX += item.label.length * 9.5 + 28;
  });

  return `
    <svg class="perf-sunburst-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
         xmlns="http://www.w3.org/2000/svg">
      <style>
        text { font-family: system-ui, -apple-system, sans-serif; }
        path:hover { opacity: 1 !important; filter: brightness(1.2); }
      </style>
      ${paths}
    </svg>
  `;
}

// ---------------------------------------------------------------------------
// Weighted Competency Mindmap
// ---------------------------------------------------------------------------

function buildWeightedCompetencyGraph(
  state: PerformanceState,
  helpers: CompetenciesHelpers,
): { nodes: any[]; links: any[]; pillarInfo: any[]; stats: any } | null {
  const meta = state.competency_meta || {};
  const comps = state.competencies || {};
  const evidence = state.competency_evidence || {};
  const h = state.issue_hierarchy;
  const cfg = state.scoring_config;
  const hasCompetencies = Object.keys(meta).length > 0;
  const hasIssues = h && h.total_issues > 0;

  if (!hasCompetencies && !hasIssues) return null;

  const scopeMult: Record<string, number> =
    cfg?.scope_multipliers || DEFAULT_SCOPE_MULTIPLIERS;
  const levelWeights = cfg?.level_weights || {};
  const pillarWeightsMap: Record<string, number> =
    levelWeights.pillar_weights || {};
  const roleWeightsMap: Record<string, Record<string, number>> =
    levelWeights.role_weights || {};
  const targetPerComp = cfg?.target_per_competency || 100;
  const targetScale = levelWeights.target_scale ?? 1.0;
  const effectiveTarget = Math.round(targetPerComp * targetScale);

  const nodes: any[] = [];
  const links: any[] = [];

  const pillarNames = Object.keys(PILLAR_DEFS);
  const angleStep = 360 / pillarNames.length;
  const pillarDefs: Record<
    string,
    { label: string; color: string; angle: number; compIds: string[] }
  > = {};
  pillarNames.forEach((name, i) => {
    pillarDefs[name] = {
      label: name,
      color: PILLAR_DEFS[name].color,
      angle: i * angleStep,
      compIds: [],
    };
  });

  for (const [compId, m] of Object.entries(meta)) {
    const cat = m.category || "Technical Contribution";
    if (pillarDefs[cat]) pillarDefs[cat].compIds.push(compId);
  }

  const allPillarIds = Object.keys(pillarDefs).map((n) =>
    `wm_pillar_${n.replace(/[^a-z]/gi, "_")}`,
  );

  const compEvidenceKeys: Record<string, Set<string>> = {};
  const compEvidencePoints: Record<string, Record<string, number>> = {};
  for (const [compId, events] of Object.entries(evidence)) {
    const keys = new Set<string>();
    const keyPoints: Record<string, number> = {};
    for (const ev of events) {
      for (const k of ev.issue_keys || []) {
        keys.add(k);
        keyPoints[k] = (keyPoints[k] || 0) + ev.points;
      }
    }
    compEvidenceKeys[compId] = keys;
    compEvidencePoints[compId] = keyPoints;
  }

  const rootId = "wm_root";
  const overallPct = helpers.getEffectiveOverall() || 0;
  nodes.push({
    id: rootId,
    label: state.quarter,
    sublabel: `${overallPct}%`,
    type: "root",
    percentage: overallPct,
    size: 32,
    color: "#667eea",
    pillars: allPillarIds,
    weightInfo: `Overall: ${overallPct}%`,
  });

  let compCount = 0,
    anstratCount = 0,
    epicCount = 0,
    issueCount = 0,
    stratCount = 0,
    evidenceLinkCount = 0;

  for (const [pillarName, pDef] of Object.entries(pillarDefs)) {
    const pillarId = `wm_pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;
    const pillarComps = pDef.compIds;
    const avgPct =
      pillarComps.length > 0
        ? Math.round(
            pillarComps.reduce(
              (s, id) => s + (comps[id]?.percentage || 0),
              0,
            ) / pillarComps.length,
          )
        : 0;
    const totalPts = pillarComps.reduce(
      (s, id) => s + (comps[id]?.points || 0),
      0,
    );
    const pw = pillarWeightsMap[pillarName] ?? 1.0;

    nodes.push({
      id: pillarId,
      label: pDef.label,
      sublabel: `${avgPct}% \u00B7 w=${pw}`,
      type: "pillar",
      percentage: avgPct,
      size: 24,
      color: pDef.color,
      heatColor: getColorForPercentage(avgPct),
      angle: pDef.angle,
      compCount: pillarComps.length,
      pillars: [pillarId],
      weightInfo: `Avg: ${avgPct}% | ${totalPts}pts | pillar_w: ${pw}`,
    });
    links.push({
      source: rootId,
      target: pillarId,
      type: "hierarchy",
      label: `w=${pw}`,
    });

    for (const compId of pillarComps) {
      compCount++;
      const m = meta[compId];
      const c = comps[compId];
      const pct = c?.percentage || m?.percentage || 0;
      const pts = c?.points || m?.points || 0;
      const target = m?.target || effectiveTarget;
      const evCount = m?.evidence_count || 0;
      const basePoints = cfg?.competencies?.[compId]?.base_points || 0;

      const nodeId = `wm_comp_${compId}`;
      const compTint = pillarTint(pDef.color, "competency", pct);
      nodes.push({
        id: nodeId,
        compId,
        label: m.name,
        sublabel: `${pts}/${target} (${pct}%)`,
        type: "competency",
        category: m.category,
        percentage: pct,
        points: pts,
        target,
        evidenceCount: evCount,
        size: Math.min(Math.max(evCount * 1.5 + 8, 8), 20),
        color: compTint,
        heatColor: compTint,
        pillarColor: pDef.color,
        pillarId,
        pillarAngle: pDef.angle,
        pillars: [pillarId],
        weightInfo: `${pts}/${target} = ${pct}% | base: ${basePoints} | ${evCount} events`,
      });
      links.push({ source: pillarId, target: nodeId, type: "hierarchy" });
    }
  }

  if (hasIssues && h) {
    const issueStrategies = Array.isArray(h.strategies) ? h.strategies : [];
    const unattachedEpics = Array.isArray(h.unattached_epics)
      ? h.unattached_epics
      : [];
    const uncatIssues = Array.isArray(h.uncategorized) ? h.uncategorized : [];

    const pillarIdToHex: Record<string, string> = {};
    for (const [pn, pd] of Object.entries(pillarDefs)) {
      pillarIdToHex[`wm_pillar_${pn.replace(/[^a-z]/gi, "_")}`] = pd.color;
    }

    const anstratIssueKeys: Record<string, Set<string>> = {};
    const anstratNodeIds: string[] = [];

    const anstratScopeMult = scopeMult.anstrat ?? 7;
    const epicScopeMult = scopeMult.epic ?? 4;
    const storyScopeMult = scopeMult.story ?? 2;

    issueStrategies.forEach((group, gi) => {
      anstratCount++;
      const gId = `wm_anstrat_${gi}`;
      anstratNodeIds.push(gId);
      const allKeys = new Set<string>();

      nodes.push({
        id: gId,
        label: group.key.replace(/^ANSTRAT-/, "AN-"),
        fullKey: group.key,
        summary: group.summary,
        sublabel: `${group.points}pts \u00D7${anstratScopeMult}`,
        type: "anstrat",
        points: group.points,
        size: Math.min(Math.max(group.points / 8, 16), 24),
        color: "#06b6d4",
        eventCount: group.event_count || 0,
        pillars: [] as string[],
        weightInfo: `${group.points}pts | scope: \u00D7${anstratScopeMult} | ${group.event_count || 0} events`,
      });

      (group.children || []).forEach((child, ci) => {
        epicCount++;
        const cId = `${gId}_epic_${ci}`;
        nodes.push({
          id: cId,
          label: child.key.replace(/^AAP-/, ""),
          fullKey: child.key,
          summary: child.summary,
          sublabel: `${child.points}pts \u00D7${epicScopeMult}`,
          type: "epic",
          points: child.points,
          size: Math.min(Math.max(child.points / 8, 10), 18),
          color: "#f97316",
          eventCount: child.event_count || 0,
          parentAnstrat: gId,
          pillars: [] as string[],
          weightInfo: `${child.points}pts | scope: \u00D7${epicScopeMult} | ${child.event_count || 0} events`,
        });
        links.push({
          source: gId,
          target: cId,
          type: "parent",
          label: `\u00D7${epicScopeMult}`,
        });
        allKeys.add(child.key);

        (child.children || []).forEach((issue, ii) => {
          issueCount++;
          const iId = `${cId}_issue_${ii}`;
          nodes.push({
            id: iId,
            label: issue.key.replace(/^AAP-/, ""),
            fullKey: issue.key,
            summary: issue.summary,
            sublabel: `${issue.points}pts \u00D7${storyScopeMult}`,
            type: issue.type || "task",
            points: issue.points,
            size: Math.min(Math.max(issue.points / 10, 6), 12),
            color: "#e879f9",
            eventCount: issue.event_count || 0,
            parentAnstrat: gId,
            pillars: [] as string[],
            weightInfo: `${issue.points}pts | scope: \u00D7${storyScopeMult} | ${issue.event_count || 0} events`,
          });
          links.push({
            source: cId,
            target: iId,
            type: "parent",
            label: `\u00D7${storyScopeMult}`,
          });
          allKeys.add(issue.key);
        });
      });

      anstratIssueKeys[gId] = allKeys;
    });

    const findPillarForKey = (key: string): string | null => {
      for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
        if (compKeys.has(key)) {
          const cat = meta[compId]?.category || "Technical Contribution";
          return `wm_pillar_${cat.replace(/[^a-z]/gi, "_")}`;
        }
      }
      return null;
    };

    const nodeMap = new Map(nodes.map((n) => [n.id, n]));
    for (const [gId, issueKeys] of Object.entries(anstratIssueKeys)) {
      const linkedCompIds: string[] = [];

      for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
        let shared = 0;
        let sharedPts = 0;
        for (const k of compKeys) {
          if (issueKeys.has(k)) {
            shared++;
            sharedPts += compEvidencePoints[compId]?.[k] || 0;
          }
        }
        if (shared > 0) {
          linkedCompIds.push(compId);
          evidenceLinkCount++;
          links.push({
            source: `wm_comp_${compId}`,
            target: gId,
            type: "evidence",
            weight: shared,
            points: sharedPts,
            label: `${sharedPts}pts`,
          });
        }
      }

      const anstratNode = nodeMap.get(gId);
      if (linkedCompIds.length > 0 && anstratNode) {
        const assocPillars = new Set<string>();
        for (const cid of linkedCompIds) {
          const cat = meta[cid]?.category || "Technical Contribution";
          assocPillars.add(`wm_pillar_${cat.replace(/[^a-z]/gi, "_")}`);
        }
        anstratNode.pillars = Array.from(assocPillars);
      } else {
        if (anstratNode) anstratNode.pillars = allPillarIds.slice();
        links.push({ source: rootId, target: gId, type: "parent" });
      }

      const anstratPillars = anstratNode?.pillars || allPillarIds;
      for (const n of nodes) {
        if (n.parentAnstrat === gId) n.pillars = anstratPillars;
      }
    }

    unattachedEpics.forEach((epic, ei) => {
      epicCount++;
      const eId = `wm_unattached_epic_${ei}`;
      const pillar = findPillarForKey(epic.key);
      const target = pillar || rootId;
      nodes.push({
        id: eId,
        label: epic.key.replace(/^AAP-/, ""),
        fullKey: epic.key,
        summary: epic.summary,
        sublabel: `${epic.points}pts \u00D7${epicScopeMult}`,
        type: "epic",
        points: epic.points,
        size: Math.min(Math.max(epic.points / 8, 10), 18),
        color: "#f97316",
        eventCount: epic.event_count || 0,
        pillars: pillar ? [pillar] : allPillarIds.slice(),
        weightInfo: `${epic.points}pts | scope: \u00D7${epicScopeMult}`,
      });
      links.push({ source: target, target: eId, type: "hierarchy" });

      (epic.children || []).forEach((issue, ii) => {
        issueCount++;
        const iId = `${eId}_issue_${ii}`;
        const issuePillar = findPillarForKey(issue.key) || pillar;
        const issuePillarHex = issuePillar
          ? pillarIdToHex[issuePillar] || "#e879f9"
          : "#e879f9";
        nodes.push({
          id: iId,
          label: issue.key.replace(/^AAP-/, ""),
          fullKey: issue.key,
          summary: issue.summary,
          sublabel: `${issue.points}pts \u00D7${storyScopeMult}`,
          type: issue.type || "task",
          points: issue.points,
          size: Math.min(Math.max(issue.points / 10, 6), 12),
          color: issuePillar
            ? pillarTint(issuePillarHex, "issue")
            : "#e879f9",
          eventCount: issue.event_count || 0,
          pillars: issuePillar ? [issuePillar] : allPillarIds.slice(),
          weightInfo: `${issue.points}pts | scope: \u00D7${storyScopeMult}`,
        });
        links.push({ source: eId, target: iId, type: "parent" });
      });
    });

    uncatIssues.forEach((issue, ui) => {
      issueCount++;
      const uId = `wm_uncat_${ui}`;
      const pillar = findPillarForKey(issue.key);
      const target = pillar || rootId;
      const uncatHex = pillar
        ? pillarIdToHex[pillar] || "#e879f9"
        : "#e879f9";

      nodes.push({
        id: uId,
        label: issue.key.replace(/^AAP-/, ""),
        fullKey: issue.key,
        summary: issue.summary,
        sublabel: `${issue.points}pts \u00D7${storyScopeMult}`,
        type: issue.type || "task",
        points: issue.points,
        size: Math.min(Math.max(issue.points / 10, 6), 12),
        color: pillar ? pillarTint(uncatHex, "issue") : "#e879f9",
        eventCount: issue.event_count || 0,
        pillars: pillar ? [pillar] : allPillarIds.slice(),
        weightInfo: `${issue.points}pts | scope: \u00D7${storyScopeMult}`,
      });
      links.push({ source: target, target: uId, type: "hierarchy" });
    });

    for (const n of nodes) {
      if (
        n.pillars &&
        n.pillars.length > 0 &&
        n.pillars.length < allPillarIds.length
      ) {
        const primaryHex = pillarIdToHex[n.pillars[0]] || "#888";
        if (n.type === "task" || n.type === "bug" || n.type === "story")
          n.color = pillarTint(primaryHex, "issue");
      }
    }
  }

  const alignment = state.strategy_alignment;
  if (alignment?.priorities) {
    const strategyScopeMult = scopeMult.strategy ?? 10;
    for (const [pi, priority] of alignment.priorities.entries()) {
      stratCount++;
      const stratId = `wm_strat_${pi}`;
      const isCovered = priority.status === "covered";
      const pillarName = priority.pillar || "End-to-End Delivery";
      const pillarId = `wm_pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;
      const stratPillars = new Set<string>([pillarId]);
      const priorityKeys = new Set(priority.issue_keys || []);

      let totalEvidencePts = 0;
      for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
        let shared = 0;
        let sharedPts = 0;
        for (const k of compKeys) {
          if (priorityKeys.has(k)) {
            shared++;
            sharedPts += compEvidencePoints[compId]?.[k] || 0;
          }
        }
        if (shared > 0) {
          evidenceLinkCount++;
          totalEvidencePts += sharedPts;
          links.push({
            source: `wm_comp_${compId}`,
            target: stratId,
            type: "evidence",
            weight: shared,
            points: sharedPts,
            label: `${sharedPts}pts`,
          });
          const compCat = meta[compId]?.category || "Technical Contribution";
          stratPillars.add(`wm_pillar_${compCat.replace(/[^a-z]/gi, "_")}`);
        }
      }

      const stratPillarHex = PILLAR_DEFS[pillarName]?.color || "#888";
      const stratTint = pillarTint(
        stratPillarHex,
        "strategy",
        undefined,
        isCovered,
      );
      nodes.push({
        id: stratId,
        label:
          priority.name.length > 30
            ? priority.name.substring(0, 27) + "..."
            : priority.name,
        fullLabel: priority.name,
        sublabel: isCovered ? `${totalEvidencePts}pts \u2713` : "gap",
        type: "strategy",
        status: priority.status,
        size: 14,
        color: stratTint,
        heatColor: stratTint,
        isCovered,
        pillarId,
        pillars: Array.from(stratPillars),
        weightInfo: `${isCovered ? "Covered" : "Gap"} | ${totalEvidencePts}pts | scope: \u00D7${strategyScopeMult}`,
      });
      links.push({
        source: pillarId,
        target: stratId,
        type: "pillar_strategy",
        label: `\u00D7${strategyScopeMult}`,
      });
    }
  }

  let ownerCount = 0;
  const wmSenderSummaries =
    alignment?.sender_relationships?.sender_summaries || {};
  const wmSenderRels = alignment?.sender_relationships?.relationships || [];
  const wmOwnerColor = "#e0e0e0";
  const wmAnstratNodeMap = new Map(
    nodes.filter((n) => n.type === "anstrat").map((n) => [n.fullKey, n.id]),
  );

  const wmEmailToDisplay = new Map<string, string>();
  const wmDisplayToEmail = new Map<string, string>();
  for (const [email] of Object.entries(wmSenderSummaries)) {
    const dn = email
      .split("@")[0]
      .replace(/[._-]/g, " ")
      .replace(/\b\w/g, (c: string) => c.toUpperCase());
    wmEmailToDisplay.set(email, dn);
    wmDisplayToEmail.set(dn, email);
  }

  const wmEmailToAnstratViaStrategy = new Map<string, Set<string>>();
  if (alignment?.priorities) {
    for (const priority of alignment.priorities) {
      const senderNames: string[] =
        priority.sender_names || priority.owner_names || [];
      const prioIssueKeys = priority.issue_keys || [];
      const prioAnstratNodeIds: string[] = [];
      for (const k of prioIssueKeys) {
        const nid = wmAnstratNodeMap.get(k);
        if (nid) prioAnstratNodeIds.push(nid);
      }
      if (prioAnstratNodeIds.length === 0) continue;
      for (const sn of senderNames) {
        const email = wmDisplayToEmail.get(sn) || sn;
        if (!wmEmailToAnstratViaStrategy.has(email))
          wmEmailToAnstratViaStrategy.set(email, new Set());
        for (const nid of prioAnstratNodeIds)
          wmEmailToAnstratViaStrategy.get(email)!.add(nid);
      }
    }
  }

  for (const [email, summary] of Object.entries(wmSenderSummaries)) {
    const senderAnstrats = wmSenderRels
      .filter((r) => r.sender === email)
      .map((r) => r.anstrat_key);
    const linkedAnstratIds: string[] = [];
    for (const key of senderAnstrats) {
      const nodeId = wmAnstratNodeMap.get(key);
      if (nodeId && !linkedAnstratIds.includes(nodeId))
        linkedAnstratIds.push(nodeId);
    }
    const strategyLinked = wmEmailToAnstratViaStrategy.get(email);
    if (strategyLinked) {
      for (const nid of strategyLinked) {
        if (!linkedAnstratIds.includes(nid)) linkedAnstratIds.push(nid);
      }
    }

    ownerCount++;
    const ownerId = `wm_owner_${email.replace(/[^a-z0-9]/gi, "_")}`;
    const displayName =
      wmEmailToDisplay.get(email) ||
      email
        .split("@")[0]
        .replace(/[._-]/g, " ")
        .replace(/\b\w/g, (c: string) => c.toUpperCase());

    const ownerPillars = new Set<string>();
    for (const anId of linkedAnstratIds) {
      const anNode = nodes.find((n) => n.id === anId);
      if (anNode?.pillars) {
        for (const p of anNode.pillars) ownerPillars.add(p);
      }
    }

    nodes.push({
      id: ownerId,
      label: displayName,
      email,
      type: "owner",
      size: 18,
      color: wmOwnerColor,
      issueCount:
        (summary as SenderSummary).anstrat_count || senderAnstrats.length,
      linkedCount: linkedAnstratIds.length,
      themes: ((summary as SenderSummary).top_themes || []).slice(0, 5),
      pillars:
        ownerPillars.size > 0
          ? Array.from(ownerPillars)
          : Object.keys(pillarDefs).map((n) =>
              `wm_pillar_${n.replace(/[^a-z]/gi, "_")}`,
            ),
    });

    if (linkedAnstratIds.length > 0) {
      for (const anId of linkedAnstratIds) {
        links.push({
          source: ownerId,
          target: anId,
          type: "owner_anstrat",
          weight: 1,
        });
      }
    } else {
      links.push({
        source: ownerId,
        target: rootId,
        type: "owner_anstrat",
        weight: 1,
      });
    }
  }

  const pillarInfo = Object.entries(pillarDefs).map(([name, def]) => ({
    id: `wm_pillar_${name.replace(/[^a-z]/gi, "_")}`,
    label: def.label,
    color: def.color,
  }));

  return {
    nodes,
    links,
    pillarInfo,
    stats: {
      pillars: Object.keys(pillarDefs).length,
      competencies: compCount,
      anstrats: anstratCount,
      owners: ownerCount,
      epics: epicCount,
      issues: issueCount,
      strategies: stratCount,
      evidenceLinks: evidenceLinkCount,
    },
  };
}

function renderWeightedMindmapView(
  state: PerformanceState,
  helpers: CompetenciesHelpers,
): string {
  const graphData = buildWeightedCompetencyGraph(state, helpers);

  if (!graphData) {
    return helpers.getEmptyStateHtml(
      "--",
      "Weighted mindmap will appear after data collection.",
    );
  }

  const graphJson = JSON.stringify(graphData);
  const s = graphData.stats;

  const parts: string[] = [];
  if (s.pillars) parts.push(`${s.pillars} pillars`);
  if (s.competencies) parts.push(`${s.competencies} competencies`);
  if (s.anstrats) parts.push(`${s.anstrats} ANSTRATs`);
  if (s.owners) parts.push(`${s.owners} owners`);
  if (s.epics) parts.push(`${s.epics} epics`);
  if (s.issues) parts.push(`${s.issues} issues`);
  if (s.strategies) parts.push(`${s.strategies} strategies`);
  if (s.evidenceLinks) parts.push(`${s.evidenceLinks} cross-links`);
  const statsHtml = parts.join(" &middot; ");

  const pillarCheckboxes = graphData.pillarInfo
    .map(
      (p: any) =>
        `<label class="perf-mindmap-toggle perf-pillar-filter" style="color:${p.color}">` +
        `<input type="checkbox" class="wmPillarChk" data-pillar="${helpers.escapeHtml(p.id)}" checked /> ${helpers.escapeHtml(p.label)}</label>`,
    )
    .join("");

  return `
    <div class="section">
      <div class="section-title">Weighted Competency Mindmap</div>
      <div class="perf-wm-d3-wrapper">
        <div class="perf-mindmap-d3-header">
          <div class="perf-mindmap-d3-filters">
            ${pillarCheckboxes}
            <span class="perf-mindmap-d3-sep">|</span>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="competency" checked /> Competencies</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="anstrat" checked /> ANSTRATs</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="epic" checked /> Epics</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="task,bug,story" checked /> Issues</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="strategy" checked /> Strategies</label>
            <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="wmTypeChk" data-types="owner" checked /> Owners</label>
          </div>
          <span class="perf-mindmap-d3-stats" id="wmStats">${statsHtml}</span>
          <div class="perf-mindmap-d3-controls">
            <label class="perf-mindmap-toggle"><input type="checkbox" id="wmLabels" checked /> Labels</label>
            <label class="perf-mindmap-toggle"><input type="checkbox" id="wmWeights" checked /> Weights</label>
            <label class="perf-mindmap-toggle"><input type="checkbox" id="wmSticky" /> Sticky</label>
            <button class="btn btn-xs" id="wmReheat" title="Reheat simulation">Reheat</button>
            <button class="btn btn-xs" id="wmFit" title="Fit to view">Fit</button>
          </div>
        </div>
        <div class="perf-mindmap-d3-graph" id="wmGraph">
          <svg id="wmSvg" class="svg-full">
            <defs>
              <filter id="wmGlow" x="-50%" y="-50%" width="200%" height="200%">
                <feGaussianBlur stdDeviation="2.5" result="blur"/>
                <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
              </filter>
            </defs>
          </svg>
        </div>
        <div class="perf-mindmap-d3-tooltip" id="wmTooltip"></div>
        <div class="perf-mindmap-d3-legend">
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-root"></span>Root</span>
          ${Object.entries(PILLAR_DEFS)
            .map(
              ([name, def]) =>
                `<span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot" style="background:${def.color}"></span>${name}</span>`,
            )
            .join("\n            ")}
          <span class="legend-separator">|</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-ring legend-dot-default"></span>Pillar</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-small"></span>Competency</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-roundrect legend-dot-default"></span>ANSTRAT</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-triangle legend-dot-default"></span>Epic</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-square legend-dot-default"></span>Issue</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-diamond-legend legend-dot-default"></span>Strategy</span>
          <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-hexagon perf-mm-legend-owner"></span>Owner</span>
          <span class="legend-separator">|</span>
          <span class="flex-row gap-4 legend-item-compact wm-legend-evidence"><span class="dot legend-dot perf-mm-legend-evidence-link"></span>Evidence Link</span>
        </div>
      </div>
      <script id="wmGraphData" type="application/json">${graphJson}</script>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function getCompetenciesContent(
  state: PerformanceState,
  helpers: CompetenciesHelpers,
): string {
  const view = state.competency_view || "sunburst";
  const toggleHtml = `
    <div class="perf-chart-view-toggle">
      <button class="perf-chart-view-btn${view === "sunburst" ? " active" : ""}"
              data-action="switchCompView" data-view="sunburst">Sunburst</button>
      <button class="perf-chart-view-btn${view === "mindmap" ? " active" : ""}"
              data-action="switchCompView" data-view="mindmap">Mindmap</button>
    </div>`;

  const chartHtml =
    view === "sunburst"
      ? `
    <div class="section">
      <div class="section-title">Competency Sunburst</div>
      <div class="perf-sunburst-container text-center">
        ${generateSunburstSVG(state, helpers)}
      </div>
      <div class="perf-sunburst-ring-legend">
        <div class="perf-sunburst-ring-item"><span class="ring-num">1</span> <b>Pillar</b> &mdash; ${Object.keys(PILLAR_DEFS).length} competency pillars (color = pillar, opacity = score)</div>
        <div class="perf-sunburst-ring-item"><span class="ring-num">2</span> <b>Competency</b> &mdash; ${Object.keys(state.competencies).length} individual competencies (color = red/yellow/green by %)</div>
      </div>
    </div>
  `
      : renderWeightedMindmapView(state, helpers);

  const overlayHelpers: OverviewHelpers = {
    getEffectivePercentage: helpers.getEffectivePercentage,
    getEffectiveOverall: helpers.getEffectiveOverall,
    formatCompetencyName: helpers.formatCompetencyName,
    escapeHtml: helpers.escapeHtml,
    getEmptyStateHtml: helpers.getEmptyStateHtml,
    renderIssueLink: helpers.renderIssueLink,
    renderIssueLinks: helpers.renderIssueLinks,
    safeText: helpers.safeText,
  };

  return `
    <div class="perf-tab-panel">
      ${toggleHtml}
      ${chartHtml}

      <!-- Expandable Competency Bars -->
      <div class="section">
        <div class="section-title">Competency Scores (click to expand)</div>
        ${renderExpandableCompetencyBars(state, overlayHelpers)}
      </div>

      <!-- Gap Suggestions -->
      ${renderGapsWithSuggestions(state, overlayHelpers)}
    </div>
  `;
}
