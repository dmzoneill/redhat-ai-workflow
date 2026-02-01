/**
 * Data Loaders
 *
 * Functions for loading data from files and D-Bus.
 * These are shared across the extension.
 */

import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import {
  MeetBotState,
  SprintState,
  SprintIssue,
  CompletedSprint,
  ToolGapRequest,
  PerformanceState,
  CompetencyScore,
  QuestionSummary,
  ExecutionTrace,
  SimpleWorkflowConfig,
  RalphLoopConfig,
} from "./types";
import { createLogger } from "../logger";

const logger = createLogger("DataLoaders");

// ============================================================================
// Path Helpers
// ============================================================================

function getWorkflowDir(): string {
  return path.join(os.homedir(), "src", "redhat-ai-workflow");
}

function getMemoryDir(): string {
  return path.join(getWorkflowDir(), "memory");
}

function getStateDir(): string {
  return path.join(getMemoryDir(), "state");
}

// ============================================================================
// Sprint Data Loaders
// ============================================================================

/**
 * Load sprint history from file.
 */
export function loadSprintHistory(): CompletedSprint[] {
  try {
    const historyPath = path.join(getStateDir(), "sprint_history.json");
    if (fs.existsSync(historyPath)) {
      const data = JSON.parse(fs.readFileSync(historyPath, "utf-8"));
      return data.completedSprints || [];
    }
  } catch (e) {
    logger.error("Failed to load sprint history", e);
  }
  return [];
}

/**
 * Load tool gap requests from file.
 */
export function loadToolGapRequests(): ToolGapRequest[] {
  try {
    const requestsPath = path.join(getStateDir(), "tool_gap_requests.json");
    if (fs.existsSync(requestsPath)) {
      const data = JSON.parse(fs.readFileSync(requestsPath, "utf-8"));
      return data.requests || [];
    }
  } catch (e) {
    logger.error("Failed to load tool gap requests", e);
  }
  return [];
}

/**
 * Load execution trace for an issue.
 */
export function loadExecutionTrace(issueKey: string): ExecutionTrace | null {
  try {
    const tracePath = path.join(getStateDir(), "traces", `${issueKey}.json`);
    if (fs.existsSync(tracePath)) {
      return JSON.parse(fs.readFileSync(tracePath, "utf-8"));
    }
  } catch (e) {
    logger.error(`Failed to load trace for ${issueKey}`, e);
  }
  return null;
}

/**
 * List all execution traces.
 */
export function listTraces(): { issueKey: string; state: string; startedAt: string }[] {
  try {
    const tracesDir = path.join(getStateDir(), "traces");
    if (!fs.existsSync(tracesDir)) {
      return [];
    }
    const files = fs.readdirSync(tracesDir).filter(f => f.endsWith(".json"));
    return files.map(f => {
      const trace = JSON.parse(fs.readFileSync(path.join(tracesDir, f), "utf-8"));
      return {
        issueKey: trace.issueKey || f.replace(".json", ""),
        state: trace.state || "unknown",
        startedAt: trace.startedAt || "",
      };
    });
  } catch (e) {
    logger.error("Failed to list traces", e);
  }
  return [];
}

/**
 * Load workflow configuration.
 */
export function loadWorkflowConfig(): SimpleWorkflowConfig {
  try {
    const configPath = path.join(getWorkflowDir(), "config.json");
    if (fs.existsSync(configPath)) {
      const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
      return {
        statusMapping: config.statusMapping || {
          todo: ["To Do", "Open", "Backlog"],
          inProgress: ["In Progress", "In Review"],
          done: ["Done", "Closed", "Resolved"],
          blocked: ["Blocked", "On Hold"],
        },
        autoTransitions: config.autoTransitions ?? true,
        notifyOnComplete: config.notifyOnComplete ?? true,
        createBranch: config.createBranch ?? true,
        createMR: config.createMR ?? true,
      };
    }
  } catch (e) {
    logger.error("Failed to load workflow config", e);
  }
  return {
    statusMapping: {
      todo: ["To Do", "Open", "Backlog"],
      inProgress: ["In Progress", "In Review"],
      done: ["Done", "Closed", "Resolved"],
      blocked: ["Blocked", "On Hold"],
    },
    autoTransitions: true,
    notifyOnComplete: true,
    createBranch: true,
    createMR: true,
  };
}

// ============================================================================
// Performance Data Loaders
// ============================================================================

/**
 * Load performance state from file.
 */
