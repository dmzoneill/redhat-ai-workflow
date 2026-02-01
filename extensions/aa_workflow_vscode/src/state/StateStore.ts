/**
 * StateStore - Centralized State Management
 *
 * A reactive state store that:
 * - Holds all cached state in one place
 * - Emits change events when state updates
 * - Handles cache invalidation automatically
 * - Provides typed accessors
 *
 * This replaces the 25+ private cache variables scattered throughout commandCenter.ts
 */

import { EventEmitter } from "events";
import type {
  ChatSession,
  WorkspaceState,
  WorkspaceExportedState,
  SkillExecution,
  RunningSkillSummary,
  SkillDefinition,
  CronJob,
  CronExecution,
  AgentStats,
  MeetBotState,
  SprintState,
  PerformanceState,
} from "../data/types";

// ============================================================================
// State Types
// ============================================================================

export interface WorkspacesState {
  workspaces: WorkspaceExportedState;
  count: number;
  groupBy: 'none' | 'project' | 'persona';
  viewMode: 'card' | 'table';
}

export interface ServicesState {
  list: ServiceStatus[];
  mcp: { running: boolean; port?: number };
}

export interface ServiceStatus {
  name: string;
  icon: string;
  running: boolean;
  status?: string;
  error?: string;
  uptime?: string;
  stats?: Record<string, any>;
}

export interface MeetingsState {
  botState: MeetBotState | null;
  data: any;
}

export interface SprintStateContainer {
  issues: any[];
  issuesUpdated: string;
  state: SprintState | null;
}

export interface CronState {
  data: any;
  config: CronConfig | null;
  history: CronExecution[];
  historyTotal: number;
}

export interface CronConfig {
  enabled: boolean;
  timezone: string;
  jobs: CronJob[];
  execution_mode: string;
}

export interface SlackState {
  channels: string[];
  pending: any[];
  config: any;
  cacheStats: any;
  history: any[];
}

export interface MemoryState {
  health: MemoryHealth | null;
  files: MemoryFiles | null;
  currentWork: CurrentWork | null;
}

export interface MemoryHealth {
  totalSize: string;
  sessionLogs: number;
  lastSession: string;
  patterns: number;
}

export interface MemoryFiles {
  state: string[];
  learned: string[];
  sessions: string[];
  knowledge: { project: string; persona: string; confidence: number }[];
}

export interface CurrentWork {
  active_issues: any[];
  recent_branches: any[];
  environments: any[];
}

export interface SkillsState {
  definitions: SkillDefinition[];
  running: RunningSkillSummary[];
  current: SkillExecution | null;
}

export interface PersonasState {
  list: Persona[];
  viewMode: 'card' | 'table';
}

export interface Persona {
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

export interface ToolsState {
  modules: ToolModule[];
}

export interface ToolModule {
  name: string;
  displayName: string;
  description: string;
  toolCount: number;
  tools: ToolDefinition[];
}

export interface ToolDefinition {
  name: string;
  description: string;
  module: string;
}

export interface OllamaState {
  status: Record<string, any>;
}

export interface InferenceState {
  stats: any;
}

export interface VideoPreviewState {
  active: boolean;
  device: string;
  mode: string;
}

// Complete application state
export interface AppState {
  workspaces: WorkspacesState;
  services: ServicesState;
  meetings: MeetingsState;
  sprint: SprintStateContainer;
  cron: CronState;
  slack: SlackState;
  memory: MemoryState;
  skills: SkillsState;
  personas: PersonasState;
  tools: ToolsState;
  ollama: OllamaState;
  inference: InferenceState;
  stats: AgentStats | null;
  videoPreview: VideoPreviewState;
  currentTab: string;
}

// ============================================================================
// Default State Factory
// ============================================================================

function getDefaultAppState(): AppState {
  return {
    workspaces: {
      workspaces: {},
      count: 0,
      groupBy: 'project',
      viewMode: 'card',
    },
    services: {
      list: [],
      mcp: { running: false },
    },
    meetings: {
      botState: null,
      data: {},
    },
    sprint: {
      issues: [],
      issuesUpdated: "",
      state: null,
    },
    cron: {
      data: {},
      config: null,
      history: [],
      historyTotal: 0,
    },
    slack: {
      channels: [],
      pending: [],
      config: null,
      cacheStats: null,
      history: [],
    },
    memory: {
      health: null,
      files: null,
      currentWork: null,
    },
    skills: {
      definitions: [],
      running: [],
      current: null,
    },
    personas: {
      list: [],
      viewMode: 'card',
    },
    tools: {
      modules: [],
    },
    ollama: {
      status: {},
    },
    inference: {
      stats: null,
    },
    stats: null,
    videoPreview: {
      active: false,
      device: "/dev/video10",
      mode: "webrtc",
    },
    currentTab: "overview",
  };
}

// ============================================================================
// StateStore Class
// ============================================================================

export type StateSection = keyof AppState;

export class StateStore extends EventEmitter {
  private state: AppState;

  constructor() {
    super();
    this.state = getDefaultAppState();
  }

  // ============================================================================
  // Generic Accessors
  // ============================================================================

  /**
   * Get the entire state (read-only snapshot)
   */
  getState(): Readonly<AppState> {
    return this.state;
  }

