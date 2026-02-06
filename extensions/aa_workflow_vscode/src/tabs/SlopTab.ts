/**
 * Slop Tab
 *
 * Displays code quality findings from the Slop Bot daemon.
 * Shows loop status, findings table, and statistics.
 * Uses D-Bus to communicate with the Slop daemon.
 */

import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("SlopTab");

interface LoopStatus {
  name: string;
  display_name: string;
  status: "idle" | "running" | "done" | "stopped" | "error";
  iteration: number;
  max_iterations: number;
  findings_count: number;
  description: string;
}

interface SlopFinding {
  id: string;
  loop: string;
  file: string;
  line: number;
  category: string;
  severity: "critical" | "high" | "medium" | "low";
  description: string;
  suggestion?: string;
  tool?: string;
  detected_at: string;
  status: "open" | "acknowledged" | "fixed" | "false_positive";
}

interface SlopStats {
  total: number;
  by_loop: Record<string, number>;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
}

interface SlopState {
  running: boolean;
  max_parallel: number;
  loops: Record<string, LoopStatus>;
  priority_order: string[];
  findings?: SlopFinding[];
  stats?: SlopStats;
  scan_in_progress?: boolean;
  scan_count?: number;
  last_scan_time?: string;
}

export class SlopTab extends BaseTab {
  private state: SlopState | null = null;
  private findings: SlopFinding[] = [];
  private filter: { loop?: string; severity?: string; status?: string } = {};
  private findingsLimit = 50;
  private loadRetryCount = 0;
  private maxRetries = 3;

