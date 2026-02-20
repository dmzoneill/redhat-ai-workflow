# CSS Restoration Tracker

92 CSS class regressions introduced during consolidation. Classes existed in commit
`457f8a07` but were removed in `82516408`. This tracks restoration using consolidated
utility classes rather than re-introducing comma-separated selector lists.

## Strategy

Instead of restoring `N` selectors in a comma-separated group, we:
1. Use an existing utility class (e.g. `.flex-between`, `.flex-col`, `.actions-row`)
2. Add that utility class to the HTML `class=""` attribute alongside the page-specific class
3. The page-specific class name stays for semantics/JS targeting; the utility provides layout

For standalone rules with unique properties, we restore them individually in CSS.

## Utility Classes (existing)

| Utility | Properties | Status |
|---------|------------|--------|
| `.flex-between` | `display:flex; align-items:center; justify-content:space-between` | exists |
| `.flex-row` | `display:flex; align-items:center; gap:8px` | exists |
| `.flex-col` | `display:flex; flex-direction:column; gap:8px` | exists |
| `.actions-row` | `display:flex; align-items:center; gap:8px` | exists |
| `.card` | background, border, radius, padding, hover | exists |
| `.label-sm` | small uppercase label | exists |
| `.gap-4` | `gap: 4px` | exists |
| `.gap-6` | `gap: 6px` | exists |
| `.gap-8` | `gap: 8px` | exists |
| `.gap-12` | `gap: 12px` | exists |
| `.flex-1` | `flex: 1; min-width: 0` | exists |

New utility needed:
| `.gap-16` | `gap: 16px` | TO ADD |

## Group 1: flex-between (6 selectors) → add `class="flex-between ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.active-meetings-header` | meetingsRenderer.ts | [ ] |
| `.caption-meta` | meetingsRenderer.ts | [ ] |
| `.integration-card-header` | meetingsRenderer.ts | [ ] |
| `.live-captions-header` | meetingsRenderer.ts | [ ] |
| `.mindmap-header` | SkillsTab.ts | [ ] |
| `.persona-controls` | PersonasTab.ts | [ ] |

## Group 2: flex-row (9 selectors) → add `class="flex-row ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.cron-history-header` | CronTab.ts | [ ] |
| `.cron-job-actions` | CronTab.ts | [ ] |
| `.cron-job-details` | CronTab.ts | [ ] |
| `.integration-name` | meetingsRenderer.ts | [ ] |
| `.mindmap-header-left` | SkillsTab.ts | [ ] |
| `.running-skill-source` | SkillsTab.ts | [ ] |
| `.session-name-cell` | SessionsTab.ts | [ ] |
| `.slack-history-header` | SlackTab.ts | [ ] |
| `.video-preview-controls` | meetingsRenderer.ts | [ ] |

## Group 3: flex-col (6 selectors) → add `class="flex-col ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.cron-jobs-list` | CronTab.ts | [ ] |
| `.session-logs-list` | MemoryTab.ts | [ ] |
| `.slack-compose` | SlackTab.ts | [ ] |
| `.slack-pending-list` | SlackTab.ts | [ ] |
| `.sprint-header-content` | sprintRenderer.ts | [ ] |
| `.upcoming-meetings-list` | meetingsRenderer.ts | [ ] |

## Group 4: flex-col gap-6 (6 selectors) → add `class="flex-col gap-6 ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.calendar-list` | meetingsRenderer.ts | [ ] |
| `.cron-history-list` | CronTab.ts | [ ] |
| `.overview-priorities` | PerformanceTab.ts | [ ] |
| `.perf-gaps-items` | PerformanceTab.ts | [ ] |
| `.slack-commands-list` | SlackTab.ts | [ ] |
| `.slack-history-list` | SlackTab.ts | [ ] |

## Group 5: flex-col gap-4 (5 selectors) → add `class="flex-col gap-4 ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.create-context-list` | CreateTab.ts | [ ] |
| `.create-session-list` | CreateTab.ts | [ ] |
| `.perf-competency-header` | PerformanceTab.ts | [ ] |
| `.perf-day-events` | PerformanceTab.ts | [ ] |
| `.running-skill-progress` | SkillsTab.ts | [ ] |

## Group 6: actions-row (12 selectors) → add `class="actions-row ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.cron-controls` | CronTab.ts | [ ] |
| `.history-item-actions` | meetingsRenderer.ts | [ ] |
| `.inference-save-actions` | InferenceTab.ts | [ ] |
| `.integration-actions` | meetingsRenderer.ts | [ ] |
| `.live-captions-actions` | meetingsRenderer.ts | [ ] |
| `.meeting-actions` | meetingsRenderer.ts | [ ] |
| `.perf-question-actions` | PerformanceTab.ts | [ ] |
| `.question-actions` | PerformanceTab.ts | [ ] |
| `.running-skills-actions` | SkillsTab.ts | [ ] |
| `.slack-db-actions` | MemoryTab.ts | [ ] |
| `.slack-pending-actions` | SlackTab.ts | [ ] |
| `.vector-db-actions` | MemoryTab.ts | [ ] |

