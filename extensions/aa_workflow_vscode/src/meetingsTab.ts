/**
 * Meetings Tab for Command Center
 *
 * Provides UI for the Google Meet Bot:
 * - Upcoming meetings list with approve/reject
 * - Active meeting panel with live transcription
 * - Avatar video preview
 * - Response controls
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// Meet bot state file
const MEET_BOT_STATE_FILE = path.join(
  os.homedir(),
  ".local",
  "share",
  "meet_bot",
  "state.json"
);

export interface Meeting {
  id: string;
  title: string;
  url: string;
  startTime: string;
  endTime?: string;
  organizer: string;
  attendees: string[];
  status: "pending" | "approved" | "joined" | "ended" | "rejected" | "missed" | "skipped" | "scheduled" | "failed" | "active";
  approvedAt?: string;
}

export interface Caption {
  speaker: string;
  text: string;
  timestamp: string;
}

export interface ActiveMeeting extends Meeting {
  sessionId: string;
  captionsCount: number;
  durationMinutes: number;
}

export interface TechnicalIntegration {
  name: string;
  status: "ready" | "not_ready" | "error" | "unknown";
  details?: string;
  path?: string;
  error?: string;
}

export interface VirtualDevicesStatus {
  pulseaudio: TechnicalIntegration;
  audioSink: TechnicalIntegration;
  audioSource: TechnicalIntegration;
  v4l2loopback: TechnicalIntegration;
  virtualCamera: TechnicalIntegration;
  ffmpeg: TechnicalIntegration;
  pipewire?: TechnicalIntegration;
}

export interface MeetBotState {
  currentMeeting: Meeting | null;  // Backward compatibility
  currentMeetings: ActiveMeeting[];  // Multiple active meetings
  activeMeetingCount: number;
  upcomingMeetings: Meeting[];
  captions: Caption[];
  isListening: boolean;
  lastWakeWord: string | null;
  responseQueue: string[];
  gpuUsage: number;
  vramUsage: number;
  status: "idle" | "joining" | "in_meeting" | "responding" | "error";
  error: string | null;
  // Notes mode additions
  schedulerRunning: boolean;
  monitoredCalendars: MonitoredCalendar[];
  recentNotes: MeetingNote[];
  botMode: "interactive" | "notes";
  // Countdown data (from unified state)
  nextMeeting?: Meeting | null;
  countdown?: string | null;
  countdownSeconds?: number | null;
  lastPoll?: string | null;
  // Technical integrations status
  virtualDevices?: VirtualDevicesStatus;
}

export interface MonitoredCalendar {
  id: string;
  calendarId: string;
  name: string;
  autoJoin: boolean;
  enabled: boolean;
}

export interface MeetingNote {
  id: number;
  title: string;
  date: string;
  duration: number;
  transcriptCount: number;
  status: string;
}

/**
 * Parse virtual devices status from unified state data
 */
function parseVirtualDevicesStatus(data: any): VirtualDevicesStatus | undefined {
  if (!data) {
    return undefined;
  }

  const parseStatus = (value: any): TechnicalIntegration => {
    if (typeof value === "boolean") {
      return {
        name: "",
        status: value ? "ready" : "not_ready",
      };
    }
    if (typeof value === "object" && value !== null) {
      return {
        name: value.name || "",
        status: value.status || (value.ready ? "ready" : "not_ready"),
        details: value.details,
        path: value.path,
        error: value.error,
      };
    }
    return { name: "", status: "unknown" };
  };

  return {
    pulseaudio: parseStatus(data.pulseaudio ?? data.pulseaudioRunning),
    audioSink: parseStatus(data.audioSink ?? data.audioSinkReady),
    audioSource: parseStatus(data.audioSource ?? data.audioSourceReady),
    v4l2loopback: parseStatus(data.v4l2loopback ?? data.v4l2loopbackLoaded),
    virtualCamera: {
      ...parseStatus(data.virtualCamera ?? data.virtualCameraReady),
      path: data.virtualCameraPath || data.videoDevicePath || "/dev/video10",
    },
    ffmpeg: parseStatus(data.ffmpeg ?? data.ffmpegAvailable),
    pipewire: data.pipewire ? parseStatus(data.pipewire) : undefined,
  };
}

/**
 * Load meet bot state from unified workspace state or fallback to file.
 *
 * @param unifiedMeetData - Meet data from workspace_states.json (preferred)
 */
