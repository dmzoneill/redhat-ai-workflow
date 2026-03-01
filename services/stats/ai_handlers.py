"""AI handler module for the stats daemon.

Provides LLM-powered analysis features using Ollama instances:
- NPU (qwen2.5:0.5b): classification, categorization (<500ms)
- iGPU (llama3.2:3b): summaries, narratives (2-5s)
- NVIDIA (llama3:8b): generation, evaluation (5-15s)

All handlers are async-safe and include caching with configurable TTL.
"""

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600
CACHE_TTL_HOURS = 4
_DEFAULT_TTL = CACHE_TTL_HOURS * SECONDS_PER_HOUR
CLOSEST_DIFF_INIT = 999
QUARTER_WEEKDAYS = 65
MISSING_LINK_SIMILARITY_THRESHOLD = 0.35
SHORT_CACHE_TTL_SECONDS = 3600


class _CacheManager:
    def __init__(self, default_ttl: float = _DEFAULT_TTL) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str, ttl: float | None = None) -> Optional[Any]:
        ttl = ttl if ttl is not None else self._default_ttl
        entry = self._cache.get(key)
        if entry and (time.time() - entry[0]) < ttl:
            return entry[1]
        return None

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.time(), value)

    def invalidate(self, prefix: str = "") -> int:
        if not prefix:
            count = len(self._cache)
            self._cache.clear()
            return count
        keys = [k for k in self._cache if k.startswith(prefix)]
        for k in keys:
            del self._cache[k]
        return len(keys)


_cache = _CacheManager()


def _cache_get(key: str, ttl: float = _DEFAULT_TTL) -> Optional[Any]:
    """Return cached value if still valid, else None."""
    return _cache.get(key, ttl)


def _cache_set(key: str, value: Any) -> None:
    _cache.set(key, value)


def cache_invalidate(prefix: str = "") -> int:
    """Remove cache entries matching prefix. Empty prefix clears all."""
    return _cache.invalidate(prefix)


def _get_ollama_client(
    preferred: str = "igpu",
    fallback_chain: Optional[list[str]] = None,
):
    """Get an available Ollama client, returning None if unavailable."""
    try:
        from tool_modules.aa_ollama.src.client import get_available_client

        return get_available_client(
            primary=preferred,
            fallback_chain=fallback_chain or ["nvidia", "cpu"],
        )
    except ImportError:
        logger.debug("Ollama client not available")
        return None
    except Exception as e:
        logger.debug(f"Failed to get Ollama client: {e}")
        return None


def _generate(
    prompt: str,
    preferred_instance: str = "igpu",
    max_tokens: int = 500,
    temperature: float = 0.3,
    system: Optional[str] = None,
) -> Optional[str]:
    """Synchronous generate wrapper with fallback. Returns None on failure."""
    client = _get_ollama_client(preferred_instance)
    if not client:
        return None
    try:
        return client.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
        )
    except Exception as e:
        logger.warning(f"Ollama generate failed ({client.name}): {e}")
        return None


def _classify(
    text: str,
    categories: list[str],
    preferred_instance: str = "npu",
) -> Optional[str]:
    """Classify text into one category. Returns None on failure."""
    client = _get_ollama_client(preferred_instance, fallback_chain=["cpu", "igpu"])
    if not client:
        return None
    try:
        return client.classify(text, categories)
    except Exception as e:
        logger.warning(f"Ollama classify failed ({client.name}): {e}")
        return None


# ==================== Peer Narrative ====================


