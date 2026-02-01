/**
 * Webview Resource Loader
 *
 * Utilities for loading CSS and JavaScript files into webviews.
 * Supports both file-based loading and inline content.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { createLogger } from "../logger";

const logger = createLogger("WebviewLoader");

/**
 * Load CSS files from the webview/styles directory
 * @param webview The webview to load styles into
 * @param extensionUri The extension's URI
 * @param styleFiles Array of CSS filenames (without path)
 * @returns Combined CSS content as a string
 */
export function loadStyles(
  extensionUri: vscode.Uri,
  ...styleFiles: string[]
): string {
  const stylesDir = path.join(extensionUri.fsPath, "src", "webview", "styles");
  const cssContent: string[] = [];

  for (const file of styleFiles) {
    const filePath = path.join(stylesDir, file);
    if (fs.existsSync(filePath)) {
      try {
        cssContent.push(fs.readFileSync(filePath, "utf-8"));
      } catch (e) {
        logger.error(`Failed to load CSS file ${file}`, e);
      }
    } else {
      logger.warn(`CSS file not found: ${filePath}`);
    }
  }

  return cssContent.join("\n\n");
}

/**
 * Load JavaScript files from the webview/scripts directory
 * @param extensionUri The extension's URI
 * @param scriptFiles Array of JS filenames (without path)
 * @returns Combined JS content as a string
 */
export function loadScripts(
  extensionUri: vscode.Uri,
  ...scriptFiles: string[]
): string {
  const scriptsDir = path.join(extensionUri.fsPath, "src", "webview", "scripts");
  const jsContent: string[] = [];

  for (const file of scriptFiles) {
    const filePath = path.join(scriptsDir, file);
    if (fs.existsSync(filePath)) {
      try {
        jsContent.push(fs.readFileSync(filePath, "utf-8"));
      } catch (e) {
        logger.error(`Failed to load JS file ${file}`, e);
      }
    } else {
      logger.warn(`JS file not found: ${filePath}`);
    }
  }

  return jsContent.join("\n\n");
}

/**
 * Get a webview URI for a local resource
 * @param webview The webview
 * @param extensionUri The extension's URI
 * @param pathSegments Path segments relative to extension root
 * @returns Webview URI for the resource
 */
export function getWebviewUri(
  webview: vscode.Webview,
  extensionUri: vscode.Uri,
  ...pathSegments: string[]
): vscode.Uri {
  return webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, ...pathSegments));
}

/**
 * Generate a style tag with loaded CSS content
 * @param extensionUri The extension's URI
 * @param styleFiles CSS files to load
 * @returns HTML style tag with CSS content
 */
export function getStyleTag(
  extensionUri: vscode.Uri,
  ...styleFiles: string[]
): string {
  const css = loadStyles(extensionUri, ...styleFiles);
  return `<style>\n${css}\n</style>`;
}

/**
 * Generate a script tag with loaded JS content
 * @param extensionUri The extension's URI
 * @param nonce CSP nonce for the script
 * @param scriptFiles JS files to load
 * @returns HTML script tag with JS content
 */
export function getScriptTag(
  extensionUri: vscode.Uri,
  nonce: string,
  ...scriptFiles: string[]
): string {
  const js = loadScripts(extensionUri, ...scriptFiles);
  return `<script nonce="${nonce}">\n${js}\n</script>`;
}
