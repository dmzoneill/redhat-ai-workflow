/**
 * MessageBus - Decoupled UI Communication
 *
 * A message bus that decouples business logic from webview communication.
 * Business logic publishes messages without knowing about the webview,
 * and the bus handles delivery.
 *
 * Benefits:
 * - Business logic can be tested without mocking VSCode
 * - Messages can be logged, filtered, or batched
 * - Multiple subscribers can react to the same message
 * - Easy to add new message types without changing business logic
 */

import * as vscode from "vscode";
import { createLogger } from "../logger";

const logger = createLogger("MessageBus");

// ============================================================================
// Types
// ============================================================================

export interface UIMessage {
  type: string;
  [key: string]: any;
}

export type MessageHandler = (message: UIMessage) => void | Promise<void>;

export interface MessageBusOptions {
  /** Enable debug logging */
  debug?: boolean;
  /** Batch messages within this window (ms) - 0 to disable */
  batchWindow?: number;
}

// ============================================================================
// MessageBus Class
// ============================================================================

export class MessageBus {
  private webview: vscode.Webview | null = null;
  private subscribers: Map<string, Set<MessageHandler>> = new Map();
  private options: Required<MessageBusOptions>;
  private batchQueue: UIMessage[] = [];
  private batchTimer: NodeJS.Timeout | null = null;
  private messageHistory: UIMessage[] = [];
  private maxHistorySize: number = 100;

  constructor(options: MessageBusOptions = {}) {
    this.options = {
      debug: options.debug ?? false,
      batchWindow: options.batchWindow ?? 0,
    };
  }

  // ============================================================================
  // Connection Management
  // ============================================================================

  /**
   * Connect to a webview for message delivery.
   * Called once during panel setup.
   */
  connect(webview: vscode.Webview): void {
    this.webview = webview;
    this.log("Connected to webview");
  }

  /**
   * Disconnect from webview (e.g., when panel is disposed)
   */
  disconnect(): void {
    this.webview = null;
    this.flushBatch(); // Send any pending messages
    this.log("Disconnected from webview");
  }

  /**
   * Check if connected to a webview
   */
  isConnected(): boolean {
    return this.webview !== null;
  }

  // ============================================================================
  // Publishing
  // ============================================================================

  /**
   * Publish a message to the webview and any local subscribers.
   * Business logic calls this - no direct webview dependency needed.
   */
  publish(type: string, payload: Record<string, any> = {}): void {
    const message: UIMessage = { type, ...payload };

    this.log(`Publishing: ${type}`, payload);
    this.recordHistory(message);

    // Notify local subscribers (for testing, logging, cross-component communication)
    this.notifySubscribers(message);

    // Send to webview
    if (this.options.batchWindow > 0) {
      this.queueMessage(message);
    } else {
      this.sendToWebview(message);
    }
  }

  /**
   * Publish multiple messages at once (for efficiency)
   */
  publishBatch(messages: Array<{ type: string; payload?: Record<string, any> }>): void {
    for (const { type, payload } of messages) {
      this.publish(type, payload || {});
    }
  }

  // ============================================================================
  // Subscription
  // ============================================================================

  /**
   * Subscribe to messages of a specific type.
   * Use '*' to subscribe to all messages.
   * Returns an unsubscribe function.
   */
  subscribe(type: string, handler: MessageHandler): () => void {
    if (!this.subscribers.has(type)) {
      this.subscribers.set(type, new Set());
    }
    this.subscribers.get(type)!.add(handler);

    this.log(`Subscribed to: ${type}`);

    // Return unsubscribe function
    return () => {
      this.subscribers.get(type)?.delete(handler);
      this.log(`Unsubscribed from: ${type}`);
    };
  }

  /**
   * Subscribe to multiple message types with the same handler
   */
  subscribeMany(types: string[], handler: MessageHandler): () => void {
    const unsubscribes = types.map(type => this.subscribe(type, handler));
    return () => unsubscribes.forEach(unsub => unsub());
  }

  /**
   * Subscribe to a message type, but only trigger once
   */
  once(type: string, handler: MessageHandler): () => void {
    const unsubscribe = this.subscribe(type, async (message) => {
      unsubscribe();
      await handler(message);
    });
    return unsubscribe;
  }

  // ============================================================================
  // History & Debugging
  // ============================================================================

  /**
   * Get recent message history (for debugging)
   */
  getHistory(): UIMessage[] {
    return [...this.messageHistory];
  }

  /**
   * Clear message history
   */
  clearHistory(): void {
    this.messageHistory = [];
  }

  /**
   * Get subscriber count for a message type
   */
  getSubscriberCount(type: string): number {
    return this.subscribers.get(type)?.size ?? 0;
  }

  /**
   * Get all subscribed message types
   */
  getSubscribedTypes(): string[] {
    return Array.from(this.subscribers.keys());
  }

  // ============================================================================
  // Internal Methods
  // ============================================================================

  private notifySubscribers(message: UIMessage): void {
    // Notify type-specific subscribers
    const typeHandlers = this.subscribers.get(message.type);
    if (typeHandlers) {
      for (const handler of typeHandlers) {
        try {
          handler(message);
        } catch (e) {
          logger.error(`Handler error for ${message.type}`, e);
        }
      }
    }

    // Notify wildcard subscribers
    const wildcardHandlers = this.subscribers.get('*');
    if (wildcardHandlers) {
      for (const handler of wildcardHandlers) {
        try {
          handler(message);
        } catch (e) {
          logger.error("Wildcard handler error", e);
        }
      }
    }
  }

  private sendToWebview(message: UIMessage): void {
    if (this.webview) {
      this.webview.postMessage(message);
    } else {
      this.log(`Warning: No webview connected, message not sent: ${message.type}`);
    }
  }

  private queueMessage(message: UIMessage): void {
    this.batchQueue.push(message);

    if (!this.batchTimer) {
      this.batchTimer = setTimeout(() => {
        this.flushBatch();
      }, this.options.batchWindow);
    }
  }

  private flushBatch(): void {
    if (this.batchTimer) {
      clearTimeout(this.batchTimer);
      this.batchTimer = null;
    }

    if (this.batchQueue.length === 0) return;

    // Send all queued messages
    for (const message of this.batchQueue) {
      this.sendToWebview(message);
    }

    this.log(`Flushed ${this.batchQueue.length} batched messages`);
    this.batchQueue = [];
  }

  private recordHistory(message: UIMessage): void {
    this.messageHistory.push({
      ...message,
      _timestamp: new Date().toISOString(),
    });

    // Trim history if needed
    if (this.messageHistory.length > this.maxHistorySize) {
      this.messageHistory = this.messageHistory.slice(-this.maxHistorySize);
    }
  }

  private log(msg: string, data?: any): void {
    if (this.options.debug) {
      if (data) {
        logger.log(`${msg} ${JSON.stringify(data)}`);
      } else {
        logger.log(msg);
      }
    }
  }

  // ============================================================================
  // Cleanup
  // ============================================================================

  /**
   * Dispose of the message bus
   */
  dispose(): void {
    this.disconnect();
    this.subscribers.clear();
    this.messageHistory = [];
    this.batchQueue = [];
  }
}

// ============================================================================
// Singleton Instance
// ============================================================================

let messageBusInstance: MessageBus | null = null;

export function getMessageBus(): MessageBus {
  if (!messageBusInstance) {
    messageBusInstance = new MessageBus();
  }
  return messageBusInstance;
}

export function resetMessageBus(): void {
  if (messageBusInstance) {
    messageBusInstance.dispose();
  }
  messageBusInstance = null;
}
