"""Tests for the aa_code_search split modules (chunking, indexing, search and tool output)."""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd
import pytest

from tool_modules.aa_code_search.src import (
    cs_chunking,
    cs_config,
    cs_index,
    cs_search,
    cs_tool_impls,
    tools_basic,
)


class _Vector(list):
    """One embedding row with numpy's tolist()."""

    def tolist(self):
        """Return the row as a plain list."""
        return list(self)


class _Matrix(list):
    """Embedding matrix with numpy's tolist()."""

    def tolist(self):
        """Return the rows as plain lists."""
        return [list(row) for row in self]


@dataclass
class _Model:
    """Deterministic embedder."""

    def encode(self, texts):
        """Embed each text as a 2-d vector."""
        return _Matrix(_Vector([float(len(t) % 7), 1.0]) for t in texts)


class _Query:
    """LanceDB query builder stand-in."""

    def __init__(self, rows):
        self.rows = rows
        self.count = 0

    def limit(self, count):
        """Record the limit."""
        self.count = count
        return self

    def nprobes(self, _count):
        """Accept nprobes."""
        return self

    def to_pandas(self):
        """Return the first rows with increasing distances."""
        frame = pd.DataFrame(self.rows[: self.count]).drop(columns=["vector"])
        frame["_distance"] = [0.2 * i for i in range(len(frame))]
        return frame


