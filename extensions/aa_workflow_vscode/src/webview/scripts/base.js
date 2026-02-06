/**
 * Base JavaScript for Command Center Webview
 *
 * Common utilities and functions shared across all tabs.
 * Tab-specific event handlers are now in their respective Tab files.
 */

// VS Code API instance
const vscode = acquireVsCodeApi();

// Global error handler for debugging
window.onerror = function(msg, url, lineNo, columnNo, error) {
  console.error('[GLOBAL ERROR]', msg, 'at line', lineNo, ':', columnNo);
  console.error('[GLOBAL ERROR] Stack:', error ? error.stack : 'no stack');
  return false;
};

window.addEventListener('unhandledrejection', function(event) {
  console.error('[UNHANDLED PROMISE]', event.reason);
});

console.log('[DEBUG] Command Center script starting...');

// Extension connection state
let extensionConnected = false;

/**
 * Check if extension is connected by sending a ping.
 * If we don't get a pong within 2 seconds, show a reconnect message.
 */
function checkExtensionConnection() {
  vscode.postMessage({ command: 'ping' });
  setTimeout(() => {
    if (!extensionConnected) {
      console.warn('[CommandCenter-Webview] Extension not responding - panel may need refresh');
      showReconnectBanner();
    }
  }, 2000);
}

/**
 * Show a reconnect banner at the top of the page.
 */
function showReconnectBanner() {
  if (document.getElementById('reconnectBanner')) return;

  const banner = document.createElement('div');
  banner.id = 'reconnectBanner';
  banner.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; background: #f59e0b; color: #000; padding: 12px 20px; text-align: center; font-weight: 600; z-index: 9999; display: flex; justify-content: center; align-items: center; gap: 16px;';
  
  const textSpan = document.createElement('span');
  textSpan.textContent = '⚠️ Command Center is disconnected from the extension. ';
  
  const reloadBtn = document.createElement('button');
  reloadBtn.textContent = 'Reload Panel';
  reloadBtn.style.cssText = 'background: #000; color: #fff; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-weight: 600;';
  reloadBtn.addEventListener('click', () => location.reload());
  
  const helpSpan = document.createElement('span');
  helpSpan.style.cssText = 'font-weight: normal; font-size: 0.9em;';
  helpSpan.textContent = ' or close this tab and reopen via Command Palette';
  
  banner.appendChild(textSpan);
  banner.appendChild(reloadBtn);
  banner.appendChild(helpSpan);
  document.body.insertBefore(banner, document.body.firstChild);
  document.body.style.paddingTop = '60px';
}

/**
 * Hide the reconnect banner.
 */
function hideReconnectBanner() {
  const banner = document.getElementById('reconnectBanner');
  if (banner) {
    banner.remove();
    document.body.style.paddingTop = '';
  }
}

// Run connection check on load
checkExtensionConnection();

// ============================================
// Utility Functions
// ============================================

/**
 * Escape HTML special characters.
 */
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Format a duration in milliseconds to a human-readable string.
 */
function formatDuration(ms) {
  if (ms === undefined || ms === null || ms === '' || isNaN(ms)) return '';
  ms = Number(ms);
  if (isNaN(ms) || ms <= 0) return '';
  if (ms < 1000) return ms + 'ms';
  if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
  const mins = Math.floor(ms / 60000);
  const secs = Math.floor((ms % 60000) / 1000);
  return mins + 'm ' + secs + 's';
}

/**
 * Format a timestamp to a relative time string.
 */
function formatRelativeTime(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  const now = new Date();
  const diff = now - date;

  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff / 60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff / 3600000) + 'h ago';
  if (diff < 604800000) return Math.floor(diff / 86400000) + 'd ago';
  return date.toLocaleDateString();
}

/**
 * Format a timestamp to a time string.
 */
function formatTime(timestamp) {
  if (!timestamp) return '';
  return new Date(timestamp).toLocaleTimeString();
}

/**
 * Format a timestamp to a date/time string.
 */
function formatDateTime(timestamp) {
  if (!timestamp) return '';
  return new Date(timestamp).toLocaleString();
}

/**
 * Format bytes to a human-readable string.
 */
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Truncate a string to a maximum length.
 */