  /**
   * Get a specific section of state
   */
  get<K extends StateSection>(section: K): AppState[K] {
    return this.state[section];
  }

  /**
   * Set a specific section of state
   */
  set<K extends StateSection>(section: K, data: AppState[K]): void {
    const oldValue = this.state[section];
    this.state[section] = data;
    this.emit(`${section}:changed`, data, oldValue);
    this.emit('state:changed', section, data);
  }

  /**
   * Update a specific section of state (partial update)
   */
  update<K extends StateSection>(section: K, updates: Partial<AppState[K]>): void {
    const oldValue = this.state[section];
    const currentValue = this.state[section];
    // Handle object spread safely
    if (currentValue !== null && typeof currentValue === 'object' && !Array.isArray(currentValue)) {
      this.state[section] = { ...currentValue, ...updates } as AppState[K];
    } else {
      this.state[section] = updates as AppState[K];
    }
    this.emit(`${section}:changed`, this.state[section], oldValue);
    this.emit('state:changed', section, this.state[section]);
  }

  /**
   * Batch update multiple sections at once
   */
  batchUpdate(updates: Partial<AppState>): void {
    const changedSections: StateSection[] = [];

    for (const [section, data] of Object.entries(updates)) {
      if (data !== undefined) {
        (this.state as any)[section] = data;
        changedSections.push(section as StateSection);
      }
    }

    // Emit individual section changes
    for (const section of changedSections) {
      this.emit(`${section}:changed`, this.state[section]);
    }

    // Emit batch change event
    this.emit('state:batch-changed', changedSections);
  }

  // ============================================================================
  // Typed Accessors (for convenience)
  // ============================================================================

  // Workspaces
  get workspaces(): WorkspacesState { return this.state.workspaces; }
  setWorkspaces(data: Partial<WorkspacesState>): void { this.update('workspaces', data); }

  // Services
  get services(): ServicesState { return this.state.services; }
  setServices(data: Partial<ServicesState>): void { this.update('services', data); }

  // Meetings
  get meetings(): MeetingsState { return this.state.meetings; }
  setMeetings(data: Partial<MeetingsState>): void { this.update('meetings', data); }

  // Sprint
  get sprint(): SprintStateContainer { return this.state.sprint; }
  setSprint(data: Partial<SprintStateContainer>): void { this.update('sprint', data); }

  // Cron
  get cron(): CronState { return this.state.cron; }
  setCron(data: Partial<CronState>): void { this.update('cron', data); }

  // Slack
  get slack(): SlackState { return this.state.slack; }
  setSlack(data: Partial<SlackState>): void { this.update('slack', data); }

  // Memory
  get memory(): MemoryState { return this.state.memory; }
  setMemory(data: Partial<MemoryState>): void { this.update('memory', data); }

  // Skills
  get skills(): SkillsState { return this.state.skills; }
  setSkills(data: Partial<SkillsState>): void { this.update('skills', data); }

  // Personas
  get personas(): PersonasState { return this.state.personas; }
  setPersonas(data: Partial<PersonasState>): void { this.update('personas', data); }

  // Tools
  get tools(): ToolsState { return this.state.tools; }
  setTools(data: Partial<ToolsState>): void { this.update('tools', data); }

  // Ollama
  get ollama(): OllamaState { return this.state.ollama; }
  setOllama(data: Partial<OllamaState>): void { this.update('ollama', data); }

  // Inference
  get inference(): InferenceState { return this.state.inference; }
  setInference(data: Partial<InferenceState>): void { this.update('inference', data); }

  // Stats
  get stats(): AgentStats | null { return this.state.stats; }
  setStats(data: AgentStats | null): void { this.set('stats', data); }

  // Video Preview
  get videoPreview(): VideoPreviewState { return this.state.videoPreview; }
  setVideoPreview(data: Partial<VideoPreviewState>): void { this.update('videoPreview', data); }

  // Current Tab
  get currentTab(): string { return this.state.currentTab; }
  setCurrentTab(tab: string): void { this.set('currentTab', tab); }

  // ============================================================================
  // Cache Management
  // ============================================================================

  /**
   * Invalidate a specific section (reset to default)
   */
  invalidate(section: StateSection): void {
    const defaultState = getDefaultAppState();
    (this.state as any)[section] = defaultState[section];
    this.emit(`${section}:invalidated`);
    this.emit('state:invalidated', section);
  }

  /**
   * Invalidate all state (reset to defaults)
   */
  invalidateAll(): void {
    this.state = getDefaultAppState();
    this.emit('state:reset');
  }

  /**
   * Check if a section has been loaded (not default/null)
   */
  isLoaded(section: StateSection): boolean {
    const value = this.state[section];
    if (value === null) return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === 'object') {
      // Check if it's more than just default values
      const defaultState = getDefaultAppState();
      return JSON.stringify(value) !== JSON.stringify(defaultState[section]);
    }
    return true;
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let stateStoreInstance: StateStore | null = null;

export function getStateStore(): StateStore {
  if (!stateStoreInstance) {
    stateStoreInstance = new StateStore();
  }
  return stateStoreInstance;
}

export function resetStateStore(): void {
  if (stateStoreInstance) {
    stateStoreInstance.invalidateAll();
    stateStoreInstance.removeAllListeners();
  }
  stateStoreInstance = null;
}
