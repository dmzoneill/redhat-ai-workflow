/**
 * Chat Utilities - Reusable functions for Cursor chat operations
 *
 * Provides a unified API for:
 * - Creating new chats with messages
 * - Opening existing chats by ID or name
 * - Renaming chats
 * - Sending keys via ydotool (Wayland compatible)
 *
 * Can be used from:
 * - UI button clicks
 * - D-Bus calls
 * - WebSocket messages
 * - Background processes
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { spawnSync } from "child_process";
import { createLogger, showLog } from "./logger";

// Create a scoped logger for chat utilities
const logger = createLogger("Chat");

// Re-export for backwards compatibility
export const log = logger.log;
export const showOutput = showLog;

// ============================================================================
// Types
// ============================================================================

export interface ChatOptions {
  /** Message to send in the chat */
  message?: string;
  /** Title/name for the chat (will attempt to rename) */
  title?: string;
  /** If true, return to previous chat after creating new one */
  returnToPrevious?: boolean;
  /** If true, auto-submit the message */
  autoSubmit?: boolean;
  /** Delay in ms between operations (default: 150) */
  delay?: number;
}

export interface OpenChatOptions {
  /** Chat ID (Cursor composer UUID) */
  chatId?: string;
  /** Chat name to search for */
  chatName?: string;
  /** If true, auto-press Enter to select first result */
  autoSelect?: boolean;
}

// ============================================================================
// ydotool Key Sending (Wayland compatible)
// ============================================================================

const YDOTOOL_ENV = { ...process.env, YDOTOOL_SOCKET: "/tmp/.ydotool_socket" };

// Key codes for ydotool (from /usr/include/linux/input-event-codes.h)
const KEY_CODES = {
  ENTER: ["28:1", "28:0"],
  CTRL_V: ["29:1", "47:1", "47:0", "29:0"],  // Ctrl+V
  CTRL_SHIFT_L: ["29:1", "42:1", "38:1", "38:0", "42:0", "29:0"],  // Ctrl+Shift+L
  ESC: ["1:1", "1:0"],
  TAB: ["15:1", "15:0"],
  DOWN: ["108:1", "108:0"],
  UP: ["103:1", "103:0"],
};

/**
 * Send keystrokes via ydotool (Wayland compatible)
 * @param keycodes Array of keycode strings (e.g., ["28:1", "28:0"] for Enter)
 * @returns true if successful
 */
export function sendKeys(keycodes: string[]): boolean {
  try {
    const result = spawnSync("/usr/bin/ydotool", ["key", ...keycodes], {
      env: YDOTOOL_ENV,
      timeout: 5000,
    });
    return result.status === 0;
  } catch (e) {
    console.error("[ChatUtils] sendKeys failed:", e);
    return false;
  }
}

/**
 * Send Enter key
 */
export function sendEnter(): boolean {
  return sendKeys(KEY_CODES.ENTER);
}

/**
 * Send Ctrl+V (paste)
 */
export function sendPaste(): boolean {
  return sendKeys(KEY_CODES.CTRL_V);
}

/**
 * Send Escape key
 */
export function sendEscape(): boolean {
  return sendKeys(KEY_CODES.ESC);
}

// ============================================================================
// Sleep Helper
// ============================================================================

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ============================================================================
// Cursor Database Access
// ============================================================================

/**
 * Get the workspace storage directory for the current workspace
 */
function getWorkspaceStorageDir(): string | null {
  const workspaceStorageDir = path.join(os.homedir(), ".config", "Cursor", "User", "workspaceStorage");
  const currentWorkspaceUri = vscode.workspace.workspaceFolders?.[0]?.uri.toString();

  if (!fs.existsSync(workspaceStorageDir) || !currentWorkspaceUri) {
    return null;
  }

  const storageDirs = fs.readdirSync(workspaceStorageDir);
  for (const dir of storageDirs) {
    const workspaceJsonPath = path.join(workspaceStorageDir, dir, "workspace.json");
    if (fs.existsSync(workspaceJsonPath)) {
      try {
        const workspaceJson = JSON.parse(fs.readFileSync(workspaceJsonPath, "utf8"));
        if (workspaceJson.folder === currentWorkspaceUri) {
          return path.join(workspaceStorageDir, dir);
        }
      } catch {
        // Skip invalid workspace.json
      }
    }
  }
  return null;
}

