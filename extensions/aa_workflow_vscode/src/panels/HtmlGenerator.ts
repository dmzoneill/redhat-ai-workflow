/**
 * HTML Generator for Command Center
 *
 * Generates the webview HTML using modular tab classes and external CSS/JS files.
 * This replaces the massive inline HTML generation in CommandCenterPanel.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { TabManager } from "./TabManager";
import { getNonce } from "../utils";
import { createLogger } from "../logger";

const logger = createLogger("HtmlGenerator");

export interface HtmlGeneratorContext {
  extensionUri: vscode.Uri;
  webview: vscode.Webview;
  currentTab: string;
}

export interface HeaderStats {
  toolCalls: number;
  skillExecutions: number;
  sessions: number;
}

export class HtmlGenerator {
  private tabManager: TabManager;
  private context: HtmlGeneratorContext;
  private cssCache: Map<string, string> = new Map();
  private jsCache: Map<string, string> = new Map();

  constructor(tabManager: TabManager, context: HtmlGeneratorContext) {
    logger.log("HtmlGenerator constructor called");
    this.tabManager = tabManager;
    this.context = context;
    logger.log(`HtmlGenerator initialized with currentTab: ${context.currentTab}`);
  }

  /**
   * Generate the full HTML for the webview
   */
  generateHtml(headerStats: HeaderStats): string {
    logger.log(`generateHtml() called with stats: toolCalls=${headerStats.toolCalls}, skillExecutions=${headerStats.skillExecutions}, sessions=${headerStats.sessions}`);
    const nonce = getNonce();
    logger.log(`generateHtml() - nonce generated: ${nonce.substring(0, 8)}...`);

    const styles = this.getAllStyles();
    logger.log(`generateHtml() - styles loaded: ${styles.length} chars`);

    const scripts = this.getAllScripts();
    logger.log(`generateHtml() - scripts loaded: ${scripts.length} chars`);

    const header = this.getHeaderHtml(headerStats);
    logger.log(`generateHtml() - header generated: ${header.length} chars`);

    const tabs = this.getTabsHtml();
    logger.log(`generateHtml() - tabs generated: ${tabs.length} chars`);

    const tabContents = this.getTabContentsHtml();
    logger.log(`generateHtml() - tabContents generated: ${tabContents.length} chars`);

    const html = `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}' 'unsafe-inline'; img-src ${this.context.webview.cspSource} https: data:; connect-src ws://localhost:* wss://localhost:*;">
      <title>AI Workflow Command Center</title>
      <style>
        ${styles}
      </style>
    </head>
    <body>
      <div class="main-content">
        ${header}
        ${tabs}
        ${tabContents}
      </div>
      <script nonce="${nonce}">
        ${scripts}
      </script>
    </body>
    </html>`;

    logger.log(`generateHtml() - total HTML length: ${html.length} chars`);
    return html;
  }

  /**
   * Get all CSS styles combined
   *
   * All styles are now in a single unified.css file to prevent
   * duplication and ensure consistency across all tabs.
   */
  private getAllStyles(): string {
    const css = this.loadCssFile("unified.css");
    logger.log(`unified.css loaded: ${css.length} chars`);
    return css;
  }

  /**
   * Get all JavaScript combined
   */
  private getAllScripts(): string {
    const scripts: string[] = [];

    // Load base scripts
    const baseJs = this.loadJsFile("base.js");
    logger.log(`base.js loaded: ${baseJs.length} chars`);
    scripts.push(baseJs);

    const tabsJs = this.loadJsFile("tabs.js");
    logger.log(`tabs.js loaded: ${tabsJs.length} chars`);
    scripts.push(tabsJs);

    // Add scripts from tab classes
    scripts.push(this.tabManager.getAllScripts());

    // Add initialization script
    scripts.push(this.getInitScript());

    const totalJs = scripts.filter(Boolean).join("\n\n");
    logger.log(`Total JS: ${totalJs.length} chars`);
    return totalJs;
  }

  /**
   * Load a CSS file from the webview/styles directory
   */
  private loadCssFile(filename: string): string {
    if (this.cssCache.has(filename)) {
      return this.cssCache.get(filename)!;
    }

    try {
      const filePath = path.join(
        this.context.extensionUri.fsPath,
        "src",
        "webview",
        "styles",
        filename
      );
      const exists = fs.existsSync(filePath);
      if (!exists) {
        logger.error(`CSS file not found: ${filePath}`);
      }
      if (exists) {
        const content = fs.readFileSync(filePath, "utf-8");
        this.cssCache.set(filename, content);
        return content;
      }
    } catch (error) {
      logger.error(`Error loading CSS file ${filename}`, error);
    }
    return "";
  }

  /**
   * Load a JavaScript file from the webview/scripts directory
   */
  private loadJsFile(filename: string): string {
    // Disable caching during development - always reload from disk
    // if (this.jsCache.has(filename)) {
    //   return this.jsCache.get(filename)!;
    // }

    try {
      const filePath = path.join(
        this.context.extensionUri.fsPath,
        "src",
        "webview",
        "scripts",
        filename
      );
      if (fs.existsSync(filePath)) {
        const content = fs.readFileSync(filePath, "utf-8");
        this.jsCache.set(filename, content);
        return content;
      }
    } catch (error) {
      logger.error(`Error loading JS file ${filename}`, error);
    }
    return "";
  }

  /**
   * Generate the header HTML
   */
  private getHeaderHtml(stats: HeaderStats): string {
    return `
      <div class="header">
        <div class="agent-avatar">
          <svg class="agent-hat" viewBox="0 0 100 55" xmlns="http://www.w3.org/2000/svg">
            <ellipse cx="50" cy="50" rx="48" ry="8" fill="rgba(0,0,0,0.2)"/>
            <ellipse cx="50" cy="45" rx="48" ry="10" fill="#EE0000"/>
            <path d="M25 45 Q25 20 50 15 Q75 20 75 45" fill="#EE0000"/>
            <rect x="25" y="38" width="50" height="8" fill="#1a1a1a"/>
          </svg>
          <div class="agent-ring"></div>
          <div class="agent-body">🤖</div>
          <div class="agent-status"></div>
        </div>
        <div class="header-info">
          <h1 class="header-title">AI Workflow Command Center</h1>
          <p class="header-subtitle">Your intelligent development assistant • Session active</p>
        </div>
        <div class="header-stats">
          <div class="header-stat">
            <div class="header-stat-value" id="statToolCalls">${this.formatNumber(stats.toolCalls)}</div>
            <div class="header-stat-label">Tool<br/>Calls</div>
          </div>
          <div class="header-stat">
            <div class="header-stat-value" id="statSkills">${stats.skillExecutions}</div>
            <div class="header-stat-label">Skills<br/>Called</div>
          </div>
          <div class="header-stat">
            <div class="header-stat-value" id="statSessions">${stats.sessions}</div>
            <div class="header-stat-label">Sessions<br/>Initiated</div>
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Generate the tabs navigation HTML
   */
  private getTabsHtml(): string {
    return `
      <div class="tabs">
        ${this.tabManager.getTabButtonsHtml()}
      </div>
    `;
  }

  /**
   * Generate all tab contents HTML
   */
  private getTabContentsHtml(): string {
    return this.tabManager.getTabContentsHtml();
  }

  /**
   * Get the initialization script
   */
  private getInitScript(): string {
    return `
      // Initialize tabs
      if (typeof initTabs === 'function') {
        initTabs();
      }

      // Set initial active tab
      const initialTab = '${this.context.currentTab}';
      if (typeof switchTab === 'function') {
        switchTab(initialTab);
      }

      // Handle messages from extension
      window.addEventListener('message', event => {
        const message = event.data;
        const msgType = message.command || message.type;

        switch (msgType) {
          case 'switchTab':
            if (typeof switchTab === 'function') {
              switchTab(message.tab);
            }
            break;
          case 'pong':
            console.log('[CommandCenter] Extension connected');
            extensionConnected = true;
            hideReconnectBanner();
            break;
          case 'updateBadges':
            // Update tab badges
            if (message.badges) {
              Object.entries(message.badges).forEach(([tabId, badge]) => {
                const badgeEl = document.querySelector(\`[data-tab="\${tabId}"] .tab-badge\`);
                if (badgeEl && badge) {
                  badgeEl.textContent = badge.text;
                  badgeEl.className = 'tab-badge ' + (badge.class || '');
                  badgeEl.style.display = '';
                } else if (badgeEl) {
                  badgeEl.style.display = 'none';
                }
              });
            }
            break;
          case 'tabContentUpdate':
            // Update tab content without full page reload
            // Note: We can't use new Function() due to CSP, so we use event delegation instead
            if (message.tabId && message.content) {
              const tabContent = document.getElementById(message.tabId);
              if (tabContent) {
                tabContent.innerHTML = message.content;
                // Event delegation handles clicks - no need to re-run scripts
              } else {
                console.warn('[TabContentUpdate] Tab content element not found:', message.tabId);
              }
            }
            break;
          case 'inferenceTestResult':
            // Handle inference test result
            if (message.data) {
              const resultArea = document.getElementById('inferenceResultArea');
              if (resultArea) {
                resultArea.style.display = '';
                resultArea.innerHTML = formatInferenceResult(message.data);
              }
              // Update button state
              const runBtn = document.querySelector('[data-action="runInferenceTest"]');
              if (runBtn) {
                runBtn.disabled = false;
                runBtn.innerHTML = '🔍 Run Inference';
              }
            }
            break;
          case 'inferenceTestStarted':
            // Update button to show running state
            const runBtnStart = document.querySelector('[data-action="runInferenceTest"]');
            if (runBtnStart) {
              runBtnStart.disabled = true;
              runBtnStart.innerHTML = '⏳ Running...';
            }
            break;
        }
      });

      // Send ping to confirm connection
      vscode.postMessage({ command: 'ping' });
    `;
  }

  /**
   * Format a number for display
   */
  private formatNumber(num: number): string {
    if (num >= 1000000) {
      return (num / 1000000).toFixed(1) + "M";
    }
    if (num >= 1000) {
      return (num / 1000).toFixed(1) + "K";
    }
    return num.toString();
  }

  /**
   * Clear the CSS and JS caches
   */
  clearCache(): void {
    this.cssCache.clear();
    this.jsCache.clear();
  }
}
