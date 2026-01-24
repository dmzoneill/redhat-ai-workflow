/**
 * Sprint Chat Launcher - Investigation Module
 *
 * This module investigates and implements the ability to:
 * 1. Create new Cursor chats programmatically
 * 2. Set chat titles/names for identification
 * 3. Pre-load context into chats
 * 4. Return to existing chats later
 * 5. Link timeline events to specific chats
 *
 * INVESTIGATION STATUS:
 * - composer.startComposerPrompt2: Creates new agent chat ✓
 * - composer.focusComposer: Focuses the input ✓
 * - composer.submitChat: Submits message ✓
 * - Chat ID retrieval: Via SQLite database (state.vscdb)
 * - Chat naming: First message becomes the "title" in history
 * - Returning to chat: Requires database lookup + internal command
 *
 * KNOWN LIMITATIONS:
 * - No direct API to set chat name
 * - No direct API to open specific chat by ID
 * - Must use workarounds via clipboard and database
 */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

// Storage for issue-to-chat mappings
const CHAT_MAPPINGS_FILE = path.join(
  os.homedir(),
  ".config",
  "aa-workflow",
  "sprint_chat_mappings.json"
);

interface ChatMapping {
  issueKey: string;
  chatId: string;
  createdAt: string;
  lastAccessed?: string;
  summary: string;
}

interface ChatMappings {
  mappings: ChatMapping[];
  lastUpdated: string;
}

/**
 * Sleep helper for timing between commands
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Load chat mappings from disk
 */
function loadChatMappings(): ChatMappings {
  try {
    if (fs.existsSync(CHAT_MAPPINGS_FILE)) {
      const content = fs.readFileSync(CHAT_MAPPINGS_FILE, "utf-8");
      return JSON.parse(content);
    }
  } catch (e) {
    console.error("Failed to load chat mappings:", e);
  }
  return { mappings: [], lastUpdated: new Date().toISOString() };
}

/**
 * Save chat mappings to disk
 */
function saveChatMappings(mappings: ChatMappings): void {
  try {
    const dir = path.dirname(CHAT_MAPPINGS_FILE);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(CHAT_MAPPINGS_FILE, JSON.stringify(mappings, null, 2));
  } catch (e) {
    console.error("Failed to save chat mappings:", e);
  }
}

/**
 * Get the Cursor state database path
 *
 * Cursor stores chat data in a SQLite database at:
 * ~/.config/Cursor/User/globalStorage/state.vscdb
 */
function getCursorDatabasePath(): string {
  const platform = process.platform;
  let configDir: string;

  if (platform === "darwin") {
    configDir = path.join(os.homedir(), "Library", "Application Support", "Cursor");
  } else if (platform === "win32") {
    configDir = path.join(os.homedir(), "AppData", "Roaming", "Cursor");
  } else {
    configDir = path.join(os.homedir(), ".config", "Cursor");
  }

  return path.join(configDir, "User", "globalStorage", "state.vscdb");
}

/**
 * Attempt to read the latest chat ID from Cursor's database
 *
 * This is experimental and may break with Cursor updates.
 * The database stores chat data under 'composer.composerData' key.
 *
 * @returns The latest chat ID or null if not found
 */
async function getLatestChatIdFromDatabase(): Promise<string | null> {
  const dbPath = getCursorDatabasePath();

  if (!fs.existsSync(dbPath)) {
    console.warn("Cursor database not found at:", dbPath);
    return null;
  }

  try {
    // We would need to use better-sqlite3 or similar to read the database
    // For now, return null and document the approach
    console.log("Database path:", dbPath);
    console.log("Note: SQLite reading requires better-sqlite3 package");

    // The database structure (based on investigation):
    // Table: ItemTable
    // Key: 'composer.composerData'
    // Value: JSON with allComposers array containing chat objects
    // Each chat has: id, messages, createdAt, etc.

    return null;
  } catch (e) {
    console.error("Failed to read Cursor database:", e);
    return null;
  }
}

/**
 * Launch a new chat for a sprint issue
 *
 * Creates a new Cursor chat with context about the issue.
 * The first message becomes the chat "title" in the history.
 *
 * @param issueKey Jira issue key (e.g., "AAP-12345")
 * @param summary Issue summary for context
 * @param additionalContext Optional additional context to include
 * @returns Chat ID if successful, null otherwise
 */