/**
 * Get composer data from Cursor's SQLite database
 */
export function getComposerData(): any | null {
  const storageDir = getWorkspaceStorageDir();
  if (!storageDir) {
    log("getComposerData: No storage dir found");
    return null;
  }
  log("getComposerData: Storage dir: " + storageDir);

  const dbPath = path.join(storageDir, "state.vscdb");
  if (!fs.existsSync(dbPath)) {
    log("getComposerData: Database not found at: " + dbPath);
    return null;
  }

  try {
    const query = `SELECT value FROM ItemTable WHERE key = 'composer.composerData'`;
    const result = spawnSync("sqlite3", [dbPath, query], { encoding: "utf8", timeout: 5000 });

    if (result.error) {
      log("getComposerData: sqlite3 error: " + result.error);
      return null;
    }
    if (result.status !== 0) {
      log("getComposerData: sqlite3 exit code: " + result.status + " stderr: " + result.stderr);
      return null;
    }

    if (result.stdout?.trim()) {
      const data = JSON.parse(result.stdout.trim());
      log(`getComposerData: Found ${data.allComposers?.length || 0} composers, selectedIds: ${JSON.stringify(data.selectedComposerIds)}`);
      return data;
    }
    log("getComposerData: No data returned from sqlite3");
  } catch (e) {
    log("getComposerData: Failed to read composer data: " + e);
  }
  return null;
}

/**
 * Get chat name by ID from Cursor's database
 */
export function getChatNameById(chatId: string): string | null {
  const composerData = getComposerData();
  if (!composerData) return null;

  const chat = (composerData.allComposers || []).find((c: any) => c.composerId === chatId);
  return chat?.name || chat?.subtitle || null;
}

/**
 * Get the currently active chat ID
 * Tries multiple sources: database selectedComposerIds, then allComposers sorted by recent
 */
export function getActiveChatId(): string | null {
  const composerData = getComposerData();
  if (!composerData) {
    log("getActiveChatId: No composer data found");
    return null;
  }

  // Try selectedComposerIds first (currently open/focused chats)
  const selectedIds = composerData.selectedComposerIds || [];
  if (selectedIds.length > 0) {
    log("getActiveChatId: Found from selectedComposerIds: " + selectedIds[0]);
    return selectedIds[0];
  }

  // Fallback: get the most recent composer from allComposers
  const allComposers = composerData.allComposers || [];
  if (allComposers.length > 0) {
    // Sort by createdAt descending to get most recent
    const sorted = [...allComposers].sort((a: any, b: any) => {
      const aTime = a.lastUpdatedAt || a.createdAt || 0;
      const bTime = b.lastUpdatedAt || b.createdAt || 0;
      return bTime - aTime;
    });
    const mostRecent = sorted[0]?.composerId;
    log("getActiveChatId: Found from allComposers (most recent): " + mostRecent);
    return mostRecent || null;
  }

  log("getActiveChatId: No active chat found");
  return null;
}

/**
 * Get all chats from the database
 */
export function getAllChats(): Array<{ id: string; name: string; createdAt: string }> {
  const composerData = getComposerData();
  if (!composerData) return [];

  return (composerData.allComposers || []).map((c: any) => ({
    id: c.composerId,
    name: c.name || c.subtitle || "Untitled",
    createdAt: c.createdAt || "",
  }));
}

// ============================================================================
// Chat Operations
// ============================================================================

/**
 * Create a new chat and optionally send a message
 *
 * @param options Chat creation options
 * @returns The new chat ID if available, or null
 */