class _Table:
    """In-memory LanceDB table."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.indexes = []

    def search(self, _vector):
        """Start a query."""
        return _Query(self.rows)

    def add(self, rows):
        """Append rows."""
        self.rows += rows

    def to_pandas(self):
        """All rows as a DataFrame."""
        return pd.DataFrame(self.rows)

    def create_index(self, **options):
        """Record index creation."""
        self.indexes.append(options)

    def optimize(self, **_options):
        """No-op optimize."""

    def __len__(self):
        return len(self.rows)


class _DB:
    """In-memory LanceDB database."""

    def __init__(self):
        self.tables = {}

    def table_names(self):
        """Names of the tables."""
        return list(self.tables)

    def create_table(self, name, data, mode):
        """Create (overwrite) a table."""
        assert mode == "overwrite"
        self.tables[name] = _Table(data)
        return self.tables[name]

    def open_table(self, name):
        """Open a table."""
        return self.tables[name]


def _p(module, name):
    """Private helper ``name`` of ``module``."""
    return vars(module)[name]


@pytest.fixture(name="env")
def fixture_env(tmp_path, monkeypatch):
    """A project of Python files with in-memory LanceDB and a fake embedder."""
    project = tmp_path / "proj"
    project.mkdir()
    for i in range(3):
        (project / f"m{i}.py").write_text(f"# m{i}\ndef f{i}():\n    return {i}\n", encoding="utf-8")
    (project / ".hidden.py").write_text("x = 1\n", encoding="utf-8")
    config = {"repositories": {"p": {"path": str(project)}}}
    db = _DB()

    monkeypatch.setattr(cs_config, "VECTOR_DB_PATH", tmp_path / "vectors")
    monkeypatch.setattr(cs_config, "_load_config", lambda: config)
    for module in (cs_index, cs_search, cs_tool_impls):
        monkeypatch.setattr(module, "_get_lance_db", lambda _project: db)
    for module in (cs_index, cs_search):
        monkeypatch.setattr(module, "_get_embedding_model", _Model)
    return SimpleNamespace(project=project, db=db)


def _text(result):
    """Text of a single-item tool result."""
    assert len(result) == 1
    return result[0].text


def test_format_size():
    """Sizes are shown in B, KB or MB."""
    assert _p(cs_config, "_format_size")(12) == "12 B"
    assert _p(cs_config, "_format_size")(2048) == "2.0 KB"
    assert _p(cs_config, "_format_size")(3 * 1024 * 1024) == "3.0 MB"


def test_chunk_python_code_splits_definitions():
    """Top-level definitions become chunks; module code before them is kept."""
    content = "import os\n\nclass A:\n    pass\n\nasync def g():\n    pass\n"
    chunks = _p(cs_chunking, "_chunk_python_code")(content, "m.py")
    assert [(c["type"], c["name"], c["start_line"], c["end_line"]) for c in chunks] == [
        ("module", "module", 1, 2),
        ("class", "A", 3, 5),
        ("async_function", "g", 6, 8),
    ]


def test_chunk_by_size_overlaps_and_labels():
    """Large content is split with overlapping lines and keeps the label."""
    label = cs_chunking.ChunkLabel("a.go", "go", "function", "big")
    chunks = _p(cs_chunking, "_chunk_by_size")("\n".join("x" * 99 for _ in range(40)), label, base_line=10)
    assert len(chunks) > 1
    assert {(c["type"], c["name"], c["language"]) for c in chunks} == {("function", "big", "go")}
    assert chunks[0]["start_line"] == 10


def test_should_index_file_rules(tmp_path):
    """Hidden, vendored and non-code files are skipped."""
    assert _p(cs_chunking, "_should_index_file")(tmp_path / "a.py", tmp_path)
    assert not _p(cs_chunking, "_should_index_file")(tmp_path / ".x" / "a.py", tmp_path)
    assert not _p(cs_chunking, "_should_index_file")(tmp_path / "node_modules" / "a.js", tmp_path)
    assert not _p(cs_chunking, "_should_index_file")(tmp_path / "a.txt", tmp_path)


def test_index_then_incremental_update(env):
    """A second run skips unchanged files and re-embeds only the changed one."""
    stats = _p(cs_index, "_index_project")("p")
    assert (stats["files_indexed"], stats["files_skipped"], stats["index_type"]) == (3, 0, "FLAT")
    (env.project / "m1.py").write_text("# m1\ndef changed():\n    pass\n", encoding="utf-8")
    stats = _p(cs_index, "_index_project")("p")
    assert (stats["files_indexed"], stats["files_skipped"]) == (1, 2)
    names = sorted(row["name"] for row in env.db.tables["code_p"].rows if row["type"] == "function")
    assert names == ["changed", "f0", "f2"]


def test_ann_index_options(monkeypatch):
    """IVF-PQ indexes cap partitions by row count and sub-vectors by dimension."""
    monkeypatch.setattr(cs_index, "_get_vector_search_config", lambda: {"num_sub_vectors": 999})
    table = _Table([])
    stats = {}
    _p(cs_index, "_create_ann_index")(table, 1000, stats)
    assert table.indexes == [
        {"metric": "cosine", "num_partitions": 100, "index_type": "IVF_PQ", "num_sub_vectors": 384}
    ]
    assert stats["index_type"] == "IVF_PQ"


@pytest.mark.usefixtures("env")
def test_search_code_keyword_options():
    """Search accepts keyword options, filters and records stats."""
    _p(cs_index, "_index_project")("p")
    results = _p(cs_search, "_search_code")(query="q", project="p", limit=2, auto_update=False)
    assert [r["similarity"] for r in results] == [1.0, 0.9]
    filtered = _p(cs_search, "_search_code")("q", "p", file_filter="m2", auto_update=False)
    assert {r["file_path"] for r in filtered} == {"m2.py"}
    assert _p(cs_search, "_get_index_stats")("p")["search_count"] == 2


@pytest.mark.usefixtures("env")
def test_search_code_not_indexed():
    """Searching an unindexed project returns an error entry."""
    assert "not indexed" in _p(cs_search, "_search_code")("q", "p", auto_update=False)[0]["error"]


@pytest.mark.usefixtures("env")
def test_tool_impls_output():
    """Tool implementations format index, search, stats and compact results."""
    assert "Indexed p" in _text(asyncio.run(_p(cs_tool_impls, "_code_index_impl")()))
    assert "### 1. `m" in _text(asyncio.run(_p(cs_tool_impls, "_code_search_impl")("q")))
    assert "### ✅ p" in _text(asyncio.run(_p(cs_tool_impls, "_code_stats_impl")()))
    assert "**Total space saved:** 0 B" in _text(asyncio.run(_p(cs_tool_impls, "_code_compact_impl")()))
    assert "not found" in _text(asyncio.run(_p(cs_tool_impls, "_code_compact_impl")("zz")))


@pytest.mark.usefixtures("env")
def test_deep_scan_update_memory_flag():
    """update_memory controls the knowledge_update() instructions."""
    with_memory = _text(asyncio.run(_p(cs_tool_impls, "_knowledge_deep_scan_impl")("p")))
    without = _text(asyncio.run(_p(cs_tool_impls, "_knowledge_deep_scan_impl")("p", update_memory=False)))
    assert 'knowledge_update("p", "developer", "gotchas", "- issue: X\\n' in with_memory
    assert "knowledge_update" not in without
    assert "Claude Analysis Instructions" in without


@pytest.mark.usefixtures("env")
def test_code_watch_argument_checks():
    """code_watch validates the project and the action."""
    assert "Please specify" in _text(asyncio.run(_p(cs_tool_impls, "_code_watch_impl")()))
    assert "Unknown action" in _text(asyncio.run(_p(cs_tool_impls, "_code_watch_impl")("p", "bogus")))
    assert "No active watcher" in _text(asyncio.run(_p(cs_tool_impls, "_code_watch_impl")("p", "stop")))


def test_tools_basic_reexports():
    """tools_basic keeps exporting the helpers other modules import."""
    assert _p(tools_basic, "_search_code") is _p(cs_search, "_search_code")
    assert _p(tools_basic, "_get_index_stats") is _p(cs_search, "_get_index_stats")
    assert tools_basic.get_vector_health is cs_search.get_vector_health
    assert set(tools_basic.__all__) <= set(vars(tools_basic))
