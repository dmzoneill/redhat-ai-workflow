/**
 * Cron Tab
 *
 * Displays cron job status, schedule, and execution history.
 * Uses D-Bus to communicate with the Cron daemon.
 */

import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";

const logger = createLogger("CronTab");

interface CronJob {
  name: string;
  description?: string;
  skill: string;
  cron?: string;           // Cron expression (e.g., "0 9 * * 1-5")
  trigger?: string;        // "cron" or "poll"
  persona?: string;        // Persona to use for execution
  enabled: boolean;
  next_run?: string;
  last_status?: "success" | "failed" | "running";
  last_duration_ms?: number;
}

interface CronHistoryEntry {
  id?: string;
  job_name: string;
  skill: string;
  timestamp: string;
  success: boolean;
  duration_ms: number;
  error?: string | null;
  output_preview?: string;
  session_name?: string;
}

interface CronState {
  enabled: boolean;
  timezone: string;
  execution_mode: string;
  jobs: CronJob[];
  history: CronHistoryEntry[];
  total_history: number;
  updated_at?: string;
}

export class CronTab extends BaseTab {
  private state: CronState | null = null;
  private historyLimit = 20;

  constructor() {
    super({
      id: "cron",
      label: "Cron",
      icon: "⏰",
    });
  }

  getBadge(): { text: string; class?: string } | null {
    if (!this.state) return null;

    const runningJobs = this.state.jobs.filter(
      (j) => j.last_status === "running"
    ).length;
    if (runningJobs > 0) {
      return { text: `${runningJobs}`, class: "running" };
    }

    const enabledJobs = this.state.jobs.filter((j) => j.enabled).length;
    if (enabledJobs > 0) {
      return { text: `${enabledJobs}`, class: "" };
    }

    return null;
  }

  async loadData(): Promise<void> {
    try {
      const result = await dbus.cron_getState();
      if (result.success && result.data) {
        const data = result.data as any;
        this.state = data.state || data;
      }
    } catch (error) {
      logger.error("Error loading data", error);
      this.state = null;
    }
  }

  getContent(): string {
    if (!this.state) {
      return this.getLoadingHtml("Loading cron data...");
    }

    const { enabled, timezone, jobs, history } = this.state;
    const enabledJobs = jobs.filter((j) => j.enabled).length;
    const successRate = this.calculateSuccessRate();

    return `
      <!-- Scheduler Status -->
      <div class="section">
        <div class="section-title">⏰ Scheduler Status</div>
        <div class="grid-4">
          <div class="stat-card ${enabled ? "green" : "red"}">
            <div class="stat-icon">${enabled ? "▶" : "⏸"}</div>
            <div class="stat-value">${enabled ? "Running" : "Paused"}</div>
            <div class="stat-label">Status</div>
          </div>
          <div class="stat-card blue">
            <div class="stat-icon">📋</div>
            <div class="stat-value">${enabledJobs}/${jobs.length}</div>
            <div class="stat-label">Active Jobs</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">📊</div>
            <div class="stat-value">${successRate}%</div>
            <div class="stat-label">Success Rate</div>
          </div>
          <div class="stat-card cyan">
            <div class="stat-icon">🌍</div>
            <div class="stat-value">${timezone || "Local"}</div>
            <div class="stat-label">Timezone</div>
          </div>
        </div>
      </div>

      <!-- Scheduler Controls -->
      <div class="section">
        <div class="cron-controls">
          <button class="btn btn-xs ${enabled ? "btn-danger" : "btn-success"}" data-action="toggleScheduler">
            ${enabled ? "⏸ Pause Scheduler" : "▶ Start Scheduler"}
          </button>
        </div>
      </div>

      <!-- Cron Jobs -->
      <div class="section">
        <div class="section-title">📋 Scheduled Jobs</div>
        <div class="cron-jobs-list">
          ${jobs.length > 0 ? jobs.map((job) => this.getCronJobHtml(job)).join("") : this.getEmptyStateHtml("📋", "No cron jobs configured")}
        </div>
      </div>

      <!-- Execution History -->
      <div class="section">
        <div class="section-title">📜 Execution History</div>
        <div class="cron-history-list">
          ${history.length > 0 ? history.slice(0, this.historyLimit).map((entry) => this.getHistoryEntryHtml(entry)).join("") : this.getEmptyStateHtml("📜", "No execution history")}
        </div>
        ${history.length > this.historyLimit ? `
          <div class="section-actions">
            <button class="btn btn-xs" data-action="loadMoreHistory">Load More</button>
          </div>
        ` : ""}
      </div>
    `;
  }

