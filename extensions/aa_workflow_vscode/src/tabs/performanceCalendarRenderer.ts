/**
 * Calendar tab renderer for Performance panel.
 * Extracted from PerformanceTab.ts renderCalendarTab and related methods.
 */

import type { PerformanceState, CapturedDay } from "./performanceTypes";
import { PILLAR_DEFS } from "./performanceConfig";

export interface CalendarHelpers {
  escapeHtml(s: string): string;
  getEmptyStateHtml(icon: string, msg: string): string;
  safeText(s: string): string;
  formatCompetencyName(id: string): string;
  renderIssueLink(key: string): string;
  renderIssueLinks(keys: string[]): string;
}

function getMonthDays(state: PerformanceState): CapturedDay[] {
  const m = state.calendar_month;
  const y = state.calendar_year;
  const prefix = `${y}-${String(m + 1).padStart(2, "0")}-`;
  return state.captured_days.filter((d) => d.date.startsWith(prefix));
}

function renderMonthlyTrend(state: PerformanceState): string {
  const monthDays = getMonthDays(state);
  if (monthDays.length < 2) return "";

  const sorted = [...monthDays].sort((a, b) => a.date.localeCompare(b.date));
  const pillars = Object.keys(PILLAR_DEFS);
  const maxPts = Math.max(...sorted.map((d) => d.total_points), 1);

  const w = 600,
    h = 70,
    padX = 4,
    padY = 4;
  const plotW = w - padX * 2;
  const plotH = h - padY * 2;
  const n = sorted.length;

  const pillarPaths: string[] = [];
  for (const pn of pillars) {
    const color = PILLAR_DEFS[pn].color;
    const pts: string[] = [];
    for (let i = 0; i < n; i++) {
      const x = padX + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
      const v = sorted[i].category_points?.[pn] || 0;
      const y2 = padY + plotH - (v / maxPts) * plotH;
      pts.push(`${x.toFixed(1)},${y2.toFixed(1)}`);
    }
    pillarPaths.push(
      `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.85"/>`,
    );
  }

  const totalPts: string[] = [];
  const dotsSvg: string[] = [];
  for (let i = 0; i < n; i++) {
    const x = padX + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2);
    const y2 = padY + plotH - (sorted[i].total_points / maxPts) * plotH;
    totalPts.push(`${x.toFixed(1)},${y2.toFixed(1)}`);
    const dayNum = parseInt(sorted[i].date.split("-")[2], 10);
    dotsSvg.push(
      `<circle cx="${x.toFixed(1)}" cy="${y2.toFixed(1)}" r="2.5" fill="var(--vscode-foreground, #ccc)" opacity="0.6"><title>${dayNum}: ${sorted[i].total_points}pts</title></circle>`,
    );
  }

  const gridLines: string[] = [];
  for (let g = 0; g <= 2; g++) {
    const gy = padY + (g / 2) * plotH;
    gridLines.push(
      `<line x1="${padX}" y1="${gy.toFixed(1)}" x2="${w - padX}" y2="${gy.toFixed(1)}" stroke="var(--vscode-widget-border, #333)" stroke-width="0.5" opacity="0.3"/>`,
    );
  }

  const legend = pillars
    .map(
      (pn) =>
        `<span class="cal-trend-legend-item"><span class="cal-trend-legend-swatch" style="background:${PILLAR_DEFS[pn].color}"></span>${pn.split(" ")[0]}</span>`,
    )
    .join("");

  return `
    <div class="cal-trend-wrap">
      <div class="cal-trend-header">
        <span class="cal-trend-title">Daily Trend</span>
        <div class="cal-trend-legend">${legend}</div>
      </div>
      <svg class="cal-trend-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        ${gridLines.join("")}
        ${pillarPaths.join("")}
        <polyline points="${totalPts.join(" ")}" fill="none" stroke="var(--vscode-foreground, #ccc)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.5" stroke-dasharray="4,3"/>
        ${dotsSvg.join("")}
      </svg>
    </div>
  `;
}

