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

    // Get D3.js URI from local resources
    const d3Uri = this.context.webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, 'resources', 'js', 'd3.v7.min.js')
    );

    // morphdom for efficient DOM patching (replaces innerHTML in tabContentUpdate)
    const morphdomUri = this.context.webview.asWebviewUri(
      vscode.Uri.joinPath(this.context.extensionUri, 'resources', 'js', 'morphdom.min.js')
    );

    const html = `<!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline' https://fonts.cdnfonts.com; font-src https://fonts.cdnfonts.com; script-src 'nonce-${nonce}' 'unsafe-inline' ${this.context.webview.cspSource}; img-src ${this.context.webview.cspSource} https: data:; connect-src ws://localhost:* wss://localhost:* http://127.0.0.1:*;">
      <link rel="stylesheet" href="https://fonts.cdnfonts.com/css/red-hat-display">
      <link rel="stylesheet" href="https://fonts.cdnfonts.com/css/red-hat-text">
      <link rel="stylesheet" href="https://fonts.cdnfonts.com/css/red-hat-mono">
      <title>AI Command Center</title>
      <style>
        ${styles}
      </style>
      <!-- D3.js for visualizations (mind map) - loaded from local resources -->
      <script nonce="${nonce}" src="${d3Uri}"></script>
      <!-- morphdom for efficient DOM patching -->
      <script nonce="${nonce}" src="${morphdomUri}"></script>
    </head>
    <body>
      <script nonce="${nonce}">fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:sentinel-A',message:'Sentinel A: script at body start',data:{ts:Date.now()},timestamp:Date.now(),hypothesisId:'H7'})}).catch(function(){});</script>
      <div class="main-content">
        ${header}
        ${tabs}
        ${tabContents}
      </div>
      <script nonce="${nonce}">
        // Bridge webview console.log to extension Output panel
        (function() {
          const origLog = console.log;
          const origWarn = console.warn;
          const origError = console.error;
          function relay(level, args) {
            try {
              const msg = Array.from(args).map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ');
              if (msg.startsWith('[MindMap]') || msg.startsWith('Mind map')) {
                vscode.postMessage({ command: 'webviewLog', level: level, message: msg });
              }
            } catch(e) {}
          }
          console.log = function() { relay('log', arguments); origLog.apply(console, arguments); };
          console.warn = function() { relay('warn', arguments); origWarn.apply(console, arguments); };
          console.error = function() { relay('error', arguments); origError.apply(console, arguments); };
        })();
        ${scripts}
      </script>
      <script nonce="${nonce}">fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:sentinel-B',message:'Sentinel B: script after main block',data:{ts:Date.now()},timestamp:Date.now(),hypothesisId:'H7'})}).catch(function(){});</script>
    </body>
    </html>`;

    logger.log(`generateHtml() - total HTML length: ${html.length} chars`);

    // #region agent log
    // Dump combined scripts to a file for offline syntax checking
    try {
      const fs = require('fs');
      const dumpPath = '/tmp/webview-scripts-df259b.js';
      fs.writeFileSync(dumpPath, scripts, 'utf8');
      fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:scriptDump',message:'Scripts dumped to file',data:{path:dumpPath,len:scripts.length},timestamp:Date.now(),hypothesisId:'H7'})}).catch(()=>{});
    } catch(e) {}
    // #endregion

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
    const d3Css = this.loadCssFile("d3-charts.css");
    logger.log(`d3-charts.css loaded: ${d3Css.length} chars`);
    return css + "\n" + d3Css;
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
        <div class="header-logo">
          <svg viewBox="0 0 613 145" xmlns="http://www.w3.org/2000/svg" class="rh-logo" width="120" height="28"><defs><style>.rh-r{fill:#e00}.rh-w{fill:#fff}</style></defs><path class="rh-r" d="M127.47,83.49c12.51,0,30.61-2.58,30.61-17.46a14,14,0,0,0-.31-3.42l-7.45-32.36c-1.72-7.12-3.23-10.35-15.73-16.6C124.89,8.69,103.76.5,97.51.5,91.69.5,90,8,83.06,8c-6.68,0-11.64-5.6-17.89-5.6-6,0-9.91,4.09-12.93,12.5,0,0-8.41,23.72-9.49,27.16A6.43,6.43,0,0,0,42.53,44c0,9.22,36.3,39.45,84.94,39.45M160,72.07c1.73,8.19,1.73,9.05,1.73,10.13,0,14-15.74,21.77-36.43,21.77C78.54,104,37.58,76.6,37.58,58.49a18.45,18.45,0,0,1,1.51-7.33C22.27,52,.5,55,.5,74.22c0,31.48,74.59,70.28,133.65,70.28,45.28,0,56.7-20.48,56.7-36.65,0-12.72-11-27.16-30.83-35.78"/><path d="M160,72.07c1.73,8.19,1.73,9.05,1.73,10.13,0,14-15.74,21.77-36.43,21.77C78.54,104,37.58,76.6,37.58,58.49a18.45,18.45,0,0,1,1.51-7.33l3.66-9.06A6.43,6.43,0,0,0,42.53,44c0,9.22,36.3,39.45,84.94,39.45,12.51,0,30.61-2.58,30.61-17.46a14,14,0,0,0-.31-3.42Z"/><path class="rh-w" d="M579.74,92.8c0,11.89,7.15,17.67,20.19,17.67a52.11,52.11,0,0,0,11.89-1.68V95a24.84,24.84,0,0,1-7.68,1.16c-5.37,0-7.36-1.68-7.36-6.73V68.3h15.56V54.1H596.78v-18l-17,3.68V54.1H568.49V68.3h11.25Zm-53,.32c0-3.68,3.69-5.47,9.26-5.47a43.12,43.12,0,0,1,10.1,1.26v7.15a21.51,21.51,0,0,1-10.63,2.63c-5.46,0-8.73-2.1-8.73-5.57m5.2,17.56c6,0,10.84-1.26,15.36-4.31v3.37h16.82V74.08c0-13.56-9.14-21-24.39-21-8.52,0-16.94,2-26,6.1l6.1,12.52c6.52-2.74,12-4.42,16.83-4.42,7,0,10.62,2.73,10.62,8.31v2.73a49.53,49.53,0,0,0-12.62-1.58c-14.31,0-22.93,6-22.93,16.73,0,9.78,7.78,17.24,20.19,17.24m-92.44-.94h18.09V80.92h30.29v28.82H506V36.12H487.93V64.41H457.64V36.12H439.55ZM370.62,81.87c0-8,6.31-14.1,14.62-14.1A17.22,17.22,0,0,1,397,72.09V91.54A16.36,16.36,0,0,1,385.24,96c-8.2,0-14.62-6.1-14.62-14.09m26.61,27.87h16.83V32.44l-17,3.68V57.05a28.3,28.3,0,0,0-14.2-3.68c-16.19,0-28.92,12.51-28.92,28.5a28.25,28.25,0,0,0,28.4,28.6,25.12,25.12,0,0,0,14.93-4.83ZM320,67c5.36,0,9.88,3.47,11.67,8.83H308.47C310.15,70.3,314.36,67,320,67M291.33,82c0,16.2,13.25,28.82,30.28,28.82,9.36,0,16.2-2.53,23.25-8.42l-11.26-10c-2.63,2.74-6.52,4.21-11.14,4.21a14.39,14.39,0,0,1-13.68-8.83h39.65V83.55c0-17.67-11.88-30.39-28.08-30.39a28.57,28.57,0,0,0-29,28.81M262,51.58c6,0,9.36,3.78,9.36,8.31S268,68.2,262,68.2H244.11V51.58Zm-36,58.16h18.09V82.92h13.77l13.89,26.82H292l-16.2-29.45a22.27,22.27,0,0,0,13.88-20.72c0-13.25-10.41-23.45-26-23.45H226Z"/></svg>
        </div>
        <div class="header-info">
          <h1 class="header-title">AI Command Center</h1>
          <p class="header-subtitle">Intelligent development workflow assistant</p>
        </div>
        <div class="activity-log" id="activityLog">
          <div class="activity-line" data-slot="0"></div>
          <div class="activity-line" data-slot="1"></div>
          <div class="activity-line" data-slot="2"></div>
          <div class="activity-line" data-slot="3"></div>
        </div>
        <div class="header-stats">
          <div class="header-stat">
            <div class="header-stat-value" id="statToolCalls">${this.formatNumber(stats.toolCalls)}</div>
            <div class="header-stat-label">Tools</div>
          </div>
          <div class="header-stat">
            <div class="header-stat-value" id="statSkills">${stats.skillExecutions}</div>
            <div class="header-stat-label">Skills</div>
          </div>
          <div class="header-stat">
            <div class="header-stat-value" id="statSessions">${stats.sessions}</div>
            <div class="header-stat-label">Sessions</div>
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
      // #region agent log
      fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:initScriptStart',message:'Init script STARTING',data:{initTabsDefined:typeof initTabs==='function',switchTabDefined:typeof switchTab==='function',vscodeApiDefined:typeof vscode!=='undefined',bodyChildCount:document.body?document.body.childElementCount:0},timestamp:Date.now(),hypothesisId:'H6'})}).catch(function(){});
      // #endregion

      // Initialize tabs
      if (typeof initTabs === 'function') {
        initTabs();
      }

      // Set initial active tab
      const initialTab = '${this.context.currentTab}';
      // #region agent log
      (function() {
        var tabContents = document.querySelectorAll('.tab-content');
        var tabBtns = document.querySelectorAll('.tab');
        var ids = [];
        tabContents.forEach(function(tc) { ids.push(tc.id); });
        fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:initScript',message:'Before switchTab',data:{initialTab:initialTab,tabContentCount:tabContents.length,tabBtnCount:tabBtns.length,tabContentIds:ids,switchTabDefined:typeof switchTab === 'function',initTabsDefined:typeof initTabs === 'function'},timestamp:Date.now(),hypothesisId:'H2'})}).catch(function(){});
      })();
      // #endregion
      if (typeof switchTab === 'function') {
        try {
          switchTab(initialTab);
          // #region agent log
          (function() {
            var activeContents = document.querySelectorAll('.tab-content.active');
            var allContents = document.querySelectorAll('.tab-content');
            var activeIds = []; allContents.forEach(function(c) { if (c.classList.contains('active')) activeIds.push(c.id); });
            var firstContentStyle = allContents.length > 0 ? window.getComputedStyle(allContents[0]).display : 'N/A';
            var activeContentStyle = activeContents.length > 0 ? window.getComputedStyle(activeContents[0]).display : 'N/A';
            var activeContentLen = activeContents.length > 0 ? activeContents[0].innerHTML.length : 0;
            fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:afterSwitchTab',message:'After switchTab',data:{initialTab:initialTab,activeContentCount:activeContents.length,totalContentCount:allContents.length,activeIds:activeIds,firstContentDisplay:firstContentStyle,activeContentDisplay:activeContentStyle,activeContentLen:activeContentLen},timestamp:Date.now(),hypothesisId:'H2'})}).catch(function(){});
          })();
          // #endregion
        } catch(e) {
          // #region agent log
          fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:switchTabError',message:'switchTab CRASHED',data:{error:e.message,stack:e.stack},timestamp:Date.now(),hypothesisId:'H2'})}).catch(function(){});
          // #endregion
        }
      } else {
        // #region agent log
        fetch('http://127.0.0.1:7244/ingest/b464bf17-3382-4be8-aea7-602ee73036e8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'df259b'},body:JSON.stringify({sessionId:'df259b',location:'HtmlGenerator.ts:noSwitchTab',message:'switchTab NOT defined',data:{},timestamp:Date.now(),hypothesisId:'H2'})}).catch(function(){});
        // #endregion
      }

      // Track user interaction on tab content areas.
      // When the user scrolls, focuses an input, types, or clicks within a tab,
      // notify the extension so it can suppress disruptive full re-renders.
      (function() {
        var _interactionTimer = null;
        function notifyInteraction(tabId) {
          if (_interactionTimer) return;
          _interactionTimer = setTimeout(function() { _interactionTimer = null; }, 500);
          vscode.postMessage({ command: 'userInteracting', tabId: tabId });
        }
        function getTabId(el) {
          var tc = el.closest ? el.closest('.tab-content') : null;
          return tc ? tc.id : null;
        }
        document.addEventListener('focusin', function(e) {
          var tid = getTabId(e.target);
          if (tid) notifyInteraction(tid);
        }, true);
        document.addEventListener('input', function(e) {
          var tid = getTabId(e.target);
          if (tid) notifyInteraction(tid);
        }, true);
        document.addEventListener('scroll', function(e) {
          var el = e.target;
          var tid = (el === document || el === document.documentElement) ? null : getTabId(el);
          if (tid) notifyInteraction(tid);
        }, true);
        document.addEventListener('mousedown', function(e) {
          var tid = getTabId(e.target);
          if (tid) notifyInteraction(tid);
        }, true);
      })();

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
            // Update tab badges - only update when badge has data, never hide existing badges
            if (message.badges) {
              Object.entries(message.badges).forEach(([tabId, badge]) => {
                const badgeEl = document.querySelector(\`[data-tab="\${tabId}"] .tab-badge\`);
                if (badgeEl && badge) {
                  badgeEl.textContent = badge.text;
                  badgeEl.className = 'tab-badge ' + (badge.class || '');
                  badgeEl.style.display = '';
                }
                // Don't hide badges when badge is null - the static HTML
                // may already have correct badges from the initial render
              });
            }
            break;
          case 'tabContentUpdate':
            if (message.tabId && message.content) {
              const tabContent = document.getElementById(message.tabId);
              if (tabContent) {
                // Capture focus state before morphdom (morphdom preserves most state
                // but we need to handle text cursor position explicitly)
                var focusedEl = document.activeElement;
                var focusedId = null;
                var focusedSelStart = null;
                var focusedSelEnd = null;
                if (focusedEl && tabContent.contains(focusedEl) && focusedEl.id) {
                  focusedId = focusedEl.id;
                  if (typeof focusedEl.selectionStart === 'number') {
                    focusedSelStart = focusedEl.selectionStart;
                    focusedSelEnd = focusedEl.selectionEnd;
                  }
                }

                // Build a temporary wrapper matching tabContent's structure
                var tempWrapper = document.createElement('div');
                tempWrapper.innerHTML = message.content;

                // Use morphdom to patch only the changed DOM nodes.
                // Unchanged elements keep their scroll positions, form values,
                // event listeners, and D3 visualizations intact.
                if (typeof morphdom === 'function') {
                  morphdom(tabContent, tempWrapper, {
                    childrenOnly: true,
                    onBeforeElUpdated: function(fromEl, toEl) {
                      // Never touch the actively focused input/textarea/select -
                      // the user may be typing or selecting.
                      if (fromEl === document.activeElement) {
                        var tag = fromEl.tagName;
                        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
                          return false;
                        }
                      }
                      // Preserve scroll position on scrollable containers
                      if (fromEl.scrollTop > 0) {
                        toEl.setAttribute('data-morph-scrollTop', fromEl.scrollTop);
                      }
                      if (fromEl.scrollLeft > 0) {
                        toEl.setAttribute('data-morph-scrollLeft', fromEl.scrollLeft);
                      }
                      return true;
                    },
                    onElUpdated: function(el) {
                      // Restore scroll positions saved during onBeforeElUpdated
                      var st = el.getAttribute('data-morph-scrollTop');
                      var sl = el.getAttribute('data-morph-scrollLeft');
                      if (st) { el.scrollTop = parseInt(st, 10); el.removeAttribute('data-morph-scrollTop'); }
                      if (sl) { el.scrollLeft = parseInt(sl, 10); el.removeAttribute('data-morph-scrollLeft'); }
                    }
                  });
                } else {
                  // Fallback if morphdom failed to load
                  tabContent.innerHTML = message.content;
                }

                // Restore text cursor position if focus was preserved
                if (focusedId) {
                  var toFocus = document.getElementById(focusedId);
                  if (toFocus && toFocus === document.activeElement && focusedSelStart !== null) {
                    try { toFocus.setSelectionRange(focusedSelStart, focusedSelEnd); } catch(e) {}
                  } else if (toFocus && toFocus !== document.activeElement) {
                    toFocus.focus();
                    if (focusedSelStart !== null && typeof toFocus.setSelectionRange === 'function') {
                      try { toFocus.setSelectionRange(focusedSelStart, focusedSelEnd); } catch(e) {}
                    }
                  }
                }

                // Re-initialize D3 visualizations only when their data elements changed
                requestAnimationFrame(function() {
                  if (message.tabId === 'skills' && document.getElementById('mindmapDataScript') && typeof initMindMap === 'function') {
                    initMindMap();
                  }
                  if (message.tabId === 'performance') {
                    if (document.getElementById('perfMindmapData') && typeof window._initPerfMindmap === 'function') {
                      setTimeout(function() { window._initPerfMindmap(); }, 200);
                    }
                    if (document.getElementById('perfHelpData') && typeof window._initPerfHelp === 'function') {
                      setTimeout(function() { window._initPerfHelp(); }, 250);
                    }
                  }
                });
              } else {
                console.warn('[TabContentUpdate] Tab content element not found:', message.tabId);
              }
            }
            break;
          case 'stepStatusUpdate':
            // Incremental step status update - avoids full DOM replacement.
            // Updates individual step nodes by changing CSS class and icon.
            if (message.steps && Array.isArray(message.steps)) {
              const statusClasses = ['pending', 'running', 'success', 'failed', 'skipped'];
              message.steps.forEach(function(stepUpdate) {
                // Find step node by data-step-index (works for both horizontal and vertical)
                const stepNode = document.querySelector('[data-step-index="' + stepUpdate.index + '"]');
                if (!stepNode) return;

                // Remove old status classes and add new one
                statusClasses.forEach(function(cls) { stepNode.classList.remove(cls); });
                stepNode.classList.add(stepUpdate.status);

                // Update the icon
                const iconEl = stepNode.querySelector('.step-icon-h') || stepNode.querySelector('.step-icon');
                if (iconEl && stepUpdate.icon) {
                  iconEl.textContent = stepUpdate.icon;
                }

                // Update tooltip if provided
                if (stepUpdate.tooltip) {
                  stepNode.title = stepUpdate.tooltip;
                }

                // Update lifecycle indicators if provided
                if (stepUpdate.lifecycleHtml !== undefined) {
                  const lifecycleEl = stepNode.querySelector('.step-lifecycle-h');
                  if (stepUpdate.lifecycleHtml && !lifecycleEl) {
                    // Add lifecycle container
                    const div = document.createElement('div');
                    div.className = 'step-lifecycle-h';
                    div.innerHTML = stepUpdate.lifecycleHtml;
                    // Insert before icon
                    const iconContainer = stepNode.querySelector('.step-icon-h');
                    if (iconContainer) {
                      stepNode.insertBefore(div, iconContainer);
                    }
                  } else if (lifecycleEl) {
                    lifecycleEl.innerHTML = stepUpdate.lifecycleHtml || '';
                  }
                }
              });

              // Also update the workflow meta status text if provided
              if (message.metaHtml) {
                const metaEl = document.querySelector('.workflow-meta');
                if (metaEl) {
                  metaEl.innerHTML = message.metaHtml;
                  // Update class for status coloring
                  if (message.metaClass) {
                    metaEl.className = 'workflow-meta ' + message.metaClass;
                  }
                }
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
          case 'activityLog':
            // Update activity log with new message
            if (message.text && typeof addActivityMessage === 'function') {
              addActivityMessage(message.text);
            }
            break;
          case 'contextTestResult':
          case 'personaTestResult':
            // Context/persona test result received - request tab re-render
            // The extension will handle updating the SlackTab's state
            console.log('[CommandCenter] Context test result received, requesting re-render');
            vscode.postMessage({ command: 'requestTabRerender', tabId: 'slack' });
            break;
          case 'contextTestStarted':
          case 'personaTestStarted':
            // Update button to show running state
            const contextBtn = document.querySelector('[data-action="runContextTest"]');
            if (contextBtn) {
              contextBtn.disabled = true;
              contextBtn.innerHTML = '⏳ Gathering...';
            }
            break;
        }
      });

      // Activity log management - shows last 4 refresh activities with fading opacity
      const activityMessages = [];
      const maxActivityMessages = 4;

      function addActivityMessage(text) {
        // Add new message to front
        activityMessages.unshift(text);
        // Keep only last 4
        if (activityMessages.length > maxActivityMessages) {
          activityMessages.pop();
        }
        // Update display
        updateActivityDisplay();
      }

      function updateActivityDisplay() {
        const slots = document.querySelectorAll('.activity-line');
        slots.forEach((slot, index) => {
          if (index < activityMessages.length) {
            slot.textContent = '› ' + activityMessages[index];
            slot.style.opacity = String(1 - (index * 0.2)); // 1.0, 0.8, 0.6, 0.4
            slot.classList.add('visible');
          } else {
            slot.textContent = '';
            slot.classList.remove('visible');
          }
        });
      }

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
