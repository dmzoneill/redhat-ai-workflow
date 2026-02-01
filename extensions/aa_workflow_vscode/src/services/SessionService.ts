/**
 * SessionService - Session Management Business Logic
 *
 * Handles session-related operations without direct UI dependencies.
 * Uses MessageBus for UI communication and NotificationService for user feedback.
 */

import * as vscode from "vscode";
import { dbus } from "../dbusClient";
import { StateStore } from "../state";
import { MessageBus } from "./MessageBus";
import { NotificationService } from "./NotificationService";
import { createLogger } from "../logger";

const logger = createLogger("SessionService");

// ============================================================================
// Types
// ============================================================================

export interface SessionServiceDependencies {
  state: StateStore;
  messages: MessageBus;
  notifications: NotificationService;
}

export interface SessionSearchResult {
  session_id: string;
  name: string;
  project?: string;
  workspace_uri?: string;
  name_match?: boolean;
  content_matches?: any[];
  match_count?: number;
  last_updated?: string;
}

export interface SessionState {
  workspaces: Record<string, WorkspaceState>;
  workspace_count: number;
}

export interface WorkspaceState {
  workspace_uri: string;
  project: string | null;
  is_auto_detected: boolean;
  active_session_id: string | null;
  sessions: Record<string, ChatSession>;
  created_at: string | null;
  last_activity: string | null;
}

export interface ChatSession {
  session_id: string;
  workspace_uri: string;
  persona: string;
  project: string | null;
  is_project_auto_detected: boolean;
  issue_key: string | null;
  branch: string | null;
  tool_count?: number;
  started_at: string | null;
  last_activity: string | null;
  name: string | null;
  last_tool: string | null;
  last_tool_time: string | null;
  tool_call_count: number;
  is_active?: boolean;
}

export interface MeetingReference {
  meeting_id: number;
  title: string;
  date: string;
  matches: number;
}

// ============================================================================
// SessionService Class
// ============================================================================

export class SessionService {
  private state: StateStore;
  private messages: MessageBus;
  private notifications: NotificationService;

  constructor(deps: SessionServiceDependencies) {
    this.state = deps.state;
    this.messages = deps.messages;
    this.notifications = deps.notifications;
  }

  // ============================================================================
  // Session State
  // ============================================================================

  /**
   * Load session state from D-Bus daemon
   */
  async loadState(): Promise<SessionState | null> {
    try {
      const result = await dbus.session_getState();

      if (result.success && result.data) {
        const data = result.data as any;
        // Handle both direct state and wrapped {success, state} format
        const state = data.state || data;
        return state as SessionState;
      }
      return null;
    } catch (e: any) {
      logger.error(`Session D-Bus error: ${e.message}`);
      return null;
    }
  }

  // ============================================================================
  // Session Search
  // ============================================================================

  /**
   * Search sessions via D-Bus
   */
  async searchSessions(query: string, limit: number = 20): Promise<SessionSearchResult[]> {
    if (!query || query.trim().length === 0) {
      this.messages.publish("searchResults", {
        results: [],
        query: "",
        error: null,
      });
      return [];
    }

    try {
      const result = await dbus.session_searchChats(query, limit);

      if (result.success && result.data) {
        const data = result.data as any;
        const searchResult = typeof data === "string" ? JSON.parse(data) : data;
        const results = searchResult.results || [];

        this.messages.publish("searchResults", {
          results,
          query,
          totalFound: searchResult.total_found || 0,
          error: searchResult.error || null,
        });

        return results;
      } else {
        // D-Bus call failed
        this.messages.publish("searchResults", {
          results: [],
          query,
          error: "Search service unavailable",
        });
        return [];
      }
    } catch (e: any) {
      logger.error(`Search via D-Bus failed: ${e.message}`);
      this.messages.publish("searchResults", {
        results: [],
        query,
        error: e.message,
      });
      return [];
    }
  }