def generate_peer_narrative(
    user_pct: dict[str, int],
    user_overall: int,
    peer_levels: dict[str, dict],
    user_event_counts: dict[str, int] | None = None,
    engineering_level: str = "",
) -> dict:
    """Generate an AI narrative comparing user to peer benchmarks.

    Returns {"success": bool, "narrative": str, "source": "ai"|"fallback"}.
    """
    cache_key = (
        f"peer_narrative:{user_overall}:{hash(json.dumps(user_pct, sort_keys=True))}"
    )
    cached = _cache_get(cache_key)
    if cached:
        return cached

    level_labels = {
        "se": "Senior Engineer",
        "pse": "Principal Engineer",
        "spse": "Sr Principal Engineer",
        "de": "Distinguished Engineer",
    }

    level_summaries = []
    for lk in ["se", "pse", "spse", "de"]:
        ld = peer_levels.get(lk)
        if not ld:
            continue
        avg_pct = ld.get("avg_competency_pct", {})
        avg_overall = ld.get("avg_overall_pct", 0)
        label = level_labels.get(lk, lk)
        level_summaries.append(
            f"- {label} ({lk}): overall {avg_overall}%, "
            f"competencies: {json.dumps(avg_pct)}"
        )

    if not level_summaries:
        result = {
            "success": False,
            "narrative": "No peer data available for comparison.",
            "source": "none",
        }
        return result

    event_info = ""
    if user_event_counts:
        event_info = (
            f"\nYour event breakdown by source: {json.dumps(user_event_counts)}"
        )
        for lk in ["se", "pse", "spse", "de"]:
            ld = peer_levels.get(lk)
            if ld and ld.get("avg_event_counts_by_source"):
                label = level_labels.get(lk, lk)
                event_info += f"\n{label} avg events: {json.dumps(ld['avg_event_counts_by_source'])}"

    prompt = f"""Analyze this engineer's quarterly performance compared to peer benchmarks.

YOUR SCORES:
- Overall: {user_overall}%
- Per competency: {json.dumps(user_pct)}
{event_info}

PEER BENCHMARKS BY LEVEL:
{chr(10).join(level_summaries)}

Write a concise 3-5 sentence analysis that:
1. States which level the engineer most closely matches
2. Highlights the top 2-3 strengths (where they exceed peers)
3. Identifies the top 2-3 gaps (where they fall short)
4. Gives one specific, actionable suggestion

Be direct and specific with numbers. Use "you" to address the engineer."""

    text = _generate(prompt, preferred_instance="igpu", max_tokens=400, temperature=0.3)
    if text:
        result = {"success": True, "narrative": text.strip(), "source": "ai"}
    else:
        result = _generate_peer_narrative_fallback(
            user_pct, user_overall, peer_levels, level_labels
        )

    _cache_set(cache_key, result)
    return result


def _generate_peer_narrative_fallback(
    user_pct: dict[str, int],
    user_overall: int,
    peer_levels: dict[str, dict],
    level_labels: dict[str, str],
) -> dict:
    """Rule-based fallback when LLM is unavailable."""
    closest_level = ""
    closest_diff = CLOSEST_DIFF_INIT
    for lk in ["se", "pse", "spse", "de"]:
        ld = peer_levels.get(lk)
        if not ld:
            continue
        diff = abs(user_overall - ld.get("avg_overall_pct", 0))
        if diff < closest_diff:
            closest_diff = diff
            closest_level = lk

    if not closest_level:
        return {
            "success": False,
            "narrative": "Insufficient peer data.",
            "source": "none",
        }

    label = level_labels.get(closest_level, closest_level)
    peer_pct = peer_levels[closest_level].get("avg_competency_pct", {})

    strengths = []
    gaps = []
    for comp_id in sorted(set(user_pct.keys()) | set(peer_pct.keys())):
        u = user_pct.get(comp_id, 0)
        p = peer_pct.get(comp_id, 0)
        delta = u - p
        name = comp_id.replace("_", " ").title()
        if delta >= 10:
            strengths.append((name, delta))
        elif delta <= -10:
            gaps.append((name, delta))

    strengths.sort(key=lambda x: -x[1])
    gaps.sort(key=lambda x: x[1])

    parts = [
        f"Your overall score ({user_overall}%) most closely matches {label} level."
    ]
    if strengths[:3]:
        s = ", ".join(f"{n} (+{d}%)" for n, d in strengths[:3])
        parts.append(f"Strengths vs {label}: {s}.")
    if gaps[:3]:
        g = ", ".join(f"{n} ({d}%)" for n, d in gaps[:3])
        parts.append(f"Gaps vs {label}: {g}.")
    if gaps:
        parts.append(
            f"Focus on improving {gaps[0][0].lower()} to close the biggest gap."
        )

    return {
        "success": True,
        "narrative": " ".join(parts),
        "source": "fallback",
    }


# ==================== Peer Strength/Weakness Differentiators ====================


