/**
 * Performance Tab Action Handlers
 *
 * Extracted from PerformanceTab.ts to reduce god-class size.
 * All handlers receive ActionContext and operate on it.
 */

import * as vscode from "vscode";
import type { PerformanceState, DayEvent } from "./performanceTypes";
import { dbus, createLogger } from "./BaseTab";
import { createNewChat } from "../chatUtils";
import { JIRA_BROWSE_URL, DEFAULT_SCOPE_MULTIPLIERS } from "./performanceConfig";

const logger = createLogger("PerfActions");

export interface ActionContext {
  state: PerformanceState;
  notifyNeedsRender(): void;
  postMessageToWebview(msg: any): void;
  refresh(): Promise<void>;
  refreshPreservingUIState(): Promise<void>;
  debouncedSaveScoringConfig(delayMs?: number): void;
  deferredSettingsRender(): void;
  escapeHtml(s: string): string;
  safeText(s: string): string;

  // Mutable fields - must be writable refs
  forceNextRender: boolean;
  _settingsDirty: boolean;
  _settingsRefreshTimer: ReturnType<typeof setTimeout> | null;
  _expandedQuestions: Set<string>;
  _questionEvidence: Map<string, any>;
  _questionEvidenceLoading: Set<string>;
  _excludedEvidence: Map<string, Set<string>>;
  _backfillPollInterval?: ReturnType<typeof setInterval>;
  _backfillEverRanning: boolean;
}

// ============================================================
// Dispatch
// ============================================================

export async function handlePerformanceActionDispatch(
  ctx: ActionContext,
  action: string,
  message: any
): Promise<boolean> {
  logger.log(`Performance action: ${action}`);

  switch (action) {
    case "collectDaily":
      await collectDailyData(ctx);
      break;
    case "backfill":
      await backfillAll(ctx);
      break;
    case "exportReport":
      await exportReport(ctx);
      break;
    case "logActivity":
      await logActivity(ctx, message.category, message.description);
      break;
    case "evaluateAll":
      await evaluateAllQuestions(ctx);
      break;
    case "collectPeers":
      await collectPeers(ctx, false);
      break;
    case "collectPeersBackfill":
      await collectPeers(ctx, true);
      break;
    case "toggleBackfillOptions":
      ctx.postMessageToWebview({ command: "toggleBackfillOptions" });
      break;
    case "cancelBackfillOptions":
      ctx.postMessageToWebview({ command: "hideBackfillOptions" });
      break;
    case "startFilteredBackfill":
      await startFilteredBackfill(ctx, message);
      break;
    case "rescorePeers":
      await rescorePeers(ctx);
      break;
    case "cancelBackfill":
      await cancelBackfill(ctx);
      break;
    case "scrubData":
      await scrubData(ctx);
      break;
    case "loadPromotionReadiness":
      await loadPromotionReadiness(ctx);
      break;
    case "loadPeerGrowth":
      await loadPeerGrowth(ctx);
      break;
    case "evaluateQuestionLocal":
      await evaluateQuestionLocal(ctx, message.questionId);
      break;
    case "classifyLogEntry":
      await classifyLogEntry(ctx, message.description);
      break;
    case "askAI":
      await askAI(ctx, message.question);
      break;
    case "getGapCoach":
      await loadGapCoach(ctx, message.competencyId);
      break;
    case "explainScore":
      await explainScore(ctx, message.competencyId);
      break;
    case "suggestConfigTune":
      await suggestConfigTune(ctx);
      break;
    case "detectMissingLinks":
      await detectMissingLinks(ctx);
      break;
    case "clearDrafts":
      await clearAllDrafts(ctx);
      break;
    case "saveQuestion":
      await saveQuestion(ctx, message.description);
      break;
    case "removeQuestion":
      await removeQuestion(ctx, message.questionId);
      break;
    case "addNote":
      await addNoteToQuestion(ctx, message.questionId);
      break;
    case "evaluate":
      await evaluateQuestion(ctx, message.questionId);
      break;
    case "toggleEvidence":
      await toggleEvidencePanel(ctx, message.questionId);
      break;
    case "toggleEvidenceItem":
      toggleEvidenceItem(ctx, message.questionId, message.evidenceId);
      break;
    case "selectAllEvidence":
      selectAllEvidence(ctx, message.questionId);
      break;
    case "deselectAllEvidence":
      deselectAllEvidence(ctx, message.questionId);
      break;
    case "switchCompView":
      ctx.state.competency_view = message.view === "mindmap" ? "mindmap" : "sunburst";
      if (ctx.state.competency_view === "mindmap") {
        ctx.forceNextRender = true;
      }
      ctx.notifyNeedsRender();
      break;
    case "switchHeatmapMode": {
      const modes = ["percentage", "raw_points", "peer_comparable"] as const;
      const validMode = modes.find((m) => m === message.mode);
      if (validMode) {
        ctx.state.heatmap_mode = validMode;
        ctx.notifyNeedsRender();
      }
      break;
    }
    case "switchEventVolumeMode":
      ctx.state.event_volume_mode = message.mode === "all" ? "all" : "comparable";
      ctx.notifyNeedsRender();
      break;
    case "toggleSessionEnrichment":
      ctx.state.session_enrichment = !ctx.state.session_enrichment;
      ctx.notifyNeedsRender();
      break;
    case "switchPeerComparisonMode": {
      const cm = message.mode === "raw" ? "raw" : "comparable";
      ctx.state.peer_comparison_mode = cm;
      ctx.state.heatmap_mode = cm === "comparable" ? "peer_comparable" : "percentage";
      ctx.state.event_volume_mode = cm === "comparable" ? "comparable" : "all";
      ctx.notifyNeedsRender();
      break;
    }
    case "switchTab": {
      const leavingSettings = ctx.state.active_tab === "settings";
      ctx.state.active_tab = message.key || "overview";
      if (ctx.state.active_tab === "mindmap" || ctx.state.active_tab === "help") {
        ctx.forceNextRender = true;
      }
      if (leavingSettings && ctx._settingsDirty) {
        ctx._settingsDirty = false;
        if (ctx._settingsRefreshTimer) {
          clearTimeout(ctx._settingsRefreshTimer);
          ctx._settingsRefreshTimer = null;
        }
        await ctx.refresh();
      } else {
        ctx.notifyNeedsRender();
      }
      break;
    }
    case "refreshHierarchy":
      await refreshHierarchy(ctx);
      break;
    case "selectDay":
      ctx.state.selected_date = message.date || null;
      ctx.state.day_detail = null;
      ctx.notifyNeedsRender();
      if (ctx.state.selected_date) {
        loadDayDetail(ctx, ctx.state.selected_date);
      }
      break;
    case "closeDay":
      ctx.state.selected_date = null;
      ctx.state.day_detail = null;
      ctx.notifyNeedsRender();
      break;
    case "prevMonth":
      navigateMonth(ctx, -1);
      break;
    case "nextMonth":
      navigateMonth(ctx, 1);
      break;
    case "toggleCompetency":
      ctx.state.expanded_competency =
        ctx.state.expanded_competency === message.key ? null : message.key;
      ctx.notifyNeedsRender();
      break;
    case "openIssue":
      if (message.key) {
        const issueKey = message.key as string;
        vscode.env.openExternal(vscode.Uri.parse(`${JIRA_BROWSE_URL}${issueKey}`));
      }
      break;
    case "toggleScoringSettings":
      ctx.state.scoring_config_expanded = !ctx.state.scoring_config_expanded;
      ctx.notifyNeedsRender();
      break;
    case "toggleScoringComp":
      ctx.state.scoring_comp_expanded =
        ctx.state.scoring_comp_expanded === message.key ? null : message.key;
      ctx.notifyNeedsRender();
      break;
    case "resetScoringConfig":
      await resetScoringConfig(ctx);
      break;
    case "toggleEventType":
      toggleScoringEventType(ctx, message.comp, message.value);
      break;
    case "removePhrase":
      removeScoringTag(ctx, "phrases", message.comp, message.value);
      break;
    case "removeKeyword":
      removeScoringTag(ctx, "keywords", message.comp, message.value);
      break;
    case "addPhrase":
      addScoringTag(ctx, "phrases", message.comp, message.value);
      break;
    case "addKeyword":
      addScoringTag(ctx, "keywords", message.comp, message.value);
      break;
    case "updateScoringGlobal":
      updateScoringGlobal(ctx, message.field, message.value);
      break;
    case "updateCompBasePoints":
      updateCompBasePoints(ctx, message.comp, message.value);
      break;
    case "setEngineeringLevel":
      setEngineeringLevel(ctx, message.value);
      break;
    case "setScopeMultiplier":
      setScopeMultiplier(ctx, message.scope, message.value);
      break;
    case "setRoleWeight":
      setRoleWeight(ctx, message.scope, message.role, message.value);
      break;
    case "setPillarWeight":
      setPillarWeight(ctx, message.pillar, message.value);
      break;
    case "setStrategyEnabled":
      setStrategyField(ctx, "enabled", message.value);
      break;
    case "setStrategyBonus":
      setStrategyField(ctx, "bonus_multiplier", parseFloat(message.value));
      break;
    case "setStrategyEnrich":
      setStrategyField(ctx, "enrich_classification", message.value);
      break;
    case "setStrategyMinOverlap":
      setStrategyField(ctx, "min_text_overlap_words", parseInt(message.value, 10));
      break;
    case "setNpuEnabled":
      setNpuField(ctx, "enabled", message.value);
      break;
    case "setNpuDevice":
      setNpuField(ctx, "device", message.value);
      break;
    case "setNpuThreshold":
      setNpuField(ctx, "confidence_threshold", parseFloat(message.value));
      break;
    case "setNpuBonusSignals":
      setNpuField(ctx, "bonus_signals", parseInt(message.value, 10));
      break;
    case "addExecutiveSender":
      await addExecutiveSender(ctx, message.value);
      break;
    case "removeExecutiveSender":
      await removeExecutiveSender(ctx, message.value);
      break;
    case "deleteExecutiveEmail":
      await deleteExecutiveEmail(ctx, message.value);
      break;
    case "backfillExecutiveEmails":
      await backfillExecutiveEmails(ctx);
      break;
    case "refreshExecutiveEmails":
      await refreshExecutiveEmails(ctx);
      break;
    case "helpTraceDate":
      await loadHelpTraceEvents(ctx, message.date);
      break;
    default:
      logger.warn(`Unknown performance action: ${action}`);
      return false;
  }
  return true;
}