function renderCalendar(state: PerformanceState, helpers: CalendarHelpers): string {
  const month = state.calendar_month;
  const year = state.calendar_year;

  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];

  const capturedSet = new Map<string, CapturedDay>();
  for (const day of state.captured_days) {
    capturedSet.set(day.date, day);
  }

  const currentQuarter = Math.floor(month / 3);
  const quarterStartMonth = currentQuarter * 3;
  const quarterEndMonth = quarterStartMonth + 2;

  const canGoPrev = month > quarterStartMonth;
  const canGoNext = month < quarterEndMonth;

  const firstDay = new Date(year, month, 1);
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const startWeekday = firstDay.getDay();

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  let html = `
    <div class="perf-calendar">
      <div class="perf-calendar-nav">
        <button class="btn btn-xs ${canGoPrev ? "" : "disabled"}" data-action="prevMonth" ${canGoPrev ? "" : "disabled"}>&#9664;</button>
        <span class="perf-calendar-month">${monthNames[month]} ${year}</span>
        <button class="btn btn-xs ${canGoNext ? "" : "disabled"}" data-action="nextMonth" ${canGoNext ? "" : "disabled"}>&#9654;</button>
      </div>
      <div class="perf-calendar-grid">
        <div class="perf-calendar-header">Mon</div>
        <div class="perf-calendar-header">Tue</div>
        <div class="perf-calendar-header">Wed</div>
        <div class="perf-calendar-header">Thu</div>
        <div class="perf-calendar-header">Fri</div>
  `;

  const mondayOffset = startWeekday === 0 ? 6 : startWeekday - 1;
  for (let i = 0; i < Math.min(mondayOffset, 5); i++) {
    html += `<div class="perf-calendar-day empty"></div>`;
  }

  for (let d = 1; d <= daysInMonth; d++) {
    const dateObj = new Date(year, month, d);
    const weekday = dateObj.getDay();
    if (weekday === 0 || weekday === 6) continue;

    const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
    const captured = capturedSet.get(dateStr);
    const isToday = dateStr === todayStr;
    const isFuture = dateObj > today;
    const isSelected = dateStr === state.selected_date;

    let classes = "perf-calendar-day";
    if (captured) classes += " captured";
    else if (!isFuture) classes += " missing";
    if (isToday) classes += " today";
    if (isFuture) classes += " future";
    if (isSelected) classes += " selected";

    const dot = captured
      ? `<span class="perf-calendar-dot captured"></span>`
      : !isFuture
        ? `<span class="perf-calendar-dot missing"></span>`
        : "";

    let eventInfo = "";
    if (captured) {
      const cp = captured.category_points || {};
      const catVals = Object.keys(PILLAR_DEFS).map((k) => cp[k] || 0);
      const maxCat = Math.max(...catVals, 1);
      const calBars = Object.entries(PILLAR_DEFS)
        .map(([pn, pd]) => {
          const v = cp[pn] || 0;
          return `<div class="perf-cal-cat-bar" title="${helpers.escapeHtml(pn)}: ${v}pts" style="height:${Math.round((v / maxCat) * 12)}px; background:${pd.color};"></div>`;
        })
        .join("");
      eventInfo = `
        <div class="perf-cal-cats">${calBars}</div>
        <span class="perf-calendar-events">${captured.total_points}pts</span>
      `;
    }

    html += `
      <div class="${classes}" data-action="selectDay" data-date="${dateStr}">
        <span class="perf-calendar-num">${d}</span>
        ${dot}
        ${eventInfo}
      </div>
    `;
  }

  html += `</div></div>`;
  return html;
}