function truncate(str, maxLength = 50) {
  if (!str) return '';
  if (str.length <= maxLength) return str;
  return str.substring(0, maxLength - 3) + '...';
}

/**
 * Debounce a function.
 */
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Throttle a function.
 */
function throttle(func, limit) {
  let inThrottle;
  return function executedFunction(...args) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

// ============================================
// DOM Helpers
// ============================================

/**
 * Get an element by ID with type checking.
 */
function $(id) {
  return document.getElementById(id);
}

/**
 * Query selector shorthand.
 */
function $$(selector) {
  return document.querySelectorAll(selector);
}

/**
 * Add event listener to all matching elements.
 */
function addEventListenerAll(selector, event, handler) {
  document.querySelectorAll(selector).forEach(el => {
    el.addEventListener(event, handler);
  });
}

/**
 * Show an element.
 */
function show(element) {
  if (typeof element === 'string') element = $(element);
  if (element) element.style.display = '';
}

/**
 * Hide an element.
 */
function hide(element) {
  if (typeof element === 'string') element = $(element);
  if (element) element.style.display = 'none';
}

/**
 * Toggle element visibility.
 */
function toggle(element, visible) {
  if (typeof element === 'string') element = $(element);
  if (element) {
    if (visible === undefined) {
      element.style.display = element.style.display === 'none' ? '' : 'none';
    } else {
      element.style.display = visible ? '' : 'none';
    }
  }
}

/**
 * Add a class to an element.
 */
function addClass(element, className) {
  if (typeof element === 'string') element = $(element);
  if (element) element.classList.add(className);
}

/**
 * Remove a class from an element.
 */
function removeClass(element, className) {
  if (typeof element === 'string') element = $(element);
  if (element) element.classList.remove(className);
}

/**
 * Toggle a class on an element.
 */
function toggleClass(element, className, force) {
  if (typeof element === 'string') element = $(element);
  if (element) element.classList.toggle(className, force);
}

// ============================================
// Message Handling
// ============================================

/**
 * Send a message to the extension.
 */
function sendMessage(command, data = {}) {
  vscode.postMessage({ command, ...data });
}

/**
 * Log a message to the extension's output channel.
 */
function log(message) {
  vscode.postMessage({ command: 'webviewLog', message });
}

// ============================================
// Inference Result Formatting
// ============================================

/**
 * Format inference test result for display.
 */
function formatInferenceResult(data) {
  const ctx = data.context || {};
  const mem = data.memory_state || {};
  const env = data.environment || {};

  // Build the layer badges
  const methods = data.methods || [];
  const layerNames = {
    layer1_core: '🔵 Core',
    layer2_persona: '🟢 Persona',
    layer3_skill: '🎯 Skill',
    layer4_npu: '🟣 NPU',
    layer4_keyword_fallback: '🟡 Keyword',
    fast_path: '⚡ Fast',
    timeout_fallback: '⏱️ Timeout',
    spawn_error_fallback: '❌ Error',
  };
  const layerBadges = methods
    .map(m => '<span class="layer-badge" style="background: rgba(139,92,246,0.2); padding: 2px 8px; border-radius: 12px; font-size: 11px;">' + (layerNames[m] || m) + '</span>')
    .join(' → ');

  // Error banner if any
  const errorBanner = data.error
    ? '<div style="background: var(--vscode-inputValidation-errorBackground); padding: 8px 12px; border-radius: 4px; margin-bottom: 12px; color: var(--vscode-errorForeground);">⚠️ ' + escapeHtml(data.error) + '</div>'
    : '';

  let html = errorBanner;

  // Summary header
  const finalToolCount = (data.tools || []).length;
  html += '<div style="display: flex; align-items: baseline; gap: 12px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--vscode-widget-border);">' +
    '<span style="font-size: 1.3em; font-weight: bold; color: var(--vscode-testing-iconPassed);">✅ ' + finalToolCount + ' tools</span>' +
    '<span style="color: var(--vscode-descriptionForeground);">' + (data.latency_ms || 0) + 'ms • ' + (data.reduction_pct || 0).toFixed(1) + '% reduction</span>' +
    '<span style="margin-left: auto;">' + layerBadges + '</span>' +
  '</div>';

  // Persona section
  const personaIcons = { developer: '👨‍💻', devops: '🔧', incident: '🚨', release: '📦' };
  const personaAutoDetected = data.persona_auto_detected || false;
  const personaReason = data.persona_detection_reason || 'passed_in';

  html += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(34,197,94,0.1); border-radius: 8px; border-left: 3px solid #22c55e;">' +
    '<div style="font-weight: bold; margin-bottom: 8px;">' + (personaIcons[data.persona] || '👤') + ' Persona: ' + escapeHtml(data.persona) +
    (personaAutoDetected ? ' <span style="background: rgba(34,197,94,0.3); padding: 2px 6px; border-radius: 8px; font-size: 10px; font-weight: normal;">🔍 Auto-detected via ' + escapeHtml(personaReason) + '</span>' : '') +
    '</div>' +
  '</div>';

  // Memory state section
  const kubeconfigs = env.kubeconfigs || {};
  html += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(168,85,247,0.1); border-radius: 8px; border-left: 3px solid #a855f7;">' +
    '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">' +
      '<span style="font-weight: bold;">🧠 Memory State</span>' +
      '<span style="font-size: 11px; display: flex; gap: 8px;">' +
        '<span>' + (env.vpn_connected ? '🟢' : '🔴') + ' VPN</span>' +
        '<span>' + (kubeconfigs.stage ? '🟢' : '⚪') + ' Stage</span>' +
        '<span>' + (kubeconfigs.prod ? '🟢' : '⚪') + ' Prod</span>' +
        '<span>' + (kubeconfigs.ephemeral ? '🟢' : '⚪') + ' Eph</span>' +
      '</span>' +
    '</div>' +
    '<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 12px;">' +
      '<div><span style="color: var(--vscode-descriptionForeground);">Current Repo:</span> <code>' + escapeHtml(mem.current_repo || 'none') + '</code></div>' +
      '<div><span style="color: var(--vscode-descriptionForeground);">Current Branch:</span> <code>' + escapeHtml(mem.current_branch || 'none') + '</code></div>' +
    '</div>' +
  '</div>';

  // Skill section if detected
  if (ctx.skill && ctx.skill.name) {
    html += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(139,92,246,0.1); border-radius: 8px; border-left: 3px solid #8b5cf6;">' +
      '<div style="font-weight: bold; margin-bottom: 8px;">🎯 Detected Skill: ' + escapeHtml(ctx.skill.name) + '</div>' +
      '<div style="display: flex; flex-wrap: wrap; gap: 4px;">' +
        (ctx.skill.tools || []).map(t => '<span style="background: rgba(139,92,246,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + t + '</span>').join('') +
      '</div>' +
    '</div>';
  }

  // Tools list
  const tools = data.tools || [];
  if (tools.length > 0) {
    html += '<div class="context-section" style="margin-bottom: 16px; padding: 12px; background: rgba(59,130,246,0.1); border-radius: 8px; border-left: 3px solid #3b82f6;">' +
      '<div style="font-weight: bold; margin-bottom: 8px;">🔧 Filtered Tools (' + tools.length + ')</div>' +
      '<div style="display: flex; flex-wrap: wrap; gap: 4px;">' +
        tools.slice(0, 30).map(t => '<span style="background: rgba(59,130,246,0.2); padding: 2px 6px; border-radius: 4px; font-size: 11px;">' + escapeHtml(t) + '</span>').join('') +
        (tools.length > 30 ? '<span style="padding: 2px 6px; font-size: 11px; color: var(--vscode-descriptionForeground);">+' + (tools.length - 30) + ' more</span>' : '') +
      '</div>' +
    '</div>';
  }

  return html;
}

// ============================================
// Centralized Event Delegation System
// ============================================
// This system allows tabs to register handlers that survive content updates.
// Handlers are stored by tab ID and can be re-registered without duplicates.

const TabEventDelegation = (function() {
  // Store handlers by tab ID -> event type -> handler function
  const handlers = new Map();
  
  // Track if global listeners are set up
  let initialized = false;
  
  /**
   * Register a click handler for a tab.
   * Can be called multiple times - will replace the previous handler.
   * 
   * @param {string} tabId - The tab container ID (e.g., 'sessions', 'slack')
   * @param {function} handler - Handler function(action, element, event)
   */
  function registerClickHandler(tabId, handler) {
    if (!handlers.has(tabId)) {
      handlers.set(tabId, {});
    }
    handlers.get(tabId).click = handler;
    console.log(`[TabEventDelegation] Registered click handler for #${tabId}`);
  }
  
  /**
   * Register a change handler for a tab (for selects, inputs).
   * 
   * @param {string} tabId - The tab container ID
   * @param {function} handler - Handler function(element, event)
   */
  function registerChangeHandler(tabId, handler) {
    if (!handlers.has(tabId)) {
      handlers.set(tabId, {});
    }
    handlers.get(tabId).change = handler;
    console.log(`[TabEventDelegation] Registered change handler for #${tabId}`);
  }
  
  /**
   * Register a keypress handler for a tab.
   * 
   * @param {string} tabId - The tab container ID
   * @param {function} handler - Handler function(element, event)
   */
  function registerKeypressHandler(tabId, handler) {
    if (!handlers.has(tabId)) {
      handlers.set(tabId, {});
    }
    handlers.get(tabId).keypress = handler;
    console.log(`[TabEventDelegation] Registered keypress handler for #${tabId}`);
  }
  
  /**
   * Initialize global event listeners (called once).
   */
  function init() {
    if (initialized) return;
    initialized = true;
    
    // Global click delegation
    document.addEventListener('click', function(e) {
      const actionBtn = e.target.closest('[data-action]');
      if (!actionBtn) return;
      
      const action = actionBtn.dataset.action;
      
      // Find which tab container this belongs to
      const tabContent = actionBtn.closest('.tab-content');
      if (!tabContent) {
        console.log(`[TabEventDelegation] Click on ${action} - no tab container found`);
        return;
      }
      
      const tabId = tabContent.id;
      const tabHandlers = handlers.get(tabId);
      
      if (tabHandlers && tabHandlers.click) {
        console.log(`[TabEventDelegation] Dispatching click '${action}' to #${tabId}`);
        tabHandlers.click(action, actionBtn, e);
      } else {
        console.log(`[TabEventDelegation] No click handler for #${tabId}, action: ${action}`);
      }
    });
    
    // Global change delegation
    document.addEventListener('change', function(e) {
      const target = e.target;
      if (!target.matches('select, input[type="checkbox"], input[type="radio"]')) return;
      
      const tabContent = target.closest('.tab-content');
      if (!tabContent) return;
      
      const tabId = tabContent.id;
      const tabHandlers = handlers.get(tabId);
      
      if (tabHandlers && tabHandlers.change) {
        console.log(`[TabEventDelegation] Dispatching change to #${tabId}`);
        tabHandlers.change(target, e);
      }
    });
    
    // Global keypress delegation
    document.addEventListener('keypress', function(e) {
      const target = e.target;
      if (!target.matches('input, textarea')) return;
      
      const tabContent = target.closest('.tab-content');
      if (!tabContent) return;
      
      const tabId = tabContent.id;
      const tabHandlers = handlers.get(tabId);
      
      if (tabHandlers && tabHandlers.keypress) {
        tabHandlers.keypress(target, e);
      }
    });
    
    console.log('[TabEventDelegation] Initialized global event listeners');
  }
  
  /**
   * Check if a tab has handlers registered.
   */
  function hasHandlers(tabId) {
    return handlers.has(tabId);
  }
  
  /**
   * Get debug info about registered handlers.
   */
  function getDebugInfo() {
    const info = {};
    handlers.forEach((h, tabId) => {
      info[tabId] = Object.keys(h);
    });
    return info;
  }
  
  // Auto-initialize
  init();
  
  return {
    registerClickHandler,
    registerChangeHandler,
    registerKeypressHandler,
    hasHandlers,
    getDebugInfo,
    init
  };
})();

// Expose globally for tab scripts
window.TabEventDelegation = TabEventDelegation;

console.log('[DEBUG] Base.js loaded with centralized event delegation system');
console.log('[DEBUG] TabEventDelegation available:', typeof TabEventDelegation !== 'undefined');
console.log('[DEBUG] TabEventDelegation methods:', TabEventDelegation ? Object.keys(TabEventDelegation) : 'N/A');
