/**
 * Constants for the AA Workflow VSCode Extension
 *
 * Centralized configuration values and D-Bus service definitions.
 */

import * as path from "path";
import * as os from "os";

// ============================================================================
// Paths
// ============================================================================

export const CONFIG_FILE = path.join(
  os.homedir(),
  "src",
  "redhat-ai-workflow",
  "config.json"
);

// Centralized state directory (used for config files, not state - state comes from D-Bus)
export const AA_CONFIG_DIR = path.join(os.homedir(), ".config", "aa-workflow");

// ============================================================================
// D-Bus Service Definitions
// ============================================================================

export interface DbusMethodArg {
  name: string;
  type: string;
  default: string;
}

export interface DbusMethod {
  name: string;
  description: string;
  args: DbusMethodArg[];
}

export interface DbusServiceDefinition {
  name: string;
  service: string;
  path: string;
  interface: string;
  icon: string;
  systemdUnit: string;
  methods: DbusMethod[];
}

export const DBUS_SERVICES: DbusServiceDefinition[] = [
  {
    name: "Slack Agent",
    service: "com.aiworkflow.BotSlack",
    path: "/com/aiworkflow/BotSlack",
    interface: "com.aiworkflow.BotSlack",
    icon: "💬",
    systemdUnit: "bot-slack.service",
    methods: [
      { name: "GetStatus", description: "Get daemon status and stats", args: [] },
      { name: "GetPending", description: "Get pending approval messages", args: [] },
      { name: "GetHistory", description: "Get message history", args: [
        { name: "limit", type: "int32", default: "10" },
        { name: "channel_id", type: "string", default: "" },
        { name: "user_id", type: "string", default: "" },
        { name: "status", type: "string", default: "" },
      ]},
      { name: "ApproveAll", description: "Approve all pending messages", args: [] },
      { name: "ReloadConfig", description: "Reload daemon configuration", args: [] },
      { name: "Shutdown", description: "Gracefully shutdown the daemon", args: [] },
    ],
  },
  {
    name: "Cron Scheduler",
    service: "com.aiworkflow.BotCron",
    path: "/com/aiworkflow/BotCron",
    interface: "com.aiworkflow.BotCron",
    icon: "🕐",
    systemdUnit: "bot-cron.service",
    methods: [
      { name: "GetStatus", description: "Get scheduler status and stats", args: [] },
      { name: "GetStats", description: "Get scheduler statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "list_jobs" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the scheduler", args: [] },
    ],
  },
  {
    name: "Meet Bot",
    service: "com.aiworkflow.BotMeet",
    path: "/com/aiworkflow/BotMeet",
    interface: "com.aiworkflow.BotMeet",
    icon: "🎥",
    systemdUnit: "bot-meet.service",
    methods: [
      { name: "GetStatus", description: "Get bot status and upcoming meetings", args: [] },
      { name: "GetStats", description: "Get bot statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "list_meetings" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
  {
    name: "Sprint Bot",
    service: "com.aiworkflow.BotSprint",
    path: "/com/aiworkflow/BotSprint",
    interface: "com.aiworkflow.BotSprint",
    icon: "🎯",
    systemdUnit: "bot-sprint.service",
    methods: [
      { name: "GetStatus", description: "Get bot status and sprint info", args: [] },
      { name: "GetStats", description: "Get bot statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "list_issues" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
  {
    name: "Session Manager",
    service: "com.aiworkflow.BotSession",
    path: "/com/aiworkflow/BotSession",
    interface: "com.aiworkflow.BotSession",
    icon: "💬",
    systemdUnit: "bot-session.service",
    methods: [
      { name: "GetStatus", description: "Get session manager status", args: [] },
      { name: "GetStats", description: "Get session statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_sessions" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the manager", args: [] },
    ],
  },
  {
    name: "Video Bot",
    service: "com.aiworkflow.BotVideo",
    path: "/com/aiworkflow/BotVideo",
    interface: "com.aiworkflow.BotVideo",
    icon: "📹",
    systemdUnit: "bot-video.service",
    methods: [
      { name: "GetStatus", description: "Get video bot status", args: [] },
      { name: "GetStats", description: "Get video statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_render_stats" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
  {
    name: "Config Daemon",
    service: "com.aiworkflow.BotConfig",
    path: "/com/aiworkflow/BotConfig",
    interface: "com.aiworkflow.BotConfig",
    icon: "⚙️",
    systemdUnit: "bot-config.service",
    methods: [
      { name: "GetStatus", description: "Get config daemon status", args: [] },
      { name: "GetStats", description: "Get config statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_config" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the daemon", args: [] },
    ],
  },
  {
    name: "Memory Daemon",
    service: "com.aiworkflow.Memory",
    path: "/com/aiworkflow/Memory",
    interface: "com.aiworkflow.Memory",
    icon: "🧠",
    systemdUnit: "bot-memory.service",
    methods: [
      { name: "GetStatus", description: "Get memory daemon status", args: [] },
      { name: "GetStats", description: "Get memory statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_memory" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the daemon", args: [] },
    ],
  },
  {
    name: "Stats Daemon",
    service: "com.aiworkflow.BotStats",
    path: "/com/aiworkflow/BotStats",
    interface: "com.aiworkflow.BotStats",
    icon: "📊",
    systemdUnit: "bot-stats.service",
    methods: [
      { name: "GetStatus", description: "Get stats daemon status", args: [] },
      { name: "GetStats", description: "Get statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_stats" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the daemon", args: [] },
    ],
  },
  {
    name: "Slop Bot",
    service: "com.aiworkflow.BotSlop",
    path: "/com/aiworkflow/BotSlop",
    interface: "com.aiworkflow.BotSlop",
    icon: "🔍",
    systemdUnit: "bot-slop.service",
    methods: [
      { name: "GetStatus", description: "Get slop bot status", args: [] },
      { name: "GetStats", description: "Get slop statistics", args: [] },
      { name: "CallMethod", description: "Call a custom method", args: [
        { name: "method_name", type: "string", default: "get_loop_status" },
        { name: "args_json", type: "string", default: "[]" },
      ]},
      { name: "Shutdown", description: "Gracefully shutdown the bot", args: [] },
    ],
  },
];
