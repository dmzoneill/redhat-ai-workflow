# Red Hat AI Workflow — 5-Agent Project Analysis

**Date:** 2026-03-06
**Method:** Five parallel analysis agents, each with a distinct perspective (Architecture, Code Quality, Security & Operations, Skills & Workflows, Developer Experience).
**Scope:** Full project at `/home/daoneill/src/redhat-ai-workflow`.

---

## Executive Summary

**redhat-ai-workflow** is an MCP-based “AI-powered development command center” that gives Claude/Cursor tools and workflows for daily dev work (Jira, GitLab, MRs), DevOps (ephemeral deploy, k8s), incidents, and releases. One FastMCP server dynamically loads tools by persona and runs YAML-defined skills; memory and session state persist context across sessions.

**Overall verdict:** The project is well-architected, richly documented, and operationally careful. The main improvement areas are: (1) config and onboarding (config not in Quick Start, missing DEVELOPMENT.md), (2) test coverage scope (server/services excluded from coverage), (3) security hardening (Slack token in config, optional kubeconfig-copy guard), (4) skill/tool discoverability and contribution guides, and (5) reducing coupling and duplication (skill engine ↔ server, duplicated CLI runners, very large files).

---

## Agent 1: Architecture & Design

### Purpose
Single MCP server exposing tools and skills; clients (Cursor, Claude Code) connect over stdio/WebSocket; personas swap tool sets at runtime; skills run multi-step workflows from YAML.

### Main Components
| Layer | Role |
|-------|------|
| **MCP core** (`server/main.py`) | FastMCP server, PersonaLoader, scheduler, WebSocket, memory |
| **Persona loader** | Loads/unloads tool modules from `personas/*.yaml`; CORE_TOOLS always registered |
| **Skill engine** (`aa_workflow/skill_engine.py`) | Runs skills: steps, templating, conditions, on_error (fail/continue/auto_heal), recovery |
| **Tool modules** (`tool_modules/aa_*`) | 27 modules, 435 tools; `register_tools(server)`; tiers: basic, core, extra |
| **Config/state** | `config.json` (projects, credentials, schedules); `state.json` (runtime toggles); `memory/` (YAML) |
| **Daemons** (`services/*`) | Slack, session, cron, meet, etc.; D-Bus IPC |

### Data Flow
1. **Startup:** `main()` → load config → load initial persona → run server (stdio, optional WebSocket).
2. **Persona switch:** `persona_load("devops")` → unload/load modules → emit `tools/list_changed`.
3. **Skill run:** `skill_run(name, inputs)` → load YAML → run steps (tool/compute/then) → template args → handle errors → optional session logging.

### Strengths
- Clear layering; docs in `docs/architecture/` and Mermaid diagrams.
- Rich skill model: steps, templating, conditions, auto_heal, WebSocket progress.
- Extensibility: new tools = new `aa_*` package; new workflows = new YAML; new hat = new persona YAML.

### Risks & Technical Debt
- **FastMCP internals:** Tool listing/debug wrapping use `_components`; may break on FastMCP upgrades.
- **Tight coupling:** `aa_workflow` imports `server.*` (tool_registry, utils, websocket, etc.); skill engine is core behavior inside a tool module.
- **Config/paths:** `load_config()` used from server, tool_modules, services; no single “project root” abstraction.
- **Tool limit:** Personas kept under ~128-tool limit; adding more may require more splitting.
- **State split:** `memory/`, StateManager (`state.json`), WorkspaceRegistry; consistency/recovery semantics could be clarified.

---

## Agent 2: Code Quality & Maintainability

### Strengths
- Clear layout: `server/`, `tool_modules/*/src`, `services/`, `scripts/` with shared `server/utils`, `tool_registry`, `error_patterns`.
- Solid test layout: `tests/` with conftest, skill harness, pytest; skill tests with fixtures and mocks.
- Good docstrings and docs; tech debt tracked in `docs/plans/cleanup.md`.
- Tooling: black, isort, mypy, pytest-cov in pyproject.toml.

