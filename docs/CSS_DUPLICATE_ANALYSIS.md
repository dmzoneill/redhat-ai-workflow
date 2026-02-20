# CSS Duplicate & Competing Declarations Analysis

**File:** `extensions/aa_workflow_vscode/src/webview/styles/unified.css` (8844 lines)
**Analysis Date:** 2026-02-20

---

## 1. CONFLICTS (Same Selector, Same Property, Different Values)

These are **potential bugs** — the later rule wins in CSS cascade, which may not match intent.

### Critical: Hover Overrides Being Overridden

| Selector | Property | Line (wins) | Line (loses) | Issue |
|----------|----------|-------------|--------------|-------|
| `.session-card:hover` | `border-color` | 2128: `var(--border-hover)` | 910: `var(--accent)` | Session cards intended to show accent on hover, but generic `.card:hover` overrides |
| `.session-card:hover` | `box-shadow` | 2128: `var(--card-shadow-hover)` | 910: `0 4px 12px rgba(0,0,0,0.15)` | Same override issue |
| `.slack-dm-card:hover` | `border-color` | 2128: `var(--border-hover)` | 730: `var(--accent)` | Consolidation at 730 wanted accent; generic card group at 2128 overrides |
| `.vector-db-card:hover` | `border-color` | 2128: `var(--border-hover)` | 730: `var(--accent)` | Same as above |

**Fix:** Exclude `.session-card`, `.slack-dm-card`, `.vector-db-card` from the generic `.card:hover` group at 2128, or increase specificity of the accent rules at 730/910.

### Chip/Tag Gap Inconsistency

| Selector | Property | Line 1 | Line 2 |
|----------|----------|--------|--------|
| `.btn-tiny` | `gap` | 221: `4px` | 1411: `3px` |
| `.scoring-tag` | `gap` | 221: `4px` | 7925: `3px` |

Both appear in consolidation (221) and section-specific rules. Section wins. Decide which value is correct.

### Display Inconsistency

| Selector | Property | Line 1 | Line 2 |
|----------|----------|--------|--------|
| `.integration-path` | `display` | 221: `inline-flex` | 5798: `inline-block` |
| `.issue-link` | `display` | 221: `inline-flex` | 2415: `inline-block` |

### Card Overrides (Base vs Section-Specific)

These may be **intentional** — base card at 2090, section overrides later:

| Selector | Property | Base (2090) | Override |
|----------|----------|-------------|----------|
| `.active-meeting-card` | `background` | `var(--bg-card)` | 5375: `var(--bg-secondary)` |
| `.active-meeting-card` | `padding` | `16px` | 5375: `12px 16px` |
| `.inference-result-area` | `background` | `var(--bg-card)` | 4255: `var(--bg-secondary)` |
| `.meeting-item` | `padding` | `16px` | 5086: `12px` |
| `.meeting-item` | `transition` | `all 0.2s ease` | 5086: `all 0.2s` |
| `.note-item` | `padding` | `16px` | 5353: `10px` |
| `.note-item` | `transition` | `all 0.2s ease` | 5353: `all 0.2s` |
| `.perf-evidence-card` | `background` | `var(--bg-card)` | 7045: `var(--bg-tertiary)` |
| `.perf-evidence-card` | `border-radius` | `var(--radius-lg)` | 7045: `var(--radius-sm)` |
| `.perf-evidence-card` | `padding` | `16px` | 7045: `6px 8px` |
| `.perf-evidence-empty` | `padding` | 6170: `12px` | 7060: `8px 20px` |
| `.perf-evidence-list` | `gap` | 1773: `4px` | 6117: `2px` |
| `.perf-evidence-list` | `max-height` | 6117: `240px` | 7035: `400px` |
| `.progress-bar` | `height` | 1830: `6px` | 2393: `8px` |
| `.running-skill-progress-bar` | `height` | 1830: `6px` | 3707: `4px` |
| `.scoring-comp-card` | `border` | 2090: `1px solid var(--border)` | 7811: `1px solid var(--border-color)` |
| `.scoring-comp-card` | `border-radius` | 2090: `var(--radius-lg)` | 7811: `var(--radius)` |
| `.skill-info-card` | `background` | 2090: `var(--bg-card)` | 1238: `var(--bg-tertiary)` |
| `.slack-search-item` | `padding` | 2090: `16px` | 1142: `12px` |
| `.stat-card` | `padding` | 2090: `16px` | 2173: `24px 20px` |
| `.tool-request-card` | `padding` | 2090: `16px` | 753: `12px` |

---

## 2. REDUNDANCIES (Same Property, Same Value — Can Remove from Later)

Remove the redundant property from the **later** definition to reduce file size and avoid confusion.

### Duplicate in Same Rule (Source Bug)

| Line | Selector | Issue |
|------|----------|-------|
| 630 | `.collapsible.collapsed .section-content` | Listed **twice** in the same comma-separated selector list |
| 802 | `.collapsible .section-title` | Listed **twice** in the same comma-separated selector list |

**Fix:** Remove the duplicate from the selector list.

### Consolidation + Section (Remove from Section)

