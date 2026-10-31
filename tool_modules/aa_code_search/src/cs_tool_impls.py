"""Implementations behind the code search MCP tools (formatting of tool output)."""

import logging
from datetime import timedelta

from mcp.types import TextContent

from tool_modules.aa_code_search.src import cs_config
from tool_modules.aa_code_search.src.cs_config import (
    _INDEX_ERRORS,
    _configured_projects,
    _format_size,
    _get_project_path,
    _get_table_name,
)
from tool_modules.aa_code_search.src.cs_embeddings import _embedding_cache, _get_lance_db
from tool_modules.aa_code_search.src.cs_index import _index_project
from tool_modules.aa_code_search.src.cs_search import (
    _get_index_stats,
    _search_code,
    get_all_vector_stats,
    get_vector_health,
)
from tool_modules.aa_code_search.src.watcher import (
    get_all_watchers,
    get_watcher,
    start_watcher,
    stop_all_watchers,
    stop_watcher,
)

logger = logging.getLogger(__name__)

_MISSING_LANCEDB = "\n\nInstall with:\n```\nuv add lancedb sentence-transformers\n```"

_DEEP_SCAN_QUERIES = (
    ("API routes and endpoints", "api"),
    ("Database models and schemas", "models"),
    ("Authentication and authorization", "auth"),
    ("Error handling and exceptions", "errors"),
    ("Configuration and settings", "config"),
    ("Background tasks and workers", "tasks"),
    ("Data validation and input checking", "validation"),
    ("External service integrations", "integrations"),
    ("Logging and monitoring", "logging"),
    ("Testing patterns and fixtures", "testing"),
)

_DEEP_SCAN_MEMORY_INSTRUCTIONS = """
Then use `knowledge_update()` to save findings to memory:

```python
knowledge_update("PROJECT", "developer", "architecture.overview", "Your summary...")
knowledge_update("PROJECT", "developer", "gotchas", "- issue: X\\n  reason: Y\\n  solution: Z")
```
"""


def _text(text: str) -> list[TextContent]:
    """Wrap text as a single MCP text result."""
    return [TextContent(type="text", text=text)]


def _default_project(project: str) -> tuple[str, list[TextContent] | None]:
    """Return ``project``, or the only configured project, or an error result."""
    if project:
        return project, None
    projects = _configured_projects()
    if len(projects) == 1:
        return projects[0], None
    return "", _text(f"❌ Please specify a project. Available: {', '.join(projects)}")


def _index_summary(project: str, stats: dict) -> str:
    """Markdown summary of an indexing run."""
    index_info = f"- Index type: **{stats.get('index_type', 'FLAT')}**"
    if stats.get("num_partitions"):
        index_info += f" ({stats['num_partitions']} partitions)"
    if stats.get("index_time_ms"):
        index_info += f"\n- Index build time: {stats['index_time_ms']:.0f}ms"
    if stats.get("index_note"):
        index_info += f"\n- Note: {stats['index_note']}"

    result = f"""✅ **Indexed {project}**

📊 **Statistics:**
- Files indexed: {stats["files_indexed"]}
- Files skipped (unchanged): {stats["files_skipped"]}
- Code chunks created: {stats["chunks_created"]}
{index_info}
"""
    if stats["errors"]:
        err_lines = [f"- {err}" for err in stats["errors"][:5]]
        if len(stats["errors"]) > 5:
            err_lines.append(f"- ... and {len(stats['errors']) - 5} more")
        result += f"\n⚠️ **Errors ({len(stats['errors'])}):**\n" + "\n".join(err_lines) + "\n"

    result += f"\n💡 Now use `code_search('{project}', 'your query')` to search semantically."
    result += "\n🏥 Use `code_health()` to check performance metrics."
    return result


