/**
 * Overview Tab
 *
 * Displays agent stats, current work, and system overview.
 */

import { BaseTab, TabConfig, dbus } from "./BaseTab";
import { createLogger } from "../logger";

const logger = createLogger("OverviewTab");

interface AgentStats {
  lifetime: {
    tool_calls: number;
    tool_successes: number;
    tool_failures: number;
    skill_executions: number;
    skill_successes: number;
    skill_failures: number;
    memory_reads: number;
    memory_writes: number;
    lines_written: number;
    sessions: number;
  };
  current_session: {
    started: string;
    tool_calls: number;
    skill_executions: number;
    memory_ops: number;
  };
  daily: Record<string, { tool_calls: number; skill_executions: number; sessions?: number }>;
}

interface CurrentWork {
  activeIssue: { key: string; summary: string; status: string } | null;
  activeMR: { id: number; title: string; project: string } | null;
  followUps: Array<{ task: string; priority: string }>;
  sprintIssues: Array<{ key: string; summary: string; status: string }>;
  activeRepo: string | null;
  totalActiveIssues: number;
  totalActiveMRs: number;
}

export class OverviewTab extends BaseTab {
  private stats: AgentStats | null = null;
  private currentWork: CurrentWork | null = null;
  private toolSuccessRate = 100;
  private skillSuccessRate = 100;
  private dailyHistory: Array<{
    date: string;
    tool_calls: number;
    skill_executions: number;
    sessions: number;
  }> = [];

  constructor() {
    super({
      id: "overview",
      label: "Overview",
      icon: "📊",
    });
  }

  async loadData(): Promise<void> {
    try {
      // Load agent stats via D-Bus - use stats_getAgentStats, not stats_getState
      const statsResult = await dbus.stats_getAgentStats();
      if (statsResult.success && statsResult.data) {
        // The response has { stats: AgentStats } structure
        const data = statsResult.data as any;
        this.stats = data.stats || data;
        this.calculateRates();
        this.buildDailyHistory();
      }

      // Load current work via D-Bus
      const workResult = await dbus.memory_getCurrentWork();
      if (workResult.success && workResult.data) {
        const data = workResult.data as any;
        const work = data.work || data.current_work || data;
        this.currentWork = {
          activeIssue: work?.activeIssue || work?.active_issue || null,
          activeMR: work?.activeMR || work?.active_mr || null,
          followUps: work?.followUps || work?.follow_ups || [],
          sprintIssues: work?.sprintIssues || work?.sprint_issues || [],
          activeRepo: work?.repo || work?.active_repo || null,
          totalActiveIssues: work?.activeIssues?.length || work?.active_issues?.length || 0,
          totalActiveMRs: work?.openMRs?.length || work?.open_mrs?.length || 0,
        };
      }
    } catch (error) {
      logger.error("Error loading data", error);
      // Don't throw - allow other tabs to load even if this one fails
    }
  }

  private calculateRates(): void {
    if (!this.stats?.lifetime) return;

    const lifetime = this.stats.lifetime;
    this.toolSuccessRate =
      (lifetime.tool_calls ?? 0) > 0
        ? Math.round(((lifetime.tool_successes ?? 0) / lifetime.tool_calls) * 100)
        : 100;
    this.skillSuccessRate =
      (lifetime.skill_executions ?? 0) > 0
        ? Math.round(((lifetime.skill_successes ?? 0) / lifetime.skill_executions) * 100)
        : 100;
  }

