/**
 * Shared Type Definitions
 *
 * Common interfaces used across the extension.
 * Extracted from legacy tab files for reuse.
 */

// ============================================================================
// Meetings Types
// ============================================================================

export interface Meeting {
  id: string;
  title: string;
  startTime: string;
  endTime: string;
  attendees: string[];
  meetLink?: string;
  calendarId?: string;
  description?: string;
  organizer?: string;
  isRecurring?: boolean;
  recurringEventId?: string;
}

export interface Caption {
  timestamp: string;
  speaker: string;
  text: string;
  confidence?: number;
}

export interface ActiveMeeting extends Meeting {
  joinedAt: string;
  captions: Caption[];
  isRecording: boolean;
  audioLevel?: number;
  participantCount?: number;
}

export interface TechnicalIntegration {
  sttEngine: string;
  sttStatus: "running" | "stopped" | "error";
  audioCapture: "active" | "inactive" | "error";
  browserStatus: "connected" | "disconnected" | "error";
  gpuAcceleration: boolean;
  modelLoaded: boolean;
  lastError?: string;
}

export interface VirtualDevicesStatus {
  camera: "active" | "inactive" | "error";
  microphone: "active" | "inactive" | "error";
  speaker: "active" | "inactive" | "error";
  cameraDevice?: string;
  microphoneDevice?: string;
}

export interface MonitoredCalendar {
  id: string;
  name: string;
  email: string;
  enabled: boolean;
  color?: string;
}

export interface MeetingNote {
  meetingId: string;
  title: string;
  date: string;
  duration: string;
  attendees: string[];
  summary?: string;
  actionItems?: string[];
  transcriptPath?: string;
}

export interface MeetBotState {
  enabled: boolean;
  status: "idle" | "joining" | "in_meeting" | "leaving" | "error";
  currentMeeting: ActiveMeeting | null;
  currentMeetings: ActiveMeeting[];
  upcomingMeetings: Meeting[];
  recentNotes: MeetingNote[];
  monitoredCalendars: MonitoredCalendar[];
  technicalStatus: TechnicalIntegration;
  virtualDevices: VirtualDevicesStatus;
  autoJoinEnabled: boolean;
  autoTranscribeEnabled: boolean;
  lastError?: string;
  schedulerRunning: boolean;
  nextScheduledCheck?: string;
}

// ============================================================================
// Sprint Types (Complete definitions from sprint renderer)
// ============================================================================

export interface SprintIssue {
  key: string;
  summary: string;
  storyPoints: number;
  priority: string;
  jiraStatus: string;
  assignee: string;
  approvalStatus:
    | "pending"
    | "approved"
    | "rejected"
    | "in_progress"
    | "completed"
    | "blocked"
    | "waiting";
  waitingReason?: string;
  priorityReasoning: string[];
  estimatedActions: string[];
  chatId?: string;
  timeline: TimelineEvent[];
  issueType?: string;
  created?: string;
  hasWorkLog?: boolean;
  workLogPath?: string;
  hasTrace?: boolean;
  tracePath?: string;
}

export interface ExecutionStep {
  step_id: string;
  name: string;
  timestamp: string;
  duration_ms?: number;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  inputs?: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  decision?: string;
  reason?: string;
  error?: string;
  skill_name?: string;
  tool_name?: string;
  chat_id?: string;
}

export interface StateTransition {
  from_state: string;
  to_state: string;
  timestamp: string;
  trigger?: string;
  data?: Record<string, unknown>;
}

export interface ExecutionTrace {
  issue_key: string;
  workflow_type: string;
  execution_mode: string;
  started_at: string;
  completed_at?: string;
  current_state: string;
  state_description: string;
  steps: ExecutionStep[];
  transitions: StateTransition[];
  summary: {
    total_steps: number;
    successful_steps: number;
    failed_steps: number;
    total_duration_ms: number;
    total_transitions: number;
    final_state: string;
  };
}

export interface TimelineEvent {
  timestamp: string;
  action: string;
  description: string;
  chatLink?: string;
  jiraLink?: string;
}