def compute_peer_differentiators(
    user_pct: dict[str, int],
    peer_levels: dict[str, dict],
    target_level: str = "",
) -> dict:
    """Compute which competencies differentiate each level and user's position.

    Returns {
        "level_differentiators": {level: [{comp, avg, distinguishing_factor}]},
        "user_vs_target": {"strengths": [...], "gaps": [...], "target_level": str},
    }
    """
    cache_key = f"peer_diff:{hash(json.dumps(user_pct, sort_keys=True))}:{target_level}"
    cached = _cache_get(cache_key, ttl=SHORT_CACHE_TTL_SECONDS)
    if cached:
        return cached

    level_order = ["se", "pse", "spse", "de"]
    level_labels = {
        "se": "Senior",
        "pse": "Principal",
        "spse": "Sr Principal",
        "de": "Distinguished",
    }

    # Find competencies that most differentiate levels
    level_differentiators: dict[str, list[dict]] = {}
    all_comp_ids = set()
    for ld in peer_levels.values():
        all_comp_ids.update(ld.get("avg_competency_pct", {}).keys())

    for lk in level_order:
        ld = peer_levels.get(lk)
        if not ld:
            continue
        pct = ld.get("avg_competency_pct", {})
        other_avg: dict[str, float] = {}
        other_count = 0
        for ok in level_order:
            if ok == lk or ok not in peer_levels:
                continue
            other_count += 1
            for c in all_comp_ids:
                other_avg[c] = other_avg.get(c, 0) + peer_levels[ok].get(
                    "avg_competency_pct", {}
                ).get(c, 0)
        if other_count:
            for c in other_avg:
                other_avg[c] /= other_count

        diffs = []
        for c in all_comp_ids:
            this_val = pct.get(c, 0)
            other_val = other_avg.get(c, 0)
            if this_val > other_val + 5:
                name = c.replace("_", " ").title()
                diffs.append(
                    {
                        "competency": c,
                        "name": name,
                        "level_avg": this_val,
                        "others_avg": round(other_val),
                        "factor": round(this_val / max(other_val, 1), 1),
                    }
                )
        diffs.sort(key=lambda x: -x["factor"])
        level_differentiators[lk] = diffs[:5]

    # User vs target level analysis
    if not target_level:
        for lk in level_order:
            ld = peer_levels.get(lk)
            if ld and ld.get("avg_overall_pct", 0) > user_pct.get("__overall", 0):
                target_level = lk
                break
        if not target_level:
            target_level = level_order[-1] if peer_levels else ""

    user_vs = {
        "strengths": [],
        "gaps": [],
        "target_level": target_level,
        "target_label": level_labels.get(target_level, target_level),
    }

    if target_level in peer_levels:
        target_pct = peer_levels[target_level].get("avg_competency_pct", {})
        for c in sorted(all_comp_ids):
            u = user_pct.get(c, 0)
            t = target_pct.get(c, 0)
            delta = u - t
            name = c.replace("_", " ").title()
            entry = {
                "competency": c,
                "name": name,
                "user": u,
                "target": t,
                "delta": delta,
            }
            if delta >= 5:
                user_vs["strengths"].append(entry)
            elif delta <= -5:
                user_vs["gaps"].append(entry)
        user_vs["strengths"].sort(key=lambda x: -x["delta"])
        user_vs["gaps"].sort(key=lambda x: x["delta"])

    result = {
        "success": True,
        "level_differentiators": level_differentiators,
        "user_vs_target": user_vs,
    }
    _cache_set(cache_key, result)
    return result


# ==================== Overview Digest ====================


def generate_overview_digest(
    summary: dict,
    daily_points_trend: list[dict] | None = None,
    peer_levels: dict | None = None,
) -> dict:
    """Generate weekly AI digest for the overview tab."""
    cache_key = f"overview_digest:{summary.get('last_updated', '')}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    overall = summary.get("overall_percentage", 0)
    comp_pct = summary.get("cumulative_percentage", {})
    day_of_quarter = summary.get("day_of_quarter", 0)
    total_events = summary.get("total_events", 0)
    highlights = summary.get("highlights", [])
    gaps = summary.get("gaps", [])

    peer_context = ""
    if peer_levels:
        for lk in ["se", "pse", "spse", "de"]:
            ld = peer_levels.get(lk)
            if ld:
                peer_context += f"\n- {lk.upper()} avg: {ld.get('avg_overall_pct', 0)}%"

    prompt = f"""Summarize this engineer's quarterly performance in 3-5 sentences.

STATS: {overall}% overall, day {day_of_quarter} of quarter, {total_events} total events.
COMPETENCIES: {json.dumps(comp_pct)}
HIGHLIGHTS: {', '.join(highlights[:5]) if highlights else 'None'}
GAPS: {', '.join(gaps[:5]) if gaps else 'None'}
{f'PEER BENCHMARKS:{peer_context}' if peer_context else ''}

Focus on: trajectory (on track?), biggest wins, biggest risks, one action item.
Be specific with numbers. Use "you" to address the engineer."""

    text = _generate(prompt, preferred_instance="igpu", max_tokens=300, temperature=0.3)

    # Trend prediction (simple linear extrapolation)
    trend = _compute_trend(daily_points_trend, day_of_quarter, overall)

    if text:
        result = {
            "success": True,
            "digest": text.strip(),
            "trend": trend,
            "source": "ai",
        }
    else:
        parts = [f"Quarter progress: {overall}% overall on day {day_of_quarter}."]
        if highlights:
            parts.append(f"Top highlight: {highlights[0]}.")
        if gaps:
            parts.append(f"Biggest gap: {gaps[0]}.")
        if trend.get("projected_final"):
            parts.append(
                f"Projected final score: {trend['projected_final']}% "
                f"({trend.get('status', 'unknown')})."
            )
        result = {
            "success": True,
            "digest": " ".join(parts),
            "trend": trend,
            "source": "fallback",
        }

    _cache_set(cache_key, result)
    return result