async def _code_index_impl(
    project: str = "",
    force: bool = False,
) -> list[TextContent]:
    """Implementation of the code_index tool."""
    project, error = _default_project(project)
    if error:
        return error

    try:
        stats = _index_project(project, force=force)
        if "error" in stats:
            return _text(f"❌ {stats['error']}")
        return _text(_index_summary(project, stats))

    except ImportError as e:
        return _text(f"❌ Missing dependency: {e}{_MISSING_LANCEDB}")
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        return _text(f"❌ Indexing failed: {e}")


def _search_result_section(i: int, result: dict) -> str:
    """Markdown for one search hit (content truncated to 800 characters)."""
    content = result["content"]
    if len(content) > 800:
        content = content[:800] + "\n... (truncated)"
    return (
        f"### {i}. `{result['file_path']}` "
        f"(lines {result['start_line']}-{result['end_line']})\n"
        f"**Type:** {result['type']} | **Name:** {result['name']}"
        f" | **Relevance:** {result['similarity']:.0%}\n\n"
        f"```{result['language']}\n{content}\n```\n"
    )


async def _code_search_impl(
    query: str,
    project: str = "",
    limit: int = 10,
    file_filter: str = "",
    type_filter: str = "",
) -> list[TextContent]:
    """Implementation of the code_search tool."""
    project, error = _default_project(project)
    if error:
        return error

    try:
        results = _search_code(
            query=query,
            project=project,
            limit=limit,
            file_filter=file_filter,
            type_filter=type_filter,
        )

        if not results:
            return _text(
                f"No results found for: {query}\n\nTry a different query or "
                f"check if the project is indexed with `code_stats('{project}')`"
            )

        if "error" in results[0]:
            return _text(f"❌ {results[0]['error']}")

        parts = [f'## 🔍 Search Results for: "{query}"\n']
        parts.extend(_search_result_section(i, result) for i, result in enumerate(results, 1))
        return _text("\n".join(parts))

    except ImportError as e:
        return _text(f"❌ Missing dependency: {e}{_MISSING_LANCEDB}")
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        return _text(f"❌ Search failed: {e}")


def _project_stats_section(proj: str, stats: dict) -> str:
    """Markdown table for one indexed project in code_stats."""
    stale_indicator = "⚠️ STALE" if stats.get("is_stale") else ""
    watcher = get_watcher(proj)
    watcher_indicator = "👁️" if watcher and watcher.is_running else ""

    output = f"### ✅ {proj} {stale_indicator} {watcher_indicator}\n\n"
    output += "| Metric | Value |\n"
    output += "|--------|-------|\n"
    output += f"| **Files** | {stats.get('files_total', 0)} indexed |\n"
    output += f"| **Chunks** | {stats.get('chunks_count', 0):,} |\n"
    output += f"| **Disk Size** | {stats.get('disk_size', '0 B')} |\n"
    output += f"| **Last Indexed** | {stats.get('index_age', 'Unknown')} |\n"
    output += f"| **Model** | `{stats.get('embedding_model', 'unknown')}` |\n"

    if stats.get("search_count", 0) > 0:
        output += f"| **Searches** | {stats.get('search_count', 0):,} total |\n"
        output += f"| **Avg Search Time** | {stats.get('avg_search_time_ms', 0):.0f}ms |\n"

    if watcher:
        ws = watcher.status
        output += f"| **Watcher** | {'🟢 Active' if ws['running'] else '🔴 Stopped'} |\n"
        if ws.get("changes_pending", 0) > 0:
            output += f"| **Pending Changes** | {ws['changes_pending']} |\n"

    return output + "\n"


