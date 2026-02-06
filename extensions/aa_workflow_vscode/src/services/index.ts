/**
 * Services Module Exports
 */

// Message Bus
export {
  MessageBus,
  getMessageBus,
  resetMessageBus,
  type UIMessage,
  type MessageHandler,
  type MessageBusOptions,
} from "./MessageBus";

// Notification Service
export {
  NotificationService,
  NotificationType,
  getNotificationService,
  resetNotificationService,
  type Notification,
  type NotificationOptions,
  type NotificationServiceOptions,
} from "./NotificationService";

// Container
export {
  Container,
  createContainer,
  getContainer,
  resetContainer,
  ServiceKeys,
  type ServiceFactory,
  type ServiceDescriptor,
  type ContainerOptions,
  type ServiceKey,
} from "./Container";

// Domain Services
export {
  MeetingService,
  type MeetingServiceDependencies,
  type MeetingNote,
  type TranscriptEntry,
  type BotLogEntry,
  type LinkedIssue,
} from "./MeetingService";

export {
  SlackService,
  type SlackServiceDependencies,
  type SlackMessage,
  type SlackChannel,
  type SlackUser,
  type SlackPendingMessage,
  type SlackCacheStats,
  type SlackSearchResult,
} from "./SlackService";

export {
  SessionService,
  type SessionServiceDependencies,
  type SessionSearchResult,
  type SessionState,
  type WorkspaceState as SessionWorkspaceState,
  type ChatSession as SessionChatSession,
  type MeetingReference as SessionMeetingReference,
} from "./SessionService";

export {
  CronService,
  type CronServiceDependencies,
  type CronJob,
  type CronExecution,
  type CronConfig,
} from "./CronService";

export {
  SprintService,
  type SprintServiceDependencies,
  type SprintIssue,
  type SprintState,
  type SprintBotResult,
} from "./SprintService";

export {
  VideoService,
  type VideoServiceDependencies,
  type VideoMode,
  type VideoPreviewState,
  type VideoFrame,
} from "./VideoService";

// ============================================================================
// Service Container for Tab Injection
// ============================================================================

import type { MeetingService } from "./MeetingService";
import type { SlackService } from "./SlackService";
import type { SessionService } from "./SessionService";
import type { CronService } from "./CronService";
import type { SprintService } from "./SprintService";
import type { VideoService } from "./VideoService";

/**
 * Container for domain services that can be injected into Tabs.
 * This allows Tabs to use Services instead of calling D-Bus directly,
 * eliminating duplicate business logic.
 */
export interface ServiceContainer {
  meeting?: MeetingService;
  slack?: SlackService;
  session?: SessionService;
  cron?: CronService;
  sprint?: SprintService;
  video?: VideoService;
}