export async function createNewChat(options: ChatOptions = {}): Promise<string | null> {
  const delay = options.delay || 150;
  const previousChatId = options.returnToPrevious ? getActiveChatId() : null;

  console.log("[ChatUtils] Creating new chat, returnToPrevious:", options.returnToPrevious);

  // Save original clipboard if we need to paste
  let originalClipboard: string | undefined;
  if (options.message) {
    originalClipboard = await vscode.env.clipboard.readText();
    await vscode.env.clipboard.writeText(options.message);
  }

  try {
    // Create new composer tab (opens prompt)
    await vscode.commands.executeCommand("composer.createNewComposerTab");
    await sleep(delay * 2);

    // Accept the prompt with Enter
    sendEnter();
    await sleep(delay * 3);

    // If we have a message, paste and submit
    if (options.message) {
      await vscode.commands.executeCommand("composer.focusComposer");
      await sleep(delay);

      sendPaste();
      await sleep(delay * 2);

      // Restore clipboard
      if (originalClipboard !== undefined) {
        await vscode.env.clipboard.writeText(originalClipboard);
      }

      // Auto-submit if requested
      if (options.autoSubmit !== false) {
        sendEnter();
      }
    }

    // Try to get the new chat ID
    await sleep(delay * 2);
    const newChatId = getActiveChatId();

    // Rename the chat if title provided
    if (options.title && newChatId) {
      await renameChat(newChatId, options.title);
    }

    // Return to previous chat if requested
    if (options.returnToPrevious && previousChatId) {
      await sleep(delay * 3);
      await openChatById(previousChatId, { autoSelect: true });
    }

    return newChatId;
  } catch (e) {
    console.error("[ChatUtils] createNewChat failed:", e);
    // Restore clipboard on error
    if (originalClipboard !== undefined) {
      await vscode.env.clipboard.writeText(originalClipboard);
    }
    return null;
  }
}

/**
 * Open an existing chat by ID
 *
 * @param chatId The Cursor composer UUID
 * @param options Open options
 */
export async function openChatById(chatId: string, options: OpenChatOptions = {}): Promise<boolean> {
  const chatName = getChatNameById(chatId);
  return openChatByName(chatName || "", { ...options, chatId });
}

/**
 * Open a chat by searching for its name
 *
 * @param chatName The chat name to search for
 * @param options Open options
 */
export async function openChatByName(chatName: string, options: OpenChatOptions = {}): Promise<boolean> {
  try {
    // Open Quick Open with chat search
    const searchQuery = chatName ? `chat:${chatName}` : "chat:";
    await vscode.commands.executeCommand("workbench.action.quickOpen", searchQuery);

    // Auto-select first result if requested
    if (options.autoSelect) {
      await sleep(200);
      sendEnter();
    }

    return true;
  } catch (e) {
    console.error("[ChatUtils] openChatByName failed:", e);
    return false;
  }
}

/**
 * Send a mouse click via ydotool
 * @param button 0=left, 1=right, 2=middle
 * @param doubleClick If true, send double-click
 */
function sendMouseClick(button: number = 0, doubleClick: boolean = false): boolean {
  try {
    // ydotool click format: button code (0x00=left, 0x01=right, 0x02=middle)
    // For double-click, we send two clicks in quick succession
    const buttonCode = button.toString(16).padStart(2, '0');

    if (doubleClick) {
      // Send two clicks with minimal delay
      const result1 = spawnSync("/usr/bin/ydotool", ["click", `0xC0${buttonCode}`], {
        env: YDOTOOL_ENV,
        timeout: 5000,
      });
      // Small delay between clicks
      const result2 = spawnSync("/usr/bin/ydotool", ["click", `0xC0${buttonCode}`], {
        env: YDOTOOL_ENV,
        timeout: 5000,
      });
      return result1.status === 0 && result2.status === 0;
    } else {
      const result = spawnSync("/usr/bin/ydotool", ["click", `0xC0${buttonCode}`], {
        env: YDOTOOL_ENV,
        timeout: 5000,
      });
      return result.status === 0;
    }
  } catch (e) {
    log("sendMouseClick failed: " + e);
    return false;
  }
}

/**
 * Type text character by character via ydotool
 * This is more reliable than paste for inline edit fields
 */
function typeText(text: string): boolean {
  try {
    const result = spawnSync("/usr/bin/ydotool", ["type", "--", text], {
      env: YDOTOOL_ENV,
      timeout: 10000,
    });
    return result.status === 0;
  } catch (e) {
    log("typeText failed: " + e);
    return false;
  }
}

