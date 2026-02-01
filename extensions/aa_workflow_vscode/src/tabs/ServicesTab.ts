/**
 * Services Tab
 *
 * Displays service status for all AI Workflow daemons.
 * Uses D-Bus to check daemon status and control services.
 */

import * as vscode from "vscode";
import { BaseTab, TabConfig, dbus } from "./BaseTab";
import { execAsync } from "../utils";
import { createLogger } from "../logger";

const logger = createLogger("ServicesTab");

interface ServiceInfo {
  name: string;
  displayName: string;
  icon: string;
  service: string;
  systemdUnit: string;
  status: "online" | "offline" | "checking" | "error";
  lastChecked?: string;
  details?: Record<string, any>;
}

interface SlackStatus {
  connected: boolean;
  channels: number;
  pendingMessages: number;
  lastMessage?: string;
}

interface OllamaInstance {
  name: string;
  url: string;
  device: string;
  status: "online" | "offline" | "checking";
  model?: string;
  vram?: number;
}

export class ServicesTab extends BaseTab {
  private services: ServiceInfo[] = [];
  private slackStatus: SlackStatus | null = null;
  private ollamaInstances: OllamaInstance[] = [];
  private onlineCount = 0;
  private offlineCount = 0;

  constructor() {
    super({
      id: "services",
      label: "Services",
      icon: "🔌",
    });

    // Initialize service list
    this.services = [
      {
        name: "sprint",
        displayName: "Sprint Bot",
        icon: "🎯",
        service: "com.aiworkflow.BotSprint",
        systemdUnit: "bot-sprint.service",
        status: "checking",
      },
      {
        name: "meet",
        displayName: "Meet Bot",
        icon: "🎥",
        service: "com.aiworkflow.BotMeet",
        systemdUnit: "bot-meet.service",
        status: "checking",
      },
      {
        name: "cron",
        displayName: "Cron Daemon",
        icon: "⏰",
        service: "com.aiworkflow.BotCron",
        systemdUnit: "bot-cron.service",
        status: "checking",
      },
      {
        name: "session",
        displayName: "Session Manager",
        icon: "💬",
        service: "com.aiworkflow.BotSession",
        systemdUnit: "bot-session.service",
        status: "checking",
      },
      {
        name: "slack",
        displayName: "Slack Bot",
        icon: "💬",
        service: "com.aiworkflow.BotSlack",
        systemdUnit: "bot-slack.service",
        status: "checking",
      },
      {
        name: "video",
        displayName: "Video Bot",
        icon: "📹",
        service: "com.aiworkflow.BotVideo",
        systemdUnit: "bot-video.service",
        status: "checking",
      },
      {
        name: "config",
        displayName: "Config Daemon",
        icon: "⚙️",
        service: "com.aiworkflow.BotConfig",
        systemdUnit: "bot-config.service",
        status: "checking",
      },
      {
        name: "memory",
        displayName: "Memory Daemon",
        icon: "🧠",
        service: "com.aiworkflow.Memory",
        systemdUnit: "bot-memory.service",
        status: "checking",
      },
      {
        name: "stats",
        displayName: "Stats Daemon",
        icon: "📊",
        service: "com.aiworkflow.BotStats",
        systemdUnit: "bot-stats.service",
        status: "checking",
      },
      {
        name: "slop",
        displayName: "Slop Bot",
        icon: "🔍",
        service: "com.aiworkflow.BotSlop",
        systemdUnit: "bot-slop.service",
        status: "checking",
      },
    ];
  }

