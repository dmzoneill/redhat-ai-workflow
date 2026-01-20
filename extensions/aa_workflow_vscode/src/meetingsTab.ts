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
  status: "pending" | "approved" | "joined" | "ended" | "rejected";
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
 * Load meet bot state from file
 */
export function loadMeetBotState(): MeetBotState {
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
      display: flex;
      flex-direction: column;
      height: calc(100vh - 250px);
    }
    
    /* Sub-tabs navigation */
    .meetings-subtabs {
      display: flex;
      gap: 4px;
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
      margin-bottom: 16px;
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
      flex: 1;
      overflow-y: auto;
    }
    
    .subtab-content.active {
      display: flex;
      flex-direction: column;
      gap: 16px;
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
    }
    
    .status-badge.pending {
      background: rgba(245, 158, 11, 0.2);
      color: var(--warning);
    }
    
    .status-badge.joined {
      background: rgba(99, 102, 241, 0.2);
      color: var(--accent);
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
    }
    
    .upcoming-meeting-row:hover {
      border-color: var(--accent);
      background: var(--bg-primary);
    }
    
    .upcoming-meeting-row.next-meeting {
      border-left: 4px solid var(--accent);
      background: linear-gradient(90deg, rgba(99, 102, 241, 0.1) 0%, var(--bg-secondary) 100%);
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
      min-width: 0;
    }
    
    .upcoming-meeting-title {
      font-weight: 500;
      font-size: 0.95rem;
      color: var(--text-primary);
      white-space: nowrap;
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
    }
    
    .upcoming-organizer,
    .upcoming-calendar {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    
    .upcoming-meeting-actions {
      display: flex;
      gap: 8px;
      flex-shrink: 0;
      align-items: center;
    }
    
    .upcoming-meeting-actions .meeting-btn {
      padding: 6px 12px;
      font-size: 0.8rem;
    }
    
    .upcoming-meeting-actions .status-badge {
      margin-right: 8px;
    }
  `;
}

/**
 * Generate HTML for the Meetings tab content
 */
export function getMeetingsTabContent(state: MeetBotState): string {
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
  const upcomingMeetingsHtml = state.upcomingMeetings.length > 0
    ? state.upcomingMeetings.map((meeting, index) => {
        const meetingAny = meeting as any;
        const calendarName = meetingAny.calendarName || "";
        const isNext = index === 0;
        const meetUrlSafe = escapeHtml(meeting.url).replace(/'/g, "\\'");
        const titleSafe = escapeHtml(meeting.title).replace(/'/g, "\\'");
        return `
        <div class="upcoming-meeting-row ${isNext ? 'next-meeting' : ''}" data-meeting-id="${meeting.id}">
          <div class="upcoming-meeting-time">
            <div class="upcoming-time-main">${formatTime(meeting.startTime)}</div>
            <div class="upcoming-time-date">${formatDateShort(meeting.startTime)}</div>
          </div>
          <div class="upcoming-meeting-info">
            <div class="upcoming-meeting-title">
              ${isNext ? '<span class="next-badge">NEXT</span>' : ''}
              ${escapeHtml(meeting.title)}
            </div>
            <div class="upcoming-meeting-meta">
              <span class="upcoming-organizer">👤 ${escapeHtml(meeting.organizer)}</span>
              ${calendarName ? `<span class="upcoming-calendar">📅 ${escapeHtml(calendarName)}</span>` : ""}
            </div>
          </div>
          <div class="upcoming-meeting-actions">
            ${meeting.status === "pending" ? `
              <button class="meeting-btn approve" data-action="approve" data-id="${meeting.id}" data-url="${meetUrlSafe}">✓ Pre-approve</button>
              <button class="meeting-btn join" data-action="join" data-url="${meetUrlSafe}" data-title="${titleSafe}">🎥 Join</button>
            ` : meeting.status === "approved" ? `
              <span class="status-badge approved">✓ Approved</span>
              <button class="meeting-btn join" data-action="join" data-url="${meetUrlSafe}" data-title="${titleSafe}">🎥 Join</button>
            ` : `
              <span class="status-badge ${meeting.status}">${meeting.status}</span>
            `}
          </div>
        </div>
      `;
      }).join("")
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
          return `
          <div class="active-meeting-card ${isEndingSoon ? 'ending-soon' : ''}" data-session-id="${meeting.sessionId || ''}">
            <div class="active-meeting-card-header">
              <div class="active-meeting-title">${escapeHtml(meeting.title)}</div>
              <button class="btn-small danger" data-action="leave" data-session="${meeting.sessionId || ''}">🚪 Leave</button>
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
            <!-- Bot Status -->
            <div class="section">
              <h2 class="section-title">📊 Bot Status</h2>
              <div class="card">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                  <div class="status-indicator ${state.status === "idle" ? "idle" : state.status === "error" ? "" : "listening"}" 
                       style="${state.status === "error" ? "background: var(--error);" : ""}"></div>
                  <span style="font-weight: 600;">${state.status.charAt(0).toUpperCase() + state.status.slice(1)}</span>
                </div>
                ${state.error ? `<div style="color: var(--error); font-size: 0.8rem;">${escapeHtml(state.error)}</div>` : ""}
              </div>
            </div>
            
            <!-- Quick Join -->
            <div class="section">
              <h2 class="section-title">🚀 Quick Join</h2>
              <div style="display: flex; flex-direction: column; gap: 8px;">
                <input type="text" class="response-input" id="quickJoinUrl" placeholder="Paste Google Meet URL...">
                <button class="btn" onclick="quickJoin()">🎥 Join Meeting</button>
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
            <button class="btn" id="btn-refresh-upcoming">🔄 Refresh</button>
          </div>
          <p style="color: var(--text-secondary); font-size: 0.85rem; margin-top: 4px;">
            Pre-approve meetings to auto-join, or join immediately
          </p>
        </div>
        <div class="upcoming-meetings-list">
          ${upcomingMeetingsHtml}
        </div>
      </div>
      
      <!-- History Tab -->
      <div class="subtab-content" id="subtab-history">
        <div class="section" style="margin-bottom: 16px;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <h2 class="section-title" style="margin: 0;">📝 Meeting History</h2>
            <button class="btn" onclick="searchNotes()">🔍 Search</button>
          </div>
        </div>
        <div class="notes-list" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px;">
          ${notesHtml}
        </div>
      </div>
      
      <!-- Settings Tab -->
      <div class="subtab-content" id="subtab-settings">
        <div class="meetings-two-col">
          <div class="meetings-sidebar">
            <!-- Mode Toggle -->
            <div class="section">
              <h2 class="section-title">🤖 Bot Mode</h2>
              <div class="mode-toggle">
                <div class="mode-btn ${isNotesMode ? "active" : ""}" onclick="setMode('notes')">
                  <div class="mode-btn-icon">📝</div>
                  <div class="mode-btn-label">Notes</div>
                  <div class="mode-btn-desc">Capture only</div>
                </div>
                <div class="mode-btn ${!isNotesMode ? "active" : ""}" onclick="setMode('interactive')">
                  <div class="mode-btn-icon">🎤</div>
                  <div class="mode-btn-label">Interactive</div>
                  <div class="mode-btn-desc">AI Voice</div>
                </div>
              </div>
            </div>
            
            <!-- Monitored Calendars -->
            <div class="section">
              <h2 class="section-title">📆 Monitored Calendars</h2>
              <div class="calendar-list">
                ${calendarsHtml}
              </div>
              <button class="btn" style="margin-top: 8px; width: 100%;" onclick="addCalendar()">
                ➕ Add Calendar
              </button>
            </div>
          </div>
          
          <div class="meetings-main">
            <!-- Quick Actions -->
            <div class="section">
              <h2 class="section-title">⚙️ Quick Actions</h2>
              <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px;">
                <button class="btn" onclick="refreshState()">🔄 Refresh State</button>
                <button class="btn" onclick="testTTS()">🔊 Test Voice</button>
                <button class="btn" onclick="testAvatar()">🎬 Test Avatar</button>
                <button class="btn" onclick="preloadJira()">📋 Preload Jira</button>
              </div>
            </div>
            
            <!-- Stats -->
            <div class="section">
              <h2 class="section-title">📊 Statistics</h2>
              <div class="card">
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; text-align: center;">
                  <div>
                    <div style="font-size: 1.5rem; font-weight: 600;">${state.monitoredCalendars.length}</div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary);">Calendars</div>
                  </div>
                  <div>
                    <div style="font-size: 1.5rem; font-weight: 600;">${upcomingCount}</div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary);">Upcoming</div>
                  </div>
                  <div>
                    <div style="font-size: 1.5rem; font-weight: 600;">${historyCount}</div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary);">Recorded</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
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
    
    function joinMeetingNow(meetUrl, title) {
      vscode.postMessage({ type: 'joinMeetingNow', meetUrl, title });
    }
    
    function quickJoin() {
      const input = document.getElementById('quickJoinUrl');
      if (input && input.value.trim()) {
        const url = input.value.trim();
        vscode.postMessage({ type: 'joinMeetingNow', meetUrl: url, title: 'Manual Join' });
        input.value = '';
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
    
    function refreshState() {
      vscode.postMessage({ type: 'refreshState' });
    }
    
    function testTTS() {
      vscode.postMessage({ type: 'testTTS' });
    }
    
    function testAvatar() {
      vscode.postMessage({ type: 'testAvatar' });
    }
    
    function preloadJira() {
      vscode.postMessage({ type: 'preloadJira' });
    }
    
    // Notes Mode Functions
    function setMode(mode) {
      vscode.postMessage({ type: 'setMode', mode });
    }
    
    function startScheduler() {
      vscode.postMessage({ type: 'startScheduler' });
    }
    
    function stopScheduler() {
      vscode.postMessage({ type: 'stopScheduler' });
    }
    
    function addCalendar() {
      vscode.postMessage({ type: 'addCalendar' });
    }
    
    function viewNote(noteId) {
      vscode.postMessage({ type: 'viewNote', noteId });
    }
    
    function searchNotes() {
      vscode.postMessage({ type: 'searchNotes' });
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
      
      // Refresh button on upcoming tab
      const refreshBtn = document.getElementById('btn-refresh-upcoming');
      if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshState);
      }
      
      // Event delegation for upcoming meetings list buttons
      const upcomingList = document.querySelector('.upcoming-meetings-list');
      if (upcomingList) {
        upcomingList.addEventListener('click', function(e) {
          const target = e.target;
          if (target.tagName === 'BUTTON' && target.dataset.action) {
            const action = target.dataset.action;
            if (action === 'approve') {
              approveMeeting(target.dataset.id, target.dataset.url);
            } else if (action === 'join') {
              joinMeetingNow(target.dataset.url, target.dataset.title);
            }
          }
        });
      }
      
      // Event delegation for active meetings buttons
      const activeMeetingsGrid = document.querySelector('.active-meetings-grid');
      if (activeMeetingsGrid) {
        activeMeetingsGrid.addEventListener('click', function(e) {
          const target = e.target;
          if (target.tagName === 'BUTTON' && target.dataset.action === 'leave') {
            leaveMeeting(target.dataset.session);
          }
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