function renderMonthlyDonut(state: PerformanceState, helpers: CalendarHelpers): string {
  const monthDays = getMonthDays(state);
  if (monthDays.length === 0) return "";

  const pillars = Object.keys(PILLAR_DEFS);
  const sums: Record<string, number> = {};
  let grandTotal = 0;
  for (const pn of pillars) sums[pn] = 0;
  for (const day of monthDays) {
    for (const pn of pillars) {
      const v = day.category_points?.[pn] || 0;
      sums[pn] += v;
      grandTotal += v;
    }
  }
  if (grandTotal === 0) return "";

  const size = 200;
  const cx = size / 2,
    cy = size / 2;
  const outerR = 90,
    innerR = 58;
  const avgPerDay = Math.round(grandTotal / monthDays.length);

  let svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" xmlns="http://www.w3.org/2000/svg">`;
  let startAngle = -Math.PI / 2;

  for (const pn of pillars) {
    const v = sums[pn];
    if (v === 0) continue;
    const sliceAngle = (v / grandTotal) * 2 * Math.PI;
    const endAngle = startAngle + sliceAngle;
    const largeArc = sliceAngle > Math.PI ? 1 : 0;

    const x1o = cx + outerR * Math.cos(startAngle);
    const y1o = cy + outerR * Math.sin(startAngle);
    const x2o = cx + outerR * Math.cos(endAngle);
    const y2o = cy + outerR * Math.sin(endAngle);
    const x1i = cx + innerR * Math.cos(endAngle);
    const y1i = cy + innerR * Math.sin(endAngle);
    const x2i = cx + innerR * Math.cos(startAngle);
    const y2i = cy + innerR * Math.sin(startAngle);

    const color = PILLAR_DEFS[pn].color;
    const d = `M ${x1o.toFixed(1)} ${y1o.toFixed(1)} A ${outerR} ${outerR} 0 ${largeArc} 1 ${x2o.toFixed(1)} ${y2o.toFixed(1)} L ${x1i.toFixed(1)} ${y1i.toFixed(1)} A ${innerR} ${innerR} 0 ${largeArc} 0 ${x2i.toFixed(1)} ${y2i.toFixed(1)} Z`;
    svg += `<path d="${d}" fill="${color}" opacity="0.85"><title>${helpers.escapeHtml(pn)}: ${v}pts (${Math.round((v / grandTotal) * 100)}%)</title></path>`;
    startAngle = endAngle;
  }

  svg += `<text x="${cx}" y="${cy - 6}" text-anchor="middle" fill="var(--vscode-foreground, #ccc)" font-size="26" font-weight="800">${avgPerDay}</text>`;
  svg += `<text x="${cx}" y="${cy + 14}" text-anchor="middle" fill="var(--vscode-descriptionForeground, #888)" font-size="12">avg/day</text>`;
  svg += `</svg>`;

  const legendItems = pillars
    .map(
      (pn) => `
    <div class="cal-donut-legend-item">
      <span class="cal-donut-legend-dot" style="background:${PILLAR_DEFS[pn].color}"></span>
      <span>${pn}</span>
      <span class="cal-donut-legend-pts">${sums[pn]}</span>
    </div>`,
    )
    .join("");

  return `
    <div class="cal-donut-panel">
      <div class="cal-donut-container">${svg}</div>
      <div class="cal-donut-legend">${legendItems}</div>
    </div>
  `;
}