// ============================================================
// Action Handlers
// ============================================================

export function navigateMonth(ctx: ActionContext, delta: number): void {
  let newMonth = ctx.state.calendar_month + delta;
  let newYear = ctx.state.calendar_year;
  if (newMonth < 0) {
    newMonth = 11;
    newYear--;
  }
  if (newMonth > 11) {
    newMonth = 0;
    newYear++;
  }

  const quarter = Math.floor(ctx.state.calendar_month / 3);
  const qStart = quarter * 3;
  const qEnd = qStart + 2;
  if (newMonth < qStart || newMonth > qEnd) return;

  ctx.state.calendar_month = newMonth;
  ctx.state.calendar_year = newYear;
  ctx.notifyNeedsRender();
}

export async function loadDayDetail(ctx: ActionContext, dateStr: string): Promise<void> {
  try {
    const result = await dbus.stats_getDayDetail(dateStr);
    if (result.success && result.data) {
      const raw = result.data as any;
      ctx.state.day_detail = {
        date: raw.date || dateStr,
        events: Array.isArray(raw.events) ? raw.events : [],
        daily_points: raw.daily_points || {},
        daily_total: raw.daily_total || 0,
        category_points: raw.category_points || {},
        has_data: raw.has_data || false,
      };
      ctx.notifyNeedsRender();
    }
  } catch (e) {
    logger.warn(`Failed to load day detail: ${e}`);
  }
}