/**
 * Rename a chat by simulating the UI interaction
 *
 * Based on Cursor source code analysis:
 * - Double-click on chat tab triggers startInlineRename()
 * - This creates an input field overlay
 * - Type new name and press Enter to confirm
 *
 * The key challenge is that the rename is triggered on the chat TAB element,
 * not through a VS Code command. We need to:
 * 1. Make sure the chat is visible in the sidebar
 * 2. Trigger the context menu on the tab
 * 3. Select "Rename Chat"
 * 4. Type the new name
 *
 * @param chatId The chat ID to rename
 * @param newName The new name
 */
export async function renameChat(chatId: string, newName: string): Promise<boolean> {
  log("========================================");
  log("renameChat called");
  log("  chatId: " + chatId);
  log("  newName: " + newName);
  log("========================================");

  try {
    // Get the current chat info
    const composerData = getComposerData();
    const chat = composerData?.allComposers?.find((c: any) => c.composerId === chatId);
    if (!chat) {
      log("ERROR: Chat not found in database");
      return false;
    }

    const currentName = chat.name || "Untitled";
    log("Current chat name: '" + currentName + "'");

    // Step 1: Open the chat history panel where we can see all chats
    log("Step 1: Opening composer history panel...");
    await vscode.commands.executeCommand("composer.showComposerHistory");
    await sleep(600);

    // Step 2: The history panel shows a list of chats
    // We need to navigate to the correct chat and trigger rename
    // Let's try using keyboard navigation

    const approaches = [
      // Approach 1: Use keyboard to navigate and trigger context menu
      // In the history list, we can use arrow keys and then Shift+F10 for context menu
      async () => {
        log("Approach 1: Keyboard navigation + Shift+F10 context menu...");

        // Focus should be on the history panel now
        // Try Shift+F10 to open context menu (standard Windows/Linux shortcut)
        sendKeys(["42:1", "68:1", "68:0", "42:0"]); // Shift+F10
        await sleep(400);

        // "Rename Chat" should be first or near first in context menu
        // Press Enter to select it
        sendEnter();
        await sleep(400);
      },

      // Approach 2: Try the application menu key (key code 127)
      async () => {
        log("Approach 2: Application/Menu key for context menu...");
        sendKeys(["127:1", "127:0"]); // Menu key
        await sleep(400);
        sendEnter();
        await sleep(400);
      },

      // Approach 3: Focus the chat first, then try F2
      async () => {
        log("Approach 3: Focus chat via quick open, then F2...");

        // Use quick open to focus the specific chat
        await vscode.commands.executeCommand("workbench.action.quickOpen", `chat:${currentName}`);
        await sleep(300);
        sendEnter(); // Select the chat
        await sleep(500);

        // Now try F2 while the chat is focused
        sendKeys(["58:1", "58:0"]); // F2
        await sleep(400);
      },

      // Approach 4: Try opening chat as editor then rename
      async () => {
        log("Approach 4: Open as editor approach...");

        // First focus the chat
        await openChatById(chatId, { autoSelect: true });
        await sleep(400);

        // Try the editor rename command
        try {
          await vscode.commands.executeCommand("workbench.action.editor.changeLanguageMode");
        } catch (e) {
          // Ignore - just trying different commands
        }
        await sleep(200);
        sendEscape(); // Cancel if it opened something
        await sleep(200);

        // Try F2 again
        sendKeys(["58:1", "58:0"]);
        await sleep(400);
      },
    ];

    for (let i = 0; i < approaches.length; i++) {
      log("--- Trying approach " + (i + 1) + " ---");

      try {
        // Trigger the rename mode
        await approaches[i]();

        // Check if we're in an input field by trying to type
        // If rename mode is active, there should be an input field focused
        log("Attempting to type new name...");

        // Select all first (Ctrl+A) to replace any existing text
        sendKeys(["29:1", "30:1", "30:0", "29:0"]); // Ctrl+A
        await sleep(100);

        // Type the new name
        log("Typing: " + newName);
        typeText(newName);
        await sleep(300);

        // Press Enter to confirm
        log("Pressing Enter to confirm...");
        sendEnter();
        await sleep(600);

        // Verify the rename worked
        log("Verifying rename...");
        const newData = getComposerData();
        const updatedChat = newData?.allComposers?.find((c: any) => c.composerId === chatId);
        const updatedName = updatedChat?.name || "Untitled";
        log("Updated name: '" + updatedName + "'");

        if (updatedName === newName) {
          log("SUCCESS! Rename verified with approach " + (i + 1));
          // Close any open panels/menus
          sendEscape();
          return true;
        }

        log("Approach " + (i + 1) + " did not change name");

        // Press Escape to cancel any partial state
        sendEscape();
        await sleep(300);

      } catch (e: any) {
        log("Approach " + (i + 1) + " error: " + e.message);
        sendEscape();
        await sleep(200);
      }
    }

    log("All rename approaches failed");
    log("The chat name remains: '" + currentName + "'");

    // Final cleanup
    sendEscape();

    return false;

  } catch (e: any) {
    log("renameChat error: " + e.message);
    return false;
  }
}