  private buildDailyHistory(): void {
    this.dailyHistory = [];
    if (!this.stats?.daily) return;

    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dateKey = d.toISOString().split("T")[0];
      const dayStats = this.stats.daily[dateKey];
      this.dailyHistory.push({
        date: dateKey,
        tool_calls: dayStats?.tool_calls ?? 0,
        skill_executions: dayStats?.skill_executions ?? 0,
        sessions: dayStats?.sessions ?? 0,
      });
    }
  }

  getContent(): string {
    const lifetime = this.stats?.lifetime || {
      tool_calls: 0,
      tool_successes: 0,
      skill_executions: 0,
      memory_reads: 0,
      memory_writes: 0,
      lines_written: 0,
      sessions: 0,
    };

    const session = this.stats?.current_session || {
      started: "",
      tool_calls: 0,
      skill_executions: 0,
      memory_ops: 0,
    };

    const today = new Date().toISOString().split("T")[0];
    const todayStats = this.stats?.daily?.[today] || {
      tool_calls: 0,
      skill_executions: 0,
    };

    return `
      <!-- Quick Stats -->
      <div class="section">
        <div class="section-title">📊 Quick Stats</div>
        <div class="grid-4">
          <div class="stat-card purple">
            <div class="stat-icon">🔧</div>
            <div class="stat-value">${lifetime.tool_calls.toLocaleString()}</div>
            <div class="stat-label">Tool Calls</div>
            <div class="stat-sub">${this.toolSuccessRate}% success</div>
          </div>
          <div class="stat-card cyan">
            <div class="stat-icon">⚡</div>
            <div class="stat-value">${lifetime.skill_executions.toLocaleString()}</div>
            <div class="stat-label">Skills Run</div>
            <div class="stat-sub">${this.skillSuccessRate}% success</div>
          </div>
          <div class="stat-card pink">
            <div class="stat-icon">🧠</div>
            <div class="stat-value">${(lifetime.memory_reads + lifetime.memory_writes).toLocaleString()}</div>
            <div class="stat-label">Memory Ops</div>
            <div class="stat-sub">${lifetime.memory_reads} reads, ${lifetime.memory_writes} writes</div>
          </div>
          <div class="stat-card orange">
            <div class="stat-icon">💬</div>
            <div class="stat-value">${lifetime.sessions.toLocaleString()}</div>
            <div class="stat-label">Sessions</div>
            <div class="stat-sub">${lifetime.lines_written.toLocaleString()} lines written</div>
          </div>
        </div>
      </div>

      <!-- Today's Activity -->
      <div class="section">
        <div class="section-title">📅 Today's Activity</div>
        <div class="grid-3">
          <div class="stat-card green">
            <div class="stat-icon">🔧</div>
            <div class="stat-value">${todayStats.tool_calls}</div>
            <div class="stat-label">Tool Calls Today</div>
          </div>
          <div class="stat-card blue">
            <div class="stat-icon">⚡</div>
            <div class="stat-value">${todayStats.skill_executions}</div>
            <div class="stat-label">Skills Today</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-icon">⏱️</div>
            <div class="stat-value">${session.tool_calls}</div>
            <div class="stat-label">This Session</div>
            <div class="stat-sub">${session.started ? "Started " + this.formatRelativeTime(session.started) : "No active session"}</div>
          </div>
        </div>
      </div>

      <!-- Current Work -->
      <div class="section">
        <div class="section-title">🎯 Current Work</div>
        ${this.getCurrentWorkHtml()}
      </div>

      <!-- 7-Day History -->
      <div class="section">
        <div class="section-title">📈 7-Day History</div>
        ${this.getHistoryChartHtml()}
      </div>
    `;
  }

  private getCurrentWorkHtml(): string {
    if (!this.currentWork) {
      return this.getEmptyStateHtml("📋", "No current work loaded");
    }

    const { activeIssue, activeMR, followUps, totalActiveIssues, totalActiveMRs } = this.currentWork;

    let html = '<div class="grid-2">';

    // Active Issue
    html += '<div class="card">';
    html += '<div class="card-header"><div class="card-icon purple">📋</div><div><div class="card-title">Active Issue</div>';
    if (activeIssue) {
      html += `<div class="card-subtitle">${activeIssue.key}</div>`;
    }
    html += "</div></div>";
    if (activeIssue) {
      html += `<div class="card-content-primary">${this.escapeHtml(activeIssue.summary)}</div>`;
      html += `<div class="card-content-secondary mt-4">Status: ${activeIssue.status}</div>`;
    } else {
      html += '<div class="loading-placeholder">No active issue</div>';
    }
    if (totalActiveIssues > 1) {
      html += `<div class="card-content-more mt-8">+${totalActiveIssues - 1} more issues</div>`;
    }
    html += "</div>";

    // Active MR
    html += '<div class="card">';
    html += '<div class="card-header"><div class="card-icon cyan">🔀</div><div><div class="card-title">Active MR</div>';
    if (activeMR) {
      html += `<div class="card-subtitle">!${activeMR.id}</div>`;
    }
    html += "</div></div>";
    if (activeMR) {
      html += `<div class="card-content-primary">${this.escapeHtml(activeMR.title)}</div>`;
      html += `<div class="card-content-secondary mt-4">Project: ${activeMR.project}</div>`;
    } else {
      html += '<div class="loading-placeholder">No active MR</div>';
    }
    if (totalActiveMRs > 1) {
      html += `<div class="card-content-more mt-8">+${totalActiveMRs - 1} more MRs</div>`;
    }
    html += "</div>";

    html += "</div>";

    // Follow-ups
    if (followUps.length > 0) {
      html += '<div class="card mt-16">';
      html += '<div class="card-header"><div class="card-icon orange">📝</div><div class="card-title">Follow-ups</div></div>';
      html += '<div class="follow-up-list">';
      followUps.slice(0, 5).forEach((fu) => {
        html += `<div class="follow-up-item">
          <span class="follow-up-priority">${fu.priority === "high" ? "🔴" : fu.priority === "medium" ? "🟡" : "🟢"}</span>
          <span>${this.escapeHtml(fu.task)}</span>
        </div>`;
      });
      if (followUps.length > 5) {
        html += `<div class="card-content-more">+${followUps.length - 5} more</div>`;
      }
      html += "</div></div>";
    }

    return html;
  }

  private getHistoryChartHtml(): string {
    const maxToolCalls = Math.max(...this.dailyHistory.map((d) => d.tool_calls), 1);

    let barsHtml = "";
    this.dailyHistory.forEach((day, idx) => {
      const height = Math.max(4, (day.tool_calls / maxToolCalls) * 80);
      const isToday = idx === this.dailyHistory.length - 1;
      const dayLabel = new Date(day.date).toLocaleDateString("en-US", { weekday: "short" });

      barsHtml += `
        <div class="history-bar-container">
          <div class="history-bar-value">${day.tool_calls}</div>
          <div class="history-bar ${isToday ? "today" : ""}" style="height: ${height}px;" title="${day.date}: ${day.tool_calls} tool calls, ${day.skill_executions} skills"></div>
          <div class="history-bar-label">${dayLabel}</div>
        </div>
      `;
    });

    return `
      <div class="history-chart">
        ${barsHtml}
      </div>
      <div class="history-legend">
        <div class="history-legend-item">
          <span class="legend-dot purple"></span>
          <span>Tool Calls</span>
        </div>
      </div>
    `;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }
}