def _compute_trend(
    daily_trend: list[dict] | None,
    day_of_quarter: int,
    current_overall: int,
) -> dict:
    """Simple trend projection for quarter-end score."""
    if not daily_trend or day_of_quarter < 5:
        return {"projected_final": None, "status": "insufficient_data"}

    try:
        import numpy as np

        days = [d.get("day", i) for i, d in enumerate(daily_trend)]
        values = [d.get("cumulative_pct", 0) for d in daily_trend]
        if len(days) < 3:
            return {"projected_final": None, "status": "insufficient_data"}

        coeffs = np.polyfit(days, values, 1)
        total_days = QUARTER_WEEKDAYS
        projected = int(np.polyval(coeffs, total_days))
        projected = max(0, min(projected, 100))

        if projected >= 80:
            status = "on_track"
        elif projected >= 60:
            status = "at_risk"
        else:
            status = "behind"

        return {
            "projected_final": projected,
            "daily_rate": round(float(coeffs[0]), 2),
            "status": status,
        }
    except Exception as e:
        logger.warning("Computing trend projection with numpy polyfit: %s", e)
        if day_of_quarter > 0:
            rate = current_overall / day_of_quarter
            projected = int(rate * QUARTER_WEEKDAYS)
            projected = max(0, min(projected, 100))
            status = (
                "on_track"
                if projected >= 80
                else "at_risk" if projected >= 60 else "behind"
            )
            return {"projected_final": projected, "status": status}
        return {"projected_final": None, "status": "insufficient_data"}


# ==================== Gap Coach ====================


def generate_gap_coach(
    competency_id: str,
    competency_name: str,
    user_pct: int,
    user_events: list[dict],
    peer_levels: dict | None = None,
    target_level: str = "",
) -> dict:
    """Generate AI coaching suggestion for a competency gap."""
    cache_key = f"gap_coach:{competency_id}:{user_pct}"
    cached = _cache_get(cache_key, ttl=SHORT_CACHE_TTL_SECONDS)
    if cached:
        return cached

    peer_context = ""
    if peer_levels and target_level and target_level in peer_levels:
        target_pct = (
            peer_levels[target_level]
            .get("avg_competency_pct", {})
            .get(competency_id, 0)
        )
        target_events = peer_levels[target_level].get("avg_event_counts_by_source", {})
        peer_context = (
            f"\nTarget level ({target_level.upper()}) averages {target_pct}% in this competency."
            f"\nTarget level event mix: {json.dumps(target_events)}"
        )

    event_summary = {}
    for ev in user_events[:50]:
        src = ev.get("source", "unknown")
        event_summary[src] = event_summary.get(src, 0) + 1

    prompt = f"""Give a specific, actionable coaching suggestion for improving the "{competency_name}" competency.

Current score: {user_pct}%
Event breakdown: {json.dumps(event_summary)}
{peer_context}

Write 2-3 sentences with a concrete suggestion. Reference specific actions (PR reviews, mentoring, etc.)."""

    text = _generate(prompt, preferred_instance="igpu", max_tokens=200, temperature=0.3)
    if text:
        result = {"success": True, "suggestion": text.strip(), "source": "ai"}
    else:
        result = {
            "success": True,
            "suggestion": f"Your {competency_name.lower()} score is {user_pct}%. "
            "Consider increasing activity in this area through targeted contributions.",
            "source": "fallback",
        }

    _cache_set(cache_key, result)
    return result


# ==================== Promotion Readiness ====================