// ============================================================================
// High-Level Functions for Sprint Bot
// ============================================================================

/**
 * Launch a chat for a Jira issue
 *
 * Creates a new chat with the issue key in the title and a skill_run command.
 * After creating and submitting, returns to the previous chat and renames
 * the new chat in the background.
 *
 * @param issueKey Jira issue key (e.g., "AAP-12345")
 * @param options Additional options
 */
export async function launchIssueChat(
  issueKey: string,
  options: {
    summary?: string;
    returnToPrevious?: boolean;
    autoApprove?: boolean;
    renameDelay?: number;  // Delay before renaming (default: 3000ms)
    customPrompt?: string;  // Full custom prompt to use instead of default
  } = {}
): Promise<string | null> {
  const delay = 150;
  const renameDelay = options.renameDelay || 3000;

  // Show output channel so user can see logs
  showOutput();

  log("===== LAUNCH ISSUE CHAT STARTING =====");
  log("Issue key: " + issueKey);
  log("Options: " + JSON.stringify({ ...options, customPrompt: options.customPrompt ? `[${options.customPrompt.length} chars]` : undefined }));

  // Get previous chat ID AND all existing composer IDs before creating new one
  const previousChatId = getActiveChatId();
  const composerDataBefore = getComposerData();
  const existingIds = new Set((composerDataBefore?.allComposers || []).map((c: any) => c.composerId));

  log("Previous chat ID: " + previousChatId);
  log("Existing composer count: " + existingIds.size);

  if (!previousChatId) {
    log("WARNING: No previous chat ID found - won't be able to return");
  }

  // Prepare the message
  // Format: "AAP-12345 short description" on first line (no separators)
  // This format tricks Cursor's auto-namer into keeping the issue key
  const summary = options.summary || "sprint work";

  // Use custom prompt if provided, otherwise use default skill_run
  let message: string;
  if (options.customPrompt) {
    // Custom prompt - prepend issue key for auto-naming
    message = `${issueKey} ${summary}

${options.customPrompt}`;
  } else {
    // Default: use sprint_autopilot skill
    message = `${issueKey} ${summary}

skill_run("sprint_autopilot", '{"issue_key": "${issueKey}", "auto_approve": ${options.autoApprove || false}}')

Please execute this skill to analyze the issue and prepare a work plan.`;
  }

  // Save original clipboard
  const originalClipboard = await vscode.env.clipboard.readText();
  await vscode.env.clipboard.writeText(message);

  try {
    // Create new composer tab (opens prompt)
    log("Creating new composer tab...");
    await vscode.commands.executeCommand("composer.createNewComposerTab");
    await sleep(delay * 2);

    // Accept the prompt with Enter
    log("Sending Enter to accept prompt...");
    sendEnter();
    await sleep(delay * 3);

    // Focus and paste
    log("Focusing composer and pasting...");
    await vscode.commands.executeCommand("composer.focusComposer");
    await sleep(delay);
    sendPaste();
    await sleep(delay * 2);

    // Restore clipboard
    await vscode.env.clipboard.writeText(originalClipboard);

    // Submit the chat
    log("Submitting chat...");
    sendEnter();
    await sleep(delay * 2);

    // Find the NEW chat ID by comparing before/after composer lists
    const composerDataAfter = getComposerData();
    const allComposersAfter = composerDataAfter?.allComposers || [];
    log("Composer count after: " + allComposersAfter.length);

    // Find the composer that wasn't in the original set
    let newChatId: string | null = null;
    for (const composer of allComposersAfter) {
      if (!existingIds.has(composer.composerId)) {
        newChatId = composer.composerId;
        log("Found NEW chat ID: " + newChatId);
        break;
      }
    }

    if (!newChatId) {
      // Fallback: get the most recently created one
      const sorted = [...allComposersAfter].sort((a: any, b: any) => {
        return (b.createdAt || 0) - (a.createdAt || 0);
      });
      newChatId = sorted[0]?.composerId || null;
      log("Fallback: using most recent chat ID: " + newChatId);
    }

    // Return to previous chat if requested
    if (options.returnToPrevious && previousChatId && previousChatId !== newChatId) {
      log("Returning to previous chat: " + previousChatId);
      await sleep(delay * 2);
      await openChatById(previousChatId, { autoSelect: true });
    } else if (previousChatId === newChatId) {
      log("WARNING: New chat ID same as previous - chat detection may have failed");
    }

    // Note: Cursor auto-names chats based on the first message content
    // Since our message starts with the issue key, the chat should be named appropriately
    // Programmatic renaming is NOT supported by Cursor's API (composer.updateTitle doesn't work)
    if (newChatId && newChatId !== previousChatId) {
      log("Chat created successfully. Cursor will auto-name it based on first message.");
      log("Expected name pattern: '" + issueKey + " - Sprint Autopilot...'");
    } else {
      log("No new chat ID found or same as previous");
    }

    return newChatId;
  } catch (e) {
    log("launchIssueChat failed: " + e);
    // Restore clipboard on error
    await vscode.env.clipboard.writeText(originalClipboard);
    return null;
  }
}

