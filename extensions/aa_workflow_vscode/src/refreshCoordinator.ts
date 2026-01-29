/**
 * RefreshCoordinator - Unified refresh system for Command Center
 *
 * This module provides centralized state management and refresh coordination
 * to eliminate UI flicker caused by multiple overlapping refresh paths.
 *
 * Key features:
 * - Single source of truth for all UI state
 * - Debounced refresh queue with priority levels
 * - Differential updates (only sends changed data)
 * - Batched postMessage dispatch
 * - Hash-based change detection
 */

import * as vscode from "vscode";

// Priority levels for refresh requests
export enum RefreshPriority {
  LOW = 0,      // Background sync, periodic updates
  NORMAL = 1,   // File watcher, visibility changes
  HIGH = 2,     // User actions, immediate feedback needed
  IMMEDIATE = 3 // Critical updates, bypass debouncing
}

// State sections that can be independently updated
// These must match the keys in UIState
export type StateSection = keyof UIState;

// Message types for the webview
export type WebviewMessageType =
  | "serviceStatus"
  | "cronData"
  | "sprintBadgeUpdate"
  | "sprintTabUpdate"
  | "meetingsTabBadgeUpdate"
  | "meetingsUpdate"
  | "performanceTabBadgeUpdate"
  | "updateWorkspaces"
  | "ollamaStatusUpdate"
  | "slackChannels"
  | "sprintIssuesUpdate"
  | "dataUpdate"
  | "batchUpdate";

// Interface for state data
export interface UIState {
  services: {
    list: any[];
    mcp: { running: boolean; pid?: number };
  };
  cron: {
    enabled: boolean;
    timezone: string;
    jobs: any[];
    execution_mode: string;
    history: any[];
    total_history: number;
  };
  sprint: {
    issues: any[];
    pendingCount: number;
    totalIssues: number;
    renderedHtml?: string;
  };
  meetings: {
    currentMeeting: any;
    currentMeetings: any[];
    upcomingMeetings: any[];
    renderedUpcomingHtml?: string;
  };
  performance: {
    overall_percentage: number;
  };
  sessions: {
    workspaces: any[];
    totalCount: number;
    renderedHtml?: string;
  };
  ollama: {
    status: any;
  };
  slack: {
    channels: string[];
  };
  overview: {
    stats: any;
    todayStats: any;
    session: any;
    toolSuccessRate: number;
    workflowStatus: any;
    currentWork: any;
    workspaceCount: number;
    memoryHealth: any;
  };
}

// Pending update request
interface PendingUpdate {
  sections: Set<StateSection>;
  priority: RefreshPriority;
  timestamp: number;
}

/**
 * RefreshCoordinator manages all UI refresh operations
 */
export class RefreshCoordinator {
  private _panel: vscode.WebviewPanel;
  private _state: UIState;
  private _stateHashes: Map<StateSection, string> = new Map();
  private _pendingUpdate: PendingUpdate | null = null;
  private _debounceTimer: NodeJS.Timeout | null = null;
  private _isProcessing: boolean = false;

  // Debounce delays by priority (ms)
  private readonly DEBOUNCE_DELAYS: Record<RefreshPriority, number> = {
    [RefreshPriority.LOW]: 500,
    [RefreshPriority.NORMAL]: 200,
    [RefreshPriority.HIGH]: 50,
    [RefreshPriority.IMMEDIATE]: 0
  };

  // Minimum time between updates (ms) to prevent rapid fire
  private readonly MIN_UPDATE_INTERVAL = 100;
  private _lastUpdateTime: number = 0;

  constructor(panel: vscode.WebviewPanel) {
    this._panel = panel;
    this._state = this._createEmptyState();
  }

  /**
   * Create an empty state object
   */
  private _createEmptyState(): UIState {
    return {
      services: { list: [], mcp: { running: false } },
      cron: { enabled: false, timezone: "UTC", jobs: [], execution_mode: "claude_cli", history: [], total_history: 0 },
      sprint: { issues: [], pendingCount: 0, totalIssues: 0 },
      meetings: { currentMeeting: null, currentMeetings: [], upcomingMeetings: [] },
      performance: { overall_percentage: 0 },
      sessions: { workspaces: [], totalCount: 0 },
      ollama: { status: {} },
      slack: { channels: [] },
      overview: {
        stats: null,
        todayStats: { tool_calls: 0, skill_executions: 0 },
        session: { tool_calls: 0, skill_executions: 0, memory_ops: 0 },
        toolSuccessRate: 100,
        workflowStatus: {},
        currentWork: {},
        workspaceCount: 0,
        memoryHealth: {}
      }
    };
  }

