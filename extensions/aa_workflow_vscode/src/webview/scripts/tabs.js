/**
 * Tab Navigation JavaScript
 *
 * Handles main tab switching and sub-tab navigation.
 */

// Current active tab
let currentTab = 'overview';

/**
 * Switch to a specific tab.
 */
function switchTab(tabId) {
  currentTab = tabId;

  // Update tab buttons
  document.querySelectorAll('.tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.tab === tabId);
  });

  // Update tab content
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.toggle('active', content.id === tabId);
  });

  // Notify extension of tab change
  sendMessage('switchTab', { tab: tabId });

  console.log('[Tabs] Switched to tab:', tabId);
}

/**
 * Switch to a sub-tab within a tab.
 */
function switchSubtab(parentSelector, subtabId) {
  const parent = document.querySelector(parentSelector);
  if (!parent) return;

  // Update sub-tab buttons
  parent.querySelectorAll('.subtab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.subtab === subtabId);
  });

  // Update sub-tab content
  parent.querySelectorAll('.subtab-content').forEach(content => {
    content.classList.toggle('active', content.id === subtabId || content.dataset.subtab === subtabId);
  });

  console.log('[Tabs] Switched to subtab:', subtabId);
}

/**
 * Initialize tab click handlers.
 */
function initTabs() {
  // Main tabs
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const tabId = tab.dataset.tab;
      if (tabId) switchTab(tabId);
    });
  });

  // Sub-tabs
  document.querySelectorAll('.subtab').forEach(tab => {
    tab.addEventListener('click', () => {
      const subtabId = tab.dataset.subtab;
      const parent = tab.closest('.subtabs')?.parentElement;
      if (subtabId && parent) {
        switchSubtab('#' + parent.id, subtabId);
      }
    });
  });
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initTabs);
} else {
  initTabs();
}