| Selector | Property | Value | Lines |
|----------|----------|-------|-------|
| `.placeholder-text` | `font-size` | `var(--text-md)` | 704, 2578 |
| `.memory-files-empty` | `padding` | `20px` | 266, 3949 |
| `.activity-line.visible` | `opacity` | `1` | 725, 1916 |
| `.collapsible.collapsed .collapse-icon` | `transform` | `rotate(-90deg)` | 2390, 4083 |
| `.progress-bar` | `background` | `var(--bg-tertiary)` | 1830, 2393 |
| `.perf-evidence-empty` | `color` | `var(--text-muted)` | 6170, 7060 |
| `.perf-evidence-empty` | `font-size` | `var(--text-sm)` | 6170, 7060 |
| `.perf-evidence-list` | `display` | `flex` | 1773, 6117 |
| `.perf-evidence-list` | `flex-direction` | `column` | 1773, 6117 |
| `.perf-evidence-list` | `overflow-y` | `auto` | 6117, 7035 |
| `.tools-sidebar` | `min-width` | `260px` | 3248, 3764 |
| `.tools-sidebar` | `overflow-y` | `auto` | 3248, 3764 |
| `.tools-sidebar` | `width` | `260px` | 3248, 3764 |

### Shared Header Pattern (Many selectors in consolidation block 1668–1702)

These selectors appear in a **consolidation block** (lines 1668–1702) that groups many header-like elements. The same properties are also set in section-specific rules. Remove from section-specific rules:

- `.context-source-card .card-header` — align-items, display, gap (1135, 1702)
- `.cron-history-header` — align-items, display, gap (595, 1702)
- `.cron-job-details` — align-items, display, gap (595, 1702)
- `.fix-header` — align-items, display, justify-content (710, 1668)
- `.inference-ollama-header` — align-items, display, justify-content (745, 1668)
- `.live-captions-title` — align-items, display, gap (1075, 1702)
- `.pattern-header` — align-items, display, justify-content (710, 1668)
- `.running-skills-title` — align-items, display, gap (1031, 1702)
- `.service-header` — align-items, display, justify-content (889, 1668)
- `.session-header` — align-items, display, justify-content (1311, 1668)
- `.slack-search-header` — align-items, display, gap (1245, 1702)
- `.slack-thread-reply-header` — align-items, display, gap (1124, 1702)
- `.tool-item-header` — align-items, display, justify-content (710, 1668)
- `.vector-db-header` — align-items, display, justify-content (745, 1668)
- `.video-preview-header` — align-items, display, justify-content (1161, 1668)

### Card Base Properties (Remove from section if inheriting from base)

- `.history-item-header` — display, flex-direction, gap (1150, 1773)
- `.slack-search-item` — background, border, border-radius (1142, 2090)
- `.stat-card:hover` — border-color, box-shadow (1323, 2128)
- `.tool-request-card` — background, border, border-radius (753, 2090)
- `.skill-info-card` — border-radius, padding (1238, 2090)
- `.scoring-tag` — align-items, display (221, 7925)

---

## 3. SPLIT DEFINITIONS (Consolidation ≤700 AND Section >700)

These selectors are defined in both the consolidation block (lines 1–700) and in section-specific rules. Consider merging or documenting the split.

| Selector | Consolidation Line | Section Line(s) |
|----------|-------------------|-----------------|
| `.no-meeting` | 213 | 5286 |
| `.empty-state` (with .no-meeting) | 213 | — |
| `.btn-tiny` | 221 | 1411 |
| `.issue-badge` | 221 | 2312 |
| `.issue-link` | 221 | 2415 |
| `.create-context-meta` | 221 | 2994 |
| `.integration-path` | 221 | 5798 |
| `.scoring-tag` | 221 | 7925 |
| `.tool-param-type` | 221 | 3872 |
| `.card-header` | 238 | 2145 |
| `.item` | 238 | 2229 |
| `.create-ralph-toggle` | 238 | 3018 |
| `.running-skill-item` | 238 | 3691 |
| `.skill-input-item` | 238 | 3317 |
| `.slack-command-item` | 238 | 4458 |
| `.slack-user-item` | 238 | 4483 |
| `.sprint-section-header` | 238 | 4831 |
| `.active-meeting-panel` | 254 | 5164 |
| `.bot-controls-bar` | 254 | 4665 |
| `.inference-result-area` | 254 | 4255 |
| `.trace-viewer` | 254 | 4913 |
| `.memory-files-empty` | 266 | 3949 |
| `.context-sources-grid` | 275 | 2618 |
| `.persona-cards-grid` | 275 | 3167 |
| `.controls` | 295 | 2072 |
| `.input-label` | 283 | 2569 |
| `.create-token-count` | 283 | 4548 |
| `.cron-job-item` | 369 | 2090 |
| `.slack-dm-card` | 686 | 2090 |
| `.memory-file-name` | 307 | 3962 |
| `.tools-module-name` | 307 | 3793 |
| `.trace-viewer .trace-header` | 238 | 4917 |
| `.mindmap-header-controls` | 295 | 7370 |
| `.mindmap-toggles .toggle-label` | 283 | 7406 |
| `.options-row .option-label` | 283 | 2727 |
| `.physics-control label` | 479 | 7469 |
| `.quick-tests` | 295 | 4260 |

---

## Summary

| Category | Count |
|----------|-------|
| **Conflicts (bugs)** | 4 critical (hover overrides), ~25 total |
| **Redundancies** | 2 in-rule duplicates, ~50 cross-rule |
| **Split definitions** | 38 selectors |

### Recommended Actions

1. **Immediate:** Fix hover override bug — exclude `.session-card`, `.slack-dm-card`, `.vector-db-card` from the generic `.card:hover` group at 2128.
2. **Quick wins:** Remove duplicate selectors at lines 630 and 802.
3. **Cleanup:** Remove redundant properties from section-specific rules where consolidation already defines them.
4. **Review:** Decide intended values for `.btn-tiny`/`.scoring-tag` gap, `.integration-path`/`.issue-link` display.
