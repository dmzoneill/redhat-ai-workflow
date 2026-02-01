/**
 * Container - Simple Dependency Injection
 *
 * A lightweight DI container that:
 * - Manages service instances
 * - Supports lazy initialization
 * - Provides typed access to services
 * - Handles cleanup on dispose
 *
 * This wires together all the services and makes them available
 * to the CommandCenterPanel without tight coupling.
 */

import * as vscode from "vscode";
import { StateStore, getStateStore, resetStateStore } from "../state";
import { MessageBus, getMessageBus, resetMessageBus } from "./MessageBus";
import { NotificationService, getNotificationService, resetNotificationService } from "./NotificationService";
import { dbus } from "../dbusClient";
import { createLogger } from "../logger";

const logger = createLogger("Container");

// ============================================================================
// Types
// ============================================================================

export type ServiceFactory<T> = () => T;

export interface ServiceDescriptor<T> {
  factory: ServiceFactory<T>;
  instance?: T;
  singleton: boolean;
}

export interface ContainerOptions {
  /** VSCode webview panel */
  panel?: vscode.WebviewPanel;
  /** Extension URI */
  extensionUri?: vscode.Uri;
}

// ============================================================================
// Service Keys (type-safe service identifiers)
// ============================================================================

export const ServiceKeys = {
  STATE: "state",
  MESSAGES: "messages",
  NOTIFICATIONS: "notifications",
  DBUS: "dbus",
  // Domain services (to be added)
  MEETING_SERVICE: "meetingService",
  SLACK_SERVICE: "slackService",
  SPRINT_SERVICE: "sprintService",
  CRON_SERVICE: "cronService",
  SESSION_SERVICE: "sessionService",
  MEMORY_SERVICE: "memoryService",
  SKILL_SERVICE: "skillService",
} as const;

export type ServiceKey = typeof ServiceKeys[keyof typeof ServiceKeys];

// ============================================================================
// Container Class
// ============================================================================

export class Container {
  private services: Map<string, ServiceDescriptor<any>> = new Map();
  private options: ContainerOptions;
  private disposed: boolean = false;

  constructor(options: ContainerOptions = {}) {
    this.options = options;
    this.registerCoreServices();
  }

  // ============================================================================
  // Registration
  // ============================================================================

  /**
   * Register a service factory
   */
  register<T>(key: string, factory: ServiceFactory<T>, singleton: boolean = true): this {
    if (this.disposed) {
      throw new Error("Container has been disposed");
    }

    this.services.set(key, {
      factory,
      singleton,
    });

    return this;
  }

  /**
   * Register an existing instance
   */
  registerInstance<T>(key: string, instance: T): this {
    if (this.disposed) {
      throw new Error("Container has been disposed");
    }

    this.services.set(key, {
      factory: () => instance,
      instance,
      singleton: true,
    });

    return this;
  }

  // ============================================================================
  // Resolution
  // ============================================================================

  /**
   * Get a service by key
   */
  get<T>(key: string): T {
    if (this.disposed) {
      throw new Error("Container has been disposed");
    }

    const descriptor = this.services.get(key);
    if (!descriptor) {
      throw new Error(`Service not registered: ${key}`);
    }

    // Return existing instance for singletons
    if (descriptor.singleton && descriptor.instance !== undefined) {
      return descriptor.instance as T;
    }

    // Create new instance
    const instance = descriptor.factory();

    // Cache singleton instances
    if (descriptor.singleton) {
      descriptor.instance = instance;
    }

    return instance as T;
  }

  /**
   * Check if a service is registered
   */
  has(key: string): boolean {
    return this.services.has(key);
  }

  /**
   * Get all registered service keys
   */
  getKeys(): string[] {
    return Array.from(this.services.keys());
  }

  // ============================================================================
  // Typed Accessors (convenience methods)
  // ============================================================================

  get state(): StateStore {
    return this.get<StateStore>(ServiceKeys.STATE);
  }

  get messages(): MessageBus {
    return this.get<MessageBus>(ServiceKeys.MESSAGES);
  }

  get notifications(): NotificationService {
    return this.get<NotificationService>(ServiceKeys.NOTIFICATIONS);
  }

  get dbusClient(): typeof dbus {
    return this.get<typeof dbus>(ServiceKeys.DBUS);
  }

  // ============================================================================
  // Core Service Registration
  // ============================================================================

  private registerCoreServices(): void {
    // State Store - centralized state management
    this.register(ServiceKeys.STATE, () => getStateStore());

    // Message Bus - UI communication
    this.register(ServiceKeys.MESSAGES, () => {
      const bus = getMessageBus();
      // Connect to webview if panel is available
      if (this.options.panel) {
        bus.connect(this.options.panel.webview);
      }
      return bus;
    });

    // Notification Service - user notifications
    this.register(ServiceKeys.NOTIFICATIONS, () => getNotificationService());

    // D-Bus Client - daemon communication
    this.registerInstance(ServiceKeys.DBUS, dbus);
  }

  // ============================================================================
  // Lifecycle
  // ============================================================================

  /**
   * Initialize all registered services
   * (useful for eager initialization)
   */
  initializeAll(): void {
    for (const key of this.services.keys()) {
      this.get(key);
    }
  }

  /**
   * Dispose of all services and reset singletons
   */
  dispose(): void {
    if (this.disposed) return;

    // Dispose services that have dispose methods
    for (const [key, descriptor] of this.services) {
      if (descriptor.instance && typeof descriptor.instance.dispose === "function") {
        try {
          descriptor.instance.dispose();
        } catch (e) {
          logger.error(`Error disposing service ${key}`, e);
        }
      }
    }

    // Clear all services
    this.services.clear();

    // Reset singleton instances
    resetStateStore();
    resetMessageBus();
    resetNotificationService();

    this.disposed = true;
  }

  /**
   * Check if container has been disposed
   */
  isDisposed(): boolean {
    return this.disposed;
  }
}

// ============================================================================
// Factory Function
// ============================================================================

/**
 * Create a new container with the given options
 */
export function createContainer(options: ContainerOptions = {}): Container {
  return new Container(options);
}

// ============================================================================
// Global Container (optional singleton pattern)
// ============================================================================

let globalContainer: Container | null = null;

/**
 * Get or create the global container
 */
export function getContainer(options?: ContainerOptions): Container {
  if (!globalContainer || globalContainer.isDisposed()) {
    globalContainer = createContainer(options);
  }
  return globalContainer;
}

/**
 * Reset the global container
 */
export function resetContainer(): void {
  if (globalContainer) {
    globalContainer.dispose();
    globalContainer = null;
  }
}