def generate_promotion_readiness(
    user_pct: dict[str, int],
    user_overall: int,
    peer_levels: dict[str, dict],
    current_level: str = "",
) -> dict:
    """Assess readiness for promotion to next level."""
    level_order = ["se", "pse", "spse", "de"]
    level_labels = {
        "se": "Senior",
        "pse": "Principal",
        "spse": "Sr Principal",
        "de": "Distinguished",
    }

    # Determine next level
    if current_level in level_order:
        idx = level_order.index(current_level)
        next_level = level_order[idx + 1] if idx + 1 < len(level_order) else None
    else:
        next_level = None
        for lk in level_order:
            ld = peer_levels.get(lk)
            if ld and ld.get("avg_overall_pct", 0) > user_overall:
                next_level = lk
                break

    if not next_level or next_level not in peer_levels:
        return {
            "success": False,
            "error": "Cannot determine next level or no peer data for it.",
        }

    cache_key = f"promo_readiness:{user_overall}:{next_level}"
    cached = _cache_get(cache_key, ttl=SHORT_CACHE_TTL_SECONDS)
    if cached:
        return cached

    target_pct = peer_levels[next_level].get("avg_competency_pct", {})
    target_overall = peer_levels[next_level].get("avg_overall_pct", 0)

    assessments = []
    ready_count = 0
    total = 0
    for comp_id in sorted(set(user_pct.keys()) | set(target_pct.keys())):
        u = user_pct.get(comp_id, 0)
        t = target_pct.get(comp_id, 0)
        name = comp_id.replace("_", " ").title()
        total += 1
        if u >= t - 5:
            status = "ready"
            ready_count += 1
        elif u >= t - 15:
            status = "almost"
        else:
            status = "gap"
        assessments.append(
            {
                "competency": comp_id,
                "name": name,
                "user_pct": u,
                "target_pct": t,
                "delta": u - t,
                "status": status,
            }
        )

    assessments.sort(key=lambda x: x["delta"])

    # Generate AI summary
    gaps_text = "\n".join(
        f"- {a['name']}: you {a['user_pct']}% vs target {a['target_pct']}% (delta {a['delta']:+d}%)"
        for a in assessments
        if a["status"] == "gap"
    )
    prompt = f"""Assess this engineer's readiness for promotion to {level_labels.get(next_level, next_level)} level.

Overall: {user_overall}% vs target {target_overall}%
Meeting {ready_count}/{total} competency benchmarks.

GAPS:
{gaps_text or 'None - all competencies meet target!'}

Write a 3-4 sentence assessment. Start with the overall readiness verdict.
Give 1-2 specific suggestions for closing the biggest gaps."""

    ai_summary = _generate(
        prompt, preferred_instance="igpu", max_tokens=300, temperature=0.3
    )

    result = {
        "success": True,
        "next_level": next_level,
        "next_level_label": level_labels.get(next_level, next_level),
        "target_overall": target_overall,
        "ready_count": ready_count,
        "total_competencies": total,
        "assessments": assessments,
        "summary": (
            ai_summary.strip()
            if ai_summary
            else (
                f"You meet {ready_count}/{total} competency benchmarks for "
                f"{level_labels.get(next_level, next_level)}."
            )
        ),
        "source": "ai" if ai_summary else "fallback",
    }

    _cache_set(cache_key, result)
    return result


# ==================== Calendar Insights ====================


def generate_calendar_insights(
    captured_days: list[str],
    total_weekdays: int,
    quarter: str = "",
) -> dict:
    """Detect work patterns and coverage forecast from calendar data."""
    from datetime import date as date_type

    if not captured_days:
        return {"success": True, "patterns": [], "forecast": None}

    dates = []
    for d in captured_days:
        try:
            dates.append(date_type.fromisoformat(d))
        except (ValueError, TypeError):
            continue

    if not dates:
        return {"success": True, "patterns": [], "forecast": None}

    patterns = []

    # Day-of-week analysis
    dow_counts = [0] * 5  # Mon-Fri
    for d in dates:
        if d.weekday() < 5:
            dow_counts[d.weekday()] += 1

    max_weeks = max(1, len(dates) / 5)
    dow_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    for i, count in enumerate(dow_counts):
        rate = count / max_weeks
        if rate < 0.4:
            patterns.append(
                {
                    "type": "gap_day",
                    "message": f"{dow_names[i]}s are frequently missing ({count} captured).",
                    "severity": "info",
                }
            )

    # Streak analysis
    dates_sorted = sorted(dates)
    current_streak = 1
    max_streak = 1
    for i in range(1, len(dates_sorted)):
        diff = (dates_sorted[i] - dates_sorted[i - 1]).days
        if diff == 1 or (diff <= 3 and dates_sorted[i - 1].weekday() == 4):
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1

    if max_streak >= 10:
        patterns.append(
            {
                "type": "streak",
                "message": f"Best streak: {max_streak} consecutive days captured.",
                "severity": "positive",
            }
        )

    # Gap detection
    biggest_gap = 0
    gap_start = None
    for i in range(1, len(dates_sorted)):
        diff = (dates_sorted[i] - dates_sorted[i - 1]).days
        if diff > biggest_gap:
            biggest_gap = diff
            gap_start = dates_sorted[i - 1]
    if biggest_gap > 5 and gap_start:
        patterns.append(
            {
                "type": "gap",
                "message": f"Longest gap: {biggest_gap} days starting {gap_start.isoformat()}.",
                "severity": "warning",
            }
        )

    # Coverage forecast
    coverage_pct = round(len(dates) / max(total_weekdays, 1) * 100)
    remaining_days = max(total_weekdays - len(dates), 0)
    total_quarter_weekdays = QUARTER_WEEKDAYS
    if total_weekdays > 0:
        capture_rate = len(dates) / total_weekdays
        projected = round(capture_rate * total_quarter_weekdays)
        projected_pct = round(projected / total_quarter_weekdays * 100)
    else:
        projected_pct = coverage_pct

    forecast = {
        "current_pct": coverage_pct,
        "projected_pct": min(projected_pct, 100),
        "remaining_weekdays": remaining_days,
    }

    return {"success": True, "patterns": patterns, "forecast": forecast}


