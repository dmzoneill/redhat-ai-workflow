/**
 * Message Router for Command Center
 *
 * Routes webview messages to appropriate handlers based on message type.
 * This replaces the massive switch statement in CommandCenterPanel with
 * a more maintainable and extensible pattern.
 */

import * as vscode from "vscode";
import { createLogger } from "../logger";

const logger = createLogger("MessageRouter");

/**
 * Context passed to message handlers.
 */
export interface MessageContext {
  panel: vscode.WebviewPanel;
  extensionUri: vscode.Uri;
  postMessage: (message: any) => void;
}

/**
 * A message from the webview.
 */
export interface WebviewMessage {
  command?: string;
  type?: string;
  [key: string]: any;
}

/**
 * Handler for a specific message type or group of message types.
 */
export interface MessageHandler {
  /**
   * Check if this handler can handle the given message.
   */
  canHandle(message: WebviewMessage): boolean;

  /**
   * Handle the message.
   */
  handle(message: WebviewMessage, context: MessageContext): Promise<void>;
}

/**
 * Base class for message handlers that handle a specific set of commands.
 */
export abstract class BaseMessageHandler implements MessageHandler {
  protected commands: Set<string>;

  constructor(commands: string[]) {
    this.commands = new Set(commands);
  }

  canHandle(message: WebviewMessage): boolean {
    const msgType = message.command || message.type;
    return msgType ? this.commands.has(msgType) : false;
  }

  abstract handle(message: WebviewMessage, context: MessageContext): Promise<void>;
}

/**
 * Message router that dispatches messages to appropriate handlers.
 */
export class MessageRouter {
  private handlers: MessageHandler[] = [];
  private defaultHandler: ((message: WebviewMessage, context: MessageContext) => Promise<void>) | null = null;

  /**
   * Register a message handler.
   */
  register(handler: MessageHandler): this {
    this.handlers.push(handler);
    return this;
  }

  /**
   * Set a default handler for unhandled messages.
   */
  setDefaultHandler(handler: (message: WebviewMessage, context: MessageContext) => Promise<void>): this {
    this.defaultHandler = handler;
    return this;
  }

  /**
   * Route a message to the appropriate handler.
   */
  async route(message: WebviewMessage, context: MessageContext): Promise<boolean> {
    const msgType = message.command || message.type;

    for (const handler of this.handlers) {
      if (handler.canHandle(message)) {
        try {
          await handler.handle(message, context);
          return true;
        } catch (error) {
          logger.error(`Handler error for ${msgType}`, error);
          throw error;
        }
      }
    }

    // No handler found, try default
    if (this.defaultHandler) {
      await this.defaultHandler(message, context);
      return true;
    }

    logger.warn(`No handler found for message type: ${msgType}`);
    return false;
  }
}

// ============================================================================
// Domain-Specific Handlers
// ============================================================================

/**
 * Handler for session-related messages.
 * 
 * NOTE: Many handlers removed - SessionsTab handles them directly:
 * - copySessionId, searchSessions, changeSessionGroupBy, changeSessionViewMode
 * 
 * Remaining handlers are for messages NOT handled by SessionsTab:
 * - refresh/refreshWorkspaces/refreshSessionsNow - global refresh
 * - openChatSession - opens chat in Cursor (VSCode-specific)
 * - viewMeetingNotes - opens meeting notes (VSCode-specific)
 */
export class SessionMessageHandler extends BaseMessageHandler {
  private onRefresh: () => Promise<void>;
  private onOpenChatSession: (sessionId: string, sessionName?: string) => Promise<void>;
  private onViewMeetingNotes: (sessionId: string) => Promise<void>;

  constructor(callbacks: {
    onRefresh: () => Promise<void>;
    onOpenChatSession: (sessionId: string, sessionName?: string) => Promise<void>;
    onViewMeetingNotes: (sessionId: string) => Promise<void>;
  }) {
    super([
      "refresh",
      "refreshWorkspaces",
      "refreshSessionsNow",
      "openChatSession",
      "viewMeetingNotes",
    ]);
    this.onRefresh = callbacks.onRefresh;
    this.onOpenChatSession = callbacks.onOpenChatSession;
    this.onViewMeetingNotes = callbacks.onViewMeetingNotes;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "refresh":
      case "refreshWorkspaces":
      case "refreshSessionsNow":
        await this.onRefresh();
        break;
      case "openChatSession":
        await this.onOpenChatSession(message.sessionId, message.sessionName);
        break;
      case "viewMeetingNotes":
        await this.onViewMeetingNotes(message.sessionId);
        break;
    }
  }
}

