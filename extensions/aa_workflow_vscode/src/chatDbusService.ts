/**
 * Chat D-Bus Service
 *
 * Exposes chat utilities via D-Bus for background processes (like sprint_daemon.py).
 *
 * Service: com.aiworkflow.Chat
 * Path: /com/aiworkflow/Chat
 * Interface: com.aiworkflow.Chat
 *
 * Methods:
 * - LaunchIssueChat(issueKey: string, summary: string, returnToPrevious: bool) -> string (JSON result)
 * - GetActiveChat() -> string (JSON with chatId, chatName)
 * - ListChats() -> string (JSON array)
 * - Ping() -> string (JSON with success, message, timestamp)
 *
 * Usage from Python:
 *   from dbus_next.aio import MessageBus
 *   bus = await MessageBus().connect()
 *   introspection = await bus.introspect("com.aiworkflow.Chat", "/com/aiworkflow/Chat")
 *   proxy = bus.get_proxy_object("com.aiworkflow.Chat", "/com/aiworkflow/Chat", introspection)
 *   chat = proxy.get_interface("com.aiworkflow.Chat")
 *   result = await chat.call_launch_issue_chat("AAP-12345", "Fix the bug", True)
 */

import {
  launchIssueChat,
  getActiveChatId,
  getChatNameById,
  getAllChats,
} from "./chatUtils";
import { createLogger } from "./logger";

const logger = createLogger("ChatDBus");

const DBUS_SERVICE_NAME = "com.aiworkflow.Chat";
const DBUS_OBJECT_PATH = "/com/aiworkflow/Chat";
const DBUS_INTERFACE_NAME = "com.aiworkflow.Chat";

let bus: any = null;
let serviceRegistered = false;
let chatInterface: any = null;
let isShuttingDown = false;

/**
 * Register the D-Bus service
 */
