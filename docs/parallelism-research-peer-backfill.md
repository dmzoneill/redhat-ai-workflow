# Parallelism Research: Peer Backfill I/O Optimization

**Date:** 2026-02-22
**Scope:** `_run_peer_backfill` in `services/stats/daemon.py` and `_collect_for_date_impl` in `services/stats/collector.py`

## Executive Summary

**Recommended strategy:** **Batch pre-fetching (c) + per-peer parallelism (a)** with a small refactor to fix thread-safety.

- **Phase 1:** Pre-fetch all quarter caches (GitLab, GitHub, Jira) for all 60 peers in parallel (semaphore-limited).
- **Phase 2:** Run the day loop with per-peer parallelism (3–5 peers at a time) using a fixed `DataCollector` per peer.

**Expected speedup:** ~8–15x (from ~30–60 min to ~3–6 min for full backfill).

---

## 1. Current Implementation

### 1.1 `_run_peer_backfill` (daemon.py:1225)

```
for each peer (60):
    for each day (35):
        daily_data = await loop.run_in_executor(None, collect_for_date, day, peer, ...)
        peer_events += len(daily_data["events"])
    await run_in_executor(None, _update_peer_summary, ...)
await run_in_executor(None, _update_peer_benchmarks, ...)
```

- Fully sequential: one peer at a time, one day at a time.
- Uses default `ThreadPoolExecutor` (typically ~32 workers) but only one task is submitted at a time.
- Each `collect_for_date` call is blocking and runs in a thread.

### 1.2 `_collect_for_date_impl` (collector.py:2239)

Per-day work (for a single peer):

| Step | Operation | Latency | Notes |
|------|-----------|---------|-------|
| 1 | **git** | ~0.5s × N repos | `subprocess` git log per repo |
| 2 | **jira** | 2–5s or ~0ms | `prefetch_jira_quarter` (REST) or in-memory lookup |
| 3 | **github** | 1–5s or ~10ms | `get_github_cache` (GraphQL) or file read |
| 4 | **gitlab** | 1–5s or ~10ms | `get_gitlab_cache` (REST) or file read |
| 5 | **jira_created** | ~0ms for peers | Returns [] for peers (already in prefetch) |
| 6 | **_fetch_missing_hierarchy** | ~0.5s × N keys | `rh-issue view-issue` subprocess per AAP key |
| 7 | **write** | ~10ms | JSON write to `peers/{peer}/daily/{date}.json` |

**Cache behavior:**
- **Jira:** `prefetch_jira_quarter` fills `_jira_quarter_cache[jira_user:year:Q]` in memory. First day for a peer triggers 2–3 REST calls; subsequent days use cache.
- **GitLab:** `get_gitlab_cache` reads/writes `gitlab_event_cache_{username}.json`. First day triggers REST; later days use file cache (1h TTL).
- **GitHub:** Same pattern with `github_cache_{username}.json`.

---

## 2. Parallelism Strategies

### (a) Per-peer parallelism

**Idea:** Run 3–5 peers concurrently with `asyncio.Semaphore`.

**Pros:**
- Simple control flow.
- Good speedup (3–5x) with minimal changes.
- Each peer writes to different files.

**Cons:**
- Shared `DataCollector` uses `_user_override` / `_level_override` instance vars → **not thread-safe** (see §3).
- `hierarchy_cache` and `_jira_quarter_cache` are shared; need coordination.

### (b) Per-source parallelism within a day

**Idea:** For each day, run git / jira / github / gitlab in parallel, then merge.

**Pros:**
- Reduces per-day wall time.

**Cons:**
- Sources have dependencies (e.g. git uses gitlab/github cache for `peer_repo_paths`).
- `seen_ids` must be shared; merge logic is more complex.
- Smaller gain than (a) or (c) because cache fetches dominate.

### (c) Batch pre-fetching

**Idea:** Pre-fetch all quarter caches for all peers before the day loop. Day loop only does git + filtering + write.

**Pros:**
- Large speedup: 60 × (GitLab + GitHub + Jira) fetches done in parallel up front.
- Day loop becomes cheap: git (~0.5s) + filter (~ms) + write (~10ms).
- Fits current cache design (file + in-memory).

**Cons:**
- Higher memory during pre-fetch (60 × 3 cache payloads).
- Requires restructuring the backfill flow.

### (d) Larger ThreadPoolExecutor