### Main Issues
- **Coverage:** `[tool.coverage.run]` only includes `tool_modules` and `scripts`; **server/** and **services/** are excluded** — core runtime is not measured.
- **Duplication:** `run_rh_issue` in both jira tools_basic and tools_extra; `run_git` in multiple git modules; `_run_with_claude_cli` duplicated in scheduler and scheduler_job_runner (~100+ lines each, LM-010 in cleanup.md).
- **Return types:** Mix of `(bool, str)`, `list[TextContent]`, raw strings; no single tool contract.
- **Very large files:** e.g. `session_tools.py` ~2200 lines, `skill_engine.py` ~1430, `skill_error_recovery.py` ~1070.
- **Scripts vs tests:** Some `test_*.py` under `scripts/` blur boundary; lint/type suppressions widespread.

### Recommendations
1. **Include server and services in coverage** in pyproject.toml; add CI coverage gate.
2. **Deduplicate:** Single `run_rh_issue` and `run_git`; extract `_run_with_claude_cli` to shared module (LM-010).
3. **Standardize tool contract:** Document preferred return types and `format_error`/`format_success` usage; align tools over time.
4. **Split large modules:** e.g. session_tools by responsibility; skill_engine into orchestrator + execution/listing/events.
5. **Clarify scripts:** Move one-off/analysis scripts to `scripts/analysis/` or similar; move script-based tests to `tests/` or `tests/scripts/`.

---

## Agent 3: Security & Operations

### Posture
- **config.json:** Gitignored; holds kubeconfig paths, Slack token, token paths. **Risk:** Slack token in plaintext; if file is ever committed or shared, token is exposed.
- **Kubeconfig:** Used by path/env only; no copying in code; docs and rules forbid copying. **Gap:** `cp` is allowed by block-cli; kubeconfig copy is not technically blocked.
- **Namespace ownership:** Bonfire release checks `--mine` before release (unless `force=True`); prevents releasing others’ namespaces.
- **CLI blocking:** block-cli.sh blocks git, kubectl, oc, bonfire, curl, etc.; all `git` is blocked (stronger than only destructive subcommands).

### Recommendations
- Move Slack token to env (e.g. `SLACK_XOXC_TOKEN`) or secret store; keep only a reference in config.
- Add `config.json.example` with placeholders; document that config is local and gitignored.
- Optionally add a hook or check that denies `cp` when target/source matches `*/.kube/config*` (or document that “no kubeconfig copy” is policy-only).

---

## Agent 4: Skills & Workflows

### How It Works
- **Skill engine:** SkillExecutor + TemplateEngineMixin (Jinja2, compute blocks) + ErrorRecoveryMixin (known-issues, auto-heal, retry, soft-failure detection).
- **Skills:** YAML with `name`, `inputs`, `steps` (tool/compute/then/description), conditions, `on_error`; many call `persona_load` early and some switch persona mid-flow.
- **Intent:** Rule-based in `docs/ai-rules/10-skill-first.md` and AGENTS.md; large “User Says” → Skill + inputs tables; no runtime intent API.
- **Multi-agent:** `review_pr_multiagent` runs 6 reviewers (Architecture, Security, Performance, Testing, Documentation, Style) via parallel subprocesses (Claude/Gemini CLI) inside one skill; coordinator step merges output.

### Strengths
- Single place for workflow logic; rich error handling and session/memory integration.
- Intent tables reduce guesswork; persona switching inside skills avoids manual switching.

### Improvements
- **Discoverability:** Add `skill_suggest(intent)` or embedding-based search; intent exists only in docs.
- **Intent coverage:** Keep single source of truth (e.g. skill metadata → generated tables) so new skills are not missing from tables.
- **session_close:** Mandatory in rules but not enforced; consider a lightweight “had activity but no summary” check.
- **Persona/agent wording:** Use “persona” consistently; reserve “agent” for separate actors (e.g. multi-agent reviewers).

---

## Agent 5: Developer Experience & Onboarding

### First-Run
- README Quick Start: clone → configure IDE → restart; uv recommended; use `.venv/bin/python` in IDE to avoid timeout.
- **Gap:** No “create config” step; config.json is not part of Quick Start — users can hit opaque failures.
- **Gap:** README shows direct server command; repo uses mcp_proxy with absolute paths; proxy vs direct not explained.

### Documentation
- **docs/** is rich: architecture, configuration, skills, personas, tool-modules, commands, scripts.
- **Missing:** `docs/DEVELOPMENT.md` is referenced (docs/README, skill-engine) but does not exist — contributor path broken.
- No single “Add a skill” or “Add a tool” guide; procedure inferred from code and plans.

### Recommendations
1. **Quick Start:** Add step: copy `config.json.example` to `config.json` and set at least one repo and `user`; optionally add “Minimal config” doc.
2. **DEVELOPMENT.md:** Add it (or fix links) with: dev install, run server, `make test` / `make test-skills` / `make validate-skills`, `make sync-ai-rules` after editing ai-rules.
3. **Contribution guides:** One “Add a skill” and one “Add a tool” doc (or sections) with steps and validation commands.
4. **IDE/MCP:** One place (README or docs/ide-mcp-setup.md) for proxy vs direct, absolute paths, “run uv sync once,” and common issues (timeout, server not starting, Reload Window).
5. **CONTRIBUTING.md:** Branch naming, run `make test` and `make validate-skills`, `make sync-ai-rules` if ai-rules changed; link to DEVELOPMENT and MR process.

---

## Cross-Cutting Themes

| Theme | Agent 1 | Agent 2 | Agent 3 | Agent 4 | Agent 5 |
|-------|---------|---------|---------|---------|---------|
| **Config** | Single source of truth | — | Token/path handling | — | Not in Quick Start; minimal config story |
| **Docs** | Architecture strong | Reference + cleanup.md | Safety rules clear | Intent tables | DEVELOPMENT.md missing; add-skill/add-tool guides |
| **Testing** | — | Coverage excludes server/services; duplication | — | — | make test/sync-ai-rules not in Contributing |
| **Coupling / size** | Skill engine ↔ server | Large files; duplicated runners | — | — | — |
| **Safety** | — | — | Slack token; kubeconfig copy | session_close not enforced | — |

---

## Prioritized Action List

1. **High:** Add config step to Quick Start; add or fix DEVELOPMENT.md; include server/services in coverage.
2. **High:** Move Slack token out of config (env or secret store); add config.json.example with placeholders.
3. **Medium:** Document “Add a skill” and “Add a tool”; add CONTRIBUTING.md with test/sync-ai-rules; unify IDE/MCP pitfalls in one place.
4. **Medium:** Deduplicate `_run_with_claude_cli`, `run_rh_issue`, `run_git`; standardize tool return contract.
5. **Lower:** Split largest modules (session_tools, skill_engine); optional kubeconfig-copy hook; skill discoverability (e.g. skill_suggest); session_close compliance check.

---

*This analysis was produced by five parallel explore agents. For full agent outputs, re-run the individual agent tasks or inspect the synthesis above.*