/**
 * Open the chat for a specific issue (if it exists)
 *
 * @param issueKey Jira issue key
 */
export async function openIssueChat(issueKey: string): Promise<boolean> {
  // Search for chats that start with the issue key
  return openChatByName(issueKey, { autoSelect: true });
}

// ============================================================================
// Export for D-Bus / WebSocket access
// ============================================================================

/**
 * Handle chat commands from external sources (D-Bus, WebSocket, etc.)
 *
 * @param command The command to execute
 * @param args Command arguments
 */
export async function handleExternalChatCommand(
  command: string,
  args: Record<string, any>
): Promise<{ success: boolean; result?: any; error?: string }> {
  try {
    switch (command) {
      case "createChat":
        const chatId = await createNewChat({
          message: args.message,
          title: args.title,
          returnToPrevious: args.returnToPrevious,
          autoSubmit: args.autoSubmit,
        });
        return { success: true, result: { chatId } };

      case "openChat":
        const opened = args.chatId
          ? await openChatById(args.chatId, { autoSelect: args.autoSelect })
          : await openChatByName(args.chatName || "", { autoSelect: args.autoSelect });
        return { success: opened };

      case "renameChat":
        const renamed = await renameChat(args.chatId, args.newName);
        return { success: renamed };

      case "launchIssueChat":
        const issueChatId = await launchIssueChat(args.issueKey, {
          summary: args.summary,
          returnToPrevious: args.returnToPrevious,
          autoApprove: args.autoApprove,
        });
        return { success: !!issueChatId, result: { chatId: issueChatId } };

      case "getActiveChat":
        const activeId = getActiveChatId();
        const activeName = activeId ? getChatNameById(activeId) : null;
        return { success: true, result: { chatId: activeId, chatName: activeName } };

      case "listChats":
        const chats = getAllChats();
        return { success: true, result: { chats } };

      default:
        return { success: false, error: `Unknown command: ${command}` };
    }
  } catch (e: any) {
    return { success: false, error: e.message };
  }
}
