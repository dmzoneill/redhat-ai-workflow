/**
 * Meetings Tab
 *
 * Displays meeting bot status, upcoming meetings, and active meetings.
 * Uses D-Bus to communicate with the Meet daemon.
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

  getBadge(): { text: string; class?: string } | null {
    if (this.activeCount > 0) {
      return { text: `${this.activeCount}`, class: "running" };
    }
    if (this.upcomingCount > 0) {
      return { text: `${this.upcomingCount}`, class: "" };
    }
    return null;
  }

  async loadData(): Promise<void> {
    logger.log("loadData() starting...");
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
        logger.log(`Loaded ${this.upcomingCount} upcoming, ${this.activeCount} active meetings`);
      } else {
        // Fallback to file-based loading (deprecated)
        logger.log("D-Bus failed, trying file-based loading...");
        this.state = await loadMeetBotState();
        this.upcomingCount = this.state?.upcomingMeetings?.length || 0;
        this.activeCount = this.state?.activeMeetingCount || 0;
        logger.log(`File-based: ${this.upcomingCount} upcoming, ${this.activeCount} active meetings`);
      }
      logger.log("loadData() complete");
    } catch (error) {
      this.lastError = error instanceof Error ? error.message : String(error);
      logger.error("Error loading data", error);
      this.state = null;
    }
  }

  getContent(): string {
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

      default:
        return false;
    }
  }

  // Meeting actions via D-Bus
  private async approveMeeting(meetingId: string, mode: string): Promise<void> {
    const result = await dbus.meet_approve(meetingId, mode);
    if (!result.success) {
      logger.error(`Failed to approve meeting: ${result.error}`);
    }
    await this.refresh();
  }

  private async rejectMeeting(meetingId: string): Promise<void> {
    const result = await dbus.meet_reject(meetingId);
    if (!result.success) {
      logger.error(`Failed to reject meeting: ${result.error}`);
    }
    await this.refresh();
  }

  private async unapproveMeeting(meetingId: string): Promise<void> {
    const result = await dbus.meet_unapprove(meetingId);
    if (!result.success) {
      logger.error(`Failed to unapprove meeting: ${result.error}`);
    }
    await this.refresh();
  }

  private async joinMeeting(
    meetUrl: string,
    title: string,
    mode: string,
    videoEnabled: boolean
  ): Promise<void> {
    const result = await dbus.meet_join(meetUrl, title, mode, videoEnabled);
    if (!result.success) {
      logger.error(`Failed to join meeting: ${result.error}`);
    }
    await this.refresh();
  }

  private async setMeetingMode(meetingId: string, mode: string): Promise<void> {
    const result = await dbus.meet_setMeetingMode(meetingId, mode);
    if (!result.success) {
      logger.error(`Failed to set meeting mode: ${result.error}`);
    }
    await this.refresh();
  }

  private async startScheduler(): Promise<void> {
    const result = await dbus.meet_startScheduler();
    if (!result.success) {
      logger.error(`Failed to start scheduler: ${result.error}`);
    }
    await this.refresh();
  }

  private async stopScheduler(): Promise<void> {
    const result = await dbus.meet_stopScheduler();
    if (!result.success) {
      logger.error(`Failed to stop scheduler: ${result.error}`);
    }
    await this.refresh();
  }

  private async leaveMeeting(sessionId: string): Promise<void> {
    const result = await dbus.meet_leave(sessionId);
    if (!result.success) {
      logger.error(`Failed to leave meeting: ${result.error}`);
    }
    await this.refresh();
  }

  private async leaveAllMeetings(): Promise<void> {
    const result = await dbus.meet_leaveAll();
    if (!result.success) {
      logger.error(`Failed to leave all meetings: ${result.error}`);
    }
    await this.refresh();
  }

  private async refreshCalendar(): Promise<void> {
    const result = await dbus.meet_refresh();
    if (!result.success) {
      logger.error(`Failed to refresh calendar: ${result.error}`);
    }
    await this.refresh();
  }
}
