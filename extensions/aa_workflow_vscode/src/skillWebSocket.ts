/**
 * WebSocket client for real-time skill execution updates.
 *
 * Connects to the MCP server's WebSocket endpoint (localhost:9876) to receive
 * instant updates about skill execution, step progress, and confirmation requests.
 */

import * as vscode from 'vscode';
import WebSocket from 'ws';
import { createLogger } from './logger';

const logger = createLogger("SkillWS");

// ==================== Types ====================

export interface SkillState {
  skillId: string;
  skillName: string;
  totalSteps: number;
  currentStep: number;
  currentStepName: string;
  currentStepDescription: string;
  status: 'running' | 'completed' | 'failed';
  steps: StepState[];
  startedAt: Date;
}

export interface StepState {
  index: number;
  name: string;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  durationMs?: number;
  error?: string;
}

export interface PendingConfirmation {
  id: string;
  skillId: string;
  stepIndex: number;
  prompt: string;
  options: string[];
  claudeSuggestion?: string;
  timeoutSeconds: number;
  createdAt: Date;
  remainingSeconds: number;
}

export interface AutoHealEvent {
  skillId: string;
  stepIndex: number;
  errorType: string;
  fixAction: string;
  errorSnippet: string;
  success?: boolean;
}

// ==================== WebSocket Client ====================

export class SkillWebSocketClient {
  private ws: WebSocket | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private heartbeatTimer: NodeJS.Timeout | null = null;
  private confirmationTimers: Map<string, NodeJS.Timeout> = new Map();
  private isDisposed = false;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectBackoff = 5000; // Start with 5s, increase on failures

  private skills: Map<string, SkillState> = new Map();
  private confirmations: Map<string, PendingConfirmation> = new Map();

  // Event emitters for UI updates
  private _onSkillStarted = new vscode.EventEmitter<SkillState>();
  private _onSkillUpdate = new vscode.EventEmitter<SkillState>();
  private _onSkillCompleted = new vscode.EventEmitter<{ skillId: string; success: boolean }>();
  private _onStepUpdate = new vscode.EventEmitter<{ skillId: string; step: StepState }>();
  private _onConfirmationRequired = new vscode.EventEmitter<PendingConfirmation>();
  private _onConfirmationResolved = new vscode.EventEmitter<string>();
  private _onAutoHeal = new vscode.EventEmitter<AutoHealEvent>();
  private _onConnectionChange = new vscode.EventEmitter<boolean>();

  public readonly onSkillStarted = this._onSkillStarted.event;
  public readonly onSkillUpdate = this._onSkillUpdate.event;
  public readonly onSkillCompleted = this._onSkillCompleted.event;
  public readonly onStepUpdate = this._onStepUpdate.event;
  public readonly onConfirmationRequired = this._onConfirmationRequired.event;
  public readonly onConfirmationResolved = this._onConfirmationResolved.event;
  public readonly onAutoHeal = this._onAutoHeal.event;
  public readonly onConnectionChange = this._onConnectionChange.event;

  private _isConnected = false;

  constructor(private readonly port: number = 9876) {}

  get isConnected(): boolean {
    return this._isConnected;
  }

