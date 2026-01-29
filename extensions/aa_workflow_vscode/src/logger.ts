/**
 * Centralized Logger for AI Workflow Extension
 *
 * All extension logs go to the "AI Workflow" output channel for easy debugging.
 *
 * Usage:
 *   import { log, logError, showLog } from "./logger";
 *   log("Something happened");
 *   logError("Something failed", error);
 */

import * as vscode from "vscode";

let outputChannel: vscode.OutputChannel | null = null;

/**
 * Get or create the output channel
 */
function getChannel(): vscode.OutputChannel {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel("AI Workflow");
  }
  return outputChannel;
}

/**
 * Log a message with timestamp and optional source tag
 * @param message The message to log
 * @param source Optional source identifier (e.g., "CommandCenter", "Sprint")
 */
export function log(message: string, source?: string): void {
  const timestamp = new Date().toISOString().substring(11, 23);
  const prefix = source ? `[${source}]` : "";
  const line = `[${timestamp}]${prefix} ${message}`;

  // Also log to console for Developer Tools
  console.log(`[AIWorkflow]${prefix}`, message);

  getChannel().appendLine(line);
}

/**
 * Log an error with stack trace
 * @param message Error description
 * @param error The error object
 * @param source Optional source identifier
 */
export function logError(message: string, error?: any, source?: string): void {
  const timestamp = new Date().toISOString().substring(11, 23);
  const prefix = source ? `[${source}]` : "";
  const errorMsg = error?.message || error || "Unknown error";
  const stack = error?.stack ? `\n${error.stack}` : "";
  const line = `[${timestamp}]${prefix} ERROR: ${message}: ${errorMsg}${stack}`;

  console.error(`[AIWorkflow]${prefix}`, message, error);

  getChannel().appendLine(line);
}

/**
 * Log a warning
 * @param message Warning message
 * @param source Optional source identifier
 */
export function logWarn(message: string, source?: string): void {
  const timestamp = new Date().toISOString().substring(11, 23);
  const prefix = source ? `[${source}]` : "";
  const line = `[${timestamp}]${prefix} WARN: ${message}`;

  console.warn(`[AIWorkflow]${prefix}`, message);

  getChannel().appendLine(line);
}

/**
 * Show the output channel (brings it to focus)
 */
export function showLog(): void {
  getChannel().show(true);  // true = preserve focus
}

/**
 * Clear the output channel
 */
export function clearLog(): void {
  getChannel().clear();
}

/**
 * Create a scoped logger for a specific module
 * @param source The module name (e.g., "CommandCenter")
 */
export function createLogger(source: string) {
  return {
    log: (message: string) => log(message, source),
    info: (message: string) => log(message, source),  // Alias for log
    debug: (message: string) => log(message, source), // Alias for log (could add DEBUG prefix if needed)
    error: (message: string, error?: any) => logError(message, error, source),
    warn: (message: string) => logWarn(message, source),
    show: showLog,
  };
}

/**
 * Dispose the output channel (call on extension deactivate)
 */
export function disposeLogger(): void {
  if (outputChannel) {
    outputChannel.dispose();
    outputChannel = null;
  }
}