async def _code_stats_impl(
    project: str = "",
) -> list[TextContent]:
    """Implementation of the code_stats tool."""
    projects = _configured_projects()
    if project:
        projects = [project] if project in projects else []

    if not projects:
        return _text(f"❌ Project '{project}' not found in config.json")

    output = "## 📊 Code Index Statistics\n\n"
    total_chunks = 0
    total_size_bytes = 0
    total_searches = 0

    for proj in projects:
        stats = _get_index_stats(proj)
        if stats.get("indexed"):
            total_chunks += stats.get("chunks_count", 0)
            total_size_bytes += stats.get("disk_size_bytes", 0)
            total_searches += stats.get("search_count", 0)
            output += _project_stats_section(proj, stats)
        else:
            output += f"### ❌ {proj} (not indexed)\n"
            output += f"Run `code_index('{proj}')` to index.\n\n"

    # Overall summary if multiple projects
    if len(projects) > 1:
        output += "---\n\n"
        output += f"**Total:** {total_chunks:,} chunks, {_format_size(total_size_bytes)}, {total_searches:,} searches\n"

    return _text(output)


def _lance_files(proj: str) -> list:
    """The project's ``*.lance`` data files."""
    return list((cs_config.vector_db_path() / proj).rglob("*.lance"))


def _compact_project(proj: str) -> tuple[str, int]:
    """Optimize one project's table. Returns (report line, bytes saved)."""
    db = _get_lance_db(proj)
    table_name = _get_table_name(proj)
    if table_name not in db.table_names():
        return f"⏭️ **{proj}**: Not indexed (skipped)", 0

    table = db.open_table(table_name)
    before = _lance_files(proj)
    size_before = sum(f.stat().st_size for f in before)

    # Optimize - remove all old versions
    table.optimize(cleanup_older_than=timedelta(days=0))

    after = _lance_files(proj)
    saved = size_before - sum(f.stat().st_size for f in after)
    if saved > 0:
        return f"✅ **{proj}**: {len(before)} → {len(after)} files, saved {_format_size(saved)}", saved
    return f"✅ **{proj}**: Already optimized ({len(after)} files)", saved


async def _code_compact_impl(
    project: str = "",
) -> list[TextContent]:
    """Implementation of the code_compact tool."""
    projects = _configured_projects()
    if project:
        if project not in projects:
            return _text(f"❌ Project '{project}' not found in config.json")
        projects = [project]

    results = []
    total_saved = 0
    for proj in projects:
        try:
            line, saved = _compact_project(proj)
        # Intentional: log the failure and continue at this boundary.
        except _INDEX_ERRORS as e:
            line, saved = f"❌ **{proj}**: {e}", 0
        results.append(line)
        total_saved += saved

    output = "## 🗜️ Vector Database Optimization\n\n"
    output += "\n".join(results)
    output += f"\n\n**Total space saved:** {_format_size(total_saved)}"
    return _text(output)


async def _knowledge_deep_scan_impl(project: str, update_memory: bool = True) -> list[TextContent]:
    """Implementation of the knowledge_deep_scan tool.

    With ``update_memory`` the output ends with instructions to save the findings
    via ``knowledge_update()``; without it, only the analysis is requested.
    """
    stats = _get_index_stats(project)
    if not stats.get("indexed"):
        index_result = _index_project(project)
        if "error" in index_result:
            return _text(f"❌ {index_result['error']}")
        stats = _get_index_stats(project)

    findings = {}
    for query, key in _DEEP_SCAN_QUERIES:
        try:
            results = _search_code(query, project, limit=5)
            if results and "error" not in results[0]:
                findings[key] = results
        # Intentional: log the failure and continue at this boundary.
        except _INDEX_ERRORS as exc:
            logger.debug("Suppressed error: %s", exc)

    output = f"""## 🔬 Deep Scan Results: {project}

**Indexed:** {stats.get("chunks_count", 0)} code chunks from {stats.get("file_count", 0)} files

---

### 📋 Findings by Category

"""

    for key, results in findings.items():
        category_lines = [f"#### {key.replace('_', ' ').title()}\n"]
        for r in results[:3]:  # Top 3 per category
            category_lines.append(
                f"- `{r['file_path']}:{r['start_line']}` - {r['type']} `{r['name']}` ({r['similarity']:.0%} match)"
            )
        output += "\n".join(category_lines) + "\n\n"

    output += """---

### 🧠 Claude Analysis Instructions

Based on these findings, please:

1. **Summarize the architecture** - How is the system structured?
2. **Identify key modules** - What are the important directories?
3. **Document patterns** - What coding/testing/deployment patterns are used?
4. **Note gotchas** - Any non-obvious behaviors or potential issues?
"""
    if update_memory:
        output += _DEEP_SCAN_MEMORY_INSTRUCTIONS

    return _text(output.replace("PROJECT", project))