  /**
   * Compute a hash for a state section
   */
  private _computeHash(data: any): string {
    return JSON.stringify(data);
  }

  /**
   * Check if a state section has changed
   */
  private _hasChanged(section: StateSection, newData: any): boolean {
    const newHash = this._computeHash(newData);
    const oldHash = this._stateHashes.get(section);

    if (newHash !== oldHash) {
      this._stateHashes.set(section, newHash);
      return true;
    }
    return false;
  }

  /**
   * Update a state section and queue a refresh if changed
   */
  public updateSection<K extends StateSection>(
    section: K,
    data: Partial<UIState[K]>,
    priority: RefreshPriority = RefreshPriority.NORMAL
  ): boolean {
    // Merge new data with existing state
    const currentData = this._state[section] as any;
    const newData = { ...currentData, ...data };

    // Check if data actually changed
    if (!this._hasChanged(section, newData)) {
      return false; // No change, no update needed
    }

    // Update state
    (this._state as any)[section] = newData;

    // Queue refresh
    this._queueRefresh(section, priority);
    return true;
  }

  /**
   * Update multiple sections at once (more efficient)
   */
  public updateSections(
    updates: Array<{ section: StateSection; data: any }>,
    priority: RefreshPriority = RefreshPriority.NORMAL
  ): StateSection[] {
    const changedSections: StateSection[] = [];

    for (const { section, data } of updates) {
      const currentData = this._state[section] as any;
      const newData = { ...currentData, ...data };

      if (this._hasChanged(section, newData)) {
        (this._state as any)[section] = newData;
        changedSections.push(section);
      }
    }

    if (changedSections.length > 0) {
      this._queueRefresh(changedSections, priority);
    }

    return changedSections;
  }

  /**
   * Queue a refresh for one or more sections
   */
  private _queueRefresh(
    sections: StateSection | StateSection[],
    priority: RefreshPriority
  ): void {
    const sectionArray = Array.isArray(sections) ? sections : [sections];

    if (this._pendingUpdate) {
      // Merge with existing pending update
      for (const section of sectionArray) {
        this._pendingUpdate.sections.add(section);
      }
      // Upgrade priority if new request is higher
      if (priority > this._pendingUpdate.priority) {
        this._pendingUpdate.priority = priority;
        // Re-schedule with new priority's debounce delay
        this._scheduleDispatch();
      }
    } else {
      // Create new pending update
      this._pendingUpdate = {
        sections: new Set(sectionArray),
        priority,
        timestamp: Date.now()
      };
      this._scheduleDispatch();
    }
  }

  /**
   * Schedule the dispatch with appropriate debouncing
   */
  private _scheduleDispatch(): void {
    if (!this._pendingUpdate) return;

    // Clear existing timer
    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
      this._debounceTimer = null;
    }

    const delay = this.DEBOUNCE_DELAYS[this._pendingUpdate.priority];