**Idea:** Increase thread pool size.

**Cons:**
- Current loop only submits one task at a time, so more workers do not help.
- Would need (a) or (c) to actually parallelize.

---

## 3. Thread-Safety Analysis

### 3.1 `DataCollector` – not safe for concurrent `collect_for_date`

| Component | Thread-safe? | Notes |
|-----------|--------------|-------|
| `_user_override` | ❌ No | Set at start of `collect_for_date`, cleared in `finally`. Concurrent calls overwrite each other; `_enrich_event` can use the wrong peer. |
| `_level_override` | ❌ No | Same as above. |
| `_jira_quarter_cache` | ⚠️ Mostly | Keyed by `jira_user:year:quarter`. Different peers use different keys. Dict assignment is atomic in CPython; concurrent writes to different keys are safe. |
| `hierarchy_cache` | ⚠️ Mostly | Read at start; `_fetch_missing_hierarchy` adds keys. Different peers add different AAP keys. Dict `__setitem__` for different keys is safe under GIL. Risk: two threads both fetch the same missing key (redundant work, not corruption). |
| `strategy_index` | ✅ Yes | Loaded once before the loop; read-only during collection. |
| `_hierarchy_tried` | ⚠️ Mostly | `set.add` is atomic. Multiple threads adding different keys is safe. |
| `get_gitlab_cache` / `get_github_cache` | ✅ Yes | Per-user cache files; no shared in-memory cache. |
| `discover_peer_repos` / `_ensure_repo_cached` | ⚠️ Low risk | Writes to disk (git clone). Two peers discovering the same new repo could race on directory creation; low probability. |

### 3.2 File writes

- Each peer writes to `peers/{peer_name}/daily/{date}.json`.
- No overlap between peers → safe.

### 3.3 Required fix for per-peer parallelism

`_user_override` and `_level_override` must not be instance-level if multiple `collect_for_date` calls run concurrently. Options:

1. **Pass overrides through the call chain** (recommended): Add `user_override` and `level_override` to `_enrich_event` and pass them from `_collect_for_date_impl`.
2. **Per-peer collector:** Create a `DataCollector` (or lightweight wrapper) per peer. Higher memory and cache duplication.
3. **Thread-local / contextvars:** Possible but awkward with `run_in_executor` (context not inherited to worker threads).

---

## 4. Recommended Strategy: Batch Pre-fetch + Per-Peer Parallelism

### 4.1 Phase 1: Pre-fetch all caches

```python
async def _prefetch_all_quarter_caches(
    self, all_peers: list[tuple[str, dict]], year: int, quarter: int
) -> None:
    """Pre-fetch GitLab, GitHub, Jira quarter caches for all peers in parallel."""
    sem = asyncio.Semaphore(5)  # Limit concurrent API calls
    loop = asyncio.get_event_loop()

    async def fetch_one(level_key: str, peer: dict) -> None:
        async with sem:
            gl_user = peer.get("gitlab_username", "")
            gh_user = peer.get("github_username", "")
            jira_user = peer.get("jira_username", "")
            if gl_user:
                await loop.run_in_executor(
                    None,
                    lambda: self._collector.get_gitlab_cache(year, quarter, gl_user),
                )
            if gh_user:
                await loop.run_in_executor(
                    None,
                    lambda: self._collector.get_github_cache(year, quarter, gh_user),
                )
            if jira_user:
                await loop.run_in_executor(
                    None,
                    lambda: self._collector.prefetch_jira_quarter(jira_user, year, quarter),
                )

    await asyncio.gather(*[fetch_one(lk, p) for lk, p in all_peers])
```

- Replaces 60 × 35 × (up to 3 cache fetches per day) with 60 × 3 fetches up front.
- Semaphore limits concurrent API load.

### 4.2 Phase 2: Per-peer parallelism with override fix

**Refactor:** Pass `user_override` and `level_override` into `_enrich_event` instead of using instance vars.

```python
# In collector.py - _enrich_event signature change
def _enrich_event(
    self,
    event: dict,
    user_override: dict | None = None,   # NEW: pass explicitly
    level_override: str | None = None,   # NEW: pass explicitly
    effective_defs: dict | None = None,
    min_signals: int | None = None,
) -> dict:
    # Use user_override/level_override params; fall back to self._user_override for backward compat
    level = level_override or self._level_override or ...
    current_user = (user_override or self._user_override or {}).get("jira_username", ...)
```

