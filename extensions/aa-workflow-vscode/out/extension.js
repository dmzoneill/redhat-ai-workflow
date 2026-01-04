"use strict";
/**
 * AI Workflow VSCode Extension
 *
 * Provides real-time status indicators and quick actions for the AI Workflow system.
 *
 * Features:
 * - Status bar items showing Slack daemon, active issue, environment health, MR status
 * - Click actions to open Jira, GitLab, or run investigations
 * - Command palette integration for common workflows
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const statusBar_1 = require("./statusBar");
const dataProvider_1 = require("./dataProvider");
const commands_1 = require("./commands");
const treeView_1 = require("./treeView");
const notifications_1 = require("./notifications");
const dashboard_1 = require("./dashboard");
const skillVisualizer_1 = require("./skillVisualizer");
let statusBarManager;
let dataProvider;
let treeProvider;
let notificationManager;
let refreshInterval;
function activate(context) {
    console.log("AI Workflow extension activating...");
    // Initialize the data provider (connects to D-Bus/memory)
    dataProvider = new dataProvider_1.WorkflowDataProvider();
    // Initialize status bar items
    statusBarManager = new statusBar_1.StatusBarManager(context, dataProvider);
    // Initialize tree view
    treeProvider = (0, treeView_1.registerTreeView)(context, dataProvider);
    // Initialize notifications
    notificationManager = (0, notifications_1.registerNotifications)(context, dataProvider);
    // Initialize dashboard webview
    (0, dashboard_1.registerDashboard)(context, dataProvider);
    // Initialize skill visualizer
    (0, skillVisualizer_1.registerSkillVisualizer)(context);
    // Register commands
    (0, commands_1.registerCommands)(context, dataProvider, statusBarManager);
    // Start periodic refresh
    const config = vscode.workspace.getConfiguration("aa-workflow");
    const intervalSeconds = config.get("refreshInterval", 30);
    refreshInterval = setInterval(async () => {
        await dataProvider?.refresh();
        statusBarManager?.update();
        treeProvider?.refresh();
        await notificationManager?.checkAndNotify();
    }, intervalSeconds * 1000);
    // Initial update
    dataProvider.refresh().then(() => {
        statusBarManager?.update();
        treeProvider?.refresh();
    });
    console.log("AI Workflow extension activated!");
}
function deactivate() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
    statusBarManager?.dispose();
    notificationManager?.dispose();
    dataProvider?.dispose();
}
//# sourceMappingURL=extension.js.map