// NOTE: SprintMessageHandler removed - SprintTab handles sprintAction directly via D-Bus
// NOTE: MeetingMessageHandler removed - MeetingsTab handles meeting messages directly via D-Bus

/**
 * Handler for Slack-related messages.
 * 
 * NOTE: Some handlers removed - SlackTab handles them directly:
 * - sendSlackMessage, approveSlackMessage, rejectSlackMessage, approveAllSlack
 * 
 * Remaining handlers are for messages NOT handled by SlackTab (different message names).
 */
export class SlackMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onLoadHistory: () => Promise<void>;
    onReplyToThread: (channel: string, text: string, threadTs?: string) => Promise<void>;
    onRefreshChannels: () => Promise<void>;
    onSearchUsers: (query: string) => Promise<void>;
    onRefreshTargets: () => Promise<void>;
    onSearchMessages: (query: string) => Promise<void>;
    onRefreshPending: () => Promise<void>;
    onRefreshCache: () => Promise<void>;
    onRefreshCacheStats: () => Promise<void>;
    onLoadChannelBrowser: (query: string) => Promise<void>;
    onLoadUserBrowser: (query: string) => Promise<void>;
    onLoadCommands: () => Promise<void>;
    onSendCommand: (commandName: string, args: any) => Promise<void>;
    onLoadConfig: () => Promise<void>;
    onSetDebugMode: (enabled: boolean) => Promise<void>;
  };

  constructor(callbacks: SlackMessageHandler["callbacks"]) {
    super([
      "loadSlackHistory",
      // NOTE: sendSlackMessage removed - SlackTab handles it directly
      "replyToSlackThread",
      "refreshSlackChannels",
      "searchSlackUsers",
      "refreshSlackTargets",
      "searchSlackMessages",
      "refreshSlackPending",
      // NOTE: approveSlackMessage, rejectSlackMessage, approveAllSlack removed - SlackTab handles them directly
      "refreshSlackCache",
      "refreshSlackCacheStats",
      "loadSlackChannelBrowser",
      "loadSlackUserBrowser",
      "loadSlackCommands",
      "sendSlackCommand",
      "loadSlackConfig",
      "setSlackDebugMode",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "loadSlackHistory":
        await this.callbacks.onLoadHistory();
        break;
      case "replyToSlackThread":
        await this.callbacks.onReplyToThread(message.channel, message.text, message.threadTs);
        break;
      case "refreshSlackChannels":
        await this.callbacks.onRefreshChannels();
        break;
      case "searchSlackUsers":
        await this.callbacks.onSearchUsers(message.query);
        break;
      case "refreshSlackTargets":
        await this.callbacks.onRefreshTargets();
        break;
      case "searchSlackMessages":
        await this.callbacks.onSearchMessages(message.query);
        break;
      case "refreshSlackPending":
        await this.callbacks.onRefreshPending();
        break;
      case "refreshSlackCache":
        await this.callbacks.onRefreshCache();
        break;
      case "refreshSlackCacheStats":
        await this.callbacks.onRefreshCacheStats();
        break;
      case "loadSlackChannelBrowser":
        await this.callbacks.onLoadChannelBrowser(message.query || "");
        break;
      case "loadSlackUserBrowser":
        await this.callbacks.onLoadUserBrowser(message.query || "");
        break;
      case "loadSlackCommands":
        await this.callbacks.onLoadCommands();
        break;
      case "sendSlackCommand":
        await this.callbacks.onSendCommand(message.commandName, message.args);
        break;
      case "loadSlackConfig":
        await this.callbacks.onLoadConfig();
        break;
      case "setSlackDebugMode":
        await this.callbacks.onSetDebugMode(message.enabled);
        break;
    }
  }
}

// NOTE: SkillMessageHandler removed - SkillsTab handles skill messages directly