# ==================== Log Auto-Categorize ====================


def classify_log_category(
    description: str,
    categories: list[str] | None = None,
) -> dict:
    """Classify a manual log entry into a category using NPU."""
    if categories is None:
        categories = [
            "Speaking",
            "Presentation",
            "Demo",
            "Mentorship",
            "Blog Post",
            "Other",
        ]

    if not description or len(description.strip()) < 5:
        return {"success": True, "category": "Other", "source": "default"}

    result = _classify(description, categories, preferred_instance="npu")
    if result:
        return {"success": True, "category": result, "source": "ai"}
    return {"success": True, "category": "Other", "source": "fallback"}


# ==================== Issue Competency Tags ====================


def classify_issue_competencies(
    issue_text: str,
    npu_classifier=None,
    top_n: int = 3,
) -> list[dict]:
    """Tag an issue with top competency matches using NPU classifier."""
    if npu_classifier and npu_classifier.enabled:
        confidences = npu_classifier.classify(issue_text)
        if confidences:
            sorted_comps = sorted(confidences.items(), key=lambda x: -x[1])[:top_n]
            return [
                {
                    "competency": comp_id,
                    "name": comp_id.replace("_", " ").title(),
                    "confidence": round(conf, 3),
                }
                for comp_id, conf in sorted_comps
                if conf >= 0.2
            ]
    return []


# ==================== Evidence Auto-Ranking ====================


def rank_evidence_for_question(
    question_text: str,
    evidence_events: list[dict],
    npu_classifier=None,
    top_n: int = 20,
) -> list[dict]:
    """Rank evidence events by relevance to a question using embedding similarity."""
    if not npu_classifier or not npu_classifier.enabled or not npu_classifier.model:
        return _rank_evidence_by_points(evidence_events, top_n)

    try:
        import numpy as np

        q_embedding = npu_classifier.model.encode(
            [question_text], normalize_embeddings=True
        )[0]

        scored = []
        for ev in evidence_events:
            text = ev.get("classification_text", "") or ev.get("title", "")
            if not text:
                scored.append((ev, 0.0))
                continue
            ev_embedding = npu_classifier.model.encode(
                [text], normalize_embeddings=True
            )[0]
            similarity = float(np.dot(q_embedding, ev_embedding))
            scored.append((ev, similarity))

        scored.sort(key=lambda x: -x[1])
        return [
            {**ev, "_relevance_score": round(score, 3)} for ev, score in scored[:top_n]
        ]
    except Exception as e:
        logger.debug(f"Evidence ranking failed, falling back to points: {e}")
        return _rank_evidence_by_points(evidence_events, top_n)


def _rank_evidence_by_points(events: list[dict], top_n: int) -> list[dict]:
    """Fallback ranking by total points."""
    scored = sorted(
        events,
        key=lambda e: sum(e.get("points", {}).values()),
        reverse=True,
    )
    return scored[:top_n]


# ==================== Ask AI (Help Tab) ====================


def ask_ai_tutor(
    question: str,
    scoring_config: dict | None = None,
    user_summary: dict | None = None,
) -> dict:
    """Answer a question about the scoring system."""
    cache_key = f"ask_ai:{hash(question)}"
    cached = _cache_get(cache_key, ttl=1800)
    if cached:
        return cached

    config_context = ""
    if scoring_config:
        config_context = f"""
SCORING CONFIG:
- Engineering level: {scoring_config.get('engineering_level', 'unknown')}
- Target per competency: {scoring_config.get('target_per_competency', 'unknown')}
- Daily cap: {scoring_config.get('daily_cap', 'unknown')}
- Min signals: {scoring_config.get('min_signals', 'unknown')}"""

    user_context = ""
    if user_summary:
        user_context = f"""
YOUR SCORES:
- Overall: {user_summary.get('overall_percentage', 0)}%
- Competencies: {json.dumps(user_summary.get('cumulative_percentage', {}))}"""

    system = (
        "You are a QC (Quarterly Connection) scoring system expert. "
        "Answer questions about how the performance scoring works, "
        "what competencies mean, and how to improve scores. "
        "Be concise and specific."
    )

    prompt = f"""{config_context}{user_context}

QUESTION: {question}

Answer concisely in 2-4 sentences."""

    text = _generate(
        prompt,
        preferred_instance="igpu",
        max_tokens=300,
        temperature=0.3,
        system=system,
    )

    if text:
        result = {"success": True, "answer": text.strip(), "source": "ai"}
    else:
        result = {
            "success": False,
            "answer": "AI is currently unavailable. Please check that Ollama is running.",
            "source": "unavailable",
        }

    _cache_set(cache_key, result)
    return result


