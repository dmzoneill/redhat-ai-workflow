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

const OLLAMA_INSTANCES = [
  { name: "NPU", device: "Intel NPU", port: 11434, unit: "ollama-npu.service", model: "qwen2.5:0.5b" },
  { name: "iGPU", device: "Intel iGPU", port: 11435, unit: "ollama-igpu.service", model: "llama3.2:3b" },
  { name: "NVIDIA", device: "NVIDIA GPU", port: 11436, unit: "ollama-nvidia.service", model: "llama3:7b" },
  { name: "CPU", device: "CPU", port: 11437, unit: "ollama-cpu.service", model: "qwen2.5:0.5b" },
];

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
  private serviceList: ServiceInfo[] = [];
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
    this.serviceList = [
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

  protected computeDataFingerprint(): string {
    const serviceStatuses = this.serviceList.map((s) => s.status).join(",");
    const ollamaStatuses = this.ollamaInstances.map((i) => i.status).join(",");
    const parts = [
      this.onlineCount,
      this.offlineCount,
      serviceStatuses,
      ollamaStatuses,
      this.slackStatus?.connected ? 1 : 0,
    ];
    return parts.join("|");
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

      this.serviceList.forEach((service) => {
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

      // Load Ollama instance status
      await this.loadOllamaInstances();

      // Clear error on success
      this.lastError = null;
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
      // Don't reset services - preserve partial data
    }

    this.notifyNeedsRender();
  }

  getContent(): string {
    return `
      <!-- Service Status Summary -->
      <div class="section">
        <div class="section-title">Service Status</div>
        <div class="grid-3">
          <div class="card stat-card green">
            <div class="stat-icon">✓</div>
            <div class="stat-value">${this.onlineCount}</div>
            <div class="label-sm text-meta stat-label">Online</div>
          </div>
          <div class="card stat-card ${this.offlineCount > 0 ? "red" : "green"}">
            <div class="stat-icon">${this.offlineCount > 0 ? "✕" : "✓"}</div>
            <div class="stat-value">${this.offlineCount}</div>
            <div class="label-sm text-meta stat-label">Offline</div>
          </div>
          <div class="card stat-card blue">
            <div class="stat-icon">⟳</div>
            <div class="stat-value">${this.serviceList.length}</div>
            <div class="label-sm text-meta stat-label">Total</div>
          </div>
        </div>
      </div>

      <!-- Service Cards -->
      <div class="section">
        <div class="section-title">Daemons</div>
        <div class="grid-3">
          ${this.serviceList.map((service) => this.getServiceCardHtml(service)).join("")}
        </div>
      </div>

      <!-- Slack Status -->
      ${this.slackStatus ? this.getSlackStatusHtml() : ""}

      <!-- Ollama Instances -->
      ${this.getOllamaStatusHtml()}
    `;
  }

  private getServiceCardHtml(service: ServiceInfo): string {
    const statusClass = service.status === "online" ? "online" : "offline";
    const statusText = service.status === "online" ? "Online" : "Offline";

    return `
      <div class="card service-card ${service.status === "offline" ? "service-offline" : ""}">
        <div class="flex-between service-header">
          <div class="flex-row service-title">
            <span>${service.icon}</span>
            ${service.displayName}
          </div>
          <div class="service-status">
            <span class="dot status-dot ${statusClass}"></span>
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
        <div class="section-title">Slack Bot</div>
        <div class="card service-card">
          <div class="flex-between service-header">
            <div class="flex-row service-title">
              <span>💬</span>
              Slack Integration
            </div>
            <div class="service-status">
              <span class="dot status-dot ${this.slackStatus.connected ? "online" : "offline"}"></span>
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
    const ollamaOnline = this.ollamaInstances.filter((i) => i.status === "online").length;
    return `
      <div class="section">
        <div class="section-title">Ollama Instances
          <span class="text-sm text-secondary font-normal" style="margin-left: 8px;">
            ${ollamaOnline}/${this.ollamaInstances.length} online
          </span>
        </div>
        <div class="inference-ollama-grid">
          ${this.ollamaInstances.map((instance) => `
            <div class="card inference-ollama-card ${instance.status}">
              <div class="flex-between inference-ollama-header">
                <span class="font-semibold inference-ollama-name">${this.escapeHtml(instance.name)}</span>
                <span class="inference-ollama-status status-${instance.status}">${instance.status}</span>
              </div>
              <div class="inference-ollama-device">${this.escapeHtml(instance.device)}</div>
              <div class="inference-ollama-url">${this.escapeHtml(instance.url)}</div>
              ${instance.model ? `<div class="inference-ollama-model">Model: ${this.escapeHtml(instance.model)}</div>` : ""}
              <div class="inference-ollama-actions">
                <button class="btn btn-xs" data-action="testOllama" data-instance="${this.escapeHtml(instance.name)}">Test</button>
              </div>
            </div>
          `).join("")}
          ${this.ollamaInstances.length === 0 ? `
            <div class="inference-ollama-empty">
              <div class="inference-ollama-empty-icon">🦙</div>
              <div class="inference-ollama-empty-title">No Ollama Instances</div>
              <div class="inference-ollama-empty-text">Checking systemd service status...</div>
            </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    // Use centralized event delegation system - handlers survive content updates
    return `
      (function() {
        // Register click handler - can be called multiple times safely
        TabEventDelegation.registerClickHandler('services', function(action, element, e) {
          const service = element.dataset.service;

          switch(action) {
            case 'startService':
              if (service) {
                vscode.postMessage({ command: 'serviceControl', action: 'start', service });
              }
              break;
            case 'stopService':
              if (service) {
                vscode.postMessage({ command: 'serviceControl', action: 'stop', service });
              }
              break;
            case 'restartService':
              if (service) {
                vscode.postMessage({ command: 'serviceControl', action: 'restart', service });
              }
              break;
            case 'testOllama':
              if (element.dataset.instance) {
                vscode.postMessage({ command: 'testOllamaInstance', instance: element.dataset.instance });
              }
              break;
          }
        });
      })();
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
    const service = this.serviceList.find((s) => s.name === serviceName);
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

  private async loadOllamaInstances(): Promise<void> {
    try {
      const units = OLLAMA_INSTANCES.map((i) => i.unit).join(" ");
      const { stdout } = await execAsync(
        `systemctl is-active ${units} 2>/dev/null || true`
      );
      const states = stdout.trim().split("\n");

      this.ollamaInstances = OLLAMA_INSTANCES.map((inst, idx) => ({
        name: inst.name,
        url: `http://localhost:${inst.port}`,
        device: inst.device,
        status: (states[idx] === "active" ? "online" : "offline") as "online" | "offline",
        model: inst.model,
      }));

      const onlineCount = this.ollamaInstances.filter((i) => i.status === "online").length;
      logger.log(`Loaded ${this.ollamaInstances.length} Ollama instances (${onlineCount} online)`);
    } catch (error) {
      logger.error("Failed to load Ollama instances", error);
      this.ollamaInstances = OLLAMA_INSTANCES.map((inst) => ({
        name: inst.name,
        url: `http://localhost:${inst.port}`,
        device: inst.device,
        status: "offline" as const,
        model: inst.model,
      }));
    }
  }

  private async testOllamaInstance(instanceName: string): Promise<void> {
    const instance = this.ollamaInstances.find((i) => i.name === instanceName);
    if (!instance) return;

    try {
      vscode.window.showInformationMessage(`Testing ${instanceName}...`);
      const { stdout } = await execAsync(
        `curl -s -o /dev/null -w "%{http_code}" ${instance.url}/api/tags 2>/dev/null || echo "000"`,
        { timeout: 5000 }
      );
      const statusCode = stdout.trim();
      if (statusCode === "200") {
        vscode.window.showInformationMessage(`${instanceName} is healthy`);
        instance.status = "online";
      } else {
        vscode.window.showWarningMessage(`${instanceName} returned status ${statusCode}`);
        instance.status = "offline";
      }
      this.notifyNeedsRender();
    } catch (error) {
      vscode.window.showErrorMessage(
        `${instanceName} test failed: ${error instanceof Error ? error.message : String(error)}`
      );
      instance.status = "offline";
      this.notifyNeedsRender();
    }
  }
}