export async function registerChatDbusService(): Promise<void> {
  if (serviceRegistered) {
    logger.log("Service already registered");
    return;
  }

  // Check if D-Bus session is available (may not be in some environments)
  if (!process.env.DBUS_SESSION_BUS_ADDRESS) {
    logger.log("D-Bus session bus not available (DBUS_SESSION_BUS_ADDRESS not set), skipping registration");
    return;
  }

  try {
    // Dynamic import for dbus-next
    const dbus = await import("dbus-next");
    const Interface = dbus.interface.Interface;

    logger.log("Connecting to session bus...");
    bus = dbus.sessionBus();

    // Handle bus errors - CRITICAL: prevent crashes by catching all errors
    bus.on("error", (err: any) => {
      if (isShuttingDown) {
        // Ignore errors during shutdown
        return;
      }
      logger.error(`D-Bus error: ${err.message}`);
      // Don't re-throw - this would crash Cursor
    });

    // Handle disconnection
    bus.on("disconnect", () => {
      logger.log("D-Bus disconnected");
      serviceRegistered = false;
      bus = null;
      chatInterface = null;
    });

    // Create interface class that extends dbus-next Interface
    // Must be defined before configureMembers is called
    class ChatDbusInterface extends Interface {
      constructor() {
        super(DBUS_INTERFACE_NAME);
      }

      // Method implementations - these must exist before configureMembers
      LaunchIssueChat(issueKey: string, summary: string, returnToPrevious: boolean): Promise<string> {
        // Check shutdown state immediately
        if (isShuttingDown) {
          return Promise.resolve(JSON.stringify({ success: false, chatId: null, error: "Service shutting down" }));
        }

        logger.log(`LaunchIssueChat called: issueKey=${issueKey}, summary=${summary}, returnToPrevious=${returnToPrevious}`);
        return launchIssueChat(issueKey, {
          summary: summary || "sprint work",
          returnToPrevious: returnToPrevious ?? true,
        }).then(chatId => {
          if (isShuttingDown) {
            return JSON.stringify({ success: false, chatId: null, error: "Service shutting down" });
          }
          const result = {
            success: !!chatId,
            chatId: chatId || null,
            error: chatId ? null : "Failed to create chat"
          };
          logger.log(`LaunchIssueChat result: ${JSON.stringify(result)}`);
          return JSON.stringify(result);
        }).catch((e: any) => {
          logger.error(`LaunchIssueChat error: ${e.message}`);
          return JSON.stringify({ success: false, chatId: null, error: e.message });
        });
      }

      // Launch chat with custom prompt (for unified sprint bot workflow)
      LaunchIssueChatWithPrompt(issueKey: string, summary: string, prompt: string, returnToPrevious: boolean): Promise<string> {
        // Check shutdown state immediately
        if (isShuttingDown) {
          return Promise.resolve(JSON.stringify({ success: false, chatId: null, error: "Service shutting down" }));
        }

        logger.log(`LaunchIssueChatWithPrompt called: issueKey=${issueKey}, summary=${summary}, promptLength=${prompt?.length || 0}, returnToPrevious=${returnToPrevious}`);
        return launchIssueChat(issueKey, {
          summary: summary || "sprint work",
          returnToPrevious: returnToPrevious ?? true,
          customPrompt: prompt || undefined,
        }).then(chatId => {
          if (isShuttingDown) {
            return JSON.stringify({ success: false, chatId: null, error: "Service shutting down" });
          }
          const result = {
            success: !!chatId,
            chatId: chatId || null,
            error: chatId ? null : "Failed to create chat"
          };
          logger.log(`LaunchIssueChatWithPrompt result: ${JSON.stringify(result)}`);
          return JSON.stringify(result);
        }).catch((e: any) => {
          logger.error(`LaunchIssueChatWithPrompt error: ${e.message}`);
          return JSON.stringify({ success: false, chatId: null, error: e.message });
        });
      }

      GetActiveChat(): string {
        if (isShuttingDown) {
          return JSON.stringify({ chatId: "", chatName: "", error: "Service shutting down" });
        }
        logger.log("GetActiveChat called");
        try {
          const chatId = getActiveChatId() || "";
          const chatName = chatId ? getChatNameById(chatId) || "" : "";
          const result = { chatId, chatName };
          logger.log(`GetActiveChat result: ${JSON.stringify(result)}`);
          return JSON.stringify(result);
        } catch (e: any) {
          logger.error(`GetActiveChat error: ${e.message}`);
          return JSON.stringify({ chatId: "", chatName: "", error: e.message });
        }
      }

      ListChats(): string {
        if (isShuttingDown) {
          return JSON.stringify([]);
        }
        logger.log("ListChats called");
        try {
          const chats = getAllChats();
          logger.log(`ListChats result: ${chats.length} chats`);
          return JSON.stringify(chats);
        } catch (e: any) {
          logger.error(`ListChats error: ${e.message}`);
          return JSON.stringify([]);
        }
      }

      Ping(): string {
        logger.log("Ping called");
        return JSON.stringify({
          success: true,
          message: "pong",
          timestamp: new Date().toISOString(),
          shuttingDown: isShuttingDown
        });
      }
    }

    // Configure the interface members (alternative to decorators)
    // This MUST be called on the class AFTER the class is defined
    // but BEFORE any instances are created
    ChatDbusInterface.configureMembers({
      methods: {
        LaunchIssueChat: {
          inSignature: "ssb",
          outSignature: "s",
        },
        LaunchIssueChatWithPrompt: {
          inSignature: "sssb",  // issueKey, summary, prompt, returnToPrevious
          outSignature: "s",
        },
        GetActiveChat: {
          inSignature: "",
          outSignature: "s",
        },
        ListChats: {
          inSignature: "",
          outSignature: "s",
        },
        Ping: {
          inSignature: "",
          outSignature: "s",
        },
      },
    });

    // Request the service name
    logger.log(`Requesting service name: ${DBUS_SERVICE_NAME}`);
    await bus.requestName(DBUS_SERVICE_NAME, 0);
    logger.log(`Service name acquired: ${DBUS_SERVICE_NAME}`);

    // Create and export the interface instance
    chatInterface = new ChatDbusInterface();
    bus.export(DBUS_OBJECT_PATH, chatInterface);

    serviceRegistered = true;
    logger.log(`D-Bus service registered at ${DBUS_OBJECT_PATH}`);
    logger.log("Available methods: LaunchIssueChat, GetActiveChat, ListChats, Ping");
  } catch (e: any) {
    logger.error(`Failed to register D-Bus service: ${e.message}`);
    logger.error(`Stack: ${e.stack}`);
    // Don't throw - the extension can still work without D-Bus
  }
}

/**
 * Unregister the D-Bus service
 */
export async function unregisterChatDbusService(): Promise<void> {
  isShuttingDown = true;

  if (!serviceRegistered || !bus) {
    return;
  }

  try {
    logger.log("Unregistering D-Bus service...");

    // Remove error handlers first to prevent crash during shutdown
    bus.removeAllListeners("error");
    bus.removeAllListeners("disconnect");

    try {
      await bus.releaseName(DBUS_SERVICE_NAME);
    } catch (e: any) {
      // Ignore release errors during shutdown
      logger.log(`Release name warning (ignorable): ${e.message}`);
    }

    try {
      bus.disconnect();
    } catch (e: any) {
      // Ignore disconnect errors
      logger.log(`Disconnect warning (ignorable): ${e.message}`);
    }

    bus = null;
    chatInterface = null;
    serviceRegistered = false;
    logger.log("D-Bus service unregistered");
  } catch (e: any) {
    logger.error(`Failed to unregister D-Bus service: ${e.message}`);
  } finally {
    isShuttingDown = false;
  }
}

/**
 * Check if the D-Bus service is registered
 */
export function isServiceRegistered(): boolean {
  return serviceRegistered;
}