# ==================== Scoring Explainer ====================


def explain_competency_score(
    competency_id: str,
    competency_name: str,
    events: list[dict],
    scoring_config: dict | None = None,
) -> dict:
    """Generate a step-by-step explanation of how a competency score was calculated."""
    total_points = 0
    event_summaries = []
    source_counts: dict[str, int] = {}
    for ev in events:
        pts = ev.get("points", {}).get(competency_id, 0)
        if pts > 0:
            total_points += pts
            src = ev.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
            event_summaries.append(
                f"- {ev.get('title', 'Unknown')[:80]} [{src}]: {pts} pts"
            )

    prompt = f"""Explain how this engineer's "{competency_name}" score was calculated.

Total points: {total_points}
Number of contributing events: {len(event_summaries)}
Events by source: {json.dumps(source_counts)}

Top contributing events:
{chr(10).join(event_summaries[:15])}

Write a 2-3 sentence explanation of where the points came from and what types of work contributed most."""

    text = _generate(prompt, preferred_instance="igpu", max_tokens=250, temperature=0.2)

    if text:
        return {
            "success": True,
            "explanation": text.strip(),
            "source": "ai",
            "total_points": total_points,
            "event_count": len(event_summaries),
        }
    return {
        "success": True,
        "explanation": (
            f"{competency_name} earned {total_points} points from "
            f"{len(event_summaries)} events. "
            f"Sources: {', '.join(f'{k} ({v})' for k, v in source_counts.items())}."
        ),
        "source": "fallback",
        "total_points": total_points,
        "event_count": len(event_summaries),
    }


# ==================== Auto-Tune Config ====================


def suggest_config_tune(
    user_event_distribution: dict[str, int],
    user_competency_pct: dict[str, int],
    peer_levels: dict | None = None,
    target_level: str = "",
) -> dict:
    """Suggest scoring config adjustments based on event distribution and peer data."""
    suggestions = []

    total_events = sum(user_event_distribution.values()) or 1
    event_pcts = {
        k: round(v / total_events * 100) for k, v in user_event_distribution.items()
    }

    if event_pcts.get("git", 0) > 70:
        suggestions.append(
            {
                "setting": "scope_multipliers",
                "message": (
                    "Your work is heavily commit-based. Consider increasing "
                    "review/mentorship activities for a more balanced profile."
                ),
                "type": "info",
            }
        )

    pct_values = [v for v in user_competency_pct.values() if v > 0]
    if pct_values:
        avg = sum(pct_values) / len(pct_values)
        std_dev = (sum((v - avg) ** 2 for v in pct_values) / len(pct_values)) ** 0.5
        if std_dev > 25:
            suggestions.append(
                {
                    "setting": "pillar_weights",
                    "message": (
                        f"Your competency distribution is peaked "
                        f"(std dev {std_dev:.0f}%). Consider adjusting "
                        f"pillar weights to encourage breadth."
                    ),
                    "type": "warning",
                }
            )

    if peer_levels and target_level and target_level in peer_levels:
        target_events = peer_levels[target_level].get("avg_event_counts_by_source", {})
        if target_events:
            for src, avg in target_events.items():
                user_count = user_event_distribution.get(src, 0)
                if avg > 0 and user_count < avg * 0.5:
                    suggestions.append(
                        {
                            "setting": "activity_mix",
                            "message": f"Target level averages {avg:.1f} {src} events but you have {user_count}.",
                            "type": "info",
                        }
                    )

    return {"success": True, "suggestions": suggestions}


# ==================== Peer Growth Trajectory ====================