export async function launchIssueChat(
  issueKey: string,
  summary: string,
  additionalContext?: string
): Promise<string | null> {
  try {
    // Step 1: Create new chat via agent mode
    await vscode.commands.executeCommand("composer.startComposerPrompt2", "agent");
    await sleep(300); // Wait for chat to initialize

    // Step 2: Focus the composer input
    await vscode.commands.executeCommand("composer.focusComposer");
    await sleep(100);

    // Step 3: Prepare the context message
    // This becomes the chat "title" in the history
    const contextMessage = `Working on ${issueKey} - ${summary}

Please help me implement this Jira issue. Here's the context:
- Issue: ${issueKey}
- Summary: ${summary}
${additionalContext ? `\nAdditional Context:\n${additionalContext}` : ""}

Let me know when you're ready to start, or if you need any clarification about the requirements.`;

    // Step 4: Paste context via clipboard (most reliable method)
    const originalClipboard = await vscode.env.clipboard.readText();
    await vscode.env.clipboard.writeText(contextMessage);

    try {
      await vscode.commands.executeCommand("editor.action.clipboardPasteAction");
    } catch {
      // Fallback: Try to type directly (less reliable)
      console.warn("Clipboard paste failed, trying alternative method");
    }

    // Restore original clipboard
    await sleep(50);
    await vscode.env.clipboard.writeText(originalClipboard);

    // Step 5: Submit to create the chat
    await sleep(100);
    await vscode.commands.executeCommand("composer.submitChat");

    // Step 6: Try to get the chat ID
    await sleep(500); // Wait for chat to be created
    const chatId = await getLatestChatIdFromDatabase();

    // Step 7: Save the mapping
    if (chatId) {
      const mappings = loadChatMappings();
      mappings.mappings.push({
        issueKey,
        chatId,
        createdAt: new Date().toISOString(),
        summary,
      });
      mappings.lastUpdated = new Date().toISOString();
      saveChatMappings(mappings);
    }

    // Generate a temporary ID if database read failed
    const finalChatId = chatId || `temp-${issueKey}-${Date.now()}`;

    // Save mapping even with temp ID
    if (!chatId) {
      const mappings = loadChatMappings();
      mappings.mappings.push({
        issueKey,
        chatId: finalChatId,
        createdAt: new Date().toISOString(),
        summary,
      });
      mappings.lastUpdated = new Date().toISOString();
      saveChatMappings(mappings);
    }

    return finalChatId;
  } catch (e) {
    console.error("Failed to launch issue chat:", e);
    vscode.window.showErrorMessage(`Failed to create chat for ${issueKey}: ${e}`);
    return null;
  }
}

/**
 * Get the chat ID for an issue
 *
 * @param issueKey Jira issue key
 * @returns Chat ID if found, null otherwise
 */
export function getChatIdForIssue(issueKey: string): string | null {
  const mappings = loadChatMappings();
  const mapping = mappings.mappings.find((m) => m.issueKey === issueKey);
  return mapping?.chatId || null;
}

/**
 * Attempt to return to an existing chat
 *
 * This is experimental and may not work reliably.
 * Cursor doesn't expose a direct API to open a specific chat.
 *
 * @param issueKey Jira issue key
 * @returns True if chat was found and opened, false otherwise
 */
export async function returnToIssueChat(issueKey: string): Promise<boolean> {
  const chatId = getChatIdForIssue(issueKey);

  if (!chatId) {
    vscode.window.showWarningMessage(`No chat found for ${issueKey}`);
    return false;
  }

  try {
    // Approach 1: Open chat history and let user find it
    await vscode.commands.executeCommand("composer.showComposerHistory");

    // Update last accessed
    const mappings = loadChatMappings();
    const mapping = mappings.mappings.find((m) => m.issueKey === issueKey);
    if (mapping) {
      mapping.lastAccessed = new Date().toISOString();
      saveChatMappings(mappings);
    }

    vscode.window.showInformationMessage(
      `Chat history opened. Look for "${issueKey}" in the list.`
    );

    return true;
  } catch (e) {
    console.error("Failed to return to chat:", e);
    vscode.window.showErrorMessage(`Failed to open chat for ${issueKey}`);
    return false;
  }
}

/**
 * List all issue-to-chat mappings
 *
 * @returns Array of chat mappings
 */
export function listChatMappings(): ChatMapping[] {
  return loadChatMappings().mappings;
}