  connect(): void {
    if (this.isDisposed) {
      return;
    }

    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      this.ws = new WebSocket(`ws://localhost:${this.port}`);

      this.ws.on('open', () => {
        if (this.isDisposed) {
          this.ws?.close();
          return;
        }
        logger.log('Connected to MCP server');
        this._isConnected = true;
        this.reconnectAttempts = 0; // Reset on successful connection
        this.reconnectBackoff = 5000;
        this._onConnectionChange.fire(true);
        this.startHeartbeat();
      });

      this.ws.on('message', (data: WebSocket.Data) => {
        if (this.isDisposed) return;
        try {
          const message = JSON.parse(data.toString());
          this.handleMessage(message);
        } catch (e) {
          logger.error('Failed to parse message', e);
        }
      });

      this.ws.on('close', () => {
        logger.log('Disconnected');
        this._isConnected = false;
        this._onConnectionChange.fire(false);
        this.stopHeartbeat();
        if (!this.isDisposed) {
          this.scheduleReconnect();
        }
      });

      this.ws.on('error', (error: Error) => {
        // Don't log connection refused errors (server not running)
        if (!error.message.includes('ECONNREFUSED')) {
          logger.error(`Error: ${error.message}`);
        }
        // Don't throw - let the close handler deal with reconnection
      });
    } catch (e) {
      logger.error('Failed to connect', e);
      if (!this.isDisposed) {
        this.scheduleReconnect();
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.isDisposed) {
      return;
    }

    // Exponential backoff with max attempts
    this.reconnectAttempts++;
    if (this.reconnectAttempts > this.maxReconnectAttempts) {
      logger.log('Max reconnect attempts reached, stopping reconnection');
      return;
    }

    // Increase backoff (max 60 seconds)
    const delay = Math.min(this.reconnectBackoff * Math.pow(1.5, this.reconnectAttempts - 1), 60000);
    logger.log(`Scheduling reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.isDisposed) {
        this.connect();
      }
    }, delay);
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'heartbeat' });
    }, 30000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private handleMessage(data: Record<string, unknown>): void {
    const type = data.type as string;

    switch (type) {
      case 'connected':
        this.handleConnected(data);
        break;
      case 'skill_started':
        this.handleSkillStarted(data);
        break;
      case 'step_started':
        this.handleStepStarted(data);
        break;
      case 'step_completed':
        this.handleStepCompleted(data);
        break;
      case 'step_failed':
        this.handleStepFailed(data);
        break;
      case 'skill_completed':
      case 'skill_failed':
        this.handleSkillEnded(data);
        break;
      case 'auto_heal_triggered':
        this.handleAutoHealTriggered(data);
        break;
      case 'auto_heal_completed':
        this.handleAutoHealCompleted(data);
        break;
      case 'confirmation_required':
        this.handleConfirmationRequired(data);
        break;
      case 'confirmation_answered':
      case 'confirmation_expired':
        this.handleConfirmationResolved(data);
        break;
      case 'heartbeat_ack':
        // Heartbeat acknowledged, connection is alive
        break;
    }
  }

  private handleConnected(data: Record<string, unknown>): void {
    // Restore state from server
    const runningSkills = data.running_skills as Array<Record<string, unknown>> || [];
    const pendingConfirmations = data.pending_confirmations as Array<Record<string, unknown>> || [];

    for (const skillData of runningSkills) {
      const skill = this.createSkillState(skillData);
      this.skills.set(skill.skillId, skill);
      this._onSkillStarted.fire(skill);
    }

    for (const confData of pendingConfirmations) {
      const conf = this.createConfirmation(confData);
      this.confirmations.set(conf.id, conf);
      this.startConfirmationTimer(conf);
      this._onConfirmationRequired.fire(conf);
    }
  }

  private handleSkillStarted(data: Record<string, unknown>): void {
    const skill = this.createSkillState(data);
    this.skills.set(skill.skillId, skill);
    this._onSkillStarted.fire(skill);
  }

  private createSkillState(data: Record<string, unknown>): SkillState {
    const totalSteps = (data.total_steps as number) || 0;

    return {
      skillId: data.skill_id as string,
      skillName: data.skill_name as string,
      totalSteps,
      currentStep: (data.current_step as number) || 0,
      currentStepName: '',
      currentStepDescription: '',
      status: (data.status as 'running' | 'completed' | 'failed') || 'running',
      steps: Array(totalSteps)
        .fill(null)
        .map((_, i) => ({
          index: i,
          name: '',
          description: '',
          status: 'pending' as const,
        })),
      startedAt: new Date(),
    };
  }

  private handleStepStarted(data: Record<string, unknown>): void {
    const skillId = data.skill_id as string;
    const skill = this.skills.get(skillId);
    if (!skill) {
      return;
    }

    const stepIndex = data.step_index as number;
    const stepName = data.step_name as string;
    const description = (data.description as string) || '';

    skill.currentStep = stepIndex;
    skill.currentStepName = stepName;
    skill.currentStepDescription = description;

    if (skill.steps[stepIndex]) {
      skill.steps[stepIndex] = {
        index: stepIndex,
        name: stepName,
        description,
        status: 'running',
      };
    }

    this._onSkillUpdate.fire(skill);
    this._onStepUpdate.fire({ skillId, step: skill.steps[stepIndex] });
  }

  private handleStepCompleted(data: Record<string, unknown>): void {
    const skillId = data.skill_id as string;
    const skill = this.skills.get(skillId);
    if (!skill) {
      return;
    }

    const stepIndex = data.step_index as number;
    const durationMs = data.duration_ms as number;

    if (skill.steps[stepIndex]) {
      skill.steps[stepIndex].status = 'completed';
      skill.steps[stepIndex].durationMs = durationMs;
    }

    this._onSkillUpdate.fire(skill);
    this._onStepUpdate.fire({ skillId, step: skill.steps[stepIndex] });
  }

  private handleStepFailed(data: Record<string, unknown>): void {
    const skillId = data.skill_id as string;
    const skill = this.skills.get(skillId);
    if (!skill) {
      return;
    }

    const stepIndex = data.step_index as number;
    const error = data.error as string;

    if (skill.steps[stepIndex]) {
      skill.steps[stepIndex].status = 'failed';
      skill.steps[stepIndex].error = error;
    }

    this._onSkillUpdate.fire(skill);
    this._onStepUpdate.fire({ skillId, step: skill.steps[stepIndex] });
  }

  private handleSkillEnded(data: Record<string, unknown>): void {
    const skillId = data.skill_id as string;
    const skill = this.skills.get(skillId);
    if (!skill) {
      return;
    }

    const success = data.type === 'skill_completed';
    skill.status = success ? 'completed' : 'failed';

    this._onSkillUpdate.fire(skill);
    this._onSkillCompleted.fire({ skillId, success });

    // Remove skill after a delay (let UI show completion state)
    setTimeout(() => {
      this.skills.delete(skillId);
    }, 10000);
  }

  private handleAutoHealTriggered(data: Record<string, unknown>): void {
    const event: AutoHealEvent = {
      skillId: data.skill_id as string,
      stepIndex: data.step_index as number,
      errorType: data.error_type as string,
      fixAction: data.fix_action as string,
      errorSnippet: data.error_snippet as string,
    };

    this._onAutoHeal.fire(event);
  }

  private handleAutoHealCompleted(data: Record<string, unknown>): void {
    const event: AutoHealEvent = {
      skillId: data.skill_id as string,
      stepIndex: data.step_index as number,
      errorType: '',
      fixAction: data.fix_action as string,
      errorSnippet: '',
      success: data.success as boolean,
    };

    this._onAutoHeal.fire(event);
  }

  private handleConfirmationRequired(data: Record<string, unknown>): void {
    const confirmation = this.createConfirmation(data);
    this.confirmations.set(confirmation.id, confirmation);
    this.startConfirmationTimer(confirmation);
    this._onConfirmationRequired.fire(confirmation);
  }

  private createConfirmation(data: Record<string, unknown>): PendingConfirmation {
    const timeoutSeconds = (data.timeout_seconds as number) || 30;

    return {
      id: data.id as string,
      skillId: data.skill_id as string,
      stepIndex: data.step_index as number,
      prompt: data.prompt as string,
      options: (data.options as string[]) || ['let_claude', 'retry_with_fix', 'abort'],
      claudeSuggestion: data.claude_suggestion as string | undefined,
      timeoutSeconds,
      createdAt: new Date(data.created_at as string),
      remainingSeconds: timeoutSeconds,
    };
  }

  private startConfirmationTimer(confirmation: PendingConfirmation): void {
    // Update remaining seconds every second
    const timer = setInterval(() => {
      const conf = this.confirmations.get(confirmation.id);
      if (conf) {
        conf.remainingSeconds--;
        this._onConfirmationRequired.fire(conf);

        if (conf.remainingSeconds <= 0) {
          clearInterval(timer);
          this.confirmationTimers.delete(confirmation.id);
        }
      } else {
        clearInterval(timer);
        this.confirmationTimers.delete(confirmation.id);
      }
    }, 1000);

    this.confirmationTimers.set(confirmation.id, timer);
  }

  private handleConfirmationResolved(data: Record<string, unknown>): void {
    const id = data.id as string;

    // Stop the countdown timer
    const timer = this.confirmationTimers.get(id);
    if (timer) {
      clearInterval(timer);
      this.confirmationTimers.delete(id);
    }

    this.confirmations.delete(id);
    this._onConfirmationResolved.fire(id);
  }

  // ==================== Public Methods ====================

  /**
   * Respond to a confirmation request.
   */
  respondToConfirmation(
    id: string,
    response: 'let_claude' | 'retry_with_fix' | 'abort' | string,
    remember: 'none' | 'this-error' | 'this-skill' | 'always' = 'none'
  ): void {
    // Stop the countdown timer
    const timer = this.confirmationTimers.get(id);
    if (timer) {
      clearInterval(timer);
      this.confirmationTimers.delete(id);
    }

    this.send({
      type: 'confirmation_response',
      id,
      response,
      remember,
    });

    // Remove from local state
    this.confirmations.delete(id);
    this._onConfirmationResolved.fire(id);
  }

  /**
   * Pause the confirmation timer (user is interacting with dialog).
   */
  pauseConfirmationTimer(id: string): void {
    this.send({ type: 'pause_timer', id });
  }

  /**
   * Resume the confirmation timer.
   */
  resumeConfirmationTimer(id: string): void {
    this.send({ type: 'resume_timer', id });
  }

  /**
   * Get all currently running skills.
   */
  getRunningSkills(): SkillState[] {
    return Array.from(this.skills.values()).filter((s) => s.status === 'running');
  }

  /**
   * Get all pending confirmations.
   */
  getPendingConfirmations(): PendingConfirmation[] {
    return Array.from(this.confirmations.values());
  }

  /**
   * Get a specific skill by ID.
   */
  getSkill(skillId: string): SkillState | undefined {
    return this.skills.get(skillId);
  }

  /**
   * Disconnect and clean up.
   */
  dispose(): void {
    this.isDisposed = true;

    try {
      this.ws?.close();
    } catch (e) {
      // Ignore close errors during disposal
    }
    this.ws = null;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }

    this.confirmationTimers.forEach((timer) => clearInterval(timer));
    this.confirmationTimers.clear();

    this.skills.clear();
    this.confirmations.clear();

    try {
      this._onSkillStarted.dispose();
      this._onSkillUpdate.dispose();
      this._onSkillCompleted.dispose();
      this._onStepUpdate.dispose();
      this._onConfirmationRequired.dispose();
      this._onConfirmationResolved.dispose();
      this._onAutoHeal.dispose();
      this._onConnectionChange.dispose();
    } catch (e) {
      // Ignore dispose errors
    }
  }
}

// ==================== Singleton Instance ====================

let _instance: SkillWebSocketClient | null = null;

export function getSkillWebSocketClient(): SkillWebSocketClient {
  if (!_instance) {
    _instance = new SkillWebSocketClient();
  }
  return _instance;
}

export function disposeSkillWebSocketClient(): void {
  if (_instance) {
    _instance.dispose();
    _instance = null;
  }
}