export interface CompletedSprint {
  id: string;
  name: string;
  startDate: string;
  endDate: string;
  totalPoints: number;
  completedPoints: number;
  issues: SprintIssue[];
  timeline: TimelineEvent[];
  collapsed: boolean;
}

export interface SprintInfo {
  id: string;
  name: string;
  startDate: string;
  endDate: string;
  totalPoints: number;
  completedPoints: number;
}

export interface SprintState {
  currentSprint: SprintInfo | null;
  nextSprint: SprintInfo | null;
  issues: SprintIssue[];
  automaticMode: boolean;
  manuallyStarted: boolean;
  backgroundTasks: boolean;
  lastUpdated: string;
  processingIssue: string | null;
}

export interface ToolGapRequest {
  id: string;
  timestamp: string;
  suggested_tool_name: string;
  desired_action: string;
  context: string;
  suggested_args: Record<string, unknown>;
  workaround_used: string | null;
  requesting_skills: string[];
  issue_key: string | null;
  vote_count: number;
  status: "open" | "in_progress" | "implemented" | "rejected";
}

// Sprint renderer's detailed status mapping
export interface StatusMappingConfig {
  displayName: string;
  icon: string;
  color: string;
  description: string;
  jiraStatuses: string[];
  botCanWork: boolean;
  uiOrder: number;
  showApproveButtons?: boolean;
  botMonitors?: boolean;
}

// Sprint renderer's workflow config (used by sprintRenderer.ts)
export interface WorkflowConfig {
  statusMappings: Record<string, StatusMappingConfig>;
  mergeHoldPatterns: string[];
  spikeKeywords: string[];
  version: string;
}

// Simple workflow config (used by data/loaders.ts)
export interface SimpleWorkflowConfig {
  statusMapping: {
    todo: string[];
    inProgress: string[];
    done: string[];
    blocked: string[];
  };
  autoTransitions: boolean;
  notifyOnComplete: boolean;
  createBranch: boolean;
  createMR: boolean;
}

// ============================================================================
// Performance Types
// ============================================================================

export interface CompetencyScore {
  category: string;
  subcategory: string;
  score: number;
  maxScore: number;
  questions: number;
  correct: number;
  lastUpdated?: string;
}

export interface QuestionSummary {
  id: string;
  category: string;
  subcategory: string;
  question: string;
  correct: boolean;
  answeredAt: string;
  timeSpent?: number;
}

export interface PerformanceState {
  overallScore: number;
  totalQuestions: number;
  correctAnswers: number;
  competencies: CompetencyScore[];
  recentQuestions: QuestionSummary[];
  streakDays: number;
  lastPractice?: string;
  weeklyGoal: number;
  weeklyProgress: number;
}

export interface SunburstData {
  name: string;
  value?: number;
  children?: SunburstData[];
}

export interface SunburstCategory {
  name: string;
  children: SunburstChild[];
}

export interface SunburstChild {
  name: string;
  value: number;
  score?: number;
}

// ============================================================================
// Create Session Types
// ============================================================================

export interface RalphLoopConfig {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  interval: number;
  lastRun?: string;
  nextRun?: string;
  status: "idle" | "running" | "error";
}

export interface ContextSource {
  type: "file" | "url" | "clipboard" | "selection" | "terminal";
  path?: string;
  content?: string;
  label?: string;
}

export interface ExternalSession {
  id: string;
  name: string;
  type: "cursor" | "vscode" | "terminal" | "browser";
  pid?: number;
  startedAt: string;
  lastActivity?: string;
  workspace?: string;
}

export interface CreateSessionState {
  activeLoops: RalphLoopConfig[];
  contextSources: ContextSource[];
  externalSessions: ExternalSession[];
  selectedPersona?: string;
  selectedSkill?: string;
  promptTemplate?: string;
}

// ============================================================================
// Cron Types
// ============================================================================

export interface CronJob {
  id: string;
  name: string;
  schedule: string;
  command: string;
  enabled: boolean;
  lastRun?: string;
  nextRun?: string;
  lastStatus?: "success" | "failure" | "running";
  lastError?: string;
  description?: string;
}

export interface CronExecution {
  id: string;
  jobId: string;
  jobName: string;
  startedAt: string;
  completedAt?: string;
  status: "running" | "success" | "failure";
  output?: string;
  error?: string;
  duration?: number;
}