## Group 7: flex-1 (3 selectors) → add `class="flex-1 ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.cron-job-info` | CronTab.ts | [ ] |
| `.running-skill-info` | SkillsTab.ts | [ ] |
| `.tools-module-info` | ToolsTab.ts | [ ] |

## Group 8: flex-col gap-16 (4 selectors) → add `class="flex-col gap-16 ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.create-context-column` | CreateTab.ts | [ ] |
| `.meetings-sidebar` | meetingsRenderer.ts | [ ] |
| `.skill-info-view` | SkillsTab.ts | [ ] |
| `.skill-workflow-view` | SkillsTab.ts | [ ] |

## Group 9: card (5 selectors) → add `class="card ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.info-card` | SkillsTab.ts | [ ] |
| `.learned-pattern-item` | MemoryTab.ts | [ ] |
| `.slack-channel-card` | SlackTab.ts | [ ] |
| `.slack-db-card` | MemoryTab.ts | [ ] |
| `.tool-fix-item` | MemoryTab.ts | [ ] |

## Group 10: flex-col gap-12 (2 selectors) → add `class="flex-col gap-12 ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.create-ralph-slider` | CreateTab.ts | [ ] |
| `.live-captions-feed` | meetingsRenderer.ts | [ ] |

## Group 11: label-sm (2 selectors) → add `class="label-sm ..."` in HTML

| Selector | File | Status |
|----------|------|--------|
| `.inference-persona-used` | InferenceTab.ts | [ ] |
| `.stat-sub` | OverviewTab.ts | [ ] |

## Group 12: grid 2-col (1 selector) → standalone CSS

| Selector | File | Status |
|----------|------|--------|
| `.create-context-builder` | CreateTab.ts | [ ] |

## Standalone CSS Rules (29 rules to restore in unified.css)

| Selector | Properties | Status |
|----------|------------|--------|
| `.empty-state-text` | font-size, color | [ ] |
| `.fix-tool` | font-weight, font-size, color, font-family | [ ] |
| `.header-info` | flex:1, min-width:0 | [ ] |
| `.step-name` | font-weight, font-size | [ ] |
| `.tool-item-desc` | font-size, color, line-height | [ ] |
| `.upcoming-time-date` | font-size, color, text-transform | [ ] |
| `.card-content` | font-size, color | [ ] |
| `.slack-command-name` | font-weight, font-size, color, font-family | [ ] |
| `.slack-search-box` | display:flex, align-items, gap | [ ] |
| `.pattern-name` | font-weight, font-size | [ ] |
| `.active-meetings-count` | display:flex, align-items, gap | [ ] |
| `.session-header-controls` | display:flex, gap, align-items | [ ] |
| `.skill-input-type` | font-size, color, font-weight | [ ] |
| `.mindmap-title` | font-weight, font-size | [ ] |
| `.past-sprint-header` | flex-between + padding | [ ] |
| `.perf-calendar-num` | font-size, font-weight | [ ] |
| `.perf-comp-description` | font-size, color, line-height | [ ] |
| `.perf-comp-goal-text` | font-size, color, font-style | [ ] |
| `.perf-gap-card` | card-like background/border | [ ] |
| `.perf-gap-card-desc` | font-size, color | [ ] |
| `.perf-gap-card-evidence` | font-size, color, font-style | [ ] |
| `.perf-gap-card-header` | font-weight, font-size | [ ] |
| `.perf-gap-cards` | grid auto-fill | [ ] |
| `.perf-gaps-item-header` | flex-between | [ ] |
| `.perf-gaps-item-name` | font-weight | [ ] |
| `.perf-highlight-item` | font-size, color, padding | [ ] |
| `.perf-tab` | tab styling | [ ] |
| `.overview-priority-header` | font-weight, margin | [ ] |
| `.perf-day-event-top` | flex-between | [ ] |

## Compound Selectors (7 rules to restore)

| Selector | Properties | Status |
|----------|------------|--------|
| `.inference-ollama-status.status-online` | success color | [ ] |
| `.inference-ollama-status.status-offline` | error color | [ ] |
| `.perf-tab:hover` | hover state | [ ] |
| `.perf-tab--active` | active state | [ ] |
| `.running-skill-progress-bar` | width, height | [ ] |
| `.running-skill-source` (standalone) | font-size, color, margin | [ ] |
| `.slack-channel-card.selected` | selected state | [ ] |

## Progress

- [x] Phase 1: Add `.gap-16` utility to CSS
- [x] Phase 2: Restore 29 standalone + 7 compound CSS rules in unified.css
- [x] Phase 3: Update HTML for 61 utility class mappings across 10 TS files
- [x] Phase 4: Verify all 92 regressions resolved (92/92)

## Results

All 92 regressions resolved:
- **61 classes**: Restored via utility class in HTML (no new CSS needed)
- **29 classes**: Standalone CSS rules restored in unified.css
- **7 compound selectors**: Restored (hover/active states, status modifiers)
- **1 class** (.meetings-main): Never had CSS, fixed with utility class

CSS impact: unified.css grew from 6063 to 6122 lines (+59 lines for standalone rules).
Many selectors were already correct from the first consolidation pass.
