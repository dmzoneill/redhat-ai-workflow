/**
 * Workflow Data Provider
 *
 * Fetches status data from:
 * 1. Memory files (~/.config/aa-workflow/memory/)
 * 2. D-Bus interface (Slack daemon)
 * 3. Direct file reads (fallback)
 *
 * This is the single source of truth for all status bar items.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { getConfigPath, getMemoryDir } from "./paths";
import { createLogger } from "./logger";
import { dbus, CurrentWork, EnvironmentStatus as DBusEnvironmentStatus } from "./dbusClient";
import { execAsync } from "./utils";

const logger = createLogger("DataProvider");

export interface SlackStatus {
  online: boolean;
  polls: number;
  processed: number;
  responded: number;
  errors: number;
}

export interface ActiveIssue {
  key: string;
  summary: string;
  status: string;
  branch?: string;
  repo?: string;
}

export interface ActiveMR {
  id: number;
  title: string;
  project: string;
  url: string;
  pipelineStatus: string;
  needsReview: boolean;
}

export interface EnvironmentStatus {
  stageStatus: string;
  prodStatus: string;
  stageAlerts: number;
  prodAlerts: number;
}

export interface FollowUp {
  task: string;
  priority: string;
  issueKey?: string;
  mrId?: number;
  due?: string;
}

export interface EphemeralNamespace {
  name: string;
  mrId?: string;
  commitSha?: string;
  deployedAt?: string;
  expires?: string;
  status?: string;
}

export interface VpnStatus {
  connected: boolean;
  name?: string;
  error?: string;
}

export interface WorkspaceInfo {
  workspace_uri?: string;
  project?: string;
  auto_detected_project?: string;
  issue_key?: string;
  branch?: string;
  persona?: string;
  active_tools?: string[];
  started_at?: string;
}

export interface WorkflowStatus {
  slack?: SlackStatus;
  activeIssue?: ActiveIssue;
  activeMR?: ActiveMR;
  environment?: EnvironmentStatus;
  followUps?: FollowUp[];
  namespaces?: EphemeralNamespace[];
  vpn?: VpnStatus;
  lastUpdated?: Date;
}

export class WorkflowDataProvider {
  private status: WorkflowStatus = {};
  private memoryDir: string;
  private configPath: string;
  private jiraUrl: string = "https://issues.redhat.com";
  private gitlabUrl: string = "https://gitlab.cee.redhat.com";
  private workspaceInfo: WorkspaceInfo = {};
  private workspaceStatesPath: string;

  constructor() {
    this.memoryDir = getMemoryDir();
    this.configPath = getConfigPath();
    // Centralized state directory
    this.workspaceStatesPath = path.join(
      os.homedir(),
      ".config",
      "aa-workflow",
      "workspace_states.json"
    );

    // Load config for URLs via D-Bus (async, will update when ready)
    this.loadConfigAsync();

    // Load workspace info
    this.loadWorkspaceInfo();
  }

  private async loadConfigAsync() {
    try {
      // Query config via D-Bus (uses ConfigManager for thread-safe access)
      const jiraResult = await this.queryDBusConfig("jira", "url");
      if (jiraResult) {
        this.jiraUrl = jiraResult;
      }

      const gitlabResult = await this.queryDBusConfig("gitlab", "url");
      if (gitlabResult) {
        this.gitlabUrl = gitlabResult;
      }
    } catch (e: any) {
      logger.log(`Failed to load config via D-Bus, using defaults: ${e?.message || e}`);
    }
  }

  private async queryDBusConfig(section: string, key: string): Promise<string | null> {
    try {
      const cmd = `dbus-send --session --print-reply --dest=com.aiworkflow.BotCron /com/aiworkflow/BotCron com.aiworkflow.BotCron.CallMethod string:"get_config" string:'${JSON.stringify({ section, key })}'`;
      const { stdout } = await execAsync(cmd, { timeout: 5000 });

      // Parse D-Bus output to extract JSON result
      const jsonMatch = stdout.match(/string\s+"(\{[\s\S]*\})"/);
      if (jsonMatch) {
        const result = JSON.parse(jsonMatch[1]);
        if (result.success && result.value !== null) {
          return result.value;
        }
      }
    } catch (e: any) {
      // D-Bus not available or cron daemon not running - this is OK
      logger.log(`D-Bus config query failed for ${section}.${key}: ${e?.message || e}`);
    }
    return null;
  }

  public getStatus(): WorkflowStatus {
    return this.status;
  }

  public getWorkspaceInfo(): WorkspaceInfo {
    return this.workspaceInfo;
  }

  private async loadWorkspaceInfoAsync(): Promise<void> {
    try {
      const result = await dbus.session_getState();
      if (result.success && result.data?.workspaces) {
        const workspaces = result.data.workspaces;

        // Get the current workspace folder
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (workspaceFolders && workspaceFolders.length > 0) {
          const currentUri = workspaceFolders[0].uri.toString();
          const currentPath = workspaceFolders[0].uri.fsPath;
          const fileUri = `file://${currentPath}`;

          // Find matching workspace state
          let workspaceState = workspaces[currentUri] || workspaces[fileUri];

          if (!workspaceState) {
            // Try to find by path match
            for (const [uri, state] of Object.entries(workspaces)) {
              const statePath = uri.replace("file://", "");
              if (statePath === currentPath || currentPath.startsWith(statePath)) {
                workspaceState = state as any;
                break;
              }
            }
          }

          if (workspaceState) {
            const activeSessionId = (workspaceState as any).active_session_id;
            const sessions = (workspaceState as any).sessions || {};
            const activeSession = activeSessionId ? sessions[activeSessionId] : null;

            this.workspaceInfo = {
              workspace_uri: (workspaceState as any).workspace_uri,
              project: activeSession?.project || (workspaceState as any).project,
              auto_detected_project: activeSession?.is_project_auto_detected
                ? activeSession.project
                : ((workspaceState as any).is_auto_detected ? (workspaceState as any).project : undefined),
              issue_key: activeSession?.issue_key || (workspaceState as any).issue_key,
              branch: activeSession?.branch || (workspaceState as any).branch,
              persona: activeSession?.persona || (workspaceState as any).persona,
              active_tools: activeSession?.active_tools || (workspaceState as any).active_tools,
              started_at: activeSession?.started_at || (workspaceState as any).started_at,
            };
          }
        }
      }
    } catch (e) {
      logger.log(`D-Bus session_getState failed: ${e}`);
    }
  }

  private loadWorkspaceInfo(): void {
    // Synchronous wrapper - call async version
    this.loadWorkspaceInfoAsync().catch(e => {
      logger.log(`Failed to load workspace info: ${e}`);
    });
  }

  public refreshWorkspaceInfo(): void {
    this.loadWorkspaceInfo();
  }

  public getJiraUrl(): string {
    return this.jiraUrl;
  }

  public getGitLabUrl(): string {
    return this.gitlabUrl;
  }

  public async refresh(): Promise<void> {
    await Promise.all([
      this.refreshSlackStatus(),
      this.refreshActiveIssue(),
      this.refreshActiveMR(),
      this.refreshEnvironment(),
      this.refreshFollowUps(),
      this.refreshNamespaces(),
      this.refreshVpnStatus(),
    ]);
    this.status.lastUpdated = new Date();
  }

  private async refreshSlackStatus(): Promise<void> {
    try {
      // Try D-Bus first
      const dbusStatus = await this.getSlackStatusFromDbus();
      if (dbusStatus) {
        this.status.slack = dbusStatus;
        return;
      }
    } catch (e) {
      // D-Bus not available, fallback to checking process
    }

    // Fallback: check if slack_daemon.py is running
    try {
      const { stdout } = await execAsync("pgrep -f slack_daemon.py");
      this.status.slack = {
        online: stdout.trim().length > 0,
        polls: 0,
        processed: 0,
        responded: 0,
        errors: 0,
      };
    } catch {
      this.status.slack = undefined;
    }
  }

  private async getSlackStatusFromDbus(): Promise<SlackStatus | undefined> {
    try {
      // Use dbus-send to query the Slack daemon
      const { stdout } = await execAsync(
        `dbus-send --session --print-reply --dest=com.aiworkflow.BotSlack ` +
          `/com/aiworkflow/BotSlack com.aiworkflow.BotSlack.GetStatus`,
        { timeout: 3000 }
      );

      // Parse D-Bus response (format: variant "json_string")
      const jsonMatch = stdout.match(/string "(.+)"/);
      if (jsonMatch) {
        const stats = JSON.parse(jsonMatch[1]);
        return {
          online: stats.running !== false,
          polls: stats.polls || 0,
          // D-Bus returns messages_processed/messages_responded, map to short names
          processed: stats.messages_processed || stats.processed || 0,
          responded: stats.messages_responded || stats.responded || 0,
          errors: stats.errors || stats.consecutive_errors || 0,
        };
      }
    } catch {
      // D-Bus call failed
    }
    return undefined;
  }

  private async refreshActiveIssue(): Promise<void> {
    try {
      // Try D-Bus first (MemoryDaemon)
      const result = await dbus.memory_getCurrentWork();
      if (result.success && result.data?.work) {
        const work = result.data.work;
        // Use activeIssue if available, otherwise first from activeIssues array
        const issue = work.activeIssue || (work.activeIssues && work.activeIssues[0]);
        if (issue) {
          this.status.activeIssue = {
            key: issue.key || "",
            summary: issue.summary || "",
            status: issue.status || "Unknown",
            branch: issue.branch,
            repo: issue.repo,
          };
          return;
        }
      }
    } catch (e) {
      logger.log(`D-Bus memory_getCurrentWork failed: ${e}`);
      this.status.activeIssue = undefined;
    }
  }

  private async refreshActiveMR(): Promise<void> {
    try {
      const result = await dbus.memory_getCurrentWork();
      if (result.success && result.data?.work) {
        const work = result.data.work;
        const mr = work.activeMR || (work.openMRs && work.openMRs[0]);
        if (mr) {
          this.status.activeMR = {
            id: mr.id || 0,
            title: mr.title || "",
            project: (mr as any).project || "",
            url: (mr as any).url || "",
            pipelineStatus: (mr as any).pipeline_status || "unknown",
            needsReview: (mr as any).needs_review !== false,
          };
          return;
        }
      }
      this.status.activeMR = undefined;
    } catch (e) {
      logger.log(`D-Bus memory_getCurrentWork failed for MR: ${e}`);
      this.status.activeMR = undefined;
    }
  }

  private async refreshEnvironment(): Promise<void> {
    try {
      const result = await dbus.memory_getEnvironments();
      if (result.success && result.data?.environments) {
        const envs = result.data.environments;
        const stage = envs.find((e: DBusEnvironmentStatus) => e.name === "stage");
        const prod = envs.find((e: DBusEnvironmentStatus) => e.name === "production");

        this.status.environment = {
          stageStatus: stage?.status || "unknown",
          prodStatus: prod?.status || "unknown",
          stageAlerts: stage?.alerts?.length || 0,
          prodAlerts: prod?.alerts?.length || 0,
        };
        return;
      }
      this.status.environment = undefined;
    } catch (e) {
      logger.log(`D-Bus memory_getEnvironments failed: ${e}`);
      this.status.environment = undefined;
    }
  }

  private async refreshFollowUps(): Promise<void> {
    try {
      const result = await dbus.memory_getCurrentWork();
      if (result.success && result.data?.work?.followUps) {
        this.status.followUps = result.data.work.followUps.map((fu: any) => ({
          task: fu.task || "",
          priority: fu.priority || "normal",
          issueKey: fu.issue_key,
          mrId: fu.mr_id,
          due: fu.due,
        }));
        return;
      }
      this.status.followUps = [];
    } catch (e) {
      logger.log(`D-Bus memory_getCurrentWork failed for follow-ups: ${e}`);
      this.status.followUps = [];
    }
  }

  private async refreshNamespaces(): Promise<void> {
    try {
      const result = await dbus.memory_getEnvironments();
      if (result.success && result.data?.environments) {
        const envs = result.data.environments;
        const ephemeral = envs.find((e: DBusEnvironmentStatus) => e.name === "ephemeral");
        if (ephemeral && (ephemeral as any).namespaces) {
          this.status.namespaces = (ephemeral as any).namespaces.map((ns: any) => ({
            name: ns.name || "",
            mrId: ns.mr_id,
            commitSha: ns.commit_sha,
            deployedAt: ns.deployed_at,
            expires: ns.expires,
            status: ns.status || "unknown",
          }));
          return;
        }
      }
      this.status.namespaces = [];
    } catch (e) {
      logger.log(`D-Bus memory_getEnvironments failed for namespaces: ${e}`);
      this.status.namespaces = [];
    }
  }

  /**
   * Simple YAML list parser for our memory files
   * Extracts items from a named list
   */
  private parseYamlList(content: string, listName: string): any[] {
    const items: any[] = [];
    const regex = new RegExp(`${listName}:\\s*\\n((?:\\s+-[^\\n]*\\n?)+)`, "m");
    const match = content.match(regex);

    if (!match) {
      return items;
    }

    // Parse each list item
    const listContent = match[1];
    const itemBlocks = listContent.split(/\n\s*-\s+/).filter(Boolean);

    for (const block of itemBlocks) {
      const item: any = {};
      // Remove leading "- " if present
      const cleanBlock = block.replace(/^-\s+/, "");
      const lines = cleanBlock.split("\n").filter(Boolean);

      for (const line of lines) {
        const keyMatch = line.match(/^\s*(\w+):\s*(.*)$/);
        if (keyMatch) {
          let value: any = keyMatch[2].trim();
          // Remove quotes if present
          if (
            (value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))
          ) {
            value = value.slice(1, -1);
          }
          // Convert to number if numeric
          if (/^\d+$/.test(value)) {
            value = parseInt(value, 10);
          }
          // Convert to boolean if true/false
          if (value === "true") value = true;
          if (value === "false") value = false;

          item[keyMatch[1]] = value;
        }
      }

      if (Object.keys(item).length > 0) {
        items.push(item);
      }
    }

    return items;
  }

  private async refreshVpnStatus(): Promise<void> {
    try {
      // Check if we can resolve gitlab.cee.redhat.com (internal host)
      const { stdout } = await execAsync("getent hosts gitlab.cee.redhat.com", { timeout: 3000 });
      if (stdout.trim()) {
        this.status.vpn = {
          connected: true,
          name: "Red Hat VPN",
        };
      } else {
        this.status.vpn = {
          connected: false,
          error: "Cannot resolve internal hosts",
        };
      }
    } catch {
      // Try alternative check - look for VPN interface
      try {
        const { stdout: nmcli } = await execAsync("nmcli -t -f NAME,TYPE,STATE connection show --active 2>/dev/null | grep -i vpn", { timeout: 2000 });
        if (nmcli.trim()) {
          const vpnName = nmcli.split(":")[0];
          this.status.vpn = {
            connected: true,
            name: vpnName || "VPN",
          };
        } else {
          this.status.vpn = {
            connected: false,
            error: "VPN not connected",
          };
        }
      } catch {
        this.status.vpn = {
          connected: false,
          error: "VPN not connected",
        };
      }
    }
  }

  public dispose() {
    // Cleanup if needed
  }
}