function renderDayOfWeekHeatmap(state: PerformanceState, helpers: CalendarHelpers): string {
  const monthDays = getMonthDays(state);
  if (monthDays.length === 0) return "";

  const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri"];
  const pillars = Object.keys(PILLAR_DEFS);
  const buckets: { total: number; count: number; cats: Record<string, number> }[] = Array.from(
    { length: 5 },
    () => ({ total: 0, count: 0, cats: {} }),
  );

  for (const pn of pillars) {
    for (const b of buckets) b.cats[pn] = 0;
  }

  for (const day of monthDays) {
    const dateObj = new Date(day.date + "T12:00:00");
    const wd = dateObj.getDay();
    if (wd === 0 || wd === 6) continue;
    const idx = wd - 1;
    buckets[idx].total += day.total_points;
    buckets[idx].count += 1;
    for (const pn of pillars) {
      buckets[idx].cats[pn] += day.category_points?.[pn] || 0;
    }
  }

  const avgs = buckets.map((b) => (b.count > 0 ? Math.round(b.total / b.count) : 0));
  const maxAvg = Math.max(...avgs, 1);

  const cells = dayNames
    .map((name, i) => {
      const avg = avgs[i];
      const count = buckets[i].count;
      const intensity = avg / maxAvg;
      const bgAlpha = (0.08 + intensity * 0.25).toFixed(2);
      const textColor = intensity > 0.6 ? "var(--text-primary)" : "var(--text-secondary)";

      const catMax = Math.max(...pillars.map((pn) => buckets[i].cats[pn] || 0), 1);
      const bars = pillars
        .map((pn) => {
          const v = count > 0 ? Math.round(buckets[i].cats[pn] / count) : 0;
          return `<div class="cal-dow-bar" style="height:${Math.round((v / catMax) * 14)}px; background:${PILLAR_DEFS[pn].color};" title="${helpers.escapeHtml(pn)}: ${v}"></div>`;
        })
        .join("");

      return `
        <div class="cal-dow-cell" style="background:rgba(255,255,255,${bgAlpha}); color:${textColor};">
          <span class="cal-dow-label">${name}</span>
          <span class="cal-dow-value">${avg}</span>
          <span class="cal-dow-sub">${count} day${count !== 1 ? "s" : ""}</span>
          <div class="cal-dow-bars">${bars}</div>
        </div>
      `;
    })
    .join("");

  return `
    <div class="cal-dow-strip">${cells}</div>
  `;
}

function renderDayDetail(state: PerformanceState, helpers: CalendarHelpers): string {
  if (!state.selected_date) return "";

  const day = state.captured_days.find((d) => d.date === state.selected_date);
  const detail = state.day_detail;

  if (!day) {
    return `
      <div class="section perf-day-detail">
        <div class="section-title">
          <span>${state.selected_date}</span>
          <button class="btn btn-xs" data-action="closeDay">Close</button>
        </div>
        <div class="empty-state">
          <div class="empty-state-icon">--</div>
          <div class="empty-state-text">No data captured for this day.</div>
        </div>
      </div>
    `;
  }

  const cp = detail?.category_points || day.category_points || {};
  const catBreakdown = Object.entries(PILLAR_DEFS)
    .map(([pn, pd]) => {
      const v = cp[pn] || 0;
      return `<div class="perf-day-cat"><span class="perf-day-cat-dot" style="background:${pd.color};"></span> ${helpers.escapeHtml(pn)} ${v}pts</div>`;
    })
    .join("\n          ");

  let html = `
    <div class="section perf-day-detail">
      <div class="section-title">
        <span>${state.selected_date}</span>
        <button class="btn btn-xs" data-action="closeDay">Close</button>
      </div>
      <div class="perf-day-stats">
        <div class="perf-day-stat">
          <span class="perf-day-stat-value">${day.event_count}</span>
          <span class="perf-day-stat-label">Events</span>
        </div>
        <div class="perf-day-stat">
          <span class="perf-day-stat-value">${day.total_points}</span>
          <span class="perf-day-stat-label">Points</span>
        </div>
        <div class="perf-day-stat">
          <span class="perf-day-stat-value">${day.sources.join(", ") || "none"}</span>
          <span class="perf-day-stat-label">Sources</span>
        </div>
      </div>
      <div class="perf-day-categories">
        ${catBreakdown}
      </div>
  `;

  if (detail && detail.has_data && detail.events.length > 0) {
    html += `<div class="flex-col gap-4 perf-day-events">`;
    for (const ev of detail.events) {
      const pts = Object.values(ev.points || {}).reduce((a: number, b: number) => a + b, 0);

      let lineageHtml = "";
      if (ev.lineage && ev.lineage.length > 0) {
        const crumbs: string[] = [];
        for (const lin of ev.lineage) {
          const parts: string[] = [];
          if (lin.anstrat) {
            parts.push(
              `<a class="perf-issue-link perf-lineage-anstrat" href="#" data-action="openIssue" data-key="${helpers.escapeHtml(lin.anstrat.key)}" title="${helpers.safeText(lin.anstrat.summary)}">${helpers.escapeHtml(lin.anstrat.key)}</a>`,
            );
          }
          if (lin.epic) {
            parts.push(
              `<a class="perf-issue-link perf-lineage-epic" href="#" data-action="openIssue" data-key="${helpers.escapeHtml(lin.epic.key)}" title="${helpers.safeText(lin.epic.summary)}">${helpers.escapeHtml(lin.epic.key)}</a>`,
            );
          }
          parts.push(
            `<a class="perf-issue-link" href="#" data-action="openIssue" data-key="${helpers.escapeHtml(lin.key)}" title="${helpers.safeText(lin.summary)}">${helpers.escapeHtml(lin.key)}</a>`,
          );
          crumbs.push(parts.join(`<span class="perf-lineage-sep">\u203A</span>`));
        }
        lineageHtml = `<div class="perf-event-lineage">${crumbs.join(" ")}</div>`;
      } else {
        const issueLinks = helpers.renderIssueLinks(ev.issue_keys || []);
        if (issueLinks) lineageHtml = `<div class="perf-event-lineage">${issueLinks}</div>`;
      }

      html += `
        <div class="card perf-day-event-card">
          <div class="perf-day-event-top">
            <span class="perf-source-badge perf-source-${helpers.escapeHtml(ev.source)}">${helpers.escapeHtml(ev.source)}</span>
            <span class="text-muted-sm perf-day-event-type">${helpers.escapeHtml(ev.type)}</span>
            <span class="perf-day-event-pts">${pts}pts</span>
          </div>
          <div class="perf-day-event-title">${helpers.safeText(ev.title)}</div>
          ${lineageHtml}
        </div>
      `;
    }
    html += `</div>`;
  } else if (detail === null) {
    html += `<div class="perf-loading-hint">Loading event details...</div>`;
  }

  html += `</div>`;
  return html;
}