def _watch_status() -> list[TextContent]:
    """Markdown status of all active watchers."""
    watchers = get_all_watchers()
    if not watchers:
        return _text("## 👁️ Code Watchers\n\nNo active watchers.\n\nStart one with `code_watch('project', 'start')`")

    watcher_parts = ["## 👁️ Code Watchers\n"]
    for proj, watcher in watchers.items():
        status = watcher.status
        icon = "🟢" if status["running"] else "🔴"
        watcher_parts.append(
            f"### {icon} {proj}\n"
            f"- **Running:** {status['running']}\n"
            f"- **Last update:** {status['last_update'] or 'Never'}\n"
            f"- **Pending changes:** {status['changes_pending']}\n"
            f"- **Debounce:** {status['debounce_seconds']}s\n"
        )
    return _text("\n".join(watcher_parts))


async def _watch_start(project: str, project_path, debounce_seconds: float) -> list[TextContent]:
    """Start a watcher for an indexed project."""
    try:
        if not _get_index_stats(project).get("indexed"):
            return _text(f"❌ Project '{project}' not indexed. Run `code_index('{project}')` first.")

        await start_watcher(
            project=project,
            project_path=project_path,
            index_func=_index_project,
            debounce_seconds=debounce_seconds,
        )
        return _text(f"""✅ **Started watching {project}**

📁 Path: `{project_path}`
⏱️ Debounce: {debounce_seconds}s (waits for quiet period before re-indexing)

The index will automatically update when you save files.
Use `code_watch(action='status')` to check watcher status.
Use `code_watch('{project}', 'stop')` to stop watching.
""")

    except ImportError as e:
        return _text(f"❌ Missing dependency: {e}\n\nInstall with:\n```\nuv add watchfiles\n```")
    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        return _text(f"❌ Failed to start watcher: {e}")


async def _code_watch_impl(
    project: str = "",
    action: str = "start",
    debounce_seconds: float = 5.0,
) -> list[TextContent]:
    """Implementation of the code_watch tool."""
    if action == "status":
        return _watch_status()

    if not project:
        return _text(f"❌ Please specify a project. Available: {', '.join(_configured_projects())}")

    project_path = _get_project_path(project)
    if not project_path or not project_path.exists():
        return _text(f"❌ Project path not found: {project}")

    if action == "start":
        return await _watch_start(project, project_path, debounce_seconds)

    if action == "stop":
        stopped = await stop_watcher(project)
        return _text(f"✅ Stopped watching {project}" if stopped else f"⚠️ No active watcher for {project}")

    return _text(f"❌ Unknown action: {action}. Use 'start', 'stop', or 'status'.")


async def _start_watcher_line(project: str, debounce_seconds: float) -> str:
    """Start one project's watcher for code_watch_all and report the outcome."""
    project_path = _get_project_path(project)
    if not project_path or not project_path.exists():
        return f"⚠️ {project}: path not found"

    if not _get_index_stats(project).get("indexed"):
        return f"⚠️ {project}: not indexed (run code_index first)"

    try:
        await start_watcher(
            project=project,
            project_path=project_path,
            index_func=_index_project,
            debounce_seconds=debounce_seconds,
        )
        return f"✅ {project}: watching"
    # Intentional: log the failure and continue at this boundary.
    except _INDEX_ERRORS as e:
        return f"❌ {project}: {e}"


