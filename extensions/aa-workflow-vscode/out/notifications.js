"use strict";
/**
 * Notification Manager
 *
 * Shows toast notifications for important workflow events:
 * - MR approved
 * - Pipeline failed
 * - Alert firing
 * - Namespace expiring
 *
 * Can subscribe to D-Bus signals for real-time updates.
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
exports.NotificationManager = void 0;
exports.registerNotifications = registerNotifications;
const vscode = __importStar(require("vscode"));
const child_process_1 = require("child_process");
const util_1 = require("util");
const execAsync = (0, util_1.promisify)(child_process_1.exec);
class NotificationManager {
    dataProvider;
    state;
    dbusWatcher;
    constructor(dataProvider) {
        this.dataProvider = dataProvider;
        this.state = {
            lastAlertCount: 0,
            lastPipelineStatus: "",
            lastMrId: 0,
            shownNotifications: new Set(),
        };
    }
    /**
     * Check for changes and show notifications
     */
    async checkAndNotify() {
        const status = this.dataProvider.getStatus();
        await Promise.all([
            this.checkAlerts(status),
            this.checkPipeline(status),
            this.checkMR(status),
        ]);
    }
    async checkAlerts(status) {
        const env = status.environment;
        if (!env)
            return;
        const currentAlertCount = (env.stageAlerts || 0) + (env.prodAlerts || 0);
        // New alerts appeared
        if (currentAlertCount > this.state.lastAlertCount) {
            const newAlerts = currentAlertCount - this.state.lastAlertCount;
            if (env.prodAlerts && env.prodAlerts > 0) {
                // Production alert - critical
                const action = await vscode.window.showErrorMessage(`🔴 Production Alert: ${env.prodAlerts} alert${env.prodAlerts > 1 ? "s" : ""} firing`, "Investigate", "Dismiss");
                if (action === "Investigate") {
                    vscode.commands.executeCommand("aa-workflow.investigateAlert");
                }
            }
            else if (env.stageAlerts && env.stageAlerts > 0) {
                // Stage alert - warning
                const action = await vscode.window.showWarningMessage(`⚠️ Stage Alert: ${env.stageAlerts} alert${env.stageAlerts > 1 ? "s" : ""} firing`, "Investigate", "Dismiss");
                if (action === "Investigate") {
                    vscode.commands.executeCommand("aa-workflow.investigateAlert");
                }
            }
        }
        this.state.lastAlertCount = currentAlertCount;
    }
    async checkPipeline(status) {
        const mr = status.activeMR;
        if (!mr)
            return;
        const notificationKey = `pipeline-${mr.id}-${mr.pipelineStatus}`;
        // Don't show if we've already notified for this state
        if (this.state.shownNotifications.has(notificationKey)) {
            return;
        }
        // Pipeline status changed to failed
        if (mr.pipelineStatus === "failed" &&
            this.state.lastPipelineStatus !== "failed") {
            const action = await vscode.window.showErrorMessage(`❌ Pipeline failed for MR !${mr.id}`, "View MR", "Dismiss");
            if (action === "View MR") {
                vscode.commands.executeCommand("aa-workflow.openMR");
            }
            this.state.shownNotifications.add(notificationKey);
        }
        // Pipeline succeeded after being failed
        if (mr.pipelineStatus === "success" &&
            this.state.lastPipelineStatus === "failed") {
            vscode.window.showInformationMessage(`✅ Pipeline passed for MR !${mr.id}`);
            this.state.shownNotifications.add(notificationKey);
        }
        this.state.lastPipelineStatus = mr.pipelineStatus;
        this.state.lastMrId = mr.id;
    }
    async checkMR(status) {
        const mr = status.activeMR;
        if (!mr)
            return;
        // Check if MR needs review and pipeline passed
        if (mr.needsReview &&
            (mr.pipelineStatus === "success" || mr.pipelineStatus === "passed")) {
            const notificationKey = `review-needed-${mr.id}`;
            if (!this.state.shownNotifications.has(notificationKey)) {
                const action = await vscode.window.showInformationMessage(`🔍 MR !${mr.id} is ready for review`, "Open MR", "Dismiss");
                if (action === "Open MR") {
                    vscode.commands.executeCommand("aa-workflow.openMR");
                }
                this.state.shownNotifications.add(notificationKey);
            }
        }
    }
    /**
     * Start watching D-Bus for real-time events
     */
    startDbusWatcher() {
        // Poll D-Bus for Slack events every 30 seconds
        this.dbusWatcher = setInterval(async () => {
            try {
                await this.checkSlackEvents();
            }
            catch {
                // D-Bus not available, skip
            }
        }, 30000);
    }
    async checkSlackEvents() {
        try {
            // Check for new unread messages via D-Bus
            const { stdout } = await execAsync(`dbus-send --session --print-reply --dest=com.aiworkflow.SlackAgent ` +
                `/com/aiworkflow/SlackAgent com.aiworkflow.SlackAgent.GetPending`);
            // Parse response for pending message count
            const countMatch = stdout.match(/int32\s+(\d+)/);
            if (countMatch) {
                const pendingCount = parseInt(countMatch[1], 10);
                if (pendingCount > 0) {
                    vscode.window.showInformationMessage(`📬 ${pendingCount} pending Slack message${pendingCount > 1 ? "s" : ""} awaiting approval`);
                }
            }
        }
        catch {
            // D-Bus not available
        }
    }
    /**
     * Show a custom notification
     */
    async showNotification(type, message, actions) {
        switch (type) {
            case "error":
                return vscode.window.showErrorMessage(message, ...(actions || []));
            case "warning":
                return vscode.window.showWarningMessage(message, ...(actions || []));
            default:
                return vscode.window.showInformationMessage(message, ...(actions || []));
        }
    }
    dispose() {
        if (this.dbusWatcher) {
            clearInterval(this.dbusWatcher);
        }
    }
}
exports.NotificationManager = NotificationManager;
function registerNotifications(context, dataProvider) {
    const notificationManager = new NotificationManager(dataProvider);
    // Start D-Bus watcher for real-time events
    notificationManager.startDbusWatcher();
    // Register command to manually check notifications
    context.subscriptions.push(vscode.commands.registerCommand("aa-workflow.checkNotifications", async () => {
        await dataProvider.refresh();
        await notificationManager.checkAndNotify();
    }));
    return notificationManager;
}
//# sourceMappingURL=notifications.js.map