Then in `_collect_for_date_impl`, pass `user_override` and `level_override` to every `_enrich_event` call. `collect_for_date` can keep setting `self._user_override` for single-threaded callers, but parallel callers should pass overrides explicitly (or we remove instance vars entirely).

**Daemon backfill loop:**

```python
# After pre-fetch...
sem = asyncio.Semaphore(4)  # 4 peers at a time

async def process_peer(peer_idx: int, level_key: str, peer: dict) -> int:
    async with sem:
        peer_events = 0
        for d in all_weekdays:
            try:
                daily_data = await loop.run_in_executor(
                    None,
                    lambda _d=d, _p=peer, _l=level_key: self._collector.collect_for_date(
                        _d, user_override=_p, level_override=_l, sources=sources
                    ),
                )
                peer_events += len(daily_data.get("events", []))
            except Exception as e:
                ...
        await loop.run_in_executor(
            None, self._update_peer_summary, peer["username"], level_key, year, quarter
        )
        return peer_events

results = await asyncio.gather(*[
    process_peer(i, lk, p) for i, (lk, p) in enumerate(all_peers)
])
total_events = sum(results)
```

### 4.3 Alternative: Per-peer collector (simpler, more memory)

If refactoring `_enrich_event` is undesirable, use one collector per peer:

```python
# Create a collector per peer - each has its own _user_override, caches
collectors = {p["username"]: DataCollector() for _, p in all_peers}
# Copy shared read-only state
for c in collectors.values():
    c.strategy_index = self._collector.strategy_index
    c.hierarchy_cache = self._collector.hierarchy_cache  # Shared ref, but we only add keys
```

- `hierarchy_cache` can stay shared (we only add keys; different keys per peer).
- `_jira_quarter_cache` is per-collector, so no sharing.
- Higher memory (60 collectors) but avoids changing `_enrich_event`.

---

## 5. Expected Speedup

| Scenario | Current | With pre-fetch only | With pre-fetch + 4-way peer parallelism |
|----------|---------|---------------------|------------------------------------------|
| Cache fetches | 60 × 35 × ~2 (avg) ≈ 4200 potential | 60 × 3 = 180, parallel | Same |
| Day loop | 60 × 35 × ~3s ≈ 105 min | 60 × 35 × ~0.6s ≈ 21 min | 60 × 35 × ~0.6s / 4 ≈ 5 min |
| **Total (approx)** | **~30–60 min** | **~5–10 min** | **~3–6 min** |

- Pre-fetch: ~5–10x (cache work done once, in parallel).
- Per-peer parallelism: additional ~2–4x on the day loop.
- Combined: ~8–15x overall.

---

## 6. Code Sketch Summary

```python
# daemon.py - _run_peer_backfill (simplified)

async def _run_peer_backfill(self, peers_config, target, ...):
    # ... setup all_peers, all_weekdays ...
    self._ensure_strategy_and_hierarchy(year, quarter)

    # Phase 1: Pre-fetch all caches
    await self._prefetch_all_quarter_caches(all_peers, year, quarter)

    # Phase 2: Day loop with per-peer parallelism
    sem = asyncio.Semaphore(4)
    loop = asyncio.get_event_loop()

    async def process_peer(peer_idx, level_key, peer):
        async with sem:
            peer_events = 0
            for d in all_weekdays:
                daily_data = await loop.run_in_executor(
                    None,
                    lambda _d=d, _p=peer, _l=level_key: self._collector.collect_for_date(
                        _d, user_override=_p, level_override=_l, sources=sources
                    ),
                )
                peer_events += len(daily_data.get("events", []))
            await loop.run_in_executor(None, self._update_peer_summary, ...)
            return peer_events

    tasks = [process_peer(i, lk, p) for i, (lk, p) in enumerate(all_peers)]
    results = await asyncio.gather(*tasks)
```

---

## 7. Implementation Order

1. **Thread-safety:** Refactor `_enrich_event` to accept `user_override` and `level_override` (or adopt per-peer collectors).
2. **Pre-fetch:** Add `_prefetch_all_quarter_caches` and call it before the day loop.
3. **Per-peer parallelism:** Replace the sequential peer loop with `asyncio.gather` + semaphore.
4. **Tuning:** Adjust semaphore sizes (e.g. 5 for pre-fetch, 4 for peers) based on API limits and load.
