/**
 * Meetings Tab
 *
 * Displays meeting bot status, upcoming meetings, and active meetings.
 *
 * Architecture: Uses MeetingService (via this.services.meeting) for business logic.
 * Falls back to direct D-Bus calls for operations not yet in the service.
 */

import { BaseTab, TabConfig, dbus, createLogger } from "./BaseTab";
import {
  MeetBotState,
  Meeting,
  ActiveMeeting,
  MonitoredCalendar,
  MeetingNote,
  loadMeetBotState,
  getMeetingsTabContent,
  getMeetingsTabStyles,
  getMeetingsTabScript,
} from "../meetingsRenderer";

const logger = createLogger("MeetingsTab");

export class MeetingsTab extends BaseTab {
  private state: MeetBotState | null = null;
  private upcomingCount = 0;
  private activeCount = 0;

  constructor() {
    super({
      id: "meetings",
      label: "Meetings",
      icon: "🎥",
    });
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
    let hasData = false;

    try {
      // Load meet state via D-Bus
      logger.log("Calling meet_getState()...");
      const result = await dbus.meet_getState();
      logger.log(`meet_getState() result: success=${result.success}, error=${result.error || 'none'}`);
      if (result.success && result.data) {
        const data = result.data as any;
        this.state = data.state || data;
        this.upcomingCount = this.state?.upcomingMeetings?.length || 0;
        this.activeCount = this.state?.activeMeetingCount || 0;
        hasData = true;
        logger.log(`Loaded ${this.upcomingCount} upcoming, ${this.activeCount} active meetings`);
      } else {
        // Fallback to file-based loading (deprecated)
        logger.log("D-Bus failed, trying file-based loading...");
        this.state = await loadMeetBotState();
        this.upcomingCount = this.state?.upcomingMeetings?.length || 0;
        this.activeCount = this.state?.activeMeetingCount || 0;
        hasData = this.state !== null;
        logger.log(`File-based: ${this.upcomingCount} upcoming, ${this.activeCount} active meetings`);
      }

      // Clear error on success
      if (hasData) {
        this.lastError = null;
      }
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
      // Don't reset state - preserve partial data
    }

    logger.log("loadData() complete");
    this.notifyNeedsRender();
  }

  getBadge(): { text: string; class?: string } | null {
    // Show error indicator if we have an error and no data
    if (this.lastError && !this.state) {
      return { text: "!", class: "error" };
    }

    if (this.activeCount > 0) {
      return { text: `${this.activeCount}`, class: "running" };
    }
    if (this.upcomingCount > 0) {
      return { text: `${this.upcomingCount}`, class: "" };
    }
    return null;
  }

  getContent(): string {
    // Show error state if we have an error and no data
    if (this.lastError && !this.state) {
      return this.getErrorHtml(`Failed to load meeting data: ${this.lastError}`);
    }

    if (!this.state) {
      return this.getLoadingHtml("Loading meeting data...");
    }
    return getMeetingsTabContent(this.state);
  }

  getStyles(): string {
    // All styles are in unified.css
    return "";
  }

  getScript(): string {
    return getMeetingsTabScript();
  }

  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;
    logger.log(`[MeetingsTab] handleMessage: ${msgType}, message: ${JSON.stringify(message).substring(0, 200)}`);

