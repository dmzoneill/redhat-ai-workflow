/**
 * Tab Manager
 *
 * Manages all tabs in the Command Center panel.
 * Handles tab registration, switching, and message routing.
 *
 * Architecture: TabManager injects Services into Tabs so they can use
 * Services instead of calling D-Bus directly. This eliminates duplicate
 * business logic between Tabs and Services.
 */

import * as vscode from "vscode";
import {
  BaseTab,
  OverviewTab,
  MeetingsTab,
  SprintTab,
  SkillsTab,
  ServicesTab,
  CronTab,
  SlackTab,
  MemoryTab,
  SessionsTab,
  PersonasTab,
  ToolsTab,
  CreateTab,
  InferenceTab,
  PerformanceTab,
  SlopTab,
} from "../tabs";
import { createLogger } from "../logger";
import type { ServiceContainer } from "../services";

const logger = createLogger("TabManager");

export interface TabManagerContext {
  extensionUri: vscode.Uri;
  webview: vscode.Webview;
}

export class TabManager {
  private tabs: Map<string, BaseTab> = new Map();
  private activeTabId: string = "overview";
  private context: TabManagerContext | null = null;
  private _onNeedsRender: (() => void) | null = null;
  private _services: ServiceContainer = {};

  constructor() {
    // Register default tabs
    this.registerDefaultTabs();
  }

  /**
   * Set the service container for all tabs.
   * This should be called after services are initialized in CommandCenterPanel.
   * Tabs can then use this.services.* instead of calling D-Bus directly.
   */
  setServices(services: ServiceContainer): void {
    this._services = services;
    // Inject services into all existing tabs
    this.tabs.forEach((tab) => {
      tab.setServices(services);
    });
    logger.log(`Services injected into ${this.tabs.size} tabs`);
  }

  /**
   * Set the callback for when any tab needs to be re-rendered.
   */
  setRenderCallback(callback: () => void): void {
    this._onNeedsRender = callback;
    // Set the callback on all existing tabs
    this.tabs.forEach((tab) => {
      tab.setRenderCallback(callback);
    });
  }

  private registerDefaultTabs(): void {
    logger.log("Registering default tabs...");
    this.registerTab(new OverviewTab());
    this.registerTab(new CreateTab());
    this.registerTab(new SprintTab());
    this.registerTab(new SessionsTab());
    this.registerTab(new PersonasTab());
    this.registerTab(new SkillsTab());
    this.registerTab(new ToolsTab());
    this.registerTab(new MemoryTab());
    this.registerTab(new MeetingsTab());
    this.registerTab(new SlackTab());
    this.registerTab(new InferenceTab());
    this.registerTab(new CronTab());
    this.registerTab(new ServicesTab());
    this.registerTab(new PerformanceTab());
    this.registerTab(new SlopTab());
    logger.log(`Registered ${this.tabs.size} tabs`);
  }

  /**
   * Set the context for all tabs
   */
  setContext(context: TabManagerContext): void {
    this.context = context;
    const tabContext = {
      extensionUri: context.extensionUri,
      webview: context.webview,
      postMessage: (message: any) => context.webview.postMessage(message),
    };
    this.tabs.forEach((tab) => {
      tab.setContext(tabContext);
    });
  }

  /**
   * Register a new tab
   */
  registerTab(tab: BaseTab): void {
    this.tabs.set(tab.getId(), tab);
    if (this.context) {
      tab.setContext({
        extensionUri: this.context.extensionUri,
        webview: this.context.webview,
        postMessage: (message: any) => this.context!.webview.postMessage(message),
      });
    }
    // Set the render callback if we have one
    if (this._onNeedsRender) {
      tab.setRenderCallback(this._onNeedsRender);
    }
    // Inject services if we have them
    if (Object.keys(this._services).length > 0) {
      tab.setServices(this._services);
    }
  }

  /**
   * Get a tab by ID
   */
  getTab(tabId: string): BaseTab | undefined {
    return this.tabs.get(tabId);
  }

  /**
   * Get all registered tabs
   */
  getAllTabs(): BaseTab[] {
    return Array.from(this.tabs.values());
  }

  /**
   * Get the active tab
   */
  getActiveTab(): BaseTab | undefined {
    return this.tabs.get(this.activeTabId);
  }

  /**
   * Get the active tab ID
   */
  getActiveTabId(): string {
    return this.activeTabId;
  }

  /**
   * Switch to a specific tab
   */
  async switchTab(tabId: string): Promise<void> {
    const previousTab = this.tabs.get(this.activeTabId);
    const newTab = this.tabs.get(tabId);

    if (!newTab) {
      logger.warn(`Tab not found: ${tabId}`);
      return;
    }

    // Deactivate previous tab
    if (previousTab) {
      await previousTab.onDeactivate();
    }

    // Update active tab
    this.activeTabId = tabId;

    // Activate new tab
    await newTab.onActivate();
  }