  private getCronJobHtml(job: CronJob): string {
    const statusIcon = job.last_status === "success" ? "✓" : job.last_status === "failed" ? "✕" : job.last_status === "running" ? "⟳" : "○";
    const statusClass = job.last_status === "success" ? "success" : job.last_status === "failed" ? "failed" : job.last_status === "running" ? "running" : "pending";

    // Format schedule display - show cron expression or trigger type
    const scheduleDisplay = job.cron
      ? this.formatCronExpression(job.cron)
      : job.trigger === "poll" ? "Poll-based" : "No schedule";

    return `
      <div class="cron-job-item ${!job.enabled ? "disabled" : ""}">
        <div class="cron-job-status ${statusClass}">${statusIcon}</div>
        <div class="cron-job-info">
          <div class="cron-job-name">${this.escapeHtml(job.name)}</div>
          <div class="cron-job-details">
            <span class="cron-job-skill">⚡ ${this.escapeHtml(job.skill)}</span>
            ${job.persona ? this.getPersonaBadgeHtml(job.persona) : ""}
          </div>
          <div class="cron-job-schedule-row">
            <span class="cron-job-schedule" title="${job.cron || ''}">🕐 ${this.escapeHtml(scheduleDisplay)}</span>
          </div>
        </div>
        <div class="cron-job-timing">
          ${job.next_run ? `<div class="cron-job-next">Next: ${this.formatRelativeTime(job.next_run)}</div>` : ""}
        </div>
        <div class="cron-job-actions">
          <button class="btn btn-xs btn-icon" data-action="runCronJobNow" data-job="${job.name}" title="Run Now">▶</button>
          <label class="toggle-switch">
            <input type="checkbox" ${job.enabled ? "checked" : ""} data-action="toggleCronJob" data-job="${job.name}" />
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
    `;
  }

  private formatCronExpression(cron: string): string {
    // Parse common cron patterns into human-readable format
    const parts = cron.trim().split(/\s+/);
    if (parts.length < 5) return cron;

    const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

    // Common patterns
    if (minute === "0" && hour === "9" && dayOfMonth === "*" && month === "*" && dayOfWeek === "1-5") {
      return "Weekdays at 9:00 AM";
    }
    if (minute === "0" && hour === "17" && dayOfMonth === "*" && month === "*" && dayOfWeek === "1-5") {
      return "Weekdays at 5:00 PM";
    }
    if (minute === "0" && hour === "8" && dayOfMonth === "*" && month === "*" && dayOfWeek === "1-5") {
      return "Weekdays at 8:00 AM";
    }
    if (minute === "0" && hour === "18" && dayOfMonth === "*" && month === "*" && dayOfWeek === "1-5") {
      return "Weekdays at 6:00 PM";
    }
    if (minute === "0" && hour === "0" && dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
      return "Daily at midnight";
    }
    if (minute === "0" && dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
      return `Daily at ${hour}:00`;
    }
    if (minute === "0" && dayOfMonth === "1" && month === "*" && dayOfWeek === "*") {
      return `Monthly on 1st at ${hour}:00`;
    }
    if (minute === "*/30" && hour === "*") {
      return "Every 30 minutes";
    }
    if (minute === "*/15" && hour === "*") {
      return "Every 15 minutes";
    }
    if (minute === "0" && hour === "*/3") {
      return "Every 3 hours";
    }
    if (minute === "0" && hour === "*/6") {
      return "Every 6 hours";
    }

    // For other patterns, show a simplified version
    const hourStr = hour === "*" ? "every hour" : `at ${hour}:${minute.padStart(2, "0")}`;
    const dayStr = dayOfWeek === "1-5" ? "weekdays" : dayOfWeek === "*" ? "" : `on day ${dayOfWeek}`;

    return `${hourStr} ${dayStr}`.trim() || cron;
  }