/**
 * Handler for D-Bus and service-related messages.
 * 
 * NOTE: Some handlers removed - ServicesTab handles them directly:
 * - refreshServices, serviceControl, testOllamaInstance
 * 
 * Remaining handlers are for messages NOT handled by ServicesTab.
 */
export class ServiceMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onQueryDBus: (service: string, method: string, args: any[]) => Promise<void>;
    onRefreshOllamaStatus: () => Promise<void>;
  };

  constructor(callbacks: ServiceMessageHandler["callbacks"]) {
    super([
      "queryDBus",
      // NOTE: refreshServices, serviceControl, testOllamaInstance removed - ServicesTab handles them directly
      "refreshOllamaStatus",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "queryDBus":
        await this.callbacks.onQueryDBus(message.service, message.method, message.args);
        break;
      case "refreshOllamaStatus":
        await this.callbacks.onRefreshOllamaStatus();
        break;
    }
  }
}

// NOTE: CronMessageHandler removed - CronTab handles cron messages directly via D-Bus

/**
 * Handler for simple command messages that just trigger VS Code commands.
 */
export class CommandMessageHandler extends BaseMessageHandler {
  constructor() {
    super([
      "openJira",
      "openMR",
      "switchAgent",
      "startWork",
      "coffee",
      "beer",
      "openJiraBoard",
      "openJiraIssue",
    ]);
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "openJira":
        await vscode.commands.executeCommand("aa-workflow.openJira");
        break;
      case "openMR":
        await vscode.commands.executeCommand("aa-workflow.openMR");
        break;
      case "switchAgent":
        await vscode.commands.executeCommand("aa-workflow.switchAgent");
        break;
      case "startWork":
        await vscode.commands.executeCommand("aa-workflow.startWork");
        break;
      case "coffee":
        await vscode.commands.executeCommand("aa-workflow.coffee");
        break;
      case "beer":
        await vscode.commands.executeCommand("aa-workflow.beer");
        break;
      case "openJiraBoard":
        await vscode.env.openExternal(
          vscode.Uri.parse("https://issues.redhat.com/secure/RapidBoard.jspa?rapidView=14813")
        );
        break;
      case "openJiraIssue":
        if (message.issueKey) {
          await vscode.env.openExternal(
            vscode.Uri.parse(`https://issues.redhat.com/browse/${message.issueKey}`)
          );
        }
        break;
    }
  }
}

/**
 * Handler for utility messages like ping/pong.
 * Note: switchTab is handled by TabMessageHandler, not here.
 */
export class UtilityMessageHandler extends BaseMessageHandler {
  constructor() {
    super(["ping", "webviewLog"]);
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "ping":
        context.postMessage({ command: "pong" });
        break;
      case "webviewLog":
        logger.log(`[Webview] ${message.message}`);
        break;
    }
  }
}

/**
 * Handler for meeting history messages.
 */
export class MeetingHistoryMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onViewNote: (noteId: string) => Promise<void>;
    onViewTranscript: (noteId: string) => Promise<void>;
    onViewBotLog: (noteId: string) => Promise<void>;
    onViewLinkedIssues: (noteId: string) => Promise<void>;
    onSearchNotes: (query: string) => Promise<void>;
    onCopyTranscript: () => Promise<void>;
    onClearCaptions: () => Promise<void>;
  };

  constructor(callbacks: MeetingHistoryMessageHandler["callbacks"]) {
    super([
      "viewNote",
      "viewTranscript",
      "viewBotLog",
      "viewLinkedIssues",
      "searchNotes",
      "copyTranscript",
      "clearCaptions",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "viewNote":
        await this.callbacks.onViewNote(message.noteId);
        break;
      case "viewTranscript":
        await this.callbacks.onViewTranscript(message.noteId);
        break;
      case "viewBotLog":
        await this.callbacks.onViewBotLog(message.noteId);
        break;
      case "viewLinkedIssues":
        await this.callbacks.onViewLinkedIssues(message.noteId);
        break;
      case "searchNotes":
        await this.callbacks.onSearchNotes(message.query);
        break;
      case "copyTranscript":
        await this.callbacks.onCopyTranscript();
        break;
      case "clearCaptions":
        await this.callbacks.onClearCaptions();
        break;
    }
  }
}

/**
 * Handler for video preview messages.
 */