export function loadMeetBotState(unifiedMeetData?: any): MeetBotState {
  // If unified data is provided, use it (preferred - always fresh)
  if (unifiedMeetData && Object.keys(unifiedMeetData).length > 0) {
    // Parse virtual devices status if available
    const virtualDevices = parseVirtualDevicesStatus(unifiedMeetData.virtualDevices);

    return {
      currentMeeting: unifiedMeetData.currentMeeting || null,
      currentMeetings: unifiedMeetData.currentMeetings || [],
      activeMeetingCount: unifiedMeetData.currentMeetings?.length || 0,
      upcomingMeetings: (unifiedMeetData.upcomingMeetings || []).map((m: any) => ({
        id: m.id || "",
        title: m.title || "Untitled",
        url: m.url || "",
        startTime: m.startTime || "",
        endTime: m.endTime || "",
        organizer: m.organizer || "",
        attendees: m.attendees || [],
        status: m.status || "pending",
        calendarName: m.calendarName || "",
      })),
      captions: (unifiedMeetData.captions || []).map((c: any) => ({
        speaker: c.speaker || "Unknown",
        text: c.text || "",
        timestamp: c.timestamp || "",
      })),
      isListening: (unifiedMeetData.currentMeetings?.length || 0) > 0,
      lastWakeWord: null,
      responseQueue: [],
      gpuUsage: 0,
      vramUsage: 0,
      status: (unifiedMeetData.currentMeetings?.length || 0) > 0 ? "in_meeting" : "idle",
      error: null,
      schedulerRunning: unifiedMeetData.schedulerRunning || false,
      monitoredCalendars: (unifiedMeetData.monitoredCalendars || []).map((c: any) => ({
        id: c.id || c.calendar_id || "",
        calendarId: c.calendarId || c.calendar_id || "",
        name: c.name || "",
        autoJoin: c.autoJoin || c.auto_join || false,
        enabled: c.enabled || false,
      })),
      recentNotes: (unifiedMeetData.recentNotes || []).map((note: any) => ({
        id: note.id || 0,
        title: note.title || "Untitled",
        date: note.date ? new Date(note.date).toLocaleDateString() : "",
        duration: Math.round(note.duration || 0),
        transcriptCount: note.transcriptCount || 0,
        actionItems: note.actionItems || 0,
        linkedIssues: note.linkedIssues || 0,
      })),
      botMode: "notes",
      // Add countdown data
      nextMeeting: unifiedMeetData.nextMeeting || null,
      countdown: unifiedMeetData.countdown || null,
      countdownSeconds: unifiedMeetData.countdownSeconds || null,
      lastPoll: unifiedMeetData.lastPoll || null,
      // Add virtual devices status
      virtualDevices: virtualDevices,
    } as MeetBotState;
  }

  // Fallback to file-based state (legacy)
  try {
    if (fs.existsSync(MEET_BOT_STATE_FILE)) {
      const content = fs.readFileSync(MEET_BOT_STATE_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) {
    console.error("Failed to load meet bot state:", e);
  }

  // Default state
  return {
    currentMeeting: null,
    currentMeetings: [],
    activeMeetingCount: 0,
    upcomingMeetings: [],
    captions: [],
    isListening: false,
    lastWakeWord: null,
    responseQueue: [],
    gpuUsage: 0,
    vramUsage: 0,
    status: "idle",
    error: null,
    schedulerRunning: false,
    monitoredCalendars: [],
    recentNotes: [],
    botMode: "notes",
  };
}

/**
 * Get CSS styles for the Meetings tab
 */
export function getMeetingsTabStyles(): string {
  return `
    /* ============================================ */
    /* Meetings Tab Styles */
    /* ============================================ */

    .meetings-container {
      display: block;
    }

    /* Sub-tabs navigation */
    .meetings-subtabs {
      display: flex;
      gap: 4px;
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
      margin-bottom: 16px;
      flex-shrink: 0; /* Don't shrink the tab bar */
    }

    .meetings-subtab {
      padding: 10px 20px;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      border-radius: 8px 8px 0 0;
      transition: all 0.2s;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .meetings-subtab:hover {
      background: var(--bg-secondary);
      color: var(--text-primary);
    }

    .meetings-subtab.active {
      background: var(--accent);
      color: white;
    }

    .meetings-subtab .badge {
      background: rgba(255,255,255,0.2);
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 0.75rem;
    }

    .meetings-subtab.active .badge {
      background: rgba(255,255,255,0.3);
    }

    /* Sub-tab content panels */
    .subtab-content {
      display: none;
    }

    .subtab-content.active {
      display: block;
    }

    /* History tab - just let content flow naturally */
    #subtab-history {
      max-height: none !important;
      height: auto !important;
      overflow: visible !important;
    }

    #subtab-history .section {
      flex-shrink: 0;
    }

    .meetings-sidebar {
      display: flex;
      flex-direction: column;
      gap: 16px;
      overflow-y: auto;
    }

    .meetings-main {
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    /* Two-column layout for some tabs */
    .meetings-two-col {
      display: grid;
      grid-template-columns: 350px 1fr;
      gap: 20px;
      flex: 1;
    }

    /* Meeting List */
    .meeting-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .meeting-item {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .meeting-item:hover {
      border-color: var(--accent);
      transform: translateX(4px);
    }

    .meeting-item.active {
      border-color: var(--success);
      background: rgba(16, 185, 129, 0.1);
    }

    .meeting-item.pending {
      border-left: 3px solid var(--warning);
    }

    .meeting-item.approved {
      border-left: 3px solid var(--success);
    }

    .meeting-title {
      font-weight: 600;
      font-size: 0.95rem;
      margin-bottom: 4px;
    }

    .meeting-time {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }

    .meeting-actions {
      display: flex;
      gap: 8px;
    }

    .meeting-btn {
      padding: 4px 12px;
      border-radius: 6px;
      border: none;
      font-size: 0.75rem;
      cursor: pointer;
      transition: all 0.2s;
    }

    .meeting-btn.approve {
      background: var(--success);
      color: white;
    }

    .meeting-btn.reject {
      background: var(--error);
      color: white;
    }

    .meeting-btn.join {
      background: var(--accent);
      color: white;
    }

    .meeting-btn:hover {
      opacity: 0.8;
      transform: scale(1.05);
    }

    .meeting-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
      transform: none;
    }

    .meeting-btn.loading {
      background: var(--text-secondary);
      pointer-events: none;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    .meeting-btn.loading::before {
      content: '';
      display: inline-block;
      width: 12px;
      height: 12px;
      border: 2px solid transparent;
      border-top-color: white;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin-right: 4px;
      vertical-align: middle;
    }

    /* Approved row styling */
    .upcoming-meeting-row.approved {
      opacity: 0.8;
      border-left-color: var(--success);
    }

    /* Active Meeting Panel */
    .active-meeting-panel {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      flex: 1;
      display: flex;
      flex-direction: column;
    }

    .active-meeting-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border);
    }

    .active-meeting-title {
      font-size: 1.1rem;
      font-weight: 600;
    }

    .active-meeting-status {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .status-indicator {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      animation: pulse 2s ease-in-out infinite;
    }

    .status-indicator.listening {
      background: var(--success);
      box-shadow: 0 0 10px var(--success);
    }

    .status-indicator.responding {
      background: var(--warning);
      box-shadow: 0 0 10px var(--warning);
    }

    .status-indicator.idle {
      background: var(--text-secondary);
    }

    /* Avatar Preview */
    .avatar-preview {
      width: 200px;
      height: 200px;
      border-radius: 12px;
      overflow: hidden;
      background: var(--bg-secondary);
      margin: 0 auto 16px;
      position: relative;
    }

    .avatar-preview video,
    .avatar-preview img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .avatar-overlay {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      padding: 8px;
      background: linear-gradient(transparent, rgba(0,0,0,0.8));
      color: white;
      font-size: 0.75rem;
      text-align: center;
    }

    /* Transcription Feed */
    .transcription-feed {
      flex: 1;
      overflow-y: auto;
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 12px;
      font-family: var(--vscode-editor-font-family);
      font-size: 0.85rem;
      max-height: 300px;
    }

    .caption-entry {
      margin-bottom: 8px;
      padding: 8px;
      border-radius: 6px;
      background: var(--bg-card);
    }

    .caption-speaker {
      font-weight: 600;
      color: var(--accent);
      margin-right: 8px;
    }

    .caption-time {
      font-size: 0.7rem;
      color: var(--text-secondary);
      float: right;
    }

    .caption-text {
      color: var(--text-primary);
    }

    .caption-entry.wake-word {
      border-left: 3px solid var(--warning);
      background: rgba(245, 158, 11, 0.1);
    }

    /* Response Controls */
    .response-controls {
      display: flex;
      gap: 12px;
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid var(--border);
    }

    .response-input {
      flex: 1;
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: var(--bg-secondary);
      color: var(--text-primary);
      font-size: 0.9rem;
    }

    .response-input:focus {
      outline: none;
      border-color: var(--accent);
    }

    .response-btn {
      padding: 10px 20px;
      border-radius: 8px;
      border: none;
      background: var(--accent);
      color: white;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }

    .response-btn:hover {
      opacity: 0.9;
      transform: scale(1.02);
    }

    .response-btn.danger {
      background: var(--error);
    }

    /* GPU Stats */
    .gpu-stats {
      display: flex;
      gap: 16px;
      margin-top: 12px;
    }

    .gpu-stat {
      flex: 1;
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 10px;
      text-align: center;
    }

    .gpu-stat-label {
      font-size: 0.7rem;
      color: var(--text-secondary);
      text-transform: uppercase;
      margin-bottom: 4px;
    }

    .gpu-stat-value {
      font-size: 1.1rem;
      font-weight: 600;
    }

    .gpu-bar {
      height: 4px;
      background: var(--bg-card);
      border-radius: 2px;
      margin-top: 6px;
      overflow: hidden;
    }

    .gpu-bar-fill {
      height: 100%;
      background: var(--accent);
      transition: width 0.3s;
    }

    /* No Meeting State */
    .no-meeting {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: var(--text-secondary);
      text-align: center;
    }

    .no-meeting-icon {
      font-size: 48px;
      margin-bottom: 16px;
      opacity: 0.5;
    }

    .no-meeting-text {
      font-size: 1rem;
      margin-bottom: 8px;
    }

    .no-meeting-hint {
      font-size: 0.85rem;
      opacity: 0.7;
    }

    /* Mode Toggle */
    .mode-toggle {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
    }

    .mode-btn {
      flex: 1;
      padding: 10px;
      border: 2px solid var(--border);
      border-radius: 8px;
      background: var(--bg-card);
      color: var(--text-primary);
      cursor: pointer;
      transition: all 0.2s;
      text-align: center;
    }

    .mode-btn:hover {
      border-color: var(--accent);
    }

    .mode-btn.active {
      border-color: var(--accent);
      background: rgba(99, 102, 241, 0.1);
    }

    .mode-btn-icon {
      font-size: 24px;
      margin-bottom: 4px;
    }

    .mode-btn-label {
      font-size: 0.85rem;
      font-weight: 600;
    }

    .mode-btn-desc {
      font-size: 0.7rem;
      color: var(--text-secondary);
    }

    /* Scheduler Status */
    .scheduler-status {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px;
      background: var(--bg-secondary);
      border-radius: 8px;
      margin-bottom: 12px;
    }

    .scheduler-status.running {
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid var(--success);
    }

    .scheduler-status.stopped {
      background: rgba(239, 68, 68, 0.1);
      border: 1px solid var(--error);
    }

    /* Calendar List */
    .calendar-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .calendar-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 10px;
      background: var(--bg-secondary);
      border-radius: 6px;
      font-size: 0.85rem;
    }

    .calendar-item .name {
      font-weight: 500;
    }

    .calendar-item .status {
      font-size: 0.75rem;
      color: var(--text-secondary);
    }

    /* Recent Notes */
    .notes-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
      max-height: 300px;
      overflow-y: auto;
    }

    .note-item {
      padding: 10px;
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .note-item:hover {
      border-color: var(--accent);
    }

    .note-title {
      font-weight: 600;
      font-size: 0.9rem;
      margin-bottom: 4px;
    }

    .note-meta {
      font-size: 0.75rem;
      color: var(--text-secondary);
    }

    /* ============================================ */
    /* Multi-Meeting Active Panel */
    /* ============================================ */

    .active-meetings-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }

    .active-meetings-count {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 1.1rem;
      font-weight: 600;
    }

    .active-meetings-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }

    .active-meeting-card {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-left: 4px solid var(--success);
      border-radius: 8px;
      padding: 12px 16px;
    }

    /* Meeting Screenshot Display */
    .meeting-screenshot {
      position: relative;
      width: 100%;
      aspect-ratio: 16/9;
      background: var(--bg-tertiary);
      border-radius: 6px;
      overflow: hidden;
      margin-bottom: 12px;
    }

    .meeting-screenshot img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .screenshot-overlay {
      position: absolute;
      bottom: 0;
      left: 0;
      right: 0;
      padding: 4px 8px;
      background: linear-gradient(transparent, rgba(0,0,0,0.7));
      font-size: 0.7rem;
      color: white;
      text-align: right;
    }

    .screenshot-time {
      opacity: 0.9;
    }

    .meeting-screenshot.placeholder {
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg-tertiary);
    }

    .screenshot-placeholder-content {
      text-align: center;
      color: var(--text-secondary);
    }

    .screenshot-placeholder-icon {
      font-size: 2rem;
      display: block;
      margin-bottom: 8px;
      opacity: 0.5;
    }

    .screenshot-placeholder-text {
      font-size: 0.75rem;
      opacity: 0.7;
    }

    .active-meeting-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 8px;
      margin-bottom: 8px;
    }

    .active-meeting-card .active-meeting-title {
      font-weight: 600;
      font-size: 0.95rem;
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .active-meeting-actions {
      display: flex;
      gap: 6px;
      flex-shrink: 0;
    }

    .audio-toggle {
      background: var(--bg-tertiary) !important;
      border: 1px solid var(--border) !important;
    }

    .audio-toggle.listening {
      background: var(--success) !important;
      border-color: var(--success) !important;
      color: white !important;
    }

    .active-meeting-stats {
      display: flex;
      gap: 16px;
      font-size: 0.8rem;
      color: var(--text-secondary);
      flex-wrap: wrap;
    }

    .active-meeting-card.ending-soon {
      border-left-color: var(--warning);
      background: linear-gradient(90deg, rgba(245, 158, 11, 0.1) 0%, var(--bg-secondary) 100%);
    }

    .time-remaining {
      font-weight: 500;
    }

    .time-remaining.warning {
      color: var(--warning);
      font-weight: 600;
    }

    .caption-meeting {
      background: var(--accent);
      color: white;
      padding: 1px 6px;
      border-radius: 4px;
      font-size: 0.7rem;
      margin-left: 8px;
    }

    .caption-hint {
      font-size: 0.75rem;
      color: var(--text-secondary);
      font-weight: normal;
    }

    /* ============================================ */
    /* Live Captions Panel */
    /* ============================================ */

    .live-captions-panel {
      flex: 1;
      display: flex;
      flex-direction: column;
      background: var(--bg-primary);
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow: hidden;
      min-height: 300px;
    }

    .live-captions-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      background: var(--bg-secondary);
      border-bottom: 1px solid var(--border);
    }

    .live-captions-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
      font-size: 0.95rem;
    }

    .live-indicator {
      width: 8px;
      height: 8px;
      background: var(--error);
      border-radius: 50%;
      animation: pulse-live 1.5s infinite;
    }

    @keyframes pulse-live {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.5; transform: scale(0.8); }
    }

    .caption-count {
      font-size: 0.75rem;
      color: var(--text-secondary);
      font-weight: normal;
      background: var(--bg-primary);
      padding: 2px 8px;
      border-radius: 10px;
    }

    .live-captions-actions {
      display: flex;
      gap: 8px;
    }

    .btn-small {
      padding: 4px 10px;
      font-size: 0.75rem;
      background: var(--bg-primary);
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--text-secondary);
      cursor: pointer;
      transition: all 0.2s;
    }

    .btn-small:hover {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }

    .live-captions-feed {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .live-caption-entry {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 12px;
      border-left: 3px solid var(--accent);
    }

    .caption-meta {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 6px;
    }

    .caption-speaker {
      font-weight: 600;
      font-size: 0.85rem;
      color: var(--accent);
    }

    .caption-time {
      font-size: 0.7rem;
      color: var(--text-secondary);
    }

    .caption-text {
      font-size: 0.9rem;
      line-height: 1.5;
      color: var(--text-primary);
    }

    .captions-placeholder {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      color: var(--text-secondary);
    }

    .captions-placeholder-icon {
      font-size: 3rem;
      margin-bottom: 12px;
      opacity: 0.5;
    }

    .captions-placeholder-text {
      font-size: 1rem;
      font-weight: 500;
      margin-bottom: 4px;
    }

    .captions-placeholder-hint {
      font-size: 0.8rem;
      opacity: 0.7;
    }

    .meeting-controls-row {
      display: flex;
      gap: 16px;
      align-items: center;
      margin-top: 16px;
    }

    .meeting-controls-row .response-controls {
      flex: 1;
    }

    .meeting-controls-row .gpu-stats {
      flex-shrink: 0;
    }

    /* Calendar and Status Badges */
    .calendar-badge {
      display: inline-block;
      background: var(--bg-secondary);
      color: var(--text-secondary);
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 0.7rem;
      margin-left: 8px;
    }

    .status-badge {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: 500;
    }

    .status-badge.approved {
      background: rgba(16, 185, 129, 0.2);
      color: var(--success);
      cursor: pointer;
      transition: all 0.2s;
    }

    .status-badge.approved:hover {
      background: rgba(239, 68, 68, 0.2);
      color: var(--error);
    }

    .status-badge.pending {
      background: rgba(245, 158, 11, 0.2);
      color: var(--warning);
    }

    .status-badge.joined {
      background: rgba(99, 102, 241, 0.2);
      color: var(--accent);
    }

    .status-badge.active {
      background: var(--success);
      color: white;
      font-weight: 600;
      animation: pulse-active 2s ease-in-out infinite;
    }

    .status-badge.missed,
    .status-badge.rejected,
    .status-badge.skipped {
      background: rgba(239, 68, 68, 0.2);
      color: var(--error);
      cursor: pointer;
      transition: all 0.2s;
    }

    .status-badge.missed:hover,
    .status-badge.rejected:hover,
    .status-badge.skipped:hover {
      background: rgba(16, 185, 129, 0.2);
      color: var(--success);
    }

    .status-badge.failed {
      background: rgba(239, 68, 68, 0.2);
      color: var(--error);
      cursor: pointer;
      transition: all 0.2s;
    }

    .status-badge.failed:hover {
      background: rgba(16, 185, 129, 0.2);
      color: var(--success);
    }

    /* Meeting organizer */
    .meeting-organizer {
      font-size: 0.75rem;
      color: var(--text-secondary);
      margin-bottom: 8px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    /* Improved meeting item for grid layout */
    .meeting-list .meeting-item {
      display: flex;
      flex-direction: column;
      height: 100%;
    }

    .meeting-list .meeting-actions {
      margin-top: auto;
      padding-top: 8px;
    }

    /* ============================================ */
    /* Upcoming Meetings List View */
    /* ============================================ */

    .upcoming-meetings-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .upcoming-meeting-row {
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 12px 16px;
      background: var(--bg-secondary);
      border-radius: 8px;
      border: 1px solid var(--border);
      transition: all 0.2s;
      flex-wrap: nowrap;
    }

    .upcoming-meeting-row:hover {
      border-color: var(--accent);
      background: var(--bg-primary);
    }

    .upcoming-meeting-row.next-meeting {
      border-left: 4px solid var(--accent);
      background: linear-gradient(90deg, rgba(99, 102, 241, 0.1) 0%, var(--bg-secondary) 100%);
    }

    .upcoming-meeting-row.active-meeting {
      border-left: 4px solid var(--success);
      background: linear-gradient(90deg, rgba(16, 185, 129, 0.15) 0%, var(--bg-secondary) 100%);
    }

    .active-badge {
      background: var(--success);
      color: white;
      font-size: 0.65rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      flex-shrink: 0;
      animation: pulse-active 2s ease-in-out infinite;
    }

    @keyframes pulse-active {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.7; }
    }

    .upcoming-meeting-time {
      min-width: 70px;
      text-align: center;
      flex-shrink: 0;
    }

    .upcoming-time-main {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    .upcoming-time-date {
      font-size: 0.7rem;
      color: var(--text-secondary);
      text-transform: uppercase;
    }

    .upcoming-meeting-info {
      flex: 1;
      min-width: 100px;
      overflow: hidden;
    }

    .upcoming-meeting-title {
      font-weight: 500;
      font-size: 0.95rem;
      color: var(--text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .next-badge {
      background: var(--accent);
      color: white;
      font-size: 0.65rem;
      font-weight: 700;
      padding: 2px 6px;
      border-radius: 4px;
      flex-shrink: 0;
    }

    .upcoming-meeting-meta {
      display: flex;
      gap: 16px;
      margin-top: 4px;
      font-size: 0.8rem;
      color: var(--text-secondary);
      flex-wrap: wrap;
    }

    .upcoming-organizer,
    .upcoming-calendar {
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .upcoming-meeting-controls {
      display: flex;
      flex-direction: row;
      gap: 6px;
      flex-shrink: 0;
      align-items: center;
      flex-wrap: nowrap;
      margin-left: auto;
    }

    .meeting-mode-selector {
      display: inline-flex;
      gap: 0;
      background: var(--bg-tertiary);
      border-radius: 6px;
      padding: 2px;
      flex-shrink: 0;
    }

    .meeting-mode-selector .mode-btn {
      padding: 4px 8px;
      font-size: 0.75rem;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s;
      white-space: nowrap;
    }

    .meeting-mode-selector .mode-btn:hover {
      background: var(--bg-secondary);
      color: var(--text-primary);
    }

    .meeting-mode-selector .mode-btn.active {
      background: var(--accent);
      color: white;
    }

    .upcoming-meeting-controls .meeting-btn {
      padding: 4px 10px;
      font-size: 0.75rem;
      white-space: nowrap;
      flex-shrink: 0;
    }

    .upcoming-meeting-controls .status-badge {
      margin: 0;
      white-space: nowrap;
      flex-shrink: 0;
      font-size: 0.75rem;
    }

    /* Countdown Display */
    .countdown-display {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 16px;
      background: linear-gradient(135deg, var(--accent) 0%, rgba(99, 102, 241, 0.8) 100%);
      border-radius: 8px;
      color: white;
      font-weight: 500;
    }

    .countdown-label {
      font-size: 0.8rem;
      opacity: 0.9;
    }

    .countdown-value {
      font-size: 1.1rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }

    .countdown-display.starting-soon {
      background: linear-gradient(135deg, var(--warning) 0%, rgba(245, 158, 11, 0.8) 100%);
      animation: pulse-countdown 1.5s ease-in-out infinite;
    }

    .countdown-display.starting-now {
      background: linear-gradient(135deg, var(--success) 0%, rgba(16, 185, 129, 0.8) 100%);
      animation: pulse-countdown 0.8s ease-in-out infinite;
    }

    @keyframes pulse-countdown {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.02); }
    }

    /* History List Styles */
    .history-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-height: none !important;
      height: auto !important;
      overflow: visible !important;
    }

    .history-item {
      background: var(--bg-secondary);
      border-radius: 8px;
      padding: 16px;
      border-left: 3px solid var(--accent);
    }

    .history-item-header {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin-bottom: 8px;
    }

    .history-item-title {
      font-weight: 600;
      font-size: 1rem;
      color: var(--text-primary);
      line-height: 1.3;
    }

    .history-item-date {
      font-size: 0.8rem;
      color: var(--text-secondary);
    }

    .history-item-meta {
      display: flex;
      gap: 16px;
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-bottom: 12px;
    }

    .history-item-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .history-item-actions .btn-small {
      padding: 4px 10px;
      font-size: 0.75rem;
      background: var(--bg-tertiary);
      border: 1px solid var(--border);
      border-radius: 4px;
      color: var(--text-primary);
      cursor: pointer;
      transition: all 0.2s;
    }

    .history-item-actions .btn-small:hover {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }

    /* Settings Styles */
    .settings-row {
      margin-bottom: 12px;
    }

    .settings-row label {
      display: block;
      font-weight: 500;
      margin-bottom: 6px;
      color: var(--text-primary);
    }

    .mode-toggle-inline {
      display: flex;
      gap: 4px;
      background: var(--bg-tertiary);
      border-radius: 6px;
      padding: 2px;
      width: fit-content;
    }

    .mode-btn-inline {
      padding: 6px 14px;
      font-size: 0.85rem;
      border: none;
      background: transparent;
      color: var(--text-secondary);
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s;
    }

    .mode-btn-inline:hover {
      background: var(--bg-secondary);
      color: var(--text-primary);
    }

    .mode-btn-inline.active {
      background: var(--accent);
      color: white;
    }

    /* ============================================ */
    /* Technical Integrations Section */
    /* ============================================ */

    .integrations-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 12px;
    }

    .integration-card {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
    }

    .integration-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }

    .integration-name {
      font-weight: 600;
      font-size: 0.9rem;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .integration-status {
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.8rem;
      font-weight: 500;
    }

    .integration-status.ready {
      color: var(--success);
    }

    .integration-status.not-ready {
      color: var(--error);
    }

    .integration-status.unknown {
      color: var(--text-secondary);
    }

    .integration-status.error {
      color: var(--error);
    }

    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
    }

    .status-dot.ready {
      background: var(--success);
      box-shadow: 0 0 6px var(--success);
    }

    .status-dot.not-ready {
      background: var(--error);
    }

    .status-dot.unknown {
      background: var(--text-secondary);
    }

    .status-dot.error {
      background: var(--error);
      animation: pulse 2s ease-in-out infinite;
    }

    .integration-details {
      font-size: 0.75rem;
      color: var(--text-secondary);
      margin-top: 4px;
    }

    .integration-path {
      font-family: var(--vscode-editor-font-family);
      font-size: 0.7rem;
      color: var(--text-secondary);
      background: var(--bg-tertiary);
      padding: 2px 6px;
      border-radius: 4px;
      margin-top: 6px;
      display: inline-block;
      word-break: break-all;
    }

    .integration-error {
      font-size: 0.75rem;
      color: var(--error);
      margin-top: 6px;
      padding: 6px 8px;
      background: rgba(239, 68, 68, 0.1);
      border-radius: 4px;
    }

    .integration-section {
      margin-bottom: 20px;
    }

    .integration-section-title {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 10px;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border);
    }

    .integration-actions {
      display: flex;
      gap: 8px;
      margin-top: 16px;
    }

    .integration-info-box {
      background: var(--bg-secondary);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      margin-top: 12px;
    }

    .integration-info-box h4 {
      font-size: 0.85rem;
      font-weight: 600;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .integration-info-box p {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin: 4px 0;
      line-height: 1.5;
    }

    .integration-info-box code {
      font-family: var(--vscode-editor-font-family);
      font-size: 0.75rem;
      background: var(--bg-tertiary);
      padding: 1px 4px;
      border-radius: 3px;
    }

    .integration-info-box ul {
      margin: 8px 0;
      padding-left: 20px;
    }

    .integration-info-box li {
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin: 4px 0;
    }
  `;
}

/**
 * Render a single integration card
 */
function renderIntegrationCard(
  icon: string,
  name: string,
  status: "ready" | "not_ready" | "error" | "unknown",
  details?: string,
  path?: string,
  error?: string
): string {
  const statusText = status === "ready" ? "Ready" :
                     status === "not_ready" ? "Not Ready" :
                     status === "error" ? "Error" : "Unknown";
  const statusClass = status === "ready" ? "ready" :
                      status === "not_ready" ? "not-ready" :
                      status === "error" ? "error" : "unknown";

  return `
    <div class="integration-card">
      <div class="integration-card-header">
        <span class="integration-name">${icon} ${escapeHtml(name)}</span>
        <span class="integration-status ${statusClass}">
          <span class="status-dot ${statusClass}"></span>
          ${statusText}
        </span>
      </div>
      ${details ? `<div class="integration-details">${escapeHtml(details)}</div>` : ""}
      ${path ? `<div class="integration-path">${escapeHtml(path)}</div>` : ""}
      ${error ? `<div class="integration-error">⚠️ ${escapeHtml(error)}</div>` : ""}
    </div>
  `;
}

/**
 * Render the Technical Integrations section for Settings tab
 */
function renderTechnicalIntegrations(state: MeetBotState): string {
  const devices = state.virtualDevices;

  // Default status when no data available
  const defaultStatus: TechnicalIntegration = { name: "", status: "unknown" };

  // Get individual device statuses or defaults
  const pulseaudio = devices?.pulseaudio || { ...defaultStatus, name: "PulseAudio" };
  const audioSink = devices?.audioSink || { ...defaultStatus, name: "Virtual Audio Sink" };
  const audioSource = devices?.audioSource || { ...defaultStatus, name: "Virtual Audio Source" };
  const v4l2loopback = devices?.v4l2loopback || { ...defaultStatus, name: "v4l2loopback" };
  const virtualCamera = devices?.virtualCamera || { ...defaultStatus, name: "Virtual Camera" };
  const ffmpeg = devices?.ffmpeg || { ...defaultStatus, name: "FFmpeg" };
  const pipewire = devices?.pipewire;

  return `
    <!-- Audio Devices Section -->
    <div class="integration-section">
      <div class="integration-section-title">🔊 Audio Devices</div>
      <div class="integrations-grid">
        ${renderIntegrationCard(
          "🎵",
          "PulseAudio",
          pulseaudio.status,
          "Audio server for virtual device routing",
          undefined,
          pulseaudio.error
        )}
        ${renderIntegrationCard(
          "📥",
          "Virtual Audio Sink",
          audioSink.status,
          "Captures meeting audio for transcription (meet_bot_sink)",
          audioSink.path,
          audioSink.error
        )}
        ${renderIntegrationCard(
          "📤",
          "Virtual Audio Source",
          audioSource.status,
          "Bot voice output to meeting microphone (meet_bot_source)",
          audioSource.path,
          audioSource.error
        )}
        ${pipewire ? renderIntegrationCard(
          "🔗",
          "PipeWire",
          pipewire.status,
          "Modern audio/video routing (optional)",
          pipewire.path,
          pipewire.error
        ) : ""}
      </div>

      <div class="integration-info-box">
        <h4>ℹ️ About PulseAudio Virtual Devices</h4>
        <p>The meet bot uses PulseAudio to create virtual audio devices:</p>
        <ul>
          <li><strong>meet_bot_sink</strong> - A null sink that captures all meeting audio for real-time transcription</li>
          <li><strong>meet_bot_source</strong> - A pipe source that injects bot TTS audio into the meeting as microphone input</li>
        </ul>
        <p>These are created automatically when the bot starts. If missing, run: <code>meet_bot_setup_devices</code></p>
      </div>
    </div>

    <!-- Video Devices Section -->
    <div class="integration-section">
      <div class="integration-section-title">📹 Video Devices</div>
      <div class="integrations-grid">
        ${renderIntegrationCard(
          "🎬",
          "v4l2loopback",
          v4l2loopback.status,
          "Kernel module for virtual camera support",
          undefined,
          v4l2loopback.error
        )}
        ${renderIntegrationCard(
          "📷",
          "Virtual Camera",
          virtualCamera.status,
          "Virtual webcam device for avatar video",
          virtualCamera.path || "/dev/video10",
          virtualCamera.error
        )}
        ${renderIntegrationCard(
          "🎥",
          "FFmpeg",
          ffmpeg.status,
          "Video encoding/streaming to virtual camera",
          undefined,
          ffmpeg.error
        )}
      </div>

      <div class="integration-info-box">
        <h4>ℹ️ About Virtual Camera (v4l2loopback)</h4>
        <p>The bot uses a virtual camera to display an avatar in Google Meet:</p>
        <ul>
          <li><strong>v4l2loopback</strong> - Linux kernel module that creates a fake webcam device</li>
          <li><strong>/dev/video10</strong> - The virtual camera device (MeetBot_Camera)</li>
          <li><strong>FFmpeg</strong> - Streams avatar video (static image or lip-sync) to the virtual camera</li>
        </ul>
        <p>To load the kernel module: <code>sudo modprobe v4l2loopback devices=1 video_nr=10 card_label=MeetBot_Camera</code></p>
      </div>
    </div>

    <!-- Browser Integration Section -->
    <div class="integration-section">
      <div class="integration-section-title">🌐 Browser Integration</div>
      <div class="integration-info-box">
        <h4>🤖 Chrome Fake Device Flags</h4>
        <p>The bot launches Chrome with special flags to use the virtual devices:</p>
        <ul>
          <li><code>--use-fake-device-for-media-stream</code> - Use fake/virtual devices instead of real hardware</li>
          <li><code>--use-fake-ui-for-media-stream</code> - Auto-approve camera/mic permissions</li>
          <li><code>--use-file-for-fake-video-capture=/path/to/video</code> - Optional: use a video file as camera input</li>
        </ul>
        <p>The bot automatically selects the virtual camera and microphone when joining meetings.</p>
      </div>
    </div>

    <!-- Actions -->
    <div class="integration-actions">
      <button class="btn btn-primary" onclick="refreshDeviceStatus()">🔄 Refresh Status</button>
      <button class="btn btn-primary" onclick="setupDevices()">🔧 Setup Devices</button>
      <button class="btn btn-primary" onclick="testVirtualCamera()">📷 Test Camera</button>
      <button class="btn btn-primary" onclick="testVirtualAudio()">🔊 Test Audio</button>
    </div>
  `;
}

/**
 * Generate HTML for the Meetings tab content
 * @param state - The meet bot state
 * @param webview - Optional webview for converting local file URIs (for screenshots)
 */
export function getMeetingsTabContent(state: MeetBotState, webview?: vscode.Webview): string {
  const avatarImage = path.join(
    os.homedir(),
    "Documents",
    "Identification",
    "IMG_3249_.jpg"
  );

  const isNotesMode = state.botMode === "notes";
  const upcomingCount = state.upcomingMeetings.length;
  const historyCount = state.recentNotes.length;

  // Format upcoming meetings for the Upcoming tab - list view sorted by time
  // Each meeting has: mode selector (Notes/Interactive), approval, and join controls
  const upcomingMeetingsHtml = state.upcomingMeetings.length > 0
    ? (() => {
        const now = new Date();
        // Find the first meeting that hasn't ended yet (next upcoming)
        let nextMeetingIndex = -1;
        for (let i = 0; i < state.upcomingMeetings.length; i++) {
          const m = state.upcomingMeetings[i];
          const startTime = new Date(m.startTime);
          if (startTime > now) {
            nextMeetingIndex = i;
            break;
          }
        }

        return state.upcomingMeetings.map((meeting, index) => {
        const meetingAny = meeting as any;
        const calendarName = meetingAny.calendarName || "";
        const startTime = new Date(meeting.startTime);
        const endTime = meeting.endTime ? new Date(meeting.endTime) : null;
        // Meeting is active if it has started but not ended
        const isActive = startTime <= now && (!endTime || endTime > now);
        // Meeting is next if it's the first one that hasn't started yet
        const isNext = index === nextMeetingIndex && !isActive;
        const meetUrlSafe = escapeHtml(meeting.url).replace(/'/g, "\\'");
        const titleSafe = escapeHtml(meeting.title).replace(/'/g, "\\'");
        const meetingMode = meetingAny.botMode || "notes"; // Default to notes
        const isApproved = meeting.status === "approved";
        const statusStr = meeting.status as string;
        const isScheduled = statusStr === "scheduled" || statusStr === "pending";
        return `
        <div class="upcoming-meeting-row ${isActive ? 'active-meeting' : ''} ${isNext ? 'next-meeting' : ''}" data-meeting-id="${meeting.id}">
          <div class="upcoming-meeting-time">
            <div class="upcoming-time-main">${formatTime(meeting.startTime)}</div>
            <div class="upcoming-time-date">${formatDateShort(meeting.startTime)}</div>
          </div>
          <div class="upcoming-meeting-info">
            <div class="upcoming-meeting-title">
              ${isActive ? '<span class="active-badge">ACTIVE</span>' : isNext ? '<span class="next-badge">NEXT</span>' : ''}
              ${escapeHtml(meeting.title)}
            </div>
            <div class="upcoming-meeting-meta">
              <span class="upcoming-organizer">👤 ${escapeHtml(meeting.organizer)}</span>
              ${calendarName ? `<span class="upcoming-calendar">📅 ${escapeHtml(calendarName)}</span>` : ""}
            </div>
          </div>
          <div class="upcoming-meeting-controls">
            <!-- Mode selector + Approval + Join all on same line -->
            <div class="meeting-mode-selector" data-meeting-id="${meeting.id}">
              <button class="mode-btn ${meetingMode === 'notes' ? 'active' : ''}" data-mode="notes" data-id="${meeting.id}" title="Capture notes only">
                📝 Notes
              </button>
              <button class="mode-btn ${meetingMode === 'interactive' ? 'active' : ''}" data-mode="interactive" data-id="${meeting.id}" title="AI voice interaction">
                🎤 Interactive
              </button>
            </div>
            ${isScheduled ? `
              <button class="meeting-btn approve" data-action="approve" data-id="${meeting.id}" data-url="${meetUrlSafe}" data-mode="${meetingMode}">✓ Approve</button>
            ` : isApproved ? `
              <span class="status-badge approved" data-action="unapprove" data-id="${meeting.id}" title="Click to skip this meeting">✓ Approved</span>
            ` : (meeting.status === "rejected" || meeting.status === "missed" || meeting.status === "skipped") ? `
              <span class="status-badge skipped" data-action="approve" data-id="${meeting.id}" data-url="${meetUrlSafe}" data-mode="${meetingMode}" title="Click to approve this meeting">✗ Skipped</span>
            ` : meeting.status === "failed" ? `
              <span class="status-badge failed" data-action="approve" data-id="${meeting.id}" data-url="${meetUrlSafe}" data-mode="${meetingMode}" title="Join failed - click to retry">✗ Failed</span>
            ` : meeting.status === "active" ? `
              <span class="status-badge active">● Active</span>
            ` : `
              <span class="status-badge ${meeting.status}">${meeting.status}</span>
            `}
            <button class="meeting-btn join" data-action="join" data-url="${meetUrlSafe}" data-title="${titleSafe}" data-mode="${meetingMode}">🎥 Join Now</button>
          </div>
        </div>
      `;
      }).join("");
      })()
    : `<div class="no-meeting" style="padding: 40px; text-align: center;">
        <div class="no-meeting-icon">📅</div>
        <div class="no-meeting-text">No upcoming meetings</div>
        <div class="no-meeting-hint">Meetings from monitored calendars will appear here</div>
      </div>`;

  // Format captions
  const captionsHtml = state.captions.length > 0
    ? state.captions.slice(-20).map(caption => `
        <div class="caption-entry ${caption.text.toLowerCase().includes("david") ? "wake-word" : ""}">
          <span class="caption-time">${formatTime(caption.timestamp)}</span>
          <span class="caption-speaker">${escapeHtml(caption.speaker)}:</span>
          <span class="caption-text">${escapeHtml(caption.text)}</span>
        </div>
      `).join("")
    : `<div style="color: var(--text-secondary); text-align: center; padding: 20px;">
        Captions will appear here when in a meeting
      </div>`;

  // Get active meetings (use new array or fall back to single meeting)
  const activeMeetings = state.currentMeetings || (state.currentMeeting ? [state.currentMeeting] : []);
  const activeMeetingCount = activeMeetings.length;

  // Active meeting panel content - supports multiple meetings
  const activeMeetingContent = activeMeetingCount > 0
    ? `
      <!-- Active Meetings Header -->
      <div class="active-meetings-header">
        <div class="active-meetings-count">
          <span class="live-indicator"></span>
          🎥 ${activeMeetingCount} Active Meeting${activeMeetingCount > 1 ? 's' : ''}
        </div>
        ${activeMeetingCount > 1 ? `
          <button class="btn-small danger" id="btn-leave-all">🚪 Leave All</button>
        ` : ''}
      </div>

      <!-- Meeting Cards -->
      <div class="active-meetings-grid">
        ${activeMeetings.map((meeting: any, index: number) => {
          const timeRemaining = meeting.timeRemainingMinutes;
          const hasScheduledEnd = timeRemaining !== null && timeRemaining !== undefined;
          const isEndingSoon = hasScheduledEnd && timeRemaining < 10;
          const screenshotPath = meeting.screenshotPath;
          const screenshotUpdated = meeting.screenshotUpdated ? new Date(meeting.screenshotUpdated * 1000).toLocaleTimeString() : '';
          // Convert local file path to webview URI if webview is available
          let screenshotUri = '';
          console.log(`[Screenshot] Path: ${screenshotPath}, Webview available: ${!!webview}`);
          if (screenshotPath && webview) {
            try {
              const fileUri = vscode.Uri.file(screenshotPath);
              screenshotUri = webview.asWebviewUri(fileUri).toString();
              console.log(`[Screenshot] Converted URI: ${screenshotUri}`);
            } catch (e) {
              console.error('Failed to convert screenshot path:', e);
            }
          } else if (screenshotPath && !webview) {
            console.warn('[Screenshot] Webview not available for URI conversion');
          }
          return `
          <div class="active-meeting-card ${isEndingSoon ? 'ending-soon' : ''}" data-session-id="${meeting.sessionId || ''}">
            ${screenshotUri ? `
              <div class="meeting-screenshot">
                <img src="${screenshotUri}" alt="Meeting view" onerror="this.parentElement.innerHTML='<div class=\\'screenshot-placeholder-content\\'><span class=\\'screenshot-placeholder-icon\\'>📹</span><span class=\\'screenshot-placeholder-text\\'>Screenshot unavailable</span></div>'" />
                <div class="screenshot-overlay">
                  <span class="screenshot-time">📷 ${screenshotUpdated}</span>
                </div>
              </div>
            ` : `
              <div class="meeting-screenshot placeholder">
                <div class="screenshot-placeholder-content">
                  <span class="screenshot-placeholder-icon">📹</span>
                  <span class="screenshot-placeholder-text">Waiting for screenshot...</span>
                </div>
              </div>
            `}
            <div class="active-meeting-card-header">
              <div class="active-meeting-title">${escapeHtml(meeting.title)}</div>
              <div class="active-meeting-actions">
                <button class="btn-small audio-toggle" data-action="toggle-audio" data-session="${meeting.sessionId || ''}" title="Toggle meeting audio">
                  🔇 Listen
                </button>
                <button class="btn-small danger" data-action="leave" data-session="${meeting.sessionId || ''}">🚪 Leave</button>
              </div>
            </div>
            <div class="active-meeting-stats">
              <span>⏱️ ${(meeting.durationMinutes || 0).toFixed(1)} min</span>
              <span>💬 ${meeting.captionsCount || 0} captions</span>
              ${hasScheduledEnd ? `
                <span class="time-remaining ${isEndingSoon ? 'warning' : ''}">
                  ${isEndingSoon ? '⚠️' : '🕐'} ${Math.round(timeRemaining)} min left
                </span>
              ` : ''}
            </div>
          </div>
        `;}).join('')}
      </div>

      <!-- Live Captions Panel - Combined from all meetings -->
      <div class="live-captions-panel">
        <div class="live-captions-header">
          <div class="live-captions-title">
            <span class="live-indicator"></span>
            📝 Live Captions
            <span class="caption-count">${state.captions.length} entries</span>
            ${activeMeetingCount > 1 ? '<span class="caption-hint">(all meetings)</span>' : ''}
          </div>
          <div class="live-captions-actions">
            <button class="btn-small" id="btn-copy-transcript">📋 Copy</button>
            <button class="btn-small" id="btn-clear-captions">🗑️ Clear</button>
          </div>
        </div>
        <div class="live-captions-feed" id="transcriptionFeed">
          ${state.captions.length > 0 ? state.captions.map((caption: any) => `
            <div class="live-caption-entry">
              <div class="caption-meta">
                <span class="caption-speaker">${escapeHtml(caption.speaker)}</span>
                ${caption.meetingTitle && activeMeetingCount > 1 ? `<span class="caption-meeting">${escapeHtml(caption.meetingTitle)}</span>` : ''}
                <span class="caption-time">${formatTime(caption.timestamp)}</span>
              </div>
              <div class="caption-text">${escapeHtml(caption.text)}</div>
            </div>
          `).join("") : `
            <div class="captions-placeholder">
              <div class="captions-placeholder-icon">🎤</div>
              <div class="captions-placeholder-text">Waiting for captions...</div>
              <div class="captions-placeholder-hint">Captions will appear here as people speak</div>
            </div>
          `}
        </div>
      </div>
    `
    : `
      <div class="no-meeting">
        <div class="no-meeting-icon">🤖</div>
        <div class="no-meeting-text">Not in a meeting</div>
        <div class="no-meeting-hint">Approve and join a meeting from the sidebar</div>
      </div>
    `;

  // Generate calendars list for notes mode
  const calendarsHtml = state.monitoredCalendars.length > 0
    ? state.monitoredCalendars.map(cal => `
        <div class="calendar-item">
          <span class="name">${cal.enabled ? "✅" : "⏸️"} ${escapeHtml(cal.name)}</span>
          <span class="status">${cal.autoJoin ? "auto-join" : "manual"}</span>
        </div>
      `).join("")
    : `<div style="color: var(--text-secondary); font-size: 0.85rem; padding: 8px;">
        No calendars configured
      </div>`;

  // Generate recent notes list
  const notesHtml = state.recentNotes.length > 0
    ? state.recentNotes.map(note => `
        <div class="note-item" onclick="viewNote(${note.id})">
          <div class="note-title">${escapeHtml(note.title)}</div>
          <div class="note-meta">
            ${note.date} • ${note.duration} min • ${note.transcriptCount} entries
          </div>
        </div>
      `).join("")
    : `<div style="color: var(--text-secondary); font-size: 0.85rem; padding: 8px;">
        No meeting notes yet
      </div>`;

  return `
    <div class="meetings-container">
      <!-- Sub-tabs Navigation -->
      <div class="meetings-subtabs">
        <button class="meetings-subtab active" id="subtab-btn-current" data-tab="current">
          🎥 Current Meeting
        </button>
        <button class="meetings-subtab" id="subtab-btn-upcoming" data-tab="upcoming">
          📅 Upcoming
          ${upcomingCount > 0 ? `<span class="badge">${upcomingCount}</span>` : ""}
        </button>
        <button class="meetings-subtab" id="subtab-btn-history" data-tab="history">
          📝 History
          ${historyCount > 0 ? `<span class="badge">${historyCount}</span>` : ""}
        </button>
        <button class="meetings-subtab" id="subtab-btn-settings" data-tab="settings">
          ⚙️ Settings
        </button>
      </div>

      <!-- Current Meeting Tab -->
      <div class="subtab-content active" id="subtab-current">
        <div class="meetings-two-col">
          <div class="meetings-sidebar">
            <!-- Bot Status + Stats Combined -->
            <div class="section">
              <h2 class="section-title">📊 Bot Status</h2>
              <div class="card" id="bot-status-card">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
                  <div class="status-indicator ${state.status === "idle" ? "idle" : state.status === "error" ? "" : "listening"}"
                       id="bot-status-indicator"
                       style="${state.status === "error" ? "background: var(--error);" : ""}"></div>
                  <span style="font-weight: 600;" id="bot-status-text">${state.status.charAt(0).toUpperCase() + state.status.slice(1)}</span>
                </div>
                ${state.error ? `<div style="color: var(--error); font-size: 0.8rem; margin-bottom: 12px;">${escapeHtml(state.error)}</div>` : ""}
                <!-- Inline Stats -->
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; text-align: center; padding-top: 8px; border-top: 1px solid var(--border);">
                  <div>
                    <div style="font-size: 1.2rem; font-weight: 600;" id="stat-calendars">${state.monitoredCalendars.length}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary);">Calendars</div>
                  </div>
                  <div>
                    <div style="font-size: 1.2rem; font-weight: 600;" id="stat-upcoming">${upcomingCount}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary);">Upcoming</div>
                  </div>
                  <div>
                    <div style="font-size: 1.2rem; font-weight: 600;" id="stat-recorded">${historyCount}</div>
                    <div style="font-size: 0.7rem; color: var(--text-secondary);">Recorded</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Quick Join -->
            <div class="section">
              <h2 class="section-title">🚀 Quick Join</h2>
              <div style="display: flex; flex-direction: column; gap: 8px;">
                <input type="text" class="response-input" id="quickJoinUrl" placeholder="Paste Google Meet URL...">
                <div style="display: flex; gap: 8px; align-items: center;">
                  <label style="font-size: 0.85rem; color: var(--text-secondary);">Mode:</label>
                  <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
                    <input type="radio" name="quickJoinMode" value="notes" ${isNotesMode ? 'checked' : ''} style="margin: 0;">
                    <span style="font-size: 0.85rem;">📝 Notes</span>
                  </label>
                  <label style="display: flex; align-items: center; gap: 4px; cursor: pointer;">
                    <input type="radio" name="quickJoinMode" value="interactive" ${!isNotesMode ? 'checked' : ''} style="margin: 0;">
                    <span style="font-size: 0.85rem;">🎤 Interactive</span>
                  </label>
                </div>
                <button class="btn btn-primary" id="quickJoinBtn">🎥 Join Meeting</button>
              </div>
            </div>

            <!-- Scheduler Status -->
            <div class="section">
              <h2 class="section-title">🤖 Auto-Join Scheduler</h2>
              <div class="scheduler-status ${state.schedulerRunning ? "running" : "stopped"}">
                <div class="status-indicator ${state.schedulerRunning ? "listening" : "idle"}"></div>
                <span>${state.schedulerRunning ? "Running" : "Stopped"}</span>
                <button class="meeting-btn ${state.schedulerRunning ? "reject" : "approve"}"
                        onclick="${state.schedulerRunning ? "stopScheduler()" : "startScheduler()"}">
                  ${state.schedulerRunning ? "Stop" : "Start"}
                </button>
              </div>
            </div>

            <!-- Monitored Calendars -->
            <div class="section">
              <h2 class="section-title">📆 Monitored Calendars</h2>
              <div class="calendar-list">
                ${calendarsHtml}
              </div>
              <p style="font-size: 0.7rem; color: var(--text-secondary); margin-top: 8px;">
                Configure calendars in <code>config.json</code>
              </p>
            </div>

            <!-- Test Actions (useful when in a meeting) -->
            <div class="section">
              <h2 class="section-title">🔧 Test Actions</h2>
              ${state.currentMeetings && state.currentMeetings.length > 0 ? `
                <div style="margin-bottom: 12px;">
                  <label style="font-size: 0.8rem; color: var(--text-secondary); display: block; margin-bottom: 4px;">
                    Target Meeting:
                  </label>
                  <select id="test-target-meeting" class="meeting-select" style="width: 100%; padding: 6px 8px; border-radius: 4px; border: 1px solid var(--border); background: var(--bg-tertiary); color: var(--text-primary); font-size: 0.85rem;">
                    ${state.currentMeetings.map((m: any) => `
                      <option value="${m.sessionId || m.id || ''}">${escapeHtml(m.title || 'Untitled Meeting')}</option>
                    `).join('')}
                  </select>
                </div>
              ` : `
                <p style="font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 12px;">
                  No active meetings. Join a meeting to test actions.
                </p>
              `}
              <div style="display: flex; flex-direction: column; gap: 8px;">
                <button class="btn btn-primary" onclick="testTTS()" ${!state.currentMeetings?.length ? 'disabled' : ''}>🔊 Test Voice</button>
                <button class="btn btn-primary" onclick="testAvatar()" ${!state.currentMeetings?.length ? 'disabled' : ''}>🎬 Test Avatar</button>
                <button class="btn btn-primary" onclick="preloadJira()" ${!state.currentMeetings?.length ? 'disabled' : ''}>📋 Preload Jira</button>
              </div>
            </div>
          </div>

          <div class="meetings-main">
            <div class="active-meeting-panel">
              ${activeMeetingContent}
            </div>
          </div>
        </div>
      </div>

      <!-- Upcoming Meetings Tab -->
      <div class="subtab-content" id="subtab-upcoming">
        <div class="section" style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2 class="section-title" style="margin: 0;">📅 Upcoming Meetings</h2>
            ${state.nextMeeting ? `
              <div class="countdown-display" id="countdown-display" data-start-time="${state.nextMeeting.startTime || ''}">
                <span class="countdown-label">Next meeting in:</span>
                <span class="countdown-value" id="countdown-value">${state.countdown || 'calculating...'}</span>
              </div>
            ` : ''}
          </div>
          <p style="color: var(--text-secondary); font-size: 0.85rem; margin-top: 4px;">
            Pre-approve meetings to auto-join, or join immediately
          </p>
        </div>
        <div class="upcoming-meetings-list">
          ${upcomingMeetingsHtml}
        </div>
      </div>

      <!-- History Tab - Enhanced with notes, issues, and bot events -->
      <div class="subtab-content" id="subtab-history">
        <div class="section" style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2 class="section-title" style="margin: 0;">📝 Meeting History</h2>
            <div style="display: flex; gap: 8px;">
              <input type="text" class="response-input" id="historySearch" placeholder="Search meetings..." style="width: 200px;">
              <button class="btn btn-primary" onclick="searchNotes()">🔍 Search</button>
            </div>
          </div>
        </div>
        <div class="history-list">
          ${state.recentNotes.length > 0 ? state.recentNotes.map((note: any) => `
            <div class="history-item" data-note-id="${note.id}">
              <div class="history-item-header">
                <div class="history-item-title">${escapeHtml(note.title)}</div>
                <div class="history-item-date">${note.date}</div>
              </div>
              <div class="history-item-meta">
                <span>⏱️ ${note.duration} min</span>
                <span>💬 ${note.transcriptCount} entries</span>
                ${note.actionItems ? `<span>✅ ${note.actionItems} actions</span>` : ''}
                ${note.linkedIssues ? `<span>🎫 ${note.linkedIssues} issues</span>` : ''}
              </div>
              <div class="history-item-actions">
                <button class="btn-small" onclick="viewNote(${note.id})">📄 View Notes</button>
                <button class="btn-small" onclick="viewTranscript(${note.id})">📝 Transcript</button>
                <button class="btn-small" onclick="viewBotLog(${note.id})">🤖 Bot Log</button>
                ${note.linkedIssues ? `<button class="btn-small" onclick="viewLinkedIssues(${note.id})">🎫 Issues</button>` : ''}
              </div>
            </div>
          `).join('') : `
            <div class="no-meeting" style="padding: 40px; text-align: center;">
              <div class="no-meeting-icon">📝</div>
              <div class="no-meeting-text">No meeting notes yet</div>
              <div class="no-meeting-hint">Meeting transcripts and notes will appear here after the bot joins meetings</div>
            </div>
          `}
        </div>
      </div>

      <!-- Settings Tab - Simplified, most controls moved to other tabs -->
      <div class="subtab-content" id="subtab-settings">
        <div class="section">
          <h2 class="section-title">⚙️ Bot Configuration</h2>
          <div class="card">
            <div class="settings-row">
              <label>Default Bot Mode</label>
              <div class="mode-toggle-inline">
                <button class="mode-btn-inline ${isNotesMode ? "active" : ""}" onclick="setDefaultMode('notes')">📝 Notes</button>
                <button class="mode-btn-inline ${!isNotesMode ? "active" : ""}" onclick="setDefaultMode('interactive')">🎤 Interactive</button>
              </div>
              <p style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;">
                Default mode for new meetings. Can be changed per-meeting in Upcoming tab.
              </p>
            </div>
            <div class="settings-row" style="margin-top: 16px;">
              <label>Auto-join Buffer</label>
              <div style="display: flex; align-items: center; gap: 8px;">
                <input type="number" class="response-input" id="joinBuffer" value="2" min="0" max="10" style="width: 60px;">
                <span style="font-size: 0.85rem; color: var(--text-secondary);">minutes before meeting start</span>
              </div>
            </div>
            <div class="settings-row" style="margin-top: 16px;">
              <label>Auto-leave Buffer</label>
              <div style="display: flex; align-items: center; gap: 8px;">
                <input type="number" class="response-input" id="leaveBuffer" value="1" min="0" max="10" style="width: 60px;">
                <span style="font-size: 0.85rem; color: var(--text-secondary);">minutes after meeting end</span>
              </div>
            </div>
          </div>
        </div>

        <div class="section" style="margin-top: 16px;">
          <h2 class="section-title">🔗 Jira Integration</h2>
          <div class="card">
            <div class="settings-row">
              <label>Jira Project</label>
              <input type="text" class="response-input" id="jiraProject" value="AAP" placeholder="e.g., AAP">
              <p style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;">
                Default project for linking meeting action items to Jira issues.
              </p>
            </div>
          </div>
        </div>

        <!-- Technical Integrations Section -->
        <div class="section" style="margin-top: 16px;">
          <h2 class="section-title">🔧 Technical Integrations</h2>

          ${renderTechnicalIntegrations(state)}
        </div>
      </div>
    </div>
  `;
}

/**
 * Get JavaScript for the Meetings tab
 */
export function getMeetingsTabScript(): string {
  return `
    // Sub-tab switching
    function switchMeetingsTab(tabName) {
      // Update tab buttons
      document.querySelectorAll('.meetings-subtab').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.tab === tabName) {
          btn.classList.add('active');
        }
      });

      // Update content panels
      document.querySelectorAll('.subtab-content').forEach(panel => {
        panel.classList.remove('active');
      });
      const targetPanel = document.getElementById('subtab-' + tabName);
      if (targetPanel) {
        targetPanel.classList.add('active');
      }
    }

    // Meetings Tab Functions
    function approveMeeting(meetingId, meetUrl) {
      vscode.postMessage({ type: 'approveMeeting', meetingId, meetUrl });
    }

    function rejectMeeting(meetingId) {
      vscode.postMessage({ type: 'rejectMeeting', meetingId });
    }

    function joinMeeting(meetingId) {
      vscode.postMessage({ type: 'joinMeeting', meetingId });
    }

    function joinMeetingNow(meetUrl, title, buttonElement) {
      // Show loading state on button if provided
      if (buttonElement) {
        buttonElement.disabled = true;
        buttonElement.classList.add('loading');
        buttonElement.innerHTML = '⏳ Joining...';
      }

      // Switch to Current Meeting tab immediately
      switchMeetingsTab('current');

      // Send join request to backend
      vscode.postMessage({ type: 'joinMeetingNow', meetUrl, title });
    }

    function quickJoin() {
      console.log('[quickJoin] Function called');
      const input = document.getElementById('quickJoinUrl');

      // Debug: log all radio buttons
      const allRadios = document.querySelectorAll('input[name="quickJoinMode"]');
      console.log('[quickJoin] All mode radios:', allRadios.length);
      allRadios.forEach((r, i) => {
        console.log('[quickJoin] Radio ' + i + ': value=' + r.value + ', checked=' + r.checked);
      });

      const modeRadio = document.querySelector('input[name="quickJoinMode"]:checked');
      const mode = modeRadio ? modeRadio.value : 'notes';
      console.log('[quickJoin] Selected mode radio:', modeRadio);
      console.log('[quickJoin] Mode value:', mode);

      if (input && input.value.trim()) {
        const url = input.value.trim();
        console.log('[quickJoin] Sending joinMeetingNow message with URL:', url, ', mode:', mode);
        // Switch to Current Meeting tab
        switchMeetingsTab('current');
        vscode.postMessage({ type: 'joinMeetingNow', meetUrl: url, title: 'Manual Join', mode: mode });
        input.value = '';
      } else {
        console.log('[quickJoin] No URL provided or input not found');
      }
    }

    function leaveMeeting(sessionId) {
      vscode.postMessage({ type: 'leaveMeeting', sessionId: sessionId || '' });
    }

    function leaveAllMeetings() {
      vscode.postMessage({ type: 'leaveAllMeetings' });
    }

    function sendManualResponse() {
      const input = document.getElementById('manualResponse');
      if (input && input.value.trim()) {
        vscode.postMessage({ type: 'sendResponse', text: input.value.trim() });
        input.value = '';
      }
    }

    function refreshCalendar() {
      vscode.postMessage({ type: 'refreshCalendar' });
    }

    function getSelectedMeetingSession() {
      const select = document.getElementById('test-target-meeting');
      return select ? select.value : '';
    }

    function testTTS() {
      const sessionId = getSelectedMeetingSession();
      vscode.postMessage({ type: 'testTTS', sessionId: sessionId });
    }

    function testAvatar() {
      const sessionId = getSelectedMeetingSession();
      vscode.postMessage({ type: 'testAvatar', sessionId: sessionId });
    }

    function preloadJira() {
      const sessionId = getSelectedMeetingSession();
      vscode.postMessage({ type: 'preloadJira', sessionId: sessionId });
    }

    // Notes Mode Functions
    function setMode(mode) {
      vscode.postMessage({ type: 'setMode', mode });
    }

    function setDefaultMode(mode) {
      vscode.postMessage({ type: 'setDefaultMode', mode });
      // Update UI
      document.querySelectorAll('.mode-btn-inline').forEach(btn => {
        btn.classList.remove('active');
      });
      const activeBtn = document.querySelector('.mode-btn-inline[onclick*="' + mode + '"]');
      if (activeBtn) activeBtn.classList.add('active');
    }

    function setMeetingMode(meetingId, mode) {
      vscode.postMessage({ type: 'setMeetingMode', meetingId, mode });
      // Update UI for this meeting's mode selector
      const selector = document.querySelector('.meeting-mode-selector[data-meeting-id="' + meetingId + '"]');
      if (selector) {
        selector.querySelectorAll('.mode-btn').forEach(btn => {
          btn.classList.remove('active');
          if (btn.dataset.mode === mode) btn.classList.add('active');
        });
      }
    }

    function startScheduler() {
      vscode.postMessage({ type: 'startScheduler' });
    }

    function stopScheduler() {
      vscode.postMessage({ type: 'stopScheduler' });
    }

    // History Functions
    function viewNote(noteId) {
      vscode.postMessage({ type: 'viewNote', noteId });
    }

    function viewTranscript(noteId) {
      vscode.postMessage({ type: 'viewTranscript', noteId });
    }

    function viewBotLog(noteId) {
      vscode.postMessage({ type: 'viewBotLog', noteId });
    }

    function viewLinkedIssues(noteId) {
      vscode.postMessage({ type: 'viewLinkedIssues', noteId });
    }

    function searchNotes() {
      const input = document.getElementById('historySearch');
      const query = input ? input.value.trim() : '';
      vscode.postMessage({ type: 'searchNotes', query });
    }

    function viewNote(noteId) {
      vscode.postMessage({ type: 'viewNote', noteId });
    }

    function searchNotes() {
      vscode.postMessage({ type: 'searchNotes' });
    }

    // Technical Integration Functions
    function refreshDeviceStatus() {
      vscode.postMessage({ type: 'refreshDeviceStatus' });
    }

    function setupDevices() {
      vscode.postMessage({ type: 'setupDevices' });
    }

    function testVirtualCamera() {
      vscode.postMessage({ type: 'testVirtualCamera' });
    }

    function testVirtualAudio() {
      vscode.postMessage({ type: 'testVirtualAudio' });
    }

    function joinNow() {
      const url = prompt('Enter Google Meet URL:');
      if (url) {
        vscode.postMessage({ type: 'joinMeetingNow', meetUrl: url, title: 'Manual Join' });
      }
    }

    function leaveNotesMode() {
      vscode.postMessage({ type: 'leaveNotesMode' });
    }

    function copyTranscript() {
      vscode.postMessage({ type: 'copyTranscript' });
    }

    function clearCaptions() {
      vscode.postMessage({ type: 'clearCaptions' });
    }

    // Auto-scroll transcription feed
    function scrollTranscription() {
      const feed = document.getElementById('transcriptionFeed');
      if (feed) {
        feed.scrollTop = feed.scrollHeight;
      }
    }

    // Auto-scroll on new captions
    const captionsObserver = new MutationObserver(function(mutations) {
      scrollTranscription();
    });

    // Initialize meetings tab event listeners
    function initMeetingsTab() {
      // Sub-tab buttons
      ['current', 'upcoming', 'history', 'settings'].forEach(tab => {
        const btn = document.getElementById('subtab-btn-' + tab);
        if (btn) {
          btn.addEventListener('click', () => switchMeetingsTab(tab));
        }
      });

      // Event delegation for upcoming meetings list buttons (including mode selectors)
      const upcomingList = document.querySelector('.upcoming-meetings-list');
      if (upcomingList) {
        upcomingList.addEventListener('click', function(e) {
          const target = e.target;

          // Handle mode selector buttons
          if (target.classList.contains('mode-btn') && target.dataset.mode) {
            const meetingId = target.dataset.id;
            const mode = target.dataset.mode;
            setMeetingMode(meetingId, mode);
            return;
          }

          // Handle status badge clicks (approved/missed toggle)
          if (target.classList.contains('status-badge') && target.dataset.action) {
            const action = target.dataset.action;
            const meetingId = target.dataset.id;
            const row = target.closest('.upcoming-meeting-row');

            if (action === 'unapprove') {
              // Toggle from approved to skipped
              target.outerHTML = '<span class="status-badge skipped" data-action="approve" data-id="' + meetingId + '" data-url="' + (target.dataset.url || '') + '" data-mode="notes" title="Click to approve this meeting">✗ Skipped</span>';
              if (row) {
                row.classList.remove('approved');
              }
              // Send to backend
              vscode.postMessage({ type: 'unapproveMeeting', meetingId: meetingId });
            } else if (action === 'approve') {
              // Toggle from skipped/failed back to approved
              target.outerHTML = '<span class="status-badge approved" data-action="unapprove" data-id="' + meetingId + '" title="Click to skip this meeting">✓ Approved</span>';
              if (row) {
                row.classList.add('approved');
              }
              // Send to backend
              vscode.postMessage({ type: 'approveMeeting', meetingId: meetingId, meetUrl: target.dataset.url, mode: target.dataset.mode || 'notes' });
            }
            return;
          }

          // Handle action buttons
          if (target.tagName === 'BUTTON' && target.dataset.action) {
            const action = target.dataset.action;
            const mode = target.dataset.mode || 'notes'; // Default to notes
            const meetingId = target.dataset.id;

            if (action === 'approve') {
              // Optimistic UI update - immediately show approved state
              const row = target.closest('.upcoming-meeting-row');
              const controlsDiv = target.closest('.upcoming-meeting-controls');
              const meetUrl = target.dataset.url || '';

              // Replace approve button with approved badge (clickable to toggle back)
              target.outerHTML = '<span class="status-badge approved" data-action="unapprove" data-id="' + meetingId + '" data-url="' + meetUrl + '" title="Click to skip this meeting">✓ Approved</span>';
              if (row) {
                row.classList.add('approved');
                row.dataset.meetingId = meetingId; // Store for potential revert
              }

              // Send to backend
              vscode.postMessage({ type: 'approveMeeting', meetingId: meetingId, meetUrl: meetUrl, mode: mode });
            } else if (action === 'join') {
              // Pass button element for loading state
              joinMeetingNow(target.dataset.url, target.dataset.title, target);
            }
          }
        });
      }

      // Event delegation for active meetings buttons
      const activeMeetingsGrid = document.querySelector('.active-meetings-grid');
      if (activeMeetingsGrid) {
        activeMeetingsGrid.addEventListener('click', function(e) {
          const target = e.target;
          if (target.tagName === 'BUTTON') {
            const action = target.dataset.action;
            if (action === 'leave') {
              leaveMeeting(target.dataset.session);
            } else if (action === 'toggle-audio') {
              toggleMeetingAudio(target);
            }
          }
        });
      }

      // Toggle meeting audio (mute/unmute)
      function toggleMeetingAudio(button) {
        const isListening = button.classList.contains('listening');
        const sessionId = button.dataset.session || '';

        // Optimistic UI update
        if (isListening) {
          button.classList.remove('listening');
          button.innerHTML = '🔇 Listen';
        } else {
          button.classList.add('listening');
          button.innerHTML = '🔊 Mute';
        }

        // Send to backend
        vscode.postMessage({
          type: isListening ? 'muteAudio' : 'unmuteAudio',
          sessionId: sessionId
        });
      }

      // Leave all button
      const leaveAllBtn = document.getElementById('btn-leave-all');
      if (leaveAllBtn) {
        leaveAllBtn.addEventListener('click', leaveAllMeetings);
      }

      // Copy transcript button
      const copyBtn = document.getElementById('btn-copy-transcript');
      if (copyBtn) {
        copyBtn.addEventListener('click', copyTranscript);
      }

      // Clear captions button
      const clearBtn = document.getElementById('btn-clear-captions');
      if (clearBtn) {
        clearBtn.addEventListener('click', clearCaptions);
      }

      // Quick Join button
      const quickJoinBtn = document.getElementById('quickJoinBtn');
      if (quickJoinBtn) {
        quickJoinBtn.addEventListener('click', quickJoin);
        console.log('[initMeetingsTab] Quick Join button listener attached');
      } else {
        console.log('[initMeetingsTab] Quick Join button NOT found');
      }

      // Start observing captions feed
      const feed = document.getElementById('transcriptionFeed');
      if (feed) {
        captionsObserver.observe(feed, { childList: true, subtree: true });
        scrollTranscription();
      }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', initMeetingsTab);
    } else {
      // DOM already loaded, init immediately
      setTimeout(initMeetingsTab, 50);
    }

    // ==================== LIVE COUNTDOWN TIMER ====================
    let countdownInterval = null;

    function formatCountdown(seconds) {
      if (seconds <= 0) return 'Starting now!';

      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      const secs = seconds % 60;

      if (hours > 0) {
        return hours + 'h ' + minutes + 'm';
      } else if (minutes > 0) {
        return minutes + 'm ' + secs + 's';
      } else {
        return secs + 's';
      }
    }

    function updateCountdown() {
      const countdownDisplay = document.getElementById('countdown-display');
      const countdownValue = document.getElementById('countdown-value');

      if (!countdownDisplay || !countdownValue) return;

      const startTime = countdownDisplay.dataset.startTime;
      if (!startTime) return;

      const now = new Date();
      const meetingStart = new Date(startTime);
      const diffMs = meetingStart.getTime() - now.getTime();
      const diffSeconds = Math.floor(diffMs / 1000);

      // Update the display
      countdownValue.textContent = formatCountdown(diffSeconds);

      // Update styling based on time remaining
      countdownDisplay.classList.remove('starting-soon', 'starting-now');
      if (diffSeconds <= 0) {
        countdownDisplay.classList.add('starting-now');
      } else if (diffSeconds <= 300) { // 5 minutes
        countdownDisplay.classList.add('starting-soon');
      }
    }

    function startCountdownTimer() {
      // Clear any existing interval
      if (countdownInterval) {
        clearInterval(countdownInterval);
      }

      // Update immediately
      updateCountdown();

      // Then update every second
      countdownInterval = setInterval(updateCountdown, 1000);
    }

    function stopCountdownTimer() {
      if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
      }
    }

    // Start the countdown timer when the page loads
    setTimeout(startCountdownTimer, 100);

    // Handle Enter key in inputs
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        if (e.target.id === 'manualResponse') {
          sendManualResponse();
        } else if (e.target.id === 'quickJoinUrl') {
          quickJoin();
        }
      }
    });

    // Handle messages from extension (for meeting approval/join responses)
    window.addEventListener('message', function(event) {
      const message = event.data;

      // Handle meeting approval response
      if (message.type === 'meetingApproved') {
        if (!message.success) {
          // Revert optimistic update on failure
          const row = document.querySelector('.upcoming-meeting-row[data-meeting-id="' + message.meetingId + '"]');
          if (row) {
            row.classList.remove('approved');
            const actionsDiv = row.querySelector('.upcoming-meeting-actions');
            if (actionsDiv && actionsDiv.dataset.originalHtml) {
              actionsDiv.innerHTML = actionsDiv.dataset.originalHtml;
            }
          }
          console.error('Meeting approval failed:', message.error);
        }
      }

      // Handle meeting unapproval response
      if (message.type === 'meetingUnapproved') {
        if (!message.success) {
          // Revert optimistic update on failure - change back to approved
          const skippedBadge = document.querySelector('.status-badge.skipped[data-id="' + message.meetingId + '"]');
          if (skippedBadge) {
            skippedBadge.outerHTML = '<span class="status-badge approved" data-action="unapprove" data-id="' + message.meetingId + '" title="Click to skip this meeting">✓ Approved</span>';
          }
          const row = document.querySelector('.upcoming-meeting-row[data-meeting-id="' + message.meetingId + '"]');
          if (row) {
            row.classList.add('approved');
          }
          console.error('Meeting unapproval failed:', message.error);
        }
      }

      // Handle meeting join response
      if (message.type === 'meetingJoining') {
        // Reset any loading buttons
        document.querySelectorAll('.meeting-btn.loading').forEach(btn => {
          btn.disabled = false;
          btn.classList.remove('loading');
          btn.innerHTML = '🎥 Join Now';
        });

        if (!message.success) {
          // Show error state in current meeting panel
          const panel = document.querySelector('.active-meeting-panel');
          if (panel) {
            const noMeeting = panel.querySelector('.no-meeting');
            if (noMeeting) {
              noMeeting.innerHTML = '<div class="no-meeting-icon" style="color: var(--error);">❌</div>' +
                '<div class="no-meeting-text">Failed to join meeting</div>' +
                '<div class="no-meeting-hint">' + (message.error || 'Unknown error') + '</div>';
            }
          }
          console.error('Meeting join failed:', message.error);
        }
      }

      // Handle full meetings state update
      if (message.type === 'meetingsUpdate' && message.state) {
        console.log('Meetings update received:', message.state);
        updateMeetingsUI(message.state);
      }

      // Handle audio state change response
      if (message.type === 'audioStateChanged') {
        const buttons = document.querySelectorAll('.audio-toggle[data-session="' + message.sessionId + '"], .audio-toggle[data-session=""]');
        buttons.forEach(function(btn) {
          if (message.error) {
            // Revert on error
            if (message.muted) {
              btn.classList.remove('listening');
              btn.innerHTML = '🔇 Listen';
            } else {
              btn.classList.add('listening');
              btn.innerHTML = '🔊 Mute';
            }
          }
          // Otherwise the optimistic update was correct
        });
      }
    });

    // Update specific UI elements without full re-render
    function updateMeetingsUI(state) {
      console.log('[MeetingsTab] updateMeetingsUI called with state:', state);

      // === UPDATE BOT STATUS SECTION ===
      // Update calendars count
      const calendarsCount = state.monitoredCalendars?.length || 0;
      const upcomingCount = state.upcomingMeetings?.length || 0;
      const historyCount = state.recentNotes?.length || 0;

      // Update stats using IDs
      const statCalendars = document.getElementById('stat-calendars');
      const statUpcoming = document.getElementById('stat-upcoming');
      const statRecorded = document.getElementById('stat-recorded');

      if (statCalendars) statCalendars.textContent = calendarsCount.toString();
      if (statUpcoming) statUpcoming.textContent = upcomingCount.toString();
      if (statRecorded) statRecorded.textContent = historyCount.toString();

      // Update bot status indicator (Idle/In Meeting)
      const hasActiveMeeting = (state.currentMeetings?.length || 0) > 0;
      const botStatusIndicator = document.getElementById('bot-status-indicator');
      const botStatusText = document.getElementById('bot-status-text');

      if (botStatusIndicator) {
        botStatusIndicator.className = 'status-indicator ' + (hasActiveMeeting ? 'listening' : 'idle');
      }
      if (botStatusText) {
        botStatusText.textContent = hasActiveMeeting ? 'In Meeting' : 'Idle';
      }

      // Update scheduler status
      const schedulerStatus = document.querySelector('.scheduler-status');
      if (schedulerStatus) {
        const isRunning = state.schedulerRunning || false;
        schedulerStatus.className = 'scheduler-status ' + (isRunning ? 'running' : 'stopped');

        const indicator = schedulerStatus.querySelector('.status-indicator');
        if (indicator) {
          indicator.className = 'status-indicator ' + (isRunning ? 'listening' : 'idle');
        }

        const statusText = schedulerStatus.querySelector('span');
        if (statusText) {
          statusText.textContent = isRunning ? 'Running' : 'Stopped';
        }

        const btn = schedulerStatus.querySelector('.meeting-btn');
        if (btn) {
          btn.className = 'meeting-btn ' + (isRunning ? 'reject' : 'approve');
          btn.textContent = isRunning ? 'Stop' : 'Start';
          btn.onclick = isRunning ? stopScheduler : startScheduler;
        }
      }

      // Update tab badges
      const upcomingBadge = document.querySelector('#subtab-btn-upcoming .badge');
      if (upcomingBadge) {
        upcomingBadge.textContent = upcomingCount.toString();
        upcomingBadge.style.display = upcomingCount > 0 ? 'inline' : 'none';
      } else if (upcomingCount > 0) {
        const upcomingBtn = document.getElementById('subtab-btn-upcoming');
        if (upcomingBtn && !upcomingBtn.querySelector('.badge')) {
          const badge = document.createElement('span');
          badge.className = 'badge';
          badge.textContent = upcomingCount.toString();
          upcomingBtn.appendChild(badge);
        }
      }

      const historyBadge = document.querySelector('#subtab-btn-history .badge');
      if (historyBadge) {
        historyBadge.textContent = historyCount.toString();
        historyBadge.style.display = historyCount > 0 ? 'inline' : 'none';
      }

      // === UPDATE LIVE CAPTIONS ===
      const captionsFeed = document.getElementById('transcriptionFeed');
      const captionCountEl = document.querySelector('.caption-count');

      if (captionsFeed && state.captions) {
        const captionsHtml = state.captions.length > 0
          ? state.captions.map(function(caption) {
              const time = caption.timestamp ? new Date(caption.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) : '';
              return '<div class="caption-entry">' +
                '<div class="caption-speaker">' + escapeHtmlJS(caption.speaker || 'Unknown') + '</div>' +
                '<div class="caption-text">' + escapeHtmlJS(caption.text || '') + '</div>' +
                '<div class="caption-time">' + time + '</div>' +
              '</div>';
            }).join('')
          : '<div class="no-captions">No captions yet. Speak to see transcription...</div>';
        captionsFeed.innerHTML = captionsHtml;

        // Auto-scroll to bottom
        captionsFeed.scrollTop = captionsFeed.scrollHeight;
      }

      if (captionCountEl) {
        captionCountEl.textContent = (state.captions?.length || 0) + ' entries';
      }

      // === UPDATE MEETING STATS ON ACTIVE CARDS ===
      if (state.currentMeetings && state.currentMeetings.length > 0) {
        state.currentMeetings.forEach(function(meeting) {
          const card = document.querySelector('.active-meeting-card[data-session-id="' + (meeting.sessionId || meeting.id || '') + '"]');
          if (card) {
            const statsEl = card.querySelector('.active-meeting-stats');
            if (statsEl) {
              const durationSpan = statsEl.querySelector('span:first-child');
              const captionsSpan = statsEl.querySelector('span:nth-child(2)');
              if (durationSpan) {
                durationSpan.textContent = '⏱️ ' + (meeting.durationMinutes || 0).toFixed(1) + ' min';
              }
              if (captionsSpan) {
                captionsSpan.textContent = '💬 ' + (meeting.captionsCount || state.captions?.length || 0) + ' captions';
              }
            }
          }
        });
      }

      // === UPDATE MONITORED CALENDARS LIST ===
      const calendarsContainer = document.querySelector('.calendar-list');
      if (calendarsContainer && state.monitoredCalendars) {
        if (state.monitoredCalendars.length > 0) {
          calendarsContainer.innerHTML = state.monitoredCalendars.map(function(cal) {
            return '<div class="calendar-item">' +
              '<span class="name">' + (cal.enabled ? '✅' : '⏸️') + ' ' + escapeHtmlJS(cal.name) + '</span>' +
              '<span class="status">' + (cal.autoJoin || cal.auto_join ? 'auto-join' : 'manual') + '</span>' +
            '</div>';
          }).join('');
        } else {
          calendarsContainer.innerHTML = '<div style="color: var(--text-secondary); font-size: 0.85rem; padding: 8px;">No calendars configured</div>';
        }
      }

      // === UPDATE COUNTDOWN TIMER ===
      // Update the countdown display with new data and restart the timer
      const countdownDisplay = document.getElementById('countdown-display');
      if (countdownDisplay && state.nextMeeting && state.nextMeeting.startTime) {
        countdownDisplay.dataset.startTime = state.nextMeeting.startTime;
        // Restart the countdown timer with the updated time
        startCountdownTimer();
      }

      console.log('[MeetingsTab] UI updated - calendars:', calendarsCount, 'upcoming:', upcomingCount, 'history:', historyCount);
    }

    // Simple HTML escape for JS
    function escapeHtmlJS(text) {
      if (!text) return '';
      return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }
  `;
}

// Helper functions
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return timestamp;
  }
}

function formatDateTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);

    let dayStr = "";
    if (date.toDateString() === now.toDateString()) {
      dayStr = "Today";
    } else if (date.toDateString() === tomorrow.toDateString()) {
      dayStr = "Tomorrow";
    } else {
      dayStr = date.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    }

    const timeStr = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `${dayStr} ${timeStr}`;
  } catch {
    return timestamp;
  }
}

function formatDateShort(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);

    if (date.toDateString() === now.toDateString()) {
      return "Today";
    } else if (date.toDateString() === tomorrow.toDateString()) {
      return "Tomorrow";
    } else {
      return date.toLocaleDateString([], { weekday: "short", day: "numeric" });
    }
  } catch {
    return "";
  }
}