async def _code_watch_all_impl(
    action: str = "start",
    debounce_seconds: float = 5.0,
) -> list[TextContent]:
    """Implementation of the code_watch_all tool."""
    projects = _configured_projects()

    if action == "start":
        results = [await _start_watcher_line(project, debounce_seconds) for project in projects]
        output = "## 👁️ Started Watchers\n\n"
        output += "\n".join(results)
        output += f"\n\n**Debounce:** {debounce_seconds}s"
        return _text(output)

    if action == "stop":
        count = await stop_all_watchers()
        return _text(f"✅ Stopped {count} watcher(s)")

    return _text(f"❌ Unknown action: {action}. Use 'start' or 'stop'.")


async def _code_health_impl() -> list[TextContent]:
    """Implementation of the code_health tool."""
    try:
        health = get_vector_health()
        stats = get_all_vector_stats()

        # Status emoji
        status_emoji = {
            "healthy": "🟢",
            "degraded": "🟡",
            "unhealthy": "🔴",
        }.get(health["status"], "⚪")

        output = f"""## 🏥 Vector Search Health

### Status: {status_emoji} {health["status"].upper()}

---

### 📊 Performance Metrics

| Metric | Value |
|--------|-------|
| **Indexed Projects** | {health["metrics"]["indexed_projects"]} |
| **Total Vectors** | {health["metrics"]["total_vectors"]:,} |
| **Avg Search Time** | {health["metrics"]["avg_search_time_ms"]:.1f}ms |
| **Cache Hit Rate** | {health["metrics"]["cache_hit_rate"]} |

---

### ⚙️ Configuration

| Setting | Value |
|---------|-------|
| **Index Type** | {stats["config"]["index_type"]} |
| **nprobes** | {stats["config"]["nprobes"]} |
| **Embedding Model** | `{stats["config"]["embedding_model"]}` |
| **Embedding Backend** | {stats["config"]["embedding_backend"]} |
| **Cache Enabled** | {stats["config"]["cache_enabled"]} |

---

### 🔄 Cache Status

| Metric | Value |
|--------|-------|
| **Cache Size** | {stats["cache"]["size"]} / {stats["cache"]["max_size"]} |
| **Session Hit Rate** | {stats["cache"]["hit_rate"]} |
| **Total Hits** | {stats["cache"]["hits"]} |
| **Total Misses** | {stats["cache"]["misses"]} |

"""

        if health["issues"]:
            issue_lines = [f"- {issue}" for issue in health["issues"]]
            output += "---\n\n### ⚠️ Issues\n\n" + "\n".join(issue_lines) + "\n\n"

        if health["recommendations"]:
            rec_lines = [f"- {rec}" for rec in health["recommendations"]]
            output += "---\n\n### 💡 Recommendations\n\n" + "\n".join(rec_lines) + "\n\n"

        return [TextContent(type="text", text=output)]

    # Intentional: convert the failure into an error result for the caller.
    except _INDEX_ERRORS as e:
        return [TextContent(type="text", text=f"❌ Health check failed: {e}")]


async def _code_cache_impl(
    action: str = "stats",
) -> list[TextContent]:
    """Implementation of the code_cache tool."""
    if action == "clear":
        _embedding_cache.clear()
        return [TextContent(type="text", text="✅ Embedding cache cleared")]

    stats = _embedding_cache.stats()

    output = f"""## 🗄️ Embedding Cache

| Metric | Value |
|--------|-------|
| **Size** | {stats["size"]} / {stats["max_size"]} |
| **Hit Rate** | {stats["hit_rate"]} |
| **Hits** | {stats["hits"]} |
| **Misses** | {stats["misses"]} |

💡 Cache stores query embeddings to speed up repeated searches.
Use `code_cache('clear')` to clear the cache.
"""

    return [TextContent(type="text", text=output)]
