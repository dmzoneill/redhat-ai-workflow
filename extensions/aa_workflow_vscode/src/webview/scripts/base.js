/**
 * Base JavaScript for Command Center Webview
 *
 * Common utilities and functions shared across all tabs.
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
  banner.innerHTML = '⚠️ Command Center is disconnected from the extension. <button onclick="location.reload()" style="background: #000; color: #fff; border: none; padding: 6px 16px; border-radius: 4px; cursor: pointer; font-weight: 600;">Reload Panel</button> <span style="font-weight: normal; font-size: 0.9em;">or close this tab and reopen via Command Palette</span>';
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
// Event Delegation for Dynamic Content
// ============================================
// This handles clicks on elements that may be replaced by tabContentUpdate
// Since we can't use new Function() due to CSP, we use event delegation instead

document.addEventListener('click', function(e) {
  const target = e.target;

  // Debug: log all clicks to extension output
  const debugActionBtn = target.closest('[data-action]');
  if (debugActionBtn) {
    log('[base.js] Click on data-action element: ' + debugActionBtn.dataset.action);
  }

  // Handle view toggle buttons (Sessions and Personas tabs)
  if (target.id === 'sessionViewCard') {
    e.preventDefault();
    vscode.postMessage({ command: 'changeSessionViewMode', value: 'card' });
    return;
  }
  if (target.id === 'sessionViewTable') {
    e.preventDefault();
    vscode.postMessage({ command: 'changeSessionViewMode', value: 'table' });
    return;
  }
  if (target.id === 'personaViewCard') {
    e.preventDefault();
    vscode.postMessage({ command: 'changePersonaViewMode', value: 'card' });
    return;
  }
  if (target.id === 'personaViewTable') {
    e.preventDefault();
    vscode.postMessage({ command: 'changePersonaViewMode', value: 'table' });
    return;
  }

  // Handle meetings subtab buttons (data-tab attribute)
  const meetingsSubtab = target.closest('.meetings-subtab[data-tab]');
  if (meetingsSubtab) {
    const tabName = meetingsSubtab.dataset.tab;
    log('[base.js] Meetings subtab clicked: ' + tabName);

    // Update tab buttons
    document.querySelectorAll('.meetings-subtab').forEach(btn => {
      btn.classList.remove('active');
      if (btn.dataset.tab === tabName) {
        btn.classList.add('active');
      }
    });

    // Update content panels
    document.querySelectorAll('.subtab-content').forEach(panel => {
      panel.classList.remove('active');
    });
    const targetPanel = document.getElementById('subtab-' + tabName);
    if (targetPanel) {
      targetPanel.classList.add('active');
    }
    return;
  }

  // Handle meetings mode selector buttons (in upcoming meetings list)
  const modeBtn = target.closest('.meeting-mode-selector .mode-btn[data-mode]');
  if (modeBtn) {
    const meetingId = modeBtn.dataset.id;
    const mode = modeBtn.dataset.mode;
    log('[base.js] Meeting mode button clicked: meetingId=' + meetingId + ', mode=' + mode);

    // Update UI for this meeting's mode selector
    const selector = modeBtn.closest('.meeting-mode-selector');
    if (selector) {
      selector.querySelectorAll('.mode-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.mode === mode) btn.classList.add('active');
      });
    }

    // Send to backend
    vscode.postMessage({ type: 'setMeetingMode', meetingId: meetingId, mode: mode });
    return;
  }

  // Handle meetings status badge clicks (approved/skipped toggle)
  const statusBadge = target.closest('.upcoming-meeting-controls .status-badge[data-action]');
  if (statusBadge) {
    const action = statusBadge.dataset.action;
    const meetingId = statusBadge.dataset.id;
    const meetUrl = statusBadge.dataset.url || '';
    const mode = statusBadge.dataset.mode || 'notes';
    const row = statusBadge.closest('.upcoming-meeting-row');
    log('[base.js] Status badge clicked: action=' + action + ', meetingId=' + meetingId);

    if (action === 'unapprove') {
      // Toggle from approved to skipped
      statusBadge.outerHTML = '<span class="status-badge skipped" data-action="approve" data-id="' + meetingId + '" data-url="' + meetUrl + '" data-mode="notes" title="Click to approve this meeting">✗ Skipped</span>';
      if (row) {
        row.classList.remove('approved');
      }
      vscode.postMessage({ type: 'unapproveMeeting', meetingId: meetingId });
    } else if (action === 'approve') {
      // Toggle from skipped/failed back to approved
      statusBadge.outerHTML = '<span class="status-badge approved" data-action="unapprove" data-id="' + meetingId + '" title="Click to skip this meeting">✓ Approved</span>';
      if (row) {
        row.classList.add('approved');
      }
      vscode.postMessage({ type: 'approveMeeting', meetingId: meetingId, meetUrl: meetUrl, mode: mode });
    }
    return;
  }

  // Handle data-action buttons
  const actionBtn = target.closest('[data-action]');
  if (actionBtn) {
    const action = actionBtn.dataset.action;
    log('data-action button clicked: ' + action);
    const sessionId = actionBtn.dataset.sessionId;
    const persona = actionBtn.dataset.persona;
    const skill = actionBtn.dataset.skill;
    const executionId = actionBtn.dataset.executionId;

    switch (action) {
      // Session actions
      case 'newSession':
        vscode.postMessage({ command: 'newSession' });
        break;
      case 'openSession':
        if (sessionId) vscode.postMessage({ command: 'openSession', sessionId });
        break;
      case 'openChatSession':
        if (sessionId) {
          const sessionName = actionBtn.dataset.sessionName;
          vscode.postMessage({ command: 'openChatSession', sessionId, sessionName });
        }
        break;
      case 'copySessionId':
        if (sessionId) vscode.postMessage({ command: 'copySessionId', sessionId });
        break;
      case 'closeSession':
        if (sessionId) vscode.postMessage({ command: 'closeSession', sessionId });
        break;
      case 'refreshSessions':
        vscode.postMessage({ command: 'refreshSessions' });
        break;

      // Persona actions
      case 'loadPersona':
        if (persona) vscode.postMessage({ command: 'loadPersona', persona });
        break;
      case 'startPersonaChat':
        if (persona) vscode.postMessage({ command: 'startPersonaChat', persona });
        break;
      case 'viewPersonaDetails':
        if (persona) vscode.postMessage({ command: 'viewPersonaDetails', persona });
        break;
      case 'refreshPersonas':
        vscode.postMessage({ command: 'refreshPersonas' });
        break;

      // Tool actions
      case 'refreshTools':
        vscode.postMessage({ command: 'refreshTools' });
        break;

      // Skill actions
      case 'runSkill':
        if (skill) vscode.postMessage({ command: 'runSkill', skillName: skill });
        break;
      case 'openSkillFile':
        if (skill) vscode.postMessage({ command: 'openSkillFile', skillName: skill });
        break;
      case 'clearStaleSkills':
        vscode.postMessage({ command: 'clearStaleSkills' });
        break;
      case 'clearSkillExecution':
        if (executionId) vscode.postMessage({ command: 'clearSkillExecution', executionId });
        break;

      // Inference actions
      case 'runInferenceTest':
        log('runInferenceTest action triggered');
        const testMessage = document.getElementById('inferenceTestMessage');
        const testPersona = document.getElementById('inferenceTestPersona');
        const testSkill = document.getElementById('inferenceTestSkill');
        log('testMessage element found: ' + (testMessage ? 'yes' : 'no'));
        log('testMessage value: ' + (testMessage ? testMessage.value : 'null'));
        if (testMessage && testMessage.value) {
          log('Sending runInferenceTest message with: ' + testMessage.value);
          vscode.postMessage({
            command: 'runInferenceTest',
            message: testMessage.value,
            persona: testPersona ? testPersona.value : '',
            skill: testSkill ? testSkill.value : ''
          });
        } else {
          log('No message value found - not sending');
        }
        break;
      case 'copyInferenceResult':
        const resultArea = document.getElementById('inferenceResultArea');
        if (resultArea && resultArea.textContent) {
          navigator.clipboard.writeText(resultArea.textContent).catch(err => {
            console.error('Failed to copy:', err);
          });
        }
        break;
      case 'clearTestResults':
        const inferenceResults = document.getElementById('inferenceResultArea');
        if (inferenceResults) {
          inferenceResults.style.display = 'none';
          inferenceResults.innerHTML = '';
        }
        break;
      case 'testOllama':
        const ollamaInstance = actionBtn.dataset.instance;
        if (ollamaInstance) {
          vscode.postMessage({ command: 'testOllamaInstance', instance: ollamaInstance });
        }
        break;
      case 'resetConfig':
        vscode.postMessage({ command: 'resetInferenceConfig' });
        break;
      case 'saveConfig':
        vscode.postMessage({ command: 'saveInferenceConfig' });
        break;

      // Cron actions
      case 'runCronJobNow': {
        const jobName = actionBtn.dataset.job;
        if (jobName) {
          vscode.postMessage({ command: 'runCronJobNow', jobName: jobName });
        }
        break;
      }
      case 'toggleCronJob': {
        const cronJobName = actionBtn.dataset.job;
        const enabled = actionBtn.checked;
        if (cronJobName !== undefined) {
          vscode.postMessage({ command: 'toggleCronJob', jobName: cronJobName, enabled: enabled });
        }
        break;
      }
      case 'toggleScheduler':
        vscode.postMessage({ command: 'toggleScheduler' });
        break;

      // Meeting actions
      case 'join': {
        const meetUrl = actionBtn.dataset.url;
        const meetTitle = actionBtn.dataset.title;
        const meetMode = actionBtn.dataset.mode || 'notes';
        // Get video enabled from the quick join checkbox
        const videoCheckbox = document.getElementById('quickJoinVideo');
        const videoEnabled = videoCheckbox ? videoCheckbox.checked : false;
        log('Join meeting: ' + meetUrl + ', title: ' + meetTitle + ', mode: ' + meetMode + ', video: ' + videoEnabled);
        vscode.postMessage({ type: 'joinMeetingNow', meetUrl: meetUrl, title: meetTitle, mode: meetMode, videoEnabled: videoEnabled });
        break;
      }
      case 'approve': {
        const approveId = actionBtn.dataset.id;
        const approveUrl = actionBtn.dataset.url || '';
        const approveMode = actionBtn.dataset.mode || 'notes';
        vscode.postMessage({ type: 'approveMeeting', meetingId: approveId, meetUrl: approveUrl, mode: approveMode });
        break;
      }
      case 'leave': {
        const leaveSession = actionBtn.dataset.session;
        vscode.postMessage({ type: 'leaveMeeting', sessionId: leaveSession || '' });
        break;
      }
      case 'toggle-audio': {
        const audioSession = actionBtn.dataset.session || '';
        const isListening = actionBtn.classList.contains('listening');

        // Optimistic UI update
        if (isListening) {
          actionBtn.classList.remove('listening');
          actionBtn.innerHTML = '🔇 Listen';
        } else {
          actionBtn.classList.add('listening');
          actionBtn.innerHTML = '🔊 Mute';
        }

        // Send to backend
        vscode.postMessage({
          type: isListening ? 'muteAudio' : 'unmuteAudio',
          sessionId: audioSession
        });
        break;
      }
      case 'quickJoin': {
        const quickJoinInput = document.getElementById('quickJoinUrl');
        const quickJoinModeRadio = document.querySelector('input[name="quickJoinMode"]:checked');
        const quickJoinMode = quickJoinModeRadio ? quickJoinModeRadio.value : 'notes';
        const quickJoinVideoCheckbox = document.getElementById('quickJoinVideo');
        const quickJoinVideoEnabled = quickJoinVideoCheckbox ? quickJoinVideoCheckbox.checked : false;

        if (quickJoinInput && quickJoinInput.value.trim()) {
          const quickJoinUrl = quickJoinInput.value.trim();
          log('Quick Join: ' + quickJoinUrl + ', mode: ' + quickJoinMode + ', video: ' + quickJoinVideoEnabled);
          vscode.postMessage({ type: 'joinMeetingNow', meetUrl: quickJoinUrl, title: 'Manual Join', mode: quickJoinMode, videoEnabled: quickJoinVideoEnabled });
          quickJoinInput.value = '';
        } else {
          log('Quick Join: No URL provided');
        }
        break;
      }

      // Service actions (Meet Bot controls)
      case 'serviceStart': {
        const service = actionBtn.dataset.service;
        if (service) {
          log('Service start: ' + service);
          vscode.postMessage({ type: 'serviceStart', service: service });
        }
        break;
      }
      case 'serviceStop': {
        const service = actionBtn.dataset.service;
        if (service) {
          log('Service stop: ' + service);
          vscode.postMessage({ type: 'serviceStop', service: service });
        }
        break;
      }
      case 'serviceLogs': {
        const service = actionBtn.dataset.service;
        if (service) {
          log('Service logs: ' + service);
          vscode.postMessage({ type: 'serviceLogs', service: service });
        }
        break;
      }
    }
    return;
  }

  // Handle quick test buttons for inference
  const quickTestBtn = target.closest('[data-quick-test]');
  if (quickTestBtn) {
    const testMsg = quickTestBtn.dataset.quickTest;
    const msgInput = document.getElementById('inferenceTestMessage');
    if (msgInput && testMsg) {
      msgInput.value = testMsg;
      // Trigger the inference test
      const testPersona = document.getElementById('inferenceTestPersona');
      const testSkill = document.getElementById('inferenceTestSkill');
      vscode.postMessage({
        command: 'runInferenceTest',
        message: testMsg,
        persona: testPersona ? testPersona.value : '',
        skill: testSkill ? testSkill.value : ''
      });
    }
    return;
  }

  // Handle running skill item clicks (open flowchart)
  // But not if clicking the clear button
  const runningSkillItem = target.closest('.running-skill-item');
  if (runningSkillItem && !target.closest('.clear-skill-btn')) {
    const executionId = runningSkillItem.dataset.executionId;
    if (executionId) {
      vscode.postMessage({ command: 'openRunningSkillFlowchart', executionId });
    }
    return;
  }

  // Handle skill item clicks (for selection)
  const skillItem = target.closest('.skill-item');
  if (skillItem) {
    const skillName = skillItem.dataset.skill;
    if (skillName) {
      vscode.postMessage({ command: 'loadSkill', skillName: skillName });
    }
    return;
  }

  // Handle skill view toggle buttons (Info/Workflow/YAML)
  const skillViewBtn = target.closest('.toggle-btn[data-view]');
  if (skillViewBtn) {
    const view = skillViewBtn.dataset.view;
    if (view) {
      vscode.postMessage({ command: 'setSkillView', view });
    }
    return;
  }

  // Handle workflow view mode toggle (Horizontal/Vertical)
  const workflowViewBtn = target.closest('.toggle-btn[data-workflow-view]');
  if (workflowViewBtn) {
    const mode = workflowViewBtn.dataset.workflowView;
    if (mode) {
      vscode.postMessage({ command: 'setWorkflowViewMode', mode });
    }
    return;
  }

  // Handle skill call badge clicks (navigate to called skill)
  const skillCallBadge = target.closest('.skill-call-badge');
  if (skillCallBadge) {
    const skillName = skillCallBadge.dataset.skill;
    if (skillName) {
      vscode.postMessage({ command: 'loadSkill', skillName });
    }
    return;
  }

  // Handle persona card clicks (for selection)
  const personaCard = target.closest('.persona-card');
  if (personaCard && target.tagName !== 'BUTTON') {
    const persona = personaCard.dataset.persona;
    if (persona) {
      vscode.postMessage({ command: 'selectPersona', persona });
    }
    return;
  }

  // Handle tool module item clicks (for selection)
  const toolModuleItem = target.closest('.tools-module-item');
  if (toolModuleItem) {
    const moduleName = toolModuleItem.dataset.module;
    if (moduleName) {
      vscode.postMessage({ command: 'selectToolModule', module: moduleName });
    }
    return;
  }

  // Handle tool item clicks (for selection)
  const toolItem = target.closest('.tool-item');
  if (toolItem) {
    const toolName = toolItem.dataset.tool;
    if (toolName) {
      vscode.postMessage({ command: 'selectTool', tool: toolName });
    }
    return;
  }

  // Handle memory category/tab clicks
  const memoryCategory = target.closest('.memory-category, .memory-tab[data-category]');
  if (memoryCategory) {
    const category = memoryCategory.dataset.category;
    if (category) {
      log('[base.js] Memory category clicked: ' + category);
      vscode.postMessage({ command: 'selectMemoryCategory', category });
    }
    return;
  }

  // Handle memory file clicks
  const memoryFile = target.closest('.memory-file');
  if (memoryFile) {
    const file = memoryFile.dataset.file;
    if (file) {
      vscode.postMessage({ command: 'selectMemoryFile', file });
    }
    return;
  }

  // Handle memory file edit button
  const editMemoryBtn = target.closest('[data-action="editMemoryFile"]');
  if (editMemoryBtn) {
    const file = editMemoryBtn.dataset.file;
    if (file) {
      vscode.postMessage({ command: 'editMemoryFile', file });
    }
    return;
  }

  // Handle collapsible section toggles
  const collapsibleTitle = target.closest('.collapsible .section-title');
  if (collapsibleTitle) {
    const section = collapsibleTitle.closest('.collapsible');
    if (section) {
      section.classList.toggle('collapsed');
    }
    return;
  }
});

// Handle input events for search boxes
document.addEventListener('input', function(e) {
  const target = e.target;

  if (target.id === 'sessionSearch') {
    vscode.postMessage({ command: 'searchSessions', query: target.value });
    return;
  }
  if (target.id === 'personaSearch') {
    vscode.postMessage({ command: 'searchPersonas', query: target.value });
    return;
  }
  if (target.id === 'skillSearch') {
    // Client-side filtering for skills
    const query = target.value.toLowerCase();
    document.querySelectorAll('.skill-item').forEach(function(item) {
      const nameEl = item.querySelector('.skill-item-name');
      const descEl = item.querySelector('.skill-item-desc');
      const name = nameEl ? nameEl.textContent.toLowerCase() : '';
      const desc = descEl ? descEl.textContent.toLowerCase() : '';
      // Also check the skill name from data attribute
      const skillName = (item.dataset.skill || '').toLowerCase();
      item.style.display = (name.includes(query) || desc.includes(query) || skillName.includes(query)) ? '' : 'none';
    });
    return;
  }
  if (target.id === 'toolSearch') {
    vscode.postMessage({ command: 'searchTools', query: target.value });
    return;
  }
});

// Handle change events for dropdowns and toggles
document.addEventListener('change', function(e) {
  const target = e.target;

  if (target.id === 'sessionGroupBy') {
    vscode.postMessage({ command: 'changeSessionGroupBy', value: target.value });
    return;
  }

  // Handle cron job toggle (checkbox with data-action="toggleCronJob")
  if (target.dataset && target.dataset.action === 'toggleCronJob') {
    const jobName = target.dataset.job;
    if (jobName) {
      vscode.postMessage({ command: 'toggleCronJob', jobName: jobName, enabled: target.checked });
    }
    return;
  }
});

console.log('[DEBUG] Event delegation initialized');