export class VideoPreviewMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onStartVideoPreview: (device: string, mode: string) => Promise<void>;
    onStopVideoPreview: () => Promise<void>;
    onGetVideoPreviewFrame: () => Promise<void>;
  };

  constructor(callbacks: VideoPreviewMessageHandler["callbacks"]) {
    super([
      "startVideoPreview",
      "stopVideoPreview",
      "getVideoPreviewFrame",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "startVideoPreview":
        await this.callbacks.onStartVideoPreview(message.device, message.mode || "webrtc");
        break;
      case "stopVideoPreview":
        await this.callbacks.onStopVideoPreview();
        break;
      case "getVideoPreviewFrame":
        await this.callbacks.onGetVideoPreviewFrame();
        break;
    }
  }
}

/**
 * Handler for meeting audio controls.
 */
export class MeetingAudioMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onMuteAudio: (sessionId: string) => Promise<void>;
    onUnmuteAudio: (sessionId: string) => Promise<void>;
    onTestTTS: (sessionId: string) => Promise<void>;
    onTestAvatar: (sessionId: string) => Promise<void>;
    onPreloadJira: (sessionId: string) => Promise<void>;
    onSetDefaultMode: (mode: string) => Promise<void>;
  };

  constructor(callbacks: MeetingAudioMessageHandler["callbacks"]) {
    super([
      "muteAudio",
      "unmuteAudio",
      "testTTS",
      "testAvatar",
      "preloadJira",
      "setDefaultMode",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "muteAudio":
        await this.callbacks.onMuteAudio(message.sessionId);
        break;
      case "unmuteAudio":
        await this.callbacks.onUnmuteAudio(message.sessionId);
        break;
      case "testTTS":
        await this.callbacks.onTestTTS(message.sessionId);
        break;
      case "testAvatar":
        await this.callbacks.onTestAvatar(message.sessionId);
        break;
      case "preloadJira":
        await this.callbacks.onPreloadJira(message.sessionId);
        break;
      case "setDefaultMode":
        await this.callbacks.onSetDefaultMode(message.mode);
        break;
    }
  }
}

/**
 * Handler for inference testing messages.
 */