  constructor() {
    super({
      id: "slop",
      label: "Slop",
      icon: "🔍",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    // Show error indicator if we have an error
    if (this.lastError && !this.state) {
      return { text: "!", class: "error" };
    }

    if (!this.state) return null;

    // Show running loops count
    const runningLoops = Object.values(this.state.loops || {}).filter(
      (l) => l.status === "running"
    ).length;
    if (runningLoops > 0) {
      return { text: `${runningLoops}`, class: "running" };
    }

    // Show open findings count
    const openFindings = this.state.stats?.by_status?.open || 0;
    if (openFindings > 0) {
      return { text: `${openFindings}`, class: "warning" };
    }

    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    let hasAnyData = false;
    let errors: string[] = [];

    try {
      // Get loop status - this is the primary data source
      logger.log("Calling slop_getLoopStatus()...");
      const statusResult = await dbus.slop_getLoopStatus();
      if (statusResult.success && statusResult.data) {
        this.state = statusResult.data as SlopState;
        hasAnyData = true;
        logger.log("Loop status loaded successfully");
      } else if (statusResult.error) {
        errors.push(`Loop status: ${statusResult.error}`);
        logger.warn(`Failed to get loop status: ${statusResult.error}`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      errors.push(`Loop status: ${msg}`);
      logger.error("Exception getting loop status", error);
    }

    // Get findings - continue even if loop status failed
    try {
      logger.log("Calling slop_getFindings()...");
      const findingsResult = await dbus.slop_getFindings(
        this.filter.loop,
        this.filter.severity,
        this.filter.status,
        this.findingsLimit
      );
      if (findingsResult.success && findingsResult.data) {
        this.findings = (findingsResult.data as any).findings || [];
        hasAnyData = true;
        logger.log(`Loaded ${this.findings.length} findings`);
      } else if (findingsResult.error) {
        errors.push(`Findings: ${findingsResult.error}`);
        logger.warn(`Failed to get findings: ${findingsResult.error}`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      errors.push(`Findings: ${msg}`);
      logger.error("Exception getting findings", error);
    }

    // Get stats - continue even if previous calls failed
    try {
      logger.log("Calling slop_getStats()...");
      const statsResult = await dbus.slop_getStats();
      if (statsResult.success && statsResult.data) {
        if (this.state) {
          this.state.stats = statsResult.data as SlopStats;
        } else {
          // Create minimal state with just stats
          this.state = {
            running: false,
            max_parallel: 1,
            loops: {},
            priority_order: [],
            stats: statsResult.data as SlopStats,
          };
        }
        hasAnyData = true;
        logger.log("Stats loaded successfully");
      } else if (statsResult.error) {
        errors.push(`Stats: ${statsResult.error}`);
        logger.warn(`Failed to get stats: ${statsResult.error}`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      errors.push(`Stats: ${msg}`);
      logger.error("Exception getting stats", error);
    }

    // Update error state
    if (errors.length > 0 && !hasAnyData) {
      this.lastError = errors.join("; ");
      this.loadRetryCount++;
      logger.error(`All D-Bus calls failed (attempt ${this.loadRetryCount}/${this.maxRetries}): ${this.lastError}`);
    } else {
      // Clear error if we got any data
      if (hasAnyData) {
        this.lastError = null;
        this.loadRetryCount = 0;
      }
    }

    // Notify that we need a re-render
    logger.log(`loadData() complete - hasData: ${hasAnyData}, errors: ${errors.length}`);
    this.notifyNeedsRender();
  }

  getContent(): string {
    // Show error state if we have an error and no data
    if (this.lastError && !this.state) {
      return this.getErrorWithRetryHtml();
    }

    if (!this.state) {
      return this.getLoadingHtml("Loading slop data...");
    }

    const { loops, stats, scan_in_progress, scan_count, last_scan_time } = this.state;
    const loopsList = Object.values(loops || {});
    const runningLoops = loopsList.filter((l) => l.status === "running").length;
    const totalFindings = stats?.total || 0;
    const openFindings = stats?.by_status?.open || 0;
    const criticalFindings = stats?.by_severity?.critical || 0;

    return `
      <!-- Overview Stats -->
      <div class="section">
        <div class="section-title">🔍 Code Quality Overview</div>
        <div class="grid-4">
          <div class="stat-card ${scan_in_progress ? "blue" : "green"}">
            <div class="stat-icon">${scan_in_progress ? "⟳" : "✓"}</div>
            <div class="stat-value">${scan_in_progress ? "Scanning" : "Idle"}</div>
            <div class="stat-label">Status</div>
          </div>
          <div class="stat-card ${runningLoops > 0 ? "blue" : "cyan"}">
            <div class="stat-icon">🔄</div>
            <div class="stat-value">${runningLoops}/${loopsList.length}</div>
            <div class="stat-label">Active Loops</div>
          </div>
          <div class="stat-card ${criticalFindings > 0 ? "red" : openFindings > 0 ? "orange" : "green"}">
            <div class="stat-icon">⚠️</div>
            <div class="stat-value">${openFindings}</div>
            <div class="stat-label">Open Issues</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">📊</div>
            <div class="stat-value">${scan_count || 0}</div>
            <div class="stat-label">Total Scans</div>
          </div>
        </div>
      </div>

      <!-- Controls -->
      <div class="section">
        <div class="controls">
          <button class="btn btn-sm btn-primary" data-action="scanNow" ${scan_in_progress ? "disabled" : ""}>
            ${scan_in_progress ? "⟳ Scanning..." : "▶ Scan Now"}
          </button>
          <button class="btn btn-sm btn-danger" data-action="stopAll" ${!scan_in_progress ? "disabled" : ""}>
            ⏹ Stop All
          </button>
          <div class="controls-right">
            ${last_scan_time ? `<span class="text-secondary text-sm">Last scan: ${this.formatRelativeTime(last_scan_time)}</span>` : ""}
          </div>
        </div>
      </div>

      <!-- Loop Status Grid -->
      <div class="section">
        <div class="section-title">🔄 Analysis Loops</div>
        <div class="grid-auto">
          ${loopsList.length > 0 ? loopsList.map((loop) => this.getLoopCardHtml(loop)).join("") : this.getEmptyStateHtml("🔄", "No loops configured")}
        </div>
      </div>

      <!-- Findings Table -->
      <div class="section">
        <div class="section-title">📋 Findings (${this.findings.length}${totalFindings > this.findings.length ? ` of ${totalFindings}` : ""})</div>
        ${this.getFiltersHtml()}
        <div class="table-container">
          ${this.findings.length > 0 ? this.getFindingsTableHtml() : this.getEmptyStateHtml("✓", "No findings match your filters")}
        </div>
        ${this.findings.length >= this.findingsLimit ? `
          <div class="section-actions">
            <button class="btn btn-sm" data-action="loadMoreFindings">Load More</button>
          </div>
        ` : ""}
      </div>

      <!-- Severity Breakdown -->
      ${stats && totalFindings > 0 ? this.getSeverityBreakdownHtml(stats) : ""}
    `;
  }

  private getLoopCardHtml(loop: LoopStatus): string {
    const statusIcon = this.getLoopStatusIcon(loop.status);
    const statusClass = this.getLoopStatusClass(loop.status);
    const progress = loop.max_iterations > 0
      ? Math.round((loop.iteration / loop.max_iterations) * 100)
      : 0;
    const borderColor = loop.status === "running" ? "blue" : loop.status === "done" ? "green" : loop.status === "error" ? "red" : "";

    return `
      <div class="card loop-card ${statusClass}" data-loop="${loop.name}">
        <div class="card-header">
          <div class="card-icon ${borderColor || "purple"}">${this.getLoopEmoji(loop.name)}</div>
          <div>
            <div class="card-title">${this.escapeHtml(loop.display_name)}</div>
            <div class="card-subtitle">${statusIcon} ${loop.status}</div>
          </div>
        </div>
        <div class="card-content">${this.escapeHtml(loop.description)}</div>
        <div class="progress-bar my-12">
          <div class="progress-fill ${borderColor || "purple"}" style="width: ${progress}%"></div>
        </div>
        <div class="loop-stats">
          <span class="badge">${loop.iteration}/${loop.max_iterations} iterations</span>
          <span class="badge ${loop.findings_count > 0 ? "badge-warning" : ""}">${loop.findings_count} found</span>
        </div>
        <div class="card-actions">
          <button class="btn btn-xs btn-primary" data-action="runLoop" data-loop="${loop.name}" title="Run" ${loop.status === "running" ? "disabled" : ""}>▶ Run</button>
          <button class="btn btn-xs btn-danger" data-action="stopLoop" data-loop="${loop.name}" title="Stop" ${loop.status !== "running" ? "disabled" : ""}>⏹ Stop</button>
        </div>
      </div>
    `;
  }

  private getLoopEmoji(loopName: string): string {
    const emojis: Record<string, string> = {
      leaky: "💧",
      zombie: "🧟",
      racer: "🏎️",
      ghost: "👻",
      copycat: "📋",
      sloppy: "🤖",
      tangled: "🕸️",
      leaker: "🔓",
      swallower: "🕳️",
      drifter: "🌊",
    };
    return emojis[loopName] || "🔄";
  }

  private getLoopStatusIcon(status: string): string {
    switch (status) {
      case "running": return "⟳";
      case "done": return "✓";
      case "stopped": return "⏹";
      case "error": return "✕";
      default: return "○";
    }
  }

  private getLoopStatusClass(status: string): string {
    switch (status) {
      case "running": return "running";
      case "done": return "done";
      case "stopped": return "stopped";
      case "error": return "error";
      default: return "idle";
    }
  }

  private getFiltersHtml(): string {
    const severities = ["all", "critical", "high", "medium", "low"];
    const statuses = ["all", "open", "acknowledged", "fixed", "false_positive"];
    const loops = this.state?.priority_order || [];

    return `
      <div class="controls mb-12">
        <select data-filter="loop">
          <option value="">All Loops</option>
          ${loops.map((l) => `<option value="${l}" ${this.filter.loop === l ? "selected" : ""}>${this.getLoopEmoji(l)} ${l.toUpperCase()}</option>`).join("")}
        </select>
        <select data-filter="severity">
          ${severities.map((s) => `<option value="${s === "all" ? "" : s}" ${this.filter.severity === (s === "all" ? "" : s) ? "selected" : ""}>${s === "all" ? "All Severities" : this.getSeverityIcon(s) + " " + s.charAt(0).toUpperCase() + s.slice(1)}</option>`).join("")}
        </select>
        <select data-filter="status">
          ${statuses.map((s) => `<option value="${s === "all" ? "" : s}" ${this.filter.status === (s === "all" ? "" : s) ? "selected" : ""}>${s === "all" ? "All Statuses" : s.charAt(0).toUpperCase() + s.slice(1).replace("_", " ")}</option>`).join("")}
        </select>
      </div>
    `;
  }

  private getFindingsTableHtml(): string {
    return `
      <table class="table slop-findings-table">
        <thead>
          <tr>
            <th class="col-severity">Severity</th>
            <th class="col-loop">Loop</th>
            <th class="col-file">File</th>
            <th>Description</th>
            <th class="col-status">Status</th>
            <th class="col-actions">Actions</th>
          </tr>
        </thead>
        <tbody>
          ${this.findings.map((f) => this.getFindingRowHtml(f)).join("")}
        </tbody>
      </table>
    `;
  }

  private getFindingRowHtml(finding: SlopFinding): string {
    const severityIcon = this.getSeverityIcon(finding.severity);
    const statusIcon = this.getStatusIcon(finding.status);
    const severityBadgeClass = finding.severity === "critical" ? "badge-error" :
                               finding.severity === "high" ? "badge-warning" :
                               finding.severity === "medium" ? "badge-info" : "badge-success";

    return `
      <tr data-finding-id="${finding.id}">
        <td>
          <span class="badge ${severityBadgeClass}">${severityIcon} ${finding.severity}</span>
        </td>
        <td>
          <span class="badge">${this.getLoopEmoji(finding.loop)} ${finding.loop}</span>
        </td>
        <td>
          <a href="#" class="link" data-action="openFile" data-file="${this.escapeHtml(finding.file)}" data-line="${finding.line}">
            ${this.escapeHtml(this.truncatePath(finding.file))}:${finding.line}
          </a>
        </td>
        <td>
          <div class="text-primary" title="${this.escapeHtml(finding.description)}">
            ${this.escapeHtml(this.truncateText(finding.description, 80))}
          </div>
          ${finding.suggestion ? `<div class="text-secondary text-sm" title="${this.escapeHtml(finding.suggestion)}">💡 ${this.escapeHtml(this.truncateText(finding.suggestion, 60))}</div>` : ""}
        </td>
        <td>
          <span class="badge ${finding.status === "open" ? "badge-warning" : finding.status === "fixed" ? "badge-success" : ""}">${statusIcon} ${finding.status}</span>
        </td>
        <td>
          ${finding.status === "open" ? `
            <div class="btn-group">
              <button class="btn btn-xs btn-success" data-action="acknowledge" data-id="${finding.id}" title="Acknowledge">✓</button>
              <button class="btn btn-xs" data-action="markFixed" data-id="${finding.id}" title="Mark Fixed">🔧</button>
              <button class="btn btn-xs btn-danger" data-action="markFalsePositive" data-id="${finding.id}" title="False Positive">✕</button>
            </div>
          ` : `<span class="text-secondary text-sm">${finding.status}</span>`}
        </td>
      </tr>
    `;
  }

  private getSeverityIcon(severity: string): string {
    switch (severity) {
      case "critical": return "🔴";
      case "high": return "🟠";
      case "medium": return "🟡";
      case "low": return "🟢";
      default: return "⚪";
    }
  }

  private getStatusIcon(status: string): string {
    switch (status) {
      case "open": return "○";
      case "acknowledged": return "◐";
      case "fixed": return "✓";
      case "false_positive": return "✕";
      default: return "○";
    }
  }

  private getSeverityBreakdownHtml(stats: SlopStats): string {
    const severities = ["critical", "high", "medium", "low"];
    const total = stats.total || 1;
    const colors: Record<string, string> = {
      critical: "red",
      high: "orange",
      medium: "cyan",
      low: "green"
    };

    return `
      <div class="section">
        <div class="section-title">📊 Severity Breakdown</div>
        <div class="severity-breakdown">
          ${severities.map((s) => {
            const count = stats.by_severity?.[s] || 0;
            const pct = Math.round((count / total) * 100);
            return `
              <div class="severity-row">
                <span class="severity-label">${this.getSeverityIcon(s)} ${s.charAt(0).toUpperCase() + s.slice(1)}</span>
                <div class="progress-bar flex-1">
                  <div class="progress-fill ${colors[s]}" style="width: ${pct}%"></div>
                </div>
                <span class="severity-count">${count} (${pct}%)</span>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  private truncatePath(path: string): string {
    const parts = path.split("/");
    if (parts.length <= 3) return path;
    return ".../" + parts.slice(-2).join("/");
  }

  private truncateText(text: string, maxLength: number): string {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  /**
   * Generate error state HTML with retry button
   */
  private getErrorWithRetryHtml(): string {
    const retryInfo = this.loadRetryCount > 0
      ? `<div class="error-retry-info">Attempt ${this.loadRetryCount}/${this.maxRetries}</div>`
      : "";

    return `
      <div class="error-state">
        <div class="error-state-icon">⚠️</div>
        <div class="error-state-title">Failed to load Slop data</div>
        <div class="error-state-message">${this.escapeHtml(this.lastError || "Unknown error")}</div>
        ${retryInfo}
        <div class="error-state-actions">
          <button class="btn btn-sm btn-primary" data-action="retryLoad">🔄 Retry</button>
        </div>
        <div class="error-state-hint">
          Check if the Slop daemon is running: <code>systemctl --user status bot-slop.service</code>
        </div>
      </div>
    `;
  }

  getStyles(): string {
    return `
      /* Loop card customizations */
      .loop-card {
        min-width: 240px;
      }
      .loop-card.running {
        border-color: var(--info);
        box-shadow: 0 0 8px rgba(59, 130, 246, 0.3);
      }
      .loop-card.done {
        border-color: var(--success);
      }
      .loop-card.error {
        border-color: var(--error);
      }
      .loop-stats {
        display: flex;
        gap: 8px;
        margin-bottom: 8px;
      }

      /* Progress fill colors for severity breakdown */
      .progress-fill.red { background: var(--error); }
      .progress-fill.orange { background: var(--warning); }
      .progress-fill.cyan { background: var(--cyan); }
      .progress-fill.green { background: var(--success); }
      .progress-fill.blue { background: var(--info); }
      .progress-fill.purple { background: var(--purple); }

      /* Severity breakdown */
      .severity-breakdown {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .severity-row {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .severity-label {
        width: 100px;
        font-size: 0.85rem;
        font-weight: 500;
      }
      .severity-count {
        width: 80px;
        text-align: right;
        font-size: 0.85rem;
        color: var(--text-secondary);
      }

      /* Table container for scrolling */
      .table-container {
        overflow-x: auto;
        margin: 0 -16px;
        padding: 0 16px;
      }

      /* Button group for actions */
      .btn-group {
        display: flex;
        gap: 4px;
      }

      /* Text utilities */
      .text-primary { color: var(--text-primary); }
      .text-secondary { color: var(--text-secondary); }
      .text-sm { font-size: 0.8rem; }

      /* Link styling */
      .link {
        color: var(--accent);
        text-decoration: none;
      }
      .link:hover {
        text-decoration: underline;
      }

      /* Error state styling */
      .error-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 48px 24px;
        text-align: center;
        gap: 12px;
      }
      .error-state-icon {
        font-size: 48px;
        opacity: 0.8;
      }
      .error-state-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: var(--error);
      }
      .error-state-message {
        font-size: 0.9rem;
        color: var(--text-secondary);
        max-width: 400px;
        word-break: break-word;
      }
      .error-retry-info {
        font-size: 0.8rem;
        color: var(--text-secondary);
        opacity: 0.7;
      }
      .error-state-actions {
        margin-top: 8px;
      }
      .error-state-hint {
        margin-top: 16px;
        font-size: 0.8rem;
        color: var(--text-secondary);
        opacity: 0.7;
      }
      .error-state-hint code {
        background: var(--bg-secondary);
        padding: 2px 6px;
        border-radius: 4px;
        font-family: monospace;
      }
    `;
  }

  getScript(): string {
    // Use centralized event delegation system - handlers survive content updates
    return `
      (function() {
        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('slop', function(action, element, e) {
          switch(action) {
            case 'scanNow':
              vscode.postMessage({ command: 'slopScanNow' });
              break;
            case 'stopAll':
              vscode.postMessage({ command: 'slopStopAll' });
              break;
            case 'runLoop':
              if (element.dataset.loop) {
                vscode.postMessage({ command: 'slopRunLoop', loop: element.dataset.loop });
              }
              break;
            case 'stopLoop':
              if (element.dataset.loop) {
                vscode.postMessage({ command: 'slopStopLoop', loop: element.dataset.loop });
              }
              break;
            case 'openFile':
              e.preventDefault();
              vscode.postMessage({
                command: 'openFile',
                file: element.dataset.file,
                line: parseInt(element.dataset.line || '0')
              });
              break;
            case 'acknowledge':
              if (element.dataset.id) {
                vscode.postMessage({ command: 'slopAcknowledge', findingId: element.dataset.id });
              }
              break;
            case 'markFixed':
              if (element.dataset.id) {
                vscode.postMessage({ command: 'slopMarkFixed', findingId: element.dataset.id });
              }
              break;
            case 'markFalsePositive':
              if (element.dataset.id) {
                vscode.postMessage({ command: 'slopMarkFalsePositive', findingId: element.dataset.id });
              }
              break;
            case 'loadMoreFindings':
              vscode.postMessage({ command: 'slopLoadMoreFindings' });
              break;
            case 'retryLoad':
              vscode.postMessage({ command: 'slopRetryLoad' });
              break;
          }
        });

        // Register change handler for filter selects
        TabEventDelegation.registerChangeHandler('slop', function(element, e) {
          if (element.matches('select[data-filter]')) {
            vscode.postMessage({
              command: 'slopFilterChange',
              filter: element.dataset.filter,
              value: element.value
            });
          }
        });
      })();
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "slopScanNow":
        await this.scanNow();
        return true;

      case "slopStopAll":
        await this.stopAll();
        return true;

      case "slopRunLoop":
        await this.runLoop(message.loop);
        return true;

      case "slopStopLoop":
        await this.stopLoop(message.loop);
        return true;

      case "slopFilterChange":
        this.filter[message.filter as keyof typeof this.filter] = message.value || undefined;
        await this.refresh();
        return true;

      case "slopAcknowledge":
        await this.acknowledgeFinding(message.findingId);
        return true;

      case "slopMarkFixed":
        await this.markFixed(message.findingId);
        return true;

      case "slopMarkFalsePositive":
        await this.markFalsePositive(message.findingId);
        return true;

      case "slopLoadMoreFindings":
        this.findingsLimit += 50;
        await this.refresh();
        return true;

      case "slopRetryLoad":
        this.loadRetryCount = 0;
        this.lastError = null;
        await this.refresh();
        return true;

      default:
        return false;
    }
  }

  private async scanNow(): Promise<void> {
    const result = await dbus.slop_scanNow();
    if (!result.success) {
      logger.error(`Failed to start scan: ${result.error}`);
    }
    await this.refresh();
  }

  private async stopAll(): Promise<void> {
    const result = await dbus.slop_stopAll();
    if (!result.success) {
      logger.error(`Failed to stop all: ${result.error}`);
    }
    await this.refresh();
  }

  private async runLoop(loopName: string): Promise<void> {
    const result = await dbus.slop_runLoops([loopName]);
    if (!result.success) {
      logger.error(`Failed to run loop: ${result.error}`);
    }
    await this.refresh();
  }

  private async stopLoop(loopName: string): Promise<void> {
    const result = await dbus.slop_stopLoop(loopName);
    if (!result.success) {
      logger.error(`Failed to stop loop: ${result.error}`);
    }
    await this.refresh();
  }

  private async acknowledgeFinding(findingId: string): Promise<void> {
    const result = await dbus.slop_acknowledge(findingId);
    if (!result.success) {
      logger.error(`Failed to acknowledge: ${result.error}`);
    }
    await this.refresh();
  }

  private async markFixed(findingId: string): Promise<void> {
    const result = await dbus.slop_markFixed(findingId);
    if (!result.success) {
      logger.error(`Failed to mark fixed: ${result.error}`);
    }
    await this.refresh();
  }

  private async markFalsePositive(findingId: string): Promise<void> {
    const result = await dbus.slop_markFalsePositive(findingId);
    if (!result.success) {
      logger.error(`Failed to mark false positive: ${result.error}`);
    }
    await this.refresh();
  }
}