  /**
   * Local fallback search - searches session names only
   */
  searchSessionsLocal(
    query: string,
    workspaceState: Record<string, WorkspaceState>
  ): SessionSearchResult[] {
    const queryLower = query.toLowerCase();
    const results: SessionSearchResult[] = [];

    for (const [uri, ws] of Object.entries(workspaceState)) {
      const sessions = ws.sessions || {};
      for (const [sid, session] of Object.entries(sessions)) {
        const name = session.name || "";
        const issueKey = session.issue_key || "";

        if (
          name.toLowerCase().includes(queryLower) ||
          issueKey.toLowerCase().includes(queryLower)
        ) {
          results.push({
            session_id: sid,
            name: name || `Session ${sid.substring(0, 8)}`,
            project: session.project || ws.project || "unknown",
            workspace_uri: uri,
            name_match: true,
            content_matches: [],
            match_count: 0,
            last_updated: session.last_activity || undefined,
          });
        }
      }
    }

    this.messages.publish("searchResults", {
      results,
      query,
      totalFound: results.length,
      localSearch: true,
      error: null,
    });

    return results;
  }

  // ============================================================================
  // Session Operations
  // ============================================================================

  /**
   * Copy session ID to clipboard
   */
  async copySessionId(sessionId: string): Promise<boolean> {
    try {
      await vscode.env.clipboard.writeText(sessionId);
      this.notifications.info(
        `Session ID copied: ${sessionId}. Search for this in your Cursor chat history to find the session.`
      );
      return true;
    } catch (e: any) {
      this.notifications.error(`Failed to copy session ID: ${e.message}`);
      return false;
    }
  }

  /**
   * Open a chat session in Cursor
   */
  async openChatSession(sessionId: string, sessionName?: string): Promise<boolean> {
    try {
      // Import chat utilities dynamically
      const { getChatNameById, sendEnter, sleep } = await import("../chatUtils");

      // Get chat name from database
      const chatName = getChatNameById(sessionId) || sessionName;
      logger.log(`Opening chat - sessionId: ${sessionId}, chatName: ${chatName}`);

      // Open Quick Open with the chat name
      const searchQuery = chatName ? `chat:${chatName}` : "chat:";
      await vscode.commands.executeCommand("workbench.action.quickOpen", searchQuery);

      // Wait for Quick Open to populate results
      await sleep(500);

      // Send Enter to select the first result
      const enterResult = sendEnter();
      if (!enterResult) {
        logger.error("sendEnter() failed - ydotool may not be running");
      }

      return true;
    } catch (e: any) {
      logger.error("openChatSession error", e);
      this.notifications.error(`Failed to open chat: ${e.message}`);
      return false;
    }
  }

  /**
   * View meeting notes for a session (sessions that were discussed in meetings)
   */
  async viewMeetingNotes(sessionId: string): Promise<MeetingReference[]> {
    try {
      // This would query the meeting daemon for meetings where this session's issues were discussed
      // For now, return empty - this needs to be implemented in the meet daemon
      this.notifications.info("Meeting notes feature coming soon");
      return [];
    } catch (e: any) {
      this.notifications.error(`Failed to load meeting notes: ${e.message}`);
      return [];
    }
  }

  // ============================================================================
  // Statistics
  // ============================================================================

  /**
   * Get session statistics from workspace state
   */
  getStatistics(workspaceState: Record<string, WorkspaceState>): {
    totalSessions: number;
    uniquePersonas: number;
    uniqueProjects: number;
    workspaceCount: number;
  } {
    let totalSessions = 0;
    const personas = new Set<string>();
    const projects = new Set<string>();

    for (const ws of Object.values(workspaceState)) {
      const sessions = ws.sessions || {};
      totalSessions += Object.keys(sessions).length;

      // Count workspace-level project
      if (ws.project) projects.add(ws.project);

      // Count from sessions
      for (const session of Object.values(sessions)) {
        if (session.persona) personas.add(session.persona);
        if (session.project) projects.add(session.project);
      }
    }

    return {
      totalSessions,
      uniquePersonas: personas.size,
      uniqueProjects: projects.size,
      workspaceCount: Object.keys(workspaceState).length,
    };
  }
}