  private getHistoryEntryHtml(entry: CronHistoryEntry): string {
    const statusIcon = entry.success ? "✓" : "✕";
    const statusClass = entry.success ? "success" : "failed";
    const duration = this.formatDuration(entry.duration_ms);

    // Show full output preview (already truncated to 500 chars by daemon)
    const outputPreview = entry.output_preview || "";

    return `
      <div class="cron-history-item ${statusClass}" data-entry-id="${entry.id || ''}">
        <div class="cron-history-status ${statusClass}">${statusIcon}</div>
        <div class="cron-history-info">
          <div class="cron-history-header">
            <span class="cron-history-job">${this.escapeHtml(entry.job_name)}</span>
            <span class="cron-history-skill">⚡ ${this.escapeHtml(entry.skill)}</span>
            ${entry.session_name ? `<span class="cron-history-session">📋 ${this.escapeHtml(entry.session_name)}</span>` : ""}
          </div>
          ${outputPreview ? `
            <div class="cron-history-output" title="${this.escapeHtml(entry.output_preview || '')}">
              ${this.escapeHtml(outputPreview)}
            </div>
          ` : ""}
          ${entry.error ? `
            <div class="cron-history-error-msg">
              ❌ ${this.escapeHtml(entry.error.length > 80 ? entry.error.substring(0, 80) + "..." : entry.error)}
            </div>
          ` : ""}
        </div>
        <div class="cron-history-timing">
          <div class="cron-history-time">${this.formatRelativeTime(entry.timestamp)}</div>
          <div class="cron-history-duration">${duration}</div>
        </div>
      </div>
    `;
  }

  private calculateSuccessRate(): number {
    if (!this.state || this.state.history.length === 0) return 100;
    const successful = this.state.history.filter((h) => h.success).length;
    return Math.round((successful / this.state.history.length) * 100);
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return `
      // Toggle scheduler
      document.querySelectorAll('[data-action="toggleScheduler"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'toggleScheduler' });
        });
      });

      // Refresh cron
      document.querySelectorAll('[data-action="refreshCron"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'refreshCron' });
        });
      });

      // Run job now
      document.querySelectorAll('[data-action="runCronJobNow"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const jobName = btn.dataset.job;
          if (jobName) {
            vscode.postMessage({ command: 'runCronJobNow', jobName });
          }
        });
      });

      // Toggle job enabled
      document.querySelectorAll('[data-action="toggleCronJob"]').forEach(input => {
        input.addEventListener('change', () => {
          const jobName = input.dataset.job;
          if (jobName) {
            vscode.postMessage({ command: 'toggleCronJob', jobName, enabled: input.checked });
          }
        });
      });

      // Load more history
      document.querySelectorAll('[data-action="loadMoreHistory"]').forEach(btn => {
        btn.addEventListener('click', () => {
          vscode.postMessage({ command: 'loadMoreCronHistory', limit: 50 });
        });
      });
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "toggleScheduler":
        await this.toggleScheduler();
        return true;

      case "refreshCron":
        await this.refresh();
        return true;

      case "toggleCronJob":
        await this.toggleCronJob(message.jobName, message.enabled);
        return true;

      case "runCronJobNow":
        await this.runCronJobNow(message.jobName);
        return true;

      case "loadMoreCronHistory":
        this.historyLimit = message.limit || 50;
        await this.refresh();
        return true;

      default:
        return false;
    }
  }

  private async toggleScheduler(): Promise<void> {
    if (!this.state) return;

    const result = await dbus.cron_toggleScheduler(!this.state.enabled);

    if (!result.success) {
      logger.error(`Failed to toggle scheduler: ${result.error}`);
    }

    await this.refresh();
  }

  private async toggleCronJob(jobName: string, enabled: boolean): Promise<void> {
    const result = await dbus.cron_toggleJob(jobName, enabled);
    if (!result.success) {
      logger.error(`Failed to toggle job: ${result.error}`);
    }
    await this.refresh();
  }

  private async runCronJobNow(jobName: string): Promise<void> {
    const result = await dbus.cron_runJob(jobName);
    if (!result.success) {
      logger.error(`Failed to run job: ${result.error}`);
    }
    await this.refresh();
  }
}