    if (delay === 0) {
      // Immediate dispatch
      this._dispatchUpdates();
    } else {
      this._debounceTimer = setTimeout(() => {
        this._dispatchUpdates();
      }, delay);
    }
  }

  /**
   * Dispatch pending updates to the webview
   */
  private _dispatchUpdates(): void {
    if (!this._pendingUpdate || this._isProcessing) return;

    // Enforce minimum update interval
    const now = Date.now();
    const timeSinceLastUpdate = now - this._lastUpdateTime;
    if (timeSinceLastUpdate < this.MIN_UPDATE_INTERVAL) {
      // Reschedule
      this._debounceTimer = setTimeout(() => {
        this._dispatchUpdates();
      }, this.MIN_UPDATE_INTERVAL - timeSinceLastUpdate);
      return;
    }

    this._isProcessing = true;
    const update = this._pendingUpdate;
    this._pendingUpdate = null;
    this._debounceTimer = null;

    try {
      // Build batch message with only changed sections
      const messages: any[] = [];

      for (const section of update.sections) {
        const message = this._buildMessageForSection(section);
        if (message) {
          messages.push(message);
        }
      }

      if (messages.length === 0) {
        return; // Nothing to send
      }

      // Send as batch if multiple messages, or single message if just one
      if (messages.length === 1) {
        this._panel.webview.postMessage(messages[0]);
      } else {
        // Send batch update
        this._panel.webview.postMessage({
          type: "batchUpdate",
          messages
        });
      }

      this._lastUpdateTime = Date.now();
    } finally {
      this._isProcessing = false;
    }
  }

  /**
   * Build a postMessage payload for a specific section
   */
  private _buildMessageForSection(section: StateSection): any | null {
    switch (section) {
      case "services":
        return {
          type: "serviceStatus",
          services: this._state.services.list,
          mcp: this._state.services.mcp
        };

      case "cron":
        return {
          type: "cronData",
          config: {
            enabled: this._state.cron.enabled,
            timezone: this._state.cron.timezone,
            jobs: this._state.cron.jobs,
            execution_mode: this._state.cron.execution_mode
          },
          history: this._state.cron.history,
          totalHistory: this._state.cron.total_history,
          currentLimit: 10
        };

      case "sprint":
        // If we have rendered HTML, send full update; otherwise just badge
        if (this._state.sprint.renderedHtml) {
          return {
            type: "sprintTabUpdate",
            issues: this._state.sprint.issues,
            renderedHtml: this._state.sprint.renderedHtml
          };
        } else {
          return {
            type: "sprintBadgeUpdate",
            pendingCount: this._state.sprint.pendingCount,
            totalIssues: this._state.sprint.totalIssues
          };
        }

      case "meetings":
        return {
          type: "meetingsTabBadgeUpdate",
          currentMeeting: this._state.meetings.currentMeeting,
          currentMeetings: this._state.meetings.currentMeetings,
          upcomingMeetings: this._state.meetings.upcomingMeetings,
          renderedUpcomingHtml: this._state.meetings.renderedUpcomingHtml
        };

      case "performance":
        return {
          type: "performanceTabBadgeUpdate",
          percentage: this._state.performance.overall_percentage
        };

      case "sessions":
        return {
          type: "updateWorkspaces",
          workspaces: this._state.sessions.workspaces,
          totalCount: this._state.sessions.totalCount,
          renderedHtml: this._state.sessions.renderedHtml
        };

      case "ollama":
        return {
          command: "ollamaStatusUpdate",
          data: this._state.ollama.status
        };

      case "slack":
        return {
          type: "slackChannels",
          channels: this._state.slack.channels
        };

      case "overview":
        return {
          type: "dataUpdate",
          stats: this._state.overview.stats,
          todayStats: this._state.overview.todayStats,
          session: this._state.overview.session,
          toolSuccessRate: this._state.overview.toolSuccessRate,
          workflowStatus: this._state.overview.workflowStatus,
          currentWork: this._state.overview.currentWork,
          workspaceCount: this._state.overview.workspaceCount,
          memoryHealth: this._state.overview.memoryHealth,
          cronConfig: {
            enabled: this._state.cron.enabled,
            jobs: this._state.cron.jobs
          }
        };

      default:
        return null;
    }
  }

  /**
   * Force immediate dispatch of all pending updates
   */
  public flush(): void {
    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
      this._debounceTimer = null;
    }
    this._dispatchUpdates();
  }

  /**
   * Get current state (read-only)
   */
  public getState(): Readonly<UIState> {
    return this._state;
  }

  /**
   * Get a specific section's state
   */
  public getSection<K extends StateSection>(section: K): Readonly<UIState[K]> {
    return this._state[section];
  }

  /**
   * Clear all state hashes (forces next update to be sent)
   */
  public invalidateCache(): void {
    this._stateHashes.clear();
  }

  /**
   * Invalidate cache for specific sections
   */
  public invalidateSections(sections: StateSection[]): void {
    for (const section of sections) {
      this._stateHashes.delete(section);
    }
  }

  /**
   * Dispose of resources
   */
  public dispose(): void {
    if (this._debounceTimer) {
      clearTimeout(this._debounceTimer);
      this._debounceTimer = null;
    }
    this._pendingUpdate = null;
    this._stateHashes.clear();
  }
}

/**
 * Helper function to create a RefreshCoordinator instance
 */
export function createRefreshCoordinator(panel: vscode.WebviewPanel): RefreshCoordinator {
  return new RefreshCoordinator(panel);
}
