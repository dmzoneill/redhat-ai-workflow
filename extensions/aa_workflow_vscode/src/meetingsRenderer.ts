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
import * as os from "os";
import { createLogger } from "./logger";

const logger = createLogger("MeetingsTabLegacy");

// ARCHITECTURE: Meet state is loaded via D-Bus from the Meet daemon.
// The commandCenter.ts uses dbus.meet_getState() for all meeting data.

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
 * ARCHITECTURE NOTE: Meet state is now loaded via D-Bus from the Meet daemon.
 * The commandCenter.ts uses dbus.meet_getState() and passes the result here.
 * The file-based fallback is DEPRECATED and should not be relied upon.
 *
 * @param unifiedMeetData - Meet data from D-Bus (preferred) or workspace_states.json
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

  // Default state - D-Bus is the primary source, no file fallback
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
 * NOTE: All CSS has been moved to src/webview/styles/unified.css
 */
export function getMeetingsTabStyles(): string {
  // All styles are now in unified.css
  return "";
}

// CSS REMOVED - See unified.css for all meeting styles
// The following classes are defined there:
// .meetings-container, .meetings-subtabs, .meeting-item, etc.


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

      <!-- Video Preview Panel -->
      <div class="video-preview-panel">
        <div class="video-preview-header">
          <h4>🎬 Video Preview</h4>
          <div class="video-preview-controls">
            <button class="btn btn-sm" id="btn-start-preview">▶️ Start</button>
            <button class="btn btn-sm" id="btn-stop-preview" disabled>⏹️ Stop</button>
            <button class="btn btn-sm" id="btn-flip-preview">🔄 Flip</button>
            <select id="video-preview-mode" class="video-device-select" title="Preview mode">
              <option value="webrtc">WebRTC (best)</option>
              <option value="mjpeg">MJPEG</option>
              <option value="snapshot">Snapshot</option>
            </select>
            <select id="video-preview-device" class="video-device-select">
              <option value="/dev/video10">/dev/video10</option>
              <option value="/dev/video11">/dev/video11</option>
              <option value="/dev/video12">/dev/video12</option>
            </select>
          </div>
        </div>
        <div class="video-preview-container" id="video-preview-container">
          <div class="video-preview-placeholder" id="video-preview-placeholder">
            <span class="placeholder-icon">📷</span>
            <span class="placeholder-text">Click "Start" to preview video output</span>
            <span class="placeholder-hint">WebRTC: Hardware-accelerated, low latency (~50ms)</span>
          </div>
          <video id="video-preview-webrtc" class="video-preview-frame d-none" autoplay playsinline muted></video>
          <img id="video-preview-frame" class="video-preview-frame d-none" alt="Video Preview" />
        </div>
        <div class="video-preview-status">
          <span id="video-preview-status-text">Status: Stopped</span>
          <span id="video-preview-fps">FPS: --</span>
          <span id="video-preview-resolution">Resolution: --</span>
          <span id="video-preview-latency" class="d-none">Latency: --</span>
        </div>
        <div class="video-preview-info text-sm text-secondary mt-8">
          <strong>WebRTC</strong>: Zero-copy Intel GPU encoding → H.264 → Browser (~6W, &lt;50ms latency)<br>
          <strong>MJPEG</strong>: Hardware JPEG encoding → HTTP stream (~8W, ~100ms latency)<br>
          <strong>Snapshot</strong>: Periodic frame capture via ffmpeg (~35W, ~500ms latency)
        </div>
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
      <button class="btn btn-sm" data-action="setupDevices">🔧 Setup Devices</button>
      <button class="btn btn-sm" data-action="testVirtualCamera">📷 Test Camera</button>
      <button class="btn btn-sm" data-action="testVirtualAudio">🔊 Test Audio</button>
    </div>
  `;
}

/**
 * Generate HTML for just the upcoming meetings list.
 * This is used for incremental updates without re-rendering the entire tab.
 * @param state - The meet bot state
 */
export function getUpcomingMeetingsHtml(state: MeetBotState): string {
  if (!state.upcomingMeetings || state.upcomingMeetings.length === 0) {
    return `<div class="empty-state">
      <div class="empty-state-icon">📅</div>
      <div class="empty-state-text">No upcoming meetings</div>
      <div class="hint-text">Meetings from monitored calendars will appear here</div>
    </div>`;
  }

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
  const upcomingCount = state.upcomingMeetings?.length || 0;
  const historyCount = state.recentNotes?.length || 0;

  // Format upcoming meetings for the Upcoming tab - use the shared function
  const upcomingMeetingsHtml = getUpcomingMeetingsHtml(state);

  // Format captions
  const captionsHtml = state.captions?.length > 0
    ? state.captions.slice(-20).map(caption => `
        <div class="caption-entry ${caption.text.toLowerCase().includes("david") ? "wake-word" : ""}">
          <span class="caption-time">${formatTime(caption.timestamp)}</span>
          <span class="caption-speaker">${escapeHtml(caption.speaker)}:</span>
          <span class="caption-text">${escapeHtml(caption.text)}</span>
        </div>
      `).join("")
    : `<div class="placeholder-centered">Captions will appear here when in a meeting</div>`;

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
            <span class="caption-count">${state.captions?.length || 0} entries</span>
            ${activeMeetingCount > 1 ? '<span class="caption-hint">(all meetings)</span>' : ''}
          </div>
          <div class="live-captions-actions">
            <button class="btn-small" id="btn-copy-transcript">📋 Copy</button>
            <button class="btn-small" id="btn-clear-captions">🗑️ Clear</button>
          </div>
        </div>
        <div class="live-captions-feed" id="transcriptionFeed">
          ${state.captions?.length > 0 ? state.captions.map((caption: any) => `
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
  const calendarsHtml = state.monitoredCalendars?.length > 0
    ? state.monitoredCalendars.map(cal => `
        <div class="calendar-item">
          <span class="name">${cal.enabled ? "✅" : "⏸️"} ${escapeHtml(cal.name)}</span>
          <span class="status">${cal.autoJoin ? "auto-join" : "manual"}</span>
        </div>
      `).join("")
    : `<div class="placeholder-text">No calendars configured</div>`;

  // Generate recent notes list
  const notesHtml = state.recentNotes?.length > 0
    ? state.recentNotes.map(note => `
        <div class="note-item" data-action="viewNote" data-note-id="${note.id}">
          <div class="note-title">${escapeHtml(note.title)}</div>
          <div class="note-meta">
            ${note.date} • ${note.duration} min • ${note.transcriptCount} entries
          </div>
        </div>
      `).join("")
    : `<div class="placeholder-text">No meeting notes yet</div>`;

  return `
    <div class="meetings-container">
      <!-- Meet Bot Header with Controls -->
      <div class="section mb-8">
        <div class="flex-between">
          <h2 class="section-title m-0">🎥 Meet Bot</h2>
          <div class="d-flex gap-8">
            <button class="btn btn-xs btn-ghost" data-action="serviceStart" data-service="meet">▶ Start</button>
            <button class="btn btn-xs btn-ghost" data-action="serviceStop" data-service="meet">⏹ Stop</button>
            <button class="btn btn-xs btn-ghost" data-action="serviceLogs" data-service="meet">📋 Logs</button>
          </div>
        </div>
      </div>

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
                <div class="d-flex items-center gap-8 mb-12">
                  <div class="status-indicator ${state.status === "idle" ? "idle" : state.status === "error" ? "bg-error" : "listening"}"
                       id="bot-status-indicator"></div>
                  <span class="font-semibold" id="bot-status-text">${(state.status || "unknown").charAt(0).toUpperCase() + (state.status || "unknown").slice(1)}</span>
                </div>
                ${state.error ? `<div class="text-error text-sm mb-12">${escapeHtml(state.error)}</div>` : ""}
                <!-- Inline Stats -->
                <div class="stats-grid">
                  <div>
                    <div class="stat-value" id="stat-calendars">${state.monitoredCalendars?.length || 0}</div>
                    <div class="stat-label">Calendars</div>
                  </div>
                  <div>
                    <div class="stat-value" id="stat-upcoming">${upcomingCount}</div>
                    <div class="stat-label">Upcoming</div>
                  </div>
                  <div>
                    <div class="stat-value" id="stat-recorded">${historyCount}</div>
                    <div class="stat-label">Recorded</div>
                  </div>
                </div>
              </div>
            </div>

            <!-- Quick Join -->
            <div class="section">
              <h2 class="section-title">🚀 Quick Join</h2>
              <div class="d-flex flex-col gap-8">
                <input type="text" class="response-input" id="quickJoinUrl" placeholder="Paste Google Meet URL...">
                <div class="form-row">
                  <label class="form-label">Mode:</label>
                  <label class="input-label">
                    <input type="radio" name="quickJoinMode" value="notes" ${isNotesMode ? 'checked' : ''}>
                    <span class="text-base">📝 Notes</span>
                  </label>
                  <label class="input-label">
                    <input type="radio" name="quickJoinMode" value="interactive" ${!isNotesMode ? 'checked' : ''}>
                    <span class="text-base">🎤 Interactive</span>
                  </label>
                </div>
                <div class="form-row">
                  <label class="input-label">
                    <input type="checkbox" id="quickJoinVideo">
                    <span class="text-base">📹 Enable Video Overlay</span>
                  </label>
                  <span class="text-sm text-secondary" title="When enabled, shows AI research overlay on virtual camera">(disabled by default)</span>
                </div>
                <button class="btn btn-sm btn-primary" id="quickJoinBtn" data-action="quickJoin">🎥 Join Meeting</button>
              </div>
            </div>

            <!-- Scheduler Status -->
            <div class="section">
              <h2 class="section-title">🤖 Auto-Join Scheduler</h2>
              <div class="scheduler-status ${state.schedulerRunning ? "running" : "stopped"}">
                <div class="status-indicator ${state.schedulerRunning ? "listening" : "idle"}"></div>
                <span>${state.schedulerRunning ? "Running" : "Stopped"}</span>
                <button class="meeting-btn ${state.schedulerRunning ? "reject" : "approve"}"
                        data-action="${state.schedulerRunning ? "stopScheduler" : "startScheduler"}">
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
              <p class="hint-text mt-8">
                Configure calendars in <code>config.json</code>
              </p>
            </div>

            <!-- Test Actions (useful when in a meeting) -->
            <div class="section">
              <h2 class="section-title">🔧 Test Actions</h2>
              ${state.currentMeetings && state.currentMeetings.length > 0 ? `
                <div class="mb-12">
                  <label class="form-label d-block mb-4">
                    Target Meeting:
                  </label>
                  <select id="test-target-meeting" class="meeting-select w-full">
                    ${state.currentMeetings.map((m: any) => `
                      <option value="${m.sessionId || m.id || ''}">${escapeHtml(m.title || 'Untitled Meeting')}</option>
                    `).join('')}
                  </select>
                </div>
              ` : `
                <p class="text-sm text-secondary mb-12">
                  No active meetings. Join a meeting to test actions.
                </p>
              `}
              <div class="d-flex flex-col gap-8">
                <button class="btn btn-sm" data-action="testTTS" ${!state.currentMeetings?.length ? 'disabled' : ''}>🔊 Test Voice</button>
                <button class="btn btn-sm" data-action="testAvatar" ${!state.currentMeetings?.length ? 'disabled' : ''}>🎬 Test Avatar</button>
                <button class="btn btn-sm" data-action="preloadJira" ${!state.currentMeetings?.length ? 'disabled' : ''}>📋 Preload Jira</button>
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
        <div class="section mb-16">
          <div class="flex-between">
            <h2 class="section-title m-0">📅 Upcoming Meetings</h2>
            ${state.nextMeeting ? `
              <div class="countdown-display" id="countdown-display" data-start-time="${state.nextMeeting.startTime || ''}">
                <span class="countdown-label">Next meeting in:</span>
                <span class="countdown-value" id="countdown-value">${state.countdown || 'calculating...'}</span>
              </div>
            ` : ''}
          </div>
          <p class="text-secondary text-base mt-4">
            Pre-approve meetings to auto-join, or join immediately
          </p>
        </div>
        <div class="upcoming-meetings-list">
          ${upcomingMeetingsHtml}
        </div>
      </div>

      <!-- History Tab - Enhanced with notes, issues, and bot events -->
      <div class="subtab-content" id="subtab-history">
        <div class="section mb-16">
          <div class="flex-between">
            <h2 class="section-title m-0">📝 Meeting History</h2>
            <div class="d-flex gap-8">
              <input type="text" class="response-input w-200" id="historySearch" placeholder="Search meetings...">
              <button class="btn btn-sm" data-action="searchNotes">🔍 Search</button>
            </div>
          </div>
        </div>
        <div class="history-list">
          ${state.recentNotes?.length > 0 ? state.recentNotes.map((note: any) => `
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
                <button class="btn-small" data-action="viewNote" data-note-id="${note.id}">📄 View Notes</button>
                <button class="btn-small" data-action="viewTranscript" data-note-id="${note.id}">📝 Transcript</button>
                <button class="btn-small" data-action="viewBotLog" data-note-id="${note.id}">🤖 Bot Log</button>
                ${note.linkedIssues ? `<button class="btn-small" data-action="viewLinkedIssues" data-note-id="${note.id}">🎫 Issues</button>` : ''}
              </div>
            </div>
          `).join('') : `
            <div class="empty-state">
              <div class="empty-state-icon">📝</div>
              <div class="empty-state-text">No meeting notes yet</div>
              <div class="hint-text">Meeting transcripts and notes will appear here after the bot joins meetings</div>
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
                <button class="mode-btn-inline ${isNotesMode ? "active" : ""}" data-action="setDefaultMode" data-mode="notes">📝 Notes</button>
                <button class="mode-btn-inline ${!isNotesMode ? "active" : ""}" data-action="setDefaultMode" data-mode="interactive">🎤 Interactive</button>
              </div>
              <p class="hint-text mt-4">
                Default mode for new meetings. Can be changed per-meeting in Upcoming tab.
              </p>
            </div>
            <div class="settings-row mt-16">
              <label>Auto-join Buffer</label>
              <div class="form-row">
                <input type="number" class="response-input w-60" id="joinBuffer" value="2" min="0" max="10">
                <span class="text-base text-secondary">minutes before meeting start</span>
              </div>
            </div>
            <div class="settings-row mt-16">
              <label>Auto-leave Buffer</label>
              <div class="form-row">
                <input type="number" class="response-input w-60" id="leaveBuffer" value="1" min="0" max="10">
                <span class="text-base text-secondary">minutes after meeting end</span>
              </div>
            </div>
          </div>
        </div>

        <div class="section mt-16">
          <h2 class="section-title">🔗 Jira Integration</h2>
          <div class="card">
            <div class="settings-row">
              <label>Jira Project</label>
              <input type="text" class="response-input" id="jiraProject" value="AAP" placeholder="e.g., AAP">
              <p class="hint-text mt-4">
                Default project for linking meeting action items to Jira issues.
              </p>
            </div>
          </div>
        </div>

        <!-- Technical Integrations Section -->
        <div class="section mt-16">
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
    // Use centralized event delegation system - handlers survive content updates
    (function() {
      const meetingsContainer = document.getElementById('meetings');
      if (!meetingsContainer) return;
      
      console.log('[MeetingsTab] Initializing with centralized event delegation...');
      
      // Use extraClickInit flag for the complex click handler that needs to be attached once
      // The TabEventDelegation system handles data-action clicks, but meetings has many
      // custom click handlers that need the traditional approach
      const needsInit = !meetingsContainer.dataset.meetingsExtraInit;
      if (needsInit) {
        meetingsContainer.dataset.meetingsExtraInit = 'true';
      }

      // Sub-tab switching
      function switchMeetingsTab(tabName) {
        // Update tab buttons
        meetingsContainer.querySelectorAll('.meetings-subtab').forEach(btn => {
          btn.classList.remove('active');
          if (btn.dataset.tab === tabName) {
            btn.classList.add('active');
          }
        });

        // Update content panels
        meetingsContainer.querySelectorAll('.subtab-content').forEach(panel => {
          panel.classList.remove('active');
        });
        const targetPanel = document.getElementById('subtab-' + tabName);
        if (targetPanel) {
          targetPanel.classList.add('active');
        }
      }
      
      // Expose for external calls
      window.switchMeetingsTab = switchMeetingsTab;

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

        // Get video enabled checkbox state (defaults to false/unchecked)
        // This uses the Quick Join video toggle as a global setting
        const videoCheckbox = document.getElementById('quickJoinVideo');
        const videoEnabled = videoCheckbox ? videoCheckbox.checked : false;

        // Switch to Current Meeting tab immediately
        switchMeetingsTab('current');

      // Send join request to backend
      vscode.postMessage({ type: 'joinMeetingNow', meetUrl, title, videoEnabled: videoEnabled });
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

      // Get video enabled checkbox state (defaults to false/unchecked)
      const videoCheckbox = document.getElementById('quickJoinVideo');
      const videoEnabled = videoCheckbox ? videoCheckbox.checked : false;
      console.log('[quickJoin] Video enabled:', videoEnabled);

      if (input && input.value.trim()) {
        const url = input.value.trim();
        console.log('[quickJoin] Sending joinMeetingNow message with URL:', url, ', mode:', mode, ', videoEnabled:', videoEnabled);
        // Switch to Current Meeting tab
        switchMeetingsTab('current');
        vscode.postMessage({ type: 'joinMeetingNow', meetUrl: url, title: 'Manual Join', mode: mode, videoEnabled: videoEnabled });
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

    // Video Preview Functions - WebRTC + MJPEG + Snapshot modes
    let videoPreviewInterval = null;
    let videoPreviewFlipped = false;
    let videoPreviewFrameCount = 0;
    let videoPreviewStartTime = null;
    let videoPreviewMode = 'webrtc';
    let webrtcPeerConnection = null;
    let webrtcSignalingWs = null;

    function startVideoPreview() {
      vscode.postMessage({ type: 'webviewLog', message: 'startVideoPreview() called' });

      const device = document.getElementById('video-preview-device').value;
      const modeSelect = document.getElementById('video-preview-mode');
      videoPreviewMode = modeSelect ? modeSelect.value : 'webrtc';

      vscode.postMessage({ type: 'webviewLog', message: 'Mode: ' + videoPreviewMode + ', Device: ' + device });

      const placeholder = document.getElementById('video-preview-placeholder');
      const videoEl = document.getElementById('video-preview-webrtc');
      const imgEl = document.getElementById('video-preview-frame');
      const statusText = document.getElementById('video-preview-status-text');
      const latencyText = document.getElementById('video-preview-latency');
      const startBtn = document.getElementById('btn-start-preview');
      const stopBtn = document.getElementById('btn-stop-preview');

      // Update UI
      placeholder.style.display = 'none';
      startBtn.disabled = true;
      stopBtn.disabled = false;
      statusText.textContent = 'Status: Connecting...';

      // Reset counters
      videoPreviewFrameCount = 0;
      videoPreviewStartTime = Date.now();

      if (videoPreviewMode === 'webrtc') {
        // WebRTC mode - hardware accelerated, lowest latency
        videoEl.style.display = 'block';
        imgEl.style.display = 'none';
        latencyText.style.display = 'inline';
        startWebRTCPreview(device);
      } else if (videoPreviewMode === 'mjpeg') {
        // MJPEG mode - HTTP stream
        imgEl.style.display = 'block';
        videoEl.style.display = 'none';
        latencyText.style.display = 'none';
        startMJPEGPreview(device);
      } else {
        // Snapshot mode - periodic frame capture (legacy)
        imgEl.style.display = 'block';
        videoEl.style.display = 'none';
        latencyText.style.display = 'none';
        startSnapshotPreview(device);
      }
    }

    async function startWebRTCPreview(device) {
      const statusText = document.getElementById('video-preview-status-text');
      const videoEl = document.getElementById('video-preview-webrtc');

      try {
        // Request backend to start streaming pipeline
        vscode.postMessage({ type: 'startVideoPreview', device: device, mode: 'webrtc' });

        // Connect to WebRTC signaling server
        const signalingPort = 8765;
        function webrtcLog(msg) {
          console.log('[WebRTC] ' + msg);
          vscode.postMessage({ type: 'webviewLog', message: '[WebRTC] ' + msg });
        }

        webrtcLog('Connecting to signaling server at ws://localhost:' + signalingPort);
        statusText.textContent = 'Status: Connecting to signaling...';

        try {
          webrtcSignalingWs = new WebSocket('ws://localhost:' + signalingPort);
        } catch (e) {
          webrtcLog('Failed to create WebSocket: ' + e);
          statusText.textContent = 'Status: WebSocket creation failed';
          return;
        }

        webrtcSignalingWs.onopen = async () => {
          webrtcLog('WebSocket connected to signaling server');
          statusText.textContent = 'Status: Signaling connected';

          // Create peer connection
          webrtcPeerConnection = new RTCPeerConnection({
            iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
          });

          // Handle incoming tracks
          webrtcPeerConnection.ontrack = (event) => {
            webrtcLog('Track received: ' + event.track.kind);
            if (event.track.kind === 'video') {
              videoEl.srcObject = event.streams[0];
              statusText.textContent = 'Status: Streaming (WebRTC)';

              // Start latency measurement
              measureWebRTCLatency();
            }
          };

          // Handle ICE candidates
          webrtcPeerConnection.onicecandidate = (event) => {
            if (event.candidate) {
              webrtcSignalingWs.send(JSON.stringify({
                type: 'ice-candidate',
                candidate: event.candidate.candidate,
                sdpMLineIndex: event.candidate.sdpMLineIndex
              }));
            }
          };

          // Request offer from server
          webrtcLog('Requesting offer from server');
          webrtcSignalingWs.send(JSON.stringify({ type: 'request_offer' }));
        };

        webrtcSignalingWs.onmessage = async (event) => {
          const data = JSON.parse(event.data);
          webrtcLog('Received message: ' + data.type);

          if (data.type === 'offer') {
            // Set remote description and create answer
            await webrtcPeerConnection.setRemoteDescription({
              type: 'offer',
              sdp: data.sdp
            });

            const answer = await webrtcPeerConnection.createAnswer();
            await webrtcPeerConnection.setLocalDescription(answer);

            webrtcSignalingWs.send(JSON.stringify({
              type: 'answer',
              sdp: answer.sdp
            }));

            statusText.textContent = 'Status: Negotiating...';
          } else if (data.type === 'ice-candidate' && data.candidate) {
            await webrtcPeerConnection.addIceCandidate({
              candidate: data.candidate,
              sdpMLineIndex: data.sdpMLineIndex
            });
          }
        };

        webrtcSignalingWs.onerror = (error) => {
          webrtcLog('Signaling error: ' + error);
          statusText.textContent = 'Status: Signaling error - check if video generator is running with --webrtc';
        };

        webrtcSignalingWs.onclose = (event) => {
          webrtcLog('Signaling closed, code: ' + event.code + ', reason: ' + event.reason);
          statusText.textContent = 'Status: Disconnected (code: ' + event.code + ')';
        };

      } catch (error) {
        console.error('WebRTC setup error:', error);
        statusText.textContent = 'Status: WebRTC error - ' + error.message;
      }
    }

    function measureWebRTCLatency() {
      const latencyText = document.getElementById('video-preview-latency');
      const fpsText = document.getElementById('video-preview-fps');
      const resText = document.getElementById('video-preview-resolution');
      const videoEl = document.getElementById('video-preview-webrtc');

      // Update stats periodically
      setInterval(() => {
        if (webrtcPeerConnection) {
          webrtcPeerConnection.getStats().then(stats => {
            stats.forEach(report => {
              if (report.type === 'inbound-rtp' && report.kind === 'video') {
                // Calculate FPS from frames received
                const fps = report.framesPerSecond || 0;
                fpsText.textContent = 'FPS: ' + fps.toFixed(1);

                // Get resolution
                if (report.frameWidth && report.frameHeight) {
                  resText.textContent = 'Resolution: ' + report.frameWidth + 'x' + report.frameHeight;
                }
              }

              if (report.type === 'candidate-pair' && report.state === 'succeeded') {
                // Get round-trip time (latency estimate)
                const rtt = report.currentRoundTripTime;
                if (rtt) {
                  latencyText.textContent = 'Latency: ' + (rtt * 1000).toFixed(0) + 'ms';
                }
              }
            });
          });
        }
      }, 1000);
    }

    function startMJPEGPreview(device) {
      const imgEl = document.getElementById('video-preview-frame');
      const statusText = document.getElementById('video-preview-status-text');

      // Request backend to start MJPEG server
      vscode.postMessage({ type: 'startVideoPreview', device: device, mode: 'mjpeg' });

      // Connect to MJPEG stream
      const mjpegPort = 8766;
      imgEl.src = 'http://localhost:' + mjpegPort + '/stream.mjpeg';
      imgEl.onload = () => {
        statusText.textContent = 'Status: Streaming (MJPEG)';
        videoPreviewFrameCount++;
        updatePreviewStats();
      };
      imgEl.onerror = () => {
        statusText.textContent = 'Status: MJPEG connection failed';
      };
    }

    function startSnapshotPreview(device) {
      const statusText = document.getElementById('video-preview-status-text');

      // Request backend to start snapshot mode
      vscode.postMessage({ type: 'startVideoPreview', device: device, mode: 'snapshot' });

      // Start polling for frames (legacy mode)
      videoPreviewInterval = setInterval(() => {
        vscode.postMessage({ type: 'getVideoPreviewFrame' });
      }, 100); // 10 FPS preview

      statusText.textContent = 'Status: Polling...';
    }

    function updatePreviewStats() {
      const fpsText = document.getElementById('video-preview-fps');
      const elapsed = (Date.now() - videoPreviewStartTime) / 1000;
      if (elapsed > 0) {
        const fps = (videoPreviewFrameCount / elapsed).toFixed(1);
        fpsText.textContent = 'FPS: ' + fps;
      }
    }

    function stopVideoPreview() {
      const placeholder = document.getElementById('video-preview-placeholder');
      const videoEl = document.getElementById('video-preview-webrtc');
      const imgEl = document.getElementById('video-preview-frame');
      const statusText = document.getElementById('video-preview-status-text');
      const fpsText = document.getElementById('video-preview-fps');
      const latencyText = document.getElementById('video-preview-latency');
      const startBtn = document.getElementById('btn-start-preview');
      const stopBtn = document.getElementById('btn-stop-preview');

      // Stop polling interval
      if (videoPreviewInterval) {
        clearInterval(videoPreviewInterval);
        videoPreviewInterval = null;
      }

      // Close WebRTC connection
      if (webrtcPeerConnection) {
        webrtcPeerConnection.close();
        webrtcPeerConnection = null;
      }
      if (webrtcSignalingWs) {
        webrtcSignalingWs.close();
        webrtcSignalingWs = null;
      }

      // Clear video element
      if (videoEl.srcObject) {
        videoEl.srcObject.getTracks().forEach(track => track.stop());
        videoEl.srcObject = null;
      }

      // Update UI
      placeholder.style.display = 'flex';
      videoEl.style.display = 'none';
      imgEl.style.display = 'none';
      latencyText.style.display = 'none';
      startBtn.disabled = false;
      stopBtn.disabled = true;
      statusText.textContent = 'Status: Stopped';
      fpsText.textContent = 'FPS: --';

      // Tell backend to stop
      vscode.postMessage({ type: 'stopVideoPreview' });
    }

    function toggleVideoFlip() {
      const videoEl = document.getElementById('video-preview-webrtc');
      const imgEl = document.getElementById('video-preview-frame');
      videoPreviewFlipped = !videoPreviewFlipped;

      if (videoPreviewFlipped) {
        videoEl.classList.add('flipped');
        imgEl.classList.add('flipped');
      } else {
        videoEl.classList.remove('flipped');
        imgEl.classList.remove('flipped');
      }
    }

    function updateVideoPreviewFrame(dataUrl, resolution) {
      const imgEl = document.getElementById('video-preview-frame');
      const statusText = document.getElementById('video-preview-status-text');
      const fpsText = document.getElementById('video-preview-fps');
      const resText = document.getElementById('video-preview-resolution');

      if (dataUrl) {
        imgEl.src = dataUrl;
        statusText.textContent = 'Status: Streaming (Snapshot)';

        // Update FPS
        videoPreviewFrameCount++;
        updatePreviewStats();

        // Update resolution
        if (resolution) {
          resText.textContent = 'Resolution: ' + resolution;
        }
      }
    }

    // Handle messages from extension
    // Only attach once using the needsInit flag
    if (needsInit) window.addEventListener('message', event => {
      const message = event.data;
      if (message.type === 'videoPreviewFrame') {
        updateVideoPreviewFrame(message.dataUrl, message.resolution);
      } else if (message.type === 'videoPreviewError') {
        const statusText = document.getElementById('video-preview-status-text');
        statusText.textContent = 'Status: Error - ' + message.error;
        stopVideoPreview();
      } else if (message.type === 'videoPreviewStarted') {
        const statusText = document.getElementById('video-preview-status-text');
        statusText.textContent = 'Status: Pipeline started';
      }
    });

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

      // Container-level click delegation for ALL meetings interactions
      // Only attach once using the needsInit flag
      if (needsInit) meetingsContainer.addEventListener('click', function(e) {
        const target = e.target;
        
        // Sub-tab buttons
        const subtabBtn = target.closest('.meetings-subtab');
        if (subtabBtn && subtabBtn.dataset.tab) {
          switchMeetingsTab(subtabBtn.dataset.tab);
          return;
        }
        
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

        // Handle action buttons (use closest to handle clicks on button content like emojis)
        const button = target.closest('button[data-action]');
        if (button) {
          const action = button.dataset.action;
          const mode = button.dataset.mode || 'notes'; // Default to notes
          const meetingId = button.dataset.id;

          if (action === 'approve') {
            // Optimistic UI update - immediately show approved state
            const row = button.closest('.upcoming-meeting-row');
            const controlsDiv = button.closest('.upcoming-meeting-controls');
            const meetUrl = button.dataset.url || '';

            // Replace approve button with approved badge (clickable to toggle back)
            button.outerHTML = '<span class="status-badge approved" data-action="unapprove" data-id="' + meetingId + '" data-url="' + meetUrl + '" title="Click to skip this meeting">✓ Approved</span>';
            if (row) {
              row.classList.add('approved');
              row.dataset.meetingId = meetingId; // Store for potential revert
            }

            // Send to backend
            vscode.postMessage({ type: 'approveMeeting', meetingId: meetingId, meetUrl: meetUrl, mode: mode });
          } else if (action === 'join') {
            // Pass button element for loading state
            joinMeetingNow(button.dataset.url, button.dataset.title, button);
          } else if (action === 'leave') {
            leaveMeeting(button.dataset.session);
          } else if (action === 'toggle-audio') {
            toggleMeetingAudio(button);
          }
          return;
        }
        
        // Handle specific button IDs
        if (target.id === 'btn-leave-all' || target.closest('#btn-leave-all')) {
          leaveAllMeetings();
          return;
        }
        if (target.id === 'btn-copy-transcript' || target.closest('#btn-copy-transcript')) {
          copyTranscript();
          return;
        }
        if (target.id === 'btn-clear-captions' || target.closest('#btn-clear-captions')) {
          clearCaptions();
          return;
        }
        if (target.id === 'quickJoinBtn' || target.closest('#quickJoinBtn')) {
          quickJoin();
          return;
        }
        if (target.id === 'btn-start-preview' || target.closest('#btn-start-preview')) {
          startVideoPreview();
          return;
        }
        if (target.id === 'btn-stop-preview' || target.closest('#btn-stop-preview')) {
          stopVideoPreview();
          return;
        }
        if (target.id === 'btn-flip-preview' || target.closest('#btn-flip-preview')) {
          toggleVideoFlip();
          return;
        }
      });
      
      // Start observing captions feed for auto-scroll
      const feed = document.getElementById('transcriptionFeed');
      if (feed) {
        captionsObserver.observe(feed, { childList: true, subtree: true });
        scrollTranscription();
      }
      
      console.log('[MeetingsTab] Container-level event delegation initialized');

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

    // Handle Enter key in inputs (scoped to meetings container)
    // Only attach once using the needsInit flag
    if (needsInit) meetingsContainer.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        if (e.target.id === 'manualResponse') {
          sendManualResponse();
        } else if (e.target.id === 'quickJoinUrl') {
          quickJoin();
        }
      }
    });

    // Handle messages from extension (for meeting approval/join responses)
    // Only attach once using the needsInit flag
    if (needsInit) window.addEventListener('message', function(event) {
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
              noMeeting.innerHTML = '<div class="no-meeting-icon text-error">❌</div>' +
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
          calendarsContainer.innerHTML = '<div class="placeholder-text">No calendars configured</div>';
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

    // Video preview buttons are now handled by container-level click delegation above
    
    })(); // End of IIFE for meetings container delegation
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
