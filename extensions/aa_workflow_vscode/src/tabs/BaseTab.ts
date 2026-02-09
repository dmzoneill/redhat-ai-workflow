/**
 * Base Tab Class
 *
 * Abstract base class for all Command Center tabs.
 * Provides common functionality for data loading, HTML generation, and updates.
 *
 * Architecture: Tabs follow MVC pattern
 * - Model: Service classes (injected via setServices)
 * - View: getContent(), getStyles(), getScript()
 * - Controller: handleMessage()
 */

import * as vscode from "vscode";
import { dbus } from "../dbusClient";
import { createLogger } from "../logger";
import type { ServiceContainer } from "../services";

// Re-export dbus for use by tab classes that import from BaseTab
// NOTE: Prefer using this.services.* instead of direct dbus calls
export { dbus };

// Export createLogger for use by tab subclasses
export { createLogger };

/**
 * Tab configuration.
 */
export interface TabConfig {
  id: string;
  label: string;
  icon: string;
  badge?: string | number;
  badgeClass?: string;
}

/**
 * Context for tab rendering.
 */
export interface TabContext {
  extensionUri: vscode.Uri;
  webview: vscode.Webview;
  postMessage: (message: any) => void;
}

/**
 * Callback for when a tab needs to be re-rendered.
 */
export type RenderCallback = () => void;

/**
 * Abstract base class for Command Center tabs.
 */
export abstract class BaseTab {
  protected readonly id: string;
  protected readonly label: string;
  protected readonly icon: string;
  protected context: TabContext | null = null;
  protected isLoading = false;
  protected lastError: string | null = null;
  private _onNeedsRender: RenderCallback | null = null;
  private _renderDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  private _renderDebounceMs = 150; // Debounce renders to max ~7/sec

  /**
   * Service container for domain services.
   * Tabs should use these services instead of calling D-Bus directly.
   * This eliminates duplicate business logic between Tabs and Services.
   */
  protected services: ServiceContainer = {};

  constructor(config: TabConfig) {
    this.id = config.id;
    this.label = config.label;
    this.icon = config.icon;
  }

  /**
   * Set the service container for this tab.
   * Called by TabManager after tab creation.
   */
  setServices(services: ServiceContainer): void {
    this.services = services;
  }

  /**
   * Set the callback for when the tab needs to be re-rendered.
   */
  setRenderCallback(callback: RenderCallback): void {
    this._onNeedsRender = callback;
  }

  /**
   * Notify that the tab needs to be re-rendered.
   * Call this when internal state changes that affect the UI.
   *
   * Debounced to prevent flickering - multiple rapid calls within
   * _renderDebounceMs are coalesced into a single render.
   */
  protected notifyNeedsRender(): void {
    const logger = createLogger(`${this.id}Tab`);
    if (!this._onNeedsRender) {
      logger.warn("notifyNeedsRender: NO callback set!");
      return;
    }

    // If a render is already scheduled, skip - it will pick up latest state
    if (this._renderDebounceTimer) {
      logger.log("notifyNeedsRender: debounced (render already scheduled)");
      return;
    }

    this._renderDebounceTimer = setTimeout(() => {
      this._renderDebounceTimer = null;
      if (this._onNeedsRender) {
        logger.log("notifyNeedsRender: executing debounced render");
        this._onNeedsRender();
      }
    }, this._renderDebounceMs);
  }

  /**
   * Force an immediate render, bypassing the debounce.
   * Use sparingly - only for user-initiated actions that need instant feedback.
   */
  protected notifyNeedsRenderImmediate(): void {
    const logger = createLogger(`${this.id}Tab`);
    if (!this._onNeedsRender) {
      logger.warn("notifyNeedsRenderImmediate: NO callback set!");
      return;
    }

    // Cancel any pending debounced render
    if (this._renderDebounceTimer) {
      clearTimeout(this._renderDebounceTimer);
      this._renderDebounceTimer = null;
    }

    logger.log("notifyNeedsRenderImmediate: rendering now");
    this._onNeedsRender();
  }

  /**
   * Get the tab ID.
   */
  getId(): string {
    return this.id;
  }

  /**
   * Get the tab label.
   */
  getLabel(): string {
    return this.label;
  }

  /**
   * Get the tab icon.
   */
  getIcon(): string {
    return this.icon;
  }

  /**
   * Set the tab context.
   */
  setContext(context: TabContext): void {
    this.context = context;
  }

  /**
   * Post an incremental message directly to the webview without triggering
   * a full re-render. Use this for targeted DOM updates (e.g., updating
   * CSS classes on individual elements) that don't require regenerating
   * the entire tab HTML.
   */
  protected postMessageToWebview(message: any): boolean {
    if (this.context?.postMessage) {
      this.context.postMessage(message);
      return true;
    }
    return false;
  }

