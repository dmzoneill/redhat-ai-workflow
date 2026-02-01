/**
 * Workspace State Provider - Watch and provide workspace state from MCP server.
 *
 * Watches the workspace_state.json file exported by the MCP server and provides
 * real-time updates to the VS Code extension UI.
 */

import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { createLogger } from './logger';

const logger = createLogger("WorkspaceState");

/**
 * Session state from MCP server
 */
export interface SessionState {
    session_id: string;
    workspace_uri: string;
    persona: string;
    project: string | null;  // Per-session project (can differ from workspace)
    is_project_auto_detected: boolean;  // Whether project was auto-detected
    issue_key: string | null;
    branch: string | null;
    active_tools: string[];
    started_at: string | null;
    last_activity: string | null;
    name: string | null;
    last_tool: string | null;
    last_tool_time: string | null;
    tool_call_count: number;
    is_active?: boolean;  // Added when flattened
}

/**
 * Workspace state from MCP server
 */
export interface WorkspaceState {
    workspace_uri: string;
    project: string | null;
    persona: string;
    issue_key: string | null;
    branch: string | null;
    active_tools: string[];
    started_at: string | null;
    is_auto_detected: boolean;
    active_session_id: string | null;
    session_count: number;
    sessions: { [id: string]: SessionState };
}

/**
 * Exported workspace state file format
 */
export interface ExportedWorkspaceState {
    version: number;
    exported_at: string;
    workspace_count: number;
    session_count: number;
    workspaces: { [uri: string]: WorkspaceState };
    sessions: SessionState[];  // Flattened list of all sessions
}

/**
 * Provider for workspace state from MCP server
 */
export class WorkspaceStateProvider implements vscode.Disposable {
    private _onDidChange = new vscode.EventEmitter<ExportedWorkspaceState | null>();
    readonly onDidChange = this._onDidChange.event;

    private watcher: fs.FSWatcher | null = null;
    private currentState: ExportedWorkspaceState | null = null;
    private stateFilePath: string;
    private refreshInterval: NodeJS.Timeout | null = null;

    constructor() {
        // Path to workspace state file - must match exporter's path
        // Centralized in ~/.config/aa-workflow/
        this.stateFilePath = path.join(
            os.homedir(),
            '.config',
            'aa-workflow',
            'workspace_states.json'
        );

        // Initial load
        this.loadState();

        // Watch for changes
        this.startWatching();

        // Also poll periodically as backup (file watchers can be unreliable)
        this.refreshInterval = setInterval(() => this.loadState(), 5000);
    }

    /**
     * Get current workspace state
     */
    getState(): ExportedWorkspaceState | null {
        return this.currentState;
    }

    /**
     * Get all workspaces
     */
    getWorkspaces(): WorkspaceState[] {
        if (!this.currentState) {
            return [];
        }
        return Object.values(this.currentState.workspaces);
    }

    /**
     * Get workspace by URI
     */
    getWorkspace(uri: string): WorkspaceState | null {
        if (!this.currentState) {
            return null;
        }
        return this.currentState.workspaces[uri] || null;
    }

    /**
     * Get current workspace (matching VS Code workspace)
     */
    getCurrentWorkspace(): WorkspaceState | null {
        if (!this.currentState) {
            return null;
        }

        // Get VS Code workspace folder
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            return null;
        }

        const currentUri = workspaceFolders[0].uri.toString();

        // Try exact match first
        if (this.currentState.workspaces[currentUri]) {
            return this.currentState.workspaces[currentUri];
        }

        // Try file:// prefix match
        const fileUri = `file://${workspaceFolders[0].uri.fsPath}`;
        if (this.currentState.workspaces[fileUri]) {
            return this.currentState.workspaces[fileUri];
        }

        // Try path match
        for (const [uri, state] of Object.entries(this.currentState.workspaces)) {
            if (uri.includes(workspaceFolders[0].uri.fsPath)) {
                return state;
            }
        }

        return null;
    }

    /**
     * Get workspace count
     */
    getWorkspaceCount(): number {
        return this.currentState?.workspace_count || 0;
    }

    /**
     * Get session count
     */
    getSessionCount(): number {
        return this.currentState?.session_count || 0;
    }

    /**
     * Get all sessions (flattened list)
     */
    getAllSessions(): SessionState[] {
        return this.currentState?.sessions || [];
    }

    /**
     * Get sessions for a specific workspace
     */
    getSessionsForWorkspace(workspaceUri: string): SessionState[] {
        const workspace = this.currentState?.workspaces[workspaceUri];
        if (!workspace || !workspace.sessions) {
            return [];
        }
        return Object.values(workspace.sessions);
    }

    /**
     * Get session by ID
     */
    getSession(sessionId: string): SessionState | null {
        if (!this.currentState?.sessions) {
            return null;
        }
        return this.currentState.sessions.find(s => s.session_id === sessionId) || null;
    }

    /**
     * Check if state file exists
     */
    hasStateFile(): boolean {
        return fs.existsSync(this.stateFilePath);
    }

    /**
     * Load state from file
     */
    private loadState(): void {
        try {
            if (!fs.existsSync(this.stateFilePath)) {
                if (this.currentState !== null) {
                    this.currentState = null;
                    this._onDidChange.fire(null);
                }
                return;
            }

            const content = fs.readFileSync(this.stateFilePath, 'utf-8');
            const newState = JSON.parse(content) as ExportedWorkspaceState;

            // Check if state actually changed
            if (JSON.stringify(newState) !== JSON.stringify(this.currentState)) {
                this.currentState = newState;
                this._onDidChange.fire(newState);
            }
        } catch (error) {
            logger.error('Failed to load workspace state', error);
        }
    }

    /**
     * Start watching the state file
     */
    private startWatching(): void {
        try {
            // Ensure directory exists
            const dir = path.dirname(this.stateFilePath);
            if (!fs.existsSync(dir)) {
                fs.mkdirSync(dir, { recursive: true });
            }

            // Watch the file
            this.watcher = fs.watch(dir, (eventType, filename) => {
                if (filename === 'workspace_states.json') {
                    // Debounce rapid changes
                    setTimeout(() => this.loadState(), 100);
                }
            });
        } catch (error) {
            logger.error('Failed to start watching workspace state', error);
        }
    }

    /**
     * Force refresh
     */
    refresh(): void {
        this.loadState();
    }

    /**
     * Dispose resources
     */
    dispose(): void {
        if (this.watcher) {
            this.watcher.close();
            this.watcher = null;
        }
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
        this._onDidChange.dispose();
    }
}

/**
 * Singleton instance
 */
let instance: WorkspaceStateProvider | null = null;

/**
 * Get the workspace state provider instance
 */
export function getWorkspaceStateProvider(): WorkspaceStateProvider {
    if (!instance) {
        instance = new WorkspaceStateProvider();
    }
    return instance;
}

/**
 * Dispose the workspace state provider
 */
export function disposeWorkspaceStateProvider(): void {
    if (instance) {
        instance.dispose();
        instance = null;
    }
}