  getBadge(): { text: string; class?: string } | null {
    if (this.offlineCount > 0) {
      return {
        text: this.offlineCount === 0 ? "●" : this.offlineCount < 3 ? "◐" : "○",
        class: `status-${this.offlineCount === 0 ? "green" : this.offlineCount < 3 ? "yellow" : "red"}`,
      };
    }
    return { text: "●", class: "status-green" };
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    try {
      // Check all daemon statuses via D-Bus
      logger.log("Calling getAllStatus()...");
      const statusResults = await dbus.getAllStatus();
      logger.log(`getAllStatus() returned: ${JSON.stringify(statusResults)}`);

      this.onlineCount = 0;
      this.offlineCount = 0;

      this.services.forEach((service) => {
        const isOnline = statusResults[service.name as keyof typeof statusResults];
        service.status = isOnline ? "online" : "offline";
        service.lastChecked = new Date().toISOString();

        if (isOnline) {
          this.onlineCount++;
        } else {
          this.offlineCount++;
        }
      });

      logger.log(`Services: ${this.onlineCount} online, ${this.offlineCount} offline`);

      // Load Slack status if available
      if (statusResults.slack) {
        logger.log("Calling slack_getStatus()...");
        const slackResult = await dbus.slack_getStatus();
        logger.log(`slack_getStatus() result: success=${slackResult.success}`);
        if (slackResult.success && slackResult.data) {
          const data = slackResult.data as any;
          this.slackStatus = {
            connected: data.connected || data.running || false,
            channels: data.channels?.length || 0,
            pendingMessages: data.pending_messages?.length || data.pending_approvals || 0,
            lastMessage: data.last_message,
          };
        }
      }
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
    }
  }

  getContent(): string {
    return `
      <!-- Service Status Summary -->
      <div class="section">
        <div class="section-title">🔌 Service Status</div>
        <div class="grid-3">
          <div class="stat-card green">
            <div class="stat-icon">✓</div>
            <div class="stat-value">${this.onlineCount}</div>
            <div class="stat-label">Online</div>
          </div>
          <div class="stat-card ${this.offlineCount > 0 ? "red" : "green"}">
            <div class="stat-icon">${this.offlineCount > 0 ? "✕" : "✓"}</div>
            <div class="stat-value">${this.offlineCount}</div>
            <div class="stat-label">Offline</div>
          </div>
          <div class="stat-card blue">
            <div class="stat-icon">⟳</div>
            <div class="stat-value">${this.services.length}</div>
            <div class="stat-label">Total</div>
          </div>
        </div>
      </div>

      <!-- Service Cards -->
      <div class="section">
        <div class="section-title">Daemons</div>
        <div class="grid-3">
          ${this.services.map((service) => this.getServiceCardHtml(service)).join("")}
        </div>
      </div>

      <!-- Slack Status -->
      ${this.slackStatus ? this.getSlackStatusHtml() : ""}

      <!-- Ollama Instances -->
      ${this.ollamaInstances.length > 0 ? this.getOllamaStatusHtml() : ""}
    `;
  }

  private getServiceCardHtml(service: ServiceInfo): string {
    const statusClass = service.status === "online" ? "online" : "offline";
    const statusText = service.status === "online" ? "Online" : "Offline";

    return `
      <div class="service-card ${service.status === "offline" ? "service-offline" : ""}">
        <div class="service-header">
          <div class="service-title">
            <span>${service.icon}</span>
            ${service.displayName}
          </div>
          <div class="service-status">
            <span class="status-dot ${statusClass}"></span>
            ${statusText}
          </div>
        </div>
        <div class="service-content">
          <div class="service-row">
            <span>Unit</span>
            <span>${service.systemdUnit}</span>
          </div>
          <div class="service-row">
            <span>Last Check</span>
            <span>${service.lastChecked ? this.formatRelativeTime(service.lastChecked) : "Never"}</span>
          </div>
        </div>
        <div class="service-actions">
          ${service.status === "online" ? `
            <button class="btn btn-xs btn-flex" data-action="restartService" data-service="${service.name}">⟳ Restart</button>
            <button class="btn btn-xs btn-danger btn-flex" data-action="stopService" data-service="${service.name}">⏹ Stop</button>
          ` : `
            <button class="btn btn-xs btn-success btn-flex" data-action="startService" data-service="${service.name}">▶ Start</button>
          `}
        </div>
      </div>
    `;
  }