def compute_peer_growth_data(
    user_daily_dir,
    peers_dir,
    peer_levels_config: dict,
    competency_ids: list[str] | None = None,
) -> dict:
    """Build time-series data for user and peer growth comparison."""
    from pathlib import Path

    def _load_daily_series(daily_dir: Path) -> list[dict]:
        series: list[dict] = []
        if not daily_dir.exists():
            return series
        cumulative: dict[str, int] = {}
        for f in sorted(daily_dir.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fh:
                    data = json.load(fh)
                for comp_id, pts in data.get("daily_points", {}).items():
                    cumulative[comp_id] = cumulative.get(comp_id, 0) + pts
                total = sum(cumulative.values())
                series.append(
                    {
                        "date": f.stem,
                        "total_points": total,
                        "competencies": dict(cumulative),
                    }
                )
            except Exception as e:
                logger.warning("Loading daily series from JSON file: %s", e)
                continue
        return series

    user_series = _load_daily_series(Path(user_daily_dir))

    level_series: dict[str, list[dict]] = {}
    for level_key, peer_list in peer_levels_config.items():
        all_peer_series = []
        for peer in peer_list:
            uname = peer.get("username", "")
            peer_daily = Path(peers_dir) / uname / "daily"
            s = _load_daily_series(peer_daily)
            if s:
                all_peer_series.append(s)

        if all_peer_series:
            max_len = max(len(s) for s in all_peer_series)
            avg_series = []
            for i in range(max_len):
                date_str = ""
                total = 0
                count = 0
                for s in all_peer_series:
                    if i < len(s):
                        date_str = s[i]["date"]
                        total += s[i]["total_points"]
                        count += 1
                if count:
                    avg_series.append(
                        {
                            "date": date_str,
                            "total_points": round(total / count),
                        }
                    )
            level_series[level_key] = avg_series

    return {
        "success": True,
        "user_series": user_series,
        "level_series": level_series,
    }


# ==================== Activity Pattern Analysis ====================


def analyze_activity_patterns(
    peer_levels: dict[str, dict],
    user_event_counts: dict[str, int],
) -> dict:
    """Compare event type distributions across levels."""
    level_labels = {
        "se": "Senior",
        "pse": "Principal",
        "spse": "Sr Principal",
        "de": "Distinguished",
    }
    insights = []

    all_sources = set(user_event_counts.keys())
    for ld in peer_levels.values():
        all_sources.update(ld.get("avg_event_counts_by_source", {}).keys())

    for src in sorted(all_sources):
        vals = {}
        for lk in ["se", "pse", "spse", "de"]:
            ld = peer_levels.get(lk)
            if ld:
                vals[lk] = ld.get("avg_event_counts_by_source", {}).get(src, 0)

        if len(vals) >= 2:
            min_val = min(vals.values())
            max_val = max(vals.values())
            if max_val > min_val * 2 and max_val > 5:
                max_level = max(vals, key=vals.get)
                insights.append(
                    {
                        "source": src,
                        "message": (
                            f"{level_labels.get(max_level, max_level)} engineers average "
                            f"{max_val:.1f} {src} events vs {min_val:.1f} for lower levels."
                        ),
                        "levels": vals,
                    }
                )

    return {"success": True, "insights": insights}


# ==================== Missing Link Detection ====================


def detect_missing_links(
    anstrat_items: list[dict],
    orphan_issues: list[dict],
    npu_classifier=None,
    threshold: float = MISSING_LINK_SIMILARITY_THRESHOLD,
    top_n: int = 5,
) -> list[dict]:
    """Find orphan issues that semantically match an ANSTRAT but aren't linked.

    Returns list of {"issue": {...}, "suggested_anstrat": {...}, "similarity": float}.
    """
    if not npu_classifier or not npu_classifier.enabled or not npu_classifier.model:
        return []

    if not anstrat_items or not orphan_issues:
        return []

    try:
        import numpy as np

        anstrat_texts = [
            f"{a.get('key', '')} {a.get('summary', '')} {a.get('description', '')[:200]}"
            for a in anstrat_items
        ]
        orphan_texts = [
            f"{o.get('key', '')} {o.get('summary', '')} {o.get('description', '')[:200]}"
            for o in orphan_issues
        ]

        anstrat_embs = npu_classifier.model.encode(
            anstrat_texts, normalize_embeddings=True
        )
        orphan_embs = npu_classifier.model.encode(
            orphan_texts, normalize_embeddings=True
        )

        suggestions = []
        for i, orphan in enumerate(orphan_issues):
            best_sim = 0.0
            best_idx = -1
            for j in range(len(anstrat_items)):
                sim = float(np.dot(orphan_embs[i], anstrat_embs[j]))
                if sim > best_sim:
                    best_sim = sim
                    best_idx = j
            if best_sim >= threshold and best_idx >= 0:
                suggestions.append(
                    {
                        "issue": {
                            "key": orphan.get("key", ""),
                            "summary": orphan.get("summary", ""),
                        },
                        "suggested_anstrat": {
                            "key": anstrat_items[best_idx].get("key", ""),
                            "summary": anstrat_items[best_idx].get("summary", ""),
                        },
                        "similarity": round(best_sim, 3),
                    }
                )

        suggestions.sort(key=lambda x: -x["similarity"])
        return suggestions[:top_n]

    except Exception as e:
        logger.debug(f"Missing link detection failed: {e}")
        return []
