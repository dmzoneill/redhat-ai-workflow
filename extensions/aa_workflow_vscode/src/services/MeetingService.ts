/**
 * MeetingService - Meeting Bot Business Logic
 *
 * Handles all meeting-related operations without direct UI dependencies.
 * Uses MessageBus for UI communication and NotificationService for user feedback.
 *
 * This extracts ~35 methods from commandCenter.ts into a testable service.
 */

import * as vscode from "vscode";
import { dbus } from "../dbusClient";
import { StateStore } from "../state";
import { MessageBus } from "./MessageBus";
import { NotificationService, NotificationType } from "./NotificationService";
import { createLogger } from "../logger";

const logger = createLogger("MeetingService");

// ============================================================================
// Types
// ============================================================================

export interface MeetingServiceDependencies {
  state: StateStore;
  messages: MessageBus;
  notifications: NotificationService;
}

export interface MeetingNote {
  id: number;
  title: string;
  date: string;
  summary?: string;
  attendees?: string[];
  duration?: number;
}

export interface TranscriptEntry {
  timestamp: string;
  speaker: string;
  text: string;
}

export interface BotLogEntry {
  timestamp: string;
  level: string;
  message: string;
}

export interface LinkedIssue {
  key?: string;
  id?: string;
  summary?: string;
  title?: string;
  url?: string;
}

// ============================================================================
// MeetingService Class
// ============================================================================

export class MeetingService {
  private state: StateStore;
  private messages: MessageBus;
  private notifications: NotificationService;
  private onSyncRequested: (() => void) | null = null;

  constructor(deps: MeetingServiceDependencies) {
    this.state = deps.state;
    this.messages = deps.messages;
    this.notifications = deps.notifications;
  }

  /**
   * Set callback for when sync is needed after an operation
   */
  setOnSyncRequested(callback: () => void): void {
    this.onSyncRequested = callback;
  }

  private requestSync(): void {
    if (this.onSyncRequested) {
      this.onSyncRequested();
    }
  }

  // ============================================================================
  // Meeting Approval Methods
  // ============================================================================