export function loadPerformanceState(): PerformanceState {
  try {
    const statePath = path.join(getStateDir(), "performance.json");
    if (fs.existsSync(statePath)) {
      const data = JSON.parse(fs.readFileSync(statePath, "utf-8"));
      return {
        overallScore: data.overallScore || 0,
        totalQuestions: data.totalQuestions || 0,
        correctAnswers: data.correctAnswers || 0,
        competencies: data.competencies || [],
        recentQuestions: data.recentQuestions || [],
        streakDays: data.streakDays || 0,
        lastPractice: data.lastPractice,
        weeklyGoal: data.weeklyGoal || 10,
        weeklyProgress: data.weeklyProgress || 0,
      };
    }
  } catch (e) {
    logger.error("Failed to load performance state", e);
  }
  return getEmptyPerformanceState();
}

/**
 * Get empty performance state.
 */
export function getEmptyPerformanceState(): PerformanceState {
  return {
    overallScore: 0,
    totalQuestions: 0,
    correctAnswers: 0,
    competencies: [],
    recentQuestions: [],
    streakDays: 0,
    weeklyGoal: 10,
    weeklyProgress: 0,
  };
}

// ============================================================================
// Create Session Data Loaders
// ============================================================================

/**
 * Load active Ralph loops.
 */
export function loadActiveLoops(): RalphLoopConfig[] {
  try {
    const loopsPath = path.join(getStateDir(), "ralph_loops.json");
    if (fs.existsSync(loopsPath)) {
      const data = JSON.parse(fs.readFileSync(loopsPath, "utf-8"));
      return data.loops || [];
    }
  } catch (e) {
    logger.error("Failed to load Ralph loops", e);
  }
  return [];
}

// ============================================================================
// Meeting Data Helpers
// ============================================================================

/**
 * Parse virtual devices status from unified state data.
 */
function parseVirtualDevicesStatus(data: any): any {
  if (!data) {
    return undefined;
  }

  const parseStatus = (value: any) => {
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
 * Load meet bot state from D-Bus data.
 */
export function loadMeetBotState(unifiedMeetData?: any): MeetBotState {
  if (unifiedMeetData && Object.keys(unifiedMeetData).length > 0) {
    const virtualDevices = parseVirtualDevicesStatus(unifiedMeetData.virtualDevices);

    return {
      enabled: true,
      status: (unifiedMeetData.currentMeetings?.length || 0) > 0 ? "in_meeting" : "idle",
      currentMeeting: unifiedMeetData.currentMeeting || null,
      currentMeetings: unifiedMeetData.currentMeetings || [],
      upcomingMeetings: (unifiedMeetData.upcomingMeetings || []).map((m: any) => ({
        id: m.id || "",
        title: m.title || "Untitled",
        startTime: m.startTime || "",
        endTime: m.endTime || "",
        attendees: m.attendees || [],
        meetLink: m.url || m.meetLink,
        organizer: m.organizer || "",
        status: m.status || "pending",
      })),
      recentNotes: (unifiedMeetData.recentNotes || []).map((note: any) => ({
        meetingId: note.id?.toString() || "",
        title: note.title || "Untitled",
        date: note.date ? new Date(note.date).toLocaleDateString() : "",
        duration: `${Math.round(note.duration || 0)}m`,
        attendees: [],
        transcriptPath: note.transcriptPath,
      })),
      monitoredCalendars: (unifiedMeetData.monitoredCalendars || []).map((c: any) => ({
        id: c.id || c.calendar_id || "",
        name: c.name || "",
        email: c.calendarId || c.calendar_id || "",
        enabled: c.enabled || false,
      })),
      technicalStatus: {
        sttEngine: "whisper",
        sttStatus: "stopped",
        audioCapture: "inactive",
        browserStatus: "disconnected",
        gpuAcceleration: false,
        modelLoaded: false,
      },
      virtualDevices: virtualDevices || {
        camera: "inactive",
        microphone: "inactive",
        speaker: "inactive",
      },
      autoJoinEnabled: unifiedMeetData.autoJoinEnabled || false,
      autoTranscribeEnabled: unifiedMeetData.autoTranscribeEnabled || false,
      schedulerRunning: unifiedMeetData.schedulerRunning || false,
      nextScheduledCheck: unifiedMeetData.nextScheduledCheck,
    };
  }

  // Return default empty state
  return {
    enabled: false,
    status: "idle",
    currentMeeting: null,
    currentMeetings: [],
    upcomingMeetings: [],
    recentNotes: [],
    monitoredCalendars: [],
    technicalStatus: {
      sttEngine: "whisper",
      sttStatus: "stopped",
      audioCapture: "inactive",
      browserStatus: "disconnected",
      gpuAcceleration: false,
      modelLoaded: false,
    },
    virtualDevices: {
      camera: "inactive",
      microphone: "inactive",
      speaker: "inactive",
    },
    autoJoinEnabled: false,
    autoTranscribeEnabled: false,
    schedulerRunning: false,
  };
}