  /**
   * Load data for all tabs with timeout
   */
  async loadAllData(): Promise<void> {
    logger.log(`loadAllData() starting for ${this.tabs.size} tabs...`);
    const TIMEOUT_MS = 5000; // 5 second timeout per tab

    const loadPromises = Array.from(this.tabs.values()).map(async (tab) => {
      const tabId = tab.getId();
      logger.log(`loadAllData() - loading ${tabId}...`);
      try {
        // Race between tab load and timeout
        await Promise.race([
          tab.loadData(),
          new Promise((_, reject) =>
            setTimeout(() => reject(new Error(`Timeout after ${TIMEOUT_MS}ms`)), TIMEOUT_MS)
          )
        ]);
        logger.log(`loadAllData() - ${tabId} loaded successfully`);
      } catch (error: any) {
        logger.warn(`loadAllData() - ${tabId} failed: ${error?.message || error}`);
      }
    });
    await Promise.all(loadPromises);
    logger.log(`loadAllData() complete`);
  }

  /**
   * Load data for the active tab only
   */
  async loadActiveTabData(): Promise<void> {
    const activeTab = this.getActiveTab();
    if (activeTab) {
      await activeTab.loadData();
    }
  }

  /**
   * Refresh the active tab
   */
  async refreshActiveTab(): Promise<void> {
    const activeTab = this.getActiveTab();
    if (activeTab) {
      await activeTab.refresh();
    }
  }

  /**
   * Handle a message from the webview
   * Returns true if the message was handled by a tab
   */
  async handleMessage(message: any): Promise<boolean> {
    const msgType = message.command || message.type;
    logger.log(`handleMessage: ${msgType}, activeTabId=${this.activeTabId}`);

    // First try the active tab
    const activeTab = this.getActiveTab();
    if (activeTab) {
      logger.log(`Trying active tab: ${activeTab.getId()}`);
      const handled = await activeTab.handleMessage(message);
      if (handled) {
        logger.log(`Message ${msgType} handled by active tab ${activeTab.getId()}`);
        return true;
      }
    }

    // Then try all other tabs
    for (const [tabId, tab] of this.tabs) {
      if (tabId !== this.activeTabId) {
        const handled = await tab.handleMessage(message);
        if (handled) {
          logger.log(`Message ${msgType} handled by tab ${tabId}`);
          return true;
        }
      }
    }

    logger.log(`Message ${msgType} not handled by any tab`);
    return false;
  }

  /**
   * Get the combined styles for all tabs
   */
  getAllStyles(): string {
    const styles: string[] = [];
    this.tabs.forEach((tab) => {
      const tabStyles = tab.getStyles();
      if (tabStyles) {
        styles.push(`/* ${tab.getId()} tab styles */\n${tabStyles}`);
      }
    });
    return styles.join("\n\n");
  }

  /**
   * Get the combined scripts for all tabs
   */
  getAllScripts(): string {
    const scripts: string[] = [];
    this.tabs.forEach((tab) => {
      const tabScript = tab.getScript();
      if (tabScript) {
        scripts.push(`// ${tab.getId()} tab script\n${tabScript}`);
      }
    });
    return scripts.join("\n\n");
  }

  /**
   * Get the tab buttons HTML
   */
  getTabButtonsHtml(): string {
    const buttons: string[] = [];
    this.tabs.forEach((tab) => {
      buttons.push(tab.getTabButtonHtml());
    });
    return buttons.join("\n");
  }

  /**
   * Get the tab content HTML for all tabs
   */
  getTabContentsHtml(): string {
    const contents: string[] = [];
    logger.log(`Generating HTML for ${this.tabs.size} tabs`);
    this.tabs.forEach((tab) => {
      try {
        const html = tab.getTabContentHtml();
        if (html === undefined || html === null) {
          logger.warn(`Tab ${tab.getId()} returned undefined/null HTML, using empty placeholder`);
          contents.push(`<div id="${tab.getId()}" class="tab-content"><div class="section"><p>Content unavailable</p></div></div>`);
        } else {
          logger.log(`Tab ${tab.getId()} HTML length: ${html.length}`);
          contents.push(html);
        }
      } catch (err) {
        logger.error(`Tab ${tab.getId()} threw error generating HTML: ${err}`);
        contents.push(`<div id="${tab.getId()}" class="tab-content"><div class="section"><p>Error loading content</p></div></div>`);
      }
    });
    const total = contents.join("\n");
    logger.log(`Total tab content HTML: ${total.length} chars`);
    return total;
  }

  /**
   * Get badges for all tabs (for updating tab buttons)
   */
  getAllBadges(): Record<string, { text: string; class?: string } | null> {
    const badges: Record<string, { text: string; class?: string } | null> = {};
    this.tabs.forEach((tab) => {
      badges[tab.getId()] = tab.getBadge();
    });
    return badges;
  }

  /**
   * Post a message to the webview for a specific tab
   */
  postMessageToTab(tabId: string, message: any): void {
    if (this.context) {
      this.context.webview.postMessage({ ...message, targetTab: tabId });
    }
  }

  /**
   * Dispose all tabs
   */
  dispose(): void {
    this.tabs.forEach((tab) => {
      if (typeof (tab as any).dispose === "function") {
        (tab as any).dispose();
      }
    });
    this.tabs.clear();
  }
}