  /**
   * Approve a meeting for bot attendance
   */
  async approveMeeting(meetingId: string, mode: string): Promise<boolean> {
    try {
      const result = await dbus.meet_approve(meetingId, mode);

      if (result.success) {
        this.messages.publish("meetingApproved", {
          meetingId,
          success: true,
          mode,
        });
        this.notifications.info(`Meeting approved (${mode} mode)`);
        this.requestSync();
        return true;
      } else {
        this.messages.publish("meetingApproved", {
          meetingId,
          success: false,
          error: result.error,
        });
        this.notifications.error(`Failed to approve meeting: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.messages.publish("meetingApproved", {
        meetingId,
        success: false,
        error: e.message,
      });
      this.notifications.error(`Failed to approve meeting: ${e.message}`);
      return false;
    }
  }

  /**
   * Reject a meeting (bot won't attend)
   */
  async rejectMeeting(meetingId: string): Promise<boolean> {
    try {
      const result = await dbus.meet_reject(meetingId);

      if (result.success) {
        this.notifications.info("Meeting rejected");
        this.requestSync();
        return true;
      } else {
        this.notifications.error(`Failed to reject meeting: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to reject meeting: ${e.message}`);
      return false;
    }
  }

  /**
   * Unapprove a meeting (mark as skipped)
   */
  async unapproveMeeting(meetingId: string): Promise<boolean> {
    try {
      const result = await dbus.meet_unapprove(meetingId);

      if (result.success) {
        this.messages.publish("meetingUnapproved", {
          meetingId,
          success: true,
        });
        this.notifications.info("Meeting marked as skipped");
        this.requestSync();
        return true;
      } else {
        this.messages.publish("meetingUnapproved", {
          meetingId,
          success: false,
          error: result.error,
        });
        this.notifications.error(`Failed to unapprove meeting: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.messages.publish("meetingUnapproved", {
        meetingId,
        success: false,
        error: e.message,
      });
      this.notifications.error(`Failed to unapprove meeting: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Meeting Join/Leave Methods
  // ============================================================================

  /**
   * Join a meeting immediately
   */
  async joinMeeting(
    meetUrl: string,
    title: string,
    mode: string,
    videoEnabled: boolean = false
  ): Promise<boolean> {
    const videoStatus = videoEnabled ? " (with video overlay)" : "";
    this.notifications.info(`🎥 Joining meeting: ${title}${videoStatus}...`);

    this.messages.publish("meetingJoining", {
      meetUrl,
      title,
      success: true,
      status: "joining",
      message: "Starting browser and logging in...",
    });

    try {
      const result = await dbus.meet_join(meetUrl, title, mode, videoEnabled);

      if (result.success) {
        const data = result.data as any;
        if (data?.status === "joining") {
          this.notifications.info(`🎥 Join started - browser is loading...`);
        } else {
          this.notifications.info(`✅ Joined meeting: ${title}`);
        }
        this.requestSync();
        // Schedule additional syncs for status updates
        this.scheduleDelayedSyncs([5000, 15000, 30000]);
        return true;
      } else {
        this.messages.publish("meetingJoining", {
          meetUrl,
          title,
          success: false,
          error: result.error,
        });
        this.notifications.error(`Failed to join meeting: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      // D-Bus timeout is expected for long operations
      if (e.message.includes("NoReply") || e.message.includes("timeout")) {
        this.notifications.info(`🎥 Join in progress - please wait...`);
        this.scheduleDelayedSyncs([5000, 15000]);
        return true; // Optimistic - assume it's working
      } else {
        this.messages.publish("meetingJoining", {
          meetUrl,
          title,
          success: false,
          error: e.message,
        });
        this.notifications.error(`Failed to join meeting: ${e.message}`);
        return false;
      }
    }
  }

  /**
   * Leave a specific meeting
   */
  async leaveMeeting(sessionId: string): Promise<boolean> {
    try {
      const result = await dbus.meet_leave(sessionId);

      if (result.success) {
        this.notifications.info("Left meeting");
        this.state.invalidate("meetings");
        this.requestSync();
        return true;
      } else {
        this.notifications.error(`Failed to leave meeting: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to leave meeting: ${e.message}`);
      return false;
    }
  }

  /**
   * Leave all active meetings
   */
  async leaveAllMeetings(): Promise<boolean> {
    try {
      const result = await dbus.meet_leaveAll();

      if (result.success) {
        this.notifications.info("Left all meetings");
        this.state.invalidate("meetings");
        this.requestSync();
        return true;
      } else {
        this.notifications.error(`Failed to leave meetings: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to leave meetings: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Meeting Mode Methods
  // ============================================================================

  /**
   * Set the mode for a specific meeting
   */
  async setMeetingMode(meetingId: string, mode: string): Promise<boolean> {
    try {
      const result = await dbus.meet_setMeetingMode(meetingId, mode);
      if (result.success) {
        this.requestSync();
        return true;
      }
      return false;
    } catch (e: any) {
      logger.error(`Failed to set meeting mode: ${e.message}`);
      return false;
    }
  }

  /**
   * Set the default mode for new meetings
   */
  async setDefaultMode(mode: string): Promise<void> {
    try {
      await dbus.meet_setDefaultMode(mode);
    } catch (e: any) {
      logger.error(`Failed to set default mode: ${e.message}`);
    }
  }

  // ============================================================================
  // Scheduler Methods
  // ============================================================================

  /**
   * Start the meeting scheduler
   */
  async startScheduler(): Promise<boolean> {
    try {
      const result = await dbus.meet_startScheduler();

      if (result.success) {
        this.notifications.info("Meeting scheduler started");
        this.requestSync();
        return true;
      } else {
        this.notifications.error(`Failed to start scheduler: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to start scheduler: ${e.message}`);
      return false;
    }
  }

  /**
   * Stop the meeting scheduler
   */
  async stopScheduler(): Promise<boolean> {
    try {
      const result = await dbus.meet_stopScheduler();

      if (result.success) {
        this.notifications.info("Meeting scheduler stopped");
        this.requestSync();
        return true;
      } else {
        this.notifications.error(`Failed to stop scheduler: ${result.error}`);
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to stop scheduler: ${e.message}`);
      return false;
    }
  }

  /**
   * Refresh calendar data
   */
  async refreshCalendars(): Promise<void> {
    try {
      await dbus.meet_refreshCalendars();
      this.requestSync();
    } catch (e: any) {
      this.notifications.error(`Failed to refresh calendars: ${e.message}`);
    }
  }

  // ============================================================================
  // Audio Control Methods
  // ============================================================================

  /**
   * Mute audio for a meeting session
   */
  async muteAudio(sessionId: string): Promise<boolean> {
    try {
      const result = await dbus.meet_muteAudio(sessionId);

      if (result.success) {
        this.messages.publish("audioStateChanged", {
          muted: true,
          sessionId,
        });
        return true;
      } else {
        this.notifications.error(`Failed to mute audio: ${result.error}`);
        this.messages.publish("audioStateChanged", {
          muted: false,
          sessionId,
          error: result.error,
        });
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to mute audio: ${e.message}`);
      return false;
    }
  }

  /**
   * Unmute audio for a meeting session
   */
  async unmuteAudio(sessionId: string): Promise<boolean> {
    try {
      const result = await dbus.meet_unmuteAudio(sessionId);

      if (result.success) {
        this.messages.publish("audioStateChanged", {
          muted: false,
          sessionId,
        });
        return true;
      } else {
        this.notifications.error(`Failed to unmute audio: ${result.error}`);
        this.messages.publish("audioStateChanged", {
          muted: true,
          sessionId,
          error: result.error,
        });
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to unmute audio: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Test Methods
  // ============================================================================

  /**
   * Test TTS (text-to-speech) for a meeting
   */
  async testTTS(sessionId?: string): Promise<void> {
    try {
      await dbus.meet_testTts(sessionId);
      this.notifications.info(
        sessionId ? `TTS test sent to meeting ${sessionId}` : "TTS test sent"
      );
    } catch (e: any) {
      this.notifications.error(`TTS test failed: ${e.message}`);
    }
  }

  /**
   * Test avatar for a meeting
   */
  async testAvatar(sessionId?: string): Promise<void> {
    try {
      await dbus.meet_testAvatar(sessionId);
      this.notifications.info(
        sessionId ? `Avatar test sent to meeting ${sessionId}` : "Avatar test sent"
      );
    } catch (e: any) {
      this.notifications.error(`Avatar test failed: ${e.message}`);
    }
  }

  /**
   * Preload Jira context for a meeting
   */
  async preloadJira(sessionId?: string): Promise<boolean> {
    try {
      const result = await dbus.meet_preloadJira(sessionId);
      if (result.success) {
        this.notifications.info("Jira context preloaded");
        return true;
      }
      return false;
    } catch (e: any) {
      this.notifications.error(`Failed to preload Jira: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Meeting History Methods
  // ============================================================================

  /**
   * Get a meeting note by ID
   */
  async getMeetingNote(noteId: number): Promise<MeetingNote | null> {
    try {
      const result = await dbus.meet_getMeetingNote(noteId);

      if (result.success && result.data) {
        const data = result.data as unknown;
        return typeof data === "string"
          ? JSON.parse(data) as MeetingNote
          : data as MeetingNote;
      }
      return null;
    } catch (e: any) {
      this.notifications.error(`Failed to load meeting note: ${e.message}`);
      return null;
    }
  }

  /**
   * Get transcript for a meeting
   */
  async getTranscript(noteId: number): Promise<TranscriptEntry[] | null> {
    try {
      const result = await dbus.meet_getTranscript(noteId);

      if (result.success && result.data) {
        const data = result.data as unknown;
        return typeof data === "string"
          ? JSON.parse(data) as TranscriptEntry[]
          : data as TranscriptEntry[];
      }
      return null;
    } catch (e: any) {
      this.notifications.error(`Failed to load transcript: ${e.message}`);
      return null;
    }
  }

  /**
   * Get bot log for a meeting
   */
  async getBotLog(noteId: number): Promise<BotLogEntry[] | null> {
    try {
      const result = await dbus.meet_getBotLog(noteId);

      if (result.success && result.data) {
        const data = result.data as unknown;
        return typeof data === "string"
          ? JSON.parse(data) as BotLogEntry[]
          : data as BotLogEntry[];
      }
      return null;
    } catch (e: any) {
      this.notifications.error(`Failed to load bot log: ${e.message}`);
      return null;
    }
  }

  /**
   * Get linked issues for a meeting
   */
  async getLinkedIssues(noteId: number): Promise<LinkedIssue[] | null> {
    try {
      const result = await dbus.meet_getLinkedIssues(noteId);

      if (result.success && result.data) {
        const data = result.data as unknown;
        return typeof data === "string"
          ? JSON.parse(data) as LinkedIssue[]
          : data as LinkedIssue[];
      }
      return null;
    } catch (e: any) {
      this.notifications.error(`Failed to load linked issues: ${e.message}`);
      return null;
    }
  }

  /**
   * Search meeting notes
   */
  async searchNotes(query: string): Promise<MeetingNote[]> {
    try {
      const result = await dbus.meet_searchNotes(query);

      if (result.success && result.data) {
        const notes = typeof result.data === "string"
          ? JSON.parse(result.data)
          : result.data;

        this.messages.publish("searchResults", { notes });
        return notes;
      }
      return [];
    } catch (e: any) {
      this.notifications.error(`Search failed: ${e.message}`);
      return [];
    }
  }

  // ============================================================================
  // Caption Methods
  // ============================================================================

  /**
   * Copy current meeting captions to clipboard
   */
  async copyTranscript(): Promise<boolean> {
    try {
      const result = await dbus.meet_getState();
      if (result.success && result.data) {
        const data = result.data as any;
        const meetData = data.state || data;
        const captions = meetData.captions || [];

        if (captions.length > 0) {
          const text = captions
            .map((c: any) => `[${c.speaker}] ${c.text}`)
            .join("\n");
          await vscode.env.clipboard.writeText(text);
          this.notifications.info(`Copied ${captions.length} captions to clipboard`);
          return true;
        } else {
          this.notifications.info("No captions to copy");
          return false;
        }
      } else {
        this.notifications.info("No captions available");
        return false;
      }
    } catch (e: any) {
      this.notifications.error(`Failed to copy transcript: ${e.message}`);
      return false;
    }
  }

  /**
   * Clear current meeting captions
   */
  async clearCaptions(): Promise<boolean> {
    try {
      await dbus.meet_clearCaptions();
      this.requestSync();
      this.notifications.info("Captions cleared");
      return true;
    } catch (e: any) {
      this.notifications.error(`Failed to clear captions: ${e.message}`);
      return false;
    }
  }

  // ============================================================================
  // Helper Methods
  // ============================================================================

  private scheduleDelayedSyncs(delays: number[]): void {
    for (const delay of delays) {
      setTimeout(() => this.requestSync(), delay);
    }
  }

  // ============================================================================
  // Formatting Methods (pure functions, no side effects)
  // ============================================================================

  /**
   * Format a meeting note for display
   */
  formatMeetingNote(note: MeetingNote): string {
    const lines: string[] = [
      `# ${note.title}`,
      "",
      `**Date:** ${note.date}`,
    ];

    if (note.attendees && note.attendees.length > 0) {
      lines.push(`**Attendees:** ${note.attendees.join(", ")}`);
    }

    if (note.duration) {
      lines.push(`**Duration:** ${Math.round(note.duration / 60)} minutes`);
    }

    if (note.summary) {
      lines.push("", "## Summary", "", note.summary);
    }

    return lines.join("\n");
  }

  /**
   * Format transcript entries for display
   */
  formatTranscript(entries: TranscriptEntry[]): string {
    if (!entries || entries.length === 0) {
      return "No transcript available.";
    }

    const lines = ["# Meeting Transcript", ""];
    for (const entry of entries) {
      lines.push(`**[${entry.timestamp}] ${entry.speaker}:** ${entry.text}`);
    }

    return lines.join("\n");
  }

  /**
   * Format bot log entries for display
   */
  formatBotLog(entries: BotLogEntry[]): string {
    if (!entries || entries.length === 0) {
      return "No bot log available.";
    }

    return entries
      .map((e) => `[${e.timestamp}] [${e.level}] ${e.message}`)
      .join("\n");
  }
}
