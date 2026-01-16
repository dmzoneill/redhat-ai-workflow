/**
 * Workspace-relative path utilities.
 *
 * Provides functions to get paths relative to the current workspace,
 * with fallbacks for when no workspace is open.
 */

import * as vscode from "vscode";
import * as path from "path";
import * as os from "os";

// Default fallback project path (used when no workspace is open)
const FALLBACK_PROJECT_PATH = path.join(
  os.homedir(),
  "src",
  "redhat-ai-workflow"
);

/**
 * Get the root path of the current workspace.
 * Falls back to the default project path if no workspace is open.
 */
export function getWorkspaceRoot(): string {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (workspaceFolders && workspaceFolders.length > 0) {
    return workspaceFolders[0].uri.fsPath;
  }
  return FALLBACK_PROJECT_PATH;
}

/**
 * Get the skills directory path.
 * Skills are stored in the `skills/` folder in the workspace root.
 */
export function getSkillsDir(): string {
  return path.join(getWorkspaceRoot(), "skills");
}

/**
 * Get the Cursor commands directory path.
 * Cursor stores custom slash commands in `.cursor/commands/` in the workspace root.
 */
export function getCommandsDir(): string {
  return path.join(getWorkspaceRoot(), ".cursor", "commands");
}

/**
 * Get the config.json path.
 * Configuration is stored in `config.json` in the workspace root.
 */
export function getConfigPath(): string {
  return path.join(getWorkspaceRoot(), "config.json");
}

/**
 * Get the memory directory path.
 * Memory files are stored in `memory/` in the workspace root.
 */
export function getMemoryDir(): string {
  return path.join(getWorkspaceRoot(), "memory");
}

/**
 * Get the personas directory path.
 * Persona definitions are stored in `personas/` in the workspace root.
 */
export function getPersonasDir(): string {
  return path.join(getWorkspaceRoot(), "personas");
}