  private getSlackStatusHtml(): string {
    if (!this.slackStatus) return "";

    return `
      <div class="section">
        <div class="section-title">💬 Slack Bot</div>
        <div class="service-card">
          <div class="service-header">
            <div class="service-title">
              <span>💬</span>
              Slack Integration
            </div>
            <div class="service-status">
              <span class="status-dot ${this.slackStatus.connected ? "online" : "offline"}"></span>
              ${this.slackStatus.connected ? "Connected" : "Disconnected"}
            </div>
          </div>
          <div class="service-content">
            <div class="service-row">
              <span>Channels</span>
              <span>${this.slackStatus.channels}</span>
            </div>
            <div class="service-row">
              <span>Pending Messages</span>
              <span>${this.slackStatus.pendingMessages}</span>
            </div>
            ${this.slackStatus.lastMessage ? `
              <div class="service-row">
                <span>Last Message</span>
                <span>${this.formatRelativeTime(this.slackStatus.lastMessage)}</span>
              </div>
            ` : ""}
          </div>
        </div>
      </div>
    `;
  }

  private getOllamaStatusHtml(): string {
    return `
      <div class="section">
        <div class="section-title">🤖 Ollama Instances</div>
        <div class="grid-2">
          ${this.ollamaInstances.map((instance) => `
            <div class="service-card">
              <div class="service-header">
                <div class="service-title">
                  <span>🤖</span>
                  ${instance.name}
                </div>
                <div class="service-status">
                  <span class="status-dot ${instance.status}"></span>
                  ${instance.status === "online" ? "Online" : "Offline"}
                </div>
              </div>
              <div class="service-content">
                <div class="service-row">
                  <span>URL</span>
                  <span>${instance.url}</span>
                </div>
                <div class="service-row">
                  <span>Device</span>
                  <span>${instance.device}</span>
                </div>
                ${instance.model ? `
                  <div class="service-row">
                    <span>Model</span>
                    <span>${instance.model}</span>
                  </div>
                ` : ""}
              </div>
              <div class="service-actions">
                <button class="btn btn-xs btn-flex" data-action="testOllama" data-instance="${instance.name}">🔍 Test</button>
              </div>
            </div>
          `).join("")}
        </div>
      </div>
    `;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return `
      // Service control buttons
      document.querySelectorAll('[data-action="startService"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const service = btn.dataset.service;
          if (service) {
            vscode.postMessage({ command: 'serviceControl', action: 'start', service });
          }
        });
      });

      document.querySelectorAll('[data-action="stopService"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const service = btn.dataset.service;
          if (service) {
            vscode.postMessage({ command: 'serviceControl', action: 'stop', service });
          }
        });
      });

      document.querySelectorAll('[data-action="restartService"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const service = btn.dataset.service;
          if (service) {
            vscode.postMessage({ command: 'serviceControl', action: 'restart', service });
          }
        });
      });

      document.querySelectorAll('[data-action="testOllama"]').forEach(btn => {
        btn.addEventListener('click', () => {
          const instance = btn.dataset.instance;
          if (instance) {
            vscode.postMessage({ command: 'testOllamaInstance', instance });
          }
        });
      });
    `;
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "serviceControl":
        await this.controlService(message.action, message.service);
        return true;

      case "refreshServices":
        await this.refresh();
        return true;

      case "testOllamaInstance":
        await this.testOllamaInstance(message.instance);
        return true;

      default:
        return false;
    }
  }

  private async controlService(action: string, serviceName: string): Promise<void> {
    const service = this.services.find((s) => s.name === serviceName);
    if (!service) return;

    try {
      const cmd = `systemctl --user ${action} ${service.systemdUnit}`;
      await execAsync(cmd);
      vscode.window.showInformationMessage(
        `Service ${service.displayName} ${action}ed successfully`
      );
    } catch (error) {
      vscode.window.showErrorMessage(
        `Failed to ${action} ${service.displayName}: ${error}`
      );
    }

    await this.refresh();
  }

  private async testOllamaInstance(instanceName: string): Promise<void> {
    const instance = this.ollamaInstances.find((i) => i.name === instanceName);
    if (!instance) return;

    try {
      const response = await fetch(`${instance.url}/api/tags`);
      if (response.ok) {
        vscode.window.showInformationMessage(
          `Ollama instance ${instanceName} is responding`
        );
      } else {
        vscode.window.showWarningMessage(
          `Ollama instance ${instanceName} returned status ${response.status}`
        );
      }
    } catch (error) {
      vscode.window.showErrorMessage(
        `Failed to connect to Ollama instance ${instanceName}: ${error}`
      );
    }
  }
}
