/**
 * Performance Mindmap Tab Renderer
 *
 * Extracted from PerformanceTab.ts. Exports getMindmapContent for the
 * Issue Mindmap tab (Root -> Pillars -> Competencies -> ANSTRATs -> Epics -> Issues).
 */

import type { PerformanceState, SenderSummary } from "./performanceTypes";
import {
  MINDMAP_PHYSICS_DEFAULTS,
  MINDMAP_SLIDER_RANGES,
  PILLAR_DEFS,
  getColorForPercentage,
  pillarTint,
} from "./performanceConfig";

export interface MindmapHelpers {
  getEffectivePercentage(compId: string): number;
  getEffectiveOverall(): number;
  formatCompetencyName(id: string): string;
  escapeHtml(s: string): string;
  getEmptyStateHtml(icon: string, msg: string): string;
}

// ---------------------------------------------------------------------------
// Graph building
// ---------------------------------------------------------------------------

function buildCombinedMindmapGraph(
  state: PerformanceState,
  helpers: MindmapHelpers,
): {
  nodes: any[];
  links: any[];
  view: string;
  pillarInfo: any[];
  stats: any;
} | null {
  const meta = state.competency_meta || {};
  const comps = state.competencies || {};
  const h = state.issue_hierarchy;
  const hasCompetencies = Object.keys(meta).length > 0;
  const hasIssues = h && h.total_issues > 0;

  if (!hasCompetencies && !hasIssues) return null;

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
    `pillar_${n.replace(/[^a-z]/gi, "_")}`,
  );

  // ---- Root ----
  const rootId = "root";
  const overallPct = helpers.getEffectiveOverall() || 0;
  nodes.push({
    id: rootId,
    label: state.quarter,
    sublabel: `${overallPct}% overall`,
    type: "root",
    percentage: overallPct,
    size: 30,
    color: "#667eea",
    pillars: allPillarIds,
  });

  let compCount = 0;
  let anstratCount = 0;
  let epicCount = 0;
  let issueCount = 0;
  let stratCount = 0;
  let evidenceLinkCount = 0;

  // Build per-competency issue key sets for linking
  const compEvidenceKeys: Record<string, Set<string>> = {};
  for (const [compId, events] of Object.entries(
    state.competency_evidence || {},
  )) {
    const keys = new Set<string>();
    for (const ev of events) {
      for (const k of ev.issue_keys || []) keys.add(k);
    }
    compEvidenceKeys[compId] = keys;
  }

  const anstratIssueKeys: Record<string, Set<string>> = {};

  // ---- Pillars + Competencies ----
  for (const [pillarName, pDef] of Object.entries(pillarDefs)) {
    const pillarId = `pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;
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

    const pillarSummary =
      state.strategy_alignment?.pillar_summary?.[pillarName];

    nodes.push({
      id: pillarId,
      label: pDef.label,
      type: "pillar",
      percentage: avgPct,
      size: 22,
      color: pDef.color,
      heatColor: getColorForPercentage(avgPct),
      angle: pDef.angle,
      compCount: pillarComps.length,
      priorityCount: pillarSummary?.priority_count || 0,
      covered: pillarSummary?.covered || 0,
      gaps: pillarSummary?.gaps || 0,
      pillars: [pillarId],
    });
    links.push({ source: rootId, target: pillarId, type: "hierarchy" });

    for (const compId of pillarComps) {
      compCount++;
      const m = meta[compId];
      const c = comps[compId];
      const pct = c?.percentage || m?.percentage || 0;
      const evidenceCount = m?.evidence_count || 0;

      const nodeId = `comp_${compId}`;
      const compTint = pillarTint(pDef.color, "competency", pct);
      nodes.push({
        id: nodeId,
        compId,
        label: m.name,
        type: "competency",
        category: m.category,
        goal: m.goal,
        description: m.description,
        percentage: pct,
        points: c?.points || m?.points || 0,
        target: m.target || 100,
        evidenceCount,
        size: Math.min(Math.max(evidenceCount * 1.5 + 8, 8), 20),
        color: compTint,
        heatColor: compTint,
        pillarColor: pDef.color,
        pillarId,
        pillarAngle: pDef.angle,
        pillars: [pillarId],
      });
      links.push({ source: pillarId, target: nodeId, type: "hierarchy" });
    }
  }

  // ---- ANSTRAT / Epic / Issue hierarchy ----
  if (hasIssues && h) {
    const issueStrategies = Array.isArray(h.strategies) ? h.strategies : [];
    const unattachedEpics = Array.isArray(h.unattached_epics)
      ? h.unattached_epics
      : [];
    const uncatIssues = Array.isArray(h.uncategorized) ? h.uncategorized : [];

    const fallbackAnstratColor = "#06b6d4";
    const fallbackEpicColor = "#f97316";
    const fallbackIssueColor = "#e879f9";

    const pillarIdToHex: Record<string, string> = {};
    for (const [pn, pd] of Object.entries(pillarDefs)) {
      pillarIdToHex[`pillar_${pn.replace(/[^a-z]/gi, "_")}`] = pd.color;
    }

    const anstratNodeIds: string[] = [];
    issueStrategies.forEach((group, gi) => {
      anstratCount++;
      const gId = `anstrat_${gi}`;
      anstratNodeIds.push(gId);
      const allKeys = new Set<string>();

      nodes.push({
        id: gId,
        label: group.key.replace(/^ANSTRAT-/, "AN-"),
        fullKey: group.key,
        summary: group.summary,
        type: "anstrat",
        points: group.points,
        size: Math.min(Math.max(group.points / 8, 16), 24),
        color: fallbackAnstratColor,
        eventCount: group.event_count || 0,
        pillars: [] as string[],
      });

      (group.children || []).forEach((child, ci) => {
        epicCount++;
        const cId = `${gId}_epic_${ci}`;
        nodes.push({
          id: cId,
          label: child.key.replace(/^AAP-/, ""),
          fullKey: child.key,
          summary: child.summary,
          type: "epic",
          points: child.points,
          size: Math.min(Math.max(child.points / 8, 10), 18),
          color: fallbackEpicColor,
          eventCount: child.event_count || 0,
          parentAnstrat: gId,
          pillars: [] as string[],
        });
        links.push({ source: gId, target: cId, type: "parent" });
        allKeys.add(child.key);

        (child.children || []).forEach((issue, ii) => {
          issueCount++;
          const iId = `${cId}_issue_${ii}`;
          nodes.push({
            id: iId,
            label: issue.key.replace(/^AAP-/, ""),
            fullKey: issue.key,
            summary: issue.summary,
            type: issue.type || "task",
            points: issue.points,
            size: Math.min(Math.max(issue.points / 10, 6), 12),
            color: fallbackIssueColor,
            eventCount: issue.event_count || 0,
            parentAnstrat: gId,
            pillars: [] as string[],
          });
          links.push({ source: cId, target: iId, type: "parent" });
          allKeys.add(issue.key);
        });
      });

      anstratIssueKeys[gId] = allKeys;
    });

    const findPillarForKey = (key: string): string | null => {
      for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
        if (compKeys.has(key)) {
          const cat = meta[compId]?.category || "Technical Contribution";
          return `pillar_${cat.replace(/[^a-z]/gi, "_")}`;
        }
      }
      return null;
    };

    unattachedEpics.forEach((epic, ei) => {
      epicCount++;
      const eId = `unattached_epic_${ei}`;
      const pillar = findPillarForKey(epic.key);
      const targetPillar = pillar || rootId;

      nodes.push({
        id: eId,
        label: epic.key.replace(/^AAP-/, ""),
        fullKey: epic.key,
        summary: epic.summary,
        type: "epic",
        points: epic.points,
        size: Math.min(Math.max(epic.points / 8, 10), 18),
        color: fallbackEpicColor,
        eventCount: epic.event_count || 0,
        pillars: pillar ? [pillar] : allPillarIds.slice(),
      });
      links.push({ source: targetPillar, target: eId, type: "hierarchy" });

      (epic.children || []).forEach((issue, ii) => {
        issueCount++;
        const iId = `${eId}_issue_${ii}`;
        const issuePillar = findPillarForKey(issue.key) || pillar;
        const issuePillarHex = issuePillar
          ? pillarIdToHex[issuePillar] || fallbackIssueColor
          : fallbackIssueColor;
        nodes.push({
          id: iId,
          label: issue.key.replace(/^AAP-/, ""),
          fullKey: issue.key,
          summary: issue.summary,
          type: issue.type || "task",
          points: issue.points,
          size: Math.min(Math.max(issue.points / 10, 6), 12),
          color: issuePillar
            ? pillarTint(issuePillarHex, "issue")
            : fallbackIssueColor,
          eventCount: issue.event_count || 0,
          pillars: issuePillar ? [issuePillar] : allPillarIds.slice(),
        });
        links.push({ source: eId, target: iId, type: "parent" });
      });
    });

    uncatIssues.forEach((issue, ui) => {
      issueCount++;
      const uId = `uncat_issue_${ui}`;
      const pillar = findPillarForKey(issue.key);
      const targetPillar = pillar || rootId;
      const uncatPillarHex = pillar
        ? pillarIdToHex[pillar] || fallbackIssueColor
        : fallbackIssueColor;

      nodes.push({
        id: uId,
        label: issue.key.replace(/^AAP-/, ""),
        fullKey: issue.key,
        summary: issue.summary,
        type: issue.type || "task",
        points: issue.points,
        size: Math.min(Math.max(issue.points / 10, 6), 12),
        color: pillar
          ? pillarTint(uncatPillarHex, "issue")
          : fallbackIssueColor,
        eventCount: issue.event_count || 0,
        pillars: pillar ? [pillar] : allPillarIds.slice(),
      });
      links.push({ source: targetPillar, target: uId, type: "hierarchy" });
    });

    const nodeMap = new Map(nodes.map((n) => [n.id, n]));
    for (const [gId, issueKeys] of Object.entries(anstratIssueKeys)) {
      const linkedCompIds: string[] = [];

      for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
        let shared = 0;
        for (const k of compKeys) {
          if (issueKeys.has(k)) shared++;
        }
        if (shared > 0) {
          linkedCompIds.push(compId);
          links.push({
            source: `comp_${compId}`,
            target: gId,
            type: "comp_anstrat",
            weight: shared,
          });
        }
      }

      const anstratNode = nodeMap.get(gId);
      if (linkedCompIds.length > 0 && anstratNode) {
        const assocPillars = new Set<string>();
        for (const cid of linkedCompIds) {
          const cat = meta[cid]?.category || "Technical Contribution";
          assocPillars.add(`pillar_${cat.replace(/[^a-z]/gi, "_")}`);
        }
        anstratNode.pillars = Array.from(assocPillars);
      } else {
        if (anstratNode) anstratNode.pillars = allPillarIds.slice();
        links.push({ source: rootId, target: gId, type: "parent" });
      }

      const anstratPillars = anstratNode?.pillars || allPillarIds;
      for (const n of nodes) {
        if (n.parentAnstrat === gId) {
          n.pillars = anstratPillars;
        }
      }
    }

    for (const n of nodes) {
      if (
        n.pillars &&
        n.pillars.length > 0 &&
        n.pillars.length < allPillarIds.length
      ) {
        const primaryPillarHex = pillarIdToHex[n.pillars[0]] || "#888";
        if (n.type === "task" || n.type === "bug" || n.type === "story")
          n.color = pillarTint(primaryPillarHex, "issue");
      }
    }
  }

  // ---- Executive Strategy diamonds ----
  const alignment = state.strategy_alignment;
  if (alignment?.priorities) {
    for (const [pi, priority] of alignment.priorities.entries()) {
      stratCount++;
      const stratId = `execstrat_${pi}`;
      const isCovered = priority.status === "covered";
      const pillarName = priority.pillar || "End-to-End Delivery";
      const pillarId = `pillar_${pillarName.replace(/[^a-z]/gi, "_")}`;

      const stratPillars = new Set<string>([pillarId]);
      const priorityKeys = new Set(priority.issue_keys || []);

      for (const [compId, compKeys] of Object.entries(compEvidenceKeys)) {
        let shared = 0;
        for (const k of compKeys) {
          if (priorityKeys.has(k)) shared++;
        }
        if (shared > 0) {
          evidenceLinkCount++;
          links.push({
            source: `comp_${compId}`,
            target: stratId,
            type: "evidence",
            weight: shared,
          });
          const compCat = meta[compId]?.category || "Technical Contribution";
          stratPillars.add(`pillar_${compCat.replace(/[^a-z]/gi, "_")}`);
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
        type: "strategy",
        status: priority.status,
        context: priority.context,
        pillar: pillarName,
        size: 12,
        color: stratTint,
        heatColor: stratTint,
        isCovered,
        issueKeys: priority.issue_keys || [],
        matchedIssues: priority.matched_user_issues || [],
        matchedMrs: priority.matched_mrs || [],
        pillarId,
        pillars: Array.from(stratPillars),
      });

      links.push({ source: pillarId, target: stratId, type: "pillar_strategy" });
    }

    for (const [pi2, priority2] of alignment.priorities.entries()) {
      const stratId2 = `execstrat_${pi2}`;
      const stratKeys = new Set(priority2.issue_keys || []);
      if (stratKeys.size === 0) continue;

      for (const [gId, issueKeys] of Object.entries(anstratIssueKeys)) {
        let shared = 0;
        for (const k of issueKeys) {
          if (stratKeys.has(k)) shared++;
        }
        if (shared > 0) {
          links.push({
            source: gId,
            target: stratId2,
            type: "anstrat_strategy",
            weight: shared,
          });
        }
      }
    }
  }

  // ---- Sender nodes ----
  let ownerCount = 0;
  const senderSummariesGraph =
    alignment?.sender_relationships?.sender_summaries || {};
  const senderRelationships =
    alignment?.sender_relationships?.relationships || [];
  const ownerColor = "#e0e0e0";
  const anstratNodeMap = new Map(
    nodes.filter((n) => n.type === "anstrat").map((n) => [n.fullKey, n.id]),
  );

  const emailToDisplay = new Map<string, string>();
  const displayToEmail = new Map<string, string>();
  for (const [email] of Object.entries(senderSummariesGraph)) {
    const dn = email
      .split("@")[0]
      .replace(/[._-]/g, " ")
      .replace(/\b\w/g, (c: string) => c.toUpperCase());
    emailToDisplay.set(email, dn);
    displayToEmail.set(dn, email);
  }

  const emailToAnstratViaStrategy = new Map<string, Set<string>>();
  if (alignment?.priorities) {
    for (const priority of alignment.priorities) {
      const senderNames: string[] =
        priority.sender_names || priority.owner_names || [];
      const prioIssueKeys = priority.issue_keys || [];
      const prioAnstratNodeIds: string[] = [];
      for (const k of prioIssueKeys) {
        const nid = anstratNodeMap.get(k);
        if (nid) prioAnstratNodeIds.push(nid);
      }
      if (prioAnstratNodeIds.length === 0) continue;
      for (const sn of senderNames) {
        const email = displayToEmail.get(sn) || sn;
        if (!emailToAnstratViaStrategy.has(email))
          emailToAnstratViaStrategy.set(email, new Set());
        for (const nid of prioAnstratNodeIds)
          emailToAnstratViaStrategy.get(email)!.add(nid);
      }
    }
  }

  for (const [email, summary] of Object.entries(senderSummariesGraph)) {
    const senderAnstrats = senderRelationships
      .filter((r) => r.sender === email)
      .map((r) => r.anstrat_key);
    const linkedAnstratIds: string[] = [];
    for (const key of senderAnstrats) {
      const nodeId = anstratNodeMap.get(key);
      if (nodeId && !linkedAnstratIds.includes(nodeId))
        linkedAnstratIds.push(nodeId);
    }
    const strategyLinked = emailToAnstratViaStrategy.get(email);
    if (strategyLinked) {
      for (const nid of strategyLinked) {
        if (!linkedAnstratIds.includes(nid)) linkedAnstratIds.push(nid);
      }
    }

    ownerCount++;
    const ownerId = `owner_${email.replace(/[^a-z0-9]/gi, "_")}`;
    const displayName =
      emailToDisplay.get(email) ||
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
      color: ownerColor,
      issueCount:
        (summary as SenderSummary).anstrat_count || senderAnstrats.length,
      linkedCount: linkedAnstratIds.length,
      themes: ((summary as SenderSummary).top_themes || []).slice(0, 5),
      pillars:
        ownerPillars.size > 0
          ? Array.from(ownerPillars)
          : allPillarIds.slice(),
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
    id: `pillar_${name.replace(/[^a-z]/gi, "_")}`,
    label: def.label,
    color: def.color,
  }));

  return {
    nodes,
    links,
    view: "combined",
    pillarInfo,
    stats: {
      pillars: Object.keys(pillarDefs).length,
      competencies: compCount,
      anstrats: anstratCount,
      epics: epicCount,
      issues: issueCount,
      strategies: stratCount,
      owners: ownerCount,
      evidenceLinks: evidenceLinkCount,
    },
  };
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function getMindmapContent(
  state: PerformanceState,
  helpers: MindmapHelpers,
): string {
  const graphData = buildCombinedMindmapGraph(state, helpers);

  if (!graphData) {
    return `
      <div class="perf-tab-panel">
        <div class="section">
          <div class="section-title">Issue Mindmap</div>
          <div class="perf-mindmap-container">
            ${helpers.getEmptyStateHtml("--", "Mindmap will appear after data collection.")}
          </div>
        </div>
      </div>
    `;
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
  const statsHtml = parts.join(" &middot; ");

  const pillarCheckboxes = graphData.pillarInfo
    .map(
      (p: any) =>
        `<label class="perf-mindmap-toggle perf-pillar-filter" style="color:${p.color}">` +
        `<input type="checkbox" class="perfMmPillarChk" data-pillar="${helpers.escapeHtml(p.id)}" checked /> ${helpers.escapeHtml(p.label)}</label>`,
    )
    .join("");

  return `
    <div class="perf-tab-panel">
      <div class="section">
        <div class="section-title">Issue Mindmap</div>
        <div class="perf-mindmap-container">
          <div class="perf-mindmap-d3-wrapper">
            <div class="perf-mindmap-d3-header">
              <div class="perf-mindmap-d3-filters">
                ${pillarCheckboxes}
                <span class="perf-mindmap-d3-sep">|</span>
                <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="competency" checked /> Competencies</label>
                <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="anstrat" checked /> ANSTRATs</label>
                <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="epic" checked /> Epics</label>
                <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="task,bug,story" checked /> Issues</label>
                <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="strategy" checked /> Strategies</label>
                <label class="text-meta perf-mindmap-toggle perf-type-filter"><input type="checkbox" class="perfMmTypeChk" data-types="owner" checked /> Owners</label>
              </div>
              <span class="perf-mindmap-d3-stats" id="perfMindmapStats">${statsHtml}</span>
              <div class="perf-mindmap-d3-controls">
                <label class="perf-mindmap-toggle"><input type="checkbox" id="perfMmLabels" /> Labels</label>
                <label class="perf-mindmap-toggle"><input type="checkbox" id="perfMmSticky" /> Sticky</label>
                <button class="btn btn-xs" id="perfMmReheat" title="Reheat simulation">Reheat</button>
                <button class="btn btn-xs" id="perfMmFit" title="Fit to view">Fit</button>
                <button class="btn btn-xs mindmap-physics-toggle" id="perfMmPhysicsToggle" title="Physics Controls" data-action="togglePerfPhysics">&#x2699;&#xFE0F;</button>
              </div>
            </div>
            <div class="mindmap-physics-panel hidden" id="perfMmPhysicsPanel">
              <div class="physics-row">
                <div class="physics-control">
                  <label for="perfMmChargeSlider">Repulsion <span class="physics-value" id="perfMmChargeValue">-200</span></label>
                  <input type="range" id="perfMmChargeSlider" min="-800" max="0" step="10" value="-200" />
                </div>
                <div class="physics-control">
                  <label for="perfMmLinkDistSlider">Link Distance <span class="physics-value" id="perfMmLinkDistValue">120</span></label>
                  <input type="range" id="perfMmLinkDistSlider" min="20" max="400" step="5" value="120" />
                </div>
                <div class="physics-control">
                  <label for="perfMmCollisionSlider">Padding <span class="physics-value" id="perfMmCollisionValue">4</span></label>
                  <input type="range" id="perfMmCollisionSlider" min="0" max="30" step="1" value="4" />
                </div>
              </div>
              <div class="physics-row">
                <div class="physics-control">
                  <label for="perfMmRadialSlider">Radial Spread <span class="physics-value" id="perfMmRadialValue">1.0</span></label>
                  <input type="range" id="perfMmRadialSlider" min="20" max="300" step="5" value="100" />
                </div>
                <div class="physics-control">
                  <label for="perfMmDecaySlider">Cooling <span class="physics-value" id="perfMmDecayValue">0.012</span></label>
                  <input type="range" id="perfMmDecaySlider" min="1" max="100" step="1" value="12" />
                </div>
                <div class="physics-control">
                  <label for="perfMmVelocitySlider">Friction <span class="physics-value" id="perfMmVelocityValue">0.35</span></label>
                  <input type="range" id="perfMmVelocitySlider" min="0" max="100" step="1" value="35" />
                </div>
              </div>
              <div class="physics-row physics-actions">
                <button class="btn btn-xs" id="perfMmPhysicsReset" title="Reset to defaults">Reset</button>
                <button class="btn btn-xs" id="perfMmPhysicsPause" title="Pause/resume simulation">Pause</button>
                <button class="btn btn-xs" id="perfMmPhysicsUnstick" title="Release all pinned nodes">Unstick All</button>
              </div>
            </div>
            <div class="perf-mindmap-d3-graph" id="perfMindmapGraph">
              <svg id="perfMindmapSvg" class="svg-full">
                <defs>
                  <filter id="perfGlow" x="-50%" y="-50%" width="200%" height="200%">
                    <feGaussianBlur stdDeviation="2.5" result="blur"/>
                    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                  </filter>
                  <filter id="perfHeatGlow" x="-100%" y="-100%" width="300%" height="300%">
                    <feGaussianBlur stdDeviation="25" result="blur"/>
                    <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
                  </filter>
                </defs>
              </svg>
            </div>
            <div class="perf-mindmap-d3-tooltip" id="perfMindmapTooltip"></div>
            <div class="perf-mindmap-d3-legend">
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-root"></span>Root</span>
              ${Object.entries(PILLAR_DEFS)
                .map(
                  ([name, def]) =>
                    `<span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot" style="background:${def.color}"></span>${name}</span>`,
                )
                .join("\n          ")}
              <span class="legend-separator">|</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-ring legend-dot-default"></span>Pillar</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot legend-dot-small"></span>Competency</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-roundrect legend-dot-default"></span>ANSTRAT</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-triangle legend-dot-default"></span>Epic</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-square legend-dot-default"></span>Issue</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-diamond-legend legend-dot-default"></span>Strategy</span>
              <span class="flex-row gap-4 legend-item-compact"><span class="dot legend-dot perf-mm-legend-hexagon perf-mm-legend-owner"></span>Owner</span>
              <span class="legend-separator">|</span>
              <span class="flex-row gap-4 legend-item-compact" title="Solid diamond = covered"><span class="dot legend-dot perf-mm-diamond-legend legend-dot-default"></span>Covered</span>
              <span class="flex-row gap-4 legend-item-compact" title="Dashed diamond = gap"><span class="dot legend-dot perf-mm-diamond-legend perf-help-dot-comparison"></span>Gap</span>
            </div>
          </div>
          <script id="perfMindmapData" type="application/json">${graphJson}</script>
        </div>
      </div>
    </div>
  `;
}