export class InferenceMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onRunInferenceTest: (message: string, persona: string, skill: string) => Promise<void>;
    onGetInferenceStats: () => Promise<void>;
    onUpdateInferenceConfig: (key: string, value: any) => Promise<void>;
    onSemanticSearch: (query: string, project: string) => Promise<void>;
    onResetInferenceConfig?: () => Promise<void>;
    onSaveInferenceConfig?: () => Promise<void>;
  };

  constructor(callbacks: InferenceMessageHandler["callbacks"]) {
    super([
      "runInferenceTest",
      "getInferenceStats",
      "updateInferenceConfig",
      "semanticSearch",
      "resetInferenceConfig",
      "saveInferenceConfig",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;
    logger.log(`InferenceMessageHandler.handle: ${msgType}, message.message="${message.message}"`);

    switch (msgType) {
      case "runInferenceTest":
        logger.log(`Calling onRunInferenceTest with message="${message.message}", persona="${message.persona}", skill="${message.skill}"`);
        await this.callbacks.onRunInferenceTest(message.message, message.persona, message.skill);
        break;
      case "getInferenceStats":
        await this.callbacks.onGetInferenceStats();
        break;
      case "updateInferenceConfig":
        await this.callbacks.onUpdateInferenceConfig(message.key, message.value);
        break;
      case "semanticSearch":
        await this.callbacks.onSemanticSearch(message.query, message.project);
        break;
      case "resetInferenceConfig":
        if (this.callbacks.onResetInferenceConfig) {
          await this.callbacks.onResetInferenceConfig();
        }
        break;
      case "saveInferenceConfig":
        if (this.callbacks.onSaveInferenceConfig) {
          await this.callbacks.onSaveInferenceConfig();
        }
        break;
    }
  }
}

/**
 * Handler for Slack persona / context injection test messages.
 */
export class SlackPersonaTestHandler extends BaseMessageHandler {
  private callbacks: {
    onRunPersonaTest: (query: string) => Promise<void>;
    onFetchContextStatus?: () => Promise<void>;
  };

  constructor(callbacks: SlackPersonaTestHandler["callbacks"]) {
    super([
      "runPersonaTest",
      "runContextTest",
      "fetchContextStatus",
      "fetchChannelContext",
      "copyFormattedContext",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;
    logger.log(`SlackPersonaTestHandler.handle: ${msgType}, query="${message.query}"`);

    switch (msgType) {
      case "runPersonaTest":
      case "runContextTest":
        await this.callbacks.onRunPersonaTest(message.query);
        break;
      case "fetchContextStatus":
        if (this.callbacks.onFetchContextStatus) {
          await this.callbacks.onFetchContextStatus();
        }
        break;
      case "fetchChannelContext":
        // TODO: Implement channel context fetching
        logger.log("fetchChannelContext not yet implemented");
        break;
      case "copyFormattedContext":
        // TODO: Implement copy to clipboard
        logger.log("copyFormattedContext not yet implemented");
        break;
    }
  }
}

// NOTE: PersonaMessageHandler removed - PersonasTab handles persona messages directly

/**
 * Handler for workspace-related messages.
 * 
 * NOTE: Some handlers removed - SessionsTab handles them directly:
 * - changeSessionGroupBy, changeSessionViewMode, refreshSessionsNow
 * 
 * Remaining handlers are for workspace management NOT handled by SessionsTab.
 */
export class WorkspaceMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onViewWorkspaceTools: (uri: string) => void;
    onSwitchToWorkspace: (uri: string) => void;
    onChangeWorkspacePersona: (uri: string, persona: string) => void;
    onRemoveWorkspace: (uri: string) => void;
  };

  constructor(callbacks: WorkspaceMessageHandler["callbacks"]) {
    super([
      "viewWorkspaceTools",
      "switchToWorkspace",
      "changeWorkspacePersona",
      "removeWorkspace",
      // NOTE: changeSessionGroupBy, changeSessionViewMode, refreshSessionsNow removed - SessionsTab handles them directly
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "viewWorkspaceTools":
        this.callbacks.onViewWorkspaceTools(message.uri);
        break;
      case "switchToWorkspace":
        this.callbacks.onSwitchToWorkspace(message.uri);
        break;
      case "changeWorkspacePersona":
        this.callbacks.onChangeWorkspacePersona(message.uri, message.persona);
        break;
      case "removeWorkspace":
        this.callbacks.onRemoveWorkspace(message.uri);
        break;
    }
  }
}

/**
 * Handler for tab switching messages.
 */
export class TabMessageHandler extends BaseMessageHandler {
  private callbacks: {
    onSwitchTab: (tab: string) => void;
    onOpenConfigFile: () => Promise<void>;
    onRefreshIssues: () => void;
  };

  constructor(callbacks: TabMessageHandler["callbacks"]) {
    super([
      "switchTab",
      "openConfigFile",
      "refreshIssues",
    ]);
    this.callbacks = callbacks;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    const msgType = message.command || message.type;

    switch (msgType) {
      case "switchTab":
        this.callbacks.onSwitchTab(message.tab);
        break;
      case "openConfigFile":
        await this.callbacks.onOpenConfigFile();
        break;
      case "refreshIssues":
        this.callbacks.onRefreshIssues();
        break;
    }
  }
}

/**
 * Handler for create session tab actions.
 */
export class CreateSessionMessageHandler extends BaseMessageHandler {
  private onCreateSessionAction: (action: string, message: any) => Promise<void>;

  constructor(callbacks: {
    onCreateSessionAction: (action: string, message: any) => Promise<void>;
  }) {
    super(["createSessionAction"]);
    this.onCreateSessionAction = callbacks.onCreateSessionAction;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    await this.onCreateSessionAction(message.action, message);
  }
}

/**
 * Handler for performance tracking actions.
 */
export class PerformanceMessageHandler extends BaseMessageHandler {
  private onPerformanceAction: (action: string, questionId?: string, category?: string, description?: string) => Promise<void>;

  constructor(callbacks: {
    onPerformanceAction: (action: string, questionId?: string, category?: string, description?: string) => Promise<void>;
  }) {
    super(["performanceAction"]);
    this.onPerformanceAction = callbacks.onPerformanceAction;
  }

  async handle(message: WebviewMessage, context: MessageContext): Promise<void> {
    await this.onPerformanceAction(message.action, message.questionId, message.category, message.description);
  }
}