    switch (msgType) {
      case "approveMeeting":
        await this.approveMeeting(message.meetingId, message.mode || "notes");
        return true;

      case "rejectMeeting":
        await this.rejectMeeting(message.meetingId);
        return true;

      case "unapproveMeeting":
        await this.unapproveMeeting(message.meetingId);
        return true;

      case "joinMeetingNow":
        logger.log(`[MeetingsTab] joinMeetingNow: url=${message.meetUrl}, title=${message.title}, mode=${message.mode}, video=${message.videoEnabled}`);
        await this.joinMeeting(
          message.meetUrl,
          message.title,
          message.mode || "notes",
          message.videoEnabled || false
        );
        return true;

      case "setMeetingMode":
        await this.setMeetingMode(message.meetingId, message.mode);
        return true;

      case "startScheduler":
        await this.startScheduler();
        return true;

      case "stopScheduler":
        await this.stopScheduler();
        return true;

      case "leaveMeeting":
        await this.leaveMeeting(message.sessionId);
        return true;

      case "leaveAllMeetings":
        await this.leaveAllMeetings();
        return true;

      case "refreshCalendar":
        await this.refreshCalendar();
        return true;

      // === NEW: History handlers (Phase 3.4) ===
      case "viewNote":
        await this.viewNote(message.noteId);
        return true;

      case "viewTranscript":
        await this.viewTranscript(message.noteId);
        return true;

      case "viewBotLog":
        await this.viewBotLog(message.noteId);
        return true;

      case "viewLinkedIssues":
        await this.viewLinkedIssues(message.noteId);
        return true;

      case "searchNotes":
        await this.searchNotes(message.query);
        return true;

      case "copyTranscript":
        await this.copyTranscript();
        return true;

      case "clearCaptions":
        await this.clearCaptions();
        return true;

      // === NEW: Audio handlers (Phase 3.4) ===
      case "muteAudio":
        await this.muteAudio(message.sessionId);
        return true;

      case "unmuteAudio":
        await this.unmuteAudio(message.sessionId);
        return true;

      case "testTTS":
        await this.testTTS(message.sessionId);
        return true;

      case "testAvatar":
        await this.testAvatar(message.sessionId);
        return true;

      case "preloadJira":
        await this.preloadJira(message.sessionId);
        return true;

      case "setDefaultMode":
        await this.setDefaultMode(message.mode);
        return true;

      // === NEW: Video preview handlers (Phase 3.4) ===
      case "startVideoPreview":
        await this.startVideoPreview(message.sessionId);
        return true;

      case "stopVideoPreview":
        await this.stopVideoPreview(message.sessionId);
        return true;

      case "getVideoPreviewFrame":
        await this.getVideoPreviewFrame(message.sessionId);
        return true;

      default:
        return false;
    }
  }

  // Meeting actions - use MeetingService if available (preferred), otherwise fall back to D-Bus
  private async approveMeeting(meetingId: string, mode: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.approveMeeting()");
      await this.services.meeting.approveMeeting(meetingId, mode);
    } else {
      logger.log("Falling back to D-Bus for approveMeeting");
      const result = await dbus.meet_approve(meetingId, mode);
      if (!result.success) {
        logger.error(`Failed to approve meeting: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async rejectMeeting(meetingId: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.rejectMeeting()");
      await this.services.meeting.rejectMeeting(meetingId);
    } else {
      logger.log("Falling back to D-Bus for rejectMeeting");
      const result = await dbus.meet_reject(meetingId);
      if (!result.success) {
        logger.error(`Failed to reject meeting: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async unapproveMeeting(meetingId: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.unapproveMeeting()");
      await this.services.meeting.unapproveMeeting(meetingId);
    } else {
      logger.log("Falling back to D-Bus for unapproveMeeting");
      const result = await dbus.meet_unapprove(meetingId);
      if (!result.success) {
        logger.error(`Failed to unapprove meeting: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async joinMeeting(
    meetUrl: string,
    title: string,
    mode: string,
    videoEnabled: boolean
  ): Promise<void> {
    logger.log(`[MeetingsTab] joinMeeting called: url=${meetUrl}, title=${title}, mode=${mode}, video=${videoEnabled}`);
    if (this.services.meeting) {
      logger.log("Using MeetingService.joinMeeting()");
      await this.services.meeting.joinMeeting(meetUrl, title, mode, videoEnabled);
    } else {
      logger.log("Falling back to D-Bus for joinMeeting");
      const result = await dbus.meet_join(meetUrl, title, mode, videoEnabled);
      logger.log(`[MeetingsTab] joinMeeting result: success=${result.success}, error=${result.error}, data=${JSON.stringify(result.data)?.substring(0, 200)}`);
      if (!result.success) {
        logger.error(`Failed to join meeting: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async setMeetingMode(meetingId: string, mode: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.setMeetingMode()");
      await this.services.meeting.setMeetingMode(meetingId, mode);
    } else {
      logger.log("Falling back to D-Bus for setMeetingMode");
      const result = await dbus.meet_setMeetingMode(meetingId, mode);
      if (!result.success) {
        logger.error(`Failed to set meeting mode: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async startScheduler(): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.startScheduler()");
      await this.services.meeting.startScheduler();
    } else {
      logger.log("Falling back to D-Bus for startScheduler");
      const result = await dbus.meet_startScheduler();
      if (!result.success) {
        logger.error(`Failed to start scheduler: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async stopScheduler(): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.stopScheduler()");
      await this.services.meeting.stopScheduler();
    } else {
      logger.log("Falling back to D-Bus for stopScheduler");
      const result = await dbus.meet_stopScheduler();
      if (!result.success) {
        logger.error(`Failed to stop scheduler: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async leaveMeeting(sessionId: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.leaveMeeting()");
      await this.services.meeting.leaveMeeting(sessionId);
    } else {
      logger.log("Falling back to D-Bus for leaveMeeting");
      const result = await dbus.meet_leave(sessionId);
      if (!result.success) {
        logger.error(`Failed to leave meeting: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async leaveAllMeetings(): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.leaveAllMeetings()");
      await this.services.meeting.leaveAllMeetings();
    } else {
      logger.log("Falling back to D-Bus for leaveAllMeetings");
      const result = await dbus.meet_leaveAll();
      if (!result.success) {
        logger.error(`Failed to leave all meetings: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async refreshCalendar(): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.refreshCalendars()");
      await this.services.meeting.refreshCalendars();
    } else {
      logger.log("Falling back to D-Bus for refreshCalendar");
      const result = await dbus.meet_refresh();
      if (!result.success) {
        logger.error(`Failed to refresh calendar: ${result.error}`);
      }
    }
    await this.refresh();
  }

  // === NEW: History handlers (Phase 3.4) ===

  private async viewNote(noteId: number): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.getMeetingNote()");
      const note = await this.services.meeting.getMeetingNote(noteId);
      if (note) {
        const formatted = this.services.meeting.formatMeetingNote(note);
        // Show in a new editor
        const doc = await import("vscode").then(vscode => 
          vscode.workspace.openTextDocument({ content: formatted, language: "markdown" })
        );
        const vscode = await import("vscode");
        await vscode.window.showTextDocument(doc);
      }
    } else {
      logger.log("Falling back to D-Bus for viewNote");
      const result = await dbus.meet_getMeetingNote(noteId);
      if (result.success && result.data) {
        const vscode = await import("vscode");
        const doc = await vscode.workspace.openTextDocument({ 
          content: JSON.stringify(result.data, null, 2), 
          language: "json" 
        });
        await vscode.window.showTextDocument(doc);
      } else {
        logger.error(`Failed to get note: ${result.error}`);
      }
    }
  }

  private async viewTranscript(noteId: number): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.getTranscript()");
      const transcript = await this.services.meeting.getTranscript(noteId);
      if (transcript) {
        const formatted = this.services.meeting.formatTranscript(transcript);
        const vscode = await import("vscode");
        const doc = await vscode.workspace.openTextDocument({ content: formatted, language: "markdown" });
        await vscode.window.showTextDocument(doc);
      }
    } else {
      logger.log("Falling back to D-Bus for viewTranscript");
      const result = await dbus.meet_getTranscript(noteId);
      if (result.success && result.data) {
        const vscode = await import("vscode");
        const doc = await vscode.workspace.openTextDocument({ 
          content: JSON.stringify(result.data, null, 2), 
          language: "json" 
        });
        await vscode.window.showTextDocument(doc);
      } else {
        logger.error(`Failed to get transcript: ${result.error}`);
      }
    }
  }

  private async viewBotLog(noteId: number): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.getBotLog()");
      const log = await this.services.meeting.getBotLog(noteId);
      if (log) {
        const formatted = this.services.meeting.formatBotLog(log);
        const vscode = await import("vscode");
        const doc = await vscode.workspace.openTextDocument({ content: formatted, language: "log" });
        await vscode.window.showTextDocument(doc);
      }
    } else {
      logger.log("Falling back to D-Bus for viewBotLog");
      const result = await dbus.meet_getBotLog(noteId);
      if (result.success && result.data) {
        const vscode = await import("vscode");
        const doc = await vscode.workspace.openTextDocument({ 
          content: JSON.stringify(result.data, null, 2), 
          language: "json" 
        });
        await vscode.window.showTextDocument(doc);
      } else {
        logger.error(`Failed to get bot log: ${result.error}`);
      }
    }
  }

  private async viewLinkedIssues(noteId: number): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.getLinkedIssues()");
      const issues = await this.services.meeting.getLinkedIssues(noteId);
      if (issues && issues.length > 0) {
        const vscode = await import("vscode");
        const formatted = issues.map(i => `- ${i.key || i.id}: ${i.summary || i.title || 'No title'}`).join('\n');
        vscode.window.showInformationMessage(`Linked Issues:\n${formatted}`);
      } else {
        const vscode = await import("vscode");
        vscode.window.showInformationMessage("No linked issues found");
      }
    } else {
      logger.log("Falling back to D-Bus for viewLinkedIssues");
      const result = await dbus.meet_getLinkedIssues(noteId);
      if (result.success && result.data) {
        const vscode = await import("vscode");
        vscode.window.showInformationMessage(`Linked Issues: ${JSON.stringify(result.data)}`);
      } else {
        logger.error(`Failed to get linked issues: ${result.error}`);
      }
    }
  }

  private async searchNotes(query: string): Promise<void> {
    if (!query) return;

    if (this.services.meeting) {
      logger.log("Using MeetingService.searchNotes()");
      await this.services.meeting.searchNotes(query);
    } else {
      logger.log("Falling back to D-Bus for searchNotes");
      const result = await dbus.meet_searchNotes(query);
      if (!result.success) {
        logger.error(`Failed to search notes: ${result.error}`);
      }
    }
    this.notifyNeedsRender();
  }

  private async copyTranscript(): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.copyTranscript()");
      await this.services.meeting.copyTranscript();
    } else {
      logger.log("Falling back to D-Bus for copyTranscript");
      const result = await dbus.meet_getState();
      if (result.success && result.data) {
        const data = result.data as any;
        const captions = data.state?.captions || data.captions || [];
        if (captions.length > 0) {
          const vscode = await import("vscode");
          const text = captions.map((c: any) => `[${c.speaker}] ${c.text}`).join('\n');
          await vscode.env.clipboard.writeText(text);
          vscode.window.showInformationMessage(`Copied ${captions.length} captions to clipboard`);
        }
      }
    }
  }

  private async clearCaptions(): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.clearCaptions()");
      await this.services.meeting.clearCaptions();
    } else {
      logger.log("Falling back to D-Bus for clearCaptions");
      const result = await dbus.meet_clearCaptions();
      if (!result.success) {
        logger.error(`Failed to clear captions: ${result.error}`);
      }
    }
    await this.refresh();
  }

  // === NEW: Audio handlers (Phase 3.4) ===

  private async muteAudio(sessionId: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.muteAudio()");
      await this.services.meeting.muteAudio(sessionId);
    } else {
      logger.log("Falling back to D-Bus for muteAudio");
      const result = await dbus.meet_muteAudio(sessionId);
      if (!result.success) {
        logger.error(`Failed to mute audio: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async unmuteAudio(sessionId: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.unmuteAudio()");
      await this.services.meeting.unmuteAudio(sessionId);
    } else {
      logger.log("Falling back to D-Bus for unmuteAudio");
      const result = await dbus.meet_unmuteAudio(sessionId);
      if (!result.success) {
        logger.error(`Failed to unmute audio: ${result.error}`);
      }
    }
    await this.refresh();
  }

  private async testTTS(sessionId?: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.testTTS()");
      await this.services.meeting.testTTS(sessionId);
    } else {
      logger.log("Falling back to D-Bus for testTTS");
      const result = await dbus.meet_testTts(sessionId);
      if (!result.success) {
        logger.error(`Failed to test TTS: ${result.error}`);
      }
    }
  }

  private async testAvatar(sessionId?: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.testAvatar()");
      await this.services.meeting.testAvatar(sessionId);
    } else {
      logger.log("Falling back to D-Bus for testAvatar");
      const result = await dbus.meet_testAvatar(sessionId);
      if (!result.success) {
        logger.error(`Failed to test avatar: ${result.error}`);
      }
    }
  }

  private async preloadJira(sessionId?: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.preloadJira()");
      await this.services.meeting.preloadJira(sessionId);
    } else {
      logger.log("Falling back to D-Bus for preloadJira");
      const result = await dbus.meet_preloadJira(sessionId);
      if (!result.success) {
        logger.error(`Failed to preload Jira: ${result.error}`);
      }
    }
  }

  private async setDefaultMode(mode: string): Promise<void> {
    if (this.services.meeting) {
      logger.log("Using MeetingService.setDefaultMode()");
      await this.services.meeting.setDefaultMode(mode);
    } else {
      logger.log("Falling back to D-Bus for setDefaultMode");
      const result = await dbus.meet_setDefaultMode(mode);
      if (!result.success) {
        logger.error(`Failed to set default mode: ${result.error}`);
      }
    }
    await this.refresh();
  }

  // === NEW: Video preview handlers (Phase 3.4) ===

  private async startVideoPreview(sessionId: string): Promise<void> {
    logger.log("Starting video preview");
    const result = await dbus.video_startPreview(sessionId);
    if (!result.success) {
      logger.error(`Failed to start video preview: ${result.error}`);
    }
  }

  private async stopVideoPreview(sessionId: string): Promise<void> {
    logger.log("Stopping video preview");
    const result = await dbus.video_stopPreview(sessionId);
    if (!result.success) {
      logger.error(`Failed to stop video preview: ${result.error}`);
    }
  }

  private async getVideoPreviewFrame(sessionId: string): Promise<void> {
    logger.log("Getting video preview frame");
    const result = await dbus.video_getFrame(sessionId);
    if (result.success && result.data) {
      // Frame data would be sent to webview for display
      this.notifyNeedsRender();
    } else {
      logger.error(`Failed to get video frame: ${result.error}`);
    }
  }
}