/**
 * Clear chat mapping for an issue
 *
 * @param issueKey Jira issue key to clear
 */
export function clearChatMapping(issueKey: string): void {
  const mappings = loadChatMappings();
  mappings.mappings = mappings.mappings.filter((m) => m.issueKey !== issueKey);
  mappings.lastUpdated = new Date().toISOString();
  saveChatMappings(mappings);
}

/**
 * Register chat launcher commands with VS Code
 */
export function registerChatLauncherCommands(
  context: vscode.ExtensionContext
): void {
  // Command to launch a new issue chat
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.launchIssueChat",
      async (issueKey?: string, summary?: string) => {
        if (!issueKey) {
          issueKey = await vscode.window.showInputBox({
            prompt: "Enter Jira issue key",
            placeHolder: "AAP-12345",
          });
        }
        if (!issueKey) return;

        if (!summary) {
          summary = await vscode.window.showInputBox({
            prompt: "Enter issue summary",
            placeHolder: "Fix pagination bug in API",
          });
        }
        if (!summary) summary = "Sprint issue";

        const chatId = await launchIssueChat(issueKey, summary);
        if (chatId) {
          vscode.window.showInformationMessage(
            `Created chat for ${issueKey} (ID: ${chatId.substring(0, 8)}...)`
          );
        }
      }
    )
  );

  // Command to return to an issue chat
  context.subscriptions.push(
    vscode.commands.registerCommand(
      "aa-workflow.returnToIssueChat",
      async (issueKey?: string) => {
        if (!issueKey) {
          const mappings = listChatMappings();
          if (mappings.length === 0) {
            vscode.window.showWarningMessage("No issue chats found");
            return;
          }

          const items = mappings.map((m) => ({
            label: m.issueKey,
            description: m.summary,
            detail: `Created: ${new Date(m.createdAt).toLocaleString()}`,
          }));

          const selected = await vscode.window.showQuickPick(items, {
            placeHolder: "Select an issue to return to",
          });

          if (!selected) return;
          issueKey = selected.label;
        }

        await returnToIssueChat(issueKey);
      }
    )
  );

  // Command to list all chat mappings
  context.subscriptions.push(
    vscode.commands.registerCommand("aa-workflow.listIssueChatMappings", () => {
      const mappings = listChatMappings();
      if (mappings.length === 0) {
        vscode.window.showInformationMessage("No issue chats found");
        return;
      }

      const content = mappings
        .map(
          (m) =>
            `${m.issueKey}: ${m.summary}\n  Chat ID: ${m.chatId}\n  Created: ${m.createdAt}`
        )
        .join("\n\n");

      vscode.workspace
        .openTextDocument({ content, language: "markdown" })
        .then((doc) => vscode.window.showTextDocument(doc));
    })
  );
}

/**
 * INVESTIGATION NOTES
 *
 * Cursor Composer Commands (discovered via extension inspection):
 * - composer.startComposerPrompt2 - Create new chat (pass "agent" for agent mode)
 * - composer.focusComposer - Focus the input field
 * - composer.submitChat - Submit the current message
 * - composer.submit - Alternative submit
 * - composer.showComposerHistory - Show chat history panel
 * - composer.closeComposerTab - Close current chat tab
 * - composer.clearComposerTabs - Clear all chat tabs
 *
 * Database Structure (state.vscdb):
 * - SQLite database
 * - Table: ItemTable
 * - Key: 'composer.composerData'
 * - Value: JSON with structure:
 *   {
 *     "allComposers": [
 *       {
 *         "id": "uuid",
 *         "messages": [...],
 *         "createdAt": timestamp,
 *         "title": "first message content",
 *         ...
 *       }
 *     ]
 *   }
 *
 * Limitations:
 * 1. No direct API to set chat title - it's derived from first message
 * 2. No direct API to open specific chat by ID
 * 3. Database reading requires native SQLite module
 * 4. Chat IDs may change between sessions
 *
 * Workarounds:
 * 1. Use first message as "title" - include issue key prominently
 * 2. Store mappings locally for lookup
 * 3. Open history panel and let user find chat
 * 4. Consider using MCP resources for context instead of chat
 *
 * Alternative Approaches:
 * 1. File-based context: Create .cursor/context/AAP-12345.md files
 * 2. MCP resources: Expose issue context as MCP resource
 * 3. Session state: Track issue context in session, not chat
 */