export async function refreshHierarchy(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Refreshing issue hierarchy from Jira...");
  try {
    const result = await dbus.stats_getIssueHierarchy(true);
    if (result.success && result.data) {
      const raw = result.data as any;
      ctx.state.issue_hierarchy = {
        strategies: Array.isArray(raw.strategies) ? raw.strategies : [],
        unattached_epics: Array.isArray(raw.unattached_epics) ? raw.unattached_epics : [],
        uncategorized: Array.isArray(raw.uncategorized) ? raw.uncategorized : [],
        total_issues: raw.total_issues || 0,
        cached: raw.cached || false,
        summary:
          raw.summary || {
            total_points: 0,
            aligned_points: 0,
            unaligned_points: 0,
            alignment_pct: 0,
            scope_points: {},
            pillar_points: {
              technical: 0,
              leadership: 0,
              mentorship: 0,
              delivery: 0,
            },
            tag_counts: {},
          },
      };
      vscode.window.showInformationMessage("Issue hierarchy refreshed");
      ctx.notifyNeedsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to refresh hierarchy: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error refreshing hierarchy: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function collectDailyData(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Collecting today's data (user + peers)...");
  try {
    const [dailyResult, peersResult] = await Promise.all([
      dbus.stats_collectDaily(),
      dbus.stats_collectPeers(false),
    ]);

    const parts: string[] = [];
    if (dailyResult.success) {
      const data = dailyResult.data as any;
      parts.push(`${data?.event_count || 0} events, ${data?.daily_total || 0} points`);
    } else {
      parts.push(`daily failed: ${dailyResult.error}`);
    }
    if (peersResult.success) {
      const pd = peersResult.data as any;
      parts.push(`${pd?.peers_processed ?? 0} peers`);
    } else {
      parts.push(`peers failed: ${peersResult.error}`);
    }

    vscode.window.showInformationMessage(`Daily collection complete: ${parts.join(", ")}`);
    await ctx.refresh();
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error collecting data: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function backfillAll(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage(
    "Backfilling all quarter data (metadata, user, peers, emails)..."
  );
  try {
    vscode.window.showInformationMessage(
      "Phase 1/4: Syncing metadata (strategy, senders, hierarchy)..."
    );
    await Promise.allSettled([
      dbus.stats_syncAnstratOwnership(),
      dbus.stats_syncSenderSources(),
      dbus.stats_getIssueHierarchy(true),
    ]);

    vscode.window.showInformationMessage(
      "Phase 2/4: Collecting user data and executive emails..."
    );
    const [daysResult, emailsResult] = await Promise.all([
      dbus.stats_backfill(),
      dbus.stats_backfillExecutiveEmails(),
    ]);

    const parts: string[] = [];
    if (daysResult.success) {
      const d = daysResult.data as any;
      parts.push(`${d?.days_processed || 0} days re-collected`);
    } else {
      parts.push(`days failed: ${daysResult.error}`);
    }
    if (emailsResult.success) {
      const e = emailsResult.data as any;
      const total = (e?.total_new || 0) + (e?.total_skipped || 0);
      parts.push(`${total} emails (${e?.total_new || 0} new)`);
    } else {
      parts.push(`emails failed: ${emailsResult.error}`);
    }

    vscode.window.showInformationMessage("Phase 3/4: Re-scoring with fresh metadata...");
    await dbus.stats_evaluateAll();

    vscode.window.showInformationMessage(
      `User backfill done: ${parts.join(", ")}. Phase 4/4: Starting peer backfill...`
    );

    try {
      const peersResult = await dbus.stats_collectPeers(true);
      if (peersResult.success) {
        ctx.postMessageToWebview({ command: "peerBackfillStarted" });
        ctx._backfillPollInterval = setInterval(() => pollBackfillProgress(ctx), 2000);
      } else {
        vscode.window.showErrorMessage(`Peer backfill failed: ${peersResult.error}`);
        await ctx.refresh();
      }
    } catch (peerError) {
      vscode.window.showErrorMessage(
        `Peer backfill error: ${peerError instanceof Error ? peerError.message : String(peerError)}`
      );
      await ctx.refresh();
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error backfilling: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function exportReport(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Generating PDF report... this may take a moment.");
  try {
    const result = await dbus.stats_exportReport("pdf");
    if (result.success && result.data) {
      const data = result.data as any;
      if (data.path) {
        vscode.window.showInformationMessage(`PDF report exported to: ${data.path}`);
        const fileUri = vscode.Uri.file(data.path);
        await vscode.env.openExternal(fileUri);
      } else {
        vscode.window.showInformationMessage("Report exported successfully");
      }
    } else {
      vscode.window.showErrorMessage(`Failed to export: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error exporting: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function collectPeers(ctx: ActionContext, backfill: boolean): Promise<void> {
  if (!backfill) {
    vscode.window.showInformationMessage("Collecting peer data for today...");
    try {
      const result = await dbus.stats_collectPeers(false);
      if (result.success) {
        const data = result.data as any;
        vscode.window.showInformationMessage(
          `Peer collection complete: ${data?.peers_processed ?? 0} peers processed`
        );
        await ctx.refresh();
      } else {
        vscode.window.showErrorMessage(`Peer collection failed: ${result.error}`);
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Error collecting peers: ${error instanceof Error ? error.message : String(error)}`
      );
    }
    return;
  }

  vscode.window.showInformationMessage("Starting peer backfill (runs in background)...");
  try {
    const result = await dbus.stats_collectPeers(true);
    if (result.success) {
      ctx.postMessageToWebview({ command: "peerBackfillStarted" });
      ctx._backfillPollInterval = setInterval(() => pollBackfillProgress(ctx), 2000);
    } else {
      vscode.window.showErrorMessage(`Peer backfill failed: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error starting backfill: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function startFilteredBackfill(ctx: ActionContext, message: any): Promise<void> {
  const allSourceKeys = ["git", "jira", "gitlab", "github", "gdrive", "meeting"] as const;
  const sources: string[] = [];
  if (message.srcGit) sources.push("git");
  if (message.srcJira) sources.push("jira");
  if (message.srcGitlab) sources.push("gitlab");
  if (message.srcGithub) sources.push("github");
  if (message.srcGdrive) sources.push("gdrive");
  if (message.srcMeeting) sources.push("meeting");

  const scopeUser = message.scopeUser !== false;
  const scopePeers = message.scopePeers !== false;
  const scopeEmails = message.scopeEmails !== false;

  if (sources.length === 0) {
    vscode.window.showWarningMessage("Select at least one source to backfill.");
    return;
  }
  if (!scopeUser && !scopePeers && !scopeEmails) {
    vscode.window.showWarningMessage(
      "Select at least one scope (My data, Peers, or Emails)."
    );
    return;
  }

  const options: { sources?: string[]; dateStart?: string; dateEnd?: string } = {};
  if (sources.length < allSourceKeys.length) {
    options.sources = sources;
  }
  const dateRange = message.dateRange as string;
  if (dateRange && dateRange !== "full") {
    const days = parseInt(dateRange, 10);
    if (!isNaN(days)) {
      const now = new Date();
      const start = new Date(now);
      start.setDate(start.getDate() - days);
      options.dateStart = start.toISOString().slice(0, 10);
    }
  }

  const scopeParts: string[] = [];
  if (scopeUser) scopeParts.push("user");
  if (scopePeers) scopeParts.push("peers");
  if (scopeEmails) scopeParts.push("emails");
  const label =
    sources.length < allSourceKeys.length ? sources.join(", ") : "all sources";
  const rangeLabel = dateRange === "full" ? "full quarter" : `last ${dateRange} days`;
  vscode.window.showInformationMessage(
    `Starting backfill: ${scopeParts.join("+")} — ${label}, ${rangeLabel}...`
  );

  ctx.postMessageToWebview({ command: "hideBackfillOptions" });

  try {
    if (scopeUser) {
      vscode.window.showInformationMessage("Syncing metadata (strategy, senders, hierarchy)...");
      await Promise.allSettled([
        dbus.stats_syncAnstratOwnership(),
        dbus.stats_syncSenderSources(),
        dbus.stats_getIssueHierarchy(true),
      ]);
    }

    const promises: Promise<any>[] = [];

    if (scopeUser) {
      promises.push(dbus.stats_backfill());
    }
    if (scopeEmails) {
      promises.push(dbus.stats_backfillExecutiveEmails());
    }

    if (promises.length > 0) {
      const results = await Promise.all(promises);
      const parts: string[] = [];
      let idx = 0;
      if (scopeUser) {
        const r = results[idx++];
        if (r.success) {
          parts.push(`${(r.data as any)?.days_processed || 0} days`);
        } else {
          parts.push(`user failed: ${r.error}`);
        }
      }
      if (scopeEmails) {
        const r = results[idx++];
        if (r.success) {
          const e = r.data as any;
          parts.push(`${(e?.total_new || 0) + (e?.total_skipped || 0)} emails`);
        } else {
          parts.push(`emails failed: ${r.error}`);
        }
      }
      if (parts.length > 0) {
        vscode.window.showInformationMessage(`Backfill progress: ${parts.join(", ")}`);
      }
    }

    if (scopeUser) {
      vscode.window.showInformationMessage("Re-scoring with fresh metadata...");
      await dbus.stats_evaluateAll();
    }

    if (scopePeers) {
      const result = await dbus.stats_collectPeers(true, options);
      if (result.success) {
        ctx.postMessageToWebview({ command: "peerBackfillStarted" });
        ctx._backfillPollInterval = setInterval(() => pollBackfillProgress(ctx), 2000);
      } else {
        vscode.window.showErrorMessage(`Peer backfill failed: ${result.error}`);
        await ctx.refresh();
      }
    } else {
      await ctx.refresh();
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error starting filtered backfill: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function rescorePeers(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Re-scoring peer data (no re-collection)...");
  ctx.postMessageToWebview({ command: "hideBackfillOptions" });
  try {
    const result = await dbus.stats_rescorePeers();
    if (result.success) {
      const data = result.data as any;
      vscode.window.showInformationMessage(
        `Re-score complete: ${data?.files_updated ?? 0} files, ${data?.peers_updated ?? 0} peers updated`
      );
      await ctx.refresh();
    } else {
      vscode.window.showErrorMessage(`Re-score failed: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error re-scoring peers: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function cancelBackfill(ctx: ActionContext): Promise<void> {
  try {
    const result = await dbus.stats_cancelBackfill();
    if (ctx._backfillPollInterval) {
      clearInterval(ctx._backfillPollInterval);
      ctx._backfillPollInterval = undefined;
    }
    ctx._backfillEverRanning = false;
    ctx.postMessageToWebview({ command: "peerBackfillCancelled" });
    if (result.success) {
      vscode.window.showInformationMessage("Backfill cancelled.");
    } else {
      vscode.window.showErrorMessage(`Cancel failed: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error cancelling backfill: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function scrubData(ctx: ActionContext): Promise<void> {
  const confirm = await vscode.window.showWarningMessage(
    "This will delete ALL collected performance data for the current quarter (user daily data, peer data, caches, executive emails). This cannot be undone.",
    { modal: true },
    "Scrub All Data"
  );
  if (confirm !== "Scrub All Data") return;

  ctx.postMessageToWebview({ command: "hideBackfillOptions" });
  try {
    const result = await dbus.stats_scrubData();
    if (result.success) {
      const data = result.data as any;
      vscode.window.showInformationMessage(
        `Data scrubbed: ${data?.message ?? "Done"}. Run Backfill to re-collect.`
      );
      ctx.state.overall_percentage = 0;
      ctx.state.peer_comparable_overall = 0;
      ctx.state.event_counts_by_source = {};
      ctx.state.competencies = {};
      ctx.state.highlights = [];
      ctx.state.gaps = [];
      ctx.state.captured_days = [];
      ctx.state.coverage = { total_weekdays: 0, captured: 0, percentage: 0 };
      ctx.state.issue_hierarchy = null;
      ctx.state.day_detail = null;
      ctx.state.competency_evidence = {};
      ctx.state.competency_meta = {};
      ctx.state.gap_suggestions = {};
      ctx.state.strategy_alignment = null;
      ctx.state.executive_emails = [];
      ctx.state.peer_benchmarks = null;
      ctx.state.org_stats = null;
      ctx.state.ai_peer_narrative = null;
      ctx.state.ai_peer_differentiators = null;
      ctx.state.ai_overview_digest = null;
      ctx.state.ai_calendar_insights = null;
      ctx.state.ai_promotion_readiness = null;
      await ctx.refresh();
    } else {
      vscode.window.showErrorMessage(`Scrub failed: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error scrubbing data: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function pollBackfillProgress(ctx: ActionContext): Promise<void> {
  try {
    const result = await dbus.stats_getPeerBackfillProgress();
    if (!result.success) return;
    const p = result.data as any;

    if (p.running) {
      ctx._backfillEverRanning = true;
    }

    ctx.postMessageToWebview({ command: "peerBackfillProgress", progress: p });

    if (!p.running && ctx._backfillEverRanning) {
      ctx._backfillEverRanning = false;
      if (ctx._backfillPollInterval) {
        clearInterval(ctx._backfillPollInterval);
        ctx._backfillPollInterval = undefined;
      }
      if (p.cancelled) {
        ctx.postMessageToWebview({ command: "peerBackfillCancelled" });
        vscode.window.showInformationMessage("Backfill was cancelled.");
      } else {
        const evts = p.total_events ?? 0;
        const peers = p.completed_peers ?? 0;
        const secs = p.elapsed_seconds ?? 0;
        const errs = p.errors?.length ?? 0;
        const filterInfo =
          p.filter_info && p.filter_info !== "all" ? ` [${p.filter_info}]` : "";
        vscode.window.showInformationMessage(
          `Peer backfill complete: ${peers} peers, ${evts} events in ${secs}s` +
            (errs > 0 ? ` (${errs} errors)` : "") +
            filterInfo
        );
        ctx.postMessageToWebview({ command: "peerBackfillComplete", progress: p });
      }
      await ctx.refresh();
    }
  } catch {
    // polling failure is transient, just skip
  }
}

export async function loadPeerGrowth(ctx: ActionContext): Promise<void> {
  try {
    const result = await dbus.stats_getPeerGrowthData();
    if (result.success && result.data) {
      const data = result.data as any;
      ctx.postMessageToWebview({ command: "peerGrowthData", data });
    } else {
      vscode.window.showWarningMessage("No growth data available.");
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Failed to load growth data: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function loadPromotionReadiness(ctx: ActionContext): Promise<void> {
  try {
    const result = await dbus.stats_getPromotionReadiness();
    if (result.success && result.data) {
      ctx.state.ai_promotion_readiness = result.data as any;
      ctx.notifyNeedsRender();
    } else {
      vscode.window.showWarningMessage(
        `Promotion readiness: ${result.error || "No data"}`
      );
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Failed to load promotion readiness: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function evaluateQuestionLocal(
  ctx: ActionContext,
  questionId: string
): Promise<void> {
  if (!questionId) return;
  vscode.window.showInformationMessage("Evaluating question with local LLM...");
  try {
    const result = await dbus.stats_evaluateQuestionLocal(questionId);
    if (result.success && result.data) {
      const data = result.data as any;
      vscode.window.showInformationMessage(
        `Evaluation complete (${data.model || "local LLM"})`
      );
      await ctx.refresh();
    } else {
      vscode.window.showErrorMessage(
        `Evaluation failed: ${result.error || "Unknown error"}`
      );
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Local evaluation error: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function classifyLogEntry(
  ctx: ActionContext,
  description: string
): Promise<void> {
  if (!description || description.length < 5) return;
  try {
    const result = await dbus.stats_classifyLogEntry(description);
    if (result.success && result.data) {
      const cat = (result.data as any).category;
      if (cat) {
        ctx.postMessageToWebview({ command: "aiLogCategory", category: cat });
      }
    }
  } catch {
    /* classification is best-effort */
  }
}

export async function askAI(ctx: ActionContext, question: string): Promise<void> {
  if (!question) return;
  try {
    const result = await dbus.stats_askAI(question);
    if (result.success && result.data) {
      const answer = (result.data as any).answer || "No answer available.";
      ctx.postMessageToWebview({ command: "aiAnswer", answer, question });
    }
  } catch (error) {
    ctx.postMessageToWebview({
      command: "aiAnswer",
      answer: "AI is currently unavailable.",
      question,
    });
  }
}

export async function loadGapCoach(
  ctx: ActionContext,
  competencyId: string
): Promise<void> {
  if (!competencyId) return;
  try {
    const result = await dbus.stats_getGapCoach(competencyId);
    if (result.success && result.data) {
      const suggestion = (result.data as any).suggestion || "";
      if (suggestion) {
        ctx.state.gap_suggestions[competencyId] = {
          ...(ctx.state.gap_suggestions[competencyId] || {}),
          ai_suggestion: suggestion,
        } as any;
        ctx.notifyNeedsRender();
      }
    }
  } catch {
    /* gap coach is best-effort */
  }
}

export async function explainScore(
  ctx: ActionContext,
  competencyId: string
): Promise<void> {
  if (!competencyId) return;
  try {
    const result = await dbus.stats_explainCompetencyScore(competencyId);
    if (result.success && result.data) {
      const explanation = (result.data as any).explanation || "";
      if (explanation) {
        vscode.window.showInformationMessage(explanation.substring(0, 500));
      }
    }
  } catch {
    /* explanation is best-effort */
  }
}

export async function detectMissingLinks(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Scanning for orphan issues...");
  try {
    const result = await dbus.stats_detectMissingLinks();
    if (result.success && result.data) {
      const suggestions = (result.data as any).suggestions || [];
      ctx.postMessageToWebview({ command: "missingLinksResult", suggestions });
      if (suggestions.length === 0) {
        vscode.window.showInformationMessage(
          "No missing links found -- all issues appear well-connected."
        );
      }
    } else {
      vscode.window.showWarningMessage(
        result.error || "Missing link detection unavailable."
      );
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Missing link detection failed: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function suggestConfigTune(ctx: ActionContext): Promise<void> {
  try {
    const result = await dbus.stats_suggestConfigTune();
    if (result.success && result.data) {
      const suggestions = (result.data as any).suggestions || [];
      if (suggestions.length === 0) {
        vscode.window.showInformationMessage(
          "No config adjustments suggested -- your settings look balanced."
        );
      } else {
        const msgs = suggestions.map((s: any) => s.message).join("\n\n");
        vscode.window.showInformationMessage(msgs.substring(0, 500));
      }
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Config tune failed: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function logActivity(
  ctx: ActionContext,
  category: string,
  description: string
): Promise<void> {
  if (!description) {
    vscode.window.showWarningMessage("Please enter a description");
    return;
  }
  try {
    const result = await dbus.stats_logActivity(category, description);
    if (result.success) {
      vscode.window.showInformationMessage(`Activity logged: ${category}`);
      await ctx.refresh();
    } else {
      vscode.window.showErrorMessage(`Failed to log activity: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error logging activity: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function evaluateAllQuestions(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Re-evaluating all questions...");
  try {
    const result = await dbus.stats_evaluateAll();
    if (result.success) {
      vscode.window.showInformationMessage("All questions re-evaluated");
      await ctx.refreshPreservingUIState();
    } else {
      vscode.window.showErrorMessage(`Failed to evaluate: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error evaluating: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function clearAllDrafts(ctx: ActionContext): Promise<void> {
  const answer = await vscode.window.showWarningMessage(
    "Clear all AI-generated drafts? You can re-generate them later.",
    "Clear Drafts",
    "Cancel"
  );
  if (answer !== "Clear Drafts") return;

  try {
    const result = await dbus.stats_clearDrafts();
    if (result.success) {
      const data = result.data as any;
      const cleared = data?.cleared || 0;
      if (data?.questions_summary) {
        ctx.state.questions_summary = data.questions_summary;
      }
      vscode.window.showInformationMessage(
        `Cleared ${cleared} AI draft${cleared !== 1 ? "s" : ""}`
      );
      ctx.notifyNeedsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to clear drafts: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error clearing drafts: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function saveQuestion(
  ctx: ActionContext,
  description: string
): Promise<void> {
  if (!description) return;

  try {
    const result = await dbus.stats_addQuestion(description);
    if (result.success) {
      const data = result.data as any;
      if (data?.questions_summary) {
        ctx.state.questions_summary = data.questions_summary;
      }
      vscode.window.showInformationMessage("Question added.");
      ctx.notifyNeedsRender();
    } else {
      vscode.window.showErrorMessage(
        `Failed to add question: ${result.error || "Unknown error"}`
      );
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error adding question: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function removeQuestion(
  ctx: ActionContext,
  questionId: string
): Promise<void> {
  if (!questionId) return;

  const answer = await vscode.window.showWarningMessage(
    "Remove this question? Evidence and notes will be lost.",
    "Remove",
    "Cancel"
  );
  if (answer !== "Remove") return;

  try {
    const result = await dbus.stats_removeQuestion(questionId);
    if (result.success) {
      const data = result.data as any;
      if (data?.questions_summary) {
        ctx.state.questions_summary = data.questions_summary;
      }
      vscode.window.showInformationMessage("Question removed.");
      ctx.notifyNeedsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to remove question: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error removing question: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function addNoteToQuestion(
  ctx: ActionContext,
  questionId: string
): Promise<void> {
  if (!questionId) return;
  const note = await vscode.window.showInputBox({
    prompt: "Enter a note for this question",
    placeHolder: "Your note...",
  });
  if (!note) return;
  try {
    const result = await dbus.stats_addQuestionNote(questionId, note);
    if (result.success) {
      const data = result.data as any;
      if (data?.questions_summary) {
        ctx.state.questions_summary = data.questions_summary;
      }
      ctx.notifyNeedsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to add note: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error adding note: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function evaluateQuestion(
  ctx: ActionContext,
  questionId: string
): Promise<void> {
  if (!questionId) return;
  const excluded = ctx._excludedEvidence.get(questionId);
  const excludedList = excluded ? Array.from(excluded) : [];

  const inputObj: Record<string, any> = { question_id: questionId };
  if (excludedList.length > 0) {
    inputObj.exclude_evidence = excludedList;
  }

  const evidence = ctx._questionEvidence.get(questionId);
  const question = ctx.state.questions_summary?.find((q) => q.id === questionId);
  const totalEvidence = evidence ? evidence.length : question?.evidence_count || 0;
  const selectedCount = evidence ? evidence.length - excludedList.length : totalEvidence;
  const notesCount = question?.notes_count || 0;

  const evalCommand = `Evaluate the quarterly performance question "${questionId}" using AI.

Step 1: Run the evaluate skill to gather evidence and build the prompt:
skill_run("performance_evaluate_questions", '${JSON.stringify(inputObj)}')

Step 2: Read the evidence and prompt from the skill output, then write a 2-3 paragraph first-person response highlighting significant accomplishments with specific examples and metrics.

Step 3: Save your generated response using:
performance_save_evaluation("${questionId}", "<your generated response>")

There are ${selectedCount} of ${totalEvidence} evidence items and ${notesCount} notes available.
After saving, the QC tab will show the result inline on the card.`;

  vscode.window.showInformationMessage(
    `Evaluating "${questionId}" (${selectedCount} items)...`
  );
  await createNewChat({
    message: evalCommand,
    autoSubmit: true,
    returnToPrevious: true,
  });
}

export async function toggleEvidencePanel(
  ctx: ActionContext,
  questionId: string
): Promise<void> {
  if (!questionId) return;

  if (ctx._expandedQuestions.has(questionId)) {
    ctx._expandedQuestions.delete(questionId);
    ctx.notifyNeedsRender();
    return;
  }

  ctx._expandedQuestions.add(questionId);

  if (!ctx._questionEvidence.has(questionId)) {
    ctx._questionEvidenceLoading.add(questionId);
    ctx.notifyNeedsRender();

    try {
      const result = await dbus.stats_getQuestionDetail(questionId);
      if (result.success && result.data) {
        const data = result.data as any;
        ctx._questionEvidence.set(questionId, data.evidence || []);
      }
    } catch (error) {
      logger.log(`Failed to load evidence for ${questionId}: ${error}`);
    } finally {
      ctx._questionEvidenceLoading.delete(questionId);
    }
  }

  ctx.notifyNeedsRender();
}

export function toggleEvidenceItem(
  ctx: ActionContext,
  questionId: string,
  evidenceId: string
): void {
  if (!questionId || !evidenceId) return;
  let excluded = ctx._excludedEvidence.get(questionId);
  if (!excluded) {
    excluded = new Set<string>();
    ctx._excludedEvidence.set(questionId, excluded);
  }

  if (excluded.has(evidenceId)) {
    excluded.delete(evidenceId);
  } else {
    excluded.add(evidenceId);
  }
  ctx.notifyNeedsRender();
}

export function selectAllEvidence(ctx: ActionContext, questionId: string): void {
  if (!questionId) return;
  ctx._excludedEvidence.delete(questionId);
  ctx.notifyNeedsRender();
}

export function deselectAllEvidence(ctx: ActionContext, questionId: string): void {
  if (!questionId) return;
  const evidence = ctx._questionEvidence.get(questionId);
  if (!evidence) return;
  ctx._excludedEvidence.set(questionId, new Set(evidence.map((e: any) => e.id)));
  ctx.notifyNeedsRender();
}

// ============================================================
// Scoring Config Handlers
// ============================================================

export function setEngineeringLevel(ctx: ActionContext, level: string): void {
  if (!ctx.state.scoring_config || !level) return;
  ctx.state.scoring_config.engineering_level = level;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function setScopeMultiplier(
  ctx: ActionContext,
  scope: string,
  value: string | number
): void {
  if (!ctx.state.scoring_config || !scope) return;
  const cfg = ctx.state.scoring_config;
  if (!cfg.scope_multipliers) cfg.scope_multipliers = {};
  cfg.scope_multipliers[scope] =
    typeof value === "string" ? parseInt(value, 10) : value;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function setRoleWeight(
  ctx: ActionContext,
  scope: string,
  role: string,
  value: string | number
): void {
  if (!ctx.state.scoring_config || !scope || !role) return;
  const cfg = ctx.state.scoring_config;
  if (!cfg.level_weights) cfg.level_weights = {};
  if (!cfg.level_weights!.role_weights) cfg.level_weights!.role_weights = {};
  if (!cfg.level_weights!.role_weights![scope])
    cfg.level_weights!.role_weights![scope] = {};
  cfg.level_weights!.role_weights![scope][role] =
    typeof value === "string" ? parseFloat(value) : value;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function setPillarWeight(
  ctx: ActionContext,
  pillar: string,
  value: string | number
): void {
  if (!ctx.state.scoring_config || !pillar) return;
  const cfg = ctx.state.scoring_config;
  if (!cfg.level_weights) cfg.level_weights = {};
  if (!cfg.level_weights!.pillar_weights) cfg.level_weights!.pillar_weights = {};
  cfg.level_weights!.pillar_weights![pillar] =
    typeof value === "string" ? parseFloat(value) : value;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function setStrategyField(
  ctx: ActionContext,
  field: string,
  value: unknown
): void {
  if (!ctx.state.scoring_config) return;
  const cfg = ctx.state.scoring_config;
  if (!cfg.strategy_alignment) cfg.strategy_alignment = {};
  (cfg.strategy_alignment as Record<string, unknown>)[field] = value;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function setNpuField(
  ctx: ActionContext,
  field: string,
  value: unknown
): void {
  if (!ctx.state.scoring_config) return;
  const cfg = ctx.state.scoring_config;
  if (!cfg.npu_settings) cfg.npu_settings = {};
  (cfg.npu_settings as Record<string, unknown>)[field] = value;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function updateScoringGlobal(
  ctx: ActionContext,
  field: string,
  value: number
): void {
  if (!ctx.state.scoring_config || !field) return;
  (ctx.state.scoring_config as unknown as Record<string, unknown>)[field] = value;
  const delay = field === "min_signals" || field === "daily_cap" ? 500 : 1500;
  ctx.debouncedSaveScoringConfig(delay);
  ctx.deferredSettingsRender();
}

export function updateCompBasePoints(
  ctx: ActionContext,
  compId: string,
  value: number
): void {
  if (!ctx.state.scoring_config?.competencies?.[compId]) return;
  ctx.state.scoring_config.competencies[compId].base_points = value;
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function toggleScoringEventType(
  ctx: ActionContext,
  compId: string,
  eventType: string
): void {
  if (!ctx.state.scoring_config?.competencies?.[compId] || !eventType) return;
  const comp = ctx.state.scoring_config.competencies[compId];
  const idx = comp.event_types.indexOf(eventType);
  if (idx >= 0) {
    comp.event_types.splice(idx, 1);
  } else {
    comp.event_types.push(eventType);
  }
  ctx.debouncedSaveScoringConfig();
  ctx.deferredSettingsRender();
}

export function removeScoringTag(
  ctx: ActionContext,
  field: "phrases" | "keywords",
  compId: string,
  value: string
): void {
  if (!ctx.state.scoring_config?.competencies?.[compId] || !value) return;
  const arr = ctx.state.scoring_config.competencies[compId][field];
  const idx = arr.indexOf(value);
  if (idx >= 0) {
    arr.splice(idx, 1);
    ctx.debouncedSaveScoringConfig();
    ctx.deferredSettingsRender();
  }
}

export function addScoringTag(
  ctx: ActionContext,
  field: "phrases" | "keywords",
  compId: string,
  value: string
): void {
  if (!ctx.state.scoring_config?.competencies?.[compId] || !value) return;
  const arr = ctx.state.scoring_config.competencies[compId][field];
  if (!arr.includes(value)) {
    arr.push(value);
    ctx.debouncedSaveScoringConfig();
    ctx.deferredSettingsRender();
  }
}

// ============================================================
// Executive Email Source Management
// ============================================================

export async function addExecutiveSender(
  ctx: ActionContext,
  email: string
): Promise<void> {
  if (!email || !email.includes("@")) return;
  const normalized = email.trim().toLowerCase();
  if (ctx.state.executive_senders.includes(normalized)) return;
  const updated = [...ctx.state.executive_senders, normalized];
  try {
    const result = await dbus.stats_setExecutiveSenders(updated);
    if (result.success && result.data) {
      ctx.state.executive_senders = (result.data as any).senders || updated;
      ctx.deferredSettingsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to add sender: ${result.error}`);
    }
  } catch (e) {
    vscode.window.showErrorMessage(
      `Error adding sender: ${e instanceof Error ? e.message : String(e)}`
    );
  }
}

export async function removeExecutiveSender(
  ctx: ActionContext,
  email: string
): Promise<void> {
  if (!email) return;
  const updated = ctx.state.executive_senders.filter((s) => s !== email);
  try {
    const result = await dbus.stats_setExecutiveSenders(updated);
    if (result.success && result.data) {
      ctx.state.executive_senders = (result.data as any).senders || updated;
      ctx.deferredSettingsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to remove sender: ${result.error}`);
    }
  } catch (e) {
    vscode.window.showErrorMessage(
      `Error removing sender: ${e instanceof Error ? e.message : String(e)}`
    );
  }
}

export async function deleteExecutiveEmail(
  ctx: ActionContext,
  emailId: string
): Promise<void> {
  if (!emailId) return;
  try {
    const result = await dbus.stats_deleteExecutiveEmail(emailId);
    if (result.success) {
      ctx.state.executive_emails = ctx.state.executive_emails.filter(
        (e) => e.email_id !== emailId
      );
      ctx.deferredSettingsRender();
    } else {
      vscode.window.showErrorMessage(`Failed to delete email: ${result.error}`);
    }
  } catch (e) {
    vscode.window.showErrorMessage(
      `Error deleting email: ${e instanceof Error ? e.message : String(e)}`
    );
  }
}

export async function backfillExecutiveEmails(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage(
    "Backfilling executive emails for this quarter..."
  );
  try {
    const result = await dbus.stats_backfillExecutiveEmails();
    if (result.success) {
      const data = result.data as any;
      const totalNew = data?.total_new ?? 0;
      const senders: Array<{
        sender: string;
        found?: number;
        new?: number;
        error?: string;
      }> = data?.senders ?? [];
      const failed = senders.filter((s) => s.error);
      const empty = senders.filter((s) => !s.error && (s.found ?? 0) === 0);
      let msg = `Backfill complete: ${totalNew} new emails fetched`;
      if (empty.length > 0) {
        msg += ` | No emails found for: ${empty.map((s) => s.sender).join(", ")}`;
      }
      if (failed.length > 0) {
        msg += ` | Failed: ${failed.map((s) => `${s.sender} (${s.error})`).join(", ")}`;
      }
      if (failed.length > 0) {
        vscode.window.showWarningMessage(msg);
      } else {
        vscode.window.showInformationMessage(msg);
      }
      await refreshExecutiveEmails(ctx);
    } else {
      vscode.window.showErrorMessage(`Backfill failed: ${result.error}`);
    }
  } catch (e) {
    vscode.window.showErrorMessage(
      `Backfill error: ${e instanceof Error ? e.message : String(e)}`
    );
  }
}

export async function refreshExecutiveEmails(ctx: ActionContext): Promise<void> {
  try {
    const result = await dbus.stats_listExecutiveEmails();
    if (result.success && result.data) {
      ctx.state.executive_emails = (result.data as any).emails || [];
      ctx.deferredSettingsRender();
    }
  } catch (e) {
    logger.warn(`Failed to refresh executive emails: ${e}`);
  }
}

export async function resetScoringConfig(ctx: ActionContext): Promise<void> {
  vscode.window.showInformationMessage("Resetting scoring config to defaults...");
  try {
    const result = await dbus.stats_resetScoringConfig();
    if (result.success) {
      vscode.window.showInformationMessage(
        "Config reset to defaults. Scores re-evaluated."
      );
      await ctx.refreshPreservingUIState();
    } else {
      vscode.window.showErrorMessage(`Failed to reset: ${result.error}`);
    }
  } catch (error) {
    vscode.window.showErrorMessage(
      `Error resetting: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

export async function loadHelpTraceEvents(
  ctx: ActionContext,
  dateStr: string
): Promise<void> {
  try {
    const result = await dbus.stats_getDayDetail(dateStr);
    if (result.success && result.data) {
      const raw = result.data as any;
      const events: DayEvent[] = Array.isArray(raw.events) ? raw.events : [];

      const scopeMultipliers = DEFAULT_SCOPE_MULTIPLIERS;

      let traceHtml = "";
      if (events.length === 0) {
        traceHtml = `<div class="perf-help-empty">No events found for ${ctx.escapeHtml(dateStr)}.</div>`;
      } else {
        traceHtml = events
          .slice(0, 10)
          .map((ev, idx) => {
            const scope = (ev as any).scope || "story";
            const role = (ev as any).role || "assignee";
            const strategyAligned = (ev as any).strategy_aligned || false;
            const scopeMult = scopeMultipliers[scope] || 1;
            const totalPts = Object.values(ev.points || {}).reduce(
              (s: number, v: number) => s + v,
              0
            );
            const compsHit = Object.keys(ev.points || {}).length;
            const lineageStr =
              (ev.lineage || [])
                .map(
                  (l: any) =>
                    `${ctx.escapeHtml(l.key)}${l.epic ? ` &rarr; ${ctx.escapeHtml(l.epic.key)}` : ""}${l.anstrat ? ` &rarr; ${ctx.escapeHtml(l.anstrat.key)}` : ""}`
                )
                .join(", ") || "none";

            return `
              <div class="perf-help-trace-step pass">
                <div class="perf-help-trace-step-num">${idx + 1}</div>
                <div class="perf-help-trace-step-content">
                  <strong>${ctx.safeText(ev.title || ev.item_id)}</strong>
                  <div class="text-secondary text-sm mt-4">
                    Source: <strong>${ctx.escapeHtml(ev.source)}</strong> &middot;
                    Type: <strong>${ctx.escapeHtml(ev.type)}</strong> &middot;
                    Scope: <strong>${ctx.escapeHtml(scope)} (x${scopeMult})</strong> &middot;
                    Role: <strong>${ctx.escapeHtml(role)}</strong>
                    ${strategyAligned ? ` &middot; <span class="text-strategy">Strategy Aligned (1.5x)</span>` : ""}
                  </div>
                  <div class="text-secondary text-sm">Lineage: ${lineageStr}</div>
                  <div class="text-sm mt-4">
                    <strong>${totalPts} pts</strong> across ${compsHit} competencies:
                    ${Object.entries(ev.points || {})
                      .map(
                        ([c, p]) =>
                          `<span class="mr-6">${ctx.escapeHtml(c)}: ${p}</span>`
                      )
                      .join("")}
                  </div>
                </div>
              </div>
            `;
          })
          .join("");

        if (events.length > 10) {
          traceHtml += `<div class="perf-help-empty">Showing 10 of ${events.length} events.</div>`;
        }
      }

      ctx.postMessageToWebview({
        command: "helpTraceResult",
        html: traceHtml,
      });
    }
  } catch (e) {
    logger.warn(`Failed to load help trace events: ${e}`);
    ctx.postMessageToWebview({
      command: "helpTraceResult",
      html: `<div class="perf-help-empty">Failed to load events.</div>`,
    });
  }
}