function renderCalendarInsights(state: PerformanceState, helpers: CalendarHelpers): string {
  const insights = state.ai_calendar_insights;
  if (!insights) return "";

  let html = "";
  if (insights.patterns.length > 0 || insights.forecast) {
    html += `<div class="section"><div class="section-title">AI Insights</div>`;
    if (insights.forecast) {
      const fc = insights.forecast;
      const fcClass = fc.projected_pct >= 80 ? "positive" : fc.projected_pct >= 60 ? "neutral" : "negative";
      html += `<div class="ai-forecast"><span class="ai-trend-badge ${fcClass}">Coverage forecast: ${fc.projected_pct}%</span> <span class="text-secondary text-sm">${fc.remaining_weekdays} weekdays remaining</span></div>`;
    }
    for (const p of insights.patterns) {
      const cls = p.severity === "positive" ? "positive" : p.severity === "warning" ? "negative" : "neutral";
      html += `<div class="ai-pattern-item ${cls}">${helpers.escapeHtml(p.message)}</div>`;
    }
    html += `</div>`;
  }
  return html;
}

export function getCalendarContent(state: PerformanceState, helpers: CalendarHelpers): string {
  return `
    <div class="perf-tab-panel">
      <!-- Calendar -->
      <div class="section">
        <div class="section-title">
          <span>Data Coverage</span>
          <span class="perf-coverage-badge">${state.coverage.captured} of ${state.coverage.total_weekdays} days (${state.coverage.percentage}%)</span>
        </div>
        ${renderMonthlyTrend(state)}
        <div class="cal-charts-row">
          ${renderCalendar(state, helpers)}
          ${renderMonthlyDonut(state, helpers)}
        </div>
        ${renderDayOfWeekHeatmap(state, helpers)}
      </div>

      <!-- Day Detail (shown when a day is clicked) -->
      ${renderDayDetail(state, helpers)}

      <!-- AI Calendar Insights -->
      ${renderCalendarInsights(state, helpers)}
    </div>
  `;
}