  /**
   * Get the badge to display on the tab (e.g., count, status).
   * Override in subclasses to provide dynamic badges.
   */
  getBadge(): { text: string; class?: string } | null {
    return null;
  }

  /**
   * Load data for the tab.
   * Override in subclasses to fetch data from D-Bus or other sources.
   */
  abstract loadData(): Promise<void>;

  /**
   * Generate HTML content for the tab.
   * Override in subclasses to provide tab-specific content.
   */
  abstract getContent(): string;

  /**
   * Generate CSS styles for the tab.
   * Override in subclasses to provide tab-specific styles.
   */
  getStyles(): string {
    return "";
  }

  /**
   * Generate JavaScript for the tab.
   * Override in subclasses to provide tab-specific scripts.
   */
  getScript(): string {
    return "";
  }

  /**
   * Handle a message from the webview.
   * Override in subclasses to handle tab-specific messages.
   */
  async handleMessage(message: any): Promise<boolean> {
    return false;
  }

  /**
   * Called when the tab becomes visible.
   */
  onActivate(): void {
    // Override in subclasses if needed
  }

  /**
   * Called when the tab becomes hidden.
   */
  onDeactivate(): void {
    // Override in subclasses if needed
  }

  /**
   * Refresh the tab data and update the UI.
   * Includes automatic retry with exponential backoff.
   */
  async refresh(maxRetries = 2): Promise<void> {
    this.isLoading = true;
    const logger = createLogger(`${this.id}Tab`);

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        await this.loadData();
        // Success - clear error and exit
        this.lastError = null;
        this.isLoading = false;
        this.notifyNeedsRender();
        return;
      } catch (error) {
        this.lastError = error instanceof Error ? error.message : String(error);
        logger.warn(`Refresh attempt ${attempt}/${maxRetries} failed: ${this.lastError}`);

        if (attempt < maxRetries) {
          // Wait before retry with exponential backoff (500ms, 1000ms, 2000ms...)
          const delay = 500 * Math.pow(2, attempt - 1);
          logger.log(`Retrying in ${delay}ms...`);
          await new Promise(resolve => setTimeout(resolve, delay));
        }
      }
    }

    // All retries exhausted
    logger.error(`All ${maxRetries} refresh attempts failed`);
    this.isLoading = false;
    this.notifyNeedsRender();
  }

  /**
   * Send a message to the webview.
   */
  protected postMessage(message: any): void {
    if (this.context) {
      this.context.postMessage(message);
    }
  }

  /**
   * Generate the tab button HTML.
   */
  getTabButtonHtml(): string {
    const badge = this.getBadge();
    const badgeHtml = badge
      ? `<span class="tab-badge ${badge.class || ""}">${badge.text}</span>`
      : '<span class="tab-badge-placeholder"></span>';

    return `
      <button class="tab" data-tab="${this.id}">
        ${badgeHtml}
        <span class="tab-icon">${this.icon}</span>
        <span class="tab-label">${this.label}</span>
      </button>
    `;
  }

  /**
   * Generate the tab content wrapper HTML.
   */
  getTabContentHtml(): string {
    try {
      const content = this.getContent();
      if (content === undefined || content === null) {
        return `
          <div id="${this.id}" class="tab-content">
            <div class="section"><p>Content unavailable</p></div>
          </div>
        `;
      }
      return `
        <div id="${this.id}" class="tab-content">
          ${content}
        </div>
      `;
    } catch (err) {
      const logger = createLogger(`${this.id}Tab`);
      logger.error(`Error in getContent(): ${err}`);
      return `
        <div id="${this.id}" class="tab-content">
          <div class="section"><p>Error loading content: ${err instanceof Error ? err.message : String(err)}</p></div>
        </div>
      `;
    }
  }

  /**
   * Generate a loading placeholder.
   */
  protected getLoadingHtml(message = "Loading..."): string {
    return `
      <div class="loading-placeholder">
        <span class="loading-spinner">⏳</span>
        <span>${message}</span>
      </div>
    `;
  }

  /**
   * Generate an error message.
   */
  protected getErrorHtml(message: string): string {
    return `
      <div class="error-message">
        <span class="error-icon">❌</span>
        <span>${this.escapeHtml(message)}</span>
      </div>
    `;
  }

  /**
   * Generate an empty state message.
   */
  protected getEmptyStateHtml(icon: string, message: string): string {
    return `
      <div class="empty-state">
        <div class="empty-state-icon">${icon}</div>
        <div class="empty-state-text">${this.escapeHtml(message)}</div>
      </div>
    `;
  }

  /**
   * Escape HTML special characters.
   */
  protected escapeHtml(text: string): string {
    if (!text) return "";
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  /**
   * Format a duration in milliseconds.
   */
  protected formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const mins = Math.floor(ms / 60000);
    const secs = Math.floor((ms % 60000) / 1000);
    return `${mins}m ${secs}s`;
  }

  /**
   * Format a timestamp to a relative time string.
   */
  protected formatRelativeTime(timestamp: string | Date | undefined | null): string {
    if (!timestamp) return "unknown";

    const date = typeof timestamp === "string" ? new Date(timestamp) : timestamp;

    // Check for invalid date
    if (isNaN(date.getTime())) return "unknown";

    const now = new Date();
    const diff = now.getTime() - date.getTime();

    if (diff < 60000) return "just now";
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return date.toLocaleDateString();
  }

  /**
   * Format a timestamp to a time string.
   */
  protected formatTime(timestamp: string | Date): string {
    const date = typeof timestamp === "string" ? new Date(timestamp) : timestamp;
    return date.toLocaleTimeString();
  }

  /**
   * 20 distinct persona colors optimized for dark backgrounds.
   * Each color has good contrast and is visually distinct.
   */
  protected static readonly PERSONA_COLORS: { bg: string; text: string }[] = [
    { bg: "rgba(139, 92, 246, 0.25)", text: "#a78bfa" },   // Purple (researcher)
    { bg: "rgba(59, 130, 246, 0.25)", text: "#60a5fa" },   // Blue (developer)
    { bg: "rgba(16, 185, 129, 0.25)", text: "#34d399" },   // Emerald (devops)
    { bg: "rgba(245, 158, 11, 0.25)", text: "#fbbf24" },   // Amber (incident)
    { bg: "rgba(239, 68, 68, 0.25)", text: "#f87171" },    // Red (release)
    { bg: "rgba(236, 72, 153, 0.25)", text: "#f472b6" },   // Pink
    { bg: "rgba(14, 165, 233, 0.25)", text: "#38bdf8" },   // Sky
    { bg: "rgba(168, 85, 247, 0.25)", text: "#c084fc" },   // Violet
    { bg: "rgba(34, 197, 94, 0.25)", text: "#4ade80" },    // Green
    { bg: "rgba(251, 146, 60, 0.25)", text: "#fb923c" },   // Orange
    { bg: "rgba(6, 182, 212, 0.25)", text: "#22d3ee" },    // Cyan
    { bg: "rgba(244, 114, 182, 0.25)", text: "#f9a8d4" },  // Rose
    { bg: "rgba(132, 204, 22, 0.25)", text: "#a3e635" },   // Lime
    { bg: "rgba(99, 102, 241, 0.25)", text: "#818cf8" },   // Indigo
    { bg: "rgba(249, 115, 22, 0.25)", text: "#fb923c" },   // Deep Orange
    { bg: "rgba(20, 184, 166, 0.25)", text: "#2dd4bf" },   // Teal
    { bg: "rgba(217, 70, 239, 0.25)", text: "#e879f9" },   // Fuchsia
    { bg: "rgba(234, 179, 8, 0.25)", text: "#facc15" },    // Yellow
    { bg: "rgba(96, 165, 250, 0.25)", text: "#93c5fd" },   // Light Blue
    { bg: "rgba(74, 222, 128, 0.25)", text: "#86efac" },   // Light Green
  ];

  /**
   * Unique icons per persona name - consistent across all tabs.
   */
  protected static readonly PERSONA_ICONS: Record<string, string> = {
    developer: "👨‍💻",
    devops: "🔧",
    incident: "🚨",
    release: "📦",
    admin: "📊",
    slack: "💬",
    core: "⚙️",
    universal: "🌐",
    researcher: "🔍",
    meetings: "📅",
    observability: "📈",
    project: "📁",
    workspace: "🏠",
    code: "💻",
    presentations: "🎬",
    performance: "📈",
  };

  /**
   * Get icon for a persona name.
   */
  protected getPersonaIcon(personaName: string): string {
    if (!personaName) return "🎭";
    const name = personaName.toLowerCase();
    return BaseTab.PERSONA_ICONS[name] || "🎭";
  }

  /**
   * Get a consistent color for a persona name.
   * Uses a hash function to ensure the same persona always gets the same color.
   */
  protected getPersonaColor(personaName: string): { bg: string; text: string } {
    if (!personaName) {
      return BaseTab.PERSONA_COLORS[0];
    }

    // Simple hash function to get consistent color index
    let hash = 0;
    for (let i = 0; i < personaName.length; i++) {
      const char = personaName.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit integer
    }

    const index = Math.abs(hash) % BaseTab.PERSONA_COLORS.length;
    return BaseTab.PERSONA_COLORS[index];
  }

  /**
   * Generate a styled persona badge HTML with icon.
   */
  protected getPersonaBadgeHtml(personaName: string): string {
    if (!personaName) return "-";

    const icon = this.getPersonaIcon(personaName);
    const personaClass = personaName.toLowerCase();
    return `<span class="persona-badge ${this.escapeHtml(personaClass)}">${icon} ${this.escapeHtml(personaName)}</span>`;
  }
}