export interface CronConfig {
  enabled: boolean;
  timezone: string;
  jobs: CronJob[];
  execution_mode: string;
}

// ============================================================================
// Tool Module Types
// ============================================================================

export interface ToolModule {
  name: string;
  description: string;
  tools: string[];
  enabled: boolean;
  category?: string;
}

// ============================================================================
// Persona Types
// ============================================================================

export interface Persona {
  id: string;
  name: string;
  description: string;
  tools: string[];
  skills?: string[];
  systemPrompt?: string;
}

// ============================================================================
// Skill Types
// ============================================================================

export interface SkillDefinition {
  name: string;
  description: string;
  category?: string;
  inputs?: { name: string; type: string; required: boolean; description?: string }[];
  steps?: string[];
}

// ============================================================================
// Agent Stats Types
// ============================================================================

export interface DailyStats {
  tool_calls: number;
  skill_executions: number;
  memory_ops?: number;
}

export interface SessionStats {
  tool_calls: number;
  skill_executions: number;
  memory_ops: number;
}

export interface LifetimeStats {
  tool_calls: number;
  tool_successes: number;
  tool_failures?: number;
  skill_executions: number;
  skill_successes?: number;
  sessions?: number;
}

export interface AgentStats {
  daily: Record<string, DailyStats>;
  current_session: SessionStats;
  lifetime: LifetimeStats;
}

// ============================================================================
// Session Types
// ============================================================================

export interface MeetingReference {
  meeting_id: number;
  title: string;
  date: string;
  matches: number;
}

export interface ChatSession {
  session_id: string;
  workspace_uri: string;
  persona: string;
  project: string | null;
  is_project_auto_detected: boolean;
  issue_key: string | null;
  branch: string | null;
  static_tool_count?: number;
  dynamic_tool_count?: number;
  tool_count?: number;
  last_filter_message?: string | null;
  last_filter_time?: string | null;
  active_tools?: string[];
  started_at: string | null;
  last_activity: string | null;
  name: string | null;
  last_tool: string | null;
  last_tool_time: string | null;
  tool_call_count: number;
  meeting_references?: MeetingReference[];
  is_active?: boolean;
}

export interface WorkspaceState {
  workspace_uri: string;
  project: string | null;
  is_auto_detected: boolean;
  active_session_id: string | null;
  sessions: { [sessionId: string]: ChatSession };
  created_at: string | null;
  last_activity: string | null;
}

export interface WorkspaceExportedState {
  [workspaceUri: string]: WorkspaceState;
}

// ============================================================================
// Skill Execution Types
// ============================================================================

export interface SkillStep {
  name: string;
  description?: string;
  tool?: string;
  compute?: string;
  condition?: string;
  status: "pending" | "running" | "success" | "failed" | "skipped";
  duration?: number;
  result?: string;
  error?: string;
}

export interface SkillExecution {
  executionId?: string;
  skillName: string;
  status: "idle" | "running" | "success" | "failed";
  currentStepIndex: number;
  totalSteps: number;
  steps: SkillStep[];
  startTime?: string;
  endTime?: string;
  source?: string;
  sourceDetails?: string;
  sessionName?: string;
}

export interface RunningSkillSummary {
  executionId: string;
  skillName: string;
  source: string;
  sourceDetails?: string;
  sessionName?: string;
  status: "running" | "success" | "failed";
  currentStepIndex: number;
  totalSteps: number;
  startTime: string;
  elapsedMs: number;
}

// ============================================================================
// Tool and Persona Types (Command Center specific)
// ============================================================================

export interface ToolDefinitionCC {
  name: string;
  description: string;
  module: string;
}

export interface ToolModuleCC {
  name: string;
  displayName: string;
  description: string;
  toolCount: number;
  tools: ToolDefinitionCC[];
}

export interface PersonaCC {
  name: string;
  fileName?: string;
  description: string;
  tools: string[];
  toolCount: number;
  skills: string[];
  personaFile?: string;
  isSlim?: boolean;
  isInternal?: boolean;
  isAgent?: boolean;
}
